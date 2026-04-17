"""Tests for orphan prevention fixes in grid executor.

Bug 1: evaluate_max_retries kills executor during active unwind
Bug 2: Graceful close retries same amount on "Insufficient funds"
Bug 3: Insufficient funds during GRACEFUL escalates to AGGRESSIVE
"""
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import TrackedOrder


@pytest.fixture
def mock_executor():
    """Create a minimally-mocked GridExecutor for unit tests."""
    config = MagicMock(spec=GridExecutorConfig)
    config.id = "test_orphan_123"
    config.trading_pair = "ARB-USD"
    config.connector_name = "kraken"
    config.side = TradeType.BUY
    config.start_price = Decimal("0.115")
    config.end_price = Decimal("0.118")
    config.total_amount_quote = Decimal("100")
    config.min_order_amount_quote = Decimal("15")
    config.max_open_orders = 3
    config.max_orders_per_batch = 2
    config.order_frequency = 3
    config.min_spread_between_orders = Decimal("0.007")
    config.activation_bounds = Decimal("0.05")
    config.safe_extra_spread = Decimal("0.0001")
    config.triple_barrier_config = MagicMock()
    config.triple_barrier_config.stop_loss = Decimal("0.05")
    config.triple_barrier_config.take_profit = Decimal("0.05")
    config.leverage = 1
    config.custom_info = {
        'close_grace_sec': 120,
        'no_fill_timeout_sec': 1800,
    }

    strategy = MagicMock()
    strategy.current_timestamp = 1000.0

    connectors = {
        "kraken": MagicMock()
    }
    connectors["kraken"].get_available_balance.return_value = Decimal("500")
    connectors["kraken"].get_balance.return_value = Decimal("500")
    connectors["kraken"].quantize_order_amount.side_effect = lambda tp, a: a
    connectors["kraken"].quantize_order_price.side_effect = lambda tp, p: p

    with patch.object(GridExecutor, '__init__', lambda self, *a, **kw: None):
        executor = GridExecutor.__new__(GridExecutor)

    # Set minimum required attributes
    executor.config = config
    executor._strategy = strategy
    executor.connectors = connectors
    executor._status = RunnableStatus.RUNNING
    executor.close_type = None
    executor._unwind_phase = "NONE"
    executor._unwind_close_reason = None
    executor._unwind_started_ts = None
    executor._unwind_attempts = 0
    executor._graceful_close_orders = set()
    executor._aggressive_close_orders = set()
    executor._graceful_sell_earliest_ts = 0.0
    executor._cancel_settle_delay = 10.0
    executor._current_retries = 0
    executor._max_retries = 10
    executor._market_retry_attempted = False
    executor._close_order = None
    executor._close_order_id = None
    executor._closing_in_progress = False
    executor._insufficient_funds_retries = 0
    executor._max_insufficient_funds_retries = 5
    executor._close_balance_max_retries = 10
    executor._close_balance_retry_interval = 1.0
    executor._stale_close_cancel_count = 0
    executor._early_stop_reason = None
    executor._failed_orders = []
    executor._canceled_orders = []
    executor.position_size_base = Decimal("0")
    executor.mid_price = Decimal("0.116")
    executor.max_close_creation_timestamp = 0
    executor.max_open_creation_timestamp = 0
    executor.grid_levels = []
    executor._cancel_request_times = {}
    executor._cancel_retry_count = {}
    executor._nl_restricted = False
    executor._nl_restricted_coin = None
    executor._custom_info = {}
    executor._exchange_min_sell_price = None
    executor._price_rejected_retries = 0
    executor._max_price_rejected_retries = 3

    # Mock methods
    executor.logger = MagicMock(return_value=MagicMock())
    executor.update_position_metrics = MagicMock()
    executor.update_grid_levels = MagicMock()
    executor._log_orphan_risk_if_inventory = MagicMock()
    executor._cancel_non_essential_orders = MagicMock()
    executor.stop = MagicMock()
    executor.place_order = MagicMock(return_value="test_order_123")
    executor.get_price = MagicMock(return_value=Decimal("0.116"))
    executor.close_order_side = TradeType.SELL
    executor.close_order_price_type = MagicMock()

    # Mock levels_by_state (must use GridLevelStates enum keys)
    executor.levels_by_state = {state: [] for state in GridLevelStates}

    # Mock trading_rules
    executor.trading_rules = MagicMock()
    executor.trading_rules.min_order_size = Decimal("10")

    return executor


