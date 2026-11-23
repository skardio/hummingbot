from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
from multi_coin_grid_pro.spot_bitget.controller import SpotGridBitgetController
from multi_coin_grid_pro.utils.dynamic_pair_manager import normalize_bitget_pair


def test_buy_cap_is_disabled_without_activation_timestamp():
    config = SpotGridBitgetConfig()
    assert config.max_executed_buy_orders_per_executor == 4
    assert not config.buy_cap_is_active(2_000_000_000)


def test_buy_cap_activates_only_at_configured_utc_time():
    config = SpotGridBitgetConfig(buy_cap_activation_timestamp_utc="2030-01-01T00:00:00Z")
    activation = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
    assert not config.buy_cap_is_active(activation - 0.001)
    assert config.buy_cap_is_active(activation)


def test_buy_cap_rejects_naive_activation_timestamp():
    with pytest.raises(ValueError, match="UTC offset"):
        SpotGridBitgetConfig(buy_cap_activation_timestamp_utc="2030-01-01T00:00:00")


def test_controller_hook_scopes_cap_to_new_bitget_usdt_after_activation():
    activation = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(buy_cap_activation_timestamp_utc="2030-01-01T00:00:00Z")
    assert controller._executor_open_order_cap(activation - 1) is None
    assert controller._executor_open_order_cap(activation) == 4

    controller.config = SpotGridBitgetConfig(
        connector_name="kraken", buy_cap_activation_timestamp_utc="2030-01-01T00:00:00Z"
    )
    assert controller._executor_open_order_cap(activation) is None


@pytest.mark.parametrize("pair,allowed", [("rSPY-USDT", False), ("BTC-USDT", True), ("rV2-USDT", True)])
def test_live_entry_and_grid_factory_block_only_v3_pairs(pair, allowed):
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(paper_trading=False)
    source = object.__new__(BitgetAPIOrderBookDataSource)
    source._v3_pairs = {"rSPY-USDT"}
    controller.connector = SimpleNamespace(order_book_tracker=SimpleNamespace(_data_source=source))
    controller.logger = MagicMock(return_value=MagicMock())
    with patch.object(MultiCoinGridController, "_check_smart_entry_filter", return_value=True) as entry, \
            patch.object(MultiCoinGridController, "_create_grid_action", return_value="action") as create:
        assert controller._check_smart_entry_filter(pair) is allowed
        assert controller._create_grid_action(pair) == ("action" if allowed else None)
        assert entry.called is allowed
        assert create.called is allowed
    if not allowed:
        controller.logger().warning.assert_called_once()


def test_unknown_order_book_source_blocks_live_entry_but_not_paper():
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(paper_trading=False)
    controller.connector = SimpleNamespace(order_book_tracker=None)
    controller.logger = MagicMock(return_value=MagicMock())
    assert not controller._entry_market_supported("BTC-USDT")
    controller.config.paper_trading = True
    assert controller._entry_market_supported("BTC-USDT")


@pytest.mark.parametrize("paper,source_kind,pair,expected", [
    (False, "bitget", "rSPY-USDT", False),
    (False, "bitget", "BTC-USDT", True),
    (False, "bitget", "NEW-USDT", False),  # unproven route is not admitted live
    (True, "bitget", "rSPY-USDT", True),
    (True, "bitget", "NEW-USDT", True),
    (False, "unknown", "rSPY-USDT", True),
])
def test_monitoring_pool_admits_only_proven_v2_routes_live(paper, source_kind, pair, expected):
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(paper_trading=paper)
    source = route_source(v3={"rSPY-USDT"}, v2={"BTC-USDT"})
    tracker = SimpleNamespace(_data_source=source) if source_kind == "bitget" else None
    controller.connector = SimpleNamespace(order_book_tracker=tracker)
    assert controller._monitoring_market_supported(pair) is expected


def route_source(v3=(), v2=(), truth=None, fail=False):
    """Real data source whose snapshot negotiation is replaced by a deterministic route oracle."""
    source = object.__new__(BitgetAPIOrderBookDataSource)
    source._v3_pairs, source._v2_pairs = set(v3), set(v2)
    source._route_probe_failures = {}
    source._snapshot_rate_limit_until = 0.0

    async def negotiate(pair):
        if fail:
            raise IOError(f"Bitget order book HTTP 429 for {pair}")
        (source._v3_pairs if pair.startswith("r") else source._v2_pairs).add(pair)
        return {}

    source._request_order_book_snapshot = AsyncMock(side_effect=negotiate)
    return source


