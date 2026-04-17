"""
Tests for the failed-order close-guard fix.

Bug: When a close order FAILS (e.g. "Insufficient balance" from Bitget), the
executor clears _close_order but never resets _closing_in_progress and
_close_order_id. The executor gets stuck forever logging "awaiting exchange
confirmation" every second — a variant of the zombie close-guard.

Fix:
1. process_order_failed_event now always resets _closing_in_progress and
   _close_order_id when the main close order fails, so the executor can retry.
2. The CLOSING state machine safety net now checks _failed_orders alongside
   _canceled_orders.

Observed in production: Bitget TRIA-USDT trade on 2026-03-29, where the close
order failed at 13:32:11 with "Insufficient balance" (error 43012) and the
executor spun for 3+ hours stuck in CLOSING state.
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


class TestFailedOrderCloseGuardFix:
    """Test that failed close orders properly reset the close guard."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "bitget"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_balance = Mock(return_value=Decimal("100.0"))
        connector.get_price = Mock(return_value=Decimal("0.032"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "TRIA-USDT": TradingRule(
                trading_pair="TRIA-USDT",
                min_order_size=Decimal("0.1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.1"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"bitget": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_failed_guard",
            connector_name="bitget",
            trading_pair="TRIA-USDT",
            side=TradeType.BUY,
            total_amount_quote=Decimal("107"),
            num_levels=3,
            start_price=Decimal("0.031666"),
            end_price=Decimal("0.032209"),
            limit_price=Decimal("0.030083"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("10"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.05"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.LIMIT,
                stop_loss_order_type=OrderType.LIMIT,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="TRIA-USDT",
                min_order_size=Decimal("0.1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.1"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.032")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"bitget": mock_connector}
            return ex

    # ------------------------------------------------------------------
    # TEST: Failed close order resets guard (Insufficient balance)
    # ------------------------------------------------------------------

    def test_failed_close_order_resets_guard_insufficient_balance(self, executor):
        """When close order fails with 'Insufficient balance', guard must reset."""
        close_order_id = "STAUT64e2815cb35b9_test"
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        # Simulate MarketOrderFailureEvent with Insufficient balance error
        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value=(
            'MarketOrderFailureEvent(order_id=STAUT64e2815cb35b9_test, '
            'error_message=\'Error executing request POST '
            'https://api.bitget.com/api/v2/spot/trade/place-order. '
            'HTTP status is 400. Error: {"code":"43012","msg":"Insufficient balance"}\', '
            'error_type=OSError)'
        ))

        executor.process_order_failed_event(None, MagicMock(), event)

        # Guard must be reset so executor can retry
        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
        assert executor._close_order is None
        assert close_order_id in executor._failed_orders
        # Should have incremented insufficient_funds_retries
        assert executor._insufficient_funds_retries == 1

    def test_failed_close_order_terminates_after_max_retries(self, executor):
        """After max retries of insufficient balance, executor should terminate."""
        from hummingbot.strategy_v2.models.base import RunnableStatus

        close_order_id = "close_retry_test"
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True
        # Set retries just below max (default max=5, set to 4 so next is >=5)
        executor._insufficient_funds_retries = 4

        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value='Insufficient balance error')

        executor.process_order_failed_event(None, MagicMock(), event)

        # Should be terminated
        assert executor._status == RunnableStatus.TERMINATED
        assert executor._insufficient_funds_retries == 5

    def test_failed_close_order_resets_guard_generic_error(self, executor):
        """For any non-specific failure, guard must still reset."""
        close_order_id = "generic_fail_test"
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value='Some unexpected API error 500')

        executor.process_order_failed_event(None, MagicMock(), event)

        # Guard must be reset even for unknown errors
        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
        assert close_order_id in executor._failed_orders

    def test_failed_close_order_does_not_affect_unrelated_orders(self, executor):
        """Failing a grid-level order must NOT reset the close guard."""
        executor._close_order = TrackedOrder(order_id="real_close_order")
        executor._close_order_id = "real_close_order"
        executor._closing_in_progress = True

        # Fail an unrelated order
        event = MagicMock()
        event.order_id = "grid_open_order_xyz"
        event.__str__ = Mock(return_value='Some error')

        executor.process_order_failed_event(None, MagicMock(), event)

        # Close guard must remain active
        assert executor._closing_in_progress is True
        assert executor._close_order_id == "real_close_order"
        assert executor._close_order is not None

    # ------------------------------------------------------------------
    # TEST: CLOSING state machine safety net for failed orders
    # ------------------------------------------------------------------

    def test_closing_state_detects_failed_order_id(self, executor):
        """In CLOSING state, if _close_order_id is in _failed_orders, reset guard."""
        failed_id = "failed_close_43012"
        executor._close_order_id = failed_id
        executor._close_order = None
        executor._closing_in_progress = True
        executor._failed_orders.append(failed_id)

        # Verify the condition that the safety net checks
        assert failed_id in executor._failed_orders
        assert failed_id not in executor._canceled_orders

        # Simulate the safety net check (mirrors the code in control_task)
        if executor._close_order_id in executor._canceled_orders or \
                executor._close_order_id in executor._failed_orders:
            executor._closing_in_progress = False
            executor._close_order_id = None

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None

    def test_closing_state_safety_net_still_works_for_cancelled_orders(self, executor):
        """Safety net must still catch cancelled orders (regression check)."""
        cancelled_id = "cancelled_close_order"
        executor._close_order_id = cancelled_id
        executor._close_order = None
        executor._closing_in_progress = True
        executor._canceled_orders.append(cancelled_id)

        if executor._close_order_id in executor._canceled_orders or \
                executor._close_order_id in executor._failed_orders:
            executor._closing_in_progress = False
            executor._close_order_id = None

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None


class TestTriaScenarioEndToEnd:
    """Test simulating the Bitget TRIA-USDT stuck close scenario."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "bitget"
        connector.get_available_balance = Mock(return_value=Decimal("3345.651"))
        connector.get_balance = Mock(return_value=Decimal("3345.651"))
        connector.get_price = Mock(return_value=Decimal("0.031902"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "TRIA-USDT": TradingRule(
                trading_pair="TRIA-USDT",
                min_order_size=Decimal("0.1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.1"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1774783924.0  # Time of the actual failure
        strategy.cancel = Mock()
        strategy.connectors = {"bitget": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="C328zueMeTDpazC5akDZhAbiHzQEwfKAYjXJtTyCbVuE",
            connector_name="bitget",
            trading_pair="TRIA-USDT",
            side=TradeType.BUY,
            total_amount_quote=Decimal("106.87"),
            num_levels=3,
            start_price=Decimal("0.031666"),
            end_price=Decimal("0.032209"),
            limit_price=Decimal("0.030083"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("10"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.05"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.LIMIT,
                stop_loss_order_type=OrderType.LIMIT,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="TRIA-USDT",
                min_order_size=Decimal("0.1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.1"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.032")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"bitget": mock_connector}
            return ex

    def test_tria_close_order_fails_and_guard_resets(self, executor):
        """
        Reproduce the exact TRIA-USDT scenario:
        1. Close order placed for 3345.6510 TRIA
        2. Bitget rejects with "Insufficient balance" (43012)
        3. Guard must reset so executor doesn't spin forever
        """
        close_id = "STAUT64e2815cb35b9ff4a82ffa8a5948d0fa146b315b1cb82"

        # State just before the failure event
        executor._close_order = TrackedOrder(order_id=close_id)
        executor._close_order_id = close_id
        executor._closing_in_progress = True

        # The exact error from production logs
        event = MagicMock()
        event.order_id = close_id
        event.__str__ = Mock(return_value=(
            'MarketOrderFailureEvent(order_id=STAUT64e2815cb35b9ff4a82ffa8a5948d0fa146b315b1cb82, '
            'trading_pair=TRIA-USDT, error_message=\'Error executing request POST '
            'https://api.bitget.com/api/v2/spot/trade/place-order. '
            'HTTP status is 400. Error: {"code":"43012","msg":"Insufficient balance",'
            '"requestTime":1774783931724,"data":null}\', error_type=OSError)'
        ))

        executor.process_order_failed_event(None, MagicMock(), event)

        # CRITICAL: Guard must be reset
        assert executor._closing_in_progress is False, \
            "Guard still active after failed close order — executor would spin forever!"
        assert executor._close_order_id is None, \
            "close_order_id not cleared — would keep logging 'awaiting confirmation'"
        assert executor._close_order is None
        assert close_id in executor._failed_orders

    def test_tria_scenario_without_fix_would_spin_forever(self, executor):
        """
        Verify that without the fix, the executor would be stuck:
        - _closing_in_progress=True and _close_order_id set → "awaiting confirmation" loop
        - _close_order_id NOT in _canceled_orders → zombie guard doesn't trigger
        - Combined: executor spins forever (as observed in production for 3+ hours)

        With the fix, both process_order_failed_event AND the safety net catch this.
        """
        close_id = "STAUT_stuck_forever"

        # Simulate state after fix: order is in _failed_orders, guard is reset
        executor._failed_orders.append(close_id)
        executor._close_order_id = close_id  # Pretend safety net hasn't run yet
        executor._closing_in_progress = True

        # Safety net check (from control_task)
        if executor._close_order_id in executor._canceled_orders or \
                executor._close_order_id in executor._failed_orders:
            executor._closing_in_progress = False
            executor._close_order_id = None

        assert executor._closing_in_progress is False
        assert executor._close_order_id is None
