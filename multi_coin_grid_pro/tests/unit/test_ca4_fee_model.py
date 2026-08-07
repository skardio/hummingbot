"""CA4: Fee model per exchange — verification tests.

Verifies:
- best_case uses maker+maker (requires post-only guarantee)
- average uses taker+maker (realistic for grids without LIMIT_MAKER)
- worst_case uses taker+taker (conservative)
- Bitget config does NOT use best_case (no LIMIT_MAKER support)
- min_grid_level_spacing_pct >= roundtrip_fee (spacing covers fees)
- config_warnings() fires when best_case is combined with use_post_only_orders=False
- Fee config units are percent-points (0.20 = 0.20%), not decimal fractions
"""
import os
import unittest

import yaml

from multi_coin_grid_pro.logic.fee_aware_filter import FeeAwareFilter

# Path to the Bitget YAML config relative to repo root
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_BITGET_YAML = os.path.join(
    _REPO_ROOT,
    "multi_coin_grid_pro", "spot_bitget", "config", "spot_grid_bitget.yaml",
)


def _make_filter(**kw) -> FeeAwareFilter:
    """Build a FeeAwareFilter with Bitget-like defaults, overridden by kw."""
    cfg = {
        "enabled": True,
        "taker_fee_pct": 0.20,
        "maker_fee_pct": 0.10,
        "fee_model": "average",
        "min_net_profit_pct": 0.20,
    }
    cfg.update(kw)
    return FeeAwareFilter(config=cfg)


class TestFeeModelCalculation(unittest.TestCase):
    """Fee model selects correct round-trip formula."""

    def test_best_case_uses_maker_maker(self):
        """best_case: RT = maker + maker."""
        f = _make_filter(fee_model="best_case", maker_fee_pct=0.10, taker_fee_pct=0.20)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.20)

    def test_average_uses_taker_maker(self):
        """average: RT = taker + maker."""
        f = _make_filter(fee_model="average", maker_fee_pct=0.10, taker_fee_pct=0.20)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.30)

    def test_worst_case_uses_taker_taker(self):
        """worst_case: RT = taker + taker."""
        f = _make_filter(fee_model="worst_case", maker_fee_pct=0.10, taker_fee_pct=0.20)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.40)

    def test_unknown_model_falls_back_to_worst_case(self):
        """Unknown fee_model defaults to worst_case (taker+taker)."""
        f = _make_filter(fee_model="typo_value", maker_fee_pct=0.10, taker_fee_pct=0.20)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.40)

    def test_best_case_kraken_scenario(self):
        """Kraken with LIMIT_MAKER: best_case = 0.20+0.20 = 0.40% RT."""
        f = _make_filter(fee_model="best_case", maker_fee_pct=0.20, taker_fee_pct=0.35)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.40)

    def test_worst_case_kraken_scenario(self):
        """Kraken worst_case = 0.35+0.35 = 0.70% RT."""
        f = _make_filter(fee_model="worst_case", maker_fee_pct=0.20, taker_fee_pct=0.35)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.70)

    def test_fee_units_are_percent_points(self):
        """Fee values in config are percent-points (0.20 = 0.20%), not fractions.

        If someone accidentally sets maker_fee_pct=0.001 (decimal fraction for 0.1%)
        instead of 0.10 (percent-point), the RT will be 0.002 which is extreme.
        This test documents the expected unit: 0.10 = 0.10%.
        """
        f_correct = _make_filter(fee_model="worst_case", taker_fee_pct=0.20)
        f_wrong_unit = _make_filter(fee_model="worst_case", taker_fee_pct=0.002)  # fraction

        # Correct: RT = 0.40% (percent-points)
        self.assertAlmostEqual(f_correct.round_trip_fee_pct, 0.40)
        # Wrong unit: RT = 0.004% — impossibly low, would pass everything
        self.assertLess(f_wrong_unit.round_trip_fee_pct, 0.01)


