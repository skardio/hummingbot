"""
INTEGRATION EXAMPLE: SmartEntry Filter met Decision Trace

Dit toont hoe je de decision trace integreert in bestaande filter logic
zonder de core functionaliteit te breken.

Key principles:
1. Zero performance impact when disabled
2. Non-intrusive (adds tracing without changing logic)
3. Production-safe (errors in tracing don't break trading)
"""

# from decimal import Decimal  # noqa: F401
from typing import Dict, Tuple

from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace, trace_percentage_check


def smart_entry_check_with_trace(
    symbol: str,
    exchange: str,
    ind: Dict,  # indicators dict
    cfg: Dict,  # config dict
    trace_enabled: bool = False
) -> Tuple[bool, str, PairDecisionTrace]:
    """
    SmartEntry filter met volledige decision trace.

    BEFORE:
        return bool, str (allowed, reason)

    AFTER:
        return bool, str, PairDecisionTrace (allowed, reason, trace)

    Usage:
        allowed, reason, trace = smart_entry_check_with_trace(...)
        if trace.enabled:
            logger.info(trace.to_compact_log())
    """

    # Create trace
    trace = PairDecisionTrace(
        trading_pair=symbol,
        exchange=exchange,
        enabled=trace_enabled,
        strategy="spot_grid"
    )

    # Track each filter check
    # The pattern: check condition, add to trace, return if failed

    # 1) RSI Checks
    rsi_buy_ok = trace_percentage_check(
        trace, "rsi_buy_max", ind["rsi"], cfg["rsi_buy_max"], "<="
    )
    if not rsi_buy_ok:
        trace.finalize(accepted=False, rejected_by="rsi_buy_max", final_reason="overbought")
        return False, f"🧠 {symbol}: NO BUY – RSI {ind['rsi']:.1f} > {cfg['rsi_buy_max']} (overbought)", trace

    rsi_block_ok = trace_percentage_check(
        trace, "rsi_block_min", ind["rsi"], cfg["rsi_block_min"], "<"
    )
    if not rsi_block_ok:
        trace.finalize(accepted=False, rejected_by="rsi_block_min", final_reason="extreme overbought")
        return False, f"🧠 {symbol}: NO BUY – RSI {ind['rsi']:.1f} >= {cfg['rsi_block_min']} (extreme overbought)", trace

    # 2) VWAP Deviation
    vwap_dev = abs(ind["vwap_deviation_pct"])
    vwap_ok = trace_percentage_check(
        trace, "vwap_deviation", vwap_dev, cfg["vwap_max_deviation_pct"], "<="
    )
    if not vwap_ok:
        trace.finalize(accepted=False, rejected_by="vwap_deviation", final_reason="too far from VWAP")
        return False,
        f"🧠 {symbol}: NO BUY – VWAP dev {ind['vwap_deviation_pct']:+.2f}% > ±{cfg['vwap_max_deviation_pct']}%",
        trace

    # 3) Wick Ratio (candle structure)
    wick_ok = trace_percentage_check(
        trace, "wick_ratio", ind["wick_ratio"], cfg["min_wick_ratio"], ">="
    )
    if not wick_ok:
        trace.finalize(accepted=False, rejected_by="wick_ratio", final_reason="poor candle structure")
        return False, f"🧠 {symbol}: NO BUY – wick_ratio {
            ind['wick_ratio']:.2f} < {
            cfg['min_wick_ratio']} (poor structure)", trace

    # 4) ATR Volatility Range
    atr_min_ok = trace_percentage_check(
        trace, "atr_min", ind["atr_pct"], cfg["min_atr_pct_for_grid"], ">="
    )
    if not atr_min_ok:
        trace.finalize(accepted=False, rejected_by="atr_min", final_reason="volatility too low")
        return False, f"🧠 {symbol}: NO BUY – ATR {
            ind['atr_pct']:.2f}% < {
            cfg['min_atr_pct_for_grid']}% (too low)", trace

    atr_max_ok = trace_percentage_check(
        trace, "atr_max", ind["atr_pct"], cfg["max_atr_pct_for_grid"], "<="
    )
    if not atr_max_ok:
        trace.finalize(accepted=False, rejected_by="atr_max", final_reason="too chaotic")
        return False, f"🧠 {symbol}: NO BUY – ATR {
            ind['atr_pct']:.2f}% > {
            cfg['max_atr_pct_for_grid']}% (too chaotic)", trace

    # 5) 5-minute spike detection
    spike_5m = abs(ind["change_5m_pct"])
    spike_ok = trace_percentage_check(
        trace, "spike_5m", spike_5m, cfg["max_5m_spike_pct"], "<="
    )
    if not spike_ok:
        trace.finalize(accepted=False, rejected_by="spike_5m", final_reason="sudden price spike")
        return False, f"🧠 {symbol}: NO BUY – 5m move {
            ind['change_5m_pct']:+.2f}% > ±{
            cfg['max_5m_spike_pct']}% (spike detected)", trace

    # 6) Trend Acceleration (1h vs 4h)
    accel = ind["trend_1h_pct"] - ind["trend_4h_pct"]

    accel_down_ok = trace_percentage_check(
        trace, "down_acceleration", accel, cfg["max_down_accel_pct"], ">="
    )
    if not accel_down_ok:
        trace.finalize(accepted=False, rejected_by="down_acceleration", final_reason="falling knife detected")
        return False, f"🧠 {symbol}: NO BUY – down accel {
            accel:.2f}% < {
            cfg['max_down_accel_pct']}% (falling knife)", trace

    accel_up_ok = trace_percentage_check(
        trace, "up_acceleration", accel, cfg["max_up_accel_pct"], "<="
    )
    if not accel_up_ok:
        trace.finalize(accepted=False, rejected_by="up_acceleration", final_reason="blow-off top risk")
        return False, f"🧠 {symbol}: NO BUY – up accel {
            accel:.2f}% > {
            cfg['max_up_accel_pct']}% (blow-off top risk)", trace

    # 7) 24h Trend Sanity Checks
    trend_24h_max_ok = trace_percentage_check(
        trace, "trend_24h_max", ind["trend_24h_pct"], cfg["max_trend_24h_pct"], "<="
    )
    if not trend_24h_max_ok:
        trace.finalize(accepted=False, rejected_by="trend_24h_max", final_reason="extended run")
        return False, f"🧠 {symbol}: NO BUY – 24h trend {
            ind['trend_24h_pct']:+.2f}% > {
            cfg['max_trend_24h_pct']}% (extended run)", trace

    trend_24h_min_ok = trace_percentage_check(
        trace, "trend_24h_min", ind["trend_24h_pct"], cfg["min_trend_24h_pct"], ">="
    )
    if not trend_24h_min_ok:
        trace.finalize(accepted=False, rejected_by="trend_24h_min", final_reason="capitulation zone")
        return False, f"🧠 {symbol}: NO BUY – 24h trend {
            ind['trend_24h_pct']:+.2f}% < {
            cfg['min_trend_24h_pct']}% (capitulation zone)", trace

    # All checks passed!
    trace.finalize(accepted=True, final_reason="all SmartEntry filters passed")

    return True, (
        f"✅ {symbol}: BUY ALLOWED – SmartEntry v2.0 passed "
        f"(RSI {ind['rsi']:.1f}, VWAP {ind['vwap_deviation_pct']:+.1f}%, ATR {ind['atr_pct']:.2f}%)"
    ), trace


