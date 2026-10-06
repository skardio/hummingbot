"""
Tests for FASE 1A/1B: soft-risk shadow-mode fill tracking + SQLite persistence
(2026-09-12/13).

Pure logging/data-collection feature - must NEVER change trading behavior.
Covers:
  - buy_fill_count only increments on FILLED BUY orders (not SELL/cancel/fail)
  - duplicate BuyOrderCompletedEvent for the same order_id is not double-counted
  - shadow risk_state is NONE for fill 1-4, SOFT_RISK_SHADOW from fill 5 onward
  - soft_risk_shadow_logging_enabled=False is a full no-op (no log emitted)
  - existing STOP_LOSS/TIME_STOP/NO_PROGRESS/TRAILING/close-race behavior is untouched
  - FillRiskSnapshot persistence: insert, dedup, multi-exchange, fail-safe on DB error
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
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.events import BuyOrderCompletedEvent, SellOrderCompletedEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevel, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import TrackedOrder
from multi_coin_grid_pro.persistence.fill_risk_snapshot_store import FillRiskSnapshot, FillRiskSnapshotStore


def _make_strategy(timestamp: float = 1_000_000.0, connector_name: str = "bitget") -> MagicMock:
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
    strategy.connectors = {connector_name: connector}
    return strategy


def _make_grid_config(
    connector_name: str = "bitget", executor_id: str = "test-fill-risk-shadow", **custom_info_overrides
) -> GridExecutorConfig:
    custom_info = {
        "no_fill_timeout_sec": 1800,
        "no_progress_timeout_sec": 3600,
        "max_hold_time_sec": 21600,
        "close_grace_sec": 120,
        "atr_pct": 0.02,
        "entry_trend_score": 0.55,
        "bot_instance_id": "bitget_usdt",
        "soft_risk_baseline_fills": 4,
        "soft_risk_state_enabled": False,
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


def _make_executor(
    config: GridExecutorConfig, start_ts: float = 1_000_000.0, connector_name: str = "bitget"
) -> GridExecutor:
    strategy = _make_strategy(timestamp=start_ts, connector_name=connector_name)
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price",
               return_value=Decimal("253.2")):
        executor = GridExecutor(strategy, config, update_interval=0.5)
    executor._start_timestamp = start_ts
    # Isolate the fill-tracking/logging logic from the full grid-level state machine.
    executor.update_tracked_orders_with_order_id = MagicMock()
    executor.update_position_metrics = MagicMock()
    # Ownership filtering is tested explicitly in TestFillEventOwnership below -
    # default to "always own" here so the other test classes keep testing
    # counting/logging/dedup behavior in isolation, unaffected by the fix.
    executor._order_belongs_to_this_executor = MagicMock(return_value=True)
    executor.position_size_quote = Decimal("28.85")
    executor.position_break_even_price = Decimal("253.2")
    executor.position_pnl_quote = Decimal("-0.50")
    executor.position_pnl_pct = Decimal("-0.017")
    executor.mid_price = Decimal("253.2")
    return executor


def _buy_event(order_id: str) -> BuyOrderCompletedEvent:
    return BuyOrderCompletedEvent(
        timestamp=1_000_100.0,
        order_id=order_id,
        base_asset="BCH",
        quote_asset="USDT",
        base_asset_amount=Decimal("0.1"),
        quote_asset_amount=Decimal("25.32"),
        order_type=OrderType.LIMIT,
    )


def _sell_event(order_id: str) -> SellOrderCompletedEvent:
    return SellOrderCompletedEvent(
        timestamp=1_000_100.0,
        order_id=order_id,
        base_asset="BCH",
        quote_asset="USDT",
        base_asset_amount=Decimal("0.1"),
        quote_asset_amount=Decimal("25.32"),
        order_type=OrderType.LIMIT,
    )


class TestFillRiskShadowMode(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):

    def setUp(self):
        super().setUp()
        # Isolate these tests from the real fill-risk DB - persistence is
        # covered separately in TestFillRiskSnapshotPersistence below.
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=None,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)
        self.executor = _make_executor(_make_grid_config())
        self.set_loggers([self.executor.logger()])

    def test_buy_fills_increment_counter(self):
        for i in range(1, 5):
            self.executor.process_order_completed_event(None, None, _buy_event(f"buy-{i}"))
            self.assertEqual(self.executor.buy_fill_count, i)

    def test_sell_fill_does_not_increment_counter(self):
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        self.executor.process_order_completed_event(None, None, _sell_event("sell-1"))
        self.assertEqual(self.executor.buy_fill_count, 1)

    def test_duplicate_buy_event_not_double_counted(self):
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        self.assertEqual(self.executor.buy_fill_count, 1)

    def test_shadow_state_none_for_fill_1_to_4(self):
        for i in range(1, 5):
            self.executor.process_order_completed_event(None, None, _buy_event(f"buy-{i}"))
        self._assert_last_log_contains("risk_state=NONE")

    def test_shadow_state_soft_risk_from_fill_5(self):
        for i in range(1, 6):
            self.executor.process_order_completed_event(None, None, _buy_event(f"buy-{i}"))
        self._assert_last_log_contains("risk_state=SOFT_RISK_SHADOW")
        self._assert_last_log_contains("fill_number=5")

    def test_logging_disabled_flag_emits_no_log(self):
        executor = _make_executor(_make_grid_config(soft_risk_shadow_logging_enabled=False))
        self.set_loggers([executor.logger()])
        executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertEqual(len(fill_risk_logs), 0)
        # Counter itself is unconditional bookkeeping - no behavior change either way.
        self.assertEqual(executor.buy_fill_count, 1)

    def test_soft_risk_state_enabled_flag_defaults_false_and_is_logged_but_not_enforced(self):
        for i in range(1, 6):
            self.executor.process_order_completed_event(None, None, _buy_event(f"buy-{i}"))
        self._assert_last_log_contains("soft_risk_state_enabled=False")
        # No new exit path exists yet - close_type must remain untouched by shadow logging.
        self.assertIsNone(self.executor.close_type)

    def test_unrealized_drawdown_pct_negative_for_real_losing_position(self):
        """Drives the REAL update_position_metrics() (not mocked) with
        avg entry=100, current price=97 -> expects position_pnl_pct ~= -3%
        and unrealized_drawdown_pct to carry that same negative sign
        (convention: negative = drawdown, 0.0 when not underwater - see
        _log_fill_risk_shadow docstring)."""
        executor = _make_executor(_make_grid_config())
        self.set_loggers([executor.logger()])
        # Undo the setUp/_make_executor mock so update_position_metrics runs for real.
        executor.update_position_metrics = GridExecutor.update_position_metrics.__get__(executor)

        level = GridLevel(
            id="L1", price=Decimal("100"), amount_quote=Decimal("100"),
            take_profit=Decimal("0.02"), side=TradeType.BUY,
            open_order_type=OrderType.LIMIT, take_profit_order_type=OrderType.LIMIT,
        )
        fake_order = MagicMock()
        fake_order.amount = Decimal("1")
        fake_order.price = Decimal("100")
        fake_order.cumulative_fee_paid.return_value = Decimal("0")
        tracked = TrackedOrder(order_id="buy-1")
        tracked.order = fake_order
        level.active_open_order = tracked
        executor.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED] = [level]
        executor.mid_price = Decimal("97")

        executor.process_order_completed_event(None, None, _buy_event("buy-1"))

        self.assertAlmostEqual(float(executor.position_pnl_pct), -0.03, places=6)
        self._assert_last_log_contains_for(executor, "unrealized_drawdown_pct=-3.000")

    def _assert_last_log_contains_for(self, executor: GridExecutor, substring: str) -> None:
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertTrue(fill_risk_logs, "Expected at least one [FILL_RISK_LOG] entry")
        self.assertIn(substring, fill_risk_logs[-1].getMessage())

    def _assert_last_log_contains(self, substring: str) -> None:
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertTrue(fill_risk_logs, "Expected at least one [FILL_RISK_LOG] entry")
        self.assertIn(substring, fill_risk_logs[-1].getMessage())


class TestFillRiskSnapshotPersistence(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """FASE 1B: persistence of FILL_RISK_LOG data into FillRiskSnapshot (SQLite)."""

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
        self.executor = _make_executor(_make_grid_config(bot_instance_id="bitget_usdt"))
        self.set_loggers([self.executor.logger()])

    def test_insert_creates_one_row(self):
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        rows = self._store.query_recent(days=100000)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].executor_id, "test-fill-risk-shadow")
        self.assertEqual(rows[0].fill_number, 1)
        self.assertEqual(rows[0].bot_instance_id, "bitget_usdt")
        self.assertEqual(rows[0].exchange, "bitget")
        self.assertEqual(rows[0].quote_currency, "USDT")

    def test_duplicate_fill_event_not_double_inserted(self):
        """Same order_id delivered twice must not double-count buy_fill_count
        (already covered elsewhere) NOR create a second DB row for the same
        (executor_id, fill_number)."""
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        rows = self._store.query_recent(days=100000)
        self.assertEqual(len(rows), 1)

    def test_same_executor_id_fill_number_not_double_inserted_even_from_two_events(self):
        """Direct dedup-key test: two DIFFERENT order_ids that (hypothetically)
        map to the same fill_number for the same executor_id must still only
        produce one row (UNIQUE(executor_id, fill_number))."""
        snap = FillRiskSnapshot(
            executor_id="exec-1", exchange="bitget", quote_currency="USDT",
            bot_instance_id="bitget_usdt", trading_pair="BCH-USDT", fill_number=1,
            timestamp=1.0, fill_price=100.0, fill_amount_base=1.0, fill_amount_quote=100.0,
            avg_entry_price=100.0, position_size_quote=100.0, unrealized_pnl_quote=0.0,
            unrealized_drawdown_pct=0.0, current_price=100.0, entry_atr_pct=0.02,
            entry_trend_score=0.5, effective_stop_pct=0.05, risk_state="NONE",
        )
        self._store.record(snap)
        self._store.record(snap)
        rows = self._store.query_recent(days=100000)
        self.assertEqual(len(rows), 1)

    def test_multiple_exchanges_and_instances_in_same_db(self):
        executor_bitget = _make_executor(
            _make_grid_config(connector_name="bitget", executor_id="exec-bitget", bot_instance_id="bitget_usdt"),
            connector_name="bitget",
        )
        executor_okx = _make_executor(
            _make_grid_config(connector_name="okx", executor_id="exec-okx", bot_instance_id="okx_usdc"),
            connector_name="okx",
        )
        for ex in (executor_bitget, executor_okx):
            self.set_loggers([ex.logger()])
        executor_bitget.process_order_completed_event(None, None, _buy_event("bitget-buy-1"))
        executor_okx.process_order_completed_event(None, None, _buy_event("okx-buy-1"))

        all_rows = self._store.query_recent(days=100000)
        self.assertEqual(len(all_rows), 2)
        bots = {r.bot_instance_id for r in all_rows}
        self.assertEqual(bots, {"bitget_usdt", "okx_usdc"})

        bitget_rows = self._store.query_recent(days=100000, bot_instance_id="bitget_usdt")
        self.assertEqual(len(bitget_rows), 1)
        self.assertEqual(bitget_rows[0].exchange, "bitget")

    def test_db_error_does_not_affect_trading_behavior(self):
        """A broken/unavailable store must never raise into process_order_completed_event."""
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            side_effect=Exception("DB unavailable"),
        ):
            # Must not raise - the surrounding try/except must swallow it.
            self.executor.process_order_completed_event(None, None, _buy_event("buy-1"))
        self.assertEqual(self.executor.buy_fill_count, 1)
        # Logging still happened despite the DB "failure".
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertTrue(fill_risk_logs)


class TestFillEventOwnership(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """
    FASE 1B FIX (2026-09-19): register_events() subscribes every executor to the
    FULL connector-wide event stream, so process_order_completed_event() also
    receives BuyOrderCompletedEvents belonging to OTHER executors on the same
    connector. Only order_id's matching this executor's own tracked orders
    (grid level open/close orders or the executor-level close order) may be
    counted/logged/persisted.
    """

    def setUp(self):
        super().setUp()
        self._store_patcher = patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor._get_fill_risk_store",
            return_value=None,
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

    def _make_owned_executor(
        self, executor_id: str = "test-fill-risk-shadow", own_order_id: str = "own-buy-1"
    ) -> GridExecutor:
        executor = _make_executor(_make_grid_config(executor_id=executor_id))
        # Use the REAL ownership check (undo the "always own" test-isolation
        # default from _make_executor(), used by the other test classes above).
        executor._order_belongs_to_this_executor = GridExecutor._order_belongs_to_this_executor.__get__(executor)
        level = GridLevel(
            id="L1", price=Decimal("100"), amount_quote=Decimal("100"),
            take_profit=Decimal("0.02"), side=TradeType.BUY,
            open_order_type=OrderType.LIMIT, take_profit_order_type=OrderType.LIMIT,
        )
        level.active_open_order = TrackedOrder(order_id=own_order_id)
        executor.grid_levels = [level]
        self.set_loggers([executor.logger()])
        return executor

    def test_own_buy_order_completed_increments_and_logs(self):
        executor = self._make_owned_executor()
        executor.process_order_completed_event(None, None, _buy_event("own-buy-1"))
        self.assertEqual(executor.buy_fill_count, 1)
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertEqual(len(fill_risk_logs), 1)

    def test_foreign_buy_event_is_ignored(self):
        executor = self._make_owned_executor()
        executor.process_order_completed_event(None, None, _buy_event("foreign-order-99"))
        self.assertEqual(executor.buy_fill_count, 0)
        fill_risk_logs = [r for r in self.log_records if "[FILL_RISK_LOG]" in r.getMessage()]
        self.assertEqual(len(fill_risk_logs), 0)

    def test_two_executors_same_connector_fill_only_registered_by_owner(self):
        """Simulates register_events() delivering the SAME connector-wide event
        to two simultaneously active executors on the same connector."""
        executor_a = self._make_owned_executor(executor_id="exec-a", own_order_id="own-buy-1")
        executor_b = self._make_owned_executor(executor_id="exec-b", own_order_id="own-buy-1-b")

        event_from_a = _buy_event("own-buy-1")
        executor_a.process_order_completed_event(None, None, event_from_a)
        executor_b.process_order_completed_event(None, None, event_from_a)  # foreign to B

        self.assertEqual(executor_a.buy_fill_count, 1)
        self.assertEqual(executor_b.buy_fill_count, 0)

    def test_duplicate_own_event_still_deduped(self):
        executor = self._make_owned_executor()
        executor.process_order_completed_event(None, None, _buy_event("own-buy-1"))
        executor.process_order_completed_event(None, None, _buy_event("own-buy-1"))
        self.assertEqual(executor.buy_fill_count, 1)

    def test_sell_event_never_counted_even_if_it_matches_own_close_order(self):
        executor = self._make_owned_executor()
        executor._close_order = TrackedOrder(order_id="own-close-1")
        executor.process_order_completed_event(None, None, _sell_event("own-close-1"))
        self.assertEqual(executor.buy_fill_count, 0)