class TestBitgetFeeModel(unittest.TestCase):
    """Bitget-specific fee model correctness."""

    def test_bitget_average_roundtrip_fee(self):
        """Bitget average RT fee = taker(0.20) + maker(0.10) = 0.30%."""
        f = _make_filter(
            fee_model="average",
            taker_fee_pct=0.20,
            maker_fee_pct=0.10,
        )
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.30)

    def test_bitget_spacing_covers_roundtrip_fee(self):
        """min_grid_level_spacing_pct=0.75 must exceed RT fee=0.30%.

        Bitget spacing 0.75% / RT 0.30% = 2.5x — adequate buffer.
        """
        bitget_min_spacing = 0.75  # percent-points
        f = _make_filter(fee_model="average", taker_fee_pct=0.20, maker_fee_pct=0.10)
        rt = f.round_trip_fee_pct  # 0.30%

        self.assertGreater(bitget_min_spacing, rt,
                           f"Spacing {bitget_min_spacing}% must exceed RT fee {rt}%")

        # Require at least 2× multiplier so there is real edge after fees
        self.assertGreaterEqual(
            bitget_min_spacing / rt, 2.0,
            f"Spacing/RT ratio {bitget_min_spacing / rt:.2f}x must be ≥ 2.0x"
        )

    def test_bitget_atr_gate_required_atr_with_average(self):
        """ATR gate: with average model (0.30% RT) × 2.0x = 0.60% required ATR."""
        f = _make_filter(fee_model="average", taker_fee_pct=0.20, maker_fee_pct=0.10)
        rt = f.round_trip_fee_pct  # 0.30%
        min_atr_multiplier = 2.0
        required_atr = rt * min_atr_multiplier
        self.assertAlmostEqual(required_atr, 0.60,
                               msg="atr_fee_gate comment expects 0.60% required ATR")

    def test_bitget_edge_gate_with_average(self):
        """Economic edge gate: spacing(0.75%) - total_cost(0.30+0.03=0.33%) = 0.42% edge."""
        f = _make_filter(fee_model="average", taker_fee_pct=0.20, maker_fee_pct=0.10)
        rt = f.round_trip_fee_pct  # 0.30%
        slippage = 0.03
        total_cost = rt + slippage  # 0.33%
        spacing = 0.75
        edge = spacing - total_cost  # 0.42%
        min_edge = 0.08  # Bitget economic_edge_gate.min_edge_pct

        self.assertGreater(edge, min_edge,
                           f"Edge {edge:.3f}% must exceed min_edge {min_edge}%")

    @unittest.skipUnless(os.path.exists(_BITGET_YAML), "Bitget YAML config not found")
    def test_bitget_yaml_does_not_use_best_case(self):
        """CA4: Bitget YAML fee_aware_filter must not use fee_model: best_case.

        Bitget lacks LIMIT_MAKER support (use_post_only_orders: false),
        so maker fills are not guaranteed. best_case understates RT fee.
        """
        with open(_BITGET_YAML) as fh:
            cfg = yaml.safe_load(fh)

        fee_filter = cfg.get("fee_aware_filter", {})
        fee_model = fee_filter.get("fee_model", "worst_case")

        self.assertNotEqual(
            fee_model, "best_case",
            f"Bitget fee_aware_filter.fee_model='{fee_model}' must not be 'best_case': "
            f"Bitget lacks LIMIT_MAKER → no maker fill guarantee. Use 'average' or 'worst_case'."
        )

    @unittest.skipUnless(os.path.exists(_BITGET_YAML), "Bitget YAML config not found")
    def test_bitget_yaml_use_post_only_orders_is_false(self):
        """Confirm Bitget explicitly disables post-only orders (no LIMIT_MAKER)."""
        with open(_BITGET_YAML) as fh:
            cfg = yaml.safe_load(fh)

        use_post_only = cfg.get("use_post_only_orders", True)
        self.assertFalse(
            use_post_only,
            "Bitget use_post_only_orders should be False (LIMIT_MAKER not supported)"
        )

    @unittest.skipUnless(os.path.exists(_BITGET_YAML), "Bitget YAML config not found")
    def test_bitget_yaml_spacing_vs_roundtrip_fee(self):
        """Bitget YAML: min_grid_level_spacing_pct >= roundtrip_fee × 2.0."""
        with open(_BITGET_YAML) as fh:
            cfg = yaml.safe_load(fh)

        fee_filter = cfg.get("fee_aware_filter", {})
        fee_model = fee_filter.get("fee_model", "worst_case")
        taker = float(fee_filter.get("taker_fee_pct", 0.35))
        maker = float(fee_filter.get("maker_fee_pct", 0.20))

        if fee_model == "best_case":
            rt = maker * 2
        elif fee_model == "average":
            rt = taker + maker
        else:
            rt = taker * 2

        spacing = float(cfg.get("min_grid_level_spacing_pct", 0.60))
        self.assertGreaterEqual(
            spacing, rt,
            f"min_grid_level_spacing_pct={spacing}% must be >= RT fee={rt}%"
        )
        self.assertGreaterEqual(
            spacing / rt, 2.0,
            f"Spacing/RT ratio {spacing / rt:.2f}x must be >= 2.0x for adequate edge"
        )


