from datetime import datetime, timezone

import pytest

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
