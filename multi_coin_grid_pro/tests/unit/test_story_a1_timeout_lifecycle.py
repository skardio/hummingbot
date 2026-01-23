"""
Story A1: Multi-Timeout Lifecycle Unit Tests
=============================================

Tests the professional timeout system:
- No-fill timeout (20 min default)
- No-progress timeout (1 hour default)
- Hard cap timeout (4 hours default)
- Bounded close (graceful → aggressive after 2 min)

Test Strategy:
- Direct unit tests of timeout logic
- Mock executor state and time
- Verify correct timeout triggers
- Verify bounded close escalation
- Verify idempotency (no double-triggers)
"""

import unittest
from unittest.mock import MagicMock

from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType


class MockExecutor:
    """Minimal mock executor for testing timeout logic"""

    def __init__(self):
        self._current_timestamp_value = 1000.0  # Internal timestamp storage
        self._status = RunnableStatus.RUNNING
        self._start_timestamp = 1000.0
        self._last_fill_timestamp = None
        self._last_progress_timestamp = None
        self._last_timeout_summary_log = 0.0
        self._timeout_close_triggered = False
        self._timeout_close_type = None
        self._force_aggressive_close = False
        self._closing_in_progress = False
        self._close_order_id = None
        self._close_order = None
        self.close_type = None
        self.position_size_base = 0.0  # Mock inventory

        # Mock config
        self.config = MagicMock()
        self.config.custom_info = {
            "no_fill_timeout_sec": 1200,  # 20 min
            "no_progress_timeout_sec": 3600,  # 1 hour
            "max_hold_time_sec": 14400,  # 4 hours
            "close_grace_sec": 120,  # 2 min
        }
        self.config.connector_name = "kraken"
        self.config.trading_pair = "BTC-EUR"

        # Mock connectors
        self.connectors = {"kraken": MagicMock()}
        self.connectors["kraken"].in_flight_orders = {}

        # Mock logger
        self._logger = MagicMock()

        # Mock strategy - use a simple object that returns the timestamp value
        class StrategyMock:
            def __init__(self, executor):
                self.executor = executor
                self.cancel_called = False

            @property
            def current_timestamp(self):
                return self.executor._current_timestamp_value

            def cancel(self, connector_name, trading_pair, order_id):
                """Mock cancel method"""
                self.cancel_called = True
                return None

        self._strategy = StrategyMock(self)

        # Mock levels
        self.levels_by_state = {'OPEN_ORDER_PLACED': []}

        # Mock trading rules for min_order_size check
        self.trading_rules = MagicMock()
        self.trading_rules.min_order_size = 0.001  # Default min size

    @property
    def current_timestamp(self):
        """Property to get/set current timestamp (for test compatibility)"""
        return self._current_timestamp_value

    @current_timestamp.setter
    def current_timestamp(self, value):
        """Set current timestamp (for test compatibility)"""
        self._current_timestamp_value = value

    @property
    def status(self):
        return self._status

    def logger(self):
        return self._logger

    def cancel_open_orders(self):
        pass

    def update_position_metrics(self):
        """Mock update_position_metrics for NO_FILL_TIMEOUT inventory check"""
        # position_size_base is already set in __init__, just pass
        pass

    def get_net_pnl_pct(self):
        """Mock get_net_pnl_pct for PRO timeout feature"""
        # Return a mock PnL percentage for timeout checks
        # Default to -2% (adverse) to allow timeout tests to proceed
        from decimal import Decimal
        return Decimal("-0.02")

    def start_forced_close(self, close_reason: CloseType):
        """Mock start_forced_close for B1 two-phase unwind integration"""
        self.close_type = close_reason
        self._status = RunnableStatus.CLOSING
        self._timeout_close_triggered = True
        self._timeout_close_type = close_reason

    # Import actual timeout check methods from GridExecutor
    from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
    _check_timeout_triggers = GridExecutor._check_timeout_triggers
    _check_bounded_close_escalation = GridExecutor._check_bounded_close_escalation


