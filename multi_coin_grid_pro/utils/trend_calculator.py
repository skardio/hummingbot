"""
Trend Calculator

Calculates and tracks price trends for multiple coins.
Phase 2: Enhanced trend detection with volatility normalization, EMA, and linear regression.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import stdev
from typing import Dict, List, Optional

import numpy as np

from hummingbot.connector.connector_base import ConnectorBase

logger = logging.getLogger(__name__)


@dataclass
class CoinTrend:
    """
    Data class for storing coin trend information

    Attributes:
        symbol: Trading pair symbol (e.g., "XRP/EUR")
        current_price: Latest price
        trend_pct: Trend percentage over lookback period (raw)
        normalized_trend_pct: Volatility-normalized trend (Phase 2.1)
        ema_trend_pct: EMA-based trend (Phase 2.2)
        linreg_trend_pct: Linear regression trend (Phase 2.3)
        consensus_trend_pct: Multi-indicator consensus (Phase 2.4)
        volatility: Rolling standard deviation (Phase 2.1)
        price_history: List of {price, timestamp} dicts
        last_updated: Unix timestamp of last update

        Phase 2.5: Multi-Timeframe Trends
        trend_60m: 1-hour trend percentage
        trend_240m: 4-hour trend percentage
        trend_1440m: 24-hour trend percentage
        trend_score: Composite score (0.2*60m + 0.4*240m + 0.4*1440m)
        long_trend_warmup: True if 24h trend is in warm-up mode (first 24h after bot start)
    """
    symbol: str
    current_price: Decimal = Decimal("0")
    trend_pct: float = 0.0  # Raw percentage trend
    normalized_trend_pct: float = 0.0  # Phase 2.1: Volatility normalized
    ema_trend_pct: float = 0.0  # Phase 2.2: EMA-based trend
    linreg_trend_pct: float = 0.0  # Phase 2.3: Linear regression trend
    consensus_trend_pct: float = 0.0  # Phase 2.4: Multi-indicator consensus
    volatility: float = 0.0  # Phase 2.1: Rolling std dev
    price_history: List[Dict] = field(default_factory=list)
    last_updated: float = 0.0

    # Phase 2.5: Multi-Timeframe Trends
    trend_60m: float = 0.0  # 1-hour trend
    trend_240m: float = 0.0  # 4-hour trend
    trend_1440m: float = 0.0  # 24-hour trend
    trend_score: float = 0.0  # Composite score
    long_trend_warmup: bool = False  # Warm-up mode for 24h trend

    @property
    def has_sufficient_data(self) -> bool:
        """Check if we have enough data points for trend calculation"""
        # Phase 2.5: Lowered threshold for faster coin selection
        # Minimum 20 points for basic trend (was 50)
        # This allows coin selection after ~10 minutes instead of ~25 minutes
        # Multi-timeframe trends will still work with less data (using warm-up mode)
        return len(self.price_history) >= 20


class TrendCalculator:
    """
    Calculates price trends for multiple coins

    Tracks price history and calculates trend percentage over a lookback period.
    """

    def __init__(
        self,
        connector: ConnectorBase,
        lookback_minutes: int = 30,
        bot_start_time: Optional[float] = None,
        base_connector: Optional[ConnectorBase] = None
    ):
        """
        Initialize trend calculator

        Args:
            connector: Exchange connector (paper trading connector for paper trading mode)
            lookback_minutes: How many minutes of history to track (legacy, kept for compatibility)
            bot_start_time: Unix timestamp of bot startup (for warm-up mode detection)
            base_connector: Base connector for price fetching in paper trading mode (optional)
        """
        self.connector = connector
        self.base_connector = base_connector  # Base connector for price fetching in paper trading
        self.lookback_seconds = lookback_minutes * 60
        self.trends: Dict[str, CoinTrend] = {}
        # Phase 2.5: Multi-timeframe support
        self.bot_start_time = bot_start_time if bot_start_time else time.time()
        self.trend_lookback_short_minutes = 60  # 1 hour
        self.trend_lookback_mid_minutes = 240  # 4 hours
        self.trend_lookback_long_minutes = 1440  # 24 hours

    async def update_coin_trend(self, symbol: str) -> Optional[CoinTrend]:
        """
        Update trend for a single coin

        Args:
            symbol: Trading pair symbol

        Returns:
            Updated CoinTrend or None if error
        """
        try:
            # Convert / to - format (Kraken uses - format, not / format)
            if "/" in symbol:
                symbol = symbol.replace("/", "-")

            # Fetch current price - use base connector for paper trading, get_last_traded_prices for live trading
            try:
                # Try get_last_traded_prices first (for live connectors)
                prices_dict = await self.connector.get_last_traded_prices([symbol])
                price = prices_dict.get(symbol) if prices_dict else None
            except NotImplementedError:
                # Paper trading connector doesn't implement get_last_traded_prices
                # FIRST: Try base connector (has access to all coins via live exchange)
                if self.base_connector:
                    try:
                        prices_dict = await self.base_connector.get_last_traded_prices([symbol])
                        price = prices_dict.get(symbol) if prices_dict else None
                        if price:
                            logger.debug(f"✅ Using base connector for {symbol}: {price}")
                    except Exception as base_error:
                        logger.debug(f"Base connector price fetch failed for {symbol}: {base_error}")
                        price = None

                # SECOND: Fallback to get_mid_price from paper connector (only works if order book exists)
                if price is None and self.connector:
                    try:
                        price_decimal = self.connector.get_mid_price(symbol)
                        price = float(price_decimal) if price_decimal else None
                        if price:
                            logger.debug(f"✅ Using get_mid_price for {symbol}: {price}")
                    except Exception as e:
                        logger.debug(f"Failed to get mid price for {symbol}: {e}")
                        price = None

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

                # Phase 2: Enhanced trend detection
                if len(trend.price_history) >= 10:  # Minimum data for advanced indicators
                    # Phase 2.1: Volatility Normalization
                    trend.volatility = self._calculate_volatility(trend.price_history)
                    if trend.volatility > 0:
                        trend.normalized_trend_pct = trend.trend_pct / trend.volatility
                    else:
                        trend.normalized_trend_pct = trend.trend_pct

                    # Phase 2.2: EMA-Based Trend Detection
                    trend.ema_trend_pct = self._calculate_ema_trend(trend.price_history)

                    # Phase 2.3: Linear Regression Slope
                    trend.linreg_trend_pct = self._calculate_linreg_trend(trend.price_history)

                    # Phase 2.4: Multi-Indicator Consensus
                    trend.consensus_trend_pct = self._calculate_consensus_trend(
                        trend.trend_pct,
                        trend.normalized_trend_pct,
                        trend.ema_trend_pct,
                        trend.linreg_trend_pct
                    )

                # Phase 2.5: Multi-Timeframe Trend Calculation
                self._calculate_multi_timeframe_trends(trend, current_time)

            return trend

        except Exception as e:
            logger.error(f"❌ Error updating trend for {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _log_trend_update(self, trend: CoinTrend) -> None:
        """Helper method to log trend update"""
        trend_emoji = "📈" if trend.trend_pct >= 0 else "📉"
        data_status = f"{len(trend.price_history)}/{int(self.lookback_seconds / 30)} points"

        # Phase 2: Show enhanced trend metrics
        if trend.consensus_trend_pct != 0.0:
            logger.info(
                f"{trend_emoji} {trend.symbol:12} | "
                f"€{trend.current_price:8.4f} | "
                f"Raw: {trend.trend_pct:+6.2f}% | "
                f"Consensus: {trend.consensus_trend_pct:+6.2f}% | "
                f"Vol: {trend.volatility:.3f}% | "
                f"Data: {data_status}"
            )
        else:
            logger.info(
                f"{trend_emoji} {trend.symbol:12} | "
                f"€{trend.current_price:8.4f} | "
                f"Trend: {trend.trend_pct:+6.2f}% | "
                f"Data: {data_status}"
            )

    async def _update_coin_trend_with_price(self, symbol: str, price: float) -> Optional[CoinTrend]:
        """
        Update trend for a coin using a pre-fetched price (for batch mode)

        Args:
            symbol: Trading pair symbol
            price: Pre-fetched price

        Returns:
            Updated CoinTrend or None if error
        """
        try:
            if price is None or price == 0:
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

                # Phase 2: Enhanced trend detection
                if len(trend.price_history) >= 10:  # Minimum data for advanced indicators
                    # Phase 2.1: Volatility Normalization
                    trend.volatility = self._calculate_volatility(trend.price_history)
                    if trend.volatility > 0:
                        trend.normalized_trend_pct = trend.trend_pct / trend.volatility
                    else:
                        trend.normalized_trend_pct = trend.trend_pct

                    # Phase 2.2: EMA-Based Trend Detection
                    trend.ema_trend_pct = self._calculate_ema_trend(trend.price_history)

                    # Phase 2.3: Linear Regression Slope
                    trend.linreg_trend_pct = self._calculate_linreg_trend(trend.price_history)

                    # Phase 2.4: Multi-Indicator Consensus
                    trend.consensus_trend_pct = self._calculate_consensus_trend(
                        trend.trend_pct,
                        trend.normalized_trend_pct,
                        trend.ema_trend_pct,
                        trend.linreg_trend_pct
                    )

                # Phase 2.5: Multi-Timeframe Trend Calculation
                self._calculate_multi_timeframe_trends(trend, current_time)

            return trend

        except Exception as e:
            logger.error(f"❌ Error updating trend for {symbol} with price {price}: {e}")
            return None

    async def update_all_trends_v2(self, symbols: List[str]) -> None:
        """
        Update trends for all monitored coins - V2 with batch API calls for optimal performance

        CRITICAL: Rate limiting is built-in to prevent API rate limit errors.
        This method will wait if called too frequently (Kraken: 1 call/second).

        Args:
            symbols: List of trading pair symbols
        """
        # Convert all symbols from / to - format (Kraken uses - format)
        converted_symbols = [s.replace("/", "-") if "/" in s else s for s in symbols]

        if not converted_symbols:
            logger.warning("No symbols to update")
            return

        # CRITICAL RATE LIMITING: Ensure we don't call this too frequently
        # Kraken allows 1 ticker call per second, so we enforce 2 seconds minimum between calls
        current_time = time.time()
        if not hasattr(self, '_last_batch_call_time'):
            self._last_batch_call_time = 0

        time_since_last_call = current_time - self._last_batch_call_time
        MIN_CALL_INTERVAL = 2.0  # Minimum 2 seconds between batch calls (Kraken: 1 call/second)

        if time_since_last_call < MIN_CALL_INTERVAL:
            wait_time = MIN_CALL_INTERVAL - time_since_last_call
            logger.debug(f"⏳ Rate limiting: Waiting {wait_time:.2f}s before batch API call (last call was {time_since_last_call:.2f}s ago)")
            await asyncio.sleep(wait_time)

        # Try batch API call first (much faster - 1 call instead of N calls)
        # Kraken's get_last_traded_prices() supports batch calls - much faster!
        prices_dict = {}
        batch_call_attempted = False
        batch_call_success = False

        try:
            # Try batch call first (for live connectors)
            # IMPORTANT: Kraken's get_last_traded_prices() with multiple pairs makes ONE API call
            # to get ALL tickers, then filters. This is much faster than individual calls.
            batch_call_attempted = True
            self._last_batch_call_time = time.time()  # Update timestamp BEFORE making the call
            logger.info(f"🔄 Attempting batch API call for {len(converted_symbols)} symbols (1 API call for all)...")
            start_time = time.time()
            prices_dict = await self.connector.get_last_traded_prices(converted_symbols)
            elapsed = time.time() - start_time
            if prices_dict and len(prices_dict) > 0:
                batch_call_success = True
                success_rate = len(prices_dict) / len(converted_symbols) * 100
                logger.info(
                    f"✅ Batch API call successful: {len(prices_dict)}/{len(converted_symbols)} prices retrieved "
                    f"({success_rate:.1f}% success) in {elapsed:.2f}s - 1 API call instead of {len(converted_symbols)}"
                )
            else:
                logger.warning(
                    f"⚠️  Batch API call returned empty dict ({len(prices_dict) if prices_dict else 0} prices) - "
                    f"falling back to individual calls (this will be slow: ~{len(converted_symbols) * 1.5:.1f}s)"
                )
        except NotImplementedError:
            # Paper trading connector - try base connector for batch call
            logger.debug("Paper trading connector - trying base connector for batch call...")
            if self.base_connector:
                try:
                    batch_call_attempted = True
                    logger.info(f"🔄 Attempting batch API call via base connector for {len(converted_symbols)} symbols...")
                    prices_dict = await self.base_connector.get_last_traded_prices(converted_symbols)
                    batch_call_success = True
                    logger.info(f"✅ Base connector batch API call successful: {len(prices_dict)}/{len(converted_symbols)} prices retrieved")
                except Exception as e:
                    logger.warning(f"⚠️  Base connector batch fetch failed: {e}")
                    prices_dict = {}
        except Exception as e:
            # Catch any other exceptions (e.g., rate limit errors, network errors)
            logger.warning(f"⚠️  Batch API call failed with exception: {type(e).__name__}: {e}")
            prices_dict = {}

        # If batch call failed or returned empty, fall back to individual calls with rate limiting
        if not batch_call_success or not prices_dict or len(prices_dict) < len(converted_symbols) * 0.5:  # If less than 50% success
            # Fallback: individual calls with rate limiting
            # IMPORTANT: Use direct price fetching instead of update_coin_trend to avoid nested API calls
            RATE_LIMIT_DELAY = 1.5  # Increased from 1.1 to 1.5 seconds between API calls to be safer (Kraken allows 1 call per second)

            if batch_call_attempted:
                logger.warning(f"⚠️  Batch call incomplete ({len(prices_dict)}/{len(converted_symbols)}), falling back to individual calls with rate limiting...")
                logger.warning(f"⚠️  This will make {len(converted_symbols)} API calls with {RATE_LIMIT_DELAY}s delay = ~{len(converted_symbols) * RATE_LIMIT_DELAY:.1f}s total")
            else:
                logger.info(f"🔄 Using individual API calls with rate limiting for {len(converted_symbols)} symbols...")

            # CRITICAL: Add delay BEFORE first call to avoid hitting rate limit immediately
            await asyncio.sleep(RATE_LIMIT_DELAY)
            for i, symbol in enumerate(converted_symbols):
                if i > 0:
                    await asyncio.sleep(RATE_LIMIT_DELAY)

                # Fetch price directly (avoid nested get_last_traded_prices calls)
                try:
                    # Try to get price directly
                    if hasattr(self.connector, 'get_last_traded_prices'):
                        try:
                            single_price_dict = await self.connector.get_last_traded_prices([symbol])
                            price = single_price_dict.get(symbol) if single_price_dict else None
                        except NotImplementedError:
                            if self.base_connector:
                                single_price_dict = await self.base_connector.get_last_traded_prices([symbol])
                                price = single_price_dict.get(symbol) if single_price_dict else None
                            else:
                                price = None
                    else:
                        price = None

                    if price and price > 0:
                        # Update trend using fetched price
                        trend = await self._update_coin_trend_with_price(symbol, float(price))
                        if trend:
                            self._log_trend_update(trend)
                    else:
                        logger.debug(f"⚠️  No price data for {symbol} in fallback mode")
                except Exception as e:
                    logger.debug(f"⚠️  Failed to fetch price for {symbol} in fallback: {e}")
                    continue
        else:
            # Batch mode: update all trends using fetched prices
            logger.info(f"✅ Batch mode: updating {len(prices_dict)} trends using batch-fetched prices")
            for symbol in converted_symbols:
                price = prices_dict.get(symbol)
                if price is None or price == 0:
                    logger.debug(f"⚠️  No price data for {symbol} in batch response")
                    continue

                # Update trend using the batch-fetched price
                trend = await self._update_coin_trend_with_price(symbol, float(price))
                if trend:
                    self._log_trend_update(trend)

    def get_best_coin(self, min_trend_pct: float, exclude_coins: Optional[List[str]] = None) -> Optional[str]:
        """
        Find coin with best (highest) trend

        Args:
            min_trend_pct: Minimum trend percentage required
            exclude_coins: Optional list of coin symbols to exclude from selection

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

        # Set of coins to exclude (for fast lookup)
        exclude_set = set(exclude_coins) if exclude_coins else set()

        best_symbol = None
        best_trend = min_trend_pct

        # Track all trends for debugging
        all_trends = []

        coin_idx = 0
        for symbol, trend in self.trends.items():
            # Skip excluded coins (e.g., coins in cooldown)
            if symbol in exclude_set:
                continue

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

            # Phase 2.5: Use multi-timeframe trend_score if available, otherwise fallback to consensus
            # Check if multi-timeframe is enabled (trend_score != 0.0 means it was calculated)
            if hasattr(trend, 'trend_score') and trend.trend_score != 0.0:
                trend_value = trend.trend_score
            else:
                # Phase 2: Use consensus trend for comparison (more robust)
                trend_value = trend.consensus_trend_pct if trend.consensus_trend_pct != 0.0 else trend.trend_pct

            all_trends.append((symbol, trend_value))

            # Check if better than current best
            if trend_value > best_trend:
                best_trend = trend_value
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

    # Phase 2.1: Volatility Normalization
    def _calculate_volatility(self, price_history: List[Dict]) -> float:
        """
        Calculate rolling standard deviation (volatility) for price history

        Args:
            price_history: List of {price, timestamp} dicts

        Returns:
            Volatility (std dev) as percentage
        """
        if len(price_history) < 2:
            return 0.0

        try:
            prices = [float(p['price']) for p in price_history]
            if len(prices) < 2:
                return 0.0

            # Calculate percentage changes
            pct_changes = []
            for i in range(1, len(prices)):
                if prices[i - 1] > 0:
                    pct_change = ((prices[i] - prices[i - 1]) / prices[i - 1]) * 100
                    pct_changes.append(pct_change)

            if len(pct_changes) < 2:
                return 0.0

            # Calculate standard deviation of percentage changes
            volatility = stdev(pct_changes) if len(pct_changes) > 1 else 0.0
            return abs(volatility)  # Return absolute value
        except Exception as e:
            logger.debug(f"Error calculating volatility: {e}")
            return 0.0

    # Phase 2.2: EMA-Based Trend Detection
    def _calculate_ema_trend(self, price_history: List[Dict]) -> float:
        """
        Calculate trend using EMA cross (EMA30 vs EMA60)

        Args:
            price_history: List of {price, timestamp} dicts

        Returns:
            Trend percentage based on EMA cross
        """
        if len(price_history) < 60:
            return 0.0

        try:
            prices = [float(p['price']) for p in price_history]

            # Calculate EMA(30) and EMA(60)
            ema30 = self._calculate_ema(prices, 30)
            ema60 = self._calculate_ema(prices, 60)

            if ema60 == 0:
                return 0.0

            # Trend = (EMA30 - EMA60) / EMA60 * 100
            trend_pct = ((ema30 - ema60) / ema60) * 100

            return trend_pct
        except Exception as e:
            logger.debug(f"Error calculating EMA trend: {e}")
            return 0.0

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """
        Calculate Exponential Moving Average

        Args:
            prices: List of prices
            period: EMA period

        Returns:
            EMA value
        """
        if len(prices) < period:
            return float(np.mean(prices)) if prices else 0.0

        # Use last 'period' prices
        recent_prices = prices[-period:]

        # Calculate EMA
        multiplier = 2.0 / (period + 1)
        ema = recent_prices[0]

        for price in recent_prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    # Phase 2.3: Linear Regression Slope
    def _calculate_linreg_trend(self, price_history: List[Dict]) -> float:
        """
        Calculate trend using linear regression slope

        Args:
            price_history: List of {price, timestamp} dicts

        Returns:
            Trend percentage based on linear regression slope
        """
        if len(price_history) < 10:
            return 0.0

        try:
            prices = [float(p['price']) for p in price_history]
            n = len(prices)

            if n < 2:
                return 0.0

            # Create x values (time indices)
            x = np.arange(n)
            y = np.array(prices)

            # Fit linear regression: y = mx + b
            # Slope (m) represents trend
            if n > 1:
                # Simple linear regression
                x_mean = np.mean(x)
                y_mean = np.mean(y)

                numerator = np.sum((x - x_mean) * (y - y_mean))
                denominator = np.sum((x - x_mean) ** 2)

                if denominator == 0:
                    return 0.0

                slope = numerator / denominator

                # Convert slope to percentage trend
                # Use average price as baseline
                avg_price = y_mean
                if avg_price > 0:
                    trend_pct = (slope / avg_price) * 100 * n  # Scale by number of periods
                    return trend_pct

            return 0.0
        except Exception as e:
            logger.debug(f"Error calculating linear regression trend: {e}")
            return 0.0

    # Phase 2.4: Multi-Indicator Consensus
    def _calculate_consensus_trend(
        self,
        raw_trend: float,
        normalized_trend: float,
        ema_trend: float,
        linreg_trend: float
    ) -> float:
        """
        Calculate weighted consensus trend from multiple indicators

        Weights:
        - EMA: 40% (most responsive to recent changes)
        - LinReg: 40% (robust against spikes)
        - Normalized: 15% (volatility-adjusted)
        - Raw: 5% (baseline)

        Args:
            raw_trend: Raw percentage trend
            normalized_trend: Volatility-normalized trend
            ema_trend: EMA-based trend
            linreg_trend: Linear regression trend

        Returns:
            Weighted consensus trend percentage
        """
        try:
            # Weights for each indicator
            weight_ema = 0.40
            weight_linreg = 0.40
            weight_normalized = 0.15
            weight_raw = 0.05

            # Calculate weighted average
            consensus = (
                ema_trend * weight_ema +
                linreg_trend * weight_linreg +
                normalized_trend * weight_normalized +
                raw_trend * weight_raw
            )

            return consensus
        except Exception as e:
            logger.debug(f"Error calculating consensus trend: {e}")
            return raw_trend  # Fallback to raw trend

    # Phase 2.5: Multi-Timeframe Trend Calculation
    def _calculate_multi_timeframe_trends(self, trend: CoinTrend, current_time: float) -> None:
        """
        Calculate trends for 3 timeframes: 60m, 240m, 1440m

        Args:
            trend: CoinTrend object to update
            current_time: Current Unix timestamp
        """
        try:
            if len(trend.price_history) < 2:
                return

            current_price = float(trend.current_price)

            # Calculate trend for each timeframe
            # 60m (1 hour)
            trend_60m = self._calculate_timeframe_trend(
                trend.price_history,
                current_price,
                current_time,
                self.trend_lookback_short_minutes * 60
            )
            trend.trend_60m = trend_60m

            # 240m (4 hours)
            trend_240m = self._calculate_timeframe_trend(
                trend.price_history,
                current_price,
                current_time,
                self.trend_lookback_mid_minutes * 60
            )
            trend.trend_240m = trend_240m

            # 1440m (24 hours) - with warm-up mode support
            time_since_bot_start = current_time - self.bot_start_time
            warmup_period_seconds = self.trend_lookback_long_minutes * 60  # 24 hours

            if time_since_bot_start < warmup_period_seconds:
                # Warm-up mode: use 240m * 2 as fallback
                trend.long_trend_warmup = True
                trend.trend_1440m = trend_240m * 2.0
                logger.debug(
                    f"🔥 Warm-up mode for {trend.symbol}: "
                    f"24h trend = {trend.trend_240m:.2f}% * 2 = {trend.trend_1440m:.2f}% "
                    f"(bot running for {time_since_bot_start / 3600:.1f}h, need {warmup_period_seconds / 3600:.1f}h)"
                )
            else:
                # Normal mode: calculate real 24h trend
                trend.long_trend_warmup = False
                trend_1440m = self._calculate_timeframe_trend(
                    trend.price_history,
                    current_price,
                    current_time,
                    self.trend_lookback_long_minutes * 60
                )
                trend.trend_1440m = trend_1440m

            # Calculate composite trend score
            # Formula: 0.2 * 60m + 0.4 * 240m + 0.4 * 1440m
            trend.trend_score = (
                0.2 * trend.trend_60m +
                0.4 * trend.trend_240m +
                0.4 * trend.trend_1440m
            )

        except Exception as e:
            # CRITICAL FIX: Log error at WARNING level so we can see what's wrong
            logger.warning(f"❌ Error calculating multi-timeframe trends for {trend.symbol}: {e}")
            import traceback
            logger.warning(f"❌ Traceback: {traceback.format_exc()}")
            # Set defaults on error
            trend.trend_60m = 0.0
            trend.trend_240m = 0.0
            trend.trend_1440m = 0.0
            trend.trend_score = 0.0

    def _calculate_timeframe_trend(
        self,
        price_history: List[Dict],
        current_price: float,
        current_time: float,
        lookback_seconds: float
    ) -> float:
        """
        Calculate trend percentage for a specific timeframe

        Args:
            price_history: List of {price, timestamp} dicts
            current_price: Current price
            current_time: Current Unix timestamp
            lookback_seconds: Lookback period in seconds

        Returns:
            Trend percentage
        """
        if len(price_history) < 2:
            return 0.0

        try:
            # Find oldest price within lookback period
            cutoff_time = current_time - lookback_seconds
            relevant_history = [
                p for p in price_history
                if p['timestamp'] > cutoff_time
            ]

            if len(relevant_history) < 2:
                # Not enough data for this timeframe
                return 0.0

            # Get oldest price in the timeframe
            oldest_price = float(relevant_history[0]['price'])

            if oldest_price <= 0:
                return 0.0

            # Calculate trend percentage
            price_change = current_price - oldest_price
            trend_pct = float((price_change / oldest_price) * 100)

            return trend_pct

        except Exception as e:
            logger.debug(f"Error calculating timeframe trend: {e}")
            return 0.0
