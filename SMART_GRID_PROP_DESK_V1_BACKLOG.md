# Smart Grid Prop Desk v1 — Production Backlog

> **Guiding Principles**
> 1. Edge komt niet van meer indicators, maar van **execution + risk + data quality + observability**
> 2. Geen trade is óók een positie (capital preservation)
> 3. Elke feature: **off → shadow → live**
> 4. Intent-driven: strategie beslist **wat**, execution beslist **hoe**

---

## 📋 Build Order (Recommended)

### Phase 1: Foundation + Quick ROI (Weeks 1-2)
1. ✅ US-A1: Intent Contract
2. ✅ US-A2: ExecutionManager
3. ✅ US-A3: RiskEngine gate
4. ✅ US-B1: Maker-first + fallback
5. ✅ US-B2: Cancel/replace policy
6. ✅ US-E1: Structured events
7. ✅ US-E3: Why-no-trade summary

### Phase 2: Risk + Sizing (Weeks 3-4)
8. ✅ US-C1: Exposure caps
9. ✅ US-C2: Drawdown kill-switch
10. ✅ US-C3: Time-stop exit (risk + execution)
11. ✅ US-D4: Liquidity-based sizing

### Phase 3: Stability + Scaling (Weeks 5-6)
12. ✅ US-G1: WS health + auto-recovery
13. ✅ US-F1: Feature flags
14. ✅ US-F3: Risk engine tests
15. ✅ US-D3: Orderbook prefetch live
16. ✅ US-E2: Metrics histograms

### Phase 4: Advanced (Optional)
17. 🔄 US-D5: Combined liquidity score
18. 🔄 US-F2: Deterministic replay
19. 🔄 US-F4: Property-based/fuzz tests

---

## EPIC A — Core Architecture: Intent → Risk → Execution

### US-A1: Introduce TradeIntent Contract

**As a** strategy controller
**I want to** output a standardized `TradeIntent` instead of placing orders directly
**So that** execution logic can evolve independently of strategy code

**Waarom:** Grote partijen scheiden decision en execution. Dit is de stap naar professioneel.

**Acceptance Criteria:**
- [ ] `TradeIntent` dataclass defined with fields:
  - `id` (UUID)
  - `exchange` (str)
  - `symbol` (str)
  - `side` (BUY/SELL)
  - `target_quote` (Decimal)
  - `urgency` (LOW/NORMAL/HIGH)
  - `constraints` (dict: max_spread, max_slippage, etc.)
  - `reason` (str: entry signal description)
- [ ] Strategy returns `List[TradeIntent]` instead of creating executors
- [ ] All intents logged with correlation ID
- [ ] No direct exchange calls from strategy module

**Out of Scope:**
- Changes to trading rules/signals
- Existing executor refactoring (keep compatibility layer)

---

### US-A2: ExecutionManager (Single Gateway)

**As a** trading system
**I want** a single component that owns all order placement/cancel/replace
**So that** order logic is consistent and auditable

**Waarom:** Voorkomt "random order calls" verspreid door code. Eén waarheid voor execution state.

**Acceptance Criteria:**
- [ ] `ExecutionManager` class created
- [ ] API methods:
  - `submit_order(intent, execution_params)`
  - `cancel_order(order_id, reason)`
  - `replace_order(order_id, new_params, reason)`
  - `amend_order()` (if connector supports)
- [ ] All orders flow through ExecutionManager
- [ ] Emits structured events:
  - `order_submitted`
  - `order_acknowledged`
  - `order_filled`
  - `order_canceled`
  - `order_replaced`
  - `order_stale`
- [ ] Event correlation with intent ID

**Out of Scope:**
- Advanced algos (TWAP, VWAP, Iceberg)
- Multi-exchange routing

---

### US-A3: Portfolio RiskEngine Gate

**As a** prop-style bot
**I want** risk approval before execution
**So that** portfolio rules are enforced consistently across strategies/exchanges

**Waarom:** Filters per coin zijn niet genoeg. Portfolio discipline is "big boys" standard.

**Acceptance Criteria:**
- [ ] `PortfolioRiskEngine` class created
- [ ] Method: `evaluate(intent, portfolio_state) -> RiskDecision`
- [ ] `RiskDecision` contains:
  - `allowed` (bool)
  - `reason_code` (Enum/const from central list)
  - `modified_size` (Decimal, optional)
