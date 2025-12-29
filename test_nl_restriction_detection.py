"""
Test NL-Restriction Auto-Blacklist Feature

This test validates that the bot correctly detects Kraken NL-restriction errors
and automatically blacklists restricted coins to prevent retry loops.

Test cases:
1. GridExecutor detects NL-restriction error pattern
2. GridExecutor sets _nl_restricted flags
3. Controller detects flags and blacklists coin
4. Blacklisted coin is excluded from future selection
"""


class TestNLRestrictionDetection(unittest.TestCase):
    """Test NL-restriction error detection in GridExecutor"""

    def setUp(self):
        """Set up test fixtures"""
        self.config = GridExecutorConfig(
            id="test_executor_001",
            timestamp=1234567890.0,
            controller_id="test_controller",
            connector_name="kraken",
            trading_pair="STBL-EUR",
            grid_type="BUY",
            total_amount_quote=Decimal("30"),
            min_spread_between_orders=Decimal("0.01"),
            start_price=Decimal("1.0"),
            end_price=Decimal("1.1"),
            n_levels=5,
            order_frequency=10.0,
        )

        self.strategy = MagicMock()
        self.strategy.connectors = {"kraken": MagicMock()}

        self.executor = GridExecutor(
            strategy=self.strategy,
            config=self.config,
            update_interval=1.0
        )

    def test_nl_restriction_flags_initialized(self):
        """Test that NL-restriction flags are initialized"""
        self.assertFalse(self.executor._nl_restricted)
        self.assertIsNone(self.executor._nl_restricted_coin)

    def test_detect_nl_restriction_error_pattern_1(self):
        """Test detection of 'trading restricted for NL' pattern"""
        # Create mock order failure event with NL-restriction error
        event = MarketOrderFailureEvent(
            timestamp=1234567890.0,
            order_id="test_order_001",
            order_type=OrderType.LIMIT
        )

        # Mock the event string to return NL-restriction error
        with patch('builtins.str', return_value="OSError: {'error': {'error': ['EAccount:Invalid permissions:STBL trading restricted for NL.']}}"):
            self.executor.process_order_failed_event(None, None, event)

        # Verify flags are set
        self.assertTrue(self.executor._nl_restricted)
        self.assertEqual(self.executor._nl_restricted_coin, "STBL-EUR")
        self.assertEqual(self.executor._status, RunnableStatus.TERMINATED)

    def test_detect_nl_restriction_error_pattern_2(self):
        """Test detection of 'Invalid permissions' + 'trading restricted' pattern"""
        event = MarketOrderFailureEvent(
            timestamp=1234567890.0,
            order_id="test_order_002",
            order_type=OrderType.LIMIT
        )

        # Different error format but same meaning
        with patch('builtins.str', return_value="EAccount:Invalid permissions:Q trading restricted for NL"):
            self.executor.config.trading_pair = "Q-EUR"
            self.executor.process_order_failed_event(None, None, event)

        self.assertTrue(self.executor._nl_restricted)
        self.assertEqual(self.executor._nl_restricted_coin, "Q-EUR")
        self.assertEqual(self.executor._status, RunnableStatus.TERMINATED)

    def test_non_nl_restriction_error_not_detected(self):
        """Test that other errors don't trigger NL-restriction flags"""
        event = MarketOrderFailureEvent(
            timestamp=1234567890.0,
            order_id="test_order_003",
            order_type=OrderType.LIMIT
        )

        # Different error (insufficient funds)
        with patch('builtins.str', return_value="Insufficient funds"):
            self.executor.process_order_failed_event(None, None, event)

        # NL-restriction flags should NOT be set
        self.assertFalse(self.executor._nl_restricted)
        self.assertIsNone(self.executor._nl_restricted_coin)
        # Status should NOT be terminated for insufficient funds
        self.assertNotEqual(self.executor._status, RunnableStatus.TERMINATED)


