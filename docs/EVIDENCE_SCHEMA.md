# Evidence Schema

Reference document for the Evidence Engine (`tools/evidence/`).

This file is **documentation only**. Every executable threshold lives in
[`config/evidence_policy.yaml`](../config/evidence_policy.yaml). If a number appears in both places,
the policy file wins and this document is out of date.

| | |
|---|---|
| Schema version | 1.0.0 |
| Matching policy version | 1.3.0 |
| Status | Deterministic foundation — no agent layer yet |

---

## 1. Purpose and scope

The Evidence Engine answers exactly one question:

> Is there sufficient evidence that a strategy, configuration or experiment performs better than its baseline?

Valid outcomes are only `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`, plus the two procedural outcomes
`EXPLORATORY` (no pre-registered contract) and `ERROR` (engine could not complete).

The engine never tunes parameters, never proposes trading ideas and never writes to any database.

---

## 2. Databases

Five bot databases share an identical schema. Only three tables are used.

| Bot | Database | Quote | controller_id |
|---|---|---|---|
| Kraken EUR | `data/multi_coin_grid_v2.sqlite` | EUR | `multi_coin_grid` |
| Kraken USD | `data/multi_coin_grid_v2_usd.sqlite` | USD | `multi_coin_grid_usd` |
| Bitget Spot | `data/spot_grid_bitget.sqlite` | USDT | `spot_grid_bitget` |
| OKX Spot | `data/spot_grid_okx.sqlite` | USD | `spot_grid_okx` |
| Bitget Futures | `data/futures_grid_bitget.sqlite` | USDT | `futures_grid_bitget` |

All access is read-only, enforced technically (see §11).

---

## 3. Database fields

### 3.1 `Executors` — primary source

```sql
id TEXT, timestamp FLOAT, type TEXT, close_type INTEGER,
close_timestamp BIGINT, status INTEGER, config JSON,
net_pnl_pct FLOAT, net_pnl_quote FLOAT, cum_fees_quote FLOAT,
filled_amount_quote FLOAT, is_active BOOLEAN, is_trading BOOLEAN,
custom_info JSON, controller_id TEXT
```

`net_pnl_quote`, `cum_fees_quote` and `filled_amount_quote` are plain floats in quote currency.
**No scaling is applied to these columns.**

### 3.2 `custom_info` JSON

Verified present in 554/554 closed executors on Kraken USD.

| Field | Meaning |
|---|---|
| `realized_buy_size_quote` | Buy notional, excluding held positions, after dust correction |
| `realized_sell_size_quote` | Sell notional, excluding held positions |
| `realized_buy_fees_quote` / `realized_sell_fees_quote` / `realized_fees_quote` | Fees in quote |
| `realized_pnl_quote` / `realized_pnl_pct` | Realised result |
| `realized_imbalance_quote` | `realized_buy_size_quote - realized_sell_size_quote` |
| `position_size_quote` / `position_pnl_quote` / `position_fees_quote` | Still-open leg |
| `held_position_value` / `held_position_orders` | Positions excluded from realised metrics |
| `filled_orders[]` | Per order: `executed_amount_base`, `executed_amount_quote`, `trade_type`, `cumulative_fee_paid_quote`, `order_type`, `order_fills{...}` with `is_taker` |
| `break_even_price`, `side`, `early_stop_reason_code` | Context |
| `entry_trend_pct`, `entry_trend_score`, `entry_grid_score` | Per-trade observations |

### 3.3 `config` JSON

Holds the **effective parameters of that individual executor**, including a nested `custom_info`
block with `bot_instance_id`, `no_fill_timeout_sec`, `no_progress_timeout_sec`, `max_hold_time_sec`,
`dynamic_tp_*`, `fee_aware_*`, `soft_risk_*`, plus `triple_barrier_config` with `stop_loss`,
`take_profit`, `trailing_stop.*` and the order types.

This is the basis for the fingerprint (§8). It is authoritative because it records what actually ran,
unlike the YAML config files which are edited between runs.

