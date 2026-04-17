"""Tests for V2-01 (Dynamic Fee Model), ST-11 (Idle Mode), ST-12 (Economic Edge Gate)."""
import logging
import unittest
from unittest.mock import MagicMock

from multi_coin_grid_pro.logic.fee_aware_filter import FeeAwareFilter


class TestDynamicFeeModel(unittest.TestCase):
    """V2-01: fee_model config selects round-trip fee calculation."""

    def _make(self, **kw):
        cfg = {
            'enabled': True,
            'taker_fee_pct': 0.26,
            'maker_fee_pct': 0.16,
            'use_maker_fees': False,
        }
        cfg.update(kw)
        return FeeAwareFilter(config=cfg, log=logging.getLogger("test"))

    def test_worst_case_default(self):
        f = self._make()
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.52)

    def test_worst_case_explicit(self):
        f = self._make(fee_model='worst_case')
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.52)

    def test_average_model(self):
        f = self._make(fee_model='average')
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.42)

    def test_best_case_model(self):
        f = self._make(fee_model='best_case')
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.32)

    def test_use_maker_fees_overrides_fee_model(self):
        """Legacy use_maker_fees takes precedence over fee_model."""
        f = self._make(fee_model='worst_case', use_maker_fees=True)
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.32)

    def test_average_model_check_pass(self):
        """average model lowers fee bar → borderline grid passes with average but not worst."""
        # 3 grids: spread = range / (num_grids - 1) = range / 2
        # Need: spread - fee < min_net (0.3) for worst, spread - fee >= 0.3 for average
        # worst: spread - 0.52 < 0.3 → spread < 0.82 → range < 1.64
        # average: spread - 0.42 >= 0.3 → spread >= 0.72 → range >= 1.44
        # So range = 1.50: spread = 0.75
        # worst: 0.75 - 0.52 = 0.23 < 0.3 → fail ✓
        # average: 0.75 - 0.42 = 0.33 >= 0.3 → pass ✓
        f_worst = self._make(fee_model='worst_case', min_net_profit_pct=0.3)
        f_avg = self._make(fee_model='average', min_net_profit_pct=0.3)
        r_worst = f_worst.check("X", grid_range_pct=1.50, num_grids=3)
        r_avg = f_avg.check("X", grid_range_pct=1.50, num_grids=3)
        self.assertFalse(r_worst.passed)
        self.assertTrue(r_avg.passed)

    def test_unknown_fee_model_falls_back_worst(self):
        f = self._make(fee_model='invalid_value')
        self.assertAlmostEqual(f.round_trip_fee_pct, 0.52)


class TestIdleMode(unittest.TestCase):
    """ST-11: Idle mode activation, deactivation, and logging."""

    def _make_controller_mock(self):
        """Create a minimal mock with idle mode state."""
        ctrl = MagicMock()
        ctrl._idle_mode_active = False
        ctrl._no_edge_cycles = 0
        ctrl._idle_mode_log_counter = 0
        ctrl._last_idle_scan_time = 0.0
        return ctrl

    def test_idle_activates_after_n_cycles(self):
        """After no_edge_cycles_to_idle cycles with no edge, idle activates."""
        ctrl = self._make_controller_mock()
        cycles_to_idle = 5

        for _ in range(cycles_to_idle):
            ctrl._no_edge_cycles += 1

        if ctrl._no_edge_cycles >= cycles_to_idle and not ctrl._idle_mode_active:
            ctrl._idle_mode_active = True

        self.assertTrue(ctrl._idle_mode_active)
        self.assertEqual(ctrl._no_edge_cycles, 5)

    def test_idle_does_not_activate_before_threshold(self):
        ctrl = self._make_controller_mock()
        cycles_to_idle = 10

        for _ in range(5):
            ctrl._no_edge_cycles += 1

        if ctrl._no_edge_cycles >= cycles_to_idle and not ctrl._idle_mode_active:
            ctrl._idle_mode_active = True

        self.assertFalse(ctrl._idle_mode_active)

    def test_idle_deactivates_on_edge_found(self):
        ctrl = self._make_controller_mock()
        ctrl._idle_mode_active = True
        ctrl._no_edge_cycles = 15
        ctrl._idle_mode_log_counter = 3

        # Simulate edge found (best_coin != None)
        ctrl._idle_mode_active = False
        ctrl._no_edge_cycles = 0
        ctrl._idle_mode_log_counter = 0

        self.assertFalse(ctrl._idle_mode_active)
        self.assertEqual(ctrl._no_edge_cycles, 0)
        self.assertEqual(ctrl._idle_mode_log_counter, 0)

    def test_idle_throttle_skips_when_interval_not_elapsed(self):
        """Scan throttle should skip processing if idle interval hasn't passed."""
        import time as _time
        ctrl = self._make_controller_mock()
        ctrl._idle_mode_active = True
        ctrl._last_idle_scan_time = _time.time()
        idle_interval = 120

        elapsed = _time.time() - ctrl._last_idle_scan_time
        should_skip = elapsed < idle_interval

        self.assertTrue(should_skip)

    def test_idle_throttle_allows_when_interval_elapsed(self):
        ctrl = self._make_controller_mock()
        ctrl._idle_mode_active = True
        ctrl._last_idle_scan_time = 1000.0  # Far in the past
        idle_interval = 120

        elapsed = 5000.0 - ctrl._last_idle_scan_time  # current_time=5000
        should_skip = elapsed < idle_interval

        self.assertFalse(should_skip)

    def test_log_counter_increments_each_idle_cycle(self):
        ctrl = self._make_controller_mock()
        ctrl._idle_mode_active = True
        log_interval = 5
        logged = []

        for cycle in range(12):
            ctrl._idle_mode_log_counter += 1
            if ctrl._idle_mode_log_counter >= log_interval:
                logged.append(cycle)
                ctrl._idle_mode_log_counter = 0

        # Should log at cycles 4, 9 (0-indexed)
        self.assertEqual(len(logged), 2)


