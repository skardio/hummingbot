"""
SmartEntryFilter v2.0 with Coin Profiles Support

This module implements intelligent entry filtering based on:
- RSI regimes (avoid overbought/oversold extremes)
- VWAP mean reversion
- Candle structure (wick ratio)
- ATR volatility regimes
- Trend acceleration detection
- 24h trend sanity checks

Each coin can have custom thresholds via coin_profiles in config.
"""
import logging

# Import from parent package
import sys
from dataclasses import dataclass
# from decimal import Decimal  # noqa: F401
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import CandleIndicators
from utils.decision_trace import PairDecisionTrace, trace_percentage_check, trace_range_check


@dataclass
class SmartEntryBaseConfig:
    """Base configuration for SmartEntry filter (global defaults)"""
    rsi_buy_max: float
    rsi_extreme_low: float
    rsi_block_min: float
    vwap_max_deviation_pct: float
    min_wick_ratio: float
    max_atr_pct_for_grid: float
    min_atr_pct_for_grid: float
    max_5m_spike_pct: float
    max_down_accel_pct: float
    max_up_accel_pct: float
    max_trend_24h_pct: float
    min_trend_24h_pct: float
    # Phase 2: Slippage Protection
    slippage_check_enabled: bool = True
    max_entry_spread_pct: float = 0.5
    # Phase 2: Order Book Depth
    depth_check_enabled: bool = True
    min_depth_multiplier: float = 3.0


