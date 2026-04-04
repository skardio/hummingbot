"""
Unit tests for Professional Risk Manager (Grid-Aware)

Tests:
- ATR-based stop loss calculation
- Context-aware time exits
- Profit tier logic
- PnL-driven pauses
- Position exit decisions
"""

import unittest
from decimal import Decimal

from multi_coin_grid_pro.risk.professional_risk_manager import (
    PortfolioRisk,
    PositionRisk,
    ProfessionalRiskManager,
    calculate_correlation_risk,
)


class TestProfessionalRiskManager(unittest.TestCase):
    """Test suite for ProfessionalRiskManager"""

    def setUp(self):
        """Set up test fixtures"""
        self.risk_mgr = ProfessionalRiskManager(
            max_daily_loss_pct=0.03,
            max_positions=6,
            atr_stop_multiplier=2.0,
            min_stop_pct=0.02,
            max_stop_pct=0.08,
            time_based_stop_minutes=360,
            time_stop_requires_stall=True,
            price_stall_threshold_atr=0.3,
            min_minutes_since_last_fill=45,
            profit_lock_tiers=[
                (0.01, 0.005, 0.0),   # Peak +1% → drawdown 0.5% → lock 0%
                (0.02, 0.013, 0.007),  # Peak +2% → drawdown 1.3% → lock +0.7%
                (0.03, 0.015, 0.015),  # Peak +3% → drawdown 1.5% → lock +1.5%
            ],
            min_rolling_pnl_pct=-0.02,
            min_win_rate=0.35,
            pause_cooldown_minutes=120,
            resume_min_pnl_pct=0.0,
        )

    def test_atr_stop_calculation_volatile_coin(self):
        """Test ATR stop for volatile coin (RENDER, 3.5% ATR)"""
        # For volatile coins: ATR stop = 2×3.5% = 7%
        # But min_capital_stop = 8%, so effective stop = max(7%, 8%) = 8%

        position = PositionRisk(
            symbol="RENDER-EUR",
            entry_price=Decimal("100.00"),
            current_price=Decimal("92.00"),  # -8% loss
            unrealized_pnl_pct=-0.08,
            time_held_minutes=120,
            atr_pct=0.035,  # 3.5% ATR
            initial_stop_pct=0.08,
            current_stop_pct=0.08,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=False,
            entry_confidence=0.8
        )

        # ATR stop: 2×3.5% = 7%
        # Min capital stop: 8%
        # Effective stop: max(7%, 8%) = 8%
        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.5
        )

        # Should trigger at -8% (min capital stop floor)
        self.assertEqual(action, "STOP_LOSS", "Should trigger at -8% (min capital stop)")
        self.assertIn("ATR stop hit", reason)

    def test_atr_stop_calculation_stable_coin(self):
        """Test ATR stop for stable coin (BTC, 1.2% ATR)"""
        entry_price = Decimal("50000.00")
        atr_pct = 0.012  # 1.2%

        position = PositionRisk(
            symbol="BTC-EUR",
            entry_price=entry_price,
            current_price=Decimal("48800.00"),  # -2.4% loss
            unrealized_pnl_pct=-0.024,
            time_held_minutes=120,
            atr_pct=atr_pct,
            initial_stop_pct=0.024,
            current_stop_pct=0.024,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=False,
            entry_confidence=0.7
        )

        # ATR stop: 2×1.2% = 2.4%
        # Clamped: max(2%, min(2.4%, 8%)) = 2.4%
        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.5
        )

        self.assertEqual(action, "STOP_LOSS", "Should trigger at -2.4% (ATR stop)")
        self.assertIn("ATR stop hit", reason)

    def test_stop_loss_triggered(self):
        """Test hard stop loss trigger"""
        position = PositionRisk(
            symbol="RENDER-EUR",
            entry_price=Decimal("2.00"),
            current_price=Decimal("1.84"),  # -8% loss (hits min capital stop)
            unrealized_pnl_pct=-0.08,
            time_held_minutes=120,
            atr_pct=0.035,  # 3.5% ATR → 2x = 7%, but min_capital_stop = 8%
            initial_stop_pct=0.08,
            current_stop_pct=0.08,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=False,
            entry_confidence=0.8
        )

        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.5
        )

        self.assertEqual(action, "STOP_LOSS", "Should trigger stop loss at -8%")
        self.assertIn("ATR stop hit", reason)

    def test_time_stop_with_stall(self):
        """Test time-based exit when position is stalled"""
        position = PositionRisk(
            symbol="TAO-EUR",
            entry_price=Decimal("100.00"),
            current_price=Decimal("97.00"),  # -3% loss
            unrealized_pnl_pct=-0.03,
            time_held_minutes=370,  # Over 6 hours
            atr_pct=0.025,
            initial_stop_pct=0.05,
            current_stop_pct=0.05,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=True,
            entry_confidence=0.7
        )

        # Price stalled (< 0.3× ATR movement)
        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.15  # 0.15× ATR < 0.3× threshold
        )

        self.assertEqual(action, "TIME_STOP", "Should exit stalled position after 6h")
        self.assertIn("Dead position", reason)

    def test_time_expired_but_not_stalled_holds(self):
        """Test that time-expired position with movement stays open"""
        position = PositionRisk(
            symbol="BCH-EUR",
            entry_price=Decimal("500.00"),
            current_price=Decimal("490.00"),  # -2% loss
            unrealized_pnl_pct=-0.02,
            time_held_minutes=370,  # Over 6 hours
            atr_pct=0.02,
            initial_stop_pct=0.04,
            current_stop_pct=0.04,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=True,
            entry_confidence=0.8
        )

        # Mock recent fill (30 min ago) to prevent no-fills exit
        from datetime import datetime, timedelta
        self.risk_mgr.position_last_fill_time[position.symbol] = datetime.now() - timedelta(minutes=30)

        # Price moving (> 0.3× ATR)
        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.8  # 0.8× ATR > 0.3× threshold
        )

        self.assertEqual(action, "HOLD", "Should keep position if price moving and fills recent")

    def test_profit_tier_lock_at_pullback(self):
        """Test profit tier waiting for drawdown threshold"""
        position = PositionRisk(
            symbol="BCH-EUR",
            entry_price=Decimal("500.00"),
            current_price=Decimal("510.00"),  # +2.0% current PnL
            unrealized_pnl_pct=0.020,
            time_held_minutes=120,
            atr_pct=0.02,
            initial_stop_pct=0.04,
            current_stop_pct=0.04,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=False,
            entry_confidence=0.8
        )

        # Set peak at +2.5% (was higher)
        self.risk_mgr.position_high_water_marks[position.symbol] = 0.025  # Peak PnL

        # Current PnL: +2.0%
        # Peak PnL: +2.5%
        # Drawdown: 2.5% - 2.0% = 0.5%
        # Tier: Peak +2% → requires 1.3% drawdown → lock +0.7%
        # Current drawdown 0.5% < 1.3% required → should HOLD

        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.5
        )

        # Should be in tier but waiting for more drawdown
        self.assertEqual(action, "HOLD", "Should wait for larger drawdown (0.5% < 1.3% required)")
        self.assertIn("tier", reason.lower())

    def test_profit_tier_lock_triggered(self):
        """Test profit tier lock when drawdown threshold reached"""
        position = PositionRisk(
            symbol="BCH-EUR",
            entry_price=Decimal("500.00"),
            current_price=Decimal("505.00"),  # +1.0% current PnL
            unrealized_pnl_pct=0.01,
            time_held_minutes=120,
            atr_pct=0.02,
            initial_stop_pct=0.04,
            current_stop_pct=0.04,
            trailing_stop_distance_pct=0.02,
            max_hold_time_minutes=360,
            is_time_expired=False,
            entry_confidence=0.8
        )

        # Set peak at +2.5%
        self.risk_mgr.position_high_water_marks[position.symbol] = 0.025  # Peak PnL

        # Current PnL: +1.0%
        # Peak PnL: +2.5%
        # Drawdown: 2.5% - 1.0% = 1.5%
        # Tier: Peak +2% → requires 1.3% drawdown → lock +0.7%
        # Current drawdown 1.5% >= 1.3% required → should LOCK

        action, reason = self.risk_mgr.should_exit_position(
            position=position,
            price_movement_last_hour_atr=0.5
        )

        self.assertEqual(action, "PROFIT_LOCK", "Should lock profit when drawdown >= threshold")
        self.assertIn("Profit tier lock", reason)

    def test_can_open_new_position_daily_limit_hit(self):
        """Test that new positions blocked when daily limit hit"""
        portfolio = PortfolioRisk(
            total_equity=Decimal("1000.00"),
            daily_pnl=Decimal("-30.00"),  # -3% loss
            daily_pnl_pct=-0.03,
            max_daily_loss_pct=0.03,
            open_positions=2,
            max_positions=6,
            recent_wins=5,
            recent_losses=10,
            win_rate=0.33,
            highly_correlated_positions=[],
            correlation_risk_score=0.2
        )

        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="NEW-EUR",
            confidence=0.8,
            portfolio_risk=portfolio
        )

        self.assertFalse(can_open, "Should block when daily limit hit")
        self.assertIn("Daily loss limit reached", reason)

    def test_can_open_new_position_max_positions(self):
        """Test that new positions blocked when max positions reached"""
        portfolio = PortfolioRisk(
            total_equity=Decimal("1000.00"),
            daily_pnl=Decimal("10.00"),
            daily_pnl_pct=0.01,
            max_daily_loss_pct=0.03,
            open_positions=6,  # Max reached
            max_positions=6,
            recent_wins=8,
            recent_losses=5,
            win_rate=0.62,
            highly_correlated_positions=[],
            correlation_risk_score=0.3
        )

        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="NEW-EUR",
            confidence=0.8,
            portfolio_risk=portfolio
        )

        self.assertFalse(can_open, "Should block when max positions reached")
        self.assertIn("Max positions reached", reason)

    def test_can_open_new_position_low_rolling_pnl(self):
        """Test pause when rolling PnL too negative"""
        # Add some losing trades
        for i in range(15):
            self.risk_mgr.record_trade_result(
                symbol=f"COIN-{i}",
                pnl_pct=-0.03,  # -3% each
                close_reason="STOP_LOSS",
                hold_time_minutes=120
            )

        portfolio = PortfolioRisk(
            total_equity=Decimal("1000.00"),
            daily_pnl=Decimal("-10.00"),
            daily_pnl_pct=-0.01,
            max_daily_loss_pct=0.03,
            open_positions=2,
            max_positions=6,
            recent_wins=0,
            recent_losses=15,
            win_rate=0.0,
            highly_correlated_positions=[],
            correlation_risk_score=0.2
        )

        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="NEW-EUR",
            confidence=0.8,
            portfolio_risk=portfolio
        )

        self.assertFalse(can_open, "Should pause when rolling PnL < -2%")
        self.assertIn("Pause triggered", reason)

    def test_can_open_new_position_success(self):
        """Test successful position opening when all checks pass"""
        # Add some winning trades
        for i in range(10):
            self.risk_mgr.record_trade_result(
                symbol=f"COIN-{i}",
                pnl_pct=0.02,  # +2% each
                close_reason="PROFIT_LOCK",
                hold_time_minutes=120
            )

        portfolio = PortfolioRisk(
            total_equity=Decimal("1000.00"),
            daily_pnl=Decimal("15.00"),
            daily_pnl_pct=0.015,
            max_daily_loss_pct=0.03,
            open_positions=2,
            max_positions=6,
            recent_wins=10,
            recent_losses=2,
            win_rate=0.83,
            highly_correlated_positions=[],
            correlation_risk_score=0.2
        )

        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="NEW-EUR",
            confidence=0.8,
            portfolio_risk=portfolio
        )

        self.assertTrue(can_open, "Should allow position when all checks pass")
        self.assertEqual(reason, "OK")

    def test_position_sizing_by_confidence(self):
        """Test position size scaling by confidence"""
        base_size = Decimal("50.00")  # Lower base to see confidence scaling
        account_equity = Decimal("1000.00")

        # Low confidence (0.5) → 1.0x size (neutral, maps to 1.0x)
        # Formula: 2*(0.5 - 0.5) + 1.0 = 1.0
        size_neutral = self.risk_mgr.calculate_position_size(
            symbol="TEST-EUR",
            confidence=0.5,
            account_equity=account_equity,
            base_position_size=base_size
        )
        self.assertEqual(size_neutral, base_size, "Confidence 0.5 should be neutral (1.0x)")

        # High confidence (0.9) → 1.8x size
        # Formula: 2*(0.9 - 0.5) + 1.0 = 1.8
        # €50 * 1.8 = €90
        size_high = self.risk_mgr.calculate_position_size(
            symbol="TEST-EUR",
            confidence=0.9,
            account_equity=account_equity,
            base_position_size=base_size
        )
        expected_high = base_size * Decimal("1.8")
        self.assertEqual(size_high, expected_high, f"High confidence should scale to 1.8x: {expected_high}")

        # Test capping at 10% of equity
        large_base = Decimal("200.00")  # Would exceed 10% limit
        size_capped = self.risk_mgr.calculate_position_size(
            symbol="TEST-EUR",
            confidence=0.9,
            account_equity=account_equity,
            base_position_size=large_base
        )
        max_allowed = account_equity * Decimal("0.10")
        self.assertEqual(size_capped, max_allowed, "Should cap at 10% of equity (€100)")

    def test_correlation_risk_calculation(self):
        """Test correlation risk scoring"""
        # No correlation (diversified)
        correlations = {
            ("BTC-EUR", "ETH-EUR"): 0.2,
            ("BTC-EUR", "SOL-EUR"): 0.1,
            ("ETH-EUR", "SOL-EUR"): 0.15,
        }

        risk_low = calculate_correlation_risk(
            open_positions=["BTC-EUR", "ETH-EUR", "SOL-EUR"],
            price_correlations=correlations
        )
        self.assertLess(risk_low, 0.3, "Low correlations should have low risk score")

        # High correlation (concentrated)
        correlations_high = {
            ("BTC-EUR", "ETH-EUR"): 0.85,
            ("BTC-EUR", "SOL-EUR"): 0.80,
            ("ETH-EUR", "SOL-EUR"): 0.90,
        }

        risk_high = calculate_correlation_risk(
            open_positions=["BTC-EUR", "ETH-EUR", "SOL-EUR"],
            price_correlations=correlations_high
        )
        self.assertGreater(risk_high, 0.7, "High correlations should have high risk score")

    def test_trade_recording_and_win_rate(self):
        """Test trade recording and win rate tracking"""
        # Record 10 trades: 7 wins, 3 losses (70% WR)
        for i in range(7):
            self.risk_mgr.record_trade_result(
                symbol=f"WIN-{i}",
                pnl_pct=0.02,
                close_reason="PROFIT_LOCK",
                hold_time_minutes=120
            )

        for i in range(3):
            self.risk_mgr.record_trade_result(
                symbol=f"LOSS-{i}",
                pnl_pct=-0.015,
                close_reason="STOP_LOSS",
                hold_time_minutes=240
            )

        # Check trade count
        self.assertEqual(len(self.risk_mgr.recent_trades), 10)

        # Calculate win rate manually
        wins = sum(1 for t in self.risk_mgr.recent_trades if t["is_win"])
        win_rate = wins / len(self.risk_mgr.recent_trades)

        self.assertAlmostEqual(win_rate, 0.70, places=2)

    def test_high_water_mark_cleanup(self):
        """Test high water mark cleanup after trade closes"""
        symbol = "TEST-EUR"
        self.risk_mgr.position_high_water_marks[symbol] = Decimal("100.00")

        self.risk_mgr.record_trade_result(
            symbol=symbol,
            pnl_pct=0.02,
            close_reason="PROFIT_LOCK",
            hold_time_minutes=120
        )

        # High water mark should be cleaned up
        self.assertNotIn(symbol, self.risk_mgr.position_high_water_marks)

    def _make_portfolio_risk(self, **kwargs):
        """Helper to create PortfolioRisk with sensible defaults"""
        defaults = dict(
            total_equity=Decimal("1000.00"),
            daily_pnl=Decimal("-5.00"),
            daily_pnl_pct=-0.005,
            max_daily_loss_pct=0.03,
            open_positions=0,
            max_positions=6,
            recent_wins=3,
            recent_losses=7,
            win_rate=0.30,
            highly_correlated_positions=[],
            correlation_risk_score=0.0,
        )
        defaults.update(kwargs)
        return PortfolioRisk(**defaults)

    def _seed_losing_trades(self, count=15, pnl=-0.005):
        """Seed the risk manager with losing trades"""
        for i in range(count):
            self.risk_mgr.record_trade_result(
                symbol=f"COIN-{i}",
                pnl_pct=pnl,
                close_reason="STOP_LOSS",
                hold_time_minutes=60,
            )

    def test_pause_deadlock_force_resume_after_max_extensions(self):
        """Test that pause deadlock is broken after max_pause_extensions"""
        from datetime import datetime, timedelta

        self.risk_mgr.max_pause_extensions = 2
        self.risk_mgr.pause_cooldown_minutes = 120

        # Seed losing trades (PnL -0.5% each → avg -0.50%)
        self._seed_losing_trades(15, pnl=-0.005)

        portfolio = self._make_portfolio_risk()

        # Trigger initial pause (rolling PnL < 0 + win rate < 35%)
        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="TEST-USD", confidence=0.7, portfolio_risk=portfolio
        )
        self.assertFalse(can_open)
        self.assertIsNotNone(self.risk_mgr.pause_until)
        self.assertEqual(self.risk_mgr._pause_extensions, 0)

        # Extension 1: expire cooldown, conditions unchanged → extends
        self.risk_mgr.pause_until = datetime.now() - timedelta(seconds=1)
        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="TEST-USD", confidence=0.7, portfolio_risk=portfolio
        )
        self.assertFalse(can_open)
        self.assertIn("Pause extended (1/2)", reason)
        self.assertEqual(self.risk_mgr._pause_extensions, 1)

        # Extension 2: expire again → hits max_pause_extensions, force resume
        # Clears stale trades so step 3 won't re-trigger
        self.risk_mgr.pause_until = datetime.now() - timedelta(seconds=1)
        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="TEST-USD", confidence=0.7, portfolio_risk=portfolio
        )
        # After force-resume: stale trades cleared, pause_until=None
        # Step 3 won't trigger because len(recent_trades) < 10
        self.assertTrue(can_open, "Should resume after max extensions (deadlock broken)")
        self.assertEqual(reason, "OK")
        self.assertEqual(len(self.risk_mgr.recent_trades), 0)
        self.assertIsNone(self.risk_mgr.pause_until)

    def test_pause_extensions_reset_on_new_trigger(self):
        """Test that _pause_extensions resets when a fresh pause is triggered"""
        self.risk_mgr._pause_extensions = 5
        self.risk_mgr._trigger_pause("Test reason")
        self.assertEqual(self.risk_mgr._pause_extensions, 0)
        self.assertIsNotNone(self.risk_mgr.pause_until)

    def test_pause_extensions_reset_on_resume(self):
        """Test that _pause_extensions resets when conditions improve"""
        from datetime import datetime, timedelta

        # Seed winning trades (PnL +2% each)
        for i in range(15):
            self.risk_mgr.record_trade_result(
                symbol=f"WIN-{i}", pnl_pct=0.02,
                close_reason="PROFIT_LOCK", hold_time_minutes=60
            )

        self.risk_mgr.pause_until = datetime.now() - timedelta(seconds=1)
        self.risk_mgr.pause_reason = "test"
        self.risk_mgr._pause_extensions = 1

        portfolio = self._make_portfolio_risk(win_rate=0.80)
        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="TEST-USD", confidence=0.7, portfolio_risk=portfolio
        )
        self.assertTrue(can_open)
        self.assertEqual(reason, "OK")
        self.assertEqual(self.risk_mgr._pause_extensions, 0)
        self.assertIsNone(self.risk_mgr.pause_until)

    def test_max_pause_extensions_configurable(self):
        """Test max_pause_extensions is configurable"""
        rm = ProfessionalRiskManager(max_pause_extensions=5)
        self.assertEqual(rm.max_pause_extensions, 5)
        self.assertEqual(rm._pause_extensions, 0)

    # --- Breakeven exclusion from win rate ---

    def test_breakeven_excluded_from_win_rate(self):
        """Breakeven trades (pnl_pct=0) must not affect win rate calculation"""
        # Record 3 wins, 5 breakevens, 2 losses — the scenario that caused the bug
        for _ in range(3):
            self.risk_mgr.record_trade_result(
                symbol="WIN-USD", pnl_pct=0.01,
                close_reason="PROFIT_LOCK", hold_time_minutes=60
            )
        for _ in range(5):
            self.risk_mgr.record_trade_result(
                symbol="BE-USD", pnl_pct=0.0,
                close_reason="GRID_COMPLETE", hold_time_minutes=30
            )
        for _ in range(2):
            self.risk_mgr.record_trade_result(
                symbol="LOSS-USD", pnl_pct=-0.01,
                close_reason="EARLY_STOP", hold_time_minutes=90
            )

        # Win rate should be 3 wins / 5 decisive = 60%, NOT 3/10 = 30%
        decisive = [t for t in self.risk_mgr.recent_trades if t["pnl_pct"] != 0]
        wins = sum(1 for t in decisive if t["is_win"])
        win_rate = wins / len(decisive)
        self.assertAlmostEqual(win_rate, 0.6)

    def test_breakeven_only_trades_default_win_rate(self):
        """If all trades are breakeven, win rate should default to 0.5 (neutral)"""
        for _ in range(10):
            self.risk_mgr.record_trade_result(
                symbol="BE-USD", pnl_pct=0.0,
                close_reason="GRID_COMPLETE", hold_time_minutes=30
            )
        decisive = [t for t in self.risk_mgr.recent_trades if t["pnl_pct"] != 0]
        win_rate = sum(1 for t in decisive if t["is_win"]) / len(decisive) if decisive else 0.5
        self.assertAlmostEqual(win_rate, 0.5)

    def test_no_pause_with_breakeven_excluded(self):
        """The exact bug scenario: 3 wins + 5 breakeven + 2 losses should NOT pause"""
        # Reproduce the exact scenario
        for _ in range(3):
            self.risk_mgr.record_trade_result(
                symbol="WIN-USD", pnl_pct=0.01,
                close_reason="PROFIT_LOCK", hold_time_minutes=60
            )
        for _ in range(5):
            self.risk_mgr.record_trade_result(
                symbol="BE-USD", pnl_pct=0.0,
                close_reason="GRID_COMPLETE", hold_time_minutes=30
            )
        for _ in range(2):
            self.risk_mgr.record_trade_result(
                symbol="LOSS-USD", pnl_pct=-0.005,
                close_reason="EARLY_STOP", hold_time_minutes=90
            )

        # Build portfolio risk with the correct (breakeven-excluded) win rate
        # 3 decisive wins / 5 decisive trades = 60%
        portfolio = self._make_portfolio_risk(win_rate=0.60)
        can_open, reason = self.risk_mgr.can_open_new_position(
            symbol="TEST-USD", confidence=0.7, portfolio_risk=portfolio
        )
        self.assertTrue(can_open, f"Should NOT pause with 60% WR, but got: {reason}")


if __name__ == "__main__":
    unittest.main()
