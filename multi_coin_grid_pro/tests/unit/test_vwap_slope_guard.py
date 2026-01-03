"""
Unit tests for VWAP Slope Guard (Story 2 - EPIC v3.4).

Tests guard logic, shadow/live modes, and threshold-based rejection.
"""

from decimal import Decimal

import pytest

from multi_coin_grid_pro.filters.smart_entry_filter import CandleIndicators, SmartEntryConfig, SmartEntryFilter


class TestVwapSlopeGuardConfig:
    """Test VWAP slope guard configuration."""

    def test_default_config_guard_disabled(self):
        """Test that VWAP slope guard is disabled by default."""
        config = SmartEntryConfig()
        assert config.vwap_slope_guard_enabled is False
        assert config.vwap_slope_guard_mode == "shadow"

    def test_custom_config_with_guard_enabled(self):
        """Test enabling VWAP slope guard with custom thresholds."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.vwap_slope_deviation_high_pct = 18.0
        config.vwap_slope_min_pct_15m = 0.05

        assert config.vwap_slope_guard_enabled is True
        assert config.vwap_slope_guard_mode == "live"
        assert config.vwap_slope_deviation_high_pct == 18.0
        assert config.vwap_slope_min_pct_15m == 0.05


class TestVwapSlopeGuardLogic:
    """Test VWAP slope guard core logic."""

    @pytest.fixture
    def guard_config(self):
        """Create config with VWAP slope guard enabled in shadow mode."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = True  # shadow mode
        config.vwap_slope_deviation_high_pct = 15.0
        config.vwap_slope_min_pct_15m = 0.10
        config.vwap_slope_log_details = False  # Quiet tests
        return config

    @pytest.fixture
    def smart_filter(self, guard_config):
        """Create SmartEntryFilter with guard enabled."""
        return SmartEntryFilter(config=guard_config)

    def test_guard_disabled_passes_all(self):
        """Test that disabled guard allows everything."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = False
        filter_obj = SmartEntryFilter(config=config)

        # Should pass even with extreme values
        allowed, reason = filter_obj.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=25.0,  # High deviation
            vwap_slope_5m_pct=0.01,  # Flat slope
            vwap_slope_15m_pct=0.01,  # Flat slope
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_negative_deviation_always_passes(self, smart_filter):
        """Test that price below VWAP always passes."""
        allowed, reason = smart_filter.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=-5.0,  # Price below VWAP
            vwap_slope_5m_pct=0.01,  # Doesn't matter
            vwap_slope_15m_pct=0.01,  # Doesn't matter
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_low_deviation_passes(self, smart_filter):
        """Test that low deviation passes (not far from VWAP)."""
        allowed, reason = smart_filter.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=10.0,  # Below threshold (15%)
            vwap_slope_5m_pct=0.01,  # Flat slope (doesn't trigger)
            vwap_slope_15m_pct=0.01,  # Flat slope (doesn't trigger)
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_high_deviation_healthy_slope_passes(self, smart_filter):
        """Test that high deviation + healthy slope passes."""
        allowed, reason = smart_filter.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=20.0,  # Above threshold
            vwap_slope_5m_pct=0.30,  # Healthy rising slope
            vwap_slope_15m_pct=0.25,  # Healthy rising slope
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_blow_off_top_detected_shadow_mode(self, smart_filter):
        """Test blow-off detection in shadow mode (logs but allows)."""
        # Shadow mode should log but NOT reject
        allowed, reason = smart_filter.check_vwap_slope_guard(
            symbol="PEPE-EUR",
            vwap_dev_pct=19.2,  # High deviation
            vwap_slope_5m_pct=0.02,  # Flat slope
            vwap_slope_15m_pct=0.03,  # Flat slope
            regime="BULL"
        )

        # Shadow mode: allows entry but logs warning
        assert allowed is True
        assert reason is None

    def test_blow_off_top_detected_live_mode(self):
        """Test blow-off detection in live mode (rejects)."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode  # LIVE MODE
        config.vwap_slope_deviation_high_pct = 15.0
        config.vwap_slope_min_pct_15m = 0.10
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        allowed, reason = filter_obj.check_vwap_slope_guard(
            symbol="PEPE-EUR",
            vwap_dev_pct=19.2,  # High deviation
            vwap_slope_5m_pct=0.02,  # Flat slope
            vwap_slope_15m_pct=0.03,  # Flat slope
            regime="BULL"
        )

        # Live mode: rejects entry
        assert allowed is False
        assert reason is not None
        assert "VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH" in reason
        assert "19.2%" in reason
        assert "0.02%" in reason or "0.03%" in reason

    def test_missing_slope_data_passes(self, smart_filter):
        """Test that missing slope data doesn't reject."""
        allowed, reason = smart_filter.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=20.0,  # High deviation
            vwap_slope_5m_pct=None,  # No slope data
            vwap_slope_15m_pct=None,  # No slope data
            regime="BULL"
        )

        # Should pass - can't reject without data
        assert allowed is True
        assert reason is None

    def test_boundary_case_exactly_at_thresholds(self):
        """Test boundary cases at exact threshold values."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.vwap_slope_dual_confirmation = True  # Story 9: dual-window
        config.vwap_slope_deviation_high_pct = 15.0
        config.vwap_slope_min_pct_5m = 0.10  # Story 9: Add 5m threshold
        config.vwap_slope_min_pct_15m = 0.10
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Exactly at deviation threshold, exactly at slope threshold
        allowed, reason = filter_obj.check_vwap_slope_guard(
            symbol="TEST-EUR",
            vwap_dev_pct=15.0,  # Exactly at threshold
            vwap_slope_5m_pct=0.10,  # Exactly at threshold
            vwap_slope_15m_pct=0.10,  # Exactly at threshold
            regime="BULL"
        )

        # Should reject (both slopes <= threshold)
        assert allowed is False
        assert "VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH" in reason


class TestVwapSlopeGuardIntegration:
    """Test VWAP slope guard integration with SmartEntryFilter.allows_entry()."""

    @pytest.fixture
    def sample_indicators(self):
        """Create sample candle indicators."""
        return CandleIndicators(
            price=Decimal("110.0"),
            vwap=Decimal("100.0"),  # 10% deviation
            rsi_14=55.0,
            atr_pct=2.5,
            wick_ratio=0.35,
            change_5m_pct=0.5,
            trend_1h_pct=3.0,
            trend_4h_pct=2.5,
            trend_24h_pct=5.0
        )

    def test_integration_guard_disabled(self, sample_indicators):
        """Test allows_entry with guard disabled."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = False
        config.vwap_max_deviation_pct = 20.0  # Allow high deviation

        filter_obj = SmartEntryFilter(config=config)

        allowed, reason = filter_obj.allows_entry(
            symbol="TEST-EUR",
            ind=sample_indicators,
            vwap_slope_5m_pct=0.01,  # Flat slope (ignored)
            vwap_slope_15m_pct=0.01,  # Flat slope (ignored)
            regime="BULL"
        )

        # Should pass other checks and ignore slope guard
        assert allowed is True

    def test_integration_guard_enabled_shadow_passes(self, sample_indicators):
        """Test allows_entry with guard enabled in shadow mode."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = True  # shadow mode
        config.vwap_slope_deviation_high_pct = 8.0  # Lower threshold for testing
        config.vwap_slope_min_pct_15m = 0.10
        config.vwap_max_deviation_pct = 20.0
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # High deviation + flat slope should log but pass in shadow
        allowed, reason = filter_obj.allows_entry(
            symbol="TEST-EUR",
            ind=sample_indicators,  # 10% deviation
            vwap_slope_5m_pct=0.02,  # Flat slope
            vwap_slope_15m_pct=0.02,  # Flat slope
            regime="BULL"
        )

        assert allowed is True

    def test_integration_guard_enabled_live_rejects(self, sample_indicators):
        """Test allows_entry with guard enabled in live mode."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.vwap_slope_deviation_high_pct = 8.0  # Lower for testing
        config.vwap_slope_min_pct_15m = 0.10
        config.vwap_max_deviation_pct = 20.0
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # High deviation + flat slope should reject
        allowed, reason = filter_obj.allows_entry(
            symbol="TEST-EUR",
            ind=sample_indicators,  # 10% deviation
            vwap_slope_5m_pct=0.02,  # Flat slope
            vwap_slope_15m_pct=0.02,  # Flat slope
            regime="BULL"
        )

        assert allowed is False
        assert "VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH" in reason

    def test_integration_other_checks_still_work(self, sample_indicators):
        """Test that other SmartEntry checks still work with guard enabled."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.rsi_block_min = 50.0  # Set low to trigger RSI block
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Should fail RSI check before slope guard
        allowed, reason = filter_obj.allows_entry(
            symbol="TEST-EUR",
            ind=sample_indicators,  # RSI=55 > block_min=50
            vwap_slope_5m_pct=0.15,  # Healthy slope
            vwap_slope_15m_pct=0.15,  # Healthy slope
            regime="BULL"
        )

        assert allowed is False
        assert "RSI too high" in reason


class TestRealWorldScenarios:
    """Test real-world scenarios from EPIC description."""

    def test_pepe_blow_off_top_scenario(self):
        """
        Test PEPE blow-off scenario from EPIC:
        Price +43% but VWAP slope flattening.
        """
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.vwap_slope_deviation_high_pct = 18.0  # BULL regime
        config.vwap_slope_min_pct_15m = 0.05  # BULL regime
        config.vwap_max_deviation_pct = 50.0  # Allow extreme deviation
        config.rsi_block_min = 100.0  # Don't block on RSI
        config.rsi_buy_max = 100.0  # Don't block on RSI buy_max
        config.max_atr_pct_for_grid = 15.0  # Allow high volatility
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # PEPE scenario: +43% above some baseline, ~19% above VWAP
        indicators = CandleIndicators(
            price=Decimal("119.0"),
            vwap=Decimal("100.0"),  # 19% deviation
            rsi_14=65.0,  # Not extreme
            atr_pct=8.0,  # High but not blocking
            wick_ratio=0.15,  # Low but RSI allows it
            change_5m_pct=1.5,
            trend_1h_pct=15.0,
            trend_4h_pct=12.0,
            trend_24h_pct=43.0
        )

        allowed, reason = filter_obj.allows_entry(
            symbol="PEPE-EUR",
            ind=indicators,
            vwap_slope_5m_pct=0.02,  # Flat slope!
            vwap_slope_15m_pct=0.03,  # Flat slope!
            regime="BULL"
        )

        # Should REJECT: High deviation + flat slope = blow-off top
        assert allowed is False
        assert "VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH" in reason

    def test_healthy_bull_trend_passes(self):
        """Test that healthy bull trends still pass."""
        config = SmartEntryConfig()
        config.vwap_slope_guard_enabled = True
        config.vwap_slope_guard_shadow_mode = False  # live mode
        config.vwap_slope_deviation_high_pct = 18.0
        config.vwap_slope_min_pct_15m = 0.05
        config.vwap_max_deviation_pct = 50.0
        config.rsi_block_min = 100.0
        config.rsi_buy_max = 100.0  # Don't block on RSI
        config.max_atr_pct_for_grid = 15.0  # Allow higher ATR
        config.max_trend_24h_pct = 50.0  # Allow high 24h trend
        config.vwap_slope_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Healthy bull: high deviation BUT slope still rising
        indicators = CandleIndicators(
            price=Decimal("120.0"),
            vwap=Decimal("100.0"),  # 20% deviation
            rsi_14=58.0,
            atr_pct=3.5,
            wick_ratio=0.30,
            change_5m_pct=0.8,
            trend_1h_pct=8.0,
            trend_4h_pct=7.0,
            trend_24h_pct=15.0
        )

        allowed, reason = filter_obj.allows_entry(
            symbol="ETH-EUR",
            ind=indicators,
            vwap_slope_5m_pct=0.30,  # Healthy rising slope
            vwap_slope_15m_pct=0.25,  # Healthy rising slope
            regime="BULL"
        )

        # Should PASS: Deviation high but momentum still healthy
        if not allowed:
            print(f"Rejection reason: {reason}")
        assert allowed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
