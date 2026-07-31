from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from .config import SearchTask, Settings
from .models import Candidate, FlightDeal
from .state import MonitorState

logger = logging.getLogger(__name__)


class DiscoveryProvider(Protocol):
    def discover(
        self,
        origin: str,
        departure_date: date,
        destinations: tuple[str, ...],
        max_price: Decimal,
        currency: str,
    ) -> list[Candidate]: ...


class Verifier(Protocol):
    def verify(
        self,
        candidate: Candidate,
        adults: int,
        max_per_adult: Decimal,
        currency: str,
        discovery_sources: tuple[str, ...],
    ) -> FlightDeal | None: ...


class Notifier(Protocol):
    def send_deal(
        self,
        deal: FlightDeal,
        airport_names: dict[str, str],
        ground_transfer_notes: dict[str, str],
        baseline: Decimal,
        now: datetime,
    ) -> None: ...


def queries_for_time(
    now: datetime, tasks: tuple[SearchTask, ...], per_run: int
) -> tuple[SearchTask, ...]:
    if per_run <= 0 or per_run >= len(tasks):
        return tasks
    slot = int(now.timestamp()) // (15 * 60)
    start = (slot * per_run) % len(tasks)
    return tuple(tasks[(start + offset) % len(tasks)] for offset in range(per_run))


def merge_candidates(
    groups: list[list[Candidate]],
) -> list[tuple[Candidate, tuple[str, ...]]]:
    merged: dict[tuple[str, str, date], tuple[Candidate, set[str]]] = {}
    for group in groups:
        for candidate in group:
            existing = merged.get(candidate.key)
            if existing is None:
                merged[candidate.key] = (candidate, {candidate.source})
                continue
            best, sources = existing
            sources.add(candidate.source)
            if candidate.estimated_price_per_adult < best.estimated_price_per_adult:
                merged[candidate.key] = (candidate, sources)
    ordered = sorted(merged.values(), key=lambda item: item[0].estimated_price_per_adult)
    return [(candidate, tuple(sorted(sources))) for candidate, sources in ordered]


class DealMonitor:
    def __init__(
        self,
        settings: Settings,
        discovery_providers: list[DiscoveryProvider],
        verifier: Verifier,
        notifier: Notifier,
        state: MonitorState,
    ) -> None:
        self.settings = settings
        self.discovery_providers = discovery_providers
        self.verifier = verifier
        self.notifier = notifier
        self.state = state

    def run(
        self,
        now: datetime,
        dry_run: bool = False,
        initialize_baseline: bool = False,
        scan_all: bool = False,
    ) -> list[FlightDeal]:
        all_tasks = self.settings.search_tasks()
        tasks = all_tasks if scan_all else queries_for_time(
            now, all_tasks, self.settings.queries_per_run
        )
        logger.info("本轮扫描 %d/%d 个出发机场+日期任务", len(tasks), len(all_tasks))
        groups: list[list[Candidate]] = []
        for task in tasks:
            for provider in self.discovery_providers:
                try:
                    found = provider.discover(
                        task.origin,
                        task.departure_date,
                        task.destinations,
                        self.settings.max_observed_price_per_adult,
                        self.settings.currency,
                    )
                    logger.info(
                        "%s %s %s / %s：%d 个目标候选",
                        task.direction,
                        task.origin,
                        task.departure_date,
                        type(provider).__name__,
                        len(found),
                    )
                    groups.append(found)
                except Exception:
                    logger.exception(
                        "%s %s %s / %s 查询失败，本轮继续",
                        task.direction,
                        task.origin,
                        task.departure_date,
                        type(provider).__name__,
                    )

        deals: list[FlightDeal] = []
        for candidate, sources in merge_candidates(groups):
            deal = self.verifier.verify(
                candidate,
                self.settings.adults,
                self.settings.max_observed_price_per_adult,
                self.settings.currency,
                sources,
            )
            if deal is None:
                continue
            baseline, previous_low = self.state.prices(deal)
            logger.info(
                "观察价 %s-%s %s：¥%s/人；基准 ¥%s；此前最低 %s",
                deal.origin,
                deal.destination,
                deal.departure_at.date(),
                deal.price_per_adult,
                baseline,
                f"¥{previous_low}" if previous_low is not None else "尚未建立",
            )
            should_notify = (
                not initialize_baseline
                and self.state.should_notify(
                    deal, self.settings.notification_drop_per_adult
                )
            )
            if should_notify:
                if dry_run:
                    logger.info("DRY RUN：将推送 %s", deal.fingerprint)
                else:
                    self.notifier.send_deal(
                        deal,
                        self.settings.airport_names,
                        self.settings.ground_transfer_notes,
                        baseline,
                        now,
                    )
                deals.append(deal)
            if not dry_run:
                self.state.mark_seen(deal, now, notified=should_notify)

        if not dry_run:
            self.state.save()
        logger.info("本轮完成：观察到 %d 条路线最低价，新推送 %d 条", len(merge_candidates(groups)), len(deals))
        return deals
