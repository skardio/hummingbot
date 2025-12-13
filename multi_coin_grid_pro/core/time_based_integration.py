"""
Time-Based Trading Integration

Wraps TimeBasedFilter for easy integration into the main bot strategy.
Provides a clean interface for checking trading permissions and adjusting position sizes.

Usage in bot main loop:
    from multi_coin_grid_pro.core.time_based_integration import TimeBasedIntegration

    # Initialize
    config = parse_time_based_config(yaml_config)
    time_integration = TimeBasedIntegration(config)

    # Check if trading is allowed
    decision = time_integration.check_trading_permission()
    if decision.can_enter_trades():
        position_size = base_size * decision.risk_multiplier
        # Create order...
"""

import logging
from datetime import datetime
from typing import Optional

from multi_coin_grid_pro.filters.time_based_filter import (
    TimeBasedConfig,
    TimeBasedDecision,
    TimeBasedFilter,
    TradingAction,
)

logger = logging.getLogger(__name__)


class TimeBasedIntegration:
    """
    Integration wrapper for TimeBasedFilter.

    Provides a simplified interface for the main bot strategy to check
    time-based trading rules and adjust behavior accordingly.
    """

    def __init__(self, config: TimeBasedConfig):
        """
        Initialize time-based integration.

        Args:
            config: TimeBasedConfig with trading rules
        """
        self.config = config
        self.filter = TimeBasedFilter(config)
        self._last_decision: Optional[TimeBasedDecision] = None
        self._last_decision_time: Optional[datetime] = None

        logger.info("⏰ Time-Based Integration initialized")

    def check_trading_permission(self, current_time: Optional[datetime] = None) -> TimeBasedDecision:
        """
        Check if trading is allowed at current time.

        Args:
            current_time: Optional datetime to check (defaults to now UTC)

        Returns:
            TimeBasedDecision with full details of what's allowed
        """
        decision = self.filter.check_time_conditions(current_time)

        # Cache for performance
        self._last_decision = decision
        self._last_decision_time = current_time or datetime.utcnow()

        # Log significant changes
        if self._should_log_decision(decision):
            self._log_decision(decision)

        return decision

    def can_enter_new_trade(self, current_time: Optional[datetime] = None) -> bool:
        """
        Simple yes/no: Can we enter a new trade right now?

        Returns:
            bool: True if new entries are allowed, False otherwise
        """
        decision = self.check_trading_permission(current_time)
        return decision.can_enter_trades()

    def can_exit_trade(self, current_time: Optional[datetime] = None) -> bool:
        """
        Simple yes/no: Can we exit a trade right now?

        Returns:
            bool: True if exits are allowed (almost always True)
        """
        decision = self.check_trading_permission(current_time)
        return decision.can_exit_trades()

    def get_position_size_adjustment(self, base_size: float, current_time: Optional[datetime] = None) -> float:
        """
        Calculate adjusted position size based on time rules.

        Args:
            base_size: Base position size (in EUR)
            current_time: Optional datetime to check

        Returns:
            float: Adjusted position size
                  - Normal hours: base_size * 1.0
                  - Weekend: base_size * 0.5 (or as configured)
                  - Monitor only: 0.0 (no new positions)
        """
        decision = self.check_trading_permission(current_time)
        adjusted_size = base_size * decision.risk_multiplier

        if adjusted_size < base_size:
            logger.info(f"💰 Position size adjusted: €{base_size:.2f} → €{adjusted_size:.2f} ({decision.reason})")

        return adjusted_size

    def get_filter_relaxation(self, current_time: Optional[datetime] = None) -> float:
        """
        Get filter relaxation bonus for high liquidity hours.

        Can be used to relax entry filter thresholds during peak trading hours.

        Returns:
            float: Bonus factor (0.0 to 0.2)
                  - 0.0 = no bonus
                  - 0.1 = 10% relaxation (RSI 65 → 71.5)
                  - 0.2 = 20% relaxation (max recommended)
        """
        decision = self.check_trading_permission(current_time)
        return decision.filter_bonus

    def get_current_status(self, current_time: Optional[datetime] = None) -> dict:
        """
        Get detailed status for monitoring/logging.

        Returns:
            dict: Status information including:
                - allowed: bool
                - action: str
                - reason: str
                - risk_multiplier: float
                - filter_bonus: float
                - is_weekend: bool
                - is_holiday: bool
                - current_hour_utc: int
        """
        decision = self.check_trading_permission(current_time)

        return {
            "allowed": decision.allowed,
            "action": decision.action.value,
            "reason": decision.reason,
            "risk_multiplier": decision.risk_multiplier,
            "filter_bonus": decision.filter_bonus,
            "can_enter": decision.can_enter_trades(),
            "can_exit": decision.can_exit_trades(),
            "is_weekend": decision.is_weekend,
            "is_holiday": decision.is_holiday,
            "current_hour_utc": decision.current_hour_utc,
        }

    def _should_log_decision(self, decision: TimeBasedDecision) -> bool:
        """Check if we should log this decision (avoid spam)"""
        # Always log first decision
        if self._last_decision is None:
            return True

        # Log if action changed
        if self._last_decision.action != decision.action:
            return True

        # Log if weekend status changed
        if self._last_decision.is_weekend != decision.is_weekend:
            return True

        # Log if hour changed (once per hour)
        if self._last_decision.current_hour_utc != decision.current_hour_utc:
            return True

        return False

    def _log_decision(self, decision: TimeBasedDecision):
        """Log trading decision"""
        emoji = "✅" if decision.can_enter_trades() else "⏸️"
        logger.info(f"{emoji} Time-based decision: {decision.reason}")

        if decision.risk_multiplier < 1.0:
            logger.info(f"   Risk multiplier: {decision.risk_multiplier:.1%}")

        if decision.filter_bonus > 0.0:
            logger.info(f"   Filter bonus: +{decision.filter_bonus:.1%}")

        if decision.action == TradingAction.MONITOR_ONLY:
            logger.warning("⚠️  MONITOR ONLY MODE - No new entries, exits still allowed")

        if decision.is_weekend:
            logger.info("📅 Weekend mode active")

        if decision.is_holiday:
            logger.info("🎉 Holiday mode active")


def create_time_based_integration_from_config(yaml_config: dict) -> TimeBasedIntegration:
    """
    Factory function to create TimeBasedIntegration from YAML config.

    Args:
        yaml_config: Full YAML configuration dictionary

    Returns:
        TimeBasedIntegration instance
    """
    from multi_coin_grid_pro.core.config_loader import parse_time_based_config

    time_config = parse_time_based_config(yaml_config)
    return TimeBasedIntegration(time_config)
