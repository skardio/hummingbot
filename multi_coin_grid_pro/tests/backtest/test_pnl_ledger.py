from decimal import Decimal

import pytest

from multi_coin_grid_pro.backtesting.ledger import Fill, PortfolioLedger

D = Decimal


def fill(trade_id, side, price, amount, fee="0", fee_asset="USD", **kwargs):
    return Fill(
        trade_id=trade_id,
        order_id=f"order-{trade_id}",
        timestamp=float(len(trade_id)),
        side=side,
        price=D(price),
        base_amount=D(amount),
        fee_amount=D(fee),
        fee_asset=fee_asset,
        **kwargs,
    )


def ledger(cash="1000"):
    return PortfolioLedger("BTC", "USD", D(cash))


def test_full_buy_sell_cycle_has_no_double_counted_fees():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "2", fee="0.2"))
    book.apply_fill(fill("s1", "SELL", "110", "2", fee="0.22", exit_reason="take_profit"))

    report = book.report(D("110"))

    assert report.realized_gross_pnl_quote == D("20")
    assert report.realized_fees_quote == D("0.42")
    assert report.realized_net_pnl_quote == D("19.58")
    assert report.total_net_pnl_quote == D("19.58")
    assert report.inventory_base == D("0")
    assert report.pnl_by_exit_reason == {"take_profit": D("19.58")}


def test_multiple_buys_and_partial_sell_use_fifo():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "1"))
    book.apply_fill(fill("b2", "BUY", "120", "1"))
    book.apply_fill(fill("s1", "SELL", "130", "1.5"))

    report = book.report(D("125"))

    assert report.realized_gross_pnl_quote == D("35")
    assert report.inventory_base == D("0.5")
    assert report.remaining_cost_basis_quote == D("60.0")
    assert report.unrealized_gross_pnl_quote == D("2.5")


def test_partial_buy_remains_open_inventory():
    book = ledger()
    book.apply_fill(fill("partial-buy", "BUY", "100", "0.4", fee="0.04"))

    report = book.report(D("105"), estimated_exit_fee_rate=D("0.001"))

    assert report.inventory_base == D("0.4")
    assert report.open_position_count == 1
    assert report.estimated_exit_cost_quote == D("0.0420")


def test_partial_sell_leaves_residual_cost_basis():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "2"))
    book.apply_fill(fill("partial-sell", "SELL", "110", "0.5", fee="0.055"))

    report = book.report(D("110"))

    assert report.inventory_base == D("1.5")
    assert report.remaining_cost_basis_quote == D("150.00")
    assert report.realized_net_pnl_quote == D("4.945")


def test_buy_fee_in_base_reduces_inventory_without_mixing_units():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "1", fee="0.01", fee_asset="BTC"))

    report = book.report(D("100"))

    assert report.cash_quote == D("900")
    assert report.inventory_base == D("0.99")
    assert report.remaining_cost_basis_quote == D("99.00")
    assert report.remaining_entry_fees_quote == D("1.00")
    assert report.total_net_pnl_quote == D("-1.00")


def test_manual_sell_closes_tracked_inventory():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "1"))
    book.apply_fill(fill("manual-sell", "SELL", "90", "1", source="manual", exit_reason="manual"))

    assert book.realized_matches[0].source == "manual"
    assert book.report(D("90")).realized_net_pnl_quote == D("-10")


def test_external_sell_excess_is_not_attributed_to_bot_inventory():
    book = ledger()
    book.apply_fill(fill("b1", "BUY", "100", "1"))
    book.apply_fill(fill("s1", "SELL", "110", "2", source="manual"))

    report = book.report(D("110"))

    assert report.inventory_base == D("0")
    assert report.realized_gross_pnl_quote == D("10")
    assert any("exceeds tracked inventory" in warning for warning in report.data_quality_warnings)


def test_duplicate_rest_and_websocket_fill_is_idempotent():
    book = ledger()
    same_fill = fill("exchange-trade-1", "BUY", "100", "1", fee="0.1")

    assert book.apply_fill(same_fill)
    assert not book.apply_fill(same_fill)

    report = book.report(D("100"))
    assert report.inventory_base == D("1")
    assert report.duplicate_fill_count == 1


def test_partial_fill_then_cancel_keeps_inventory_and_fee():
    book = ledger()
    book.apply_fill(fill("partial", "BUY", "100", "0.25", fee="0.025"))
    book.record_cancel("order-partial", "partial_then_cancel")

    report = book.report(D("100"))

    assert report.inventory_base == D("0.25")
    assert report.cancel_count == 1
    assert report.total_net_pnl_quote == D("-0.025")


def test_third_asset_fee_requires_conversion_rate():
    book = ledger()

    with pytest.raises(ValueError, match="conversion rate"):
        book.apply_fill(fill("b1", "BUY", "100", "1", fee="1", fee_asset="BNB"))


def test_maker_and_taker_fee_combination_is_reported_once():
    book = ledger()
    book.apply_fill(fill("maker-buy", "BUY", "100", "1", fee="0.1", liquidity="maker"))
    book.apply_fill(fill("taker-sell", "SELL", "105", "1", fee="0.21", liquidity="taker"))

    report = book.report(D("105"))

    assert report.realized_fees_quote == D("0.31")
    assert report.realized_net_pnl_quote == D("4.69")
    assert report.total_net_pnl_quote == D("4.69")


def test_zero_fills_is_explicitly_not_a_winning_backtest():
    report = ledger().report(D("100"))

    assert report.fill_count == 0
    assert report.win_rate_pct is None
    assert report.profit_factor is None
    assert report.total_net_pnl_quote == D("0")