class SmartEntryFilter:
    """
    SmartEntry v2.0 - Intelligent entry filter with coin-specific profiles

    Usage:
        base_cfg = SmartEntryBaseConfig(**config["smart_entry_filter"])
        coin_profiles = config.get("coin_profiles", {})
        filter = SmartEntryFilter(base_cfg, coin_profiles, logger)

        allowed, reason = filter.allows_entry(symbol, indicators)
        if allowed:
            # Place orders
        else:
            logger.info(reason)
    """

    def __init__(
        self,
        base_cfg: SmartEntryBaseConfig,
        coin_profiles: Dict[str, Dict[str, Any]],
        logger: Optional[logging.Logger] = None,
        exchange=None,
    ):
        """
        Initialize SmartEntry filter

        Args:
            base_cfg: Base configuration with global defaults
            coin_profiles: Dict mapping symbol -> overrides (e.g., {"ATOM-EUR": {"min_wick_ratio": 0.20}})
            logger: Optional logger instance
        """
        self.base_cfg = base_cfg
        self.coin_profiles = coin_profiles
        self.logger = logger or logging.getLogger(__name__)
        self.exchange = exchange

        self.logger.info("=" * 80)
        self.logger.info("🧠 SmartEntryFilter v2.0 initialized")
        self.logger.info(f"   Base RSI range: [{base_cfg.rsi_extreme_low}, {base_cfg.rsi_buy_max}]")
        self.logger.info(f"   ATR range: [{base_cfg.min_atr_pct_for_grid}, {base_cfg.max_atr_pct_for_grid}]%")
        self.logger.info(f"   Coin profiles loaded: {len(coin_profiles)} coins")
        self.logger.info("=" * 80)

    def _get_best_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch best bid/ask from exchange order book.
        Returns (bid, ask) or (None, None) if unavailable.
        """
        if not self.exchange:
            return None, None

        try:
            order_book = self.exchange.get_order_book(symbol)
            if not order_book or 'bids' not in order_book or 'asks' not in order_book:
                return None, None

            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])
            if not bids or not asks:
                return None, None

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            return best_bid, best_ask
        except Exception as e:
            self.logger.warning(f"[SPREAD] {symbol} - Error fetching bid/ask: {e}")
            return None, None

    def _check_spread(
        self,
        symbol: str,
        bid_price: Optional[float],
        ask_price: Optional[float],
        max_spread_pct: float,
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Check if bid-ask spread is acceptable.
        Uses the same logic and thresholds as legacy SmartEntryFilter.
        """
        if bid_price is None or ask_price is None:
            bid_price, ask_price = self._get_best_bid_ask(symbol)

        if bid_price is None or ask_price is None:
            self.logger.warning(f"[SPREAD] {symbol} - Invalid prices: bid={bid_price}, ask={ask_price}")
            return True, "Invalid prices (skipping check)", None

        if bid_price <= 0 or ask_price <= 0:
            self.logger.warning(f"[SPREAD] {symbol} - Invalid prices: bid={bid_price}, ask={ask_price}")
            return True, "Invalid prices (skipping check)", None

        mid_price = (bid_price + ask_price) / 2
        spread_pct = float((ask_price - bid_price) / mid_price * 100)

        if spread_pct > max_spread_pct:
            return False, (
                f"Spread too wide: {spread_pct:.3f}% > {max_spread_pct}% "
                f"(bid={bid_price:.4f}, ask={ask_price:.4f})"
            ), spread_pct

        return True, f"Spread OK: {spread_pct:.3f}%", spread_pct

    def _check_order_book_depth(self, symbol: str, order_size_eur: float, min_depth_multiplier: float) -> Tuple[bool, str, float, float]:
        """
        Check if order book has sufficient depth for order.
        Uses the same logic and thresholds as legacy SmartEntryFilter.
        """
        if not self.exchange:
            return True, "Depth check disabled or no exchange", 0.0, 0.0

        try:
            required_depth = order_size_eur * min_depth_multiplier

            order_book = self.exchange.get_order_book(symbol)

            if not order_book or 'bids' not in order_book or 'asks' not in order_book:
                self.logger.warning(f"[DEPTH] {symbol} - No order book data available")
                return True, "No order book data (skipping check)", 0.0, required_depth

            bid_total_eur = 0.0
            for bid_price, bid_volume in order_book['bids']:
                bid_total_eur += float(bid_price) * float(bid_volume)
                if bid_total_eur >= required_depth:
                    break

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
                    f"ASK {ask_total_eur:.0f}/{required_depth:.0f} EUR (need {min_depth_multiplier}x)"
                ), min(bid_total_eur, ask_total_eur), required_depth

            return True, f"Sufficient depth ({min_depth_multiplier}x confirmed)", min(bid_total_eur, ask_total_eur), required_depth

        except Exception as e:
            self.logger.warning(f"[DEPTH] {symbol} - Error checking depth: {e}")
            return True, f"Depth check failed (allowing entry): {e}", 0.0, 0.0

    def _get_effective_cfg(self, symbol: str) -> Dict[str, Any]:
        """
        Get effective configuration for a symbol (base + profile overrides)

        Args:
            symbol: Trading pair symbol (e.g., "ATOM-EUR")

        Returns:
            Dict with all effective parameters
        """
        cfg = {
            "rsi_buy_max": self.base_cfg.rsi_buy_max,
            "rsi_extreme_low": self.base_cfg.rsi_extreme_low,
            "rsi_block_min": self.base_cfg.rsi_block_min,
            "vwap_max_deviation_pct": self.base_cfg.vwap_max_deviation_pct,
            "min_wick_ratio": self.base_cfg.min_wick_ratio,
            "max_atr_pct_for_grid": self.base_cfg.max_atr_pct_for_grid,
            "min_atr_pct_for_grid": self.base_cfg.min_atr_pct_for_grid,
            "max_5m_spike_pct": self.base_cfg.max_5m_spike_pct,
            "max_down_accel_pct": self.base_cfg.max_down_accel_pct,
            "max_up_accel_pct": self.base_cfg.max_up_accel_pct,
            "max_trend_24h_pct": self.base_cfg.max_trend_24h_pct,
            "min_trend_24h_pct": self.base_cfg.min_trend_24h_pct,
            # Phase 2: Slippage Protection
            "slippage_check_enabled": self.base_cfg.slippage_check_enabled,
            "max_entry_spread_pct": self.base_cfg.max_entry_spread_pct,
            # Phase 2: Order Book Depth
            "depth_check_enabled": self.base_cfg.depth_check_enabled,
            "min_depth_multiplier": self.base_cfg.min_depth_multiplier,
        }

        # Apply coin-specific overrides
        profile = self.coin_profiles.get(symbol, {})
        if profile:
            self.logger.debug(f"Applying profile overrides for {symbol}: {profile}")
            cfg.update(profile)

        return cfg

    def allows_entry(
        self,
        symbol: str,
        ind: CandleIndicators,
        exchange: str = "unknown",
        trace_enabled: bool = False,
        order_size_eur: Optional[float] = None,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[PairDecisionTrace]]:
        """
        Check if entry is allowed for this symbol based on indicators

        Args:
            symbol: Trading pair (e.g., "ATOM-EUR")
            ind: CandleIndicators with all technical data
            exchange: Exchange name (for trace)
            trace_enabled: Enable decision tracing

        Returns:
            Tuple of (allowed: bool, reason: str, trace: Optional[PairDecisionTrace])
            - If allowed=True, reason explains why entry is OK
            - If allowed=False, reason explains which filter blocked it
            - trace: Optional decision trace (None if trace_enabled=False)
        """
        # Create trace (zero overhead if disabled)
        trace = PairDecisionTrace(
            trading_pair=symbol,
            exchange=exchange,
            enabled=trace_enabled,
            strategy="spot_grid"
        )

        cfg = self._get_effective_cfg(symbol)

        # 0) Slippage Protection - Check spread
        if cfg["slippage_check_enabled"]:
            spread_ok, spread_reason, spread_pct = self._check_spread(
                symbol,
                bid_price,
                ask_price,
                cfg["max_entry_spread_pct"],
            )
            trace.add_check(
                filter_name="spread",
                value=spread_pct,
                threshold=cfg["max_entry_spread_pct"],
                passed=spread_ok,
                operator="<="
            )
            if not spread_ok:
                trace.finalize(accepted=False, rejected_by="spread", final_reason="spread too wide")
                return False, f"🧠 {symbol}: NO BUY – {spread_reason}", trace

        # 0B) Order Book Depth Check
        if cfg["depth_check_enabled"] and order_size_eur:
            depth_ok, depth_reason, depth_available, depth_required = self._check_order_book_depth(
                symbol,
                order_size_eur,
                cfg["min_depth_multiplier"],
            )
            trace.add_check(
                filter_name="depth",
                value=depth_available,
                threshold=depth_required,
                passed=depth_ok,
                operator=">="
            )
            if not depth_ok:
                trace.finalize(accepted=False, rejected_by="depth", final_reason="insufficient depth")
                return False, f"🧠 {symbol}: NO BUY – {depth_reason}", trace

        # 1) RSI Regime Checks
        # Use rsi_block_min (max overbought threshold) - allows coin profiles to override
        rsi_block_ok = trace_range_check(trace, "rsi_block", ind.rsi_14, 0, cfg["rsi_block_min"])
        if not rsi_block_ok:
            trace.finalize(accepted=False, rejected_by="rsi_block", final_reason="overbought")
            return False, f"🧠 {symbol}: NO BUY – RSI {ind.rsi_14:.1f} >= {cfg['rsi_block_min']} (overbought)", trace

        rsi_buy_ok = trace_percentage_check(trace, "rsi_buy_max", ind.rsi_14, cfg["rsi_buy_max"], "<=")
        if not rsi_buy_ok:
            trace.finalize(accepted=False, rejected_by="rsi_buy_max", final_reason="overbought")
            return False, f"🧠 {symbol}: NO BUY – RSI {ind.rsi_14:.1f} > {cfg['rsi_buy_max']} (overbought)", trace

        rsi_extreme_ok = trace_percentage_check(trace, "rsi_extreme", ind.rsi_14, cfg["rsi_extreme_low"], ">=")
        if not rsi_extreme_ok:
            trace.finalize(accepted=False, rejected_by="rsi_extreme", final_reason="falling knife risk")
            return False, f"🧠 {symbol}: NO BUY – RSI {ind.rsi_14:.1f} < {cfg['rsi_extreme_low']} (falling knife risk)", trace

        # 2) VWAP Mean Reversion Check
        vwap_dev = 0.0
        if ind.vwap > 0:
            vwap_dev = float((ind.price - ind.vwap) / ind.vwap * 100)
        vwap_ok = trace_percentage_check(trace, "vwap_deviation", abs(vwap_dev), cfg["vwap_max_deviation_pct"], "<=")
        if not vwap_ok:
            trace.finalize(accepted=False, rejected_by="vwap_deviation", final_reason="too far from VWAP")
            return False, f"🧠 {symbol}: NO BUY – VWAP dev {vwap_dev:+.2f}% > ±{cfg['vwap_max_deviation_pct']}%", trace

        # 3) Wick Structure Check (candle quality)
        wick_ok = trace_percentage_check(trace, "wick_ratio", ind.wick_ratio, cfg["min_wick_ratio"], ">=")
        if not wick_ok:
            trace.finalize(accepted=False, rejected_by="wick_ratio", final_reason="poor candle structure")
            return False, f"🧠 {symbol}: NO BUY – wick_ratio {ind.wick_ratio:.2f} < {cfg['min_wick_ratio']} (poor structure)", trace

        # 4) ATR Volatility Regime
        atr_min_ok = trace_percentage_check(trace, "atr_min", ind.atr_pct, cfg["min_atr_pct_for_grid"], ">=")
        if not atr_min_ok:
            trace.finalize(accepted=False, rejected_by="atr_min", final_reason="volatility too low")
            return False, f"🧠 {symbol}: NO BUY – ATR {ind.atr_pct:.2f}% < {cfg['min_atr_pct_for_grid']}% (too low)", trace

        atr_max_ok = trace_percentage_check(trace, "atr_max", ind.atr_pct, cfg["max_atr_pct_for_grid"], "<=")
        if not atr_max_ok:
            trace.finalize(accepted=False, rejected_by="atr_max", final_reason="too chaotic")
            return False, f"🧠 {symbol}: NO BUY – ATR {ind.atr_pct:.2f}% > {cfg['max_atr_pct_for_grid']}% (too chaotic)", trace

        # 5) 5m Spike Detection (news/chaos filter)
        spike_5m = abs(ind.change_5m_pct)
        spike_ok = trace_percentage_check(trace, "spike_5m", spike_5m, cfg["max_5m_spike_pct"], "<=")
        if not spike_ok:
            trace.finalize(accepted=False, rejected_by="spike_5m", final_reason="sudden price spike")
            return False, f"🧠 {symbol}: NO BUY – 5m move {ind.change_5m_pct:+.2f}% > ±{cfg['max_5m_spike_pct']}% (spike detected)", trace

        # 6) Trend Acceleration Check (1h vs 4h)
        accel = ind.trend_1h_pct - ind.trend_4h_pct

        accel_down_ok = trace_percentage_check(trace, "down_acceleration", accel, cfg["max_down_accel_pct"], ">=")
        if not accel_down_ok:
            trace.finalize(accepted=False, rejected_by="down_acceleration", final_reason="falling knife detected")
            return False, f"🧠 {symbol}: NO BUY – down accel {accel:.2f}% < {cfg['max_down_accel_pct']}% (falling knife)", trace

        accel_up_ok = trace_percentage_check(trace, "up_acceleration", accel, cfg["max_up_accel_pct"], "<=")
        if not accel_up_ok:
            trace.finalize(accepted=False, rejected_by="up_acceleration", final_reason="blow-off top risk")
            return False, f"🧠 {symbol}: NO BUY – up accel {accel:.2f}% > {cfg['max_up_accel_pct']}% (blow-off top risk)", trace

        # 7) 24h Trend Sanity Checks
        trend_24h_max_ok = trace_percentage_check(trace, "trend_24h_max", ind.trend_24h_pct, cfg["max_trend_24h_pct"], "<=")
        if not trend_24h_max_ok:
            trace.finalize(accepted=False, rejected_by="trend_24h_max", final_reason="extended run")
            return False, f"🧠 {symbol}: NO BUY – 24h trend {ind.trend_24h_pct:+.2f}% > {cfg['max_trend_24h_pct']}% (extended run)", trace

        trend_24h_min_ok = trace_percentage_check(trace, "trend_24h_min", ind.trend_24h_pct, cfg["min_trend_24h_pct"], ">=")
        if not trend_24h_min_ok:
            trace.finalize(accepted=False, rejected_by="trend_24h_min", final_reason="capitulation zone")
            return False, f"🧠 {symbol}: NO BUY – 24h trend {ind.trend_24h_pct:+.2f}% < {cfg['min_trend_24h_pct']}% (capitulation zone)", trace

        # All checks passed!
        trace.finalize(accepted=True, final_reason="all SmartEntry filters passed")
        return True, (
            f"✅ {symbol}: BUY ALLOWED – SmartEntry v2.0 passed "
            f"(RSI={ind.rsi_14:.1f}, ATR={ind.atr_pct:.2f}%, wick={ind.wick_ratio:.2f})"
        ), trace
