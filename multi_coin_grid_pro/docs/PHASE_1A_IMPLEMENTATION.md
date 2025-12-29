# Phase 1A: Observability Foundation - Implementation Complete ✅

## Summary

Implemented **Phase 1A foundation** for structured observability with:
- Central ReasonCode taxonomy (30 rejection codes)
- JSONL event logger with correlation tracking
- Additive changes to PairDecisionTrace
- Config schema for feature flags
- Comprehensive unit + integration tests

**All changes additive - no breaking signatures, safe default (disabled)**

---

## Commit Structure

### Commit 1: Foundation
```bash
git add multi_coin_grid_pro/core/reason_codes.py
git add multi_coin_grid_pro/observability/__init__.py
git add multi_coin_grid_pro/observability/event_logger.py
git add multi_coin_grid_pro/utils/decision_trace.py
git add multi_coin_grid_pro/config/config.prod.yaml
git add multi_coin_grid_pro/config/config.test.yaml
git add multi_coin_grid_pro/config/config.usd.yaml
git add multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
git commit -m "feat(observability): Phase 1A foundation - ReasonCode + EventLogger + config

- Add ReasonCode enum (30 rejection codes, grouped by stage)
- Add Stage enum (SMART_ENTRY/MTF/RISK/EXECUTION/REGIME)
- Add EventLogger (JSONL writer with buffered writes)
- Extend PairDecisionTrace with correlation_id, stage, reason_code
- Add observability config schema to all bot configs (structured_events_enabled: false by default)
- Add compute_config_hash() utility for run tracking

Config updates:
- config.prod.yaml (Kraken EUR)
- config.test.yaml (Test environment)
- config.usd.yaml (Kraken USD)
- spot_bitget/config/spot_grid_bitget.yaml (Bitget)

No behavior changes - all behind feature flag (default: off)"
```

### Commit 2: Tests
```bash
git add test/multi_coin_grid_pro/test_reason_codes.py
git add test/multi_coin_grid_pro/test_event_logger_integration.py
git add SMART_GRID_PROP_DESK_V1_BACKLOG.md
git commit -m "feat(observability): Phase 1A tests + backlog update

Unit tests:
- ReasonCode enum completeness (30 codes, no duplicates)
- Stage mapping correctness
- JSON serialization

Integration tests:
- 5 decision scenarios with correlation_id tracking
- JSONL output validation
- Buffer auto-flush behavior

Backlog:
- Mark Phase 1A complete
- Phase 1B pending (instrumentation)

All tests passing (15/15)"
```

---

## Files Created

```
multi_coin_grid_pro/core/reason_codes.py                    (160 lines)
multi_coin_grid_pro/observability/__init__.py               (4 lines)
multi_coin_grid_pro/observability/event_logger.py           (280 lines)
test/multi_coin_grid_pro/test_reason_codes.py               (200 lines)
test/multi_coin_grid_pro/test_event_logger_integration.py   (320 lines)
```

## Files Modified

```
multi_coin_grid_pro/utils/decision_trace.py                 (+3 fields)
multi_coin_grid_pro/config/config.prod.yaml                 (+observability section)
multi_coin_grid_pro/config/config.test.yaml                 (+observability section)
multi_coin_grid_pro/config/config.usd.yaml                  (+observability section)
multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml (+observability section)
SMART_GRID_PROP_DESK_V1_BACKLOG.md                          (status update)
```

---

## ReasonCode Taxonomy (30 Codes)

### SMART_ENTRY (14 codes)
- RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_EXTREME_BLOCK
- VWAP_DEVIATION_TOO_HIGH
- WICK_RATIO_LOW
- ATR_TOO_LOW, ATR_TOO_HIGH
- SPIKE_5M_EXCESSIVE
- ACCEL_FALLING_KNIFE, ACCEL_BLOWOFF
- TREND_24H_OUT_OF_RANGE
- SPREAD_TOO_WIDE
- DEPTH_INSUFFICIENT, ORDERBOOK_UNAVAILABLE

### MTF (2 codes)
- MTF_INSUFFICIENT
- MTF_CRASH_DETECTED

### RISK (6 codes)
- EXPOSURE_LIMIT
- DAILY_LOSS_LIMIT
- COOLDOWN_EXIT, COOLDOWN_SWITCH, COOLDOWN_LOSS_STREAK
- POSITION_LIMIT

### EXECUTION (6 codes)
- BLACKLIST, SLOT_FULL, ALREADY_TRADING
- STARTUP_DELAY, NOT_TRADEABLE, ORDERBOOK_ERROR

### REGIME (2 codes)
- REGIME_BTC_DUMP, REGIME_DUMP_COOLDOWN

**Note:** No APPROVED code - success is `trace.accepted=True` or `gate_passed` event

---

## Correlation ID Propagation Strategy

### Pattern 1: SmartEntry (via trace + optional param)
```python
# Controller generates correlation_id
correlation_id = str(uuid.uuid4())[:8]

# Pass to SmartEntry (new optional param - backward compatible)
allowed, reason, trace = smart_entry.allows_entry(
    symbol, indicators, exchange,
    trace_enabled=True,
    correlation_id=correlation_id  # NEW OPTIONAL
)

# SmartEntry sets (internally):
trace.correlation_id = correlation_id
trace.stage = Stage.SMART_ENTRY
trace.reason_code = ReasonCode.RSI_OVERBOUGHT  # On rejection
```

### Pattern 2: MTF/Risk (via function param OR kwargs)

