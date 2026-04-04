"""
Unit tests for PnL Reconciliation Feature

Tests the reset_daily_loss() and adjust_daily_loss() methods in GlobalRiskManager,
which are used to reconcile tracked PnL with actual exchange fills.

Bug context:
- Grid executor sometimes misses fill events (websocket disconnect, restart)
- This causes false unrealized losses that block trading via max_daily_loss_pct
- Reconciliation detects when tracked loss >> actual loss and corrects it
"""
import time
import unittest
from decimal import Decimal

from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits


class TestResetDailyLoss(unittest.TestCase):
    """Test reset_daily_loss() method"""

    def setUp(self):
        """Set up test fixtures"""
        self.limits = RiskLimits(
            max_daily_loss_pct=Decimal("5.0"),
            max_balance_risk_per_trade_pct=Decimal("50.0"),
            max_total_open_risk_pct=Decimal("80.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=300,
            symbol_switch_cooldown_seconds=120,
            consecutive_loss_cooldown_seconds=600,
        )
        self.manager = GlobalRiskManager(
            reference_balance_quote=Decimal("1000.0"),
            limits=self.limits
        )

    def test_reset_daily_loss_clears_loss(self):
        """reset_daily_loss() should set daily loss to zero"""
        # Simulate a loss trade
        now = time.time()
        self.manager.register_open_trade(symbol="BTC-EUR", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="BTC-EUR",
            realised_pnl_quote=Decimal("-50.0"),  # $50 loss
            now=now + 60
        )

        # Verify loss is tracked
        self.assertEqual(self.manager._daily_loss_quote, Decimal("50.0"))
        self.assertEqual(self.manager._consecutive_losses.get("BTC-EUR", 0), 1)

        # Reset
        self.manager.reset_daily_loss(reason="test_reconciliation")

        # Verify cleared
        self.assertEqual(self.manager._daily_loss_quote, Decimal("0"))
        self.assertEqual(self.manager._daily_realised_pnl_quote, Decimal("0"))
        self.assertEqual(self.manager._consecutive_losses, {})
        self.assertEqual(self.manager._last_loss_time, {})

    def test_reset_daily_loss_unblocks_trading(self):
        """After reset, trading should be allowed again"""
        now = time.time()

        # Create enough loss to block trading (5% of 1000 = $50)
        self.manager.register_open_trade(symbol="BTC-EUR", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="BTC-EUR",
            realised_pnl_quote=Decimal("-60.0"),  # $60 loss = 6% > 5% limit
            now=now + 60
        )

        # Skip cooldown
        now += 700

        # Verify blocked
        result = self.manager.can_open_trade(
            symbol="ETH-EUR",
            requested_notional=Decimal("100"),
            now=now
        )
        self.assertIsNone(result)  # Blocked due to daily loss

        # Reset loss
        self.manager.reset_daily_loss(reason="external_fill_reconciliation")

        # Verify unblocked
        result = self.manager.can_open_trade(
            symbol="ETH-EUR",
            requested_notional=Decimal("100"),
            now=now
        )
        self.assertIsNotNone(result)  # Should be allowed now

    def test_reset_preserves_open_allocations(self):
        """reset_daily_loss() should NOT affect open positions"""
        now = time.time()

        # Open a position
        self.manager.register_open_trade(symbol="SOL-EUR", notional=Decimal("200"), now=now)

        # Add some loss
        self.manager.register_open_trade(symbol="BTC-EUR", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="BTC-EUR",
            realised_pnl_quote=Decimal("-30.0"),
            now=now + 30
        )

        # Reset loss
        self.manager.reset_daily_loss(reason="test")

        # SOL position should still exist
        self.assertIn("SOL-EUR", self.manager._open_allocations)
        self.assertEqual(
            self.manager._open_allocations["SOL-EUR"].notional_quote,
            Decimal("200")
        )


class TestAdjustDailyLoss(unittest.TestCase):
    """Test adjust_daily_loss() method"""

    def setUp(self):
        """Set up test fixtures"""
        self.limits = RiskLimits(
            max_daily_loss_pct=Decimal("10.0"),
            max_balance_risk_per_trade_pct=Decimal("50.0"),
            max_total_open_risk_pct=Decimal("80.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=300,
            symbol_switch_cooldown_seconds=120,
            consecutive_loss_cooldown_seconds=600,
        )
        self.manager = GlobalRiskManager(
            reference_balance_quote=Decimal("400.0"),  # Match USD config
            limits=self.limits
        )

    def test_adjust_reduces_loss(self):
        """adjust_daily_loss() should reduce tracked loss"""
        now = time.time()

        # Simulate tracked loss of $75 (from missed sell)
        self.manager.register_open_trade(symbol="HBAR-USD", notional=Decimal("75"), now=now)
        self.manager.register_close_trade(
            symbol="HBAR-USD",
            realised_pnl_quote=Decimal("-75.0"),  # Bug: missed sell, shows as loss
            now=now + 60
        )

        self.assertEqual(self.manager._daily_loss_quote, Decimal("75.0"))

        # Reconcile: Actual loss was only $10
        adjustment = Decimal("65.0")  # 75 - 10 = 65 adjustment
        self.manager.adjust_daily_loss(adjustment, reason="balance_reconciliation")

        self.assertEqual(self.manager._daily_loss_quote, Decimal("10.0"))

    def test_adjust_cannot_go_negative(self):
        """adjust_daily_loss() should not create negative loss"""
        now = time.time()

        # Track $30 loss
        self.manager.register_open_trade(symbol="BTC-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="BTC-USD",
            realised_pnl_quote=Decimal("-30.0"),
            now=now + 60
        )

        # Try to adjust by more than the loss
        self.manager.adjust_daily_loss(Decimal("50.0"), reason="over_adjustment")

        # Should be clamped to zero, not become negative
        self.assertEqual(self.manager._daily_loss_quote, Decimal("0"))

    def test_partial_adjustment_allows_trading(self):
        """Partial adjustment should reduce loss% and potentially unblock"""
        now = time.time()

        # $50 loss on $400 reference = 12.5% > 10% limit
        self.manager.register_open_trade(symbol="ETH-USD", notional=Decimal("100"), now=now)
        self.manager.register_close_trade(
            symbol="ETH-USD",
            realised_pnl_quote=Decimal("-50.0"),
            now=now + 60
        )

        # Skip cooldowns
        now += 700

        # Verify blocked (12.5% > 10%)
        result = self.manager.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=now
        )
        self.assertIsNone(result)

        # Adjust by $15: new loss = $35 = 8.75% < 10%
        self.manager.adjust_daily_loss(Decimal("15.0"), reason="reconciliation")

        # Verify unblocked
        result = self.manager.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=now
        )
        self.assertIsNotNone(result)


