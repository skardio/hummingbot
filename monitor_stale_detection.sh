#!/bin/bash
# Monitor stale detection in real-time

echo "=== STALE DETECTION MONITOR ==="
echo "Press Ctrl+C to stop"
echo ""

# Track counts
STALE_COUNT=0
RECOVER_COUNT=0
NO_PRICE_COUNT=0

# Function to show stats
show_stats() {
    echo ""
    echo "📊 STATS (last 5 min):"
    echo "  Stale marks:     $STALE_COUNT"
    echo "  Recoveries:      $RECOVER_COUNT"
    echo "  NO_PRICE_DATA:   $NO_PRICE_COUNT"
    if [ $STALE_COUNT -gt 0 ]; then
        RECOVERY_RATE=$((100 * RECOVER_COUNT / STALE_COUNT))
        echo "  Recovery rate:   ${RECOVERY_RATE}%"
    fi
    echo ""
}

# Set up trap to show final stats
trap show_stats EXIT

# Monitor logs
tail -f logs/*.log | while read line; do
    # Count stale marks
    if echo "$line" | grep -q "marked STALE"; then
        STALE_COUNT=$((STALE_COUNT + 1))
        echo "⚠️  $line"
    fi

    # Count recoveries
    if echo "$line" | grep -q "recovered from stale"; then
        RECOVER_COUNT=$((RECOVER_COUNT + 1))
        echo "✅ $line"
    fi

    # Count NO_PRICE_DATA
    if echo "$line" | grep -q "NO_PRICE_DATA"; then
        NO_PRICE_COUNT=$((NO_PRICE_COUNT + 1))
    fi

    # Show periodic stale checks
    if echo "$line" | grep -q "Periodic stale check"; then
        echo "🔍 $line"
    fi

    # Show stats every 300 lines (~5 min)
    if [ $((($STALE_COUNT + $RECOVER_COUNT) % 20)) -eq 0 ] && [ $STALE_COUNT -gt 0 ]; then
        show_stats
    fi
done
