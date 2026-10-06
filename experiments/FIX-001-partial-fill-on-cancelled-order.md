# Fix proposal — partial fills on cancelled orders are not counted

| | |
|---|---|
| Discovered by | EXP-2026-10-KRAKEN-USD-001, aborted after 2.0 days |
| Severity | **High** — corrupts realised PnL, can invalidate any measurement |
| Related | **FIX-002 (kill switch not fed)** — discovered during the impact analysis, see section 5 |
| Status | **Proposed, not implemented** |
| Blocks | EXP-2026-10-KRAKEN-USD-002 |

---

## 1. The defect

When a sell order is **partially filled and then cancelled**, the executed portion is
discarded from the executor's books. The matching purchase stays, so the executor reports
a loss equal to the unsold notional.

### Evidence — XDC-USD, 2026-10-06

```
order 461474338   qty = 2020.6411 XDC   filled = 999.9440 XDC ($33.45)   status = OrderCancelled
                  -> recorded in _canceled_orders only
```

| | Ground truth (`TradeFill`) | Booked by executor |
|---|---|---|
| Bought | 2020.6410 XDC / $67.0752 | $67.08 |
| Sold | 2020.6411 XDC / $67.5394 | $34.09 |
| Residual | −0.0001 XDC | 999.94 XDC |
| **Result** | **+$0.4642 profit** | **−$33.3897 loss** |

Accounting error: **−$33.85** on a single trade.

### Why it happens

