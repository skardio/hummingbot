import asyncio
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.markets_recorder import MarketsRecorder
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import TradeType
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.model.position import Position
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.arbitrage_executor.arbitrage_executor import ArbitrageExecutor
from hummingbot.strategy_v2.executors.arbitrage_executor.data_types import ArbitrageExecutorConfig
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.executors.dca_executor.data_types import DCAExecutorConfig
from hummingbot.strategy_v2.executors.dca_executor.dca_executor import DCAExecutor
from hummingbot.strategy_v2.executors.executor_orchestrator import ExecutorOrchestrator, PositionHold
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import PositionExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor
from hummingbot.strategy_v2.executors.twap_executor.data_types import TWAPExecutorConfig
from hummingbot.strategy_v2.executors.twap_executor.twap_executor import TWAPExecutor
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction, StoreExecutorAction
from hummingbot.strategy_v2.models.executors import CloseType
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, PerformanceReport


class TestExecutorOrchestrator(unittest.TestCase):

    @patch.object(MarketsRecorder, "get_instance")
    def setUp(self, markets_recorder: MagicMock):
        markets_recorder.return_value = MagicMock(spec=MarketsRecorder)
        markets_recorder.get_all_executors = MagicMock(return_value=[])
        markets_recorder.get_all_positions = MagicMock(return_value=[])
        markets_recorder.store_or_update_executor = MagicMock(return_value=None)
        markets_recorder.update_or_store_position = MagicMock(return_value=None)
        self.mock_strategy = self.create_mock_strategy()
        self.orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

    @staticmethod
    def create_mock_strategy():
        market = MagicMock()
        market_info = MagicMock()
        market_info.market = market

        strategy = MagicMock(spec=ScriptStrategyBase)
        type(strategy).market_info = PropertyMock(return_value=market_info)
        type(strategy).trading_pair = PropertyMock(return_value="ETH-USDT")
        connector = MagicMock(spec=ExchangePyBase)
        type(connector).trading_rules = PropertyMock(return_value={"ETH-USDT": TradingRule(trading_pair="ETH-USDT")})
        strategy.connectors = {
            "binance": connector,
        }
        strategy.market_data_provider = MagicMock(spec=MarketDataProvider)
        strategy.market_data_provider.get_price_by_type = MagicMock(return_value=Decimal(230))
        # Add the controllers attribute that ExecutorOrchestrator now checks for
        strategy.controllers = {}
        # Add the markets attribute that ExecutorOrchestrator now checks for
        strategy.markets = {"binance": {"ETH-USDT", "BTC-USDT"}}
        return strategy

    @patch.object(PositionExecutor, "start")
    @patch.object(DCAExecutor, "start")
    @patch.object(ArbitrageExecutor, "start")
    @patch.object(TWAPExecutor, "start")
    @patch.object(GridExecutor, "start")
    @patch.object(GridExecutor, "_generate_grid_levels")
    @patch.object(MarketsRecorder, "get_instance")
    def test_execute_actions_create_executor(self, markets_recorder_mock, grid_start_mock: MagicMock,
                                             generate_grid_levels_mock: MagicMock,
                                             arbitrage_start_mock: MagicMock, dca_start_mock: MagicMock,
                                             position_start_mock: MagicMock, twap_start_mock: MagicMock):
        markets_recorder_mock.return_value = MagicMock(spec=MarketsRecorder)
        markets_recorder_mock.store_or_update_executor = MagicMock(return_value=None)
        position_executor_config = PositionExecutorConfig(
            timestamp=1234, connector_name="binance",
            trading_pair="ETH-USDT", side=TradeType.BUY, entry_price=Decimal(100), amount=Decimal(10))
        arbitrage_executor_config = ArbitrageExecutorConfig(
            timestamp=1234, order_amount=Decimal(10), min_profitability=Decimal(0.01),
            buying_market=ConnectorPair(connector_name="binance", trading_pair="ETH-USDT"),
            selling_market=ConnectorPair(connector_name="coinbase", trading_pair="ETH-USDT"),
        )
        dca_executor_config = DCAExecutorConfig(
            timestamp=1234, connector_name="binance", trading_pair="ETH-USDT",
            side=TradeType.BUY, amounts_quote=[Decimal(10)], prices=[Decimal(100)],)
        twap_executor_config = TWAPExecutorConfig(
            timestamp=1234, connector_name="binance", trading_pair="ETH-USDT",
            side=TradeType.BUY, total_amount_quote=Decimal(100), total_duration=10, order_interval=5,
        )
        grid_executor_config = GridExecutorConfig(
            timestamp=1234, connector_name="binance", trading_pair="ETH-USDT",
            side=TradeType.BUY, total_amount_quote=Decimal(100), start_price=Decimal(100),
            end_price=Decimal(200), limit_price=Decimal(90),
            triple_barrier_config=TripleBarrierConfig(take_profit=Decimal(0.01), stop_loss=Decimal(0.2))
        )
        actions = [
            CreateExecutorAction(executor_config=position_executor_config, controller_id="test"),
            CreateExecutorAction(executor_config=arbitrage_executor_config, controller_id="test"),
            CreateExecutorAction(executor_config=dca_executor_config, controller_id="test"),
            CreateExecutorAction(executor_config=twap_executor_config, controller_id="test"),
            CreateExecutorAction(executor_config=grid_executor_config, controller_id="test"),
        ]
        self.orchestrator.execute_actions(actions)
        self.assertEqual(len(self.orchestrator.active_executors["test"]), 5)

    def test_execute_actions_store_executor_active(self):
        position_executor = MagicMock(spec=PositionExecutor)
        position_executor.is_active = True
        config_mock = MagicMock(PositionExecutorConfig)
        config_mock.id = "test"
        config_mock.controller_id = "test"
        position_executor.config = config_mock
        self.orchestrator.cached_performance["test"] = PerformanceReport()
        self.orchestrator.active_executors["test"] = [position_executor]
        actions = [StoreExecutorAction(executor_id="test", controller_id="test")]
        self.orchestrator.execute_actions(actions)
        self.assertEqual(len(self.orchestrator.active_executors["test"]), 1)

    @patch.object(MarketsRecorder, "get_instance")
    def test_execute_actions_store_executor_inactive(self, markets_recorder_mock):
        markets_recorder_mock.return_value = MagicMock(spec=MarketsRecorder)
        markets_recorder_mock.store_or_update_executor = MagicMock(return_value=None)
        position_executor = MagicMock(spec=PositionExecutor)
        position_executor.is_active = False
        config_mock = MagicMock(PositionExecutorConfig)
        config_mock.id = "test"
        config_mock.controller_id = "test"
        position_executor.config = config_mock
        self.orchestrator.active_executors["test"] = [position_executor]
        self.orchestrator.cached_performance["test"] = PerformanceReport()
        actions = [StoreExecutorAction(executor_id="test", controller_id="test")]
        self.orchestrator.execute_actions(actions)
        self.assertEqual(len(self.orchestrator.active_executors["test"]), 0)

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.time.time")
    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_get_executors_report_persists_live_snapshots(self, mock_get_instance, mock_time):
        mock_time.return_value = 100.0
        markets_recorder_mock = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = markets_recorder_mock

        config_mock = PositionExecutorConfig(
            timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
            side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
        )
        executor_info = ExecutorInfo(
            id="live-exec", timestamp=1234, type="position_executor",
            status=RunnableStatus.RUNNING, config=config_mock,
            filled_amount_quote=Decimal("25"), net_pnl_quote=Decimal("1"), net_pnl_pct=Decimal("0.04"),
            cum_fees_quote=Decimal("0.05"), is_trading=True, is_active=True, custom_info={"side": TradeType.BUY},
            controller_id="test",
        )
        executor = MagicMock()
        executor.is_closed = False
        executor.executor_info = executor_info
        executor.config = config_mock

        self.orchestrator.active_executors["test"] = [executor]

        report = self.orchestrator.get_executors_report()

        markets_recorder_mock.store_or_update_executor.assert_called_once_with(executor)
        self.assertEqual(report["test"], [executor_info])

    @patch('hummingbot.connector.markets_recorder.MarketsRecorder.get_instance')
    def test_generate_performance_report(self, mock_get_instance):
        # Create a mock for MarketsRecorder and its get_executors_by_controller method
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_markets_recorder.get_executors_by_controller.return_value = []
        mock_get_instance.return_value = mock_markets_recorder
        config_mock = PositionExecutorConfig(
            timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
            side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
        )
        position_executor_non_active = MagicMock(spec=PositionExecutor)
        position_executor_non_active.executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.RUNNING, config=config_mock,
            filled_amount_quote=Decimal(0), net_pnl_quote=Decimal(0), net_pnl_pct=Decimal(0),
            cum_fees_quote=Decimal(0), is_trading=False, is_active=True, custom_info={"side": TradeType.BUY}
        )
        position_executor_active = MagicMock(spec=PositionExecutor)
        position_executor_active.executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.RUNNING, config=config_mock,
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(10), net_pnl_pct=Decimal(10),
            cum_fees_quote=Decimal(1), is_trading=True, is_active=True, custom_info={"side": TradeType.BUY}
        )
        position_executor_failed = MagicMock(spec=PositionExecutor)
        position_executor_failed.executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=config_mock,
            close_type=CloseType.FAILED,
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(0), net_pnl_pct=Decimal(0),
            cum_fees_quote=Decimal(1), is_trading=True, is_active=True, custom_info={"side": TradeType.BUY}
        )
        position_executor_tp = MagicMock(spec=PositionExecutor)
        position_executor_tp.executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=config_mock,
            close_type=CloseType.TAKE_PROFIT,
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(10), net_pnl_pct=Decimal(10),
            cum_fees_quote=Decimal(1), is_trading=False, is_active=False, custom_info={"side": TradeType.BUY}
        )
        self.orchestrator.active_executors["test"] = [position_executor_non_active, position_executor_active,
                                                      position_executor_failed, position_executor_tp]
        report = self.orchestrator.generate_performance_report(controller_id="test")
        self.assertEqual(report.realized_pnl_quote, Decimal(10))
        self.assertEqual(report.unrealized_pnl_quote, Decimal(10))

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_initialize_cached_performance(self, mock_get_instance: MagicMock):
        # Create mock markets recorder
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # Create mock executor info
        executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.RUNNING, config=PositionExecutorConfig(
                timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ),
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(10), net_pnl_pct=Decimal(10),
            cum_fees_quote=Decimal(1), is_trading=True, is_active=True, custom_info={"side": TradeType.BUY},
            controller_id="test",
        )

        # Set up mock to return executor info
        mock_markets_recorder.get_all_executors.return_value = [executor_info]
        mock_markets_recorder.get_all_positions.return_value = []

        # Add the controller to the strategy's controllers dict
        self.mock_strategy.controllers = {"test": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)
        self.assertEqual(len(orchestrator.cached_performance), 1)

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_initialize_cached_performance_with_positions(self, mock_get_instance: MagicMock):
        # Create mock markets recorder
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # Create mock position from database
        position1 = Position(
            id="pos1",
            timestamp=1234,
            controller_id="controller1",
            connector_name="binance",
            trading_pair="ETH-USDT",
            side=TradeType.BUY.name,
            amount=Decimal("1"),
            breakeven_price=Decimal("1000"),
            unrealized_pnl_quote=Decimal("50"),
            cum_fees_quote=Decimal("5"),
            volume_traded_quote=Decimal("1000")
        )

        position2 = Position(
            id="pos2",
            timestamp=1235,
            controller_id="controller2",
            connector_name="binance",
            trading_pair="BTC-USDT",
            side=TradeType.SELL.name,
            amount=Decimal("0.1"),
            breakeven_price=Decimal("50000"),
            unrealized_pnl_quote=Decimal("-100"),
            cum_fees_quote=Decimal("10"),
            volume_traded_quote=Decimal("5000")
        )

        # Set up mock to return executor info and positions
        mock_markets_recorder.get_all_executors.return_value = []
        mock_markets_recorder.get_all_positions.return_value = [position1, position2]

        # Add the controllers to the strategy's controllers dict
        self.mock_strategy.controllers = {"controller1": MagicMock(), "controller2": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Check that positions were loaded
        self.assertEqual(len(orchestrator.cached_performance), 2)
        self.assertIn("controller1", orchestrator.cached_performance)
        self.assertIn("controller2", orchestrator.cached_performance)

        # Check that positions were converted to PositionHold objects
        self.assertEqual(len(orchestrator.positions_held["controller1"]), 1)
        self.assertEqual(len(orchestrator.positions_held["controller2"]), 1)

        # Verify position data was correctly loaded
        position_hold1 = orchestrator.positions_held["controller1"][0]
        self.assertEqual(position_hold1.connector_name, "binance")
        self.assertEqual(position_hold1.trading_pair, "ETH-USDT")
        self.assertEqual(position_hold1.side, TradeType.BUY)
        self.assertEqual(position_hold1.buy_amount_base, Decimal("1"))
        self.assertEqual(position_hold1.buy_amount_quote, Decimal("1000"))
        self.assertEqual(position_hold1.volume_traded_quote, Decimal("1000"))
        self.assertEqual(position_hold1.cum_fees_quote, Decimal("5"))

        position_hold2 = orchestrator.positions_held["controller2"][0]
        self.assertEqual(position_hold2.connector_name, "binance")
        self.assertEqual(position_hold2.trading_pair, "BTC-USDT")
        self.assertEqual(position_hold2.side, TradeType.SELL)
        self.assertEqual(position_hold2.sell_amount_base, Decimal("0.1"))
        self.assertEqual(position_hold2.sell_amount_quote, Decimal("5000"))
        self.assertEqual(position_hold2.volume_traded_quote, Decimal("5000"))
        self.assertEqual(position_hold2.cum_fees_quote, Decimal("10"))

    @patch.object(MarketsRecorder, "get_instance")
    def test_store_all_positions(self, markets_recorder_mock):
        markets_recorder_mock.return_value = MagicMock(spec=MarketsRecorder)
        markets_recorder_mock.update_or_store_position = MagicMock(return_value=None)
        position_held = PositionHold("binance", "SOL-USDT", side=TradeType.BUY)
        executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1234, trading_pair="SOL-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ), net_pnl_pct=Decimal(0), net_pnl_quote=Decimal(0), cum_fees_quote=Decimal(0),
            filled_amount_quote=Decimal(100), is_active=False, is_trading=False,
            custom_info={"held_position_orders": [
                {"order_id": "123", "amount": Decimal(10), "trade_type": "BUY",
                 "executed_amount_base": Decimal("10"), "executed_amount_quote": Decimal("2300"),
                 "cumulative_fee_paid_quote": Decimal(0)}]},
            controller_id="main"
        )
        position_held.add_orders_from_executor(executor_info)
        self.orchestrator.positions_held = {
            "main": [position_held]
        }
        self.orchestrator.store_all_positions()
        self.assertEqual(len(self.orchestrator.positions_held), 0)

    def test_get_positions_report(self):
        position_held = PositionHold("binance", "SOL-USDT", side=TradeType.BUY)
        executor_info = ExecutorInfo(
            id="123", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1234, trading_pair="SOL-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ), net_pnl_pct=Decimal(0), net_pnl_quote=Decimal(0), cum_fees_quote=Decimal(0),
            filled_amount_quote=Decimal(100), is_active=False, is_trading=False,
            custom_info={"held_position_orders": [
                {"order_id": "123", "amount": Decimal(10), "trade_type": "SELL",
                 "executed_amount_base": Decimal("10"), "executed_amount_quote": Decimal("2300"),
                 "cumulative_fee_paid_quote": Decimal(0)}]},
            controller_id="main"
        )
        position_held.add_orders_from_executor(executor_info)
        self.orchestrator.positions_held = {
            "main": [position_held]
        }
        report = self.orchestrator.get_positions_report()
        self.assertEqual(len(report), 1)
        self.assertEqual(report["main"][0].amount, Decimal(10))

    @patch.object(MarketsRecorder, "get_instance")
    def test_store_all_executors(self, markets_recorder_mock):
        markets_recorder_mock.return_value = MagicMock(spec=MarketsRecorder)
        markets_recorder_mock.store_or_update_executor = MagicMock(return_value=None)
        position_executor = MagicMock(spec=PositionExecutor)
        position_executor.is_active = False
        config_mock = MagicMock(PositionExecutorConfig)
        config_mock.id = "test"
        config_mock.controller_id = "test"
        position_executor.config = config_mock
        self.orchestrator.active_executors["test"] = [position_executor]
        self.orchestrator.store_all_executors()
        self.assertEqual(self.orchestrator.active_executors, {})

    @patch.object(ExecutorOrchestrator, "store_all_positions")
    def test_stop(self, store_all_positions):
        async def test_async():
            store_all_positions.return_value = None
            position_executor = MagicMock(spec=PositionExecutor)
            position_executor.is_closed = False
            position_executor.early_stop = MagicMock(return_value=None)
            position_executor.executor_info = MagicMock()
            position_executor.executor_info.is_done = True
            self.orchestrator.active_executors["test"] = [position_executor]
            await self.orchestrator.stop()
            position_executor.early_stop.assert_called_once()

        asyncio.run(test_async())

    def test_stop_executor(self):
        position_executor = MagicMock(spec=PositionExecutor)
        position_executor.is_closed = False
        position_executor.early_stop = MagicMock(return_value=None)
        position_executor.config = MagicMock(PositionExecutorConfig)
        position_executor.config.id = "123"
        self.orchestrator.active_executors["test"] = [position_executor]
        self.orchestrator.stop_executor(StopExecutorAction(executor_id="123", controller_id="test"))

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_generate_performance_report_with_loaded_positions(self, mock_get_instance: MagicMock):
        # Create mock markets recorder
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # Create a position from database
        db_position = Position(
            id="pos1",
            timestamp=1234,
            controller_id="test",
            connector_name="binance",
            trading_pair="ETH-USDT",
            side=TradeType.BUY.name,
            amount=Decimal("2"),
            breakeven_price=Decimal("1000"),
            unrealized_pnl_quote=Decimal("100"),
            cum_fees_quote=Decimal("10"),
            volume_traded_quote=Decimal("2000")
        )

        # Set up mock to return position
        mock_markets_recorder.get_all_executors.return_value = []
        mock_markets_recorder.get_all_positions.return_value = [db_position]

        # Add the controller to the strategy's controllers dict
        self.mock_strategy.controllers = {"test": MagicMock()}

        # Create orchestrator which will load the position
        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Generate performance report
        report = orchestrator.generate_performance_report(controller_id="test")

        # Verify the report includes data from the loaded position
        self.assertEqual(report.volume_traded, Decimal("2000"))
        # The unrealized PnL should be calculated fresh based on current price (230)
        # For a BUY position: (current_price - breakeven_price) * amount = (230 - 1000) * 2 = -1540
        self.assertEqual(report.unrealized_pnl_quote, Decimal("-1540"))
        # Check that the report has the position summary
        self.assertTrue(hasattr(report, "positions_summary"))
        self.assertEqual(len(report.positions_summary), 1)
        self.assertEqual(report.positions_summary[0].amount, Decimal("2"))
        self.assertEqual(report.positions_summary[0].breakeven_price, Decimal("1000"))

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_initial_positions_override(self, mock_get_instance: MagicMock):
        # Create mock markets recorder
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # Create a database position that should be ignored due to override
        db_position = Position(
            id="db_pos1",
            timestamp=1234,
            controller_id="test_controller",
            connector_name="binance",
            trading_pair="ETH-USDT",
            side=TradeType.BUY.name,
            amount=Decimal("5"),
            breakeven_price=Decimal("2000"),
            unrealized_pnl_quote=Decimal("0"),
            cum_fees_quote=Decimal("0"),
            volume_traded_quote=Decimal("10000")
        )

        # Import the shared InitialPositionConfig
        from hummingbot.strategy_v2.models.position_config import InitialPositionConfig

        # Create initial position configs that should override the database
        initial_positions = {
            "test_controller": [
                InitialPositionConfig(
                    connector_name="binance",
                    trading_pair="ETH-USDT",
                    amount=Decimal("2"),
                    side=TradeType.BUY
                ),
                InitialPositionConfig(
                    connector_name="binance",
                    trading_pair="BTC-USDT",
                    amount=Decimal("0.1"),
                    side=TradeType.SELL
                )
            ]
        }

        # Set up mock to return both executors and positions
        mock_markets_recorder.get_all_executors.return_value = []
        mock_markets_recorder.get_all_positions.return_value = [db_position]

        # Add the controller to the strategy's controllers dict
        self.mock_strategy.controllers = {"test_controller": MagicMock()}

        # Create orchestrator with initial position overrides
        orchestrator = ExecutorOrchestrator(
            strategy=self.mock_strategy,
            initial_positions_by_controller=initial_positions
        )

        # Verify that the database position was NOT loaded
        # and instead the initial positions were created
        self.assertEqual(len(orchestrator.positions_held["test_controller"]), 2)

        # Check first position (ETH-USDT BUY)
        eth_position = orchestrator.positions_held["test_controller"][0]
        self.assertEqual(eth_position.connector_name, "binance")
        self.assertEqual(eth_position.trading_pair, "ETH-USDT")
        self.assertEqual(eth_position.side, TradeType.BUY)
        self.assertEqual(eth_position.buy_amount_base, Decimal("2"))
        self.assertTrue(eth_position.buy_amount_quote.is_nan())  # Initially NaN
        self.assertEqual(eth_position.volume_traded_quote, Decimal("0"))  # Fresh start
        self.assertEqual(eth_position.cum_fees_quote, Decimal("0"))  # Fresh start

        # Check second position (BTC-USDT SELL)
        btc_position = orchestrator.positions_held["test_controller"][1]
        self.assertEqual(btc_position.connector_name, "binance")
        self.assertEqual(btc_position.trading_pair, "BTC-USDT")
        self.assertEqual(btc_position.side, TradeType.SELL)
        self.assertEqual(btc_position.sell_amount_base, Decimal("0.1"))
        self.assertTrue(btc_position.sell_amount_quote.is_nan())  # Initially NaN
        self.assertEqual(btc_position.volume_traded_quote, Decimal("0"))  # Fresh start
        self.assertEqual(btc_position.cum_fees_quote, Decimal("0"))  # Fresh start

        # Test that lazy calculation works when getting position summary
        eth_summary = eth_position.get_position_summary(Decimal("230"))
        self.assertEqual(eth_position.buy_amount_quote, Decimal("2") * Decimal("230"))  # Now calculated
        self.assertEqual(eth_summary.breakeven_price, Decimal("230"))

        btc_summary = btc_position.get_position_summary(Decimal("230"))
        self.assertEqual(btc_position.sell_amount_quote, Decimal("0.1") * Decimal("230"))  # Now calculated
        self.assertEqual(btc_summary.breakeven_price, Decimal("230"))

    def test_get_all_reports_with_done_position_hold_executors(self):
        """Test get_all_reports with executors that need position updates"""
        # This tests the high-level functionality that exercises lines 413,415,423-424,426,428-430,433,436,438-439,442,447-448

        # Create an executor that meets criteria for position hold processing
        config = PositionExecutorConfig(
            timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
            side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
        )
        config.id = "test_executor_id"

        executor = MagicMock()
        executor.executor_info = ExecutorInfo(
            id="test_executor_id", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=config,
            filled_amount_quote=Decimal(1000), net_pnl_quote=Decimal(50), net_pnl_pct=Decimal(5),
            cum_fees_quote=Decimal(5), is_trading=False, is_active=False,
            custom_info={"held_position_orders": [
                {"client_order_id": "order_1", "executed_amount_base": Decimal("5"),
                 "executed_amount_quote": Decimal("1000"), "trade_type": "BUY",
                 "cumulative_fee_paid_quote": Decimal("5")}
            ]},
            close_type=CloseType.POSITION_HOLD,
            connector_name="binance",
            trading_pair="ETH-USDT"
        )
        # Since is_done is a computed property based on status, and we set status=TERMINATED, is_done will be True

        # Set up orchestrator with the executor
        self.orchestrator.active_executors = {"test_controller": [executor]}
        self.orchestrator.positions_held = {"test_controller": []}
        self.orchestrator.executors_ids_position_held = []
        self.orchestrator.cached_performance = {"test_controller": PerformanceReport()}

        # Call get_all_reports which should trigger position processing
        result = self.orchestrator.get_all_reports()

        # Verify that the executor was processed and position created
        self.assertIn("test_executor_id", self.orchestrator.executors_ids_position_held)
        self.assertEqual(len(self.orchestrator.positions_held["test_controller"]), 1)

        # Verify the position was created correctly
        position = self.orchestrator.positions_held["test_controller"][0]
        self.assertEqual(position.connector_name, "binance")
        self.assertEqual(position.trading_pair, "ETH-USDT")
        self.assertEqual(position.side, TradeType.BUY)

        # Verify report structure
        self.assertIn("test_controller", result)
        self.assertIn("executors", result["test_controller"])
        self.assertIn("positions", result["test_controller"])
        self.assertIn("performance", result["test_controller"])

    def test_get_all_reports_with_perpetual_executors(self):
        """Test get_all_reports with perpetual market executors to exercise position side logic"""
        # This tests lines 454-456,458-460,462-465,467 through high-level functionality

        from hummingbot.core.data_type.common import PositionAction, PositionMode
        from hummingbot.strategy_v2.executors.order_executor.data_types import ExecutionStrategy, OrderExecutorConfig

        # Create config with position_action for perpetual market using OrderExecutorConfig
        config = OrderExecutorConfig(
            timestamp=1234, trading_pair="ETH-USDT", connector_name="binance_perpetual",
            side=TradeType.BUY, amount=Decimal(10), execution_strategy=ExecutionStrategy.MARKET,
            position_action=PositionAction.CLOSE
        )
        config.id = "perp_executor_id"

        executor = MagicMock()
        executor.executor_info = ExecutorInfo(
            id="perp_executor_id", timestamp=1234, type="order_executor",
            status=RunnableStatus.TERMINATED, config=config,
            filled_amount_quote=Decimal(1000), net_pnl_quote=Decimal(50), net_pnl_pct=Decimal(5),
            cum_fees_quote=Decimal(5), is_trading=False, is_active=False,
            custom_info={"held_position_orders": [
                {"client_order_id": "order_2", "executed_amount_base": Decimal("3"),
                 "executed_amount_quote": Decimal("600"), "trade_type": "SELL",
                 "cumulative_fee_paid_quote": Decimal("3")}
            ]},
            close_type=CloseType.POSITION_HOLD,
            connector_name="binance_perpetual",
            trading_pair="ETH-USDT"
        )
        # Since status=TERMINATED, is_done will be True

        # Set up perpetual market with HEDGE mode
        mock_market = MagicMock()
        mock_market.position_mode = PositionMode.HEDGE
        self.mock_strategy.connectors = {"binance_perpetual": mock_market}

        # Set up orchestrator
        self.orchestrator.active_executors = {"perp_controller": [executor]}
        self.orchestrator.positions_held = {"perp_controller": []}
        self.orchestrator.executors_ids_position_held = []
        self.orchestrator.cached_performance = {"perp_controller": PerformanceReport()}

        # Call get_all_reports
        self.orchestrator.get_all_reports()

        # Verify that the executor was processed
        self.assertIn("perp_executor_id", self.orchestrator.executors_ids_position_held)
        self.assertEqual(len(self.orchestrator.positions_held["perp_controller"]), 1)

        # Verify the position side logic was applied (CLOSE action should use opposite side)
        position = self.orchestrator.positions_held["perp_controller"][0]
        self.assertEqual(position.side, TradeType.SELL)  # Opposite of BUY due to CLOSE action

    def test_get_all_reports_with_existing_positions(self):
        """Test get_all_reports with existing positions to exercise find_existing_position logic"""
        # This tests lines 475-476,480-482,485,487 through high-level functionality

        # Create existing position
        existing_position = PositionHold("binance", "ETH-USDT", TradeType.BUY)
        existing_position.buy_amount_base = Decimal("2")
        existing_position.buy_amount_quote = Decimal("400")
        existing_position.volume_traded_quote = Decimal("400")

        # Create executor that should add to existing position
        config = PositionExecutorConfig(
            timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
            side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
        )
        config.id = "add_to_position_id"

        executor = MagicMock()
        executor.executor_info = ExecutorInfo(
            id="add_to_position_id", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=config,
            filled_amount_quote=Decimal(600), net_pnl_quote=Decimal(30), net_pnl_pct=Decimal(5),
            cum_fees_quote=Decimal(3), is_trading=False, is_active=False,
            custom_info={"held_position_orders": [
                {"client_order_id": "order_3", "executed_amount_base": Decimal("3"),
                 "executed_amount_quote": Decimal("600"), "trade_type": "BUY",
                 "cumulative_fee_paid_quote": Decimal("3")}
            ]},
            close_type=CloseType.POSITION_HOLD
        )
        # Since status=TERMINATED, is_done will be True

        # Set up orchestrator with existing position
        self.orchestrator.active_executors = {"existing_pos_controller": [executor]}
        self.orchestrator.positions_held = {"existing_pos_controller": [existing_position]}
        self.orchestrator.executors_ids_position_held = []
        self.orchestrator.cached_performance = {"existing_pos_controller": PerformanceReport()}

        # Call get_all_reports
        result = self.orchestrator.get_all_reports()

        # Verify that the executor was processed and added to existing position
        self.assertIn("add_to_position_id", self.orchestrator.executors_ids_position_held)
        self.assertEqual(len(self.orchestrator.positions_held["existing_pos_controller"]), 1)  # Still one position

        # Verify the existing position was updated
        self.assertEqual(existing_position.buy_amount_base, Decimal("5"))  # 2 + 3
        self.assertEqual(existing_position.buy_amount_quote, Decimal("1000"))  # 400 + 600
        self.assertEqual(existing_position.volume_traded_quote, Decimal("1000"))  # 400 + 600

        # Verify position appears in the report
        positions_in_report = result["existing_pos_controller"]["positions"]
        self.assertEqual(len(positions_in_report), 1)
        self.assertEqual(positions_in_report[0].amount, Decimal("5"))

    def test_get_all_reports_comprehensive_controller_aggregation(self):
        """Test get_all_reports aggregating controllers from different sources"""
        # This tests lines 545,548-549,552,557 comprehensively

        # Set up orchestrator with controllers spread across different data structures
        # Controller 1: Has active executors only
        self.orchestrator.active_executors = {"controller1": [MagicMock()]}

        # Controller 2: Has positions only
        position = PositionHold("binance", "BTC-USDT", TradeType.SELL)
        self.orchestrator.positions_held = {"controller2": [position]}

        # Controller 3: Has cached performance only
        self.orchestrator.cached_performance = {"controller3": PerformanceReport()}

        # Controller 4: Has multiple data types
        self.orchestrator.active_executors["controller4"] = [MagicMock()]
        self.orchestrator.positions_held["controller4"] = [PositionHold("binance", "ADA-USDT", TradeType.BUY)]
        self.orchestrator.cached_performance["controller4"] = PerformanceReport()

        # Call get_all_reports
        result = self.orchestrator.get_all_reports()

        # Verify all controllers are included
        expected_controllers = {"controller1", "controller2", "controller3", "controller4"}
        self.assertEqual(set(result.keys()), expected_controllers)

        # Verify each controller has the expected structure
        for controller_id in expected_controllers:
            self.assertIn("executors", result[controller_id])
            self.assertIn("positions", result[controller_id])
            self.assertIn("performance", result[controller_id])

        # Verify that controllers with no data have empty lists/reports
        self.assertEqual(len(result["controller1"]["positions"]), 0)
        self.assertEqual(len(result["controller2"]["executors"]), 0)
        self.assertEqual(len(result["controller3"]["executors"]), 0)
        self.assertEqual(len(result["controller3"]["positions"]), 0)

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_single_controller(self, mock_get_instance: MagicMock):
        """Orphan fills should create PositionHold entries, not add to realized PnL.

        A true orphan fill is one that:
        - Is NOT matched by order_id in any executor's filled_orders/held_position_orders
        - Falls OUTSIDE all executor active windows for its trading_pair
        - Occurred AFTER the first executor ever ran for that pair (not pre-executor history)
        - The pair HAS had at least one executor (otherwise it belongs to a different system)
        """
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # ETH-USDT executor: tracks one order, closed at t=2000s
        executor_eth = ExecutorInfo(
            id="exec1", timestamp=1000, close_timestamp=2000, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1000, trading_pair="ETH-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ),
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(5), net_pnl_pct=Decimal(5),
            cum_fees_quote=Decimal(1), is_trading=False, is_active=False,
            custom_info={"side": TradeType.BUY, "filled_orders": [{"client_order_id": "tracked_order_1"}]},
            controller_id="test",
            close_type=CloseType.TAKE_PROFIT,
        )

        # SOL-USDT executor: also closed at t=2000s, no filled_orders in custom_info
        executor_sol = ExecutorInfo(
            id="exec2", timestamp=1000, close_timestamp=2000, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1000, trading_pair="SOL-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(5), entry_price=Decimal(50),
            ),
            filled_amount_quote=Decimal(50), net_pnl_quote=Decimal(0), net_pnl_pct=Decimal(0),
            cum_fees_quote=Decimal(0), is_trading=False, is_active=False,
            custom_info={"side": TradeType.BUY},  # no filled_orders recorded
            controller_id="test",
            close_type=CloseType.TRAILING_STOP,
        )

        # Tracked fill for ETH-USDT (matched by order_id)
        tracked_fill = MagicMock()
        tracked_fill.order_id = "tracked_order_1"
        tracked_fill.price = Decimal("100")
        tracked_fill.amount = Decimal("1")
        tracked_fill.trade_fee_in_quote = Decimal("0.20")
        tracked_fill.trade_type = "BUY"
        tracked_fill.symbol = "ETH-USDT"
        tracked_fill.market = "binance"
        tracked_fill.timestamp = 1500000  # ms, within ETH executor window [1000000, 2060000]

        # True orphan fills for SOL-USDT: AFTER the SOL executor's close window (2000s + 60s buffer)
        # Window ends at: 2000*1000 + 60000 = 2060000 ms. Orphan fills arrive at 3000000 ms.
        orphan_buy = MagicMock()
        orphan_buy.order_id = "orphan_buy_1"
        orphan_buy.price = Decimal("50")
        orphan_buy.amount = Decimal("2")
        orphan_buy.trade_fee_in_quote = Decimal("0.10")
        orphan_buy.trade_type = "BUY"
        orphan_buy.symbol = "SOL-USDT"
        orphan_buy.market = "binance"
        orphan_buy.timestamp = 3000000  # ms, AFTER SOL executor close window

        orphan_sell = MagicMock()
        orphan_sell.order_id = "orphan_sell_1"
        orphan_sell.price = Decimal("55")
        orphan_sell.amount = Decimal("2")
        orphan_sell.trade_fee_in_quote = Decimal("0.15")
        orphan_sell.trade_type = "SELL"
        orphan_sell.symbol = "SOL-USDT"
        orphan_sell.market = "binance"
        orphan_sell.timestamp = 3000000  # ms, AFTER SOL executor close window

        mock_markets_recorder.get_all_executors.return_value = [executor_eth, executor_sol]
        mock_markets_recorder.get_all_positions.return_value = []
        mock_markets_recorder.get_all_trade_fills.return_value = [tracked_fill, orphan_buy, orphan_sell]

        self.mock_strategy.controllers = {"test": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Executor PnL in cached_performance: both executors (5 + 0 = 5)
        report = orchestrator.cached_performance["test"]
        self.assertEqual(report.realized_pnl_quote, Decimal("5"))

        # Orphan fills should create a PositionHold for SOL-USDT
        positions = orchestrator.positions_held.get("test", [])
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos.trading_pair, "SOL-USDT")
        self.assertEqual(pos.buy_amount_base, Decimal("2"))
        self.assertEqual(pos.sell_amount_base, Decimal("2"))
        self.assertEqual(pos.buy_amount_quote, Decimal("100"))   # 50*2
        self.assertEqual(pos.sell_amount_quote, Decimal("110"))  # 55*2
        self.assertEqual(pos.cum_fees_quote, Decimal("0.25"))
        self.assertEqual(pos.trading_pair, "SOL-USDT")
        self.assertEqual(pos.buy_amount_base, Decimal("2"))
        self.assertEqual(pos.sell_amount_base, Decimal("2"))
        self.assertEqual(pos.buy_amount_quote, Decimal("100"))   # 50*2
        self.assertEqual(pos.sell_amount_quote, Decimal("110"))  # 55*2
        self.assertEqual(pos.cum_fees_quote, Decimal("0.25"))

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_no_orphans(self, mock_get_instance: MagicMock):
        """When all fills are tracked, no orphan positions should be created."""
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        executor_info = ExecutorInfo(
            id="exec1", timestamp=1234, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1234, trading_pair="ETH-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ),
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(5), net_pnl_pct=Decimal(5),
            cum_fees_quote=Decimal(1), is_trading=False, is_active=False,
            custom_info={
                "side": TradeType.BUY,
                "filled_orders": [{"client_order_id": "order_1"}],
            },
            controller_id="test",
            close_type=CloseType.TAKE_PROFIT,
        )

        # All fills tracked by the executor
        tracked_fill = MagicMock()
        tracked_fill.order_id = "order_1"
        tracked_fill.price = Decimal("100")
        tracked_fill.amount = Decimal("1")
        tracked_fill.trade_fee_in_quote = Decimal("0.20")
        tracked_fill.trade_type = "BUY"
        tracked_fill.symbol = "ETH-USDT"
        tracked_fill.market = "binance"

        mock_markets_recorder.get_all_executors.return_value = [executor_info]
        mock_markets_recorder.get_all_positions.return_value = []
        mock_markets_recorder.get_all_trade_fills.return_value = [tracked_fill]

        self.mock_strategy.controllers = {"test": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)
        report = orchestrator.cached_performance["test"]

        # Only executor PnL, no orphan positions
        self.assertEqual(report.realized_pnl_quote, Decimal("5"))
        self.assertEqual(report.volume_traded, Decimal("100"))
        self.assertEqual(len(orchestrator.positions_held.get("test", [])), 0)

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_multi_controller_skipped(self, mock_get_instance: MagicMock):
        """Orphan adjustment should be skipped for multi-controller setups."""
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        mock_markets_recorder.get_all_executors.return_value = []
        mock_markets_recorder.get_all_positions.return_value = []
        # This should NOT be called when multi-controller is detected
        mock_markets_recorder.get_all_trade_fills.return_value = []

        self.mock_strategy.controllers = {"ctrl1": MagicMock(), "ctrl2": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Both controllers should have default empty reports
        self.assertEqual(orchestrator.cached_performance["ctrl1"].realized_pnl_quote, Decimal("0"))
        self.assertEqual(orchestrator.cached_performance["ctrl2"].realized_pnl_quote, Decimal("0"))
        # get_all_trade_fills should not have been called
        mock_markets_recorder.get_all_trade_fills.assert_not_called()

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_empty_fills(self, mock_get_instance: MagicMock):
        """Empty TradeFills should not cause errors."""
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        mock_markets_recorder.get_all_executors.return_value = []
        mock_markets_recorder.get_all_positions.return_value = []
        mock_markets_recorder.get_all_trade_fills.return_value = []

        self.mock_strategy.controllers = {"test": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)
        report = orchestrator.cached_performance["test"]

        self.assertEqual(report.realized_pnl_quote, Decimal("0"))
        self.assertEqual(report.volume_traded, Decimal("0"))

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_held_position_orders(self, mock_get_instance: MagicMock):
        """Orders in held_position_orders should also be considered tracked.

        A fill for a pair that has never had an executor is NOT classified as an orphan
        (it belongs to a different trading system). Only fills that arrive after an executor
        already closed for that pair are genuine orphans.
        """
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # ETH-USDT executor closed at t=2000s, tracks filled_1 and held_1
        executor_eth = ExecutorInfo(
            id="exec1", timestamp=1000, close_timestamp=2000, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1000, trading_pair="ETH-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(10), entry_price=Decimal(100),
            ),
            filled_amount_quote=Decimal(100), net_pnl_quote=Decimal(0), net_pnl_pct=Decimal(0),
            cum_fees_quote=Decimal(1), is_trading=False, is_active=False,
            custom_info={
                "side": TradeType.BUY,
                "filled_orders": [{"client_order_id": "filled_1"}],
                "held_position_orders": [{"client_order_id": "held_1"}],
            },
            controller_id="test",
            close_type=CloseType.TAKE_PROFIT,
        )

        # SOL-USDT executor closed at t=2000s — needed so SOL fills qualify as orphans
        executor_sol = ExecutorInfo(
            id="exec2", timestamp=1000, close_timestamp=2000, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1000, trading_pair="SOL-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(5), entry_price=Decimal(50),
            ),
            filled_amount_quote=Decimal(0), net_pnl_quote=Decimal(0), net_pnl_pct=Decimal(0),
            cum_fees_quote=Decimal(0), is_trading=False, is_active=False,
            custom_info={"side": TradeType.BUY},
            controller_id="test",
            close_type=CloseType.TRAILING_STOP,
        )

        # held_1 is tracked by the ETH executor's held_position_orders
        held_fill = MagicMock()
        held_fill.order_id = "held_1"
        held_fill.price = Decimal("100")
        held_fill.amount = Decimal("1")
        held_fill.trade_fee_in_quote = Decimal("0.10")
        held_fill.trade_type = "BUY"
        held_fill.symbol = "ETH-USDT"
        held_fill.market = "binance"
        held_fill.timestamp = 1500000  # ms, within ETH executor window

        # True orphan SELL for SOL-USDT — arrives AFTER the SOL executor's close window
        # Close window ends at: 2000*1000 + 60000 = 2060000 ms
        orphan_fill = MagicMock()
        orphan_fill.order_id = "orphan_1"
        orphan_fill.price = Decimal("200")
        orphan_fill.amount = Decimal("1")
        orphan_fill.trade_fee_in_quote = Decimal("0.50")
        orphan_fill.trade_type = "SELL"
        orphan_fill.symbol = "SOL-USDT"
        orphan_fill.market = "binance"
        orphan_fill.timestamp = 3000000  # ms, AFTER SOL executor close window

        mock_markets_recorder.get_all_executors.return_value = [executor_eth, executor_sol]
        mock_markets_recorder.get_all_positions.return_value = []
        mock_markets_recorder.get_all_trade_fills.return_value = [held_fill, orphan_fill]

        self.mock_strategy.controllers = {"test": MagicMock()}

        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Executor PnL stays at 0 (no orphan added to realized)
        report = orchestrator.cached_performance["test"]
        self.assertEqual(report.realized_pnl_quote, Decimal("0"))

        # Orphan SELL creates a PositionHold for SOL-USDT with net short direction
        positions = orchestrator.positions_held.get("test", [])
        self.assertEqual(len(positions), 1)
        pos = positions[0]
        self.assertEqual(pos.trading_pair, "SOL-USDT")
        self.assertEqual(pos.sell_amount_base, Decimal("1"))
        self.assertEqual(pos.sell_amount_quote, Decimal("200"))
        self.assertEqual(pos.side, TradeType.SELL)  # net short

    @patch("hummingbot.strategy_v2.executors.executor_orchestrator.MarketsRecorder.get_instance")
    def test_orphan_fill_adjustment_excludes_historical_and_foreign_fills(self, mock_get_instance: MagicMock):
        """Verify that fills are excluded when:
        - The fill is for a pair that never had an executor (foreign-system fill).
        - The fill arrived before the first executor ever opened for that pair (pre-executor history).
        - The fill falls within an executor's active window (late arriving exchange fill).
        Only fills after all executor windows, for pairs that had executors, should be orphans.
        """
        mock_markets_recorder = MagicMock(spec=MarketsRecorder)
        mock_get_instance.return_value = mock_markets_recorder

        # SOL-USDT executor: open=1000s, close=2000s → window [1000000ms, 2060000ms]
        executor_sol = ExecutorInfo(
            id="exec_sol", timestamp=1000, close_timestamp=2000, type="position_executor",
            status=RunnableStatus.TERMINATED, config=PositionExecutorConfig(
                timestamp=1000, trading_pair="SOL-USDT", connector_name="binance",
                side=TradeType.BUY, amount=Decimal(5), entry_price=Decimal(50),
            ),
            filled_amount_quote=Decimal(50), net_pnl_quote=Decimal(1), net_pnl_pct=Decimal(2),
            cum_fees_quote=Decimal(0), is_trading=False, is_active=False,
            custom_info={"side": TradeType.BUY},
            controller_id="test",
            close_type=CloseType.TRAILING_STOP,
        )

        # 1. Foreign fill — BTC-USDT has no executor at all
        foreign_fill = MagicMock()
        foreign_fill.order_id = "btc_fill_1"
        foreign_fill.symbol = "BTC-USDT"
        foreign_fill.timestamp = 5000000  # doesn't matter, pair has no executor
        foreign_fill.trade_type = "BUY"
        foreign_fill.price = Decimal("30000")
        foreign_fill.amount = Decimal("0.01")
        foreign_fill.trade_fee_in_quote = Decimal("0.30")
        foreign_fill.market = "binance"

        # 2. Pre-executor fill — SOL-USDT fill BEFORE the first SOL executor opened
        pre_exec_fill = MagicMock()
        pre_exec_fill.order_id = "sol_early_fill"
        pre_exec_fill.symbol = "SOL-USDT"
        pre_exec_fill.timestamp = 500000  # ms — before SOL executor opened at 1000000ms
        pre_exec_fill.trade_type = "BUY"
        pre_exec_fill.price = Decimal("40")
        pre_exec_fill.amount = Decimal("3")
        pre_exec_fill.trade_fee_in_quote = Decimal("0.12")
        pre_exec_fill.market = "binance"

        # 3. In-window fill — SOL-USDT fill DURING the SOL executor's active window
        in_window_fill = MagicMock()
        in_window_fill.order_id = "sol_in_window"
        in_window_fill.symbol = "SOL-USDT"
        in_window_fill.timestamp = 1500000  # ms — inside [1000000, 2060000]
        in_window_fill.trade_type = "SELL"
        in_window_fill.price = Decimal("55")
        in_window_fill.amount = Decimal("1")
        in_window_fill.trade_fee_in_quote = Decimal("0.05")
        in_window_fill.market = "binance"

        # 4. True orphan — SOL-USDT fill AFTER the executor's close window
        true_orphan_fill = MagicMock()
        true_orphan_fill.order_id = "sol_late_fill"
        true_orphan_fill.symbol = "SOL-USDT"
        true_orphan_fill.timestamp = 5000000  # ms — after window ends at 2060000ms
        true_orphan_fill.trade_type = "BUY"
        true_orphan_fill.price = Decimal("60")
        true_orphan_fill.amount = Decimal("1")
        true_orphan_fill.trade_fee_in_quote = Decimal("0.06")
        true_orphan_fill.market = "binance"

        mock_markets_recorder.get_all_executors.return_value = [executor_sol]
        mock_markets_recorder.get_all_positions.return_value = []
        mock_markets_recorder.get_all_trade_fills.return_value = [
            foreign_fill, pre_exec_fill, in_window_fill, true_orphan_fill
        ]

        self.mock_strategy.controllers = {"test": MagicMock()}
        orchestrator = ExecutorOrchestrator(strategy=self.mock_strategy)

        # Only the true orphan fill should create a position
        positions = orchestrator.positions_held.get("test", [])
        self.assertEqual(len(positions), 1, "Only true orphan fills should create positions")
        pos = positions[0]
        self.assertEqual(pos.trading_pair, "SOL-USDT")
        self.assertEqual(pos.buy_amount_base, Decimal("1"))
        self.assertEqual(pos.buy_amount_quote, Decimal("60"))  # 60 * 1
        self.assertEqual(pos.cum_fees_quote, Decimal("0.06"))
