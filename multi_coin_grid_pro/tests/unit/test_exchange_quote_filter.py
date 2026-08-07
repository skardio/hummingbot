# test_exchange_quote_filter.py — unit tests for per-exchange quote asset filtering.
# Covers ExchangeConfig.effective_quote_assets(), _is_wanted_pair(), fetch_all
# enabled-flag skip, apply_preselection stats metadata, and reporter table output.
# No real HTTP calls. No asyncio I/O beyond the enabled-flag test.
import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_preselection
from multi_coin_grid_pro.signals.momentum_config import ExchangeConfig, ServiceConfig
from multi_coin_grid_pro.signals.momentum_market_data import BitgetFetcher, KrakenFetcher, MarketDataFetcher, OKXFetcher
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate, ExchangePreselectionStats, PreselectionReport
from multi_coin_grid_pro.signals.momentum_preselection import apply_preselection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(10)


def _mock_session() -> MagicMock:
    return MagicMock(spec=["get"])


def _exchange_cfg(
    exchange: str,
    quote_assets: list,
    allowed_quote_assets: list = None,
    disallowed_quote_assets: list = None,
    region: str = "global",
    enabled: bool = True,
) -> ExchangeConfig:
    return ExchangeConfig(
        exchange=exchange,
        api_url=f"https://api.{exchange}.com",
        quote_assets=quote_assets,
        allowed_quote_assets=allowed_quote_assets or [],
        disallowed_quote_assets=disallowed_quote_assets or [],
        region=region,
        enabled=enabled,
    )


def _candidate(
    exchange: str = "kraken",
    pair: str = "SOL-USD",
    spread_pct: float = 0.05,
    quote_volume_24h: Optional[float] = 500_000.0,
    price_change_24h_pct: Optional[float] = 5.0,
) -> EnrichedCandidate:
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=pair,
        price=100.0,
        bid=99.95,
        ask=100.05,
        spread_pct=spread_pct,
        quote_volume_24h=quote_volume_24h,
        price_change_24h_pct=price_change_24h_pct,
    )


# ---------------------------------------------------------------------------
# ExchangeConfig.effective_quote_assets()
# ---------------------------------------------------------------------------

class TestEffectiveQuoteAssets:

    def test_returns_allowed_when_set(self) -> None:
        cfg = _exchange_cfg("okx", ["USDT", "USDC"], allowed_quote_assets=["USDC"])
        assert cfg.effective_quote_assets() == ["USDC"]

    def test_falls_back_to_quote_assets_when_allowed_empty(self) -> None:
        cfg = _exchange_cfg("kraken", ["USD"], allowed_quote_assets=[])
        assert cfg.effective_quote_assets() == ["USD"]

    def test_falls_back_to_quote_assets_when_allowed_not_provided(self) -> None:
        cfg = ExchangeConfig(exchange="bitget", api_url="https://api.bitget.com", quote_assets=["USDT"])
        assert cfg.effective_quote_assets() == ["USDT"]

    def test_allowed_takes_precedence_over_quote_assets(self) -> None:
        cfg = _exchange_cfg("okx", ["USDT", "USDC"], allowed_quote_assets=["USDC"])
        # even though quote_assets includes USDT, effective must only return USDC
        assert "USDT" not in cfg.effective_quote_assets()
        assert "USDC" in cfg.effective_quote_assets()

    def test_enabled_default_true(self) -> None:
        cfg = ExchangeConfig(exchange="kraken", api_url="https://api.kraken.com", quote_assets=["USD"])
        assert cfg.enabled is True

    def test_disabled_exchange(self) -> None:
        cfg = _exchange_cfg("kraken", ["USD"], enabled=False)
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# _is_wanted_pair — OKX (USDC-only allowlist)
# ---------------------------------------------------------------------------

class TestOKXQuoteFilter:

    def _okx(self, quote_assets: list) -> OKXFetcher:
        return OKXFetcher(
            api_url="https://www.okx.com",
            quote_assets=quote_assets,
            session=_mock_session(),
            semaphore=_semaphore(),
        )

    def test_usdc_pair_accepted(self) -> None:
        fetcher = self._okx(["USDC"])
        assert fetcher._is_wanted_pair("SOL-USDC") is True

    def test_usdt_pair_rejected_when_usdc_only(self) -> None:
        fetcher = self._okx(["USDC"])
        assert fetcher._is_wanted_pair("PHA-USDT") is False

    def test_usdt_pair_rejected_near_usdt(self) -> None:
        fetcher = self._okx(["USDC"])
        assert fetcher._is_wanted_pair("NEAR-USDT") is False

    def test_btc_usdc_pair_accepted(self) -> None:
        fetcher = self._okx(["USDC"])
        assert fetcher._is_wanted_pair("BTC-USDC") is True

    def test_both_accepted_when_both_allowed(self) -> None:
        fetcher = self._okx(["USDT", "USDC"])
        assert fetcher._is_wanted_pair("SOL-USDT") is True
        assert fetcher._is_wanted_pair("SOL-USDC") is True

    def test_malformed_pair_rejected(self) -> None:
        fetcher = self._okx(["USDC"])
        assert fetcher._is_wanted_pair("SOLUSDC") is False


