# Phase 2 + Shadow Mode Implementation ✅

**Datum:** 24 december 2025
**Status:** Complete - Ready for testing

## 🎯 Implementation Summary

Implemented **Phase 2 (Early Filtering)** en **Shadow Mode** voor liquidity-aware coin selection volgens architectuur spec.

---

## 🚀 Features Implemented

### 1. **Shadow Mode** (Testing & Validation)
- **Mode:** `shadow`
- **Behavior:** Logs depth checks maar filtert NIET
- **Use case:** Veilig testen van nieuwe thresholds zonder trading impact
- **Logging:** Toont welke coins zouden passen/falen met huidige config

```yaml
orderbook_liquidity:
  enabled: true
  mode: shadow  # Log-only, no filtering
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
```

**Outputvoorbeeld:**
```
👻 Shadow Mode: Testing depth filtering (would require €400.00) - NO actual filtering
✅ Shadow: BTC-EUR would PASS (bid: €850.25 >= €400.00)
❌ Shadow: SHIB-EUR would FAIL (bid: €120.50 < €400.00) - but NOT filtering
👻 Shadow Mode: 8/14 would pass depth check
```

---

### 2. **Phase 1: Ranking Mode** (Current Default)
- **Mode:** `ranking`
- **Behavior:** Filtert in `get_best_coin()` / `get_top_n_coins()` TIJDENS coin selection
- **Use case:** Huidige productie behavior (Phase 1 implementation)
- **Performance:** Extra API calls tijdens coin ranking

```yaml
orderbook_liquidity:
  enabled: true
  mode: ranking  # Default - filter during selection (Phase 1)
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
```

---

### 3. **Phase 2: Early Mode** (Performance Optimization) ⚡
- **Mode:** `early`
- **Behavior:** Filtert in `update_all_trends_v2()` VOOR trend berekening
- **Use case:** Production optimization - skip expensive trend calculation voor illiquide coins
- **Performance:** Veel sneller - filtert VOOR trend updates + API calls

```yaml
orderbook_liquidity:
  enabled: true
  mode: early  # Phase 2 - filter BEFORE trend calculation (fastest)
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
```

**Workflow:**
```
1. Controller roept update_all_trends_v2(coins, orderbook_config)
2. TrendCalculator checkt orderbook depth voor ALLE coins
3. Filtert illiquide coins UIT voordat trend berekening start
4. Alleen liquide coins krijgen trend updates
5. get_best_coin() skipt depth check (al gedaan in stap 2)
```

**Performance voordeel:**
- ❌ **Ranking mode:** 14 trend updates + 14 depth checks tijdens selection
- ✅ **Early mode:** 8 trend updates (6 gefilterd) + 14 depth checks upfront = 42% minder werk

---

## 📊 Mode Comparison

| Mode | Filtering Location | API Calls | Best For |
|------|-------------------|-----------|----------|
| **shadow** | Nowhere (log only) | Max (all coins) | Testing new thresholds |
| **ranking** | During coin selection | Medium (trends + on-demand depth) | Current production (Phase 1) |
| **early** | Before trend calculation | Minimal (only liquid coins) | Optimal performance (Phase 2) |

---

## 🔧 Implementation Details

### Files Modified

1. **trend_calculator.py** (3 functions)
   - `update_all_trends_v2()`: Added orderbook_config parameter + Phase 2 early filtering
   - `get_best_coin()`: Added shadow mode + mode detection
   - `get_top_n_coins()`: Added shadow mode + mode detection

2. **multi_coin_grid_controller.py**
   - `_build_orderbook_config()`: Added mode parameter passthrough
   - `_update_all_trends()`: Pass orderbook_config to update_all_trends_v2 (3 locations)

3. **multi_coin_grid_config.py**
   - Updated `orderbook_liquidity` description with mode options

### Code Changes Summary

**Phase 2 Early Filtering Logic:**
```python
# In update_all_trends_v2()
if mode == 'early':
    # Check depth for ALL coins upfront
    for symbol in all_coins:
        orderbook = await get_orderbook_snapshot(...)
        bid_depth, ask_depth = calculate_orderbook_depth(...)

        if is_sufficient_depth(...):
            filtered.append(symbol)  # PASS - will update trends
        else:
            # SKIP - no trend calculation for this coin
            logger.debug(f"❌ {symbol}: Insufficient depth - SKIPPED")

    # Only update trends for LIQUID coins
    converted_symbols = filtered
```

**Shadow Mode Logic:**
```python
# In get_best_coin() / get_top_n_coins()
if shadow_mode:
    # Check depth but DON'T filter
    if depth_sufficient:
        logger.info(f"✅ Shadow: {symbol} would PASS")
    else:
        logger.info(f"❌ Shadow: {symbol} would FAIL - but NOT filtering")
    # Continue evaluation (allow all coins through)
```

---

## 📝 Configuration Examples

### Example 1: Test Shadow Mode (Safe Testing)
```yaml
# Test new thresholds without trading impact
orderbook_liquidity:
  enabled: true
  mode: shadow
  depth_pct_range: 0.5  # ±0.5% from mid price
  depth_levels: 10       # Top 10 orderbook levels
  min_depth_multiplier: 8.0  # Testing higher threshold (8x instead of 5x)
```

### Example 2: Production - Ranking Mode (Current)
```yaml
# Current behavior (Phase 1)
orderbook_liquidity:
  enabled: true
  mode: ranking
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
```

### Example 3: Production - Early Mode (Optimized)
```yaml
# Optimal performance (Phase 2)
orderbook_liquidity:
  enabled: true
  mode: early  # Filter BEFORE expensive trend calculation
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
```

