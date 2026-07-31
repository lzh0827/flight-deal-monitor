from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class SearchTask:
    direction: str
    origin: str
    departure_date: date
    destinations: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    currency: str
    adults: int
    required_baggage_kg: int
    max_observed_price_per_adult: Decimal
    notification_drop_per_adult: Decimal
    default_comparison_baseline_per_adult: Decimal
    request_timeout_seconds: int
    queries_per_run: int
    travelpayouts_markets: tuple[str, ...]
    state_file: Path
    airport_names: dict[str, str]
    departure_airports: tuple[str, ...]
    arrival_airports: tuple[str, ...]
    outbound_dates: tuple[date, ...]
    return_dates: tuple[date, ...]
    known_baselines: dict[str, Decimal]
    ground_transfer_notes: dict[str, str]

    def search_tasks(self) -> tuple[SearchTask, ...]:
        tasks: list[SearchTask] = []
        for departure_date in self.outbound_dates:
            for origin in self.departure_airports:
                tasks.append(
                    SearchTask("去程", origin, departure_date, self.arrival_airports)
                )
        for departure_date in self.return_dates:
            for origin in self.arrival_airports:
                tasks.append(
                    SearchTask("返程", origin, departure_date, self.departure_airports)
                )
        return tuple(tasks)


def _codes(values: list[str]) -> tuple[str, ...]:
    return tuple(str(value).upper() for value in values)


def _dates(values: list[str]) -> tuple[date, ...]:
    return tuple(date.fromisoformat(str(value)) for value in values)


def load_settings(path: Path) -> Settings:
    data = json.loads(path.read_text(encoding="utf-8"))
    adults = int(data["adults"])
    if adults != 3:
        raise ValueError("本次潮汕行程固定按 3 名成人监控")
    departure_airports = _codes(data["departure_airports"])
    arrival_airports = _codes(data["arrival_airports"])
    if not departure_airports or not arrival_airports:
        raise ValueError("出发和到达机场列表都不能为空")
    return Settings(
        currency=str(data["currency"]).upper(),
        adults=adults,
        required_baggage_kg=int(data["required_baggage_kg"]),
        max_observed_price_per_adult=Decimal(
            str(data["max_observed_price_per_adult"])
        ),
        notification_drop_per_adult=Decimal(
            str(data["notification_drop_per_adult"])
        ),
        default_comparison_baseline_per_adult=Decimal(
            str(data["default_comparison_baseline_per_adult"])
        ),
        request_timeout_seconds=int(data["request_timeout_seconds"]),
        queries_per_run=int(data["queries_per_run"]),
        travelpayouts_markets=tuple(
            str(item).lower() for item in data.get("travelpayouts_markets", ["cn"])
        ),
        state_file=(path.parent / data["state_file"]).resolve(),
        airport_names={str(k).upper(): str(v) for k, v in data["airport_names"].items()},
        departure_airports=departure_airports,
        arrival_airports=arrival_airports,
        outbound_dates=_dates(data["outbound_dates"]),
        return_dates=_dates(data["return_dates"]),
        known_baselines={
            str(key).upper(): Decimal(str(value))
            for key, value in data.get("known_baselines", {}).items()
        },
        ground_transfer_notes={
            str(key).upper(): str(value)
            for key, value in data.get("ground_transfer_notes", {}).items()
        },
    )
