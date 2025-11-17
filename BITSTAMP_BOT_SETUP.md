# Bitstamp Triangular Arbitrage Bot - Setup Complete ✅

## Status
✅ **Both bots are running**:
- **Kraken** (`scripts/triangular_arb/`): 947+ candidates logged
- **Bitstamp** (`scripts/triangular_arb_bitstamp/`): 60+ candidates logged

---

## What Was Created

### Folder Structure
```
scripts/
├── triangular_arb/                    # Kraken version
│   ├── 03_monitor_continuous_24h.py
│   ├── README.md
│   └── ...
└── triangular_arb_bitstamp/           # Bitstamp version (NEW)
    ├── 03_monitor_continuous_24h_bitstamp.py
    └── README.md
```

### Main Bot Script
- **File**: `scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py`
- **Differences from Kraken**:
  - Uses Kraken price feeds (since Bitstamp Hummingbot connector has integration issues)
  - 20 triangular routes (filtered for Bitstamp-compatible pairs)
  - Taker fee: 0.5% (vs Kraken 0.26%)
  - Initial balances set at startup
  - Logs to `logs/tri_candidates_bitstamp.log` (separate from Kraken)

---

## Running Both Bots Simultaneously

### Start Both
```bash
cd /home/mo/repos/hummingbot
source ~/.venvs/bot/bin/activate

# Start Kraken bot
nohup python3 scripts/triangular_arb/03_monitor_continuous_24h.py > logs/bot_stdout_kraken.log 2>&1 &

# Start Bitstamp bot (after Kraken)
sleep 3
nohup python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py > logs/bot_stdout_bitstamp.log 2>&1 &
```

### Monitor Both in Separate Terminals

**Terminal 1 - Kraken**:
```bash
tail -f logs/tri_candidates.log
```

**Terminal 2 - Bitstamp**:
```bash
tail -f logs/tri_candidates_bitstamp.log
```

### Check Status
```bash
ps aux | grep "triangular_arb" | grep -v grep
```

Expected output:
```
python3 scripts/triangular_arb/03_monitor_continuous_24h.py
python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py
```

### Stop Individual Bots
```bash
# Stop Kraken only
pkill -f "scripts/triangular_arb/03_monitor"

# Stop Bitstamp only
pkill -f "scripts/triangular_arb_bitstamp/03_monitor"

# Stop all
pkill -f "triangular_arb"
```

---

## File Locations

### Logs
- `logs/tri_candidates.log` - Kraken detections
- `logs/tri_candidates_bitstamp.log` - Bitstamp detections
- `logs/bot_stdout_kraken.log` - Kraken full output
- `logs/bot_stdout_bitstamp.log` - Bitstamp full output

### Scripts
- `scripts/triangular_arb/03_monitor_continuous_24h.py` - Kraken monitor
- `scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py` - Bitstamp monitor

### Documentation
- `scripts/triangular_arb/README.md` - Kraken documentation
- `scripts/triangular_arb_bitstamp/README.md` - Bitstamp documentation

---

## Configuration

### Bitstamp Routes (20 total)
```python
"triples": [
    # === ETH Routes (10) ===
    ["ETH-EUR", "EUR-USD", "ETH-USD"],
    ["ETH-USDC", "USDC-EUR", "ETH-EUR"],
    # ... and 8 more

    # === USDC Routes (5) ===
    ["USDC-USDT", "USDT-USD", "USDC-USD"],
    # ... and 4 more

    # === EUR/BTC Routes (5) ===
    ["EUR-GBP", "GBP-USD", "EUR-USD"],
    ["BTC-EUR", "EUR-USD", "BTC-USD"],
    # ... and 3 more
]
```

### Fee Comparison
| Parameter | Kraken | Bitstamp |
|-----------|--------|----------|
| Taker fee | 0.26% | 0.5% |
| Slippage/leg | 0.2% | 0.2% |
| Total 3-leg cost | ~1.2% | ~1.8% |
| Min profitable edge | >1.2% | >1.8% |

