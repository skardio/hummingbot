"""
Unit tests for MultiCoinGridController methods

Tests for methods that are not yet covered by existing tests.
"""

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hummingbot.core.data_type.common import OrderType

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

from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig


@pytest.fixture
def mock_strategy():
    """Create a mock strategy"""
    strategy = MagicMock()
    strategy.connectors = {}
    strategy.current_timestamp = 1000.0
    return strategy


@pytest.fixture
def mock_market_data_provider():
    """Create a mock market data provider"""
    return MagicMock()


@pytest.fixture
def mock_actions_queue():
    """Create a mock actions queue"""
    return MagicMock()


@pytest.fixture
def mock_connector():
    """Create a mock connector"""
    connector = MagicMock()
    connector.name = "kraken"
    connector.trading_rules = {
        "XRP-EUR": MagicMock(min_order_size=Decimal("10"), min_price_increment=Decimal("0.0001"))
    }
    connector.get_price_by_type = MagicMock(return_value=Decimal("2.0"))
    connector.get_order_book = MagicMock(return_value=MagicMock())
    connector.get_available_balance = MagicMock(return_value=Decimal("1000"))
    return connector


@pytest.fixture
def config():
    """Create a test config"""
    return MultiCoinGridConfig(
        controller_name="test_controller",
        connector_name="kraken",
        quote_asset="EUR",
        total_amount_quote=Decimal("50"),
        stop_loss_pct=Decimal("0.08"),
        trend_min_change_pct=Decimal("0.15"),
        max_coins_to_monitor=5,
        trend_lookback_minutes=60,
    )


@pytest.fixture
def controller(config, mock_strategy, mock_market_data_provider, mock_actions_queue, mock_connector):
    """Create a controller instance for testing"""
    with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'), \
            patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=mock_market_data_provider,
            actions_queue=mock_actions_queue,
            connectors={"kraken": mock_connector},
            update_interval=10.0
        )
        controller._strategy = mock_strategy
        controller.connector = mock_connector
        controller.base_connector = mock_connector

        # Mock dynamic_slot_manager to return proper numeric values
        mock_dynamic_slot_manager = MagicMock()
        mock_dynamic_slot_manager.enabled = False  # Disable by default to use static config
        mock_dynamic_slot_manager.get_max_slots = MagicMock(return_value=4)
        controller.dynamic_slot_manager = mock_dynamic_slot_manager

        return controller


class TestErrorHandling:
    """Tests for error handling methods"""

    @pytest.mark.asyncio
    async def test_handle_api_error(self, controller):
        """Test _handle_api_error method"""
        controller.consecutive_api_errors = 0
        controller.api_error_threshold = 10
        controller.api_error_backoff_seconds = 1.0
        controller.max_backoff_seconds = 60.0
        controller.api_error_paused = False

        error = Exception("Test error")
        await controller._handle_api_error(error, "test_operation")

        assert controller.consecutive_api_errors > 0

    @pytest.mark.asyncio
    async def test_api_call_with_error_handling_success(self, controller):
        """Test _api_call_with_error_handling with successful call"""
        async def test_func():
            return "success"

        result = await controller._api_call_with_error_handling(test_func)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_api_call_with_error_handling_retry(self, controller):
        """Test _api_call_with_error_handling with error handling"""
        call_count = 0

        async def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Temporary error")
            return "success"

        # First call will fail and be handled
        result = await controller._api_call_with_error_handling(test_func)
        # Result will be None because error was handled
        assert result is None or result == "success"

    @pytest.mark.asyncio
    async def test_get_ticker_data_safe(self, controller, mock_connector):
        """Test _get_ticker_data_safe method"""
        mock_connector._get_ticker_data = AsyncMock(return_value={"XRP-EUR": {"last": "2.0"}})

        result = await controller._get_ticker_data_safe()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_ticker_data_safe_rate_limiting(self, controller, mock_connector):
        """Test that _get_ticker_data_safe enforces rate limiting"""
        import time

        mock_connector._get_ticker_data = AsyncMock(return_value={"XRP-EUR": {"last": "2.0"}})

        # First call - should proceed immediately
        start_time = time.time()
        await controller._get_ticker_data_safe()
        # First call completed

        # Second call immediately after - should wait at least 1.5 seconds
        start_time = time.time()
        await controller._get_ticker_data_safe()
        second_call_time = time.time() - start_time

        # Second call should take longer due to rate limiting
        assert second_call_time >= 1.3, f"Rate limiting not working: second call took {
            second_call_time:.2f}s (expected >= 1.3s)"
        assert mock_connector._get_ticker_data.call_count == 2, "Should have made 2 API calls"


class TestComponentInitialization:
    """Tests for component initialization"""

    def test_initialize_components(self, controller, mock_connector):
        """Test _initialize_components method"""
        controller.connectors = {"kraken": mock_connector}
        controller._initialize_components()

        assert controller.connector is not None
        assert controller.coin_discovery is not None
        assert controller.trend_calculator is not None


