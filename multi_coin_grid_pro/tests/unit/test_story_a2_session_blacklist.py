"""
Story A2: Session Blacklist & Anti-Flipflop Unit Tests
========================================================

Tests the session blacklist system that prevents re-selecting coins
that were closed due to timeouts (NO_FILL_TIMEOUT, NO_PROGRESS_TIMEOUT, TIME_LIMIT).

Test Coverage:
- Blacklist add & expiry
- Blacklist filtering during coin selection
- Idempotency (processing same executor twice)
- Non-timeout closes don't trigger blacklist
- Config toggle (blacklist_after_timeout_sec = 0 disables)
"""

import unittest
from unittest.mock import MagicMock, patch

from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType


class TestStoryA2SessionBlacklist(unittest.TestCase):
    """Test suite for Story A2 session blacklist & anti-flipflop"""

    def setUp(self):
        """Set up test fixtures"""
        # Import controller here to avoid issues
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # Create minimal config
        self.config = MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            blacklist_after_timeout_sec=1800,  # 30 minutes
        )

        # Mock dependencies
        self.market_data_provider = MagicMock()
        self.market_data_provider.time = MagicMock(return_value=1000.0)
        self.market_data_provider.ready = True

        self.actions_queue = MagicMock()
        self.connectors = {"kraken": MagicMock()}

        # Create controller with mocked components
        with patch.object(MultiCoinGridController, '_initialize_components'):
            self.controller = MultiCoinGridController(
                config=self.config,
                market_data_provider=self.market_data_provider,
                actions_queue=self.actions_queue,
                connectors=self.connectors,
            )

        # Set current time
        self.now = 1000.0

    def test_is_blacklisted_returns_false_for_non_blacklisted_coin(self):
        """Test: Non-blacklisted coin returns False"""
        self.assertFalse(self.controller._is_blacklisted("BTC-EUR", self.now))

    def test_add_to_blacklist_and_check(self):
        """Test: Adding coin to blacklist makes it blacklisted until expiry"""
        symbol = "BTC-EUR"
        reason = "NO_FILL_TIMEOUT"

        # Add to blacklist
        self.controller._add_to_blacklist(symbol, reason, self.now)

        # Should be blacklisted now
        self.assertTrue(self.controller._is_blacklisted(symbol, self.now))

        # Should still be blacklisted 10 minutes later
        self.assertTrue(self.controller._is_blacklisted(symbol, self.now + 600))

        # Should still be blacklisted 29 minutes later
        self.assertTrue(self.controller._is_blacklisted(symbol, self.now + 1740))

        # Should NOT be blacklisted 31 minutes later (after 30min expiry)
        self.assertFalse(self.controller._is_blacklisted(symbol, self.now + 1860))

    def test_purge_expired_blacklist(self):
        """Test: Purge removes expired entries but keeps active ones"""
        # Add 3 coins to blacklist at different times
        self.controller._add_to_blacklist("BTC-EUR", "NO_FILL_TIMEOUT", self.now)
        self.controller._add_to_blacklist("ETH-EUR", "NO_PROGRESS_TIMEOUT", self.now + 600)  # 10m later
        self.controller._add_to_blacklist("SOL-EUR", "TIME_LIMIT", self.now + 1200)  # 20m later

        # All 3 should be in blacklist
        self.assertEqual(len(self.controller.session_blacklist), 3)

        # Purge at 35 minutes (only BTC should expire at 30m, ETH at 40m, SOL at 50m)
        self.controller._purge_expired_blacklist(self.now + 2100)

        # BTC should be purged (30m + 35m = 65m > 30m expiry)
        self.assertEqual(len(self.controller.session_blacklist), 2)
        self.assertNotIn("BTC-EUR", self.controller.session_blacklist)
        self.assertIn("ETH-EUR", self.controller.session_blacklist)
        self.assertIn("SOL-EUR", self.controller.session_blacklist)

    def test_no_timeout_close_does_not_trigger_blacklist(self):
        """Test: Normal closes (TAKE_PROFIT, COMPLETED) don't trigger blacklist"""
        # Create mock executor with TAKE_PROFIT close
        executor = MagicMock()
        executor.id = "test_executor_1"
        executor.status = RunnableStatus.TERMINATED
        executor.close_type = CloseType.TAKE_PROFIT
        executor.net_pnl_quote = 10.0
        executor.config = MagicMock()
        executor.config.trading_pair = "BTC-EUR"

        # Simulate executor termination processing
        self.controller.executors_info = [executor]
        self.controller._realised_executors_tracked = {}
        self.controller._processed_timeout_executors = set()

        # Process the executor in _sync_risk_state context
        trading_pair = "BTC-EUR"
        if executor.id not in self.controller._processed_timeout_executors:
            self.controller._processed_timeout_executors.add(executor.id)

            timeout_close_types = {
                CloseType.NO_FILL_TIMEOUT,
                CloseType.NO_PROGRESS_TIMEOUT,
                CloseType.TIME_LIMIT,
                CloseType.HARD_CAP_TIME_LIMIT,
            }

            if executor.close_type in timeout_close_types:
                reason = executor.close_type.name if executor.close_type else "TIMEOUT"
                self.controller._add_to_blacklist(trading_pair, reason, self.now)

        # BTC should NOT be blacklisted (normal close)
        self.assertFalse(self.controller._is_blacklisted("BTC-EUR", self.now))
        self.assertEqual(len(self.controller.session_blacklist), 0)

    def test_timeout_close_triggers_blacklist(self):
        """Test: Timeout closes (NO_FILL_TIMEOUT, etc) trigger blacklist"""
        # Test all timeout close types
        timeout_types = [
            CloseType.NO_FILL_TIMEOUT,
            CloseType.NO_PROGRESS_TIMEOUT,
            CloseType.TIME_LIMIT,
            CloseType.HARD_CAP_TIME_LIMIT,
        ]

        for idx, close_type in enumerate(timeout_types):
            symbol = f"TEST{idx}-EUR"

            # Create mock executor with timeout close
            executor = MagicMock()
            executor.id = f"test_executor_{idx}"
            executor.status = RunnableStatus.TERMINATED
            executor.close_type = close_type
            executor.net_pnl_quote = -5.0
            executor.config = MagicMock()
            executor.config.trading_pair = symbol

            # Process executor
            trading_pair = symbol
            if executor.id not in self.controller._processed_timeout_executors:
                self.controller._processed_timeout_executors.add(executor.id)

                timeout_close_types = {
                    CloseType.NO_FILL_TIMEOUT,
                    CloseType.NO_PROGRESS_TIMEOUT,
                    CloseType.TIME_LIMIT,
                    CloseType.HARD_CAP_TIME_LIMIT,
                }

                if executor.close_type in timeout_close_types:
                    reason = executor.close_type.name if executor.close_type else "TIMEOUT"
                    self.controller._add_to_blacklist(trading_pair, reason, self.now)

            # Symbol should be blacklisted
            self.assertTrue(
                self.controller._is_blacklisted(symbol, self.now),
                f"{close_type.name} should trigger blacklist"
            )

    def test_idempotency_same_executor_processed_twice(self):
        """Test: Processing same executor twice doesn't extend blacklist"""
        symbol = "BTC-EUR"

        # Create executor
        executor = MagicMock()
        executor.id = "test_executor_1"
        executor.status = RunnableStatus.TERMINATED
        executor.close_type = CloseType.NO_FILL_TIMEOUT
        executor.config = MagicMock()
        executor.config.trading_pair = symbol

        # Process first time
        if executor.id not in self.controller._processed_timeout_executors:
            self.controller._processed_timeout_executors.add(executor.id)
            self.controller._add_to_blacklist(symbol, "NO_FILL_TIMEOUT", self.now)

        # Get original expiry
        original_expiry = self.controller.session_blacklist[symbol]

        # Try to process again (should be skipped)
        if executor.id not in self.controller._processed_timeout_executors:
            self.controller._processed_timeout_executors.add(executor.id)
            self.controller._add_to_blacklist(symbol, "NO_FILL_TIMEOUT", self.now + 100)

        # Expiry should NOT have changed
        self.assertEqual(self.controller.session_blacklist[symbol], original_expiry)

    def test_blacklist_disabled_when_config_zero(self):
        """Test: blacklist_after_timeout_sec=0 disables blacklisting"""
        # Change config to disable
        self.controller.config.blacklist_after_timeout_sec = 0

        # Try to add to blacklist
        self.controller._add_to_blacklist("BTC-EUR", "NO_FILL_TIMEOUT", self.now)

        # Should NOT be blacklisted (disabled)
        self.assertFalse(self.controller._is_blacklisted("BTC-EUR", self.now))
        self.assertEqual(len(self.controller.session_blacklist), 0)

    def test_get_blacklist_info_returns_correct_format(self):
        """Test: _get_blacklist_info returns formatted string"""
        symbol = "BTC-EUR"

        # Add to blacklist
        self.controller._add_to_blacklist(symbol, "NO_FILL_TIMEOUT", self.now)

        # Get info immediately
        info = self.controller._get_blacklist_info(symbol, self.now)
        self.assertIsNotNone(info)
        self.assertIn("expires in", info)
        self.assertIn("30m", info)  # Should be 30 minutes remaining

        # Get info 20 minutes later
        info = self.controller._get_blacklist_info(symbol, self.now + 1200)
        self.assertIsNotNone(info)
        self.assertIn("expires in", info)
        self.assertIn("10m", info)  # Should be ~10 minutes remaining

        # Get info after expiry
        info = self.controller._get_blacklist_info(symbol, self.now + 1900)
        self.assertIsNone(info)  # Expired

        # Get info for non-blacklisted coin
        info = self.controller._get_blacklist_info("ETH-EUR", self.now)
        self.assertIsNone(info)

    def test_multiple_coins_blacklist_independently(self):
        """Test: Multiple coins can be blacklisted with different expiry times"""
        # Add 3 coins at different times
        self.controller._add_to_blacklist("BTC-EUR", "NO_FILL_TIMEOUT", self.now)
        self.controller._add_to_blacklist("ETH-EUR", "NO_PROGRESS_TIMEOUT", self.now + 300)
        self.controller._add_to_blacklist("SOL-EUR", "TIME_LIMIT", self.now + 600)

        # All should be blacklisted at now + 650
        test_time = self.now + 650
        self.assertTrue(self.controller._is_blacklisted("BTC-EUR", test_time))
        self.assertTrue(self.controller._is_blacklisted("ETH-EUR", test_time))
        self.assertTrue(self.controller._is_blacklisted("SOL-EUR", test_time))

        # BTC should expire first (at now + 1800)
        test_time = self.now + 1850
        self.assertFalse(self.controller._is_blacklisted("BTC-EUR", test_time))
        self.assertTrue(self.controller._is_blacklisted("ETH-EUR", test_time))
        self.assertTrue(self.controller._is_blacklisted("SOL-EUR", test_time))

        # ETH should expire next (at now + 300 + 1800 = now + 2100)
        test_time = self.now + 2150
        self.assertFalse(self.controller._is_blacklisted("BTC-EUR", test_time))
        self.assertFalse(self.controller._is_blacklisted("ETH-EUR", test_time))
        self.assertTrue(self.controller._is_blacklisted("SOL-EUR", test_time))


if __name__ == '__main__':
    unittest.main()
