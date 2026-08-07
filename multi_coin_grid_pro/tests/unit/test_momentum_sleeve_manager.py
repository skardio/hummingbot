"""
Unit tests for MomentumSleeveManager (paper mode).
"""

from dataclasses import dataclass, field
from typing import List

import pytest

from multi_coin_grid_pro.execution.momentum_sleeve_manager import (
    _EXIT_MAX_HOLD,
    _EXIT_STOP_LOSS,
    _EXIT_TAKE_PROFIT,
    _EXIT_TRAILING,
    MomentumPosition,
    MomentumSleeveManager,
    build_momentum_sleeve_manager,
)

# ---------------------------------------------------------------------------
# Minimal MomentumCandidate stub
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    symbol: str
    score: float = 80.0
    entry_allowed: bool = True
    regime_at_score: str = "BULL"
    volume_expansion: float = 1.5
    trend_1h: float = 1.0
    trend_4h: float = 2.0
    trend_24h: float = 3.0
    relative_strength: float = 0.5
    spread_pct: float = 0.1
    rsi: float = 55.0
    wick_risk: float = 0.2
    primary_rejection_reason: str = ""
    all_rejection_reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "mode": "paper",
    "max_positions": 2,
    "max_quote_per_position": 25.0,
    "min_score": 75.0,
    "stop_loss_pct": 0.012,
    "take_profit_pct": 0.020,
    "trailing_activation_pct": 0.012,
    "trailing_distance_pct": 0.008,
    "max_hold_minutes": 90,
    "cooldown_minutes": 60,
    "summary_interval_minutes": 60,
}


def make_manager(**overrides) -> MomentumSleeveManager:
    cfg = {**BASE_CONFIG, **overrides}
    return MomentumSleeveManager(cfg)


def make_candidate(**kwargs) -> _Candidate:
    return _Candidate(**kwargs)


NOW = 1_700_000_000.0
PRICE = 1.0  # 1 USD per unit, simplifies math


# ---------------------------------------------------------------------------
# Entry tests
# ---------------------------------------------------------------------------

class TestEntry:
    def test_basic_entry_creates_position(self):
        mgr = make_manager()
        c = make_candidate(symbol="SOL-USD")
        pos = mgr.maybe_enter(c, PRICE, NOW)
        assert pos is not None
        assert pos.trading_pair == "SOL-USD"
        assert pos.entry_price == PRICE
        assert pos.quote_size == 25.0
        assert pos.base_size == pytest.approx(25.0)
        assert pos.score_at_entry == 80.0
        assert pos.regime_at_entry == "BULL"
        assert pos.vol_exp_at_entry == 1.5

    def test_entry_skipped_when_score_below_min(self):
        mgr = make_manager(min_score=75.0)
        c = make_candidate(symbol="SOL-USD", score=70.0)
        pos = mgr.maybe_enter(c, PRICE, NOW)
        assert pos is None
        assert len(mgr.open_positions) == 0

    def test_entry_skipped_when_not_entry_allowed(self):
        mgr = make_manager()
        c = make_candidate(symbol="SOL-USD", entry_allowed=False)
        pos = mgr.maybe_enter(c, PRICE, NOW)
        assert pos is None

    def test_entry_skipped_when_max_positions_reached(self):
        mgr = make_manager(max_positions=1)
        c1 = make_candidate(symbol="SOL-USD")
        c2 = make_candidate(symbol="ETH-USD")
        mgr.maybe_enter(c1, PRICE, NOW)
        pos = mgr.maybe_enter(c2, PRICE, NOW)
        assert pos is None
        assert len(mgr.open_positions) == 1

    def test_no_duplicate_position_same_pair(self):
        mgr = make_manager(max_positions=5)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, PRICE, NOW)
        pos2 = mgr.maybe_enter(c, PRICE, NOW + 60)
        assert pos2 is None
        assert len(mgr.open_positions) == 1

    def test_entry_skipped_during_cooldown(self):
        mgr = make_manager(cooldown_minutes=60)
        c = make_candidate(symbol="SOL-USD")
        # Simulate expired position for this pair
        mgr._cooldowns["SOL-USD"] = NOW + 3600  # expires 1h in future
        pos = mgr.maybe_enter(c, PRICE, NOW)
        assert pos is None

    def test_entry_allowed_after_cooldown_expires(self):
        mgr = make_manager(cooldown_minutes=60)
        c = make_candidate(symbol="SOL-USD")
        mgr._cooldowns["SOL-USD"] = NOW - 1  # already expired
        pos = mgr.maybe_enter(c, PRICE, NOW)
        assert pos is not None

    def test_entry_skipped_invalid_price(self):
        mgr = make_manager()
        c = make_candidate(symbol="SOL-USD")
        pos = mgr.maybe_enter(c, 0.0, NOW)
        assert pos is None

    def test_stop_and_tp_prices_correct(self):
        mgr = make_manager(stop_loss_pct=0.012, take_profit_pct=0.020)
        c = make_candidate(symbol="SOL-USD")
        price = 100.0
        pos = mgr.maybe_enter(c, price, NOW)
        assert pos.stop_loss_price == pytest.approx(100.0 * (1 - 0.012))
        assert pos.take_profit_price == pytest.approx(100.0 * (1 + 0.020))
        assert pos.trailing_activation_price == pytest.approx(100.0 * (1 + 0.012))
        assert pos.trailing_stop_price is None


