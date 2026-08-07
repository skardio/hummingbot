# Momentum Signal Analysis Report

Snapshot: 2026-07-24 18:24 Europe/Berlin
Database: `data/momentum_signals.sqlite`
WAL checkpoint: `[(0, 343, 343)]`

## Method Notes

This report analyses only outcomes that can be joined back to current `signals` rows. The database contains many older `signal_outcomes` rows whose `signal_id` no longer exists in the current `signals` table; those rows are useful as a data-retention warning, but not for current score/exchange/filter attribution.

Net EV uses the same fee model as before:

- `TP1`: `+0.70%`
- `TP2`: `+2.00%`
- `STOP`: `-2.00%`
- `TIMEOUT`: `best_exit_pct - 0.50%`

Rows with `n < 15` are marked insufficient.

## 1. Data Quality

```sql
SELECT
  (SELECT COUNT(*) FROM signals) AS signals_total,
  (SELECT COUNT(*) FROM signals WHERE signal_label IS NOT NULL) AS labeled_signals,
  (SELECT COUNT(*) FROM signals WHERE signal_label='BUY_NOW') AS buy_now_signals,
  (SELECT COUNT(*) FROM signals WHERE signal_label='WATCH') AS watch_signals,
  (SELECT COUNT(*) FROM signal_outcomes WHERE evaluated_at IS NOT NULL) AS evaluated_outcomes_total,
  (SELECT COUNT(*) FROM signal_outcomes o JOIN signals s ON s.id=o.signal_id WHERE o.evaluated_at IS NOT NULL) AS evaluated_outcomes_joinable,
  (SELECT COUNT(*) FROM signal_outcomes o LEFT JOIN signals s ON s.id=o.signal_id WHERE o.evaluated_at IS NOT NULL AND s.id IS NULL) AS orphan_evaluated_outcomes,
  (SELECT datetime(MIN(timestamp),'unixepoch') FROM signals) AS min_signal_ts,
  (SELECT datetime(MAX(timestamp),'unixepoch') FROM signals) AS max_signal_ts;
```

| signals_total | labeled_signals | buy_now_signals | watch_signals | evaluated_outcomes_total | evaluated_outcomes_joinable | orphan_evaluated_outcomes | min_signal_ts | max_signal_ts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1,565,680 | 75 | 69 | 6 | 1,206 | 50 | 1,156 | 2026-07-17 16:26:23 | 2026-07-24 16:26:06 |

Interpretation: The service has a lot of scan data, but only 75 labeled current signals. Most evaluated outcomes are stale/orphaned and cannot be attributed to current signal features; current performance analysis should use the 50 joinable outcomes only. This strongly suggests the outcome table should be pruned or archived together with its matching signal rows.

## 2. BUY_NOW Performance

```sql
-- Current joined BUY_NOW outcomes only.
SELECT first_hit, COUNT(*) n,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) pct,
       ROUND(AVG(net_ev_pct),3) avg_net_ev_pct
FROM current_outcomes
WHERE signal_label='BUY_NOW'
GROUP BY first_hit;
```

| first_hit | n | pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | --- |
| TP1 | 22 | 44.9 | 0.700 |  |
| TIMEOUT | 19 | 38.8 | -0.403 |  |
| STOP | 8 | 16.3 | -2.000 | insufficient |

Summary:

| n | tp_first_n | tp_first_pct | stop_first_n | stop_first_pct | timeout_n | avg_best_exit_pct | avg_worst_drawdown_pct | avg_net_ev_pct |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 49 | 22 | 44.9 | 8 | 16.3 | 19 | 1.770 | -1.216 | -0.169 |

Interpretation: BUY_NOW is much better than the earlier June snapshot, but still below the fee-adjusted breakeven target of ~74% TP-first. Average net EV is slightly negative at `-0.169%` per signal, mainly because timeouts and stops still eat the TP1 edge. This is promising directionally, not tradable edge yet.

## 3. Score Calibration

```sql
SELECT bucket, COUNT(*) n,
       ROUND(100.0*AVG(tp_first),1) tp_first_pct,
       ROUND(100.0*AVG(stop_first),1) stop_first_pct,
       ROUND(AVG(best_exit_pct),3) avg_best_exit_pct,
       ROUND(AVG(net_ev_pct),3) avg_net_ev_pct
FROM score_bucketed_buy_now
GROUP BY bucket;
```

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 0.80-0.85 | 9 | 33.3 | 11.1 | 2.444 | 0.095 | insufficient |
| 0.85-0.90 | 29 | 41.4 | 17.2 | 1.274 | -0.288 |  |
| >=0.90 | 11 | 63.6 | 18.2 | 2.526 | -0.070 | insufficient |

Interpretation: Higher score appears to improve TP-first rate, especially `>=0.90`, but that bucket has only 11 rows. The middle bucket is currently negative EV. Score calibration looks better than before, but needs more samples before hard threshold changes.

## 4. WATCH Signals

