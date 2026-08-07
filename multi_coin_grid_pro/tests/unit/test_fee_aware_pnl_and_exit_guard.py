from decimal import Decimal
from unittest.mock import MagicMock

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason
from multi_coin_grid_pro.logic.exit_safety import (
    fee_aware_exit_decision,
    position_tracking_cleanup_allowed,
    realized_net_pnl,
    stop_allowed_after_preclose,
)


def test_pengu_regression_realized_pnl_uses_kraken_style_net_formula():
    realized_buy_quote = Decimal("24.17424") + Decimal("23.95537")
    realized_sell_quote = Decimal("47.27893")
    realized_buy_fees_quote = Decimal("0.08461") + Decimal("0.04791")
    realized_sell_fees_quote = Decimal("0.09456")

    assert realized_net_pnl(
        realized_sell_quote=realized_sell_quote,
        realized_buy_quote=realized_buy_quote,
        realized_buy_fees_quote=realized_buy_fees_quote,
        realized_sell_fees_quote=realized_sell_fees_quote,
    ) == Decimal("-1.07776")


def test_fee_aware_guard_blocks_hard_cap_when_exit_is_below_break_even():
    decision = fee_aware_exit_decision(
        side="BUY",
        avg_entry=Decimal("100"),
        position_size_base=Decimal("1"),
        buy_fees_quote=Decimal("0.20"),
        current_price=Decimal("100.30"),
        expected_exit_fee_rate=Decimal("0.0035"),
    )

    assert decision.break_even > Decimal("100.30")
    assert decision.allowed is False


def test_fee_aware_guard_allows_hard_cap_above_break_even():
    decision = fee_aware_exit_decision(
        side="BUY",
        avg_entry=Decimal("100"),
        position_size_base=Decimal("1"),
        buy_fees_quote=Decimal("0.20"),
        current_price=Decimal("100.80"),
        expected_exit_fee_rate=Decimal("0.0035"),
    )

    assert decision.break_even < Decimal("100.80")
    assert decision.allowed is True


def test_pengu_trend_exit_is_below_fee_aware_break_even():
    avg_entry = Decimal("0.0116550005")
    position_size_quote = Decimal("48.12961")
    position_size_base = position_size_quote / avg_entry

    decision = fee_aware_exit_decision(
        side="BUY",
        avg_entry=avg_entry,
        position_size_base=position_size_base,
        buy_fees_quote=Decimal("0.13252"),
        current_price=Decimal("0.011449"),
        expected_exit_fee_rate=Decimal("0.0035"),
    )

    assert decision.break_even > Decimal("0.011449")
    assert decision.allowed is False


def test_preclose_failure_blocks_non_emergency_stop_action():
    assert stop_allowed_after_preclose(can_close=False, emergency=False) is False


def test_preclose_failure_allows_explicit_emergency_stop_action():
    assert stop_allowed_after_preclose(can_close=False, emergency=True) is True


def test_stop_loss_close_type_bypasses_fee_aware_break_even_guard():
    executor = GridExecutor.__new__(GridExecutor)

    assert executor._fee_aware_close_allowed(
        CloseType.STOP_LOSS,
        current_price=Decimal("0.66"),
        stage="regression_stop_loss",
    ) is True


def test_early_stop_with_stop_loss_reason_sets_stop_loss_close_type():
    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.id = "rave-regression"
    executor.config.connector_name = "kraken"
    executor.config.trading_pair = "RAVE-USD"
    connector = MagicMock()
    connector.get_available_balance = MagicMock(return_value=Decimal("0"))
    executor.connectors = {"kraken": connector}
    executor.trading_rules = MagicMock(min_order_size=Decimal("1"))
    executor.position_size_base = Decimal("0")
    executor.position_size_quote = Decimal("0")
    executor._early_stop_reason = None
    executor.cancel_open_orders = MagicMock()
    executor.update_position_metrics = MagicMock()
    executor.update_metrics = MagicMock()
    executor.logger = MagicMock(return_value=MagicMock())

    executor.early_stop(keep_position=False, reason=EarlyStopReason.STOP_LOSS)

    assert executor.close_type == CloseType.STOP_LOSS
    assert executor._early_stop_reason == EarlyStopReason.STOP_LOSS


def test_position_tracking_cleanup_waits_for_confirmed_close():
    assert position_tracking_cleanup_allowed(status_name="CLOSING", is_active=True) is False
    assert position_tracking_cleanup_allowed(status_name="SHUTTING_DOWN", is_active=True) is False
    assert position_tracking_cleanup_allowed(status_name="TERMINATED", is_active=False) is True


