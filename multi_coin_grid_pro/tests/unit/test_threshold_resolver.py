"""
Unit tests for Threshold Resolver

Part of EPIC v3.4: Momentum Health Guards
Story 5: Regime-aware threshold resolution with safety floors

Tests:
- Precedence order (coin_profile > regime > baseline)
- Safety floor enforcement
- Validation on init
- Multiple threshold resolution
- Helper functions
"""

from multi_coin_grid_pro.filters.threshold_resolver import SAFETY_FLOORS, ThresholdResolver, create_regime_config_dict


class TestThresholdPrecedence:
    """Test precedence order: coin_profile > regime > baseline"""

    def test_baseline_only(self):
        """Test baseline fallback when no overrides"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5
        }

        resolver = ThresholdResolver(config=config)
        value = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct", regime="NEUTRAL")

        assert value == 2.5

    def test_regime_overrides_baseline(self):
        """Test regime-specific threshold overrides baseline"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_5m_min_pct__BULL": 3.0
        }

        resolver = ThresholdResolver(config=config)

        # BULL regime uses override
        value_bull = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct", regime="BULL")
        assert value_bull == 3.0

        # NEUTRAL regime uses baseline
        value_neutral = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct", regime="NEUTRAL")
        assert value_neutral == 2.5

    def test_coin_profile_overrides_regime(self):
        """Test coin profile overrides regime and baseline"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_5m_min_pct__BULL": 3.0
        }

        coin_profiles = {
            "PEPE-EUR": {
                "parabolic_accel_5m_min_pct": 5.0  # Higher for meme coin
            }
        }

        resolver = ThresholdResolver(config=config, coin_profiles=coin_profiles)

        # PEPE uses coin profile (even in BULL regime)
        value_pepe = resolver.resolve("PEPE-EUR", "parabolic_accel_5m_min_pct", regime="BULL")
        assert value_pepe == 5.0

        # ETH uses regime override
        value_eth = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct", regime="BULL")
        assert value_eth == 3.0

    def test_precedence_all_three_levels(self):
        """Test all three precedence levels"""
        config = {
            "parabolic_vwap_dev_min_pct": 18.0,
            "parabolic_vwap_dev_min_pct__BULL": 22.0,
            "parabolic_vwap_dev_min_pct__CHOP": 14.0
        }

        coin_profiles = {
            "PEPE-EUR": {"parabolic_vwap_dev_min_pct": 25.0},
            "SUI-EUR": {}  # No override, uses regime
        }

        resolver = ThresholdResolver(config=config, coin_profiles=coin_profiles)

        # PEPE: coin profile (highest precedence)
        assert resolver.resolve("PEPE-EUR", "parabolic_vwap_dev_min_pct", "BULL") == 25.0

        # SUI in BULL: regime override
        assert resolver.resolve("SUI-EUR", "parabolic_vwap_dev_min_pct", "BULL") == 22.0

        # SUI in CHOP: regime override
        assert resolver.resolve("SUI-EUR", "parabolic_vwap_dev_min_pct", "CHOP") == 14.0

        # ETH (not in profiles) in NEUTRAL: baseline
        assert resolver.resolve("ETH-EUR", "parabolic_vwap_dev_min_pct", "NEUTRAL") == 18.0


class TestSafetyFloors:
    """Test safety floor enforcement"""

    def test_safety_floor_enforced_on_coin_profile(self):
        """Test that coin profile cannot violate safety floor"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5
        }

        coin_profiles = {
            "PEPE-EUR": {
                "parabolic_accel_5m_min_pct": 0.5  # Below floor of 1.0
            }
        }

        resolver = ThresholdResolver(config=config, coin_profiles=coin_profiles, validate_on_init=False)

        # Should enforce floor of 1.0
        value = resolver.resolve("PEPE-EUR", "parabolic_accel_5m_min_pct")
        assert value == SAFETY_FLOORS["parabolic_accel_5m_min_pct"]
        assert value == 1.0

    def test_safety_floor_enforced_on_regime(self):
        """Test that regime override cannot violate safety floor"""
        config = {
            "vwap_slope_min_pct_15m": 0.10,
            "vwap_slope_min_pct_15m__BULL": 0.005  # Below floor of 0.01
        }

        resolver = ThresholdResolver(config=config)

        # Should enforce floor of 0.01
        value = resolver.resolve("ETH-EUR", "vwap_slope_min_pct_15m", regime="BULL")
        assert value == SAFETY_FLOORS["vwap_slope_min_pct_15m"]
        assert value == 0.01

    def test_safety_floor_enforced_on_baseline(self):
        """Test that even baseline cannot go below floor"""
        config = {
            "parabolic_cooldown_sec": 60  # Below floor of 300
        }

        resolver = ThresholdResolver(config=config)

        # Should enforce floor of 300
        value = resolver.resolve("ETH-EUR", "parabolic_cooldown_sec")
        assert value == SAFETY_FLOORS["parabolic_cooldown_sec"]
        assert value == 300

    def test_value_above_floor_not_modified(self):
        """Test that values above floor are not modified"""
        config = {
            "parabolic_accel_15m_min_pct": 6.0  # Above floor of 3.0
        }

        resolver = ThresholdResolver(config=config)

        # Should keep original value
        value = resolver.resolve("ETH-EUR", "parabolic_accel_15m_min_pct")
        assert value == 6.0

    def test_all_safety_floors_exist(self):
        """Test that all documented safety floors are defined"""
        expected_floors = [
            "vwap_slope_min_pct_15m",
            "parabolic_accel_5m_min_pct",
            "parabolic_accel_15m_min_pct",
            "parabolic_vwap_dev_min_pct",
            "parabolic_cooldown_sec"
        ]

        for key in expected_floors:
            assert key in SAFETY_FLOORS, f"Missing safety floor: {key}"
            assert SAFETY_FLOORS[key] > 0, f"Invalid safety floor for {key}"