def warmup_check_with_trace(
    symbol: str,
    exchange: str,
    trend_1h: float,
    trend_4h: float,
    trend_24h: float,
    cfg: Dict,
    trace_enabled: bool = False
) -> Tuple[bool, str, PairDecisionTrace]:
    """
    Warm-up mode validation met decision trace.

    Returns: (passed, reason, trace)
    """

    trace = PairDecisionTrace(
        trading_pair=symbol,
        exchange=exchange,
        enabled=trace_enabled,
        strategy="spot_grid"
    )

    # Check 1: 4H must be strongly bullish
    trend_4h_ok = trace_percentage_check(
        trace, "warmup_4h_strong", trend_4h, cfg["warmup_4h_strong_min"], ">"
    )

    # Check 2: 1H can be slightly negative if 4H override is enabled
    if cfg.get("warmup_override_enabled", False):
        # Professional pullback buying: accept negative 1H if 4H is strong
        trend_1h_ok = trace_percentage_check(
            trace, "warmup_1h_override", trend_1h, cfg["warmup_1h_min_if_4h_strong"], ">="
        )

        if trend_1h_ok:
            trace.checks[-1].reason = "pullback buy allowed (4H override active)"
    else:
        # Strict mode: 1H must be neutral or positive
        trend_1h_ok = trace_percentage_check(
            trace, "warmup_1h_strict", trend_1h, 0.0, ">="
        )

    # Check 3: Both must be positive (or override active)
    both_positive = trend_4h > 0.0 and trend_1h > 0.0
    override_active = cfg.get("warmup_override_enabled", False) and trend_4h >= cfg["warmup_4h_strong_min"]

    trace.add_check(
        filter_name="both_trends_positive",
        value=f"4h:{trend_4h:+.2f}% 1h:{trend_1h:+.2f}%",
        passed=both_positive or override_active,
        reason="override active" if override_active and not both_positive else None
    )

    # Final decision
    all_passed = trend_4h_ok and trend_1h_ok and (both_positive or override_active)

    if all_passed:
        trace.finalize(
            accepted=True,
            final_reason="warmup checks passed" + (" (4H override)" if override_active else "")
        )
        return True, f"✅ {symbol}: Warmup OK (4h: {trend_4h:+.2f}%, 1h: {trend_1h:+.2f}%)", trace
    else:
        # Determine rejection reason
        if not trend_4h_ok:
            rejected_by = "warmup_4h_strong"
            reason = f"4H trend {trend_4h:+.2f}% too weak (needs > {cfg['warmup_4h_strong_min']:+.2f}%)"
        elif not trend_1h_ok:
            rejected_by = "warmup_1h"
            reason = f"1H trend {trend_1h:+.2f}% too negative"
        else:
            rejected_by = "both_trends_positive"
            reason = "trends not aligned"

        trace.finalize(accepted=False, rejected_by=rejected_by, final_reason=reason)
        return False, f"❌ {symbol}: Warmup REJECT – {reason}", trace