- [ ] All denials logged with reason + intent details
- [ ] Denial counters tracked per reason
- [ ] Risk rules loaded from YAML config

**Note:** Define central `ReasonCode` enum:
```python
class ReasonCode(str, Enum):
    EXPOSURE_CAP = "EXPOSURE_CAP"
    DRAWDOWN_KILL = "DRAWDOWN_KILL"
    TIME_STOP = "TIME_STOP"
    CORRELATION_BUCKET = "CORRELATION_BUCKET"
    # SmartEntry reasons:
    RSI_EXTREME = "RSI_EXTREME"
    RSI_BLOCK = "RSI_BLOCK"
    VWAP_DEVIATION = "VWAP_DEVIATION"
    ATR_TOO_LOW = "ATR_TOO_LOW"
    ATR_TOO_HIGH = "ATR_TOO_HIGH"
    DEPTH_INSUFFICIENT = "DEPTH_INSUFFICIENT"
    DEPTH_UNAVAILABLE = "DEPTH_UNAVAILABLE"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    MTF_BLOCK = "MTF_BLOCK"
    # Add as needed
```

**Out of Scope:**
- External risk feeds (for now)
- Cross-strategy correlation (single strategy first)

---

## EPIC B — Execution Excellence (Hoogste ROI)

### US-B1: Maker-First + Controlled Taker Fallback

**As an** execution engine
**I want to** prioritize maker orders and allow taker only under strict conditions
**So that** fees stay low and fill probability stays acceptable

**Waarom:** Grid/mean-reversion edge sterft door fees. Maker-first is core voor profitability.

**Acceptance Criteria:**
- [ ] Default: place limit orders with `price_offset_ticks` (maker)
- [ ] Taker fallback triggers only if:
  - `urgency == HIGH` OR
  - `time_to_fill > max_time_to_fill` AND
  - `current_spread_bps < max_taker_spread_bps`
- [ ] Every taker action logged with:
  - `reason` (urgency/timeout)
  - `spread_bps`
  - `expected_fee`
- [ ] Config params:
  - `maker_price_offset_ticks`
  - `max_time_to_fill_seconds`
  - `max_taker_spread_bps`

**Out of Scope:**
- Smart order routing across venues
- Post-only enforcement (depends on connector)

---

### US-B2: Stale Order Detection + Cancel/Replace Policy

**As an** execution engine
**I want to** detect and replace stale orders
**So that** orders stay relevant to current mid price and spread

**Waarom:** "Stale quotes" = dead capital + missed fills. Active order management is prop desk 101.

**Acceptance Criteria:**
- [ ] Stale detection triggers when:
  - `abs(current_mid - order_price) > staleness_threshold_bps` OR
  - `current_spread > order_placed_spread * spread_widen_factor`
- [ ] Replace action:
  - Cancel old order
  - Submit new order at updated price
- [ ] Guards:
  - `max_replaces_per_minute` per symbol
  - `cooldown_seconds` after replace
- [ ] No infinite loops (circuit breaker after N consecutive replaces)
- [ ] Config params:
  - `staleness_threshold_bps`
  - `spread_widen_factor`
  - `max_replaces_per_minute`
  - `replace_cooldown_seconds`

**Out of Scope:**
- Predictive repricing (ML-based)
- Amend orders (use cancel/replace for now)

---

### US-B3: Entry/Exit Laddering (Micro-Slicing)

**As an** execution engine
**I want to** split large intents into a small ladder of limit orders
**So that** I reduce slippage and improve maker fill rate

**Waarom:** Desks "work the order" i.p.v. all-in single price. Lowers market impact.

**Acceptance Criteria:**
- [ ] Ladder parameters configurable:
  - `num_levels` (2-5)
  - `spacing_bps` (price distance between levels)
  - `size_distribution` (equal, pyramidal, top-heavy)
- [ ] Total ladder size equals intent size
- [ ] Each level is a separate limit order
- [ ] Ladder cancellation:
  - If intent invalidated (risk deny, regime change)
  - If time limit exceeded
  - If partial fills + remaining too small
- [ ] Ladder state tracked per intent

**Out of Scope:**
- Dynamic ladder adjustment (static for v1)
- Cross-venue laddering

---

### US-B4: Time-to-Fill Metrics + Adaptive Repricing

