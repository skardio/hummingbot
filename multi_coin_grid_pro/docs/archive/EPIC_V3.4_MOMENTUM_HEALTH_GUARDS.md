# EPIC v3.4 — "Momentum Health Guards"
## VWAP Slope + Parabolic Detector for Kraken & Bitget

**Status**: ✅ LIVE in Production (Stories 1-11 complete)
**Created**: 2026-01-02
**Deployed**: 2026-01-03
**Priority**: HIGH - Prevents top-buying during blow-off tops

---

## Executive Summary

### Problem
Bot currently uses static VWAP deviation limits (12-20%) to allow bull market entries. However, this enables entries during **parabolic blow-off tops** where:
- Price is +25% above VWAP (deviation check passes)
- VWAP slope is flattening (momentum dying)
- Acceleration is extreme (unsustainable)
- Entry results in immediate drawdown

**Example**: PEPE +43% on 2026-01-02 with flat VWAP slope → top-buy risk

### Solution
Add **momentum health guards** that detect exhaustion conditions:
1. **VWAP Slope Guard**: Reject if price far above VWAP BUT VWAP slope flattening
2. **Parabolic Detector**: Cooldown symbol when acceleration + deviation both extreme
3. **Shadow Mode**: Safe rollout with observation-only phase

### Success Metrics
- Reduce drawdowns from top-buys by >50%
- Maintain 80%+ of valid bull entries (avoid false rejections)
- Zero production incidents during rollout (shadow → live)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Indicator Service (momentum_indicators.py)             │
│  ├─ VWAP deviation %                                    │
│  ├─ VWAP slope 15m %                                    │
│  ├─ Acceleration 5m/15m %                               │
│  └─ Handles Kraken/Bitget candle sources               │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  SmartEntry Filter Integration                          │
│  ├─ VWAP Slope Guard (deviation-gated)                 │
│  ├─ Parabolic Detector (3-condition trigger)           │
│  └─ Per-symbol Cooldown Blacklist                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Regime-Aware Threshold Resolver                        │
│  ├─ Precedence: coin_profile > regime > baseline       │
│  ├─ Hard safety floors (prevent disabling)             │
│  └─ Supports shadow/live mode per guard                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Observability Layer                                    │
│  ├─ JSON structured events (entry_guard_evaluation)    │
│  ├─ Debug traces with all metrics                      │
│  └─ Rate-limited logging (avoid spam)                  │
└─────────────────────────────────────────────────────────┘
```

---

## Stories

### Story 1 — Add Unified Indicator Service (VWAP + slopes + accel windows) ✅

**As a** strategy developer
**I want** a single indicator module that computes VWAP deviation, VWAP slope (15m), and acceleration (5m/15m)
**So that** SmartEntry and coin ranking use consistent numbers across Kraken and Bitget

#### Acceptance Criteria

- [x] New module `multi_coin_grid_pro/indicators/momentum_indicators.py` exposes:
  - `vwap_deviation_pct` (current price vs VWAP)
  - `vwap_slope_15m_pct` (VWAP momentum: now vs 15m ago)
  - `accel_5m_pct` (price acceleration over 5 minutes)
  - `accel_15m_pct` (price acceleration over 15 minutes)

- [x] Works with candle sources for both connectors:
  - **Kraken**: OHLC from connector data feed (EUR spot)
  - **Bitget**: OHLC/perp candles (USDT spot/futures)
  - Same interface for both exchanges

- [x] Handles missing candles gracefully:
  - Returns `None` with descriptive reason ("insufficient history", "no VWAP data")
  - Does not crash selection loop
  - Logs warning once per symbol (rate-limited)

- [x] Unit tests for:
  - Normal values (positive/negative slopes)
  - Insufficient history (warmup period < 15 minutes)
  - Flat price series (slope = 0)
  - Edge cases: missing VWAP, NaN prices, zero division

#### Implementation Notes

**VWAP Slope Calculation:**
```python
vwap_slope_15m_pct = (vwap_now / vwap_15m_ago - 1) * 100
```

**Acceleration Calculation:**
```python
# Reuse existing "up accel" logic or implement:
accel_5m_pct = (price_now / price_5m_ago - 1) * 100
accel_15m_pct = (price_now / price_15m_ago - 1) * 100
```

**Metrics Context:**
```python
@dataclass
class MomentumMetrics:
    timestamp: float
    symbol: str
    vwap_deviation_pct: Optional[float]
    vwap_slope_15m_pct: Optional[float]
    accel_5m_pct: Optional[float]
    accel_15m_pct: Optional[float]
    reason: Optional[str]  # If any metric is None
```

**Files to Create:**
- `multi_coin_grid_pro/indicators/__init__.py`
- `multi_coin_grid_pro/indicators/momentum_indicators.py`
- `multi_coin_grid_pro/tests/unit/test_momentum_indicators.py`

---

### Story 2 — Implement VWAP Slope Guard (Regime-aware, deviation-gated) ✅

**As a** trader running grid strategies
**I want** to reject entries when price is far above VWAP while VWAP slope is flat/negative
**So that** the bot avoids buying near blow-off tops

#### Acceptance Criteria

- [x] New config section in `config.prod.yaml` and `spot_grid_bitget.yaml`:
```yaml
vwap_slope_guard:
  enabled: true
  mode: shadow  # shadow|live
  window_min: 15
  deviation_high_pct:
    baseline: 15.0
    BULL: 18.0
    CHOP: 12.0
    BEAR: 10.0
  slope_min_pct_15m:
    baseline: 0.10
    BULL: 0.05
    CHOP: 0.15
    BEAR: 0.20
  log_details: true
```

- [x] Guard triggers only if `vwap_deviation_pct >= deviation_high_pct`
  - Example: PEPE dev=19.2% and BULL deviation_high=18.0% → check slope
  - If dev=10.5% and threshold=15.0% → skip guard (not far enough from VWAP)

- [x] Reject if `vwap_slope_15m_pct <= slope_min_pct_15m`
  - Example: slope=0.03% and BULL slope_min=0.05% → REJECT
  - Rationale: VWAP momentum is dying while price extended

- [x] Adds debug_trace reject reason:
  - `VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH`
  - Include: deviation, slope, thresholds used

- [x] Adds structured event (see Story 6)

#### Implementation Notes

**Integration Point:**
`multi_coin_grid_pro/filters/smart_entry_filter.py` after existing VWAP deviation check:

```python
# Existing VWAP deviation check (bidirectional)
if abs(vwap_dev_pct) > self.config.vwap_max_deviation_pct:
    return False, f"{symbol}: NO BUY – VWAP dev {vwap_dev_pct:.2f}%"

# NEW: VWAP Slope Guard (only if deviation HIGH on upside)
if self.config.vwap_slope_guard.enabled and vwap_dev_pct > 0:
    threshold = self._resolve_slope_threshold(symbol, regime)
    if vwap_dev_pct >= threshold["deviation_high_pct"]:
        if vwap_slope_15m_pct <= threshold["slope_min_pct_15m"]:
            if self.config.vwap_slope_guard.mode == "live":
                return False, (
                    f"{symbol}: NO BUY – VWAP slope flat while extended "
                    f"(dev={vwap_dev_pct:.1f}%, slope={vwap_slope_15m_pct:.2f}%)"
                )
            else:  # shadow mode
                self.logger.info(f"[SHADOW] Would reject {symbol} by slope guard")
```

**Example Log Output:**
```
[ENTRY] PEPE-EUR dev=19.2% slope15=0.03% thresh=0.05% => REJECT VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH
```

---

### Story 3 — Implement Parabolic Detector + Cooldown Blacklist (Per symbol) ✅

**As a** risk-aware bot operator
**I want** to detect parabolic conditions and apply a cooldown per symbol
**So that** the bot stops repeatedly trying to enter during exhaustion

#### Acceptance Criteria

- [x] New config section:
```yaml
parabolic_detector:
  enabled: true
  mode: shadow  # shadow|live
  accel_5m_min_pct:
    baseline: 2.5
    BULL: 3.0
    CHOP: 2.2
    BEAR: 2.0
  accel_15m_min_pct:
    baseline: 6.0
    BULL: 7.0
    CHOP: 5.0
    BEAR: 4.0
  vwap_dev_min_pct:
    baseline: 18.0
    BULL: 22.0
    CHOP: 14.0
    BEAR: 12.0
  cooldown_sec: 1800  # 30 minutes
  blacklist_scope: session  # session|persistent
  log_details: true
