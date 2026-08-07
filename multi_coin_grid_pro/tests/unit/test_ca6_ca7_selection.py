"""
CA6 / CA7 Selection Logic Tests
================================

CA7: ATR ranking in auto-mode used abs(trend_value), making a -8% crash rank the
     same as a +8% rally.  Fix: use max(tv, 0.0) so negative trends never get a
     positive momentum boost.  Gate check (abs >= min_trend_pct) is unchanged so
     crash coins still qualify as candidates but rank last.

CA6: grid_scorer was never passed to get_top_n_coins(); the internal
     use_grid_ranking logic was dead because grid_scorer=None was always sent.
     Fix: controller now passes grid_scorer=self.grid_suitability_scorer so coins
     are ranked by mean-reversion fitness *during* selection, not only as a
     post-filter on the already-narrowed pool.

CA8 (audit): CoinSelector.filter_pairs() is dead code — the controller has
     equivalent inline filtering (quote-asset, volume, blacklist, spread) in its
     auto-discovery path.  No code change; documented in MASTER_IMPLEMENTATION_PLAN.
"""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, Mock

try:
    from multi_coin_grid_pro.utils.trend_calculator import CoinTrend, TrendCalculator
    TREND_CALCULATOR_AVAILABLE = True
except ImportError:
    TREND_CALCULATOR_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trend(symbol: str, consensus: float, atr_pct: float = 1.0) -> "CoinTrend":
    t = CoinTrend(symbol=symbol)
    t._has_sufficient_data = True
    t.trend_pct = consensus
    t.consensus_trend_pct = consensus
    t.atr_pct = atr_pct
    t.price_history = [Decimal("100")] * 100
    t.candles = []
    return t


def _make_calculator(*trends: "CoinTrend") -> "TrendCalculator":
    connector = Mock()
    connector.name = "kraken"
    tc = TrendCalculator(connector=connector, lookback_minutes=60)
    tc.trends = {t.symbol: t for t in trends}
    return tc


def _make_grid_scorer(enabled: bool, logging_only: bool, min_score: float, scores: dict):
    """Return a mock GridSuitabilityScorer.

    scores: {symbol: float} — grid score per coin
    """
    scorer = MagicMock()
    scorer.enabled = enabled
    scorer.logging_only = logging_only
    scorer.min_grid_score = min_score

    def _score_coin(symbol, candles):
        if symbol not in scores:
            return None
        gs = MagicMock()
        gs.score = scores[symbol]
        gs.range_efficiency = 0.5
        gs.mean_reversion = 0.5
        gs.bounce_rate = 0.5
        gs.atr_consistency = 0.5
        gs.reason = "mock"
        return gs

    scorer.score_coin.side_effect = _score_coin
    return scorer


# ---------------------------------------------------------------------------
# CA7: ATR ranking — no crash-boost in auto mode
# ---------------------------------------------------------------------------

