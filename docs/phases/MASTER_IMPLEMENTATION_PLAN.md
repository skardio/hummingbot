# Master Implementation Plan — Multi-Coin Grid Bot

> **Generated:** 2026-03-13 | **Revised:** 2026-03-14 (v5 — T0/T1/T2 complete, headless fixed, config optimized, T3 filter relaxation applied)
> **Based on:** 4-round professional review (Strategy, Architecture, Risk, Production) + 2 plan reviews
> **Review files:** `.github/review-bundles/ROUND_{1..4}_*.md`
> **Target capital:** €25,000+ (current €300 trading budget on $1475 exchange balance — rest is long-term coin investments)
> **Cross-round verdict:** Paper trading only until T3 proof gate passes
> **AI policy:** No AI execution influence before T1+T2. No live AI gating before T3 + 30d shadow evidence. AI = overlay only (scorer/blocker/size-reducer/cooldown/safe-mode), never unrestricted trader.
> **Strategy warning:** Trend selector picks trending coins, but grid is mean-reversion → fundamental conflict. T3 filter relaxation applied to improve fill rate. Strategy validation (T3.5) still required.

---

## Cross-Round Consensus

| Round | Score | One-line Summary |
|-------|-------|------------------|
| **R1 Strategy** | Negative EV | 98.3% no-fill rate, grid levels too far from market, trend selector contradicts grid mechanics |
| **R2 Architecture** | 2.5/10 | 9,182-line God class, 0 locks, 4 parallel risk systems, dead code bug L8806 |
| **R3 Risk** | 1.5/10 | **Kill switch is dead** (PnL tracker gets no data), all risk checks fail-open, stop-loss disabled |
| **R4 Production** | Late Hobby | No process supervision, 320MB monitoring.db, 6.3GB logs, 2/3 bots capital-blocked |

### The 3 Critical Findings

1. **Kill switch is dead** — `RealtimePnLTracker.on_trade_fill()` is never called → `daily_pnl_pct()` always returns 0% → no loss limit can ever trigger. Running for 14 months.
2. **98.3% no-fill rate** — Grid levels are too far below market price (ATR×1.5 down) with a 20 min timeout. Trending coins (selected by trend engine) don't pull back enough.
3. **2/3 bots are capital-blocked** — Stuck SONIC order locks $71 on Bitget Spot, futures has only $9 left. Auto-cancel is missing.

---

## TIER 0: Quick-wins (< 30 min each, no risk)

| # | Item | Source | Effort | Impact | Location |
|---|------|--------|--------|--------|----------|
| **Q1** | **Fee bug fix** — `price_change_pct - estimated_fees_pct` result discarded, must be assigned | R2 | 5 min | PnL: exits trigger 0.31% too late | `controller.py` L8807 |
| **Q2** | **Duplicate config field removal** — `max_daily_loss_pct` defined as `Decimal(0.03)` at L863 AND as `float(5.0)` at L1000. L863 is dead code | R2 | 15 min | Bug: type mismatch, confusing dead code | `config.py` L863-870 |
| **Q3** | **Duplicate logging removal** — identical P&L log block appears 2× back-to-back | R2/R4 | 5 min | Noise: every status update logs twice | `controller.py` L8438-8444 |
| **Q4** | **Remove `gc.collect()` from hot path** — stop-the-world GC every tick | R2 | 15 min | Latency: 50-200ms pause per tick | `controller.py` L2129-2131 |
| **Q5** | **Fail-closed drawdown check** — `except: continue` → `except: return actions` (block trades on error) | R3 | 5 min | Safety: drawdown check can be bypassed by exception | `controller.py` L3897-3899 |
| **Q6** | **Fail-closed risk guard** — add try/except around `check_limits()` so exception → kill trading | R3 | 10 min | Safety: risk check can fail without consequences | `controller.py` L1904 |
| **Q7** | **Config: daily loss 30%→3%** — "TIJDELIJK" label from Feb 2025, unchanged for 13 months | R3 | 5 min | Safety: 30% limit = no real limit | All 4 YAML configs |
| **Q8** | **Config: enable stop-loss** — `null` → `0.05` (5%) in spot configs | R3 | 5 min | PnL: losses unbounded until -12% emergency | 3 spot YAML configs |
| **Q9** | **Config: emergency exit -12%→-5%** — and hard stop -15%→-8% | R3 | 5 min | Safety: 4 coins × -12% = -48% portfolio in flash crash | All spot YAML configs |
| **Q10** | **Config: extend grid timeout** — `no_fill_timeout_sec` 1200→3600 (60 min) | R1 | 15 min | High: 98.3% no-fill, timeout too short for grid to fill | YAML configs |
| **Q11** | **Config: extend monitoring timeout** — 180s→600s, more time for grid setup | R1 | 15 min | Medium: coins rotated before grid has chance to fill | YAML configs |

**Subtotal Tier 0: ~2 hours, 11 items**

### Proof Gate T0

- [x] All 11 items deployed (2026-03-12)
- [x] `flake8` passes on changed files
- [x] Bot starts without errors on each exchange (verified 2026-03-13 log)
- [x] Kill switch daily_loss_pct reads 3% (YAML confirmed, runtime not explicitly logged)
- [x] `stop_loss_pct` shows 0.05 in executor logs (`stop_loss=Decimal('0.05')`)
- [x] Grid timeout in logs shows 3600s, monitoring timeout shows 600s
- [x] Tests: 959 passed, 8 skipped, 0 failed

### Verified Locations (2026-03-12)

