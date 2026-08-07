# Momentum Signal Analysis Report

Snapshot date: 2026-06-07
Database: `data/momentum_signals.sqlite`
WAL checkpoint executed first: `[(0, 265, 265)]`

Method notes: `TP_PROXY` means old-code `first_hit IS NULL` rows where `hit_tp1=1 AND hit_stop=0`; `STOP_PROXY` means `hit_stop=1 AND hit_tp1=0`; `AMBIGUOUS` rows hit both and are excluded from net EV/rate denominators. Proxy TP uses conservative TP1 net EV (+0.70%). Sections A, D, I, J, and K focus on actionable BUY_NOW. Sections B, G, and H use evaluated BUY_NOW+WATCH so calibration/filter buckets include lower-score WATCH data. Sections E and the >=6% part of F use scan-sampled synthetic outcomes because TOO_LATE rows have no `signal_outcomes`.

## Data Quality Check

```sql
SELECT
  signal_label,
  COUNT(*) AS n,
  ROUND(MIN(score), 3) AS min_score,
  ROUND(MAX(score), 3) AS max_score,
  ROUND(AVG(score), 3) AS avg_score,
  SUM(CASE WHEN score < 0.80 THEN 1 ELSE 0 END) AS score_lt_080_n
FROM signals
WHERE signal_label IN ('BUY_NOW','WATCH')
GROUP BY signal_label;
```

| signal_label | n | min_score | max_score | avg_score | score_lt_080_n |
| --- | --- | --- | --- | --- | --- |
| BUY_NOW | 114 | 0.724 | 0.912 | 0.842 | 17 |
| WATCH | 84 | 0.572 | 0.872 | 0.731 | 83 |

Interpretation: The table contains 17 BUY_NOW rows with `score < 0.80`, despite the stated BUY_NOW minimum. Most are Bitvavo rows, so this should be checked in the live signal labelling/config path before treating score calibration as clean.

## A. Overall BUY_NOW performance (first_hit)

### Distribution

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  outcome_class,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_buy_now_eval,
  ROUND(AVG(net_ev_pct), 3) AS avg_net_ev_pct,
  CASE WHEN COUNT(*) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM classified
WHERE signal_label = 'BUY_NOW'
GROUP BY outcome_class
ORDER BY CASE outcome_class
  WHEN 'TP2' THEN 1 WHEN 'TP1' THEN 2 WHEN 'TP_PROXY' THEN 3
  WHEN 'TIMEOUT' THEN 4 WHEN 'TIMEOUT_PROXY' THEN 5
  WHEN 'STOP' THEN 6 WHEN 'STOP_PROXY' THEN 7
  WHEN 'AMBIGUOUS' THEN 8 ELSE 9 END;
```

| outcome_class | n | pct_of_buy_now_eval | avg_net_ev_pct | note |
| --- | --- | --- | --- | --- |
| TP1 | 12 | 10.6 | 0.7 | ⚠️ insufficient data |
| TP_PROXY | 13 | 11.5 | 0.7 | ⚠️ insufficient data |
| TIMEOUT | 15 | 13.3 | -0.343 |  |
| TIMEOUT_PROXY | 47 | 41.6 | -0.209 |  |
| STOP | 7 | 6.2 | -2 | ⚠️ insufficient data |
| STOP_PROXY | 13 | 11.5 | -2 | ⚠️ insufficient data |
| AMBIGUOUS | 6 | 5.3 |  | ⚠️ insufficient data |


### Summary

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  COUNT(*) AS evaluated_buy_now,
  SUM(CASE WHEN outcome_class IN ('AMBIGUOUS','UNKNOWN') THEN 1 ELSE 0 END) AS excluded_ambiguous,
  SUM(CASE WHEN outcome_class NOT IN ('AMBIGUOUS','UNKNOWN') THEN 1 ELSE 0 END) AS usable_n,
  ROUND(100.0 * SUM(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN outcome_class NOT IN ('AMBIGUOUS','UNKNOWN') THEN 1 ELSE 0 END),0), 1) AS tp_first_pct,
  ROUND(100.0 * SUM(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN outcome_class NOT IN ('AMBIGUOUS','UNKNOWN') THEN 1 ELSE 0 END),0), 1) AS stop_first_pct,
  ROUND(AVG(CASE WHEN outcome_class NOT IN ('AMBIGUOUS','UNKNOWN') THEN net_ev_pct END), 3) AS avg_net_ev_pct
FROM classified
WHERE signal_label='BUY_NOW';
```

