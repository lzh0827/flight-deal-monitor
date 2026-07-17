from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from .config import Settings
from .models import Candidate, FlightDeal
from .state import MonitorState

logger = logging.getLogger(__name__)


class DiscoveryProvider(Protocol):
    def discover(
        self,
        origin: str,
        start: date,
        end: date,
        max_price: Decimal,
        currency: str,
    ) -> list[Candidate]: ...


class Verifier(Protocol):
    def verify(
        self,
        candidate: Candidate,
        adults: int,
        max_total: Decimal,
        max_per_adult: Decimal,
        currency: str,
        discovery_sources: tuple[str, ...],
    ) -> FlightDeal | None: ...


class Notifier(Protocol):
    def send_deal(
        self, deal: FlightDeal, airport_names: dict[str, str], now: datetime
    ) -> None: ...


def origin_for_time(now: datetime, cycle: tuple[str, ...]) -> str:
    """Choose one origin deterministically per 15-minute slot."""
    slot = int(now.timestamp()) // (15 * 60)
    return cycle[slot % len(cycle)]


def merge_candidates(groups: list[list[Candidate]]) -> list[tuple[Candidate, tuple[str, ...]]]:
    merged: dict[tuple[str, str, date], tuple[Candidate, set[str]]] = {}
    for group in groups:
        for candidate in group:
            existing = merged.get(candidate.key)
            if existing is None:
                merged[candidate.key] = (candidate, {candidate.source})
            else:
                best, sources = existing
                sources.add(candidate.source)
                if candidate.estimated_price_per_adult < best.estimated_price_per_adult:
                    merged[candidate.key] = (candidate, sources)
    ordered = sorted(
        merged.values(), key=lambda item: item[0].estimated_price_per_adult
    )
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

    def run(self, now: datetime, dry_run: bool = False) -> list[FlightDeal]:
        origin = origin_for_time(now, self.settings.origin_cycle)
        start = now.date() + timedelta(days=self.settings.departure_start_offset_days)
        end = now.date() + timedelta(days=self.settings.days_ahead)
        logger.info("本轮扫描 %s，日期 %s 至 %s", origin, start, end)

        groups: list[list[Candidate]] = []
        for provider in self.discovery_providers:
            try:
                found = provider.discover(
                    origin,
                    start,
                    end,
                    self.settings.max_price_per_adult,
                    self.settings.currency,
                )
                logger.info("%s 发现 %d 个候选", type(provider).__name__, len(found))
                groups.append(found)
            except Exception:
                logger.exception("%s 发现阶段失败，本轮继续", type(provider).__name__)

        candidates = []
        for candidate, sources in merge_candidates(groups):
            if self.state.should_verify_candidate(
                candidate.origin,
                candidate.destination,
                candidate.departure_date.isoformat(),
                now,
                timedelta(minutes=self.settings.candidate_recheck_minutes),
            ):
                candidates.append((candidate, sources))
            if len(candidates) >= self.settings.max_candidates_to_verify_per_run:
                break
        deals: list[FlightDeal] = []
        for candidate, sources in candidates:
            try:
                deal = self.verifier.verify(
                    candidate,
                    self.settings.adults,
                    self.settings.max_total_price,
                    self.settings.max_price_per_adult,
                    self.settings.currency,
                    sources,
                )
            except Exception:
                logger.exception(
                    "实时复核失败：%s-%s %s",
                    candidate.origin,
                    candidate.destination,
                    candidate.departure_date,
                )
                continue
            if deal is None:
                if not dry_run:
                    self.state.mark_candidate_checked(
                        candidate.origin,
                        candidate.destination,
                        candidate.departure_date.isoformat(),
                        now,
                    )
                continue
            if not dry_run:
                self.state.mark_candidate_checked(
                    candidate.origin,
                    candidate.destination,
                    candidate.departure_date.isoformat(),
                    now,
                )
            should_notify = self.state.should_notify(
                deal,
                now,
                self.settings.notification_price_drop_cny,
                timedelta(hours=self.settings.renotify_after_missing_hours),
            )
            if should_notify:
                if dry_run:
                    logger.info("DRY RUN：将推送 %s", deal.fingerprint)
                else:
                    self.notifier.send_deal(deal, self.settings.airport_names, now)
                deals.append(deal)
            self.state.mark_seen(deal, now, notified=should_notify and not dry_run)

        self.state.prune(now)
        if not dry_run:
            self.state.save()
        logger.info("本轮完成：复核 %d 个候选，新推送 %d 个", len(candidates), len(deals))
        return deals