```

- [x] Parabolic condition (ALL must be true):
  1. `vwap_deviation_pct >= vwap_dev_min`
  2. `accel_5m_pct >= accel_5m_min`
  3. `accel_15m_pct >= accel_15m_min`

- [x] If parabolic detected:
  - Add symbol to session blacklist with cooldown timer
  - Log structured event: `PARABOLIC_DETECTED_COOLDOWN`
  - Reject entry with reason including cooldown remaining

- [x] Debug trace includes all values:
  - Symbol, regime, deviation, slope, accel5, accel15
  - Thresholds used
  - Cooldown remaining (if applicable)

- [x] Cooldown management:
  - In-memory dict: `{symbol: expiry_timestamp}`
  - Check before entry attempt
  - Remove expired entries automatically

#### Implementation Notes

**Data Structure:**
```python
@dataclass
class ParabolicBlacklist:
    blacklist: Dict[str, float] = field(default_factory=dict)

    def add(self, symbol: str, cooldown_sec: int):
        expiry = time.time() + cooldown_sec
        self.blacklist[symbol] = expiry

    def is_blocked(self, symbol: str) -> Tuple[bool, Optional[int]]:
        if symbol not in self.blacklist:
            return False, None
        expiry = self.blacklist[symbol]
        if time.time() >= expiry:
            del self.blacklist[symbol]
            return False, None
        remaining = int(expiry - time.time())
        return True, remaining
```

**Example Log Output:**
```
[ENTRY] SUI-EUR dev=22.1% slope15=0.02% a5=3.2% a15=7.9% => REJECT PARABOLIC_COOLDOWN(1800s)
```

**Files to Modify:**
- `multi_coin_grid_pro/filters/smart_entry_filter.py` (add parabolic check)
- `multi_coin_grid_pro/multi_coin_grid_v2.py` (initialize blacklist)

---

### Story 4 — Exchange Nuance: Bitget USDT "Funding / Spread / Contract" Guard Integration ✅

**As a** Bitget futures operator
**I want** the entry guard system to include Bitget-specific checks
**So that** parabolic detection doesn't greenlight trades with insane spread or contract constraints

#### Acceptance Criteria

- [x] For **Bitget only** (spot_grid_bitget.yaml):
  - Spread/slippage check runs **BEFORE** slope/parabolic checks
  - Min notional/contract size constraints verified
  - Order of checks: spread → notional → slope guard → parabolic detector

- [x] If spread check fails:
  - Slope/parabolic computations may still run (for metrics logging)
  - But must not override spread rejection
  - Log: "REJECTED by spread, parabolic metrics: [...]"

- [x] Structured event includes Bitget-specific fields:
  - `connector_name`: "bitget"
  - `market_type`: "spot" or "perp"
  - `notional`: order value in USDT
  - `contract_size`: if applicable (perp only)
  - `spread_bps`: basis points

#### Implementation Notes

**Check Order in SmartEntry:**
```python
# 1. Spread check (Bitget specific)
if connector_name == "bitget":
    spread_ok, spread_reason = self._check_spread(symbol)
    if not spread_ok:
        return False, spread_reason  # Early exit

# 2. Notional size check (all exchanges)
notional_ok, notional_reason = self._check_min_notional(symbol, price, amount)
if not notional_ok:
    return False, notional_reason

# 3. VWAP slope guard (both exchanges)
slope_ok, slope_reason = self._check_vwap_slope_guard(symbol, metrics, regime)
if not slope_ok:
    return False, slope_reason

# 4. Parabolic detector (both exchanges)
parabolic_ok, parabolic_reason = self._check_parabolic_detector(symbol, metrics, regime)
if not parabolic_ok:
    return False, parabolic_reason
```

**Bitget Spread Limits** (from existing config):
- Normal: 0.25% max
- High volatility: 0.40% max
- Extreme: 0.50% max (with warning)

---

### Story 5 — Regime-aware Threshold Resolver (Coin profile overrides can't break guards) ✅

**As a** strategy maintainer
**I want** a clean precedence system for thresholds (coin_profile > regime > baseline)
**So that** coin profiles cannot accidentally disable safety guards

#### Acceptance Criteria

- [x] Add resolver function:
```python
def resolve_threshold(
    symbol: str,
    key: str,
    regime: str,
    config: ConfigDict
) -> float:
    """
    Resolve threshold with precedence:
    1. Coin profile (if exists)
    2. Regime-specific (BULL/CHOP/BEAR)
    3. Baseline

    Enforces hard safety floors for critical guards.
    """
```

- [x] Hard safety floors (cannot be overridden):
  - `slope_min_pct_15m`: Cannot be < 0.01% (prevents disabling)
  - `accel_5m_min_pct`: Cannot be < 1.0% (too low = false positives)
  - `vwap_dev_min_pct`: Cannot be < 8.0% (must be meaningful deviation)
  - `cooldown_sec`: Cannot be < 300 (5 minutes minimum)

- [x] Validation on config load:
  - Warn if coin profile violates safety floors
  - Auto-correct to floor value with log warning
  - Example: "PEPE slope_min overridden from 0.00% to 0.01% (safety floor)"

- [x] Unit tests for:
  - Precedence order (coin > regime > baseline)
  - Safety floor enforcement
  - Missing values fallback

#### Implementation Notes

**Config Structure Example:**
```yaml
# Baseline defaults
vwap_slope_guard:
  slope_min_pct_15m:
    baseline: 0.10
    BULL: 0.05
    CHOP: 0.15
    BEAR: 0.20

# Regime overrides (automatically applied)
adaptive_regime_filters:
  BULL:
    vwap_slope_guard:
      slope_min_pct_15m: 0.05  # More lenient in bull

# Coin profile overrides (highest priority)
coin_profiles:
  PEPE-EUR:
    vwap_slope_guard:
      slope_min_pct_15m: 0.03  # Even more lenient for meme coins
      # But cannot go below 0.01% (safety floor)
```

**Resolver Implementation:**
```python
SAFETY_FLOORS = {
    "slope_min_pct_15m": 0.01,
    "accel_5m_min_pct": 1.0,
    "accel_15m_min_pct": 3.0,
    "vwap_dev_min_pct": 8.0,
    "cooldown_sec": 300,
}

def resolve_threshold(symbol, key, regime, config):
    # 1. Check coin profile
    if symbol in config.coin_profiles:
        value = config.coin_profiles[symbol].get(key)
        if value is not None:
            floor = SAFETY_FLOORS.get(key)
            if floor and value < floor:
                logger.warning(f"{symbol} {key}={value} below floor {floor}, using floor")
                return floor
            return value

    # 2. Check regime-specific
    if regime in config.adaptive_regime_filters:
        value = config.adaptive_regime_filters[regime].get(key)
        if value is not None:
            return value

    # 3. Fallback to baseline
    return config.get(key + "_baseline", SAFETY_FLOORS.get(key, 0))
```

---

### Story 6 — Observability: JSON structured events for Entry Guard Decisions ✅

**As a** bot operator
**I want** machine-readable JSON events for each guard decision
**So that** I can audit why entries were accepted/rejected and tune thresholds

#### Acceptance Criteria

- [x] Event type: `entry_guard_evaluation`

- [x] Event fields (minimum):
```json
{
  "event_type": "entry_guard_evaluation",
  "timestamp": 1704196800.123,
  "connector": "kraken",
  "symbol": "PEPE-EUR",
  "regime": "BULL",
  "decision": "REJECTED",
  "reject_reason": "VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH",
  "metrics": {
    "vwap_deviation_pct": 19.2,
    "vwap_slope_15m_pct": 0.03,
    "accel_5m_pct": 2.1,
    "accel_15m_pct": 5.8
  },
  "thresholds": {
    "deviation_high_pct": 18.0,
    "slope_min_pct_15m": 0.05,
    "accel_5m_min_pct": 3.0,
    "accel_15m_min_pct": 7.0
  },
  "cooldown_remaining_sec": null
}
```

- [x] Events written to `logs/events/` directory:
  - File pattern: `entry_guards_YYYYMMDD.jsonl`
  - One JSON object per line (JSONL format)
  - Rotates daily

- [x] Events rate-limited:
  - Max 1 event per symbol per 60 seconds (avoid spam when scanning 50 coins)
  - Separate counters for ACCEPTED vs REJECTED
  - Always log first occurrence per symbol per session

#### Implementation Notes

**Event Emitter:**
```python
class EntryGuardEventEmitter:
    def __init__(self, log_dir: str = "logs/events"):
        self.log_dir = log_dir
        self.rate_limiter = {}  # {symbol: last_logged_ts}

    def emit(self, event: dict, force: bool = False):
        symbol = event["symbol"]
        now = time.time()

        # Rate limiting (60 seconds per symbol)
        if not force:
            last_logged = self.rate_limiter.get(symbol, 0)
            if now - last_logged < 60:
                return  # Skip

        self.rate_limiter[symbol] = now

        # Write to JSONL
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"{self.log_dir}/entry_guards_{date_str}.jsonl"
        os.makedirs(self.log_dir, exist_ok=True)

        with open(filename, "a") as f:
            f.write(json.dumps(event) + "\n")
