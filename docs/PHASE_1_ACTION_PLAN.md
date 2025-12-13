# 🎯 Phase 1 Action Plan - Critical Fixes for €1000

**Timeline:** 2-3 weeks
**Goal:** Bring bot from 6.5/10 → 8.5/10
**Capital Target:** €500-€1000

---

## ✅ **Completed Today**
1. ✅ Fixed `trend_min_entry_strength` in `config.prod.yaml` (was missing, now 0.10)

---

## 🔴 **Critical Fixes (Week 1-2)**

### **Fix #1: Slippage Protection**
**Priority:** 🔴 CRITICAL
**Time:** 1 day
**Risk:** Can lose 0.5-2% per trade from wide spreads

**Implementation:**
```python
# File: multi_coin_grid_controller.py
# Add to _should_create_new_grid() method

def _check_spread_acceptable(self, symbol: str, max_spread_pct: float = 0.5) -> bool:
    """
    Check if bid-ask spread is acceptable before entry
    Returns False if spread too wide (illiquid market)
    """
    try:
        order_book = self.connector.get_order_book(symbol)
        if not order_book or not order_book.snapshot:
            self.logger().warning(f"⚠️  No order book for {symbol}")
            return False

        bid = order_book.snapshot[0][0]  # Best bid
        ask = order_book.snapshot[1][0]  # Best ask
        mid = (bid + ask) / 2

        spread_pct = abs(ask - bid) / mid * 100

        if spread_pct > max_spread_pct:
            self.logger().warning(
                f"🚫 Rejecting {symbol}: Spread too wide ({spread_pct:.2f}% > {max_spread_pct}%)"
            )
            return False

        self.logger().info(f"✅ {symbol} spread OK: {spread_pct:.3f}%")
        return True

    except Exception as e:
        self.logger().error(f"Error checking spread for {symbol}: {e}")
        return False  # Reject on error (conservative)

# Add to config
max_entry_spread_pct: 0.5  # Reject if spread >0.5%
```

**Config Addition:**
```yaml
# config.prod.yaml
max_entry_spread_pct: 0.5  # Maximum acceptable bid-ask spread
```

---

### **Fix #2: Daily Drawdown Limit**
**Priority:** 🔴 CRITICAL
**Time:** 2 days
**Risk:** Can lose €50+ per day without limit

**Implementation:**
```python
# File: multi_coin_grid_controller.py

class DrawdownTracker:
    """Track daily/weekly/monthly drawdown"""

    def __init__(self, config):
        self.max_daily_loss_pct = config.max_daily_loss_pct  # 5%
        self.max_weekly_loss_pct = config.max_weekly_loss_pct  # 10%
        self.max_monthly_loss_pct = config.max_monthly_loss_pct  # 15%

        self.daily_start_balance = self._get_current_balance()
        self.weekly_start_balance = self.daily_start_balance
        self.monthly_start_balance = self.daily_start_balance

        self.last_reset_day = datetime.now().date()
        self.last_reset_week = datetime.now().isocalendar()[1]
        self.last_reset_month = datetime.now().month

    def check_drawdown_limits(self) -> tuple[bool, str]:
        """
        Returns: (is_allowed, reason)
        """
        # Reset counters if new day/week/month
        self._reset_if_needed()

        current_balance = self._get_current_balance()

        # Check daily limit
        daily_pnl_pct = (current_balance - self.daily_start_balance) / self.daily_start_balance * 100
        if daily_pnl_pct < -self.max_daily_loss_pct:
            return False, f"Daily drawdown limit exceeded: {daily_pnl_pct:.2f}% < -{self.max_daily_loss_pct}%"

        # Check weekly limit
        weekly_pnl_pct = (current_balance - self.weekly_start_balance) / self.weekly_start_balance * 100
        if weekly_pnl_pct < -self.max_weekly_loss_pct:
            return False, f"Weekly drawdown limit exceeded: {weekly_pnl_pct:.2f}% < -{self.max_weekly_loss_pct}%"

        # Check monthly limit
        monthly_pnl_pct = (current_balance - self.monthly_start_balance) / self.monthly_start_balance * 100
        if monthly_pnl_pct < -self.max_monthly_loss_pct:
            return False, f"Monthly drawdown limit exceeded: {monthly_pnl_pct:.2f}% < -{self.max_monthly_loss_pct}%"

        return True, "OK"

    def _reset_if_needed(self):
        """Reset balance counters at new day/week/month"""
        now = datetime.now()

        # New day?
        if now.date() > self.last_reset_day:
            self.daily_start_balance = self._get_current_balance()
            self.last_reset_day = now.date()
            self.logger().info(f"📅 New day - Daily balance reset to €{self.daily_start_balance:.2f}")

        # New week?
        if now.isocalendar()[1] > self.last_reset_week:
            self.weekly_start_balance = self._get_current_balance()
            self.last_reset_week = now.isocalendar()[1]
            self.logger().info(f"📅 New week - Weekly balance reset to €{self.weekly_start_balance:.2f}")

        # New month?
        if now.month > self.last_reset_month:
            self.monthly_start_balance = self._get_current_balance()
            self.last_reset_month = now.month
            self.logger().info(f"📅 New month - Monthly balance reset to €{self.monthly_start_balance:.2f}")

    def _get_current_balance(self) -> Decimal:
        """Get current EUR balance"""
        return self.connector.get_balance(self.config.quote_asset)

# Add to MultiCoinGridController.__init__
self.drawdown_tracker = DrawdownTracker(config)

# Add to determine_executor_actions()
allowed, reason = self.drawdown_tracker.check_drawdown_limits()
if not allowed:
    self.logger().error(f"🛑 TRADING PAUSED: {reason}")
    return []  # No new trades
```