| evaluated_buy_now | excluded_ambiguous | usable_n | tp_first_pct | stop_first_pct | avg_net_ev_pct |
| --- | --- | --- | --- | --- | --- |
| 113 | 6 | 107 | 23.4 | 18.7 | -0.35 |


Interpretation: BUY_NOW has 107 usable evaluated rows after excluding 6 ambiguous old-code rows. TP-first is 23.4%, far below the 74% fee-adjusted breakeven rate, and average net EV is -0.350% per usable signal. This is negative EV even with the relatively generous TIMEOUT treatment requested in the prompt.

## B. Score calibration

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
),
buckets(bucket, sort_order) AS (
  VALUES ('<0.80',1), ('0.80-0.85',2), ('0.85-0.90',3), ('>=0.90',4)
), scored AS (
  SELECT
    CASE
      WHEN score < 0.80 THEN '<0.80'
      WHEN score < 0.85 THEN '0.80-0.85'
      WHEN score < 0.90 THEN '0.85-0.90'
      ELSE '>=0.90'
    END AS bucket,
    *
  FROM classified
  WHERE signal_label IN ('BUY_NOW','WATCH')
    AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
), agg AS (
  SELECT
    bucket,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM scored
  GROUP BY bucket
)
SELECT b.bucket, COALESCE(a.n,0) AS n, a.tp_first_pct, a.stop_first_pct, a.avg_best_exit_pct,
       CASE WHEN COALESCE(a.n,0) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM buckets b
LEFT JOIN agg a USING (bucket)
ORDER BY b.sort_order;
```

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| <0.80 | 41 | 2.4 | 9.8 | 0.864 |  |
| 0.80-0.85 | 40 | 30 | 22.5 | 0.859 |  |
| 0.85-0.90 | 47 | 19.1 | 14.9 | 0.858 |  |
| >=0.90 | 6 | 50 | 0 | 1.636 | ⚠️ insufficient data |


Interpretation: The score is not monotonic yet: 0.80-0.85 outperforms 0.85-0.90 on TP-first rate, while >=0.90 looks best but has only 6 rows and is flagged insufficient. The <0.80 bucket is mostly WATCH but includes some BUY_NOW rows in the raw table, so the score threshold implementation/config should be checked.

## C. WATCH signal value

### WATCH -> BUY_NOW within 30m

```sql
SELECT
  COUNT(*) AS watch_n,
  SUM(CASE WHEN EXISTS (
    SELECT 1
    FROM signals b
    WHERE b.signal_label = 'BUY_NOW'
      AND b.exchange = w.exchange
      AND b.trading_pair = w.trading_pair
      AND b.timestamp > w.timestamp
      AND b.timestamp <= w.timestamp + 1800
  ) THEN 1 ELSE 0 END) AS followed_by_buy_now_30m_n,
  ROUND(100.0 * SUM(CASE WHEN EXISTS (
    SELECT 1
    FROM signals b
    WHERE b.signal_label = 'BUY_NOW'
      AND b.exchange = w.exchange
      AND b.trading_pair = w.trading_pair
      AND b.timestamp > w.timestamp
      AND b.timestamp <= w.timestamp + 1800
  ) THEN 1 ELSE 0 END) / COUNT(*), 1) AS followed_by_buy_now_30m_pct
FROM signals w
WHERE w.signal_label = 'WATCH';
```

| watch_n | followed_by_buy_now_30m_n | followed_by_buy_now_30m_pct |
| --- | --- | --- |
| 84 | 5 | 6 |


### WATCH outcome distribution

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  outcome_class,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_watch_eval,
  ROUND(AVG(net_ev_pct), 3) AS avg_net_ev_pct,
  CASE WHEN COUNT(*) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM classified
WHERE signal_label='WATCH'
GROUP BY outcome_class
ORDER BY CASE outcome_class
  WHEN 'TP2' THEN 1 WHEN 'TP1' THEN 2 WHEN 'TP_PROXY' THEN 3
  WHEN 'TIMEOUT' THEN 4 WHEN 'TIMEOUT_PROXY' THEN 5
  WHEN 'STOP' THEN 6 WHEN 'STOP_PROXY' THEN 7
  WHEN 'AMBIGUOUS' THEN 8 ELSE 9 END;
```

| outcome_class | n | pct_of_watch_eval | avg_net_ev_pct | note |
| --- | --- | --- | --- | --- |
| TIMEOUT | 27 | 100 | 0.527 |  |