class TestValidation:
    """Test validation and error handling"""

    def test_validation_warns_on_floor_violation(self, caplog):
        """Test that validation warns about floor violations"""
        config = {"parabolic_accel_5m_min_pct": 2.5}

        coin_profiles = {
            "PEPE-EUR": {
                "parabolic_accel_5m_min_pct": 0.5  # Below floor
            }
        }

        ThresholdResolver(config=config, coin_profiles=coin_profiles, validate_on_init=True)

        # Should have logged warning
        assert "below safety floor" in caplog.text.lower()
        assert "PEPE-EUR" in caplog.text

    def test_validation_can_be_disabled(self):
        """Test that validation can be disabled on init"""
        config = {"parabolic_accel_5m_min_pct": 2.5}

        coin_profiles = {
            "PEPE-EUR": {
                "parabolic_accel_5m_min_pct": 0.5
            }
        }

        # Should not raise error even with violation
        resolver = ThresholdResolver(config=config, coin_profiles=coin_profiles, validate_on_init=False)

        # But should still enforce at resolution time
        value = resolver.resolve("PEPE-EUR", "parabolic_accel_5m_min_pct")
        assert value == 1.0  # Floor enforced

    def test_missing_key_returns_default(self):
        """Test that missing keys return default value"""
        config = {}

        resolver = ThresholdResolver(config=config)

        # With default
        value = resolver.resolve("ETH-EUR", "missing_key", default=10.0)
        assert value == 10.0

        # Without default
        value = resolver.resolve("ETH-EUR", "missing_key")
        assert value is None


class TestBatchResolution:
    """Test resolving multiple thresholds at once"""

    def test_resolve_dict(self):
        """Test resolving multiple keys in one call"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_15m_min_pct": 6.0,
            "parabolic_vwap_dev_min_pct": 18.0
        }

        resolver = ThresholdResolver(config=config)

        keys = [
            "parabolic_accel_5m_min_pct",
            "parabolic_accel_15m_min_pct",
            "parabolic_vwap_dev_min_pct"
        ]

        result = resolver.resolve_dict("ETH-EUR", keys)

        assert result["parabolic_accel_5m_min_pct"] == 2.5
        assert result["parabolic_accel_15m_min_pct"] == 6.0
        assert result["parabolic_vwap_dev_min_pct"] == 18.0

    def test_resolve_dict_with_regime(self):
        """Test batch resolution with regime overrides"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_5m_min_pct__BULL": 3.0,
            "parabolic_accel_15m_min_pct": 6.0,
            "parabolic_accel_15m_min_pct__BULL": 7.0
        }

        resolver = ThresholdResolver(config=config)

        keys = ["parabolic_accel_5m_min_pct", "parabolic_accel_15m_min_pct"]

        # BULL regime
        result_bull = resolver.resolve_dict("ETH-EUR", keys, regime="BULL")
        assert result_bull["parabolic_accel_5m_min_pct"] == 3.0
        assert result_bull["parabolic_accel_15m_min_pct"] == 7.0

        # NEUTRAL regime
        result_neutral = resolver.resolve_dict("ETH-EUR", keys, regime="NEUTRAL")
        assert result_neutral["parabolic_accel_5m_min_pct"] == 2.5
        assert result_neutral["parabolic_accel_15m_min_pct"] == 6.0


class TestConfigObjectSupport:
    """Test support for both dict and object config"""

    def test_dict_config(self):
        """Test with dict-based config"""
        config = {"parabolic_accel_5m_min_pct": 2.5}

        resolver = ThresholdResolver(config=config)
        value = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct")

        assert value == 2.5

    def test_object_config(self):
        """Test with object-based config (e.g., SmartEntryConfig)"""
        class MockConfig:
            parabolic_accel_5m_min_pct = 2.5

        config = MockConfig()

        resolver = ThresholdResolver(config=config)
        value = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct")

        assert value == 2.5