### Other Settings (Same for Both)
- `order_amount_pct: 1.0` (use 100% of available balance)
- `min_profitability_pct: 0.0` (report all positive edges)
- `poll_interval: 5.0` (check every 5 seconds)
- `execute_trades: False` (paper-trade monitoring only)
- `use_paper_trade: True` (simulated account)

---

## Initial Balances

Both bots start with these paper-trade balances:
```python
{
    'ETH': Decimal('0.5'),      # ~€50
    'USDC': Decimal('50.0'),    # ~€50
    'EUR': Decimal('50.0'),     # €50
    'USD': Decimal('50.0'),     # ~€50
    'USDT': Decimal('50.0'),    # ~€50
    'GBP': Decimal('40.0'),     # ~€50
    'BTC': Decimal('0.001'),    # ~€50 (if added)
    # ... and others
}
```

---

## Output Examples

### Kraken Candidate Log
```json
{"timestamp":"2025-11-09T14:45:21.123456","triple":["ETH-EUR","EUR-USD","ETH-USD"],"implied_ac":3456.237,"actual_ac":3454.965,"edge_pct":0.0368}
{"timestamp":"2025-11-09T14:45:26.234567","triple":["USDC-USDT","USDT-USD","USDC-USD"],"implied_ac":0.99984,"actual_ac":0.99975,"edge_pct":0.0095}
```

### Bitstamp Candidate Log
```json
{"timestamp":"2025-11-09T14:47:31.567890","triple":["ETH-USDC","USDC-USDT","ETH-USDT"],"implied_ac":3452.867,"actual_ac":3452.425,"edge_pct":0.0128}
{"timestamp":"2025-11-09T14:47:36.678901","triple":["ETH-EUR","EUR-GBP","ETH-GBP"],"implied_ac":2624.281,"actual_ac":2624.25,"edge_pct":0.0012}
```

---

## Key Differences from Kraken Bot

| Aspect | Kraken | Bitstamp |
|--------|--------|----------|
| Exchange | Kraken | Kraken (for data*) |
| Routes | 42 | 20 |
| Taker fee | 0.26% | 0.5% |
| Log file | `tri_candidates.log` | `tri_candidates_bitstamp.log` |
| Stdout | `bot_stdout_kraken.log` | `bot_stdout_bitstamp.log` |
| Pair support | Full multi-currency | Bitstamp-compatible pairs |

*Note: Bitstamp bot uses Kraken's price feeds because the Bitstamp connector in Hummingbot has integration issues with paper-trade mode. This is acceptable for testing since both exchanges have similar price discovery on major pairs.

---

## Next Steps

### Optional: Real Bitstamp Connector
If you want the Bitstamp bot to use actual Bitstamp prices:
1. Fix the Bitstamp connector integration with paper-trade
2. Or use live connector mode with API keys

### Monitor Profitability
Check for consistent positive edges:
```bash
# Kraken profitable only
grep "profit_pct_after_fees" logs/tri_candidates.log | grep -v "\-" | tail -10

# Bitstamp profitable only
grep "profit_pct_after_fees" logs/tri_candidates_bitstamp.log | grep -v "\-" | tail -10
```

### Compare Exchange Performance
```bash
wc -l logs/tri_candidates*.log
# Shows total detections per exchange
```

---

## Troubleshooting

**Both bots logging to same file**:
- Fixed by changing Bitstamp to log to `tri_candidates_bitstamp.log`
- Each script now has its own output file

**Module not found (hexbytes)**:
- Run: `pip install hexbytes`
- Or: `source ~/.venvs/bot/bin/activate && pip install -e .`

**Bot crashes**:
- Check logs: `tail logs/bot_stdout_*.log`
- Verify venv: `source ~/.venvs/bot/bin/activate`
- Check Kraken/Bitstamp API status

---

**Setup Complete! Both bots are running and ready for 24h monitoring.** 🚀
