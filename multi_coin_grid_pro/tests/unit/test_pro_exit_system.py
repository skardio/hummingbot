"""
Unit tests for PRO EXIT SYSTEM - 5-Layer Stack

Tests Layer 3 (Price-Based Exit) and Layer 5 (Grid Profit Exit)
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

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus


@pytest.fixture
def controller():
    """Create controller instance with PRO EXIT SYSTEM config"""
    config = MultiCoinGridConfig(
        controller_name="test_controller",
        connector_name="kraken",
        quote_asset="EUR",
        manual_trading_pairs=["BTC-EUR"],
        # PRO EXIT SYSTEM config
        min_hold_time_seconds=3600,  # 1 hour
        emergency_exit_pct=-2.5,  # Exit at -2.5%
        hard_stop_pct=-4.0,  # Hard stop at -4.0%
        min_grid_profit_pct=0.6,  # Grid profit exit at 0.6%
        exit_short_threshold=-1.0,  # Trend exit thresholds
        exit_mid_threshold=0.0,
        # Risk management config (required for risk_manager initialization)
        risk_reference_balance_quote=Decimal("10000"),
        risk_max_daily_loss_pct=Decimal("2"),
        risk_max_balance_per_trade_pct=Decimal("0.5"),
        risk_max_total_open_risk_pct=Decimal("3"),
        risk_exit_cooldown_minutes=30,
        risk_symbol_switch_cooldown_minutes=45,
        risk_consecutive_loss_cooldown_minutes=60,
    )

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = 1000000.0  # Mock time

    actions_queue = MagicMock()
    connectors = {"kraken": MagicMock()}

    controller = MultiCoinGridController(
        config=config,
        market_data_provider=market_data_provider,
        actions_queue=actions_queue,
        connectors=connectors,
        update_interval=10.0
    )

    # Set up mock trend calculator
    controller.trend_calculator = MagicMock()

    # Set up mock executors_info
    controller.executors_info = []

    # Set last switch time (1 hour ago, so hold time is passed)
    controller.last_switch_time = 1000000.0 - 3600.0

    return controller


@pytest.fixture
def mock_trend():
    """Create mock trend object"""
    trend = MagicMock()
    trend.current_price = Decimal("50000.0")
    trend.trend_60m = 0.5  # Positive 1h trend
    trend.trend_240m = 1.0  # Positive 4h trend
    trend.trend_1440m = 2.0  # Positive 24h trend
    trend.last_updated = 1000000.0 - 10  # Recent update (10 seconds ago)
    trend.consensus_trend_pct = Decimal("1.5")  # For trend strength calculation
    trend.trend_pct = Decimal("1.5")  # Fallback value
    trend.trend_score = Decimal("1.5")  # For trend strength calculation
    return trend


def create_grid_config(entry_price: Decimal, executor_id: str = "test_executor_123") -> GridExecutorConfig:
    """Helper function to create GridExecutorConfig for tests"""
    return GridExecutorConfig(
        id=executor_id,
        timestamp=1000000.0,
        controller_id="test_controller",
        connector_name="kraken",
        trading_pair="BTC-EUR",
        side=TradeType.BUY,
        start_price=entry_price,
        end_price=entry_price * Decimal("1.1"),
        limit_price=entry_price * Decimal("0.95"),
        total_amount_quote=Decimal("5000.0"),
        triple_barrier_config=TripleBarrierConfig(
            stop_loss=Decimal("0.08"),
            take_profit=Decimal("0.02"),
            time_limit=None,
            trailing_stop=None,
            open_order_type=OrderType.LIMIT_MAKER,
            take_profit_order_type=OrderType.LIMIT_MAKER,
            stop_loss_order_type=OrderType.MARKET,
            time_limit_order_type=OrderType.MARKET,
        ),
    )


class TestLayer1HoldTime:
    """Test Layer 1: Minimum Hold Time"""

    def test_hold_time_blocks_exit(self, controller, mock_trend):
        """Test that exit is blocked during hold time grace period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 30 minutes ago (still in grace period)
        controller.last_switch_time = controller.market_data_provider.time() - 1800.0

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit) because hold time not passed
        result = controller.should_exit_position(coin)
        assert result is None

    def test_hold_time_allows_exit_after_period(self, controller, mock_trend):
        """Test that exit is allowed after hold time period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement (> -1.5%)
        current_price = Decimal("49000.0")  # -2.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 2 hours ago (hold time passed, including hard minimum)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with negative trends to trigger trend exit
        mock_trend.current_price = current_price  # BUG FIX: Set current price
        mock_trend.trend_60m = -1.5  # Below threshold
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return exit reason (trend exit)
        result = controller.should_exit_position(coin)
        assert result == "trend_exit"


class TestLayer3PriceBasedExit:
    """Test Layer 3: Price-Based Emergency Exits"""

    def test_emergency_exit_triggered(self, controller, mock_trend):
        """Test that emergency exit is triggered at -2.5%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with current price
        mock_trend.current_price = current_price
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"

    def test_emergency_exit_not_triggered_above_threshold(self, controller, mock_trend):
        """Test that emergency exit is NOT triggered above -2.5%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("49000.0")  # -2.0% drop (above threshold)

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with current price
        mock_trend.current_price = current_price
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no emergency exit)
        result = controller.should_exit_position(coin)
        assert result != "emergency_exit"

    def test_hard_stop_triggered(self, controller, mock_trend):
        """Test that hard stop is triggered at -4.0%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48000.0")  # -4.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with current price
        mock_trend.current_price = current_price
        # BUG FIX: Ensure trends are positive so emergency_exit doesn't trigger first
        mock_trend.trend_60m = 0.5
        mock_trend.trend_240m = 0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return hard_stop_exit (emergency_exit checks first, but -4.0% is below emergency threshold)
        # Actually, emergency_exit_pct is -2.5%, so -4.0% will trigger emergency_exit first
        # Let's adjust to test hard_stop specifically by setting emergency_exit_pct lower
        controller.config.emergency_exit_pct = -5.0  # Set emergency threshold lower than hard stop
        result = controller.should_exit_position(coin)
        assert result == "hard_stop_exit"

    def test_emergency_exit_priority_over_trend(self, controller, mock_trend):
        """Test that emergency exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% drop (emergency exit)

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with negative trends (would trigger trend exit)
        mock_trend.current_price = current_price
        mock_trend.trend_60m = -1.5  # Below threshold
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit (not trend_exit) because emergency has priority
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"


class TestLayer5GridProfitExit:
    """Test Layer 5: Grid Profit Exit"""

    def test_grid_profit_exit_triggered(self, controller, mock_trend):
        """Test that grid profit exit is triggered when realized profit >= 0.6%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit >= 0.6% NET (after 0.31% fees)
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        # 0.6% net + 0.31% fees = 0.91% gross -> 0.91% of 5000 = 45.5
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit (above 0.6% threshold)
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"

    def test_grid_profit_exit_not_triggered_below_threshold(self, controller, mock_trend):
        """Test that grid profit exit is NOT triggered when realized profit < 0.6%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit < 0.6%
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: Use real GridExecutorConfig instead of MagicMock
        grid_config = GridExecutorConfig(
            id="test_executor_123",
            timestamp=1000000.0,
            controller_id="test_controller",
            connector_name="kraken",
            trading_pair="BTC-EUR",
            side=TradeType.BUY,
            start_price=entry_price,
            end_price=entry_price * Decimal("1.1"),
            limit_price=entry_price * Decimal("0.95"),
            total_amount_quote=Decimal("5000.0"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=None,
                trailing_stop=None,
                open_order_type=OrderType.LIMIT_MAKER,
                take_profit_order_type=OrderType.LIMIT_MAKER,
                stop_loss_order_type=OrderType.MARKET,
                time_limit_order_type=OrderType.MARKET,
            ),
        )
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=grid_config,
            net_pnl_pct=Decimal("0.004"),  # 0.4% profit (below 0.6% threshold)
            net_pnl_quote=Decimal("20.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("15.0"),  # 0.3% of 5000 = 15 (below 0.6% threshold)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None or trend_exit (not grid_profit_exit)
        result = controller.should_exit_position(coin)
        assert result != "grid_profit_exit"

    def test_grid_profit_exit_priority_over_trend(self, controller, mock_trend):
        """Test that grid profit exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit >= 0.6% NET (after fees)
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement
        mock_trend.current_price = Decimal("49000.0")  # -2.0% drop
        mock_trend.trend_60m = -1.5  # Below threshold
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit (not trend_exit) because grid profit has priority
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"


