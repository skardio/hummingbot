"""Synthetic Bitget ticker-to-risk pipeline; no exchange or operational files."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.core.risk_buckets import CoinBucket, RiskBucketExposureTracker
from multi_coin_grid_pro.utils.dynamic_pair_manager import DynamicPairManager, PairMetrics, normalize_bitget_pair


class FakeResponse:
    status = 200

    def __init__(self, tickers):
        self.tickers = tickers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self):
        return {"code": "00000", "data": self.tickers}


class FakeSession:
    def __init__(self, tickers):
        self.tickers = tickers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def get(self, *_args, **_kwargs):
        return FakeResponse(self.tickers)


def ticker(symbol, volume=60_000_000, bid=1.0, ask=1.001):
    return {"symbol": symbol, "quoteVolume": str(volume), "lastPr": "1", "bidPr": str(bid), "askPr": str(ask)}


def bare_controller(exchange="bitget", quote="USDT"):
    controller = MultiCoinGridController.__new__(MultiCoinGridController)
    controller.config = SimpleNamespace(
        connector_name=exchange, quote_asset=quote,
        risk_reference_balance=Decimal("164.05"),
        max_exposure_per_coin_pct=Decimal("0.5"),
        max_total_exposure_pct=Decimal("0.7"),
        max_coins_to_monitor=5,
    )
    controller.connector = SimpleNamespace(trading_pair_symbol_map=AsyncMock())
    controller.logger = MagicMock(return_value=MagicMock())
    controller.all_available_pairs = []
    controller.monitored_coins = []
    controller.active_coins = {}
    controller.pair_volumes = {}
    controller.pair_spreads = {}
    controller.current_exposure_per_coin = {}
    controller.total_exposure = Decimal("0")
    controller.bucket_tracker = RiskBucketExposureTracker(164.05)
    controller._update_monitored_coins_from_pool = AsyncMock()
    return controller


@pytest.mark.asyncio
async def test_bitget_raw_ticker_reaches_refresh_and_risk_bucket():
    controller = bare_controller()
    pair_map = {"ARIAUSDT": "ARIA-USDT", "BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}
    controller._api_call_with_error_handling = AsyncMock(return_value=pair_map)
    raw = [ticker("ARIAUSDT"), ticker("BTCUSDT", 80_000_000), ticker("ETHUSDT", 90_000_000)]
    with patch("aiohttp.ClientSession", return_value=FakeSession(raw)):
        tickers = await controller._get_bitget_ticker_data()
    assert set(tickers) == {"ARIA-USDT", "BTC-USDT", "ETH-USDT"}
    assert normalize_bitget_pair("BTCUSDC") == "BTC-USDC"
    assert normalize_bitget_pair("DOGEBTC") == "DOGE-BTC"

    # Startup discovery and periodic refresh use this same extractor.
    startup_volumes, startup_spreads = controller._ticker_pair_metrics(pair_map, tickers, pair_map.values())
    controller.pair_volumes = startup_volumes
    controller.pair_spreads = startup_spreads
    controller._get_ticker_data_safe = AsyncMock(return_value=tickers)
    await controller._refresh_coin_pool()
    assert controller.pair_volumes == startup_volumes
    assert controller.pair_spreads == startup_spreads
    assert len(controller.pair_volumes) == 3
    assert controller.pair_volumes["ARIA-USDT"] == 60_000_000
    assert controller.pair_spreads["ARIA-USDT"] == pytest.approx(0.001 / 1.001)
    allowed, binding = controller._limit_slot_to_risk_budget("ARIA-USDT", Decimal("155.85"))
    assert allowed > 0 and binding == "risk_bucket"
    assert controller.bucket_tracker._classifier.classify("ARIA-USDT", None).bucket is CoinBucket.BLOCKED


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ticker", [
    {"quoteVolume": float("nan"), "a": ["1.001"], "b": ["1"]},
    {"quoteVolume": -1, "a": ["1.001"], "b": ["1"]},
    {"quoteVolume": 60_000_000, "a": ["0.9"], "b": ["1"]},
    {"quoteVolume": 60_000_000, "a": ["1.001"]},
    None,
])
async def test_missing_or_invalid_metrics_remain_blocked(bad_ticker):
    controller = bare_controller()
    pair_map = {"ARIAUSDT": "ARIA-USDT"}
    controller._api_call_with_error_handling = AsyncMock(return_value=pair_map)
    controller.pair_volumes = {"ARIA-USDT": 60_000_000}
    controller.pair_spreads = {"ARIA-USDT": 0.001}
    controller._get_ticker_data_safe = AsyncMock(return_value={"ARIA-USDT": bad_ticker} if bad_ticker else {})
    await controller._refresh_coin_pool()
    assert controller.pair_volumes == controller.pair_spreads == {}
    assert controller._limit_slot_to_risk_budget("ARIA-USDT", Decimal("155.85")) == (Decimal("0"), "risk_bucket")


def test_kraken_exchange_symbol_lookup_is_unchanged():
    controller = bare_controller("kraken", "USD")
    volumes, spreads = controller._ticker_pair_metrics(
        {"XBTUSD": "BTC-USD"},
        {"XBTUSD": {"v": [0, 100], "c": ["2"], "a": ["2.01"], "b": ["2"]}},
        ["BTC-USD"],
    )
    assert volumes == {"BTC-USD": 200}
    assert spreads["BTC-USD"] == pytest.approx(0.01 / 2.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange,expected", [("kraken", "kraken"), ("okx", "okx")])
async def test_other_exchanges_keep_their_dynamic_ticker_route(exchange, expected):
    manager = DynamicPairManager(connector=SimpleNamespace(name=exchange), quote_asset="USD")
    manager._fetch_kraken_tickers = AsyncMock(return_value={"route": "kraken"})
    manager._fetch_okx_tickers = AsyncMock(return_value={"route": "okx"})
    manager._fetch_bitget_tickers = AsyncMock(return_value={"route": "bitget"})
    assert await manager._fetch_all_tickers(["BTC-USD"]) == {"route": expected}
    manager._fetch_bitget_tickers.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_bitget_scan_uses_same_internal_pair_key():
    connector = SimpleNamespace(name="bitget", trading_pair_symbol_map=AsyncMock(return_value={"ARIAUSDT": "ARIA-USDT"}))
    manager = DynamicPairManager(connector=connector, quote_asset="USDT")
    with patch("aiohttp.ClientSession", return_value=FakeSession([ticker("ARIAUSDT")])):
        assert await manager.full_scan() == 1
    assert manager.all_pairs["ARIA-USDT"].volume_24h == 60_000_000
    controller = bare_controller()
    controller.dynamic_pair_manager = manager
    with patch("aiohttp.ClientSession", return_value=FakeSession([ticker("ARIAUSDT")])):
        await controller._run_dynamic_pair_scan()
    assert controller.pair_volumes["ARIA-USDT"] == 60_000_000
    assert controller.pair_spreads["ARIA-USDT"] == pytest.approx(0.001)


@pytest.mark.asyncio
async def test_dynamic_scan_does_not_reuse_stale_metrics_after_failed_scan():
    controller = bare_controller()
    old = PairMetrics(symbol="ARIA-USDT", volume_24h=60_000_000, bid=1, ask=1.001, last_scanned=1)
    controller.dynamic_pair_manager = SimpleNamespace(
        all_pairs={"ARIA-USDT": old}, full_scan=AsyncMock(return_value=0)
    )
    await controller._run_dynamic_pair_scan()
    assert controller.pair_volumes == controller.pair_spreads == {}
