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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Import from parent package
# Avoid importing from utils/__init__.py which has heavy dependencies
# Import directly from the module files to keep tests lightweight
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import CandleIndicators  # noqa: E402
from core.reason_codes import ReasonCode, Stage  # noqa: E402
from utils.decision_trace import PairDecisionTrace, trace_percentage_check, trace_range_check  # noqa: E402
from utils.log_throttle import should_log  # noqa: E402


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
    max_trend_4h_pct: float = 99.0
    # Phase 2: Slippage Protection
    slippage_check_enabled: bool = True
    max_entry_spread_pct: float = 0.5
    # Phase 2: Order Book Depth
    depth_check_enabled: bool = True
    min_depth_multiplier: float = 3.0
    # US-001: Fail-closed market data gate
    # When True, entries are BLOCKED if price/orderbook data is unavailable
    # This prevents blind trading without proper market data validation
    require_orderbook: bool = True  # Block entry if orderbook unavailable
    require_price: bool = True      # Block entry if price data unavailable
    # EPIC v3.4: Momentum Guards (optional fields with defaults)
    vwap_slope_guard_enabled: bool = False
    vwap_slope_guard_shadow_mode: bool = True
    vwap_slope_dual_confirmation: bool = True  # Story 9: Require both 5m AND 15m slopes flat
    vwap_slope_deviation_high_pct: float = 15.0
    vwap_slope_min_pct_5m: float = 0.05  # Story 9: 5m slope threshold
    vwap_slope_min_pct_15m: float = 0.10
    vwap_slope_log_details: bool = True
    parabolic_detector_enabled: bool = False
    parabolic_detector_shadow_mode: bool = True
    parabolic_cooldown_persist: bool = True  # Story 10: Persist cooldowns to SQLite
    parabolic_accel_5m_min_pct: float = 2.5
    parabolic_accel_15m_min_pct: float = 6.0
    parabolic_vwap_dev_min_pct: float = 18.0
    parabolic_cooldown_minutes: int = 30
    parabolic_blacklist_scope: str = "session"
    parabolic_log_details: bool = True
    momentum_thresholds: dict = None
    # Story 11: Market Exhaustion Warning
    market_exhaustion_enabled: bool = False
    market_exhaustion_threshold_pct: float = 0.70
    market_exhaustion_sample_size: int = 10
    market_exhaustion_cooldown_min: int = 30
    market_exhaustion_telegram: bool = False
    market_exhaustion_actions: list = None


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
        exchange_connector=None,
        connector_name: Optional[str] = None,
        event_logger=None,  # EPIC v3.4 Story 6: Event logging support
    ):
        """
        Initialize SmartEntry filter

        Args:
            base_cfg: Base configuration with global defaults
            coin_profiles: Dict mapping symbol -> overrides (e.g., {"ATOM-EUR": {"min_wick_ratio": 0.20}})
            logger: Optional logger instance
            exchange_connector: MarketDataProvider instance for order book access
            connector_name: Name of the connector to query (e.g., 'kraken')
            event_logger: Optional EventLogger for structured event tracking (EPIC v3.4)
        """
        self.base_cfg = base_cfg
        self.coin_profiles = coin_profiles or {}  # Handle None from YAML
        self.logger = logger or logging.getLogger(__name__)
        self.exchange_connector = exchange_connector
        self.connector_name = connector_name
        self.event_logger = event_logger  # EPIC v3.4: Store event logger

        self.logger.info("=" * 80)
        self.logger.info("🧠 SmartEntryFilter v2.0 initialized")
        self.logger.info(f"   Base RSI range: [{base_cfg.rsi_extreme_low}, {base_cfg.rsi_buy_max}]")
        self.logger.info(f"   ATR range: [{base_cfg.min_atr_pct_for_grid}, {base_cfg.max_atr_pct_for_grid}]%")
        self.logger.info(f"   Coin profiles loaded: {len(self.coin_profiles)} coins")
        self.logger.info("=" * 80)

    def _get_best_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch best bid/ask from exchange order book.
        Returns (bid, ask) or (None, None) if unavailable.
        """
        if not self.exchange_connector or not self.connector_name:
            return None, None

        try:
            # MarketDataProvider.get_order_book() returns an OrderBook object
            order_book = self.exchange_connector.get_order_book(self.connector_name, symbol)
            if order_book is None:
                return None, None

            # OrderBook has a .snapshot property that returns (bids, asks)
            # where each is a DataFrame or list of (price, amount) tuples
            if not hasattr(order_book, 'snapshot') or order_book.snapshot is None:
                return None, None

            bids, asks = order_book.snapshot

            # Handle empty orderbook
            if bids is None or asks is None:
                return None, None

            # Handle DataFrame vs list formats
            if hasattr(bids, 'empty'):
                # DataFrame format
                if bids.empty or asks.empty:
                    return None, None
                best_bid = float(bids.iloc[0, 0])  # First row, first column (price)
                best_ask = float(asks.iloc[0, 0])
            elif hasattr(bids, '__len__'):
                # List/array format
                if len(bids) == 0 or len(asks) == 0:
                    return None, None
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
            else:
                return None, None

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
            self.logger.debug(f"[SPREAD] {symbol} - Unable to fetch prices, skipping check")
            # US-001: Emit event for tracking
            if self.event_logger:
                try:
                    self.event_logger.emit_gate_denied(
                        correlation_id=f"spread_check_{symbol}",
                        symbol=symbol,
                        stage=Stage.SMART_ENTRY,
                        reason_code=ReasonCode.NO_PRICE_DATA,
                        reason_msg="Prices unavailable for spread check",
                        metadata={"check_type": "spread"},
                        connector=self.connector_name
                    )
                except Exception as e:
                    self.logger.debug(f"Failed to emit gate_denied event: {e}")
            # US-001: Fail-closed - reject entry when price data unavailable
            # Check require_price config flag (default True for safety)
            require_price = getattr(self.base_cfg, 'require_price', True)
            if require_price:
                self.logger.warning(f"[SPREAD] {symbol} - Price data unavailable, BLOCKING entry (fail-closed)")
                return False, "Price data unavailable (fail-closed)", None
            return True, "Prices unavailable (skipping spread check)", None

        if bid_price <= 0 or ask_price <= 0:
            self.logger.warning(f"[SPREAD] {symbol} - Invalid prices: bid={bid_price}, ask={ask_price}")
            # US-001: Fail-closed - also reject when prices are zero/negative
            require_price = getattr(self.base_cfg, 'require_price', True)
            if require_price:
                return False, "Invalid prices (fail-closed)", None
            return True, "Invalid prices (skipping spread check)", None

        mid_price = (bid_price + ask_price) / 2
        spread_pct = float((ask_price - bid_price) / mid_price * 100)

        if spread_pct > max_spread_pct:
            return False, (
                f"Spread too wide: {spread_pct:.3f}% > {max_spread_pct}% "
                f"(bid={bid_price:.4f}, ask={ask_price:.4f})"
            ), spread_pct

        return True, f"Spread OK: {spread_pct:.3f}%", spread_pct

    def _check_order_book_depth(self, symbol: str, order_size_eur: float,
                                min_depth_multiplier: float) -> Tuple[bool, str, float, float]:
        """
        Check if order book has sufficient depth for safe order execution.

        Uses liquidity_proxy utility for standardized depth calculation.

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            order_size_eur: Order size in quote currency
            min_depth_multiplier: Required depth as multiplier of order size (e.g., 5.0 = 5x)

        Returns:
            (is_ok, reason, depth_available, depth_required)
        """
        if not self.exchange_connector:
            self.logger.debug(f"[DEPTH] {symbol} - Exchange connector not available, skipping check")
            return True, "Depth check disabled (no exchange connector)", 0.0, 0.0

        try:
            from decimal import Decimal

            # Import inside function to avoid circular imports
            try:
                from multi_coin_grid_pro.controllers.utils.liquidity_proxy import (
                    calculate_orderbook_depth,
                    format_depth_log,
                    get_orderbook_snapshot,
                    is_sufficient_depth,
                )
            except ImportError:
                from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import (
                    calculate_orderbook_depth,
                    format_depth_log,
                    get_orderbook_snapshot,
                    is_sufficient_depth,
                )

            # Get orderbook snapshot (with retry logic)
            bids, asks, mid_price = get_orderbook_snapshot(self.exchange_connector, symbol)

            if not bids or not asks or not mid_price:
                if should_log(f"depth_no_ob_{symbol}", interval_sec=300):
                    self.logger.warning(f"[DEPTH] {symbol} - No orderbook data available (depth check skipped)")
                # Do NOT emit gate_denied here: the depth check is skipped (returns True),
                # so counting this as a denial inflates NO_ORDERBOOK_DATA stats incorrectly.
                return True, "No orderbook data (skipping check)", 0.0, 0.0

            # Calculate depth metrics (bids/asks are List[OrderBookRow], mid_price is Decimal)
            depth_metrics = calculate_orderbook_depth(
                bids=bids,
                asks=asks,
                mid_price=mid_price,
                pct_range=0.5,  # ±0.5% around mid price
                max_levels=10   # Top 10 levels per side
            )

            # Check if depth is sufficient
            order_size_decimal = Decimal(str(order_size_eur))
            is_ok, required_depth = is_sufficient_depth(
                depth_score=depth_metrics.depth_score,
                order_size_quote=order_size_decimal,
                multiplier=min_depth_multiplier,
                tolerance_pct=10.0  # 10% tolerance
            )

            # Format log message
            log_msg = format_depth_log(
                symbol=symbol,
                metrics=depth_metrics,
                order_size=order_size_decimal,
                multiplier=min_depth_multiplier,
                is_sufficient=is_ok
            )

            if is_ok:
                self.logger.debug(f"[DEPTH] {log_msg}")
                return True, f"Sufficient depth ({min_depth_multiplier}x confirmed)", \
                    float(depth_metrics.depth_score), float(required_depth)
            else:
                self.logger.warning(f"[DEPTH] {log_msg}")
                return False, \
                    f"Insufficient liquidity: depth={depth_metrics.depth_score:.1f} " \
                    f"< required={required_depth:.1f} ({min_depth_multiplier}x)", \
                    float(depth_metrics.depth_score), float(required_depth)

        except Exception as e:
            self.logger.warning(f"[DEPTH] {symbol} - Error checking depth: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
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
            "max_trend_4h_pct": self.base_cfg.max_trend_4h_pct,
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
        vwap_slope_15m_pct: Optional[float] = None,  # EPIC v3.4 Story 6
        accel_5m_pct: Optional[float] = None,  # EPIC v3.4 Story 6
        accel_15m_pct: Optional[float] = None,  # EPIC v3.4 Story 6
        regime: str = "CHOP",  # EPIC v3.4 Story 6
    ) -> Tuple[bool, str, Optional[PairDecisionTrace]]:
        """
        Check if entry is allowed for this symbol based on indicators

        Args:
            symbol: Trading pair (e.g., "ATOM-EUR")
            ind: CandleIndicators with all technical data
            exchange: Exchange name (for trace)
            trace_enabled: Enable decision tracing
            order_size_eur: Order size for depth checks
            bid_price: Optional bid price override
            ask_price: Optional ask price override
            vwap_slope_15m_pct: VWAP momentum slope (EPIC v3.4)
            accel_5m_pct: 5-minute price acceleration (EPIC v3.4)
            accel_15m_pct: 15-minute price acceleration (EPIC v3.4)
            regime: Market regime (BULL/CHOP/BEAR) (EPIC v3.4)

        Returns:
            Tuple of (allowed: bool, reason: str, trace: Optional[PairDecisionTrace])
            - If allowed=True, reason explains why entry is OK
            - If allowed=False, reason explains which filter blocked it
            - trace: Optional decision trace (None if trace_enabled=False)
        """
        # Create trace (zero overhead if disabled)
        # Fix #1: Generate correlation_id here (single source of truth per evaluation)
        import uuid
        correlation_id = str(uuid.uuid4()) if trace_enabled else None

        trace = PairDecisionTrace(
            trading_pair=symbol,
            exchange=exchange,
            enabled=trace_enabled,
            strategy="spot_grid"
        )
        if trace_enabled and correlation_id:
            trace.correlation_id = correlation_id
            trace.stage = Stage.SMART_ENTRY.value  # Fix #2: Set stage early for pass/fail

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
                trace.reason_code = ReasonCode.SPREAD_TOO_WIDE.value
                trace.stage = Stage.SMART_ENTRY.value
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
            # US-001: Fail-closed gate - REJECT if orderbook data is unavailable
            # This prevents blind trading without proper market data validation
            if not depth_ok and depth_available > 0:
                trace.finalize(accepted=False, rejected_by="depth", final_reason="insufficient depth")
                trace.reason_code = ReasonCode.DEPTH_INSUFFICIENT.value
                trace.stage = Stage.SMART_ENTRY.value
                return False, f"🧠 {symbol}: NO BUY – {depth_reason}", trace
            elif not depth_ok:
                # US-001: Depth data unavailable - REJECT entry (fail-closed)
                # Previously this was allowed, but blind entries cause losses
                trace.finalize(accepted=False, rejected_by="depth", final_reason="no orderbook data")
                trace.reason_code = ReasonCode.NO_ORDERBOOK_DATA.value
                trace.stage = Stage.SMART_ENTRY.value
                self.logger.warning(f"[DEPTH] {symbol} - Orderbook unavailable, BLOCKING entry (fail-closed)")
                return False, f"🧠 {symbol}: NO BUY – orderbook data unavailable (fail-closed)", trace

        # 1) RSI Regime Checks
        # Use rsi_block_min (max overbought threshold) - allows coin profiles to override
        rsi_block_ok = trace_range_check(trace, "rsi_block", ind.rsi_14, 0, cfg["rsi_block_min"])
        if not rsi_block_ok:
            trace.finalize(accepted=False, rejected_by="rsi_block", final_reason="overbought")
            trace.reason_code = ReasonCode.RSI_OVERBOUGHT.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – RSI {ind.rsi_14:.1f} >= {cfg['rsi_block_min']} (overbought)", trace

        rsi_buy_ok = trace_percentage_check(trace, "rsi_buy_max", ind.rsi_14, cfg["rsi_buy_max"], "<=")
        if not rsi_buy_ok:
            trace.finalize(accepted=False, rejected_by="rsi_buy_max", final_reason="overbought")
            trace.reason_code = ReasonCode.RSI_OVERBOUGHT.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – RSI {ind.rsi_14:.1f} > {cfg['rsi_buy_max']} (overbought)", trace

        rsi_extreme_ok = trace_percentage_check(trace, "rsi_extreme", ind.rsi_14, cfg["rsi_extreme_low"], ">=")
        if not rsi_extreme_ok:
            trace.finalize(accepted=False, rejected_by="rsi_extreme", final_reason="falling knife risk")
            trace.reason_code = ReasonCode.RSI_OVERSOLD.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – RSI {
                ind.rsi_14:.1f} < {
                cfg['rsi_extreme_low']} (falling knife risk)", trace

        # 2) VWAP Mean Reversion Check
        vwap_dev = 0.0
        if ind.vwap > 0:
            vwap_dev = float((ind.price - ind.vwap) / ind.vwap * 100)
        vwap_ok = trace_percentage_check(trace, "vwap_deviation", abs(vwap_dev), cfg["vwap_max_deviation_pct"], "<=")
        if not vwap_ok:
            trace.finalize(accepted=False, rejected_by="vwap_deviation", final_reason="too far from VWAP")
            trace.reason_code = ReasonCode.VWAP_DEVIATION_TOO_HIGH.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – VWAP dev {vwap_dev:+.2f}% > ±{cfg['vwap_max_deviation_pct']}%", trace

        # 3) Wick Structure Check (candle quality)
        wick_ok = trace_percentage_check(trace, "wick_ratio", ind.wick_ratio, cfg["min_wick_ratio"], ">=")
        if not wick_ok:
            trace.finalize(accepted=False, rejected_by="wick_ratio", final_reason="poor candle structure")
            trace.reason_code = ReasonCode.WICK_RATIO_LOW.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – wick_ratio {
                ind.wick_ratio:.2f} < {
                cfg['min_wick_ratio']} (poor structure)", trace

        # 4) ATR Volatility Regime
        atr_min_ok = trace_percentage_check(trace, "atr_min", ind.atr_pct, cfg["min_atr_pct_for_grid"], ">=")
        if not atr_min_ok:
            trace.finalize(accepted=False, rejected_by="atr_min", final_reason="volatility too low")
            trace.reason_code = ReasonCode.ATR_TOO_LOW.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – ATR {
                ind.atr_pct:.2f}% < {
                cfg['min_atr_pct_for_grid']}% (too low)", trace

        atr_max_ok = trace_percentage_check(trace, "atr_max", ind.atr_pct, cfg["max_atr_pct_for_grid"], "<=")
        if not atr_max_ok:
            trace.finalize(accepted=False, rejected_by="atr_max", final_reason="too chaotic")
            trace.reason_code = ReasonCode.ATR_TOO_HIGH.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – ATR {
                ind.atr_pct:.2f}% > {
                cfg['max_atr_pct_for_grid']}% (too chaotic)", trace

        # 5) 5m Spike Detection (news/chaos filter)
        spike_5m = abs(ind.change_5m_pct)
        spike_ok = trace_percentage_check(trace, "spike_5m", spike_5m, cfg["max_5m_spike_pct"], "<=")
        if not spike_ok:
            trace.finalize(accepted=False, rejected_by="spike_5m", final_reason="sudden price spike")
            trace.reason_code = ReasonCode.SPIKE_5M_EXCESSIVE.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – 5m move {
                ind.change_5m_pct:+.2f}% > ±{
                cfg['max_5m_spike_pct']}% (spike detected)", trace

        # 6) Trend Acceleration Check (1h vs 4h)
        accel = ind.trend_1h_pct - ind.trend_4h_pct

        accel_down_ok = trace_percentage_check(trace, "down_acceleration", accel, cfg["max_down_accel_pct"], ">=")
        if not accel_down_ok:
            trace.finalize(accepted=False, rejected_by="down_acceleration", final_reason="falling knife detected")
            trace.reason_code = ReasonCode.ACCEL_FALLING_KNIFE.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – down accel {
                accel:.2f}% < {
                cfg['max_down_accel_pct']}% (falling knife)", trace

        accel_up_ok = trace_percentage_check(trace, "up_acceleration", accel, cfg["max_up_accel_pct"], "<=")
        if not accel_up_ok:
            trace.finalize(accepted=False, rejected_by="up_acceleration", final_reason="blow-off top risk")
            trace.reason_code = ReasonCode.ACCEL_BLOWOFF.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – up accel {
                accel:.2f}% > {
                cfg['max_up_accel_pct']}% (blow-off top risk)", trace

        # 6b) 4h Trend Cap (RE-01: entries after 4h rally perform worse)
        trend_4h_ok = trace_percentage_check(
            trace, "trend_4h_max", ind.trend_4h_pct, cfg["max_trend_4h_pct"], "<=")
        if not trend_4h_ok:
            trace.finalize(accepted=False, rejected_by="trend_4h_max",
                           final_reason="4h trend too high")
            trace.reason_code = ReasonCode.TREND_4H_TOO_HIGH.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – 4h trend {
                ind.trend_4h_pct:+.2f}% > {
                cfg['max_trend_4h_pct']}% (post-rally risk)", trace

        # 7) 24h Trend Sanity Checks
        trend_24h_max_ok = trace_percentage_check(
            trace, "trend_24h_max", ind.trend_24h_pct, cfg["max_trend_24h_pct"], "<=")
        if not trend_24h_max_ok:
            trace.finalize(accepted=False, rejected_by="trend_24h_max", final_reason="extended run")
            trace.reason_code = ReasonCode.TREND_24H_OUT_OF_RANGE.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – 24h trend {
                ind.trend_24h_pct:+.2f}% > {
                cfg['max_trend_24h_pct']}% (extended run)", trace

        trend_24h_min_ok = trace_percentage_check(
            trace, "trend_24h_min", ind.trend_24h_pct, cfg["min_trend_24h_pct"], ">=")
        if not trend_24h_min_ok:
            trace.finalize(accepted=False, rejected_by="trend_24h_min", final_reason="capitulation zone")
            trace.reason_code = ReasonCode.TREND_24H_OUT_OF_RANGE.value
            trace.stage = Stage.SMART_ENTRY.value
            return False, f"🧠 {symbol}: NO BUY – 24h trend {
                ind.trend_24h_pct:+.2f}% < {
                cfg['min_trend_24h_pct']}% (capitulation zone)", trace

        # All checks passed!
        # Fix #2: Stage already set at trace creation, no reason_code on success
        trace.finalize(accepted=True, final_reason="all SmartEntry filters passed")
        return True, (
            f"✅ {symbol}: BUY ALLOWED – SmartEntry v2.0 passed "
            f"(RSI={ind.rsi_14:.1f}, ATR={ind.atr_pct:.2f}%, wick={ind.wick_ratio:.2f})"
        ), trace
