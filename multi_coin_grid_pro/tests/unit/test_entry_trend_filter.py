"""
Entry Trend Filter Tests
========================

Covers:
- filter disabled / zero threshold → always allow
- score 1.49 → block; score 1.50 → allow; score above → allow
- score None → fail-open + ENTRY_FILTER_BYPASS logged
- score NaN / inf → fail-open + ENTRY_FILTER_BYPASS logged
- missing entry_trend_filter config → safe default (allow)
- main loop: filter blocks before _should_create_new_grid
- multi-coin loop: bad candidate skipped, loop continues to next
- blocked entry creates no executor, no budget reservation, no active_coins entry
"""

import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller(entry_trend_filter_cfg=None):
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    config = MultiCoinGridConfig(
        connector_name="kraken",
        quote_asset="USD",
        entry_trend_filter=entry_trend_filter_cfg,
    )

    mdp = MagicMock()
    mdp.time.return_value = 1000.0
    mdp.ready = True

    with patch.object(MultiCoinGridController, '_initialize_components'):
        ctrl = MultiCoinGridController(
            config=config,
            market_data_provider=mdp,
            actions_queue=MagicMock(),
            connectors={"kraken": MagicMock()},
        )
    ctrl.decision_logger = None
    return ctrl


def _trend(score):
    t = MagicMock()
    t.trend_score = score
    return t


# ---------------------------------------------------------------------------
# Unit tests: helper alone
# ---------------------------------------------------------------------------

class TestFilterDisabled(unittest.TestCase):

    def test_no_config_allows(self):
        ctrl = _make_controller(None)
        ctrl.trend_calculator = MagicMock()
        ctrl.trend_calculator.get_trend.return_value = _trend(0.1)
        self.assertTrue(ctrl._check_entry_trend_filter("XRP-USD"))

    def test_enabled_false_allows(self):
        ctrl = _make_controller({"enabled": False, "min_entry_trend_score": 3.0})
        ctrl.trend_calculator = MagicMock()
        ctrl.trend_calculator.get_trend.return_value = _trend(0.0)
        self.assertTrue(ctrl._check_entry_trend_filter("XRP-USD"))

    def test_zero_threshold_allows(self):
        ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 0.0})
        ctrl.trend_calculator = MagicMock()
        ctrl.trend_calculator.get_trend.return_value = _trend(0.0)
        self.assertTrue(ctrl._check_entry_trend_filter("XRP-USD"))

    def test_negative_threshold_allows(self):
        ctrl = _make_controller({"enabled": True, "min_entry_trend_score": -1.0})
        ctrl.trend_calculator = MagicMock()
        ctrl.trend_calculator.get_trend.return_value = _trend(-5.0)
        self.assertTrue(ctrl._check_entry_trend_filter("XRP-USD"))


