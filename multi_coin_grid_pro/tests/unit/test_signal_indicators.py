# test_signal_indicators.py — unit tests for momentum_indicators.py
# All tests are pure / deterministic. No I/O, no network.
from multi_coin_grid_pro.signals.momentum_indicators import (
    acceleration_score,
    apply_candle_metrics,
    apply_orderbook_metrics,
    estimate_slippage_pct,
    orderbook_depth_quote,
    orderbook_imbalance,
    price_change_pct,
    volatility_pct,
    volume_ratio,
)
from multi_coin_grid_pro.signals.momentum_models import CandleSnapshot, EnrichedCandidate, OrderBookSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(closes, volume=100.0, end_ts: float = 10000.0):
    """Build a list of CandleSnapshots with the given close prices.

    Candles are 1-minute apart, with the newest ending at ``end_ts``.
    ``apply_candle_metrics`` requires the newest candle to be <120s old;
    pass ``now=end_ts + 60`` in those tests.
    """
    n = len(closes)
    return [
        CandleSnapshot(
            timestamp=end_ts - (n - 1 - i) * 60,
            open=c, high=c, low=c, close=c, volume=volume,
        )
        for i, c in enumerate(closes)
    ]


def _make_ob(bids=None, asks=None, fetched_at=1000.0):
    return OrderBookSnapshot(
        fetched_at=fetched_at,
        bids=bids or [],
        asks=asks or [],
    )


def _make_candidate():
    return EnrichedCandidate(
        exchange="kraken",
        trading_pair="SOL-USD",
        price=100.0,
        bid=99.9,
        ask=100.1,
        spread_pct=0.2,
    )


# ---------------------------------------------------------------------------
# price_change_pct
# ---------------------------------------------------------------------------