class TestHelperFunctions:
    """Test helper functions"""

    def test_create_regime_config_dict_baseline_only(self):
        """Test creating config dict with baseline only"""
        config = create_regime_config_dict(
            baseline={"parabolic_accel_5m_min_pct": 2.5}
        )

        assert config["parabolic_accel_5m_min_pct"] == 2.5
        assert len(config) == 1

    def test_create_regime_config_dict_with_regimes(self):
        """Test creating config dict with regime overrides"""
        config = create_regime_config_dict(
            baseline={"parabolic_accel_5m_min_pct": 2.5},
            bull={"parabolic_accel_5m_min_pct": 3.0},
            chop={"parabolic_accel_5m_min_pct": 2.2},
            bear={"parabolic_accel_5m_min_pct": 2.0}
        )

        assert config["parabolic_accel_5m_min_pct"] == 2.5
        assert config["parabolic_accel_5m_min_pct__BULL"] == 3.0
        assert config["parabolic_accel_5m_min_pct__CHOP"] == 2.2
        assert config["parabolic_accel_5m_min_pct__BEAR"] == 2.0

    def test_create_regime_config_dict_multiple_keys(self):
        """Test creating config dict with multiple keys"""
        config = create_regime_config_dict(
            baseline={
                "parabolic_accel_5m_min_pct": 2.5,
                "parabolic_vwap_dev_min_pct": 18.0
            },
            bull={
                "parabolic_accel_5m_min_pct": 3.0,
                "parabolic_vwap_dev_min_pct": 22.0
            }
        )

        assert config["parabolic_accel_5m_min_pct"] == 2.5
        assert config["parabolic_accel_5m_min_pct__BULL"] == 3.0
        assert config["parabolic_vwap_dev_min_pct"] == 18.0
        assert config["parabolic_vwap_dev_min_pct__BULL"] == 22.0

    def test_get_safety_floor(self):
        """Test getting safety floor for a key"""
        resolver = ThresholdResolver(config={})

        floor = resolver.get_safety_floor("parabolic_accel_5m_min_pct")
        assert floor == 1.0

        floor = resolver.get_safety_floor("nonexistent_key")
        assert floor is None

    def test_is_at_safety_floor(self):
        """Test checking if value is at safety floor"""
        resolver = ThresholdResolver(config={})

        # At floor
        assert resolver.is_at_safety_floor("parabolic_accel_5m_min_pct", 1.0) is True

        # Above floor
        assert resolver.is_at_safety_floor("parabolic_accel_5m_min_pct", 2.5) is False

        # Below floor
        assert resolver.is_at_safety_floor("parabolic_accel_5m_min_pct", 0.5) is False

        # No floor defined
        assert resolver.is_at_safety_floor("nonexistent_key", 10.0) is False


class TestRealWorldScenarios:
    """Test with realistic configurations"""

    def test_pepe_meme_coin_profile(self):
        """Test PEPE with aggressive meme coin thresholds"""
        config = {
            "parabolic_accel_5m_min_pct": 2.5,
            "parabolic_accel_5m_min_pct__BULL": 3.0,
            "parabolic_vwap_dev_min_pct": 18.0,
            "parabolic_vwap_dev_min_pct__BULL": 22.0
        }

        coin_profiles = {
            "PEPE-EUR": {
                "parabolic_accel_5m_min_pct": 5.0,  # Higher for memes
                "parabolic_vwap_dev_min_pct": 30.0   # Much higher deviation
            }
        }

        resolver = ThresholdResolver(config=config, coin_profiles=coin_profiles)

        # PEPE uses coin profile (more lenient)
        pepe_accel = resolver.resolve("PEPE-EUR", "parabolic_accel_5m_min_pct", "BULL")
        pepe_dev = resolver.resolve("PEPE-EUR", "parabolic_vwap_dev_min_pct", "BULL")

        assert pepe_accel == 5.0
        assert pepe_dev == 30.0

        # ETH uses regime defaults (more strict)
        eth_accel = resolver.resolve("ETH-EUR", "parabolic_accel_5m_min_pct", "BULL")
        eth_dev = resolver.resolve("ETH-EUR", "parabolic_vwap_dev_min_pct", "BULL")

        assert eth_accel == 3.0
        assert eth_dev == 22.0

    def test_bear_regime_strict_thresholds(self):
        """Test that BEAR regime uses stricter thresholds"""
        config = {
            "vwap_slope_min_pct_15m": 0.10,
            "vwap_slope_min_pct_15m__BULL": 0.05,
            "vwap_slope_min_pct_15m__BEAR": 0.20
        }

        resolver = ThresholdResolver(config=config)

        # BULL is lenient
        bull_threshold = resolver.resolve("ETH-EUR", "vwap_slope_min_pct_15m", "BULL")
        assert bull_threshold == 0.05

        # BEAR is strict
        bear_threshold = resolver.resolve("ETH-EUR", "vwap_slope_min_pct_15m", "BEAR")
        assert bear_threshold == 0.20

        # BEAR threshold is 4x BULL threshold
        assert bear_threshold == bull_threshold * 4
