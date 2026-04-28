"""Exit type classification and per-type cooldown durations."""
from __future__ import annotations

import datetime as _dt
from enum import Enum
from typing import Optional


class ExitType(str, Enum):
    """Classification of why a position was closed."""

    TAKE_PROFIT = "TP"
    SMALL_LOSS = "SMALL_LOSS"   # pnl < 0 but abs(pnl) < 1R
    STOP_LOSS = "SL"            # stop-loss triggered OR abs(pnl) >= 1R
    TREND_EXIT = "TREND"        # falling-knife / trend / timeout while declining
    UNKNOWN = "UNKNOWN"         # fallback — use short default cooldown


# Cooldown in seconds per exit type.
# None means "block until end of UTC day".
COOLDOWN_SECONDS: dict[ExitType, Optional[int]] = {
    ExitType.TAKE_PROFIT: 15 * 60,     # 15 min
    ExitType.SMALL_LOSS: 60 * 60,      # 60 min
    ExitType.STOP_LOSS: 4 * 60 * 60,   # 4 hours
    ExitType.TREND_EXIT: None,          # block until EOD UTC
    ExitType.UNKNOWN: 5 * 60,           # 5 min (conservative fallback)
}


def seconds_until_eod_utc(now: float) -> int:
    """Return seconds remaining until 00:00:00 UTC (start of next day)."""
    dt_now = _dt.datetime.utcfromtimestamp(now)
    dt_eod = (dt_now + _dt.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((dt_eod - dt_now).total_seconds()))


def cooldown_for_exit(exit_type: ExitType, now: float) -> int:
    """Return concrete cooldown duration in seconds for the given exit type."""
    duration = COOLDOWN_SECONDS.get(exit_type, 5 * 60)
    if duration is None:
        return seconds_until_eod_utc(now)
    return duration
