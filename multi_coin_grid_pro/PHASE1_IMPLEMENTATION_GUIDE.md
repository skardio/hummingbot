# 🚀 PHASE 1 IMPLEMENTATION OVERVIEW
**Updated:** 2025-11-15
**Status:** Ready to implement
**Priority:** CRITICAL - Must complete before €500+ capital

---

## 📊 PHASE 1 EXPANDED: 6 Critical Features

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: CRITICAL RISK MANAGEMENT (11 hours)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1.1  Stop-Loss Mechanism           [🔥 2.0h]  Per-coin       │
│       └─ Liquidate at -8% loss                                 │
│                                                                 │
│  1.2  Circuit Breaker               [🔥 2.0h]  Volatility     │
│       └─ Pause on 5% spike in 1 min                           │
│                                                                 │
│  1.3  API Error Handling            [🔥 1.5h]  Resilience    │
│       └─ Exponential backoff, graceful degradation            │
│                                                                 │
│  1.4  Position Size Limits          [🔥 1.0h]  Capital mgmt  │
│       └─ Max exposure, liquidity checks                        │
│                                                                 │
│  1.5  Daily Risk Limits      🆕     [🔥 1.5h]  Daily P&L     │
│       └─ Stop at -3% daily loss, lock until next day          │
│                                                                 │
│  1.6  Market-Wide Risk       🆕     [🔥 3.0h]  Systemic      │
│       └─ BTC crash detector, market stress protection          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  TOTAL: 11 hours  |  6 features  |  All CRITICAL              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Implementation Order (Recommended)

### Week 1 - Foundation (Days 1-2)
```
Day 1 Morning:   1.1 Stop-Loss (2h)
Day 1 Afternoon: 1.2 Circuit Breaker (2h)
Day 2 Morning:   1.3 API Error Handling (1.5h)
Day 2 Afternoon: 1.4 Position Limits (1h)
```

### Week 1 - Advanced Protection (Days 3-4)
```
Day 3 Morning:   1.5 Daily Risk Limits (1.5h)
Day 3 Afternoon: 1.6 Market-Wide Risk - Part 1 (1.5h)
Day 4 Morning:   1.6 Market-Wide Risk - Part 2 (1.5h)
Day 4 Afternoon: Integration Testing (2h)
```

### Week 2 - Testing & Validation
```
Day 5: Unit tests for all 6 features
Day 6: Integration testing
Day 7: Live testing with €100
```

---

## 🔥 Feature Breakdown

### 1.1 Stop-Loss Mechanism
**Time:** 2 hours
**Files:**
- `src/risk/stop_loss.py` (new)
- `src/core/bot.py` (integration)

**Implementation:**
```python
class StopLoss:
    def __init__(self, trigger_pct=-0.08):
        self.trigger_pct = trigger_pct
        self.entry_prices = {}  # coin -> entry_price

    def check(self, coin, current_price):
        entry = self.entry_prices.get(coin)
        if not entry:
            return False

        loss_pct = (current_price - entry) / entry

        if loss_pct <= self.trigger_pct:
            return True  # TRIGGER!
        return False

    def liquidate(self, coin):
        # Sell all, cancel orders, switch to next coin
        pass
```

**Tests:**
- Simulate coin drop from €100 → €92 (trigger at €92)
- Simulate coin drop from €100 → €80 (large loss)
- Test entry price tracking
- Test liquidation logic

---

### 1.2 Circuit Breaker
**Time:** 2 hours
**Files:**
- `src/risk/circuit_breaker.py` (new)

**Implementation:**
```python
class CircuitBreaker:
    def __init__(self, vol_threshold=0.05):
        self.vol_threshold = vol_threshold
        self.price_history = deque(maxlen=60)  # 1 min

    def check_volatility(self, price):
        self.price_history.append(price)

        if len(self.price_history) < 60:
            return False

        min_price = min(self.price_history)
        max_price = max(self.price_history)

        vol = (max_price - min_price) / min_price

        if vol > self.vol_threshold:
            return True  # TRIP BREAKER!
        return False
```

**Tests:**
- Normal volatility: 1% move
- High volatility: 5% move in 60s
- Flash crash: 10% drop in 10s
- Recovery after breaker trip

---

### 1.3 API Error Handling
**Time:** 1.5 hours
**Files:**
- `src/market/exchange.py` (enhance existing)
- `src/utils/retry.py` (new)

