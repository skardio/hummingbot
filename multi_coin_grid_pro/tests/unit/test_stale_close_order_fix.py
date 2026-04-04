"""
Tests for the stale close order timeout fix.

Bug: When a close order (limit sell) is placed during the unwind protocol,
it can sit unfilled on the exchange indefinitely. The executor logs
"Close order still pending" every second but never cancels or re-places it.

Observed in production: Kraken XDC-USD on 2026-03-30, where the aggressive
close order 813053652 was placed at 10:06 and remained OPEN for 2.5+ hours
with the executor stuck in a "Close order still pending" loop.

Fix:
1. STALE CLOSE ORDER TIMEOUT: If a close order has been pending for longer
   than stale_close_timeout_sec (default 300s), cancel it. The
   process_order_canceled_event handler resets _close_order/_close_order_id.
2. AGGRESSIVE RETRY: When in AGGRESSIVE unwind phase with no active close
   order (after cancel or failed placement), automatically re-place the
   aggressive close order instead of just logging "waiting".
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import TrackedOrder


class TestStaleCloseOrderFix:
    """Test that stale close orders are cancelled and re-placed."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("200.0"))
        connector.get_balance = Mock(return_value=Decimal("200.0"))
        connector.get_price = Mock(return_value=Decimal("0.0315"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "XDC-USD": TradingRule(
                trading_pair="XDC-USD",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 10000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_stale_close",
            connector_name="kraken",
            trading_pair="XDC-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("94"),
            num_levels=3,
            start_price=Decimal("0.03127"),
            end_price=Decimal("0.03158"),
            limit_price=Decimal("0.02970"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("15"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.05"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.LIMIT,
                stop_loss_order_type=OrderType.LIMIT,
            ),
            custom_info={
                'stale_close_timeout_sec': 300,
                'close_grace_sec': 120,
            },
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="XDC-USD",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.01"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.0315")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"kraken": mock_connector}
            return ex

    # ------------------------------------------------------------------
    # Part 1: Stale close order detection and cancel
    # ------------------------------------------------------------------

    def test_stale_close_order_init_counter(self, executor):
        """Verify _stale_close_cancel_count is initialized to 0."""
        assert executor._stale_close_cancel_count == 0

    def test_stale_close_order_cancelled_after_timeout(self, executor, mock_strategy):
        """Close order pending > stale_close_timeout_sec must be cancelled."""
        close_order_id = "stale_close_813053652"
        executor._status = RunnableStatus.CLOSING
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True
        executor._unwind_phase = "AGGRESSIVE"

        # Create a mock in-flight order that's been open for 400s (> 300s timeout)
        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.is_filled = False
        mock_in_flight.is_cancelled = False
        mock_in_flight.is_failure = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 400

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {close_order_id: mock_in_flight}

        # Mock _check_unwind_phase_transition and _check_bounded_close_escalation
        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # Strategy.cancel should have been called for the stale order
        mock_strategy.cancel.assert_called_once_with(
            connector_name="kraken",
            trading_pair="XDC-USD",
            order_id=close_order_id
        )
        assert executor._stale_close_cancel_count == 1

    def test_stale_close_order_not_cancelled_before_timeout(self, executor, mock_strategy):
        """Close order pending < stale_close_timeout_sec must NOT be cancelled."""
        close_order_id = "young_close_order"
        executor._status = RunnableStatus.CLOSING
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        # Order has been open for only 60s (< 300s timeout)
        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 60

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {close_order_id: mock_in_flight}

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        mock_strategy.cancel.assert_not_called()
        assert executor._stale_close_cancel_count == 0

    def test_stale_close_timeout_configurable(self, executor, mock_strategy):
        """Custom stale_close_timeout_sec is respected."""
        executor.config.custom_info['stale_close_timeout_sec'] = 600

        close_order_id = "custom_timeout_order"
        executor._status = RunnableStatus.CLOSING
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        # Order has been open for 400s (> 300 default but < 600 custom)
        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 400

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {close_order_id: mock_in_flight}

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # Should NOT cancel — 400s < 600s custom timeout
        mock_strategy.cancel.assert_not_called()

    def test_stale_close_cancel_count_increments(self, executor, mock_strategy):
        """Cancel count increments on each stale cancel."""
        executor._stale_close_cancel_count = 2  # Already cancelled twice

        close_order_id = "third_stale_cancel"
        executor._status = RunnableStatus.CLOSING
        executor._close_order = TrackedOrder(order_id=close_order_id)
        executor._close_order_id = close_order_id
        executor._closing_in_progress = True

        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 500

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {close_order_id: mock_in_flight}

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        assert executor._stale_close_cancel_count == 3

    # ------------------------------------------------------------------
    # Part 2: Aggressive retry (re-place order after cancel)
    # ------------------------------------------------------------------

    def test_aggressive_retry_replaces_order_when_no_close_active(self, executor):
        """In AGGRESSIVE phase with no close order, must re-place."""
        executor._status = RunnableStatus.CLOSING
        executor._unwind_phase = "AGGRESSIVE"
        executor._closing_in_progress = False
        executor._close_order_id = None
        executor._close_order = None

        # Has remaining inventory
        executor.position_size_base = Decimal("1994.27")

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False), \
             patch.object(executor, 'update_position_metrics'), \
             patch.object(executor, '_place_aggressive_close_orders', new_callable=AsyncMock) as mock_place:
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        mock_place.assert_called_once_with(Decimal("1994.27"))
        assert executor._closing_in_progress is True

    def test_aggressive_retry_transitions_to_shutting_down_when_no_inventory(self, executor):
        """In AGGRESSIVE phase with no inventory, transition to SHUTTING_DOWN."""
        executor._status = RunnableStatus.CLOSING
        executor._unwind_phase = "AGGRESSIVE"
        executor._closing_in_progress = False
        executor._close_order_id = None
        executor._close_order = None

        # No remaining inventory
        executor.position_size_base = Decimal("0")

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False), \
             patch.object(executor, 'update_position_metrics'):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        assert executor._status == RunnableStatus.SHUTTING_DOWN
        assert executor._unwind_phase == "DONE"
        assert executor._closing_in_progress is False

    def test_aggressive_retry_does_not_trigger_when_close_order_active(self, executor, mock_strategy):
        """If close order IS active, AGGRESSIVE_RETRY must NOT trigger."""
        close_order_id = "active_aggressive_order"
        executor._status = RunnableStatus.CLOSING
        executor._unwind_phase = "AGGRESSIVE"
        executor._closing_in_progress = True
        executor._close_order_id = close_order_id
        executor._close_order = TrackedOrder(order_id=close_order_id)

        # Order still pending but not stale (only 30s old)
        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 30

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {close_order_id: mock_in_flight}

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False), \
             patch.object(executor, '_place_aggressive_close_orders', new_callable=AsyncMock) as mock_place:
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # Must NOT re-place — there's already an active order
        mock_place.assert_not_called()

    def test_graceful_phase_does_not_trigger_aggressive_retry(self, executor):
        """In GRACEFUL phase with no close order, must NOT trigger AGGRESSIVE retry."""
        executor._status = RunnableStatus.CLOSING
        executor._unwind_phase = "GRACEFUL"
        executor._closing_in_progress = False
        executor._close_order_id = None
        executor._close_order = None

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False), \
             patch.object(executor, '_place_aggressive_close_orders', new_callable=AsyncMock) as mock_place:
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # GRACEFUL phase should NOT trigger aggressive retry
        mock_place.assert_not_called()