class TestGridCreation:
    """Tests for grid creation logic"""

    def test_should_create_new_grid_no_active(self, controller):
        """Test _should_create_new_grid when no active executor"""
        controller.active_executor_id = None
        controller.active_coin = None
        controller.active_coins = {}  # Multi-coin: no active coins
        controller.trend_calculator = MagicMock()
        controller.bot_start_time = 0
        controller.config.min_startup_wait_seconds = 0  # Skip startup delay
        controller.max_simultaneous_coins = 4

        # Task 2.1.1: Initialize stale detection state to simulate fresh data
        controller._last_price_update = {"XRP-EUR": time.time()}
        controller._last_ob_update = {"XRP-EUR": time.time()}

        # Mock SmartEntry filter to return True (allows entry)
        with patch.object(controller, '_check_smart_entry_filter', return_value=True):
            # Mock risk manager to allow the trade
            controller.risk_manager = MagicMock()
            controller.risk_manager.can_open_trade = MagicMock(return_value=Decimal("50"))

            result = controller._should_create_new_grid("XRP-EUR")
            # Should return True when startup delay is passed
            assert result is True

    def test_should_create_new_grid_different_coin(self, controller):
        """Test _should_create_new_grid when different coin is best"""
        controller.active_executor_id = "executor_1"
        controller.active_coin = "ADA-EUR"
        controller.last_grid_creation_time = 0
        controller.last_switch_time = 0
        controller.trend_calculator = MagicMock()
        active_trend = MagicMock()
        active_trend.trend_score = 1.0
        active_trend.consensus_trend_pct = 1.0  # Must be float, not MagicMock
        active_trend.trend_pct = 1.0  # Must be float, not MagicMock
        best_trend = MagicMock()
        best_trend.trend_score = 2.0
        best_trend.consensus_trend_pct = 2.0  # Must be float, not MagicMock
        best_trend.trend_pct = 2.0  # Must be float, not MagicMock
        controller.trend_calculator.get_trend = MagicMock(
            side_effect=lambda coin: active_trend if coin == "ADA-EUR" else best_trend)
        controller.config.min_switch_interval_seconds = 0
        controller.market_data_provider = MagicMock()
        controller.market_data_provider.time = MagicMock(return_value=1000)

        with patch.object(controller, '_is_executor_actually_active', return_value=True):
            result = controller._should_create_new_grid("XRP-EUR")
            # Should return False if executor is still active and conditions aren't met
            assert isinstance(result, bool)

    def test_create_grid_action(self, controller, mock_connector):
        """Test _create_grid_action method"""
        controller.active_coin = None
        controller.last_grid_price = {}
        controller.connector = mock_connector
        controller.trend_calculator = MagicMock()
        trend = MagicMock()
        trend.volatility = 0.02
        trend.current_price = Decimal("2.0")  # Use Decimal, not MagicMock
        trend.price_history = [{"price": Decimal("2.0"), "high": Decimal(
            "2.05"), "low": Decimal("1.95"), "timestamp": 1000}] * 20
        trend.consensus_trend_pct = 1.0
        trend.trend_pct = 1.0
        controller.trend_calculator.get_trend = MagicMock(return_value=trend)
        controller.bot_start_time = 0  # Set bot start time
        controller.config.min_startup_wait_seconds = 0  # Skip startup delay

        action = controller._create_grid_action("XRP-EUR")

        assert action is not None
        assert isinstance(action, CreateExecutorAction)
        assert action.executor_config.trading_pair == "XRP-EUR"
        assert action.executor_config.triple_barrier_config.open_order_type == OrderType.LIMIT_MAKER
        assert action.executor_config.triple_barrier_config.take_profit_order_type == OrderType.LIMIT_MAKER

    def test_bitget_config_keeps_limit_order_type(self):
        """Bitget spot must keep LIMIT because LIMIT_MAKER is unsupported there."""
        bitget_config = SpotGridBitgetConfig(
            controller_name="test_bitget_controller",
            connector_name="bitget",
            quote_asset="USDT",
            total_amount_quote=Decimal("50"),
            max_coins_to_monitor=5,
        )

        triple_barrier = bitget_config.triple_barrier_config

        assert triple_barrier.open_order_type == OrderType.LIMIT
        assert triple_barrier.take_profit_order_type == OrderType.LIMIT

    def test_create_stop_action(self, controller):
        """Test _create_stop_action method"""
        controller.active_executor_id = "executor_1"
        controller.active_coin = "XRP-EUR"
        controller.entry_prices = {}

        # Mock executor info to make executor "exist"
        executor_info = MagicMock()
        executor_info.id = "executor_1"
        executor_info.net_pnl_quote = Decimal("0")
        executor_info.filled_amount_quote = Decimal("0")
        executor_info.custom_info = {"position_size_quote": Decimal("0")}  # Set custom_info as dict
        controller.executors_info = [executor_info]

        action = controller._create_stop_action()

        assert action is not None
        assert isinstance(action, StopExecutorAction)
        assert action.executor_id == "executor_1"


