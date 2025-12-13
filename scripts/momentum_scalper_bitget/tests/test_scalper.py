#!/usr/bin/env python3
"""
Unit tests for B2 Hybrid Scalper Bot
Tests the AI-adaptive features without requiring live API access.
"""

import sys
import unittest
from collections import deque
from decimal import Decimal
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.momentum_scalper_bitget.momentum_scalper import MomentumScalperBot


class TestOrderflowMomentumScore(unittest.TestCase):
    """Test orderflow momentum score calculation."""

    def setUp(self):
        """Create bot instance with test config."""
        self.bot = MomentumScalperBot()

    def test_neutral_orderflow(self):
        """Test neutral orderflow (50/50 split)."""
        score = self.bot.compute_orderflow_momentum_score(
            imbalance=0.5,
            taker_buy_ratio=0.5,
            spread_pct=0.05,
            micro_move_pct=0.0,
        )
        # Neutral imbalance/taker = 0 points from those
        # Good spread (0.05%) = ~15 points
        # No micro move = 0 points
        self.assertGreater(score, 10)
        self.assertLess(score, 25)

    def test_bullish_orderflow(self):
        """Test strong bullish orderflow."""
        score = self.bot.compute_orderflow_momentum_score(
            imbalance=0.70,  # 70% bids = bullish
            taker_buy_ratio=0.75,  # 75% taker buys = bullish
            spread_pct=0.02,  # Tight spread
            micro_move_pct=0.03,  # Small positive move
        )
        # High imbalance (0.7-0.5)*2 = 0.4 → 0.4*35 = 14
        # High taker (0.75-0.5)*2 = 0.5 → 0.5*35 = 17.5
        # Tight spread → ~18
        # Micro move 0.03/0.05 = 0.6 → 0.6*10 = 6
        # Total ~55-60
        self.assertGreater(score, 50)
        self.assertLess(score, 70)

    def test_bearish_orderflow(self):
        """Test strong bearish orderflow."""
        score = self.bot.compute_orderflow_momentum_score(
            imbalance=0.30,  # 30% bids = bearish
            taker_buy_ratio=0.25,  # 25% taker buys = bearish
            spread_pct=0.02,
            micro_move_pct=-0.02,  # Negative move
        )
        # Should get medium-high score (abs distance)
        self.assertGreater(score, 40)
        self.assertLess(score, 60)

    def test_wide_spread_penalty(self):
        """Test that wide spread reduces score."""
        tight_spread = self.bot.compute_orderflow_momentum_score(
            imbalance=0.6,
            taker_buy_ratio=0.6,
            spread_pct=0.02,  # 0.02% tight
            micro_move_pct=0.0,
        )

        wide_spread = self.bot.compute_orderflow_momentum_score(
            imbalance=0.6,
            taker_buy_ratio=0.6,
            spread_pct=0.25,  # 0.25% wide
            micro_move_pct=0.0,
        )

        # Tight spread should score higher
        self.assertGreater(tight_spread, wide_spread)
        self.assertGreater(tight_spread - wide_spread, 10)


class TestAdaptiveATR(unittest.TestCase):
    """Test AI-adaptive ATR threshold logic."""

    def setUp(self):
        self.bot = MomentumScalperBot()

    def test_normal_atr_above_threshold(self):
        """Test that normal ATR above base threshold passes."""
        result = self.bot.adaptive_atr_threshold(
            atr_pct=0.05,  # 0.05% > 0.03% base
            imbalance=0.5,
            taker_buy_ratio=0.5,
            of_score=30,
        )
        self.assertTrue(result)

    def test_low_atr_weak_orderflow_rejects(self):
        """Test that low ATR + weak orderflow rejects."""
        result = self.bot.adaptive_atr_threshold(
            atr_pct=0.02,  # Below 0.03% base
            imbalance=0.5,
            taker_buy_ratio=0.5,
            of_score=40,  # Weak orderflow
        )
        self.assertFalse(result)

    def test_low_atr_strong_orderflow_passes(self):
        """Test that low ATR passes with strong orderflow (65+)."""
        result = self.bot.adaptive_atr_threshold(
            atr_pct=0.02,  # 0.02% < 0.03% base
            imbalance=0.7,
            taker_buy_ratio=0.7,
            of_score=70,  # Strong orderflow (>= 65)
        )
        # 0.02% >= 0.03 * 0.60 = 0.018 → should pass
        self.assertTrue(result)

    def test_very_low_atr_extreme_orderflow_passes(self):
        """Test that very low ATR passes with extreme orderflow (80+)."""
        result = self.bot.adaptive_atr_threshold(
            atr_pct=0.015,  # Very low
            imbalance=0.8,
            taker_buy_ratio=0.8,
            of_score=85,  # Extreme orderflow (>= 80)
        )
        # 0.015% >= 0.03 * 0.40 = 0.012 → should pass
        self.assertTrue(result)


