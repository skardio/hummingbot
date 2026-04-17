"""
Grid Suitability Scorer — per-coin mean-reversion fitness for grid trading.

Scores each coin on how well it suits grid (mean-reversion) trading
based on recent price action. Trending coins score low, choppy/bouncy
coins score high.

Configuration (YAML):
    grid_suitability:
        enabled: true
        logging_only: true       # log scores without blocking
        min_grid_score: 0.30     # 0-1 threshold
        range_efficiency_max: 0.70
        lookback_candles: 48     # 48 × 5min = 4 hours
"""
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class GridScore:
    """Score result for a single coin."""
    symbol: str
    score: float                  # 0-1 composite
    range_efficiency: float       # 0-1, lower = choppier = better for grids
    mean_reversion: float         # 0-1, higher = reverts to mean more
    bounce_rate: float            # 0-1, higher = more reversals
    atr_consistency: float        # 0-1, higher = stable volatility
    reason: str                   # human-readable summary


class GridSuitabilityScorer:
    """
    Scores coins on grid-trading suitability using 5-min candle data.

    High score = good for grids (mean-reverting, bouncy, stable vol).
    Low score = bad for grids (trending, one-directional, spiky vol).
    """

    def __init__(self, config: dict, logger):
        self.config = config or {}
        self.logger = logger
        self.enabled = self.config.get('enabled', False)
        self.logging_only = self.config.get('logging_only', True)
        self.min_grid_score = self.config.get('min_grid_score', 0.30)
        self.range_efficiency_max = self.config.get('range_efficiency_max', 0.70)
        self.lookback_candles = self.config.get('lookback_candles', 48)
        self.last_scores: dict[str, GridScore] = {}  # Cache for post-hoc analysis

    def score_coin(self, symbol: str, candles: list) -> Optional[GridScore]:
        """
        Score a coin's grid suitability from its recent candles.

        Args:
            symbol: Trading pair (e.g., "QNT-USD")
            candles: List of CandleData objects (5-min OHLCV),
                     newest last.

        Returns:
            GridScore or None if insufficient data.
        """
        if not candles or len(candles) < 12:
            return None

        # Use the most recent N candles
        recent = candles[-self.lookback_candles:]
        closes = self._extract_closes(recent)
        if len(closes) < 12:
            return None

        re = self._range_efficiency(recent)
        mr = self._mean_reversion_score(closes)
        br = self._bounce_rate(closes)
        ac = self._atr_consistency(recent)

        composite = (
            (1.0 - re) * 0.35
            + mr * 0.30
            + br * 0.20
            + ac * 0.15
        )
        composite = max(0.0, min(1.0, composite))

        reason = self._build_reason(re, mr, br, ac, composite)

        return GridScore(
            symbol=symbol,
            score=composite,
            range_efficiency=re,
            mean_reversion=mr,
            bounce_rate=br,
            atr_consistency=ac,
            reason=reason,
        )

    def filter_coins(
        self, symbols: List[str], candles_by_symbol: dict
    ) -> List[str]:
        """
        Filter and re-rank a list of coin symbols by grid suitability.

        Args:
            symbols: Ordered list of symbols (from trend selection).
            candles_by_symbol: {symbol: [CandleData, ...]} mapping.

        Returns:
            Filtered/re-ranked symbol list. If logging_only, returns
            the original list unchanged (but logs scores).
        """
        if not self.enabled or not symbols:
            return list(symbols)

        scored: list[tuple[str, GridScore]] = []
        for sym in symbols:
            candles = candles_by_symbol.get(sym, [])
            gs = self.score_coin(sym, candles)
            if gs:
                scored.append((sym, gs))
                self.last_scores[sym] = gs  # Cache for custom_info
                self.logger.info(
                    f"📐 GridScore {sym}: {gs.score:.2f} "
                    f"(RE={gs.range_efficiency:.2f}, MR={gs.mean_reversion:.2f}, "
                    f"BR={gs.bounce_rate:.2f}, AC={gs.atr_consistency:.2f}) "
                    f"{'✅' if gs.score >= self.min_grid_score else '❌'} "
                    f"{gs.reason}"
                )
            else:
                # Not enough data — let it through
                scored.append((sym, None))
                self.logger.debug(
                    f"📐 GridScore {sym}: N/A (insufficient candle data)"
                )

        if self.logging_only:
            return list(symbols)

        # Active mode: filter out low-scoring coins, keep original
        # trend-rank order among passing coins.
        result = []
        for sym, gs in scored:
            if gs is None:
                # Insufficient data — allow through (fail-open)
                result.append(sym)
            elif gs.score >= self.min_grid_score:
                result.append(sym)
            else:
                self.logger.warning(
                    f"🚫 GridScore {sym}: {gs.score:.2f} < {self.min_grid_score} "
                    f"— skipped (not suitable for grid trading)"
                )

        return result

    # ── metrics ──────────────────────────────────────────────

    @staticmethod
    def _extract_closes(candles: list) -> np.ndarray:
        """Extract close prices as numpy array."""
        closes = []
        for c in candles:
            val = c.close if isinstance(c.close, float) else float(c.close)
            if val > 0:
                closes.append(val)
        return np.array(closes)

    @staticmethod
    def _range_efficiency(candles: list) -> float:
        """
        Directional movement / total range.
        1.0 = perfect trend, 0.0 = pure chop.
        """
        if len(candles) < 2:
            return 0.5

        first_close = float(candles[0].close)
        last_close = float(candles[-1].close)
        net_move = abs(last_close - first_close)

        total_range = 0.0
        for c in candles:
            h = float(c.high)
            lo = float(c.low)
            total_range += h - lo

        if total_range == 0:
            return 0.5
        return min(1.0, net_move / total_range)

    @staticmethod
    def _mean_reversion_score(closes: np.ndarray) -> float:
        """
        Measure tendency to revert to rolling mean.
        Uses lag-1 autocorrelation of returns — negative = mean-reverting.
        Returns 0-1 where 1.0 = strongly mean-reverting.
        """
        if len(closes) < 10:
            return 0.5

        returns = np.diff(closes) / closes[:-1]
        if len(returns) < 3:
            return 0.5

        # Lag-1 autocorrelation of returns
        r1 = returns[:-1]
        r2 = returns[1:]
        if np.std(r1) == 0 or np.std(r2) == 0:
            return 0.5

        autocorr = float(np.corrcoef(r1, r2)[0, 1])
        # autocorr in [-1, +1]. -1 = perfect mean reversion, +1 = momentum
        # Map to 0-1: -1 → 1.0, 0 → 0.5, +1 → 0.0
        return max(0.0, min(1.0, 0.5 - autocorr * 0.5))

    @staticmethod
    def _bounce_rate(closes: np.ndarray) -> float:
        """
        Fraction of candles that reverse direction (sign change in returns).
        More reversals = more grid fills.
        Returns 0-1.
        """
        if len(closes) < 4:
            return 0.5

        returns = np.diff(closes)
        if len(returns) < 3:
            return 0.5

        sign_changes = 0
        for i in range(1, len(returns)):
            if returns[i] * returns[i - 1] < 0:
                sign_changes += 1

        return sign_changes / (len(returns) - 1)

    @staticmethod
    def _atr_consistency(candles: list) -> float:
        """
        How consistent is the per-candle range over the period.
        Stable volatility = predictable grid spacing.
        Returns 0-1 where 1.0 = perfectly consistent.
        """
        if len(candles) < 6:
            return 0.5

        ranges = []
        for c in candles:
            h = float(c.high)
            lo = float(c.low)
            cl = float(c.close)
            if cl > 0:
                ranges.append((h - lo) / cl)

        if not ranges or max(ranges) == 0:
            return 0.5

        arr = np.array(ranges)
        mean_r = np.mean(arr)
        if mean_r == 0:
            return 0.5

        # Coefficient of variation (lower = more consistent)
        cv = float(np.std(arr) / mean_r)
        # CV typically 0.3-2.0. Map: 0 → 1.0, 1.0 → 0.5, 2.0 → 0.0
        return max(0.0, min(1.0, 1.0 - cv * 0.5))

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_reason(re: float, mr: float, br: float, ac: float,
                      score: float) -> str:
        parts = []
        if re > 0.6:
            parts.append(f"trending(RE={re:.2f})")
        elif re < 0.3:
            parts.append(f"choppy(RE={re:.2f})")
        if mr > 0.6:
            parts.append("mean-reverting")
        elif mr < 0.35:
            parts.append("momentum-driven")
        if br > 0.5:
            parts.append(f"bouncy({br:.0%})")
        if ac < 0.4:
            parts.append("volatile-ATR")
        elif ac > 0.7:
            parts.append("stable-ATR")
        if not parts:
            parts.append("neutral")
        return f"[{score:.2f}] " + ", ".join(parts)