def _make_take_profit_executor(position_pnl_quote: Decimal) -> GridExecutor:
    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.id = "tp-regression"
    executor.config.side = TradeType.BUY
    executor.config.end_price = Decimal("100")
    executor.config.custom_info = {
        "dynamic_tp_enabled": True,
        "dynamic_tp_min_pct": 0.02,
        "min_grid_profit_pct": 2.0,
        "fee_aware_min_net_profit_pct": 0.3,
    }
    executor.mid_price = Decimal("101")
    executor.position_size_base = Decimal("1")
    executor.position_size_quote = Decimal("100")
    executor.position_pnl_quote = position_pnl_quote
    executor.position_break_even_price = Decimal("100")
    executor.update_position_metrics = MagicMock()
    executor._get_fee_rates = MagicMock(return_value=(Decimal("0.0020"), Decimal("0.0035")))
    executor.logger = MagicMock(return_value=MagicMock())
    return executor


def test_global_take_profit_blocks_tiny_net_profit_below_required_target():
    executor = _make_take_profit_executor(position_pnl_quote=Decimal("1.00"))

    assert executor.take_profit_condition() is False


def test_global_take_profit_allows_when_net_profit_reaches_required_target():
    executor = _make_take_profit_executor(position_pnl_quote=Decimal("2.70"))

    assert executor.take_profit_condition() is True


def test_global_take_profit_does_not_close_empty_executor_as_take_profit():
    executor = _make_take_profit_executor(position_pnl_quote=Decimal("0"))
    executor.position_size_base = Decimal("0")
    executor.position_size_quote = Decimal("0")

    assert executor.take_profit_condition() is False


def test_grid_executor_net_pnl_pct_uses_entry_notional_not_round_trip_volume():
    executor = GridExecutor.__new__(GridExecutor)
    executor.close_type = CloseType.STOP_LOSS
    executor.realized_buy_size_quote = Decimal("54.510328236")
    executor.realized_sell_size_quote = Decimal("53.10920358")
    executor.realized_pnl_quote = Decimal("-1.657363226")
    executor.position_size_quote = Decimal("0")
    executor.position_size_base = Decimal("0")
    executor.trading_rules = MagicMock(min_order_size=Decimal("0"))

    assert executor.filled_amount_quote == Decimal("107.619531816")
    assert (executor.get_net_pnl_pct() * Decimal("100")).quantize(Decimal("0.0001")) == Decimal("-3.0405")


# ---------------------------------------------------------------------------
# Residual-dust PnL correction — step-size quantization (INJ / Bitget case)
# ---------------------------------------------------------------------------

def _make_inj_fill_order(trade_type: str, amount_base: str, amount_quote: str,
                         fees_quote: str = "0") -> dict:
    """Minimal filled-order dict matching InFlightOrder.to_json() structure."""
    return {
        "trade_type": trade_type,
        "executed_amount_base": amount_base,
        "executed_amount_quote": amount_quote,
        "cumulative_fee_paid_quote": fees_quote,
    }


def _make_executor_for_residual_test(
    filled_orders: list,
    min_order_size: str = "0.1",
    close_type: CloseType = CloseType.TAKE_PROFIT,
) -> GridExecutor:
    """Bare GridExecutor wired up for update_realized_pnl_metrics() calls."""
    executor = GridExecutor.__new__(GridExecutor)
    executor._filled_orders = filled_orders
    executor._held_position_orders = []
    executor.close_type = close_type
    executor.trading_rules = MagicMock()
    executor.trading_rules.min_order_size = Decimal(min_order_size)
    executor.logger = MagicMock(return_value=MagicMock())
    # Attrs updated by the method itself — pre-zero so assertions are clean
    executor.realized_buy_size_quote = Decimal("0")
    executor.realized_sell_size_quote = Decimal("0")
    executor.realized_imbalance_quote = Decimal("0")
    executor.realized_buy_fees_quote = Decimal("0")
    executor.realized_sell_fees_quote = Decimal("0")
    executor.realized_fees_quote = Decimal("0")
    executor.realized_pnl_quote = Decimal("0")
    executor.realized_pnl_pct = Decimal("0")
    return executor


