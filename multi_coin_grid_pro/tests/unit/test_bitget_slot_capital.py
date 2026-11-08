"""
Regression tests for the phantom Bitget portfolio value (2026-11-08).

The bot reported quote=442.77 + coins=237.81 = 680.58 USDT; the 237.81 came from
historical positions_held (orphan fills / stale Position rows) and inflated the
dynamic slot count. Bitget now sizes slots on working capital (quote balance +
active executors). Historical positions stay in memory/DB for analysis only.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import yaml

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.execution.dynamic_slot_manager import DynamicSlotManager

YAML = Path(__file__).resolve().parents[2] / "spot_bitget" / "config" / "spot_grid_bitget.yaml"
QUOTE = Decimal("442.77")


def _position(amount, price):
    return SimpleNamespace(amount=Decimal(amount), breakeven_price=Decimal(price), unrealized_pnl_quote=Decimal("0"))


# Phantom history worth 237.81 USDT (ETH/SOL/BTC rows without a live executor).
PHANTOM = [_position("0.0363", "3500"), _position("0.7", "150"), _position("0.0000576", "100000")]


def _executor(active, size, pnl="0", fees="0"):
    ei = MagicMock()
    ei.is_active = active
    ei.custom_info = {"position_size_quote": Decimal(size), "position_pnl_quote": Decimal(pnl),
                      "position_fees_quote": Decimal(fees)}
    return ei


def _ctrl(connector_name="bitget", quote=QUOTE, executors=(), positions=(), regime="BULL"):
    ctrl = MagicMock(spec=MultiCoinGridController)
    ctrl.config = SimpleNamespace(connector_name=connector_name)
    ctrl._balance_currency = "USDT"
    ctrl.connector = MagicMock()
    ctrl.connector.get_balance = Mock(return_value=quote)
    ctrl.executors_info = list(executors)
    ctrl.positions_held = list(positions)
    ctrl.max_simultaneous_coins = 3
    with open(YAML) as fh:
        cfg = yaml.safe_load(fh)["dynamic_slots"]
    ctrl.dynamic_slot_manager = DynamicSlotManager(config=cfg, logger=MagicMock())
    ctrl.market_regime_filter = MagicMock()
    ctrl.market_regime_filter.get_market_regime_state = Mock(return_value=SimpleNamespace(regime=regime))
    for name in ("_calculate_portfolio_value", "_calculate_drawdown_portfolio", "_get_current_max_slots"):
        setattr(ctrl, name, getattr(MultiCoinGridController, name).__get__(ctrl))
    return ctrl


def test_phantom_fixture_matches_incident_value():
    assert sum(p.amount * p.breakeven_price for p in PHANTOM) == Decimal("237.81")
    assert _ctrl(positions=PHANTOM)._calculate_portfolio_value() == Decimal("680.58")


@pytest.mark.parametrize("regime,expected", [("BEAR", 1), ("CHOP", 3), ("BULL", 6)])
def test_bitget_slots_ignore_historical_positions(regime, expected):
    with_history = _ctrl(positions=PHANTOM, regime=regime)
    clean = _ctrl(regime=regime)
    assert with_history._get_current_max_slots() == expected
    assert clean._get_current_max_slots() == expected


def test_legacy_connectors_keep_portfolio_basis():
    # Kraken/OKX unchanged: positions_held still counted (BULL 680.58 -> 7 slots).
    assert _ctrl(connector_name="kraken", positions=PHANTOM)._get_current_max_slots() == 7
    assert _ctrl(connector_name="okx", positions=PHANTOM)._get_current_max_slots() == 7


def test_no_active_executor_no_coin_value():
    ctrl = _ctrl(positions=PHANTOM, executors=[_executor(False, "11.04")])
    assert ctrl._calculate_drawdown_portfolio() == QUOTE


def test_one_active_executor_valued_mark_to_market():
    ctrl = _ctrl(quote=Decimal("421.75"), executors=[_executor(True, "20", "1", "0.02")])
    assert ctrl._calculate_drawdown_portfolio() == Decimal("442.77")


def test_duplicate_history_of_active_pair_is_not_double_counted():
    dup = [_position("60", "0.35"), _position("60", "0.35")]
    ctrl = _ctrl(quote=Decimal("421.75"), executors=[_executor(True, "21")], positions=dup)
    assert ctrl._calculate_drawdown_portfolio() == Decimal("442.75")


def test_restart_with_historical_db_creates_no_extra_slot_capital():
    # After restart: only terminated executors + Position rows loaded from the DB.
    ctrl = _ctrl(positions=PHANTOM, executors=[_executor(False, "11.04"), _executor(False, "11.07")])
    assert ctrl._calculate_drawdown_portfolio() == QUOTE
    assert ctrl._get_current_max_slots() == 6
    assert len(ctrl.positions_held) == 3  # kept for analysis/reconciliation, not deleted


def test_regime_route_log_shows_basis():
    ctrl = _ctrl(positions=PHANTOM)
    logger = MagicMock()
    ctrl.logger = Mock(return_value=logger)
    ctrl._get_current_max_slots()
    msg = logger.info.call_args_list[-1].args[0]
    assert "balance=442.77" in msg and "basis=working_capital" in msg