# ============================================================================
# INTEGRATION IN CONTROLLER
# ============================================================================

def example_controller_integration():
    """
    Voorbeeld van hoe je dit integreert in multi_coin_grid_controller.py
    """

    # In your controller __init__:
    # self.debug_trace_enabled = config.get("debug_trace_enabled", False)
    # self.debug_trace_format = config.get("debug_trace_format", "compact")
    # self.debug_trace_log_accepted = config.get("debug_trace_log_accepted", False)
    # self.debug_trace_log_rejected = config.get("debug_trace_log_rejected", True)

    # In your coin evaluation loop:
    def evaluate_coin_for_trading(self, coin: str):
        """Evaluate if coin should be traded"""

        # Get indicators
        ind = self.get_indicators(coin)
        cfg = self.config.smart_entry

        # Run SmartEntry filter with trace
        allowed, reason, trace = smart_entry_check_with_trace(
            symbol=coin,
            exchange=self.exchange,
            ind=ind,
            cfg=cfg,
            trace_enabled=self.debug_trace_enabled
        )

        # Log based on config
        if trace.enabled:
            if (not allowed and self.debug_trace_log_rejected) or \
               (allowed and self.debug_trace_log_accepted):

                if self.debug_trace_format == "detailed":
                    self.logger().info(trace.to_detailed_log())
                elif self.debug_trace_format == "json":
                    self.logger().info(f"DECISION_TRACE: {trace.to_json()}")
                else:  # compact
                    self.logger().info(trace.to_compact_log())

        # Continue with normal logic
        if not allowed:
            self.logger().warning(reason)
            return False

        # If SmartEntry passed, check warmup
        trend = self.get_trend(coin)
        warmup_ok, warmup_reason, warmup_trace = warmup_check_with_trace(
            symbol=coin,
            exchange=self.exchange,
            trend_1h=trend.trend_60m,
            trend_4h=trend.trend_240m,
            trend_24h=trend.trend_1440m,
            cfg=self.config,
            trace_enabled=self.debug_trace_enabled
        )

        if warmup_trace.enabled and self.debug_trace_log_rejected and not warmup_ok:
            self.logger().info(warmup_trace.to_compact_log())

        if not warmup_ok:
            self.logger().warning(warmup_reason)
            return False

        # All checks passed!
        return True


if __name__ == "__main__":
    # Run example
    print("=== SmartEntry Filter Example ===\n")

    # Mock data
    ind = {
        "rsi": 79.3,
        "vwap_deviation_pct": 5.05,
        "wick_ratio": 0.15,
        "atr_pct": 2.5,
        "change_5m_pct": 0.5,
        "trend_1h_pct": -1.00,
        "trend_4h_pct": 1.89,
        "trend_24h_pct": 0.45
    }

    cfg = {
        "rsi_buy_max": 72.0,
        "rsi_block_min": 80.0,
        "vwap_max_deviation_pct": 5.0,
        "min_wick_ratio": 0.0,
        "min_atr_pct_for_grid": 0.2,
        "max_atr_pct_for_grid": 6.0,
        "max_5m_spike_pct": 2.5,
        "max_down_accel_pct": -4.0,
        "max_up_accel_pct": 1.8,
        "max_trend_24h_pct": 10.0,
        "min_trend_24h_pct": -10.0
    }

    allowed, reason, trace = smart_entry_check_with_trace(
        symbol="CHZ-USDT",
        exchange="bitget",
        ind=ind,
        cfg=cfg,
        trace_enabled=True
    )

    print(trace.to_detailed_log())
    print("\n" + "=" * 60 + "\n")
    print("COMPACT LOG:")
    print(trace.to_compact_log())
