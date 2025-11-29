# Phase 2.5: Multi-Timeframe Trend Engine & Smart Switching Logic

**Status:** ⚠️ PLANNED
**Priority:** 🟡 MEDIUM-HIGH
**Estimated Time:** 20-24 uur
**Dependencies:** Phase 2 (Trend Detection) completed

---

## 🎯 Objective

Replace the single lookback trend calculation with a full multi-timeframe trend engine and add smart buy/sell/switch rules based on professional trend-following logic.

**Problem Statement:**
- Current bot uses single 24h lookback (1440 minutes)
- **CRITICAL ISSUE:** 24h trend can hide recent crashes!
  - Example: Coin has +5.8% over 24h, but crashed -3% in last 3 hours
  - Bot sees +5.8% → buys → buys at peak, misses the crash
- Bot switches too quickly on temporary dips
- No distinction between short-term noise and long-term trends
- Missing professional trend-following logic

**Real-World Example:**
```
SPX-EUR Price History:
- 24h ago: €100
- 3h ago:  €105.8 (+5.8% peak)
- 1h ago:  €102.6 (-3% crash)
- Now:     €101.5 (-1.5% still falling)

Current System (24h only):
- trend_24h = +5.8% → "GOOD COIN!" → BUY ❌ (buys at peak!)

Multi-Timeframe System:
- trend_1440m = +5.8% (good macro trend)
- trend_240m  = -1.2% (crashing!)
- trend_60m   = -1.5% (still falling!)
- → EXIT CONDITIONS MET → SELL ✅ (avoids loss!)
```

**Solution:**
- Implement 3 timeframes: 60m, 240m, 1440m
- Composite trend score for ranking
- Smart buy/exit/switch conditions
- Anti-churn logic to prevent premature exits

---

## 🧩 Requirements

### 1. Calculate 3 Trend Timeframes

Implement trend calculation for:
- `trend_60m` - 1 hour lookback (short-term)
- `trend_240m` - 4 hour lookback (mid-term)
- `trend_1440m` - 24 hour lookback (long-term)

**Storage:**
- Store these per coin in `CoinTrend` dataclass
- Update every tick/candle
- Use efficient circular buffer for performance

**Implementation:**
```python
@dataclass
class CoinTrend:
    symbol: str
    current_price: Decimal
    trend_60m: float = 0.0
    trend_240m: float = 0.0
    trend_1440m: float = 0.0
    trend_score: float = 0.0  # Composite score
    long_trend_warmup: bool = False
    # ... existing fields
```

### 2. Compute Composite Trend Score

```python
trend_score = (
    0.2 * trend_60m +
    0.4 * trend_240m +
    0.4 * trend_1440m
)
```

**Rationale:**
- Long-term trends (40%) most important
- Mid-term trends (40%) confirm direction
- Short-term trends (20%) for timing

### 3. Buy Conditions

A coin is allowed to be selected as active coin **ONLY if**:

```
trend_1440m > +1%   (24h trend must be positive)
trend_240m  > +1%   (4h trend must be positive)
trend_60m   >= 0%   (1h trend not negative)
```

**Purpose:** Only enter positions when all timeframes align positively.

### 4. Exit Conditions (Trend Break)

Exit the active coin if:

```
trend_60m < -1%     (short-term trend breaks)
AND
trend_240m < +0.5%  (mid-term trend weakens)
```

**Purpose:** Exit quickly when trend breaks, but avoid false exits.

### 5. Anti-Churn (No Early Switches)

If active coin has strong macro-trend:

```
trend_1440m > +2%   (strong long-term trend)
AND
trend_240m > +0.5%  (mid-term still positive)
AND
-1% <= trend_60m < 0%  (temporary dip, not breakdown)
```

→ **Do NOT switch**
→ Active coin must be retained.

**Purpose:** Prevent switching away from strong trends due to temporary dips.

### 6. Switching Logic

Switch only if another coin has significantly better trend score:

```
trend_score(new_coin) - trend_score(active_coin) >= 1.5%
```

**Purpose:** Only switch when opportunity is clearly better (covers switch costs).

### 7. Warm-Up Mode

For first 24h after bot startup:

- Mark `trend_1440m` as `warming_up=True`
- Temporary fallback: `trend_1440m = trend_240m * 2`
- Until enough data is collected (1440 minutes of history)
- All decisions must log warm-up reasoning

