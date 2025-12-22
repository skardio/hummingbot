"""
Adaptive filter resolution based on detected market regime.
Adjusts SmartEntry filters for BULL, CHOP, or BEAR markets.
"""
from typing import Dict

from .regime_detector import RegimeState


class AdaptiveFilterResolver:
    """
    Resolves filter parameters based on detected regime.
    Handles smooth transitions and confidence scaling.
    """

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.baseline_filters = config.get('baseline', {})
        self.regime_filters = {
            'BULL': config.get('BULL', {}),
            'CHOP': config.get('CHOP', {}),
            'BEAR': config.get('BEAR', {})
        }
        self.active_filters = self.baseline_filters.copy()
        self.last_regime = "CHOP"

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
            return self.regime_filters.get('BEAR', {}).get('bear_allow_meanrev', False)

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