### BUY_NOW vs WATCH entry quality

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  signal_label,
  COUNT(*) AS n,
  ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
  ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
  ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct,
  ROUND(AVG(worst_drawdown_pct), 3) AS avg_worst_drawdown_pct,
  ROUND(AVG(net_ev_pct), 3) AS avg_net_ev_pct,
  CASE WHEN COUNT(*) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM classified
WHERE signal_label IN ('BUY_NOW','WATCH')
  AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
GROUP BY signal_label
ORDER BY signal_label;
```

| signal_label | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_worst_drawdown_pct | avg_net_ev_pct | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BUY_NOW | 107 | 23.4 | 18.7 | 0.862 | -1.407 | -0.35 |  |
| WATCH | 27 | 0 | 0 | 1.027 | -1.005 | 0.527 |  |


Interpretation: Only 6.0% of WATCH rows became BUY_NOW within 30 minutes, so WATCH is not currently a strong conversion funnel. Evaluated WATCH rows all timed out: they did not hit TP1 or stop, but their average best excursion was slightly higher and drawdown lower than BUY_NOW. That makes WATCH useful as a low-risk early monitor, not yet as an actionable entry.

## D. Event deduplication

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
),
buy AS (
  SELECT * FROM classified WHERE signal_label='BUY_NOW'
), signal_level AS (
  SELECT
    'signal_level' AS grain,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM buy
  WHERE outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
), event_ranked AS (
  SELECT
    *,
    CAST(timestamp / 1800 AS INTEGER) AS event_bucket,
    ROW_NUMBER() OVER (
      PARTITION BY exchange, trading_pair, CAST(timestamp / 1800 AS INTEGER)
      ORDER BY timestamp, signal_id
    ) AS event_rn
  FROM buy
), event_level AS (
  SELECT
    'event_level_first_signal' AS grain,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM event_ranked
  WHERE event_rn = 1
    AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
)
SELECT *, CASE WHEN n < 15 THEN '⚠️ insufficient data' ELSE '' END AS note FROM signal_level
UNION ALL
SELECT *, CASE WHEN n < 15 THEN '⚠️ insufficient data' ELSE '' END AS note FROM event_level;
```

| grain | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| signal_level | 107 | 23.4 | 18.7 | 0.862 |  |
| event_level_first_signal | 92 | 26.1 | 15.2 | 0.95 |  |


Interpretation: Deduplicating BUY_NOW to the first exchange+pair+30-minute event improves TP-first from 23.4% to 26.1% and lowers stop-first from 18.7% to 15.2%. Repeated same-coin BUY_NOW signals are not inflating the win rate in this snapshot; if anything, they slightly dilute it.

## E. TOO_LATE validation

```sql
WITH db_max AS (
  SELECT MAX(timestamp) AS max_ts FROM signals
), too_late AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    s.exchange,
    s.trading_pair,
    COALESCE(s.entry_max, s.price) AS entry_price,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct
  FROM signals s, db_max m
  WHERE (s.signal_label = 'TOO_LATE'
         OR s.rejection_reason = 'TOO_LATE_EXTENDED_MOVE'
         OR s.all_reasons LIKE '%"TOO_LATE_EXTENDED_MOVE"%')
    AND s.timestamp <= m.max_ts - 1800
), future AS (
  SELECT
    t.signal_id,
    t.timestamp,
    t.exchange,
    t.trading_pair,
    t.entry_price,
    t.score,
    t.price_change_15m_pct,
    t.volume_ratio,
    t.spread_pct,
    MAX(f.price) AS max_price_30m,
    MIN(f.price) AS min_price_30m,
    MIN(CASE WHEN f.price >= t.entry_price * 1.012 THEN f.timestamp - t.timestamp END) AS tp1_at_seconds,
    MIN(CASE WHEN f.price <= t.entry_price * 0.985 THEN f.timestamp - t.timestamp END) AS stop_at_seconds
  FROM too_late t
  LEFT JOIN signals f
    ON f.exchange = t.exchange
   AND f.trading_pair = t.trading_pair
   AND f.timestamp > t.timestamp
   AND f.timestamp <= t.timestamp + 1800
  GROUP BY t.signal_id
), classified_too_late AS (
  SELECT
    *,
    (max_price_30m - entry_price) / entry_price * 100.0 AS best_exit_pct,
    (min_price_30m - entry_price) / entry_price * 100.0 AS worst_drawdown_pct,
    CASE
      WHEN max_price_30m IS NULL THEN 'NO_FUTURE_DATA'
      WHEN tp1_at_seconds IS NULL AND stop_at_seconds IS NULL THEN 'TIMEOUT'
      WHEN tp1_at_seconds IS NOT NULL AND (stop_at_seconds IS NULL OR tp1_at_seconds <= stop_at_seconds) THEN 'TP_PROXY'
      WHEN stop_at_seconds IS NOT NULL AND (tp1_at_seconds IS NULL OR stop_at_seconds < tp1_at_seconds) THEN 'STOP_PROXY'
      ELSE 'AMBIGUOUS'
    END AS outcome_class
  FROM future
)
SELECT
  COUNT(*) AS n,
  ROUND(100.0 * AVG(CASE WHEN outcome_class = 'TP_PROXY' THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
  ROUND(100.0 * AVG(CASE WHEN outcome_class = 'STOP_PROXY' THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
  ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct,
  ROUND(AVG(worst_drawdown_pct), 3) AS avg_worst_drawdown_pct,
  SUM(CASE WHEN outcome_class='TIMEOUT' THEN 1 ELSE 0 END) AS timeout_n,
  CASE WHEN COUNT(*) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM classified_too_late
WHERE outcome_class <> 'NO_FUTURE_DATA';
```

