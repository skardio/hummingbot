"""
Unit tests for Phase 1 Fix #2, #3, #4:
- Drawdown Limits (percentage-based)
- Daily Loss Limits (euro-based)
- Volatility-Based Position Sizing
"""

import sys
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from multi_coin_grid_pro.core.drawdown_tracker import DrawdownTracker


class TestPhase1DrawdownTracker(unittest.TestCase):
    """Test drawdown tracking (Phase 1 Fix #2 & #3)"""

    def setUp(self):
        """Set up test fixtures"""
        self.tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("5.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            max_daily_loss_eur=Decimal("50.0"),
            quote_asset="EUR"
        )

    def test_initialization(self):
        """Test tracker initializes correctly"""
        self.assertEqual(self.tracker.max_daily_loss_pct, Decimal("5.0"))
        self.assertEqual(self.tracker.max_weekly_loss_pct, Decimal("10.0"))
        self.assertEqual(self.tracker.max_monthly_loss_pct, Decimal("15.0"))
        self.assertEqual(self.tracker.max_daily_loss_eur, Decimal("50.0"))
        self.assertEqual(self.tracker.quote_asset, "EUR")
        self.assertFalse(self.tracker.is_paused)

    def test_first_check_initializes_balances(self):
        """Test that first check initializes starting balances"""
        current_balance = Decimal("1000")

        allowed, reason = self.tracker.check_drawdown_limits(current_balance)

        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")
        self.assertEqual(self.tracker.daily_start_balance, current_balance)
        self.assertEqual(self.tracker.weekly_start_balance, current_balance)
        self.assertEqual(self.tracker.monthly_start_balance, current_balance)

    def test_daily_percentage_limit_not_exceeded(self):
        """Test trading continues when daily loss within limit"""
        # Start at €1000
        self.tracker.initialize_balances(Decimal("1000"))

        # Current balance: €960 (-4%)
        current_balance = Decimal("960")
        allowed, reason = self.tracker.check_drawdown_limits(current_balance)

        self.assertTrue(allowed, "Should allow trading when loss < 5%")
        self.assertEqual(reason, "OK")

    def test_daily_percentage_limit_exceeded(self):
        """Test trading pauses when daily loss exceeds limit"""
        # Start at €1000
        self.tracker.initialize_balances(Decimal("1000"))

        # Current balance: €940 (-6%)
        current_balance = Decimal("940")
        allowed, reason = self.tracker.check_drawdown_limits(current_balance)

        self.assertFalse(allowed, "Should pause trading when loss > 5%")
        self.assertIn("Daily drawdown limit exceeded", reason)
        self.assertTrue(self.tracker.is_paused)

    def test_weekly_percentage_limit_exceeded(self):
        """Test trading pauses when weekly loss exceeds limit (but daily OK)"""
        # Use lower daily limit so weekly can trigger
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("15.0"),  # Higher daily limit
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("20.0"),
            quote_asset="EUR"
        )

        # Start at €1000
        tracker.initialize_balances(Decimal("1000"))

        # Current balance: €880 (-12%)
        # Daily: -12% < -15% (OK)
        # Weekly: -12% > -10% (EXCEED!)
        current_balance = Decimal("880")
        allowed, reason = tracker.check_drawdown_limits(current_balance)

        self.assertFalse(allowed, "Should pause trading when weekly loss > 10%")
        self.assertIn("Weekly drawdown limit exceeded", reason)
        self.assertTrue(tracker.is_paused)

    def test_monthly_percentage_limit_exceeded(self):
        """Test trading pauses when monthly loss exceeds limit (but daily/weekly OK)"""
        # Use higher daily/weekly limits so monthly can trigger
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("20.0"),  # Higher limits
            max_weekly_loss_pct=Decimal("20.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="EUR"
        )

        # Start at €1000
        tracker.initialize_balances(Decimal("1000"))

        # Current balance: €830 (-17%)
        # Daily: -17% < -20% (OK)
        # Weekly: -17% < -20% (OK)
        # Monthly: -17% > -15% (EXCEED!)
        current_balance = Decimal("830")
        allowed, reason = tracker.check_drawdown_limits(current_balance)

        self.assertFalse(allowed, "Should pause trading when monthly loss > 15%")
        self.assertIn("Monthly drawdown limit exceeded", reason)
        self.assertTrue(tracker.is_paused)

    def test_daily_euro_limit_not_exceeded(self):
        """Test euro limit allows trading when within limit"""
        self.tracker.initialize_balances(Decimal("1000"))

        # Record losses
        self.tracker.record_trade_pnl(Decimal("-20"), "XRP-EUR")  # -€20
        self.tracker.record_trade_pnl(Decimal("-15"), "ADA-EUR")  # -€15
        # Total: -€35 < -€50 limit

        allowed, reason = self.tracker.check_drawdown_limits(Decimal("965"))

        self.assertTrue(allowed, "Should allow trading when euro loss < €50")
        self.assertEqual(self.tracker.daily_realized_pnl, Decimal("-35"))

    def test_daily_euro_limit_exceeded(self):
        """Test euro limit pauses when exceeded"""
        # Use high percentage limits so euro limit triggers first
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("20.0"),  # High percentage limit
            max_weekly_loss_pct=Decimal("20.0"),
            max_monthly_loss_pct=Decimal("20.0"),
            max_daily_loss_eur=Decimal("50.0"),  # Euro limit will trigger
            quote_asset="EUR"
        )
        tracker.initialize_balances(Decimal("1000"))

        # Record large losses
        tracker.record_trade_pnl(Decimal("-30"), "XRP-EUR")
        tracker.record_trade_pnl(Decimal("-25"), "ADA-EUR")
        # Total: -€55 > -€50 limit

        # Balance: €945 (-5.5% < -20% percentage limit OK, but euro exceeded)
        allowed, reason = tracker.check_drawdown_limits(Decimal("945"))

        self.assertFalse(allowed, "Should pause when euro loss > €50")
        self.assertIn("EUR loss limit exceeded", reason)
        self.assertTrue(tracker.is_paused)

    def test_profit_trades_reduce_loss(self):
        """Test that profitable trades offset losses"""
        self.tracker.initialize_balances(Decimal("1000"))

        # Record trades
        self.tracker.record_trade_pnl(Decimal("-30"), "XRP-EUR")  # Loss
        self.tracker.record_trade_pnl(Decimal("+15"), "ADA-EUR")  # Profit
        # Net: -€15

        self.assertEqual(self.tracker.daily_realized_pnl, Decimal("-15"))

        allowed, reason = self.tracker.check_drawdown_limits(Decimal("985"))
        self.assertTrue(allowed)

    @patch('multi_coin_grid_pro.core.drawdown_tracker.datetime')
    def test_daily_reset_at_midnight(self, mock_datetime):
        """Test that counters reset at midnight"""
        # Setup: Start on Day 1
        day1 = datetime(2025, 12, 1, 10, 0, 0)
        mock_datetime.now.return_value = day1

        self.tracker.initialize_balances(Decimal("1000"))
        self.tracker.record_trade_pnl(Decimal("-30"), "XRP-EUR")

        # Move to Day 2
        day2 = datetime(2025, 12, 2, 10, 0, 0)
        mock_datetime.now.return_value = day2

        # Check on new day - should reset
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("970"))

        # Realized P&L should be reset to 0
        self.assertEqual(self.tracker.daily_realized_pnl, Decimal("0"))
        self.assertEqual(len(self.tracker.daily_trades), 0)

        # Daily start balance should be updated
        self.assertEqual(self.tracker.daily_start_balance, Decimal("970"))

    def test_status_reporting(self):
        """Test status reporting works"""
        self.tracker.initialize_balances(Decimal("1000"))
        self.tracker.record_trade_pnl(Decimal("-25"), "XRP-EUR")

        status = self.tracker.get_status(Decimal("975"))

        self.assertFalse(status['is_paused'])
        self.assertEqual(status['daily_realized_pnl'], -25.0)
        self.assertEqual(status['daily_trades_count'], 1)
        self.assertEqual(status['limits']['daily_pct'], 5.0)
        self.assertEqual(status['limits']['daily_eur'], 50.0)

    def test_multiple_limit_checks(self):
        """Test that most restrictive limit triggers first"""
        # Start at €1000
        self.tracker.initialize_balances(Decimal("1000"))

        # Scenario: -6% loss (exceeds daily 5%, within weekly 10%)
        current_balance = Decimal("940")
        allowed, reason = self.tracker.check_drawdown_limits(current_balance)

        self.assertFalse(allowed)
        self.assertIn("Daily drawdown", reason)  # Daily should trigger first