### Example 4: Disabled (No Liquidity Filtering)
```yaml
# Backward compatible - no filtering
orderbook_liquidity:
  enabled: false
```

---

## 🧪 Testing Plan

### Phase 1: Shadow Mode Testing
1. Enable shadow mode op Kraken bot
2. Monitor logs voor 1 uur
3. Analyze: hoeveel coins zouden gefilterd worden?
4. Tune `min_depth_multiplier` based on results

### Phase 2: Early Mode Testing
1. Switch naar early mode
2. Monitor performance: trend update tijd
3. Verify: geen false positives (goede coins gefilterd)
4. Compare met ranking mode baseline

### Phase 3: Production Rollout
1. Deploy early mode op beide bots
2. Monitor first 24h closely
3. Validate: depth filtering werkt correct
4. Measure: performance improvement

---

## 📈 Expected Performance Improvements

**Scenario:** 14 monitored coins, 6 illiquid (43%)

### Current (Ranking Mode):
- 14 trend calculations ≈ 2.1s (14 × 0.15s)
- 14 depth checks tijdens selection ≈ 0.7s (14 × 0.05s)
- **Total:** ≈ 2.8s per update cycle

### With Early Mode (Phase 2):
- 14 upfront depth checks ≈ 0.7s (14 × 0.05s)
- 8 trend calculations ≈ 1.2s (8 × 0.15s) [6 gefilterd]
- **Total:** ≈ 1.9s per update cycle

**Performance gain:** 32% faster (2.8s → 1.9s)

---

## 🎛️ Migration Path

### Step 1: Enable Shadow Mode (Safe)
```bash
# Edit config via Hummingbot
config orderbook_liquidity '{"enabled": true, "mode": "shadow", "depth_pct_range": 0.5, "depth_levels": 10, "min_depth_multiplier": 5.0}'
```

### Step 2: Analyze Shadow Logs
```bash
# Check how many coins would be filtered
grep "Shadow:" logs/*.log | grep "would FAIL" | wc -l
grep "Shadow:" logs/*.log | grep "would PASS" | wc -l
```

### Step 3: Switch to Early Mode (Production)
```bash
# Only after validating thresholds in shadow mode
config orderbook_liquidity '{"enabled": true, "mode": "early", "depth_pct_range": 0.5, "depth_levels": 10, "min_depth_multiplier": 5.0}'
```

---

## 🔍 Monitoring & Debugging

### Key Log Lines to Watch

**Shadow Mode:**
```
👻 Shadow Mode: Testing depth filtering (would require €X.XX)
✅ Shadow: COIN would PASS (bid: €X >= €Y)
❌ Shadow: COIN would FAIL (bid: €X < €Y) - but NOT filtering
👻 Shadow Mode: N/M would pass depth check
```

**Early Mode:**
```
🔍 Phase 2 Early Filtering: Checking 14 coins for depth >= €400.00
❌ COIN: Insufficient depth (bid: €X, ask: €Y < required: €Z) - SKIPPED
✅ Phase 2 Early Filtering: 8 passed, 6 filtered (8/14 will update trends)
```

**Ranking Mode:**
```
🔍 Depth filtering: 6 coins filtered out (8 liquid coins remain)
✅ COIN: Sufficient depth (available=€X, required=€Y)
🚫 COIN: Insufficient depth (available=€X, required=€Y) - SKIPPED
```

---

## 🚨 Known Limitations

1. **Early mode requires orderbook API calls for ALL coins upfront**
   - Pro: Filters BEFORE expensive trend calculation
   - Con: Initial depth check latency (0.7s for 14 coins)
   - Mitigation: Still faster overall due to fewer trend calculations

2. **Shadow mode generates verbose logs**
   - Pro: Excellent for testing/validation
   - Con: Log spam in production
   - Mitigation: Only use shadow for testing, not production

3. **Mode changes require bot restart**
   - Pro: Simple implementation
   - Con: Config hot-reload niet supported
   - Mitigation: Use `config` command + restart

---

## ✅ Implementation Checklist

- [x] Phase 2 early filtering in update_all_trends_v2()
- [x] Shadow mode logging (test-only, no filtering)
- [x] Mode parameter in orderbook_config
- [x] Controller passes orderbook_config to update calls (3 locations)
- [x] Config schema documentation updated
- [x] No syntax errors (flake8 clean)
- [ ] Shadow mode testing (1 hour Kraken bot)
- [ ] Early mode testing (compare performance)
- [ ] Production deployment (both bots)

---

## 🎯 Next Steps (Phase 4: Regime-Aware)

Na succesvolle Phase 2 deployment, implementeren:

### Phase 4: Regime-Aware Depth Thresholds
- BULL: 8.0x multiplier (looser, grotere orders mogelijk)
- CHOP: 5.0x multiplier (moderate, current default)
- BEAR: 10.0x multiplier (strictest, veiligheid eerst)

**Integration point:**
```python
# In _build_orderbook_config()
if market_regime == 'BULL':
    min_depth_multiplier = 8.0
elif market_regime == 'BEAR':
    min_depth_multiplier = 10.0
else:  # CHOP
    min_depth_multiplier = 5.0
```

---

## 📚 References

- **Architecture Spec:** User-provided liquidity architecture (4 phases)
- **Phase 1 Implementation:** INTEGRATION_V3.3_COMPLETE.md
- **Liquidity Proxy:** hummingbot/multi_coin_grid_controllers/utils/liquidity_proxy.py
- **Trend Calculator:** multi_coin_grid_pro/utils/trend_calculator.py (lines 645-1180)

---

**Implementation Status:** ✅ COMPLETE
**Recommended Next Action:** Test shadow mode op Kraken bot (1 uur monitoring)