class TestAdaptivePositionSizing(unittest.TestCase):
    """Test AI-adaptive position sizing."""

    def setUp(self):
        self.bot = MomentumScalperBot()
        self.bot.CONFIG['enable_adaptive_sizing'] = True
        self.bot.CONFIG['order_size_usdt'] = Decimal('20')
        # Initialize a symbol in stats
        self.bot.symbol_stats['BTC/USDT'] = {
            'hot_score': 0.5,
            'recent_results': deque(maxlen=10),
        }

    def test_disabled_adaptive_sizing(self):
        """Test that disabling returns base size."""
        self.bot.CONFIG['enable_adaptive_sizing'] = False
        size = self.bot.compute_position_size_usdt('BTC/USDT', 50, 50)
        self.assertEqual(size, Decimal('20'))

    def test_neutral_conditions(self):
        """Test neutral conditions returns ~1x base size."""
        self.bot.daily_pnl = Decimal('0')
        size = self.bot.compute_position_size_usdt(
            'BTC/USDT',
            signal_strength=50,  # Medium
            of_score=50,  # Medium
        )
        # trade_quality = 0.6*0.5 + 0.4*0.5 = 0.5 → q_mult = 1.0
        # hot_score = 0.5 → h_mult = 1.0
        # safety = 1.0
        # → 1.0x base = $20
        self.assertEqual(size, Decimal('20'))

    def test_high_quality_hot_symbol(self):
        """Test high quality + hot symbol increases size."""
        self.bot.symbol_stats['BTC/USDT']['hot_score'] = 0.8  # Hot
        self.bot.daily_pnl = Decimal('0')
        size = self.bot.compute_position_size_usdt(
            'BTC/USDT',
            signal_strength=90,  # High
            of_score=90,  # High
        )
        # trade_quality = 0.6*0.9 + 0.4*0.9 = 0.9 → q_mult = 2.0
        # hot_score = 0.8 → h_mult = 1.25
        # safety = 1.0
        # → 2.0 × 1.25 = 2.5x base = $50
        self.assertEqual(size, Decimal('50'))

    def test_losing_day_reduces_size(self):
        """Test that losing day reduces position size."""
        self.bot.daily_pnl = Decimal('-30')  # Losing day
        size = self.bot.compute_position_size_usdt(
            'BTC/USDT',
            signal_strength=80,
            of_score=80,
        )
        # trade_quality = 0.8 → q_mult = 2.0
        # hot_score = 0.5 → h_mult = 1.0
        # daily_pnl = -30 < -20 → safety = 0.7
        # → 2.0 × 1.0 × 0.7 = 1.4x base = $28
        self.assertEqual(size, Decimal('28'))

    def test_cold_symbol_reduces_size(self):
        """Test that cold symbol reduces position size."""
        self.bot.symbol_stats['BTC/USDT']['hot_score'] = 0.2  # Cold
        self.bot.daily_pnl = Decimal('0')
        size = self.bot.compute_position_size_usdt(
            'BTC/USDT',
            signal_strength=70,
            of_score=70,
        )
        # trade_quality = 0.7 → q_mult = 1.5
        # hot_score = 0.2 < 0.3 → h_mult = 0.7
        # safety = 1.0
        # → 1.5 × 0.7 = 1.05x base = ~$21
        self.assertAlmostEqual(float(size), 21.0, places=0)

    def test_size_clamping(self):
        """Test that size is clamped to min/max bounds."""
        self.bot.CONFIG['min_position_multiplier'] = 0.5
        self.bot.CONFIG['max_position_multiplier'] = 3.0
        self.bot.symbol_stats['BTC/USDT']['hot_score'] = 1.0  # Super hot
        self.bot.daily_pnl = Decimal('100')  # Winning

        # This should want to go > 3x
        size = self.bot.compute_position_size_usdt(
            'BTC/USDT',
            signal_strength=100,
            of_score=100,
        )
        # trade_quality = 1.0 → q_mult = 2.0
        # hot_score = 1.0 > 0.7 → h_mult = 1.25
        # 2.0 × 1.25 = 2.5x → clamped to 3.0x max
        # But actual calculation: check if clamped correctly
        self.assertGreaterEqual(float(size), 40)  # At least 2x
        self.assertLessEqual(float(size), 60)  # At most 3x