**As a** system
**I want to** measure time-to-fill and adjust aggressiveness
**So that** execution quality improves over time

**Waarom:** Feedback loop = competitive advantage. Measure, adapt, improve.

**Acceptance Criteria:**
- [ ] Track per intent:
  - `intent_created_at`
  - `first_fill_at`
  - `fully_filled_at`
  - `time_to_first_fill` (histogram)
  - `time_to_complete` (histogram)
- [ ] Adaptive logic:
  - If `avg_time_to_fill > target`: increase aggressiveness (tighter spread, higher urgency threshold)
  - Never violates `max_taker_spread_bps`
- [ ] Metrics exposed for dashboard
- [ ] Config params:
  - `target_time_to_fill_seconds`
  - `aggressiveness_step_bps`

**Out of Scope:**
- Machine learning models (simple heuristics first)

**Note:** Feature flag recommended:
```yaml
features:
  adaptive_repricing:
    mode: shadow  # observe before live
```

---

## EPIC C — Portfolio Risk (Prop Discipline)

### US-C1: Exposure Limits (Per Coin, Per Exchange, Total)

**As a** risk engine
**I want** exposure caps
**So that** no single coin/exchange dominates risk

**Waarom:** Portfolio risk management = survival. Concentration kills funds.

**Acceptance Criteria:**
- [ ] Risk rules enforced pre-trade:
  - `max_total_exposure_pct` (% of portfolio)
  - `max_exposure_per_coin_pct` (% of portfolio per coin)
  - `max_exchange_exposure_pct` (% of portfolio per exchange)
- [ ] Deny intent if any limit exceeded
- [ ] Monitoring:
  - Real-time exposure tracking
  - Alerts if approaching limits (80%+ utilization)
- [ ] Config example:
  ```yaml
  risk:
    max_total_exposure_pct: 80
    max_exposure_per_coin_pct: 20
    max_exchange_exposure_pct: 50
  ```

**Out of Scope:**
- Sector/asset class limits (future)
- Dynamic limits based on volatility (v2)

---

### US-C2: Drawdown Kill-Switch (Daily)

**As an** operator
**I want** a daily drawdown stop
**So that** worst-case is bounded

**Waarom:** Capital preservation > catching every move. Kill-switches zijn niet-onderhandelbaar.

**Acceptance Criteria:**
- [ ] Track daily equity curve (start of day vs current)
- [ ] If `current_dd_pct > max_daily_dd_pct`:
  - Set `kill_switch_active = True`
  - Disable new entries
  - Allow exits only
  - Send alert (Telegram/log)
- [ ] Reset options:
  - Manual reset command
  - Auto-reset at start of new trading day
  - Cooldown period
- [ ] Config params:
  - `max_daily_dd_pct` (default: 3%)
  - `reset_mode` (manual/auto/cooldown)

**Out of Scope:**
- Weekly/monthly DD tracking (daily first)
- Dynamic threshold adjustment

---

### US-C3: Time-Stop Exit (Risk Trigger + Execution Unwind)

**As a** risk engine + execution system
**I want** max hold time per position with graceful unwind
**So that** mean reversion doesn't become bag-holding

**Waarom:** Grids falen door te lang vasthouden in trending markets. Time-stop is veiligheidsnet.

**Acceptance Criteria:**

**Risk Detection:**
- [ ] Track `position_opened_at` per coin
- [ ] If `position_age > max_hold_seconds`:
  - Generate `unwind_intent` with urgency=HIGH
  - Mark as "time-stop exit" in logs
  - Include hold duration in log

**Execution Unwind:**
- [ ] Maker-first ladder (if time allows)
  - Split into 2-3 levels if size allows
  - Use aggressive pricing (closer to mid)
- [ ] Taker as last resort if:
  - Urgency=HIGH and ladder unfilled
  - Spread within acceptable range

**Config (single block):**
```yaml
time_stop:
  max_hold_seconds: 14400  # 4 hours
  unwind_urgency: HIGH
  unwind_ladder_levels: 2
  max_taker_spread_bps: 50
```

**Out of Scope:**
- Trailing time-stop (static threshold first)
- Profit-dependent hold time (static for v1)
- Partial unwinds (all-or-nothing for v1)

---

### US-C4: Correlation Buckets

