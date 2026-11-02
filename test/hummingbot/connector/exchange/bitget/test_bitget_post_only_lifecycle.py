import asyncio
from decimal import Decimal

import pytest

from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import OrderState


@pytest.fixture
def exchange():
    instance = BitgetExchange(
        bitget_api_key="testKey",
        bitget_secret_key="testSecret",
        bitget_passphrase="testPassphrase",
        trading_pairs=["BTC-USDT"],
    )
    instance._set_current_timestamp(1700000000)
    return instance


def start_post_only_order(exchange, order_id="client-1"):
    exchange.start_tracking_order(
        order_id=order_id,
        exchange_order_id="exchange-1",
        trading_pair="BTC-USDT",
        order_type=OrderType.LIMIT_MAKER,
        trade_type=TradeType.BUY,
        price=Decimal("30000"),
        amount=Decimal("0.1"),
        initial_state=OrderState.OPEN,
    )
    return exchange.in_flight_orders[order_id]


@pytest.mark.asyncio
async def test_post_only_cancel_without_fill_is_terminal_cancel_not_failure(exchange):
    order = start_post_only_order(exchange)

    exchange._process_order_event_message({
        "status": "cancelled",
        "clientOid": order.client_order_id,
        "orderId": order.exchange_order_id,
        "uTime": "1700000000000",
    })
    await asyncio.sleep(0)

    cached = exchange._order_tracker.fetch_cached_order(order.client_order_id)
    assert cached.current_state is OrderState.CANCELED
    assert not cached.is_failure
    assert cached.executed_amount_base == Decimal("0")


@pytest.mark.asyncio
async def test_partial_fill_then_post_only_cancel_keeps_fee_and_inventory_once(exchange):
    order = start_post_only_order(exchange)
    trade_message = {
        "tradeId": "trade-1",
        "orderId": order.exchange_order_id,
        "side": "buy",
        "priceAvg": "30000",
        "size": "0.04",
        "amount": "1200",
        "uTime": "1700000000000",
        "feeDetail": {"totalFee": "-0.00004", "feeCoin": "BTC"},
    }
    trade_update = exchange._parse_trade_update(trade_message, order, "websocket")

    exchange._order_tracker.process_trade_update(trade_update)
    exchange._order_tracker.process_trade_update(trade_update)  # REST/WS duplicate
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert order.executed_amount_base == Decimal("0.04")
    assert len(order.order_fills) == 1
    assert order.cumulative_fee_paid("BTC") == Decimal("0.00004")

    exchange._process_order_event_message({
        "status": "cancelled",
        "clientOid": order.client_order_id,
        "orderId": order.exchange_order_id,
        "uTime": "1700000001000",
    })
    await asyncio.sleep(0)

    cached = exchange._order_tracker.fetch_cached_order(order.client_order_id)
    assert cached.current_state is OrderState.CANCELED
    assert cached.executed_amount_base == Decimal("0.04")
    assert len(cached.order_fills) == 1


def test_fill_fee_currency_is_taken_from_exchange_payload(exchange):
    order = start_post_only_order(exchange)
    trade_update = exchange._parse_trade_update({
        "tradeId": "trade-quote-fee",
        "orderId": order.exchange_order_id,
        "side": "buy",
        "priceAvg": "30000",
        "size": "0.01",
        "amount": "300",
        "uTime": "1700000000000",
        "feeDetail": {"totalFee": "-0.30", "feeCoin": "USDT"},
    }, order, "rest")

    assert trade_update.fee.flat_fees[0].token == "USDT"
    assert trade_update.fee.flat_fees[0].amount == Decimal("0.30")
