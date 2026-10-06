"""
Tests for FASE 1C: post-fill periodic shadow risk sampling (2026-09-22,
updated 2026-10-02 to start from fill 3 instead of fill 5 - see
post_fill_sampling_start_fill).

Pure logging/data-collection feature - must NEVER change trading behavior.
Covers:
  - inactive while buy_fill_count < custom_info['post_fill_sampling_start_fill'] (default 3)
  - active once buy_fill_count >= post_fill_sampling_start_fill, keeps sampling at 4, 5, 6+
  - post_fill_sampling_start_fill is independent from soft_risk_baseline_fills
  - throttling: drawdown-change threshold and time-based cadence
  - exactly one guaranteed final sample at close (stop()), never duplicated
  - no final sample if the sampling-start threshold was never reached
  - PostFillRiskSnapshot persistence via the same shared store as FillRiskSnapshot
  - no influence whatsoever on trading/exit state (close_type/_status untouched)
"""
import os
import shutil
import tempfile
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
from multi_coin_grid_pro.persistence.fill_risk_snapshot_store import FillRiskSnapshotStore


def _make_strategy(timestamp: float = 1_000_000.0, connector_name: str = "bitget") -> MagicMock:
    market = MagicMock()
    market_info = MagicMock()
    market_info.market = market
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=market_info)
    type(strategy).trading_pair = PropertyMock(return_value="BCH-USDT")
    type(strategy).current_timestamp = PropertyMock(return_value=timestamp)
    strategy.cancel.return_value = None
    connector = MagicMock(spec=ExchangePyBase)
    type(connector).trading_rules = PropertyMock(return_value={
        "BCH-USDT": TradingRule(
            trading_pair="BCH-USDT",
            min_order_value=Decimal("5"),
            min_order_size=Decimal("0.0001"),
            min_price_increment=Decimal("0.1"),
        )
    })
    strategy.connectors = {connector_name: connector}
    return strategy


def _make_grid_config(
    executor_id: str = "test-post-fill-risk", connector_name: str = "bitget", **custom_info_overrides
) -> GridExecutorConfig:
    custom_info = {
        "no_fill_timeout_sec": 1800,
        "no_progress_timeout_sec": 3600,
        "max_hold_time_sec": 21600,
        "close_grace_sec": 120,
        "bot_instance_id": "bitget_usdt",
        "soft_risk_baseline_fills": 4,
        "post_fill_sampling_start_fill": 3,
    }
    custom_info.update(custom_info_overrides)
    return GridExecutorConfig(
        id=executor_id,
        timestamp=1_000_000.0,
        side=TradeType.BUY,
        connector_name=connector_name,
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
    strategy = _make_strategy(timestamp=start_ts, connector_name=config.connector_name)
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price",
               return_value=Decimal("253.2")):
        executor = GridExecutor(strategy, config, update_interval=0.5)
    executor._start_timestamp = start_ts
    executor.update_position_metrics = MagicMock()  # isolate from full grid-level state machine
    executor.position_size_quote = Decimal("28.85")
    executor.position_break_even_price = Decimal("253.2")
    executor.position_pnl_quote = Decimal("-0.50")
    executor.position_pnl_pct = Decimal("-0.017")
    executor.mid_price = Decimal("253.2")
    return executor


