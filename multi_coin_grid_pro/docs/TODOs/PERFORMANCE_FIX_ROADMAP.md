# 🚀 PERFORMANCE FIX ROADMAP - IMPLEMENTATION PLAN

**Project:** Kraken Multi-Coin Grid V2 Performance Recovery
**Created:** 2026-01-12
**Owner:** Mo
**Status:** Ready to Build
**Target:** Fix 6 kritieke issues, +300% performance, +€8/day

---

## 📋 OVERVIEW

**Current State:**
- 73% rejection rate (21K/28K events)
- 99% executors geen fills
- €-8.26/dag dust losses
- 1,276 missed opportunities (SLOT_FULL)
- 1,963 exit blocks (grace period)

**Target State (na Fase 1+2):**
- <40% rejection rate (was 73%)
- 30-40% executor success (was 1%)
- Dust losses tracked & minimized (baseline: €-8.26/dag)
- 250-400 fills/dag (2-4× improvement over baseline)
- Clean inventory management (net drift ~0)

**ROI:** TBD - Meet first, optimize later
**Expected:** -60% wasted opportunities, cleaner execution, lower stuck capital

---

## 🎯 FASE 1: QUICK WINS - INCREMENTAL ROLLOUT (2-3 HOURS - START HIER!)

**Prioriteit:** P0 - Doe dit VANDAAG
**Impact:** -60% rejections, +100-200% fills, cleaner execution
**Risk:** Very Low (per change, met rollback)
**Skills:** Config editing (geen code!)

**⚠️ CRITICAL:** Deploy ONE change at a time, measure 60-90 min, then next change!
Dit voorkomt "changed 5 things, don't know what broke".

### ✅ Task 1.0: Universe Throttling (BIGGEST QUICK WIN!)
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Priority:** P0 - DO THIS FIRST!

```yaml
# FIND THIS SECTION (or wherever pair universe is defined):
# active_pairs: [list of 49 pairs...]

# CHANGE TO TOP 10-15 LIQUID EUR PAIRS:
active_pairs:
  - BTC-EUR
  - ETH-EUR
  - SOL-EUR
  - MATIC-EUR
  - ADA-EUR
  - DOT-EUR
  - LINK-EUR
  - AVAX-EUR
  - UNI-EUR
  - AAVE-EUR
  # Add 5 more if wanted (RENDER, TAO, etc.)
  # Avoid: illiquid pairs, high min order size pairs
```

**Why:** 49 pairs = WS overload, stale data, rate limits
**Impact:** -40-60% NO_PRICE_DATA/NO_ORDERBOOK immediately
**Test:** `grep "NO_.*_DATA" logs/*.log | wc -l` (should drop 50%+)

**Measure (60-90 min):**
- [ ] NO_PRICE_DATA rate drops
- [ ] NO_ORDERBOOK_DATA rate drops
- [ ] All 10-15 pairs have recent prices (<5s stale)
- [ ] No WS disconnect errors

**Per-Pair Performance Tracking (for optimization):**
```bash
# After 24-48h, analyze per pair:
python3 -c "
import json
from collections import defaultdict

pair_stats = defaultdict(lambda: {'fills': 0, 'rejections': 0, 'stale': 0})

with open('logs/events/events_*.jsonl') as f:
    for line in f:
        e = json.loads(line)
        symbol = e.get('symbol')
        if e.get('event_type') == 'gate_denied':
            pair_stats[symbol]['rejections'] += 1
            if 'NO_PRICE' in e.get('reason_code', ''):
                pair_stats[symbol]['stale'] += 1
        elif e.get('event_type') == 'gate_passed':
            pair_stats[symbol]['fills'] += 1

for pair, stats in sorted(pair_stats.items(), key=lambda x: x[1]['fills'], reverse=True):
    print(f'{pair:15} fills={stats[\"fills\"]:3}, rej={stats[\"rejections\"]:3}, stale={stats[\"stale\"]:3}')
"
# Use this to:
# - Remove consistently problematic pairs
# - Add high-performing pairs (RENDER, TAO)
# - Make universe data-driven, not static
```

**Expected:** This alone can fix 50% of your data pipeline issues!

---

### ✅ Task 1.1: Grace Period Reduction
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Line:** ~657

```yaml
# CHANGE THIS:
switch_grace_period_seconds: 420   # 7 min

# TO THIS:
switch_grace_period_seconds: 180   # 🚀 3 min (allow faster rotations)
```

**Why:** Positions stuck 21+ minuten, slots blocked
**Impact:** -57% grace blocks, immediate capital efficiency
**Test:** `grep "grace period" logs/*.log | wc -l` (should drop 80%)

**Measure (60-90 min):**
- [ ] Grace period blocks/hour < 100 (was ~200/h)
- [ ] Avg position duration drops (track in audits)
- [ ] Slot turnover increases
- [ ] No increase in bad exits (check PnL)

**Rollback if:** Grace blocks stay high OR avg trade PnL drops >20%

---

### ✅ Task 1.2: Slot Limit Increase
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Lines:** ~97-104, ~112-119, ~124-131

```yaml
# CHANGE THIS:
adaptive_filters:
  baseline:
    max_active_grids: 2
  BULL:
    max_active_grids: 3
  CHOP:
    max_active_grids: 1

# TO THIS:
adaptive_filters:
  baseline:
    max_active_grids: 4  # 🚀 2→4
  BULL:
    max_active_grids: 6  # 🚀 3→6
  CHOP:
    max_active_grids: 3  # 🚀 1→3
```

**Why:** 1,276 SLOT_FULL rejections, gemiste RENDER +10%, SOL +9%
**Impact:** -70% SLOT_FULL, +100% concurrent capacity
**Test:** Check events JSONL for SLOT_FULL drops

**⚠️ RISK CHECK - Add these limits:**
```yaml
# ADD AFTER max_active_grids:
risk_limits:
  max_total_open_order_value_pct: 75.0  # Total notional < 75% balance
  max_quote_alloc_per_grid_eur: 80.0    # €80 per grid max
  max_open_orders_per_grid: 8           # Limit order spam
```

**Measure (60-90 min):**
- [ ] SLOT_FULL rejections < 50/hour (was ~100/h)
- [ ] Total open order notional < 75% balance (check in logs)
- [ ] Active grids 3-6 (depending on regime)
- [ ] NO increase in INSUFFICIENT_BALANCE errors

