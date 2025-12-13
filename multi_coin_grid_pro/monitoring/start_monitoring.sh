#!/bin/bash
# Start Monitoring System
# Starts collector and dashboard

cd /home/mo/repos/hummingbot

# Load environment variables
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "✅ Loaded .env file"
else
    echo "⚠️  Warning: .env file not found"
fi

echo "=========================================="
echo "  STARTING MONITORING SYSTEM"
echo "=========================================="
echo ""

# Check if collector is already running
if pgrep -f "monitoring.collector" > /dev/null; then
    echo "⚠️  Collector already running"
else
    echo "🚀 Starting data collector..."
    nohup python -m multi_coin_grid_pro.monitoring.collector > logs/monitoring_collector.log 2>&1 &
    echo "✅ Collector started (PID: $!)"
fi

# Check if dashboard is already running
if pgrep -f "monitoring.dashboard" > /dev/null; then
    echo "⚠️  Dashboard already running"
else
    echo "🚀 Starting dashboard..."
    nohup python -m multi_coin_grid_pro.monitoring.dashboard > logs/monitoring_dashboard.log 2>&1 &
    echo "✅ Dashboard started (PID: $!)"
    echo ""
    echo "📊 Dashboard available at: http://localhost:5000"
fi

# Check if Telegram command handler is already running
if pgrep -f "monitoring.telegram_bot_handler" > /dev/null; then
    echo "⚠️  Telegram handler already running"
else
    echo "🚀 Starting Telegram command handler..."
    nohup python -m multi_coin_grid_pro.monitoring.telegram_bot_handler > logs/monitoring_telegram_handler.log 2>&1 &
    echo "✅ Telegram handler started (PID: $!)"
    echo ""
    echo "📱 Telegram commands available: /status, /events, /help"
fi

# Check if risk monitor is already running
if pgrep -f "monitoring.risk_monitor" > /dev/null; then
    echo "⚠️  Risk monitor already running"
else
    echo "🚀 Starting risk monitor..."
    nohup python -m multi_coin_grid_pro.monitoring.risk_monitor > logs/monitoring_risk_monitor.log 2>&1 &
    echo "✅ Risk monitor started (PID: $!)"
    echo ""
    echo "⚠️  Risk monitoring active"
fi

echo ""
echo "=========================================="
echo "To check status:"
echo "  ps aux | grep monitoring"
echo ""
echo "To view logs:"
echo "  tail -f logs/monitoring_collector.log"
echo "  tail -f logs/monitoring_dashboard.log"
echo "  tail -f logs/monitoring_risk_monitor.log"
echo ""
echo "To stop:"
echo "  pkill -f monitoring.collector"
echo "  pkill -f monitoring.dashboard"
echo "  pkill -f monitoring.telegram_bot_handler"
echo "  pkill -f monitoring.risk_monitor"
echo ""
echo "Telegram commands:"
echo "  /status - Get bot status"
echo "  /events [N] - Get recent events (default: 5)"
echo "  /help - Show help"
echo "=========================================="