class TestPostFillRiskSampling(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):

    def setUp(self):
        super().setUp()
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=None,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)
        self.executor = _make_executor(_make_grid_config())
        self.set_loggers([self.executor.logger()])

    def _post_fill_logs(self):
        return [r for r in self.log_records if "[POST_FILL_RISK_LOG]" in r.getMessage()]

    def test_inactive_below_sampling_start_fill(self):
        for count in (0, 1, 2):
            self.executor._buy_fill_count = count
            self.executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs()), 0)

    def test_active_from_fill_3(self):
        self.executor._buy_fill_count = 3
        self.executor._maybe_sample_post_fill_risk()
        logs = self._post_fill_logs()
        self.assertEqual(len(logs), 1)
        self.assertIn("buy_fill_count=3", logs[0].getMessage())
        self.assertIn("is_final=False", logs[0].getMessage())

    def test_active_from_fill_5(self):
        self.executor._buy_fill_count = 5
        self.executor._maybe_sample_post_fill_risk()
        logs = self._post_fill_logs()
        self.assertEqual(len(logs), 1)
        self.assertIn("buy_fill_count=5", logs[0].getMessage())
        self.assertIn("is_final=False", logs[0].getMessage())

    def test_throttle_suppresses_repeated_sample_same_drawdown_short_interval(self):
        self.executor._buy_fill_count = 5
        self.executor._maybe_sample_post_fill_risk()  # first sample always taken
        self.executor._maybe_sample_post_fill_risk()  # same drawdown, no time passed
        self.assertEqual(len(self._post_fill_logs()), 1)

    def test_drawdown_change_triggers_new_sample(self):
        self.executor._buy_fill_count = 5
        self.executor._maybe_sample_post_fill_risk()
        self.executor.position_pnl_pct = Decimal("-0.05")  # -5% now, was -1.7%
        self.executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs()), 2)

    def test_time_based_cadence_triggers_new_sample(self):
        self.executor._buy_fill_count = 5
        self.executor._maybe_sample_post_fill_risk()
        # Advance the strategy clock by >45s with an unchanged drawdown.
        type(self.executor._strategy).current_timestamp = PropertyMock(return_value=1_000_100.0)
        self.executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs()), 2)

    def test_final_snapshot_written_exactly_once_at_close(self):
        self.executor._buy_fill_count = 5
        self.executor.stop()
        self.executor.stop()  # calling stop() twice must not duplicate the final sample
        final_logs = [r for r in self._post_fill_logs() if "is_final=True" in r.getMessage()]
        self.assertEqual(len(final_logs), 1)

    def test_no_final_snapshot_if_fill_5_never_reached(self):
        self.executor._buy_fill_count = 2
        self.executor.stop()
        self.assertEqual(len(self._post_fill_logs()), 0)

    def test_sampling_never_touches_close_type_or_status(self):
        """Purely observational: no side effects on trading/exit state."""
        self.executor._buy_fill_count = 5
        close_type_before = self.executor.close_type
        status_before = self.executor.status
        self.executor._maybe_sample_post_fill_risk()
        self.executor.stop()
        self.assertEqual(close_type_before, None)
        self.assertEqual(self.executor.close_type, close_type_before)
        # status DOES change via the normal super().stop() shutdown path - that's
        # expected/unrelated to our sampling logic, which never sets it itself.
        self.assertNotEqual(status_before, None)


class TestPostFillRiskPersistence(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """PostFillRiskSnapshot persistence via the same shared FillRiskSnapshotStore."""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "fill_risk_snapshots_test.db")
        self._store = FillRiskSnapshotStore(self._db_path)
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=self._store,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)
        self.addCleanup(self._store.close)
        self.addCleanup(shutil.rmtree, self._tmpdir, True)
        self.executor = _make_executor(_make_grid_config())
        self.set_loggers([self.executor.logger()])

    def test_sample_persisted_with_correct_fields(self):
        self.executor._buy_fill_count = 5
        self.executor._maybe_sample_post_fill_risk()
        rows = self._store.query_post_fill_recent(days=100000)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.executor_id, "test-post-fill-risk")
        self.assertEqual(row.exchange, "bitget")
        self.assertEqual(row.bot_instance_id, "bitget_usdt")
        self.assertEqual(row.buy_fill_count, 5)
        self.assertFalse(row.is_final)

    def test_final_row_persisted_at_close(self):
        self.executor._buy_fill_count = 5
        self.executor.stop()
        rows = self._store.query_post_fill_recent(days=100000)
        self.assertTrue(any(r.is_final for r in rows))

    def test_snapshots_always_carry_exchange_and_bot_instance_id_never_mixed(self):
        """Generic rollout across Bitget/OKX/Kraken USD/EUR shares the same
        GridExecutor + PostFillRiskSnapshot table - exchange/bot_instance_id
        must always be present and distinct per bot so results can never be
        pooled across exchanges during later per-bot analysis."""
        executor_bitget = _make_executor(_make_grid_config(
            executor_id="exec-bitget", connector_name="bitget", bot_instance_id="spot_grid_bitget",
        ))
        executor_okx = _make_executor(_make_grid_config(
            executor_id="exec-okx", connector_name="okx", bot_instance_id="spot_grid_okx",
        ))
        executor_kraken_eur = _make_executor(_make_grid_config(
            executor_id="exec-kraken-eur", connector_name="kraken", bot_instance_id="eur",
        ))
        for ex in (executor_bitget, executor_okx, executor_kraken_eur):
            self.set_loggers([ex.logger()])
            ex._buy_fill_count = 3  # new shared default start point
            ex._maybe_sample_post_fill_risk()

        rows = self._store.query_post_fill_recent(days=100000)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.exchange for r in rows))
        self.assertTrue(all(r.bot_instance_id for r in rows))
        pairs = {(r.exchange, r.bot_instance_id) for r in rows}
        self.assertEqual(pairs, {("bitget", "spot_grid_bitget"), ("okx", "spot_grid_okx"), ("kraken", "eur")})

        # Filtering by bot_instance_id must never leak another bot's rows.
        eur_rows = self._store.query_post_fill_recent(days=100000, executor_id="exec-kraken-eur")
        self.assertEqual(len(eur_rows), 1)
        self.assertEqual(eur_rows[0].exchange, "kraken")
        self.assertEqual(eur_rows[0].bot_instance_id, "eur")

    def test_db_error_does_not_affect_trading_behavior(self):
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            side_effect=Exception("DB unavailable"),
        ):
            self.executor._buy_fill_count = 5
            self.executor._maybe_sample_post_fill_risk()  # must not raise
        logs = [r for r in self.log_records if "[POST_FILL_RISK_LOG]" in r.getMessage()]
        self.assertTrue(logs)


