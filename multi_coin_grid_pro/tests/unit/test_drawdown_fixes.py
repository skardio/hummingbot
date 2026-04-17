"""
Tests for drawdown tracker bug fixes:
1. Frozen pause_reason — always evaluate fresh, never return cached state
2. Midnight reset — simplified reset + auto-recovery in check_drawdown_limits
3. Phantom threshold — 2× daily limit instead of hardcoded 10%
4. Auto-recovery — trading resumes when portfolio recovers
5. Drawdown portfolio — excludes positions_held (orphaned coins)
6. BUY timing phantom — phantom detection catches timing-based drops
"""

import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.core.drawdown_tracker import DrawdownTracker


class TestFrozenPauseReason(unittest.TestCase):
    """Bug 1: pause_reason must always show current values, not frozen ones."""

    def setUp(self):
        self.tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )

    def test_pause_reason_updates_with_current_values(self):
        """The reason string must reflect the CURRENT portfolio, not the first-pause value."""
        self.tracker.initialize_balances(Decimal("1000"))

        # First check: portfolio at $960 → -4% > -3% limit → pause
        # (4% < 6% phantom threshold, so it's a real pause)
        allowed1, reason1 = self.tracker.check_drawdown_limits(Decimal("960"))
        self.assertFalse(allowed1)
        self.assertIn("960.00", reason1)

        # Second check: portfolio dropped further to $950 → -5%
        # (5% < 6% phantom threshold, still a real pause)
        allowed2, reason2 = self.tracker.check_drawdown_limits(Decimal("950"))
        self.assertFalse(allowed2)
        # Reason must show 950, NOT the old 960
        self.assertIn("950.00", reason2)
        self.assertNotIn("960.00", reason2)

    def test_no_cached_pause_returned(self):
        """check_drawdown_limits must NOT short-circuit on is_paused."""
        self.tracker.initialize_balances(Decimal("1000"))

        # Pause at $960
        self.tracker.check_drawdown_limits(Decimal("960"))
        self.assertTrue(self.tracker.is_paused)

        # Check again with recovered portfolio ($990 → -1%, within limit)
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("990"))
        # Should be allowed — auto-recovery!
        self.assertTrue(allowed)
        self.assertFalse(self.tracker.is_paused)


class TestAutoRecovery(unittest.TestCase):
    """Bug 1+2: Trading must resume when portfolio recovers within limits."""

    def setUp(self):
        self.tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )

    def test_auto_recovery_when_portfolio_recovers(self):
        """Trading resumes automatically when drawdown recovers."""
        self.tracker.initialize_balances(Decimal("1000"))

        # Pause: portfolio drops 4%
        allowed, _ = self.tracker.check_drawdown_limits(Decimal("960"))
        self.assertFalse(allowed)
        self.assertTrue(self.tracker.is_paused)

        # Recover: portfolio back to $985 (-1.5%, within 3% limit)
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("985"))
        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")
        self.assertFalse(self.tracker.is_paused)
        self.assertIsNone(self.tracker.pause_reason)

    def test_no_recovery_if_still_violated(self):
        """Bot stays paused if drawdown is still exceeded."""
        self.tracker.initialize_balances(Decimal("1000"))

        # Pause: -4%
        self.tracker.check_drawdown_limits(Decimal("960"))
        self.assertTrue(self.tracker.is_paused)

        # Still violated: -3.5%
        allowed, _ = self.tracker.check_drawdown_limits(Decimal("965"))
        self.assertFalse(allowed)
        self.assertTrue(self.tracker.is_paused)

    def test_recovery_exactly_at_limit(self):
        """At exactly the limit boundary, trading should be allowed."""
        self.tracker.initialize_balances(Decimal("1000"))

        # Pause: -4%
        self.tracker.check_drawdown_limits(Decimal("960"))

        # Exactly at -3%: $970
        allowed, _ = self.tracker.check_drawdown_limits(Decimal("970"))
        # -3.0% is NOT < -3.0%, so should pass
        self.assertTrue(allowed)
        self.assertFalse(self.tracker.is_paused)

    def test_weekly_limit_prevents_recovery(self):
        """If weekly limit is violated, daily recovery doesn't help."""
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("5.0"),
            max_weekly_loss_pct=Decimal("3.0"),  # Tight weekly limit
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )
        tracker.initialize_balances(Decimal("1000"))

        # Pause via weekly: -4% daily (OK), -4% weekly (exceeds 3%)
        allowed, reason = tracker.check_drawdown_limits(Decimal("960"))
        self.assertFalse(allowed)
        self.assertIn("Weekly", reason)

        # Even if daily recovers, weekly still violated
        allowed, reason = tracker.check_drawdown_limits(Decimal("965"))
        self.assertFalse(allowed)
        self.assertIn("Weekly", reason)


