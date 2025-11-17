"""
Unit tests for CoinDiscovery module
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.coin_discovery import CoinDiscovery

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestCoinDiscovery:
    """Test suite for CoinDiscovery class"""

    @pytest_asyncio.fixture
    async def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.get_all_trading_pairs = AsyncMock(return_value=[
            "XRP/EUR", "ADA/EUR", "DOT/EUR", "SOL/EUR", "LINK/EUR",
            "BTC/EUR", "ETH/EUR", "MATIC/EUR"
        ])
        return connector

    @pytest_asyncio.fixture
    async def coin_discovery(self, mock_connector):
        """Create CoinDiscovery instance"""
        return CoinDiscovery(
            connector=mock_connector,
            quote_asset="EUR",
            min_24h_volume=Decimal("50000"),
            max_coins=5,
            exclude_expensive=True
        )

    async def test_discover_coins_basic(self, coin_discovery, mock_connector):
        """Test basic coin discovery"""
        # Mock price and volume data
        mock_connector.get_quote_volume_for_base_amount = AsyncMock(
            return_value=Decimal("100000")
        )
        mock_connector.get_price_by_type = AsyncMock(
            side_effect=[
                Decimal("1.5"),   # XRP
                Decimal("0.8"),   # ADA
                Decimal("10.2"),  # DOT
                Decimal("150.0"),  # SOL
                Decimal("18.5"),  # LINK
            ]
        )

        coins = await coin_discovery.discover_coins()

        # Should return up to 5 coins
        assert len(coins) <= 5
        assert all("EUR" in coin for coin in coins)

    async def test_exclude_expensive_coins(self, coin_discovery, mock_connector):
        """Test that BTC/ETH are excluded"""
        mock_connector.get_quote_volume_for_base_amount = AsyncMock(
            return_value=Decimal("100000")
        )
        mock_connector.get_price_by_type = AsyncMock(
            return_value=Decimal("100")
        )

        coins = await coin_discovery.discover_coins()

        # BTC and ETH should not be in results
        assert "BTC/EUR" not in coins
        assert "ETH/EUR" not in coins

    async def test_volume_filtering(self, mock_connector):
        """Test volume-based filtering"""
        # High volume threshold
        discovery = CoinDiscovery(
            connector=mock_connector,
            quote_asset="EUR",
            min_24h_volume=Decimal("1000000"),  # High threshold
            max_coins=20,
            exclude_expensive=False
        )

        # Mock low volume
        mock_connector.get_quote_volume_for_base_amount = AsyncMock(
            return_value=Decimal("50000")  # Below threshold
        )
        mock_connector.get_price_by_type = AsyncMock(
            return_value=Decimal("1.0")
        )

        coins = await discovery.discover_coins()

        # Should fallback to default list
        assert len(coins) > 0

    async def test_error_handling(self, mock_connector):
        """Test error handling and fallback"""
        # Simulate API error
        mock_connector.get_all_trading_pairs = AsyncMock(
            side_effect=Exception("API Error")
        )

        discovery = CoinDiscovery(
            connector=mock_connector,
            quote_asset="EUR",
            min_24h_volume=Decimal("50000"),
            max_coins=5,
            exclude_expensive=True
        )

        coins = await discovery.discover_coins()

        # Should return fallback list
        assert len(coins) > 0
        assert all("EUR" in coin for coin in coins)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
