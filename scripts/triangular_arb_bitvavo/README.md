# Bitvavo Triangular Arbitrage Monitor (ccxt-based)

This directory contains scripts for discovering and monitoring triangular arbitrage opportunities on Bitvavo using `ccxt` (no Hummingbot connector required).

## Quick Start

### Prerequisites
- Python 3.8+
- Hummingbot project venv activated: `source ~/.venvs/bot/bin/activate`
- Install ccxt: `pip install ccxt`

### Step 1: Quick Scan (assess viability)
```bash
python3 01_bitvavo_quick_scan.py
```

**Output:**
- Prints top 20 routes by net edge (after fees) to console
- Saves detailed results to `logs/bitvavo_routes_scan.csv`
- Summary: "VIABLE" or "NOT VIABLE" for triangular arbitrage

**Time:** ~30 seconds to 2 minutes (depends on number of pairs and network latency)

### Step 1b: Test Bitvavo API Keys (Optional)
If you have Bitvavo API keys and want to validate them:

```bash
# Export your keys (or pass inline, don't paste in script!)
export BITVAVO_API_KEY="your_key"
export BITVAVO_API_SECRET="your_secret"

# Test the keys
python3 05_test_bitvavo_keys.py
```

Expected output: "✓ API keys are VALID and have read permissions" + your balance summary

### Step 2: 24h Paper-Trade Monitor (if viable)
If Step 1 shows profitable routes, run the continuous monitor:

```bash
# Run in foreground (with logs printed to terminal)
python3 03_monitor_continuous_24h_bitvavo.py

# OR run in background and tail the log file
nohup python3 03_monitor_continuous_24h_bitvavo.py &> logs/bitvavo_monitor.log &
tail -f logs/tri_candidates_bitvavo_ccxt.log

# WITH API keys (optional, for authenticated data):
export BITVAVO_API_KEY="your_key"
export BITVAVO_API_SECRET="your_secret"
python3 03_monitor_continuous_24h_bitvavo.py
```

**Features:**
- Maintains paper-trade balances (initial seed: 50 EUR, 50 USDT, etc.)
- Polls every 5 seconds
- Simulates execution with slippage (0.2% per leg) and taker fees (0.2%)
- Logs candidates to `logs/tri_candidates_bitvavo_ccxt.log` (JSON lines)
- Does NOT execute real trades
- 100% safe to run 24/7

**To stop:**
- Foreground: `Ctrl+C`
- Background: `pkill -f "03_monitor_continuous_24h_bitvavo.py"`

## Output Files

- `logs/bitvavo_routes_scan.csv` — detailed scan results (pair1, pair2, pair3, volumes, edge %)
- `logs/tri_candidates_bitvavo_ccxt.log` — continuous log of detected opportunities (JSON format)
- `logs/bitvavo_monitor.log` — debug/info logs (if run in background)

## Sample Log Entry (JSON)
```json
{
  "timestamp": "2025-11-09T14:30:45.123456",
  "pair1": "EUR/BTC",
  "pair2": "BTC/ETH",
  "pair3": "ETH/EUR",
  "available_balance": 50.0,
  "start_amount": 50.0,
  "final_amount": 50.075,
  "edge": 0.075,
  "edge_pct": 0.15,
  "mid_prices": [19500.5, 0.052, 94250.0]
}
```

## Configuration

Edit the `BitvavoPaperTradeMonitor.CONFIG` dict in `03_monitor_continuous_24h_bitvavo.py` to customize:

```python
CONFIG = {
    'poll_interval': 5.0,  # seconds between polls
    'taker_fee_pct': Decimal('0.2'),  # Bitvavo fee
    'slippage_pct_per_leg': Decimal('0.2'),  # slippage model per leg
    'min_edge_pct_to_log': Decimal('0.05'),  # only log if edge > 0.05%
    'order_amount_pct': Decimal('1.0'),  # use 100% of available balance
}
```

## Caveats & Notes

1. **ccxt-based**: Uses ccxt library for API calls; does NOT use Hummingbot connectors
2. **Paper-trade only**: Balances and orders are simulated in memory; no live execution
3. **Mid-price + slippage**: Simulates execution by walking the order book or assuming conservative slippage
4. **Rate limits**: ccxt respects Bitvavo rate limits; if you see 429 errors, increase `poll_interval`
5. **EUR focus**: Bitvavo is EUR-heavy; triangles with EUR pairings are most liquid

## Next Steps

- If viable: run 24h monitor to collect data on real opportunities
- If profitable routes found: consider implementing a full Hummingbot Bitvavo connector for live trading
- Share results with this agent to plan next phase (live trading, multi-exchange monitoring, etc.)

## Troubleshooting

**No triangles found:**
- Bitvavo may have limited pair overlap; check manually on their website
- Try again at peak market hours (more liquidity = more pairs)

**Rate limit errors (429):**
- Increase `poll_interval` in CONFIG (e.g., 10.0 instead of 5.0)
- Reduce logging frequency or number of polled triangles

**No profitable routes logged:**
- Edge threshold may be too high; lower `min_edge_pct_to_log` to 0.01
- Fees/slippage assumptions may be conservative; adjust CONFIG

**API/network errors:**
- Check Bitvavo status page
- Ensure your machine has internet connectivity
- Try restarting the monitor

## Author Notes

These scripts are proof-of-concept tools for rapid assessment of arbitrage viability on Bitvavo. If results are positive, we recommend:
1. Collecting 24h+ of candidate data to understand true profitability distribution
2. Implementing a native Bitvavo connector in Hummingbot (if live trading is desired)
3. Integrating with order management and risk controls (position limits, max drawdown, etc.)
