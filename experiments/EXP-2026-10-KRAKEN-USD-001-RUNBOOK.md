# Runbook — EXP-2026-10-KRAKEN-USD-001

Operational companion to [`EXP-2026-10-KRAKEN-USD-001.yaml`](./EXP-2026-10-KRAKEN-USD-001.yaml).
The contract is the evidence; this file is the procedure.

| | |
|---|---|
| Bot | Kraken USD multi-coin grid (`multi_coin_grid_usd`) |
| Mode | **LIVE** — `paper_trading: false` |
| Available capital | **300,40 USD** (operator-reported, 2026-10-04) |
| Frozen fingerprint | `49344cef79` (34 fields) |
| Policy | 1.3.0 |
| Target | 100 matched trades, ≥20 trading days, ≥5 pairs, within 45 days |
| **Status** | **ABORTED 2026-10-06 — ABORT-OPERATIONAL. See [FIX-001](./FIX-001-partial-fill-on-cancelled-order.md)** |
| Drawdown abort | −25,00 USD (8,32% of available capital) |
| Expected duration | ~24 trading days at the observed 4.25 matched trades/day |

> **This experiment is closed.** It aborted on 2026-10-06 after 2.0 days when a single XDC-USD
> executor booked −33.39 USD on a position that had in fact closed at +0.46 USD profit. The cause
> is an instrumentation defect, not a trading loss: partial fills on cancelled orders are dropped
> from realised PnL. Diagnosis in the contract's `abort_diagnosis`; fix proposal in
> [FIX-001](./FIX-001-partial-fill-on-cancelled-order.md). The successor is
> EXP-2026-10-KRAKEN-USD-002, to be frozen only after the fix is verified.
>
> This run cannot return PASS. No valid baseline cohort exists, and gate G7 requires one.
> The attainable outcomes are **FAIL** or **INSUFFICIENT_EVIDENCE**. The purpose is to
> measure the current strategy honestly and to create the baseline for the next experiment.

---

## 1. Freeze checklist

Complete every line before starting. A single unchecked line invalidates the run.

### Configuration

- [ ] `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` is in the exact state recorded in the contract (`sha256` prefix `0d8a38ea918450f9…`).
- [ ] None of the nine tracked parameters has been touched since `frozen_at`.
- [ ] `paper_trading: false` is intentional and live trading with 300,40 USD is accepted.
- [ ] Available balance re-checked immediately before starting; if it deviates materially from 300,40 USD, update the contract **before** `period_start`.
- [ ] Risk calibration confirmed: `risk_reference_balance_quote` 300 matches the available 300,40, so every percentage limit resolves to within 0,13 pp of its stated intent. `total_amount_quote` 300, `max_daily_loss_quote` 9,00.
- [ ] None of those three fields is part of the fingerprint, so changing them would not break the cohort — but changing them *during* the run alters the risk envelope mid-measurement and is not permitted.
- [ ] No pending edits in `coin_profiles:` or any regime override block.

### Code

- [ ] Working tree contains no uncommitted change to `multi_coin_grid_pro/controllers/`, `hummingbot/strategy_v2/executors/grid_executor/`, `multi_coin_grid_pro/risk/` or `multi_coin_grid_pro/logic/`.
- [ ] Both controller copies are in sync (`diff` of the two `multi_coin_grid_controller.py` files is empty).
- [ ] No planned deploy during the measurement window. A code change that adds or removes a `custom_info` field changes the fingerprint even when no parameter changes — that happened to `post_fill_sampling_start_fill` between September and October.

### Measurement instrument

- [ ] `config/evidence_policy.yaml` reports `policy_version: 1.3.0`.
- [ ] `pytest tests/evidence/ -q` is green (109 tests).
- [ ] `flake8 tools/evidence/ tests/evidence/` is clean.
- [ ] A dry run confirms the active fingerprint is `49344cef79`.

### Record

- [ ] Contract is committed, so `frozen_at` is externally verifiable.
- [ ] Current realized-PnL baseline noted, so the −25.00 USD drawdown abort is measurable from a known zero.

---

## 2. Start checklist

- [ ] Freeze checklist fully complete.
- [x] Start timestamp recorded: **2026-10-04T14:55:58Z** (`1791125758`, 16:55 CEST). Written into the contract as `period_start` / `period_start_unix`, with `period_end_latest` 2026-11-18T14:55:58Z.
- [x] The same unix value is set in the monitoring script (`PERIOD_START`) and in the final command (`--period-start`).
- [ ] Bot actually started at or after that timestamp. If you start materially later, update all three places first.
- [ ] **Operator starts the bot.** No agent, script or assistant may start, stop or restart it.
- [ ] After roughly one hour, run the drift check below and confirm the first closed executors carry fingerprint `49344cef79`.
- [ ] If the first executors show a different fingerprint: stop immediately. The freeze was incomplete; diagnose before restarting under a new experiment id.

