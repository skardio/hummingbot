# Codex Prompt — Momentum Signal Analysis

Kopieer alles hieronder (vanaf de horizontale lijn) naar Codex.

---

## Task

You are a quantitative analyst. Analyse a live crypto momentum signal database and produce a structured performance report. The database is SQLite. All SQL must be SQLite-compatible.

---

## Database

**File**: `data/momentum_signals.sqlite`
**Mode**: WAL — run this first before any query:

```python
import sqlite3
conn = sqlite3.connect('data/momentum_signals.sqlite')
conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
```

---

## Schema

```sql
CREATE TABLE signals (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id               TEXT    NOT NULL,
    timestamp             REAL    NOT NULL,      -- Unix epoch (seconds)
    exchange              TEXT    NOT NULL,       -- 'bitvavo' | 'kraken' | 'okx'
    trading_pair          TEXT    NOT NULL,
    price                 REAL    NOT NULL,
    spread_pct            REAL,                  -- bid-ask spread as % of midprice
    price_change_1m_pct   REAL,
    price_change_3m_pct   REAL,
    price_change_5m_pct   REAL,
    price_change_15m_pct  REAL,                  -- key filter: TOO_LATE if >= 6.0%
    volume_ratio          REAL,                  -- current / average volume
    score                 REAL    NOT NULL,       -- composite score 0.0–1.0
    accepted              INTEGER NOT NULL,       -- 1 = passed all filters
    signal_label          TEXT,                  -- 'BUY_NOW'|'WATCH'|'TOO_LATE'|NULL
    entry_min             REAL,
    entry_max             REAL,
    invalidation_price    REAL,                  -- stop-loss level (absolute)
    take_profit_1         REAL,                  -- TP1 level (~+1.2% above entry)
    take_profit_2         REAL,                  -- TP2 level (~+2.5% above entry)
    slippage_100eur       REAL,
    preselection_score    REAL,
    preselection_bucket   TEXT,
    preselection_breakdown TEXT                  -- JSON
);

CREATE TABLE signal_outcomes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id            INTEGER NOT NULL,        -- FK → signals.id
    entry_price          REAL    NOT NULL,         -- entry_max (worst-case entry)
    max_price_30m        REAL,
    min_price_30m        REAL,
    hit_tp1              INTEGER DEFAULT 0,        -- 1 = TP1 reached within 30min (order-agnostic)
    hit_tp2              INTEGER DEFAULT 0,
    hit_stop             INTEGER DEFAULT 0,
    best_exit_pct        REAL,   -- (max_price_30m - entry_price) / entry_price * 100
    worst_drawdown_pct   REAL,   -- (min_price_30m - entry_price) / entry_price * 100
    evaluated_at         REAL,   -- NULL = not yet evaluated
    -- ORDER matters (these are NULL if service not yet restarted after v2 upgrade):
    first_hit            TEXT,   -- 'TP1'|'TP2'|'STOP'|'TIMEOUT'|NULL
    tp1_hit_at_seconds   REAL,   -- seconds after entry when TP1 first hit
    tp2_hit_at_seconds   REAL,
    stop_hit_at_seconds  REAL
);
```

---

## System constants (treat as fixed)

| Parameter | Value |
|---|---|
| TP1 target | +1.2% above entry |
| TP2 target | +2.5% above entry |
| Stop level | −1.5% below entry |
| Evaluation window | 30 minutes |
| Round-trip fee | 0.50% |
| TOO_LATE threshold | Δ15m ≥ 6.0% |
| Min score for BUY_NOW | ≥ 0.80 |

**Breakeven win rate** (TP-first needed to cover fees):
- Without fees: 1.5 / (1.2 + 1.5) ≈ 56%
- With 0.50% round-trip fee: 2.0 / (0.7 + 2.0) ≈ **74%**

> If `TP1-first rate < 74%`, the strategy has negative expected value at current fees.

---

## Current data snapshot (2026-06-07)

| | Count |
|---|---|
| signals with label | 197 |
| BUY_NOW | 114 (bitvavo: 73, kraken: 37, okx: 4) |
| WATCH | 83 |
| signal_outcomes with evaluated_at | 140 |
| outcomes with first_hit populated | 61 |