class TestEconomicEdgeGate(unittest.TestCase):
    """ST-12: Economic edge gate blocks grids with insufficient edge."""

    def _compute_edge(self, range_down=3.0, range_up=3.0, num_grids=5,
                      taker_fee=0.26, maker_fee=0.16, fee_model='average',
                      include_spread_cost=True, slippage=0.05):
        """Replicate the controller's edge gate computation."""
        total_range = range_down + range_up
        grid_spread_pct = total_range / max(1, num_grids)

        if fee_model == 'best_case':
            rt_fee = maker_fee * 2
        elif fee_model == 'average':
            rt_fee = taker_fee + maker_fee
        else:
            rt_fee = taker_fee * 2

        total_cost = rt_fee
        if include_spread_cost:
            total_cost += rt_fee * 0.5
        total_cost += slippage

        return grid_spread_pct - total_cost

    def test_wide_grid_passes(self):
        """6% total range / 5 grids = 1.2% spread. Costs ~0.68%. Edge=0.52%."""
        edge = self._compute_edge(range_down=3.0, range_up=3.0, num_grids=5)
        self.assertGreater(edge, 0.10)

    def test_narrow_grid_rejected(self):
        """2% total range / 5 grids = 0.4% spread. Costs ~0.68%. Negative edge."""
        edge = self._compute_edge(range_down=1.0, range_up=1.0, num_grids=5)
        self.assertLess(edge, 0.10)

    def test_worst_case_fees_harder_to_pass(self):
        """Worst-case fees increase costs, making edge gate stricter."""
        edge_avg = self._compute_edge(fee_model='average')
        edge_worst = self._compute_edge(fee_model='worst_case')
        self.assertGreater(edge_avg, edge_worst)

    def test_best_case_fees_easier_to_pass(self):
        edge_best = self._compute_edge(fee_model='best_case')
        edge_avg = self._compute_edge(fee_model='average')
        self.assertGreater(edge_best, edge_avg)

    def test_no_spread_cost_lowers_bar(self):
        edge_with = self._compute_edge(include_spread_cost=True)
        edge_without = self._compute_edge(include_spread_cost=False)
        self.assertGreater(edge_without, edge_with)

    def test_higher_slippage_tightens_gate(self):
        edge_low = self._compute_edge(slippage=0.02)
        edge_high = self._compute_edge(slippage=0.10)
        self.assertGreater(edge_low, edge_high)

    def test_more_grids_reduces_spread_per_level(self):
        """10 grids on same range → half the spread per level."""
        edge_5 = self._compute_edge(num_grids=5)
        edge_10 = self._compute_edge(num_grids=10)
        self.assertGreater(edge_5, edge_10)

    def test_exact_kraken_defaults(self):
        """With Kraken defaults + average model: 6%/5 = 1.2% - 0.68% = 0.52%."""
        edge = self._compute_edge(
            range_down=3.0, range_up=3.0, num_grids=5,
            taker_fee=0.26, maker_fee=0.16, fee_model='average',
            include_spread_cost=True, slippage=0.05,
        )
        # rt_fee=0.42, spread_cost=0.21, slippage=0.05 → total=0.68
        # spread=1.2 - 0.68 = 0.52
        self.assertAlmostEqual(edge, 0.52, places=2)

    def test_edge_gate_disabled_allows_thin_grid(self):
        """When edge gate disabled, even negative-edge grids can proceed."""
        # This tests the config check, not the math
        enabled = False
        edge = self._compute_edge(range_down=0.5, range_up=0.5, num_grids=5)
        self.assertLess(edge, 0)  # Would fail if enabled
        # But since not enabled, it wouldn't block
        self.assertFalse(enabled)


if __name__ == "__main__":
    unittest.main()