```sql
SELECT signal_label, COUNT(*) n,
       ROUND(100.0*AVG(tp_first),1) tp_first_pct,
       ROUND(100.0*AVG(stop_first),1) stop_first_pct,
       ROUND(AVG(best_exit_pct),3) avg_best_exit_pct,
       ROUND(AVG(net_ev_pct),3) avg_net_ev_pct
FROM current_outcomes
WHERE signal_label IN ('BUY_NOW','WATCH')
GROUP BY signal_label;
```

| signal_label | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| BUY_NOW | 49 | 44.9 | 16.3 | 1.770 | -0.169 |  |
| WATCH | 1 | 0.0 | 0.0 | 0.491 | -0.009 | insufficient |

WATCH conversion:

| watch_n | followed_by_buy_now_30m_n | followed_by_buy_now_30m_pct |
| ---: | ---: | ---: |
| 6 | 0 | 0.0 |

Interpretation: WATCH has almost no usable data in the current run. None of the six WATCH labels became BUY_NOW within 30 minutes. No conclusion should be drawn beyond “WATCH is not currently generating much signal flow.”

## 5. Event Deduplication

Event definition: same `exchange + trading_pair + 30-minute bucket`, first signal only.

| grain | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| signal_level | 49 | 44.9 | 16.3 | 1.770 | -0.169 |  |
| event_level_first_signal | 45 | 46.7 | 15.6 | 1.869 | -0.107 |  |

Interpretation: Repeated signals are not inflating performance. Event-level metrics are slightly better than raw signal-level metrics, so duplicate same-coin signals are mildly dilutive rather than artificially boosting the win rate.

## 6. TOO_LATE Validation

There are 685 TOO_LATE rows, but no stored `signal_outcomes` for them. This section uses synthetic scan-based 30-minute future prices.

| n | tp1_n | tp_first_pct | stop_n | stop_first_pct | timeout_n | avg_best_exit_pct | avg_worst_drawdown_pct | note |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 643 | 317 | 49.3 | 283 | 44.0 | 43 | 2.890 | -2.020 |  |

Interpretation: TOO_LATE moves have strong upside, but the stop-first rate is very high at 44.0%. TP-first is still far below fee-adjusted breakeven, so the TOO_LATE filter looks directionally justified. It may be worth testing a special “late breakout but no trade” alert, but not loosening the entry filter yet.

## 7. Delta 15m Buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2.5-4% | 42 | 45.2 | 11.9 | 1.926 | -0.048 |  |
| 4-5.5% | 7 | 42.9 | 42.9 | 0.838 | -0.889 | insufficient |

Interpretation: The accepted BUY_NOW population is mostly in the `2.5-4%` 15-minute move bucket, and that is close to breakeven but still slightly negative. The `4-5.5%` bucket is very small and ugly: same TP-first as stop-first. For now, do not raise the momentum ceiling.

## 8. Volume Ratio Buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2-3x | 2 | 0.0 | 50.0 | 0.369 | -0.737 | insufficient |
| 3-5x | 8 | 62.5 | 0.0 | 2.996 | 0.358 | insufficient |
| >=5x | 39 | 43.6 | 17.9 | 1.591 | -0.247 |  |

Interpretation: Extreme volume `>=5x` is the dominant accepted bucket and is negative EV so far. The `3-5x` bucket looks better, but only has 8 rows. This suggests testing a softer penalty for very high volume instead of a hard cap.

## 9. Spread Buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| <0.10% | 31 | 48.4 | 16.1 | 1.676 | -0.067 |  |
| 0.10-0.20% | 18 | 38.9 | 16.7 | 1.932 | -0.344 |  |

Interpretation: Lower spread is cleaner. The `<0.10%` bucket is near breakeven, while `0.10-0.20%` is notably worse net EV. Consider tightening or penalizing entries above `0.10%`, especially if the next sample confirms this.

## 10. Exchange Performance

| exchange | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| bitget | 28 | 53.6 | 25.0 | 2.231 | -0.147 |  |
| bitvavo | 11 | 54.5 | 9.1 | 2.204 | 0.166 | insufficient |
| kraken | 7 | 14.3 | 0.0 | 0.676 | 0.035 | insufficient |
| okx | 3 | 0.0 | 0.0 | -1.570 | -2.070 | insufficient |

Interpretation: Bitget has enough observations for an early read: strong TP-first but too many stops, producing slightly negative EV. Bitvavo looks best, but has only 11 outcomes. Kraken and OKX are too under-sampled for conclusions.

## 11. Daily Regime