class TestPhantomThreshold(unittest.TestCase):
    """Bug 3: Phantom threshold should be 2× daily limit, not hardcoded 10%."""

    def setUp(self):
        self.tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )

    def test_phantom_detected_at_lower_threshold(self):
        """Phantom detection triggers at 2× daily limit (6%) with low realized PnL."""
        self.tracker.initialize_balances(Decimal("1000"))
        # No realized trades → realized PnL = $0

        # Portfolio drops 7% (> 2×3%=6%) but realized PnL is $0
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("930"))
        self.assertTrue(allowed)
        self.assertIn("phantom", reason.lower())

    def test_real_drawdown_not_phantom(self):
        """Real drawdown (with matching realized PnL) is not phantom."""
        self.tracker.initialize_balances(Decimal("1000"))
        # Record a real loss
        self.tracker.record_trade_pnl(Decimal("-40"), "TEST-USD")

        # Portfolio drops 7% WITH realized PnL of -4%
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("930"))
        self.assertFalse(allowed)
        self.assertIn("Daily drawdown limit exceeded", reason)

    def test_moderate_drop_not_phantom(self):
        """A 5% drop (< 6% threshold) with no realized PnL is NOT phantom → pauses."""
        self.tracker.initialize_balances(Decimal("1000"))

        # Drop 5%: below phantom threshold (6%) but above daily limit (3%)
        allowed, _ = self.tracker.check_drawdown_limits(Decimal("950"))
        self.assertFalse(allowed)
        self.assertTrue(self.tracker.is_paused)

    def test_old_10pct_threshold_would_miss_phantom(self):
        """Document: with old 10% threshold, a 7% phantom would cause permanent pause."""
        # This test verifies the fix works for the exact scenario from the bug.
        self.tracker.initialize_balances(Decimal("245"))  # Real working capital

        # Executor buys $75, quote drops but executor not updated yet:
        # Portfolio = $170 (quote only), drop = ($170-$245)/$245 = -30.6%
        # Old threshold: 30.6% > 10%? Yes, but this test runs with new threshold
        allowed, reason = self.tracker.check_drawdown_limits(Decimal("170"))
        # 30.6% > 6% (2×3%) AND realized 0% < 3% → PHANTOM
        self.assertTrue(allowed)
        self.assertIn("phantom", reason.lower())


class TestMidnightReset(unittest.TestCase):
    """Bug 2: Midnight reset must update start balances and allow auto-recovery."""

    def test_daily_reset_updates_start_balance(self):
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )

        # Initialize on day 1
        yesterday = date.today() - timedelta(days=1)
        tracker.daily_start_balance = Decimal("1000")
        tracker.weekly_start_balance = Decimal("1000")
        tracker.monthly_start_balance = Decimal("1000")
        tracker.last_reset_day = yesterday
        tracker.last_reset_week = datetime.now().isocalendar()[1]
        tracker.last_reset_month = datetime.now().month

        # Simulate pause (from yesterday)
        tracker.is_paused = True
        tracker.pause_reason = "Old frozen reason"
        tracker.daily_realized_pnl = Decimal("-20")

        # Call check — today > yesterday, so reset fires
        allowed, _ = tracker.check_drawdown_limits(Decimal("990"))
        # After reset: daily_start_balance = 990, pnl_pct = 0% → passes
        # Weekly: (990-1000)/1000 = -1% → passes (limit -10%)
        # All OK → auto-recovery
        self.assertTrue(allowed)
        self.assertFalse(tracker.is_paused)
        self.assertEqual(tracker.daily_start_balance, Decimal("990"))
        self.assertEqual(tracker.daily_realized_pnl, Decimal("0"))

    def test_daily_reset_clears_trades(self):
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("5.0"),
            quote_asset="USD",
        )
        yesterday = date.today() - timedelta(days=1)
        tracker.daily_start_balance = Decimal("1000")
        tracker.weekly_start_balance = Decimal("1000")
        tracker.monthly_start_balance = Decimal("1000")
        tracker.last_reset_day = yesterday
        tracker.last_reset_week = datetime.now().isocalendar()[1]
        tracker.last_reset_month = datetime.now().month
        tracker.daily_trades = [{"pnl": -5}, {"pnl": -3}]
        tracker.daily_realized_pnl = Decimal("-8")

        tracker.check_drawdown_limits(Decimal("995"))

        self.assertEqual(tracker.daily_realized_pnl, Decimal("0"))
        self.assertEqual(len(tracker.daily_trades), 0)
        self.assertEqual(tracker.last_reset_day, date.today())


