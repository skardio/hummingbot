# 🏛️ Prop Desk Implementation Roadmap
**Multi-Coin Grid Pro - Professional Trading Architecture**

> **Status:** Planning Phase
> **Created:** 2025-12-30
> **Architecture Pattern:** Prop Trading Desk (Decision/Execution/Risk/Observability Layers)

---

## 0️⃣ Global Architecture (Professional Pattern)

### Core Principles

```
┌─────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                       │
│         (Structured Logs + Metrics + Audit Records)         │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────┐
│                       RISK LAYER                             │
│            (GlobalRiskManager - Can Override All)            │
│         • Kill Switch  • Exposure Caps  • Drawdown          │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌──────────────────┐    ┌─────────────────────────────────────┐
│  DECISION LAYER  │───▶│        EXECUTION LAYER               │
│   (Controller/   │    │      (GridExecutor Fleet)            │
│    Selector)     │    │  • State Machine  • Timeouts         │
│  • What to trade │    │  • Unwind Protocol  • Orders         │
│  • When to rotate│    └─────────────────────────────────────┘
└──────────────────┘
```

### 🔒 Bounded Execution Guarantee

**Every "forced exit" MUST be bounded (always terminates):**

1. **Graceful unwind** (maker/limit orders)
2. **Fallback** (taker/market) after `close_grace_sec`
3. **Timeout** (hard deadline)

**No infinite hangs. No stuck positions.**

---

## 🎯 EPIC A — Opportunity Cost & Rotation

### Story A1 — Multi-Timeout Lifecycle (No-Fill / No-Progress / Hard Cap)

**Scope:** GridExecutor krijgt 3 timeouts + duidelijke close-reasons

**Code Locations (Indicative):**
- `executors/grid_executor.py`: lifecycle, control loop, status, close triggers
- `models/`: `CloseType` / `CloseReason` enum, `ExecutorStatus` extensions
- `config/`: YAML schema + defaults + validation

**Config Keys (Minimal):**
```yaml
grid_timeouts:
  no_fill_timeout_sec: 1800        # 30 min - geen enkele fill → cancel + close
  no_progress_timeout_sec: 3600    # 1 hour - geen nieuwe fills → start unwind
  max_coin_time_sec: 14400         # 4 hours - hard cap (VSN-EUR 21h fix!)
  close_grace_sec: 300             # 5 min graceful close window
```

**Definition of Done:**
- [ ] GridExecutor tracks: `start_ts`, `last_fill_ts`, `last_progress_ts`
- [ ] Timeout triggers:
  - **no-fill**: cancel orders → close status `"NO_FILL_TIMEOUT"` (no inventory unwind needed)
  - **no-progress**: start unwind → `"NO_PROGRESS_TIMEOUT"`
  - **hard cap**: start unwind → `"TIME_LIMIT"`
- [ ] Every exit has exactly 1 reason + audit record
- [ ] Logging: 1 summary line per 30s (no spam)
- [ ] Backward compatible: missing keys → defaults, behavior stable

**PR Checklist:**
- [ ] Config defaults added + docs in `config.prod.yaml.example`
- [ ] Enums extended without breaking changes
- [ ] Unit tests green
- [ ] No new log spam (max lines/min verified)
- [ ] Changelog entry: "Timeout lifecycle added"

**Test Plan:**

**Unit:**
- "no fills" → after `no_fill_timeout_sec` status = `CLOSED_BY_NO_FILL_TIMEOUT`
- "1 buy fill, no close" → after `no_progress_timeout_sec` close flow starts
- hard cap → close flow always starts
- idempotency: timeout trigger 2x → only 1 close-sequence

**Integration (Mock Exchange):**
- Simulate order events + time travel (fake clock)
- Assert: orders cancelled, close orders placed, status transitions correct

---

### Story A2 — Session Blacklist & Anti-Flipflop

**Scope:** Controller/Selector remembers coins that "timeout-exited" and avoids them temporarily

**Code Locations:**
- `controllers/multi_coin_grid_controller.py` (or your controller)
- `selectors/coin_selector.py` (or selection function in controller)

