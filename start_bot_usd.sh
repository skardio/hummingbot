#!/bin/bash
# Multi-Coin Grid Pro - USD Research Bot (Option C)
# Parallel test with USD pairs for liquidity comparison

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🔬 Multi-Coin Grid Pro - USD RESEARCH Bot"
echo "=================================================="
echo ""
echo "⚠️  RESEARCH MODE: USD pairs for comparison"
echo "   EUR bot should be running in parallel"
echo ""

# Load .env for API keys
if [ -f .env ]; then
    echo "✅ Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "❌ ERROR: .env file not found!"
    exit 1
fi

# Verify API keys
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo "❌ ERROR: KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set in .env"
    exit 1
fi

echo "✅ API keys loaded"
echo ""

# Set environment for USD config
export BOT_ENV="usd"

echo "=================================================="
echo "🏃 Starting USD Research Bot"
echo "=================================================="
echo ""
echo "Config: multi_coin_grid_pro/config/config.usd.yaml"
echo "Quote: USD"
echo "Capital: ~$110 (€100 equivalent)"
echo "Logs: logs/multi_coin_grid_usd.log"
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""
echo "=================================================="
echo ""

# Activate venv and run bot
cd multi_coin_grid_pro
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt > /dev/null 2>&1
    echo "✅ Virtual environment ready"
else
    source venv/bin/activate
fi

python3 bot_v2.py
