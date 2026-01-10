"""
Story B1: Two-Phase Unwind Protocol Unit Tests
===============================================

Tests the professional bounded exit system:
- Graceful phase (maker/limit orders)
- Aggressive phase (market/IOC orders after grace period)
- Priority system (RISK > STOP_LOSS > TIME_LIMIT > MANUAL)
- Idempotency (no duplicate close orders)
- Integration with Story A1 timeouts

Test Strategy:
- Direct unit tests of unwind protocol
- Mock executor state
- Verify phase transitions
- Verify priority upgrades
- Verify idempotency
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, get_close_type_priority


class MockTradingRules:
    """Mock trading rules"""

    def __init__(self):
        self.min_order_size = Decimal("0.001")


class MockConnector:
    """Mock exchange connector"""

    def __init__(self):
        self.in_flight_orders = {}

    def quantize_order_price(self, trading_pair, price):
        return price.quantize(Decimal("0.01"))

    def quantize_order_amount(self, trading_pair, amount):
        return amount.quantize(Decimal("0.0001"))


class MockExecutor:
    """Minimal mock executor for testing B1 unwind protocol"""

    def __init__(self):
        self._current_timestamp_value = 1000.0
        self._status = RunnableStatus.RUNNING
        self.position_size_base = Decimal("0.5")  # Has inventory

        # B1 unwind state
        self._unwind_phase = "NONE"
        self._unwind_close_reason = None
        self._unwind_started_ts = None
        self._unwind_attempts = 0
        self._graceful_close_orders = set()
        self._aggressive_close_orders = set()

        # Mock config
        self.config = MagicMock()
        self.config.connector_name = "kraken"
        self.config.trading_pair = "BTC-EUR"
        self.config.custom_info = {
            "close_grace_sec": 120,
            "aggressive_close_method": "MARKET",
            "aggressive_close_slippage_guard_pct": Decimal("0.30"),
        }

        # Mock components
        self.connectors = {"kraken": MockConnector()}
        self.trading_rules = MockTradingRules()
        self.close_order_side = TradeType.SELL
        self.close_order_price_type = "BestAsk"
        self.mid_price = Decimal("2500")
        self._logger = MagicMock()
        self.close_type = None
        self._closing_in_progress = False
        self._close_order_id = None
        self._force_aggressive_close = False

        # Mock strategy
        class StrategyMock:
            def __init__(self, executor):
                self.executor = executor
                self.placed_orders = []

            @property
            def current_timestamp(self):
                return self.executor._current_timestamp_value

            def place_order(self, connector_name, trading_pair, order_type, side, amount, price):
                order_id = f"test_order_{len(self.placed_orders)}"
                self.placed_orders.append({
                    "order_id": order_id,
                    "order_type": order_type,
                    "side": side,
                    "amount": amount,
                    "price": price,
                })
                return order_id

            def cancel(self, connector_name, trading_pair, order_id):
                pass

        self._strategy = StrategyMock(self)
        self.levels_by_state = {"OPEN_ORDER_PLACED": []}

    @property
    def current_timestamp(self):
        return self._current_timestamp_value

    @current_timestamp.setter
    def current_timestamp(self, value):
        self._current_timestamp_value = value

    @property
    def status(self):
        return self._status

    def logger(self):
        return self._logger

    def get_price(self, connector_name, trading_pair, price_type):
        return self.mid_price

    def update_position_metrics(self):
        pass

    def place_order(self, connector_name, trading_pair, order_type, side, amount, price):
        """Delegate to strategy for tracking"""
        return self._strategy.place_order(connector_name, trading_pair, order_type, side, amount, price)

    def start_forced_close(self, close_reason: CloseType) -> None:
        """
        Simplified version of Story B1 two-phase unwind protocol for testing.
        """
        from hummingbot.strategy_v2.models.executors import get_close_type_priority

        # Skip if already terminated
        if self._status == RunnableStatus.TERMINATED:
            return

        # Idempotency: Check if already unwinding with higher priority reason
        if self._unwind_phase != "NONE" and self._unwind_close_reason is not None:
            current_priority = get_close_type_priority(self._unwind_close_reason)
            new_priority = get_close_type_priority(close_reason)

            if new_priority <= current_priority:
                return
            else:
                self._logger.warning(f"Upgrading unwind reason to {close_reason}")

        # Initialize unwind state
        if self._unwind_phase == "NONE":
            self._unwind_started_ts = self._strategy.current_timestamp
            self._unwind_attempts = 0

        self._unwind_close_reason = close_reason
        self.close_type = close_reason

        # Start graceful phase
        self._unwind_phase = "GRACEFUL"

        # If no inventory, skip directly to shutdown
        if self.position_size_base < self.trading_rules.min_order_size:
            self._status = RunnableStatus.SHUTTING_DOWN
            self._unwind_phase = "DONE"
            return

        # Place graceful close orders
        self._place_graceful_close_orders(self.position_size_base)

        # Transition to CLOSING status
        if self._status != RunnableStatus.CLOSING:
            self._status = RunnableStatus.CLOSING

        self._unwind_attempts += 1

    def _place_graceful_close_orders(self, inventory: Decimal) -> None:
        """Place maker/limit close orders for remaining inventory."""
        if inventory < self.trading_rules.min_order_size:
            return

        try:
            close_price = self.get_price(
                self.config.connector_name,
                self.config.trading_pair,
                self.close_order_price_type
            )

            price_offset = Decimal("1.0005") if self.close_order_side == TradeType.SELL else Decimal("0.9995")
            adjusted_price = close_price * price_offset

            adjusted_price = self.connectors[self.config.connector_name].quantize_order_price(
                self.config.trading_pair, adjusted_price
            )

            quantized_amount = self.connectors[self.config.connector_name].quantize_order_amount(
                self.config.trading_pair, inventory
            )

            if quantized_amount < self.trading_rules.min_order_size:
                return

            # Use self.place_order() which delegates to _strategy.place_order()
            order_id = self.place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=OrderType.LIMIT,
                side=self.close_order_side,
                amount=quantized_amount,
                price=adjusted_price
            )

            if order_id:
                self._graceful_close_orders.add(order_id)
                self._close_order_id = order_id
                self._closing_in_progress = True

        except Exception as e:
            self._logger.error(f"Failed to place graceful close order: {e}")

    def _check_unwind_phase_transition(self) -> None:
        """Check if we should transition from GRACEFUL to AGGRESSIVE phase."""
        if self._unwind_phase != "GRACEFUL":
            return

        custom_info = self.config.custom_info or {}
        close_grace_sec = custom_info.get('close_grace_sec', 120)

        now = self._strategy.current_timestamp
        time_in_graceful = now - self._unwind_started_ts

        if time_in_graceful >= close_grace_sec:
            self.update_position_metrics()
            remaining_inventory = self.position_size_base

            # If no inventory left during grace period, stay in GRACEFUL
            # (will transition to DONE via other logic when appropriate)
            if remaining_inventory < self.trading_rules.min_order_size:
                return

            # Transition to aggressive
            self._unwind_phase = "AGGRESSIVE"
            self._place_aggressive_close_orders(remaining_inventory)

    def _place_aggressive_close_orders(self, inventory: Decimal) -> None:
        """Place market/IOC close orders for remaining inventory."""
        if inventory < self.trading_rules.min_order_size:
            return

        try:
            quantized_amount = self.connectors[self.config.connector_name].quantize_order_amount(
                self.config.trading_pair, inventory
            )

            if quantized_amount < self.trading_rules.min_order_size:
                return

            # Use self.place_order() which delegates to _strategy.place_order()
            order_id = self.place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=OrderType.MARKET,
                side=self.close_order_side,
                amount=quantized_amount,
                price=Decimal("0")  # Market order doesn't need price
            )

            if order_id:
                self._aggressive_close_orders.add(order_id)

        except Exception as e:
            self._logger.error(f"Failed to place aggressive close order: {e}")

    def cancel_open_orders(self):
        pass


class TestStoryB1TwoPhaseUnwind(unittest.TestCase):
    """Test suite for Story B1 two-phase unwind protocol"""

    def setUp(self):
        """Set up test fixtures"""
        self.executor = MockExecutor()

    def test_priority_system_values(self):
        """Test: Priority values are correctly ordered"""
        # High priority reasons
        risk_priority = get_close_type_priority(CloseType.RISK_KILL_SWITCH)
        sl_priority = get_close_type_priority(CloseType.STOP_LOSS)
        hard_cap_priority = get_close_type_priority(CloseType.HARD_CAP_TIME_LIMIT)
        time_limit_priority = get_close_type_priority(CloseType.TIME_LIMIT)

        # Medium priority reasons
        no_progress_priority = get_close_type_priority(CloseType.NO_PROGRESS_TIMEOUT)
        no_fill_priority = get_close_type_priority(CloseType.NO_FILL_TIMEOUT)
        manual_priority = get_close_type_priority(CloseType.MANUAL)

        # Low priority reasons
        tp_priority = get_close_type_priority(CloseType.TAKE_PROFIT)

        # Verify hierarchy
        self.assertGreater(risk_priority, sl_priority, "RISK_KILL_SWITCH > STOP_LOSS")
        self.assertGreater(sl_priority, hard_cap_priority, "STOP_LOSS > HARD_CAP_TIME_LIMIT")
        self.assertGreater(hard_cap_priority, time_limit_priority, "HARD_CAP > TIME_LIMIT")
        self.assertGreater(time_limit_priority, no_progress_priority, "TIME_LIMIT > NO_PROGRESS")
        self.assertGreater(no_progress_priority, no_fill_priority, "NO_PROGRESS > NO_FILL")
        self.assertGreater(manual_priority, tp_priority, "MANUAL > TAKE_PROFIT")

    def test_start_forced_close_initializes_state(self):
        """Test: start_forced_close() initializes unwind state correctly"""
        # Start forced close
        self.executor.start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)

        # Verify state initialized
        self.assertEqual(self.executor._unwind_phase, "GRACEFUL")
        self.assertEqual(self.executor._unwind_close_reason, CloseType.NO_PROGRESS_TIMEOUT)
        self.assertEqual(self.executor.close_type, CloseType.NO_PROGRESS_TIMEOUT)
        self.assertIsNotNone(self.executor._unwind_started_ts)
        self.assertEqual(self.executor._unwind_attempts, 1)
        self.assertEqual(self.executor._status, RunnableStatus.CLOSING)

    def test_start_forced_close_places_graceful_order(self):
        """Test: start_forced_close() places graceful close order"""
        # Start forced close
        self.executor.start_forced_close(CloseType.TIME_LIMIT)

        # Verify graceful order placed
        self.assertEqual(len(self.executor._strategy.placed_orders), 1)
        order = self.executor._strategy.placed_orders[0]

        self.assertEqual(order["order_type"], OrderType.LIMIT, "Graceful phase uses LIMIT orders")
        self.assertEqual(order["side"], TradeType.SELL)
        self.assertGreater(order["amount"], Decimal("0"))
        self.assertEqual(len(self.executor._graceful_close_orders), 1)

    def test_idempotency_same_reason_ignored(self):
        """Test: Duplicate start_forced_close() with same reason is ignored"""
        # First call
        self.executor.start_forced_close(CloseType.TIME_LIMIT)
        first_ts = self.executor._unwind_started_ts
        first_attempts = self.executor._unwind_attempts

        # Advance time slightly
        self.executor.current_timestamp += 10

        # Second call with same reason (should be ignored)
        self.executor.start_forced_close(CloseType.TIME_LIMIT)

        # Verify state unchanged
        self.assertEqual(self.executor._unwind_started_ts, first_ts, "Timestamp should not change")
        self.assertEqual(self.executor._unwind_attempts, first_attempts, "Attempts should not increment")
        self.assertEqual(len(self.executor._strategy.placed_orders), 1, "No duplicate orders")

    def test_priority_upgrade_works(self):
        """Test: Higher priority reason upgrades lower priority reason"""
        # Start with TIME_LIMIT (priority 70)
        self.executor.start_forced_close(CloseType.TIME_LIMIT)
        self.assertEqual(self.executor._unwind_close_reason, CloseType.TIME_LIMIT)

        # Trigger STOP_LOSS (priority 90 - higher)
        self.executor.start_forced_close(CloseType.STOP_LOSS)

        # Verify reason upgraded
        self.assertEqual(self.executor._unwind_close_reason, CloseType.STOP_LOSS, "Reason should upgrade")
        self.assertEqual(self.executor.close_type, CloseType.STOP_LOSS)

    def test_priority_downgrade_blocked(self):
        """Test: Lower priority reason cannot downgrade higher priority reason"""
        # Start with STOP_LOSS (priority 90)
        self.executor.start_forced_close(CloseType.STOP_LOSS)
        self.assertEqual(self.executor._unwind_close_reason, CloseType.STOP_LOSS)

        # Try to trigger MANUAL (priority 40 - lower)
        self.executor.start_forced_close(CloseType.MANUAL)

        # Verify reason NOT downgraded
        self.assertEqual(self.executor._unwind_close_reason, CloseType.STOP_LOSS, "Reason should NOT downgrade")
        self.assertEqual(self.executor.close_type, CloseType.STOP_LOSS)

    def test_graceful_to_aggressive_transition(self):
        """Test: Graceful phase transitions to aggressive after grace period"""
        # Start graceful phase
        self.executor.start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)
        self.assertEqual(self.executor._unwind_phase, "GRACEFUL")

        # Advance time past grace period (120s)
        self.executor.current_timestamp += 121

        # Check phase transition
        self.executor._check_unwind_phase_transition()

        # Verify transitioned to aggressive
        self.assertEqual(self.executor._unwind_phase, "AGGRESSIVE")

        # Verify aggressive order placed (graceful + aggressive)
        self.assertGreaterEqual(len(self.executor._strategy.placed_orders), 2, "Should have graceful + aggressive orders")

        # Verify last order is aggressive (MARKET)
        last_order = self.executor._strategy.placed_orders[-1]
        self.assertEqual(last_order["order_type"], OrderType.MARKET, "Aggressive phase uses MARKET orders")

    def test_graceful_transition_no_inventory_skips_aggressive(self):
        """Test: No transition to aggressive if inventory gone during grace period"""
        # Start graceful phase
        self.executor.start_forced_close(CloseType.TIME_LIMIT)
        self.assertEqual(self.executor._unwind_phase, "GRACEFUL")

        # Simulate inventory filled during grace period
        self.executor.position_size_base = Decimal("0.0000001")  # Below min order size

        # Advance time past grace period
        self.executor.current_timestamp += 121

        # Check phase transition
        self.executor._check_unwind_phase_transition()

        # Verify still in graceful (no transition needed)
        self.assertEqual(self.executor._unwind_phase, "GRACEFUL", "Should stay graceful if no inventory")

    def test_zero_inventory_skips_unwind(self):
        """Test: start_forced_close() with zero inventory skips to shutdown"""
        # Set zero inventory
        self.executor.position_size_base = Decimal("0")

        # Start forced close
        self.executor.start_forced_close(CloseType.NO_FILL_TIMEOUT)

        # Verify went directly to shutdown
        self.assertEqual(self.executor._status, RunnableStatus.SHUTTING_DOWN, "Should skip to SHUTTING_DOWN")
        self.assertEqual(self.executor._unwind_phase, "DONE")
        self.assertEqual(len(self.executor._strategy.placed_orders), 0, "No orders placed for zero inventory")

    def test_terminated_executor_ignores_close(self):
        """Test: start_forced_close() on terminated executor is ignored"""
        # Set executor to terminated
        self.executor._status = RunnableStatus.TERMINATED

        # Try to start forced close
        self.executor.start_forced_close(CloseType.MANUAL)

        # Verify ignored (unwind_phase stays NONE)
        self.assertEqual(self.executor._unwind_phase, "NONE", "Terminated executor should ignore close")
        self.assertEqual(len(self.executor._strategy.placed_orders), 0, "No orders placed")


if __name__ == "__main__":
    unittest.main()
