#!/bin/bash
# Continuous Bot Error Monitor
# Monitors bot logs for errors and alerts

LOG_FILE="/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2.log"
CHECK_INTERVAL=60  # Check every 60 seconds
MAX_ERRORS=5        # Alert if more than 5 errors found

echo "=========================================="
echo "  BOT ERROR MONITOR"
echo "=========================================="
echo "📁 Log file: $LOG_FILE"
echo "⏰ Check interval: ${CHECK_INTERVAL} seconds"
echo "🔔 Alert threshold: ${MAX_ERRORS} errors"
echo ""
echo "Press Ctrl+C to stop monitoring"
echo "=========================================="
echo ""

# Track last checked line
LAST_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")

while true; do
    # Get current line count
    CURRENT_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")

    if [ "$CURRENT_LINE" -gt "$LAST_LINE" ]; then
        # Check for new errors
        NEW_LINES=$((CURRENT_LINE - LAST_LINE))
        ERRORS=$(tail -n "$NEW_LINES" "$LOG_FILE" | grep -E "(ERROR|CRITICAL|Exception|Traceback)" | wc -l)

        if [ "$ERRORS" -gt 0 ]; then
            TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
            echo "❌ [$TIMESTAMP] Found $ERRORS new error(s)!"
            echo "----------------------------------------"
            tail -n "$NEW_LINES" "$LOG_FILE" | grep -B 2 -A 5 -E "(ERROR|CRITICAL|Exception)" | head -n 30
            echo "----------------------------------------"
            echo ""

            # Check total recent errors
            TOTAL_RECENT=$(tail -n 200 "$LOG_FILE" | grep -E "(ERROR|CRITICAL|Exception)" | wc -l)
            if [ "$TOTAL_RECENT" -gt "$MAX_ERRORS" ]; then
                echo "⚠️  WARNING: More than ${MAX_ERRORS} errors in recent logs!"
                echo "   Total recent errors: $TOTAL_RECENT"
                echo ""
            fi
        else
            # Show status every 5 minutes
            MINUTES=$(($(date +%s) / 60))
            if [ $((MINUTES % 5)) -eq 0 ]; then
                TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
                echo "✅ [$TIMESTAMP] No errors - Bot running normally"
            fi
        fi

        LAST_LINE=$CURRENT_LINE
    fi

    sleep "$CHECK_INTERVAL"
done
