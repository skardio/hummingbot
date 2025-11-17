"""
Unit tests for TrendCalculator module
"""

import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.trend_calculator import CoinTrend, TrendCalculator

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestTrendCalculator:
    """Test suite for TrendCalculator class"""

    @pytest_asyncio.fixture
    async def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.get_price_by_type = AsyncMock(return_value=Decimal("1.5"))
        return connector

    @pytest_asyncio.fixture
    async def trend_calculator(self, mock_connector):
        """Create TrendCalculator instance"""
        return TrendCalculator(
            connector=mock_connector,
            lookback_minutes=30
        )

    async def test_update_coin_trend(self, trend_calculator, mock_connector):
        """Test updating trend for a single coin"""
        # Mock price
        mock_connector.get_price_by_type = AsyncMock(return_value=Decimal("1.5"))

        trend = await trend_calculator.update_coin_trend("XRP/EUR")

        assert trend is not None
        assert trend.symbol == "XRP/EUR"
        assert trend.current_price == Decimal("1.5")
        assert len(trend.price_history) == 1

    async def test_trend_calculation(self, trend_calculator, mock_connector):
        """Test trend percentage calculation"""
        # Simulate price increase
        prices = [Decimal("1.0"), Decimal("1.05"), Decimal("1.10")]

        for price in prices:
            mock_connector.get_price_by_type = AsyncMock(return_value=price)
            await trend_calculator.update_coin_trend("XRP/EUR")
            time.sleep(0.01)  # Small delay

        trend = trend_calculator.get_trend("XRP/EUR")

        assert trend is not None
        assert trend.trend_pct > 0  # Upward trend
        assert abs(trend.trend_pct - 10.0) < 1.0  # ~10% increase

    async def test_price_history_cleanup(self, trend_calculator, mock_connector):
        """Test old price data is removed"""
        # Create calculator with 1 second lookback for testing
        calculator = TrendCalculator(
            connector=mock_connector,
            lookback_minutes=0.0167  # ~1 second
        )

        # Add multiple prices
        for i in range(5):
            mock_connector.get_price_by_type = AsyncMock(
                return_value=Decimal("1.0")
            )
            await calculator.update_coin_trend("XRP/EUR")
            time.sleep(0.3)

        trend = calculator.get_trend("XRP/EUR")

        # Old data should be cleaned up
        assert len(trend.price_history) < 5

    async def test_get_best_coin(self, trend_calculator, mock_connector):
        """Test finding best trending coin"""
        # Create trends for multiple coins
        coins = {
            "XRP/EUR": Decimal("1.0"),
            "ADA/EUR": Decimal("0.8"),
            "DOT/EUR": Decimal("10.0"),
        }

        # Simulate trends
        for symbol, start_price in coins.items():
            # Add multiple data points
            for i in range(65):  # More than 60 for sufficient data
                price = start_price * (Decimal("1.0") + Decimal(str(i * 0.001)))
                mock_connector.get_price_by_type = AsyncMock(return_value=price)
                await trend_calculator.update_coin_trend(symbol)

        best = trend_calculator.get_best_coin(min_trend_pct=0.0)

        assert best is not None
        assert best in coins.keys()

    async def test_insufficient_data(self, trend_calculator, mock_connector):
        """Test behavior with insufficient data"""
        # Add only 2 data points
        mock_connector.get_price_by_type = AsyncMock(return_value=Decimal("1.0"))
        await trend_calculator.update_coin_trend("XRP/EUR")
        await trend_calculator.update_coin_trend("XRP/EUR")

        # Should not select coin with insufficient data
        best = trend_calculator.get_best_coin(min_trend_pct=0.5)

        assert best is None

    async def test_error_handling(self, trend_calculator, mock_connector):
        """Test error handling during price fetch"""
        # Simulate API error
        mock_connector.get_price_by_type = AsyncMock(
            side_effect=Exception("API Error")
        )

        trend = await trend_calculator.update_coin_trend("XRP/EUR")

        # Should return None on error
        assert trend is None


class TestCoinTrend:
    """Test CoinTrend dataclass"""

    def test_has_sufficient_data(self):
        """Test sufficient data check"""
        trend = CoinTrend(
            symbol="XRP/EUR",
            current_price=Decimal("1.5"),
            trend_pct=2.5
        )

        # Not enough data
        assert not trend.has_sufficient_data

        # Add 60 data points
        trend.price_history = [
            {'price': Decimal("1.0"), 'timestamp': time.time()}
            for _ in range(60)
        ]

        # Now has sufficient data
        assert trend.has_sufficient_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