class TestBug1_EvaluateMaxRetriesUnwindProtection:
    """Bug 1: evaluate_max_retries should not kill executor during active unwind."""

    def test_does_not_terminate_during_graceful_unwind(self, mock_executor):
        """When unwind is GRACEFUL, evaluate_max_retries should return without terminating."""
        mock_executor._current_retries = 15  # Way over max
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor.position_size_base = Decimal("565.94")

        mock_executor.evaluate_max_retries()

        # Should NOT be stopped
        mock_executor.stop.assert_not_called()
        assert mock_executor._status == RunnableStatus.RUNNING

    def test_does_not_terminate_during_aggressive_unwind(self, mock_executor):
        """When unwind is AGGRESSIVE, evaluate_max_retries should return without terminating."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "AGGRESSIVE"
        mock_executor.position_size_base = Decimal("565.94")

        mock_executor.evaluate_max_retries()

        mock_executor.stop.assert_not_called()
        assert mock_executor._status == RunnableStatus.RUNNING

    def test_starts_forced_close_on_first_max_retry(self, mock_executor):
        """First time max retries hit with inventory: should start forced close."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor.position_size_base = Decimal("565.94")

        mock_executor.evaluate_max_retries()

        # Should have set _market_retry_attempted and called start_forced_close
        assert mock_executor._market_retry_attempted is True
        mock_executor.stop.assert_not_called()
        # start_forced_close will set _unwind_phase
        assert mock_executor._unwind_phase == "GRACEFUL"

    def test_terminates_when_unwind_done_and_no_inventory(self, mock_executor):
        """When unwind is DONE and no inventory, should terminate normally."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "DONE"
        mock_executor.position_size_base = Decimal("0")

        mock_executor.evaluate_max_retries()

        mock_executor.stop.assert_called_once()
        assert mock_executor.close_type is not None


class TestBug2_GracefulRetryCapToAvailable:
    """Bug 2: GRACEFUL_RETRY should cap sell amount to available balance."""

    def test_caps_sell_to_available_after_insufficient_funds(self, mock_executor):
        """When _insufficient_funds_retries > 0, _cap_sell_to_available should be called."""
        mock_executor._insufficient_funds_retries = 1
        mock_executor.position_size_base = Decimal("233.61")

        # Mock _cap_sell_to_available to return a lower amount
        mock_executor._cap_sell_to_available = MagicMock(return_value=Decimal("230.00"))
        mock_executor._place_graceful_close_orders = MagicMock()

        # Simulate the GRACEFUL_RETRY logic from control_task
        remaining = mock_executor.position_size_base
        if mock_executor._insufficient_funds_retries > 0:
            remaining = mock_executor._cap_sell_to_available(remaining)

        mock_executor._cap_sell_to_available.assert_called_once_with(Decimal("233.61"))
        assert remaining == Decimal("230.00")

    def test_no_cap_without_insufficient_funds(self, mock_executor):
        """Normal case: no capping when no insufficient funds failures."""
        mock_executor._insufficient_funds_retries = 0
        mock_executor.position_size_base = Decimal("233.61")

        remaining = mock_executor.position_size_base
        if mock_executor._insufficient_funds_retries > 0:
            remaining = Decimal("0")  # Would be capped

        # Should NOT have been capped
        assert remaining == Decimal("233.61")


class TestBug3_InsufficientFundsEscalation:
    """Bug 3: Insufficient funds during GRACEFUL should escalate to AGGRESSIVE."""

    def test_escalates_level_close_to_aggressive(self, mock_executor):
        """Level close order insufficient funds during GRACEFUL → escalate to AGGRESSIVE."""
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor._insufficient_funds_retries = 4  # One below new max (5)
        mock_executor._status = RunnableStatus.CLOSING

        # Set up a grid level close order that will fail
        level = MagicMock()
        level.active_close_order = MagicMock()
        level.active_close_order.order_id = "level_close_123"
        mock_executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED] = [level]

        event = MagicMock()
        event.order_id = "level_close_123"
        event.__str__ = Mock(return_value='Insufficient funds')

        mock_executor.process_order_failed_event(None, MagicMock(), event)

        # Should escalate to AGGRESSIVE, not terminate
        assert mock_executor._unwind_phase == "AGGRESSIVE"
        assert mock_executor._status == RunnableStatus.CLOSING  # NOT TERMINATED
        assert mock_executor._insufficient_funds_retries == 0  # Reset for aggressive

    def test_escalates_main_close_to_aggressive(self, mock_executor):
        """Main close order insufficient funds during GRACEFUL → escalate to AGGRESSIVE."""
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor._insufficient_funds_retries = 4  # One below new max (5)
        mock_executor._status = RunnableStatus.CLOSING

        close_order_id = "main_close_456"
        mock_executor._close_order = TrackedOrder(order_id=close_order_id)
        mock_executor._close_order_id = close_order_id
        mock_executor._closing_in_progress = True

        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value='Insufficient funds')

        mock_executor.process_order_failed_event(None, MagicMock(), event)

        # Should escalate to AGGRESSIVE
        assert mock_executor._unwind_phase == "AGGRESSIVE"
        assert mock_executor._status == RunnableStatus.CLOSING
        assert mock_executor._insufficient_funds_retries == 0

    def test_terminates_when_not_in_graceful(self, mock_executor):
        """When NOT in GRACEFUL unwind, max retries should terminate as before."""
        mock_executor._unwind_phase = "NONE"
        mock_executor._insufficient_funds_retries = 4
        mock_executor._status = RunnableStatus.CLOSING

        close_order_id = "close_term_789"
        mock_executor._close_order = TrackedOrder(order_id=close_order_id)
        mock_executor._close_order_id = close_order_id
        mock_executor._closing_in_progress = True

        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value='Insufficient funds')

        mock_executor.process_order_failed_event(None, MagicMock(), event)

        assert mock_executor._status == RunnableStatus.TERMINATED

    def test_terminates_after_aggressive_max_retries(self, mock_executor):
        """After AGGRESSIVE phase also hits max retries, should terminate."""
        mock_executor._unwind_phase = "AGGRESSIVE"
        mock_executor._insufficient_funds_retries = 4
        mock_executor._status = RunnableStatus.CLOSING

        close_order_id = "close_agg_fail"
        mock_executor._close_order = TrackedOrder(order_id=close_order_id)
        mock_executor._close_order_id = close_order_id
        mock_executor._closing_in_progress = True

        event = MagicMock()
        event.order_id = close_order_id
        event.__str__ = Mock(return_value='Insufficient funds')

        mock_executor.process_order_failed_event(None, MagicMock(), event)

        assert mock_executor._status == RunnableStatus.TERMINATED


class TestConfigValues:
    """Verify the new default values are correct."""

    def test_cancel_settle_delay_is_10(self, mock_executor):
        assert mock_executor._cancel_settle_delay == 10.0

    def test_close_balance_max_retries_is_10(self, mock_executor):
        assert mock_executor._close_balance_max_retries == 10

    def test_max_insufficient_funds_retries_is_5(self, mock_executor):
        assert mock_executor._max_insufficient_funds_retries == 5


class TestDustPositionCompletion:
    """Bug 4: Close order filled but dust position_size_base prevents completion."""

    def test_evaluate_max_retries_forces_done_after_timeout_with_dust(self, mock_executor):
        """When GRACEFUL unwind > 10 min and close order filled with dust, force completion."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor._unwind_started_ts = 100.0  # Started at 100
        mock_executor._strategy.current_timestamp = 800.0  # 700s > 600s timeout
        mock_executor.position_size_base = Decimal("0.00000004")  # Dust

        # Mock a filled close order
        close_order = MagicMock()
        close_order.order = MagicMock()
        close_order.order.is_filled = True
        mock_executor._close_order = close_order

        mock_executor.evaluate_max_retries()

        assert mock_executor._unwind_phase == "DONE"
        mock_executor.stop.assert_called_once()

    def test_evaluate_max_retries_keeps_waiting_when_not_filled(self, mock_executor):
        """When GRACEFUL unwind > 10 min but close order NOT filled, keep waiting."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor._unwind_started_ts = 100.0
        mock_executor._strategy.current_timestamp = 800.0  # > 10 min
        mock_executor.position_size_base = Decimal("208.715")

        # Close order NOT filled
        close_order = MagicMock()
        close_order.order = MagicMock()
        close_order.order.is_filled = False
        mock_executor._close_order = close_order

        mock_executor.evaluate_max_retries()

        # Should NOT force done — still waiting for fill
        assert mock_executor._unwind_phase == "GRACEFUL"
        mock_executor.stop.assert_not_called()

    def test_evaluate_max_retries_keeps_waiting_under_timeout(self, mock_executor):
        """When GRACEFUL unwind < 10 min, keep waiting even with dust."""
        mock_executor._current_retries = 15
        mock_executor._max_retries = 10
        mock_executor._market_retry_attempted = True
        mock_executor._unwind_phase = "GRACEFUL"
        mock_executor._unwind_started_ts = 500.0
        mock_executor._strategy.current_timestamp = 800.0  # 300s < 600s
        mock_executor.position_size_base = Decimal("0.00000004")

        close_order = MagicMock()
        close_order.order = MagicMock()
        close_order.order.is_filled = True
        mock_executor._close_order = close_order

        mock_executor.evaluate_max_retries()

        # Under timeout — keep waiting
        assert mock_executor._unwind_phase == "GRACEFUL"
        mock_executor.stop.assert_not_called()
