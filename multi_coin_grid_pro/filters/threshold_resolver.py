"""
Threshold Resolver - Regime-aware threshold resolution with safety floors

Part of EPIC v3.4: Momentum Health Guards
Story 5: Clean precedence system (coin_profile > regime > baseline)

Precedence Order:
1. Coin profile override (highest priority)
2. Regime-specific threshold (BULL/CHOP/BEAR)
3. Baseline default (fallback)

Safety Floors (cannot be overridden):
- slope_min_pct_15m: >= 0.01%
- accel_5m_min_pct: >= 1.0%
- accel_15m_min_pct: >= 3.0%
- vwap_dev_min_pct: >= 8.0%
- cooldown_sec: >= 300 (5 minutes)
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Hard safety floors - cannot be violated even by coin profiles
SAFETY_FLOORS = {
    "vwap_slope_min_pct_15m": 0.01,      # Cannot disable slope guard
    "parabolic_accel_5m_min_pct": 1.0,    # Too low = false positives
    "parabolic_accel_15m_min_pct": 3.0,   # Too low = false positives
    "parabolic_vwap_dev_min_pct": 8.0,    # Must be meaningful deviation
    "parabolic_cooldown_sec": 300,         # 5 minutes minimum
}


class ThresholdResolver:
    """
    Resolves thresholds with precedence: coin_profile > regime > baseline.

    Enforces safety floors to prevent accidental disabling of guards.
    """

    def __init__(
        self,
        config: Any,
        coin_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
        validate_on_init: bool = True
    ):
        """
        Initialize resolver.

        Args:
            config: SmartEntryConfig or config dict with baseline thresholds
            coin_profiles: Optional dict of {symbol: {key: value}}
            validate_on_init: Validate coin profiles on initialization
        """
        self.config = config
        self.coin_profiles = coin_profiles or {}

        if validate_on_init:
            self._validate_coin_profiles()

    def resolve(
        self,
        symbol: str,
        key: str,
        regime: str = "NEUTRAL",
        default: Optional[float] = None
    ) -> float:
        """
        Resolve threshold with precedence order.

        Args:
            symbol: Trading pair (e.g., "PEPE-EUR")
            key: Config key (e.g., "parabolic_accel_5m_min_pct")
            regime: Market regime (BULL/CHOP/BEAR/NEUTRAL)
            default: Fallback if all lookups fail

        Returns:
            Resolved threshold value (with safety floor applied)
        """
        value = None
        source = None

        # 1. Check coin profile (highest priority)
        if symbol in self.coin_profiles:
            profile = self.coin_profiles[symbol]
            if key in profile:
                value = profile[key]
                source = f"coin_profile[{symbol}]"

        # 2. Check regime-specific (if no coin profile)
        if value is None and regime != "NEUTRAL":
            regime_key = f"{key}__{regime}"  # e.g., "parabolic_accel_5m_min_pct__BULL"
            value = self._get_config_value(regime_key)
            if value is not None:
                source = f"regime[{regime}]"

        # 3. Fallback to baseline
        if value is None:
            value = self._get_config_value(key)
            if value is not None:
                source = "baseline"

        # 4. Use default if all else fails
        if value is None:
            value = default
            source = "default_fallback"

        # Apply safety floor
        if key in SAFETY_FLOORS:
            floor = SAFETY_FLOORS[key]
            if value is not None and value < floor:
                logger.warning(
                    f"[THRESHOLD] {symbol} {key}={value} below safety floor {floor} "
                    f"(source={source}), enforcing floor"
                )
                value = floor

        return value

    def resolve_dict(
        self,
        symbol: str,
        keys: list,
        regime: str = "NEUTRAL"
    ) -> Dict[str, float]:
        """
        Resolve multiple thresholds at once.

        Args:
            symbol: Trading pair
            keys: List of config keys to resolve
            regime: Market regime

        Returns:
            Dict of {key: resolved_value}
        """
        return {key: self.resolve(symbol, key, regime) for key in keys}

    def _get_config_value(self, key: str) -> Optional[float]:
        """
        Get value from config object.

        Supports both dict and object attribute access.
        """
        if isinstance(self.config, dict):
            return self.config.get(key)
        else:
            return getattr(self.config, key, None)

    def _validate_coin_profiles(self) -> None:
        """
        Validate coin profiles against safety floors.

        Logs warnings for violations but does not raise errors
        (violations are enforced at resolution time).
        """
        for symbol, profile in self.coin_profiles.items():
            for key, value in profile.items():
                if key in SAFETY_FLOORS:
                    floor = SAFETY_FLOORS[key]
                    if value < floor:
                        logger.warning(
                            f"[CONFIG] Coin profile {symbol}.{key}={value} "
                            f"below safety floor {floor}, will be enforced at runtime"
                        )

    def get_safety_floor(self, key: str) -> Optional[float]:
        """Get safety floor for a given key."""
        return SAFETY_FLOORS.get(key)

    def is_at_safety_floor(self, key: str, value: float) -> bool:
        """Check if a value is at its safety floor."""
        floor = SAFETY_FLOORS.get(key)
        if floor is None:
            return False
        return abs(value - floor) < 1e-6  # Float comparison tolerance


def create_regime_config_dict(
    baseline: Dict[str, float],
    bull: Optional[Dict[str, float]] = None,
    chop: Optional[Dict[str, float]] = None,
    bear: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """
    Helper to create regime-aware config dict.

    Example:
        config = create_regime_config_dict(
            baseline={"parabolic_accel_5m_min_pct": 2.5},
            bull={"parabolic_accel_5m_min_pct": 3.0},
            chop={"parabolic_accel_5m_min_pct": 2.2}
        )

    Returns flat dict with regime suffixes:
        {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_5m_min_pct__BULL": 3.0,
            "parabolic_accel_5m_min_pct__CHOP": 2.2
        }
    """
    result = baseline.copy()

    if bull:
        for key, value in bull.items():
            result[f"{key}__BULL"] = value

    if chop:
        for key, value in chop.items():
            result[f"{key}__CHOP"] = value

    if bear:
        for key, value in bear.items():
            result[f"{key}__BEAR"] = value

    return result
