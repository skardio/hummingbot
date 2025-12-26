"""
Unit tests for PnL Tracker and RiskGuard v2.0
"""
import logging
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from multi_coin_grid_pro.core.models import TradeFill
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestRealtimePnLTracker(unittest.TestCase):
    """Test P&L tracking logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)

        self.tracker = RealtimePnLTracker(
            starting_balance=Decimal("1000"),
            logger=self.logger
        )

    def test_initial_state(self):
        """Test initial state"""
        self.assertEqual(self.tracker.equity(), Decimal("1000"))
        self.assertEqual(self.tracker.realized_pnl, Decimal("0"))
        self.assertEqual(self.tracker.unrealized_pnl, Decimal("0"))
        self.assertEqual(self.tracker.daily_pnl_pct(), 0.0)

    def test_buy_trade(self):
        """Test buy trade processing"""
        fill = TradeFill(
            symbol="BTC-EUR",
            side="buy",
            price=Decimal("50000"),
            size=Decimal("0.01"),
            fee=Decimal("1.0"),
            ts=1234567890,
            order_id="order1"
        )

        self.tracker.on_trade_fill(fill)

        # Check position created
        self.assertIn("BTC-EUR", self.tracker.positions)
        pos = self.tracker.positions["BTC-EUR"]
        self.assertEqual(pos.size, Decimal("0.01"))
        self.assertEqual(pos.avg_entry_price, Decimal("50000"))

        # Check balance reduced
        expected_balance = Decimal("1000") - Decimal("500") - Decimal("1.0")  # 0.01*50000 + fee
        self.assertEqual(self.tracker.current_balance, expected_balance)

        # Check fees
        self.assertEqual(self.tracker.fees_paid, Decimal("1.0"))

    def test_sell_trade_profit(self):
        """Test sell trade with profit"""
        # Buy first
        buy_fill = TradeFill(
            symbol="BTC-EUR",
            side="buy",
            price=Decimal("50000"),
            size=Decimal("0.01"),
            fee=Decimal("1.0"),
            ts=1234567890
        )
        self.tracker.on_trade_fill(buy_fill)

        # Sell at higher price
        sell_fill = TradeFill(
            symbol="BTC-EUR",
            side="sell",
            price=Decimal("51000"),
            size=Decimal("0.01"),
            fee=Decimal("1.0"),
            ts=1234567900
        )
        self.tracker.on_trade_fill(sell_fill)

        # Check realized P&L
        expected_pnl = (Decimal("51000") - Decimal("50000")) * Decimal("0.01")
        self.assertEqual(self.tracker.realized_pnl, expected_pnl)

        # Position should be closed
        self.assertEqual(self.tracker.positions["BTC-EUR"].size, Decimal("0"))

    def test_unrealized_pnl(self):
        """Test unrealized P&L calculation"""
        # Buy
        fill = TradeFill(
            symbol="BTC-EUR",
            side="buy",
            price=Decimal("50000"),
            size=Decimal("0.01"),
            fee=Decimal("1.0"),
            ts=1234567890
        )
        self.tracker.on_trade_fill(fill)

        # Update with current prices
        self.tracker.update_unrealized({"BTC-EUR": Decimal("52000")})

        # Check unrealized P&L
        expected_unrealized = (Decimal("52000") - Decimal("50000")) * Decimal("0.01")
        self.assertEqual(self.tracker.unrealized_pnl, expected_unrealized)

        # Check equity
        expected_equity = self.tracker.current_balance + expected_unrealized
        self.assertEqual(self.tracker.equity(), expected_equity)

    def test_daily_pnl_percentage(self):
        """Test daily P&L percentage calculation"""
        # Buy position
        buy_fill = TradeFill(
            symbol="BTC-EUR",
            side="buy",
            price=Decimal("50000"),
            size=Decimal("0.01"),
            fee=Decimal("0.08"),  # 0.16% fee on €500 = €0.08 (realistic)
            ts=1234567890
        )
        self.tracker.on_trade_fill(buy_fill)

        # Sell at profit
        sell_fill = TradeFill(
            symbol="BTC-EUR",
            side="sell",
            price=Decimal("55000"),  # 10% profit
            size=Decimal("0.01"),
            fee=Decimal("0.088"),  # 0.16% fee on €550 = €0.088
            ts=1234567900
        )
        self.tracker.on_trade_fill(sell_fill)

        # Calculate daily P&L %
        daily_pct = self.tracker.daily_pnl_pct()

        # Should be positive (€50 gross profit - €0.168 fees = €49.83 net profit)
        # On €1000 starting balance = ~4.98% daily gain
        self.assertGreater(daily_pct, 0.0)


class TestRiskGuardV2(unittest.TestCase):
    """Test RiskGuard kill switch logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)

        class MockAlerter:

            def critical(self, msg):
                pass

            def warning(self, msg):
                pass

        self.tracker = RealtimePnLTracker(Decimal("1000"), self.logger)
        self.alerter = MockAlerter()

        self.cfg = {
            "max_daily_loss_pct": 3.0,
            "max_weekly_loss_pct": 8.0,
            "max_monthly_loss_pct": 12.0,
            "max_daily_loss_eur": 50.0,
            "max_exposure_per_coin_pct": 40,
            "max_total_exposure_pct": 80,
        }

        self.guard = RiskGuardV2(self.cfg, self.tracker, self.alerter, self.logger)

    def test_normal_operation(self):
        """Test normal operation (no kill switch)"""
        self.assertTrue(self.guard.check_limits())
        self.assertTrue(self.guard.trading_enabled)

    def test_daily_loss_trigger(self):
        """Test daily loss kill switch"""
        # Simulate 5% daily loss
        self.tracker.daily_start_equity = Decimal("1000")
        self.tracker.current_balance = Decimal("950")
        self.tracker.unrealized_pnl = Decimal("0")

        # Should trigger kill switch (5% > 3%)
        self.assertFalse(self.guard.check_limits())
        self.assertFalse(self.guard.trading_enabled)
        self.assertIsNotNone(self.guard.kill_reason)

    def test_position_size_limit(self):
        """Test position size limit"""
        # Try to open 50% position (max is 40%)
        allowed, reason = self.guard.can_open_position("BTC-EUR", Decimal("500"))
        self.assertFalse(allowed)
        self.assertIn("Position size", reason)

    def test_total_exposure_limit(self):
        """Test total exposure limit"""
        # Add existing position
        fill = TradeFill(
            symbol="ETH-EUR",
            side="buy",
            price=Decimal("3000"),
            size=Decimal("0.2"),
            fee=Decimal("1.0"),
            ts=1234567890
        )
        self.tracker.on_trade_fill(fill)

        # Try to add another large position (would exceed 80% total)
        allowed, reason = self.guard.can_open_position("BTC-EUR", Decimal("400"))
        self.assertFalse(allowed)
        self.assertIn("Total exposure", reason)


if __name__ == "__main__":
    unittest.main()
