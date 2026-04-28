"""
ATR Grid Width Calibrator — Item 6

Analyzes recent ATR measurements to suggest optimal atr_multiplier values
for the grid bot. Keeps historical ATR per coin and computes percentile-based
multipliers so the grid range covers typical price movement.

Usage (offline / diagnostics):
    from multi_coin_grid_pro.scoring.atr_calibrator import ATRCalibrator
    cal = ATRCalibrator()
    cal.record("ETH-EUR", 2.3)
    suggestion = cal.suggest("ETH-EUR")
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

log = logging.getLogger(__name__)

# Optimal grid range should span ~2 ATR periods so orders actually get filled
_DEFAULT_MULTIPLIER_DOWN = 1.0
_DEFAULT_MULTIPLIER_UP = 1.5
_HISTORY_MAXLEN = 200  # Last N ATR measurements per coin


@dataclass
class ATRSuggestion:
    coin: str
    atr_pct_median: float
    atr_pct_p75: float       # 75th percentile — "normal" volatility
    atr_pct_p90: float       # 90th percentile — "high" volatility
    multiplier_down: float   # Suggested atr_multiplier_down
    multiplier_up: float     # Suggested atr_multiplier_up
    sample_count: int
    note: str


class ATRCalibrator:
    """
    Lightweight in-memory ATR history per coin.
    Records live ATR values during operation and provides suggestions.
    """

    def __init__(self, min_samples: int = 20):
        self._history: Dict[str, Deque[float]] = {}
        self.min_samples = min_samples

    def record(self, coin: str, atr_pct: float) -> None:
        """Record a new ATR% observation for a coin."""
        if atr_pct <= 0:
            return
        if coin not in self._history:
            self._history[coin] = deque(maxlen=_HISTORY_MAXLEN)
        self._history[coin].append(atr_pct)

    def suggest(self, coin: str) -> Optional[ATRSuggestion]:
        """
        Compute calibration suggestion for a coin.

        Returns None if insufficient samples.

        The grid should be wide enough to capture typical swing (p75 ATR)
        without being so wide that fills never happen (p90 ATR would rarely close).
        """
        history = self._history.get(coin)
        if not history or len(history) < self.min_samples:
            return None

        sorted_atr: List[float] = sorted(history)
        n = len(sorted_atr)
        median = sorted_atr[n // 2]
        p75 = sorted_atr[int(n * 0.75)]
        p90 = sorted_atr[int(n * 0.90)]

        # Downside: cover 1 ATR (buy grid should capture mean-reversion)
        # Upside: cover 1.5x ATR (TP grid needs room above entry)
        mult_down = round(max(0.8, min(2.0, p75 / median)), 2)
        mult_up = round(max(1.0, min(3.0, p90 / median * 1.2)), 2)

        note = "OK"
        if median > 5.0:
            note = "HIGH_VOLATILITY: consider reducing position size"
        elif median < 0.8:
            note = "LOW_VOLATILITY: grid may be too tight for fees"

        log.info(
            "ATR_CALIBRATION %s: median=%.2f%% p75=%.2f%% p90=%.2f%% "
            "→ mult_down=%.2f mult_up=%.2f (%s)",
            coin, median, p75, p90, mult_down, mult_up, note
        )
        return ATRSuggestion(
            coin=coin,
            atr_pct_median=round(median, 3),
            atr_pct_p75=round(p75, 3),
            atr_pct_p90=round(p90, 3),
            multiplier_down=mult_down,
            multiplier_up=mult_up,
            sample_count=n,
            note=note,
        )

    def suggest_all(self) -> Dict[str, ATRSuggestion]:
        """Return suggestions for all coins with sufficient history."""
        return {
            coin: s
            for coin in self._history
            if (s := self.suggest(coin)) is not None
        }
