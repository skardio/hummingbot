"""
Unit tests for Phase 1 Fix #1: Slippage Protection

Tests the _check_spread_acceptable() method that rejects entries with wide spreads.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestPhase1SlippageProtection(unittest.TestCase):
    """Test slippage protection (Phase 1 Fix #1)"""

    def setUp(self):
        """Set up test fixtures with simplified mocking"""
        # Create a mock controller with just the attributes we need
        self.controller = MagicMock()

        # Mock config
        self.controller.config = MagicMock()
        self.controller.config.quote_asset = "EUR"
        self.controller.config.use_dynamic_pair_discovery = False  # Ensure spread checks are enforced

        # Mock connector
        self.controller.connector = MagicMock()

        # Mock logger
        self.controller.logger = MagicMock()
        self.controller.logger.return_value = MagicMock()

        # Import the actual method we want to test
        from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController

        # Mock _is_trading_pair_tradeable to always return True
        self.controller._is_trading_pair_tradeable = MagicMock(return_value=True)

        # Bind the method to our mock (so 'self' works correctly)
        self.check_spread = MultiCoinGridController._check_spread_acceptable.__get__(
            self.controller, MultiCoinGridController)

    def test_spread_acceptable_tight_spread(self):
        """Test that tight spread (0.3%) is accepted"""
        # Setup: Order book with snapshot attribute (tuple of bids, asks)
        mock_order_book = MagicMock()
        mock_order_book.snapshot = (
            [[2.1990, 100]],  # bids
            [[2.2056, 100]]   # asks: 0.3% spread
        )
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = self.check_spread("XRP-EUR", max_spread_pct=0.5)

        # Verify
        self.assertTrue(result, "Tight spread should be accepted")

    def test_spread_rejected_wide_spread(self):
        """Test that wide spread (1.2%) is rejected"""
        # Setup: Wide spread
        mock_order_book = MagicMock()
        mock_order_book.snapshot = (
            [[2.1900, 100]],  # bids
            [[2.2163, 100]]   # asks: 1.2% spread
        )
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = self.check_spread("DOGE-EUR", max_spread_pct=0.5)

        # Verify
        self.assertFalse(result, "Wide spread should be rejected")

    def test_spread_boundary_exactly_at_limit(self):
        """Test spread exactly at limit (0.5%)"""
        # Setup: Exactly 0.5% spread
        mock_order_book = MagicMock()
        mock_order_book.snapshot = (
            [[2.2000, 100]],  # bids
            [[2.2110, 100]]   # asks: 0.5% spread
        )
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = self.check_spread("ADA-EUR", max_spread_pct=0.5)

        # Verify: Exactly at limit should pass (< or =)
        self.assertTrue(result, "Spread exactly at limit should be accepted")

    def test_spread_custom_threshold(self):
        """Test custom spread threshold (1.0%)"""
        # Setup: 0.8% spread
        mock_order_book = MagicMock()
        mock_order_book.snapshot = (
            [[1.0500, 100]],  # bids
            [[1.0584, 100]]   # asks: 0.8% spread
        )
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute with higher threshold
        result = self.check_spread("BCH-EUR", max_spread_pct=1.0)

        # Verify: Should pass with 1.0% threshold
        self.assertTrue(result, "0.8% spread should pass 1.0% threshold")

        # Execute with lower threshold
        result2 = self.check_spread("BCH-EUR", max_spread_pct=0.5)

        # Verify: Should fail with 0.5% threshold
        self.assertFalse(result2, "0.8% spread should fail 0.5% threshold")

    def test_spread_no_order_book(self):
        """Test handling when order book is None"""
        # Setup: No order book
        self.controller.connector.get_order_book.return_value = None

        # Execute
        result = self.check_spread("UNKNOWN-EUR")

        # Verify: Should reject (conservative approach)
        self.assertFalse(result, "Should reject when no order book")

    def test_spread_empty_order_book(self):
        """Test handling when order book snapshot is empty"""
        # Setup: Empty snapshot
        mock_order_book = MagicMock()
        mock_order_book.snapshot = ([], [])  # Empty bids/asks
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = self.check_spread("EMPTY-EUR")

        # Verify: Should reject
        self.assertFalse(result, "Should reject when order book empty")

    def test_spread_no_snapshot(self):
        """Test handling when order book has no snapshot"""
        # Setup: Order book without snapshot
        mock_order_book = MagicMock()
        mock_order_book.snapshot = None
        self.controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = self.check_spread("MALFORMED-EUR")

        # Verify: Should reject
        self.assertFalse(result, "Should reject when snapshot None")

    def test_spread_order_book_exception(self):
        """Test handling when get_order_book raises exception"""
        # Setup: Exception on order book fetch
        self.controller.connector.get_order_book.side_effect = Exception("API Error")

        # Execute
        result = self.check_spread("ERROR-EUR")

        # Verify: Should reject (conservative)
        self.assertFalse(result, "Should reject when order book fetch fails")

    def test_spread_different_price_ranges(self):
        """Test spread calculation works across different price ranges"""
        # Test 1: High price coin (€3000)
        mock_order_book1 = MagicMock()
        mock_order_book1.snapshot = ([[3000.0, 1]], [[3015.0, 1]])  # 0.5% spread
        self.controller.connector.get_order_book.return_value = mock_order_book1
        result1 = self.check_spread("ETH-EUR", max_spread_pct=0.5)
        self.assertTrue(result1, "Should work for high-price coins")

        # Test 2: Low price coin (€0.10)
        mock_order_book2 = MagicMock()
        mock_order_book2.snapshot = ([[0.1000, 1000]], [[0.1005, 1000]])  # 0.5% spread
        self.controller.connector.get_order_book.return_value = mock_order_book2
        result2 = self.check_spread("SHIB-EUR", max_spread_pct=0.5)
        self.assertTrue(result2, "Should work for low-price coins")

        # Test 3: Mid price coin (€2.20)
        mock_order_book3 = MagicMock()
        mock_order_book3.snapshot = ([[2.1990, 100]], [[2.2100, 100]])  # 0.5% spread
        self.controller.connector.get_order_book.return_value = mock_order_book3
        result3 = self.check_spread("XRP-EUR", max_spread_pct=0.5)
        self.assertTrue(result3, "Should work for mid-price coins")

    def test_spread_futures_bitget(self):
        """Test that slippage protection works for Bitget futures"""
        # Setup futures controller mock
        futures_controller = MagicMock()
        futures_controller.config = MagicMock()
        futures_controller.config.quote_asset = "USDT"
        futures_controller.config.use_dynamic_pair_discovery = False
        futures_controller.connector = MagicMock()
        futures_controller.logger = MagicMock()
        futures_controller.logger.return_value = MagicMock()
        futures_controller._is_trading_pair_tradeable = MagicMock(return_value=True)

        # Import and bind method
        from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
        check_spread_futures = MultiCoinGridController._check_spread_acceptable.__get__(
            futures_controller, MultiCoinGridController
        )

        # Setup: Tight spread for BTC perpetual
        mock_order_book = MagicMock()
        mock_order_book.snapshot = ([[43000.0, 10]], [[43200.0, 10]])  # ~0.46% spread
        futures_controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = check_spread_futures("BTC-USDT", max_spread_pct=0.5)

        # Verify
        self.assertTrue(result, "Should work for futures contracts")

    def test_spread_futures_wide_rejected(self):
        """Test that wide spreads are rejected for futures too"""
        # Setup futures controller
        futures_controller = MagicMock()
        futures_controller.config = MagicMock()
        futures_controller.config.quote_asset = "USDT"
        futures_controller.config.use_dynamic_pair_discovery = False
        futures_controller.connector = MagicMock()
        futures_controller.logger = MagicMock()
        futures_controller.logger.return_value = MagicMock()
        futures_controller._is_trading_pair_tradeable = MagicMock(return_value=True)

        from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
        check_spread_futures = MultiCoinGridController._check_spread_acceptable.__get__(
            futures_controller, MultiCoinGridController
        )

        # Setup: Wide spread
        mock_order_book = MagicMock()
        mock_order_book.snapshot = ([[43000.0, 10]], [[43800.0, 10]])  # ~1.86% spread
        futures_controller.connector.get_order_book.return_value = mock_order_book

        # Execute
        result = check_spread_futures("SHITCOIN-USDT", max_spread_pct=0.5)

        # Verify
        self.assertFalse(result, "Should reject wide spreads for futures")


if __name__ == "__main__":
    unittest.main()