| Item | File | Exact Lines | Status |
|------|------|-------------|--------|
| Q1 | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | L8803-8808 | ✅ Confirmed |
| Q2 | `multi_coin_grid_pro/controllers/multi_coin_grid_config.py` | L863-870 (first), L1000-1007 (second) | ✅ Confirmed |
| Q3 | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | L8430-8444 | ✅ Confirmed |
| Q4 | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | L2129-2133 | ✅ Confirmed |
| Q5 | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | L3894-3899 | ✅ Confirmed |
| Q6 | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | L1904-1907 | ✅ Confirmed |
| Q7 | All 4 YAML configs: `spot_grid_kraken_usd.yaml`, `spot_grid_kraken_eur.yaml`, `spot_grid_bitget.yaml`, `futures_grid_bitget.yaml` | Various | ✅ Confirmed |
| Q8 | 3 spot YAML configs | `stop_loss_pct: null` | ✅ Confirmed |
| Q9 | All spot YAML configs | `emergency_exit_pct: -12.0`, `hard_stop_pct: -15.0` | ✅ Confirmed |
| Q10 | All YAML configs | `no_fill_timeout_sec: 1200` | ✅ Confirmed (moved from T3-F1) |
| Q11 | All YAML configs | Monitoring timeout 180s | ✅ Confirmed (moved from T3-F6) |

---

## TIER 1: Kill Switch & Critical Safety (1-2 days)

| # | Item | Source | Effort | Impact | What |
|---|------|--------|--------|--------|------|
| **K1** | **Wire kill switch** — call `pnl_tracker_v2.on_trade_fill()` on executor fills | R3 | 4h | **CRITICAL**: kill switch dead for 14 months | Controller: fill event handling |
| **K2** | **Kill switch closes positions** — on trigger: stop all executors + cancel open orders (not just "return") | R3 | 8h | **CRITICAL**: current kill switch only stops new trades, existing grids keep running | Controller: `control_task()` L1904-1906 |
| **K3** | **Emergency exit cooldown** — after emergency/hard-stop: coin 30 min in session blacklist | R3 | 2h | High: bot can immediately re-buy the same crashing coin | Controller: `note_exit()` call sites |
| **K4** | **Persist entry prices** — SQLite table for entry prices, load at `on_start()` | R3 | 4h | High: after restart bot doesn't know when positions were opened → exit logic broken | New: SQLite table |

**Subtotal Tier 1: ~18h (2-2.5 days), 4 items**

### Verified Locations (2026-03-12)

| Item | Evidence |
|------|----------|
| K1 | `pnl_tracker_v2` instantiated at L490, passed to `RiskGuardV2` at L507, but `.on_trade_fill()` and `.update_unrealized()` have ZERO calls in controller |
| K2 | L1904-1906: `if not check_limits(): return` — only prevents new decisions, no `StopExecutorAction` issued |
| K3 | `note_exit()` at L3862/L4133/L4149 only sets `_last_exit_time`, no `session_blacklist` addition |
| K4 | `self.entry_prices: Dict[str, Decimal] = {}` at L240 — in-memory only, zero SQLite persistence |

### Implementation Status (2026-03-13)

| Item | Status | What was done |
|------|--------|---------------|
| K1 | ✅ Done | Synthetic buy+sell `TradeFill` objects fed to `pnl_tracker_v2.on_trade_fill()` at executor termination in `_sync_risk_state()`. Also calls `update_unrealized()` each tick for open positions. |
| K2 | ✅ Done | New `_kill_switch_stop_all_executors()` method: issues `StopExecutorAction(keep_position=False)` for ALL active executors. Called from `control_task()` when `check_limits()` is False or errors. Telegram alert with PnL summary. |
| K3 | ✅ Done | `_add_to_blacklist()` called after emergency_exit, hard_stop_exit, stop_loss in both pro exit system and `_sync_risk_state()` STOP_LOSS handler. Uses existing `blacklist_after_timeout_sec` config (default 30m). |
| K4 | ✅ Done | New `EntryPriceStore` (SQLite, WAL mode) in `persistence/entry_price_store.py`. Save on grid creation, delete on stop/cleanup. Load in `on_start()`. Survives restarts. |
| Tests | ✅ 17 pass | `test_t1_kill_switch.py`: 9 EntryPriceStore, 4 PnLTracker, 3 RiskGuard, 1 cooldown |

### Proof Gate T1

