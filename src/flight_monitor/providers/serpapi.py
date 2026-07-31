from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import requests

from ..models import RoundTripDeal


class SerpApiGoogleFlights:
    endpoint = "https://serpapi.com/search.json"

    def __init__(
        self, api_key: str, timeout: int, session: requests.Session
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = session

    def search_roundtrip(
        self,
        origins: tuple[str, ...],
        destinations: tuple[str, ...],
        outbound_date: date,
        return_date: date,
        adults: int,
        currency: str,
    ) -> list[RoundTripDeal]:
        response = self.session.get(
            self.endpoint,
            params={
                "engine": "google_flights",
                "api_key": self.api_key,
                "departure_id": ",".join(origins),
                "arrival_id": ",".join(destinations),
                "outbound_date": outbound_date.isoformat(),
                "return_date": return_date.isoformat(),
                "adults": adults,
                "currency": currency,
                "hl": "zh-cn",
                "gl": "cn",
                "type": 1,
                "travel_class": 1,
                "sort_by": 2,
                "stops": 0,
            },
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.ok:
            message = payload.get("error") or f"HTTP {response.status_code}"
            raise RuntimeError(f"SerpApi Google Flights 查询失败: {message}")
        if payload.get("error"):
            raise RuntimeError(f"SerpApi Google Flights 查询失败: {payload['error']}")
        comparison_url = str(
            payload.get("search_metadata", {}).get("google_flights_url", "")
        )
        results: list[RoundTripDeal] = []
        for item in payload.get("best_flights", []) + payload.get("other_flights", []):
            segments = item.get("flights") or []
            if not segments:
                continue
            first = segments[0].get("departure_airport") or {}
            last = segments[-1].get("arrival_airport") or {}
            origin = str(first.get("id", "")).upper()
            destination = str(last.get("id", "")).upper()
            if origin not in origins or destination not in destinations:
                continue
            try:
                price = Decimal(str(item["price"]))
            except (KeyError, InvalidOperation, TypeError):
                continue
            flight_numbers = tuple(
                str(segment.get("flight_number", "航班待确认"))
                for segment in segments
            )
            results.append(
                RoundTripDeal(
                    origin=origin,
                    destination=destination,
                    outbound_date=outbound_date,
                    return_date=return_date,
                    displayed_price_per_adult=price,
                    currency=currency,
                    adults=adults,
                    flight_numbers=flight_numbers,
                    stops=max(0, len(segments) - 1),
                    source="Google Flights（SerpApi）",
                    comparison_url=comparison_url,
                )
            )
        return results
