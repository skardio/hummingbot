#!/bin/bash
# Bot Error Checker Script
# Check for errors in multi-coin grid bot logs

LOG_FILE="/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file not found: $LOG_FILE"
    exit 1
fi

echo "=========================================="
echo "  BOT ERROR CHECKER"
echo "=========================================="
echo ""
echo "📁 Log file: $LOG_FILE"
echo "⏰ Checking last 200 lines..."
echo ""

# Check for errors in last 200 lines
ERRORS=$(tail -n 200 "$LOG_FILE" | grep -E "(ERROR|CRITICAL|Exception|Traceback)" | tail -n 20)

if [ -z "$ERRORS" ]; then
    echo "✅ No errors found in recent logs!"
    echo ""
    echo "📊 Recent activity:"
    tail -n 30 "$LOG_FILE" | grep -E "(INFO|WARNING|✅|🔄|🎯)" | tail -n 10
else
    echo "❌ ERRORS FOUND:"
    echo "----------------------------------------"
    echo "$ERRORS"
    echo "----------------------------------------"
    echo ""
    echo "📋 Full error context (last 5 errors):"
    tail -n 500 "$LOG_FILE" | grep -B 5 -A 10 -E "(ERROR|CRITICAL|Exception)" | tail -n 50
fi

echo ""
echo "=========================================="
echo "Run this script periodically to check for errors"
echo "Usage: bash scripts/check_bot_errors.sh"
echo "=========================================="