**Option A: Add optional param (safest, explicit)**
```python
# In controller
allowed = self._check_multi_timeframe_buy(symbol, correlation_id=correlation_id)

# In MTF function signature (backward compatible)
def _check_multi_timeframe_buy(self, symbol: str, correlation_id: Optional[str] = None) -> bool:
    # Use correlation_id if provided
    if self.event_logger and correlation_id:
        self.event_logger.emit_gate_denied(
            correlation_id=correlation_id,
            ...
        )
```

**Option B: Via context dict (if many functions need it)**
```python
# In controller, create context dict
eval_ctx = {"correlation_id": correlation_id}

# Pass to functions that need it
allowed = self._check_multi_timeframe_buy(symbol, context=eval_ctx)

# In MTF function
def _check_multi_timeframe_buy(self, symbol: str, context: Optional[Dict] = None) -> bool:
    correlation_id = context.get("correlation_id") if context else None
```

**🚫 AVOID: Temporary instance variables (global state risk)**
```python
# DON'T DO THIS - race conditions in parallel loops
self._eval_correlation_id = correlation_id  # BAD
```

**Chosen Strategy for Phase 1B:**
- **SmartEntry**: Optional `correlation_id` param (explicit)
- **MTF/Risk**: Optional `correlation_id` param (explicit)
- **Controller**: Generate once per candidate, pass explicitly

**No global state, no race conditions** ✅

---

## Config Schema

```yaml
# config.prod.yaml
observability:
  structured_events_enabled: false  # Safe default: OFF
  events_output_dir: "logs/events"
  buffer_size: 100
  why_no_trade_report_enabled: false  # Phase 1B
  report_interval_seconds: 3600
```

---

## Test Results

```bash
$ pytest test/multi_coin_grid_pro/test_reason_codes.py -v
========================= 12 passed, 1 warning in 0.04s =========================

$ pytest test/multi_coin_grid_pro/test_event_logger_integration.py -v
========================= 3 passed, 1 warning in 0.03s =========================
```

**All 15 tests passing** ✅

---

## Usage Example

### Enable Structured Events
```yaml
# config.prod.yaml
observability:
  structured_events_enabled: true  # Enable
```

### Run Bot
```bash
./start.sh
```

### Verify JSONL Output
```bash
cat logs/events/events_20251226_*.jsonl | head -5
```

Expected output:
```json
{"ts": 1735234567.89, "event_type": "config_loaded", "config_hash": "abc123def456", ...}
{"ts": 1735234568.12, "event_type": "gate_denied", "correlation_id": "a1b2c3", "symbol": "BTC-EUR", "stage": "SMART_ENTRY", "reason_code": "RSI_OVERBOUGHT", ...}
{"ts": 1735234568.45, "event_type": "gate_passed", "correlation_id": "d4e5f6", "symbol": "ETH-EUR", "stage": "SMART_ENTRY", ...}
```

### Parse Events
```bash
cat logs/events/*.jsonl | jq -s 'group_by(.event_type) | map({type: .[0].event_type, count: length})'
```

---

## Next Steps (Phase 1B - Commit 3)

### Instrumentation Points
1. **SmartEntry** (`logic/smart_entry.py`)
   - Set `trace.stage = Stage.SMART_ENTRY`
   - Set `trace.reason_code` on each rejection
   - Accept `correlation_id` param

2. **MTF Check** (`controllers/multi_coin_grid_controller.py`)
   - Emit `gate_denied` / `gate_passed` events
   - Use `self._eval_correlation_id` context

3. **Risk Manager** (`core/global_risk_manager.py`)
   - Emit `gate_denied` for limit breaches
   - Track correlation_id via logger context

4. **Controller**
   - Initialize EventLogger
   - Generate correlation_id per candidate
   - Propagate via params + context

### Validation
```bash
# Run bot for 1 hour with events enabled
# Verify JSONL contains:
# - All events have correlation_id
# - All rejections have stage + reason_code
# - Config hash present
```

---

## Architecture Diagram

```
Controller
    │
    ├─ correlation_id = uuid()
    │
    ├─ SmartEntry.allows_entry(correlation_id=...)
    │      │
    │      ├─ trace.stage = SMART_ENTRY
    │      ├─ trace.reason_code = RSI_OVERBOUGHT
    │      └─ return allowed, reason, trace
    │
    ├─ _check_multi_timeframe_buy(symbol)
    │      │
    │      ├─ correlation_id = self._eval_correlation_id
    │      └─ event_logger.emit_gate_denied(...)
    │
    └─ risk_manager.can_open_trade(...)
           │
           ├─ correlation_id = self._eval_correlation_id
           └─ event_logger.emit_gate_denied(...)
```

---

## Risk Assessment

| Risk | Mitigation | Status |
|------|------------|--------|
| Breaking changes | Additive only, optional params | ✅ Safe |
| Performance impact | Feature flag (default: off), buffered writes | ✅ Safe |
| Disk usage | JSONL rotation (future), small buffer | ⚠️ Monitor |
| Missing correlation_id | Fallback to "unknown", non-critical | ✅ Safe |

---

## References

- [SMART_GRID_PROP_DESK_V1_BACKLOG.md](../SMART_GRID_PROP_DESK_V1_BACKLOG.md) - Epic E: Observability
- [reason_codes.py](multi_coin_grid_pro/core/reason_codes.py) - Central taxonomy
- [event_logger.py](multi_coin_grid_pro/observability/event_logger.py) - JSONL writer
- [decision_trace.py](multi_coin_grid_pro/utils/decision_trace.py) - Trace extensions

---

**Status:** ✅ Ready for Phase 1B (instrumentation)
**Tests:** ✅ 15/15 passing
**Breaking Changes:** ❌ None
**Feature Flag:** ✅ Safe default (off)