### 3.4 `TradeFill` — secondary, attributable via `order_id`

```sql
symbol, base_asset, quote_asset, timestamp BIGINT(ms), order_id,
trade_type, order_type, price BIGINT, amount BIGINT,
trade_fee JSON, trade_fee_in_quote BIGINT, exchange_trade_id
```

`TradeFill.order_id` is a declared foreign key to `Order.id` and matches the `client_order_id`
values in `custom_info`. Attribution to a controller therefore runs per executor and is reliable.

Measured **attribution** — the share of executor volume confirmed in `TradeFill`:
**Kraken USD 96.4%, Bitget 99.8%.**

The earlier figures of 47% and 22% were wrong twice over: they used the `/1e9` scaling and divided
total `TradeFill` volume by executor volume. That reverse ratio is meaningless, because `TradeFill`
also contains fills from orders the executors never recorded in `custom_info` (3,253 of 3,976 rows on
Kraken, in the same date range). The engine therefore reports attribution only in the direction that
is well defined, and prints `TRADEFILL ATTRIBUTION: NOT MEASURABLE PER CONTROLLER` when no client
order ids are available.

### 3.5 `Order` — secondary

Provides the requested `price`, enabling realised slippage when joined to `TradeFill.order_id`.

---

## 4. Decimal and scaling rules

| Column | Scaling | Note |
|---|---|---|
| `Executors.net_pnl_quote` | none | plain float, quote currency |
| `Executors.cum_fees_quote` | none | plain float, quote currency |
| `Executors.filled_amount_quote` | none | counts buy **and** sell notional |
| `TradeFill.amount` | **`/ 1e8`** | base units |
| `TradeFill.price` | `/ 1e8` | quote per base |
| `TradeFill.trade_fee_in_quote` | **`/ 1e8`** | quote currency |
| `Order.amount` / `Order.price` | **`/ 1e8`** / `/ 1e8` | same as `TradeFill` |

> **Scaling correction (policy 1.2.0).** `TradeFill.amount` and
> `trade_fee_in_quote` are scaled by `1e8`, not `1e9`. The `/1e9` figure in
> `.github/analysis-context.md` and `performance.agent.md` was wrong and was
> inherited by an earlier version of this document.
>
> Proof, one order present in both tables:
> `TradeFill.amount` `12162587330 / 1e8 = 121.62587330`, exactly equal to
> `custom_info.filled_orders[].executed_amount_base` for order `1381052760`.
> The fee follows the same factor: `11997200 / 1e8 = 0.119972`, exactly the
> `trade_fee.flat_fees[0].amount` of that row.
>
> Note that the fee *rate* cannot settle the question, since fee and amount
> scale together. Only absolute values can.
>
> When writing SQL, express the divisor as the REAL literal `1e8`. SQLite
> performs integer division on `price/100000000` and silently truncates it to
> zero.
| `custom_info.*` numeric strings | none | parse as `Decimal(str(v))` |

**Deployed capital** is `realized_buy_size_quote + position_size_quote`, never `filled_amount_quote`,
because the latter double-counts a round trip.

All monetary arithmetic uses `Decimal`. Floats are used only at the reporting boundary.

---

## 5. Fee rules

### 5.1 The actual format

```json
{"fee_type": "AddedToCost", "percent": "0", "percent_token": "USD",
 "flat_fees": [{"token": "AAVE", "amount": "0.0437276"}]}
```

Three verified facts:

1. **`$.amount` does not exist.** Any query using `json_extract(trade_fee,'$.amount')` returns NULL.
2. **`$.flat_fees[0].amount` must never be summed.** For BUY orders the token is the *base* asset.
   Summing across rows adds ADA units to AAVE units. Measured nonsense total on Bitget: 1,518,689.
3. **`trade_fee_in_quote` is the correct column**, scaled by `1e8` (see section 4). Verified: Bitget
   yields exactly 0.100% of notional, matching the published spot fee.

### 5.2 Fees are already deducted from `net_pnl_quote`

