#!/bin/bash
# Auto-start Multi-Coin Grid Bot via Hummingbot CLI

cd /home/mo/repos/hummingbot

# Export API keys
export KRAKEN_API_KEY="ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk"
export KRAKEN_SECRET_KEY="4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=="

echo "======================================================================"
echo "  STARTING MULTI-COIN GRID BOT V2"
echo "======================================================================"
echo ""
echo "API Keys: Exported ✓"
echo "Config: €50 capital, -8% stop-loss"
echo ""
echo "In Hummingbot CLI, the bot will auto-start or type:"
echo "  >>> start --script multi_coin_grid_v2.py"
echo ""
echo "To monitor:"
echo "  tail -f logs/hummingbot.log"
echo ""
echo "======================================================================"
echo ""

# Start Hummingbot CLI
exec ~/.venvs/bot/bin/python bin/hummingbot.py
