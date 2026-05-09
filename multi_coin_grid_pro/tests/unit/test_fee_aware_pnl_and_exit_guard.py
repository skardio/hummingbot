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
