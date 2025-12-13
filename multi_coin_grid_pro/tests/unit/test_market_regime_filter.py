"""
Unit tests for Market Regime Filter
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from multi_coin_grid_pro.filters.market_regime_filter import (
    BTCTrendData,
    MarketRegimeConfig,
    MarketRegimeFilter,
    MarketRegimeState,
)


class TestMarketRegimeFilter:
    """Test suite for MarketRegimeFilter"""

    def setup_method(self):
        """Setup for each test"""
        self.config = MarketRegimeConfig()
        self.filter = MarketRegimeFilter(self.config)

    def create_btc_data(
        self,
        trend_1h: float = 0.0,
        trend_4h: float = 0.0,
        trend_24h: float = 0.0,
    ) -> BTCTrendData:
        """Helper to create BTC trend data"""
        return BTCTrendData(
            price=Decimal("85000.0"),
            trend_1h_pct=trend_1h,
            trend_4h_pct=trend_4h,
            trend_24h_pct=trend_24h,
            timestamp=datetime.now(),
        )

    def test_favorable_market_regime(self):
        """Test favorable market conditions"""
        btc_data = self.create_btc_data(
            trend_1h=1.0,    # +1% (above -2% min)
            trend_4h=2.0,    # +2% (above 0% min)
            trend_24h=5.0,   # +5% (above -5% min)
        )

        altcoin_trends = {
            "ETH-EUR": 1.5,
            "SOL-EUR": 2.0,
            "BNB-EUR": 0.8,
            "AVAX-EUR": 1.2,
            "LINK-EUR": 0.6,
        }

        state = self.filter.check_market_regime(btc_data, altcoin_trends)

        assert state.is_favorable is True
        assert state.in_dump_cooldown is False
        assert state.btc_trend_1h == 1.0
        assert state.altcoin_breadth == 1.0  # All 5 coins > 0.5%

    def test_btc_1h_too_bearish(self):
        """Test rejection when BTC 1h is too bearish"""
        btc_data = self.create_btc_data(
            trend_1h=-3.0,   # -3% (below -2% min)
            trend_4h=1.0,
            trend_24h=2.0,
        )

        state = self.filter.check_market_regime(btc_data, None)

        assert state.is_favorable is False
        assert "1h too bearish" in state.reason

    def test_btc_4h_too_bearish(self):
        """Test rejection when BTC 4h is too bearish"""
        btc_data = self.create_btc_data(
            trend_1h=0.5,
            trend_4h=-1.0,   # -1% (below 0% min)
            trend_24h=2.0,
        )

        state = self.filter.check_market_regime(btc_data, None)

        assert state.is_favorable is False
        assert "4h too bearish" in state.reason

    def test_btc_24h_too_bearish(self):
        """Test rejection when BTC 24h is too bearish"""
        btc_data = self.create_btc_data(
            trend_1h=0.5,
            trend_4h=1.0,
            trend_24h=-6.0,  # -6% (below -5% min)
        )

        state = self.filter.check_market_regime(btc_data, None)

        assert state.is_favorable is False
        assert "24h too bearish" in state.reason

    def test_dump_detection(self):
        """Test BTC dump detection"""
        btc_data = self.create_btc_data(
            trend_1h=-6.0,   # -6% = DUMP (threshold -5%)
            trend_4h=0.0,
            trend_24h=0.0,
        )

        state = self.filter.check_market_regime(btc_data, None)

        assert state.is_favorable is False
        assert state.in_dump_cooldown is True
        assert state.cooldown_remaining_minutes == 60
        assert "post-dump cooldown" in state.reason

    def test_dump_cooldown_expires(self):
        """Test that dump cooldown expires after configured time"""
        # First, trigger a dump
        btc_data_dump = self.create_btc_data(trend_1h=-6.0, trend_4h=0.0, trend_24h=0.0)
        self.filter.check_market_regime(btc_data_dump, None)

        # Manually set dump time to 61 minutes ago
        self.filter.last_dump_time = datetime.now() - timedelta(minutes=61)

        # Now check with normal BTC data
        btc_data_ok = self.create_btc_data(trend_1h=1.0, trend_4h=1.0, trend_24h=2.0)
        state = self.filter.check_market_regime(btc_data_ok, None)

        assert state.is_favorable is True
        assert state.in_dump_cooldown is False

    def test_recovery_cancels_cooldown(self):
        """Test that strong recovery cancels dump cooldown"""
        # First, trigger a dump
        btc_data_dump = self.create_btc_data(trend_1h=-6.0, trend_4h=0.0, trend_24h=0.0)
        self.filter.check_market_regime(btc_data_dump, None)

        # Now simulate recovery (BTC +2.5% in 1h)
        btc_data_recovery = self.create_btc_data(
            trend_1h=2.5,    # Strong recovery
            trend_4h=0.5,
            trend_24h=0.0,
        )
        state = self.filter.check_market_regime(btc_data_recovery, None)

        assert state.is_favorable is True
        assert state.in_dump_cooldown is False

    def test_altcoin_breadth_calculation(self):
        """Test altcoin breadth calculation"""
        btc_data = self.create_btc_data(trend_1h=1.0, trend_4h=1.0, trend_24h=2.0)

        # 3 out of 5 coins bullish (60%)
        altcoin_trends = {
            "ETH-EUR": 1.5,   # Bullish
            "SOL-EUR": 0.8,   # Bullish
            "BNB-EUR": 0.3,   # Not bullish (< 0.5%)
            "AVAX-EUR": -0.5,  # Bearish
            "LINK-EUR": 0.6,  # Bullish
        }

        state = self.filter.check_market_regime(btc_data, altcoin_trends)

        assert state.is_favorable is True  # 60% > 30% min
        assert state.altcoin_breadth == 0.6

    def test_low_altcoin_breadth(self):
        """Test rejection when altcoin breadth is too low"""
        btc_data = self.create_btc_data(trend_1h=1.0, trend_4h=1.0, trend_24h=2.0)

        # Only 1 out of 5 coins bullish (20%)
        altcoin_trends = {
            "ETH-EUR": 0.6,   # Bullish
            "SOL-EUR": 0.2,   # Not bullish
            "BNB-EUR": -0.5,  # Bearish
            "AVAX-EUR": -1.0,  # Bearish
            "LINK-EUR": 0.1,  # Not bullish
        }

        state = self.filter.check_market_regime(btc_data, altcoin_trends)

        assert state.is_favorable is False  # 20% < 30% min
        assert "Low altcoin breadth" in state.reason

    def test_edge_case_exact_thresholds(self):
        """Test edge case with exact threshold values"""
        btc_data = self.create_btc_data(
            trend_1h=-2.0,   # Exactly at min threshold
            trend_4h=0.0,    # Exactly at min threshold
            trend_24h=-5.0,  # Exactly at min threshold
        )

        state = self.filter.check_market_regime(btc_data, None)

        # Should be favorable (>= check, not >)
        assert state.is_favorable is True

    def test_reset_cooldown(self):
        """Test manual cooldown reset"""
        # Trigger dump
        btc_data = self.create_btc_data(trend_1h=-6.0, trend_4h=0.0, trend_24h=0.0)
        self.filter.check_market_regime(btc_data, None)

        # Reset cooldown manually
        self.filter.reset_cooldown()

        # Check that cooldown is cleared
        btc_data_ok = self.create_btc_data(trend_1h=1.0, trend_4h=1.0, trend_24h=2.0)
        state = self.filter.check_market_regime(btc_data_ok, None)

        assert state.in_dump_cooldown is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
