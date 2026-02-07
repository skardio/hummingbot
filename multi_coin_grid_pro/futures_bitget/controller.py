"""
Futures-specific extensions for the Bitget grid controller.

Supports:
- LONG grids: Buy low, sell high (profit when price goes UP)
- SHORT grids: Sell high, buy low (profit when price goes DOWN)
- AUTO mode: Automatically choose direction based on market trend
- Exchange-side TPSL: Stop-loss orders placed on Bitget (safety net if bot crashes)
"""

from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.core.data_type.common import PositionMode, TradeType
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction, StopExecutorAction
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.futures_bitget.config_schema import (
    FuturesGridBitgetConfig,
    FuturesPositionMode,
    FuturesTradeDirection,
)
from multi_coin_grid_pro.futures_bitget.risk_guard import FuturesGridRiskGuard


class FuturesGridBitgetController(MultiCoinGridController):
    """
    Adds Bitget-perpetual specific connector management (leverage + position mode).

    Supports LONG, SHORT, and AUTO trading directions:
    - LONG: Traditional grid (buy low, sell high) - profit when price UP
    - SHORT: Inverse grid (sell high, buy low) - profit when price DOWN
    - AUTO: Chooses direction based on current market trend

    Also supports exchange-side TPSL orders for safety.
    """

    def __init__(self, *args, config: FuturesGridBitgetConfig, **kwargs):
        super().__init__(*args, config=config, **kwargs)
        self._position_mode_set = False
        self.liquidation_prices: Dict[str, Dict[str, Decimal]] = {}

        # Track active direction per coin
        self.active_directions: Dict[str, FuturesTradeDirection] = {}

        # Track exchange-side TPSL order IDs per coin
        self.exchange_tpsl_orders: Dict[str, Dict[str, str]] = {}

        # Track pending TPSL schedules to avoid duplicate scheduling
        self._pending_tpsl_symbols: set = set()

        # Risk Guard: centralized kill-switch logic
        self.risk_guard = FuturesGridRiskGuard(self)

    def _initialize_components(self):
        initialized = super()._initialize_components()
        if self.connector and not self._position_mode_set:
            self._configure_position_mode()
            # Check and place TPSL for existing positions
            self._schedule_tpsl_for_existing_positions()
        return initialized

    def _schedule_tpsl_for_existing_positions(self) -> None:
        """
        Check for existing positions and place TPSL if not already set.

        This is called at bot startup to protect positions that were opened
        before the bot started or survived a restart.
        """
        if not getattr(self.config, 'exchange_stop_loss_enabled', True):
            return

        if not self.connector:
            return

        from hummingbot.core.utils.async_utils import safe_ensure_future
        safe_ensure_future(self._place_tpsl_for_existing_positions())

    async def _place_tpsl_for_existing_positions(self) -> None:
        """
        Async function to place TPSL for existing positions.
        Waits for positions to load and retries if needed.
        """
        import asyncio

        # Wait for connector to fully initialize and load positions
        await asyncio.sleep(10)

        if not self.connector:
            return

        max_wait_attempts = 6  # Wait up to 60 seconds for positions to load

        try:
            positions = None
            for attempt in range(max_wait_attempts):
                positions = self.connector.account_positions
                if positions:
                    break
                self.logger().debug(f"⏳ Waiting for positions to load... (attempt {attempt + 1}/{max_wait_attempts})")
                await asyncio.sleep(10)

            if not positions:
                self.logger().info("ℹ️  No existing positions found at startup")
                return

            for pos_key, pos in positions.items():
                symbol = str(pos_key).split("_")[0] if "_" in str(pos_key) else str(pos_key)
                # Normalize symbol format (SOLUSDT -> SOL-USDT)
                if "-" not in symbol and "USDT" in symbol:
                    symbol = symbol.replace("USDT", "-USDT")

                position_size = abs(Decimal(str(pos.amount)))
                if position_size <= 0:
                    continue

                # Skip if TPSL already exists for this symbol
                if symbol in self.exchange_tpsl_orders:
                    self.logger().debug(f"ℹ️  TPSL already exists for {symbol}")
                    continue

                # Skip if already pending
                if symbol in self._pending_tpsl_symbols:
                    continue

                # Get entry price from position
                entry_price = Decimal(str(pos.entry_price)) if hasattr(pos, 'entry_price') and pos.entry_price else None
                if not entry_price or entry_price <= 0:
                    self.logger().warning(f"⚠️  No entry price for {symbol}, using mark price")
                    # Try to get mark price instead
                    try:
                        mid_price = self.get_mid_price(symbol)
                        if mid_price:
                            entry_price = Decimal(str(mid_price))
                    except Exception:
                        pass

                if not entry_price or entry_price <= 0:
                    self.logger().warning(f"⚠️  Cannot place TPSL for {symbol}: no price available")
                    continue

                # Determine direction from position
                is_short = pos.amount < 0
                direction = FuturesTradeDirection.SHORT if is_short else FuturesTradeDirection.LONG
                self.active_directions[symbol] = direction

                self.logger().info(
                    f"🔍 Found existing {direction.value.upper()} position: {symbol} "
                    f"size={position_size}, entry={entry_price:.4f}"
                )

                # Mark as pending
                self._pending_tpsl_symbols.add(symbol)

                try:
                    await self._place_exchange_tpsl(symbol, entry_price, position_size)
                finally:
                    self._pending_tpsl_symbols.discard(symbol)

                # Small delay between positions
                await asyncio.sleep(1)

        except Exception as e:
            self.logger().error(f"❌ Error checking existing positions: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    def _configure_position_mode(self):
        desired_mode = getattr(self.config, "position_mode", FuturesPositionMode.ONEWAY)
        if desired_mode is None:
            return

        target_mode = _convert_position_mode(desired_mode)
        connector_modes = getattr(self.connector, "supported_position_modes", lambda: [])()
        if connector_modes and target_mode not in connector_modes:
            self.logger().warning(
                f"⚠️  Desired position mode {target_mode.name} not supported by connector; "
                f"supported={connector_modes}"
            )
            self._position_mode_set = True
            return

        try:
            # IMPORTANT: Force the internal _position_mode to match config
            # This ensures orders are placed with correct tradeSide parameter
            # We do NOT call set_position_mode() because that triggers exchange API calls
            # which will fail if positions exist and potentially reset our forced value
            if hasattr(self.connector, '_perpetual_trading') and self.connector._perpetual_trading:
                self.connector._perpetual_trading._position_mode = target_mode
                self.logger().info(f"✅ Position mode FORCED to {target_mode.name} in connector (internal only).")
            elif hasattr(self.connector, '_position_mode'):
                self.connector._position_mode = target_mode
                self.logger().info(f"✅ Position mode FORCED to {target_mode.name} in connector (internal only).")
            else:
                self.logger().warning("⚠️  Could not force position mode - connector structure unknown")
        except Exception as e:
            self.logger().warning(f"⚠️  Could not force position mode: {e}")
        finally:
            self._position_mode_set = True

    # ============================================================
    # EXCHANGE-SIDE TPSL (STOP LOSS / TAKE PROFIT ON BITGET)
    # ============================================================

    async def _place_exchange_tpsl(self, symbol: str, entry_price: Decimal, position_size: Decimal) -> None:
        """
        Place stop-loss and/or take-profit orders directly on Bitget exchange.

        These act as a safety net: if the bot crashes, Bitget will still
        execute the stop-loss order and protect your capital.

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            entry_price: Estimated entry price (will try to get real from position)
            position_size: Estimated size (will use actual from position)
        """
        if not getattr(self.config, 'exchange_stop_loss_enabled', True):
            return

        if not self.connector or not hasattr(self.connector, '_api_post'):
            self.logger().warning("⚠️  Cannot place exchange TPSL: connector not ready")
            return

        # ============================================================
        # GET ACTUAL POSITION DATA FROM BITGET (INCLUDING REAL ENTRY PRICE)
        # ============================================================
        try:
            positions = self.connector.account_positions
            has_position = False
            actual_position_size = Decimal("0")
            actual_entry_price = None
            actual_side = None

            for pos_key, pos in positions.items():
                if symbol in str(pos_key):
                    actual_position_size = abs(Decimal(str(pos.amount)))
                    if actual_position_size > 0:
                        has_position = True
                        # Get REAL entry price from position
                        if hasattr(pos, 'entry_price') and pos.entry_price:
                            actual_entry_price = Decimal(str(pos.entry_price))
                        # Determine direction from position amount (negative = SHORT)
                        actual_side = "short" if pos.amount < 0 else "long"
                        break

            if not has_position:
                self.logger().debug(
                    f"ℹ️  Skipping TPSL for {symbol}: no position exists yet (size={actual_position_size})"
                )
                return

            # Use ACTUAL data from position
            position_size = actual_position_size
            if actual_entry_price and actual_entry_price > 0:
                self.logger().info(
                    f"✅ Position found for {symbol}: size={position_size}, "
                    f"REAL entry={actual_entry_price} (estimated was {entry_price})"
                )
                entry_price = actual_entry_price  # Use REAL entry price!
            else:
                self.logger().warning(
                    f"⚠️  No entry price in position for {symbol}, using estimated: {entry_price}"
                )

        except Exception as e:
            self.logger().warning(f"⚠️  Could not verify position for {symbol}: {e} - skipping TPSL")
            return

        direction = self.active_directions.get(symbol, FuturesTradeDirection.LONG)
        # Override direction based on actual position if available
        if actual_side:
            direction = FuturesTradeDirection.SHORT if actual_side == "short" else FuturesTradeDirection.LONG
            self.active_directions[symbol] = direction
        is_short = (direction == FuturesTradeDirection.SHORT)

        # Calculate SL price based on REAL entry price
        sl_pct = Decimal(str(getattr(self.config, 'exchange_stop_loss_pct', 5.0))) / 100
        if is_short:
            # SHORT: SL triggers when price goes UP
            sl_price = entry_price * (Decimal("1") + sl_pct)
            hold_side = "short"
        else:
            # LONG: SL triggers when price goes DOWN
            sl_price = entry_price * (Decimal("1") - sl_pct)
            hold_side = "long"

        # FIX: Round prices to correct precision for Bitget API (max 4-6 decimals)
        # Get price precision from trading rules or use sensible defaults
        try:
            trading_rules = self.connector.trading_rules.get(symbol)
            if trading_rules and trading_rules.min_price_increment:
                # Calculate decimals from min_price_increment
                import math
                min_price = float(trading_rules.min_price_increment)
                price_decimals = max(0, -int(math.floor(math.log10(min_price)))) if min_price > 0 else 4
            else:
                # Default: 4 decimals for most pairs, 2 for high-value pairs like BTC
                price_decimals = 2 if float(entry_price) > 100 else 4
        except Exception:
            price_decimals = 4  # Safe default

        # Round SL price to correct decimals
        sl_price = Decimal(str(round(float(sl_price), price_decimals)))

        try:
            from hummingbot.connector.derivative.bitget_perpetual import bitget_perpetual_constants as CONSTANTS

            # Determine product type
            if hasattr(self.connector, 'product_type_associated_to_trading_pair'):
                product_type = await self.connector.product_type_associated_to_trading_pair(symbol)
            else:
                product_type = CONSTANTS.USDT_PRODUCT_TYPE

            # Get exchange symbol
            if hasattr(self.connector, 'exchange_symbol_associated_to_pair'):
                exchange_symbol = await self.connector.exchange_symbol_associated_to_pair(symbol)
            else:
                exchange_symbol = symbol.replace("-", "")

            # Get margin coin
            margin_coin = symbol.split("-")[-1] if "-" in symbol else "USDT"

            # Round position size to correct precision for Bitget
            # Most perpetual contracts use 2-4 decimals
            size_decimals = 4  # Default
            try:
                trading_rules = self.connector.trading_rules.get(symbol)
                if trading_rules:
                    min_order_size = trading_rules.min_order_size
                    # Calculate decimals from min_order_size (e.g., 0.001 = 3 decimals)
                    if min_order_size and min_order_size > 0:
                        import math
                        size_decimals = max(0, -int(math.floor(math.log10(float(min_order_size)))))
                        position_size = Decimal(str(round(float(position_size), size_decimals)))
                    else:
                        position_size = Decimal(str(round(float(position_size), 4)))
                else:
                    position_size = Decimal(str(round(float(position_size), 4)))
            except Exception as e:
                self.logger().debug(f"Could not get trading rules for {symbol}: {e}")
                position_size = Decimal(str(round(float(position_size), 4)))

            # FIX: Validate position_size is positive before placing order
            if position_size <= 0:
                self.logger().warning(
                    f"⚠️  Cannot place exchange TPSL for {symbol}: position_size={position_size} <= 0"
                )
                return

            # Place STOP LOSS order
            sl_data = {
                "marginCoin": margin_coin,
                "productType": product_type,
                "symbol": exchange_symbol,
                "planType": "loss_plan",  # Stop loss
                "triggerPrice": str(sl_price),
                "triggerType": "mark_price",
                "executePrice": "0",  # Market execution
                "holdSide": hold_side,
                "size": str(position_size),
            }

            self.logger().info(
                f"🛡️  Placing exchange SL for {symbol} ({direction.value.upper()}): "
                f"trigger@{sl_price:.4f} ({sl_pct * 100:.1f}% from entry)"
            )

            sl_response = await self.connector._api_post(
                path_url=CONSTANTS.PLACE_TPSL_ORDER_ENDPOINT,
                data=sl_data,
                is_auth_required=True,
                headers={"X-CHANNEL-API-CODE": CONSTANTS.API_CODE},
            )

            if sl_response.get("code") == CONSTANTS.RET_CODE_OK:
                sl_order_id = sl_response.get("data", {}).get("orderId", "")
                self.exchange_tpsl_orders[symbol] = {"sl_order_id": sl_order_id}
                self.logger().info(
                    f"✅ Exchange SL placed for {symbol}: orderId={sl_order_id}"
                )
            else:
                self.logger().warning(
                    f"⚠️  Failed to place exchange SL for {symbol}: {sl_response}"
                )

            # Optionally place TAKE PROFIT order
            if getattr(self.config, 'exchange_take_profit_enabled', False):
                tp_pct = Decimal(str(getattr(self.config, 'exchange_take_profit_pct', 10.0))) / 100
                if is_short:
                    tp_price = entry_price * (Decimal("1") - tp_pct)
                else:
                    tp_price = entry_price * (Decimal("1") + tp_pct)

                # Round TP price to correct decimals (same as SL)
                tp_price = Decimal(str(round(float(tp_price), price_decimals)))

                tp_data = {
                    "marginCoin": margin_coin,
                    "productType": product_type,
                    "symbol": exchange_symbol,
                    "planType": "profit_plan",  # Take profit
                    "triggerPrice": str(tp_price),
                    "triggerType": "mark_price",
                    "executePrice": "0",
                    "holdSide": hold_side,
                    "size": str(position_size),
                }

                self.logger().info(
                    f"🎯 Placing exchange TP for {symbol}: trigger@{tp_price:.4f}"
                )

                tp_response = await self.connector._api_post(
                    path_url=CONSTANTS.PLACE_TPSL_ORDER_ENDPOINT,
                    data=tp_data,
                    is_auth_required=True,
                    headers={"X-CHANNEL-API-CODE": CONSTANTS.API_CODE},
                )

                if tp_response.get("code") == CONSTANTS.RET_CODE_OK:
                    tp_order_id = tp_response.get("data", {}).get("orderId", "")
                    self.exchange_tpsl_orders[symbol]["tp_order_id"] = tp_order_id
                    self.logger().info(
                        f"✅ Exchange TP placed for {symbol}: orderId={tp_order_id}"
                    )

        except Exception as e:
            self.logger().error(f"❌ Error placing exchange TPSL for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    async def _cancel_exchange_tpsl(self, symbol: str) -> None:
        """
        Cancel exchange-side TPSL orders when grid closes normally.

        This prevents the exchange from triggering SL after the grid
        has already closed successfully.

        IMPORTANT: Only cancels TPSL if the position is actually closed!
        If position still exists, we keep the TPSL as protection.
        """
        if symbol not in self.exchange_tpsl_orders:
            return

        if not self.connector or not hasattr(self.connector, '_api_post'):
            return

        # SAFETY CHECK: Only cancel TPSL if position is actually closed
        try:
            positions = self.connector.account_positions
            for pos_key, pos in positions.items():
                if symbol in str(pos_key):
                    position_size = abs(Decimal(str(pos.amount)))
                    if position_size > 0:
                        self.logger().warning(
                            f"⚠️  NOT cancelling TPSL for {symbol}: position still open ({position_size}). "
                            f"TPSL remains active as protection!"
                        )
                        return
        except Exception as e:
            self.logger().warning(f"⚠️  Could not check position for {symbol}: {e} - NOT cancelling TPSL for safety")
            return

        try:
            from hummingbot.connector.derivative.bitget_perpetual import bitget_perpetual_constants as CONSTANTS

            # Get product type and symbol
            if hasattr(self.connector, 'product_type_associated_to_trading_pair'):
                product_type = await self.connector.product_type_associated_to_trading_pair(symbol)
            else:
                product_type = CONSTANTS.USDT_PRODUCT_TYPE

            if hasattr(self.connector, 'exchange_symbol_associated_to_pair'):
                exchange_symbol = await self.connector.exchange_symbol_associated_to_pair(symbol)
            else:
                exchange_symbol = symbol.replace("-", "")

            margin_coin = symbol.split("-")[-1] if "-" in symbol else "USDT"

            orders = self.exchange_tpsl_orders.get(symbol, {})

            for order_type, order_id in orders.items():
                if order_id:
                    cancel_data = {
                        "marginCoin": margin_coin,
                        "productType": product_type,
                        "symbol": exchange_symbol,
                        "orderId": order_id,
                    }

                    response = await self.connector._api_post(
                        path_url=CONSTANTS.CANCEL_TPSL_ORDER_ENDPOINT,
                        data=cancel_data,
                        is_auth_required=True,
                    )

                    if response.get("code") == CONSTANTS.RET_CODE_OK:
                        self.logger().info(f"✅ Cancelled exchange {order_type} for {symbol}")
                    else:
                        self.logger().debug(
                            f"⚠️  Could not cancel {order_type} for {symbol}: {response}"
                        )

            # Clean up tracking
            self.exchange_tpsl_orders.pop(symbol, None)

        except Exception as e:
            self.logger().warning(f"⚠️  Error cancelling exchange TPSL for {symbol}: {e}")
            self.exchange_tpsl_orders.pop(symbol, None)

    # ============================================================
    # TRADE DIRECTION LOGIC
    # ============================================================

    def _determine_trade_direction(self, symbol: str) -> FuturesTradeDirection:
        """
        Determine trading direction for a symbol.

        Returns:
            FuturesTradeDirection.LONG: Bullish market, buy low sell high
            FuturesTradeDirection.SHORT: Bearish market, sell high buy low
        """
        config_direction = getattr(self.config, 'trade_direction', FuturesTradeDirection.AUTO)

        # If explicit direction, use it
        if config_direction != FuturesTradeDirection.AUTO:
            self.logger().info(f"📊 {symbol}: Using config direction = {config_direction.value.upper()}")
            return config_direction

        # AUTO mode: determine based on trend
        trend = self.trend_calculator.get_trend(symbol)
        if not trend:
            self.logger().warning(f"⚠️  {symbol}: No trend data, defaulting to LONG")
            return FuturesTradeDirection.LONG

        threshold = float(getattr(self.config, 'auto_direction_threshold_pct', 1.0))
        consensus = float(trend.consensus_trend_pct)

        if consensus > threshold:
            direction = FuturesTradeDirection.LONG
            self.logger().info(
                f"📈 {symbol}: AUTO → LONG (trend {consensus:+.2f}% > +{threshold}%)"
            )
        elif consensus < -threshold:
            direction = FuturesTradeDirection.SHORT
            self.logger().info(
                f"📉 {symbol}: AUTO → SHORT (trend {consensus:+.2f}% < -{threshold}%)"
            )
        else:
            # Neutral zone - don't trade
            self.logger().info(
                f"⏸️  {symbol}: AUTO → NO TRADE (trend {consensus:+.2f}% in neutral zone ±{threshold}%)"
            )
            return None  # Signal to skip this coin

        return direction

    def _create_grid_action(self, symbol: str, total_amount_quote=None):
        """
        Create grid action with correct direction (LONG or SHORT).

        For SHORT grids:
        - TradeType.SELL instead of BUY
        - Swapped start/end prices (start > end)
        - Inverted liquidation calculation
        """
        # Determine direction BEFORE creating the grid
        direction = self._determine_trade_direction(symbol)

        if direction is None:
            # Neutral zone - skip trading
            self.logger().info(f"⏸️  {symbol}: Skipping - trend in neutral zone")
            return None

        # Store active direction for this symbol
        self.active_directions[symbol] = direction

        # For SHORT: We need to override the grid creation
        if direction == FuturesTradeDirection.SHORT:
            action = self._create_short_grid_action(symbol, total_amount_quote)
        else:
            # LONG: Use standard grid creation
            action = super()._create_grid_action(symbol, total_amount_quote)

        if action is None:
            self.liquidation_prices.pop(symbol, None)
            self.active_directions.pop(symbol, None)
            return None

        self._apply_leverage(symbol)
        self._calculate_liquidation_buffer(symbol)

        # Notificeer RiskGuard: nieuwe grid gestart
        self.risk_guard.notify_grid_started(symbol)

        # Place exchange-side TPSL (safety net if bot crashes)
        self._schedule_exchange_tpsl(symbol, action)

        return action

    def _schedule_exchange_tpsl(self, symbol: str, action: CreateExecutorAction) -> None:
        """
        Schedule placing exchange-side TPSL after the grid action is created.

        IMPORTANT: We delay TPSL placement by 30 seconds to allow the position
        to be opened first. Bitget error 43023 occurs if we try to place TPSL
        before a position exists.

        NOTE: We pass estimated entry price here, but _place_exchange_tpsl will
        try to get the REAL entry price from the position once it's opened.
        """
        if not getattr(self.config, 'exchange_stop_loss_enabled', True):
            return

        # Avoid duplicate scheduling - only schedule once per symbol
        if symbol in self._pending_tpsl_symbols:
            self.logger().debug(f"ℹ️  TPSL already scheduled for {symbol} - skipping duplicate")
            return

        # Also skip if TPSL already placed for this symbol
        if symbol in self.exchange_tpsl_orders:
            self.logger().debug(f"ℹ️  TPSL already exists for {symbol} - skipping")
            return

        try:
            # Get ESTIMATED entry price from the action
            # For SHORT: start_price is near current price (entry zone)
            # For LONG: start_price is the entry zone too
            # NOTE: limit_price is the STOP-OUT level, NOT entry price!
            grid_config = action.executor_config
            entry_price = grid_config.start_price  # Use start_price, NOT limit_price
            position_size = grid_config.total_amount_quote / entry_price

            # Mark as pending
            self._pending_tpsl_symbols.add(symbol)

            # Schedule async TPSL placement WITH DELAY to allow position to open
            from hummingbot.core.utils.async_utils import safe_ensure_future
            safe_ensure_future(
                self._delayed_place_exchange_tpsl(symbol, entry_price, position_size, delay_seconds=30)
            )

        except Exception as e:
            self._pending_tpsl_symbols.discard(symbol)
            self.logger().warning(f"⚠️  Could not schedule exchange TPSL for {symbol}: {e}")

    async def _delayed_place_exchange_tpsl(
        self, symbol: str, entry_price: Decimal, position_size: Decimal, delay_seconds: int = 30
    ) -> None:
        """
        Wait for position to be opened, then place TPSL.
        Retries multiple times if position not yet filled.

        Args:
            symbol: Trading pair
            entry_price: Entry price for TPSL calculation
            position_size: Position size for TPSL
            delay_seconds: Initial seconds to wait before first attempt
        """
        import asyncio

        self.logger().info(
            f"⏳ Scheduling exchange TPSL for {symbol} in {delay_seconds}s (waiting for position to open)..."
        )

        max_retries = 10  # Try up to 10 times
        retry_interval = 30  # 30 seconds between retries

        try:
            # Initial wait
            await asyncio.sleep(delay_seconds)

            for attempt in range(max_retries):
                # Check if symbol is still active before placing TPSL
                if symbol not in self.active_directions:
                    self.logger().info(f"ℹ️  Skipping TPSL for {symbol}: no longer active")
                    return

                # Check if TPSL already exists
                if symbol in self.exchange_tpsl_orders:
                    self.logger().debug(f"ℹ️  TPSL already placed for {symbol}")
                    return

                # Try to place TPSL - it will check if position exists
                await self._place_exchange_tpsl(symbol, entry_price, position_size)

                # Check if TPSL was successfully placed
                if symbol in self.exchange_tpsl_orders:
                    return  # Success!

                # If not placed (no position yet), wait and retry
                if attempt < max_retries - 1:
                    self.logger().debug(
                        f"⏳ TPSL for {symbol}: position not ready, retry {attempt + 2}/{max_retries} in {retry_interval}s"
                    )
                    await asyncio.sleep(retry_interval)

            self.logger().warning(
                f"⚠️  Could not place TPSL for {symbol} after {max_retries} attempts - "
                "position may not have been opened or already closed"
            )
        finally:
            # Always remove from pending set
            self._pending_tpsl_symbols.discard(symbol)

    def _create_short_grid_action(self, symbol: str, total_amount_quote=None) -> Optional[CreateExecutorAction]:
        """
        Create a SHORT grid action (sell high, buy low - profit when price DOWN).

        Key differences from LONG grid:
        - TradeType.SELL instead of BUY
        - Start price > End price (inverted)
        - Profit when price decreases

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            total_amount_quote: Override for position size

        Returns:
            CreateExecutorAction with SHORT GridExecutorConfig, or None
        """
        from hummingbot.core.data_type.common import OrderType
        from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, TripleBarrierConfig

        try:
            # Get current price
            trend = self.trend_calculator.get_trend(symbol)
            if not trend or not trend.current_price:
                self.logger().warning(f"❌ {symbol}: No price data for SHORT grid")
                return None

            current_price = Decimal(str(trend.current_price))

            # Calculate grid range for SHORT
            # IMPORTANT: For grid_executor, start_price must be ABOVE mid_price for SELL side
            # to avoid "price out of range" error
            grid_range_up = Decimal(str(self.config.grid_range_pct_up)) / 100
            grid_range_down = Decimal(str(self.config.grid_range_pct_down)) / 100

            # SHORT grid:
            # - start_price = slightly above current (entry zone)
            # - end_price = take profit zone (lower)
            # - limit_price = stop loss zone (higher than entry) or None to disable
            # Grid executor requires: start_price > mid_price > end_price for SELL
            start_price = current_price * (1 + Decimal("0.001"))  # 0.1% above current - immediate entry
            end_price = current_price * (1 - grid_range_down)     # Take profit zone (lower)
            # For SHORT: limit_price should be the stop-out level (price rises too high)
            # Set it above start_price to avoid triggering limit_price_condition immediately
            # Use grid_range_up as the stop-loss level
            limit_price = current_price * (1 + grid_range_up)  # Stop loss if price rises this high

            self.logger().info(
                f"📉 {symbol} SHORT grid: current={current_price:.4f}, "
                f"entry@{start_price:.4f}, take_profit@{end_price:.4f}, stop_loss@{limit_price:.4f}"
            )

            # Use provided amount or calculate from config
            if total_amount_quote:
                trade_amount = Decimal(str(total_amount_quote))
            else:
                trade_amount = Decimal(str(self.config.total_amount_quote))

            # ============================================================
            # CRITICAL VALIDATION: Check if trade_amount meets minimum
            # ============================================================
            min_order = Decimal(str(self.config.min_order_amount_quote))
            num_levels = int(getattr(self.config, 'num_grids', 4))
            per_level_amount = trade_amount / Decimal(str(num_levels))

            if per_level_amount < min_order:
                self.logger().error(
                    f"❌ {symbol} SHORT grid REJECTED: per-level amount €{per_level_amount:.2f} "
                    f"< min_order_amount €{min_order}!\n"
                    f"   📊 Breakdown: total={trade_amount}, levels={num_levels}, "
                    f"per_level={per_level_amount:.2f}\n"
                    f"   🔧 FIX: Increase 'risk_max_balance_per_trade_pct' in config, "
                    f"or reduce 'max_simultaneous_coins' or 'num_grids'"
                )
                return None

            # Get leverage
            leverage = int(getattr(self.config, 'derivative_leverage', 1))

            # Triple barrier config for SHORT
            order_type = OrderType.LIMIT
            triple_barrier = TripleBarrierConfig(
                stop_loss=self.config.stop_loss_pct,
                take_profit=self.config.take_profit_pct,
                time_limit=None,
                trailing_stop=None,
                open_order_type=order_type,
                take_profit_order_type=order_type,
                stop_loss_order_type=OrderType.LIMIT,
                time_limit_order_type=OrderType.LIMIT
            )

            # Build grid config for SHORT
            grid_config = GridExecutorConfig(
                timestamp=self.market_data_provider.time(),
                connector_name=self.config.connector_name,
                trading_pair=symbol,
                side=TradeType.SELL,  # ← KEY DIFFERENCE: SELL for shorts!
                start_price=start_price,
                end_price=end_price,
                limit_price=limit_price,
                total_amount_quote=trade_amount,
                min_spread_between_orders=Decimal("0.001"),
                min_order_amount_quote=self.config.min_order_amount_quote,
                triple_barrier_config=triple_barrier,
                max_open_orders=max(1, min(self.config.max_open_orders, self.config.num_grids)),
                max_orders_per_batch=2,
                order_frequency=self.config.order_frequency,
                activation_bounds=self.config.take_profit_pct,
                keep_position=False,
                leverage=leverage,
                deduct_base_fees=False,
                custom_info=self._build_executor_custom_info_short()
            )

            controller_id = self.config.id or getattr(self.config, 'controller_name', 'futures_grid_bitget')

            self.logger().info(
                f"📉 Creating SHORT grid for {symbol}: "
                f"sell@{start_price:.4f} → buy@{end_price:.4f}, "
                f"size={trade_amount}, leverage={leverage}x"
            )

            return CreateExecutorAction(
                executor_config=grid_config,
                controller_id=controller_id
            )

        except Exception as e:
            self.logger().error(f"❌ Error creating SHORT grid for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return None

    def _build_executor_custom_info_short(self) -> dict:
        """
        Build custom_info for SHORT grid executors.
        Same as LONG but with direction marker.
        """
        # Build custom_info inline (matching parent class pattern)
        return {
            "no_fill_timeout_sec": getattr(self.config, 'no_fill_timeout_sec', 300),
            "no_progress_timeout_sec": getattr(self.config, 'no_progress_timeout_sec', 600),
            "max_hold_time_sec": getattr(self.config, 'max_hold_time_seconds', 3600),
            "close_grace_sec": getattr(self.config, 'close_grace_sec', 30),
            "trade_direction": "short",
        }

    def _apply_leverage(self, symbol: Optional[str]):
        leverage = getattr(self.config, "derivative_leverage", None)
        if leverage is None or symbol is None:
            return

        if hasattr(self.connector, "set_leverage"):
            try:
                buffer_pct = float(getattr(self.config, "liquidation_buffer_pct", 0.2))
                safe_leverage = max(1, int(leverage * (1 - buffer_pct)))
                if safe_leverage < leverage:
                    self.logger().info(
                        f"⚖️  Adjusting leverage from x{leverage} to x{safe_leverage} "
                        f"to preserve {buffer_pct:.0%} liquidation buffer."
                    )
                self.connector.set_leverage(symbol, safe_leverage)
                self.logger().debug(f"🎚️  Leverage set to x{safe_leverage} for {symbol}.")
            except Exception as e:
                self.logger().warning(f"⚠️  Failed to set leverage x{leverage} for {symbol}: {e}")

    def _calculate_liquidation_buffer(self, symbol: str) -> None:
        """
        Approximate liquidation distance for the active futures grid and
        track a warning threshold that triggers a defensive exit.

        Handles both LONG and SHORT positions:
        - LONG: Liquidation when price falls (price < entry)
        - SHORT: Liquidation when price rises (price > entry)
        """
        leverage = getattr(self.config, "derivative_leverage", None)
        entry_price = self.entry_prices.get(symbol)
        if leverage in (None, 0) or entry_price is None:
            self.liquidation_prices.pop(symbol, None)
            return

        entry_price_dec = Decimal(str(entry_price))
        leverage_dec = Decimal(str(leverage))
        if leverage_dec <= 1:
            self.liquidation_prices.pop(symbol, None)
            return

        # Determine direction
        direction = self.active_directions.get(symbol, FuturesTradeDirection.LONG)
        is_short = (direction == FuturesTradeDirection.SHORT)

        buffer_pct = Decimal(str(getattr(self.config, "liquidation_buffer_pct", 0.2)))
        safety_distance = Decimal(str(self.config.liquidation_safety_distance_pct))

        if is_short:
            # SHORT: Liquidation occurs when price goes UP
            # At 10x leverage: +10% price move = liquidation
            baseline_liq = entry_price_dec * (Decimal("1") + (Decimal("1") / leverage_dec))
            buffer_price = entry_price_dec * (Decimal("1") + buffer_pct)
            # Warning price is between entry and liquidation
            safe_exit_price = entry_price_dec + (baseline_liq - entry_price_dec) * safety_distance
            warning_price = min(buffer_price, safe_exit_price)

            self.logger().info(
                f"🛡️  {symbol} SHORT liquidation guard: "
                f"entry={entry_price_dec:.4f}, "
                f"liquidation≈{baseline_liq:.4f} (price UP), "
                f"warning_exit={warning_price:.4f}"
            )
        else:
            # LONG: Liquidation occurs when price goes DOWN
            baseline_liq = entry_price_dec * (Decimal("1") - (Decimal("1") / leverage_dec))
            baseline_liq = max(baseline_liq, Decimal("0"))
            buffer_price = entry_price_dec * (Decimal("1") - buffer_pct)
            safe_exit_price = entry_price_dec - (entry_price_dec - baseline_liq) * safety_distance
            warning_price = max(buffer_price, safe_exit_price)

            self.logger().info(
                f"🛡️  {symbol} LONG liquidation guard: "
                f"entry={entry_price_dec:.4f}, "
                f"liquidation≈{baseline_liq:.4f} (price DOWN), "
                f"warning_exit={warning_price:.4f}"
            )

        self.liquidation_prices[symbol] = {
            "entry": entry_price_dec,
            "liquidation": baseline_liq,
            "warning": warning_price,
            "direction": direction.value,  # Store direction for monitoring
        }

    def _monitor_liquidation_risk(self) -> Optional[StopExecutorAction]:
        """
        Monitor liquidation risk for active position.

        Handles both LONG and SHORT:
        - LONG: Stop if price <= warning (price falling toward liquidation)
        - SHORT: Stop if price >= warning (price rising toward liquidation)
        """
        if not self.active_coin or self.active_coin not in self.liquidation_prices:
            return None

        buffer = self.liquidation_prices[self.active_coin]
        trend = self.trend_calculator.get_trend(self.active_coin)
        if not trend or not trend.current_price:
            return None

        current_price = Decimal(str(trend.current_price))
        warning_price = buffer["warning"]
        liquidation_price = buffer["liquidation"]
        direction = buffer.get("direction", "long")

        # Check based on direction
        is_danger = False
        if direction == "short":
            # SHORT: Danger when price goes UP toward warning/liquidation
            is_danger = current_price >= warning_price
        else:
            # LONG: Danger when price goes DOWN toward warning/liquidation
            is_danger = current_price <= warning_price

        if is_danger:
            self.logger().critical(
                f"🚨 {self.active_coin} ({direction.upper()}) at {current_price:.4f} "
                f"breached liquidation buffer ({warning_price:.4f}); "
                f"liquidation≈{liquidation_price:.4f}. Initiating emergency stop."
            )
            self.liquidation_prices.pop(self.active_coin, None)
            self.active_directions.pop(self.active_coin, None)
            self._schedule_cancel_exchange_tpsl(self.active_coin)
            return self._create_stop_action()

        return None

    def determine_executor_actions(self) -> List[ExecutorAction]:
        # PRIORITEIT 1: RiskGuard check (meest kritisch)
        # Only evaluate if there's actually an active executor for the coin
        if self.active_coin and self._is_executor_actually_active():
            risk_stop = self.risk_guard.evaluate(self.active_coin)
            if risk_stop:
                # Cleanup liquidation tracking and cancel exchange TPSL
                self.liquidation_prices.pop(self.active_coin, None)
                self.risk_guard.notify_grid_stopped(self.active_coin)
                self._schedule_cancel_exchange_tpsl(self.active_coin)
                return [risk_stop]

        # PRIORITEIT 2: Liquidation risk monitoring
        liquidation_action = self._monitor_liquidation_risk()
        if liquidation_action:
            if self.active_coin:
                self.risk_guard.notify_grid_stopped(self.active_coin)
                self._schedule_cancel_exchange_tpsl(self.active_coin)
            return [liquidation_action]

        # PRIORITEIT 3: Normale grid logic
        return super().determine_executor_actions()

    def _schedule_cancel_exchange_tpsl(self, symbol: str) -> None:
        """Schedule cancellation of exchange-side TPSL orders."""
        if symbol not in self.exchange_tpsl_orders:
            return

        try:
            from hummingbot.core.utils.async_utils import safe_ensure_future
            safe_ensure_future(self._cancel_exchange_tpsl(symbol))
        except Exception as e:
            self.logger().warning(f"⚠️  Could not schedule TPSL cancel for {symbol}: {e}")

    def should_exit_position(self, coin: str) -> Optional[str]:
        """
        Tighten emergency and hard-stop thresholds for leveraged futures positions.
        """
        original_emergency = getattr(self.config, "emergency_exit_pct", -2.0)
        original_hard = getattr(self.config, "hard_stop_pct", -3.0)
        futures_emergency = getattr(self.config, "futures_emergency_exit_pct", -1.5)
        futures_hard = getattr(self.config, "futures_hard_stop_pct", -2.5)

        setattr(self.config, "emergency_exit_pct", futures_emergency)
        setattr(self.config, "hard_stop_pct", futures_hard)
        try:
            return super().should_exit_position(coin)
        finally:
            setattr(self.config, "emergency_exit_pct", original_emergency)
            setattr(self.config, "hard_stop_pct", original_hard)

    def _check_multi_timeframe_buy_conditions(self, coin: str) -> bool:
        """
        Tightened futures entry gating aligned with liquidation-aware risk rules.

        Supports both LONG and SHORT directions:
        - LONG: Requires positive trends (24h > +1.5%, 4h > +1.0%, 1h >= 0%)
        - SHORT: Requires negative trends (24h < -1.5%, 4h < -1.0%, 1h <= 0%)
        - AUTO: Accepts either strong positive OR strong negative trends

        Also supports warm-up mode with relaxed thresholds.
        """
        try:
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return False

            staleness_threshold = getattr(self.config, "price_update_interval", 30) * 4
            data_age = self.market_data_provider.time() - trend.last_updated
            if data_age > staleness_threshold:
                self.logger().debug(
                    f"⚠️  Futures entry rejected for {coin}: trend data stale "
                    f"({data_age:.1f}s > {staleness_threshold}s)"
                )
                return False

            if not hasattr(trend, "trend_60m") or not hasattr(trend, "trend_240m"):
                self.logger().warning(
                    f"⚠️  Futures entry rejected for {coin}: multi-timeframe fields missing"
                )
                return False

            # Get trend values
            trend_24h = float(getattr(trend, 'trend_1440m', 0.0))
            trend_4h = float(trend.trend_240m)
            trend_1h = float(trend.trend_60m)

            # Determine configured direction
            config_direction = getattr(self.config, 'trade_direction', FuturesTradeDirection.AUTO)

            # ===== WARM-UP MODE (24h data not yet complete) =====
            if getattr(trend, "long_trend_warmup", False):
                warmup_4h_min = float(getattr(self.config, 'warmup_min_4h_trend_pct', 1.0))
                warmup_1h_min = float(getattr(self.config, 'warmup_min_1h_trend_pct', 0.5))

                # For LONG/AUTO: check positive warmup thresholds
                if config_direction in (FuturesTradeDirection.LONG, FuturesTradeDirection.AUTO):
                    if trend_4h > warmup_4h_min and trend_1h >= warmup_1h_min:
                        self.logger().info(
                            f"[FUTURES] ✅ {coin} warm-up entry allowed: "
                            f"4h={trend_4h:+.2f}% (>{warmup_4h_min:+.2f}), "
                            f"1h={trend_1h:+.2f}% (≥{warmup_1h_min:+.2f})"
                        )
                        return True

                # For SHORT/AUTO: check negative warmup thresholds
                if config_direction in (FuturesTradeDirection.SHORT, FuturesTradeDirection.AUTO):
                    if trend_4h < -warmup_4h_min and trend_1h <= -warmup_1h_min:
                        self.logger().info(
                            f"[FUTURES] ✅ {coin} SHORT warm-up entry allowed: "
                            f"4h={trend_4h:+.2f}% (<{-warmup_4h_min:+.2f}), "
                            f"1h={trend_1h:+.2f}% (≤{-warmup_1h_min:+.2f})"
                        )
                        return True

                self.logger().info(
                    f"[FUTURES] ❌ {coin} warm-up entry blocked: "
                    f"4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%"
                )
                return False

            # ===== NORMAL MODE (24h data available) =====
            min_24h = float(self.config.futures_min_entry_strength_24h)
            min_4h = float(self.config.futures_min_entry_strength_4h)
            min_1h = float(self.config.futures_min_entry_strength_1h)

            # Check LONG conditions (positive trends)
            long_24h_ok = trend_24h > min_24h
            long_4h_ok = trend_4h > min_4h
            long_1h_ok = trend_1h >= min_1h
            long_ok = long_24h_ok and long_4h_ok and long_1h_ok

            # Check SHORT conditions (negative trends - inverted thresholds)
            short_24h_ok = trend_24h < -min_24h
            short_4h_ok = trend_4h < -min_4h
            short_1h_ok = trend_1h <= -min_1h
            short_ok = short_24h_ok and short_4h_ok and short_1h_ok

            # Decision based on direction mode
            if config_direction == FuturesTradeDirection.LONG:
                if long_ok:
                    self.logger().info(
                        f"[FUTURES] ✅ {coin} LONG entry: "
                        f"24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%"
                    )
                    return True
                else:
                    self.logger().info(
                        f"[FUTURES] ❌ {coin} LONG blocked: trends not bullish enough "
                        f"(24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%)"
                    )
                    return False

            elif config_direction == FuturesTradeDirection.SHORT:
                if short_ok:
                    self.logger().info(
                        f"[FUTURES] ✅ {coin} SHORT entry: "
                        f"24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%"
                    )
                    return True
                else:
                    self.logger().info(
                        f"[FUTURES] ❌ {coin} SHORT blocked: trends not bearish enough "
                        f"(24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%)"
                    )
                    return False

            else:  # AUTO mode
                if long_ok:
                    self.logger().info(
                        f"[FUTURES] ✅ {coin} AUTO→LONG: strong bullish "
                        f"(24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%)"
                    )
                    return True
                elif short_ok:
                    self.logger().info(
                        f"[FUTURES] ✅ {coin} AUTO→SHORT: strong bearish "
                        f"(24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%)"
                    )
                    return True
                else:
                    self.logger().info(
                        f"[FUTURES] ❌ {coin} AUTO blocked: no clear trend "
                        f"(24h={trend_24h:+.2f}%, 4h={trend_4h:+.2f}%, 1h={trend_1h:+.2f}%)"
                    )
                    return False

        except Exception as e:
            self.logger().error(f"❌ Error checking multi-timeframe conditions for {coin}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return False

    def stop(self):
        """
        Cleanup on controller shutdown.

        Cancels any exchange-side TPSL orders that are still active,
        then calls parent stop.
        """
        # Cancel all active exchange TPSL orders
        for symbol in list(self.exchange_tpsl_orders.keys()):
            self._schedule_cancel_exchange_tpsl(symbol)

        # Call parent cleanup
        super().stop()


def _convert_position_mode(mode: FuturesPositionMode) -> PositionMode:
    if isinstance(mode, FuturesPositionMode):
        return PositionMode[mode.name]
    if isinstance(mode, PositionMode):
        return mode
    return PositionMode[str(mode).upper()]
