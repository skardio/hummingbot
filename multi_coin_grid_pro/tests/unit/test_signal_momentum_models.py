"""
Unit tests for momentum_models.py

Tests: instantiatie, defaults, properties, sanity-checks.
Geen I/O, geen exchange-dependencies.
"""

import time

from multi_coin_grid_pro.signals.momentum_models import (
    EnrichedCandidate,
    FilterResult,
    MomentumSignal,
    RawTicker,
    RejectedCandidate,
    ScanResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ticker(**kwargs) -> RawTicker:
    defaults = dict(
        exchange="kraken",
        trading_pair="WIF-USD",
        price=2.34,
        bid=2.339,
        ask=2.341,
        volume_24h=500_000.0,
        timestamp=time.time(),
    )
    defaults.update(kwargs)
    return RawTicker(**defaults)


def make_candidate(**kwargs) -> EnrichedCandidate:
    defaults = dict(
        exchange="kraken",
        trading_pair="WIF-USD",
        price=2.34,
        bid=2.339,
        ask=2.341,
        spread_pct=0.085,
    )
    defaults.update(kwargs)
    return EnrichedCandidate(**defaults)


def make_signal(**kwargs) -> MomentumSignal:
    defaults = dict(
        scan_id="scan-001",
        timestamp=time.time(),
        exchange="kraken",
        trading_pair="WIF-USD",
        price=2.34,
        spread_pct=0.085,
        score=0.82,
        accepted=True,
        rank=1,
    )
    defaults.update(kwargs)
    return MomentumSignal(**defaults)


# ---------------------------------------------------------------------------
# RawTicker
# ---------------------------------------------------------------------------

class TestRawTicker:
    def test_instantiation(self) -> None:
        t = make_ticker()
        assert t.exchange == "kraken"
        assert t.trading_pair == "WIF-USD"
        assert t.price == 2.34

    def test_spread_pct_computed(self) -> None:
        t = make_ticker(bid=2.0, ask=2.01)
        assert abs(t.spread_pct - 0.5) < 0.01

    def test_spread_pct_zero_bid(self) -> None:
        t = make_ticker(bid=0.0, ask=1.0)
        assert t.spread_pct == 0.0

    def test_spread_pct_zero_when_equal(self) -> None:
        t = make_ticker(bid=1.0, ask=1.0)
        assert t.spread_pct == 0.0


# ---------------------------------------------------------------------------
# EnrichedCandidate
# ---------------------------------------------------------------------------

class TestEnrichedCandidate:
    def test_instantiation_minimal(self) -> None:
        c = make_candidate()
        assert c.exchange == "kraken"
        assert c.trading_pair == "WIF-USD"

    def test_optional_fields_default_none(self) -> None:
        c = make_candidate()
        assert c.price_change_1m_pct is None
        assert c.price_change_5m_pct is None
        assert c.price_change_15m_pct is None
        assert c.volume_ratio is None
        assert c.orderbook_depth_quote is None
        assert c.orderbook_imbalance is None
        assert c.volatility_pct is None
        assert c.trend_1h_pct is None
        assert c.trend_4h_pct is None
        assert c.volume_expansion is None
        assert c.rsi is None
        assert c.wick_risk is None

    def test_boolean_fields_default_false(self) -> None:
        c = make_candidate()
        assert c.active_grid_position is False
        assert c.blacklisted is False
        assert c.in_cooldown is False

    def test_timestamps_default_zero(self) -> None:
        c = make_candidate()
        assert c.ob_fetched_at == 0.0
        assert c.candles_fetched_at == 0.0

    def test_optional_fields_set(self) -> None:
        c = make_candidate(
            price_change_5m_pct=3.2,
            volume_ratio=4.5,
            rsi=58.0,
            blacklisted=True,
        )
        assert c.price_change_5m_pct == 3.2
        assert c.volume_ratio == 4.5
        assert c.rsi == 58.0
        assert c.blacklisted is True


# ---------------------------------------------------------------------------
# MomentumSignal
# ---------------------------------------------------------------------------

class TestMomentumSignal:
    def test_instantiation(self) -> None:
        s = make_signal()
        assert s.scan_id == "scan-001"
        assert s.accepted is True
        assert s.rank == 1

    def test_score_range(self) -> None:
        for score in [0.0, 0.5, 0.7, 1.0]:
            s = make_signal(score=score)
            assert 0.0 <= s.score <= 1.0

    def test_optional_fields_default_none(self) -> None:
        s = make_signal()
        assert s.rejection_reason is None
        assert s.id is None
        assert s.rank == 1  # overridden in make_signal

    def test_list_fields_default_empty(self) -> None:
        s = make_signal()
        assert s.all_reasons == []
        assert s.score_breakdown == {}

    def test_rejected_signal(self) -> None:
        s = make_signal(
            accepted=False,
            rank=None,
            score=0.45,
            rejection_reason="SCORE_TOO_LOW",
            all_reasons=["SCORE_TOO_LOW"],
        )
        assert not s.accepted
        assert s.rank is None
        assert s.rejection_reason == "SCORE_TOO_LOW"

    def test_score_breakdown_stored(self) -> None:
        breakdown = {"trend_1h": 0.8, "volume_expansion": 0.6}
        s = make_signal(score_breakdown=breakdown)
        assert s.score_breakdown["trend_1h"] == 0.8
        assert s.score_breakdown["volume_expansion"] == 0.6


# ---------------------------------------------------------------------------
# FilterResult
# ---------------------------------------------------------------------------

class TestFilterResult:
    def test_empty_result(self) -> None:
        fr = FilterResult()
        assert fr.n_accepted == 0
        assert fr.n_rejected == 0
        assert fr.rejection_breakdown == {}

    def test_n_accepted(self) -> None:
        fr = FilterResult(
            accepted=[make_candidate(), make_candidate(trading_pair="SOL-USD")],
            rejected=[],
        )
        assert fr.n_accepted == 2
        assert fr.n_rejected == 0

    def test_n_rejected(self) -> None:
        rc = RejectedCandidate(
            candidate=make_candidate(),
            rejection_reason="BLACKLISTED",
            all_reasons=["BLACKLISTED"],
        )
        fr = FilterResult(accepted=[], rejected=[rc])
        assert fr.n_accepted == 0
        assert fr.n_rejected == 1

    def test_rejection_breakdown_counts(self) -> None:
        fr = FilterResult(
            rejected=[
                RejectedCandidate(make_candidate(), "BLACKLISTED", ["BLACKLISTED"]),
                RejectedCandidate(make_candidate(), "BLACKLISTED", ["BLACKLISTED"]),
                RejectedCandidate(make_candidate(), "SPREAD_TOO_HIGH", ["SPREAD_TOO_HIGH"]),
            ]
        )
        bd = fr.rejection_breakdown
        assert bd["BLACKLISTED"] == 2
        assert bd["SPREAD_TOO_HIGH"] == 1


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------

class TestScanResult:
    def _make_scan(self, signals: list[MomentumSignal]) -> ScanResult:
        return ScanResult(
            scan_id="scan-abc",
            timestamp=time.time(),
            scan_duration_seconds=3.1,
            signals=signals,
        )

    def test_empty_scan(self) -> None:
        sr = self._make_scan([])
        assert sr.total_scanned == 0
        assert sr.total_accepted == 0
        assert sr.total_rejected == 0
        assert sr.top_signals == []
        assert sr.rejection_breakdown == {}

    def test_total_counts(self) -> None:
        signals = [
            make_signal(accepted=True, rank=1),
            make_signal(accepted=True, rank=2),
            make_signal(accepted=False, rank=None, rejection_reason="SCORE_TOO_LOW"),
        ]
        sr = self._make_scan(signals)
        assert sr.total_scanned == 3
        assert sr.total_accepted == 2
        assert sr.total_rejected == 1

    def test_top_signals_only_accepted(self) -> None:
        signals = [
            make_signal(accepted=True, rank=2, score=0.80),
            make_signal(accepted=False, rank=None, score=0.45, rejection_reason="SCORE_TOO_LOW"),
            make_signal(accepted=True, rank=1, score=0.91),
        ]
        sr = self._make_scan(signals)
        top = sr.top_signals
        assert len(top) == 2
        # Gesorteerd op rank
        assert top[0].rank == 1
        assert top[1].rank == 2

    def test_top_signals_sorted_by_rank(self) -> None:
        signals = [
            make_signal(accepted=True, rank=3, score=0.71),
            make_signal(accepted=True, rank=1, score=0.95),
            make_signal(accepted=True, rank=2, score=0.83),
        ]
        sr = self._make_scan(signals)
        ranks = [s.rank for s in sr.top_signals]
        assert ranks == [1, 2, 3]

    def test_rejection_breakdown(self) -> None:
        signals = [
            make_signal(accepted=False, rank=None, rejection_reason="BLACKLISTED"),
            make_signal(accepted=False, rank=None, rejection_reason="BLACKLISTED"),
            make_signal(accepted=False, rank=None, rejection_reason="SPREAD_TOO_HIGH"),
            make_signal(accepted=True, rank=1),
        ]
        sr = self._make_scan(signals)
        bd = sr.rejection_breakdown
        assert bd["BLACKLISTED"] == 2
        assert bd["SPREAD_TOO_HIGH"] == 1
        assert "SCORE_TOO_LOW" not in bd

    def test_scan_duration_stored(self) -> None:
        sr = ScanResult(
            scan_id="x",
            timestamp=1.0,
            scan_duration_seconds=4.7,
        )
        assert sr.scan_duration_seconds == 4.7

    def test_signals_list_defaults_empty(self) -> None:
        sr = ScanResult(scan_id="x", timestamp=1.0, scan_duration_seconds=0.1)
        assert sr.signals == []