**Rollback if:** Open order value >80% balance OR order spam >100/hour

**Note for Later (Fase 3):** Consider adding min PnL expectation per grid:
- Only start grid if: `expected_width × fill_rate > min_threshold`
- Prevents starting grids in choppy/low-opportunity pairs
- Makes slot allocation more selective

---

### ✅ Task 1.3: Filter Loosening
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Lines:** ~94, ~95, ~96

```yaml
# CHANGE THIS:
adaptive_filters:
  baseline:
    rsi_buy_min: 25.0
    atr_min_pct: 0.08
    max_up_accel_pct: 4.0
  BULL:
    # (probably inherits baseline or has own values)
  CHOP:
    # (probably stricter)

# TO THIS (REGIME-AWARE LOOSENING):
adaptive_filters:
  baseline:
    rsi_buy_min: 22.0           # 🚀 25→22 (moderate)
    atr_min_pct: 0.06           # 🚀 0.08→0.06 (more coins)
    max_up_accel_pct: 5.0       # 🚀 4→5 (moderate)
    max_down_accel_pct: -9.0    # 🚀 -8→-9 (moderate)
  BULL:
    rsi_buy_min: 20.0           # Lower in bull (catch dips)
    rsi_buy_max: 85.0           # Higher max (ride momentum)
    atr_min_pct: 0.05           # More relaxed
    max_up_accel_pct: 7.0       # Allow strong moves
  CHOP:
    rsi_buy_min: 25.0           # STRICTER in chop
    atr_min_pct: 0.07           # Higher ATR needed
    min_spread_bps: 15          # Wider spread required (avoid fee grind)
    min_orderbook_depth_eur: 5000  # Need liquidity
```

**Why:** 1,778 filter rejections (ATR_TOO_LOW, RSI, ACCEL)
**Impact:** +100-200 entries/day (realistic)
**Test:** Count gate_denied with reason_code filters

**Measure (60-90 min):**
- [ ] Filter rejections < 30/hour (was ~70/h)
- [ ] Fills/hour increases by 20-40%
- [ ] Fee/fill ratio stays reasonable (<0.5% avg)
- [ ] CHOP regime still selective (not fee grinding)

**🔧 IMPORTANT: Log Acceptance Reasons Too!**
```python
# In your filter logic, add:
if entry_allowed:
    self.logger().info(
        f"✅ {symbol} ACCEPTED | "
        f"regime={regime} rsi={rsi:.1f} atr={atr:.3f} "
        f"spread={spread_bps:.1f}bps accel={accel:.2f}% "
        f"confidence={confidence:.0f}%"  # Even if binary for now
    )
# This makes Fase 3 (confidence-based) much easier to build
```

**Rollback if:** Fees/hour spike >50% without PnL improvement

---

### ✅ Task 1.4: Dust Detection (Detection Only - NO PnL Changes Yet!)
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Location:** Add nieuwe sectie na professional_risk_mgmt

```yaml
# ADD THIS NEW SECTION:
# ==============================================================================
# DUST TRACKING (Track dust, don't auto-sell yet)
# ==============================================================================
dust_management:
  enabled: true
  detect_dust_only: true             # Just log, don't change PnL
  log_dust_closes: true              # Log all dust scenarios
  min_close_value_eur: 10.0          # Flag closes below this
```

**Why:** 35 FAILED closes appear to cause €-8.26/dag losses
**Impact:** **Track & log only** - verify dust is real problem before fixing
**Test:** Grep for "dust" in logs, count occurrences

**Measure (24 hours):**
- [ ] Count "dust close" events per day
- [ ] Calculate actual € value of dust (not just log errors)
- [ ] Verify if FAILED closes are really PnL hits or just log noise
- [ ] Check if dust accumulates or resolves naturally

**⚠️ DON'T:** Change PnL accounting yet - that's Fase 3!

---

### ✅ Task 1.5: Order Sizing Safety
**File:** `multi_coin_grid_pro/config/config.prod.yaml`
**Lines:** ~650, and add new section

```yaml
# CHANGE THIS:
risk_max_balance_per_trade_pct: 80  # 80% van €350 = €280

# TO THIS:
risk_max_balance_per_trade_pct: 60  # 🚀 60% (safer for 4-6 concurrent grids)

# ADD THIS NEW SECTION:
order_sizing:
  min_order_size_eur: 10.0           # Kraken minimum
  max_order_size_eur: 100.0          # Per order cap
  target_order_size_eur: 50.0        # Default for €350 account
  size_scaling_mode: "dynamic"       # Scale with balance
  reserve_balance_pct: 20.0          # Keep 20% in reserve (€70)
```

**Why:** 152 INSUFFICIENT_BALANCE closes
**Impact:** -90% insufficient balance errors
**Test:** No INSUFFICIENT_BALANCE in audit logs

**Measure (60-90 min):**
- [ ] No INSUFFICIENT_BALANCE errors
- [ ] All grids can place at least 1 order
- [ ] Reserve balance maintained (€50-70)
- [ ] Order sizes 25-80 EUR range

**Rollback if:** Still getting INSUFFICIENT_BALANCE errors

---

### 📝 FASE 1 INCREMENTAL CHECKLIST (ONE CHANGE AT A TIME!)

**Pre-Flight:**
- [ ] Backup: `cp config.prod.yaml config.prod.yaml.backup_20260112`
- [ ] Create health check script (see below)
- [ ] Baseline metrics: Run health check, save output

**Task 1.0: Universe Throttling (60-90 min)**
- [ ] Change active_pairs to 10-15 top liquid pairs
- [ ] Restart bot
- [ ] Run health check every 15 min (4-6 times)
- [ ] **Go/No-Go:** NO_PRICE_DATA drops >40% → PASS → Next task
- [ ] **Rollback if:** NO_PRICE_DATA same or worse

**Task 1.1: Grace Period (60-90 min)**
- [ ] Change grace 420→180
- [ ] Restart bot
- [ ] Run health check every 15 min
- [ ] **Go/No-Go:** Grace blocks drop, PnL stable → PASS → Next
- [ ] **Rollback if:** Grace blocks same OR PnL drops >20%

