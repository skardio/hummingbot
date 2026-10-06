"""Tests for the reconciliation checks, including the fee-rate denominator."""
from __future__ import annotations

from decimal import Decimal

import pytest

from tools.evidence.reconcile import (
    check_count_conservation,
    check_fee_rate,
    check_leg_identity,
    check_non_negative_fees,
    reconcile,
)

RANGE = (Decimal("0"), Decimal("0.006"))


def test_fee_rate_uses_traded_notional_not_deployed_capital():
    """Kraken: 57.77 fees on 18,239 traded notional is 0.317%, well inside range.

    Dividing by deployed capital (9,345.6) would give 0.62% and falsely fail.
    """
    traded = Decimal("9345.6") + Decimal("8893.5")
    check = check_fee_rate(Decimal("57.77"), traded, RANGE)
    assert check.passed
    assert Decimal("0.0031") < check.value < Decimal("0.0032")

    deployed_only = check_fee_rate(Decimal("57.77"), Decimal("9345.6"), RANGE)
    assert not deployed_only.passed


def test_fee_rate_matches_bitget_schedule():
    traded = Decimal("14915.32") + Decimal("14865.66")
    check = check_fee_rate(Decimal("32.00"), traded, RANGE)
    assert check.passed
    assert Decimal("0.00107") < check.value < Decimal("0.00108")


def test_fee_rate_rejects_implausible_rate():
    assert not check_fee_rate(Decimal("50"), Decimal("1000"), RANGE).passed


def test_fee_rate_skips_when_no_notional():
    check = check_fee_rate(Decimal("0"), Decimal("0"), RANGE)
    assert check.passed
    assert check.value is None


def test_negative_fees_are_rejected_by_default():
    """futures_grid_bitget has SUM(cum_fees_quote) = -0.1 in the real data."""
    assert not check_non_negative_fees(Decimal("-0.1"), allow_negative=False).passed
    assert check_non_negative_fees(Decimal("-0.1"), allow_negative=True).passed


def test_leg_identity_tolerance_scales_with_size():
    # (109 - 100) - 1 = 8, so a net_pnl of 8 is exactly consistent.
    tight = check_leg_identity(
        Decimal("8"), Decimal("100"), Decimal("109"), Decimal("1"),
        residual_rel=Decimal("0.005"), residual_abs=Decimal("0.5"),
    )
    assert tight.passed
    assert tight.value == Decimal("0")

    broken = check_leg_identity(
        Decimal("10"), Decimal("100"), Decimal("105"), Decimal("1"),
        residual_rel=Decimal("0.005"), residual_abs=Decimal("0.5"),
    )
    assert not broken.passed
    assert broken.value == Decimal("6")


def test_count_conservation():
    assert check_count_conservation(10, 10).passed
    assert not check_count_conservation(10, 9).passed


@pytest.mark.parametrize("allow_negative", [True, False])
def test_reconcile_aggregates_all_checks(allow_negative):
    result = reconcile(
        net_pnl=Decimal("-510.32"),
        buy_quote=Decimal("9345.6"),
        sell_quote=Decimal("8893.5"),
        fees=Decimal("57.77"),
        pnl_a=Decimal("-510.32"),
        pnl_b=Decimal("-47.01"),
        pnl_c=Decimal("-463.31"),
        traded_notional=Decimal("18239.1"),
        total_executors=554,
        classified_executors=554,
        residual_rel=Decimal("0.005"),
        residual_abs=Decimal("0.5"),
        abc_tolerance=Decimal("0.01"),
        allow_negative_fees=allow_negative,
        fee_rate_range=RANGE,
    )
    assert {check.name for check in result.checks} == {
        "leg_identity", "abc_identity", "non_negative_fees",
        "fee_rate_plausible", "count_conservation",
    }
    assert result.passed
