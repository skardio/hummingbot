"""FIX-003: stuck bucket/budget/active-coin exposure must be released exactly once.

The defect: inside ``_sync_risk_state()`` the cleanup block ("🔧 CLEANUP: Remove
terminated/failed executors from active_coins") iterated ``self.executors_info``
filtered on TERMINATED status - the exact same pattern that was proven dead for
PnL propagation in FIX-002. With ``closed_executors_buffer = 0`` the orchestrator
removes a closed executor from ``active_executors`` inside the same strategy
tick that publishes the snapshot, so the controller's async loop effectively
never observes TERMINATED. As a result ``active_coins``, ``budget_allocator``
and ``bucket_tracker`` were never released for a closed executor.

Production evidence: Kraken USD bucket ILLIQUID stuck at 44.7% for 7 days
straight (2026-10-07 to 2026-10-14) with 0 open executors in the database,
blocking every new entry, and 0 "Cleanup: Removed" log lines across 99 log
rotations since the restart.

This affects every bot derived from ``MultiCoinGridController`` (Kraken
EUR/USD, Bitget spot/futures, OKX spot) since none of them override
``_sync_risk_state()``.

FIX-003 reuses the exact same collection (``_collect_realised_candidates()``)
that FIX-002 introduced for the PnL loop, calling it exactly once per tick and
using the single result for both the cleanup loop and the PnL loop.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType
from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController


def _make_controller(config_kwargs=None):
    """Return a real MultiCoinGridController with _initialize_components patched out.

    Mirrors the harness in test_ca1_ca2_ca5_verification.py so that
    active_coins, entry_prices, price_history_for_volatility,
    current_exposure_per_coin, budget_allocator, bucket_tracker and
    realised_pnl_ledger are all the real objects set up in __init__
    (none of these live inside the patched _initialize_components).
    """
    cfg_defaults = dict(connector_name="kraken", quote_asset="USD")
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
    controller.risk_manager = MagicMock()
    controller.budget_allocator = MagicMock()
    controller.bucket_tracker = MagicMock()
    return controller


def _make_executor(
    exec_id, pnl, trading_pair="XRP-USD", close_type=CloseType.STOP_LOSS,
    status=RunnableStatus.TERMINATED, is_active=False,
):
    executor = MagicMock()
    executor.id = exec_id
    executor.status = status
    executor.is_active = is_active
    executor.close_type = close_type
    executor.net_pnl_quote = pnl
    executor.cum_fees_quote = Decimal("0.1")
    executor.config.trading_pair = trading_pair
    executor.custom_info = {}
    executor.close_timestamp = 1791260419
    return executor


def _seed_active(controller, trading_pair, executor_id):
    controller.active_coins[trading_pair] = executor_id
    controller.price_history_for_volatility[trading_pair] = [{"price": 1.0, "timestamp": 1000.0}]


class TestFix003BucketCleanupDelivery(unittest.TestCase):
    """FIX-003: active_coins/budget_allocator/bucket_tracker are released exactly once."""

    def setUp(self):
        self.controller = _make_controller()

    def _seed_active(self, trading_pair, executor_id):
        _seed_active(self.controller, trading_pair, executor_id)

    def test_cleanup_releases_active_coins_budget_and_bucket_exactly_once(self):
        """A single closed executor must release active_coins, budget and bucket exactly once."""
        executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = [executor]

        self.controller._sync_risk_state()

        self.assertNotIn("XRP-USD", self.controller.active_coins)
        self.controller.budget_allocator.release.assert_called_once_with("e1")
        self.controller.bucket_tracker.clear_coin.assert_called_once_with("XRP-USD")
        self.assertNotIn("XRP-USD", self.controller.price_history_for_volatility)

    def test_repeated_sync_does_not_double_release(self):
        """Calling _sync_risk_state() twice for the same executor must only release once."""
        executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = [executor]

        self.controller._sync_risk_state()
        self.controller._sync_risk_state()  # second tick, same executor still in executors_info

        self.controller.budget_allocator.release.assert_called_once_with("e1")
        self.controller.bucket_tracker.clear_coin.assert_called_once_with("XRP-USD")

    def test_restart_does_not_double_release(self):
        """A new controller instance (simulating restart) backed by the same ledger
        file must not re-release an already-claimed executor id."""
        import tempfile
        from pathlib import Path

        from multi_coin_grid_pro.persistence.realised_pnl_ledger import RealisedPnlLedger

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = str(Path(tmp) / "ledger.db")

            executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
            self.controller.realised_pnl_ledger = RealisedPnlLedger(ledger_path)
            self._seed_active("XRP-USD", "e1")
            self.controller.executors_info = [executor]
            self.controller._sync_risk_state()
            self.controller.budget_allocator.release.assert_called_once_with("e1")

            # Simulate a restart: fresh controller, same durable ledger file.
            restarted = _make_controller()
            restarted.realised_pnl_ledger = RealisedPnlLedger(ledger_path)
            _seed_active(restarted, "XRP-USD", "e1")
            restarted.executors_info = [executor]
            restarted._sync_risk_state()

            restarted.budget_allocator.release.assert_not_called()
            restarted.bucket_tracker.clear_coin.assert_not_called()

    def test_multiple_closed_executors_each_cleaned_up_once(self):
        """Two distinct closed executors on two coins both get released, once each."""
        e1 = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        e2 = _make_executor("e2", Decimal("+2.0"), trading_pair="BTC-USD", close_type=CloseType.TAKE_PROFIT)
        self._seed_active("XRP-USD", "e1")
        self._seed_active("BTC-USD", "e2")
        self.controller.executors_info = [e1, e2]

        self.controller._sync_risk_state()

        self.assertNotIn("XRP-USD", self.controller.active_coins)
        self.assertNotIn("BTC-USD", self.controller.active_coins)
        self.assertEqual(self.controller.budget_allocator.release.call_count, 2)
        self.assertEqual(self.controller.bucket_tracker.clear_coin.call_count, 2)

    def test_explicit_handover_also_drives_cleanup(self):
        """enqueue_realised_executor() (the FIX-002 hand-over path) must also
        drive bucket/budget cleanup, not only the executors_info fallback."""
        executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = []  # not in the snapshot at all
        self.controller.enqueue_realised_executor(executor)

        self.controller._sync_risk_state()

        self.assertNotIn("XRP-USD", self.controller.active_coins)
        self.controller.budget_allocator.release.assert_called_once_with("e1")
        self.controller.bucket_tracker.clear_coin.assert_called_once_with("XRP-USD")

    def test_running_executor_is_not_cleaned_up(self):
        """A still-RUNNING executor must never trigger cleanup, regardless of source."""
        executor = _make_executor(
            "e1", Decimal("0"), trading_pair="XRP-USD",
            status=RunnableStatus.RUNNING, is_active=True,
        )
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = [executor]

        self.controller._sync_risk_state()

        self.assertIn("XRP-USD", self.controller.active_coins)
        self.controller.budget_allocator.release.assert_not_called()
        self.controller.bucket_tracker.clear_coin.assert_not_called()

    def test_ledger_claim_failure_blocks_cleanup_as_well_as_pnl(self):
        """If the ledger claim fails, neither cleanup nor PnL propagation may fire
        (fail-closed applies uniformly, not just to the PnL half)."""
        executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = [executor]
        self.controller.realised_pnl_ledger = MagicMock()
        self.controller.realised_pnl_ledger.claim.return_value = False

        self.controller._sync_risk_state()

        self.assertIn("XRP-USD", self.controller.active_coins)
        self.controller.budget_allocator.release.assert_not_called()
        self.controller.bucket_tracker.clear_coin.assert_not_called()
        self.controller.risk_manager.register_close_trade.assert_not_called()

    def test_single_collection_call_per_tick(self):
        """_collect_realised_candidates() must be called exactly once per
        _sync_risk_state() tick; the cleanup and PnL loops must share the result."""
        executor = _make_executor("e1", Decimal("-5.0"), trading_pair="XRP-USD")
        self._seed_active("XRP-USD", "e1")
        self.controller.executors_info = [executor]

        with patch.object(
            self.controller, "_collect_realised_candidates",
            wraps=self.controller._collect_realised_candidates,
        ) as collect_spy:
            self.controller._sync_risk_state()
            collect_spy.assert_called_once()

        # Both side effects still happened, proving both loops used the one result.
        self.assertNotIn("XRP-USD", self.controller.active_coins)
        self.controller.risk_manager.register_close_trade.assert_called_once()


class TestFix003AppliesToAllDerivedControllers(unittest.TestCase):
    """Structural proof that the fix applies to every bot built on this controller."""

    def test_no_derived_controller_overrides_sync_risk_state(self):
        from multi_coin_grid_pro.futures_bitget.controller import FuturesGridBitgetController
        from multi_coin_grid_pro.spot_bitget.controller import SpotGridBitgetController
        from multi_coin_grid_pro.spot_okx.controller import SpotGridOKXController

        for cls in (SpotGridBitgetController, FuturesGridBitgetController, SpotGridOKXController):
            self.assertNotIn(
                "_sync_risk_state", cls.__dict__,
                f"{cls.__name__} overrides _sync_risk_state(); FIX-003 no longer "
                "covers it automatically and needs its own fix.",
            )
            self.assertIs(
                cls._sync_risk_state, MultiCoinGridController._sync_risk_state,
                f"{cls.__name__} does not use the shared, fixed _sync_risk_state().",
            )


if __name__ == "__main__":
    unittest.main()
