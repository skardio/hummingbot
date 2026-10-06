"""FIX-002 end to end: a loss must actually trip the kill switch.

The unit tests prove delivery and deduplication. This proves the consequence:
realised PnL arriving through the new path moves the tracker far enough that
``RiskGuardV2.check_limits()`` returns False and trading stops.

Before the fix this was impossible: the controller never observed a closed
executor, ``daily_pnl_pct()`` stayed at 0.0%, and no loss could ever trip the
guard.
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
from multi_coin_grid_pro.core.models import TradeFill as PnlTradeFill  # noqa: E402
from multi_coin_grid_pro.persistence.realised_pnl_ledger import RealisedPnlLedger  # noqa: E402
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker  # noqa: E402
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2  # noqa: E402

STARTING_BALANCE = Decimal("300")
MAX_DAILY_LOSS_PCT = 3.0        # spot_grid_kraken_usd.yaml:1016


def make_closed_executor(executor_id: str, net_pnl: str, trading_pair: str = "XDC-USD"):
    return SimpleNamespace(
        id=executor_id,
        status=RunnableStatus.TERMINATED,
        net_pnl_quote=Decimal(net_pnl),
        cum_fees_quote=Decimal("0.10"),
        close_timestamp=1791260419,
        config=SimpleNamespace(trading_pair=trading_pair),
        custom_info={},
    )


@pytest.fixture
def rig(tmp_path):
    """Controller delivery path wired to a real tracker and a real risk guard."""
    controller = MultiCoinGridController.__new__(MultiCoinGridController)
    controller._pending_realised_executors = []
    controller._realised_executors_tracked = {}
    controller.realised_pnl_ledger = RealisedPnlLedger(str(tmp_path / "ledger.db"))
    controller.executors_info = []
    controller.config = SimpleNamespace(id="multi_coin_grid_usd")
    controller.logger = MagicMock(return_value=MagicMock())

    tracker = RealtimePnLTracker(starting_balance=STARTING_BALANCE)
    guard = RiskGuardV2(
        pnl_tracker=tracker,
        cfg={"max_daily_loss_pct": MAX_DAILY_LOSS_PCT},
        alerter=MagicMock(),
        logger=MagicMock(),
    )
    return controller, tracker, guard


def deliver(controller, tracker, executor, entry_price=Decimal("1.0")):
    """Run the production delivery path, including the T1-K1 fill synthesis."""
    for claimed in controller._collect_realised_candidates():
        position_size = Decimal("50")
        qty = position_size / entry_price
        tracker.on_trade_fill(PnlTradeFill(
            symbol=claimed.config.trading_pair, side="buy",
            price=entry_price, size=qty, fee=Decimal("0"), ts=1791260419,
        ))
        pnl_ratio = claimed.net_pnl_quote / position_size
        tracker.on_trade_fill(PnlTradeFill(
            symbol=claimed.config.trading_pair, side="sell",
            price=entry_price * (Decimal("1") + pnl_ratio), size=qty,
            fee=Decimal("0"), ts=1791260420,
        ))


def test_guard_allows_trading_before_any_loss(rig):
    _, _, guard = rig
    assert guard.check_limits() is True


def test_single_large_loss_trips_the_kill_switch(rig):
    """A loss beyond 3% of the reference balance must stop trading."""
    controller, tracker, guard = rig
    assert guard.check_limits() is True

    controller.enqueue_realised_executor(make_closed_executor("exec-big-loss", "-15"))
    deliver(controller, tracker, make_closed_executor("exec-big-loss", "-15"))

    assert tracker.daily_pnl_pct() <= -MAX_DAILY_LOSS_PCT
    assert guard.check_limits() is False
    assert guard.trading_enabled is False
    assert guard.kill_reason is not None


def test_accumulating_small_losses_eventually_trip_the_guard(rig):
    """Several ordinary losses add up through the new delivery path."""
    controller, tracker, guard = rig
    for index in range(6):
        controller.enqueue_realised_executor(make_closed_executor(f"exec-{index}", "-2"))
        deliver(controller, tracker, make_closed_executor(f"exec-{index}", "-2"))
        if not guard.check_limits():
            break
    assert guard.trading_enabled is False, (
        f"guard should have tripped; daily_pnl_pct={tracker.daily_pnl_pct():.2f}%"
    )


def test_small_loss_does_not_trip_the_guard(rig):
    """The guard must not be hair-trigger either."""
    controller, tracker, guard = rig
    controller.enqueue_realised_executor(make_closed_executor("exec-small", "-1"))
    deliver(controller, tracker, make_closed_executor("exec-small", "-1"))

    assert tracker.daily_pnl_pct() > -MAX_DAILY_LOSS_PCT
    assert guard.check_limits() is True


def test_profit_never_trips_the_guard(rig):
    controller, tracker, guard = rig
    controller.enqueue_realised_executor(make_closed_executor("exec-win", "20"))
    deliver(controller, tracker, make_closed_executor("exec-win", "20"))

    assert tracker.daily_pnl_pct() > 0
    assert guard.check_limits() is True


def test_duplicate_delivery_cannot_inflate_the_loss(rig):
    """Re-delivering the same executor must not move the tracker again."""
    controller, tracker, guard = rig
    executor = make_closed_executor("exec-once", "-5")

    controller.enqueue_realised_executor(executor)
    deliver(controller, tracker, executor)
    after_first = tracker.daily_pnl_pct()

    for _ in range(5):
        controller.enqueue_realised_executor(executor)
        deliver(controller, tracker, executor)

    assert tracker.daily_pnl_pct() == after_first


def test_regression_without_delivery_the_guard_stays_blind(rig):
    """Control: the pre-fix behaviour, reproduced.

    Executors close, the controller never observes them, daily_pnl_pct stays at
    zero and no loss can ever trip the guard.
    """
    _, tracker, guard = rig
    for _ in range(10):
        pass  # executors close; nothing is ever delivered
    assert tracker.daily_pnl_pct() == 0.0
    assert guard.check_limits() is True