```

**Integration:**
- Call after each guard check (slope, parabolic, etc.)
- Include decision, reason, all metrics, thresholds
- Force log on first occurrence or cooldown trigger

---

### Story 7 — Backtest/Replay Harness Hook (Offline evaluation mode)

**As a** developer
**I want** a replay mode that runs the guard logic on historical candles
**So that** I can validate blow-off detection without risking live capital

#### Acceptance Criteria

- [ ] CLI flag or config: `guards_replay_mode.enabled: true`

- [ ] Reads candle snapshots:
  - Source: existing market data collection (`data/market_data.db`)
  - Or: CSV export from TradingView / exchange API
  - Minimum: symbol, timestamp, open, high, low, close, volume, vwap

- [ ] Produces summary report:
```json
{
  "replay_period": "2025-12-15 to 2026-01-01",
  "total_candles": 15840,
  "total_entry_attempts": 347,
  "rejections": {
    "vwap_slope_guard": 23,
    "parabolic_detector": 41,
    "other": 12
  },
  "false_positives": 7,  # Manual label optional
  "true_positives": 57,
  "symbols_analyzed": ["PEPE-EUR", "SUI-EUR", "DOT-EUR", ...],
  "worst_false_positive": {
    "symbol": "ADA-EUR",
    "timestamp": "2025-12-20T14:30:00Z",
    "reason": "Rejected by slope guard but +15% in next 4h"
  }
}
```

- [ ] Exports report to JSON:
  - File: `logs/replay_reports/guards_replay_YYYYMMDD_HHMMSS.json`
  - Includes per-symbol breakdown
  - Includes threshold tuning suggestions (optional)

- [ ] Minimal replay if no harness exists:
  - "Run on last N candles per symbol"
  - N = 100 candles (25 hours of 15m data)
  - Compare guard decisions to actual price action

#### Implementation Notes

**Replay Script:**
```python
# multi_coin_grid_pro/tools/replay_entry_guards.py

def replay_guards_on_history(
    symbols: List[str],
    start_date: str,
    end_date: str,
    config_path: str
) -> dict:
    """
    Load historical candles and run SmartEntry guard logic.
    Returns summary dict with rejection counts and accuracy.
    """
    pass
```

**Usage:**
```bash
python -m multi_coin_grid_pro.tools.replay_entry_guards \
    --symbols PEPE-EUR,SUI-EUR,DOT-EUR \
    --start 2025-12-15 \
    --end 2026-01-01 \
    --config multi_coin_grid_pro/config/config.prod.yaml \
    --output logs/replay_reports/
```

**False Positive Detection** (optional):
- If rejected by guard but price +X% in next 4h → potential false positive
- Threshold: X = 10% for BULL regime, 5% for CHOP
- Manual review recommended

---

### Story 8 — Safe Defaults + Rollout Controls (Shadow → Live) ✅

**As a** cautious operator
**I want** to enable guards in shadow mode first and then switch to live
**So that** I can confirm behavior before it blocks real trades

#### Acceptance Criteria

- [x] Each guard supports `mode: shadow|live`:
```yaml
vwap_slope_guard:
  enabled: true
  mode: shadow  # Start here

parabolic_detector:
  enabled: true
  mode: shadow  # Start here
```

- [x] **Shadow mode** behavior:
  - Logs decision + reason (INFO level)
  - Does NOT block entry
  - Emits structured event with `mode: "shadow"`
  - Prefix: `[SHADOW]` in all log lines

- [x] **Live mode** behavior:
  - Actively rejects entry
  - Triggers cooldown (parabolic detector)
  - Emits structured event with `mode: "live"`
  - Prefix: `[LIVE]` in all log lines

- [x] **Rollout plan** document in repo:
  - Day 1-2: Enable shadow mode on both exchanges
  - Day 3: Review logs, tune thresholds if needed
  - Day 4: Switch to live mode (one exchange at a time)
  - Day 5: Monitor for 24h, confirm no false rejections
  - Day 6: Enable on second exchange

- [x] Safe defaults for initial rollout:
  - All guards: `mode: shadow`
  - Thresholds: Conservative (fewer rejections)
  - Cooldown: 1800s (30 minutes)
  - Log details: Enabled

#### Implementation Notes

**Shadow Mode Log Example:**
```
[2026-01-02 14:23:45] INFO [SHADOW] PEPE-EUR: Would reject by VWAP_SLOPE_FLAT (dev=19.2%, slope=0.03%)
[2026-01-02 14:23:45] INFO [SHADOW] Entry proceeds despite shadow rejection
```

**Live Mode Log Example:**
```
[2026-01-02 14:23:45] INFO [LIVE] PEPE-EUR: REJECTED by VWAP_SLOPE_FLAT (dev=19.2%, slope=0.03%)
[2026-01-02 14:23:45] INFO [LIVE] Entry blocked, cooldown not applied (slope guard only rejects, no cooldown)
```

**Rollout Checklist:**
```markdown
## EPIC v3.4 Rollout Checklist

### Phase 1: Shadow Mode (Days 1-2)
- [ ] Deploy with all guards in shadow mode
- [ ] Monitor logs for 24 hours
- [ ] Collect JSON events for analysis
- [ ] Verify no crashes or performance issues

### Phase 2: Analysis (Day 3)
- [ ] Count rejections per guard type
- [ ] Identify false positives (manual review)
- [ ] Tune thresholds if >20% false positive rate
- [ ] Document edge cases

### Phase 3: Staged Live Rollout (Days 4-6)
- [ ] Day 4: Enable live mode on Kraken only
- [ ] Day 5: Monitor for 24h, confirm <5% false rejections
- [ ] Day 6: Enable live mode on Bitget
- [ ] Day 7: Full production monitoring

### Phase 4: Optimization (Week 2)
- [ ] Run replay on 1 month history
- [ ] Adjust regime-specific thresholds
- [ ] Add coin profile overrides for outliers
- [ ] Document tuning in EPIC_V3.4_TUNING_LOG.md
```

---

### Story 9 — Dual-Window Confirmation (5m + 15m slope) to Reduce False Positives ✅

**As a** bot operator
**I want** VWAP slope rejections only when short-term AND medium-term momentum is flattening
**So that** we don't reject healthy bull continuations

#### Problem Statement

Single-window VWAP slope guard (15m only) may reject healthy bull trends when:
- 15m VWAP slope temporarily flattens due to consolidation
- But 5m VWAP slope is still rising (momentum intact)
- This creates false rejections during healthy pullbacks

**Solution**: Require BOTH 5m and 15m slopes to be flat before rejecting.

#### Acceptance Criteria

- [x] Extend `vwap_slope_guard` config to include 5m window:
```yaml
vwap_slope_guard:
  enabled: true
  mode: shadow
  dual_confirmation: true  # NEW: require both windows
  slope_min_pct_5m:
    baseline: 0.05
    BULL: 0.00    # Allow flat 5m in bull (lenient)
    CHOP: 0.05
    BEAR: 0.10
  slope_min_pct_15m:
    baseline: 0.10
    BULL: 0.05
    CHOP: 0.15
    BEAR: 0.20
```

- [x] Rejection logic (when `dual_confirmation: true`):
  1. Check if `vwap_deviation_pct >= deviation_high_pct` (existing)
  2. **AND** `vwap_slope_5m_pct <= slope_min_pct_5m`
  3. **AND** `vwap_slope_15m_pct <= slope_min_pct_15m`
  4. Only reject if ALL three conditions true

- [x] Test scenarios:
  - ✅ **15m flat + 5m rising**: PASS (healthy consolidation)
  - ✅ **15m flat + 5m flat**: REJECT (true blow-off top)
  - ✅ **15m rising + 5m flat**: PASS (temporary 5m pause)
  - ✅ **Both rising**: PASS (strong trend)

- [x] Structured event includes both slopes:
```json
{
  "reject_reason": "VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH",
  "metrics": {
    "vwap_slope_5m_pct": 0.02,
    "vwap_slope_15m_pct": 0.03,
    "vwap_deviation_pct": 19.2
  },
  "thresholds": {
    "slope_min_5m": 0.00,
    "slope_min_15m": 0.05
  }
}
```

- [x] Backward compatibility:
  - If `dual_confirmation: false` → use 15m only (Story 2 behavior)
  - Default: `dual_confirmation: true` (recommended)

#### Implementation Notes

**Indicator Extension** (Story 1):
```python
# Add to MomentumMetrics dataclass
vwap_slope_5m_pct: Optional[float]  # NEW
vwap_slope_15m_pct: Optional[float]

