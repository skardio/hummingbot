"""Unit tests for exit-type cooldowns (Item 2)."""
from __future__ import annotations

import unittest
from decimal import Decimal

from multi_coin_grid_pro.core.exit_types import ExitType, cooldown_for_exit, seconds_until_eod_utc
from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits


def _make_grm(balance: float = 1000.0) -> GlobalRiskManager:
    limits = RiskLimits(
        max_daily_loss_pct=Decimal("10"),
        max_balance_risk_per_trade_pct=Decimal("20"),
        max_total_open_risk_pct=Decimal("80"),
        min_hold_seconds=0,
        exit_cooldown_seconds=300,   # 5 min default
        symbol_switch_cooldown_seconds=0,
        consecutive_loss_cooldown_seconds=0,
    )
    return GlobalRiskManager(Decimal(str(balance)), limits)


T0 = 1_745_000_000.0   # arbitrary fixed timestamp (in UTC daytime)


class TestExitTypeCooldownSeconds(unittest.TestCase):

    def test_take_profit_cooldown(self):
        result = cooldown_for_exit(ExitType.TAKE_PROFIT, T0)
        self.assertEqual(result, 15 * 60)

    def test_stop_loss_cooldown(self):
        result = cooldown_for_exit(ExitType.STOP_LOSS, T0)
        self.assertEqual(result, 4 * 60 * 60)

    def test_small_loss_cooldown(self):
        result = cooldown_for_exit(ExitType.SMALL_LOSS, T0)
        self.assertEqual(result, 60 * 60)

    def test_trend_exit_cooldown_is_eod(self):
        result = cooldown_for_exit(ExitType.TREND_EXIT, T0)
        self.assertGreater(result, 0)
        self.assertLessEqual(result, 86400)

    def test_unknown_cooldown_is_short(self):
        result = cooldown_for_exit(ExitType.UNKNOWN, T0)
        self.assertEqual(result, 5 * 60)

    def test_seconds_until_eod_range(self):
        result = seconds_until_eod_utc(T0)
        self.assertGreater(result, 0)
        self.assertLessEqual(result, 86400)


class TestGlobalRiskManagerExitTypeCooldowns(unittest.TestCase):

    def test_blocked_during_stop_loss_cooldown(self):
        grm = _make_grm()
        grm.note_exit("ETH-USD", T0, exit_type=ExitType.STOP_LOSS)

        # 30 minutes later — still within 4h cooldown
        elapsed_ts = T0 + 30 * 60
        result = grm.can_open_trade(
            symbol="ETH-USD",
            requested_notional=Decimal("50"),
            now=elapsed_ts,
        )
        self.assertIsNone(result, "Should be blocked 30min after SL exit (cooldown=4h)")

    def test_allowed_after_take_profit_cooldown(self):
        grm = _make_grm()
        grm.note_exit("BTC-USD", T0, exit_type=ExitType.TAKE_PROFIT)

        # 16 minutes later — past 15-min TP cooldown
        elapsed_ts = T0 + 16 * 60
        result = grm.can_open_trade(
            symbol="BTC-USD",
            requested_notional=Decimal("50"),
            now=elapsed_ts,
        )
        self.assertIsNotNone(result, "Should be allowed 16min after TP exit (cooldown=15min)")

    def test_blocked_before_take_profit_cooldown_expires(self):
        grm = _make_grm()
        grm.note_exit("BTC-USD", T0, exit_type=ExitType.TAKE_PROFIT)

        # 10 minutes later — within 15-min TP cooldown
        elapsed_ts = T0 + 10 * 60
        result = grm.can_open_trade(
            symbol="BTC-USD",
            requested_notional=Decimal("50"),
            now=elapsed_ts,
        )
        self.assertIsNone(result, "Should be blocked 10min after TP exit (cooldown=15min)")

    def test_small_loss_cooldown_one_hour(self):
        grm = _make_grm()
        grm.note_exit("SOL-USD", T0, exit_type=ExitType.SMALL_LOSS)

        # 59 minutes — still blocked
        result_59 = grm.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=T0 + 59 * 60,
        )
        self.assertIsNone(result_59, "Should be blocked 59min after SMALL_LOSS")

        # 61 minutes — unblocked
        result_61 = grm.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=T0 + 61 * 60,
        )
        self.assertIsNotNone(result_61, "Should be allowed 61min after SMALL_LOSS")

    def test_coins_in_exit_cooldown_shows_exit_type_duration(self):
        grm = _make_grm()
        grm.note_exit("XRP-USD", T0, exit_type=ExitType.STOP_LOSS)

        remaining = grm.coins_in_exit_cooldown(T0 + 60)
        self.assertIn("XRP-USD", remaining)
        # Should be close to 4h - 60s
        self.assertAlmostEqual(remaining["XRP-USD"], 4 * 3600 - 60, delta=5)

    def test_register_close_trade_uses_exit_type(self):
        grm = _make_grm()
        grm.register_open_trade(
            symbol="AVAX-USD", notional=Decimal("50"), now=T0
        )
        grm.register_close_trade(
            symbol="AVAX-USD",
            realised_pnl_quote=Decimal("-3"),
            now=T0 + 100,
            exit_type=ExitType.STOP_LOSS,
        )
        # 1h later: blocked (4h SL cooldown)
        result = grm.can_open_trade(
            symbol="AVAX-USD",
            requested_notional=Decimal("50"),
            now=T0 + 3600,
        )
        self.assertIsNone(result)
        # Verify exit type stored
        self.assertEqual(grm.get_exit_type("AVAX-USD"), ExitType.STOP_LOSS)


if __name__ == "__main__":
    unittest.main()
