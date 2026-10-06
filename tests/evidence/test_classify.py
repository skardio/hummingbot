"""Classification tests: all ten classes plus the anti-bias regression."""
from __future__ import annotations

from decimal import Decimal

import pytest

from tools.evidence.classify import (
    HELD_ONLY,
    MATCHED_DUST_CONFIRMED,
    MATCHED_DUST_HEURISTIC,
    MATCHED_EXACT,
    NO_FILL,
    OVERSOLD,
    PARTIAL_OPEN,
    UNMATCHED_BUY,
    UNMATCHED_SELL,
    VIEW_B_CLASSES,
    classify,
    extract_facts,
)

from .conftest import make_custom_info, make_order


def run(policy, custom_info):
    facts = extract_facts(custom_info)
    result = classify(
        facts,
        dust_abs_quote=policy.decimal("classification.dust_abs_quote"),
        dust_rel_pct=policy.decimal("classification.dust_rel_pct"),
        zero_residual_epsilon_base=policy.decimal("classification.zero_residual_epsilon_base"),
        dust_signature_epsilon_quote=policy.decimal("classification.dust_signature_epsilon_quote"),
    )
    return facts, result


def test_matched_exact_with_profit(policy):
    info = make_custom_info([
        make_order("BUY", "100", "100.00", "b1"),
        make_order("SELL", "100", "110.00", "s1"),
    ])
    facts, result = run(policy, info)
    assert result.cls == MATCHED_EXACT
    assert result.layer == 2
    assert result.exact is True
    assert facts.residual_base == Decimal(0)


def test_matched_exact_with_40_percent_loss(policy):
    """Regression: a fully closed losing trade must stay in the strategy view.

    The rejected quote-based rule would have classified this as PARTIAL because
    |sell - buy| / buy = 0.40, removing large losers from view B.
    """
    info = make_custom_info([
        make_order("BUY", "100", "100.00", "b1"),
        make_order("SELL", "100", "60.00", "s1"),
    ])
    facts, result = run(policy, info)
    assert result.cls == MATCHED_EXACT
    assert result.exact is True
    assert result.cls in VIEW_B_CLASSES
    quote_deviation = abs(facts.sell_quote - facts.buy_quote) / facts.buy_quote
    assert quote_deviation == Decimal("0.40")


def test_unmatched_buy(policy):
    info = make_custom_info([make_order("BUY", "100", "100.00", "b1")])
    _, result = run(policy, info)
    assert result.cls == UNMATCHED_BUY
    assert result.layer == 1
    assert result.exact is True


def test_unmatched_sell(policy):
    info = make_custom_info([make_order("SELL", "100", "100.00", "s1")])
    _, result = run(policy, info)
    assert result.cls == UNMATCHED_SELL
    assert result.exact is True


def test_oversold(policy):
    info = make_custom_info([
        make_order("BUY", "50", "50.00", "b1"),
        make_order("SELL", "100", "100.00", "s1"),
    ])
    _, result = run(policy, info)
    assert result.cls == OVERSOLD
    assert result.residual_base < 0


def test_matched_dust_confirmed(policy):
    """The executor's own dust correction is authoritative: no threshold used.

    A residual of 10 base units would normally exceed the heuristic limits, but
    the shortfall in realized_buy_size_quote proves the executor judged it
    unsellable against the real exchange min_order_size.
    """
    info = make_custom_info(
        [
            make_order("BUY", "100", "100.00", "b1"),
            make_order("SELL", "90", "90.00", "s1"),
        ],
        realized_buy_size_quote="90.00",
    )
    _, result = run(policy, info)
    assert result.cls == MATCHED_DUST_CONFIRMED
    assert result.layer == 3
    assert result.exact is True
    assert result.dust_signature is True


def test_matched_dust_heuristic(policy):
    """Residual below both the absolute and relative policy limits."""
    info = make_custom_info([
        make_order("BUY", "1000", "100.00", "b1"),
        make_order("SELL", "997", "99.70", "s1"),
    ])
    _, result = run(policy, info)
    assert result.cls == MATCHED_DUST_HEURISTIC
    assert result.layer == 4
    assert result.exact is False
    assert result.dust_signature is False
    assert result.residual_value_quote < policy.decimal("classification.dust_abs_quote")
    assert result.residual_rel < policy.decimal("classification.dust_rel_pct")


def test_partial_open(policy):
    """A sellable residual remains open: operational, not strategy."""
    info = make_custom_info([
        make_order("BUY", "100", "100.00", "b1"),
        make_order("SELL", "50", "50.00", "s1"),
    ])
    _, result = run(policy, info)
    assert result.cls == PARTIAL_OPEN
    assert result.layer == 4
    assert result.exact is False


def test_no_fill(policy):
    _, result = run(policy, make_custom_info([]))
    assert result.cls == NO_FILL
    assert result.exact is True


def test_held_only(policy):
    held = make_order("BUY", "100", "100.00", "h1")
    info = make_custom_info([held], held_position_orders=[held], realized_buy_size_quote="0")
    _, result = run(policy, info)
    assert result.cls == HELD_ONLY
    assert result.exact is True


def test_held_orders_are_excluded_from_facts(policy):
    """Held orders must not contribute to realised accounting."""
    held = make_order("BUY", "999", "999.00", "h1")
    info = make_custom_info(
        [make_order("BUY", "100", "100.00", "b1"), make_order("SELL", "100", "110.00", "s1"), held],
        held_position_orders=[held],
    )
    facts, result = run(policy, info)
    assert facts.buy_base == Decimal("100")
    assert result.cls == MATCHED_EXACT


@pytest.mark.parametrize(
    "dust_abs,dust_rel,expected",
    [
        ("0.05", "0.01", PARTIAL_OPEN),
        ("5.00", "0.05", MATCHED_DUST_HEURISTIC),
    ],
)
def test_heuristic_depends_on_thresholds(policy, dust_abs, dust_rel, expected):
    """Layer 4 is threshold-dependent by construction; the sweep must catch it."""
    info = make_custom_info([
        make_order("BUY", "1000", "100.00", "b1"),
        make_order("SELL", "997", "99.70", "s1"),
    ])
    facts = extract_facts(info)
    result = classify(
        facts,
        dust_abs_quote=Decimal(dust_abs),
        dust_rel_pct=Decimal(dust_rel),
        zero_residual_epsilon_base=policy.decimal("classification.zero_residual_epsilon_base"),
        dust_signature_epsilon_quote=policy.decimal("classification.dust_signature_epsilon_quote"),
    )
    assert result.cls == expected