| n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_worst_drawdown_pct | timeout_n | note |
| --- | --- | --- | --- | --- | --- | --- |
| 288 | 45.8 | 39.6 | 2.123 | -3.009 | 42 |  |


Interpretation: There are no signal_outcomes rows for TOO_LATE_EXTENDED_MOVE, so this uses scan-sampled future prices from signals rather than the outcome service. The TOO_LATE zone has plenty of upside (avg best_exit_pct 2.123%) but also a very high stop-first rate of 39.6% and TP-first of 45.8%, still far below the 74% breakeven requirement. The filter looks directionally justified as a blow-off risk control, not obviously too strict.

## F. Δ15m bucket analysis

```sql
WITH actual_base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    s.exchange,
    s.trading_pair,
    s.signal_label AS source,
    s.price_change_15m_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_stop,
    o.best_exit_pct
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
    AND s.signal_label IN ('BUY_NOW','WATCH')
), actual AS (
  SELECT
    signal_id, timestamp, exchange, trading_pair, source, price_change_15m_pct, best_exit_pct,
    CASE
      WHEN first_hit IN ('TP1','TP2') THEN 'TP_PROXY'
      WHEN first_hit = 'STOP' THEN 'STOP_PROXY'
      WHEN first_hit = 'TIMEOUT' THEN 'TIMEOUT'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT'
      ELSE 'UNKNOWN'
    END AS outcome_class
  FROM actual_base
), db_max AS (
  SELECT MAX(timestamp) AS max_ts FROM signals
), too_late AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    s.exchange,
    s.trading_pair,
    'TOO_LATE_SYNTH' AS source,
    s.price_change_15m_pct,
    COALESCE(s.entry_max, s.price) AS entry_price
  FROM signals s, db_max m
  WHERE (s.signal_label = 'TOO_LATE'
         OR s.rejection_reason = 'TOO_LATE_EXTENDED_MOVE'
         OR s.all_reasons LIKE '%"TOO_LATE_EXTENDED_MOVE"%')
    AND s.timestamp <= m.max_ts - 1800
), too_late_eval AS (
  SELECT
    t.signal_id,
    t.timestamp,
    t.exchange,
    t.trading_pair,
    t.source,
    t.price_change_15m_pct,
    (MAX(f.price) - t.entry_price) / t.entry_price * 100.0 AS best_exit_pct,
    CASE
      WHEN MAX(f.price) IS NULL THEN 'NO_FUTURE_DATA'
      WHEN MIN(CASE WHEN f.price >= t.entry_price * 1.012 THEN f.timestamp - t.timestamp END) IS NULL
       AND MIN(CASE WHEN f.price <= t.entry_price * 0.985 THEN f.timestamp - t.timestamp END) IS NULL THEN 'TIMEOUT'
      WHEN MIN(CASE WHEN f.price >= t.entry_price * 1.012 THEN f.timestamp - t.timestamp END) IS NOT NULL
       AND (MIN(CASE WHEN f.price <= t.entry_price * 0.985 THEN f.timestamp - t.timestamp END) IS NULL
        OR MIN(CASE WHEN f.price >= t.entry_price * 1.012 THEN f.timestamp - t.timestamp END)
         <= MIN(CASE WHEN f.price <= t.entry_price * 0.985 THEN f.timestamp - t.timestamp END)) THEN 'TP_PROXY'
      WHEN MIN(CASE WHEN f.price <= t.entry_price * 0.985 THEN f.timestamp - t.timestamp END) IS NOT NULL THEN 'STOP_PROXY'
      ELSE 'AMBIGUOUS'
    END AS outcome_class
  FROM too_late t
  LEFT JOIN signals f
    ON f.exchange = t.exchange
   AND f.trading_pair = t.trading_pair
   AND f.timestamp > t.timestamp
   AND f.timestamp <= t.timestamp + 1800
  GROUP BY t.signal_id
), universe AS (
  SELECT * FROM actual
  UNION ALL
  SELECT signal_id, timestamp, exchange, trading_pair, source, price_change_15m_pct, best_exit_pct, outcome_class
  FROM too_late_eval
  WHERE outcome_class <> 'NO_FUTURE_DATA'
), bucketed AS (
  SELECT
    CASE
      WHEN price_change_15m_pct < 2.5 THEN '<2.5%'
      WHEN price_change_15m_pct < 4.0 THEN '2.5-4%'
      WHEN price_change_15m_pct < 5.5 THEN '4-5.5%'
      WHEN price_change_15m_pct < 6.0 THEN '5.5-6%'
      ELSE '>=6% (TOO_LATE zone)'
    END AS bucket,
    *
  FROM universe
  WHERE outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
), buckets(bucket, sort_order) AS (
  VALUES ('<2.5%',1), ('2.5-4%',2), ('4-5.5%',3), ('5.5-6%',4), ('>=6% (TOO_LATE zone)',5)
), agg AS (
  SELECT
    bucket,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class = 'TP_PROXY' THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class = 'STOP_PROXY' THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM bucketed
  GROUP BY bucket
)
SELECT b.bucket, COALESCE(a.n,0) AS n, a.tp_first_pct, a.stop_first_pct, a.avg_best_exit_pct,
       CASE WHEN COALESCE(a.n,0) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM buckets b
LEFT JOIN agg a USING (bucket)
ORDER BY b.sort_order;
```

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| <2.5% | 0 |  |  |  | ⚠️ insufficient data |
| 2.5-4% | 110 | 13.6 | 12.7 | 0.616 |  |
| 4-5.5% | 21 | 47.6 | 19 | 2.384 |  |
| 5.5-6% | 1 | 0 | 0 | 1.627 | ⚠️ insufficient data |
| >=6% (TOO_LATE zone) | 290 | 45.5 | 40 | 2.11 |  |


