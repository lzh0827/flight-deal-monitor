from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import requests

from ..models import Candidate, FlightDeal


class AmadeusClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        environment: str,
        timeout: int,
        session: requests.Session,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = (
            "https://api.amadeus.com"
            if environment == "production"
            else "https://test.api.amadeus.com"
        )
        self.environment = environment
        self.timeout = timeout
        self.session = session
        self._access_token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    def _token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and now < self._token_expires_at:
            return self._access_token
        response = self.session.post(
            f"{self.base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 1200))
        self._token_expires_at = now + timedelta(seconds=max(60, expires_in - 60))
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def discover(
        self,
        origin: str,
        start: date,
        end: date,
        max_price: Decimal,
        currency: str,
    ) -> list[Candidate]:
        response = self.session.get(
            f"{self.base_url}/v1/shopping/flight-destinations",
            headers=self._headers(),
            params={
                "origin": origin,
                "departureDate": f"{start.isoformat()},{end.isoformat()}",
                "oneWay": "true",
                "maxPrice": str(max_price),
                "currency": currency,
                "viewBy": "DESTINATION",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        candidates: list[Candidate] = []
        for item in response.json().get("data", []):
            try:
                departure = date.fromisoformat(item["departureDate"])
                price = Decimal(str(item["price"]["total"]))
                destination = str(item["destination"]).upper()
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue
            if start <= departure <= end and price <= max_price:
                candidates.append(
                    Candidate(origin, destination, departure, price, "Amadeus缓存")
                )
        return candidates

    def verify(
        self,
        candidate: Candidate,
        adults: int,
        max_total: Decimal,
        max_per_adult: Decimal,
        currency: str,
        discovery_sources: tuple[str, ...],
    ) -> FlightDeal | None:
        response = self.session.get(
            f"{self.base_url}/v2/shopping/flight-offers",
            headers=self._headers(),
            params={
                "originLocationCode": candidate.origin,
                "destinationLocationCode": candidate.destination,
                "departureDate": candidate.departure_date.isoformat(),
                "adults": adults,
                "travelClass": "ECONOMY",
                "currencyCode": currency,
                "maxPrice": str(max_total),
                "max": 10,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        qualifying: list[dict[str, Any]] = []
        for offer in response.json().get("data", []):
            if self._offer_qualifies(offer, adults, max_total, max_per_adult, currency):
                qualifying.append(offer)
        if not qualifying:
            return None
        qualifying.sort(key=lambda x: Decimal(str(x["price"].get("grandTotal", x["price"]["total"]))))

        # Flight Offers Price is the official final availability/price confirmation step.
        confirmed = self._confirm_price(qualifying[0])
        if not self._offer_qualifies(
            confirmed, adults, max_total, max_per_adult, currency
        ):
            return None
        return self._to_deal(confirmed, adults, discovery_sources)

    def _confirm_price(self, offer: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/v1/shopping/flight-offers/pricing",
            headers={**self._headers(), "X-HTTP-Method-Override": "GET"},
            json={
                "data": {
                    "type": "flight-offers-pricing",
                    "flightOffers": [offer],
                }
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        offers = response.json().get("data", {}).get("flightOffers", [])
        if not offers:
            raise RuntimeError("Amadeus 最终询价没有返回航班")
        return offers[0]

    @staticmethod
    def _offer_qualifies(
        offer: dict[str, Any],
        adults: int,
        max_total: Decimal,
        max_per_adult: Decimal,
        currency: str,
    ) -> bool:
        try:
            price = offer["price"]
            if str(price["currency"]).upper() != currency:
                return False
            total = Decimal(str(price.get("grandTotal", price["total"])))
            if total > max_total:
                return False
            seats = int(offer.get("numberOfBookableSeats", adults))
            if seats < adults:
                return False
            traveler_prices = [
                Decimal(str(item["price"]["total"]))
                for item in offer.get("travelerPricings", [])
                if item.get("travelerType") == "ADULT"
            ]
            if traveler_prices:
                if len(traveler_prices) != adults:
                    return False
                if any(value > max_per_adult for value in traveler_prices):
                    return False
            else:
                if total / adults > max_per_adult:
                    return False
            return True
        except (KeyError, TypeError, ValueError, InvalidOperation, ZeroDivisionError):
            return False

    @staticmethod
    def _baggage_text(offer: dict[str, Any]) -> str:
        allowances: list[str] = []
        for traveler in offer.get("travelerPricings", []):
            for detail in traveler.get("fareDetailsBySegment", []):
                bag = detail.get("includedCheckedBags") or {}
                if int(bag.get("quantity", 0) or 0) > 0:
                    allowances.append(f"{int(bag['quantity'])}件")
                elif int(bag.get("weight", 0) or 0) > 0:
                    allowances.append(
                        f"{int(bag['weight'])}{bag.get('weightUnit', 'KG').lower()}"
                    )
                else:
                    allowances.append("无托运行李或未提供")
        if not allowances:
            return "无托运行李或数据源未提供"
        unique = list(dict.fromkeys(allowances))
        return "、".join(unique)

    @classmethod
    def _to_deal(
        cls,
        offer: dict[str, Any],
        adults: int,
        discovery_sources: tuple[str, ...],
    ) -> FlightDeal:
        itinerary = offer["itineraries"][0]
        segments = itinerary["segments"]
        first, last = segments[0], segments[-1]
        origin = first["departure"]["iataCode"]
        destination = last["arrival"]["iataCode"]
        departure_at = datetime.fromisoformat(first["departure"]["at"])
        arrival_at = datetime.fromisoformat(last["arrival"]["at"])
        flight_numbers = tuple(
            f"{segment['carrierCode']}{segment['number']}" for segment in segments
        )
        total = Decimal(
            str(offer["price"].get("grandTotal", offer["price"]["total"]))
        )
        travel_query = quote(
            f"Flights from {origin} to {destination} on "
            f"{departure_at.date().isoformat()} for 2 adults"
        )
        ctrip = (
            "https://flights.ctrip.com/online/list/oneway-"
            f"{origin.lower()}-{destination.lower()}?depdate="
            f"{departure_at.date().isoformat()}&adult=2&child=0&infant=0"
        )
        return FlightDeal(
            origin=origin,
            destination=destination,
            departure_at=departure_at,
            arrival_at=arrival_at,
            flight_numbers=flight_numbers,
            total_price=total,
            price_per_adult=total / adults,
            currency=str(offer["price"]["currency"]).upper(),
            adults=adults,
            baggage=cls._baggage_text(offer),
            stops=max(0, len(segments) - 1),
            validating_airlines=tuple(offer.get("validatingAirlineCodes", [])),
            discovery_sources=discovery_sources,
            booking_url=ctrip,
            comparison_url=f"https://www.google.com/travel/flights?q={travel_query}",
        )