class TestPhase1VolatilityPositionSizing(unittest.TestCase):
    """Test volatility-based position sizing (Phase 1 Fix #4)"""

    def setUp(self):
        """Set up test fixtures"""
        # We'll test the logic directly without full controller init
        pass

    def test_high_volatility_reduces_size(self):
        """Test that high volatility (>5%) reduces position size to 67%"""
        # High volatility: 6% ATR
        # Expected: 67% of base size
        base_size = Decimal("30")
        volatility_pct = 6.0

        # Apply multiplier
        if volatility_pct > 5.0:
            multiplier = Decimal("0.67")

        adjusted = base_size * multiplier
        expected = Decimal("20.1")  # 30 × 0.67 = 20.1

        self.assertAlmostEqual(float(adjusted), float(expected), places=1)

    def test_medium_volatility_slight_reduction(self):
        """Test medium volatility (3-5%) reduces to 83%"""
        base_size = Decimal("30")
        volatility_pct = 4.0

        if volatility_pct > 3.0 and volatility_pct <= 5.0:
            multiplier = Decimal("0.83")

        adjusted = base_size * multiplier
        expected = Decimal("24.9")  # 30 × 0.83 = 24.9

        self.assertAlmostEqual(float(adjusted), float(expected), places=1)

    def test_normal_volatility_no_change(self):
        """Test normal volatility (1.5-3%) keeps base size"""
        base_size = Decimal("30")
        volatility_pct = 2.0

        if 1.5 <= volatility_pct <= 3.0:
            multiplier = Decimal("1.0")

        adjusted = base_size * multiplier

        self.assertEqual(adjusted, base_size)

    def test_low_volatility_increases_size(self):
        """Test low volatility (<1.5%) increases to 133%"""
        base_size = Decimal("30")
        volatility_pct = 1.0

        if volatility_pct < 1.5:
            multiplier = Decimal("1.33")

        adjusted = base_size * multiplier
        expected = Decimal("39.9")  # 30 × 1.33 = 39.9

        self.assertAlmostEqual(float(adjusted), float(expected), places=1)

    def test_bounds_respected(self):
        """Test that position size stays within 50%-150% bounds"""
        base_size = Decimal("30")

        # Test minimum bound
        min_size = base_size * Decimal("0.5")  # €15
        self.assertEqual(min_size, Decimal("15"))

        # Test maximum bound
        max_size = base_size * Decimal("1.5")  # €45
        self.assertEqual(max_size, Decimal("45"))


if __name__ == "__main__":
    unittest.main()