**Purpose:** Allow bot to start trading immediately without waiting 24h for data.

### 8. Config Additions

Add in `multi_coin_grid_config.py`:

```python
trend_lookback_short_minutes: int = 60
trend_lookback_mid_minutes: int = 240
trend_lookback_long_minutes: int = 1440
switch_threshold_percent: float = 1.5
exit_short_threshold: float = -1.0
exit_mid_threshold: float = 0.5
```

### 9. Logging Requirements

Every decision must log:

**Format:**
```
[TREND] coin=SPX 60m=-0.3% 240m=+2.1% 1440m=+4.8% score=3.09 warmup=False
[DECISION] keep | exit | buy | switch → reason="Strong macro-trend, temporary dip"
[SWITCH] from=GIGA score=0.8% to=ICP score=3.2% difference=+2.4% threshold=1.5% → APPROVED
```

**Required Fields:**
- All 3 trends (60m, 240m, 1440m)
- Composite trend_score
- Warmup state
- Reason for buy/exit/switch
- Alternative coin considered
- Difference-score for any switch decision

### 10. Testing Requirements

Write tests for:

- ✅ Trend calculations (3 timeframes)
- ✅ Composite score calculation
- ✅ Valid buy scenario (all conditions met)
- ✅ Invalid buy scenario (conditions not met)
- ✅ Valid exit scenario (trend break)
- ✅ Invalid exit scenario (no trend break)
- ✅ Anti-churn behavior (strong trend, temporary dip)
- ✅ Switch threshold correctness (1.5% difference)
- ✅ Warm-up mode trend replacement
- ✅ Edge cases (insufficient data, negative trends, etc.)

---

## 📦 Expected Deliverables

1. **TrendEngine class** (`multi_coin_grid_pro/utils/trend_engine.py`)
   - Multi-timeframe trend calculation
   - Composite score calculation
   - Warm-up mode handling

2. **DecisionEngine upgrade** (`multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`)
   - Buy condition checks
   - Exit condition checks
   - Anti-churn logic
   - Switch logic integration

3. **Config updates** (`multi_coin_grid_pro/controllers/multi_coin_grid_config.py`)
   - New config parameters
   - Validation

4. **Unit tests** (`multi_coin_grid_pro/tests/unit/test_multi_timeframe_trend.py`)
   - All scenarios covered

5. **Log messages** (integrated in controller)
   - Structured logging format
   - Decision reasoning

6. **Mock examples** (in test file)
   - Example decisions
   - Example log outputs

---

## 🔄 FLOWCHART — Multi-Timeframe Trend Engine & Smart Switching Logic

```
                             ┌───────────────────────────┐
                             │ Start Tick / New Candle   │
                             └───────────────┬───────────┘
                                             │
                                             ▼
                         ┌──────────────────────────────────────┐
                         │ Recalculate Trends for Each Coin     │
                         │  - trend_60m                         │
                         │  - trend_240m (4h)                   │
                         │  - trend_1440m (24h or fallback)     │
                         └───────────────────┬──────────────────┘
                                             │
                                             ▼
                       ┌──────────────────────────────────────┐
                       │ Is 24h Trend in Warm-Up Mode?        │
                       └───────────────┬──────────────────────┘
                                       │ YES
                                       ▼
                   ┌─────────────────────────────────────────────┐
                   │ Replace 1440m Trend with 240m * 2 Fallback   │
                   │ Mark: long_trend_warmup = True               │
                   └────────────────────────┬────────────────────┘
                                            │
                                            ▼
                         (If NO warmup → use real 24h trend)

                                        ▼

                    ┌──────────────────────────────────────┐
                    │ Compute Composite Trend Score        │
                    │ trend_score =                       │
                    │   0.2*60m + 0.4*240m + 0.4*1440m     │
                    └───────────────────┬──────────────────┘
                                        │
                                        ▼
                  ┌────────────────────────────────────────┐
                  │ Determine the Best Coin (highest score)│
                  └───────────────────┬────────────────────┘
                                      │
                                      ▼
     ┌──────────────────────────────────────────────────────────────────┐
     │ Is There an Active Coin?                                        │
     └───────────────┬─────────────────────────────────────────────────┘
                     │ NO
                     ▼
       ┌───────────────────────────────────────────────────────────┐
       │ BUY best coin IF:                                         │
       │  - 1440m > +1%                                             │
       │  - 240m > +1%                                              │
       │  - 60m >= 0%                                               │
       └───────────────────────────────────────────────────────────┘
                     │
                     └──────────────→ END TICK

Flow When There Is an Active Coin

                         ▼

         ┌──────────────────────────────────────────────┐
         │ Check Exit Conditions (trend break)          │
         │  - 60m < -1%                                 │
         │  - AND 240m < +0.5%                          │
         └───────────────────────────┬──────────────────┘
                                     │
                         YES         │          NO
                         ▼                        ▼
      ┌────────────────────────────────┐    ┌──────────────────────────────┐
      │ EXIT POSITION                  │    │ Check Anti-Churn Rules       │
      │ (Sell coin)                    │    └───────────────┬──────────────┘
      │                                │                    │
      └─────────────────┬──────────────┘         YES        │      NO
                        │                                ▼   │
                        └──────────→ END TICK    ┌────────────────────────┐
                                                │ KEEP POSITION           │
                                                │ Do not switch           │
                                                └────────────────────────┘

                                                                   ▼

Switch Logic (Only if No Exit + No Anti-Churn)

                     ▼
      ┌────────────────────────────────────────────────────────┐
      │ Compare trend_score(best_coin) vs trend_score(active)  │
      └───────────────┬────────────────────────────────────────┘
                      │
               Difference >= 1.5% ?

                      │
        YES           │          NO
        ▼                         ▼
┌───────────────────┐   ┌───────────────────────────┐
│ SWITCH to best    │   │ KEEP current coin         │
│ (sell + buy new)  │   └───────────────────────────┘
└───────────────────┘

        │
        ▼
     END TICK
```

