# test_signal_buy_now_scorer.py — unit tests for BuyNowScorer (US-202).
# All tests are pure / deterministic. No I/O, no network.
import pytest

from multi_coin_grid_pro.signals.momentum_buy_now_scorer import (
    BuyNowScoreBreakdown,
    BuyNowScorer,
    _acceleration_component,
    _liquidity_score,
    _risk_score,
    _short_momentum_score,
    _volume_spike_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCandidate:
    """Minimal fake EnrichedCandidate for scorer tests."""

    def __init__(
        self,
        price_change_3m_pct=None,
        price_change_5m_pct=None,
        price_change_15m_pct=None,
        acceleration_score=None,
        volume_ratio=None,
        spread_pct=0.10,
        slippage_100eur=None,
    ):
        self.price_change_3m_pct = price_change_3m_pct
        self.price_change_5m_pct = price_change_5m_pct
        self.price_change_15m_pct = price_change_15m_pct
        self.acceleration_score = acceleration_score
        self.volume_ratio = volume_ratio
        self.spread_pct = spread_pct
        self.slippage_100eur = slippage_100eur


def _strong_candidate() -> _FakeCandidate:
    """A clearly strong buy-now candidate."""
    return _FakeCandidate(
        price_change_3m_pct=1.2,
        price_change_5m_pct=2.0,
        price_change_15m_pct=3.5,
        acceleration_score=1.0,
        volume_ratio=4.0,
        spread_pct=0.05,
        slippage_100eur=0.05,
    )


def _weak_candidate() -> _FakeCandidate:
    """A candidate with minimal values — should score near 0."""
    return _FakeCandidate(
        price_change_3m_pct=0.0,
        price_change_5m_pct=0.0,
        price_change_15m_pct=0.0,
        acceleration_score=0.0,
        volume_ratio=1.0,
        spread_pct=0.35,
        slippage_100eur=0.50,
    )


# ---------------------------------------------------------------------------
# _short_momentum_score
# ---------------------------------------------------------------------------

class TestShortMomentumScore:

    def test_both_none_returns_zero(self):
        assert _short_momentum_score(None, None) == 0.0

    def test_p3m_none_returns_zero(self):
        assert _short_momentum_score(None, 2.0) == 0.0

    def test_p5m_none_returns_zero(self):
        assert _short_momentum_score(1.0, None) == 0.0

    def test_both_zero_returns_zero(self):
        assert _short_momentum_score(0.0, 0.0) == 0.0

    def test_full_score_at_upper_bounds(self):
        # p3=1.5, p5=2.5 → both saturate → score = 1.0
        result = _short_momentum_score(1.5, 2.5)
        assert result == pytest.approx(1.0)

    def test_above_bounds_capped_at_1(self):
        result = _short_momentum_score(5.0, 10.0)
        assert result == pytest.approx(1.0)

    def test_half_scores_average(self):
        # p3=0.75 → s3=0.5; p5=1.25 → s5=0.5 → avg = 0.5
        result = _short_momentum_score(0.75, 1.25)
        assert result == pytest.approx(0.5)

    def test_negative_values_clamp_to_zero(self):
        # Negative moves score 0
        result = _short_momentum_score(-2.0, -3.0)
        assert result == 0.0


# ---------------------------------------------------------------------------
# _acceleration_component
# ---------------------------------------------------------------------------

class TestAccelerationComponent:

    def test_none_returns_zero(self):
        assert _acceleration_component(None) == 0.0

    def test_zero_returns_zero(self):
        assert _acceleration_component(0.0) == 0.0

    def test_1_returns_1(self):
        assert _acceleration_component(1.0) == pytest.approx(1.0)

    def test_07_returns_07(self):
        assert _acceleration_component(0.7) == pytest.approx(0.7)

    def test_04_returns_04(self):
        assert _acceleration_component(0.4) == pytest.approx(0.4)

    def test_above_1_capped_at_1(self):
        assert _acceleration_component(2.0) == pytest.approx(1.0)

    def test_negative_clamped_to_zero(self):
        assert _acceleration_component(-0.5) == 0.0


# ---------------------------------------------------------------------------
# _volume_spike_score
# ---------------------------------------------------------------------------

class TestVolumeSpikeScore:

    def test_none_returns_zero(self):
        assert _volume_spike_score(None) == 0.0

    def test_below_1x_returns_zero(self):
        assert _volume_spike_score(0.5) == 0.0

    def test_exactly_1x_returns_zero(self):
        assert _volume_spike_score(1.0) == 0.0

    def test_5x_returns_1(self):
        # (5.0 - 1.0) / 4.0 = 1.0
        assert _volume_spike_score(5.0) == pytest.approx(1.0)

    def test_above_5x_capped_at_1(self):
        assert _volume_spike_score(10.0) == pytest.approx(1.0)

    def test_3x_returns_half(self):
        # (3.0 - 1.0) / 4.0 = 0.5
        assert _volume_spike_score(3.0) == pytest.approx(0.5)

    def test_2x_returns_025(self):
        # (2.0 - 1.0) / 4.0 = 0.25
        assert _volume_spike_score(2.0) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# _liquidity_score
# ---------------------------------------------------------------------------

class TestLiquidityScore:

    def test_zero_spread_no_slippage_returns_1(self):
        # Perfect spread, no slippage data → spread_score=1.0
        assert _liquidity_score(0.0, None) == pytest.approx(1.0)

    def test_max_spread_returns_zero(self):
        # spread=0.35 → spread_score = 0; no slippage
        assert _liquidity_score(0.35, None) == pytest.approx(0.0, abs=1e-6)

    def test_above_max_spread_clamped_to_zero(self):
        assert _liquidity_score(1.0, None) == pytest.approx(0.0, abs=1e-6)

    def test_half_spread_no_slippage_returns_half(self):
        # spread=0.175 → spread_score = 0.5; no slippage
        assert _liquidity_score(0.175, None) == pytest.approx(0.5)

    def test_zero_spread_zero_slippage_returns_1(self):
        # Both perfect
        assert _liquidity_score(0.0, 0.0) == pytest.approx(1.0)

    def test_max_slippage_reduces_score(self):
        # spread=0 (spread_score=1.0), slippage=0.50 (slip_score=0.0)
        # 0.6 * 1.0 + 0.4 * 0.0 = 0.6
        result = _liquidity_score(0.0, 0.50)
        assert result == pytest.approx(0.6)

    def test_combined_spread_and_slippage(self):
        # spread=0.175 → spread_score=0.5; slippage=0.25 → slip_score=0.5
        # 0.6 * 0.5 + 0.4 * 0.5 = 0.5
        result = _liquidity_score(0.175, 0.25)
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _risk_score
# ---------------------------------------------------------------------------

class TestRiskScore:

    def test_both_none_returns_1(self):
        # No data → no penalty
        assert _risk_score(None, None) == pytest.approx(1.0)

    def test_small_moves_near_1(self):
        # Δ5m=1%, Δ15m=3% → minimal penalty
        result = _risk_score(1.0, 3.0)
        assert result > 0.5

    def test_spike_5m_reduces_risk(self):
        # Δ5m=4.5 → fully penalized → 0.0; Δ15m=None
        result = _risk_score(4.5, None)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_extended_15m_reduces_risk(self):
        # Δ15m=9.0 → fully penalized → 0.0; Δ5m=None
        result = _risk_score(None, 9.0)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_both_max_returns_zero(self):
        assert _risk_score(4.5, 9.0) == pytest.approx(0.0, abs=1e-6)

    def test_negative_values_treated_as_zero(self):
        # Negative moves: no lateness risk
        result = _risk_score(-1.0, -5.0)
        assert result == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# BuyNowScorer — score_candidate
# ---------------------------------------------------------------------------

class TestBuyNowScorerScoreCandidate:

    def test_returns_float_between_0_and_1(self):
        scorer = BuyNowScorer()
        c = _strong_candidate()
        score = scorer.score_candidate(c)
        assert 0.0 <= score <= 1.0

    def test_strong_candidate_scores_high(self):
        scorer = BuyNowScorer()
        score = scorer.score_candidate(_strong_candidate())
        assert score >= 0.55  # should at least reach WATCH threshold

    def test_weak_candidate_scores_low(self):
        scorer = BuyNowScorer()
        score = scorer.score_candidate(_weak_candidate())
        assert score < 0.30

    def test_all_none_fields_scores_low(self):
        # Only spread is available (required field)
        scorer = BuyNowScorer()
        c = _FakeCandidate(spread_pct=0.20)
        score = scorer.score_candidate(c)
        # liquidity component still contributes
        assert 0.0 <= score <= 1.0

    def test_max_acceleration_boosts_score(self):
        scorer = BuyNowScorer()
        c_low = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=2.0,
            acceleration_score=0.0, volume_ratio=3.0, spread_pct=0.10,
        )
        c_high = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=2.0,
            acceleration_score=1.0, volume_ratio=3.0, spread_pct=0.10,
        )
        assert scorer.score_candidate(c_high) > scorer.score_candidate(c_low)

    def test_high_slippage_reduces_score(self):
        scorer = BuyNowScorer()
        c_clean = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=2.0,
            acceleration_score=1.0, volume_ratio=4.0,
            spread_pct=0.05, slippage_100eur=0.0,
        )
        c_dirty = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=2.0,
            acceleration_score=1.0, volume_ratio=4.0,
            spread_pct=0.05, slippage_100eur=0.50,
        )
        assert scorer.score_candidate(c_clean) > scorer.score_candidate(c_dirty)

    def test_spike_move_scores_lower_than_steady_move(self):
        scorer = BuyNowScorer()
        c_steady = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=2.0, price_change_15m_pct=3.5,
            acceleration_score=1.0, volume_ratio=4.0, spread_pct=0.05,
        )
        c_spike = _FakeCandidate(
            price_change_3m_pct=1.0, price_change_5m_pct=4.4, price_change_15m_pct=8.9,
            acceleration_score=1.0, volume_ratio=4.0, spread_pct=0.05,
        )
        assert scorer.score_candidate(c_steady) > scorer.score_candidate(c_spike)