From `multi_coin_grid_pro/logic/exit_safety.py:15-27`:

```python
realized_net_pnl = realized_sell_quote - realized_buy_quote \
                   - realized_buy_fees_quote - realized_sell_fees_quote
```

### 5.3 The canonical rule

```
FEE_CANONICAL  = SUM(Executors.cum_fees_quote)     # only source for totals
NET_PNL        = SUM(Executors.net_pnl_quote)      # ALREADY NET
GROSS_PNL      = NET_PNL + FEE_CANONICAL
FEE_RATE       = FEE_CANONICAL / (buy_quote + sell_quote)   # per side, both legs

FORBIDDEN: NET_PNL - FEE_CANONICAL                  (double counting)
FORBIDDEN: json_extract(trade_fee, '$.amount')      (does not exist)
FORBIDDEN: SUM(json_extract(trade_fee, '$.flat_fees[0].amount'))  (mixed currencies)
```

Fee rates (never totals) may be derived from `TradeFill`, always accompanied by the coverage figure.

**Denominator correction (policy 1.1.0).** The plausibility check divides by total traded notional
(`buy + sell`), not by deployed capital. Fees are charged on both legs, so the deployed-capital
denominator roughly doubles the apparent rate: Kraken measured 0.57% against a 0.60% limit, a
near-false-positive. With traded notional the rates are Kraken 0.317% and Bitget 0.107%, matching
the published schedules exactly.

### 5.4 Known fee anomalies

- `futures_grid_bitget` has `SUM(cum_fees_quote) = -0.1`. Negative fees fail gate G0 unless
  `data_integrity.allow_negative_fees` is set.
- Kraken shows inconsistent effective rates per order type (`LIMIT` 0.091%, `LIMIT_MAKER` 0.284%,
  `MARKET` 0.205%). Unexplained; raised as a data-quality flag.

---

## 6. CloseType enum

Authoritative source: `hummingbot/strategy_v2/models/executors.py:52-71`.

| # | Name | # | Name |
|---|---|---|---|
| 1 | TIME_LIMIT | 9 | COMPLETED |
| 2 | STOP_LOSS | 10 | POSITION_HOLD |
| 3 | TAKE_PROFIT | 11 | NO_FILL_TIMEOUT |
| 4 | EXPIRED | 12 | NO_PROGRESS_TIMEOUT |
| 5 | EARLY_STOP | 13 | HARD_CAP_TIME_LIMIT |
| 6 | TRAILING_STOP | 14 | RISK_KILL_SWITCH |
| 7 | INSUFFICIENT_BALANCE | 15 | MANUAL |
| 8 | FAILED | 16 | SWITCH |

Two mappings in `.github/agents/performance.agent.md` are wrong: it lists 4 as TRAILING_STOP
(4 is EXPIRED, 6 is TRAILING_STOP) and 11 as CLOSE_ORDER_FAILED (11 is NO_FILL_TIMEOUT).

`close_type` is **descriptive only**. It is never used to classify an executor, because phantom
profits were found under `close_type` 11 and 12 and artefacts under 5. Classification uses the
accounting rules in §7.

---

## 7. Classification

### 7.1 Inputs, per executor

```
reg       = filled_orders  MINUS  held_position_orders   (matched on client_order_id)
buy_base  = sum executed_amount_base  where trade_type = BUY   over reg
sell_base = sum executed_amount_base  where trade_type = SELL  over reg
buy_quote = sum executed_amount_quote where trade_type = BUY   over reg
residual  = buy_base - sell_base
avg_entry = buy_quote / buy_base
dust_signature = (buy_quote - custom_info.realized_buy_size_quote) > dust_signature_epsilon_quote
```

`residual` is a **quantity**, not a value. Price movement does not affect it. This is the reason an
earlier quote-based rule was rejected: `|sell_quote - buy_quote| / buy_quote` *is* the profit or
loss, so a threshold on it would have classified every large loss as "not properly closed",
systematically removing losers from the strategy view.

### 7.2 The four layers

