"""
Unit tests for US-004: Budget Allocator

Tests that the budget allocator correctly:
1. Calculates required quote with fee buffer
2. Checks budget availability
3. Reserves and releases capital
4. Prevents concurrent executor budget conflicts
"""
import logging
import unittest
from decimal import Decimal

from multi_coin_grid_pro.utils.budget_allocator import BudgetAllocator, BudgetReservation


class TestBudgetAllocator(unittest.TestCase):
    """Tests for BudgetAllocator."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)

        self.allocator = BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),  # 0.2%
            quote_reserve_pct=Decimal("0.05"),  # 5%
            logger=self.logger,
        )

    def test_calculate_required_quote_without_fee_buffer(self):
        """Required quote without fee buffer equals base amount."""
        result = self.allocator.calculate_required_quote(
            base_amount=Decimal("100"),
            grid_levels=3,
            include_fee_buffer=False,
        )
        self.assertEqual(result, Decimal("100"))

    def test_calculate_required_quote_with_fee_buffer(self):
        """Required quote with fee buffer adds extra for trading fees."""
        # 100 base + (100 * 0.002 * 3 levels * 2 trades) = 100 + 1.2 = 101.2
        result = self.allocator.calculate_required_quote(
            base_amount=Decimal("100"),
            grid_levels=3,
            include_fee_buffer=True,
        )
        expected = Decimal("100") + Decimal("100") * Decimal("0.002") * Decimal("6")  # 3 levels * 2 trades
        self.assertEqual(result, expected)

    def test_check_budget_allowed_when_sufficient(self):
        """Budget check allows when enough free capital."""
        result = self.allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("100"),
            symbol="BTC-USDT",
        )

        self.assertTrue(result.is_allowed)
        # Available = 1000 - 0 reserved - 50 (5% reserve) = 950
        self.assertEqual(result.available_quote, Decimal("950"))
        self.assertEqual(result.required_quote, Decimal("100"))
        self.assertIsNone(result.reason)

    def test_check_budget_blocked_when_insufficient(self):
        """Budget check blocks when not enough free capital."""
        result = self.allocator.check_budget(
            total_balance=Decimal("100"),
            required_quote=Decimal("100"),  # Need 100, but only 95 available after reserve
            symbol="BTC-USDT",
        )

        self.assertFalse(result.is_allowed)
        # Available = 100 - 0 reserved - 5 (5% reserve) = 95
        self.assertEqual(result.available_quote, Decimal("95"))
        self.assertIsNotNone(result.reason)
        self.assertIn("Insufficient", result.reason)

    def test_reserve_creates_reservation(self):
        """Reserve creates a reservation and tracks it."""
        success = self.allocator.reserve(
            executor_id="exec-123",
            symbol="BTC-USDT",
            amount=Decimal("100"),
            grid_levels=3,
            timestamp=1000.0,
        )

        self.assertTrue(success)
        self.assertEqual(self.allocator.total_reserved, Decimal("100"))
        self.assertEqual(self.allocator.active_executor_count, 1)

        reservation = self.allocator.get_reservation("exec-123")
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.symbol, "BTC-USDT")
        self.assertEqual(reservation.reserved_amount, Decimal("100"))

    def test_reserve_prevents_duplicate(self):
        """Cannot reserve twice with same executor ID."""
        self.allocator.reserve("exec-123", "BTC-USDT", Decimal("100"), 3, 1000.0)

        # Try to reserve again with same ID
        success = self.allocator.reserve("exec-123", "ETH-USDT", Decimal("50"), 3, 1001.0)

        self.assertFalse(success)
        self.assertEqual(self.allocator.active_executor_count, 1)
        self.assertEqual(self.allocator.total_reserved, Decimal("100"))

    def test_release_removes_reservation(self):
        """Release removes reservation and frees capital."""
        self.allocator.reserve("exec-123", "BTC-USDT", Decimal("100"), 3, 1000.0)
        self.assertEqual(self.allocator.total_reserved, Decimal("100"))

        released = self.allocator.release("exec-123")

        self.assertEqual(released, Decimal("100"))
        self.assertEqual(self.allocator.total_reserved, Decimal("0"))
        self.assertEqual(self.allocator.active_executor_count, 0)

    def test_release_nonexistent_returns_none(self):
        """Release of nonexistent executor returns None."""
        released = self.allocator.release("nonexistent")
        self.assertIsNone(released)

    def test_multiple_reservations_sum_correctly(self):
        """Multiple reservations sum together."""
        self.allocator.reserve("exec-1", "BTC-USDT", Decimal("100"), 3, 1000.0)
        self.allocator.reserve("exec-2", "ETH-USDT", Decimal("80"), 3, 1001.0)
        self.allocator.reserve("exec-3", "SOL-USDT", Decimal("50"), 3, 1002.0)

        self.assertEqual(self.allocator.total_reserved, Decimal("230"))
        self.assertEqual(self.allocator.active_executor_count, 3)

    def test_check_budget_accounts_for_existing_reservations(self):
        """Budget check subtracts existing reservations."""
        # Reserve 500 for existing executor
        self.allocator.reserve("exec-1", "BTC-USDT", Decimal("500"), 3, 1000.0)

        # Check if we can allocate 500 more with 1000 balance
        # Available = 1000 - 500 reserved - 50 (5% reserve) = 450
        result = self.allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("500"),
            symbol="ETH-USDT",
        )

        self.assertFalse(result.is_allowed)  # Need 500, have 450
        self.assertEqual(result.available_quote, Decimal("450"))
        self.assertEqual(result.reserved_by_others, Decimal("500"))

    def test_sync_removes_orphaned_reservations(self):
        """Sync removes reservations for executors no longer active."""
        self.allocator.reserve("exec-1", "BTC-USDT", Decimal("100"), 3, 1000.0)
        self.allocator.reserve("exec-2", "ETH-USDT", Decimal("100"), 3, 1001.0)
        self.allocator.reserve("exec-3", "SOL-USDT", Decimal("100"), 3, 1002.0)

        # Only exec-2 is still active
        active_ids = {"exec-2"}
        cleaned = self.allocator.sync_with_active_executors(active_ids, 2000.0)

        self.assertEqual(cleaned, 2)  # exec-1 and exec-3 removed
        self.assertEqual(self.allocator.total_reserved, Decimal("100"))
        self.assertEqual(self.allocator.active_executor_count, 1)
        self.assertIsNotNone(self.allocator.get_reservation("exec-2"))

    def test_get_symbol_reservations(self):
        """Get total reserved for a specific symbol."""
        self.allocator.reserve("exec-1", "BTC-USDT", Decimal("100"), 3, 1000.0)
        self.allocator.reserve("exec-2", "BTC-USDT", Decimal("80"), 3, 1001.0)
        self.allocator.reserve("exec-3", "ETH-USDT", Decimal("50"), 3, 1002.0)

        btc_reserved = self.allocator.get_symbol_reservations("BTC-USDT")
        eth_reserved = self.allocator.get_symbol_reservations("ETH-USDT")
        sol_reserved = self.allocator.get_symbol_reservations("SOL-USDT")

        self.assertEqual(btc_reserved, Decimal("180"))
        self.assertEqual(eth_reserved, Decimal("50"))
        self.assertEqual(sol_reserved, Decimal("0"))

    def test_cleanup_stale_reservations(self):
        """Cleanup removes reservations older than max age."""
        self.allocator.reserve("exec-old", "BTC-USDT", Decimal("100"), 3, 1000.0)
        self.allocator.reserve("exec-new", "ETH-USDT", Decimal("100"), 3, 5000.0)

        # Cleanup with max age 1 hour (3600s), current time 6000
        # exec-old is 5000s old (> 3600), exec-new is 1000s old (< 3600)
        cleaned = self.allocator.cleanup_stale_reservations(
            max_age_seconds=3600.0,
            current_time=6000.0,
        )

        self.assertEqual(cleaned, 1)
        self.assertIsNone(self.allocator.get_reservation("exec-old"))
        self.assertIsNotNone(self.allocator.get_reservation("exec-new"))

    def test_get_summary(self):
        """Get summary returns correct structure."""
        self.allocator.reserve("exec-1", "BTC-USDT", Decimal("100"), 3, 1000.0)

        summary = self.allocator.get_summary()

        self.assertEqual(summary["total_reserved"], 100.0)
        self.assertEqual(summary["executor_count"], 1)
        self.assertIn("exec-1", summary["reservations"])
        self.assertEqual(summary["reservations"]["exec-1"]["symbol"], "BTC-USDT")


class TestBudgetAllocatorEdgeCases(unittest.TestCase):
    """Edge case tests for BudgetAllocator."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)

        self.allocator = BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),
            quote_reserve_pct=Decimal("0.05"),
            logger=self.logger,
        )

    def test_zero_balance_blocks_all(self):
        """Zero balance blocks all allocations."""
        result = self.allocator.check_budget(
            total_balance=Decimal("0"),
            required_quote=Decimal("10"),
            symbol="BTC-USDT",
        )

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.available_quote, Decimal("0"))

    def test_negative_available_capped_to_zero(self):
        """Negative available (overcommitted) is capped to zero."""
        # Reserve more than balance (shouldn't happen but test edge case)
        self.allocator._reservations["exec-1"] = BudgetReservation(
            executor_id="exec-1",
            symbol="BTC-USDT",
            reserved_amount=Decimal("2000"),  # More than balance
            grid_levels=3,
            timestamp=1000.0,
        )

        result = self.allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("100"),
            symbol="ETH-USDT",
        )

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.available_quote, Decimal("0"))  # Capped at 0

    def test_exactly_enough_budget_allows(self):
        """Exactly enough budget (no margin) allows allocation."""
        # Balance 1000, reserve 5% = 50, available = 950
        result = self.allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("950"),
            symbol="BTC-USDT",
        )

        self.assertTrue(result.is_allowed)

    def test_one_cent_over_blocks(self):
        """One cent over budget blocks allocation."""
        # Balance 1000, reserve 5% = 50, available = 950
        result = self.allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("950.01"),
            symbol="BTC-USDT",
        )

        self.assertFalse(result.is_allowed)


if __name__ == "__main__":
    unittest.main()
