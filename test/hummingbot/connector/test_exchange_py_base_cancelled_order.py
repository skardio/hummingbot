"""
Test that asyncio.CancelledError during order placement properly marks
the order as FAILED instead of silently losing it (ghost order fix).

Root cause: network disconnects during _place_order_and_process_update()
raise asyncio.CancelledError, which previously propagated without
triggering _on_order_failure(), leaving orders with exchange_order_id=None
tracked forever.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType


@pytest.fixture
def mock_exchange():
    """Create a minimal mock of ExchangePyBase for testing _create_order."""
    from hummingbot.connector.exchange_py_base import ExchangePyBase

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
    exchange.quantize_order_price = MagicMock(return_value=Decimal("0.0998"))
    exchange.quantize_order_amount = MagicMock(return_value=Decimal("205.30"))
    exchange.get_price = MagicMock(return_value=Decimal("0.0998"))
    exchange.supported_order_types = MagicMock(return_value=[OrderType.LIMIT, OrderType.MARKET])

    # Track order calls
    exchange.start_tracking_order = MagicMock()
    mock_order = MagicMock()
    mock_order.client_order_id = "sell_1445866582"
    exchange._order_tracker = MagicMock()
    exchange._order_tracker.active_orders = {"sell_1445866582": mock_order}

    exchange._on_order_failure = MagicMock()
    exchange._update_order_after_failure = MagicMock()

    # Use the real logger
    exchange.logger = MagicMock(return_value=MagicMock())

    return exchange


@pytest.mark.asyncio
async def test_cancelled_error_marks_order_as_failed(mock_exchange):
    """
    When _place_order_and_process_update raises asyncio.CancelledError,
    _on_order_failure MUST be called before re-raising.
    This prevents ghost orders that are tracked locally but never reach the exchange.
    """
    from hummingbot.connector.exchange_py_base import ExchangePyBase

    # Make _place_order_and_process_update raise CancelledError
    mock_exchange._place_order_and_process_update = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    # Call the real _create_order method with the mock as self
    with pytest.raises(asyncio.CancelledError):
        await ExchangePyBase._create_order(
            mock_exchange,
            trade_type=TradeType.SELL,
            order_id="sell_1445866582",
            trading_pair="DOGE-USD",
            amount=Decimal("205.30"),
            order_type=OrderType.LIMIT,
            price=Decimal("0.0998"),
        )

    # The critical assertion: _on_order_failure MUST have been called
    mock_exchange._on_order_failure.assert_called_once()
    call_kwargs = mock_exchange._on_order_failure.call_args
    assert call_kwargs[1]["order_id"] == "sell_1445866582"
    assert call_kwargs[1]["trading_pair"] == "DOGE-USD"
    assert call_kwargs[1]["trade_type"] == TradeType.SELL


@pytest.mark.asyncio
async def test_cancelled_error_still_propagates(mock_exchange):
    """
    CancelledError must still be re-raised after marking the order as failed,
    so asyncio task cancellation semantics are preserved.
    """
    from hummingbot.connector.exchange_py_base import ExchangePyBase

    mock_exchange._place_order_and_process_update = AsyncMock(
        side_effect=asyncio.CancelledError()
    )

    with pytest.raises(asyncio.CancelledError):
        await ExchangePyBase._create_order(
            mock_exchange,
            trade_type=TradeType.SELL,
            order_id="sell_1445866582",
            trading_pair="DOGE-USD",
            amount=Decimal("205.30"),
            order_type=OrderType.LIMIT,
            price=Decimal("0.0998"),
        )

    # Verify CancelledError was indeed raised (pytest.raises above ensures this)
    # AND _on_order_failure was called (order not silently lost)
    assert mock_exchange._on_order_failure.called


@pytest.mark.asyncio
async def test_regular_exception_still_handled(mock_exchange):
    """
    Regular exceptions (IOError, etc.) still go through _on_order_failure
    as before — regression test.
    """
    from hummingbot.connector.exchange_py_base import ExchangePyBase

    mock_exchange._place_order_and_process_update = AsyncMock(
        side_effect=IOError("EOrder:Insufficient funds")
    )

    # Should NOT raise (exception is caught)
    await ExchangePyBase._create_order(
        mock_exchange,
        trade_type=TradeType.SELL,
        order_id="sell_1445866582",
        trading_pair="DOGE-USD",
        amount=Decimal("205.30"),
        order_type=OrderType.LIMIT,
        price=Decimal("0.0998"),
    )

    mock_exchange._on_order_failure.assert_called_once()
    call_kwargs = mock_exchange._on_order_failure.call_args
    assert call_kwargs[1]["order_id"] == "sell_1445866582"
    assert isinstance(call_kwargs[1]["exception"], IOError)


@pytest.mark.asyncio
async def test_successful_order_no_failure_called(mock_exchange):
    """Successful order placement does NOT trigger _on_order_failure."""
    from hummingbot.connector.exchange_py_base import ExchangePyBase

    mock_exchange._place_order_and_process_update = AsyncMock(return_value="KRAKEN-12345")

    await ExchangePyBase._create_order(
        mock_exchange,
        trade_type=TradeType.BUY,
        order_id="sell_1445866582",
        trading_pair="DOGE-USD",
        amount=Decimal("205.30"),
        order_type=OrderType.LIMIT,
        price=Decimal("0.0998"),
    )

    mock_exchange._on_order_failure.assert_not_called()
