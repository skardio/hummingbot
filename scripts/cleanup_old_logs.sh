#!/bin/bash
# Cleanup old log files for multi-coin grid bot
# Usage: ./scripts/cleanup_old_logs.sh [days_to_keep]

DAYS_TO_KEEP=${1:-7}  # Default: keep logs from last 7 days
LOG_DIR="/home/mo/repos/hummingbot/logs"

echo "=========================================="
echo "  LOG CLEANUP SCRIPT"
echo "=========================================="
echo ""
echo "📁 Log directory: $LOG_DIR"
echo "📅 Keeping logs from last $DAYS_TO_KEEP days"
echo ""

# Count logs before cleanup
TOTAL_BEFORE=$(find "$LOG_DIR" -name "logs_multi_coin_grid_v2*.log*" 2>/dev/null | wc -l)
echo "📊 Current log files: $TOTAL_BEFORE"

# Find logs older than X days
OLD_LOGS=$(find "$LOG_DIR" -name "logs_multi_coin_grid_v2*.log*" -mtime +$DAYS_TO_KEEP 2>/dev/null)

if [ -z "$OLD_LOGS" ]; then
    echo ""
    echo "✅ No old logs to clean up!"
else
    OLD_COUNT=$(echo "$OLD_LOGS" | wc -l)
    OLD_SIZE=$(echo "$OLD_LOGS" | xargs du -ch 2>/dev/null | tail -1 | cut -f1)

    echo ""
    echo "🗑️  Found $OLD_COUNT log files older than $DAYS_TO_KEEP days ($OLD_SIZE)"
    echo ""
    echo "Files to delete:"
    echo "$OLD_LOGS" | head -10
    if [ $OLD_COUNT -gt 10 ]; then
        echo "... and $((OLD_COUNT - 10)) more"
    fi
    echo ""

    read -p "Delete these files? (y/N) " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "$OLD_LOGS" | xargs rm -f
        echo "✅ Deleted $OLD_COUNT old log files"
    else
        echo "❌ Cleanup cancelled"
    fi
fi

echo ""
echo "=========================================="
echo "Current logs:"
ls -lht "$LOG_DIR"/logs_multi_coin_grid_v2*.log* 2>/dev/null | head -10
echo "=========================================="
