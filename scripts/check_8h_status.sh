#!/bin/bash
# Check status of 8-hour bot checker

echo "=========================================="
echo "  8-HOUR BOT CHECKER STATUS"
echo "=========================================="
echo ""

# Check if process is running
PID=$(ps aux | grep "check_bot_after_8h.py" | grep -v grep | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "❌ 8-hour checker is NOT running"
    echo ""
    echo "To start it:"
    echo "  cd /home/mo/repos/hummingbot"
    echo "  nohup python3 scripts/check_bot_after_8h.py > logs/bot_8h_checker.log 2>&1 &"
else
    echo "✅ 8-hour checker is running (PID: $PID)"
    echo ""

    # Show log output
    if [ -f "logs/bot_8h_checker.log" ]; then
        echo "📄 Recent log output:"
        echo "----------------------------------------"
        tail -n 15 logs/bot_8h_checker.log
        echo "----------------------------------------"
    fi

    # Calculate time remaining
    START_TIME=$(ps -p $PID -o lstart= 2>/dev/null)
    if [ ! -z "$START_TIME" ]; then
        echo ""
        echo "⏰ Started at: $START_TIME"
        echo "⏰ Will analyze bot activity in ~8 hours from start"
    fi
fi

echo ""
echo "=========================================="
echo "To view full log:"
echo "  tail -f logs/bot_8h_checker.log"
echo ""
echo "To check for reports:"
echo "  ls -lt logs/bot_activity_report_8h_*.txt | head -1"
echo "=========================================="
