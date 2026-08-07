from types import SimpleNamespace

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage, get_stage_for_reason
from multi_coin_grid_pro.logic.momentum_candidate_scorer import MomentumCandidateScorer


def trend(trend_1h=3.0, trend_4h=8.0, trend_24h=10.0, volume_expansion=2.5):
    return SimpleNamespace(
        trend_60m=trend_1h,
        trend_240m=trend_4h,
        trend_1440m=trend_24h,
        volume_ratio=volume_expansion,
    )


def candle(volume):
    return SimpleNamespace(volume=volume)


class TestMomentumCandidateScorer:
    def test_score_high_momentum_coin(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(),
            trend(trend_4h=1.0),
            spread=0.05,
            rsi=60,
            wick_risk=0.2,
            regime="BULL",
        )

        assert candidate.score > 70
        assert candidate.entry_allowed is True
        assert candidate.primary_rejection_reason is None
        assert candidate.all_rejection_reasons == []

    def test_score_rejects_low_volume(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(volume_expansion=0.8),
            trend(trend_4h=1.0),
            spread=0.05,
            rsi=60,
            wick_risk=0.2,
            regime="BULL",
        )

        assert candidate.entry_allowed is False
        assert ReasonCode.MOMENTUM_VOLUME_TOO_LOW.value in candidate.all_rejection_reasons

    def test_score_rejects_overbought(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(),
            trend(trend_4h=1.0),
            spread=0.05,
            rsi=84,
            wick_risk=0.2,
            regime="BULL",
        )

        assert candidate.entry_allowed is False
        assert ReasonCode.MOMENTUM_RSI_TOO_HIGH.value in candidate.all_rejection_reasons

    def test_score_penalizes_wide_spread(self):
        scorer = MomentumCandidateScorer()

        tight = scorer.score("APE-USD", trend(), trend(trend_4h=1.0), 0.05, 60, 0.2, "BULL")
        wide = scorer.score("APE-USD", trend(), trend(trend_4h=1.0), 0.8, 60, 0.2, "BULL")

        assert wide.score < tight.score
        assert ReasonCode.MOMENTUM_SPREAD_TOO_WIDE.value in wide.all_rejection_reasons

    def test_relative_strength_vs_btc(self):
        scorer = MomentumCandidateScorer()

        strong_rs = scorer.score("APE-USD", trend(trend_4h=8.0), trend(trend_4h=1.0), 0.05, 60, 0.2, "BULL")
        weak_rs = scorer.score("APE-USD", trend(trend_4h=8.0), trend(trend_4h=7.0), 0.05, 60, 0.2, "BULL")

        assert strong_rs.relative_strength == 7.0
        assert weak_rs.relative_strength == 1.0
        assert strong_rs.score > weak_rs.score

    def test_no_crash_without_btc(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(),
            None,
            spread=0.05,
            rsi=60,
            wick_risk=0.2,
            regime="BULL",
        )

        assert candidate.relative_strength == 0.0
        assert candidate.score > 0

    def test_volume_expansion_ignores_zero_volume_live_candles(self):
        scorer = MomentumCandidateScorer()
        trend_obj = SimpleNamespace(
            trend_60m=3.0,
            trend_240m=8.0,
            trend_1440m=10.0,
            candles=[candle(100) for _ in range(20)] + [candle(250), candle(0), candle(0)],
        )

        candidate = scorer.score(
            "APE-USD",
            trend_obj,
            trend(trend_4h=1.0),
            spread=0.05,
            rsi=60,
            wick_risk=0.2,
            regime="BULL",
        )

        assert candidate.volume_expansion > 2.0
        assert ReasonCode.MOMENTUM_VOLUME_TOO_LOW.value not in candidate.all_rejection_reasons

    def test_no_crash_with_null_inputs(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            None,
            None,
            spread=None,
            rsi=None,
            wick_risk=None,
            regime=None,
        )

        assert candidate.symbol == "APE-USD"
        assert candidate.relative_strength == 0.0
        assert candidate.regime_at_score == "CHOP"
        assert candidate.entry_allowed is False
        assert ReasonCode.MOMENTUM_SCORE_TOO_LOW.value in candidate.all_rejection_reasons

    def test_regime_gate_blocks_bear(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(),
            trend(trend_4h=1.0),
            spread=0.05,
            rsi=60,
            wick_risk=0.2,
            regime="BEAR",
        )

        assert candidate.entry_allowed is False
        assert candidate.primary_rejection_reason == ReasonCode.MOMENTUM_REGIME_BLOCKED.value

    def test_all_weights_configurable(self):
        default = MomentumCandidateScorer()
        custom = MomentumCandidateScorer(
            {
                "scorer_weights": {
                    "trend_1h": 1.0,
                    "trend_4h": 0.0,
                    "volume_expansion": 0.0,
                    "relative_strength": 0.0,
                    "spread": 0.0,
                    "rsi_wick_risk": 0.0,
                }
            }
        )
        input_trend = trend(trend_1h=1.0, trend_4h=8.0, volume_expansion=2.5)

        default_score = default.score("APE-USD", input_trend, trend(trend_4h=1.0), 0.05, 60, 0.2, "BULL").score
        custom_score = custom.score("APE-USD", input_trend, trend(trend_4h=1.0), 0.05, 60, 0.2, "BULL").score

        assert custom_score != default_score
        assert custom_score < default_score

    def test_reason_codes_map_to_momentum_stage(self):
        for reason in [
            ReasonCode.MOMENTUM_SCORE_TOO_LOW,
            ReasonCode.MOMENTUM_REGIME_BLOCKED,
            ReasonCode.MOMENTUM_CAPITAL_LIMIT,
            ReasonCode.MOMENTUM_POSITION_LIMIT,
            ReasonCode.MOMENTUM_COOLDOWN,
            ReasonCode.MOMENTUM_DUPLICATE,
            ReasonCode.MOMENTUM_RSI_TOO_HIGH,
            ReasonCode.MOMENTUM_VOLUME_TOO_LOW,
            ReasonCode.MOMENTUM_SPREAD_TOO_WIDE,
            ReasonCode.MOMENTUM_WICK_RISK_TOO_HIGH,
            ReasonCode.MOMENTUM_STOP_LOSS,
            ReasonCode.MOMENTUM_TRAILING_STOP,
            ReasonCode.MOMENTUM_TIME_STOP,
            ReasonCode.MOMENTUM_REGIME_EXIT,
        ]:
            assert get_stage_for_reason(reason) == Stage.MOMENTUM

    def test_primary_rejection_follows_priority(self):
        scorer = MomentumCandidateScorer()

        candidate = scorer.score(
            "APE-USD",
            trend(trend_1h=-1.0, trend_4h=0.1, volume_expansion=0.8),
            trend(trend_4h=5.0),
            spread=0.8,
            rsi=84,
            wick_risk=0.9,
            regime="BEAR",
        )

        assert candidate.primary_rejection_reason == ReasonCode.MOMENTUM_REGIME_BLOCKED.value
        assert ReasonCode.MOMENTUM_RSI_TOO_HIGH.value in candidate.all_rejection_reasons
        assert ReasonCode.MOMENTUM_SCORE_TOO_LOW.value in candidate.all_rejection_reasons


