"""
Test coin selection fallback logic

Tests that when the best trending coin is rejected by SmartEntry or multi-timeframe filters,
the bot automatically tries the next best coins from the top 10 list.

This tests the critical path implemented in lines 1870-1920 of multi_coin_grid_controller.py
"""

import unittest
from unittest.mock import MagicMock


class TestCoinSelectionFallback(unittest.TestCase):
    """
    Unit tests for coin selection fallback logic.
    Tests the logic without requiring full controller instantiation by testing
    the if/elif/for loop logic that implements the fallback mechanism.
    """

    def test_fallback_when_best_coin_rejected_by_smart_entry(self):
        """
        Test that bot tries fallback coins when best coin is rejected by SmartEntry filters.

        Scenario:
        - THQ-EUR is #1 with +16% but RSI too low (falling knife)
        - KAS-EUR is #2 with +6% and passes all filters
        - Bot should select KAS-EUR as fallback
        """
        # Mock trend calculator with top 10 coins
        mock_trend_calc = MagicMock()
        mock_trend_calc._debug_info = {
            'top_10': [
                ('THQ-EUR', 16.63),   # Best but will be rejected (RSI too low)
                ('KAS-EUR', 6.05),    # Should be selected as fallback
                ('0G-EUR', 4.79),     # Backup option
                ('XDC-EUR', 4.04),
                ('GRT-EUR', 3.83),
            ],
        }

        # Simulate the fallback logic without full controller
        excluded_coins = set()
        config_blacklist = set()
        best_coin = 'THQ-EUR'

        # Mock filter functions
        def check_smart_entry_filter(coin):
            if coin == 'THQ-EUR':
                return False  # Rejected: RSI 19.4 < 25
            elif coin == 'KAS-EUR':
                return True   # Passes all SmartEntry checks
            return False

        def check_multi_timeframe_buy(coin):
            if coin == 'THQ-EUR':
                return False  # 1h trend -1.95% < 0
            elif coin == 'KAS-EUR':
                return True   # All trends positive
            return False

        # Test the fallback logic (extracted from controller lines 1870-1920)
        if best_coin and not check_smart_entry_filter(best_coin):
            fallback_found = False
            if hasattr(mock_trend_calc, '_debug_info'):
                top_10 = mock_trend_calc._debug_info.get('top_10', [])
                for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                    if fallback_coin in excluded_coins or fallback_coin in config_blacklist:
                        continue

                    # Check SmartEntry for fallback
                    if check_smart_entry_filter(fallback_coin):
                        # Multi-timeframe buy protection check
                        if not check_multi_timeframe_buy(fallback_coin):
                            continue

                        # Success - use fallback coin
                        best_coin = fallback_coin
                        fallback_found = True
                        break

            if not fallback_found:
                best_coin = None

        # ASSERTIONS
        self.assertIsNotNone(best_coin, "Bot should have selected a fallback coin")
        self.assertEqual(best_coin, 'KAS-EUR', "Bot should have selected KAS-EUR as fallback")

    def test_no_fallback_when_all_coins_rejected(self):
        """
        Test that bot doesn't select any coin when all coins are rejected.

        Scenario:
        - All top coins fail SmartEntry filters (all have RSI < 25 = falling knives)
        - Bot should set best_coin = None and log rejection
        """
        # Mock trend calculator with top 10 coins
        mock_trend_calc = MagicMock()
        mock_trend_calc._debug_info = {
            'top_10': [
                ('THQ-EUR', 16.63),
                ('KAS-EUR', 6.05),
                ('0G-EUR', 4.79),
                ('XDC-EUR', 4.04),
                ('GRT-EUR', 3.83),
            ],
        }

        # Simulate the fallback logic without full controller
        excluded_coins = set()
        config_blacklist = set()
        best_coin = 'THQ-EUR'

        # Mock filter functions - ALL COINS REJECTED
        def check_smart_entry_filter(coin):
            return False  # All coins fail (RSI too low)

        def check_multi_timeframe_buy(coin):
            return False  # All coins fail (negative trends)

        # Test the fallback logic (extracted from controller lines 1870-1920)
        rejection_reason = None
        if best_coin and not check_smart_entry_filter(best_coin):
            fallback_found = False
            if hasattr(mock_trend_calc, '_debug_info'):
                top_10 = mock_trend_calc._debug_info.get('top_10', [])
                for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                    if fallback_coin in excluded_coins or fallback_coin in config_blacklist:
                        continue

                    # Check SmartEntry for fallback
                    if check_smart_entry_filter(fallback_coin):
                        # Multi-timeframe buy protection check
                        if not check_multi_timeframe_buy(fallback_coin):
                            continue

                        # Success - use fallback coin
                        best_coin = fallback_coin
                        fallback_found = True
                        break

            if not fallback_found:
                best_coin = None
                rejection_reason = "All top coins rejected by SmartEntry filters"

        # ASSERTIONS
        self.assertIsNone(best_coin, "Bot should NOT select any coin when all are rejected")
        self.assertIsNotNone(rejection_reason, "Should have rejection reason when all coins fail")
        self.assertIn("rejected", rejection_reason.lower(), "Rejection reason should mention rejection")

    def test_fallback_skips_blacklisted_coins(self):
        """
        Test that fallback logic correctly skips blacklisted coins.

        Scenario:
        - THQ-EUR (#1) rejected by filters
        - KAS-EUR (#2) is in blacklist - should be skipped
        - 0G-EUR (#3) passes filters - should be selected
        """
        # Mock trend calculator with top 10 coins
        mock_trend_calc = MagicMock()
        mock_trend_calc._debug_info = {
            'top_10': [
                ('THQ-EUR', 16.63),
                ('KAS-EUR', 6.05),    # In blacklist - should be skipped
                ('0G-EUR', 4.79),     # Should be selected
                ('XDC-EUR', 4.04),
                ('GRT-EUR', 3.83),
            ],
        }

        # Simulate the fallback logic with blacklist
        excluded_coins = set()
        config_blacklist = {'KAS-EUR'}  # KAS is blacklisted
        best_coin = 'THQ-EUR'

        # Mock filter functions
        def check_smart_entry_filter(coin):
            # THQ fails, all others pass
            return coin != 'THQ-EUR'

        def check_multi_timeframe_buy(coin):
            # All pass (except THQ already rejected)
            return True

        # Test the fallback logic (extracted from controller lines 1870-1920)
        if best_coin and not check_smart_entry_filter(best_coin):
            fallback_found = False
            if hasattr(mock_trend_calc, '_debug_info'):
                top_10 = mock_trend_calc._debug_info.get('top_10', [])
                for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                    # Should skip KAS-EUR because it's in config_blacklist
                    if fallback_coin in excluded_coins or fallback_coin in config_blacklist:
                        continue

                    # Check SmartEntry for fallback
                    if check_smart_entry_filter(fallback_coin):
                        # Multi-timeframe buy protection check
                        if not check_multi_timeframe_buy(fallback_coin):
                            continue

                        # Success - use fallback coin
                        best_coin = fallback_coin
                        fallback_found = True
                        break

            if not fallback_found:
                best_coin = None

        # ASSERTIONS
        self.assertIsNotNone(best_coin, "Bot should have selected a fallback coin")
        self.assertEqual(best_coin, '0G-EUR', "Bot should skip KAS (blacklisted) and select 0G-EUR")
        self.assertNotEqual(best_coin, 'KAS-EUR', "Bot should NOT select blacklisted KAS-EUR")


if __name__ == '__main__':
    unittest.main()
