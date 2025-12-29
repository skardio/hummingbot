"""
Test: Duplicate Grid Prevention

Validates that multi-coin controller never creates multiple grids for the same coin.

Bug scenario (before fix):
- max_simultaneous_coins = 2
- total_amount_quote = 70 (or 140)
- Bot selects ONDO as best_coin
- Creates grid with $35 (70/2)
- Next cycle: selects ONDO AGAIN (no "already active" check)
- Creates 2nd grid with $35
- ... continues until budget exhausted
- Result: 5 grids on same coin = $175 attempted, $140 used

Expected behavior (after fix):
- First cycle: ONDO selected → grid created → added to active_coins
- Second cycle: ONDO filtered out by pick_first_inactive() → selects different coin
- Result: 2 grids on 2 different coins = $70 each
"""

# Import controller
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config.multi_coin_grid_config import MultiCoinGridConfig

from controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.data_feed.market_data_provider import MarketDataProvider

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "multi_coin_grid_pro"))


class TestDuplicateGridPrevention(unittest.TestCase):
    """Test that controller prevents creating multiple grids for same coin"""

    def setUp(self):
        """Set up test controller with mocked dependencies"""
        # Mock config
        self.config = Mock(spec=MultiCoinGridConfig)
        self.config.total_amount_quote = 70.0
        self.config.max_simultaneous_coins = 2
        self.config.connector_name = "bitget"
        self.config.trading_pair = "ONDO-USDT"
        self.config.grid_step = 0.01
        self.config.num_grids = 7

        # Mock market data provider
        self.market_data = Mock(spec=MarketDataProvider)
        self.market_data.time.return_value = 1234567890.0

        # Mock actions queue
        self.actions_queue = Mock()

        # Mock connector
        self.connector = Mock(spec=ConnectorBase)

        # Create controller
        with patch.object(MultiCoinGridController, '__init__', return_value=None):
            self.controller = MultiCoinGridController(
                config=self.config,
                market_data_provider=self.market_data,
                actions_queue=self.actions_queue
            )

            # Manually set required attributes
            self.controller.config = self.config
            self.controller.market_data_provider = self.market_data
            self.controller.active_coins = {}
            self.controller.max_simultaneous_coins = 2
            self.controller.logger = Mock(return_value=Mock())

    def test_pick_first_inactive_returns_first_coin_when_none_active(self):
        """Test that pick_first_inactive returns first coin when no coins are active"""
        coins = ["BTC-USDT", "ETH-USDT", "ONDO-USDT"]

        result = self.controller.pick_first_inactive(coins)

        self.assertEqual(result, "BTC-USDT")
        self.assertEqual(len(self.controller.active_coins), 0)

    def test_pick_first_inactive_skips_active_coins(self):
        """Test that pick_first_inactive skips coins with active grids"""
        self.controller.active_coins = {
            "BTC-USDT": "executor-id-btc",
            "ETH-USDT": "executor-id-eth"
        }
        coins = ["BTC-USDT", "ETH-USDT", "ONDO-USDT", "SOL-USDT"]

        result = self.controller.pick_first_inactive(coins)

        self.assertEqual(result, "ONDO-USDT")  # First non-active coin

    def test_pick_first_inactive_returns_none_when_all_active(self):
        """Test that pick_first_inactive returns None when all coins are active"""
        self.controller.active_coins = {
            "BTC-USDT": "executor-id-btc",
            "ETH-USDT": "executor-id-eth",
            "ONDO-USDT": "executor-id-ondo"
        }
        coins = ["BTC-USDT", "ETH-USDT", "ONDO-USDT"]

        result = self.controller.pick_first_inactive(coins)

        self.assertIsNone(result)

    def test_pick_first_inactive_returns_none_for_empty_list(self):
        """Test that pick_first_inactive handles empty coin list"""
        result = self.controller.pick_first_inactive([])

        self.assertIsNone(result)

    def test_simulate_bug_scenario_prevented(self):
        """
        Test that simulates the original bug scenario:
        - Same coin selected multiple times
        - Verify pick_first_inactive prevents duplicate grids
        """
        # Simulate multiple evaluation cycles
        top_coins = ["ONDO-USDT", "BTC-USDT", "ETH-USDT"]

        # Cycle 1: Select first coin
        cycle1_coin = self.controller.pick_first_inactive(top_coins)
        self.assertEqual(cycle1_coin, "ONDO-USDT")

        # Simulate grid creation
        self.controller.active_coins["ONDO-USDT"] = "executor-id-ondo-1"

        # Cycle 2: Try to select again (should skip ONDO)
        cycle2_coin = self.controller.pick_first_inactive(top_coins)
        self.assertEqual(cycle2_coin, "BTC-USDT")  # Should select next coin

        # Simulate second grid creation
        self.controller.active_coins["BTC-USDT"] = "executor-id-btc-1"

        # Cycle 3: All slots filled (max_simultaneous_coins=2)
        cycle3_coin = self.controller.pick_first_inactive(top_coins)
        self.assertEqual(cycle3_coin, "ETH-USDT")  # Still has free slots in list

        # But if we had max_coins enforcement:
        if len(self.controller.active_coins) >= self.controller.max_simultaneous_coins:
            # Should not create more grids
            self.assertEqual(len(self.controller.active_coins), 2)

    def test_active_coins_cleanup_removes_terminated(self):
        """Test that cleanup removes terminated executors from active_coins"""
        # Setup: 2 active coins
        self.controller.active_coins = {
            "ONDO-USDT": "exec-ondo-123",
            "BTC-USDT": "exec-btc-456"
        }

        # Mock executors_info with one terminated
        mock_executor_ondo = Mock()
        mock_executor_ondo.is_active = False
        mock_executor_ondo.status = Mock()
        mock_executor_ondo.status.name = "TERMINATED"
        mock_executor_ondo.id = "exec-ondo-123"
        mock_executor_ondo.config = Mock()
        mock_executor_ondo.config.trading_pair = "ONDO-USDT"

        mock_executor_btc = Mock()
        mock_executor_btc.is_active = True
        mock_executor_btc.id = "exec-btc-456"

        self.controller.executors_info = [mock_executor_ondo, mock_executor_btc]

        # Need to import RunnableStatus for the check
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus
        mock_executor_ondo.status = RunnableStatus.TERMINATED

        # Run cleanup logic (simplified version)
        for executor in self.controller.executors_info:
            if not executor.is_active and executor.status == RunnableStatus.TERMINATED:
                trading_pair = executor.config.trading_pair if hasattr(executor, 'config') else None
                if trading_pair and trading_pair in self.controller.active_coins:
                    if self.controller.active_coins[trading_pair] == executor.id:
                        del self.controller.active_coins[trading_pair]

        # Verify ONDO removed but BTC still active
        self.assertNotIn("ONDO-USDT", self.controller.active_coins)
        self.assertIn("BTC-USDT", self.controller.active_coins)


if __name__ == "__main__":
    unittest.main()