**Config Keys:**
```yaml
grid_timeouts:
  blacklist_after_timeout_sec: 7200  # 2 hours - avoid timeout coins
```

**Definition of Done:**
- [ ] `session_blacklist[symbol] = expires_ts` exists
- [ ] Selector skips symbol while blacklist active
- [ ] Only for timeout reasons (NO_FILL/NO_PROGRESS/TIME_LIMIT), not normal TP complete
- [ ] Logs: `blacklist_add`, `blacklist_skip`, `blacklist_expire`

**PR Checklist:**
- [ ] Selector output mentions "skipped due to blacklist"
- [ ] Tests cover expiry and skip

**Test Plan:**
- Timeout on coin A → A is avoided for X sec → then selectable again

---

### Story A3 — Multi-Coin Concurrency (2–3 Grids Parallel)

**Scope:** Multiple executors simultaneously + exposure caps

**Code Locations:**
- Controller (manage list of active executors)
- Risk manager / exposure tracker

**Config Keys:**
```yaml
execution:
  max_concurrent_grids: 2           # Phase 1: 2 coins, Phase 2: 3 coins

risk:
  max_quote_exposure_total: 120     # €120 total (2 × €60)
  max_quote_exposure_per_symbol: 60 # €60 per coin
```

**Definition of Done:**
- [ ] Controller can manage N executors simultaneously
- [ ] New grid starts only if exposure/caps OK
- [ ] One grid hangs → others keep running

**Test Plan:**
- Start N grids → N+1 is rejected with reason `CONCURRENCY_LIMIT`
- Exposure exceeded → rejected with reason `EXPOSURE_LIMIT`

---

## 🔄 EPIC B — Execution & Unwind (Bounded Exits)

### Story B1 — Two-Phase Unwind (Graceful → Aggressive Fallback)

**Scope:** Every forced close (timeout/SL/manual/risk) uses 2 phases

**Code Locations:**
- `executors/grid_executor.py`: close orchestration
- `connectors/` or order placement util: support for market/taker/IOC depending on connector
- `models/close_policy.py` (optional new): close policy parameters

**Config Keys:**
```yaml
grid_timeouts:
  close_grace_sec: 300              # 5 min graceful window

execution:
  aggressive_close_type: MARKET     # MARKET | IOC | FOK (per exchange)
  max_close_retries: 3
```

**Definition of Done:**
- [ ] **Phase 1:**
  - Cancel non-essential orders
  - Place close via maker/limit where possible
- [ ] **Phase 2:**
  - After grace: remaining inventory → aggressive close
- [ ] **Bounded:**
  - Forced exit always done within `close_grace_sec` + `aggressive_window`
- [ ] **Idempotent:**
  - No duplicate close orders / double sells

**PR Checklist:**
- [ ] Exchange-compat matrix in docs (Kraken vs Bitget differences)
- [ ] Extra logs only at transition (start graceful, start aggressive, done)

**Test Plan:**
- Simulate "close order hangs" → aggressive fallback triggers
- Simulate partial fills → remainder closed correctly

---

### Story B2 — Close Reason Taxonomy + Audit Records

**Scope:** Every grid produces an audit record for analysis

**Code Locations:**
- `models/execution_audit.py` (new)
- `storage/` (sqlite/csv/json) depending on your setup
- Controller: commit audit on executor finish

**Fields (Minimal):**
```python
@dataclass
class ExecutionAudit:
    symbol: str
    start_ts: float
    end_ts: float
    reason: CloseReason              # TP_COMPLETE | NO_FILL_TIMEOUT | NO_PROGRESS_TIMEOUT | etc.
    realized_pnl: Decimal
    fees: Decimal
    num_fills: int
    num_closed_levels: int
    max_adverse_excursion: Decimal   # MAE (optional - best effort first)
    config_snapshot: Dict            # Grid params used
    version: str = "1.0"
```

**Definition of Done:**
- [ ] On every executor finish → record written
- [ ] Reason always filled
- [ ] Record schema versionable (future-proof)