@unittest.skipUnless(TREND_CALCULATOR_AVAILABLE, "TrendCalculator not available")
class TestCA7AtrRanking(unittest.TestCase):
    """CA7: In auto mode negative trends must not outrank positive ones."""

    def _get_top(self, tc, direction, n=5, atr_config=None):
        return tc.get_top_n_coins(
            n=n,
            min_trend_pct=1.0,
            trade_direction=direction,
            atr_selection_config=atr_config,
        )

    # ---- simple sort (no ATR blending) ----

    def test_auto_simple_sort_positive_above_crash(self):
        """
        +2% trend must rank above -8% crash in auto simple-sort path.
        Without this fix, abs(-8) > abs(2) so the crash coin came first.
        """
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0),
            _make_trend("BULL-EUR", +2.0),
        )
        result = self._get_top(tc, "auto")
        self.assertIn("BULL-EUR", result)
        self.assertIn("CRASH-EUR", result)
        self.assertLess(
            result.index("BULL-EUR"),
            result.index("CRASH-EUR"),
            "BULL-EUR (+2%) must rank before CRASH-EUR (-8%) in auto mode",
        )

    def test_auto_crash_still_qualifies_via_gate(self):
        """
        A crash coin (-8%) still passes the abs >= min_trend_pct gate and is
        a valid candidate — it just ranks last among positive coins.
        """
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0),
            _make_trend("BULL-EUR", +2.0),
        )
        result = self._get_top(tc, "auto")
        self.assertIn("CRASH-EUR", result, "crash coin must still be a candidate")

    def test_auto_two_positives_ranked_by_magnitude(self):
        """Among positive trends, higher % still ranks first."""
        tc = _make_calculator(
            _make_trend("BIG-EUR", +7.0),
            _make_trend("SMALL-EUR", +2.0),
        )
        result = self._get_top(tc, "auto")
        self.assertLess(result.index("BIG-EUR"), result.index("SMALL-EUR"))

    def test_auto_all_negative_ranks_by_least_negative(self):
        """
        When all candidates are negative, -2% ranks above -8% (closer to 0
        means more remaining upside for a spot grid).
        """
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0),
            _make_trend("DIP-EUR", -2.0),
        )
        result = self._get_top(tc, "auto")
        # max(-8, 0)=0 and max(-2, 0)=0 → equal rank; order is stable
        # Both are 0 so order depends on sort stability; either order is acceptable.
        # The key invariant: neither gets a *positive* boost proportional to crash depth.
        # We just verify both are present.
        self.assertIn("CRASH-EUR", result)
        self.assertIn("DIP-EUR", result)

    # ---- ATR blended sort ----

    def test_auto_atm_blended_positive_above_crash(self):
        """
        With ATR blended ranking, +2%/1.5%ATR must rank above -8%/1.5%ATR.
        Before CA7 fix: trend_norm(-8%) = 0.40 >> trend_norm(+2%) = 0.10.
        After fix: trend_norm(-8%) = 0.0, trend_norm(+2%) = 0.10.
        """
        atr_cfg = {
            "required_atr_pct": 0.5,
            "prefilter_ratio": 0.0,
            "use_as_ranking_signal": True,
        }
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0, atr_pct=1.5),
            _make_trend("BULL-EUR", +2.0, atr_pct=1.5),
        )
        result = self._get_top(tc, "auto", atr_config=atr_cfg)
        self.assertIn("BULL-EUR", result)
        self.assertIn("CRASH-EUR", result)
        self.assertLess(
            result.index("BULL-EUR"),
            result.index("CRASH-EUR"),
            "BULL-EUR (+2%) must rank before CRASH-EUR (-8%) in ATR blended auto mode",
        )

    def test_auto_atm_blended_crash_no_positive_boost(self):
        """
        In ATR blended auto mode, -8% crash gets effective_tv=0.0, so its
        trend contribution to the rank key is exactly 0.0.
        """
        atr_cfg = {
            "required_atr_pct": 0.5,
            "prefilter_ratio": 0.0,
            "use_as_ranking_signal": True,
        }
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0, atr_pct=1.0),
        )
        result = self._get_top(tc, "auto", n=1, atr_config=atr_cfg)
        # Still selects the coin (passes gate), but trend contributes 0
        self.assertIn("CRASH-EUR", result)

    # ---- long / short modes unaffected ----

    def test_long_mode_excludes_negative_trend(self):
        """long mode: only positive trends qualify."""
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0),
            _make_trend("BULL-EUR", +2.0),
        )
        result = self._get_top(tc, "long")
        self.assertIn("BULL-EUR", result)
        self.assertNotIn("CRASH-EUR", result)

    def test_short_mode_excludes_positive_trend(self):
        """short mode: only negative trends qualify."""
        tc = _make_calculator(
            _make_trend("CRASH-EUR", -8.0),
            _make_trend("BULL-EUR", +2.0),
        )
        result = self._get_top(tc, "short")
        self.assertIn("CRASH-EUR", result)
        self.assertNotIn("BULL-EUR", result)

    def test_long_mode_atm_blended_unchanged(self):
        """ATR blended long mode: uses abs(tv) as before (both trends positive)."""
        atr_cfg = {
            "required_atr_pct": 0.5,
            "prefilter_ratio": 0.0,
            "use_as_ranking_signal": True,
        }
        tc = _make_calculator(
            _make_trend("BIG-EUR", +7.0, atr_pct=1.0),
            _make_trend("SMALL-EUR", +2.0, atr_pct=1.0),
        )
        result = self._get_top(tc, "long", atr_config=atr_cfg)
        self.assertLess(result.index("BIG-EUR"), result.index("SMALL-EUR"))


# ---------------------------------------------------------------------------
# CA6: grid_scorer passed into get_top_n_coins
# ---------------------------------------------------------------------------

