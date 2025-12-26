"""
Unit tests for TrendCalculator orderbook depth filtering

Tests the integration of liquidity_proxy depth filtering into TrendCalculator's
coin selection methods (get_best_coin and get_top_n_coins).
"""

import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.order_book_row import OrderBookRow

# Import TrendCalculator
try:
    from hummingbot.multi_coin_grid_utils.trend_calculator import CoinTrend, TrendCalculator
    TREND_CALCULATOR_AVAILABLE = True
except ImportError:
    try:
        from multi_coin_grid_pro.utils.trend_calculator import CoinTrend, TrendCalculator
        TREND_CALCULATOR_AVAILABLE = True
    except ImportError:
        TREND_CALCULATOR_AVAILABLE = False

# Import liquidity proxy
try:
    from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import DepthMetrics
    LIQUIDITY_PROXY_AVAILABLE = True
except ImportError:
    LIQUIDITY_PROXY_AVAILABLE = False


@unittest.skipUnless(TREND_CALCULATOR_AVAILABLE and LIQUIDITY_PROXY_AVAILABLE,
                     "TrendCalculator or liquidity_proxy not available")
class TestTrendCalculatorDepthFiltering(unittest.TestCase):
    """Test orderbook depth filtering in TrendCalculator"""

    def setUp(self):
        """Set up test fixtures"""
        self.connector = Mock(spec=ConnectorBase)
        self.connector.name = "kraken"

        # Create TrendCalculator instance
        self.trend_calculator = TrendCalculator(
            connector=self.connector,
            lookback_minutes=60,
        )

        # Add mock coins with trends
        self.trend_calculator.trends = {
            "BTC-EUR": self._create_mock_trend("BTC-EUR", trend_pct=8.5, consensus=8.5),
            "ETH-EUR": self._create_mock_trend("ETH-EUR", trend_pct=7.2, consensus=7.2),
            "SHIB-EUR": self._create_mock_trend("SHIB-EUR", trend_pct=12.0, consensus=12.0),  # High trend but illiquid
            "SOL-EUR": self._create_mock_trend("SOL-EUR", trend_pct=6.8, consensus=6.8),
        }

        # Mock orderbook config (100 EUR order size, 5× multiplier = 500 EUR required)
        self.orderbook_config = {
            'enabled': True,
            'depth_pct_range': 0.5,
            'depth_levels': 10,
            'min_depth_multiplier': 5.0,
            'order_size': Decimal("100"),
        }

    def _create_mock_trend(self, symbol: str, trend_pct: float, consensus: float) -> CoinTrend:
        """Create a mock CoinTrend with sufficient data"""
        trend = CoinTrend(symbol=symbol)
        # Set internal attribute directly (has_sufficient_data is a @property)
        trend._has_sufficient_data = True
        trend.trend_pct = trend_pct
        trend.consensus_trend_pct = consensus
        # Add enough price history to pass warmup
        trend.price_history = [Decimal("100")] * 100
        return trend

    def _create_mock_orderbook(self, symbol: str, bid_depth: float, ask_depth: float):
        """Create a mock orderbook with specified depth"""
        orderbook = Mock()
        orderbook.snapshot_uid = "test_snapshot"

        # Create bid/ask lists
        mid_price = Decimal("1000")
        orderbook.bids = [
            OrderBookRow(price=mid_price * Decimal("0.999"), amount=Decimal(str(bid_depth)), update_id=1)
        ]
        orderbook.asks = [
            OrderBookRow(price=mid_price * Decimal("1.001"), amount=Decimal(str(ask_depth)), update_id=1)
        ]

        return orderbook

    def _create_mock_depth_metrics(self, bid_depth: float, ask_depth: float):
        """Create mock DepthMetrics"""
        return DepthMetrics(
            bid_depth=Decimal(str(bid_depth)),
            ask_depth=Decimal(str(ask_depth)),
            depth_score=Decimal(str(min(bid_depth, ask_depth))),
            spread_pct=Decimal("0.05"),
            mid_price=Decimal("1000"),
            price_range_pct=0.5,
            levels_analyzed=10,
        )

    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.get_orderbook_snapshot')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_orderbook_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_required_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.is_sufficient_depth')
    def test_get_best_coin_with_depth_filtering_all_liquid(
        self, mock_is_sufficient, mock_calc_required, mock_calc_depth, mock_get_orderbook
    ):
        """Test get_best_coin with depth filtering when all coins are liquid"""

        # Mock all coins as liquid (sufficient depth)
        mock_get_orderbook.side_effect = lambda conn, symbol: self._create_mock_orderbook(symbol, 5000, 5000)
        mock_calc_depth.side_effect = lambda **kwargs: self._create_mock_depth_metrics(5000, 5000)
        mock_calc_required.return_value = Decimal("500")
        mock_is_sufficient.return_value = True

        # Get best coin
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=5.0,
            orderbook_config=self.orderbook_config
        )

        # Should select SHIB (highest trend) since all are liquid
        self.assertEqual(best_coin, "SHIB-EUR")

        # Verify depth checks were called
        self.assertGreater(mock_get_orderbook.call_count, 0)
        self.assertGreater(mock_calc_depth.call_count, 0)

    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.get_orderbook_snapshot')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_orderbook_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_required_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.is_sufficient_depth')
    def test_get_best_coin_filters_illiquid_coins(
        self, mock_is_sufficient, mock_calc_required, mock_calc_depth, mock_get_orderbook
    ):
        """Test that illiquid coins are filtered out"""

        def depth_check_side_effect(symbol):
            # SHIB has low depth (illiquid), others are liquid
            if symbol == "SHIB-EUR":
                return self._create_mock_orderbook(symbol, 50, 50)
            else:
                return self._create_mock_orderbook(symbol, 5000, 5000)

        def depth_metrics_side_effect(bids, **kwargs):
            # Return depth based on bid amount
            amount = float(bids[0].amount)
            if amount < 100:  # SHIB
                return self._create_mock_depth_metrics(50, 50)
            else:  # Others
                return self._create_mock_depth_metrics(5000, 5000)

        def sufficient_check_side_effect(depth_metrics, required, tolerance):
            # SHIB insufficient (50 < 500), others sufficient
            return depth_metrics.bid_depth >= required * Decimal(str(1 - tolerance))

        mock_get_orderbook.side_effect = lambda conn, symbol: depth_check_side_effect(symbol)
        mock_calc_depth.side_effect = depth_metrics_side_effect
        mock_calc_required.return_value = Decimal("500")
        mock_is_sufficient.side_effect = sufficient_check_side_effect

        # Get best coin
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=5.0,
            orderbook_config=self.orderbook_config
        )

        # Should select BTC (highest trend among LIQUID coins) - SHIB is filtered out
        self.assertEqual(best_coin, "BTC-EUR")

        # Verify debug info shows filtering
        self.assertIn('depth_filtered', self.trend_calculator._debug_info)
        self.assertGreater(self.trend_calculator._debug_info['depth_filtered'], 0)

    def test_get_best_coin_without_depth_filtering(self):
        """Test get_best_coin without depth filtering (disabled)"""

        # Get best coin without orderbook_config
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=5.0,
            orderbook_config=None  # Disabled
        )

        # Should select SHIB (highest trend) since depth filtering is disabled
        self.assertEqual(best_coin, "SHIB-EUR")

    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.get_orderbook_snapshot')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_orderbook_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_required_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.is_sufficient_depth')
    def test_get_best_coin_handles_orderbook_errors_gracefully(
        self, mock_is_sufficient, mock_calc_required, mock_calc_depth, mock_get_orderbook
    ):
        """Test that orderbook fetch errors don't block coins (allow through)"""

        def orderbook_side_effect(conn, symbol):
            if symbol == "SHIB-EUR":
                raise Exception("API error")
            else:
                return self._create_mock_orderbook(symbol, 5000, 5000)

        mock_get_orderbook.side_effect = orderbook_side_effect
        mock_calc_depth.side_effect = lambda **kwargs: self._create_mock_depth_metrics(5000, 5000)
        mock_calc_required.return_value = Decimal("500")
        mock_is_sufficient.return_value = True

        # Get best coin (should NOT crash)
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=5.0,
            orderbook_config=self.orderbook_config
        )

        # Should select SHIB despite error (allowed through)
        self.assertEqual(best_coin, "SHIB-EUR")

    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.get_orderbook_snapshot')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_orderbook_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.calculate_required_depth')
    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.is_sufficient_depth')
    def test_get_top_n_coins_with_depth_filtering(
        self, mock_is_sufficient, mock_calc_required, mock_calc_depth, mock_get_orderbook
    ):
        """Test get_top_n_coins filters illiquid coins"""

        def depth_metrics_side_effect(bids, **kwargs):
            # Return depth based on bid amount
            amount = float(bids[0].amount)
            if amount < 100:  # SHIB
                return self._create_mock_depth_metrics(50, 50)
            else:  # Others
                return self._create_mock_depth_metrics(5000, 5000)

        def sufficient_check_side_effect(depth_metrics, required, tolerance):
            # SHIB insufficient (50 < 450), others sufficient
            return depth_metrics.bid_depth >= required * Decimal(str(1 - tolerance))

        mock_get_orderbook.side_effect = lambda conn, symbol: (
            self._create_mock_orderbook(symbol, 50, 50) if symbol == "SHIB-EUR"
            else self._create_mock_orderbook(symbol, 5000, 5000)
        )
        mock_calc_depth.side_effect = depth_metrics_side_effect
        mock_calc_required.return_value = Decimal("500")
        mock_is_sufficient.side_effect = sufficient_check_side_effect

        # Get top 3 coins
        top_coins = self.trend_calculator.get_top_n_coins(
            n=3,
            min_trend_pct=5.0,
            orderbook_config=self.orderbook_config
        )

        # Should return only liquid coins (SHIB filtered out)
        self.assertEqual(len(top_coins), 3)
        self.assertNotIn("SHIB-EUR", top_coins)
        self.assertIn("BTC-EUR", top_coins)
        self.assertIn("ETH-EUR", top_coins)
        self.assertIn("SOL-EUR", top_coins)

    @patch('hummingbot.multi_coin_grid_utils.trend_calculator.get_orderbook_snapshot')
    def test_get_top_n_coins_skips_coins_without_orderbook(
        self, mock_get_orderbook
    ):
        """Test that coins without orderbook data are skipped"""

        def orderbook_side_effect(conn, symbol):
            if symbol == "SHIB-EUR":
                # Return orderbook without snapshot_uid (invalid)
                orderbook = Mock()
                orderbook.snapshot_uid = None
                return orderbook
            else:
                return self._create_mock_orderbook(symbol, 5000, 5000)

        mock_get_orderbook.side_effect = orderbook_side_effect

        # Get top coins
        top_coins = self.trend_calculator.get_top_n_coins(
            n=4,
            min_trend_pct=5.0,
            orderbook_config=self.orderbook_config
        )

        # SHIB should be filtered out (no valid orderbook)
        self.assertNotIn("SHIB-EUR", top_coins)

    def test_orderbook_config_missing_order_size(self):
        """Test that missing order_size disables depth filtering"""

        # Config without order_size
        invalid_config = {
            'enabled': True,
            'depth_pct_range': 0.5,
            'depth_levels': 10,
            'min_depth_multiplier': 5.0,
            # 'order_size': Missing!
        }

        # Should NOT crash, but disable filtering
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=5.0,
            orderbook_config=invalid_config
        )

        # Should work without depth filtering (selects highest trend)
        self.assertEqual(best_coin, "SHIB-EUR")


