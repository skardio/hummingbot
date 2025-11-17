# Triangular Arbitrage Tools - BITSTAMP

Georganiseerde scripts voor triangular arbitrage discovery, testing, en continuous monitoring op Bitstamp.

⚠️ **NOTE**: Dit is aparte version voor Bitstamp. Voor Kraken, zie `../triangular_arb/`

## Scripts

### 3️⃣ `03_monitor_continuous_24h_bitstamp.py`
**Purpose**: Real-time continuous monitor die 24/7 naar profitable opportunities scant (paper-trade mode).

**Output**:
- `logs/tri_candidates_bitstamp.log` – JSON lines van gedetecteerde opportunities
- `logs/bot_stdout_bitstamp.log` – Full bot console output (als je nohup gebruikt)

**Usage - Option A (nohup, background)**:
```bash
cd /home/mo/repos/hummingbot
nohup python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py > logs/bot_stdout_bitstamp.log 2>&1 &
```

**Usage - Option B (screen, beheersbaar)**:
```bash
cd /home/mo/repos/hummingbot
screen -S arb_bitstamp -d -m python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py
```

**Usage - Option C (direct run)**:
```bash
python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py
```

**Monitor real-time output**:
```bash
tail -f logs/tri_candidates_bitstamp.log
```

**What it does**:
1. Initialized Bitstamp connector in paper-trade mode
2. Laadt alle 42 top routes (ETH, USDC, EUR, USD, GBP, CAD, AUD, CHF, JPY, USDT)
3. Elke 5 seconden:
   - Fetcht live mid-prices van Bitstamp
   - Voor elke route: haalt beschikbaar saldo op voor base currency A
   - Berekent `order_amount = available_balance * 100%` (dynamic allocation)
   - Berekent implied vs actual prices
   - Detecteert arbitrage edges
   - Appliceert fees/slippage
   - Logt candidates naar `logs/tri_candidates_bitstamp.log`
4. Wacht op profitable "event moments" (market dislocations)

**Example log output**:
```json
{"timestamp":"2025-11-09T14:30:21.538493","triple":["ETH-USD","USD-EUR","ETH-EUR"],"implied_ac":1.0812,"actual_ac":1.0795,"edge_pct":0.1573,"profit_pct_after_fees":0.0175}
{"timestamp":"2025-11-09T14:30:26.745621","triple":["USDC-USD","USD-EUR","USDC-EUR"],"implied_ac":1.0089,"actual_ac":1.0075,"edge_pct":0.1389,"profit_pct_after_fees":-0.0611}
```

---

## Configuration

Alle settings zijn in `03_monitor_continuous_24h_bitstamp.py` in CONFIG dict:

| Setting | Value | Meaning |
|---------|-------|---------|
| `exchange` | `"bitstamp"` | Use Bitstamp exchange |
| `triples` | 42 routes | All top-20 routes (ETH + USDC + EUR + AUD) |
| `order_amount_pct` | 1.0 (100%) | Use 100% of available base currency balance per cycle |
| `min_profitability_pct` | 0.0 | Report edges ≥ 0.0% |
| `poll_interval` | 5.0 sec | Check prices every 5 seconds |
| `execute_trades` | False | Paper-trade mode (no real money) |
| `use_paper_trade` | True | Use simulated market |
| `taker_fee_pct` | 0.5% | Bitstamp's taker fee (0.5% vs Kraken 0.26%) |
| `slippage_pct_per_leg` | 0.2% | Per-leg price impact |

**Dynamic Balance Allocation**:
- Bot fetches available balance for each base currency (A) before checking that triple
- Order amount = `available_balance * order_amount_pct`
- With `order_amount_pct: 1.0`, bot uses 100% of available balance per cycle
- Initial paper-trade balances set at startup:
  - ETH: 0.5, USDC/EUR/USD/AUD/GBP/CAD/CHF/JPY/USDT: 50 each

**To change settings**:
1. Edit CONFIG dict in `03_monitor_continuous_24h_bitstamp.py`
2. Modify `taker_fee_pct`, `poll_interval`, or `order_amount_pct`
3. Restart bot with new screen session

---

## Running Both Bots (Kraken + Bitstamp)

Run them simultaneously in separate screen sessions:

**Terminal 1 - Kraken**:
```bash
cd /home/mo/repos/hummingbot
screen -S arb_kraken -d -m python3 scripts/triangular_arb/03_monitor_continuous_24h.py
```

**Terminal 2 - Bitstamp**:
```bash
cd /home/mo/repos/hummingbot
screen -S arb_bitstamp -d -m python3 scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py
```

**Monitor both**:
```bash
# Kraken candidates
tail -f logs/tri_candidates.log

# Bitstamp candidates (new terminal)
tail -f logs/tri_candidates_bitstamp.log
```

**List running screens**:
```bash
screen -ls
# Output:
# 	12345.arb_kraken		(Detached)
# 	12346.arb_bitstamp		(Detached)
```

**Reattach to Kraken**:
```bash
screen -r arb_kraken
```

**Reattach to Bitstamp**:
```bash
screen -r arb_bitstamp
```

**Kill Kraken bot**:
```bash
screen -S arb_kraken -X quit
# or
pkill -f "triangular_arb/03_monitor_continuous_24h.py"
```

**Kill Bitstamp bot**:
```bash
screen -S arb_bitstamp -X quit
# or
pkill -f "triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py"
```

---

## Expected Results

### Bitstamp Market (~€50 per route)
- **Higher taker fee**: 0.5% (vs Kraken 0.26%)
- **Expected profitability**: Likely -1.7% to -2.0% loss (higher fees + spreads)
- **Bot behavior**: Logs all detections, but profitable edges less frequent than Kraken due to higher fees

### Comparison: Kraken vs Bitstamp
| Metric | Kraken | Bitstamp |
|--------|--------|----------|
| Taker Fee | 0.26% | 0.5% |
| Per-leg slippage | 0.2% | 0.2% |
| Total 3-leg cost | ~1.2% | ~1.8% |
| Min profitable edge | >1.2% | >1.8% |

When Profitable Opportunities Appear on Bitstamp:
```bash
tail -100 logs/tri_candidates_bitstamp.log | grep "profit_pct_after_fees" | grep -v "\-"
```

---

## Troubleshooting

**Bot crashes on start**:
- Ensure Bitstamp connector is available: `python3 -c "from hummingbot.connector.exchange.bitstamp import BitstampExchange"`
- Check Python version: `python3 --version` (need 3.8+)

**No logs to `tri_candidates_bitstamp.log`**:
- Check that min_profitability_pct is low (currently 0.0)
- Verify Bitstamp API responding: `curl -s "https://www.bitstamp.net/api/v2/ticker/btcusd/"`
- Check `logs/bot_stdout_bitstamp.log` for errors

**High CPU usage**:
- Increase poll_interval in CONFIG (e.g., 10.0 instead of 5.0)
- Reduce number of triples to monitor

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/triangular_arb_bitstamp/03_monitor_continuous_24h_bitstamp.py` | Main monitor bot for Bitstamp |
| `logs/tri_candidates_bitstamp.log` | Live detections from Bitstamp monitor bot (appended each run) |
| `logs/bot_stdout_bitstamp.log` | Full console output (if using nohup) |

---

**Ready to monitor Bitstamp triangular arbitrage! 🚀**