# Calculation
vwap_slope_5m_pct = (vwap_now / vwap_5m_ago - 1) * 100
```

**Guard Logic** (SmartEntry Filter):
```python
if self.config.vwap_slope_guard.enabled and vwap_dev_pct > 0:
    threshold = self._resolve_slope_threshold(symbol, regime)

    if vwap_dev_pct >= threshold["deviation_high_pct"]:
        if self.config.vwap_slope_guard.dual_confirmation:
            # Both windows must be flat
            slope_5m_flat = vwap_slope_5m_pct <= threshold["slope_min_pct_5m"]
            slope_15m_flat = vwap_slope_15m_pct <= threshold["slope_min_pct_15m"]

            if slope_5m_flat and slope_15m_flat:
                reason = f"VWAP dual slope flat (5m={vwap_slope_5m_pct:.2f}%, 15m={vwap_slope_15m_pct:.2f}%)"
                return self._handle_rejection(symbol, reason, mode)
        else:
            # Single window (15m only - backward compat)
            if vwap_slope_15m_pct <= threshold["slope_min_pct_15m"]:
                reason = f"VWAP slope flat (15m={vwap_slope_15m_pct:.2f}%)"
                return self._handle_rejection(symbol, reason, mode)
```

**Why This Matters:**
- Reduces false positives by 40-60% (estimated)
- Allows healthy consolidation during bull runs
- Still catches true blow-off tops (both windows flat)

**Example Scenarios:**

| Scenario | 5m Slope | 15m Slope | Deviation | Decision | Reason |
|----------|----------|-----------|-----------|----------|--------|
| Healthy consolidation | +0.15% | +0.02% | 19% | ✅ PASS | 5m still rising |
| Blow-off top | -0.05% | +0.01% | 22% | ❌ REJECT | Both flat/negative |
| Strong trend | +0.40% | +0.25% | 25% | ✅ PASS | Both rising |
| Temporary pause | +0.03% | +0.18% | 18% | ✅ PASS | 15m still strong |

---

### Story 10 — Cooldown Persistence in SQLite (Restart-Safe + TTL Cleanup) ✅

**As a** live trader
**I want** parabolic cooldowns to survive bot restarts
**So that** I don't re-enter exhaustion immediately after restart/crash

#### Problem Statement

Current cooldown system (Story 3) uses in-memory dict:
- Lost on bot restart
- Lost on crash
- Can lead to immediate re-entry into exhausted symbols

**Example**: Bot detects PEPE parabolic at 14:00, applies 30min cooldown. Bot crashes at 14:05. Restart at 14:10 → cooldown lost → re-enters PEPE immediately.

#### Acceptance Criteria

- [x] Create SQLite table `symbol_cooldowns`:
```sql
CREATE TABLE symbol_cooldowns (
    connector TEXT NOT NULL,
    symbol TEXT NOT NULL,
    reason TEXT NOT NULL,
    expires_at INTEGER NOT NULL,  -- Unix timestamp
    created_at INTEGER NOT NULL,
    PRIMARY KEY (connector, symbol)
);

CREATE INDEX idx_expires_at ON symbol_cooldowns(expires_at);
```

- [x] Implement `CooldownStore` class:
```python
class CooldownStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._create_table()

    def set_cooldown(self, connector: str, symbol: str,
                     reason: str, cooldown_sec: int):
        """Add or update cooldown (upsert)"""

    def get_remaining(self, connector: str, symbol: str) -> Optional[int]:
        """Returns remaining seconds or None if not on cooldown"""

    def cleanup_expired(self):
        """Remove expired cooldowns (run periodically)"""

    def load_active(self) -> Dict[str, float]:
        """Load all active cooldowns on startup"""
```

- [x] Integration with `ParabolicDetector`:
  - On parabolic trigger (live mode): `store.set_cooldown(connector, symbol, reason, cooldown_sec)`
  - On startup: `blacklist = store.load_active()`
  - Every 5 minutes: `store.cleanup_expired()`

- [x] **Shadow mode rule** (critical):
  - In shadow mode: NO database writes
  - Prevents "silent" influence on behavior
  - Log: `[SHADOW] Would persist cooldown for PEPE-EUR (1800s)`

- [x] Unit tests:
  - Set cooldown → restart → verify cooldown persists
  - Expired cooldown → verify auto-removed
  - Shadow mode → verify no DB writes

#### Implementation Notes

**Database Location:**
```python
# multi_coin_grid_pro/persistence/cooldown_store.py
class CooldownStore:
    DEFAULT_DB_PATH = "data/cooldowns.db"
```

**Startup Sequence:**
```python
# In multi_coin_grid_v2.py on_start()
self.cooldown_store = CooldownStore("data/cooldowns.db")
active_cooldowns = self.cooldown_store.load_active()
self.parabolic_blacklist.restore(active_cooldowns)

self.logger.info(f"Loaded {len(active_cooldowns)} active cooldowns from persistence")
```

**Periodic Cleanup:**
```python
# Every 5 minutes (300 seconds)
if self.current_timestamp - self.last_cleanup_ts > 300:
    deleted = self.cooldown_store.cleanup_expired()
    self.logger.debug(f"Cleaned up {deleted} expired cooldowns")
    self.last_cleanup_ts = self.current_timestamp
```

**Example Log Output:**
```
[2026-01-02 14:00:00] INFO Loaded 3 active cooldowns from persistence
[2026-01-02 14:00:00] INFO   - PEPE-EUR: 1200s remaining (expires 14:20:00)
[2026-01-02 14:00:00] INFO   - SUI-EUR: 300s remaining (expires 14:05:00)
[2026-01-02 14:00:00] INFO   - DOGE-EUR: 1800s remaining (expires 14:30:00)
```

**Files to Create:**
- `multi_coin_grid_pro/persistence/__init__.py`
- `multi_coin_grid_pro/persistence/cooldown_store.py`
- `multi_coin_grid_pro/tests/unit/test_cooldown_persistence.py`

---

### Story 11 — Market Exhaustion Warning (Meta-Signal) ✅

**As a** bot operator
**I want** an alert when the market is broadly parabolic/exhausted
**So that** I can reduce risk or pause trading proactively

#### Problem Statement

Current system detects parabolic conditions per symbol. But if MANY symbols are parabolic simultaneously:
- Indicates market-wide exhaustion
- Higher risk of broad correction
- Opportunity to reduce position sizes or pause trading

**Example**: 8 out of 10 top coins are parabolic → market exhaustion likely

#### Acceptance Criteria

- [x] New config section:
```yaml
market_exhaustion_warning:
  enabled: true
  threshold_pct: 0.70  # 70% of sample must be parabolic
  sample_size: 10      # Top N candidates to evaluate
  cooldown_min: 30     # Alert rate limit (minutes)
  actions:
    - log              # Always log
    - telegram         # Optional: send Telegram alert
    # Future: auto_reduce_size, auto_pause
```

- [x] Detection logic during candidate evaluation:
```python
# After evaluating top N candidates
parabolic_count = len([c for c in candidates if c.rejected_by == "PARABOLIC"])
exhaustion_ratio = parabolic_count / len(candidates)

if exhaustion_ratio >= threshold_pct:
    emit_market_exhaustion_warning(ratio, parabolic_count, total_count)
```

- [x] Structured event:
```json
{
  "event_type": "market_exhaustion_warning",
  "timestamp": 1704196800.123,
  "connector": "kraken",
  "regime": "BULL",
  "exhaustion_ratio": 0.80,
  "parabolic_count": 8,
  "total_evaluated": 10,
  "symbols_parabolic": ["PEPE-EUR", "SUI-EUR", "DOGE-EUR", ...],
  "action_taken": "logged"  # Future: "reduced_size", "paused_trading"
}
```

- [x] Rate limiting:
  - Max 1 warning per 30 minutes (default)
  - Prevents spam during extended exhaustion
  - Log: `[EXHAUSTION] Rate limited, last warning 15 minutes ago`

- [x] Telegram alert format:
```
⚠️ MARKET EXHAUSTION WARNING

Connector: Kraken EUR
Regime: BULL
Parabolic: 8/10 coins (80%)

Symbols: PEPE, SUI, DOGE, DOT, ADA, AVAX, SOL, LINK

Consider:
- Reducing position sizes
- Tightening stop losses
- Pausing new entries

Next alert in 30 minutes minimum
```

- [x] Unit tests:
  - 5/10 parabolic → no warning (below threshold)
  - 7/10 parabolic → warning triggered
  - Second warning within 30min → suppressed
  - After 30min cooldown → warning allowed again

#### Implementation Notes

**Integration Point** (multi_coin_grid_controller.py):
```python
# In select_best_coin() after filtering candidates

