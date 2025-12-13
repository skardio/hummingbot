"""
Unit tests for Time-Based Trading Filter

Tests all time-based trading scenarios:
- Low liquidity hours (00:00-06:00 UTC)
- High liquidity hours (13:00-19:00 UTC)
- Weekend risk reduction
- Monitor-only mode
- Holiday handling
- Position size adjustments
"""

from datetime import datetime, timezone

import pytest

from multi_coin_grid_pro.filters.time_based_filter import (
    TimeBasedConfig,
    TimeBasedDecision,
    TimeBasedFilter,
    TradingAction,
)


class TestTimeBasedFilterBasics:
    """Test basic initialization and disabled state"""

    def test_filter_disabled(self):
        """When disabled, all trading should be allowed"""
        config = TimeBasedConfig(enabled=False)
        filter = TimeBasedFilter(config)

        # Test at various times - all should be normal
        midnight = datetime(2025, 12, 11, 0, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(midnight)

        assert decision.allowed is True
        assert decision.action == TradingAction.NORMAL
        assert decision.risk_multiplier == 1.0
        assert decision.filter_bonus == 0.0
        assert "disabled" in decision.reason.lower()

    def test_normal_trading_hour(self):
        """Normal hours (not low/high) should allow standard trading"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            high_liquidity_hours_utc=[13, 14, 15, 16, 17, 18],
        )
        filter = TimeBasedFilter(config)

        # Test 10:00 UTC (neither low nor high)
        normal_hour = datetime(2025, 12, 11, 10, 0, tzinfo=timezone.utc)  # Thursday
        decision = filter.check_time_conditions(normal_hour)

        assert decision.allowed is True
        assert decision.action == TradingAction.NORMAL
        assert decision.risk_multiplier == 1.0
        assert decision.filter_bonus == 0.0
        assert decision.can_enter_trades() is True
        assert decision.can_exit_trades() is True


class TestLowLiquidityHours:
    """Test low liquidity hour restrictions"""

    def test_low_liquidity_monitor_only(self):
        """Low liquidity hours with monitor_only action"""
        config = TimeBasedConfig(
            enabled=True,
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        # Test 02:00 UTC (low liquidity)
        low_hour = datetime(2025, 12, 11, 2, 0, tzinfo=timezone.utc)  # Thursday
        decision = filter.check_time_conditions(low_hour)

        assert decision.allowed is True  # Trading is allowed (not blocked)
        assert decision.action == TradingAction.MONITOR_ONLY
        assert decision.risk_multiplier == 0.0  # No new positions
        assert decision.can_enter_trades() is False
        assert decision.can_exit_trades() is True  # Exits still allowed
        assert "low liquidity" in decision.reason.lower()

    def test_low_liquidity_reduced_risk(self):
        """Low liquidity hours with reduced_risk action"""
        config = TimeBasedConfig(
            enabled=True,
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            low_liquidity_action="reduced_risk",
        )
        filter = TimeBasedFilter(config)

        low_hour = datetime(2025, 12, 11, 3, 30, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(low_hour)

        assert decision.action == TradingAction.REDUCED_RISK
        assert decision.risk_multiplier == 0.5
        assert decision.can_enter_trades() is True  # Still can enter
        assert decision.can_exit_trades() is True

    def test_low_liquidity_all_hours(self):
        """Test all configured low liquidity hours"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        for hour in [0, 1, 2, 3, 4, 5]:
            test_time = datetime(2025, 12, 11, hour, 0, tzinfo=timezone.utc)
            decision = filter.check_time_conditions(test_time)
            assert decision.action == TradingAction.MONITOR_ONLY
            assert decision.can_enter_trades() is False

    def test_low_liquidity_disabled(self):
        """When avoid_low_liquidity_hours=False, should trade normally"""
        config = TimeBasedConfig(
            enabled=True,
            avoid_low_liquidity_hours=False,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
        )
        filter = TimeBasedFilter(config)

        midnight = datetime(2025, 12, 11, 0, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(midnight)

        assert decision.action == TradingAction.NORMAL
        assert decision.can_enter_trades() is True


class TestHighLiquidityHours:
    """Test high liquidity hour bonuses"""

    def test_high_liquidity_bonus(self):
        """High liquidity hours should provide filter bonus"""
        config = TimeBasedConfig(
            enabled=True,
            prefer_high_liquidity_hours=True,
            high_liquidity_hours_utc=[13, 14, 15, 16, 17, 18],
            high_liquidity_bonus=0.1,  # 10% relaxation
        )
        filter = TimeBasedFilter(config)

        # Test 15:00 UTC (EU+US overlap)
        high_hour = datetime(2025, 12, 11, 15, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(high_hour)

        assert decision.action == TradingAction.NORMAL
        assert decision.filter_bonus == 0.1
        assert decision.risk_multiplier == 1.0
        assert "high liquidity" in decision.reason.lower()

    def test_high_liquidity_all_hours(self):
        """Test all configured high liquidity hours"""
        config = TimeBasedConfig(
            enabled=True,
            high_liquidity_hours_utc=[13, 14, 15, 16, 17, 18],
            high_liquidity_bonus=0.15,
        )
        filter = TimeBasedFilter(config)

        for hour in [13, 14, 15, 16, 17, 18]:
            test_time = datetime(2025, 12, 11, hour, 0, tzinfo=timezone.utc)
            decision = filter.check_time_conditions(test_time)
            assert decision.filter_bonus == 0.15
            assert "peak trading" in decision.reason.lower()

    def test_high_liquidity_disabled(self):
        """When prefer_high_liquidity_hours=False, no bonus"""
        config = TimeBasedConfig(
            enabled=True,
            prefer_high_liquidity_hours=False,
            high_liquidity_hours_utc=[13, 14, 15, 16, 17, 18],
            high_liquidity_bonus=0.1,
        )
        filter = TimeBasedFilter(config)

        high_hour = datetime(2025, 12, 11, 15, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(high_hour)

        assert decision.filter_bonus == 0.0  # No bonus when disabled


class TestWeekendMode:
    """Test weekend risk adjustments"""

    def test_weekend_reduced_risk(self):
        """Weekend should reduce position sizes"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="reduced_risk",
            weekend_risk_multiplier=0.5,
            weekend_days=[6, 7],  # Saturday, Sunday
        )
        filter = TimeBasedFilter(config)

        # Saturday, December 13, 2025
        saturday = datetime(2025, 12, 13, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(saturday)

        assert decision.is_weekend is True
        assert decision.action == TradingAction.REDUCED_RISK
        assert decision.risk_multiplier == 0.5
        assert decision.can_enter_trades() is True
        assert "weekend" in decision.reason.lower()

    def test_weekend_monitor_only(self):
        """Weekend can be set to monitor_only"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="monitor_only",
            weekend_days=[6, 7],
        )
        filter = TimeBasedFilter(config)

        sunday = datetime(2025, 12, 14, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(sunday)

        assert decision.is_weekend is True
        assert decision.action == TradingAction.MONITOR_ONLY
        assert decision.can_enter_trades() is False
        assert decision.can_exit_trades() is True

    def test_weekend_normal_mode(self):
        """Weekend can be set to normal (no restrictions)"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="normal",
        )
        filter = TimeBasedFilter(config)

        saturday = datetime(2025, 12, 13, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(saturday)

        assert decision.action == TradingAction.NORMAL
        assert decision.risk_multiplier == 1.0

    def test_weekend_plus_low_liquidity(self):
        """Weekend + low liquidity hours = most restrictive"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="reduced_risk",
            weekend_risk_multiplier=0.5,
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        # Saturday at 02:00 UTC (weekend + low liquidity)
        saturday_night = datetime(2025, 12, 13, 2, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(saturday_night)

        assert decision.is_weekend is True
        assert decision.action == TradingAction.MONITOR_ONLY  # Most restrictive
        assert decision.risk_multiplier == 0.0
        assert decision.can_enter_trades() is False
        assert "weekend" in decision.reason.lower() and "low liquidity" in decision.reason.lower()

    def test_weekday_not_weekend(self):
        """Weekdays should not be treated as weekend"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="monitor_only",
            weekend_days=[6, 7],
        )
        filter = TimeBasedFilter(config)

        # Thursday, December 11, 2025
        thursday = datetime(2025, 12, 11, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(thursday)

        assert decision.is_weekend is False
        assert decision.action == TradingAction.NORMAL


class TestHolidayHandling:
    """Test holiday calendar support"""

    def test_holiday_reduced_risk(self):
        """Holidays should apply weekend mode settings"""
        config = TimeBasedConfig(
            enabled=True,
            respect_holidays=True,
            holiday_dates=["2025-12-25", "2026-01-01"],
            weekend_mode="reduced_risk",
            weekend_risk_multiplier=0.5,
        )
        filter = TimeBasedFilter(config)

        # Christmas Day 2025
        christmas = datetime(2025, 12, 25, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(christmas)

        assert decision.is_holiday is True
        assert decision.action == TradingAction.REDUCED_RISK
        assert decision.risk_multiplier == 0.5
        assert "holiday" in decision.reason.lower()

    def test_holiday_disabled(self):
        """When respect_holidays=False, holidays are normal days"""
        config = TimeBasedConfig(
            enabled=True,
            respect_holidays=False,
            holiday_dates=["2025-12-25"],
        )
        filter = TimeBasedFilter(config)

        christmas = datetime(2025, 12, 25, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(christmas)

        assert decision.is_holiday is False
        assert decision.action == TradingAction.NORMAL

    def test_non_holiday_date(self):
        """Non-holiday dates should trade normally"""
        config = TimeBasedConfig(
            enabled=True,
            respect_holidays=True,
            holiday_dates=["2025-12-25"],
        )
        filter = TimeBasedFilter(config)

        normal_day = datetime(2025, 12, 11, 12, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(normal_day)

        assert decision.is_holiday is False


class TestHelperMethods:
    """Test convenience methods"""

    def test_should_allow_entry(self):
        """Test simple entry permission check"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[0, 1, 2],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        # Low liquidity: no entries
        low_hour = datetime(2025, 12, 11, 1, 0, tzinfo=timezone.utc)
        assert filter.should_allow_entry(low_hour) is False

        # Normal hour: entries allowed
        normal_hour = datetime(2025, 12, 11, 10, 0, tzinfo=timezone.utc)
        assert filter.should_allow_entry(normal_hour) is True

    def test_should_allow_exit(self):
        """Test exit permission (almost always True)"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[0, 1, 2],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        # Even in monitor_only mode, exits are allowed
        low_hour = datetime(2025, 12, 11, 1, 0, tzinfo=timezone.utc)
        assert filter.should_allow_exit(low_hour) is True

    def test_get_position_size_multiplier(self):
        """Test position size multiplier calculation"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="reduced_risk",
            weekend_risk_multiplier=0.5,
        )
        filter = TimeBasedFilter(config)

        # Weekend: 0.5x
        saturday = datetime(2025, 12, 13, 12, 0, tzinfo=timezone.utc)
        assert filter.get_position_size_multiplier(saturday) == 0.5

        # Weekday: 1.0x
        thursday = datetime(2025, 12, 11, 12, 0, tzinfo=timezone.utc)
        assert filter.get_position_size_multiplier(thursday) == 1.0

    def test_get_filter_bonus(self):
        """Test filter bonus retrieval"""
        config = TimeBasedConfig(
            enabled=True,
            high_liquidity_hours_utc=[15],
            high_liquidity_bonus=0.15,
        )
        filter = TimeBasedFilter(config)

        # High liquidity: bonus
        high_hour = datetime(2025, 12, 11, 15, 0, tzinfo=timezone.utc)
        assert filter.get_filter_bonus(high_hour) == 0.15

        # Normal hour: no bonus
        normal_hour = datetime(2025, 12, 11, 10, 0, tzinfo=timezone.utc)
        assert filter.get_filter_bonus(normal_hour) == 0.0


class TestTimezoneHandling:
    """Test timezone conversion and UTC handling"""

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime (no timezone) should be treated as UTC"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[2],
            low_liquidity_action="monitor_only",
        )
        filter = TimeBasedFilter(config)

        # Naive datetime
        naive_time = datetime(2025, 12, 11, 2, 0)  # No tzinfo
        decision = filter.check_time_conditions(naive_time)

        assert decision.current_hour_utc == 2
        assert decision.action == TradingAction.MONITOR_ONLY

    def test_explicit_utc_timezone(self):
        """Explicit UTC timezone should work correctly"""
        config = TimeBasedConfig(
            enabled=True,
            low_liquidity_hours_utc=[3],
        )
        filter = TimeBasedFilter(config)

        utc_time = datetime(2025, 12, 11, 3, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(utc_time)

        assert decision.current_hour_utc == 3


class TestRealWorldScenarios:
    """Test realistic trading scenarios"""

    def test_typical_weekday_trading_day(self):
        """Simulate full 24-hour weekday"""
        config = TimeBasedConfig(
            enabled=True,
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
            low_liquidity_action="monitor_only",
            prefer_high_liquidity_hours=True,
            high_liquidity_hours_utc=[13, 14, 15, 16, 17, 18],
            high_liquidity_bonus=0.1,
        )
        filter = TimeBasedFilter(config)

        thursday = datetime(2025, 12, 11, 0, 0, tzinfo=timezone.utc)

        # 00:00-05:00: Monitor only
        for hour in range(0, 6):
            test_time = thursday.replace(hour=hour)
            decision = filter.check_time_conditions(test_time)
            assert decision.can_enter_trades() is False

        # 06:00-12:00: Normal trading
        for hour in range(6, 13):
            test_time = thursday.replace(hour=hour)
            decision = filter.check_time_conditions(test_time)
            assert decision.can_enter_trades() is True
            assert decision.filter_bonus == 0.0

        # 13:00-18:00: High liquidity bonus
        for hour in range(13, 19):
            test_time = thursday.replace(hour=hour)
            decision = filter.check_time_conditions(test_time)
            assert decision.can_enter_trades() is True
            assert decision.filter_bonus == 0.1

        # 19:00-23:00: Normal trading
        for hour in range(19, 24):
            test_time = thursday.replace(hour=hour)
            decision = filter.check_time_conditions(test_time)
            assert decision.can_enter_trades() is True
            assert decision.filter_bonus == 0.0

    def test_typical_weekend(self):
        """Simulate weekend trading"""
        config = TimeBasedConfig(
            enabled=True,
            weekend_mode="reduced_risk",
            weekend_risk_multiplier=0.5,
            avoid_low_liquidity_hours=True,
            low_liquidity_hours_utc=[0, 1, 2, 3, 4, 5],
        )
        filter = TimeBasedFilter(config)

        # Saturday 10:00 UTC: reduced risk
        saturday_day = datetime(2025, 12, 13, 10, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(saturday_day)
        assert decision.risk_multiplier == 0.5
        assert decision.can_enter_trades() is True

        # Saturday 02:00 UTC: monitor only (weekend + low liquidity)
        saturday_night = datetime(2025, 12, 13, 2, 0, tzinfo=timezone.utc)
        decision = filter.check_time_conditions(saturday_night)
        assert decision.can_enter_trades() is False