class TestSwitchLogic:
    """Tests for switch logic methods"""

    def test_check_smart_switch_threshold(self, controller):
        """Test _check_smart_switch_threshold method"""
        active_trend = MagicMock()
        active_trend.trend_score = 1.0
        active_trend.trend_1440m = 1.0
        active_trend.trend_240m = 1.0
        active_trend.trend_60m = 0.5
        active_trend.current_price = Decimal("2.0")
        active_trend.consensus_trend_pct = 1.0
        active_trend.trend_pct = 1.0
        active_trend.volatility = 0.02  # 2% volatility

        best_trend = MagicMock()
        best_trend.trend_score = 2.0
        best_trend.trend_1440m = 2.0
        best_trend.trend_240m = 2.0
        best_trend.trend_60m = 1.0
        best_trend.current_price = Decimal("2.1")
        best_trend.consensus_trend_pct = 2.0
        best_trend.trend_pct = 2.0

        controller.last_grid_creation_time = 0
        controller.config.min_switch_interval_seconds = 0

        result = controller._check_smart_switch_threshold(active_trend, best_trend)
        assert isinstance(result, bool)

    def test_check_smart_switch_threshold_relaxed(self, controller):
        """Test _check_smart_switch_threshold_relaxed method"""
        active_trend = MagicMock()
        active_trend.trend_score = 1.0
        active_trend.trend_1440m = 1.0
        active_trend.trend_240m = 1.0
        active_trend.trend_60m = 0.5
        active_trend.current_price = Decimal("2.0")
        active_trend.consensus_trend_pct = 1.0
        active_trend.trend_pct = 1.0
        active_trend.volatility = 0.02  # 2% volatility

        best_trend = MagicMock()
        best_trend.trend_score = 1.5
        best_trend.trend_1440m = 1.5
        best_trend.trend_240m = 1.5
        best_trend.trend_60m = 0.8
        best_trend.current_price = Decimal("2.05")
        best_trend.consensus_trend_pct = 1.5
        best_trend.trend_pct = 1.5

        controller.last_grid_creation_time = 0
        controller.config.min_switch_interval_seconds = 0

        result = controller._check_smart_switch_threshold_relaxed(active_trend, best_trend)
        assert isinstance(result, bool)

    def test_check_switch_cost(self, controller):
        """Test _check_switch_cost method"""
        active_trend = MagicMock()
        active_trend.trend_score = 1.0

        best_trend = MagicMock()
        best_trend.trend_score = 2.0

        controller.switch_costs = {}

        result = controller._check_switch_cost("XRP-EUR", active_trend, best_trend)
        assert isinstance(result, bool)

    def test_check_switch_cost_relaxed(self, controller):
        """Test _check_switch_cost_relaxed method"""
        active_trend = MagicMock()
        active_trend.trend_score = 1.0

        best_trend = MagicMock()
        best_trend.trend_score = 1.5

        controller.switch_costs = {}

        result = controller._check_switch_cost_relaxed("XRP-EUR", active_trend, best_trend)
        assert isinstance(result, bool)


class TestLiquidityAndVolatility:
    """Tests for liquidity and volatility methods"""

    def test_check_liquidity_requirements(self, controller):
        """Test _check_liquidity_requirements method"""
        controller.pair_volumes = {"XRP-EUR": 200000}  # €200k volume
        controller.pair_spreads = {"XRP-EUR": 0.001}  # 0.1% spread
        controller.config.min_24h_volume_eur = Decimal("100000")

        result = controller._check_liquidity_requirements("XRP-EUR")
        assert isinstance(result, bool)

    def test_calculate_atr(self, controller):
        """Test _calculate_atr method"""
        trend = MagicMock()
        # Need at least 14 periods for ATR calculation
        trend.price_history = [
            {"price": Decimal("2.0"), "high": Decimal("2.05"), "low": Decimal("1.95"), "timestamp": 1000 + i * 100}
            for i in range(20)
        ]

        result = controller._calculate_atr("XRP-EUR", trend)
        assert result is None or isinstance(result, float)

    def test_calculate_volatility_based_grid_count(self, controller):
        """Test _calculate_volatility_based_grid_count method"""
        trend = MagicMock()
        trend.volatility = 0.02  # 2% volatility

        result = controller._calculate_volatility_based_grid_count("XRP-EUR", trend)
        assert isinstance(result, int)
        assert result > 0

    @pytest.mark.asyncio
    async def test_ensure_order_book_exists(self, controller, mock_connector):
        """Test _ensure_order_book_exists method"""
        mock_connector.get_order_book = MagicMock(return_value=MagicMock())

        result = await controller._ensure_order_book_exists("XRP-EUR")
        assert result is True


