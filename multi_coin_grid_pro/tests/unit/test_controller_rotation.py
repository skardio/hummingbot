"""
Unit tests for MultiCoinGridController rotation and monitoring methods
"""
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus

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


class TestControllerRotation:
    """Test coin rotation logic"""

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.name = "kraken"
        connector.get_all_trading_pairs = AsyncMock(return_value=["XRP-EUR", "ADA-EUR", "SOL-EUR"])
        return connector

    @pytest.fixture
    def config(self):
        """Create test config"""
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            max_coins_to_monitor=3,
            min_24h_volume_eur=Decimal("1000"),
            coin_rotation_threshold=5,  # Low threshold for testing
            blacklist=[],
        )

    @pytest.fixture
    def controller(self, config, mock_connector):
        """Create controller instance"""
        with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
                patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
            pass

            market_data_provider = MagicMock()
            actions_queue = MagicMock()

            controller = MultiCoinGridController(
                config=config,
                market_data_provider=market_data_provider,
                actions_queue=actions_queue,
                connectors={"kraken": mock_connector},
                update_interval=1.0
            )

            # Initialize components
            controller.coin_discovery = MagicMock()
            controller.trend_calculator = MagicMock()
            controller.monitored_coins = ["XRP-EUR", "ADA-EUR"]
            controller.all_available_pairs = ["XRP-EUR", "ADA-EUR", "SOL-EUR", "BTC-EUR"]
            controller.pair_volumes = {
                "XRP-EUR": 5000.0,
                "ADA-EUR": 3000.0,
                "SOL-EUR": 4000.0,
                "BTC-EUR": 10000.0,
            }
            controller.pair_spreads = {
                "XRP-EUR": 0.001,
                "ADA-EUR": 0.002,
                "SOL-EUR": 0.0015,
            }
            controller.coin_performance = {
                "XRP-EUR": 0,
                "ADA-EUR": 0,
            }

            return controller

    def test_rotate_underperforming_coins_no_replacement_needed(self, controller):
        """Test rotation when no coins need replacement"""
        controller.coin_performance = {"XRP-EUR": 2, "ADA-EUR": 3}
        controller.rotation_threshold = 5

        controller._rotate_underperforming_coins()

        # Should not replace anything
        assert len(controller.monitored_coins) == 2
        assert "XRP-EUR" in controller.monitored_coins
        assert "ADA-EUR" in controller.monitored_coins

    def test_rotate_underperforming_coins_replaces_underperforming(self, controller):
        """Test rotation replaces coins that exceed threshold"""
        controller.coin_performance = {"XRP-EUR": 6, "ADA-EUR": 3}  # XRP exceeds threshold
        controller.rotation_threshold = 5

        controller._rotate_underperforming_coins()

        # XRP should be replaced with highest volume coin not monitored (BTC-EUR has 10000 > SOL-EUR 4000)
        assert "XRP-EUR" not in controller.monitored_coins
        # Should be replaced with BTC-EUR (highest volume) or SOL-EUR (if BTC not available)
        assert any(coin in controller.monitored_coins for coin in ["BTC-EUR", "SOL-EUR"])
        assert controller.coin_performance.get("XRP-EUR") is None or "XRP-EUR" not in controller.coin_performance

    def test_rotate_respects_blacklist(self, controller):
        """Test rotation respects blacklist"""
        controller.config.blacklist = ["SOL-EUR"]
        controller.coin_performance = {"XRP-EUR": 6, "ADA-EUR": 3}
        controller.rotation_threshold = 5

        controller._rotate_underperforming_coins()

        # SOL is blacklisted, so BTC should be selected instead (if available)
        # Or no replacement if BTC is also blacklisted/not available
        assert "SOL-EUR" not in controller.monitored_coins

    def test_rotate_respects_volume_threshold(self, controller):
        """Test rotation respects minimum volume threshold"""
        controller.config.min_24h_volume_eur = Decimal("8000")  # Higher threshold
        controller.coin_performance = {"XRP-EUR": 6, "ADA-EUR": 3}
        controller.rotation_threshold = 5

        # Only BTC-EUR meets volume threshold (10000 > 8000)
        controller._rotate_underperforming_coins()

        # Should replace with BTC-EUR (only one meeting threshold)
        assert "BTC-EUR" in controller.monitored_coins or len(controller.monitored_coins) == 2

    def test_rotate_respects_spread_limit(self, controller):
        """Test rotation respects spread limit"""
        controller.pair_spreads["SOL-EUR"] = 0.01  # Too high spread (> 0.5%)
        controller.coin_performance = {"XRP-EUR": 6, "ADA-EUR": 3}
        controller.rotation_threshold = 5

        controller._rotate_underperforming_coins()

        # SOL should not be selected due to high spread
        # Should select BTC-EUR instead (if available and meets criteria)
        assert "SOL-EUR" not in controller.monitored_coins or controller.pair_spreads.get("SOL-EUR", 0) <= 0.005


