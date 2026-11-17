import json
from decimal import Decimal
from test.hummingbot.strategy_v2.executors.grid_executor import test_grid_executor_multi_tp as base

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridLevelStates

ROWS = []
Z = Decimal("0")


class Checked(base.TestGridExecutorMultiTakeProfit):
    def setUp(self):
        super().setUp()
        self._fees_base = Z
        self._step = 0

    def fill(self, oid, amount, fee_base=Z):
        super().fill(oid, amount, fee_base)
        if self.ex.confirmed[oid].trade_type == TradeType.BUY:
            self._fees_base += fee_base
        self.check(f"fill {oid} {amount}")

    def confirm_cancel(self, oid):
        super().confirm_cancel(oid)
        self.check(f"cancel {oid}")

    def confirm_sells(self):
        super().confirm_sells()
        self.check("confirm_sells")

    async def tick(self, seconds=6.0):
        await super().tick(seconds)
        self.check("tick")

    def check(self, step):
        self._step += 1
        e, ex = self.executor, self.ex
        if getattr(e, "mid_price", None) is None:
            e.mid_price = Decimal("3.23")  # same mark as tick()'s patched get_price
        e.update_grid_levels()
        e.update_position_metrics()
        e.update_realized_pnl_metrics()
        p = e.mid_price
        orders = list({**ex.pending, **ex.confirmed}.values())
        buys = [o for o in orders if o.trade_type == TradeType.BUY]
        sells = [o for o in orders if o.trade_type == TradeType.SELL]
        buy_b = sum((o.executed_amount_base for o in buys), Z)
        sell_b = sum((o.executed_amount_base for o in sells), Z)
        ledger = buy_b - self._fees_base - sell_b
        cash = sum((o.executed_amount_quote for o in sells), Z) - sum((o.executed_amount_quote for o in buys), Z)
        filled_lv = e.levels_by_state.get(GridLevelStates.OPEN_ORDER_FILLED, []) + \
            e.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, [])
        open_part_b = open_part_q = Z
        for lv in e.levels_by_state.get(GridLevelStates.OPEN_ORDER_PLACED, []):
            o = lv.active_open_order
            if o is not None and o.order is not None and o.executed_amount_base > 0:
                open_part_b += o.executed_amount_base - o.cum_fees_base
                open_part_q += o.executed_amount_quote
        standalone = e._held_residual_base if not filled_lv else Z
        standalone_cost = e._held_residual_cost_quote if not filled_lv else Z
        close_partial = Z
        if e._close_order is not None and e._close_order.order is not None and not e._close_order.is_done:
            close_partial = e._close_order.executed_amount_base
        tracked = e.position_size_base + open_part_b + standalone - close_partial
        gap = cash + ex.held * p - (e.realized_pnl_quote + e.position_pnl_quote)
        expected_gap = (open_part_b * p - open_part_q) + (standalone * p - standalone_cost) \
            - close_partial * (p - e.position_break_even_price) if e.position_size_base > 0 else \
            (open_part_b * p - open_part_q) + (standalone * p - standalone_cost)
        fills_fee_q = sum((o.cumulative_fee_paid("USDT") for o in orders), Z)
        locked = ex.locked()
        ids = [o.get("client_order_id") for o in e._filled_orders]
        ROWS.append({
            "test": self._testMethodName, "n": self._step, "step": step,
            "ledger": str(ledger), "exchange": str(ex.held), "tracked": str(tracked),
            "inv_ok": tracked == ex.held, "sim_shortfall": str(ledger - ex.held),
            "pnl_gap": str(gap), "expected_gap": str(expected_gap),
            "pnl_ok": abs(gap - expected_gap) < Decimal("1e-12"),
            "fees_ok": e.realized_fees_quote + e.position_fees_quote <= fills_fee_q + Decimal("1e-12"),
            "fees": [str(e.realized_fees_quote), str(e.position_fees_quote), str(fills_fee_q)],
            "no_oversell": ex.held >= 0 and locked <= ex.held and sell_b <= buy_b - self._fees_base,
            "no_dup_archive": len(ids) == len(set(ids)),
            "dust": str(e.get_custom_info().get("residual_dust_base", Z)),
            "status": e.status.name, "filled_levels": len(filled_lv),
        })

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with open("/tmp/cycle_rows.json", "w") as fh:
            json.dump(ROWS, fh)


del base.TestGridExecutorMultiTakeProfit