**Implementation:**
```python
class ExchangeWrapper:
    def __init__(self):
        self.consecutive_errors = 0
        self.max_errors = 3

    def safe_call(self, func, *args, **kwargs):
        for attempt in range(3):
            try:
                result = func(*args, **kwargs)
                self.consecutive_errors = 0  # Reset
                return result
            except Exception as e:
                self.consecutive_errors += 1

                if self.consecutive_errors >= self.max_errors:
                    # PAUSE TRADING
                    raise CriticalError("Too many errors")

                # Exponential backoff
                sleep_time = 2 ** attempt
                time.sleep(sleep_time)
```

**Tests:**
- Single API error (should retry)
- 2 consecutive errors (should retry)
- 3 consecutive errors (should pause)
- Network timeout
- Rate limit handling

---

### 1.4 Position Size Limits
**Time:** 1 hour
**Files:**
- `src/risk/position_limits.py` (new)

**Implementation:**
```python
class PositionLimits:
    def __init__(self, max_per_coin=80, max_total=90):
        self.max_per_coin = max_per_coin
        self.max_total = max_total

    def can_trade(self, coin, amount):
        current_exposure = self.get_exposure(coin)
        total_exposure = self.get_total_exposure()

        if current_exposure + amount > self.max_per_coin:
            return False, "Exceeds per-coin limit"

        if total_exposure + amount > self.max_total:
            return False, "Exceeds total limit"

        return True, "OK"
```

**Tests:**
- Single position within limit
- Single position exceeds limit
- Total exposure exceeds limit
- Multiple positions

---

### 1.5 Daily Risk Limits 🆕
**Time:** 1.5 hours
**Files:**
- `src/risk/daily_limits.py` (new)

**Implementation:**
```python
class DailyRiskLimits:
    def __init__(self, max_loss_pct=-0.03):
        self.max_loss_pct = max_loss_pct
        self.daily_start_capital = None
        self.last_reset = None
        self.locked = False

    def check_and_reset(self):
        now = datetime.utcnow()

        # Reset at midnight UTC
        if self.last_reset is None or now.date() > self.last_reset.date():
            self.daily_start_capital = self.get_current_capital()
            self.last_reset = now
            self.locked = False

    def check_breach(self):
        if self.locked:
            return True, "Locked until next day"

        current = self.get_current_capital()
        loss_pct = (current - self.daily_start_capital) / self.daily_start_capital

        if loss_pct <= self.max_loss_pct:
            self.locked = True
            return True, f"Daily loss limit breached: {loss_pct:.2%}"

        return False, "OK"
```

**Real-world scenarios:**
```
Scenario A: Multiple Small Losses
09:00 - Start: €100
10:00 - Trade 1: -€1 (€99, -1%)
11:00 - Trade 2: -€1 (€98, -2%)
12:00 - Trade 3: -€1 (€97, -3%) ← TRIGGER! Lock trading.

Scenario B: One Large Loss
09:00 - Start: €100
10:00 - Big loss: -€3.50 (€96.50, -3.5%) ← TRIGGER! Lock trading.

Scenario C: Profit then Loss
09:00 - Start: €100
10:00 - Profit: +€5 (€105)
11:00 - Loss: -€8 (€97, -3% from start) ← TRIGGER!
```

**Tests:**
- Multiple small losses → lock
- One large loss → lock
- Profit then loss → check from daily start
- Reset at midnight UTC
- Locked state persists until reset

---

### 1.6 Market-Wide Risk Layer 🆕
**Time:** 3 hours
**Files:**
- `src/risk/market_risk.py` (new)
- `src/market/btc_monitor.py` (new)

