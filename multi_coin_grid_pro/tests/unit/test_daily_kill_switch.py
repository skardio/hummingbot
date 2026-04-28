"""Unit tests for daily coin kill switch (Item 4)."""
from __future__ import annotations

import time
import unittest
from decimal import Decimal

from multi_coin_grid_pro.core.exit_types import ExitType
from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits


def _make_grm(balance: float = 1000.0, r_unit: float = 5.0) -> GlobalRiskManager:
    limits = RiskLimits(
        max_daily_loss_pct=Decimal("50"),   # high limit so kill-switch logic is isolated
        max_balance_risk_per_trade_pct=Decimal("20"),
        max_total_open_risk_pct=Decimal("80"),
        min_hold_seconds=0,
        exit_cooldown_seconds=0,   # disable exit cooldown so kill-switch is the only gate
        symbol_switch_cooldown_seconds=0,
        consecutive_loss_cooldown_seconds=0,
    )
    grm = GlobalRiskManager(Decimal(str(balance)), limits)
    grm.set_r_unit(r_unit)
    return grm


# Use current time so _reset_if_new_day() never triggers a stale-day reset
T0 = time.time()


class TestDailyKillSwitch(unittest.TestCase):

    def test_not_halved_below_1r(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("ETH-USD", -4.99)
        self.assertFalse(grm.is_coin_halved_today("ETH-USD"))
        self.assertFalse(grm.is_coin_disabled_today("ETH-USD"))

    def test_halved_at_exactly_1r(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("ETH-USD", -5.01)
        self.assertTrue(grm.is_coin_halved_today("ETH-USD"))
        self.assertFalse(grm.is_coin_disabled_today("ETH-USD"))

    def test_disabled_at_2r(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("ETH-USD", -10.01)
        self.assertTrue(grm.is_coin_halved_today("ETH-USD"))
        self.assertTrue(grm.is_coin_disabled_today("ETH-USD"))

    def test_cumulative_pnl_across_multiple_records(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("SOL-USD", -3.0)
        grm.record_coin_pnl("SOL-USD", -3.0)
        # Total = -6.0 → > -1R (5.0) → halved
        self.assertTrue(grm.is_coin_halved_today("SOL-USD"))
        self.assertFalse(grm.is_coin_disabled_today("SOL-USD"))

    def test_win_after_loss_reduces_net_loss(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("BTC-USD", -9.0)
        grm.record_coin_pnl("BTC-USD", 5.0)
        # Net = -4.0 → < -1R → not halved
        self.assertFalse(grm.is_coin_halved_today("BTC-USD"))

    def test_two_coins_are_independent(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("ETH-USD", -10.01)
        # ETH disabled, BTC untouched
        self.assertTrue(grm.is_coin_disabled_today("ETH-USD"))
        self.assertFalse(grm.is_coin_disabled_today("BTC-USD"))

    def test_get_coin_daily_pnl(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("XRP-USD", -3.5)
        grm.record_coin_pnl("XRP-USD", -1.5)
        self.assertAlmostEqual(grm.get_coin_daily_pnl("XRP-USD"), -5.0)

    def test_unknown_coin_not_disabled(self):
        grm = _make_grm(r_unit=5.0)
        self.assertFalse(grm.is_coin_disabled_today("UNKNOWN-USD"))
        self.assertFalse(grm.is_coin_halved_today("UNKNOWN-USD"))

    def test_can_open_trade_blocked_when_disabled(self):
        """is_coin_disabled_today blocks can_open_trade."""
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("DOGE-USD", -10.5)   # > -2R
        result = grm.can_open_trade(
            symbol="DOGE-USD",
            requested_notional=Decimal("50"),
            now=T0,
        )
        self.assertIsNone(result, "Disabled coin must be blocked by can_open_trade")

    def test_day_reset_clears_kill_switch(self):
        grm = _make_grm(r_unit=5.0)
        grm.record_coin_pnl("ETH-USD", -20.0)
        self.assertTrue(grm.is_coin_disabled_today("ETH-USD"))
        # Force a new-day reset by calling can_open_trade with tomorrow's timestamp
        tomorrow_ts = T0 + 86400 + 1
        grm.can_open_trade(
            symbol="ETH-USD",
            requested_notional=Decimal("50"),
            now=tomorrow_ts,
        )
        self.assertFalse(grm.is_coin_disabled_today("ETH-USD"))

    def test_register_close_trade_also_records_coin_pnl(self):
        grm = _make_grm(r_unit=5.0)
        grm.register_open_trade(symbol="AVAX-USD", notional=Decimal("50"), now=T0)
        grm.register_close_trade(
            symbol="AVAX-USD",
            realised_pnl_quote=Decimal("-6"),
            now=T0 + 100,
            exit_type=ExitType.STOP_LOSS,
        )
        # daily PnL should be -6 → halved but not disabled (r_unit=5)
        self.assertTrue(grm.is_coin_halved_today("AVAX-USD"))
        self.assertFalse(grm.is_coin_disabled_today("AVAX-USD"))


if __name__ == "__main__":
    unittest.main()
