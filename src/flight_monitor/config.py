from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    currency: str
    adults: int
    max_price_per_adult: Decimal
    days_ahead: int
    departure_start_offset_days: int
    max_candidates_to_verify_per_run: int
    candidate_recheck_minutes: int
    notification_price_drop_cny: Decimal
    renotify_after_missing_hours: int
    request_timeout_seconds: int
    state_file: Path
    airport_names: dict[str, str]
    origin_cycle: tuple[str, ...]
    amadeus_environment: str

    @property
    def max_total_price(self) -> Decimal:
        return self.max_price_per_adult * self.adults


def load_settings(path: Path) -> Settings:
    data = json.loads(path.read_text(encoding="utf-8"))
    environment = os.getenv("AMADEUS_ENVIRONMENT", "production").lower()
    if environment not in {"test", "production"}:
        raise ValueError("AMADEUS_ENVIRONMENT 必须是 test 或 production")
    if int(data["adults"]) != 2:
        raise ValueError("当前需求固定为 2 名成人")
    cycle = tuple(str(item).upper() for item in data["origin_cycle"])
    if not cycle:
        raise ValueError("origin_cycle 不能为空")
    return Settings(
        currency=str(data["currency"]).upper(),
        adults=int(data["adults"]),
        max_price_per_adult=Decimal(str(data["max_price_per_adult"])),
        days_ahead=int(data["days_ahead"]),
        departure_start_offset_days=int(data["departure_start_offset_days"]),
        max_candidates_to_verify_per_run=int(data["max_candidates_to_verify_per_run"]),
        candidate_recheck_minutes=int(data["candidate_recheck_minutes"]),
        notification_price_drop_cny=Decimal(
            str(data["notification_price_drop_cny"])
        ),
        renotify_after_missing_hours=int(data["renotify_after_missing_hours"]),
        request_timeout_seconds=int(data["request_timeout_seconds"]),
        state_file=(path.parent / data["state_file"]).resolve(),
        airport_names={str(k).upper(): str(v) for k, v in data["airport_names"].items()},
        origin_cycle=cycle,
        amadeus_environment=environment,
    )