**Task 1.2: Slot Increase (60-90 min)**
- [ ] Change slots + add risk limits
- [ ] Restart bot
- [ ] Run health check every 15 min
- [ ] **Go/No-Go:** SLOT_FULL drops, exposure <75% → PASS → Next
- [ ] **Rollback if:** Exposure >80% OR INSUFFICIENT_BALANCE errors

**Task 1.3: Order Sizing (60 min)**
- [ ] Change sizing + reserve
- [ ] Restart bot
- [ ] Run health check every 15 min
- [ ] **Go/No-Go:** No INSUFFICIENT_BALANCE → PASS → Next

**Task 1.4: Filter Loosening (60-90 min)**
- [ ] Change filters (regime-aware)
- [ ] Restart bot
- [ ] Run health check every 15 min
- [ ] **Go/No-Go:** Fills increase, fees reasonable → PASS → Next
- [ ] **Rollback if:** Fees spike without PnL improvement

**Task 1.5: Dust Detection (24 hours)**
- [ ] Add dust tracking config
- [ ] Let run 24h, collect logs
- [ ] Analyze actual dust value
- [ ] Decide if Fase 2 dust fix needed

**Total Time:** 6-8 hours (with measurements)

**Health Check Script (create this!):**
```bash
#!/bin/bash
# save as: multi_coin_grid_pro/scripts/health_check.sh
echo "=== HEALTH CHECK $(date) ==="
echo ""
echo "Rejection Rates (last 1000 events):"
tail -1000 logs/events/events_*.jsonl | \
  python3 -c "import sys,json; \
  from collections import Counter; \
  c=Counter(json.loads(l).get('reason_code','OK') for l in sys.stdin if 'gate_denied' in l); \
  total=sum(c.values()); \
  print(f'Total denials: {total}'); \
  [print(f'  {k:30} {v:4} ({100*v/total:5.1f}%)') for k,v in c.most_common(10)]"

echo ""
echo "Fills/Cancels (last hour):"
grep -h "$(date -d '1 hour ago' +'%Y-%m-%d %H'):" logs/*.log | \
  grep -c "OrderFilled\|ORDER_FILLED" && \
grep -h "$(date -d '1 hour ago' +'%Y-%m-%d %H'):" logs/*.log | \
  grep -c "OrderCancelled\|ORDER_CANCELLED"

echo ""
echo "Active Executors:"
sqlite3 data/multi_coin_grid_v2.sqlite "SELECT COUNT(*) FROM Executors WHERE status='ACTIVE' OR status='RUNNING'"

echo ""
echo "Open Order Notional:"
# (approximation - adjust based on your DB schema)
sqlite3 data/multi_coin_grid_v2.sqlite "SELECT SUM(amount * price) FROM Order WHERE status='OPEN' OR status='PENDING'"

echo ""
echo "Decision Latency (last 100 gate_passed → order placed):"
# Log time between entry eligible and order placed
# TODO: Implement in bot logs - target <500ms
grep -h "gate_passed\|OrderPlaced" logs/*.log | tail -200 | \
  awk '/gate_passed/{t1=\$2} /OrderPlaced/{if(t1)print \$2-t1}' | \
  python3 -c "import sys; times=[float(x) for x in sys.stdin]; \
  print(f'  Avg: {sum(times)/len(times)*1000:.0f}ms, Max: {max(times)*1000:.0f}ms') if times else print('  No data')"

echo "==========================="
```

---

## 🔧 FASE 2: CORE FIXES (4-6 HOURS)

**Prioriteit:** P0 - Deze week
**Impact:** -85% data failures, -90% zero-fills, -100% dust losses
**Risk:** Low-Medium
**Skills:** Python development

### 🛠️ Task 2.1: Market Data Warm-up (Issue #1)
**Priority:** P0
**Time:** 1-2 hours
**Files to modify:** 3

#### 2.1.1: Add stale detection + resubscribe in MarketDataProvider
**File:** `multi_coin_grid_pro/data/market_data_provider.py`

```python
# TODO: Add at class level
import time
from collections import defaultdict

class MarketDataProvider:
    def __init__(self, ...):
        self._last_price_update: Dict[str, float] = {}
        self._last_ob_update: Dict[str, float] = {}
        self._stale_symbols: Set[str] = set()
        self._resubscribe_backoff: Dict[str, float] = defaultdict(lambda: 1.0)
        self._max_stale_seconds = 5.0

    def _is_ready(self, symbol: str) -> bool:
        """Check if we have recent data"""
        now = time.time()
        price_age = now - self._last_price_update.get(symbol, 0)
        ob_age = now - self._last_ob_update.get(symbol, 0)
        return price_age < self._max_stale_seconds and ob_age < self._max_stale_seconds

    def _mark_stale(self, symbol: str):
        """Mark symbol as stale and trigger recovery"""
        if symbol not in self._stale_symbols:
            self._stale_symbols.add(symbol)
            self.logger().warning(f"⚠️  {symbol} market data STALE - triggering resubscribe")
            asyncio.create_task(self._recover_symbol(symbol))

    async def _recover_symbol(self, symbol: str):
        """Attempt to recover stale symbol subscription"""
        backoff = self._resubscribe_backoff[symbol]
        await asyncio.sleep(backoff)  # Exponential backoff

        try:
            # Resubscribe to ticker + orderbook
            await self.exchange.unsubscribe_ticker(symbol)
            await self.exchange.unsubscribe_orderbook(symbol)
            await asyncio.sleep(0.5)  # Brief pause
            await self.exchange.subscribe_ticker(symbol)
            await self.exchange.subscribe_orderbook(symbol)

            self.logger().info(f"✅ Resubscribed {symbol}")

            # Wait to verify recovery
            await asyncio.sleep(5)
            if self._is_ready(symbol):
                self._stale_symbols.discard(symbol)
                self._resubscribe_backoff[symbol] = 1.0  # Reset backoff
                self.logger().info(f"✅ {symbol} recovered")
            else:
                # Still stale, increase backoff
                self._resubscribe_backoff[symbol] = min(backoff * 2, 60.0)
                self.logger().warning(f"⚠️  {symbol} still stale, will retry in {self._resubscribe_backoff[symbol]}s")
        except Exception as e:
            self.logger().error(f"Failed to recover {symbol}: {e}")
            self._resubscribe_backoff[symbol] = min(backoff * 2, 60.0)

    def get_mid_price(self, symbol: str) -> Optional[Decimal]:
        if not self._is_ready(symbol):
            self._mark_stale(symbol)  # Trigger recovery
            return None
        return self._prices.get(symbol)

    def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        if not self._is_ready(symbol):
            self._mark_stale(symbol)  # Trigger recovery
            return None
        return self._orderbooks.get(symbol)

    # TODO: Add periodic stale check (every 30s)
    async def _periodic_stale_check(self):
        """Background task to detect stale symbols"""
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for symbol in self.subscribed_symbols:
                if not self._is_ready(symbol):
                    self._mark_stale(symbol)
```

