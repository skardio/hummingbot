"""
Regression tests: every filled grid level gets its own take-profit (NEAR-USDT 2026-11-16).

Executor XGQzQLZta2 filled 4 BUY levels, but get_close_orders_to_create() returned []
while one TP was open, so only 6.83 of ~27.33 NEAR was ever offered at TP.
TPs are now placed sequentially (max one per tick, only after the previous TP is
confirmed) and capped to inventory not reserved by other open TPs.

The tests drive the executor through control_task() and the normal order-event
handlers; a small fake exchange confirms orders via connector._order_tracker.
"""

from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from test.logger_mixin_for_test import LoggerMixinForTest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderState, TradeUpdate
from hummingbot.core.data_type.trade_fee import AddedToCostTradeFee, TokenAmount
from hummingbot.core.event.events import (
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCreatedEvent,
)
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop, TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder

PAIR = "NEAR-USDT"
CONNECTOR = "binance"


class FakeExchange:
    """Tracks orders and NEAR balances; orders become visible only once confirmed."""

    def __init__(self, strategy, connector):
        self.pending = {}
        self.confirmed = {}
        self.held = Decimal("0")
        self.extra_locked = Decimal("0")  # base locked outside this executor (temporary)
        self.stale_available = None  # simulate a delayed balance update
        self.sell_count = 0
        self.connector = connector
        connector._order_tracker = MagicMock()
        connector._order_tracker.fetch_order.side_effect = lambda client_order_id: self.confirmed.get(client_order_id)
        connector.get_available_balance = MagicMock(side_effect=lambda asset: self.available())
        connector.get_balance = MagicMock(side_effect=lambda asset: self.held)
        connector._update_balances = AsyncMock()
        strategy.sell.side_effect = self._sell
        strategy.buy.side_effect = AssertionError("no BUY expected in these tests")

    def locked(self) -> Decimal:
        return sum(
            (o.amount - o.executed_amount_base for o in self.confirmed.values()
             if o.trade_type == TradeType.SELL and o.current_state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED)),
            Decimal("0"),
        )

    def available(self) -> Decimal:
        if self.stale_available is not None:
            return self.stale_available
        return self.held - self.locked() - self.extra_locked

    def _sell(self, connector_name, trading_pair, amount, order_type, price, position_action=PositionAction.NIL):
        self.sell_count += 1
        oid = f"SELL-{self.sell_count}"
        self.pending[oid] = InFlightOrder(
            client_order_id=oid, trading_pair=trading_pair, order_type=order_type, trade_type=TradeType.SELL,
            amount=amount, price=price, creation_timestamp=0, initial_state=OrderState.PENDING_CREATE,
        )
        return oid

    def sells(self):
        return {**self.pending, **self.confirmed}