class TestVolumeExpansionFallback:
    """Unit tests for _volume_expansion() fallback behaviour.

    These tests verify that the method returns the correct value (and does not
    crash) for the three representative input shapes, and that the ``symbol``
    parameter reaches the log output via the fallback branches.
    """

    def test_real_volumes_returns_computed_ratio(self):
        """20 baseline candles (vol=100) + 1 latest (vol=200) → ratio ≈ 2.0, not fallback."""
        trend_obj = SimpleNamespace(
            symbol="TEST-USDT",
            candles=[candle(100)] * 20 + [candle(200)],
        )
        result = MomentumCandidateScorer._volume_expansion(trend_obj, symbol="TEST-USDT")
        assert result > 1.5, f"Expected computed ratio ~2.0, got {result}"
        assert result != 1.0, "Should NOT have fallen back to 1.0 with real volume data"

    def test_all_zero_volumes_returns_fallback(self, caplog):
        """100 ticker-created candles (vol=0) → silent fallback to 1.0."""
        import logging
        trend_obj = SimpleNamespace(
            symbol="TEST-USDT",
            candles=[candle(0)] * 100,
        )
        with caplog.at_level(logging.DEBUG, logger="multi_coin_grid_pro.logic.momentum_candidate_scorer"):
            result = MomentumCandidateScorer._volume_expansion(trend_obj, symbol="TEST-USDT")

        assert result == 1.0
        assert any(
            "vol_exp_fallback" in record.message and "all_ticker_candles_zero_volume" in record.message
            for record in caplog.records
        ), "Expected a vol_exp_fallback log with fallback_reason=all_ticker_candles_zero_volume"

    def test_empty_candle_list_returns_fallback(self, caplog):
        """Empty candle list → fallback to 1.0 (insufficient_candles)."""
        import logging
        trend_obj = SimpleNamespace(
            symbol="TEST-USDT",
            candles=[],
        )
        with caplog.at_level(logging.DEBUG, logger="multi_coin_grid_pro.logic.momentum_candidate_scorer"):
            result = MomentumCandidateScorer._volume_expansion(trend_obj, symbol="TEST-USDT")

        assert result == 1.0
        assert any(
            "vol_exp_fallback" in record.message and "insufficient_candles" in record.message
            for record in caplog.records
        ), "Expected a vol_exp_fallback log with fallback_reason=insufficient_candles"
