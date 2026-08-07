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
    day = run_day.lower().strip()
    if day not in VALID_DAYS:
        raise ValueError(f"RUN_DAY must be one of {sorted(VALID_DAYS)}, got {run_day!r}")

    scheduled_job = getattr(schedule.every(), day)
    scheduled_job.at(run_time).do(job)
    LOGGER.info("Scheduler started: every %s at %s", day, run_time)

    while True:
        schedule.run_pending()
        time.sleep(30)
