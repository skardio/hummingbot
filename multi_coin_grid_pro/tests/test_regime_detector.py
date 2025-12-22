"""
Unit tests for Regime Detector

Tests the market regime detection system.
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from multi_coin_grid_pro.utils.regime_detector import RegimeDetector, RegimeMetrics, RegimeState


class TestRegimeMetrics(unittest.TestCase):
    """Test suite for RegimeMetrics"""

    def test_regime_metrics_creation(self):
        """Test RegimeMetrics dataclass creation"""
        metrics = RegimeMetrics(
            trend_1h=0.5,
            trend_4h=1.2,
            trend_24h=3.5,
            consensus=1.7,
            atr_pct=0.25,
            atr_expansion=10.0,
            range_efficiency=0.65,
            pullback_depth_pct=2.5,
            timestamp=datetime.now()
        )

        self.assertEqual(metrics.trend_1h, 0.5)
        self.assertEqual(metrics.trend_4h, 1.2)
        self.assertEqual(metrics.consensus, 1.7)
        self.assertIsInstance(metrics.timestamp, datetime)


class TestRegimeState(unittest.TestCase):
    """Test suite for RegimeState"""

    def test_regime_state_creation(self):
        """Test RegimeState dataclass creation"""
        metrics = RegimeMetrics(
            trend_1h=0.5,
            trend_4h=1.2,
            trend_24h=3.5,
            consensus=1.7,
            atr_pct=0.25,
            atr_expansion=10.0,
            range_efficiency=0.65,
            pullback_depth_pct=2.5,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="BULL",
            score=5.5,
            confidence=0.75,
            duration_minutes=30,
            reason="Strong uptrend",
            metrics=metrics
        )

        self.assertEqual(state.regime, "BULL")
        self.assertEqual(state.score, 5.5)
        self.assertEqual(state.confidence, 0.75)
        self.assertIsInstance(state.metrics, RegimeMetrics)


class TestRegimeDetector(unittest.TestCase):
    """Test suite for RegimeDetector"""

    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'bull_threshold': 3.0,
            'bear_threshold': -3.0,
            'chop_range': 2.0
        }
        self.logger = MagicMock()
        self.detector = RegimeDetector(self.config, self.logger)

    def test_initialization(self):
        """Test RegimeDetector initialization"""
        self.assertIsNotNone(self.detector)
        self.assertEqual(self.detector.current_regime, "CHOP")
        self.assertIsInstance(self.detector.regime_start_time, datetime)

    def test_calculate_metrics_basic(self):
        """Test basic metrics calculation"""
        trend_data = {
            'trend_1h': 0.5,
            'trend_4h': 1.2,
            'trend_24h': 3.5,
            'consensus': 1.7
        }

        candles_1h = self._create_mock_candles(50)
        candles_4h = self._create_mock_candles(30)

        metrics = self.detector.calculate_metrics(trend_data, candles_1h, candles_4h)

        self.assertIsInstance(metrics, RegimeMetrics)
        self.assertEqual(metrics.trend_1h, 0.5)
        self.assertEqual(metrics.trend_4h, 1.2)
        self.assertEqual(metrics.consensus, 1.7)

    def test_calculate_metrics_insufficient_data(self):
        """Test metrics calculation with insufficient candles"""
        trend_data = {
            'trend_1h': 0.5,
            'trend_4h': 1.2,
            'trend_24h': 3.5,
            'consensus': 1.7
        }

        candles_1h = self._create_mock_candles(5)  # Too few
        candles_4h = self._create_mock_candles(3)

        metrics = self.detector.calculate_metrics(trend_data, candles_1h, candles_4h)

        self.assertIsInstance(metrics, RegimeMetrics)
        # Should still work but with limited data

    def test_regime_enum_values(self):
        """Test regime string values"""
        valid_regimes = ["BULL", "BEAR", "CHOP"]
        self.assertIn(self.detector.current_regime, valid_regimes)

    def test_regime_history_tracking(self):
        """Test that regime history is tracked"""
        self.assertEqual(len(self.detector.regime_history), 0)
        # History tracking happens in detect_regime method

    # Helper methods

    def _create_mock_candles(self, count):
        """Create mock candle data"""
        candles = []
        base_price = 50000.0

        for i in range(count):
            candles.append({
                "timestamp": 1700000000 + (i * 3600),
                "open": base_price + i * 10,
                "high": base_price + i * 10 + 50,
                "low": base_price + i * 10 - 30,
                "close": base_price + i * 10 + 20,
                "volume": 1000000
            })

        return candles


if __name__ == "__main__":
    unittest.main()
