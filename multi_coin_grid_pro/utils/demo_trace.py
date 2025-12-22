"""
STANDALONE DEMO: Decision Trace System

Run this to see exactly how the trace system works with real CHZ-USDT data.
No Hummingbot dependencies required.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from decision_trace import PairDecisionTrace, trace_percentage_check, trace_range_check


def demo_chz_usdt_rejection():
    """
    Real scenario: CHZ-USDT being rejected by RSI
    This shows EXACTLY what happens in production
    """

    print("=" * 70)
    print("SCENARIO: CHZ-USDT Evaluation (Bitget Spot Grid)")
    print("=" * 70)
    print()

    # Real data from logs
    trading_pair = "CHZ-USDT"
    exchange = "bitget"

    # Trend data
    consensus_trend = 16.25  # Very bullish!
    trend_1h = -1.00         # Short-term pullback
    trend_4h = 1.89          # Still bullish
    trend_24h = 0.45         # Neutral

    # Technical indicators
    rsi = 79.3               # Overbought!
    vwap_deviation = 5.05    # Slightly above threshold
    atr_pct = 2.5
    wick_ratio = 0.15

    # Config thresholds
    consensus_min = 0.5
    warmup_1h_min = -1.5
    down_accel_max = -4.0
    rsi_max = 72.0
    vwap_max = 5.0

    # ========================================
    # CREATE TRACE
    # ========================================

    trace = PairDecisionTrace(
        trading_pair=trading_pair,
        exchange=exchange,
        enabled=True,
        strategy="spot_grid",
        slot_index=0
    )

    print("📊 MARKET DATA:")
    print(f"   Consensus Trend: +{consensus_trend}% (very bullish)")
    print(f"   1H Trend: {trend_1h:+.2f}% (pullback)")
    print(f"   4H Trend: +{trend_4h}%")
    print(f"   RSI: {rsi}")
    print(f"   VWAP Deviation: +{vwap_deviation}%")
    print()
    print("🔍 RUNNING FILTERS...\n")

    # ========================================
    # FILTER CHECKS (same order as real code)
    # ========================================

    # 1. Consensus Trend Check
    print("1️⃣  Checking consensus trend...")
    consensus_ok = trace_percentage_check(
        trace, "consensus_trend", consensus_trend, consensus_min, ">="
    )
    print(f"    Result: {'✅ PASS' if consensus_ok else '❌ FAIL'}")
    print(f"    {consensus_trend}% >= {consensus_min}% → {consensus_ok}")
    print()

    # 2. Warm-up 1H Check (with override)
    print("2️⃣  Checking warm-up 1H trend...")
    warmup_ok = trace_percentage_check(
        trace, "warmup_1h", trend_1h, warmup_1h_min, ">="
    )
    print(f"    Result: {'✅ PASS' if warmup_ok else '❌ FAIL'}")
    print(f"    {trend_1h}% >= {warmup_1h_min}% → {warmup_ok}")
    print(f"    (4H override active: 4H {trend_4h}% > 0.5%)")
    print()

    # 3. Down Acceleration Check
    print("3️⃣  Checking down acceleration (falling knife filter)...")
    accel = trend_1h - trend_4h
    accel_ok = trace_percentage_check(
        trace, "down_acceleration", accel, down_accel_max, ">="
    )
    print(f"    Result: {'✅ PASS' if accel_ok else '❌ FAIL'}")
    print(f"    Acceleration: {trend_1h}% - {trend_4h}% = {accel:.2f}%")
    print(f"    {accel:.2f}% >= {down_accel_max}% → {accel_ok}")
    print()

    # 4. RSI Check
    print("4️⃣  Checking RSI (overbought protection)...")
    rsi_ok = trace_range_check(
        trace, "rsi", rsi, 20.0, rsi_max
    )
    if not rsi_ok:
        trace.checks[-1].reason = "overbought"
    print(f"    Result: {'✅ PASS' if rsi_ok else '❌ FAIL'}")
    print(f"    RSI {rsi} must be <= {rsi_max} → {rsi_ok}")
    print(f"    ⚠️  REJECTION TRIGGER: RSI too high!")
    print()

    # 5. VWAP Deviation Check
    print("5️⃣  Checking VWAP deviation...")
    vwap_ok = trace_percentage_check(
        trace, "vwap_deviation", vwap_deviation, vwap_max, "<="
    )
    print(f"    Result: {'✅ PASS' if vwap_ok else '❌ FAIL'}")
    print(f"    {vwap_deviation}% <= {vwap_max}% → {vwap_ok}")
    print()

    # ========================================
    # FINALIZE DECISION
    # ========================================

    all_passed = all([consensus_ok, warmup_ok, accel_ok, rsi_ok, vwap_ok])
    rejected_by = None if all_passed else "rsi"

    trace.finalize(
        accepted=all_passed,
        rejected_by=rejected_by,
        final_reason="overbought" if not all_passed else None
    )

    print("=" * 70)
    print("📋 FINAL DECISION")
    print("=" * 70)
    print()

    # Show all output formats
    print("🎯 COMPACT LOG (what you see in production):")
    print("-" * 70)
    print(trace.to_compact_log())
    print()

    print("📊 DETAILED LOG (for debugging):")
    print("-" * 70)
    print(trace.to_detailed_log())
    print()

    print("💾 JSON OUTPUT (for analysis/dashboard):")
    print("-" * 70)
    print(trace.to_json())
    print()

    # Analysis
    print("=" * 70)
    print("🧠 ANALYSIS")
    print("=" * 70)
    print()
    print(f"✅ Passed: {len(trace.get_passed_filters())} filters")
    for f in trace.get_passed_filters():
        print(f"   - {f}")
    print()
    print(f"❌ Failed: {len(trace.get_failed_filters())} filters")
    for f in trace.get_failed_filters():
        print(f"   - {f}")
    print()

    print("💡 EXPLANATION:")
    print("   CHZ-USDT has excellent trend (+16.25% consensus) but RSI is")
    print("   overbought at 79.3 (max 72). The bot correctly rejects to")
    print("   avoid buying at the top of a short-term pump.")
    print()
    print("📈 RECOMMENDATION:")
    print("   Wait for RSI to cool down below 72, or adjust config if you")
    print("   want more aggressive entries during strong trends.")
    print()


def demo_accepted_scenario():
    """
    Scenario where a coin passes all checks
    """

    print("\n\n")
    print("=" * 70)
    print("SCENARIO 2: DOGE-USDT Accepted (All Checks Pass)")
    print("=" * 70)
    print()

    trace = PairDecisionTrace(
        trading_pair="DOGE-USDT",
        exchange="bitget",
        enabled=True
    )

    # All good values
    trace_percentage_check(trace, "consensus_trend", 5.49, 0.5, ">=")
    trace_percentage_check(trace, "warmup_1h", 0.5, -1.5, ">=")
    trace_percentage_check(trace, "down_acceleration", -1.0, -4.0, ">=")
    trace_range_check(trace, "rsi", 65.0, 20.0, 72.0)
    trace_percentage_check(trace, "vwap_deviation", 2.5, 5.0, "<=")
    trace_percentage_check(trace, "atr", 2.8, 0.2, ">=")

    trace.finalize(accepted=True, final_reason="all checks passed")

    print("🎯 COMPACT LOG:")
    print(trace.to_compact_log())
    print()
    print("📊 DETAILED LOG:")
    print(trace.to_detailed_log())


if __name__ == "__main__":
    demo_chz_usdt_rejection()
    demo_accepted_scenario()
