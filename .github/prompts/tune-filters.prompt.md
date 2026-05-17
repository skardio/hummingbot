---
description: "Analyze which filters block trades and separate tuning from blacklist/code/observability findings. Usage: /tune-filters [bot]"
agent: "log-analyzer"
argument-hint: "Which bot? (kraken-usd, kraken-eur, bitget)"
---

Analyze the filter rejection patterns for the specified bot and suggest only statistically justified changes.
Do not default to loosening thresholds: first decide whether the data points to a threshold issue, a bad symbol, a code/exit-limbo issue, or an observability gap.

## Analysis Steps

1. Read `.github/analysis-context.md` for paths
2. Find the most recent WHY-NO-TRADE report: `ls -lt logs/*report*.log | head -3`
3. Parse the rejection breakdown by reason code and by stage
4. Check JSONL event logs for `gate_denied` and `gate_passed` events: `grep "gate_denied" logs/events_usd/events_*.jsonl | tail -100`
5. Cross-reference with current config values in the YAML file
6. Count rejected vs approved entries in event logs and main logs
7. For each high-volume reason, check per-symbol concentration:
   - If one symbol causes >25% of a reason, prefer blacklist/universe-gate action over threshold loosening
   - If several symbols are persistent rejects across multiple filters, flag them for universe-quality review
8. Separate entry filtering from exit/control-loop issues:
   - Scan logs for `FEE_AWARE_EXIT_BLOCKED`, timeout loops, blocked slots, repeated stop attempts
   - Report these as code/exit policy issues, not entry threshold tuning
9. Check whether events include top-level `regime`; if missing, mark an observability gap instead of inferring too strongly

## Output

### 1. Filter Rejection Ranking

| # | Reason | Count | % of Total | Stage | Current Threshold |
|---|--------|-------|-----------|-------|-------------------|

Include `gate_passed`, total denied, and pass rate, but do not tune toward an arbitrary pass-rate target.

### 2. Findings Classification

For each material finding, classify it as one of:
- `threshold_change`: threshold looks too tight or too loose
- `coin_blacklist`: one symbol is structurally bad for this exchange/pair
- `code_issue`: loop, state, sizing, or exit policy behaves incorrectly
- `observability_gap`: missing data prevents a reliable decision
- `no_change`: filter is doing its job

For each filter that blocks >15% of entries, assess:
- Is this threshold too tight, or is it correctly protecting?
- Are rejects concentrated in one symbol or broad across the universe?
- Are rejected symbols later profitable or mostly avoided bad entries?
- Suggest specific value changes only if the evidence supports it.

### 3. Regime Breakdown

Show if rejections cluster in specific regimes (BULL/CHOP/BEAR).
If regime is missing from JSONL, say so explicitly and recommend adding it to event metadata.

### 4. Proposed Changes

If tuning is warranted, provide exact parameter changes for `@config-tuner`:
```
rsi_buy_max: 72 → 74  (reason: 30% of rejects, most were borderline)
max_entry_spread_pct: 0.5 → 0.6  (reason: Kraken spreads avg 0.4%)
```

If a blacklist/universe action is warranted, provide exact YAML:
```
coin_blacklist:
  - PLAY-USD  # structural spread outlier
```

If a code or observability issue is found, provide the owning area and a one-line implementation recommendation.