# ---------------------------------------------------------------------------
# _is_wanted_pair — Kraken (USD-only allowlist)
# ---------------------------------------------------------------------------

class TestKrakenQuoteFilter:

    def _kraken(self, quote_assets: list) -> KrakenFetcher:
        return KrakenFetcher(
            api_url="https://api.kraken.com",
            quote_assets=quote_assets,
            session=_mock_session(),
            semaphore=_semaphore(),
        )

    def test_usd_pair_accepted(self) -> None:
        fetcher = self._kraken(["USD"])
        assert fetcher._is_wanted_pair("SOL-USD") is True

    def test_usdt_pair_rejected_when_usd_only(self) -> None:
        fetcher = self._kraken(["USD"])
        assert fetcher._is_wanted_pair("SOL-USDT") is False

    def test_eur_pair_rejected_when_usd_only(self) -> None:
        fetcher = self._kraken(["USD"])
        assert fetcher._is_wanted_pair("BTC-EUR") is False

    def test_btc_usd_accepted(self) -> None:
        fetcher = self._kraken(["USD"])
        assert fetcher._is_wanted_pair("BTC-USD") is True


# ---------------------------------------------------------------------------
# _is_wanted_pair — Bitget (USDT-only allowlist)
# ---------------------------------------------------------------------------

class TestBitgetQuoteFilter:

    def _bitget(self, quote_assets: list) -> BitgetFetcher:
        return BitgetFetcher(
            api_url="https://api.bitget.com",
            quote_assets=quote_assets,
            session=_mock_session(),
            semaphore=_semaphore(),
        )

    def test_usdt_pair_accepted(self) -> None:
        fetcher = self._bitget(["USDT"])
        assert fetcher._is_wanted_pair("SOL-USDT") is True

    def test_usdc_pair_rejected_when_usdt_only(self) -> None:
        fetcher = self._bitget(["USDT"])
        assert fetcher._is_wanted_pair("SOL-USDC") is False

    def test_usd_pair_rejected_when_usdt_only(self) -> None:
        fetcher = self._bitget(["USDT"])
        assert fetcher._is_wanted_pair("SOL-USD") is False

    def test_btc_usdt_accepted(self) -> None:
        fetcher = self._bitget(["USDT"])
        assert fetcher._is_wanted_pair("BTC-USDT") is True


# ---------------------------------------------------------------------------
# fetch_all — disabled exchange is skipped entirely
# ---------------------------------------------------------------------------

class TestFetchAllEnabledFlag:

    @pytest.mark.asyncio
    async def test_disabled_exchange_not_fetched(self) -> None:
        """fetch_all must not call fetch_exchange for a disabled exchange."""
        cfgs = [
            _exchange_cfg("kraken", ["USD"], allowed_quote_assets=["USD"], enabled=False),
        ]
        fetcher = MarketDataFetcher(session=_mock_session(), max_concurrency=2)
        with patch.object(fetcher, "fetch_exchange", new_callable=AsyncMock) as mock_fe:
            result = await fetcher.fetch_all(cfgs)
        mock_fe.assert_not_called()
        assert result == []

    @pytest.mark.asyncio
    async def test_enabled_exchange_is_fetched(self) -> None:
        """fetch_all calls fetch_exchange for an enabled exchange."""
        cfgs = [
            _exchange_cfg("kraken", ["USD"], allowed_quote_assets=["USD"], enabled=True),
        ]
        fetcher = MarketDataFetcher(session=_mock_session(), max_concurrency=2)
        with patch.object(fetcher, "fetch_exchange", new_callable=AsyncMock, return_value=[]) as mock_fe:
            await fetcher.fetch_all(cfgs)
        mock_fe.assert_called_once_with("kraken", "https://api.kraken.com", ["USD"])

    @pytest.mark.asyncio
    async def test_mixed_enabled_disabled(self) -> None:
        """fetch_all only calls fetch_exchange for the enabled exchange."""
        cfgs = [
            _exchange_cfg("kraken", ["USD"], allowed_quote_assets=["USD"], enabled=True),
            _exchange_cfg("okx", ["USDC"], allowed_quote_assets=["USDC"], enabled=False),
        ]
        fetcher = MarketDataFetcher(session=_mock_session(), max_concurrency=2)
        with patch.object(fetcher, "fetch_exchange", new_callable=AsyncMock, return_value=[]) as mock_fe:
            await fetcher.fetch_all(cfgs)
        assert mock_fe.call_count == 1
        args = mock_fe.call_args[0]
        assert args[0] == "kraken"

    @pytest.mark.asyncio
    async def test_effective_quote_assets_passed_to_fetch_exchange(self) -> None:
        """fetch_all passes effective_quote_assets (not quote_assets) to fetch_exchange."""
        cfgs = [
            _exchange_cfg("okx", ["USDT", "USDC"], allowed_quote_assets=["USDC"], enabled=True),
        ]
        fetcher = MarketDataFetcher(session=_mock_session(), max_concurrency=2)
        with patch.object(fetcher, "fetch_exchange", new_callable=AsyncMock, return_value=[]) as mock_fe:
            await fetcher.fetch_all(cfgs)
        # Must pass ["USDC"], not ["USDT", "USDC"]
        args = mock_fe.call_args[0]
        assert args[2] == ["USDC"]


