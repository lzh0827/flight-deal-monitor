from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .models import FlightDeal


class MonitorState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {"version": 1, "notified": {}, "candidate_checks": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("version") == 1 and isinstance(loaded.get("notified"), dict):
                self.data = loaded
                self.data.setdefault("candidate_checks", {})
        except (OSError, ValueError, TypeError):
            # 损坏的状态不能阻止监控运行；保留副本便于排查。
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass

    def should_notify(
        self,
        deal: FlightDeal,
        now: datetime,
        minimum_drop: Decimal,
        renotify_after_missing: timedelta,
    ) -> bool:
        record = self.data["notified"].get(deal.fingerprint)
        if record is None:
            return True
        old_price = Decimal(str(record["lowest_total_price"]))
        if deal.total_price <= old_price - minimum_drop:
            return True
        last_seen = datetime.fromisoformat(record["last_seen_at"])
        return now - last_seen >= renotify_after_missing

    def mark_seen(self, deal: FlightDeal, now: datetime, notified: bool) -> None:
        key = deal.fingerprint
        record = self.data["notified"].get(key)
        price = str(deal.total_price)
        if record is None:
            record = {
                "lowest_total_price": price,
                "last_notified_at": now.isoformat() if notified else None,
                "last_seen_at": now.isoformat(),
                "departure_at": deal.departure_at.isoformat(),
            }
            self.data["notified"][key] = record
            return
        record["last_seen_at"] = now.isoformat()
        if Decimal(price) < Decimal(str(record["lowest_total_price"])):
            record["lowest_total_price"] = price
        if notified:
            record["last_notified_at"] = now.isoformat()

    def should_verify_candidate(
        self, origin: str, destination: str, departure_date: str, now: datetime, cooldown: timedelta
    ) -> bool:
        key = f"{origin}-{destination}-{departure_date}"
        checked = self.data["candidate_checks"].get(key)
        if not checked:
            return True
        try:
            return now - datetime.fromisoformat(checked) >= cooldown
        except (TypeError, ValueError):
            return True

    def mark_candidate_checked(
        self, origin: str, destination: str, departure_date: str, now: datetime
    ) -> None:
        key = f"{origin}-{destination}-{departure_date}"
        self.data["candidate_checks"][key] = now.isoformat()

    def prune(self, now: datetime) -> None:
        cutoff = now - timedelta(days=200)
        kept = {}
        for key, value in self.data["notified"].items():
            try:
                departure = datetime.fromisoformat(value["departure_at"])
                if departure.tzinfo is None:
                    departure = departure.replace(tzinfo=timezone.utc)
                if departure >= cutoff:
                    kept[key] = value
            except (KeyError, TypeError, ValueError):
                continue
        self.data["notified"] = kept
        check_cutoff = now - timedelta(days=7)
        self.data["candidate_checks"] = {
            key: value
            for key, value in self.data["candidate_checks"].items()
            if _is_recent(value, check_cutoff)
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _is_recent(value: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(value) >= cutoff
    except (TypeError, ValueError):
        return False