---

## 3. Monitoring during the run

At most once per day. Observation only.

```bash
source ~/.venvs/bot/bin/activate
cd /home/mo/repos/hummingbot
python experiments/monitor_EXP-2026-10-KRAKEN-USD-001.py
```

Exit code 0 means no abort condition triggered; exit code 1 means action is required.
The script reads the frozen constants from the contract and checks the sample gate, the
abort thresholds, policy drift and fingerprint drift in one pass.

The script deliberately prints no profitability figures. **Not permitted before the sample gate is
met:** expectancy, win rate, PnL, or any statement about profitability. Looking invites stopping at
a favourable moment.

---

## 4. Stop / abort checklist

Any one trigger ends the run. Record which one, and when.

| Trigger | Threshold | Action |
|---|---|---|
| Fingerprint drift | any fingerprint ≠ `49344cef79` | **INVALID** — stop, do not analyse, new id |
| Policy drift | `policy_version` ≠ 1.3.0 | **INVALID (POLICY_DRIFT)** — new id |
| Data integrity | gate G0 fails | stop, investigate before collecting more |
| Operational noise | `operational_share_of_total` > 0.25 | stop; view B no longer representative |
| Unmatched buys | `unmatched_buy_rate` > 0.10 | stop; the April–May failure mode has returned |
| Drawdown | realized-PnL-sequence drawdown of view A < −25,00 USD (8,32% of 300,40) | stop; protect capital |
| Risk halt | bot's own daily limit trips — **9,00 USD**, i.e. 3,00% of available capital | stop; the trading-day count is compromised |
| Classification | heuristic share > 0.20, or `DUST_SENSITIVE` | stop; the verdict would rest on a threshold |
| Timeout | 2026-11-18 reached without 100 matched trades | close as `INSUFFICIENT_EVIDENCE (SAMPLE)`; do not extend |

On every abort:

- [ ] The **operator** stops the bot. Never an agent or script.
- [ ] Record the trigger, the timestamp and the metric value in the contract's `outcome` section.
- [ ] Do not tune anything in response. Diagnose first.
- [ ] A necessary bugfix means a new experiment id — the old run is closed, not repaired.

---

## 5. Final adjudication

Run only once, after the sample gate is met or an abort has been recorded.

```bash
source ~/.venvs/bot/bin/activate
cd /home/mo/repos/hummingbot

python -m tools.evidence.cli \
    --database data/multi_coin_grid_v2_usd.sqlite \
    --controller-id multi_coin_grid_usd \
    --quote USD \
    --period-start 1791125758 \
    --json-out reports/EXP-2026-10-KRAKEN-USD-001.json \
    | tee reports/EXP-2026-10-KRAKEN-USD-001.md
```

`1791125758` is `2026-10-04T14:55:58Z`, the contract's `period_start_unix`. Add `--period-end <unix>`
when closing on an abort, so the window matches the recorded stop.

Afterwards:

- [ ] Copy `verdict`, `gate` and `reason_code` verbatim from the JSON into the contract's `outcome`.
- [ ] Set `report_path` and `outcome_recorded_at`.
- [ ] Do not reinterpret the verdict. If it reads `INSUFFICIENT_EVIDENCE`, that is the result.
- [ ] This cohort becomes `baseline_id` for the next experiment, whatever the verdict.

---

## 6. Known limitations of this run

1. **PASS is unreachable.** No baseline exists, and G7 requires one.
2. **The accounting defect is unfixed.** `held_position_orders` is still only populated on
   `POSITION_HOLD`, so a `FAILED` executor with an open position still books its full purchase as a
   loss. Not observed on Kraken since May 2026, but the code path is live. The `ABORT-UNMATCHED-BUY`
   trigger is the guard.
3. **Layer-4 classification remains heuristic** until `min_order_size` is persisted per executor.
   Currently 19.3% of view B; the abort threshold is 20%.
4. **Trade independence is not established.** Concurrent executors run on correlated pairs; the block
   bootstrap by calendar day is a partial correction, not a solution.
5. **The risk envelope is correctly calibrated.** `risk_reference_balance_quote` 300 matches the
   available 300,40, so the daily loss limit is 3,00% of real capital, the per-coin cap 54,93% and the
   portfolio cap 94,87% — each within 0,13 pp of its stated intent. Expected peak exposure is ~128 USD
   (42,7%). Within a single day the bot's own 9,00 USD limit binds first; across days the −25,00 USD
   `ABORT-DRAWDOWN` is the guard.
