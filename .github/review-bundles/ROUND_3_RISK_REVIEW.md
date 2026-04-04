# Round 3: Risk Management & Safety Review

**Reviewer role:** Trading Risk Engineer — crypto market makers, prop desks, worst-case analysis
**Date:** 2026-03-12
**Scope:** RiskGuardV2, ProfessionalRiskManager, SmartEntryFilter, FuturesGridRiskGuard, DrawdownTracker, production configs, and data snapshot (2026-03-08)
**Risk Score: 1.5 / 10**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Risk Score Justification](#2-risk-score-justification)
3. [The Fundamental Flaw: Dead Kill Switch](#3-the-fundamental-flaw-dead-kill-switch)
4. [Catastrophic Scenario Playbook](#4-catastrophic-scenario-playbook)
5. [Missing Safeguards (Ranked)](#5-missing-safeguards-ranked)
6. [Recommended Risk Parameters](#6-recommended-risk-parameters)
7. [Recovery Gaps](#7-recovery-gaps)
8. [Risk Architecture Verdict](#8-risk-architecture-verdict)
9. [Edge Cases in the Risk Chain](#9-edge-cases-in-the-risk-chain)
10. [What to Keep](#10-what-to-keep)
11. [Capital Scaling Verdict](#11-capital-scaling-verdict)
12. [Confidence Classification](#12-confidence-classification)

---

## 1. Executive Summary

**The bot's primary kill switch — `RiskGuardV2` — is structurally incapable of firing.** Its data source (`RealtimePnLTracker`) is initialized but never receives trade fills or unrealized PnL updates. The `daily_pnl_pct()` method always returns ~0%. The kill switch will never activate, regardless of actual losses.

This single finding renders the entire risk control system decorative. The bot has been running live for ~14 months (since November 2024) with a daily loss limit that cannot trigger.

The data confirms this: **−€229 cumulative loss across all 4 bot instances**, with the futures bot losing −310% in 9 days — and no kill switch fired. The "temporary" 30% daily loss limit (set February 2025, still active March 2026) is irrelevant because the check cannot detect any loss.

Beyond the dead kill switch:
- All risk checks are **fail-open** (exceptions = continue trading)
- The kill switch does not close existing positions or cancel open orders
- Stop-loss is **disabled** on spot; 3 of 6 futures guards are permanently disabled
- No correlation risk monitoring (hardcoded to 0.0)
- No high-water-mark drawdown protection
- No post-emergency-exit cooldown
- Reconciliation is detect-only, not auto-remediate
- The `ProfessionalRiskManager`'s win rate and dead liquidity tracking are never fed data

**This system has no functional safety net against capital loss.**

---

## 2. Risk Score Justification

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| **Kill switch effectiveness** | 0 | 30% | 0.00 |
| **Position-level protection** | 2 | 20% | 0.40 |
| **Fail-closed behavior** | 0 | 15% | 0.00 |
| **Recovery / reconciliation** | 2 | 10% | 0.20 |
| **Entry filter quality** | 5 | 10% | 0.50 |
| **Observability during risk events** | 4 | 10% | 0.40 |
| **Futures-specific safeguards** | 1 | 5% | 0.05 |
| **Weighted total** | | | **1.55 → 1.5** |

**Why not 0:** The SmartEntryFilter is genuinely functional and has prevented some bad entries. The Telegram alerting for orphaned positions exists. The DrawdownTracker, while fail-open, at least executes its check.

**Why not higher:** Zero functional kill switch. Fail-open on all risk paths. No cancel-all. No correlation monitoring. Stop-loss disabled. Three futures guards disabled. "Temporary" 30% limit unchanged for 13 months. -€229 confirmed losses with no safety trigger.

---

## 3. The Fundamental Flaw: Dead Kill Switch

### Evidence

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `RealtimePnLTracker` never receives data | `on_trade_fill()` and `update_unrealized()` are never called from the controller. Only callers are docstring example and test file. | **Kill switch permanently inert** — PnL always reads 0% | Wire executor fill events to `pnl_tracker_v2.on_trade_fill()` | ✅ High |
| `RiskGuardV2.check_limits()` always returns True | With daily/weekly/monthly PnL at 0%, no threshold is ever breached | Bot trades through any loss level with no intervention | Fix PnL tracker OR replace with balance-based detection | ✅ High |
| "Temporary" 30% daily limit since Feb 2025 | Comment: `TIJDELIJK: Verhoogd naar 30% vanwege PnL tracking bug (20250214)` in all 4 YAML files | Even if kill switch worked, 30% daily loss would need a catastrophic crash to trigger | Reduce to 3-5% once PnL tracking works | ✅ High |
| Data confirms kill switch never fired | −€73 on Kraken EUR over 77 days, −$155 on futures in 9 days — no kill switch activation in any log | Kill switch is confirmed non-functional in production | N/A — data proves the code finding | ✅ High |

### The Chain of Failure

```
RealtimePnLTracker          RiskGuardV2.check_limits()
     .on_trade_fill()  ──✗── never called
     .update_unrealized() ──✗── never called
     .daily_pnl_pct() ─────→ always 0%
                                  │
                                  ├── daily_pct (0%) > -30%?  → True (OK)
                                  ├── weekly_pct (0%) > -7%?  → True (OK)
                                  ├── monthly_pct (0%) > -10%? → True (OK)
                                  └── returns True → trading continues
```

The `DrawdownTracker` at L3892 is a separate path and DOES get fed `current_balance` from the connector. However, it is called inside `determine_executor_actions()` (L3892), not in `control_task()`, and catches exceptions with fail-open behavior.

### Impact on All Other Risk Findings

Because the kill switch is dead, every other risk gap in this review is compounded. There is **no backstop** — if entry filters fail, if positions go bad, if the market crashes, the bot keeps trading.

---

## 4. Catastrophic Scenario Playbook

### Scenario 1: Flash Crash (−30% in 5 Minutes)

| Phase | What SHOULD Happen | What ACTUALLY Happens |
|-------|-------------------|----------------------|
| T+0 | Kill switch detects rapid loss | Kill switch sees 0% loss (PnL tracker dead) |
| T+0 | Cancel all open orders | No cancel-all mechanism exists |
| T+1min | Emergency exit at −12% fires | `should_exit_position()` at L8806 uses **raw price** (fee bug: L8806 discarded expression). Emergency exit fires when price ≤ entry × 0.88 |
| T+2min | Position closed, coin blacklisted | Position closed, but **NO cooldown** — `note_exit()` does not set `session_blacklist`. Bot can re-enter same coin next cycle |
| T+3min | Bot paused, Telegram alert sent | Bot continues trading. Grid executors for other coins remain live on exchange. SmartEntryFilter may block re-entry via RSI/ATR checks, but this is not guaranteed |
| T+5min | Portfolio protected at −12% per coin | With 4 concurrent coins at −12% each (worst case), **−48% portfolio loss**. No kill switch fires. DrawdownTracker may catch it at next `determine_executor_actions()` call — IF balance check doesn't error (fail-open) |

**Worst case with current controls:** 4 coins × −15% (hard stop) = **−60% portfolio loss** before any circuit breaker has a chance to fire. If hard stop also fails (exchange down), losses are unbounded up to margin/balance.

### Scenario 2: Exchange API Down for 30 Minutes During Open Positions

| Phase | What SHOULD Happen | What ACTUALLY Happens |
|-------|-------------------|----------------------|
| T+0 | Detect connectivity loss, halt new orders | `_handle_api_error()` at L957 counts errors, exponential backoff up to 300s. After `max_total_errors`, sets `permanent_api_failure` |
| T+5min | Alert operator | Telegram alert sent (via `_handle_api_error`) ✅ |
| T+30min | On reconnect, reconcile state | `_reconcile_external_fills()` checks balance vs reference. If balance ≥ 95% of reference, **resets tracked losses** as "likely tracking error" — even if actual losses occurred during outage. No order/position reconciliation |
| Risk | Positions may have been liquidated or stopped on exchange side | Bot has no knowledge of what happened. Exchange-side TPSL (futures only) provides some protection. Spot has no exchange-side stops |

**Critical gap:** No exchange-side stop-loss orders on spot. All protection is bot-side. If bot is disconnected, spot positions are completely unprotected.

### Scenario 3: Bot Crash and Restart with 6 Active Grids

| Phase | What SHOULD Happen | What ACTUALLY Happens |
|-------|-------------------|----------------------|
| Restart | Load open orders from exchange | Not implemented — `on_start()` does not load exchange orders |
| Restart | Reconcile positions with exchange | `_detect_orphaned_positions()` **detects** coins in wallet, sends Telegram alert: "Consider manually selling" — no auto-action |
| Restart | Reconcile/cancel stale orders | Stale order detection exists but is **alert-only** — no auto-cancel |
| Restart | Restore entry prices for risk calc | Entry prices are **lost** — they are in-memory only (no persistence). `should_exit_position()` at L8803 uses `self.entry_prices.get()` which returns None for all coins after restart |
| Restart | Wait for warmup | No warmup gate — `on_start()` completes, trading starts immediately |
| Result | Bot creates NEW grids while old ones still have open orders on exchange | **Double exposure**: old exchange orders still live + new bot orders = up to 2× intended position size |

**Worst case:** 6 orphaned grids with open orders + 6 new grids = up to 12× intended maximum positions. Budget allocator may prevent some of this, but exchange orders are invisible to it.

### Scenario 4: Correlated Dump (All 6 Coins Drop Simultaneously)

| Factor | Current Protection | Gap |
|--------|-------------------|-----|
| Correlation monitoring | Hardcoded to 0.0 at L5661: `correlation_risk_score=0.0` | **No correlation check** |
| Position limit | 4–6 concurrent coins (config) | Still allows full exposure to correlated assets |
| Portfolio max exposure | 80% per config | 4 coins × 80% = 320% theoretical, limited by balance |
| Emergency exit | −12% per coin | 4 × −12% = −48% portfolio |
| Kill switch | Dead (PnL tracker unfed) | No backstop |

**Worst case:** Single market event (e.g., regulatory news) hitting all altcoins simultaneously → all 4 positions hit emergency exit → −48% portfolio in one event with no kill switch response.

### Scenario 5: Partial Fills → Stuck Inventory Across Multiple Coins

| Factor | Current Protection | Gap |
|--------|-------------------|-----|
| Stuck order detection | `_cleanup_stale_orders()` at L1795 | **Alert-only, no auto-cancel** |
| Budget impact | Stuck orders lock capital on exchange | Bot detects "insufficient capital" but cannot free it |
| Data confirms | Bitget Spot: $71 locked by stuck SONIC LIMIT SELL, $3.62 free < $30 minimum | **2 of 3 active bots are capital-blocked** by stuck orders |

**Confirmed production impact:** The data snapshot shows 2 of 3 active bots cannot trade because stuck orders lock their capital. The bot logs the error 368 times ("Insufficient capital: $3.62 < $30.00 minimum") but never auto-cancels the stuck order.

### Scenario 6: Database Corruption During Trading

| Factor | Current Protection | Gap |
|--------|-------------------|-----|
| CooldownStore SQLite | `check_same_thread=False` — no locking | Corruption possible under concurrent writes |
| Executor database | Hummingbot framework SQLite | Separate from custom code |
| State persistence | Only CooldownStore — entry prices, PnL, positions all in-memory | Corruption of CooldownStore = lost cooldowns (low impact) |
| Recovery | No data integrity checks on startup | Corrupted DB loads normally, potentially with invalid data |

**Impact:** Low relative to other risks, because almost nothing is persisted. The real danger is the opposite: too little is persisted, so a restart already loses all state.

---

## 5. Missing Safeguards (Ranked)

Ranked by (financial impact × likelihood × absence severity):

### #1: Functional Kill Switch (CRITICAL)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Kill switch receives no PnL data | `pnl_tracker_v2.on_trade_fill()` never called from controller | Unlimited loss potential — no daily/weekly/monthly cap | Wire fill events OR replace with balance-based kill switch | ✅ High |

**Impact on PnL:** High — eliminates maximum loss boundary
**Impact on safety:** Critical — primary safety layer is non-functional
**Implementation effort:** 2–4 hours to wire fill events; 1 day for balance-based alternative
**Urgency:** **IMMEDIATE** — stop live trading until fixed

### #2: Fail-Closed Risk Checks (CRITICAL)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| RiskGuardV2 check is fail-open | Exception in `check_limits()` propagates; framework retries next tick with no risk check | Risk checks bypassed on any error | Wrap in try/except: `except Exception: return False` (= kill trading on error) | ✅ High |
| DrawdownTracker is fail-open | L3897: `except Exception: # Continue on error` | Drawdown check bypassed on error | Change to: `except Exception: return actions` (= block new trades on error) | ✅ High |

**Impact on PnL:** High when risk system errors coincide with market stress
**Impact on safety:** Critical — the safety system is unsafe against its own failures
**Implementation effort:** 30 minutes
**Urgency:** **IMMEDIATE**

### #3: Kill Switch Must Close Existing Positions (CRITICAL)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Kill switch only prevents new decisions | `control_task()` returns early, `determine_executor_actions()` never called → no `StopExecutorAction` issued | Existing grids keep running with live exchange orders after kill switch | Kill switch must: (1) stop all executors, (2) cancel all open orders, (3) then return | ✅ High |

**Impact on PnL:** High — positions continue accumulating losses after kill switch fires
**Impact on safety:** Critical — kill switch doesn't actually kill
**Implementation effort:** 1 day
**Urgency:** **IMMEDIATE**

### #4: No Post-Stop-Loss / Emergency Exit Cooldown (HIGH)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| No cooldown after emergency exit | `note_exit()` at L3862 only sets `_last_exit_time`, not `session_blacklist` | Bot can re-enter coin that just crashed within one cycle | Add emergency exit coin to session_blacklist with ≥30min cooldown | ✅ High |
| Known incident: "Stop-loss → immediate re-buy" | Failure history table: "Lost money twice on same coin, no cooldown after stop-loss" | Confirmed production loss | Same fix addresses known incident | ✅ High |

**Impact on PnL:** High — doubles/triples loss on crashing coins
**Impact on safety:** High
**Implementation effort:** 2 hours
**Urgency:** **IMMEDIATE**

### #5: Exchange-Side Stop Orders for Spot (HIGH)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| No exchange-side stops on spot | Futures has `exchange_stop_loss_enabled: true`; spot has nothing | If bot disconnects, spot positions have zero protection | Implement OCO/TPSL orders on spot exchanges where supported | 🟡 Medium |

**Impact on PnL:** Potentially total loss during extended outage
**Impact on safety:** High
**Implementation effort:** 3–5 days (exchange API dependent)
**Urgency:** Next sprint

### #6: Correlation Risk Control (HIGH)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Correlation always 0.0 | L5661: `correlation_risk_score=0.0` hardcoded; `calculate_correlation_risk()` never called | All 4 concurrent positions can be in highly correlated altcoins | Implement 24h rolling return correlation, block if avg > 0.7 | ✅ High |

**Impact on PnL:** High during market-wide events
**Impact on safety:** Medium
**Implementation effort:** 2 days
**Urgency:** Next sprint

### #7: High-Water-Mark Portfolio Drawdown (MEDIUM)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Only period-start-based loss tracking | DrawdownTracker uses `daily_start_balance`; no `high_water_mark` field | Intraday peak-to-trough unprotected: $400→$450→$380 = 15.5% drawdown, but tracker sees only 5% | Add peak-equity tracking: if equity drops >X% from all-time or session peak, pause | ✅ High |

**Impact on PnL:** Medium
**Impact on safety:** Medium
**Implementation effort:** 1 day
**Urgency:** Next sprint

### #8: Auto-Cancel Stale Orders on Startup (MEDIUM)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Stale orders detected but not cancelled | `_cleanup_stale_orders()` sends Telegram alert only | Capital locked by orphaned orders → bot cannot trade | Add `cancel_order()` call for stale orders detected on startup after configurable delay | ✅ High |

**Impact on PnL:** Medium (opportunity cost + locked capital)
**Impact on safety:** Medium
**Implementation effort:** 4 hours
**Urgency:** Next sprint — **2 of 3 bots currently blocked by this**

### #9: Persist Entry Prices Across Restart (MEDIUM)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Entry prices lost on restart | `self.entry_prices` is `Dict` in memory, no persistence | `should_exit_position()` cannot compute PnL after restart → positions held indefinitely or exited at wrong time | Persist to SQLite alongside CooldownStore | ✅ High |

**Impact on PnL:** Medium
**Impact on safety:** Medium
**Implementation effort:** 4 hours
**Urgency:** Next sprint

### #10: ProfessionalRiskManager Data Feed (MEDIUM)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `record_fill()` and `record_trade_result()` never called | `position_last_fill_time` always empty; `recent_trades` always empty | Dead liquidity detection (no fills > 45min) inactive; win rate tracking inactive; rolling PnL pause inactive | Wire executor close events to `record_trade_result()` | ✅ High |

**Impact on PnL:** Medium
**Impact on safety:** Medium
**Implementation effort:** 4 hours
**Urgency:** Next sprint

---

## 6. Recommended Risk Parameters

### 6.1 Daily Loss Limit: 3% (Not 30%)

**Math:**

For a €300 spot portfolio with 4 concurrent positions:
- Per-position size: ~€75 (25% of portfolio)
- Emergency exit at −12%: max loss per position = €9
- 4 positions hit emergency exit simultaneously = €36 = 12% portfolio loss
- Daily loss limit should be BELOW simultaneous emergency exit: **3–5%**

```
max_daily_loss_pct = 3.0%    (from current 30.0%)
max_daily_loss_eur = €15     (from current €100)
```

At 3%, a €300 portfolio triggers kill switch at €9 loss — well before the fourth emergency exit can compound.

**Current 30% = €90 on €300 portfolio.** This is more than the entire starting capital of the Bitget Futures bot ($50). The "temporary" label has been active for 13 months.

### 6.2 Emergency Exit: −5% (Not −12%)

**Math:**

With a 0.5% spread + 0.31% fees round-trip:
- Breakeven requires: +0.81% grid profit
- Mean-reversion range for grid: typically ±3–5% of ATR
- Grid should be profitable within 2–3× ATR

Setting emergency exit at 2×ATR (clamped to [2%, 8%]) is already handled by ProfessionalRiskManager's ATR-based stops. The −12% emergency exit as the last resort should be tighter:

```
emergency_exit_pct = -5.0    (from -12.0)
hard_stop_pct = -8.0         (from -15.0)
```

**Rationale:** At −12%, a €75 position has lost €9 — which is 60× the average grid take-profit (~€0.15 per fill at the observed fill rates). No grid recovery can compensate for a −12% move.

### 6.3 Stop-Loss: Enable at 2×ATR

**Math:**

Currently `stop_loss_pct: null` (disabled). The ATR-based stop in `ProfessionalRiskManager.should_exit_position()` IS called, but:
1. Only within `determine_executor_actions()` which is skipped when kill switch fires
2. The data shows 96% of filled futures trades hit stop-loss — the exits ARE triggering but losing money because they're too wide

```
stop_loss_pct = 2×ATR, clamped [2%, 5%]    (from null)
```

For typical crypto ATR of 2–3%: stop at 4–6% → clamped to 5%.

### 6.4 Weekly/Monthly Limits: Keep but Tighten

```
max_weekly_loss_pct = 5.0    (from 7.0)
max_monthly_loss_pct = 8.0   (from 10.0)
```

These are reasonable as cascading circuit breakers but only work if the kill switch is functional.

### 6.5 Concurrent Position Exposure

```
max_simultaneous_coins = 3         (from 4-6)
max_exposure_per_coin_pct = 30     (from 80)
max_total_exposure_pct = 60        (from 80)
```

**Rationale:** With 80% per coin and 4 coins, theoretical max exposure is 320%. Even with budget limits, the intent should be explicit. At 30% per coin × 3 coins = 90% max theoretical, 60% total cap = realistic limit.

### 6.6 Summary Table

| Parameter | Current | Recommended | Rationale |
|-----------|---------|-------------|-----------|
| `max_daily_loss_pct` | 30.0% | **3.0%** | Must be below worst-case concurrent loss |
| `max_daily_loss_eur` | €100 | **€15** | 5% of €300 portfolio |
| `max_weekly_loss_pct` | 7.0% | **5.0%** | Two bad days = weekly halt |
| `max_monthly_loss_pct` | 10.0% | **8.0%** | Harder cap before serious damage |
| `stop_loss_pct` | null | **2×ATR [2%,5%]** | Re-enable per-position stops |
| `emergency_exit_pct` | −12.0% | **−5.0%** | Tighter emergency net |
| `hard_stop_pct` | −15.0% | **−8.0%** | Absolute last resort |
| `max_simultaneous_coins` | 4–6 | **3** | Reduce correlation risk |
| `max_exposure_per_coin_pct` | 80% | **30%** | Prevent concentration |
| `max_total_exposure_pct` | 80% | **60%** | Portfolio-level cap |

---

## 7. Recovery Gaps

### 7.1 Current Recovery Behavior

| Scenario | Detection | Remediation | Verdict |
|----------|-----------|-------------|---------|
| **Orphaned positions** (coin in wallet, no executor) | ✅ `_detect_orphaned_positions()` scans balances | ❌ Alert-only: "Consider manually selling" | Manual only |
| **Stale orders** (limit order without executor) | ✅ `_cleanup_stale_orders()` detects & alerts | ❌ Alert-only: "Consider cancelling manually" | Manual only |
| **Lost entry prices** (restart) | ❌ Not detected — `entry_prices` dict starts empty | ❌ `should_exit_position()` uses `entry_prices.get()`, returns None → exit logic silently skipped | **Silent failure** |
| **Daily loss tracking errors** | ✅ `_reconcile_external_fills()` checks balance | ⚠️ Auto-resets loss if balance ≥ 95% of reference — could mask real losses | **Dangerous** |
| **Loss > 15% but balance check fails** | ✅ Detected | ⚠️ Auto-resets as "likely tracking error" (L1637) — could mask catastrophic loss | **Dangerous** |
| **Double exposure after restart** | ❌ Old exchange orders invisible to bot | ❌ Bot creates new grids → 2× position size | **Unprotected** |

### 7.2 The Reconciliation Paradox

The `_reconcile_external_fills()` method (L1547–L1640) has a dangerous assumption: if tracked daily loss > 15% and the balance check fails, it resets the loss counter as "likely tracking error." This means:

1. Bot crashes during a genuine −15% loss event
2. On restart, tracked loss shows 15%
3. Balance check fails (exchange API still unstable)
4. Bot resets loss to 0% as "tracking error"
5. Bot resumes trading, now with 15% less capital and no risk awareness

### 7.3 What's Missing

| Gap | Impact | Implementation | Urgency |
|-----|--------|----------------|---------|
| **Persist entry prices to SQLite** | Exit logic works after restart | 4 hours | Immediate |
| **Auto-cancel stale orders** (with configurable delay) | Frees locked capital | 4 hours | Immediate |
| **Load open orders from exchange on start** | Prevents double exposure | 1 day | Immediate |
| **Warmup gate** (no trading until reconciliation complete) | Prevents premature decisions | 4 hours | Immediate |
| **Safe reconciliation** (never auto-reset losses without confirmed balance improvement) | Prevents masking real losses | 4 hours | Next sprint |

---

## 8. Risk Architecture Verdict

### 8.1 Layered Approach — Sound in Theory, Broken in Practice

The architecture has a sensible **layered defense** design:

```
Layer 1: SmartEntryFilter  →  Prevent bad entries     [FUNCTIONAL ✅]
Layer 2: ProfRiskManager   →  Dynamic position exits  [PARTIALLY FUNCTIONAL ⚠️]
Layer 3: DrawdownTracker   →  Daily/weekly/monthly     [FAIL-OPEN ⚠️]
Layer 4: RiskGuardV2       →  Kill switch             [DEAD ❌]
Layer 5: Emergency Exit    →  Price-based last resort  [NO COOLDOWN ⚠️]
Layer 6: Futures RiskGuard →  Grid-specific guards     [3/6 DISABLED ⚠️]
```

**The problem is not the design — it's that layers 2, 3, and 4 are either dead or fail-open.** The entry filters (Layer 1) are the only barrier that consistently functions, and the data shows they're arguably too aggressive (98%+ rejection rate with NO_ORDERBOOK_DATA as the #1 reason at 35–44%).

### 8.2 The Four Risk Systems Problem (from Round 2)

Four separate systems track overlapping concerns with no arbiter:

| System | Data Source | State | Functional? |
|--------|------------|-------|-------------|
| `RiskGuardV2` | `RealtimePnLTracker` (unfed) | `trading_enabled` boolean | ❌ Dead |
| `DrawdownTracker` | `connector.get_balance()` (live) | `is_paused` boolean | ⚠️ Fail-open |
| `ProfessionalRiskManager` | `PositionRisk` dataclass (constructed per call) | `pause_until`, `recent_trades` (never populated) | ⚠️ Partially dead |
| `risk_manager` (GlobalRiskManager) | Direct fill tracking | `daily_loss_pct`, `cumulative_daily_loss_quote` | ⚠️ Unknown accuracy |

**The balance-based drawdown check is the only risk system receiving live data.** And it's fail-open.

### 8.3 Verdict

The risk architecture is **fragile**. It has multiple layers that each look correct in isolation but are disconnected from their data sources. The result is a Potemkin risk system: impressive on inspection, non-functional under stress.

The architecture would become sound if:
1. The PnL tracker receives live data (or is replaced with balance-based detection)
2. All risk checks are fail-closed
3. The kill switch actually kills (stops executors + cancels orders)
4. Entry prices survive restarts
5. One unified risk coordinator replaces 4 parallel systems

---

## 9. Edge Cases in the Risk Chain

### 9.1 What If the Risk Guard Errors?

| Scenario | Behavior | Evidence |
|----------|----------|---------|
| `check_limits()` throws exception | Exception propagates to Hummingbot framework, which catches and retries next tick — **trading continues without risk check** | L1902-1905: no try/except around `check_limits()` call |
| `pnl_tracker` attribute missing | Same — AttributeError propagates, trading continues | `pnl_tracker_v2` methods accessed without defensive coding |
| Decimal math error in PnL calc | Same pattern | `starting_balance` could be 0 → division by zero in `daily_pnl_pct()` |

**Verdict: FAIL-OPEN on all paths.** The risk system has no self-protection.

### 9.2 What If PnL Tracking Is Wrong?

**It IS wrong — PnL tracking shows 0% always.** The "temporary" workaround of raising the limit to 30% was applied 13 months ago and is still in production across all 4 bot configs.

Even the `DrawdownTracker` (which does receive balance data) has a vulnerability: it compares current balance to period-start balance. If the bot restarts mid-day, the new `daily_start_balance` is the CURRENT (depleted) balance — resetting the daily loss counter.

### 9.3 What If Trend Calculator Returns Stale Data?

| Protection | Evidence | Scope |
|-----------|----------|-------|
| `StalenessGuard` checks price age | L6511: blocks entry on stale price data | ✅ New entries only |
| No staleness check on active positions | `should_exit_position()` at L8719 uses `trend_calculator` data without freshness check | ❌ Active positions |
| No staleness check in risk evaluation | `_check_professional_exit_signals()` at L5261 uses `trend_calculator` without freshness check | ❌ Exit decisions |

**Consequence:** If market data pipeline stalls, the bot continues holding positions based on stale prices. Exit signals may fire late or not at all.

### 9.4 What If Kraken Rate-Limits During a Risk Event?

The data shows 336 WebSocket-related events in a 3-day Kraken session. The controller has rate-limit handling with exponential backoff (L957–L1050), but:

| Scenario | Behavior |
|----------|----------|
| Rate-limited during normal trading | Backoff 5s → 10s → 20s → ... → 300s max. Eventually sets `permanent_api_failure` |
| Rate-limited while trying to close position (kill switch) | **Kill switch doesn't close positions** — it only prevents new decisions. So rate limiting during risk events is N/A, but for the wrong reason: there's nothing to rate-limit |
| Rate-limited during stale order cleanup | Stale order cleanup is alert-only — no API calls to cancel |

**The real gap:** There is no "emergency close all" path that could be rate-limited. The bot has no mechanism to urgently liquidate positions.

---

## 10. What to Keep

### 10.1 SmartEntryFilter — ⭐ Best Component

The entry filter system is the **only consistently functional safety layer**. It demonstrates:
- Multi-factor analysis (RSI, VWAP, ATR, momentum, trend)
- Regime-aware thresholds (BULL/CHOP/BEAR)
- Structured event logging with rate limiting
- Shadow mode for new filters (safe rollout)
- SQLite-persistent cooldowns (parabolic blacklist)
- Configurable per-timeframe parameters

**However:** The 98.3% rejection rate suggests the filters may be too restrictive — or that the data pipeline (NO_ORDERBOOK_DATA at 35–44%) is the real bottleneck, not the filters themselves.

### 10.2 Telegram Alerting Infrastructure

All critical events generate Telegram alerts:
- Kill switch activation (would alert, if it could fire)
- Orphaned position detection ✅
- Stale order detection ✅
- API error escalation ✅
- Capital-blocked notification ✅

**This is genuinely useful** for the manual remediation model, even though auto-remediation is missing.

### 10.3 Futures TPSL (Exchange-Side Orders)

The futures config has `exchange_stop_loss_enabled: true` with exchange-side TPSL orders:
- Survives bot crashes ✅
- Provides protection during disconnects ✅
- Independent of bot's PnL tracking ✅

**This pattern should be extended to spot** where exchange APIs support it.

### 10.4 ProfessionalRiskManager Design

The class design is sound:
- ATR-based dynamic stops (not fixed %)
- Context-aware time exits (stall + no fills)
- Profit tier logic with high-water-mark tracking
- Rolling PnL-driven pauses

**The problem is integration, not design.** If `record_fill()` and `record_trade_result()` were called, the dead liquidity detection, win rate monitoring, and PnL-driven pauses would all activate.

### 10.5 DrawdownTracker Period Logic

Despite being fail-open, the `DrawdownTracker` has correct period boundary logic:
- Multi-period tracking (daily/weekly/monthly)
- Conditional unpause (all limits must be satisfied)
- Based on actual exchange balance (not tracked PnL)

**If made fail-closed, this would be the most reliable risk check in the system** — because it's the only one using live balance data.

### 10.6 Budget Allocator Defensive Design

The `BudgetAllocator` (337 lines) uses:
- 0.2% fee buffer
- 5% reserve
- `Decimal("0.01")` tolerance
- Pessimistic reservation model

This is the primary reason the bot doesn't accidentally over-expose on entry. It's well-designed and should be preserved unchanged.

---

## 11. Capital Scaling Verdict

### Current Controls → **Paper Trading Only**

**Maximum capital I would trust with CURRENT risk controls: €0 (paper only)**

| Criterion | Status | Rating |
|-----------|--------|--------|
| Kill switch functional | ❌ PnL tracker never fed data | Fail |
| Risk checks fail-closed | ❌ All checks fail-open | Fail |
| Kill switch closes positions | ❌ Only prevents new decisions | Fail |
| Stop-loss on positions | ❌ Disabled (null) | Fail |
| Post-exit cooldown | ❌ No cooldown after emergency exit | Fail |
| State survives restart | ❌ Entry prices lost, no order reconciliation | Fail |
| Stale order auto-cleanup | ❌ Alert-only | Fail |
| Correlation monitoring | ❌ Hardcoded to 0.0 | Fail |

**No system managing real capital should have a non-functional kill switch.** The bot has been losing money for 14 months with no safety trigger. The data confirms this: −€229 cumulative across all instances.

### Upgrade Path

#### Tier 1: Paper Trading → Small Live (< €500)
**Requirements (all must be met):**

| # | Requirement | Effort | Priority |
|---|-------------|--------|----------|
| 1 | **Wire PnL tracker to fill events** OR replace kill switch with balance-based detection | 1 day | P0 |
| 2 | **Make all risk checks fail-closed** (`except Exception: return False` / block trading) | 30 min | P0 |
| 3 | **Kill switch must stop all executors** + cancel open orders | 1 day | P0 |
| 4 | **Enable stop-loss** at 2×ATR [2%, 5%] | 1 hour | P0 |
| 5 | **Add emergency exit cooldown** (30 min blacklist) | 2 hours | P0 |
| 6 | **Reduce daily loss limit** to 3% (from 30%) | 15 min | P0 |
| 7 | **Persist entry prices** to SQLite | 4 hours | P0 |
| 8 | **Auto-cancel stale orders** on startup | 4 hours | P0 |

**Total effort: ~4 days. After this, bot is safe for ≤ €500 with daily monitoring.**

#### Tier 2: Small Live → Medium (€500–€5,000)
**Additional requirements:**

| # | Requirement | Effort |
|---|-------------|--------|
| 9 | High-water-mark portfolio drawdown (max 10% from peak) | 1 day |
| 10 | Correlation risk monitoring (block if avg correlation > 0.7) | 2 days |
| 11 | Exchange-side stop orders for spot | 3 days |
| 12 | Warmup gate (no trading until reconciliation complete) | 4 hours |
| 13 | Load open orders from exchange on restart | 1 day |
| 14 | Wire `ProfessionalRiskManager.record_trade_result()` | 4 hours |
| 15 | Integration test suite for risk paths (kill switch fires, exits trigger, cooldowns work) | 3 days |
| 16 | Fix the Grid Execution (covered in round 1, requires resolving 98% no-fill rate) | Variable |

**Total additional effort: ~12 days. Requires operator monitoring 1x/day minimum.**

#### Tier 3: Medium → Larger (€5,000–€50,000)
**Additional requirements:**

| # | Requirement |
|---|-------------|
| 17 | Unified risk coordinator (replace 4 parallel systems) |
| 18 | Event-sourced audit trail (every state mutation logged) |
| 19 | Automated integration tests running before each deployment |
| 20 | Redundant kill switch (exchange-side + bot-side) |
| 21 | Position sizing using Kelly criterion or fixed fractional |
| 22 | Proven positive expected value over 1,000+ fills in paper trading |
| 23 | Split the God class (Round 2 recommendation) |
| 24 | External monitoring (not just self-monitoring) |

**Tier 4 (> €50,000): Not achievable with this architecture.** Would require a ground-up rewrite with proper exchange adapter layer, formal verification of risk paths, and institutional-grade infrastructure.

---

## 12. Confidence Classification

### Confirmed Findings (Direct Code + Data Evidence)

| Finding | Evidence Type |
|---------|-------------|
| PnL tracker never fed data → kill switch dead | `grep` for `on_trade_fill` / `update_unrealized` calls: 0 in controller |
| All risk checks are fail-open | Code at L1902 (no try/except), L3897 (explicit fail-open comment) |
| Kill switch doesn't close positions | `control_task()` returns early, `determine_executor_actions()` unreachable |
| Daily loss limit at 30% for 13 months | All 4 YAML configs: `TIJDELIJK: Verhoogd naar 30%` dated Feb 2025 |
| Stop-loss disabled on spot | All spot YAMLs: `stop_loss_pct: null` |
| 3/6 futures guards disabled | `_hard_loss`, `_grid_depth`, `_atr_explosion` all `return False` |
| Correlation hardcoded to 0.0 | L5661: `correlation_risk_score=0.0` |
| No high-water-mark drawdown | `DrawdownTracker` has no `high_water_mark` field |
| Entry prices not persisted | `self.entry_prices` is plain `Dict`, no SQLite write |
| Stale orders: alert-only | `_cleanup_stale_orders()` logs + Telegram, no cancel |
| 2/3 bots capital-blocked | Data snapshot: Bitget Spot $3.62/$30, Futures $9.41/$15 |
| −€229 cumulative loss, 98.3% no-fill | Data snapshot combined summary |
| `ProfessionalRiskManager` data feeds disconnected | `record_fill`/`record_trade_result` never called from controller |
| No emergency exit cooldown | `note_exit()` does not add to `session_blacklist` |
| Reconciliation resets >15% loss as "tracking error" | L1637: explicit fallback reset |
| Fee deduction bug at L8806 | Discarded expression (code inspection) |

### Reasonable Inferences (High Confidence)

| Finding | Basis |
|---------|-------|
| Kill switch has never fired in 14 months of production | −€229 loss with no kill switch log entry; PnL tracker proves it cannot fire |
| Double exposure possible after restart | No open order loading + immediate trading after `on_start()` |
| Correlated dump would hit all positions simultaneously | 4 concurrent altcoins, zero correlation monitoring |
| DrawdownTracker has fired on some occasions | It receives live balance data and has reasonable (if too high) thresholds |

### Unknowns — Requires More Data

| Question | What Data Is Needed |
|----------|-------------------|
| Has `DrawdownTracker.check_drawdown_limits()` ever actually paused trading? | Search production logs for "DRAWDOWN LIMIT" or "TRADING PAUSED" |
| What is the actual correlation between concurrent positions historically? | Compute 24h rolling return correlations for all traded pairs |
| How often does the balance check in reconciliation actually mask real losses? | Search logs for "Resetting as likely tracking error" |
| What would the fill rate be if NO_ORDERBOOK_DATA were fixed? | The 35–44% NO_ORDERBOOK_DATA rejection rate is the #1 blocker — fixing it could dramatically change bot behavior |
| Is the `GlobalRiskManager` (`risk_manager`) receiving fill data correctly? | Search for `risk_manager.on_fill` or equivalent calls |

---

## Appendix A: Production Config Risk Parameters (All 4 Bots)

| Parameter | Kraken EUR | Kraken USD | Bitget Spot | Bitget Futures |
|-----------|-----------|-----------|-------------|----------------|
| `max_daily_loss_pct` | 30.0% | 30.0% | 30.0% | 30.0% |
| `max_daily_loss_eur` | €100 | $120 | — | $50 |
| `max_weekly_loss_pct` | 7.0% | 7.0% | 8.0% | 10.0% |
| `max_monthly_loss_pct` | 10.0% | 10.0% | 12.0% | 15.0% |
| `risk_max_daily_loss_pct` | 30 | 30 | 30 | 30 |
| `stop_loss_pct` | null | null | null | 0.03 (3%) |
| `emergency_exit_pct` | −12.0% | −12.0% | −12.0% | −1.5% |
| `hard_stop_pct` | −15.0% | −15.0% | −15.0% | −2.5% |
| `max_simultaneous_coins` | 6 | 4 | 6 | 1 |
| `max_exposure_per_coin_pct` | 80% | 80% | 50% | 0.8 (?) |
| `risk_guard_enabled` | — | — | — | true |
| `exchange_stop_loss_enabled` | — | — | — | true |

**Notes:**
- All 4 bots have identical "temporary" 30% daily loss limit
- Only futures has a functioning `stop_loss_pct` and `exchange_stop_loss_enabled`
- Futures has tigher emergency/hard stops (−1.5%/−2.5%) vs spot (−12%/−15%)
- Kraken EUR is retired but config preserved

## Appendix B: Quick-Fix Checklist (P0 Items — 4 Days Total)

| # | Fix | File | Change | Effort | Test |
|---|-----|------|--------|--------|------|
| 1 | Wire PnL tracker | controller L1900 area | After fill events, call `pnl_tracker_v2.on_trade_fill()` | 4h | Verify `daily_pnl_pct()` returns non-zero after trade |
| 2 | Fail-closed risk guard | controller L1902 | `try: if not self.risk_guard_v2.check_limits(): ... except Exception: self.logger().critical(...); return` | 15min | Intentionally break PnL tracker, verify trading stops |
| 3 | Fail-closed drawdown | controller L3897 | Change `except: # Continue` to `except: return actions` | 15min | Mock exception, verify no new trades |
| 4 | Kill switch stops executors | controller L1904 | Before `return`, iterate `executors_info` and append `StopExecutorAction` for each active executor | 4h | Fire kill switch, verify all executors stopped |
| 5 | Emergency exit cooldown | controller L3862 area | After `note_exit()`, add `self._add_to_blacklist(coin, 1800)` (30min) | 30min | Trigger emergency exit, verify coin blocked |
| 6 | Set daily limit to 3% | All 4 YAML configs | `max_daily_loss_pct: 3.0` | 15min | Config change only |
| 7 | Enable stop-loss | Spot YAML configs | `stop_loss_pct: 0.05` (5%) | 15min | Config change only |
| 8 | Persist entry prices | controller + new SQLite table | Save on entry, load in `on_start()` | 4h | Restart bot, verify entry prices loaded |
| 9 | Auto-cancel stale orders | controller L1795 | After detection, call `connector.cancel()` with 60s delay | 4h | Create stuck order, restart, verify auto-cancelled |
| 10 | Fix fee deduction bug | controller L8806 | `price_change_pct = price_change_pct - estimated_fees_pct` | 5min | Unit test for `should_exit_position()` |
