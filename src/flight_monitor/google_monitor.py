from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from .config import Settings
from .models import RoundTripDeal
from .notify import PushPlusNotifier
from .providers.serpapi import SerpApiGoogleFlights
from .state import MonitorState

logger = logging.getLogger(__name__)


def roundtrip_date_pairs(settings: Settings) -> tuple[tuple, ...]:
    return tuple(
        (outbound, returning)
        for outbound in settings.outbound_dates
        for returning in settings.return_dates
        if (returning - outbound).days in (3, 4)
    )


def google_schedule_slot(now: datetime) -> str | None:
    period = "am" if 7 <= now.hour < 12 else "pm" if 18 <= now.hour < 23 else None
    # 每月预留至少10次免费查询给首次启用、失败重试和人工复核。
    if now.day == 1 and period == "pm":
        return None
    return f"{now.date().isoformat()}-{period}" if period else None


def _cheapest_per_route(deals: list[RoundTripDeal]) -> list[RoundTripDeal]:
    cheapest: dict[str, RoundTripDeal] = {}
    for deal in deals:
        current = cheapest.get(deal.key)
        if (
            current is None
            or deal.displayed_price_per_adult < current.displayed_price_per_adult
        ):
            cheapest[deal.key] = deal
    return sorted(
        cheapest.values(), key=lambda item: item.displayed_price_per_adult
    )


def run_google_flights_monitor(
    now: datetime,
    settings: Settings,
    provider: SerpApiGoogleFlights,
    notifier: PushPlusNotifier,
    state: MonitorState,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[RoundTripDeal]:
    if now.date() > max(settings.return_dates):
        logger.info("Google Flights：行程日期已过，停止查询")
        return []
    slot = google_schedule_slot(now)
    if not force and slot is None:
        logger.info("Google Flights：当前不在早晚扫描窗口")
        return []
    if not force and state.google_slot_completed(slot):
        logger.info("Google Flights：时段 %s 已完成，跳过重复查询", slot)
        return []

    pairs = roundtrip_date_pairs(settings)
    all_deals: list[RoundTripDeal] = []
    completed = 0
    for outbound, returning in pairs:
        try:
            found = provider.search_roundtrip(
                settings.departure_airports,
                settings.arrival_airports,
                outbound,
                returning,
                settings.adults,
                settings.currency,
            )
            completed += 1
            all_deals.extend(found)
            logger.info(
                "Google Flights %s去/%s回：%d 个候选",
                outbound,
                returning,
                len(found),
            )
        except Exception:
            logger.exception(
                "Google Flights %s去/%s回查询失败，本轮继续", outbound, returning
            )

    deals = _cheapest_per_route(all_deals)
    alerts: list[tuple[RoundTripDeal, Decimal]] = []
    for deal in deals:
        baseline = state.google_baseline(deal)
        if state.should_notify_google(
            deal, settings.notification_drop_per_adult
        ):
            alerts.append((deal, baseline))
        if not dry_run:
            state.mark_google_seen(deal, now, notified=False)

    if force and not dry_run:
        notifier.send_google_roundtrip_digest(
            deals, settings.airport_names, now, "Google Flights首次/手动低价榜"
        )
    elif not dry_run:
        for deal, baseline in alerts:
            notifier.send_google_drop(
                deal, settings.airport_names, baseline, now
            )
            state.mark_google_seen(deal, now, notified=True)

    if not dry_run:
        if slot is not None and completed == len(pairs):
            state.mark_google_slot_completed(slot, now)
        state.save()
    logger.info(
        "Google Flights完成：%d/%d个日期组合，%d条路线，%d条降价提醒",
        completed,
        len(pairs),
        len(deals),
        len(alerts),
    )
    return deals
