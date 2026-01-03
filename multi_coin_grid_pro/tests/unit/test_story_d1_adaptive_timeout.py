"""
Unit tests for Story D1: Adaptive Timeout Calculator

Tests AdaptiveTimeout volatility calculations and timeout adjustments.
"""

import unittest
from decimal import Decimal

from multi_coin_grid_pro.utils.adaptive_timeout import AdaptiveTimeout


class TestAdaptiveTimeout(unittest.TestCase):
    """Test AdaptiveTimeout calculator"""

    def setUp(self):
        """Create calculator with base 600s (10min) timeout"""
        self.calculator = AdaptiveTimeout(base_timeout_sec=600)

    def test_low_volatility_reduces_timeout(self):
        """Low volatility should reduce timeout (faster stall detection)"""
        # Very low volatility: price barely moves (<0.5% ATR for LOW regime)
        current_price = Decimal("100.0")
        highs = [Decimal("100.2"), Decimal("100.15"), Decimal("100.25")]
        lows = [Decimal("99.8"), Decimal("99.85"), Decimal("99.75")]
        closes = [Decimal("100.0"), Decimal("100.0"), Decimal("100.0")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "LOW")
        self.assertEqual(adjustment.adjustment_factor, 0.7)  # -30%
        self.assertEqual(adjustment.adjusted_timeout_sec, 420)  # 600 * 0.7
        self.assertIn("decreased", adjustment.reasoning)

    def test_normal_volatility_unchanged_timeout(self):
        """Normal volatility should keep timeout unchanged"""
        # Normal volatility: 1.5-2% ATR
        current_price = Decimal("100.0")
        highs = [Decimal("101.0"), Decimal("101.2"), Decimal("100.8")]
        lows = [Decimal("99.0"), Decimal("98.8"), Decimal("99.2")]
        closes = [Decimal("100.0"), Decimal("100.0"), Decimal("100.0")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "NORMAL")
        self.assertEqual(adjustment.adjustment_factor, 1.0)  # no change
        self.assertEqual(adjustment.adjusted_timeout_sec, 600)  # unchanged
        self.assertIn("unchanged", adjustment.reasoning)

    def test_high_volatility_increases_timeout(self):
        """High volatility should increase timeout (more time for fills)"""
        # High volatility: 4-5% ATR
        current_price = Decimal("100.0")
        highs = [Decimal("102.5"), Decimal("102.2"), Decimal("102.8")]
        lows = [Decimal("97.5"), Decimal("97.8"), Decimal("97.2")]
        closes = [Decimal("100.0"), Decimal("100.0"), Decimal("100.0")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "HIGH")
        self.assertEqual(adjustment.adjustment_factor, 1.5)  # +50%
        self.assertEqual(adjustment.adjusted_timeout_sec, 900)  # 600 * 1.5
        self.assertIn("increased", adjustment.reasoning)

    def test_extreme_volatility_doubles_timeout(self):
        """Extreme volatility should double timeout"""
        # Extreme volatility: >10% ATR
        current_price = Decimal("100.0")
        highs = [Decimal("115.0"), Decimal("112.0"), Decimal("118.0")]
        lows = [Decimal("85.0"), Decimal("88.0"), Decimal("82.0")]
        closes = [Decimal("100.0"), Decimal("105.0"), Decimal("95.0")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "EXTREME")
        self.assertEqual(adjustment.adjustment_factor, 2.0)  # +100%
        self.assertEqual(adjustment.adjusted_timeout_sec, 1200)  # 600 * 2.0
        self.assertIn("increased", adjustment.reasoning)

    def test_timeout_minimum_bound(self):
        """Timeout should not go below MIN_TIMEOUT_SEC (180s)"""
        # Very low base timeout + low volatility
        calculator = AdaptiveTimeout(base_timeout_sec=200)

        current_price = Decimal("100.0")
        highs = [Decimal("100.3"), Decimal("100.2"), Decimal("100.4")]
        lows = [Decimal("99.7"), Decimal("99.8"), Decimal("99.6")]
        closes = [Decimal("100.0"), Decimal("100.0"), Decimal("100.0")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        # 200 * 0.7 = 140, but should be clamped to MIN_TIMEOUT_SEC (180)
        self.assertEqual(adjustment.adjusted_timeout_sec, 180)

    def test_timeout_maximum_bound(self):
        """Timeout should not exceed MAX_TIMEOUT_SEC (1800s)"""
        # Very high base timeout + extreme volatility
        calculator = AdaptiveTimeout(base_timeout_sec=1200)

        current_price = Decimal("100.0")
        highs = [Decimal("130.0"), Decimal("125.0"), Decimal("135.0")]
        lows = [Decimal("70.0"), Decimal("75.0"), Decimal("65.0")]
        closes = [Decimal("100.0"), Decimal("110.0"), Decimal("90.0")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        # 1200 * 2.0 = 2400, but should be clamped to MAX_TIMEOUT_SEC (1800)
        self.assertEqual(adjustment.adjusted_timeout_sec, 1800)

    def test_empty_data_uses_defaults(self):
        """Empty price data should default to NORMAL regime"""
        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=Decimal("100.0"),
            high_prices=[],
            low_prices=[],
            close_prices=[]
        )

        self.assertEqual(adjustment.volatility_regime, "NORMAL")
        self.assertEqual(adjustment.adjusted_timeout_sec, 600)  # unchanged

    def test_single_candle_data(self):
        """Single candle should work (no previous close for true range)"""
        current_price = Decimal("100.0")
        highs = [Decimal("102.0")]
        lows = [Decimal("98.0")]
        closes = [Decimal("100.0")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        # Should calculate based on high-low range
        self.assertIn(adjustment.volatility_regime, ["LOW", "NORMAL", "HIGH", "EXTREME"])
        self.assertGreaterEqual(adjustment.adjusted_timeout_sec, 180)
        self.assertLessEqual(adjustment.adjusted_timeout_sec, 1800)

    def test_atr_calculation(self):
        """Verify ATR calculation with multiple candles"""
        current_price = Decimal("100.0")

        # Candle 1: High=105, Low=95, Range=10
        # Candle 2: High=103, Low=97, Range=6, but high-close[0]=103-100=3, low-close[0]=97-100=3
        #           True Range = max(6, 3, 3) = 6
        # Candle 3: High=108, Low=98, Range=10, high-close[1]=108-101=7, low-close[1]=98-101=3
        #           True Range = max(10, 7, 3) = 10
        # ATR = (10 + 6 + 10) / 3 = 8.67
        # ATR% = 8.67 / 100 = 8.67% → HIGH volatility

        highs = [Decimal("105"), Decimal("103"), Decimal("108")]
        lows = [Decimal("95"), Decimal("97"), Decimal("98")]
        closes = [Decimal("100"), Decimal("101"), Decimal("104")]

        adjustment = self.calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        # ~8% ATR → HIGH or EXTREME regime
        self.assertIn(adjustment.volatility_regime, ["HIGH", "EXTREME"])
        self.assertGreater(adjustment.adjusted_timeout_sec, 600)  # increased timeout


class TestGetRecommendedTimeout(unittest.TestCase):
    """Test simplified get_recommended_timeout interface"""

    def setUp(self):
        """Create calculator"""
        self.calculator = AdaptiveTimeout(base_timeout_sec=600)

    def test_recommended_timeout_success(self):
        """get_recommended_timeout returns adjusted timeout"""
        market_data = {
            'current_price': 100.0,
            'highs': [102.0, 101.5, 102.5],
            'lows': [98.0, 98.5, 97.5],
            'closes': [100.0, 100.5, 99.5]
        }

        timeout = self.calculator.get_recommended_timeout("TEST-USD", market_data)

        self.assertIsInstance(timeout, int)
        self.assertGreaterEqual(timeout, 180)
        self.assertLessEqual(timeout, 1800)

    def test_recommended_timeout_fallback_on_error(self):
        """get_recommended_timeout falls back to base timeout on error"""
        # Invalid market data
        market_data = {'invalid': 'data'}

        timeout = self.calculator.get_recommended_timeout("TEST-USD", market_data)

        # Should fall back to base timeout
        self.assertEqual(timeout, 600)

    def test_recommended_timeout_with_string_prices(self):
        """get_recommended_timeout accepts string prices (converted to Decimal)"""
        market_data = {
            'current_price': "100.0",
            'highs': ["102.0", "101.5", "102.5"],
            'lows': ["98.0", "98.5", "97.5"],
            'closes': ["100.0", "100.5", "99.5"]
        }

        timeout = self.calculator.get_recommended_timeout("TEST-USD", market_data)

        self.assertIsInstance(timeout, int)
        self.assertGreaterEqual(timeout, 180)


class TestVolatilityClassification(unittest.TestCase):
    """Test volatility regime classification thresholds"""

    def test_low_threshold(self):
        """ATR < 1% = LOW"""
        calculator = AdaptiveTimeout(base_timeout_sec=600)

        # 0.6% ATR
        current_price = Decimal("1000.0")
        highs = [Decimal("1003"), Decimal("1003"), Decimal("1003")]
        lows = [Decimal("997"), Decimal("997"), Decimal("997")]
        closes = [Decimal("1000"), Decimal("1000"), Decimal("1000")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "LOW")

    def test_normal_threshold(self):
        """1% <= ATR < 3% = NORMAL"""
        calculator = AdaptiveTimeout(base_timeout_sec=600)

        # 1.5% ATR
        current_price = Decimal("1000.0")
        highs = [Decimal("1008"), Decimal("1008"), Decimal("1008")]
        lows = [Decimal("992"), Decimal("992"), Decimal("992")]
        closes = [Decimal("1000"), Decimal("1000"), Decimal("1000")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "NORMAL")

    def test_high_threshold(self):
        """3% <= ATR < 6% = HIGH"""
        calculator = AdaptiveTimeout(base_timeout_sec=600)

        # 4% ATR
        current_price = Decimal("1000.0")
        highs = [Decimal("1020"), Decimal("1020"), Decimal("1020")]
        lows = [Decimal("980"), Decimal("980"), Decimal("980")]
        closes = [Decimal("1000"), Decimal("1000"), Decimal("1000")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "HIGH")

    def test_extreme_threshold(self):
        """ATR >= 6% = EXTREME"""
        calculator = AdaptiveTimeout(base_timeout_sec=600)

        # 8% ATR
        current_price = Decimal("1000.0")
        highs = [Decimal("1080"), Decimal("1079"), Decimal("1081")]
        lows = [Decimal("920"), Decimal("921"), Decimal("919")]
        closes = [Decimal("1000"), Decimal("1000"), Decimal("1000")]

        adjustment = calculator.calculate_timeout(
            symbol="TEST-USD",
            current_price=current_price,
            high_prices=highs,
            low_prices=lows,
            close_prices=closes
        )

        self.assertEqual(adjustment.volatility_regime, "EXTREME")


if __name__ == '__main__':
    unittest.main()
