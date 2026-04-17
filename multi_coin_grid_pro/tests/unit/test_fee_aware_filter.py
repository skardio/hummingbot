"""Tests for FeeAwareFilter (pre-entry profitability check)."""
import logging
import unittest

from multi_coin_grid_pro.logic.fee_aware_filter import FeeAwareFilter, FeeCheckResult


class TestFeeAwareFilter(unittest.TestCase):
    """Tests for fee-aware grid filtering."""

    def _make_filter(self, **overrides):
        config = {
            'enabled': True,
            'taker_fee_pct': 0.26,
            'maker_fee_pct': 0.16,
            'min_net_profit_pct': 0.3,
            'use_maker_fees': False,
        }
        config.update(overrides)
        return FeeAwareFilter(config=config, log=logging.getLogger("test"))

    # ---- Round-trip fee ----

    def test_taker_round_trip_fee(self):
        f = self._make_filter()
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.52)

    def test_maker_round_trip_fee(self):
        f = self._make_filter(use_maker_fees=True)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.32)

    # ---- Check pass/fail ----

    def test_profitable_grid_passes(self):
        """4% range, 3 grids → 2% spread per level → 2.0 - 0.52 = 1.48% net."""
        f = self._make_filter()
        result = f.check("LINK-USD", grid_range_pct=4.0, num_grids=3)
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 2.0)
        self.assertAlmostEqual(result.net_profit_pct, 2.0 - 0.52, places=2)

    def test_unprofitable_grid_rejected(self):
        """1% range, 3 grids → 0.5% spread → 0.5 - 0.52 = -0.02% net."""
        f = self._make_filter()
        result = f.check("FET-USD", grid_range_pct=1.0, num_grids=3)
        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 0.5)
        self.assertLess(result.net_profit_pct, 0)

    def test_borderline_passes_when_above_min(self):
        """1.66% range, 3 grids → 0.83% spread → 0.83 - 0.52 = 0.31% net > min."""
        f = self._make_filter()
        result = f.check("SOL-USD", grid_range_pct=1.66, num_grids=3)
        self.assertTrue(result.passed)
        self.assertGreater(result.net_profit_pct, 0.3)

    def test_borderline_fails_when_below_min(self):
        """1.62% range, 3 grids → 0.81% spread → 0.81 - 0.52 = 0.29% net < 0.30%."""
        f = self._make_filter()
        result = f.check("SOL-USD", grid_range_pct=1.62, num_grids=3)
        self.assertFalse(result.passed)

    # ---- Single grid ----

    def test_single_grid_uses_full_range(self):
        """With 1 grid, spread = full range."""
        f = self._make_filter()
        result = f.check("BTC-USD", grid_range_pct=2.0, num_grids=1)
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 2.0)

    # ---- ATR reality check ----

    def test_atr_caps_effective_spread(self):
        """If grid is wider than 2×ATR, effective spread is capped."""
        f = self._make_filter()
        # 10% range, 3 grids → 5% per level, but ATR says only 1% moves typical
        result = f.check("FET-USD", grid_range_pct=10.0, num_grids=3, atr_pct=0.01)
        # effective = min(5.0, 0.01*2) = 0.02 → way too small
        self.assertFalse(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 0.02)

    def test_atr_doesnt_affect_narrow_grids(self):
        """If grid is narrower than 2×ATR, ATR doesn't change the spread."""
        f = self._make_filter()
        # 4% range, 3 grids → 2% per level, ATR=3.0% → 2*ATR=6.0%
        # atr_pct is in same units as grid_range_pct (percentage points)
        result = f.check("ETH-USD", grid_range_pct=4.0, num_grids=3, atr_pct=3.0)
        # effective = min(2.0, 6.0) = 2.0
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 2.0)

    # ---- Disabled filter ----

    def test_disabled_filter_always_passes(self):
        f = self._make_filter(enabled=False)
        result = f.check("FET-USD", grid_range_pct=0.1, num_grids=10)
        self.assertTrue(result.passed)

    # ---- Edge cases ----

    def test_zero_grids_treated_as_one(self):
        f = self._make_filter()
        # num_grids=0 edge → should not crash
        result = f.check("SOL-USD", grid_range_pct=2.0, num_grids=0)
        # num_grids=0, so grid_spread_pct = grid_range_pct (not 1 path)
        self.assertIsInstance(result, FeeCheckResult)

    def test_negative_atr_ignored(self):
        f = self._make_filter()
        result = f.check("SOL-USD", grid_range_pct=4.0, num_grids=3, atr_pct=-1.0)
        # negative ATR → uses grid_spread_pct directly
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.grid_spread_pct, 2.0)

    def test_none_config_uses_defaults(self):
        f = FeeAwareFilter(config=None, log=logging.getLogger("test"))
        self.assertTrue(f.enabled)
        self.assertAlmostEqual(f.taker_fee_pct, 0.26)
        self.assertAlmostEqual(f.min_net_profit_pct, 0.3)

    # ---- Profitability estimation ----

    def test_estimate_grid_profitability(self):
        f = self._make_filter()
        est = f.estimate_grid_profitability(
            symbol="LINK-USD",
            grid_range_pct=4.0,
            num_grids=3,
            total_amount_quote=150.0,
            expected_fill_rate=0.5,
        )
        self.assertIn("symbol", est)
        self.assertEqual(est["symbol"], "LINK-USD")
        self.assertIn("estimated_net_profit", est)

    def test_check_result_reason_contains_info(self):
        f = self._make_filter()
        result = f.check("SOL-USD", grid_range_pct=4.0, num_grids=3)
        self.assertIn("spread", result.reason.lower())
        self.assertIn("fees", result.reason.lower())


if __name__ == "__main__":
    unittest.main()
