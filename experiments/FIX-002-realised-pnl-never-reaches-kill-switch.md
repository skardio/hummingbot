# FIX-002 — realised PnL never reaches the kill switch

| | |
|---|---|
| Discovered by | EXP-2026-10-KRAKEN-USD-001 impact analysis |
| Severity | **Critical** — the kill switch cannot fire; the daily loss limit is unenforced |
| Priority | **P1** (before FIX-001) |
| Status | **Design — implementation follows** |

---

## 1. Root cause, proven

### 1.1 The dead block

[`_sync_risk_state()`](../multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L6865)
lines 6904–7320 drive four safety mechanisms, all gated on a single condition:

```python
for executor in self.executors_info:
    if executor.status == RunnableStatus.TERMINATED:        # never true in practice
        if executor.id not in self._realised_executors_tracked:
            realised_pnl = Decimal(str(executor.net_pnl_quote))
```

| Line | Mechanism | State |
|---|---|---|
| 6919–6930 | `PHANTOM_LOSS_FIX` | unreachable |
| 7067 | `drawdown_tracker.record_trade_pnl()` | unreachable |
| 7095–7110 | `T1-K1` — feeds `pnl_tracker_v2` → kill switch | unreachable |
| 6931–6960 | trade label persistence | unreachable |
| 7306 | `risk_manager.register_close_trade()` | unreachable |

### 1.2 The lifecycle, step by step

The running script is **`multi_coin_grid_pro/scripts/multi_coin_grid_v2_usd.py`** (inode 3708436),
not `scripts/multi_coin_grid_v2_usd.py` (inode 2890321). Line 69 of the running script:

```python
closed_executors_buffer: int = 0      # ST-06b: crash-safe immediate persistence
```

With that value, inside a single synchronous `StrategyV2Base.on_tick()`:

```
on_tick()                                     strategy_v2_base.py:339
 ├─ update_executors_info()                   :340
 │    controller.executors_info = snapshot from active_executors
 │    (the TERMINATED executor is still present here)
 ├─ determine_executor_actions()               :343
 │    └─ store_actions_proposal()              :369
 │         len([is_done]) > 0  → TRUE because buffer == 0
 │         → StoreExecutorAction for EVERY done executor
 └─ execute_action()                           :345
      └─ store_executor()                      executor_orchestrator.py:619
           ├─ MarketsRecorder.store_or_update_executor()   → row lands in the DB
           └─ active_executors[cid].remove(executor)        :642
```

