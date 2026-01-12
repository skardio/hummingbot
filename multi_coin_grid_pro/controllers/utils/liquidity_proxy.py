"""
Orderbook Depth-Based Liquidity Proxy

Provides real-time liquidity measurement using orderbook depth analysis,
independent of exchange-provided volume data.

Use Cases:
- Exchanges with unreliable ticker volume (e.g., Bitget)
- Real-time liquidity validation for safe order execution
- Alternative liquidity metric for coin selection

Phase 1: Log-only depth metrics + SmartEntry validation
Phase 2: Depth-based ranking (future)
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

from hummingbot.core.data_type.order_book_row import OrderBookRow

logger = logging.getLogger(__name__)


@dataclass
class DepthMetrics:
    """Orderbook depth analysis results"""
    bid_depth: Decimal  # Total bid volume within range
    ask_depth: Decimal  # Total ask volume within range
    depth_score: Decimal  # min(bid_depth, ask_depth)
    spread_pct: Decimal  # Current spread percentage
    mid_price: Decimal  # Reference mid price
    price_range_pct: float  # Range used for calculation
    levels_analyzed: int  # Number of orderbook levels checked


def calculate_orderbook_depth(
    bids: List[OrderBookRow],
    asks: List[OrderBookRow],
    mid_price: Decimal,
    pct_range: float = 0.5,
    max_levels: int = 10
) -> DepthMetrics:
    """
    Calculate orderbook depth within a price range around mid price.

    Args:
        bids: List of bid orderbook rows (price, amount)
        asks: List of ask orderbook rows (price, amount)
        mid_price: Current mid price (for range calculation)
        pct_range: Percentage range around mid price (e.g., 0.5 = ±0.5%)
        max_levels: Maximum number of orderbook levels to analyze per side

    Returns:
        DepthMetrics with bid/ask depth and liquidity score

    Example:
        >>> bids = [OrderBookRow(100.0, 10.0), OrderBookRow(99.5, 5.0)]
        >>> asks = [OrderBookRow(100.5, 8.0), OrderBookRow(101.0, 12.0)]
        >>> metrics = calculate_orderbook_depth(bids, asks, Decimal("100"), 0.5, 10)
        >>> print(metrics.depth_score)  # min(bid_depth, ask_depth)
    """
    # Input validation
    if not bids or not asks:
        logger.warning("Empty orderbook data - cannot calculate depth")
        return DepthMetrics(
            bid_depth=Decimal("0"),
            ask_depth=Decimal("0"),
            depth_score=Decimal("0"),
            spread_pct=Decimal("0"),
            mid_price=mid_price,
            price_range_pct=pct_range,
            levels_analyzed=0
        )

    # Calculate price range bounds
    range_decimal = Decimal(str(pct_range / 100))  # 0.5% → 0.005
    lower_bound = mid_price * (Decimal("1") - range_decimal)
    upper_bound = mid_price * (Decimal("1") + range_decimal)

    # Calculate bid depth IN QUOTE CURRENCY (price × amount)
    bid_depth = Decimal("0")
    bid_levels = 0
    for bid in bids[:max_levels]:
        bid_price = Decimal(str(bid.price))
        if bid_price >= lower_bound:
            bid_amount = Decimal(str(bid.amount))
            bid_depth += bid_price * bid_amount  # Quote currency value
            bid_levels += 1
        else:
            break  # Bids are sorted descending, stop when price too low

    # Calculate ask depth IN QUOTE CURRENCY (price × amount)
    ask_depth = Decimal("0")
    ask_levels = 0
    for ask in asks[:max_levels]:
        ask_price = Decimal(str(ask.price))
        if ask_price <= upper_bound:
            ask_amount = Decimal(str(ask.amount))
            ask_depth += ask_price * ask_amount  # Quote currency value
            ask_levels += 1
        else:
            break  # Asks are sorted ascending, stop when price too high

    # Calculate spread
    best_bid = Decimal(str(bids[0].price)) if bids else Decimal("0")
    best_ask = Decimal(str(asks[0].price)) if asks else Decimal("0")
    spread_pct = Decimal("0")
    if best_bid > 0 and best_ask > 0:
        spread_pct = ((best_ask - best_bid) / best_bid) * Decimal("100")

    # Depth score = minimum of both sides (bottleneck)
    depth_score = min(bid_depth, ask_depth)

    return DepthMetrics(
        bid_depth=bid_depth,
        ask_depth=ask_depth,
        depth_score=depth_score,
        spread_pct=spread_pct,
        mid_price=mid_price,
        price_range_pct=pct_range,
        levels_analyzed=bid_levels + ask_levels
    )


def calculate_required_depth(
    order_size_quote: Decimal,
    multiplier: float = 5.0
) -> Decimal:
    """
    Calculate minimum required depth based on order size.

    Args:
        order_size_quote: Planned order size in quote currency
        multiplier: Safety multiplier (e.g., 5.0 = 5x order size)

    Returns:
        Minimum required depth in quote currency

    Example:
        >>> calculate_required_depth(Decimal("100"), 5.0)
        Decimal('500')
    """
    return order_size_quote * Decimal(str(multiplier))


def is_sufficient_depth(
    depth_score: Decimal,
    order_size_quote: Decimal,
    multiplier: float = 5.0,
    tolerance_pct: float = 10.0
) -> Tuple[bool, Decimal]:
    """
    Check if orderbook depth is sufficient for safe execution.

    Args:
        depth_score: Calculated depth score (min of bid/ask depth)
        order_size_quote: Planned order size in quote currency
        multiplier: Safety multiplier for required depth
        tolerance_pct: Tolerance percentage below required (e.g., 10% = accept 90% of required)

    Returns:
        (is_sufficient, required_depth)

    Example:
        >>> is_sufficient_depth(Decimal("500"), Decimal("100"), 5.0, 10.0)
        (True, Decimal('500'))  # 500 >= 450 (90% of 500)
    """
    required_depth = calculate_required_depth(order_size_quote, multiplier)
    tolerance_factor = Decimal("1") - Decimal(str(tolerance_pct / 100))
    min_acceptable = required_depth * tolerance_factor

    is_ok = depth_score >= min_acceptable
    return is_ok, required_depth


def format_depth_log(
    symbol: str,
    metrics: DepthMetrics,
    order_size: Decimal,
    multiplier: float,
    is_sufficient: bool
) -> str:
    """
    Format depth metrics for logging.

    Args:
        symbol: Trading pair symbol
        metrics: Calculated depth metrics
        order_size: Order size in quote currency
        multiplier: Depth multiplier used
        is_sufficient: Whether depth is sufficient

    Returns:
        Formatted log string

    Example:
        >>> format_depth_log("BTC-USDT", metrics, Decimal("100"), 5.0, True)
        "BTC-USDT: depth=520.3 (bid=550.0, ask=520.3) vs required=500.0 (5.0x$100) ✅ spread=0.05%"
    """
    required = calculate_required_depth(order_size, multiplier)
    status = "✅" if is_sufficient else "❌"

    return (
        f"{symbol}: depth={metrics.depth_score:.1f} "
        f"(bid={metrics.bid_depth:.1f}, ask={metrics.ask_depth:.1f}) "
        f"vs required={required:.1f} ({multiplier}x${order_size:.0f}) "
        f"{status} spread={metrics.spread_pct:.2f}%"
    )


def get_orderbook_snapshot(
    connector,
    trading_pair: str,
    max_retries: int = 3,
    retry_delay_ms: int = 500
) -> Tuple[Optional[List[OrderBookRow]], Optional[List[OrderBookRow]], Optional[Decimal]]:
    """
    Get orderbook snapshot from connector with retry logic.

    Args:
        connector: Exchange connector instance
        trading_pair: Trading pair symbol
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay_ms: Delay between retries in milliseconds (default: 500)

    Returns:
        (bids, asks, mid_price) or (None, None, None) if unavailable after retries

    Note:
        Uses cached orderbook data - no additional REST calls.
        Retries handle race conditions during orderbook initialization.
    """
    import time

    for attempt in range(max_retries):
        try:
            order_book = connector.get_order_book(trading_pair)
            if not order_book:
                if attempt < max_retries - 1:
                    logger.debug(f"[OB_RETRY] {trading_pair} - No order_book object (attempt {attempt + 1}/{max_retries})")
                    time.sleep((retry_delay_ms / 1000.0) * (attempt + 1))
                    continue
                return None, None, None

            snapshot = order_book.snapshot
            if snapshot is None or snapshot[0] is None or snapshot[1] is None:
                if attempt < max_retries - 1:
                    logger.debug(f"[OB_RETRY] {trading_pair} - No snapshot (attempt {attempt + 1}/{max_retries})")
                    time.sleep((retry_delay_ms / 1000.0) * (attempt + 1))
                    continue
                return None, None, None

            bids = snapshot[0]  # List[OrderBookRow]
            asks = snapshot[1]  # List[OrderBookRow]

            # Explicit None check to avoid DataFrame ambiguity
            if bids is None or asks is None or len(bids) == 0 or len(asks) == 0:
                if attempt < max_retries - 1:
                    logger.debug(f"[OB_RETRY] {trading_pair} - Empty bids/asks (attempt {attempt + 1}/{max_retries})")
                    time.sleep((retry_delay_ms / 1000.0) * (attempt + 1))
                    continue
                return None, None, None

            # Calculate mid price
            best_bid = Decimal(str(bids[0].price))
            best_ask = Decimal(str(asks[0].price))
            mid_price = (best_bid + best_ask) / Decimal("2")

            # Success - log if retry was needed
            if attempt > 0:
                logger.info(f"[OB_RETRY] {trading_pair} - Success after {attempt + 1} attempts")

            return bids, asks, mid_price

        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"[OB_RETRY] {trading_pair} - Exception: {e} (attempt {attempt + 1}/{max_retries})")
                time.sleep((retry_delay_ms / 1000.0) * (attempt + 1))
            else:
                logger.debug(f"Failed to get orderbook for {trading_pair} after {max_retries} attempts: {e}")

    return None, None, None
