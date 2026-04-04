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

## Output

Provide a full performance report with:
- Period summary (total PnL, volume, fees, win rate)
- Per-coin breakdown table
- Top 3 / bottom 3 coins
- Fee impact analysis
- Hold time analysis
- Actionable insights