Interpretation: The 4-5.5% bucket is the best observed area so far, with 47.6% TP-first and 2.384% average best excursion, though n=21 is still early. The >=6% bucket also has upside but nearly matches it with stop-first risk at 40.0%, so loosening the TOO_LATE threshold would likely add volatility rather than clean edge. The exact 5.5-6.0% boundary has only 1 usable row, so the precise 6.0% cutoff cannot be validated yet.

## G. Volume ratio analysis

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
),
buckets(bucket, sort_order) AS (
  VALUES ('<2x',1), ('2-3x',2), ('3-5x',3), ('>=5x',4)
), bucketed AS (
  SELECT
    CASE
      WHEN volume_ratio < 2.0 THEN '<2x'
      WHEN volume_ratio < 3.0 THEN '2-3x'
      WHEN volume_ratio < 5.0 THEN '3-5x'
      ELSE '>=5x'
    END AS bucket,
    *
  FROM classified
  WHERE signal_label IN ('BUY_NOW','WATCH')
    AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
    AND volume_ratio IS NOT NULL
), agg AS (
  SELECT
    bucket,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM bucketed
  GROUP BY bucket
)
SELECT b.bucket, COALESCE(a.n,0) AS n, a.tp_first_pct, a.stop_first_pct, a.avg_best_exit_pct,
       CASE WHEN COALESCE(a.n,0) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM buckets b
