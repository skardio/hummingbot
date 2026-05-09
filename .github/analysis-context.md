# Analysis Context — Trading Bot Workspace

This document provides AI assistants with all paths, locations, and commands needed to analyze the multi-coin grid trading bots.

> **CRITICAL**: NEVER kill, stop, or restart running bot processes. Only the operator may do this manually.

---

## Bot Overview

| Bot | Connector | Quote | Config | Database | Status |
|-----|-----------|-------|--------|----------|--------|
| Kraken EUR | `kraken` | EUR | `multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml` | `data/multi_coin_grid_v2.sqlite` | Active |
| Kraken USD | `kraken` | USD | `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` | `data/multi_coin_grid_v2_usd.sqlite` | Active |
| Bitget USDT | `bitget` | USDT | `multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml` | `data/spot_grid_bitget.sqlite` | Active |
| Bitget Futures | `bitget` | USDT | `multi_coin_grid_pro/spot_bitget/config/futures_grid_bitget.yaml` | `data/futures_grid_bitget.sqlite` | Active |

---

## How to Find Current Logs

### Pattern: Log files are timestamped at bot startup

```bash
# Find MOST RECENT log for each bot type
ls -lt logs/logs_multi_coin_grid_v2_20*.log | head -1        # Kraken EUR
ls -lt logs/logs_multi_coin_grid_v2_usd_20*.log | head -1    # Kraken USD
ls -lt logs/logs_spot_grid_bitget_20*.log | head -1          # Bitget Spot
ls -lt logs/logs_futures_grid_bitget_20*.log | head -1       # Bitget Futures

# Rotated logs (newest = .log, oldest = .log.10)
# .log   = current/most recent (~2MB initially)
# .log.1 = 1 rotation ago (~20MB each)
# .log.2, .log.3, etc = progressively older
# .log.200 = oldest retained

# Example: Find log with specific timestamp range
ls -la logs/logs_multi_coin_grid_v2_usd_2026-02-24*.log*
```

### Daily Reports (WHY-NO-TRADE summaries)

```bash
# Kraken EUR reports (format: kraken_multi_coin_grid_eur_report_YYYYMMDD.log)
ls -lt logs/kraken_multi_coin_grid_eur_report_*.log | head -5

# Kraken USD reports
ls -lt logs/kraken_multi_coin_grid_usd_report_*.log | head -5

# Bitget USDT reports
ls -lt logs/bitget_multi_coin_grid_report_*.log | head -5

# Example output - shows hourly rejection breakdown:
# Top Rejection Reasons:
#   1. NO_ORDERBOOK_DATA: 967 (42.1%) [SMART_ENTRY]
#   2. RSI_OVERSOLD: 234 (10.2%) [SMART_ENTRY]
#   3. ACCEL_FALLING_KNIFE: 97 (4.2%) [SMART_ENTRY]
```

### Event Logs (JSONL structured events)

```bash
# Kraken USD events
ls -lt logs/events_usd/events_*.jsonl | head -5

# Bitget events
ls -lt logs/events/events_*.jsonl | head -5

# Query specific event types
grep "gate_denied" logs/events_usd/events_*.jsonl | tail -20
grep "gate_passed" logs/events/events_*.jsonl | tail -20

# Common reason codes in events:
# - NO_ORDERBOOK_DATA     # Exchange not sending orderbook
# - STALE_PRICE           # Price data older than max_price_age_ms
# - RSI_OVERBOUGHT        # RSI > rsi_buy_max
# - RSI_OVERSOLD          # RSI < rsi_extreme_low
# - ACCEL_FALLING_KNIFE   # Rapid downward acceleration
# - VWAP_DEVIATION_TOO_HIGH
# - SPREAD_TOO_WIDE       # Bid-ask spread > max_spread_pct
```

---

## Databases

### Main Trading Databases (SQLite)

| Bot | Database Path |
|-----|---------------|
| Kraken EUR | `data/multi_coin_grid_v2.sqlite` |
| Kraken USD | `data/multi_coin_grid_v2_usd.sqlite` |
| Bitget Spot | `data/spot_grid_bitget.sqlite` |
| Bitget Futures | `data/futures_grid_bitget.sqlite` |

### Database Schema (Important Tables)

**TradeFill** - Actual executed trades:
```sql
-- Note: amount and price are stored as BIGINT (multiply by 1e-9 for actual values)
-- trade_fee is JSON with {currency, amount} structure
SELECT datetime(timestamp/1000, 'unixepoch', 'localtime') as time,
       trade_type, base_asset,
       amount/1000000000.0 as qty,
       price/100000000.0 as px,
       (amount/1000000000.0)*(price/100000000.0) as value,
       order_id
FROM TradeFill WHERE base_asset='BTC' ORDER BY timestamp DESC LIMIT 20;
```

