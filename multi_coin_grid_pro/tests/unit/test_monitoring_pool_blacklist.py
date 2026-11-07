"""Effective blacklist is applied consistently to every optional monitoring-pool route."""
import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController


def make_controller(connector="kraken", quote="EUR", blacklist=(), overrides=None, max_coins=3):
    config = MultiCoinGridConfig(
        connector_name=connector,
        quote_asset=quote,
        max_coins_to_monitor=max_coins,
        min_24h_volume_eur=Decimal("1000"),
        pool_membership_cooldown_seconds=0,
        blacklist=list(blacklist),
        connector_overrides=overrides or {},
    )
    connector_mock = AsyncMock()
    connector_mock.name = connector
    with patch("multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery"), \
            patch("multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator"):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=MagicMock(),
            actions_queue=MagicMock(),
            connectors={connector: connector_mock},
            update_interval=1.0,
        )
    controller.market_data_provider.time = MagicMock(return_value=1000.0)
    controller._subscribe_to_orderbook = MagicMock()
    controller._unsubscribe_from_orderbook = MagicMock()
    controller.auto_blacklisted_coins = set()
    controller.active_coins = {}
    controller.current_exposure_per_coin = {}
    return controller


def pairs(quote, *bases):
    return [f"{base}-{quote}" for base in bases]


class TestBoundedPool:
    def test_kraken_without_blacklist_is_unchanged(self):
        controller = make_controller()
        assert controller._bounded_monitored_coins(pairs("EUR", "BTC", "XRP", "ADA", "SOL")) == pairs(
            "EUR", "BTC", "XRP", "ADA")

    def test_global_blacklist_frees_slots_for_next_candidates(self):
        controller = make_controller(blacklist=pairs("EUR", "BTC"))
        assert controller._bounded_monitored_coins(pairs("EUR", "BTC", "XRP", "ADA", "SOL")) == pairs(
            "EUR", "XRP", "ADA", "SOL")

    def test_okx_connector_override_applies_only_to_okx(self):
        overrides = {"okx": {"blacklist": ["BTC-USDT"]}}
        okx = make_controller("okx", "USDT", overrides=overrides)
        kraken = make_controller("kraken", "USDT", overrides=overrides)
        candidates = pairs("USDT", "BTC", "XRP", "ADA", "SOL")
        assert okx._bounded_monitored_coins(candidates) == pairs("USDT", "XRP", "ADA", "SOL")
        assert kraken._bounded_monitored_coins(candidates) == pairs("USDT", "BTC", "XRP", "ADA")

    def test_protected_executor_exposure_and_active_coin_bypass_blacklist(self):
        controller = make_controller(blacklist=pairs("EUR", "BTC", "ETH", "DOT"))
        controller.executors_info = [SimpleNamespace(is_done=False, trading_pair="BTC-EUR")]
        controller.current_exposure_per_coin = {"ETH-EUR": Decimal("3")}
        controller.active_coins = {"DOT-EUR": "executor"}
        assert controller._bounded_monitored_coins(pairs("EUR", "XRP", "ADA")) == pairs("EUR", "BTC", "DOT", "ETH")

    def test_pool_stays_smaller_when_only_blacklisted_pairs_remain(self):
        controller = make_controller(blacklist=pairs("EUR", "BTC", "ETH"), max_coins=30)
        assert controller._bounded_monitored_coins(pairs("EUR", "BTC", "ETH", "XRP")) == ["XRP-EUR"]