class TestStoryA1TimeoutLifecycle(unittest.TestCase):
    """Test suite for Story A1 multi-timeout lifecycle"""

    def setUp(self):
        """Set up test fixtures"""
        self.executor = MockExecutor()

    def test_no_fill_timeout_triggers_shutdown(self):
        """Test: No fills after 20 min → cancel orders + shutdown"""
        # Setup: No fills received
        self.executor._last_fill_timestamp = None
        self.executor._last_progress_timestamp = None

        # Advance time past no_fill_timeout (20 min = 1200s)
        self.executor.current_timestamp = 1000.0 + 1201

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: Timeout triggered
        self.assertTrue(result, "No-fill timeout should trigger")
        self.assertTrue(self.executor._timeout_close_triggered)
        self.assertEqual(self.executor._timeout_close_type, CloseType.NO_FILL_TIMEOUT)
        self.assertEqual(self.executor.close_type, CloseType.NO_FILL_TIMEOUT)
        self.assertEqual(self.executor._status, RunnableStatus.SHUTTING_DOWN)

    def test_no_fill_timeout_does_not_trigger_if_fills_received(self):
        """Test: No-fill timeout NOT triggered if fills received"""
        # Setup: Fill received at 10 minutes
        self.executor.current_timestamp = 1000.0 + 600
        self.executor._last_fill_timestamp = self.executor.current_timestamp

        # Advance time past no_fill_timeout
        self.executor.current_timestamp = 1000.0 + 1300  # Total 1300s, but only 700s since fill

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: No timeout
        self.assertFalse(result, "No-fill timeout should NOT trigger if fills received")
        self.assertFalse(self.executor._timeout_close_triggered)

    def test_no_fill_timeout_with_inventory_triggers_forced_close(self):
        """Test: No fills after 20 min BUT has inventory → start forced close (not shutdown)"""
        # Setup: No last_fill_timestamp (e.g., from inflight orders) but has inventory
        self.executor._last_fill_timestamp = None
        self.executor._last_progress_timestamp = None
        self.executor.position_size_base = 1.5  # Has inventory from partial fills

        # Advance time past no_fill_timeout (20 min = 1200s)
        self.executor.current_timestamp = 1000.0 + 1201

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: Timeout triggered, but forced close (not shutdown) due to inventory
        self.assertTrue(result, "No-fill timeout should trigger")
        self.assertTrue(self.executor._timeout_close_triggered)
        self.assertEqual(self.executor._timeout_close_type, CloseType.NO_FILL_TIMEOUT)
        self.assertEqual(self.executor.close_type, CloseType.NO_FILL_TIMEOUT)
        # Should call start_forced_close, which sets status to CLOSING (not SHUTTING_DOWN)
        self.assertEqual(self.executor._status, RunnableStatus.CLOSING)

    def test_no_progress_timeout_triggers_graceful_close(self):
        """Test: No progress after 1 hour → start graceful unwind"""
        # Setup: Had fills but no progress (no completed levels)
        self.executor._last_fill_timestamp = self.executor.current_timestamp + 100
        self.executor._last_progress_timestamp = None

        # Advance time past no_progress_timeout (1 hour = 3600s)
        self.executor.current_timestamp = 1000.0 + 3601

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: Timeout triggered, graceful close
        self.assertTrue(result, "No-progress timeout should trigger")
        self.assertTrue(self.executor._timeout_close_triggered)
        self.assertEqual(self.executor._timeout_close_type, CloseType.NO_PROGRESS_TIMEOUT)
        self.assertEqual(self.executor.close_type, CloseType.NO_PROGRESS_TIMEOUT)
        self.assertEqual(self.executor._status, RunnableStatus.CLOSING)

    def test_no_progress_timeout_reset_on_progress(self):
        """Test: Progress resets no-progress timer"""
        # Setup: Had fills to avoid no-fill timeout
        self.executor._last_fill_timestamp = 1000.0 + 100

        # Had progress recently
        self.executor.current_timestamp = 1000.0 + 3000  # 50 minutes
        self.executor._last_progress_timestamp = self.executor.current_timestamp

        # Advance time (not enough to trigger)
        self.executor.current_timestamp += 700  # Only 700s since last progress

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: No timeout
        self.assertFalse(result, "Progress should reset no-progress timer")
        self.assertFalse(self.executor._timeout_close_triggered)

    def test_hard_cap_timeout_forces_rotation(self):
        """Test: Position held > 4 hours → forced rotation"""
        # Setup: Position running for long time with some activity
        # Important: set progress timestamp to avoid triggering no_progress_timeout first
        self.executor.current_timestamp = 1000.0 + 14401
        self.executor._last_fill_timestamp = self.executor.current_timestamp - 1000  # Recent fill
        self.executor._last_progress_timestamp = self.executor.current_timestamp - 500  # Recent progress

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: Hard cap triggered
        self.assertTrue(result, "Hard cap timeout should trigger")
        self.assertTrue(self.executor._timeout_close_triggered)
        self.assertEqual(self.executor._timeout_close_type, CloseType.HARD_CAP_TIME_LIMIT)
        self.assertEqual(self.executor.close_type, CloseType.HARD_CAP_TIME_LIMIT)
        self.assertEqual(self.executor._status, RunnableStatus.CLOSING)

    def test_timeout_idempotency_guard(self):
        """Test: Timeout triggers only once (idempotent)"""
        # Setup: No fills
        self.executor._last_fill_timestamp = None

        # Advance time past no_fill_timeout
        self.executor.current_timestamp = 1000.0 + 1201

        # First trigger
        result1 = self.executor._check_timeout_triggers()
        self.assertTrue(result1)
        self.assertEqual(self.executor._timeout_close_type, CloseType.NO_FILL_TIMEOUT)

        # Second trigger (should be blocked by guard)
        result2 = self.executor._check_timeout_triggers()
        self.assertFalse(result2, "Second timeout check should be blocked by guard")

    def test_bounded_close_escalation(self):
        """Test: Graceful close fails → escalate to market order after 2 min"""
        # Setup: Timeout triggered, in CLOSING state
        self.executor._timeout_close_triggered = True
        self.executor._timeout_close_type = CloseType.NO_PROGRESS_TIMEOUT
        self.executor._status = RunnableStatus.CLOSING
        self.executor._force_aggressive_close = False
        self.executor._closing_in_progress = True  # Important: close in progress

        # Mock stuck close order
        order_id = "test_order_123"
        self.executor._close_order_id = order_id
        self.executor._close_order = MagicMock()  # Must set this too
        mock_order = MagicMock()
        mock_order.is_done = False
        mock_order.creation_timestamp = self.executor.current_timestamp
        self.executor.connectors["kraken"].in_flight_orders[order_id] = mock_order

        # Advance time past close_grace_sec (2 min = 120s)
        self.executor.current_timestamp += 121
        mock_order.creation_timestamp = self.executor.current_timestamp - 121

        # Trigger bounded close check
        result = self.executor._check_bounded_close_escalation()

        # Verify: Escalation triggered
        self.assertTrue(result, "Bounded close should escalate after grace period")
        self.assertTrue(self.executor._force_aggressive_close)
        self.assertFalse(self.executor._closing_in_progress)
        self.assertIsNone(self.executor._close_order_id)

    def test_bounded_close_does_not_escalate_if_filled(self):
        """Test: Bounded close does NOT escalate if order filled"""
        # Setup: Timeout triggered, in CLOSING state
        self.executor._timeout_close_triggered = True
        self.executor._status = RunnableStatus.CLOSING

        # Mock filled close order
        order_id = "test_order_123"
        self.executor._close_order_id = order_id
        mock_order = MagicMock()
        mock_order.is_done = True
        mock_order.is_filled = True
        mock_order.creation_timestamp = self.executor.current_timestamp - 150
        self.executor.connectors["kraken"].in_flight_orders[order_id] = mock_order

        # Advance time past grace period
        self.executor.current_timestamp += 150

        # Trigger bounded close check
        result = self.executor._check_bounded_close_escalation()

        # Verify: No escalation (order filled)
        self.assertFalse(result, "Bounded close should NOT escalate if order filled")
        self.assertFalse(self.executor._force_aggressive_close)

    def test_bounded_close_only_for_timeout_closes(self):
        """Test: Bounded close only applies to timeout-triggered closes"""
        # Setup: Regular close (not timeout-triggered)
        self.executor._timeout_close_triggered = False
        self.executor._status = RunnableStatus.CLOSING

        # Mock stuck order
        order_id = "test_order_123"
        self.executor._close_order_id = order_id
        mock_order = MagicMock()
        mock_order.is_done = False
        mock_order.creation_timestamp = self.executor.current_timestamp - 150
        self.executor.connectors["kraken"].in_flight_orders[order_id] = mock_order

        # Trigger bounded close check
        result = self.executor._check_bounded_close_escalation()

        # Verify: No escalation (not timeout-triggered)
        self.assertFalse(result, "Bounded close should only apply to timeout closes")

    def test_timeout_check_skips_if_not_running(self):
        """Test: Timeout checks skip if executor not in RUNNING state"""
        # Setup: Executor in CLOSING state
        self.executor._status = RunnableStatus.CLOSING
        self.executor._last_fill_timestamp = None

        # Advance time past all timeouts
        self.executor.current_timestamp = 1000.0 + 15000

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: No timeout triggered (not in RUNNING state)
        self.assertFalse(result, "Timeout should not trigger if not RUNNING")
        self.assertFalse(self.executor._timeout_close_triggered)

    def test_disabled_timeout_config(self):
        """Test: Timeout checks disabled if config = 0"""
        # Setup: Disable all timeouts
        self.executor.config.custom_info = {
            "no_fill_timeout_sec": 0,  # Disabled
            "no_progress_timeout_sec": 0,  # Disabled
            "max_hold_time_sec": 0,  # Disabled
            "close_grace_sec": 120,
        }
        self.executor._last_fill_timestamp = None

        # Advance time significantly
        self.executor.current_timestamp = 1000.0 + 20000

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: No timeout (all disabled)
        self.assertFalse(result, "Timeouts should be disabled when config = 0")
        self.assertFalse(self.executor._timeout_close_triggered)

    def test_timeout_priority_no_fill_over_no_progress(self):
        """Test: No-fill timeout has priority over no-progress timeout"""
        # Setup: Both timeouts would trigger
        self.executor._last_fill_timestamp = None
        self.executor._last_progress_timestamp = None

        # Advance time past both timeouts
        self.executor.current_timestamp = 1000.0 + 4000  # Past both

        # Trigger timeout check
        result = self.executor._check_timeout_triggers()

        # Verify: No-fill timeout triggered first
        self.assertTrue(result)
        self.assertEqual(self.executor._timeout_close_type, CloseType.NO_FILL_TIMEOUT)
        self.assertEqual(self.executor._status, RunnableStatus.SHUTTING_DOWN)


if __name__ == '__main__':
    unittest.main()