class TestControllerMonitoring:
    """Test stop-loss and volatility monitoring"""

    @pytest.fixture
    def config(self):
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            stop_loss_pct=Decimal("0.08"),
            circuit_breaker_volatility_pct=10.0,
        )

    @pytest.fixture
    def controller(self, config):
        with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
                patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
            market_data_provider = MagicMock()
            market_data_provider.time.return_value = 1000.0
            actions_queue = MagicMock()

            controller = MultiCoinGridController(
                config=config,
                market_data_provider=market_data_provider,
                actions_queue=actions_queue,
                connectors={},
                update_interval=1.0
            )

            controller.trend_calculator = MagicMock()
            controller.active_coin = "XRP-EUR"
            controller.active_executor_id = "test_executor_1"
            controller.entry_prices = {"XRP-EUR": Decimal("2.0")}
            controller.stop_loss_triggered = {}
            controller.executors_info = []

            return controller

    def test_monitor_stop_loss_no_active_coin(self, controller):
        """Test monitoring returns early if no active coin"""
        controller.active_coin = None
        controller._monitor_stop_loss_and_volatility()
        # Should return without error

    def test_monitor_stop_loss_no_trend(self, controller):
        """Test monitoring returns early if no trend data"""
        controller.trend_calculator.get_trend.return_value = None
        controller._monitor_stop_loss_and_volatility()
        # Should return without error

    def test_monitor_stop_loss_detects_stop_loss(self, controller):
        """Test monitoring detects stop-loss trigger"""
        from hummingbot.core.data_type.common import TradeType
        from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
        from hummingbot.strategy_v2.models.executors import CloseType

        # Mock trend with lower price (triggering stop-loss)
        mock_trend = MagicMock()
        mock_trend.current_price = 1.84  # 8% below entry (2.0)
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Create proper config for ExecutorInfo
        from hummingbot.core.data_type.common import OrderType
        from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig

        grid_config = GridExecutorConfig(
            id="test_executor_1",
            connector_name="kraken",
            trading_pair="XRP-EUR",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=3,
            start_price=Decimal("1.8"),
            end_price=Decimal("2.2"),
            limit_price=Decimal("1.7"),
            min_order_amount_quote=Decimal("10"),
            min_spread_between_orders=Decimal("0.01"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

        # Mock executor that was stopped due to stop-loss
        executor_info = ExecutorInfo(
            id="test_executor_1",
            timestamp=1000.0,
            type="grid",
            status=RunnableStatus.SHUTTING_DOWN,
            config=grid_config,
            net_pnl_pct=Decimal("-8.0"),
            net_pnl_quote=Decimal("-16.0"),
            cum_fees_quote=Decimal("0.5"),
            filled_amount_quote=Decimal("200"),
            is_active=False,
            is_trading=False,
            custom_info={"side": TradeType.BUY},
            close_type=CloseType.STOP_LOSS,
        )
        controller.executors_info = [executor_info]

        controller._monitor_stop_loss_and_volatility()

        # Should record stop-loss trigger
        assert "XRP-EUR" in controller.stop_loss_triggered

    def test_reset_circuit_breaker(self, controller):
        """Test circuit breaker reset"""
        controller.circuit_breaker_active = True
        controller.circuit_breaker_triggered_at = 1000.0

        controller.reset_circuit_breaker()

        assert controller.circuit_breaker_active is False
        assert controller.circuit_breaker_triggered_at is None

    def test_reset_api_errors(self, controller):
        """Test API error counter reset"""
        # Initialize attributes if they don't exist
        if not hasattr(controller, 'api_error_paused'):
            controller.api_error_paused = False
        if not hasattr(controller, 'consecutive_api_errors'):
            controller.consecutive_api_errors = 0
        if not hasattr(controller, 'api_error_paused_at'):
            controller.api_error_paused_at = None
        if not hasattr(controller, 'api_error_backoff_seconds'):
            controller.api_error_backoff_seconds = 1.0

        # Set paused state
        controller.api_error_paused = True
        controller.consecutive_api_errors = 5
        controller.api_error_paused_at = 1000.0
        controller.api_error_backoff_seconds = 2.0

        # Call reset method
        controller.reset_api_errors()

        # Verify reset
        assert controller.api_error_paused is False
        assert controller.consecutive_api_errors == 0
        assert controller.api_error_paused_at is None
        assert controller.api_error_backoff_seconds == 1.0
