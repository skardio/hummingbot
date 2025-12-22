"""
Tests for the Bitget futures controller with relaxed multi-timeframe conditions.
"""
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from multi_coin_grid_pro.futures_bitget.config_schema import FuturesGridBitgetConfig  # noqa: E402
from multi_coin_grid_pro.futures_bitget.controller import FuturesGridBitgetController  # noqa: E402

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


class TestFuturesGridBitgetController:
    """Tests for futures-specific controller behavior"""

    @pytest.fixture
    def futures_controller(self):
        """Create a futures controller instance for testing"""
        config = FuturesGridBitgetConfig(
            controller_name="test_futures_controller",
            connector_name="bitget_perpetual",
            quote_asset="USDT",
            manual_trading_pairs=["BTC-USDT"],
            trend_min_change_pct=Decimal("0.1"),
            use_multi_timeframe=True,
            max_coins_to_monitor=10,
            trend_lookback_minutes=1440,
            min_switch_interval_seconds=900,
            total_amount_quote=Decimal("1000.0"),
            stop_loss_pct=Decimal("0.10"),
            price_update_interval=30,
            # Risk management config (required for risk_manager initialization)
            risk_reference_balance_quote=Decimal("10000"),
            risk_max_daily_loss_pct=Decimal("2"),
            risk_max_balance_per_trade_pct=Decimal("0.5"),
            risk_max_total_open_risk_pct=Decimal("3"),
            risk_exit_cooldown_minutes=30,
            risk_symbol_switch_cooldown_minutes=45,
            risk_consecutive_loss_cooldown_minutes=60,
            # Futures-specific config
            futures_min_entry_strength_24h=1.5,
            futures_min_entry_strength_4h=1.0,
            futures_min_entry_strength_1h=0.0,
            trend_min_entry_strength=0.07,  # 7% trend strength (0.07 = 7%)
            # Warmup mode thresholds
            warmup_min_4h_trend_pct=1.0,
            warmup_min_1h_trend_pct=0.5,
        )

        market_data_provider = MagicMock()
        market_data_provider.time.return_value = 1000000.0  # Mock time

        controller = FuturesGridBitgetController(
            config=config,
            market_data_provider=market_data_provider,
            actions_queue=MagicMock(),
            connectors={},
            update_interval=10.0
        )
        controller.trend_calculator = MagicMock()
        controller.market_data_provider = market_data_provider
        # BUG FIX: Create proper logger mock - logger() should return a logger object with info/warning/debug methods
        logger_instance = MagicMock()
        logger_instance.info = MagicMock()
        logger_instance.warning = MagicMock()
        logger_instance.debug = MagicMock()
        logger_instance.critical = MagicMock()
        controller.logger = MagicMock(return_value=logger_instance)
        # Also store logger_instance for test assertions
        controller._logger_instance = logger_instance
        return controller

    def test_futures_multi_timeframe_buy_conditions_relaxed_thresholds(self, futures_controller):
        """Test that futures controller uses relaxed thresholds (0.1% instead of 1.0%)"""
        trend = MagicMock()
        trend.trend_1440m = 2.0  # Above 1.5% threshold (futures requires >1.5%)
        trend.trend_240m = 1.5   # Above 1.0% threshold (futures requires >1.0%)
        trend.trend_60m = 0.5     # Above 0.0% threshold (futures requires >=0.0%)
        trend.trend_score = Decimal("7.5")  # For trend strength calculation (7.5 / 10 = 0.75 >= 0.7)
        trend.consensus_trend_pct = Decimal("7.5")  # For trend strength calculation
        trend.trend_pct = Decimal("7.5")  # Fallback value
        trend.long_trend_warmup = False
        trend.last_updated = futures_controller.market_data_provider.time() - 10  # Recent update
        trend.current_price = Decimal("50000.0")

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("BTC-USDT")

        assert result is True, "Futures controller should accept coins with 2.0% 24h, 1.5% 4h, 0.5% 1h trends"
        futures_controller._logger_instance.info.assert_called()
        call_args = str(futures_controller._logger_instance.info.call_args)
        assert "futures" in call_args.lower() or "approved" in call_args.lower() or "entry confirmed" in call_args.lower()

    def test_futures_multi_timeframe_buy_conditions_warmup_relaxed(self, futures_controller):
        """Test that futures warm-up mode has relaxed requirements"""
        trend = MagicMock()
        trend.trend_1440m = 1.0  # Warm-up fallback
        trend.trend_240m = 1.5   # Above 1.0% threshold for warm-up (futures requires >1.0%)
        trend.trend_60m = 0.6    # Above 0.5% threshold for warm-up (futures requires >=0.5%)
        trend.trend_score = Decimal("7.0")  # For trend strength calculation (7.0 / 10 = 0.7 >= 0.7)
        trend.consensus_trend_pct = Decimal("7.0")  # For trend strength calculation
        trend.trend_pct = Decimal("7.0")  # Fallback value
        trend.long_trend_warmup = True
        trend.last_updated = futures_controller.market_data_provider.time() - 10
        trend.current_price = Decimal("50000.0")

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("ETH-USDT")

        assert result is True, "Futures warm-up should accept coins with 1.5% 4h and 0.6% 1h trends"
        futures_controller._logger_instance.info.assert_called()
        call_args = str(futures_controller._logger_instance.info.call_args)
        assert "futures warm-up" in call_args.lower() or "approved" in call_args.lower() or "warm-up entry allowed" in call_args.lower()

    def test_futures_multi_timeframe_buy_conditions_rejects_strong_decline(self, futures_controller):
        """Test that futures controller still rejects strongly declining trends"""
        trend = MagicMock()
        trend.trend_1440m = 2.0   # Positive 24h
        trend.trend_240m = -0.6   # Negative 4h (below 1.0% threshold)
        trend.trend_60m = -1.5    # Strongly negative 1h (below 0.0% threshold)
        trend.trend_score = Decimal("-0.5")  # For trend strength calculation
        trend.consensus_trend_pct = Decimal("-0.5")  # For trend strength calculation
        trend.trend_pct = Decimal("-0.5")  # Fallback value
        trend.long_trend_warmup = False
        trend.last_updated = futures_controller.market_data_provider.time() - 10
        trend.current_price = Decimal("50000.0")

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("SOL-USDT")

        assert result is False, "Futures controller should reject strongly declining trends"
        # Should log rejection reason
        assert futures_controller._logger_instance.info.called or futures_controller._logger_instance.debug.called

    def test_futures_multi_timeframe_buy_conditions_allows_slight_negative_1h(self, futures_controller):
        """Test that futures controller allows 1h trend at 0.0% threshold (futures requires >=0.0%)"""
        trend = MagicMock()
        trend.trend_1440m = 2.0   # Above 1.5% threshold
        trend.trend_240m = 1.5    # Above 1.0% threshold
        trend.trend_60m = 0.0     # At 0.0% threshold (futures requires >=0.0%)
        trend.trend_score = Decimal("7.5")  # For trend strength calculation (7.5 / 10 = 0.75 >= 0.7)
        trend.consensus_trend_pct = Decimal("7.5")  # For trend strength calculation
        trend.trend_pct = Decimal("7.5")  # Fallback value
        trend.long_trend_warmup = False
        trend.last_updated = futures_controller.market_data_provider.time() - 10
        trend.current_price = Decimal("50000.0")

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("XRP-USDT")

        assert result is True, "Futures controller should allow 1h trend at 0.0% (futures requires >=0.0%)"
        futures_controller._logger_instance.info.assert_called()

    def test_futures_multi_timeframe_buy_conditions_rejects_below_threshold(self, futures_controller):
        """Test that futures controller rejects coins below threshold"""
        trend = MagicMock()
        trend.trend_1440m = 1.0   # Below 1.5% threshold (futures requires >1.5%)
        trend.trend_240m = 1.5
        trend.trend_60m = 0.5
        trend.trend_score = 0.05   # Low trend score (0.05 < 0.07 threshold)
        trend.consensus_trend_pct = 0.05  # Ensure consensus is also low
        trend.long_trend_warmup = False
        trend.last_updated = futures_controller.market_data_provider.time() - 10
        trend.current_price = Decimal("50000.0")

        futures_controller.trend_calculator.get_trend = MagicMock(return_value=trend)

        result = futures_controller._check_multi_timeframe_buy_conditions("LINK-USDT")

        assert result is False, "Futures controller should reject coins with trend score < 0.07"
        # Should have logged rejection reason (either debug for trend strength or info for timeframe thresholds)
        logged = futures_controller._logger_instance.info.called or futures_controller._logger_instance.debug.called
        assert logged, "Should log rejection reason"
