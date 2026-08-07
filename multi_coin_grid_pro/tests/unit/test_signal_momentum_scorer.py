# test_signal_momentum_scorer.py — unit tests for momentum_signal_scorer.py
import pytest

from multi_coin_grid_pro.signals.momentum_config import ScoringConfig
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate
from multi_coin_grid_pro.signals.momentum_signal_scorer import SignalScorer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HIGH_MOMENTUM = dict(
    trend_1h=5.0, trend_4h=12.0, volume_expansion=8.0,
    relative_strength=3.0, spread_pct=0.05,
    rsi=55.0, wick_risk=0.1, regime="BULL",
)

LOW_MOMENTUM = dict(
    trend_1h=0.0, trend_4h=0.0, volume_expansion=0.0,
    relative_strength=0.0, spread_pct=1.0,
    rsi=90.0, wick_risk=1.0, regime="BEAR",
)


def make_candidate(
    price: float = 1.0,
    spread_pct: float = 0.10,
    trend_1h: float = 3.0,
    trend_4h: float = 8.0,
    volume_expansion: float = 4.0,
    rsi: float = 60.0,
    wick_risk: float = 0.2,
) -> EnrichedCandidate:
    return EnrichedCandidate(
        exchange="kraken",
        trading_pair="BTC-USD",
        price=price,
        bid=price * 0.999,
        ask=price * 1.001,
        spread_pct=spread_pct,
        trend_1h_pct=trend_1h,
        trend_4h_pct=trend_4h,
        volume_expansion=volume_expansion,
        rsi=rsi,
        wick_risk=wick_risk,
    )


# ---------------------------------------------------------------------------
# score_raw — range and determinism
# ---------------------------------------------------------------------------

class TestScoreRaw:

    def test_returns_float(self) -> None:
        scorer = SignalScorer()
        result = scorer.score_raw(**HIGH_MOMENTUM)
        assert isinstance(result, float)

    def test_never_exceeds_1(self) -> None:
        scorer = SignalScorer()
        assert scorer.score_raw(**HIGH_MOMENTUM) <= 1.0

    def test_non_negative(self) -> None:
        scorer = SignalScorer()
        assert scorer.score_raw(**LOW_MOMENTUM) >= 0.0

    def test_deterministic(self) -> None:
        scorer = SignalScorer()
        assert scorer.score_raw(**HIGH_MOMENTUM) == scorer.score_raw(**HIGH_MOMENTUM)

    def test_high_momentum_scores_above_low(self) -> None:
        scorer = SignalScorer()
        high = scorer.score_raw(**HIGH_MOMENTUM)
        low = scorer.score_raw(**LOW_MOMENTUM)
        assert high > low

    def test_regime_param_accepted_without_error(self) -> None:
        scorer = SignalScorer()
        scorer.score_raw(**{**HIGH_MOMENTUM, "regime": "BEAR"})  # must not raise

    def test_regime_does_not_affect_score(self) -> None:
        # The raw score is purely numeric — regime only affects rejection reasons
        scorer = SignalScorer()
        kwargs = {k: v for k, v in HIGH_MOMENTUM.items() if k != "regime"}
        bull = scorer.score_raw(**kwargs, regime="BULL")
        bear = scorer.score_raw(**kwargs, regime="BEAR")
        assert bull == pytest.approx(bear)


# ---------------------------------------------------------------------------
# min_score / accepts
# ---------------------------------------------------------------------------

class TestMinScore:

    def test_default_min_score(self) -> None:
        scorer = SignalScorer()
        assert scorer.min_score == pytest.approx(0.70)

    def test_custom_min_score(self) -> None:
        scorer = SignalScorer(min_score=0.80)
        assert scorer.min_score == pytest.approx(0.80)

    def test_accepts_high_score(self) -> None:
        scorer = SignalScorer(min_score=0.10)  # low bar
        score = scorer.score_raw(**HIGH_MOMENTUM)
        assert scorer.accepts(score)

    def test_rejects_low_score(self) -> None:
        scorer = SignalScorer(min_score=0.99)  # very high bar
        score = scorer.score_raw(**LOW_MOMENTUM)
        assert not scorer.accepts(score)

    def test_from_scoring_config(self) -> None:
        cfg = ScoringConfig(min_score=0.65)
        scorer = SignalScorer(min_score=cfg.min_score)
        assert scorer.min_score == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------

class TestScoreCandidate:

    def test_returns_float_in_range(self) -> None:
        scorer = SignalScorer()
        cand = make_candidate()
        result = scorer.score_candidate(cand)
        assert 0.0 <= result <= 1.0

    def test_deterministic_with_candidate(self) -> None:
        scorer = SignalScorer()
        cand = make_candidate()
        assert scorer.score_candidate(cand) == scorer.score_candidate(cand)

    def test_none_optional_fields_do_not_crash(self) -> None:
        scorer = SignalScorer()
        cand = EnrichedCandidate(
            exchange="kraken",
            trading_pair="BTC-USD",
            price=1.0,
            bid=0.999,
            ask=1.001,
            spread_pct=0.20,
            # All optional scorer fields left as None
        )
        result = scorer.score_candidate(cand)
        assert 0.0 <= result <= 1.0

    def test_high_momentum_candidate_beats_flat(self) -> None:
        scorer = SignalScorer()
        high = make_candidate(trend_1h=6.0, trend_4h=15.0, volume_expansion=10.0, rsi=55.0)
        flat = make_candidate(trend_1h=0.0, trend_4h=0.0, volume_expansion=1.0, rsi=70.0)
        assert scorer.score_candidate(high) > scorer.score_candidate(flat)


# ---------------------------------------------------------------------------
# score_breakdown
# ---------------------------------------------------------------------------

class TestScoreBreakdown:

    def test_returns_dict_with_expected_keys(self) -> None:
        scorer = SignalScorer()
        bd = scorer.score_breakdown(
            trend_1h=3.0, trend_4h=8.0, volume_expansion=4.0,
            relative_strength=1.0, spread_pct=0.15, rsi=60.0, wick_risk=0.2,
        )
        assert isinstance(bd, dict)
        for key in ("trend_1h", "trend_4h", "volume_expansion",
                    "relative_strength", "spread", "rsi_wick_risk"):
            assert key in bd

    def test_breakdown_values_in_range(self) -> None:
        scorer = SignalScorer()
        bd = scorer.score_breakdown(
            trend_1h=3.0, trend_4h=8.0, volume_expansion=4.0,
            relative_strength=1.0, spread_pct=0.15, rsi=60.0, wick_risk=0.2,
        )
        for key, val in bd.items():
            assert 0.0 <= val <= 1.0, f"{key}={val} out of range"
