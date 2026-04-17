"""Tests for RegimeCoinSelector (regime-first coin selection)."""
import logging
import unittest
from unittest.mock import MagicMock

from multi_coin_grid_pro.logic.regime_coin_selector import RegimeCoinSelector


class TestRegimeCoinSelector(unittest.TestCase):
    """Tests for regime-first coin selection logic."""

    def setUp(self):
        self.log = logging.getLogger("test")
        self.trend_calc = MagicMock()
        self.grid_scorer = MagicMock()
        self.grid_scorer.enabled = True
        # Default: get_trend returns a mild trend (within CHOP bounds)
        self.trend_calc.get_trend.return_value = MagicMock(
            consensus_trend_pct=1.0
        )

    def _make_selector(self, **overrides):
        config = {
            'bear_allow_trading': False,
            'bear_max_grids': 0,
            'chop_use_grid_ranking': True,
            'bull_use_grid_ranking': False,
        }
        config.update(overrides)
        return RegimeCoinSelector(config=config, log=self.log)

    # ---- BEAR regime ----

    def test_bear_sit_out_by_default(self):
        sel = self._make_selector()
        result = sel.select(
            regime="BEAR", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        self.assertEqual(result, [])
        self.trend_calc.get_top_n_coins.assert_not_called()

    def test_bear_allowed_but_zero_grids(self):
        sel = self._make_selector(bear_allow_trading=True, bear_max_grids=0)
        result = sel.select(
            regime="BEAR", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        self.assertEqual(result, [])

    def test_bear_allowed_with_limited_grids(self):
        self.trend_calc.get_top_n_coins.return_value = ["SOL-USD"]
        sel = self._make_selector(bear_allow_trading=True, bear_max_grids=1)
        sel.select(
            regime="BEAR", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=3, min_trend_pct=0.007,
        )
        # n capped to bear_max_grids=1
        self.trend_calc.get_top_n_coins.assert_called_once()
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertEqual(call_kwargs.kwargs.get('n', call_kwargs[1].get('n')), 1)

    # ---- CHOP regime ----

    def test_chop_uses_grid_ranking(self):
        self.trend_calc.get_top_n_coins.return_value = ["LINK-USD", "DOT-USD"]
        sel = self._make_selector(chop_use_grid_ranking=True)
        result = sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        self.assertEqual(result, ["LINK-USD", "DOT-USD"])
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertIs(call_kwargs.kwargs.get('grid_scorer'), self.grid_scorer)

    def test_chop_fallback_when_no_scorer(self):
        self.trend_calc.get_top_n_coins.return_value = ["LINK-USD"]
        sel = self._make_selector(chop_use_grid_ranking=True)
        sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=None, n=2, min_trend_pct=0.007,
        )
        # Falls back to trend ranking (no grid_scorer kwarg)
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertNotIn('grid_scorer', call_kwargs.kwargs)

    def test_chop_disabled_grid_ranking(self):
        self.trend_calc.get_top_n_coins.return_value = ["LINK-USD"]
        sel = self._make_selector(chop_use_grid_ranking=False)
        sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        # Trend ranking used (no grid_scorer kwarg)
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertNotIn('grid_scorer', call_kwargs.kwargs)

    # ---- BULL regime ----

    def test_bull_uses_trend_ranking(self):
        self.trend_calc.get_top_n_coins.return_value = ["BTC-USD", "ETH-USD"]
        sel = self._make_selector(bull_use_grid_ranking=False)
        result = sel.select(
            regime="BULL", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        self.assertEqual(result, ["BTC-USD", "ETH-USD"])
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        # No grid_scorer → trend ranking
        self.assertIsNone(call_kwargs.kwargs.get('grid_scorer'))

    def test_bull_with_grid_ranking(self):
        self.trend_calc.get_top_n_coins.return_value = ["SOL-USD"]
        sel = self._make_selector(bull_use_grid_ranking=True)
        sel.select(
            regime="BULL", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=1, min_trend_pct=0.007,
        )
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertIs(call_kwargs.kwargs.get('grid_scorer'), self.grid_scorer)

    # ---- Edge cases ----

    def test_none_regime_defaults_to_chop(self):
        self.trend_calc.get_top_n_coins.return_value = []
        sel = self._make_selector()
        sel.select(
            regime=None, trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=1, min_trend_pct=0.007,
        )
        # CHOP path triggered (grid ranking)
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertIs(call_kwargs.kwargs.get('grid_scorer'), self.grid_scorer)

    def test_unknown_regime_defaults_to_bull(self):
        self.trend_calc.get_top_n_coins.return_value = []
        sel = self._make_selector()
        sel.select(
            regime="MEGA_BULL", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=1, min_trend_pct=0.007,
        )
        # Falls to BULL (else branch)
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertIsNone(call_kwargs.kwargs.get('grid_scorer'))

    def test_exclude_coins_forwarded(self):
        self.trend_calc.get_top_n_coins.return_value = ["ETH-USD"]
        sel = self._make_selector()
        sel.select(
            regime="BULL", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
            exclude_coins=["FET-USD", "DOGE-USD"],
        )
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        self.assertEqual(
            call_kwargs.kwargs.get('exclude_coins'),
            ["FET-USD", "DOGE-USD"],
        )

    def test_get_selection_mode(self):
        sel = self._make_selector()
        self.assertEqual(sel.get_selection_mode("BEAR"), "BEAR:sit_out")
        self.assertIn("CHOP:grid_suitability", sel.get_selection_mode("CHOP"))
        self.assertEqual(sel.get_selection_mode("BULL"), "BULL:trend_momentum")

        sel2 = self._make_selector(
            bear_allow_trading=True, chop_use_grid_ranking=False,
            bull_use_grid_ranking=True,
        )
        self.assertEqual(sel2.get_selection_mode("BEAR"), "BEAR:cautious_grid")
        self.assertEqual(sel2.get_selection_mode("CHOP"), "CHOP:trend_fallback")
        self.assertEqual(sel2.get_selection_mode("BULL"), "BULL:grid_suitability")

    def test_empty_config_uses_defaults(self):
        sel = RegimeCoinSelector(config={}, log=self.log)
        self.assertFalse(sel.bear_allow_trading)
        self.assertTrue(sel.chop_use_grid_ranking)
        self.assertFalse(sel.bull_use_grid_ranking)

    def test_none_config_uses_defaults(self):
        sel = RegimeCoinSelector(config=None, log=self.log)
        self.assertFalse(sel.bear_allow_trading)

    # ---- CHOP trend bounds ----

    def test_chop_uses_low_min_trend(self):
        """CHOP should use chop_min_trend_pct, not the normal min_trend_pct."""
        self.trend_calc.get_top_n_coins.return_value = ["LINK-USD"]
        sel = self._make_selector(chop_min_trend_pct=0.001)
        sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        # Should use 0.001 (chop floor), NOT 0.007 (normal floor)
        self.assertAlmostEqual(
            call_kwargs.kwargs.get('min_trend_pct'), 0.001
        )

    def test_chop_filters_too_trendy_coins(self):
        """CHOP should exclude coins with |trend| > chop_max_trend_pct."""
        # Return 3 candidates from get_top_n_coins
        self.trend_calc.get_top_n_coins.return_value = [
            "LINK-USD", "FET-USD", "DOT-USD"
        ]
        # Mock get_trend: FET has 5% trend (too trendy)
        mock_trends = {
            "LINK-USD": MagicMock(consensus_trend_pct=1.2),
            "FET-USD": MagicMock(consensus_trend_pct=5.0),
            "DOT-USD": MagicMock(consensus_trend_pct=0.8),
        }
        self.trend_calc.get_trend.side_effect = lambda s: mock_trends.get(s)

        sel = self._make_selector(chop_max_trend_pct=3.0)
        result = sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        # FET-USD should be excluded (5% > 3%)
        self.assertNotIn("FET-USD", result)
        self.assertIn("LINK-USD", result)
        self.assertIn("DOT-USD", result)

    def test_chop_default_bounds(self):
        """Default chop bounds should be sensible."""
        sel = self._make_selector()
        self.assertAlmostEqual(sel.chop_min_trend_pct, 0.001)
        self.assertAlmostEqual(sel.chop_max_trend_pct, 3.0)

    def test_chop_overfetches_for_post_filter(self):
        """CHOP should over-fetch (n*3) to allow post-filter headroom."""
        self.trend_calc.get_top_n_coins.return_value = []
        sel = self._make_selector()
        sel.select(
            regime="CHOP", trend_calculator=self.trend_calc,
            grid_scorer=self.grid_scorer, n=2, min_trend_pct=0.007,
        )
        call_kwargs = self.trend_calc.get_top_n_coins.call_args
        # n=2 → should request n*3=6 from get_top_n_coins
        self.assertEqual(call_kwargs.kwargs.get('n'), 6)


if __name__ == "__main__":
    unittest.main()