The controller runs in a **separate async loop**
([`control_task()`](../hummingbot/strategy_v2/controllers/controller_base.py#L171)), gated on
`executors_update_event`. To observe the executor it must read `executors_info` inside the
millisecond window between `update_executors_info()` and `store_executor()` within the same tick.

### 1.3 Empirical confirmation

| Measurement | Value |
|---|---|
| Closed executors during the run | 4 |
| Log rotations inspected | 32 (full 2-day run) |
| `determine_executor_actions` reached (`Selected coin`) | 1462 |
| `T1-K1` markers | **0** |
| `PHANTOM_LOSS_FIX` markers | **0** |
| `Trade label` markers | **0** |
| `🧹 Cleanup: Removed` markers | **0** |

Every executor reached the database, so `store_executor()` ran every time. The controller observed
none of them.

### 1.4 The irony

`closed_executors_buffer = 0` is a deliberate crash-safety decision (ST-06b, and a hard rule in the
repository instructions: *"executors are written to DB within one tick of closing"*). That choice
is correct on its own terms, and it is what silently killed the kill switch. The framework default
of 100 would have kept closed executors visible — which is why
`multi_coin_grid_pro/tests/unit/test_executors_buffer.py` asserts the override, unaware of the
side effect.

### 1.5 One physical file

The controller is a **symlink**: `hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py`
and `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` share inode 3728277. No
dual-file sync is required. The two *scripts* are genuinely separate files; only the
`multi_coin_grid_pro` one runs.

---

## 2. Design

### 2.1 Principle

**Realised PnL must be delivered exactly once per executor, from a source that cannot disappear,
and must survive a restart without double counting.**

Three pieces:

| Piece | Responsibility |
|---|---|
| `RealisedPnlLedger` | Durable, atomic, idempotent claim on an executor id |
| `process_realised_executor()` | The existing logic, extracted from the dead block |
| Deterministic delivery | A hook that fires before the executor is removed, plus the existing loop as a fallback |

### 2.2 `RealisedPnlLedger`

New file `multi_coin_grid_pro/persistence/realised_pnl_ledger.py`, following the established
pattern of `cooldown_store.py` and `entry_price_store.py`.

```sql
CREATE TABLE IF NOT EXISTS realised_pnl_processed (
    executor_id     TEXT PRIMARY KEY,
    controller_id   TEXT,
    trading_pair    TEXT,
    close_timestamp INTEGER,
    realised_pnl    TEXT,          -- Decimal as string, never float
    processed_at    INTEGER
);
```

```python
def claim(executor_id, ...) -> bool:
    """Atomically claim an executor. True only for the first caller, ever."""
```

`INSERT OR IGNORE` on a `PRIMARY KEY` makes the claim atomic within SQLite. A second caller — in
the same tick, a later tick, or after a restart — receives `False` and skips.

### 2.3 `process_realised_executor(executor_info) -> bool`

Extracted verbatim from lines 6904–7320, with the gating conditions removed. Order of operations
is preserved exactly:

1. Read `realised_pnl` from `net_pnl_quote`
2. Apply `PHANTOM_LOSS_FIX` when `close_type == FAILED` and `sell < buy`
3. Persist the trade label
4. `drawdown_tracker.record_trade_pnl()`
5. `T1-K1` — synthesise fills, feed `pnl_tracker_v2`
6. `risk_manager.register_close_trade()`
7. Record in `_realised_executors_tracked` (in-memory cap stays)

The ledger claim happens **first**. If the claim fails, the method returns `False` immediately and
touches nothing.

### 2.4 Delivery path

**Primary — deterministic.** The running script overrides `store_actions_proposal()`. At that
moment the executor is still in `get_all_executors()` and is guaranteed to be about to disappear:

```python
def store_actions_proposal(self):
    actions = super().store_actions_proposal()
    for action in actions:
        controller = self.controllers.get(action.controller_id)
        info = self._find_executor_info(action.executor_id)
        if controller is not None and info is not None:
            controller.process_realised_executor(info)      # exactly-once via the ledger
    return actions
```

**Fallback — the existing loop stays.** Lines 6904+ keep running. With the ledger in place it can
only ever be a no-op or a genuine catch of something the primary path missed. Keeping it costs
nothing and covers framework changes.

### 2.5 Restart behaviour

The ledger is durable, so a restart cannot double count. It must also not replay history: on
startup the ledger is only consulted, never bulk-processed. Executors closed while the bot was
down are **not** retroactively fed to the kill switch — `pnl_tracker_v2` is in-memory and resets on
restart anyway, so replaying them would corrupt the daily window rather than restore it.

That is a deliberate limitation, recorded in section 5.

### 2.6 Explicitly out of scope

- No change to trading strategy logic, entry/exit decisions or order placement.
- No change to `closed_executors_buffer` — crash safety stays as it is.
- No change to `tools/evidence/`.
- No retroactive database repair.

---

## 3. Test plan

### FIX-002

| # | Test | Asserts |
|---|---|---|
| 1 | `test_terminated_executor_feeds_pnl_tracker_once` | tracker receives the PnL exactly once |
| 2 | `test_repeated_sync_does_not_double_count` | second call is a no-op |
| 3 | `test_restart_does_not_double_count` | a fresh ledger instance on the same file still refuses |
| 4 | `test_multiple_closed_executors_processed` | each id processed once, none skipped |
| 5 | `test_negative_pnl_reaches_daily_loss_path` | `daily_pnl_pct()` goes negative; the guard can trip |
| 6 | `test_positive_pnl_updates_tracker` | sign handled correctly |
| 7 | `test_drawdown_tracker_receives_same_pnl` | both consumers see an identical value |
| 8 | `test_phantom_loss_correction_applies` | FAILED + sell < buy → `-fees`, not `-(buy+fees)` |

### FIX-001

| # | Test | Asserts |
|---|---|---|
| 1 | `test_cancelled_partial_sell_counted` | proceeds enter `realized_sell_size_quote` |
| 2 | `test_cancelled_partial_buy_counted` | same on the buy side |
| 3 | `test_zero_fill_cancel_ignored` | nothing archived |
| 4 | `test_repeated_cancel_does_not_double_count` | archived once |
| 5 | `test_xdc_scenario_classifies_as_matched` | the real case becomes `MATCHED_EXACT` with positive PnL |

---

## 4. Verification before EXP-002

1. Full relevant test suite green; `flake8` clean.
2. Replay XDC-USD and both PEPE cases through the Evidence Engine.
3. Demonstrate the kill switch actually receives PnL.
4. Synthetic loss test in which `RiskGuardV2` demonstrably trips.
5. Restart/dedup test.
6. Full Evidence Engine run over history.
7. Record the new commit hash.

---

## 5. Known limitations after the fix

1. **Executors closed while the bot is down are not replayed.** `pnl_tracker_v2` is in-memory and
   resets on restart; the daily loss window restarts with the bot. Pre-existing behaviour, not
   introduced here.
2. **The in-memory `_realised_executors_tracked` cap stays.** The durable ledger is the real dedup;
   the in-memory dict remains only for the existing reporting logic.
3. **The ledger grows unbounded.** One row per closed executor. At the observed rate (~4/day) that
   is negligible, but it is not pruned.
