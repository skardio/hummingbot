#!/bin/bash
# Start Bitget Triangular Arbitrage Monitor for 24/7 monitoring
# Usage: ./start_monitor_24h.sh

cd /home/mo/repos/hummingbot

# Bitget Spot API keys
export BITGET_API_KEY="bg_116b72fa44fc6eb7e4ab09d9b9ff2741"
export BITGET_SECRET_KEY="4a5272c8aa126df27187c3b1b92e3886659e31a5474d97a37a265cbd0000e932"
export BITGET_PASSPHRASE="M4x9QpL2aR7bT8vC5zN1kH6uW3eJ0sD"

# Telegram notifications (optional)
export TELEGRAM_BOT_TOKEN="8310424124:AAGc--tOZvhucvyfJnoKeIucm6aD9L9N1Jk"
export TELEGRAM_CHAT_ID="8586283471"

echo "========================================"
echo "  BITGET TRIANGULAR ARB MONITOR"
echo "========================================"
echo ""
echo "API Keys: Configured ✓"
echo "Telegram: Enabled ✓"
echo ""
echo "Starting monitor..."
echo "Log: logs/bitget_monitor.log"
echo "Candidates: logs/bitget_tri_candidates.log"
echo ""

# Start in background with nohup
nohup ~/.venvs/bot/bin/python scripts/triangular_arb_bitget/03_monitor_continuous.py > logs/bitget_monitor.log 2>&1 &

PID=$!
echo "Monitor started with PID: $PID"
echo ""
echo "To check status:"
echo "  tail -f logs/bitget_monitor.log"
echo ""
echo "To stop:"
echo "  kill $PID"
echo ""
echo "========================================"