**Test Plan:**
- Unit: record created for each reason
- Integration: record output exists and is valid JSON/CSV

---

## 📊 EPIC C — Observability (Pro Logging + Metrics Without 400MB Logs)

### Story C1 — Structured Logging + Sampling + Log Budget

**Scope:** One summary log per 30s per grid + burst debug only on anomalies

**Code Locations:**
- `logging/` config + formatter
- Executor/controller: replace spam logs with summaries

**Definition of Done:**
- [ ] **Structured logs** (key=value or JSON)
- [ ] **Sampling:**
  - Steady-state: 1 log/30s/grid
  - Anomalies: state transitions, timeouts, risk events → detail
- [ ] **Log budget** warns on exceeded threshold (e.g. MB/hour)

**Test Plan:**
- Simulate 10 min runtime: verify log count within target
- Trigger timeout: verify burst detail present

---

### Story C2 — Metrics Export + KPIs

**Scope:** CSV/Prometheus-ready metrics per coin/strategy

**KPIs (Minimal):**
```yaml
time_to_first_fill:        # Seconds until first grid fill
time_to_progress:          # Seconds between fills
pnl_per_hour:              # €/hour realized
fees_per_hour:             # €/hour in fees
timeout_rate:              # % grids ending in timeout (per reason)
fill_rate:                 # Fills/hour
close_rate:                # Successful closes/hour
exposure_time_distribution: # p50/p95 time in position
```

**Definition of Done:**
- [ ] Metrics emitter interface
- [ ] Per grid summary event + per coin aggregates
- [ ] One "daily/session report" file

**Test Plan:**
- Unit: aggregator correct
- Integration: metrics file filled after trades/timeouts

---

## 🎯 EPIC D — Coin Selection Like Pros (Score + Cost Model)

### Story D1 — Score-Based Selector with Fee/Spread/Depth Model

**Scope:** Selection is not "feeling", but score with breakdown

**Code Locations:**
- `selectors/coin_selector.py`
- `market_data/` (spread/depth/vol inputs)
- Controller: log top candidates

**Definition of Done:**
- [ ] **Score = f(spread, depth, volatility, volume, regime, penalties)**
- [ ] Penalty for high timeout-rate / blacklist history
- [ ] Log top 5 with breakdown

**Score Formula (Example):**
```python
score = (
    trend_consensus * 0.30
    + liquidity_score * 0.25      # depth/spread composite
    + volume_score * 0.20
    + regime_bonus * 0.15
    - timeout_penalty * 0.10      # historical timeout rate
)
```

**Test Plan:**
- Synthetic inputs → score ordering as expected
- Penalty works

---

### Story D2 — Regime-Aware Grid Presets (Adaptive TP/Spacing/Timeouts)

**Scope:** Regime detection (low-vol vs high-vol vs trend) and presets

**Code Locations:**
- `strategy/regime_detector.py` (new) or in controller
- `config/regime_presets.yaml`

**Definition of Done:**
- [ ] Regime labels + mapping to grid params
- [ ] Timeouts can get multiplier per regime
- [ ] Logging: regime switch event

**Regime Presets (Example):**
```yaml
regime_presets:
  LOW_VOL:
    timeout_multiplier: 1.5       # More patient
    grid_spacing_mult: 0.8        # Tighter grids
    tp_target_pct: 1.5

  HIGH_VOL:
    timeout_multiplier: 0.7       # Faster rotation
    grid_spacing_mult: 1.2        # Wider grids
    tp_target_pct: 2.5

  TREND:
    timeout_multiplier: 1.0
    asymmetric_bias: 0.7          # More grids on trend side
    tp_target_pct: 3.0
```

**Test Plan:**
- Feed candles/returns → regime correct
- Params change according to preset

---

## 🛡️ EPIC E — Desk-Grade Risk

### Story E1 — Global Kill-Switch + Exposure Caps

**Scope:** Risk manager can block new grids and unwind all inventory