**Config Addition:**
```yaml
# config.prod.yaml
max_daily_loss_pct: 5.0    # Max -5% loss per day
max_weekly_loss_pct: 10.0  # Max -10% loss per week
max_monthly_loss_pct: 15.0 # Max -15% loss per month
```

---

### **Fix #3: Max Daily Loss (Euro Amount)**
**Priority:** 🔴 CRITICAL
**Time:** 1 day
**Risk:** Percentage limits may allow large euro losses

**Implementation:**
```python
# Simpler alternative to #2 (or use BOTH)

class DailyLossTracker:
    """Track euro loss per day"""

    def __init__(self, max_daily_loss_eur: Decimal):
        self.max_daily_loss_eur = max_daily_loss_eur
        self.daily_trades_pnl: List[Decimal] = []
        self.last_reset_date = datetime.now().date()

    def record_trade_pnl(self, pnl_eur: Decimal):
        """Record P&L from completed trade"""
        self._reset_if_new_day()
        self.daily_trades_pnl.append(pnl_eur)

    def check_limit(self) -> tuple[bool, str]:
        """Check if daily loss limit exceeded"""
        self._reset_if_new_day()

        total_daily_pnl = sum(self.daily_trades_pnl)

        if total_daily_pnl < -self.max_daily_loss_eur:
            return False, f"Daily loss limit exceeded: €{total_daily_pnl:.2f} < -€{self.max_daily_loss_eur:.2f}"

        return True, "OK"

    def _reset_if_new_day(self):
        """Reset at midnight"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_trades_pnl = []
            self.last_reset_date = today
            self.logger().info("📅 New day - Daily loss counter reset")

# Usage
self.daily_loss_tracker = DailyLossTracker(max_daily_loss_eur=Decimal("50"))  # €50 max loss per day

# When trade closes
self.daily_loss_tracker.record_trade_pnl(realized_pnl)

# Before creating new executor
allowed, reason = self.daily_loss_tracker.check_limit()
if not allowed:
    self.logger().error(f"🛑 {reason}")
    return []
```

**Config Addition:**
```yaml
# config.prod.yaml
max_daily_loss_eur: 50  # Max €50 loss per day (5% of €1000)
```

---

### **Fix #4: Volatility-Based Position Sizing**
**Priority:** 🟡 HIGH
**Time:** 1 day
**Impact:** Better risk-adjusted returns

