#!/bin/bash

# Script to run flake8 on each directory separately
# This prevents VS Code from crashing on large scans

DIRS=(
    "alerts"
    "backtest"
    "config"
    "controllers"
    "core"
    "filters"
    "futures_bitget"
    "logic"
    "monitoring"
    "paper_trading"
    "risk"
    "scripts"
    "spot_bitget"
    "spot_microarb_bitget"
    "src"
    "tests"
    "utils"
)

# Also check root-level Python files
echo "=== Checking root Python files ==="
flake8 *.py 2>/dev/null

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo ""
        echo "=== Checking $dir ==="
        flake8 "$dir"
    fi
done
