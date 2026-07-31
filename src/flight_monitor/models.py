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
    departure_at: datetime | None = None
    flight_number: str = "待确认"
    stops: int | None = None
    booking_url: str = ""

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


@dataclass(frozen=True)
class RoundTripDeal:
    origin: str
    destination: str
    outbound_date: date
    return_date: date
    displayed_price_per_adult: Decimal
    currency: str
    adults: int
    flight_numbers: tuple[str, ...]
    stops: int
    source: str
    comparison_url: str

    @property
    def key(self) -> str:
        return (
            f"{self.origin}-{self.destination}-"
            f"{self.outbound_date.isoformat()}-{self.return_date.isoformat()}"
        )
