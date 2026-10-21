"""Independent virtual-portfolio state for the A/B shadow sandbox: variant A
and variant B must never see or affect each other's capital, open positions,
or drawdown."""
import time
from decimal import Decimal

from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualExitReason, VirtualGridPosition
from multi_coin_grid_pro.shadow.virtual_portfolio import VirtualPortfolio


def _position(symbol="XRP-USD", notional=Decimal("100")) -> VirtualGridPosition:
    return VirtualGridPosition(
        symbol=symbol, notional_quote=notional, stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), max_hold_seconds=3600.0,
        limit_price=Decimal("1.0"), created_at=time.time(),
    )


def test_two_portfolios_do_not_share_state():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("300"), max_slots=3)
    b = VirtualPortfolio(variant_label="B", capital_quote=Decimal("300"), max_slots=3)

    a.open_position(_position("XRP-USD"))

    assert "XRP-USD" in a.open_positions
    assert "XRP-USD" not in b.open_positions
    assert a.reserved_quote == Decimal("100")
    assert b.reserved_quote == Decimal("0")


def test_cannot_open_same_symbol_twice_in_one_portfolio():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("300"), max_slots=3)
    assert a.can_open("XRP-USD", Decimal("100")) is True
    a.open_position(_position("XRP-USD"))
    assert a.can_open("XRP-USD", Decimal("100")) is False


def test_cannot_exceed_max_slots():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("300"), max_slots=1)
    a.open_position(_position("XRP-USD"))
    assert a.can_open("ETH-USD", Decimal("50")) is False


def test_cannot_exceed_available_capital():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("100"), max_slots=3)
    a.open_position(_position("XRP-USD", notional=Decimal("90")))
    assert a.can_open("ETH-USD", Decimal("20")) is False  # only 10 left


def test_close_position_releases_slot_and_capital_and_records_result():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("300"), max_slots=3)
    position = _position("XRP-USD")
    a.open_position(position)
    now = time.time()
    position.try_fill_entry(Decimal("1.0"), now)
    position.try_fill_entry(Decimal("1.0"), now + 1)
    position.close(Decimal("1.05"), now + 60, VirtualExitReason.TAKE_PROFIT_NET)

    closed = a.close_position("XRP-USD")

    assert closed is position
    assert "XRP-USD" not in a.open_positions
    assert a.reserved_quote == Decimal("0")
    assert a.available_slots() == 3
    assert closed in a.closed_positions
    assert a.realized_pnl_total() == position.net_pnl_quote


def test_max_drawdown_tracks_peak_to_trough_on_realised_equity_curve():
    a = VirtualPortfolio(variant_label="A", capital_quote=Decimal("300"), max_slots=3)

    def _closed(net_pnl: Decimal) -> VirtualGridPosition:
        p = _position(symbol=f"C{net_pnl}")
        now = time.time()
        p.try_fill_entry(Decimal("1.0"), now)
        p.try_fill_entry(Decimal("1.0"), now + 1)
        p.net_pnl_quote = net_pnl  # directly set for a controlled equity curve
        a.closed_positions.append(p)
        return p

    _closed(Decimal("5"))    # equity: 5 (peak 5)
    _closed(Decimal("-8"))   # equity: -3 (drawdown -8 from peak 5)
    _closed(Decimal("2"))    # equity: -1

    assert a.max_drawdown_quote() == Decimal("-8")
