from __future__ import annotations

from datetime import datetime

import requests

from .models import FlightDeal


class PushPlusNotifier:
    endpoint = "https://www.pushplus.plus/send"

    def __init__(self, token: str, timeout: int, session: requests.Session) -> None:
        self.token = token
        self.timeout = timeout
        self.session = session

    def send_deal(
        self, deal: FlightDeal, airport_names: dict[str, str], now: datetime
    ) -> None:
        origin_name = airport_names.get(deal.origin, deal.origin)
        destination_name = airport_names.get(deal.destination, deal.destination)
        flights = " → ".join(deal.flight_numbers)
        stop_text = (
            "中转次数待确认"
            if deal.stops < 0
            else ("直飞" if deal.stops == 0 else f"中转 {deal.stops} 次")
        )
        content = "\n".join(
            [
                f"## ✈️ 发现 ≤ ¥300/人的缓存机票价格",
                "",
                f"- **航线**：{origin_name}（{deal.origin}）→ "
                f"{destination_name}（{deal.destination}）",
                f"- **起飞**：{deal.departure_at.strftime('%Y-%m-%d %H:%M')}",
                f"- **航班**：{flights}（{stop_text}）",
                f"- **两人估算总价**：¥{deal.total_price:.2f}",
                f"- **每人缓存价**：¥{deal.price_per_adult:.2f}",
                f"- **托运行李**：{deal.baggage}",
                f"- **发现来源**：{'、'.join(deal.discovery_sources)}（非实时库存）",
                f"- **发现时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}（Asia/Shanghai）",
                "",
                f"[打开 Aviasales 复核]({deal.booking_url}) | "
                f"[用 Google Flights 比价]({deal.comparison_url})",
                "",
                "> ⚠️ 这是最近用户搜索形成的缓存发现价，不代表当前仍有两张票，"
                "也不能保证最终含税结算价。请在付款前核对两名成人的总价、座位、"
                "行李额和票价适用条件。",
            ]
        )
        self._send(
            f"低价机票：{deal.origin}→{deal.destination} ¥{deal.price_per_adult:.0f}/人",
            content,
        )

    def send_test(self) -> None:
        self._send(
            "机票监控测试成功",
            "## ✅ 微信通知已连通\n\n以后发现每人缓存价不超过 ¥300 的机票时，会发到这里；下单前需要再次核对实时总价。",
        )

    def send_lowest_test(
        self,
        deal: FlightDeal | None,
        airport_names: dict[str, str],
        now: datetime,
    ) -> None:
        if deal is None:
            self._send(
                "最低价航班测试：本轮无结果",
                "## 本轮没有找到可用的缓存航班记录\n\n"
                f"检测时间：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
            )
            return

        origin_name = airport_names.get(deal.origin, deal.origin)
        destination_name = airport_names.get(deal.destination, deal.destination)
        flights = "、".join(deal.flight_numbers)
        stop_text = (
            "中转次数待确认"
            if deal.stops < 0
            else ("直飞" if deal.stops == 0 else f"中转 {deal.stops} 次")
        )
        content = "\n".join(
            [
                "## ✈️ 本轮最低缓存价格（一次性测试）",
                "",
                f"- **航线**：{origin_name}（{deal.origin}）→ "
                f"{destination_name}（{deal.destination}）",
                f"- **出发**：{deal.departure_at.strftime('%Y-%m-%d %H:%M')}",
                f"- **航班**：{flights}（{stop_text}）",
                f"- **每人缓存价**：¥{deal.price_per_adult:.2f}",
                f"- **两人估算总价**：¥{deal.total_price:.2f}",
                f"- **来源**：{'、'.join(deal.discovery_sources)}",
                f"- **检测时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
                "",
                f"[打开 Aviasales 复核]({deal.booking_url}) | "
                f"[使用 Google Flights 比价]({deal.comparison_url})",
                "",
                "> 这是缓存搜索价格测试，不保证仍有两张票，也不保证最终含税价、行李额和座位；付款前必须重新核对。",
            ]
        )
        self._send(
            f"最低价测试：{deal.origin}→{deal.destination} ¥{deal.price_per_adult:.0f}/人",
            content,
        )

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
