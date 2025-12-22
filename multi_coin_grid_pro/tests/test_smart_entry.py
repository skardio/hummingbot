"""
Unit tests for SmartEntryFilter v2.0
"""
import logging
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from multi_coin_grid_pro.core.models import CandleIndicators  # noqa: E402
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig, SmartEntryFilter  # noqa: E402

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSmartEntryFilter(unittest.TestCase):
    """Test SmartEntry v2.0 filtering logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)  # Suppress logs during tests

        # Base configuration (matches config.prod.yaml v3.0)
        self.base_cfg = SmartEntryBaseConfig(
            rsi_buy_max=60.0,
            rsi_extreme_low=25.0,
            rsi_block_min=70.0,
            vwap_max_deviation_pct=3.0,
            min_wick_ratio=0.25,  # Updated to match v3.0 config
            max_atr_pct_for_grid=6.0,
            min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5,
            max_down_accel_pct=-1.0,
            max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0,
            min_trend_24h_pct=-12.0,
            # Phase 2: Slippage Protection
            slippage_check_enabled=True,
            max_entry_spread_pct=0.5,
            # Phase 2: Order Book Depth
            depth_check_enabled=True,
            min_depth_multiplier=3.0,
        )

        # Coin profiles with overrides
        self.coin_profiles = {
            "ATOM-EUR": {
                "min_wick_ratio": 0.20,  # More lenient for ATOM
            },
            "SOL-EUR": {
                "max_atr_pct_for_grid": 5.0,  # More strict for SOL
            }
        }

        self.filter = SmartEntryFilter(self.base_cfg, self.coin_profiles, self.logger)

    def test_good_entry_conditions(self):
        """Test entry allowed with good conditions"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,  # Good RSI
            vwap=Decimal("10.4"),  # Close to VWAP
            atr_pct=2.5,  # Good volatility
            wick_ratio=0.50,  # Good structure
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,  # Reasonable trend
            change_5m_pct=0.2,  # Small move
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertTrue(allowed, f"Entry should be allowed: {reason}")
        self.assertIn("BUY ALLOWED", reason)

    def test_rsi_overbought_block(self):
        """Test RSI overbought blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=75.0,  # Too high
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("RSI", reason)
        self.assertIn("overbought", reason.lower())

    def test_rsi_oversold_block(self):
        """Test RSI oversold blocking (falling knife)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=20.0,  # Too low
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("RSI", reason)
        self.assertIn("falling knife", reason.lower())

    def test_vwap_deviation_block(self):
        """Test VWAP deviation blocking"""
        indicators = CandleIndicators(
            price=Decimal("11.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),  # 10% deviation
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("VWAP", reason)

    def test_wick_ratio_block(self):
        """Test wick ratio blocking (poor structure)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.20,  # Too low (below 0.25 threshold)
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("wick_ratio", reason)
        self.assertIn("poor structure", reason.lower())

    def test_coin_profile_override(self):
        """Test coin-specific profile overrides"""
        # ATOM has min_wick_ratio=0.20 vs base 0.25
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.22,  # Between ATOM override (0.20) and base (0.25)
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Should fail for BTC (uses base config with 0.25 threshold)
        allowed_btc, _, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed_btc)

        # Should pass for ATOM (has override)
        allowed_atom, reason_atom, _ = self.filter.allows_entry("ATOM-EUR", indicators)
        self.assertTrue(allowed_atom, f"ATOM should be allowed with profile override: {reason_atom}")

    def test_atr_too_low(self):
        """Test ATR too low blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=0.3,  # Too low
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("ATR", reason)
        self.assertIn("too low", reason.lower())

    def test_atr_too_high(self):
        """Test ATR too high blocking (chaos)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=8.0,  # Too high
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("ATR", reason)
        self.assertIn("chaotic", reason.lower())

    def test_5m_spike_detection(self):
        """Test 5-minute spike blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=5.0,  # Large spike
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("5m move", reason)
        self.assertIn("spike", reason.lower())

    def test_downside_acceleration_block(self):
        """Test downside acceleration blocking (falling knife)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=-2.0,  # 1h much worse than 4h
            trend_4h_pct=0.5,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("accel", reason)

    def test_24h_trend_extended(self):
        """Test 24h trend too extended blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=15.0,  # Too high
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("24h trend", reason)
        self.assertIn("extended", reason.lower())


if __name__ == "__main__":
    unittest.main()