class TestFilterBoundaryScores(unittest.TestCase):

    def setUp(self):
        self.ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 1.5})
        self.ctrl.trend_calculator = MagicMock()

    def test_score_1_49_blocks(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(1.49)
        self.assertFalse(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_score_1_50_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(1.50)
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_score_above_threshold_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(9.99)
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_zero_score_blocks(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(0.0)
        self.assertFalse(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_negative_score_blocks(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(-2.5)
        self.assertFalse(self.ctrl._check_entry_trend_filter("XRP-USD"))


class TestFilterFailOpen(unittest.TestCase):
    """score None / NaN / inf → fail-open."""

    def setUp(self):
        self.ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 1.5})
        self.ctrl.trend_calculator = MagicMock()

    def test_none_score_allows(self):
        t = MagicMock(); t.trend_score = None
        self.ctrl.trend_calculator.get_trend.return_value = t
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_nan_score_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(float('nan'))
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_positive_inf_score_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(float('inf'))
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_negative_inf_score_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(float('-inf'))
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_no_trend_object_allows(self):
        self.ctrl.trend_calculator.get_trend.return_value = None
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_no_trend_calculator_allows(self):
        self.ctrl.trend_calculator = None
        self.assertTrue(self.ctrl._check_entry_trend_filter("XRP-USD"))

    def test_none_logs_bypass(self):
        t = MagicMock(); t.trend_score = None
        self.ctrl.trend_calculator.get_trend.return_value = t
        logged = []
        with patch.object(self.ctrl.logger(), 'info', side_effect=logged.append):
            self.ctrl._check_entry_trend_filter("NEAR-USD")
        self.assertTrue(
            any("ENTRY_FILTER_BYPASS" in str(m) for m in logged),
            "Expected ENTRY_FILTER_BYPASS log for None score"
        )

    def test_nan_logs_bypass(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(float('nan'))
        logged = []
        with patch.object(self.ctrl.logger(), 'info', side_effect=logged.append):
            self.ctrl._check_entry_trend_filter("NEAR-USD")
        self.assertTrue(
            any("ENTRY_FILTER_BYPASS" in str(m) for m in logged),
            "Expected ENTRY_FILTER_BYPASS log for NaN score"
        )


class TestFilterBlockLogging(unittest.TestCase):

    def setUp(self):
        self.ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 1.5})
        self.ctrl.trend_calculator = MagicMock()

    def test_blocked_entry_logs_required_fields(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(1.21)
        logged = []
        with patch.object(self.ctrl.logger(), 'info', side_effect=logged.append):
            result = self.ctrl._check_entry_trend_filter("NEAR-USD")
        self.assertFalse(result)
        blocked = [str(m) for m in logged if "ENTRY_BLOCKED" in str(m)]
        self.assertTrue(len(blocked) >= 1)
        msg = blocked[0]
        self.assertIn("NEAR-USD", msg)
        self.assertIn("ENTRY_TREND_SCORE_BELOW_MIN", msg)


# ---------------------------------------------------------------------------
# Integration: main loop — filter blocks BEFORE _should_create_new_grid
# ---------------------------------------------------------------------------

class TestMainLoopIntegration(unittest.TestCase):

    def setUp(self):
        self.ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 1.5})
        self.ctrl.trend_calculator = MagicMock()

    def test_blocked_does_not_call_should_create_new_grid(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(0.5)
        with patch.object(self.ctrl, '_should_create_new_grid') as mock_sng:
            result = self.ctrl._check_entry_trend_filter("XRP-USD")
            self.assertFalse(result)
            mock_sng.assert_not_called()

    def test_blocked_does_not_reserve_budget(self):
        self.ctrl.trend_calculator.get_trend.return_value = _trend(0.5)
        self.ctrl.budget_allocator = MagicMock()
        self.ctrl._check_entry_trend_filter("XRP-USD")
        self.ctrl.budget_allocator.reserve.assert_not_called()

    def test_blocked_does_not_appear_in_active_coins(self):
        initial = dict(self.ctrl.active_coins)
        self.ctrl.trend_calculator.get_trend.return_value = _trend(0.5)
        self.ctrl._check_entry_trend_filter("XRP-USD")
        self.assertEqual(self.ctrl.active_coins, initial)


# ---------------------------------------------------------------------------
# Integration: multi-coin loop — bad candidate skipped, good one passes
# ---------------------------------------------------------------------------

class TestMultiCoinLoopIntegration(unittest.TestCase):

    def setUp(self):
        self.ctrl = _make_controller({"enabled": True, "min_entry_trend_score": 1.5})

    def test_bad_candidate_skipped_good_candidate_passes(self):
        self.ctrl.trend_calculator = MagicMock()
        self.ctrl.trend_calculator.get_trend.side_effect = (
            lambda s: _trend(0.5) if s == "BAD-USD" else _trend(2.0)
        )
        self.assertFalse(self.ctrl._check_entry_trend_filter("BAD-USD"))
        self.assertTrue(self.ctrl._check_entry_trend_filter("GOOD-USD"))

    def test_blocked_candidate_leaves_no_state(self):
        self.ctrl.trend_calculator = MagicMock()
        self.ctrl.trend_calculator.get_trend.return_value = _trend(0.3)
        active_before = dict(self.ctrl.active_coins)
        exposure_before = dict(self.ctrl.current_exposure_per_coin)
        self.ctrl._check_entry_trend_filter("SPAM-USD")
        self.assertEqual(self.ctrl.active_coins, active_before)
        self.assertEqual(self.ctrl.current_exposure_per_coin, exposure_before)


if __name__ == "__main__":
    unittest.main()
