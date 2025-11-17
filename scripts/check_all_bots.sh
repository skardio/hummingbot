#!/bin/bash
# Quick bot status checker

echo "=========================================="
echo "  BOT STATUS CHECKER"
echo "=========================================="
echo ""

# Check triangular arbitrage
echo "📊 TRIANGULAIRE ARBITRAGE:"
if ps aux | grep "03_monitor_continuous_24h.py" | grep -v grep > /dev/null; then
    MONITOR_PID=$(ps aux | grep "03_monitor_continuous_24h.py" | grep -v grep | awk '{print $2}')
    MONITOR_TIME=$(ps -p $MONITOR_PID -o etime= | tr -d ' ')
    echo "  ✅ Monitor: Running (PID: $MONITOR_PID, Runtime: $MONITOR_TIME)"
else
    echo "  ❌ Monitor: STOPPED"
fi

if ps aux | grep "dry_run_continuous.py" | grep -v grep > /dev/null; then
    DRYRUN_PID=$(ps aux | grep "dry_run_continuous.py" | grep -v grep | awk '{print $2}')
    DRYRUN_TIME=$(ps -p $DRYRUN_PID -o etime= | tr -d ' ')
    echo "  ✅ Dry-run: Running (PID: $DRYRUN_PID, Runtime: $DRYRUN_TIME)"
else
    echo "  ❌ Dry-run: STOPPED"
fi

echo ""
echo "📈 GRID TRADING:"
echo "  ⏳ Ready to start (manual)"
echo "  📂 Config: scripts/grid_trading_kraken/"
echo ""

# Log file sizes
echo "📁 LOG FILES:"
if [ -f logs/tri_candidates.log ]; then
    TRI_SIZE=$(du -h logs/tri_candidates.log | cut -f1)
    TRI_LINES=$(wc -l < logs/tri_candidates.log)
    echo "  - tri_candidates.log: $TRI_SIZE ($TRI_LINES lines)"
fi

if [ -f logs/dry_run_continuous.log ]; then
    DRY_SIZE=$(du -h logs/dry_run_continuous.log | cut -f1)
    DRY_LINES=$(wc -l < logs/dry_run_continuous.log)
    echo "  - dry_run_continuous.log: $DRY_SIZE ($DRY_LINES lines)"
fi

echo ""
echo "=========================================="
echo "Commands:"
echo "  Triangular logs: tail -f logs/tri_candidates.log"
echo "  Dry-run logs:    tail -f logs/dry_run_continuous.log"
echo "  Grid monitor:    cd scripts/grid_trading_kraken && python3 03_grid_monitor.py"
echo "  This status:     bash scripts/check_all_bots.sh"
echo "=========================================="