def pool_controller(source, max_coins=3, paper=False):
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(paper_trading=paper, max_coins_to_monitor=max_coins)
    controller.connector = SimpleNamespace(order_book_tracker=SimpleNamespace(_data_source=source))
    controller.logger = MagicMock(return_value=MagicMock())
    controller.active_coins = {}
    controller.current_exposure_per_coin = {}
    return controller


TOP30_V3 = [f"rS{i}-USDT" for i in range(30)]
NORMALS = [f"N{i}-USDT" for i in range(5)]


async def build_pool(controller, candidates):
    await controller._prepare_monitoring_candidates(candidates)
    return controller._bounded_monitored_coins(candidates)


@pytest.mark.asyncio
async def test_v3_only_top30_is_classified_before_admission_and_normals_fill_pool():
    source = route_source()
    controller = pool_controller(source)
    assert await build_pool(controller, TOP30_V3 + NORMALS) == NORMALS[:3]
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list]
    assert probed == TOP30_V3 + NORMALS[:3]  # rank order, stops once the pool can be filled
    assert source._v3_pairs == set(TOP30_V3)


@pytest.mark.asyncio
async def test_known_routes_are_not_probed_again_and_higher_ranked_unknown_is_checked():
    source = route_source(v3=TOP30_V3, v2=NORMALS)
    controller = pool_controller(source)
    assert await build_pool(controller, TOP30_V3 + NORMALS) == NORMALS[:3]
    source._request_order_book_snapshot.assert_not_awaited()
    assert await build_pool(controller, ["NEW-USDT"] + NORMALS) == ["NEW-USDT"] + NORMALS[:2]
    assert [c.args[0] for c in source._request_order_book_snapshot.await_args_list] == ["NEW-USDT"]


@pytest.mark.asyncio
async def test_protected_v3_executor_and_exposure_stay_without_consuming_probes():
    source = route_source(v3={"rE-USDT", "rX-USDT"})
    controller = pool_controller(source, max_coins=3)
    controller.current_exposure_per_coin = {"rX-USDT": Decimal("5")}
    controller.executors_info = [SimpleNamespace(is_done=False, trading_pair="rE-USDT")]
    assert await build_pool(controller, ["rE-USDT", "rX-USDT"] + TOP30_V3[:2] + NORMALS) == [
        "rE-USDT", "rX-USDT", NORMALS[0]]
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list]
    assert "rE-USDT" not in probed and "rX-USDT" not in probed


@pytest.mark.asyncio
async def test_failed_or_rate_limited_probes_fail_closed_without_looping():
    source = route_source(fail=True)
    controller = pool_controller(source)
    assert await build_pool(controller, TOP30_V3 + NORMALS) == []
    assert source._request_order_book_snapshot.await_count == 3
    controller.logger().warning.assert_called_once()


@pytest.mark.asyncio
async def test_probe_budget_bounds_requests_per_pool_build():
    source = route_source()
    controller = pool_controller(source)
    with patch.object(CONSTANTS, "ORDERBOOK_ROUTE_PROBE_LIMIT", 5):
        assert await build_pool(controller, TOP30_V3 + NORMALS) == []
    assert source._request_order_book_snapshot.await_count == 5


@pytest.mark.asyncio
async def test_paper_mode_does_not_probe_and_keeps_existing_pool_behaviour():
    source = route_source()
    controller = pool_controller(source, paper=True)
    assert await build_pool(controller, TOP30_V3 + NORMALS) == TOP30_V3[:3]
    source._request_order_book_snapshot.assert_not_awaited()


def blacklisted_pool_controller(source, blacklist, max_coins=3):
    controller = pool_controller(source, max_coins=max_coins)
    controller.config = SpotGridBitgetConfig(max_coins_to_monitor=max_coins, blacklist=list(blacklist))
    return controller


@pytest.mark.asyncio
async def test_blacklisted_v2_pairs_are_not_probed_nor_fill_live_slots():
    source = route_source(v2={"BTC-USDT"})
    controller = blacklisted_pool_controller(source, ["BTC-USDT", "N0-USDT"])
    pool = await build_pool(controller, ["BTC-USDT"] + TOP30_V3[:2] + NORMALS)
    assert pool == NORMALS[1:4]  # freed slots go to the next admissible pairs
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list]
    assert "BTC-USDT" not in probed and "N0-USDT" not in probed


@pytest.mark.asyncio
async def test_blacklisted_protected_executor_and_exposure_stay_monitored():
    source = route_source(v2={"BTC-USDT", "ETH-USDT"})
    controller = blacklisted_pool_controller(source, ["BTC-USDT", "ETH-USDT"])
    controller.current_exposure_per_coin = {"ETH-USDT": Decimal("5")}
    controller.executors_info = [SimpleNamespace(is_done=False, trading_pair="BTC-USDT")]
    assert await build_pool(controller, NORMALS) == ["BTC-USDT", "ETH-USDT", NORMALS[0]]