class TestLayer2TrendExit:
    """Test Layer 2: Trend Exit (Macro Confirmation)"""

    def test_trend_exit_triggered(self, controller, mock_trend):
        """Test that trend exit is triggered when both trends are below thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement (> -1.5%)
        current_price = Decimal("49000.0")  # -2.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with negative trends
        mock_trend.current_price = current_price  # BUG FIX: Set current price
        mock_trend.trend_60m = -1.5  # Below -1.0% threshold
        mock_trend.trend_240m = -0.5  # Below 0.0% threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return trend_exit
        result = controller.should_exit_position(coin)
        assert result == "trend_exit"

    def test_trend_exit_not_triggered_above_thresholds(self, controller, mock_trend):
        """Test that trend exit is NOT triggered when trends are above thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with positive trends
        mock_trend.trend_60m = 0.5  # Above -1.0% threshold
        mock_trend.trend_240m = 0.5  # Above 0.0% threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no trend exit)
        result = controller.should_exit_position(coin)
        assert result != "trend_exit"


class TestExitPriority:
    """Test exit priority order"""

    def test_emergency_exit_has_highest_priority(self, controller, mock_trend):
        """Test that emergency exit has highest priority (checked first)"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% (emergency exit)

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID with high profit (would trigger grid profit exit)
        controller.active_executor_id = "test_executor_123"
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("30.0"),  # 0.6% of 5000 = 30
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        mock_trend.current_price = current_price
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit (highest priority)
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"

    def test_grid_profit_exit_priority_over_trend(self, controller, mock_trend):
        """Test that grid profit exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID with high profit
        controller.active_executor_id = "test_executor_123"
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement
        mock_trend.current_price = Decimal("49000.0")  # -2.0% drop
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit (priority over trend_exit)
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"


class TestNoExit:
    """Test cases where no exit should occur"""

    def test_no_exit_when_all_conditions_met_but_hold_time_not_passed(self, controller, mock_trend):
        """Test that no exit occurs during hold time grace period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 30 minutes ago (still in grace period)
        controller.last_switch_time = controller.market_data_provider.time() - 1800.0

        # Mock trend with negative trends (would trigger trend exit if hold time passed)
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit) because hold time not passed
        result = controller.should_exit_position(coin)
        assert result is None

    def test_no_exit_when_price_above_thresholds(self, controller, mock_trend):
        """Test that no exit occurs when price is above all thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("51000.0")  # +2.0% (above all thresholds)

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with positive trends
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 0.5  # Positive
        mock_trend.trend_240m = 1.0  # Positive
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit)
        result = controller.should_exit_position(coin)
        assert result is None
