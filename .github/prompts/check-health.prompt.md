---
description: "Quick health check: are all bots running, any errors in last hour, any stuck orders or risk pauses active right now?"
agent: "log-analyzer"
argument-hint: "Optional: specific bot (kraken-usd, kraken-eur, bitget) or leave empty for all"
---

Perform a quick health check on the trading bot(s). Focus on the last 1 hour only.

## Checks (in order)

1. **Process alive?** — Check if log file was written to recently (`ls -lt logs/`)
2. **Errors?** — Count ERROR/WARNING in last hour of each log
3. **Trading?** — Any fills in the last hour?
4. **Stuck orders?** — Grep for "still pending", "CLOSING", "zombie", "stale"
5. **Risk pauses?** — Check for kill switch, daily loss limit, win rate pause
6. **Cooldowns active?** — Query cooldown databases
7. **WebSocket healthy?** — Any disconnect/reconnect in last hour?

## Output

Keep it concise — traffic light format:

```
🟢 Kraken USD: Healthy — 3 fills last hour, no errors
🟡 Kraken EUR: Warning — 0 fills, risk pause active since 14:32
🔴 Bitget: Problem — WebSocket disconnected 23 min ago, no recovery
```

Then expand on any 🟡 or 🔴 findings only.
