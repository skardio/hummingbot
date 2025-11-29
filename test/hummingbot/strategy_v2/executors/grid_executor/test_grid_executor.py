from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from test.logger_mixin_for_test import LoggerMixinForTest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TokenAmount
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
)
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop, TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder


class TestGridExecutor(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    def setUp(self) -> None:
        super().setUp()
        self.strategy = self.create_mock_strategy()
        self.update_interval = 0.5

    @staticmethod
    def create_mock_strategy():
        market = MagicMock()
        market_info = MagicMock()
        market_info.market = market

        strategy = MagicMock(spec=ScriptStrategyBase)
        type(strategy).market_info = PropertyMock(return_value=market_info)
        type(strategy).trading_pair = PropertyMock(return_value="ETH-USDT")
        n_orders = 20
        strategy.buy.side_effect = [f"OID-BUY-{i}" for i in range(1, n_orders + 1)]
        strategy.sell.side_effect = [f"OID-SELL-{i}" for i in range(1, n_orders + 1)]
        type(strategy).current_timestamp = PropertyMock(return_value=1234567890)
        strategy.cancel.return_value = None
        connector = MagicMock(spec=ExchangePyBase)
        type(connector).trading_rules = PropertyMock(return_value={"ETH-USDT": TradingRule(trading_pair="ETH-USDT",
                                                                                           min_order_value=Decimal("5"),
                                                                                           min_price_increment=Decimal(
                                                                                               "0.1"))})
        strategy.connectors = {
            "binance": connector,
            "binance_perpetual": connector,
        }
        return strategy

    def get_grid_executor_from_config(self, config: GridExecutorConfig):
        executor = GridExecutor(self.strategy, config, self.update_interval)
        self.set_loggers(loggers=[executor.logger()])
        return executor

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("110")))
    async def test_control_task_grid_open_orders(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("9"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        await executor.control_task()
        # Verify grid levels were created and first orders placed
        self.assertEqual(len(executor.grid_levels), 10)  # Based on config parameters
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]), 2)
        # Verify order properties
        first_level = executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED][0]
        self.assertEqual(first_level.active_open_order.order_id, "OID-BUY-1")
        self.assertAlmostEqual(first_level.amount_quote, Decimal("10"))

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("110")))
    async def test_control_task_grid_open_orders_perps(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance_perpetual",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("9"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        await executor.control_task()
        # Verify grid levels were created and first orders placed
        self.assertEqual(len(executor.grid_levels), 10)

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("100")))
    async def test_control_task_grid_close_orders(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.SELL,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("80"),
            end_price=Decimal("100"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("9"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("110"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-SELL-1")
        order = InFlightOrder(
            client_order_id="OID-SELL-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.SELL,
            amount=Decimal("10"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        order.executed_amount_base = Decimal("10")
        order.executed_amount_quote = Decimal("1000")
        executor.grid_levels[0].active_open_order.order = order
        await executor.control_task()
        # Verify grid levels were created and first orders placed
        self.assertEqual(len(executor.grid_levels), 10)  # Based on config parameters
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]), 1)

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("100")))
    async def test_control_task_grid_close_orders_perps(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance_perpetual",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("9"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("10"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        order.executed_amount_base = Decimal("10")
        order.executed_amount_quote = Decimal("1000")
        executor.grid_levels[0].active_open_order.order = order
        await executor.control_task()
        # Verify grid levels were created and first orders placed
        self.assertEqual(len(executor.grid_levels), 10)

    @patch.object(GridExecutor, "get_price")
    async def test_grid_activation_bounds_open_orders(self, get_price_mock):
        get_price_mock.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("9"),
            activation_bounds=Decimal("0.05"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        # Test when price is outside activation bounds
        get_price_mock.return_value = Decimal("100")
        await executor.control_task()
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]), 10)
        for level in executor.grid_levels:
            level.reset_level()
        # Test when price is within activation bounds
        get_price_mock.return_value = Decimal("120")
        await executor.control_task()
        executor.update_grid_levels()
        self.assertTrue(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]) < 5)

    @patch.object(GridExecutor, "get_price")
    async def test_grid_activation_bounds_close_orders(self, get_price_mock):
        get_price_mock.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.SELL,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("80"),
            end_price=Decimal("100"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("8"),
            activation_bounds=Decimal("0.05"),
            limit_price=Decimal("110"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-SELL-1")
        order = InFlightOrder(
            client_order_id="OID-SELL-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.SELL,
            amount=Decimal("10"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        order.executed_amount_base = Decimal("10")
        order.executed_amount_quote = Decimal("1000")
        executor.grid_levels[0].active_open_order.order = order
        # Test when price is outside activation bounds
        get_price_mock.return_value = Decimal("100")
        await executor.control_task()
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]), 0)
        # Test when price is within activation bounds
        executor.grid_levels[9].active_open_order = TrackedOrder("OID-SELL-10")
        order = InFlightOrder(
            client_order_id="OID-SELL-10",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.SELL,
            amount=Decimal("10"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        order.executed_amount_base = Decimal("10")
        order.executed_amount_quote = Decimal("1000")
        executor.grid_levels[9].active_open_order.order = order
        get_price_mock.return_value = Decimal("100")
        await executor.control_task()
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]), 1)

    @patch.object(GridExecutor, "get_price")
    async def test_grid_take_profit_condition(self, get_price_mock):
        get_price_mock.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        # Test when price is below end price
        executor.update_metrics()
        self.assertFalse(executor.take_profit_condition())
        # Test when price moves above end price
        get_price_mock.return_value = Decimal("125")
        executor.update_metrics()
        self.assertTrue(executor.take_profit_condition())

    @patch.object(GridExecutor, "get_price")
    def test_grid_metrics_update(self, get_price_mock):
        get_price_mock.return_value = Decimal("125")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        # Create three filled orders with different trade types and amounts
        buy_order_1 = InFlightOrder(
            client_order_id="buy_1",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("1.0"),
            price=Decimal("100"),
            creation_timestamp=1640001112.0,
            initial_state=OrderState.FILLED,
        )
        buy_order_1.executed_amount_base = Decimal("1.0")
        buy_order_1.executed_amount_quote = Decimal("100.0")
        buy_order_2 = InFlightOrder(
            client_order_id="buy_2",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("2.0"),
            price=Decimal("105"),
            creation_timestamp=1640001112.0,
            initial_state=OrderState.FILLED,
        )
        buy_order_2.executed_amount_base = Decimal("2.0")
        buy_order_2.executed_amount_quote = Decimal("210.0")
        sell_order = InFlightOrder(
            client_order_id="sell_1",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.SELL,
            amount=Decimal("1.5"),
            price=Decimal("110"),
            creation_timestamp=1640001112.0,
            initial_state=OrderState.FILLED,
        )
        sell_order.executed_amount_base = Decimal("1.5")
        sell_order.executed_amount_quote = Decimal("165.0")
        # Add the orders to filled_orders
        executor._filled_orders = [
            buy_order_1.to_json(),
            buy_order_2.to_json(),
            sell_order.to_json(),
        ]
        executor.update_realized_pnl_metrics()
        # Verify metrics
        self.assertEqual(executor.realized_buy_size_quote, Decimal("310"))  # 100 + 210
        self.assertEqual(executor.realized_sell_size_quote, Decimal("165"))  # 165
        self.assertEqual(executor.realized_imbalance_quote, Decimal("145"))  # 310 - 165
        self.assertEqual(executor.realized_pnl_quote, Decimal("-145"))  # 165 - 310
        self.assertAlmostEqual(round(executor.realized_pnl_pct, 4), round(Decimal("-0.4677419355"), 4))  # -145 / 310

    @patch.object(GridExecutor, "get_price")
    def test_generate_grid_levels_logs_base_amount_using_market_price(self, get_price_mock):
        get_price_mock.return_value = Decimal("110")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.mid_price = Decimal("110")
        logger_mock = MagicMock()
        with patch.object(executor, "logger", return_value=logger_mock):
            grid_levels = executor._generate_grid_levels()

        quote_amount = grid_levels[0].amount_quote
        expected_base = quote_amount / Decimal("110")
        log_messages = [call.args[0] for call in logger_mock.info.call_args_list if isinstance(call.args[0], str)]
        self.assertTrue(log_messages, "Expected at least one info log message")
        self.assertIn(f"(base amount: {expected_base:.8f}", log_messages[-1])

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("100")))
    async def test_close_order_waits_for_locked_balance_release(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.SHUTTING_DOWN
        executor.close_type = CloseType.EARLY_STOP
        executor.levels_by_state = {state: [] for state in GridLevelStates}
        executor.position_size_base = Decimal("10")
        executor.mid_price = Decimal("100")
        executor.current_close_quote = Decimal("100")
        executor.trading_rules.min_order_size = Decimal("1")

        connector = self.strategy.connectors["binance"]
        connector.get_available_balance = MagicMock(
            side_effect=[
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("10"),
                Decimal("10"),
            ]
        )
        connector.get_balance = MagicMock(return_value=Decimal("10"))

        with patch.object(GridExecutor, "update_metrics", MagicMock()), \
                patch.object(GridExecutor, "_sleep", new=AsyncMock()) as sleep_mock, \
                patch.object(GridExecutor, "_refresh_connector_balances", new=AsyncMock()) as refresh_mock, \
                patch.object(GridExecutor, "place_order", return_value="CLOSE-OID") as place_order_mock:
            await executor.control_close_order()

        self.assertTrue(refresh_mock.awaited)
        sleep_mock.assert_awaited()
        place_order_mock.assert_called_once()
        self.assertEqual(place_order_mock.call_args.kwargs["amount"], Decimal("10"))

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("100")))
    async def test_close_order_caps_amount_by_available_balance(self):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("90"),
            end_price=Decimal("110"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("80"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
            ),
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.SHUTTING_DOWN
        executor.close_type = CloseType.EARLY_STOP
        executor.levels_by_state = {state: [] for state in GridLevelStates}
        executor.position_size_base = Decimal("10")
        executor.mid_price = Decimal("100")
        executor.current_close_quote = Decimal("100")
        executor.trading_rules.min_order_size = Decimal("1")

        connector = self.strategy.connectors["binance"]
        connector.get_available_balance = MagicMock(return_value=Decimal("6"))
        connector.get_balance = MagicMock(return_value=Decimal("12"))

        with patch.object(GridExecutor, "update_metrics", MagicMock()), \
                patch.object(GridExecutor, "_sleep", new=AsyncMock()) as sleep_mock, \
                patch.object(GridExecutor, "_refresh_connector_balances", new=AsyncMock()) as refresh_mock, \
                patch.object(GridExecutor, "place_order", return_value="CLOSE-OID") as place_order_mock:
            await executor.control_close_order()

        refresh_mock.assert_awaited()
        sleep_mock.assert_not_awaited()
        place_order_mock.assert_called_once()
        self.assertEqual(place_order_mock.call_args.kwargs["amount"], Decimal("6"))

    @patch.object(GridExecutor, "_sleep")
    @patch.object(GridExecutor, "get_price")
    async def test_control_shutdown_process(self, get_price_mock, _):
        get_price_mock.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.SHUTTING_DOWN
        # Add some active orders
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.OPEN
        )
        await executor.control_task()
        self.strategy.cancel.assert_called_with(
            connector_name="binance",
            trading_pair="ETH-USDT",
            order_id="OID-BUY-1"
        )
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        await executor.control_task()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]), 1)
        self.assertIsInstance(executor._close_order, TrackedOrder)
        executor._close_order.order = InFlightOrder(
            client_order_id="OID-SELL-1",
            exchange_order_id="EOID5",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.SELL,
            amount=Decimal("0.1"),
            price=Decimal("101"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        executor._close_order.order.executed_amount_base = Decimal("0.1")
        await executor.control_task()
        self.assertEqual(executor.status, RunnableStatus.TERMINATED)

    @patch.object(GridExecutor, "get_in_flight_order")
    @patch.object(GridExecutor, "get_price", return_value=Decimal("100"))
    def test_process_order_created_event(self, _, get_in_flight_order_mock):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        event = BuyOrderCreatedEvent(
            timestamp=1234567890,
            order_id="OID-BUY-1",
            trading_pair="ETH-USDT",
            amount=Decimal("0.1"),
            type=OrderType.LIMIT,
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            exchange_order_id="EOID4"
        )
        get_in_flight_order_mock.return_value = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.OPEN
        )
        executor.process_order_created_event(None, None, event)
        self.assertEqual(executor.grid_levels[0].active_open_order.order_id, "OID-BUY-1")

    @patch.object(GridExecutor, "get_in_flight_order")
    @patch.object(GridExecutor, "get_price", return_value=Decimal("100"))
    def test_process_order_filled_event(self, _, get_in_flight_order_mock):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
        )
        in_flight_updated = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.PARTIALLY_FILLED
        )
        in_flight_updated.executed_amount_base = Decimal("0.1")
        get_in_flight_order_mock.return_value = in_flight_updated
        event = OrderFilledEvent(
            timestamp=1234567890,
            order_id="OID-BUY-1",
            trading_pair="ETH-USDT",
            trade_type=TradeType.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100"),
            amount=Decimal("0.1"),
            trade_fee=AddedToCostTradeFee(flat_fees=[TokenAmount(token="USDT", amount=Decimal("0.1"))]),
            exchange_trade_id="123",
            leverage=1,
            position=PositionAction.NIL.value,
        )
        executor.process_order_filled_event(None, None, event)
        self.assertEqual(executor.grid_levels[0].active_open_order.executed_amount_base, Decimal("0.1"))

    @patch.object(GridExecutor, "get_in_flight_order")
    @patch.object(GridExecutor, "get_price", return_value=Decimal("100"))
    def test_process_order_completed_event(self, _, get_in_flight_order_mock):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        get_in_flight_order_mock.return_value = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        event = BuyOrderCompletedEvent(
            timestamp=1234567890,
            order_id="OID-BUY-1",
            base_asset="ETH",
            quote_asset="USDT",
            base_asset_amount=Decimal("0.1"),
            quote_asset_amount=Decimal("10"),
            order_type=OrderType.LIMIT,
            exchange_order_id="EOID4"
        )
        executor.process_order_completed_event(None, None, event)
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]), 1)

    @patch.object(GridExecutor, "get_price", return_value=Decimal("100"))
    def test_process_order_canceled_event(self, _):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        event = OrderCancelledEvent(
            timestamp=1234567890,
            order_id="OID-BUY-1",
            exchange_order_id="EOID4"
        )
        executor.process_order_canceled_event(None, None, event)
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]), 0)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        executor.grid_levels[0].active_close_order = TrackedOrder("OID-SELL-1")
        event = OrderCancelledEvent(
            timestamp=1234567890,
            order_id="OID-SELL-1",
            exchange_order_id="EOID4"
        )
        executor.process_order_canceled_event(None, None, event)
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]), 0)

    @patch.object(GridExecutor, "get_price", return_value=Decimal("100"))
    def test_process_order_failed_event(self, _):
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        event = MarketOrderFailureEvent(
            timestamp=1234567890,
            order_id="OID-BUY-1",
            order_type=OrderType.LIMIT
        )
        executor.process_order_failed_event(None, None, event)
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]), 0)
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        executor.grid_levels[0].active_close_order = TrackedOrder("OID-SELL-1")
        event = MarketOrderFailureEvent(
            timestamp=1234567890,
            order_id="OID-SELL-1",
            order_type=OrderType.LIMIT
        )
        executor.process_order_failed_event(None, None, event)
        executor.update_grid_levels()
        self.assertEqual(len(executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]), 0)

    @patch.object(GridExecutor, 'adjust_order_candidates')
    @patch.object(GridExecutor, "get_price")
    async def test_validate_sufficient_balance_spot(self, mock_price, mock_adjust_order_candidates):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        # Test with sufficient balance
        mock_adjust_order_candidates.side_effect = [
            [OrderCandidate(
                trading_pair="ETH-USDT",
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.BUY,
                amount=Decimal("1"),
                price=Decimal("100")
            )],
            [OrderCandidate(
                trading_pair="ETH-USDT",
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.BUY,
                amount=Decimal("0"),
                price=Decimal("100")
            )]]
        await executor.validate_sufficient_balance()
        self.assertEqual(executor.close_type, None)
        # Test with insufficient balance
        await executor.validate_sufficient_balance()
        self.assertEqual(executor.close_type, CloseType.INSUFFICIENT_BALANCE)

    @patch.object(GridExecutor, 'adjust_order_candidates')
    @patch.object(GridExecutor, "get_price")
    async def test_validate_sufficient_balance_perpetual(self, mock_price, mock_adjust_order_candidates):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.SELL,
            connector_name="binance_perpetual",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("85"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        # Test with sufficient balance
        mock_adjust_order_candidates.side_effect = [
            [OrderCandidate(
                trading_pair="ETH-USDT",
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.SELL,
                amount=Decimal("100"),
                price=Decimal("100")
            )],
            [OrderCandidate(
                trading_pair="ETH-USDT",
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.SELL,
                amount=Decimal("0"),
                price=Decimal("100")
            )]]
        await executor.validate_sufficient_balance()
        self.assertEqual(executor.close_type, None)
        # Test with insufficient balance
        await executor.validate_sufficient_balance()
        self.assertEqual(executor.close_type, CloseType.INSUFFICIENT_BALANCE)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_with_position_expired(self, mock_price):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=1,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        await executor.on_start()
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.TIME_LIMIT)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_with_position_below_limit_price(self, mock_price):
        mock_price.return_value = Decimal("80")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=1,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        await executor.on_start()
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.STOP_LOSS)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_with_position_above_end_price(self, mock_price):
        """Test that executor shuts down when price > end_price and there IS a position"""
        mock_price.return_value = Decimal("125")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.mid_price = Decimal("125")
        # Simulate that there IS a position (filled orders exist)
        # Create a filled buy order to simulate a position
        buy_order = InFlightOrder(
            client_order_id="test_buy_1",
            trading_pair="ETH-USDT",
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("110"),
            creation_timestamp=1640001112.0,
            initial_state=OrderState.FILLED,
        )
        buy_order.executed_amount_base = Decimal("0.1")
        buy_order.executed_amount_quote = Decimal("11.0")
        executor._filled_orders = [buy_order.to_json()]
        executor.position_amount = Decimal("0.1")  # Has position
        await executor.on_start()
        # Should shutdown because there IS a position and price > end_price
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.TAKE_PROFIT)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_buy_order_take_profit_price_above_end_shuts_down(self, mock_price):
        """BUY grid should shut down when TAKE_PROFIT triggers even if no position yet"""
        mock_price.return_value = Decimal("125")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,  # Recent timestamp (not expired)
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,  # Long time limit
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.mid_price = Decimal("125")  # Above end_price
        # No position yet (no filled orders)
        await executor.on_start()
        # Should shut down to respect triple-barrier condition even without a position
        self.assertEqual(executor.close_type, CloseType.TAKE_PROFIT)
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_sell_order_take_profit_price_below_end_shuts_down(self, mock_price):
        """SELL grid should shut down when TAKE_PROFIT triggers even if no position yet

        For SELL grids: start_price > end_price (sell high, buy back low)
        Take profit triggers when price < end_price (reaches buy-back target)
        """
        mock_price.return_value = Decimal("75")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,  # Recent timestamp (not expired)
            side=TradeType.SELL,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),  # High price (where selling begins)
            end_price=Decimal("80"),     # Low price (buy-back target) - for SELL grid, end_price < start_price
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("130"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,  # Long time limit
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.mid_price = Decimal("75")  # Below end_price (for SELL grid) - triggers take profit
        # No position yet (no filled orders)
        await executor.on_start()
        # Should shut down to respect triple-barrier condition even without a position
        self.assertEqual(executor.close_type, CloseType.TAKE_PROFIT)
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)

    @patch.object(GridExecutor, "get_price")
    async def test_on_start_stop_loss_shuts_down(self, mock_price):
        """Test that STOP_LOSS close type shuts down executor"""
        mock_price.return_value = Decimal("80")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,  # Recent timestamp (not expired)
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,  # Long time limit
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.mid_price = Decimal("80")
        # Simulate position with negative PnL (stop loss condition)
        executor.position_pnl_pct = Decimal("-0.06")  # Below stop loss threshold
        await executor.on_start()
        # Should shutdown because stop loss is triggered
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.STOP_LOSS)

    @patch.object(GridExecutor, "get_price")
    async def test_early_stop(self, mock_price):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING
        executor.early_stop()
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.EARLY_STOP)

    @patch.object(GridExecutor, "get_price")
    async def test_get_custom_info(self, mock_price):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor_info = executor.executor_info
        custom_info = executor_info.custom_info
        self.assertEqual(custom_info["levels_by_state"],
                         {key.name: value for key, value in executor.levels_by_state.items()})
        self.assertEqual(custom_info["filled_orders"], executor._filled_orders)
        self.assertEqual(custom_info["failed_orders"], executor._failed_orders)
        self.assertEqual(custom_info["canceled_orders"], executor._canceled_orders)
        self.assertEqual(custom_info["realized_buy_size_quote"], executor.realized_buy_size_quote)
        self.assertEqual(custom_info["realized_sell_size_quote"], executor.realized_sell_size_quote)
        self.assertEqual(custom_info["realized_imbalance_quote"], executor.realized_imbalance_quote)
        self.assertEqual(custom_info["realized_fees_quote"], executor.realized_fees_quote)
        self.assertEqual(custom_info["realized_pnl_quote"], executor.realized_pnl_quote)
        self.assertEqual(custom_info["realized_pnl_pct"], executor.realized_pnl_pct)
        self.assertEqual(custom_info["position_size_quote"], executor.position_size_quote)
        self.assertEqual(custom_info["position_fees_quote"], executor.position_fees_quote)
        self.assertEqual(custom_info["position_pnl_quote"], executor.position_pnl_quote)
        self.assertEqual(custom_info["open_liquidity_placed"], executor.open_liquidity_placed)
        self.assertEqual(custom_info["close_liquidity_placed"], executor.close_liquidity_placed)

    def test_creating_grid_with_unsupported_stop_loss_order(self, ):
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                stop_loss_order_type=OrderType.LIMIT,
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        with self.assertRaises(ValueError):
            self.get_grid_executor_from_config(config)

    @patch.object(GridExecutor, "get_price")
    async def test_evaluate_max_retries(self, mock_price):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            order_frequency=1.0,
            max_open_orders=5,
            max_orders_per_batch=2,
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05"),
                time_limit=100,
                trailing_stop=TrailingStop(
                    activation_price=Decimal("0.05"),
                    trailing_delta=Decimal("0.005")
                )
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor._current_retries = 11
        await executor.control_task()
        self.assertEqual(executor._status, RunnableStatus.TERMINATED)

    @patch.object(GridExecutor, "_sleep")
    @patch.object(GridExecutor, "get_price")
    async def test_control_shutdown_process_position_hold(self, mock_price, _):
        mock_price.return_value = Decimal("100")
        config = GridExecutorConfig(
            id="test",
            timestamp=123,
            side=TradeType.BUY,
            connector_name="binance",
            trading_pair="ETH-USDT",
            start_price=Decimal("100"),
            end_price=Decimal("120"),
            total_amount_quote=Decimal("100"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("90"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )
        executor = self.get_grid_executor_from_config(config)
        executor.open_liquidity_placed = Decimal("0")
        executor.close_liquidity_placed = Decimal("0")
        executor._status = RunnableStatus.SHUTTING_DOWN
        executor.close_type = CloseType.POSITION_HOLD
        # Add some active orders
        executor.grid_levels[0].active_open_order = TrackedOrder("OID-BUY-1")
        executor.grid_levels[0].active_open_order.order = InFlightOrder(
            client_order_id="OID-BUY-1",
            exchange_order_id="EOID4",
            trading_pair=config.trading_pair,
            order_type=OrderType.LIMIT,
            trade_type=TradeType.BUY,
            amount=Decimal("0.1"),
            price=Decimal("100"),
            creation_timestamp=1640001112.223,
            initial_state=OrderState.FILLED
        )
        await executor.control_task()
        self.assertEqual(executor._status, RunnableStatus.TERMINATED)
        self.assertEqual(executor.close_type, CloseType.POSITION_HOLD)
