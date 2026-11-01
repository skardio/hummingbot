"""
Regression tests: Bitget buy-fee (AddedToCost, charged in BASE token) must not be
deducted twice from realized P&L when `deduct_base_fees=True`.

With deduct_base_fees the executor already sells `executed_base - fee_base`, so the
fee is embedded in (sell - buy). Real case: BR-USDT executor G171n5h8... (Bitget,
2026-10-23): buy 157.941114 USDT / 300.93 BR, buy fee 0.30093 BR, sell 154.759176
USDT, sell fee 0.154759176 USDT. Cashflow P&L = -3.336697 (executor booked -3.494638).

Kraken (`deduct_base_fees=False`, fees in quote) must stay bit-identical.
"""
from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType


def _make_executor(pair: str, connector: str, deduct_base_fees: bool, min_order_size: str = "0.0001") -> GridExecutor:
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).current_timestamp = PropertyMock(return_value=1_000_000.0)
    conn = MagicMock(spec=ExchangePyBase)
    type(conn).trading_rules = PropertyMock(return_value={
        pair: TradingRule(trading_pair=pair, min_order_value=Decimal("1"),
                          min_order_size=Decimal(min_order_size), min_price_increment=Decimal("0.0001")),
    })
    strategy.connectors = {connector: conn}
    config = GridExecutorConfig(
        id=f"base-fee-{connector}", timestamp=1_000_000.0, side=TradeType.BUY, connector_name=connector,
        trading_pair=pair, start_price=Decimal("1"), end_price=Decimal("2"), limit_price=Decimal("0.5"),
        total_amount_quote=Decimal("200"), min_spread_between_orders=Decimal("0.005"),
        min_order_amount_quote=Decimal("10"), deduct_base_fees=deduct_base_fees,
        triple_barrier_config=TripleBarrierConfig(take_profit=Decimal("0.05"), stop_loss=Decimal("0.05")),
    )
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price", return_value=Decimal("1")):
        executor = GridExecutor(strategy, config, update_interval=0.5)
    # Fully closed position: only realized figures should be reported.
    executor.position_size_base = Decimal("0")
    executor.position_size_quote = Decimal("0")
    executor.position_fees_quote = Decimal("0")
    executor.position_pnl_quote = Decimal("0")
    executor.close_type = CloseType.STOP_LOSS
    return executor


def _order(pair, side, base, quote, fee_token, fee_amount, price=None):
    price = price if price is not None else Decimal(quote) / Decimal(base)
    fee_quote = Decimal(fee_amount) * (price if fee_token == pair.split("-")[0] else Decimal("1"))
    return {
        "client_order_id": f"{side}-{base}", "trading_pair": pair, "trade_type": side,
        "executed_amount_base": str(base), "executed_amount_quote": str(quote),
        "cumulative_fee_paid_quote": float(fee_quote),
        "order_fills": {"t1": {
            "fill_price": str(price), "fill_base_amount": str(base), "fill_quote_amount": str(quote),
            "fee": {"fee_type": "AddedToCost" if side == "BUY" else "DeductedFromReturns", "percent": "0",
                    "percent_token": None, "flat_fees": [{"token": fee_token, "amount": str(fee_amount)}]},
        }},
    }


def _br_orders():
    return [
        _order("BR-USDT", "BUY", "300.93", "157.941114", "BR", "0.30093"),
        _order("BR-USDT", "SELL", "300.62", "154.759176", "USDT", "0.154759176"),
    ]


