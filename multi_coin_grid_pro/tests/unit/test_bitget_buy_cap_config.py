from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