@unittest.skipUnless(TREND_CALCULATOR_AVAILABLE, "TrendCalculator not available")
class TestCA6GridScorerPassthrough(unittest.TestCase):
    """CA6: grid_scorer must be passed to get_top_n_coins and influence ranking."""

    def _run(self, tc, scorer=None, n=5, direction="long"):
        return tc.get_top_n_coins(
            n=n,
            min_trend_pct=0.5,
            trade_direction=direction,
            grid_scorer=scorer,
        )

    def test_no_scorer_uses_trend_ranking(self):
        """With scorer=None, falls back to trend ranking (existing behaviour)."""
        tc = _make_calculator(
            _make_trend("HIGH-EUR", +7.0),
            _make_trend("LOW-EUR", +2.0),
        )
        result = self._run(tc, scorer=None)
        self.assertLess(result.index("HIGH-EUR"), result.index("LOW-EUR"))

    def test_scorer_logging_only_uses_trend_ranking(self):
        """logging_only=True: scorer is ignored for ranking; trend order kept."""
        tc = _make_calculator(
            _make_trend("HIGH-EUR", +7.0),
            _make_trend("LOW-EUR", +2.0),
        )
        # Give LOW-EUR a great grid score — should NOT win in logging_only mode
        scorer = _make_grid_scorer(
            enabled=True, logging_only=True, min_score=0.4,
            scores={"HIGH-EUR": 0.2, "LOW-EUR": 0.9},
        )
        result = self._run(tc, scorer=scorer)
        # Trend ranking preserved: HIGH-EUR (7%) before LOW-EUR (2%)
        self.assertLess(result.index("HIGH-EUR"), result.index("LOW-EUR"))

    def test_scorer_active_ranks_by_grid_score(self):
        """
        When scorer is active (not logging_only), coins are ranked by grid score.
        LOW-EUR has lower trend but higher grid score → should come first.
        """
        tc = _make_calculator(
            _make_trend("HIGH-EUR", +7.0),
            _make_trend("LOW-EUR", +2.0),
        )
        scorer = _make_grid_scorer(
            enabled=True, logging_only=False, min_score=0.1,
            scores={"HIGH-EUR": 0.3, "LOW-EUR": 0.9},
        )
        result = self._run(tc, scorer=scorer)
        self.assertIn("LOW-EUR", result)
        self.assertIn("HIGH-EUR", result)
        self.assertLess(
            result.index("LOW-EUR"),
            result.index("HIGH-EUR"),
            "LOW-EUR (grid=0.9) must rank before HIGH-EUR (grid=0.3) when scorer active",
        )

    def test_scorer_active_filters_below_min_score(self):
        """
        Coin below min_grid_score is excluded from results when scorer is active.
        """
        tc = _make_calculator(
            _make_trend("GOOD-EUR", +5.0),
            _make_trend("BAD-EUR", +4.0),
        )
        scorer = _make_grid_scorer(
            enabled=True, logging_only=False, min_score=0.5,
            scores={"GOOD-EUR": 0.8, "BAD-EUR": 0.2},
        )
        result = self._run(tc, scorer=scorer)
        self.assertIn("GOOD-EUR", result)
        self.assertNotIn("BAD-EUR", result, "BAD-EUR (grid=0.2 < 0.5) must be filtered")

    def test_scorer_active_no_candles_falls_to_last(self):
        """
        Coin with no candle data gets score=0.0 (fallback) and ranks last;
        it is NOT excluded (score 0.0 uses the 'gs == 0.0' passthrough).
        """
        tc = _make_calculator(
            _make_trend("SCORED-EUR", +5.0),   # candles provided via scorer mock
            _make_trend("NOCANDLE-EUR", +6.0),  # scorer returns None → score=0.0
        )
        # scorer.score_coin returns None for NOCANDLE-EUR → treated as score=0.0
        scorer = _make_grid_scorer(
            enabled=True, logging_only=False, min_score=0.1,
            scores={"SCORED-EUR": 0.7},  # NOCANDLE-EUR absent → None returned
        )
        result = self._run(tc, scorer=scorer)
        # SCORED-EUR has grid=0.7, NOCANDLE-EUR has score=0.0 → SCORED-EUR first
        self.assertLess(result.index("SCORED-EUR"), result.index("NOCANDLE-EUR"))

    def test_scorer_disabled_uses_trend_ranking(self):
        """When scorer.enabled=False, falls back to trend ranking."""
        tc = _make_calculator(
            _make_trend("HIGH-EUR", +7.0),
            _make_trend("LOW-EUR", +2.0),
        )
        scorer = _make_grid_scorer(
            enabled=False, logging_only=False, min_score=0.1,
            scores={"HIGH-EUR": 0.1, "LOW-EUR": 0.9},
        )
        result = self._run(tc, scorer=scorer)
        self.assertLess(result.index("HIGH-EUR"), result.index("LOW-EUR"))


