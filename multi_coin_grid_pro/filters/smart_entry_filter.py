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
- VWAP Slope Guard (EPIC v3.4 Stories 2+9): momentum health detection
- Parabolic Detector (EPIC v3.4 Stories 3+10): blow-off top cooldowns with persistence
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from multi_coin_grid_pro.filters.parabolic_blacklist import ParabolicBlacklist

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

    # VWAP Slope Guard (NEW - EPIC v3.4 Stories 2 + 9)
    vwap_slope_guard_enabled: bool = False  # Enable VWAP slope momentum guard
    vwap_slope_guard_shadow_mode: bool = True  # True = shadow mode (log only), False = live blocking
    vwap_slope_dual_confirmation: bool = True  # Story 9: Require BOTH 5m AND 15m slopes flat
    vwap_slope_deviation_high_pct: float = 15.0  # Baseline: check slope if dev >= 15%
    vwap_slope_min_pct_5m: float = 0.05      # Story 9: Baseline 5m slope threshold
    vwap_slope_min_pct_15m: float = 0.10     # Baseline: reject if 15m slope <= 0.10%
    vwap_slope_log_details: bool = True      # Log detailed guard decisions

    # Parabolic Detector (NEW - EPIC v3.4 Stories 3 + 10)
    parabolic_detector_enabled: bool = False  # Enable parabolic blow-off detector
    parabolic_detector_shadow_mode: bool = True  # True = shadow mode (log only), False = live blocking
    parabolic_cooldown_persist: bool = True   # Story 10: Persist cooldowns to SQLite
    parabolic_accel_5m_min_pct: float = 2.5   # Baseline: min 5m acceleration
    parabolic_accel_15m_min_pct: float = 6.0  # Baseline: min 15m acceleration
    parabolic_vwap_dev_min_pct: float = 18.0  # Baseline: min VWAP deviation
    parabolic_cooldown_minutes: int = 30      # Cooldown duration in minutes
    parabolic_blacklist_scope: str = "session"  # "session" or "persistent"
    parabolic_log_details: bool = True        # Log detailed detector decisions

    # Momentum Thresholds (NEW - EPIC v3.4 Story 5)
    momentum_thresholds: dict = None          # Regime-aware momentum thresholds (baseline + BULL/CHOP/BEAR overrides)

    # Market Exhaustion Warning (NEW - EPIC v3.4 Story 11)
    market_exhaustion_enabled: bool = False   # Enable market-wide exhaustion detection
    market_exhaustion_threshold_pct: float = 0.70  # Trigger if >= 70% of sample is parabolic
    market_exhaustion_sample_size: int = 10   # Evaluate top N candidates
    market_exhaustion_cooldown_min: int = 30  # Alert rate limit in minutes
    market_exhaustion_telegram: bool = False  # Send Telegram alerts (backward compat with config.prod.yaml)
    market_exhaustion_actions: list = None    # Actions: ['log', 'telegram'] (optional alternative format)

    @property
    def vwap_slope_guard_mode(self) -> str:
        """Convert boolean shadow_mode to string mode for backward compatibility"""
        return "shadow" if self.vwap_slope_guard_shadow_mode else "live"

    @property
    def parabolic_detector_mode(self) -> str:
        """Convert boolean shadow_mode to string mode for backward compatibility"""
        return "shadow" if self.parabolic_detector_shadow_mode else "live"

    @property
    def parabolic_cooldown_sec(self) -> int:
        """Convert minutes to seconds for backward compatibility"""
        return self.parabolic_cooldown_minutes * 60


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

    def __init__(self, config: SmartEntryConfig = None, exchange=None, connector_name: str = None, event_logger=None, cooldown_store=None):
        self.config = config or SmartEntryConfig()
        self.exchange = exchange  # For order book queries
        self.connector_name = connector_name  # Store connector name for API calls
        self.parabolic_blacklist = ParabolicBlacklist()  # Session-scoped cooldown tracking
        self.cooldown_store = cooldown_store  # Story 10: Optional SQLite persistence
        self.event_logger = event_logger  # EPIC v3.4 Story 6: Structured event logging
        self._last_event_time = {}  # {symbol: timestamp} for rate limiting
        self._event_cooldown_sec = 60  # Max 1 event per symbol per 60 seconds

        # Story 10: Load active cooldowns from persistence if available
        if self.cooldown_store and self.connector_name:
            active_cooldowns = self.cooldown_store.load_active(connector=self.connector_name)
            if active_cooldowns:
                logger.info(f"Loaded {len(active_cooldowns)} active cooldowns from persistence")
                # Restore to in-memory blacklist
                for symbol, expires_at in active_cooldowns.items():
                    remaining = int(expires_at - time.time())
                    if remaining > 0:
                        self.parabolic_blacklist.blacklist[symbol] = expires_at

        logger.info("🧠 SmartEntryFilter initialized")
        logger.info(
            f"   RSI range: {self.config.rsi_extreme_low}-{self.config.rsi_buy_max} (block >{self.config.rsi_block_min})")  # noqa: E501
        logger.info(f"   ATR range: {self.config.min_atr_pct_for_grid}%-{self.config.max_atr_pct_for_grid}%")
        logger.info(f"   5m spike max: {self.config.max_5m_spike_pct}%")
        logger.info(f"   Trend accel: {self.config.max_down_accel_pct}% to +{self.config.max_up_accel_pct}%")
        logger.info(
            f"   Slippage protection: max spread {
                self.config.max_entry_spread_pct}% (enabled={
                self.config.slippage_check_enabled})")
        logger.info(
            f"   Depth protection: {
                self.config.min_depth_multiplier}x multiplier (enabled={
                self.config.depth_check_enabled})")
        if event_logger:
            logger.info("   📝 Entry guard event logging: ENABLED")

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

            # Get current order book from exchange using the new API
            order_book = self.exchange.get_order_book(self.connector_name, symbol)

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

    def _emit_entry_guard_event(
        self,
        symbol: str,
        decision: str,
        regime: str,
        reject_reason: Optional[str] = None,
        metrics: Optional[Dict[str, Optional[float]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        cooldown_remaining_sec: Optional[int] = None,
        mode: str = "live",
        force: bool = False
    ) -> None:
        """
        Emit entry guard evaluation event with rate limiting (Story 6).

        Args:
            symbol: Trading pair
            decision: "ACCEPTED" or "REJECTED"
            regime: Market regime (BULL/CHOP/BEAR/NEUTRAL)
            reject_reason: Rejection reason code (if REJECTED)
            metrics: Momentum metrics
            thresholds: Thresholds used
            cooldown_remaining_sec: Cooldown remaining (if applicable)
            mode: "shadow" or "live"
            force: Force emit (ignore rate limit)
        """
        if not self.event_logger:
            return

        import time
        now = time.time()

        # Rate limiting: max 1 event per symbol per 60 seconds
        if not force:
            last_event = self._last_event_time.get(symbol, 0)
            if now - last_event < self._event_cooldown_sec:
                return  # Skip event (rate limited)

        self._last_event_time[symbol] = now

        # Emit event
        self.event_logger.emit_entry_guard_evaluation(
            connector=self.connector_name or "unknown",
            symbol=symbol,
            decision=decision,
            regime=regime,
            reject_reason=reject_reason,
            metrics=metrics or {},
            thresholds=thresholds or {},
            cooldown_remaining_sec=cooldown_remaining_sec,
            mode=mode
        )

    def _resolve_threshold(
        self,
        symbol: str,
        threshold_key: str,
        regime: str
    ) -> float:
        """
        Resolve threshold with precedence (Story 5 + Story 9).

        Precedence order:
        1. Coin profile override (if exists)
        2. Regime-specific value (BULL/CHOP/BEAR)
        3. Baseline default

        Args:
            symbol: Trading pair symbol
            threshold_key: Key to look up (e.g., "slope_min_pct_5m", "deviation_high_pct")
            regime: Market regime (BULL/CHOP/BEAR/NEUTRAL)

        Returns:
            Resolved threshold value
        """
        # Safety floors (cannot be overridden by coin profiles)
        SAFETY_FLOORS = {
            "slope_min_pct_5m": 0.00,     # Allow completely flat in lenient configs
            "slope_min_pct_15m": 0.01,
            "accel_5m_min_pct": 1.0,
            "accel_15m_min_pct": 3.0,
            "vwap_dev_min_pct": 8.0,
            "deviation_high_pct": 10.0,
        }

        # Try getting from momentum_thresholds config
        if self.config.momentum_thresholds:
            thresholds = self.config.momentum_thresholds

            # 1. Check coin profile (if exists) - TODO: implement per-symbol overrides
            # coin_profile = thresholds.get("coin_profiles", {}).get(symbol, {})
            # if threshold_key in coin_profile:
            #     value = coin_profile[threshold_key]
            #     floor = SAFETY_FLOORS.get(threshold_key)
            #     if floor and value < floor:
            #         return floor
            #     return value

            # 2. Check regime-specific
            if regime in ["BULL", "CHOP", "BEAR"]:
                regime_config = thresholds.get("regimes", {}).get(regime, {})
                if threshold_key in regime_config:
                    return regime_config[threshold_key]

            # 3. Check baseline
            baseline = thresholds.get("baseline", {})
            if threshold_key in baseline:
                return baseline[threshold_key]

        # Fallback to flat config attributes (backward compatibility)
        if threshold_key == "slope_min_pct_5m":
            return getattr(self.config, "vwap_slope_min_pct_5m", 0.05)
        elif threshold_key == "slope_min_pct_15m":
            return getattr(self.config, "vwap_slope_min_pct_15m", 0.10)
        elif threshold_key == "deviation_high_pct":
            return getattr(self.config, "vwap_slope_deviation_high_pct", 15.0)

        # Last resort: return safety floor or 0
        return SAFETY_FLOORS.get(threshold_key, 0.0)

    def allows_entry(
        self,
        symbol: str,
        ind: CandleIndicators,
        order_size_eur: float = None,
        bid_price: Decimal = None,
        ask_price: Decimal = None,
        vwap_slope_5m_pct: Optional[float] = None,  # Story 9: 5m slope for dual-window confirmation
        vwap_slope_15m_pct: Optional[float] = None,
        accel_5m_pct: Optional[float] = None,
        accel_15m_pct: Optional[float] = None,
        regime: str = "NEUTRAL",
    ) -> Tuple[bool, str]:
        """
        Besluit of entry toegestaan is.

        Args:
            symbol: Trading pair
            ind: Candle indicators
            order_size_eur: Order size for depth checking (optional)
            bid_price: Current bid for spread checking (optional)
            ask_price: Current ask for spread checking (optional)
            vwap_slope_5m_pct: VWAP slope over 5m (optional, for EPIC v3.4 Story 9)
            vwap_slope_15m_pct: VWAP slope over 15m (optional, for EPIC v3.4 Story 2)
            accel_5m_pct: Price acceleration over 5m (optional, for EPIC v3.4 Story 3)
            accel_15m_pct: Price acceleration over 15m (optional, for EPIC v3.4 Story 3)
            regime: Market regime (BULL/CHOP/BEAR, optional, for EPIC v3.4)

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
        vwap_dev_pct = 0.0
        if ind.vwap > 0:
            vwap_dev_pct = float((ind.price - ind.vwap) / ind.vwap * 100)
            if abs(vwap_dev_pct) > self.config.vwap_max_deviation_pct:
                return False, (
                    f"{symbol}: NO BUY – VWAP dev {vwap_dev_pct:.2f}% > "
                    f"{self.config.vwap_max_deviation_pct}% (too far from mean)"
                )

        # 2A) VWAP Slope Guard - Blow-off Top Detection (EPIC v3.4 Stories 2 + 9)
        if self.config.vwap_slope_guard_enabled:
            slope_ok, slope_reason = self.check_vwap_slope_guard(
                symbol=symbol,
                vwap_dev_pct=vwap_dev_pct,
                vwap_slope_5m_pct=vwap_slope_5m_pct,  # Story 9: Added 5m slope
                vwap_slope_15m_pct=vwap_slope_15m_pct,
                regime=regime
            )
            if not slope_ok:
                return False, f"{symbol}: NO BUY – {slope_reason}"

        # 2B) Parabolic Detector - Extreme Blow-off Top + Cooldown (EPIC v3.4)
        if self.config.parabolic_detector_enabled:
            parabolic_ok, parabolic_reason = self.check_parabolic_detector(
                symbol=symbol,
                vwap_dev_pct=vwap_dev_pct,
                accel_5m_pct=accel_5m_pct,
                accel_15m_pct=accel_15m_pct,
                regime=regime
            )
            if not parabolic_ok:
                return False, f"{symbol}: NO BUY – {parabolic_reason}"

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

    def check_vwap_slope_guard(
        self,
        symbol: str,
        vwap_dev_pct: float,
        vwap_slope_5m_pct: Optional[float],
        vwap_slope_15m_pct: Optional[float],
        regime: str = "NEUTRAL"
    ) -> Tuple[bool, Optional[str]]:
        """
        VWAP Slope Guard - Detects blow-off tops.

        Story 9: Dual-window confirmation - requires BOTH 5m AND 15m slopes flat
        to reduce false positives during healthy consolidations.

        Rejects entry when:
        1. Price is far above VWAP (deviation >= threshold)
        2. AND (single-window mode): VWAP 15m slope is flat/negative
           OR (dual-window mode): BOTH 5m AND 15m slopes are flat/negative

        Returns:
            (allowed, reject_reason) - (True, None) if passed, (False, reason) if rejected
        """
        if not self.config.vwap_slope_guard_enabled:
            return True, None

        # Only check if deviation is positive (price above VWAP)
        if vwap_dev_pct <= 0:
            return True, None

        # Check if deviation exceeds threshold (price too far above VWAP)
        deviation_threshold = self._resolve_threshold(symbol, "deviation_high_pct", regime)
        if vwap_dev_pct < deviation_threshold:
            # Not far enough above VWAP to check slope
            return True, None

        # Dual-window confirmation mode (Story 9)
        if self.config.vwap_slope_dual_confirmation:
            # Check both slopes available
            if vwap_slope_5m_pct is None or vwap_slope_15m_pct is None:
                if self.config.vwap_slope_log_details:
                    logger.debug(
                        f"[{self.config.vwap_slope_guard_mode.upper()}] {symbol}: "
                        f"VWAP slope data unavailable (5m={vwap_slope_5m_pct}, 15m={vwap_slope_15m_pct})"
                    )
                return True, None  # Don't reject if we can't calculate slopes

            # Get thresholds for both windows
            slope_threshold_5m = self._resolve_threshold(symbol, "slope_min_pct_5m", regime)
            slope_threshold_15m = self._resolve_threshold(symbol, "slope_min_pct_15m", regime)

            # Check if BOTH slopes are flat/negative
            slope_5m_flat = vwap_slope_5m_pct <= slope_threshold_5m
            slope_15m_flat = vwap_slope_15m_pct <= slope_threshold_15m

            if slope_5m_flat and slope_15m_flat:
                # BLOW-OFF TOP DETECTED: Both windows show dying momentum
                reason = (
                    f"VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH "
                    f"(dev={vwap_dev_pct:.1f}%, 5m={vwap_slope_5m_pct:.2f}%, 15m={vwap_slope_15m_pct:.2f}%, "
                    f"thresholds: dev>={deviation_threshold}%, 5m<={slope_threshold_5m}%, 15m<={slope_threshold_15m}%)"
                )

                # EPIC v3.4 Story 6: Emit structured event
                self._emit_entry_guard_event(
                    symbol=symbol,
                    decision="REJECTED",
                    regime=regime,
                    reject_reason="VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH",
                    metrics={
                        "vwap_deviation_pct": vwap_dev_pct,
                        "vwap_slope_5m_pct": vwap_slope_5m_pct,
                        "vwap_slope_15m_pct": vwap_slope_15m_pct
                    },
                    thresholds={
                        "deviation_high_pct": deviation_threshold,
                        "slope_min_5m": slope_threshold_5m,
                        "slope_min_15m": slope_threshold_15m
                    },
                    mode=self.config.vwap_slope_guard_mode
                )

                if self.config.vwap_slope_guard_mode == "live":
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                    return False, reason
                else:
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[SHADOW] {symbol}: Would reject by dual-slope guard – {reason}")
                        logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                    return True, None
            else:
                # At least one window still has momentum - allow entry
                if self.config.vwap_slope_log_details and (slope_5m_flat or slope_15m_flat):
                    logger.debug(
                        f"{symbol}: Dual-window PASS (5m={'FLAT' if slope_5m_flat else 'OK'}, "
                        f"15m={'FLAT' if slope_15m_flat else 'OK'}) - at least one window has momentum"
                    )
                return True, None

        else:
            # Single-window mode (15m only - backward compatibility)
            if vwap_slope_15m_pct is None:
                if self.config.vwap_slope_log_details:
                    logger.debug(
                        f"[{self.config.vwap_slope_guard_mode.upper()}] {symbol}: "
                        f"VWAP 15m slope data unavailable (dev={vwap_dev_pct:.1f}%)"
                    )
                return True, None

            slope_threshold_15m = self._resolve_threshold(symbol, "slope_min_pct_15m", regime)

            if vwap_slope_15m_pct <= slope_threshold_15m:
                reason = (
                    f"VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH "
                    f"(dev={vwap_dev_pct:.1f}%, 15m={vwap_slope_15m_pct:.2f}%, "
                    f"thresholds: dev>={deviation_threshold}%, 15m<={slope_threshold_15m}%)"
                )

                self._emit_entry_guard_event(
                    symbol=symbol,
                    decision="REJECTED",
                    regime=regime,
                    reject_reason="VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH",
                    metrics={
                        "vwap_deviation_pct": vwap_dev_pct,
                        "vwap_slope_15m_pct": vwap_slope_15m_pct
                    },
                    thresholds={
                        "deviation_high_pct": deviation_threshold,
                        "slope_min_pct_15m": slope_threshold_15m
                    },
                    mode=self.config.vwap_slope_guard_mode
                )

                if self.config.vwap_slope_guard_mode == "live":
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                    return False, reason
                else:
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[SHADOW] {symbol}: Would reject by slope guard – {reason}")
                        logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                    return True, None

        # Passed: Price above VWAP but slope(s) still healthy
        return True, None

    def check_parabolic_detector(
        self,
        symbol: str,
        vwap_dev_pct: float,
        accel_5m_pct: Optional[float],
        accel_15m_pct: Optional[float],
        regime: str = "NEUTRAL"
    ) -> Tuple[bool, Optional[str]]:
        """
        Parabolic Detector - Detects extreme blow-off tops with cooldown.

        Triggers cooldown when ALL THREE conditions are met:
        1. VWAP deviation >= threshold (price far above VWAP)
        2. 5m acceleration >= threshold (extreme short-term momentum)
        3. 15m acceleration >= threshold (extreme medium-term momentum)

        Returns:
            (allowed, reject_reason) - (True, None) if passed, (False, reason) if rejected
        """
        if not self.config.parabolic_detector_enabled:
            return True, None

        # Check if already in cooldown
        is_blocked, remaining_sec = self.parabolic_blacklist.is_blocked(symbol)
        if is_blocked:
            reason = (
                f"PARABOLIC_COOLDOWN_ACTIVE "
                f"(remaining={remaining_sec}s of {self.config.parabolic_cooldown_sec}s)"
            )
            if self.config.parabolic_detector_mode == "live":
                if self.config.parabolic_log_details:
                    logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                return False, reason
            else:
                if self.config.parabolic_log_details:
                    logger.info(f"[SHADOW] {symbol}: Would reject by cooldown – {reason}")
                    logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                return True, None

        # Check data availability
        if accel_5m_pct is None or accel_15m_pct is None:
            if self.config.parabolic_log_details:
                logger.debug(
                    f"[{self.config.parabolic_detector_mode.upper()}] {symbol}: "
                    f"Acceleration data unavailable (accel_5m={accel_5m_pct}, accel_15m={accel_15m_pct})"
                )
            return True, None  # Don't reject if we can't calculate

        # Get thresholds (baseline only for now, regime-aware in Story 5)
        dev_threshold = self.config.parabolic_vwap_dev_min_pct
        accel_5m_threshold = self.config.parabolic_accel_5m_min_pct
        accel_15m_threshold = self.config.parabolic_accel_15m_min_pct

        # Check all three conditions
        condition_1 = vwap_dev_pct >= dev_threshold
        condition_2 = accel_5m_pct >= accel_5m_threshold
        condition_3 = accel_15m_pct >= accel_15m_threshold

        if condition_1 and condition_2 and condition_3:
            # PARABOLIC DETECTED: All three conditions met
            reason = (
                f"PARABOLIC_DETECTED "
                f"(dev={vwap_dev_pct:.1f}%>={dev_threshold}%, "
                f"accel5={accel_5m_pct:.2f}%>={accel_5m_threshold}%, "
                f"accel15={accel_15m_pct:.2f}%>={accel_15m_threshold}%)"
            )

            # Add to blacklist with cooldown (in-memory)
            self.parabolic_blacklist.add(symbol, self.config.parabolic_cooldown_sec)

            # Story 10: Persist to SQLite if enabled
            if self.cooldown_store and self.connector_name and self.config.parabolic_cooldown_persist:
                shadow_mode = self.config.parabolic_detector_mode == "shadow"
                self.cooldown_store.set_cooldown(
                    connector=self.connector_name,
                    symbol=symbol,
                    reason="PARABOLIC_DETECTED",
                    cooldown_sec=self.config.parabolic_cooldown_sec,
                    shadow_mode=shadow_mode
                )

            # EPIC v3.4 Story 6: Emit structured event
            self._emit_entry_guard_event(
                symbol=symbol,
                decision="REJECTED",
                regime=regime,
                reject_reason="PARABOLIC_DETECTED",
                metrics={
                    "vwap_deviation_pct": vwap_dev_pct,
                    "accel_5m_pct": accel_5m_pct,
                    "accel_15m_pct": accel_15m_pct
                },
                thresholds={
                    "vwap_dev_min_pct": dev_threshold,
                    "accel_5m_min_pct": accel_5m_threshold,
                    "accel_15m_min_pct": accel_15m_threshold
                },
                cooldown_remaining_sec=self.config.parabolic_cooldown_sec,
                mode=self.config.parabolic_detector_mode,
                force=True
            )

            if self.config.parabolic_detector_mode == "live":
                # Live mode: actually reject entry
                if self.config.parabolic_log_details:
                    logger.info(
                        f"[LIVE] {symbol}: NO BUY – {reason} "
                        f"→ COOLDOWN {self.config.parabolic_cooldown_sec}s"
                    )
                return False, reason
            else:
                # Shadow mode: log but don't reject
                if self.config.parabolic_log_details:
                    logger.info(
                        f"[SHADOW] {symbol}: Would reject by parabolic detector – {reason}"
                    )
                    logger.info(
                        f"[SHADOW] {symbol}: Would trigger cooldown {self.config.parabolic_cooldown_sec}s"
                    )
                    logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                return True, None  # Allow in shadow mode

        # Passed: Not all conditions met
        return True, None
