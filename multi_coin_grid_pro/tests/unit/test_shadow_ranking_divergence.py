"""FIX for A/B shadow validation: both ranking variants must reach materially
different conclusions on the exact same underlying candidate data — proving
the ranking divergence is real, not just a theoretical code path.

Uses ``TrendCalculator.__new__`` (bypassing its connector-requiring
``__init__``, same established pattern as the live-controller unit tests) so
this test needs zero network access and zero live connector.
"""
import logging
import time
from decimal import Decimal

from multi_coin_grid_pro.utils.grid_suitability_scorer import GridSuitabilityScorer
from multi_coin_grid_pro.utils.trend_calculator import CandleData, CoinTrend, TrendCalculator


def _make_trend(symbol: str, deltas, consensus_trend_pct: float) -> CoinTrend:
    """Synthetic CoinTrend with both `candles` (GridSuitabilityScorer input)
    and `price_history` (>=20 entries, required by `has_sufficient_data`,
    the real pre-filter gate `get_top_n_coins` uses) populated consistently."""
    candles = []
    price_history = []
    base = 100.0
    now = time.time()
    for i, delta in enumerate(deltas):
        base += delta
        ts = now - (len(deltas) - i) * 300
        candles.append(CandleData(
            timestamp=ts, open=Decimal(str(base)), high=Decimal(str(base + 0.5)),
            low=Decimal(str(base - 0.5)), close=Decimal(str(base)), volume=Decimal("1000"),
        ))
        price_history.append({"price": base, "timestamp": ts})
    return CoinTrend(
        symbol=symbol, current_price=Decimal(str(base)),
        consensus_trend_pct=consensus_trend_pct, candles=candles, price_history=price_history,
    )


def _make_calculator(trends: dict) -> TrendCalculator:
    tc = TrendCalculator.__new__(TrendCalculator)
    tc.trends = trends
    tc.connector = type("FakeConnector", (), {"name": "kraken"})()
    tc._permanently_failed_symbols = set()
    return tc


def _scorer() -> GridSuitabilityScorer:
    return GridSuitabilityScorer(
        config={"enabled": True, "logging_only": False, "min_grid_score": 0.0, "lookback_candles": 48},
        logger=logging.getLogger("test"),
    )


HIGHTREND_DELTAS = [0.3] * 60  # steady one-directional move: high trend, low grid-suitability
CHOPPY_DELTAS = ([1, -0.8, 0.9, -1.0, 0.8, -0.9, 1.0, -0.8] * 7) + [0.2]  # bouncy: low trend, high grid-suitability


def test_variant_a_and_b_select_different_coins_on_identical_data():
    """Core proof: with the real, unmodified get_top_n_coins() and the same
    self.trends state, passing grid_scorer changes which coin wins."""
    trends = {
        "HIGHTREND-USD": _make_trend("HIGHTREND-USD", HIGHTREND_DELTAS, consensus_trend_pct=20.0),
        "CHOPPY-USD": _make_trend("CHOPPY-USD", CHOPPY_DELTAS, consensus_trend_pct=1.0),
    }
    tc = _make_calculator(trends)
    scorer = _scorer()

    variant_a = tc.get_top_n_coins(n=1, min_trend_pct=0.0, grid_scorer=None)
    variant_b = tc.get_top_n_coins(n=1, min_trend_pct=0.0, grid_scorer=scorer)

    assert variant_a == ["HIGHTREND-USD"], "Variant A (70/30 trend+ATR) must pick the higher-trend coin"
    assert variant_b == ["CHOPPY-USD"], "Variant B (grid suitability) must pick the more mean-reverting coin"
    assert variant_a != variant_b


def test_both_variants_see_the_full_candidate_pool_not_a_pre_filtered_subset():
    """Regression guard for the exact bug under test: variant B must be able
    to choose a coin even if it would rank low/last under variant A's own
    internal sort, as long as it's in the shared `self.trends` pool."""
    trends = {
        "HIGHTREND-USD": _make_trend("HIGHTREND-USD", HIGHTREND_DELTAS, consensus_trend_pct=20.0),
        "MIDTREND-USD": _make_trend("MIDTREND-USD", [0.1] * 60, consensus_trend_pct=5.0),
        "CHOPPY-USD": _make_trend("CHOPPY-USD", CHOPPY_DELTAS, consensus_trend_pct=1.0),
    }
    tc = _make_calculator(trends)
    scorer = _scorer()

    # Variant A's own ranking would put CHOPPY-USD last (lowest trend).
    variant_a_full = tc.get_top_n_coins(n=3, min_trend_pct=0.0, grid_scorer=None)
    assert variant_a_full[-1] == "CHOPPY-USD"

    # Variant B, scoring the SAME pool, must still be able to promote it to first.
    variant_b_full = tc.get_top_n_coins(n=3, min_trend_pct=0.0, grid_scorer=scorer)
    assert variant_b_full[0] == "CHOPPY-USD"


def test_no_lookahead_ranking_only_uses_data_already_in_self_trends():
    """The ranking call takes no "future" parameter at all — it is a pure
    function of the already-populated self.trends state at call time. This
    test documents/pins that contract: appending a trend AFTER the call
    cannot have affected a result already returned."""
    trends = {
        "A-USD": _make_trend("A-USD", HIGHTREND_DELTAS, consensus_trend_pct=20.0),
    }
    tc = _make_calculator(trends)
    result_before = tc.get_top_n_coins(n=5, min_trend_pct=0.0, grid_scorer=None)
    assert result_before == ["A-USD"]

    # Simulate a coin that will only become known/qualifying "later".
    tc.trends["B-USD"] = _make_trend("B-USD", [5.0] * 60, consensus_trend_pct=300.0)
    result_after = tc.get_top_n_coins(n=5, min_trend_pct=0.0, grid_scorer=None)
    assert "B-USD" in result_after and result_before != result_after, (
        "Sanity check: the new coin must now appear now it's genuinely present; "
        "this is the inverse proof that it could not have appeared beforehand."
    )