LEFT JOIN agg a USING (bucket)
ORDER BY b.sort_order;
```

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| <2x | 0 |  |  |  | ⚠️ insufficient data |
| 2-3x | 24 | 4.2 | 12.5 | 0.78 |  |
| 3-5x | 36 | 19.4 | 16.7 | 0.851 |  |
| >=5x | 74 | 23 | 14.9 | 0.954 |  |


Interpretation: Within evaluated BUY_NOW+WATCH rows, >=5x volume does not show worse aggregate outcomes; TP-first is 23.0% versus 19.4% for 3-5x. However, the worst-signal review shows high volume is common among severe losers, so volume_ratio likely needs interaction checks with spread and Δ15m rather than a simple cap.

## H. Spread analysis

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
),
buckets(bucket, sort_order) AS (
  VALUES ('<0.10%',1), ('0.10-0.20%',2), ('0.20-0.30%',3), ('>=0.30%',4)
), bucketed AS (
  SELECT
    CASE
      WHEN spread_pct < 0.10 THEN '<0.10%'
      WHEN spread_pct < 0.20 THEN '0.10-0.20%'
      WHEN spread_pct < 0.30 THEN '0.20-0.30%'
      ELSE '>=0.30%'
    END AS bucket,
    *
  FROM classified
  WHERE signal_label IN ('BUY_NOW','WATCH')
    AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
    AND spread_pct IS NOT NULL
), agg AS (
  SELECT
    bucket,
    COUNT(*) AS n,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
    ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
    ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct
  FROM bucketed
  GROUP BY bucket
)
SELECT b.bucket, COALESCE(a.n,0) AS n, a.tp_first_pct, a.stop_first_pct, a.avg_best_exit_pct,
       CASE WHEN COALESCE(a.n,0) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM buckets b
LEFT JOIN agg a USING (bucket)
ORDER BY b.sort_order;
```

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| <0.10% | 40 | 27.5 | 2.5 | 0.963 |  |
| 0.10-0.20% | 71 | 11.3 | 18.3 | 0.69 |  |
| 0.20-0.30% | 23 | 26.1 | 26.1 | 1.411 |  |
| >=0.30% | 0 |  |  |  | ⚠️ insufficient data |


Interpretation: The cleanest bucket is <0.10% spread: 27.5% TP-first and only 2.5% stop-first. Spreads of 0.10-0.20% have the weakest TP-first rate, while 0.20-0.30% is mixed with both high TP and high stop rates; there are no accepted/evaluated rows >=0.30%. Do not tighten max_spread_pct solely from this yet, but monitor or penalize >0.20% spread until more data arrives.