class TestPauseTrading(unittest.TestCase):
    """_pause_trading should only log CRITICAL on first pause, not every tick."""

    def test_first_pause_sets_timestamp(self):
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            quote_asset="USD",
        )
        tracker.initialize_balances(Decimal("1000"))

        tracker.check_drawdown_limits(Decimal("960"))
        first_pause_time = tracker.paused_at
        self.assertIsNotNone(first_pause_time)

        # Second pause call should NOT change paused_at
        tracker.check_drawdown_limits(Decimal("955"))
        self.assertEqual(tracker.paused_at, first_pause_time)

    def test_pause_reason_always_current(self):
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            quote_asset="USD",
        )
        tracker.initialize_balances(Decimal("1000"))

        _, reason1 = tracker.check_drawdown_limits(Decimal("960"))
        self.assertIn("960.00", reason1)

        _, reason2 = tracker.check_drawdown_limits(Decimal("940"))
        self.assertIn("940.00", reason2)
        # pause_reason should match the latest
        self.assertIn("940.00", tracker.pause_reason)


class TestCheckAllLimitsOk(unittest.TestCase):
    """_check_all_limits_ok uses Decimal comparisons, not float."""

    def test_decimal_comparison(self):
        tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal("3.0"),
            max_weekly_loss_pct=Decimal("10.0"),
            max_monthly_loss_pct=Decimal("15.0"),
            quote_asset="USD",
        )
        tracker.daily_start_balance = Decimal("1000")
        tracker.weekly_start_balance = Decimal("1000")
        tracker.monthly_start_balance = Decimal("1000")

        # All OK
        ok, reason = tracker._check_all_limits_ok(Decimal("990"))
        self.assertTrue(ok)
        self.assertIsNone(reason)

        # Daily violated
        ok, reason = tracker._check_all_limits_ok(Decimal("960"))
        self.assertFalse(ok)
        self.assertIn("Daily", reason)