**Acceptance Criteria:**
- [ ] `_is_ready()` method implemented
- [ ] Stale detection marks symbols as UNHEALTHY
- [ ] Auto-resubscribe with exponential backoff
- [ ] Periodic stale check (30s background task)
- [ ] Unit test: Mock stale → verify resubscribe called
- [ ] Metrics: stale_symbol_count avg < 2
- [ ] Metrics: recovered_subscriptions_per_hour > 0
- [ ] NO_PRICE_DATA drops by 70-80%

---

#### 2.1.2: Add 30s warm-up on bot start
**File:** `multi_coin_grid_pro/scripts/multi_coin_grid_v2.py`

```python
# TODO: In start() method, after market_data.start()
async def start(self):
    await self.market_data.start()

    # NEW: Wait for initial data
    self.logger().info("⏳ Warming up market data feeds (30s)...")
    await asyncio.sleep(30)

    # Verify data availability
    ready_pairs = []
    for symbol in self.active_pairs:
        if self.market_data.is_ready(symbol):
            ready_pairs.append(symbol)
        else:
            self.logger().warning(f"⚠️  {symbol} not ready - skipping")

    self.logger().info(f"✅ Ready: {len(ready_pairs)}/{len(self.active_pairs)} pairs")

    # Continue with normal startup...
```

**Acceptance Criteria:**
- [ ] 30s delay on startup
- [ ] Log which pairs are ready/not ready
- [ ] Integration test: Start bot, verify all pairs ready after 30s

---

#### 2.1.3: Add retry logic in SmartEntryFilter
**File:** `multi_coin_grid_pro/filters/smart_entry_filter.py`

```python
# TODO: In check_spread() and similar methods
async def check_spread(self, symbol: str) -> FilterResult:
    price = await self.market_data.get_mid_price(symbol)

    # NEW: retry once if None
    if price is None:
        await asyncio.sleep(0.5)  # 500ms backoff
        price = await self.market_data.get_mid_price(symbol)
        if price is None:
            return FilterResult.deny("NO_PRICE_DATA", retriable=True)

    # Normal spread check logic...
```

**Acceptance Criteria:**
- [ ] 1x retry with 500ms backoff
- [ ] Unit test: Mock None → retry → success
- [ ] NO_PRICE_DATA drops further

---

### 🛠️ Task 2.2: Grace Bypass Logic (Issue #3)
**Priority:** P0
**Time:** 1-2 hours
**Files to modify:** 2

#### 2.2.1: Add grace_period_bypass config
**File:** `multi_coin_grid_pro/config/config.prod.yaml`

```yaml
# TODO: Add after switch_grace_period_seconds

grace_period_bypass:
  enabled: true
  bypass_on_tp_hit: true          # Exit immediately if TP reached
  bypass_on_sl_hit: true          # Exit immediately if SL reached
  bypass_on_inventory_full: true  # Exit if we need the slot
  bypass_on_regime_flip: true     # Exit if regime changed (BULL→CHOP)
  bypass_on_no_orders: true       # Exit if no orders + no fills > 5min
```

---

#### 2.2.2: Implement bypass logic in ExitManager
**File:** `multi_coin_grid_pro/execution/exit_manager.py` (or relevant exit logic file)

```python
# TODO: Add method
def should_bypass_grace_period(self, executor: GridExecutor) -> bool:
    """Check if we should override grace period"""
    config = self.config.get("grace_period_bypass", {})
    if not config.get("enabled", False):
        return False

    # Check TP/SL
    if config.get("bypass_on_tp_hit") and executor.is_tp_reached():
        self.logger().info(f"✅ {executor.symbol} bypass grace: TP hit")
        return True

    if config.get("bypass_on_sl_hit") and executor.is_sl_reached():
        self.logger().info(f"🛑 {executor.symbol} bypass grace: SL hit")
        return True

    # Check slot pressure
    if config.get("bypass_on_inventory_full") and self.slot_manager.is_full():
        self.logger().info(f"⚠️  {executor.symbol} bypass grace: need slot")
        return True

    # Check regime flip
    if config.get("bypass_on_regime_flip"):
        entry_regime = executor.entry_regime
        current_regime = self.regime_detector.get_regime()
        if entry_regime != current_regime:
            self.logger().info(f"🔄 {executor.symbol} bypass grace: {entry_regime}→{current_regime}")
            return True

    # Check dead grid
    if config.get("bypass_on_no_orders"):
        if executor.open_orders_count == 0 and executor.minutes_since_fill > 5:
            self.logger().info(f"💤 {executor.symbol} bypass grace: dead grid")
            return True

    return False

# TODO: Call this in exit check logic
# if in_grace_period and not should_bypass_grace_period(executor):
#     return  # Still blocked
```

**Acceptance Criteria:**
- [ ] All 5 bypass conditions implemented
- [ ] Unit tests for each condition
- [ ] Grace blocks drop by 80%
- [ ] Log bypass events

---

### 🛠️ Task 2.3: Pre-Close Validation (Prevent Bad Closes)
**Priority:** P1 - Prevent executor failures
**Time:** 1-2 hours
**Files to modify:** 1-2

#### 2.3.1: Add pre-flight close checks (NO PnL changes yet!)
**File:** `multi_coin_grid_pro/execution/executor_manager.py` (or wherever close logic is)