@pytest.mark.asyncio
async def test_pool_stays_smaller_than_limit_without_enough_admissible_pairs():
    source = route_source(v2={"BTC-USDT"})
    controller = blacklisted_pool_controller(source, ["BTC-USDT"], max_coins=30)
    assert await build_pool(controller, ["BTC-USDT"] + TOP30_V3 + NORMALS[:2]) == NORMALS[:2]


@pytest.mark.asyncio
async def test_failed_probe_batch_reports_reasons():
    source = route_source(fail=True)
    controller = pool_controller(source)
    await build_pool(controller, NORMALS)
    args = controller.logger().warning.call_args.args
    assert "reasons=" in args[0] and args[-1] == {"http_429": 3}


@pytest.mark.parametrize("message, rate_limited, expected", [
    ("Bitget order book request in backoff for X-USDT", True, "shared_rate_limit_backoff"),
    ("Bitget order book request in backoff for X-USDT", False, "pair_error_backoff"),
    ("Bitget order book HTTP 429 for X-USDT", False, "http_429"),
    ("Bitget order book rate limited for X-USDT", False, "http_429"),
    ("Bitget order book request failed for X-USDT: HTTP 500, {}", False, "http_error"),
    ("Invalid Bitget order book JSON for X-USDT", False, "OSError"),
])
def test_route_probe_failure_reason_distinguishes_shared_backoff(message, rate_limited, expected):
    source = route_source()
    source._time = MagicMock(return_value=100.0)
    source._snapshot_rate_limit_until = 130.0 if rate_limited else 0.0
    assert source._route_probe_failure_reason(IOError(message)) == expected


@pytest.mark.asyncio
async def test_route_probe_failure_is_cleared_after_success():
    source = route_source()
    source._route_probe_failures["N0-USDT"] = "http_429"
    assert await source.classify_order_book_route("N0-USDT") == "v2"
    assert source.route_probe_failure_summary(["N0-USDT"]) == {}


TOP100_V3 = [f"rT{i}-USDT" for i in range(100)]


async def run_bitget_discovery_cycle(controller, ranked_pairs, tickers=None, keep_pool=False):
    """One real first-run discovery cycle: volume rank -> spread -> route probe -> bounded pool."""
    if not keep_pool:
        controller.monitored_coins = []
    controller.all_available_pairs = []
    controller.config.quote_asset = "USDT"
    controller.config.min_24h_volume_usdt = 0
    controller.config.manual_trading_pairs = None
    controller.connector.trading_pair_symbol_map_ready = lambda: True
    controller.connector.trading_pair_symbol_map = AsyncMock(
        return_value={pair.replace("-", ""): pair for pair in ranked_pairs})

    async def call(func, *args):
        return await func(*args)

    controller._api_call_with_error_handling = call
    controller._get_ticker_data_safe = AsyncMock(return_value=tickers or {
        normalize_bitget_pair(pair): {"a": ["1.001"], "b": ["1.0"]} for pair in ranked_pairs})
    controller._ticker_pair_metrics = MagicMock(return_value=(
        {pair: 10_000_000 - i for i, pair in enumerate(ranked_pairs)}, {}))
    controller.coin_discovery_refresh_interval = 0
    try:
        await controller.update_processed_data()
    except Exception:
        pass  # only the discovery prefix is under test; later stages need a full controller
    return controller.monitored_coins


@pytest.mark.asyncio
async def test_discovery_reaches_v2_pairs_behind_100_v3_candidates():
    source = route_source()
    controller = pool_controller(source)
    ranked = TOP100_V3 + NORMALS
    assert await run_bitget_discovery_cycle(controller, ranked) == []
    assert source._v3_pairs == set(TOP100_V3)  # bounded: exactly the 100-probe budget was used
    assert source._request_order_book_snapshot.await_count == CONSTANTS.ORDERBOOK_ROUTE_PROBE_LIMIT

    assert await run_bitget_discovery_cycle(controller, ranked) == NORMALS[:3]
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list[100:]]
    assert probed == NORMALS[:3]  # proven V3 pairs are neither re-probed nor occupying the window
    assert controller._monitoring_candidates == NORMALS


