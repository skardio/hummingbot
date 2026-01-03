"""
Unit tests for Parabolic Detector + Cooldown Blacklist

Part of EPIC v3.4: Momentum Health Guards
Story 3: Parabolic Detector with per-symbol cooldown

Tests:
- Parabolic Blacklist operations
- Parabolic Detector configuration
- Parabolic detection logic (3-condition trigger)
- Cooldown tracking and expiry
- Shadow vs Live mode behavior
- Integration with SmartEntryFilter
"""

import time
from decimal import Decimal

from multi_coin_grid_pro.filters.parabolic_blacklist import ParabolicBlacklist
from multi_coin_grid_pro.filters.smart_entry_filter import CandleIndicators, SmartEntryConfig, SmartEntryFilter


class TestParabolicBlacklist:
    """Test parabolic blacklist data structure"""

    def test_add_and_check_blocked(self):
        """Test adding symbol to blacklist and checking block status"""
        blacklist = ParabolicBlacklist()

        # Initially not blocked
        is_blocked, remaining = blacklist.is_blocked("PEPE-EUR")
        assert is_blocked is False
        assert remaining is None

        # Add with 10 second cooldown
        blacklist.add("PEPE-EUR", cooldown_sec=10)

        # Now blocked
        is_blocked, remaining = blacklist.is_blocked("PEPE-EUR")
        assert is_blocked is True
        assert remaining is not None
        assert 8 <= remaining <= 10  # Should be close to 10 seconds

    def test_cooldown_expiry(self):
        """Test that cooldown expires after duration"""
        blacklist = ParabolicBlacklist()

        # Add with 1 second cooldown
        blacklist.add("ETH-EUR", cooldown_sec=1)

        # Initially blocked
        is_blocked, remaining = blacklist.is_blocked("ETH-EUR")
        assert is_blocked is True

        # Wait for expiry
        time.sleep(1.1)

        # No longer blocked
        is_blocked, remaining = blacklist.is_blocked("ETH-EUR")
        assert is_blocked is False
        assert remaining is None

    def test_multiple_symbols(self):
        """Test tracking multiple symbols independently"""
        blacklist = ParabolicBlacklist()

        blacklist.add("PEPE-EUR", cooldown_sec=10)
        blacklist.add("WIF-EUR", cooldown_sec=15)

        # PEPE blocked
        is_blocked, _ = blacklist.is_blocked("PEPE-EUR")
        assert is_blocked is True

        # WIF blocked
        is_blocked, _ = blacklist.is_blocked("WIF-EUR")
        assert is_blocked is True

        # SUI not blocked
        is_blocked, _ = blacklist.is_blocked("SUI-EUR")
        assert is_blocked is False

    def test_get_all_blocked(self):
        """Test getting all blocked symbols"""
        blacklist = ParabolicBlacklist()

        blacklist.add("PEPE-EUR", cooldown_sec=10)
        blacklist.add("WIF-EUR", cooldown_sec=5)

        blocked = blacklist.get_all_blocked()
        assert len(blocked) == 2
        assert "PEPE-EUR" in blocked
        assert "WIF-EUR" in blocked
        assert blocked["PEPE-EUR"] <= 10
        assert blocked["WIF-EUR"] <= 5

    def test_clear(self):
        """Test clearing all entries"""
        blacklist = ParabolicBlacklist()

        blacklist.add("PEPE-EUR", cooldown_sec=10)
        blacklist.add("WIF-EUR", cooldown_sec=10)

        # Clear all
        blacklist.clear()

        # Nothing blocked
        is_blocked, _ = blacklist.is_blocked("PEPE-EUR")
        assert is_blocked is False
        is_blocked, _ = blacklist.is_blocked("WIF-EUR")
        assert is_blocked is False


