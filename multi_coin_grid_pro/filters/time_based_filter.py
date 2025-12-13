"""
Time-Based Trading Filter

Implements trading restrictions based on time of day, day of week, and market hours.
Helps avoid low-liquidity periods and adjust risk during weekends.

Features:
- Low liquidity hour blocking (e.g., 00:00-06:00 UTC)
- High liquidity hour bonuses (e.g., 13:00-19:00 UTC EU+US overlap)
- Weekend risk reduction
- Monitor-only mode (allows exits but blocks entries)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class TradingAction(Enum):
    """Allowed trading actions based on time conditions"""
    NORMAL = "normal"           # Full trading allowed
    MONITOR_ONLY = "monitor_only"  # Only exits, no new entries
    REDUCED_RISK = "reduced_risk"  # Lower position sizes
    NO_TRADING = "no_trading"   # Complete shutdown (future use)


@dataclass
class TimeBasedConfig:
    """Configuration for time-based trading rules"""
    enabled: bool = True

    # Low liquidity hours (UTC)
    avoid_low_liquidity_hours: bool = True
    low_liquidity_hours_utc: List[int] = None  # e.g., [0, 1, 2, 3, 4, 5]
    low_liquidity_action: str = "monitor_only"  # "monitor_only" or "reduced_risk"

    # High liquidity hours (UTC)
    prefer_high_liquidity_hours: bool = True
    high_liquidity_hours_utc: List[int] = None  # e.g., [13, 14, 15, 16, 17, 18]
    high_liquidity_bonus: float = 0.0  # Relaxation factor for filters (0.0-0.2)

    # Weekend adjustments
    weekend_mode: str = "reduced_risk"  # "normal", "reduced_risk", "monitor_only"
    weekend_risk_multiplier: float = 0.5  # Position size multiplier for weekends
    weekend_days: List[int] = None  # ISO weekday: 6=Saturday, 7=Sunday

    # Daily reset
    daily_stats_reset_hour_utc: int = 0  # Hour when daily stats reset

    # Holiday calendar
    respect_holidays: bool = False
    holiday_dates: List[str] = None  # ISO format dates ["2025-12-25", ...]
    holiday_risk_multiplier: float = 0.5  # Position size multiplier for holidays (default 50%)

    def __post_init__(self):
        """Set defaults for mutable lists"""
        if self.low_liquidity_hours_utc is None:
            self.low_liquidity_hours_utc = [0, 1, 2, 3, 4, 5]
        if self.high_liquidity_hours_utc is None:
            self.high_liquidity_hours_utc = [13, 14, 15, 16, 17, 18]
        if self.weekend_days is None:
            self.weekend_days = [6, 7]  # Saturday, Sunday
        if self.holiday_dates is None:
            self.holiday_dates = []


@dataclass
class TimeBasedDecision:
    """Result from time-based filter check"""
    allowed: bool  # Whether trading is allowed
    action: TradingAction  # Type of trading allowed
    risk_multiplier: float  # Position size multiplier (0.0-1.0+)
    filter_bonus: float  # Bonus relaxation for entry filters (0.0-0.2)
    reason: str  # Human-readable explanation
    current_hour_utc: int
    is_weekend: bool
    is_holiday: bool

    def can_enter_trades(self) -> bool:
        """Check if new trade entries are allowed"""
        return self.action == TradingAction.NORMAL or self.action == TradingAction.REDUCED_RISK

    def can_exit_trades(self) -> bool:
        """Check if trade exits are allowed (almost always true)"""
        return self.action != TradingAction.NO_TRADING


class TimeBasedFilter:
    """
    Filter that restricts trading based on time of day and day of week.

    Usage:
        config = TimeBasedConfig(
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5]
        )
        filter = TimeBasedFilter(config)
        decision = filter.check_time_conditions()

        if decision.can_enter_trades():
            # Proceed with entry logic
            position_size = base_size * decision.risk_multiplier
    """

    def __init__(self, config: TimeBasedConfig):
        self.config = config
        self._log_configuration()

    def _log_configuration(self):
        """Log current configuration on initialization"""
        if not self.config.enabled:
            logger.info("⏰ Time-Based Filter: DISABLED")
            return

        logger.info("⏰ Time-Based Filter: ENABLED")
        if self.config.avoid_low_liquidity_hours:
            logger.info(f"   Low liquidity hours: {self.config.low_liquidity_hours_utc} UTC → {self.config.low_liquidity_action}")
        if self.config.prefer_high_liquidity_hours:
            logger.info(f"   High liquidity hours: {self.config.high_liquidity_hours_utc} UTC (bonus: {self.config.high_liquidity_bonus:.1%})")
        if self.config.weekend_mode != "normal":
            logger.info(f"   Weekend mode: {self.config.weekend_mode} (risk multiplier: {self.config.weekend_risk_multiplier:.1%})")

    def check_time_conditions(self, current_time: Optional[datetime] = None) -> TimeBasedDecision:
        """
        Check current time conditions and return trading decision.

        Args:
            current_time: Optional datetime to check (defaults to now UTC)

        Returns:
            TimeBasedDecision with action, risk_multiplier, and reasoning
        """
        if not self.config.enabled:
            return TimeBasedDecision(
                allowed=True,
                action=TradingAction.NORMAL,
                risk_multiplier=1.0,
                filter_bonus=0.0,
                reason="Time-based filter disabled",
                current_hour_utc=0,
                is_weekend=False,
                is_holiday=False
            )

        # Get current time in UTC
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        elif current_time.tzinfo is None:
            # Assume naive datetime is UTC
            current_time = current_time.replace(tzinfo=timezone.utc)

        current_hour = current_time.hour
        current_weekday = current_time.isoweekday()  # 1=Monday, 7=Sunday
        current_date = current_time.date().isoformat()

        # Check holiday
        is_holiday = (
            self.config.respect_holidays and
            current_date in self.config.holiday_dates
        )

        # Check weekend
        is_weekend = current_weekday in self.config.weekend_days

        # Priority 1: Holiday check (if enabled)
        if is_holiday:
            action = TradingAction.REDUCED_RISK  # Holidays always reduce risk
            risk_mult = self.config.holiday_risk_multiplier  # Use dedicated holiday multiplier
            return TimeBasedDecision(
                allowed=(action != TradingAction.NO_TRADING),
                action=action,
                risk_multiplier=risk_mult,
                filter_bonus=0.0,
                reason=f"Holiday: {current_date}",
                current_hour_utc=current_hour,
                is_weekend=False,
                is_holiday=True
            )

        # Priority 2: Weekend check
        if is_weekend and self.config.weekend_mode != "normal":
            action = self._get_action_from_string(self.config.weekend_mode)
            risk_mult = self.config.weekend_risk_multiplier if action == TradingAction.REDUCED_RISK else 1.0

            # Weekend + low liquidity hours = even more restrictive
            if self.config.avoid_low_liquidity_hours and current_hour in self.config.low_liquidity_hours_utc:
                action = TradingAction.MONITOR_ONLY
                risk_mult = 0.0
                reason = f"Weekend + low liquidity hour ({current_hour:02d}:00 UTC)"
            else:
                reason = f"Weekend (day {current_weekday})"

            return TimeBasedDecision(
                allowed=(action != TradingAction.NO_TRADING),
                action=action,
                risk_multiplier=risk_mult,
                filter_bonus=0.0,
                reason=reason,
                current_hour_utc=current_hour,
                is_weekend=True,
                is_holiday=False
            )

        # Priority 3: Low liquidity hours (weekday)
        if self.config.avoid_low_liquidity_hours and current_hour in self.config.low_liquidity_hours_utc:
            action = self._get_action_from_string(self.config.low_liquidity_action)
            risk_mult = 0.0 if action == TradingAction.MONITOR_ONLY else 0.5

            return TimeBasedDecision(
                allowed=(action != TradingAction.NO_TRADING),
                action=action,
                risk_multiplier=risk_mult,
                filter_bonus=0.0,
                reason=f"Low liquidity hour: {current_hour:02d}:00 UTC",
                current_hour_utc=current_hour,
                is_weekend=False,
                is_holiday=False
            )

        # Priority 4: High liquidity hours (bonus conditions)
        if self.config.prefer_high_liquidity_hours and current_hour in self.config.high_liquidity_hours_utc:
            return TimeBasedDecision(
                allowed=True,
                action=TradingAction.NORMAL,
                risk_multiplier=1.0,
                filter_bonus=self.config.high_liquidity_bonus,
                reason=f"High liquidity hour: {current_hour:02d}:00 UTC (peak trading)",
                current_hour_utc=current_hour,
                is_weekend=False,
                is_holiday=False
            )

        # Default: Normal trading
        return TimeBasedDecision(
            allowed=True,
            action=TradingAction.NORMAL,
            risk_multiplier=1.0,
            filter_bonus=0.0,
            reason=f"Normal trading hour: {current_hour:02d}:00 UTC",
            current_hour_utc=current_hour,
            is_weekend=False,
            is_holiday=False
        )

    def _get_action_from_string(self, action_str: str) -> TradingAction:
        """Convert config string to TradingAction enum"""
        action_map = {
            "normal": TradingAction.NORMAL,
            "monitor_only": TradingAction.MONITOR_ONLY,
            "reduced_risk": TradingAction.REDUCED_RISK,
            "no_trading": TradingAction.NO_TRADING,
        }
        return action_map.get(action_str.lower(), TradingAction.NORMAL)

    def get_position_size_multiplier(self, current_time: Optional[datetime] = None) -> float:
        """
        Get position size multiplier based on current time.

        Returns:
            float: Multiplier for position sizing (0.0 to 1.0+)
                  - 1.0 = normal size
                  - 0.5 = half size (weekend/reduced risk)
                  - 0.0 = no new positions (monitor only)
        """
        decision = self.check_time_conditions(current_time)
        return decision.risk_multiplier

    def should_allow_entry(self, current_time: Optional[datetime] = None) -> bool:
        """Check if new trade entries should be allowed"""
        decision = self.check_time_conditions(current_time)
        return decision.can_enter_trades()

    def should_allow_exit(self, current_time: Optional[datetime] = None) -> bool:
        """Check if trade exits should be allowed (almost always True)"""
        decision = self.check_time_conditions(current_time)
        return decision.can_exit_trades()

    def get_filter_bonus(self, current_time: Optional[datetime] = None) -> float:
        """
        Get filter relaxation bonus during high liquidity hours.

        Returns:
            float: Bonus to add to filter thresholds (0.0 to 0.2)
                  - Can be used to relax RSI limits, VWAP thresholds, etc.
                  - Example: If RSI max is 65 and bonus is 0.1, allow up to 71.5 (65 * 1.1)
        """
        decision = self.check_time_conditions(current_time)
        return decision.filter_bonus
