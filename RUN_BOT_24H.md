# 24-Hour Triangular Arbitrage Monitoring Bot

Bot is configured to monitor **35 top-20 routes** (20 ETH + 15 USDC) on Kraken for profitable opportunities.

## Quick Start

### Option 1: Simple background run (nohup)
```bash
cd /home/mo/repos/hummingbot
nohup python3 scripts/triangular_arbitrage_bot.py > logs/bot_stdout.log 2>&1 &
```
- Bot runs in background even if terminal closes
- Output logged to `logs/bot_stdout.log`
- Check PID: `jobs -l` or `ps aux | grep triangular_arbitrage_bot.py`

### Option 2: Screen session (recommended - easier to monitor)
```bash
cd /home/mo/repos/hummingbot
screen -S arb_monitor -d -m python3 scripts/triangular_arbitrage_bot.py
```
- Attach to monitor: `screen -r arb_monitor`
- Detach from screen: `Ctrl+A` then `D`
- List sessions: `screen -ls`
- Kill session: `screen -S arb_monitor -X quit`

### Option 3: Direct run (for testing)
```bash
cd /home/mo/repos/hummingbot
python3 scripts/triangular_arbitrage_bot.py
```

## Monitor Progress

### Watch real-time detections:
```bash
tail -f logs/tri_candidates.log
```

### Sample output (JSON lines):
```json
{"timestamp":"2025-11-09T00:02:21.538493","triple":["ETH-EUR","EUR-USD","ETH-USD"],"implied_ac":1.0812,"actual_ac":1.0795,"edge_pct":0.1573,"profit_pct_after_fees":0.0175}
{"timestamp":"2025-11-09T00:02:26.745621","triple":["USDC-USDT","USDT-USD","USDC-USD"],"implied_ac":1.0089,"actual_ac":1.0075,"edge_pct":0.1389,"profit_pct_after_fees":-0.0611}
```

### Key fields to look for:
- **edge_pct**: Percentage arbitrage opportunity (raw, before fees)
- **profit_pct_after_fees**: Net profit after 0.26% taker fee × 3 legs + 0.2% slippage per leg
  - **Positive value** = potential profit opportunity
  - **Negative value** = expected loss at current prices
  - **≥ 0.2%** = candidate worth investigating (threshold set in CONFIG["min_profitability_pct"])

### Full bot output log:
```bash
tail -f logs/bot_stdout.log
```

## Configuration

All settings in `scripts/triangular_arbitrage_bot.py` CONFIG dict:

| Setting | Value | Meaning |
|---------|-------|---------|
| `triples` | 35 routes | Routes from top-20 scan (20 ETH + 15 USDC) |
| `min_profitability_pct` | 0.0 | Report all edges ≥ 0.0% |
| `poll_interval` | 5.0 sec | Check prices every 5 seconds |
| `execute_trades` | False | Paper-trade mode only (no real money) |
| `use_paper_trade` | True | Use simulated market |
| `taker_fee_pct` | 0.26% | Kraken's taker fee per leg |
| `slippage_pct_per_leg` | 0.2% | Conservative slippage estimate |

## Stop the Bot

### If running with nohup:
```bash
pkill -f "python3 scripts/triangular_arbitrage_bot.py"
# or find PID and kill it:
ps aux | grep triangular_arbitrage_bot.py
kill -9 <PID>
```

### If running in screen:
```bash
screen -S arb_monitor -X quit
# or attach then press Ctrl+C:
screen -r arb_monitor
# then Ctrl+C
```

## Expected Behavior

1. **Startup**: Bot initializes connector, loads 35 routes, starts polling
2. **Polling loop**: Every 5 seconds:
   - Fetches live mid-prices from Kraken Ticker API
   - Calculates implied vs actual prices
   - Computes edge and net profit
   - If profit_pct_after_fees > min_profitability_pct, logs to `tri_candidates.log`
3. **No profitable routes expected initially**: Current market is efficient (~-1.3% to -1.4% loss on all routes)
   - Bot will log detections, but no profitable edges expected unless market dislocations occur
4. **Waiting for "event moments"**: Bot will catch if profitable opportunities appear (e.g., exchange lag, order book imbalance)

## Data Files

- `logs/tri_candidates.log` – All detection candidates (JSON lines, appended each run)
- `logs/bot_stdout.log` – Full bot console output (if using nohup)
- `logs/top20_routes_ETH.json` – 20 ETH-starting routes with liquidity scores
- `logs/top20_routes_USDC.json` – 15 USDC-starting routes with liquidity scores

## Troubleshooting

**Bot crashes with "connector not found":**
- Ensure Hummingbot is installed and Kraken connector available
- Check: `python3 -c "from hummingbot.connector.exchange.kraken import KrakenExchange"`

**No output to `tri_candidates.log`:**
- Check that min_profitability_pct is set low (currently 0.0)
- Verify Kraken API is responding: `curl -s "https://api.kraken.com/0/public/Ticker?pair=ETHUSD" | head -20`
- Check `bot_stdout.log` for error messages

**High CPU usage:**
- Reduce poll_interval (e.g., 10.0 instead of 5.0)
- Reduce number of triples to monitor (edit CONFIG["triples"])

**Kraken API rate limit:**
- If seeing 429 errors, Kraken is throttling
- Increase poll_interval or wait before restarting
- Current setup: 35 routes × 0.1 API calls per route per 5s = ~7 requests/5s (well within limits)

---

**Ready to run!** Start bot and let it monitor for 24 hours.
