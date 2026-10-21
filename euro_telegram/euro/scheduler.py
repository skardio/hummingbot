from __future__ import annotations

import logging
import time
from collections.abc import Callable

import schedule

LOGGER = logging.getLogger(__name__)

VALID_DAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


def run_weekly(run_day: str, run_time: str, job: Callable[[], None]) -> None:
    days = [part.strip().lower() for part in run_day.split(",") if part.strip()]
    invalid = [day for day in days if day not in VALID_DAYS]
    if invalid or not days:
        raise ValueError(
            f"RUN_DAY must be one or more comma-separated values from {sorted(VALID_DAYS)}, got {run_day!r}"
        )

    for day in days:
        getattr(schedule.every(), day).at(run_time).do(job)
    LOGGER.info("Scheduler started: every %s at %s", ", ".join(days), run_time)

    while True:
        schedule.run_pending()
        time.sleep(30)
