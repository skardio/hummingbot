"""
US-003: Hard Order Validity Guard

Pre-validates orders BEFORE sending to exchange to prevent:
- Min notional violations (order value too small)
- Insufficient balance errors
- Quantity/price precision issues
- Zero quantity after rounding

This module should be called before any order placement to avoid
HTTP 400 errors and failed executors.
"""
import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class OrderSkipReason(Enum):
    """Reasons why an order was skipped (not sent to exchange)"""
    NONE = "NONE"  # Order is valid
    MIN_NOTIONAL = "MIN_NOTIONAL"  # Order value below exchange minimum
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"  # Not enough balance
    QTY_ROUNDS_TO_ZERO = "QTY_ROUNDS_TO_ZERO"  # Quantity rounds to zero
    PRICE_INVALID = "PRICE_INVALID"  # Price is zero or negative
    QTY_INVALID = "QTY_INVALID"  # Quantity is zero or negative
    TRADING_PAIR_UNKNOWN = "TRADING_PAIR_UNKNOWN"  # No trading rules for pair


@dataclass
class OrderValidationResult:
    """Result of order validation check"""
    is_valid: bool
    skip_reason: OrderSkipReason
    message: str
    # Validated/quantized values
    quantized_amount: Optional[Decimal] = None
    quantized_price: Optional[Decimal] = None
    notional_value: Optional[Decimal] = None
    # Exchange requirements
    min_notional: Optional[Decimal] = None
    min_order_size: Optional[Decimal] = None
    step_size: Optional[Decimal] = None
    tick_size: Optional[Decimal] = None


