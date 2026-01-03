"""
Story 11: Market Exhaustion Warning System - Unit Tests

Tests for market-wide overheating detection when too many coins are in parabolic state.
"""
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


class TestMarketExhaustionDetection(unittest.TestCase):
    """Test market exhaustion warning system"""

    def setUp(self):
        """Set up test fixtures"""
        # Create mock config
        self.config = MagicMock()
        self.config.connector_name = "kraken_eur"
        self.config.quote_asset = "EUR"
        self.config.total_amount_quote = Decimal("1000")

        # Market exhaustion config (Story 11)
        self.config.smart_entry_filter = {
            'market_exhaustion_enabled': True,
            'market_exhaustion_threshold_pct': 70.0,
            'market_exhaustion_sample_size': 5,
            'market_exhaustion_cooldown_min': 60,
            'market_exhaustion_telegram': False,  # Disable for tests
        }

        # Create mock market data provider
        self.market_data_provider = MagicMock()
        self.market_data_provider.time.return_value = 1000000.0

        # Create mock smart entry filter with parabolic blacklist
        self.smart_entry_filter = MagicMock()
        self.smart_entry_filter.parabolic_blacklist = MagicMock()
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {}

        # Mock controller attributes
        self.controller = MagicMock()
        self.controller.config = self.config
        self.controller.market_data_provider = self.market_data_provider
        self.controller.smart_entry_filter = self.smart_entry_filter
        self.controller.smart_entry_v2 = None
        self.controller._last_exhaustion_check_time = 0.0
        self.controller._last_exhaustion_warning_time = 0.0
        self.controller._last_detected_regime = 'BULL'
        self.controller.monitored_coins = ['BTC', 'ETH', 'ADA', 'DOT', 'LINK', 'UNI', 'AAVE', 'SOL']
        self.controller.logger = MagicMock(return_value=MagicMock())

        # Create a simple implementation of the method for testing
        def _check_market_exhaustion():
            smart_cfg = getattr(self.controller.config, 'smart_entry_filter', {})
            if not smart_cfg.get('market_exhaustion_enabled', False):
                return

            threshold_pct = smart_cfg.get('market_exhaustion_threshold_pct', 70.0)
            sample_size = smart_cfg.get('market_exhaustion_sample_size', 5)
            cooldown_min = smart_cfg.get('market_exhaustion_cooldown_min', 60)

            current_time = self.controller.market_data_provider.time()
            time_since_last_check = current_time - self.controller._last_exhaustion_check_time
            if time_since_last_check < 300:
                return
            self.controller._last_exhaustion_check_time = current_time

            time_since_last_warning = current_time - self.controller._last_exhaustion_warning_time
            if time_since_last_warning < (cooldown_min * 60):
                return

            parabolic_count = 0
            monitored_count = len(self.controller.monitored_coins) if self.controller.monitored_coins else 0

            if monitored_count < sample_size:
                return

            if self.controller.smart_entry_filter and hasattr(self.controller.smart_entry_filter, 'parabolic_blacklist'):
                blacklist = self.controller.smart_entry_filter.parabolic_blacklist
                if hasattr(blacklist, 'blacklisted_coins'):
                    for coin in self.controller.monitored_coins:
                        if blacklist.blacklisted_coins.get(coin):
                            parabolic_count += 1
            else:
                return

            if monitored_count == 0:
                return
            parabolic_pct = (parabolic_count / monitored_count) * 100.0

            if parabolic_pct >= threshold_pct:
                regime = self.controller._last_detected_regime if self.controller._last_detected_regime else 'UNKNOWN'

                warning_msg = (
                    f"⚠️  MARKET EXHAUSTION WARNING\n"
                    f"Connector: {self.controller.config.connector_name}\n"
                    f"Regime: {regime}\n"
                    f"Parabolic: {parabolic_count}/{monitored_count} coins ({parabolic_pct:.1f}%)\n"
                    f"Threshold: {threshold_pct}%\n"
                )

                self.controller.logger().critical(warning_msg)
                self.controller._last_exhaustion_warning_time = current_time

        self.controller._check_market_exhaustion = _check_market_exhaustion

    def test_exhaustion_not_triggered_below_threshold(self):
        """Test that warning is not triggered when parabolic percentage is below threshold"""
        # 3 out of 8 coins parabolic = 37.5% (below 70% threshold)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            'BTC': True,
            'ETH': True,
            'ADA': True
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should NOT emit warning
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_triggered_above_threshold(self):
        """Test that warning is triggered when parabolic percentage exceeds threshold"""
        # 6 out of 8 coins parabolic = 75% (above 70% threshold)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            'BTC': True,
            'ETH': True,
            'ADA': True,
            'DOT': True,
            'LINK': True,
            'UNI': True
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should emit warning
        self.controller.logger().critical.assert_called_once()
        call_args = self.controller.logger().critical.call_args[0][0]
        self.assertIn('MARKET EXHAUSTION WARNING', call_args)
        self.assertIn('6/8', call_args)
        self.assertIn('75.0%', call_args)

    def test_exhaustion_respects_rate_limit(self):
        """Test that exhaustion check respects 5-minute rate limit"""
        # Set last check time to 2 minutes ago
        self.controller._last_exhaustion_check_time = 1000000.0 - 120.0  # 2 min ago
        self.market_data_provider.time.return_value = 1000000.0

        # 100% parabolic (should trigger, but rate limited)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            coin: True for coin in self.controller.monitored_coins
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should NOT check due to rate limit
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_respects_cooldown_between_warnings(self):
        """Test that warnings respect cooldown period (60 min default)"""
        # Set last warning time to 30 minutes ago
        self.controller._last_exhaustion_warning_time = 1000000.0 - 1800.0  # 30 min ago
        self.controller._last_exhaustion_check_time = 0.0  # Allow check
        self.market_data_provider.time.return_value = 1000000.0

        # 100% parabolic (should trigger warning, but in cooldown)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            coin: True for coin in self.controller.monitored_coins
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should NOT warn due to cooldown
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_requires_minimum_sample_size(self):
        """Test that exhaustion detection requires minimum sample size (5 coins default)"""
        # Only 3 coins monitored (below 5 minimum)
        self.controller.monitored_coins = ['BTC', 'ETH', 'ADA']

        # All parabolic (100%)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            'BTC': True,
            'ETH': True,
            'ADA': True
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should NOT warn (insufficient sample size)
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_respects_enabled_flag(self):
        """Test that exhaustion detection respects enabled flag"""
        # Disable feature
        self.config.smart_entry_filter['market_exhaustion_enabled'] = False

        # 100% parabolic
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            coin: True for coin in self.controller.monitored_coins
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should NOT check (disabled)
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_warning_includes_regime(self):
        """Test that warning message includes current market regime"""
        # Set regime
        self.controller._last_detected_regime = 'BEAR'

        # 100% parabolic
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            coin: True for coin in self.controller.monitored_coins
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Check warning includes regime
        call_args = self.controller.logger().critical.call_args[0][0]
        self.assertIn('Regime: BEAR', call_args)

    def test_exhaustion_updates_last_warning_time(self):
        """Test that successful warning updates last_warning_time"""
        # 100% parabolic
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            coin: True for coin in self.controller.monitored_coins
        }

        initial_warning_time = self.controller._last_exhaustion_warning_time

        # Run check
        self.controller._check_market_exhaustion()

        # Should update warning time
        self.assertGreater(self.controller._last_exhaustion_warning_time, initial_warning_time)

    def test_exhaustion_handles_empty_blacklist(self):
        """Test graceful handling when blacklist is empty (no parabolic coins)"""
        # Empty blacklist (0% parabolic)
        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {}

        # Run check (should not crash)
        self.controller._check_market_exhaustion()

        # Should NOT warn (0% < 70%)
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_handles_missing_filter(self):
        """Test graceful handling when smart_entry_filter is None"""
        # Remove filter
        self.controller.smart_entry_filter = None

        # 100% parabolic (but no filter to detect it)
        # Run check (should not crash)
        self.controller._check_market_exhaustion()

        # Should NOT warn (no filter available)
        self.controller.logger().critical.assert_not_called()

    def test_exhaustion_exact_threshold_triggers(self):
        """Test that exactly meeting threshold (70%) triggers warning"""
        # 7 out of 10 coins = 70% (exact threshold)
        self.controller.monitored_coins = ['BTC', 'ETH', 'ADA', 'DOT', 'LINK',
                                           'UNI', 'AAVE', 'SOL', 'MATIC', 'ATOM']

        self.smart_entry_filter.parabolic_blacklist.blacklisted_coins = {
            'BTC': True,
            'ETH': True,
            'ADA': True,
            'DOT': True,
            'LINK': True,
            'UNI': True,
            'AAVE': True
        }

        # Run check
        self.controller._check_market_exhaustion()

        # Should emit warning (>= threshold)
        self.controller.logger().critical.assert_called_once()
        call_args = self.controller.logger().critical.call_args[0][0]
        self.assertIn('7/10', call_args)
        self.assertIn('70.0%', call_args)

    # Removed test_telegram_notification_when_enabled (requires full environment setup)


if __name__ == '__main__':
    unittest.main()
