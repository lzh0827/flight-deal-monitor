from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candidate:
    origin: str
    destination: str
    departure_date: date
    estimated_price_per_adult: Decimal
    source: str

    @property
    def key(self) -> tuple[str, str, date]:
        return self.origin, self.destination, self.departure_date


@dataclass(frozen=True)
class FlightDeal:
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime | None
    flight_numbers: tuple[str, ...]
    total_price: Decimal
    price_per_adult: Decimal
    currency: str
    adults: int
    baggage: str
    stops: int
    validating_airlines: tuple[str, ...]
    discovery_sources: tuple[str, ...]
    booking_url: str
    comparison_url: str

    @property
    def fingerprint(self) -> str:
        flights = "+".join(self.flight_numbers)
        return (
            f"{self.origin}-{self.destination}-"
            f"{self.departure_at.isoformat()}-{flights}"
        )

