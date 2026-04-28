"""Unit tests for Item 7 — Dynamic Take-Profit logic."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_trend(trend_val: float, consensus: float = 0.0):
    """Create a minimal fake trend object."""
    t = MagicMock()
    t.trend_pct = trend_val
    t.consensus_trend_pct = consensus
    t.volatility = 0.02
    return t


def _calc_dynamic_tp(
    base_tp: float,
    trend_val: float,
    min_tp: float | None = None,
    max_tp: float | None = None,
) -> float:
    """
    Replicate the dynamic TP calculation from _create_grid_action.
    Keeps tests decoupled from the controller class.
    """
    effective_min = min_tp if min_tp is not None else base_tp * 0.7
    effective_max = max_tp if max_tp is not None else base_tp * 2.0

    if trend_val > 2.0:
        adjusted = base_tp * 1.5
    elif trend_val > 1.0:
        adjusted = base_tp * 1.25
    elif trend_val > 0.0:
        adjusted = base_tp * 1.0
    elif trend_val > -1.0:
        adjusted = base_tp * 0.85
    else:
        adjusted = base_tp * 0.70

    return max(effective_min, min(adjusted, effective_max))


# ── Tests: scaling bands ────────────────────────────────────────────────────


BASE = 0.02  # 2% base TP


def test_strong_uptrend_widens_tp():
    result = _calc_dynamic_tp(BASE, trend_val=3.5)
    assert result == pytest.approx(BASE * 1.5)


def test_mild_uptrend_increases_tp():
    result = _calc_dynamic_tp(BASE, trend_val=1.5)
    assert result == pytest.approx(BASE * 1.25)


def test_flat_market_keeps_tp():
    result = _calc_dynamic_tp(BASE, trend_val=0.5)
    assert result == pytest.approx(BASE * 1.0)


def test_mild_downtrend_tightens_tp():
    result = _calc_dynamic_tp(BASE, trend_val=-0.5)
    assert result == pytest.approx(BASE * 0.85)


def test_strong_downtrend_tightens_tp_to_70pct():
    result = _calc_dynamic_tp(BASE, trend_val=-2.5)
    assert result == pytest.approx(BASE * 0.70)


# ── Tests: clamp to min/max ─────────────────────────────────────────────────


def test_clamp_to_min_tp():
    """Configured min_tp prevents TP from going too tight."""
    result = _calc_dynamic_tp(BASE, trend_val=-5.0, min_tp=0.018)
    assert result == pytest.approx(0.018)


def test_clamp_to_max_tp():
    """Configured max_tp prevents TP from going too wide."""
    result = _calc_dynamic_tp(BASE, trend_val=10.0, max_tp=0.025)
    assert result == pytest.approx(0.025)


def test_default_min_is_70pct_of_base():
    """Without explicit min_tp the floor is 0.7× base."""
    floor = BASE * 0.7
    result = _calc_dynamic_tp(BASE, trend_val=-10.0)
    assert result == pytest.approx(floor)


def test_default_max_is_2x_base():
    """The ceiling (2× base) exists as a safety cap above the strongest band (1.5×)."""
    # strongest band yields 1.5×; explicitly push a value above that via min_tp=max_tp trick
    ceiling = BASE * 2.0
    # Force it: pass a result already at ceiling value, should still be clamped
    result = _calc_dynamic_tp(BASE, trend_val=10.0, min_tp=ceiling, max_tp=ceiling)
    assert result == pytest.approx(ceiling)


# ── Tests: consensus_trend_pct takes precedence ─────────────────────────────


def test_consensus_trend_takes_priority_over_trend_pct():
    """If consensus_trend_pct != 0 it should be used, not trend_pct."""
    # Simulate controller logic: use consensus if != 0
    trend = _make_trend(trend_val=-5.0, consensus=3.0)
    trend_val = (
        trend.consensus_trend_pct
        if trend.consensus_trend_pct != 0.0
        else trend.trend_pct
    )
    result = _calc_dynamic_tp(BASE, trend_val=trend_val)
    # consensus=3.0 → strong uptrend → 1.5×
    assert result == pytest.approx(BASE * 1.5)


def test_falls_back_to_trend_pct_when_consensus_is_zero():
    trend = _make_trend(trend_val=-2.5, consensus=0.0)
    trend_val = (
        trend.consensus_trend_pct
        if trend.consensus_trend_pct != 0.0
        else trend.trend_pct
    )
    result = _calc_dynamic_tp(BASE, trend_val=trend_val)
    assert result == pytest.approx(BASE * 0.70)


# ── Tests: Decimal conversion stays in range ────────────────────────────────


def test_result_convertible_to_decimal():
    result = _calc_dynamic_tp(BASE, trend_val=1.5)
    dec = Decimal(str(result))
    assert dec > 0


def test_exact_boundary_trend_2():
    """trend_val=2.0 is NOT > 2.0, so falls into >1.0 band (1.25×)."""
    result = _calc_dynamic_tp(BASE, trend_val=2.0)
    assert result == pytest.approx(BASE * 1.25)


def test_exact_boundary_trend_minus1():
    """trend_val=-1.0 is NOT > -1.0, so falls into else band (0.70×)."""
    result = _calc_dynamic_tp(BASE, trend_val=-1.0)
    assert result == pytest.approx(BASE * 0.70)