**Code Locations:**
- `risk/global_risk_manager.py`
- Controller: pre-check before start grid
- Executor: risk-trigger → forced unwind

**Definition of Done:**
- [ ] **Hard limits:** daily loss, drawdown, exposure total/per coin
- [ ] Trigger → `RISK_HALTED` + unwind all
- [ ] Bounded close (B1) used

**Config Keys:**
```yaml
risk:
  max_daily_loss_pct: 3.0           # Kill switch
  max_drawdown_pct: 5.0             # Kill switch
  max_quote_exposure_total: 120
  max_quote_exposure_per_symbol: 60

  kill_switch:
    enabled: true
    unwind_mode: GRACEFUL            # GRACEFUL | AGGRESSIVE | IMMEDIATE
    notification_channels: [telegram, email]
```

**Test Plan:**
- Trigger drawdown → no new grids + unwind starts
- Exposure overshoot → start blocked

---

### Story E2 — Inventory Aging Guard (Anti Adverse Selection)

**Scope:** Inventory held too long is actively managed

**Code Locations:**
- Executor level tracking

**Definition of Done:**
- [ ] Per filled level: `filled_ts`
- [ ] Aging threshold → action:
  - Partial unwind or force close (policy)
- [ ] KPI: `inventory_age_p95`

**Config Keys:**
```yaml
risk:
  inventory_aging:
    max_age_sec: 21600              # 6 hours max hold per level
    action: PARTIAL_UNWIND          # PARTIAL_UNWIND | FORCE_CLOSE
```

---

## 🔬 EPIC F — Research Harness (Optional But "Real Pro")

### Story F1 — Replay Harness (Orderbook Snapshots) for Timeouts/Selector

**Scope:** Run strategy in sim-mode on your saved data

**Definition of Done:**
- [ ] **Sim connector** with:
  - Maker/taker fills
  - Fees
  - Latency simulation
- [ ] **Outputs:** same audit + KPIs

**Benefits:**
- Test timeout logic without 4-hour live wait
- Validate selector on historical data
- Regression testing for strategy changes

---

## 📋 "PR-Sized" Workflow (How Copilot Builds This Best)

### Approach Per PR:

1. **Add config keys + defaults + schema/validation**
2. **Add enums/status extensions**
3. **Implement logic in executor/controller**
4. **Add tests (unit + small integration)**
5. **Add observability (logs/metrics)**
6. **Update docs + example config**

### PR Size Guidelines:

✅ **Good PR:** 1 story = 300-800 lines
❌ **Too big:** Entire EPIC in 1 PR
❌ **Too small:** Just config keys without logic

---

## 🎯 Recommended Implementation Order (Pragmatic Clustering)

### 🔥 **Cluster 1: Stop the Bleeding** (Week 1)
**Stories: A1 + B1 + A2**
- ✅ **A1** - Multi-Timeout Lifecycle (no-fill, no-progress, max 4h)
- ✅ **B1** - Two-Phase Unwind (graceful → aggressive fallback)
- ✅ **A2** - Session Blacklist (anti-flipflop)

**Impact:** VSN-EUR 21-hour problem SOLVED + no more stuck positions
**PR Size:** ~600-800 lines (tight cluster, shared context)
**Why together:** Timeouts without proper unwind = dangerous. Unwind without blacklist = flipflop. Bundle = complete solution.

---

### 📊 **Cluster 2: Get Visibility** (Week 2)
**Stories: C1 + C2 + B2**
- ✅ **C1** - Structured Logging + Log Budget (1 log/30s steady-state)
- ✅ **C2** - Metrics Export + KPIs (time_to_fill, timeout_rate, pnl/hour)
- ✅ **B2** - Close Reason Taxonomy + Audit Records

**Impact:** 400MB log explosion FIXED + real KPIs + audit trail
**PR Size:** ~400-600 lines (observability layer)
**Why together:** Metrics need structured logs. Audit records share same KPI infra. Natural cluster.

---

