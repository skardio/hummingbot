"""
EPIC v3.4 Story 6: Controller Integration Tests

Tests that momentum guards are properly integrated into the controller:
- MomentumIndicatorService is instantiated
- Metrics are calculated during candidate evaluation
- Metrics are passed to allows_entry()
- Regime is detected and passed
"""
import pytest


class TestControllerMomentumIntegration:
    """Test momentum service integration in controller"""

    def test_momentum_service_instantiated(self):
        """Test: MomentumIndicatorService is imported and can be instantiated"""
        from multi_coin_grid_pro.indicators.momentum_indicators import MomentumIndicatorService

        # ASSERT: Service can be instantiated with connector_name
        service = MomentumIndicatorService(connector_name="kraken")
        assert service is not None, "MomentumIndicatorService should be instantiated"
        assert service.connector_name == "kraken", "Connector name should be set"

    def test_controller_has_momentum_service_attribute(self):
        """Test: Controller code references momentum_service"""
        import inspect

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # ASSERT: Check __init__ source code contains momentum_service
        source = inspect.getsource(MultiCoinGridController.__init__)
        assert "momentum_service" in source, "Controller __init__ should create momentum_service"
        assert "MomentumIndicatorService" in source, "Controller should import and instantiate MomentumIndicatorService"

    def test_check_smart_entry_v2_calculates_momentum(self):
        """Test: _check_smart_entry_v2 calculates momentum metrics"""
        import inspect

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # ASSERT: Check _check_smart_entry_v2 source code
        source = inspect.getsource(MultiCoinGridController._check_smart_entry_v2)
        assert "momentum_service.calculate_metrics" in source, "Should call calculate_metrics"
        assert "vwap_slope_15m_pct" in source, "Should extract vwap_slope_15m_pct"
        assert "accel_5m_pct" in source, "Should extract accel_5m_pct"
        assert "accel_15m_pct" in source, "Should extract accel_15m_pct"

    def test_allows_entry_receives_momentum_params(self):
        """Test: allows_entry is called with momentum parameters"""
        import inspect

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # ASSERT: Check _check_smart_entry_v2 passes params to allows_entry
        source = inspect.getsource(MultiCoinGridController._check_smart_entry_v2)
        assert "vwap_slope_15m_pct=vwap_slope_15m_pct" in source, "Should pass vwap_slope_15m_pct to allows_entry"
        assert "accel_5m_pct=accel_5m_pct" in source, "Should pass accel_5m_pct to allows_entry"
        assert "accel_15m_pct=accel_15m_pct" in source, "Should pass accel_15m_pct to allows_entry"
        assert "regime=regime" in source, "Should pass regime to allows_entry"

    def test_regime_is_detected_and_cached(self):
        """Test: Regime is detected and cached in _last_detected_regime"""
        import inspect

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # ASSERT: Check control_task caches regime
        source = inspect.getsource(MultiCoinGridController.control_task)
        assert "_last_detected_regime" in source, "Should cache detected regime in _last_detected_regime"

    def test_config_files_have_momentum_guard_config(self):
        """Test: Config files contain momentum guard configuration"""
        import yaml

        # ASSERT: Check spot_grid_kraken_eur.yaml
        with open("/home/mo/repos/hummingbot/multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml") as f:
            config_prod = yaml.safe_load(f)

        assert "vwap_slope_guard_enabled" in config_prod["smart_entry_filter"], "Config should have vwap_slope_guard_enabled"
        assert "parabolic_detector_enabled" in config_prod["smart_entry_filter"], "Config should have parabolic_detector_enabled"
        assert "momentum_thresholds" in config_prod["smart_entry_filter"], "Config should have momentum_thresholds"

        # Check baseline thresholds
        thresholds = config_prod["smart_entry_filter"]["momentum_thresholds"]
        assert "baseline" in thresholds, "Should have baseline thresholds"
        assert "regimes" in thresholds, "Should have regime-specific thresholds"
        assert "BULL" in thresholds["regimes"], "Should have BULL regime thresholds"
        assert "CHOP" in thresholds["regimes"], "Should have CHOP regime thresholds"
        assert "BEAR" in thresholds["regimes"], "Should have BEAR regime thresholds"

        # ASSERT: Check spot_grid_bitget.yaml
        with open("/home/mo/repos/hummingbot/multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml") as f:
            config_bitget = yaml.safe_load(f)

        assert "vwap_slope_guard_enabled" in config_bitget["smart_entry_filter"], "Bitget config should have vwap_slope_guard_enabled"
        assert "parabolic_detector_enabled" in config_bitget["smart_entry_filter"], "Bitget config should have parabolic_detector_enabled"
        assert "momentum_thresholds" in config_bitget["smart_entry_filter"], "Bitget config should have momentum_thresholds"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
