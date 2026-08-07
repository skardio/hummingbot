# test_max_volume_ratio.py — unit tests for max_volume_ratio filter, spread unit,
# and market context fields in MomentumSignal model.
from pathlib import Path

import pytest

from multi_coin_grid_pro.signals.momentum_config import CandidateFilters, ServiceConfig
from multi_coin_grid_pro.signals.momentum_filters import (
    REASON_SPREAD_TOO_HIGH_FOR_ENTRY,
    REASON_VOLUME_SPIKE_TOO_EXTREME,
    HardFilter,
)
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate, MomentumSignal
from multi_coin_grid_pro.signals.momentum_signal_store import SignalStore

NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate(
    volume_ratio: float = 5.0,
    spread_pct: float = 0.10,
    trading_pair: str = "ALT-USD",
) -> EnrichedCandidate:
    """Volledig verrijkte candidate — passeert standaard alle filters."""
    return EnrichedCandidate(
        exchange="kraken",
        trading_pair=trading_pair,
        price=1.0,
        bid=0.999,
        ask=1.001,
        spread_pct=spread_pct,
        price_change_1m_pct=0.50,
        price_change_3m_pct=0.80,
        price_change_5m_pct=2.5,
        price_change_15m_pct=4.0,
        volume_ratio=volume_ratio,
        slippage_100eur=0.20,
        slippage_250eur=0.30,
        candles_fetched_at=NOW,
        ob_fetched_at=NOW,
    )


def _config_with_vol_filter(max_volume_ratio: float, max_spread_pct_entry: float = 0.0) -> ServiceConfig:
    cf = CandidateFilters(max_volume_ratio=max_volume_ratio, max_spread_pct_entry=max_spread_pct_entry)
    cfg = ServiceConfig(mode="signal_only")
    cfg.candidate_filters = cf
    return cfg


def _config_with_spread_filter(max_spread_pct_entry: float) -> ServiceConfig:
    cf = CandidateFilters(max_spread_pct_entry=max_spread_pct_entry, max_volume_ratio=0.0)
    cfg = ServiceConfig(mode="signal_only")
    cfg.candidate_filters = cf
    return cfg


def _apply(candidate: EnrichedCandidate, cfg: ServiceConfig):
    return HardFilter().apply([candidate], config=cfg, now=NOW)


# ---------------------------------------------------------------------------
# §1 — max_volume_ratio grenswaarden
# ---------------------------------------------------------------------------

class TestMaxVolumeRatioFilter:

    def test_exactly_at_limit_is_accepted(self) -> None:
        """volume_ratio == max_volume_ratio (1000.0) → geaccepteerd (grens inclusief)."""
        c = _candidate(volume_ratio=1000.0)
        result = _apply(c, _config_with_vol_filter(max_volume_ratio=1000.0))
        assert len(result.accepted) == 1
        assert len(result.rejected) == 0

    def test_one_above_limit_is_rejected(self) -> None:
        """volume_ratio == 1001.0 > max_volume_ratio=1000 → VOLUME_SPIKE_TOO_EXTREME."""
        c = _candidate(volume_ratio=1001.0)
        result = _apply(c, _config_with_vol_filter(max_volume_ratio=1000.0))
        assert len(result.rejected) == 1
        assert result.rejected[0].rejection_reason == REASON_VOLUME_SPIKE_TOO_EXTREME

    def test_extreme_spike_rejected(self) -> None:
        """Extreme spike (6645x gezien in data) wordt correct gefilterd."""
        c = _candidate(volume_ratio=6645.0)
        result = _apply(c, _config_with_vol_filter(max_volume_ratio=1000.0))
        assert len(result.rejected) == 1
        assert REASON_VOLUME_SPIKE_TOO_EXTREME in result.rejected[0].all_reasons

    def test_filter_disabled_when_zero(self) -> None:
        """max_volume_ratio=0.0 → filter uitgeschakeld; zelfs extreem hoge waarden passeren."""
        c = _candidate(volume_ratio=999_999.0)
        result = _apply(c, _config_with_vol_filter(max_volume_ratio=0.0))
        assert len(result.accepted) == 1, "Filter mag niet actief zijn bij max_volume_ratio=0.0"

    def test_none_volume_ratio_not_rejected_when_filter_active(self) -> None:
        """Als volume_ratio None is (ontbrekende data), sla volume-spike check over."""
        c = _candidate(volume_ratio=None)
        # Candidate wordt mogelijk om andere reden gefilterd (MISSING_VOLUME_RATIO),
        # maar niet door VOLUME_SPIKE_TOO_EXTREME.
        result = _apply(c, _config_with_vol_filter(max_volume_ratio=500.0))
        for rej in result.rejected:
            assert REASON_VOLUME_SPIKE_TOO_EXTREME not in rej.all_reasons


# ---------------------------------------------------------------------------
# §2 — max_spread_pct_entry eenheden (percentage punten, niet fractioneel)
# ---------------------------------------------------------------------------

