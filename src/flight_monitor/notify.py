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
        stop_text = "直飞" if deal.stops == 0 else f"中转 {deal.stops} 次"
        content = "\n".join(
            [
                f"## ✈️ 发现 ≤ ¥300/人的机票",
                "",
                f"- **航线**：{origin_name}（{deal.origin}）→ "
                f"{destination_name}（{deal.destination}）",
                f"- **起飞**：{deal.departure_at.strftime('%Y-%m-%d %H:%M')}",
                f"- **航班**：{flights}（{stop_text}）",
                f"- **两人含税总价**：¥{deal.total_price:.2f}",
                f"- **每人含税价**：¥{deal.price_per_adult:.2f}",
                f"- **托运行李**：{deal.baggage}",
                f"- **发现来源**：{'、'.join(deal.discovery_sources)}；Amadeus 实时复核",
                f"- **复核时间**：{now.strftime('%Y-%m-%d %H:%M:%S')}（Asia/Shanghai）",
                "",
                f"[打开携程搜索页]({deal.booking_url}) | "
                f"[用 Google Flights 比价]({deal.comparison_url})",
                "",
                "> 价格和座位会实时变化；付款前请再次核对两名成人的最终含税价、"
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
            "## ✅ 微信通知已连通\n\n以后发现每人含税价不超过 ¥300 的机票时，会发到这里。",
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

