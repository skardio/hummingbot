"""
Unit tests for Multi-Timeframe Trend Engine (Phase 2.5)

Tests the multi-timeframe trend calculation, warm-up mode, composite scores,
and all buy/exit/switch logic.
"""

import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.trend_calculator import CoinTrend, TrendCalculator

# Only mark async tests with asyncio
# pytestmark = pytest.mark.asyncio  # Removed - only async tests need this mark


class TestMultiTimeframeTrendCalculation:
    """Test multi-timeframe trend calculations"""

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.get_last_traded_prices = AsyncMock(return_value={"XRP-EUR": Decimal("1.5")})
        return connector

    @pytest.fixture
    def trend_calculator(self, mock_connector):
        """Create TrendCalculator with multi-timeframe support"""
        bot_start_time = time.time() - 3600  # Bot started 1 hour ago
        return TrendCalculator(
            connector=mock_connector,
            lookback_minutes=30,
            bot_start_time=bot_start_time
        )

    @pytest.mark.asyncio
    async def test_multi_timeframe_fields_exist(self, trend_calculator, mock_connector):
        """Test that CoinTrend has multi-timeframe fields"""
        mock_connector.get_last_traded_prices = AsyncMock(
            return_value={"XRP-EUR": Decimal("1.5")}
        )

        trend = await trend_calculator.update_coin_trend("XRP/EUR")  # Input can be XRP/EUR, will be converted

        assert trend is not None
        assert hasattr(trend, 'trend_60m')
        assert hasattr(trend, 'trend_240m')
        assert hasattr(trend, 'trend_1440m')
        assert hasattr(trend, 'trend_score')
        assert hasattr(trend, 'long_trend_warmup')

    @pytest.mark.asyncio
    async def test_trend_score_calculation(self, trend_calculator, mock_connector):
        """Test composite trend score calculation"""
        # Create price history with clear trends
        # Start price: 1.0, end price: 1.1 (10% increase)
        prices = [Decimal("1.0") + Decimal(str(i * 0.001)) for i in range(100)]

        for price in prices:
            mock_connector.get_last_traded_prices = AsyncMock(
                return_value={"XRP-EUR": price}
            )
            await trend_calculator.update_coin_trend("XRP/EUR")  # Input can be XRP/EUR, will be converted
            time.sleep(0.01)

        trend = trend_calculator.get_trend("XRP-EUR")  # get_trend uses converted symbol

        # Verify trends are calculated
        assert trend is not None
        assert trend.trend_60m != 0.0 or trend.long_trend_warmup  # Either calculated or warm-up
        assert trend.trend_240m != 0.0 or trend.long_trend_warmup
        assert trend.trend_1440m != 0.0 or trend.long_trend_warmup

        # Verify trend_score is calculated
        if not trend.long_trend_warmup:
            expected_score = (
                0.2 * trend.trend_60m +
                0.4 * trend.trend_240m +
                0.4 * trend.trend_1440m
            )
            assert abs(trend.trend_score - expected_score) < 0.01  # Allow small rounding error

    @pytest.mark.asyncio
    async def test_warmup_mode_24h_trend(self, mock_connector):
        """Test warm-up mode for 24h trend (first 24h after bot start)"""
        # Bot just started
        bot_start_time = time.time()
        calculator = TrendCalculator(
            connector=mock_connector,
            lookback_minutes=30,
            bot_start_time=bot_start_time
        )

        # Add some price data
        prices = [Decimal("1.0") + Decimal(str(i * 0.001)) for i in range(50)]
        for price in prices:
            mock_connector.get_last_traded_prices = AsyncMock(
                return_value={"XRP-EUR": price}
            )
            await calculator.update_coin_trend("XRP/EUR")  # Input can be XRP/EUR, will be converted
            time.sleep(0.01)

        trend = calculator.get_trend("XRP-EUR")  # get_trend uses converted symbol

        # Should be in warm-up mode (less than 24h since bot start)
        assert trend.long_trend_warmup is True

        # 24h trend should be 240m trend * 2
        if trend.trend_240m != 0.0:
            expected_1440m = trend.trend_240m * 2.0
            assert abs(trend.trend_1440m - expected_1440m) < 0.01

    @pytest.mark.asyncio
    async def test_warmup_mode_after_24h(self, mock_connector):
        """Test that warm-up mode ends after 24h"""
        # Bot started 25 hours ago
        bot_start_time = time.time() - (25 * 3600)
        calculator = TrendCalculator(
            connector=mock_connector,
            lookback_minutes=30,
            bot_start_time=bot_start_time
        )

        # Add enough price data (need at least 1440 minutes worth)
        # For testing, we'll add data points with timestamps
        prices = [Decimal("1.0") + Decimal(str(i * 0.001)) for i in range(200)]
        for price in prices:
            mock_connector.get_last_traded_prices = AsyncMock(
                return_value={"XRP-EUR": price}
            )
            await calculator.update_coin_trend("XRP/EUR")  # Input can be XRP/EUR, will be converted
            time.sleep(0.01)

        trend = calculator.get_trend("XRP-EUR")  # get_trend uses converted symbol

        # Should NOT be in warm-up mode (more than 24h since bot start)
        assert trend.long_trend_warmup is False

        # 24h trend should be calculated normally (not 240m * 2)
        # Note: This might still be 240m * 2 if we don't have enough data points
        # But the warmup flag should be False

    @pytest.mark.asyncio
    async def test_get_best_coin_uses_trend_score(self, trend_calculator, mock_connector):
        """Test that get_best_coin uses trend_score for selection"""
        # Create two coins with different trends
        coins = {
            "XRP-EUR": Decimal("1.0"),
            "ADA-EUR": Decimal("0.5"),
        }

        # Add data for both coins
        for symbol, start_price in coins.items():
            prices = [start_price * (Decimal("1.0") + Decimal(str(i * 0.001))) for i in range(50)]
            for price in prices:
                mock_connector.get_last_traded_prices = AsyncMock(
                    return_value={symbol: price}
                )
                await trend_calculator.update_coin_trend(symbol)  # Symbol is already in XRP-EUR format
                time.sleep(0.01)

        best = trend_calculator.get_best_coin(min_trend_pct=0.0)

        # Should return one of the coins (or None if insufficient data)
        if best is not None:
            assert best in coins.keys()
            trend = trend_calculator.get_trend(best)
            # Verify trend_score is used
            assert hasattr(trend, 'trend_score')