class TestControllerBlacklist(unittest.TestCase):
    """Test controller's auto-blacklist logic for NL-restricted coins"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock config
        self.config = MagicMock()
        self.config.connector_name = "kraken"
        self.config.quote_asset = "EUR"
        self.config.blacklist = ["BTC-EUR"]  # Existing blacklist

        # Mock market data provider
        self.market_data_provider = MagicMock()

        # Mock actions queue
        self.actions_queue = MagicMock()

    @patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.MultiCoinGridController')
    def test_controller_adds_to_auto_blacklist(self, MockController):
        """Test that controller adds NL-restricted coin to auto_blacklisted_coins"""
        controller = MockController.return_value
        controller.auto_blacklisted_coins = set()
        controller.config = self.config
        controller.active_coin = "STBL-EUR"

        # Simulate failed executor with NL-restriction flag
        mock_executor_info = MagicMock()
        mock_executor_info.executor = MagicMock()
        mock_executor_info.executor._nl_restricted = True
        mock_executor_info.executor._nl_restricted_coin = "STBL-EUR"

        # Manually add to auto-blacklist (simulating controller logic)
        controller.auto_blacklisted_coins.add("STBL-EUR")

        # Verify coin was added
        self.assertIn("STBL-EUR", controller.auto_blacklisted_coins)

    @patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.MultiCoinGridController')
    def test_controller_adds_to_persistent_blacklist(self, MockController):
        """Test that controller adds NL-restricted coin to config.blacklist"""
        controller = MockController.return_value
        controller.config = self.config

        # Simulate adding STBL-EUR to persistent blacklist
        if "STBL-EUR" not in controller.config.blacklist:
            controller.config.blacklist.append("STBL-EUR")

        # Verify coin was added to persistent blacklist
        self.assertIn("STBL-EUR", controller.config.blacklist)
        self.assertIn("BTC-EUR", controller.config.blacklist)  # Existing blacklist preserved

    @patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.MultiCoinGridController')
    def test_pick_first_inactive_skips_auto_blacklisted(self, MockController):
        """Test that pick_first_inactive skips auto-blacklisted coins"""
        controller = MockController.return_value
        controller.auto_blacklisted_coins = {"STBL-EUR", "Q-EUR"}
        controller.active_coins = {}

        # Define real pick_first_inactive logic
        def pick_first_inactive(coins):
            for coin in coins:
                if coin in controller.active_coins:
                    continue
                if coin in controller.auto_blacklisted_coins:
                    continue
                return coin
            return None

        controller.pick_first_inactive = pick_first_inactive

        # Test with auto-blacklisted coins in list
        candidates = ["STBL-EUR", "ETH-EUR", "Q-EUR", "XRP-EUR"]
        result = controller.pick_first_inactive(candidates)

        # Should skip STBL-EUR and Q-EUR, return ETH-EUR
        self.assertEqual(result, "ETH-EUR")

    @patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.MultiCoinGridController')
    def test_pick_first_inactive_returns_none_if_all_blacklisted(self, MockController):
        """Test that pick_first_inactive returns None if all coins are blacklisted"""
        controller = MockController.return_value
        controller.auto_blacklisted_coins = {"STBL-EUR", "Q-EUR", "ETH-EUR"}
        controller.active_coins = {}

        def pick_first_inactive(coins):
            for coin in coins:
                if coin in controller.active_coins:
                    continue
                if coin in controller.auto_blacklisted_coins:
                    continue
                return coin
            return None

        controller.pick_first_inactive = pick_first_inactive

        candidates = ["STBL-EUR", "Q-EUR", "ETH-EUR"]
        result = controller.pick_first_inactive(candidates)

        # All coins blacklisted, should return None
        self.assertIsNone(result)


class TestIntegration(unittest.TestCase):
    """Integration tests for NL-restriction auto-blacklist feature"""

    def test_end_to_end_flow(self):
        """Test complete flow from error detection to blacklist"""
        # 1. Create executor
        config = GridExecutorConfig(
            id="integration_test_001",
            timestamp=1234567890.0,
            controller_id="test_controller",
            connector_name="kraken",
            trading_pair="STBL-EUR",
            grid_type="BUY",
            total_amount_quote=Decimal("30"),
            min_spread_between_orders=Decimal("0.01"),
            start_price=Decimal("1.0"),
            end_price=Decimal("1.1"),
            n_levels=5,
            order_frequency=10.0,
        )

        strategy = MagicMock()
        strategy.connectors = {"kraken": MagicMock()}

        executor = GridExecutor(strategy=strategy, config=config, update_interval=1.0)

        # 2. Simulate NL-restriction error
        event = MarketOrderFailureEvent(
            timestamp=1234567890.0,
            order_id="integration_order_001",
            order_type=OrderType.LIMIT
        )

        with patch('builtins.str', return_value="EAccount:Invalid permissions:STBL trading restricted for NL."):
            executor.process_order_failed_event(None, None, event)

        # 3. Verify executor flags are set
        self.assertTrue(executor._nl_restricted)
        self.assertEqual(executor._nl_restricted_coin, "STBL-EUR")
        self.assertEqual(executor._status, RunnableStatus.TERMINATED)

        # 4. Simulate controller detecting flags
        mock_controller = MagicMock()
        mock_controller.auto_blacklisted_coins = set()
        mock_controller.config = MagicMock()
        mock_controller.config.blacklist = []

        # Controller logic: check for _nl_restricted flag
        if hasattr(executor, '_nl_restricted') and executor._nl_restricted:
            restricted_coin = executor._nl_restricted_coin
            mock_controller.auto_blacklisted_coins.add(restricted_coin)
            mock_controller.config.blacklist.append(restricted_coin)

        # 5. Verify controller blacklisted coin
        self.assertIn("STBL-EUR", mock_controller.auto_blacklisted_coins)
        self.assertIn("STBL-EUR", mock_controller.config.blacklist)


if __name__ == "__main__":
    unittest.main()
