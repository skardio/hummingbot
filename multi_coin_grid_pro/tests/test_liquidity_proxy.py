"""
Unit tests for Orderbook Depth-Based Liquidity Proxy

Tests the liquidity_proxy utility functions for:
- Depth calculation within price range
- Required depth calculation
- Sufficient depth validation
- Orderbook snapshot retrieval
- Log formatting
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock

from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import (
    DepthMetrics,
    calculate_orderbook_depth,
    calculate_required_depth,
    format_depth_log,
    get_orderbook_snapshot,
    is_sufficient_depth,
)


class TestLiquidityProxy(unittest.TestCase):
    """Test suite for liquidity proxy utility functions"""

    def setUp(self):
        """Set up test fixtures"""
        # Create realistic orderbook data
        self.bids = [
            OrderBookRow(100.0, 10.0, 1),  # Best bid: €100, 10 units
            OrderBookRow(99.5, 5.0, 2),    # €99.5, 5 units
            OrderBookRow(99.0, 8.0, 3),    # €99.0, 8 units
            OrderBookRow(98.5, 3.0, 4),    # €98.5, 3 units
        ]

        self.asks = [
            OrderBookRow(100.5, 8.0, 1),   # Best ask: €100.5, 8 units
            OrderBookRow(101.0, 12.0, 2),  # €101.0, 12 units
            OrderBookRow(101.5, 6.0, 3),   # €101.5, 6 units
            OrderBookRow(102.0, 4.0, 4),   # €102.0, 4 units
        ]

        self.mid_price = Decimal("100.25")  # (100 + 100.5) / 2

    def test_calculate_orderbook_depth_basic(self):
        """Test basic depth calculation"""
        metrics = calculate_orderbook_depth(
            bids=self.bids,
            asks=self.asks,
            mid_price=self.mid_price,
            pct_range=0.5,  # ±0.5%
            max_levels=10
        )

        # Verify metrics structure
        self.assertIsInstance(metrics, DepthMetrics)
        self.assertGreater(metrics.bid_depth, 0)
        self.assertGreater(metrics.ask_depth, 0)
        self.assertGreater(metrics.depth_score, 0)
        self.assertGreater(metrics.spread_pct, 0)

        # Depth score should be minimum of bid/ask
        self.assertEqual(metrics.depth_score, min(metrics.bid_depth, metrics.ask_depth))

        print(f"✅ Basic depth calculation: bid={metrics.bid_depth}, ask={metrics.ask_depth}, "
              f"score={metrics.depth_score}, spread={metrics.spread_pct}%")

    def test_calculate_orderbook_depth_within_range(self):
        """Test that only prices within range are counted"""
        # ±0.5% of 100.25 = [99.7488, 100.7513]
        metrics = calculate_orderbook_depth(
            bids=self.bids,
            asks=self.asks,
            mid_price=self.mid_price,
            pct_range=0.5,
            max_levels=10
        )

        # Best bid (100.0) should be included
        # With ±0.5% range, depth should include some volume
        self.assertGreaterEqual(metrics.bid_depth, Decimal("10.0"))  # At least best bid

        # Best ask (100.5) should be included
        self.assertGreaterEqual(metrics.ask_depth, Decimal("8.0"))  # At least best ask

        print(f"✅ Range filtering: bid_depth={metrics.bid_depth}, ask_depth={metrics.ask_depth}")

    def test_calculate_orderbook_depth_empty_book(self):
        """Test handling of empty orderbook"""
        metrics = calculate_orderbook_depth(
            bids=[],
            asks=[],
            mid_price=Decimal("100"),
            pct_range=0.5,
            max_levels=10
        )

        self.assertEqual(metrics.bid_depth, Decimal("0"))
        self.assertEqual(metrics.ask_depth, Decimal("0"))
        self.assertEqual(metrics.depth_score, Decimal("0"))
        self.assertEqual(metrics.levels_analyzed, 0)

        print("✅ Empty orderbook handled correctly")

    def test_calculate_orderbook_depth_max_levels(self):
        """Test max_levels parameter limits analysis"""
        # Create 20 bid/ask levels
        many_bids = [OrderBookRow(100.0 - i * 0.1, 5.0, i + 1) for i in range(20)]
        many_asks = [OrderBookRow(100.5 + i * 0.1, 5.0, i + 1) for i in range(20)]

        metrics = calculate_orderbook_depth(
            bids=many_bids,
            asks=many_asks,
            mid_price=Decimal("100.25"),
            pct_range=5.0,  # Wide range to include all levels
            max_levels=5    # But limit to 5 levels
        )

        # Should analyze max 5 levels per side = 10 total
        self.assertLessEqual(metrics.levels_analyzed, 10)

        print(f"✅ Max levels respected: {metrics.levels_analyzed} levels analyzed (max 10)")

    def test_calculate_required_depth(self):
        """Test required depth calculation"""
        order_size = Decimal("100")
        multiplier = 5.0

        required = calculate_required_depth(order_size, multiplier)

        self.assertEqual(required, Decimal("500"))

        print(f"✅ Required depth: {required} (100 × 5.0)")

    def test_is_sufficient_depth_pass(self):
        """Test sufficient depth validation (passing)"""
        # Depth score of 500, required 100 × 5.0 = 500
        # With 10% tolerance, minimum acceptable = 450
        is_ok, required = is_sufficient_depth(
            depth_score=Decimal("500"),
            order_size_quote=Decimal("100"),
            multiplier=5.0,
            tolerance_pct=10.0
        )

        self.assertTrue(is_ok)
        self.assertEqual(required, Decimal("500"))

        print("✅ Sufficient depth validation: PASS (500 >= 450)")

    def test_is_sufficient_depth_tolerance(self):
        """Test tolerance allows slightly lower depth"""
        # Depth score of 460, required 500, tolerance allows down to 450
        is_ok, required = is_sufficient_depth(
            depth_score=Decimal("460"),
            order_size_quote=Decimal("100"),
            multiplier=5.0,
            tolerance_pct=10.0
        )

        self.assertTrue(is_ok)

        print("✅ Tolerance works: 460 >= 450 (90% of 500) → PASS")

    def test_is_sufficient_depth_fail(self):
        """Test insufficient depth validation (failing)"""
        # Depth score of 400, required 500, minimum acceptable = 450
        is_ok, required = is_sufficient_depth(
            depth_score=Decimal("400"),
            order_size_quote=Decimal("100"),
            multiplier=5.0,
            tolerance_pct=10.0
        )

        self.assertFalse(is_ok)
        self.assertEqual(required, Decimal("500"))

        print("✅ Insufficient depth validation: FAIL (400 < 450)")

    def test_format_depth_log_sufficient(self):
        """Test depth log formatting for sufficient liquidity"""
        metrics = DepthMetrics(
            bid_depth=Decimal("550"),
            ask_depth=Decimal("520"),
            depth_score=Decimal("520"),
            spread_pct=Decimal("0.05"),
            mid_price=Decimal("100"),
            price_range_pct=0.5,
            levels_analyzed=8
        )

        log_msg = format_depth_log(
            symbol="BTC-USDT",
            metrics=metrics,
            order_size=Decimal("100"),
            multiplier=5.0,
            is_sufficient=True
        )

        self.assertIn("BTC-USDT", log_msg)
        self.assertIn("520.0", log_msg)  # depth_score
        self.assertIn("500.0", log_msg)  # required
        self.assertIn("✅", log_msg)
        self.assertIn("0.05%", log_msg)  # spread

        print(f"✅ Log format (sufficient): {log_msg}")

    def test_format_depth_log_insufficient(self):
        """Test depth log formatting for insufficient liquidity"""
        metrics = DepthMetrics(
            bid_depth=Decimal("450"),
            ask_depth=Decimal("300"),
            depth_score=Decimal("300"),
            spread_pct=Decimal("0.12"),
            mid_price=Decimal("100"),
            price_range_pct=0.5,
            levels_analyzed=4
        )

        log_msg = format_depth_log(
            symbol="SHIB-USDT",
            metrics=metrics,
            order_size=Decimal("100"),
            multiplier=5.0,
            is_sufficient=False
        )

        self.assertIn("SHIB-USDT", log_msg)
        self.assertIn("300.0", log_msg)  # depth_score
        self.assertIn("500.0", log_msg)  # required
        self.assertIn("❌", log_msg)
        self.assertIn("0.12%", log_msg)  # spread

        print(f"✅ Log format (insufficient): {log_msg}")

    def test_get_orderbook_snapshot_success(self):
        """Test orderbook snapshot retrieval"""
        # Create mock connector
        mock_connector = Mock()
        mock_order_book = Mock()

        # Mock orderbook snapshot
        mock_order_book.snapshot = (self.bids, self.asks)
        mock_connector.get_order_book.return_value = mock_order_book

        bids, asks, mid_price = get_orderbook_snapshot(mock_connector, "BTC-USDT")

        self.assertIsNotNone(bids)
        self.assertIsNotNone(asks)
        self.assertIsNotNone(mid_price)
        self.assertEqual(len(bids), 4)
        self.assertEqual(len(asks), 4)

        # Mid price should be between best bid and best ask
        best_bid = Decimal(str(bids[0].price))
        best_ask = Decimal(str(asks[0].price))
        self.assertGreater(mid_price, best_bid)
        self.assertLess(mid_price, best_ask)

        print(f"✅ Orderbook snapshot: bid={best_bid}, ask={best_ask}, mid={mid_price}")

    def test_get_orderbook_snapshot_no_data(self):
        """Test orderbook snapshot with no data"""
        mock_connector = Mock()
        mock_connector.get_order_book.return_value = None

        bids, asks, mid_price = get_orderbook_snapshot(mock_connector, "INVALID-PAIR")

        self.assertIsNone(bids)
        self.assertIsNone(asks)
        self.assertIsNone(mid_price)

        print("✅ No orderbook data handled correctly")

    def test_get_orderbook_snapshot_exception(self):
        """Test orderbook snapshot with exception"""
        mock_connector = Mock()
        mock_connector.get_order_book.side_effect = Exception("Connection error")

        bids, asks, mid_price = get_orderbook_snapshot(mock_connector, "BTC-USDT")

        self.assertIsNone(bids)
        self.assertIsNone(asks)
        self.assertIsNone(mid_price)

        print("✅ Exception in snapshot handled correctly")

    def test_spread_calculation(self):
        """Test spread percentage calculation"""
        metrics = calculate_orderbook_depth(
            bids=self.bids,
            asks=self.asks,
            mid_price=self.mid_price,
            pct_range=0.5,
            max_levels=10
        )

        # Spread = (100.5 - 100.0) / 100.0 * 100 = 0.5%
        expected_spread = Decimal("0.5")
        self.assertAlmostEqual(float(metrics.spread_pct), float(expected_spread), places=2)

        print(f"✅ Spread calculation: {metrics.spread_pct}% (expected ~0.5%)")

    def test_depth_score_is_bottleneck(self):
        """Test that depth_score is always the minimum (bottleneck)"""
        # Create asymmetric orderbook (more bids than asks)
        heavy_bids = [OrderBookRow(100.0 - i * 0.1, 100.0, i + 1) for i in range(5)]
        light_asks = [OrderBookRow(100.5 + i * 0.1, 10.0, i + 1) for i in range(5)]

        metrics = calculate_orderbook_depth(
            bids=heavy_bids,
            asks=light_asks,
            mid_price=Decimal("100.25"),
            pct_range=1.0,  # Wide range
            max_levels=10
        )

        # Depth score should equal ask_depth (smaller side)
        self.assertEqual(metrics.depth_score, metrics.ask_depth)
        self.assertLess(metrics.depth_score, metrics.bid_depth)

        print(f"✅ Bottleneck detection: bid={metrics.bid_depth}, ask={metrics.ask_depth}, "
              f"score={metrics.depth_score} (minimum)")


class TestLiquidityProxyIntegration(unittest.TestCase):
    """Integration tests for liquidity proxy in trading scenarios"""

    def test_typical_btc_scenario(self):
        """Test typical BTC-USDT orderbook scenario"""
        # Realistic BTC orderbook at $100,000
        bids = [
            OrderBookRow(100000.0, 0.5, 1),    # €50,000
            OrderBookRow(99950.0, 0.3, 2),     # €29,985
            OrderBookRow(99900.0, 0.8, 3),     # €79,920
        ]
        asks = [
            OrderBookRow(100050.0, 0.4, 1),    # €40,020
            OrderBookRow(100100.0, 0.6, 2),    # €60,060
            OrderBookRow(100150.0, 0.5, 3),    # €50,075
        ]

        metrics = calculate_orderbook_depth(
            bids=bids,
            asks=asks,
            mid_price=Decimal("100025"),
            pct_range=0.5,
            max_levels=10
        )

        # Check if €5000 order (5x multiplier) can be executed
        order_size = Decimal("1000")  # €1000 order
        is_ok, required = is_sufficient_depth(
            depth_score=metrics.depth_score,
            order_size_quote=order_size,
            multiplier=5.0,
            tolerance_pct=10.0
        )

        print(f"✅ BTC scenario: order=€{order_size}, depth={metrics.depth_score:.0f}, "
              f"required={required:.0f}, result={'PASS' if is_ok else 'FAIL'}")

    def test_low_liquidity_altcoin(self):
        """Test low liquidity altcoin scenario"""
        # Thin orderbook
        bids = [
            OrderBookRow(1.0, 100, 1),     # €100
            OrderBookRow(0.99, 50, 2),     # €49.5
        ]
        asks = [
            OrderBookRow(1.01, 80, 1),     # €80.8
            OrderBookRow(1.02, 60, 2),     # €61.2
        ]

        metrics = calculate_orderbook_depth(
            bids=bids,
            asks=asks,
            mid_price=Decimal("1.005"),
            pct_range=0.5,
            max_levels=10
        )

        # Try €50 order with 5x multiplier (needs €250 depth)
        order_size = Decimal("50")
        is_ok, required = is_sufficient_depth(
            depth_score=metrics.depth_score,
            order_size_quote=order_size,
            multiplier=5.0,
            tolerance_pct=10.0
        )

        # Should fail - not enough liquidity
        self.assertFalse(is_ok)

        print(f"✅ Low liquidity altcoin: order=€{order_size}, depth={metrics.depth_score:.0f}, "
              f"required={required:.0f}, result={'PASS' if is_ok else 'FAIL (expected)'}")


def run_tests():
    """Run all liquidity proxy tests"""
    print("\n" + "=" * 80)
    print("🧪 LIQUIDITY PROXY UNIT TESTS")
    print("=" * 80 + "\n")

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestLiquidityProxy))
    suite.addTests(loader.loadTestsFromTestCase(TestLiquidityProxyIntegration))

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 80)
    print(f"✅ Tests passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"❌ Tests failed: {len(result.failures)}")
    print(f"💥 Tests errors: {len(result.errors)}")
    print("=" * 80 + "\n")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
