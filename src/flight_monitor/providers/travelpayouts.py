from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from ..models import Candidate


class TravelpayoutsDiscovery:
    """Discover cached low fares; every result must be live-verified elsewhere."""

    endpoint = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

    def __init__(
        self,
        token: str,
        timeout: int,
        session: requests.Session,
        market: str = "cn",
    ) -> None:
        self.token = token
        self.timeout = timeout
        self.session = session
        self.market = market.lower()

    def discover(
        self,
        origin: str,
        start: date,
        end: date,
        max_price: Decimal,
        currency: str,
    ) -> list[Candidate]:
        response = self.session.get(
            self.endpoint,
            headers={"X-Access-Token": self.token},
            params={
                "origin": origin,
                "currency": currency.lower(),
                "one_way": "true",
                "direct": "false",
                "unique": "false",
                "market": self.market,
                "page": 1,
                "limit": 1000,
                "sorting": "price",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is not True:
            raise RuntimeError(f"Travelpayouts 返回错误: {payload.get('error')}")
        candidates: list[Candidate] = []
        for item in payload.get("data", []):
            try:
                departure_at = datetime.fromisoformat(item["departure_at"])
                departure = departure_at.date()
                price = Decimal(str(item["price"]))
                destination = str(item["destination"]).upper()
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue
            if (
                start <= departure <= end
                and price <= max_price
                and destination != origin
            ):
                link = str(item.get("link", ""))
                if link.startswith("/"):
                    link = f"https://www.aviasales.com{link}"
                airline = str(item.get("airline", "")).upper()
                number = str(item.get("flight_number", ""))
                flight_number = f"{airline}{number}" if airline or number else "待确认"
                candidates.append(
                    Candidate(
                        origin,
                        destination,
                        departure,
                        price,
                        f"Aviasales缓存价({self.market.upper()})",
                        departure_at=departure_at,
                        flight_number=flight_number,
                        stops=int(item["transfers"]) if item.get("transfers") is not None else None,
                        booking_url=link,
                    )
                )
        return candidates
