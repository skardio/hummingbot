#!/bin/bash
# Check triangular arbitrage overnight results

echo "🌅 TRIANGULAR ARBITRAGE OVERNIGHT REPORT"
echo "========================================"
echo ""

# Check if processes still running
echo "📊 PROCESS STATUS:"
if pgrep -f "03_monitor_continuous_24h.py" > /dev/null; then
    MONITOR_PID=$(pgrep -f "03_monitor_continuous_24h.py")
    echo "   ✅ Monitor running (PID: $MONITOR_PID)"
else
    echo "   ❌ Monitor NOT running"
fi

if pgrep -f "execute_triangular_live_zero_fees.py" > /dev/null; then
    EXECUTOR_PID=$(pgrep -f "execute_triangular_live_zero_fees.py")
    echo "   ✅ Executor running (PID: $EXECUTOR_PID)"
else
    echo "   ❌ Executor NOT running"
fi

echo ""
echo "📈 MONITOR STATISTICS:"
TOTAL_POLLS=$(grep "Poll #" logs/tri_monitor.log | wc -l)
CANDIDATES_FOUND=$(grep "found.*candidate" logs/tri_monitor.log | tail -20 | grep -o "found [0-9]*" | awk '{sum+=$2} END {print sum/NR}')
echo "   Total polls: $TOTAL_POLLS"
echo "   Avg candidates per poll: ${CANDIDATES_FOUND:-0}"

echo ""
echo "💰 BEST OPPORTUNITIES FOUND:"
echo "   (Top 10 highest net profit edges after slippage)"
grep "lijkt rendabel: verwacht profit" logs/tri_monitor.log | \
    grep -oP "profit after fees\+slippage = \K[-0-9.]+%" | \
    sort -rn | head -10

echo ""
echo "🎯 EXECUTOR STATISTICS:"
OPPORTUNITIES=$(grep "💰 PROFITABLE" logs/tri_executor_live.log | wc -l)
EXECUTED=$(grep "🎯 Executing" logs/tri_executor_live.log | wc -l)
FAILED=$(grep "❌ Trade failed" logs/tri_executor_live.log | wc -l)
SUCCESS=$(grep "✅ Trade completed" logs/tri_executor_live.log | wc -l)

echo "   Opportunities seen: $OPPORTUNITIES"
echo "   Execution attempts: $EXECUTED"
echo "   Failed trades: $FAILED"
echo "   Successful trades: $SUCCESS"

if [ $SUCCESS -gt 0 ]; then
    echo ""
    echo "💸 SUCCESSFUL TRADES:"
    grep "✅ Trade completed" logs/tri_executor_live.log | tail -5
fi

echo ""
echo "💰 CURRENT BALANCE:"
cd /home/mo/repos/hummingbot && KRAKEN_API_KEY="ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk" KRAKEN_SECRET_KEY="4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw==" ~/.venvs/bot/bin/python3 << 'EOF'
import ccxt, os
ex = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_SECRET_KEY')
})
bal = ex.fetch_balance()
eur_start = 76.59
eur_now = bal.get('free', {}).get('EUR', 0)
diff = eur_now - eur_start

print(f"   Start:  €{eur_start:.2f}")
print(f"   Now:    €{eur_now:.2f}")
print(f"   Change: €{diff:+.2f} ({diff/eur_start*100:+.2f}%)")

for cur in ['USDC', 'XRP', 'ETH', 'SOL']:
    amount = bal.get('free', {}).get(cur, 0)
    if amount > 0.01:
        print(f"   {cur}: {amount:.4f}")
EOF

echo ""
echo "📊 LAATSTE 10 MONITOR ENTRIES:"
tail -10 logs/tri_monitor.log

echo ""
echo "🔍 LAATSTE 10 EXECUTOR ENTRIES:"
tail -10 logs/tri_executor_live.log

echo ""
echo "✅ Report complete! Run anytime: bash scripts/triangular_arb/check_overnight_results.sh"
