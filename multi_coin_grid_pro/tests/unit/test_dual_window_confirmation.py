"""
Unit tests for Dual-Window VWAP Slope Confirmation (Story 9).

Tests dual-window (5m + 15m) confirmation logic to reduce false positives
during healthy consolidations while still catching true blow-off tops.
"""

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from multi_coin_grid_pro.filters.smart_entry_filter import SmartEntryConfig, SmartEntryFilter


@dataclass
class MockMetrics:
    """Mock momentum metrics for testing."""
    vwap_deviation_pct: float
    vwap_slope_5m_pct: float
    vwap_slope_15m_pct: float


class TestDualWindowConfirmation(unittest.TestCase):
    """Test suite for dual-window VWAP slope guard."""

    def setUp(self):
        """Create filter instance for each test."""
        self.config = SmartEntryConfig()
        self.config.vwap_slope_guard_enabled = True
        self.config.vwap_slope_guard_shadow_mode = False  # Live mode
        self.config.vwap_slope_dual_confirmation = True  # Enable dual-window
        self.config.vwap_slope_deviation_high_pct = 15.0
        self.config.vwap_slope_min_pct_5m = 0.05
        self.config.vwap_slope_min_pct_15m = 0.10
        self.config.vwap_slope_log_details = False  # Reduce noise in tests

        self.filter = SmartEntryFilter(config=self.config)

    def test_dual_window_both_flat_rejects(self):
        """Test that both windows flat triggers rejection (true blow-off top)."""
        # Setup: Price far above VWAP, both slopes flat
        vwap_dev = 19.0  # > 15% threshold
        slope_5m = 0.02  # < 0.05% threshold
        slope_15m = 0.03  # < 0.10% threshold

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="PEPE-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertFalse(allowed)
        self.assertIsNotNone(reason)
        self.assertIn("VWAP_SLOPE_DUAL_FLAT", reason)
        self.assertIn("5m=0.02%", reason)
        self.assertIn("15m=0.03%", reason)

    def test_dual_window_5m_rising_15m_flat_passes(self):
        """Test healthy consolidation: 5m rising, 15m temporarily flat = PASS."""
        # Setup: 5m slope still positive (momentum intact)
        vwap_dev = 19.0
        slope_5m = 0.15  # > 0.05% threshold (healthy)
        slope_15m = 0.03  # < 0.10% threshold (temporarily flat)

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="SUI-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_dual_window_5m_flat_15m_rising_passes(self):
        """Test temporary 5m pause during strong 15m trend = PASS."""
        # Setup: 15m slope still strong
        vwap_dev = 19.0
        slope_5m = 0.03  # < 0.05% threshold (temporary pause)
        slope_15m = 0.18  # > 0.10% threshold (strong trend)

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="DOT-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_dual_window_both_rising_passes(self):
        """Test strong trend: both windows rising = PASS."""
        vwap_dev = 19.0
        slope_5m = 0.40  # Strong 5m momentum
        slope_15m = 0.25  # Strong 15m momentum

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="AVAX-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_single_window_mode_backward_compat(self):
        """Test single-window mode (15m only) for backward compatibility."""
        # Disable dual confirmation
        self.config.vwap_slope_dual_confirmation = False
        self.filter = SmartEntryFilter(config=self.config)

        # Setup: 5m rising but 15m flat
        vwap_dev = 19.0
        slope_5m = 0.20  # Healthy (but ignored in single-window mode)
        slope_15m = 0.03  # < 0.10% threshold

        # Should REJECT (only checks 15m)
        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="LINK-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertFalse(allowed)
        self.assertIn("VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH", reason)
        self.assertNotIn("DUAL", reason)  # Single-window rejection

    def test_deviation_below_threshold_skips_check(self):
        """Test that low deviation skips slope check."""
        # Setup: Deviation below threshold
        vwap_dev = 10.0  # < 15% threshold
        slope_5m = -0.05  # Negative (would normally reject)
        slope_15m = -0.02  # Negative

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="ADA-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_negative_deviation_skips_check(self):
        """Test that price below VWAP skips slope check."""
        vwap_dev = -5.0  # Negative deviation (price below VWAP)
        slope_5m = 0.01
        slope_15m = 0.02

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="XRP-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_missing_5m_slope_data(self):
        """Test graceful handling when 5m slope unavailable."""
        vwap_dev = 19.0
        slope_5m = None  # Missing data
        slope_15m = 0.03

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="SOL-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        # Should allow (don't reject if we can't calculate)
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_missing_15m_slope_data(self):
        """Test graceful handling when 15m slope unavailable."""
        vwap_dev = 19.0
        slope_5m = 0.03
        slope_15m = None  # Missing data

        allowed, reason = self.filter.check_vwap_slope_guard(
            symbol="MATIC-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )

        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_shadow_mode_logs_but_allows(self):
        """Test shadow mode logs rejection but allows entry."""
        # Enable shadow mode
        self.config.vwap_slope_guard_shadow_mode = True
        self.config.vwap_slope_log_details = True
        self.filter = SmartEntryFilter(config=self.config)

        # Setup: Would reject in live mode
        vwap_dev = 19.0
        slope_5m = 0.02  # Flat
        slope_15m = 0.03  # Flat

        with patch('multi_coin_grid_pro.filters.smart_entry_filter.logger') as mock_logger:
            allowed, reason = self.filter.check_vwap_slope_guard(
                symbol="DOGE-EUR",
                vwap_dev_pct=vwap_dev,
                vwap_slope_5m_pct=slope_5m,
                vwap_slope_15m_pct=slope_15m,
                regime="BULL"
            )

            # Should ALLOW in shadow mode
            self.assertTrue(allowed)
            self.assertIsNone(reason)

            # Should log shadow rejection
            logged_messages = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("[SHADOW]" in msg for msg in logged_messages))
            self.assertTrue(any("Would reject" in msg for msg in logged_messages))

    def test_regime_aware_thresholds(self):
        """Test regime-specific thresholds via momentum_thresholds config."""
        # Setup momentum thresholds with regime overrides
        self.config.momentum_thresholds = {
            "baseline": {
                "slope_min_pct_5m": 0.05,
                "slope_min_pct_15m": 0.10,
                "deviation_high_pct": 15.0
            },
            "regimes": {
                "BULL": {
                    "slope_min_pct_5m": 0.00,  # Allow flat 5m in bull
                    "slope_min_pct_15m": 0.02,  # Lenient 15m in bull
                    "deviation_high_pct": 18.0
                },
                "CHOP": {
                    "slope_min_pct_5m": 0.05,
                    "slope_min_pct_15m": 0.15,  # Strict in chop
                    "deviation_high_pct": 12.0
                }
            }
        }
        self.filter = SmartEntryFilter(config=self.config)

        # Test BULL regime (lenient)
        vwap_dev = 19.0
        slope_5m = -0.01  # Slightly negative (OK in BULL)
        slope_15m = 0.01  # Very flat (< 0.02% threshold)

        # Should REJECT (both below BULL thresholds)
        allowed, _ = self.filter.check_vwap_slope_guard(
            symbol="PEPE-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="BULL"
        )
        self.assertFalse(allowed)

        # Test CHOP regime (strict)
        vwap_dev = 13.0  # Above CHOP threshold (12%)
        slope_5m = 0.04  # < 0.05% (below CHOP threshold)
        slope_15m = 0.10  # < 0.15% (below CHOP threshold)

        # Should REJECT in CHOP (stricter thresholds)
        allowed, _ = self.filter.check_vwap_slope_guard(
            symbol="SUI-EUR",
            vwap_dev_pct=vwap_dev,
            vwap_slope_5m_pct=slope_5m,
            vwap_slope_15m_pct=slope_15m,
            regime="CHOP"
        )
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
