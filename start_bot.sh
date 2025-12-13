#!/bin/bash
# Multi-Coin Grid Pro - Direct Launcher (All-in-One)
# Loads .env and starts bot_v2.py directly

set -e  # Exit on error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🚀 Multi-Coin Grid Pro Bot - Quick Start"
echo "=================================================="
echo ""

# Load .env for API keys
if [ -f .env ]; then
    echo "✅ Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "❌ ERROR: .env file not found!"
    echo "   Copy .env.example to .env and fill in your API keys"
    exit 1
fi

# Verify required variables
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo "❌ ERROR: KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set in .env"
    exit 1
fi

echo "✅ API keys loaded from .env"
echo ""

# Check if virtualenv exists
if [ ! -d "multi_coin_grid_pro/venv" ]; then
    echo "📦 Creating virtual environment..."
    cd multi_coin_grid_pro
    python3 -m venv venv
    source venv/bin/activate
    echo "📥 Installing dependencies..."
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt > /dev/null 2>&1
    echo "✅ Virtual environment created & dependencies installed"
    cd ..
else
    echo "✅ Virtual environment exists"
fi

echo ""
echo "=================================================="
echo "🏃 Starting Multi-Coin Grid Bot V2"
echo "=================================================="
echo ""
echo "Config: multi_coin_grid_pro/config/config.prod.yaml"
echo "Logs: logs/logs_multi_coin_grid_v2_*.log"
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""
echo "=================================================="
echo ""

# Activate venv and run bot
cd multi_coin_grid_pro
source venv/bin/activate
python3 bot_v2.py
