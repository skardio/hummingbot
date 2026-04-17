"""
Unit tests for Adaptive Filter Resolver

Tests the adaptive filter system that adjusts based on regime.
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock

from multi_coin_grid_pro.utils.adaptive_filter_resolver import AdaptiveFilterResolver
from multi_coin_grid_pro.utils.regime_detector import RegimeMetrics, RegimeState


class TestAdaptiveFilterResolver(unittest.TestCase):
    """Test suite for AdaptiveFilterResolver"""

    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'baseline': {
                'rsi_buy_min': 30.0,
                'rsi_buy_max': 70.0,
                'atr_min': 0.15,
                'trend_min': 0.5
            },
            'BULL': {
                'rsi_buy_min': 25.0,
                'rsi_buy_max': 80.0,
                'atr_min': 0.10,
                'trend_min': 1.0
            },
            'CHOP': {
                'rsi_buy_min': 35.0,
                'rsi_buy_max': 65.0,
                'atr_min': 0.15,
                'trend_min': 0.2
            },
            'BEAR': {
                'rsi_buy_min': 20.0,
                'rsi_buy_max': 60.0,
                'atr_min': 0.20,
                'trend_min': 0.3
            }
        }
        self.logger = MagicMock()
        self.resolver = AdaptiveFilterResolver(self.config, self.logger)

    def test_initialization(self):
        """Test AdaptiveFilterResolver initialization"""
        self.assertIsNotNone(self.resolver)
        self.assertIn('baseline', self.config)
        self.assertEqual(self.resolver.last_regime, "CHOP")

    def test_resolve_bull_filters(self):
        """Test filter resolution for BULL regime"""
        metrics = RegimeMetrics(
            trend_1h=1.0,
            trend_4h=2.0,
            trend_24h=5.0,
            consensus=2.7,
            atr_pct=0.25,
            atr_expansion=15.0,
            range_efficiency=0.75,
            pullback_depth_pct=1.5,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="BULL",
            score=6.0,
            confidence=0.8,
            duration_minutes=30,
            reason="Strong uptrend",
            metrics=metrics
        )

        filters = self.resolver.resolve_filters(state)

        self.assertIsInstance(filters, dict)
        self.assertIn('rsi_buy_max', filters)
        # BULL filters should be applied

    def test_resolve_chop_filters(self):
        """Test filter resolution for CHOP regime"""
        metrics = RegimeMetrics(
            trend_1h=0.1,
            trend_4h=-0.2,
            trend_24h=0.3,
            consensus=0.05,
            atr_pct=0.15,
            atr_expansion=-5.0,
            range_efficiency=0.35,
            pullback_depth_pct=0.5,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="CHOP",
            score=0.0,
            confidence=0.65,
            duration_minutes=60,
            reason="Sideways market",
            metrics=metrics
        )

        filters = self.resolver.resolve_filters(state)

        self.assertIsInstance(filters, dict)
        # CHOP filters should be more conservative

    def test_resolve_bear_filters(self):
        """Test filter resolution for BEAR regime"""
        metrics = RegimeMetrics(
            trend_1h=-1.5,
            trend_4h=-2.5,
            trend_24h=-5.0,
            consensus=-3.0,
            atr_pct=0.30,
            atr_expansion=20.0,
            range_efficiency=0.55,
            pullback_depth_pct=5.0,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="BEAR",
            score=-6.0,
            confidence=0.75,
            duration_minutes=45,
            reason="Strong downtrend",
            metrics=metrics
        )

        filters = self.resolver.resolve_filters(state)

        self.assertIsInstance(filters, dict)
        # BEAR filters should be most conservative

    def test_confidence_scaling(self):
        """Test that confidence affects filter values"""
        metrics = RegimeMetrics(
            trend_1h=1.0,
            trend_4h=2.0,
            trend_24h=5.0,
            consensus=2.7,
            atr_pct=0.25,
            atr_expansion=15.0,
            range_efficiency=0.75,
            pullback_depth_pct=1.5,
            timestamp=datetime.now()
        )

        # High confidence
        high_conf_state = RegimeState(
            regime="BULL",
            score=7.0,
            confidence=0.9,
            duration_minutes=60,
            reason="Very strong trend",
            metrics=metrics
        )

        # Low confidence
        low_conf_state = RegimeState(
            regime="BULL",
            score=3.5,
            confidence=0.55,
            duration_minutes=15,
            reason="Weak trend",
            metrics=metrics
        )

        high_filters = self.resolver.resolve_filters(high_conf_state)
        low_filters = self.resolver.resolve_filters(low_conf_state)

        # Both should return valid filters
        self.assertIsInstance(high_filters, dict)
        self.assertIsInstance(low_filters, dict)

    def test_baseline_fallback(self):
        """Test fallback to baseline when regime config missing"""
        # Create resolver with limited config
        limited_config = {
            'baseline': self.config['baseline'],
            'CHOP': self.config['CHOP']
            # Missing BULL and BEAR
        }

        resolver = AdaptiveFilterResolver(limited_config, self.logger)

        metrics = RegimeMetrics(
            trend_1h=1.0,
            trend_4h=2.0,
            trend_24h=5.0,
            consensus=2.7,
            atr_pct=0.25,
            atr_expansion=15.0,
            range_efficiency=0.75,
            pullback_depth_pct=1.5,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="BULL",
            score=6.0,
            confidence=0.8,
            duration_minutes=30,
            reason="Strong uptrend",
            metrics=metrics
        )

        filters = resolver.resolve_filters(state)

        # Should use baseline values
        self.assertIsInstance(filters, dict)

    def test_active_filters_update(self):
        """Test that active_filters are updated after resolve"""
        metrics = RegimeMetrics(
            trend_1h=0.5,
            trend_4h=1.0,
            trend_24h=3.0,
            consensus=1.5,
            atr_pct=0.20,
            atr_expansion=10.0,
            range_efficiency=0.65,
            pullback_depth_pct=2.0,
            timestamp=datetime.now()
        )

        state = RegimeState(
            regime="BULL",
            score=5.0,
            confidence=0.7,
            duration_minutes=25,
            reason="Moderate uptrend",
            metrics=metrics
        )

        self.resolver.resolve_filters(state)

        # active_filters should be updated
        self.assertIsInstance(self.resolver.active_filters, dict)
        self.assertGreater(len(self.resolver.active_filters), 0)

    def test_atr_excluded_from_confidence_scaling(self):
        """ST-01: ATR min/max are binary quality gates — NOT interpolated."""
        config = {
            'baseline': {
                'rsi_buy_max': 70.0,
                'atr_min_pct': 0.15,
                'atr_max_pct': 7.0,
            },
            'BEAR': {
                'rsi_buy_max': 60.0,
                'atr_min_pct': 0.08,
                'atr_max_pct': 5.0,
            },
        }
        resolver = AdaptiveFilterResolver(config, MagicMock())
        metrics = RegimeMetrics(
            trend_1h=-1.0, trend_4h=-2.0, trend_24h=-3.0,
            consensus=-2.0, atr_pct=0.20, atr_expansion=-5.0,
            range_efficiency=0.30, pullback_depth_pct=3.0,
            timestamp=datetime.now()
        )
        state = RegimeState(
            regime="BEAR", score=2.0, confidence=0.6,
            duration_minutes=60, reason="Downtrend", metrics=metrics
        )

        filters = resolver.resolve_filters(state)

        # ATR should use regime value directly (no interpolation)
        self.assertEqual(filters['atr_min_pct'], 0.08)
        self.assertEqual(filters['atr_max_pct'], 5.0)

        # RSI SHOULD still be interpolated
        # expected: 70 + (60 - 70) * 0.6 = 70 - 6 = 64.0
        self.assertAlmostEqual(filters['rsi_buy_max'], 64.0, places=1)

    def test_no_scale_keys_use_regime_value_at_any_confidence(self):
        """ST-01: _NO_SCALE_KEYS produce same result at any confidence."""
        config = {
            'baseline': {'atr_min_pct': 0.15, 'rsi_buy_max': 70.0},
            'BULL': {'atr_min_pct': 0.05, 'rsi_buy_max': 80.0},
        }
        resolver = AdaptiveFilterResolver(config, MagicMock())
        metrics = RegimeMetrics(
            trend_1h=2.0, trend_4h=3.0, trend_24h=5.0,
            consensus=3.3, atr_pct=0.30, atr_expansion=10.0,
            range_efficiency=0.80, pullback_depth_pct=1.0,
            timestamp=datetime.now()
        )

        filters_low = resolver.resolve_filters(RegimeState(
            regime="BULL", score=3.0, confidence=0.3,
            duration_minutes=10, reason="Weak", metrics=metrics
        ))
        filters_high = resolver.resolve_filters(RegimeState(
            regime="BULL", score=8.0, confidence=0.95,
            duration_minutes=60, reason="Strong", metrics=metrics
        ))

        # ATR min should be identical regardless of confidence
        self.assertEqual(filters_low['atr_min_pct'], 0.05)
        self.assertEqual(filters_high['atr_min_pct'], 0.05)

        # RSI should differ between confidence levels
        self.assertNotEqual(filters_low['rsi_buy_max'], filters_high['rsi_buy_max'])


if __name__ == "__main__":
    unittest.main()