def _check_market_exhaustion(self, candidates: List[CandidateResult]):
    if not self.config.market_exhaustion_warning.enabled:
        return

    sample_size = self.config.market_exhaustion_warning.sample_size
    sample = candidates[:sample_size]

    # Count parabolic rejections (include shadow mode)
    parabolic = [c for c in sample if "PARABOLIC" in c.reject_reason]
    ratio = len(parabolic) / len(sample)

    threshold = self.config.market_exhaustion_warning.threshold_pct
    if ratio >= threshold:
        # Check rate limit
        if self._can_emit_exhaustion_warning():
            self._emit_exhaustion_warning(ratio, len(parabolic), len(sample), parabolic)
            self.last_exhaustion_warning_ts = time.time()

def _emit_exhaustion_warning(self, ratio, parabolic_count, total, symbols):
    event = {
        "event_type": "market_exhaustion_warning",
        "timestamp": time.time(),
        "connector": self.connector_name,
        "regime": self.current_regime,
        "exhaustion_ratio": ratio,
        "parabolic_count": parabolic_count,
        "total_evaluated": total,
        "symbols_parabolic": [s.symbol for s in symbols],
    }

    # Log
    self.logger.warning(
        f"⚠️  MARKET EXHAUSTION: {parabolic_count}/{total} ({ratio:.0%}) "
        f"coins parabolic: {', '.join([s.symbol for s in symbols[:5]])}"
    )

    # Emit event
    self.event_emitter.emit(event)

    # Optional: Telegram alert
    if "telegram" in self.config.market_exhaustion_warning.actions:
        self._send_telegram_exhaustion_alert(event)
```

**Why This Matters:**
- Early warning system for market tops
- Allows proactive risk reduction
- Complements per-symbol parabolic detection
- Foundation for v3.5 auto-reduction features

**Example Scenarios:**

| Scenario | Parabolic Count | Total | Ratio | Action |
|----------|-----------------|-------|-------|--------|
| Normal bull | 2/10 | 10 | 20% | ✅ No warning |
| Heating up | 5/10 | 10 | 50% | ✅ No warning (below 70%) |
| Exhaustion | 7/10 | 10 | 70% | ⚠️ WARNING + Telegram |
| Extreme | 9/10 | 10 | 90% | ⚠️ WARNING + Telegram |

**Files to Modify:**
- `multi_coin_grid_pro/multi_coin_grid_controller.py` (add exhaustion check)
- `multi_coin_grid_pro/config/config_models.py` (add config model)
- `multi_coin_grid_pro/tests/unit/test_market_exhaustion.py` (new test file)

---

## Guard Execution Order (Critical for Both Exchanges)

**Unified pipeline for Kraken EUR + Bitget USDT:**

```python
# Phase 1: Technical/Exchange Constraints (MUST pass before guard logic)
1. ✅ Spread/slippage check (Bitget critical, also Kraken)
2. ✅ Orderbook depth check
3. ✅ Min notional / contract size constraints (Bitget)
4. ✅ Trading rule validation (min order size, price precision)

# Phase 2: Market Condition Filters (existing SmartEntry)
5. ✅ RSI extreme checks (overbought/oversold)
6. ✅ ATR volatility check
7. ✅ Wick ratio / market structure
8. ✅ VWAP deviation (bidirectional: ±12-20%)

# Phase 3: Momentum Health Guards (NEW - EPIC v3.4)
9. ✅/❌ VWAP Slope Guard (dual confirmation: 5m + 15m)
10. ✅/❌ Parabolic Detector (3-condition + cooldown)
11. ⚠️  Market Exhaustion Warning (meta-signal, non-blocking)

# Phase 4: Final Approval
12. ✅ Entry approved → create grid order
```

**Why This Order Matters:**

1. **Technical checks first**: No point checking momentum if spread is 0.8% (Bitget)
2. **Market filters second**: Prevents obvious bad entries (RSI 85, extreme wick)
3. **Momentum guards last**: Most expensive (candle lookback), only run if other checks pass
4. **Exhaustion warning**: Non-blocking, runs after all candidates evaluated

**Bitget-Specific Prechecks:**
```python
if self.connector_name == "bitget":
    # Bitget has higher spread risk on volatile coins
    if spread_bps > 50:  # 0.50%
        return False, f"Spread too wide for Bitget: {spread_bps}bps"

    # Bitget contract size validation (perp only)
    if self.is_perpetual:
        if notional < min_notional:
            return False, f"Below min notional: {notional} < {min_notional}"
```

**Log Example (Full Pipeline):**
```
[ENTRY] PEPE-EUR evaluation pipeline:
  1. Spread check: ✅ PASS (0.12% < 0.25%)
  2. Depth check: ✅ PASS (€5,200 available)
  3. Min notional: ✅ PASS (€120 > €10)
  4. RSI check: ✅ PASS (54.2, not extreme)
  5. ATR check: ✅ PASS (3.2% < 6.0%)
  6. Wick ratio: ✅ PASS (0.15 < 0.40)
  7. VWAP deviation: ✅ PASS (19.2% < 20.0%)
  8. VWAP slope guard: ❌ REJECT (5m=0.02%, 15m=0.03%, both < thresholds)
  → Entry REJECTED by momentum health guard
```

---

## Configuration Examples

### Kraken EUR (config.prod.yaml)
```yaml
# At top level
vwap_slope_guard:
  enabled: true
  mode: shadow  # Start shadow, then live
  window_min: 15
  deviation_high_pct:
    baseline: 15.0
    BULL: 18.0
    CHOP: 12.0
    BEAR: 10.0
  slope_min_pct_15m:
    baseline: 0.10
    BULL: 0.05  # More lenient in bull
    CHOP: 0.15
    BEAR: 0.20
  log_details: true

parabolic_detector:
  enabled: true
  mode: shadow
  accel_5m_min_pct:
    baseline: 2.5
    BULL: 3.0
    CHOP: 2.2
    BEAR: 2.0
  accel_15m_min_pct:
    baseline: 6.0
    BULL: 7.0
    CHOP: 5.0
    BEAR: 4.0
  vwap_dev_min_pct:
    baseline: 18.0
    BULL: 22.0  # Allow higher deviation in bull
    CHOP: 14.0
    BEAR: 12.0
  cooldown_sec: 1800
  blacklist_scope: session
  log_details: true

# Coin profile overrides (optional)
coin_profiles:
  PEPE-EUR:
    parabolic_detector:
      vwap_dev_min_pct: 25.0  # Meme coin = more extreme
      accel_15m_min_pct: 10.0  # Higher threshold
      cooldown_sec: 3600  # Longer cooldown (1h)

  SUI-EUR:
    vwap_slope_guard:
      slope_min_pct_15m: 0.03  # L1 = volatile, more lenient
```

### Bitget USDT (spot_grid_bitget.yaml)
```yaml
# Same structure as Kraken
vwap_slope_guard:
  enabled: true
  mode: shadow
  # ... same thresholds

parabolic_detector:
  enabled: true
  mode: shadow
  # ... same thresholds

# Bitget-specific: ensure spread check runs first
smart_entry_filter:
  check_order:
    - spread  # Must be first for Bitget
    - notional
    - vwap_slope_guard
    - parabolic_detector
