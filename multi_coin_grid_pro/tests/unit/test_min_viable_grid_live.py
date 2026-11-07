"""Minimum viable live grid (Bitget, min order 10 USDT): selection, sizing and GridExecutor agree.

Pins why a 15 USDT minimum is not a grid: the executor needs min_order x 1.05 per level, so
15 USDT yields one order at mid price, while the controller minimum (3 x min order = 30) yields
a multi-level grid. No production code is changed by these tests.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from multi_coin_grid_pro.execution.dynamic_slot_manager import MIN_VIABLE_LEVELS
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
from multi_coin_grid_pro.spot_bitget.controller import SpotGridBitgetController
from multi_coin_grid_pro.tests.unit.test_capital_adaptive_risk import bitget_config, ready

D = Decimal
MIN_ORDER = D("10")
MID = D("105")


def _executor(total_quote, open_order_cap=None):
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=MagicMock())
    type(strategy).current_timestamp = PropertyMock(return_value=1234567890)
    connector = MagicMock(spec=ExchangePyBase)
    type(connector).trading_rules = PropertyMock(return_value={"SOL-USDT": TradingRule(
        trading_pair="SOL-USDT", min_order_size=D("0.0001"), min_notional_size=D("1"),
        min_price_increment=D("0.01"), min_base_amount_increment=D("0.0001"))})
    strategy.connectors = {"bitget": connector}
    config = GridExecutorConfig(
        id="t", timestamp=1, side=TradeType.BUY, connector_name="bitget", trading_pair="SOL-USDT",
        start_price=D("100"), end_price=D("110"), limit_price=D("95"), total_amount_quote=D(total_quote),
        min_spread_between_orders=D("0.005"), min_order_amount_quote=MIN_ORDER, max_open_orders=5,
        max_executed_open_orders=open_order_cap,
        triple_barrier_config=TripleBarrierConfig(take_profit=D("0.01"), stop_loss=D("0.05")))
    with patch.object(GridExecutor, "get_price", MagicMock(return_value=MID)):
        executor = GridExecutor(strategy, config, 1.0)
        executor.mid_price = MID
        levels = executor._generate_grid_levels()
    return executor, levels


@pytest.mark.parametrize("total, expected_levels", [
    ("15", 1), ("16.41", 1), ("20", 1), ("21", 2), ("30", 2), ("31.5", 3), ("65", 6),
])
def test_executor_levels_per_slot_size(total, expected_levels):
    _, levels = _executor(total)
    assert len(levels) == expected_levels
    assert sum(level.amount_quote for level in levels) <= D(total)


@pytest.mark.parametrize("total", ["21", "30", "31.5", "65"])
def test_every_grid_level_meets_the_minimum_order_with_margin(total):
    _, levels = _executor(total)
    for level in levels:
        assert level.amount_quote >= MIN_ORDER * D("1.05") - D("0.01")


def test_fifteen_usdt_is_a_single_order_at_mid_price_not_a_grid():
    _, levels = _executor("15")
    assert len(levels) == 1
    assert levels[0].price == MID


def test_controller_minimum_produces_a_multi_level_grid_and_half_of_it_does_not():
    cfg = bitget_config()
    minimum = D(str(cfg.min_order_amount_quote)) * MIN_VIABLE_LEVELS
    assert cfg.min_order_amount_quote == MIN_ORDER and minimum == D("30")
    assert len(_executor(str(minimum))[1]) >= 2
    assert len(_executor(str(minimum / 2))[1]) == 1


def test_available_balance_below_the_minimum_is_infeasible():
    ctrl = ready(bitget_config, "USDT", D("164.05"))
    manager, grids = ctrl.dynamic_slot_manager, ctrl.config.num_grids
    low = manager.calculate_optimal_allocation(available_balance=D("15"), min_order_amount=MIN_ORDER,
                                               preferred_grids=grids, max_coins=3)
    assert low.is_feasible is False and low.num_coins == 0
    enough = manager.calculate_optimal_allocation(available_balance=D("164.05"), min_order_amount=MIN_ORDER,
                                                  preferred_grids=grids, max_coins=3)
    assert enough.is_feasible is True
    assert enough.amount_per_grid_level >= MIN_ORDER


def test_illiquid_headroom_is_rejected_at_selection_and_would_be_one_order_in_the_executor():
    ctrl = ready(bitget_config, "USDT", D("164.05"))
    ctrl.pair_volumes = {"JCT-USDT": 3_556_104}
    ctrl.pair_spreads = {"JCT-USDT": 0.00142}
    headroom, binding = ctrl._limit_slot_to_risk_budget("JCT-USDT", D("Infinity"))
    assert binding == "risk_bucket" and headroom < D("30")
    assert ctrl._risk_budget_admits_slot("JCT-USDT") is False
    assert ctrl._slot_fits_risk_budget("JCT-USDT", D("65"))[0] is False
    assert len(_executor(str(headroom))[1]) == 1


def test_buy_cap_is_passed_unchanged_and_binds_on_a_funded_grid():
    activation = datetime(2026, 11, 7, 13, 40, tzinfo=timezone.utc).timestamp()
    controller = object.__new__(SpotGridBitgetController)
    controller.config = SpotGridBitgetConfig(buy_cap_activation_timestamp_utc="2026-11-07T13:40:00+00:00")
    cap = controller._executor_open_order_cap(activation)
    assert cap == 4
    executor, levels = _executor("65", open_order_cap=cap)
    assert executor._configured_open_order_cap() == 4
    assert len(levels) > cap