> `first_hit` is NULL for ~79 outcomes — the service ran old code before a restart. For those rows, fall back to `hit_tp1` / `hit_stop` as a proxy (order-agnostic approximation).

**Data is early-stage** (service started 2026-06-04). The 2-week target is ~2026-06-19. Flag any segment with n < 15 as "insufficient data".

---

## Analysis tasks

Run **all** of the following. For each section: show the SQL, show the result table, and add 2–3 sentences of interpretation.

### A. Overall BUY_NOW performance (first_hit)

Distribution of `first_hit` outcomes. Calculate net EV per outcome:
- TP1 → +0.70% net (1.2 − 0.50 fee)
- TP2 → +2.00% net (2.5 − 0.50 fee)
- STOP → −2.00% net (−1.5 − 0.50 fee)
- TIMEOUT → `best_exit_pct − 0.50`

Report: n, pct, avg net EV. Compare TP-first rate to 74% breakeven.

For rows where `first_hit IS NULL`, use proxy: `hit_tp1=1 AND hit_stop=0` → TP, `hit_stop=1 AND hit_tp1=0` → STOP, both=1 → ambiguous (exclude from net EV).

### B. Score calibration

Bucket `score` into: `<0.80`, `0.80–0.85`, `0.85–0.90`, `>=0.90`.
Report per bucket: n, TP-first %, stop-first %, avg `best_exit_pct`.
Does higher score predict better outcome?

### C. WATCH signal value

1. How often does a WATCH signal get followed by a BUY_NOW on the same exchange+pair within 30 minutes?
2. What is the outcome distribution for WATCH signals (using `first_hit` or proxy)?
3. Is WATCH entry quality comparable to BUY_NOW?

### D. Event deduplication

Define one "event" = same exchange + trading_pair, signals within the same 30-minute bucket (`CAST(timestamp/1800 AS INTEGER)`). Take only the first signal per event.

Compare: signal-level TP-first rate vs event-level TP-first rate. Are repeated signals on the same coin inflating the win rate?

### E. TOO_LATE validation

What would have happened if we had entered on TOO_LATE signals?
- Report TP-first %, stop-first %, avg `best_exit_pct`
- Interpret: is the filter too strict (TOO_LATE signals would have been profitable) or working correctly?

### F. Δ15m bucket analysis

Bucket `price_change_15m_pct` into: `<2.5%`, `2.5–4%`, `4–5.5%`, `5.5–6%`, `>=6% (TOO_LATE zone)`.
For each bucket: n, TP-first %, stop-first %, avg `best_exit_pct`.
Is the 6.0% TOO_LATE threshold at the right place?

### G. Volume ratio analysis

Bucket `volume_ratio` into: `<2x`, `2–3x`, `3–5x`, `>=5x`.
Does extreme volume (>=5x, blow-off top risk) correlate with worse outcomes?

### H. Spread analysis

Bucket `spread_pct` into: `<0.10%`, `0.10–0.20%`, `0.20–0.30%`, `>=0.30%`.
Does higher spread correlate with worse outcomes? Suggest if `max_spread_pct` should be tightened.

### I. Exchange performance

Per exchange: n, TP-first %, stop-first %, avg `best_exit_pct`.
Minimum 20 outcomes per exchange for conclusions; else mark as indicative.

### J. Daily regime

Per day (`date(timestamp, 'unixepoch')`): n, TP-first %, avg `best_exit_pct`.
Does one day dominate the results? If yes, flag that conclusions are not yet generalisable.

### K. Worst signals (filter tuning)

List the 20 worst BUY_NOW signals by `worst_drawdown_pct` where `first_hit = 'STOP'` (or `hit_stop=1`).
Columns: exchange, trading_pair, score, price_change_15m_pct, volume_ratio, spread_pct, first_hit, stop_hit_at_seconds, worst_drawdown_pct.
Identify patterns: same exchange? high spread? high Δ15m?

---

## Output format

For each section (A–K):
1. The SQL query used
2. Result as a markdown table
3. 2–3 sentence interpretation
4. Flag any segment with n < 15 as "⚠️ insufficient data"

At the end, write a **summary** (max 10 bullet points):
- Overall EV positive or negative?
- Score calibration working?
- Is WATCH a useful early signal?
- Any filter obviously mis-set?
- What is the biggest concern at this stage?
- What to check again after 2 weeks of data?
