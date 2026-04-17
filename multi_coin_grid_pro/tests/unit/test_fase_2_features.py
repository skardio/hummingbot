"""
Unit tests for Fase 2 features:
- Task 2.2: Grace Period Bypass Logic
- Task 2.3: Pre-Close Validation

Created: 2026-01-13
"""

import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, Mock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))


# Minimal mock classes for testing without full hummingbot dependencies


class MockTradingRule:
    def __init__(self, trading_pair, min_order_size, min_notional, min_price_increment, min_base_amount_increment):
        self.trading_pair = trading_pair
        self.min_order_size = min_order_size
        self.min_notional = min_notional
        self.min_price_increment = min_price_increment
        self.min_base_amount_increment = min_base_amount_increment


class TestGraceBypassLogic(unittest.TestCase):
    """Test Task 2.2: Grace Period Bypass Logic"""

    def setUp(self):
        """Setup mock controller and config"""
        # Import here to avoid circular dependencies
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # Mock config with bypass flags
        self.mock_config = Mock(spec=MultiCoinGridConfig)
        self.mock_config.grace_bypass_on_executor_error = True
        self.mock_config.grace_bypass_on_sl_hit = True
        self.mock_config.grace_bypass_on_regime_flip = True
        self.mock_config.grace_bypass_on_slot_pressure = True
        self.mock_config.grace_bypass_on_stale_data = True
        self.mock_config.max_simultaneous_coins = 2

        # Mock market data provider
        self.mock_market_data = Mock()
        self.mock_market_data.time.return_value = 1000000
        self.mock_market_data._stale_symbols = set()

        # Create controller with mocks
        self.controller = MultiCoinGridController.__new__(MultiCoinGridController)
        self.controller.config = self.mock_config
        self.controller.market_data_provider = self.mock_market_data
        self.controller.executors_info = []
        self.controller._logger = Mock()
        self.controller.logger = MagicMock(return_value=self.controller._logger)

        # Mock connector (no spec needed)
        self.mock_connector = Mock()
        self.controller.connector = self.mock_connector

    def test_bypass_on_executor_error_failed(self):
        """Test bypass when executor has FAILED status"""
        executor_info = Mock()
        executor_info.is_active = False
        executor_info.close_type = "FAILED"
        executor_info.custom_info = {}

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "BTC-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertIn("executor error", reason)
        self.assertIn("FAILED", reason)

    def test_bypass_on_executor_error_insufficient_balance(self):
        """Test bypass when executor has INSUFFICIENT_BALANCE error"""
        executor_info = Mock()
        executor_info.is_active = False
        executor_info.close_type = "INSUFFICIENT_BALANCE"
        executor_info.custom_info = {}

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "ETH-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertIn("executor error", reason)
        self.assertIn("INSUFFICIENT_BALANCE", reason)

    def test_bypass_on_stop_loss_hit(self):
        """Test bypass when stop-loss is triggered"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.close_type = None
        executor_info.custom_info = {'stop_loss_hit': True}

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "SOL-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertEqual(reason, "stop-loss triggered")

    def test_bypass_on_regime_flip_bull_to_bear(self):
        """Test bypass when regime flips from BULL to BEAR"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {'entry_regime': 'BULL'}

        # Mock market regime filter
        self.controller.market_regime_filter = Mock()
        self.controller.market_regime_filter.get_current_regime = Mock(return_value='BEAR')

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "DASH-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertIn("regime flip", reason)
        self.assertIn("BULL→BEAR", reason)

    def test_bypass_on_regime_flip_bear_to_bull(self):
        """Test bypass when regime flips from BEAR to BULL"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {'entry_regime': 'BEAR'}

        # Mock market regime filter
        self.controller.market_regime_filter = Mock()
        self.controller.market_regime_filter.get_current_regime = Mock(return_value='BULL')

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "LTC-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertIn("regime flip", reason)
        self.assertIn("BEAR→BULL", reason)

    def test_no_bypass_on_regime_same(self):
        """Test NO bypass when regime stays the same"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {'entry_regime': 'BULL'}

        # Mock market regime filter - same regime
        self.controller.market_regime_filter = Mock()
        self.controller.market_regime_filter.get_current_regime = Mock(return_value='BULL')

        # Mock connector with valid price (prevents no-price-data bypass)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("100.0"))

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "DOT-EUR"
        )

        self.assertFalse(should_bypass)
        self.assertEqual(reason, "")

    def test_bypass_on_slot_pressure(self):
        """Test bypass when all slots are full"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {}

        # Mock executors_info with 2 active executors (all slots full)
        mock_exec1 = Mock()
        mock_exec1.is_active = True
        mock_exec2 = Mock()
        mock_exec2.is_active = True
        self.controller.executors_info = [mock_exec1, mock_exec2]

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "BNB-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertIn("slot pressure", reason)
        self.assertIn("2/2 full", reason)

    def test_no_bypass_when_slots_available(self):
        """Test NO bypass when slots are still available"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {}

        # Mock executors_info with only 1 active executor (1 slot free)
        mock_exec1 = Mock()
        mock_exec1.is_active = True
        self.controller.executors_info = [mock_exec1]

        # Mock connector with valid price (prevents no-price-data bypass)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("100.0"))

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "AAVE-EUR"
        )

        self.assertFalse(should_bypass)
        self.assertEqual(reason, "")

    def test_bypass_on_stale_data(self):
        """Test bypass when market data is stale"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {}

        # Mark pair as stale
        self.controller.market_data_provider._stale_symbols.add("SUI-EUR")

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "SUI-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertEqual(reason, "stale market data")

    def test_bypass_on_no_price_data(self):
        """Test bypass when price data is unavailable"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {}

        # Mock connector to return None for price
        self.mock_connector.get_mid_price = Mock(return_value=None)

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "MATIC-EUR"
        )

        self.assertTrue(should_bypass)
        self.assertEqual(reason, "no price data available")

    def test_no_bypass_when_all_conditions_ok(self):
        """Test NO bypass when all conditions are normal"""
        executor_info = Mock()
        executor_info.is_active = True
        executor_info.timestamp = 999000  # 1000s old (> min_bypass_age)
        executor_info.custom_info = {}

        # Mock market regime filter - same regime
        self.controller.market_regime_filter = Mock()
        self.controller.market_regime_filter.get_current_regime = Mock(return_value='BULL')

        # Mock connector with valid price
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("100.0"))

        # Only 1 active executor (slots available)
        mock_exec1 = Mock()
        mock_exec1.is_active = True
        self.controller.executors_info = [mock_exec1]

        should_bypass, reason = self.controller._should_bypass_grace_period(
            executor_info, "BTC-EUR"
        )

        self.assertFalse(should_bypass)
        self.assertEqual(reason, "")


