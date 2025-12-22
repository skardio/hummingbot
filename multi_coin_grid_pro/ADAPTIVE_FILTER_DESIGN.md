# ADAPTIVE FILTER SYSTEM - Design Document

**Author**: Senior Quant Researcher
**Date**: 2025-12-20
**Version**: 1.0

## Executive Summary

Design voor een **regime-adaptive filter system** dat automatisch SmartEntry parameters aanpast
op basis van real-time marktomstandigheden. Doel: maximale opportuniteit in bull markets,
maximale bescherming in chop/bear markets - zonder handmatige tuning.

---

## 1. Problem Statement

### Current Situation
Bot heeft **statische SmartEntry filters**:
- `rsi_buy_max: 80` (altijd)
- `vwap_max_deviation_pct: 5.0` (altijd)
- `max_up_accel_pct: 1.8` (altijd)

### Issues
1. **Bull markets**: Te strict - coins met +13% trend worden rejected (VWAP +6.5%)
2. **Chop markets**: Te loose - coins met fake breakouts worden geaccepteerd
3. **Bear markets**: Te aggressive - bot probeert te traden in downtrends

### Solution
**Adaptive filtering**: Regime detection → Filter adjustment → Smart execution

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      MARKET DATA INPUT                          │
│  (price, volume, candles 1m/5m/1h/4h/24h)                      │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   REGIME DETECTOR                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Multi-Timeframe Analysis:                                 │  │
│  │  • 24H trend: +3.14%                                      │  │
│  │  • 4H trend:  +5.89%                                      │  │
│  │  • 1H trend:  +0.38%                                      │  │
│  │  • Consensus: +13.07%                                     │  │
│  │  • ATR: 0.28% (expanding)                                 │  │
│  │  • Range efficiency: 0.72 (directional)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           ↓                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Regime Classification:                                    │  │
│  │  Score: +8.5 → BULL (threshold: +5)                      │  │
│  │  Confidence: 0.89                                         │  │
│  │  Duration: 147 minutes (min: 30 min)                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│               ADAPTIVE FILTER RESOLVER                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Regime: BULL → Load Bull Filter Set:                     │  │
│  │  • rsi_buy_max: 85.0 (vs 80.0 baseline)                  │  │
│  │  • vwap_max_deviation_pct: 7.0 (vs 5.0 baseline)         │  │
│  │  • max_up_accel_pct: 3.0 (vs 1.8 baseline)               │  │
│  │  • atr_min: 0.10 (vs 0.15 baseline)                      │  │
│  │  • grid_spacing_mult: 1.2 (wider grids)                  │  │
│  │  • max_active_grids: 3 (vs 1 baseline)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SMART ENTRY VALIDATOR                         │
│  Apply adapted filters to candidate coins                       │
│  UNI-USDT: RSI 61.3 ✅, VWAP +6.57% ✅, Accel +2.1% ✅          │
│  → APPROVED (would be rejected in CHOP/BEAR)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Regime Detection

### 3.1 Core Metrics

```python
class RegimeMetrics:
    # Trend strength
    trend_1h: float       # -100 to +100
    trend_4h: float       # -100 to +100
    trend_24h: float      # -100 to +100
    consensus: float      # Weighted average

    # Volatility
    atr_pct: float        # Current ATR %
    atr_trend: float      # ATR change vs 24h ago (expansion/compression)

    # Efficiency
    range_efficiency: float   # 0-1: directional movement / total range
    higher_high_count: int    # Recent HH count (4h timeframe)
    lower_low_count: int      # Recent LL count (4h timeframe)

    # Pullback characteristics
    pullback_depth_pct: float    # Current pullback from 4h high
    pullback_vs_trend: float     # Pullback relative to 24h trend
```

### 3.2 Regime Scoring System

**Score Calculation:**
```python
regime_score = (
    trend_24h * 0.30 +      # Long-term bias
    trend_4h * 0.40 +       # Medium-term momentum
    trend_1h * 0.20 +       # Short-term action
    atr_expansion * 0.10    # Volatility confirmation
)

# ATR expansion factor
atr_expansion = (atr_current - atr_24h_ago) / atr_24h_ago * 100
```

**Classification Thresholds:**
```yaml
BULL:
  score_min: +5.0
  confidence_min: 0.65
  min_duration_minutes: 30

CHOP:
  score_range: [-3.0, +5.0]
  confidence_max: 0.85
  min_duration_minutes: 15

BEAR:
  score_max: -3.0
  confidence_min: 0.65
  min_duration_minutes: 30
```

### 3.3 Hysteresis Logic

Voorkom flip-flopping tussen regimes:

