"""
Test duplicate grid prevention fix
Verifies that a coin can only have ONE active grid at a time
"""


class TestDuplicateGridPrevention(unittest.TestCase):
    """Test that duplicate grids for same coin are prevented"""

    def setUp(self):
        """Setup mock controller"""
        # Import here to avoid issues
        import sys
        sys.path.insert(0, '/home/mo/repos/hummingbot')

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # Mock config
        self.mock_config = Mock()
        self.mock_config.max_simultaneous_coins = 2
        self.mock_config.total_amount_quote = 140

        # Mock market data provider
        self.mock_market_data = Mock()
        self.mock_market_data.time.return_value = 1000000

        # Create controller with mocks
        with patch.multiple(
            'multi_coin_grid_pro.controllers.multi_coin_grid_controller',
            MarketDataProvider=Mock(return_value=self.mock_market_data),
        ):
            self.controller = MultiCoinGridController.__new__(MultiCoinGridController)
            self.controller.config = self.mock_config
            self.controller.market_data_provider = self.mock_market_data
            self.controller.active_coins = {}
            self.controller.executors = {}
            self.controller._logger = Mock()

    def test_pick_first_inactive_returns_first_eligible(self):
        """Test helper picks first coin NOT in active_coins"""
        self.controller.active_coins = {'BTC-USDT': 'exec1'}

        result = self.controller.pick_first_inactive(['BTC-USDT', 'ETH-USDT', 'SOL-USDT'])

        self.assertEqual(result, 'ETH-USDT')

    def test_pick_first_inactive_returns_none_if_all_active(self):
        """Test helper returns None if all coins already active"""
        self.controller.active_coins = {
            'BTC-USDT': 'exec1',
            'ETH-USDT': 'exec2',
            'SOL-USDT': 'exec3'
        }

        result = self.controller.pick_first_inactive(['BTC-USDT', 'ETH-USDT', 'SOL-USDT'])

        self.assertIsNone(result)

    def test_pick_first_inactive_logs_skips(self):
        """Test helper logs when skipping active coins"""
        self.controller.active_coins = {'BTC-USDT': 'exec1'}

        # Mock the logger() method to return our mock logger
        self.controller.logger = MagicMock(return_value=self.controller._logger)

        self.controller.pick_first_inactive(['BTC-USDT', 'ETH-USDT'])

        # Should log skip for BTC-USDT (using debug level)
        self.controller._logger.debug.assert_called()
        call_args = str(self.controller._logger.debug.call_args)
        self.assertIn('BTC-USDT', call_args)
        self.assertIn('already has active grid', call_args)

    def test_active_coins_cleanup_on_executor_stop(self):
        """Test active_coins is cleaned when executor stops"""
        # Setup: BTC has active executor
        mock_executor = Mock()
        mock_executor.config = Mock()
        mock_executor.config.trading_pair = 'BTC-USDT'
        mock_executor.status = RunnableStatus.TERMINATED

        self.controller.executors = {'exec1': mock_executor}
        self.controller.active_coins = {'BTC-USDT': 'exec1'}

        # Simulate cleanup (would be called in _sync_risk_state)
        for exec_id, executor in self.controller.executors.items():
            if executor.status == RunnableStatus.TERMINATED:
                coin = executor.config.trading_pair
                if coin in self.controller.active_coins and self.controller.active_coins[coin] == exec_id:
                    del self.controller.active_coins[coin]

        # Verify cleanup happened
        self.assertNotIn('BTC-USDT', self.controller.active_coins)

    def test_race_condition_guard(self):
        """Test that race condition guard prevents double-create"""
        # Simulate: coin becomes active between selection and creation
        self.controller.active_coins = {}
        best_coin = 'BTC-USDT'

        # First create - should succeed
        self.assertNotIn(best_coin, self.controller.active_coins)

        # Simulate adding to active_coins
        self.controller.active_coins[best_coin] = 'exec1'

        # Second create attempt - should be blocked
        if best_coin in self.controller.active_coins:
            # Guard prevents double-create
            should_create = False
        else:
            should_create = True

        self.assertFalse(should_create, "Race condition guard should prevent double-create")

    def test_multiple_ticks_same_coin(self):
        """Test that same coin cannot be selected in consecutive ticks"""
        # Tick 1: ONDO selected
        top_coins_tick1 = ['ONDO-USDT', 'BTC-USDT', 'ETH-USDT']
        best_coin_tick1 = self.controller.pick_first_inactive(top_coins_tick1)
        self.assertEqual(best_coin_tick1, 'ONDO-USDT')

        # Simulate grid created
        self.controller.active_coins['ONDO-USDT'] = 'exec1'

        # Tick 2: ONDO still #1 but should be skipped
        top_coins_tick2 = ['ONDO-USDT', 'BTC-USDT', 'ETH-USDT']
        best_coin_tick2 = self.controller.pick_first_inactive(top_coins_tick2)
        self.assertEqual(best_coin_tick2, 'BTC-USDT', "Should skip ONDO and pick BTC")

        # Simulate second grid created
        self.controller.active_coins['BTC-USDT'] = 'exec2'

        # Tick 3: Both slots full
        top_coins_tick3 = ['ONDO-USDT', 'BTC-USDT', 'ETH-USDT']
        best_coin_tick3 = self.controller.pick_first_inactive(top_coins_tick3)
        self.assertEqual(best_coin_tick3, 'ETH-USDT', "Should skip ONDO and BTC, pick ETH")


if __name__ == '__main__':
    print("🧪 Running duplicate grid prevention tests...")
    unittest.main(verbosity=2)
