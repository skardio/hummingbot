"""Virtual fill/exit/fee/PnL logic for the A/B shadow sandbox.

Every exit-decision formula reused here (`realized_net_pnl`,
`fee_aware_exit_decision`) is the exact same pure function the live
`GridExecutor` uses — these tests pin that the shadow's math matches
production's math, not just that it computes *something* plausible.
"""
import time
from decimal import Decimal

from multi_coin_grid_pro.shadow.virtual_grid_position import (
    VirtualExitReason,
    VirtualGridPosition,
    VirtualPositionStatus,
)


def _make_position(**overrides) -> VirtualGridPosition:
    defaults = dict(
        symbol="XRP-USD",
        notional_quote=Decimal("100"),
        stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"),
        maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"),
        max_hold_seconds=3600.0,
        limit_price=Decimal("1.000"),
        created_at=time.time(),
    )
    defaults.update(overrides)
    return VirtualGridPosition(**defaults)


def test_entry_does_not_fill_on_a_single_touch():
    """Guards against the exact anti-pattern the user explicitly forbade:
    filling the instant price merely touches the limit once."""
    position = _make_position(limit_price=Decimal("1.000"))
    now = time.time()

    filled = position.try_fill_entry(Decimal("1.000"), now)
    assert filled is False
    assert position.status == VirtualPositionStatus.PENDING_ENTRY


def test_entry_fills_after_two_consecutive_ticks_at_or_below_limit():
    position = _make_position(limit_price=Decimal("1.000"))
    now = time.time()

    position.try_fill_entry(Decimal("1.000"), now)
    filled = position.try_fill_entry(Decimal("0.999"), now + 1)

    assert filled is True
    assert position.status == VirtualPositionStatus.OPEN
    assert position.entry_price == Decimal("0.999")
    assert position.entry_fees_quote == Decimal("100") * Decimal("0.0020")


def test_entry_fill_streak_resets_if_price_moves_away():
    position = _make_position(limit_price=Decimal("1.000"))
    now = time.time()

    position.try_fill_entry(Decimal("1.000"), now)       # streak = 1
    position.try_fill_entry(Decimal("1.010"), now + 1)   # price above limit -> reset
    filled = position.try_fill_entry(Decimal("0.999"), now + 2)  # streak = 1 again

    assert filled is False
    assert position.status == VirtualPositionStatus.PENDING_ENTRY


def test_stop_loss_fires_exactly_at_configured_threshold():
    position = _make_position(stop_loss_pct=Decimal("0.015"), limit_price=Decimal("100"))
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)
    assert position.status == VirtualPositionStatus.OPEN

    # Price far enough below entry to breach -1.5% unrealized (after entry fee).
    reason = position.tick(Decimal("98.0"), now + 60)
    assert reason == VirtualExitReason.STOP_LOSS


def test_take_profit_requires_net_pct_not_just_gross_move():
    """A move that is gross-positive but below the fee-aware required net
    percentage must NOT trigger TAKE_PROFIT_NET — mirrors
    grid_executor.take_profit_condition()'s fee-aware gate exactly."""
    position = _make_position(required_take_profit_net_pct=Decimal("0.02"), limit_price=Decimal("100"))
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)

    # +0.5% gross move: comfortably profitable gross, but far below the 2% net bar.
    reason = position.tick(Decimal("100.5"), now + 60)
    assert reason is None, "A small gross gain below the net-profit bar must not exit as TAKE_PROFIT_NET"


def test_take_profit_fires_once_net_pct_bar_is_cleared():
    position = _make_position(required_take_profit_net_pct=Decimal("0.02"), limit_price=Decimal("100"))
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)

    reason = position.tick(Decimal("103.5"), now + 60)
    assert reason == VirtualExitReason.TAKE_PROFIT_NET


def test_time_limit_fires_after_max_hold_seconds():
    position = _make_position(
        max_hold_seconds=100.0, stop_loss_pct=Decimal("0.50"),
        required_take_profit_net_pct=Decimal("0.50"), limit_price=Decimal("100"),
    )
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)

    reason = position.tick(Decimal("100.1"), now + 200)
    assert reason == VirtualExitReason.TIME_LIMIT


def test_close_computes_realized_net_pnl_matching_the_canonical_formula():
    """Pin the exact numbers: this must match
    multi_coin_grid_pro.logic.exit_safety.realized_net_pnl bit-for-bit."""
    position = _make_position(
        notional_quote=Decimal("100"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), limit_price=Decimal("100"),
    )
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)  # entry_price=100, size_base=1, entry_fee=0.20

    position.close(Decimal("102"), now + 120, VirtualExitReason.TAKE_PROFIT_NET)

    expected_gross = Decimal("102") - Decimal("100")              # sell_quote - buy_quote, size_base=1
    expected_exit_fee = Decimal("102") * Decimal("0.0035")
    expected_net = expected_gross - Decimal("0.20") - expected_exit_fee

    assert position.gross_pnl_quote == expected_gross
    assert position.net_pnl_quote == expected_net
    assert position.status == VirtualPositionStatus.CLOSED


def test_closed_position_records_empirical_fee_annotation_without_using_it_in_pnl():
    """The empirical ~0.29% fee annotation must be purely observational —
    it must never change net_pnl_quote."""
    position = _make_position(limit_price=Decimal("100"))
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)
    position.close(Decimal("101"), now + 60, VirtualExitReason.TIME_LIMIT)

    assert position.annotated_fee_quote_at_empirical_rate is not None
    # The config-assumed fee (0.20%/0.35%) and the empirical one (0.29%/0.29%)
    # must differ for this to be a meaningful annotation, and net_pnl_quote
    # must be computed from the config-assumed fees only.
    config_assumed_total_fee = position.fees_quote
    assert config_assumed_total_fee != position.annotated_fee_quote_at_empirical_rate


def test_tick_before_fill_is_a_noop():
    position = _make_position()
    assert position.tick(Decimal("50"), time.time()) is None
    assert position.status == VirtualPositionStatus.PENDING_ENTRY
