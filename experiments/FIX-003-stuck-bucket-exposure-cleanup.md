# FIX-003 — stuck bucket/budget/active-coin exposure never released

| | |
|---|---|
| Discovered by | External (Codex) investigation into "bot running for days with few trades" |
| Verified by | Independent log/code inspection (not just trusting the external report) |
| Severity | **Critical** — bucket exposure caps freeze permanently, blocking all new entries indefinitely |
| Priority | P3 (after FIX-001 / FIX-002) |
| Status | **Implemented** |
| Scope | All five bot variants (Kraken EUR, Kraken USD, Bitget spot, Bitget futures, OKX spot) |

---

## 1. Root cause, proven

### 1.1 Same disease, second limb

[`_sync_risk_state()`](../multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L6959)
contained **two** blocks gated on the same dead condition. FIX-002 fixed one of them (realised
PnL → kill switch / drawdown tracker / PHANTOM_LOSS_FIX / trade labels). The other — the
"🔧 CLEANUP: Remove terminated/failed executors from active_coins" block, which releases
`active_coins`, `budget_allocator` reservations, `bucket_tracker` exposure and
`price_history_for_volatility` — was left untouched:

```python
for executor in self.executors_info:                     # never TERMINATED, same reason as FIX-002
    status_name = ...
    if position_tracking_cleanup_allowed(status_name, executor.is_active):
        self._clear_position_tracking_after_confirmed_close(...)
        ...
        self.budget_allocator.release(executor.id)
        self.bucket_tracker.clear_coin(trading_pair)
```

The lifecycle proof from FIX-002 §1.2 applies unchanged: with `closed_executors_buffer = 0`, the
orchestrator removes a closed executor from `active_executors` within the same tick that publishes
the `executors_info` snapshot to the controller's separate async loop, so this loop's
`executor.status == TERMINATED` condition effectively never matches.

### 1.2 Empirical confirmation (independently re-verified, not just taken from the external report)

| Measurement | Value |
|---|---|
| `🧹 Cleanup: Removed` log lines since the Oct 7 restart | **0** (99 log rotations inspected) |
| `ILLIQUID` bucket exposure | stuck at `44.7%` from shortly after restart through **Oct 14, 13:35:16** (latest log at time of check) |
| Open executors in DB since restart | 0 |
| Active slots reported | `0/3 slots used` |
| New entries since restart | 0 for 5+ consecutive days despite 8–12 candidates/day surviving the ATR filter |

A bucket that reports non-zero exposure with zero open executors can only be explained by the
exposure never being released after the executor(s) that produced it closed.

### 1.3 `_clear_position_tracking_after_confirmed_close()` has exactly one caller

[`_clear_position_tracking_after_confirmed_close()`](../multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L6455)
is called from nowhere except the dead block above. There is no other code path that releases
`budget_allocator` / `bucket_tracker` state for a closed executor.

### 1.4 Scope: affects every derived bot, automatically fixed by one file

`SpotGridBitgetController`, `FuturesGridBitgetController` and `SpotGridOKXController` all inherit
from `MultiCoinGridController` and do not override `_sync_risk_state()` — confirmed by
`cls.__dict__` introspection in the test suite (§4). The three live scripts
(`spot_grid_bitget.py`, `futures_grid_bitget.py`, `spot_grid_okx.py`) all subclass
`MultiCoinGridStrategyV2` from `multi_coin_grid_pro/scripts/multi_coin_grid_v2.py`, the exact file
already carrying the FIX-002 `store_actions_proposal()` hand-over — so they already deliver
candidates through `enqueue_realised_executor()` with zero script changes required. Fixing the one
shared controller file fixes all five variants.

### 1.5 Open question, not resolved and not asserted either way

Whether commit `e07679ec3` (FIX-001/FIX-002) *introduced* this specific regression, or whether the
cleanup block was already just as dead before that commit (same `closed_executors_buffer = 0`
condition, which predates FIX-002), is **not established**. Both blocks shared the identical
`self.executors_info` scan before FIX-002 touched anything, so the prior-art evidence points at
"always dead", but this has not been independently proven with pre-FIX-002 logs and is not claimed
as fact here.

---

## 2. Design

### 2.1 Principle

Reuse the exact mechanism FIX-002 already built, rather than inventing a second one.
`_collect_realised_candidates()` already answers "which closed executors have not yet had their
one-time side effects applied, in a restart-safe, exactly-once way" — the cleanup block needs
precisely the same answer. Treating PnL propagation and bucket/budget release as two *consumers of
one event* (an executor closing) rather than two independently-gated blocks removes the whole bug
class, not just one instance of it.

### 2.2 Change

`_sync_risk_state()` now calls `self._collect_realised_candidates()` **exactly once** per tick,
stores the result in a local variable, and both the cleanup loop and the PnL loop iterate that same
list:

