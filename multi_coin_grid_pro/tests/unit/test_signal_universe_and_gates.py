# test_signal_universe_and_gates.py — tests for universe filter, missing-data gate,
# and LOW_SCORE enforcement in the momentum signal service.
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.services.momentum_signal_service import MomentumSignalService
from multi_coin_grid_pro.signals.momentum_config import ServiceConfig, UniverseConfig
from multi_coin_grid_pro.signals.momentum_filters import (
    REASON_EXCLUDED_ASSET_TYPE,
    REASON_EXCLUDED_MAJOR_ASSET,
    REASON_MISSING_PRICE_CHANGE_5M,
    REASON_MISSING_PRICE_CHANGE_15M,
    REASON_MISSING_VOLUME_RATIO,
    REASON_SCORE_TOO_LOW,
    REASON_STABLECOIN_OR_FOREX,
    HardFilter,
)
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate

NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_candidate(
    trading_pair: str = "ALT-USDT",
    exchange: str = "bitget",
    price_change_5m_pct: float = 3.5,
    price_change_15m_pct: float = 6.0,
    volume_ratio: float = 4.0,
    spread_pct: float = 0.10,
    **kwargs,
) -> EnrichedCandidate:
    """Candidate with all mandatory momentum fields populated."""
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=trading_pair,
        price=1.0,
        bid=0.999,
        ask=1.001,
        spread_pct=spread_pct,
        price_change_5m_pct=price_change_5m_pct,
        price_change_15m_pct=price_change_15m_pct,
        volume_ratio=volume_ratio,
        **kwargs,
    )


def _config_with_universe(**uc_kwargs) -> ServiceConfig:
    return ServiceConfig(mode="signal_only", universe=UniverseConfig(**uc_kwargs))


def _run_filter(candidates, **uc_kwargs):
    cfg = _config_with_universe(**uc_kwargs)
    return HardFilter().apply(candidates, config=cfg, now=NOW)


def _service(tmp_path: Path) -> MomentumSignalService:
    return MomentumSignalService(
        config=ServiceConfig(),
        db_path=str(tmp_path / "s.sqlite"),
        snapshot_path=str(tmp_path / "s.json"),
    )


# ---------------------------------------------------------------------------
# 1. MISSING_MOMENTUM_DATA gate
# ---------------------------------------------------------------------------

class TestMissingMomentumDataGate:
    """Candidates missing any of the three required momentum fields are rejected."""

    def test_none_price_change_5m_rejected(self) -> None:
        c = _full_candidate(price_change_5m_pct=None)
        result = HardFilter().apply([c], config=ServiceConfig(), now=NOW)
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_MISSING_PRICE_CHANGE_5M

    def test_none_price_change_15m_rejected(self) -> None:
        c = _full_candidate(price_change_15m_pct=None)
        result = HardFilter().apply([c], config=ServiceConfig(), now=NOW)
        assert result.n_rejected == 1
        assert REASON_MISSING_PRICE_CHANGE_15M in result.rejected[0].all_reasons

    def test_none_volume_ratio_rejected(self) -> None:
        c = _full_candidate(volume_ratio=None)
        result = HardFilter().apply([c], config=ServiceConfig(), now=NOW)
        assert result.n_rejected == 1
        assert REASON_MISSING_VOLUME_RATIO in result.rejected[0].all_reasons

    def test_all_three_none_rejected(self) -> None:
        c = _full_candidate(
            price_change_5m_pct=None,
            price_change_15m_pct=None,
            volume_ratio=None,
        )
        result = HardFilter().apply([c], config=ServiceConfig(), now=NOW)
        assert result.n_rejected == 1
        reasons = result.rejected[0].all_reasons
        assert REASON_MISSING_PRICE_CHANGE_5M in reasons
        assert REASON_MISSING_PRICE_CHANGE_15M in reasons
        assert REASON_MISSING_VOLUME_RATIO in reasons

    def test_all_fields_present_passes_data_gate(self) -> None:
        """Candidate with all three fields set should pass the data gate."""
        c = _full_candidate()
        result = HardFilter().apply([c], config=ServiceConfig(), now=NOW)
        # May still fail momentum/volume thresholds, but NOT for missing data
        missing_reasons = {REASON_MISSING_PRICE_CHANGE_5M, REASON_MISSING_PRICE_CHANGE_15M, REASON_MISSING_VOLUME_RATIO}
        for rej in result.rejected:
            assert not missing_reasons.intersection(rej.all_reasons)


# ---------------------------------------------------------------------------
# 2. Universe filter
# ---------------------------------------------------------------------------

