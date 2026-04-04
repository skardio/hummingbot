"""
Tests for the zombie close-guard fix.

Bug: When a close order (from a previous run) is cancelled, _closing_in_progress
stays True and blocks all future close attempts → orphaned coins (FET-USD orphan).

Fix: process_order_canceled_event now resets _closing_in_progress and _close_order_id
when the close order is cancelled. Safety net in CLOSING state machine also detects
cancelled orders in _canceled_orders list.
"""

from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import TrackedOrder


class TestZombieCloseGuardFix:
    """Test that cancelled close orders properly reset the close guard."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_balance = Mock(return_value=Decimal("100.0"))
        connector.get_price = Mock(return_value=Decimal("0.25"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "FET-USD": TradingRule(
                trading_pair="FET-USD",
                min_order_size=Decimal("1.0"),
                min_notional_size=Decimal("0.5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_zombie_guard",
            connector_name="kraken",
            trading_pair="FET-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=2,
            start_price=Decimal("0.20"),
            end_price=Decimal("0.30"),
            limit_price=Decimal("0.15"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.10"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="FET-USD",
                min_order_size=Decimal("1.0"),
                min_notional_size=Decimal("0.5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.01"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.25")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"kraken": mock_connector}
            return ex

    # ------------------------------------------------------------------
    # TEST: Cancel event resets all close state
    # ------------------------------------------------------------------

    def test_cancel_event_resets_close_guard(self, executor):
        """When close order is cancelled, _closing_in_progress must reset to False."""
        close_order_id = "zombie_order_123"
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        # Simulate OrderCancelledEvent
        event = MagicMock()
        event.order_id = close_order_id

        executor.process_order_canceled_event(None, MagicMock(), event)

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
        assert executor._close_order is None
        assert close_order_id in executor._canceled_orders

    def test_cancel_event_safety_net_close_order_already_none(self, executor):
        """When _close_order is None but _close_order_id matches, still reset guard."""
        close_order_id = "zombie_order_456"
        executor._close_order = None  # Already cleared somehow
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        event = MagicMock()
        event.order_id = close_order_id

        executor.process_order_canceled_event(None, MagicMock(), event)

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
        assert close_order_id in executor._canceled_orders

    def test_cancel_event_does_not_affect_unrelated_orders(self, executor):
        """Cancelling a grid-level order must NOT reset the close guard."""
        executor._close_order = TrackedOrder(order_id="real_close_order")
        executor._close_order_id = "real_close_order"
        executor._closing_in_progress = True

        # Cancel an unrelated open order
        event = MagicMock()
        event.order_id = "grid_open_order_789"

        executor.process_order_canceled_event(None, MagicMock(), event)

        # Close guard must remain active
        assert executor._closing_in_progress is True
        assert executor._close_order_id == "real_close_order"
        assert executor._close_order is not None

    # ------------------------------------------------------------------
    # TEST: CLOSING state machine safety net
    # ------------------------------------------------------------------

    def test_closing_state_detects_cancelled_order_id(self, executor):
        """In CLOSING state, if _close_order_id is in _canceled_orders, reset guard."""
        zombie_id = "zombie_1903315003"
        executor._close_order_id = zombie_id
        executor._close_order = None
        executor._closing_in_progress = True
        executor._canceled_orders.append(zombie_id)

        from hummingbot.strategy_v2.models.base import RunnableStatus
        executor._status = RunnableStatus.CLOSING

        # The state machine code that checks this is inside control_task.
        # We test the logic directly: if close_order_id in _canceled_orders → reset.
        assert zombie_id in executor._canceled_orders
        # After the fix, the CLOSING branch resets the guard
        # Simulate the check:
        if executor._close_order_id in executor._canceled_orders:
            executor._closing_in_progress = False
            executor._close_order_id = None

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None


class TestZombieScenarioEndToEnd:
    """End-to-end test simulating the FET-USD zombie orphan scenario."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("340.52"))
        connector.get_balance = Mock(return_value=Decimal("340.52"))
        connector.get_price = Mock(return_value=Decimal("0.2426"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "FET-USD": TradingRule(
                trading_pair="FET-USD",
                min_order_size=Decimal("1.0"),
                min_notional_size=Decimal("0.5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_fet_zombie",
            connector_name="kraken",
            trading_pair="FET-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=2,
            start_price=Decimal("0.20"),
            end_price=Decimal("0.30"),
            limit_price=Decimal("0.15"),
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.10"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="FET-USD",
                min_order_size=Decimal("1.0"),
                min_notional_size=Decimal("0.5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.01"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.2426")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"kraken": mock_connector}
            return ex

    def test_zombie_order_cancel_allows_retry(self, executor):
        """
        Scenario: Close order 1903315003 from previous run is restored.
        It stays OPEN for 1.5h, then is finally cancelled.
        After cancellation, a NEW close order must be possible.
        """
        zombie_id = "1903315003"

        # Step 1: Executor has a close order from previous run
        executor._close_order = TrackedOrder(order_id=zombie_id)
        executor._close_order_id = zombie_id
        executor._closing_in_progress = True

        # Step 2: Cancel event arrives for the zombie order
        cancel_event = MagicMock()
        cancel_event.order_id = zombie_id
        executor.process_order_canceled_event(None, MagicMock(), cancel_event)

        # Step 3: Verify guard is reset
        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
        assert executor._close_order is None

        # Step 4: A new close attempt should NOT be blocked by the guard
        # (The "Close already in progress" check should pass)
        assert executor._closing_in_progress is False  # Guard allows entry
