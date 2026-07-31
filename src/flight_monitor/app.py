from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_settings
from .http import build_session
from .monitor import DealMonitor
from .notify import PushPlusNotifier
from .providers.cached import CachedFareVerifier
from .providers.travelpayouts import TravelpayoutsDiscovery
from .state import MonitorState


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="潮汕行程定向机票监控器")
    parser.add_argument("--config", type=Path, default=project_root / "config.json")
    parser.add_argument("--dry-run", action="store_true", help="搜索但不推送、不保存")
    parser.add_argument("--test-notification", action="store_true")
    parser.add_argument(
        "--initialize-baseline",
        action="store_true",
        help="扫描并保存当前观察价作为基线，不发送低价提醒",
    )
    parser.add_argument("--scan-all", action="store_true", help="本轮扫描全部任务")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args(argv)
    try:
        settings = load_settings(args.config.resolve())
        session = build_session()
        notifier = PushPlusNotifier(
            _required_env("PUSHPLUS_TOKEN"), settings.request_timeout_seconds, session
        )
        if args.test_notification:
            notifier.send_test(settings)
            print("PushPlus 测试消息已提交，请检查微信。")
            return 0
        token = _required_env("TRAVELPAYOUTS_TOKEN")
        providers = [
            TravelpayoutsDiscovery(
                token, settings.request_timeout_seconds, session, market
            )
            for market in settings.travelpayouts_markets
        ]
        state = MonitorState(
            settings.state_file,
            settings.known_baselines,
            settings.default_comparison_baseline_per_adult,
        )
        state.load()
        monitor = DealMonitor(
            settings, providers, CachedFareVerifier(), notifier, state
        )
        monitor.run(
            datetime.now(ZoneInfo("Asia/Shanghai")),
            dry_run=args.dry_run,
            initialize_baseline=args.initialize_baseline,
            scan_all=args.scan_all,
        )
        return 0
    except Exception as exc:
        logging.exception("监控运行失败")
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
