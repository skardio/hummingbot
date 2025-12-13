"""
Unit tests for DynamicGridSizer v2.0
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multi_coin_grid_pro.logic.grid_sizer import DynamicGridSizer


class TestDynamicGridSizer(unittest.TestCase):
    """Test DynamicGridSizer logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)

        self.cfg = {
            "min_grids": 3,
            "max_grids": 7,
            "low_vol_atr_pct": 0.7,
            "mid_vol_atr_pct": 2.0,
            "high_vol_atr_pct": 4.0,
        }

        self.sizer = DynamicGridSizer(self.cfg, self.logger)

    def test_low_volatility(self):
        """Test low volatility returns min grids"""
        count = self.sizer.grid_count_for(atr_pct=0.5)
        self.assertEqual(count, 3, "Low volatility should return min_grids=3")

    def test_medium_volatility(self):
        """Test medium volatility returns moderate grids"""
        count = self.sizer.grid_count_for(atr_pct=1.5)
        self.assertGreaterEqual(count, 4, "Medium vol should be >= 4")
        self.assertLessEqual(count, 5, "Medium vol should be <= 5")

    def test_high_volatility(self):
        """Test high volatility returns max grids"""
        count = self.sizer.grid_count_for(atr_pct=3.0)
        self.assertEqual(count, 7, "High volatility should return max_grids=7")

    def test_very_high_volatility(self):
        """Test very high volatility reduces grids (risk management)"""
        count = self.sizer.grid_count_for(atr_pct=6.0)
        self.assertEqual(count, 5, "Very high vol should reduce to 5 grids")

    def test_edge_cases(self):
        """Test boundary conditions"""
        # Exactly at low threshold (0.7 is NOT < 0.7, so goes to medium vol)
        count_low = self.sizer.grid_count_for(atr_pct=0.7)
        self.assertEqual(count_low, 4)  # Medium vol logic: min_grids + 1 = 3 + 1 = 4

        # Exactly at mid threshold (2.0 is NOT < 2.0, triggers high vol: 2.0 < 4.0)
        count_mid = self.sizer.grid_count_for(atr_pct=2.0)
        self.assertEqual(count_mid, 7)  # High vol branch: max_grids = 7

        # Exactly at high threshold (4.0 is NOT < 4.0, triggers very high vol)
        count_high = self.sizer.grid_count_for(atr_pct=4.0)
        self.assertEqual(count_high, 5)  # Very high vol: max_grids - 2 = 7 - 2 = 5

    def test_get_grid_spacing(self):
        """Test grid spacing calculation"""
        spacing = self.sizer.get_grid_spacing(atr_pct=2.5, price=100.0)

        self.assertIn("spacing_pct", spacing)
        self.assertIn("num_grids", spacing)
        self.assertIn("range_down_pct", spacing)
        self.assertIn("range_up_pct", spacing)

        # Spacing should be reasonable
        self.assertGreater(spacing["spacing_pct"], 0.3)
        self.assertLess(spacing["spacing_pct"], 3.0)


if __name__ == "__main__":
    unittest.main()
