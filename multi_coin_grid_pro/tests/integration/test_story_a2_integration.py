"""
Story A2: Session Blacklist Integration Test
==============================================

Tests the end-to-end flow of blacklisting:
1. Executor closes with timeout → symbol blacklisted
2. Next coin selection cycle → blacklisted symbol is skipped
3. After expiry → symbol becomes selectable again
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType


class TestStoryA2Integration(unittest.TestCase):
    """Integration test for Story A2 blacklist flow"""

    def setUp(self):
        """Set up test environment"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # Create config
        self.config = MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            blacklist_after_timeout_sec=1800,  # 30 minutes
            trend_min_change_pct=Decimal("1.0"),
        )

        # Mock dependencies
        self.market_data_provider = MagicMock()
        self.market_data_provider.time = MagicMock(return_value=1000.0)
        self.market_data_provider.ready = True

        self.actions_queue = MagicMock()
        self.connectors = {"kraken": MagicMock()}

        # Create controller
        with patch.object(MultiCoinGridController, '_initialize_components'):
            self.controller = MultiCoinGridController(
                config=self.config,
                market_data_provider=self.market_data_provider,
                actions_queue=self.actions_queue,
                connectors=self.connectors,
            )

        self.now = 1000.0

    def test_timeout_close_then_selection_skip_then_expiry(self):
        """
        Integration Test: Executor timeout → blacklist → skip in selection → expiry

        Scenario:
        1. BTC-EUR executor closes with NO_FILL_TIMEOUT
        2. BTC-EUR is added to blacklist for 30 minutes
        3. Next coin selection cycle: BTC-EUR is excluded from candidates
        4. After 30 minutes: BTC-EUR becomes selectable again
        """
        symbol = "BTC-EUR"

        # ===== STEP 1: Executor closes with timeout =====
        executor = MagicMock()
        executor.id = "test_executor_timeout"
        executor.status = RunnableStatus.TERMINATED
        executor.close_type = CloseType.NO_FILL_TIMEOUT
        executor.net_pnl_quote = -5.0
        executor.config = MagicMock()
        executor.config.trading_pair = symbol
        executor.custom_info = {}

        # Add to executors_info
        self.controller.executors_info = [executor]
        self.controller._realised_executors_tracked = {}
        self.controller._processed_timeout_executors = set()

        # Simulate _sync_risk_state processing (where blacklist logic runs)
        for exec_info in self.controller.executors_info:
            if exec_info.status == RunnableStatus.TERMINATED:
                if exec_info.id not in self.controller._realised_executors_tracked:
                    trading_pair = getattr(getattr(exec_info, "config", None), "trading_pair", None)

                    if trading_pair and exec_info.id not in self.controller._processed_timeout_executors:
                        self.controller._processed_timeout_executors.add(exec_info.id)

                        timeout_close_types = {
                            CloseType.NO_FILL_TIMEOUT,
                            CloseType.NO_PROGRESS_TIMEOUT,
                            CloseType.TIME_LIMIT,
                            CloseType.HARD_CAP_TIME_LIMIT,
                        }

                        if exec_info.close_type in timeout_close_types:
                            reason = exec_info.close_type.name if exec_info.close_type else "TIMEOUT"
                            self.controller._add_to_blacklist(trading_pair, reason, self.now)

                    self.controller._realised_executors_tracked[exec_info.id] = Decimal(str(exec_info.net_pnl_quote))

        # Verify BTC-EUR is blacklisted
        self.assertTrue(self.controller._is_blacklisted(symbol, self.now))
        self.assertIn(symbol, self.controller.session_blacklist)

        # ===== STEP 2: Coin selection should skip blacklisted coin =====
        # Purge expired (none yet)
        self.controller._purge_expired_blacklist(self.now + 100)

        # Build exclusion set (simulating determine_executor_actions logic)
        blacklisted_coins = set(self.controller.session_blacklist.keys())
        config_blacklist = set(getattr(self.config, 'blacklist', []) or [])
        excluded_coins = blacklisted_coins | config_blacklist

        # Verify BTC-EUR is in exclusions
        self.assertIn(symbol, excluded_coins)

        # ===== STEP 3: After 30 minutes, blacklist expires =====
        # Advance time past expiry
        future_time = self.now + 1900  # 31.67 minutes later

        # Purge expired
        self.controller._purge_expired_blacklist(future_time)

        # Verify BTC-EUR is NO LONGER blacklisted
        self.assertFalse(self.controller._is_blacklisted(symbol, future_time))
        self.assertNotIn(symbol, self.controller.session_blacklist)

        # Build exclusion set again - BTC should NOT be excluded now
        blacklisted_coins = set(self.controller.session_blacklist.keys())
        excluded_coins = blacklisted_coins | config_blacklist
        self.assertNotIn(symbol, excluded_coins)

    def test_normal_close_does_not_affect_next_selection(self):
        """
        Test: Normal close (TAKE_PROFIT) doesn't blacklist

        Scenario:
        1. BTC-EUR executor closes with TAKE_PROFIT
        2. BTC-EUR is NOT added to blacklist
        3. Next coin selection cycle: BTC-EUR is still selectable
        """
        symbol = "BTC-EUR"

        # ===== STEP 1: Executor closes with TAKE_PROFIT =====
        executor = MagicMock()
        executor.id = "test_executor_normal"
        executor.status = RunnableStatus.TERMINATED
        executor.close_type = CloseType.TAKE_PROFIT
        executor.net_pnl_quote = 15.0
        executor.config = MagicMock()
        executor.config.trading_pair = symbol

        # Add to executors_info
        self.controller.executors_info = [executor]
        self.controller._realised_executors_tracked = {}
        self.controller._processed_timeout_executors = set()

        # Simulate processing
        for exec_info in self.controller.executors_info:
            if exec_info.status == RunnableStatus.TERMINATED:
                if exec_info.id not in self.controller._realised_executors_tracked:
                    trading_pair = getattr(getattr(exec_info, "config", None), "trading_pair", None)

                    if trading_pair and exec_info.id not in self.controller._processed_timeout_executors:
                        self.controller._processed_timeout_executors.add(exec_info.id)

                        timeout_close_types = {
                            CloseType.NO_FILL_TIMEOUT,
                            CloseType.NO_PROGRESS_TIMEOUT,
                            CloseType.TIME_LIMIT,
                            CloseType.HARD_CAP_TIME_LIMIT,
                        }

                        if exec_info.close_type in timeout_close_types:
                            reason = exec_info.close_type.name if exec_info.close_type else "TIMEOUT"
                            self.controller._add_to_blacklist(trading_pair, reason, self.now)

                    self.controller._realised_executors_tracked[exec_info.id] = Decimal(str(exec_info.net_pnl_quote))

        # Verify BTC-EUR is NOT blacklisted
        self.assertFalse(self.controller._is_blacklisted(symbol, self.now))
        self.assertNotIn(symbol, self.controller.session_blacklist)

        # ===== STEP 2: Coin selection should NOT exclude BTC-EUR =====
        blacklisted_coins = set(self.controller.session_blacklist.keys())
        self.assertNotIn(symbol, blacklisted_coins)


if __name__ == '__main__':
    unittest.main()