# ---------------------------------------------------------------------------
# Exit tests
# ---------------------------------------------------------------------------

class TestMaybeExit:
    def _open_position(self, mgr: MomentumSleeveManager, price: float = PRICE) -> MomentumPosition:
        c = make_candidate(symbol="SOL-USD")
        return mgr.maybe_enter(c, price, NOW)

    def test_stop_loss_triggers(self):
        mgr = make_manager(stop_loss_pct=0.012)
        pos = self._open_position(mgr, 100.0)
        reason = mgr.maybe_exit(pos, 100.0 * 0.987, NOW + 60)  # below stop
        assert reason == _EXIT_STOP_LOSS

    def test_take_profit_triggers(self):
        mgr = make_manager(take_profit_pct=0.020)
        pos = self._open_position(mgr, 100.0)
        reason = mgr.maybe_exit(pos, 100.0 * 1.021, NOW + 60)  # above TP
        assert reason == _EXIT_TAKE_PROFIT

    def test_trailing_stop_triggers_after_activation(self):
        mgr = make_manager(trailing_activation_pct=0.012, trailing_distance_pct=0.008)
        pos = self._open_position(mgr, 100.0)
        # Price rises to activate trailing stop (activation at 101.2)
        mgr.update_positions({"SOL-USD": 102.0}, NOW + 60)
        assert pos.trailing_stop_price is not None
        # Now drop below trailing stop
        trail = pos.trailing_stop_price
        reason = mgr.maybe_exit(pos, trail - 0.01, NOW + 120)
        assert reason == _EXIT_TRAILING

    def test_max_hold_triggers(self):
        mgr = make_manager(max_hold_minutes=90)
        pos = self._open_position(mgr, 100.0)
        reason = mgr.maybe_exit(pos, 100.0, NOW + 91 * 60)  # 91 min > 90
        assert reason == _EXIT_MAX_HOLD

    def test_no_exit_in_normal_conditions(self):
        mgr = make_manager()
        pos = self._open_position(mgr, 100.0)
        reason = mgr.maybe_exit(pos, 100.5, NOW + 60)
        assert reason is None

    def test_stop_loss_exact_boundary(self):
        mgr = make_manager(stop_loss_pct=0.012)
        pos = self._open_position(mgr, 100.0)
        stop = pos.stop_loss_price
        # At exactly stop price → triggered
        reason = mgr.maybe_exit(pos, stop, NOW + 60)
        assert reason == _EXIT_STOP_LOSS


# ---------------------------------------------------------------------------
# update_positions tests
# ---------------------------------------------------------------------------