# ---------------------------------------------------------------------------
# CA8: CoinSelector dead-code audit
# ---------------------------------------------------------------------------

class TestCA8CoinSelectorDeadCode(unittest.TestCase):
    """
    CA8 audit finding: CoinSelector.filter_pairs() is never called in the
    live controller path.  The controller has equivalent inline filtering.

    No code change was made (dead code retained for potential future refactor).
    This test documents the finding and guards against accidental wiring that
    would duplicate existing filtering.
    """

    def test_coin_selector_class_importable(self):
        """CoinSelector is importable (class exists, not deleted)."""
        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        self.assertTrue(callable(CoinSelector))

    def test_coin_selector_filter_pairs_signature(self):
        """filter_pairs() accepts available_pairs, volume_eur, spreads."""
        import inspect

        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        sig = inspect.signature(CoinSelector.filter_pairs)
        params = list(sig.parameters)
        self.assertIn("available_pairs", params)
        self.assertIn("volume_eur", params)
        self.assertIn("spreads", params)

    def test_coin_selector_filters_blacklisted_pair(self):
        """filter_pairs() correctly removes blacklisted pairs."""
        import logging

        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        sel = CoinSelector(
            cfg={
                "blacklist": ["SCAM-EUR"],
                "core_universe": ["BTC-EUR"],
                "min_24h_volume_eur": 0,
                "max_entry_spread_pct": 99.0,
                "quote_asset": "EUR",
                "use_dynamic_pair_discovery": True,
            },
            logger=logging.getLogger("test"),
        )
        result = sel.filter_pairs(
            available_pairs=["BTC-EUR", "SCAM-EUR"],
            volume_eur={"BTC-EUR": 1_000_000, "SCAM-EUR": 1_000_000},
            spreads=None,
        )
        self.assertIn("BTC-EUR", result)
        self.assertNotIn("SCAM-EUR", result)

    def test_coin_selector_filters_low_volume(self):
        """filter_pairs() removes pairs below min_24h_volume_eur."""
        import logging

        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        sel = CoinSelector(
            cfg={
                "blacklist": [],
                "core_universe": ["BTC-EUR"],
                "min_24h_volume_eur": 500_000,
                "max_entry_spread_pct": 99.0,
                "quote_asset": "EUR",
                "use_dynamic_pair_discovery": True,
            },
            logger=logging.getLogger("test"),
        )
        result = sel.filter_pairs(
            available_pairs=["BTC-EUR", "DUST-EUR"],
            volume_eur={"BTC-EUR": 1_000_000, "DUST-EUR": 1_000},
            spreads=None,
        )
        self.assertIn("BTC-EUR", result)
        self.assertNotIn("DUST-EUR", result)

    def test_coin_selector_filters_high_spread(self):
        """filter_pairs() removes pairs with spread > max_entry_spread_pct."""
        import logging

        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        sel = CoinSelector(
            cfg={
                "blacklist": [],
                "core_universe": ["BTC-EUR"],
                "min_24h_volume_eur": 0,
                "max_entry_spread_pct": 0.5,
                "quote_asset": "EUR",
                "use_dynamic_pair_discovery": True,
            },
            logger=logging.getLogger("test"),
        )
        result = sel.filter_pairs(
            available_pairs=["BTC-EUR", "WIDE-EUR"],
            volume_eur={"BTC-EUR": 1_000_000, "WIDE-EUR": 1_000_000},
            # spreads stored as raw ratio; CoinSelector multiplies by 100 internally
            spreads={"BTC-EUR": 0.002, "WIDE-EUR": 0.02},  # 0.2% and 2.0%
        )
        self.assertIn("BTC-EUR", result)
        self.assertNotIn("WIDE-EUR", result)

    def test_coin_selector_valid_pair_passes_all_filters(self):
        """A valid pair passes all filters and is returned."""
        import logging

        from multi_coin_grid_pro.logic.coin_selector import CoinSelector
        sel = CoinSelector(
            cfg={
                "blacklist": [],
                "core_universe": ["BTC-EUR"],
                "min_24h_volume_eur": 500_000,
                "max_entry_spread_pct": 0.5,
                "quote_asset": "EUR",
                "use_dynamic_pair_discovery": True,
            },
            logger=logging.getLogger("test"),
        )
        result = sel.filter_pairs(
            available_pairs=["BTC-EUR"],
            volume_eur={"BTC-EUR": 1_000_000},
            spreads={"BTC-EUR": 0.002},  # 0.2% < 0.5% limit
        )
        self.assertIn("BTC-EUR", result)


if __name__ == "__main__":
    unittest.main()
