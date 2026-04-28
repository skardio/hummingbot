"""
Unit tests for SessionEdgeDetector.

Item 13 — Session Edge Detector
"""
from dataclasses import dataclass

import pytest

from multi_coin_grid_pro.core.session_edge_detector import SessionEdgeDetector, SessionStats


# Minimal stub matching TradeLabel interface used by detector
@dataclass
class FakeLabel:
    coin: str
    session: str
    pnl_quote: float
    timestamp_close: int = 0
    quality_score: int = 50


def make_labels(session: str, pnls, coin: str = "BTC-EUR"):
    return [FakeLabel(coin=coin, session=session, pnl_quote=p) for p in pnls]


class TestCompute:
    def test_compute_win_rate(self):
        detector = SessionEdgeDetector(min_trades=1)
        labels = make_labels("EU", [5.0, -1.0, 3.0, -2.0, 4.0])
        stats = detector.compute(labels)
        eu = stats["EU"]
        assert eu.trade_count == 5
        assert eu.win_rate == pytest.approx(0.6)

    def test_compute_total_pnl(self):
        detector = SessionEdgeDetector(min_trades=1)
        labels = make_labels("US", [2.0, -1.0, 3.0])
        stats = detector.compute(labels)
        assert stats["US"].total_pnl == pytest.approx(4.0)

    def test_compute_filters_by_coin(self):
        detector = SessionEdgeDetector(min_trades=1)
        labels = (
            make_labels("EU", [5.0, 3.0], coin="BTC-EUR")
            + make_labels("EU", [-5.0, -3.0], coin="ETH-EUR")
        )
        stats = detector.compute(labels, coin="BTC-EUR")
        assert stats["EU"].avg_pnl > 0

    def test_unknown_session_not_in_result(self):
        detector = SessionEdgeDetector(min_trades=1)
        labels = [FakeLabel(coin="BTC", session="INVALID", pnl_quote=1.0)]
        stats = detector.compute(labels)
        assert "INVALID" not in stats

    def test_empty_labels_returns_empty(self):
        detector = SessionEdgeDetector()
        stats = detector.compute([])
        assert stats == {}


class TestHasEdge:
    def test_has_edge_true_when_criteria_met(self):
        s = SessionStats(session="EU", trade_count=10, win_rate=0.6, avg_pnl=2.0, total_pnl=20.0)
        assert s.has_edge is True

    def test_has_edge_false_insufficient_trades(self):
        s = SessionStats(session="EU", trade_count=4, win_rate=0.75, avg_pnl=2.0, total_pnl=8.0)
        assert s.has_edge is False

    def test_has_edge_false_low_win_rate(self):
        s = SessionStats(session="EU", trade_count=10, win_rate=0.5, avg_pnl=2.0, total_pnl=20.0)
        assert s.has_edge is False

    def test_has_edge_false_negative_avg_pnl(self):
        s = SessionStats(session="EU", trade_count=10, win_rate=0.6, avg_pnl=-1.0, total_pnl=-10.0)
        assert s.has_edge is False


class TestBestSession:
    def test_best_session_returns_highest_avg_pnl(self):
        detector = SessionEdgeDetector(min_trades=5)
        labels = (
            make_labels("EU", [2.0] * 6, "BTC")
            + make_labels("US", [5.0] * 6, "BTC")
            + make_labels("Asia", [-1.0] * 6, "BTC")
        )
        best = detector.best_session(labels)
        assert best == "US"

    def test_best_session_none_when_insufficient_data(self):
        detector = SessionEdgeDetector(min_trades=5)
        labels = make_labels("EU", [1.0, 2.0])  # only 2 trades
        assert detector.best_session(labels) is None


class TestShouldAvoidSession:
    def test_avoid_session_with_negative_edge(self):
        detector = SessionEdgeDetector(min_trades=5)
        labels = make_labels("Asia", [-3.0, -2.0, 1.0, -4.0, -2.0, -1.0], "BTC")
        assert detector.should_avoid_session("Asia", labels) is True

    def test_no_avoid_session_positive_edge(self):
        detector = SessionEdgeDetector(min_trades=5)
        labels = make_labels("EU", [2.0, 3.0, 1.0, 2.0, 4.0, 2.0], "BTC")
        assert detector.should_avoid_session("EU", labels) is False

    def test_no_avoid_when_insufficient_trades(self):
        detector = SessionEdgeDetector(min_trades=5)
        labels = make_labels("US", [-5.0, -5.0])  # only 2 trades
        assert detector.should_avoid_session("US", labels) is False