**As a** risk engine
**I want** correlation bucket caps
**So that** I avoid hidden concentration

**Waarom:** SOL/AVAX/ADA tegelijk = hetzelfde risico. Bucket management is sophisticated risk.

**Acceptance Criteria:**
- [ ] Define correlation buckets in config:
  ```yaml
  correlation_buckets:
    majors: [BTC, ETH]
    layer1: [SOL, ADA, AVAX, DOT]
    memes: [DOGE, SHIB, PEPE]
    defi: [UNI, AAVE, SNX]
  ```
- [ ] Bucket exposure limits:
  - `max_exposure_per_bucket_pct`
- [ ] Deny intent if bucket cap exceeded
- [ ] Allow manual bucket override (shadow mode first)

**Out of Scope:**
- Dynamic correlation calculation (static config for v1)
- Cross-bucket rebalancing

---

### US-C5: Regime-Aware Risk Posture

**As a** system
**I want** tighter risk in BEAR and looser in CHOP/BULL
**So that** aggressiveness matches market regime

**Waarom:** Risk appetite moet context-aware zijn. BEAR ≠ BULL risk tolerance.

**Acceptance Criteria:**
- [ ] Per-regime risk config:
  ```yaml
  risk:
    BULL:
      max_total_exposure_pct: 80
      max_exposure_per_coin_pct: 25
    CHOP:
      max_total_exposure_pct: 60
      max_exposure_per_coin_pct: 20
    BEAR:
      max_total_exposure_pct: 40
      max_exposure_per_coin_pct: 15
  ```
- [ ] Regime switch logic:
  - Hysteresis: require N consecutive confirmations before switch
  - Log regime change + effective params snapshot
- [ ] No abrupt flip-flopping (cooldown between switches)

**Out of Scope:**
- Intraday regime changes (daily granularity first)

---

## EPIC D — Liquidity & Market Data Quality

### US-D1: LiquidityModel + LiquiditySnapshot

**As a** bot
**I want** a cached `LiquiditySnapshot` per symbol
**So that** risk/execution can use executable liquidity metrics

**Waarom:** Depth/spread moeten first-class signals zijn. Liquidity = executability.

**Acceptance Criteria:**
- [ ] `LiquiditySnapshot` dataclass:
  - `symbol`
  - `depth_score` (available notional within ±X% band)
  - `spread_bps`
  - `mid_price`
  - `timestamp`
- [ ] Cached per symbol with TTL (default: 5 seconds)
- [ ] Computation:
  - `depth_score = min(bid_depth, ask_depth)` within `depth_pct_range`
  - `spread_bps = (ask - bid) / mid * 10000`
- [ ] Fallback: if orderbook unavailable, use last known or None

**Out of Scope:**
- Volume-weighted depth (simple notional first)
- Historical depth tracking (real-time only)

---

### US-D2: SmartEntry Depth Validation (Final Gate)

**As a** SmartEntry gate
**I want** depth validation when orderbook is available
**So that** trades are executable

**Waarom:** Depth check hoort in executability gate, niet in ranking loop. Correcte separation of concerns.

**Acceptance Criteria:**
- [ ] Depth check in SmartEntry:
  - If orderbook available: enforce `required_depth_multiplier * order_size`
  - If orderbook unavailable: skip + log (no deadlock)
- [ ] Rejection reason explicit:
  - `DEPTH_INSUFFICIENT` vs `DEPTH_UNAVAILABLE`
- [ ] Config params:
  - `depth_check_enabled` (bool)
  - `required_depth_multiplier` (float, default: 5.0)

**Current Status:** ✅ Grotendeels geïmplementeerd (Phase 2 Shadow Mode)

**Out of Scope:**
- Predictive depth modeling

---

### US-D3: Orderbook Prefetch (Off → Shadow → Live)

**As a** controller
**I want to** warm orderbooks for top-N candidates
**So that** depth validation is available earlier without spamming WS

**Waarom:** Depth data sneller beschikbaar bij eerste entry, maar moet rate-limited zijn.

**Acceptance Criteria:**
- [ ] Feature modes:
  - `off`: no prefetch
  - `shadow`: log cache status only
  - `live`: subscribe to orderbooks for top-N
- [ ] Config params:
  - `orderbook_prefetch.enabled`
  - `orderbook_prefetch.mode` (off/shadow/live)
  - `orderbook_prefetch.top_n` (default: 3)
  - `orderbook_prefetch.max_subscriptions_per_minute` (default: 6)