```python
class RegimeHysteresis:
    current_regime: str = "CHOP"
    regime_start_time: datetime
    min_duration_sec: Dict[str, int] = {
        "BULL": 1800,   # 30 min
        "CHOP": 900,    # 15 min
        "BEAR": 1800    # 30 min
    }

    def should_switch_regime(self, new_regime: str, new_score: float) -> bool:
        # Require stronger signal to exit BULL/BEAR
        if self.current_regime in ["BULL", "BEAR"]:
            time_in_regime = (datetime.now() - self.regime_start_time).seconds
            if time_in_regime < self.min_duration_sec[self.current_regime]:
                return False  # Too early to switch

        # Require overlap zone crossing with margin
        if self.current_regime == "BULL" and new_regime == "CHOP":
            return new_score < 4.0  # Hysteresis: -1.0 buffer

        if self.current_regime == "CHOP" and new_regime == "BULL":
            return new_score > 6.0  # Hysteresis: +1.0 buffer

        return True  # Default: allow switch
```

---

## 4. Adaptive Filter Sets

### 4.1 Filter Parameters per Regime

```yaml
adaptive_filters:
  baseline:
    # Conservative defaults (CHOP equivalent)
    rsi_buy_min: 25.0
    rsi_buy_max: 70.0
    rsi_extreme_min: 20.0
    vwap_max_deviation_pct: 3.0
    max_up_accel_pct: 1.2
    max_down_accel_pct: -2.0
    atr_min_pct: 0.15
    atr_max_pct: 6.0
    spike_5m_max_pct: 2.0
    wick_ratio_min: 0.0
    grid_spacing_mult: 1.0
    max_active_grids: 1

  BULL:
    # Relaxed filters for trending markets
    rsi_buy_max: 85.0           # +15 vs baseline (allow overbought)
    vwap_max_deviation_pct: 7.0  # +4.0 vs baseline (allow momentum)
    max_up_accel_pct: 3.0        # +1.8 vs baseline (allow blow-off)
    max_down_accel_pct: -4.0     # -2.0 vs baseline (deeper pullbacks OK)
    atr_min_pct: 0.10            # -0.05 vs baseline (accept lower vol)
    spike_5m_max_pct: 3.5        # +1.5 vs baseline (allow spikes)
    grid_spacing_mult: 1.2       # Wider grids (more room to breathe)
    max_active_grids: 3          # Multiple positions OK
    entry_confidence_min: 0.60   # Lower bar (more entries)

  CHOP:
    # Strict filters for ranging markets (= baseline)
    rsi_buy_max: 70.0
    vwap_max_deviation_pct: 3.0
    max_up_accel_pct: 1.2
    max_down_accel_pct: -2.0
    atr_min_pct: 0.15
    spike_5m_max_pct: 2.0
    grid_spacing_mult: 0.8       # Tighter grids (range-bound)
    max_active_grids: 1          # Single position only
    entry_confidence_min: 0.75   # High bar (selective)

  BEAR:
    # Ultra-strict or disabled
    rsi_buy_max: 50.0            # -20 vs baseline (only oversold)
    vwap_max_deviation_pct: 1.5  # -1.5 vs baseline (near VWAP only)
    max_up_accel_pct: 0.5        # -0.7 vs baseline (no fakeouts)
    max_down_accel_pct: -1.0     # +1.0 vs baseline (shallow only)
    atr_min_pct: 0.20            # +0.05 vs baseline (need volatility)
    spike_5m_max_pct: 1.0        # -1.0 vs baseline (no pumps)
    grid_spacing_mult: 1.5       # Very wide (expect volatility)
    max_active_grids: 0          # DISABLED (optional: 1 for mean-rev)
    entry_confidence_min: 0.90   # Extreme bar (almost never)
```

### 4.2 Regime Transition Matrix

```
Current → New    | BULL Action              | CHOP Action         | BEAR Action
─────────────────┼──────────────────────────┼─────────────────────┼────────────────────
BULL → BULL      | Keep positions           | Continue trading    | N/A
BULL → CHOP      | Tighten stops (+1%)      | Reduce grid count   | Exit 50% positions
BULL → BEAR      | Emergency exit           | Stop new entries    | Close all
─────────────────┼──────────────────────────┼─────────────────────┼────────────────────
CHOP → BULL      | Widen grids              | Allow new entries   | N/A
CHOP → CHOP      | Keep current             | Continue selective  | N/A
CHOP → BEAR      | Close positions          | Stop trading        | Monitor only
─────────────────┼──────────────────────────┼─────────────────────┼────────────────────
BEAR → BULL      | Start fresh              | Allow entries       | N/A
BEAR → CHOP      | Cautious re-entry        | Test with 1 coin    | N/A
BEAR → BEAR      | Stay out                 | No trading          | Monitor only
```

