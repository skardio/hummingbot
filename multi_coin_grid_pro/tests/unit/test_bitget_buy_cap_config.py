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
