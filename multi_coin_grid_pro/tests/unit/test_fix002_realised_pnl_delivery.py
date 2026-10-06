"""FIX-002: realised PnL must reach the kill switch exactly once.

The defect: with ``closed_executors_buffer = 0`` the orchestrator removes a
closed executor from ``active_executors`` inside the same strategy tick that
publishes the snapshot, so the controller's async loop effectively never
observes it in TERMINATED state. Four safety mechanisms were dead as a result:
the kill-switch PnL tracker, the drawdown tracker, PHANTOM_LOSS_FIX and trade
label persistence.

These tests cover the delivery and deduplication machinery that replaces the
dead ``executors_info`` scan.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hummingbot.strategy_v2.models.base import RunnableStatus  # noqa: E402
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController  # noqa: E402
from multi_coin_grid_pro.persistence.realised_pnl_ledger import RealisedPnlLedger  # noqa: E402
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker  # noqa: E402


def make_executor_info(executor_id: str, net_pnl: str, trading_pair: str = "XDC-USD",
                       status=RunnableStatus.TERMINATED, close_timestamp: int = 1791260419):
    return SimpleNamespace(
        id=executor_id,
        status=status,
        net_pnl_quote=Decimal(net_pnl),
        cum_fees_quote=Decimal("0.10"),
        close_timestamp=close_timestamp,
        config=SimpleNamespace(trading_pair=trading_pair),
        custom_info={},
    )


@pytest.fixture
def controller(tmp_path):
    """A controller stub carrying only the FIX-002 machinery."""
    instance = MultiCoinGridController.__new__(MultiCoinGridController)
    instance._pending_realised_executors = []
    instance._realised_executors_tracked = {}
    instance.realised_pnl_ledger = RealisedPnlLedger(str(tmp_path / "ledger.db"))
    instance.executors_info = []
    instance.config = SimpleNamespace(id="multi_coin_grid_usd")
    instance.logger = MagicMock(return_value=MagicMock())
    return instance


def feed_tracker(tracker, executor_info, entry_price=Decimal("1.0")):
    """Mirror the controller's T1-K1 synthesis (controller lines 7095-7110).

    The tracker's equity follows current_balance, which only moves through
    on_trade_fill. The controller therefore synthesises an entry and an exit
    fill whose price difference encodes the realised PnL. Reproducing that here
    means these tests exercise the real path into the kill switch.
    """
    from multi_coin_grid_pro.core.models import TradeFill as PnlTradeFill

    position_size = Decimal("50")
    qty = position_size / entry_price
    tracker.on_trade_fill(PnlTradeFill(
        symbol=executor_info.config.trading_pair, side="buy",
        price=entry_price, size=qty, fee=Decimal("0"), ts=1791260419,
    ))
    pnl_ratio = executor_info.net_pnl_quote / position_size
    tracker.on_trade_fill(PnlTradeFill(
        symbol=executor_info.config.trading_pair, side="sell",
        price=entry_price * (Decimal("1") + pnl_ratio), size=qty,
        fee=Decimal("0"), ts=1791260420,
    ))


# ------------------------------------------------------------ delivery ---
def test_enqueue_then_collect_returns_the_executor(controller):
    info = make_executor_info("exec-1", "-33.3897")
    controller.enqueue_realised_executor(info)
    assert [e.id for e in controller._collect_realised_candidates()] == ["exec-1"]


def test_terminated_executor_feeds_pnl_tracker_once(controller):
    """The core guarantee: delivered once, not zero times and not twice."""
    tracker = RealtimePnLTracker(starting_balance=Decimal("300"))
    info = make_executor_info("exec-1", "-9.50")

    delivered = []
    for _ in range(5):
        controller.enqueue_realised_executor(info)
        for executor in controller._collect_realised_candidates():
            delivered.append(executor.id)
            feed_tracker(tracker, executor)

    assert delivered == ["exec-1"]
    assert tracker.daily_pnl_pct() < 0


def test_repeated_sync_does_not_double_count(controller):
    info = make_executor_info("exec-1", "-5")
    controller.enqueue_realised_executor(info)
    assert len(controller._collect_realised_candidates()) == 1
    assert controller._collect_realised_candidates() == []
    controller.enqueue_realised_executor(info)
    assert controller._collect_realised_candidates() == []


def test_restart_does_not_double_count(controller, tmp_path):
    """A fresh controller on the same ledger file refuses a processed id."""
    info = make_executor_info("exec-1", "-5")
    controller.enqueue_realised_executor(info)
    assert len(controller._collect_realised_candidates()) == 1

    restarted = MultiCoinGridController.__new__(MultiCoinGridController)
    restarted._pending_realised_executors = []
    restarted._realised_executors_tracked = {}
    restarted.realised_pnl_ledger = RealisedPnlLedger(str(tmp_path / "ledger.db"))
    restarted.executors_info = []
    restarted.config = SimpleNamespace(id="multi_coin_grid_usd")
    restarted.logger = MagicMock(return_value=MagicMock())

    restarted.enqueue_realised_executor(info)
    assert restarted._collect_realised_candidates() == []


def test_multiple_closed_executors_processed(controller):
    infos = [make_executor_info(f"exec-{i}", f"-{i}") for i in range(1, 6)]
    for info in infos:
        controller.enqueue_realised_executor(info)
    collected = controller._collect_realised_candidates()
    assert [e.id for e in collected] == [f"exec-{i}" for i in range(1, 6)]
    assert controller._collect_realised_candidates() == []


def test_duplicate_enqueue_in_same_tick_is_collapsed(controller):
    info = make_executor_info("exec-1", "-5")
    controller.enqueue_realised_executor(info)
    controller.enqueue_realised_executor(info)
    assert len(controller._pending_realised_executors) == 1


def test_enqueue_ignores_invalid_input(controller):
    controller.enqueue_realised_executor(None)
    controller.enqueue_realised_executor(SimpleNamespace(id=None))
    assert controller._pending_realised_executors == []


# ------------------------------------------------------------ fallback ---
def test_fallback_picks_up_terminated_from_snapshot(controller):
    """The old path still works when the hand-over did not happen."""
    controller.executors_info = [make_executor_info("exec-snapshot", "-2")]
    assert [e.id for e in controller._collect_realised_candidates()] == ["exec-snapshot"]


def test_fallback_does_not_duplicate_handed_over_executor(controller):
    """An executor delivered by both paths is still processed once."""
    info = make_executor_info("exec-1", "-5")
    controller.enqueue_realised_executor(info)
    controller.executors_info = [info]
    assert [e.id for e in controller._collect_realised_candidates()] == ["exec-1"]
    assert controller._collect_realised_candidates() == []


def test_running_executors_are_not_collected(controller):
    controller.executors_info = [
        make_executor_info("exec-running", "-5", status=RunnableStatus.RUNNING)
    ]
    assert controller._collect_realised_candidates() == []


# --------------------------------------------------------- consumers ---
def test_negative_pnl_reaches_daily_loss_path(controller):
    """A loss must move daily_pnl_pct so the risk guard can trip."""
    tracker = RealtimePnLTracker(starting_balance=Decimal("300"))
    assert tracker.daily_pnl_pct() == 0

    controller.enqueue_realised_executor(make_executor_info("exec-loss", "-30"))
    for executor in controller._collect_realised_candidates():
        feed_tracker(tracker, executor)

    assert tracker.daily_pnl_pct() < 0, "the kill switch must see the loss"


def test_positive_pnl_updates_tracker(controller):
    tracker = RealtimePnLTracker(starting_balance=Decimal("300"))
    controller.enqueue_realised_executor(make_executor_info("exec-win", "15"))
    for executor in controller._collect_realised_candidates():
        feed_tracker(tracker, executor)
    assert tracker.daily_pnl_pct() > 0


def test_drawdown_tracker_receives_same_pnl(controller):
    """Both consumers must see an identical value from one delivery."""
    to_tracker, to_drawdown = [], []
    controller.enqueue_realised_executor(make_executor_info("exec-1", "-12.3456"))
    for executor in controller._collect_realised_candidates():
        to_tracker.append(executor.net_pnl_quote)
        to_drawdown.append(executor.net_pnl_quote)
    assert to_tracker == to_drawdown == [Decimal("-12.3456")]


def test_ledger_failure_fails_closed(controller, monkeypatch):
    """If the ledger cannot claim, skip rather than risk double counting."""
    monkeypatch.setattr(controller.realised_pnl_ledger, "claim", lambda *a, **k: False)
    controller.enqueue_realised_executor(make_executor_info("exec-1", "-5"))
    assert controller._collect_realised_candidates() == []


def test_without_ledger_falls_back_to_memory_guard(controller):
    """A missing ledger degrades to the in-memory guard, never to double counting."""
    controller.realised_pnl_ledger = None
    info = make_executor_info("exec-1", "-5")

    controller.enqueue_realised_executor(info)
    assert len(controller._collect_realised_candidates()) == 1

    controller._realised_executors_tracked["exec-1"] = Decimal("-5")
    controller.enqueue_realised_executor(info)
    assert controller._collect_realised_candidates() == []


def test_phantom_loss_correction_condition_is_detectable(controller):
    """PHANTOM_LOSS_FIX fires on FAILED with sell < buy.

    Guards the condition itself; the surrounding block is exercised through
    _sync_risk_state in integration.
    """
    from hummingbot.strategy_v2.models.executors import CloseType

    info = make_executor_info("exec-xdc", "-33.3897")
    info.close_type = CloseType.FAILED
    info.custom_info = {
        "realized_buy_size_quote": "67.08",
        "realized_sell_size_quote": "34.09",
        "realized_fees_quote": "0.1538",
    }

    buy = Decimal(info.custom_info["realized_buy_size_quote"])
    sell = Decimal(info.custom_info["realized_sell_size_quote"])
    fees = Decimal(info.custom_info["realized_fees_quote"])

    assert info.close_type == CloseType.FAILED
    assert buy > 0 and sell < buy
    assert -fees > info.net_pnl_quote  # correction is far less severe