**Order** - All orders placed:
```sql
SELECT datetime(creation_timestamp/1000, 'unixepoch', 'localtime') as time,
       id, symbol, order_type, last_status, exchange_order_id,
       amount/1000000000.0 as qty, price/100000000.0 as px
FROM "Order" WHERE symbol LIKE '%BTC%' ORDER BY creation_timestamp DESC LIMIT 20;
```

**Executors** - Grid executor state (note: may lag behind actual trades):
```sql
SELECT id, datetime(timestamp, 'unixepoch', 'localtime') as start_time,
       status, is_active, net_pnl_quote, filled_amount_quote,
       json_extract(config, '$.trading_pair') as pair
FROM Executors ORDER BY timestamp DESC LIMIT 10;
```

### Cooldown Databases

| Bot | Database Path |
|-----|---------------|
| Default (EUR) | `data/cooldowns.db` |
| Kraken EUR | `data/cooldowns_eur.db` |
| Kraken USD | `data/cooldowns_usd.db` |

```sql
-- Check active cooldowns
sqlite3 data/cooldowns_usd.db "SELECT * FROM symbol_cooldowns"
```

---

## Common Analysis Queries

### Log Analysis

```bash
# Count fills/trades
grep -iE "FILL|filled|OrderFilledEvent" logs/logs_multi_coin_grid_v2_usd_*.log* | wc -l

# Check errors
grep -iE "ERROR|Exception|Failed" logs/logs_multi_coin_grid_v2_usd_*.log | tail -50

# SmartEntry rejections (why no buy)
grep -E "REJECTED|NO BUY|blocked" logs/logs_*.log | tail -20

# Budget blocks (insufficient capital)
grep -E "US-004 BUDGET BLOCKED|Insufficient free capital" logs/logs_*.log | tail -20

# Executor state issues
grep -E "PHASE 3.5|Close order pending|external.*close" logs/logs_*.log | tail -20

# Check active positions
grep -E "slots used" logs/logs_*.log | tail -10

# Network/connectivity issues
grep -E "disconnect|reconnect|timeout|Insufficient balance" logs/logs_*.log | tail -20
```

### Database Summary Queries

```bash
# Trades breakdown by coin (last session)
sqlite3 data/multi_coin_grid_v2_usd.sqlite \
  "SELECT base_asset, trade_type, COUNT(*) as cnt,
          SUM(amount/1000000000.0) as total_qty
   FROM TradeFill GROUP BY base_asset, trade_type ORDER BY base_asset"

# Net position per coin
sqlite3 data/multi_coin_grid_v2_usd.sqlite \
  "SELECT base_asset,
          SUM(CASE WHEN trade_type='BUY' THEN amount ELSE -amount END)/1000000000.0 as net_qty
   FROM TradeFill GROUP BY base_asset HAVING net_qty != 0"

# Recent orders with status
sqlite3 data/multi_coin_grid_v2_usd.sqlite \
  "SELECT datetime(creation_timestamp/1000, 'unixepoch', 'localtime') as time,
          symbol, order_type, last_status
   FROM 'Order' ORDER BY creation_timestamp DESC LIMIT 15"
```

---

## Key Code Files

| Component | Path |
|-----------|------|
| **Grid Executor** | `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py` |
| Main Controller | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` |
| Config Model | `multi_coin_grid_pro/controllers/multi_coin_grid_config.py` |
| Budget Allocator | `multi_coin_grid_pro/utils/budget_allocator.py` |
| Trend Calculator | `multi_coin_grid_pro/utils/trend_calculator.py` |
| SmartEntry Filter | `multi_coin_grid_pro/filters/smart_entry_filter.py` |
| Staleness Guard | `multi_coin_grid_pro/utils/staleness_guard.py` |
| Pair Health Monitor | `multi_coin_grid_pro/utils/pair_health_monitor.py` |

### Grid Executor Critical Methods

| Method | Purpose |
|--------|---------|
| `control_close_process()` | Manages executor close state machine |
| `adjust_close_order_stuck()` | Escalates stuck close orders |
| `start_forced_close()` | Two-phase unwind (graceful → aggressive) |
| `control_shutdown_process()` | Final cleanup before termination |

---

## Common Issues & Debugging

### "Bot bought but didn't sell" (Stuck Position)

**Symptom:** Logs show "PHASE 3.5: Close order pending" repeating indefinitely

**Root causes:**
1. **Order filled but not detected** - Order removed from `in_flight_orders` after fill
2. **External close detection** - Using `get_available_balance()` instead of `get_balance()`
3. **Race condition** - Balance check during pending order

**Debug steps:**
```bash
# Find the stuck executor
grep "PHASE 3.5.*Close order pending" logs/logs_*.log | tail -5

# Check if order is actually filled in database
sqlite3 data/multi_coin_grid_v2_usd.sqlite \
  "SELECT last_status FROM 'Order' WHERE id='<order_id>'"

