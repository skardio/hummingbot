"""
ST-05a: Execution Funnel Tracker — live in-memory counters for the
considered → allowed → approved → started pipeline.

Accumulates per-tick results and periodically logs a compact summary
so operators can verify the funnel balance without post-hoc JSONL parsing.

Design:
- Thread-safe via simple dict operations (GIL-protected)
- Rolling window: resets every ``window_sec`` seconds (default 15 min)
- Never raises — all methods are fault-tolerant
"""

import logging
import time
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


class ExecutionFunnelTracker:
    """Accumulates funnel stats and emits periodic summaries."""

    def __init__(self, window_sec: int = 900):
        self.window_sec = window_sec
        self.reset()

    # ── recording API ─────────────────────────────────────────────

    def record_considered(self, count: int) -> None:
        """Number of coins in the monitored pool this tick."""
        self._considered += count

    def record_allowed(self, symbol: str) -> None:
        """Coin passed SmartEntry filter."""
        self._allowed += 1

    def record_rejected(self, symbol: str, filter_name: str) -> None:
        """Coin rejected by a specific filter."""
        self._rejected += 1
        self._reject_reasons[filter_name] += 1

    def record_approved(self, symbol: str) -> None:
        """Coin passed all filters including MTF."""
        self._approved += 1

    def record_started(self, symbol: str) -> None:
        """Grid executor actually created for this coin."""
        self._started += 1

    def record_tick(self) -> None:
        """Increment tick counter."""
        self._ticks += 1

    # ── periodic summary ──────────────────────────────────────────

    def maybe_log_summary(self) -> Optional[dict]:
        """Log summary if window has elapsed.  Returns summary dict or None."""
        now = time.time()
        if now - self._window_start < self.window_sec:
            return None

        summary = self.get_summary()
        if summary["ticks"] > 0:
            logger.info(f"📈 Execution funnel ({self.window_sec}s window): {summary}")
        self.reset()
        return summary

    def get_summary(self) -> dict:
        """Return current accumulated stats without resetting."""
        total_decisions = self._allowed + self._rejected
        return {
            "ticks": self._ticks,
            "considered": self._considered,
            "allowed": self._allowed,
            "rejected": self._rejected,
            "approved": self._approved,
            "started": self._started,
            "allow_rate_pct": (
                round(self._allowed / total_decisions * 100, 1)
                if total_decisions > 0 else 0.0
            ),
            "start_rate_pct": (
                round(self._started / self._approved * 100, 1)
                if self._approved > 0 else 0.0
            ),
            "reject_reasons": dict(self._reject_reasons),
            "window_sec": self.window_sec,
        }

    def reset(self) -> None:
        """Reset all counters for a new window."""
        self._window_start = time.time()
        self._ticks = 0
        self._considered = 0
        self._allowed = 0
        self._rejected = 0
        self._approved = 0
        self._started = 0
        self._reject_reasons: Counter = Counter()
