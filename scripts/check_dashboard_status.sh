#!/bin/bash
# Check dashboard status and port usage

echo "=========================================="
echo "  DASHBOARD STATUS CHECK"
echo "=========================================="
echo ""

# Check if dashboard is running
DASHBOARD_PID=$(ps aux | grep "monitoring.dashboard" | grep -v grep | awk '{print $2}')

if [ -z "$DASHBOARD_PID" ]; then
    echo "❌ Dashboard is NOT running"
    echo ""
    echo "To start it:"
    echo "  python -m multi_coin_grid_pro.monitoring.dashboard"
else
    echo "✅ Dashboard is running (PID: $DASHBOARD_PID)"

    # Check which port it's using
    PORT=$(lsof -i -P -n 2>/dev/null | grep "$DASHBOARD_PID" | grep LISTEN | awk '{print $9}' | cut -d: -f2)

    if [ ! -z "$PORT" ]; then
        echo "📡 Port: $PORT"
        echo "🌐 URL: http://localhost:$PORT"
    else
        echo "⚠️  Could not determine port"
    fi

    # Show process info
    echo ""
    echo "Process info:"
    ps aux | grep "$DASHBOARD_PID" | grep -v grep
fi

echo ""
echo "=========================================="
echo "Port 5000 status:"
if lsof -i :5000 >/dev/null 2>&1; then
    echo "⚠️  Port 5000 is in use:"
    lsof -i :5000 | grep -v COMMAND
    echo ""
    echo "To stop the process on port 5000:"
    echo "  kill $(lsof -i :5000 | tail -1 | awk '{print $2}')"
else
    echo "✅ Port 5000 is available"
fi
echo "=========================================="
