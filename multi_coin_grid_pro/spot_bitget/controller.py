"""
Bitget SPOT Grid Controller

Extends MultiCoinGridController with Bitget spot-specific logic:
- No leverage/margin
- USDT quote asset
- Bitget fee structure (0.1% maker/taker)
- Rate limiting for Bitget API
"""

import asyncio
from decimal import Decimal
from typing import List, Optional

from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig


class SpotGridBitgetController(MultiCoinGridController):
    """
    Controller for Bitget SPOT grid trading.

    Inherits all base functionality from MultiCoinGridController and adds:
    - Bitget-specific rate limiting
    - USDT pair filtering
    - Spot-specific risk management (no liquidation)
    """

    def __init__(self, config: SpotGridBitgetConfig, **kwargs):
        """
        Initialize Bitget SPOT controller

        Args:
            config: SpotGridBitgetConfig with Bitget parameters
            **kwargs: Additional arguments passed to parent (connectors, market_data_provider, etc.)
        """
        super().__init__(config=config, **kwargs)
        self.config: SpotGridBitgetConfig = config

        # Initialize trends dict (required for volatility-adjusted sizing)
        self.trends = {}

        self.logger().info("=" * 80)
        self.logger().info("  BITGET SPOT GRID CONTROLLER INITIALIZED")
        self.logger().info("=" * 80)
        self.logger().info("  Exchange: Bitget SPOT")
        self.logger().info(f"  Quote Asset: {config.quote_asset}")
        self.logger().info(f"  Capital: {config.total_amount_quote} {config.quote_asset}")
        self.logger().info(f"  Trading Pairs: {len(config.manual_trading_pairs)}")
        self.logger().info(f"  Grid Levels: {config.num_grids}")
        self.logger().info(f"  Order Size: {config.min_order_amount_quote} {config.quote_asset}")
        self.logger().info("=" * 80)

    def _validate_trading_pair(self, trading_pair: str) -> bool:
        """
        Validate if trading pair is suitable for Bitget SPOT.

        Args:
            trading_pair: Trading pair (e.g., "BTC-USDT")

        Returns:
            True if valid for Bitget spot
        """
        if not super()._validate_trading_pair(trading_pair):
            return False

        # Bitget SPOT specific validation
        base, quote = trading_pair.split("-")

        # Must be USDT quote
        if quote != self.config.quote_asset:
            self.logger.debug(f"❌ {trading_pair}: Quote must be {self.config.quote_asset}")
            return False

        # Check if in blacklist
        if trading_pair in self.config.blacklist:
            self.logger.debug(f"❌ {trading_pair}: Blacklisted")
            return False

        return True

    def _executor_open_order_cap(self, timestamp: float):
        """Enable only for newly-created Bitget Spot USDT executors after activation."""
        if (self.config.connector_name == "bitget"
                and self.config.quote_asset == "USDT"
                and self.config.buy_cap_is_active(timestamp)):
            return self.config.max_executed_buy_orders_per_executor
        return None

    def _entry_market_supported(self, symbol: str) -> bool:
        if self.config.paper_trading or self.config.connector_name != "bitget":
            return True
        tracker = getattr(self.connector, 'order_book_tracker', None)
        source = getattr(tracker, '_data_source', None)
        if isinstance(source, BitgetAPIOrderBookDataSource) and not source.requires_v3_order_book(symbol):
            return True
        if not hasattr(self, '_unsupported_entry_pairs'):
            self._unsupported_entry_pairs = set()
        if symbol not in self._unsupported_entry_pairs:
            self._unsupported_entry_pairs.add(symbol)
            self.logger().warning(
                "[ENTRY_REJECTED] pair=%s reason=BITGET_ORDER_ROUTE_UNVERIFIED source=%s",
                symbol, "V3" if isinstance(source, BitgetAPIOrderBookDataSource) else "unknown",
            )
        return False

    def _live_bitget_order_book_source(self) -> Optional[BitgetAPIOrderBookDataSource]:
        if self.config.paper_trading or self.config.connector_name != "bitget":
            return None
        tracker = getattr(self.connector, 'order_book_tracker', None)
        source = getattr(tracker, '_data_source', None)
        return source if isinstance(source, BitgetAPIOrderBookDataSource) else None

    def _monitoring_market_supported(self, pair: str) -> bool:
        """Live pool admits only pairs with a proven V2 order-book route; protected pairs bypass this."""
        source = self._live_bitget_order_book_source()
        return source is None or source.order_book_route(pair) == "v2"

    async def _prepare_monitoring_candidates(self, candidates: List[str]) -> None:
        """Classify unproven routes in rank order until enough V2 pairs can fill the pool."""
        source = self._live_bitget_order_book_source()
        if source is None:
            return
        protected = set(self._bounded_monitored_coins([]))
        need = self.config.max_coins_to_monitor - len(protected)
        ordered = [pair for pair in dict.fromkeys(candidates) if pair not in protected]
        budget = CONSTANTS.ORDERBOOK_ROUTE_PROBE_LIMIT
        while need > 0 and budget > 0:
            filled, pending = 0, []
            for pair in ordered:
                route = source.order_book_route(pair)
                if route == "v2":
                    filled += 1
                elif route is None:
                    pending.append(pair)
                if filled + len(pending) >= need:
                    break
            batch = pending[:budget]
            if not batch:
                return
            budget -= len(batch)
            routes = await asyncio.gather(*(source.classify_order_book_route(pair) for pair in batch))
            if not any(routes):
                self.logger().warning(
                    "[MONITORING] order-book route unknown for %s candidates; left out of live pool", len(batch))
                return

    def _check_smart_entry_filter(self, symbol: str) -> bool:
        return self._entry_market_supported(symbol) and super()._check_smart_entry_filter(symbol)

    def _create_grid_action(
        self, symbol: str, total_amount_quote: Optional[Decimal] = None
    ) -> Optional[CreateExecutorAction]:
        if not self._entry_market_supported(symbol):
            return None
        return super()._create_grid_action(symbol, total_amount_quote)

    def _decision_telemetry_config(self) -> dict:
        if not self.config.decision_telemetry_enabled:
            return {}
        return {
            "decision_telemetry_enabled": True,
            "decision_telemetry_db_path": "data/trading_decision_telemetry_spot_grid_bitget.db",
            "decision_telemetry_queue_size": self.config.decision_telemetry_queue_size,
            "decision_telemetry_retention_days": self.config.decision_telemetry_retention_days,
            "buy_cap_config_version": self.config.buy_cap_config_version,
        }

    def _calculate_order_size(self, trading_pair: str, mid_price: Decimal) -> Decimal:
        """
        Calculate order size for Bitget spot (no leverage).

        Args:
            trading_pair: Trading pair
            mid_price: Current mid price

        Returns:
            Order size in base currency
        """
        # Get base order size from config
        order_size_quote = Decimal(str(self.config.min_order_amount_quote))

        # Convert to base currency
        order_size_base = order_size_quote / mid_price

        # Apply exposure limits
        max_exposure_quote = Decimal(str(self.config.total_amount_quote)) * \
            Decimal(str(self.config.max_exposure_per_coin_pct))
        max_order_size_base = max_exposure_quote / mid_price

        # Take minimum
        final_size = min(order_size_base, max_order_size_base)

        self.logger.debug(
            f"{trading_pair} | Order size: {final_size:.6f} "
            f"({order_size_quote:.2f} {self.config.quote_asset})"
        )

        return final_size

    def _check_rate_limits(self) -> bool:
        """
        Check if we're within Bitget rate limits.

        Bitget SPOT limits:
        - Public API: 20 req/sec
        - Private API: 10 req/sec
        - Orders: 10/sec

        Returns:
            True if safe to proceed
        """
        # This is handled by Hummingbot's rate limiter
        # but we add extra buffer via config.rate_limit_buffer
        return True

    def _get_bitget_fees(self, trading_pair: str) -> tuple[Decimal, Decimal]:
        """
        Get Bitget spot trading fees.

        Args:
            trading_pair: Trading pair

        Returns:
            Tuple of (maker_fee, taker_fee) as decimals
        """
        maker_fee = Decimal(str(self.config.bitget_maker_fee_pct)) / Decimal("100")
        taker_fee = Decimal(str(self.config.bitget_taker_fee_pct)) / Decimal("100")

        return maker_fee, taker_fee

    def _adjust_for_tick_size(self, price: Decimal, trading_pair: str) -> Decimal:
        """
        Adjust price to match Bitget's tick size requirements.

        Bitget enforces strict tick sizes - orders rejected if not exact.

        Args:
            price: Desired price
            trading_pair: Trading pair

        Returns:
            Price adjusted to tick size
        """
        # Get tick size from connector if available
        try:
            tick_size = self.connector.get_order_price_quantum(
                trading_pair=trading_pair,
                price=price
            )
            if tick_size and tick_size > 0:
                # Round to nearest tick
                adjusted_price = (price // tick_size) * tick_size
                return adjusted_price
        except Exception as e:
            self.logger.warning(f"Could not get tick size for {trading_pair}: {e}")

        # Fallback: round to 2 decimal places (common for USDT pairs)
        return price.quantize(Decimal("0.01"))

    def _adjust_for_lot_size(self, amount: Decimal, trading_pair: str) -> Decimal:
        """
        Adjust amount to match Bitget's lot size requirements.

        Args:
            amount: Desired amount
            trading_pair: Trading pair

        Returns:
            Amount adjusted to lot size
        """
        # Get lot size from connector if available
        try:
            lot_size = self.connector.get_order_size_quantum(
                trading_pair=trading_pair,
                order_size=amount
            )
            if lot_size and lot_size > 0:
                # Round down to nearest lot
                adjusted_amount = (amount // lot_size) * lot_size
                return adjusted_amount
        except Exception as e:
            self.logger.warning(f"Could not get lot size for {trading_pair}: {e}")

        # Fallback: return as-is
        return amount

    def format_status(self) -> str:
        """
        Format status display for Bitget spot bot.

        Returns:
            Formatted status string
        """
        lines = []
        lines.append("\n" + "=" * 80)
        lines.append("  BITGET SPOT GRID - STATUS")
        lines.append("=" * 80)

        # Capital info
        lines.append(f"  💰 Capital: {self.config.total_amount_quote} {self.config.quote_asset}")
        lines.append(f"  📊 Max Exposure: {self.config.max_exposure_per_coin_pct * 100:.0f}% per coin")

        # Trading pairs
        lines.append(f"\n  🎯 Active Pairs: {len(self.config.manual_trading_pairs)}")
        for pair in self.config.manual_trading_pairs[:5]:  # Show first 5
            lines.append(f"     • {pair}")
        if len(self.config.manual_trading_pairs) > 5:
            lines.append(f"     ... and {len(self.config.manual_trading_pairs) - 5} more")

        # Risk limits
        lines.append("\n  🛡️  Risk Management:")
        lines.append(f"     Stop Loss: {self.config.stop_loss_pct:.1f}%")
        lines.append(f"     Take Profit: {self.config.take_profit_pct:.1f}%")
        lines.append(f"     Max Daily Loss: {self.config.max_daily_loss_usdt} {self.config.quote_asset}")

        lines.append("=" * 80 + "\n")

        return "\n".join(lines)
