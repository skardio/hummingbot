"""
Regression tests for the BCH-USDT close-order race condition (2026-09-08).

Root cause
----------
Two independent close mechanisms could both try to close the SAME executor:
  1. The timeout-triggered two-phase unwind (``start_forced_close`` ->
     ``_place_graceful_close_orders`` / ``_place_aggressive_close_orders``),
     which tracks its close order via ``self._close_order`` / ``_close_order_id``.
  2. The controller-triggered ``early_stop()`` (e.g. EMERGENCY_EXIT), which
     placed its OWN close order via ``place_close_order_and_cancel_open_orders``
     and wrote to the SAME ``self._close_order`` / ``_close_order_id``.

When both fired for the same executor, whichever order was placed second
overwrote the tracked reference of the first. If the first order's exchange
fill event arrived after the overwrite, it could no longer be matched to any
``TrackedOrder`` and was silently dropped from ``_filled_orders`` -- causing
``realized_sell_size_quote`` to stay at 0 even though the position was
actually sold on the exchange (phantom near-total-loss PnL).

Fix: ``early_stop()`` now defers to an already-active two-phase unwind
(``self._unwind_phase in ("GRACEFUL", "AGGRESSIVE")``) instead of placing a
competing close order, routing the (possibly higher-priority) close reason
through ``start_forced_close()``'s existing idempotent priority mechanism.
"""

from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from test.logger_mixin_for_test import LoggerMixinForTest
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason


def _make_strategy(timestamp: float = 1_000_000.0) -> MagicMock:
    market = MagicMock()
    market_info = MagicMock()
    market_info.market = market
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=market_info)
    type(strategy).trading_pair = PropertyMock(return_value="BCH-USDT")
    type(strategy).current_timestamp = PropertyMock(return_value=timestamp)
    strategy.cancel.return_value = None
    strategy.buy.return_value = "OID-BUY-1"
    strategy.sell.return_value = "OID-SELL-1"
    connector = MagicMock(spec=ExchangePyBase)
    type(connector).trading_rules = PropertyMock(return_value={
        "BCH-USDT": TradingRule(
            trading_pair="BCH-USDT",
            min_order_value=Decimal("5"),
            min_order_size=Decimal("0.0001"),
            min_price_increment=Decimal("0.1"),
        )
    })
    strategy.connectors = {"bitget": connector}
    return strategy


def _make_grid_config(**custom_info_overrides) -> GridExecutorConfig:
    custom_info = {
        "no_fill_timeout_sec": 1800,
        "no_progress_timeout_sec": 3600,
        "max_hold_time_sec": 21600,
        "close_grace_sec": 120,
        "aggressive_close_method": "MARKET",
        "aggressive_close_slippage_guard_pct": Decimal("0.30"),
    }
    custom_info.update(custom_info_overrides)
    return GridExecutorConfig(
        id="test-bch-race",
        timestamp=1_000_000.0,
        side=TradeType.BUY,
        connector_name="bitget",
        trading_pair="BCH-USDT",
        start_price=Decimal("261.4"),
        end_price=Decimal("271.4"),
        total_amount_quote=Decimal("29"),
        min_spread_between_orders=Decimal("0.005"),
        min_order_amount_quote=Decimal("10"),
        limit_price=Decimal("248.3"),
        triple_barrier_config=TripleBarrierConfig(
            take_profit=Decimal("0.075"),
            stop_loss=Decimal("0.05"),
        ),
        custom_info=custom_info,
    )


def _make_executor(config: GridExecutorConfig, start_ts: float = 1_000_000.0) -> GridExecutor:
    strategy = _make_strategy(timestamp=start_ts)
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price",
               return_value=Decimal("253.2")):
        executor = GridExecutor(strategy, config, update_interval=0.5)
    executor._start_timestamp = start_ts
    return executor