class TestUniverseFilter:
    """Universe filter rejects forex, stablecoins, metals, and major assets."""

    def test_btc_excluded_as_major(self) -> None:
        c = _full_candidate(trading_pair="BTC-USDT")
        result = _run_filter(
            [c],
            exclude_major_assets=True,
            excluded_base_assets=["BTC"],
        )
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_EXCLUDED_MAJOR_ASSET

    def test_eth_excluded_as_major(self) -> None:
        c = _full_candidate(trading_pair="ETH-USDT")
        result = _run_filter(
            [c],
            exclude_major_assets=True,
            excluded_base_assets=["ETH"],
        )
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_EXCLUDED_MAJOR_ASSET

    def test_gbp_excluded_as_forex(self) -> None:
        c = _full_candidate(trading_pair="GBP-USD")
        result = _run_filter([c], exclude_forex_pairs=True)
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_STABLECOIN_OR_FOREX

    def test_rlusd_excluded_as_stablecoin(self) -> None:
        c = _full_candidate(trading_pair="RLUSD-USD")
        result = _run_filter([c], exclude_stablecoins=True)
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_STABLECOIN_OR_FOREX

    def test_xaut_excluded_as_tokenized_metal(self) -> None:
        c = _full_candidate(trading_pair="XAUT-USDT")
        result = _run_filter([c], exclude_tokenized_metals=True)
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_EXCLUDED_ASSET_TYPE

    def test_paxg_excluded_as_tokenized_metal(self) -> None:
        c = _full_candidate(trading_pair="PAXG-USDT")
        result = _run_filter([c], exclude_tokenized_metals=True)
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_EXCLUDED_ASSET_TYPE

    def test_major_not_excluded_when_flag_off(self) -> None:
        """BTC is NOT excluded when exclude_major_assets=False (default)."""
        c = _full_candidate(trading_pair="BTC-USDT")
        result = _run_filter([c], exclude_major_assets=False)
        universe_reasons = [
            r for r in (result.rejected[0].all_reasons if result.rejected else [])
            if r == REASON_EXCLUDED_MAJOR_ASSET
        ]
        assert not universe_reasons

    def test_altcoin_not_excluded(self) -> None:
        """An altcoin not in the excluded list is never EXCLUDED_MAJOR_ASSET."""
        c = _full_candidate(trading_pair="ALGO-USDT")
        result = _run_filter(
            [c],
            exclude_major_assets=True,
            excluded_base_assets=["BTC", "ETH"],
        )
        universe_reasons = [
            r for r in (result.rejected[0].all_reasons if result.rejected else [])
            if r == REASON_EXCLUDED_MAJOR_ASSET
        ]
        assert not universe_reasons

    def test_usdt_excluded_as_stablecoin_not_major(self) -> None:
        """USDT is caught by stablecoin check, not major check (no double label)."""
        c = _full_candidate(trading_pair="USDT-USD")
        result = _run_filter(
            [c],
            exclude_stablecoins=True,
            exclude_major_assets=True,
            excluded_base_assets=["USDT"],
        )
        assert result.n_rejected == 1
        reasons = result.rejected[0].all_reasons
        assert REASON_STABLECOIN_OR_FOREX in reasons
        assert REASON_EXCLUDED_MAJOR_ASSET not in reasons


# ---------------------------------------------------------------------------
# 3. LOW_SCORE gate (in service._run_scan)
# ---------------------------------------------------------------------------

class TestLowScoreGate:
    """Candidates with score < min_score are rejected even after hard filter."""

    @pytest.mark.asyncio
    async def test_low_score_candidate_not_accepted(self, tmp_path: Path) -> None:
        """A candidate with no trend data scores ~0.17 and must not be accepted
        when min_score=0.70."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        # Candidate passes hard filter (all momentum fields set) but has no
        # trend_1h/trend_4h/volume_expansion, so scorer gives ~0.17.
        c = _full_candidate()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        accepted = [s for s in result.signals if s.accepted]
        assert len(accepted) == 0

    @pytest.mark.asyncio
    async def test_low_score_candidate_appears_as_score_too_low(
        self, tmp_path: Path
    ) -> None:
        """Low-scoring candidate has rejection_reason == SCORE_TOO_LOW."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        c = _full_candidate()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        score_rejected = [
            s for s in result.signals
            if not s.accepted and s.rejection_reason == REASON_SCORE_TOO_LOW
        ]
        assert len(score_rejected) >= 1

    @pytest.mark.asyncio
    async def test_accepted_signals_score_above_min(self, tmp_path: Path) -> None:
        """Any accepted signal must have score >= config.scoring.min_score."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [
            _full_candidate(trading_pair=f"T{i}-USDT") for i in range(20)
        ]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        min_score = svc._config.scoring.min_score
        for sig in result.signals:
            if sig.accepted:
                assert sig.score >= min_score, (
                    f"{sig.trading_pair} accepted with score {sig.score:.3f} < {min_score}"
                )

    @pytest.mark.asyncio
    async def test_top_signals_are_only_accepted(self, tmp_path: Path) -> None:
        """top_signals must only contain accepted candidates."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [
            _full_candidate(trading_pair=f"C{i}-USDT") for i in range(5)
        ]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        for sig in result.top_signals:
            assert sig.accepted

    @pytest.mark.asyncio
    async def test_accepted_signals_have_valid_momentum_data(
        self, tmp_path: Path
    ) -> None:
        """Any accepted signal must have non-None price_change_5m/15m and volume_ratio."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_full_candidate()]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        for sig in result.signals:
            if sig.accepted:
                assert sig.price_change_5m_pct is not None
                assert sig.price_change_15m_pct is not None
                assert sig.volume_ratio is not None
