#!/bin/bash
# Deployment & Monitoring Script for Task 2.1.1
# Run this to deploy and monitor stale detection feature

set -e

echo "============================================================"
echo "🚀 Task 2.1.1: Stale Detection Deployment"
echo "============================================================"
echo ""

# Step 1: Verify changes
echo "📋 Step 1: Verifying changes..."
python3 -m py_compile multi_coin_grid_pro/controllers/multi_coin_grid_controller.py
python3 -m py_compile multi_coin_grid_pro/utils/trend_calculator.py
echo "✅ Syntax check passed"
echo ""

# Step 2: Run unit test
echo "📋 Step 2: Running unit tests..."
python3 test_stale_detection.py
echo ""

# Step 3: Backup current logs
echo "📋 Step 3: Backing up current logs..."
BACKUP_DIR="logs/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp logs/*.log "$BACKUP_DIR/" 2>/dev/null || true
cp logs/events/*.jsonl "$BACKUP_DIR/" 2>/dev/null || true
echo "✅ Logs backed up to $BACKUP_DIR"
echo ""

# Step 4: Create monitoring script
echo "📋 Step 4: Creating monitoring script..."
cat > monitor_stale_detection.sh << 'MONITOR_EOF'
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
MONITOR_EOF

chmod +x monitor_stale_detection.sh
echo "✅ Monitoring script created: ./monitor_stale_detection.sh"
echo ""

# Step 5: Restart bot
echo "📋 Step 5: Restart instructions"
echo ""
echo "To deploy, restart your bot(s):"
echo ""
echo "  # Kraken bot:"
echo "  ./start_bot.sh"
echo ""
echo "  # Bitget bot (if running):"
echo "  ./start_bot_usd.sh"
echo ""
echo "Then monitor with:"
echo ""
echo "  ./monitor_stale_detection.sh"
echo ""

# Step 6: Performance analysis commands
echo "📋 Step 6: Performance Analysis Commands"
echo ""
echo "After 2-4 hours, check impact:"
echo ""
echo "  # Count stale detections:"
echo "  grep 'marked STALE' logs/*.log | wc -l"
echo ""
echo "  # Count recoveries:"
echo "  grep 'recovered from stale' logs/*.log | wc -l"
echo ""
echo "  # Check NO_PRICE_DATA reduction:"
echo "  grep 'NO_PRICE_DATA' logs/events/events_*.jsonl | tail -1000 | wc -l"
echo ""
echo "  # Full performance report:"
echo "  python3 analyze_bot_performance.py"
echo ""

echo "============================================================"
echo "✅ DEPLOYMENT PREP COMPLETE"
echo "============================================================"
echo ""
echo "Next: Restart bot and run ./monitor_stale_detection.sh"
echo ""
