"""
Tests for per-coin consecutive loss cooldown.

Bug: Loss cooldown was GLOBAL — one coin's loss blocked ALL coins from trading.
Fix: _consecutive_losses and _last_loss_time are now Dict[str, ...] keyed by symbol.
"""

import unittest
from decimal import Decimal

from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits

# Fixed noon-UTC timestamp to avoid midnight-crossing flakiness
_NOON_UTC = 1_718_452_800.0  # 2024-06-15 12:00:00 UTC


class TestPerCoinLossCooldown(unittest.TestCase):
    """Test that consecutive loss cooldown is per-coin, not global."""

    def setUp(self):
        self.limits = RiskLimits(
            max_daily_loss_pct=Decimal("10.0"),
            max_balance_risk_per_trade_pct=Decimal("50.0"),
            max_total_open_risk_pct=Decimal("80.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=0,       # disable exit cooldown
            symbol_switch_cooldown_seconds=0,  # disable switch cooldown
            consecutive_loss_cooldown_seconds=3600,
        )
        self.manager = GlobalRiskManager(
            reference_balance_quote=Decimal("5000.0"),
            limits=self.limits,
        )

    def test_loss_on_coin_a_does_not_block_coin_b(self):
        """A loss on LINK should NOT block HYPE from trading."""
        now = _NOON_UTC

        # LINK loses
        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-5"), now=now + 120
        )

        check_time = now + 130  # 10s after LINK loss

        # LINK should be blocked (loss cooldown)
        result = self.manager.can_open_trade(
            symbol="LINK-USD", requested_notional=Decimal("100"), now=check_time
        )
        self.assertIsNone(result, "LINK should be blocked by its own loss cooldown")

        # HYPE should NOT be blocked
        result = self.manager.can_open_trade(
            symbol="HYPE-USD", requested_notional=Decimal("100"), now=check_time
        )
        self.assertIsNotNone(result, "HYPE should NOT be blocked by LINK's loss")

    def test_loss_cooldown_expires_per_coin(self):
        """After cooldown expires, the same coin can trade again."""
        now = _NOON_UTC

        self.manager.register_open_trade(symbol="DOGE-USD", notional=Decimal("50"), now=now)
        self.manager.register_close_trade(
            symbol="DOGE-USD", realised_pnl_quote=Decimal("-3"), now=now + 60
        )

        # Still in cooldown
        result = self.manager.can_open_trade(
            symbol="DOGE-USD", requested_notional=Decimal("50"), now=now + 100
        )
        self.assertIsNone(result)

        # After cooldown (3600s)
        result = self.manager.can_open_trade(
            symbol="DOGE-USD", requested_notional=Decimal("50"), now=now + 3700
        )
        self.assertIsNotNone(result)

    def test_consecutive_losses_tracked_per_coin(self):
        """Each coin tracks its own consecutive loss count."""
        now = _NOON_UTC

        # LINK loses twice
        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-2"), now=now + 60
        )
        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now + 3700)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-3"), now=now + 3800
        )

        # HYPE wins
        self.manager.register_open_trade(symbol="HYPE-USD", notional=Decimal("100"), now=now + 100)
        self.manager.register_close_trade(
            symbol="HYPE-USD", realised_pnl_quote=Decimal("10"), now=now + 200
        )

        self.assertEqual(self.manager._consecutive_losses.get("LINK-USD", 0), 2)
        self.assertNotIn("HYPE-USD", self.manager._consecutive_losses)

    def test_win_resets_loss_streak_per_coin(self):
        """A win on one coin resets only THAT coin's streak."""
        now = _NOON_UTC

        # Both coins lose
        self.manager.register_open_trade(symbol="FET-USD", notional=Decimal("80"), now=now)
        self.manager.register_close_trade(
            symbol="FET-USD", realised_pnl_quote=Decimal("-4"), now=now + 60
        )
        self.manager.register_open_trade(symbol="DOGE-USD", notional=Decimal("50"), now=now)
        self.manager.register_close_trade(
            symbol="DOGE-USD", realised_pnl_quote=Decimal("-2"), now=now + 60
        )

        self.assertEqual(self.manager._consecutive_losses.get("FET-USD", 0), 1)
        self.assertEqual(self.manager._consecutive_losses.get("DOGE-USD", 0), 1)

        # FET wins next
        self.manager.register_open_trade(symbol="FET-USD", notional=Decimal("80"), now=now + 3700)
        self.manager.register_close_trade(
            symbol="FET-USD", realised_pnl_quote=Decimal("5"), now=now + 3800
        )

        # FET streak reset, DOGE streak untouched
        self.assertNotIn("FET-USD", self.manager._consecutive_losses)
        self.assertEqual(self.manager._consecutive_losses.get("DOGE-USD", 0), 1)

    def test_reset_daily_loss_clears_all_coin_cooldowns(self):
        """reset_daily_loss() must clear per-coin dicts too."""
        now = _NOON_UTC

        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-10"), now=now + 60
        )
        self.manager.register_open_trade(symbol="DOGE-USD", notional=Decimal("50"), now=now)
        self.manager.register_close_trade(
            symbol="DOGE-USD", realised_pnl_quote=Decimal("-5"), now=now + 60
        )

        self.manager.reset_daily_loss(reason="test")

        self.assertEqual(self.manager._consecutive_losses, {})
        self.assertEqual(self.manager._last_loss_time, {})

    def test_new_day_resets_per_coin_cooldowns(self):
        """_reset_if_new_day() clears per-coin dicts."""
        now = _NOON_UTC

        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-5"), now=now + 60
        )

        self.assertIn("LINK-USD", self.manager._consecutive_losses)

        # Simulate next day (86401 seconds later)
        next_day = now + 86401
        self.manager._reset_if_new_day(next_day)

        self.assertEqual(self.manager._consecutive_losses, {})
        self.assertEqual(self.manager._last_loss_time, {})

    def test_multiple_coins_independent_cooldowns(self):
        """Three coins losing at different times have independent cooldowns."""
        now = _NOON_UTC

        # LINK loses at t=0
        self.manager.register_open_trade(symbol="LINK-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="LINK-USD", realised_pnl_quote=Decimal("-5"), now=now + 60
        )

        # HYPE loses at t=1800
        self.manager.register_open_trade(symbol="HYPE-USD", notional=Decimal("100"), now=now + 1800)
        self.manager.register_close_trade(
            symbol="HYPE-USD", realised_pnl_quote=Decimal("-3"), now=now + 1860
        )

        # DOGE never lost
        check_time = now + 2000  # 2000s after LINK loss, 140s after HYPE loss

        # LINK: 2000s / 3600s cooldown → still blocked
        result = self.manager.can_open_trade(
            symbol="LINK-USD", requested_notional=Decimal("100"), now=check_time
        )
        self.assertIsNone(result, "LINK still in cooldown (2000s < 3600s)")

        # HYPE: 140s / 3600s cooldown → still blocked
        result = self.manager.can_open_trade(
            symbol="HYPE-USD", requested_notional=Decimal("100"), now=check_time
        )
        self.assertIsNone(result, "HYPE still in cooldown (140s < 3600s)")

        # DOGE: no losses → not blocked
        result = self.manager.can_open_trade(
            symbol="DOGE-USD", requested_notional=Decimal("100"), now=check_time
        )
        self.assertIsNotNone(result, "DOGE has no losses, should be allowed")

        # LINK after full cooldown
        result = self.manager.can_open_trade(
            symbol="LINK-USD", requested_notional=Decimal("100"), now=now + 3700
        )
        self.assertIsNotNone(result, "LINK cooldown expired (3700s > 3600s)")


if __name__ == "__main__":
    unittest.main()
