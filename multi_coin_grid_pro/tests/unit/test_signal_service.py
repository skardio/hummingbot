# test_signal_service.py — unit tests for momentum_signal_service.py
# No real HTTP, no real SQLite writes in network paths.
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.services.momentum_signal_service import (
    _BANNER,
    DISCLAIMER,
    REASON_SCORE_TOO_HIGH_ANALYSIS_VARIANT,
    MomentumSignalService,
)
from multi_coin_grid_pro.signals.momentum_config import ServiceConfig
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate, ScanResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**kwargs) -> ServiceConfig:
    """Create a minimal valid ServiceConfig."""
    return ServiceConfig(**kwargs)


def _service(tmp_path: Path, **kwargs) -> MomentumSignalService:
    return MomentumSignalService(
        config=_config(**kwargs),
        db_path=str(tmp_path / "signals.sqlite"),
        snapshot_path=str(tmp_path / "snapshot.json"),
    )


def _candidate(
    trading_pair: str = "BTC-USD",
    exchange: str = "kraken",
    spread_pct: float = 0.10,
    price_change_5m_pct: float = 3.5,
    price_change_15m_pct: float = 6.0,
    volume_ratio: float = 4.0,
) -> EnrichedCandidate:
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=trading_pair,
        price=30000.0,
        bid=29999.0,
        ask=30001.0,
        spread_pct=spread_pct,
        price_change_5m_pct=price_change_5m_pct,
        price_change_15m_pct=price_change_15m_pct,
        volume_ratio=volume_ratio,
    )


# ---------------------------------------------------------------------------
# MomentumSignalService — construction & mode guard
# ---------------------------------------------------------------------------