class TestDrawdownPortfolioExcludesOrphans(unittest.TestCase):
    """Bug 5: Drawdown portfolio must exclude positions_held (orphan coins)."""

    def _make_controller(self, quote_balance, executors_info=None,
                         positions_held=None):
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.config = MagicMock()
        ctrl.config.quote_asset = "USD"
        ctrl.executors_info = executors_info or []
        ctrl.positions_held = positions_held or []

        connector = MagicMock()
        connector.get_balance = MagicMock(
            return_value=Decimal(str(quote_balance))
        )
        ctrl.connector = connector

        # Bind real methods
        ctrl._calculate_drawdown_portfolio = (
            MultiCoinGridController._calculate_drawdown_portfolio.__get__(ctrl)
        )
        ctrl._calculate_portfolio_value = (
            MultiCoinGridController._calculate_portfolio_value.__get__(ctrl)
        )
        return ctrl

    def _make_executor(self, is_active=True, pos_size=0, pos_pnl=0,
                       pos_fees=0):
        ei = MagicMock()
        ei.is_active = is_active
        ei.custom_info = {
            'position_size_quote': Decimal(str(pos_size)),
            'position_pnl_quote': Decimal(str(pos_pnl)),
            'position_fees_quote': Decimal(str(pos_fees)),
        }
        return ei

    def _make_position(self, amount, breakeven_price, unrealized_pnl=0):
        pos = MagicMock()
        pos.amount = Decimal(str(amount))
        pos.breakeven_price = Decimal(str(breakeven_price))
        pos.unrealized_pnl_quote = Decimal(str(unrealized_pnl))
        return pos

    def test_drawdown_excludes_positions_held(self):
        """Drawdown portfolio must NOT include orphaned positions."""
        orphan = self._make_position(amount=68000, breakeven_price=Decimal("0.03"),
                                     unrealized_pnl=Decimal("-100"))
        ctrl = self._make_controller(
            quote_balance=245,
            positions_held=[orphan],
        )

        drawdown_val = ctrl._calculate_drawdown_portfolio()
        portfolio_val = ctrl._calculate_portfolio_value()

        # Drawdown portfolio = only quote ($245)
        self.assertEqual(drawdown_val, Decimal("245"))
        # Full portfolio includes the orphan
        expected_orphan = Decimal("68000") * Decimal("0.03") + Decimal("-100")
        self.assertEqual(portfolio_val, Decimal("245") + expected_orphan)
        self.assertGreater(portfolio_val, drawdown_val)

    def test_drawdown_includes_active_executors(self):
        """Active executor positions ARE included in drawdown portfolio."""
        executor = self._make_executor(is_active=True, pos_size=50,
                                       pos_pnl=-2, pos_fees=Decimal("0.1"))
        ctrl = self._make_controller(
            quote_balance=200,
            executors_info=[executor],
        )

        val = ctrl._calculate_drawdown_portfolio()
        # $200 + ($50 - $2 + $0.1) = $248.1
        self.assertEqual(val, Decimal("248.1"))

    def test_drawdown_excludes_inactive_executors(self):
        """Inactive executors are not counted."""
        executor = self._make_executor(is_active=False, pos_size=50)
        ctrl = self._make_controller(
            quote_balance=200,
            executors_info=[executor],
        )

        val = ctrl._calculate_drawdown_portfolio()
        self.assertEqual(val, Decimal("200"))

    def test_real_scenario_orphans_dont_inflate_drawdown(self):
        """Real bug scenario: $245 quote + $1950 orphans.
        Drawdown should track $245, not $2195."""
        orphans = [
            self._make_position(amount=58500000, breakeven_price=Decimal("0.00001"),
                                unrealized_pnl=Decimal("0")),  # PEPE ~$585
            self._make_position(amount=68, breakeven_price=Decimal("1.30"),
                                unrealized_pnl=Decimal("0")),  # TON ~$88
            self._make_position(amount=27000, breakeven_price=Decimal("0.01"),
                                unrealized_pnl=Decimal("0")),  # PENGU ~$270
        ]
        ctrl = self._make_controller(
            quote_balance=245,
            positions_held=orphans,
        )

        drawdown_val = ctrl._calculate_drawdown_portfolio()
        portfolio_val = ctrl._calculate_portfolio_value()

        self.assertEqual(drawdown_val, Decimal("245"))
        self.assertGreater(portfolio_val, Decimal("1000"))

    def test_no_phantom_from_buy_timing(self):
        """Bug 6: When executor buys, drawdown portfolio stays stable
        if custom_info is updated promptly."""
        # Before buy: $245 quote, no executors
        ctrl_before = self._make_controller(quote_balance=245)
        before_val = ctrl_before._calculate_drawdown_portfolio()
        self.assertEqual(before_val, Decimal("245"))

        # During buy: quote drops $75, executor tracking $75
        executor = self._make_executor(is_active=True, pos_size=75)
        ctrl_during = self._make_controller(
            quote_balance=170,
            executors_info=[executor],
        )
        during_val = ctrl_during._calculate_drawdown_portfolio()
        self.assertEqual(during_val, Decimal("245"))  # $170 + $75 = $245

        # After sell: quote returns (small loss $2)
        ctrl_after = self._make_controller(quote_balance=243)
        after_val = ctrl_after._calculate_drawdown_portfolio()
        self.assertEqual(after_val, Decimal("243"))


if __name__ == '__main__':
    unittest.main()