[`process_order_canceled_event`](../hummingbot/strategy_v2/executors/grid_executor/grid_executor.py#L4507)
(lines 4507–4548) appends only the order id and resets the level:

```python
for level in levels_close_order_placed:
    if event.order_id == level.active_close_order.order_id:
        self._canceled_orders.append(level.active_close_order.order_id)   # fill discarded
        self.max_close_creation_timestamp = 0
        level.reset_close_order()
```

And [`update_realized_pnl_metrics`](../hummingbot/strategy_v2/executors/grid_executor/grid_executor.py#L4836)
(lines 4849–4866) sums exclusively from `_filled_orders`:

```python
self.realized_sell_size_quote = sum([
    Decimal(order["executed_amount_quote"])
    for order in regular_filled_orders if order["trade_type"] == TradeType.SELL.name
])
```

A precedent already exists for the *fully* filled close order at line 2306
(`"Archive the filled close order so its sell data is preserved"`), but it is guarded by
`in_flight_order.is_done` and therefore never fires for a cancelled partial.

### Historical exposure

Across the full Kraken USD history, 3 of the 14 `UNMATCHED_BUY` / `PARTIAL_OPEN` executors
carry sell fills on cancelled orders that were never counted:

| Pair | Booked | Unaccounted proceeds |
|---|---|---|
| PEPE-USD | −56.02 | $57.16 |
| PEPE-USD | −0.21 | $53.90 |
| XDC-USD | −33.39 | $33.45 |
| | | **$144.51** |

This supersedes the "terminal-fill race" hypothesis from the Part A investigation, which was
inferred from timestamps rather than from order state. The other 11 executors show no fills on
cancelled orders and remain unexplained — they are a separate problem.

---

## 2. Proposed change

**One principle: an executed quantity is never discarded, regardless of the order's final status.**

In `process_order_canceled_event`, before appending to `_canceled_orders`, archive any order
that carries an executed amount — mirroring what line 2306 already does for the filled case.

Sketch (not applied):

```python
def _archive_partial_fill(self, order) -> bool:
    """Preserve an executed amount from an order that is being cancelled.

    A cancelled order can still carry a partial fill. Dropping it removes the
    proceeds from realised PnL while the matching purchase remains, which books
    the unsold notional as a loss (XDC-USD 2026-10-06: -33.39 booked, +0.46 real).
    """
    if order is None or order.executed_amount_base <= Decimal("0"):
        return False
    payload = order.to_json()
    if any(o.get("client_order_id") == payload.get("client_order_id")
           for o in self._filled_orders):
        return False                      # already archived; never double count
    self._filled_orders.append(payload)
    self.logger().info(
        f"📥 PARTIAL_FILL_ARCHIVED: {self.config.trading_pair} | "
        f"order {order.client_order_id} cancelled with "
        f"{float(order.executed_amount_base):.8f} base executed "
        f"({float(order.executed_amount_quote):.4f} quote) — preserved for PnL"
    )
    return True
```

Call it at each of the three sites that hold an order object:

| Line | Site |
|---|---|
| 4528 | `level.active_open_order` |
| 4533 | `level.active_close_order` |
| 4537 | `self._close_order` |

Line 4546 (`event.order_id` safety net) has no order object; leave it, but log when a cancelled
id is unknown so the gap stays visible.

### Deliberately out of scope

- **No change to the trading decision path.** This only affects bookkeeping.
- **No retroactive database repair.** History stays as it is; the Evidence Engine reclassifies
  from the raw fields.
- **No change to classification or gates** in `tools/evidence/`. The engine is already correct —
  it faithfully reported what the database contained.

---

## 3. Test plan

### New regression tests

1. **`test_cancelled_partial_fill_counted`** — reproduces XDC-USD: buy 2020.64, sell order for
   the full amount partially filled 999.944 then cancelled, remainder sold. Expect
   `realized_sell_size_quote` to include both fills and `net_pnl_quote > 0`.
2. **`test_cancelled_zero_fill_not_archived`** — a cancelled order with no execution must not
   enter `_filled_orders`.
3. **`test_no_double_count_on_repeat_cancel`** — the same order cancelled twice archives once.
4. **`test_open_order_partial_cancel_counted`** — same mechanism on the buy side.
5. **`test_classification_after_fix`** — the XDC fixture classifies as `MATCHED_EXACT`
   instead of `PARTIAL_OPEN`.

### Must stay green

- `multi_coin_grid_pro/tests/unit/test_stale_close_order_fix.py`
- `multi_coin_grid_pro/tests/unit/test_zombie_close_guard_fix.py`
- `multi_coin_grid_pro/tests/unit/test_grid_executor_phantom_pnl_fix.py`
- `test/hummingbot/strategy_v2/executors/grid_executor/test_grid_executor.py`
- `tests/evidence/` (110 tests) — untouched, but confirm

---

## 4. Verification before EXP-002

1. `flake8` clean on the changed file; full test suite green.
2. Replay the three historical cases and confirm the engine now sees their proceeds.
   Expect the Kraken `operational_share` to drop materially.
3. Recompute the config fingerprint. **The fix changes code, not config, so the fingerprint
   should be unchanged** — verify rather than assume.
4. Run the engine over the full history and record the new class distribution as the starting
   point for the EXP-002 contract.
5. Only then freeze EXP-002.

---

## 5. Impact analysis — answered 2026-10-06

**The question was: does the mis-booked PnL feed back into trading decisions, or only into
reporting? The answer turned out to be neither, and the finding is worse than the original bug.**

### 5.1 The consumers

`executor.net_pnl_quote` is read in exactly one place that matters for safety:
[`_sync_risk_state()`](../multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L6865),
lines 6904–7115, inside:

```python
for executor in self.executors_info:
    if executor.status == RunnableStatus.TERMINATED:
        if executor.id not in self._realised_executors_tracked:
            realised_pnl = Decimal(str(executor.net_pnl_quote))
```

That block drives four safety mechanisms:

| Line | Mechanism |
|---|---|
| 6919–6930 | `PHANTOM_LOSS_FIX` — corrects exactly the defect described above |
| 7067 | `drawdown_tracker.record_trade_pnl()` |
| 7095–7110 | `T1-K1` — feeds the kill-switch PnL tracker with synthesised fills |
| 6931–6960 | trade label persistence |

### 5.2 The block never executes

`_sync_risk_state()` is called unconditionally from `determine_executor_actions()` (line 4144),
which demonstrably runs: `Selected coin` appears **1462** times in the logs.

Yet across **32 log rotations covering the full 2-day run, with 4 executors closed**, every log
marker inside that block appears **zero** times:

| Marker | Occurrences |
|---|---|
| `T1-K1` | **0** |
| `PHANTOM_LOSS_FIX` | **0** |
| `Trade label` | **0** |
| `🧹 Cleanup: Removed` (same method, earlier loop) | **0** |

The controller never observes an executor in `TERMINATED` state. `executors_info` is populated
from `executor_orchestrator.get_executors_report()`, which builds from `active_executors`; a
closed executor is removed from that list in `store_executor()` (line 642) after being written to
the database.

*Uncertain:* `closed_executors_buffer` resolves to the framework default of 100 for this script,
which should keep closed executors visible for a while. The empirical result contradicts that, so
the precise mechanism is not fully pinned down. **The fact is established; the explanation is not.**

### 5.3 Consequences

1. **The kill switch is not fed.** `pnl_tracker_v2.daily_pnl_pct()` stays at 0%, so
   `RiskGuardV2.check_limits()` can never trigger on daily, weekly or monthly loss. This is the
   exact finding from the original four-round review — recorded as fixed under T1-K1 — reproduced
   live. The remediation exists in code but does not execute.
2. **`PHANTOM_LOSS_FIX` never fires.** A correction for this very defect was already written and
   sits unreachable. Had it run on XDC-USD, `realised_pnl` would have been corrected to `-fees`
   for risk purposes.
3. **The drawdown tracker receives no realised PnL**, so the contract's `ABORT-DRAWDOWN` guard
   would not have been enforced by the bot either — only by the external monitor.
4. **Trading decisions are NOT polluted.** Because the block never runs, the phantom loss never
   propagates. The original concern is void: this is a reporting defect in the executor and a
   *dead safety path* in the controller, not a corrupted decision loop.

### 5.4 Consequence for sequencing

FIX-001 as proposed is **correct but insufficient on its own**. Fixing the executor's bookkeeping
makes the database truthful; it does not revive the kill switch. The dead safety path is the more
serious of the two and should be addressed first, or at least alongside.

Proposed split:

- **FIX-001** (this document) — count partial fills on cancelled orders. Restores measurement.
- **FIX-002** (to be written) — make realised-PnL propagation independent of observing
  `TERMINATED` in `executors_info`. Restores the kill switch, the drawdown tracker and
  `PHANTOM_LOSS_FIX`.

Neither should be implemented before the operator has decided on sequencing, and the bot is
currently running live with an unfed kill switch.
