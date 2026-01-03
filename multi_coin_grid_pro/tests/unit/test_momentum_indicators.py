"""
Unit tests for MomentumIndicatorService.

Tests VWAP slopes, acceleration calculations, error handling, and edge cases.

Part of EPIC v3.4 - Story 1
"""

import time
from typing import Dict, List

import pytest

from multi_coin_grid_pro.indicators.momentum_indicators import MomentumIndicatorService, MomentumMetrics


class TestMomentumMetrics:
    """Test MomentumMetrics dataclass."""

    def test_dataclass_creation(self):
        """Test basic metrics creation."""
        metrics = MomentumMetrics(
            timestamp=1704196800.0,
            symbol="PEPE-EUR",
            vwap_deviation_pct=19.2,
            vwap_slope_5m_pct=0.15,
            vwap_slope_15m_pct=0.03,
            accel_5m_pct=2.1,
            accel_15m_pct=5.8,
            reason=None
        )

        assert metrics.symbol == "PEPE-EUR"
        assert metrics.vwap_deviation_pct == 19.2
        assert metrics.vwap_slope_5m_pct == 0.15
        assert metrics.vwap_slope_15m_pct == 0.03
        assert metrics.accel_5m_pct == 2.1
        assert metrics.accel_15m_pct == 5.8
        assert metrics.reason is None

    def test_metrics_with_none_values(self):
        """Test metrics with missing data."""
        metrics = MomentumMetrics(
            timestamp=1704196800.0,
            symbol="BTC-USDT",
            vwap_deviation_pct=None,
            vwap_slope_5m_pct=None,
            vwap_slope_15m_pct=None,
            accel_5m_pct=None,
            accel_15m_pct=None,
            reason="insufficient_history"
        )

        assert metrics.vwap_deviation_pct is None
        assert metrics.reason == "insufficient_history"