---

## 🎓 Implementation Notes

### Performance Considerations

1. **Data Storage:**
   - Use circular buffers for price history (efficient memory)
   - Store only necessary data points
   - Clean old data automatically

2. **Calculation Efficiency:**
   - Cache trend calculations
   - Only recalculate when new price arrives
   - Batch updates for multiple coins

3. **Warm-Up Mode:**
   - Track bot startup time
   - Check if 24h has passed
   - Auto-disable warm-up after sufficient data

### Integration Points

1. **TrendCalculator Integration:**
   - Extend existing `TrendCalculator` class
   - Add multi-timeframe methods
   - Keep backward compatibility

2. **Controller Integration:**
   - Modify `determine_executor_actions()` method
   - Add buy/exit/switch checks
   - Integrate with existing switch logic (Phase 3)

3. **Config Integration:**
   - Add new fields to `MultiCoinGridConfig`
   - Validate on startup
   - Provide sensible defaults

### Edge Cases

1. **Insufficient Data:**
   - Handle warm-up mode gracefully
   - Fallback to shorter timeframes if needed
   - Log warnings when data is incomplete

2. **Negative Trends:**
   - Handle all-negative scenarios
   - Prevent buying when all trends negative
   - Exit quickly when trends turn negative

3. **Rapid Market Changes:**
   - Handle flash crashes
   - Prevent false exits during volatility
   - Use circuit breaker (Phase 1.2) as backup

---

## 📊 Success Metrics

After implementation, measure:

1. **Reduced Switch Frequency:**
   - Target: <50% reduction in switches
   - Measure: Switches per day before/after

2. **Improved Entry Quality:**
   - Target: >70% of entries profitable
   - Measure: Win rate of positions entered

3. **Reduced False Exits:**
   - Target: <20% false exits (exit then immediate recovery)
   - Measure: Exit → recovery within 1h

4. **Better Trend Following:**
   - Target: Capture >60% of major trends
   - Measure: Trend capture ratio

---

## ⚠️ Risks & Mitigations

1. **Risk: Over-Complexity**
   - **Mitigation:** Start simple, add complexity gradually
   - **Mitigation:** Extensive testing before production

2. **Risk: Performance Impact**
   - **Mitigation:** Use efficient data structures
   - **Mitigation:** Cache calculations
   - **Mitigation:** Profile and optimize

3. **Risk: False Signals**
   - **Mitigation:** Combine with existing indicators
   - **Mitigation:** Use warm-up mode for startup
   - **Mitigation:** Extensive backtesting

---

## 📝 References

- Professional trend-following strategies
- Multi-timeframe analysis best practices
- Anti-churn logic in algorithmic trading
- Warm-up modes in trading systems

---

**Last Updated:** 2025-11-20
**Status:** ⚠️ PLANNED - Awaiting implementation
