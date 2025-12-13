#!/bin/bash
# Start Hybrid Momentum/Scalper Bot for Bitget
# Usage: ./start_scalper.sh [live]

cd /home/mo/repos/hummingbot

# Bitget API keys
export BITGET_API_KEY="bg_116b72fa44fc6eb7e4ab09d9b9ff2741"
export BITGET_SECRET_KEY="4a5272c8aa126df27187c3b1b92e3886659e31a5474d97a37a265cbd0000e932"
export BITGET_PASSPHRASE="M4x9QpL2aR7bT8vC5zN1kH6uW3eJ0sD"

# Telegram
export TELEGRAM_BOT_TOKEN="8310424124:AAGc--tOZvhucvyfJnoKeIucm6aD9L9N1Jk"
export TELEGRAM_CHAT_ID="8586283471"

# Check for live mode
if [ "$1" = "live" ]; then
    export EXECUTE_TRADES=true
    echo "⚠️  LIVE MODE ENABLED - REAL TRADES WILL BE PLACED!"
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Cancelled."
        exit 1
    fi
else
    export EXECUTE_TRADES=false
    echo "🔄 SIMULATION MODE (no real trades)"
fi

echo ""
echo "Starting Momentum Scalper..."
echo ""

~/.venvs/bot/bin/python scripts/momentum_scalper_bitget/momentum_scalper.py
