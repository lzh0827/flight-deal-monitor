from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from urllib.parse import quote

from ..models import Candidate, FlightDeal


class CachedFareVerifier:
    """Convert a cache observation into a clearly labelled candidate fare."""

    def verify(
        self,
        candidate: Candidate,
        adults: int,
        max_per_adult: Decimal,
        currency: str,
        discovery_sources: tuple[str, ...],
    ) -> FlightDeal | None:
        per_adult = candidate.estimated_price_per_adult
        if per_adult > max_per_adult:
            return None
        departure_at = candidate.departure_at or datetime.combine(
            candidate.departure_date, time.min
        )
        query = quote(
            f"Flights from {candidate.origin} to {candidate.destination} on "
            f"{candidate.departure_date.isoformat()} for {adults} adults"
        )
        booking_url = candidate.booking_url or (
            "https://www.aviasales.com/search/"
            f"{candidate.origin}{candidate.departure_date.strftime('%d%m')}"
            f"{candidate.destination}{adults}"
        )
        return FlightDeal(
            origin=candidate.origin,
            destination=candidate.destination,
            departure_at=departure_at,
            arrival_at=None,
            flight_numbers=(candidate.flight_number,),
            total_price=per_adult * adults,
            price_per_adult=per_adult,
            currency=currency,
            adults=adults,
            baggage="缓存数据未提供，必须另核20kg托运行李后的结算价",
            stops=candidate.stops if candidate.stops is not None else -1,
            validating_airlines=(),
            discovery_sources=discovery_sources,
            booking_url=booking_url,
            comparison_url=f"https://www.google.com/travel/flights?q={query}",
        )
