# test_signal_coverage_report.py — tests for DataCoverageReport, blind-warning,
# top-rejected, and coverage counter correctness.
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.services.momentum_signal_service import MomentumSignalService
from multi_coin_grid_pro.signals.momentum_config import OutputConfig, ServiceConfig
from multi_coin_grid_pro.signals.momentum_models import DataCoverageReport, EnrichedCandidate, ExchangeCoverageStats

NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _candidate(
    exchange: str = "bitget",
    trading_pair: str = "ALT-USDT",
    price_change_5m_pct: float = 3.5,
    price_change_15m_pct: float = 6.0,
    volume_ratio: float = 4.0,
    orderbook_depth_quote: float = 12_000.0,
    price_change_1m_pct: float = 1.0,
    candles_fetched_at: float = NOW - 30.0,
    ob_fetched_at: float = NOW - 2.0,
    spread_pct: float = 0.10,
) -> EnrichedCandidate:
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
        orderbook_depth_quote=orderbook_depth_quote,
        price_change_1m_pct=price_change_1m_pct,
        candles_fetched_at=candles_fetched_at,
        ob_fetched_at=ob_fetched_at,
    )


def _no_data_candidate(exchange: str = "bitget", trading_pair: str = "FOO-USDT") -> EnrichedCandidate:
    """Candidate with no candle or orderbook data — as if fetcher returned nothing."""
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=trading_pair,
        price=1.0,
        bid=0.999,
        ask=1.001,
        spread_pct=0.10,
        # All optional fields stay None / 0.0 defaults
        candles_fetched_at=0.0,
        ob_fetched_at=0.0,
    )


def _service(tmp_path: Path, market_data_mode: str = "full", **output_kwargs) -> MomentumSignalService:
    from multi_coin_grid_pro.signals.momentum_config import MarketDataConfig
    oc = OutputConfig(**output_kwargs) if output_kwargs else OutputConfig()
    cfg = ServiceConfig(output=oc, market_data=MarketDataConfig(mode=market_data_mode))
    return MomentumSignalService(
        config=cfg,
        db_path=str(tmp_path / "s.sqlite"),
        snapshot_path=str(tmp_path / "s.json"),
    )


# ---------------------------------------------------------------------------
# ExchangeCoverageStats model
# ---------------------------------------------------------------------------

class TestExchangeCoverageStatsModel:

    def test_dataclass_defaults_zero(self) -> None:
        stats = ExchangeCoverageStats(exchange="test")
        assert stats.pairs_total == 0
        assert stats.momentum_data_complete == 0
        assert stats.accepted == 0

    def test_fields_are_independent(self) -> None:
        a = ExchangeCoverageStats(exchange="a", pairs_total=5)
        b = ExchangeCoverageStats(exchange="b", pairs_total=10)
        assert a.pairs_total != b.pairs_total


# ---------------------------------------------------------------------------
# DataCoverageReport model
# ---------------------------------------------------------------------------

class TestDataCoverageReportModel:

    def test_total_pairs_aggregates_exchanges(self) -> None:
        cov = DataCoverageReport(by_exchange=[
            ExchangeCoverageStats(exchange="a", pairs_total=50),
            ExchangeCoverageStats(exchange="b", pairs_total=100),
        ])
        assert cov.total_pairs == 150

    def test_total_missing_aggregates_exchanges(self) -> None:
        cov = DataCoverageReport(by_exchange=[
            ExchangeCoverageStats(exchange="a", missing_momentum_data=40),
            ExchangeCoverageStats(exchange="b", missing_momentum_data=60),
        ])
        assert cov.total_missing == 100

    def test_blind_warning_default_false(self) -> None:
        cov = DataCoverageReport()
        assert not cov.blind_warning


# ---------------------------------------------------------------------------
# _build_coverage: coverage counters per exchange
# ---------------------------------------------------------------------------