```python
realised_candidates = self._collect_realised_candidates()

for executor in realised_candidates:        # cleanup (FIX-003)
    if position_tracking_cleanup_allowed(...):
        ...

for executor in realised_candidates:        # PnL (FIX-002, unchanged)
    if executor.id not in self._realised_executors_tracked:
        ...
```

Calling `_collect_realised_candidates()` twice would be wrong: it pops
`_pending_realised_executors` and consults the durable ledger, so a second call in the same tick
would see an empty pending queue and a ledger that already recorded the claim — silently starving
the cleanup loop. The fix depends on a single call shared by both consumers.

### 2.3 Why gating cleanup on the ledger claim (not just on `TERMINATED`) is the safe direction

Before this fix, the cleanup block had no ledger gating at all — it was purely
`executors_info`-driven and (in principle, had it ever fired) could have run on every tick for as
long as a stale executor lingered in the snapshot. After this fix, cleanup only fires when
`_collect_realised_candidates()` returns the executor, i.e. when the realised-PnL ledger claim
succeeds. This is deliberately asymmetric-safe: if the claim cannot be confirmed (ledger error,
duplicate delivery, restart race), the executor's slot stays marked occupied rather than being
released. A missed release is a lost trading opportunity (recoverable); an incorrect release would
let a new position open into exposure that is not actually free (not recoverable after the fact).

### 2.4 Scope boundaries, deliberately not touched

* The dead block's inline re-implementation of `active_coins` / `budget_allocator` /
  `bucket_tracker` / `price_history_for_volatility` cleanup, which **duplicates** what
  `_clear_position_tracking_after_confirmed_close()` already does immediately above it in the same
  loop body — pre-existing redundancy, left as-is. Removing it is a separate, unrelated
  simplification and out of scope for this fix.
* No trading-strategy logic changed. No script changes required (see §1.4).
* No change to `RealisedPnlLedger` itself — reused exactly as built for FIX-002.

---

## 3. Implementation

Single file changed: `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` (symlinked
with `hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py`, same inode — no
dual-file sync needed). `_sync_risk_state()`:

* `realised_candidates = self._collect_realised_candidates()` called once, before both loops.
* Cleanup loop now iterates `realised_candidates` instead of `self.executors_info`.
* PnL loop (FIX-002) now iterates `realised_candidates` instead of calling
  `self._collect_realised_candidates()` a second time.
* All inner logic of both loops preserved verbatim — this is a source-list change only.

---

## 4. Tests

New file `multi_coin_grid_pro/tests/unit/test_fix003_bucket_cleanup_delivery.py`:

| Test | Proves |
|---|---|
| `test_cleanup_releases_active_coins_budget_and_bucket_exactly_once` | A closed executor releases `active_coins`, `budget_allocator`, `bucket_tracker`, `price_history_for_volatility` |
| `test_repeated_sync_does_not_double_release` | A second `_sync_risk_state()` tick for the same executor does not re-release |
| `test_restart_does_not_double_release` | A fresh controller instance backed by the same ledger file (simulated restart) does not re-release |
| `test_multiple_closed_executors_each_cleaned_up_once` | Two distinct closed executors are each cleaned up exactly once |
| `test_explicit_handover_also_drives_cleanup` | The FIX-002 `enqueue_realised_executor()` hand-over path (not just the `executors_info` fallback) drives cleanup |
| `test_running_executor_is_not_cleaned_up` | A still-`RUNNING` executor is never cleaned up |
| `test_ledger_claim_failure_blocks_cleanup_as_well_as_pnl` | Fail-closed applies uniformly: a failed ledger claim blocks both cleanup and PnL propagation |
| `test_single_collection_call_per_tick` | `_collect_realised_candidates()` is called exactly once per tick; both loops consume the same result |
| `TestFix003AppliesToAllDerivedControllers::test_no_derived_controller_overrides_sync_risk_state` | Structural proof: Bitget spot/futures and OKX controllers use the identical, now-fixed `_sync_risk_state()` |

Regression coverage (unchanged, re-run to confirm no interference): all FIX-002 tests
(`test_fix002_realised_pnl_delivery.py`, `test_fix002_kill_switch_end_to_end.py`) and the CA5
`_sync_risk_state()` tests in `test_ca1_ca2_ca5_verification.py`, since they exercise the same
method and the same `_call_sync()` harness.

---

## 5. Verification results

| Check | Result |
|---|---|
| `flake8` on changed files | clean |
| New FIX-003 tests | 9 passed |
| FIX-001/FIX-002/ledger/CA5 regression tests (76 total) | all passed |
| Full `multi_coin_grid_pro/tests/` suite | 2702 passed, 8 skipped, 17 xfailed, 3 xpassed (pre-existing, unrelated to this change), 0 failed |
| `tests/evidence/` suite | 110 passed (unaffected — no evidence-engine files touched) |

No bot was started or stopped as part of this work.