```python
# TODO: Add before attempting close
def can_safely_close(self, executor: GridExecutor) -> Tuple[bool, str]:
    """Check if position can be closed safely (before attempting)"""
    base_asset = executor.base_asset
    symbol = executor.symbol

    # Get actual exchange balance (NOT bot's tracked balance)
    try:
        actual_balance = self.exchange_connector.get_balance(base_asset)
    except Exception as e:
        return False, f"Can't query balance: {e}"

    # Get exchange minimums (these vary per pair!)
    try:
        trading_rule = self.exchange_connector.trading_rules[symbol]
        min_order_size = trading_rule.min_order_size
        min_notional = trading_rule.min_notional  # DON'T hardcode €10!
    except Exception as e:
        return False, f"Can't get trading rules: {e}"

    # Check 1: Do we have enough tokens?
    if actual_balance < min_order_size:
        return False, f"Dust: {actual_balance} < min {min_order_size}"

    # Check 2: Is value > min notional?
    mid_price = self.market_data.get_mid_price(symbol)
    if mid_price is None:
        return False, "No price data"

    order_value = actual_balance * mid_price
    if order_value < min_notional:
        return False, f"Below min notional: €{order_value:.2f} < €{min_notional:.2f}"

    return True, "OK"

# TODO: Use in close logic
async def close_executor(self, executor: GridExecutor):
    # Pre-flight check
    can_close, reason = self.can_safely_close(executor)

    if not can_close:
        self.logger().warning(f"⚠️  {executor.symbol} cannot close: {reason}")
        self.logger().warning(f"     Marking as CLOSE_PENDING for manual review")

        # DON'T book loss, DON'T change PnL
        # Just mark for manual intervention
        executor.status = "CLOSE_PENDING"
        executor.close_reason = reason
        return

    # Normal close logic...
    await self._execute_close(executor)
```