class TestReconciliationScenarios(unittest.TestCase):
    """Test real-world reconciliation scenarios"""

    def test_hbar_missed_sell_scenario(self):
        """
        Real bug scenario: HBAR-USD
        - 4 buys totaling $75.34
        - 1 sell at $75.50 (missed by websocket)
        - Bot tracked -$74.58 loss (19.09% of $390 reference)
        - Actual result: +$0.16 profit
        """
        limits = RiskLimits(
            max_daily_loss_pct=Decimal("2.5"),  # Original limit
            max_balance_risk_per_trade_pct=Decimal("60.0"),
            max_total_open_risk_pct=Decimal("75.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=300,
            symbol_switch_cooldown_seconds=120,
            consecutive_loss_cooldown_seconds=600,
        )
        manager = GlobalRiskManager(
            reference_balance_quote=Decimal("390.0"),
            limits=limits
        )

        now = time.time()

        # Simulate the buys being tracked
        for i in range(4):
            manager.register_open_trade(
                symbol="HBAR-USD",
                notional=Decimal("18.84"),  # ~$75.34 / 4
                now=now + i
            )

        # Simulate the "loss" that was incorrectly calculated
        # (bot tracked buys but missed the sell fill)
        manager._daily_loss_quote = Decimal("74.58")

        # Trading should be blocked (74.58/390 = 19.09% > 2.5%)
        now += 700  # Skip cooldowns
        result = manager.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=now
        )
        self.assertIsNone(result)

        # Reconciliation detects balance is fine
        # Reset the false loss
        manager.reset_daily_loss(reason="external_fill_reconciliation")

        # Now trading should work
        result = manager.can_open_trade(
            symbol="SOL-USD",
            requested_notional=Decimal("50"),
            now=now
        )
        self.assertIsNotNone(result)

    def test_balance_check_reconciliation_full_reset(self):
        """
        Test reconciliation: If balance >= 95% of reference, reset (probable tracking error)
        """
        limits = RiskLimits(
            max_daily_loss_pct=Decimal("5.0"),
            max_balance_risk_per_trade_pct=Decimal("50.0"),
            max_total_open_risk_pct=Decimal("80.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=300,
            symbol_switch_cooldown_seconds=120,
            consecutive_loss_cooldown_seconds=600,
        )
        reference = Decimal("400.0")
        manager = GlobalRiskManager(
            reference_balance_quote=reference,
            limits=limits
        )

        # Balance still at 98% = tracking error
        tracked_loss_quote = Decimal("80.0")  # 20% tracked loss
        actual_balance = Decimal("392.0")  # 98% of reference

        manager._daily_loss_quote = tracked_loss_quote

        # Simulate reconciliation logic
        balance_ratio = actual_balance / reference
        if balance_ratio >= Decimal("0.95"):
            manager.reset_daily_loss(reason="balance_ok")

        self.assertEqual(manager._daily_loss_quote, Decimal("0"))

    def test_balance_check_reconciliation_partial_adjust(self):
        """
        Test reconciliation: If actual loss < 50% of tracked, adjust (partial reconciliation)
        """
        limits = RiskLimits(
            max_daily_loss_pct=Decimal("5.0"),
            max_balance_risk_per_trade_pct=Decimal("50.0"),
            max_total_open_risk_pct=Decimal("80.0"),
            min_hold_seconds=60,
            exit_cooldown_seconds=300,
            symbol_switch_cooldown_seconds=120,
            consecutive_loss_cooldown_seconds=600,
        )
        reference = Decimal("400.0")
        manager = GlobalRiskManager(
            reference_balance_quote=reference,
            limits=limits
        )

        # Tracked 10% loss, but actual only 2% loss
        manager._daily_loss_quote = Decimal("40.0")  # 10% tracked ($40 of $400)
        actual_balance = Decimal("392.0")  # 2% actual loss ($8 lost)
        actual_loss_quote = reference - actual_balance  # $8
        actual_loss_pct = actual_loss_quote / reference  # 2%
        tracked_loss_pct = manager._daily_loss_quote / reference  # 10%

        # Actual 2% < 50% of tracked 10% (5%)? Yes, adjust
        if actual_loss_pct < tracked_loss_pct * Decimal("0.5"):
            adjustment = manager._daily_loss_quote - actual_loss_quote  # $40 - $8 = $32
            manager.adjust_daily_loss(adjustment, reason="balance_reconciliation")

        self.assertEqual(manager._daily_loss_quote, Decimal("8.0"))


if __name__ == "__main__":
    unittest.main()