class TestUpdatePositions:
    def test_stop_loss_closes_position(self):
        mgr = make_manager(stop_loss_pct=0.012)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 100.0, NOW)
        closed = mgr.update_positions({"SOL-USD": 98.0}, NOW + 60)
        assert len(closed) == 1
        assert closed[0].exit_reason == _EXIT_STOP_LOSS
        assert len(mgr.open_positions) == 0
        assert len(mgr.closed_positions) == 1

    def test_pnl_calculated_correctly_on_stop(self):
        mgr = make_manager(stop_loss_pct=0.05, max_quote_per_position=100.0)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 10.0, NOW)  # 100 quote → 10 base
        closed = mgr.update_positions({"SOL-USD": 9.0}, NOW + 60)
        pos = closed[0]
        # pnl = (9.0 - 10.0) * 10.0 base = -10 quote
        assert pos.paper_pnl_quote == pytest.approx(-10.0, abs=1e-4)
        assert pos.paper_pnl_pct == pytest.approx(-10.0, abs=1e-3)

    def test_missing_price_skips_without_crash(self):
        mgr = make_manager()
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 100.0, NOW)
        closed = mgr.update_positions({}, NOW + 60)  # no price for SOL-USD
        assert closed == []
        assert len(mgr.open_positions) == 1  # still open

    def test_cooldown_set_after_exit(self):
        mgr = make_manager(cooldown_minutes=60, stop_loss_pct=0.012)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 100.0, NOW)
        mgr.update_positions({"SOL-USD": 85.0}, NOW + 60)
        assert "SOL-USD" in mgr._cooldowns
        assert mgr._cooldowns["SOL-USD"] > NOW

    def test_trailing_stop_ratchets_up(self):
        # Large TP so we don't accidentally close the position while testing trailing
        mgr = make_manager(trailing_activation_pct=0.01, trailing_distance_pct=0.01,
                           take_profit_pct=0.50)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 100.0, NOW)
        # Rise to 101.5 → above activation (101.0), trailing activates
        mgr.update_positions({"SOL-USD": 101.5}, NOW + 60)
        pos = mgr.open_positions["SOL-USD"]
        trail1 = pos.trailing_stop_price
        assert trail1 is not None
        # Rise further to 105 → trailing should move up
        mgr.update_positions({"SOL-USD": 105.0}, NOW + 120)
        trail2 = pos.trailing_stop_price
        assert trail2 > trail1

    def test_excursion_tracking(self):
        # Large TP and wide trailing so position stays open during the pullback
        mgr = make_manager(take_profit_pct=0.50, trailing_distance_pct=0.05)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 100.0, NOW)
        mgr.update_positions({"SOL-USD": 103.0}, NOW + 60)  # +3%
        mgr.update_positions({"SOL-USD": 101.0}, NOW + 120)  # back down, stays above 103*0.95=97.85
        pos = mgr.open_positions["SOL-USD"]
        assert pos.max_favorable_excursion_pct == pytest.approx(3.0, abs=0.01)


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_no_trades(self):
        mgr = make_manager()
        s = mgr.get_summary()
        assert s["total_trades"] == 0
        assert s["win_rate_pct"] is None
        assert s["total_paper_pnl_quote"] == 0.0

    def test_summary_after_winning_trade(self):
        mgr = make_manager(stop_loss_pct=0.05, take_profit_pct=0.10, max_quote_per_position=100.0)
        c = make_candidate(symbol="SOL-USD")
        mgr.maybe_enter(c, 10.0, NOW)
        mgr.update_positions({"SOL-USD": 11.0}, NOW + 60)  # +10% → TP
        s = mgr.get_summary()
        assert s["total_trades"] == 1
        assert s["win_rate_pct"] == 100.0
        assert s["total_paper_pnl_quote"] > 0

    def test_summary_log_respects_interval(self, caplog):
        import logging
        mgr = make_manager(summary_interval_minutes=60)
        # First call — should log (last_summary is 0)
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.execution.momentum_sleeve_manager"):
            mgr.log_summary_if_due(NOW)
        assert any("[MOMENTUM_PAPER_SUMMARY]" in r.message for r in caplog.records)

        caplog.clear()
        # Second call within interval — should NOT log
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.execution.momentum_sleeve_manager"):
            mgr.log_summary_if_due(NOW + 30 * 60)
        assert not any("[MOMENTUM_PAPER_SUMMARY]" in r.message for r in caplog.records)

        caplog.clear()
        # Third call after interval — should log again
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.execution.momentum_sleeve_manager"):
            mgr.log_summary_if_due(NOW + 61 * 60)
        assert any("[MOMENTUM_PAPER_SUMMARY]" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# build_momentum_sleeve_manager factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_returns_manager_for_paper_mode(self):
        cfg = {**BASE_CONFIG, "mode": "paper"}
        mgr = build_momentum_sleeve_manager(cfg)
        assert isinstance(mgr, MomentumSleeveManager)

    def test_returns_none_for_detect_only(self):
        cfg = {**BASE_CONFIG, "mode": "detect_only"}
        mgr = build_momentum_sleeve_manager(cfg)
        assert mgr is None

    def test_returns_none_for_non_dict(self):
        mgr = build_momentum_sleeve_manager("paper")
        assert mgr is None
