"""
CA1 / CA2 / CA5 Verification Tests
====================================

CA1: session_blacklist stores expiry_time semantics (not a 'blacklisted_at' start
     timestamp).  Proves the fix that was already in the codebase is correct.

CA2: _sync_risk_state() fires _add_to_blacklist() exactly at the
     max_streak_before_blacklist threshold and resets the streak afterwards.

CA5: _sync_risk_state() calls GlobalRiskManager.register_close_trade() exactly
     once per executor close, with correct symbol, pnl and exit_type mapping.
     Calling _sync_risk_state() a second time with the same executor id is a
     no-op (idempotency guaranteed by _realised_executors_tracked).
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _make_controller(config_kwargs=None):
    """Return a MultiCoinGridController with _initialize_components patched out."""
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    cfg_defaults = dict(
        connector_name="kraken",
        quote_asset="USD",
    )
    if config_kwargs:
        cfg_defaults.update(config_kwargs)
    config = MultiCoinGridConfig(**cfg_defaults)

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = 1000.0
    market_data_provider.ready = True

    with patch.object(MultiCoinGridController, '_initialize_components'):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=market_data_provider,
            actions_queue=MagicMock(),
            connectors={"kraken": MagicMock()},
        )
    return controller


def _make_executor(exec_id, pnl, close_type=CloseType.STOP_LOSS, symbol="XRP-USD"):
    """Return a minimal executor mock for use in _sync_risk_state()."""
    executor = MagicMock()
    executor.id = exec_id
    executor.status = RunnableStatus.TERMINATED
    executor.is_active = False
    executor.close_type = close_type
    executor.net_pnl_quote = pnl
    executor.cum_fees_quote = Decimal("0.1")
    executor.config.trading_pair = symbol
    executor.custom_info = {}
    return executor


def _call_sync(controller):
    """Call _sync_risk_state() with the two blocking side-effects patched out."""
    with patch(
        "multi_coin_grid_pro.controllers.multi_coin_grid_controller"
        ".position_tracking_cleanup_allowed",
        return_value=False,
    ), patch.object(controller, "_check_professional_exit_signals"):
        controller._sync_risk_state()


# ---------------------------------------------------------------------------
# CA1: session_blacklist expiry semantics
# ---------------------------------------------------------------------------

class TestCA1BlacklistExpiry(unittest.TestCase):
    """CA1: stored timestamp in session_blacklist is the *expiry* time, not start."""

    def setUp(self):
        self.controller = _make_controller()
        self.now = 1000.0

    # --- core semantic test ---------------------------------------------------

    def test_stored_value_is_expiry_not_start(self):
        """The value stored for a symbol must equal now + duration, not now."""
        self.controller._add_to_blacklist("XRP-USD", "TEST", self.now, duration_override=60)
        stored = self.controller.session_blacklist["XRP-USD"]
        # Must be the future expiry timestamp
        self.assertAlmostEqual(stored, self.now + 60, delta=1)
        # Must NOT be the start time
        self.assertNotAlmostEqual(stored, self.now, delta=1)

    # --- _is_blacklisted uses the value correctly ----------------------------

    def test_blocked_before_expiry(self):
        self.controller._add_to_blacklist("XRP-USD", "TEST", self.now, duration_override=60)
        self.assertTrue(self.controller._is_blacklisted("XRP-USD", self.now + 30))

    def test_released_exactly_at_expiry(self):
        self.controller._add_to_blacklist("XRP-USD", "TEST", self.now, duration_override=60)
        # At exact expiry: should be released (>= semantics)
        self.assertFalse(self.controller._is_blacklisted("XRP-USD", self.now + 60))

    def test_released_after_expiry(self):
        self.controller._add_to_blacklist("XRP-USD", "TEST", self.now, duration_override=60)
        self.assertFalse(self.controller._is_blacklisted("XRP-USD", self.now + 61))

    # --- purge uses the value correctly --------------------------------------

    def test_purge_removes_expired_keeps_active(self):
        self.controller._add_to_blacklist("XRP-USD", "T1", self.now, duration_override=60)
        self.controller._add_to_blacklist("BTC-USD", "T2", self.now, duration_override=3600)
        # 2 minutes later: XRP expired, BTC still valid
        self.controller._purge_expired_blacklist(self.now + 120)
        self.assertNotIn("XRP-USD", self.controller.session_blacklist)
        self.assertIn("BTC-USD", self.controller.session_blacklist)


# ---------------------------------------------------------------------------
# CA2: loss streak → blacklist at threshold
# ---------------------------------------------------------------------------

class TestCA2LossStreakBlacklist(unittest.TestCase):
    """CA2: _sync_risk_state() blacklists a coin when streak >= max_streak_before_blacklist."""

    def setUp(self):
        self.controller = _make_controller()
        # Ensure a clean slate for each test
        self.controller._realised_executors_tracked = {}
        self.controller._loss_streaks = {}
        self.controller.session_blacklist = {}
        # Override active_coin so the unrealised update at end is skipped
        self.controller.active_coin = None
        self.controller.active_executor_id = None

    def _run(self, executor):
        # Pre-register in STORY A2's idempotency set so that STORY A2 blacklisting
        # is skipped — we are only testing the Phase 1 loss-streak path here.
        self.controller._processed_timeout_executors.add(executor.id)
        self.controller.executors_info = [executor]
        _call_sync(self.controller)

    # -------------------------------------------------------------------------

    def test_first_loss_increments_streak_no_blacklist(self):
        """One loss below threshold → streak == 1, no blacklist."""
        self.controller.config.close_cooldowns = {"max_streak_before_blacklist": 3}
        self._run(_make_executor("e1", Decimal("-5.0")))
        self.assertEqual(self.controller._loss_streaks.get("XRP-USD", 0), 1)
        self.assertNotIn("XRP-USD", self.controller.session_blacklist)

    def test_second_loss_triggers_blacklist_at_threshold_two(self):
        """Two losses with max_streak=2 → blacklisted, streak reset to 0."""
        self.controller.config.close_cooldowns = {
            "max_streak_before_blacklist": 2,
            "loss_streak_blacklist_sec": 3600,
        }
        self._run(_make_executor("e1", Decimal("-5.0")))
        self._run(_make_executor("e2", Decimal("-3.0")))
        self.assertIn("XRP-USD", self.controller.session_blacklist)
        self.assertEqual(self.controller._loss_streaks.get("XRP-USD", 0), 0)

    def test_win_resets_streak_to_zero(self):
        """A profitable close resets the streak regardless of current count."""
        self.controller.config.close_cooldowns = {"max_streak_before_blacklist": 5}
        self._run(_make_executor("e1", Decimal("-5.0")))
        self.assertEqual(self.controller._loss_streaks.get("XRP-USD", 0), 1)
        self._run(_make_executor("e2", Decimal("+2.0"), close_type=CloseType.TAKE_PROFIT))
        self.assertEqual(self.controller._loss_streaks.get("XRP-USD", 0), 0)

    def test_blacklisted_at_threshold_expiry_is_in_future(self):
        """After blacklisting, the stored timestamp must be a *future* expiry."""
        self.controller.config.close_cooldowns = {
            "max_streak_before_blacklist": 2,
            "loss_streak_blacklist_sec": 3600,
        }
        self._run(_make_executor("e1", Decimal("-5.0")))
        self._run(_make_executor("e2", Decimal("-3.0")))
        now = self.controller.market_data_provider.time()
        stored_ts = self.controller.session_blacklist["XRP-USD"]
        # Stored value is expiry → must be strictly greater than now
        self.assertGreater(stored_ts, now)

    def test_streak_not_incremented_for_different_symbol(self):
        """Losses on different symbols track independently."""
        self.controller.config.close_cooldowns = {"max_streak_before_blacklist": 5}
        xrp = _make_executor("e1", Decimal("-5.0"), symbol="XRP-USD")
        btc = _make_executor("e2", Decimal("-5.0"), symbol="BTC-USD")
        self._run(xrp)
        self._run(btc)
        self.assertEqual(self.controller._loss_streaks.get("XRP-USD", 0), 1)
        self.assertEqual(self.controller._loss_streaks.get("BTC-USD", 0), 1)


# ---------------------------------------------------------------------------
# CA5: register_close_trade() called in _sync_risk_state()
# ---------------------------------------------------------------------------

class TestCA5RegisterCloseTrade(unittest.TestCase):
    """CA5: _sync_risk_state() calls risk_manager.register_close_trade() once per close."""

    def setUp(self):
        self.controller = _make_controller()
        self.controller._realised_executors_tracked = {}
        self.controller._loss_streaks = {}
        self.controller.session_blacklist = {}
        self.controller.active_coin = None
        self.controller.active_executor_id = None
        # Replace real GlobalRiskManager with a mock so we can assert on calls
        self.controller.risk_manager = MagicMock()

    def _run(self, executor):
        self.controller.executors_info = [executor]
        _call_sync(self.controller)

    # -------------------------------------------------------------------------

    def test_called_once_per_executor_close(self):
        """register_close_trade must be called exactly once for a single closed executor."""
        executor = _make_executor("e1", Decimal("-5.0"))
        self._run(executor)
        self.controller.risk_manager.register_close_trade.assert_called_once()

    def test_idempotency_same_executor_id_second_call_is_noop(self):
        """Processing the same executor id twice must NOT call register_close_trade twice."""
        executor = _make_executor("e1", Decimal("-5.0"))
        self._run(executor)  # first time
        self._run(executor)  # second time, same id
        self.assertEqual(
            self.controller.risk_manager.register_close_trade.call_count, 1,
            "register_close_trade must not be called a second time for the same executor id",
        )

    def test_called_for_each_distinct_executor(self):
        """Two distinct closed executors → two calls to register_close_trade."""
        e1 = _make_executor("e1", Decimal("-5.0"), symbol="XRP-USD")
        e2 = _make_executor("e2", Decimal("+2.0"), close_type=CloseType.TAKE_PROFIT, symbol="BTC-USD")
        self.controller.executors_info = [e1, e2]
        _call_sync(self.controller)
        self.assertEqual(self.controller.risk_manager.register_close_trade.call_count, 2)

    def test_correct_symbol_passed(self):
        executor = _make_executor("e1", Decimal("-5.0"), symbol="XRP-USD")
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["symbol"], "XRP-USD")

    def test_correct_pnl_passed(self):
        executor = _make_executor("e1", Decimal("-7.5"))
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["realised_pnl_quote"], Decimal("-7.5"))

    # --- exit_type mapping ---------------------------------------------------

    def test_close_type_stop_loss_maps_to_exit_type_stop_loss(self):
        from multi_coin_grid_pro.core.exit_types import ExitType
        executor = _make_executor("e1", Decimal("-5.0"), close_type=CloseType.STOP_LOSS)
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["exit_type"], ExitType.STOP_LOSS)

    def test_close_type_take_profit_maps_to_exit_type_take_profit(self):
        from multi_coin_grid_pro.core.exit_types import ExitType
        executor = _make_executor("e1", Decimal("+3.0"), close_type=CloseType.TAKE_PROFIT)
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["exit_type"], ExitType.TAKE_PROFIT)

    def test_timeout_with_negative_pnl_maps_to_trend_exit(self):
        from multi_coin_grid_pro.core.exit_types import ExitType
        for ct in (CloseType.NO_FILL_TIMEOUT, CloseType.NO_PROGRESS_TIMEOUT, CloseType.TIME_LIMIT):
            self.controller.risk_manager.reset_mock()
            self.controller._realised_executors_tracked = {}
            executor = _make_executor("e1", Decimal("-2.0"), close_type=ct)
            self._run(executor)
            kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
            self.assertEqual(
                kwargs["exit_type"], ExitType.TREND_EXIT,
                f"Expected TREND_EXIT for {ct}, got {kwargs['exit_type']}",
            )

    def test_large_loss_without_stop_loss_close_type_maps_to_stop_loss(self):
        """pnl < 0 and abs(pnl) >= r_unit → STOP_LOSS exit type."""
        from multi_coin_grid_pro.core.exit_types import ExitType

        # r_unit_quote default is 5.0; use pnl of -6.0
        executor = _make_executor("e1", Decimal("-6.0"), close_type=CloseType.POSITION_HOLD)
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["exit_type"], ExitType.STOP_LOSS)

    def test_small_loss_without_stop_loss_close_type_maps_to_small_loss(self):
        """pnl < 0 and abs(pnl) < r_unit → SMALL_LOSS exit type."""
        from multi_coin_grid_pro.core.exit_types import ExitType

        # r_unit_quote default 5.0; use pnl of -1.0
        executor = _make_executor("e1", Decimal("-1.0"), close_type=CloseType.POSITION_HOLD)
        self._run(executor)
        kwargs = self.controller.risk_manager.register_close_trade.call_args[1]
        self.assertEqual(kwargs["exit_type"], ExitType.SMALL_LOSS)

    def test_register_close_trade_failure_does_not_crash_sync(self):
        """If register_close_trade raises, _sync_risk_state must not propagate the error."""
        self.controller.risk_manager.register_close_trade.side_effect = RuntimeError("db down")
        executor = _make_executor("e1", Decimal("-5.0"))
        # Must not raise
        self._run(executor)

    def test_grm_state_updated_with_real_risk_manager(self):
        """Integration smoke-test: real GlobalRiskManager.register_close_trade() updates state."""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager

        # Re-create controller with a real GlobalRiskManager
        config = MultiCoinGridConfig(connector_name="kraken", quote_asset="USD")
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        market_data_provider = MagicMock()
        market_data_provider.time.return_value = 1000.0
        market_data_provider.ready = True
        with patch.object(MultiCoinGridController, '_initialize_components'):
            ctrl = MultiCoinGridController(
                config=config,
                market_data_provider=market_data_provider,
                actions_queue=MagicMock(),
                connectors={"kraken": MagicMock()},
            )
        ctrl._realised_executors_tracked = {}
        ctrl._loss_streaks = {}
        ctrl.session_blacklist = {}
        ctrl.active_coin = None
        ctrl.active_executor_id = None

        executor = _make_executor("e1", Decimal("-5.0"), close_type=CloseType.STOP_LOSS)
        ctrl.executors_info = [executor]
        _call_sync(ctrl)

        # The real GRM should have recorded the PnL
        grm: GlobalRiskManager = ctrl.risk_manager
        self.assertIn("XRP-USD", grm._daily_coin_pnl)
        self.assertLess(grm._daily_coin_pnl["XRP-USD"], 0)


if __name__ == "__main__":
    unittest.main()
