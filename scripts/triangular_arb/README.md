# Triangular Arbitrage Tools

Georganiseerde scripts voor triangular arbitrage discovery, testing, en continuous monitoring op Kraken.

## Scripts

### 1️⃣ `01_discover_top20_routes.py`
**Purpose**: Discover en rank top-20 triangular arbitrage routes op basis van 24h liquidity volume.

**Output**:
- `logs/top20_routes_ETH.json` – 20 beste routes startend met ETH
- `logs/top20_routes_USDC.json` – 15 beste routes startend met USDC

**Usage**:
```bash
python3 scripts/triangular_arb/01_discover_top20_routes.py
```

**What it does**:
1. Haalt alle 1,228 mogelijke triangular routes op van Kraken
2. Ranked ze op 24-hour liquidity volume
3. Filtert top-20 voor ETH en top-15 voor USDC
4. Saves JSON met route rankings en liquidity scores

---

### 2️⃣ `02_simulate_profitability.py` (Recommended for Kraken)
**Purpose**: Simulate profit/loss voor alle discovered routes met realistische slippage + fees (using mid-prices).

**Output**:
- `logs/midprice_sim_ETH_summary.csv` – Simulatie resultaten ETH routes
- `logs/midprice_sim_USDC_summary.csv` – Simulatie resultaten USDC routes

**Usage**:
```bash
python3 scripts/triangular_arb/02_simulate_profitability.py
```

**What it does**:
1. Laadt top-20 routes uit JSON files
2. Voor elke route met €50 startkapitaal:
   - Simuleert 3-leg trade via Kraken Ticker mid-prices
   - Appliceert 0.2% slippage per leg
   - Appliceert 0.26% taker fee per leg
3. Berekent net profit/loss percentage
4. Genereert CSV summary

**Example output**:
```
route,profit_pct,amounts_a,amounts_b,amounts_c,edge_pct
['ETH-EUR', 'EUR-USD', 'ETH-USD'],-1.4178,0.017,15.27,15.11,-0.0615
['USDC-USDT', 'USDT-USD', 'USDC-USD'],-1.3673,50.0,50.36,49.32,0.0268
```

---

### 2A️⃣ `02a_simulate_with_depth.py` (Alternative - Depth-based)
**Purpose**: Simulate using live Kraken Depth orderbooks (€50 per route).

**Output**:
- `logs/tri_depth_top20_ETH.jsonl` – Depth-based simulation results per route (JSON lines)
- `logs/tri_depth_top20_ETH_summary.csv` – Summary CSV
- `logs/tri_depth_top20_USDC.jsonl`, `logs/tri_depth_top20_USDC_summary.csv` – Same for USDC

**Usage**:
```bash
python3 scripts/triangular_arb/02a_simulate_with_depth.py
```

**What it does**:
1. Laadt top-20 routes uit JSON files
2. Computes €50 equivalent in base asset units (A)
3. Voor elke route:
   - Fetches live Kraken Depth orderbook voor alle 3 pairs
   - Simuleert 3-leg fill (sell A via bids, sell B via bids, buy A via asks)
   - Applies 0.26% taker fee per leg
   - Reports fill status: full fill vs partial/insufficient depth
4. Writes JSONL per route + CSV summary

**Note**: Kraken Depth API often returns empty orderbooks voor public pairs. Use `02_simulate_profitability.py` (mid-price based) voor meer reliable results.

---

### 2B️⃣ `02b_filter_by_depth_and_retest.py` (Optional)
**Purpose**: Filter routes by non-empty Kraken Depth orderbooks en re-test alleen die routes.

---

### 2B️⃣ `02b_filter_by_depth_and_retest.py` (Optional)
**Purpose**: Filter routes by non-empty Kraken Depth orderbooks en re-test alleen die routes.

**Output**:
- `logs/midprice_sim_ETH_depth_filtered_summary.csv` – Filtered ETH routes met actieve orderbooks
- `logs/midprice_sim_USDC_depth_filtered_summary.csv` – Filtered USDC routes met actieve orderbooks

**Usage**:
```bash
python3 scripts/triangular_arb/02b_filter_by_depth_and_retest.py
```