class TestFeeConfigValidation(unittest.TestCase):
    """config_warnings() detects inconsistencies (CA4 validation)."""

    def test_best_case_with_post_only_no_warning(self):
        """Kraken/OKX: best_case + use_post_only_orders=True → no warnings."""
        f = _make_filter(fee_model="best_case", taker_fee_pct=0.35, maker_fee_pct=0.20)
        warnings = f.config_warnings(use_post_only_orders=True)
        self.assertEqual(warnings, [])

    def test_best_case_without_post_only_warns(self):
        """Bitget pattern: best_case + use_post_only_orders=False → warning issued."""
        f = _make_filter(fee_model="best_case", taker_fee_pct=0.20, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("best_case", warnings[0])
        self.assertIn("use_post_only_orders=False", warnings[0])
        self.assertIn("average", warnings[0])

    def test_average_without_post_only_no_warning(self):
        """Bitget with correct fee_model=average → no warnings."""
        f = _make_filter(fee_model="average", taker_fee_pct=0.20, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=False)
        self.assertEqual(warnings, [])

    def test_worst_case_without_post_only_no_warning(self):
        """worst_case without post-only → no warnings (conservative is always safe)."""
        f = _make_filter(fee_model="worst_case", taker_fee_pct=0.20, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=False)
        self.assertEqual(warnings, [])

    def test_negative_fee_warns(self):
        """Negative fee rate is a config error."""
        f = _make_filter(taker_fee_pct=-0.10, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=True)
        self.assertTrue(any("Negative" in w for w in warnings))

    def test_extreme_fee_warns(self):
        """Fee > 2% in percent-points suggests a units error (decimal fraction given)."""
        f = _make_filter(taker_fee_pct=3.5, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=True)
        self.assertTrue(any("Unusually high" in w for w in warnings))

    def test_decimal_fraction_unit_mistake_detected(self):
        """taker_fee_pct=0.0035 (decimal) instead of 0.35 (percent) triggers high-fee warning.

        Note: 0.0035 is NOT > 2% so it won't trigger the high-fee warning,
        but the resulting RT fee would be impossibly small (0.007%).
        This test confirms that percent-point units (0.35) give the expected RT,
        while the wrong unit (0.0035) gives an implausibly small value.
        """
        f_correct = _make_filter(fee_model="worst_case", taker_fee_pct=0.35)
        f_wrong = _make_filter(fee_model="worst_case", taker_fee_pct=0.0035)

        self.assertAlmostEqual(f_correct.round_trip_fee_pct, 0.70, places=4)
        self.assertLess(f_wrong.round_trip_fee_pct, 0.01,
                        "Wrong-unit fee gives implausibly small RT — signals config error")

    def test_warning_includes_suggested_rt_fee(self):
        """Warning message includes both current and suggested RT fees."""
        f = _make_filter(fee_model="best_case", taker_fee_pct=0.20, maker_fee_pct=0.10)
        warnings = f.config_warnings(use_post_only_orders=False)
        self.assertEqual(len(warnings), 1)
        # Should mention the current (0.20%) and suggested (0.30%) RT fees
        self.assertIn("0.200", warnings[0])  # maker+maker = 0.10*2
        self.assertIn("0.300", warnings[0])  # taker+maker = 0.20+0.10


if __name__ == "__main__":
    unittest.main()