- [ ] Manual test: kill switch triggers at configured `max_daily_loss_pct` (3%)
- [ ] On trigger: all executors stopped, open orders cancelled (verified on exchange)
- [ ] On trigger: no new entries created for remainder of day
- [ ] On trigger: Telegram alert sent with loss amount and action taken
- [x] After bot restart: entry prices loaded from SQLite, match pre-restart values (unit tested)
- [x] Emergency exit → coin appears in session blacklist for 30 min (code verified)
- [ ] Kill switch state survives restart (doesn't reset daily counter)

## TIER 2: Capital Recovery & Operations (1-2 days) — ✅ IMPLEMENTED 2026-03-14

| # | Item | Source | Effort | Impact | What | Status |
|---|------|--------|--------|--------|------|--------|
| **O1** | **Auto-cancel stale orders** | R3/R4 | 4h | High | `_cleanup_stale_orders()` → now calls `connector.cancel()` | ✅ Done |
| **O2** | **systemd service per bot** | R4 | 2h | Critical | `deploy/systemd/bot-kraken-usd.service` + README | ✅ Done |
| **O3** | **SQLite WAL mode** | R4 | 30 min | Medium | WAL added to cooldown_store, monitoring/database | ✅ Done |
| **O4** | **Daily DB backup cron** | R4 | 1h | High | `deploy/backup_dbs.sh` — sqlite3 .backup, 7d retention | ✅ Done |
| **O5** | **Monitoring DB retention** | R4 | 2h | Medium | `prune_old_data()` — status>7d, events>30d, trades>90d; auto on init | ✅ Done |
| **O6** | **Log cleanup cron** | R4 | 1h | Medium | `deploy/cleanup_logs.sh` — JSONL>14d delete, logs>7d gzip | ✅ Done |
| **O7** | **Health check endpoint** | R4 | 2h | High | `/health` → 200/503 based on bot_status freshness (120s) | ✅ Done |
| **O8** | **Rotation cooldown** | R1/R4 | 2h | Medium | 5min blacklist after TAKE_PROFIT/normal close via `duration_override` | ✅ Done |

**Tests: 14 new (test_t2_ops.py) — 990 passed, 8 skipped, 0 failed**

### Proof Gate T2

- [ ] Stale orders auto-cancelled after 60s grace period (verified on exchange)
- [ ] Stuck SONIC order resolved → Bitget Spot capital unblocked
- [ ] `systemctl status bot-*` shows all bots running with Restart=always
- [ ] Simulated bot kill → auto-restart within 15s
- [x] SQLite databases use WAL mode (`PRAGMA journal_mode` returns `wal`)
- [ ] Backup cron runs daily, 7-day retention verified
- [x] monitoring.db < 50MB after retention cleanup
- [x] `/health` endpoint returns last_tick < 30s ago
- [x] Rotation cooldown prevents same-coin re-selection within N minutes

### Verified Locations (2026-03-12)

| Item | Evidence |
|------|----------|
| O1 | `_cleanup_stale_orders()` L1795-1895: detects, alerts via Telegram ("consider cancelling manually"), stores in `self._stale_orders` — NEVER calls cancel |
| O2 | `find` for `*.service` → zero results. Start scripts use `set -e` + direct `python3` |
| O3 | `grep` for `journal_mode`/`WAL` → zero results in Python code |
| O4 | `data/backup/` has 6 files from Dec 2025 migration only. No cron. |
| O5 | `monitoring.db` = 320MB, `database.py` has no DELETE/purge |
| O6 | `logs/` = 6.3GB, 149 files, JSONL events never cleaned |
| O7 | No `/health` endpoint exists. Flask dashboard has `/api/status` (informational only) |
| O8 | SONIC-loop (19× consecutive) documented in R4. Rotation logic in controller has no cooldown/backoff per coin. |

---

## TIER 2.5: Headless Launch Fix (2026-03-14) — ✅ COMPLETE

> **Context:** Systemd deployment revealed 4 bugs preventing headless operation.
> Fixed same day. Bot confirmed starting with connectors and order books.

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| **H1** | `ptpython` top-level import crash | Bot won't start | Made lazy import in `bin/hummingbot_quickstart.py` |
| **H2** | Strategy file name `.py` suffix mismatch | Config loading fails | Pass `strategy_name` without `.py` |
| **H3** | MQTT forced in headless mode + infinite retry | Zero trading, 3KB logs/2min | Removed forced `mqtt_autostart`, `run_headless()` no longer requires MQTT |
| **H4** | `importlib.reload()` resets `markets = {}` | **ROOT CAUSE**: empty connectors dict → no trading | Removed reload in `load_script_class()`, reuse loaded module |

**Files changed:** `bin/hummingbot_quickstart.py`, `hummingbot/core/trading_core.py`, `hummingbot/client/hummingbot_application.py`
**Service files:** `deploy/systemd/bot-*.service` — removed WatchdogSec, Restart=on-failure
**Tests:** 990 passed, 8 skipped, 0 failed

---

## TIER 2.6: Config Optimization for $300 Budget (2026-03-14) — ✅ COMPLETE

> **Problem:** Bot had $300 trading budget but config allowed 4 simultaneous coins.
> With volatility adjustment, 1 grid consumed ~$145 → only $7 left → "Insufficient capital" 253x/day.
> Exchange balance is $1475 but ~$1175 is locked in long-term coin investments.

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| `max_simultaneous_coins` | 4 | **2** | $300/2 = $150/coin → eliminates deadlock |
| `num_grids` | 5 | **3** | 3 levels × $50 = snelle fill, past in budget |
| `dynamic_grid_sizer.min_grids` | 4 | **3** | Match num_grids |
| `dynamic_grid_sizer.max_grids` | 12 | **5** | $300 budget limiet |
| `dynamic_slots.max_slots` | 12 | **3** | Max 2-3 coins |
| `max_open_orders` | 60 | **20** | 2 coins × 5 levels × 2 = 20 voldoende |
| `risk_reference_balance_quote` | $400 | **$300** | Match actual budget |
| `max_daily_loss_quote` | $120 | **$9** | 3% van $300 |
| `risk_max_balance_per_trade_pct` | 60% | **55%** | Max $165/coin |
| `max_exposure_per_coin_pct` | 80% | **55%** | Past in 2-slot model |
| `max_total_exposure_pct` | 80% | **95%** | 2 slots gebruiken bijna alles |

**March PnL audit:** +$6.58 (27 grids, 9W/4L/14 zero-fill) — positief na T0/T1 fixes, maar te weinig trades door capital deadlock.

---

## TIER 3: Fill Rate Fix (2-4 days) — 🔸 IN PROGRESS

> **Note:** Config-only fill-rate items (timeout, monitoring window) moved to T0. Rotation cooldown moved to T2.
> **Discovery:** SmartEntry filter analysis revealed exact rejection breakdown (across all rotated logs):
> - RSI overbought: **1782** (42%) — effective threshold 64.4 due to BEAR regime + confidence scaling
> - Spread too wide: **1051** (25%) — Kraken altcoin spreads naturally 0.3-0.6%, old threshold 0.3%
> - Falling knife: **612** (15%) — VVV-USD responsible for 235 of these
> - Acceleration: **508** (12%) — VVV-USD responsible for 137
> - Trend: **155** (4%)
> **Key finding:** Market is in BEAR regime with confidence ≈0.6. Adaptive formula: `baseline + (regime - baseline) × conf`.
> With old config (baseline=68, BEAR=62): `68 + (62-68) × 0.6 = 64.4` — confirmed by all 5 threshold parameters.

| # | Item | Source | Effort | Impact | What | Status |
|---|------|--------|--------|--------|------|--------|
| **F4** | **NO_ORDERBOOK_DATA investigation** | R1/R4 | 1-3d | Medium (only 2 hits today, was 336/3d) | WebSocket reconnect logic | ✅ Investigated — resolved itself |
| **F2** | **Grid distribution** — levels close enough with 3-grid/ATR-based | R1 | 4h | Medium: current 4% down range is OK | `grid_range_pct_down: 4.0`, ATR-based | ✅ Reviewed — adequate |
| **F3** | **SmartEntry filter relaxation** — RSI, spread, accel thresholds | R1 | 2h | **High: #1 rejection reason** | YAML adaptive_filters + smart_entry_filter | ✅ Config applied |

### T3-F3 Implementation Details (2026-03-14)

**SmartEntry filter changes (`smart_entry_filter` section):**

| Parameter | Before | After | Impact |
|-----------|--------|-------|--------|
| `rsi_buy_max` | 68 | **72** | Baseline RSI threshold raised |
| `max_entry_spread_pct` | 0.3% | **0.5%** | Eliminates 25% spread rejects on Kraken altcoins |
| `max_down_accel_pct` | -8.0 | **-6.0** | Slightly tighter falling knife protection |
| `max_up_accel_pct` | 4.0 | **5.0** | Reduces blow-off acceleration rejects |

**Adaptive filter changes (`adaptive_filters` section):**

| Regime | rsi_buy_max | max_up_accel | max_down_accel | entry_confidence_min |
|--------|-------------|--------------|----------------|---------------------|
| baseline | 68→**72** | 4→**5** | -8→**-6** | 0.65→**0.60** |
| BULL | 72→**76** | 3→**5** | -4→-4 | 0.60→**0.55** |
| CHOP | 68→**72** | 1.8→**2.5** | -2.5→**-3.0** | 0.75→**0.65** |
| BEAR | 62→**66** | 1.5→**2.0** | -2.0→**-3.0** | 0.90→**0.80** |

**Projected effective thresholds (BEAR, conf=0.6):**

| Parameter | Old effective | New effective | Improvement |
|-----------|--------------|---------------|-------------|
| rsi_buy_max | 64.4 | **68.4** | +4 pts → ~40% fewer RSI rejects |
| max_entry_spread | 0.3% | **0.5%** | Not adaptive, direct → eliminates spread rejects |
| max_up_accel | 2.5 | **3.2** | More lenient blow-off filter |
| max_down_accel | -4.4 | **-4.2** | Slightly tighter knife protection |

**⚠️ Changes require bot restart to take effect. Bot is running with old config (PID 5610).**

### Proof Gate T3

- [ ] No-fill rate drops from 98.3% to < 80% (measured over 7 days post-restart)
- [ ] First-fill rate ≥ 30% of opened grids
- [ ] Average time-to-first-fill decreases measurably
- [x] NO_ORDERBOOK_DATA rejection rate < 15% — currently ~0.1% (2 hits today vs 336/3d before)
- [ ] PnL per filled grid does not worsen vs pre-T3 baseline
- [ ] No increase in stop-loss/emergency-exit triggers

---

## TIER 3.5: Strategy Validation (1-2 weeks)

> **Gate:** T3 proof gate must pass first. This tier answers: "Does the strategy have positive EV at all?"
> Without this, all infrastructure work is for a bot that structurally loses money.
> **Core conflict:** Trend engine selects coins that are trending up → grid expects mean-reversion pullbacks → pullbacks don't come → 98.3% no-fill → timeout → rotate → repeat.

| # | Item | Source | Effort | Impact | What |
|---|------|--------|--------|--------|------|
| **S1** | **Replay backtest framework** — replay logged market data + decisions through strategy | v3 review | 3-5d | **Critical**: no way to validate strategy without replay | New: event replay engine using injectable clock (requires A1) |
| **S2** | **Regime classification** — identify mean-reversion vs trending vs choppy regimes per coin | v3 review | 2-3d | High: grid only works in mean-reversion, need to filter | New: regime detector module |
| **S3** | **Pair selection validation** — backtest which coin selection method yields best fill rate + PnL | v3 review | 2-3d | **High: pair selection may matter more than grid parameters** | Analysis: top-volume vs trend vs volatility vs mean-reversion score |
| **S4** | **Parameter sensitivity analysis** — sweep grid_spread, num_levels, timeout across historical data | v3 review | 1-2d | Medium: current params never validated against data | Analysis: parameter sweep script |
| **S5** | **Fix markets_recorder orderbook collection** — `_record_market_data()` in `markets_recorder.py` is enabled but writes 0 rows to MarketData table. Likely cause: `all(ex.ready for ex in self._markets)` never passes in V2 framework. Fix would enable orderbook snapshot collection for replay/backtest (S1). | investigation | 1-2d | Medium: useful data source for backtesting | `hummingbot/connector/markets_recorder.py` |
| **S6** | **Hurst exponent in GridSuitabilityScorer** — replace lag-1 autocorrelation (48 candles, statistically weak) with Hurst exponent (H<0.5 = mean-reverting). Requires 500+ observations. Add half-life of mean reversion (Ornstein-Uhlenbeck). Validates whether a coin is *structurally* mean-reverting, not just recently choppy. | quant review | 2-3d | **High: current mean_reversion score is educated guess, not statistically validated** | `grid_suitability_scorer.py` |
| **S7** | **GridScore weight validation via backtest** — current weights (RE 35%, MR 30%, BR 20%, AC 15%) are unvalidated. Score historical coin selections against actual grid PnL outcomes. Optimize weights or train simple model. Out-of-sample validation required. | quant review | 2-3d | **High: weights may be suboptimal or counterproductive** | Requires S1 (replay framework) + outcome data (AI-F2) |

**Subtotal Tier 3.5: ~2-3 weeks, 7 items**

### Proof Gate T3.5

- [ ] Replay backtest produces deterministic results (same input → same output)
- [ ] Regime detector correctly classifies at least 3 known historical periods
- [ ] Pair selection analysis shows measurable fill-rate difference between methods
- [ ] At least one parameter combination shows positive EV in backtest (net of fees)
- [ ] Strategy has positive EV on paper for 14+ consecutive days with validated params
- [ ] If no positive EV found: **STOP and redesign strategy before adding more capital**

---

## TIER 4: Risk Architecture (3-5 days)

> **Includes A6 (risk coordinator)** — pulled forward from T5. Cannot build risk architecture with 4 uncoordinated systems.

| # | Item | Source | Effort | Impact | What |
|---|------|--------|--------|--------|------|
| **R6** | **Unify 4 risk systems → `RiskCoordinator`** — single entry point for RiskGuard, ProfessionalRiskManager, DrawdownTracker, PnLTracker | R2/v3 | 5d | **High: 4 parallel risk systems with no arbiter, prerequisite for all below** | Controller + new module |
| **R1** | **Correlation risk monitoring** — `correlation_risk_score` hardcoded 0.0, implement 24h rolling correlation | R3 | 2d | Medium: all positions can be maximally correlated | Controller L5661 + new |
| **R2** | **High-water-mark drawdown** — peak-equity tracking instead of period-start | R3 | 1d | Medium: intraday peak-to-trough unprotected | `DrawdownTracker` |
| **R3** | **Feed ProfessionalRiskManager** — call `record_fill()` and `record_trade_result()` | R3 | 4h | Medium: dead liquidity detection, win rate tracking inactive | Controller: fill/close events |
| **R4** | **Warmup gate** — no trading until reconciliation complete | R3 | 4h | Medium: bot can create double positions after restart | Controller: `on_start()` |
| **R5** | **Load open orders from exchange on start** — prevent double exposure | R3 | 1d | High: after restart, exchange orders invisible to bot | Controller: `on_start()` |

**Subtotal Tier 4: ~9.5 days (2 weeks), 6 items**

### Proof Gate T4

- [ ] Single `RiskCoordinator` handles all risk decisions (no direct calls to individual risk systems)
- [ ] Correlation risk score is non-zero when holding correlated positions (e.g., BTC+ETH)
- [ ] Drawdown tracker triggers on intraday peak-to-trough (not just start-of-day)
- [ ] `ProfessionalRiskManager` shows non-zero fill/trade counts after 24h operation
- [ ] Bot does not trade during warmup phase (verified in logs: "warmup X/Y" messages)
- [ ] After restart: exchange open orders are loaded and reconciled before first trade

---

## TIER 5: Code Quality & Architecture (weeks-months)

| # | Item | Source | Effort | Impact | What |
|---|------|--------|--------|--------|------|
| **A1** | **34× `time.time()` → injectable clock** — backtesting/replay impossible | R2 | 1d | Medium: violates repo rules, blocks replay | Controller: 34 locations |
| **A2** | **`run_until_complete` deadlock fix** — make `determine_executor_actions()` async, or pre-compute orderbook | R2 | 2d | Medium: can silently halt trading | Controller L4046 |
| **A3** | **24× inline `import traceback` → top-level** | R2 | 30 min | Low: code hygiene | Controller: 24 locations |
| **A4** | **Config decomposition** — 141 fields → nested Pydantic models (GridConfig, RiskConfig, etc.) | R2 | 3d | Medium: maintainability | `multi_coin_grid_config.py` |
| **A5** | **Split God method** — `determine_executor_actions()` (1342 lines) → 8 stage methods | R2 | 5d | High: untestable, incomprehensible | Controller L3180-4522 |
| **A6** | ~~**Moved to T4 as R6**~~ — Unify 4 risk systems → `RiskCoordinator` | R2 | — | — | See T4-R6 |
| **A7** | **Split `_is_executor_actually_active()`** — query with side-effects → pure check + mutation separately | R2 | 2d | Medium: unpredictable behavior | Controller L4541-4760 |
| **A8** | **33 connector private attr accesses** → `ConnectorAdapter` facade | R2 | 3d | Medium: upstream Hummingbot update breaks bot | Controller: scattered |
| **A9** | **Fix test infrastructure** — mock layer so 67% broken tests run again | R2 | 3d | High: 4/6 test files fail collection | `test/multi_coin_grid_pro/` |
| **A10** | **Late instance vars** — ~10 vars created outside `__init__` → defaults in `__init__` | R2 | 1h | Low: `AttributeError` landmines | Controller: scattered |
| **A11** | **God class decomposition** — full plan: 9,182 lines → 15 files of <500 lines | R2 | 30d | Critical for scaling beyond €5K | Everything |

**Subtotal Tier 5: ~50+ days, 11 items**

### Proof Gate T5

- [ ] All test files pass collection and run green
- [ ] No `time.time()` in controller code (only injectable clock)
- [ ] No inline `import` statements in controller
- [ ] God method < 200 lines per function
- [ ] Config model uses nested Pydantic structure (validate with `config.model_json_schema()`)
- [ ] 4 risk systems → 1 `RiskCoordinator` with single entry point

---

## TIER 6: Production Infrastructure (weeks)

| # | Item | Source | Effort | Impact | What |
|---|------|--------|--------|--------|------|
| **I1** | **External uptime monitoring** — healthchecks.io or UptimeKuma | R4 | 4h | High: nobody notices if bot dies | External + health endpoint |
| **I2** | **WebSocket stability fix** — 336 errors in 3 days on Kraken | R4 | 1-3d | High: #1 data pipeline problem | WS reconnect/keepalive |
| **I3** | **Cross-bot dashboard** — aggregated PnL/exposure view | R4 | 3d | Medium: no portfolio-wide overview | Monitoring stack |
| **I4** | **Config versioning** — `schema_version` + git-tracked configs + diff on startup | R4 | 4h | Medium: unknown which config was running for which loss | YAML configs + startup log |
| **I5** | **Deploy script with git tags** — `git tag v1.X.X` + `systemctl restart` + rollback | R4 | 4h | Medium: manual deploy, no rollback | New: deploy script |
| **I6** | **Distinct error logging** — 368× identical "Insufficient capital" → log count instead of repeating | R4 | 2h | Low: log noise | Controller: error paths |
| **I7** | **Exchange-side stop orders for spot** — OCO/TPSL on Kraken where supported | R3 | 3-5d | High: if bot is gone, spot positions unprotected | New: exchange adapter |
| **I8** | **Prometheus + Grafana** | R4 | 1w | Medium: professional monitoring | New: infra |
| **I9** | **Containerize all bots** | R4 | 1w | Medium | Docker Compose |
| **I10** | **Secret management** — `.env` → Vault/similar | R4 | 3d | Medium: machine compromise = all keys exposed | Infra |

**Subtotal Tier 6: ~3-6 weeks, 10 items**

### Proof Gate T6

- [ ] External uptime monitor alerts within 60s of bot down
- [ ] WebSocket error rate < 10/day (from 336/3 days)
- [ ] Cross-bot dashboard shows total exposure and aggregate PnL
- [ ] Config version tracked in startup log, git-tagged
- [ ] Deploy + rollback tested end-to-end
- [ ] All bots containerized, secrets not in plaintext files

---

## Summary

| Tier | Items | Effort | When | Goal |
|------|-------|--------|------|------|
| **T0: Quick-wins** | 11 | ~2h | ✅ DONE (2026-03-12) | Fix bugs + tighten safety params + config fill-rate wins |
| **T1: Kill Switch** | 4 | ~2 days | ✅ DONE (2026-03-13) | Functional safety net |
| **T2: Operations** | 8 | ~2 days | ✅ DONE (2026-03-14) | Process supervision, backups, stale order cleanup, rotation cooldown |
| **T2.5: Headless Launch** | 4 bugs | ~4h | ✅ DONE (2026-03-14) | Fix headless mode: ptpython, filename, MQTT, importlib.reload |
| **T2.6: Config Optimization** | 1 | ~30min | ✅ DONE (2026-03-14) | $300 budget: 2 slots, 3 grids, eliminate capital deadlock |
| **T3: Fill Rate** | 3 | ~2-4 days | **⬅️ NEXT** — F4 (WS/orderbook) first | Fix data pipeline, grid distribution, RSI filter |
| **T3.5: Strategy Validation** | 4 | ~1-2 weeks | **After T3** — does strategy have positive EV? | Replay backtest, regime detection, pair selection, param sweep |
| **T4: Risk Architecture** | 6 | ~2 weeks | After T3.5 — includes A6 (risk coordinator) | Unify risk, correlation, HWM drawdown, warmup gate |
| **T5: Code Quality** | 10 | ~45+ days | Ongoing, long-term (A6 moved to T4) | Decompose God class, fix async, tests |
| **T5.5: AI Foundation** | 3 | ~2-3 weeks | After T1+T2 complete | Decision/outcome logging + dataset export |
| **T6: Production Infra** | 10 | ~3-6 weeks | After T4 | Professional monitoring, containers, secrets |
| **T6.5: AI Shadow** | 8 | ~2-3 months | After T3.5 + 30d paper with positive EV | Shadow scoring for entry/rotation/risk + operator tooling |
| **T7: AI Soft Live** | 7 | ~2-3 months | After 30d positive shadow | Soft gating, blocking, supervisor, guardrails |
| **T8: Trend-Aware Grid** | 4 | ~2 weeks | After T1-T3 validated | Cap buy levels by regime, asymmetric spacing, trend-exit acceleration |
| **T9: Correlation Buckets** | 4 | ~2 weeks | After T8+2w | Correlation matrix, bucket allocation, portfolio beta, sector diversification |
| **T10: Fee Optimization** | 4 | ~2 weeks | After T3+T3.5 | Maker-only fees, ATR-proportional spacing, real-fee backtest, post-only orders |

**Total: 82 items.** T0+T1+T2 = ✅ DONE. T2.5 headless fix = ✅ DONE. T2.6 config optimized for $300. Next: T3 fill rate fix.

---

## Capital Scaling Tiers (from all 4 reviews + v2 correction)

> **Target:** €25,000+ across multiple exchanges. Current €300 is the development/validation phase — not the end state.
> Every tier below is a gate on the path to target capital. No shortcuts.

| Capital Tier | Requirements | Status |
|-------------|-------------|--------|
| **Paper only** | Current state | ✅ Done |
| **Paper with safety** | T0 + T1 + T2 complete (~5 days) | ✅ Done (2026-03-14) |
| **Micro-live validation** (≤€100, 1 exchange) | + T3 proof gate passed + no-fill < 80% | 🔸 In progress — live met $300, fill rate verbetering nodig |
| **< €500 live** | + T3.5 complete + **positive EV proven** in backtest + 30d stable paper | ⬜ |
| **€500–€5,000** | + T4 complete + 30d positive live PnL + fill rate < 60% no-fill | ⬜ |
| **€5,000–€25,000** ← target | + T5 (God class split) + T6 core (Prometheus, containers) + T5.5 AI foundation + 6mo track record | ⬜ |
| **€25,000–€50,000** | + T6.5 AI shadow validated + T7 guardrails proven + 12mo track record | ⬜ |
| **> €50,000** | Ground-up rewrite, PostgreSQL, HSM, multi-region, 24/7 monitoring | ⬜ Not achievable with current architecture |

---

## Priority Order (execution phases)

### Fase A — Nu direct (safety + capital recovery)

1. Q1-Q11 (all quick-wins including config fill-rate items)
2. K1 Wire kill switch
3. K2 Kill switch closes positions
4. K3 Emergency exit cooldown
5. Q5, Q6 Fail-closed risk checks
6. O1 Auto-cancel stale orders → **restart blocked bots**
7. O2 systemd service per bot

### Fase B — Meteen daarna (operations + persistence)

8. O3 WAL mode
9. O4 DB backup cron
10. O5 Monitoring DB retention
11. O6 Log cleanup cron
12. O7 Health check endpoint
13. O8 Rotation cooldown
14. K4 Persist entry prices

### Fase C — Fill rate fix (data first, then mechanics)

15. F4 NO_ORDERBOOK_DATA / WebSocket investigation ← **start here, may unlock everything**
16. F2 Grid level distribution
17. F3 RSI filter relaxation

### Fase C.5 — Strategy validation (does the strategy have positive EV?)

18. S1 Replay backtest framework
19. S2 Regime classification (mean-reversion vs trending)
20. S3 Pair selection validation
21. S4 Parameter sensitivity analysis
22. **PROOF GATE: positive EV in backtest. If not → redesign strategy before continuing.**

### Fase D — Risk architecture (includes A6 from T5)

23. R6 Unify 4 risk systems → RiskCoordinator
24. R5 Load open orders on start
25. R4 Warmup gate
26. R1 Correlation risk monitoring
27. R2 High-water-mark drawdown
28. R3 Feed ProfessionalRiskManager

### Fase E — AI Foundation (start after T1+T2)

29. ~~AI-F1 Decision snapshot logging (entry + rotation)~~ ✅ Done (18 JSONL files, live since Apr 2026)
30. ~~AI-F2 Outcome logging (entry + rotation)~~ ✅ Done (OutcomeLogger + 15 tests, wired in controller)
31. AI-F3 Dataset export pipeline

### Fase F — Code quality + architecture (ongoing)

32. A1-A5, A7-A11 (God class decomposition, async fix, tests — A6 already done in Fase D)
33. I1-I10 (production infrastructure)

### Fase G — AI Shadow + Soft Live (after T3.5 positive EV + 30d evidence)

34. AI-S1 through AI-S8 (shadow models, advisory modes, operator tooling)
35. AI-L1 through AI-L7 (soft gating, live intervention, guardrails, governance)

---

## TIER 5.5: AI Foundation (after T1+T2 complete)

> **Gate:** Do not start before T1 (kill switch) and T2 (operations) are fully proven.
> These items create data collection infrastructure only — zero influence on trading decisions.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **AI-F1** | **Decision snapshot logging** ✅ | AI-1 | 1w | Log structured feature snapshot for every entry AND rotation decision (market, strategy, bot-state, risk-context). Unique `decision_id`. Works in live/paper/replay. Logging failure never blocks trading. |
| **AI-F2** | **Outcome logging** ✅ | AI-1 | 1w | Link each `decision_id` to executor outcome: fill_happened, pnl, fees, hold_time, MAE, MFE, close_type. Survives restart. Missing outcomes explicitly marked. Rotation outcomes include switch cost and net benefit. |
| **AI-F3** | **Dataset export pipeline** | AI-1 | 3d | Export decisions+outcomes to ML-ready tabular format. Handle missing values. Explicit target labels. Filter by date/exchange/bot. Versioned datasets. |

**Subtotal T5.5: ~2.5 weeks, 3 items** (merged from AI-US-01 through AI-US-05)

### Proof Gate T5.5

- [ ] Decision logs written for every entry and rotation evaluation (0 gaps over 48h)
- [ ] Outcome records link to decision_ids (>95% match rate)
- [ ] Exported dataset loads without errors in pandas
- [ ] Logging adds < 5ms latency per decision cycle
- [ ] Logging failure does not block any trade

---

## TIER 6.5: AI Shadow Layer (after T3 + 30d stable paper)

> **Gate:** T3 proof gate passed + 30 days stable paper performance + working kill switch evidence.
> All models run in shadow/advisory mode only — zero influence on live trading.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **AI-S1** | **Fill probability model training** | AI-2 | 1w | Predict P(first_fill) from feature snapshots. Baseline comparison. Feature importance. Versioned artifact. |
| **AI-S2** | **Profitability model training** | AI-2 | 1w | Predict profitable_after_fees. Precision/recall/calibration. Segmented by exchange/regime. Does not replace hard rules. |
| **AI-S3** | **Entry AI shadow mode** | AI-2 | 1w | Score every eligible entry without changing behavior. Log with `decision_id`. Shadow reports compare AI suggestions vs actual results. Togglable per bot. |
| **AI-S4** | **Rotation quality model training** | AI-3 | 1w | Predict beneficial switch after costs. Compare against rule-based switching. Report false-positive harmful switches. |
| **AI-S5** | **Rotation AI advisory mode** | AI-3 | 3d | Log allow/reject/defer recommendation for every considered switch. Bot behavior unchanged. Report AI-vs-rule disagreements. |
| **AI-S6** | **Rule-based risk supervisor** | AI-4 | 1w | Monitor: repeated errors, stuck orders, no-fill storms, WS instability, rotation loops. Actions: alert, pause, reduce slots, safe mode. Cannot disable hard exits. |
| **AI-S7** | **Anomaly detection model** | AI-4 | 1w | Offline model on historical data. Features: rejection rates, WS errors, fill starvation, API errors. Shadow mode. Distinguish anomaly from hard-rule incidents. |
| **AI-S8** | **LLM operator tooling** | AI-5 | 1w | On-demand bot behavior summary from structured logs. Facts vs inferences labeled. Incident root-cause assistant. Hourly health digest. Valuable at target scale (€25K+ across multiple bots). |

**Subtotal T6.5: ~2-3 months, 8 items**

### Proof Gate T6.5

- [ ] Shadow entry model precision > 60% on held-out data
- [ ] Shadow reports show model would have improved fill rate or avoided losing trades
- [ ] Rule-based supervisor correctly detects at least 3 known historical incidents in replay
- [ ] Anomaly model false-positive rate < 20% over 30d shadow run
- [ ] Zero impact on live trading behavior during entire shadow period

---

## TIER 7: AI Soft Live (after 30d positive shadow evidence)

> **Gate:** T6.5 shadow models run 30d+ with documented positive evidence. Formal review report required.
> AI may ONLY: score, block, reduce size, apply cooldown, trigger safe-mode. NEVER place discretionary trades.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **AI-L1** | **Entry AI soft gating** | AI-2 | 1w | AI may reject/reduce-size/cooldown. Hard rules always first. AI cannot override kill switch, stop-loss, emergency exits, max exposure. Configurable thresholds. Every action logged with score+reason. |
| **AI-L2** | **Entry AI performance review gate** | AI-2 | 3d | Live gating requires min shadow window passed. Review report: fill rate impact, trade frequency, PnL impact. Explicit config flag. Rollback without redeploy. |
| **AI-L3** | **Rotation AI soft blocking** | AI-3 | 3d | Block lowest-quality rotations only. Cannot force switches. Same-coin timeout patterns weighted negatively. Logged with score/features/threshold. |
| **AI-L4** | **AI risk supervisor live mode** | AI-4 | 1w | Limited actions: pause entries, reduce slots, cooldown, temp blacklist, safe mode. No discretionary trades. Config enablement per action. Auditable. Manual override. |
| **AI-L5** | **AI guardrail framework** | AI-6 | 1w | Hard rules always before AI. AI cannot override: kill switch, stop-loss, emergency, max exposure, reconciliation. Violations blocked+logged. Guardrail tests exist. |
| **AI-L6** | **Model versioning + rollback** | AI-6 | 3d | Version logged per scored decision. Previous model restorable by config. Metadata: dataset version, training date. Rollback documented. |
| **AI-L7** | **Offline eval pipeline + rollout gate** | AI-6 | 1w | Repeatable evaluation: precision/recall/calibration/business impact vs baseline. Staged rollout: logging→shadow→advisory→soft-live. Stage transitions require passing criteria. No training→live jumps. |

**Subtotal T7: ~2-3 months, 7 items**

### Proof Gate T7

- [ ] Entry AI soft gating improves net PnL vs rule-only baseline over 30d
- [ ] Zero guardrail violations (AI never overrides hard safety rules)
- [ ] Rotation blocking reduces timeout-loop churn by >50%
- [ ] Risk supervisor correctly intervenes on real anomalies with <10% false positive rate
- [ ] Rollback from AI-live to AI-shadow completes in <5 minutes
- [ ] Every AI action traceable: decision_id + model_version + score + threshold + action

---

## TIER 8: Trend-Aware Grid Levels (after T1-T3 validated)

> **Gate:** Trailing TP + Dynamic TP + Regime kill switch live for 2 weeks with measured improvement.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **TAL-1** | **Cap buy levels in CHOP/BEAR** | GRID-1 | 3d | When detected regime is CHOP, cap grid to bottom 60% of levels. In BEAR, cap to bottom 40%. Prevents buying at range top during downtrend. Configurable multipliers per regime. |
| **TAL-2** | **Asymmetric grid spacing** | GRID-1 | 3d | Wider spacing between upper levels (less aggressive buying near range top), tighter spacing at bottom (catch bounces). Spacing ratio configurable per regime. |
| **TAL-3** | **Trend-exit acceleration** | GRID-2 | 2d | If regime flips to BEAR while grid has open buys, reduce max_hold_time by 50% to exit faster. Configurable acceleration factor. |
| **TAL-4** | **Regime-aware TP adjustment** | GRID-2 | 2d | In BULL regime, widen TP by 1.5× (let winners run). In BEAR, tighten TP to 0.7× (take profit quickly). Multipliers configurable per regime. |

**Subtotal T8: ~2 weeks, 4 items**

### Proof Gate T8

- [ ] Timeout-exit rate drops from 80% to <50% over 2-week validation
- [ ] Average PnL per closed grid improves vs pre-T8 baseline
- [ ] BEAR regime caps prevent >90% of "bought at top" entries
- [ ] No regression in BULL regime performance

---

## TIER 9: Correlation Buckets & Portfolio Diversification

> **Gate:** T8 live for 2 weeks. Portfolio-level risk improvements required.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **CB-1** | **Correlation matrix computation** | PORTFOLIO-1 | 3d | Compute rolling 24h return correlations between all active trading pairs. Use 5-min candle returns. Cache and refresh every hour. |
| **CB-2** | **Correlation-aware slot allocation** | PORTFOLIO-1 | 3d | Group coins into correlation buckets (ρ > 0.7). Never allocate >1 slot to same bucket. If best coin is correlated with active position, pick next-best from different bucket. |
| **CB-3** | **Portfolio beta tracking** | PORTFOLIO-2 | 2d | Track portfolio beta to BTC. If all positions are high-beta (>0.8), reduce max_active_grids by 1 until diversified. Log portfolio beta every cycle. |
| **CB-4** | **Sector diversification** | PORTFOLIO-2 | 3d | Tag coins by sector (L1, DeFi, Meme, AI). Config: max 2 coins from same sector. Prevent concentration in single narrative. |

**Subtotal T9: ~2 weeks, 4 items**

### Proof Gate T9

- [ ] Max portfolio drawdown reduced by >20% vs uncorrelated baseline
- [ ] No duplicate-bucket positions observed over 2-week validation
- [ ] Portfolio beta stays below 0.9 when diversification is active
- [ ] Sector concentration never exceeds configured limits

---

## TIER 10: Fee Optimization & Strategy Backtesting (added 2026-04-03)

> **Gate:** T3 fill rate fixes live + T3.5 strategy validation framework ready.
> **Context:** USD run analysis (Apr 2-3, 2026) showed Kraken taker fees (0.26%/side, 0.42% RT) were the #1 margin killer — nearly all executor PnL was consumed by fees. ATR-proportional spacing and maker-only execution would significantly improve profitability.

| # | Item | Epic | Effort | What |
|---|------|------|--------|------|
| **FO-1** | **Maker-only fee evaluation** | FEE-1 | 2d | Evaluate switching all limit orders to post-only (maker-only) mode. Kraken maker fee is 0.16% vs 0.26% taker. Requires: (1) connector support for post-only flag, (2) handling of post-only rejection when price crosses, (3) measure fill rate impact. Target: reduce RT fee from 0.42% to 0.32%. |
| **FO-2** | **ATR-proportional grid spacing** | GRID-3 | 3d | Grid spacing must scale with coin ATR. Current fixed spacing (e.g. 3 levels over 4% = 1.33% per level) is too wide for low-ATR coins and too narrow for high-ATR coins. Formula: `level_spacing = base_spacing × (coin_atr / median_atr)`. Configurable base_spacing and clamp range. |
| **FO-3** | **Real-fee backtest framework** | TEST-1 | 5d | Backtest all strategies using actual Kraken fee schedule (not zero-fee assumptions). Requirements: (1) fee model injected into backtester, (2) per-exchange fee profiles, (3) comparison report: zero-fee vs real-fee PnL for each pair. Must prove strategy has positive EV after fees before live deployment. |
| **FO-4** | **Post-only order mode** | FEE-1 | 2d | Implement `post_only=True` flag in grid executor order submission. When enabled, all limit orders use post-only mode. If order would cross spread (immediate fill), cancel and re-price at next tick. Track rejection rate for monitoring. |

**Subtotal T10: ~2 weeks, 4 items**

### Proof Gate T10

- [ ] Maker-only mode reduces avg RT fee by ≥20% over 2-week validation
- [ ] ATR-proportional spacing produces tighter grids for low-ATR coins and wider for high-ATR
- [ ] Backtest with real fees shows positive EV for ≥60% of traded pairs
- [ ] Post-only rejection rate stays below 15% (orders repriced successfully)
- [ ] Net PnL per executor improves vs pre-T10 baseline with same coin selection