**Implementation:**
```python
def _calculate_position_size(self, symbol: str, base_size: Decimal) -> Decimal:
    """
    Adjust position size based on volatility (ATR)

    Args:
        symbol: Trading pair (e.g., "XRP-EUR")
        base_size: Base position size from config (e.g., €30)

    Returns:
        Adjusted position size based on volatility
    """
    try:
        atr = self._calculate_atr(symbol, periods=14)
        current_price = self.connector.get_mid_price(symbol)

        if not atr or not current_price:
            self.logger().warning(f"⚠️  No ATR/price for {symbol}, using base size")
            return base_size

        # Calculate volatility percentage
        volatility_pct = float(atr / current_price * 100)

        # Adjust size based on volatility
        if volatility_pct > 5.0:  # Very high volatility
            multiplier = Decimal("0.67")  # 67% of base (€30 → €20)
            self.logger().info(f"📉 {symbol}: High volatility ({volatility_pct:.1f}%) → reduced size")
        elif volatility_pct > 3.0:  # Medium-high volatility
            multiplier = Decimal("0.83")  # 83% of base (€30 → €25)
            self.logger().info(f"⚖️  {symbol}: Medium volatility ({volatility_pct:.1f}%) → normal size")
        elif volatility_pct < 1.5:  # Very low volatility
            multiplier = Decimal("1.33")  # 133% of base (€30 → €40)
            self.logger().info(f"📈 {symbol}: Low volatility ({volatility_pct:.1f}%) → increased size")
        else:  # Normal volatility
            multiplier = Decimal("1.0")  # 100% of base

        adjusted_size = base_size * multiplier

        # Ensure within reasonable bounds
        min_size = base_size * Decimal("0.5")  # Min 50% of base
        max_size = base_size * Decimal("1.5")  # Max 150% of base

        final_size = max(min_size, min(adjusted_size, max_size))

        self.logger().info(
            f"💰 {symbol} position size: €{base_size} → €{final_size:.2f} "
            f"(volatility: {volatility_pct:.1f}%, multiplier: {multiplier})"
        )

        return final_size

    except Exception as e:
        self.logger().error(f"Error calculating position size for {symbol}: {e}")
        return base_size  # Fallback to base size

# Usage in _create_grid_action()
base_size = Decimal(str(self.config.total_amount_quote))
adjusted_size = self._calculate_position_size(best_coin, base_size)

grid_config = GridExecutorConfig(
    # ...
    total_amount_quote=adjusted_size,  # Use adjusted size instead of base
    # ...
)
```

---

### **Fix #5: Real-time P&L Tracker**
**Priority:** 🟡 HIGH
**Time:** 2 days
**Impact:** Better visibility and risk management

