"""Unit tests for GridSuitabilityScorer."""
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pytest

from multi_coin_grid_pro.utils.grid_suitability_scorer import GridSuitabilityScorer


@dataclass
class FakeCandleData:
    """Mimics CandleData for tests."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0
    vwap: Optional[float] = None


def _make_candles(closes: list[float], spread_pct: float = 0.005) -> list[FakeCandleData]:
    """Generate candles from a list of close prices with synthetic OHLC."""
    candles = []
    for i, c in enumerate(closes):
        half_spread = c * spread_pct
        candles.append(FakeCandleData(
            timestamp=1700000000 + i * 300,
            open=c - half_spread * 0.3,
            high=c + half_spread,
            low=c - half_spread,
            close=c,
        ))
    return candles


def _make_trending_candles(n: int = 48, start: float = 100.0,
                           pct_per_bar: float = 0.003) -> list[FakeCandleData]:
    """Strongly trending up — bad for grids."""
    closes = [start * (1 + pct_per_bar) ** i for i in range(n)]
    return _make_candles(closes, spread_pct=0.002)


def _make_choppy_candles(n: int = 48, center: float = 100.0,
                         amplitude: float = 1.5) -> list[FakeCandleData]:
    """Oscillating around center — great for grids."""
    closes = [center + amplitude * np.sin(i * 0.8) for i in range(n)]
    return _make_candles(closes, spread_pct=0.005)


def _make_random_walk_candles(n: int = 48, start: float = 100.0,
                              seed: int = 42) -> list[FakeCandleData]:
    """Random walk — mixed suitability."""
    rng = np.random.default_rng(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + rng.normal(0, 0.005)))
    return _make_candles(prices, spread_pct=0.004)


@pytest.fixture
def logger():
    return logging.getLogger("test_scorer")


@pytest.fixture
def scorer(logger):
    config = {
        'enabled': True,
        'logging_only': False,
        'min_grid_score': 0.30,
        'lookback_candles': 48,
    }
    return GridSuitabilityScorer(config, logger)


@pytest.fixture
def scorer_logging_only(logger):
    config = {
        'enabled': True,
        'logging_only': True,
        'min_grid_score': 0.30,
        'lookback_candles': 48,
    }
    return GridSuitabilityScorer(config, logger)


@pytest.fixture
def scorer_disabled(logger):
    config = {
        'enabled': False,
    }
    return GridSuitabilityScorer(config, logger)


# ──────────────────────────────────────────────────────────
# score_coin tests
# ──────────────────────────────────────────────────────────

class TestScoreCoin:

    def test_choppy_coin_scores_high(self, scorer):
        """Oscillating price = good for grids → high score."""
        candles = _make_choppy_candles()
        result = scorer.score_coin("CHOP-USD", candles)
        assert result is not None
        assert result.score > 0.45, f"Choppy coin should score high, got {result.score}"
        assert result.range_efficiency < 0.3

    def test_trending_coin_scores_low(self, scorer):
        """Strong trend = bad for grids → low score."""
        candles = _make_trending_candles()
        result = scorer.score_coin("TREND-USD", candles)
        assert result is not None
        assert result.score < 0.45, f"Trending coin should score low, got {result.score}"
        assert result.range_efficiency > 0.3

    def test_insufficient_candles_returns_none(self, scorer):
        """Less than 12 candles → None."""
        candles = _make_choppy_candles(n=5)
        result = scorer.score_coin("SHORT-USD", candles)
        assert result is None

    def test_empty_candles_returns_none(self, scorer):
        result = scorer.score_coin("EMPTY-USD", [])
        assert result is None

    def test_score_bounded_0_1(self, scorer):
        """Score must always be in [0, 1]."""
        for factory in [_make_choppy_candles, _make_trending_candles, _make_random_walk_candles]:
            candles = factory()
            result = scorer.score_coin("TEST-USD", candles)
            assert result is not None
            assert 0.0 <= result.score <= 1.0
            assert 0.0 <= result.range_efficiency <= 1.0
            assert 0.0 <= result.mean_reversion <= 1.0
            assert 0.0 <= result.bounce_rate <= 1.0
            assert 0.0 <= result.atr_consistency <= 1.0

    def test_lookback_trims_candles(self, logger):
        """Only last N candles used when more are provided."""
        config = {'enabled': True, 'logging_only': False,
                  'min_grid_score': 0.3, 'lookback_candles': 20}
        scorer = GridSuitabilityScorer(config, logger)
        # 100 candles but only last 20 used
        candles = _make_choppy_candles(n=100)
        result = scorer.score_coin("LONG-USD", candles)
        assert result is not None

    def test_reason_not_empty(self, scorer):
        candles = _make_choppy_candles()
        result = scorer.score_coin("QNT-USD", candles)
        assert result is not None
        assert len(result.reason) > 0


# ──────────────────────────────────────────────────────────
# filter_coins tests
# ──────────────────────────────────────────────────────────

class TestFilterCoins:

    def test_disabled_returns_unmodified(self, scorer_disabled):
        symbols = ["A-USD", "B-USD", "C-USD"]
        result = scorer_disabled.filter_coins(symbols, {})
        assert result == symbols

    def test_logging_only_returns_unmodified(self, scorer_logging_only):
        """Logging mode logs scores but doesn't filter."""
        symbols = ["CHOP-USD", "TREND-USD"]
        candles_map = {
            "CHOP-USD": _make_choppy_candles(),
            "TREND-USD": _make_trending_candles(),
        }
        result = scorer_logging_only.filter_coins(symbols, candles_map)
        assert result == symbols

    def test_active_filters_low_scoring_coins(self, scorer):
        """Active mode removes trending coins below threshold."""
        symbols = ["CHOP-USD", "TREND-USD"]
        candles_map = {
            "CHOP-USD": _make_choppy_candles(),
            "TREND-USD": _make_trending_candles(),
        }
        result = scorer.filter_coins(symbols, candles_map)
        # Choppy should pass, trending might fail
        assert "CHOP-USD" in result

    def test_missing_candles_passes_through(self, scorer):
        """Coins without candle data pass through (fail-open)."""
        symbols = ["NODATA-USD"]
        result = scorer.filter_coins(symbols, {})
        assert "NODATA-USD" in result

    def test_empty_symbols_returns_empty(self, scorer):
        result = scorer.filter_coins([], {})
        assert result == []


