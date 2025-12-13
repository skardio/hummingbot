#!/bin/bash
# Start Telegram Bot Command Handler
# Uses environment variables from .env file

cd /home/mo/repos/hummingbot

# Load environment variables from .env file
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "ERROR: .env file not found!"
    echo "Copy .env.example to .env and fill in your API keys"
    exit 1
fi

# Verify Telegram vars are set
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env"
    exit 1
fi

echo "🤖 Starting Telegram Bot Handler..."
echo "Bot Token: ${TELEGRAM_BOT_TOKEN:0:20}..."
echo "Chat ID: $TELEGRAM_CHAT_ID"
echo ""

# Use the bot's virtual environment
# Note: log-path is now auto-detected from MonitoringConfig (finds latest timestamped log)
~/.venvs/bot/bin/python -m multi_coin_grid_pro.monitoring.telegram_bot_handler "$@"
