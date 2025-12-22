"""
════════════════════════════════════════════════════════════════════════════════
DECISION TRACE - QUICK REFERENCE CARD
════════════════════════════════════════════════════════════════════════════════

🚀 QUICK START
────────────────────────────────────────────────────────────────────────────────

# 1. Enable in config
debug_trace_enabled: true
debug_trace_format: compact

# 2. Use in code
from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace, trace_percentage_check

trace = PairDecisionTrace("CHZ-USDT", "bitget", enabled=True)
ok = trace_percentage_check(trace, "rsi", 79.3, 72.0, "<=")
trace.finalize(accepted=ok, rejected_by="rsi" if not ok else None)
logger.info(trace.to_compact_log())

════════════════════════════════════════════════════════════════════════════════
📊 OUTPUT FORMATS
════════════════════════════════════════════════════════════════════════════════

1. COMPACT (for production logs):
   🔴 CHZ-USDT [bitget] REJECTED by rsi | ✅ consensus: 16.25% | ❌ rsi: 79.3

2. DETAILED (for debugging):
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   🔍 DECISION TRACE: CHZ-USDT [bitget]
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   FILTERS:
     ✅ consensus: 16.25% >= 0.5%
     ❌ rsi: 79.3 > 72.0 (overbought)
   DECISION: 🔴 REJECTED

3. JSON (for analysis):
   {"trading_pair": "CHZ-USDT", "decision": {"accepted": false}, ...}

════════════════════════════════════════════════════════════════════════════════
🔧 COMMON CHECKS
════════════════════════════════════════════════════════════════════════════════

# Percentage check (>=, <=, >, <)
trace_percentage_check(trace, "consensus", value, threshold, ">=")

# Range check (min <= value <= max)
trace_range_check(trace, "rsi", value, min_val, max_val)

# Custom check
trace.add_check("filter_name", value=x, threshold=y, passed=True/False)

════════════════════════════════════════════════════════════════════════════════
🎯 ANALYZING LOGS
════════════════════════════════════════════════════════════════════════════════

# Count rejections by filter
grep "REJECTED by" logs/*.log | cut -d'|' -f1 | cut -d' ' -f5 | sort | uniq -c

# Show last 20 rejections
grep "REJECTED" logs/*.log | tail -20

# Find specific coin rejections
grep "CHZ-USDT.*REJECTED" logs/*.log

# Acceptance rate
TOTAL=$(grep -c "ACCEPTED\\|REJECTED" logs/*.log)
ACCEPTED=$(grep -c "ACCEPTED" logs/*.log)
echo "Acceptance rate: $((ACCEPTED * 100 / TOTAL))%"

════════════════════════════════════════════════════════════════════════════════
⚡ COMMON PATTERNS
════════════════════════════════════════════════════════════════════════════════

PATTERN 1: Simple filter function
────────────────────────────────────────────────────────────────────────────────
def check_rsi(symbol, exchange, rsi, max_rsi, trace_enabled=False):
    trace = PairDecisionTrace(symbol, exchange, enabled=trace_enabled)
    ok = trace_percentage_check(trace, "rsi", rsi, max_rsi, "<=")
    trace.finalize(accepted=ok, rejected_by="rsi" if not ok else None)
    return ok, trace

PATTERN 2: Multi-filter validation
────────────────────────────────────────────────────────────────────────────────
def validate_entry(symbol, exchange, data, cfg, trace_enabled=False):
    trace = PairDecisionTrace(symbol, exchange, enabled=trace_enabled)

    checks = [
        ("consensus", data["consensus"], cfg["min_consensus"], ">="),
        ("rsi", data["rsi"], cfg["max_rsi"], "<="),
        ("vwap", abs(data["vwap_dev"]), cfg["max_vwap"], "<=")
    ]

    for name, value, threshold, op in checks:
        ok = trace_percentage_check(trace, name, value, threshold, op)
        if not ok:
            trace.finalize(accepted=False, rejected_by=name)
            return False, trace

    trace.finalize(accepted=True)
    return True, trace

PATTERN 3: Controller integration
────────────────────────────────────────────────────────────────────────────────
def evaluate_coin(self, coin):
    allowed, trace = self.check_filters(coin, trace_enabled=self.debug_trace_enabled)

    if trace.enabled and (not allowed or self.debug_trace_log_accepted):
        self.logger().info(trace.to_compact_log())

    return allowed

════════════════════════════════════════════════════════════════════════════════
📈 OPTIMIZATION WORKFLOW
════════════════════════════════════════════════════════════════════════════════

1. Enable traces: debug_trace_enabled: true
2. Run bot for 1-2 hours
3. Analyze rejection patterns:
   grep "REJECTED by" logs/*.log | cut -d'|' -f1 | cut -d' ' -f5 | sort | uniq -c
4. Identify most common rejections (e.g., "rsi: 15 times")
5. Evaluate if threshold is too strict
6. Adjust config and repeat

Example findings:
   15 rsi           → Maybe increase rsi_buy_max from 72 to 75
    8 vwap          → VWAP deviation threshold might be too strict
    3 acceleration  → Falling knife filter working correctly

════════════════════════════════════════════════════════════════════════════════
🐛 DEBUGGING TIPS
════════════════════════════════════════════════════════════════════════════────

Problem: Not seeing traces in logs
Solution: Check debug_trace_enabled: true and debug_trace_log_rejected: true

Problem: Too many logs
Solution: Set debug_trace_log_accepted: false (only log rejections)

Problem: Hard to read
Solution: Switch to detailed format: debug_trace_format: detailed

Problem: Need to analyze programmatically
Solution: Use JSON format and parse logs

════════════════════════════════════════════════════════════════════════════════
🎓 EXAMPLES FROM REAL SCENARIOS
════════════════════════════════════════════════════════════════════════════════

SCENARIO 1: CHZ-USDT rejected by RSI
────────────────────────────────────────────────────────────────────────────────
🔴 CHZ-USDT [bitget] REJECTED by rsi | ✅ consensus: 16.25% | ✅ warmup: -1.0% | ❌ rsi: 79.3

Interpretation:
- Strong consensus trend (+16.25%) ✅
- Warm-up check passed (-1.0% within limits) ✅
- RSI too high (79.3 > 72) ❌
- Action: Wait for RSI cooldown or increase rsi_buy_max if aggressive

SCENARIO 2: DOGE-USDT accepted
────────────────────────────────────────────────────────────────────────────────
🟢 DOGE-USDT [bitget] ACCEPTED | ✅ consensus: 5.49% | ✅ rsi: 65.0 | ✅ vwap: 2.5%

Interpretation:
- All checks passed ✅
- Bot will create grid for DOGE-USDT

SCENARIO 3: Multiple coins rejected by same filter
────────────────────────────────────────────────────────────────────────────────
🔴 CHZ-USDT [bitget] REJECTED by vwap_deviation
🔴 DOGE-USDT [bitget] REJECTED by vwap_deviation
🔴 ETH-USDT [bitget] REJECTED by vwap_deviation

Interpretation:
- Market-wide volatility spike
- VWAP filter protecting against unstable entries
- Action: Wait for market to stabilize

════════════════════════════════════════════════════════════════════════════════
💡 PRO TIPS
════════════════════════════════════════════════════════════════════════════════

1. Start with compact format, switch to detailed only when debugging specific issue
2. Only log rejections in production (debug_trace_log_accepted: false)
3. Use JSON format for collecting data for backtesting/optimization
4. Check rejection patterns weekly to identify overly strict filters
5. Trace is zero-overhead when disabled - safe to leave code in production
6. Add traces incrementally (don't try to trace everything at once)
7. Use meaningful filter names (e.g., "rsi_buy_max" not just "rsi")

════════════════════════════════════════════════════════════════════════════════
📚 FILES
════════════════════════════════════════════════════════════════════════════════

decision_trace.py              - Core trace system
decision_trace_integration.py  - Integration examples
demo_trace.py                  - Standalone demo
INTEGRATION_GUIDE.md           - Full integration guide
QUICK_REFERENCE.md             - This file

════════════════════════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    print(__doc__)