class TestServiceInit:

    def test_accepts_signal_only_mode(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        assert svc._config.mode == "signal_only"

    def test_rejects_wrong_mode(self, tmp_path: Path) -> None:
        config = _config()
        config.mode = "live"   # force-override after creation
        with pytest.raises(AssertionError):
            MomentumSignalService(
                config=config,
                db_path=str(tmp_path / "s.sqlite"),
                snapshot_path=str(tmp_path / "s.json"),
            )

    def test_rejects_empty_mode(self, tmp_path: Path) -> None:
        config = _config()
        config.mode = ""
        with pytest.raises(AssertionError):
            MomentumSignalService(
                config=config,
                db_path=str(tmp_path / "s.sqlite"),
                snapshot_path=str(tmp_path / "s.json"),
            )

    def test_banner_contains_disclaimer(self) -> None:
        assert DISCLAIMER in _BANNER

    def test_banner_contains_read_only(self) -> None:
        assert "READ-ONLY" in _BANNER


# ---------------------------------------------------------------------------
# _annotate — pure state annotation (no I/O when no exchange paths set)
# ---------------------------------------------------------------------------

class TestAnnotate:

    def test_annotate_empty_exchanges_unchanged(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        candidates = [_candidate("BTC-USD"), _candidate("ETH-USD")]
        result = svc._annotate(candidates)
        assert all(not c.active_grid_position for c in result)
        assert all(not c.blacklisted for c in result)

    def test_annotate_returns_same_list(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        candidates = [_candidate()]
        result = svc._annotate(candidates)
        assert result is candidates


# ---------------------------------------------------------------------------
# _run_scan — mocked MarketDataFetcher
# ---------------------------------------------------------------------------

class TestRunScan:

    @pytest.mark.asyncio
    async def test_run_scan_returns_scan_result(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        candidate = _candidate()
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[candidate])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("test-scan", time.time())

        assert isinstance(result, ScanResult)
        assert result.scan_id == "test-scan"

    @pytest.mark.asyncio
    async def test_run_scan_scan_duration_positive(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        assert result.scan_duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_run_scan_rejected_candidates_in_signals(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        # Candidate that will be rejected by spread filter
        bad = _candidate(spread_pct=5.0)  # way above 0.35% max
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[bad])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        rejected = [s for s in result.signals if not s.accepted]
        assert len(rejected) >= 1

    @pytest.mark.asyncio
    async def test_run_scan_empty_exchange_returns_empty_scan(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("empty", time.time())

        assert result.total_scanned == 0
        assert result.total_accepted == 0

    @pytest.mark.asyncio
    async def test_run_scan_accepted_signal_has_rank(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        # Candidate that passes all filters (spread OK, momentum OK, volume OK)
        good = _candidate(
            spread_pct=0.05,
            price_change_5m_pct=5.0,
            price_change_15m_pct=8.0,
            volume_ratio=4.5,
        )
        good.ob_fetched_at = 0.0  # skip orderbook staleness

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[good])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        accepted = [s for s in result.signals if s.accepted]
        if accepted:
            assert accepted[0].rank == 1


# ---------------------------------------------------------------------------
# start() — cancel path
# ---------------------------------------------------------------------------

class TestServiceStart:

    @pytest.mark.asyncio
    async def test_start_cancels_cleanly(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)

        async def mock_loop():
            raise asyncio.CancelledError()

        svc._run_loop = mock_loop
        # Should complete without raising
        await svc.start()

    @pytest.mark.asyncio
    async def test_start_closes_session_on_cancel(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)

        async def mock_loop():
            raise asyncio.CancelledError()

        svc._run_loop = mock_loop
        await svc.start()
        # After start, _session should be closed (aiohttp.ClientSession.closed = True)
        assert svc._session is not None
        assert svc._session.closed

    @pytest.mark.asyncio
    async def test_start_logs_banner(self, tmp_path: Path, caplog) -> None:
        import logging
        svc = _service(tmp_path)

        async def mock_loop():
            raise asyncio.CancelledError()

        svc._run_loop = mock_loop

        with caplog.at_level(logging.INFO):
            await svc.start()

        assert DISCLAIMER in caplog.text


# ---------------------------------------------------------------------------
# _build_coverage — sample mode and enriched tracking
# ---------------------------------------------------------------------------

class TestBuildCoverage:

    def _enriched_candidate(
        self, exchange: str = "kraken", complete: bool = True, is_enriched: bool = True
    ) -> EnrichedCandidate:
        """Helper to build a candidate with or without enrichment."""
        c = EnrichedCandidate(
            exchange=exchange,
            trading_pair="BTC-USD",
            price=30000.0,
            bid=29999.0,
            ask=30001.0,
            spread_pct=0.007,
        )
        if is_enriched:
            c.candles_fetched_at = time.time()
            if complete:
                c.price_change_5m_pct = 2.0
                c.price_change_15m_pct = 3.0
                c.volume_ratio = 2.5
        return c

    def test_sample_mode_no_global_blind_when_enriched_ok(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        # 1819 candidates total, only 75 enriched (all complete) — sample mode
        candidates = (
            [self._enriched_candidate(is_enriched=True, complete=True)] * 75
            + [self._enriched_candidate(is_enriched=False)] * 1744
        )
        coverage = svc._build_coverage(candidates, [], time.time(), sample_mode=True)
        # enriched: 75 complete, 0 incomplete → no blind
        assert coverage.sample_mode is True
        assert coverage.blind_warning is False
        assert coverage.enriched_total == 75
        assert coverage.enriched_complete == 75
        assert coverage.enriched_incomplete == 0

    def test_sample_mode_blind_when_enriched_mostly_incomplete(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        # 25 enriched, 6 complete, 19 incomplete → 76% incomplete → blind
        complete = [self._enriched_candidate(is_enriched=True, complete=True)] * 6
        incomplete = [self._enriched_candidate(is_enriched=True, complete=False)] * 19
        candidates = complete + incomplete
        coverage = svc._build_coverage(candidates, [], time.time(), sample_mode=True)
        assert coverage.blind_warning is True

    def test_non_sample_mode_global_blind_when_mostly_missing(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        # 100 candidates, 90 missing complete data → 90% → blind
        complete = [self._enriched_candidate(is_enriched=True, complete=True)] * 10
        incomplete = [self._enriched_candidate(is_enriched=False, complete=False)] * 90
        candidates = complete + incomplete
        coverage = svc._build_coverage(candidates, [], time.time(), sample_mode=False)
        assert coverage.blind_warning is True

    def test_coverage_has_sample_mode_fields(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        candidates = [self._enriched_candidate(is_enriched=True, complete=True)] * 3
        coverage = svc._build_coverage(candidates, [], time.time(), sample_mode=True)
        assert hasattr(coverage, "sample_mode")
        assert hasattr(coverage, "enriched_total")
        assert hasattr(coverage, "enriched_complete")
        assert hasattr(coverage, "enriched_incomplete")


# ---------------------------------------------------------------------------
# _run_scan — top_rejected vs missing_data_sample split
# ---------------------------------------------------------------------------

class TestRunScanRejectedSplit:

    def _good_rejected(self) -> EnrichedCandidate:
        """Candidate rejected by score but with complete momentum data."""
        c = _candidate(
            spread_pct=5.0,  # rejected by spread filter
            price_change_5m_pct=2.0,
            price_change_15m_pct=3.5,
            volume_ratio=2.1,
        )
        return c

    def _na_candidate(self) -> EnrichedCandidate:
        """Candidate with no momentum data."""
        c = EnrichedCandidate(
            exchange="kraken",
            trading_pair="OBSCURE-USD",
            price=0.001,
            bid=0.0009,
            ask=0.0011,
            spread_pct=5.0,
        )
        # price_change_5m_pct, volume_ratio remain None
        return c

    @pytest.mark.asyncio
    async def test_top_rejected_contains_only_complete_data(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        enriched = self._good_rejected()
        na = self._na_candidate()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[enriched, na])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        # top_rejected must have no n/a signals
        for sig in result.top_rejected:
            assert sig.price_change_5m_pct is not None
            assert sig.price_change_15m_pct is not None
            assert sig.volume_ratio is not None

    @pytest.mark.asyncio
    async def test_missing_data_sample_contains_na_candidates(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        na = self._na_candidate()

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[na])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        assert len(result.missing_data_sample) >= 1
        for sig in result.missing_data_sample:
            assert (
                sig.price_change_5m_pct is None
                or sig.price_change_15m_pct is None
                or sig.volume_ratio is None
            )

    @pytest.mark.asyncio
    async def test_missing_data_sample_max_10(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()

        # 15 n/a candidates — only 10 should appear in sample
        na_list = []
        for i in range(15):
            c = EnrichedCandidate(
                exchange="kraken",
                trading_pair=f"COIN{i}-USD",
                price=0.001,
                bid=0.0009,
                ask=0.0011,
                spread_pct=5.0,
            )
            na_list.append(c)

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=na_list)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("x", time.time())

        assert len(result.missing_data_sample) <= 10


# ---------------------------------------------------------------------------
# _internal_to_bitget_symbol — symbol mapping
# ---------------------------------------------------------------------------

class TestBitgetSymbolMapping:

    def test_sol_usdt_maps_to_solusdt(self) -> None:
        from multi_coin_grid_pro.signals.momentum_market_data import _internal_to_bitget_symbol
        assert _internal_to_bitget_symbol("SOL-USDT") == "SOLUSDT"

    def test_btc_usdt_maps_to_btcusdt(self) -> None:
        from multi_coin_grid_pro.signals.momentum_market_data import _internal_to_bitget_symbol
        assert _internal_to_bitget_symbol("BTC-USDT") == "BTCUSDT"

    def test_eth_eur_maps_correctly(self) -> None:
        from multi_coin_grid_pro.signals.momentum_market_data import _internal_to_bitget_symbol
        assert _internal_to_bitget_symbol("ETH-EUR") == "ETHEUR"


# ---------------------------------------------------------------------------
# Paper-test specific classification gates (signal-only service)
# ---------------------------------------------------------------------------

class TestPaperTestGates:

    def test_buy_now_blocked_in_q4_proxy_regime(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        cfg = svc._config.classification
        cfg.paper_test_enabled = True
        cfg.paper_block_buy_now_when_market_regime_ge_pct = 0.35
        cfg.buy_now_min_score = 0.80

        c = _candidate(
            trading_pair="ALT-USD",
            exchange="kraken",
            price_change_5m_pct=2.8,
            price_change_15m_pct=3.2,
            volume_ratio=4.0,
        )

        label = svc._classify_label(c, score=0.90, market_regime=0.40)
        assert label == "WATCH"

    @pytest.mark.asyncio
    async def test_bitget_preference_affects_ranking_optionally(self, tmp_path: Path) -> None:
        svc = _service(tmp_path, top_n=1)
        svc._session = MagicMock()
        cfg = svc._config.classification
        cfg.paper_test_enabled = True
        cfg.paper_prefer_exchange_enabled = True
        cfg.paper_preferred_exchange = "bitget"
        cfg.paper_preferred_exchange_rank_bonus = 0.05

        bitget_c = _candidate(trading_pair="AAA-USDT", exchange="bitget", price_change_5m_pct=2.5, price_change_15m_pct=4.5, volume_ratio=4.0, spread_pct=0.05)
        kraken_c = _candidate(trading_pair="BBB-USD", exchange="kraken", price_change_5m_pct=2.5, price_change_15m_pct=4.5, volume_ratio=4.0, spread_pct=0.05)

        breakdown = MagicMock(
            short_momentum=0.2,
            acceleration=0.2,
            volume_spike=0.2,
            liquidity=0.2,
            risk=0.2,
        )

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher, patch(
            "multi_coin_grid_pro.services.momentum_signal_service.BuyNowScorer"
        ) as MockScorer:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[bitget_c, kraken_c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            MockScorer.return_value.score_candidate = MagicMock(return_value=0.82)
            MockScorer.return_value.score_breakdown = MagicMock(return_value=breakdown)

            result = await svc._run_scan("x", time.time())

        accepted = [s for s in result.signals if s.accepted]
        assert len(accepted) == 1
        assert accepted[0].exchange == "bitget"

    @pytest.mark.asyncio
    async def test_analysis_max_score_filter_only_when_enabled(self, tmp_path: Path) -> None:
        svc = _service(tmp_path, top_n=10)
        svc._session = MagicMock()
        cfg = svc._config.classification
        cfg.paper_test_enabled = True
        cfg.analysis_max_score_filter_enabled = True
        cfg.analysis_max_score = 0.85

        c = _candidate(
            trading_pair="HIGH-USD",
            exchange="kraken",
            price_change_5m_pct=2.5,
            price_change_15m_pct=4.5,
            volume_ratio=4.0,
            spread_pct=0.05,
        )

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher, patch(
            "multi_coin_grid_pro.services.momentum_signal_service.BuyNowScorer"
        ) as MockScorer:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda items, *a, **kw: items)
            MockScorer.return_value.score_candidate = MagicMock(return_value=0.90)
            MockScorer.return_value.score_breakdown = MagicMock(return_value=MagicMock(
                short_momentum=0.2,
                acceleration=0.2,
                volume_spike=0.2,
                liquidity=0.2,
                risk=0.2,
            ))

            result = await svc._run_scan("x", time.time())

        accepted = [s for s in result.signals if s.accepted]
        assert accepted == []
        rejected = [s for s in result.signals if not s.accepted]
        assert any(s.rejection_reason == REASON_SCORE_TOO_HIGH_ANALYSIS_VARIANT for s in rejected)
