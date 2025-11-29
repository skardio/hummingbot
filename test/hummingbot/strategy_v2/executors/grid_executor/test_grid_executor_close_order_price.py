"""
Unit tests for GridExecutor close order price fix

Tests that early_stop() and place_close_order_and_cancel_open_orders()
always use valid prices (not NaN) for market orders when closing positions.
"""

from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from test.logger_mixin_for_test import LoggerMixinForTest
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType


class TestGridExecutorCloseOrderPrice(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """Test suite for GridExecutor close order price validation"""

    def setUp(self) -> None:
        super().setUp()
        self.strategy = self.create_mock_strategy()
        self.update_interval = 0.5

    @staticmethod
    def create_mock_strategy():
        """Create a mock strategy for testing"""
        market = MagicMock()
        market_info = MagicMock()
        market_info.market = market

        strategy = MagicMock(spec=ScriptStrategyBase)
        type(strategy).market_info = PropertyMock(return_value=market_info)
        type(strategy).trading_pair = PropertyMock(return_value="STRK-EUR")
        type(strategy).current_timestamp = PropertyMock(return_value=1234567890)
        strategy.cancel.return_value = None
        strategy.place_order.return_value = "TEST_ORDER_ID"

        connector = MagicMock(spec=ExchangePyBase)
        type(connector).trading_rules = PropertyMock(return_value={
            "STRK-EUR": TradingRule(
                trading_pair="STRK-EUR",
                min_order_value=Decimal("5"),
                min_order_size=Decimal("10"),
                min_price_increment=Decimal("0.0001")
            )
        })
        strategy.connectors = {"kraken": connector}
        return strategy

    def get_grid_executor_from_config(self, config: GridExecutorConfig):
        """Create GridExecutor from config"""
        executor = GridExecutor(self.strategy, config, self.update_interval)
        self.set_loggers(loggers=[executor.logger()])
        return executor

    @patch.object(GridExecutor, "get_price")
    @patch.object(GridExecutor, "update_metrics")
    def test_early_stop_with_valid_price(self, mock_update_metrics, mock_get_price):
        """Test that early_stop() uses valid price when closing position"""
        mock_get_price.return_value = Decimal("0.2185")

        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING

        # Set up position metrics to simulate open position
        executor.position_size_base = Decimal("245.06196")
        executor.position_size_quote = Decimal("53.50")
        executor.mid_price = Decimal("0.2185")
        executor.current_close_quote = Decimal("0.2185")

        # Call early_stop with keep_position=False
        executor.early_stop(keep_position=False)

        # Verify that place_order was called with valid price (not NaN)
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
        self.assertEqual(executor.close_type, CloseType.EARLY_STOP)

        # Verify place_order was called
        self.assertTrue(self.strategy.place_order.called)

        # Get the call arguments
        call_args = self.strategy.place_order.call_args
        self.assertIsNotNone(call_args)

        # Verify price is not NaN
        price_arg = call_args.kwargs.get('price')
        self.assertIsNotNone(price_arg)
        self.assertFalse(price_arg.is_nan(), f"Price should not be NaN, got {price_arg}")
        self.assertGreater(price_arg, Decimal("0"), f"Price should be positive, got {price_arg}")

        # Verify order type is MARKET
        self.assertEqual(call_args.kwargs.get('order_type'), OrderType.MARKET)

        # Verify side is SELL (closing BUY position)
        self.assertEqual(call_args.kwargs.get('side'), TradeType.SELL)

        # Verify position_action is CLOSE
        self.assertEqual(call_args.kwargs.get('position_action'), PositionAction.CLOSE)

    @patch.object(GridExecutor, "get_price")
    @patch.object(GridExecutor, "update_metrics")
    def test_early_stop_fallback_to_get_price(self, mock_update_metrics, mock_get_price):
        """Test that early_stop() falls back to get_price() if metrics don't have price"""
        mock_get_price.return_value = Decimal("0.2185")

        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING

        # Set up position but no price in metrics
        executor.position_size_base = Decimal("245.06196")
        executor.position_size_quote = Decimal("53.50")
        # Don't set mid_price or current_close_quote

        # Call early_stop
        executor.early_stop(keep_position=False)

        # Verify get_price was called as fallback
        self.assertTrue(mock_get_price.called)

        # Verify place_order was called with valid price
        call_args = self.strategy.place_order.call_args
        price_arg = call_args.kwargs.get('price')
        self.assertFalse(price_arg.is_nan(), f"Price should not be NaN, got {price_arg}")

    @patch.object(GridExecutor, "get_price")
    def test_place_close_order_with_nan_price_fallback(self, mock_get_price):
        """Test that place_close_order_and_cancel_open_orders() handles NaN price"""
        mock_get_price.return_value = Decimal("0.2185")

        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor.position_size_base = Decimal("245.06196")
        executor.position_size_quote = Decimal("53.50")

        # Call place_close_order with NaN price
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("NaN")
        )

        # Verify get_price was called to get valid price
        self.assertTrue(mock_get_price.called)

        # Verify place_order was called with valid price
        call_args = self.strategy.place_order.call_args
        price_arg = call_args.kwargs.get('price')
        self.assertFalse(price_arg.is_nan(), f"Price should not be NaN, got {price_arg}")
        self.assertGreater(price_arg, Decimal("0"), f"Price should be positive, got {price_arg}")

    @patch.object(GridExecutor, "get_price")
    def test_place_close_order_with_zero_price_fallback(self, mock_get_price):
        """Test that place_close_order_and_cancel_open_orders() handles zero price"""
        mock_get_price.return_value = Decimal("0.2185")

        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor.position_size_base = Decimal("245.06196")
        executor.position_size_quote = Decimal("53.50")

        # Call place_close_order with zero price
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("0")
        )

        # Verify get_price was called to get valid price
        self.assertTrue(mock_get_price.called)

        # Verify place_order was called with valid price
        call_args = self.strategy.place_order.call_args
        price_arg = call_args.kwargs.get('price')
        self.assertFalse(price_arg.is_nan(), f"Price should not be NaN, got {price_arg}")
        self.assertGreater(price_arg, Decimal("0"), f"Price should be positive, got {price_arg}")

    @patch.object(GridExecutor, "get_price")
    def test_place_close_order_with_valid_price_no_fallback(self, mock_get_price):
        """Test that place_close_order_and_cancel_open_orders() uses provided valid price"""
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor.position_size_base = Decimal("245.06196")
        executor.position_size_quote = Decimal("53.50")

        valid_price = Decimal("0.2185")

        # Call place_close_order with valid price
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=valid_price
        )

        # Verify get_price was NOT called (price was already valid)
        # Note: get_price might still be called by update_metrics, so we check the call args
        call_args = self.strategy.place_order.call_args
        price_arg = call_args.kwargs.get('price')

        # Verify the price used matches what we provided
        self.assertEqual(price_arg, valid_price)
        self.assertFalse(price_arg.is_nan())

    @patch.object(GridExecutor, "get_price")
    def test_early_stop_no_position_no_order(self, mock_get_price):
        """Test that early_stop() doesn't place order when position is too small"""
        config = GridExecutorConfig(
            id="test",
            timestamp=1234567890,
            side=TradeType.BUY,
            connector_name="kraken",
            trading_pair="STRK-EUR",
            start_price=Decimal("0.215"),
            end_price=Decimal("0.220"),
            total_amount_quote=Decimal("50"),
            min_spread_between_orders=Decimal("0.0001"),
            min_order_amount_quote=Decimal("10"),
            limit_price=Decimal("0.20"),
            triple_barrier_config=TripleBarrierConfig(
                take_profit=Decimal("0.001"),
                stop_loss=Decimal("0.05")
            )
        )

        executor = self.get_grid_executor_from_config(config)
        executor._status = RunnableStatus.RUNNING

        # Set position smaller than min_order_size
        executor.position_size_base = Decimal("5")  # Less than min_order_size (10)
        executor.position_size_quote = Decimal("1")

        # Call early_stop
        executor.early_stop(keep_position=False)

        # Verify place_order was NOT called (position too small)
        self.assertFalse(self.strategy.place_order.called)

        # But status should still be SHUTTING_DOWN
        self.assertEqual(executor._status, RunnableStatus.SHUTTING_DOWN)
