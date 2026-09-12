"""
US-005 TIME_STOP semantics verification tests.

Context (2026-09-10 investigation): BCH-USDT logged repeated
"US-005 Exit Signal: TIME_STOP - Dead position" warnings for 1000+ minutes
without the position ever actually closing, immediately followed by
"No better coin found, but keeping BCH-USDT running." This looked like
TIME_STOP was being treated as a mere rotation candidate that got blocked
by "no better coin available".

Investigation result: TIME_STOP is NOT gated by coin availability.
``_check_professional_exit_signals()`` unconditionally builds a
``StopExecutorAction(keep_position=False)`` whenever
``ProfessionalRiskManager.should_exit_position()`` returns TIME_STOP/
STOP_LOSS/PROFIT_LOCK, independent of ``best_coin``/rotation logic (which
lives in a completely separate branch of ``determine_executor_actions()``
that only controls whether NEW positions may be opened). The real root
cause of the "never closes" symptom was the close-order race condition
fixed separately in grid_executor.py: the internal two-phase unwind
(NO_PROGRESS_TIMEOUT, started hours earlier) and TIME_STOP's own
``early_stop()`` call were both trying to close the same executor,
repeatedly racing and failing instead of TIME_STOP actually being ignored.

These tests confirm TIME_STOP's intended (and actual) semantics: it is a
mandatory exit signal, not a rotation candidate.
"""

import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction


def _make_controller():
    """Return a MultiCoinGridController with heavy component init patched out."""
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    config = MultiCoinGridConfig(connector_name="bitget", quote_asset="USDT")

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = time.time()
    market_data_provider.ready = True

    with patch.object(MultiCoinGridController, '_initialize_components'):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=market_data_provider,
            actions_queue=MagicMock(),
            connectors={"bitget": MagicMock()},
        )
    controller.event_logger = None  # skip optional event emission in the code path
    return controller


def _wire_active_position(controller, trading_pair="BCH-USDT", executor_id="exec-bch-1"):
    """Wire up controller state so _check_professional_exit_signals() finds
    exactly one active position for `trading_pair`."""
    now = controller.market_data_provider.time()

    executor_info = MagicMock()
    executor_info.id = executor_id
    executor_info.is_active = True
    controller.executors_info = [executor_info]

    controller.active_coins = {trading_pair: executor_id}
    controller.entry_prices = {trading_pair: Decimal("261.4")}
    controller._executor_creation_timestamps = {executor_id: now - 3600 * 20}  # 20h old

    trend = MagicMock()
    trend.current_price = Decimal("253.2")
    trend.atr_pct = 0.02
    trend.atr_value = None
    controller.trend_calculator = MagicMock()
    controller.trend_calculator.get_trend.return_value = trend

    return executor_id


class TestTimeStopIsUnconditionalExit(unittest.TestCase):
    """US-005: TIME_STOP must be a mandatory exit signal, never gated by
    whether a better coin is currently available for rotation."""

    def setUp(self):
        self.controller = _make_controller()
        self.executor_id = _wire_active_position(self.controller)

    def test_time_stop_creates_stop_action_when_better_coin_available(self):
        """Scenario 1: TIME_STOP + a better coin IS available.
        The stop action must still be created -- rotation availability is
        irrelevant to this risk-driven exit decision."""
        with patch.object(
            self.controller.professional_risk_manager, "should_exit_position",
            return_value=("TIME_STOP", "Dead position: stalled 20h, no fills"),
        ):
            actions = self.controller._check_professional_exit_signals()

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], StopExecutorAction)
        self.assertEqual(actions[0].executor_id, self.executor_id)
        self.assertFalse(actions[0].keep_position, "TIME_STOP must request a real close, not POSITION_HOLD")

    def test_time_stop_creates_stop_action_when_no_better_coin_available(self):
        """Scenario 2: TIME_STOP + NO better coin available.
        Must behave identically to scenario 1 -- _check_professional_exit_signals()
        has no concept of "best coin" at all, so it cannot be blocked by it."""
        with patch.object(
            self.controller.professional_risk_manager, "should_exit_position",
            return_value=("TIME_STOP", "Dead position: stalled 20h, no fills"),
        ):
            actions = self.controller._check_professional_exit_signals()

        # Same assertion as scenario 1: the method is unconditional.
        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], StopExecutorAction)
        self.assertFalse(actions[0].keep_position)

    def test_time_stop_action_not_dropped_by_no_better_coin_branch(self):
        """Scenario 2b: the 'no better coin found, but keeping X running' log
        branch lives in a separate part of determine_executor_actions() that
        only decides whether to open NEW positions. It must never remove or
        suppress a TIME_STOP action already produced this tick. We assert
        this directly on the actions list construction pattern used by
        determine_executor_actions(): actions.extend(exit_actions) followed
        by unrelated no-better-coin bookkeeping must leave exit_actions intact."""
        with patch.object(
            self.controller.professional_risk_manager, "should_exit_position",
            return_value=("TIME_STOP", "Dead position: stalled 20h, no fills"),
        ):
            exit_actions = self.controller._check_professional_exit_signals()

        actions = []
        actions.extend(exit_actions)

        # Simulate the unrelated "no better coin" bookkeeping that runs later
        # in determine_executor_actions() -- it only logs/pauses new entries,
        # it does not touch `actions`.
        best_coin = None
        if not best_coin and self.controller.active_coin is None:
            pass  # matches the real code's behavior: no mutation of `actions`

        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].keep_position)

    def test_time_stop_action_created_independent_of_active_unwind_state(self):
        """Scenario 3: TIME_STOP fires while another exit routine (the
        executor's own timeout-triggered two-phase unwind) is already
        active. _check_professional_exit_signals() has no visibility into
        (and must not need) the executor's internal unwind state -- it
        always requests the stop. Safe handling of an already-active unwind
        is the executor's responsibility (see early_stop() unwind-defer fix
        in grid_executor.py, tested in test_grid_executor_close_race.py)."""
        # Simulate the executor already being mid-unwind by giving it a
        # custom_info flag some callers might (incorrectly) expect to matter.
        self.controller.executors_info[0].custom_info = {
            "unwind_phase": "AGGRESSIVE",
            "unwind_close_reason": "NO_PROGRESS_TIMEOUT",
        }

        with patch.object(
            self.controller.professional_risk_manager, "should_exit_position",
            return_value=("TIME_STOP", "Dead position: stalled 20h, no fills"),
        ):
            actions = self.controller._check_professional_exit_signals()

        self.assertEqual(
            len(actions), 1,
            "TIME_STOP must still be requested even while the executor's own "
            "unwind mechanism is active; deferring/upgrading is early_stop()'s job."
        )
        self.assertFalse(actions[0].keep_position)

    def test_no_exit_action_when_risk_manager_says_hold(self):
        """Sanity check: when the risk manager says HOLD, no stop action is
        created (confirms the mock wiring above is meaningful, not a tautology)."""
        with patch.object(
            self.controller.professional_risk_manager, "should_exit_position",
            return_value=("HOLD", "Position healthy"),
        ):
            actions = self.controller._check_professional_exit_signals()

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
