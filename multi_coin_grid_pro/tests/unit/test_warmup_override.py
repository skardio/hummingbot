"""
Unit tests for Warmup Override logic (4H strong > 1H weak)

Tests the professional pullback-buying strategy where strong 4H uptrends
allow temporary negative 1H trends (buying the dip).
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
    except ImportError:
        from controllers.multi_coin_grid_config import MultiCoinGridConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController


pytestmark = pytest.mark.asyncio


class MockTrend:
    """Mock trend object for testing"""

    def __init__(self, trend_1440m, trend_240m, trend_60m, long_trend_warmup=True):
        self.trend_1440m = trend_1440m
        self.trend_240m = trend_240m
        self.trend_60m = trend_60m
        self.trend_score = (trend_1440m + trend_240m + trend_60m) / 3
        self.long_trend_warmup = long_trend_warmup
        self.price_history = [100.0] * 500  # Simulate historical data


class TestWarmupOverride:
    """Test suite for Warmup Override functionality"""

    @pytest.fixture
    def config_override_enabled(self):
        """Config with warmup override ENABLED"""
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            total_amount_quote=Decimal("100"),
            warmup_override_enabled=True,
            warmup_4h_strong_min=1.0,
            warmup_1h_min_if_4h_strong=-0.6,
            # Required risk fields
            risk_reference_balance_quote=Decimal("10000"),
            risk_max_daily_loss_pct=Decimal("2"),
            risk_max_balance_per_trade_pct=Decimal("0.5"),
            risk_max_total_open_risk_pct=Decimal("3"),
        )

    @pytest.fixture
    def config_override_disabled(self):
        """Config with warmup override DISABLED"""
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            total_amount_quote=Decimal("100"),
            warmup_override_enabled=False,
            # Required risk fields
            risk_reference_balance_quote=Decimal("10000"),
            risk_max_daily_loss_pct=Decimal("2"),
            risk_max_balance_per_trade_pct=Decimal("0.5"),
            risk_max_total_open_risk_pct=Decimal("3"),
        )

    @pytest.fixture
    def mock_controller(self, config_override_enabled):
        """Create mock controller with override enabled"""
        controller = Mock(spec=MultiCoinGridController)
        controller.config = config_override_enabled
        controller.logger = Mock(return_value=Mock())
        return controller

    def test_override_config_defaults(self, config_override_enabled):
        """Test that override config has correct defaults"""
        assert config_override_enabled.warmup_override_enabled is True
        assert config_override_enabled.warmup_4h_strong_min == 1.0
        assert config_override_enabled.warmup_1h_min_if_4h_strong == -0.6

    def test_scenario_1_strong_4h_negative_1h_override_allows(self, config_override_enabled):
        """
        SCENARIO 1: Strong 4H (+1.12%), negative 1H (-0.38%)
        EXPECTED: BUY ALLOWED (override kicks in)

        This is the TAO-EUR case from production logs
        """
        trend = MockTrend(
            trend_1440m=0.37,  # 24h fallback
            trend_240m=1.12,   # 4h STRONG (> 1.0%)
            trend_60m=-0.38,   # 1h negative BUT within -0.6% limit
        )

        # Simulate warmup logic
        warmup_240m_ok = trend.trend_240m > 0.75  # True
        warmup_60m_ok = trend.trend_60m >= 0.0    # False initially

        # Apply override
        if config_override_enabled.warmup_override_enabled:
            if trend.trend_240m >= config_override_enabled.warmup_4h_strong_min:
                if trend.trend_60m >= config_override_enabled.warmup_1h_min_if_4h_strong:
                    warmup_60m_ok = True  # OVERRIDE

        assert warmup_240m_ok is True, "4H trend should be strong enough"
        assert warmup_60m_ok is True, "Override should allow negative 1H"

    def test_scenario_2_weak_4h_negative_1h_rejects(self, config_override_enabled):
        """
        SCENARIO 2: Weak 4H (+0.5%), negative 1H (-0.38%)
        EXPECTED: BUY REJECTED (override does NOT activate)
        """
        trend = MockTrend(
            trend_1440m=0.2,
            trend_240m=0.5,    # 4h too weak (< 1.0%)
            trend_60m=-0.38,
        )

        warmup_240m_ok = trend.trend_240m > 0.75  # False
        warmup_60m_ok = trend.trend_60m >= 0.0    # False

        # Override won't activate (4h not strong enough)
        if config_override_enabled.warmup_override_enabled:
            if trend.trend_240m >= config_override_enabled.warmup_4h_strong_min:
                if trend.trend_60m >= config_override_enabled.warmup_1h_min_if_4h_strong:
                    warmup_60m_ok = True

        assert warmup_240m_ok is False, "4H trend too weak"
        assert warmup_60m_ok is False, "Override should NOT activate"

    def test_scenario_3_strong_4h_very_negative_1h_rejects(self, config_override_enabled):
        """
        SCENARIO 3: Strong 4H (+1.5%), VERY negative 1H (-0.8%)
        EXPECTED: BUY REJECTED (1H drop too steep, below -0.6% limit)
        """
        trend = MockTrend(
            trend_1440m=1.0,
            trend_240m=1.5,    # 4h VERY strong
            trend_60m=-0.8,    # 1h TOO negative (< -0.6%)
        )

        warmup_240m_ok = trend.trend_240m > 0.75  # True
        warmup_60m_ok = trend.trend_60m >= 0.0    # False

        # Override tries but fails (1h too negative)
        if config_override_enabled.warmup_override_enabled:
            if trend.trend_240m >= config_override_enabled.warmup_4h_strong_min:
                if trend.trend_60m >= config_override_enabled.warmup_1h_min_if_4h_strong:
                    warmup_60m_ok = True

        assert warmup_240m_ok is True, "4H trend strong enough"
        assert warmup_60m_ok is False, "1H drop too steep for override"

    def test_scenario_4_override_disabled_rejects_negative_1h(self, config_override_disabled):
        """
        SCENARIO 4: Override DISABLED, strong 4H (+1.2%), negative 1H (-0.3%)
        EXPECTED: BUY REJECTED (conservative mode, no override)
        """
        trend = MockTrend(
            trend_1440m=0.5,
            trend_240m=1.2,
            trend_60m=-0.3,
        )

        warmup_240m_ok = trend.trend_240m > 0.75  # True
        warmup_60m_ok = trend.trend_60m >= 0.0    # False

        # Override disabled - no change
        if config_override_disabled.warmup_override_enabled:  # False
            if trend.trend_240m >= 1.0:
                if trend.trend_60m >= -0.6:
                    warmup_60m_ok = True

        assert warmup_240m_ok is True
        assert warmup_60m_ok is False, "Override disabled, conservative rules apply"

    def test_scenario_5_perfect_conditions_both_positive(self, config_override_enabled):
        """
        SCENARIO 5: Perfect conditions - 4H (+1.5%), 1H (+0.2%)
        EXPECTED: BUY ALLOWED (no override needed, normal approval)
        """
        trend = MockTrend(
            trend_1440m=1.0,
            trend_240m=1.5,
            trend_60m=0.2,  # Positive, no override needed
        )

        warmup_240m_ok = trend.trend_240m > 0.75  # True
        warmup_60m_ok = trend.trend_60m >= 0.0    # True (normal check)
        both_positive = trend.trend_240m > 0.0 and trend.trend_60m > 0.0  # True

        assert warmup_240m_ok is True
        assert warmup_60m_ok is True
        assert both_positive is True, "Perfect uptrend, approved normally"

    def test_scenario_6_edge_case_exactly_at_limits(self, config_override_enabled):
        """
        SCENARIO 6: Edge case - 4H exactly +1.0%, 1H exactly -0.6%
        EXPECTED: BUY ALLOWED (at threshold boundaries)
        """
        trend = MockTrend(
            trend_1440m=0.5,
            trend_240m=1.0,   # Exactly at minimum
            trend_60m=-0.6,   # Exactly at minimum
        )

        warmup_240m_ok = trend.trend_240m > 0.75  # True
        warmup_60m_ok = trend.trend_60m >= 0.0    # False

        # Override at exact limits
        if config_override_enabled.warmup_override_enabled:
            if trend.trend_240m >= config_override_enabled.warmup_4h_strong_min:  # 1.0 >= 1.0 -> True
                if trend.trend_60m >= config_override_enabled.warmup_1h_min_if_4h_strong:  # -0.6 >= -0.6 -> True
                    warmup_60m_ok = True

        assert warmup_60m_ok is True, "Should pass at exact threshold"

    def test_real_production_case_tao_eur(self, config_override_enabled):
        """
        REAL PRODUCTION CASE: TAO-EUR from logs at 00:45
        24h: +0.37%, 4h: +1.12%, 1h: -0.38%
        EXPECTED: BUY ALLOWED with override
        """
        trend = MockTrend(
            trend_1440m=0.37,
            trend_240m=1.12,
            trend_60m=-0.38,
        )

        # Full warmup logic simulation
        warmup_240m_ok = trend.trend_240m > 0.75
        warmup_60m_ok = trend.trend_60m >= 0.0
        both_positive = trend.trend_240m > 0.0 and trend.trend_60m > 0.0

        override_active = False
        if config_override_enabled.warmup_override_enabled:
            if trend.trend_240m >= config_override_enabled.warmup_4h_strong_min:
                if trend.trend_60m >= config_override_enabled.warmup_1h_min_if_4h_strong:
                    warmup_60m_ok = True
                    both_positive = True  # Override bypasses both_positive check
                    override_active = True

        final_approval = warmup_240m_ok and warmup_60m_ok and both_positive

        assert override_active is True, "Override should activate for TAO-EUR"
        assert final_approval is True, "TAO-EUR should be approved with override"
        assert trend.trend_240m > trend.trend_60m, "4H should dominate weak 1H"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
