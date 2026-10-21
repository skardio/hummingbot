"""Observability fix: EARLY_STOP/FAILED closes with no EarlyStopReason were
silently persisted as ``UNKNOWN`` with no trace of why. Root-cause analysis of
6 production executors (3 EARLY_STOP, 3 FAILED) found all 6 had
``early_stop_reason=UNKNOWN`` and no corresponding log line, because:

1. ``early_stop()`` defaults to ``EarlyStopReason.UNKNOWN`` when called without
   an explicit reason, with no record of the caller.
2. The external-position-closed detection path in
   ``control_shutdown_process()`` sets ``close_type = CloseType.FAILED``
   directly and never touches ``_early_stop_reason`` at all.

This is a pure observability addition: a new ``_exit_diagnostic`` string,
surfaced via ``get_custom_info()["exit_diagnostic"]``. It does not change
``CloseType``/``EarlyStopReason`` enum semantics, trading logic, or exit
timing — confirmed by the tests below.
"""
from decimal import Decimal
from unittest.mock import MagicMock

from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason


def _make_early_stop_executor(pair: str = "NIL-USD") -> GridExecutor:
    """Minimal executor stub exercising early_stop()'s real code path."""
    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.id = "exit-reason-regression"
    executor.config.connector_name = "kraken"
    executor.config.trading_pair = pair
    connector = MagicMock()
    connector.get_available_balance = MagicMock(return_value=Decimal("0"))
    executor.connectors = {"kraken": connector}
    executor.trading_rules = MagicMock(min_order_size=Decimal("1"))
    executor.position_size_base = Decimal("0")
    executor.position_size_quote = Decimal("0")
    executor._early_stop_reason = None
    executor._exit_diagnostic = None
    executor.cancel_open_orders = MagicMock()
    executor.update_position_metrics = MagicMock()
    executor.update_metrics = MagicMock()
    executor.logger = MagicMock(return_value=MagicMock())
    return executor


def test_explicit_reason_is_preserved_and_no_diagnostic_is_recorded():
    """A properly-reasoned stop (e.g. the controller's emergency path) must
    keep working exactly as before: no diagnostic noise is added."""
    executor = _make_early_stop_executor()

    executor.early_stop(keep_position=False, reason=EarlyStopReason.STOP_LOSS)

    assert executor._early_stop_reason == EarlyStopReason.STOP_LOSS
    assert executor.close_type == CloseType.STOP_LOSS
    assert executor._exit_diagnostic is None


def test_reason_less_stop_is_recorded_as_unknown_with_diagnostic_and_caller():
    """A stop_action arriving without a reason (the production pattern found
    in GNOT/FIL/DOT) must still end up queryable: EarlyStopReason.UNKNOWN,
    plus a diagnostic string identifying it was reason-less and who called."""
    executor = _make_early_stop_executor(pair="GNOT-USD")

    executor.early_stop(keep_position=False, reason=None)

    assert executor._early_stop_reason == EarlyStopReason.UNKNOWN
    assert executor._exit_diagnostic is not None
    assert executor._exit_diagnostic.startswith("early_stop_no_reason:caller=")
    assert "test_reason_less_stop_is_recorded_as_unknown_with_diagnostic_and_caller" in executor._exit_diagnostic


def test_reason_less_stop_still_maps_to_early_stop_not_stop_loss():
    """UNKNOWN must never be mistaken for an emergency reason: close_type stays
    EARLY_STOP, distinct from STOP_LOSS (emergency/hard-stop) and FAILED."""
    executor = _make_early_stop_executor()

    executor.early_stop(keep_position=False, reason=None)

    assert executor.close_type == CloseType.EARLY_STOP


def test_emergency_and_hard_stop_reasons_remain_unaffected():
    """Protective emergency/hard-stop exits must keep mapping to STOP_LOSS and
    stay diagnostic-free — the fix must not touch this existing behavior."""
    for reason in (EarlyStopReason.EMERGENCY_EXIT, EarlyStopReason.HARD_STOP_EXIT):
        executor = _make_early_stop_executor()
        executor.early_stop(keep_position=False, reason=reason)

        assert executor.close_type == CloseType.STOP_LOSS
        assert executor._early_stop_reason == reason
        assert executor._exit_diagnostic is None


def test_get_custom_info_exposes_exit_diagnostic_without_breaking_existing_fields():
    """DB/downstream consumers must keep getting every existing custom_info
    key; exit_diagnostic is additive only."""
    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.custom_info = {}
    executor.config.side = MagicMock()
    executor.levels_by_state = {}
    executor._held_position_orders = []
    executor._filled_orders = []
    executor._failed_orders = []
    executor._canceled_orders = []
    executor.realized_buy_size_quote = Decimal("0")
    executor.realized_sell_size_quote = Decimal("0")
    executor.realized_imbalance_quote = Decimal("0")
    executor.realized_buy_fees_quote = Decimal("0")
    executor.realized_sell_fees_quote = Decimal("0")
    executor.realized_fees_quote = Decimal("0")
    executor.realized_pnl_quote = Decimal("0")
    executor.realized_pnl_pct = Decimal("0")
    executor.position_size_quote = Decimal("0")
    executor.position_fees_quote = Decimal("0")
    executor.position_break_even_price = Decimal("0")
    executor.position_pnl_quote = Decimal("0")
    executor.open_liquidity_placed = Decimal("0")
    executor.close_liquidity_placed = Decimal("0")
    executor._early_stop_reason = EarlyStopReason.UNKNOWN
    executor._exit_diagnostic = "external_position_closed:tracked=0_actual=0_NIL"

    info = executor.get_custom_info()

    # Pre-existing keys (US-006) are untouched.
    assert info["early_stop_reason"] == "UNKNOWN"
    assert info["early_stop_reason_code"] == 0
    # New, additive key.
    assert info["exit_diagnostic"] == "external_position_closed:tracked=0_actual=0_NIL"


def test_get_custom_info_exit_diagnostic_defaults_to_none():
    """When a proper EarlyStopReason was recorded, no diagnostic noise leaks
    into stored records."""
    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.custom_info = {}
    executor.config.side = MagicMock()
    executor.levels_by_state = {}
    executor._held_position_orders = []
    executor._filled_orders = []
    executor._failed_orders = []
    executor._canceled_orders = []
    executor.realized_buy_size_quote = Decimal("0")
    executor.realized_sell_size_quote = Decimal("0")
    executor.realized_imbalance_quote = Decimal("0")
    executor.realized_buy_fees_quote = Decimal("0")
    executor.realized_sell_fees_quote = Decimal("0")
    executor.realized_fees_quote = Decimal("0")
    executor.realized_pnl_quote = Decimal("0")
    executor.realized_pnl_pct = Decimal("0")
    executor.position_size_quote = Decimal("0")
    executor.position_fees_quote = Decimal("0")
    executor.position_break_even_price = Decimal("0")
    executor.position_pnl_quote = Decimal("0")
    executor.open_liquidity_placed = Decimal("0")
    executor.close_liquidity_placed = Decimal("0")
    executor._early_stop_reason = EarlyStopReason.STOP_LOSS
    executor._exit_diagnostic = None

    info = executor.get_custom_info()

    assert info["exit_diagnostic"] is None
