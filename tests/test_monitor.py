from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flight_monitor.models import Candidate, FlightDeal
from flight_monitor.monitor import merge_candidates, origin_for_time
from flight_monitor.providers.amadeus import AmadeusClient
from flight_monitor.state import MonitorState


def sample_offer(total: str = "599.98", seats: int = 2) -> dict:
    return {
        "numberOfBookableSeats": seats,
        "price": {"currency": "CNY", "total": total, "grandTotal": total},
        "travelerPricings": [
            {
                "travelerType": "ADULT",
                "price": {"total": str(Decimal(total) / 2)},
                "fareDetailsBySegment": [
                    {"includedCheckedBags": {"weight": 20, "weightUnit": "KG"}}
                ],
            },
            {
                "travelerType": "ADULT",
                "price": {"total": str(Decimal(total) / 2)},
                "fareDetailsBySegment": [
                    {"includedCheckedBags": {"weight": 20, "weightUnit": "KG"}}
                ],
            },
        ],
    }


def sample_deal(total: str = "580") -> FlightDeal:
    return FlightDeal(
        origin="HGH",
        destination="CAN",
        departure_at=datetime(2026, 8, 1, 8, 0),
        arrival_at=datetime(2026, 8, 1, 10, 0),
        flight_numbers=("CZ1234",),
        total_price=Decimal(total),
        price_per_adult=Decimal(total) / 2,
        currency="CNY",
        adults=2,
        baggage="20kg",
        stops=0,
        validating_airlines=("CZ",),
        discovery_sources=("test",),
        booking_url="https://example.com",
        comparison_url="https://example.com",
    )


class MonitorTests(unittest.TestCase):
    def test_price_requires_both_adults_under_300(self) -> None:
        self.assertTrue(
            AmadeusClient._offer_qualifies(
                sample_offer(), 2, Decimal("600"), Decimal("300"), "CNY"
            )
        )
        self.assertFalse(
            AmadeusClient._offer_qualifies(
                sample_offer("600.02"), 2, Decimal("600"), Decimal("300"), "CNY"
            )
        )
        self.assertFalse(
            AmadeusClient._offer_qualifies(
                sample_offer(seats=1), 2, Decimal("600"), Decimal("300"), "CNY"
            )
        )

    def test_baggage_parsing(self) -> None:
        self.assertEqual(AmadeusClient._baggage_text(sample_offer()), "20kg")

    def test_merge_candidates_keeps_lowest_and_all_sources(self) -> None:
        first = Candidate("HGH", "CAN", date(2026, 8, 1), Decimal("290"), "A")
        second = Candidate("HGH", "CAN", date(2026, 8, 1), Decimal("280"), "B")
        merged = merge_candidates([[first], [second]])
        self.assertEqual(merged[0][0].estimated_price_per_adult, Decimal("280"))
        self.assertEqual(merged[0][1], ("A", "B"))

    def test_origin_cycle_is_deterministic(self) -> None:
        now = datetime(2026, 7, 17, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(origin_for_time(now, ("HGH",)), "HGH")
        self.assertIn(origin_for_time(now, ("HGH", "PVG")), {"HGH", "PVG"})

    def test_state_deduplicates_and_notifies_price_drop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = MonitorState(state_path)
            now = datetime(2026, 7, 17, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
            deal = sample_deal("580")
            self.assertTrue(
                state.should_notify(deal, now, Decimal("1"), timedelta(hours=24))
            )
            state.mark_seen(deal, now, notified=True)
            self.assertFalse(
                state.should_notify(
                    deal,
                    now + timedelta(minutes=30),
                    Decimal("1"),
                    timedelta(hours=24),
                )
            )
            cheaper = sample_deal("578")
            self.assertTrue(
                state.should_notify(
                    cheaper,
                    now + timedelta(hours=1),
                    Decimal("1"),
                    timedelta(hours=24),
                )
            )
            state.save()
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn(deal.fingerprint, loaded["notified"])


if __name__ == "__main__":
    unittest.main()
