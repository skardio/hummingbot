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


if __name__ == '__main__':
    unittest.main()