class TestParabolicDetectorConfig:
    """Test parabolic detector configuration"""

    def test_default_config_detector_disabled(self):
        """Test that detector is disabled by default"""
        config = SmartEntryConfig()
        assert config.parabolic_detector_enabled is False
        assert config.parabolic_detector_mode == "shadow"

    def test_custom_config_with_detector_enabled(self):
        """Test custom configuration with detector enabled"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_accel_5m_min_pct = 3.0
        config.parabolic_accel_15m_min_pct = 7.0
        config.parabolic_vwap_dev_min_pct = 20.0
        config.parabolic_cooldown_minutes = 900 // 60  # convert seconds to minutes  # 15 minutes

        assert config.parabolic_detector_enabled is True
        assert config.parabolic_detector_mode == "live"
        assert config.parabolic_accel_5m_min_pct == 3.0
        assert config.parabolic_accel_15m_min_pct == 7.0
        assert config.parabolic_vwap_dev_min_pct == 20.0
        assert config.parabolic_cooldown_sec == 900


class TestParabolicDetectorLogic:
    """Test parabolic detector core logic"""

    def test_detector_disabled_passes_all(self):
        """Test that detector passes everything when disabled"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = False

        filter_obj = SmartEntryFilter(config=config)

        # Extreme parabolic conditions but detector disabled
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="PEPE-EUR",
            vwap_dev_pct=50.0,  # Extreme deviation
            accel_5m_pct=10.0,  # Extreme 5m
            accel_15m_pct=20.0,  # Extreme 15m
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_single_condition_met_passes(self):
        """Test that detector passes if only one condition met"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Only deviation meets threshold
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="ETH-EUR",
            vwap_dev_pct=20.0,  # Meets threshold
            accel_5m_pct=1.0,   # Below threshold
            accel_15m_pct=3.0,  # Below threshold
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_two_conditions_met_passes(self):
        """Test that detector passes if only two conditions met"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Deviation and accel_5m meet threshold, but accel_15m doesn't
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="WIF-EUR",
            vwap_dev_pct=20.0,  # Meets
            accel_5m_pct=3.0,   # Meets
            accel_15m_pct=4.0,  # Below threshold
            regime="BULL"
        )

        assert allowed is True
        assert reason is None

    def test_all_three_conditions_met_shadow_mode(self):
        """Test that all three conditions in shadow mode logs but passes"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = True  # shadow mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # All three conditions met
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="PEPE-EUR",
            vwap_dev_pct=25.0,  # Meets
            accel_5m_pct=4.0,   # Meets
            accel_15m_pct=8.0,  # Meets
            regime="BULL"
        )

        # Shadow mode: passes but cooldown still added to blacklist
        assert allowed is True
        assert reason is None

        # Cooldown should be added to blacklist
        is_blocked, remaining = filter_obj.parabolic_blacklist.is_blocked("PEPE-EUR")
        assert is_blocked is True
        assert remaining is not None

    def test_all_three_conditions_met_live_mode(self):
        """Test that all three conditions in live mode rejects"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_cooldown_minutes = 1800 // 60  # convert seconds to minutes
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # All three conditions met
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="WIF-EUR",
            vwap_dev_pct=30.0,  # Meets
            accel_5m_pct=5.0,   # Meets
            accel_15m_pct=10.0,  # Meets
            regime="BULL"
        )

        # Live mode: rejects
        assert allowed is False
        assert reason is not None
        assert "PARABOLIC_DETECTED" in reason
        assert "30.0%" in reason  # deviation
        assert "5.00%" in reason  # accel_5m
        assert "10.00%" in reason  # accel_15m

    def test_missing_acceleration_data_passes(self):
        """Test that missing acceleration data allows entry"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Missing accel_5m
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="ETH-EUR",
            vwap_dev_pct=25.0,
            accel_5m_pct=None,
            accel_15m_pct=8.0,
            regime="BULL"
        )
        assert allowed is True
        assert reason is None

        # Missing accel_15m
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="ETH-EUR",
            vwap_dev_pct=25.0,
            accel_5m_pct=4.0,
            accel_15m_pct=None,
            regime="BULL"
        )
        assert allowed is True
        assert reason is None

    def test_cooldown_prevents_subsequent_entries_live(self):
        """Test that cooldown blocks subsequent entries in live mode"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_cooldown_minutes = 1  # 1 minute cooldown
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # First detection triggers cooldown
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="PEPE-EUR",
            vwap_dev_pct=25.0,
            accel_5m_pct=4.0,
            accel_15m_pct=8.0,
            regime="BULL"
        )
        assert allowed is False  # Rejected due to detection

        # Second attempt immediately after - blocked by cooldown
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="PEPE-EUR",
            vwap_dev_pct=10.0,  # Even with normal conditions
            accel_5m_pct=1.0,
            accel_15m_pct=2.0,
            regime="BULL"
        )
        assert allowed is False  # Rejected due to cooldown
        assert "PARABOLIC_COOLDOWN_ACTIVE" in reason

    def test_cooldown_expires_after_duration(self):
        """Test that cooldown allows entry after expiry"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_cooldown_minutes = 1 // 60  # convert seconds to minutes  # 1 second for fast test
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Trigger cooldown
        filter_obj.check_parabolic_detector(
            symbol="ETH-EUR",
            vwap_dev_pct=25.0,
            accel_5m_pct=4.0,
            accel_15m_pct=8.0,
            regime="BULL"
        )

        # Wait for cooldown to expire
        time.sleep(1.1)

        # Should now allow entry
        allowed, reason = filter_obj.check_parabolic_detector(
            symbol="ETH-EUR",
            vwap_dev_pct=10.0,
            accel_5m_pct=1.0,
            accel_15m_pct=2.0,
            regime="BULL"
        )
        assert allowed is True
        assert reason is None


class TestParabolicDetectorIntegration:
    """Test integration with SmartEntryFilter allows_entry"""

    def test_integration_detector_disabled(self):
        """Test that allows_entry works with detector disabled"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = False

        filter_obj = SmartEntryFilter(config=config)

        indicators = CandleIndicators(
            price=Decimal("125.0"),
            vwap=Decimal("100.0"),
            rsi_14=55.0,
            atr_pct=2.5,
            wick_ratio=0.35,
            change_5m_pct=1.0,
            trend_1h_pct=5.0,
            trend_4h_pct=4.0,
            trend_24h_pct=6.0
        )

        # Parabolic conditions but detector disabled
        allowed, reason = filter_obj.allows_entry(
            symbol="ETH-EUR",
            ind=indicators,
            accel_5m_pct=5.0,
            accel_15m_pct=10.0
        )

        # Should fail on VWAP deviation check (25% > 3% default)
        assert allowed is False
        assert "VWAP dev" in reason

    def test_integration_detector_enabled_shadow_passes(self):
        """Test that allows_entry passes in shadow mode even with parabolic"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = True  # shadow mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.vwap_max_deviation_pct = 50.0  # Allow high deviation
        config.rsi_buy_max = 100.0  # Don't block on RSI
        config.max_trend_24h_pct = 50.0  # Allow high trend
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        indicators = CandleIndicators(
            price=Decimal("125.0"),
            vwap=Decimal("100.0"),
            rsi_14=55.0,
            atr_pct=2.5,
            wick_ratio=0.35,
            change_5m_pct=1.0,
            trend_1h_pct=5.0,
            trend_4h_pct=4.0,
            trend_24h_pct=6.0
        )

        # Parabolic conditions met
        allowed, reason = filter_obj.allows_entry(
            symbol="ETH-EUR",
            ind=indicators,
            accel_5m_pct=5.0,   # Meets threshold
            accel_15m_pct=10.0,  # Meets threshold
            regime="BULL"
        )

        # Shadow mode: entry allowed
        assert allowed is True

    def test_integration_detector_enabled_live_rejects(self):
        """Test that allows_entry rejects in live mode with parabolic"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.vwap_max_deviation_pct = 50.0
        config.rsi_buy_max = 100.0
        config.max_trend_24h_pct = 50.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        indicators = CandleIndicators(
            price=Decimal("125.0"),
            vwap=Decimal("100.0"),
            rsi_14=55.0,
            atr_pct=2.5,
            wick_ratio=0.35,
            change_5m_pct=1.0,
            trend_1h_pct=5.0,
            trend_4h_pct=4.0,
            trend_24h_pct=6.0
        )

        # Parabolic conditions met
        allowed, reason = filter_obj.allows_entry(
            symbol="WIF-EUR",
            ind=indicators,
            accel_5m_pct=5.0,
            accel_15m_pct=10.0,
            regime="BULL"
        )

        # Live mode: entry rejected
        assert allowed is False
        assert "PARABOLIC_DETECTED" in reason

    def test_integration_cooldown_blocks_entry(self):
        """Test that cooldown blocks subsequent entries"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_cooldown_minutes = 1  # 1 minute cooldown
        config.vwap_max_deviation_pct = 50.0
        config.rsi_buy_max = 100.0
        config.max_trend_24h_pct = 50.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        indicators_parabolic = CandleIndicators(
            price=Decimal("125.0"),
            vwap=Decimal("100.0"),
            rsi_14=55.0,
            atr_pct=2.5,
            wick_ratio=0.35,
            change_5m_pct=1.0,
            trend_1h_pct=5.0,
            trend_4h_pct=4.0,
            trend_24h_pct=6.0
        )

        # First entry triggers parabolic detector
        allowed, reason = filter_obj.allows_entry(
            symbol="PEPE-EUR",
            ind=indicators_parabolic,
            accel_5m_pct=5.0,
            accel_15m_pct=10.0,
            regime="BULL"
        )
        assert allowed is False
        assert "PARABOLIC_DETECTED" in reason

        # Second entry with normal conditions - blocked by cooldown
        indicators_normal = CandleIndicators(
            price=Decimal("102.0"),
            vwap=Decimal("100.0"),
            rsi_14=50.0,
            atr_pct=2.0,
            wick_ratio=0.40,
            change_5m_pct=0.5,
            trend_1h_pct=2.0,
            trend_4h_pct=1.5,
            trend_24h_pct=3.0
        )

        allowed, reason = filter_obj.allows_entry(
            symbol="PEPE-EUR",
            ind=indicators_normal,
            accel_5m_pct=1.0,
            accel_15m_pct=2.0,
            regime="BULL"
        )
        assert allowed is False
        assert "PARABOLIC_COOLDOWN_ACTIVE" in reason


class TestRealWorldScenarios:
    """Test with real-world market scenarios"""

    def test_pepe_parabolic_blow_off(self):
        """Test PEPE parabolic blow-off top scenario"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.parabolic_cooldown_minutes = 1800 // 60  # convert seconds to minutes
        config.vwap_max_deviation_pct = 50.0
        config.rsi_buy_max = 100.0
        config.max_trend_24h_pct = 100.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # PEPE +45% day, extreme momentum
        indicators = CandleIndicators(
            price=Decimal("0.00001850"),
            vwap=Decimal("0.00001500"),  # 23% above VWAP
            rsi_14=82.0,
            atr_pct=8.5,
            wick_ratio=0.15,  # Very low wicks, straight up
            change_5m_pct=1.8,
            trend_1h_pct=12.0,
            trend_4h_pct=22.0,
            trend_24h_pct=45.0
        )

        allowed, reason = filter_obj.allows_entry(
            symbol="PEPE-EUR",
            ind=indicators,
            accel_5m_pct=4.5,   # Extreme 5m acceleration
            accel_15m_pct=9.0,  # Extreme 15m acceleration
            regime="BULL"
        )

        # Should reject due to parabolic detector
        assert allowed is False
        assert "PARABOLIC_DETECTED" in reason or "RSI" in reason or "ATR" in reason

    def test_healthy_bull_market_passes(self):
        """Test that healthy bull market still passes"""
        config = SmartEntryConfig()
        config.parabolic_detector_enabled = True
        config.parabolic_detector_shadow_mode = False  # live mode
        config.parabolic_vwap_dev_min_pct = 18.0
        config.parabolic_accel_5m_min_pct = 2.5
        config.parabolic_accel_15m_min_pct = 6.0
        config.vwap_max_deviation_pct = 50.0
        config.rsi_buy_max = 100.0
        config.rsi_block_min = 100.0
        config.max_atr_pct_for_grid = 10.0
        config.max_trend_24h_pct = 50.0
        config.parabolic_log_details = False

        filter_obj = SmartEntryFilter(config=config)

        # Healthy bull: moderate deviation, healthy momentum
        indicators = CandleIndicators(
            price=Decimal("110.0"),
            vwap=Decimal("100.0"),  # 10% above VWAP (below threshold)
            rsi_14=58.0,
            atr_pct=3.0,
            wick_ratio=0.35,
            change_5m_pct=0.6,
            trend_1h_pct=4.0,
            trend_4h_pct=3.5,
            trend_24h_pct=8.0
        )

        allowed, reason = filter_obj.allows_entry(
            symbol="ETH-EUR",
            ind=indicators,
            accel_5m_pct=1.5,  # Healthy but not extreme
            accel_15m_pct=3.0,  # Healthy but not extreme
            regime="BULL"
        )

        # Should pass - not parabolic
        assert allowed is True