- [ ] Rate limit enforcement:
  - Track subscription timestamps
  - Reject if rate exceeded
- [ ] Non-blocking: fire-and-forget subscriptions
- [ ] Shadow mode logs:
  ```
  [PREFETCH][SHADOW] #1 XDC-EUR orderbook_cached=False
  [PREFETCH][SHADOW] #2 DYDX-EUR orderbook_cached=True
  ```

**Current Status:** ✅ Shadow mode geïmplementeerd, live mode pending

**Out of Scope:**
- Predictive prefetch (ML-based)
- Multi-exchange prefetch coordination

---

### US-D4: Liquidity-Based Sizing (v1 Light)

**As a** risk/execution engine
**I want** order size scaled by liquidity
**So that** small books get small orders

**Waarom:** Big boys schalen size op executability. Enorme ROI zonder meer trades.

**Acceptance Criteria:**
- [ ] Compute `liquidity_multiplier`:
  ```python
  multiplier = clamp(
      depth_score / required_depth,
      min_multiplier,
      max_multiplier
  )
  ```
- [ ] Apply to intent size:
  ```python
  effective_size = base_size * liquidity_multiplier
  ```
- [ ] Log multiplier + effective size
- [ ] Config params:
  - `liquidity_sizing.enabled`
  - `liquidity_sizing.min_multiplier` (default: 0.5)
  - `liquidity_sizing.max_multiplier` (default: 1.5)

**Out of Scope:**
- Volume-weighted sizing (depth only for v1)

---

### US-D5: Combined Liquidity Score (Optional)

**As a** ranker
**I want to** combine ticker-volume + depth + spread into `liquidity_score`
**So that** ranking prefers true executable liquidity

**Waarom:** Volume alone is noisy. Depth + spread = better signal.

**Acceptance Criteria:**
- [ ] Compute weighted score:
  ```python
  liquidity_score = (
      w1 * normalized_volume +
      w2 * normalized_depth +
      w3 * (1 - normalized_spread)
  )
  ```
- [ ] Fallback logic:
  - If volume unavailable: adjust weights automatically
  - If depth unavailable: use volume + spread only
- [ ] Configurable weights
- [ ] Use in coin ranking (optional mode)

**Priority:** Low (nice-to-have, after metrics prove depth-first works)

---

## EPIC E — Observability & Metrics (No Big Boys Without This)

### US-E1: Structured Events (JSONL)

**As an** operator
**I want** machine-readable events
**So that** analysis is reliable and automated

**Waarom:** Sturen op data, niet op gevoel. Structured logging = professioneel.

**Acceptance Criteria:**
- [ ] JSONL output for event types:
  - `intent_created`
  - `risk_decision` (allow/deny + reason)
  - `execution_action` (submit/cancel/replace)
  - `order_fill`
  - `order_cancel`
  - `order_replace`
  - `exit_forced` (time-stop/drawdown)
- [ ] Each event includes:
  - `timestamp`
  - `event_type`
  - `correlation_id` (intent_id)
  - `exchange`
  - `symbol`
  - `details` (JSON object)
- [ ] Events written to separate log file or stdout

**Out of Scope:**
- Real-time streaming to external systems (file-based first)

---

### US-E2: Metrics Counters & Histograms

**As a** system owner
**I want** metrics for decisions and performance
**So that** tuning is data-driven

**Waarom:** Fill rate, slippage, time-to-fill zijn je echte edge. Measure everything.

**Acceptance Criteria:**
- [ ] Counters:
  - `intents_created_total`
  - `intents_denied_total` (by reason: EXPOSURE, DRAWDOWN, etc.)
  - `orders_submitted_total`
  - `orders_filled_total`
  - `orders_canceled_total`
  - `orders_replaced_total`
- [ ] Histograms:
  - `time_to_fill_seconds`
  - `slippage_bps`
  - `spread_bps_at_entry`
  - `depth_score`
- [ ] Export options:
  - Periodic log dump (JSON)
  - HTTP endpoint (Prometheus-compatible)

**Out of Scope:**
- External metrics aggregation (Grafana, etc.)

---

### US-E3: "Why No Trade?" Summary Report

