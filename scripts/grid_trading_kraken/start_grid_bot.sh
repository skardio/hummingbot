#!/bin/bash
# Grid Trading Quick Start Script

set -e

cd /home/mo/repos/hummingbot

echo "╔════════════════════════════════════════════════════════════╗"
echo "║      GRID TRADING BOT - KRAKEN ETH/EUR                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check API keys
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo "⚠️  API keys not set! Setting them now..."
    export KRAKEN_API_KEY=ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk
    export KRAKEN_SECRET_KEY=4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw==
    echo "✓ API keys exported"
fi

echo ""
echo "Select mode:"
echo "  1) Paper Trading (safe, no real orders)"
echo "  2) Live Trading DRY RUN (logs orders, doesn't execute)"
echo "  3) Live Trading REAL (⚠️  uses real money!)"
echo ""
read -p "Choice [1-3]: " choice

case $choice in
    1)
        echo ""
        echo "🧪 Starting Paper Trading..."
        read -p "Duration in minutes [default: 60]: " duration
        duration=${duration:-60}
        python3 scripts/grid_trading_kraken/05_grid_paper_trade.py $duration
        ;;
    2)
        echo ""
        echo "🔍 Starting Live Trading (DRY RUN)..."
        python3 scripts/grid_trading_kraken/06_grid_live_trade.py --dry-run
        ;;
    3)
        echo ""
        echo "╔════════════════════════════════════════════════════════════╗"
        echo "║                    ⚠️  WARNING ⚠️                          ║"
        echo "║                                                            ║"
        echo "║  You are about to start LIVE trading with REAL money!     ║"
        echo "║                                                            ║"
        echo "║  Config:                                                   ║"
        echo "║    • Pair: ETH/EUR                                         ║"
        echo "║    • Range: €2950 - €3200                                  ║"
        echo "║    • Grids: 10 levels                                      ║"
        echo "║    • Capital: €100                                         ║"
        echo "║    • Stop Loss: €2850                                      ║"
        echo "║    • Take Profit: €3300                                    ║"
        echo "║                                                            ║"
        echo "╚════════════════════════════════════════════════════════════╝"
        echo ""
        read -p "Type 'YES' to confirm: " confirm

        if [ "$confirm" = "YES" ]; then
            echo ""
            echo "🚀 Starting LIVE trading..."
            python3 scripts/grid_trading_kraken/06_grid_live_trade.py
        else
            echo "❌ Cancelled"
            exit 0
        fi
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "✓ Done!"
