from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import FlightDeal


def route_key(deal: FlightDeal) -> str:
    return (
        f"{deal.origin}-{deal.destination}-"
        f"{deal.departure_at.date().isoformat()}"
    )


class MonitorState:
    def __init__(
        self,
        path: Path,
        known_baselines: dict[str, Decimal],
        default_comparison_baseline: Decimal | None = None,
    ) -> None:
        self.path = path
        self.known_baselines = known_baselines
        self.default_comparison_baseline = default_comparison_baseline
        self.data: dict = {"version": 2, "routes": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("version") == 2 and isinstance(loaded.get("routes"), dict):
                self.data = loaded
        except (OSError, ValueError, TypeError):
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass

    def prices(self, deal: FlightDeal) -> tuple[Decimal, Decimal | None]:
        key = route_key(deal)
        record = self.data["routes"].get(key)
        configured = self.known_baselines.get(key)
        if record is None:
            return (
                configured
                or self.default_comparison_baseline
                or deal.price_per_adult,
                None,
            )
        return (
            Decimal(str(record["baseline_price_per_adult"])),
            Decimal(str(record["lowest_price_per_adult"])),
        )

    def should_notify(self, deal: FlightDeal, minimum_drop: Decimal) -> bool:
        baseline, previous_low = self.prices(deal)
        if previous_low is None and route_key(deal) not in self.known_baselines:
            return (
                self.default_comparison_baseline is not None
                and deal.price_per_adult
                <= self.default_comparison_baseline - minimum_drop
            )
        is_new_low = previous_low is None or deal.price_per_adult < previous_low
        return is_new_low and deal.price_per_adult <= baseline - minimum_drop

    def mark_seen(self, deal: FlightDeal, now: datetime, notified: bool) -> None:
        key = route_key(deal)
        record = self.data["routes"].get(key)
        configured = self.known_baselines.get(key)
        price = deal.price_per_adult
        if record is None:
            baseline = configured or price
            self.data["routes"][key] = {
                "baseline_price_per_adult": str(baseline),
                "lowest_price_per_adult": str(price),
                "last_seen_at": now.isoformat(),
                "last_notified_at": now.isoformat() if notified else None,
            }
            return
        record["last_seen_at"] = now.isoformat()
        if price < Decimal(str(record["lowest_price_per_adult"])):
            record["lowest_price_per_adult"] = str(price)
        if notified:
            record["last_notified_at"] = now.isoformat()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
