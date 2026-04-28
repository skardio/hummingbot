"""
Unit tests for TradeQualityScorer and quality_size_multiplier.

Items 5 & 8 — Trade Quality Scorer + Quality-Based Position Sizing.
"""
import pytest

from multi_coin_grid_pro.scoring.trade_quality_scorer import QualityScore, TradeQualityScorer, quality_size_multiplier


@pytest.fixture
def scorer():
    return TradeQualityScorer()


# ------------------------------------------------------------------ #
# Individual component tests
# ------------------------------------------------------------------ #

class TestRegimeScore:
    def test_bull_gets_max(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.regime == 25

    def test_neutral_gets_15(self, scorer):
        qs = scorer.score(regime="NEUTRAL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.regime == 15

    def test_bear_gets_zero(self, scorer):
        qs = scorer.score(regime="BEAR", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.regime == 0

    def test_unknown_regime_gets_zero(self, scorer):
        qs = scorer.score(regime="SIDEWAYS", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.regime == 0


class TestRsiScore:
    def test_rsi_in_30_50_gets_20(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40.0, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.rsi == 20

    def test_rsi_in_50_60_gets_15(self, scorer):
        qs = scorer.score(regime="BULL", rsi=55.0, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.rsi == 15

    def test_rsi_in_60_70_gets_5(self, scorer):
        qs = scorer.score(regime="BULL", rsi=65.0, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.rsi == 5

    def test_rsi_above_70_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=80.0, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.rsi == 0

    def test_rsi_below_30_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=20.0, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.rsi == 0


class TestSpreadScore:
    def test_tight_spread_gets_20(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.spread == 20

    def test_spread_at_0_2_gets_15(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.2,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.spread == 15

    def test_spread_at_0_3_gets_10(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.3,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.spread == 10

    def test_spread_at_0_5_gets_5(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.5,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.spread == 5

    def test_wide_spread_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=1.0,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.spread == 0


class TestDepthScore:
    def test_depth_10x_gets_15(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10.0, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.depth == 15

    def test_depth_5x_gets_10(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=5.0, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.depth == 10

    def test_depth_3x_gets_5(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=3.0, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.depth == 5

    def test_depth_below_3x_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=2.0, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.depth == 0


class TestVolatilityScore:
    def test_atr_in_1_3_gets_10(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.volatility == 10

    def test_atr_0_75_gets_7(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=0.75, btc_1h_pct=0.5)
        assert qs.volatility == 7

    def test_atr_3_5_gets_7(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=3.5, btc_1h_pct=0.5)
        assert qs.volatility == 7

    def test_atr_extreme_high_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=6.0, btc_1h_pct=0.5)
        assert qs.volatility == 0

    def test_atr_extreme_low_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=0.1, btc_1h_pct=0.5)
        assert qs.volatility == 0


class TestBtcTrendScore:
    def test_btc_positive_gets_10(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.btc_trend == 10

    def test_btc_slightly_negative_gets_5(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=-0.5)
        assert qs.btc_trend == 5

    def test_btc_very_negative_gets_zero(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=-2.0)
        assert qs.btc_trend == 0


# ------------------------------------------------------------------ #
# Full score tests
# ------------------------------------------------------------------ #

class TestFullScore:
    def test_perfect_score(self, scorer):
        """BULL + ideal RSI + tight spread + deep book + normal ATR + BTC up."""
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.total == 100

    def test_worst_score(self, scorer):
        """BEAR + extreme RSI + wide spread + thin book + extreme ATR + BTC crashing."""
        qs = scorer.score(regime="BEAR", rsi=80, spread_pct=2.0,
                          depth_multiple=1.0, atr_pct=8.0, btc_1h_pct=-3.0)
        assert qs.total == 0

    def test_total_is_sum_of_components(self, scorer):
        qs = scorer.score(regime="NEUTRAL", rsi=55, spread_pct=0.25,
                          depth_multiple=4, atr_pct=3.5, btc_1h_pct=-0.5)
        expected = qs.regime + qs.rsi + qs.spread + qs.depth + qs.volatility + qs.btc_trend
        assert qs.total == expected

    def test_returns_quality_score_dataclass(self, scorer):
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert isinstance(qs, QualityScore)
        assert isinstance(qs.details, dict)
        assert len(qs.details) == 6

    def test_total_capped_at_100(self, scorer):
        """Total must never exceed 100."""
        qs = scorer.score(regime="BULL", rsi=40, spread_pct=0.05,
                          depth_multiple=10, atr_pct=2.0, btc_1h_pct=0.5)
        assert qs.total <= 100


# ------------------------------------------------------------------ #
# quality_size_multiplier tests (Item 8)
# ------------------------------------------------------------------ #

class TestQualitySizeMultiplier:
    def test_score_80_plus_gives_1_25(self):
        assert quality_size_multiplier(85) == pytest.approx(1.25)

    def test_score_60_to_79_gives_1_0(self):
        assert quality_size_multiplier(70) == pytest.approx(1.0)

    def test_score_40_to_59_gives_0_75(self):
        assert quality_size_multiplier(50) == pytest.approx(0.75)

    def test_score_below_40_gives_0_5(self):
        assert quality_size_multiplier(30) == pytest.approx(0.5)

    def test_halved_flag_halves_multiplier(self):
        assert quality_size_multiplier(85, halved=True) == pytest.approx(0.625)
        assert quality_size_multiplier(70, halved=True) == pytest.approx(0.5)
        assert quality_size_multiplier(50, halved=True) == pytest.approx(0.375)
        assert quality_size_multiplier(30, halved=True) == pytest.approx(0.25)

    def test_boundary_exactly_80(self):
        assert quality_size_multiplier(80) == pytest.approx(1.25)

    def test_boundary_exactly_60(self):
        assert quality_size_multiplier(60) == pytest.approx(1.0)

    def test_boundary_exactly_40(self):
        assert quality_size_multiplier(40) == pytest.approx(0.75)

    def test_boundary_39_is_poor(self):
        assert quality_size_multiplier(39) == pytest.approx(0.5)
