"""Data-integrity reconciliation (gate G0 inputs).

Two independent identities must hold before any metric may be reported:

1. ``net_pnl == (sell - buy) - fees`` at cohort level.
2. ``pnl(A) == pnl(B) + pnl(C)`` across the classification views.

Plus fee sanity: no negative fees and a plausible effective rate.

All functions in this module are pure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Check:
    """A single named integrity check."""

    name: str
    passed: bool
    value: Optional[Decimal]
    limit: Optional[Decimal]
    detail: str = ""


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of all data-integrity checks."""

    checks: Tuple[Check, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> Tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.passed)


def leg_identity_residual(
    net_pnl: Decimal,
    buy_quote: Decimal,
    sell_quote: Decimal,
    fees: Decimal,
) -> Decimal:
    """Return ``net_pnl - ((sell - buy) - fees)``.

    Verified empirically on all four populated databases; residuals were below
    0.6 quote on totals of up to 510.
    """
    expected = (sell_quote - buy_quote) - fees
    return net_pnl - expected


def check_leg_identity(
    net_pnl: Decimal,
    buy_quote: Decimal,
    sell_quote: Decimal,
    fees: Decimal,
    residual_rel: Decimal,
    residual_abs: Decimal,
) -> Check:
    residual = leg_identity_residual(net_pnl, buy_quote, sell_quote, fees)
    limit = max(residual_rel * abs(net_pnl), residual_abs)
    return Check(
        name="leg_identity",
        passed=abs(residual) <= limit,
        value=residual,
        limit=limit,
        detail="net_pnl vs (sell - buy) - fees",
    )


def check_abc_identity(
    pnl_a: Decimal,
    pnl_b: Decimal,
    pnl_c: Decimal,
    tolerance: Decimal,
) -> Check:
    """Guarantee that classification reclassifies rather than discards rows."""
    residual = pnl_a - (pnl_b + pnl_c)
    return Check(
        name="abc_identity",
        passed=abs(residual) <= tolerance,
        value=residual,
        limit=tolerance,
        detail="pnl(A) vs pnl(B) + pnl(C)",
    )


def check_non_negative_fees(fees: Decimal, allow_negative: bool) -> Check:
    passed = allow_negative or fees >= 0
    return Check(
        name="non_negative_fees",
        passed=passed,
        value=fees,
        limit=Decimal(0),
        detail="cumulative fees must not be negative",
    )


def check_fee_rate(
    fees: Decimal,
    traded_notional: Decimal,
    rate_range: Tuple[Decimal, Decimal],
) -> Check:
    """Check the effective per-side fee rate against a plausible range.

    The denominator is total traded notional (buy + sell), not deployed capital.
    Fees are charged on both legs, so dividing by deployed capital would roughly
    double the apparent rate and produce false positives. Verified against the
    published schedules: Kraken 0.317%, Bitget 0.107%.

    With no traded notional the check is vacuously true rather than a division
    by zero.
    """
    low, high = rate_range
    if traded_notional <= 0:
        return Check(
            name="fee_rate_plausible",
            passed=True,
            value=None,
            limit=None,
            detail="no traded notional; check skipped",
        )
    rate = fees / traded_notional
    return Check(
        name="fee_rate_plausible",
        passed=low <= rate <= high,
        value=rate,
        limit=high,
        detail=f"fees / (buy + sell) notional must lie within [{low}, {high}]",
    )


def check_count_conservation(total_executors: int, classified: int) -> Check:
    """Every executor must end up in exactly one class."""
    return Check(
        name="count_conservation",
        passed=total_executors == classified,
        value=Decimal(classified - total_executors),
        limit=Decimal(0),
        detail="every executor must be classified exactly once",
    )


def reconcile(
    *,
    net_pnl: Decimal,
    buy_quote: Decimal,
    sell_quote: Decimal,
    fees: Decimal,
    pnl_a: Decimal,
    pnl_b: Decimal,
    pnl_c: Decimal,
    traded_notional: Decimal,
    total_executors: int,
    classified_executors: int,
    residual_rel: Decimal,
    residual_abs: Decimal,
    abc_tolerance: Decimal,
    allow_negative_fees: bool,
    fee_rate_range: Tuple[Decimal, Decimal],
) -> ReconciliationResult:
    """Run every integrity check. Thresholds come from the policy."""
    checks: List[Check] = [
        check_leg_identity(net_pnl, buy_quote, sell_quote, fees, residual_rel, residual_abs),
        check_abc_identity(pnl_a, pnl_b, pnl_c, abc_tolerance),
        check_non_negative_fees(fees, allow_negative_fees),
        check_fee_rate(fees, traded_notional, fee_rate_range),
        check_count_conservation(total_executors, classified_executors),
    ]
    return ReconciliationResult(checks=tuple(checks))