class TestBaseFeeRealizedPnl(IsolatedAsyncioWrapperTestCase):

    def _run(self, executor, orders):
        executor._filled_orders = orders
        executor.update_realized_pnl_metrics()
        return executor

    def test_bitget_br_usdt_buy_fee_not_deducted_twice(self):
        ex = self._run(_make_executor("BR-USDT", "bitget", True), _br_orders())
        self.assertAlmostEqual(float(ex.realized_pnl_quote), -3.336697176, places=6)
        self.assertAlmostEqual(float(ex.get_net_pnl_quote()), -3.336697176, places=6)

    def test_bitget_fee_registration_unchanged(self):
        ex = self._run(_make_executor("BR-USDT", "bitget", True), _br_orders())
        self.assertAlmostEqual(float(ex.realized_buy_fees_quote), 0.157941114, places=6)
        self.assertAlmostEqual(float(ex.realized_sell_fees_quote), 0.154759176, places=6)
        self.assertAlmostEqual(float(ex.realized_fees_quote), 0.3127003, places=6)
        self.assertAlmostEqual(float(ex.get_cum_fees_quote()), 0.3127003, places=6)
        self.assertEqual(ex.realized_buy_size_quote, Decimal("157.941114"))
        self.assertEqual(ex.realized_sell_size_quote, Decimal("154.759176"))

    def test_bitget_gross_equals_net_plus_fees_is_price_move_only(self):
        """gross = net + fees must equal sell minus cost of the units actually received."""
        ex = self._run(_make_executor("BR-USDT", "bitget", True), _br_orders())
        gross = ex.get_net_pnl_quote() + ex.get_cum_fees_quote()
        received_cost = Decimal("157.941114") * (Decimal("300.93") - Decimal("0.30093")) / Decimal("300.93")
        self.assertAlmostEqual(float(gross), float(Decimal("154.759176") - received_cost), places=6)

    def test_bitget_pnl_pct_denominator_unchanged(self):
        ex = self._run(_make_executor("BR-USDT", "bitget", True), _br_orders())
        self.assertAlmostEqual(float(ex.realized_pnl_pct), float(ex.realized_pnl_quote / Decimal("157.941114")), places=9)
        self.assertAlmostEqual(float(ex.get_net_pnl_pct()), float(ex.realized_pnl_quote / Decimal("157.941114")), places=9)

    def test_kraken_quote_fees_formula_bit_identical(self):
        orders = [_order("ADA-USD", "BUY", "100", "100", "USD", "0.3", price=Decimal("1")),
                  _order("ADA-USD", "SELL", "100", "101", "USD", "0.3", price=Decimal("1.01"))]
        ex = self._run(_make_executor("ADA-USD", "kraken", False), orders)
        self.assertEqual(ex.realized_pnl_quote, ex.realized_sell_size_quote - ex.realized_buy_size_quote
                         - ex.realized_buy_fees_quote - ex.realized_sell_fees_quote)
        self.assertAlmostEqual(float(ex.realized_pnl_quote), 0.4, places=9)
        self.assertAlmostEqual(float(ex.realized_fees_quote), 0.6, places=9)

    def test_base_fee_without_deduct_flag_keeps_old_formula(self):
        """Fee in base token but deduct_base_fees=False: executor sells gross amount, fee still charged."""
        ex = self._run(_make_executor("BR-USDT", "bitget", False), _br_orders())
        self.assertAlmostEqual(float(ex.realized_pnl_quote), -3.494638290, places=6)

    def test_small_base_fee_below_min_order_size_not_overcorrected(self):
        """Fee units alone (<min_order_size) used to be absorbed by the residual-dust branch; no double offset now."""
        orders = [_order("BTC-USDT", "BUY", "0.001", "50", "BTC", "0.000001"),
                  _order("BTC-USDT", "SELL", "0.000999", "50.0499", "USDT", "0.05005")]
        ex = self._run(_make_executor("BTC-USDT", "bitget", True, min_order_size="0.00001"), orders)
        # cashflow: -50 + 50.0499 - 0.05005
        self.assertAlmostEqual(float(ex.realized_pnl_quote), -0.00015, places=8)

    def test_true_dust_still_removed_from_cost(self):
        """Genuine leftover (received - sold) below min_order_size keeps the existing dust correction."""
        orders = [_order("BTC-USDT", "BUY", "0.001", "50", "BTC", "0.000001"),
                  _order("BTC-USDT", "SELL", "0.0009985", "50.0", "USDT", "0.05")]
        ex = self._run(_make_executor("BTC-USDT", "bitget", True, min_order_size="0.00001"), orders)
        dust_cost = Decimal("0.0000005") * Decimal("50") / Decimal("0.001")
        expected = Decimal("50.0") - Decimal("0.05") - (Decimal("50") - dust_cost)
        self.assertAlmostEqual(float(ex.realized_pnl_quote), float(expected), places=8)