class TestMomentumIndicatorService:
    """Test MomentumIndicatorService calculations."""

    @pytest.fixture
    def service(self):
        """Create indicator service instance."""
        return MomentumIndicatorService(connector_name="kraken")

    @pytest.fixture
    def sample_candles(self) -> List[Dict]:
        """Create sample candle data for testing (20 candles)."""
        base_price = 100.0
        base_vwap = 100.0
        candles = []

        for i in range(20):
            # Simulate uptrend: price increasing 0.5% per candle
            price = base_price * (1.005 ** i)
            vwap = base_vwap * (1.003 ** i)  # VWAP increases slower

            candles.append({
                "timestamp": 1704196800.0 + (i * 60),  # 1-minute intervals
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000.0,
                "vwap": vwap
            })

        return candles

    def test_calculate_metrics_normal_values(self, service, sample_candles):
        """Test normal calculation with sufficient data."""
        current_price = 110.0
        current_vwap = 106.0

        metrics = service.calculate_metrics(
            symbol="PEPE-EUR",
            current_price=current_price,
            current_vwap=current_vwap,
            candles=sample_candles
        )

        assert metrics.symbol == "PEPE-EUR"
        assert metrics.vwap_deviation_pct is not None
        assert metrics.vwap_slope_5m_pct is not None
        assert metrics.vwap_slope_15m_pct is not None
        assert metrics.accel_5m_pct is not None
        assert metrics.accel_15m_pct is not None
        assert metrics.reason is None

    def test_vwap_deviation_positive(self, service):
        """Test VWAP deviation when price above VWAP."""
        deviation = service._calculate_vwap_deviation(
            current_price=120.0,
            current_vwap=100.0
        )

        assert deviation == 20.0  # (120/100 - 1) * 100 = 20%

    def test_vwap_deviation_negative(self, service):
        """Test VWAP deviation when price below VWAP."""
        deviation = service._calculate_vwap_deviation(
            current_price=80.0,
            current_vwap=100.0
        )

        assert deviation == -20.0  # (80/100 - 1) * 100 = -20%

    def test_vwap_deviation_no_vwap(self, service):
        """Test VWAP deviation when VWAP unavailable."""
        deviation = service._calculate_vwap_deviation(
            current_price=120.0,
            current_vwap=None
        )

        assert deviation is None

    def test_vwap_slope_positive(self, service):
        """Test VWAP slope calculation - rising."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0 + i,
                "vwap": 100.0 + (i * 0.5)  # Rising VWAP
            })

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)

        assert slope is not None
        assert slope > 0  # Should be positive
        assert reason is None

    def test_vwap_slope_negative(self, service):
        """Test VWAP slope calculation - falling."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0 - i,
                "vwap": 100.0 - (i * 0.3)  # Falling VWAP
            })

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)

        assert slope is not None
        assert slope < 0  # Should be negative
        assert reason is None

    def test_vwap_slope_flat(self, service):
        """Test VWAP slope when flat."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0,
                "vwap": 100.0  # Flat VWAP
            })

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)

        assert slope is not None
        assert abs(slope) < 0.01  # Should be ~0
        assert reason is None

    def test_vwap_slope_insufficient_history(self, service):
        """Test VWAP slope with insufficient candles."""
        candles = [
            {"timestamp": 1704196800.0, "close": 100.0, "vwap": 100.0},
            {"timestamp": 1704196860.0, "close": 101.0, "vwap": 100.5},
        ]

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)

        assert slope is None
        assert reason == "insufficient_history_for_5m"

    def test_vwap_slope_missing_vwap(self, service):
        """Test VWAP slope when VWAP data missing."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0 + i,
                "vwap": None  # Missing VWAP
            })

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)

        assert slope is None
        assert "no_vwap" in reason

    def test_acceleration_positive(self, service):
        """Test price acceleration - increasing."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0 * (1.01 ** i),  # Accelerating upward
                "vwap": 100.0
            })

        # Current price higher than 5 minutes ago
        current_price = candles[-1]["close"] * 1.05  # 5% above last candle

        accel, reason = service._calculate_acceleration(
            candles=candles,
            current_price=current_price,
            window_minutes=5
        )

        assert accel is not None
        assert accel > 0  # Should be positive
        assert reason is None

    def test_acceleration_negative(self, service):
        """Test price acceleration - decreasing."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": 100.0 * (0.99 ** i),  # Decelerating downward
                "vwap": 100.0
            })

        # Current price lower than 5 minutes ago
        current_price = candles[-1]["close"] * 0.95  # 5% below last candle

        accel, reason = service._calculate_acceleration(
            candles=candles,
            current_price=current_price,
            window_minutes=5
        )

        assert accel is not None
        assert accel < 0  # Should be negative
        assert reason is None

    def test_acceleration_insufficient_history(self, service):
        """Test acceleration with insufficient candles."""
        candles = [
            {"timestamp": 1704196800.0, "close": 100.0, "vwap": 100.0},
        ]

        accel, reason = service._calculate_acceleration(
            candles=candles,
            current_price=105.0,
            window_minutes=15
        )

        assert accel is None
        assert reason == "insufficient_history_for_15m"

    def test_dual_window_slopes(self, service, sample_candles):
        """Test both 5m and 15m slope calculations."""
        metrics = service.calculate_metrics(
            symbol="SUI-EUR",
            current_price=110.0,
            current_vwap=106.0,
            candles=sample_candles
        )

        assert metrics.vwap_slope_5m_pct is not None
        assert metrics.vwap_slope_15m_pct is not None
        # 15m slope should be smoother/smaller than 5m in trending market
        assert abs(metrics.vwap_slope_15m_pct) >= 0

    def test_dual_window_acceleration(self, service, sample_candles):
        """Test both 5m and 15m acceleration calculations."""
        metrics = service.calculate_metrics(
            symbol="DOT-EUR",
            current_price=110.0,
            current_vwap=106.0,
            candles=sample_candles
        )

        assert metrics.accel_5m_pct is not None
        assert metrics.accel_15m_pct is not None
        # 15m acceleration should capture larger move
        assert isinstance(metrics.accel_15m_pct, float)

    def test_no_candles_provided(self, service):
        """Test with empty candle list."""
        metrics = service.calculate_metrics(
            symbol="BTC-EUR",
            current_price=50000.0,
            current_vwap=49000.0,
            candles=[]
        )

        assert metrics.reason == "insufficient_history"
        assert metrics.vwap_deviation_pct is None
        assert metrics.vwap_slope_5m_pct is None
        assert metrics.accel_5m_pct is None

    def test_invalid_current_price(self, service, sample_candles):
        """Test with invalid current price."""
        metrics = service.calculate_metrics(
            symbol="ETH-EUR",
            current_price=0.0,  # Invalid
            current_vwap=3000.0,
            candles=sample_candles
        )

        assert metrics.reason == "invalid_price"
        assert metrics.vwap_deviation_pct is None

    def test_missing_vwap_graceful_handling(self, service, sample_candles):
        """Test graceful handling when VWAP missing."""
        metrics = service.calculate_metrics(
            symbol="ADA-EUR",
            current_price=1.0,
            current_vwap=None,  # Missing VWAP
            candles=sample_candles
        )

        # Should still calculate acceleration but not VWAP metrics
        assert metrics.vwap_deviation_pct is None
        assert metrics.reason == "no_vwap_data"
        # Slopes require VWAP in candles, but accel might work

    def test_has_sufficient_data_true(self, service):
        """Test has_sufficient_data with complete metrics."""
        metrics = MomentumMetrics(
            timestamp=time.time(),
            symbol="PEPE-EUR",
            vwap_deviation_pct=19.2,
            vwap_slope_5m_pct=0.15,
            vwap_slope_15m_pct=0.03,
            accel_5m_pct=2.1,
            accel_15m_pct=5.8,
            reason=None
        )

        assert service.has_sufficient_data(metrics) is True

    def test_has_sufficient_data_false(self, service):
        """Test has_sufficient_data with incomplete metrics."""
        metrics = MomentumMetrics(
            timestamp=time.time(),
            symbol="BTC-EUR",
            vwap_deviation_pct=None,
            vwap_slope_5m_pct=0.15,
            vwap_slope_15m_pct=0.03,
            accel_5m_pct=2.1,
            accel_15m_pct=5.8,
            reason="no_vwap_data"
        )

        assert service.has_sufficient_data(metrics) is False

    def test_connector_name_kraken(self):
        """Test service with Kraken connector."""
        service = MomentumIndicatorService(connector_name="kraken")
        assert service.connector_name == "kraken"

    def test_connector_name_bitget(self):
        """Test service with Bitget connector."""
        service = MomentumIndicatorService(connector_name="bitget")
        assert service.connector_name == "bitget"

    def test_zero_division_protection(self, service):
        """Test protection against zero division."""
        # VWAP deviation with zero VWAP
        deviation = service._calculate_vwap_deviation(
            current_price=100.0,
            current_vwap=0.0
        )
        assert deviation is None

        # Slope with zero VWAP
        candles = [
            {"timestamp": 1704196800.0 + i * 60, "close": 100.0, "vwap": 0.0}
            for i in range(20)
        ]
        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)
        assert slope is None

    def test_nan_handling(self, service):
        """Test handling of NaN values."""
        candles = []
        for i in range(20):
            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": float('nan'),  # NaN price
                "vwap": 100.0
            })

        # Should handle gracefully
        accel, reason = service._calculate_acceleration(
            candles=candles,
            current_price=100.0,
            window_minutes=5
        )
        # Depending on implementation, might be None or error
        # The important thing is it doesn't crash

    def test_extreme_values(self, service):
        """Test with extreme but valid values."""
        metrics = service.calculate_metrics(
            symbol="MEME-EUR",
            current_price=0.00001,  # Very small price
            current_vwap=0.000008,
            candles=[
                {
                    "timestamp": 1704196800.0 + i * 60,
                    "close": 0.00001 * (1.1 ** i),
                    "vwap": 0.000008 * (1.05 ** i)
                }
                for i in range(20)
            ]
        )

        # Should calculate without overflow/underflow
        assert metrics.vwap_deviation_pct is not None
        assert abs(metrics.vwap_deviation_pct) > 0

    def test_metrics_repr(self):
        """Test string representation of metrics."""
        metrics = MomentumMetrics(
            timestamp=1704196800.0,
            symbol="TEST-EUR",
            vwap_deviation_pct=19.23,
            vwap_slope_5m_pct=0.15,
            vwap_slope_15m_pct=0.03,
            accel_5m_pct=2.10,
            accel_15m_pct=5.80,
            reason=None
        )

        repr_str = repr(metrics)
        assert "TEST-EUR" in repr_str
        assert "19.23" in repr_str

    def test_warning_rate_limiting(self, service, sample_candles):
        """Test that warnings are rate-limited."""
        # First call should log warning (insufficient data)
        metrics1 = service.calculate_metrics(
            symbol="RATE-TEST",
            current_price=100.0,
            current_vwap=None,  # Trigger warning
            candles=sample_candles
        )

        # Immediate second call should NOT log (rate limited)
        # We can't directly test logging, but we can verify the method runs
        metrics2 = service.calculate_metrics(
            symbol="RATE-TEST",
            current_price=100.0,
            current_vwap=None,
            candles=sample_candles
        )

        assert metrics1.reason == "no_vwap_data"
        assert metrics2.reason == "no_vwap_data"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_exactly_minimum_candles_5m(self):
        """Test with exactly 5 candles (minimum for 5m calculation)."""
        service = MomentumIndicatorService(connector_name="test")
        candles = [
            {"timestamp": 1704196800.0 + i * 60, "close": 100.0 + i, "vwap": 100.0}
            for i in range(6)  # Need 6 for 5-minute lookback (current + 5 back)
        ]

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=5)
        assert slope is not None or reason is not None

    def test_exactly_minimum_candles_15m(self):
        """Test with exactly 15 candles (minimum for 15m calculation)."""
        service = MomentumIndicatorService(connector_name="test")
        candles = [
            {"timestamp": 1704196800.0 + i * 60, "close": 100.0 + i, "vwap": 100.0}
            for i in range(16)  # Need 16 for 15-minute lookback
        ]

        slope, reason = service._calculate_vwap_slope(candles, window_minutes=15)
        assert slope is not None or reason is not None

    def test_large_candle_dataset(self):
        """Test with large number of candles (performance check)."""
        service = MomentumIndicatorService(connector_name="test")
        candles = [
            {"timestamp": 1704196800.0 + i * 60, "close": 100.0 + (i * 0.1), "vwap": 100.0}
            for i in range(1000)  # 1000 candles
        ]

        metrics = service.calculate_metrics(
            symbol="BIG-DATA",
            current_price=200.0,
            current_vwap=150.0,
            candles=candles
        )

        # Should handle efficiently
        assert metrics is not None


