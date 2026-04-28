"""Unit tests for Item 6 — ATR Grid Width Calibrator."""
from __future__ import annotations

import pytest

from multi_coin_grid_pro.scoring.atr_calibrator import ATRCalibrator, ATRSuggestion


def _make_calibrator(coin: str, values: list[float]) -> ATRCalibrator:
    cal = ATRCalibrator(min_samples=5)
    for v in values:
        cal.record(coin, v)
    return cal


# ── Basic API ───────────────────────────────────────────────────────────────


def test_suggest_returns_none_below_min_samples():
    cal = ATRCalibrator(min_samples=5)
    cal.record("BTC-EUR", 1.2)
    assert cal.suggest("BTC-EUR") is None


def test_suggest_returns_none_for_unknown_coin():
    cal = ATRCalibrator()
    assert cal.suggest("UNKNOWN-EUR") is None


def test_suggest_returns_suggestion_after_enough_samples():
    cal = _make_calibrator("ETH-EUR", [1.0, 1.2, 1.4, 1.6, 1.8, 2.0])
    s = cal.suggest("ETH-EUR")
    assert isinstance(s, ATRSuggestion)


def test_suggestion_coin_name():
    cal = _make_calibrator("SOL-EUR", [1.0] * 10)
    s = cal.suggest("SOL-EUR")
    assert s.coin == "SOL-EUR"


def test_suggestion_sample_count():
    cal = _make_calibrator("ADA-EUR", [1.0] * 7)
    s = cal.suggest("ADA-EUR")
    assert s.sample_count == 7


# ── Percentile logic ────────────────────────────────────────────────────────


def test_median_is_middle_value():
    # 10 equal values → median must be that value
    cal = _make_calibrator("XRP-EUR", [2.0] * 10)
    s = cal.suggest("XRP-EUR")
    assert s.atr_pct_median == pytest.approx(2.0)


def test_p75_greater_than_median_for_right_skewed():
    values = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 8.0]
    cal = _make_calibrator("DOT-EUR", values)
    s = cal.suggest("DOT-EUR")
    assert s.atr_pct_p75 >= s.atr_pct_median


def test_p90_greater_than_p75():
    values = [1.0] * 7 + [5.0, 8.0, 10.0]
    cal = _make_calibrator("MATIC-EUR", values)
    s = cal.suggest("MATIC-EUR")
    assert s.atr_pct_p90 >= s.atr_pct_p75


# ── Multiplier bounds ───────────────────────────────────────────────────────


def test_multiplier_down_within_bounds():
    cal = _make_calibrator("BNB-EUR", [2.0] * 10)
    s = cal.suggest("BNB-EUR")
    assert 0.8 <= s.multiplier_down <= 2.0


def test_multiplier_up_within_bounds():
    cal = _make_calibrator("LTC-EUR", [2.0] * 10)
    s = cal.suggest("LTC-EUR")
    assert 1.0 <= s.multiplier_up <= 3.0


def test_high_volatility_note():
    cal = _make_calibrator("MEME-EUR", [6.0] * 10)
    s = cal.suggest("MEME-EUR")
    assert "HIGH_VOLATILITY" in s.note


def test_low_volatility_note():
    cal = _make_calibrator("USDC-EUR", [0.5] * 10)
    s = cal.suggest("USDC-EUR")
    assert "LOW_VOLATILITY" in s.note


def test_normal_volatility_note_is_ok():
    cal = _make_calibrator("ETH-EUR", [2.0] * 10)
    s = cal.suggest("ETH-EUR")
    assert s.note == "OK"


# ── suggest_all ─────────────────────────────────────────────────────────────


def test_suggest_all_only_returns_coins_with_enough_samples():
    cal = ATRCalibrator(min_samples=5)
    for _ in range(3):
        cal.record("ETH-EUR", 2.0)  # Not enough
    for _ in range(6):
        cal.record("BTC-EUR", 1.5)  # Enough
    result = cal.suggest_all()
    assert "BTC-EUR" in result
    assert "ETH-EUR" not in result


def test_suggest_all_empty_when_no_history():
    cal = ATRCalibrator()
    assert cal.suggest_all() == {}


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_record_ignores_zero_or_negative_atr():
    cal = ATRCalibrator(min_samples=2)
    cal.record("XLM-EUR", 0.0)
    cal.record("XLM-EUR", -1.5)
    # No valid samples recorded
    assert cal.suggest("XLM-EUR") is None


def test_history_bounded_by_maxlen():
    """History should not grow unboundedly."""
    from multi_coin_grid_pro.scoring.atr_calibrator import _HISTORY_MAXLEN
    cal = ATRCalibrator()
    for _ in range(_HISTORY_MAXLEN + 50):
        cal.record("LINK-EUR", 1.5)
    # Deque maxlen keeps it bounded
    assert len(cal._history["LINK-EUR"]) == _HISTORY_MAXLEN