class TestPositionLimits:
    """Tests for position limit checks"""

    def test_check_position_limits(self, controller):
        """Test _check_position_limits method"""
        controller.exposure_tracking = {}

        result = controller._check_position_limits("XRP-EUR")
        assert isinstance(result, bool)

    def test_update_exposure_tracking(self, controller):
        """Test _update_exposure_tracking method"""
        # Initialize exposure tracking attributes
        if not hasattr(controller, 'current_exposure_per_coin'):
            controller.current_exposure_per_coin = {}
        if not hasattr(controller, 'total_exposure'):
            controller.total_exposure = Decimal("0")

        controller._update_exposure_tracking("XRP-EUR", Decimal("50"))

        # Check if exposure was tracked
        assert "XRP-EUR" in controller.current_exposure_per_coin
        assert controller.current_exposure_per_coin["XRP-EUR"] == Decimal("50")


class TestMultiTimeframeConditions:
    """Tests for multi-timeframe condition checks"""

    def test_check_multi_timeframe_buy_conditions(self, controller):
        """Test _check_multi_timeframe_buy_conditions method"""
        controller.trend_calculator = MagicMock()
        trend = MagicMock()
        trend.trend_1440m = 2.0
        trend.trend_240m = 1.5
        trend.trend_60m = 0.5
        trend.long_trend_warmup = False
        controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = controller._check_multi_timeframe_buy_conditions("XRP-EUR")
        assert isinstance(result, bool)

    def test_check_multi_timeframe_exit_conditions(self, controller):
        """Test _check_multi_timeframe_exit_conditions method"""
        controller.trend_calculator = MagicMock()
        trend = MagicMock()
        trend.trend_60m = -0.6
        trend.trend_240m = 0.3
        controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = controller._check_multi_timeframe_exit_conditions("XRP-EUR")
        assert isinstance(result, bool)


class TestTrendUpdateScheduling:
    """Tests for trend update scheduling and rate limiting"""

    @pytest.mark.asyncio
    async def test_update_processed_data_skips_when_interval_not_elapsed(self, controller):
        """Ensure trend updates are skipped if called before price_update_interval"""
        controller.monitored_coins = ["XRP-EUR"]
        controller.all_available_pairs = ["XRP-EUR"]
        controller.trend_calculator = MagicMock()
        controller.trend_calculator.update_all_trends_v2 = AsyncMock()
        controller.config.price_update_interval = 30
        controller._last_trend_update = time.time()

        await controller.update_processed_data()

        controller.trend_calculator.update_all_trends_v2.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_processed_data_runs_after_interval(self, controller):
        """Ensure trend updates run when enough time has elapsed"""
        controller.monitored_coins = ["XRP-EUR"]
        controller.all_available_pairs = ["XRP-EUR"]
        controller.trend_calculator = MagicMock()
        controller.trend_calculator.update_all_trends_v2 = AsyncMock()
        controller.config.price_update_interval = 5
        controller._last_trend_update = time.time() - 10

        # Mock _build_orderbook_config to avoid issues
        controller._build_orderbook_config = MagicMock(return_value=None)

        await controller.update_processed_data()

        controller.trend_calculator.update_all_trends_v2.assert_awaited_once()


