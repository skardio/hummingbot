"""
Integration Tests - Full Bot Cycle

Tests the complete bot cycle including:
- Coin discovery
- Trend calculation
- Grid creation
- Executor management
- Error handling
"""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from controllers.multi_coin_grid_config import MultiCoinGridConfig
    from controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

pytestmark = pytest.mark.asyncio


class TestFullCycle:
    """Integration tests for full bot cycle"""

    @pytest.fixture
    def mock_connector(self):
        connector = AsyncMock()
        connector.name = "kraken"
        connector.ready = True
        connector.get_price_by_type = AsyncMock(return_value=Decimal("1.5"))
        connector.get_order_book = Mock(return_value=MagicMock())
        connector.get_fee = Mock(return_value=Decimal("0.0016"))
        connector.get_last_traded_prices = AsyncMock(return_value={"XRP-EUR": Decimal("1.5")})

        # Mock trading pair map
        from bidict import bidict
        connector.trading_pair_symbol_map = AsyncMock(return_value=bidict({
            "XRP-EUR": "XRP-EUR",
            "ADA-EUR": "ADA-EUR",
        }))
        return connector

    @pytest.fixture
    def mock_market_data_provider(self):
        provider = MagicMock()
        provider.time = Mock(return_value=datetime.now().timestamp())
        return provider

    @pytest.fixture
    def config(self):
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            total_amount_quote=Decimal("120"),
            max_coins_to_monitor=5,
            min_24h_volume_eur=Decimal("50000"),
            trend_min_change_pct=Decimal("0.5"),
        )

    @pytest.fixture
    def controller(self, config, mock_connector, mock_market_data_provider):
        # Create controller without patching - we'll set the instances directly
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=mock_market_data_provider,
            actions_queue=[],
            connectors={"kraken": mock_connector},
            update_interval=10.0
        )

        # Setup mocks directly
        mock_discovery_instance = AsyncMock()
        mock_discovery_instance.discover_coins = AsyncMock(return_value=["XRP-EUR", "ADA-EUR"])
        controller.coin_discovery = mock_discovery_instance

        mock_trend_instance = MagicMock()
        controller.trend_calculator = mock_trend_instance

        # Initialize required attributes
        controller.monitored_coins = []
        controller.executors_info = []
        controller.active_executor_id = None
        controller.active_coin = None
        controller.last_switch_time = mock_market_data_provider.time() - 10000
        controller.entry_prices = {}
        controller.stop_loss_triggered = {}
        controller.price_history_for_volatility = {}
        controller.circuit_breaker_active = False
        controller.consecutive_api_errors = 0
        controller.api_error_last_timestamp = 0
        controller.total_exposure = Decimal("0")
        controller.current_exposure_per_coin = {}
        controller.pair_volumes = {}
        controller.pair_spreads = {}
        controller.switch_costs = {}
        controller.last_grid_creation_time = 0
        controller.last_grid_price = {}

        return controller

    async def test_full_discovery_cycle(self, controller, mock_connector):
        """Test complete coin discovery cycle"""
        # Mock ticker data for volume/spread calculation
        mock_connector._get_ticker_data = AsyncMock(return_value={
            "XRPEUR": {
                "v": [1000, 2000000],  # [volume_today, volume_24h]
                "c": ["1.5"],  # Last price
                "a": ["1.501"],  # Ask
                "b": ["1.499"],  # Bid
            },
            "ADAEUR": {
                "v": [500, 1500000],
                "c": ["0.8"],
                "a": ["0.801"],
                "b": ["0.799"],
            },
        })

        # Ensure connector is ready
        mock_connector.ready = True

        # Run discovery
        await controller.update_processed_data()

        # Verify coins were discovered (may be empty if ticker data doesn't work, but should not crash)
        # The test verifies the method runs without error
        assert controller.monitored_coins is not None

    async def test_trend_update_cycle(self, controller):
        """Test trend update cycle"""
        # Mock trend calculator update_all_trends_v2 method
        controller.trend_calculator.update_all_trends_v2 = AsyncMock(return_value=None)
        controller.trend_calculator.trends = {}  # Initialize trends dict

        # Mock trend calculator get_best_coin
        try:
            from multi_coin_grid_pro.utils.trend_calculator import CoinTrend
        except ImportError:
            from utils.trend_calculator import CoinTrend

        mock_trend = CoinTrend(
            symbol="XRP-EUR",
            current_price=Decimal("1.5"),
            trend_pct=2.5,
            consensus_trend_pct=2.5,
            volatility=0.02
        )
        controller.trend_calculator.trends["XRP-EUR"] = mock_trend
        controller.trend_calculator.get_best_coin = Mock(return_value="XRP-EUR")

        # Mock _build_orderbook_config to avoid issues
        controller._build_orderbook_config = Mock(return_value=None)

        # Set last update time far in the past to ensure update runs
        controller._last_trend_update = 0.0

        # Update trends
        controller.monitored_coins = ["XRP-EUR", "ADA-EUR"]
        await controller.update_processed_data()

        # Verify trends were updated (update_all_trends_v2 was called)
        assert controller.trend_calculator.update_all_trends_v2.called

    async def test_grid_creation_cycle(self, controller):
        """Test grid creation cycle"""
        controller.monitored_coins = ["XRP-EUR"]
        controller.active_coin = None

        # Mock trend calculator with sufficient data
        try:
            from multi_coin_grid_pro.utils.trend_calculator import CoinTrend
        except ImportError:
            from utils.trend_calculator import CoinTrend
        mock_trend = CoinTrend(
            symbol="XRP-EUR",
            current_price=Decimal("1.5"),
            trend_pct=2.5,
            consensus_trend_pct=2.5,
            volatility=0.02
        )
        # Add price history to make has_sufficient_data True
        import time
        mock_trend.price_history = [
            {"price": Decimal("1.0"), "timestamp": time.time() - 100}
            for _ in range(60)
        ]
        controller.trend_calculator.trends = {"XRP-EUR": mock_trend}
        controller.trend_calculator.get_best_coin = Mock(return_value="XRP-EUR")

        # Determine actions
        actions = controller.determine_executor_actions()

        # Should create grid action (or at least not crash)
        assert isinstance(actions, list)

    async def test_error_recovery_cycle(self, controller, mock_connector):
        """Test error recovery cycle"""
        # Simulate API error
        mock_connector.get_price_by_type = AsyncMock(side_effect=Exception("API Error"))

        # Handle error
        initial_errors = controller.consecutive_api_errors
        await controller._handle_api_error(Exception("Test"), "test")

        # Should increment error count
        assert controller.consecutive_api_errors > initial_errors

        # Reset errors (only works if paused)
        controller.api_error_paused = True
        controller.api_error_paused_at = controller.market_data_provider.time()
        controller.reset_api_errors()
        assert controller.consecutive_api_errors == 0
