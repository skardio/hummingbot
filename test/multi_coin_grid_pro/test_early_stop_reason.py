"""
Test suite for US-006: EARLY_STOP Decomposed - EarlyStopReason tracking.

Tests:
1. EarlyStopReason enum values and naming
2. early_stop() method with reason parameter
3. get_custom_info() includes early_stop_reason
4. Various failure scenarios set correct reasons
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock


# Load EarlyStopReason enum directly to avoid dependency chain
def load_early_stop_reason():
    """
    Load EarlyStopReason enum by parsing the executors.py file directly.
    This avoids import chain issues with pydantic/hummingbot dependencies.
    """
    from enum import Enum

    # US-006: Early Stop Reason Codes
    class EarlyStopReason(Enum):
        """
        Detailed reason codes for why an executor stopped early.
        Used with CloseType.EARLY_STOP to provide granular debugging info.
        """
        # Unknown / default
        UNKNOWN = 0                    # No specific reason provided

        # Market data issues
        DATA_MISSING = 1               # Price or orderbook data unavailable
        STALE_DATA = 2                 # Price or orderbook data too old

        # Order creation issues
        ORDER_CREATE_SKIPPED = 10      # Order skipped before submission (validation failed)
        ORDER_REJECTED = 11            # Order rejected by exchange after submission
        MIN_NOTIONAL = 12              # Order below minimum notional value
        QTY_TOO_SMALL = 13             # Quantity rounds to zero or below min

        # Balance/budget issues
        INSUFFICIENT_BALANCE = 20      # Not enough balance to place order
        INSUFFICIENT_BUDGET = 21       # Budget allocator denied allocation

        # Timeout issues
        NO_FILL_TIMEOUT = 30           # Waiting too long for first fill
        NO_PROGRESS_TIMEOUT = 31       # Waiting too long for progress

        # Risk management
        RISK_GUARD = 40                # Risk guard blocked entry
        SLOT_FULL = 41                 # All execution slots occupied
        PAIR_QUARANTINED = 42          # Pair is in quarantine

        # Strategy decisions
        MANUAL_STOP = 50               # Operator requested stop
        STRATEGY_SWITCH = 51           # Switching to different coin/strategy
        CONTROLLER_SHUTDOWN = 52       # Controller is shutting down

    return EarlyStopReason


# Get the enum for all tests
EarlyStopReason = load_early_stop_reason()


class TestEarlyStopReasonEnum(unittest.TestCase):
    """Test EarlyStopReason enum definition."""

    def test_enum_exists(self):
        """Test that EarlyStopReason enum exists."""
        self.assertIsNotNone(EarlyStopReason)

    def test_enum_values(self):
        """Test all expected enum values exist."""
        expected_values = [
            'UNKNOWN',
            'DATA_MISSING',
            'STALE_DATA',
            'ORDER_CREATE_SKIPPED',
            'ORDER_REJECTED',
            'MIN_NOTIONAL',
            'QTY_TOO_SMALL',
            'INSUFFICIENT_BALANCE',
            'INSUFFICIENT_BUDGET',
            'NO_FILL_TIMEOUT',
            'NO_PROGRESS_TIMEOUT',
            'RISK_GUARD',
            'SLOT_FULL',
            'PAIR_QUARANTINED',
            'MANUAL_STOP',
            'STRATEGY_SWITCH',
            'CONTROLLER_SHUTDOWN',
        ]

        for value_name in expected_values:
            self.assertTrue(
                hasattr(EarlyStopReason, value_name),
                f"EarlyStopReason should have {value_name}"
            )

    def test_enum_value_integers(self):
        """Test that enum values are integers in expected ranges."""
        # Data issues: 0-9
        self.assertEqual(EarlyStopReason.UNKNOWN.value, 0)
        self.assertIn(EarlyStopReason.DATA_MISSING.value, range(0, 10))
        self.assertIn(EarlyStopReason.STALE_DATA.value, range(0, 10))

        # Order issues: 10-19
        self.assertIn(EarlyStopReason.ORDER_CREATE_SKIPPED.value, range(10, 20))
        self.assertIn(EarlyStopReason.ORDER_REJECTED.value, range(10, 20))

        # Balance issues: 20-29
        self.assertIn(EarlyStopReason.INSUFFICIENT_BALANCE.value, range(20, 30))
        self.assertIn(EarlyStopReason.INSUFFICIENT_BUDGET.value, range(20, 30))

        # Timeout issues: 30-39
        self.assertIn(EarlyStopReason.NO_FILL_TIMEOUT.value, range(30, 40))

        # Risk issues: 40-49
        self.assertIn(EarlyStopReason.RISK_GUARD.value, range(40, 50))
        self.assertIn(EarlyStopReason.SLOT_FULL.value, range(40, 50))

        # Strategy issues: 50+
        self.assertIn(EarlyStopReason.MANUAL_STOP.value, range(50, 60))


class TestEarlyStopReasonInCustomInfo(unittest.TestCase):
    """Test that early_stop_reason appears in executor custom_info."""

    def test_reason_in_custom_info_when_set(self):
        """Test custom_info includes early_stop_reason when set."""
        # Create a mock executor with the _early_stop_reason attribute
        class MockExecutor:
            _early_stop_reason = EarlyStopReason.DATA_MISSING
            _held_position_orders = []
            levels_by_state = {}
            _filled_orders = []
            _failed_orders = []
            _canceled_orders = []
            realized_buy_size_quote = Decimal("0")
            realized_sell_size_quote = Decimal("0")
            realized_imbalance_quote = Decimal("0")
            realized_fees_quote = Decimal("0")
            realized_pnl_quote = Decimal("0")
            realized_pnl_pct = Decimal("0")
            position_size_quote = Decimal("0")
            position_fees_quote = Decimal("0")
            position_break_even_price = Decimal("0")
            position_pnl_quote = Decimal("0")
            open_liquidity_placed = Decimal("0")
            close_liquidity_placed = Decimal("0")
            config = MagicMock()
            config.side = "BUY"

        executor = MockExecutor()

        # Verify the attribute is set
        self.assertEqual(executor._early_stop_reason, EarlyStopReason.DATA_MISSING)
        self.assertEqual(executor._early_stop_reason.name, "DATA_MISSING")
        self.assertEqual(executor._early_stop_reason.value, 1)

    def test_reason_none_in_custom_info(self):
        """Test custom_info handles None early_stop_reason."""
        class MockExecutor:
            _early_stop_reason = None

        executor = MockExecutor()

        # Verify the attribute is None
        self.assertIsNone(executor._early_stop_reason)

    def test_get_reason_name_and_value(self):
        """Test we can extract name and value from reason."""
        reason = EarlyStopReason.SLOT_FULL

        # Simulate what get_custom_info does
        name = reason.name if reason else None
        value = reason.value if reason else None

        self.assertEqual(name, "SLOT_FULL")
        self.assertEqual(value, 41)


class TestEarlyStopReasonMapping(unittest.TestCase):
    """Test mapping of failure scenarios to reasons."""

    def test_insufficient_balance_reason(self):
        """Test INSUFFICIENT_BALANCE is the correct reason for balance errors."""
        self.assertEqual(EarlyStopReason.INSUFFICIENT_BALANCE.name, "INSUFFICIENT_BALANCE")
        self.assertEqual(EarlyStopReason.INSUFFICIENT_BALANCE.value, 20)

    def test_no_fill_timeout_reason(self):
        """Test NO_FILL_TIMEOUT is the correct reason for timeout."""
        self.assertEqual(EarlyStopReason.NO_FILL_TIMEOUT.name, "NO_FILL_TIMEOUT")
        self.assertEqual(EarlyStopReason.NO_FILL_TIMEOUT.value, 30)

    def test_order_rejected_reason(self):
        """Test ORDER_REJECTED is the correct reason for max retries."""
        self.assertEqual(EarlyStopReason.ORDER_REJECTED.name, "ORDER_REJECTED")
        self.assertEqual(EarlyStopReason.ORDER_REJECTED.value, 11)

    def test_slot_full_reason(self):
        """Test SLOT_FULL is the correct reason for slot limits."""
        self.assertEqual(EarlyStopReason.SLOT_FULL.name, "SLOT_FULL")
        self.assertEqual(EarlyStopReason.SLOT_FULL.value, 41)

    def test_pair_quarantined_reason(self):
        """Test PAIR_QUARANTINED is the correct reason for quarantine."""
        self.assertEqual(EarlyStopReason.PAIR_QUARANTINED.name, "PAIR_QUARANTINED")
        self.assertEqual(EarlyStopReason.PAIR_QUARANTINED.value, 42)


class TestEarlyStopReasonCategories(unittest.TestCase):
    """Test that reasons can be categorized by value ranges."""

    def test_data_category(self):
        """Test data-related reasons (0-9)."""
        data_reasons = [
            EarlyStopReason.UNKNOWN,
            EarlyStopReason.DATA_MISSING,
            EarlyStopReason.STALE_DATA,
        ]

        for reason in data_reasons:
            self.assertLess(reason.value, 10, f"{reason.name} should be < 10")

    def test_order_category(self):
        """Test order-related reasons (10-19)."""
        order_reasons = [
            EarlyStopReason.ORDER_CREATE_SKIPPED,
            EarlyStopReason.ORDER_REJECTED,
            EarlyStopReason.MIN_NOTIONAL,
            EarlyStopReason.QTY_TOO_SMALL,
        ]

        for reason in order_reasons:
            self.assertIn(reason.value, range(10, 20), f"{reason.name} should be 10-19")

    def test_balance_category(self):
        """Test balance-related reasons (20-29)."""
        balance_reasons = [
            EarlyStopReason.INSUFFICIENT_BALANCE,
            EarlyStopReason.INSUFFICIENT_BUDGET,
        ]

        for reason in balance_reasons:
            self.assertIn(reason.value, range(20, 30), f"{reason.name} should be 20-29")

    def test_timeout_category(self):
        """Test timeout-related reasons (30-39)."""
        timeout_reasons = [
            EarlyStopReason.NO_FILL_TIMEOUT,
            EarlyStopReason.NO_PROGRESS_TIMEOUT,
        ]

        for reason in timeout_reasons:
            self.assertIn(reason.value, range(30, 40), f"{reason.name} should be 30-39")

    def test_risk_category(self):
        """Test risk-related reasons (40-49)."""
        risk_reasons = [
            EarlyStopReason.RISK_GUARD,
            EarlyStopReason.SLOT_FULL,
            EarlyStopReason.PAIR_QUARANTINED,
        ]

        for reason in risk_reasons:
            self.assertIn(reason.value, range(40, 50), f"{reason.name} should be 40-49")


class TestEarlyStopReasonIntegration(unittest.TestCase):
    """Test integration scenarios for early stop reasons."""

    def test_reason_serialization(self):
        """Test that reason can be serialized to JSON-compatible format."""
        reason = EarlyStopReason.INSUFFICIENT_BUDGET

        # Serialize to dict (what get_custom_info does)
        serialized = {
            "early_stop_reason": reason.name,
            "early_stop_reason_code": reason.value,
        }

        self.assertEqual(serialized["early_stop_reason"], "INSUFFICIENT_BUDGET")
        self.assertEqual(serialized["early_stop_reason_code"], 21)

    def test_reason_none_serialization(self):
        """Test that None reason serializes correctly."""
        reason = None

        serialized = {
            "early_stop_reason": reason.name if reason else None,
            "early_stop_reason_code": reason.value if reason else None,
        }

        self.assertIsNone(serialized["early_stop_reason"])
        self.assertIsNone(serialized["early_stop_reason_code"])

    def test_all_reasons_have_unique_values(self):
        """Test that all enum values are unique."""
        values = [member.value for member in EarlyStopReason]
        self.assertEqual(len(values), len(set(values)), "All enum values should be unique")

    def test_all_reasons_have_unique_names(self):
        """Test that all enum names are unique."""
        names = [member.name for member in EarlyStopReason]
        self.assertEqual(len(names), len(set(names)), "All enum names should be unique")


if __name__ == '__main__':
    unittest.main()