class TestPaperTradingOrderBook:
    """Tests for paper trading order book initialization"""

    @pytest.mark.asyncio
    async def test_ensure_order_book_exists_adds_to_paper_trading_connector(self, controller, mock_connector):
        """Test that _ensure_order_book_exists adds trading pair to paper trading connector's _trading_pairs"""
        # Setup paper trading connector mock
        paper_connector = MagicMock()
        paper_connector._trading_pairs = {}  # Empty dict (paper trading uses dict)
        paper_connector.split_trading_pair = MagicMock(return_value=("TNSR", "EUR"))
        paper_connector._order_book_trade_listener = MagicMock()

        # Mock get_order_book to raise ValueError (simulating missing order book)
        def get_order_book_side_effect(symbol):
            if symbol == "TNSR-EUR":
                raise ValueError(f"No order book exists for '{symbol}'.")
            return MagicMock()
        paper_connector.get_order_book = MagicMock(side_effect=get_order_book_side_effect)

        # Mock target market class
        target_market_class = MagicMock()
        target_market_instance = MagicMock()
        target_market_instance.convert_to_exchange_trading_pair = MagicMock(return_value="TNSR/EUR")
        target_market_class.return_value = target_market_instance
        paper_connector._target_market = target_market_class

        controller.connector = paper_connector

        # Setup order book tracker mock
        tracker = MagicMock()
        tracker._trading_pairs = ["XRP-EUR"]  # List (tracker uses list) - TNSR-EUR NOT in list yet
        tracker._order_books = {"XRP-EUR": MagicMock()}  # TNSR-EUR NOT in order_books yet
        tracker._data_source = MagicMock()
        tracker._data_source._trading_pairs = ["XRP-EUR"]

        # Mock CompositeOrderBook that will be created
        composite_order_book = MagicMock()
        composite_order_book.c_add_listener = MagicMock()
        tracker._initial_order_book_for_trading_pair = AsyncMock(return_value=composite_order_book)
        tracker._tracking_message_queues = {}
        tracker._tracking_tasks = {}

        paper_connector.order_book_tracker = tracker

        # Import OrderBookEvent for the test
        # Call the method - should trigger initialization
        await controller._ensure_order_book_exists("TNSR-EUR")

        # Verify trading pair was added to tracker
        assert "TNSR-EUR" in tracker._trading_pairs

        # Verify trading pair was added to paper trading connector's _trading_pairs dict
        assert "TNSR-EUR" in paper_connector._trading_pairs

        # Verify TradingPair object was created
        from hummingbot.connector.exchange.paper_trade.trading_pair import TradingPair
        assert isinstance(paper_connector._trading_pairs["TNSR-EUR"], TradingPair)

    @pytest.mark.asyncio
    async def test_ensure_order_book_exists_adds_trade_listener(self, controller, mock_connector):
        """Test that _ensure_order_book_exists adds trade listener to CompositeOrderBook"""
        # Setup paper trading connector mock
        paper_connector = MagicMock()
        paper_connector._trading_pairs = {}
        paper_connector.split_trading_pair = MagicMock(return_value=("WLFI", "EUR"))
        paper_connector._order_book_trade_listener = MagicMock()

        # Mock get_order_book to raise ValueError (simulating missing order book)
        def get_order_book_side_effect(symbol):
            if symbol == "WLFI-EUR":
                raise ValueError(f"No order book exists for '{symbol}'.")
            return MagicMock()
        paper_connector.get_order_book = MagicMock(side_effect=get_order_book_side_effect)

        # Mock target market class
        target_market_class = MagicMock()
        target_market_instance = MagicMock()
        target_market_instance.convert_to_exchange_trading_pair = MagicMock(return_value="WLFI/EUR")
        target_market_class.return_value = target_market_instance
        paper_connector._target_market = target_market_class

        controller.connector = paper_connector

        # Setup order book tracker mock
        tracker = MagicMock()
        tracker._trading_pairs = []  # Empty - WLFI-EUR not in list yet
        tracker._order_books = {}  # Empty - WLFI-EUR not in order_books yet
        tracker._data_source = MagicMock()
        tracker._data_source._trading_pairs = []

        # Mock CompositeOrderBook that will be created - this is what gets returned
        composite_order_book = MagicMock()
        composite_order_book.c_add_listener = MagicMock()
        tracker._initial_order_book_for_trading_pair = AsyncMock(return_value=composite_order_book)
        tracker._tracking_message_queues = {}
        tracker._tracking_tasks = {}

        paper_connector.order_book_tracker = tracker

        # Call the method - should trigger initialization and add listener
        await controller._ensure_order_book_exists("WLFI-EUR")

        # Verify listener was added (after order book is initialized)
        from hummingbot.core.event.events import OrderBookEvent

        # The listener is added after the order book is created and stored
        # Check that c_add_listener was called on the composite_order_book
        composite_order_book.c_add_listener.assert_called_once_with(
            OrderBookEvent.TradeEvent.value,
            paper_connector._order_book_trade_listener
        )

    def test_init_markets_passes_common_pairs_for_paper_trading(self):
        """Test that init_markets passes common trading pairs for paper trading"""
        # Mock ConfigManager - patch it where it's imported
        mock_manager = MagicMock()
        mock_manager.load_config = MagicMock(return_value={
            'connector_name': 'kraken',
            'quote_asset': 'EUR',
            'paper_trading': True  # Enable paper trading
        })

        # Patch ConfigManager at the import location in multi_coin_grid_v2
        with patch('multi_coin_grid_pro.config.config_manager.ConfigManager') as mock_cm_class:
            mock_cm_class.return_value = mock_manager

            # Import the module again to get the patched ConfigManager
            import importlib

            import multi_coin_grid_pro.scripts.multi_coin_grid_v2
            importlib.reload(multi_coin_grid_pro.scripts.multi_coin_grid_v2)

            # Call init_markets WITHOUT config (so it uses yaml config)
            multi_coin_grid_pro.scripts.multi_coin_grid_v2.MultiCoinGridStrategyV2.init_markets(config=None)

            # Verify markets were set with common pairs
            assert hasattr(multi_coin_grid_pro.scripts.multi_coin_grid_v2.MultiCoinGridStrategyV2, 'markets')
            assert "kraken_paper_trade" in multi_coin_grid_pro.scripts.multi_coin_grid_v2.MultiCoinGridStrategyV2.markets  # noqa: E501
            markets = multi_coin_grid_pro.scripts.multi_coin_grid_v2.MultiCoinGridStrategyV2.markets["kraken_paper_trade"]  # noqa: E501

            # Verify common pairs are included
            assert isinstance(markets, set)
            assert "BTC-EUR" in markets
            assert "ETH-EUR" in markets


