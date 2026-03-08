"""
Futures-specific extensions for the Bitget grid controller.

Supports:
- LONG grids: Buy low, sell high (profit when price goes UP)
- SHORT grids: Sell high, buy low (profit when price goes DOWN)
- AUTO mode: Automatically choose direction based on market trend
- Exchange-side TPSL: Stop-loss orders placed on Bitget (safety net if bot crashes)
- Funding rate filter: Skip trades where you pay high funding (direction-aware)
- Correlation filter: Limit exposure to correlated assets
- Trailing stop: Lock profits when grid is winning
"""

import time
from decimal import Decimal
from typing import Dict, List, Optional, Set

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

        # ============================================================
        # SPRINT 2: Funding Rate Filter
        # ============================================================
        self._funding_rate_cache: Dict[str, Dict] = {}  # {symbol: {rate: float, timestamp: float}}

        # ============================================================
        # SPRINT 2: Correlation Filter
        # ============================================================
        self._active_correlation_groups: Set[str] = set()  # Track which groups have active positions

        # ============================================================
        # SPRINT 3: Trailing Stop
        # ============================================================
        self._trailing_stop_high_water_marks: Dict[str, Decimal] = {}  # {symbol: highest_pnl_pct}
        self._trailing_stop_activated: Dict[str, bool] = {}  # {symbol: is_activated}

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
                # Handle HEDGE mode position keys like "OP-USDTLONG" or "OP-USDTSHORT"
                symbol = str(pos_key)

                # Remove LONG/SHORT suffix from HEDGE mode position keys
                if symbol.endswith("LONG"):
                    symbol = symbol[:-4]  # Remove "LONG"
                elif symbol.endswith("SHORT"):
                    symbol = symbol[:-5]  # Remove "SHORT"

                # Also handle underscore format like "OPUSDT_LONG"
                if "_" in symbol:
                    symbol = symbol.split("_")[0]

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
            self.logger().warning(f"⚠️  {symbol}: No trend data, skipping (no blind trades)")
            return None  # Don't trade without trend data

        threshold = float(getattr(self.config, 'auto_direction_threshold_pct', 0.5))
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

    # ============================================================
    # PORTFOLIO EXPOSURE CAPS (Sprint 1 Risk Management)
    # ============================================================

    def _check_portfolio_exposure_caps(self, symbol: str, requested_notional: Decimal) -> tuple[bool, str]:
        """
        Three-layer portfolio exposure check before opening new grid.

        Layer 1: max_open_positions - limits concurrent grids
        Layer 2: max_total_risk_pct - limits total risk exposure
        Layer 3: max_notional_exposure_pct - limits leverage-aware notional

        Returns:
            (can_open, reason) - True if allowed, False with reason if blocked
        """
        # Count current open positions (active grids)
        active_count = len([e for e in self.executors_info if e.is_active])

        # Layer 1: Position count cap
        max_positions = int(getattr(self.config, 'max_open_positions', 4))
        if active_count >= max_positions:
            return False, f"MAX_POSITIONS: {active_count}/{max_positions} grids open"

        # Get reference balance for calculations
        ref_balance = Decimal(str(getattr(self.config, 'risk_reference_balance_quote', 1000)))

        # Layer 2: Total risk percentage cap
        max_total_risk_pct = Decimal(str(getattr(self.config, 'max_total_risk_pct', 8.0)))
        per_trade_risk_pct = Decimal(str(getattr(self.config, 'risk_max_balance_per_trade_pct', 2.0)))

        # Calculate current total risk (active positions × per-trade risk)
        current_total_risk_pct = Decimal(str(active_count)) * per_trade_risk_pct
        projected_risk_pct = current_total_risk_pct + per_trade_risk_pct

        if projected_risk_pct > max_total_risk_pct:
            return False, (
                f"MAX_TOTAL_RISK: {projected_risk_pct:.1f}% > {max_total_risk_pct:.1f}% "
                f"(current={current_total_risk_pct:.1f}%, adding={per_trade_risk_pct:.1f}%)"
            )

        # Layer 3: Notional exposure cap (leverage-aware)
        max_notional_pct = Decimal(str(getattr(self.config, 'max_notional_exposure_pct', 150.0)))
        max_notional = ref_balance * max_notional_pct / Decimal("100")

        # Calculate current notional from active positions
        current_notional = self._calculate_current_notional()
        leverage = Decimal(str(getattr(self.config, 'derivative_leverage', 5)))
        projected_notional = current_notional + (requested_notional * leverage)

        if projected_notional > max_notional:
            return False, (
                f"MAX_NOTIONAL: {projected_notional:.0f} > {max_notional:.0f} USDT "
                f"(current={current_notional:.0f}, adding={requested_notional * leverage:.0f})"
            )

        # All checks passed
        self.logger().debug(
            f"✅ Portfolio caps OK for {symbol}: "
            f"positions={active_count + 1}/{max_positions}, "
            f"risk={projected_risk_pct:.1f}/{max_total_risk_pct:.1f}%, "
            f"notional={projected_notional:.0f}/{max_notional:.0f}"
        )
        return True, ""

    def _calculate_current_notional(self) -> Decimal:
        """
        Calculate current total notional exposure from open positions.

        Returns:
            Total notional in quote currency (USDT)
        """
        total_notional = Decimal("0")

        try:
            # Get positions from connector
            if self.connector and hasattr(self.connector, 'account_positions'):
                positions = self.connector.account_positions
                for pos_key, pos in positions.items():
                    position_size = abs(Decimal(str(pos.amount)))
                    if position_size > 0:
                        # Get position value
                        entry_price = Decimal(str(pos.entry_price)) if hasattr(pos, 'entry_price') and pos.entry_price else Decimal("0")
                        if entry_price > 0:
                            notional = position_size * entry_price
                            total_notional += notional
        except Exception as e:
            self.logger().debug(f"Could not calculate notional from positions: {e}")
            # Fallback: estimate from active executors
            for executor in self.executors_info:
                if executor.is_active:
                    exec_config = getattr(executor, 'config', None)
                    if exec_config and hasattr(exec_config, 'total_amount_quote'):
                        leverage = Decimal(str(getattr(self.config, 'derivative_leverage', 5)))
                        total_notional += Decimal(str(exec_config.total_amount_quote)) * leverage

        return total_notional

    # ============================================================
    # SPRINT 2: FUNDING RATE FILTER (Direction-Aware)
    # ============================================================

    async def _fetch_funding_rate(self, symbol: str) -> Optional[float]:
        """
        Fetch current funding rate from Bitget API.

        Returns:
            Funding rate as percentage (e.g., 0.01 = 0.01%), or None if failed
        """
        try:
            if not self.connector or not hasattr(self.connector, '_api_get'):
                return None

            from hummingbot.connector.derivative.bitget_perpetual import bitget_perpetual_constants as CONSTANTS

            # Get exchange symbol format
            if hasattr(self.connector, 'exchange_symbol_associated_to_pair'):
                exchange_symbol = await self.connector.exchange_symbol_associated_to_pair(symbol)
            else:
                exchange_symbol = symbol.replace("-", "")

            # Get product type
            if hasattr(self.connector, 'product_type_associated_to_trading_pair'):
                product_type = await self.connector.product_type_associated_to_trading_pair(symbol)
            else:
                product_type = CONSTANTS.USDT_PRODUCT_TYPE

            # Fetch funding rate
            response = await self.connector._api_get(
                path_url="/api/v2/mix/market/current-fund-rate",
                params={"symbol": exchange_symbol, "productType": product_type},
            )

            if response.get("code") == "00000":
                data = response.get("data", [])
                if data:
                    # Rate is returned as string like "0.0001" (0.01%)
                    rate_str = data[0].get("fundingRate", "0")
                    rate = float(rate_str) * 100  # Convert to percentage
                    return rate
            return None

        except Exception as e:
            self.logger().debug(f"Could not fetch funding rate for {symbol}: {e}")
            return None

    def _get_cached_funding_rate(self, symbol: str) -> Optional[float]:
        """
        Get funding rate from cache, or return None if expired/missing.
        """
        cache_entry = self._funding_rate_cache.get(symbol)
        if not cache_entry:
            return None

        cache_seconds = int(getattr(self.config, 'funding_rate_cache_seconds', 300))
        current_time = self.market_data_provider.time() if self.market_data_provider else time.time()
        if current_time - cache_entry['timestamp'] > cache_seconds:
            return None  # Cache expired

        return cache_entry['rate']

    def _update_funding_rate_cache(self, symbol: str, rate: float) -> None:
        """Update the funding rate cache for a symbol."""
        current_time = self.market_data_provider.time() if self.market_data_provider else time.time()
        self._funding_rate_cache[symbol] = {
            'rate': rate,
            'timestamp': current_time
        }

    def _check_funding_rate_filter(self, symbol: str, direction: FuturesTradeDirection) -> tuple[bool, str]:
        """
        Check if funding rate is acceptable for the given direction.

        Direction-aware logic:
        - Positive funding rate: LONGS pay, SHORTS receive
        - Negative funding rate: SHORTS pay, LONGS receive

        Returns:
            (can_trade, reason) - True if OK to trade, False with reason if blocked
        """
        if not getattr(self.config, 'funding_rate_filter_enabled', False):
            return True, ""

        # Try to get cached rate first
        funding_rate = self._get_cached_funding_rate(symbol)

        if funding_rate is None:
            # No cached rate - we'll fetch async but allow trade for now
            # Schedule async fetch for next time
            try:
                from hummingbot.core.utils.async_utils import safe_ensure_future
                safe_ensure_future(self._async_update_funding_rate(symbol))
            except Exception:
                pass
            return True, ""  # Allow trade when no data (conservative)

        max_cost = float(getattr(self.config, 'max_funding_cost_pct', 0.03))

        # Calculate YOUR cost based on direction
        if direction == FuturesTradeDirection.LONG:
            # Positive funding = LONGS pay
            your_cost = funding_rate if funding_rate > 0 else 0
        else:  # SHORT
            # Negative funding = SHORTS pay (positive funding = shorts receive)
            your_cost = -funding_rate if funding_rate < 0 else 0

        if your_cost > max_cost:
            return False, (
                f"FUNDING_RATE: {direction.value.upper()} would pay {your_cost:.4f}% > max {max_cost:.4f}% "
                f"(rate={funding_rate:+.4f}%)"
            )

        # Log if we're receiving funding (bonus!)
        if your_cost < 0:
            self.logger().info(
                f"💰 {symbol} {direction.value.upper()} BONUS: receiving {abs(your_cost):.4f}% funding "
                f"(rate={funding_rate:+.4f}%)"
            )

        return True, ""

    async def _async_update_funding_rate(self, symbol: str) -> None:
        """Async helper to update funding rate cache."""
        try:
            rate = await self._fetch_funding_rate(symbol)
            if rate is not None:
                self._update_funding_rate_cache(symbol, rate)
        except Exception as e:
            self.logger().debug(f"Failed to update funding rate for {symbol}: {e}")

    # ============================================================
    # SPRINT 2: CORRELATION FILTER
    # ============================================================

    def _get_correlation_group(self, symbol: str) -> Optional[str]:
        """
        Get the correlation group for a symbol.

        Returns:
            Group name (e.g., 'major_caps') or None if not in any group
        """
        correlation_groups = getattr(self.config, 'correlation_groups', {})
        if not correlation_groups:
            return None

        for group_name, symbols in correlation_groups.items():
            if symbol in symbols:
                return group_name

        return None

    def _check_correlation_filter(self, symbol: str) -> tuple[bool, str]:
        """
        Check if we can open a position for this symbol based on correlation groups.

        Prevents opening multiple positions in highly correlated assets.

        Returns:
            (can_trade, reason) - True if OK to trade, False with reason if blocked
        """
        if not getattr(self.config, 'correlation_filter_enabled', False):
            return True, ""

        group = self._get_correlation_group(symbol)
        if not group:
            # Symbol not in any correlation group - allow
            return True, ""

        max_per_group = int(getattr(self.config, 'max_correlated_positions', 1))

        # Count active positions in this correlation group
        active_in_group = 0
        correlation_groups = getattr(self.config, 'correlation_groups', {})
        group_symbols = correlation_groups.get(group, [])

        for executor in self.executors_info:
            if executor.is_active:
                exec_symbol = getattr(executor.config, 'trading_pair', '') if executor.config else ''
                if exec_symbol in group_symbols:
                    active_in_group += 1

        if active_in_group >= max_per_group:
            # Find which symbols are active in this group for logging
            active_symbols = []
            for executor in self.executors_info:
                if executor.is_active:
                    exec_symbol = getattr(executor.config, 'trading_pair', '') if executor.config else ''
                    if exec_symbol in group_symbols:
                        active_symbols.append(exec_symbol)

            return False, (
                f"CORRELATION: group '{group}' has {active_in_group}/{max_per_group} positions "
                f"(active: {active_symbols})"
            )

        return True, ""

    def _update_correlation_tracking(self, symbol: str, is_opening: bool) -> None:
        """Update correlation group tracking when position opens/closes."""
        group = self._get_correlation_group(symbol)
        if group:
            if is_opening:
                self._active_correlation_groups.add(group)
            # Note: We don't remove from set on close because there might be other positions in group

    # ============================================================
    # SPRINT 3: TRAILING STOP (Profit Lock)
    # ============================================================

    def _check_trailing_stop(self, symbol: str) -> Optional[StopExecutorAction]:
        """
        Check if trailing stop should trigger for a symbol.

        Trailing stop logic:
        1. Activates when unrealized PnL exceeds activation threshold
        2. Tracks highest PnL (high water mark)
        3. Triggers stop when PnL drops by distance threshold from high water mark

        Returns:
            StopExecutorAction if trailing stop triggered, None otherwise
        """
        if not getattr(self.config, 'trailing_stop_enabled', False):
            return None

        # Get current unrealized PnL for the symbol
        current_pnl_pct = self._get_position_pnl_pct(symbol)
        if current_pnl_pct is None:
            return None

        activation_pct = Decimal(str(getattr(self.config, 'trailing_stop_activation_pct', 2.0)))
        distance_pct = Decimal(str(getattr(self.config, 'trailing_stop_distance_pct', 1.0)))

        # Check if trailing stop is activated
        is_activated = self._trailing_stop_activated.get(symbol, False)
        high_water_mark = self._trailing_stop_high_water_marks.get(symbol, Decimal("0"))

        if not is_activated:
            # Check if we should activate
            if current_pnl_pct >= activation_pct:
                self._trailing_stop_activated[symbol] = True
                self._trailing_stop_high_water_marks[symbol] = current_pnl_pct
                self.logger().info(
                    f"🎯 {symbol} TRAILING STOP ACTIVATED: PnL {current_pnl_pct:.2f}% >= {activation_pct:.2f}%"
                )
            return None

        # Trailing stop is activated - update high water mark if new high
        if current_pnl_pct > high_water_mark:
            self._trailing_stop_high_water_marks[symbol] = current_pnl_pct
            high_water_mark = current_pnl_pct
            self.logger().debug(
                f"📈 {symbol} new high water mark: {high_water_mark:.2f}%"
            )

        # Check if we should trigger (dropped too far from high water mark)
        distance_from_high = high_water_mark - current_pnl_pct

        if distance_from_high >= distance_pct:
            self.logger().warning(
                f"🛑 {symbol} TRAILING STOP TRIGGERED: "
                f"PnL dropped {distance_from_high:.2f}% from high ({high_water_mark:.2f}% → {current_pnl_pct:.2f}%)"
            )
            # Clean up tracking
            self._trailing_stop_activated.pop(symbol, None)
            self._trailing_stop_high_water_marks.pop(symbol, None)
            return self._create_stop_action_for_symbol(symbol, "TRAILING_STOP")

        return None

    def _get_position_pnl_pct(self, symbol: str) -> Optional[Decimal]:
        """
        Get current unrealized PnL percentage for a position.

        Returns:
            PnL as percentage (e.g., 2.5 = +2.5%), or None if no position
        """
        try:
            if not self.connector or not hasattr(self.connector, 'account_positions'):
                return None

            positions = self.connector.account_positions
            for pos_key, pos in positions.items():
                if symbol in str(pos_key):
                    position_size = abs(Decimal(str(pos.amount)))
                    if position_size > 0:
                        # Get unrealized PnL
                        unrealized_pnl = Decimal(str(getattr(pos, 'unrealized_pnl', 0)))
                        entry_price = Decimal(str(getattr(pos, 'entry_price', 0)))

                        if entry_price > 0:
                            # Calculate PnL percentage
                            position_value = position_size * entry_price
                            if position_value > 0:
                                pnl_pct = (unrealized_pnl / position_value) * Decimal("100")
                                return pnl_pct
            return None

        except Exception as e:
            self.logger().debug(f"Could not get PnL for {symbol}: {e}")
            return None

    def _create_stop_action_for_symbol(self, symbol: str, reason: str) -> Optional[StopExecutorAction]:
        """
        Create a stop action for a specific symbol's executor.

        Returns:
            StopExecutorAction or None if no active executor found
        """
        for executor in self.executors_info:
            if executor.is_active:
                exec_symbol = getattr(executor.config, 'trading_pair', '') if executor.config else ''
                if exec_symbol == symbol:
                    self.logger().info(f"🛑 Creating stop action for {symbol}: {reason}")
                    return StopExecutorAction(
                        controller_id=self.config.id,
                        executor_id=executor.id
                    )
        return None

    def _reset_trailing_stop(self, symbol: str) -> None:
        """Reset trailing stop tracking for a symbol (called when grid closes)."""
        self._trailing_stop_activated.pop(symbol, None)
        self._trailing_stop_high_water_marks.pop(symbol, None)

    # ============================================================
    # SPRINT 3: DYNAMIC TIMEOUT
    # ============================================================

    def _get_dynamic_timeout(self, symbol: str) -> int:
        """
        Calculate dynamic grid timeout based on volatility.

        Low volatility → longer timeout (market needs more time)
        High volatility → shorter timeout (quick moves expected)

        Returns:
            Timeout in seconds
        """
        if not getattr(self.config, 'dynamic_timeout_enabled', False):
            return int(getattr(self.config, 'risk_guard_max_grid_time_seconds', 3600))

        base_timeout = int(getattr(self.config, 'base_grid_timeout_seconds', 3600))
        low_vol_multiplier = float(getattr(self.config, 'low_volatility_multiplier', 2.0))
        high_vol_multiplier = float(getattr(self.config, 'high_volatility_multiplier', 0.5))
        vol_threshold_low = float(getattr(self.config, 'volatility_threshold_low', 0.5))
        vol_threshold_high = float(getattr(self.config, 'volatility_threshold_high', 2.0))

        # Get current ATR/volatility
        try:
            trend = self.trend_calculator.get_trend(symbol)
            if trend and hasattr(trend, 'atr_pct') and trend.atr_pct:
                atr_pct = float(trend.atr_pct)

                if atr_pct < vol_threshold_low:
                    # Low volatility - extend timeout
                    timeout = int(base_timeout * low_vol_multiplier)
                    self.logger().debug(
                        f"📊 {symbol} low volatility ({atr_pct:.2f}% < {vol_threshold_low}%), "
                        f"timeout extended to {timeout}s"
                    )
                elif atr_pct > vol_threshold_high:
                    # High volatility - shorten timeout
                    timeout = int(base_timeout * high_vol_multiplier)
                    self.logger().debug(
                        f"📊 {symbol} high volatility ({atr_pct:.2f}% > {vol_threshold_high}%), "
                        f"timeout shortened to {timeout}s"
                    )
                else:
                    # Normal volatility - use base timeout
                    timeout = base_timeout

                return timeout

        except Exception as e:
            self.logger().debug(f"Could not calculate dynamic timeout for {symbol}: {e}")

        return base_timeout

    def _create_grid_action(self, symbol: str, total_amount_quote=None):
        """
        Create grid action with correct direction (LONG or SHORT).

        Includes all risk filters (Sprint 1-3):
        - Portfolio exposure caps (Sprint 1)
        - Funding rate filter (Sprint 2)
        - Correlation filter (Sprint 2)

        For SHORT grids:
        - TradeType.SELL instead of BUY
        - Swapped start/end prices (start > end)
        - Inverted liquidation calculation
        """
        # ============================================================
        # SPRINT 1: Portfolio Exposure Cap Check
        # ============================================================
        # Calculate requested notional for this trade
        if total_amount_quote:
            requested_notional = Decimal(str(total_amount_quote))
        else:
            # Calculate from config
            ref_balance = Decimal(str(getattr(self.config, 'risk_reference_balance_quote', 1000)))
            risk_pct = Decimal(str(getattr(self.config, 'risk_max_balance_per_trade_pct', 2.0)))
            requested_notional = ref_balance * risk_pct / Decimal("100")
            total_amount_quote = requested_notional  # Set for downstream use

        # ============================================================
        # DYNAMIC MARGIN CHECK: Adjust capital to available balance
        # ============================================================
        try:
            available_balance = Decimal(str(self.connector.get_available_balance("USDT")))
            leverage = Decimal(str(getattr(self.config, 'derivative_leverage', 3)))
            min_order_quote = Decimal(str(getattr(self.config, 'min_order_amount_quote', 5)))

            # Max notional we can open with available margin
            max_notional = available_balance * leverage

            if max_notional < min_order_quote:
                self.logger().warning(
                    f"⏸️  {symbol}: Insufficient margin ({available_balance:.2f} USDT available, "
                    f"need {min_order_quote / leverage:.2f} USDT for min order). Waiting..."
                )
                return None

            if requested_notional > max_notional:
                old_notional = requested_notional
                requested_notional = max_notional * Decimal("0.95")  # 5% buffer
                total_amount_quote = requested_notional
                self.logger().info(
                    f"💰 {symbol}: Adjusted capital {old_notional:.2f} → {requested_notional:.2f} USDT "
                    f"(available margin: {available_balance:.2f} USDT × {leverage}x leverage)"
                )
        except Exception as e:
            self.logger().debug(f"Could not check available margin for {symbol}: {e}")

        can_open, reason = self._check_portfolio_exposure_caps(symbol, requested_notional)
        if not can_open:
            self.logger().warning(
                f"🛑 PORTFOLIO CAP BLOCKED {symbol}: {reason}"
            )
            return None

        # ============================================================
        # SPRINT 2: Correlation Filter Check
        # ============================================================
        can_trade, corr_reason = self._check_correlation_filter(symbol)
        if not can_trade:
            self.logger().warning(
                f"🛑 CORRELATION BLOCKED {symbol}: {corr_reason}"
            )
            return None

        # Determine direction BEFORE creating the grid
        direction = self._determine_trade_direction(symbol)

        if direction is None:
            # Neutral zone - skip trading
            self.logger().info(f"⏸️  {symbol}: Skipping - trend in neutral zone")
            return None

        # ============================================================
        # SPRINT 2: Funding Rate Filter Check (direction-aware)
        # ============================================================
        can_trade, funding_reason = self._check_funding_rate_filter(symbol, direction)
        if not can_trade:
            self.logger().warning(
                f"🛑 FUNDING RATE BLOCKED {symbol}: {funding_reason}"
            )
            return None

        # Store active direction for this symbol
        self.active_directions[symbol] = direction

        # Update correlation tracking
        self._update_correlation_tracking(symbol, is_opening=True)

        # For SHORT: We need to override the grid creation
        if direction == FuturesTradeDirection.SHORT:
            action = self._create_short_grid_action(symbol, total_amount_quote)
        else:
            # LONG: Use standard grid creation
            action = super()._create_grid_action(symbol, total_amount_quote)

        if action is None:
            self.liquidation_prices.pop(symbol, None)
            self.active_directions.pop(symbol, None)
            self._update_correlation_tracking(symbol, is_opening=False)
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
                self._reset_trailing_stop(self.active_coin)
                return [risk_stop]

        # PRIORITEIT 2: Liquidation risk monitoring
        liquidation_action = self._monitor_liquidation_risk()
        if liquidation_action:
            if self.active_coin:
                self.risk_guard.notify_grid_stopped(self.active_coin)
                self._schedule_cancel_exchange_tpsl(self.active_coin)
                self._reset_trailing_stop(self.active_coin)
            return [liquidation_action]

        # PRIORITEIT 3: Trailing stop check (Sprint 3)
        if self.active_coin and self._is_executor_actually_active():
            trailing_stop_action = self._check_trailing_stop(self.active_coin)
            if trailing_stop_action:
                self.liquidation_prices.pop(self.active_coin, None)
                self.risk_guard.notify_grid_stopped(self.active_coin)
                self._schedule_cancel_exchange_tpsl(self.active_coin)
                return [trailing_stop_action]

        # PRIORITEIT 4: Normale grid logic
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
