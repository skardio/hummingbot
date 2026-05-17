---
description: "Generate a full performance report with PnL, win rates, fees, and per-coin breakdown from the trading database."
agent: "performance"
argument-hint: "Which bot and period? (e.g. kraken-usd 7days, bitget 30days)"
---

Generate a comprehensive performance report from the trading database.

## Steps

1. Read `.github/analysis-context.md` for database paths
2. Identify the correct database for the requested bot
3. Run the performance queries for the requested time period (default: 7 days)
4. Calculate: net PnL, gross PnL, fees, win rate, profit factor
5. Break down per coin
6. Identify best/worst performers
7. Calculate average hold times
8. Run the close-type breakdown query to see STOP_LOSS / EARLY_STOP / TIMEOUT distribution

## Critical query rules (avoid past analysis mistakes)

- `Executors.timestamp` is **already in Unix seconds** (FLOAT) — use `datetime(timestamp, 'unixepoch')`, never `timestamp/1000`
- Filter closed executors with `status = 4` (INTEGER), not `status = 'COMPLETED'` (string) and not `close_type = 'COMPLETED'`
- `close_type` is an INTEGER — always use the CASE mapping from the performance agent, never compare to strings
- **Include EARLY_STOP (close_type=5)** in all PnL totals — these can be profitable exits (regime switches, manual close)
- `entry_trend_pct` in custom_info is the **multi-indicator consensus signal at entry**, NOT the 24h price trend — do not compare it to 24h candle data or describe it as "24h trend"
- When a coin shows 0 in one query but has fills in TradeFill — cross-check: executor may have closed as EARLY_STOP and been missed

## Output

Provide a full performance report with:
- Period summary (total PnL, volume, fees, win rate)
- Per-coin breakdown table
- Close-type distribution (COMPLETED / EARLY_STOP / STOP_LOSS / TIMEOUT counts + PnL per type)
- Top 3 / bottom 3 coins
- Fee impact analysis
- Hold time analysis
- Actionable insights