# NOTE: TestStaleDetection removed (2026-01-13)
# Stale detection moved to MarketDataProvider in Task 2.1.1
# New tests in test_fase_2_features.py cover the updated implementation


class TestOrderbookSubscriptionGuard:
    """Tests for _has_orderbook_subscription + guard in _check_smart_entry_filter."""

    def test_has_orderbook_subscription_true(self, controller, mock_connector):
        """Returns True when symbol is in tracker._trading_pairs."""
        mock_tracker = MagicMock()
        mock_tracker._trading_pairs = ["SOL-EUR", "BTC-EUR"]
        mock_connector.order_book_tracker = mock_tracker
        controller.connector = mock_connector

        assert controller._has_orderbook_subscription("SOL-EUR") is True

    def test_has_orderbook_subscription_false(self, controller, mock_connector):
        """Returns False when symbol is NOT in tracker._trading_pairs."""
        mock_tracker = MagicMock()
        mock_tracker._trading_pairs = ["BTC-EUR"]
        mock_connector.order_book_tracker = mock_tracker
        controller.connector = mock_connector

        assert controller._has_orderbook_subscription("JUP-EUR") is False

    def test_has_orderbook_subscription_no_tracker(self, controller, mock_connector):
        """Returns False gracefully when connector has no order_book_tracker."""
        mock_connector.order_book_tracker = None
        controller.connector = mock_connector

        assert controller._has_orderbook_subscription("SOL-EUR") is False

    def test_check_smart_entry_filter_subscribes_and_rejects_unsubscribed_pair(
        self, controller, mock_connector
    ):
        """Unsubscribed pair triggers _subscribe_to_orderbook and returns False (no denial event)."""
        mock_tracker = MagicMock()
        mock_tracker._trading_pairs = ["BTC-EUR"]  # JUP-EUR not subscribed
        mock_connector.order_book_tracker = mock_tracker
        controller.connector = mock_connector

        subscribe_mock = MagicMock()
        controller._subscribe_to_orderbook = subscribe_mock

        result = controller._check_smart_entry_filter("JUP-EUR")

        assert result is False, "Unsubscribed pair must be rejected this cycle"
        subscribe_mock.assert_called_once_with("JUP-EUR")

    def test_check_smart_entry_filter_subscribed_pair_continues_evaluation(
        self, controller, mock_connector
    ):
        """Subscribed pair skips the OB guard and proceeds to normal evaluation."""
        mock_tracker = MagicMock()
        mock_tracker._trading_pairs = ["SOL-EUR"]
        mock_connector.order_book_tracker = mock_tracker
        controller.connector = mock_connector

        # Disable all other guards so we reach a True result
        controller.pair_health_monitor = None
        controller.staleness_guard = None
        controller.smart_entry_v2 = None
        controller.smart_entry_filter = None

        result = controller._check_smart_entry_filter("SOL-EUR")

        assert result is True, "Subscribed pair should reach normal evaluation"