**What it does**:
1. Laadt top-20 routes uit JSON files
2. Voor elke route: checked of alle 3 pairs niet-lege Depth orderbooks hebben
3. Filtert routes met lege orderbooks uit (inactive pairs)
4. Re-simuleert profitability alleen voor routes met actieve pairs
5. Genereert gefilterde CSV summary

**Note**: Kraken Depth API retourneert vaak lege orderbooks voor public pairs. Dit script is vooral nuttig als je later naar ander exchanges gaat (Binance, OKX) waar Depth meer reliable is.

---

### 2C️⃣ `02c_depth_simulator.py` (Low-level tool)
**Purpose**: Direct depth-based REST orderbook simulator; uses CONFIG from `03_monitor_continuous_24h.py`.

**Output**:
- `logs/tri_depth.log` – Raw JSON lines of simulation results
- `logs/tri_depth_summary.csv` – CSV summary

**Usage**:
```bash
python3 scripts/triangular_arb/02c_depth_simulator.py
```

**What it does**:
1. Loads CONFIG triples from `03_monitor_continuous_24h.py`
2. Simulates depth-based fills for each triple (same logic as 02a)
3. Writes results to JSONL + CSV

**Note**: This is a lower-level tool; use `02a` or `02` instead for top-20 routes specifically.

---

### 3️⃣ `03_monitor_continuous_24h.py`
**Purpose**: Real-time continuous monitor die 24/7 naar profitable opportunities scant (paper-trade mode).

**Output**:
- `logs/tri_candidates.log` – JSON lines van gedetecteerde opportunities
- `logs/bot_stdout.log` – Full bot console output (als je nohup gebruikt)

**Usage - Option A (nohup, background)**:
```bash
cd /home/mo/repos/hummingbot
nohup python3 scripts/triangular_arb/03_monitor_continuous_24h.py > logs/bot_stdout.log 2>&1 &
```

**Usage - Option B (screen, beheersbaar)**:
```bash
cd /home/mo/repos/hummingbot
screen -S arb_monitor -d -m python3 scripts/triangular_arb/03_monitor_continuous_24h.py
```

**Usage - Option C (direct run)**:
```bash
python3 scripts/triangular_arb/03_monitor_continuous_24h.py
```

**Monitor real-time output**:
```bash
tail -f logs/tri_candidates.log
```

**What it does**:
1. Initialized Kraken connector in paper-trade mode
2. Laadt alle 42 top-20 routes (20 ETH + 15 USDC + 6 EUR + 1 AUD)
3. Elke 5 seconden:
   - Fetcht live mid-prices van Kraken
   - Voor elke route: haalt beschikbaar saldo op voor base currency A
   - Berekent `order_amount = available_balance * 100%` (dynamic allocation)
   - Berekent implied vs actual prices
   - Detecteert arbitrage edges
   - Appliceert fees/slippage
   - Logt candidates naar `tri_candidates.log`
4. Wacht op profitable "event moments" (market dislocations)

**Example log output**:
```json
{"timestamp":"2025-11-09T00:02:21.538493","triple":["ETH-EUR","EUR-USD","ETH-USD"],"implied_ac":1.0812,"actual_ac":1.0795,"edge_pct":0.1573,"profit_pct_after_fees":0.0175}
{"timestamp":"2025-11-09T00:02:26.745621","triple":["USDC-USDT","USDT-USD","USDC-USD"],"implied_ac":1.0089,"actual_ac":1.0075,"edge_pct":0.1389,"profit_pct_after_fees":-0.0611}
```

---

## Workflow

### Step 1: Discover routes (eenmalig)
```bash
python3 scripts/triangular_arb/01_discover_top20_routes.py
# Output: logs/top20_routes_ETH.json, logs/top20_routes_USDC.json
```

### Step 2: Test profitability (eenmalig) - Choose one:

**Option A: Mid-price simulation (RECOMMENDED for Kraken)**
```bash
python3 scripts/triangular_arb/02_simulate_profitability.py
# Output: logs/midprice_sim_ETH_summary.csv, logs/midprice_sim_USDC_summary.csv
# Why: Kraken Depth is reliable; mid-prices always available
```

