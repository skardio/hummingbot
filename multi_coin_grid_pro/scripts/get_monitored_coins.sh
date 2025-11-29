#!/bin/bash
# Script om monitored coins uit logs te halen

LOG_FILE="${1:-logs/logs_multi_coin_grid_v2.log}"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file niet gevonden: $LOG_FILE"
    exit 1
fi

echo "📊 Monitored Coins uit logs:"
echo "================================"

# Zoek naar de laatste "All X selected coins" regel en haal de volgende regels op
# Format: "   1. USDC-EUR: €96,380,793 (spread: 0.012%)"
# Gebruik tail om laatste 10000 regels te pakken (laatste discovery)
tail -10000 "$LOG_FILE" | \
    grep -A 60 "All.*selected coins by 24h volume" | \
    tail -55 | \
    grep -E "^\s+[0-9]+\." | \
    sed 's/.*INFO -[[:space:]]*//' | \
    sed -E 's/^[[:space:]]*[0-9]+\.\s*([A-Z0-9-]+-EUR):.*/\1/' | \
    head -50

echo ""
echo "💡 Tip: Dit zijn de coins die bij de laatste discovery zijn geselecteerd"
echo "💡 Voor real-time lijst, check de logs tijdens bot runtime"