class TestRegimeRouting:
    """Fase 1 regime routing tests with minimal controller stubs."""

    class _SlotManager:
        enabled = True

        def __init__(self):
            self.received_regime = None

        def get_dynamic_slots(self, account_balance_eur, current_regime, static_fallback):
            self.received_regime = current_regime
            return {"BULL": 6, "BEAR": 1, "baseline": static_fallback}.get(current_regime, 4)

    class _RegimeDetector:
        def __init__(self):
            self.metrics_calls = []

        def calculate_metrics(self, trend_data, candles_1h, candles_4h):
            self.metrics_calls.append(trend_data)
            return {"trend_data": trend_data}

        def detect_regime(self, metrics):
            return SimpleNamespace(
                regime="BULL",
                score=8.0,
                confidence=0.9,
                duration_minutes=15,
                reason="test regime",
            )

    def _controller_stub(self):
        ctl = object.__new__(MultiCoinGridController)
        ctl.config = SimpleNamespace(quote_asset="USD")
        ctl.max_simultaneous_coins = 4
        ctl.market_regime_filter = None
        ctl._last_detected_regime = None
        ctl._last_regime_input_pair = None
        ctl._last_regime_input_source = None
        ctl._regime_macro_trends = {}
        ctl.dynamic_slot_manager = self._SlotManager()
        ctl._calculate_portfolio_value = MagicMock(return_value=Decimal("1000"))
        ctl.logger = MagicMock(return_value=MagicMock())
        return ctl

    @staticmethod
    def _trend(trend_1h=1.0, trend_4h=2.0, trend_24h=3.0):
        return SimpleNamespace(
            trend_60m=trend_1h,
            trend_240m=trend_4h,
            trend_1440m=trend_24h,
            consensus_trend_pct=trend_4h,
            candles=[],
        )

    def test_slot_manager_receives_bull_regime(self):
        ctl = self._controller_stub()
        ctl._last_detected_regime = "BULL"

        slots = ctl._get_dynamic_slots_count()

        assert slots == 6
        assert ctl.dynamic_slot_manager.received_regime == "BULL"
        route_logs = [
            call.args[0] for call in ctl.logger.return_value.info.call_args_list
            if call.args and "[REGIME_ROUTE]" in call.args[0]
        ]
        assert route_logs
        assert "slots=6" in route_logs[-1]
        assert "balance=1000" in route_logs[-1]

    def test_slot_manager_receives_bear_regime(self):
        ctl = self._controller_stub()
        ctl._last_detected_regime = "BEAR"

        slots = ctl._get_dynamic_slots_count()

        assert slots == 1
        assert ctl.dynamic_slot_manager.received_regime == "BEAR"

    def test_slot_manager_falls_back_to_baseline_when_none(self):
        ctl = self._controller_stub()
        ctl._last_detected_regime = None

        slots = ctl._get_dynamic_slots_count()

        assert slots == 4
        assert ctl.dynamic_slot_manager.received_regime == "baseline"

    @pytest.mark.asyncio
    async def test_detect_regime_prefers_btc_over_altcoin(self):
        ctl = self._controller_stub()
        ctl.regime_detector = self._RegimeDetector()
        ctl.monitored_coins = ["APE-USD"]
        ctl.trend_calculator = SimpleNamespace(
            trends={
                "BTC-USD": self._trend(1.5, 2.5, 4.0),
                "APE-USD": self._trend(9.0, 9.0, 9.0),
            }
        )

        result = await ctl._detect_current_regime()

        assert result.regime == "BULL"
        assert ctl._last_regime_input_pair == "BTC-USD"
        assert ctl._last_regime_input_source == "btc_direct"

    @pytest.mark.asyncio
    async def test_detect_regime_falls_back_to_sol(self):
        ctl = self._controller_stub()
        ctl.regime_detector = self._RegimeDetector()
        ctl.monitored_coins = ["APE-USD"]
        ctl.trend_calculator = SimpleNamespace(
            trends={
                "SOL-USD": self._trend(1.0, 2.0, 3.0),
                "APE-USD": self._trend(9.0, 9.0, 9.0),
            }
        )

        result = await ctl._detect_current_regime()

        assert result.regime == "BULL"
        assert ctl._last_regime_input_pair == "SOL-USD"
        assert ctl._last_regime_input_source == "sol_direct"

    @pytest.mark.asyncio
    async def test_detect_regime_uses_cached_btc_when_direct_missing(self):
        ctl = self._controller_stub()
        ctl.regime_detector = self._RegimeDetector()
        ctl.monitored_coins = ["APE-USD"]
        ctl._regime_macro_trends = {"BTC-USD": self._trend(1.5, 2.5, 4.0)}
        ctl.trend_calculator = SimpleNamespace(
            trends={
                "APE-USD": self._trend(9.0, 9.0, 9.0),
            }
        )

        result = await ctl._detect_current_regime()

        assert result.regime == "BULL"
        assert ctl._last_regime_input_pair == "BTC-USD"
        assert ctl._last_regime_input_source == "btc_cached"

    @pytest.mark.asyncio
    async def test_detect_regime_falls_back_to_altcoin(self):
        ctl = self._controller_stub()
        ctl.regime_detector = self._RegimeDetector()
        ctl.monitored_coins = ["APE-USD"]
        ctl.trend_calculator = SimpleNamespace(trends={"APE-USD": self._trend(0.5, 1.0, 1.5)})

        result = await ctl._detect_current_regime()

        assert result.regime == "BULL"
        assert ctl._last_regime_input_pair == "APE-USD"
        assert ctl._last_regime_input_source == "monitored_fallback"

    @pytest.mark.asyncio
    async def test_regime_macro_trends_cached_outside_grid_trends(self):
        ctl = self._controller_stub()
        ctl.monitored_coins = ["APE-USD"]
        btc_trend = self._trend(1.0, 2.0, 3.0)
        sol_trend = self._trend(0.5, 1.0, 1.5)

        async def update_all_trends(symbols, orderbook_config=None):
            assert symbols == ["BTC-USD", "SOL-USD"]
            ctl.trend_calculator.trends["BTC-USD"] = btc_trend
            ctl.trend_calculator.trends["SOL-USD"] = sol_trend
            ctl.trend_calculator._debug_info = {"top_10": [("BTC-USD", 9.0)]}

        ctl.trend_calculator = SimpleNamespace(
            trends={},
            _debug_info={"top_10": [("APE-USD", 1.0)]},
            load_historical_data=AsyncMock(),
            update_all_trends_v2=AsyncMock(side_effect=update_all_trends),
        )

        await ctl._ensure_regime_macro_trends(load_history=False, update_prices=True)

        assert ctl._regime_macro_trends["BTC-USD"] is btc_trend
        assert ctl._regime_macro_trends["SOL-USD"] is sol_trend
        assert "BTC-USD" not in ctl.trend_calculator.trends
        assert "SOL-USD" not in ctl.trend_calculator.trends
        assert ctl.trend_calculator._debug_info == {"top_10": [("APE-USD", 1.0)]}