```

---

## Testing Strategy

### Unit Tests
- `test_momentum_indicators.py`: Indicator calculations
- `test_vwap_slope_guard.py`: Guard logic, thresholds, regime resolution
- `test_parabolic_detector.py`: 3-condition trigger, cooldown management
- `test_threshold_resolver.py`: Precedence, safety floors, validation

### Integration Tests
- `test_smart_entry_with_guards.py`: Full SmartEntry flow with guards
- `test_shadow_vs_live_mode.py`: Mode switching behavior
- `test_bitget_specific_checks.py`: Spread check ordering

### Replay Tests
- Historical data: PEPE blow-off (Jan 15, 2025)
- Expected: Parabolic detector triggers at +40%, slope guard at +30%
- Verify: No entry until cooldown expires + slope recovers

### Load Tests
- Scan 50 coins with guards enabled
- Max latency: <100ms per coin
- Memory: No leaks after 1000 scans

---

## Success Criteria

### Functional
- ✅ VWAP slope guard correctly rejects flat momentum during extension
- ✅ Parabolic detector triggers on extreme acceleration + deviation
- ✅ Cooldown prevents repeated attempts during exhaustion
- ✅ Shadow mode logs without blocking
- ✅ Live mode blocks entries correctly

### Performance
- ✅ Guard checks add <50ms latency per coin
- ✅ No memory leaks after 24h operation
- ✅ Event logging scales to 1000 events/hour

### Business Impact
- ✅ Reduce top-buy drawdowns by >50%
- ✅ Maintain >80% of valid bull entries
- ✅ Zero false positives during strong trends (>15% 24h gain)
- ✅ Cooldown reduces repeated attempts by >90%

---

## Rollout Plan

### Week 1: Development + Unit Tests (Core Guards)
- Day 1-2: Story 1 (Indicator Service - including 5m window)
- Day 3-4: Story 2 (VWAP Slope Guard - single window)
- Day 5: Story 3 (Parabolic Detector)

### Week 2: Integration + Exchange Nuances
- Day 1: Story 4 (Bitget Integration)
- Day 2: Story 5 (Threshold Resolver)
- Day 3: Story 6 (Observability)
- Day 4-5: Integration tests

### Week 3: Advanced Features + Replay
- Day 1: Story 9 (Dual-window confirmation)
- Day 2: Story 10 (Cooldown persistence)
- Day 3: Story 11 (Market exhaustion warning)
- Day 4: Story 7 (Replay Harness)
- Day 5: Replay on historical data

### Week 4: Shadow Mode + Analysis
- Day 1-2: Deploy to staging with shadow mode
- Day 3: Analyze shadow logs, tune thresholds
- Day 4-5: Shadow mode on production (both exchanges)
- Day 6-7: Collect data, verify no false positives

### Week 5: Production Rollout
- Day 1: Enable live mode on Kraken (Stories 1-8)
- Day 2: Monitor Kraken for 24h
- Day 3: Enable Stories 9-11 on Kraken
- Day 4: Enable live mode on Bitget (all stories)
- Day 5-7: Full production monitoring

---

## Open Questions & Risks

### Questions
1. **VWAP calculation source**: Use exchange VWAP or compute from OHLCV?
   - Recommendation: Use exchange VWAP if available, fallback to computed
2. **Cooldown persistence**: Store in SQLite or in-memory only?
   - Recommendation: Start in-memory, add persistence in v3.5
3. **Multi-timeframe confirmation**: Require 5m AND 15m slope flat?
   - Recommendation: Add as Story 9 (optional enhancement)
4. **Alert on market exhaustion**: Log warning if >70% coins parabolic?
   - Recommendation: Add in Story 6 (observability)

### Risks
- **False rejections in strong trends**: Tune thresholds in BULL regime to be lenient
- **Insufficient candle history**: Handle gracefully with None + reason
- **Performance impact**: Profile guard checks, optimize if >100ms per coin
- **Config complexity**: Provide sane defaults, validate on load

---

## Future Enhancements (v3.5+)

1. ~~**Persistent cooldown**~~: ✅ **Promoted to Story 10**
2. ~~**Multi-timeframe confirmation**~~: ✅ **Promoted to Story 9**
3. ~~**Market exhaustion alert**~~: ✅ **Promoted to Story 11**
4. **Adaptive thresholds**: Auto-tune based on false positive rate (ML-based)
5. **Slope acceleration**: Detect if VWAP slope itself is decelerating (2nd derivative)
6. **Volume confirmation**: Require decreasing volume during parabolic (volume divergence)
7. **Historical performance tracking**: Track which guard prevented biggest drawdowns
8. **Auto position size reduction**: Reduce size by 50% during market exhaustion
9. **Auto pause trading**: Pause new entries when exhaustion ratio >90%
10. **Cross-exchange correlation**: Detect if both Kraken and Bitget exhausted simultaneously

---

## EPIC v3.4.x — "Crash-Proof Continuity & Self-Healing"
### Full State Persistence + Exchange Reconciliation

**Status**: 📋 PLANNED (Post v3.4)
**Priority**: HIGH - Critical for production resilience
**Depends On**: Story 10 (Cooldown Persistence)
**Target**: Weeks 6-8 (after v3.4 completion)

---

### Executive Summary

**Problem:**
Current Story 10 only persists cooldowns. After bot crash/restart:
- Active grids are lost (can't resume)
- Open orders become "orphans" (duplicate risk)
- Inventory untracked (exposure unknown)
- Timers reset (no_fill/max_hold bypassed)
- Risk tracking lost (daily loss counter)

**Real Scenario:**
Bot opens PEPE grid at 14:00, fills 3 levels. Crash at 14:05. Restart at 14:10:
- ❌ Without recovery: Places NEW grid → doubles exposure
- ✅ With recovery: Resumes existing grid from level 3

**Solution:**
Comprehensive state persistence + exchange reconciliation on startup.

**Success Metrics:**
- Zero duplicate orders after restart (100% safety)
- Resume trading within 30 seconds of restart
- Graceful degradation if reconciliation fails (monitor-only fallback)
- <1% position drift after recovery (vs exchange truth)

---

### Story 10x — Unified Recovery Framework (Foundation)

**As a** production bot operator
**I want** a centralized recovery system that handles all crash scenarios
**So that** the bot can safely continue in any market condition

#### Scope: What Must Be Persisted?

**A) Cooldowns & Blacklists** (Story 10 baseline)
- Parabolic cooldowns (already implemented)
- Session blacklist (temporary exclusions)
- No-trade reason counters (diagnostics)

**B) Active Execution State** (NEW - Critical)
- Per symbol state: `OPENING` / `ACTIVE` / `CLOSING`
- Entry timestamp, last_fill_ts, last_progress_ts
- Grid parameters: range, num_grids, spacing, capital allocated
- Open orders list: clientOrderId ↔ exchangeOrderId mapping
- Inventory snapshot: base/quote exposure per symbol

**C) Risk/Kill-Switch State** (NEW - Safety)
- Daily loss tracker snapshot
- "Halt until" timers (dump pause, maintenance pause)
- Per-symbol circuit breaker state

#### Database Schema (SQLite Extension)

**New Tables:**

```sql
-- Bot-level runtime state
CREATE TABLE runtime_state (
    bot_id TEXT PRIMARY KEY,
    connector TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    last_update INTEGER NOT NULL,
    daily_pnl_snapshot REAL DEFAULT 0.0,
    kill_switch_active BOOLEAN DEFAULT 0,
    halt_until INTEGER,  -- Unix timestamp
    mode TEXT DEFAULT 'live'  -- live|shadow|monitor_only
);

-- Per-symbol grid state
CREATE TABLE symbol_state (
    connector TEXT NOT NULL,
    symbol TEXT NOT NULL,
    grid_id TEXT NOT NULL,
    state TEXT NOT NULL,  -- OPENING|ACTIVE|CLOSING|TERMINATED
    entry_ts INTEGER,
    entry_price REAL,
    last_fill_ts INTEGER,
    last_progress_ts INTEGER,
    base_inventory REAL DEFAULT 0.0,
    quote_inventory REAL DEFAULT 0.0,
    grid_params_json TEXT,  -- Serialized grid config
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (connector, symbol, grid_id)
);

-- Per-order tracking
CREATE TABLE order_state (
    connector TEXT NOT NULL,
    symbol TEXT NOT NULL,
    grid_id TEXT NOT NULL,
    client_order_id TEXT PRIMARY KEY,
    exchange_order_id TEXT,
    side TEXT NOT NULL,  -- buy|sell
    level INTEGER NOT NULL,  -- Grid level (0-indexed)
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    filled_quantity REAL DEFAULT 0.0,
    status TEXT NOT NULL,  -- open|filled|cancelled|failed
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (connector, symbol, grid_id)
        REFERENCES symbol_state(connector, symbol, grid_id)
);

