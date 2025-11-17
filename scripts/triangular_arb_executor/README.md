# Triangular Arbitrage Executor

Complete execution toolkit for automated triangular arbitrage trading on Kraken.

## Quick Start

### 1. Verify API Keys
```bash
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
python3 test_kraken_keys.py
```

Expected output: ✓ API KEY TESTS COMPLETED

### 2. Compare Exchanges (Kraken vs Bitstamp)
```bash
python3 compare_exchanges.py
```

Shows statistics on opportunities across both exchanges + recommendation on which is better.

### 3. Dry-Run Testing (30 min - NO REAL TRADES)
```bash
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
python3 execute_triangular_dry_run.py

# In another terminal, monitor:
tail -f ../logs/dry_run_executions.log
```

**What it does:**
- Reads candidate opportunities from `logs/tri_candidates.log`
- Simulates trade execution (buys at ask, sells at bid, includes slippage & fees)
- Logs what it "would execute" to `dry_run_executions.log`
- **NO real money spent**

### 4. Live Execution (Start Small!)

#### Phase A: Test with 10 EUR
```bash
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
export KRAKEN_EXECUTE_TRADES=true
export KRAKEN_ORDER_SIZE_EUR=10
export KRAKEN_MIN_EDGE_PCT=0.20
python3 execute_triangular_live.py

# Monitor:
tail -f ../logs/live_executions.log
```

Run for **30 minutes**, check if trades are profitable.

#### Phase B: Scale to 25 EUR
```bash
export KRAKEN_ORDER_SIZE_EUR=25
export KRAKEN_MIN_EDGE_PCT=0.15
python3 execute_triangular_live.py
```

Run for **1 hour**, continue monitoring.

#### Phase C: Scale to 50+ EUR (if Phase B profitable)
```bash
export KRAKEN_ORDER_SIZE_EUR=50
export KRAKEN_MIN_EDGE_PCT=0.12
python3 execute_triangular_live.py
```

---

## File Reference

| Script | Purpose | Real Trades? | Safety |
|--------|---------|------------|--------|
| `test_kraken_keys.py` | Verify API keys work | No | ✅ Read-only test |
| `compare_exchanges.py` | Stats: Kraken vs Bitstamp | No | ✅ Read-only analysis |
| `execute_triangular_dry_run.py` | Simulate execution | No | ✅ 100% Safe |
| `execute_triangular_live.py` | **Place real orders** | **Yes** | ⚠️ Start small! |

---

## Environment Variables

### Required
- `KRAKEN_API_KEY` — Your Kraken API key
- `KRAKEN_SECRET_KEY` — Your Kraken secret

### Optional (Dry-Run & Live)
- `KRAKEN_MIN_EDGE_PCT` — Minimum edge % to execute (default: 0.15%)
- `KRAKEN_ORDER_SIZE_EUR` — Order size in EUR (default: 50)
- `KRAKEN_EXECUTE_TRADES` — Set to "true" to enable real execution (default: false)

---

## Configuration

Edit the `CONFIG` dict inside each script to customize:

**Dry-Run** (`execute_triangular_dry_run.py`):
```python
'min_edge_pct_to_execute': Decimal('0.10'),  # Only simulate if edge > 0.1%
'order_size_eur': Decimal('100'),             # Simulate 100 EUR orders
'slippage_pct': Decimal('0.3'),               # Add 0.3% slippage model
'taker_fee_pct': Decimal('0.26'),             # Kraken taker fee
```

**Live** (`execute_triangular_live.py`):
```python
'min_edge_pct_to_execute': Decimal('0.15'),   # Execute if edge > 0.15%
'order_size_eur': Decimal('50'),              # Start with 50 EUR
'max_open_trades': 10,                        # Max 10 simultaneous trades
'max_trades_per_day': 100,                    # Max 100 trades/day
```

---

## Safety Features

### Dry-Run
- Simulates slippage & fees realistically
- Logs what "would execute" without placing orders
- 100% safe, no capital at risk

### Live Executor
- Configurable order size (start small: 10 EUR)
- Minimum edge threshold filter (prevent low-profit trades)
- Max open trades limit (prevents overexposure)
- Max trades per day limit (prevents runaway execution)
- Order timeout (cancels unfilled orders after 30s)
- All trades logged with timestamps & order IDs

---

## Workflow

### Recommended First Run

```bash
# Terminal 1: Start test key verification
python3 test_kraken_keys.py
# → Should output: ✓ API KEY TESTS COMPLETED

# Terminal 2: Check opportunities (Kraken vs Bitstamp)
python3 compare_exchanges.py
# → Should show top routes + recommendation

# Terminal 3: Run dry-run for 30 min
export KRAKEN_API_KEY="..."
export KRAKEN_SECRET_KEY="..."
python3 execute_triangular_dry_run.py

# Terminal 4: Monitor dry-run in real-time
tail -f ../logs/dry_run_executions.log
```

After 30 min:
1. Check log: how many "would execute" opportunities?
2. What's the average edge %?
3. Are prices realistic vs. order book?

If satisfied with dry-run, **Phase A: Live with 10 EUR** (see section above).

---

## Troubleshooting

### "EAPI:Invalid key"
- Keys might have expired on Kraken
- Regenerate new keys in Kraken Settings → API

### No opportunities logged
- Kraken monitor may not be running (`scripts/triangular_arb/03_monitor_continuous_24h.py`)
- Check: `ps aux | grep 03_monitor | grep -v grep`
- If not running, start it: `nohup python3 scripts/triangular_arb/03_monitor_continuous_24h.py &`

### Dry-run shows very small edges
- Expected! Real market conditions include slippage & fees
- Only simulate/execute if edge > threshold

### Live trades not executing
- Check min edge threshold is not too high
- Verify order book liquidity (small orders easier to fill)
- Check Kraken status page for API issues

---

## Logs

All executions logged to `../logs/`:

- `tri_candidates.log` — Real-time candidate opportunities (from monitor)
- `dry_run_executions.log` — Simulated executions (dry-run script)
- `live_executions.log` — Real trade executions (live script)

View in real-time:
```bash
tail -f ../logs/dry_run_executions.log
tail -f ../logs/live_executions.log
```

Parse JSON:
```bash
tail -20 ../logs/live_executions.log | jq '.edge_pct'
```

---

## Important Notes

⚠️ **Before Going Live:**

1. **Run dry-run for at least 1-2 hours** to validate behavior
2. **Start with small order sizes (10 EUR)** and monitor closely
3. **Never enable live execution on untested code**
4. **Monitor Kraken status** for API/market issues
5. **Have a daily loss limit** and stick to it

💡 **Best Practices:**

- Run during peak market hours (11:00-23:00 UTC) for better liquidity
- Monitor network latency (Kraken API rate limits if too fast)
- Periodically review logs for profitability trends
- Adjust thresholds based on real execution results
- Keep API keys secure; rotate regularly

---

## Questions?

If scripts behave unexpectedly:
1. Check logs for error messages
2. Verify API keys and permissions
3. Ensure Kraken/network connectivity
4. Try verbose mode (edit script logging level)

Good luck! 🚀
