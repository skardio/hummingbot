"""
Regression tests for the ICNT SELL-loop incident (Bitget, 2026-11-08).

The ICNT order book froze at bid 0.3178 for ~3.5h while the market traded at
0.33-0.39. PRO EXIT priced its close from the frozen book, the Story B1
aggressive close kept placing LIMIT SELL 34.79 @ 0.3168, Bitget rejected each
with 41117 ("selling price cannot be lower than X") and the executor retried
every tick (~9,900 rejections) until the coins were sold manually.

All tests are offline: connectors and strategy are mocks; no orders are sent.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType

NOW = 1_794_135_000.0
PAIR = "ICNT-USDT"
STALE_BID = Decimal("0.3178")
FRESH_BID = Decimal("0.3700")
FRESH_ASK = Decimal("0.3710")
INVENTORY = Decimal("34.79517")
RULE = TradingRule(
    trading_pair=PAIR,
    min_order_size=Decimal("0.01"),
    min_notional_size=Decimal("1"),
    min_price_increment=Decimal("0.0001"),
    min_base_amount_increment=Decimal("0.01"),
)


def _err_41117(min_price: str) -> str:
    return (
        f"MarketOrderFailureEvent(error_message='Error executing request POST place-order. "
        f'HTTP status is 400. Error: {{"code":"41117","msg":"ICNT/USDT selling price cannot be lower than '
        f"{min_price}\"}}')"
    )


def _book(age_s: float):
    book = MagicMock()
    uid = int((NOW - age_s) * 1000)
    book.snapshot_uid = uid
    book.last_diff_uid = uid
    return book


def _snapshot(bid=FRESH_BID, ask=FRESH_ASK, age_s=1.0):
    snap = MagicMock()
    snap.bids = [OrderBookRow(float(bid), 100.0, 1)]
    snap.asks = [OrderBookRow(float(ask), 100.0, 1)]
    snap.timestamp = NOW - age_s
    return snap


def _make(connector_name="bitget", book_age_s=3.5 * 3600):
    connector = MagicMock()
    connector.name = connector_name
    connector.get_available_balance = Mock(return_value=INVENTORY)
    connector.get_balance = Mock(return_value=INVENTORY)
    connector.get_price_by_type = Mock(return_value=STALE_BID)
    connector.get_order_book = Mock(return_value=_book(book_age_s))
    connector.quantize_order_amount = Mock(side_effect=lambda p, a: a)
    connector.quantize_order_price = Mock(
        side_effect=lambda p, pr: (pr / RULE.min_price_increment).to_integral_value(rounding="ROUND_DOWN")
        * RULE.min_price_increment
    )
    connector.supported_order_types = Mock(return_value=[OrderType.LIMIT, OrderType.MARKET])
    connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(return_value=_snapshot())
    connector.get_last_traded_prices = AsyncMock(return_value={PAIR: 0.365})
    connector.in_flight_orders = {}
    connector.trading_rules = {PAIR: RULE}

    strategy = MagicMock()
    strategy.current_timestamp = NOW
    strategy.connectors = {connector_name: connector}
    strategy.sell = Mock(side_effect=lambda *a, **k: f"sell-{strategy.sell.call_count}")
    strategy.buy = Mock(return_value="buy-1")

    config = GridExecutorConfig(
        id=f"icnt_{connector_name}",
        connector_name=connector_name,
        trading_pair=PAIR,
        side=TradeType.BUY,
        total_amount_quote=Decimal("33"),
        num_levels=3,
        start_price=Decimal("0.3150"),
        end_price=Decimal("0.3200"),
        limit_price=Decimal("0.3000"),
        min_spread_between_orders=Decimal("0.001"),
        min_order_amount_quote=Decimal("10"),
        triple_barrier_config=TripleBarrierConfig(
            stop_loss=Decimal("0.05"), take_profit=Decimal("0.05"), time_limit=3600,
            time_limit_order_type=OrderType.LIMIT, stop_loss_order_type=OrderType.LIMIT,
        ),
    )
    with patch.object(GridExecutor, "get_trading_rules", return_value=RULE), \
            patch.object(GridExecutor, "get_price", return_value=STALE_BID), \
            patch.object(GridExecutor, "update_metrics"), \
            patch.object(GridExecutor, "update_position_metrics"):
        ex = GridExecutor(strategy, config)
    ex._strategy = strategy
    ex.connectors = {connector_name: connector}
    ex.position_size_base = INVENTORY
    ex.mid_price = STALE_BID
    ex._determine_close_order_amount = AsyncMock(side_effect=lambda amt: amt)
    ex.update_position_metrics = Mock()
    return ex, connector, strategy


def _aggressive(ex):
    ex._unwind_phase = "AGGRESSIVE"
    ex._unwind_close_reason = CloseType.EARLY_STOP
    ex._unwind_started_ts = NOW - 300
    ex._status = RunnableStatus.CLOSING


def _sell_calls(strategy):
    # ExecutorBase.place_order → strategy.sell(connector, pair, amount, order_type, price, position_action)
    return [c.args for c in strategy.sell.call_args_list]


def _fail(ex, order_id, msg):
    event = MagicMock()
    event.order_id = order_id
    event.__str__ = Mock(return_value=msg)
    ex.process_order_failed_event(None, MagicMock(), event)


def run(coro):
    # Private loop: asyncio.run() would reset the global loop to None and break later tests.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestFreshClosePrice:
    def test_icnt_stale_book_sells_near_fresh_bid_not_frozen_price(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        run(ex._place_aggressive_close_orders(INVENTORY))
        calls = _sell_calls(strategy)
        assert len(calls) == 1
        _, _, amount, order_type, price, _ = calls[0]
        assert order_type == OrderType.LIMIT
        assert amount == INVENTORY
        # fresh bid 0.3700 minus 0.30% guard → 0.3688; never the frozen 0.3168
        assert price == Decimal("0.3688")
        assert price > Decimal("0.3262")  # better than the original TP target

    def test_get_price_uses_fresh_quote_only_when_book_stale(self):
        ex, connector, _ = _make()
        run(ex._maybe_refresh_close_quote())
        assert ex.get_price("bitget", PAIR, PriceType.BestBid) == FRESH_BID
        assert ex.get_price("bitget", PAIR, PriceType.BestAsk) == FRESH_ASK

        fresh, fresh_conn, _ = _make(book_age_s=1.0)
        assert run(fresh._maybe_refresh_close_quote()) is True
        assert fresh.get_price("bitget", PAIR, PriceType.BestBid) == STALE_BID
        fresh_conn.order_book_tracker.data_source._order_book_snapshot.assert_not_called()

    def test_old_rest_snapshot_falls_back_to_ticker(self):
        ex, connector, strategy = _make()
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(
            return_value=_snapshot(age_s=600)
        )
        _aggressive(ex)
        run(ex._place_aggressive_close_orders(INVENTORY))
        price = _sell_calls(strategy)[0][4]
        assert price == Decimal("0.3639")  # ticker 0.365 × 0.997

    def test_no_reliable_price_places_no_blind_order(self):
        ex, connector, strategy = _make()
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(side_effect=IOError("timeout"))
        connector.get_last_traded_prices = AsyncMock(side_effect=IOError("timeout"))
        _aggressive(ex)
        ex._closing_in_progress = True
        run(ex._place_aggressive_close_orders(INVENTORY))
        strategy.sell.assert_not_called()
        assert ex._closing_in_progress is False
        assert ex.status == RunnableStatus.CLOSING  # position stays tracked/visible
        assert ex._aggressive_close_next_ts > NOW

    def test_rate_limited_refresh_is_not_hammered(self):
        ex, connector, strategy = _make()
        snap = AsyncMock(side_effect=IOError("HTTP 429 Too Many Requests"))
        connector.order_book_tracker.data_source._order_book_snapshot = snap
        connector.get_last_traded_prices = AsyncMock(side_effect=IOError("HTTP 429"))
        assert run(ex._maybe_refresh_close_quote()) is False
        strategy.current_timestamp = NOW + 1
        assert run(ex._maybe_refresh_close_quote()) is False
        assert snap.await_count == 1
        strategy.current_timestamp = NOW + 6
        run(ex._maybe_refresh_close_quote())
        assert snap.await_count == 2
        strategy.sell.assert_not_called()

    def test_41117_forces_refresh_and_clamps_to_exchange_min(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        run(ex._place_aggressive_close_orders(INVENTORY))
        first_id = "sell-1"
        _fail(ex, first_id, _err_41117("0.3493"))
        assert ex._exchange_min_sell_price == Decimal("0.3493")
        assert ex._fresh_close_quote is None
        assert ex._aggressive_close_attempts == 1
        assert ex._is_book_price_stale() is True

        # Market moved down below the band: the next price must respect the minimum.
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(
            return_value=_snapshot(bid=Decimal("0.3400"), ask=Decimal("0.3410"))
        )
        strategy.current_timestamp = NOW + 11
        run(ex._place_aggressive_close_orders(INVENTORY))
        price = _sell_calls(strategy)[-1][4]
        assert price >= Decimal("0.3493")

    def test_rejections_are_bounded_with_one_real_market_fallback(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        for i in range(30):
            strategy.current_timestamp = NOW + i * 11
            before = strategy.sell.call_count
            run(ex._place_aggressive_close_orders(INVENTORY))
            if strategy.sell.call_count > before:
                _fail(ex, f"sell-{strategy.sell.call_count}", _err_41117("0.3493"))
        calls = _sell_calls(strategy)
        assert len(calls) == 6  # max_aggressive_close_attempts default
        assert [c[3] for c in calls].count(OrderType.MARKET) == 1
        assert calls[3][3] == OrderType.MARKET  # after 3 price rejections
        assert ex._close_failure_active is True
        assert ex.status == RunnableStatus.CLOSING

    def test_backoff_blocks_immediate_retry(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        run(ex._place_aggressive_close_orders(INVENTORY))
        _fail(ex, "sell-1", _err_41117("0.3493"))
        strategy.current_timestamp = NOW + 1
        run(ex._place_aggressive_close_orders(INVENTORY))
        assert strategy.sell.call_count == 1

    def test_unknown_failure_on_aggressive_order_is_counted(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        run(ex._place_aggressive_close_orders(INVENTORY))
        _fail(ex, "sell-1", "MarketOrderFailureEvent(error_message='unknown status, request timeout')")
        assert ex._aggressive_close_attempts == 1
        _fail(ex, "not-an-aggressive-order", "MarketOrderFailureEvent(error_message='x')")
        assert ex._aggressive_close_attempts == 1

    def test_manual_sale_resolves_close_failure_without_sell(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        ex._close_failure_active = True
        connector.get_available_balance = Mock(return_value=Decimal("0.00068"))
        run(ex._place_aggressive_close_orders(INVENTORY))
        strategy.sell.assert_not_called()
        assert ex._close_failure_active is False
        assert ex.status == RunnableStatus.SHUTTING_DOWN
        assert ex._unwind_phase == "DONE"

    def test_close_failure_keeps_position_when_coins_still_present(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        ex._close_failure_active = True
        run(ex._place_aggressive_close_orders(INVENTORY))
        strategy.sell.assert_not_called()
        assert ex.status == RunnableStatus.CLOSING

    def test_partial_fill_sells_only_remaining_amount(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        remaining = Decimal("12.34")
        run(ex._place_aggressive_close_orders(remaining))
        assert _sell_calls(strategy)[0][2] == remaining

    def test_repeated_early_stop_does_not_place_duplicate_sell(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        ex._close_order_id = "sell-x"
        ex._closing_in_progress = True
        ex.early_stop(keep_position=False)
        ex.early_stop(keep_position=False)
        strategy.sell.assert_not_called()

    def test_early_stop_with_stale_book_routes_through_unwind(self):
        ex, connector, strategy = _make()
        ex._status = RunnableStatus.RUNNING
        ex.early_stop(keep_position=False)
        strategy.sell.assert_not_called()
        assert ex._unwind_phase == "GRACEFUL"

    def test_graceful_close_deferred_without_fresh_price(self):
        ex, connector, strategy = _make()
        ex._place_graceful_close_orders(INVENTORY)
        strategy.sell.assert_not_called()

    def test_no_buy_orders_while_in_close_failure(self):
        ex, connector, strategy = _make()
        _aggressive(ex)
        ex._close_failure_active = True
        ex._aggressive_close_next_ts = NOW + 100
        with patch.object(GridExecutor, "update_grid_levels"), \
                patch.object(GridExecutor, "update_metrics"), \
                patch.object(GridExecutor, "_maybe_sample_post_fill_risk"), \
                patch.object(GridExecutor, "get_open_orders_to_create", return_value=[]) as opens:
            run(ex.control_task())
        opens.assert_not_called()
        strategy.buy.assert_not_called()
        strategy.sell.assert_not_called()


@pytest.mark.parametrize("connector_name", ["kraken", "okx"])
def test_kraken_okx_pricing_unchanged(connector_name):
    ex, connector, strategy = _make(connector_name=connector_name)
    assert ex._is_book_price_stale() is False
    assert run(ex._maybe_refresh_close_quote()) is True
    assert ex.get_price(connector_name, PAIR, PriceType.BestBid) == STALE_BID
    connector.order_book_tracker.data_source._order_book_snapshot.assert_not_called()
    _aggressive(ex)
    run(ex._place_aggressive_close_orders(INVENTORY))
    # Same slippage-guarded LIMIT from the connector book as before the fix.
    assert _sell_calls(strategy)[0][3] == OrderType.LIMIT
    assert _sell_calls(strategy)[0][4] == Decimal("0.3168")


# ---------------------------------------------------------------------------
# TP close pricing from the current market (Bitget only)
# ---------------------------------------------------------------------------
ENTRY = Decimal("0.3174")
TP_TARGET = Decimal("0.3262")
BOUGHT = Decimal("34.83")


def _tp_level():
    level = MagicMock()
    level.side = TradeType.BUY
    level.price = ENTRY
    level.take_profit = TP_TARGET / ENTRY - 1
    level.active_open_order.executed_amount_base = BOUGHT
    level.active_open_order.fee_asset = "USDT"
    return level


def _tp_price(ex):
    ex._estimate_close_fee_pct = Mock(return_value=Decimal("0.001"))  # Bitget 0.1% maker
    ex.current_close_quote = ex.get_price(ex.config.connector_name, PAIR, PriceType.BestAsk)
    return ex._get_close_order_candidate(_tp_level()).price


class TestTakeProfitMarketPrice:
    def test_icnt_tp_uses_fresh_best_bid_above_target(self):
        ex, connector, _ = _make()  # book frozen at 0.3178, fresh REST bid 0.3700
        assert run(ex._maybe_refresh_close_quote()) is True
        price = _tp_price(ex)
        assert price == FRESH_BID  # marketable LIMIT at best bid, not 0.3168 and not above the ask
        assert price > TP_TARGET

    def test_tp_never_priced_from_stale_book_without_fresh_price(self):
        ex, connector, _ = _make()
        connector.get_price_by_type = Mock(return_value=Decimal("0.3400"))  # stale book above target
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(side_effect=OSError("429"))
        connector.get_last_traded_prices = AsyncMock(side_effect=OSError("429"))
        assert run(ex._maybe_refresh_close_quote()) is False
        # Legacy would rest at stale ask × 1.0001 = 0.340034; the target is not market-derived.
        assert _tp_price(ex) == pytest.approx(TP_TARGET, abs=Decimal("1e-12"))

    def test_tp_below_market_keeps_target(self):
        ex, connector, _ = _make(book_age_s=1.0)  # fresh book
        connector.get_price_by_type = Mock(
            side_effect=lambda p, t: Decimal("0.3200") if t == PriceType.BestBid else Decimal("0.3205")
        )
        assert _tp_price(ex) == pytest.approx(TP_TARGET, abs=Decimal("1e-12"))

    def test_tp_respects_learned_41117_minimum(self):
        ex, connector, _ = _make(book_age_s=1.0)
        connector.get_price_by_type = Mock(return_value=Decimal("0.3200"))
        ex._exchange_min_sell_price = Decimal("0.3493")
        assert _tp_price(ex) == Decimal("0.3496")

    @pytest.mark.parametrize("connector_name", ["kraken", "okx"])
    def test_kraken_okx_tp_pricing_unchanged(self, connector_name):
        ex, connector, _ = _make(connector_name=connector_name)
        connector.get_price_by_type = Mock(return_value=Decimal("0.3400"))
        assert _tp_price(ex) == Decimal("0.3400") * (1 + ex.config.safe_extra_spread)


def _filled(order_id, side, price, amount, fee_token, fee_amount):
    from hummingbot.core.data_type.common import PositionAction
    from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, TradeUpdate
    from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TokenAmount

    order = InFlightOrder(
        client_order_id=order_id, trading_pair=PAIR, order_type=OrderType.LIMIT, trade_type=side,
        amount=amount, creation_timestamp=NOW, price=price, exchange_order_id=f"x{order_id}",
        initial_state=OrderState.OPEN, position=PositionAction.NIL,
    )
    order.update_with_trade_update(TradeUpdate(
        trade_id=f"t{order_id}", client_order_id=order_id, exchange_order_id=f"x{order_id}", trading_pair=PAIR,
        fill_timestamp=NOW, fill_price=price, fill_base_amount=amount, fill_quote_amount=price * amount,
        fee=DeductedFromReturnsTradeFee(flat_fees=[TokenAmount(fee_token, fee_amount)]),
    ))
    return order.to_json()


def test_icnt_tp_fill_records_fees_and_net_pnl():
    """BUY 34.83 @0.3174 (fee 0.03483 ICNT, Bitget base-fee) → TP SELL 34.79 @ best bid 0.3700 (0.1% USDT fee)."""
    ex, _, _ = _make()
    ex.config.deduct_base_fees = True
    ex.close_type = CloseType.TAKE_PROFIT
    sold = Decimal("34.79")
    sell_fee = Decimal("0.012872300")  # 0.1% of 12.8723
    ex._filled_orders = [
        _filled("buy-1", TradeType.BUY, ENTRY, BOUGHT, "ICNT", Decimal("0.03483")),
        _filled("sell-1", TradeType.SELL, FRESH_BID, sold, "USDT", sell_fee),
    ]
    ex.update_realized_pnl_metrics()

    buy_cost = ENTRY * BOUGHT                                  # 11.055042 USDT paid
    proceeds = FRESH_BID * sold                                # 12.8723 USDT gross
    dust = BOUGHT - Decimal("0.03483") - sold                  # 0.00517 ICNT < min order size
    cash_pnl = proceeds - sell_fee - buy_cost                  # 1.804386 USDT real cash result
    assert ex.realized_sell_size_quote == proceeds
    assert ex.realized_sell_fees_quote == pytest.approx(sell_fee)
    assert ex.realized_buy_fees_quote == pytest.approx(Decimal("0.03483") * ENTRY)
    # Net PnL = real cash result; the cost of the unsellable dust is excluded by design.
    assert ex.realized_pnl_quote == pytest.approx(cash_pnl + dust * ENTRY, abs=Decimal("1e-6"))
    assert ex.realized_pnl_quote > Decimal("1.80")


# ---------------------------------------------------------------------------
# Trailing stop / profit exits only on reliable prices (Bitget); stop-loss always
# ---------------------------------------------------------------------------
def _trailing(connector_name="bitget", book_age_s=1.0):
    from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop

    ex, connector, strategy = _make(connector_name=connector_name, book_age_s=book_age_s)
    ex.config.triple_barrier_config.trailing_stop = TrailingStop(
        activation_price=Decimal("0.015"), trailing_delta=Decimal("0.010"))
    ex.config.timestamp = NOW - 600  # not expired (time_limit 3600 s)
    ex._fee_aware_close_allowed = Mock(return_value=True)
    return ex, connector, strategy


def _tick(ex, pnl_pct):
    ex.position_pnl_pct = Decimal(str(pnl_pct))
    return ex.control_triple_barrier()


def _feed_down(connector):
    connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(side_effect=OSError("429"))
    connector.get_last_traded_prices = AsyncMock(side_effect=OSError("429"))


class TestTrailingPriceValidation:
    def test_trailing_activates_raises_and_fires_on_fresh_prices(self, caplog):
        ex, _, _ = _trailing()
        caplog.set_level("INFO")
        assert _tick(ex, "0.010") is False and ex._trailing_stop_trigger_pct is None
        assert _tick(ex, "0.020") is False
        assert ex._trailing_stop_trigger_pct == Decimal("0.010")
        assert _tick(ex, "0.035") is False
        assert ex._trailing_stop_trigger_pct == Decimal("0.025")
        assert ex._trailing_peak_pnl_pct == Decimal("0.035")
        assert _tick(ex, "0.024") is True
        assert ex.close_type == CloseType.TRAILING_STOP
        assert "TRAILING_ACTIVATED" in caplog.text and "TRAILING_STOP_HIT" in caplog.text

    def test_stale_book_without_fallback_pauses_trailing(self):
        ex, connector, _ = _trailing(book_age_s=3.5 * 3600)
        ex._trailing_stop_trigger_pct = Decimal("0.025")
        _feed_down(connector)
        assert run(ex._maybe_refresh_close_quote()) is False
        assert _tick(ex, "0.001") is False  # would have fired on the stale price
        assert ex._trailing_stop_trigger_pct == Decimal("0.025")
        assert ex.close_type is None or ex.close_type != CloseType.TRAILING_STOP

    def test_stale_book_with_rest_fallback_evaluates_trailing(self):
        ex, _, _ = _trailing(book_age_s=3.5 * 3600)
        ex._trailing_stop_trigger_pct = Decimal("0.025")
        assert run(ex._maybe_refresh_close_quote()) is True  # fresh REST snapshot 0.37/0.371
        assert ex.get_price(ex.config.connector_name, PAIR, PriceType.MidPrice) == (FRESH_BID + FRESH_ASK) / 2
        assert _tick(ex, "0.020") is True
        assert ex.close_type == CloseType.TRAILING_STOP

    def test_stop_loss_still_fires_during_feed_outage(self):
        ex, connector, _ = _trailing(book_age_s=3.5 * 3600)
        _feed_down(connector)
        run(ex._maybe_refresh_close_quote())
        assert _tick(ex, "-0.06") is True  # stop_loss 5%
        assert ex.close_type == CloseType.STOP_LOSS

    def test_price_reliable_flag_for_controller(self):
        ex, connector, _ = _trailing(book_age_s=3.5 * 3600)
        _feed_down(connector)
        run(ex._maybe_refresh_close_quote())
        assert ex._price_reliable_for_controller() is False
        ex2, _, _ = _trailing(book_age_s=1.0)
        assert ex2._price_reliable_for_controller() is True

    @pytest.mark.parametrize("connector_name", ["kraken", "okx"])
    def test_kraken_okx_trailing_unchanged(self, connector_name):
        ex, connector, _ = _trailing(connector_name=connector_name, book_age_s=3.5 * 3600)
        _feed_down(connector)
        assert ex._price_reliable_for_controller() is True
        assert _tick(ex, "0.020") is False
        assert _tick(ex, "0.005") is True
        assert ex.close_type == CloseType.TRAILING_STOP


class TestReliableBidForController:
    """Executor publishes a fresh executable bid so the controller emergency exit is not ticker-only."""

    def test_stale_book_publishes_rest_fallback_bid(self):
        ex, _, _ = _make()
        assert run(ex._maybe_refresh_close_quote()) is True
        assert ex._reliable_bid_for_controller() == FRESH_BID

    def test_stale_book_without_fallback_publishes_nothing(self):
        ex, connector, _ = _make()
        _feed_down(connector)
        assert run(ex._maybe_refresh_close_quote()) is False
        assert ex._reliable_bid_for_controller() is None  # never the frozen 0.3178

    def test_fresh_book_publishes_book_bid(self):
        ex, connector, _ = _make(book_age_s=1.0)
        connector.get_price_by_type = Mock(return_value=Decimal("0.2761"))
        assert ex._reliable_bid_for_controller() == Decimal("0.2761")

    @pytest.mark.parametrize("connector_name", ["kraken", "okx"])
    def test_kraken_okx_publish_nothing(self, connector_name):
        ex, _, _ = _make(connector_name=connector_name)
        assert ex._reliable_bid_for_controller() is None


class TestStaleBookBlocksNewBuys:
    """New BUY levels are never evaluated on a stale Bitget book without a fresh REST quote."""

    def _sentinel_levels(self, ex):
        ex._filter_levels_by_activation_bounds = Mock(return_value=["L1"])
        ex._sort_levels_by_proximity = Mock(side_effect=lambda levels: levels)
        ex._configured_open_order_cap = Mock(return_value=None)
        ex._emit_decision_telemetry = Mock()

    def test_stale_book_without_fallback_blocks_buys(self):
        ex, connector, _ = _make()
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(side_effect=IOError("down"))
        connector.get_last_traded_prices = AsyncMock(side_effect=IOError("down"))
        self._sentinel_levels(ex)
        assert run(ex._maybe_refresh_close_quote()) is False
        assert ex.get_open_orders_to_create() == []
        ex._filter_levels_by_activation_bounds.assert_not_called()
        ex._emit_decision_telemetry.assert_called_once_with("BUY_DECISION_BLOCK", reason_code="STALE_PRICE")
        ex.get_open_orders_to_create()
        assert ex._emit_decision_telemetry.call_count == 1  # deduplicated while still stale

    def test_stale_book_with_fresh_rest_quote_evaluates_buys_on_fresh_price(self):
        ex, _, _ = _make()
        self._sentinel_levels(ex)
        assert run(ex._maybe_refresh_close_quote()) is True
        assert ex.get_price("bitget", PAIR, PriceType.MidPrice) == (FRESH_BID + FRESH_ASK) / 2
        assert ex.get_open_orders_to_create() == ["L1"]

    def test_fresh_book_is_not_blocked(self):
        ex, _, _ = _make(book_age_s=2)
        self._sentinel_levels(ex)
        assert ex.get_open_orders_to_create() == ["L1"]

    def test_buys_resume_after_price_becomes_fresh(self):
        ex, connector, _ = _make()
        snap = connector.order_book_tracker.data_source._order_book_snapshot
        connector.order_book_tracker.data_source._order_book_snapshot = AsyncMock(side_effect=IOError("down"))
        connector.get_last_traded_prices = AsyncMock(side_effect=IOError("down"))
        self._sentinel_levels(ex)
        run(ex._maybe_refresh_close_quote())
        assert ex.get_open_orders_to_create() == []
        connector.order_book_tracker.data_source._order_book_snapshot = snap
        ex._last_fresh_quote_fetch_ts = 0.0
        assert run(ex._maybe_refresh_close_quote()) is True
        assert ex.get_open_orders_to_create() == ["L1"]

    def test_kraken_okx_never_hit_stale_buy_gate(self):
        for name in ("kraken", "okx"):
            ex, _, _ = _make(connector_name=name)
            self._sentinel_levels(ex)
            assert ex.get_open_orders_to_create() == ["L1"]