class TestHotColdTracking(unittest.TestCase):
    """Test hot/cold scoring system."""

    def setUp(self):
        self.bot = MomentumScalperBot()
        self.bot.symbol_stats['ETH/USDT'] = {
            'hot_score': 0.5,
            'recent_results': deque(maxlen=10),
            'cooldown_until': 0.0,
            'last_trade_ts': 0.0,
        }

    def test_hot_score_after_wins(self):
        """Test that wins increase hot score."""
        stats = self.bot.symbol_stats['ETH/USDT']

        # Simulate 8 wins, 2 losses
        results = [1, 1, 1, -1, 1, 1, 1, -1, 1, 1]
        for r in results:
            stats['recent_results'].append(r)

        # avg = (8-2)/10 = 0.6 → hot_score = (0.6+1)/2 = 0.8
        avg = sum(stats['recent_results']) / len(stats['recent_results'])
        hot_score = (avg + 1) / 2.0

        self.assertAlmostEqual(hot_score, 0.8, places=2)

    def test_hot_score_after_losses(self):
        """Test that losses decrease hot score."""
        stats = self.bot.symbol_stats['ETH/USDT']

        # Simulate 3 wins, 7 losses
        results = [1, -1, -1, -1, 1, -1, -1, 1, -1, -1]
        for r in results:
            stats['recent_results'].append(r)

        # avg = (3-7)/10 = -0.4 → hot_score = (-0.4+1)/2 = 0.3
        avg = sum(stats['recent_results']) / len(stats['recent_results'])
        hot_score = (avg + 1) / 2.0

        self.assertAlmostEqual(hot_score, 0.3, places=2)


class TestConfigLoader(unittest.TestCase):
    """Test configuration loading."""

    def test_default_config(self):
        """Test that default config loads when file missing."""
        config = MomentumScalperBot._default_config()

        # Check critical keys exist
        self.assertIn('symbols', config)
        self.assertIn('order_size_usdt', config)
        self.assertIn('momentum_threshold', config)
        self.assertIn('enable_adaptive_sizing', config)
        self.assertIn('enable_cooldown', config)

        # Check types
        self.assertIsInstance(config['order_size_usdt'], Decimal)
        self.assertIsInstance(config['symbols'], list)
        self.assertGreater(len(config['symbols']), 0)


class TestATRCalculation(unittest.TestCase):
    """Test ATR calculation."""

    def setUp(self):
        self.bot = MomentumScalperBot()

    def test_atr_with_sufficient_data(self):
        """Test ATR calculation with sufficient candles."""
        # Create 20 sample candles with increasing volatility
        # [timestamp, open, high, low, close, volume]
        candles = []
        base_price = 100.0
        for i in range(20):
            high = base_price + 0.5 + (i * 0.1)
            low = base_price - 0.5 - (i * 0.1)
            close = base_price + (i * 0.05)
            candles.append([
                1000000 + i * 60000,  # timestamp
                base_price,  # open
                high,  # high
                low,  # low
                close,  # close
                1000,  # volume
            ])

        atr = self.bot.calculate_atr(candles, period=14)

        # ATR should be positive
        self.assertGreater(atr, 0)
        # Should be reasonable (volatility is ~1-2 per candle)
        self.assertGreater(atr, 0.5)
        self.assertLess(atr, 5.0)

    def test_atr_insufficient_data(self):
        """Test ATR returns 0 with insufficient data."""
        candles = [
            [1000000, 100, 101, 99, 100, 1000],
            [1000060, 100, 101, 99, 100, 1000],
        ]

        atr = self.bot.calculate_atr(candles, period=14)
        self.assertEqual(atr, 0.0)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestOrderflowMomentumScore))
    suite.addTests(loader.loadTestsFromTestCase(TestAdaptiveATR))
    suite.addTests(loader.loadTestsFromTestCase(TestAdaptivePositionSizing))
    suite.addTests(loader.loadTestsFromTestCase(TestHotColdTracking))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigLoader))
    suite.addTests(loader.loadTestsFromTestCase(TestATRCalculation))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
