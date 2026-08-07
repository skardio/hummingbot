# test_signal_entry_levels.py — unit tests voor compute_entry_levels (US-204/205)
import pytest

from multi_coin_grid_pro.signals.momentum_config import EntryConfig
from multi_coin_grid_pro.signals.momentum_entry_levels import EntryLevels, compute_entry_levels


def _cfg(**kwargs) -> EntryConfig:
    defaults = dict(
        entry_below_bid_pct=0.3,
        entry_above_ask_pct=0.2,
        max_chase_above_entry_max_pct=0.8,
        stop_below_entry_min_pct=1.5,
        tp1_above_entry_max_pct=1.2,
        tp2_above_entry_max_pct=2.5,
    )
    defaults.update(kwargs)
    return EntryConfig(**defaults)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestComputeEntryLevels:
    def test_returns_entry_levels_dataclass(self):
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert isinstance(result, EntryLevels)

    def test_entry_min_below_bid(self):
        # entry_min = bid * (1 - 0.3/100) = 1.000 * 0.997 = 0.997
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert abs(result.entry_min - 0.997) < 1e-9

    def test_entry_max_above_ask(self):
        # entry_max = ask * (1 + 0.2/100) = 1.010 * 1.002 = 1.01202
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert abs(result.entry_max - 1.010 * 1.002) < 1e-9

    def test_max_chase_above_entry_max(self):
        # max_chase = entry_max * (1 + 0.8/100)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        expected = result.entry_max * 1.008
        assert abs(result.max_chase_price - expected) < 1e-9

    def test_stop_below_entry_min(self):
        # stop = entry_min * (1 - 1.5/100)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        expected = result.entry_min * (1 - 1.5 / 100)
        assert abs(result.invalidation_price - expected) < 1e-9

    def test_tp1_above_entry_max(self):
        # tp1 = entry_max * (1 + 1.2/100)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        expected = result.entry_max * 1.012
        assert abs(result.take_profit_1 - expected) < 1e-9

    def test_tp2_above_entry_max(self):
        # tp2 = entry_max * (1 + 2.5/100)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        expected = result.entry_max * 1.025
        assert abs(result.take_profit_2 - expected) < 1e-9

    def test_tp2_greater_than_tp1(self):
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert result.take_profit_2 > result.take_profit_1

    def test_entry_min_less_than_entry_max(self):
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert result.entry_min < result.entry_max

    def test_stop_less_than_entry_min(self):
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert result.invalidation_price < result.entry_min

    def test_max_chase_greater_than_entry_max(self):
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=_cfg())
        assert result is not None
        assert result.max_chase_price > result.entry_max


# ---------------------------------------------------------------------------
# Edge cases — ongeldige bid/ask
# ---------------------------------------------------------------------------

class TestInvalidBidAsk:
    def test_returns_none_when_bid_is_zero(self):
        result = compute_entry_levels(bid=0.0, ask=1.010, cfg=_cfg())
        assert result is None

    def test_returns_none_when_ask_is_zero(self):
        result = compute_entry_levels(bid=1.000, ask=0.0, cfg=_cfg())
        assert result is None

    def test_returns_none_when_bid_negative(self):
        result = compute_entry_levels(bid=-0.5, ask=1.010, cfg=_cfg())
        assert result is None

    def test_returns_none_when_ask_negative(self):
        result = compute_entry_levels(bid=1.000, ask=-1.0, cfg=_cfg())
        assert result is None

    def test_returns_none_when_both_zero(self):
        result = compute_entry_levels(bid=0.0, ask=0.0, cfg=_cfg())
        assert result is None


# ---------------------------------------------------------------------------
# Config variations
# ---------------------------------------------------------------------------

class TestConfigVariations:
    def test_wider_entry_zone(self):
        cfg = _cfg(entry_below_bid_pct=1.0, entry_above_ask_pct=1.0)
        result = compute_entry_levels(bid=1.000, ask=1.000, cfg=cfg)
        assert result is not None
        assert abs(result.entry_min - 0.990) < 1e-9
        assert abs(result.entry_max - 1.010) < 1e-9

    def test_tight_stop(self):
        cfg = _cfg(stop_below_entry_min_pct=0.5)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=cfg)
        assert result is not None
        expected_stop = result.entry_min * (1 - 0.5 / 100)
        assert abs(result.invalidation_price - expected_stop) < 1e-9

    def test_high_tp(self):
        cfg = _cfg(tp1_above_entry_max_pct=5.0, tp2_above_entry_max_pct=10.0)
        result = compute_entry_levels(bid=1.000, ask=1.010, cfg=cfg)
        assert result is not None
        assert result.take_profit_1 > result.entry_max * 1.04
        assert result.take_profit_2 > result.take_profit_1

    @pytest.mark.parametrize("price", [0.00001, 0.001, 0.5, 100, 10000, 50000])
    def test_works_for_various_price_magnitudes(self, price):
        result = compute_entry_levels(bid=price * 0.999, ask=price, cfg=_cfg())
        assert result is not None
        assert result.entry_min > 0
        assert result.entry_max > result.entry_min