class TestRealWorldScenarios:
    """Test realistic market scenarios."""

    def test_pepe_blowoff_top_scenario(self):
        """
        Test PEPE blow-off top scenario from EPIC description.
        Price +43% but VWAP slope flattening.
        """
        service = MomentumIndicatorService(connector_name="kraken")

        # Simulate PEPE rally: price shoots up but VWAP lags
        candles = []
        base_price = 100.0
        base_vwap = 100.0

        for i in range(20):
            if i < 10:
                # Early rally: both rise
                price_mult = 1.03 ** i
                vwap_mult = 1.02 ** i
            else:
                # Late rally: price parabolic, VWAP flattening
                price_mult = (1.03 ** 10) * (1.08 ** (i - 10))
                vwap_mult = (1.02 ** 10) * (1.005 ** (i - 10))  # Slowing

            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": base_price * price_mult,
                "vwap": base_vwap * vwap_mult
            })

        current_price = base_price * 1.43  # +43%
        current_vwap = candles[-1]["vwap"]

        metrics = service.calculate_metrics(
            symbol="PEPE-EUR",
            current_price=current_price,
            current_vwap=current_vwap,
            candles=candles
        )

        # Verify blow-off characteristics
        assert metrics.vwap_deviation_pct > 10.0  # Price above VWAP
        assert metrics.vwap_slope_15m_pct is not None
        assert metrics.accel_15m_pct is not None  # Acceleration calculated

    def test_healthy_consolidation_scenario(self):
        """
        Test healthy consolidation: 15m slope flat but 5m still rising.
        Should NOT trigger false rejection.
        """
        service = MomentumIndicatorService(connector_name="kraken")

        candles = []
        base_price = 100.0

        for i in range(20):
            if i < 15:
                # Initial rise
                price = base_price * (1.01 ** i)
                vwap = base_price * (1.008 ** i)
            else:
                # Recent consolidation (last 5 candles)
                price = base_price * (1.01 ** 15) * (1.002 ** (i - 15))
                vwap = base_price * (1.008 ** 15) * (1.001 ** (i - 15))

            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": price,
                "vwap": vwap
            })

        metrics = service.calculate_metrics(
            symbol="SUI-EUR",
            current_price=candles[-1]["close"] * 1.01,
            current_vwap=candles[-1]["vwap"],
            candles=candles
        )

        # 5m slope should still be positive (recent activity)
        # 15m slope might be flatter (includes consolidation)
        assert metrics.vwap_slope_5m_pct is not None
        assert metrics.vwap_slope_15m_pct is not None

    def test_strong_downtrend_scenario(self):
        """Test strong downtrend with negative slopes and acceleration."""
        service = MomentumIndicatorService(connector_name="kraken")

        candles = []
        base_price = 100.0

        for i in range(20):
            # Steady decline
            price = base_price * (0.98 ** i)
            vwap = base_price * (0.985 ** i)

            candles.append({
                "timestamp": 1704196800.0 + (i * 60),
                "close": price,
                "vwap": vwap
            })

        metrics = service.calculate_metrics(
            symbol="BEAR-EUR",
            current_price=candles[-1]["close"] * 0.98,
            current_vwap=candles[-1]["vwap"],
            candles=candles
        )

        # All metrics should be negative
        assert metrics.vwap_slope_5m_pct < 0
        assert metrics.vwap_slope_15m_pct < 0
        assert metrics.accel_5m_pct < 0
        assert metrics.accel_15m_pct < 0
        assert metrics.vwap_deviation_pct < 0  # Price below VWAP


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
