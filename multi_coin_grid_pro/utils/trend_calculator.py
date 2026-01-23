"""
Trend Calculator

Calculates and tracks price trends for multiple coins.
Phase 2: Enhanced trend detection with volatility normalization, EMA, and linear regression.
Phase 3: Production-ready validation with OHLCV candles and output contract.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from statistics import stdev
from typing import Dict, List, Optional

import numpy as np

from hummingbot.connector.connector_base import ConnectorBase

# Liquidity proxy utilities for orderbook depth filtering
try:
    from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import (
        calculate_orderbook_depth,
        calculate_required_depth,
        get_orderbook_snapshot,
        is_sufficient_depth,
    )
    LIQUIDITY_PROXY_AVAILABLE = True
except ImportError:
    # Import may fail during standalone testing but works in bot runtime
    # Set functions to None and check at runtime instead
    calculate_orderbook_depth = None
    calculate_required_depth = None
    is_sufficient_depth = None
    get_orderbook_snapshot = None
    LIQUIDITY_PROXY_AVAILABLE = False
    # Note: This is expected when importing trend_calculator standalone
    # In production bot context, the import succeeds

logger = logging.getLogger(__name__)


def _check_liquidity_proxy_available() -> bool:
    """
    Runtime check for liquidity proxy availability.

    Import-time checks can fail when trend_calculator is imported before
    full Hummingbot environment is loaded. This function checks at runtime.

    Returns:
        True if liquidity proxy functions are available, False otherwise
    """
    global calculate_orderbook_depth, calculate_required_depth
    global is_sufficient_depth, get_orderbook_snapshot

    # If import-time check succeeded, we're good
    if LIQUIDITY_PROXY_AVAILABLE:
        return True

    # If import-time failed, try importing again at runtime
    try:
        from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import (
            calculate_orderbook_depth as _calc_depth,
            calculate_required_depth as _req_depth,
            get_orderbook_snapshot as _get_snapshot,
            is_sufficient_depth as _is_sufficient,
        )

        # Update global references
        calculate_orderbook_depth = _calc_depth
        calculate_required_depth = _req_depth
        is_sufficient_depth = _is_sufficient
        get_orderbook_snapshot = _get_snapshot
        return True
    except ImportError:
        return False


# ============================================================================
# CONSTANTS - Production-Ready Thresholds
# ============================================================================

MIN_TREND_THRESHOLD = 0.5  # Minimum +0.5% trend_score required for selection
MIN_CANDLES_FOR_WARMUP = 360  # Minimum 360 candles (30h × 60/5m) for valid trends
TARGET_HISTORICAL_CANDLES = 720  # Target 720 candles (60h) for full history


# ============================================================================
# ENUMS - Trend Status
# ============================================================================

class TrendStatus(str, Enum):
    """Trend validation status"""
    WARMUP = "WARMUP"  # Insufficient data (< 360 candles)
    BEARISH = "BEARISH"  # Trend score < MIN_TREND_THRESHOLD
    SIDEWAYS = "SIDEWAYS"  # Trend score between -0.5% and +0.5%
    BULLISH = "BULLISH"  # Trend score >= MIN_TREND_THRESHOLD


@dataclass
class CandleData:
    """
    Single 5-minute OHLCV candle data.
    Used for SmartEntryFilter indicator calculations.
    """
    timestamp: float      # Unix timestamp in seconds
    open: Decimal         # Open price
    high: Decimal         # High price
    low: Decimal          # Low price
    close: Decimal        # Close price
    volume: Decimal       # Volume
    vwap: Optional[Decimal] = None  # VWAP (optional, added for EPIC v3.4 momentum indicators)


@dataclass
class TrendSelection:
    """
    Output contract for trend validation and selection.

    Attributes:
        symbol: Trading pair symbol
        trend_1h: 1-hour trend percentage
        trend_4h: 4-hour trend percentage
        trend_24h: 24-hour trend percentage
        trend_score_pct: Composite trend score (weighted average)
        passes: True if trend passes MIN_TREND_THRESHOLD
        status: Trend status (WARMUP, BEARISH, SIDEWAYS, BULLISH)
        candle_count: Number of candles available
        consensus_pct: Multi-indicator consensus trend
        volatility: Current volatility (std dev)
    """
    symbol: str
    trend_1h: float
    trend_4h: float
    trend_24h: float
    trend_score_pct: float
    passes: bool
    status: TrendStatus
    candle_count: int
    consensus_pct: float = 0.0
    volatility: float = 0.0


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
        price_history: List of {price, timestamp} dicts (LEGACY - kept for compatibility)
        candles: List of CandleData (NEW - full OHLCV for SmartEntry indicators)
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
    price_history: List[Dict] = field(default_factory=list)  # LEGACY compatibility
    candles: List[CandleData] = field(default_factory=list)  # NEW: Full OHLCV
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

    @property
    def candle_count(self) -> int:
        """Get number of OHLCV candles available"""
        return len(self.candles)

    @property
    def is_warmup(self) -> bool:
        """Check if coin is in warmup mode (< 360 candles)"""
        return self.candle_count < MIN_CANDLES_FOR_WARMUP


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
        base_connector: Optional[ConnectorBase] = None,
        data_freshness_callback: Optional[callable] = None
    ):
        """
        Initialize trend calculator

        Args:
            connector: Exchange connector (paper trading connector for paper trading mode)
            lookback_minutes: How many minutes of history to track (legacy, kept for compatibility)
            bot_start_time: Unix timestamp of bot startup (for warm-up mode detection)
            base_connector: Base connector for price fetching in paper trading mode (optional)
            data_freshness_callback: Optional callback to mark data as fresh (Task 2.1.1)
        """
        self.connector = connector
        self.base_connector = base_connector  # Base connector for price fetching in paper trading
        self.data_freshness_callback = data_freshness_callback  # Task 2.1.1: Stale detection hook

        # CRITICAL FIX: FORCE CORRECT VALUE - This runs EVERY time __init__ is called!
        # Even if old bytecode is cached, this will execute during object creation
        _correct_lookback = 65 * 3600  # 234000 seconds = 65 hours
        self.lookback_seconds = _correct_lookback

        self.trends: Dict[str, CoinTrend] = {}
        # Phase 2.5: Multi-timeframe support
        self.bot_start_time = bot_start_time if bot_start_time else time.time()
        self.trend_lookback_short_minutes = 60  # 1 hour
        self.trend_lookback_mid_minutes = 240  # 4 hours
        self.trend_lookback_long_minutes = 1440  # 24 hours
        self._historical_data_loaded = False  # Track if we've loaded historical data

    async def load_historical_data(self, symbols: List[str]) -> None:
        """
        Load historical OHLCV data from Kraken for all symbols.
        This allows us to calculate accurate 24h trends from the start!

        Args:
            symbols: List of trading pairs to load historical data for (e.g., ["XRP-EUR", "SOL-EUR"])
        """
        # 🔧 FIX: Check per-coin CANDLES (not price_history)!
        # SmartEntry v2 requires trend.candles >= 14, so we check candles count
        min_candles_required = 14  # SmartEntry v2 minimum
        symbols_to_load = [
            s for s in symbols
            if s not in self.trends
            or not self.trends[s].candles
            or len(self.trends[s].candles) < min_candles_required
        ]

        if not symbols_to_load:
            logger.info(f"📊 All {len(symbols)} coins already have historical data, skipping...")
            return

        if len(symbols_to_load) < len(symbols):
            logger.info(f"📊 Partial load: {len(symbols_to_load)}/{len(symbols)} coins need data (others already loaded)")

        try:
            import ccxt

            # Detect exchange from connector
            exchange_name = self.connector.name.replace("_paper_trade", "")
            logger.info(f"📥 Loading historical data for {len(symbols_to_load)} coins from {exchange_name}...")

            # Create ccxt exchange instance dynamically
            exchange_class = getattr(ccxt, exchange_name, None)
            if not exchange_class:
                logger.error(f"❌ Unsupported exchange for historical data: {exchange_name}")
                return

            exchange = exchange_class()

            # Calculate timeframe: get 30 hours of data (buffer for 5m candles)
            since_ms = int((time.time() - (30 * 3600)) * 1000)  # 30 hours ago

            successful_loads = 0
            failed_loads = []

            for symbol in symbols_to_load:  # 🔧 FIX: Use filtered list
                try:
                    # Convert XRP-EUR to XRP/EUR format for ccxt
                    ccxt_symbol = symbol.replace("-", "/")

                    # Fetch 5-minute OHLCV data (limit = 720 candles max!)
                    # Supported timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d
                    # 720 candles × 5 min = 3600 min = 60 hours ✅ (covers 24h + buffer)
                    logger.debug(f"  Fetching {ccxt_symbol} OHLCV data...")
                    ohlcv = exchange.fetch_ohlcv(
                        symbol=ccxt_symbol,
                        timeframe='5m',  # 5-minute candles (gives 60h coverage)
                        since=since_ms,
                        limit=720  # Max 720 candles = 60 hours of data
                    )

                    if not ohlcv:
                        logger.warning(f"  ⚠️  No historical data for {symbol}")
                        failed_loads.append(symbol)
                        continue

                    # Initialize trend object if not exists
                    if symbol not in self.trends:
                        self.trends[symbol] = CoinTrend(symbol=symbol)

                    trend = self.trends[symbol]

                    # Convert OHLCV to CandleData format (NEW: full OHLCV storage)
                    # OHLCV format: [timestamp_ms, open, high, low, close, volume]
                    candles = []
                    price_history = []  # Keep legacy format for compatibility

                    for candle in ohlcv:
                        timestamp_ms = candle[0]
                        timestamp_sec = timestamp_ms / 1000.0

                        # NEW: Store full OHLCV in CandleData
                        candle_data = CandleData(
                            timestamp=timestamp_sec,
                            open=Decimal(str(candle[1])),
                            high=Decimal(str(candle[2])),
                            low=Decimal(str(candle[3])),
                            close=Decimal(str(candle[4])),
                            volume=Decimal(str(candle[5]))
                        )
                        candles.append(candle_data)

                        # LEGACY: Keep price_history for backward compatibility
                        price_history.append({
                            "price": candle_data.close,
                            "timestamp": timestamp_sec
                        })

                    # Set both candles (new) and price_history (legacy)
                    trend.candles = candles
                    trend.price_history = price_history
                    trend.current_price = candles[-1].close if candles else Decimal("0")
                    trend.last_updated = time.time()

                    successful_loads += 1
                    logger.info(
                        f"  ✅ {symbol}: Loaded {len(price_history)} historical prices "
                        f"(oldest: {time.strftime('%H:%M', time.localtime(price_history[0]['timestamp']))} → "
                        f"latest: {time.strftime('%H:%M', time.localtime(price_history[-1]['timestamp']))})"
                    )

                    # Small delay to avoid rate limits
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(f"  ❌ Failed to load {symbol}: {e}")
                    failed_loads.append(symbol)
                    continue

            self._historical_data_loaded = True

            logger.info(
                f"📊 Historical data loading complete: "
                f"{successful_loads}/{len(symbols)} successful"
            )

            if failed_loads:
                logger.warning(f"⚠️  Failed to load: {', '.join(failed_loads)}")

            # DEBUG: Log actual data loaded for verification
            for symbol in symbols[:3]:  # First 3 coins for debugging
                if symbol in self.trends:
                    trend = self.trends[symbol]
                    if len(trend.price_history) > 1:
                        first_price = float(trend.price_history[0]['price'])
                        last_price = float(trend.price_history[-1]['price'])
                        change = ((last_price - first_price) / first_price) * 100 if first_price > 0 else 0
                        currency = self._get_currency_symbol(symbol)
                        logger.info(
                            f"  🔍 {symbol}: {len(trend.price_history)} points, "
                            f"first={currency}{first_price:.4f}, last={currency}{last_price:.4f}, change={change:+.2f}%"
                        )

            # Log summary
            logger.info(
                "🎯 Ready for accurate 24h trends! No more warm-up mode needed! ✅"
            )

        except Exception as e:
            logger.error(f"❌ Error loading historical data: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

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
                            # Task 2.1.1: Mark data as fresh
                            if self.data_freshness_callback:
                                self.data_freshness_callback(symbol, "price")
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

            # Update OHLCV candles (new)
            if trend.candles:
                # Get last candle timestamp (5-minute aligned)
                last_candle = trend.candles[-1]
                last_candle_start = int(last_candle.timestamp / 300) * 300  # Floor to 5-min boundary
                current_candle_start = int(current_time / 300) * 300

                # If same 5-minute window, update last candle (update high/low/close)
                if current_candle_start == last_candle_start:
                    last_candle.high = max(last_candle.high, price)
                    last_candle.low = min(last_candle.low, price)
                    last_candle.close = price
                    # Volume update not possible (no real-time volume from ticker)
                else:
                    # New 5-minute candle - create new one
                    new_candle = CandleData(
                        timestamp=current_candle_start,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=Decimal("0")  # Unknown volume from ticker
                    )
                    trend.candles.append(new_candle)

                    # Remove old candles (keep last 720 = 60 hours)
                    if len(trend.candles) > 720:
                        trend.candles = trend.candles[-720:]
            else:
                # CRITICAL FIX: Initialize first candle if empty (e.g., after dynamic discovery)
                # Without this, candle_count stays 0 forever and SmartEntry always rejects with WARMUP
                current_candle_start = int(current_time / 300) * 300  # Floor to 5-min boundary
                first_candle = CandleData(
                    timestamp=current_candle_start,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=Decimal("0")
                )
                trend.candles.append(first_candle)

            # Add to price history (LEGACY)
            prev_price_value = Decimal(str(trend.price_history[-1]['price'])) if trend.price_history else price
            high = max(price, prev_price_value)
            low = min(price, prev_price_value)
            trend.price_history.append({
                'price': price,
                'timestamp': current_time,
                'high': high,
                'low': low,
            })

            # Remove old data points (LEGACY)
            cutoff_time = current_time - self.lookback_seconds
            trend.price_history = [
                p for p in trend.price_history
                if p['timestamp'] > cutoff_time
            ]

            # Calculate trend if we have enough data
            if len(trend.price_history) >= 2:
                oldest_price = Decimal(str(trend.price_history[0]['price']))  # Keep as Decimal
                price_change = price - oldest_price
                trend.trend_pct = float(price_change / oldest_price * Decimal("100")) if oldest_price > 0 else 0.0

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

    def _get_currency_symbol(self, symbol: str) -> str:
        """Get currency symbol based on quote asset in trading pair"""
        if symbol.endswith("-USD") or symbol.endswith("/USD"):
            return "$"
        elif symbol.endswith("-USDT") or symbol.endswith("/USDT"):
            return "$"
        elif symbol.endswith("-USDC") or symbol.endswith("/USDC"):
            return "$"
        else:
            return "€"  # EUR or other

    def _log_trend_update(self, trend: CoinTrend) -> None:
        """Helper method to log trend update"""
        trend_emoji = "📈" if trend.trend_pct >= 0 else "📉"
        data_status = f"{len(trend.price_history)}/{int(self.lookback_seconds / 30)} points"
        currency = self._get_currency_symbol(trend.symbol)

        # Phase 2: Show enhanced trend metrics
        if trend.consensus_trend_pct != 0.0:
            logger.info(
                f"{trend_emoji} {trend.symbol:12} | "
                f"{currency}{trend.current_price:8.4f} | "
                f"Raw: {trend.trend_pct:+6.2f}% | "
                f"Consensus: {trend.consensus_trend_pct:+6.2f}% | "
                f"Vol: {trend.volatility:.3f}% | "
                f"Data: {data_status}"
            )
        else:
            logger.info(
                f"{trend_emoji} {trend.symbol:12} | "
                f"{currency}{trend.current_price:8.4f} | "
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
            # Convert price to Decimal for consistent arithmetic
            price = Decimal(str(price))

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

            # Update OHLCV candles (new)
            if trend.candles:
                # Get last candle timestamp (5-minute aligned)
                last_candle = trend.candles[-1]
                last_candle_start = int(last_candle.timestamp / 300) * 300  # Floor to 5-min boundary
                current_candle_start = int(current_time / 300) * 300

                # If same 5-minute window, update last candle (update high/low/close)
                if current_candle_start == last_candle_start:
                    last_candle.high = max(last_candle.high, price)
                    last_candle.low = min(last_candle.low, price)
                    last_candle.close = price
                    # Volume update not possible (no real-time volume from ticker)
                else:
                    # New 5-minute candle - create new one
                    new_candle = CandleData(
                        timestamp=current_candle_start,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=Decimal("0")  # Unknown volume from ticker
                    )
                    trend.candles.append(new_candle)

                    # Remove old candles (keep last 720 = 60 hours)
                    if len(trend.candles) > 720:
                        trend.candles = trend.candles[-720:]
            else:
                # CRITICAL FIX: Initialize first candle if empty (e.g., after dynamic discovery)
                # Without this, candle_count stays 0 forever and SmartEntry always rejects with WARMUP
                current_candle_start = int(current_time / 300) * 300  # Floor to 5-min boundary
                first_candle = CandleData(
                    timestamp=current_candle_start,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=Decimal("0")
                )
                trend.candles.append(first_candle)

            # Add to price history (LEGACY)
            prev_price_value = Decimal(str(trend.price_history[-1]['price'])) if trend.price_history else price
            high = max(price, prev_price_value)
            low = min(price, prev_price_value)
            trend.price_history.append({
                'price': price,
                'timestamp': current_time,
                'high': high,
                'low': low,
            })

            # Remove old data points (LEGACY)
            cutoff_time = current_time - self.lookback_seconds
            trend.price_history = [
                p for p in trend.price_history
                if p['timestamp'] > cutoff_time
            ]

            # Calculate trend if we have enough data
            if len(trend.price_history) >= 2:
                oldest_price = Decimal(str(trend.price_history[0]['price']))  # Keep as Decimal
                price_change = price - oldest_price
                trend.trend_pct = float(price_change / oldest_price * Decimal("100")) if oldest_price > 0 else 0.0

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

    async def update_all_trends_v2(
            self, symbols: List[str], retry_on_failure: bool = True,
            orderbook_config: Optional[dict] = None) -> None:
        """
        Batch update all trends using efficient batch API call.
        Falls back to individual API calls if batch fails.

        Args:
            symbols: List of trading pairs to update (e.g. ['BTC-EUR', 'ETH-EUR'])
            retry_on_failure: Whether to retry failed updates after a delay (default: True)
            orderbook_config: Optional dict for Phase 2 early depth filtering:
                - enabled: bool
                - mode: str ('shadow', 'ranking', 'early')
                - depth_pct_range: float
                - depth_levels: int
                - min_depth_multiplier: float
                - order_size: Decimal
        """
        # Convert all symbols from / to - format (Kraken uses - format)
        converted_symbols = [s.replace("/", "-") if "/" in s else s for s in symbols]

        # === PHASE 2: EARLY DEPTH FILTERING ===
        # Pre-filter coins by liquidity BEFORE expensive trend calculation
        depth_filtered_symbols = converted_symbols
        if orderbook_config and _check_liquidity_proxy_available():
            mode = orderbook_config.get('mode', 'ranking')
            enabled = orderbook_config.get('enabled', False)

            if enabled and mode == 'early':
                # Early mode: Pre-filter coins BEFORE trend updates
                # NOTE: Disabled - orderbook data not reliably available in trend update loop
                # Depth filtering moved to SmartEntry phase where orderbook is cached
                logger.info(
                    "⚠️ Early mode enabled but depth filtering skipped - "
                    "orderbook data not available in trend update loop. "
                    "Depth filtering happens in SmartEntry phase instead."
                )
                depth_filtered_symbols = converted_symbols
            elif enabled and mode == 'shadow':
                # Shadow mode: Check depth but DON'T filter (log only)
                depth_pct_range = orderbook_config.get('depth_pct_range', 0.5)
                depth_levels = orderbook_config.get('depth_levels', 10)
                min_depth_multiplier = orderbook_config.get('min_depth_multiplier', 5.0)
                order_size = orderbook_config.get('order_size')

                if order_size:
                    required_depth = calculate_required_depth(
                        order_size_quote=Decimal(str(order_size)),
                        multiplier=min_depth_multiplier
                    )

                    logger.info(
                        f"👻 Shadow Mode: Testing depth filtering (would require €{required_depth:.2f}) "
                        f"- NO actual filtering"
                    )

                    would_pass = 0
                    would_fail = 0

                    for symbol in converted_symbols[:5]:  # Test first 5 only for performance
                        try:
                            orderbook = await get_orderbook_snapshot(
                                connector=self.connector,
                                symbol=symbol,
                                depth_levels=depth_levels
                            )

                            if orderbook:
                                bid_depth, ask_depth = calculate_orderbook_depth(
                                    orderbook=orderbook,
                                    pct_range=depth_pct_range,
                                    quote_currency='EUR'
                                )

                                if is_sufficient_depth(bid_depth, ask_depth, required_depth):
                                    would_pass += 1
                                    logger.info(f"✅ Shadow: {symbol} would PASS (bid: €{bid_depth:.2f}, ask: €{ask_depth:.2f})")
                                else:
                                    would_fail += 1
                                    logger.info(f"❌ Shadow: {symbol} would FAIL (bid: €{bid_depth:.2f}, ask: €{ask_depth:.2f})")
                        except Exception as e:
                            logger.debug(f"Shadow check error for {symbol}: {e}")

                    logger.info(f"👻 Shadow Mode: {would_pass}/{would_pass + would_fail} would pass depth check")

        converted_symbols = depth_filtered_symbols  # Use filtered list
        # === END PHASE 2 ===

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
            logger.debug(
                f"⏳ Rate limiting: Waiting {
                    wait_time:.2f}s before batch API call (last call was {
                    time_since_last_call:.2f}s ago)")
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
                    logger.info(
                        f"🔄 Attempting batch API call via base connector for {
                            len(converted_symbols)} symbols...")
                    prices_dict = await self.base_connector.get_last_traded_prices(converted_symbols)
                    batch_call_success = True
                    logger.info(
                        f"✅ Base connector batch API call successful: {len(prices_dict)}/{len(converted_symbols)} prices retrieved")  # noqa: E501
                except Exception as e:
                    logger.warning(f"⚠️  Base connector batch fetch failed: {e}")
                    prices_dict = {}
        except Exception as e:
            # Catch any other exceptions (e.g., rate limit errors, network errors)
            logger.warning(f"⚠️  Batch API call failed with exception: {type(e).__name__}: {e}")
            prices_dict = {}

        # If batch call failed or returned empty, fall back to individual calls with rate limiting
        if not batch_call_success or not prices_dict or len(prices_dict) < len(
                converted_symbols) * 0.5:  # If less than 50% success
            # Fallback: individual calls with rate limiting
            # IMPORTANT: Use direct price fetching instead of update_coin_trend to avoid nested API calls
            # Increased from 1.1 to 1.5 seconds between API calls to be safer (Kraken allows 1 call per second)
            RATE_LIMIT_DELAY = 1.5

            if batch_call_attempted:
                logger.warning(
                    f"⚠️  Batch call incomplete ({
                        len(prices_dict)}/{
                        len(converted_symbols)}), falling back to individual calls with rate limiting...")
                logger.warning(
                    f"⚠️  This will make {
                        len(converted_symbols)} API calls with {RATE_LIMIT_DELAY}s delay = ~{
                        len(converted_symbols)
                        * RATE_LIMIT_DELAY:.1f}s total")
            else:
                logger.info(f"🔄 Using individual API calls with rate limiting for {len(converted_symbols)} symbols...")

            # CRITICAL: Add delay BEFORE first call to avoid hitting rate limit immediately
            await asyncio.sleep(RATE_LIMIT_DELAY)

            successful_updates = 0
            failed_updates = []

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
                            successful_updates += 1
                        else:
                            failed_updates.append(f"{symbol}:no_trend")
                    else:
                        logger.warning(f"⚠️  No price data for {symbol} in fallback mode (price={price})")
                        failed_updates.append(f"{symbol}:no_price")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to fetch price for {symbol} in fallback: {e}")
                    failed_updates.append(f"{symbol}:{type(e).__name__}")
                    continue
            # Log fallback results
            logger.info(
                f"✅ Fallback complete: {successful_updates}/{len(converted_symbols)} trends updated successfully")
            if failed_updates:
                logger.warning(f"❌ Failed updates: {', '.join(failed_updates[:10])}" + (
                    f" (+{len(failed_updates) - 10} more)" if len(failed_updates) > 10 else ""))
        else:
            # Batch mode: update all trends using fetched prices
            logger.info(f"✅ Batch mode: updating {len(prices_dict)} trends using batch-fetched prices")

            successful_updates = 0
            failed_updates = []

            # DEBUG: Log which coins got prices vs which didn't
            debug_coins = ['MON-EUR', 'AVAX-EUR', 'TAO-EUR', 'TRX-EUR']
            for dc in debug_coins:
                if dc in converted_symbols:
                    price = prices_dict.get(dc)
                    logger.warning(
                        f"🔍 DEBUG {dc}: price_in_dict={price}, dict_keys_sample={
                            list(
                                prices_dict.keys())[
                                :5]}")

            for symbol in converted_symbols:
                price = prices_dict.get(symbol)
                if price is None or price == 0:
                    logger.debug(f"No price data for {symbol} in batch response")
                    failed_updates.append(f"{symbol}:no_price_in_batch")
                    continue

                # Update trend using the batch-fetched price
                try:
                    trend = await self._update_coin_trend_with_price(symbol, float(price))
                    if trend:
                        self._log_trend_update(trend)
                        successful_updates += 1
                    else:
                        failed_updates.append(f"{symbol}:no_trend")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to update trend for {symbol}: {e}")
                    failed_updates.append(f"{symbol}:{type(e).__name__}")

            # Log batch results summary
            logger.info(
                f"✅ Batch update complete: {successful_updates}/{len(converted_symbols)} trends updated successfully")
            if failed_updates:
                logger.warning(f"❌ Failed batch updates ({len(failed_updates)}): {', '.join(failed_updates[:5])}" + (
                    f" (+{len(failed_updates) - 5} more)" if len(failed_updates) > 5 else ""))

                # If most updates failed and retry is enabled, try one more time after a delay
                failure_rate = len(failed_updates) / len(converted_symbols)
                if retry_on_failure and failure_rate > 0.5 and successful_updates < 5:
                    logger.warning(f"⚠️ High failure rate ({failure_rate:.0%}), retrying after 2s delay...")
                    await asyncio.sleep(2.0)
                    # Retry only the failed symbols (without retry flag to prevent infinite loop)
                    failed_symbols = [f.split(':')[0] for f in failed_updates if ':' in f]
                    if failed_symbols:
                        logger.info(f"🔄 Retrying {len(failed_symbols)} failed symbols...")
                        await self.update_all_trends_v2(failed_symbols, retry_on_failure=False)

    def get_best_coin(self, min_trend_pct: float, exclude_coins: Optional[List[str]] = None,
                      orderbook_config: Optional[dict] = None) -> Optional[str]:
        """
        Find coin with best (highest) trend, filtered by orderbook depth

        Args:
            min_trend_pct: Minimum trend percentage required
            exclude_coins: Optional list of coin symbols to exclude from selection
            orderbook_config: Optional dict with depth filtering config:
                - enabled: bool (default True if provided)
                - mode: str ('shadow', 'ranking', 'early') - default 'ranking'
                  * 'shadow': Log depth checks but DON'T filter (test mode)
                  * 'ranking': Filter HERE during coin selection (Phase 1 behavior)
                  * 'early': Filter in update_all_trends_v2() BEFORE trend calc (Phase 2 optimization)
                - depth_pct_range: float (default 0.5)
                - depth_levels: int (default 10)
                - min_depth_multiplier: float (default 5.0)
                - order_size: Decimal (required if enabled)

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

        # Parse orderbook config with mode support
        depth_filtering_enabled = False
        shadow_mode = False
        if orderbook_config and _check_liquidity_proxy_available():
            enabled = orderbook_config.get('enabled', True)
            mode = orderbook_config.get('mode', 'ranking')

            # Determine if we should filter here
            if mode == 'shadow':
                shadow_mode = True  # Log only, don't filter
                depth_filtering_enabled = False
            elif mode == 'ranking':
                depth_filtering_enabled = enabled  # Filter here (Phase 1 behavior)
            elif mode == 'early':
                depth_filtering_enabled = False  # Already filtered in update_all_trends_v2()
                logger.debug("Mode='early': depth filtering already done in update loop, skipping here")

            depth_pct_range = orderbook_config.get('depth_pct_range', 0.5)
            depth_levels = orderbook_config.get('depth_levels', 10)
            min_depth_multiplier = orderbook_config.get('min_depth_multiplier', 5.0)
            order_size = orderbook_config.get('order_size')

            if not order_size and (depth_filtering_enabled or shadow_mode):
                logger.warning("⚠️ Orderbook config missing 'order_size', disabling depth filtering")
                depth_filtering_enabled = False
                shadow_mode = False
        elif orderbook_config and not _check_liquidity_proxy_available():
            logger.warning("⚠️ Liquidity proxy not available, disabling depth filtering")

        # Set of coins to exclude (for fast lookup)
        exclude_set = set(exclude_coins) if exclude_coins else set()

        best_symbol = None
        best_trend = min_trend_pct

        # Track all trends for debugging
        all_trends = []
        depth_filtered_count = 0

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

            # DEPTH PRE-FILTER (Phase 1 + Shadow Mode Support)
            if depth_filtering_enabled or shadow_mode:
                try:
                    # Get orderbook snapshot
                    orderbook = get_orderbook_snapshot(self.connector, symbol)
                    if not orderbook or not orderbook.snapshot_uid:
                        # ✅ PRO RULE: Unknown data NEVER blocks, only confirmed illiquidity blocks
                        if shadow_mode:
                            logger.info(f"👻 Shadow: {symbol} - No orderbook data (would skip if filtering)")
                        elif depth_filtering_enabled:
                            logger.debug(f"⚠️  {symbol}: No orderbook data (UNKNOWN ≠ ILLIQUID) - allowing entry")
                            # Don't block - unknown is not the same as illiquid
                        # Continue to normal evaluation (fall through)

                    else:
                        # We have orderbook data - check if depth is sufficient
                        # Calculate depth metrics
                        depth_metrics = calculate_orderbook_depth(
                            bids=orderbook.bids,
                            asks=orderbook.asks,
                            mid_price=orderbook.bids[0].price if orderbook.bids else Decimal("0"),
                            pct_range=depth_pct_range,
                            max_levels=depth_levels
                        )

                        # Check if depth is sufficient
                        required_depth = calculate_required_depth(
                            order_size_quote=order_size,
                            multiplier=min_depth_multiplier
                        )

                        depth_sufficient = is_sufficient_depth(depth_metrics, required_depth, tolerance=0.1)

                    if shadow_mode:
                        # Shadow mode: LOG but don't filter
                        if depth_sufficient:
                            logger.info(
                                f"✅ Shadow: {symbol} would PASS "
                                f"(bid: €{depth_metrics.bid_depth:.2f}, ask: €{depth_metrics.ask_depth:.2f} >= €{required_depth:.2f})"
                            )
                        else:
                            logger.info(
                                f"❌ Shadow: {symbol} would FAIL "
                                f"(bid: €{depth_metrics.bid_depth:.2f}, ask: €{depth_metrics.ask_depth:.2f} < €{required_depth:.2f}) "
                                f"- but NOT filtering (shadow mode)"
                            )
                    elif depth_filtering_enabled:
                        # Ranking mode: Actually filter
                        if not depth_sufficient:
                            logger.info(
                                f"🚫 {symbol}: Insufficient depth "
                                f"(available={depth_metrics.bid_depth:.1f}, "
                                f"required={required_depth:.1f}) - SKIPPED"
                            )
                            depth_filtered_count += 1
                            continue
                        else:
                            logger.debug(
                                f"✅ {symbol}: Sufficient depth "
                                f"(available={depth_metrics.bid_depth:.1f}, "
                                f"required={required_depth:.1f})"
                            )

                except Exception as e:
                    if shadow_mode:
                        logger.info(f"👻 Shadow: {symbol} - Depth check error ({e})")
                    else:
                        logger.warning(f"⚠️ {symbol}: Depth check failed ({e}), allowing through")
                    # Don't filter on errors - let SmartEntry handle it

            # SIMPLIFIED: Just use consensus_trend_pct directly (always in percentage format like 7.98 for 7.98%)
            # No need for complex multi-timeframe checks - consensus is already the best metric
            trend_value = trend.consensus_trend_pct

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

        # Log depth filtering stats
        if depth_filtering_enabled and depth_filtered_count > 0:
            logger.info(
                f"🔍 Depth filtering: {depth_filtered_count} coins filtered out "
                f"({len(all_trends)} liquid coins remain)"
            )
            self._debug_info['depth_filtered'] = depth_filtered_count

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

    def get_top_n_coins(self, n: int, min_trend_pct: float, exclude_coins: Optional[List[str]] = None,
                        orderbook_config: Optional[dict] = None) -> List[str]:
        """
        Find top N coins with best (highest) trends, filtered by orderbook depth

        Args:
            n: Number of top coins to return
            min_trend_pct: Minimum trend percentage required
            exclude_coins: Optional list of coin symbols to exclude from selection
            orderbook_config: Optional dict with depth filtering config:
                - enabled: bool (default True if provided)
                - mode: str ('shadow', 'ranking', 'early') - default 'ranking'
                - depth_pct_range: float (default 0.5)
                - depth_levels: int (default 10)
                - min_depth_multiplier: float (default 5.0)
                - order_size: Decimal (required if enabled)

        Returns:
            List of symbols for top N coins, or empty list if no coins meet criteria
        """
        # Parse orderbook config with mode support
        depth_filtering_enabled = False
        shadow_mode = False
        if orderbook_config and _check_liquidity_proxy_available():
            enabled = orderbook_config.get('enabled', True)
            mode = orderbook_config.get('mode', 'ranking')

            # Determine if we should filter here
            if mode == 'shadow':
                shadow_mode = True  # Log only, don't filter
                depth_filtering_enabled = False
            elif mode == 'ranking':
                depth_filtering_enabled = enabled  # Filter here (Phase 1 behavior)
            elif mode == 'early':
                depth_filtering_enabled = False  # Already filtered in update_all_trends_v2()
                logger.debug("Mode='early': depth filtering already done in update loop, skipping here")

            depth_pct_range = orderbook_config.get('depth_pct_range', 0.5)
            depth_levels = orderbook_config.get('depth_levels', 10)
            min_depth_multiplier = orderbook_config.get('min_depth_multiplier', 5.0)
            order_size = orderbook_config.get('order_size')

            if not order_size and (depth_filtering_enabled or shadow_mode):
                logger.warning("⚠️ Orderbook config missing 'order_size', disabling depth filtering")
                depth_filtering_enabled = False
                shadow_mode = False
        elif orderbook_config and not _check_liquidity_proxy_available():
            logger.warning("⚠️ Liquidity proxy not available, disabling depth filtering")

        # Set of coins to exclude (for fast lookup)
        exclude_set = set(exclude_coins) if exclude_coins else set()

        # Collect all qualifying coins with their trends
        qualifying_coins = []
        all_coins = []  # Track ALL coins for fallback purposes
        depth_filtered_count = 0

        for symbol, trend in self.trends.items():
            # Skip excluded coins (e.g., coins in cooldown or already active)
            if symbol in exclude_set:
                continue

            # Skip coins without sufficient data
            if not trend.has_sufficient_data:
                continue

            # DEPTH PRE-FILTER (Phase 1 + Shadow Mode Support)
            if depth_filtering_enabled or shadow_mode:
                try:
                    # Get orderbook snapshot
                    orderbook = get_orderbook_snapshot(self.connector, symbol)
                    if not orderbook or not orderbook.snapshot_uid:
                        # ✅ PRO RULE: Unknown data NEVER blocks, only confirmed illiquidity blocks
                        if shadow_mode:
                            logger.info(f"👻 Shadow: {symbol} - No orderbook data (would skip if filtering)")
                        elif depth_filtering_enabled:
                            logger.debug(f"⚠️  {symbol}: No orderbook data (UNKNOWN ≠ ILLIQUID) - allowing entry")
                            # Don't block - unknown is not the same as illiquid
                        # Continue to normal evaluation (fall through)

                    else:
                        # We have orderbook data - check if depth is sufficient
                        # Calculate depth metrics
                        depth_metrics = calculate_orderbook_depth(
                            bids=orderbook.bids,
                            asks=orderbook.asks,
                            mid_price=orderbook.bids[0].price if orderbook.bids else Decimal("0"),
                            pct_range=depth_pct_range,
                            max_levels=depth_levels
                        )

                        # Check if depth is sufficient
                        required_depth = calculate_required_depth(
                            order_size_quote=order_size,
                            multiplier=min_depth_multiplier
                        )

                        depth_sufficient = is_sufficient_depth(depth_metrics, required_depth, tolerance=0.1)

                    if shadow_mode:
                        # Shadow mode: LOG but don't filter (only log first 3 for performance)
                        if len(qualifying_coins) < 3:
                            if depth_sufficient:
                                logger.info(
                                    f"✅ Shadow: {symbol} would PASS "
                                    f"(bid: €{depth_metrics.bid_depth:.2f} >= €{required_depth:.2f})"
                                )
                            else:
                                logger.info(
                                    f"❌ Shadow: {symbol} would FAIL "
                                    f"(bid: €{depth_metrics.bid_depth:.2f} < €{required_depth:.2f}) "
                                    f"- but NOT filtering"
                                )
                    elif depth_filtering_enabled:
                        # Ranking mode: Actually filter
                        if not depth_sufficient:
                            logger.debug(
                                f"🚫 {symbol}: Insufficient depth "
                                f"(available={depth_metrics.bid_depth:.1f}, "
                                f"required={required_depth:.1f}) - SKIPPED"
                            )
                            depth_filtered_count += 1
                            continue

                except Exception as e:
                    if shadow_mode:
                        logger.debug(f"👻 Shadow: {symbol} - Depth check error ({e})")
                    else:
                        logger.warning(f"⚠️ {symbol}: Depth check failed ({e}), allowing through")
                    # Don't filter on errors - let SmartEntry handle it

            # SIMPLIFIED: Just use consensus_trend_pct directly (always in percentage format like 7.98 for 7.98%)
            # No need for complex multi-timeframe checks - consensus is already the best metric
            trend_value = trend.consensus_trend_pct

            # Store ALL coins for fallback (even if below min_trend)
            all_coins.append((symbol, trend_value))

            # DEBUG: Log first 5 coins to see what's happening
            if len(qualifying_coins) < 5:
                logger.info(
                    f"🔍 DEBUG {symbol}: consensus={trend.consensus_trend_pct:.4f}%, "
                    f"min_req={min_trend_pct:.4f}%, passes={trend_value >= min_trend_pct}"
                )

            # Only include coins that meet minimum trend requirement
            if trend_value >= min_trend_pct:
                qualifying_coins.append((symbol, trend_value))

        # Sort both lists by trend strength (descending)
        qualifying_coins.sort(key=lambda x: x[1], reverse=True)
        all_coins.sort(key=lambda x: x[1], reverse=True)
        top_n = qualifying_coins[:n]

        # Log depth filtering stats
        if depth_filtering_enabled and depth_filtered_count > 0:
            logger.info(
                f"🔍 Depth filtering: {depth_filtered_count} coins filtered out "
                f"({len(qualifying_coins)} liquid coins remain)"
            )

        # Log selection
        if top_n:
            logger.info(f"\n🔝 TOP {len(top_n)} COINS (requested {n}):")
            for idx, (symbol, trend) in enumerate(top_n, 1):
                logger.info(f"  {idx}. {symbol}: {trend:+.3f}%")
        else:
            logger.info(f"\n⚠️  NO COINS MEET MINIMUM TREND ({min_trend_pct}%)")

        # Store debug info (compatible with existing controller logging)
        self._debug_info = {
            'total': len(self.trends),
            'sufficient': sum(1 for t in self.trends.values() if t.has_sufficient_data),
            'min_trend': min_trend_pct,
            'all_count': len(qualifying_coins),
            'top_10': all_coins[:10],  # Use ALL coins (not just qualifying) for fallback
            'depth_filtered': depth_filtered_count if depth_filtering_enabled else 0
        }

        # Add 'best' key if we have qualifying coins (for controller compatibility)
        if top_n:
            self._debug_info['best'] = top_n[0]  # (symbol, trend_value) tuple

        return [symbol for symbol, _ in top_n]

    def get_trend(self, symbol: str) -> Optional[CoinTrend]:
        """Get trend data for a specific coin"""
        return self.trends.get(symbol)

    def clear_trends(self) -> None:
        """Clear all trend data"""
        self.trends.clear()

    # ========================================================================
    # Phase 3: Validation & Output Contract
    # ========================================================================

    def validate_trend(self, symbol: str) -> Optional[TrendSelection]:
        """
        Validate trend and return structured output contract.

        This method implements the production-ready validation logic:
        1. Check candle count (minimum 360 for valid trends)
        2. Check trend threshold (minimum +0.5% for bullish)
        3. Return structured output with passes/status fields

        Args:
            symbol: Trading pair symbol (e.g., "BTC-EUR")

        Returns:
            TrendSelection object with validation results, or None if symbol not found
        """
        trend = self.trends.get(symbol)
        if not trend:
            return None

        # Get candle count
        candle_count = trend.candle_count

        # Check warmup status (< 360 candles)
        if candle_count < MIN_CANDLES_FOR_WARMUP:
            return TrendSelection(
                symbol=symbol,
                trend_1h=trend.trend_60m,
                trend_4h=trend.trend_240m,
                trend_24h=trend.trend_1440m,
                trend_score_pct=trend.trend_score,
                passes=False,
                status=TrendStatus.WARMUP,
                candle_count=candle_count,
                consensus_pct=trend.consensus_trend_pct,
                volatility=trend.volatility
            )

        # 🔧 FIX: Use consensus trend instead of weighted average (trend_score)
        # Consensus trend is more responsive and better for bullish markets
        # trend_score was too conservative (0.2*1h + 0.4*4h + 0.4*24h)
        trend_score = trend.consensus_trend_pct  # Changed from trend.trend_score

        # Determine status and passes flag
        if trend_score < -MIN_TREND_THRESHOLD:
            # Strong bearish trend
            status = TrendStatus.BEARISH
            passes = False
        elif trend_score < MIN_TREND_THRESHOLD:
            # Sideways or weak trend
            status = TrendStatus.SIDEWAYS
            passes = False
        else:
            # Bullish trend (>= +0.5%)
            status = TrendStatus.BULLISH
            passes = True

        return TrendSelection(
            symbol=symbol,
            trend_1h=trend.trend_60m,
            trend_4h=trend.trend_240m,
            trend_24h=trend.trend_1440m,
            trend_score_pct=trend_score,
            passes=passes,
            status=status,
            candle_count=candle_count,
            consensus_pct=trend.consensus_trend_pct,
            volatility=trend.volatility
        )

    def get_all_selections(self) -> List[TrendSelection]:
        """
        Get validation output for all tracked coins.

        Returns:
            List of TrendSelection objects sorted by trend_score (descending)
        """
        selections = []
        for symbol in self.trends.keys():
            selection = self.validate_trend(symbol)
            if selection:
                selections.append(selection)

        # Sort by trend score (best first)
        selections.sort(key=lambda x: x.trend_score_pct, reverse=True)
        return selections

    def print_selection_report(self) -> None:
        """
        Print formatted selection report for all coins.

        Example output:
        {
          "symbol": "BTC/EUR",
          "trend_1h": -0.8,
          "trend_4h": -1.4,
          "trend_24h": -2.9,
          "trend_score_pct": -1.96,
          "passes": false,
          "status": "BEARISH"
        }
        """
        selections = self.get_all_selections()

        logger.info("\n" + "=" * 80)
        logger.info("📊 TREND SELECTION REPORT")
        logger.info("=" * 80)
        logger.info(f"Total coins tracked: {len(selections)}")
        logger.info(f"Minimum threshold: {MIN_TREND_THRESHOLD:+.2f}%")
        logger.info(f"Minimum candles: {MIN_CANDLES_FOR_WARMUP}")
        logger.info("")

        # Count by status
        status_counts = {
            TrendStatus.WARMUP: 0,
            TrendStatus.BEARISH: 0,
            TrendStatus.SIDEWAYS: 0,
            TrendStatus.BULLISH: 0
        }

        for sel in selections:
            status_counts[sel.status] += 1

        logger.info("Status Distribution:")
        logger.info(f"  WARMUP:   {status_counts[TrendStatus.WARMUP]} coins (insufficient data)")
        logger.info(f"  BEARISH:  {status_counts[TrendStatus.BEARISH]} coins (< {-MIN_TREND_THRESHOLD:+.2f}%)")
        logger.info(
            f"  SIDEWAYS: {status_counts[TrendStatus.SIDEWAYS]} coins ({-MIN_TREND_THRESHOLD:+.2f}% to {MIN_TREND_THRESHOLD:+.2f}%)")  # noqa: E501
        logger.info(f"  BULLISH:  {status_counts[TrendStatus.BULLISH]} coins (>= {MIN_TREND_THRESHOLD:+.2f}%)")
        logger.info("")

        # Print each selection
        for idx, sel in enumerate(selections, 1):
            status_emoji = {
                TrendStatus.WARMUP: "⏳",
                TrendStatus.BEARISH: "📉",
                TrendStatus.SIDEWAYS: "➡️",
                TrendStatus.BULLISH: "📈"
            }[sel.status]

            passes_emoji = "✅" if sel.passes else "❌"

            logger.info(
                f"{idx:2}. {status_emoji} {sel.symbol:12} | "
                f"Score: {sel.trend_score_pct:+6.2f}% | "
                f"1h: {sel.trend_1h:+6.2f}% | "
                f"4h: {sel.trend_4h:+6.2f}% | "
                f"24h: {sel.trend_24h:+6.2f}% | "
                f"Candles: {sel.candle_count:3} | "
                f"{passes_emoji} {sel.status.value}"
            )

        logger.info("=" * 80 + "\n")

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
                ema_trend * weight_ema
                + linreg_trend * weight_linreg
                + normalized_trend * weight_normalized
                + raw_trend * weight_raw
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
            # BUGFIX: Reduce warm-up from 24h to 6h - with 360+ candles we have enough data
            warmup_period_seconds = min(self.trend_lookback_long_minutes * 60, 360 * 60)  # Max 6 hours

            if time_since_bot_start < warmup_period_seconds:
                # BUGFIX: In warm-up mode, use conservative averaging instead of aggressive extrapolation
                # Old behavior: trend_1440m = trend_240m * 2.0 (WRONG! Could be 10x off!)
                # New behavior: Use average of 4h and 1h trends (MUCH safer!)
                trend.long_trend_warmup = True

                # Use conservative fallback = average of 4h and 1h trends
                # This is MUCH safer than 4h * 2 (which was causing 10x errors!)
                trend.trend_1440m = (trend_240m + trend_60m) / 2.0

                logger.debug(
                    f"Warm-up mode for {trend.symbol}: "
                    f"24h trend = avg({trend.trend_240m:.2f}%, {trend.trend_60m:.2f}%) = {trend.trend_1440m:.2f}% "
                    f"(bot running for {time_since_bot_start / 3600:.1f}h, need {warmup_period_seconds / 3600:.1f}h)"
                )
            else:
                # Normal mode: calculate real 24h trend from price history
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
                0.2 * trend.trend_60m
                + 0.4 * trend.trend_240m
                + 0.4 * trend.trend_1440m
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
                logger.debug(
                    f"⚠️ TF calc: Not enough data! lookback={lookback_seconds / 60:.0f}m, "
                    f"total_points={len(price_history)}, relevant={len(relevant_history)}, "
                    f"cutoff={time.strftime('%H:%M:%S', time.localtime(cutoff_time))}"
                )
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