| Layer | Condition | Class | Exact? |
|---|---|---|---|
| 1 | `reg` empty, no held orders | `NO_FILL` | yes |
| 1 | `reg` empty, held orders present | `HELD_ONLY` | yes |
| 1 | `buy_base > 0`, `sell_base == 0` | `UNMATCHED_BUY` | yes |
| 1 | `sell_base > 0`, `buy_base == 0` | `UNMATCHED_SELL` | yes |
| 1 | `residual < 0` | `OVERSOLD` | yes |
| 2 | `residual == 0` | `MATCHED_EXACT` | yes |
| 3 | `residual > 0` and `dust_signature` | `MATCHED_DUST_CONFIRMED` | yes |
| 4 | `residual > 0`, no signature, `residual*avg_entry < dust_abs_quote` and `residual/buy_base < dust_rel_pct` | `MATCHED_DUST_HEURISTIC` | **no** |
| 4 | `residual > 0`, otherwise | `PARTIAL_OPEN` | **no** |

Layer 3 is exact because the dust correction in
`hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:4869-4886` only fires when
`0 < residual_base < min_order_size`, using the exchange's real trading rule. Its effect is
detectable as a shortfall between the summed buy notional and the stored `realized_buy_size_quote`.

### 7.3 Why layer 4 cannot be eliminated

`trading_rules.min_order_size` is **not persisted** to the database. Without it, an unflagged
positive residual cannot be proven sellable or unsellable. Adding `min_order_size` to
`config.custom_info` at executor creation would remove layer 4 entirely. That change is out of scope
for the Evidence Engine.

### 7.4 Dust sensitivity

Measured residual distributions are bimodal on Kraken (p50 $0.000001, p95 $9.15) and continuous on
Bitget (p50 $0.038, p99 $0.68). Any threshold between $0.001 and $5 yields an identical result on
Kraken; on Bitget the choice shifts PnL between views B and C.

The engine therefore does not rely on a single threshold. It re-runs the entire gate chain across
`classification.dust_sensitivity_sweep` and requires an identical verdict. A verdict that flips
within the sweep becomes `INSUFFICIENT_EVIDENCE (DUST_SENSITIVE)`.

---

## 8. Views A / B / C

| View | Contents |
|---|---|
| **A — ALL-IN** | Every closed executor, unfiltered. Always reported first. |
| **B — STRATEGY** | `MATCHED_EXACT` + `MATCHED_DUST_CONFIRMED` + `MATCHED_DUST_HEURISTIC` |
| **C — OPERATIONAL** | Everything else: `UNMATCHED_BUY`, `UNMATCHED_SELL`, `OVERSOLD`, `PARTIAL_OPEN`, `NO_FILL`, `HELD_ONLY` |

The anti-bias guarantee:

```
pnl(A) == pnl(B) + pnl(C)    within data_integrity.abc_identity_tolerance_abs
```

Rows may be **reclassified but never discarded**, and the sum must close. A broken identity means the
classification is wrong and yields `INSUFFICIENT_EVIDENCE (DATA_INTEGRITY)`.

Further rules:

- View B is never reported alone; A, B and C always appear together.
- `UNMATCHED_SELL` and `OVERSOLD` never count as winners in any win rate: their profit originates
  from a purchase booked elsewhere.
- If `|pnl(C)| > operational.max_operational_share_of_total * |pnl(A)|`, view B is not representative
  and gate G5 blocks.

---

## 9. Fingerprint

### 9.1 Method

1. Take the **full** executor `config` JSON.
2. Flatten to dotted keys; lists become `<list:n>`.
3. Remove only the denylist from `fingerprint.denylist`.
4. Canonicalise each value: `None` → `"null"`, bool → `"true"`/`"false"`, numerics (including numeric
   strings) → `Decimal`, normalised and quantised to `numeric_significant_digits`, formatted without
   exponent; everything else → `str()`.
5. Sort by key, serialise as JSON with sorted keys.
6. `SHA256` → hex; report the short prefix plus the full hash.