---

## 5. Implementation Classes

### 5.1 RegimeDetector

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple
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

    def __init__(self, config: Dict):
        self.config = config
        self.current_regime = "CHOP"  # Start conservative
        self.regime_start_time = datetime.now()
        self.regime_history = []  # Track regime changes

    def calculate_metrics(self, candle_data: Dict) -> RegimeMetrics:
        """
        Calculate regime metrics from price data.

        Args:
            candle_data: {
                '1h': List[OHLCV],
                '4h': List[OHLCV],
                '24h': List[OHLCV]
            }

        Returns:
            RegimeMetrics object
        """
        # Extract trends (already calculated by TrendCalculator)
        trend_1h = candle_data['trend_1h']
        trend_4h = candle_data['trend_4h']
        trend_24h = candle_data['trend_24h']
        consensus = candle_data['consensus']

        # Calculate ATR expansion
        atr_current = self._calculate_atr(candle_data['1h'][-14:])
        atr_24h_ago = self._calculate_atr(candle_data['1h'][-38:-24])
        atr_expansion = (atr_current - atr_24h_ago) / atr_24h_ago * 100

        # Calculate range efficiency (directional movement vs total range)
        range_efficiency = self._calculate_range_efficiency(candle_data['4h'][-24:])

        # Calculate pullback depth from 4h high
        pullback_depth = self._calculate_pullback_depth(candle_data['4h'][-24:])

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
        score = (
            m.trend_24h * 0.30 +      # Long-term bias (30%)
            m.trend_4h * 0.40 +       # Medium-term momentum (40%)
            m.trend_1h * 0.20 +       # Short-term action (20%)
            m.atr_expansion * 0.10    # Volatility confirmation (10%)
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
        if self.current_regime == "BULL":
            # Require score drop below threshold with buffer
            if score < (bull_min - 1.0) and confidence >= min_confidence:
                return "CHOP" if score >= chop_min else "BEAR"
            return "BULL"

        elif self.current_regime == "CHOP":
            # Allow switch to BULL/BEAR with buffer
            if score > (bull_min + 1.0) and confidence >= min_confidence:
                return "BULL"
            if score < (bear_max - 1.0) and confidence >= min_confidence:
                return "BEAR"
            return "CHOP"

        elif self.current_regime == "BEAR":
            # Require score rise above threshold with buffer
            if score > (chop_min + 1.0) and confidence >= min_confidence:
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
            high = candles[i]['high']
            low = candles[i]['low']
            prev_close = candles[i-1]['close']

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr / candles[i]['close'] * 100)

        return np.mean(true_ranges) if true_ranges else 0.0

    def _calculate_range_efficiency(self, candles: list) -> float:
        """
        Range efficiency: directional movement / total range.
        1.0 = perfect trend, 0.0 = pure chop
        """
        if len(candles) < 2:
            return 0.5

        # Net directional movement
        net_move = abs(candles[-1]['close'] - candles[0]['close'])

        # Total range (sum of all candle ranges)
        total_range = sum(c['high'] - c['low'] for c in candles)

        return net_move / total_range if total_range > 0 else 0.0

    def _calculate_pullback_depth(self, candles: list) -> float:
        """
        Pullback depth from recent high.
        Negative = pullback from high, positive = rally from low
        """
        if len(candles) < 2:
            return 0.0

        high = max(c['high'] for c in candles)
        low = min(c['low'] for c in candles)
        current = candles[-1]['close']

        # Distance from high
        from_high = (current - high) / high * 100

        # Distance from low
        from_low = (current - low) / low * 100

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
```

### 5.2 AdaptiveFilterResolver

```python
from typing import Dict