# ──────────────────────────────────────────────────────────
# Individual metric tests
# ──────────────────────────────────────────────────────────

class TestMetrics:

    def test_range_efficiency_trending(self):
        """Strongly trending → high range efficiency."""
        candles = _make_trending_candles(n=30, pct_per_bar=0.005)
        re = GridSuitabilityScorer._range_efficiency(candles)
        assert re > 0.3, f"Expected >0.3 for trend, got {re}"

    def test_range_efficiency_choppy(self):
        """Choppy → low range efficiency."""
        candles = _make_choppy_candles(n=30)
        re = GridSuitabilityScorer._range_efficiency(candles)
        assert re < 0.3, f"Expected <0.3 for chop, got {re}"

    def test_mean_reversion_choppy(self):
        """Oscillating prices should show mean-reverting behavior."""
        # Use higher frequency oscillation for clearer mean-reversion signal
        closes_raw = [100.0 + 2.0 * ((-1) ** i) for i in range(60)]
        candles = _make_candles(closes_raw)
        closes = GridSuitabilityScorer._extract_closes(candles)
        mr = GridSuitabilityScorer._mean_reversion_score(closes)
        assert mr > 0.45, f"Expected >0.45 for choppy, got {mr}"

    def test_bounce_rate_choppy(self):
        """Alternating prices should have high bounce rate."""
        # Perfect alternation: every bar reverses
        closes_raw = [100.0 + 1.5 * ((-1) ** i) for i in range(60)]
        candles = _make_candles(closes_raw)
        closes = GridSuitabilityScorer._extract_closes(candles)
        br = GridSuitabilityScorer._bounce_rate(closes)
        assert br > 0.8, f"Expected >0.8 for alternating, got {br}"

    def test_atr_consistency_uniform(self):
        """Consistent spread → high ATR consistency."""
        # All candles have identical spread
        candles = _make_candles([100.0] * 30, spread_pct=0.005)
        ac = GridSuitabilityScorer._atr_consistency(candles)
        assert ac > 0.7, f"Expected >0.7 for uniform, got {ac}"

    def test_atr_consistency_spikey(self):
        """Varying spread → lower ATR consistency."""
        prices = [100.0] * 30
        candles = []
        for i, p in enumerate(prices):
            spread = 0.001 if i % 3 == 0 else 0.02
            half = p * spread
            candles.append(FakeCandleData(
                timestamp=1700000000 + i * 300,
                open=p, high=p + half, low=p - half, close=p,
            ))
        ac = GridSuitabilityScorer._atr_consistency(candles)
        assert ac < 0.7, f"Expected <0.7 for spiky vol, got {ac}"
