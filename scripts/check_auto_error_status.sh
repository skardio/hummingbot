#!/bin/bash
# Quick status check for auto error checker

echo "=========================================="
echo "  AUTO ERROR CHECKER STATUS"
echo "=========================================="
echo ""

# Check if process is running
PID=$(ps aux | grep "auto_check_errors_in_1h.py" | grep -v grep | awk '{print $2}')

if [ -z "$PID" ]; then
    echo "❌ Auto error checker is NOT running"
    echo ""
    echo "To start it:"
    echo "  cd /home/mo/repos/hummingbot"
    echo "  nohup python3 scripts/auto_check_errors_in_1h.py > logs/auto_error_checker.log 2>&1 &"
else
    echo "✅ Auto error checker is running (PID: $PID)"
    echo ""

    # Show log output
    if [ -f "logs/auto_error_checker.log" ]; then
        echo "📄 Recent log output:"
        echo "----------------------------------------"
        tail -n 10 logs/auto_error_checker.log
        echo "----------------------------------------"
    fi

    # Calculate time remaining
    START_TIME=$(ps -p $PID -o lstart= 2>/dev/null)
    if [ ! -z "$START_TIME" ]; then
        echo ""
        echo "⏰ Started at: $START_TIME"
        echo "⏰ Will check logs in ~1 hour from start"
    fi
fi

echo ""
echo "=========================================="
echo "To view full log:"
echo "  tail -f logs/auto_error_checker.log"
echo "=========================================="