class TestPreCloseValidation(unittest.TestCase):
    """Test Task 2.3: Pre-Close Validation"""

    def setUp(self):
        """Setup mock controller"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        # Create controller
        self.controller = MultiCoinGridController.__new__(MultiCoinGridController)
        self.controller._logger = Mock()
        self.controller.logger = MagicMock(return_value=self.controller._logger)

        # Mock connector
        self.mock_connector = Mock()
        self.controller.connector = self.mock_connector

        # Mock executor info
        self.mock_executor = Mock()
        self.mock_executor.custom_info = {'position_size_base': Decimal("0.5")}

    def test_can_close_when_balance_sufficient(self):
        """Test successful close when balance is above minimums"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="BTC-EUR",
            min_order_size=Decimal("0.0001"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.0001")
        )
        self.mock_connector.trading_rules = {"BTC-EUR": trading_rule}

        # Mock balance (0.5 BTC)
        self.mock_connector.get_balance = Mock(return_value=Decimal("0.5"))

        # Mock price (€50,000)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("50000.0"))

        can_close, reason = self.controller._can_safely_close_position(
            "BTC-EUR", self.mock_executor
        )

        self.assertTrue(can_close)
        self.assertEqual(reason, "OK")

    def test_cannot_close_when_dust_below_min_order_size(self):
        """Test rejection when balance is below min order size (dust)"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="ETH-EUR",
            min_order_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.001")
        )
        self.mock_connector.trading_rules = {"ETH-EUR": trading_rule}

        # Mock balance (0.005 ETH - below min 0.01)
        self.mock_connector.get_balance = Mock(return_value=Decimal("0.005"))

        # Mock price (€3,000)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("3000.0"))

        can_close, reason = self.controller._can_safely_close_position(
            "ETH-EUR", self.mock_executor
        )

        self.assertFalse(can_close)
        self.assertIn("Dust", reason)
        self.assertIn("0.00500000 ETH < min 0.01000000", reason)

    def test_cannot_close_when_below_min_notional(self):
        """Test rejection when order value is below min notional"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="SOL-EUR",
            min_order_size=Decimal("0.1"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.01")
        )
        self.mock_connector.trading_rules = {"SOL-EUR": trading_rule}

        # Mock balance (0.2 SOL - above min size but...)
        self.mock_connector.get_balance = Mock(return_value=Decimal("0.2"))

        # Mock price (€30 - value is only €6, below €10 notional)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("30.0"))

        can_close, reason = self.controller._can_safely_close_position(
            "SOL-EUR", self.mock_executor
        )

        self.assertFalse(can_close)
        self.assertIn("Below min notional", reason)
        self.assertIn("€6.00 < €10.00", reason)

    def test_cannot_close_when_no_price_data(self):
        """Test rejection when price data is unavailable"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="DASH-EUR",
            min_order_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.01")
        )
        self.mock_connector.trading_rules = {"DASH-EUR": trading_rule}

        # Mock balance (sufficient)
        self.mock_connector.get_balance = Mock(return_value=Decimal("1.0"))

        # Mock NO price data
        self.mock_connector.get_mid_price = Mock(return_value=None)

        can_close, reason = self.controller._can_safely_close_position(
            "DASH-EUR", self.mock_executor
        )

        self.assertFalse(can_close)
        self.assertEqual(reason, "No price data available")

    def test_cannot_close_when_no_trading_rules(self):
        """Test rejection when trading rules are missing"""
        # Mock NO trading rules for this pair
        self.mock_connector.trading_rules = {}

        # Mock balance
        self.mock_connector.get_balance = Mock(return_value=Decimal("1.0"))

        can_close, reason = self.controller._can_safely_close_position(
            "UNKNOWN-EUR", self.mock_executor
        )

        self.assertFalse(can_close)
        self.assertIn("No trading rules found", reason)

    def test_warning_on_position_mismatch(self):
        """Test warning logged when position mismatch detected (but still allows close)"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="LTC-EUR",
            min_order_size=Decimal("0.1"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.01")
        )
        self.mock_connector.trading_rules = {"LTC-EUR": trading_rule}

        # Mock balance (0.6 LTC - 20% more than tracked 0.5 LTC)
        self.mock_connector.get_balance = Mock(return_value=Decimal("0.6"))

        # Mock price (€100)
        self.mock_connector.get_mid_price = Mock(return_value=Decimal("100.0"))

        can_close, reason = self.controller._can_safely_close_position(
            "LTC-EUR", self.mock_executor
        )

        # Should still allow close but log warning
        self.assertTrue(can_close)
        self.assertEqual(reason, "OK")

        # Verify warning was logged
        self.controller._logger.warning.assert_called()
        warning_call = str(self.controller._logger.warning.call_args)
        self.assertIn("Position mismatch", warning_call)
        self.assertIn("exchange=0.60000000", warning_call)
        self.assertIn("tracked=0.50000000", warning_call)

    def test_handles_balance_query_error(self):
        """Test graceful handling of balance query errors"""
        # Mock trading rule
        trading_rule = MockTradingRule(
            trading_pair="DOT-EUR",
            min_order_size=Decimal("1.0"),
            min_notional=Decimal("10.0"),
            min_price_increment=Decimal("0.01"),
            min_base_amount_increment=Decimal("0.1")
        )
        self.mock_connector.trading_rules = {"DOT-EUR": trading_rule}

        # Mock balance query error
        self.mock_connector.get_balance = Mock(side_effect=Exception("API Error"))

        can_close, reason = self.controller._can_safely_close_position(
            "DOT-EUR", self.mock_executor
        )

        self.assertFalse(can_close)
        self.assertIn("Can't query balance", reason)
        self.assertIn("API Error", reason)


if __name__ == '__main__':
    print("🧪 Running Fase 2 feature tests...")
    print("=" * 60)

    # Run tests
    suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print("\n" + "=" * 60)
    print(f"✅ Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"❌ Failed: {len(result.failures)}")
    print(f"💥 Errors: {len(result.errors)}")
    print("=" * 60)

    # Exit with proper code
    exit(0 if result.wasSuccessful() else 1)