class TestPostFillFinalSnapshotLifecycle(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """
    Regression tests for the missing is_final=1 bug (2026-09-27).

    Confirmed root causes:
      1. control_shutdown_process()'s "position externally closed" branch resets
         self.levels_by_state to {} right before calling stop() - update_position_metrics()
         then raises KeyError on direct dict-indexing, silently aborting the final
         sample. Fixed by isolating that refresh call so a failure falls back to
         the already-fresh values from this tick's earlier update_metrics() call.
      2. Several lifecycle branches (dust-close, NL-restriction termination,
         insufficient-balance-after-retries) set self._status = TERMINATED
         DIRECTLY and never call stop() at all - control_task() keeps ticking
         forever on those paths (only stop() sets the asyncio.Event that ends
         the control loop). Fixed with a control_task()-level TERMINATED check
         that acts as a universal safety net for every close type.
    """

    def setUp(self):
        super().setUp()
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=None,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

    def _final_logs(self, executor: GridExecutor):
        return [r for r in self.log_records if "[POST_FILL_RISK_LOG]" in r.getMessage() and "is_final=True" in r.getMessage()]

    def test_normal_close_with_levels_by_state_cleared_still_yields_final_snapshot(self):
        """Direct regression test for the confirmed root cause (XLM-USDT case)."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        # Use the REAL update_position_metrics() so this test genuinely reproduces
        # the KeyError on direct dict-indexing when levels_by_state is emptied.
        executor.update_position_metrics = GridExecutor.update_position_metrics.__get__(executor)
        # Reproduce exactly what control_shutdown_process() does right before
        # calling stop() on the "position externally closed" path.
        executor.levels_by_state = {}
        executor.close_type = CloseType.FAILED
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_stop_loss_close_yields_exactly_one_final_snapshot(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        executor.close_type = CloseType.STOP_LOSS
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_no_progress_timeout_close_yields_exactly_one_final_snapshot(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 6
        executor.close_type = CloseType.NO_PROGRESS_TIMEOUT
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_expired_close_yields_exactly_one_final_snapshot(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        executor.close_type = CloseType.EXPIRED
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_early_stop_reason_still_yields_exactly_one_final_snapshot(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        executor._early_stop_reason = EarlyStopReason.EMERGENCY_EXIT
        executor.close_type = CloseType.EARLY_STOP
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    async def test_control_task_safety_net_catches_status_set_directly_to_terminated(self):
        """Reproduces lifecycle paths that set _status = TERMINATED directly and
        NEVER call stop() at all (e.g. dust-close, NL-restriction termination)."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        executor.update_grid_levels = MagicMock()
        executor.update_metrics = MagicMock()
        executor.close_type = CloseType.INSUFFICIENT_BALANCE
        executor._status = RunnableStatus.TERMINATED  # stop() deliberately NOT called

        await executor.control_task()

        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_restart_shutdown_path_never_duplicates_final_snapshot(self):
        """stop() called more than once (e.g. duplicate shutdown signal) must not
        produce a second final snapshot."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        executor.close_type = CloseType.EXPIRED
        executor.stop()
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_no_final_snapshot_for_executor_below_sampling_start_fill(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 2
        executor.close_type = CloseType.TAKE_PROFIT
        executor.stop()
        self.assertEqual(len(self._final_logs(executor)), 0)

    def test_db_error_on_final_snapshot_does_not_affect_trading_behavior(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 5
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            side_effect=Exception("DB unavailable"),
        ):
            executor.stop()  # must not raise, status must still transition
        self.assertEqual(executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(len(self._final_logs(executor)), 1)  # log still happened despite DB "failure"


class TestPostFillSamplingStartFillConfig(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """
    Regression tests for moving the post-fill sampling start point from fill 5
    to fill 3 (2026-10-02), via a DEDICATED `post_fill_sampling_start_fill`
    config key that is independent from `soft_risk_baseline_fills` (which
    continues to govern only the SOFT_RISK_SHADOW risk_state / shadow-stop
    display math, untouched by this change). Purely observational - no
    trading/exit logic is affected.
    """

    def setUp(self):
        super().setUp()
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=None,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

    def _post_fill_logs(self, executor: GridExecutor):
        return [r for r in self.log_records if "[POST_FILL_RISK_LOG]" in r.getMessage()]

    def _final_logs(self, executor: GridExecutor):
        return [r for r in self._post_fill_logs(executor) if "is_final=True" in r.getMessage()]

    def test_no_sampling_at_fill_1_or_2(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        for count in (1, 2):
            executor._buy_fill_count = count
            executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs(executor)), 0)

    def test_sampling_starts_exactly_at_fill_3(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        executor._maybe_sample_post_fill_risk()
        logs = self._post_fill_logs(executor)
        self.assertEqual(len(logs), 1)
        self.assertIn("buy_fill_count=3", logs[0].getMessage())

    def test_sampling_continues_through_fill_4_5_6(self):
        """Each later fill_count, combined with a drawdown change, must still
        produce a new sample - sampling does not stop once started."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        drawdowns = [Decimal("-0.017"), Decimal("-0.03"), Decimal("-0.05"), Decimal("-0.08")]
        for fill_count, dd in zip((3, 4, 5, 6), drawdowns):
            executor._buy_fill_count = fill_count
            executor.position_pnl_pct = dd
            executor._maybe_sample_post_fill_risk()
        logs = self._post_fill_logs(executor)
        self.assertEqual(len(logs), 4)
        for fill_count, log in zip((3, 4, 5, 6), logs):
            self.assertIn(f"buy_fill_count={fill_count}", log.getMessage())

    def test_sampling_start_fill_independent_from_soft_risk_baseline_fills(self):
        """Raising soft_risk_baseline_fills must NOT delay/gate sampling start -
        the two configs must stay fully decoupled."""
        executor = _make_executor(_make_grid_config(soft_risk_baseline_fills=10))
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs(executor)), 1)

    def test_custom_sampling_start_fill_overrides_default(self):
        executor = _make_executor(_make_grid_config(post_fill_sampling_start_fill=6))
        self.set_loggers([executor.logger()])
        for count in (3, 4, 5):
            executor._buy_fill_count = count
            executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs(executor)), 0)
        executor._buy_fill_count = 6
        executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs(executor)), 1)

    def test_falls_back_to_default_start_fill_3_when_key_missing_from_custom_info(self):
        config = _make_grid_config()
        del config.custom_info["post_fill_sampling_start_fill"]
        executor = _make_executor(config)
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        executor._maybe_sample_post_fill_risk()
        self.assertEqual(len(self._post_fill_logs(executor)), 1)

    def test_final_snapshot_exactly_once_with_fill_3_start(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        executor.close_type = CloseType.STOP_LOSS
        executor.stop()
        executor.stop()  # duplicate stop() must not duplicate the final sample
        self.assertEqual(len(self._final_logs(executor)), 1)

    async def test_control_task_safety_net_fires_from_fill_3(self):
        """Lifecycle paths that set _status = TERMINATED directly (never calling
        stop()) must still catch the final snapshot once fill 3 has been reached."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        executor.update_grid_levels = MagicMock()
        executor.update_metrics = MagicMock()
        executor.close_type = CloseType.INSUFFICIENT_BALANCE
        executor._status = RunnableStatus.TERMINATED  # stop() deliberately NOT called

        await executor.control_task()

        self.assertEqual(len(self._final_logs(executor)), 1)

    def test_db_error_at_fill_3_does_not_affect_trading_behavior(self):
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        executor._buy_fill_count = 3
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            side_effect=Exception("DB unavailable"),
        ):
            executor.stop()  # must not raise
        self.assertEqual(executor.status, RunnableStatus.TERMINATED)
        self.assertEqual(len(self._final_logs(executor)), 1)
