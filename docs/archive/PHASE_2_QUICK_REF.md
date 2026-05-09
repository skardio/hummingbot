# Phase 2 + Shadow Mode - Quick Reference 🚀

## ⚡ 3 Modi in 30 Seconden

### Mode 1: Shadow (Testing)
```yaml
orderbook_liquidity:
  enabled: true
  mode: shadow  # Logs maar filtert NIET
```
**Gebruik:** Test nieuwe thresholds veilig

---

### Mode 2: Ranking (Current Default)
```yaml
orderbook_liquidity:
  enabled: true
  mode: ranking  # Filtert tijdens coin selection
```
**Gebruik:** Huidige productie (Phase 1 behavior)

---

### Mode 3: Early (Performance)
```yaml
orderbook_liquidity:
  enabled: true
  mode: early  # Filtert VOOR trend berekening
```
**Gebruik:** Best performance (Phase 2 optimization)

---

## 🎯 Welke Mode Gebruiken?

| Situatie | Mode | Reden |
|----------|------|-------|
| Test nieuwe config | **shadow** | Geen trading impact |
| Eerste keer gebruiken | **shadow** → **ranking** | Veilig valideren eerst |
| Productie (nu) | **ranking** | Current behavior |
| Productie (optimaal) | **early** | 32% sneller |

---

## 🔧 Hoe Gebruiken?

### Stap 1: Shadow Mode (Testing)
```bash
# Via Hummingbot command line:
config orderbook_liquidity '{"enabled": true, "mode": "shadow", "depth_pct_range": 0.5, "depth_levels": 10, "min_depth_multiplier": 5.0}'

# Check logs:
tail -f logs/*.log | grep Shadow
```

### Stap 2: Analyze Results
```bash
# Hoeveel coins zouden PASS/FAIL?
grep "Shadow:" logs/*.log | grep "would PASS" | wc -l
grep "Shadow:" logs/*.log | grep "would FAIL" | wc -l
```

### Stap 3: Production Mode
```bash
# Als shadow results goed zijn → early mode:
config orderbook_liquidity '{"enabled": true, "mode": "early", "depth_pct_range": 0.5, "depth_levels": 10, "min_depth_multiplier": 5.0}'

# Restart bot:
stop
start
```

---

## 📊 Expected Output Examples

### Shadow Mode:
```
👻 Shadow Mode: Testing depth filtering (would require €400.00) - NO actual filtering
✅ Shadow: BTC-EUR would PASS (bid: €850.25 >= €400.00)
❌ Shadow: SHIB-EUR would FAIL (bid: €120.50 < €400.00) - but NOT filtering
👻 Shadow Mode: 8/14 would pass depth check
```

### Early Mode:
```
🔍 Phase 2 Early Filtering: Checking 14 coins for depth >= €400.00
✅ Phase 2 Early Filtering: 8 passed, 6 filtered (8/14 will update trends)
```

### Ranking Mode:
```
🔍 Depth filtering: 6 coins filtered out (8 liquid coins remain)
```

---

## ⚙️ Config Parameters Explained

```yaml
orderbook_liquidity:
  enabled: true          # Master switch
  mode: early            # 'shadow' | 'ranking' | 'early'
  depth_pct_range: 0.5   # Check ±0.5% from mid price
  depth_levels: 10       # Top 10 orderbook levels
  min_depth_multiplier: 5.0  # Require 5x order_size in depth
```

**depth_pct_range:**
- 0.5 = check bid/ask depth within ±0.5% of mid price
- Smaller = stricter (moet meer liquiditeit DIRECT bij mid price zijn)

**min_depth_multiplier:**
- 5.0 = require 5x your order size in orderbook depth
- Example: €80 order → need €400 depth
- Higher = stricter filtering

---

## 🚀 Performance Impact

**14 coins, 6 illiquid (43%):**

| Mode | Trend Updates | Depth Checks | Total Time | Improvement |
|------|--------------|--------------|------------|-------------|
| ranking | 14 updates | 14 checks | 2.8s | baseline |
| early | 8 updates | 14 checks | 1.9s | **32% faster** |

---

## 🎯 Recommended Workflow

1. **Week 1:** Shadow mode (validate thresholds)
2. **Week 2:** Early mode testing (compare performance)
3. **Week 3+:** Production early mode (both bots)

---

## 📝 Full Documentation

See: [PHASE_2_SHADOW_MODE_IMPLEMENTATION.md](PHASE_2_SHADOW_MODE_IMPLEMENTATION.md)
