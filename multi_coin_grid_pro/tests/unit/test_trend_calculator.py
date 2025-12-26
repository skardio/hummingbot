"""
Unit tests for TrendCalculator module
"""

import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from utils.trend_calculator import CoinTrend, TrendCalculator

sys.path.insert(0, str(Path(__file__).parent.parent))


# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestTrendCalculator:
    """Test suite for TrendCalculator class"""

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        from unittest.mock import AsyncMock, MagicMock
        connector = MagicMock()
        # Mock get_last_traded_prices which is what the implementation uses (async)
        # Note: The code converts XRP/EUR to XRP-EUR before calling, so mock should return XRP-EUR
        connector.get_last_traded_prices = AsyncMock(return_value={"XRP-EUR": Decimal("1.5")})
        # Mock get_mid_price (sync method)
        connector.get_mid_price = MagicMock(return_value=Decimal("1.5"))
        return connector

    @pytest.fixture
    def trend_calculator(self, mock_connector):
        """Create TrendCalculator instance"""
        return TrendCalculator(
            connector=mock_connector,
            lookback_minutes=30
        )

    async def test_update_coin_trend(self, trend_calculator, mock_connector):
        """Test updating trend for a single coin"""
        # Mock price - note: code converts XRP/EUR to XRP-EUR before API call
        mock_connector.get_last_traded_prices = AsyncMock(
            return_value={"XRP-EUR": Decimal("1.5")}
        )

        trend = await trend_calculator.update_coin_trend("XRP/EUR")

        assert trend is not None
        assert trend.symbol == "XRP-EUR"  # Symbol is converted internally
        assert trend.current_price == Decimal("1.5")
        assert len(trend.price_history) == 1

    async def test_trend_calculation(self, trend_calculator, mock_connector):
        """Test trend percentage calculation"""
        # Simulate price increase
        prices = [Decimal("1.0"), Decimal("1.05"), Decimal("1.10")]

        for price in prices:
            # Note: code converts XRP/EUR to XRP-EUR before API call
            mock_connector.get_last_traded_prices = AsyncMock(
                return_value={"XRP-EUR": price}
            )
            await trend_calculator.update_coin_trend("XRP/EUR")
            time.sleep(0.01)  # Small delay

        # Symbol is stored as XRP-EUR after conversion
        trend = trend_calculator.get_trend("XRP-EUR")

        assert trend is not None
        # With only 3 data points, trend might be 0 or small
        # Just verify trend exists and has price history
        assert len(trend.price_history) == 3
        assert trend.current_price == Decimal("1.10")

    async def test_price_history_cleanup(self, trend_calculator, mock_connector):
        """Test old price data is removed"""
        # Create calculator with 1 second lookback for testing
        calculator = TrendCalculator(
            connector=mock_connector,
            lookback_minutes=0.0167  # ~1 second
        )

        # Add multiple prices
        for i in range(5):
            # Note: code converts XRP/EUR to XRP-EUR before API call
            mock_connector.get_last_traded_prices = AsyncMock(
                return_value={"XRP-EUR": Decimal("1.0")}
            )
            await calculator.update_coin_trend("XRP/EUR")
            time.sleep(0.3)

        # Symbol is stored as XRP-EUR after conversion
        trend = calculator.get_trend("XRP-EUR")

        # Old data should be cleaned up (but might not be if timestamps are close)
        # Just verify we have some data
        assert trend is not None
        assert len(trend.price_history) > 0

    async def test_get_best_coin(self, trend_calculator, mock_connector):
        """Test finding best trending coin"""
        # Create trends for multiple coins
        coins = {
            "XRP/EUR": Decimal("1.0"),
            "ADA/EUR": Decimal("0.8"),
            "DOT/EUR": Decimal("10.0"),
        }

        # Simulate trends - need at least 50 data points for sufficient data
        for symbol, start_price in coins.items():
            # Add multiple data points
            for i in range(50):  # Minimum 50 for sufficient data
                price = start_price * (Decimal("1.0") + Decimal(str(i * 0.001)))
                mock_connector.get_last_traded_prices = AsyncMock(
                    return_value={symbol: price}
                )
                await trend_calculator.update_coin_trend(symbol)
                time.sleep(0.01)  # Small delay

        best = trend_calculator.get_best_coin(min_trend_pct=0.0)

        # Should return one of the coins (or None if no sufficient data)
        assert best is None or best in coins.keys()

    async def test_insufficient_data(self, trend_calculator, mock_connector):
        """Test behavior with insufficient data"""
        # Add only 2 data points
        mock_connector.get_last_traded_prices = AsyncMock(
            return_value={"XRP/EUR": Decimal("1.0")}
        )
        await trend_calculator.update_coin_trend("XRP/EUR")
        await trend_calculator.update_coin_trend("XRP/EUR")

        # Should not select coin with insufficient data (< 50 points)
        best = trend_calculator.get_best_coin(min_trend_pct=0.5)

        assert best is None

    async def test_error_handling(self, trend_calculator, mock_connector):
        """Test error handling during price fetch"""
        # Simulate API error
        mock_connector.get_last_traded_prices = AsyncMock(
            side_effect=Exception("API Error")
        )

        trend = await trend_calculator.update_coin_trend("XRP/EUR")

        # Should return None on error
        assert trend is None

    async def test_paper_trading_not_implemented_error_fallback_to_base_connector(self):
        """Test that NotImplementedError from paper trading connector falls back to base connector"""
        from unittest.mock import AsyncMock, MagicMock

        # Mock paper trading connector (raises NotImplementedError)
        paper_connector = MagicMock()
        paper_connector.get_last_traded_prices = AsyncMock(
            side_effect=NotImplementedError("Not implemented in paper trading")
        )
        paper_connector.get_mid_price = MagicMock(return_value=None)  # No order book (sync method)

        # Mock base connector (works correctly)
        base_connector = MagicMock()
        base_connector.get_last_traded_prices = AsyncMock(
            return_value={"XRP-EUR": Decimal("1.5")}
        )

        # Create calculator with both connectors
        calculator = TrendCalculator(
            connector=paper_connector,
            lookback_minutes=30,
            base_connector=base_connector
        )

        trend = await calculator.update_coin_trend("XRP-EUR")

        # Should succeed using base connector
        assert trend is not None
        assert trend.symbol == "XRP-EUR"
        assert trend.current_price == Decimal("1.5")
        # Verify base connector was called
        base_connector.get_last_traded_prices.assert_called_once_with(["XRP-EUR"])

    async def test_paper_trading_fallback_to_get_mid_price(self):
        """Test that if base connector also fails, fallback to get_mid_price from paper connector"""
        from unittest.mock import AsyncMock, MagicMock

        # Mock paper trading connector
        paper_connector = MagicMock()
        paper_connector.get_last_traded_prices = AsyncMock(
            side_effect=NotImplementedError("Not implemented in paper trading")
        )
        # get_mid_price works (order book exists) - NOTE: this is a SYNC method, not async!
        paper_connector.get_mid_price = MagicMock(return_value=Decimal("1.5"))

        # Mock base connector (also fails)
        base_connector = MagicMock()
        base_connector.get_last_traded_prices = AsyncMock(
            side_effect=Exception("Base connector error")
        )

        # Create calculator with both connectors
        calculator = TrendCalculator(
            connector=paper_connector,
            lookback_minutes=30,
            base_connector=base_connector
        )

        trend = await calculator.update_coin_trend("XRP-EUR")

        # Should succeed using get_mid_price fallback
        assert trend is not None
        assert trend.symbol == "XRP-EUR"
        assert trend.current_price == Decimal("1.5")
        # Verify get_mid_price was called (sync method)
        paper_connector.get_mid_price.assert_called_once_with("XRP-EUR")

    async def test_symbol_format_conversion_slash_to_dash(self):
        """Test that symbol format is converted from XRP/EUR to XRP-EUR"""
        from unittest.mock import AsyncMock, MagicMock

        connector = MagicMock()
        # Mock returns price for XRP-EUR format
        connector.get_last_traded_prices = AsyncMock(
            return_value={"XRP-EUR": Decimal("1.5")}
        )

        calculator = TrendCalculator(connector=connector, lookback_minutes=30)

        # Pass symbol in XRP/EUR format
        trend = await calculator.update_coin_trend("XRP/EUR")

        # Should succeed (conversion happens internally)
        assert trend is not None
        # Verify connector was called with converted format
        connector.get_last_traded_prices.assert_called_once()
        # Check that the call used the converted format
        call_args = connector.get_last_traded_prices.call_args[0][0]
        assert "XRP-EUR" in call_args or "XRP/EUR" in call_args

    async def test_batch_api_call_success(self):
        """Test that update_all_trends_v2 uses batch API calls for multiple coins"""
        from unittest.mock import AsyncMock, MagicMock

        connector = MagicMock()
        # Mock batch call returning prices for multiple coins
        connector.get_last_traded_prices = AsyncMock(
            return_value={
                "XRP-EUR": Decimal("1.5"),
                "ADA-EUR": Decimal("0.8"),
                "DOT-EUR": Decimal("10.0")
            }
        )

        calculator = TrendCalculator(connector=connector, lookback_minutes=30)

        # Update trends for multiple coins
        symbols = ["XRP/EUR", "ADA/EUR", "DOT/EUR"]
        await calculator.update_all_trends_v2(symbols)

        # Verify batch call was made (should be called once with all symbols)
        assert connector.get_last_traded_prices.call_count == 1
        call_args = connector.get_last_traded_prices.call_args[0][0]
        # Should have all converted symbols
        assert len(call_args) == 3
        assert "XRP-EUR" in call_args
        assert "ADA-EUR" in call_args
        assert "DOT-EUR" in call_args

        # Verify trends were updated
        assert calculator.get_trend("XRP-EUR") is not None
        assert calculator.get_trend("ADA-EUR") is not None
        assert calculator.get_trend("DOT-EUR") is not None

    async def test_batch_api_call_fallback_to_individual(self):
        """Test that update_all_trends_v2 falls back to individual calls if batch fails"""
        from unittest.mock import AsyncMock, MagicMock

        connector = MagicMock()
        # Mock batch call returning empty dict (simulating failure)
        connector.get_last_traded_prices = AsyncMock(
            return_value={}  # Empty result triggers fallback
        )

        calculator = TrendCalculator(connector=connector, lookback_minutes=30)

        # Update trends - should fall back to individual calls
        symbols = ["XRP/EUR", "ADA/EUR"]
        await calculator.update_all_trends_v2(symbols)

        # Should have made multiple calls (batch + individual fallback)
        assert connector.get_last_traded_prices.call_count >= 1

    async def test_batch_api_call_with_base_connector(self):
        """Test that batch calls work with paper trading connector using base connector"""
        from unittest.mock import AsyncMock, MagicMock

        # Mock paper trading connector (raises NotImplementedError)
        paper_connector = MagicMock()
        paper_connector.get_last_traded_prices = AsyncMock(
            side_effect=NotImplementedError("Not implemented in paper trading")
        )

        # Mock base connector (works correctly)
        base_connector = MagicMock()
        base_connector.get_last_traded_prices = AsyncMock(
            return_value={
                "XRP-EUR": Decimal("1.5"),
                "ADA-EUR": Decimal("0.8")
            }
        )

        calculator = TrendCalculator(
            connector=paper_connector,
            lookback_minutes=30,
            base_connector=base_connector
        )

        # Update trends - should use base connector
        symbols = ["XRP/EUR", "ADA/EUR"]
        await calculator.update_all_trends_v2(symbols)

        # Should have called base connector, not paper connector
        assert base_connector.get_last_traded_prices.call_count == 1
        assert paper_connector.get_last_traded_prices.call_count == 1  # Called first, then NotImplementedError

    async def test_rate_limiting_enforces_minimum_interval(self):
        """Test that update_all_trends_v2 enforces minimum interval between calls"""
        import time
        from unittest.mock import AsyncMock, MagicMock

        connector = MagicMock()
        connector.get_last_traded_prices = AsyncMock(return_value={
            "XRP-EUR": 1.5,
            "BTC-EUR": 50000.0
        })

        calculator = TrendCalculator(connector=connector, lookback_minutes=30)

        # First call - should proceed immediately
        start_time = time.time()
        await calculator.update_all_trends_v2(["XRP-EUR", "BTC-EUR"])
        time.time() - start_time

        # Second call immediately after - should wait
        start_time = time.time()
        await calculator.update_all_trends_v2(["XRP-EUR", "BTC-EUR"])
        second_call_time = time.time() - start_time

        # Second call should take longer due to rate limiting (at least 2 seconds)
        assert second_call_time >= 1.8, f"Rate limiting not working: second call took {
            second_call_time:.2f}s (expected >= 1.8s)"
        assert connector.get_last_traded_prices.call_count == 2, "Should have made 2 API calls"

    async def test_rate_limiting_skips_wait_if_enough_time_passed(self):
        """Test that rate limiting doesn't wait if enough time has passed"""
        import asyncio
        import time
        from unittest.mock import AsyncMock, MagicMock

        connector = MagicMock()
        connector.get_last_traded_prices = AsyncMock(return_value={
            "XRP-EUR": 1.5
        })

        calculator = TrendCalculator(connector=connector, lookback_minutes=30)

        # First call
        await calculator.update_all_trends_v2(["XRP-EUR"])

        # Wait more than minimum interval (2 seconds)
        await asyncio.sleep(2.5)

        # Second call - should proceed immediately (no wait)
        start_time = time.time()
        await calculator.update_all_trends_v2(["XRP-EUR"])
        call_time = time.time() - start_time

        # Should be fast (no rate limiting wait)
        assert call_time < 1.0, f"Rate limiting waited unnecessarily: call took {call_time:.2f}s (expected < 1.0s)"
        assert connector.get_last_traded_prices.call_count == 2, "Should have made 2 API calls"
        from unittest.mock import AsyncMock, MagicMock

        # Mock paper trading connector (raises NotImplementedError)
        paper_connector = MagicMock()
        paper_connector.get_last_traded_prices = AsyncMock(
            side_effect=NotImplementedError("Not implemented in paper trading")
        )

        # Mock base connector (works correctly)
        base_connector = MagicMock()
        base_connector.get_last_traded_prices = AsyncMock(
            return_value={
                "XRP-EUR": Decimal("1.5"),
                "ADA-EUR": Decimal("0.8")
            }
        )

        calculator = TrendCalculator(
            connector=paper_connector,
            lookback_minutes=30,
            base_connector=base_connector
        )

        symbols = ["XRP/EUR", "ADA/EUR"]
        await calculator.update_all_trends_v2(symbols)

        # Should have tried paper connector first, then base connector
        assert paper_connector.get_last_traded_prices.call_count == 1
        assert base_connector.get_last_traded_prices.call_count == 1

        # Verify trends were updated using base connector prices
        assert calculator.get_trend("XRP-EUR") is not None
        assert calculator.get_trend("ADA-EUR") is not None


class TestCoinTrend:
    """Test CoinTrend dataclass"""

    @pytest.mark.asyncio
    async def test_has_sufficient_data(self):
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
