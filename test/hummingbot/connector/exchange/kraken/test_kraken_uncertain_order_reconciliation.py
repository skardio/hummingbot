from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from hummingbot.connector.exchange.kraken import kraken_constants as CONSTANTS
from hummingbot.connector.exchange.kraken.kraken_exchange import KrakenExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState


@pytest.fixture
def exchange():
    instance = KrakenExchange(
        kraken_api_key="testKey",
        kraken_secret_key="c2VjcmV0",
        trading_pairs=["BTC-USD"],
    )
    instance._set_current_timestamp(1700000000)
    return instance


def pending_order(side=TradeType.BUY):
    return InFlightOrder(
        client_order_id="12345",
        trading_pair="BTC-USD",
        order_type=OrderType.LIMIT_MAKER,
        trade_type=side,
        amount=Decimal("0.1"),
        price=Decimal("30000"),
        creation_timestamp=1700000000,
    )


@pytest.mark.asyncio
async def test_recovers_accepted_open_order_by_userref(exchange):
    order = pending_order()
    exchange.get_open_orders_with_userref = AsyncMock(return_value={
        "open": {"KRAKEN-TXID": {"status": "open", "vol_exec": "0"}}
    })
    exchange.get_closed_orders_with_userref = AsyncMock()

    update = await exchange._request_order_status(order)

    assert update.exchange_order_id == "KRAKEN-TXID"
    assert update.new_state is OrderState.OPEN
    exchange.get_closed_orders_with_userref.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovers_fast_closed_sell_after_restart(exchange):
    order = pending_order(side=TradeType.SELL)
    exchange.get_open_orders_with_userref = AsyncMock(return_value={"open": {}})
    exchange.get_closed_orders_with_userref = AsyncMock(return_value={
        "closed": {"KRAKEN-TXID": {"status": "closed", "vol_exec": "0.1"}}
    })

    update = await exchange._request_order_status(order)

    assert update.exchange_order_id == "KRAKEN-TXID"
    assert update.new_state is OrderState.FILLED


@pytest.mark.asyncio
@pytest.mark.parametrize("side", [TradeType.BUY, TradeType.SELL])
async def test_recovers_late_fill_and_exact_fee_before_terminal_update(exchange, side):
    order = pending_order(side=side)
    exchange.start_tracking_order(
        order_id=order.client_order_id,
        exchange_order_id=None,
        trading_pair=order.trading_pair,
        trade_type=order.trade_type,
        price=order.price,
        amount=order.amount,
        order_type=order.order_type,
    )
    tracked_order = exchange.in_flight_orders[order.client_order_id]
    exchange.get_open_orders_with_userref = AsyncMock(return_value={"open": {}})
    exchange.get_closed_orders_with_userref = AsyncMock(return_value={
        "closed": {
            "KRAKEN-TXID": {
                "status": "closed",
                "vol_exec": "0.1",
                "trades": ["TRADE-1"],
            }
        }
    })
    exchange._api_request_with_retry = AsyncMock(return_value={
        "TRADE-1": {
            "ordertxid": "KRAKEN-TXID",
            "fee": "1.25",
            "vol": "0.1",
            "price": "30000",
            "time": 1700000001,
        }
    })
    exchange._order_tracker.process_trade_update = MagicMock(
        wraps=exchange._order_tracker.process_trade_update
    )

    update = await exchange._request_order_status(tracked_order)

    assert update.new_state is OrderState.FILLED
    trade_update = exchange._order_tracker.process_trade_update.call_args.args[0]
    assert trade_update.trade_id == "TRADE-1"
    assert trade_update.fee.flat_fees[0].token == "USD"
    assert trade_update.fee.flat_fees[0].amount == Decimal("1.25")


@pytest.mark.asyncio
async def test_duplicate_late_fill_uses_same_exchange_trade_id(exchange):
    order = pending_order()
    exchange._api_request_with_retry = AsyncMock(return_value={
        "TRADE-1": {
            "ordertxid": "KRAKEN-TXID",
            "fee": "1.25",
            "vol": "0.1",
            "price": "30000",
            "time": 1700000001,
        }
    })

    first = await exchange._trade_updates_for_trade_ids(order, ["TRADE-1"])
    second = await exchange._trade_updates_for_trade_ids(order, ["TRADE-1"])

    assert first[0].trade_id == second[0].trade_id == "TRADE-1"


@pytest.mark.asyncio
async def test_recovers_partial_fill_without_losing_order(exchange):
    order = pending_order()
    exchange.get_open_orders_with_userref = AsyncMock(return_value={
        "open": {"KRAKEN-TXID": {"status": "open", "vol_exec": "0.04"}}
    })

    update = await exchange._request_order_status(order)

    assert update.new_state is OrderState.PARTIALLY_FILLED


@pytest.mark.asyncio
async def test_healthy_open_and_closed_queries_confirm_not_found(exchange):
    order = pending_order()
    exchange.get_open_orders_with_userref = AsyncMock(return_value={"open": {}})
    exchange.get_closed_orders_with_userref = AsyncMock(return_value={"closed": {}})

    with pytest.raises(IOError, match=CONSTANTS.UNKNOWN_ORDER_MESSAGE):
        await exchange._request_order_status(order)


@pytest.mark.asyncio
async def test_temporary_open_orders_failure_remains_ambiguous(exchange):
    order = pending_order()
    exchange.get_open_orders_with_userref = AsyncMock(side_effect=IOError("temporary REST outage"))

    with pytest.raises(IOError, match="temporary REST outage") as error:
        await exchange._request_order_status(order)

    assert not exchange._is_order_not_found_during_status_update_error(error.value)


def test_pending_order_round_trip_is_restart_recoverable():
    order = pending_order()

    restored = InFlightOrder.from_json(order.to_json())

    assert restored.current_state is OrderState.PENDING_CREATE
    assert restored.client_order_id == order.client_order_id
    assert restored.exchange_order_id is None