**Option B: Depth-based simulation (alternative)**
```bash
python3 scripts/triangular_arb/02a_simulate_with_depth.py
# Output: logs/tri_depth_top20_ETH_summary.csv, logs/tri_depth_top20_USDC_summary.csv
# Why: More realistic; uses actual orderbook depth
# Note: Kraken Depth API may return empty books
```

### Step 2B: Optional - Filter by active orderbooks (eenmalig, optional)
```bash
python3 scripts/triangular_arb/02b_filter_by_depth_and_retest.py
# Output: logs/midprice_sim_ETH_depth_filtered_summary.csv, logs/midprice_sim_USDC_depth_filtered_summary.csv
# Note: Useful for exchanges with reliable Depth data; Kraken Depth is often empty
```

### Step 3: Run 24h continuous monitor
```bash
screen -S arb_monitor -d -m python3 scripts/triangular_arb/03_monitor_continuous_24h.py
# Let it run, check logs occasionally
tail -f logs/tri_candidates.log
```

---

## Configuration

Alle settings zijn in `03_monitor_continuous_24h.py` in CONFIG dict:

| Setting | Value | Meaning |
|---------|-------|---------|
| `triples` | 42 routes | All top-20 routes (ETH + USDC + EUR + AUD) |
| `order_amount_pct` | 1.0 (100%) | Use 100% of available base currency balance per cycle |
| `min_profitability_pct` | 0.0 | Report edges ≥ 0.0% |
| `poll_interval` | 5.0 sec | Check prices every 5 seconds |
| `execute_trades` | False | Paper-trade mode (no real money) |
| `use_paper_trade` | True | Use simulated market |
| `taker_fee_pct` | 0.26% | Kraken's taker fee |
| `slippage_pct_per_leg` | 0.2% | Per-leg price impact |

**Dynamic Balance Allocation**:
- Bot now fetches available balance for each base currency (A) before checking that triple
- Order amount = `available_balance * order_amount_pct`
- With `order_amount_pct: 1.0`, bot uses 100% of available balance per cycle
- If balance unavailable or zero, that triple is skipped for that poll cycle
- Fallback: If balance query fails, uses fixed `order_amount` (currently 1.0)

**To change settings**:
1. Edit CONFIG dict in `03_monitor_continuous_24h.py`
2. Modify `order_amount_pct` to use different % (e.g., 0.5 for 50%)
3. Restart bot with new screen session

---

## Expected Results

### Current Market (Kraken, ~€50 per route)
- **Expected profitability**: -1.3% to -1.4% loss
- **Reason**: Kraken fees (0.78%) + spreads (0.6%) = 1.4% cost, market is efficient
- **Bot behavior**: Logs all detections, but no profitable edges expected unless market dislocations occur

### When Profitable Opportunities Appear
Bot will log entries to `tri_candidates.log` with `profit_pct_after_fees > 0`. Check periodically:
```bash
tail -100 logs/tri_candidates.log | grep "profit_pct_after_fees" | grep -v "\-"
```

---

## Troubleshooting

**Bot crashes on start**:
- Ensure Kraken connector is available: `python3 -c "from hummingbot.connector.exchange.kraken import KrakenExchange"`
- Check Python version: `python3 --version` (need 3.8+)

**No logs to `tri_candidates.log`**:
- Check that min_profitability_pct is low (currently 0.0)
- Verify Kraken API responding: `curl -s "https://api.kraken.com/0/public/Ticker?pair=ETHUSD"`
- Check `logs/bot_stdout.log` for errors

**High CPU usage**:
- Increase poll_interval in CONFIG (e.g., 10.0 instead of 5.0)
- Reduce number of triples to monitor

---

## Files Reference

| File | Purpose |
|------|---------|
| `logs/top20_routes_ETH.json` | 20 ETH-starting routes (ranked by liquidity) |
| `logs/top20_routes_USDC.json` | 15 USDC-starting routes (ranked by liquidity) |
| `logs/midprice_sim_ETH_summary.csv` | Profitability simulation results for ETH routes |
| `logs/midprice_sim_USDC_summary.csv` | Profitability simulation results for USDC routes |
| `logs/tri_candidates.log` | Live detections from monitor bot (appended each run) |
| `logs/bot_stdout.log` | Full console output (if using nohup) |

---

**Ready to start monitoring! 🚀**