## I. Exchange performance

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  exchange,
  COUNT(*) AS n,
  ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
  ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('STOP','STOP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS stop_first_pct,
  ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct,
  CASE
    WHEN COUNT(*) < 15 THEN '⚠️ insufficient data'
    WHEN COUNT(*) < 20 THEN 'indicative (<20 outcomes)'
    ELSE ''
  END AS note
FROM classified
WHERE signal_label='BUY_NOW'
  AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
GROUP BY exchange
ORDER BY n DESC;
```

| exchange | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- | --- |
| bitvavo | 67 | 23.9 | 17.9 | 0.976 |  |
| kraken | 36 | 19.4 | 22.2 | 0.505 |  |
| okx | 4 | 50 | 0 | 2.164 | ⚠️ insufficient data |


Interpretation: Bitvavo and Kraken both have enough outcomes for early conclusions and both are below breakeven. Bitvavo is modestly better on TP-first and average best excursion; Kraken has higher stop-first and lower average best excursion. OKX has only 4 usable outcomes and is insufficient data.

## J. Daily regime

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  signal_day,
  COUNT(*) AS n,
  ROUND(100.0 * AVG(CASE WHEN outcome_class IN ('TP1','TP2','TP_PROXY') THEN 1.0 ELSE 0.0 END), 1) AS tp_first_pct,
  ROUND(AVG(best_exit_pct), 3) AS avg_best_exit_pct,
  CASE WHEN COUNT(*) < 15 THEN '⚠️ insufficient data' ELSE '' END AS note
FROM classified
WHERE signal_label='BUY_NOW'
  AND outcome_class NOT IN ('AMBIGUOUS','UNKNOWN')
GROUP BY signal_day
ORDER BY signal_day;
```

| signal_day | n | tp_first_pct | avg_best_exit_pct | note |
| --- | --- | --- | --- | --- |
| 2026-06-05 | 40 | 20 | 0.738 |  |
| 2026-06-06 | 42 | 16.7 | 0.88 |  |
| 2026-06-07 | 25 | 40 | 1.03 |  |


Interpretation: No single day dominates the row count: 2026-06-05 and 2026-06-06 are similar, and 2026-06-07 is smaller. The newest day has much better TP-first (40.0%), so the current aggregate may be regime-sensitive and is not yet generalisable.

## K. Worst signals (filter tuning)

### Worst 20 BUY_NOW drawdowns

```sql
WITH base AS (
  SELECT
    s.id AS signal_id,
    s.timestamp,
    date(s.timestamp, 'unixepoch') AS signal_day,
    s.exchange,
    s.trading_pair,
    s.signal_label,
    s.score,
    s.price_change_15m_pct,
    s.volume_ratio,
    s.spread_pct,
    o.first_hit,
    o.hit_tp1,
    o.hit_tp2,
    o.hit_stop,
    o.best_exit_pct,
    o.worst_drawdown_pct,
    o.stop_hit_at_seconds
  FROM signals s
  JOIN signal_outcomes o ON o.signal_id = s.id
  WHERE o.evaluated_at IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN first_hit IN ('TP1','TP2','STOP','TIMEOUT') THEN first_hit
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 'TP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN 'STOP_PROXY'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=1 THEN 'AMBIGUOUS'
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN 'TIMEOUT_PROXY'
      ELSE 'UNKNOWN'
    END AS outcome_class,
    CASE
      WHEN first_hit = 'TP1' THEN 0.70
      WHEN first_hit = 'TP2' THEN 2.00
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=1 AND COALESCE(hit_stop,0)=0 THEN 0.70
      WHEN first_hit = 'STOP' THEN -2.00
      WHEN first_hit IS NULL AND COALESCE(hit_stop,0)=1 AND COALESCE(hit_tp1,0)=0 THEN -2.00
      WHEN first_hit = 'TIMEOUT' THEN best_exit_pct - 0.50
      WHEN first_hit IS NULL AND COALESCE(hit_tp1,0)=0 AND COALESCE(hit_stop,0)=0 THEN best_exit_pct - 0.50
      ELSE NULL
    END AS net_ev_pct
  FROM base
)
SELECT
  exchange,
  trading_pair,
  ROUND(score, 3) AS score,
  ROUND(price_change_15m_pct, 3) AS price_change_15m_pct,
  ROUND(volume_ratio, 3) AS volume_ratio,
  ROUND(spread_pct, 3) AS spread_pct,
  outcome_class AS first_hit,
  ROUND(stop_hit_at_seconds, 1) AS stop_hit_at_seconds,
  ROUND(worst_drawdown_pct, 3) AS worst_drawdown_pct
FROM classified
WHERE signal_label='BUY_NOW'
  AND (outcome_class = 'STOP' OR COALESCE(hit_stop,0)=1)
ORDER BY worst_drawdown_pct ASC
LIMIT 20;
```

| exchange | trading_pair | score | price_change_15m_pct | volume_ratio | spread_pct | first_hit | stop_hit_at_seconds | worst_drawdown_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bitvavo | ENA-EUR | 0.876 | 3.721 | 5.284 | 0.073 | AMBIGUOUS |  | -4.9 |
| kraken | JTO-USD | 0.749 | 2.985 | 3.114 | 0.137 | STOP_PROXY |  | -4.823 |
| kraken | WLD-USD | 0.873 | 3.035 | 6.057 | 0.21 | STOP | 323.9 | -4.801 |
| bitvavo | ALLO-EUR | 0.854 | 6.082 | 5.372 | 0.136 | STOP_PROXY |  | -4.799 |
| bitvavo | EPIC-EUR | 0.728 | 4.944 | 2.097 | 0.165 | STOP_PROXY |  | -4.687 |
| bitvavo | JTO-EUR | 0.724 | 2.887 | 2.636 | 0.16 | STOP_PROXY |  | -4.539 |
| bitvavo | WLD-EUR | 0.732 | 6.836 | 2.403 | 0.154 | STOP_PROXY |  | -4.33 |
| kraken | H-USD | 0.816 | 3.899 | 4.231 | 0.228 | STOP_PROXY |  | -4.265 |
| bitvavo | JTO-EUR | 0.745 | 2.958 | 2.312 | 0.155 | AMBIGUOUS |  | -4.18 |
| kraken | MON-USD | 0.889 | 2.634 | 9.807 | 0.145 | STOP_PROXY |  | -4.06 |
| bitvavo | BABY-EUR | 0.877 | 3.387 | 7.542 | 0.07 | AMBIGUOUS |  | -3.831 |
| kraken | MON-USD | 0.861 | 2.539 | 6.657 | 0.194 | STOP_PROXY |  | -3.781 |
| kraken | TIA-USD | 0.861 | 3.091 | 11.234 | 0.245 | STOP | 712 | -3.648 |
| bitvavo | SPX-EUR | 0.841 | 2.947 | 4.39 | 0.21 | STOP | 1819.4 | -3.621 |
| bitvavo | BABY-EUR | 0.911 | 4.554 | 7.796 | 0.041 | AMBIGUOUS |  | -3.236 |
| bitvavo | EPIC-EUR | 0.834 | 2.856 | 4.043 | 0.141 | AMBIGUOUS |  | -3.225 |
| bitvavo | TON-EUR | 0.825 | 3.214 | 8.749 | 0.163 | STOP | 637 | -3.089 |
| bitvavo | TON-EUR | 0.83 | 3.133 | 8.484 | 0.099 | STOP | 716.1 | -3.062 |
| kraken | AKT-USD | 0.831 | 2.83 | 7.86 | 0.143 | STOP | 866.7 | -2.993 |
| kraken | PEAQ-USD | 0.871 | 3.435 | 8.632 | 0.211 | STOP_PROXY |  | -2.8 |


### Worst-20 pattern summary

```sql
WITH base AS (
  SELECT s.exchange, s.trading_pair, s.score, s.price_change_15m_pct, s.volume_ratio, s.spread_pct,
         o.first_hit, o.hit_tp1, o.hit_stop, o.worst_drawdown_pct
  FROM signals s JOIN signal_outcomes o ON o.signal_id=s.id
  WHERE s.signal_label='BUY_NOW' AND (o.first_hit='STOP' OR COALESCE(o.hit_stop,0)=1)
  ORDER BY o.worst_drawdown_pct ASC LIMIT 20
)
SELECT
  COUNT(*) AS n,
  SUM(exchange='bitvavo') AS bitvavo_n,
  SUM(exchange='kraken') AS kraken_n,
  SUM(exchange='okx') AS okx_n,
  ROUND(AVG(score),3) AS avg_score,
  SUM(score<0.8) AS score_lt_08_n,
  ROUND(AVG(price_change_15m_pct),3) AS avg_d15,
  SUM(price_change_15m_pct>=5.5) AS d15_ge_55_n,
  ROUND(AVG(volume_ratio),3) AS avg_volume_ratio,
  SUM(volume_ratio>=5) AS vol_ge_5_n,
  ROUND(AVG(spread_pct),3) AS avg_spread,
  SUM(spread_pct>=0.20) AS spread_ge_020_n
FROM base;
```

| n | bitvavo_n | kraken_n | okx_n | avg_score | score_lt_08_n | avg_d15 | d15_ge_55_n | avg_volume_ratio | vol_ge_5_n | avg_spread | spread_ge_020_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 12 | 8 | 0 | 0.826 | 5 | 3.598 | 2 | 5.935 | 12 | 0.154 | 5 |


Interpretation: The worst 20 are concentrated on Bitvavo and Kraken, with no OKX rows. The clearest pattern is high volume: 12 of 20 have volume_ratio >=5x, while only 5 of 20 have spread >=0.20% and only 2 of 20 have Δ15m >=5.5%. Several worst rows also have BUY_NOW scores below 0.80, which is a configuration/data quality concern given the stated BUY_NOW minimum.

## Summary

- Overall BUY_NOW EV is negative: usable TP-first is 23.4% versus the 74% fee-adjusted breakeven target, with avg net EV -0.350% per usable signal.
- Score calibration is not reliable yet; higher score is not monotonic, and the >=0.90 bucket has only 6 rows.
- WATCH is useful as an early monitor but not a strong actionable trigger: only 6.0% converted to BUY_NOW within 30 minutes.
- Deduplication does not reveal inflated win rate; event-level TP-first is slightly better than signal-level.
- The TOO_LATE filter is probably working as risk control: synthetic TOO_LATE TP-first is 45.8%, but stop-first is 39.6% and still below fee breakeven.
- The 4-5.5% Δ15m area looks most promising so far; the exact 5.5-6.0% cutoff remains under-sampled.
- No simple volume cap is justified from aggregate buckets, but high volume appears frequently in the worst drawdowns and deserves interaction analysis.
- Low spread (<0.10%) is clearly cleaner; >0.20% spread should be watched or penalized, but not hard-tightened yet.
- Biggest concern: early-stage data plus old-code proxy outcomes; 79 evaluated outcomes lack real order-aware first_hit.
- After two weeks, re-check first_hit-only performance, score monotonicity, Δ15m 5.5-6.0%, exchange splits, and high-volume/high-spread interaction effects.