# ---------------------------------------------------------------------------
# BuyNowScorer — score_breakdown
# ---------------------------------------------------------------------------

class TestBuyNowScorerBreakdown:

    def test_returns_breakdown_object(self):
        scorer = BuyNowScorer()
        result = scorer.score_breakdown(_strong_candidate())
        assert isinstance(result, BuyNowScoreBreakdown)

    def test_total_equals_weighted_sum(self):
        scorer = BuyNowScorer()
        c = _strong_candidate()
        bd = scorer.score_breakdown(c)
        expected = (
            0.30 * bd.short_momentum
            + 0.25 * bd.acceleration
            + 0.20 * bd.volume_spike
            + 0.15 * bd.liquidity
            + 0.10 * bd.risk
        )
        assert bd.total == pytest.approx(expected, abs=1e-4)

    def test_all_components_between_0_and_1(self):
        scorer = BuyNowScorer()
        bd = scorer.score_breakdown(_strong_candidate())
        for field_name in ("short_momentum", "acceleration", "volume_spike", "liquidity", "risk"):
            val = getattr(bd, field_name)
            assert 0.0 <= val <= 1.0, f"{field_name}={val} out of range"

    def test_total_between_0_and_1(self):
        scorer = BuyNowScorer()
        bd = scorer.score_breakdown(_strong_candidate())
        assert 0.0 <= bd.total <= 1.0

    def test_breakdown_matches_score_candidate(self):
        scorer = BuyNowScorer()
        c = _strong_candidate()
        score = scorer.score_candidate(c)
        bd = scorer.score_breakdown(c)
        assert score == pytest.approx(bd.total, abs=1e-4)

    def test_details_contains_inputs(self):
        scorer = BuyNowScorer()
        c = _strong_candidate()
        bd = scorer.score_breakdown(c)
        assert "price_change_3m_pct" in bd.details
        assert "acceleration_score" in bd.details
        assert bd.details["volume_ratio"] == c.volume_ratio

    def test_weak_candidate_has_low_total(self):
        scorer = BuyNowScorer()
        bd = scorer.score_breakdown(_weak_candidate())
        assert bd.total < 0.30

    def test_strong_candidate_has_high_total(self):
        scorer = BuyNowScorer()
        bd = scorer.score_breakdown(_strong_candidate())
        assert bd.total >= 0.55


