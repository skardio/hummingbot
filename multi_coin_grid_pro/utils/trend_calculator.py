"""
Trend Calculator

Calculates and tracks price trends for multiple coins.
"""

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import PriceType

logger = logging.getLogger(__name__)


@dataclass
class CoinTrend:
    """
    Data class for storing coin trend information

    Attributes:
        symbol: Trading pair symbol (e.g., "XRP/EUR")
        current_price: Latest price
        trend_pct: Trend percentage over lookback period
        price_history: List of {price, timestamp} dicts
        last_updated: Unix timestamp of last update
    """
    symbol: str
    current_price: Decimal = Decimal("0")
    trend_pct: float = 0.0
    price_history: List[Dict] = field(default_factory=list)
    last_updated: float = 0.0

    @property
    def has_sufficient_data(self) -> bool:
        """Check if we have enough data points (minimum 50 for 60min at 70s intervals)"""
        return len(self.price_history) >= 50


class TrendCalculator:
    """
    Calculates price trends for multiple coins

    Tracks price history and calculates trend percentage over a lookback period.
    """

    def __init__(
        self,
        connector: ConnectorBase,
        lookback_minutes: int = 30
    ):
        """
        Initialize trend calculator

        Args:
            connector: Exchange connector
            lookback_minutes: How many minutes of history to track
        """
        self.connector = connector
        self.lookback_seconds = lookback_minutes * 60
        self.trends: Dict[str, CoinTrend] = {}

    async def update_coin_trend(self, symbol: str) -> Optional[CoinTrend]:
        """
        Update trend for a single coin

        Args:
            symbol: Trading pair symbol

        Returns:
            Updated CoinTrend or None if error
        """
        try:
            # Fetch current price using REST API (Kraken uses PLURAL method)
            prices_dict = await self.connector.get_last_traded_prices([symbol])
            price = prices_dict.get(symbol) if prices_dict else None

            if price is None or price == 0:
                # Don't spam logs - silently skip
                return None

            current_time = time.time()

            # Initialize trend if doesn't exist
            if symbol not in self.trends:
                self.trends[symbol] = CoinTrend(
                    symbol=symbol,
                    current_price=price,
                    trend_pct=0.0,
                    price_history=[],
                    last_updated=current_time
                )

            trend = self.trends[symbol]

            # Update current price
            trend.current_price = price
            trend.last_updated = current_time

            # Add to price history
            trend.price_history.append({
                'price': price,
                'timestamp': current_time
            })

            # Remove old data points
            cutoff_time = current_time - self.lookback_seconds
            trend.price_history = [
                p for p in trend.price_history
                if p['timestamp'] > cutoff_time
            ]

            # Calculate trend if we have enough data
            if len(trend.price_history) >= 2:
                oldest_price = trend.price_history[0]['price']
                price_change = price - oldest_price
                trend.trend_pct = float(price_change / oldest_price * 100)

            return trend

        except Exception as e:
            logger.error(f"❌ Error updating trend for {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def update_all_trends_v2(self, symbols: List[str]) -> None:
        """
        Update trends for all monitored coins - V2 with fixed price fetching

        Args:
            symbols: List of trading pair symbols
        """
        logger.info(f"🚨 ENTERING update_all_trends_v2 with {len(symbols)} symbols")
        logger.info(f"🚨 First symbol: {symbols[0] if symbols else 'NONE'}")

        # Test fetch BEFORE the loop
        try:
            logger.info("🚨 Testing get_last_traded_prices on first symbol...")
            test_prices = await self.connector.get_last_traded_prices([symbols[0]])
            logger.info(f"🚨 Test result: {test_prices}")
        except Exception as e:
            logger.error(f"🚨 TEST FAILED: {e}")

        logger.info("🚨 Starting loop over symbols...")
        for i, symbol in enumerate(symbols):
            logger.info(f"🚨 Loop iteration {i}: {symbol}")
            print(f"🔧 DEBUG: Processing {i + 1}/{len(symbols)}: {symbol}")
            trend = await self.update_coin_trend(symbol)
            print(f"🔧 DEBUG: Result for {symbol}: {trend}")

            if trend:
                trend_emoji = "📈" if trend.trend_pct >= 0 else "📉"
                data_status = f"{len(trend.price_history)}/{int(self.lookback_seconds / 30)} points"

                logger.info(
                    f"{trend_emoji} {symbol:12} | "
                    f"€{trend.current_price:8.4f} | "
                    f"Trend: {trend.trend_pct:+6.2f}% | "
                    f"Data: {data_status}"
                )

    def get_best_coin(self, min_trend_pct: float) -> Optional[str]:
        """
        Find coin with best (highest) trend

        Args:
            min_trend_pct: Minimum trend percentage required

        Returns:
            Symbol of best coin or None if no coin meets criteria
        """
        # DEBUG: Log what we have - return in dict for controller to log
        total_coins = len(self.trends)
        coins_with_data = sum(1 for t in self.trends.values() if t.has_sufficient_data)

        # Store debug info to return later
        self._debug_info = {
            'total': total_coins,
            'sufficient': coins_with_data,
            'min_trend': min_trend_pct
        }

        best_symbol = None
        best_trend = min_trend_pct

        # Track all trends for debugging
        all_trends = []

        coin_idx = 0
        for symbol, trend in self.trends.items():
            # DEBUG: Show data status for first 10 coins
            if coin_idx < 10:
                logger.info(
                    f"  Coin {symbol}: {len(trend.price_history)} points, "
                    f"sufficient={trend.has_sufficient_data}, trend={trend.trend_pct:+.3f}%"
                )
            coin_idx += 1

            # Skip coins without sufficient data
            if not trend.has_sufficient_data:
                continue

            all_trends.append((symbol, trend.trend_pct))

            # Check if better than current best
            if trend.trend_pct > best_trend:
                best_trend = trend.trend_pct
                best_symbol = symbol

        # Store top trends for controller to log
        if all_trends:
            all_trends.sort(key=lambda x: x[1], reverse=True)
            self._debug_info['top_10'] = all_trends[:10]
            self._debug_info['all_count'] = len(all_trends)
        else:
            self._debug_info['top_10'] = []
            self._debug_info['all_count'] = 0

        if best_symbol:
            self._debug_info['best'] = (best_symbol, best_trend)
        else:
            # Check data collection progress
            max_history = max(
                (len(t.price_history) for t in self.trends.values()),
                default=0
            )
            if max_history < 60:
                time_collected = max_history * 0.5  # 30s intervals
                time_remaining = 30 - time_collected
                logger.info(
                    f"\n⏳ DATA COLLECTION: {max_history}/60 points "
                    f"({time_collected:.1f}/30 min) - wait {time_remaining:.1f} min more"
                )
            else:
                logger.warning(
                    f"\n⚠️  NO COIN MEETS MINIMUM TREND ({min_trend_pct}%)"
                )

        return best_symbol

    def get_trend(self, symbol: str) -> Optional[CoinTrend]:
        """Get trend data for a specific coin"""
        return self.trends.get(symbol)

    def clear_trends(self) -> None:
        """Clear all trend data"""
        self.trends.clear()