### 🎯 **Cluster 3: Get Smarter** (Week 3)
**Stories: D1 + A3**
- ✅ **D1** - Score-Based Selector (fee/spread/depth model)
- ✅ **A3** - Multi-Coin Concurrency (2-3 grids parallel)

**Impact:** Better coin selection + scale to 2-3 simultaneous positions
**PR Size:** ~500-700 lines
**Why together:** Smart selector needed before scaling to multi-coin. Selector + concurrency = complete scaling solution.

---

### 🛡️ **Cluster 4: Desk-Grade Safety** (Week 4)
**Stories: E1 + E2**
- ✅ **E1** - Global Kill-Switch + Exposure Caps
- ✅ **E2** - Inventory Aging Guard

**Impact:** Production-grade risk management
**PR Size:** ~300-500 lines
**Why together:** Kill-switch + aging = complete risk layer.

---

### 🚀 **Cluster 5: Advanced (Optional)**
**Stories: D2 + F1**
- 🎁 **D2** - Regime-Aware Grid Presets (adaptive params)
- 🎁 **F1** - Replay Harness (backtesting on saved data)

**Impact:** Optimization + research capability
**Why together:** Replay harness validates regime detection.

---

## 📊 Success Metrics

**After Each Cluster:**

### Cluster 1 (Week 1) - Stop the Bleeding
| Metric | Before | Target | Status |
|--------|--------|--------|--------|
| Max position hold time | 21+ hours | ≤ 4 hours | 🔴→🟢 |
| Stuck positions | 1 (VSN-EUR) | 0 | 🔴→🟢 |
| Flipflop switches | TBD | < 2/day | 🔴→🟢 |
| Unwind success rate | TBD | > 95% | ⚪→🟢 |

### Cluster 2 (Week 2) - Get Visibility
| Metric | Before | Target | Status |
|--------|--------|--------|--------|
| Log volume | 400+ MB/day | < 100 MB/day | 🔴→🟢 |
| Time to first fill (p95) | Unknown | < 15 min | ⚪→🟢 |
| Timeout rate | Unknown | < 10% | ⚪→🟢 |
| KPI dashboard | None | Live | ⚪→🟢 |

### Cluster 3 (Week 3) - Get Smarter
| Metric | Before | Target | Status |
|--------|--------|--------|--------|
| Concurrent positions | 1 | 2-3 | 🔴→🟢 |
| Selection confidence | Gut feeling | Score + breakdown | 🔴→🟢 |
| Opportunity capture | TBD | > 70% | ⚪→🟢 |

### Cluster 4 (Week 4) - Desk-Grade Safety
| Metric | Before | Target | Status |
|--------|--------|--------|--------|
| Kill-switch tested | No | Yes | ⚪→🟢 |
| Max drawdown breaches | Possible | 0 | ⚪→🟢 |
| Exposure violations | Possible | 0 | ⚪→🟢 |

---

## 🚀 Getting Started (Updated)

**Week 1 Sprint:** Cluster 1 (A1 + B1 + A2)
1. Day 1-2: Config + enums + tests (setup)
2. Day 3-4: Executor timeout logic + unwind
3. Day 5: Blacklist integration + testing
4. Weekend: Code review + merge

**Week 2 Sprint:** Cluster 2 (C1 + C2 + B2)
1. Day 1-2: Log formatter + sampling
2. Day 3-4: Metrics emitter + KPIs
3. Day 5: Audit records + dashboard
4. Weekend: Code review + merge

**Week 3 Sprint:** Cluster 3 (D1 + A3)
**Week 4 Sprint:** Cluster 4 (E1 + E2)

---

## 📚 References

- [Grid Executor State Machine](./GRID_EXECUTOR_STATE_MACHINE.md) (TODO)
- [Risk Manager Architecture](./RISK_MANAGER_ARCHITECTURE.md) (TODO)
- [Observability Guide](./OBSERVABILITY_GUIDE.md) (TODO)

---

**Document Version:** 1.0
**Last Updated:** 2025-12-30
**Maintainer:** Trading Team
**Status:** 📋 Planning → 🚧 In Progress (after approval)
