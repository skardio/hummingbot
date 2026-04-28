"""
Fill Quality Monitor — tracks expected vs actual fill prices to measure slippage.

Records per-fill slippage for post-hoc analysis and real-time monitoring.
Thread-safe for single-process use (relies on GIL for list append).

Part of the 17-upgrade trading bot roadmap:
  Item 15 — Fill Quality / Slippage Monitor
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class FillRecord:
    """Single fill event with expected vs actual price comparison."""

    symbol: str
    expected_price: float
    actual_price: float
    side: str           # "buy" | "sell"
    size_quote: float
    timestamp: float

    @property
    def slippage_pct(self) -> float:
        """
        Slippage as a percentage of the expected price.

        For *buy* orders, positive means we paid more than expected (unfavourable).
        For *sell* orders, positive means we received less than expected (unfavourable).
        """
        if self.expected_price <= 0:
            return 0.0
        if self.side == "buy":
            return ((self.actual_price - self.expected_price) / self.expected_price) * 100.0
        return ((self.expected_price - self.actual_price) / self.expected_price) * 100.0


class FillQualityMonitor:
    """
    Lightweight slippage tracker.

    Usage
    -----
    Call ``record_fill()`` on each confirmed fill.  Query ``avg_slippage_pct()``
    or ``summary()`` for monitoring dashboards or alerting.

    Parameters
    ----------
    max_records : int
        Circular buffer size — oldest records are discarded once exceeded.
    """

    def __init__(self, max_records: int = 500):
        self._records: List[FillRecord] = []
        self._max_records = max_records

    def record_fill(
        self,
        *,
        symbol: str,
        expected_price: float,
        actual_price: float,
        side: str,
        size_quote: float,
        timestamp: float,
    ) -> FillRecord:
        """
        Record a confirmed fill and return the ``FillRecord``.

        Parameters
        ----------
        symbol : str
            Trading pair.
        expected_price : float
            Price at which the order was placed (limit price or mid at placement).
        actual_price : float
            Actual fill price reported by the exchange.
        side : str
            "buy" or "sell".
        size_quote : float
            Fill size in quote currency.
        timestamp : float
            Unix timestamp of the fill.
        """
        rec = FillRecord(
            symbol=symbol,
            expected_price=expected_price,
            actual_price=actual_price,
            side=side,
            size_quote=size_quote,
            timestamp=timestamp,
        )
        self._records.append(rec)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]
        log.debug("FILL_QUALITY %s: slippage=%.3f%%", symbol, rec.slippage_pct)
        return rec

    def avg_slippage_pct(self, symbol: Optional[str] = None, last_n: int = 50) -> float:
        """
        Average slippage percentage over the last *last_n* fills.

        Parameters
        ----------
        symbol : str, optional
            Filter to fills for this trading pair.  ``None`` = all fills.
        last_n : int
            Number of most recent fills to consider.
        """
        records = [r for r in self._records if symbol is None or r.symbol == symbol]
        records = records[-last_n:]
        if not records:
            return 0.0
        return sum(r.slippage_pct for r in records) / len(records)

    def worst_slippage_pct(self, symbol: Optional[str] = None, last_n: int = 50) -> float:
        """Maximum single-fill slippage over the last *last_n* fills."""
        records = [r for r in self._records if symbol is None or r.symbol == symbol]
        records = records[-last_n:]
        if not records:
            return 0.0
        return max(r.slippage_pct for r in records)

    def summary(self) -> Dict:
        """Return an aggregated stats dict suitable for logging or metrics."""
        return {
            "total_fills": len(self._records),
            "avg_slippage_pct": round(self.avg_slippage_pct(), 4),
            "worst_slippage_pct": round(self.worst_slippage_pct(), 4),
        }
