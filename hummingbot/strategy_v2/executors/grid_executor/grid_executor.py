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
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder
from hummingbot.strategy_v2.utils.distributions import Distributions


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
        if config.triple_barrier_config.time_limit_order_type != OrderType.MARKET or \
                config.triple_barrier_config.stop_loss_order_type != OrderType.MARKET:
            error = "Only market orders are supported for time_limit and stop_loss"
            self.logger().error(error)
            raise ValueError(error)
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
        self._close_balance_max_retries = 5  # how many times we wait for locked balances

    @property
    def is_perpetual(self) -> bool:
        """
        Check if the exchange connector is perpetual.

        :return: True if the exchange connector is perpetual, False otherwise.
        """
        return self.is_perpetual_connector(self.config.connector_name)

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
        if adjusted_order_candidates[0].amount == Decimal("0"):
            # Log detailed error info
            if self.is_perpetual:
                connector = self.connectors.get(self.config.connector_name)
                if connector:
                    # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
                    trading_pair_parts = self.config.trading_pair.split("-")
                    if len(trading_pair_parts) < 2:
                        self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
                        self.close_type = CloseType.INSUFFICIENT_BALANCE
                        self.logger().error("Not enough budget to open position.")
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
            self.logger().error("Not enough budget to open position.")
            self.stop()

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
        """
        return self._status in [RunnableStatus.RUNNING, RunnableStatus.NOT_STARTED, RunnableStatus.SHUTTING_DOWN]

    async def control_task(self):
        """
        This method is responsible for controlling the task based on the status of the executor.

        :return: None
        """
        self.update_grid_levels()
        self.update_metrics()
        if self.status == RunnableStatus.RUNNING:
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
            for level in close_orders_to_create:
                self.adjust_and_place_close_order(level)
            for orders_id_to_cancel in open_order_ids_to_cancel + close_order_ids_to_cancel:
                # TODO: Implement batch order cancel
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=orders_id_to_cancel
                )
        elif self.status == RunnableStatus.SHUTTING_DOWN:
            await self.control_shutdown_process()
        self.evaluate_max_retries()

    def early_stop(self, keep_position: bool = False):
        """
        This method allows strategy to stop the executor early.

        :return: None
        """
        self.cancel_open_orders()
        self._status = RunnableStatus.SHUTTING_DOWN
        self.close_type = CloseType.POSITION_HOLD if keep_position else CloseType.EARLY_STOP

        # If keep_position=False, close any open position immediately
        if not keep_position:
            # Update metrics to get current position size and price
            self.update_position_metrics()
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
                self.levels_by_state = {}
                self.stop()
            else:
                # Regular shutdown process for non-held positions
                order_execution_completed = self.position_size_base == Decimal("0")
                if order_execution_completed:
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
                self.logger().info("Waiting for close order to be filled")
            else:
                self._failed_orders.append(self._close_order.order_id)
                self._close_order = None
        elif not self.config.keep_position or (self.close_type is not None and self.close_type != CloseType.POSITION_HOLD):
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

            order_amount = await self._determine_close_order_amount(self.position_size_base)
            if order_amount is None:
                # Wait for next loop (or manual action) before attempting again
                return

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
        rejection_reason = self._validate_open_order_candidate(order_candidate)
        if rejection_reason is not None:
            self.logger().warning(
                f"🚫 Skipping open order for {self.config.trading_pair}: {rejection_reason}"
            )
            self._failed_orders.append(order_candidate)
            return

        if order_candidate.amount > 0:
            order_id = self.place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=self.config.triple_barrier_config.open_order_type,
                amount=order_candidate.amount,
                price=order_candidate.price,
                side=order_candidate.order_side,
                position_action=PositionAction.OPEN,
            )
            level.active_open_order = TrackedOrder(order_id=order_id)
            self.max_open_creation_timestamp = self._strategy.current_timestamp
            self.logger().debug(f"Executor ID: {self.config.id} - Placing open order {order_id}")

    def adjust_and_place_close_order(self, level: GridLevel):
        order_candidate = self._get_close_order_candidate(level)
        self.adjust_order_candidates(self.config.connector_name, [order_candidate])
        if order_candidate.amount > 0:
            order_id = self.place_order(
                connector_name=self.config.connector_name,
                trading_pair=self.config.trading_pair,
                order_type=self.config.triple_barrier_config.take_profit_order_type,
                amount=order_candidate.amount,
                price=order_candidate.price,
                side=order_candidate.order_side,
                position_action=PositionAction.CLOSE,
            )
            level.active_close_order = TrackedOrder(order_id=order_id)
            self.logger().debug(f"Executor ID: {self.config.id} - Placing close order {order_id}")

    def get_take_profit_price(self, level: GridLevel):
        return level.price * (1 + level.take_profit) if self.config.side == TradeType.BUY else level.price * (1 - level.take_profit)

    def _get_open_order_candidate(self, level: GridLevel):
        if ((level.side == TradeType.BUY and level.price >= self.current_open_quote) or
                (level.side == TradeType.SELL and level.price <= self.current_open_quote)):
            entry_price = self.current_open_quote * (1 - self.config.safe_extra_spread) if level.side == TradeType.BUY else self.current_open_quote * (1 + self.config.safe_extra_spread)
        else:
            entry_price = level.price
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

    def _validate_open_order_candidate(self, order_candidate: Union[OrderCandidate, PerpetualOrderCandidate]) -> Optional[str]:
        order_amount_quote = order_candidate.amount * order_candidate.price

        max_position_size_quote = getattr(self.config, "max_position_size_quote", None)
        if max_position_size_quote is not None and order_amount_quote > max_position_size_quote:
            return (
                f"order notional {order_amount_quote:.8f} exceeds configured max_position_size_quote "
                f"{max_position_size_quote}"
            )

        trading_rule = getattr(self, "trading_rules", None)
        if trading_rule is not None:
            max_order_size = getattr(trading_rule, "max_order_size", None)
            if max_order_size:
                max_order_notional = Decimal(str(max_order_size)) * order_candidate.price
                if order_amount_quote > max_order_notional:
                    return (
                        f"order notional {order_amount_quote:.8f} exceeds connector max order size "
                        f"{max_order_notional:.8f}"
                    )

            max_notional_size = getattr(trading_rule, "max_notional_size", None)
            if max_notional_size:
                max_notional_size_decimal = Decimal(str(max_notional_size))
                if order_amount_quote > max_notional_size_decimal:
                    return (
                        f"order notional {order_amount_quote:.8f} exceeds connector max notional size "
                        f"{max_notional_size_decimal}"
                    )

        min_liquidation_distance_pct = getattr(self.config, "min_liquidation_distance_pct", None)
        if self.is_perpetual and min_liquidation_distance_pct is not None and min_liquidation_distance_pct > 0:
            liquidation_price = self._projected_liquidation_price(order_candidate.price)
            if liquidation_price is not None and self.mid_price > 0:
                distance_pct = abs((self.mid_price - liquidation_price) / self.mid_price) * Decimal("100")
                if distance_pct < min_liquidation_distance_pct:
                    return (
                        f"projected liquidation price {liquidation_price:.8f} only {distance_pct:.4f}% away from mid price "
                        f"{self.mid_price:.8f} (min required {min_liquidation_distance_pct}%)"
                    )

        return None

    def _projected_liquidation_price(self, entry_price: Decimal) -> Optional[Decimal]:
        leverage = Decimal(str(self.config.leverage)) if getattr(self.config, "leverage", None) else None
        if leverage is None or leverage <= 0:
            return None

        distance_factor = Decimal("1") / leverage
        if self.config.side == TradeType.BUY:
            return entry_price * (Decimal("1") - distance_factor)
        return entry_price * (Decimal("1") + distance_factor)

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

        :return: None
        """
        close_orders_proposal = []
        open_orders_filled = self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]
        for level in open_orders_filled:
            if self.config.activation_bounds:
                tp_to_mid = abs(self.get_take_profit_price(level) - self.mid_price) / self.mid_price
                if tp_to_mid < self.config.activation_bounds:
                    close_orders_proposal.append(level)
            else:
                close_orders_proposal.append(level)
        return close_orders_proposal

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
        This method is responsible for controlling the close orders. It will check if the take profit is greater than the
        current price and cancel the close order.

        :return: None
        """
        if self.config.activation_bounds:
            close_orders_to_cancel = []
            close_orders_placed = [level.active_close_order for level in
                                   self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
            for order in close_orders_placed:
                price = order.price
                if price:
                    distance_to_mid = abs(price - self.mid_price) / self.mid_price
                    if distance_to_mid > self.config.activation_bounds:
                        close_orders_to_cancel.append(order.order_id)
            return close_orders_to_cancel
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
        Take profit condition:
        - For BUY grids: trigger when mid_price > end_price (price has risen above sell target)
        - For SELL grids: trigger when mid_price < start_price (price has dropped below upper bound)

        Note: For SELL grids, start_price is the upper bound (where selling begins) and end_price is the
        lower bound (buy-back target). Take-profit should trigger when price drops below start_price,
        indicating the sell grid has reached its profit target.
        """
        if self.config.side == TradeType.BUY:
            # BUY grid: take profit when price rises above end_price (sell target)
            return self.mid_price > self.config.end_price
        else:
            # SELL grid: take profit when price drops below start_price (upper bound)
            # BUG FIX: Changed from end_price to start_price for correct SELL grid take-profit logic
            # This ensures the strategy triggers take-profit at the correct price level
            return self.mid_price < self.config.start_price

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
        self.cancel_open_orders()
        min_order_size = getattr(self.trading_rules, "min_order_size", Decimal("0"))
        target_amount = order_amount if order_amount is not None else self.position_size_base

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

            # FIX: Check available balance before placing market order to prevent "Insufficient funds" errors
            # BUG FIX: Validate trading_pair format before splitting to avoid IndexError
            trading_pair_parts_balance = self.config.trading_pair.split("-")
            if len(trading_pair_parts_balance) < 2:
                self.logger().error(f"❌ Invalid trading_pair format: {self.config.trading_pair}")
                return
            base_asset = trading_pair_parts_balance[0]
            try:
                available_balance = self._coerce_to_decimal(
                    self.connectors[self.config.connector_name].get_available_balance(base_asset)
                )
                if available_balance < target_amount:
                    self.logger().error(
                        f"❌ INSUFFICIENT BALANCE: Cannot place close order - "
                        f"Available: {available_balance} {base_asset}, "
                        f"Required: {target_amount} {base_asset}"
                    )
                    # Adjust amount to available balance if possible
                    if available_balance >= min_order_size:
                        self.logger().warning(
                            f"⚠️  Adjusting order amount from {target_amount} to {available_balance} {base_asset}"
                        )
                        order_amount_to_use = available_balance
                    else:
                        self.logger().error(
                            f"❌ Available balance ({available_balance}) below minimum order size "
                            f"({min_order_size}) - cannot place order"
                        )
                        return
                else:
                    order_amount_to_use = target_amount
            except Exception as e:
                self.logger().warning(
                    f"⚠️  Could not check balance before placing close order: {e}. "
                    f"Proceeding with order placement..."
                )
                order_amount_to_use = target_amount

            # CRITICAL FIX: Use LIMIT orders instead of MARKET orders for better execution prices
            # Only use MARKET orders for emergency exits (stop-loss, time-limit)
            # For regular exits (early_stop, trend_exit), use LIMIT orders to avoid slippage and high fees
            use_limit_order = close_type not in [CloseType.STOP_LOSS, CloseType.TIME_LIMIT]

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
                    else:
                        # Closing SELL position = BUY order, use current price - small buffer (0.05%)
                        limit_price = current_market_price * Decimal("0.9995")  # 0.05% below market

                    # Fallback to provided price if limit_price is invalid
                    if limit_price.is_nan() or limit_price == Decimal("0"):
                        limit_price = price

                    # CRITICAL FIX: Check if LIMIT price is acceptable (within 0.1% of market)
                    # BUG FIX: Validate current_market_price is non-zero before division
                    if current_market_price and current_market_price != Decimal("0") and not current_market_price.is_nan():
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
                            order_type=OrderType.LIMIT,
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
                # Emergency exits (stop-loss, time-limit) still use MARKET orders for speed
                self.logger().info(
                    f"🚨 Placing MARKET close order (emergency): {order_amount_to_use} {base_asset} "
                    f"@ €{price:.6f} (market order - emergency exit)"
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
            self._close_order = TrackedOrder(order_id=order_id)
            self.logger().debug(f"Executor ID: {self.config.id} - Placing close order {order_id}")
        self.close_type = close_type
        self._status = RunnableStatus.SHUTTING_DOWN

    def cancel_open_orders(self):
        """
        This method is responsible for canceling the open orders.

        :return: None
        """
        open_order_placed = [level.active_open_order for level in
                             self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        close_order_placed = [level.active_close_order for level in
                              self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        for order in open_order_placed + close_order_placed:
            # TODO: Implement cancel batch orders
            if order:
                self._strategy.cancel(
                    connector_name=self.config.connector_name,
                    trading_pair=self.config.trading_pair,
                    order_id=order.order_id
                )
                self.logger().debug("Removing open order")
                self.logger().debug(f"Executor ID: {self.config.id} - Canceling open order {order.order_id}")

    def get_custom_info(self) -> Dict:
        held_position_value = sum([
            Decimal(order["executed_amount_quote"])
            for order in self._held_position_orders
        ])

        return {
            "side": self.config.side,
            "levels_by_state": {key.name: value for key, value in self.levels_by_state.items()},
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
                # For SELL grids, TAKE_PROFIT means price < start_price (price dropped below upper bound)
                # BUG FIX: Updated comment and condition to match take_profit_condition() logic
                # This is expected if price moved outside range - don't fail immediately if no position yet
                price_out_of_range = False
                if self.config.side == TradeType.BUY and self.mid_price > self.config.end_price:
                    price_out_of_range = True
                    self.logger().warning(
                        f"⚠️  Grid range exceeded (price {self.mid_price:.4f} > end {self.config.end_price:.4f}) "
                        f"- but no position yet, so continuing"
                    )
                elif self.config.side == TradeType.SELL and self.mid_price < self.config.start_price:
                    # BUG FIX: Changed from end_price to start_price to match take_profit_condition()
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

    def evaluate_max_retries(self):
        """
        This method is responsible for evaluating the maximum number of retries to place an order and stop the executor
        if the maximum number of retries is reached.

        :return: None
        """
        if self._current_retries > self._max_retries:
            self.close_type = CloseType.FAILED
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

    def process_order_failed_event(self, _, market, event: MarketOrderFailureEvent):
        """
        This method is responsible for processing the order failed event. Here we will add the InFlightOrder to the
        failed orders list.
        """
        self.update_grid_levels()
        levels_open_order_placed = [level for level in self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]
        levels_close_order_placed = [level for level in self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]
        for level in levels_open_order_placed:
            if event.order_id == level.active_open_order.order_id:
                self._failed_orders.append(level.active_open_order.order_id)
                self.max_open_creation_timestamp = 0
                level.reset_open_order()
        for level in levels_close_order_placed:
            if event.order_id == level.active_close_order.order_id:
                self._failed_orders.append(level.active_close_order.order_id)
                self.max_close_creation_timestamp = 0
                level.reset_close_order()
        if self._close_order and event.order_id == self._close_order.order_id:
            self._failed_orders.append(self._close_order.order_id)
            self._close_order = None

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

        :return: The net pnl percentage.
        """
        return self.get_net_pnl_quote() / self.filled_amount_quote if self.filled_amount_quote > 0 else Decimal("0")

    async def _sleep(self, delay: float):
        """
        This method is responsible for sleeping the executor for a specific time.

        :param delay: The time to sleep.
        :return: None
        """
        await asyncio.sleep(delay)
