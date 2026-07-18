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

    def send_lowest_test(
        self,
        deal: FlightDeal | None,
        airport_names: dict[str, str],
        now: datetime,
    ) -> None: ...


def origins_for_time(
    now: datetime,
    every_run_origins: tuple[str, ...],
    rotating_origins: tuple[str, ...],
) -> tuple[str, ...]:
    """Scan core airports every run and rotate one lower-priority airport."""
    slot = int(now.timestamp()) // (15 * 60)
    origins = list(every_run_origins)
    if rotating_origins:
        origins.append(rotating_origins[slot % len(rotating_origins)])
    return tuple(dict.fromkeys(origins))


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

    def run(
        self,
        now: datetime,
        dry_run: bool = False,
        notify_lowest_test: bool = False,
    ) -> list[FlightDeal]:
        origins = origins_for_time(
            now,
            self.settings.every_run_origins,
            self.settings.rotating_origins,
        )
        start = now.date() + timedelta(days=self.settings.departure_start_offset_days)
        end = now.date() + timedelta(days=self.settings.days_ahead)
        logger.info("本轮扫描 %s，日期 %s 至 %s", "、".join(origins), start, end)

        groups: list[list[Candidate]] = []
        discovery_price_limit = (
            Decimal("999999999")
            if notify_lowest_test
            else self.settings.max_price_per_adult
        )
        for origin in origins:
            for provider in self.discovery_providers:
                try:
                    found = provider.discover(
                        origin,
                        start,
                        end,
                        discovery_price_limit,
                        self.settings.currency,
                    )
                    logger.info(
                        "%s / %s 发现 %d 个候选",
                        origin,
                        type(provider).__name__,
                        len(found),
                    )
                    groups.append(found)
                except Exception:
                    logger.exception(
                        "%s / %s 发现阶段失败，本轮继续",
                        origin,
                        type(provider).__name__,
                    )

        merged_candidates = merge_candidates(groups)
        if notify_lowest_test:
            test_deal: FlightDeal | None = None
            if merged_candidates:
                candidate, sources = merged_candidates[0]
                test_deal = self.verifier.verify(
                    candidate,
                    self.settings.adults,
                    Decimal("999999999"),
                    Decimal("999999999"),
                    self.settings.currency,
                    sources,
                )
            if not dry_run:
                self.notifier.send_lowest_test(
                    test_deal, self.settings.airport_names, now
                )
            logger.info("最低价测试完成：%s", test_deal.fingerprint if test_deal else "无结果")
            return [test_deal] if test_deal else []

        candidates = []
        for candidate, sources in merged_candidates:
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