| day | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-07-18 | 6 | 33.3 | 33.3 | 0.983 | -0.441 | insufficient |
| 2026-07-19 | 12 | 50.0 | 33.3 | 2.728 | -0.323 | insufficient |
| 2026-07-20 | 7 | 57.1 | 14.3 | 1.435 | -0.026 | insufficient |
| 2026-07-21 | 6 | 50.0 | 0.0 | 1.281 | 0.275 | insufficient |
| 2026-07-22 | 7 | 0.0 | 14.3 | -0.496 | -1.175 | insufficient |
| 2026-07-23 | 7 | 57.1 | 0.0 | 2.451 | 0.381 | insufficient |
| 2026-07-24 | 4 | 75.0 | 0.0 | 4.172 | 0.588 | insufficient |

Interpretation: No single day dominates count, but every daily segment is too small. July 22 was clearly poor; July 23-24 were better. The strategy is regime-sensitive, and a few good recent signals should not be overfit.

## 12. Market Regime At Signal

| regime_bucket | n | tp_first_pct | stop_first_pct | avg_best_exit_pct | avg_net_ev_pct | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| <-0.2 | 5 | 40.0 | 40.0 | 1.311 | -0.669 | insufficient |
| -0.2-0 | 12 | 41.7 | 0.0 | 1.629 | 0.084 | insufficient |
| 0-0.2 | 27 | 51.9 | 14.8 | 2.131 | -0.118 |  |
| >=0.2 | 5 | 20.0 | 40.0 | 0.618 | -0.549 | insufficient |

Interpretation: The middle neutral/slightly positive regime is the main sample and is still slightly negative EV. Extreme positive and negative regimes look bad but are too small. Avoid drawing hard conclusions until regime buckets have at least 30+ rows each.

## 13. Worst Drawdowns

```sql
SELECT exchange, trading_pair, score, price_change_15m_pct, volume_ratio,
       spread_pct, first_hit, stop_hit_at_seconds, best_exit_pct, worst_drawdown_pct
FROM current_outcomes
WHERE signal_label='BUY_NOW' AND (first_hit='STOP' OR hit_stop=1)
ORDER BY worst_drawdown_pct ASC
LIMIT 20;
```

| exchange | pair | score | d15_pct | volume_ratio | spread_pct | first_hit | stop_hit_at_seconds | best_exit_pct | worst_drawdown_pct |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| bitget | US-USDT | 0.904 | 2.750 | 6.941 | 0.082 | TP1 | 1037.9 | 4.075 | -3.515 |
| bitget | BONK-USDT | 0.870 | 3.221 | 8.775 | 0.033 | STOP | 1484.8 | -0.297 | -2.763 |
| bitvavo | BILL-EUR | 0.866 | 3.050 | 30.332 | 0.148 | STOP | 1385.1 | -0.014 | -2.618 |
| bitget | ONDO-USDT | 0.909 | 2.941 | 8.576 | 0.072 | STOP | 317.5 | -0.247 | -2.612 |
| bitget | GWEI-USDT | 0.890 | 2.756 | 7.548 | 0.100 | STOP | 317.2 | -0.302 | -2.581 |
| bitget | LAB-USDT | 0.805 | 4.256 | 2.888 | 0.031 | STOP | 1192.1 | -0.289 | -2.551 |
| bitget | COLLECT-USDT | 0.877 | 4.274 | 8.670 | 0.136 | STOP | 1789.9 | -0.300 | -2.398 |
| bitget | US-USDT | 0.891 | 4.137 | 5.308 | 0.118 | STOP | 1665.7 | 0.397 | -2.331 |
| bitget | GWEI-USDT | 0.905 | 2.794 | 5.865 | 0.084 | STOP | 397.5 | -0.045 | -2.330 |
| bitget | US-USDT | 0.886 | 3.100 | 5.383 | 0.085 | TP1 | 1197.2 | 5.444 | -2.247 |

Interpretation: Worst drawdowns cluster heavily on Bitget and high-volume setups. Some rows hit TP1 first and later drew down, so order-aware first-hit prevents overstating these as immediate failures. Still, the common pattern is violent post-entry volatility, not merely high spread.

## Summary

- There is a lot of raw scan data, but only 49 current evaluated BUY_NOW outcomes are usable for signal-feature analysis.
- The outcome table has 1,156 orphan evaluated outcomes; prune/archive outcomes together with their source signals or preserve the matching signal history.
- BUY_NOW improved materially: TP-first is 44.9%, stop-first 16.3%, average best excursion 1.77%.
- Despite improvement, average net EV is still slightly negative at `-0.169%` per BUY_NOW signal under the 0.50% fee model.
- Event-level dedupe improves EV from `-0.169%` to `-0.107%`, so duplicates are not inflating results.
- Higher score looks directionally useful, but the highest bucket is still under-sampled.
- The best current zone is `2.5-4%` 15m momentum, low spread `<0.10%`, and possibly volume `3-5x`, though that volume bucket is too small.
- TOO_LATE remains a useful risk filter: synthetic TP-first 49.3%, stop-first 44.0%.
- Bitget has the most data and is still slightly negative EV; Bitvavo looks better but needs more samples.
- Main next action: fix outcome retention/joinability, keep collecting, and re-run after at least 150-200 current BUY_NOW outcomes.