class TestStaleCloseEndToEnd:
    """End-to-end scenario: XDC-USD stale close order → cancel → retry."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("200.0"))
        connector.get_balance = Mock(return_value=Decimal("1994.27"))
        connector.get_price = Mock(return_value=Decimal("0.0315"))
        connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
        connector.quantize_order_price = Mock(side_effect=lambda p, pr: pr)
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "XDC-USD": TradingRule(
                trading_pair="XDC-USD",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 10000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_xdc_e2e",
            connector_name="kraken",
            trading_pair="XDC-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("94"),
            num_levels=3,
            start_price=Decimal("0.03127"),
            end_price=Decimal("0.03158"),
            limit_price=Decimal("0.02970"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("15"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.05"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.LIMIT,
                stop_loss_order_type=OrderType.LIMIT,
            ),
            custom_info={
                'stale_close_timeout_sec': 300,
            },
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch.object(
            GridExecutor,
            "get_trading_rules",
            return_value=TradingRule(
                trading_pair="XDC-USD",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.000001"),
                min_base_amount_increment=Decimal("0.01"),
            ),
        ), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.0315")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            ex = GridExecutor(mock_strategy, grid_config)
            ex._strategy = mock_strategy
            ex.connectors = {"kraken": mock_connector}
            return ex

    def test_xdc_scenario_stale_cancel_then_aggressive_retry(self, executor, mock_strategy):
        """
        Reproduce XDC-USD scenario:
        1. Executor in CLOSING/AGGRESSIVE with stale limit sell (>300s)
        2. Stale detection cancels the order
        3. process_order_canceled_event resets state
        4. Next control_task: AGGRESSIVE_RETRY re-places the order
        """
        from hummingbot.core.event.events import OrderCancelledEvent

        stale_order_id = "813053652"
        executor._status = RunnableStatus.CLOSING
        executor._unwind_phase = "AGGRESSIVE"
        executor._close_order = TrackedOrder(order_id=stale_order_id)
        executor._close_order_id = stale_order_id
        executor._closing_in_progress = True
        executor._timeout_close_triggered = True

        # Step 1: Simulate stale order (400s old)
        mock_in_flight = MagicMock()
        mock_in_flight.is_done = False
        mock_in_flight.current_state = "OPEN"
        mock_in_flight.creation_timestamp = mock_strategy.current_timestamp - 400

        mock_connector = executor.connectors["kraken"]
        mock_connector.in_flight_orders = {stale_order_id: mock_in_flight}

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False):
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # Verify: cancel was called
        mock_strategy.cancel.assert_called_once_with(
            connector_name="kraken",
            trading_pair="XDC-USD",
            order_id=stale_order_id
        )
        assert executor._stale_close_cancel_count == 1

        # Step 2: Simulate cancel event (as exchange would fire)
        cancel_event = MagicMock(spec=OrderCancelledEvent)
        cancel_event.order_id = stale_order_id
        executor.process_order_canceled_event(None, mock_connector, cancel_event)

        # Verify: state reset
        assert executor._close_order is None
        assert executor._close_order_id is None
        assert executor._closing_in_progress is False
        assert executor._unwind_phase == "AGGRESSIVE"  # Phase unchanged

        # Step 3: Next control_task should trigger AGGRESSIVE_RETRY
        executor.position_size_base = Decimal("1994.27")
        mock_connector.in_flight_orders = {}  # Order is gone

        with patch.object(executor, '_check_unwind_phase_transition', new_callable=AsyncMock), \
             patch.object(executor, '_check_bounded_close_escalation', return_value=False), \
             patch.object(executor, 'update_position_metrics'), \
             patch.object(executor, '_place_aggressive_close_orders', new_callable=AsyncMock) as mock_place:
            asyncio.get_event_loop().run_until_complete(executor.control_task())

        # Verify: aggressive retry placed new order
        mock_place.assert_called_once_with(Decimal("1994.27"))
        assert executor._closing_in_progress is True