class TestPriceChangePct:

    def test_5m_positive(self):
        candles = _make_candles([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        # 6 candles, n=5: (close[-1] - close[-6]) / close[-6] * 100 = 5/100*100 = 5%
        result = price_change_pct(candles, 5)
        assert result is not None
        assert abs(result - 5.0) < 0.001

    def test_15m_positive(self):
        closes = list(range(100, 117))  # 100..116 → 17 candles
        candles = _make_candles(closes)
        result = price_change_pct(candles, 15)
        # (116 - 101) / 101 * 100
        expected = (116 - 101) / 101 * 100.0
        assert result is not None
        assert abs(result - expected) < 0.001

    def test_negative_price_change(self):
        candles = _make_candles([110.0, 109.0, 108.0, 107.0, 106.0, 105.0])
        result = price_change_pct(candles, 5)
        assert result is not None
        assert result < 0

    def test_insufficient_candles_returns_none(self):
        # Need n_periods+1 candles; with n=5, need 6
        candles = _make_candles([100.0, 101.0, 102.0, 103.0, 104.0])
        assert price_change_pct(candles, 5) is None

    def test_exactly_enough_candles(self):
        candles = _make_candles([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        result = price_change_pct(candles, 5)
        assert result is not None

    def test_zero_close_ago_returns_none(self):
        candles = _make_candles([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        assert price_change_pct(candles, 5) is None

    def test_empty_candles_returns_none(self):
        assert price_change_pct([], 5) is None

    def test_1m_change(self):
        candles = _make_candles([100.0, 102.0])
        result = price_change_pct(candles, 1)
        assert result is not None
        assert abs(result - 2.0) < 0.001

    def test_flat_market_zero(self):
        candles = _make_candles([100.0] * 10)
        assert price_change_pct(candles, 5) == 0.0


# ---------------------------------------------------------------------------
# volume_ratio
# ---------------------------------------------------------------------------

class TestVolumeRatio:

    def test_high_recent_volume(self):
        # baseline_n=15 candles with vol=10, recent_n=5 candles with vol=50
        baseline = _make_candles(range(15), volume=10.0)
        recent = _make_candles(range(15, 20), volume=50.0)
        candles = baseline + recent
        result = volume_ratio(candles, recent_n=5, baseline_n=15)
        assert result is not None
        assert abs(result - 5.0) < 0.001

    def test_equal_volume_ratio_is_one(self):
        candles = _make_candles(range(20), volume=10.0)
        result = volume_ratio(candles, recent_n=5, baseline_n=15)
        assert result is not None
        assert abs(result - 1.0) < 0.001

    def test_insufficient_candles_returns_none(self):
        # Need 5+15=20 candles; only 19
        candles = _make_candles(range(19), volume=10.0)
        assert volume_ratio(candles, recent_n=5, baseline_n=15) is None

    def test_exactly_enough_candles(self):
        candles = _make_candles(range(20), volume=10.0)
        result = volume_ratio(candles, recent_n=5, baseline_n=15)
        assert result is not None

    def test_zero_baseline_returns_none(self):
        baseline = _make_candles(range(15), volume=0.0)
        recent = _make_candles(range(15, 20), volume=10.0)
        candles = baseline + recent
        assert volume_ratio(candles, recent_n=5, baseline_n=15) is None

    def test_empty_candles_returns_none(self):
        assert volume_ratio([], recent_n=5, baseline_n=15) is None


# ---------------------------------------------------------------------------
# volatility_pct
# ---------------------------------------------------------------------------

class TestVolatilityPct:

    def test_stable_price_low_volatility(self):
        candles = _make_candles([100.0] * 20)
        result = volatility_pct(candles)
        assert result is not None
        assert result == 0.0

    def test_volatile_prices_higher_value(self):
        closes = [100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0, 105.0,
                  100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0, 105.0]
        candles = _make_candles(closes)
        result = volatility_pct(candles)
        assert result is not None
        assert result > 1.0

    def test_single_candle_returns_none(self):
        assert volatility_pct(_make_candles([100.0])) is None

    def test_empty_candles_returns_none(self):
        assert volatility_pct([]) is None

    def test_two_candles_returns_value(self):
        candles = _make_candles([100.0, 102.0])
        result = volatility_pct(candles)
        # With 2 candles, only 1 return → stdev needs >= 2 values → None
        assert result is None

    def test_three_candles_ok(self):
        candles = _make_candles([100.0, 102.0, 101.0])
        result = volatility_pct(candles)
        assert result is not None


# ---------------------------------------------------------------------------
# orderbook_depth_quote
# ---------------------------------------------------------------------------

class TestOrderbookDepthQuote:

    def test_simple_depth(self):
        bids = [[100.0, 2.0], [99.0, 3.0]]
        asks = [[101.0, 1.5], [102.0, 2.5]]
        ob = _make_ob(bids=bids, asks=asks)
        result = orderbook_depth_quote(ob, depth=20)
        # 100*2 + 99*3 + 101*1.5 + 102*2.5 = 200+297+151.5+255 = 903.5
        assert result is not None
        assert abs(result - 903.5) < 0.01

    def test_empty_ob_returns_none(self):
        ob = _make_ob(bids=[], asks=[])
        assert orderbook_depth_quote(ob) is None

    def test_depth_limits_levels(self):
        bids = [[100.0 - i, 1.0] for i in range(30)]  # 30 bid levels
        asks = [[101.0 + i, 1.0] for i in range(30)]  # 30 ask levels
        ob = _make_ob(bids=bids, asks=asks)
        result_20 = orderbook_depth_quote(ob, depth=20)
        result_5 = orderbook_depth_quote(ob, depth=5)
        assert result_5 < result_20

    def test_only_bids(self):
        bids = [[100.0, 5.0]]
        ob = _make_ob(bids=bids, asks=[])
        result = orderbook_depth_quote(ob)
        assert result is not None
        assert abs(result - 500.0) < 0.01

    def test_only_asks(self):
        asks = [[100.0, 3.0]]
        ob = _make_ob(bids=[], asks=asks)
        result = orderbook_depth_quote(ob)
        assert result is not None
        assert abs(result - 300.0) < 0.01


# ---------------------------------------------------------------------------
# orderbook_imbalance
# ---------------------------------------------------------------------------

class TestOrderbookImbalance:

    def test_balanced_ob(self):
        bids = [[100.0, 5.0]]
        asks = [[101.0, 5.0]]
        ob = _make_ob(bids=bids, asks=asks)
        result = orderbook_imbalance(ob)
        # bid_depth=500, ask_depth=505 (different prices but same amount)
        assert result is not None
        assert 0.0 < result < 1.0

    def test_bid_heavy(self):
        bids = [[100.0, 10.0]]
        asks = [[101.0, 1.0]]
        ob = _make_ob(bids=bids, asks=asks)
        result = orderbook_imbalance(ob)
        assert result is not None
        # bid_depth=1000, ask_depth=101 → > 0.9
        assert result > 0.9

    def test_ask_heavy(self):
        bids = [[100.0, 1.0]]
        asks = [[101.0, 10.0]]
        ob = _make_ob(bids=bids, asks=asks)
        result = orderbook_imbalance(ob)
        assert result is not None
        assert result < 0.5

    def test_empty_ob_returns_none(self):
        ob = _make_ob(bids=[], asks=[])
        assert orderbook_imbalance(ob) is None

    def test_result_is_between_0_and_1(self):
        bids = [[100.0, 3.0], [99.0, 2.0]]
        asks = [[101.0, 1.0], [102.0, 4.0]]
        ob = _make_ob(bids=bids, asks=asks)
        result = orderbook_imbalance(ob)
        assert result is not None
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# apply_candle_metrics
# ---------------------------------------------------------------------------

class TestApplyCandleMetrics:

    def test_all_metrics_filled_when_enough_candles(self):
        # Need 20 candles for volume_ratio (5+15), and 16 for p15m
        candles = _make_candles(range(100, 120), volume=10.0)
        candidate = _make_candidate()
        now = 10060.0  # newest candle is at 10000, 60s old — within 120s threshold
        apply_candle_metrics(candidate, candles, now=now)
        assert candidate.candles_fetched_at == now
        assert candidate.price_change_1m_pct is not None
        assert candidate.price_change_3m_pct is not None
        assert candidate.price_change_5m_pct is not None
        assert candidate.price_change_15m_pct is not None
        assert candidate.volume_ratio is not None
        assert candidate.volatility_pct is not None
        assert candidate.acceleration_score is not None  # set (may be 0.0)

    def test_empty_candles_does_not_modify_candidate(self):
        candidate = _make_candidate()
        apply_candle_metrics(candidate, [], now=9999.0)
        assert candidate.candles_fetched_at == 0.0
        assert candidate.price_change_5m_pct is None

    def test_partial_candles_yields_nones(self):
        # Only 10 candles — not enough for p15m (needs 16) or volume_ratio (needs 20)
        candles = _make_candles(range(100, 110), volume=10.0)
        candidate = _make_candidate()
        apply_candle_metrics(candidate, candles, now=10060.0)  # newest candle at 10000, 60s old
        assert candidate.price_change_3m_pct is not None    # needs 4
        assert candidate.price_change_5m_pct is not None  # needs 6
        assert candidate.price_change_15m_pct is None     # needs 16
        assert candidate.volume_ratio is None              # needs 20

    def test_3m_requires_at_least_4_candles(self):
        # Exactly 3 candles: price_change_3m_pct needs 4 (n_periods+1), should be None
        candles = _make_candles([100.0, 101.0, 102.0])
        candidate = _make_candidate()
        apply_candle_metrics(candidate, candles, now=10060.0)
        assert candidate.price_change_3m_pct is None

    def test_3m_with_exactly_4_candles_is_not_none(self):
        # _make_candles with end_ts=10000: newest candle at 10000, now=10060 → age=60s → OK
        candles = _make_candles([100.0, 101.0, 102.0, 103.0])
        candidate = _make_candidate()
        apply_candle_metrics(candidate, candles, now=10060.0)
        assert candidate.price_change_3m_pct is not None

    def test_stale_candles_leave_metrics_as_none(self):
        # Newest candle is >120s old → metrics must not be applied
        candles = _make_candles(range(100, 120), volume=10.0)  # newest at ts=10000
        candidate = _make_candidate()
        apply_candle_metrics(candidate, candles, now=10300.0)  # 300s after newest candle
        assert candidate.candles_fetched_at == 0.0  # not set
        assert candidate.price_change_3m_pct is None
        assert candidate.price_change_5m_pct is None
        assert candidate.price_change_15m_pct is None
        assert candidate.volume_ratio is None


# ---------------------------------------------------------------------------
# apply_orderbook_metrics
# ---------------------------------------------------------------------------

class TestApplyOrderbookMetrics:

    def test_metrics_written_to_candidate(self):
        bids = [[100.0, 5.0], [99.0, 3.0]]
        asks = [[101.0, 4.0], [102.0, 2.0]]
        ob = _make_ob(bids=bids, asks=asks, fetched_at=8888.0)
        candidate = _make_candidate()
        apply_orderbook_metrics(candidate, ob)
        assert candidate.ob_fetched_at == 8888.0
        assert candidate.orderbook_depth_quote is not None
        assert candidate.orderbook_imbalance is not None

    def test_slippage_fields_set(self):
        # asks: 101@4 + 102@2 → enough depth for €100 and €250
        asks = [[101.0, 4.0], [102.0, 2.0]]
        ob = _make_ob(asks=asks, fetched_at=1000.0)
        candidate = _make_candidate()
        apply_orderbook_metrics(candidate, ob)
        # €100 order: 100/101 ≈ 0.99 base → avg_fill = 101 → slippage = 0%
        assert candidate.slippage_100eur is not None
        assert candidate.slippage_100eur >= 0.0
        assert candidate.slippage_250eur is not None

    def test_slippage_none_on_empty_orderbook(self):
        ob = _make_ob(bids=[], asks=[], fetched_at=1000.0)
        candidate = _make_candidate()
        apply_orderbook_metrics(candidate, ob)
        assert candidate.slippage_100eur is None
        assert candidate.slippage_250eur is None

    def test_empty_ob_depth_is_none(self):
        ob = _make_ob(bids=[], asks=[], fetched_at=8888.0)
        candidate = _make_candidate()
        apply_orderbook_metrics(candidate, ob)
        assert candidate.orderbook_depth_quote is None

    def test_fetched_at_written(self):
        ob = _make_ob(bids=[[100.0, 1.0]], asks=[], fetched_at=12345.0)
        candidate = _make_candidate()
        apply_orderbook_metrics(candidate, ob)
        assert candidate.ob_fetched_at == 12345.0


# ---------------------------------------------------------------------------
# acceleration_score
# ---------------------------------------------------------------------------

class TestAccelerationScore:

    def test_all_thresholds_met_returns_1(self):
        # Δ1m=0.25%, Δ3m=0.7%, Δ5m=1.2% → 1.0
        assert acceleration_score(0.25, 0.7, 1.2) == 1.0

    def test_above_all_thresholds_returns_1(self):
        assert acceleration_score(1.0, 2.0, 3.0) == 1.0

    def test_3m_and_5m_met_but_not_1m_returns_07(self):
        # Δ1m < 0.25 but Δ3m ≥ 0.7 and Δ5m ≥ 1.2 → 0.7
        assert acceleration_score(0.10, 0.8, 1.5) == 0.7

    def test_only_5m_met_returns_04(self):
        # Δ5m ≥ 1.2 but Δ3m < 0.7 → 0.4
        assert acceleration_score(0.10, 0.3, 1.5) == 0.4

    def test_no_thresholds_met_returns_0(self):
        assert acceleration_score(0.05, 0.2, 0.8) == 0.0

    def test_none_p1m_returns_0(self):
        assert acceleration_score(None, 0.8, 1.5) == 0.0

    def test_none_p3m_returns_0(self):
        assert acceleration_score(0.5, None, 1.5) == 0.0

    def test_none_p5m_returns_0(self):
        assert acceleration_score(0.5, 0.8, None) == 0.0

    def test_all_none_returns_0(self):
        assert acceleration_score(None, None, None) == 0.0

    def test_exact_boundary_5m(self):
        # Exactly at 1.2% Δ5m → 0.4 (only 5m met)
        assert acceleration_score(0.0, 0.0, 1.2) == 0.4

    def test_just_below_5m_threshold(self):
        # Δ5m = 1.19% → 0.0
        assert acceleration_score(1.0, 1.0, 1.19) == 0.0


# ---------------------------------------------------------------------------
# estimate_slippage_pct
# ---------------------------------------------------------------------------

class TestEstimateSlippagePct:

    def test_no_asks_returns_none(self):
        ob = _make_ob(bids=[[100.0, 10.0]], asks=[])
        assert estimate_slippage_pct(ob, 100.0) is None

    def test_zero_best_ask_returns_none(self):
        ob = _make_ob(asks=[[0.0, 10.0]])
        assert estimate_slippage_pct(ob, 100.0) is None

    def test_order_too_large_returns_none(self):
        # Single level: 101 × 0.5 = €50.5 — not enough for €100
        ob = _make_ob(asks=[[101.0, 0.5]])
        assert estimate_slippage_pct(ob, 100.0) is None

    def test_exact_fill_at_best_ask_zero_slippage(self):
        # Single level: 100 × 2 = €200, order = €100 → fills entirely at 100
        # avg_fill = 100 = best_ask → slippage = 0%
        ob = _make_ob(asks=[[100.0, 2.0]])
        result = estimate_slippage_pct(ob, 100.0)
        assert result is not None
        assert abs(result) < 0.001

    def test_multi_level_positive_slippage(self):
        # Level 1: 100 × 0.5 = €50 (fills half)
        # Level 2: 110 × 1.0 = €110 (fills rest at higher price)
        # Total base ≈ 0.5 + 50/110 ≈ 0.5 + 0.4545 = 0.9545
        # avg_fill = 100 / 0.9545 ≈ 104.76 → slippage ≈ 4.76%
        ob = _make_ob(asks=[[100.0, 0.5], [110.0, 1.0]])
        result = estimate_slippage_pct(ob, 100.0)
        assert result is not None
        assert result > 0.0  # positive slippage (paying above best ask)

    def test_apply_slippage_sets_both_fields(self):
        asks = [[100.0, 5.0], [101.0, 5.0]]
        ob = _make_ob(asks=asks)
        s100 = estimate_slippage_pct(ob, 100.0)
        s250 = estimate_slippage_pct(ob, 250.0)
        # larger order → same or more slippage
        assert s100 is not None
        assert s250 is not None
        assert s250 >= s100