**As a** trader
**I want** hourly breakdown of rejection reasons
**So that** tuning is data-driven

**Waarom:** "Waarom trade ik niet?" is de belangrijkste vraag. Transparantie = vertrouwen.

**Acceptance Criteria:**
- [ ] Aggregate rejection reasons per hour:
  - RSI blocks
  - VWAP blocks
  - ATR blocks
  - Depth blocks
  - Multi-timeframe blocks
  - Exposure caps
  - Drawdown kill-switch
- [ ] Output format:
  ```
  [WHY-NO-TRADE] Hour 14:00-15:00
    Total intents: 120
    Denied: 85 (70.8%)
      - RSI_EXTREME: 30 (25.0%)
      - ATR_TOO_LOW: 25 (20.8%)
      - VWAP_DEVIATION: 15 (12.5%)
      - DEPTH_INSUFFICIENT: 10 (8.3%)
      - EXPOSURE_CAP: 5 (4.2%)
  ```
- [ ] Per exchange + per regime breakdown
- [ ] Summary printed every X minutes (configurable)

**Out of Scope:**
- Real-time dashboard (log-based first)

---

## EPIC F — Testing, Replay, Safe Rollouts

### US-F1: Feature Flags (Off/Shadow/Live)

**As a** dev
**I want** per-feature flags
**So that** I can roll out safely

**Waarom:** Voorkomt regressies. Rollout zoals pros: observe first, act later.

**Acceptance Criteria:**
- [ ] Every major feature supports modes:
  - `off`: feature disabled
  - `shadow`: logs decisions but doesn't act
  - `live`: full execution
- [ ] Feature flag config:
  ```yaml
  features:
    execution_laddering: live
    liquidity_sizing: shadow
    time_stop_unwind: off
  ```
- [ ] Flag snapshot logged on startup
- [ ] Shadow mode produces full observability without side effects

**Out of Scope:**
- Runtime flag changes (restart required for v1)

---

### US-F2: Deterministic Replay Harness (v1)

**As a** dev
**I want** replay from recorded market snapshots
**So that** I can reproduce bugs and regressions

**Waarom:** "Bugs reproduceren" in 1 command is big-boy engineering.

**Acceptance Criteria:**
- [ ] Market data recorder:
  - Record per tick: timestamp, symbol, mid, spread_bps, top-of-book
  - Record candle updates
  - Record order events (fills, cancels)
  - Output: JSONL or Parquet
- [ ] Replay runner:
  - CLI: `replay --file <dataset> --config <cfg>`
  - Feeds recorded data into bot pipeline
  - Produces same intents/decisions (within tolerance)
- [ ] Determinism controls:
  - Fixed random seeds
  - Injectable clock
  - Config snapshot embedded in output
- [ ] Replay report:
  - Intent counts
  - Denials by reason
  - Fills, slippage stats
  - Diff tool: compare run A vs run B

**Priority:** Medium (after core execution works)

**Out of Scope:**
- Real-time replay (offline batch first)
- Multi-exchange coordination

---

### US-F3: Unit Tests + Golden Cases (RiskEngine)

**As a** dev
**I want** comprehensive test coverage for risk rules
**So that** risk doesn't silently break

**Waarom:** Risk regressies zijn duur. Tests maken je echt production-grade.

**Acceptance Criteria:**

**Golden Cases (deterministic):**
- [ ] Test per rule with known inputs → expected outputs:
  - Exposure caps (per coin, per exchange, total)
  - Drawdown kill-switch
  - Correlation buckets
  - Time-stop exits
- [ ] Test each regime config (BULL/CHOP/BEAR)
- [ ] Assert exact reason codes (use ReasonCode enum)
- [ ] Edge cases: boundary values (99% vs 100% exposure, etc.)

**Out of Scope:**
- Integration tests with live exchanges (unit tests only)

---

### US-F4: Property-Based / Fuzz Tests (Optional Advanced)

**As a** dev
**I want** property-based tests for edge cases
**So that** I discover crashes before production

**Waarom:** Randomized testing ontdekt rare edge cases (negatieve sizes, NaNs, extreme spikes).

**Acceptance Criteria:**
- [ ] Use `hypothesis` library
- [ ] Generate random:
  - Portfolio states (valid + malformed)
  - Intents (valid + invalid sizes/prices)
  - Market conditions (zero depth, negative spreads, NaN prices)
