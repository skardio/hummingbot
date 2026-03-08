"""
Unit tests for Dynamic Slot Manager (Task 3.1)

Tests account-size and regime-aware slot scaling:
- €350 → 4 slots baseline, 6 BULL, 3 CHOP
- €1000 → 6 slots baseline, 9 BULL, 4 CHOP
- €2000 → 8 slots baseline, 12 BULL, 6 CHOP
"""

import unittest
from decimal import Decimal

from multi_coin_grid_pro.execution.dynamic_slot_manager import DynamicSlotManager


class TestDynamicSlotManager(unittest.TestCase):
    """Test dynamic slot calculation"""

    def test_disabled_returns_fallback(self):
        """When disabled, should return static fallback"""
        manager = DynamicSlotManager(config={"enabled": False})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="BULL",
            static_fallback=5
        )

        self.assertEqual(result, 5, "Should return fallback when disabled")

    def test_small_account_baseline(self):
        """€350 account → 4 slots baseline"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="baseline",
            static_fallback=2
        )

        self.assertEqual(result, 4, "€350 should get 4 slots")

    def test_small_account_bull(self):
        """€350 account → 6 slots in BULL (4 * 1.5)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="BULL",
            static_fallback=2
        )

        self.assertEqual(result, 6, "€350 BULL should get 6 slots (4 * 1.5)")

    def test_small_account_chop(self):
        """€350 account → 3 slots in CHOP (4 * 0.75)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="CHOP",
            static_fallback=2
        )

        self.assertEqual(result, 3, "€350 CHOP should get 3 slots (4 * 0.75)")

    def test_small_account_bear(self):
        """€350 account → 1 slot in BEAR (4 * 0.25)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="BEAR",
            static_fallback=2
        )

        self.assertEqual(result, 1, "€350 BEAR should get 1 slot (4 * 0.25)")

    def test_medium_account_baseline(self):
        """€1000 account → 6 slots baseline"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="baseline",
            static_fallback=4
        )

        self.assertEqual(result, 6, "€1000 should get 6 slots")

    def test_medium_account_bull(self):
        """€1000 account → 9 slots in BULL (6 * 1.5)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="BULL",
            static_fallback=4
        )

        self.assertEqual(result, 9, "€1000 BULL should get 9 slots (6 * 1.5)")

    def test_medium_account_chop(self):
        """€1000 account → 4 slots in CHOP (6 * 0.75 = 4.5 → 4)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="CHOP",
            static_fallback=4
        )

        self.assertEqual(result, 4, "€1000 CHOP should get 4 slots (6 * 0.75 rounded)")

    def test_large_account_baseline(self):
        """€2000 account → 8 slots baseline"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("2000"),
            current_regime="baseline",
            static_fallback=4
        )

        self.assertEqual(result, 8, "€2000 should get 8 slots")

    def test_large_account_bull_capped_at_max(self):
        """€2000 account → 12 slots in BULL (8 * 1.5 = 12), respects max"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "max_slots": 12
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("2000"),
            current_regime="BULL",
            static_fallback=4
        )

        self.assertEqual(result, 12, "€2000 BULL should get 12 slots (max cap)")

    def test_very_large_account_capped(self):
        """€5000 account should be capped at max_slots"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "max_slots": 12
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("5000"),
            current_regime="baseline",
            static_fallback=4
        )

        self.assertLessEqual(result, 12, "Should respect max_slots cap")

    def test_min_slots_enforced(self):
        """Very small account or BEAR should respect min_slots"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_slots": 1
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("100"),  # Very small
            current_regime="BEAR",
            static_fallback=4
        )

        self.assertGreaterEqual(result, 1, "Should respect min_slots")

    def test_interpolation_between_tiers(self):
        """€500 should interpolate between €350 (4 slots) and €700 (5 slots)"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("500"),
            current_regime="baseline",
            static_fallback=4
        )

        # €500 is midpoint between €350 and €700, so should get ~4.4 slots → 4
        self.assertIn(result, [4, 5], "€500 should interpolate to 4 or 5 slots")

    def test_custom_regime_multipliers(self):
        """Custom regime multipliers should override defaults"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "regime_multipliers": {
                "BULL": Decimal("2.0"),  # 2x instead of 1.5x
                "CHOP": Decimal("0.5")   # 0.5x instead of 0.75x
            }
        })

        result_bull = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="BULL",
            static_fallback=2
        )

        result_chop = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="CHOP",
            static_fallback=2
        )

        self.assertEqual(result_bull, 8, "€350 BULL with 2.0x should get 8 slots (4 * 2)")
        self.assertEqual(result_chop, 2, "€350 CHOP with 0.5x should get 2 slots (4 * 0.5)")

    def test_unknown_regime_defaults_to_baseline(self):
        """Unknown regime should use 1.0x multiplier"""
        manager = DynamicSlotManager(config={"enabled": True})

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="UNKNOWN_REGIME",
            static_fallback=4
        )

        # Should behave like baseline (6 slots for €1000)
        self.assertEqual(result, 6, "Unknown regime should default to baseline")

    def test_slot_report_generation(self):
        """Should generate readable slot report"""
        manager = DynamicSlotManager(config={"enabled": True})

        report = manager.get_slot_report(
            account_balance_eur=Decimal("1000"),
            current_regime="BULL"
        )

        self.assertIn("€1000", report, "Report should show balance")
        self.assertIn("BULL", report, "Report should show regime")
        self.assertIn("9", report, "Report should show calculated slots")


class TestDynamicSlotManagerFeasibilityCheck(unittest.TestCase):
    """Test minimum order size feasibility constraint"""

    def test_slots_capped_by_min_order_size(self):
        """Slots should be capped when per-level amount would be < min_order"""
        # $50 capital, $10 min order, 8 grids
        # Max slots = 50 / (10 * 8) = 0.625 → 1 slot
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 8,
            "total_amount_quote": 50,
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("116"),  # Would normally give 4+ slots
            current_regime="BULL",  # Would normally multiply to 6 slots
            static_fallback=4
        )

        self.assertEqual(result, 1, "Should cap to 1 slot due to min order constraint")

    def test_slots_capped_medium_account(self):
        """Medium account should have slots capped appropriately"""
        # $300 capital, $10 min order, 8 grids
        # Max slots = 300 / (10 * 8) = 3.75 → 3 slots
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 8,
            "total_amount_quote": 300,
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("300"),  # Would normally give 4 slots baseline
            current_regime="BULL",  # Would normally multiply to 6 slots
            static_fallback=4
        )

        self.assertEqual(result, 3, "Should cap to 3 slots due to min order constraint")

    def test_large_account_no_cap_needed(self):
        """Large account should not be capped by min order constraint"""
        # $1000 capital, $10 min order, 8 grids
        # Max slots = 1000 / (10 * 8) = 12.5 → 12 slots
        # BULL regime would give 9 slots (6 * 1.5), which is < 12
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 8,
            "total_amount_quote": 1000,
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("1000"),
            current_regime="BULL",
            static_fallback=4
        )

        self.assertEqual(result, 9, "Large account should not be capped (9 < 12)")

    def test_feasibility_with_fewer_grids(self):
        """Fewer grid levels should allow more slots"""
        # $100 capital, $10 min order, 2 grids
        # Max slots = 100 / (10 * 2) = 5 slots
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 2,
            "total_amount_quote": 100,
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),  # Would give 4 slots baseline
            current_regime="baseline",
            static_fallback=4
        )

        self.assertEqual(result, 4, "Fewer grids should allow 4 slots (4 < 5)")

    def test_no_feasibility_check_when_config_missing(self):
        """Without total_amount_quote, feasibility check should be skipped"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            # No total_amount_quote set
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("350"),
            current_regime="BULL",
            static_fallback=4
        )

        self.assertEqual(result, 6, "Without constraints, should get normal 6 slots")

    def test_feasibility_at_least_one_slot(self):
        """Even with very small capital, should get at least 1 slot"""
        # $5 capital, $10 min order, 8 grids → impossible
        # But should still return 1 slot minimum
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_slots": 1,
            "min_order_amount_quote": 10,
            "num_grids": 8,
            "total_amount_quote": 5,  # Very small!
        })

        result = manager.get_dynamic_slots(
            account_balance_eur=Decimal("100"),
            current_regime="BULL",
            static_fallback=4
        )

        self.assertGreaterEqual(result, 1, "Should always return at least 1 slot")


