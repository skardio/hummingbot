"""
Tests for the Bitget futures controller with relaxed multi-timeframe conditions.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from decimal import Decimal

from multi_coin_grid_pro.futures_bitget.config_schema import FuturesGridBitgetConfig
from multi_coin_grid_pro.futures_bitget.controller import FuturesGridBitgetController


class TestFuturesGridBitgetController:
    """Tests for futures-specific controller behavior"""

    @pytest.fixture
    def futures_controller(self):
        """Create a futures controller instance for testing"""
        config = MagicMock(spec=FuturesGridBitgetConfig)
        config.trend_min_change_pct = 0.1
        config.use_multi_timeframe = True
        # BUG FIX: Add required config attributes that controller accesses during initialization
        config.connector_name = "bitget_perpetual"
        config.quote_asset = "USDT"
        config.max_coins_to_monitor = 10
        config.trend_lookback_minutes = 1440
        config.min_switch_interval_seconds = 900
        config.total_amount_quote = Decimal("1000.0")  # BUG FIX: Add total_amount_quote attribute
        config.stop_loss_pct = 0.10  # BUG FIX: Add stop_loss_pct attribute (10% stop loss)

        controller = FuturesGridBitgetController(
            config=config,
            market_data_provider=MagicMock(),
            actions_queue=MagicMock(),
            connectors={},
            update_interval=10.0
        )
        controller.trend_calculator = MagicMock()
        # BUG FIX: Create proper logger mock - logger() should return a logger object with info/warning/debug methods
        logger_instance = MagicMock()
        logger_instance.info = MagicMock()
        logger_instance.warning = MagicMock()
        logger_instance.debug = MagicMock()
        controller.logger = MagicMock(return_value=logger_instance)
        # Also store logger_instance for test assertions
        controller._logger_instance = logger_instance
        return controller

    def test_futures_multi_timeframe_buy_conditions_relaxed_thresholds(self, futures_controller):
        """Test that futures controller uses relaxed thresholds (0.1% instead of 1.0%)"""
        trend = MagicMock()
        trend.trend_1440m = 0.2  # Would be rejected by spot (needs >1.0%), but OK for futures (>0.1%)
        trend.trend_240m = 0.2   # Would be rejected by spot (needs >1.0%), but OK for futures (>0.1%)
        trend.trend_60m = 0.0    # OK for both
        trend.trend_score = 0.15
        trend.long_trend_warmup = False

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("BTC-USDT")

        assert result is True, "Futures controller should accept coins with 0.2% trends"
        futures_controller._logger_instance.info.assert_called()
        call_args = str(futures_controller._logger_instance.info.call_args)
        assert "futures mode" in call_args.lower() or "approved" in call_args.lower()

    def test_futures_multi_timeframe_buy_conditions_warmup_relaxed(self, futures_controller):
        """Test that futures warm-up mode has relaxed requirements"""
        trend = MagicMock()
        trend.trend_1440m = 1.0  # Warm-up fallback
        trend.trend_240m = 0.6   # Would be rejected by spot warm-up (needs >1.5%), but OK for futures (>0.5%)
        trend.trend_60m = 0.1    # Would be rejected by spot warm-up (needs >=0.3%), but OK for futures (>=0.0%)
        trend.trend_score = 0.5
        trend.long_trend_warmup = True

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("ETH-USDT")

        assert result is True, "Futures warm-up should accept coins with 0.6% 4h and 0.1% 1h trends"
        futures_controller._logger_instance.info.assert_called()
        call_args = str(futures_controller._logger_instance.info.call_args)
        assert "futures warm-up" in call_args.lower() or "approved" in call_args.lower()

    def test_futures_multi_timeframe_buy_conditions_rejects_strong_decline(self, futures_controller):
        """Test that futures controller still rejects strongly declining trends"""
        trend = MagicMock()
        trend.trend_1440m = 2.0   # Positive 24h
        trend.trend_240m = -0.6   # Negative 4h
        trend.trend_60m = -1.5    # Strongly negative 1h (< -1.0%)
        trend.trend_score = -0.5
        trend.long_trend_warmup = False

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("SOL-USDT")

        assert result is False, "Futures controller should reject strongly declining trends"
        futures_controller._logger_instance.warning.assert_called()
        call_args = str(futures_controller._logger_instance.warning.call_args)
        assert "declining" in call_args.lower() or "rejected" in call_args.lower()

    def test_futures_multi_timeframe_buy_conditions_allows_slight_negative_1h(self, futures_controller):
        """Test that futures controller allows slight negative 1h trend (>= -0.2%)"""
        trend = MagicMock()
        trend.trend_1440m = 0.5   # Positive 24h
        trend.trend_240m = 0.3    # Positive 4h
        trend.trend_60m = -0.1    # Slight negative 1h (would be rejected by spot, but OK for futures >= -0.2%)
        trend.trend_score = 0.2
        trend.long_trend_warmup = False

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("XRP-USDT")

        assert result is True, "Futures controller should allow slight negative 1h trend (-0.1%)"
        futures_controller._logger_instance.info.assert_called()

    def test_futures_multi_timeframe_buy_conditions_rejects_below_threshold(self, futures_controller):
        """Test that futures controller rejects coins below 0.1% threshold"""
        trend = MagicMock()
        trend.trend_1440m = 0.05  # Below 0.1% threshold
        trend.trend_240m = 0.2
        trend.trend_60m = 0.1
        trend.trend_score = 0.1
        trend.long_trend_warmup = False

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("LINK-USDT")

        assert result is False, "Futures controller should reject coins with 24h trend <= 0.1%"
        futures_controller._logger_instance.debug.assert_called()