class TestSpreadFilterUnit:

    def test_spread_just_below_limit_accepted(self) -> None:
        """spread_pct=0.149 met max_spread_pct_entry=0.15 → geaccepteerd."""
        c = _candidate(spread_pct=0.149)
        result = _apply(c, _config_with_spread_filter(max_spread_pct_entry=0.15))
        assert len(result.accepted) == 1

    def test_spread_exactly_at_limit_accepted(self) -> None:
        """spread_pct=0.15 met max_spread_pct_entry=0.15 → geaccepteerd (grens inclusief)."""
        c = _candidate(spread_pct=0.15)
        result = _apply(c, _config_with_spread_filter(max_spread_pct_entry=0.15))
        assert len(result.accepted) == 1

    def test_spread_just_above_limit_rejected(self) -> None:
        """spread_pct=0.151 met max_spread_pct_entry=0.15 → SPREAD_TOO_HIGH_FOR_ENTRY."""
        c = _candidate(spread_pct=0.151)
        result = _apply(c, _config_with_spread_filter(max_spread_pct_entry=0.15))
        assert len(result.rejected) == 1
        assert result.rejected[0].rejection_reason == REASON_SPREAD_TOO_HIGH_FOR_ENTRY

    def test_spread_filter_disabled_when_zero(self) -> None:
        """max_spread_pct_entry=0.0 → filter uitgeschakeld."""
        c = _candidate(spread_pct=99.0)  # absurde spread — moet passeren
        result = _apply(c, _config_with_spread_filter(max_spread_pct_entry=0.0))
        assert REASON_SPREAD_TOO_HIGH_FOR_ENTRY not in [
            r.rejection_reason for r in result.rejected
        ]


# ---------------------------------------------------------------------------
# §3 — MomentumSignal market context velden + DB opslag
# ---------------------------------------------------------------------------

def _make_signal(
    market_regime: float = None,
    market_breadth: float = None,
    btc_d15m: float = None,
    eth_d15m: float = None,
) -> MomentumSignal:
    return MomentumSignal(
        scan_id="test-001",
        timestamp=NOW,
        exchange="kraken",
        trading_pair="ALT-USD",
        price=1.0,
        spread_pct=0.10,
        price_change_5m_pct=2.5,
        price_change_15m_pct=4.0,
        volume_ratio=5.0,
        score=0.85,
        accepted=True,
        rank=1,
        all_reasons=[],
        score_breakdown={},
        market_regime_at_signal=market_regime,
        market_breadth_15m=market_breadth,
        btc_15m_change_pct=btc_d15m,
        eth_15m_change_pct=eth_d15m,
    )


class TestMomentumSignalMarketContextFields:

    def test_fields_default_to_none(self) -> None:
        """Nieuwe marktcontext velden zijn standaard None."""
        sig = _make_signal()
        assert sig.market_regime_at_signal is None
        assert sig.market_breadth_15m is None
        assert sig.btc_15m_change_pct is None
        assert sig.eth_15m_change_pct is None

    def test_fields_can_be_set(self) -> None:
        sig = _make_signal(market_regime=0.45, market_breadth=62.5, btc_d15m=1.2, eth_d15m=-0.3)
        assert sig.market_regime_at_signal == pytest.approx(0.45)
        assert sig.market_breadth_15m == pytest.approx(62.5)
        assert sig.btc_15m_change_pct == pytest.approx(1.2)
        assert sig.eth_15m_change_pct == pytest.approx(-0.3)

    def test_fields_saved_to_db_and_retrieved(self, tmp_path: Path) -> None:
        """market_regime en breadth worden correct opgeslagen en teruggezocht in SQLite."""
        store = SignalStore(db_path=str(tmp_path / "momentum_signals.sqlite"))
        sig = _make_signal(market_regime=0.45, market_breadth=62.5, btc_d15m=1.2, eth_d15m=-0.3)
        row_id = store.save(sig)
        assert row_id > 0

        conn = store._conn
        row = conn.execute(
            "SELECT market_regime_at_signal, market_breadth_15m, btc_15m_change_pct, eth_15m_change_pct "
            "FROM signals WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(0.45)
        assert row[1] == pytest.approx(62.5)
        assert row[2] == pytest.approx(1.2)
        assert row[3] == pytest.approx(-0.3)
        store.close()

    def test_null_fields_saved_as_null(self, tmp_path: Path) -> None:
        """None waarden worden als NULL in de DB opgeslagen."""
        store = SignalStore(db_path=str(tmp_path / "momentum_signals.sqlite"))
        sig = _make_signal()  # alle velden None
        row_id = store.save(sig)

        conn = store._conn
        row = conn.execute(
            "SELECT market_regime_at_signal, market_breadth_15m, btc_15m_change_pct, eth_15m_change_pct "
            "FROM signals WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert all(v is None for v in row)
        store.close()
