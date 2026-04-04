# Bot Data Snapshot — 8 March 2026

> **Snapshot date**: 2026-03-08 ~15:00 UTC
> **Purpose**: Attach this file as evidence when running a review round.
> **Shelf life**: Data becomes stale within days. Re-run the queries below
> to generate a fresh snapshot before each review round.

---

## How to regenerate this snapshot

Run from the repo root (`/home/mo/repos/hummingbot`):

```bash
# Activate the venv first
source .venv/bin/activate

# ──────────────────────────────────────────────────
# 1. DATABASE QUERIES  (repeat for each .sqlite DB)
# ──────────────────────────────────────────────────

# Per-pair performance
sqlite3 -header -column data/<DB>.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair,
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN net_pnl_quote < 0 THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN filled_amount_quote = 0 THEN 1 ELSE 0 END) as zero_fill,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY json_extract(config, '\$.trading_pair') ORDER BY total_pnl DESC;"

# Close type distribution
sqlite3 -header -column data/<DB>.sqlite "
SELECT close_type, COUNT(*) as cnt,
    ROUND(SUM(net_pnl_quote), 4) as sum_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY close_type ORDER BY cnt DESC;"

# Date range + totals
sqlite3 -header -column data/<DB>.sqlite "
SELECT date(MIN(timestamp), 'unixepoch') as first,
    date(MAX(timestamp), 'unixepoch') as last,
    COUNT(*) as total,
    SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) as filled,
    ROUND(100.0 * SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as fill_pct,
    ROUND(SUM(net_pnl_quote), 4) as pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as vol
FROM Executors WHERE close_type IS NOT NULL;"

# Futures only: filled trades by pair + close type
sqlite3 -header -column data/futures_grid_bitget.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair, close_type,
    COUNT(*) as cnt,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL AND filled_amount_quote > 0
GROUP BY pair, close_type ORDER BY total_pnl DESC;"

# ──────────────────────────────────────────────────
# 2. LOG ERROR FREQUENCY
# ──────────────────────────────────────────────────

# Find the most recent log for each bot:
ls -t logs/logs_multi_coin_grid_v2_usd_*.log | head -1   # Kraken USD
ls -t logs/logs_spot_grid_bitget_*.log | head -1          # Bitget Spot
ls -t logs/logs_futures_grid_bitget_*.log | head -1       # Bitget Futures

# Then for each:
grep -oP "(ERROR|WARNING|CRITICAL)" <logfile> | sort | uniq -c | sort -rn
grep "ERROR" <logfile> | grep -oP "ERROR - .*" | sort -u | head -15
grep -c "WSS_ERROR\|WebSocket\|websocket" <logfile>       # WebSocket count

# ──────────────────────────────────────────────────
# 3. WHY-NO-TRADE SUMMARIES
# ──────────────────────────────────────────────────

# Find the most recent report log:
ls -t logs/kraken_*report*.log | head -1
ls -t logs/bitget_*report*.log | head -1

# Extract the last few hours:
grep -B1 -A 15 "WHY-NO-TRADE SUMMARY" <report_log> | tail -60

# ──────────────────────────────────────────────────
# 4. ROTATION TIMEOUT EVENTS
# ──────────────────────────────────────────────────

grep -oP "MONITORING TIMEOUT: \K[A-Z]+-[A-Z]+" <logfile> | sort | uniq -c | sort -rn
grep -i "MONITORING TIMEOUT" <logfile> | tail -20
```

Replace `<DB>` with: `multi_coin_grid_v2.sqlite` (Kraken EUR),
`multi_coin_grid_v2_usd.sqlite` (Kraken USD), `spot_grid_bitget.sqlite`
(Bitget Spot), `futures_grid_bitget.sqlite` (Bitget Futures).

---

## Database files