# Check current balance on exchange vs database
grep "total_balance:" logs/logs_*.log | tail -5
```

### "Insufficient balance" / "Reserved too high"

**Symptom:** `US-004 BUDGET BLOCKED` with `reserved > balance`

**Root cause:** An executor is reserving capital but stuck

**Debug:**
```bash
# Find what's reserving capital
grep "reserved=" logs/logs_*.log | tail -5

# Check active executors
grep "slots used" logs/logs_*.log | tail -5
```

### "No trades happening" (All filters passing but no buys)

**Check reasons:**
```bash
# RSI overbought
grep "overbought" logs/logs_*.log | tail -10

# Spread too wide
grep "Spread too wide" logs/logs_*.log | tail -10

# Trend filter
grep "consensus=.*passes=False" logs/logs_*.log | tail -10

# Stale data
grep "STALE" logs/logs_*.log | tail -10
```

---

## Config Locations

### Main Configs

| Bot | Config Path |
|-----|-------------|
| Kraken EUR | `multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml` |
| Kraken USD | `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` |
| Bitget Spot | `multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml` |
| Bitget Futures | `multi_coin_grid_pro/spot_bitget/config/futures_grid_bitget.yaml` |

### Key Config Parameters

```yaml
# Budget & Position Sizing
capital_per_coin: 300          # USD/EUR per coin
max_active_grids: 4            # Max concurrent positions
min_order_size_quote: 15       # Minimum order size

# SmartEntry Filters
rsi_buy_max: 68                # Don't buy above this RSI
rsi_extreme_low: 18            # Oversold threshold
max_spread_pct: 0.3            # Max bid-ask spread

# Timeouts
no_fill_timeout_seconds: 120
no_progress_timeout_seconds: 5400  # 90 minutes

# Dynamic Pair Discovery
use_dynamic_pair_discovery: true
trading_pairs_blacklist: [...]
```

---

## Test Commands

```bash
# Run all multi_coin_grid_pro tests
pytest multi_coin_grid_pro/tests/ -v

# Run specific test
pytest multi_coin_grid_pro/tests/utils/test_budget_allocator.py -v

# Syntax check grid_executor
python -m py_compile hummingbot/strategy_v2/executors/grid_executor/grid_executor.py
```

---

## Analysis Request Examples

When user asks to analyze a bot, use these patterns:

### "Analyze last run of Kraken EUR"
1. Find latest log: `ls -lt logs/logs_multi_coin_grid_v2_*.log | head -1`
2. Check errors: `grep -iE "ERROR|Exception" <logfile> | tail -30`
3. Count fills: `grep -i "fill" <logfile> | wc -l`
4. Check report: `ls -lt logs/kraken_multi_coin_grid_eur_report_*.log | head -1`

### "Analyze last run of Bitget"
1. Find latest log: `ls -lt logs/logs_spot_grid_bitget_*.log | head -1`
2. Check errors: `grep -iE "ERROR|Exception" <logfile> | tail -30`
3. Count fills: `grep -i "fill" <logfile> | wc -l`
4. Check report: `ls -lt logs/bitget_multi_coin_grid_report_*.log | head -1`

### "Check PnL for Kraken USD"
1. Find report: `ls -lt logs/kraken_multi_coin_grid_usd_report_*.log | head -1`
2. Read report: `cat <reportfile>`
3. Query database: `sqlite3 data/multi_coin_grid_v2_usd.sqlite "SELECT ..."`

### "Why is bot not trading?"
1. Check logs for blocks: `grep -iE "blocked|denied|rejected|cooldown" <logfile> | tail -30`
2. Check cooldowns: `sqlite3 data/cooldowns.db "SELECT * FROM cooldowns WHERE expires_at > datetime('now')"`
3. Check kill switch: `grep -i "kill.?switch" <logfile> | tail -10`
4. Check connectivity: `grep -E "disconnect|timeout" <logfile> | tail -10`

---

## Workspace Structure

```
/home/mo/repos/hummingbot/
├── .github/
│   ├── copilot-instructions.md    # Main AI instructions
│   ├── analysis-context.md        # This file
│   └── agents/
│       ├── planner.agent.md
│       ├── implementer.agent.md
│       └── reviewer.agent.md
├── multi_coin_grid_pro/           # Strategy code
│   ├── controllers/
│   ├── utils/
│   ├── filters/
│   ├── core/
│   ├── persistence/
│   ├── observability/
│   ├── config/                    # Kraken configs
│   ├── spot_bitget/config/        # Bitget configs
│   ├── data/                      # Monitoring DB
│   └── tests/
├── logs/                          # All log files
│   └── events/                    # JSONL event logs
├── data/                          # SQLite databases
└── hummingbot/                    # Hummingbot core
```

---

*Last updated: 2026-02-19*
