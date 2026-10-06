"""Metric and reconciliation identity tests."""
from __future__ import annotations

from decimal import Decimal

from tools.evidence.classify import PHANTOM_PROFIT_CLASSES, VIEW_B_CLASSES, VIEW_C_CLASSES
from tools.evidence.metrics import compute_metrics
from tools.evidence.reconcile import check_abc_identity, leg_identity_residual

from .conftest import build_record, make_custom_info, make_order


def mixed_population(policy):
    """One executor of every class, with deliberately varied PnL."""
    return [
        build_record(
            policy,
            executor_id="matched-win",
            day_offset=0,
            net_pnl="10.00",
            fees="0.30",
            custom_info=make_custom_info([
                make_order("BUY", "100", "100.00", "b1"),
                make_order("SELL", "100", "110.30", "s1"),
            ]),
        ),
        build_record(
            policy,
            executor_id="matched-loss",
            day_offset=1,
            trading_pair="SOL-USD",
            net_pnl="-40.00",
            fees="0.20",
            custom_info=make_custom_info([
                make_order("BUY", "100", "100.00", "b1"),
                make_order("SELL", "100", "60.00", "s1"),
            ]),
        ),
        build_record(
            policy,
            executor_id="unmatched-buy",
            day_offset=2,
            trading_pair="UNI-USD",
            close_type=8,
            net_pnl="-77.07",
            fees="0.10",
            custom_info=make_custom_info([make_order("BUY", "100", "76.97", "b1")]),
        ),
        build_record(
            policy,
            executor_id="unmatched-sell",
            day_offset=3,
            trading_pair="TIA-USD",
            close_type=11,
            net_pnl="22.90",
            fees="0.08",
            custom_info=make_custom_info([make_order("SELL", "100", "22.98", "s1")]),
        ),
        build_record(
            policy,
            executor_id="no-fill",
            day_offset=4,
            trading_pair="PEPE-USD",
            close_type=7,
            net_pnl="0",
            fees="0",
            custom_info=make_custom_info([]),
        ),
    ]


def test_abc_identity_holds(policy):
    bundle = compute_metrics(mixed_population(policy))
    a, b, c = bundle.views["A"], bundle.views["B"], bundle.views["C"]
    assert a.net_pnl == b.net_pnl + c.net_pnl
    assert a.n == b.n + c.n
    assert a.fees == b.fees + c.fees


def test_abc_identity_check_detects_a_break(policy):
    ok = check_abc_identity(Decimal("10"), Decimal("6"), Decimal("4"), Decimal("0.01"))
    assert ok.passed
    broken = check_abc_identity(Decimal("10"), Decimal("6"), Decimal("3"), Decimal("0.01"))
    assert not broken.passed
    assert broken.value == Decimal("1")


def test_views_partition_every_record(policy):
    records = mixed_population(policy)
    bundle = compute_metrics(records)
    in_b = [r for r in records if r.cls in VIEW_B_CLASSES]
    in_c = [r for r in records if r.cls in VIEW_C_CLASSES]
    assert len(in_b) + len(in_c) == len(records)
    assert not set(VIEW_B_CLASSES) & set(VIEW_C_CLASSES)
    assert sum(bundle.class_distribution.values()) == len(records)


def test_gross_equals_net_plus_fees(policy):
    bundle = compute_metrics(mixed_population(policy))
    for view in bundle.views.values():
        assert view.gross_pnl == view.net_pnl + view.fees


def test_no_double_fee_deduction(policy):
    """net_pnl_quote is already net of fees; subtracting again must be visible."""
    record = build_record(
        policy,
        net_pnl="9.70",
        fees="0.30",
        custom_info=make_custom_info([
            make_order("BUY", "100", "100.00", "b1"),
            make_order("SELL", "100", "110.00", "s1"),
        ]),
    )
    bundle = compute_metrics([record])
    view = bundle.views["A"]
    assert view.net_pnl == Decimal("9.70")
    assert view.gross_pnl == Decimal("10.00")
    assert view.gross_pnl != view.net_pnl - view.fees


def test_phantom_profit_never_counts_as_a_winner(policy):
    """UNMATCHED_SELL profit originates from a purchase booked elsewhere."""
    record = build_record(
        policy,
        executor_id="phantom",
        net_pnl="22.90",
        custom_info=make_custom_info([make_order("SELL", "100", "22.98", "s1")]),
    )
    assert record.cls in PHANTOM_PROFIT_CLASSES
    assert record.net_pnl_quote > 0
    assert record.is_winner is False
    bundle = compute_metrics([record])
    assert bundle.views["A"].n_winners == 0


def test_deployed_capital_excludes_sell_leg(policy):
    """filled_amount_quote double-counts a round trip; deployed capital must not."""
    record = build_record(
        policy,
        custom_info=make_custom_info([
            make_order("BUY", "100", "100.00", "b1"),
            make_order("SELL", "100", "110.00", "s1"),
        ]),
    )
    assert record.filled_amount_quote == Decimal("210.00")
    assert record.deployed_capital == Decimal("100.00")


def test_leg_identity_residual_matches_real_world_shape():
    """net_pnl == (sell - buy) - fees, the identity verified on real databases."""
    residual = leg_identity_residual(
        net_pnl=Decimal("-510.32"),
        buy_quote=Decimal("9345.6"),
        sell_quote=Decimal("8893.5"),
        fees=Decimal("57.8"),
    )
    assert abs(residual) < Decimal("0.5")


def test_operational_share_and_unmatched_rate(policy):
    bundle = compute_metrics(mixed_population(policy))
    assert bundle.operational_share_of_total is not None
    assert bundle.unmatched_buy_rate == Decimal(1) / Decimal(5)
    assert bundle.class_distribution["UNMATCHED_BUY"] == 1


def test_drawdown_is_pnl_sequence_not_equity(policy):
    records = [
        build_record(policy, executor_id="a", day_offset=0, net_pnl="10",
                     custom_info=make_custom_info([
                         make_order("BUY", "10", "10.00", "b1"),
                         make_order("SELL", "10", "20.00", "s1")])),
        build_record(policy, executor_id="b", day_offset=1, net_pnl="-25",
                     custom_info=make_custom_info([
                         make_order("BUY", "10", "10.00", "b1"),
                         make_order("SELL", "10", "5.00", "s1")])),
        build_record(policy, executor_id="c", day_offset=2, net_pnl="5",
                     custom_info=make_custom_info([
                         make_order("BUY", "10", "10.00", "b1"),
                         make_order("SELL", "10", "15.00", "s1")])),
    ]
    bundle = compute_metrics(records)
    assert bundle.views["A"].pnl_sequence_drawdown == Decimal("-25")
    assert bundle.views["A"].max_consecutive_losses == 1


def test_empty_population_is_safe(policy):
    bundle = compute_metrics([])
    assert bundle.views["A"].n == 0
    assert bundle.views["A"].expectancy_per_trade is None
    assert bundle.operational_share_of_total is None


def test_daily_grouping_only_covers_view_b(policy):
    bundle = compute_metrics(mixed_population(policy))
    total_in_days = sum(len(values) for values in bundle.daily_pnl_matched.values())
    assert total_in_days == bundle.views["B"].n