**Implementation:**
```python
class PortfolioPnLTracker:
    """Track real portfolio P&L across all trades"""

    def __init__(self):
        self.trades: List[Dict] = []  # All completed trades
        self.active_positions: Dict[str, Dict] = {}  # {symbol: {entry_price, size, ...}}

        self.realized_pnl_total = Decimal("0")
        self.unrealized_pnl_total = Decimal("0")

        self.fees_paid_total = Decimal("0")
        self.switch_costs_total = Decimal("0")

    def record_entry(self, symbol: str, entry_price: Decimal, size: Decimal, fee: Decimal):
        """Record new position entry"""
        self.active_positions[symbol] = {
            'entry_price': entry_price,
            'size': size,
            'entry_fee': fee,
            'entry_time': datetime.now()
        }
        self.fees_paid_total += fee

    def record_exit(self, symbol: str, exit_price: Decimal, exit_fee: Decimal, reason: str):
        """Record position exit and calculate P&L"""
        if symbol not in self.active_positions:
            self.logger().error(f"Cannot exit {symbol} - no active position!")
            return

        pos = self.active_positions[symbol]

        # Calculate P&L
        entry_value = pos['entry_price'] * pos['size']
        exit_value = exit_price * pos['size']
        price_pnl = exit_value - entry_value

        total_fees = pos['entry_fee'] + exit_fee
        net_pnl = price_pnl - total_fees

        # Record trade
        trade = {
            'symbol': symbol,
            'entry_time': pos['entry_time'],
            'exit_time': datetime.now(),
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'size': pos['size'],
            'price_pnl': price_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'exit_reason': reason,
            'hold_duration': (datetime.now() - pos['entry_time']).total_seconds()
        }

        self.trades.append(trade)
        self.realized_pnl_total += net_pnl
        self.fees_paid_total += exit_fee

        # Remove from active positions
        del self.active_positions[symbol]

        self.logger().info(
            f"💼 Trade closed: {symbol} | "
            f"P&L: €{net_pnl:.2f} | "
            f"Entry: €{pos['entry_price']:.4f} → Exit: €{exit_price:.4f} | "
            f"Fees: €{total_fees:.2f} | "
            f"Reason: {reason}"
        )

    def get_unrealized_pnl(self, connector) -> Decimal:
        """Calculate current unrealized P&L"""
        total = Decimal("0")

        for symbol, pos in self.active_positions.items():
            current_price = connector.get_mid_price(symbol)
            if not current_price:
                continue

            entry_value = pos['entry_price'] * pos['size']
            current_value = current_price * pos['size']
            unrealized = current_value - entry_value

            total += unrealized

        self.unrealized_pnl_total = total
        return total

    def get_summary(self) -> Dict:
        """Get portfolio summary"""
        win_trades = [t for t in self.trades if t['net_pnl'] > 0]
        loss_trades = [t for t in self.trades if t['net_pnl'] < 0]

        return {
            'total_trades': len(self.trades),
            'win_trades': len(win_trades),
            'loss_trades': len(loss_trades),
            'win_rate': len(win_trades) / len(self.trades) * 100 if self.trades else 0,
            'realized_pnl': float(self.realized_pnl_total),
            'unrealized_pnl': float(self.unrealized_pnl_total),
            'total_pnl': float(self.realized_pnl_total + self.unrealized_pnl_total),
            'fees_paid': float(self.fees_paid_total),
            'avg_profit_per_trade': float(self.realized_pnl_total / len(self.trades)) if self.trades else 0,
            'active_positions': len(self.active_positions)
        }

    def log_summary(self):
        """Log portfolio summary"""
        summary = self.get_summary()

        self.logger().info("=" * 70)
        self.logger().info("📊 PORTFOLIO SUMMARY")
        self.logger().info("=" * 70)
        self.logger().info(f"Total Trades: {summary['total_trades']}")
        self.logger().info(f"Win Rate: {summary['win_rate']:.1f}% ({summary['win_trades']}W / {summary['loss_trades']}L)")
        self.logger().info(f"Realized P&L: €{summary['realized_pnl']:.2f}")
        self.logger().info(f"Unrealized P&L: €{summary['unrealized_pnl']:.2f}")
        self.logger().info(f"Total P&L: €{summary['total_pnl']:.2f}")
        self.logger().info(f"Fees Paid: €{summary['fees_paid']:.2f}")
        self.logger().info(f"Avg P&L per Trade: €{summary['avg_profit_per_trade']:.2f}")
        self.logger().info(f"Active Positions: {summary['active_positions']}")
        self.logger().info("=" * 70)

# Add to controller
self.pnl_tracker = PortfolioPnLTracker()

# Log summary every hour
if time.time() - self.last_summary_log > 3600:
    self.pnl_tracker.log_summary()
    self.last_summary_log = time.time()
```

---

## 📊 **Success Metrics**

After completing Phase 1, you should have:

✅ **Safety Features:**
- Slippage protection (reject if spread >0.5%)
- Daily loss limit (max -5% or €50/day)
- Weekly loss limit (max -10%)
- Monthly loss limit (max -15%)

✅ **Better Risk Management:**
- Volatility-adjusted position sizing
- Real-time P&L tracking
- Better visibility into performance

✅ **Bot Grade:** 6.5/10 → **8.0/10** ✅

✅ **Ready for:** €500-€1000 testing

---

## 🎯 **Testing Plan After Phase 1**

### **Step 1: €100 Test (1 week)**
- All Phase 1 fixes active
- Monitor daily loss limits
- Check spread rejections
- Verify P&L tracking

### **Step 2: €300 Test (1 week)**
- Increase capital if €100 test successful
- Monitor position sizing adjustments
- Check drawdown limits

### **Step 3: €500-€1000 Test (2+ weeks)**
- Full capital deployment
- All systems monitored
- Ready for production

---

## 📝 **Implementation Order**

**Day 1-2:** Slippage Protection (#1)
**Day 3-5:** Drawdown Limits (#2, #3)
**Day 6:** Position Sizing (#4)
**Day 7-9:** P&L Tracker (#5)
**Day 10:** Testing & Documentation

**Total:** ~10 working days (2 weeks)

---

## ⚠️ **Important Notes**

1. **Test Each Fix Separately**
   - Don't implement all at once
   - Test each fix with €50 first
   - Verify it works before next fix

2. **Keep Logs Detailed**
   - Log every rejection reason
   - Log every limit trigger
   - Use for debugging

3. **Monitor First Week Closely**
   - Watch for false positives
   - Tune thresholds if needed
   - Adjust based on real data

---

**Next:** Start with Fix #1 (Slippage Protection) tomorrow! 🚀