class OrderValidator:
    """
    Validates orders before sending to exchange.

    Usage:
        validator = OrderValidator(connector, min_notional_buffer_pct=0.10)
        result = validator.validate_order(
            trading_pair="ACT-USDT",
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.0265")
        )
        if not result.is_valid:
            logger.warning(f"Order skipped: {result.skip_reason.value} - {result.message}")
            return
        # Place order with result.quantized_amount, result.quantized_price
    """

    def __init__(
        self,
        connector,
        min_notional_buffer_pct: float = 0.10,
        balance_reserve_pct: float = 0.05,
        log_skipped_orders: bool = True
    ):
        """
        Initialize order validator.

        Args:
            connector: Exchange connector with trading_rules
            min_notional_buffer_pct: Buffer above min notional (default 10%)
            balance_reserve_pct: Reserve for fees/slippage (default 5%)
            log_skipped_orders: Whether to log skipped orders
        """
        self.connector = connector
        self.min_notional_buffer_pct = min_notional_buffer_pct
        self.balance_reserve_pct = balance_reserve_pct
        self.log_skipped_orders = log_skipped_orders

        # Cache for trading rules (avoid repeated lookups)
        self._rules_cache = {}

    def get_trading_rules(self, trading_pair: str) -> Optional[dict]:
        """Get trading rules for a pair, with caching."""
        if trading_pair in self._rules_cache:
            return self._rules_cache[trading_pair]

        try:
            if not hasattr(self.connector, 'trading_rules'):
                return None

            rules = self.connector.trading_rules.get(trading_pair)
            if rules:
                self._rules_cache[trading_pair] = {
                    'min_notional': getattr(rules, 'min_notional_size', Decimal("1")),
                    'min_order_size': getattr(rules, 'min_order_size', Decimal("0")),
                    'step_size': getattr(rules, 'min_base_amount_increment', Decimal("0.00000001")),
                    'tick_size': getattr(rules, 'min_price_increment', Decimal("0.00000001")),
                }
                return self._rules_cache[trading_pair]
        except Exception as e:
            logger.debug(f"Failed to get trading rules for {trading_pair}: {e}")

        return None

    def quantize_amount(self, amount: Decimal, step_size: Decimal) -> Decimal:
        """Round amount down to step size."""
        if step_size <= Decimal("0"):
            return amount
        return (amount / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size

    def quantize_price(self, price: Decimal, tick_size: Decimal) -> Decimal:
        """Round price to tick size."""
        if tick_size <= Decimal("0"):
            return price
        return (price / tick_size).to_integral_value(rounding=ROUND_DOWN) * tick_size

    def validate_order(
        self,
        trading_pair: str,
        side: str,  # "BUY" or "SELL"
        amount: Decimal,
        price: Decimal,
        check_balance: bool = True
    ) -> OrderValidationResult:
        """
        Validate an order before sending to exchange.

        Args:
            trading_pair: Trading pair (e.g., "ACT-USDT")
            side: "BUY" or "SELL"
            amount: Order amount in base currency
            price: Order price
            check_balance: Whether to check available balance

        Returns:
            OrderValidationResult with validation status and details
        """
        # 1. Basic validation - check for NaN and invalid values
        try:
            price_invalid = price.is_nan() or price <= Decimal("0")
        except (AttributeError, TypeError):
            price_invalid = price is None or price <= 0

        if price_invalid:
            return OrderValidationResult(
                is_valid=False,
                skip_reason=OrderSkipReason.PRICE_INVALID,
                message=f"Price must be positive, got {price}"
            )

        try:
            amount_invalid = amount.is_nan() if hasattr(amount, 'is_nan') else False
            amount_invalid = amount_invalid or amount <= Decimal("0")
        except (AttributeError, TypeError):
            amount_invalid = amount is None or amount <= 0

        if amount_invalid:
            return OrderValidationResult(
                is_valid=False,
                skip_reason=OrderSkipReason.QTY_INVALID,
                message=f"Amount must be positive, got {amount}"
            )

        # 2. Get trading rules
        rules = self.get_trading_rules(trading_pair)
        if not rules:
            # Use conservative defaults if rules unavailable
            logger.warning(f"[ORDER_VALIDATOR] No trading rules for {trading_pair}, using defaults")
            rules = {
                'min_notional': Decimal("1"),  # Conservative default
                'min_order_size': Decimal("0"),
                'step_size': Decimal("0.00000001"),
                'tick_size': Decimal("0.00000001"),
            }

        min_notional = rules['min_notional']
        step_size = rules['step_size']
        tick_size = rules['tick_size']

        # 3. Quantize amount and price
        quantized_amount = self.quantize_amount(amount, step_size)
        quantized_price = self.quantize_price(price, tick_size)

        # 4. Check if amount rounds to zero
        if quantized_amount <= Decimal("0"):
            msg = f"Amount {amount} rounds to 0 with step_size {step_size}"
            if self.log_skipped_orders:
                logger.warning(f"[ORDER_VALIDATOR] {trading_pair} SKIPPED: {msg}")
            return OrderValidationResult(
                is_valid=False,
                skip_reason=OrderSkipReason.QTY_ROUNDS_TO_ZERO,
                message=msg,
                step_size=step_size
            )

        # 5. Calculate notional value
        notional = quantized_amount * quantized_price

        # 6. Check min notional (with buffer)
        min_notional_with_buffer = min_notional * Decimal(str(1 + self.min_notional_buffer_pct))
        if notional < min_notional_with_buffer:
            msg = (
                f"Notional {float(notional):.4f} < min {float(min_notional_with_buffer):.4f} "
                f"(min={float(min_notional):.2f} + {self.min_notional_buffer_pct * 100:.0f}% buffer)"
            )
            if self.log_skipped_orders:
                logger.warning(f"[ORDER_VALIDATOR] {trading_pair} SKIPPED: {msg}")
            return OrderValidationResult(
                is_valid=False,
                skip_reason=OrderSkipReason.MIN_NOTIONAL,
                message=msg,
                quantized_amount=quantized_amount,
                quantized_price=quantized_price,
                notional_value=notional,
                min_notional=min_notional
            )

        # 7. Check balance (if enabled)
        if check_balance:
            try:
                if side.upper() == "BUY":
                    # Need quote currency (e.g., USDT)
                    quote_asset = trading_pair.split("-")[1]
                    available = self.connector.get_available_balance(quote_asset)
                    required = notional * Decimal(str(1 + self.balance_reserve_pct))

                    if available < required:
                        msg = f"Insufficient {quote_asset}: have {float(available):.4f}, need {float(required):.4f}"
                        if self.log_skipped_orders:
                            logger.warning(f"[ORDER_VALIDATOR] {trading_pair} SKIPPED: {msg}")
                        return OrderValidationResult(
                            is_valid=False,
                            skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                            message=msg,
                            quantized_amount=quantized_amount,
                            quantized_price=quantized_price,
                            notional_value=notional
                        )
                else:
                    # Need base currency (e.g., ACT)
                    base_asset = trading_pair.split("-")[0]
                    available = self.connector.get_available_balance(base_asset)

                    if available < quantized_amount:
                        msg = f"Insufficient {base_asset}: have {float(available):.6f}, need {float(quantized_amount):.6f}"
                        if self.log_skipped_orders:
                            logger.warning(f"[ORDER_VALIDATOR] {trading_pair} SKIPPED: {msg}")
                        return OrderValidationResult(
                            is_valid=False,
                            skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                            message=msg,
                            quantized_amount=quantized_amount,
                            quantized_price=quantized_price
                        )
            except Exception as e:
                # Balance check failed, but don't block order
                logger.debug(f"[ORDER_VALIDATOR] Balance check failed for {trading_pair}: {e}")

        # 8. All checks passed
        return OrderValidationResult(
            is_valid=True,
            skip_reason=OrderSkipReason.NONE,
            message="Order valid",
            quantized_amount=quantized_amount,
            quantized_price=quantized_price,
            notional_value=notional,
            min_notional=min_notional,
            step_size=step_size,
            tick_size=tick_size
        )


@dataclass
class StandaloneValidationResult:
    """Result for standalone validation (without connector)"""
    is_valid: bool
    skip_reason: Optional[OrderSkipReason]
    message: str
    quantized_quantity: Optional[Decimal] = None
    quantized_price: Optional[Decimal] = None


def validate_order_before_submit(
    trading_pair: str,
    side,  # TradeType enum
    price: Decimal,
    quantity: Decimal,
    trading_rules,
    available_balance: Decimal,
    min_notional_buffer_pct: float = 0.10,
    is_perpetual: bool = False,  # For futures: balance is quote asset (margin)
) -> StandaloneValidationResult:
    """
    Standalone order validation without connector dependency.

    This is called from GridExecutor before placing orders.

    Args:
        trading_pair: Trading pair (e.g., "ACT-USDT")
        side: TradeType.BUY or TradeType.SELL
        price: Order price
        quantity: Order quantity
        trading_rules: TradingRule object from connector
        available_balance: Available balance for the relevant asset
        min_notional_buffer_pct: Buffer above min notional (default 10%)

    Returns:
        StandaloneValidationResult with validation status and quantized values
    """
    # Convert side to string if it's an enum
    side_str = side.name if hasattr(side, 'name') else str(side).upper()

    # 1. Basic validation
    if price is None or price <= Decimal("0"):
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.PRICE_INVALID,
            message=f"Price must be positive, got {price}"
        )

    if quantity is None or quantity <= Decimal("0"):
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.QTY_INVALID,
            message=f"Quantity must be positive, got {quantity}"
        )

    # 2. Get trading rules values
    if trading_rules is None:
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.TRADING_PAIR_UNKNOWN,
            message=f"No trading rules for {trading_pair}"
        )

    min_notional = getattr(trading_rules, 'min_notional_size', Decimal("1"))
    min_order_size = getattr(trading_rules, 'min_order_size', Decimal("0"))
    step_size = getattr(trading_rules, 'min_base_amount_increment', Decimal("0.00000001"))
    tick_size = getattr(trading_rules, 'min_price_increment', Decimal("0.00000001"))

    # 3. Quantize values
    if step_size and step_size > Decimal("0"):
        quantized_qty = (quantity / step_size).to_integral_value(rounding=ROUND_DOWN) * step_size
    else:
        quantized_qty = quantity

    if tick_size and tick_size > Decimal("0"):
        quantized_price = (price / tick_size).to_integral_value(rounding=ROUND_DOWN) * tick_size
    else:
        quantized_price = price

    # 4. Check if quantity rounds to zero
    if quantized_qty <= Decimal("0"):
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.QTY_ROUNDS_TO_ZERO,
            message=f"Quantity {quantity} rounds to 0 with step_size {step_size}"
        )

    # 5. Check min order size
    if min_order_size and quantized_qty < min_order_size:
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.QTY_INVALID,
            message=f"Quantity {quantized_qty} < min_order_size {min_order_size}"
        )

    # 6. Calculate notional and check minimum
    notional = quantized_qty * quantized_price
    min_notional_with_buffer = min_notional * Decimal(str(1 + min_notional_buffer_pct))

    if notional < min_notional_with_buffer:
        return StandaloneValidationResult(
            is_valid=False,
            skip_reason=OrderSkipReason.MIN_NOTIONAL,
            message=f"Notional {float(notional):.4f} < min {float(min_notional_with_buffer):.4f}"
        )

    # 7. Check balance
    if available_balance is not None:
        if is_perpetual:
            # For perpetual futures: both BUY and SELL use quote asset as margin
            # The available_balance passed in is already the quote (USDT) balance
            # For shorts, we just need enough margin, not the actual asset
            # Margin requirement is roughly: notional / leverage (but we don't have leverage here)
            # So just check if we have some reasonable balance
            # Note: actual margin check should be done by connector
            required = notional * Decimal("0.25")  # Assume ~4x leverage, need 25% as margin
            if available_balance < required:
                return StandaloneValidationResult(
                    is_valid=False,
                    skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                    message=f"Insufficient margin: have {float(available_balance):.4f}, need ~{float(required):.4f}"
                )
        elif side_str == "BUY":
            # For spot buy: need notional + buffer
            required = notional * Decimal("1.05")  # 5% buffer for fees
            if available_balance < required:
                return StandaloneValidationResult(
                    is_valid=False,
                    skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                    message=f"Insufficient balance: have {float(available_balance):.4f}, need {float(required):.4f}"
                )
        else:
            # For spot sell: need quantity
            if available_balance < quantized_qty:
                # Allow dust rounding differences (≤ 1 step_size) by capping qty to balance.
                # This fixes the common case where a BUY fill of e.g. 2697.422700 PENGU
                # results in a SELL order of 2697.422720 (floating-point drift in fill tracking).
                dust_threshold = step_size if step_size > Decimal("0") else Decimal("0.000001")
                deficit = quantized_qty - available_balance
                if deficit <= dust_threshold and available_balance > Decimal("0"):
                    # Floor available balance down to step_size
                    adjusted_qty = (available_balance / step_size).to_integral_value(
                        rounding=ROUND_DOWN
                    ) * step_size if step_size > Decimal("0") else available_balance
                    adjusted_notional = adjusted_qty * quantized_price
                    if adjusted_qty > Decimal("0") and adjusted_notional >= min_notional_with_buffer:
                        # Use reduced qty — log at quantized level (caller sees 📐 message)
                        quantized_qty = adjusted_qty
                    else:
                        return StandaloneValidationResult(
                            is_valid=False,
                            skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                            message=(
                                f"Insufficient balance: have {float(available_balance):.6f}, "
                                f"need {float(quantized_qty):.6f} "
                                f"(adjusted {float(adjusted_qty):.6f} fails min_notional)"
                            )
                        )
                else:
                    return StandaloneValidationResult(
                        is_valid=False,
                        skip_reason=OrderSkipReason.INSUFFICIENT_BALANCE,
                        message=f"Insufficient balance: have {float(available_balance):.6f}, need {float(quantized_qty):.6f}"
                    )

    # 8. All checks passed
    return StandaloneValidationResult(
        is_valid=True,
        skip_reason=OrderSkipReason.NONE,
        message="Order valid",
        quantized_quantity=quantized_qty,
        quantized_price=quantized_price
    )