# ---------------------------------------------------------------------------
# apply_preselection — stats reflect exchange config metadata
# ---------------------------------------------------------------------------

class TestPreselectionStatsMetadata:

    def _service_config(self, exchange_cfgs) -> ServiceConfig:
        return ServiceConfig(exchanges=exchange_cfgs)

    def test_stats_region_populated_from_config(self) -> None:
        cfg = _exchange_cfg("okx", ["USDC"], allowed_quote_assets=["USDC"], region="europe")
        candidates = [_candidate(exchange="okx", pair="SOL-USDC")]
        _, report = apply_preselection(candidates, self._service_config([cfg]), max_per_exchange=10)
        stats = next(s for s in report.by_exchange if s.exchange == "okx")
        assert stats.region == "europe"

    def test_stats_allowed_quote_assets_populated(self) -> None:
        cfg = _exchange_cfg("okx", ["USDT", "USDC"], allowed_quote_assets=["USDC"])
        candidates = [_candidate(exchange="okx", pair="SOL-USDC")]
        _, report = apply_preselection(candidates, self._service_config([cfg]), max_per_exchange=10)
        stats = next(s for s in report.by_exchange if s.exchange == "okx")
        assert stats.allowed_quote_assets == ["USDC"]

    def test_stats_enabled_populated(self) -> None:
        cfg = _exchange_cfg("kraken", ["USD"], allowed_quote_assets=["USD"], enabled=True)
        candidates = [_candidate(exchange="kraken", pair="SOL-USD")]
        _, report = apply_preselection(candidates, self._service_config([cfg]), max_per_exchange=10)
        stats = next(s for s in report.by_exchange if s.exchange == "kraken")
        assert stats.enabled is True

    def test_stats_fallback_when_no_exchange_config(self) -> None:
        """Exchange not in config.exchanges gets default region/enabled."""
        candidates = [_candidate(exchange="unknown_exchange", pair="SOL-USD")]
        config = ServiceConfig()  # no exchanges configured
        _, report = apply_preselection(candidates, config, max_per_exchange=10)
        stats = next(s for s in report.by_exchange if s.exchange == "unknown_exchange")
        assert stats.region == "global"
        assert stats.enabled is True
        assert stats.allowed_quote_assets == []


# ---------------------------------------------------------------------------
# _fmt_preselection reporter — new columns in output
# ---------------------------------------------------------------------------

class TestFmtPreselection:

    def _report(self) -> PreselectionReport:
        return PreselectionReport(by_exchange=[
            ExchangePreselectionStats(
                exchange="kraken",
                universe_total=659,
                eligible=70,
                selected=50,
                region="global",
                allowed_quote_assets=["USD"],
                enabled=True,
            ),
            ExchangePreselectionStats(
                exchange="okx",
                universe_total=89,
                eligible=45,
                selected=40,
                region="europe",
                allowed_quote_assets=["USDC"],
                enabled=True,
            ),
        ])

    def test_region_column_present(self) -> None:
        output = _fmt_preselection(self._report())
        assert "global" in output
        assert "europe" in output

    def test_quotes_column_present(self) -> None:
        output = _fmt_preselection(self._report())
        assert "USD" in output
        assert "USDC" in output

    def test_enabled_column_present(self) -> None:
        output = _fmt_preselection(self._report())
        assert "true" in output

    def test_universe_eligible_selected_present(self) -> None:
        output = _fmt_preselection(self._report())
        assert "659" in output
        assert "70" in output
        assert "50" in output
        assert "89" in output
        assert "45" in output
        assert "40" in output

    def test_exchange_names_present(self) -> None:
        output = _fmt_preselection(self._report())
        assert "kraken" in output
        assert "okx" in output
