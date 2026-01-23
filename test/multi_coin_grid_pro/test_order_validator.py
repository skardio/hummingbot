"""
Unit tests for US-003: Order Validator

Tests the OrderValidator utility that prevents HTTP 400 errors like:
- "notional 0.06 < min 1" (min notional violations)
- "Insufficient balance" (balance issues)
- Quantity rounds to zero
"""
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

# Import the order validator
from multi_coin_grid_pro.utils.order_validator import (
    OrderSkipReason,
    OrderValidationResult,
    OrderValidator,
    validate_order_before_submit,
)


class MockTradingRules:
    """Mock trading rules for testing."""

    def __init__(
        self,
        trading_pair: str = "BTC-USDT",
        min_order_size: Decimal = Decimal("0.0001"),
        min_price_increment: Decimal = Decimal("0.01"),
        min_base_amount_increment: Decimal = Decimal("0.0001"),
        min_notional_size: Decimal = Decimal("1.0"),
    ):
        self.trading_pair = trading_pair
        self.min_order_size = min_order_size
        self.min_price_increment = min_price_increment
        self.min_base_amount_increment = min_base_amount_increment
        self.min_notional_size = min_notional_size


def create_mock_connector(trading_rules_dict: dict, balances: dict = None) -> MagicMock:
    """Create a mock connector with trading rules and balances."""
    connector = MagicMock()

    # Set up trading_rules as a dict-like object
    trading_rules = {}
    for pair, rules in trading_rules_dict.items():
        trading_rules[pair] = rules
    connector.trading_rules = trading_rules

    # Set up quantize methods
    def quantize_price(pair, price):
        rules = trading_rules.get(pair)
        if rules:
            tick = rules.min_price_increment
            return (price // tick) * tick
        return price

    def quantize_amount(pair, amount):
        rules = trading_rules.get(pair)
        if rules:
            step = rules.min_base_amount_increment
            return (amount // step) * step
        return amount

    connector.quantize_order_price = quantize_price
    connector.quantize_order_amount = quantize_amount

    # Set up balance
    if balances:
        connector.get_available_balance = lambda asset: balances.get(asset, Decimal("0"))
    else:
        connector.get_available_balance = lambda asset: Decimal("1000000")

    return connector


class TestOrderValidator(unittest.TestCase):
    """Tests for the OrderValidator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.trading_rules = MockTradingRules(
            trading_pair="ACT-USDT",
            min_order_size=Decimal("1"),
            min_price_increment=Decimal("0.0001"),
            min_base_amount_increment=Decimal("0.01"),
            min_notional_size=Decimal("1.0"),  # Bitget ACT-USDT min notional
        )
        self.connector = create_mock_connector(
            {"ACT-USDT": self.trading_rules}
        )
        self.validator = OrderValidator(
            connector=self.connector,
            min_notional_buffer_pct=0.10,  # 10% buffer
        )

    # =========================================================================
    # Test: Min Notional Validation
    # =========================================================================

    def test_notional_below_minimum_rejected(self):
        """US-003: Order with notional 0.06 < min 1 should be rejected."""
        # This is the exact scenario from the logs: notional 0.06 < min 1
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("0.06"),
            amount=Decimal("1"),  # notional = 0.06 * 1 = 0.06 < 1.0
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)
        self.assertIn("min", result.message.lower())

    def test_notional_at_minimum_with_buffer_rejected(self):
        """Order at exactly min notional should be rejected (need 10% buffer)."""
        # Min notional = 1.0, with 10% buffer need >= 1.1
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("1.0"),
            amount=Decimal("1"),  # notional = 1.0 * 1 = 1.0 (exactly min, no buffer)
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)

    def test_notional_above_minimum_with_buffer_accepted(self):
        """Order above min notional + buffer should be accepted."""
        # Min notional = 1.0, with 10% buffer need >= 1.1
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("1.2"),
            amount=Decimal("1"),  # notional = 1.2 * 1 = 1.2 > 1.1
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.NONE)

    # =========================================================================
    # Test: Quantity Validation
    # =========================================================================

    def test_zero_quantity_rejected(self):
        """Order with zero quantity should be rejected."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("100"),
            amount=Decimal("0"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.QTY_INVALID)

    def test_negative_quantity_rejected(self):
        """Order with negative quantity should be rejected."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("100"),
            amount=Decimal("-1"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.QTY_INVALID)

    def test_quantity_rounds_to_zero_rejected(self):
        """Order where quantity rounds to zero should be rejected."""
        # Step size = 0.01, quantity = 0.001 rounds to 0
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("1000"),
            amount=Decimal("0.001"),  # Will round to 0
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.QTY_ROUNDS_TO_ZERO)

    # =========================================================================
    # Test: Price Validation
    # =========================================================================

    def test_zero_price_rejected(self):
        """Order with zero price should be rejected."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("0"),
            amount=Decimal("10"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.PRICE_INVALID)

    def test_negative_price_rejected(self):
        """Order with negative price should be rejected."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("-100"),
            amount=Decimal("10"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.PRICE_INVALID)

    # =========================================================================
    # Test: Balance Validation
    # =========================================================================

    def test_buy_insufficient_balance_rejected(self):
        """BUY order with insufficient quote balance should be rejected."""
        # Create connector with limited balance
        connector = create_mock_connector(
            {"ACT-USDT": self.trading_rules},
            balances={"USDT": Decimal("500")}
        )
        validator = OrderValidator(connector=connector, min_notional_buffer_pct=0.10)

        result = validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("100"),
            amount=Decimal("10"),  # notional = 1000, balance = 500
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.INSUFFICIENT_BALANCE)

    def test_sell_insufficient_balance_rejected(self):
        """SELL order with insufficient base balance should be rejected."""
        connector = create_mock_connector(
            {"ACT-USDT": self.trading_rules},
            balances={"ACT": Decimal("5")}
        )
        validator = OrderValidator(connector=connector, min_notional_buffer_pct=0.10)

        result = validator.validate_order(
            trading_pair="ACT-USDT",
            side="SELL",
            price=Decimal("100"),
            amount=Decimal("10"),  # Need 10 ACT, have 5
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.INSUFFICIENT_BALANCE)

    def test_sufficient_balance_accepted(self):
        """Order with sufficient balance should be accepted."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("10"),
            amount=Decimal("1"),  # notional = 10
        )

        self.assertTrue(result.is_valid)

    # =========================================================================
    # Test: Quantization
    # =========================================================================

    def test_price_quantized_correctly(self):
        """Price should be quantized to tick size."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("100.12345"),  # tick = 0.0001
            amount=Decimal("1"),
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.quantized_price, Decimal("100.1234"))

    def test_quantity_quantized_correctly(self):
        """Quantity should be quantized to step size."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("10"),
            amount=Decimal("1.12345"),  # step = 0.01
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.quantized_amount, Decimal("1.12"))

    # =========================================================================
    # Test: Convenience Function (Standalone - called from GridExecutor)
    # =========================================================================

    def test_validate_order_before_submit_function(self):
        """Test the standalone convenience function used by GridExecutor."""
        from hummingbot.core.data_type.common import TradeType

        # Create mock trading rules
        class MockTradingRules:
            min_notional_size = Decimal("1")
            min_order_size = Decimal("0.001")
            min_base_amount_increment = Decimal("0.01")
            min_price_increment = Decimal("0.0001")

        result = validate_order_before_submit(
            trading_pair="ACT-USDT",
            side=TradeType.BUY,
            price=Decimal("0.05"),
            quantity=Decimal("1"),  # notional = 0.05 < 1.0
            trading_rules=MockTradingRules(),
            available_balance=Decimal("100"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)

    # =========================================================================
    # Test: Edge Cases
    # =========================================================================

    def test_nan_price_rejected(self):
        """Order with NaN price should be rejected."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("NaN"),
            amount=Decimal("10"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.PRICE_INVALID)

    def test_very_small_notional_rejected(self):
        """Very small orders should be rejected (real scenario from logs)."""
        # Real scenario: ACT-USDT with price 0.06 and qty 1 = notional 0.06
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("0.06"),
            amount=Decimal("1"),
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)

    def test_valid_order_returns_all_fields(self):
        """Valid order should return all quantized values."""
        result = self.validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            price=Decimal("10.5"),
            amount=Decimal("2"),  # notional = 21 > 1.1
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.NONE)
        self.assertEqual(result.message, "Order valid")
        self.assertIsNotNone(result.quantized_price)
        self.assertIsNotNone(result.quantized_amount)
        self.assertIsNotNone(result.notional_value)


class TestOrderValidatorKraken(unittest.TestCase):
    """Tests for Kraken-specific scenarios."""

    def setUp(self):
        """Set up Kraken test fixtures."""
        # Kraken has different min notional (typically in EUR)
        self.trading_rules = MockTradingRules(
            trading_pair="BTC-EUR",
            min_order_size=Decimal("0.0001"),
            min_price_increment=Decimal("0.1"),
            min_base_amount_increment=Decimal("0.00001"),
            min_notional_size=Decimal("5.0"),  # Kraken min notional ~5 EUR
        )
        self.connector = create_mock_connector(
            {"BTC-EUR": self.trading_rules}
        )
        self.validator = OrderValidator(
            connector=self.connector,
            min_notional_buffer_pct=0.10,
        )

    def test_kraken_min_notional_check(self):
        """Kraken: Order below 5 EUR min notional should be rejected."""
        result = self.validator.validate_order(
            trading_pair="BTC-EUR",
            side="BUY",
            price=Decimal("40000"),
            amount=Decimal("0.0001"),  # notional = 4 EUR < 5 EUR
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)

    def test_kraken_valid_order_accepted(self):
        """Kraken: Order above min notional should be accepted."""
        result = self.validator.validate_order(
            trading_pair="BTC-EUR",
            side="BUY",
            price=Decimal("40000"),
            amount=Decimal("0.0002"),  # notional = 8 EUR > 5.5 EUR (with buffer)
        )

        self.assertTrue(result.is_valid)


class TestOrderValidationResult(unittest.TestCase):
    """Tests for the OrderValidationResult dataclass."""

    def test_valid_result_creation(self):
        """Test creating a valid result."""
        result = OrderValidationResult(
            is_valid=True,
            skip_reason=OrderSkipReason.NONE,
            message="Order valid",
            quantized_price=Decimal("100"),
            quantized_amount=Decimal("1"),
            notional_value=Decimal("100"),
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.NONE)

    def test_invalid_result_creation(self):
        """Test creating an invalid result."""
        result = OrderValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.MIN_NOTIONAL,
            message="Notional 0.06 < min 1.1",
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.skip_reason, OrderSkipReason.MIN_NOTIONAL)
        self.assertEqual(result.message, "Notional 0.06 < min 1.1")


if __name__ == "__main__":
    unittest.main()
