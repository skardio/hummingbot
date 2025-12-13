"""
SmartEntryFilter - ML-lite Entry Decision System

Besluit of een grid entry toegestaan is op basis van:
- RSI regime (overbought/oversold)
- VWAP mean-reversion potential
- Wick analysis (market structure)
- ATR-based volatility regime
- News/chaos detection (5m spikes)
- Trend acceleration (falling knife / blow-off top)
- 24h trend sanity checks
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass
class CandleIndicators:
    """Technical indicators berekend van 5m candles"""
    price: Decimal              # Current price
    rsi_14: float               # RSI(14) - 0-100
    vwap: Decimal               # Session VWAP
    atr_pct: float              # ATR(14) / price * 100
    wick_ratio: float           # (high - close) / max((close - low), tiny)
    trend_1h_pct: float         # % change over last 1h
    trend_4h_pct: float         # % change over last 4h
    trend_24h_pct: float        # % change over last 24h
    change_5m_pct: float        # Last 5m candle % change


@dataclass
class SmartEntryConfig:
    """Configuration for SmartEntryFilter"""

    # RSI Regime
    rsi_buy_max: float = 60.0          # Koop alleen onder deze RSI
    rsi_extreme_low: float = 25.0      # Extreme dip - mogelijk falling knife
    rsi_block_min: float = 70.0        # Nooit kopen boven deze RSI (overbought)

    # VWAP Mean-Reversion (AANGEPAST: ruimer voor trends)
    vwap_max_deviation_pct: float = 3.0  # Max |price-vwap| in % (was 1.2, nu 3.0)

    # Wick Analysis (AANGEPAST: minder strict)
    min_wick_ratio: float = 0.25      # >= 0.25 = voldoende wicks (balanced threshold)

    # Volatility Regime via ATR
    max_atr_pct_for_grid: float = 6.0  # >6% ATR = te bruut, grid uit
    min_atr_pct_for_grid: float = 0.5  # <0.5% ATR = te dood, skip

    # News/Chaos Filter via 5m candle
    max_5m_spike_pct: float = 2.5     # Geen nieuwe buys als 5m move > 2.5%

    # Trend Acceleration (1h vs 4h)
    max_down_accel_pct: float = -1.0  # Als 1h-4h < -1% → falling knife
    max_up_accel_pct: float = 1.5     # Als 1h-4h > 1.5% → mogelijk blow-off top

    # 24h Trend Sanity Check
    max_trend_24h_pct: float = 8.0    # > +8% dagtrend → beter niet instappen
    min_trend_24h_pct: float = -12.0  # < -12% dagtrend → capitulatie risk

    # Slippage Protection (NEW - Phase 2)
    max_entry_spread_pct: float = 0.5  # Reject if bid-ask spread > 0.5%
    slippage_check_enabled: bool = True  # Enable spread checking

    # Order Book Depth (NEW - Phase 2)
    min_depth_multiplier: float = 3.0   # Need 3x order size on each side
    depth_check_enabled: bool = True    # Enable depth validation


class SmartEntryFilter:
    """
    Intelligent entry filter voor grid trading.
    Voorkomt entries tijdens:
    - Overbought/oversold extremes
    - News/chaos events
    - Falling knives / blow-off tops
    - Dead markets
    - Wide spreads (slippage protection)
    - Thin order books (depth protection)
    """

    def __init__(self, config: SmartEntryConfig = None, exchange=None):
        self.config = config or SmartEntryConfig()
        self.exchange = exchange  # For order book queries
        logger.info("🧠 SmartEntryFilter initialized")
        logger.info(f"   RSI range: {self.config.rsi_extreme_low}-{self.config.rsi_buy_max} (block >{self.config.rsi_block_min})")
        logger.info(f"   ATR range: {self.config.min_atr_pct_for_grid}%-{self.config.max_atr_pct_for_grid}%")
        logger.info(f"   5m spike max: {self.config.max_5m_spike_pct}%")
        logger.info(f"   Trend accel: {self.config.max_down_accel_pct}% to +{self.config.max_up_accel_pct}%")
        logger.info(f"   Slippage protection: max spread {self.config.max_entry_spread_pct}% (enabled={self.config.slippage_check_enabled})")
        logger.info(f"   Depth protection: {self.config.min_depth_multiplier}x multiplier (enabled={self.config.depth_check_enabled})")

    def check_order_book_depth(self, symbol: str, order_size_eur: float) -> Tuple[bool, str]:
        """
        Check if order book has sufficient depth for order.

        Args:
            symbol: Trading pair (e.g., "SUI-EUR")
            order_size_eur: Order size in EUR

        Returns:
            (passes_check: bool, reason: str)
        """
        if not self.config.depth_check_enabled or not self.exchange:
            return True, "Depth check disabled or no exchange"

        try:
            required_depth = order_size_eur * self.config.min_depth_multiplier

            # Get current order book from exchange
            order_book = self.exchange.get_order_book(symbol)

            if not order_book or 'bids' not in order_book or 'asks' not in order_book:
                logger.warning(f"[DEPTH] {symbol} - No order book data available")
                return True, "No order book data (skipping check)"

            # Sum BID side (people willing to buy from us = we sell)
            bid_total_eur = 0.0
            for bid_price, bid_volume in order_book['bids']:
                bid_total_eur += float(bid_price) * float(bid_volume)
                if bid_total_eur >= required_depth:
                    break

            # Sum ASK side (people willing to sell to us = we buy)
            ask_total_eur = 0.0
            for ask_price, ask_volume in order_book['asks']:
                ask_total_eur += float(ask_price) * float(ask_volume)
                if ask_total_eur >= required_depth:
                    break

            has_bid_depth = bid_total_eur >= required_depth
            has_ask_depth = ask_total_eur >= required_depth

            if not has_bid_depth or not has_ask_depth:
                return False, (
                    f"Insufficient liquidity: BID {bid_total_eur:.0f}/{required_depth:.0f} EUR, "
                    f"ASK {ask_total_eur:.0f}/{required_depth:.0f} EUR (need {self.config.min_depth_multiplier}x)"
                )

            logger.debug(
                f"[DEPTH] {symbol} ✓ BID: {bid_total_eur:.0f}/{required_depth:.0f} EUR, "
                f"ASK: {ask_total_eur:.0f}/{required_depth:.0f} EUR"
            )
            return True, f"Sufficient depth ({self.config.min_depth_multiplier}x confirmed)"

        except Exception as e:
            logger.warning(f"[DEPTH] {symbol} - Error checking depth: {e}")
            return True, f"Depth check failed (allowing entry): {e}"

    def check_spread(self, symbol: str, bid_price: Decimal, ask_price: Decimal) -> Tuple[bool, str]:
        """
        Check if bid-ask spread is acceptable.

        Args:
            symbol: Trading pair
            bid_price: Current bid price
            ask_price: Current ask price

        Returns:
            (passes_check: bool, reason: str)
        """
        if not self.config.slippage_check_enabled:
            return True, "Spread check disabled"

        if bid_price <= 0 or ask_price <= 0:
            logger.warning(f"[SPREAD] {symbol} - Invalid prices: bid={bid_price}, ask={ask_price}")
            return True, "Invalid prices (skipping check)"

        mid_price = (bid_price + ask_price) / 2
        spread_pct = float((ask_price - bid_price) / mid_price * 100)

        if spread_pct > self.config.max_entry_spread_pct:
            return False, (
                f"Spread too wide: {spread_pct:.3f}% > {self.config.max_entry_spread_pct}% "
                f"(bid={float(bid_price):.4f}, ask={float(ask_price):.4f})"
            )

        logger.debug(f"[SPREAD] {symbol} ✓ {spread_pct:.3f}% (< {self.config.max_entry_spread_pct}%)")
        return True, f"Spread OK: {spread_pct:.3f}%"

    def allows_entry(
        self,
        symbol: str,
        ind: CandleIndicators,
        order_size_eur: float = None,
        bid_price: Decimal = None,
        ask_price: Decimal = None,
    ) -> Tuple[bool, str]:
        """
        Besluit of entry toegestaan is.

        Args:
            symbol: Trading pair
            ind: Candle indicators
            order_size_eur: Order size for depth checking (optional)
            bid_price: Current bid for spread checking (optional)
            ask_price: Current ask for spread checking (optional)

        Returns:
            (allowed: bool, reason: str)
        """

        # 0A) Slippage Protection - Check spread
        if bid_price and ask_price:
            spread_ok, spread_reason = self.check_spread(symbol, bid_price, ask_price)
            if not spread_ok:
                return False, f"{symbol}: NO BUY – {spread_reason}"

        # 0B) Order Book Depth Check
        if order_size_eur:
            depth_ok, depth_reason = self.check_order_book_depth(symbol, order_size_eur)
            if not depth_ok:
                return False, f"{symbol}: NO BUY – {depth_reason}"

        # 1) RSI Regime Check
        if ind.rsi_14 >= self.config.rsi_block_min:
            return False, f"{symbol}: BLOCKED – RSI too high ({ind.rsi_14:.1f} >= {self.config.rsi_block_min})"

        if ind.rsi_14 > self.config.rsi_buy_max:
            return False, f"{symbol}: NO BUY – RSI={ind.rsi_14:.1f} > buy_max={self.config.rsi_buy_max}"

        if ind.rsi_14 < self.config.rsi_extreme_low:
            # Extreme oversold - mogelijk falling knife
            return False, f"{symbol}: NO BUY – RSI={ind.rsi_14:.1f} (extreme oversold, falling knife risk)"

        # 2) VWAP Mean-Reversion Check
        if ind.vwap > 0:
            vwap_dev_pct = float((ind.price - ind.vwap) / ind.vwap * 100)
            if abs(vwap_dev_pct) > self.config.vwap_max_deviation_pct:
                return False, (
                    f"{symbol}: NO BUY – VWAP dev {vwap_dev_pct:.2f}% > "
                    f"{self.config.vwap_max_deviation_pct}% (too far from mean)"
                )

        # 3) Wick Ratio Check - market structure
        # SMART LOGIC: wick_ratio 0.00 OK als RSI niet overbought (<65)
        # Perfect bullish candles zijn OK als de coin niet al te heet is
        if ind.wick_ratio < self.config.min_wick_ratio:
            # Exception: wick_ratio 0.00 toegestaan als RSI < 65 (nog niet overbought)
            if ind.wick_ratio == 0.00 and ind.rsi_14 < 65.0:
                logger.info(f"🎯 {symbol}: wick_ratio 0.00 accepted (RSI={ind.rsi_14:.1f} < 65, perfect bullish candle)")
            else:
                return False, (
                    f"{symbol}: NO BUY – wick_ratio {ind.wick_ratio:.2f} < "
                    f"{self.config.min_wick_ratio} (poor structure)"
                )

        # 4) Volatility Regime via ATR
        if ind.atr_pct < self.config.min_atr_pct_for_grid:
            return False, (
                f"{symbol}: NO BUY – ATR too low ({ind.atr_pct:.2f}%) → dead market"
            )

        if ind.atr_pct > self.config.max_atr_pct_for_grid:
            return False, (
                f"{symbol}: NO BUY – ATR too high ({ind.atr_pct:.2f}%) → news/chaos"
            )

        # 5) News/Chaos Filter via 5m candle spike
        if abs(ind.change_5m_pct) > self.config.max_5m_spike_pct:
            return False, (
                f"{symbol}: NO BUY – 5m move {ind.change_5m_pct:.2f}% > "
                f"{self.config.max_5m_spike_pct}% (likely news/impulse)"
            )

        # 6) Trend Acceleration Check (1h vs 4h)
        accel = ind.trend_1h_pct - ind.trend_4h_pct
        if accel < self.config.max_down_accel_pct:
            return False, (
                f"{symbol}: NO BUY – downside acceleration {accel:.2f}% "
                f"(1h << 4h, falling knife)"
            )

        if accel > self.config.max_up_accel_pct:
            return False, (
                f"{symbol}: NO BUY – upside acceleration {accel:.2f}% "
                f"(1h >> 4h, blow-off top risk)"
            )

        # 7) 24h Trend Sanity Check
        if ind.trend_24h_pct > self.config.max_trend_24h_pct:
            return False, (
                f"{symbol}: NO BUY – 24h trend too high ({ind.trend_24h_pct:.2f}%) "
                f"(extended run)"
            )

        if ind.trend_24h_pct < self.config.min_trend_24h_pct:
            return False, (
                f"{symbol}: NO BUY – 24h trend too low ({ind.trend_24h_pct:.2f}%) "
                f"(possible capitulation)"
            )

        # ✅ ALL CHECKS PASSED
        return True, (
            f"{symbol}: ✅ BUY ALLOWED – RSI={ind.rsi_14:.1f}, ATR={ind.atr_pct:.2f}%, "
            f"accel={accel:.2f}%, 24h={ind.trend_24h_pct:.2f}%"
        )

    def get_filter_stats(self, symbol: str, ind: CandleIndicators) -> dict:
        """
        Returns detailed stats voor debugging/monitoring.
        """
        accel = ind.trend_1h_pct - ind.trend_4h_pct
        vwap_dev = float((ind.price - ind.vwap) / ind.vwap * 100) if ind.vwap > 0 else 0.0

        return {
            "symbol": symbol,
            "rsi": ind.rsi_14,
            "atr_pct": ind.atr_pct,
            "vwap_dev_pct": vwap_dev,
            "wick_ratio": ind.wick_ratio,
            "change_5m_pct": ind.change_5m_pct,
            "acceleration": accel,
            "trend_1h_pct": ind.trend_1h_pct,
            "trend_4h_pct": ind.trend_4h_pct,
            "trend_24h_pct": ind.trend_24h_pct,
            "price": float(ind.price),
            "vwap": float(ind.vwap),
        }