**Acceptance Criteria:**
- [ ] Pre-flight check implemented
- [ ] Uses actual exchange balance (not bot's tracked balance)
- [ ] Gets actual trading rules (not hardcoded €10)
- [ ] Logs dust scenarios without crashing
- [ ] Unit tests for dust detection
- [ ] No more FAILED closes that should have been detected

**Note:** Full dust cleanup + PnL fixes moved to Fase 3 (after we verify dust is real issue)

---

#### REMOVED: 2.3.2 and 2.3.3 (moved to Fase 3)
See Fase 3 for full dust cleanup implementation

---

### 📝 FASE 2 CHECKLIST

- [ ] **Task 2.1:** Market data stale detection + recovery
  - [ ] 2.1.1: Stale detection + resubscribe in MarketDataProvider
  - [ ] 2.1.2: 30s warm-up on start (OPTIONAL if 2.1.1 works)
  - [ ] 2.1.3: Retry logic in filters (OPTIONAL)
  - [ ] Unit tests pass
  - [ ] Metrics: stale_symbol_count < 2, recovered_subs > 0
  - [ ] NO_PRICE_DATA < 10% (was 31%)

- [ ] **Task 2.2:** Grace bypass logic implemented
  - [ ] 2.2.1: Config added
  - [ ] 2.2.2: Bypass logic in ExitManager
  - [ ] Unit tests for all 5 conditions
  - [ ] Grace blocks < 400/day (was 1963)

- [ ] **Task 2.3:** Pre-close validation
  - [ ] 2.3.1: Pre-flight checks (no PnL changes)
  - [ ] Uses actual exchange balance & trading rules
  - [ ] Logs dust scenarios
  - [ ] No more unexpected FAILED closes

- [ ] **Integration Testing:**
  - [ ] Run bot in paper mode for 4 hours
  - [ ] Check all metrics improved
  - [ ] No regressions in fees or PnL
  - [ ] Ready for production

---

## 🚀 FASE 3: ADVANCED + DUST CLEANUP (NEXT WEEK)

**Prioriteit:** P2 - Nice to have
**Impact:** Future-proof, professional-grade
**Time:** 10-14 hours

### Task 3.0: Dust Inventory Management (ONLY IF FASE 1.5 PROVES IT'S REAL)
**Priority:** P1 (conditional)
**Time:** 3-4 hours
**Files:** 3-4

**Prerequisites:**
- [ ] Fase 1.5 dust tracking ran for 24+ hours
- [ ] Verified actual € value of dust losses (not just log errors)
- [ ] Confirmed FAILED closes are real PnL hits
- [ ] Dust value > €5/day (worth fixing)

**If prerequisites met, implement:**

#### 3.0.1: Create DustInventoryTracker
**File:** `multi_coin_grid_pro/execution/dust_inventory_tracker.py` (NEW)

```python
from decimal import Decimal
from collections import defaultdict
from typing import Dict, Optional

class DustInventoryTracker:
    """Track dust inventory with mark-to-market valuation"""

    def __init__(self, config: dict, market_data):
        self.config = config.get("dust_management", {})
        self.market_data = market_data
        self.dust_positions: Dict[str, Decimal] = defaultdict(Decimal)
        self.write_off_threshold = Decimal("1.0")  # €1 threshold

    def add_dust(self, symbol: str, amount: Decimal):
        """Add dust position (unrealized, not booked as loss yet)"""
        self.dust_positions[symbol] += amount
        value = self.get_dust_value(symbol)
        self.logger().info(
            f"💎 {symbol} dust added: {amount} (total: {self.dust_positions[symbol]}, "
            f"value: €{value:.4f})"
        )

    def get_dust_value(self, symbol: str) -> Decimal:
        """Get current mark-to-market value of dust"""
        amount = self.dust_positions.get(symbol, Decimal("0"))
        if amount == 0:
            return Decimal("0")

        mid_price = self.market_data.get_mid_price(symbol)
        if mid_price is None:
            return Decimal("0")

        return amount * mid_price

    def get_total_dust_value(self) -> Decimal:
        """Total unrealized dust value across all symbols"""
        return sum(self.get_dust_value(s) for s in self.dust_positions.keys())

    def should_write_off(self, symbol: str) -> bool:
        """Check if dust is below write-off threshold"""
        value = self.get_dust_value(symbol)
        return value < self.write_off_threshold and value > 0
```

#### 3.0.2: Dust Cleanup via Maker Orders (NOT market sells!)
**File:** `multi_coin_grid_pro/execution/dust_cleanup_manager.py` (NEW)

```python
async def cleanup_dust_maker(self, symbol: str, amount: Decimal):
    """Cleanup dust using MAKER orders (avoid slippage)"""
    # Get orderbook
    ob = self.market_data.get_orderbook(symbol)
    if ob is None:
        self.logger().warning(f"No orderbook for {symbol} dust cleanup")
        return False

    # Place limit order at best ask (post-only)
    best_ask = ob.best_ask_price
    try:
        order = await self.exchange.place_order(
            symbol=symbol,
            side="SELL",
            order_type="LIMIT",
            amount=amount,
            price=best_ask,
            post_only=True  # Ensures maker fee!
        )

        self.logger().info(f"🧹 Dust cleanup order placed: {symbol} {amount} @ {best_ask}")

        # Wait up to 5 min for fill
        await asyncio.sleep(300)

        # Check if filled
        order_status = await self.exchange.get_order_status(order.id)
        if order_status == "FILLED":
            self.dust_tracker.dust_positions[symbol] = Decimal("0")
            self.logger().info(f"✅ Dust cleanup filled: {symbol}")
            return True
        else:
            # Cancel and retry later
            await self.exchange.cancel_order(order.id)
            return False
    except Exception as e:
        self.logger().error(f"Dust cleanup failed for {symbol}: {e}")
        return False
```

#### 3.0.3: Update PnL Accounting (Mark Dust as Unrealized)
**File:** `multi_coin_grid_pro/execution/pnl_calculator.py`

```python
def calculate_realized_pnl(self, executor, close_result) -> Decimal:
    # If close was blocked due to dust:
    if close_result.status == "DUST_PENDING":
        # Don't book as realized loss
        # Track as unrealized inventory
        dust_value = self.dust_tracker.get_dust_value(executor.symbol)

        self.logger().info(
            f"💎 {executor.symbol} close blocked (dust). "
            f"Tracking as unrealized: €{dust_value:.4f}"
        )

        # Return 0 realized PnL (it's unrealized!)
        return Decimal("0")

    # Normal PnL...
```

**Acceptance Criteria:**
- [ ] Dust tracked as unrealized, not loss
- [ ] Cleanup uses maker orders (post-only)
- [ ] Periodic cleanup attempts (every 6h)
- [ ] Write-off for <€1 dust
- [ ] Daily report shows dust value
- [ ] No impact on realized PnL accuracy

---

### Task 3.1: Dynamic Slot Manager
**File:** `multi_coin_grid_pro/execution/slot_manager.py` (NEW)
**Time:** 2-3 hours

Account-size-aware slot scaling:
- €350 → 4 slots
- €1000 → 6 slots
- €2000 → 8 slots
- Regime multipliers (BULL 1.5x, CHOP 0.75x)

---

### Task 3.2: Coin-Specific Filter Profiles
**File:** `multi_coin_grid_pro/filters/adaptive_filter_engine.py`
**Time:** 2-3 hours

Per-coin overrides:
- Low-vol: BNB, ADA (ATR 0.05%)
- High-vol: PEPE, BONK (ATR 15%)
- Momentum: RENDER, SOL (accel 8%, RSI 90)

---

### Task 3.3: Real-Time Inventory Reconciliation
**File:** `multi_coin_grid_pro/execution/inventory_reconciler.py` (NEW)
**Time:** 2-3 hours

Every 5min:
- Query exchange balances
- Compare with bot state
- Log discrepancies
- Auto-correct small drifts
- Alert on large drifts

---

### Task 3.4: Confidence-Based Filtering
**Files:** Multiple filter modules
**Time:** 4-5 hours

Replace binary pass/fail with 0-100% confidence:
- 90%+ → auto-trade
- 70-90% → trade if slots available
- 50-70% → trade only in BULL
- <50% → reject

---

## 📊 TESTING STRATEGY

### Unit Tests
```bash
# After each task
pytest test/multi_coin_grid_pro/test_market_data_provider.py -v
pytest test/multi_coin_grid_pro/test_exit_manager.py -v
pytest test/multi_coin_grid_pro/test_dust_cleanup_manager.py -v
pytest test/multi_coin_grid_pro/test_inventory_manager.py -v
```

### Integration Tests
```bash
# After Fase 2 complete
./start_bot.sh --paper --config config.prod.yaml

# Monitor for 4 hours:
# - tail -f logs/*.log | grep "ERROR\|WARNING"
# - watch -n 10 'sqlite3 data/multi_coin_grid_v2.sqlite "SELECT COUNT(*) FROM Executors WHERE is_active=1"'
# - python3 -c "import json; ..." # Check events JSONL
```

### Performance Benchmarks
```bash
# Before vs After comparison
python3 scripts/compare_performance.py \
  --before logs/events/events_20260111_224340.jsonl \
  --after logs/events/events_20260113_XXXXXX.jsonl
```

---

## 🎯 SUCCESS CRITERIA

### Fase 1 (2-3 hours incremental)
- [ ] Task 1.0: Universe throttling
  - [ ] NO_PRICE_DATA rate drops >40%
  - [ ] All active pairs have <5s stale data
- [ ] Task 1.1: Grace period
  - [ ] Grace blocks < 100/hour
  - [ ] Avg PnL per trade stable or improved
- [ ] Task 1.2: Slot increase
  - [ ] SLOT_FULL < 50/hour
  - [ ] Total open order value < 75% balance
  - [ ] Active grids 3-6 depending on regime
- [ ] Task 1.3: Order sizing
  - [ ] No INSUFFICIENT_BALANCE errors
  - [ ] All grids can place orders
- [ ] Task 1.4: Filter loosening
  - [ ] Filter rejections < 30/hour
  - [ ] Fills increase 20-50%
  - [ ] Fee/fill ratio stays <0.5%
- [ ] Task 1.5: Dust tracking
  - [ ] Dust scenarios logged
  - [ ] Actual € value calculated

### Fase 2 (4-6 hours)
- [ ] All code implemented
- [ ] Unit tests pass (>70% coverage)
- [ ] Integration test 4h clean run
- [ ] NO_PRICE_DATA < 10% (was 31%)
- [ ] Stale symbols avg < 2
- [ ] Grace blocks < 400/day (was 1963)
- [ ] No more unexpected FAILED closes
- [ ] Executor success > 30% (was 1%)

### Production (24 hours post-deploy)
- [ ] Overall rejection rate < 40% (was 73%)
- [ ] Fills > 250/day (baseline ~100)
- [ ] Net inventory drift < 20% of balance
- [ ] Order cancel rate < 30% of placed orders
- [ ] Zero-fill executors < 30% (was 99%)
- [ ] No critical errors
- [ ] Fee burn < 1% of traded volume
- [ ] PnL positive or neutral (not worse than before)

---

## 🚨 ROLLBACK PLAN

### If any Fase 1 task fails:
```bash
# Each task is incremental, just revert that specific change
cp config.prod.yaml.backup_20260112 config.prod.yaml
./restart_bot.sh

# Or revert just one setting (e.g., grace period):
# Manually edit config.prod.yaml, change grace back to 420
```

### If Fase 2 has issues:
```bash
git checkout HEAD -- multi_coin_grid_pro/data/market_data_provider.py
git checkout HEAD -- multi_coin_grid_pro/execution/
cp config.prod.yaml.backup_20260112 config.prod.yaml
./restart_bot.sh
```

### Rollback Triggers (per task):

**Task 1.0 (Universe):**
- NO_PRICE_DATA same or worse after 90 min
- WS disconnects increase

**Task 1.1 (Grace):**
- Grace blocks don't decrease
- Avg PnL per trade drops >20%
- Exit quality degrades (more losses)

**Task 1.2 (Slots):**
- Total open order value >80% balance
- INSUFFICIENT_BALANCE errors appear
- Order spam >100/hour

**Task 1.3 (Sizing):**
- INSUFFICIENT_BALANCE errors persist
- Can't place orders for any grid

**Task 1.4 (Filters):**
- Fees spike >50% without PnL improvement
- Fee/fill ratio >0.7% consistently
- Trade quality drops (more losses)

**General triggers (any phase):**
- Critical error rate >10/hour
- Overall rejection rate >80%
- PnL < -3% in 4 hours
- Exchange rate limit errors
- Bot crashes/restarts >2 times

---

## 📝 DEVELOPMENT NOTES

### File Locations (waar je moet zoeken)
```
multi_coin_grid_pro/
├── config/
│   └── config.prod.yaml              # All config changes
├── data/
│   └── market_data_provider.py       # Task 2.1.1
├── scripts/
│   └── multi_coin_grid_v2.py         # Task 2.1.2
├── filters/
│   └── smart_entry_filter.py         # Task 2.1.3
├── execution/
│   ├── exit_manager.py               # Task 2.2.2 (if exists)
│   ├── inventory_manager.py          # Task 2.3.2 (if exists)
│   ├── dust_cleanup_manager.py       # Task 2.3.1 (NEW)
│   └── pnl_calculator.py             # Task 2.3.3 (if exists)
└── docs/
    └── TODOs/
        └── PERFORMANCE_FIX_ROADMAP.md  # THIS FILE
```

### Testing Commands
```bash
# Run health check (use script from Fase 1 checklist)
./multi_coin_grid_pro/scripts/health_check.sh

# Create simple monitoring dashboard
python3 -c '
import json, sqlite3, time
from collections import Counter
from pathlib import Path

print("=== PERFORMANCE DASHBOARD ===")
print(f"Time: {time.strftime("%Y-%m-%d %H:%M:%S")}\n")

# Rejection stats (last 1000 events)
print("Rejection Rates (last 1000 events):")
event_files = sorted(Path("logs/events").glob("events_*.jsonl"))
if event_files:
    with open(event_files[-1]) as f:
        events = [json.loads(line) for line in f.readlines()[-1000:]]
    denied = [e for e in events if e.get("event_type") == "gate_denied"]
    total = len(events)
    reasons = Counter(e.get("reason_code") for e in denied)
    print(f"  Total events: {total}, Denied: {len(denied)} ({100*len(denied)/total:.1f}%)")
    for reason, count in reasons.most_common(5):
        print(f"    {reason:30} {count:4} ({100*count/len(denied):5.1f}%)")
print()

# Executor stats
print("Executor Status:")
db = sqlite3.connect("data/multi_coin_grid_v2.sqlite")
cur = db.cursor()
active = cur.execute("SELECT COUNT(*) FROM Executors WHERE status IN ('ACTIVE', 'RUNNING')").fetchone()[0]
total = cur.execute("SELECT COUNT(*) FROM Executors").fetchone()[0]
print(f"  Active: {active}, Total: {total}")

# PnL summary
pnl = cur.execute("SELECT SUM(net_pnl_quote), SUM(cum_fees_quote) FROM Executors").fetchone()
print(f"  Total PnL: €{pnl[0] or 0:.2f}, Fees: €{pnl[1] or 0:.2f}")

# Recent fills
recent_fills = cur.execute(
    "SELECT COUNT(*) FROM TradeFill WHERE timestamp > ?",
    (int((time.time() - 3600) * 1e6),)
).fetchone()[0]
print(f"  Fills last hour: {recent_fills}")

db.close()
print("\n=============================\n")
'
```
# Check rejection stats
python3 -c "
import json
from collections import Counter
reasons = Counter()
with open('logs/events/events_*.jsonl') as f:
    for line in f:
        event = json.loads(line)
        if event.get('event_type') == 'gate_denied':
            reasons[event.get('reason_code')] += 1
for k,v in reasons.most_common(10):
    print(f'{k:30} {v:5}')
"

# Check dust errors
grep -c "could not auto-close" logs/*.log

# Check executor success
python3 -c "
import json
success = fail = 0
with open('audits/2026-01-13.jsonl') as f:
    for line in f:
        e = json.loads(line)
        if e.get('num_fills', 0) > 0: success += 1
        else: fail += 1
print(f'Success: {success}, Fail: {fail}, Rate: {100*success/(success+fail):.1f}%')
"
```

---


## ⚠️ EXPECTED BEHAVIOR & REALITY CHECK

### 📈 Non-Linear Improvement Pattern

**What Will Actually Happen:**
```
Task 1.0 (Universe):     🚀🚀🚀  HUGE WIN (40-60% issues solved!)
Task 1.1 (Grace):        🚀🚀    Clear improvement
Task 1.2 (Slots):        🚀🚀    Clear improvement
Task 1.3 (Sizing):       🚀      Stability (fewer errors)
Task 1.4 (Filters):      🚀      Incremental gains
Task 1.5 (Dust):         📊      Measurement only
```

**Expected:** Big wins early (Task 1.0), then refinement.
**Don't:** Stop after Task 1.0 thinking "good enough" - complete the foundation!

---

### 🔥 First 24-48h: Set Your Expectations!

**You WILL See (✅ Good Signs):**
- Fills increase 50-150%
- NO_PRICE_DATA drops dramatically
- Rejections drop overall
- More concurrent grids (2-4 active)
- Faster position rotations

**You MIGHT See (⚠️ Don't Panic - This is Normal!):**
- **Fees ↑** (more trades = more fees, but better than sitting idle)
- **PnL ~ flat** (removing blockers first, optimizing later)
- **Buy/sell ratio still imbalanced** (takes time to normalize)
- **Some pairs still problematic** (why you track per-pair!)
- **Occasional stale data** (Kraken reality, now handled gracefully)

**This is NORMAL!** You're building a stable foundation, not instant profits.

---

### 🚧 More Fills ≠ Better PnL (At First)

**Why This Matters:**

```
Phase 1 (Now):     Remove blockers → More execution
Phase 2 (Week 2):  Fix core logic → Better execution
Phase 3 (Week 3+): Optimize → Profitable execution
```

**Current Phase:** Removing friction (slots, grace, data, filters)
**Next Phase:** Better timing (entry/exit optimization)
**Final Phase:** Measured profitability

Don't get discouraged if PnL doesn't moon immediately. Stable execution enables profitability.

---

### 🏛️ The Kraken Reality

**Accept This Truth:**
- Kraken EUR pairs = more fragile than Binance/Bitget USDT
- Even with perfect code, you'll still have:
  - Occasional WS disconnects
  - Orderbook lag
  - Brief stale data periods

**Your Goal This Phase:**
- ✅ Make bot **resilient** to Kraken's quirks
- ✅ Graceful degradation (not crashes)
- ✅ Measure real performance ceiling
- ❌ NOT: "Perfect bot on perfect exchange"

**Think:** "Kraken-proof" not "Kraken-perfect"

---

### ⏱️ Decision Latency Watch

**New Risk:** Retries + warmup + resubscribe can slow decisions

**Monitor:** Time from "entry eligible" → "order placed"
- <500ms = ✅ Excellent
- 500ms-2s = ⚠️ Acceptable (some missed fills tolerable)
- >2s = 🛑 Too slow (optimize retry logic)

**Already tracked in health check!** If creeping up, tune retry delays.

---

### 🎯 Success Timeline

**Week 1:** Executor success 1% → 30-40% (remove blockers)
**Week 2:** Stable data + smart exits + pre-checks (fix core)
**Week 3+:** Measured ROI + optimization + dust cleanup (refine)

---

## � FINAL DELIVERABLE

Na completion:
- [ ] Update `PERFORMANCE_DEGRADATION_ROOT_CAUSE_ANALYSIS.md` met actual results
- [ ] Create `IMPLEMENTATION_LOG.md` met:
  - [ ] What you did (each task)
  - [ ] Actual metrics before/after each change
  - [ ] What worked / what didn't
  - [ ] Any deviations from plan
  - [ ] Lessons learned
- [ ] Document final config (`config.prod.yaml.final`)
- [ ] Create ongoing monitoring queries/dashboard
- [ ] Schedule 1-week follow-up review
- [ ] If dust is real issue: plan Fase 3 dust cleanup
- [ ] Identify next optimization targets

---

## 📊 MEASUREMENT-FIRST PHILOSOPHY

**Critical Mindset:**
1. ✅ **One change at a time** - Know what worked
2. ✅ **Measure before/after** - Prove impact
3. ✅ **Set rollback triggers** - Fast revert if bad
4. ✅ **Log everything** - Debug when needed
5. ✅ **Realistic targets** - 2-4× improvement is great!
6. ✅ **Verify assumptions** - Dust might not be €8/day
7. ✅ **Fee awareness** - More trades ≠ more profit
8. ✅ **Risk limits** - Don't blow up exposure

**Red Flags to Watch:**
- ⚠️ Fees spike without PnL improvement
- ⚠️ Open order value >80% balance
- ⚠️ Order cancel rate >40%
- ⚠️ Net inventory drift >30%
- ⚠️ Same errors keep appearing
- ⚠️ Exchange rate limit warnings

---

## 🛣️ RECOMMENDED EXECUTION ORDER

**Week 1 - Day 1-2 (Fase 1):**
1. Universe throttling (90 min + measure)
2. Grace period (90 min + measure)
3. Slots + risk limits (90 min + measure)
4. Order sizing (60 min + measure)
5. Filters (90 min + measure)
6. Dust tracking (deploy, let run 24h)

**Week 1 - Day 3-4 (Fase 2):**
7. Market data stale detection (4-6 hours)
8. Grace bypass logic (2-3 hours)
9. Pre-close validation (2 hours)
10. Integration testing (4 hours paper)

**Week 2 (Fase 3 - Optional):**
11. Review dust tracking data
12. If dust is real issue: implement cleanup
13. Advanced features (dynamic slots, coin profiles)
14. Inventory reconciliation

**Total realistic time:** 12-16 hours over 1-2 weeks

---

## 🔑 KEY IMPROVEMENTS FROM FEEDBACK

**What Changed:**
1. ✅ **Incremental rollout** - One change at a time with measurement
2. ✅ **Universe throttling added** - Biggest quick win (Task 1.0)
3. ✅ **Realistic targets** - 250-400 fills/day, not 800-1200
4. ✅ **Stale detection** - Auto-resubscribe, not just warm-up
5. ✅ **Risk checks** - Exposure limits with slot increase
6. ✅ **Regime-aware filters** - Different thresholds per market state
7. ✅ **Dust simplified** - Track first, fix later (Fase 3)
8. ✅ **Health dashboard** - Simple monitoring script
9. ✅ **Better rollback triggers** - Per-task specific triggers
10. ✅ **Measurement-first** - Prove before proceeding

**What We Avoided:**
- ❌ Changing 5 things at once
- ❌ Unrealistic 800 trades/day target
- ❌ Hardcoded €10 minimums
- ❌ Market sell dust (use maker orders)
- ❌ Assuming dust = €8/day without proof
- ❌ Ignoring fee impact
- ❌ Missing risk exposure checks

---

**Status:** Ready to Start
**Next Action:** Task 1.0 - Universe Throttling
**Est. Total Time:** 12-16 hours (over 1-2 weeks)
**Expected Impact:** 2-4× performance improvement, cleaner execution, measured ROI

Good luck! 🚀 **Remember: Measure, don't guess!**
