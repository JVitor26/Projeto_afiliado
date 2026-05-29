from __future__ import annotations

import time

from .config import AppConfig
from .services.mining import MiningService
from .services.publishing import PublishingService


def _sleep_until_next_cycle(interval_seconds: int, cycle_start: float) -> None:
    remaining = cycle_start + interval_seconds - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    else:
        print("Next cycle is already due; starting immediately.")


def run_forever(
    config: AppConfig,
    mining: MiningService,
    publishing: PublishingService,
    *,
    publish_limit: int | None = None,
    limit_per_keyword: int | None = None,
) -> None:
    interval_seconds = max(config.interval_minutes, 1) * 60
    while True:
        cycle_start = time.monotonic()
        report = mining.mine(
            config.keywords,
            limit_per_keyword=limit_per_keyword or config.mine_limit_per_keyword,
        )
        print(
            f"Mining: imported={report.imported} skipped={report.skipped} "
            f"errors={len(report.errors)}"
        )
        for error in report.errors:
            print(f"  - {error}")

        sent = publishing.publish(limit=publish_limit or config.publish_limit)
        print(f"Publishing: sent={sent}")
        print(f"Sleeping {config.interval_minutes} minutes. Ctrl+C to stop.")
        _sleep_until_next_cycle(interval_seconds, cycle_start)
