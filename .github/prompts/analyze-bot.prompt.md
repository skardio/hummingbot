---
description: "Analyze last N hours of a trading bot: errors, trades, stuck orders, risk pauses. Usage: /analyze-bot [bot] [hours]"
agent: "log-analyzer"
argument-hint: "Which bot? (kraken-usd, kraken-eur, bitget) and how many hours? (e.g. kraken-usd 12)"
---

Analyze the trading bot session. The user may specify which bot and how many hours to look back.

## Steps

1. Read `.github/analysis-context.md` for log paths and database locations
2. Find the most recent log files for the requested bot
3. Analyze the last N hours (default: 12 hours if not specified)
4. Count: fills, errors, executor creates, risk pauses, rejections
5. Identify: stuck orders, WebSocket drops, stale data events
6. Build a timeline of key events
7. Calculate trade PnL where possible
8. Check cooldown database for active cooldowns

## Output

Provide a structured report with:
- Session overview (duration, trades, errors)
- Key findings (severity ordered: 🔴 🟡 🟢)
- Trade summary (per coin)
- Root cause for any problems found
- Actionable recommendations