class TestPoolRoutes:
    @pytest.mark.asyncio
    async def test_dynamic_scan_excludes_blacklisted_ranked_pairs(self):
        controller = make_controller("okx", "USDT", blacklist=pairs("USDT", "BTC", "ETH"))
        controller.monitored_coins = pairs("USDT", "BTC", "XRP")
        ranked = pairs("USDT", "BTC", "ETH", "XRP", "ADA", "SOL")
        controller.dynamic_pair_manager = SimpleNamespace(
            full_scan=AsyncMock(return_value=10),
            _select_best_pairs=MagicMock(return_value=ranked),
            all_pairs={},
            candidate_pairs=[],
        )
        await controller._run_dynamic_pair_scan()
        assert controller.monitored_coins == pairs("USDT", "ADA", "SOL", "XRP")  # equal scores: name order
        controller._unsubscribe_from_orderbook.assert_called_once_with("BTC-USDT")

    @pytest.mark.asyncio
    async def test_dynamic_scan_keeps_blacklisted_pair_with_exposure(self):
        controller = make_controller("okx", "USDT", blacklist=pairs("USDT", "BTC"))
        controller.monitored_coins = pairs("USDT", "BTC")
        controller.current_exposure_per_coin = {"BTC-USDT": Decimal("10")}
        controller.dynamic_pair_manager = SimpleNamespace(
            full_scan=AsyncMock(return_value=10),
            _select_best_pairs=MagicMock(return_value=pairs("USDT", "BTC", "XRP", "ADA", "SOL")),
            all_pairs={},
            candidate_pairs=[],
        )
        await controller._run_dynamic_pair_scan()
        assert controller.monitored_coins == pairs("USDT", "BTC", "ADA", "SOL")

    @pytest.mark.asyncio
    async def test_periodic_refresh_drops_blacklisted_pair_kept_by_cooldown(self):
        controller = make_controller(blacklist=pairs("EUR", "BTC"))
        controller.config.pool_membership_cooldown_seconds = 10 ** 9
        controller.monitored_coins = pairs("EUR", "BTC", "XRP")
        volumes = dict.fromkeys(pairs("EUR", "BTC", "XRP", "ADA", "SOL"), 5000.0)
        spreads = dict.fromkeys(volumes, 0.001)
        await controller._update_monitored_coins_from_pool(volumes, spreads)
        assert "BTC-EUR" not in controller.monitored_coins
        assert len(controller.monitored_coins) == 3

    @pytest.mark.asyncio
    async def test_resync_replaces_blacklisted_unprotected_pair(self):
        controller = make_controller(blacklist=pairs("EUR", "BTC"))
        controller.monitored_coins = pairs("EUR", "BTC", "XRP")
        controller._monitoring_candidates = pairs("EUR", "ADA", "SOL")
        await controller._resync_monitoring_pool()
        assert controller.monitored_coins == pairs("EUR", "XRP", "ADA", "SOL")
        controller._unsubscribe_from_orderbook.assert_called_once_with("BTC-EUR")

    @pytest.mark.asyncio
    async def test_discovery_emergency_fallback_excludes_blacklisted_pairs(self):
        controller = make_controller("bitget", "USDT", blacklist=pairs("USDT", "XRP", "SOL", "LINK"), max_coins=30)
        controller.monitored_coins = []
        controller.config.use_dynamic_pair_discovery = True
        controller.connector = MagicMock(trading_pair_symbol_map_ready=MagicMock(side_effect=RuntimeError("boom")))
        controller.trend_calculator = MagicMock(_historical_data_loaded=True)
        try:
            await controller.update_processed_data()
        except Exception:
            pass  # only the fallback assignment during discovery is under test
        assert controller.monitored_coins == pairs("USDT", "ADA", "DOT")

    @pytest.mark.asyncio
    async def test_resync_is_noop_without_blacklisted_or_unsupported_pairs(self):
        controller = make_controller()
        controller.monitored_coins = pairs("EUR", "BTC", "XRP")
        await controller._resync_monitoring_pool()
        assert controller.monitored_coins == pairs("EUR", "BTC", "XRP")
        controller._unsubscribe_from_orderbook.assert_not_called()


class TestBearLightUsesMacroBtcTrend:
    def test_macro_trend_is_available_after_btc_leaves_pool(self):
        controller = make_controller("bitget", "USDT", blacklist=["BTC-USDT"])
        btc = SimpleNamespace(trend_1440m=-2.0)
        controller.trend_calculator = SimpleNamespace(trends={"BTC-USDT": btc})
        controller.monitored_coins = ["XRP-USDT"]
        controller._cache_regime_macro_trends(remove_from_grid_trends=True)
        assert "BTC-USDT" not in controller.trend_calculator.trends
        assert controller._get_macro_trend("BTC-USDT") is btc

    def test_divergence_filter_reads_btc_via_macro_trend(self):
        source = inspect.getsource(MultiCoinGridController)
        assert "btc_trend_obj = self._get_macro_trend(btc_pair)" in source
        assert "btc_trend_obj = self.trend_calculator.trends.get(btc_pair)" not in source
