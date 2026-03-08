"""
Tests for Sprint 1-3 Futures Risk Management Features.

Sprint 1: Portfolio Exposure Caps
Sprint 2: Funding Rate Filter + Correlation Filter
Sprint 3: Trailing Stop + Dynamic Timeout
"""
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from multi_coin_grid_pro.futures_bitget.config_schema import (  # noqa: E402
    FuturesGridBitgetConfig,
    FuturesTradeDirection,
)
from multi_coin_grid_pro.futures_bitget.controller import FuturesGridBitgetController  # noqa: E402


def create_mock_executor(trading_pair: str, is_active: bool = True):
    """Create a mock executor for testing."""
    executor = MagicMock()
    executor.is_active = is_active
    executor.config = MagicMock()
    executor.config.trading_pair = trading_pair
    executor.config.total_amount_quote = Decimal("100")
    executor.id = f"executor_{trading_pair}"
    return executor


def create_futures_controller(
    max_open_positions: int = 4,
    max_total_risk_pct: float = 8.0,
    max_notional_exposure_pct: float = 150.0,
    funding_rate_filter_enabled: bool = False,
    correlation_filter_enabled: bool = False,
    trailing_stop_enabled: bool = False,
    dynamic_timeout_enabled: bool = False,
    correlation_groups: dict = None,
):
    """Create a futures controller with specified config for testing."""
    config = FuturesGridBitgetConfig(
        controller_name="test_futures_controller",
        connector_name="bitget_perpetual",
        quote_asset="USDT",
        manual_trading_pairs=["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        total_amount_quote=Decimal("1000.0"),
        stop_loss_pct=Decimal("0.015"),
        price_update_interval=30,
        # Risk management config
        risk_reference_balance_quote=Decimal("1500"),
        risk_max_daily_loss_pct=Decimal("5"),
        risk_max_balance_per_trade_pct=Decimal("2"),
        risk_max_total_open_risk_pct=Decimal("10"),
        risk_exit_cooldown_minutes=30,
        risk_symbol_switch_cooldown_minutes=15,
        risk_consecutive_loss_cooldown_minutes=60,
        # Sprint 1: Portfolio caps
        max_open_positions=max_open_positions,
        max_total_risk_pct=max_total_risk_pct,
        max_notional_exposure_pct=max_notional_exposure_pct,
        # Sprint 2: Funding rate filter
        funding_rate_filter_enabled=funding_rate_filter_enabled,
        max_funding_cost_pct=0.03,
        funding_rate_cache_seconds=300,
        # Sprint 2: Correlation filter
        correlation_filter_enabled=correlation_filter_enabled,
        max_correlated_positions=1,
        correlation_groups=correlation_groups or {},  # Pass directly to config
        # Sprint 3: Trailing stop
        trailing_stop_enabled=trailing_stop_enabled,
        trailing_stop_activation_pct=2.0,
        trailing_stop_distance_pct=1.0,
        # Sprint 3: Dynamic timeout
        dynamic_timeout_enabled=dynamic_timeout_enabled,
        base_grid_timeout_seconds=3600,
        low_volatility_multiplier=2.0,
        high_volatility_multiplier=0.5,
        volatility_threshold_low=0.5,
        volatility_threshold_high=2.0,
        # Futures-specific
        futures_min_entry_strength_24h=1.5,
        futures_min_entry_strength_4h=1.0,
        futures_min_entry_strength_1h=0.0,
        derivative_leverage=5,
    )

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = 1000000.0

    controller = FuturesGridBitgetController(
        config=config,
        market_data_provider=market_data_provider,
        actions_queue=MagicMock(),
        connectors={},
        update_interval=10.0
    )

    # Setup mocks
    controller.trend_calculator = MagicMock()
    controller.market_data_provider = market_data_provider
    logger_instance = MagicMock()
    controller.logger = MagicMock(return_value=logger_instance)
    controller._logger_instance = logger_instance

    return controller


# =============================================================================
# SPRINT 1: PORTFOLIO EXPOSURE CAPS TESTS
# =============================================================================

class TestPortfolioExposureCaps:
    """Tests for Sprint 1 Portfolio Exposure Caps"""

    def test_max_open_positions_allows_when_below_limit(self):
        """Test that trades are allowed when below max_open_positions"""
        controller = create_futures_controller(max_open_positions=4)
        controller.executors_info = [
            create_mock_executor("BTC-USDT", is_active=True),
            create_mock_executor("ETH-USDT", is_active=True),
        ]

        can_open, reason = controller._check_portfolio_exposure_caps("SOL-USDT", Decimal("30"))
        assert can_open is True
        assert reason == ""

    def test_max_open_positions_blocks_when_at_limit(self):
        """Test that trades are blocked when at max_open_positions"""
        controller = create_futures_controller(max_open_positions=2)
        controller.executors_info = [
            create_mock_executor("BTC-USDT", is_active=True),
            create_mock_executor("ETH-USDT", is_active=True),
        ]

        can_open, reason = controller._check_portfolio_exposure_caps("SOL-USDT", Decimal("30"))
        assert can_open is False
        assert "MAX_POSITIONS" in reason
        assert "2/2" in reason

    def test_max_total_risk_blocks_when_exceeded(self):
        """Test that trades are blocked when max_total_risk_pct would be exceeded"""
        # 4 grids at 2% each = 8% total, adding another would be 10% > 8%
        controller = create_futures_controller(max_open_positions=10, max_total_risk_pct=8.0)
        controller.executors_info = [
            create_mock_executor("BTC-USDT", is_active=True),
            create_mock_executor("ETH-USDT", is_active=True),
            create_mock_executor("SOL-USDT", is_active=True),
            create_mock_executor("DOGE-USDT", is_active=True),
        ]

        can_open, reason = controller._check_portfolio_exposure_caps("AVAX-USDT", Decimal("30"))
        assert can_open is False
        assert "MAX_TOTAL_RISK" in reason

    def test_max_notional_exposure_blocks_when_exceeded(self):
        """Test that trades are blocked when max_notional_exposure_pct would be exceeded"""
        controller = create_futures_controller(
            max_open_positions=10,
            max_total_risk_pct=50.0,  # High limit so it doesn't trigger
            max_notional_exposure_pct=150.0,  # 150% of 1500 = 2250 max
        )

        # Mock connector with existing positions
        controller.connector = MagicMock()
        mock_position = MagicMock()
        mock_position.amount = Decimal("1")  # 1 BTC
        mock_position.entry_price = Decimal("50000")  # $50k entry = $50k notional
        controller.connector.account_positions = {"BTC-USDT_LONG": mock_position}

        controller.executors_info = []

        # Try to add position that would exceed notional cap
        # Current: 50000, requesting: 30 * 5 leverage = 150
        # But we need to exceed 2250, so let's use a bigger position
        can_open, reason = controller._check_portfolio_exposure_caps("SOL-USDT", Decimal("500"))
        # 500 * 5 = 2500 notional, plus existing 50000 = 52500 > 2250
        assert can_open is False
        assert "MAX_NOTIONAL" in reason

    def test_all_caps_pass_allows_trade(self):
        """Test that trades are allowed when all caps pass"""
        controller = create_futures_controller(
            max_open_positions=5,
            max_total_risk_pct=15.0,
            max_notional_exposure_pct=200.0,
        )
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        can_open, reason = controller._check_portfolio_exposure_caps("ETH-USDT", Decimal("30"))
        assert can_open is True


# =============================================================================
# SPRINT 2: FUNDING RATE FILTER TESTS
# =============================================================================

class TestFundingRateFilter:
    """Tests for Sprint 2 Funding Rate Filter"""

    def test_funding_filter_disabled_allows_all(self):
        """Test that trades are allowed when funding filter is disabled"""
        controller = create_futures_controller(funding_rate_filter_enabled=False)
        controller._funding_rate_cache = {"BTC-USDT": {"rate": 0.1, "timestamp": 1000000.0}}

        can_trade, reason = controller._check_funding_rate_filter(
            "BTC-USDT", FuturesTradeDirection.LONG
        )
        assert can_trade is True
        assert reason == ""

    def test_funding_filter_blocks_long_when_paying_high_rate(self):
        """Test that LONG trades are blocked when funding rate is high (longs pay)"""
        controller = create_futures_controller(funding_rate_filter_enabled=True)
        controller.config.max_funding_cost_pct = 0.03  # Max 0.03%
        # Use current time from market_data_provider
        current_time = controller.market_data_provider.time()
        # Positive funding = longs pay, rate 0.05% > 0.03% max
        controller._funding_rate_cache = {"BTC-USDT": {"rate": 0.05, "timestamp": current_time}}

        can_trade, reason = controller._check_funding_rate_filter(
            "BTC-USDT", FuturesTradeDirection.LONG
        )
        assert can_trade is False
        assert "FUNDING_RATE" in reason
        assert "LONG" in reason
        assert "pay" in reason

    def test_funding_filter_allows_long_when_receiving(self):
        """Test that LONG trades are allowed when funding is negative (longs receive)"""
        controller = create_futures_controller(funding_rate_filter_enabled=True)
        current_time = controller.market_data_provider.time()
        # Negative funding = longs receive
        controller._funding_rate_cache = {"BTC-USDT": {"rate": -0.05, "timestamp": current_time}}

        can_trade, reason = controller._check_funding_rate_filter(
            "BTC-USDT", FuturesTradeDirection.LONG
        )
        assert can_trade is True

    def test_funding_filter_blocks_short_when_paying_high_rate(self):
        """Test that SHORT trades are blocked when funding rate is negative (shorts pay)"""
        controller = create_futures_controller(funding_rate_filter_enabled=True)
        controller.config.max_funding_cost_pct = 0.03
        current_time = controller.market_data_provider.time()
        # Negative funding = shorts pay, rate -0.05% means shorts pay 0.05%
        controller._funding_rate_cache = {"BTC-USDT": {"rate": -0.05, "timestamp": current_time}}

        can_trade, reason = controller._check_funding_rate_filter(
            "BTC-USDT", FuturesTradeDirection.SHORT
        )
        assert can_trade is False
        assert "FUNDING_RATE" in reason
        assert "SHORT" in reason

    def test_funding_filter_allows_short_when_receiving(self):
        """Test that SHORT trades are allowed when funding is positive (shorts receive)"""
        controller = create_futures_controller(funding_rate_filter_enabled=True)
        current_time = controller.market_data_provider.time()
        # Positive funding = shorts receive
        controller._funding_rate_cache = {"BTC-USDT": {"rate": 0.05, "timestamp": current_time}}

        can_trade, reason = controller._check_funding_rate_filter(
            "BTC-USDT", FuturesTradeDirection.SHORT
        )
        assert can_trade is True

    def test_funding_cache_expiry(self):
        """Test that expired cache returns None"""
        controller = create_futures_controller(funding_rate_filter_enabled=True)
        controller.config.funding_rate_cache_seconds = 300
        current_time = controller.market_data_provider.time()
        # Cache from 1000 seconds ago (expired)
        controller._funding_rate_cache = {"BTC-USDT": {"rate": 0.05, "timestamp": current_time - 1000}}

        rate = controller._get_cached_funding_rate("BTC-USDT")
        assert rate is None


# =============================================================================
# SPRINT 2: CORRELATION FILTER TESTS
# =============================================================================

class TestCorrelationFilter:
    """Tests for Sprint 2 Correlation Filter"""

    def test_correlation_filter_disabled_allows_all(self):
        """Test that trades are allowed when correlation filter is disabled"""
        controller = create_futures_controller(correlation_filter_enabled=False)
        can_trade, reason = controller._check_correlation_filter("BTC-USDT")
        assert can_trade is True

    def test_correlation_filter_blocks_same_group(self):
        """Test that trades in same correlation group are blocked"""
        correlation_groups = {
            "major_caps": ["BTC-USDT", "ETH-USDT"],
            "layer1_alts": ["SOL-USDT", "AVAX-USDT"],
        }
        controller = create_futures_controller(
            correlation_filter_enabled=True,
            correlation_groups=correlation_groups,
        )
        controller.config.correlation_groups = correlation_groups

        # Active executor in BTC (major_caps group)
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        # Try to open ETH (same group)
        can_trade, reason = controller._check_correlation_filter("ETH-USDT")
        assert can_trade is False
        assert "CORRELATION" in reason
        assert "major_caps" in reason

    def test_correlation_filter_allows_different_group(self):
        """Test that trades in different correlation groups are allowed"""
        correlation_groups = {
            "major_caps": ["BTC-USDT", "ETH-USDT"],
            "layer1_alts": ["SOL-USDT", "AVAX-USDT"],
        }
        controller = create_futures_controller(
            correlation_filter_enabled=True,
            correlation_groups=correlation_groups,
        )

        # Active executor in BTC (major_caps group)
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        # Try to open SOL (different group)
        can_trade, reason = controller._check_correlation_filter("SOL-USDT")
        assert can_trade is True

    def test_correlation_filter_allows_ungrouped_coin(self):
        """Test that ungrouped coins are always allowed"""
        correlation_groups = {
            "major_caps": ["BTC-USDT", "ETH-USDT"],
        }
        controller = create_futures_controller(
            correlation_filter_enabled=True,
            correlation_groups=correlation_groups,
        )

        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        # DOGE is not in any group
        can_trade, reason = controller._check_correlation_filter("DOGE-USDT")
        assert can_trade is True

    def test_get_correlation_group(self):
        """Test getting correlation group for a symbol"""
        correlation_groups = {
            "major_caps": ["BTC-USDT", "ETH-USDT"],
            "layer1_alts": ["SOL-USDT", "AVAX-USDT"],
        }
        controller = create_futures_controller(correlation_groups=correlation_groups)

        assert controller._get_correlation_group("BTC-USDT") == "major_caps"
        assert controller._get_correlation_group("SOL-USDT") == "layer1_alts"
        assert controller._get_correlation_group("DOGE-USDT") is None


# =============================================================================
# SPRINT 3: TRAILING STOP TESTS
# =============================================================================

class TestTrailingStop:
    """Tests for Sprint 3 Trailing Stop"""

    def test_trailing_stop_disabled_returns_none(self):
        """Test that trailing stop returns None when disabled"""
        controller = create_futures_controller(trailing_stop_enabled=False)
        result = controller._check_trailing_stop("BTC-USDT")
        assert result is None

    def test_trailing_stop_activates_at_threshold(self):
        """Test that trailing stop activates at the activation threshold"""
        controller = create_futures_controller(trailing_stop_enabled=True)
        controller.config.trailing_stop_activation_pct = 2.0

        # Mock position with 2.5% PnL (above 2% activation)
        controller._get_position_pnl_pct = MagicMock(return_value=Decimal("2.5"))
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        # First check - should activate but not trigger
        result = controller._check_trailing_stop("BTC-USDT")
        assert result is None  # Not triggered yet, just activated
        assert controller._trailing_stop_activated.get("BTC-USDT") is True
        assert controller._trailing_stop_high_water_marks.get("BTC-USDT") == Decimal("2.5")

    def test_trailing_stop_updates_high_water_mark(self):
        """Test that high water mark is updated on new highs"""
        controller = create_futures_controller(trailing_stop_enabled=True)
        controller._trailing_stop_activated["BTC-USDT"] = True
        controller._trailing_stop_high_water_marks["BTC-USDT"] = Decimal("2.5")

        # Mock position with higher PnL
        controller._get_position_pnl_pct = MagicMock(return_value=Decimal("3.0"))
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        controller._check_trailing_stop("BTC-USDT")

        # High water mark should be updated
        assert controller._trailing_stop_high_water_marks["BTC-USDT"] == Decimal("3.0")

    def test_trailing_stop_triggers_on_distance_exceeded(self):
        """Test that trailing stop triggers when distance from high is exceeded"""
        controller = create_futures_controller(trailing_stop_enabled=True)
        controller.config.trailing_stop_distance_pct = 1.0

        controller._trailing_stop_activated["BTC-USDT"] = True
        controller._trailing_stop_high_water_marks["BTC-USDT"] = Decimal("3.0")

        # Mock position with PnL dropped 1.5% from high (3.0 - 1.5 = 1.5% PnL)
        controller._get_position_pnl_pct = MagicMock(return_value=Decimal("1.5"))
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        result = controller._check_trailing_stop("BTC-USDT")

        # Should trigger stop action (distance 1.5% > 1.0% threshold)
        assert result is not None

    def test_trailing_stop_does_not_trigger_within_distance(self):
        """Test that trailing stop does not trigger when within allowed distance"""
        controller = create_futures_controller(trailing_stop_enabled=True)
        controller.config.trailing_stop_distance_pct = 1.0

        controller._trailing_stop_activated["BTC-USDT"] = True
        controller._trailing_stop_high_water_marks["BTC-USDT"] = Decimal("3.0")

        # Mock position with PnL dropped only 0.5% from high
        controller._get_position_pnl_pct = MagicMock(return_value=Decimal("2.5"))
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        result = controller._check_trailing_stop("BTC-USDT")

        # Should NOT trigger (distance 0.5% < 1.0% threshold)
        assert result is None

    def test_reset_trailing_stop(self):
        """Test that trailing stop state is properly reset"""
        controller = create_futures_controller(trailing_stop_enabled=True)
        controller._trailing_stop_activated["BTC-USDT"] = True
        controller._trailing_stop_high_water_marks["BTC-USDT"] = Decimal("3.0")

        controller._reset_trailing_stop("BTC-USDT")

        assert "BTC-USDT" not in controller._trailing_stop_activated
        assert "BTC-USDT" not in controller._trailing_stop_high_water_marks


# =============================================================================
# SPRINT 3: DYNAMIC TIMEOUT TESTS
# =============================================================================

class TestDynamicTimeout:
    """Tests for Sprint 3 Dynamic Timeout"""

    def test_dynamic_timeout_disabled_returns_base(self):
        """Test that base timeout is returned when dynamic timeout is disabled"""
        controller = create_futures_controller(dynamic_timeout_enabled=False)
        controller.config.risk_guard_max_grid_time_seconds = 3600

        timeout = controller._get_dynamic_timeout("BTC-USDT")
        assert timeout == 3600

    def test_dynamic_timeout_extends_for_low_volatility(self):
        """Test that timeout is extended in low volatility"""
        controller = create_futures_controller(dynamic_timeout_enabled=True)
        controller.config.base_grid_timeout_seconds = 3600
        controller.config.low_volatility_multiplier = 2.0
        controller.config.volatility_threshold_low = 0.5

        # Mock low volatility (ATR 0.3%)
        mock_trend = MagicMock()
        mock_trend.atr_pct = 0.3
        controller.trend_calculator.get_trend.return_value = mock_trend

        timeout = controller._get_dynamic_timeout("BTC-USDT")
        assert timeout == 7200  # 3600 * 2.0

    def test_dynamic_timeout_shortens_for_high_volatility(self):
        """Test that timeout is shortened in high volatility"""
        controller = create_futures_controller(dynamic_timeout_enabled=True)
        controller.config.base_grid_timeout_seconds = 3600
        controller.config.high_volatility_multiplier = 0.5
        controller.config.volatility_threshold_high = 2.0

        # Mock high volatility (ATR 3.0%)
        mock_trend = MagicMock()
        mock_trend.atr_pct = 3.0
        controller.trend_calculator.get_trend.return_value = mock_trend

        timeout = controller._get_dynamic_timeout("BTC-USDT")
        assert timeout == 1800  # 3600 * 0.5

    def test_dynamic_timeout_uses_base_for_normal_volatility(self):
        """Test that base timeout is used for normal volatility"""
        controller = create_futures_controller(dynamic_timeout_enabled=True)
        controller.config.base_grid_timeout_seconds = 3600
        controller.config.volatility_threshold_low = 0.5
        controller.config.volatility_threshold_high = 2.0

        # Mock normal volatility (ATR 1.0%)
        mock_trend = MagicMock()
        mock_trend.atr_pct = 1.0
        controller.trend_calculator.get_trend.return_value = mock_trend

        timeout = controller._get_dynamic_timeout("BTC-USDT")
        assert timeout == 3600  # Base timeout unchanged


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestCreateGridActionIntegration:
    """Integration tests for _create_grid_action with all filters"""

    def test_create_grid_action_blocked_by_portfolio_cap(self):
        """Test that grid action is blocked when portfolio cap is reached"""
        controller = create_futures_controller(max_open_positions=2)
        controller.executors_info = [
            create_mock_executor("BTC-USDT", is_active=True),
            create_mock_executor("ETH-USDT", is_active=True),
        ]

        result = controller._create_grid_action("SOL-USDT")
        assert result is None

    def test_create_grid_action_blocked_by_correlation(self):
        """Test that grid action is blocked by correlation filter"""
        correlation_groups = {"major_caps": ["BTC-USDT", "ETH-USDT"]}
        controller = create_futures_controller(
            correlation_filter_enabled=True,
            correlation_groups=correlation_groups,
        )
        controller.config.correlation_groups = correlation_groups
        controller.executors_info = [create_mock_executor("BTC-USDT", is_active=True)]

        result = controller._create_grid_action("ETH-USDT")
        assert result is None


# =============================================================================
# CONFIG SCHEMA TESTS
# =============================================================================

class TestFuturesConfigSchema:
    """Tests for the config schema with new parameters"""

    def test_config_has_sprint1_params(self):
        """Test that config schema has Sprint 1 parameters"""
        config = FuturesGridBitgetConfig(
            connector_name="bitget_perpetual",
            quote_asset="USDT",
            manual_trading_pairs=["BTC-USDT"],
        )
        assert hasattr(config, 'max_open_positions')
        assert hasattr(config, 'max_total_risk_pct')
        assert hasattr(config, 'max_notional_exposure_pct')

    def test_config_has_sprint2_params(self):
        """Test that config schema has Sprint 2 parameters"""
        config = FuturesGridBitgetConfig(
            connector_name="bitget_perpetual",
            quote_asset="USDT",
            manual_trading_pairs=["BTC-USDT"],
        )
        assert hasattr(config, 'funding_rate_filter_enabled')
        assert hasattr(config, 'max_funding_cost_pct')
        assert hasattr(config, 'correlation_filter_enabled')
        assert hasattr(config, 'max_correlated_positions')

    def test_config_has_sprint3_params(self):
        """Test that config schema has Sprint 3 parameters"""
        config = FuturesGridBitgetConfig(
            connector_name="bitget_perpetual",
            quote_asset="USDT",
            manual_trading_pairs=["BTC-USDT"],
        )
        assert hasattr(config, 'trailing_stop_enabled')
        assert hasattr(config, 'trailing_stop_activation_pct')
        assert hasattr(config, 'trailing_stop_distance_pct')
        assert hasattr(config, 'dynamic_timeout_enabled')
        assert hasattr(config, 'base_grid_timeout_seconds')

    def test_config_defaults(self):
        """Test that config has correct defaults"""
        config = FuturesGridBitgetConfig(
            connector_name="bitget_perpetual",
            quote_asset="USDT",
            manual_trading_pairs=["BTC-USDT"],
        )
        # Sprint 1 defaults
        assert config.max_open_positions == 4
        assert config.max_total_risk_pct == 8.0
        assert config.max_notional_exposure_pct == 150.0

        # Sprint 2 defaults (disabled by default)
        assert config.funding_rate_filter_enabled is False
        assert config.correlation_filter_enabled is False

        # Sprint 3 defaults (disabled by default)
        assert config.trailing_stop_enabled is False
        assert config.dynamic_timeout_enabled is False
