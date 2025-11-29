#!/bin/bash
# Start Multi-Coin Grid Bot with Multi-Timeframe Trend Engine Enabled
# Phase 2.5: Multi-Timeframe analysis prevents buying during crashes

cd /home/mo/repos/hummingbot

echo "======================================================================"
echo "  STARTING MULTI-COIN GRID BOT V2"
echo "  WITH MULTI-TIMEFRAME TREND ENGINE (Phase 2.5)"
echo "======================================================================"
echo ""
echo "✅ Multi-Timeframe Features:"
echo "   - 60m trend (1 hour) - detects crashes quickly"
echo "   - 240m trend (4 hours) - detects trend breaks"
echo "   - 1440m trend (24 hours) - macro trend"
echo "   - Composite score: 0.2×60m + 0.4×240m + 0.4×1440m"
echo "   - Buy conditions: All 3 timeframes must be positive"
echo "   - Exit conditions: Detects crashes before they get worse"
echo ""
echo "📝 Configuration:"
echo "   - Config: multi_coin_grid_pro/config/config.dev.yaml"
echo "   - Paper Trading: Enabled (check config)"
echo "   - Multi-Timeframe: Enabled"
echo ""
echo "🚀 Starting Hummingbot..."
echo "   In CLI, type: start --script multi_coin_grid_v2.py"
echo ""
echo "📊 Monitor logs:"
echo "   tail -f logs/logs_multi_coin_grid_v2.log | grep -E '\[TREND\]|\[DECISION\]|Selected coin'"
echo ""
echo "======================================================================"
echo ""

# Export API keys if needed
if [ -z "$KRAKEN_API_KEY" ]; then
    export KRAKEN_API_KEY="ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk"
    export KRAKEN_SECRET_KEY="4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=="
    echo "✓ API keys exported"
fi

# Start Hummingbot CLI
exec ~/.venvs/bot/bin/python bin/hummingbot.py
