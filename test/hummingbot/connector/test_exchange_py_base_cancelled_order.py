"""Regression tests for ambiguous order-submission outcomes.

Cancellation and timeouts are local task outcomes. They do not prove that an
exchange rejected the order, so the client order id must remain tracked until
connector reconciliation establishes an exchange state.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType


@pytest.fixture
def mock_exchange():
    exchange = MagicMock(spec=ExchangePyBase)
    exchange._trading_rules = {
        "DOGE-USD": TradingRule(
            trading_pair="DOGE-USD",
            min_order_size=Decimal("10"),
            min_notional_size=Decimal("1"),
            min_price_increment=Decimal("0.0001"),
            min_base_amount_increment=Decimal("0.01"),
        )
    }
    exchange.quantize_order_price.return_value = Decimal("0.0998")
    exchange.quantize_order_amount.return_value = Decimal("205.30")
    exchange.get_price.return_value = Decimal("0.0998")
    exchange.supported_order_types.return_value = [OrderType.LIMIT, OrderType.MARKET]
    exchange.only_count_confirmed_order_not_found = True
    exchange.logger.return_value = MagicMock()

    tracked_order = MagicMock()
    tracked_order.client_order_id = "sell_1445866582"
    exchange._order_tracker = MagicMock()
    exchange._order_tracker.active_orders = {tracked_order.client_order_id: tracked_order}
    return exchange


async def create_order(exchange):
    await ExchangePyBase._create_order(
        exchange,
        trade_type=TradeType.SELL,
        order_id="sell_1445866582",
        trading_pair="DOGE-USD",
        amount=Decimal("205.30"),
        order_type=OrderType.LIMIT,
        price=Decimal("0.0998"),
    )


@pytest.mark.asyncio
async def test_cancelled_submission_stays_tracked_and_propagates(mock_exchange):
    mock_exchange._place_order_and_process_update = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await create_order(mock_exchange)

    mock_exchange._on_order_failure.assert_not_called()
    assert "sell_1445866582" in mock_exchange._order_tracker.active_orders


@pytest.mark.asyncio
async def test_timed_out_submission_stays_tracked_for_reconciliation(mock_exchange):
    mock_exchange._place_order_and_process_update = AsyncMock(side_effect=asyncio.TimeoutError())

    await create_order(mock_exchange)

    mock_exchange._on_order_failure.assert_not_called()
    assert "sell_1445866582" in mock_exchange._order_tracker.active_orders


@pytest.mark.asyncio
async def test_definitive_exchange_rejection_is_failed(mock_exchange):
    rejection = IOError("EOrder:Insufficient funds")
    mock_exchange._place_order_and_process_update = AsyncMock(side_effect=rejection)

    await create_order(mock_exchange)

    mock_exchange._on_order_failure.assert_called_once()
    assert mock_exchange._on_order_failure.call_args.kwargs["exception"] is rejection


@pytest.mark.asyncio
async def test_successful_order_does_not_fail(mock_exchange):
    mock_exchange._place_order_and_process_update = AsyncMock(return_value="KRAKEN-12345")

    await create_order(mock_exchange)

    mock_exchange._on_order_failure.assert_not_called()


@pytest.mark.asyncio
async def test_transient_status_failure_does_not_increment_not_found_counter(mock_exchange):
    order = MagicMock()
    order.client_order_id = "sell_1445866582"
    mock_exchange._is_order_not_found_during_status_update_error.return_value = False
    mock_exchange._order_tracker.process_order_not_found = AsyncMock()

    await ExchangePyBase._handle_update_error_for_active_order(
        mock_exchange,
        order=order,
        error=IOError("temporary REST outage"),
    )

    mock_exchange._order_tracker.process_order_not_found.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_not_found_uses_bounded_lost_order_counter(mock_exchange):
    order = MagicMock()
    order.client_order_id = "sell_1445866582"
    mock_exchange._is_order_not_found_during_status_update_error.return_value = True
    mock_exchange._order_tracker.process_order_not_found = AsyncMock()
    mock_exchange._order_tracker._order_not_found_records = {order.client_order_id: 1}
    mock_exchange._order_tracker.lost_order_count_limit = 3

    await ExchangePyBase._handle_update_error_for_active_order(
        mock_exchange,
        order=order,
        error=IOError("Unknown order"),
    )

    mock_exchange._order_tracker.process_order_not_found.assert_awaited_once_with(order.client_order_id)