@pytest.mark.asyncio
async def test_discovery_respects_shared_backoff_and_resumes_afterwards():
    source = route_source(v3=TOP100_V3)
    clock = {"now": 100.0}
    source._time = lambda: clock["now"]
    source._snapshot_rate_limit_until = 130.0  # shared 429 backoff active until t=130

    async def negotiate(pair):
        source._v2_pairs.add(pair)
        return {}

    source._request_order_book_snapshot = AsyncMock(side_effect=negotiate)
    controller = pool_controller(source)
    ranked = TOP100_V3 + NORMALS
    assert await run_bitget_discovery_cycle(controller, ranked) == []  # unknown routes stay excluded
    source._request_order_book_snapshot.assert_not_awaited()  # no probe while backoff is active
    assert all(source.order_book_route(pair) is None for pair in NORMALS)

    clock["now"] = 129.9
    assert await run_bitget_discovery_cycle(controller, ranked) == []
    source._request_order_book_snapshot.assert_not_awaited()

    clock["now"] = 130.0  # backoff expired: resume at the first unproven ranked candidates
    assert await run_bitget_discovery_cycle(controller, ranked) == NORMALS[:3]
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list]
    assert probed == NORMALS[:3]


@pytest.mark.asyncio
async def test_discovery_stops_probing_once_a_probe_hits_429():
    source = route_source()
    clock = {"now": 100.0}
    source._time = lambda: clock["now"]

    async def negotiate(pair):
        if pair == "N1-USDT" and source._snapshot_rate_limit_until == 0.0:
            source._snapshot_rate_limit_until = clock["now"] + 30.0
            raise IOError(f"Bitget order book HTTP 429 for {pair}")
        source._v2_pairs.add(pair)
        return {}

    source._request_order_book_snapshot = AsyncMock(side_effect=negotiate)
    controller = pool_controller(source)
    assert await build_pool(controller, NORMALS) == ["N0-USDT", "N2-USDT"]
    assert source._request_order_book_snapshot.await_count == 3  # N1 is not retried within the backoff
    assert source.order_book_route("N1-USDT") is None and source.order_book_route("N3-USDT") is None

    clock["now"] = 130.0
    assert await build_pool(controller, NORMALS) == NORMALS[:3]
    assert [c.args[0] for c in source._request_order_book_snapshot.await_args_list[3:]] == ["N1-USDT"]


@pytest.mark.asyncio
async def test_discovery_window_keeps_blacklist_spread_and_kraken_unchanged():
    source = route_source(v3=TOP100_V3)
    controller = blacklisted_pool_controller(source, ["N0-USDT"])
    ranked = TOP100_V3 + NORMALS
    tickers = {normalize_bitget_pair(pair): {"a": ["1.001"], "b": ["1.0"]} for pair in ranked}
    tickers["N1-USDT"] = {"a": ["1.1"], "b": ["1.0"]}  # spread > 0.5%
    pool = await run_bitget_discovery_cycle(controller, ranked)
    controller._get_ticker_data_safe = AsyncMock(return_value=tickers)
    controller.monitored_coins = []
    try:
        await controller.update_processed_data()
    except Exception:
        pass
    assert pool == NORMALS[1:4]
    assert controller.monitored_coins == NORMALS[2:5]
    assert not MultiCoinGridController._monitoring_route_rejected(controller, TOP100_V3[0])


@pytest.mark.asyncio
async def test_discovery_reaches_v2_pairs_behind_100_wide_spread_unprobed_pairs():
    wide = [f"W{i}-USDT" for i in range(150)]  # route unknown, spread 1% -> never probed
    ranked = wide + NORMALS
    tickers = {normalize_bitget_pair(pair): {"a": ["1.01"], "b": ["1.0"]} for pair in wide}
    tickers.update({normalize_bitget_pair(pair): {"a": ["1.001"], "b": ["1.0"]} for pair in NORMALS})
    source = route_source()
    controller = pool_controller(source)
    assert await run_bitget_discovery_cycle(controller, ranked, tickers) == NORMALS[:3]
    assert controller._monitoring_candidates == NORMALS  # spread filter unchanged: no wide pair admitted
    probed = [c.args[0] for c in source._request_order_book_snapshot.await_args_list]
    assert probed == NORMALS[:3]


@pytest.mark.asyncio
async def test_empty_discovery_does_not_overwrite_pool_set_by_concurrent_pair_scan():
    source = route_source(v3=TOP100_V3)
    controller = pool_controller(source)
    scan_pool = ["BGB-USDT", "NEAR-USDT"]

    async def probes_while_pair_scan_runs(candidates):
        controller.monitored_coins = list(scan_pool)  # US-007 rotation lands during the await

    controller._prepare_monitoring_candidates = probes_while_pair_scan_runs
    controller._bounded_monitored_coins = MagicMock(return_value=[])
    assert await run_bitget_discovery_cycle(controller, TOP100_V3 + NORMALS) == scan_pool
    errors = [c.args[0] for c in controller.logger.return_value.error.call_args_list]
    assert "❌ No coins discovered!" not in errors