class TestBuildCoverageCounters:

    @pytest.mark.asyncio
    async def test_pairs_total_per_exchange(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [
            _candidate(exchange="ex1", trading_pair="A-USDT"),
            _candidate(exchange="ex1", trading_pair="B-USDT"),
            _candidate(exchange="ex2", trading_pair="C-USDT"),
        ]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.coverage is not None
        ex1 = next(s for s in result.coverage.by_exchange if s.exchange == "ex1")
        ex2 = next(s for s in result.coverage.by_exchange if s.exchange == "ex2")
        assert ex1.pairs_total == 2
        assert ex2.pairs_total == 1

    @pytest.mark.asyncio
    async def test_tickers_ok_equals_pairs_total(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_candidate(trading_pair=f"T{i}-USDT") for i in range(5)]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        cov = result.coverage
        assert cov is not None
        for stats in cov.by_exchange:
            assert stats.tickers_ok == stats.pairs_total

    @pytest.mark.asyncio
    async def test_candles_5m_ok_counts_non_none(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [
            _candidate(trading_pair="HAS-USDT", price_change_5m_pct=3.0),
            _no_data_candidate(trading_pair="NO-USDT"),
        ]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        cov = result.coverage
        assert cov is not None
        stats = cov.by_exchange[0]
        assert stats.candles_5m_ok == 1
        assert stats.missing_momentum_data == 1   # NO-USDT has no data

    @pytest.mark.asyncio
    async def test_momentum_data_complete_vs_missing(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        complete = [_candidate(trading_pair=f"C{i}-USDT") for i in range(3)]
        missing = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(7)]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=complete + missing)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        cov = result.coverage
        assert cov is not None
        stats = cov.by_exchange[0]
        assert stats.momentum_data_complete == 3
        assert stats.missing_momentum_data == 7

    @pytest.mark.asyncio
    async def test_orderbook_ok_counts_depth_not_none(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [
            _candidate(trading_pair="HAS-USDT", orderbook_depth_quote=5000.0),
            _no_data_candidate(trading_pair="NO-USDT"),  # OB depth = None
        ]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        cov = result.coverage
        assert cov is not None
        stats = cov.by_exchange[0]
        assert stats.orderbook_ok == 1

    @pytest.mark.asyncio
    async def test_accepted_rejected_per_exchange(self, tmp_path: Path) -> None:
        """accepted/rejected in coverage matches actual signal outcome."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"X{i}-USDT") for i in range(4)]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        cov = result.coverage
        assert cov is not None
        stats = cov.by_exchange[0]
        assert stats.accepted == 0
        assert stats.rejected == 4


# ---------------------------------------------------------------------------
# Missing reason breakdown
# ---------------------------------------------------------------------------

class TestMissingReasonBreakdown:

    @pytest.mark.asyncio
    async def test_missing_price_change_5m_counted(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        # 3 no-data candidates → all missing 5m
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(3)]
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        bd = result.coverage.missing_reason_breakdown
        assert bd.get("MISSING_PRICE_CHANGE_5M", 0) == 3
        assert bd.get("MISSING_PRICE_CHANGE_15M", 0) == 3
        assert bd.get("MISSING_VOLUME_RATIO", 0) == 3

    @pytest.mark.asyncio
    async def test_missing_candles_counted_when_fetched_at_zero(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        c_no_candles = _no_data_candidate()          # candles_fetched_at = 0.0
        c_has_candles = _candidate(trading_pair="HAS-USDT")   # candles_fetched_at > 0
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c_no_candles, c_has_candles])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        bd = result.coverage.missing_reason_breakdown
        assert bd.get("MISSING_CANDLES", 0) == 1

    @pytest.mark.asyncio
    async def test_missing_orderbook_counted_when_depth_none(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        c = _no_data_candidate()   # orderbook_depth_quote = None
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        bd = result.coverage.missing_reason_breakdown
        assert bd.get("MISSING_ORDERBOOK", 0) == 1

    @pytest.mark.asyncio
    async def test_complete_candidate_not_in_missing_breakdown(self, tmp_path: Path) -> None:
        """A fully-enriched candidate should not appear in missing reason counts."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        c = _candidate()
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        bd = result.coverage.missing_reason_breakdown
        assert bd.get("MISSING_PRICE_CHANGE_5M", 0) == 0
        assert bd.get("MISSING_PRICE_CHANGE_15M", 0) == 0
        assert bd.get("MISSING_VOLUME_RATIO", 0) == 0
        assert bd.get("MISSING_CANDLES", 0) == 0
        assert bd.get("MISSING_ORDERBOOK", 0) == 0


# ---------------------------------------------------------------------------
# Blind warning (> 80% missing momentum data)
# ---------------------------------------------------------------------------

class TestBlindWarning:

    @pytest.mark.asyncio
    async def test_blind_warning_triggered_above_80pct(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        # 9 no-data + 1 complete = 90% missing → warning
        candidates = (
            [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(9)]
            + [_candidate(trading_pair="OK-USDT")]
        )
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.coverage is not None
        assert result.coverage.blind_warning is True

    @pytest.mark.asyncio
    async def test_blind_warning_not_triggered_below_80pct(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        # 5 no-data + 5 complete = 50% missing → no warning
        candidates = (
            [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(5)]
            + [_candidate(trading_pair=f"OK{i}-USDT") for i in range(5)]
        )
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.coverage is not None
        assert result.coverage.blind_warning is False

    @pytest.mark.asyncio
    async def test_blind_warning_exactly_80pct_no_trigger(self, tmp_path: Path) -> None:
        svc = _service(tmp_path)
        svc._session = MagicMock()
        # Exactly 80% missing — threshold is STRICTLY > 80%
        candidates = (
            [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(8)]
            + [_candidate(trading_pair=f"OK{i}-USDT") for i in range(2)]
        )
        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.coverage is not None
        assert result.coverage.blind_warning is False

    @pytest.mark.asyncio
    async def test_blind_warning_logged_when_triggered(self, tmp_path: Path) -> None:
        """blind_warning=True must emit a logger.warning call."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(10)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            with patch(
                "multi_coin_grid_pro.services.momentum_signal_service.logger"
            ) as mock_logger:
                await svc._run_scan("t", time.time())
                assert mock_logger.warning.called
                call_args = mock_logger.warning.call_args[0][0]
                assert "MOMENTUM_DATA_WARNING" in call_args

    @pytest.mark.asyncio
    async def test_no_warning_when_coverage_disabled(self, tmp_path: Path) -> None:
        """When log_data_coverage=False, coverage is None and no warning is emitted."""
        svc = _service(tmp_path, log_data_coverage=False)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(10)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            with patch(
                "multi_coin_grid_pro.services.momentum_signal_service.logger"
            ) as mock_logger:
                result = await svc._run_scan("t", time.time())
                assert result.coverage is None
                assert not mock_logger.warning.called


# ---------------------------------------------------------------------------
# Top rejected candidates
# ---------------------------------------------------------------------------

class TestTopRejectedCandidates:

    @pytest.mark.asyncio
    async def test_top_rejected_are_sorted_by_score_desc(self, tmp_path: Path) -> None:
        """top_rejected must be in descending score order."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_candidate(trading_pair=f"X{i}-USDT") for i in range(5)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        tr = result.top_rejected
        scores = [s.score for s in tr]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_rejected_not_accepted(self, tmp_path: Path) -> None:
        """Every entry in top_rejected must be a rejected signal."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(5)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        for sig in result.top_rejected:
            assert not sig.accepted

    @pytest.mark.asyncio
    async def test_top_rejected_contains_expected_metrics(self, tmp_path: Path) -> None:
        """top_rejected entries expose the required diagnostic fields."""
        svc = _service(tmp_path)
        svc._session = MagicMock()
        c = _candidate(orderbook_depth_quote=8500.0)

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=[c])
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.top_rejected
        sig = result.top_rejected[0]
        # All required diagnostic fields must be present
        assert sig.exchange == c.exchange
        assert sig.trading_pair == c.trading_pair
        assert isinstance(sig.score, float)
        assert sig.price_change_5m_pct == c.price_change_5m_pct
        assert sig.price_change_15m_pct == c.price_change_15m_pct
        assert sig.volume_ratio == c.volume_ratio
        assert sig.spread_pct == c.spread_pct
        assert sig.orderbook_depth_quote == 8500.0
        assert sig.rejection_reason is not None

    @pytest.mark.asyncio
    async def test_top_rejected_respects_top_n_limit(self, tmp_path: Path) -> None:
        """top_rejected must not exceed output.top_rejected_n."""
        svc = _service(tmp_path, top_rejected_n=3)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(10)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert len(result.top_rejected) <= 3

    @pytest.mark.asyncio
    async def test_top_rejected_empty_when_disabled(self, tmp_path: Path) -> None:
        svc = _service(tmp_path, log_top_rejected_candidates=False)
        svc._session = MagicMock()
        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(5)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result = await svc._run_scan("t", time.time())

        assert result.top_rejected == []


# ---------------------------------------------------------------------------
# Accepted candidates not affected by coverage logging
# ---------------------------------------------------------------------------

class TestAcceptedNotAffectedByCoverage:

    @pytest.mark.asyncio
    async def test_coverage_on_vs_off_same_accepted(self, tmp_path: Path) -> None:
        """Enabling/disabling coverage must not change which signals are accepted."""
        # Build a service with coverage ON
        cfg_on = ServiceConfig(output=OutputConfig(log_data_coverage=True))
        svc_on = MomentumSignalService(
            config=cfg_on,
            db_path=str(tmp_path / "on.sqlite"),
            snapshot_path=str(tmp_path / "on.json"),
        )
        svc_on._session = MagicMock()

        cfg_off = ServiceConfig(output=OutputConfig(log_data_coverage=False))
        svc_off = MomentumSignalService(
            config=cfg_off,
            db_path=str(tmp_path / "off.sqlite"),
            snapshot_path=str(tmp_path / "off.json"),
        )
        svc_off._session = MagicMock()

        candidates = [_no_data_candidate(trading_pair=f"N{i}-USDT") for i in range(5)]

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result_on = await svc_on._run_scan("t1", time.time())

        with patch(
            "multi_coin_grid_pro.services.momentum_signal_service.MarketDataFetcher"
        ) as MockFetcher:
            MockFetcher.return_value.fetch_all = AsyncMock(return_value=candidates)
            MockFetcher.return_value.enrich_all = AsyncMock(side_effect=lambda c, *a, **kw: c)
            result_off = await svc_off._run_scan("t2", time.time())

        assert result_on.total_accepted == result_off.total_accepted
        assert result_on.total_rejected == result_off.total_rejected