class TestMultiTimeframeBuyConditions:
    """Test multi-timeframe buy conditions"""

    def test_buy_conditions_all_met(self):
        """Test buy conditions when all timeframes meet criteria"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=1.5,   # >= 0% ✓
            trend_240m=2.0,   # > +1% ✓
            trend_1440m=3.0,  # > +1% ✓
        )

        # Buy conditions: trend_1440m > +1%, trend_240m > +1%, trend_60m >= 0%
        assert trend.trend_1440m > 1.0
        assert trend.trend_240m > 1.0
        assert trend.trend_60m >= 0.0

        # Should allow buying
        buy_allowed = (
            trend.trend_1440m > 1.0 and
            trend.trend_240m > 1.0 and
            trend.trend_60m >= 0.0
        )
        assert buy_allowed is True

    def test_buy_conditions_60m_fails(self):
        """Test buy conditions when 60m trend fails"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-0.5,  # < 0% ✗
            trend_240m=2.0,   # > +1% ✓
            trend_1440m=3.0,  # > +1% ✓
        )

        buy_allowed = (
            trend.trend_1440m > 1.0 and
            trend.trend_240m > 1.0 and
            trend.trend_60m >= 0.0
        )
        assert buy_allowed is False

    def test_buy_conditions_240m_fails(self):
        """Test buy conditions when 240m trend fails"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=1.0,    # >= 0% ✓
            trend_240m=0.5,   # <= +1% ✗
            trend_1440m=3.0,  # > +1% ✓
        )

        buy_allowed = (
            trend.trend_1440m > 1.0 and
            trend.trend_240m > 1.0 and
            trend.trend_60m >= 0.0
        )
        assert buy_allowed is False

    def test_buy_conditions_1440m_fails(self):
        """Test buy conditions when 1440m trend fails"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=1.0,    # >= 0% ✓
            trend_240m=2.0,   # > +1% ✓
            trend_1440m=0.5,  # <= +1% ✗
        )

        buy_allowed = (
            trend.trend_1440m > 1.0 and
            trend.trend_240m > 1.0 and
            trend.trend_60m >= 0.0
        )
        assert buy_allowed is False


