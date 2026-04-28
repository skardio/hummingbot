"""
Unit tests for MetaCoinRanker.

Item 14 — Meta Coin Ranker
"""
from dataclasses import dataclass

import pytest

from multi_coin_grid_pro.core.meta_coin_ranker import CoinRank, MetaCoinRanker

NOW = 1_700_000_000.0  # fixed reference timestamp


@dataclass
class FakeLabel:
    coin: str
    pnl_quote: float
    quality_score: int
    timestamp_close: int
    session: str = "EU"


def make_labels(coin: str, pnls, quality: int = 70, ts_close: int = None):
    if ts_close is None:
        ts_close = int(NOW - 3600)  # 1 hour ago (within 7-day lookback)
    return [FakeLabel(coin=coin, pnl_quote=p, quality_score=quality, timestamp_close=ts_close)
            for p in pnls]


class TestRank:
    def test_returns_list_of_coin_ranks(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        labels = make_labels("BTC-EUR", [1.0, 2.0, 3.0])
        result = ranker.rank(labels, now=NOW)
        assert len(result) == 1
        assert isinstance(result[0], CoinRank)

    def test_insufficient_trades_excluded(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=5)
        labels = make_labels("BTC-EUR", [1.0, 2.0, 3.0])  # only 3
        result = ranker.rank(labels, now=NOW)
        assert result == []

    def test_coins_sorted_by_score_descending(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        # BTC has high win rate and high avg PnL → should rank first
        btc = make_labels("BTC-EUR", [5.0, 4.0, 6.0, 5.0, 5.0])
        eth = make_labels("ETH-EUR", [-2.0, -1.0, 0.5, -1.0, -0.5])
        result = ranker.rank(btc + eth, now=NOW)
        assert result[0].coin == "BTC-EUR"
        assert result[-1].coin == "ETH-EUR"

    def test_lookback_filters_old_trades(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        old_ts = int(NOW - 8 * 86400)  # 8 days ago — outside lookback
        labels = make_labels("BTC-EUR", [1.0, 2.0, 3.0, 4.0, 5.0], ts_close=old_ts)
        result = ranker.rank(labels, now=NOW)
        assert result == []

    def test_score_calculation_components(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=5)
        # 5 wins, pnl=5 each (pnl_scaled=1.0), quality=100
        labels = make_labels("BTC-EUR", [5.0] * 5, quality=100)
        result = ranker.rank(labels, now=NOW)
        assert len(result) == 1
        r = result[0]
        expected_score = (1.0 * 40) + (1.0 * 40) + (100 / 100.0 * 20)
        assert r.score == pytest.approx(expected_score)


class TestGetPreferredCoins:
    def test_returns_top_n_coins(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        labels = (
            make_labels("BTC-EUR", [5.0] * 5)
            + make_labels("ETH-EUR", [3.0] * 5)
            + make_labels("SOL-EUR", [1.0] * 5)
        )
        preferred = ranker.get_preferred_coins(labels, top_n=2, now=NOW)
        assert len(preferred) == 2
        assert "BTC-EUR" in preferred

    def test_fewer_coins_than_top_n(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        labels = make_labels("BTC-EUR", [1.0, 2.0, 3.0])
        preferred = ranker.get_preferred_coins(labels, top_n=5, now=NOW)
        assert len(preferred) == 1


class TestGetScore:
    def test_get_score_for_existing_coin(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        labels = make_labels("BTC-EUR", [2.0, 3.0, 4.0])
        score = ranker.get_score("BTC-EUR", labels, now=NOW)
        assert score is not None
        assert score > 0

    def test_get_score_returns_none_for_unknown(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=3)
        labels = make_labels("BTC-EUR", [1.0, 2.0, 3.0])
        assert ranker.get_score("UNKNOWN-EUR", labels, now=NOW) is None

    def test_get_score_returns_none_insufficient_trades(self):
        ranker = MetaCoinRanker(lookback_days=7, min_trades=5)
        labels = make_labels("BTC-EUR", [1.0, 2.0])  # only 2
        assert ranker.get_score("BTC-EUR", labels, now=NOW) is None
