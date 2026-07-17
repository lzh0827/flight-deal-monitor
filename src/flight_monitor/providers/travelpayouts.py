from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import requests

from ..models import Candidate


class TravelpayoutsDiscovery:
    """Discover cached low fares; every result must be live-verified elsewhere."""

    endpoint = "https://api.travelpayouts.com/v2/prices/latest"

    def __init__(self, token: str, timeout: int, session: requests.Session) -> None:
        self.token = token
        self.timeout = timeout
        self.session = session

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
                "period_type": "year",
                "one_way": "true",
                "page": 1,
                "limit": 1000,
                "sorting": "price",
                "show_to_affiliates": "false",
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
                departure = date.fromisoformat(item["depart_date"])
                price = Decimal(str(item["value"]))
                destination = str(item["destination"]).upper()
            except (KeyError, TypeError, ValueError, InvalidOperation):
                continue
            if (
                start <= departure <= end
                and price <= max_price
                and destination != origin
                and item.get("actual", True)
            ):
                candidates.append(
                    Candidate(origin, destination, departure, price, "Travelpayouts")
                )
        return candidates