class TestGridExecutorMultiTakeProfit(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    def setUp(self):
        super().setUp()
        self.clock = [1_000_000.0]
        market_info = MagicMock()
        self.strategy = MagicMock(spec=ScriptStrategyBase)
        type(self.strategy).market_info = PropertyMock(return_value=market_info)
        type(self.strategy).current_timestamp = PropertyMock(side_effect=lambda: self.clock[0])
        self.strategy.cancel.return_value = None
        connector = MagicMock(spec=ExchangePyBase)
        type(connector).trading_rules = PropertyMock(return_value={PAIR: TradingRule(
            trading_pair=PAIR,
            min_order_size=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.01"),
            min_price_increment=Decimal("0.001"),
            min_notional_size=Decimal("1"),
        )})
        self.strategy.connectors = {CONNECTOR: connector}
        self.ex = FakeExchange(self.strategy, connector)
        self.connector = connector

        config = GridExecutorConfig(
            id="XGQzQLZta2-test", timestamp=self.clock[0], side=TradeType.BUY, connector_name=CONNECTOR,
            trading_pair=PAIR, start_price=Decimal("3.20"), end_price=Decimal("3.25"), limit_price=Decimal("3.10"),
            total_amount_quote=Decimal("100"), min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("22"), deduct_base_fees=True,
            triple_barrier_config=TripleBarrierConfig(take_profit=Decimal("0.027"), stop_loss=Decimal("0.02")),
        )
        with patch.object(GridExecutor, "get_price", return_value=Decimal("3.23")):
            self.executor = GridExecutor(self.strategy, config, update_interval=0.5)
        self.executor._status = RunnableStatus.RUNNING
        self.set_loggers([self.executor.logger()])
        self.buy_levels = sorted(self.executor.grid_levels, key=lambda lvl: lvl.price, reverse=True)[:4]
        self.assertEqual(len(self.buy_levels), 4)
        for i, level in enumerate(self.buy_levels):
            oid = f"BUY-{i + 1}"
            level.active_open_order = TrackedOrder(order_id=oid)
            order = InFlightOrder(
                client_order_id=oid, trading_pair=PAIR, order_type=OrderType.LIMIT, trade_type=TradeType.BUY,
                amount=Decimal("6.84"), price=level.price, creation_timestamp=0, initial_state=OrderState.OPEN,
            )
            self.ex.confirmed[oid] = order
            self.executor.process_order_created_event(None, None, BuyOrderCreatedEvent(
                self.clock[0], OrderType.LIMIT, PAIR, Decimal("6.84"), level.price, oid, 0))

    # ------------------------------------------------------------------ helpers
    def fill(self, oid: str, amount: Decimal, fee_base: Decimal = Decimal("0")):
        order = self.ex.confirmed[oid]
        fee = AddedToCostTradeFee(flat_fees=[TokenAmount("NEAR", fee_base)] if fee_base else [])
        order.update_with_trade_update(TradeUpdate(
            trade_id=f"T-{oid}-{order.executed_amount_base}", client_order_id=oid, exchange_order_id=f"E-{oid}",
            trading_pair=PAIR, fill_timestamp=self.clock[0], fill_price=order.price, fill_base_amount=amount,
            fill_quote_amount=amount * order.price, fee=fee,
        ))
        order.current_state = OrderState.FILLED if order.executed_amount_base >= order.amount \
            else OrderState.PARTIALLY_FILLED
        if order.trade_type == TradeType.BUY:
            self.ex.held += amount - fee_base
        else:
            self.ex.held -= amount
        self.executor.process_order_filled_event(None, None, OrderFilledEvent(
            self.clock[0], oid, PAIR, order.trade_type, OrderType.LIMIT, order.price, amount, fee))

    def confirm_sells(self):
        for oid, order in list(self.ex.pending.items()):
            order.current_state = OrderState.OPEN
            self.ex.confirmed[oid] = self.ex.pending.pop(oid)
            self.executor.process_order_created_event(None, None, SellOrderCreatedEvent(
                self.clock[0], OrderType.LIMIT, PAIR, order.amount, order.price, oid, 0))

    def confirm_cancel(self, oid: str):
        self.ex.confirmed[oid].current_state = OrderState.CANCELED
        self.executor.process_order_canceled_event(None, None, OrderCancelledEvent(self.clock[0], oid))

    def tracked_position(self) -> Decimal:
        self.executor.update_grid_levels()
        self.executor.update_position_metrics()
        return self.executor.position_size_base

    async def tick(self, seconds: float = 6.0):
        self.clock[0] += seconds
        with patch.object(GridExecutor, "get_price", return_value=Decimal("3.23")), \
                patch.object(GridExecutor, "get_open_orders_to_create", return_value=[]), \
                patch.object(GridExecutor, "_check_timeout_triggers", return_value=False), \
                patch.object(GridExecutor, "_get_fee_rates", return_value=(Decimal("0.001"), Decimal("0.001"))), \
                patch.object(GridExecutor, "_sleep", new=AsyncMock()):
            await self.executor.control_task()

    def tp_levels(self):
        self.executor.update_grid_levels()
        return self.executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]

    def offered_tp_base(self) -> Decimal:
        return sum((lvl.active_close_order.order.amount for lvl in self.tp_levels()
                    if lvl.active_close_order.order is not None), Decimal("0"))

    # ------------------------------------------------------------------ tests
    async def test_each_filled_level_gets_own_tp_while_first_tp_is_open(self):
        fee = Decimal("0.01")
        self.fill("BUY-1", Decimal("6.84"), fee)
        await self.tick()
        self.confirm_sells()
        self.assertEqual(len(self.tp_levels()), 1)

        for oid in ("BUY-2", "BUY-3", "BUY-4"):
            self.fill(oid, Decimal("6.84"), fee)
        for _ in range(3):
            await self.tick()
            self.confirm_sells()

        self.assertEqual(self.ex.sell_count, 4)
        self.assertEqual(len(self.tp_levels()), 4)
        self.assertEqual(self.offered_tp_base(), Decimal("27.32"))
        self.assertLessEqual(self.offered_tp_base(), self.ex.held)
        self.assertEqual(self.ex.available(), Decimal("0"))
        for level in self.tp_levels():
            self.assertGreater(level.active_close_order.order.price, level.price)

    async def test_partial_fills_and_repeated_ticks_do_not_duplicate_tps(self):
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("2.18"))
        for _ in range(3):
            await self.tick()
            self.confirm_sells()
        self.assertEqual(self.ex.sell_count, 1, "a partially filled BUY level must not get a TP yet")

        self.fill("BUY-2", Decimal("4.66"))
        for _ in range(5):
            await self.tick()
            self.confirm_sells()
        self.assertEqual(self.ex.sell_count, 2)
        self.assertEqual(sorted(o.amount for o in self.ex.confirmed.values() if o.trade_type == TradeType.SELL),
                         [Decimal("6.84"), Decimal("6.84")])

    async def test_waits_for_unconfirmed_tp_and_respects_balance_sync_delay(self):
        self.fill("BUY-1", Decimal("6.84"))
        self.fill("BUY-2", Decimal("6.84"))
        self.clock[0] += 10
        await self.tick(0)
        self.assertEqual(self.ex.sell_count, 1)
        await self.tick()
        await self.tick()
        self.assertEqual(self.ex.sell_count, 1, "no 2nd TP while the 1st is unconfirmed")

        self.confirm_sells()
        self.fill("BUY-3", Decimal("6.84"))
        await self.tick(1)
        self.assertEqual(self.ex.sell_count, 2, "BUY-2 is past the sync delay, BUY-3 is not")
        self.confirm_sells()
        await self.tick(1)
        self.assertEqual(self.ex.sell_count, 2, "BUY-3 still inside balance_sync_delay")
        await self.tick(6)
        self.assertEqual(self.ex.sell_count, 3)

    async def test_failed_tp_placement_is_retried_without_duplicates(self):
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("6.84"))
        await self.tick()
        self.assertEqual(self.ex.sell_count, 2)
        failed_oid = "SELL-2"
        self.ex.pending.pop(failed_oid)
        self.executor.process_order_failed_event(None, None, MarketOrderFailureEvent(
            self.clock[0], failed_oid, OrderType.LIMIT, "rejected by exchange"))
        self.assertEqual(len(self.tp_levels()), 1)

        await self.tick()
        self.confirm_sells()
        await self.tick()
        self.assertEqual(self.ex.sell_count, 3)
        self.assertEqual(len(self.tp_levels()), 2)

    async def test_additional_tp_is_capped_to_unlocked_balance(self):
        # Exchange holds less than tracked (e.g. unrecorded base fee): 2nd TP must not oversell.
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("6.84"))
        self.ex.held -= Decimal("0.05")
        await self.tick()
        self.confirm_sells()
        amounts = [self.ex.confirmed[f"SELL-{i}"].amount for i in (1, 2)]
        self.assertEqual(amounts, [Decimal("6.84"), Decimal("6.79")])
        self.assertEqual(self.ex.available(), Decimal("0"))

    async def test_tp_deferred_when_unreserved_inventory_below_minimum(self):
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("6.84"))
        self.ex.held = Decimal("6.845")  # only dust left beyond the first TP
        for _ in range(3):
            await self.tick()
        self.assertEqual(self.ex.sell_count, 1)
        self.assertEqual(self.executor.status, RunnableStatus.RUNNING)

    async def test_stop_loss_cancels_all_tps_and_sells_only_remaining_position(self):
        for oid in ("BUY-1", "BUY-2", "BUY-3"):
            self.fill(oid, Decimal("6.84"))
        for _ in range(3):
            await self.tick()
            self.confirm_sells()
        self.assertEqual(len(self.tp_levels()), 3)

        # One TP fills just before the stop-loss tick.
        self.fill("SELL-2", Decimal("6.84"))
        self.executor.close_type = CloseType.STOP_LOSS
        self.executor._status = RunnableStatus.SHUTTING_DOWN

        await self.tick()
        cancelled = {c.kwargs.get("order_id") for c in self.strategy.cancel.call_args_list}
        self.assertEqual(cancelled, {"SELL-1", "SELL-3", "BUY-4"})
        for oid in ("SELL-1", "SELL-3", "BUY-4"):
            self.ex.confirmed[oid].current_state = OrderState.CANCELED
            self.executor.process_order_canceled_event(None, None, OrderCancelledEvent(self.clock[0], oid))

        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), \
                patch("time.sleep"):
            await self.tick()
        close_order = self.executor._close_order
        self.assertIsNotNone(close_order)
        close_sell = self.ex.sells()[close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("13.68"))
        self.assertEqual(close_sell.amount, self.ex.held)

    # ---------------------------------------------------------- reduced TP (risk 1)
    async def _two_levels_first_tp_open(self):
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("6.84"))

    async def test_temporary_lock_defers_tp_instead_of_stranding_inventory(self):
        await self._two_levels_first_tp_open()
        self.ex.extra_locked = Decimal("0.05")  # exchange holds 13.68, 0.05 briefly unavailable
        for _ in range(2):
            await self.tick()
        self.assertEqual(self.ex.sell_count, 1, "temporary shortfall must not create a reduced TP")
        level2 = self.buy_levels[1]
        self.executor.update_grid_levels()
        self.assertEqual(level2.state, GridLevelStates.OPEN_ORDER_FILLED)
        self.assertEqual(self.tracked_position(), Decimal("13.68"))

        self.ex.extra_locked = Decimal("0")
        await self.tick()
        self.confirm_sells()
        self.assertEqual(self.ex.confirmed["SELL-2"].amount, Decimal("6.84"))
        self.fill("SELL-2", Decimal("6.84"))
        self.executor.update_grid_levels()
        self.assertEqual(level2.state, GridLevelStates.NOT_ACTIVE)
        self.assertEqual(self.tracked_position(), Decimal("6.84"))
        self.assertEqual(self.tracked_position(), self.ex.held)

    async def test_step_rounding_dust_does_not_defer_additional_tp(self):
        await self._two_levels_first_tp_open()
        self.executor.update_grid_levels()
        self.executor.update_position_metrics()
        level2 = self.buy_levels[1]
        first_tp = self.executor.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED][0]

        first_tp.active_close_order.order.amount = Decimal("7.31")
        self.executor.position_size_base = Decimal("14.62536")
        self.ex.held = Decimal("14.62956")
        candidate = SimpleNamespace(amount=Decimal("7.31268"), price=Decimal("3.082"))

        allowed = self.executor._cap_additional_close_amount(level2, candidate)

        self.assertTrue(allowed)
        self.assertEqual(candidate.amount, Decimal("7.31"))

    def test_near_ledger_registers_fee_remainder_as_dust_without_double_fee(self):
        def buy(order_id, price, trade_id):
            fee = Decimal("0.00732")
            amount = Decimal("7.32")
            return {
                "client_order_id": order_id,
                "trading_pair": PAIR,
                "trade_type": TradeType.BUY.name,
                "executed_amount_base": str(amount),
                "executed_amount_quote": str(amount * price),
                "cumulative_fee_paid_quote": str(fee * price),
                "order_fills": {
                    trade_id: {
                        "fill_price": str(price),
                        "fee": {
                            "flat_fees": [{"token": "NEAR", "amount": str(fee)}]
                        },
                    }
                },
            }

        self.executor._filled_orders = [
            buy("BUY-1", Decimal("3.012"), "T1"),
            buy("BUY-2", Decimal("3.012"), "T2"),
            buy("BUY-3", Decimal("3.003"), "T3"),
            {
                "client_order_id": "SELL-1",
                "trading_pair": PAIR,
                "trade_type": TradeType.SELL.name,
                "executed_amount_base": "21.93",
                "executed_amount_quote": "66.2286",
                "cumulative_fee_paid_quote": "0.0662286",
                "order_fills": {
                    "TS1": {
                        "fill_price": "3.02",
                        "fee": {
                            "flat_fees": [
                                {"token": "USDT", "amount": "0.0662286"}
                            ]
                        },
                    }
                },
            },
        ]
        self.executor.close_type = CloseType.EARLY_STOP

        self.executor.update_realized_pnl_metrics()

        self.assertEqual(self.executor._residual_dust_base, Decimal("0.00804"))
        self.assertEqual(
            self.executor.realized_buy_size_quote, Decimal("66.05344764")
        )
        self.assertEqual(
            self.executor.realized_fees_quote, Decimal("0.13230624")
        )
        self.assertEqual(
            self.executor.realized_pnl_quote, Decimal("0.10892376")
        )

    async def test_real_dust_shortfall_caps_tp_and_residual_is_cost_not_sale(self):
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("0.05")  # exchange really holds 0.05 less (unsellable: notional < 1)
        await self.tick()
        self.confirm_sells()
        tp2 = self.ex.confirmed["SELL-2"]
        self.assertEqual(tp2.amount, Decimal("6.79"))
        self.fill("SELL-2", Decimal("6.79"))
        level2 = self.buy_levels[1]
        self.executor.update_grid_levels()
        self.assertEqual(level2.state, GridLevelStates.NOT_ACTIVE)
        self.assertEqual(self.tracked_position(), Decimal("6.84"))
        self.assertEqual(self.tracked_position(), self.ex.held, "tracked inventory equals exchange inventory")
        self.assertEqual(self.executor._retained_residual_base, Decimal("0.05"))
        self.assertEqual(self.executor._held_residual_base, Decimal("0"), "exchange never held it: not inventory")
        self.executor.update_realized_pnl_metrics()
        sold = [o for o in self.executor._filled_orders if o["trade_type"] == TradeType.SELL.name]
        self.assertEqual([Decimal(o["executed_amount_base"]) for o in sold], [Decimal("6.79")])
        self.assertEqual(self.executor.realized_sell_size_quote, Decimal("6.79") * tp2.price)
        self.assertEqual(self.executor.realized_buy_size_quote, Decimal("6.84") * self.buy_levels[1].price)

    async def test_cancelled_partial_buy_is_position_once_and_sold_on_close(self):
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("0.05")  # real shortfall: the exchange never holds this 0.05
        await self.tick()
        self.confirm_sells()
        self.fill("SELL-2", Decimal("6.79"))
        self.assertEqual(self.executor._retained_residual_base, Decimal("0.05"))

        fee = Decimal("0.01")
        self.fill("BUY-3", Decimal("2.00"), fee)  # open partial BUY: not yet position
        self.assertEqual(self.tracked_position(), Decimal("6.84"))
        self.confirm_cancel("BUY-3")
        self.assertEqual(self.tracked_position(), Decimal("8.83"), "level 6.84 + net partial BUY 1.99")
        self.assertEqual(self.tracked_position(), self.ex.held)
        self.confirm_cancel("BUY-3")  # duplicate cancel event: counted once
        self.assertEqual(self.tracked_position(), Decimal("8.83"))
        entry1, entry3 = self.buy_levels[0].price, self.buy_levels[2].price
        self.assertEqual(self.executor.position_break_even_price,
                         (Decimal("6.84") * entry1 + Decimal("1.99") * entry3) / Decimal("8.83"))
        self.assert_reconciles(Decimal("3.23"))

        self.fill("SELL-1", Decimal("6.84"))
        self.assertEqual(self.executor._held_residual_base, Decimal("1.99"))
        await self._stop_with_no_filled_levels()
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("1.99"))
        self.confirm_sells()
        self.fill(close_sell.client_order_id, Decimal("1.99"))
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            for _ in range(2):
                await self.tick()
        self.assertEqual(self.executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(self.ex.held, Decimal("0"))
        self.assertEqual(self.ex.sell_count, 3, "partial BUY sold exactly once")
        self.assertEqual(self.executor.get_custom_info()["residual_dust_base"], Decimal("0"))
        fees = sum((Decimal(o["cumulative_fee_paid_quote"]) for o in self.executor._filled_orders), Decimal("0"))
        self.assertEqual(self.executor.realized_fees_quote, fees, "every fill fee booked once")
        self.assert_reconciles(Decimal("3.23"))

    async def test_cancelled_partial_buy_is_in_final_settlement(self):
        fee = Decimal("0.01")
        self.fill("BUY-1", Decimal("6.84"))
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("2.00"), fee)
        self.confirm_cancel("BUY-2")
        self.fill("SELL-1", Decimal("6.84"))
        self.assertEqual(self.ex.held, Decimal("1.99"))

        await self._stop_with_no_filled_levels()
        self.assertIsNotNone(self.executor._close_order, "stop must create a close order for the bought 1.99")
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("1.99"))
        self.confirm_sells()
        self.fill(close_sell.client_order_id, Decimal("1.99"))
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            for _ in range(2):
                await self.tick()
        self.assertEqual(self.executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(self.ex.held, Decimal("0"))
        self.assertEqual(self.ex.sell_count, 2)
        self.assert_reconciles(Decimal("3.23"))

    async def test_unsellable_cancelled_partial_buy_is_registered_as_dust(self):
        self.fill("BUY-1", Decimal("0.20"))  # 0.20 x 3.23 < min notional 1
        self.confirm_cancel("BUY-1")
        await self._stop_with_no_filled_levels()
        self.assertEqual(self.executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(self.ex.sell_count, 0, "unsellable partial BUY is not sold")
        self.assertEqual(self.executor.get_custom_info()["residual_dust_base"], Decimal("0.20"))

    async def test_temporarily_reduced_tp_fully_filled_keeps_residual_tracked(self):
        # Delayed balance credit: exchange total/available briefly show 0.05 NEAR less, so the
        # 2nd TP is sized 6.79 although the level holds 6.84. The credit then arrives.
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("0.05")
        await self.tick()
        self.confirm_sells()
        tp2 = self.ex.confirmed["SELL-2"]
        self.assertEqual(tp2.amount, Decimal("6.79"))
        self.ex.held += Decimal("0.05")
        self.assertEqual(self.ex.held, Decimal("13.68"))

        self.fill("SELL-2", Decimal("6.79"))
        level2 = self.buy_levels[1]
        self.assertEqual(self.ex.held, Decimal("6.89"))
        self.assertEqual(self.tracked_position(), Decimal("6.89"), "0.05 still held: must stay in the position")
        self.assertEqual(self.tracked_position(), self.ex.held)
        self.assertEqual(level2.state, GridLevelStates.NOT_ACTIVE, "level is free for a new grid cycle")
        self.assertEqual(self.executor._held_residual_base, Decimal("0.05"))
        level1 = self.buy_levels[0]
        self.assertEqual(self.executor.position_break_even_price,
                         (Decimal("6.84") * level1.price + Decimal("0.05") * level2.price) / Decimal("6.89"))

        self.executor.update_realized_pnl_metrics()
        sold = [Decimal(o["executed_amount_base"]) for o in self.executor._filled_orders
                if o["trade_type"] == TradeType.SELL.name]
        self.assertEqual(sold, [Decimal("6.79")], "only the 6.79 actually sold is booked as a sale")
        self.assertEqual(self.executor.realized_sell_size_quote, Decimal("6.79") * tp2.price)
        self.assertEqual(self.executor.realized_buy_size_quote, Decimal("6.79") * level2.price,
                         "cost of the held 0.05 stays with the open position, not in realized P&L")

        # Eventual handling: the stop/close sells the residual together with the remaining position.
        self.executor.close_type = CloseType.STOP_LOSS
        self.executor._status = RunnableStatus.SHUTTING_DOWN
        await self.tick()
        self.confirm_cancel("SELL-1")
        self.confirm_cancel("BUY-3")
        self.confirm_cancel("BUY-4")
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            await self.tick()
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("6.89"))
        self.assertEqual(close_sell.amount, self.ex.held)

    async def test_material_real_shortfall_defers_tp(self):
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("2")  # sellable amount missing: do not shrink the TP, keep level under SL
        for _ in range(2):
            await self.tick()
        self.assertEqual(self.ex.sell_count, 1)
        self.assertEqual(self.executor.status, RunnableStatus.RUNNING)

    # ------------------------------------------------- partial TP fill + stop (risk 2)
    async def test_partial_tp_fills_are_deducted_and_stop_closes_only_remainder(self):
        for oid in ("BUY-1", "BUY-2", "BUY-3"):
            self.fill(oid, Decimal("6.84"))
        for _ in range(3):
            await self.tick()
            self.confirm_sells()
        self.assertEqual(self.ex.held, Decimal("20.52"))

        self.fill("SELL-1", Decimal("3.00"))
        self.assertEqual(self.tracked_position(), Decimal("17.52"), "partial TP sale leaves the position")

        self.executor.close_type = CloseType.STOP_LOSS
        self.executor._status = RunnableStatus.SHUTTING_DOWN
        await self.tick()
        cancelled = {c.kwargs.get("order_id") for c in self.strategy.cancel.call_args_list}
        self.assertEqual(cancelled, {"SELL-1", "SELL-2", "SELL-3", "BUY-4"})

        self.fill("SELL-2", Decimal("2.00"))  # fill while the cancel is in flight
        for oid in ("SELL-2", "SELL-3", "BUY-4"):
            self.confirm_cancel(oid)
        self.assertEqual(self.tracked_position(), Decimal("15.52"))
        self.ex.stale_available = Decimal("20.52")  # balance update still pending

        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            await self.tick()
            self.assertIsNone(self.executor._close_order, "SELL-1 still open on the exchange: wait for cancel")

            self.confirm_cancel("SELL-1")
            await self.tick()
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("15.52"))
        self.assertEqual(close_sell.amount, self.ex.held)
        sold = sorted(Decimal(o["executed_amount_base"]) for o in self.executor._filled_orders
                      if o["trade_type"] == TradeType.SELL.name)
        self.assertEqual(sold, [Decimal("2.00"), Decimal("3.00")], "partial TP sales archived once each")

    # ------------------------------------------- partial TP P&L, exits and residuals
    def _snapshot(self, price):
        self.executor.mid_price = price
        self.tracked_position()
        self.executor.update_realized_pnl_metrics()
        return self.executor.get_custom_info()

    def assert_reconciles(self, price):
        """Tracked inventory equals the exchange and net P&L equals the cash flows of all fills."""
        self._snapshot(price)
        orders = list({**self.ex.pending, **self.ex.confirmed}.values())
        sells = sum((o.executed_amount_quote for o in orders if o.trade_type == TradeType.SELL), Decimal("0"))
        buys = sum((o.executed_amount_quote for o in orders if o.trade_type == TradeType.BUY), Decimal("0"))
        self.assertEqual(self.executor.position_size_base, self.ex.held)
        total = self.executor.realized_pnl_quote + self.executor.position_pnl_quote
        self.assertAlmostEqual(total, sells - buys + self.ex.held * price, places=12)
        return sells, buys

    def _controller(self):
        ctrl = MultiCoinGridController.__new__(MultiCoinGridController)
        ctrl.config = SimpleNamespace(
            fee_aware_filter={"taker_fee_pct": Decimal("0.20")},
            grid_profit_exit_require_remaining_profitable=False,
        )
        return ctrl

    def _entries(self):
        return tuple(level.price for level in self.buy_levels[:2])

    async def _three_sold_from_first_tp(self):
        await self._two_levels_first_tp_open()
        await self.tick()
        self.confirm_sells()
        self.fill("SELL-1", Decimal("3"))
        entry1, entry2 = self._entries()
        return entry1, entry2, Decimal("3.84") * entry1 + Decimal("6.84") * entry2

    async def test_open_partial_tp_sale_is_realized_with_its_cost_for_profit_exit(self):
        entry1, _, remaining_cost = await self._three_sold_from_first_tp()
        sell1 = self.ex.confirmed["SELL-1"].price
        info = self._snapshot(Decimal("3.25"))

        self.assertEqual(self.executor.realized_sell_size_quote, Decimal("3") * sell1)
        self.assertEqual(self.executor.realized_buy_size_quote, Decimal("3") * entry1)
        self.assertEqual(self.executor.realized_pnl_quote, Decimal("3") * (sell1 - entry1))
        self.assertEqual(self.executor.position_size_base, Decimal("10.68"))
        self.assertAlmostEqual(self.executor.position_size_quote, remaining_cost, places=12)
        self.assert_reconciles(Decimal("3.25"))
        self.assertEqual(self._controller()._total_net_grid_profit_decision(PAIR, info, 0.6, False), "exit")

    async def test_cancelled_partial_tp_and_replacement_book_cost_once(self):
        entry1, _, _ = await self._three_sold_from_first_tp()
        sell1 = self.ex.confirmed["SELL-1"].price
        self.confirm_cancel("SELL-1")
        info = self._snapshot(Decimal("3.23"))

        self.assertEqual(self.executor.realized_buy_size_quote, Decimal("3") * entry1)
        self.assertEqual(self.executor.realized_pnl_quote, Decimal("3") * (sell1 - entry1))
        self.assert_reconciles(Decimal("3.23"))
        self.assertNotEqual(self._controller()._total_net_grid_profit_decision(PAIR, info, 0.6, False), "exit")

        await self.tick()
        self.confirm_sells()
        replacement = self.ex.confirmed[f"SELL-{self.ex.sell_count}"]
        self.assertEqual(replacement.amount, Decimal("3.84"))
        self.fill(replacement.client_order_id, Decimal("3.84"))
        self._snapshot(Decimal("3.23"))
        self.assertEqual(self.executor.realized_buy_size_quote, Decimal("6.84") * entry1)
        self.assertEqual(self.executor.realized_sell_size_quote,
                         Decimal("3") * sell1 + Decimal("3.84") * replacement.price)
        archived_ids = [o["client_order_id"] for o in self.executor._filled_orders]
        self.assertEqual(len(archived_ids), len(set(archived_ids)), "no order archived twice")
        self.assert_reconciles(Decimal("3.23"))

    async def test_trailing_stop_uses_cost_of_remaining_units(self):
        _, _, remaining_cost = await self._three_sold_from_first_tp()
        remaining_entry = remaining_cost / Decimal("10.68")
        self.tracked_position()
        self.assertEqual(self.executor.position_break_even_price, remaining_entry)
        self.executor.config.triple_barrier_config.trailing_stop = TrailingStop(
            activation_price=Decimal("0.003"), trailing_delta=Decimal("0.002"))
        self.executor._trailing_stop_trigger_pct = None
        self.executor._trailing_peak_pnl_pct = None
        gross_entry = sum(self._entries()) / 2  # entry incl. units already sold

        # Activates at 0.33% on the remaining units, although only ~0.27% above the gross entry.
        self.executor.mid_price = remaining_entry * Decimal("1.0033")
        self.assertLess(self.executor.mid_price / gross_entry - 1, Decimal("0.003"))
        self.executor.update_position_metrics()
        self.assertAlmostEqual(self.executor.position_pnl_pct, Decimal("0.0033"), places=12)
        self.assertFalse(self.executor.trailing_stop_condition())
        self.assertIsNotNone(self.executor._trailing_stop_trigger_pct)

        self.executor.mid_price = remaining_entry * Decimal("1.0011")
        self.executor.update_position_metrics()
        for realized in (Decimal("-100"), Decimal("100")):
            self.executor.realized_pnl_quote = realized
            self.assertTrue(self.executor.trailing_stop_condition())

    async def test_stop_loss_uses_cost_of_remaining_units(self):
        _, _, remaining_cost = await self._three_sold_from_first_tp()
        self.tracked_position()
        remaining_entry = remaining_cost / Decimal("10.68")
        stop = self.executor.config.triple_barrier_config.stop_loss

        self.executor.mid_price = remaining_entry * (1 - stop) * Decimal("1.0001")
        self.executor.update_position_metrics()
        self.assertGreater(self.executor.position_pnl_pct, -stop)
        self.assertFalse(self.executor.stop_loss_condition())
        self.assertFalse(self.executor.control_triple_barrier())
        self.assertIsNone(self.executor.close_type)

        self.executor.mid_price = remaining_entry * (1 - stop) * Decimal("0.9999")
        self.executor.update_position_metrics()
        self.assertTrue(self.executor.stop_loss_condition())

    async def _stop_with_no_filled_levels(self):
        for oid, order in list(self.ex.confirmed.items()):
            if order.trade_type == TradeType.BUY and order.current_state == OrderState.OPEN:
                self.confirm_cancel(oid)
        self.executor.close_type = CloseType.STOP_LOSS
        self.executor._status = RunnableStatus.SHUTTING_DOWN
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            await self.tick()

    async def test_aggregate_sellable_residual_is_sold_after_last_level_closes(self):
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("0.20")
        await self.tick()
        self.confirm_sells()
        self.assertEqual(self.ex.confirmed["SELL-2"].amount, Decimal("6.64"))
        self.ex.held += Decimal("0.20")
        self.fill("SELL-2", Decimal("6.64"))
        self.fill("BUY-3", Decimal("6.84"))
        self.ex.held -= Decimal("0.40")
        await self.tick()
        self.confirm_sells()
        self.assertEqual(self.ex.confirmed["SELL-3"].amount, Decimal("6.64"))
        self.ex.held += Decimal("0.40")
        self.fill("SELL-3", Decimal("6.64"))
        self.fill("SELL-1", Decimal("6.84"))

        self.assertEqual(self.tracked_position(), Decimal("0"), "residual alone does not drive stops while running")
        self.assertEqual(self.executor._held_residual_base, Decimal("0.40"))
        self.assertEqual(self.ex.held, Decimal("0.40"))
        self._snapshot(Decimal("3.23"))
        residual_cost = Decimal("0.20") * (self.buy_levels[1].price + self.buy_levels[2].price)
        orders = list(self.ex.confirmed.values())
        sells = sum((o.executed_amount_quote for o in orders if o.trade_type == TradeType.SELL), Decimal("0"))
        buys = sum((o.executed_amount_quote for o in orders if o.trade_type == TradeType.BUY), Decimal("0"))
        self.assertEqual(self.executor.realized_buy_size_quote, buys - residual_cost, "residual held at cost")
        self.assertAlmostEqual(self.executor.realized_pnl_quote, sells - buys + residual_cost, places=12)

        await self._stop_with_no_filled_levels()
        self.assertEqual(self.ex.sell_count, 4)
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("0.40"))
        self.confirm_sells()
        self.fill(close_sell.client_order_id, Decimal("0.40"))
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            for _ in range(2):  # CLOSING -> SHUTTING_DOWN -> TERMINATED
                await self.tick()
        self.assertEqual(self.executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(self.ex.held, Decimal("0"))
        self.assertEqual(self.ex.sell_count, 4, "residual sold exactly once")
        self.assert_reconciles(Decimal("3.23"))

    async def test_unsellable_residual_dust_is_registered_separately(self):
        await self._two_levels_first_tp_open()
        self.ex.held -= Decimal("0.05")
        await self.tick()
        self.confirm_sells()
        self.ex.held += Decimal("0.05")
        self.fill("SELL-2", Decimal("6.79"))
        self.fill("SELL-1", Decimal("6.84"))

        self.assertEqual(self.tracked_position(), Decimal("0"))
        info = self._snapshot(Decimal("3.23"))
        self.assertEqual(info["residual_dust_base"], Decimal("0.05"))
        await self._stop_with_no_filled_levels()
        self.assertEqual(self.executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(self.ex.sell_count, 2, "unsellable dust (0.05 x 3.23 < min notional 1) is not sold")
        self.assertEqual(self.executor.get_custom_info()["residual_dust_base"], Decimal("0.05"))

    async def test_inventory_and_pnl_reconcile_with_base_fees_through_partial_tp_and_stop(self):
        fee = Decimal("0.01")
        self.fill("BUY-1", Decimal("6.84"), fee)
        await self.tick()
        self.confirm_sells()
        self.fill("BUY-2", Decimal("6.84"), fee)
        await self.tick()
        self.confirm_sells()
        self.assertEqual(self.ex.confirmed["SELL-1"].amount, Decimal("6.83"))
        self.fill("SELL-1", Decimal("3"))
        self.assertEqual(self.tracked_position(), Decimal("10.66"))
        self.assert_reconciles(Decimal("3.21"))

        self.executor.close_type = CloseType.STOP_LOSS
        self.executor.cancel_open_orders()
        self.executor._status = RunnableStatus.SHUTTING_DOWN
        await self.tick()
        for oid in ("SELL-1", "SELL-2", "BUY-3", "BUY-4"):
            self.confirm_cancel(oid)
        with patch.object(GridExecutor, "_close_price_unreliable", return_value=False), patch("time.sleep"):
            await self.tick()
        close_sell = self.ex.sells()[self.executor._close_order.order_id]
        self.assertEqual(close_sell.amount, Decimal("10.66"))
        self.assert_reconciles(Decimal("3.21"))
