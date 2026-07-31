from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from flight_monitor.config import SearchTask, load_settings
from flight_monitor.google_monitor import google_schedule_slot, roundtrip_date_pairs
from flight_monitor.models import Candidate, FlightDeal, RoundTripDeal
from flight_monitor.monitor import merge_candidates, queries_for_time
from flight_monitor.providers.cached import CachedFareVerifier
from flight_monitor.providers.travelpayouts import TravelpayoutsDiscovery
from flight_monitor.providers.serpapi import SerpApiGoogleFlights
from flight_monitor.state import MonitorState, route_key


def sample_deal(price: str = "270", origin: str = "NGB", destination: str = "SWA") -> FlightDeal:
    per_adult = Decimal(price)
    return FlightDeal(
        origin=origin,
        destination=destination,
        departure_at=datetime(2026, 8, 30, 9, 50),
        arrival_at=None,
        flight_numbers=("9C7611",),
        total_price=per_adult * 3,
        price_per_adult=per_adult,
        currency="CNY",
        adults=3,
        baggage="待确认20kg",
        stops=0,
        validating_airlines=("9C",),
        discovery_sources=("test",),
        booking_url="https://example.com",
        comparison_url="https://example.com",
    )


class MonitorTests(unittest.TestCase):
    def test_serpapi_uses_one_multi_airport_query_and_parses_result(self) -> None:
        class FakeResponse:
            ok = True

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "search_metadata": {
                        "google_flights_url": "https://www.google.com/travel/flights/test"
                    },
                    "best_flights": [
                        {
                            "price": 688,
                            "flights": [
                                {
                                    "departure_airport": {"id": "NGB"},
                                    "arrival_airport": {"id": "SWA"},
                                    "flight_number": "9C 7611",
                                }
                            ],
                        }
                    ],
                    "other_flights": [],
                }

        class FakeSession:
            def __init__(self) -> None:
                self.params: dict = {}

            def get(self, url: str, **kwargs: object) -> FakeResponse:
                self.params = kwargs["params"]  # type: ignore[assignment]
                return FakeResponse()

        session = FakeSession()
        provider = SerpApiGoogleFlights("secret", 10, session)  # type: ignore[arg-type]
        deals = provider.search_roundtrip(
            ("NGB", "HGH"),
            ("SWA", "CAN"),
            date(2026, 8, 30),
            date(2026, 9, 2),
            3,
            "CNY",
        )
        self.assertEqual(session.params["departure_id"], "NGB,HGH")
        self.assertEqual(session.params["arrival_id"], "SWA,CAN")
        self.assertEqual(session.params["adults"], 3)
        self.assertEqual(session.params["hl"], "zh-cn")
        self.assertEqual(deals[0].displayed_price_per_adult, Decimal("688"))

    def test_google_schedule_and_four_trip_combinations(self) -> None:
        settings = load_settings(Path(__file__).parents[1] / "config.json")
        self.assertEqual(len(roundtrip_date_pairs(settings)), 4)
        self.assertEqual(
            google_schedule_slot(datetime(2026, 8, 1, 8, 30)),
            "2026-08-01-am",
        )
        self.assertIsNone(google_schedule_slot(datetime(2026, 8, 1, 14, 0)))

    def test_google_roundtrip_alerts_after_fifty_yuan_drop(self) -> None:
        state = MonitorState(Path("unused"), {})
        now = datetime(2026, 7, 31, 12, 0)

        def deal(price: str) -> RoundTripDeal:
            return RoundTripDeal(
                "NGB", "SWA", date(2026, 8, 30), date(2026, 9, 2),
                Decimal(price), "CNY", 3, ("9C 7611",), 0,
                "Google Flights（SerpApi）", "https://example.com"
            )

        state.mark_google_seen(deal("700"), now, False)
        self.assertFalse(state.should_notify_google(deal("651"), Decimal("50")))
        self.assertTrue(state.should_notify_google(deal("650"), Decimal("50")))

    def test_travelpayouts_queries_each_destination_explicitly(self) -> None:
        class FakeResponse:
            def __init__(self, destination: str) -> None:
                self.destination = destination

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "success": True,
                    "data": [
                        {
                            "departure_at": "2026-08-30T09:50:00+08:00",
                            "destination": self.destination,
                            "price": 250,
                            "airline": "9C",
                            "flight_number": "7611",
                            "transfers": 0,
                        }
                    ],
                }

        class FakeSession:
            def __init__(self) -> None:
                self.destinations: list[str] = []

            def get(self, url: str, **kwargs: object) -> FakeResponse:
                params = kwargs["params"]
                assert isinstance(params, dict)
                destination = str(params["destination"])
                self.destinations.append(destination)
                return FakeResponse(destination)

        session = FakeSession()
        provider = TravelpayoutsDiscovery("token", 10, session)  # type: ignore[arg-type]
        results = provider.discover(
            "NGB",
            date(2026, 8, 30),
            ("SWA", "XMN"),
            Decimal("2000"),
            "CNY",
        )
        self.assertEqual(session.destinations, ["SWA", "XMN"])
        self.assertEqual({item.destination for item in results}, {"SWA", "XMN"})

    def test_real_config_has_expected_scope(self) -> None:
        settings = load_settings(Path(__file__).parents[1] / "config.json")
        self.assertEqual(settings.adults, 3)
        self.assertEqual(settings.required_baggage_kg, 20)
        self.assertEqual(settings.queries_per_run, 23)
        self.assertEqual(len(settings.search_tasks()), 45)
        self.assertIn("SWA", settings.arrival_airports)
        self.assertIn("FUO", settings.arrival_airports)

    def test_query_rotation_covers_contiguous_batch(self) -> None:
        tasks = tuple(
            SearchTask("去程", f"A{i}", date(2026, 8, 30), ("SWA",))
            for i in range(45)
        )
        now = datetime(
            2026, 7, 31, 12, 0, tzinfo=timezone(timedelta(hours=8))
        )
        selected = queries_for_time(now, tasks, 9)
        self.assertEqual(len(selected), 9)
        self.assertEqual(len(set(selected)), 9)

    def test_two_23_task_runs_cover_all_45_tasks(self) -> None:
        tasks = tuple(
            SearchTask("去程", f"A{i}", date(2026, 8, 30), ("SWA",))
            for i in range(45)
        )
        first_time = datetime(
            2026, 7, 31, 12, 0, tzinfo=timezone(timedelta(hours=8))
        )
        second_time = first_time + timedelta(minutes=15)
        covered = set(queries_for_time(first_time, tasks, 23))
        covered.update(queries_for_time(second_time, tasks, 23))
        self.assertEqual(covered, set(tasks))

    def test_cached_fare_uses_three_adults(self) -> None:
        candidate = Candidate(
            "NGB", "SWA", date(2026, 8, 30), Decimal("219"), "cache"
        )
        deal = CachedFareVerifier().verify(
            candidate, 3, Decimal("2000"), "CNY", ("cache",)
        )
        self.assertIsNotNone(deal)
        self.assertEqual(deal.total_price, Decimal("657"))

    def test_merge_candidates_keeps_lowest_and_sources(self) -> None:
        first = Candidate("NGB", "SWA", date(2026, 8, 30), Decimal("260"), "A")
        second = Candidate("NGB", "SWA", date(2026, 8, 30), Decimal("250"), "B")
        merged = merge_candidates([[first], [second]])
        self.assertEqual(merged[0][0].estimated_price_per_adult, Decimal("250"))
        self.assertEqual(merged[0][1], ("A", "B"))

    def test_unknown_route_first_observation_only_establishes_baseline(self) -> None:
        state = MonitorState(Path("unused"), {})
        now = datetime(2026, 7, 31, 12, 0)
        deal = sample_deal("400", origin="HGH")
        self.assertFalse(state.should_notify(deal, Decimal("50")))
        state.mark_seen(deal, now, notified=False)
        self.assertFalse(state.should_notify(sample_deal("360", origin="HGH"), Decimal("50")))
        self.assertTrue(state.should_notify(sample_deal("349", origin="HGH"), Decimal("50")))

    def test_known_270_baseline_alerts_at_220_or_lower(self) -> None:
        key = "NGB-SWA-2026-08-30"
        state = MonitorState(Path("unused"), {key: Decimal("270")})
        self.assertFalse(state.should_notify(sample_deal("221"), Decimal("50")))
        self.assertTrue(state.should_notify(sample_deal("220"), Decimal("50")))
        state.mark_seen(sample_deal("220"), datetime(2026, 7, 31, 12, 0), True)
        self.assertFalse(state.should_notify(sample_deal("220"), Decimal("50")))
        self.assertTrue(state.should_notify(sample_deal("219"), Decimal("50")))

    def test_first_seen_route_alerts_if_below_global_270_reference(self) -> None:
        state = MonitorState(Path("unused"), {}, Decimal("270"))
        self.assertFalse(
            state.should_notify(sample_deal("221", origin="YIW"), Decimal("50"))
        )
        self.assertTrue(
            state.should_notify(sample_deal("220", origin="YIW"), Decimal("50"))
        )

    def test_state_saves_version_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = MonitorState(path, {})
            deal = sample_deal("300", origin="HGH")
            state.mark_seen(deal, datetime(2026, 7, 31, 12, 0), False)
            state.save()
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["version"], 2)
            self.assertIn(route_key(deal), loaded["routes"])


if __name__ == "__main__":
    unittest.main()
