# test_signal_market_data.py — unit tests for momentum_market_data.py
# No real HTTP calls. _get_json is replaced with AsyncMock on each fetcher.
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from multi_coin_grid_pro.signals.momentum_market_data import (
    BitgetFetcher,
    BitvavoFetcher,
    KrakenFetcher,
    MarketDataFetcher,
    OKXFetcher,
    _internal_to_bitget_symbol,
    _normalize_bitget_pair,
)
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(10)


def _mock_session() -> MagicMock:
    return MagicMock(spec=["get"])


def _make_kraken(quote_assets=None) -> KrakenFetcher:
    return KrakenFetcher(
        api_url="https://api.kraken.com",
        quote_assets=quote_assets or ["USD", "EUR"],
        session=_mock_session(),
        semaphore=_semaphore(),
    )


def _make_okx(quote_assets=None) -> OKXFetcher:
    return OKXFetcher(
        api_url="https://www.okx.com",
        quote_assets=quote_assets or ["USDT", "USDC"],
        session=_mock_session(),
        semaphore=_semaphore(),
    )


def _make_bitget(quote_assets=None) -> BitgetFetcher:
    return BitgetFetcher(
        api_url="https://api.bitget.com",
        quote_assets=quote_assets or ["USDT"],
        session=_mock_session(),
        semaphore=_semaphore(),
    )


# ---------------------------------------------------------------------------
# _normalize_bitget_pair (pure function)
# ---------------------------------------------------------------------------

class TestNormalizeBitgetPair:

    def test_btcusdt(self) -> None:
        assert _normalize_bitget_pair("BTCUSDT") == "BTC-USDT"

    def test_ethusdc(self) -> None:
        assert _normalize_bitget_pair("ETHUSDC") == "ETH-USDC"

    def test_solusdt(self) -> None:
        assert _normalize_bitget_pair("SOLUSDT") == "SOL-USDT"

    def test_btceth(self) -> None:
        assert _normalize_bitget_pair("BTCETH") == "BTC-ETH"

    def test_unknown_passthrough(self) -> None:
        assert _normalize_bitget_pair("UNKNOWN") == "UNKNOWN"


# ---------------------------------------------------------------------------
# KrakenFetcher — pure helpers
# ---------------------------------------------------------------------------