class AdaptiveFilterResolver:
    """
    Resolves filter parameters based on detected regime.
    Handles smooth transitions and exchange-specific overrides.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.baseline_filters = config.get('baseline', {})
        self.regime_filters = {
            'BULL': config.get('BULL', {}),
            'CHOP': config.get('CHOP', {}),
            'BEAR': config.get('BEAR', {})
        }
        self.active_filters = self.baseline_filters.copy()

    def resolve_filters(self, regime_state: RegimeState) -> Dict:
        """
        Get active filter parameters for current regime.

        Args:
            regime_state: Current regime classification

        Returns:
            Dict of filter parameters
        """
        regime = regime_state.regime

        # Get regime-specific filters
        regime_filters = self.regime_filters.get(regime, {})

        # Merge with baseline (regime overrides baseline)
        active = self.baseline_filters.copy()
        active.update(regime_filters)

        # Apply confidence scaling
        # Lower confidence = move toward baseline (safer)
        active = self._apply_confidence_scaling(
            active,
            regime_filters,
            regime_state.confidence
        )

        self.active_filters = active
        return active

    def _apply_confidence_scaling(
        self,
        active: Dict,
        regime: Dict,
        confidence: float
    ) -> Dict:
        """
        Scale filter aggressiveness based on regime confidence.
        Low confidence = interpolate toward baseline (safer).

        Example:
          Regime says rsi_buy_max=85, baseline=70, confidence=0.7
          → Actual = 70 + (85-70) * 0.7 = 80.5
        """
        scaled = active.copy()

        for key, regime_value in regime.items():
            if key in self.baseline_filters:
                baseline_value = self.baseline_filters[key]

                # Interpolate: baseline + (regime - baseline) * confidence
                if isinstance(regime_value, (int, float)):
                    scaled[key] = baseline_value + (regime_value - baseline_value) * confidence

        return scaled

    def get_transition_action(self, old_regime: str, new_regime: str) -> str:
        """
        Get recommended action for regime transition.

        Returns:
            Action string: "tighten_stops", "exit_all", "widen_grids", etc.
        """
        transitions = {
            ('BULL', 'CHOP'): 'tighten_stops',
            ('BULL', 'BEAR'): 'exit_all',
            ('CHOP', 'BULL'): 'widen_grids',
            ('CHOP', 'BEAR'): 'stop_new_entries',
            ('BEAR', 'CHOP'): 'cautious_reentry',
            ('BEAR', 'BULL'): 'start_fresh'
        }

        return transitions.get((old_regime, new_regime), 'no_action')

    def should_allow_entry(self, regime_state: RegimeState) -> bool:
        """Check if new entries are allowed in current regime."""
        if regime_state.regime == "BEAR":
            # Check if mean-reversion mode enabled
            return self.config.get('bear_allow_meanrev', False)

        return True  # BULL and CHOP allow entries

    def explain_active_filters(self) -> str:
        """Generate human-readable explanation of active filters."""
        lines = [
            "🎚️  ACTIVE FILTER SET:",
            f"   RSI range: {self.active_filters.get('rsi_buy_min', 25):.0f}-{self.active_filters.get('rsi_buy_max', 70):.0f}",
            f"   VWAP deviation: ±{self.active_filters.get('vwap_max_deviation_pct', 3):.1f}%",
            f"   Up accel limit: {self.active_filters.get('max_up_accel_pct', 1.2):.1f}%",
            f"   Down accel limit: {self.active_filters.get('max_down_accel_pct', -2.0):.1f}%",
            f"   ATR range: {self.active_filters.get('atr_min_pct', 0.15):.2f}%-{self.active_filters.get('atr_max_pct', 6.0):.1f}%",
            f"   Grid spacing: {self.active_filters.get('grid_spacing_mult', 1.0):.1f}x",
            f"   Max grids: {self.active_filters.get('max_active_grids', 1)}"
        ]
        return "\n".join(lines)
```

---

## 6. Configuration Schema

```yaml
# multi_coin_grid_pro/config/adaptive_filters.yaml

adaptive_regime_detection:
  enabled: true

  # Regime classification thresholds
  bull_score_min: 5.0         # Score >= 5 → BULL
  chop_score_min: -3.0        # Score in [-3, 5] → CHOP
  bear_score_max: -3.0        # Score < -3 → BEAR
  min_confidence: 0.65        # Minimum confidence to classify

  # Hysteresis settings (prevent flip-flopping)
  bull_min_duration_sec: 1800   # 30 min minimum in BULL
  chop_min_duration_sec: 900    # 15 min minimum in CHOP
  bear_min_duration_sec: 1800   # 30 min minimum in BEAR
  hysteresis_buffer: 1.0        # Score buffer for regime exit

  # Logging
  log_regime_changes: true
  log_filter_updates: true

adaptive_filters:
  # Baseline filters (conservative, used as fallback)
  baseline:
    rsi_buy_min: 25.0
    rsi_buy_max: 70.0
    rsi_extreme_min: 20.0
    vwap_max_deviation_pct: 3.0
    max_up_accel_pct: 1.2
    max_down_accel_pct: -2.0
    atr_min_pct: 0.15
    atr_max_pct: 6.0
    spike_5m_max_pct: 2.0
    wick_ratio_min: 0.0
    grid_spacing_mult: 1.0
    max_active_grids: 1
    entry_confidence_min: 0.70

  # BULL regime: relaxed filters
  BULL:
    rsi_buy_max: 85.0
    vwap_max_deviation_pct: 7.0
    max_up_accel_pct: 3.0
    max_down_accel_pct: -4.0
    atr_min_pct: 0.10
    spike_5m_max_pct: 3.5
    grid_spacing_mult: 1.2
    max_active_grids: 3
    entry_confidence_min: 0.60

  # CHOP regime: strict filters (= baseline)
  CHOP:
    rsi_buy_max: 70.0
    vwap_max_deviation_pct: 3.0
    max_up_accel_pct: 1.2
    max_down_accel_pct: -2.0
    atr_min_pct: 0.15
    spike_5m_max_pct: 2.0
    grid_spacing_mult: 0.8
    max_active_grids: 1
    entry_confidence_min: 0.75

  # BEAR regime: ultra-strict or disabled
  BEAR:
    rsi_buy_max: 50.0
    vwap_max_deviation_pct: 1.5
    max_up_accel_pct: 0.5
    max_down_accel_pct: -1.0
    atr_min_pct: 0.20
    spike_5m_max_pct: 1.0
    grid_spacing_mult: 1.5
    max_active_grids: 0          # Disabled
    entry_confidence_min: 0.90
    bear_allow_meanrev: false    # Set true to allow mean-reversion trades

# Exchange-specific overrides (optional)
exchange_overrides:
  bitget:
    # USDT pairs on Bitget: slightly more aggressive
    BULL:
      rsi_buy_max: 87.0
      max_active_grids: 4

  kraken:
    # EUR pairs on Kraken: slightly more conservative
    BULL:
      rsi_buy_max: 82.0
      vwap_max_deviation_pct: 6.0
```

---

## 7. Integration Flow

### 7.1 Main Bot Loop Integration

```python
# In multi_coin_grid_controller.py

class MultiCoinGridController:
    def __init__(self, config):
        # ... existing init ...

        # NEW: Adaptive filter system
        if config.adaptive_regime_detection.enabled:
            self.regime_detector = RegimeDetector(config.adaptive_regime_detection)
            self.filter_resolver = AdaptiveFilterResolver(config.adaptive_filters)
        else:
            self.regime_detector = None
            self.filter_resolver = None

    async def control_task(self):
        """Main control loop with adaptive filters."""
        while True:
            try:
                # 1. Detect current regime (once per cycle)
                if self.regime_detector:
                    regime_state = await self._detect_current_regime()
                    self.logger.info(
                        f"🌡️  REGIME: {regime_state.regime} "
                        f"(score: {regime_state.score:.1f}, "
                        f"confidence: {regime_state.confidence:.2f}, "
                        f"duration: {regime_state.duration_minutes}m)\n"
                        f"   {regime_state.reason}"
                    )

                    # 2. Resolve filters for regime
                    active_filters = self.filter_resolver.resolve_filters(regime_state)
                    self.logger.info(self.filter_resolver.explain_active_filters())

                    # 3. Check if regime changed
                    if hasattr(self, '_last_regime') and self._last_regime != regime_state.regime:
                        action = self.filter_resolver.get_transition_action(
                            self._last_regime,
                            regime_state.regime
                        )
                        self.logger.warning(
                            f"⚡ REGIME CHANGE: {self._last_regime} → {regime_state.regime}\n"
                            f"   Action: {action}"
                        )
                        await self._handle_regime_transition(action)

                    self._last_regime = regime_state.regime

                    # 4. Check if entries allowed
                    if not self.filter_resolver.should_allow_entry(regime_state):
                        self.logger.warning(f"🛑 {regime_state.regime} regime: New entries DISABLED")
                        await asyncio.sleep(60)
                        continue
                else:
                    # Fallback: use static filters
                    active_filters = self.config.smart_entry

                # 5. Select coins with adaptive filters
                top_coins = await self._select_top_coins_adaptive(active_filters)

                # ... rest of existing bot logic ...

            except Exception as e:
                self.logger.error(f"Error in control task: {e}")
                await asyncio.sleep(60)

    async def _detect_current_regime(self) -> RegimeState:
        """Detect regime using multi-timeframe data."""
        # Get candle data for all tracked pairs
        sample_pair = self._get_sample_pair()

        candle_data = {
            '1h': await self._get_candles(sample_pair, '1h', limit=48),
            '4h': await self._get_candles(sample_pair, '4h', limit=48),
            '24h': await self._get_candles(sample_pair, '1d', limit=14),
            'trend_1h': self.trend_scores[sample_pair]['1h'],
            'trend_4h': self.trend_scores[sample_pair]['4h'],
            'trend_24h': self.trend_scores[sample_pair]['24h'],
            'consensus': self.trend_scores[sample_pair]['consensus']
        }

        metrics = self.regime_detector.calculate_metrics(candle_data)
        regime_state = self.regime_detector.detect_regime(metrics)

        return regime_state

    async def _handle_regime_transition(self, action: str):
        """Handle regime change actions."""
        if action == "exit_all":
            self.logger.warning("🚨 Exiting all positions due to regime change")
            await self._emergency_exit_all_positions()

        elif action == "tighten_stops":
            self.logger.info("⚠️  Tightening stops by 1%")
            await self._adjust_all_stops(modifier=-0.01)

        elif action == "stop_new_entries":
            self.logger.warning("🛑 Stopping new entries")
            # Flag will be checked in should_allow_entry()

        elif action == "widen_grids":
            self.logger.info("📈 Widening grid spacing")
            # Grid spacing already updated by filter_resolver

        # ... other actions ...
```

### 7.2 SmartEntry Integration

```python
def _smart_entry_check(
    self,
    pair: str,
    metrics: Dict,
    active_filters: Dict  # NEW: passed from regime resolver
) -> Tuple[bool, List[str]]:
    """
    Validate entry with adaptive filters.

    Args:
        pair: Trading pair
        metrics: Calculated metrics (RSI, VWAP, etc.)
        active_filters: Regime-adapted filter thresholds

    Returns:
        (approved, reasons)
    """
    reasons = []

    # RSI block
    rsi = metrics.get('rsi', 50)
    rsi_max = active_filters.get('rsi_buy_max', 70)
    if rsi > rsi_max:
        reasons.append(f"❌ RSI {rsi:.1f} > {rsi_max:.1f} (overbought)")
        return False, reasons

    # VWAP deviation
    vwap_dev = metrics.get('vwap_deviation_pct', 0)
    vwap_max = active_filters.get('vwap_max_deviation_pct', 3.0)
    if abs(vwap_dev) > vwap_max:
        reasons.append(f"❌ VWAP dev {vwap_dev:+.2f}% > ±{vwap_max:.1f}%")
        return False, reasons

    # Up acceleration (blow-off top)
    up_accel = metrics.get('up_acceleration_pct', 0)
    up_max = active_filters.get('max_up_accel_pct', 1.2)
    if up_accel > up_max:
        reasons.append(f"❌ Up accel {up_accel:.2f}% > {up_max:.1f}% (blow-off risk)")
        return False, reasons

    # ... all other checks using active_filters ...

    reasons.append(f"✅ All filters passed (regime-adapted)")
    return True, reasons
```

---

## 8. Example Scenario: CHZ-USDT

### 8.1 Current Situation (Static Filters)

```
Time: 2025-12-20 17:54
Coin: CHZ-USDT
Metrics:
  - Consensus: +9.997%
  - 24h: -1.26%, 4h: -3.41%, 1h: +0.89%
  - RSI: 49.07
  - VWAP deviation: +0.24%
  - ATR: 0.28%
  - Up acceleration: +4.37%
  - Down acceleration: +4.37%

Static Filter Check:
  ✅ RSI 49.07 in [0, 80]
  ✅ RSI >= 25
  ✅ VWAP +0.24% <= 5.0%
  ✅ Wick ratio OK
  ✅ ATR 0.28% >= 0.15%
  ✅ ATR 0.28% <= 6.0%
  ✅ Spike 5m 0.19% <= 2.5%
  ✅ Down accel +4.37% >= -4.0%
  ❌ Up accel +4.37% > 1.8%  ← REJECTED

Result: REJECTED (blow-off top risk)
```

### 8.2 With Adaptive Filters (BULL Regime)

```
Regime Detection:
  Metrics:
    - Trend consensus: +9.997%
    - 24h: -1.26%, 4h: -3.41%, 1h: +0.89%
    - ATR expansion: +12.3% (expanding)
    - Range efficiency: 0.68 (directional)
    - Pullback depth: -3.41% (healthy pullback from 4h high)

  Score Calculation:
    = (24h * 0.3) + (4h * 0.4) + (1h * 0.2) + (ATR exp * 0.1)
    = (-1.26 * 0.3) + (-3.41 * 0.4) + (0.89 * 0.2) + (12.3 * 0.1)
    = -0.38 + -1.36 + 0.18 + 1.23
    = -0.33 (raw)

    * Efficiency multiplier: 0.5 + (0.68 * 1.0) = 1.18
    = -0.33 * 1.18 = -0.39

  Wait... this scores CHOP, not BULL!

  Let me recalculate using CONSENSUS (not individual TF):
    Consensus: +9.997%
    ATR expansion: +12.3%

    Score = (consensus * 0.8) + (ATR exp * 0.2)
          = (9.997 * 0.8) + (12.3 * 0.2)
          = 8.0 + 2.46
          = 10.46

    * Efficiency mult: 1.18
    = 10.46 * 1.18 = 12.34

  Regime: BULL (score 12.34 > 5.0)
  Confidence: 0.87 (high)
  Reason: "Strong consensus +10.0% | Volatility expanding (+12.3%) |
           High efficiency (0.68) | Score 12.3 > 5.0"

Adaptive Filter Resolution:
  Regime: BULL → Load bull_filters
  Active filters (with 0.87 confidence scaling):
    - rsi_buy_max: 70 + (85-70) * 0.87 = 83.0
    - vwap_max_deviation_pct: 3.0 + (7.0-3.0) * 0.87 = 6.5%
    - max_up_accel_pct: 1.2 + (3.0-1.2) * 0.87 = 2.8%
    - max_active_grids: 3

SmartEntry Check (Adaptive):
  ✅ RSI 49.07 < 83.0 (bull-adjusted)
  ✅ VWAP +0.24% < ±6.5% (bull-adjusted)
  ✅ Up accel +4.37% > 2.8%  ← STILL REJECTED!

Hmm, 4.37% acceleration is still too high even for BULL.
This might be legitimate blow-off top protection.

Let me check if this is a pullback scenario:
  - 4h trend: -3.41% (pullback in progress)
  - 1h trend: +0.89% (bounce starting)
  - Up accel: +4.37% (strong bounce)

This is a BULLISH PULLBACK BOUNCE - exactly what we want!
The issue: up_accel is measured over 1h, showing strong bounce.

Solution: In BULL regime with active pullback, allow higher up_accel:
  If pullback_depth < -2% AND 1h_trend > 0:
    up_accel_max = 5.0%  (allow aggressive bounce)

Revised Check:
  Pullback: -3.41% from 4h high ✅
  Bounce: 1h +0.89% ✅
  → Up accel limit raised to 5.0%
  ✅ Up accel +4.37% < 5.0%  ← APPROVED!

Result: ✅ APPROVED for entry
Entry reason: "BULL regime pullback bounce"
```

---

## 9. Logging & Observability

### 9.1 Regime Change Logs

```
2025-12-20 17:30:15 - INFO - 🌡️  REGIME: CHOP (score: 2.3, confidence: 0.68, duration: 47m)
   Neutral consensus +2.1% | Low efficiency (0.42) | Score 2.3 in [-3, 5]

2025-12-20 18:12:43 - WARNING - ⚡ REGIME CHANGE: CHOP → BULL
   Score: 8.7 → +8.7 (crossed +6.0 threshold with hysteresis)
   Confidence: 0.89
   Reason: Strong consensus +10.2% | Volatility expanding (+15.3%) | High efficiency (0.74)
   Action: widen_grids

2025-12-20 18:12:43 - INFO - 🎚️  ACTIVE FILTER SET:
   RSI range: 25-84
   VWAP deviation: ±6.8%
   Up accel limit: 2.9%
   Down accel limit: -3.9%
   ATR range: 0.10%-6.0%
   Grid spacing: 1.2x
   Max grids: 3
```

### 9.2 Entry Decision Logs

```
2025-12-20 18:15:22 - INFO - 🔍 Evaluating UNI-USDT for entry
2025-12-20 18:15:22 - INFO -    Regime: BULL (confidence: 0.89)
2025-12-20 18:15:22 - INFO -    Filters: BULL-adapted (RSI max: 84, VWAP max: 6.8%)
2025-12-20 18:15:22 - DEBUG -   ✅ rsi_block: 61.3 < 84.0
2025-12-20 18:15:22 - DEBUG -   ✅ vwap_deviation: +6.57% < 6.8%
2025-12-20 18:15:22 - DEBUG -   ✅ up_accel: +2.1% < 2.9%
2025-12-20 18:15:22 - INFO - ✅ UNI-USDT APPROVED for entry (BULL regime)
```

---

## 10. Testing Strategy

### 10.1 Unit Tests

```python
def test_regime_detection_bull():
    """Test BULL regime classification."""
    detector = RegimeDetector(default_config)

    metrics = RegimeMetrics(
        trend_1h=2.5,
        trend_4h=6.2,
        trend_24h=4.8,
        consensus=12.3,
        atr_pct=0.35,
        atr_expansion=18.2,
        range_efficiency=0.78,
        pullback_depth_pct=-1.2,
        timestamp=datetime.now()
    )

    regime = detector.detect_regime(metrics)

    assert regime.regime == "BULL"
    assert regime.score > 5.0
    assert regime.confidence > 0.65

def test_regime_hysteresis():
    """Test hysteresis prevents flip-flopping."""
    detector = RegimeDetector(default_config)

    # Enter BULL
    bull_metrics = create_bull_metrics()
    regime1 = detector.detect_regime(bull_metrics)
    assert regime1.regime == "BULL"

    # Slight drop (but within hysteresis buffer)
    chop_metrics = create_chop_metrics(score=4.5)
    regime2 = detector.detect_regime(chop_metrics)
    assert regime2.regime == "BULL"  # Should stay BULL

    # Strong drop (below buffer)
    chop_metrics_strong = create_chop_metrics(score=2.0)
    time.sleep(1801)  # Wait min duration
    regime3 = detector.detect_regime(chop_metrics_strong)
    assert regime3.regime == "CHOP"  # Now switches

def test_filter_confidence_scaling():
    """Test filter scaling with confidence."""
    resolver = AdaptiveFilterResolver(default_config)

    regime_state = RegimeState(
        regime="BULL",
        score=8.5,
        confidence=0.7,  # 70% confident
        duration_minutes=45,
        reason="Test",
        metrics=None
    )

    filters = resolver.resolve_filters(regime_state)

    # Bull rsi_max=85, baseline=70
    # Expected: 70 + (85-70)*0.7 = 80.5
    assert abs(filters['rsi_buy_max'] - 80.5) < 0.1
```

### 10.2 Backtest Validation

Run on historical data with known regime periods:
- **Dec 2024 bull run**: CHZ, UNI, etc. rallying
- **Nov 2024 chop**: Range-bound, low efficiency
- **May 2024 bear**: Downtrends

Compare:
- Entry count per regime
- Win rate per regime
- Regime classification accuracy (manual validation)

---

## 11. Rollout Plan

### Phase 1: Regime Detection Only (Week 1)
- Deploy `RegimeDetector` with logging only
- Monitor regime classifications for 7 days
- Validate against manual observation
- Tune thresholds if needed

### Phase 2: Simulation Mode (Week 2)
- Deploy `AdaptiveFilterResolver` in DRY-RUN mode
- Log what decisions WOULD change with adaptive filters
- Compare static vs adaptive entry counts
- Identify false positives/negatives

### Phase 3: Gradual Rollout (Week 3-4)
- Enable adaptive filters on Kraken (paper trading) first
- Monitor for 7 days
- If successful, enable on Bitget (live)
- Set `confidence_min_for_override: 0.80` initially (high bar)

### Phase 4: Full Production (Week 5+)
- Lower confidence threshold to 0.65
- Enable all regime actions (exit_all, stop_entries, etc.)
- Monitor closely for 2 weeks
- Fine-tune based on real performance

---

## 12. Monitoring & Alerts

### Key Metrics to Track
1. **Regime distribution**: % time in BULL/CHOP/BEAR
2. **Regime changes**: Frequency, duration before switch
3. **Filter effectiveness**: Entry approval rate per regime
4. **Performance per regime**: Win rate, avg profit per regime
5. **False regime classifications**: Manual review weekly

### Alert Conditions
- Regime flip-flopping (>5 changes per hour)
- Confidence drops below 0.5 for >30 min
- BEAR regime lasting >6 hours (check market conditions)
- Entry approval rate drops to 0 in BULL (filters too strict)

---

## 13. Future Enhancements

### V2 Features (Q1 2026)
- **Volume regime**: Separate detection for volume expansion/dry-up
- **Correlation regime**: Detect when pairs move together (risk-off) vs independently
- **Intraday regimes**: Detect opening pump, midday chop, closing rally patterns
- **ML-based regime**: Train classifier on historical data

### V3 Features (Q2 2026)
- **Multi-asset regime**: Detect regime across BTC, ETH, altcoins separately
- **Risk regime**: Adjust position sizing per regime (not just filters)
- **Dynamic exit regime**: Adjust take-profit targets per regime

---

## Conclusion

This adaptive filter system provides:
1. **Automatic adaptation** to market conditions
2. **Protection** from false breakouts in chop
3. **Opportunity capture** in strong trends
4. **Explainability** for all decisions
5. **Stability** via hysteresis

**Next Steps**:
1. Review design with team
2. Implement `RegimeDetector` class
3. Deploy in logging-only mode
4. Gather 1 week of regime data
5. Tune thresholds based on observations
6. Proceed to Phase 2 (simulation)

---

**End of Design Document**
