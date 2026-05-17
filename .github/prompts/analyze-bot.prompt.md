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
7. Calculate trade PnL where possible — use `datetime(timestamp, 'unixepoch')` for Executors (timestamp is in **seconds**, not ms). Filter closed rows with `status = 4`. Include EARLY_STOP (close_type=5) in totals — they can be profitable exits.
8. Check cooldown database for active cooldowns

### 🔍 Funnel gap check (always do this)
9. Compare WHY-NO-TRADE "Approved" count vs actual executor creates in the same window.
   - If approved >> executor starts (e.g. 500 approved, 1 executor started), there is a post-filter blocker.
   - Search logs for: `insufficient capital`, `budget_precheck_blocked`, `insufficient balance`, `capital reserve`, `effective=`, `need=`
   - Also check for: `SLOT_FULL`, `TWO_FAILED_CYCLES`, `ALREADY_TRADING` blocking at admission stage

### 🔍 Capital / budget health check (always do this)
10. Search logs for any of these patterns in the analysis window:
    - `insufficient capital` / `budget_precheck`
    - `stale.*reserv` / `orphan reserv`
    - `effective=` lines that show available capital near zero
    - `INSUFFICIENT_BALANCE` as early_stop_reason in SQLite
    Report the count and first/last occurrence. If found, this is likely the root cause of low trade counts.

## Output

Provide a structured report with:
- Session overview (duration, trades, errors)
- **Funnel gap**: approved-by-filters vs executors-actually-started (flag if ratio > 10:1)
- Key findings (severity ordered: 🔴 🟡 🟢)
- Trade summary (per coin)
- Root cause for any problems found
- Actionable recommendations
