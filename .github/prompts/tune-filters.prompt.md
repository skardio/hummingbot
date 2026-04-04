---
description: "Analyze which entry filters block the most trades and suggest tuning adjustments. Usage: /tune-filters [bot]"
agent: "log-analyzer"
argument-hint: "Which bot? (kraken-usd, kraken-eur, bitget)"
---

Analyze the entry filter rejection patterns for the specified bot and suggest config tuning.

## Analysis Steps

1. Read `.github/analysis-context.md` for paths
2. Find the most recent WHY-NO-TRADE report: `ls -lt logs/*report*.log | head -3`
3. Parse the rejection breakdown by reason code
4. Check JSONL event logs for `gate_denied` events: `grep "gate_denied" logs/events_usd/events_*.jsonl | tail -100`
5. Cross-reference with current config values in the YAML file
6. Count rejected vs approved entries in main logs

## Output

### 1. Filter Rejection Ranking

| # | Reason | Count | % of Total | Current Threshold |
|---|--------|-------|-----------|-------------------|

### 2. Tuning Recommendations

For each filter that blocks >15% of entries, assess:
- Is this threshold too tight? (blocking good entries)
- Is it correctly protecting? (blocking bad entries)
- Suggest specific value changes if appropriate

### 3. Regime Breakdown

Show if rejections cluster in specific regimes (BULL/CHOP/BEAR).

### 4. Proposed Changes

If tuning is warranted, provide exact parameter changes for `@config-tuner`:
```
rsi_buy_max: 72 → 74  (reason: 30% of rejects, most were borderline)
max_entry_spread_pct: 0.5 → 0.6  (reason: Kraken spreads avg 0.4%)
```
