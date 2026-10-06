"""FIX-001: partial fills on cancelled orders must never be discarded.

A cancelled order can still carry an executed amount. Dropping it removes the
proceeds from realised PnL while the matching purchase remains, booking the
unsold notional as a loss.

Reference case, XDC-USD 2026-10-06: order 461474338 was placed for the full
2020.6411 XDC, filled 999.9440 (33.45 USD), then cancelled. The executor booked
-33.39 USD on a position that had in fact closed at +0.46 USD profit.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor  # noqa: E402


def make_order(client_order_id: str, trade_type: str, executed_base: str, executed_quote: str):
    """A tracked order wrapper shaped like the executor's level orders."""
    order = MagicMock()
    order.client_order_id = client_order_id
    order.executed_amount_base = Decimal(executed_base)
    order.executed_amount_quote = Decimal(executed_quote)
    order.to_json.return_value = {
        "client_order_id": client_order_id,
        "trade_type": trade_type,
        "executed_amount_base": executed_base,
        "executed_amount_quote": executed_quote,
        "cumulative_fee_paid_quote": "0",
        "order_type": "LIMIT",
    }
    tracked = MagicMock()
    tracked.order = order
    tracked.order_id = client_order_id
    return tracked


@pytest.fixture
def executor():
    """A bare executor with only what _archive_partial_fill touches."""
    instance = GridExecutor.__new__(GridExecutor)
    instance._filled_orders = []
    instance.config = MagicMock()
    instance.config.trading_pair = "XDC-USD"
    instance.logger = MagicMock(return_value=MagicMock())
    return instance


def test_cancelled_partial_sell_counted(executor):
    """The XDC mechanism: a partially filled sell that is then cancelled."""
    tracked = make_order("461474338", "SELL", "999.9440", "33.4481")
    assert executor._archive_partial_fill(tracked) is True
    assert len(executor._filled_orders) == 1
    archived = executor._filled_orders[0]
    assert archived["client_order_id"] == "461474338"
    assert archived["trade_type"] == "SELL"
    assert Decimal(archived["executed_amount_quote"]) == Decimal("33.4481")


def test_cancelled_partial_buy_counted(executor):
    """Same mechanism on the buy side."""
    tracked = make_order("729008628", "BUY", "1010.3206", "33.4416")
    assert executor._archive_partial_fill(tracked) is True
    assert executor._filled_orders[0]["trade_type"] == "BUY"


def test_zero_fill_cancel_ignored(executor):
    """A cancelled order that never executed must not be archived."""
    tracked = make_order("160918503", "SELL", "0", "0")
    assert executor._archive_partial_fill(tracked) is False
    assert executor._filled_orders == []


def test_repeated_cancel_does_not_double_count(executor):
    """Archiving the same order twice must add it once."""
    tracked = make_order("461474338", "SELL", "999.9440", "33.4481")
    assert executor._archive_partial_fill(tracked) is True
    assert executor._archive_partial_fill(tracked) is False
    assert len(executor._filled_orders) == 1


def test_order_already_in_filled_orders_is_not_duplicated(executor):
    """An order archived through the normal path is not archived again."""
    executor._filled_orders.append({
        "client_order_id": "752038520",
        "trade_type": "SELL",
        "executed_amount_base": "1020.6971",
        "executed_amount_quote": "34.0913",
    })
    tracked = make_order("752038520", "SELL", "1020.6971", "34.0913")
    assert executor._archive_partial_fill(tracked) is False
    assert len(executor._filled_orders) == 1


def test_missing_order_is_safe(executor):
    assert executor._archive_partial_fill(None) is False
    empty = MagicMock()
    empty.order = None
    assert executor._archive_partial_fill(empty) is False
    assert executor._filled_orders == []


def test_malformed_amount_is_safe(executor):
    tracked = make_order("broken", "SELL", "0", "0")
    tracked.order.executed_amount_base = "not-a-number"
    assert executor._archive_partial_fill(tracked) is False
    assert executor._filled_orders == []


def test_negative_amount_is_not_archived(executor):
    tracked = make_order("weird", "SELL", "-5", "0")
    assert executor._archive_partial_fill(tracked) is False


def test_xdc_scenario_produces_correct_realised_pnl(executor):
    """End to end on the real numbers.

    Buys 2020.6410 XDC for 67.0752. Sells 999.9440 on a cancelled order and
    1020.6971 on a completed one: 2020.6411 total for 67.5394.

    Without the fix only the completed sell is counted, giving a residual of
    999.944 XDC and a booked loss of roughly -33.4. With the fix the position
    reconciles to zero and the result is the real +0.46 profit.
    """
    buy_one = make_order("729010726", "BUY", "1010.3205", "33.6336")
    buy_two = make_order("729008628", "BUY", "1010.3205", "33.4416")
    executor._filled_orders.append(buy_one.order.to_json())
    executor._filled_orders.append(buy_two.order.to_json())

    cancelled_sell = make_order("461474338", "SELL", "999.9440", "33.4481")
    assert executor._archive_partial_fill(cancelled_sell) is True

    completed_sell = make_order("752038520", "SELL", "1020.6971", "34.0913")
    executor._filled_orders.append(completed_sell.order.to_json())

    buy_base = sum(Decimal(o["executed_amount_base"]) for o in executor._filled_orders
                   if o["trade_type"] == "BUY")
    sell_base = sum(Decimal(o["executed_amount_base"]) for o in executor._filled_orders
                    if o["trade_type"] == "SELL")
    buy_quote = sum(Decimal(o["executed_amount_quote"]) for o in executor._filled_orders
                    if o["trade_type"] == "BUY")
    sell_quote = sum(Decimal(o["executed_amount_quote"]) for o in executor._filled_orders
                     if o["trade_type"] == "SELL")

    residual = buy_base - sell_base
    assert abs(residual) < Decimal("0.001"), f"position should reconcile, residual={residual}"

    realised = sell_quote - buy_quote
    assert realised > 0, f"the real trade was profitable, got {realised}"
    assert abs(realised - Decimal("0.4642")) < Decimal("0.0001")


def test_without_archiving_the_loss_reappears(executor):
    """Control: skipping the archive reproduces the original defect."""
    for order in (
        make_order("729010726", "BUY", "1010.3205", "33.6336"),
        make_order("729008628", "BUY", "1010.3205", "33.4416"),
        make_order("752038520", "SELL", "1020.6971", "34.0913"),
    ):
        executor._filled_orders.append(order.order.to_json())

    buy_base = sum(Decimal(o["executed_amount_base"]) for o in executor._filled_orders
                   if o["trade_type"] == "BUY")
    sell_base = sum(Decimal(o["executed_amount_base"]) for o in executor._filled_orders
                    if o["trade_type"] == "SELL")
    residual = buy_base - sell_base
    assert residual > Decimal("999"), "the defect leaves ~999.944 XDC unaccounted for"