class TestResidualDustPnlCorrection:
    """
    INJ / Bitget scenario: bot bought 3.1968 INJ but step-size 0.1 allowed
    selling only 3.1 INJ.  The 0.0968 INJ residual (< min_order_size 0.1) must
    NOT cause TAKE_PROFIT to report a negative PnL.
    """

    # Scenario numbers:
    # S1 – INJ residual below step-size → correction applied, PnL >= 0
    # S2 – residual above dust threshold → no correction (bot can retry sell)
    # S3 – no residual (perfectly matched) → no correction
    # S4 – POSITION_HOLD → no correction (residual is intentional)
    # S5 – PnL stays >= 0 even with non-trivial fees

    def test_s1_inj_residual_below_step_size_pnl_is_non_negative(self):
        """
        3 buy fills totalling 3.1968 INJ @ avg $30.  1 sell of 3.1 INJ @ $30.15.
        Residual 0.0968 INJ < min_order_size 0.1 → correction deducts residual
        cost from realized_buy_size_quote, making PnL >= 0.
        """
        fills = [
            # Three buys: 1.0 + 1.0 + 1.1968 INJ
            _make_inj_fill_order("BUY", "1.0", "30.000", "0.030"),
            _make_inj_fill_order("BUY", "1.0", "30.000", "0.030"),
            _make_inj_fill_order("BUY", "1.1968", "35.904", "0.0359"),
            # Close sell: 3.1 INJ @ $30.15 (step-size truncated from 3.1968)
            _make_inj_fill_order("SELL", "3.1", "93.465", "0.093"),
        ]
        executor = _make_executor_for_residual_test(fills)

        executor.update_realized_pnl_metrics()

        # Residual = 3.1968 - 3.1 = 0.0968 < 0.1 → correction applied
        # buy_quote before correction = 30 + 30 + 35.904 = 95.904
        # avg_entry = 95.904 / 3.1968 ≈ 30.00
        # residual_cost = 0.0968 * 30.00 = 2.904
        # effective_buy_quote = 95.904 - 2.904 = 93.000
        # pnl = 93.465 - 93.000 - (0.030+0.030+0.0359) - 0.093 ≈ +0.276
        assert executor.realized_pnl_quote >= Decimal("0"), (
            f"TAKE_PROFIT must not be negative after step-size residual correction, "
            f"got {executor.realized_pnl_quote}"
        )

    def test_s1_corrected_buy_quote_reflects_only_sold_portion(self):
        fills = [
            _make_inj_fill_order("BUY", "3.1968", "95.904", "0.096"),
            _make_inj_fill_order("SELL", "3.1", "93.465", "0.093"),
        ]
        executor = _make_executor_for_residual_test(fills)
        executor.update_realized_pnl_metrics()

        # effective_buy = 95.904 - (0.0968/3.1968)*95.904 = 95.904 - 2.904 = 93.000
        assert executor.realized_buy_size_quote == Decimal("93.000").quantize(
            executor.realized_buy_size_quote
        ) or abs(executor.realized_buy_size_quote - Decimal("93.000")) < Decimal("0.001"), (
            f"buy_quote after correction should be ~93.000, got {executor.realized_buy_size_quote}"
        )

    def test_s2_residual_above_dust_threshold_no_correction(self):
        """
        Residual 0.5 INJ > min_order_size 0.1 → bot can place another sell →
        no correction should be applied (imbalance should trigger another close).
        """
        fills = [
            _make_inj_fill_order("BUY", "3.5", "105.00", "0.105"),
            _make_inj_fill_order("SELL", "3.0", "90.45", "0.090"),
        ]
        executor = _make_executor_for_residual_test(fills)
        executor.update_realized_pnl_metrics()

        # No correction: buy_quote should still be 105.00
        assert executor.realized_buy_size_quote == Decimal("105.00"), (
            f"No correction when residual 0.5 > dust_threshold 0.1, "
            f"got {executor.realized_buy_size_quote}"
        )

    def test_s3_no_residual_no_correction(self):
        """Perfectly matched buys and sells → no correction, normal PnL."""
        fills = [
            _make_inj_fill_order("BUY", "3.1", "93.00", "0.093"),
            _make_inj_fill_order("SELL", "3.1", "93.93", "0.094"),
        ]
        executor = _make_executor_for_residual_test(fills)
        executor.update_realized_pnl_metrics()

        assert executor.realized_buy_size_quote == Decimal("93.00")
        assert executor.realized_pnl_quote == Decimal("93.93") - Decimal("93.00") - Decimal("0.093") - Decimal("0.094")

    def test_s4_position_hold_no_correction(self):
        """
        POSITION_HOLD: residual is intentional inventory, not dust.
        Correction must NOT be applied.
        """
        fills = [
            _make_inj_fill_order("BUY", "3.1968", "95.904", "0.096"),
            _make_inj_fill_order("SELL", "3.1", "93.465", "0.093"),
        ]
        executor = _make_executor_for_residual_test(
            fills, close_type=CloseType.POSITION_HOLD
        )
        executor.update_realized_pnl_metrics()

        assert executor.realized_buy_size_quote == Decimal("95.904"), (
            "POSITION_HOLD must not apply residual correction"
        )

    def test_s5_take_profit_pnl_non_negative_with_fees(self):
        """
        Ensures TAKE_PROFIT stays >= 0 after correction even when fees are
        non-trivial (0.1% buy + 0.1% sell Bitget standard).
        """
        buy_quote = Decimal("95.904")
        sell_quote = Decimal("93.465")
        buy_fees = buy_quote * Decimal("0.001")
        sell_fees = sell_quote * Decimal("0.001")

        fills = [
            _make_inj_fill_order("BUY", "3.1968", str(buy_quote), str(buy_fees)),
            _make_inj_fill_order("SELL", "3.1", str(sell_quote), str(sell_fees)),
        ]
        executor = _make_executor_for_residual_test(fills)
        executor.update_realized_pnl_metrics()

        assert executor.realized_pnl_quote >= Decimal("0"), (
            f"PnL must be >= 0 for TAKE_PROFIT with standard fees, "
            f"got {executor.realized_pnl_quote}"
        )