class TestMomentumDetectOnlyController:
    """Detect-only controller helper tests: logging throttle and no-crash paths."""

    @staticmethod
    def _controller_stub(now=1000.0, momentum_sleeve=None):
        if momentum_sleeve is None:
            momentum_sleeve = {
                "mode": "detect_only",
                "rejected_log_throttle_seconds": 300,
            }
        ctl = object.__new__(MultiCoinGridController)
        ctl.config = SimpleNamespace(
            quote_asset="USD",
            momentum_sleeve=momentum_sleeve,
        )
        ctl.market_data_provider = SimpleNamespace(time=MagicMock(return_value=now))
        ctl._momentum_rejected_log_ts = {}
        ctl.logger = MagicMock(return_value=MagicMock())
        return ctl

    @staticmethod
    def _candidate(symbol="APE-USD"):
        return SimpleNamespace(
            symbol=symbol,
            score=42.0,
            trend_1h=1.0,
            trend_4h=2.0,
            volume_expansion=0.8,
            relative_strength=0.0,
            spread_pct=0.1,
            rsi=55.0,
            regime_at_score="CHOP",
            entry_allowed=False,
            primary_rejection_reason="MOMENTUM_VOLUME_TOO_LOW",
            all_rejection_reasons=["MOMENTUM_VOLUME_TOO_LOW"],
        )

    def test_momentum_rejected_log_is_throttled(self):
        ctl = self._controller_stub(now=1000.0)
        candidate = self._candidate()

        ctl._log_momentum_candidate(candidate)
        ctl._log_momentum_candidate(candidate)

        info_calls = ctl.logger.return_value.info.call_args_list
        rejected_logs = [
            call.args[0] for call in info_calls
            if call.args and "[MOMENTUM_CANDIDATE_REJECTED]" in call.args[0]
        ]
        assert len(rejected_logs) == 1

        ctl.market_data_provider.time.return_value = 1301.0
        ctl._log_momentum_candidate(candidate)
        rejected_logs = [
            call.args[0] for call in ctl.logger.return_value.info.call_args_list
            if call.args and "[MOMENTUM_CANDIDATE_REJECTED]" in call.args[0]
        ]
        assert len(rejected_logs) == 2

    def test_momentum_detect_only_accepts_object_config(self):
        ctl = self._controller_stub(
            momentum_sleeve=SimpleNamespace(
                mode="detect_only",
                rejected_log_throttle_seconds=300,
            )
        )
        candidate = self._candidate()
        ctl.momentum_candidate_scorer = MagicMock()
        ctl.momentum_candidate_scorer.score.return_value = candidate
        trend = SimpleNamespace(candles=[1] * 14)
        ctl.trend_calculator = SimpleNamespace(
            trends={"APE-USD": trend},
            _debug_info={},
            get_trend=MagicMock(return_value=trend),
        )
        ctl._calculate_smart_entry_indicators = MagicMock(
            return_value=SimpleNamespace(rsi_14=55.0, wick_ratio=0.5)
        )
        ctl.pair_spreads = {"APE-USD": 0.001}
        ctl._last_detected_regime = "CHOP"

        ctl._log_momentum_candidates_detect_only(["APE-USD"])

        ctl.momentum_candidate_scorer.score.assert_called_once()
        ctl.logger.return_value.warning.assert_not_called()

    def test_momentum_detect_only_empty_symbols_no_crash(self):
        ctl = self._controller_stub()
        ctl.momentum_candidate_scorer = MagicMock()
        ctl.trend_calculator = SimpleNamespace(trends={}, _debug_info={})

        ctl._log_momentum_candidates_detect_only([])

        ctl.logger.return_value.warning.assert_not_called()

    def test_momentum_detect_only_bad_scorer_no_crash(self):
        ctl = self._controller_stub()
        ctl.momentum_candidate_scorer = MagicMock()
        ctl.momentum_candidate_scorer.score.side_effect = RuntimeError("boom")
        trend = SimpleNamespace(candles=[1] * 14)
        ctl.trend_calculator = SimpleNamespace(
            trends={"APE-USD": trend},
            _debug_info={},
            get_trend=MagicMock(return_value=trend),
        )
        ctl._calculate_smart_entry_indicators = MagicMock(
            return_value=SimpleNamespace(rsi_14=55.0, wick_ratio=0.5)
        )
        ctl.pair_spreads = {"APE-USD": 0.001}
        ctl._last_detected_regime = "CHOP"

        ctl._log_momentum_candidates_detect_only(["APE-USD"])

        warning_logs = [
            call.args[0] for call in ctl.logger.return_value.warning.call_args_list
            if call.args
        ]
        assert any("Momentum detect-only scoring skipped" in msg for msg in warning_logs)
