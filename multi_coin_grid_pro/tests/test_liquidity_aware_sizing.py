"""
Unit tests for Liquidity-Aware Smart Sizing (Feature 1.2b)

Tests the sizing cap functionality to prevent bonus stacking
"""
import unittest
from decimal import Decimal

from multi_coin_grid_pro.logic.liquidity_aware_sizer import LiquidityAwareSizing


class TestLiquidityAwareSizing(unittest.TestCase):
    """Test Liquidity-Aware Smart Sizing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.config_enabled = {
            "enabled": True,
            "max_total_size_multiplier": 1.2,
            "log_sizing_calc": False  # Disable for cleaner test output
        }

        self.config_disabled = {
            "enabled": False,
            "max_total_size_multiplier": 1.2,
            "log_sizing_calc": False
        }

    def test_disabled_feature_passes_through(self):
        """Test that disabled feature doesn't modify sizing"""
        sizer = LiquidityAwareSizing(self.config_disabled)

        base_size = Decimal("50.0")
        multiplier = 1.5  # Would normally be capped

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        expected = base_size * Decimal("1.5")

        self.assertEqual(result, expected)
        self.assertEqual(result, Decimal("75.0"))

    def test_multiplier_below_cap_passes_through(self):
        """Test that multipliers below cap are not modified"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        base_size = Decimal("50.0")
        multiplier = 1.1  # Below 1.2 cap

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        expected = base_size * Decimal("1.1")

        self.assertEqual(result, expected)
        self.assertEqual(result, Decimal("55.0"))

    def test_multiplier_at_cap_passes_through(self):
        """Test that multipliers exactly at cap pass through"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        base_size = Decimal("50.0")
        multiplier = 1.2  # Exactly at cap

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        expected = base_size * Decimal("1.2")

        self.assertEqual(result, expected)
        self.assertEqual(result, Decimal("60.0"))

    def test_multiplier_above_cap_gets_capped(self):
        """Test that multipliers above cap are capped"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        base_size = Decimal("50.0")
        multiplier = 1.39  # Above 1.2 cap (bonus stacking scenario)

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        expected = base_size * Decimal("1.2")  # Capped at 1.2

        self.assertEqual(result, expected)
        self.assertEqual(result, Decimal("60.0"))
        # Not 69.5 (50 * 1.39)

    def test_realistic_bonus_stacking_scenario(self):
        """Test realistic scenario: time × regime × volatility bonuses"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        base_size = Decimal("69.0")  # 207 EUR / 3 coins

        # Simulate bonus stacking:
        # - Weekend high liquidity: 1.10x
        # - Strong bull regime: 1.15x
        # - Low volatility: 1.10x
        # Total: 1.10 × 1.15 × 1.10 = 1.3915x

        stacked_multiplier = 1.10 * 1.15 * 1.10  # = 1.3915

        # Without cap: 69 * 1.3915 = 96.01 EUR (TOO MUCH!)
        # With cap: 69 * 1.2 = 82.8 EUR (SAFE)

        result = sizer.apply_sizing_cap(base_size, stacked_multiplier, "BTC-EUR")
        expected = base_size * Decimal("1.2")

        self.assertEqual(result, expected)
        self.assertAlmostEqual(float(result), 82.8, places=1)

        # Verify we prevented oversizing
        without_cap = base_size * Decimal(str(stacked_multiplier))
        self.assertGreater(without_cap, result)
        self.assertAlmostEqual(float(without_cap), 96.01, places=1)

    def test_get_effective_multiplier_below_cap(self):
        """Test effective multiplier calculation below cap"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        result = sizer.get_effective_multiplier(1.1)
        self.assertEqual(result, 1.1)

    def test_get_effective_multiplier_above_cap(self):
        """Test effective multiplier calculation above cap"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        result = sizer.get_effective_multiplier(1.5)
        self.assertEqual(result, 1.2)

    def test_get_effective_multiplier_disabled(self):
        """Test effective multiplier when feature disabled"""
        sizer = LiquidityAwareSizing(self.config_disabled)

        result = sizer.get_effective_multiplier(1.5)
        self.assertEqual(result, 1.5)  # No capping

    def test_zero_base_size_edge_case(self):
        """Test handling of zero base size"""
        sizer = LiquidityAwareSizing(self.config_enabled)

        base_size = Decimal("0")
        multiplier = 1.5

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        self.assertEqual(result, Decimal("0"))

    def test_custom_cap_value(self):
        """Test with custom max_total_size_multiplier"""
        custom_config = {
            "enabled": True,
            "max_total_size_multiplier": 1.5,  # Higher cap
            "log_sizing_calc": False
        }
        sizer = LiquidityAwareSizing(custom_config)

        base_size = Decimal("50.0")
        multiplier = 1.4

        result = sizer.apply_sizing_cap(base_size, multiplier, "TEST-EUR")
        expected = base_size * Decimal("1.4")  # Below 1.5 cap

        self.assertEqual(result, expected)
        self.assertEqual(result, Decimal("70.0"))


if __name__ == '__main__':
    unittest.main()