### 9.2 Why a denylist and not a whitelist

Measured over 34 Kraken USD executors (Sept–Oct 2026):

| Method | Fields hashed | Distinct fingerprints | Dominant share |
|---|---|---|---|
| Whitelist | 18 | 9 | 35% |
| **Denylist** | **41** | **11** | **21%** |

The whitelist merged executors whose parameters genuinely differed. Among the 23 fields it missed
were `triple_barrier_config.trailing_stop.activation_price` and `trailing_delta`, the three order
type fields, `custom_info.no_progress_max_extension_sec` (which varied), and the three
`custom_info.soft_risk_*` switches.

A new strategy parameter is not on the denylist and therefore enters the hash automatically. The
cohort **splits** rather than silently merging — failure in the safe direction.

### 9.3 Fingerprint health

```
fingerprint_health = distinct fingerprints / n executors
< fingerprint_health_warn    OK
.. fingerprint_health_stale  warning: check the denylist
> fingerprint_health_stale   DENYLIST_STALE: a new volatile field is present
```

### 9.4 Runtime outputs on the denylist

Seven fields were traced to code that computes them per executor. They are results of the strategy,
not settings of it, so a change in their value must not split a cohort. The settings that drive them
stay in the fingerprint.

| Field | Code path | How it is computed |
|---|---|---|
| `triple_barrier_config.stop_loss` | `controller.py:10721-10745` → `:11011` | `clamp(trend.volatility × atr_stop_multiplier, min_stop_pct, max_stop_pct)` |
| `triple_barrier_config.take_profit` | `controller.py:10787-10825` → `:11012` | trend-dependent, clamped by `dynamic_tp_min_pct` / `dynamic_tp_max_pct` |
| `activation_bounds` | `controller.py:11037-11039` | set equal to the dynamic take profit |
| `max_open_orders` | `controller.py:11034` | `max(1, min(config.max_open_orders, num_grids))` |
| `min_spread_between_orders` | `controller.py:10658` → `:11030` | `roundtrip_fee_pct + min_net_profit_pct` |
| `custom_info.no_fill_timeout_sec` | `controller.py:10905-10948` → `:11047` | regime base plus ATR resolver `get_recommended_timeout()` |
| `custom_info.no_progress_max_extension_sec` | `controller.py:11051` | `regime_progress_sec × 2` |
| `custom_info.no_progress_timeout_sec` *(1.3.0)* | `controller.py:10921` → `:11048` | regime bucket: BULL 7200 / CHOP 5400 / BEAR 3600 |

Both venues run with `use_professional_risk_mgmt: true` and `use_dynamic_take_profit: true`. The
difference in `stop_loss` cardinality follows from the clamp band: Kraken `[0.010, 0.020]` yields 4
distinct values, Bitget `[0.02, 0.05]` yields 17.

`custom_info.no_progress_timeout_sec` was added in policy 1.3.0 after it blocked the first freeze
attempt. The YAML scalar (`2700` on Kraken) is only a fallback; the effective value comes from the
`regime_timeouts` block and therefore changes when the market regime flips, with no configuration
change whatsoever. Leaving it in split the September Kraken cohort into 19 + 9 executors across a
single CHOP → BULL → CHOP excursion, costing 32% of the sample for a non-strategic reason. Denylisting
the sibling (`no_fill_timeout_sec`) and the derivative (`no_progress_max_extension_sec`) while keeping
the source was also internally incoherent.

**Deliberately NOT denylisted** — classified `NEEDS REVIEW` and still under investigation:
`custom_info.fee_aware_min_net_profit_pct`, `triple_barrier_config.stop_loss_order_type`,
`time_limit_order_type`, `coerce_tp_to_step`, `safe_extra_spread`, `deduct_base_fees`.

### 9.5 Per-field volatility diagnostic

**The aggregate health ratio is not sufficient.** This was found during implementation and the design
was changed rather than worked around.