class TestDynamicAllocation(unittest.TestCase):
    """Test the new calculate_optimal_allocation method for fully dynamic allocation"""

    def test_small_account_79_usdt(self):
        """€79 should allocate 1 coin with reduced grids"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_slots": 1,
            "max_slots": 12,
            "quote_asset": "USDT",
            "min_order_amount_quote": 10,
            "num_grids": 10,
            "total_amount_quote": 50000,
        })

        alloc = manager.calculate_optimal_allocation(
            available_balance=Decimal("79"),
            current_regime="BULL"
        )

        self.assertTrue(alloc.is_feasible)
        self.assertEqual(alloc.num_coins, 1)
        # €79 * 0.95 = €75.05 / min_order_10 / safety_1.2 = 6.25 grids max → 5 or 6
        self.assertLessEqual(alloc.num_grids, 7)
        self.assertGreaterEqual(alloc.num_grids, 3)
        self.assertGreaterEqual(alloc.amount_per_grid_level, Decimal("10"))

    def test_medium_account_300_usdt(self):
        """€300 should allocate 2 coins with good grids"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_slots": 1,
            "max_slots": 12,
            "quote_asset": "USDT",
            "min_order_amount_quote": 10,
            "num_grids": 10,
            "total_amount_quote": 50000,
        })

        alloc = manager.calculate_optimal_allocation(
            available_balance=Decimal("300"),
            current_regime="BULL"
        )

        self.assertTrue(alloc.is_feasible)
        self.assertGreaterEqual(alloc.num_coins, 2)
        self.assertGreaterEqual(alloc.num_grids, 5)
        self.assertGreaterEqual(alloc.amount_per_grid_level, Decimal("10"))

    def test_large_account_5000_usdt(self):
        """€5000 should allocate many coins with max grids"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_slots": 1,
            "max_slots": 12,
            "quote_asset": "USDT",
            "min_order_amount_quote": 10,
            "num_grids": 10,
            "total_amount_quote": 50000,
        })

        alloc = manager.calculate_optimal_allocation(
            available_balance=Decimal("5000"),
            current_regime="BULL"
        )

        self.assertTrue(alloc.is_feasible)
        self.assertGreaterEqual(alloc.num_coins, 6)
        self.assertEqual(alloc.num_grids, 10)  # Preferred grids
        self.assertGreaterEqual(alloc.amount_per_grid_level, Decimal("30"))

    def test_too_small_account_not_feasible(self):
        """€20 should not be feasible with €10 min order"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 10,
        })

        alloc = manager.calculate_optimal_allocation(
            available_balance=Decimal("20"),
            current_regime="BULL"
        )

        # €20 * 0.95 = €19, need min €30 (3 grids × €10)
        self.assertFalse(alloc.is_feasible)
        self.assertEqual(alloc.num_coins, 0)
        self.assertEqual(alloc.num_grids, 0)

    def test_minimum_viable_account(self):
        """€35 should be just barely feasible (3 grids × €10 = €30)"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 10,
        })

        alloc = manager.calculate_optimal_allocation(
            available_balance=Decimal("35"),
            current_regime="BULL"
        )

        self.assertTrue(alloc.is_feasible)
        self.assertEqual(alloc.num_coins, 1)
        self.assertEqual(alloc.num_grids, 3)  # Minimum grids

    def test_allocation_report_readable(self):
        """Allocation report should be human readable"""
        manager = DynamicSlotManager(config={
            "enabled": True,
            "min_order_amount_quote": 10,
            "num_grids": 10,
            "quote_asset": "USDT",
        })

        report = manager.get_allocation_report(
            available_balance=Decimal("79"),
            current_regime="BULL"
        )

        self.assertIn("DYNAMIC ALLOCATION", report)
        self.assertIn("Coins:", report)
        self.assertIn("Grids per coin:", report)
        self.assertIn("Per grid level:", report)


if __name__ == '__main__':
    unittest.main()