class TestEarlyStopUnwindRace(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """Reproduces and verifies the fix for the BCH-USDT close-order race."""

    def setUp(self):
        super().setUp()
        config = _make_grid_config()
        self.executor = _make_executor(config)
        self.set_loggers([self.executor.logger()])
        # Simulate an open position (2 BUY fills, no sells yet) without needing
        # to wire up real grid-level fills.
        self.executor.position_size_base = Decimal("0.1094")
        self.executor.position_size_quote = Decimal("28.85")
        self.executor.mid_price = Decimal("253.2")
        self.executor.current_close_quote = Decimal("253.2")
        # update_position_metrics() would recompute position_size_base from
        # levels_by_state (empty in this test) and reset it to 0 - patch it to
        # a no-op so our pre-set inventory values are respected, exactly like
        # a real grid with confirmed BUY fills would report.
        self.executor.update_position_metrics = MagicMock()

    def test_no_active_unwind_early_stop_places_order_directly(self):
        """Baseline: with no unwind active, early_stop() behaves as before."""
        self.assertEqual(self.executor._unwind_phase, "NONE")

        self.executor.early_stop(keep_position=False, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertEqual(self.executor.close_type, CloseType.STOP_LOSS)
        self.assertTrue(
            self.executor._strategy.sell.called,
            "early_stop() should place its own close order when no unwind is active"
        )

    def test_early_stop_defers_when_unwind_already_active(self):
        """Core fix: early_stop() must NOT place a competing close order while
        a two-phase unwind (e.g. NO_PROGRESS_TIMEOUT) is already in flight."""
        # Simulate an already-active two-phase unwind, as would happen after
        # _check_timeout_triggers() called start_forced_close(NO_PROGRESS_TIMEOUT).
        self.executor._unwind_phase = "AGGRESSIVE"
        self.executor._unwind_close_reason = CloseType.NO_PROGRESS_TIMEOUT
        self.executor._status = RunnableStatus.CLOSING
        self.executor._unwind_started_ts = self.executor._strategy.current_timestamp

        self.executor.early_stop(keep_position=False, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertFalse(
            self.executor._strategy.sell.called,
            "early_stop() must NOT place a second competing close order while "
            "the two-phase unwind is already active (this caused the BCH-USDT "
            "phantom PnL incident)."
        )

    def test_early_stop_upgrades_unwind_reason_when_higher_priority(self):
        """EMERGENCY_EXIT (-> STOP_LOSS, priority 90) must upgrade an in-flight
        NO_PROGRESS_TIMEOUT unwind (priority 60) instead of being dropped."""
        self.executor._unwind_phase = "GRACEFUL"
        self.executor._unwind_close_reason = CloseType.NO_PROGRESS_TIMEOUT
        self.executor._status = RunnableStatus.CLOSING
        self.executor._unwind_started_ts = self.executor._strategy.current_timestamp

        self.executor.early_stop(keep_position=False, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertEqual(self.executor._unwind_close_reason, CloseType.STOP_LOSS)
        self.assertEqual(self.executor.close_type, CloseType.STOP_LOSS)
        self.assertEqual(self.executor._status, RunnableStatus.CLOSING)

    def test_early_stop_does_not_clobber_in_flight_close_order_tracking(self):
        """The exact incident scenario: the unwind has already placed a close
        order (tracked via _close_order_id). early_stop() must not reset or
        overwrite this tracked order -- doing so is what orphaned the BCH
        sell fill from realized PnL."""
        self.executor._unwind_phase = "AGGRESSIVE"
        self.executor._unwind_close_reason = CloseType.NO_PROGRESS_TIMEOUT
        self.executor._status = RunnableStatus.CLOSING
        self.executor._closing_in_progress = True
        self.executor._close_order_id = "unwind_order_1"

        self.executor.early_stop(keep_position=False, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertEqual(
            self.executor._close_order_id, "unwind_order_1",
            "early_stop() must not clear/overwrite the unwind's in-flight close order id"
        )
        self.assertTrue(self.executor._closing_in_progress)
        self.assertFalse(self.executor._strategy.sell.called)

    def test_early_stop_keep_position_ignores_unwind_state(self):
        """keep_position=True must still short-circuit to POSITION_HOLD
        regardless of unwind state (no close order should ever be placed)."""
        self.executor._unwind_phase = "AGGRESSIVE"
        self.executor._unwind_close_reason = CloseType.NO_PROGRESS_TIMEOUT

        self.executor.early_stop(keep_position=True, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertEqual(self.executor.close_type, CloseType.POSITION_HOLD)
        self.assertFalse(self.executor._strategy.sell.called)

    def test_early_stop_records_reason_even_when_deferring(self):
        """_early_stop_reason bookkeeping must be recorded even when the
        order placement itself is deferred to the active unwind."""
        self.executor._unwind_phase = "GRACEFUL"
        self.executor._unwind_close_reason = CloseType.NO_PROGRESS_TIMEOUT

        self.executor.early_stop(keep_position=False, reason=EarlyStopReason.EMERGENCY_EXIT)

        self.assertEqual(self.executor._early_stop_reason, EarlyStopReason.EMERGENCY_EXIT)