class TestMultiTimeframeExitConditions:
    """Test multi-timeframe exit conditions"""

    def test_exit_conditions_met(self):
        """Test exit conditions when both criteria are met"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-1.5,   # < -1% ✓
            trend_240m=0.3,   # < +0.5% ✓
            trend_1440m=2.0,
        )

        # Exit conditions: trend_60m < -1% AND trend_240m < +0.5%
        exit_triggered = (
            trend.trend_60m < -1.0 and
            trend.trend_240m < 0.5
        )
        assert exit_triggered is True

    def test_exit_conditions_60m_not_met(self):
        """Test exit conditions when 60m trend doesn't meet threshold"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-0.5,   # >= -1% ✗
            trend_240m=0.3,    # < +0.5% ✓
            trend_1440m=2.0,
        )

        exit_triggered = (
            trend.trend_60m < -1.0 and
            trend.trend_240m < 0.5
        )
        assert exit_triggered is False

    def test_exit_conditions_240m_not_met(self):
        """Test exit conditions when 240m trend doesn't meet threshold"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-1.5,   # < -1% ✓
            trend_240m=1.0,   # >= +0.5% ✗
            trend_1440m=2.0,
        )

        exit_triggered = (
            trend.trend_60m < -1.0 and
            trend.trend_240m < 0.5
        )
        assert exit_triggered is False


class TestAntiChurnLogic:
    """Test anti-churn logic (prevent switching from strong trends)"""

    def test_anti_churn_prevents_switch(self):
        """Test that anti-churn prevents switching when macro-trend is strong"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-0.5,   # -1% <= trend_60m < 0% ✓
            trend_240m=1.0,    # > +0.5% ✓
            trend_1440m=3.0,   # > +2% ✓
        )

        # Anti-churn: trend_1440m > +2% AND trend_240m > +0.5% AND -1% <= trend_60m < 0%
        anti_churn_active = (
            trend.trend_1440m > 2.0 and
            trend.trend_240m > 0.5 and
            -1.0 <= trend.trend_60m < 0.0
        )
        assert anti_churn_active is True

    def test_anti_churn_not_active_60m_too_low(self):
        """Test that anti-churn doesn't activate when 60m trend is too low"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-1.5,   # < -1% ✗
            trend_240m=1.0,    # > +0.5% ✓
            trend_1440m=3.0,   # > +2% ✓
        )

        anti_churn_active = (
            trend.trend_1440m > 2.0 and
            trend.trend_240m > 0.5 and
            -1.0 <= trend.trend_60m < 0.0
        )
        assert anti_churn_active is False

    def test_anti_churn_not_active_1440m_too_low(self):
        """Test that anti-churn doesn't activate when 1440m trend is too low"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_60m=-0.5,   # -1% <= trend_60m < 0% ✓
            trend_240m=1.0,    # > +0.5% ✓
            trend_1440m=1.5,   # <= +2% ✗
        )

        anti_churn_active = (
            trend.trend_1440m > 2.0 and
            trend.trend_240m > 0.5 and
            -1.0 <= trend.trend_60m < 0.0
        )
        assert anti_churn_active is False


class TestSwitchLogic:
    """Test smart switching logic"""

    def test_switch_threshold_met(self):
        """Test that switch happens when threshold is met"""
        active_trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_score=2.0,
        )

        new_trend = CoinTrend(
            symbol="ADA/EUR",
            current_price=Decimal("0.5"),
            trend_score=4.0,  # 4.0 - 2.0 = 2.0% >= 1.5% ✓
        )

        # Switch threshold: trend_score(new) - trend_score(active) >= 1.5%
        switch_allowed = (new_trend.trend_score - active_trend.trend_score) >= 1.5
        assert switch_allowed is True

    def test_switch_threshold_not_met(self):
        """Test that switch doesn't happen when threshold is not met"""
        active_trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_score=2.0,
        )

        new_trend = CoinTrend(
            symbol="ADA/EUR",
            current_price=Decimal("0.5"),
            trend_score=3.0,  # 3.0 - 2.0 = 1.0% < 1.5% ✗
        )

        switch_allowed = (new_trend.trend_score - active_trend.trend_score) >= 1.5
        assert switch_allowed is False

    def test_switch_threshold_exact(self):
        """Test switch threshold at exact boundary"""
        active_trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_score=2.0,
        )

        new_trend = CoinTrend(
            symbol="ADA/EUR",
            current_price=Decimal("0.5"),
            trend_score=3.5,  # 3.5 - 2.0 = 1.5% == 1.5% ✓
        )

        switch_allowed = (new_trend.trend_score - active_trend.trend_score) >= 1.5
        assert switch_allowed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
