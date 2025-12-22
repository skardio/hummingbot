"""
Regime detection for adaptive filtering.
Detects BULL, CHOP, or BEAR market regimes based on multi-timeframe analysis.
"""
from dataclasses import dataclass
from datetime import datetime
# from decimal import Decimal  # noqa: F401
from typing import Dict, List

import numpy as np


@dataclass
class RegimeMetrics:
    """Market regime measurement data."""
    trend_1h: float
    trend_4h: float
    trend_24h: float
    consensus: float
    atr_pct: float
    atr_expansion: float
    range_efficiency: float
    pullback_depth_pct: float
    timestamp: datetime


@dataclass
class RegimeState:
    """Current regime classification."""
    regime: str  # "BULL", "CHOP", "BEAR"
    score: float
    confidence: float
    duration_minutes: int
    reason: str
    metrics: RegimeMetrics


class RegimeDetector:
    """
    Detects market regime based on multi-timeframe analysis.
    Uses hysteresis to prevent flip-flopping.
    """

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.current_regime = "CHOP"  # Start conservative
        self.regime_start_time = datetime.now()
        self.regime_history = []  # Track regime changes

    def calculate_metrics(self, trend_data: Dict, candles_1h: List[Dict], candles_4h: List[Dict]) -> RegimeMetrics:
        """
        Calculate regime metrics from price data.

        Args:
            trend_data: {
                'trend_1h': float,
                'trend_4h': float,
                'trend_24h': float,
                'consensus': float
            }
            candles_1h: List of 1h OHLCV dicts
            candles_4h: List of 4h OHLCV dicts

        Returns:
            RegimeMetrics object
        """
        # Extract trends (already calculated by TrendCalculator)
        trend_1h = trend_data.get('trend_1h', 0.0)
        trend_4h = trend_data.get('trend_4h', 0.0)
        trend_24h = trend_data.get('trend_24h', 0.0)
        consensus = trend_data.get('consensus', 0.0)

        # Calculate ATR expansion
        if len(candles_1h) >= 38:
            atr_current = self._calculate_atr(candles_1h[-14:])
            atr_24h_ago = self._calculate_atr(candles_1h[-38:-24])
            atr_expansion = ((atr_current - atr_24h_ago) / atr_24h_ago * 100) if atr_24h_ago > 0 else 0.0
        else:
            atr_current = 0.0
            atr_expansion = 0.0

        # Calculate range efficiency (directional movement vs total range)
        range_efficiency = self._calculate_range_efficiency(candles_4h[-24:] if len(candles_4h) >= 24 else candles_4h)

        # Calculate pullback depth from 4h high
        pullback_depth = self._calculate_pullback_depth(candles_4h[-24:] if len(candles_4h) >= 24 else candles_4h)

        return RegimeMetrics(
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            trend_24h=trend_24h,
            consensus=consensus,
            atr_pct=atr_current,
            atr_expansion=atr_expansion,
            range_efficiency=range_efficiency,
            pullback_depth_pct=pullback_depth,
            timestamp=datetime.now()
        )

    def detect_regime(self, metrics: RegimeMetrics) -> RegimeState:
        """
        Classify market regime based on metrics.

        Returns:
            RegimeState with classification and reasoning
        """
        # Calculate regime score
        score = self._calculate_regime_score(metrics)
        confidence = self._calculate_confidence(metrics)

        # Classify with hysteresis
        new_regime = self._classify_with_hysteresis(score, confidence)

        # Calculate duration in current regime
        duration_min = int((datetime.now() - self.regime_start_time).seconds / 60)

        # Generate reasoning
        reason = self._generate_reason(metrics, score, new_regime)

        # Update regime if changed
        if new_regime != self.current_regime:
            self._log_regime_change(new_regime, score, reason)
            self.current_regime = new_regime
            self.regime_start_time = datetime.now()
            duration_min = 0

        return RegimeState(
            regime=new_regime,
            score=score,
            confidence=confidence,
            duration_minutes=duration_min,
            reason=reason,
            metrics=metrics
        )

    def _calculate_regime_score(self, m: RegimeMetrics) -> float:
        """
        Weighted score combining trend + volatility.
        Range: -100 to +100 (negative = bearish, positive = bullish)
        """
        # Use consensus as primary signal (it's already weighted)
        score = (
            m.consensus * 0.80 +      # Consensus trend (80%)
            m.atr_expansion * 0.20    # Volatility confirmation (20%)
        )

        # Apply range efficiency multiplier
        # High efficiency (trending) = amplify score
        # Low efficiency (choppy) = dampen score
        efficiency_mult = 0.5 + (m.range_efficiency * 1.0)
        score *= efficiency_mult

        return score

    def _calculate_confidence(self, m: RegimeMetrics) -> float:
        """
        Confidence in regime classification (0-1).
        High when timeframes align and efficiency is high.
        """
        # Timeframe alignment: all pointing same direction?
        trend_alignment = 1.0 - (
            abs(m.trend_1h - m.trend_4h) / 20.0 +
            abs(m.trend_4h - m.trend_24h) / 20.0
        ) / 2.0
        trend_alignment = max(0.0, min(1.0, trend_alignment))

        # Range efficiency: higher = more confident
        efficiency = m.range_efficiency

        # Volatility confirmation: ATR expanding in trend direction?
        vol_confirm = 1.0 if (
            (m.consensus > 0 and m.atr_expansion > 0) or
            (m.consensus < 0 and m.atr_expansion > 0)
        ) else 0.5

        confidence = (
            trend_alignment * 0.50 +
            efficiency * 0.30 +
            vol_confirm * 0.20
        )

        return max(0.0, min(1.0, confidence))

    def _classify_with_hysteresis(self, score: float, confidence: float) -> str:
        """
        Classify regime with hysteresis buffer zones.
        Prevents flip-flopping by requiring stronger signal to switch.
        """
        # Get config thresholds
        bull_min = self.config.get('bull_score_min', 5.0)
        chop_min = self.config.get('chop_score_min', -3.0)
        bear_max = self.config.get('bear_score_max', -3.0)
        min_confidence = self.config.get('min_confidence', 0.65)

        # Check minimum duration in current regime
        duration_sec = (datetime.now() - self.regime_start_time).seconds
        min_duration = self.config.get(f'{self.current_regime.lower()}_min_duration_sec', 900)

        if duration_sec < min_duration:
            # Too early to switch - stay in current regime
            return self.current_regime

        # Apply hysteresis buffers based on current regime
        hysteresis_buffer = self.config.get('hysteresis_buffer', 1.0)

        if self.current_regime == "BULL":
            # Require score drop below threshold with buffer
            if score < (bull_min - hysteresis_buffer) and confidence >= min_confidence:
                return "CHOP" if score >= chop_min else "BEAR"
            return "BULL"

        elif self.current_regime == "CHOP":
            # Allow switch to BULL/BEAR with buffer
            if score > (bull_min + hysteresis_buffer) and confidence >= min_confidence:
                return "BULL"
            if score < (bear_max - hysteresis_buffer) and confidence >= min_confidence:
                return "BEAR"
            return "CHOP"

        elif self.current_regime == "BEAR":
            # Require score rise above threshold with buffer
            if score > (chop_min + hysteresis_buffer) and confidence >= min_confidence:
                return "CHOP" if score < bull_min else "BULL"
            return "BEAR"

        # Default: stay in current regime
        return self.current_regime

    def _calculate_atr(self, candles: list) -> float:
        """Calculate ATR% over candles."""
        if len(candles) < 2:
            return 0.0

        true_ranges = []
        for i in range(1, len(candles)):
            high = float(candles[i].get('high', 0))
            low = float(candles[i].get('low', 0))
            close = float(candles[i].get('close', 0))
            prev_close = float(candles[i - 1].get('close', 0))

            if close == 0:
                continue

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr / close * 100)

        return float(np.mean(true_ranges)) if true_ranges else 0.0

    def _calculate_range_efficiency(self, candles: list) -> float:
        """
        Range efficiency: directional movement / total range.
        1.0 = perfect trend, 0.0 = pure chop
        """
        if len(candles) < 2:
            return 0.5

        # Net directional movement
        close_first = float(candles[0].get('close', 0))
        close_last = float(candles[-1].get('close', 0))
        net_move = abs(close_last - close_first)

        # Total range (sum of all candle ranges)
        total_range = sum(
            float(c.get('high', 0)) - float(c.get('low', 0))
            for c in candles
        )

        return net_move / total_range if total_range > 0 else 0.0

    def _calculate_pullback_depth(self, candles: list) -> float:
        """
        Pullback depth from recent high.
        Negative = pullback from high, positive = rally from low
        """
        if len(candles) < 2:
            return 0.0

        high = max(float(c.get('high', 0)) for c in candles)
        low = min(float(c.get('low', 0)) for c in candles)
        current = float(candles[-1].get('close', 0))

        if high == 0:
            return 0.0

        # Distance from high
        from_high = (current - high) / high * 100

        # Distance from low
        from_low = (current - low) / low * 100 if low > 0 else 0.0

        # Return whichever is smaller (we're near high = small negative)
        return from_high if abs(from_high) < abs(from_low) else from_low

    def _generate_reason(self, m: RegimeMetrics, score: float, regime: str) -> str:
        """Generate human-readable reasoning for regime choice."""
        reasons = []

        if regime == "BULL":
            reasons.append(f"Strong consensus trend +{m.consensus:.1f}%")
            if m.atr_expansion > 5:
                reasons.append(f"Volatility expanding (+{m.atr_expansion:.1f}%)")
            if m.range_efficiency > 0.7:
                reasons.append(f"High directional efficiency ({m.range_efficiency:.2f})")
            reasons.append(f"Score {score:.1f} > threshold 5.0")

        elif regime == "CHOP":
            reasons.append(f"Neutral consensus trend {m.consensus:+.1f}%")
            if m.range_efficiency < 0.5:
                reasons.append(f"Low directional efficiency ({m.range_efficiency:.2f})")
            if abs(m.atr_expansion) < 5:
                reasons.append("Volatility compressed")
            reasons.append(f"Score {score:.1f} in [-3.0, 5.0] range")

        elif regime == "BEAR":
            reasons.append(f"Negative consensus trend {m.consensus:.1f}%")
            if m.atr_expansion > 5:
                reasons.append(f"Volatility expanding ({m.atr_expansion:.1f}%)")
            reasons.append(f"Score {score:.1f} < threshold -3.0")

        return " | ".join(reasons)

    def _log_regime_change(self, new_regime: str, score: float, reason: str):
        """Log regime transitions for analysis."""
        self.logger.warning(
            f"⚡ REGIME CHANGE: {self.current_regime} → {new_regime}\n"
            f"   Score: {score:.1f}\n"
            f"   Reason: {reason}"
        )

        self.regime_history.append({
            'timestamp': datetime.now(),
            'from': self.current_regime,
            'to': new_regime,
            'score': score,
            'reason': reason
        })

        # Keep last 50 transitions
        if len(self.regime_history) > 50:
            self.regime_history = self.regime_history[-50:]
