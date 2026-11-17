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
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
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
        return self.held - self.locked()

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