**Implementation:**
```python
class MarketRiskMonitor:
    def __init__(self):
        self.btc_prices = deque(maxlen=60)  # 1 min history
        self.market_stressed = False
        self.stress_start_time = None

    def update_btc_price(self, price):
        self.btc_prices.append({
            'price': price,
            'timestamp': time.time()
        })

    def detect_btc_crash(self, threshold=0.03):
        """Detect BTC drop >3% in 1 minute"""
        if len(self.btc_prices) < 60:
            return False

        oldest = self.btc_prices[0]['price']
        newest = self.btc_prices[-1]['price']

        drop_pct = (oldest - newest) / oldest

        if drop_pct > threshold:
            return True
        return False

    def detect_spread_explosion(self, spreads):
        """Detect >1% spread on any monitored coin"""
        for coin, spread in spreads.items():
            if spread > 0.01:
                return True, coin
        return False, None

    def should_pause_trading(self):
        """Main decision function"""
        # Check 1: BTC crash
        if self.detect_btc_crash():
            self.trigger_stress("BTC crashed >3% in 1 min")
            return True

        # Check 2: Spread explosion
        stressed, coin = self.detect_spread_explosion(self.get_spreads())
        if stressed:
            self.trigger_stress(f"Spread explosion on {coin}")
            return True

        # Check 3: Already in stress - wait for stability
        if self.market_stressed:
            if self.stress_stable_for_minutes(5):
                self.clear_stress()
                return False
            return True

        return False

    def trigger_stress(self, reason):
        self.market_stressed = True
        self.stress_start_time = time.time()
        logger.critical(f"🚨 MARKET STRESS: {reason}")
        # Cancel all orders
        # Alert user

    def stress_stable_for_minutes(self, minutes):
        """Check if market stable for N minutes"""
        if not self.stress_start_time:
            return False

        elapsed = (time.time() - self.stress_start_time) / 60

        # Re-check conditions
        if self.detect_btc_crash():
            self.stress_start_time = time.time()  # Reset timer
            return False

        return elapsed >= minutes
```

**Real-world scenarios:**
```
Scenario A: Flash Crash
18:00:00 - BTC €90,000
18:00:30 - BTC €87,000 (-3.3% in 30s)
         → TRIGGER! Pause all trading
18:01:00 - All altcoins: -5% to -8%
         → Bot is PAUSED, no buys
18:05:00 - BTC stable at €88,000 for 5 min
         → Resume trading

Without market risk protection:
18:00:30 - Bot sees ALT1 -5% → "great dip, buy!"
18:00:45 - ALT1 drops to -10%
18:01:00 - ALT1 drops to -15% → stop-loss trigger
         → Loss realized

Scenario B: Spread Explosion
10:00:00 - Normal spread: 0.1%
10:00:15 - Exchange issues, spread: 2%
         → TRIGGER! Pause trading
         → Bot doesn't buy at bad prices

Scenario C: Market Gap
03:00:00 - All coins stable
03:00:01 - Massive news, all coins +7% instant
         → TRIGGER! Market anomaly
         → Wait 5 min for confirmation
```

**Tests:**
- Normal market: no trigger
- BTC -3% in 60s: trigger
- BTC -5% in 10s: trigger
- Spread 2%: trigger
- Recovery: wait 5 min
- Multiple stress events: reset timer

---

## 🧪 Integration Testing Scenarios

After all 6 features implemented, test combinations:

### Test 1: Stop-Loss + Daily Limit
```
Start: €100
Loss 1: -€2 (€98, -2%)
Loss 2: -€1.50 (€96.50, -3.5%)
→ Both stop-loss AND daily limit trigger
→ Bot must handle both simultaneously
```

### Test 2: Market Crash + Circuit Breaker
```
BTC drops -5% → Market risk triggers
Coin drops -10% in 1 min → Circuit breaker triggers
→ Bot must stay paused, not resume until both clear
```

### Test 3: API Errors During Stop-Loss
```
Coin triggers stop-loss
Try to liquidate → API error
Retry → API error
Retry → API error
→ Circuit breaker AND API error handler both trigger
→ Must handle gracefully, not get stuck
```

### Test 4: Daily Limit Reset Timing
```
23:50 UTC - Trading locked (daily limit hit)
00:01 UTC - New day starts
→ Must auto-unlock
→ Must reset daily P&L counter
```

---

## 📈 Success Criteria

After Phase 1 complete, bot must:

✅ **Survive** all test scenarios without crash
✅ **Protect** capital in 10+ different failure modes
✅ **Recover** gracefully from errors
✅ **Alert** user on all critical events
✅ **Log** all decisions and triggers
✅ **Test coverage** >80% for risk modules

**Score improvement:**
- Before: 4.8/10 (Safety: 4/10)
- After Phase 1: 7.0/10 (Safety: 8/10)

---

## 🚀 Ready to Start?

**Next command:** Start implementing 1.1 - Stop-Loss

Files to create:
1. `src/risk/__init__.py`
2. `src/risk/stop_loss.py`
3. `tests/unit/test_stop_loss.py`

**Zeg "start" om te beginnen!** 💪