| Database | Bot | Size | Period |
|----------|-----|------|--------|
| `data/multi_coin_grid_v2.sqlite` | Kraken EUR (retired) | 12 MB | 2025-11-20 → 2026-02-05 |
| `data/multi_coin_grid_v2_usd.sqlite` | Kraken USD (active) | 8.0 MB | 2026-01-21 → 2026-01-23 |
| `data/spot_grid_bitget.sqlite` | Bitget Spot (blocked) | 6.0 MB | 2026-01-06 → 2026-01-12 |
| `data/futures_grid_bitget.sqlite` | Bitget Futures (blocked) | 2.9 MB | 2026-02-01 → 2026-02-10 |

## Close type legend

| Code | Meaning |
|------|---------|
| 3 | TAKE_PROFIT |
| 5 | EARLY_STOP (no-fill, soft stop) |
| 7 | EXPIRED / no-fill timeout |
| 8 | STOP_LOSS |
| 11 | FAILED_TO_OPEN |
| 12 | SMART_SWITCH (rotation exit) |

---

## 1. Kraken EUR (historical, retired)

**Period**: 2025-11-20 → 2026-02-05 (77 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 2,209 | 34 | 1.5% | −€73.39 | €3.71 | €2,236.62 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 1,473 | +€11.83 | €1,767.85 |
| 7 (EXPIRED) | 704 | €0.00 | €0.00 |
| 3 (TAKE_PROFIT) | 11 | +€24.49 | €248.48 |
| 8 (STOP_LOSS) | 7 | −€109.72 | €220.29 |
| 11 (FAILED_TO_OPEN) | 11 | €0.00 | €0.00 |
| 12 (SMART_SWITCH) | 3 | €0.00 | €0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| STRK-EUR | 10 | 1 | 0 | 9 | +€24.40 | €0.96 | €216.94 |
| TAO-EUR | 45 | 2 | 2 | 41 | +€1.96 | €0.00 | €115.44 |
| XTZ-EUR | 56 | 1 | 1 | 54 | −€0.30 | €0.01 | €139.54 |
| ATOM-EUR | 303 | 0 | 3 | 300 | −€0.32 | €0.01 | €174.54 |
| POL-EUR | 236 | 1 | 3 | 232 | −€0.50 | €0.01 | €279.26 |
| JASMY-EUR | 2 | 0 | 1 | 1 | −€0.68 | €0.00 | €104.09 |
| UNI-EUR | 13 | 0 | 1 | 12 | −€1.11 | €0.97 | €215.79 |
| SOL-EUR | 122 | 1 | 4 | 117 | −€2.32 | €1.73 | €557.85 |
| SUI-EUR | 95 | 0 | 1 | 94 | −€0.01 | €0.00 | €34.96 |
| DOT-EUR | 89 | 0 | 1 | 88 | −€0.02 | €0.00 | €34.95 |
| ALGO-EUR | 4 | 0 | 1 | 3 | −€15.56 | €0.00 | €31.47 |
| RENDER-EUR | 103 | 0 | 2 | 101 | −€15.63 | €0.00 | €66.40 |
| ADA-EUR | 104 | 0 | 1 | 103 | −€15.63 | €0.00 | €31.47 |
| CC-EUR | 26 | 1 | 4 | 21 | −€15.70 | €0.01 | €170.98 |
| AAVE-EUR | 30 | 0 | 1 | 29 | −€15.93 | €0.00 | €31.47 |
| PEPE-EUR | 1 | 0 | 1 | 0 | −€16.02 | €0.00 | €31.47 |

### Per-pair (zero-fill only, no trades — top 10 by executor count)
| Pair | Executors | All zero-fill |
|------|-----------|---------------|
| SAND-EUR | 152 | 152 |
| FIL-EUR | 157 | 157 |
| MANA-EUR | 127 | 127 |
| SNX-EUR | 124 | 124 |
| BNB-EUR | 92 | 92 |
| ZRO-EUR* | — | — |
| DOGE-EUR | 42 | 42 |
| KAS-EUR | 31 | 31 |
| BCH-EUR | 33 | 33 |
| OPEN-EUR | 29 | 29 |

---

## 2. Kraken USD (active, limited data)

**Period**: 2026-01-21 → 2026-01-23 (2 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 212 | 1 | 0.5% | −$0.26 | $0.00 | $33.04 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 7 (EXPIRED) | 210 | $0.00 | $0.00 |
| 11 (FAILED_TO_OPEN) | 1 | $0.00 | $0.00 |
| 5 (EARLY_STOP) | 1 | −$0.26 | $33.04 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL |
|------|--------|------|--------|-----------|-----|
| ZRO-USD | 68 | 0 | 0 | 68 | $0.00 |
| XCN-USD | 48 | 0 | 0 | 48 | $0.00 |
| TAO-USD | 8 | 0 | 0 | 8 | $0.00 |
| SOL-USD | 14 | 0 | 0 | 14 | $0.00 |
| SAND-USD | 8 | 0 | 0 | 8 | $0.00 |
| MANA-USD | 7 | 0 | 0 | 7 | $0.00 |
| AVAX-USD | 7 | 0 | 0 | 7 | $0.00 |
| ADA-USD | 10 | 0 | 0 | 10 | $0.00 |
| AXS-USD | 42 | 0 | 1 | 41 | −$0.26 |

---

## 3. Bitget Spot (capital-blocked)

**Period**: 2026-01-06 → 2026-01-12 (6 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 400 | 6 | 1.5% | −$0.72 | $0.36 | $242.77 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 382 | −$0.31 | $132.83 |
| 12 (SMART_SWITCH) | 9 | −$0.41 | $109.93 |
| 11 (FAILED_TO_OPEN) | 9 | $0.00 | $0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| AVA-USDT | 99 | 0 | 1 | 98 | −$0.03 | $0.03 | $22.17 |
| ASTR-USDT | 4 | 0 | 1 | 3 | −$0.04 | $0.03 | $22.18 |
| CHZ-USDT | 8 | 0 | 1 | 7 | −$0.08 | $0.07 | $44.39 |
| SWCH-USDT | 57 | 0 | 3 | 54 | −$0.56 | $0.23 | $154.02 |

**Current state**: BLOCKED — $3.62 free capital < $30.00 minimum.
Stuck SONIC LIMIT SELL @ $0.046419 (1533 units) locking ~$71.

---

## 4. Bitget Futures (capital-depleted)

**Period**: 2026-02-01 → 2026-02-10 (9 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 932 | 23 | 2.5% | −$155.39 | −$0.09* | $472.90 |

*Negative fees = maker rebates on some trades.

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 3 (TAKE_PROFIT) | 737 | +$0.57 | $33.85 |
| 7 (EXPIRED) | 171 | $0.00 | $0.00 |
| 8 (STOP_LOSS) | 22 | −$155.96 | $439.05 |
| 11 (FAILED_TO_OPEN) | 2 | $0.00 | $0.00 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| SOL-USDT | 101 | 2 | 0 | 99 | +$9.31 | −$0.01 | $67.83 |
| SUI-USDT | 72 | 1 | 1 | 70 | +$0.09 | −$0.01 | $31.53 |
| AVAX-USDT | 113 | 0 | 1 | 112 | −$5.42 | $0.00 | $10.90 |
| LINK-USDT | 175 | 0 | 1 | 174 | −$9.56 | $0.00 | $19.26 |
| DOGE-USDT | 28 | 1 | 3 | 24 | −$10.57 | −$0.01 | $42.33 |
| XRP-USDT | 217 | 1 | 2 | 214 | −$11.96 | −$0.01 | $46.37 |
| OP-USDT | 1 | 0 | 1 | 0 | −$12.61 | −$0.01 | $24.86 |
| ARB-USDT | 116 | 0 | 3 | 113 | −$23.05 | −$0.01 | $45.90 |
| BTC-USDT | 59 | 0 | 3 | 56 | −$28.84 | −$0.01 | $57.73 |
| ETH-USDT | 50 | 0 | 3 | 47 | −$62.78 | −$0.03 | $126.18 |

### Filled trades detail (close type breakdown)
| Pair | Close type | Count | Wins | PnL | Volume |
|------|------------|-------|------|-----|--------|
| SOL-USDT | 8 (STOP_LOSS) | 1 | 1 | +$8.74 | $33.98 |
| SOL-USDT | 3 (TAKE_PROFIT) | 1 | 1 | +$0.57 | $33.85 |
| SUI-USDT | 8 (STOP_LOSS) | 2 | 1 | +$0.09 | $31.53 |
| AVAX-USDT | 8 | 1 | 0 | −$5.42 | $10.90 |
| LINK-USDT | 8 | 1 | 0 | −$9.56 | $19.26 |
| DOGE-USDT | 8 | 4 | 1 | −$10.57 | $42.33 |
| XRP-USDT | 8 | 3 | 1 | −$11.96 | $46.37 |
| OP-USDT | 8 | 1 | 0 | −$12.61 | $24.86 |
| ARB-USDT | 8 | 3 | 0 | −$23.05 | $45.90 |
| BTC-USDT | 8 | 3 | 0 | −$28.84 | $57.73 |
| ETH-USDT | 8 | 3 | 0 | −$62.78 | $126.18 |

**Current state**: BLOCKED — $9.09–$9.41 free capital < $15.00 minimum.
−$155 on $50 capital = −310% return in 9 days.

---

## 5. Combined summary

| Bot | Period | Executors | Filled | Fill % | PnL | Capital | Return |
|-----|--------|-----------|--------|--------|-----|---------|--------|
| Kraken EUR | Nov 25 – Feb 26 | 2,209 | 34 | 1.5% | −€73.39 | €300 | −24.5% |
| Kraken USD | Jan 21–23 | 212 | 1 | 0.5% | −$0.26 | ~$300 | −0.1% |
| Bitget Spot | Jan 6–12 | 400 | 6 | 1.5% | −$0.72 | ~$100 | −0.7% |
| Bitget Futures | Feb 1–10 | 932 | 23 | 2.5% | −$155.39 | ~$50 | −310.8% |
| **Combined** | | **3,753** | **64** | **1.7%** | **≈ −€229** | | |

**Key observations**:
- Not a single bot instance is profitable
- 98.3% of all executors across all bots never get a single fill
- Futures shows highest fill rate (2.5%) but worst outcome (96% stopped out)
- Only 1 of 3 active bots can currently attempt to trade (Kraken USD)

---

## 6. Error frequency from logs

### Kraken USD
**Log**: `logs/logs_multi_coin_grid_v2_usd_2026-03-05-16-20-24.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 277 |
| ERROR | 225 |

**Unique errors**:
- `MQTT is already stopped!` — MQTT connection management issue
- `Unexpected error while listening to user stream. Retrying after 5 seconds...` — WebSocket instability

**WebSocket-related messages**: 336 occurrences

### Bitget Spot
**Log**: `logs/logs_spot_grid_bitget_2026-03-05-16-42-05.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 1,664 |
| ERROR | 368 |

**Single error (all 368 occurrences)**:
```
❌ Cannot create grid: Insufficient capital: $3.62 < $30.00 minimum (3 grids × $10)
```

### Bitget Futures
**Log**: `logs/logs_futures_grid_bitget_2026-02-28-13-34-36.log`
**Session**: 2026-02-28 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 37 |
| ERROR | 37 |

**Unique errors (all insufficient capital variations)**:
```
❌ Cannot create grid: Insufficient capital: $9.27 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.29 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.34 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.41 < $15.00 minimum (3 grids × $5)
```

---

## 7. WHY-NO-TRADE summaries

### Kraken USD — 2026-03-08 (3 hourly reports)

**09:29 UTC** | 2,561 intents evaluated | 83.1% denied | 16.9% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 1,137 | 44.4% |
| RSI_OVERBOUGHT | 776 | 30.3% |
| STALE_PRICE | 157 | 6.1% |
| ATR_TOO_LOW | 35 | 1.4% |
| SPREAD_TOO_WIDE | 15 | 0.6% |
| RSI_OVERSOLD | 7 | 0.3% |

**10:30 UTC** | 1,827 intents | 57.0% denied | 43.0% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 666 | 36.5% |
| RSI_OVERBOUGHT | 265 | 14.5% |
| ATR_TOO_LOW | 93 | 5.1% |
| STALE_PRICE | 9 | 0.5% |
| RSI_OVERSOLD | 6 | 0.3% |
| SPREAD_TOO_WIDE | 2 | 0.1% |

**11:30 UTC** | 2,359 intents | 74.8% denied | 25.2% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 971 | 41.2% |
| RSI_OVERBOUGHT | 721 | 30.6% |
| STALE_PRICE | 70 | 3.0% |
| SPREAD_TOO_WIDE | 3 | 0.1% |

**Pattern**: NO_ORDERBOOK_DATA is consistently #1 (36–44%), RSI_OVERBOUGHT #2 (14–31%).

### Bitget Spot — 2026-03-05 to 2026-03-08

**20:42 (Mar 5)** | 99 intents | 70.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 40 | 40.4% |
| RSI_OVERBOUGHT | 10 | 10.1% |
| ATR_TOO_LOW | 10 | 10.1% |
| ACCEL_FALLING_KNIFE | 6 | 6.1% |
| VWAP_DEVIATION_TOO_HIGH | 4 | 4.0% |

**22:42 (Mar 5)** | 1,094 intents | 52.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 405 | 37.0% |
| RSI_OVERBOUGHT | 97 | 8.9% |
| ACCEL_FALLING_KNIFE | 60 | 5.5% |
| ATR_TOO_LOW | 12 | 1.1% |
| TREND_24H_OUT_OF_RANGE | 3 | 0.3% |

**10:47 (Mar 8)** | ~2,000 intents | ~70% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | ~40% | — |
| RSI_OVERBOUGHT | ~18% | — |
| ACCEL_FALLING_KNIFE | 83 | 4.0% |
| TREND_24H_OUT_OF_RANGE | 61 | 3.0% |
| SPREAD_TOO_WIDE | 37 | 1.8% |

**11:48 (Mar 8)** | 1,883 intents | 72.1% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 746 | 39.6% |
| RSI_OVERBOUGHT | 342 | 18.2% |
| ACCEL_FALLING_KNIFE | 109 | 5.8% |
| WICK_RATIO_LOW | 65 | 3.5% |
| TREND_24H_OUT_OF_RANGE | 54 | 2.9% |
| STALE_PRICE | 35 | 1.9% |
| SPREAD_TOO_WIDE | 6 | 0.3% |

**After 12:48 (Mar 8)**: 0 intents evaluated — Bitget Spot stopped evaluating
(likely capital-blocked, no coins being monitored).

---

## 8. Rotation timeout events

### Kraken USD (current session)
| Coin | Timeouts |
|------|----------|
| SUI-USD | 2 |

### Bitget Spot (current session)
| Coin | Timeouts |
|------|----------|
| SONIC-USDT | 19 |
| HYPE-USDT | 2 |

**SONIC-USDT rotation loop**: Rotates every ~3.1 minutes without progress.
Sample (all from March 8):
```
12:08 → 12:12 → 12:15 → 12:18 → 12:21 → 12:24 → 12:28 → 12:31
→ 12:34 → 12:37 → 12:41 → 12:44 → 12:47 → 12:50 → 12:57 → 13:00
→ 13:03 → 13:07 → ...
```
19 consecutive "monitoring timeout" events for the same coin = rotation
logic doesn't detect that it keeps selecting the same stuck coin.

---

## 9. Critical observations

1. **Fill rate crisis**: 98.3% of executors never fill. This is the #1 problem.
2. **NO_ORDERBOOK_DATA**: #1 rejection reason (35–44%) across all bots. Likely a data pipeline issue, not a strategy issue.
3. **Capital adequacy**: 2 of 3 active bots cannot trade due to insufficient capital.
4. **Futures catastrophe**: −$155 on $50 capital. 96% of filled trades hit stop-loss. Grid + leverage = amplified losses.
5. **Rotation loops**: SONIC-USDT rotates 19 times without progress. The bot doesn't learn.
6. **Kraken WebSocket**: 336 WebSocket-related events in a 3-day session.
7. **Only SOL-USDT** is consistently profitable across all bots (+$9.31 futures, positive on spot).