CREATE INDEX idx_order_status ON order_state(connector, symbol, status);
CREATE INDEX idx_symbol_state ON symbol_state(connector, symbol, state);
```

#### Acceptance Criteria

- [x] **Restart Safety:**
  - On startup: Load persisted state from SQLite
  - Fetch exchange truth (balances + open orders + positions)
  - Reconcile DB state vs exchange state
  - Continue without placing duplicate grids/orders

- [x] **Shadow Mode Protection:**
  - Guards in shadow mode do NOT write execution state
  - Only observability events allowed

- [x] **Reconciliation Logic:**
  - If DB says "grid active" but exchange has no orders/inventory:
    - Mark grid as `TERMINATED` (clean exit)
  - If exchange has orders but DB state missing:
    - Reconstruct minimal state: `RECOVERED_ACTIVE`
  - If inventory exists but orders missing:
    - Create recovery plan: re-place grid OR safe unwind

- [x] **Idempotent Order Placement:**
  - Deterministic client order IDs:
    ```
    {bot_id}_{symbol}_{grid_id}_{side}_{level}_{timestamp}
    ```
  - On restart: Detect "already placed" orders, skip duplicates

- [x] **Failsafe Mode:**
  - If reconciliation fails (API down, partial data):
    - Enter `monitor_only` for affected symbols
    - Emit event: `recovery_failed` + Telegram alert
    - Retry with exponential backoff (60s → 300s → 900s)

---

### Story 10a — Startup Recovery Manager (Orchestrator)

**As a** developer
**I want** a centralized RecoveryManager class
**So that** recovery logic is testable and maintainable

#### Acceptance Criteria

- [x] New module: `multi_coin_grid_pro/recovery/recovery_manager.py`

- [x] Core methods:
```python
class RecoveryManager:
    def __init__(self, controller, db_path: str):
        self.controller = controller
        self.state_store = StateStore(db_path)
        self.reconciler = ExchangeReconciler(controller.connector)

    async def run_startup_recovery(self) -> RecoveryResult:
        """
        Full recovery on bot startup:
        1. Load persisted state
        2. Fetch exchange state
        3. Reconcile differences
        4. Resume or failsafe
        """

    async def run_periodic_reconcile(self, interval_sec: int = 300):
        """
        Periodic sanity check (every 5 minutes):
        - Verify open orders still valid
        - Check for unexpected fills
        - Detect orphaned orders
        """

    def emit_recovery_event(self, event_type: str, details: dict):
        """Structured events: recovery_started, completed, failed"""
```

- [x] Events emitted:
  - `recovery_started`: Timestamp, symbols to recover
  - `recovery_completed`: Success rate, symbols resumed, symbols failed
  - `recovery_failed`: Error details, failsafe actions taken

- [x] Unit tests:
  - Mock exchange API responses
  - Test reconciliation logic (8+ scenarios)
  - Verify idempotent behavior (run twice → same result)

---

### Story 10b — Exchange Reconciliation (Kraken + Bitget)

**As a** multi-exchange operator
**I want** reconciliation to work for both Kraken spot and Bitget spot/futures
**So that** recovery is exchange-agnostic

#### Acceptance Criteria

- [x] Kraken Spot:
  - API: `OpenOrders` (fetch open orders)
  - API: `Balance` (fetch balances)
  - Rate limit: 15 req/sec (respect existing 0.8x buffer)

- [x] Bitget Spot:
  - API: `GET /api/spot/v1/trade/open-orders`
  - API: `GET /api/spot/v1/account/assets`
  - Rate limit: 20 req/sec

- [x] Bitget Futures (Phase 2):
  - API: `GET /api/mix/v1/order/current`
  - API: `GET /api/mix/v1/account/accounts` (positions + leverage)
  - Handle perpetual-specific fields: contracts, leverage, funding

- [x] Reconciliation steps:
  1. Fetch all open orders from exchange
  2. Fetch balances (spot) or positions (futures)
  3. Compare with DB state:
     - Match by clientOrderId prefix
     - Detect orphans (orders without DB entry)
     - Detect ghosts (DB entries without exchange orders)
  4. Execute reconciliation policy (see Story 10c)

- [x] Error handling:
  - API timeout → retry with backoff
  - Rate limit hit → pause, respect cooldown
  - Partial data → failsafe to monitor_only

#### Implementation Notes

**Reconciliation Context:**
```python
@dataclass
class ReconciliationContext:
    connector: str
    symbol: str

    # DB state
    db_grid_state: Optional[GridState]
    db_orders: List[OrderRecord]

    # Exchange state
    exchange_orders: List[ExchangeOrder]
    exchange_balance: Balance
    exchange_position: Optional[Position]  # Futures only

    # Reconciliation results
    matched_orders: List[Tuple[OrderRecord, ExchangeOrder]]
    orphan_orders: List[ExchangeOrder]
    ghost_orders: List[OrderRecord]
    inventory_drift: float  # % difference
```

---

### Story 10c — Orphan Order Handling (Critical Safety)

**As a** operator
**I want** orphan orders (without local state) handled safely
**So that** random fills don't cause runaway risk

#### Problem

**Orphan order** = Open order on exchange but no matching DB entry.

**Causes:**
- Crash before DB write completed
- Manual order placed via exchange UI
- DB corruption

**Risk:**
If filled → unexpected inventory without tracking → can trigger:
- Double grid placement
- Stop loss bypass
- PnL tracking error

#### Acceptance Criteria

- [x] Configurable policy per bot:
```yaml
recovery:
  orphan_orders_policy: cancel  # cancel|adopt|monitor_only
```

- [x] **Policy: CANCEL** (safest, default):
  - Cancel all orphan orders immediately
  - Log: symbol, order_id, side, price, qty
  - Emit event: `orphan_order_cancelled`
  - Risk: Lose maker edge, may cancel profitable limit orders

- [x] **Policy: ADOPT** (advanced):
  - Reconstruct grid state from orphan orders
  - Infer entry price from order levels
  - Add to DB as `RECOVERED_ACTIVE`
  - Continue managing as normal grid
  - Risk: Incorrect reconstruction if orders incomplete

- [x] **Policy: MONITOR_ONLY** (debug mode):
  - Do NOT cancel
  - Do NOT trade symbol
  - Log orphan orders every 5 minutes
  - Emit Telegram alert
  - Manual intervention required

- [x] Structured event per orphan:
```json
{
  "event_type": "orphan_order_detected",
  "connector": "kraken",
  "symbol": "PEPE-EUR",
  "order_id": "O12345",
  "client_order_id": "unknown",
  "side": "buy",
  "price": 0.0000123,
  "quantity": 50000,
  "policy": "cancel",
  "action_taken": "cancelled"
}
```

#### Implementation Notes

**Adoption Logic** (for `adopt` policy):
```python
def adopt_orphan_orders(self, symbol: str, orphans: List[ExchangeOrder]) -> GridState:
    """
    Reconstruct grid from orphan orders:
    1. Group by side (buy/sell)
    2. Infer grid range from price levels
    3. Calculate entry price (midpoint assumption)
    4. Rebuild DB state
    """
    buy_orders = [o for o in orphans if o.side == "buy"]
    sell_orders = [o for o in orphans if o.side == "sell"]

    if not buy_orders or not sell_orders:
        raise RecoveryError("Cannot adopt: incomplete grid")

    # Infer entry from midpoint
    min_buy = min(o.price for o in buy_orders)
    max_sell = max(o.price for o in sell_orders)
    entry_price = (min_buy + max_sell) / 2

    # Reconstruct grid
    grid_state = GridState(
        symbol=symbol,
        grid_id=f"RECOVERED_{int(time.time())}",
        state="RECOVERED_ACTIVE",
        entry_price=entry_price,
        # ... infer remaining params
    )

    return grid_state
```

---

### Story 10d — Inventory Recovery: "Have Coins But No Grid"

**As a** operator
**I want** untracked inventory handled safely
**So that** I don't sit on bags or trigger double exposure

#### Scenarios

1. **Crash during grid execution:**
   - Some fills occurred
   - Bot restarted before DB update
   - Exchange shows inventory, DB shows no grid

2. **Manual intervention:**
   - Operator bought coins via exchange UI
   - Bot sees unexpected inventory

3. **Partial liquidation:**
   - Market moved hard, some orders filled
   - Others cancelled/expired

#### Acceptance Criteria

- [x] Detection on startup:
  - Compare exchange inventory vs DB expected inventory
  - Threshold: >5% drift triggers recovery

- [x] **Recovery Option 1: Re-seed Grid**
  - Place grid around current price
  - Use recovered inventory as "entry reference"
  - Calculate new levels from current_price ± grid_range
  - Mark as `RECOVERED_ACTIVE` with entry_price = avg cost

- [x] **Recovery Option 2: Safe Unwind**
  - If inventory + current_price violates stop_loss:
    - Use maker→taker fallback (close_grace concept)
    - Place sell limit at current_bid + 0.1%
    - If not filled in 60s → market sell
  - Emit event: `inventory_unwound`

- [x] Must respect:
  - `stop_loss_pct` (don't re-enter losing position)
  - `hard_stop_pct` (kill switch if exceeded)
  - Daily loss limits

- [x] Structured event:
```json
{
  "event_type": "inventory_recovery",
  "symbol": "PEPE-EUR",
  "exchange_inventory": 50000,
  "db_expected_inventory": 0,
  "drift_pct": 100.0,
  "recovery_action": "re_seed_grid",  // or "safe_unwind"
  "new_grid_id": "RECOVERED_1704196800"
}
```

#### Implementation Notes

**Inventory Drift Calculation:**
```python
def calculate_inventory_drift(self, symbol: str) -> float:
    """
    Returns % difference between exchange and DB inventory.
    """
    exchange_balance = self.connector.get_balance(symbol.split("-")[0])
    db_state = self.state_store.get_symbol_state(symbol)

    if db_state is None:
        # No DB state but have inventory = 100% drift
        return 100.0 if exchange_balance > 0 else 0.0

    db_inventory = db_state.base_inventory
    if db_inventory == 0:
        return 100.0 if exchange_balance > 0 else 0.0

    drift_pct = abs(exchange_balance - db_inventory) / db_inventory * 100
    return drift_pct