On Bitget, `triple_barrier_config.stop_loss` takes **17 distinct values** such as
`0.0210957447345` and `0.0342587902338`. These are ATR-derived per-trade values, not configured
parameters. They shatter the cohort (202 distinct fingerprints over 1093 executors, dominant share
33%) while `fingerprint_health` stays at 0.185 — far below the 0.70 stale threshold. The aggregate
ratio therefore misses *semi*-volatile fields entirely.

The engine now also reports, whenever a cohort fragments, which fields drive the fragmentation and
with how many distinct values. It does **not** auto-denylist them, because the same key can be a
genuine parameter on one venue and an observation on another: `stop_loss` is a fixed `0.02` on
Kraken and market-derived on Bitget. Deciding which is which is an operator judgement.

Measured examples:

| Venue | Top fragmenting field | Distinct |
|---|---|---|
| Bitget | `triple_barrier_config.stop_loss` | 17 |
| Bitget | `max_open_orders` | 11 |
| Kraken USD | `max_open_orders` | 9 |
| Kraken USD | `custom_info.no_fill_timeout_sec` | 8 |

---

## 10. Metrics

### 10.1 Measurable

`n_executors`, `n_filled`, `n_matched`, `fill_rate`, `net_pnl`, `fees`, `gross_pnl`,
`deployed_capital`, `expectancy_per_trade`, `return_on_deployed`, `win_rate`, `avg_win`, `avg_loss`,
`payoff_ratio`, `profit_factor`, `worst_trade`, `max_consecutive_losses`, `close_type_distribution`,
`leg_imbalance`, `reconciliation_residual`.

### 10.2 Conditionally measurable

| Metric | Condition | Caveat |
|---|---|---|
| `realized_slippage_bps` | `TradeFill`↔`Order` join | 47% / 22% coverage. Verified: LIMIT_MAKER 0.0 bps, LIMIT −0.16 bps, MARKET −19.24 bps |
| `maker_taker_mix` | `order_type` | `LIMIT` is ambiguous; it is 93% of Kraken fills. `order_fills.is_taker` exists but is not yet validated |
| `effective_fee_rate` | `trade_fee_in_quote` | Report coverage alongside |
| `pnl_drawdown` | ordered by `close_timestamp` | **Not equity drawdown.** Concurrent and unrealised positions are absent. Must be labelled *realized-PnL-sequence drawdown* |
| `regime_performance` | `entry_regime` | Coverage: Kraken USD 0/554, Kraken EUR 0/2216, Bitget 107/1092, OKX 9/21 — effectively unusable |

### 10.3 Not measurable with current data

The engine must refuse to report these, even approximately:

- **Equity curve / true max drawdown** — no periodic account equity snapshots
- **Sharpe / Sortino / return volatility** — requires a fixed-interval equity series
- **Time-weighted return** — no capital snapshots; `total_amount_quote` is an order budget
- **True maker/taker split** — 93% of Kraken fills carry an ambiguous `LIMIT` type
- **Regime-segmented performance** — coverage 0–10%
- **Expected vs realised slippage** — the pre-trade estimate is not persisted
- **Opportunity cost of locked capital** — no balance time series
- **Trade independence** — concurrent executors on correlated pairs; not correctable from the data

---

## 11. Read-only enforcement

Three independent mechanisms, all applied:

1. URI connection with `mode=ro` plus `immutable=0`.
2. `PRAGMA query_only = ON` immediately after connect.
3. An `sqlite3` authorizer callback that denies every non-read action
   (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `VACUUM`, `PRAGMA`, `ATTACH`, …).

Any attempted mutation raises before reaching the file.

---

## 12. Gate order G0–G7

Strictly ordered. The first gate that trips determines the outcome.

