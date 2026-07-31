from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

import requests

from .config import Settings
from .models import FlightDeal, RoundTripDeal


class PushPlusNotifier:
    endpoint = "https://www.pushplus.plus/send"

    def __init__(self, token: str, timeout: int, session: requests.Session) -> None:
        self.token = token
        self.timeout = timeout
        self.session = session

    def send_deal(
        self,
        deal: FlightDeal,
        airport_names: dict[str, str],
        ground_transfer_notes: dict[str, str],
        baseline: Decimal,
        now: datetime,
    ) -> None:
        origin_name = airport_names.get(deal.origin, deal.origin)
        destination_name = airport_names.get(deal.destination, deal.destination)
        flights = " → ".join(deal.flight_numbers)
        stop_text = "中转待确认" if deal.stops < 0 else (
            "直飞" if deal.stops == 0 else f"中转 {deal.stops} 次"
        )
        drop = baseline - deal.price_per_adult
        links = self._comparison_links(deal)
        transfer_airport = (
            deal.destination if deal.destination in ground_transfer_notes else deal.origin
        )
        content = "\n".join(
            [
                "## ✈️ 潮汕行程出现新的路线历史低价",
                "",
                f"- **航线**：{origin_name}（{deal.origin}）→ {destination_name}（{deal.destination}）",
                f"- **日期/时间**：{deal.departure_at.strftime('%Y-%m-%d %H:%M')}",
                f"- **航班**：{flights}（{stop_text}）",
                f"- **缓存观察价**：¥{deal.price_per_adult:.2f}/人，三人 ¥{deal.total_price:.2f}",
                f"- **本路线基准**：¥{baseline:.2f}/人，已下降 ¥{drop:.2f}/人",
                "- **托运行李要求**：三人均需各20kg；当前缓存价未确认包含行李",
                f"- **接驳提示**：{ground_transfer_notes.get(transfer_airport, '请核算机场、高铁站和最终目的地之间的接驳')}",
                f"- **数据来源**：{'、'.join(deal.discovery_sources)}（近期搜索缓存，不是实时库存）",
                f"- **发现时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
                "",
                " | ".join(f"[{name}]({url})" for name, url in links),
                "",
                "> 下单前请在至少两个平台核对：三名成人同一航班、含税燃油、每人20kg托运、学生/青年优惠券、退改规则。只有最终支付页价格能与现有¥270/人的宁波—揭阳方案直接比较。",
            ]
        )
        self._send(
            f"潮汕机票降价：{deal.origin}→{deal.destination} ¥{deal.price_per_adult:.0f}/人",
            content,
        )

    def send_test(self, settings: Settings) -> None:
        self._send(
            "潮汕机票监控已配置",
            "\n".join(
                [
                    "## ✅ 微信通知链路正常",
                    "",
                    f"- 旅客：{settings.adults}名成人/学生",
                    f"- 行李：每人{settings.required_baggage_kg}kg托运",
                    f"- 去程：{'、'.join(item.isoformat() for item in settings.outbound_dates)}",
                    f"- 返程：{'、'.join(item.isoformat() for item in settings.return_dates)}",
                    f"- 提醒门槛：路线刷新历史最低且较基准下降至少¥{settings.notification_drop_per_adult}/人",
                    "",
                    "> 缓存候选价不含行李保证；收到降价后仍需打开多个平台核对最终支付价。",
                ]
            ),
        )

    def send_top_deals(
        self,
        deals: list[FlightDeal],
        airport_names: dict[str, str],
        now: datetime,
        requested_count: int,
    ) -> None:
        if not deals:
            content = "\n".join(
                [
                    "## ✈️ 潮汕机票低价榜",
                    "",
                    "本轮全量扫描没有找到目标日期和机场范围内的缓存价格。",
                    "",
                    "> 没有缓存记录不代表没有航班或没有票，只表示近期 Aviasales 搜索缓存未覆盖。",
                ]
            )
            self._send("潮汕机票低价榜：本轮无缓存结果", content)
            return

        lines = [
            f"## ✈️ 当前最便宜路线（{len(deals)}/{requested_count}条）",
            "",
        ]
        for index, deal in enumerate(deals, start=1):
            origin = airport_names.get(deal.origin, deal.origin)
            destination = airport_names.get(deal.destination, deal.destination)
            stop_text = "直飞" if deal.stops == 0 else (
                f"中转{deal.stops}次" if deal.stops > 0 else "中转待确认"
            )
            lines.append(
                f"{index}. **{origin}→{destination}**｜{deal.departure_at.strftime('%m-%d %H:%M')}｜"
                f"¥{deal.price_per_adult:.0f}/人｜三人¥{deal.total_price:.0f}｜{stop_text}"
            )
        lines.extend(
            [
                "",
                f"扫描时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
                "",
                "> 排名来自近期搜索缓存，不保证仍有3张票，也不保证包含税费、优惠券或每人20kg托运行李。请在携程、去哪儿、飞猪及航司官网核对最终支付价。",
            ]
        )
        self._send(
            f"潮汕机票低价榜：当前{len(deals)}条候选",
            "\n".join(lines),
        )

    def send_google_roundtrip_digest(
        self,
        deals: list[RoundTripDeal],
        airport_names: dict[str, str],
        now: datetime,
        title_prefix: str = "Google Flights往返低价榜",
    ) -> None:
        ranked = sorted(deals, key=lambda item: item.displayed_price_per_adult)[:10]
        lines = ["## ✈️ Google Flights 往返低价候选", ""]
        if not ranked:
            lines.append("本轮没有返回符合机场和日期范围的候选。")
        for index, deal in enumerate(ranked, start=1):
            origin = airport_names.get(deal.origin, deal.origin)
            destination = airport_names.get(deal.destination, deal.destination)
            stops = "直飞" if deal.stops == 0 else f"中转{deal.stops}次"
            lines.append(
                f"{index}. **{origin}→{destination}**｜"
                f"{deal.outbound_date.strftime('%m-%d')}去 / {deal.return_date.strftime('%m-%d')}回｜"
                f"展示价¥{deal.displayed_price_per_adult:.0f}/人｜{stops}"
            )
        lines.extend(
            [
                "",
                f"扫描时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
                "",
                "> 这是按3名成人搜索时Google Flights显示的往返候选价。返程班次、3张余票、税费以及每人20kg托运行李均须进入结果页和最终支付页确认。",
            ]
        )
        if ranked and ranked[0].comparison_url:
            lines.extend(["", f"[打开Google Flights核价]({ranked[0].comparison_url})"])
        self._send(f"{title_prefix}：{len(ranked)}条候选", "\n".join(lines))

    def send_google_drop(
        self,
        deal: RoundTripDeal,
        airport_names: dict[str, str],
        baseline: Decimal,
        now: datetime,
    ) -> None:
        origin = airport_names.get(deal.origin, deal.origin)
        destination = airport_names.get(deal.destination, deal.destination)
        drop = baseline - deal.displayed_price_per_adult
        content = "\n".join(
            [
                "## ✈️ Google Flights 往返价刷新历史低价",
                "",
                f"- **航线**：{origin}（{deal.origin}）→ {destination}（{deal.destination}）",
                f"- **日期**：{deal.outbound_date.isoformat()}去 / {deal.return_date.isoformat()}回",
                f"- **当前展示价**：¥{deal.displayed_price_per_adult:.0f}/人",
                f"- **首次观察基准**：¥{baseline:.0f}/人，已下降¥{drop:.0f}/人",
                f"- **发现时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
                "",
                f"[打开Google Flights核价]({deal.comparison_url})",
                "",
                "> 请确认三人同价、完整往返班次、税费和每人20kg托运行李；API展示价不是最终支付价。",
            ]
        )
        self._send(
            f"Google往返降价：{deal.origin}→{deal.destination} ¥{deal.displayed_price_per_adult:.0f}/人",
            content,
        )

    def _comparison_links(self, deal: FlightDeal) -> list[tuple[str, str]]:
        origin = deal.origin
        destination = deal.destination
        departure_date = deal.departure_at.date().isoformat()
        query = quote(
            f"{origin} {destination} {departure_date} 3 adults 20kg baggage"
        )
        return [
            ("Aviasales候选", deal.booking_url),
            (
                "携程",
                f"https://flights.ctrip.com/online/list/oneway-{origin.lower()}-{destination.lower()}?depdate={departure_date}",
            ),
            (
                "去哪儿",
                "https://flight.qunar.com/site/oneway_list.htm?"
                f"fromCode={origin}&toCode={destination}&fromDate={departure_date}",
            ),
            (
                "飞猪",
                "https://sjipiao.fliggy.com/flight_search_result.htm?"
                f"tripType=0&depCity={origin}&arrCity={destination}&depDate={departure_date}",
            ),
            ("Google Flights", f"https://www.google.com/travel/flights?q={query}"),
            ("春秋官网", f"https://flights.ch.com/flight-date/{origin}-{destination}/"),
        ]

    def _send(self, title: str, content: str) -> None:
        response = self.session.post(
            self.endpoint,
            json={
                "token": self.token,
                "title": title,
                "content": content,
                "template": "markdown",
                "channel": "wechat",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("code", -1)) != 200:
            raise RuntimeError(f"PushPlus 推送失败: {payload.get('msg', payload)}")