- [ ] Invariants tested:
  - Risk engine never crashes (no unhandled exceptions)
  - All denials have reason codes
  - No silent failures (all errors logged)
  - Exposure tracking never goes negative

**Priority:** Low (nice-to-have after golden cases pass)

**Out of Scope:**
- Generative testing for ML models (not applicable)

---

## EPIC G — Operations & Reliability

### US-G1: WS Health Checks + Auto-Recovery

**As a** 24/7 bot
**I want** detect stale feeds and recover
**So that** I don't trade on stale data

**Waarom:** 24/7 stability is edge. WS drops = missed opportunities or bad decisions.

**Acceptance Criteria:**
- [ ] Health checks:
  - Orderbook TTL (last update timestamp)
  - Trades stream TTL
  - Heartbeat/ping-pong
- [ ] Stale detection:
  - If no update for > TTL: mark unhealthy
  - Log warning
- [ ] Auto-recovery:
  - Reconnect with exponential backoff
  - Max retries configurable
- [ ] Safe behavior during unhealthy state:
  - Pause new entries
  - Allow exits
  - Log: "PAUSED: WS unhealthy"

**Out of Scope:**
- Multi-path redundancy (single WS first)

---

### US-G2: Safe-Mode on Missing Critical Data

**As a** system
**I want** safe-mode when key inputs are missing
**So that** I avoid blind trading

**Waarom:** Missing candles/prices = danger zone. Better safe than sorry.

**Acceptance Criteria:**
- [ ] Safe-mode triggers:
  - Candles missing (< required lookback)
  - WS stale (see US-G1)
  - Price data unavailable
- [ ] Safe-mode behavior:
  - Disable new entries
  - Allow exits
  - Log: "SAFE_MODE: <reason>"
- [ ] Recovery:
  - Auto-exit safe-mode when data restored
  - Cooldown period after recovery

**Out of Scope:**
- Partial safe-mode (all-or-nothing for v1)

---

### US-G3: Config Versioning & Diff Report

**As an** operator
**I want** config hash + diff on startup
**So that** I always know what's running

**Waarom:** "Wat draait er?" moet 100% duidelijk zijn. Diff = accountability.

**Acceptance Criteria:**
- [ ] On startup:
  - Compute config hash (MD5/SHA256)
  - Log hash + version tag
  - Print key params (top 20 most important)
- [ ] If config changed from last run:
  - Show diff of changed params
  - Highlight critical changes (risk limits, feature flags)
- [ ] Store config snapshot per run:
  - Timestamped YAML file
  - Linked to run ID

**Out of Scope:**
- Config validation (assume correct for v1)
- Hot-reload (restart required)

---

## 🚨 Copilot Guardrail Prompt (Gebruik bij elke sprint)

> **RULES FOR COPILOT:**
> 1. **Do not refactor unrelated modules** — stay in scope
> 2. **Implement only the current story** — no "helpful extras"
> 3. **Preserve current trading behavior** — unless story explicitly changes it
> 4. **Add off/shadow/live flags** for behavior changes
> 5. **Add explicit logs with reason codes** for every decision
> 6. **Test your changes** — run existing test suite before commit
> 7. **Update this backlog** — mark stories as ✅ when done

---

## 📊 Success Metrics (What "Done" Looks Like)

| Metric | Target | Current |
|--------|--------|---------|
| Fill rate (maker) | >70% | TBD |
| Avg time-to-fill | <30s | TBD |
| Slippage (median) | <5 bps | TBD |
| Rejection rate | <40% | ~70% |
| Drawdown max | <3% daily | TBD |
| WS uptime | >99% | TBD |
| Tests passing | 100% | ~99% |

---

## 📚 References & Context

- **Current Status:** Phase 2 Shadow Mode complete, SmartEntry v2.0 active
- **Active Filters:** RSI, VWAP, ATR, Multi-Timeframe, Depth (shadow)
- **Known Issues:** Orderbook prefetch needs live mode, ATR thresholds too strict
- **Architecture:** Hummingbot Strategy V2, GridExecutor, TrendCalculator
- **Exchanges:** Kraken (EUR), Bitget (USDT)

---

**Last Updated:** 2025-12-24
**Owner:** Mo
**Status:** 🔄 In Progress (Phase 2 complete, Phase 3 pending)