class TestKrakenFetcher:

    def test_filter_asset_pairs_wanted(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        raw = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "online"},
            "XETHZUSD": {"wsname": "ETH/USD", "status": "online"},
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online"},  # EUR not wanted
        }}
        pairs = fetcher._filter_asset_pairs(raw)
        assert set(pairs.keys()) == {"XXBTZUSD", "XETHZUSD"}
        assert pairs["XXBTZUSD"] == ("BTC", "USD")
        assert pairs["XETHZUSD"] == ("ETH", "USD")

    def test_filter_asset_pairs_skips_offline(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        raw = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "offline"},
        }}
        pairs = fetcher._filter_asset_pairs(raw)
        assert pairs == {}

    def test_filter_asset_pairs_skips_missing_wsname(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        raw = {"result": {"XXBTZUSD": {"status": "online"}}}
        pairs = fetcher._filter_asset_pairs(raw)
        assert pairs == {}

    def test_xbt_maps_to_btc(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        raw = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "online"},
        }}
        pairs = fetcher._filter_asset_pairs(raw)
        assert pairs["XXBTZUSD"][0] == "BTC"

    def test_xdg_maps_to_doge(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        raw = {"result": {
            "XDGUSD": {"wsname": "XDG/USD", "status": "online"},
        }}
        pairs = fetcher._filter_asset_pairs(raw)
        assert pairs["XDGUSD"][0] == "DOGE"

    def test_make_candidate_valid(self) -> None:
        fetcher = _make_kraken()
        data = {"b": ["29999.0", 1, "1"], "a": ["30001.0", 1, "1"], "c": ["30000.0", "0.001"]}
        c = fetcher._make_candidate(("BTC", "USD"), data)
        assert c is not None
        assert c.trading_pair == "BTC-USD"
        assert c.price == 30000.0
        assert c.bid == pytest.approx(29999.0)
        assert c.ask == pytest.approx(30001.0)
        assert c.spread_pct == pytest.approx((30001.0 - 29999.0) / 29999.0 * 100)
        assert c.exchange == "kraken"
        assert isinstance(c, EnrichedCandidate)

    def test_make_candidate_zero_bid_returns_none(self) -> None:
        fetcher = _make_kraken()
        data = {"b": ["0", 1, "1"], "a": ["30001.0", 1, "1"], "c": ["30000.0", "0.001"]}
        assert fetcher._make_candidate(("BTC", "USD"), data) is None

    def test_make_candidate_missing_key_returns_none(self) -> None:
        fetcher = _make_kraken()
        assert fetcher._make_candidate(("BTC", "USD"), {}) is None

    def test_is_wanted_pair_true(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        assert fetcher._is_wanted_pair("BTC-USD") is True

    def test_is_wanted_pair_false(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        assert fetcher._is_wanted_pair("BTC-EUR") is False

    def test_is_wanted_pair_malformed(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        assert fetcher._is_wanted_pair("BTCUSD") is False

    @pytest.mark.asyncio
    async def test_fetch_candidates_mocked(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        asset_pairs_response = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "online"},
            "XETHZUSD": {"wsname": "ETH/USD", "status": "online"},
        }}
        ticker_response = {"result": {
            "XXBTZUSD": {"b": ["29999", 1, "1"], "a": ["30001", 1, "1"], "c": ["30000", "0.001"]},
            "XETHZUSD": {"b": ["1999", 1, "1"], "a": ["2001", 1, "1"], "c": ["2000", "0.1"]},
        }}
        fetcher._get_json = AsyncMock(side_effect=[asset_pairs_response, ticker_response])

        candidates = await fetcher.fetch_candidates()
        assert len(candidates) == 2
        pairs = {c.trading_pair for c in candidates}
        assert "BTC-USD" in pairs
        assert "ETH-USD" in pairs

    @pytest.mark.asyncio
    async def test_fetch_candidates_asset_pairs_error_returns_empty(self) -> None:
        fetcher = _make_kraken()
        fetcher._get_json = AsyncMock(side_effect=Exception("network error"))
        result = await fetcher.fetch_candidates()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_candidates_ticker_error_continues(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        asset_pairs_response = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "online"},
        }}
        fetcher._get_json = AsyncMock(
            side_effect=[asset_pairs_response, Exception("ticker error")]
        )
        result = await fetcher.fetch_candidates()
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_candidates_no_wanted_pairs(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        asset_pairs_response = {"result": {
            "XXBTZEUR": {"wsname": "XBT/EUR", "status": "online"},
        }}
        fetcher._get_json = AsyncMock(return_value=asset_pairs_response)
        result = await fetcher.fetch_candidates()
        assert result == []


# ---------------------------------------------------------------------------
# OKXFetcher — pure helpers
# ---------------------------------------------------------------------------

class TestOKXFetcher:

    def test_parse_item_valid(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        item = {"instId": "BTC-USDT", "bidPx": "29999", "askPx": "30001", "last": "30000"}
        c = fetcher._parse_item(item)
        assert c is not None
        assert c.trading_pair == "BTC-USDT"
        assert c.exchange == "okx"
        assert c.spread_pct == pytest.approx((30001 - 29999) / 29999 * 100)

    def test_parse_item_unwanted_quote_returns_none(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        item = {"instId": "BTC-EUR", "bidPx": "29999", "askPx": "30001", "last": "30000"}
        assert fetcher._parse_item(item) is None

    def test_parse_item_zero_bid_returns_none(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        item = {"instId": "BTC-USDT", "bidPx": "0", "askPx": "30001", "last": "30000"}
        assert fetcher._parse_item(item) is None

    def test_parse_item_missing_price_returns_none(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        item = {"instId": "BTC-USDT", "bidPx": "29999", "askPx": "30001", "last": "0"}
        assert fetcher._parse_item(item) is None

    def test_parse_item_null_bid_returns_none(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        item = {"instId": "BTC-USDT", "bidPx": None, "askPx": "30001", "last": "30000"}
        assert fetcher._parse_item(item) is None

    @pytest.mark.asyncio
    async def test_fetch_candidates_mocked(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        raw = {"data": [
            {"instId": "BTC-USDT", "bidPx": "29999", "askPx": "30001", "last": "30000"},
            {"instId": "ETH-USDT", "bidPx": "1999", "askPx": "2001", "last": "2000"},
            {"instId": "BTC-EUR", "bidPx": "28000", "askPx": "28100", "last": "28050"},
        ]}
        fetcher._get_json = AsyncMock(return_value=raw)
        candidates = await fetcher.fetch_candidates()
        assert len(candidates) == 2
        pairs = {c.trading_pair for c in candidates}
        assert "BTC-USDT" in pairs
        assert "ETH-USDT" in pairs
        assert "BTC-EUR" not in pairs

    @pytest.mark.asyncio
    async def test_fetch_candidates_network_error_returns_empty(self) -> None:
        fetcher = _make_okx()
        fetcher._get_json = AsyncMock(side_effect=Exception("timeout"))
        assert await fetcher.fetch_candidates() == []

    @pytest.mark.asyncio
    async def test_fetch_candidates_empty_data(self) -> None:
        fetcher = _make_okx()
        fetcher._get_json = AsyncMock(return_value={"data": []})
        assert await fetcher.fetch_candidates() == []


# ---------------------------------------------------------------------------
# BitgetFetcher — pure helpers
# ---------------------------------------------------------------------------

class TestBitgetFetcher:

    def test_parse_item_valid(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        item = {"symbol": "BTCUSDT", "bidPr": "29999", "askPr": "30001", "lastPr": "30000"}
        c = fetcher._parse_item(item)
        assert c is not None
        assert c.trading_pair == "BTC-USDT"
        assert c.exchange == "bitget"
        assert c.price == pytest.approx(30000.0)

    def test_parse_item_unwanted_quote_returns_none(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        item = {"symbol": "BTCEUR", "bidPr": "28000", "askPr": "28100", "lastPr": "28050"}
        assert fetcher._parse_item(item) is None

    def test_parse_item_zero_bid_returns_none(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        item = {"symbol": "BTCUSDT", "bidPr": "0", "askPr": "30001", "lastPr": "30000"}
        assert fetcher._parse_item(item) is None

    def test_parse_item_missing_lastpr_returns_none(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        item = {"symbol": "BTCUSDT", "bidPr": "29999", "askPr": "30001", "lastPr": "0"}
        assert fetcher._parse_item(item) is None

    @pytest.mark.asyncio
    async def test_fetch_candidates_mocked(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        raw = {"data": [
            {"symbol": "BTCUSDT", "bidPr": "29999", "askPr": "30001", "lastPr": "30000"},
            {"symbol": "SOLUSDT", "bidPr": "99", "askPr": "101", "lastPr": "100"},
            {"symbol": "BTCEUR", "bidPr": "28000", "askPr": "28100", "lastPr": "28050"},
        ]}
        fetcher._get_json = AsyncMock(return_value=raw)
        candidates = await fetcher.fetch_candidates()
        assert len(candidates) == 2
        pairs = {c.trading_pair for c in candidates}
        assert "BTC-USDT" in pairs
        assert "SOL-USDT" in pairs

    @pytest.mark.asyncio
    async def test_fetch_candidates_network_error_returns_empty(self) -> None:
        fetcher = _make_bitget()
        fetcher._get_json = AsyncMock(side_effect=Exception("timeout"))
        assert await fetcher.fetch_candidates() == []


# ---------------------------------------------------------------------------
# MarketDataFetcher — orchestrator
# ---------------------------------------------------------------------------

class _FakeExchangeConfig:
    def __init__(self, exchange: str, api_url: str, quote_assets: list) -> None:
        self.exchange = exchange
        self.api_url = api_url
        self.quote_assets = quote_assets
        self.enabled = True

    def effective_quote_assets(self) -> list:
        return self.quote_assets


class TestMarketDataFetcher:

    def _fetcher(self) -> MarketDataFetcher:
        return MarketDataFetcher(session=_mock_session(), max_concurrency=3)

    @pytest.mark.asyncio
    async def test_unknown_exchange_returns_empty(self) -> None:
        f = self._fetcher()
        result = await f.fetch_exchange("binance", "https://api.binance.com", ["USDT"])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_exchange_kraken(self) -> None:
        f = self._fetcher()
        asset_pairs = {"result": {
            "XXBTZUSD": {"wsname": "XBT/USD", "status": "online"},
        }}
        ticker = {"result": {
            "XXBTZUSD": {"b": ["29999", 1, "1"], "a": ["30001", 1, "1"], "c": ["30000", "0.001"]},
        }}
        # Patch _get_json on the fetcher that gets created internally
        original_init = KrakenFetcher.__init__

        captured = {}

        def patched_init(self, **kwargs):
            original_init(self, **kwargs)
            self._get_json = AsyncMock(side_effect=[asset_pairs, ticker])
            captured["fetcher"] = self

        KrakenFetcher.__init__ = lambda self, **kw: patched_init(self, **kw)
        try:
            result = await f.fetch_exchange("kraken", "https://api.kraken.com", ["USD"])
        finally:
            KrakenFetcher.__init__ = original_init

        assert any(c.trading_pair == "BTC-USD" for c in result)

    @pytest.mark.asyncio
    async def test_fetch_all_aggregates_exchanges(self) -> None:
        f = self._fetcher()
        configs = [
            _FakeExchangeConfig("okx", "https://www.okx.com", ["USDT"]),
            _FakeExchangeConfig("bitget", "https://api.bitget.com", ["USDT"]),
        ]
        okx_raw = {"data": [
            {"instId": "BTC-USDT", "bidPx": "29999", "askPx": "30001", "last": "30000"},
        ]}
        bitget_raw = {"data": [
            {"symbol": "ETHUSDT", "bidPr": "1999", "askPr": "2001", "lastPr": "2000"},
        ]}

        call_count = 0

        async def mock_get_json(self_inner, url, params=None):
            nonlocal call_count
            call_count += 1
            if "okx" in url:
                return okx_raw
            return bitget_raw

        OKXFetcher._get_json = mock_get_json
        BitgetFetcher._get_json = mock_get_json
        try:
            candidates = await f.fetch_all(configs)
        finally:
            del OKXFetcher._get_json
            del BitgetFetcher._get_json

        assert len(candidates) == 2
        exchanges = {c.exchange for c in candidates}
        assert "okx" in exchanges
        assert "bitget" in exchanges

    @pytest.mark.asyncio
    async def test_fetch_all_handles_exception_in_one_exchange(self) -> None:
        f = self._fetcher()
        configs = [
            _FakeExchangeConfig("okx", "https://www.okx.com", ["USDT"]),
        ]

        async def failing_get_json(self_inner, url, params=None):
            raise Exception("network error")

        OKXFetcher._get_json = failing_get_json
        try:
            candidates = await f.fetch_all(configs)
        finally:
            del OKXFetcher._get_json

        assert candidates == []


# ---------------------------------------------------------------------------
# _internal_to_bitget_symbol (pure function)
# ---------------------------------------------------------------------------

class TestInternalToBitgetSymbol:

    def test_sol_usdt(self) -> None:
        assert _internal_to_bitget_symbol("SOL-USDT") == "SOLUSDT"

    def test_btc_usdt(self) -> None:
        assert _internal_to_bitget_symbol("BTC-USDT") == "BTCUSDT"

    def test_eth_usdc(self) -> None:
        assert _internal_to_bitget_symbol("ETH-USDC") == "ETHUSDC"

    def test_no_dash_passthrough(self) -> None:
        assert _internal_to_bitget_symbol("BTCUSDT") == "BTCUSDT"


# ---------------------------------------------------------------------------
# KrakenFetcher.fetch_candles  (mocked _get_json)
# ---------------------------------------------------------------------------

class TestKrakenFetcherCandles:

    @pytest.mark.asyncio
    async def test_fetch_candles_parses_ohlc_format(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        # Simulate Kraken OHLC: [ts, open, high, low, close, vwap, volume, count]
        row = [1000000, "100.0", "105.0", "99.0", "102.0", "101.0", "50.5", 10]
        fetcher._get_json = AsyncMock(return_value={
            "error": [],
            "result": {"XXBTZUSD": [row], "last": 1000001},
        })
        # Need a pair_name_map entry so the lookup works
        fetcher._pair_name_map["BTC-USD"] = "XXBTZUSD"
        candles = await fetcher.fetch_candles("BTC-USD", limit=20)
        assert len(candles) == 1
        c = candles[0]
        assert c.open == 100.0
        assert c.high == 105.0
        assert c.low == 99.0
        assert c.close == 102.0
        assert c.volume == 50.5  # row[6]

    @pytest.mark.asyncio
    async def test_fetch_candles_unknown_pair_returns_empty(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        fetcher._get_json = AsyncMock(return_value={"error": [], "result": {}})
        candles = await fetcher.fetch_candles("UNKNOWN-USD", limit=5)
        assert candles == []


# ---------------------------------------------------------------------------
# KrakenFetcher.fetch_orderbook  (mocked _get_json)
# ---------------------------------------------------------------------------

class TestKrakenFetcherOrderbook:

    @pytest.mark.asyncio
    async def test_fetch_orderbook_parses_depth_format(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        # Kraken Depth: bids/asks are [price_str, amount_str, timestamp]
        fetcher._get_json = AsyncMock(return_value={
            "error": [],
            "result": {
                "XXBTZUSD": {
                    "bids": [["98000.0", "0.5", 1000000]],
                    "asks": [["98100.0", "0.3", 1000000]],
                }
            },
        })
        fetcher._pair_name_map["BTC-USD"] = "XXBTZUSD"
        ob = await fetcher.fetch_orderbook("BTC-USD", count=20)
        assert ob is not None
        assert len(ob.bids) == 1
        assert ob.bids[0] == [98000.0, 0.5]
        assert ob.asks[0] == [98100.0, 0.3]

    @pytest.mark.asyncio
    async def test_fetch_orderbook_unknown_pair_returns_none(self) -> None:
        fetcher = _make_kraken(quote_assets=["USD"])
        fetcher._get_json = AsyncMock(return_value={"error": [], "result": {}})
        ob = await fetcher.fetch_orderbook("UNKNOWN-USD", count=20)
        assert ob is None


# ---------------------------------------------------------------------------
# OKXFetcher.fetch_candles  (newest-first reversed)
# ---------------------------------------------------------------------------

class TestOKXFetcherCandles:

    @pytest.mark.asyncio
    async def test_fetch_candles_reverses_newest_first(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        # OKX returns newest-first: ts_ms=2000 then ts_ms=1000
        fetcher._get_json = AsyncMock(return_value={
            "code": "0",
            "data": [
                ["2000000", "105.0", "106.0", "104.0", "105.5", "200.0", "21000"],
                ["1000000", "100.0", "101.0", "99.0", "100.5", "100.0", "10000"],
            ],
        })
        candles = await fetcher.fetch_candles("SOL-USDT", limit=2)
        assert len(candles) == 2
        # After reversal: oldest (ts_ms=1000) first
        assert candles[0].timestamp == 1000.0  # 1000000 / 1000
        assert candles[1].timestamp == 2000.0
        assert candles[0].close == 100.5
        assert candles[1].close == 105.5

    @pytest.mark.asyncio
    async def test_fetch_candles_empty_data_returns_empty(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={"code": "0", "data": []})
        candles = await fetcher.fetch_candles("SOL-USDT", limit=5)
        assert candles == []


# ---------------------------------------------------------------------------
# OKXFetcher.fetch_orderbook
# ---------------------------------------------------------------------------

class TestOKXFetcherOrderbook:

    @pytest.mark.asyncio
    async def test_fetch_orderbook_parses_books_format(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={
            "code": "0",
            "data": [{
                "bids": [["150.0", "10.0", "0", "1"]],
                "asks": [["150.5", "5.0", "0", "1"]],
            }],
        })
        ob = await fetcher.fetch_orderbook("SOL-USDT", count=20)
        assert ob is not None
        assert ob.bids[0] == [150.0, 10.0]
        assert ob.asks[0] == [150.5, 5.0]

    @pytest.mark.asyncio
    async def test_fetch_orderbook_empty_data_returns_none(self) -> None:
        fetcher = _make_okx(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={"code": "0", "data": []})
        ob = await fetcher.fetch_orderbook("SOL-USDT", count=20)
        assert ob is None


# ---------------------------------------------------------------------------
# BitgetFetcher.fetch_candles  (oldest-first — API returns ascending timestamps)
# ---------------------------------------------------------------------------

class TestBitgetFetcherCandles:

    @pytest.mark.asyncio
    async def test_fetch_candles_oldest_first(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        # Bitget returns oldest-first (ascending timestamps)
        fetcher._get_json = AsyncMock(return_value={
            "code": "00000",
            "data": [
                ["1000000", "100.0", "101.0", "99.0", "100.5", "100.0", "10000"],
                ["2000000", "105.0", "106.0", "104.0", "105.5", "200.0", "21000"],
            ],
        })
        candles = await fetcher.fetch_candles("SOL-USDT", limit=2)
        assert len(candles) == 2
        # No reversal: oldest remains first, newest last
        assert candles[0].close == 100.5   # oldest (ts=1000s)
        assert candles[1].close == 105.5   # newest (ts=2000s)

    @pytest.mark.asyncio
    async def test_fetch_candles_empty_data_returns_empty(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={"code": "00000", "data": []})
        candles = await fetcher.fetch_candles("SOL-USDT", limit=5)
        assert candles == []


# ---------------------------------------------------------------------------
# BitgetFetcher.fetch_orderbook
# ---------------------------------------------------------------------------

class TestBitgetFetcherOrderbook:

    @pytest.mark.asyncio
    async def test_fetch_orderbook_parses_format(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={
            "code": "00000",
            "data": {
                "bids": [["150.0", "10.0"]],
                "asks": [["150.5", "5.0"]],
            },
        })
        ob = await fetcher.fetch_orderbook("SOL-USDT", count=20)
        assert ob is not None
        assert ob.bids[0] == [150.0, 10.0]
        assert ob.asks[0] == [150.5, 5.0]

    @pytest.mark.asyncio
    async def test_fetch_orderbook_no_data_returns_none(self) -> None:
        fetcher = _make_bitget(quote_assets=["USDT"])
        fetcher._get_json = AsyncMock(return_value={"code": "00000", "data": None})
        ob = await fetcher.fetch_orderbook("SOL-USDT", count=20)
        assert ob is None


# ---------------------------------------------------------------------------
# MarketDataConfig / RateLimitConfig parsing
# ---------------------------------------------------------------------------

class TestMarketDataConfig:

    def test_defaults(self) -> None:
        from multi_coin_grid_pro.signals.momentum_config import MarketDataConfig
        cfg = MarketDataConfig()
        assert cfg.mode == "sample"
        assert cfg.max_enriched_pairs_per_exchange == 25
        assert cfg.rate_limits.max_requests_per_minute_per_exchange == 60
        assert cfg.rate_limits.min_seconds_between_orderbook_calls == 2.0

    def test_from_dict_custom_values(self) -> None:
        import yaml

        from multi_coin_grid_pro.signals.momentum_config import ServiceConfig
        raw_yaml = """
mode: signal_only
scan_interval_seconds: 60
top_n: 5
exchanges:
  - exchange: okx
    api_url: https://www.okx.com
    quote_assets: [USDT]
market_data:
  mode: full
  max_enriched_pairs_per_exchange: 50
  rate_limits:
    max_requests_per_minute_per_exchange: 30
    min_seconds_between_orderbook_calls: 5.0
"""
        d = yaml.safe_load(raw_yaml)
        cfg = ServiceConfig._from_dict(d)
        assert cfg.market_data.mode == "full"
        assert cfg.market_data.max_enriched_pairs_per_exchange == 50
        assert cfg.market_data.rate_limits.max_requests_per_minute_per_exchange == 30
        assert cfg.market_data.rate_limits.min_seconds_between_orderbook_calls == 5.0

    def test_from_dict_without_market_data_uses_defaults(self) -> None:
        import yaml

        from multi_coin_grid_pro.signals.momentum_config import ServiceConfig
        raw_yaml = """
mode: signal_only
scan_interval_seconds: 60
top_n: 5
exchanges:
  - exchange: okx
    api_url: https://www.okx.com
    quote_assets: [USDT]
"""
        d = yaml.safe_load(raw_yaml)
        cfg = ServiceConfig._from_dict(d)
        assert cfg.market_data.mode == "sample"
        assert cfg.market_data.max_enriched_pairs_per_exchange == 25


# ---------------------------------------------------------------------------
# MarketDataFetcher.enrich_all — sample mode + spread ordering
# ---------------------------------------------------------------------------

class _FakeExchangeConfig2:
    def __init__(self, exchange, api_url, quote_assets):
        self.exchange = exchange
        self.api_url = api_url
        self.quote_assets = quote_assets
        self.grid_db_path = None
        self.blacklist_yaml = None
        self.min_volume_usd_24h = 0.0
        self.max_spread_pct = 10.0
        self.min_price = 0.0
        self.candidate_timeout_seconds = 10.0


def _make_enriched_candidate(exchange, pair, spread_pct) -> EnrichedCandidate:
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=pair,
        price=100.0,
        bid=99.0,
        ask=101.0,
        spread_pct=spread_pct,
    )


class TestMarketDataFetcherEnrichAll:

    @pytest.mark.asyncio
    async def test_sample_mode_respects_max_pairs(self) -> None:
        """With max_enriched=2, only 2 candidates get candle data per exchange."""
        from multi_coin_grid_pro.signals.momentum_config import MarketDataConfig, RateLimitConfig
        from multi_coin_grid_pro.signals.momentum_models import CandleSnapshot
        cfg = MarketDataConfig(
            mode="sample",
            max_enriched_pairs_per_exchange=2,
            rate_limits=RateLimitConfig(min_seconds_between_orderbook_calls=0.0),
        )

        # 5 candidates for okx with increasing spread (C0 most liquid)
        candidates = [
            _make_enriched_candidate("okx", f"C{i}-USDT", spread_pct=float(i))
            for i in range(5)
        ]

        mdf = MarketDataFetcher(session=_mock_session())
        okx_fetcher = _make_okx()
        # fetch_candles returns 1 dummy candle so apply_candle_metrics triggers
        # timestamp must be within 120s of now=9999.0 to pass staleness check
        dummy_candle = CandleSnapshot(timestamp=9939.0, open=100.0, high=100.0, low=100.0, close=100.0, volume=10.0)
        okx_fetcher.fetch_candles = AsyncMock(return_value=[dummy_candle])
        okx_fetcher.fetch_orderbook = AsyncMock(return_value=None)
        mdf._fetchers["okx"] = okx_fetcher

        exc_cfgs = [_FakeExchangeConfig2("okx", "https://www.okx.com", ["USDT"])]
        await mdf.enrich_all(candidates, cfg, exc_cfgs, now=9999.0)

        # Only 2 (most liquid) should have candles_fetched_at set
        enriched = [c for c in candidates if c.candles_fetched_at != 0.0]
        assert len(enriched) == 2

    @pytest.mark.asyncio
    async def test_sample_mode_picks_most_liquid_first(self) -> None:
        """Most liquid = smallest spread should be enriched first."""
        from multi_coin_grid_pro.signals.momentum_config import MarketDataConfig, RateLimitConfig
        from multi_coin_grid_pro.signals.momentum_models import CandleSnapshot
        cfg = MarketDataConfig(
            mode="sample",
            max_enriched_pairs_per_exchange=2,
            rate_limits=RateLimitConfig(min_seconds_between_orderbook_calls=0.0),
        )

        candidates = [
            _make_enriched_candidate("okx", "C3-USDT", spread_pct=3.0),
            _make_enriched_candidate("okx", "C1-USDT", spread_pct=1.0),
            _make_enriched_candidate("okx", "C5-USDT", spread_pct=5.0),
        ]

        mdf = MarketDataFetcher(session=_mock_session())
        okx_fetcher = _make_okx()
        # timestamp must be within 120s of now=9999.0 to pass staleness check
        dummy_candle = CandleSnapshot(timestamp=9939.0, open=100.0, high=100.0, low=100.0, close=100.0, volume=10.0)
        okx_fetcher.fetch_candles = AsyncMock(return_value=[dummy_candle])
        okx_fetcher.fetch_orderbook = AsyncMock(return_value=None)
        mdf._fetchers["okx"] = okx_fetcher

        exc_cfgs = [_FakeExchangeConfig2("okx", "https://www.okx.com", ["USDT"])]
        await mdf.enrich_all(candidates, cfg, exc_cfgs, now=9999.0)

        # C1 (spread=1.0) and C3 (spread=3.0) should be enriched; C5 not
        by_pair = {c.trading_pair: c for c in candidates}
        assert by_pair["C1-USDT"].candles_fetched_at != 0.0
        assert by_pair["C3-USDT"].candles_fetched_at != 0.0
        assert by_pair["C5-USDT"].candles_fetched_at == 0.0


# ---------------------------------------------------------------------------
# BitvavoFetcher
# ---------------------------------------------------------------------------

def _make_bitvavo(quote_assets=None) -> BitvavoFetcher:
    return BitvavoFetcher(
        api_url="https://api.bitvavo.com",
        quote_assets=quote_assets or ["EUR"],
        session=_mock_session(),
        semaphore=_semaphore(),
    )


class TestBitvavoFetcherPairFilter:

    def test_eur_pair_accepted(self) -> None:
        f = _make_bitvavo(["EUR"])
        assert f._is_wanted_pair("BTC-EUR") is True

    def test_wrong_quote_rejected(self) -> None:
        f = _make_bitvavo(["EUR"])
        assert f._is_wanted_pair("BTC-USDT") is False

    def test_malformed_pair_rejected(self) -> None:
        f = _make_bitvavo(["EUR"])
        assert f._is_wanted_pair("BTCEUR") is False


class TestBitvavoParseItem:

    def _item(self, **overrides):
        base = {
            "market": "WLD-EUR",
            "last": "1.23",
            "bid": "1.22",
            "ask": "1.24",
            "open": "1.10",
            "high": "1.30",
            "low": "1.05",
            "volumeQuote": "500000",
        }
        base.update(overrides)
        return base

    def test_parse_valid_item(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item())
        assert c is not None
        assert c.trading_pair == "WLD-EUR"
        assert c.exchange == "bitvavo"
        assert abs(c.price - 1.23) < 1e-9
        assert abs(c.bid - 1.22) < 1e-9
        assert abs(c.ask - 1.24) < 1e-9
        assert abs(c.quote_volume_24h - 500_000.0) < 1.0
        assert c.price_change_24h_pct is not None
        assert abs(c.price_change_24h_pct - (1.23 - 1.10) / 1.10 * 100.0) < 0.01
        assert c.high_24h == 1.30
        assert c.low_24h == 1.05

    def test_spread_pct(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item())
        assert c is not None
        expected = (1.24 - 1.22) / 1.22 * 100.0
        assert abs(c.spread_pct - expected) < 0.001

    def test_wrong_quote_returns_none(self) -> None:
        f = _make_bitvavo(["EUR"])
        c = f._parse_item(self._item(market="BTC-USDT"))
        assert c is None

    def test_zero_bid_returns_none(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item(bid="0"))
        assert c is None

    def test_missing_open_gives_no_change_pct(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item(open="0"))
        assert c is not None
        assert c.price_change_24h_pct is None

    def test_missing_volume_gives_none_vol(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item(volumeQuote="0"))
        assert c is not None
        assert c.quote_volume_24h is None

    def test_missing_high_low_gives_none(self) -> None:
        f = _make_bitvavo()
        c = f._parse_item(self._item(high="0", low="0"))
        assert c is not None
        assert c.high_24h is None
        assert c.low_24h is None


class TestBitvavoFetchCandlesAndOrderbook:

    @pytest.mark.asyncio
    async def test_fetch_candles_parses_and_reverses(self) -> None:
        f = _make_bitvavo()
        raw = [
            [1700000120000, "2.0", "2.1", "1.9", "2.05", "1000"],
            [1700000060000, "1.9", "2.0", "1.8", "1.95", "900"],
            [1700000000000, "1.8", "1.9", "1.7", "1.85", "800"],
        ]
        f._get_json = AsyncMock(return_value=raw)
        candles = await f.fetch_candles("WLD-EUR", limit=3)
        assert len(candles) == 3
        assert candles[0].timestamp == 1700000000000 / 1000.0
        assert candles[0].close == 1.85
        assert candles[2].close == 2.05

    @pytest.mark.asyncio
    async def test_fetch_candles_empty_on_error(self) -> None:
        f = _make_bitvavo()
        f._get_json = AsyncMock(side_effect=Exception("network error"))
        candles = await f.fetch_candles("WLD-EUR")
        assert candles == []

    @pytest.mark.asyncio
    async def test_fetch_orderbook_parses_bids_asks(self) -> None:
        f = _make_bitvavo()
        raw = {
            "market": "BTC-EUR",
            "nonce": 1,
            "bids": [["66321", "0.002"], ["66300", "0.01"]],
            "asks": [["66400", "0.003"], ["66500", "0.01"]],
            "timestamp": 1700000000000,
        }
        f._get_json = AsyncMock(return_value=raw)
        ob = await f.fetch_orderbook("BTC-EUR", count=5)
        assert ob is not None
        assert len(ob.bids) == 2
        assert ob.bids[0][0] == 66321.0
        assert ob.asks[0][0] == 66400.0

    @pytest.mark.asyncio
    async def test_fetch_orderbook_none_on_error(self) -> None:
        f = _make_bitvavo()
        f._get_json = AsyncMock(side_effect=Exception("timeout"))
        ob = await f.fetch_orderbook("BTC-EUR")
        assert ob is None

    @pytest.mark.asyncio
    async def test_fetch_candidates_filters_non_eur(self) -> None:
        f = _make_bitvavo(["EUR"])
        raw = [
            {"market": "BTC-EUR", "last": "66000", "bid": "65900",
             "ask": "66100", "open": "65000", "volumeQuote": "1000000"},
            {"market": "ETH-USDT", "last": "3000", "bid": "2990",
             "ask": "3010", "open": "2900", "volumeQuote": "500000"},
        ]
        f._get_json = AsyncMock(return_value=raw)
        candidates = await f.fetch_candidates()
        assert len(candidates) == 1
        assert candidates[0].trading_pair == "BTC-EUR"

    @pytest.mark.asyncio
    async def test_fetch_candidates_empty_on_error(self) -> None:
        f = _make_bitvavo()
        f._get_json = AsyncMock(side_effect=Exception("timeout"))
        candidates = await f.fetch_candidates()
        assert candidates == []