| Gate | Check | Outcome on failure |
|---|---|---|
| **G0** | Reconciliation residual, `A == B + C`, no negative fees, fee rate within range | `INSUFFICIENT_EVIDENCE (DATA_INTEGRITY)` — stop, report no metrics |
| **G1** | Dominant fingerprint share, same venue/quote/controller, no period overlap, denylist not stale | `INSUFFICIENT_EVIDENCE (MIXED_COHORT)` or `(DENYLIST_STALE)` |
| **G2** | Valid pre-registered contract with `frozen_at` before `period_start`, matching `policy_version` | `EXPLORATORY` (can never become PASS) or `(POLICY_DRIFT)` |
| **G3** | `min_matched_trades`, `min_trading_days`, `min_distinct_pairs`, pair and single-trade concentration | `INSUFFICIENT_EVIDENCE (SAMPLE)` |
| **G4** | Contract abort condition triggered during the run | `FAIL (ABORTED)` |
| **G5** | Operational share of total, unmatched-buy rate | `INSUFFICIENT_EVIDENCE (OPERATIONAL_NOISE)` |
| **G6** | Primary metric at or below `failure_threshold`; or non-positive expectancy after fees | `FAIL` |
| **G7** | All of: primary metric at or above `success_threshold`; bootstrap CI lower bound above baseline; positive expectancy after fees; drawdown within `max_drawdown_ratio_vs_baseline`; operational rate not worse | `PASS`, else `INSUFFICIENT_EVIDENCE (INCONCLUSIVE)` |

Additional hard rules:

- **Gate orthogonality.** The G3 concentration checks (`max_pair_pnl_share`,
  `max_single_trade_pnl_share`) are measured on **view B only**. Measuring them on view A would let a
  single large operational loss — a G5 concern — surface as a sample problem at G3 and mask itself.
  This was found and corrected during implementation.
- The primary metric must come from `decision.primary_metric_allowlist`. `win_rate` is explicitly
  forbidden — Bitget showed a 53.7% win rate with negative expectancy.
- If `payoff_ratio * win_rate / (1 - win_rate) <= 1` the edge is mathematically negative → `FAIL`.
- A `PASS` on paper data is reported as `PASS (PAPER)` and never authorises live trading.
- When two outcomes are defensible, the conservative one wins: `INSUFFICIENT_EVIDENCE`.

---

## 13. Responsibility boundary

| Python (`tools/evidence/`) | Agent (future, thin) |
|---|---|
| Load and validate policy and contract | Start the tool |
| Fingerprint, classify, reconcile | Read `report.json` |
| Compute metrics and bootstrap | Quote `verdict` **verbatim** |
| Run the dust sensitivity sweep | Explain which gate failed |
| **Evaluate gates and decide the verdict** | Refer on to the next agent |
| Write `report.md` and `report.json` | — |

The agent may never compute, derive, soften or reinterpret a verdict. Reproducibility is enforced by
a fixed bootstrap seed and an `input_hash` over policy version, contract, database identity and
cohort selection.

---

## 14. Known open risks

1. **Layer 4 remains heuristic** until `min_order_size` is persisted per executor.
2. **`TradeFill` coverage is 22–47%**, so execution-quality metrics are estimates on a subset.
3. **Kraken's effective fee rate is internally inconsistent** across order types; unexplained.
4. **Ten `UNMATCHED_BUY` executors on Kraken USD represent −484.20**, 94.9% of that database's total
   loss. Until that is explained operationally, no experiment on that database can produce a `PASS`.
5. **`order_fills.is_taker` is present but unvalidated**; a `LIMIT_MAKER` order was observed with
   `is_taker: true`, which is contradictory.
6. **Both production databases fail gate G1 over their full history.** Kraken USD has 84 distinct
   fingerprints over 554 executors (dominant 10%); Bitget has 202 over 1093 (dominant 33%). Until a
   configuration is held still long enough to accumulate the required sample, no experiment on
   either database can reach a verdict beyond `INSUFFICIENT_EVIDENCE`. This is a finding about the
   way the bots have been operated, not a defect in the engine.
7. **Dust-sweep stability can be masked.** When an earlier gate blocks every sweep point the verdict
   is trivially identical, which says nothing about the dust threshold. Bitget's view B varies from
   126 to 484 trades across the sweep while the verdict stays constant at G1. The engine reports
   this masking explicitly.
