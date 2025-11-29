#!/bin/bash
# Quick script to run unit tests

cd /home/mo/repos/hummingbot

echo "🧪 Running Multi-Coin Grid Bot Unit Tests..."
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "❌ pytest not found. Installing..."
    pip install pytest pytest-asyncio pytest-cov
fi

# Run tests
pytest multi_coin_grid_pro/tests/unit/ \
    -v \
    --tb=short \
    --color=yes \
    "$@"

echo ""
echo "✅ Tests completed!"