```

**Re-seed Grid Logic:**
```python
def reseed_grid_from_inventory(self, symbol: str, inventory: float) -> GridState:
    """
    Create new grid around current price with existing inventory.
    """
    current_price = self.connector.get_mid_price(symbol)

    # Calculate avg cost (assume worst case: bought at current + X%)
    assumed_entry = current_price * 1.05  # 5% slippage buffer

    # Create grid
    grid_params = self._calculate_recovery_grid(
        symbol=symbol,
        current_price=current_price,
        inventory=inventory,
        entry_reference=assumed_entry
    )

    # Persist
    grid_state = GridState(
        symbol=symbol,
        grid_id=f"RECOVERED_{int(time.time())}",
        state="RECOVERED_ACTIVE",
        entry_price=assumed_entry,
        entry_ts=int(time.time()),
        base_inventory=inventory,
        grid_params_json=json.dumps(grid_params)
    )

    self.state_store.save_symbol_state(grid_state)
    return grid_state
```

---

### Story 10e — Persisted Timers (No-Fill / Max-Hold)

**As a** operator
**I want** lifecycle timers to survive crashes
**So that** timeouts continue correctly after restart

#### Problem

Current implementation (from config):
```yaml
lifecycle_management:
  no_fill_timeout_sec: 1800      # 30 minutes
  no_progress_timeout_sec: 3600  # 1 hour
  max_hold_time_sec: 14400       # 4 hours
```

These timers are **in-memory only**:
- Reset on restart
- Can be exploited: restart before timeout → timeout resets

**Example:**
- Grid opened at 14:00, no fills
- Crash at 14:25 (5 minutes before no_fill timeout)
- Restart at 14:30 → timer resets → waits another 30 minutes

#### Acceptance Criteria

- [x] Persist per symbol in `symbol_state` table:
  - `entry_ts`: Grid entry timestamp
  - `last_fill_ts`: Last fill on any level
  - `last_progress_ts`: Last meaningful change (fill or order update)

- [x] On restart:
  - Load timestamps from DB
  - Calculate elapsed time since entry/last_fill
  - Continue timeout where it left off

- [x] Timeout evaluation:
```python
# No-fill timeout
time_since_entry = current_ts - entry_ts
if time_since_entry > no_fill_timeout_sec:
    trigger_no_fill_exit()

# No-progress timeout
time_since_progress = current_ts - last_progress_ts
if time_since_progress > no_progress_timeout_sec:
    trigger_no_progress_exit()

# Max-hold timeout
time_since_entry = current_ts - entry_ts
if time_since_entry > max_hold_time_sec:
    trigger_max_hold_exit()
```

- [x] Update `last_fill_ts` and `last_progress_ts` in DB on every fill

- [x] Structured event:
```json
{
  "event_type": "timeout_triggered",
  "symbol": "PEPE-EUR",
  "timeout_type": "no_fill",
  "entry_ts": 1704196800,
  "last_fill_ts": null,
  "elapsed_sec": 1850,
  "threshold_sec": 1800,
  "action": "force_close_grid"
}
```

#### Implementation Notes

**Timer Persistence:**
```python
def update_progress_timestamp(self, symbol: str, event_type: str):
    """
    Update last_progress_ts on any fill or significant order update.
    """
    current_ts = int(time.time())

    self.state_store.update_symbol_state(
        symbol=symbol,
        last_progress_ts=current_ts
    )

    if event_type == "fill":
        self.state_store.update_symbol_state(
            symbol=symbol,
            last_fill_ts=current_ts
        )
```

**Startup Timer Verification:**
```python
def verify_timeouts_on_startup(self):
    """
    Check all active grids for expired timeouts.
    """
    active_grids = self.state_store.get_active_grids()
    current_ts = int(time.time())

    for grid in active_grids:
        # Check no-fill timeout
        if grid.last_fill_ts is None:
            time_since_entry = current_ts - grid.entry_ts
            if time_since_entry > self.config.no_fill_timeout_sec:
                self.logger.warning(
                    f"{grid.symbol}: No-fill timeout exceeded "
                    f"({time_since_entry}s), closing grid"
                )
                self.close_grid(grid.symbol, reason="no_fill_timeout")

        # Check max-hold timeout
        time_since_entry = current_ts - grid.entry_ts
        if time_since_entry > self.config.max_hold_time_sec:
            self.logger.warning(
                f"{grid.symbol}: Max-hold timeout exceeded "
                f"({time_since_entry}s), closing grid"
            )
            self.close_grid(grid.symbol, reason="max_hold_timeout")
```

---

## Implementation Roadmap (v3.4.x)

### Week 6: Foundation (Stories 10x + 10a)
- Day 1-2: Database schema design + StateStore class
- Day 3-4: RecoveryManager skeleton + basic reconciliation
- Day 5: Unit tests for StateStore + RecoveryManager

### Week 7: Exchange Integration (Stories 10b + 10c)
- Day 1-2: Kraken reconciliation (spot only)
- Day 3-4: Bitget reconciliation (spot + futures)
- Day 5: Orphan order handling (all 3 policies)

### Week 8: Safety Features (Stories 10d + 10e)
- Day 1-2: Inventory recovery (re-seed + unwind)
- Day 3: Timer persistence
- Day 4-5: Integration tests + chaos testing

### Week 9: Production Validation
- Day 1-3: Staged rollout (shadow → limited → full)
- Day 4-5: Crash simulation tests (kill -9, network failures)
- Day 6-7: Documentation + runbook

---

## Testing Strategy (Critical)

### Chaos Tests (New)
```python
def test_crash_during_grid_opening():
    """Simulate crash after grid partially opened"""

def test_crash_during_fill():
    """Simulate crash between fill and DB write"""

def test_exchange_api_timeout_during_recovery():
    """Simulate API down during startup"""

def test_orphan_order_all_policies():
    """Test cancel/adopt/monitor policies"""

def test_inventory_drift_recovery():
    """Test re-seed vs unwind logic"""
```

### Integration Tests
- Full bot restart after 10 minutes of trading
- Verify no duplicate orders
- Verify inventory matches exchange
- Verify timers continue correctly

### Performance Tests
- Recovery must complete in <30 seconds
- Reconciliation overhead: <5% of cycle time

---

## Configuration Example

```yaml
recovery:
  enabled: true

  # Startup behavior
  startup_reconciliation: true
  reconciliation_timeout_sec: 30

  # Orphan order handling
  orphan_orders_policy: cancel  # cancel|adopt|monitor_only

  # Inventory recovery
  inventory_drift_threshold_pct: 5.0
  inventory_recovery_action: re_seed_grid  # re_seed_grid|safe_unwind

  # Failsafe
  failsafe_mode: monitor_only  # If reconciliation fails
  reconciliation_retry_schedule: [60, 300, 900]  # seconds

  # Periodic reconciliation
  periodic_reconciliation_enabled: true
  periodic_reconciliation_interval_sec: 300  # Every 5 minutes

  # Observability
  emit_recovery_events: true
  telegram_alerts_on_recovery: true
```

---

## Success Metrics (v3.4.x)

### Functional
- ✅ Zero duplicate orders after 100 restarts
- ✅ 100% inventory reconciliation accuracy
- ✅ <30 seconds recovery time (median)
- ✅ Graceful degradation on API failures

### Safety
- ✅ No runaway risk scenarios in chaos tests
- ✅ Orphan orders handled in <10 seconds
- ✅ Timers continue correctly (±5 seconds drift)

### Production
- ✅ 1000+ crash recoveries with zero incidents
- ✅ <1% false failsafe triggers
- ✅ Manual intervention required in <5% of cases

---

## References
- Current VWAP filter: `multi_coin_grid_pro/filters/smart_entry_filter.py` lines 235-250
- Regime detection: `multi_coin_grid_pro/logic/regime_detector.py`
- Existing cooldown: `multi_coin_grid_pro/logic/coin_blacklist.py` (NL restriction)
- Market data: `data/market_data.db` (candle history)
- Story 10: `multi_coin_grid_pro/persistence/cooldown_store.py` (cooldown persistence baseline)

---

**Document Version**: 1.1
**Last Updated**: 2026-01-03
**Owner**: Mo
**Status**: v3.4 (Stories 1-11) ✅ LIVE | v3.4.x (Crash Recovery) 📋 PLANNED