@unittest.skipUnless(TREND_CALCULATOR_AVAILABLE, "TrendCalculator not available")
class TestMarketRegimeIntegrationDepthFiltering(unittest.TestCase):
    """Test orderbook depth config passthrough in MarketRegimeIntegration"""

    def setUp(self):
        """Set up test fixtures"""
        from multi_coin_grid_pro.core.market_regime_integration import MarketRegimeIntegration
        from multi_coin_grid_pro.filters.market_regime_filter import MarketRegimeConfig

        self.connector = Mock(spec=ConnectorBase)
        self.connector.name = "kraken"

        self.trend_calculator = TrendCalculator(
            connector=self.connector,
            lookback_minutes=60,
        )

        regime_config = MarketRegimeConfig()

        self.regime_integration = MarketRegimeIntegration(
            trend_calculator=self.trend_calculator,
            regime_config=regime_config,
            enabled=False,  # Disabled for testing
        )

    @patch.object(TrendCalculator, 'get_best_coin')
    def test_orderbook_config_passthrough(self, mock_get_best_coin):
        """Test that orderbook_config is passed through correctly"""

        orderbook_config = {
            'enabled': True,
            'depth_pct_range': 0.5,
            'depth_levels': 10,
            'min_depth_multiplier': 5.0,
            'order_size': Decimal("100"),
        }

        mock_get_best_coin.return_value = "BTC-EUR"

        # Call get_best_coin_with_regime_check with orderbook_config
        best_coin = self.regime_integration.get_best_coin_with_regime_check(
            min_trend_pct=5.0,
            exclude_coins=["SHIB-EUR"],
            orderbook_config=orderbook_config
        )

        # Verify orderbook_config was passed to TrendCalculator
        mock_get_best_coin.assert_called_once_with(
            min_trend_pct=5.0,
            exclude_coins=["SHIB-EUR"],
            orderbook_config=orderbook_config
        )

        self.assertEqual(best_coin, "BTC-EUR")


