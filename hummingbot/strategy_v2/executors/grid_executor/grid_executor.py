import asyncio
import logging
import math
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Union

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PositionAction, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate, PerpetualOrderCandidate
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
    SellOrderCreatedEvent,
)
from hummingbot.logger import HummingbotLogger
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.executor_base import ExecutorBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevel, GridLevelStates
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason, TrackedOrder
from hummingbot.strategy_v2.utils.distributions import Distributions

# Story C1: Log Throttling - prevent executor spam
try:
    from multi_coin_grid_pro.utils.log_throttle import StructuredLogger, should_log
    HAS_LOG_THROTTLE = True
except ImportError:
    HAS_LOG_THROTTLE = False

# US-003: Order validation before exchange submission
try:
    from multi_coin_grid_pro.utils.order_validator import validate_order_before_submit
    HAS_ORDER_VALIDATOR = True
except ImportError:
    HAS_ORDER_VALIDATOR = False


class GridExecutor(ExecutorBase):
    _logger = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, strategy: ScriptStrategyBase, config: GridExecutorConfig,
                 update_interval: float = 1.0, max_retries: int = 10):
        """
        Initialize the PositionExecutor instance.

        :param strategy: The strategy to be used by the PositionExecutor.
        :param config: The configuration for the PositionExecutor, subclass of PositionExecutoConfig.
        :param update_interval: The interval at which the PositionExecutor should be updated, defaults to 1.0.
        :param max_retries: The maximum number of retries for the PositionExecutor, defaults to 5.
        """
        self.config: GridExecutorConfig = config
        # Store configured order types for stop_loss and time_limit exits
        # LIMIT orders can be used for lower fees, but execution is not guaranteed
        # MARKET orders guarantee execution but have higher fees
        self._stop_loss_order_type = config.triple_barrier_config.stop_loss_order_type
        self._time_limit_order_type = config.triple_barrier_config.time_limit_order_type
        super().__init__(strategy=strategy, config=config, connectors=[config.connector_name],
                         update_interval=update_interval)
        self.open_order_price_type = PriceType.BestBid if config.side == TradeType.BUY else PriceType.BestAsk
        self.close_order_price_type = PriceType.BestAsk if config.side == TradeType.BUY else PriceType.BestBid
        self.close_order_side = TradeType.BUY if config.side == TradeType.SELL else TradeType.SELL
        self.trading_rules = self.get_trading_rules(self.config.connector_name, self.config.trading_pair)
        # Grid levels
        self.grid_levels = self._generate_grid_levels()
        self.levels_by_state = {state: [] for state in GridLevelStates}
        self._close_order: Optional[TrackedOrder] = None
        self._filled_orders = []
        self._failed_orders = []
        self._canceled_orders = []

        self.step = Decimal("0")
        self.position_break_even_price = Decimal("0")
        self.position_size_base = Decimal("0")
        self.position_size_quote = Decimal("0")
        self.position_fees_quote = Decimal("0")
        self.position_pnl_quote = Decimal("0")
        self.position_pnl_pct = Decimal("0")
        self.open_liquidity_placed = Decimal("0")
        self.close_liquidity_placed = Decimal("0")
        self.realized_buy_size_quote = Decimal("0")
        self.realized_sell_size_quote = Decimal("0")
        self.realized_imbalance_quote = Decimal("0")
        self.realized_fees_quote = Decimal("0")
        self.realized_pnl_quote = Decimal("0")
        self.realized_pnl_pct = Decimal("0")
        self.max_open_creation_timestamp = 0
        self.max_close_creation_timestamp = 0
        self._open_fee_in_base = False

        self._trailing_stop_trigger_pct: Optional[Decimal] = None
        self._current_retries = 0
        self._max_retries = max_retries
        self._close_balance_retry_interval = 1.0  # seconds between balance refresh attempts
        self._close_balance_max_retries = 10  # how many times we wait for locked balances (Kraken is slow)

        # Insufficient funds retry tracking (prevents infinite loops)
        self._insufficient_funds_retries = 0
        self._max_insufficient_funds_retries = 5  # After 5 attempts, mark executor as failed

        # Exchange min sell price enforcement (Bitget error 41117)
        # When exchange rejects a sell with "selling price cannot be lower than X",
        # we parse the min price and use it on the next attempt.
        self._exchange_min_sell_price: Optional[Decimal] = None
        self._price_rejected_retries = 0
        self._max_price_rejected_retries = 3

        # CRITICAL FIX: Balance mismatch spam prevention
        # Track close order placement attempts when balance < order amount
        self._balance_mismatch_attempts = 0
        self._max_balance_mismatch_attempts = 10  # Stop after 10 failed attempts

        # Cancel retry backoff tracking (BITGET FIX)
        # Prevents excessive cancel retries when exchange is slow to confirm
        self._cancel_request_times = {}  # order_id -> last cancel request timestamp
        self._cancel_retry_count = {}    # order_id -> number of cancel attempts
        self._cancel_min_interval = 10.0  # minimum 10 seconds between cancel retries
        self._cancel_max_retries = 5     # give up after 5 attempts

        # NL-RESTRICTION DETECTION: Track Kraken NL-restricted coins
        self._nl_restricted = False  # Flag: This executor hit NL-restriction error
        self._nl_restricted_coin = None  # Which coin was restricted

        # Phase 1+3: Closing state management (prevent double sell bug)
        self._closing_in_progress = False  # Guard flag to prevent duplicate close orders
        self._close_order_id = None  # Track active close order ID

        # ==============================================================================
        # EXCHANGE BALANCE SYNC FIX: Delay SELL after BUY fill
        # Kraken/Bitget/other exchanges take 2-5 seconds to update balance after a fill.
        # Without this delay, SELL orders fail with "Insufficient funds" because
        # the connector reports 0 balance while the exchange is still processing.
        # Set to 5s to match the connector's SHORT_POLL_INTERVAL (5 seconds).
        # ==============================================================================
        self._balance_sync_delay = 5.0  # seconds to wait after BUY fill before placing SELL

        # ==============================================================================
        # STORY A1: Multi-Timeout Lifecycle Tracking
        # ==============================================================================
        self._start_timestamp = self._strategy.current_timestamp  # Executor start time
        self._last_fill_timestamp = None  # Last fill event (any grid level)
        self._last_progress_timestamp = None  # Last closed level (TP sell filled)
        self._last_timeout_summary_log = 0  # Rate limit for summary logs (1 per 30s)
        self._timeout_close_triggered = False  # Guard: prevent double close from timeouts
        self._timeout_close_type = None  # Which timeout triggered: NO_FILL / NO_PROGRESS / HARD_CAP
        self._force_aggressive_close = False  # Bounded close: escalate to market order after grace period
        # ==============================================================================

        # ==============================================================================
        # STORY B1: Two-Phase Unwind Protocol (Graceful → Aggressive Fallback)
        # ==============================================================================
        self._unwind_phase = "NONE"  # "NONE" | "GRACEFUL" | "AGGRESSIVE"
        self._unwind_close_reason = None  # CloseType for forced exit
        self._unwind_started_ts = None  # Timestamp when unwind started
        self._unwind_attempts = 0  # Number of unwind attempts
        self._graceful_close_orders = set()  # Track graceful close order IDs
        self._aggressive_close_orders = set()  # Track aggressive close order IDs
        self._stale_close_cancel_count = 0  # Track how many times a stale close order was cancelled
        # Cancel-settle delay: After cancelling grid orders, Kraken needs ~3-5s
        # to free locked base tokens.  The sell is deferred until this timestamp.
        self._graceful_sell_earliest_ts: float = 0.0
        self._cancel_settle_delay: float = 10.0  # seconds to wait after cancel (Kraken needs 5-15s)
        # ==============================================================================

        # ==============================================================================
        # US-006: Early Stop Reason Tracking
        # ==============================================================================
        self._early_stop_reason: Optional[EarlyStopReason] = None  # Detailed reason for EARLY_STOP
        # ==============================================================================

        # ==============================================================================
        # ZOMBIE CLOSE ORDER WATCHDOG: Reset orders that exchange never confirmed
        # Tracks when each close order was locally placed. If no InFlightOrder arrives
        # within _zombie_order_watchdog_sec, the order is reset so the level retries.
        # This prevents the DOGE scenario where a sell order got a local order_id but
        # the exchange never sent a created/filled/failed event, blocking the grid.
        # ==============================================================================
        self._close_order_local_ts: dict = {}  # order_id -> strategy timestamp
        self._zombie_order_watchdog_sec = 60.0  # Reset zombie close orders after 60s
        # ==============================================================================

    @property
    def is_perpetual(self) -> bool:
        """
        Check if the exchange connector is perpetual.

        :return: True if the exchange connector is perpetual, False otherwise.
        """
        return self.is_perpetual_connector(self.config.connector_name)

    # ==========================================================================
    # US-003: Validated Order Placement
    # ==========================================================================
    def _validated_place_order(
        self,
        connector_name: str,
        trading_pair: str,
        order_type: OrderType,
        side: TradeType,
        amount: Decimal,
        price: Decimal,
        position_action: PositionAction = PositionAction.NIL,
        skip_validation: bool = False,
    ) -> Optional[str]:
        """
        Places an order after validating against trading rules and balance.

        US-003: Pre-validates orders to prevent HTTP 400 errors like:
        - "notional 0.06 < min 1" (min notional violations)
        - "Insufficient balance" (balance issues)
        - Quantity rounds to zero

        :param connector_name: The name of the connector
        :param trading_pair: The trading pair for the order
        :param order_type: The type of the order (LIMIT, MARKET)
        :param side: The side of the order (BUY or SELL)
        :param amount: The amount for the order
        :param price: The price for the order (used for notional calculation)
        :param position_action: The position action for the order
        :param skip_validation: If True, skips validation (for emergency closes)
        :return: Order ID if successful, None if validation fails
        """
        # Fall back to regular place_order if validator not available
        if not HAS_ORDER_VALIDATOR or skip_validation:
            return self.place_order(
                connector_name=connector_name,
                trading_pair=trading_pair,
                order_type=order_type,
                side=side,
                amount=amount,
                position_action=position_action,
                price=price,
            )

        # Get connector and trading rules
        connector = self.connectors.get(connector_name)
        if not connector:
            self.logger().error(f"❌ US-003: Connector {connector_name} not found")
            return None

        # Get trading rules
        try:
            trading_rules = self.get_trading_rules(connector_name, trading_pair)
        except Exception as e:
            self.logger().warning(f"⚠️  US-003: Could not get trading rules for {trading_pair}: {e} - proceeding without validation")
            return self.place_order(
                connector_name=connector_name,
                trading_pair=trading_pair,
                order_type=order_type,
                side=side,
                amount=amount,
                position_action=position_action,
                price=price,
            )

        # Get available balance
        try:
            if self.is_perpetual:
                # For PERPETUAL futures: always use quote asset (USDT) for margin
                # Both LONG (buy) and SHORT (sell) require USDT margin, not base asset
                quote_asset = trading_pair.split("-")[1] if "-" in trading_pair else "USDT"
                available_balance = connector.get_available_balance(quote_asset)
                # For perpetuals, calculate required margin based on leverage
                # This will be validated differently in validate_order_before_submit
            elif side == TradeType.BUY:
                # For spot BUY: need quote asset
                quote_asset = trading_pair.split("-")[1] if "-" in trading_pair else "USDT"
                available_balance = connector.get_available_balance(quote_asset)
            else:
                # For spot SELL: need base asset
                base_asset = trading_pair.split("-")[0] if "-" in trading_pair else trading_pair
                available_balance = connector.get_available_balance(base_asset)

                # FIX: Race condition after BUY fill - exchange balance may not be updated yet
                # If exchange reports 0 but we have tracked inventory from fills, use tracked amount
                if available_balance == Decimal("0") and self.position_size_base > Decimal("0"):
                    self.logger().debug(
                        f"📊 Balance sync fix: Exchange reports 0 {base_asset}, using tracked position "
                        f"{float(self.position_size_base):.6f} for SELL validation"
                    )
                    available_balance = self.position_size_base
        except Exception as e:
            self.logger().warning(f"⚠️  US-003: Could not get balance for {trading_pair}: {e} - proceeding without validation")
            available_balance = Decimal("999999")  # Skip balance check

        # Validate order
        result = validate_order_before_submit(
            trading_pair=trading_pair,
            side=side,
            price=price,
            quantity=amount,
            trading_rules=trading_rules,
            available_balance=available_balance,
            is_perpetual=self.is_perpetual,  # Pass perpetual flag for correct balance check
        )

        if not result.is_valid:
            # Log skip reason with context
            skip_reason = result.skip_reason.name if result.skip_reason else "UNKNOWN"
            self.logger().warning(
                f"⚠️  US-003: Order skipped | pair={trading_pair} side={side.name} "
                f"qty={float(amount):.6f} price={float(price):.6f} "
                f"reason={skip_reason} msg={result.message}"
            )
            return None

        # Use quantized values from validation result
        final_amount = result.quantized_quantity if result.quantized_quantity else amount
        final_price = result.quantized_price if result.quantized_price else price

        # Log if values were adjusted
        if final_amount != amount or final_price != price:
            self.logger().debug(
                f"📐 US-003: Order quantized | pair={trading_pair} "
                f"qty: {float(amount):.6f} → {float(final_amount):.6f}, "
                f"price: {float(price):.6f} → {float(final_price):.6f}"
            )

        # Place validated order
        return self.place_order(
            connector_name=connector_name,
            trading_pair=trading_pair,
            order_type=order_type,
            side=side,
            amount=final_amount,
            position_action=position_action,
            price=final_price,
        )
    # ==========================================================================

    async def validate_sufficient_balance(self):
        # Try to get current price, with fallback for paper trading when order book doesn't exist
        mid_price = None
        try:
            mid_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
        except (ValueError, KeyError) as e:
            # Handle missing order book in paper trading
            error_msg = str(e)
            if "No order book exists" in error_msg or "order book" in error_msg.lower():
                # Try to get price from base connector (for paper trading)
                connector = self.connectors.get(self.config.connector_name)
                if connector and hasattr(connector, '_target_market') and connector._target_market is not None:
                    try:
                        base_connector = connector._target_market()
                        if base_connector:
                            mid_price = base_connector.get_price_by_type(self.config.trading_pair, PriceType.MidPrice)
                            self.logger().debug(
                                f"Using base connector price for {self.config.trading_pair} in validate_sufficient_balance: {mid_price}"
                            )
                    except Exception as base_e:
                        self.logger().warning(
                            f"Could not get price from base connector for {self.config.trading_pair}: {base_e}"
                        )

                # If still no price, use midpoint of start_price and end_price as fallback
                if mid_price is None:
                    mid_price = self._validated_midpoint_price("validate_sufficient_balance (paper fallback)")
                    self.logger().warning(
                        f"No order book exists for {self.config.trading_pair} in paper trading. "
                        f"Using fallback price (midpoint of grid range) in validate_sufficient_balance: {mid_price}"
                    )
            else:
                # Re-raise if it's a different error
                raise

        # Ensure price is valid (should never be None at this point, but safety check)
        if mid_price is None or mid_price <= Decimal("0"):
            mid_price = self._validated_midpoint_price("validate_sufficient_balance (invalid price)")
            self.logger().warning(
                f"Invalid price in validate_sufficient_balance, using fallback: {mid_price}"
            )

        total_amount_base = self.config.total_amount_quote / mid_price

        # Debug: Log balance info before checking
        if self.is_perpetual:
            connector = self.connectors.get(self.config.connector_name)
            if connector:
                # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
                trading_pair_parts = self.config.trading_pair.split("-")
                if len(trading_pair_parts) < 2:
                    self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
                    return None
                quote_asset = trading_pair_parts[1]
                try:
                    available_balance = connector.get_available_balance(quote_asset)
                    total_balance = connector.get_balance(quote_asset)
                    exposure = self.config.total_amount_quote * Decimal(self.config.leverage)
                    required_margin = self.config.total_amount_quote / Decimal(self.config.leverage)
                    self.logger().info(
                        f"💰 Balance check for {self.config.trading_pair}:\n"
                        f"   Available balance: {available_balance} {quote_asset}\n"
                        f"   Total balance: {total_balance} {quote_asset}\n"
                        f"   Total amount quote: {self.config.total_amount_quote} {quote_asset}\n"
                        f"   Leverage: {self.config.leverage}x\n"
                        f"   Exposure: {exposure} {quote_asset} (amount * leverage)\n"
                        f"   Required margin: {required_margin} {quote_asset} (amount / leverage)\n"
                        f"   Base amount: {total_amount_base} {trading_pair_parts[0] if len(trading_pair_parts) > 0 else 'N/A'}"
                    )
                except Exception as e:
                    self.logger().warning(f"Could not get balance info: {e}")

        if self.is_perpetual:
            order_candidate = PerpetualOrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=self.config.triple_barrier_config.open_order_type.is_limit_type(),
                order_type=self.config.triple_barrier_config.open_order_type,
                order_side=self.config.side,
                amount=total_amount_base,
                price=mid_price,
                leverage=Decimal(self.config.leverage),
            )
        else:
            order_candidate = OrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=self.config.triple_barrier_config.open_order_type.is_limit_type(),
                order_type=self.config.triple_barrier_config.open_order_type,
                order_side=self.config.side,
                amount=total_amount_base,
                price=mid_price,
            )
        adjusted_order_candidates = self.adjust_order_candidates(self.config.connector_name, [order_candidate])
        self.logger().info(f"[BUDGET DEBUG] {self.config.trading_pair}: original amount={order_candidate.amount}, adjusted amount={adjusted_order_candidates[0].amount}, price={mid_price}")
        if adjusted_order_candidates[0].amount == Decimal("0"):
            # Log detailed error info
            connector = self.connectors.get(self.config.connector_name)
            if connector:
                quote_asset = self.config.trading_pair.split("-")[1]
                available_balance = connector.get_available_balance(quote_asset)
                self.logger().error(f"[BUDGET] {self.config.trading_pair}: Available {quote_asset} balance: {available_balance}, Required: {self.config.total_amount_quote}")
            if self.is_perpetual:
                connector = self.connectors.get(self.config.connector_name)
                if connector:
                    # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
                    trading_pair_parts = self.config.trading_pair.split("-")
                    if len(trading_pair_parts) < 2:
                        self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
                        self.close_type = CloseType.INSUFFICIENT_BALANCE
                        # US-006: Set early stop reason
                        self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                        self.logger().error("Not enough budget to open position.")
                        # FIX: Check if we have inventory to sell before stopping
                        self.update_position_metrics()
                        if self.position_size_base > Decimal("0"):
                            self.logger().warning(
                                f"🔄 INSUFFICIENT_BALANCE but have inventory: {self.position_size_base} - initiating forced close"
                            )
                            self.start_forced_close(CloseType.INSUFFICIENT_BALANCE)
                        else:
                            self.stop()
                        return None
                    quote_asset = trading_pair_parts[1]
                    try:
                        available_balance = connector.get_available_balance(quote_asset)
                        required_margin = self.config.total_amount_quote / Decimal(self.config.leverage)
                        self.logger().error(
                            f"❌ INSUFFICIENT BALANCE for {self.config.trading_pair}:\n"
                            f"   Available: {available_balance} {quote_asset}\n"
                            f"   Required margin: {required_margin} {quote_asset} (for {self.config.total_amount_quote} {quote_asset} with {self.config.leverage}x leverage)\n"
                            f"   Order candidate amount: {total_amount_base} {trading_pair_parts[0] if len(trading_pair_parts) > 0 else 'N/A'}\n"
                            f"   Price: {mid_price} {quote_asset}"
                        )
                    except Exception as e:
                        self.logger().error(f"Could not get balance info for error log: {e}")
            self.close_type = CloseType.INSUFFICIENT_BALANCE
            # US-006: Set early stop reason
            self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
            self.logger().error("Not enough budget to open position.")
            # FIX: Check if we have inventory to sell before stopping
            self.update_position_metrics()
            if self.position_size_base > Decimal("0"):
                self.logger().warning(
                    f"🔄 INSUFFICIENT_BALANCE but have inventory: {self.position_size_base} - initiating forced close"
                )
                self.start_forced_close(CloseType.INSUFFICIENT_BALANCE)
            else:
                self.stop()
            return None

    def _generate_grid_levels(self):
        grid_levels = []
        # Try to get current price, with fallback for paper trading when order book doesn't exist
        price = None
        try:
            price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
        except (ValueError, KeyError) as e:
            # Handle missing order book in paper trading
            error_msg = str(e)
            if "No order book exists" in error_msg or "order book" in error_msg.lower():
                # Try to get price from base connector (for paper trading)
                connector = self.connectors.get(self.config.connector_name)
                if connector and hasattr(connector, '_target_market') and connector._target_market is not None:
                    try:
                        base_connector = connector._target_market()
                        if base_connector:
                            price = base_connector.get_price_by_type(self.config.trading_pair, PriceType.MidPrice)
                            self.logger().info(
                                f"Using base connector price for {self.config.trading_pair}: {price}"
                            )
                    except Exception as base_e:
                        self.logger().warning(
                            f"Could not get price from base connector for {self.config.trading_pair}: {base_e}"
                        )

                # If still no price, use midpoint of start_price and end_price as fallback
                if price is None:
                    price = self._validated_midpoint_price("generate_grid_levels (paper fallback)")
                    self.logger().warning(
                        f"No order book exists for {self.config.trading_pair} in paper trading. "
                        f"Using fallback price (midpoint of grid range): {price}"
                    )
            else:
                # Re-raise if it's a different error
                raise

        # Ensure price is valid (should never be None at this point, but safety check)
        if price is None or price <= Decimal("0"):
            price = self._validated_midpoint_price("generate_grid_levels (invalid price)")
            self.logger().error(
                f"Invalid price for {self.config.trading_pair}, using fallback: {price}"
            )

        reference_price_for_logging = price

        # Get minimum notional and base amount increment from trading rules
        min_notional = max(
            self.config.min_order_amount_quote,
            self.trading_rules.min_notional_size
        )
        min_base_increment = self.trading_rules.min_base_amount_increment
        # Add safety margin to minimum notional to account for price movements and quantization
        min_notional_with_margin = min_notional * Decimal("1.05")  # 20% margin for safety
        # Calculate minimum base amount that satisfies both min_notional and quantization
        min_base_amount = max(
            min_notional_with_margin / price,  # Minimum from notional requirement
            min_base_increment * Decimal(str(math.ceil(float(min_notional) / float(min_base_increment * price))))
        )
        # Quantize the minimum base amount
        min_base_amount = Decimal(
            str(math.ceil(float(min_base_amount) / float(min_base_increment)))) * min_base_increment
        # Verify the quantized amount meets minimum notional
        min_quote_amount = min_base_amount * price
        # Calculate grid range and minimum step size
        grid_range = (self.config.end_price - self.config.start_price) / self.config.start_price
        min_step_size = max(
            self.config.min_spread_between_orders,
            self.trading_rules.min_price_increment / price
        )
        # Calculate maximum possible levels based on total amount
        max_possible_levels = int(self.config.total_amount_quote / min_quote_amount)
        if max_possible_levels == 0:
            # If we can't even create one level, create a single level with minimum amount
            n_levels = 1
            quote_amount_per_level = min_quote_amount
        else:
            # Calculate optimal number of levels
            max_levels_by_step = int(grid_range / min_step_size)
            n_levels = min(max_possible_levels, max_levels_by_step)
            # Calculate quote amount per level ensuring it meets minimum after quantization
            base_amount_per_level = max(
                min_base_amount,
                Decimal(str(math.floor(float(self.config.total_amount_quote / (price * n_levels)) /
                                       float(min_base_increment)))) * min_base_increment
            )
            quote_amount_per_level = base_amount_per_level * price
            # Adjust number of levels if total amount would be exceeded
            n_levels = min(n_levels, int(float(self.config.total_amount_quote) / float(quote_amount_per_level)))
        # Ensure we have at least one level
        n_levels = max(1, n_levels)
        # Generate price levels with even distribution
        if n_levels > 1:
            level_prices = Distributions.linear(n_levels, float(self.config.start_price), float(self.config.end_price))
            self.step = grid_range / (n_levels - 1)
        else:
            # For single level, use mid-point of range
            mid_price = self._validated_midpoint_price("generate_grid_levels (single level)")
            level_prices = [mid_price]
            self.step = grid_range
        take_profit = max(self.step, self.config.triple_barrier_config.take_profit) if self.config.coerce_tp_to_step else self.config.triple_barrier_config.take_profit

        # Tier 3: Dynamic TP — override with ATR-scaled TP if enabled
        custom = self.config.custom_info or {}
        if custom.get("dynamic_tp_enabled") and custom.get("atr_pct", 0) > 0:
            atr_pct = float(custom["atr_pct"])
            multiplier = float(custom.get("dynamic_tp_atr_multiplier", 0.5))
            tp_min = float(custom.get("dynamic_tp_min_pct", 0.008))
            tp_max = float(custom.get("dynamic_tp_max_pct", 0.025))
            dynamic_tp = max(tp_min, min(atr_pct * multiplier, tp_max))
            take_profit = max(self.step, Decimal(str(dynamic_tp)))
            self.logger().info(
                f"📈 Dynamic TP: ATR={atr_pct * 100:.2f}% × {multiplier} → "
                f"TP={dynamic_tp * 100:.2f}% (clamped [{tp_min * 100:.1f}%-{tp_max * 100:.1f}%])"
            )

        # Create grid levels
        for i, level_price in enumerate(level_prices):
            grid_levels.append(
                GridLevel(
                    id=f"L{i}",
                    price=level_price,
                    amount_quote=quote_amount_per_level,
                    take_profit=take_profit,
                    side=self.config.side,
                    open_order_type=self.config.triple_barrier_config.open_order_type,
                    take_profit_order_type=self.config.triple_barrier_config.take_profit_order_type,
                )
            )
        # Log grid creation details
        # BUG FIX: Validate trading_pair format before splitting for logging
        trading_pair_parts_log = self.config.trading_pair.split("-")
        quote_asset_log = trading_pair_parts_log[1] if len(trading_pair_parts_log) > 1 else "N/A"
        base_asset_log = trading_pair_parts_log[0] if len(trading_pair_parts_log) > 0 else "N/A"
        self.logger().info(
            f"Created {len(grid_levels)} grid levels with "
            f"amount per level: {quote_amount_per_level:.4f} {quote_asset_log} "
            f"(base amount: {(quote_amount_per_level / reference_price_for_logging):.8f} "
            f"{base_asset_log})"
        )
        return grid_levels

    @property
    def end_time(self) -> Optional[float]:
        """
        Calculate the end time of the position based on the time limit

        :return: The end time of the position.
        """
        if not self.config.triple_barrier_config.time_limit:
            return None
        return self.config.timestamp + self.config.triple_barrier_config.time_limit

    @property
    def is_expired(self) -> bool:
        """
        Check if the position is expired.

        :return: True if the position is expired, False otherwise.
        """
        return self.end_time and self.end_time <= self._strategy.current_timestamp

    @property
    def is_trading(self):
        """
        Check if the position is trading.

        :return: True if the position is trading, False otherwise.
        """
        return self.status == RunnableStatus.RUNNING and self.position_size_quote > Decimal("0")

    @property
    def is_active(self):
        """
        Returns whether the executor is open or trading.
        Phase 3: CLOSING is still "active" (has open position being closed)
        """
        return self._status in [RunnableStatus.RUNNING, RunnableStatus.NOT_STARTED, RunnableStatus.CLOSING, RunnableStatus.SHUTTING_DOWN]

    # ==============================================================================
    # ZOMBIE CLOSE ORDER WATCHDOG
    # ==============================================================================

    def _check_zombie_close_orders(self):
        """
        Reset close orders that were placed locally but never confirmed by the exchange.

        When place_order() returns an order_id, we create a TrackedOrder with that id.
        The exchange should then send a created/filled/failed event that populates the
        InFlightOrder on the TrackedOrder. If that event never comes (network issue,
        Kraken API dropped the request), the TrackedOrder.order stays None and the
        grid level is stuck in CLOSE_ORDER_PLACED forever — blocking ALL future close
        orders (since get_close_orders_to_create returns [] when any close is pending).

        This watchdog resets such zombie orders after _zombie_order_watchdog_sec (60s)
        so the level returns to OPEN_ORDER_FILLED and gets a fresh close order.
        """
        now = self._strategy.current_timestamp

        for level in list(self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, [])):
            co = level.active_close_order
            if co is None:
                continue

            # Skip orders that already have exchange confirmation
            if co.order is not None:
                # Clean up tracking for confirmed orders
                self._close_order_local_ts.pop(co.order_id, None)
                continue

            # Check how long ago we placed this order locally
            placed_at = self._close_order_local_ts.get(co.order_id)
            if placed_at is None:
                # No tracking entry — could be from before this feature. Start tracking now.
                self._close_order_local_ts[co.order_id] = now
                continue

            age = now - placed_at
            if age > self._zombie_order_watchdog_sec:
                self.logger().warning(
                    f"🧟 ZOMBIE_CLOSE_RESET: {self.config.trading_pair} | "
                    f"Order {co.order_id} has no exchange confirmation after {age:.0f}s "
                    f"(threshold: {self._zombie_order_watchdog_sec:.0f}s). "
                    f"Resetting level to retry close order."
                )
                self._failed_orders.append(co.order_id)
                self._close_order_local_ts.pop(co.order_id, None)
                level.reset_close_order()

    # ==============================================================================
    # STORY A1: Multi-Timeout Lifecycle Methods
    # ==============================================================================

    def _check_timeout_triggers(self) -> bool:
        """
        Check if any timeout has been exceeded and trigger close if needed.

        Returns:
            bool: True if timeout triggered close, False otherwise
        """
        # Skip if already closing or timeout already triggered
        if self._timeout_close_triggered or self.status != RunnableStatus.RUNNING:
            return False

        # Get timeout config from controller config (via executor config custom_info)
        custom_info = self.config.custom_info or {}
        no_fill_timeout = custom_info.get('no_fill_timeout_sec', 1200)  # Default 20 min
        no_progress_timeout = custom_info.get('no_progress_timeout_sec', 3600)  # Default 1h
        max_hold_time = custom_info.get('max_hold_time_sec', 14400)  # Default 4h

        now = self._strategy.current_timestamp
        age_sec = now - self._start_timestamp
        since_last_fill = (now - self._last_fill_timestamp) if self._last_fill_timestamp else age_sec
        since_last_progress = (now - self._last_progress_timestamp) if self._last_progress_timestamp else age_sec

        # Log summary every 30 seconds (rate limited)
        if now - self._last_timeout_summary_log >= 30:
            open_orders_count = len(self.levels_by_state.get(GridLevelStates.OPEN_ORDER_PLACED, []))
            close_orders_count = len(self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, []))
            self.logger().info(
                f"⏱️  Grid timeout check: {self.config.trading_pair} | "
                f"age={age_sec / 60:.1f}m | since_fill={since_last_fill / 60:.1f}m | "
                f"since_progress={since_last_progress / 60:.1f}m | "
                f"open={open_orders_count} | close={close_orders_count} | "
                f"inventory={float(self.position_size_base):.4f}"
            )
            self._last_timeout_summary_log = now

        # Check 1: No-fill timeout (no fills at all)
        if no_fill_timeout > 0 and self._last_fill_timestamp is None and age_sec >= no_fill_timeout:
            self.logger().warning(
                f"⏰ NO_FILL_TIMEOUT triggered: {self.config.trading_pair} | "
                f"age={age_sec / 60:.1f}m >= {no_fill_timeout / 60:.1f}m | No fills received"
            )
            self._timeout_close_triggered = True
            self._timeout_close_type = CloseType.NO_FILL_TIMEOUT
            self.close_type = CloseType.NO_FILL_TIMEOUT
            # US-006: Set early stop reason
            self._early_stop_reason = EarlyStopReason.NO_FILL_TIMEOUT

            # 🔧 CRITICAL FIX: Check if there's inventory before skipping unwind
            # Even with no last_fill_timestamp, partial fills might exist (e.g., from inflight orders)
            self.update_position_metrics()

            if self.position_size_base >= self.trading_rules.min_order_size:
                # Have inventory - must close position with two-phase unwind
                self.logger().warning(
                    f"⚠️  NO_FILL_TIMEOUT but have inventory: {float(self.position_size_base):.6f} "
                    f"{self.config.trading_pair.split('-')[0]} - starting forced close to prevent stuck position"
                )
                self.start_forced_close(CloseType.NO_FILL_TIMEOUT)
            else:
                # No inventory - safe to shutdown directly
                self.logger().info(
                    "✅ NO_FILL_TIMEOUT with no inventory - safe shutdown"
                )
                self.cancel_open_orders()
                self._status = RunnableStatus.SHUTTING_DOWN
            return True

        # Check 2: No-progress timeout (PRO VERSION: PnL + ATR aware)
        # Only trigger if:
        #   1. Time elapsed AND
        #   2. Unrealized loss > threshold (avoid stopping break-even/winning positions)
        #   EXCEPTION: If grid is stalled (has inventory but 0 working orders), always trigger
        if no_progress_timeout > 0 and since_last_progress >= no_progress_timeout:
            # Get PnL-aware thresholds from config
            timeout_min_loss_pct = custom_info.get('no_progress_min_loss_pct', 1.5)  # Default -1.5%
            timeout_atr_multiplier = custom_info.get('no_progress_atr_multiplier', 0.0)  # Default 0 = disabled

            # Calculate current unrealized PnL %
            self.update_position_metrics()
            unrealized_pnl_pct = self.get_net_pnl_pct() * Decimal("100")  # Convert to %

            # STALLED GRID DETECTION: If we have inventory but no working orders,
            # the grid can NEVER make progress — force close regardless of PnL.
            # This prevents capital deadlock where inventory is stuck with no sell orders.
            open_order_count = len(self.levels_by_state.get(GridLevelStates.OPEN_ORDER_PLACED, []))
            close_order_count = len(self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, []))
            has_inventory = self.position_size_base >= self.trading_rules.min_order_size

            # Also detect "zombie" close orders: orders tracked locally but never
            # confirmed by the exchange (exchange_order_id is None) or that have
            # gone stale (no fills for longer than no_progress_timeout).
            zombie_close_orders = 0
            if close_order_count > 0:
                stale_threshold = no_progress_timeout  # Same as no-progress timeout
                for level in self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, []):
                    co = level.active_close_order
                    if co is None:
                        zombie_close_orders += 1
                    elif co.order is None:
                        # Order created locally but never got InFlightOrder from exchange
                        zombie_close_orders += 1
                    elif not co.is_open and not co.is_filled and not co.is_done:
                        # Order is in limbo — not open, not filled, not done
                        zombie_close_orders += 1
                    elif co.creation_timestamp and (now - co.creation_timestamp) > stale_threshold:
                        # Order has been pending too long without any fill
                        if co.executed_amount_base == Decimal("0"):
                            zombie_close_orders += 1

            effective_close_count = close_order_count - zombie_close_orders
            is_stalled = has_inventory and open_order_count == 0 and effective_close_count <= 0

            if is_stalled:
                stall_detail = (
                    f"open={open_order_count}, close={close_order_count}, "
                    f"zombie_close={zombie_close_orders}"
                )
                self.logger().warning(
                    f"⏰ NO_PROGRESS_TIMEOUT triggered (STALLED): {self.config.trading_pair} | "
                    f"since_progress={since_last_progress / 60:.1f}m >= {no_progress_timeout / 60:.1f}m | "
                    f"inventory={float(self.position_size_base):.4f} orders=({stall_detail}) | "
                    f"unrealized_pnl={float(unrealized_pnl_pct):.2f}% | "
                    f"Grid deadlocked - forcing unwind"
                )
                self._timeout_close_triggered = True
                self._timeout_close_type = CloseType.NO_PROGRESS_TIMEOUT
                self.start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)
                return True

            # Check if we have adverse PnL (losing position)
            has_adverse_pnl = unrealized_pnl_pct < -Decimal(str(timeout_min_loss_pct))

            # Optional: Check ATR-based adverse move (if enabled)
            has_adverse_move = True  # Default: always pass if ATR check disabled
            atr_check_status = "disabled"
            if timeout_atr_multiplier > 0:
                try:
                    # Get ATR from connector/strategy (if available)
                    atr_pct = custom_info.get('atr_pct', 0.0)  # Should be set by controller
                    if atr_pct > 0:
                        # Check if price moved adversely > k × ATR from avg entry
                        avg_entry = (self.position_size_quote / self.position_size_base
                                     if self.position_size_base > Decimal("0") else None)
                        current_price = self.mid_price
                        if avg_entry and current_price:
                            move_pct = abs((current_price - avg_entry) / avg_entry) * Decimal("100")
                            threshold_move = Decimal(str(atr_pct * timeout_atr_multiplier))
                            has_adverse_move = move_pct > threshold_move
                            atr_check_status = f"move={float(move_pct):.2f}% vs threshold={float(threshold_move):.2f}% (ATR={atr_pct:.2f}% × {timeout_atr_multiplier}) → {'FAIL' if has_adverse_move else 'PASS'}"
                            self.logger().info(
                                f"🎯 ATR adverse move check: {self.config.trading_pair} | {atr_check_status}"
                            )
                        else:
                            atr_check_status = "no avg_entry or price"
                    else:
                        atr_check_status = "ATR not available, passing by default"
                        self.logger().debug(f"⚠️  ATR check enabled but atr_pct=0 for {self.config.trading_pair}")
                except Exception as e:
                    atr_check_status = f"error: {e}"
                    self.logger().warning(f"ATR check failed: {e}")

            # PRO LOGIC: Only trigger if BOTH time elapsed AND adverse conditions
            if has_adverse_pnl and has_adverse_move:
                self.logger().warning(
                    f"⏰ NO_PROGRESS_TIMEOUT triggered (PRO): {self.config.trading_pair} | "
                    f"since_progress={since_last_progress / 60:.1f}m >= {no_progress_timeout / 60:.1f}m | "
                    f"unrealized_pnl={float(unrealized_pnl_pct):.2f}% (threshold: -{timeout_min_loss_pct}%) ✓ | "
                    f"ATR check: {atr_check_status} | "
                    f"Grid stalled with adverse PnL - starting unwind"
                )
                self._timeout_close_triggered = True
                self._timeout_close_type = CloseType.NO_PROGRESS_TIMEOUT
                # Story B1: Start two-phase unwind protocol (graceful → aggressive)
                self.start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)
                return True
            else:
                # Time elapsed but NOT adverse — check extension cap.
                # Default max extension = 2x the timeout (e.g. 60m timeout → 120m extension → 180m total)
                max_extension_sec = custom_info.get('no_progress_max_extension_sec', no_progress_timeout * 2)
                extension_sec = since_last_progress - no_progress_timeout
                if max_extension_sec > 0 and extension_sec >= max_extension_sec:
                    self.logger().warning(
                        f"⏰ NO_PROGRESS_TIMEOUT triggered (MAX_EXTENSION): {self.config.trading_pair} | "
                        f"extension={extension_sec / 60:.1f}m >= max={max_extension_sec / 60:.1f}m | "
                        f"unrealized_pnl={float(unrealized_pnl_pct):.2f}% | "
                        f"Position was OK but extension limit reached - forcing unwind"
                    )
                    self._timeout_close_triggered = True
                    self._timeout_close_type = CloseType.NO_PROGRESS_TIMEOUT
                    self.start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)
                    return True

                # Log and continue
                if now - getattr(self, '_last_no_progress_log', 0) >= 60:
                    reason = []
                    if not has_adverse_pnl:
                        reason.append(f"PnL OK ({float(unrealized_pnl_pct):.2f}% > -{timeout_min_loss_pct}%)")
                    if not has_adverse_move:
                        reason.append(f"ATR OK ({atr_check_status})")

                    self.logger().info(
                        f"⏳ NO_PROGRESS_TIMEOUT time elapsed but position OK: {self.config.trading_pair} | "
                        f"since_progress={since_last_progress / 60:.1f}m >= {no_progress_timeout / 60:.1f}m | "
                        f"Reasons: {' AND '.join(reason)} | "
                        f"Extension: {extension_sec / 60:.0f}m/{max_extension_sec / 60:.0f}m | "
                        f"Allowing more time for grid to work"
                    )
                    self._last_no_progress_log = now

        # Check 3: Hard cap (max hold time)
        if max_hold_time > 0 and age_sec >= max_hold_time:
            self.logger().warning(
                f"⏰ HARD_CAP_TIME_LIMIT triggered: {self.config.trading_pair} | "
                f"age={age_sec / 60:.1f}m >= {max_hold_time / 60:.1f}m | "
                f"Maximum hold time exceeded - forcing rotation"
            )
            self._timeout_close_triggered = True
            self._timeout_close_type = CloseType.HARD_CAP_TIME_LIMIT
            # Story B1: Start two-phase unwind protocol (graceful → aggressive)
            self.start_forced_close(CloseType.HARD_CAP_TIME_LIMIT)
            return True

        return False

    def _check_bounded_close_escalation(self) -> bool:
        """
        Story A1: Check if we should escalate from graceful close to aggressive close.
        Returns True if escalation triggered (forces market order).
        """
        if not self._timeout_close_triggered or self.status != RunnableStatus.CLOSING:
            return False

        # Get close_grace_sec from config
        custom_info = self.config.custom_info or {}
        close_grace_sec = custom_info.get('close_grace_sec', 120)  # Default 2 min

        # Check if close order is stuck (no fill after grace period)
        if self._close_order and self._close_order_id:
            try:
                connector = self.connectors[self.config.connector_name]
                in_flight_order = connector.in_flight_orders.get(self._close_order_id)

                # CRITICAL FIX (2026-02-26): Also check TrackedOrder's cached InFlightOrder
                if in_flight_order is None and self._close_order and self._close_order.order:
                    in_flight_order = self._close_order.order

                if in_flight_order and not in_flight_order.is_done:
                    # Check how long order has been open
                    order_age = self._strategy.current_timestamp - in_flight_order.creation_timestamp

                    if order_age >= close_grace_sec:
                        self.logger().warning(
                            f"⚠️  Story A1 Bounded Close: Graceful close failed after {order_age:.0f}s "
                            f"(grace period: {close_grace_sec}s) | "
                            f"Cancelling maker order + forcing aggressive close for {self.config.trading_pair}"
                        )
                        # Cancel stuck order
                        self._strategy.cancel(
                            connector_name=self.config.connector_name,
                            trading_pair=self.config.trading_pair,
                            order_id=self._close_order_id
                        )
                        # Reset close tracking to allow aggressive close
                        self._closing_in_progress = False
                        self._close_order_id = None
                        # Set flag to force market order on next close attempt
                        self._force_aggressive_close = True
                        return True
                elif in_flight_order is None:
                    # CRITICAL FIX (2026-02-26): Order not in any tracker - check age
                    # If order was placed but is no longer tracked, it's likely completed
                    order_timestamp = getattr(self._close_order, 'creation_timestamp', None)
                    if order_timestamp:
                        order_age = self._strategy.current_timestamp - order_timestamp
                        if order_age > 60:
                            self.logger().info(
                                f"✅ Story A1: Close order assumed completed (order_id: {self._close_order_id}, "
                                f"order age: {order_age:.0f}s) - not found in any tracker"
                            )
                            # Reset state - the control_close_process will handle the transition
                            self._closing_in_progress = False
                            self._close_order_id = None
                            return True
            except Exception as e:
                self.logger().warning(f"⚠️  Could not check bounded close escalation: {e}")

        return False

    # ==============================================================================
    # STORY B1: Two-Phase Unwind Protocol (Graceful → Aggressive Fallback)
    # ==============================================================================

    def start_forced_close(self, close_reason: CloseType) -> None:
        """
        Story B1: Start forced close with two-phase protocol (graceful → aggressive).

        This method is idempotent - can be called multiple times with different reasons.
        Higher priority reason wins (e.g., RISK_KILL_SWITCH > STOP_LOSS > TIME_LIMIT).

        Args:
            close_reason: CloseType indicating why we're forcing close

        Flow:
            1. Check idempotency (already closing with higher priority reason?)
            2. Cancel non-essential open orders
            3. Start graceful phase (maker/limit close orders)
            4. Transition to CLOSING status
        """
        from hummingbot.strategy_v2.models.executors import get_close_type_priority

        # Skip if already fully closed
        if self._status == RunnableStatus.TERMINATED:
            self.logger().debug(
                f"Story B1: Ignoring start_forced_close({close_reason}) - executor already terminated"
            )
            return

        # Idempotency: Check if already unwinding with higher priority reason
        if self._unwind_phase != "NONE" and self._unwind_close_reason is not None:
            current_priority = get_close_type_priority(self._unwind_close_reason)
            new_priority = get_close_type_priority(close_reason)

            if new_priority <= current_priority:
                self.logger().debug(
                    f"Story B1: Ignoring start_forced_close({close_reason}, priority={new_priority}) - "
                    f"already unwinding with {self._unwind_close_reason} (priority={current_priority})"
                )
                return
            else:
                self.logger().warning(
                    f"🔄 Story B1: Upgrading unwind reason from {self._unwind_close_reason} "
                    f"(priority={current_priority}) to {close_reason} (priority={new_priority})"
                )

        # Initialize unwind state
        if self._unwind_phase == "NONE":
            self._unwind_started_ts = self._strategy.current_timestamp
            self._unwind_attempts = 0

        self._unwind_close_reason = close_reason
        self.close_type = close_reason

        # Get current inventory
        self.update_position_metrics()
        remaining_inventory = self.position_size_base

        # Log unwind start
        self.logger().info(
            f"🚨 UNWIND_PHASE_START phase=GRACEFUL reason={close_reason.name} "
            f"pair={self.config.trading_pair} inv={float(remaining_inventory):.6f}"
        )

        # Step 1: Cancel all non-essential open orders (buy orders for LONG grid)
        self._cancel_non_essential_orders()

        # Step 2: Start graceful phase
        self._unwind_phase = "GRACEFUL"

        # Reset insufficient-funds counter — previous retries were from the
        # cancel-settle race, not genuine balance problems.
        self._insufficient_funds_retries = 0

        # 🔧 FIX: Always try to close inventory if any exists
        # Let the exchange reject if it's too small - don't skip preemptively
        if remaining_inventory <= Decimal("0"):
            self.logger().info(
                f"✅ UNWIND_DONE reason={close_reason.name} inv=0 (no position to close)"
            )
            self._status = RunnableStatus.SHUTTING_DOWN
            self._unwind_phase = "DONE"
            return

        # Step 3: Defer the sell order to let cancel settle on the exchange.
        # The GRACEFUL_RETRY block in control_task will place the sell after
        # _cancel_settle_delay seconds have elapsed.
        self._graceful_sell_earliest_ts = (
            self._strategy.current_timestamp + self._cancel_settle_delay
        )
        self.logger().info(
            f"⏳ Cancel-settle delay: deferring graceful sell by "
            f"{self._cancel_settle_delay:.0f}s for {self.config.trading_pair}"
        )

        # Step 4: Transition to CLOSING status
        if self._status != RunnableStatus.CLOSING:
            self._status = RunnableStatus.CLOSING

        self._unwind_attempts += 1

    def _cancel_non_essential_orders(self) -> None:
        """Cancel ALL grid orders (buy AND sell) during unwind.

        During forced close / unwind the executor will sell the entire position
        in a single graceful (then aggressive) order.  Any remaining individual
        grid SELL orders lock base-asset balance on the exchange, which causes
        ``_cap_sell_to_available`` to cap the unwind sell to less than the full
        inventory — leaving an orphan for the remainder.

        By also cancelling grid close (sell) orders here we free ALL base tokens
        so the unwind sell covers the full position.
        """
        # Cancel open BUY orders (grid entry orders)
        open_order_levels = self.levels_by_state.get(GridLevelStates.OPEN_ORDER_PLACED, [])

        for level in open_order_levels:
            if level.active_open_order and level.active_open_order.order_id:
                self.logger().debug(
                    f"Story B1: Cancelling open order {level.active_open_order.order_id} "
                    f"at price {level.price}"
                )
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=level.active_open_order.order_id
                )

        # Cancel grid SELL/close orders to free locked base tokens
        close_order_levels = self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, [])

        for level in close_order_levels:
            if level.active_close_order and level.active_close_order.order_id:
                self.logger().debug(
                    f"Story B1: Cancelling grid close order {level.active_close_order.order_id} "
                    f"to free base tokens for unwind"
                )
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=level.active_close_order.order_id
                )

    def _place_graceful_close_orders(self, inventory: Decimal) -> None:
        """
        Place maker/limit close orders for remaining inventory.

        Uses best bid/ask with slight offset to avoid being maker but still competitive.

        IMPORTANT: We intentionally do NOT call _cap_sell_to_available() here.
        At graceful-close start we just fired cancels for all grid sell orders,
        but the exchange may not have settled them yet — so get_available_balance()
        would still report the old (lower) amount, causing us to sell less than
        the full position and orphan the remainder.  Instead we trust the
        inventory figure from position tracking (position_size_base).  If the
        exchange rejects the order (cancel not yet settled), the aggressive phase
        will retry with _determine_close_order_amount which has a balance-wait
        retry loop.
        """
        if inventory <= Decimal("0"):
            return

        try:
            # Get current price for close order
            close_price = self.get_price(
                self.config.connector_name,
                self.config.trading_pair,
                self.close_order_price_type  # Best ask for SELL (long close)
            )

            # Add small offset to improve fill probability while staying maker
            # For SELL: use ask + 0.05% (slightly above best ask)
            price_offset = Decimal("1.0005") if self.close_order_side == TradeType.SELL else Decimal("0.9995")
            adjusted_price = close_price * price_offset

            # Quantize price to trading rules
            adjusted_price = self.connectors[self.config.connector_name].quantize_order_price(
                self.config.trading_pair, adjusted_price
            )

            # Quantize amount to trading rules
            quantized_amount = self.connectors[self.config.connector_name].quantize_order_amount(
                self.config.trading_pair, inventory
            )

            # 🔧 FIX: Try to place order regardless of size - let exchange reject if needed
            if quantized_amount <= Decimal("0"):
                self.logger().warning(
                    f"Story B1: Quantized amount is zero for inventory {inventory} - cannot place order"
                )
                return

            order_value = quantized_amount * adjusted_price
            self.logger().info(
                f"📤 Story B1: Placing graceful close order | "
                f"side={self.close_order_side.name} amount={float(quantized_amount):.6f} "
                f"price={float(adjusted_price):.6f} value=€{float(order_value):.2f}"
            )

            # Place limit maker order
            order_id = self.place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=OrderType.LIMIT,  # Maker order for graceful close
                side=self.close_order_side,
                amount=quantized_amount,
                price=adjusted_price
            )

            if order_id:
                self._graceful_close_orders.add(order_id)
                self._close_order_id = order_id  # Track for existing logic compatibility
                self._close_order = TrackedOrder(order_id=order_id)
                self._closing_in_progress = True
            else:
                # Order was rejected but no exception - likely too small
                self.logger().warning(
                    "⚠️  Story B1: Graceful close order rejected (likely too small) - "
                    "will try aggressive close after grace period"
                )

        except Exception as e:
            # 🔧 FIX: Log rejection and continue - don't crash, let aggressive phase handle it
            self.logger().warning(
                f"⚠️  Story B1: Failed to place graceful close order: {e} - "
                f"will try aggressive close after grace period"
            )

    async def _check_unwind_phase_transition(self) -> None:
        """
        Check if we should transition from GRACEFUL to AGGRESSIVE phase.
        Called from control_task when in CLOSING status.
        """
        if self._unwind_phase != "GRACEFUL":
            return

        # Get close_grace_sec from config
        custom_info = self.config.custom_info or {}
        close_grace_sec = custom_info.get('close_grace_sec', 120)  # Default 2 min

        # Check if grace period expired
        now = self._strategy.current_timestamp
        time_in_graceful = now - self._unwind_started_ts

        if time_in_graceful >= close_grace_sec:
            # Check if we still have inventory
            self.update_position_metrics()
            remaining_inventory = self.position_size_base

            # 🔧 FIX: Try aggressive close for ANY remaining inventory, not just > min_order_size
            if remaining_inventory > Decimal("0"):
                self.logger().warning(
                    f"⚠️  UNWIND_PHASE_START phase=AGGRESSIVE reason={self._unwind_close_reason.name} | "
                    f"Graceful phase failed after {time_in_graceful:.0f}s | "
                    f"Remaining inv={float(remaining_inventory):.6f} | "
                    f"Escalating to aggressive close"
                )

                # Cancel all graceful close orders AND remaining grid close orders
                self._cancel_graceful_close_orders()
                self._cancel_remaining_grid_close_orders()

                # Transition to aggressive phase
                self._unwind_phase = "AGGRESSIVE"
                self._closing_in_progress = True  # Keep guard active during async order setup

                # Place aggressive close order (market or IOC)
                await self._place_aggressive_close_orders(remaining_inventory)

    def _cancel_graceful_close_orders(self) -> None:
        """Cancel all graceful close orders."""
        for order_id in list(self._graceful_close_orders):
            try:
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=order_id
                )
                self.logger().debug(f"Story B1: Cancelled graceful close order {order_id}")
            except Exception as e:
                self.logger().warning(f"Could not cancel graceful order {order_id}: {e}")

        self._graceful_close_orders.clear()
        self._closing_in_progress = False
        self._close_order_id = None

    def _cancel_remaining_grid_close_orders(self) -> None:
        """Cancel any remaining grid-level close (sell) orders to free locked base tokens.

        Called before aggressive close to ensure the full inventory is available
        for the MARKET sell order, preventing partial-fill orphans.
        """
        close_order_levels = self.levels_by_state.get(GridLevelStates.CLOSE_ORDER_PLACED, [])
        for level in close_order_levels:
            if level.active_close_order and level.active_close_order.order_id:
                try:
                    self._strategy.cancel(
                        connector_name=self.config.connector_name,
                        trading_pair=self.config.trading_pair,
                        order_id=level.active_close_order.order_id
                    )
                    self.logger().debug(
                        f"Story B1: Cancelled grid close order {level.active_close_order.order_id} "
                        f"to free base tokens for aggressive close"
                    )
                except Exception as e:
                    self.logger().warning(
                        f"Could not cancel grid close order {level.active_close_order.order_id}: {e}"
                    )

    async def _place_aggressive_close_orders(self, inventory: Decimal) -> None:
        """
        Place aggressive close orders (market or taker IOC) for remaining inventory.

        Uses config aggressive_close_method to determine order type.
        After cancelling graceful orders, the exchange may still report the base
        balance as locked.  We use ``_determine_close_order_amount`` to wait for
        the balance to unlock (up to ~5 s) before placing the market order.
        """
        if inventory <= Decimal("0"):
            return

        # Wait for balance unlock after graceful-order cancellation.
        # _determine_close_order_amount retries up to _close_balance_max_retries
        # times, sleeping _close_balance_retry_interval between each attempt.
        resolved = await self._determine_close_order_amount(inventory)
        if resolved is not None and resolved > Decimal("0"):
            inventory = resolved
        else:
            # Fallback: cap to whatever is available right now
            inventory = self._cap_sell_to_available(inventory)
            if inventory <= Decimal("0"):
                self.logger().warning(
                    f"⚠️  Aggressive close: no available {self.config.trading_pair.split('-')[0]} "
                    f"balance after waiting — transitioning to SHUTTING_DOWN"
                )
                self._status = RunnableStatus.SHUTTING_DOWN
                self._unwind_phase = "DONE"
                self._closing_in_progress = False
                return

        try:
            # Get config for aggressive close
            custom_info = self.config.custom_info or {}
            close_method = custom_info.get('aggressive_close_method', 'MARKET')
            slippage_guard_pct = custom_info.get('aggressive_close_slippage_guard_pct', Decimal("0.30"))

            # Quantize amount
            quantized_amount = self.connectors[self.config.connector_name].quantize_order_amount(
                self.config.trading_pair, inventory
            )

            # 🔧 FIX: Try to place order regardless of size - let exchange reject if needed
            if quantized_amount <= Decimal("0"):
                self.logger().warning(
                    f"Story B1: Quantized amount is zero for inventory {inventory} - cannot place order"
                )
                self._status = RunnableStatus.SHUTTING_DOWN
                self._unwind_phase = "DONE"
                self._closing_in_progress = False
                return

            current_price = self.mid_price if self.mid_price else Decimal("1")
            order_value = quantized_amount * current_price

            if close_method == "MARKET":
                # Place market-equivalent order with slippage guard.
                # Instead of a raw MARKET order (no price protection), we use a
                # LIMIT order priced aggressively with slippage_guard_pct as a
                # safety ceiling.  This ensures the fill never exceeds the guard.
                try:
                    current_price = self.get_price(
                        self.config.connector_name,
                        self.config.trading_pair,
                        self.close_order_price_type
                    )
                except Exception:
                    current_price = self.mid_price if self.mid_price else Decimal("0")

                # Apply slippage guard as price ceiling/floor
                if current_price and current_price > Decimal("0"):
                    slippage_mult = (
                        (Decimal("1") - slippage_guard_pct / Decimal("100"))
                        if self.close_order_side == TradeType.SELL
                        else (Decimal("1") + slippage_guard_pct / Decimal("100"))
                    )
                    guarded_price = current_price * slippage_mult

                    # Quantize price to exchange precision
                    guarded_price = self.connectors[self.config.connector_name].quantize_order_price(
                        self.config.trading_pair, guarded_price
                    )

                    self.logger().warning(
                        f"🚨 Story B1: Placing MARKET close order (slippage-guarded) | "
                        f"side={self.close_order_side.name} amount={float(quantized_amount):.6f} "
                        f"value=€{float(order_value):.2f} "
                        f"price={float(guarded_price):.6f} "
                        f"(mid={float(current_price):.6f}, guard={float(slippage_guard_pct):.2f}%)"
                    )

                    order_id = self.place_order(
                        connector_name=self.config.connector_name,
                        trading_pair=self.config.trading_pair,
                        order_type=OrderType.LIMIT,
                        side=self.close_order_side,
                        amount=quantized_amount,
                        price=guarded_price,
                    )
                else:
                    # Fallback: no valid price, use raw MARKET as last resort
                    self.logger().warning(
                        f"🚨 Story B1: Placing raw MARKET close order (no price available) | "
                        f"side={self.close_order_side.name} amount={float(quantized_amount):.6f} "
                        f"value=€{float(order_value):.2f}"
                    )

                    order_id = self.place_order(
                        connector_name=self.config.connector_name,
                        trading_pair=self.config.trading_pair,
                        order_type=OrderType.MARKET,
                        side=self.close_order_side,
                        amount=quantized_amount,
                        price=current_price,
                    )

            else:  # TAKER_LIMIT_IOC
                # Place IOC limit order with slippage guard
                current_price = self.get_price(
                    self.config.connector_name,
                    self.config.trading_pair,
                    self.close_order_price_type
                )

                # Apply slippage: For SELL, go below best bid. For BUY, go above best ask.
                slippage_mult = (Decimal("1") - slippage_guard_pct / Decimal("100")) \
                    if self.close_order_side == TradeType.SELL \
                    else (Decimal("1") + slippage_guard_pct / Decimal("100"))

                aggressive_price = current_price * slippage_mult

                # Quantize price
                aggressive_price = self.connectors[self.config.connector_name].quantize_order_price(
                    self.config.trading_pair, aggressive_price
                )

                self.logger().warning(
                    f"🚨 Story B1: Placing IOC close order | "
                    f"side={self.close_order_side.name} amount={float(quantized_amount):.6f} "
                    f"price={float(aggressive_price):.6f} (slippage={float(slippage_guard_pct):.2f}%)"
                )

                order_id = self.place_order(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_type=OrderType.LIMIT,  # IOC is usually a limit order flag
                    side=self.close_order_side,
                    amount=quantized_amount,
                    price=aggressive_price,
                    # Note: IOC flag depends on connector - some use position_action=CLOSE
                )

            if order_id:
                self._aggressive_close_orders.add(order_id)
                self._close_order_id = order_id
                self._close_order = TrackedOrder(order_id=order_id)
                self._closing_in_progress = True
                self._force_aggressive_close = True  # Set flag for existing logic compatibility
            else:
                # Order was rejected but no exception - likely too small
                self.logger().warning(
                    f"⚠️  Story B1: Aggressive close order rejected (likely too small) - "
                    f"inventory will remain: {float(quantized_amount):.6f} (€{float(order_value):.2f})"
                )
                # Accept the loss and continue - don't keep retrying
                self._status = RunnableStatus.SHUTTING_DOWN
                self._unwind_phase = "DONE"

        except Exception as e:
            # 🔧 FIX: Log rejection and continue - don't crash or retry endlessly
            self.logger().warning(
                f"⚠️  Story B1: Failed to place aggressive close order: {e} - "
                f"inventory will remain: {float(quantized_amount):.6f} (€{float(order_value):.2f})"
            )
            # Accept the loss and move on - don't block the bot
            self._status = RunnableStatus.SHUTTING_DOWN
            self._unwind_phase = "DONE"

    # ==============================================================================

    async def control_task(self):
        """
        This method is responsible for controlling the task based on the status of the executor.

        :return: None
        """
        self.update_grid_levels()
        self.update_metrics()
        if self.status == RunnableStatus.RUNNING:
            # Story A1: Check timeout triggers FIRST (before triple barrier)
            if self._check_timeout_triggers():
                return  # Timeout triggered, skip normal control logic

            if self.control_triple_barrier():
                self.cancel_open_orders()
                self._status = RunnableStatus.SHUTTING_DOWN
                return
            open_orders_to_create = self.get_open_orders_to_create()
            close_orders_to_create = self.get_close_orders_to_create()
            open_order_ids_to_cancel = self.get_open_order_ids_to_cancel()
            close_order_ids_to_cancel = self.get_close_order_ids_to_cancel()
            for level in open_orders_to_create:
                self.adjust_and_place_open_order(level)

            # ==============================================================================
            # EXCHANGE BALANCE SYNC FIX: Force balance refresh before placing SELL orders
            # Kraken/Bitget only poll balances every 5 seconds via REST API.
            # After a BUY fill, the local balance cache may still show 0.
            # Force a fresh balance fetch before attempting to place SELL orders.
            # ==============================================================================
            if close_orders_to_create:
                self.logger().debug(
                    f"🔄 Executor {self.config.id[:8]}... Refreshing balance before placing "
                    f"{len(close_orders_to_create)} close order(s)"
                )
                await self._refresh_connector_balances()

            for level in close_orders_to_create:
                self.adjust_and_place_close_order(level)
            for orders_id_to_cancel in open_order_ids_to_cancel + close_order_ids_to_cancel:
                # TODO: Implement batch order cancel
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=orders_id_to_cancel
                )

            # ZOMBIE WATCHDOG: Reset close orders that exchange never confirmed
            self._check_zombie_close_orders()
        elif self.status == RunnableStatus.CLOSING:
            # Story B1: Check if we should transition from graceful to aggressive phase
            await self._check_unwind_phase_transition()

            # Story A1: Check if we should escalate to aggressive close
            if self._check_bounded_close_escalation():
                # Escalation triggered - bounded close will force market order on next iteration
                return

            # Phase 3: State machine - check if close order is filled
            if self._close_order and self._close_order_id:
                # PRIMARY: Check order status (more reliable than balance)
                try:
                    connector = self.connectors[self.config.connector_name]
                    # Try to get order from connector's order tracker
                    in_flight_order = connector.in_flight_orders.get(self._close_order_id)

                    # CRITICAL FIX (2026-02-26): Also check TrackedOrder's cached InFlightOrder
                    # When order is filled and removed from connector's in_flight_orders,
                    # the TrackedOrder may still have a reference to the InFlightOrder with correct state.
                    # This was causing the CRV stuck bug where filled orders were not detected.
                    if in_flight_order is None and self._close_order and self._close_order.order:
                        in_flight_order = self._close_order.order
                        self.logger().debug(
                            f"🔍 PHASE 3.5: Using TrackedOrder's cached InFlightOrder "
                            f"(order_id: {self._close_order_id}, state: {getattr(in_flight_order, 'current_state', 'unknown')})"
                        )

                    if in_flight_order:
                        if in_flight_order.is_done:  # FILLED, CANCELED, or FAILED
                            if in_flight_order.is_filled:
                                self.logger().info(
                                    f"✅ PHASE 3.5: Close order FILLED via order status check "
                                    f"(order_id: {self._close_order_id}, state: {in_flight_order.current_state})"
                                )
                                self._status = RunnableStatus.SHUTTING_DOWN
                                self._closing_in_progress = False
                                return
                            elif in_flight_order.is_cancelled or in_flight_order.is_failure:
                                self.logger().warning(
                                    f"⚠️  PHASE 3.5: Close order {in_flight_order.current_state} "
                                    f"(order_id: {self._close_order_id}) - resetting guard to allow retry"
                                )
                                self._closing_in_progress = False  # Allow retry
                                self._close_order_id = None
                                return
                        else:
                            # Order still pending
                            self.logger().debug(
                                f"⏳ Close order still pending (order_id: {self._close_order_id}, "
                                f"state: {in_flight_order.current_state})"
                            )
                            # STALE CLOSE ORDER TIMEOUT: cancel and re-place if pending too long
                            custom_info = self.config.custom_info or {}
                            stale_close_timeout = custom_info.get('stale_close_timeout_sec', 300)
                            order_age = self._strategy.current_timestamp - in_flight_order.creation_timestamp
                            if order_age >= stale_close_timeout:
                                self._stale_close_cancel_count += 1
                                self.logger().warning(
                                    f"⏰ STALE_CLOSE_ORDER: {self.config.trading_pair} | "
                                    f"Close order {self._close_order_id} pending for {order_age:.0f}s "
                                    f"(timeout: {stale_close_timeout}s) | "
                                    f"Cancel #{self._stale_close_cancel_count} to allow re-placement"
                                )
                                try:
                                    self._strategy.cancel(
                                        connector_name=self.config.connector_name,
                                        trading_pair=self.config.trading_pair,
                                        order_id=self._close_order_id
                                    )
                                except Exception as cancel_err:
                                    self.logger().warning(
                                        f"⚠️  Failed to cancel stale close order: {cancel_err}"
                                    )
                                # process_order_canceled_event will reset state
                                return
                    else:
                        # CRITICAL FIX (2026-02-26): Order not found anywhere!
                        # This happens when the order was filled and fully cleaned up from all trackers.
                        # Check if enough time has passed to assume it completed.
                        order_timestamp = getattr(self._close_order, 'creation_timestamp', None)
                        if order_timestamp:
                            order_age = self._strategy.current_timestamp - order_timestamp
                            # If order was placed >60s ago and is not in any tracker, assume it filled
                            if order_age > 60:
                                self.logger().info(
                                    f"✅ PHASE 3.5: Close order ASSUMED FILLED (order_id: {self._close_order_id}) - "
                                    f"order age: {order_age:.0f}s, not found in any tracker"
                                )
                                self._status = RunnableStatus.SHUTTING_DOWN
                                self._closing_in_progress = False
                                return

                    # SECONDARY: Balance sanity check (in case order status not available)
                    #
                    # CRITICAL FIX (2026-02-23): Use get_balance() (total) instead of get_available_balance()!
                    # When we have a pending LIMIT SELL order, our tokens are in "reserved" not "available".
                    # Using get_available_balance() would incorrectly show ~0 and trigger premature shutdown.
                    # This was the root cause of the SWEAT bug.
                    trading_pair_parts = self.config.trading_pair.split("-")
                    if len(trading_pair_parts) >= 2:
                        base_asset = trading_pair_parts[0]
                        # Use get_balance() for total (available + reserved) balance
                        total_balance = self._coerce_to_decimal(
                            connector.get_balance(base_asset)
                        )
                        min_order_size = getattr(self.trading_rules, "min_order_size", Decimal("0"))

                        # Only if TOTAL balance is truly dust (< 10% of min), force transition
                        if total_balance < min_order_size * Decimal("0.1"):
                            self.logger().info(
                                f"✅ PHASE 3.5: Position closed by BALANCE FALLBACK check "
                                f"(total_balance: {total_balance} {base_asset} < dust threshold {min_order_size * Decimal('0.1')})"
                            )
                            self._status = RunnableStatus.SHUTTING_DOWN
                            self._closing_in_progress = False
                        else:
                            # Story C1: Throttle position check log to max 1 per 120s per executor
                            if HAS_LOG_THROTTLE and should_log(f"close_pending_{self.config.id}", interval_sec=120):
                                self.logger().debug(
                                    f"⏳ PHASE 3.5: Close order pending - order_id: {self._close_order_id}, "
                                    f"total_balance: {total_balance} {base_asset}, min_order: {min_order_size} {base_asset}"
                                )
                except Exception as e:
                    self.logger().warning(f"⚠️  Could not check close progress: {e}")
            elif self._close_order_id:
                # ZOMBIE GUARD SAFETY NET: If order was already cancelled or failed, reset guard
                if self._close_order_id in self._canceled_orders or self._close_order_id in self._failed_orders:
                    source = "cancelled" if self._close_order_id in self._canceled_orders else "failed"
                    self.logger().warning(
                        f"⚠️  ZOMBIE_GUARD_RESET: Close order {self._close_order_id} was {source} "
                        f"but guard was still active - resetting to allow retry"
                    )
                    self._closing_in_progress = False
                    self._close_order_id = None
                    return
                # Order ID assigned but TrackedOrder not yet created by exchange event
                self.logger().debug(
                    f"⏳ Close order placed (id={self._close_order_id}) awaiting exchange confirmation"
                )
            elif self._closing_in_progress or self._unwind_phase in ("GRACEFUL", "AGGRESSIVE"):
                # GRACEFUL RETRY: If in GRACEFUL phase with no active close order,
                # re-place the order (cancel may have settled since first attempt)
                if (self._unwind_phase == "GRACEFUL"
                        and not self._closing_in_progress
                        and not self._close_order_id):
                    # Respect cancel-settle delay before placing the sell
                    now = self._strategy.current_timestamp
                    if now < self._graceful_sell_earliest_ts:
                        wait_left = self._graceful_sell_earliest_ts - now
                        self.logger().debug(
                            f"⏳ Cancel-settle wait: {self.config.trading_pair} "
                            f"| {wait_left:.1f}s remaining before SELL"
                        )
                        return
                    self.update_position_metrics()
                    remaining = self.position_size_base
                    if remaining > Decimal("0"):
                        # FIX: If we had insufficient-funds failures, cap to available
                        # balance so the retry doesn't fail with the same amount.
                        if self._insufficient_funds_retries > 0:
                            remaining = self._cap_sell_to_available(remaining)
                        self.logger().info(
                            f"🔄 GRACEFUL_RETRY: {self.config.trading_pair} | "
                            f"Phase=GRACEFUL but no close order active | "
                            f"Re-placing graceful close for {float(remaining):.6f}"
                        )
                        if remaining > Decimal("0"):
                            self._place_graceful_close_orders(remaining)
                        else:
                            self.logger().warning(
                                f"⚠️  GRACEFUL_RETRY: Available balance is 0 for "
                                f"{self.config.trading_pair} — escalating to AGGRESSIVE"
                            )
                            # Force transition to aggressive phase immediately
                            self._unwind_phase = "AGGRESSIVE"
                            self._unwind_started_ts = (
                                self._strategy.current_timestamp
                                - (self.config.custom_info or {}).get('close_grace_sec', 120)
                            )
                    else:
                        self.logger().info(
                            f"✅ Position fully closed for {self.config.trading_pair} "
                            f"- transitioning to SHUTTING_DOWN"
                        )
                        self._status = RunnableStatus.SHUTTING_DOWN
                        self._unwind_phase = "DONE"
                        self._closing_in_progress = False
                # AGGRESSIVE RETRY: If in AGGRESSIVE phase with no active close order,
                # re-place the order (e.g., after stale close cancel or failed placement)
                elif (self._unwind_phase == "AGGRESSIVE"
                        and not self._closing_in_progress
                        and not self._close_order_id):
                    self.update_position_metrics()
                    remaining = self.position_size_base
                    if remaining > Decimal("0"):
                        self.logger().warning(
                            f"🔄 AGGRESSIVE_RETRY: {self.config.trading_pair} | "
                            f"Phase=AGGRESSIVE but no close order active | "
                            f"Re-placing aggressive close for {float(remaining):.6f}"
                        )
                        self._closing_in_progress = True
                        await self._place_aggressive_close_orders(remaining)
                    else:
                        self.logger().info(
                            f"✅ Position fully closed for {self.config.trading_pair} "
                            f"- transitioning to SHUTTING_DOWN"
                        )
                        self._status = RunnableStatus.SHUTTING_DOWN
                        self._unwind_phase = "DONE"
                        self._closing_in_progress = False
                else:
                    # Active close/unwind in progress (e.g., aggressive order being set up)
                    self.logger().debug(
                        f"⏳ Close process active (phase={self._unwind_phase}, "
                        f"closing_in_progress={self._closing_in_progress}) - waiting"
                    )
            else:
                # No close order tracked and no active close phase
                self.logger().warning("⚠️  In CLOSING state but no close order tracked - transitioning to SHUTTING_DOWN")
                self._status = RunnableStatus.SHUTTING_DOWN
                self._closing_in_progress = False
        elif self.status == RunnableStatus.SHUTTING_DOWN:
            await self.control_shutdown_process()

        # Story C1: Periodic throttled summary log (max 1 per 300s = 5min per executor)
        if HAS_LOG_THROTTLE and should_log(f"executor_summary_{self.config.id}", interval_sec=300):
            try:
                slog = StructuredLogger(self.logger())
                slog.info(
                    "EXECUTOR_SUMMARY",
                    symbol=self.config.trading_pair,
                    status=self.status.name,
                    pnl_net=float(self.net_pnl_quote) if hasattr(self, 'net_pnl_quote') else 0.0,
                    open_fills=len(self.open_fills),
                    close_fills=len(self.close_fills) if hasattr(self, 'close_fills') else 0,
                    phase=getattr(self, '_unwind_phase', 'N/A')
                )
            except Exception:
                pass  # Silently skip if summary fails

        self.evaluate_max_retries()

    def early_stop(self, keep_position: bool = False, reason: Optional[EarlyStopReason] = None):
        """
        This method allows strategy to stop the executor early.

        :param keep_position: If True, keep the position open (POSITION_HOLD). If False, close it (EARLY_STOP).
        :param reason: Optional EarlyStopReason to explain WHY the executor stopped early (US-006).
        :return: None
        """
        self.cancel_open_orders()
        self._status = RunnableStatus.SHUTTING_DOWN
        self.close_type = CloseType.POSITION_HOLD if keep_position else CloseType.EARLY_STOP

        # US-006: Store detailed early stop reason
        if reason is not None:
            self._early_stop_reason = reason
            self.logger().info(f"🛑 US-006: Early stop reason: {reason.name} ({reason.value})")
        elif self._early_stop_reason is None:
            # Set default reason if none provided
            self._early_stop_reason = EarlyStopReason.UNKNOWN

        # If keep_position=False, close any open position immediately
        if not keep_position:
            # 🔧 FIX: Force process pending fills BEFORE calculating position
            # This prevents partial sells when recent fills aren't processed yet
            try:
                # Process any pending order updates/fills
                connector = self.connectors[self.config.connector_name]
                if hasattr(connector, '_process_trade_fills'):
                    connector._process_trade_fills()

                # Also update in-flight orders to ensure all fills are tracked
                if hasattr(connector, '_update_inflight_orders'):
                    connector._update_inflight_orders()

                self.logger().debug(f"🔄 Processed pending fills before stop for {self.config.trading_pair}")
            except Exception as e:
                self.logger().warning(f"⚠️  Could not process pending fills: {e}")

            # Update metrics to get current position size and price
            self.update_position_metrics()

            # 🔧 FIX: Double-check position with actual exchange balance
            # Prevents partial sells when tracked position is outdated
            try:
                connector = self.connectors[self.config.connector_name]
                trading_pair_parts = self.config.trading_pair.split("-")
                if len(trading_pair_parts) >= 1:
                    base_asset = trading_pair_parts[0]
                    actual_balance = connector.get_available_balance(base_asset)

                    # If actual balance > tracked position, use actual balance
                    if actual_balance > self.position_size_base:
                        self.logger().warning(
                            f"⚠️  Position mismatch detected! "
                            f"Tracked: {self.position_size_base} {base_asset}, "
                            f"Actual: {actual_balance} {base_asset}. "
                            f"Using ACTUAL balance for close order."
                        )
                        self.position_size_base = actual_balance
            except Exception as e:
                self.logger().warning(f"⚠️  Could not verify position with exchange balance: {e}")

            # Also update full metrics to ensure mid_price and current_close_quote are set
            try:
                self.update_metrics()
            except Exception as e:
                self.logger().warning(f"⚠️  Could not update full metrics: {e}")

            # If there's an open position, place a market order to close it
            if self.position_size_base >= self.trading_rules.min_order_size:
                # BUG FIX: Validate trading_pair format before splitting for logging
                trading_pair_parts_close = self.config.trading_pair.split("-")
                base_asset_close = trading_pair_parts_close[0] if len(trading_pair_parts_close) > 0 else "N/A"
                self.logger().info(
                    f"Executor {self.config.id[:8]}... closing position: "
                    f"{self.position_size_base} {base_asset_close} "
                    f"(value: €{self.position_size_quote:.2f})"
                )
                # CRITICAL FIX: For market orders, we need a valid price (even though it's ignored for market orders)
                # Kraken connector validates the price parameter even for market orders
                # Use current_close_quote (best ask for sell orders) if available, otherwise mid_price
                close_price = None

                # Try to get price from updated metrics
                if hasattr(self, 'current_close_quote') and self.current_close_quote and not self.current_close_quote.is_nan():
                    close_price = self.current_close_quote
                elif hasattr(self, 'mid_price') and self.mid_price and not self.mid_price.is_nan():
                    close_price = self.mid_price

                # If price is still invalid, try to get it directly from connector
                # BUG FIX: Check None explicitly before calling is_nan() to avoid AttributeError
                if close_price is None or (hasattr(close_price, 'is_nan') and close_price.is_nan()) or close_price == Decimal("0"):
                    try:
                        from hummingbot.core.data_type.common import PriceType

                        # For sell orders (closing BUY position), use BestAsk
                        close_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.BestAsk)
                        # BUG FIX: Check None before calling is_nan() to avoid AttributeError
                        if close_price is None or (hasattr(close_price, 'is_nan') and close_price.is_nan()) or close_price == Decimal("0"):
                            # Fallback: use mid price
                            close_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
                    except Exception as e:
                        self.logger().warning(f"⚠️  Could not get price for close order: {e}")
                        close_price = Decimal("0")

                # Validate price: must not be None, NaN, zero, or unreasonably small (less than 0.0001)
                # This ensures we don't proceed with invalid placeholder values
                # Threshold of 0.0001 is low enough for very cheap coins but catches invalid placeholders
                # Explicitly check for None first to avoid AttributeError on is_nan() call
                if close_price is not None and not close_price.is_nan() and close_price >= Decimal("0.0001"):
                    self.logger().info(f"💰 Using price €{close_price:.6f} for market close order")
                    self.place_close_order_and_cancel_open_orders(close_type=self.close_type, price=close_price)
                else:
                    # CRITICAL FIX: Since keep_position=False, we MUST close the position even if price retrieval failed
                    # Use last-resort fallback price from grid configuration (midpoint of grid range)
                    # This ensures positions are always liquidated when keep_position=False
                    # Use midpoint of grid range as last-resort fallback for market orders
                    # Market orders will execute at best available price anyway, so this is just for validation
                    try:
                        fallback_price = self._validated_midpoint_price("early_stop close order fallback")
                        self.logger().warning(
                            f"⚠️  Using fallback price from grid config (€{fallback_price:.6f}) for market close order. "
                            f"Price retrieval failed but position must be closed (keep_position=False)."
                        )
                        self.place_close_order_and_cancel_open_orders(close_type=self.close_type, price=fallback_price)
                    except ValueError:
                        # BUG FIX: Validate trading_pair format before splitting for logging
                        trading_pair_parts_err = self.config.trading_pair.split("-")
                        base_asset_err = trading_pair_parts_err[0] if len(trading_pair_parts_err) > 0 else "N/A"
                        self.logger().error(
                            f"❌ CRITICAL: Cannot place close order - invalid fallback price configuration. "
                            f"Position {self.position_size_base} {base_asset_err} "
                            f"may need to be closed manually!"
                        )
            else:
                self.logger().debug(f"Executor {self.config.id[:8]}... no open position to close")

    def update_grid_levels(self):
        self.levels_by_state = {state: [] for state in GridLevelStates}
        for level in self.grid_levels:
            level.update_state()
            self.levels_by_state[level.state].append(level)
        completed = self.levels_by_state[GridLevelStates.COMPLETE]
        # Get completed orders and store them in the filled orders list
        for level in completed:
            if level.active_open_order.order.completely_filled_event.is_set() and level.active_close_order.order.completely_filled_event.is_set():
                open_order = level.active_open_order.order.to_json()
                close_order = level.active_close_order.order.to_json()
                self._filled_orders.append(open_order)
                self._filled_orders.append(close_order)
                self.levels_by_state[GridLevelStates.COMPLETE].remove(level)
                level.reset_level()
                self.levels_by_state[GridLevelStates.NOT_ACTIVE].append(level)

                # STORY A1: Update last_progress_timestamp (completed level = progress)
                self._last_progress_timestamp = self._strategy.current_timestamp

    async def control_shutdown_process(self):
        """
        Control the shutdown process of the executor, handling held positions separately
        """
        self.close_timestamp = self._strategy.current_timestamp
        open_orders_completed = self.open_liquidity_placed == Decimal("0")
        close_orders_completed = self.close_liquidity_placed == Decimal("0")

        if open_orders_completed and close_orders_completed:
            if self.close_type == CloseType.POSITION_HOLD:
                # Move filled orders to held positions instead of regular filled orders
                for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]:
                    if level.active_open_order and level.active_open_order.order:
                        self._held_position_orders.append(level.active_open_order.order.to_json())
                    level.reset_level()
                for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]:
                    if level.active_close_order and level.active_close_order.order:
                        self._held_position_orders.append(level.active_close_order.order.to_json())
                    level.reset_level()
                if len(self._held_position_orders) == 0:
                    self.close_type = CloseType.EARLY_STOP
                    # US-006: Set reason if not already set
                    if self._early_stop_reason is None:
                        self._early_stop_reason = EarlyStopReason.UNKNOWN
                self.levels_by_state = {}
                self.stop()
            else:
                # Regular shutdown process for non-held positions
                order_execution_completed = self.position_size_base == Decimal("0")

                # FIX: If close order is filled but position_size_base has dust
                # (rounding difference between buy amounts and sell executed),
                # treat it as completed.  This prevents the executor from looping
                # forever in SHUTTING_DOWN when the sell fully filled but the
                # remaining base is < min_order_size (e.g. 0.00000004 FET).
                if (not order_execution_completed
                        and self._close_order is not None
                        and self._close_order.order is not None
                        and self._close_order.order.is_filled):
                    min_order_size = getattr(self.trading_rules, 'min_order_size', Decimal("1"))
                    if self.position_size_base < min_order_size:
                        self.logger().info(
                            f"✅ Close order filled with dust remaining "
                            f"({float(self.position_size_base):.10f} < min {float(min_order_size)}) "
                            f"— treating as complete"
                        )
                        order_execution_completed = True

                # FIX: Also check actual exchange balance to detect externally sold positions
                # This prevents infinite retry loops when coins were sold outside the bot
                #
                # CRITICAL FIX (2026-02-23): Skip this check if we have a pending close order!
                # When a LIMIT SELL order is placed, the exchange moves tokens from "available" to "reserved".
                # If we check get_available_balance() while our own close order is pending, we'll see ~0
                # and incorrectly conclude the position was "externally closed".
                # This caused the SWEAT bug where the bot abandoned a position with an unfilled sell order.
                has_pending_close_order = (
                    self._close_order is not None and
                    self._close_order.order is not None and
                    not self._close_order.order.is_done
                )

                if not order_execution_completed and not has_pending_close_order:
                    try:
                        base_asset = self.config.trading_pair.split("-")[0]
                        # Use get_balance() (total) instead of get_available_balance() for more accurate check
                        # This includes both available AND reserved (locked in orders) balance
                        connector = self._strategy.connectors[self.config.connector_name]
                        actual_balance = connector.get_balance(base_asset)
                        min_order_size = self.trading_rules.min_order_size if self.trading_rules else Decimal("0.00001")
                        if actual_balance < min_order_size:
                            self.logger().warning(
                                f"⚠️ Position externally closed: tracked={self.position_size_base} {base_asset}, "
                                f"actual_total={actual_balance} {base_asset} (< min {min_order_size}). "
                                f"Forcing shutdown to prevent infinite retries."
                            )
                            order_execution_completed = True
                            self.close_type = CloseType.FAILED  # Mark as failed since we didn't close it ourselves
                            # FIX: Reset position to zero since coins are confirmed gone on exchange.
                            # Without this, position_pnl_quote is calculated with stale position_size
                            # and possibly zero mid_price, causing catastrophic PnL miscalculation
                            # (e.g., ALGO-USD reported -$68 when actual loss was ~$1).
                            self.position_size_base = Decimal("0")
                            self.position_size_quote = Decimal("0")
                            self.position_pnl_quote = Decimal("0")
                            self.position_fees_quote = Decimal("0")
                    except Exception as e:
                        self.logger().debug(f"Could not verify actual balance: {e}")
                elif has_pending_close_order:
                    self.logger().debug(
                        f"⏳ Skipping external-close check: pending close order {self._close_order.order_id[:8]}... "
                        f"(balance may be reserved)"
                    )

                if order_execution_completed:
                    # Story B1: Log unwind completion if we were in unwind mode
                    if self._unwind_phase in ["GRACEFUL", "AGGRESSIVE"]:
                        self.logger().info(
                            f"✅ UNWIND_DONE reason={self._unwind_close_reason.name if self._unwind_close_reason else 'UNKNOWN'} "
                            f"phase={self._unwind_phase} inv=0 "
                            f"realized_pnl={float(self.realized_pnl_quote):.4f} "
                            f"fees={float(self.realized_fees_quote):.4f}"
                        )
                        self._unwind_phase = "DONE"

                    for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]:
                        if level.active_open_order and level.active_open_order.order:
                            self._filled_orders.append(level.active_open_order.order.to_json())
                        level.reset_level()
                    for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]:
                        if level.active_close_order and level.active_close_order.order:
                            self._filled_orders.append(level.active_close_order.order.to_json())
                        level.reset_level()
                    if self._close_order and self._close_order.order:
                        self._filled_orders.append(self._close_order.order.to_json())
                        self._close_order = None
                    self.update_realized_pnl_metrics()
                    self.levels_by_state = {}
                    self.stop()
                else:
                    await self.control_close_order()
                    self._current_retries += 1
        else:
            self.cancel_open_orders()
        await self._sleep(5.0)

    async def control_close_order(self):
        """
        This method is responsible for controlling the close order. If the close order is filled and the open orders are
        completed, it stops the executor. If the close order is not placed, it places the close order. If the close order
        is not filled, it waits for the close order to be filled and requests the order information to the connector.
        """
        if self._close_order:
            in_flight_order = self.get_in_flight_order(self.config.connector_name,
                                                       self._close_order.order_id) if not self._close_order.order else self._close_order.order
            if in_flight_order:
                self._close_order.order = in_flight_order

                # FIX: Detect PARTIAL close — close order filled but position still remains.
                # Without this, the executor loops forever waiting on an already-filled order
                # while the remaining position is never sold (ALGO-USD -$68 catastrophe).
                if in_flight_order.is_done:
                    self.update_position_metrics()
                    min_order_size = getattr(self.trading_rules, 'min_order_size', Decimal("0"))
                    if self.position_size_base >= min_order_size:
                        self.logger().warning(
                            f"⚠️  Close order filled but position still has "
                            f"{float(self.position_size_base):.6f} {self.config.trading_pair.split('-')[0]} remaining. "
                            f"Archiving partial close and placing new close order."
                        )
                        # Archive the filled close order so its sell data is preserved
                        self._filled_orders.append(in_flight_order.to_json())
                        self._close_order = None
                        # Fall through to place a new close order for the remainder
                    else:
                        return  # Close order filled, dust remaining — will be handled by control_shutdown_process
                else:
                    # Story C1: Throttle this log to max 1 per 60s per executor
                    if HAS_LOG_THROTTLE and should_log(f"close_wait_{self.config.id}", interval_sec=60):
                        self.logger().info("Waiting for close order to be filled")
                    elif not HAS_LOG_THROTTLE:
                        self.logger().debug("Waiting for close order to be filled")  # Downgrade to debug if no throttle
                    return
            else:
                self._failed_orders.append(self._close_order.order_id)
                self._close_order = None
        if not self._close_order and (not self.config.keep_position or (self.close_type is not None and self.close_type != CloseType.POSITION_HOLD)):
            # CRITICAL FIX: Place close order for any close type (STOP_LOSS, TIME_LIMIT, TAKE_PROFIT, etc.)
            # Only skip if keep_position=True AND close_type is None or POSITION_HOLD
            # Ensure we have a valid price for market orders
            # Update metrics first to get current prices
            try:
                self.update_metrics()
            except Exception:
                pass  # Ignore errors, we'll try to get price anyway

            # Get price for close order (use current_close_quote or mid_price)
            close_price = None
            if hasattr(self, 'current_close_quote') and self.current_close_quote and not self.current_close_quote.is_nan():
                close_price = self.current_close_quote
            elif hasattr(self, 'mid_price') and self.mid_price and not self.mid_price.is_nan():
                close_price = self.mid_price
            else:
                # Fallback: get price directly from connector
                try:
                    from hummingbot.core.data_type.common import PriceType
                    close_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.BestAsk)
                    # BUG FIX: Check None before calling is_nan() to avoid AttributeError
                    if close_price is None or (hasattr(close_price, 'is_nan') and close_price.is_nan()) or close_price == Decimal("0"):
                        close_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
                except Exception:
                    close_price = Decimal("NaN")  # Will be handled in place_close_order_and_cancel_open_orders

            minimum_order_size = getattr(self.trading_rules, "min_order_size", Decimal("0"))
            if self.position_size_base < minimum_order_size:
                self.logger().warning(
                    f"⚠️  Position size {self.position_size_base} is below minimum order size "
                    f"({minimum_order_size}) - skipping automatic close."
                )
                return

            # FIX: Also check actual exchange balance to prevent infinite retries
            # when position was sold externally (outside the bot)
            # Use get_balance() (total) instead of get_available_balance() (free only)
            # because available can be 0 when tokens are locked in pending orders,
            # causing a false "sold externally" conclusion that leaves positions unsold.
            try:
                base_asset = self.config.trading_pair.split("-")[0]
                actual_balance = self._strategy.connectors[self.config.connector_name].get_balance(base_asset)
                if actual_balance < minimum_order_size:
                    self.logger().warning(
                        f"⚠️ Actual balance {actual_balance} {base_asset} is below minimum order size "
                        f"({minimum_order_size}) - position was likely sold externally. Skipping close."
                    )
                    return
            except Exception as e:
                self.logger().debug(f"Could not verify actual balance before close: {e}")

            order_amount = await self._determine_close_order_amount(self.position_size_base)
            if order_amount is None:
                # Wait for next loop (or manual action) before attempting again
                return

            # CRITICAL FIX: After 5 failed close attempts, force MARKET order
            # This prevents infinite LIMIT order retries when price moves away or network issues
            if self._balance_mismatch_attempts >= 5:
                self.logger().error(
                    f"❌ FORCE MARKET ORDER: After {self._balance_mismatch_attempts} failed close attempts, "
                    f"switching from LIMIT to MARKET order to guarantee execution. "
                    f"Original close_type: {self.close_type}, forcing to TIME_LIMIT (market)."
                )
                # Force market order by setting TIME_LIMIT close type
                self.close_type = CloseType.HARD_CAP_TIME_LIMIT
                # Reset counter to prevent spam
                self._balance_mismatch_attempts = 0

            self.place_close_order_and_cancel_open_orders(
                close_type=self.close_type,
                price=close_price,
                order_amount=order_amount,
            )

    def adjust_and_place_open_order(self, level: GridLevel):
        """
        This method is responsible for adjusting the open order and placing it.

        :param level: The level to adjust and place the open order.
        :return: None
        """
        order_candidate = self._get_open_order_candidate(level)
        self.adjust_order_candidates(self.config.connector_name, [order_candidate])
        if order_candidate.amount > 0:
            # US-003: Use validated placement to prevent min notional/balance errors
            order_id = self._validated_place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=self.config.triple_barrier_config.open_order_type,
                amount=order_candidate.amount,
                price=order_candidate.price,
                side=order_candidate.order_side,
                position_action=PositionAction.OPEN,
            )
            if order_id:
                level.active_open_order = TrackedOrder(order_id=order_id)
                self.max_open_creation_timestamp = self._strategy.current_timestamp
                self.logger().debug(f"Executor ID: {self.config.id} - Placing open order {order_id}")
            else:
                # US-003: Order failed validation, reset level to allow retry later
                self.logger().debug(f"Executor ID: {self.config.id} - Open order failed validation, will retry")
                level.reset_open_order()

    def adjust_and_place_close_order(self, level: GridLevel):
        order_candidate = self._get_close_order_candidate(level)
        self.adjust_order_candidates(self.config.connector_name, [order_candidate])

        # ==============================================================================
        # BALANCE VALIDATION before placing close order
        # NOTE: Balance sync delay is handled in get_close_orders_to_create() which waits
        # 3 seconds after BUY fill before allowing SELL. If we get here, balance SHOULD
        # be synced. This is a fallback check.
        # ==============================================================================
        if order_candidate.amount > 0:
            try:
                base_asset = self.config.trading_pair.split("-")[0]
                connector = self._strategy.connectors[self.config.connector_name]
                connector_balance = connector.get_available_balance(base_asset)
                internal_inventory = self.position_size_base
                min_order_size = connector.get_order_size_quantum(
                    self.config.trading_pair, order_candidate.amount
                )

                # Case 1: Connector has sufficient balance - proceed normally
                if connector_balance >= order_candidate.amount:
                    pass  # All good, place order

                # Case 2: Balance still not synced after delay - this shouldn't happen often
                # If it does, it means 3 seconds wasn't enough. Log and retry on next cycle.
                elif connector_balance < order_candidate.amount and internal_inventory >= order_candidate.amount:
                    self._balance_mismatch_attempts += 1
                    if self._balance_mismatch_attempts <= 3:
                        # First few attempts: wait for sync (will retry on next control_task cycle)
                        self.logger().warning(
                            f"⏳ Executor {self.config.id[:8]}... Balance still syncing after delay "
                            f"(attempt {self._balance_mismatch_attempts}/3): "
                            f"connector={connector_balance}, internal={internal_inventory} {base_asset}. "
                            f"Waiting for next cycle..."
                        )
                        return  # Don't place order yet, retry on next cycle
                    else:
                        # After 3 retries: try placing order anyway, exchange will verify
                        self.logger().warning(
                            f"⚠️ Executor {self.config.id[:8]}... Balance sync timeout after {self._balance_mismatch_attempts} attempts. "
                            f"Attempting order anyway (exchange will verify)."
                        )

                # Case 3: Neither connector nor internal shows sufficient balance
                elif connector_balance < min_order_size and internal_inventory < min_order_size:
                    self.logger().error(
                        f"❌ Executor {self.config.id[:8]}... No balance available: "
                        f"connector={connector_balance}, internal={internal_inventory} {base_asset}. "
                        f"Position was likely sold externally. Terminating."
                    )
                    level.reset_close_order()
                    self.close_type = CloseType.FAILED
                    self._status = RunnableStatus.TERMINATED
                    self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                    return

                # Case 4: Connector has partial balance - use what's available
                elif connector_balance >= min_order_size:
                    self._balance_mismatch_attempts += 1
                    if self._balance_mismatch_attempts >= self._max_balance_mismatch_attempts:
                        self.logger().error(
                            f"❌ SPAM PREVENTION: Executor {self.config.id[:8]}... stopped after "
                            f"{self._balance_mismatch_attempts} failed attempts. TERMINATING."
                        )
                        level.reset_close_order()
                        self.close_type = CloseType.FAILED
                        self._status = RunnableStatus.TERMINATED
                        self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                        return

                    self.logger().warning(
                        f"⚠️ Executor {self.config.id[:8]}... Using partial balance: "
                        f"requested {order_candidate.amount}, available {connector_balance} {base_asset}"
                    )
                    order_candidate.amount = connector_balance

            except Exception as e:
                self.logger().warning(
                    f"⚠️ Could not verify balance before placing close order: {e}. "
                    f"Proceeding with order placement..."
                )

            # US-003: Use validated placement to prevent min notional/balance errors
            order_id = self._validated_place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=self.config.triple_barrier_config.take_profit_order_type,
                amount=order_candidate.amount,
                price=order_candidate.price,
                side=order_candidate.order_side,
                position_action=PositionAction.CLOSE,
            )
            if order_id:
                level.active_close_order = TrackedOrder(order_id=order_id)
                self._close_order_local_ts[order_id] = self._strategy.current_timestamp
                self.logger().debug(f"Executor ID: {self.config.id} - Placing close order {order_id}")

                # Reset insufficient funds counter on successful order placement
                if self._insufficient_funds_retries > 0:
                    self.logger().debug(
                        f"✅ Close order placed successfully, resetting insufficient funds counter "
                        f"(was: {self._insufficient_funds_retries})"
                    )
                    self._insufficient_funds_retries = 0

                # CRITICAL FIX: Also reset balance mismatch counter on success
                if self._balance_mismatch_attempts > 0:
                    self.logger().debug(
                        f"✅ Close order placed successfully, resetting balance mismatch counter "
                        f"(was: {self._balance_mismatch_attempts})"
                    )
                    self._balance_mismatch_attempts = 0

    def _get_fee_rates(self) -> tuple:
        """Return (maker_fee_decimal, taker_fee_decimal) from the connector's fee schema.

        Values are Decimals in 0-1 range (e.g. Decimal('0.0016') for 0.16 %).
        Falls back to conservative defaults if the connector is unavailable.
        """
        try:
            connector = self.connectors[self.config.connector_name]
            schema = connector.trade_fee_schema()
            return (schema.maker_percent_fee_decimal, schema.taker_percent_fee_decimal)
        except Exception:
            # Conservative fallback — Kraken worst-case taker tier
            return (Decimal("0.0025"), Decimal("0.004"))

    def _estimate_close_fee_pct(self, is_shutdown: bool = False) -> Decimal:
        """Estimate round-trip fee percentage for a close.

        - *Normal limit close*: buy was taker-or-maker (use taker to be safe),
          sell is a resting limit order → maker.
        - *Shutdown / forced close*: sell is aggressive → taker.

        A small slippage buffer is added for market orders.
        """
        _maker_fee, taker_fee = self._get_fee_rates()
        # Buy-side: conservatively assume taker (we don't know at this point)
        buy_side = taker_fee
        if is_shutdown:
            sell_side = taker_fee
            slippage = Decimal("0.0005")  # 0.05 % slippage buffer for market sell
        else:
            sell_side = _maker_fee  # resting LIMIT sell
            slippage = Decimal("0")
        return buy_side + sell_side + slippage

    def get_take_profit_price(self, level: GridLevel):
        return level.price * (1 + level.take_profit) if self.config.side == TradeType.BUY else level.price * (1 - level.take_profit)

    def _get_open_order_candidate(self, level: GridLevel):
        if ((level.side == TradeType.BUY and level.price >= self.current_open_quote) or
                (level.side == TradeType.SELL and level.price <= self.current_open_quote)):
            entry_price = self.current_open_quote * (1 - self.config.safe_extra_spread) if level.side == TradeType.BUY else self.current_open_quote * (1 + self.config.safe_extra_spread)
        else:
            entry_price = level.price

        # GUARDRAIL B: Never place entry orders with negative edge
        # Entry must have minimum spread buffer from mid price
        mid_price = self.mid_price
        min_edge_pct = Decimal("0.0008")  # 0.08% minimum edge (covers fees + slippage)

        if level.side == TradeType.BUY:
            max_buy_price = mid_price * (Decimal("1") - min_edge_pct)
            if entry_price > max_buy_price:
                self.logger().debug(
                    f"GUARDRAIL: Adjusting buy price from €{entry_price:.6f} to €{max_buy_price:.6f} "
                    f"(mid €{mid_price:.6f} - {min_edge_pct * 100:.2f}%)"
                )
                entry_price = max_buy_price
        else:  # SELL
            min_sell_price = mid_price * (Decimal("1") + min_edge_pct)
            if entry_price < min_sell_price:
                self.logger().debug(
                    f"GUARDRAIL: Adjusting sell price from €{entry_price:.6f} to €{min_sell_price:.6f} "
                    f"(mid €{mid_price:.6f} + {min_edge_pct * 100:.2f}%)"
                )
                entry_price = min_sell_price

        if self.is_perpetual:
            return PerpetualOrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=self.config.triple_barrier_config.open_order_type.is_limit_type(),
                order_type=self.config.triple_barrier_config.open_order_type,
                order_side=self.config.side,
                amount=level.amount_quote / self.mid_price,
                price=entry_price,
                leverage=Decimal(self.config.leverage)
            )
        return OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=self.config.triple_barrier_config.open_order_type.is_limit_type(),
            order_type=self.config.triple_barrier_config.open_order_type,
            order_side=self.config.side,
            amount=level.amount_quote / self.mid_price,
            price=entry_price
        )

    def _get_close_order_candidate(self, level: GridLevel):
        take_profit_price = self.get_take_profit_price(level)
        if ((level.side == TradeType.BUY and take_profit_price <= self.current_close_quote) or
                (level.side == TradeType.SELL and take_profit_price >= self.current_close_quote)):
            take_profit_price = self.current_close_quote * (
                1 + self.config.safe_extra_spread) if level.side == TradeType.BUY else self.current_close_quote * (
                1 - self.config.safe_extra_spread)

        # GUARDRAIL A: Never sell below breakeven (entry + fees + min profit buffer)
        # Prevents "buy high / sell low" grid placement errors
        if level.side == TradeType.BUY:  # We're selling after a buy
            # Fee buffer pulled from the connector's fee schema.
            # Per-level close is a resting LIMIT order (is_shutdown=False) → maker sell fee.
            entry_price = level.price
            fee_buffer_pct = self._estimate_close_fee_pct(is_shutdown=False)
            min_profit_pct = Decimal("0.0015")  # 0.15% minimum profit
            min_acceptable_price = entry_price * (Decimal("1") + fee_buffer_pct + min_profit_pct)

            if take_profit_price < min_acceptable_price:
                self.logger().warning(
                    f"⚠️ GUARDRAIL: Blocking sell order below breakeven! "
                    f"Take profit €{take_profit_price:.6f} < minimum €{min_acceptable_price:.6f} "
                    f"(entry €{entry_price:.6f} + fees + buffer). "
                    f"Using minimum price instead."
                )
                take_profit_price = min_acceptable_price
        # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
        trading_pair_parts_fee = self.config.trading_pair.split("-")
        base_asset_fee = trading_pair_parts_fee[0] if len(trading_pair_parts_fee) > 0 else None
        if base_asset_fee and level.active_open_order.fee_asset == base_asset_fee and self.config.deduct_base_fees:
            amount = level.active_open_order.executed_amount_base - level.active_open_order.cum_fees_base
            self._open_fee_in_base = True
        else:
            amount = level.active_open_order.executed_amount_base
        if self.is_perpetual:
            return PerpetualOrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=self.config.triple_barrier_config.take_profit_order_type.is_limit_type(),
                order_type=self.config.triple_barrier_config.take_profit_order_type,
                order_side=self.close_order_side,
                amount=amount,
                price=take_profit_price,
                leverage=Decimal(self.config.leverage)
            )
        return OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=self.config.triple_barrier_config.take_profit_order_type.is_limit_type(),
            order_type=self.config.triple_barrier_config.take_profit_order_type,
            order_side=self.close_order_side,
            amount=amount,
            price=take_profit_price
        )

    def _get_price_with_fallback(self, price_type: PriceType, context: str) -> Decimal:
        try:
            return self.get_price(self.config.connector_name, self.config.trading_pair, price_type)
        except (ValueError, KeyError) as e:
            error_msg = str(e)
            if "No order book exists" in error_msg or "order book" in error_msg.lower():
                connector = self.connectors.get(self.config.connector_name) if hasattr(self, "connectors") else None
                if connector and hasattr(connector, "_target_market") and connector._target_market is not None:
                    try:
                        base_connector = connector._target_market()
                        if base_connector:
                            price = base_connector.get_price_by_type(self.config.trading_pair, price_type)
                            self.logger().info(
                                f"Using base connector price for {self.config.trading_pair} during {context}: {price}"
                            )
                            return price
                    except Exception as base_error:
                        self.logger().warning(
                            f"Could not get price from base connector for {self.config.trading_pair} during {context}: "
                            f"{base_error}"
                        )

                fallback_price = self._validated_midpoint_price(f"{context} (price fallback)")
                self.logger().warning(
                    f"⚠️  No order book exists for {self.config.trading_pair} during {context}. "
                    f"Using fallback price: {fallback_price:.6f}"
                )
                return fallback_price
            raise

    async def _refresh_connector_balances(self):
        connector = self.connectors.get(self.config.connector_name)
        if connector is None:
            return

        refresh_fn = getattr(connector, "_update_balances", None)
        if refresh_fn is not None:
            try:
                await refresh_fn()
                return
            except TypeError:
                # Some connectors allow forcing a throttled update
                await refresh_fn(True)
                return
            except Exception as e:
                self.logger().debug(f"Unable to refresh balances via connector: {e}")

        strategy_refresh = getattr(self._strategy, "update_balances", None)
        if strategy_refresh is not None:
            try:
                if asyncio.iscoroutinefunction(strategy_refresh):
                    await strategy_refresh(connector_name=self.config.connector_name)
                else:
                    strategy_refresh(connector_name=self.config.connector_name)
            except Exception as e:
                self.logger().debug(f"Unable to refresh balances via strategy: {e}")

    def _safe_get_total_balance(self, connector: ConnectorBase, asset: str) -> Optional[Decimal]:
        if connector is None:
            return None
        get_balance = getattr(connector, "get_balance", None)
        if get_balance is None:
            return None
        try:
            balance = get_balance(asset)
            return Decimal(str(balance))
        except Exception as e:
            self.logger().debug(f"Unable to read total balance for {asset}: {e}")
            return None

    @staticmethod
    def _coerce_to_decimal(value) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _cap_sell_to_available(self, inventory: Decimal) -> Decimal:
        """Cap sell quantity to actual available balance (prevents Bitget 43012)."""
        try:
            base_asset = self.config.trading_pair.split("-")[0]
            connector = self.connectors.get(self.config.connector_name)
            if connector is None:
                return inventory
            available = self._coerce_to_decimal(connector.get_available_balance(base_asset))
            if Decimal("0") < available < inventory:
                self.logger().warning(
                    f"⚠️ Fee-adjusted unwind: capping sell from {inventory:.6f} to "
                    f"{available:.6f} {base_asset} (fees reduced actual balance)"
                )
                return available
        except Exception as e:
            self.logger().warning(f"⚠️ Could not check available balance: {e}")
        return inventory

    def _validated_midpoint_price(self, context: str) -> Decimal:
        midpoint = (self.config.start_price + self.config.end_price) / Decimal("2")
        if midpoint <= Decimal("0"):
            message = (
                f"Invalid fallback price ({midpoint}) for {self.config.trading_pair} during {context}. "
                f"Check start_price ({self.config.start_price}) and end_price ({self.config.end_price})."
            )
            self.logger().error(message)
            raise ValueError(message)
        return midpoint

    async def _determine_close_order_amount(self, required_amount: Decimal) -> Optional[Decimal]:
        """
        Ensure we have enough available base asset to place the market close order. This method attempts to refresh
        balances when Kraken still reports funds as locked right after canceling open orders.
        """
        # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
        trading_pair_parts = self.config.trading_pair.split("-")
        if len(trading_pair_parts) < 2:
            self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
            return None
        base_asset = trading_pair_parts[0]
        connector = self.connectors.get(self.config.connector_name)
        if connector is None:
            self.logger().error("Connector not available when attempting to close position.")
            return None

        await self._refresh_connector_balances()

        min_order_size = getattr(self.trading_rules, "min_order_size", Decimal("0"))
        available = self._coerce_to_decimal(connector.get_available_balance(base_asset))
        total_balance = self._safe_get_total_balance(connector, base_asset)
        target_amount = min(required_amount, available)

        if available >= target_amount and target_amount >= min_order_size:
            return target_amount

        for attempt in range(1, self._close_balance_max_retries + 1):
            if total_balance is not None and total_balance < min_order_size:
                break

            self.logger().info(
                f"⏳ Waiting for {base_asset} balance to unlock before closing position "
                f"(available {available:.8f}, required {target_amount:.8f}) "
                f"[attempt {attempt}/{self._close_balance_max_retries}]"
            )
            await self._refresh_connector_balances()
            await self._sleep(self._close_balance_retry_interval)

            available = self._coerce_to_decimal(connector.get_available_balance(base_asset))
            total_balance = self._safe_get_total_balance(connector, base_asset)
            target_amount = min(required_amount, available)

            if available >= target_amount and target_amount >= min_order_size:
                return target_amount

        if available >= min_order_size:
            self.logger().warning(
                f"⚠️  Proceeding with partial close of {available:.8f} {base_asset} "
                f"(requested {required_amount:.8f}) due to locked balances."
            )
            return available

        self.logger().error(
            f"❌ Unable to close position automatically: available {base_asset} balance "
            f"({available:.8f}) remains below minimum order size ({min_order_size}). "
            f"Manual intervention may be required."
        )
        self._notify_manual_close_required(base_asset, available, min_order_size)
        return None

    def _notify_manual_close_required(self, base_asset: str, available: Decimal, min_order_size: Decimal):
        message = (
            f"⚠️ GridExecutor could not auto-close {self.config.trading_pair}: "
            f"{available:.6f} {base_asset} available, minimum order size {min_order_size}. "
            f"Please close the remaining position manually."
        )
        self.logger().error(message)
        notify = getattr(self._strategy, "notify_hb_app_with_timestamp", None)
        if callable(notify):
            notify(message)

    def update_metrics(self):
        self.mid_price = self._get_price_with_fallback(PriceType.MidPrice, "update_metrics (mid_price)")
        self.current_open_quote = self._get_price_with_fallback(
            self.open_order_price_type, "update_metrics (open_quote)"
        )
        self.current_close_quote = self._get_price_with_fallback(
            self.close_order_price_type, "update_metrics (close_quote)"
        )
        self.update_position_metrics()
        self.update_realized_pnl_metrics()

    def get_open_orders_to_create(self):
        """
        This method is responsible for controlling the open orders. Will check for each grid level if the order if there
        is an open order. If not, it will place a new orders from the proposed grid levels based on the current price,
        max open orders, max orders per batch, activation bounds and order frequency.
        """
        n_open_orders = len(
            [level.active_open_order for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]])
        if (self.max_open_creation_timestamp > self._strategy.current_timestamp - self.config.order_frequency or
                n_open_orders >= self.config.max_open_orders):
            return []
        levels_allowed = self._filter_levels_by_activation_bounds()
        sorted_levels_by_proximity = self._sort_levels_by_proximity(levels_allowed)
        return sorted_levels_by_proximity[:self.config.max_orders_per_batch]

    def get_close_orders_to_create(self):
        """
        This method is responsible for controlling the take profit. It will check if the net pnl percentage is greater
        than the take profit percentage and place the close order.

        CRITICAL FIX: Limits close orders to 1 per batch to prevent "Insufficient funds" race conditions
        when multiple levels try to sell the same inventory simultaneously.

        EXCHANGE BALANCE SYNC FIX: Waits for balance_sync_delay (3s) after BUY fill before placing SELL.
        This prevents "Insufficient funds" errors on Kraken, Bitget, and other exchanges where the
        balance API doesn't update instantly after a fill.

        :return: List of levels that need close orders
        """
        close_orders_proposal = []
        open_orders_filled = self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]

        # Count existing close orders being processed
        n_close_orders_pending = len(
            [level.active_close_order for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        )

        # CRITICAL: Only allow 1 close order at a time to prevent balance race conditions
        # If we already have a close order pending, don't create more
        if n_close_orders_pending >= 1:
            return []

        current_time = self._strategy.current_timestamp

        # FIX: ALWAYS place close (SELL) orders immediately after BUY is filled
        # The activation_bounds check was causing SELL orders to be delayed/skipped
        # when price was > activation_bounds away from TP price, leaving inventory unsold
        # activation_bounds should only apply to OPEN (BUY) orders, not CLOSE (SELL) orders
        for level in open_orders_filled:
            # ==============================================================================
            # EXCHANGE BALANCE SYNC FIX: Check if enough time has passed since BUY fill
            # Kraken/Bitget/other exchanges take 2-5 seconds to update balance after fill.
            # If we try to SELL too soon, the connector reports 0 balance and order fails.
            # ==============================================================================
            if level.active_open_order and level.active_open_order.last_update_timestamp:
                fill_time = level.active_open_order.last_update_timestamp
                time_since_fill = current_time - fill_time

                # Only apply delay if time_since_fill is non-negative and within delay window
                # Negative time_since_fill can happen in tests or if timestamps are misaligned
                if 0 <= time_since_fill < self._balance_sync_delay:
                    # Not enough time has passed - wait for balance to sync
                    remaining = self._balance_sync_delay - time_since_fill
                    self.logger().debug(
                        f"⏳ Executor {self.config.id[:8]}... Balance sync delay: "
                        f"waiting {remaining:.1f}s more before placing SELL "
                        f"(fill was {time_since_fill:.1f}s ago, need {self._balance_sync_delay}s)"
                    )
                    continue  # Skip this level for now, will be picked up on next control_task cycle

            close_orders_proposal.append(level)

        # CRITICAL: Return max 1 close order at a time (serialize close orders)
        # This prevents race conditions where multiple levels try to sell same inventory
        return close_orders_proposal[:1] if close_orders_proposal else []

    def get_open_order_ids_to_cancel(self):
        if self.config.activation_bounds:
            open_orders_to_cancel = []
            open_orders_placed = [level.active_open_order for level in
                                  self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
            for order in open_orders_placed:
                price = order.price
                if price:
                    distance_pct = abs(price - self.mid_price) / self.mid_price
                    if distance_pct > self.config.activation_bounds:
                        open_orders_to_cancel.append(order.order_id)
                        self.logger().debug(f"Executor ID: {self.config.id} - Canceling open order {order.order_id}")
            return open_orders_to_cancel
        return []

    def get_close_order_ids_to_cancel(self):
        """
        This method is responsible for controlling the close orders.

        FIX: activation_bounds should NOT be used to cancel close orders!
        Close orders (SELL) are placed at a target price (e.g., +5% TP).
        Cancelling them because they're "too far" from mid_price defeats the purpose.
        activation_bounds is meant for OPEN orders only - to avoid buying when price moves away.

        :return: Empty list - close orders should not be cancelled by activation_bounds
        """
        # FIX: Return empty list - don't cancel close orders based on activation_bounds
        # The old logic was cancelling SELL orders when price > activation_bounds from mid,
        # which prevented sells from ever executing (constant cancel/replace loop).
        return []

    def _filter_levels_by_activation_bounds(self):
        not_active_levels = self.levels_by_state[GridLevelStates.NOT_ACTIVE]
        if self.config.activation_bounds:
            if self.config.side == TradeType.BUY:
                activation_bounds_price = self.mid_price * (1 - self.config.activation_bounds)
                return [level for level in not_active_levels if level.price >= activation_bounds_price]
            else:
                activation_bounds_price = self.mid_price * (1 + self.config.activation_bounds)
                return [level for level in not_active_levels if level.price <= activation_bounds_price]
        return not_active_levels

    def _sort_levels_by_proximity(self, levels: List[GridLevel]):
        return sorted(levels, key=lambda level: abs(level.price - self.mid_price))

    def control_triple_barrier(self):
        """
        This method is responsible for controlling the barriers. It controls the stop loss, take profit, time limit and
        trailing stop.

        :return: None
        """
        if self.stop_loss_condition():
            self.close_type = CloseType.STOP_LOSS
            return True
        elif self.limit_price_condition():
            self.close_type = CloseType.POSITION_HOLD if self.config.keep_position else CloseType.STOP_LOSS
            return True
        elif self.is_expired:
            self.close_type = CloseType.TIME_LIMIT
            return True
        elif self.trailing_stop_condition():
            self.close_type = CloseType.TRAILING_STOP
            return True
        elif self.take_profit_condition():
            self.close_type = CloseType.TAKE_PROFIT
            return True
        return False

    def take_profit_condition(self):
        """
        Take profit condition — FEE-AWARE version.

        Only triggers when the ENTIRE position's unrealized PnL (after buy fees
        already paid AND estimated sell fees) exceeds the per-level take-profit
        threshold.  This prevents the old bug where the executor would dump
        everything as soon as mid_price crossed end_price (~1 % grid width),
        which was far below the fee-adjusted break-even on Kraken (0.48 % RT).

        Fall-through: the per-level close-order path still places individual
        LIMIT sells at each level's TP price, so normal grid operation is
        unaffected.  This global condition is the "all-at-once" exit that
        must only fire when it is genuinely profitable.
        """
        # --- price must at least be above end_price (original gate) ---
        if self.config.side == TradeType.BUY:
            if self.mid_price <= self.config.end_price:
                return False
        else:
            is_short_mode = (
                self.config.custom_info and
                self.config.custom_info.get('trade_direction', '').lower() == 'short'
            )
            if is_short_mode:
                if self.mid_price >= self.config.end_price:
                    return False
            else:
                if self.mid_price >= self.config.start_price:
                    return False

        # --- fee-aware profitability check ---
        # position_pnl_quote already includes buy-side fees paid.
        # We still need to subtract *estimated* sell-side fees.
        # Shutdown path uses aggressive/market orders → taker fee + slippage.
        self.update_position_metrics()
        if self.position_size_quote <= Decimal("0"):
            return True  # nothing to sell, let the executor clean up

        _maker_fee, taker_fee = self._get_fee_rates()
        estimated_sell_fee_pct = taker_fee + Decimal("0.0005")  # taker + slippage
        estimated_sell_fees = self.position_size_base * self.mid_price * estimated_sell_fee_pct
        net_pnl_after_fees = self.position_pnl_quote - estimated_sell_fees

        if net_pnl_after_fees <= Decimal("0"):
            return False  # not profitable after fees — let per-level TP handle it

        return True

    def stop_loss_condition(self):
        """
        This method is responsible for controlling the stop loss. If the net pnl percentage is less than the stop loss
        percentage, it places the close order and cancels the open orders.

        :return: None
        """
        if self.config.triple_barrier_config.stop_loss:
            return self.position_pnl_pct <= -self.config.triple_barrier_config.stop_loss
        return False

    def limit_price_condition(self):
        """
        This method is responsible for controlling the limit price. If the current price is greater than the limit price,
        it places the close order and cancels the open orders.

        :return: None
        """
        if self.config.limit_price:
            if self.config.side == TradeType.BUY:
                return self.mid_price <= self.config.limit_price
            else:
                return self.mid_price >= self.config.limit_price
        return False

    def trailing_stop_condition(self):
        if self.config.triple_barrier_config.trailing_stop:
            net_pnl_pct = self.position_pnl_pct
            if not self._trailing_stop_trigger_pct:
                if net_pnl_pct > self.config.triple_barrier_config.trailing_stop.activation_price:
                    self._trailing_stop_trigger_pct = net_pnl_pct - self.config.triple_barrier_config.trailing_stop.trailing_delta
            else:
                if net_pnl_pct < self._trailing_stop_trigger_pct:
                    return True
                if net_pnl_pct - self.config.triple_barrier_config.trailing_stop.trailing_delta > self._trailing_stop_trigger_pct:
                    self._trailing_stop_trigger_pct = net_pnl_pct - self.config.triple_barrier_config.trailing_stop.trailing_delta
        return False

    def place_close_order_and_cancel_open_orders(
        self,
        close_type: CloseType,
        price: Decimal = Decimal("NaN"),
        order_amount: Optional[Decimal] = None,
    ):
        """
        This method is responsible for placing the close order and canceling the open orders. If the difference between
        the open filled amount and the close filled amount is greater than the minimum order size, it places the close
        order. It also cancels the open orders.

        :param close_type: The type of the close order.
        :param price: The price to be used in the close order.
        :return: None
        """
        # Story A1: Bounded close - force market order if escalation triggered
        if self._force_aggressive_close:
            self.logger().warning(
                "⚠️  Story A1 Bounded Close: Forcing MARKET order for aggressive close "
                "(graceful LIMIT order failed after grace period)"
            )
            # Force market order by setting appropriate close_type
            # PANIC EXITS (stop_loss, time_limit, early_stop) already use MARKET orders
            # We use TIME_LIMIT as it triggers market order path
            close_type = CloseType.HARD_CAP_TIME_LIMIT  # Forces market order
            self._force_aggressive_close = False  # Reset flag

        # PHASE 1+3: DOUBLE SELL GUARD - Prevent duplicate close orders
        if self._closing_in_progress:
            self.logger().warning(
                f"⚠️  Close already in progress (order_id: {self._close_order_id}) - "
                f"skipping duplicate close request"
            )
            return

        # Phase 3: Set CLOSING state before any operations
        self._closing_in_progress = True
        self._status = RunnableStatus.CLOSING
        self.logger().info(f"🔒 Executor state: CLOSING (close_type: {close_type})")

        # CRITICAL FIX for Kraken/Bitget "Insufficient funds" bug:
        # Cancel open orders first, then wait for exchange to process cancellations
        # Without this delay, balance remains locked and close order fails
        import time

        # Count orders to cancel
        open_order_count = len([
            level for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]
            if level.active_open_order
        ])
        close_order_count = len([
            level for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]
            if level.active_close_order
        ])
        total_cancels = open_order_count + close_order_count

        # Cancel orders
        self.cancel_open_orders()

        # Wait for cancellations to be processed by exchange
        # On retry after "Insufficient balance", wait longer — the previous cancel
        # may not have been fully processed by the exchange (Bitget locks balance
        # until cancel confirmations arrive).
        is_retry = self._insufficient_funds_retries > 0
        if total_cancels > 0 or is_retry:
            if is_retry:
                # Retry: wait extra to ensure ALL pending orders are fully cancelled
                wait_time = min(5.0 + (total_cancels * 0.5), 10.0)
            else:
                wait_time = min(3.0 + (total_cancels * 0.3), 6.0)
            self.logger().info(
                f"⏳ Waiting {wait_time:.1f}s for {total_cancels} order cancellations to unlock balance"
                f"{' (retry after Insufficient balance)' if is_retry else ''}..."
            )
            time.sleep(wait_time)
        min_order_size = getattr(self.trading_rules, "min_order_size", Decimal("0"))

        # PHASE 1 FIX: Get FRESH balance from exchange (not cached position_size)
        # This prevents "Insufficient funds" from trying to sell already-sold inventory
        trading_pair_parts = self.config.trading_pair.split("-")
        if len(trading_pair_parts) < 2:
            self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
            self._closing_in_progress = False  # Reset guard
            return
        base_asset = trading_pair_parts[0]

        # FIX: Use position_size_base directly — it tracks actual fills accurately.
        # DO NOT use min(position_size_base, get_available_balance()) because:
        # 1. available_balance can be STALE (exchange hasn't synced after fills)
        #    → QNT bug: 0.528 QNT bought, balance still shows old 0.240
        # 2. available_balance can be REDUCED by pending-cancel close orders
        #    → RIVER bug: 0.656 locked in cancel-pending sell, new sell undersized
        # Both cause the close order to be undersized, leaving coins unsold.
        target_amount = order_amount if order_amount is not None else self.position_size_base

        # SAFETY NET: If previous close attempts failed with "Insufficient balance",
        # the position_size_base may not account for base-asset fees (e.g. Bitget).
        # Fall back to actual available balance to prevent orphaned positions.
        if self._insufficient_funds_retries > 0 and order_amount is None:
            try:
                available = self._coerce_to_decimal(
                    self.connectors[self.config.connector_name].get_available_balance(base_asset)
                )
                if Decimal("0") < available < target_amount:
                    self.logger().warning(
                        f"⚠️ Fee-adjusted close: reducing sell from {target_amount:.6f} to "
                        f"{available:.6f} {base_asset} (base-asset fees reduced actual balance)"
                    )
                    target_amount = available
            except Exception as e:
                self.logger().warning(f"⚠️ Could not check available balance for fee adjustment: {e}")

        # Monitor wallet balance for visibility (warning only, not blocking)
        try:
            wallet_balance = self._coerce_to_decimal(
                self.connectors[self.config.connector_name].get_balance(base_asset)
            )
            self.logger().info(
                f"📊 Close amount: target={target_amount:.6f} {base_asset}, "
                f"wallet_total={wallet_balance:.6f}, "
                f"executor_position={self.position_size_base:.6f}"
            )
            if wallet_balance < target_amount:
                self.logger().warning(
                    f"⚠️  Wallet balance ({wallet_balance:.6f}) < target ({target_amount:.6f}) — "
                    f"exchange may reject if balance doesn't settle in time"
                )
        except Exception as e:
            self.logger().warning(f"⚠️  Could not read wallet balance for monitoring: {e}")

        if target_amount >= min_order_size:
            # CRITICAL FIX: Ensure we have a valid price for market orders
            # Kraken connector validates price parameter even for market orders
            # Check if price is None before calling is_nan() to avoid AttributeError
            if price is None or price.is_nan() or price == Decimal("0"):
                # Try to get price from metrics
                if hasattr(self, 'current_close_quote') and self.current_close_quote and not self.current_close_quote.is_nan():
                    price = self.current_close_quote
                elif hasattr(self, 'mid_price') and self.mid_price and not self.mid_price.is_nan():
                    price = self.mid_price
                else:
                    # Last resort: get price directly from connector
                    try:
                        # Update metrics first
                        try:
                            self.update_metrics()
                        except Exception:
                            pass
                        # Get best ask for sell orders (PriceType is already imported at top of file)
                        price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.BestAsk)
                        # BUG FIX: Check if price is None before calling is_nan() to avoid AttributeError
                        if price is None or price.is_nan() or price == Decimal("0"):
                            price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
                    except Exception as e:
                        self.logger().error(f"❌ CRITICAL: Cannot get price for close order: {e}")
                        # Set price to 0 to trigger validation error - don't use placeholder value
                        price = Decimal("0")

            # Validate price: must not be None, NaN, zero, or unreasonably small (less than 0.0001)
            # This catches both Decimal("0") and Decimal("0.000001") placeholder values
            # Threshold of 0.0001 is low enough for very cheap coins but catches invalid placeholders
            if price is None or price.is_nan() or price == Decimal("0") or price < Decimal("0.0001"):
                # CRITICAL FIX: Use last-resort fallback price from grid configuration
                # Market orders will execute at best available price anyway, so this is just for validation
                try:
                    fallback_price = self._validated_midpoint_price("close order placement fallback")
                    self.logger().warning(
                        f"⚠️  Using fallback price from grid config (€{fallback_price:.6f}) for market close order. "
                        f"Price retrieval failed but position must be closed."
                    )
                    price = fallback_price
                except ValueError:
                    # BUG FIX: Validate trading_pair format before splitting for logging
                    trading_pair_parts_crit = self.config.trading_pair.split("-")
                    base_asset_crit = trading_pair_parts_crit[0] if len(trading_pair_parts_crit) > 0 else "N/A"
                    self.logger().error(
                        f"❌ CRITICAL: Cannot place close order - invalid price ({price}) and fallback configuration. "
                        f"Position {self.position_size_base} {base_asset_crit} "
                        f"may need to be closed manually!"
                    )
                    return

            # Phase 1+3: Check if remaining amount is worth closing (dust handling)
            if target_amount < min_order_size:
                self.logger().warning(
                    f"⚠️  Remaining amount {target_amount} {base_asset} below min order size "
                    f"({min_order_size}) - marking as CLOSED_WITH_DUST"
                )
                self._status = RunnableStatus.TERMINATED
                self._closing_in_progress = False
                self.close_type = close_type
                self.logger().info(f"✅ Executor closed with dust (<{min_order_size} {base_asset})")
                return

            order_amount_to_use = target_amount

            # Determine order type based on close_type and configured order types
            # Default behavior: PANIC exits (stop_loss, early_stop, time_limit) use configured order type
            # This allows users to choose LIMIT for lower fees or MARKET for guaranteed execution
            if self._insufficient_funds_retries > 0:
                # CRITICAL: On retry after "Insufficient balance", force MARKET order.
                # The previous LIMIT order may have failed to fill in a falling market
                # (e.g. stop-loss triggered, LIMIT sell sits above market price).
                # Using MARKET guarantees execution and prevents ORPHAN_RISK.
                use_limit_order = False
                self.logger().warning(
                    f"⚠️ Retry {self._insufficient_funds_retries}: forcing MARKET order "
                    f"to prevent orphan (previous close failed with Insufficient balance)"
                )
            elif close_type == CloseType.STOP_LOSS:
                use_limit_order = self._stop_loss_order_type == OrderType.LIMIT
            elif close_type == CloseType.TIME_LIMIT:
                use_limit_order = self._time_limit_order_type == OrderType.LIMIT
            elif close_type == CloseType.EARLY_STOP:
                # Early stop uses same logic as stop_loss
                use_limit_order = self._stop_loss_order_type == OrderType.LIMIT
            else:
                # Regular exits (take_profit, etc.) use LIMIT by default
                use_limit_order = True

            # PHASE 3.5: Log invariants (production monitoring)
            order_type_chosen = "LIMIT" if use_limit_order else "MARKET"
            self.logger().info(
                f"📋 CLOSE DECISION: "
                f"close_type={close_type}, "
                f"use_limit_order={use_limit_order}, "
                f"order_type={order_type_chosen}, "
                f"amount={order_amount_to_use} {base_asset}"
            )

            if use_limit_order:
                # Use LIMIT order with current market price (will execute at limit or better)
                # This avoids slippage and uses maker fees (8x cheaper than taker fees)
                # order_type = OrderType.LIMIT (verwijderd, niet gebruikt)

                # CRITICAL FIX: Use current market price with small buffer for better execution
                # Don't use BestAsk/BestBid as they can be worse than market price
                # BUG FIX: Add error handling for get_price() call to prevent crashes
                try:
                    current_market_price = self.get_price(self.config.connector_name, self.config.trading_pair, PriceType.MidPrice)
                    # BUG FIX: Validate price is not None, NaN, or zero before using it
                    if current_market_price is None or current_market_price.is_nan() or current_market_price == Decimal("0"):
                        # Fallback to provided price or use fallback mechanism
                        self.logger().warning(
                            f"⚠️  Invalid market price retrieved ({current_market_price}), falling back to provided price"
                        )
                        # BUG FIX: Check for NaN in addition to None and zero
                        current_market_price = price if (price and price != Decimal("0") and not price.is_nan()) else self._validated_midpoint_price("LIMIT order fallback")
                except Exception as e:
                    # BUG FIX: Handle get_price() failures gracefully
                    self.logger().warning(
                        f"⚠️  Failed to get market price for LIMIT order: {e}. "
                        f"Falling back to provided price or MARKET order."
                    )
                    # Try fallback price, or fall back to MARKET order
                    try:
                        # BUG FIX: Check for NaN in addition to None and zero
                        current_market_price = price if (price and price != Decimal("0") and not price.is_nan()) else self._validated_midpoint_price("LIMIT order fallback")
                    except ValueError:
                        # Cannot get valid price - must use MARKET order instead
                        self.logger().error(
                            "❌ Cannot get valid price for LIMIT order - falling back to MARKET order"
                        )
                        use_limit_order = False
                        current_market_price = Decimal("0")  # Will trigger MARKET order path

                # BUG FIX: Initialize price_diff_pct to avoid UnboundLocalError
                price_diff_pct = 0.0
                limit_price = None

                # Only proceed with LIMIT order if we have a valid price
                if use_limit_order and current_market_price and current_market_price != Decimal("0") and not current_market_price.is_nan():
                    if self.config.side == TradeType.BUY:
                        # Closing BUY position = SELL order, use current price + small buffer (0.05%)
                        # This ensures we get a good price while still using LIMIT order
                        limit_price = current_market_price * Decimal("1.0005")  # 0.05% above market

                        # BITGET FIX: Enforce exchange minimum sell price if known
                        # When Bitget rejects a sell below their min price, we stored it
                        # and must use it (+ buffer) on the retry.
                        if self._exchange_min_sell_price and limit_price < self._exchange_min_sell_price:
                            limit_price = self._exchange_min_sell_price * Decimal("1.001")  # 0.1% above min
                            self.logger().warning(
                                f"⚠️ MIN_SELL_PRICE: Adjusted sell price to {limit_price:.6f} "
                                f"(exchange min: {self._exchange_min_sell_price})"
                            )
                    else:
                        # Closing SELL position = BUY order, use current price - small buffer (0.05%)
                        limit_price = current_market_price * Decimal("0.9995")  # 0.05% below market

                    # Fallback to provided price if limit_price is invalid
                    # BUG FIX: Check if limit_price is None or invalid before calling .is_nan()
                    if limit_price is None or limit_price.is_nan() or limit_price == Decimal("0"):
                        limit_price = price

                    # CRITICAL FIX: Check if LIMIT price is acceptable (within 0.1% of market)
                    # BUG FIX: Validate current_market_price is non-zero before division
                    # BUG FIX: Also ensure limit_price is not None before using it in calculation
                    if limit_price and current_market_price and current_market_price != Decimal("0") and not current_market_price.is_nan():
                        price_diff_pct = abs(float((limit_price - current_market_price) / current_market_price * 100))
                    else:
                        # Invalid market price - cannot calculate diff, use MARKET order
                        self.logger().warning(
                            "⚠️  Invalid market price for diff calculation - using MARKET order instead"
                        )
                        use_limit_order = False
                        price_diff_pct = 0  # Will trigger fallback

                    if price_diff_pct > 0.1:
                        # LIMIT price too far from market - use MARKET order instead
                        self.logger().warning(
                            f"⚠️  LIMIT price ({limit_price:.6f}) too far from market ({current_market_price:.6f}) - "
                            f"using MARKET order instead (diff: {price_diff_pct:.2f}%)"
                        )
                        use_limit_order = False

                if use_limit_order:
                    # BUG FIX: Ensure limit_price is set before placing order
                    if limit_price is None or limit_price == Decimal("0") or limit_price.is_nan():
                        # Fallback to provided price if limit_price is not set
                        # BUG FIX: Check for NaN in addition to None and zero
                        limit_price = price if (price and price != Decimal("0") and not price.is_nan()) else current_market_price
                        if limit_price is None or limit_price == Decimal("0") or limit_price.is_nan():
                            # Cannot use LIMIT order without valid price - fall back to MARKET
                            self.logger().warning(
                                "⚠️  Cannot determine valid limit_price - falling back to MARKET order"
                            )
                            use_limit_order = False

                    if use_limit_order:
                        # Place LIMIT order
                        # BUG FIX: Ensure limit_price and current_market_price are valid before logging
                        if limit_price is not None and current_market_price and current_market_price != Decimal("0"):
                            self.logger().info(
                                f"💰 Placing LIMIT close order: {order_amount_to_use} {base_asset} "
                                f"@ €{limit_price:.6f} (market: €{current_market_price:.6f}, diff: {price_diff_pct:.3f}%)"
                            )
                        else:
                            # BUG FIX: Handle case where limit_price might be None
                            limit_price_str = f"€{limit_price:.6f}" if limit_price is not None else "market price"
                            self.logger().info(
                                f"💰 Placing LIMIT close order: {order_amount_to_use} {base_asset} "
                                f"@ {limit_price_str}"
                            )
                        order_id = self.place_order(
                            connector_name=self.config.connector_name,
                            trading_pair=self.config.trading_pair,
                            order_type=self.config.triple_barrier_config.take_profit_order_type,
                            amount=order_amount_to_use,
                            price=limit_price,
                            side=self.close_order_side,
                            position_action=PositionAction.CLOSE,
                        )
                else:
                    # Fallback to MARKET order when LIMIT price diverges too far
                    # BUG FIX: Handle case where limit_price might be None
                    if limit_price is not None:
                        limit_price_str = f"€{limit_price:.6f}"
                        price_diff_str = f"{price_diff_pct:.2f}%"
                    else:
                        limit_price_str = "N/A"
                        price_diff_str = "N/A"
                    self.logger().info(
                        f"🚨 Placing MARKET close order (LIMIT price diverged): {order_amount_to_use} {base_asset} "
                        f"@ market price (LIMIT price {limit_price_str} was {price_diff_str} from market)"
                    )
                    order_id = self.place_order(
                        connector_name=self.config.connector_name,
                        trading_pair=self.config.trading_pair,
                        order_type=OrderType.MARKET,
                        amount=order_amount_to_use,
                        price=price,  # Use provided price for MARKET order
                        side=self.close_order_side,
                        position_action=PositionAction.CLOSE,
                    )
            else:
                # Phase 1: PANIC EXITS use MARKET for certainty (stop_loss, time_limit, early_stop)
                self.logger().info(
                    f"🚨 PHASE 1: MARKET close order (panic/emergency): {order_amount_to_use} {base_asset} "
                    f"@ €{price:.6f} (close_type: {close_type})"
                )
                self.logger().warning(
                    "⚡ Using MARKET order for exit certainty. Taker fee (~0.01%) is acceptable "
                    "vs delay risk (10s can cost 0.5%+ in panic)"
                )
                order_id = self.place_order(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_type=OrderType.MARKET,
                    amount=order_amount_to_use,
                    price=price,
                    side=self.close_order_side,
                    position_action=PositionAction.CLOSE,
                )

            # Phase 3: Track close order in state machine
            self._close_order = TrackedOrder(order_id=order_id)
            self._close_order_id = order_id
            self.logger().info(f"🔒 Close order placed: {order_id} (state: CLOSING)")
            self.logger().debug(f"Executor ID: {self.config.id} - Placing close order {order_id}")
        else:
            # No amount to close - mark as complete
            self.logger().info("✅ No position to close (amount < min_order_size)")
            self._status = RunnableStatus.TERMINATED
            self._closing_in_progress = False

        self.close_type = close_type
        # Phase 3: State already set to CLOSING above, will transition to SHUTTING_DOWN on fill

    def cancel_open_orders(self):
        """
        Cancel open orders with retry backoff to prevent excessive API calls.

        BITGET FIX: Prevents the bot from spamming cancel requests every 6 seconds.
        Instead, uses exponential backoff (10s, 20s, 30s intervals) between retries.
        Gives up after 5 attempts to avoid infinite retry loops.

        :return: None
        """
        import time

        open_order_placed = [level.active_open_order for level in
                             self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        close_order_placed = [level.active_close_order for level in
                              self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]

        current_time = time.time()

        for order in open_order_placed + close_order_placed:
            if not order:
                continue

            order_id = order.order_id

            # Check if we've exceeded max retries for this order
            retry_count = self._cancel_retry_count.get(order_id, 0)
            if retry_count >= self._cancel_max_retries:
                self.logger().warning(
                    f"⚠️  Executor ID: {self.config.id} - Giving up on canceling order {order_id} "
                    f"after {retry_count} attempts (may already be filled or cancelled)"
                )
                # Remove from tracking to prevent further retries
                self._cancel_request_times.pop(order_id, None)
                self._cancel_retry_count.pop(order_id, None)
                continue

            # Check if enough time has passed since last cancel request (backoff)
            last_cancel_time = self._cancel_request_times.get(order_id, 0)
            time_since_last = current_time - last_cancel_time

            # Exponential backoff: 10s, 20s, 30s, 40s, 50s
            backoff_time = self._cancel_min_interval * (retry_count + 1)

            if time_since_last < backoff_time:
                # Too soon to retry - skip this order
                remaining = backoff_time - time_since_last
                if retry_count > 0:  # Only log for retries, not first attempt
                    self.logger().debug(
                        f"Executor ID: {self.config.id} - Skipping cancel retry for {order_id} "
                        f"(retry {retry_count}, wait {remaining:.1f}s more)"
                    )
                continue

            # Send cancel request
            self._strategy.cancel(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_id=order_id
            )

            # Update tracking
            self._cancel_request_times[order_id] = current_time
            self._cancel_retry_count[order_id] = retry_count + 1

            if retry_count == 0:
                self.logger().debug(f"Executor ID: {self.config.id} - Canceling open order {order_id}")
            else:
                self.logger().info(
                    f"Executor ID: {self.config.id} - Retry {retry_count + 1}/{self._cancel_max_retries} "
                    f"canceling order {order_id} (backoff: {backoff_time:.0f}s)"
                )

    async def cancel_open_orders_and_wait(self, max_wait_seconds: float = 10.0):
        """
        Cancel all open orders and wait for confirmations from exchange.
        This prevents "Insufficient funds" errors when placing close orders immediately after cancelling.

        CRITICAL FIX for Kraken: Kraken locks balances until cancel confirmations are received.
        Without waiting, close orders fail with "Insufficient funds" even though balance is actually available.

        :param max_wait_seconds: Maximum time to wait for all cancellations (default 10 seconds)
        :return: None
        """
        # Get all orders to cancel
        open_order_placed = [level.active_open_order for level in
                             self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        close_order_placed = [level.active_close_order for level in
                              self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        orders_to_cancel = [order for order in open_order_placed + close_order_placed if order]

        if not orders_to_cancel:
            self.logger().debug(f"Executor ID: {self.config.id} - No open orders to cancel")
            return

        # Track which orders need to be cancelled
        pending_cancels = {order.order_id for order in orders_to_cancel}
        self.logger().info(
            f"Executor ID: {self.config.id} - Canceling {len(pending_cancels)} open orders "
            f"and waiting for confirmations..."
        )

        # Send cancel requests
        for order in orders_to_cancel:
            self._strategy.cancel(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_id=order.order_id
            )
            self.logger().debug(f"Executor ID: {self.config.id} - Sent cancel request for {order.order_id}")

        # Wait for cancellations to be confirmed
        start_time = asyncio.get_event_loop().time()
        check_interval = 0.5  # Check every 500ms

        while pending_cancels and (asyncio.get_event_loop().time() - start_time) < max_wait_seconds:
            # Check if orders are still in OPEN_ORDER_PLACED or CLOSE_ORDER_PLACED states
            still_open = []
            for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]:
                if level.active_open_order and level.active_open_order.order_id in pending_cancels:
                    still_open.append(level.active_open_order.order_id)
            for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]:
                if level.active_close_order and level.active_close_order.order_id in pending_cancels:
                    still_open.append(level.active_close_order.order_id)

            # Update pending list
            pending_cancels = set(still_open)

            if not pending_cancels:
                elapsed = asyncio.get_event_loop().time() - start_time
                self.logger().info(
                    f"✅ Executor ID: {self.config.id} - All {len(orders_to_cancel)} orders cancelled successfully "
                    f"in {elapsed:.2f}s"
                )
                break

            # Wait before checking again
            await self._sleep(check_interval)

        # Log results
        if pending_cancels:
            elapsed = asyncio.get_event_loop().time() - start_time
            self.logger().warning(
                f"⚠️  Executor ID: {self.config.id} - {len(pending_cancels)} orders still pending after {elapsed:.1f}s: "
                f"{list(pending_cancels)[:5]}{'...' if len(pending_cancels) > 5 else ''}"
            )
            # Wait a bit more to allow balance to unlock
            await self._sleep(2.0)

    @staticmethod
    def _serialize_grid_level(level) -> Dict:
        """Serialize a GridLevel to a JSON-safe dict (TrackedOrder → order_id string)."""
        return {
            "id": level.id,
            "price": str(level.price),
            "amount_quote": str(level.amount_quote),
            "take_profit": str(level.take_profit),
            "side": level.side.name,
            "open_order_type": level.open_order_type.name,
            "take_profit_order_type": level.take_profit_order_type.name,
            "active_open_order": level.active_open_order.order_id if level.active_open_order else None,
            "active_close_order": level.active_close_order.order_id if level.active_close_order else None,
            "state": level.state.value,
        }

    def get_custom_info(self) -> Dict:
        held_position_value = sum([
            Decimal(order["executed_amount_quote"])
            for order in self._held_position_orders
        ])

        # Preserve entry_* fields from config.custom_info (set by controller at creation)
        initial_info = self.config.custom_info or {}
        entry_fields = {k: v for k, v in initial_info.items() if k.startswith("entry_")}

        return {
            **entry_fields,
            "side": self.config.side,
            "levels_by_state": {
                key.name: [self._serialize_grid_level(lvl) for lvl in value]
                for key, value in self.levels_by_state.items()
            },
            "filled_orders": self._filled_orders,
            "held_position_orders": self._held_position_orders,
            "held_position_value": held_position_value,
            "failed_orders": self._failed_orders,
            "canceled_orders": self._canceled_orders,
            "realized_buy_size_quote": self.realized_buy_size_quote,
            "realized_sell_size_quote": self.realized_sell_size_quote,
            "realized_imbalance_quote": self.realized_imbalance_quote,
            "realized_fees_quote": self.realized_fees_quote,
            "realized_pnl_quote": self.realized_pnl_quote,
            "realized_pnl_pct": self.realized_pnl_pct,
            "position_size_quote": self.position_size_quote,
            "position_fees_quote": self.position_fees_quote,
            "break_even_price": self.position_break_even_price,
            "position_pnl_quote": self.position_pnl_quote,
            "open_liquidity_placed": self.open_liquidity_placed,
            "close_liquidity_placed": self.close_liquidity_placed,
            # US-006: Early stop reason tracking
            "early_stop_reason": self._early_stop_reason.name if self._early_stop_reason else None,
            "early_stop_reason_code": self._early_stop_reason.value if self._early_stop_reason else None,
        }

    async def on_start(self):
        """
        This method is responsible for starting the executor and validating if the position is expired. The base method
        validates if there is enough balance to place the open order.

        :return: None
        """
        await super().on_start()
        self.update_metrics()

        # Check if grid range is still valid before checking triple barrier
        # If price moved outside range, log warning but don't fail immediately
        # (grid might still be useful if price moves back)
        if self.config.side == TradeType.BUY:
            if self.mid_price > self.config.end_price:
                self.logger().warning(
                    f"⚠️  Current price ({self.mid_price:.4f}) above grid end_price ({self.config.end_price:.4f}) "
                    f"- grid may not be effective, but will continue"
                )
            elif self.mid_price < self.config.start_price:
                self.logger().warning(
                    f"⚠️  Current price ({self.mid_price:.4f}) below grid start_price ({self.config.start_price:.4f}) "
                    f"- grid may not be effective, but will continue"
                )
        else:  # TradeType.SELL
            # For SELL grids: start_price is upper bound (where selling begins), end_price is lower bound (buy-back target)
            if self.mid_price > self.config.start_price:
                self.logger().warning(
                    f"⚠️  Current price ({self.mid_price:.4f}) above grid start_price ({self.config.start_price:.4f}) "
                    f"- grid may not be effective, but will continue"
                )
            elif self.mid_price < self.config.end_price:
                self.logger().warning(
                    f"⚠️  Current price ({self.mid_price:.4f}) below grid end_price ({self.config.end_price:.4f}) "
                    f"- grid may not be effective, but will continue"
                )

        # Only fail if triple barrier conditions are truly met (not just price outside range)
        if self.control_triple_barrier():
            # Check if it's just a price-out-of-range issue (which we already warned about)
            if self.close_type == CloseType.TAKE_PROFIT:
                # For BUY grids, TAKE_PROFIT means price > end_price (price risen above sell target)
                # For SELL grids, TAKE_PROFIT means price < end_price (price dropped to take profit zone)
                # This is expected if price moved outside range - don't fail immediately if no position yet
                price_out_of_range = False
                if self.config.side == TradeType.BUY and self.mid_price > self.config.end_price:
                    price_out_of_range = True
                    self.logger().warning(
                        f"⚠️  Grid range exceeded (price {self.mid_price:.4f} > end {self.config.end_price:.4f}) "
                        f"- but no position yet, so continuing"
                    )
                elif self.config.side == TradeType.SELL:
                    # Check if this is a futures SHORT grid
                    is_short_mode = (
                        self.config.custom_info and
                        self.config.custom_info.get('trade_direction', '').lower() == 'short'
                    )
                    if is_short_mode:
                        # SHORT futures: out of range when price drops below end_price (TP zone)
                        if self.mid_price < self.config.end_price:
                            price_out_of_range = True
                            self.logger().warning(
                                f"⚠️  SHORT grid range exceeded (price {self.mid_price:.4f} < end {self.config.end_price:.4f}) "
                                f"- but no position yet, so continuing"
                            )
                    else:
                        # Traditional SELL: out of range when price drops below start_price
                        if self.mid_price < self.config.start_price:
                            price_out_of_range = True
                            self.logger().warning(
                                f"⚠️  Grid range exceeded (price {self.mid_price:.4f} < start {self.config.start_price:.4f}) "
                                f"- but no position yet, so continuing"
                            )

                if price_out_of_range:
                    # Check if there's an open position (filled open orders without close orders)
                    # A position exists if:
                    # 1. There are levels with OPEN_ORDER_FILLED state, OR
                    # 2. There are filled orders (which indicates some trading activity)
                    # Update grid levels first to ensure state is current
                    self.update_grid_levels()
                    has_open_position = (
                        len(self.levels_by_state.get(GridLevelStates.OPEN_ORDER_FILLED, [])) > 0 or
                        len(self._filled_orders) > 0
                    )

                    if not has_open_position:
                        # No position yet - respect triple barrier by shutting down cleanly
                        self.logger().info(
                            f"Grid range exceeded but no position yet - shutting down (close_type={self.close_type})"
                        )
                        self._status = RunnableStatus.SHUTTING_DOWN
                        return
                    else:
                        # There IS a position - should shutdown with TAKE_PROFIT
                        # Don't reset close_type, let it proceed to shutdown
                        self.logger().warning(
                            "⚠️  Grid range exceeded with open position - shutting down with TAKE_PROFIT"
                        )
                        # Shutdown immediately - no need to continue to general shutdown logic
                        self.logger().error(f"Grid is already expired by {self.close_type}.")
                        self._status = RunnableStatus.SHUTTING_DOWN
                        return

            # For other close types (stop loss, time limit, etc.), or TAKE_PROFIT when price is in range, fail as normal
            # Note: self.close_type is guaranteed to be set here (either TAKE_PROFIT that wasn't handled above, or another close type)
            # The TAKE_PROFIT case with position already handled above with early return
            if self.close_type is not None:
                self.logger().error(f"Grid is already expired by {self.close_type}.")
                self._status = RunnableStatus.SHUTTING_DOWN
            else:
                # This should not happen, but handle it gracefully
                # Note: This can only occur if control_triple_barrier() returns True but close_type is None,
                # which should not happen in normal operation
                self.logger().error("Grid triple barrier condition met but close_type is None.")
                self._status = RunnableStatus.SHUTTING_DOWN

    def _log_orphan_risk_if_inventory(self):
        """Log CRITICAL alert if executor is terminating while still holding inventory."""
        try:
            self.update_position_metrics()
            if self.position_size_base > Decimal("0"):
                base_asset = self.config.trading_pair.split("-")[0]
                approx_value = float(self.position_size_base * self.mid_price) if self.mid_price else 0.0
                self.logger().error(
                    f"🚨 ORPHAN_RISK: {self.config.trading_pair} | "
                    f"Executor terminating with {float(self.position_size_base):.6f} {base_asset} "
                    f"(~${approx_value:.2f}) still on exchange! "
                    f"close_type={self.close_type}, reason={self._early_stop_reason} | "
                    f"Manual intervention may be required."
                )
        except Exception:
            pass  # Don't block termination if logging fails

    def evaluate_max_retries(self):
        """
        This method is responsible for evaluating the maximum number of retries to place an order and stop the executor
        if the maximum number of retries is reached.

        When inventory exists, attempt a market-order sell before giving up.
        This prevents orphan coins stuck on the exchange after ORDER_REJECTED failures.
        """
        if self._current_retries > self._max_retries:
            # FIX: If an unwind is already in progress (GRACEFUL or AGGRESSIVE),
            # do NOT terminate — let the unwind phases complete their sell orders.
            # The previous code would kill the executor on the very next tick after
            # start_forced_close because _market_retry_attempted was already True.
            if self._unwind_phase in ("GRACEFUL", "AGGRESSIVE"):
                # SAFETY NET: If unwind has been active > 10 minutes, check if the
                # close order already filled but position_size_base has dust.
                # This prevents the executor from blocking capital forever when the
                # sell order filled but rounding dust keeps position_size_base > 0.
                if self._unwind_started_ts:
                    unwind_age = self._strategy.current_timestamp - self._unwind_started_ts
                    if unwind_age > 600:  # 10 minutes
                        self.update_position_metrics()
                        min_order_size = getattr(self.trading_rules, 'min_order_size', Decimal("1"))
                        close_order_filled = (
                            self._close_order is not None
                            and self._close_order.order is not None
                            and self._close_order.order.is_filled
                        )
                        if close_order_filled and self.position_size_base < min_order_size:
                            self.logger().warning(
                                f"⏰ Unwind stuck for {unwind_age:.0f}s but close order filled with dust "
                                f"({float(self.position_size_base):.10f} < min {float(min_order_size)}) — "
                                f"forcing completion for {self.config.trading_pair}"
                            )
                            self._unwind_phase = "DONE"
                            self.close_type = CloseType.EARLY_STOP
                            self._early_stop_reason = EarlyStopReason.NO_PROGRESS_TIMEOUT
                            self.stop()
                            return

                self.logger().debug(
                    f"Max retries exceeded but unwind phase={self._unwind_phase} active — "
                    f"letting unwind complete for {self.config.trading_pair}"
                )
                return

            # Check if we have inventory that needs to be sold
            self.update_position_metrics()
            if self.position_size_base > Decimal("0") and not getattr(self, '_market_retry_attempted', False):
                self._market_retry_attempted = True
                self.logger().warning(
                    f"🔄 Max retries ({self._max_retries}) reached for {self.config.trading_pair} "
                    f"but have inventory {float(self.position_size_base):.6f} — "
                    f"attempting forced market close to prevent orphan"
                )
                self.start_forced_close(CloseType.FAILED)
                return  # Don't stop yet — let forced close handle it

            self.close_type = CloseType.FAILED
            # US-006: Set early stop reason for max retries
            self._early_stop_reason = EarlyStopReason.ORDER_REJECTED
            self._log_orphan_risk_if_inventory()
            self.stop()

    def update_tracked_orders_with_order_id(self, order_id: str):
        """
        This method is responsible for updating the tracked orders with the information from the InFlightOrder, using
        the order_id as a reference.

        :param order_id: The order_id to be used as a reference.
        :return: None
        """
        self.update_grid_levels()
        in_flight_order = self.get_in_flight_order(self.config.connector_name, order_id)
        if in_flight_order:
            for level in self.grid_levels:
                if level.active_open_order and level.active_open_order.order_id == order_id:
                    level.active_open_order.order = in_flight_order
                if level.active_close_order and level.active_close_order.order_id == order_id:
                    level.active_close_order.order = in_flight_order
            if self._close_order and self._close_order.order_id == order_id:
                self._close_order.order = in_flight_order

    def process_order_created_event(self, _, market, event: Union[BuyOrderCreatedEvent, SellOrderCreatedEvent]):
        """
        This method is responsible for processing the order created event. Here we will update the TrackedOrder with the
        order_id.
        """
        self.update_tracked_orders_with_order_id(event.order_id)

    def process_order_filled_event(self, _, market, event: OrderFilledEvent):
        """
        This method is responsible for processing the order filled event. Here we will update the value of
        _total_executed_amount_backup, that can be used if the InFlightOrder
        is not available.
        """
        self.update_tracked_orders_with_order_id(event.order_id)

        # STORY A1: Update last_fill_timestamp (any fill = activity)
        self._last_fill_timestamp = self._strategy.current_timestamp

    def process_order_completed_event(self, _, market, event: Union[BuyOrderCompletedEvent, SellOrderCompletedEvent]):
        """
        This method is responsible for processing the order completed event. Here we will check if the id is one of the
        tracked orders and update the state
        """
        self.update_tracked_orders_with_order_id(event.order_id)

    def process_order_canceled_event(self, _, market: ConnectorBase, event: OrderCancelledEvent):
        """
        This method is responsible for processing the order canceled event
        """
        # BITGET FIX: Clear cancel retry tracking when order is successfully cancelled
        order_id = event.order_id
        if order_id in self._cancel_request_times:
            retry_count = self._cancel_retry_count.get(order_id, 0)
            if retry_count > 0:
                self.logger().debug(
                    f"✅ Executor ID: {self.config.id} - Order {order_id} cancelled successfully "
                    f"after {retry_count} attempts"
                )
            self._cancel_request_times.pop(order_id, None)
            self._cancel_retry_count.pop(order_id, None)

        self.update_grid_levels()
        levels_open_order_placed = [level for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        levels_close_order_placed = [level for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        for level in levels_open_order_placed:
            if event.order_id == level.active_open_order.order_id:
                self._canceled_orders.append(level.active_open_order.order_id)
                self.max_open_creation_timestamp = 0
                level.reset_open_order()
        for level in levels_close_order_placed:
            if event.order_id == level.active_close_order.order_id:
                self._canceled_orders.append(level.active_close_order.order_id)
                self.max_close_creation_timestamp = 0
                level.reset_close_order()
        if self._close_order and event.order_id == self._close_order.order_id:
            self._canceled_orders.append(self._close_order.order_id)
            self._close_order = None
            # ZOMBIE GUARD FIX: Reset close guard so executor can retry close.
            # Without this, _closing_in_progress stays True after a cancelled
            # close order (e.g. zombie from previous run) → orphan.
            self._closing_in_progress = False
            self._close_order_id = None
        elif self._close_order_id and event.order_id == self._close_order_id:
            # Safety net: _close_order already None but order_id still matches
            self._canceled_orders.append(event.order_id)
            self._closing_in_progress = False
            self._close_order_id = None

    def process_order_failed_event(self, _, market, event: MarketOrderFailureEvent):
        """
        This method is responsible for processing the order failed event. Here we will add the InFlightOrder to the
        failed orders list.
        """
        # BITGET FIX: Clear cancel retry tracking when order fails (including "order not found" errors)
        order_id = event.order_id
        if order_id in self._cancel_request_times:
            # Check if this is an "order not found" error (order already cancelled)
            error_msg = str(event).lower()
            if "not found" in error_msg or "not exist" in error_msg:
                self.logger().debug(
                    f"✅ Executor ID: {self.config.id} - Order {order_id} already cancelled "
                    f"(received 'not found' error after {self._cancel_retry_count.get(order_id, 0)} attempts)"
                )
            self._cancel_request_times.pop(order_id, None)
            self._cancel_retry_count.pop(order_id, None)

        # CRITICAL: Check for Kraken NL-restriction errors first
        # Pattern: "EAccount:Invalid permissions:STBL trading restricted for NL."
        error_msg_full = str(event)  # Preserve case for matching
        error_msg = error_msg_full.lower()

        # Detect NL-restriction pattern
        is_nl_restricted = (
            "trading restricted for nl" in error_msg
            or ("invalid permissions" in error_msg and "trading restricted" in error_msg)
        )

        if is_nl_restricted:
            # Extract coin from trading pair (e.g., "STBL-EUR" -> "STBL-EUR")
            trading_pair = self.config.trading_pair
            self.logger().warning(
                f"🚫 NL-RESTRICTION: {trading_pair} is restricted for NL accounts on Kraken\n"
                f"   Error: {error_msg_full}\n"
                f"   This coin will be auto-blacklisted to prevent retries."
            )
            # Mark this executor with NL-restriction flag for controller to detect
            self._nl_restricted = True
            self._nl_restricted_coin = trading_pair
            # Also store in custom_info so ExecutorInfo can access it
            self._custom_info['nl_restricted'] = True
            self._custom_info['nl_restricted_coin'] = trading_pair
            # Terminate executor immediately - no point retrying
            self._status = RunnableStatus.TERMINATED
            return  # Skip normal error processing

        # BUG FIX: Check if this is an "Insufficient funds" error on close orders
        # If so, mark the level for early shutdown to prevent infinite retries
        is_insufficient_funds = ("insufficient" in error_msg and ("fund" in error_msg or "balance" in error_msg))

        # BITGET FIX: Detect min sell price rejection (error 41117)
        # Bitget rejects sells below an exchange-enforced minimum price:
        #   "HUMA/USDT selling price cannot be lower than 0.02001"
        # Parse the min price and store it so the next close attempt uses it.
        is_price_rejected = "selling price cannot be lower" in error_msg
        if is_price_rejected:
            self._price_rejected_retries += 1
            # Parse the minimum price from the error message
            import re
            match = re.search(r'lower than\s+([\d.]+)', error_msg)
            if match:
                try:
                    self._exchange_min_sell_price = Decimal(match.group(1))
                    self.logger().warning(
                        f"⚠️ PRICE_REJECTED: {self.config.trading_pair} sell rejected — "
                        f"exchange min sell price is {self._exchange_min_sell_price} "
                        f"(retry {self._price_rejected_retries}/{self._max_price_rejected_retries})"
                    )
                except Exception:
                    self.logger().warning(
                        f"⚠️ PRICE_REJECTED: Could not parse min price from: {error_msg_full}"
                    )
            else:
                self.logger().warning(
                    f"⚠️ PRICE_REJECTED: {self.config.trading_pair} sell rejected "
                    f"(retry {self._price_rejected_retries}/{self._max_price_rejected_retries})"
                )

            if self._price_rejected_retries >= self._max_price_rejected_retries:
                # Exhausted retries — fall through to MARKET order on next attempt
                # by treating this like insufficient_funds (forces MARKET)
                self.logger().warning(
                    f"⚠️ PRICE_REJECTED: Max retries reached for {self.config.trading_pair}, "
                    f"next close attempt will use MARKET order"
                )
                self._insufficient_funds_retries = 1  # Trigger MARKET order path

        self.update_grid_levels()
        levels_open_order_placed = [level for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        levels_close_order_placed = [level for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        for level in levels_open_order_placed:
            if event.order_id == level.active_open_order.order_id:
                self._failed_orders.append(level.active_open_order.order_id)
                self.max_open_creation_timestamp = 0
                level.reset_open_order()

                # CRITICAL FIX: Handle "Insufficient funds" on OPEN/BUY orders
                # This prevents infinite retry spam when account has insufficient balance
                if is_insufficient_funds:
                    self._insufficient_funds_retries += 1
                    self.logger().warning(
                        f"⚠️ Executor {self.config.id[:8]}... OPEN order failed with 'Insufficient funds' "
                        f"(retry {self._insufficient_funds_retries}/{self._max_insufficient_funds_retries}). "
                        f"Account balance too low for {self.config.trading_pair}."
                    )

                    # Terminate immediately after max retries
                    if self._insufficient_funds_retries >= self._max_insufficient_funds_retries:
                        self.logger().error(
                            f"❌ Executor {self.config.id[:8]}... TERMINATING: Insufficient funds after "
                            f"{self._max_insufficient_funds_retries} retries. Need more {self.config.trading_pair.split('-')[1]} balance."
                        )
                        self._status = RunnableStatus.TERMINATED
                        self.close_type = CloseType.INSUFFICIENT_BALANCE
                        self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                        return

        for level in levels_close_order_placed:
            if event.order_id == level.active_close_order.order_id:
                self._failed_orders.append(level.active_close_order.order_id)
                self.max_close_creation_timestamp = 0
                level.reset_close_order()

                # BITGET FIX: Handle price rejection on level close order
                if is_price_rejected:
                    self._closing_in_progress = False
                    self._close_order_id = None
                    continue  # Allow retry with corrected price

                # BUG FIX: If this is an insufficient funds error, log warning and mark executor for shutdown
                # This prevents infinite retry loops with wrong amounts
                if is_insufficient_funds:
                    self._insufficient_funds_retries += 1
                    self.logger().warning(
                        f"⚠️ Executor {self.config.id[:8]}... Close order failed with 'Insufficient funds' "
                        f"(retry {self._insufficient_funds_retries}/{self._max_insufficient_funds_retries}). "
                        f"This likely means position was already sold. Resetting close state."
                    )

                    # If we hit max retries during GRACEFUL unwind, escalate to AGGRESSIVE
                    # instead of terminating — AGGRESSIVE uses _determine_close_order_amount
                    # which caps to available balance.
                    if self._insufficient_funds_retries >= self._max_insufficient_funds_retries:
                        if self._unwind_phase == "GRACEFUL":
                            self.logger().warning(
                                f"⚠️  Executor {self.config.id[:8]}... Insufficient funds during GRACEFUL "
                                f"unwind — escalating to AGGRESSIVE (market order with balance cap)"
                            )
                            self._unwind_phase = "AGGRESSIVE"
                            self._closing_in_progress = False
                            self._close_order_id = None
                            self._insufficient_funds_retries = 0  # Reset for aggressive phase
                            return

                        self.logger().error(
                            f"❌ Executor {self.config.id[:8]}... Insufficient funds errors exceeded max retries "
                            f"({self._max_insufficient_funds_retries}). Terminating executor."
                        )
                        self._status = RunnableStatus.TERMINATED
                        self.close_type = CloseType.FAILED
                        # US-006: Set early stop reason
                        self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                        self._log_orphan_risk_if_inventory()
                        return

                    # Phase 3+: Reset guard to allow retry with fresh balance check
                    self._closing_in_progress = False
                    self._close_order_id = None

        if self._close_order and event.order_id == self._close_order.order_id:
            self._failed_orders.append(self._close_order.order_id)
            self._close_order = None

            # BITGET FIX: Handle price rejection on main close order
            # Reset closing state so the next attempt uses the corrected min price
            if is_price_rejected:
                self._closing_in_progress = False
                self._close_order_id = None
                return  # Don't fall through to insufficient funds — handled above

            # BUG FIX: Same insufficient funds handling for main close order
            if is_insufficient_funds:
                self._insufficient_funds_retries += 1
                self.logger().warning(
                    f"⚠️ Executor {self.config.id[:8]}... Main close order failed with 'Insufficient funds' "
                    f"(retry {self._insufficient_funds_retries}/{self._max_insufficient_funds_retries}). "
                    f"Resetting close guard to allow retry."
                )

                # After max retries, escalate or terminate
                if self._insufficient_funds_retries >= self._max_insufficient_funds_retries:
                    if self._unwind_phase == "GRACEFUL":
                        self.logger().warning(
                            f"⚠️  Executor {self.config.id[:8]}... Main close: Insufficient funds during "
                            f"GRACEFUL unwind — escalating to AGGRESSIVE (market order with balance cap)"
                        )
                        self._unwind_phase = "AGGRESSIVE"
                        self._closing_in_progress = False
                        self._close_order_id = None
                        self._insufficient_funds_retries = 0  # Reset for aggressive phase
                        return

                    self.logger().error(
                        f"❌ Executor {self.config.id[:8]}... Insufficient funds errors exceeded max retries "
                        f"({self._max_insufficient_funds_retries}). Terminating executor."
                    )
                    self._status = RunnableStatus.TERMINATED
                    self.close_type = CloseType.FAILED
                    # US-006: Set early stop reason
                    self._early_stop_reason = EarlyStopReason.INSUFFICIENT_BALANCE
                    self._log_orphan_risk_if_inventory()
                    return

            # FAILED-ORDER GUARD FIX: Always reset close guard after any
            # failed close order so the executor can retry instead of
            # spinning forever with "awaiting exchange confirmation".
            self._closing_in_progress = False
            self._close_order_id = None

    def update_position_metrics(self):
        """
        Calculate the unrealized pnl in quote asset

        :return: The unrealized pnl in quote asset.
        """
        open_filled_levels = self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED] + self.levels_by_state[
            GridLevelStates.CLOSE_ORDER_PLACED]
        side_multiplier = 1 if self.config.side == TradeType.BUY else -1
        executed_amount_base = Decimal(sum([level.active_open_order.order.amount for level in open_filled_levels]))
        if executed_amount_base == Decimal("0"):
            self.position_size_base = Decimal("0")
            self.position_size_quote = Decimal("0")
            self.position_fees_quote = Decimal("0")
            self.position_pnl_quote = Decimal("0")
            self.position_pnl_pct = Decimal("0")
            self.close_liquidity_placed = Decimal("0")
        else:
            self.position_break_even_price = sum(
                [level.active_open_order.order.price * level.active_open_order.order.amount
                 for level in open_filled_levels]) / executed_amount_base
            if self._open_fee_in_base:
                executed_amount_base -= sum([level.active_open_order.cum_fees_base for level in open_filled_levels])
            close_order_size_base = self._close_order.executed_amount_base if self._close_order and self._close_order.is_done else Decimal(
                "0")
            self.position_size_base = executed_amount_base - close_order_size_base
            self.position_size_quote = self.position_size_base * self.position_break_even_price
            self.position_fees_quote = Decimal(sum([level.active_open_order.cum_fees_quote for level in open_filled_levels]))
            self.position_pnl_quote = side_multiplier * ((self.mid_price - self.position_break_even_price) / self.position_break_even_price) * self.position_size_quote - self.position_fees_quote
            self.position_pnl_pct = self.position_pnl_quote / self.position_size_quote if self.position_size_quote > 0 else Decimal(
                "0")
            self.close_liquidity_placed = sum([level.amount_quote for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED] if level.active_close_order and level.active_close_order.executed_amount_base == Decimal("0")])
        if len(self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]) > 0:
            self.open_liquidity_placed = sum([level.amount_quote for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED] if level.active_open_order and level.active_open_order.executed_amount_base == Decimal("0")])
        else:
            self.open_liquidity_placed = Decimal("0")

    def update_realized_pnl_metrics(self):
        """
        Calculate the realized pnl in quote asset, excluding held positions
        """
        if len(self._filled_orders) == 0:
            self._reset_metrics()
            return
        # Calculate metrics only for fully closed trades (not held positions)
        regular_filled_orders = [order for order in self._filled_orders
                                 if order not in self._held_position_orders]
        if len(regular_filled_orders) == 0:
            self._reset_metrics()
            return
        if self._open_fee_in_base:
            self.realized_buy_size_quote = sum([
                Decimal(order["executed_amount_quote"]) - Decimal(order["cumulative_fee_paid_quote"])
                for order in regular_filled_orders if order["trade_type"] == TradeType.BUY.name
            ])
        else:
            self.realized_buy_size_quote = sum([
                Decimal(order["executed_amount_quote"])
                for order in regular_filled_orders if order["trade_type"] == TradeType.BUY.name
            ])
        self.realized_sell_size_quote = sum([
            Decimal(order["executed_amount_quote"])
            for order in regular_filled_orders if order["trade_type"] == TradeType.SELL.name
        ])
        self.realized_imbalance_quote = self.realized_buy_size_quote - self.realized_sell_size_quote
        self.realized_fees_quote = sum([
            Decimal(order["cumulative_fee_paid_quote"])
            for order in regular_filled_orders
        ])
        self.realized_pnl_quote = (
            self.realized_sell_size_quote -
            self.realized_buy_size_quote -
            self.realized_fees_quote
        )
        self.realized_pnl_pct = (
            self.realized_pnl_quote / self.realized_buy_size_quote
            if self.realized_buy_size_quote > 0 else Decimal("0")
        )

    def _reset_metrics(self):
        """Helper method to reset all PnL metrics"""
        self.realized_buy_size_quote = Decimal("0")
        self.realized_sell_size_quote = Decimal("0")
        self.realized_imbalance_quote = Decimal("0")
        self.realized_fees_quote = Decimal("0")
        self.realized_pnl_quote = Decimal("0")
        self.realized_pnl_pct = Decimal("0")

    def get_net_pnl_quote(self) -> Decimal:
        """
        Calculate the net pnl in quote asset

        :return: The net pnl in quote asset.
        """
        return self.position_pnl_quote + self.realized_pnl_quote if self.close_type != CloseType.POSITION_HOLD else self.realized_pnl_quote

    def get_cum_fees_quote(self) -> Decimal:
        """
        Calculate the cumulative fees in quote asset

        :return: The cumulative fees in quote asset.
        """
        return self.position_fees_quote + self.realized_fees_quote if self.close_type != CloseType.POSITION_HOLD else self.realized_fees_quote

    @property
    def filled_amount_quote(self) -> Decimal:
        """
        Calculate the total amount in quote asset

        :return: The total amount in quote asset.
        """
        matched_volume = self.realized_buy_size_quote + self.realized_sell_size_quote
        return self.position_size_quote + matched_volume if self.close_type != CloseType.POSITION_HOLD else matched_volume

    def get_net_pnl_pct(self) -> Decimal:
        """
        Calculate the net pnl percentage

        DEFENSIVE: Prevents absurd values when filled_amount is tiny (precision bug)
        Returns 0 if filled_amount < $1 (sub-dollar position = meaningless %)
        Also caps result at ±100% (anything beyond that is likely a calculation error)

        :return: The net pnl percentage.
        """
        if self.filled_amount_quote <= Decimal("1"):
            # Position too small to calculate meaningful percentage
            # (prevents -2162.46% or -92.44% display bugs from micro-fills)
            return Decimal("0")

        pnl_pct = self.get_net_pnl_quote() / self.filled_amount_quote

        # Sanity check: cap at ±100% - anything higher is a calculation bug
        # (e.g., from fees being larger than position due to precision issues)
        if pnl_pct > Decimal("1"):
            return Decimal("0")
        if pnl_pct < Decimal("-1"):
            return Decimal("0")

        return pnl_pct

    async def _sleep(self, delay: float):
        """
        This method is responsible for sleeping the executor for a specific time.

        :param delay: The time to sleep.
        :return: None
        """
        await asyncio.sleep(delay)