# ---------------------------------------------------------------------------
# Threshold behaviour — matches ClassificationConfig defaults
# ---------------------------------------------------------------------------

class TestThresholds:

    def test_watch_threshold_reachable(self):
        """A real-world moderate signal should reach WATCH (≥ 0.55)."""
        scorer = BuyNowScorer()
        # Moderate move with some acceleration
        c = _FakeCandidate(
            price_change_3m_pct=0.9,
            price_change_5m_pct=1.8,
            price_change_15m_pct=3.0,
            acceleration_score=0.7,
            volume_ratio=3.5,
            spread_pct=0.08,
            slippage_100eur=0.05,
        )
        assert scorer.score_candidate(c) >= 0.55

    def test_buy_now_threshold_reachable(self):
        """A strong signal should reach BUY_NOW (≥ 0.72)."""
        scorer = BuyNowScorer()
        c = _FakeCandidate(
            price_change_3m_pct=1.3,
            price_change_5m_pct=2.2,
            price_change_15m_pct=3.8,
            acceleration_score=1.0,
            volume_ratio=5.0,
            spread_pct=0.05,
            slippage_100eur=0.02,
        )
        assert scorer.score_candidate(c) >= 0.72

    def test_too_late_candidate_risk_component_is_near_zero(self):
        """A late spike has a near-zero risk component.

        Note: the scorer does NOT block TOO_LATE signals — that is the job of
        _classify_label() in the service.  The risk dimension (weight 0.10)
        signals lateness but does not override the other strong dimensions.
        """
        scorer = BuyNowScorer()
        c = _FakeCandidate(
            price_change_3m_pct=2.0,
            price_change_5m_pct=4.4,   # near spike threshold
            price_change_15m_pct=8.5,  # near extended-move threshold
            acceleration_score=1.0,
            volume_ratio=5.0,
            spread_pct=0.05,
        )
        bd = scorer.score_breakdown(c)
        # Risk component should be near zero for such an extended move
        assert bd.risk < 0.05
        # Other dimensions should still score high (scorer does not block; classifier does)
        assert bd.short_momentum > 0.9
        assert bd.acceleration == pytest.approx(1.0)
