"""
Staleness Guard - US-008

Ensures we don't trade on stale/outdated market data.
Tracks last update timestamps for prices and orderbooks per trading pair.

Usage:
    guard = StalenessGuard(max_price_age_ms=2000, max_orderbook_age_ms=5000)
    guard.update_price("BTC-USDT", 50000.0)
    guard.update_orderbook("BTC-USDT")

    is_fresh, reason = guard.is_data_fresh("BTC-USDT")
    if not is_fresh:
        logger.warning(f"Stale data: {reason}")
"""
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class StaleReason(Enum):
    """Reason why data is considered stale."""
    FRESH = "FRESH"
    STALE_PRICE = "STALE_PRICE"
    STALE_ORDERBOOK = "STALE_ORDERBOOK"
    NO_PRICE_DATA = "NO_PRICE_DATA"
    NO_ORDERBOOK_DATA = "NO_ORDERBOOK_DATA"


@dataclass
class DataFreshness:
    """Result of freshness check."""
    is_fresh: bool
    reason: StaleReason
    price_age_ms: Optional[float] = None
    orderbook_age_ms: Optional[float] = None
    details: Optional[str] = None


class StalenessGuard:
    """
    Guards against trading on stale market data.

    Tracks timestamps of last price and orderbook updates per trading pair.
    Rejects entries when data is older than configured thresholds.
    """

    def __init__(
        self,
        max_price_age_ms: int = 2000,
        max_orderbook_age_ms: int = 5000,
        enabled: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize staleness guard.

        Args:
            max_price_age_ms: Maximum allowed age for price data (milliseconds)
            max_orderbook_age_ms: Maximum allowed age for orderbook data (milliseconds)
            enabled: Whether staleness checking is enabled
            logger: Optional logger instance
        """
        self.max_price_age_ms = max_price_age_ms
        self.max_orderbook_age_ms = max_orderbook_age_ms
        self.enabled = enabled
        self.logger = logger or logging.getLogger(__name__)

        # Track last update timestamps per pair (in seconds, using time.time())
        self._last_price_update: Dict[str, float] = {}
        self._last_orderbook_update: Dict[str, float] = {}

        # Track last known prices (for detecting stale/unchanged prices)
        self._last_prices: Dict[str, float] = {}

        # Statistics
        self._stale_rejections: Dict[str, int] = {}  # {pair: count}

        self.logger.info(
            f"🕐 StalenessGuard initialized: "
            f"max_price_age={max_price_age_ms}ms, "
            f"max_orderbook_age={max_orderbook_age_ms}ms, "
            f"enabled={enabled}"
        )

    def update_price(self, symbol: str, price: float) -> None:
        """
        Record a price update for a trading pair.

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            price: Current price
        """
        now = time.time()
        self._last_price_update[symbol] = now
        self._last_prices[symbol] = price

    def update_orderbook(self, symbol: str) -> None:
        """
        Record an orderbook update for a trading pair.

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
        """
        self._last_orderbook_update[symbol] = time.time()

    def get_price_age_ms(self, symbol: str) -> Optional[float]:
        """
        Get age of last price update in milliseconds.

        Args:
            symbol: Trading pair

        Returns:
            Age in milliseconds, or None if no price data
        """
        if symbol not in self._last_price_update:
            return None
        age_seconds = time.time() - self._last_price_update[symbol]
        return age_seconds * 1000

    def get_orderbook_age_ms(self, symbol: str) -> Optional[float]:
        """
        Get age of last orderbook update in milliseconds.

        Args:
            symbol: Trading pair

        Returns:
            Age in milliseconds, or None if no orderbook data
        """
        if symbol not in self._last_orderbook_update:
            return None
        age_seconds = time.time() - self._last_orderbook_update[symbol]
        return age_seconds * 1000

    def is_data_fresh(
        self,
        symbol: str,
        require_price: bool = True,
        require_orderbook: bool = True
    ) -> DataFreshness:
        """
        Check if market data for a trading pair is fresh enough for trading.

        Args:
            symbol: Trading pair to check
            require_price: Whether price data is required
            require_orderbook: Whether orderbook data is required

        Returns:
            DataFreshness result with is_fresh, reason, and age info
        """
        if not self.enabled:
            return DataFreshness(
                is_fresh=True,
                reason=StaleReason.FRESH,
                details="Staleness check disabled"
            )

        price_age_ms = self.get_price_age_ms(symbol)
        orderbook_age_ms = self.get_orderbook_age_ms(symbol)

        # Check if we have price data
        if require_price and price_age_ms is None:
            self._record_rejection(symbol, StaleReason.NO_PRICE_DATA)
            return DataFreshness(
                is_fresh=False,
                reason=StaleReason.NO_PRICE_DATA,
                price_age_ms=None,
                orderbook_age_ms=orderbook_age_ms,
                details=f"No price data available for {symbol}"
            )

        # Check if we have orderbook data
        if require_orderbook and orderbook_age_ms is None:
            self._record_rejection(symbol, StaleReason.NO_ORDERBOOK_DATA)
            return DataFreshness(
                is_fresh=False,
                reason=StaleReason.NO_ORDERBOOK_DATA,
                price_age_ms=price_age_ms,
                orderbook_age_ms=None,
                details=f"No orderbook data available for {symbol}"
            )

        # Check price staleness
        if require_price and price_age_ms is not None:
            if price_age_ms > self.max_price_age_ms:
                self._record_rejection(symbol, StaleReason.STALE_PRICE)
                return DataFreshness(
                    is_fresh=False,
                    reason=StaleReason.STALE_PRICE,
                    price_age_ms=price_age_ms,
                    orderbook_age_ms=orderbook_age_ms,
                    details=f"Price data stale: {price_age_ms:.0f}ms > {self.max_price_age_ms}ms"
                )

        # Check orderbook staleness
        if require_orderbook and orderbook_age_ms is not None:
            if orderbook_age_ms > self.max_orderbook_age_ms:
                self._record_rejection(symbol, StaleReason.STALE_ORDERBOOK)
                return DataFreshness(
                    is_fresh=False,
                    reason=StaleReason.STALE_ORDERBOOK,
                    price_age_ms=price_age_ms,
                    orderbook_age_ms=orderbook_age_ms,
                    details=f"Orderbook stale: {orderbook_age_ms:.0f}ms > {self.max_orderbook_age_ms}ms"
                )

        # All checks passed - build details string safely
        price_str = f"{price_age_ms:.0f}ms" if price_age_ms is not None else "N/A"
        orderbook_str = f"{orderbook_age_ms:.0f}ms" if orderbook_age_ms is not None else "N/A"
        return DataFreshness(
            is_fresh=True,
            reason=StaleReason.FRESH,
            price_age_ms=price_age_ms,
            orderbook_age_ms=orderbook_age_ms,
            details=f"Data fresh (price: {price_str}, orderbook: {orderbook_str})"
        )

    def _record_rejection(self, symbol: str, reason: StaleReason) -> None:
        """Record a rejection for statistics."""
        key = f"{symbol}:{reason.value}"
        self._stale_rejections[key] = self._stale_rejections.get(key, 0) + 1

    def get_statistics(self) -> Dict[str, any]:
        """
        Get staleness guard statistics.

        Returns:
            Dict with stats like rejection counts, oldest data, etc.
        """
        now = time.time()

        # Find oldest price and orderbook data
        oldest_price_age_ms = None
        oldest_price_pair = None
        for symbol, ts in self._last_price_update.items():
            age_ms = (now - ts) * 1000
            if oldest_price_age_ms is None or age_ms > oldest_price_age_ms:
                oldest_price_age_ms = age_ms
                oldest_price_pair = symbol

        oldest_orderbook_age_ms = None
        oldest_orderbook_pair = None
        for symbol, ts in self._last_orderbook_update.items():
            age_ms = (now - ts) * 1000
            if oldest_orderbook_age_ms is None or age_ms > oldest_orderbook_age_ms:
                oldest_orderbook_age_ms = age_ms
                oldest_orderbook_pair = symbol

        return {
            "enabled": self.enabled,
            "max_price_age_ms": self.max_price_age_ms,
            "max_orderbook_age_ms": self.max_orderbook_age_ms,
            "tracked_pairs_price": len(self._last_price_update),
            "tracked_pairs_orderbook": len(self._last_orderbook_update),
            "oldest_price_age_ms": oldest_price_age_ms,
            "oldest_price_pair": oldest_price_pair,
            "oldest_orderbook_age_ms": oldest_orderbook_age_ms,
            "oldest_orderbook_pair": oldest_orderbook_pair,
            "total_rejections": sum(self._stale_rejections.values()),
            "rejections_by_type": dict(self._stale_rejections)
        }

    def clear_pair(self, symbol: str) -> None:
        """
        Clear tracking data for a trading pair.

        Args:
            symbol: Trading pair to clear
        """
        self._last_price_update.pop(symbol, None)
        self._last_orderbook_update.pop(symbol, None)
        self._last_prices.pop(symbol, None)

    def reset(self) -> None:
        """Reset all tracking data."""
        self._last_price_update.clear()
        self._last_orderbook_update.clear()
        self._last_prices.clear()
        self._stale_rejections.clear()
