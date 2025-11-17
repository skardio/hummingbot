#!/bin/bash
# Quick Start Script - Multi-Coin Grid Pro

set -e  # Exit on error

echo "=================================================="
echo "🚀 Multi-Coin Grid Pro - Setup & Start"
echo "=================================================="
echo ""

# Check if we're in the right directory
if [ ! -f "ROADMAP_TO_PRODUCTION.md" ]; then
    echo "❌ Error: Run this script from multi_coin_grid_pro directory"
    exit 1
fi

# Check Python version
echo "📍 Checking Python version..."
python3 --version

# Check if virtualenv exists
if [ ! -d "venv" ]; then
    echo ""
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
fi

# Activate virtualenv
echo ""
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo ""
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Dependencies installed"

# Check for API keys
echo ""
echo "🔑 Checking API credentials..."
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo ""
    echo "⚠️  WARNING: API keys not set!"
    echo ""
    echo "Please set environment variables:"
    echo "  export KRAKEN_API_KEY='your_key'"
    echo "  export KRAKEN_SECRET_KEY='your_secret'"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ API keys found"
fi

# Show status
echo ""
echo "=================================================="
echo "📊 Project Status"
echo "=================================================="
echo ""
echo "Version: 2.0.0-dev"
echo "Phase: 1 - Critical Risks"
echo "Task: Stop-Loss Implementation"
echo "Progress: 0/34 tasks (0%)"
echo ""
echo "⚠️  NOT READY FOR PRODUCTION"
echo "    Safe for: €100 testing only"
echo ""

# Ask what to do
echo "=================================================="
echo "What would you like to do?"
echo "=================================================="
echo ""
echo "1) Install dependencies only (done)"
echo "2) Run legacy bot (v1.0 - working version)"
echo "3) Start Phase 1.1 - Stop Loss Implementation"
echo "4) Run tests (when available)"
echo "5) Check roadmap"
echo "6) Exit"
echo ""
read -p "Choice [1-6]: " choice

case $choice in
    1)
        echo "✅ Dependencies already installed!"
        ;;
    2)
        echo ""
        echo "🏃 Starting legacy bot (v1.0)..."
        python3 bot_v2.py
        ;;
    3)
        echo ""
        echo "🚧 Phase 1.1 - Stop Loss Implementation"
        echo "This will be implemented next!"
        echo "See ROADMAP_TO_PRODUCTION.md for details"
        ;;
    4)
        echo ""
        echo "🧪 Running tests..."
        pytest tests/ -v
        ;;
    5)
        echo ""
        cat ROADMAP_TO_PRODUCTION.md | less
        ;;
    6)
        echo "👋 Bye!"
        exit 0
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "=================================================="
echo "✅ Done!"
echo "=================================================="