@unittest.skipUnless(TREND_CALCULATOR_AVAILABLE, "TrendCalculator not available")
class TestControllerOrderbookConfigBuilder(unittest.TestCase):
    """Test MultiCoinGridController._build_orderbook_config()"""

    def test_build_orderbook_config_enabled(self):
        """Test building orderbook config when enabled"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        # Create mock config
        config = Mock(spec=MultiCoinGridConfig)
        config.orderbook_liquidity = {
            'enabled': True,
            'depth_pct_range': 0.5,
            'depth_levels': 10,
            'min_depth_multiplier': 5.0,
        }
        config.total_amount_quote = Decimal("100")

        # Mock controller (simplified)
        controller = Mock()
        controller.config = config

        # Import and bind method
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        _build_orderbook_config = MultiCoinGridController._build_orderbook_config.__get__(controller, type(controller))

        # Build config
        orderbook_config = _build_orderbook_config()

        # Verify
        self.assertIsNotNone(orderbook_config)
        self.assertEqual(orderbook_config['enabled'], True)
        self.assertEqual(orderbook_config['depth_pct_range'], 0.5)
        self.assertEqual(orderbook_config['depth_levels'], 10)
        self.assertEqual(orderbook_config['min_depth_multiplier'], 5.0)
        self.assertEqual(orderbook_config['order_size'], Decimal("100"))

    def test_build_orderbook_config_disabled(self):
        """Test building orderbook config when disabled"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        # Create mock config with disabled orderbook
        config = Mock(spec=MultiCoinGridConfig)
        config.orderbook_liquidity = {
            'enabled': False,
        }
        config.total_amount_quote = Decimal("100")

        # Mock controller with logger
        controller = Mock()
        controller.config = config
        controller.logger = Mock(return_value=Mock())

        # Import and bind method
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        _build_orderbook_config = MultiCoinGridController._build_orderbook_config.__get__(controller, type(controller))

        # Build config
        orderbook_config = _build_orderbook_config()

        # Should return None when disabled
        self.assertIsNone(orderbook_config)

    def test_build_orderbook_config_missing(self):
        """Test building orderbook config when section is missing"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        # Create mock config without orderbook_liquidity
        config = Mock(spec=MultiCoinGridConfig)
        config.orderbook_liquidity = None
        config.total_amount_quote = Decimal("100")

        # Mock controller with logger
        controller = Mock()
        controller.config = config
        controller.logger = Mock(return_value=Mock())

        # Import and bind method
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        _build_orderbook_config = MultiCoinGridController._build_orderbook_config.__get__(controller, type(controller))

        # Build config
        orderbook_config = _build_orderbook_config()

        # Should return None when missing
        self.assertIsNone(orderbook_config)


if __name__ == '__main__':
    unittest.main()
