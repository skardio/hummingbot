# 🚀 Hybrid Grid Bot v2.0 - Complete Implementation Guide

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Components](#components)
4. [Configuration](#configuration)
5. [Integration Guide](#integration-guide)
6. [Testing](#testing)
7. [Deployment](#deployment)
8. [Monitoring](#monitoring)

---

## 🎯 Overview

**Hybrid Grid Bot v2.0** is a professional cryptocurrency trading bot that combines:

- **SmartEntry Filter v2**: ML-lite entry filter with coin-specific profiles
- **DynamicGridSizer v2**: ATR-based adaptive grid sizing (3-7 levels)
- **Real-time P&L Tracker**: Daily/weekly/monthly profit tracking
- **RiskGuard v2**: Multi-layer kill switch protection
- **Telegram Alerts**: Real-time critical notifications
- **Dynamic Discovery**: Automatic coin selection by volume/spread

### Key Features

✅ **Adaptive Grid Sizing** - ATR-based dynamic grids (3-7 levels)
✅ **Coin Profiles** - Per-coin parameter overrides (e.g., ATOM: `min_wick_ratio=0.20`)
✅ **Multi-Timeframe Analysis** - 5m/1h/4h/24h trend analysis
✅ **Kill Switch Protection** - Daily/weekly/monthly loss limits
✅ **Real-time P&L** - Realized + unrealized P&L tracking
✅ **Telegram Integration** - Critical alerts via Telegram bot
✅ **Historical Data Loading** - Load 25+ hours of data at startup
✅ **Paper Trading Ready** - Test safely with zero risk

---

## 🏗️ Architecture

### Directory Structure

```
multi_coin_grid_pro/
├── core/
│   ├── models.py              # Data models (Candle, Position, TradeFill)
│   └── config_loader.py       # YAML config loader
├── logic/
│   ├── smart_entry.py         # SmartEntry v2.0 filter
│   ├── grid_sizer.py          # Dynamic ATR-based grid sizing
│   ├── grid_builder.py        # Grid construction logic
│   └── coin_selector.py       # Dynamic pair discovery
├── risk/
│   ├── pnl_tracker.py         # Real-time P&L tracking
│   └── risk_guard.py          # Kill switch & risk limits
├── alerts/
│   └── telegram_alerter.py    # Telegram notifications
├── config/
│   └── config.prod.yaml       # Production configuration
└── controllers/
    └── multi_coin_grid_controller.py  # Main controller (existing)
```

### Component Flow

```
┌─────────────────┐
│  Config Loader  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  Coin Selector  │────▶│  Historical Data │
│  (Discovery)    │     │  Loader (Kraken) │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  SmartEntry v2  │────▶│  Grid Sizer v2   │
│  (Entry Filter) │     │  (ATR → grids)   │
└────────┬────────┘     └─────────┬────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐     ┌──────────────────┐
│  Grid Builder   │────▶│  Order Placement │
│  (Build Levels) │     │  (Kraken API)    │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  PnL Tracker    │◀────│  Trade Fills     │
│  (Real-time)    │     │  (Executed)      │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  Risk Guard v2  │────▶│  Kill Switch     │
│  (Loss Limits)  │     │  (Stop Trading)  │
└────────┬────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐
│  Telegram Alert │
│  (Notifications)│
└─────────────────┘
```

---

## 🧩 Components

### 1. SmartEntry Filter v2.0

**Purpose**: Intelligent entry filtering to avoid bad market conditions

**Location**: `logic/smart_entry.py`

**Features**:
- RSI regime detection (25-60 safe zone, block <25 or >70)
- VWAP mean reversion (max 3% deviation)
- Candle structure quality (wick ratio ≥0.45)
- ATR volatility regime (0.5-6.0% ATR)
- 5m spike detection (block >2.5% moves)
- Trend acceleration detection (1h vs 4h)
- 24h trend sanity checks (-12% to +8%)
- **Coin profiles**: Per-coin parameter overrides

**Example**:
```python
from logic.smart_entry import SmartEntryFilter, SmartEntryBaseConfig
from core.models import CandleIndicators

# Base config
base_cfg = SmartEntryBaseConfig(
    rsi_buy_max=60.0,
    min_wick_ratio=0.45,
    max_atr_pct_for_grid=6.0,
    # ... other params
)

# Coin-specific overrides
coin_profiles = {
    "ATOM-EUR": {"min_wick_ratio": 0.20},  # More lenient for ATOM
    "SOL-EUR": {"max_atr_pct_for_grid": 5.0}  # Stricter for SOL
}

filter = SmartEntryFilter(base_cfg, coin_profiles, logger)

# Check if entry is allowed
indicators = CandleIndicators(price=..., rsi_14=50.0, ...)
allowed, reason = filter.allows_entry("ATOM-EUR", indicators)

if allowed:
    # Place orders
else:
    logger.info(reason)  # "🧠 ATOM-EUR: NO BUY – wick_ratio 0.35 < 0.45"
```

### 2. Dynamic Grid Sizer v2.0

**Purpose**: Automatically determine optimal grid count based on ATR volatility

**Location**: `logic/grid_sizer.py`

**Logic**:
- **Low vol** (<0.7% ATR): 3 grids (tight market)
- **Medium vol** (0.7-2.0%): 4-5 grids (normal)
- **High vol** (2.0-4.0%): 7 grids (choppy - ideal for mean reversion)
- **Very high** (>4.0%): 5 grids (risk reduction)

**Example**:
```python
from logic.grid_sizer import DynamicGridSizer

cfg = {
    "min_grids": 3,
    "max_grids": 7,
    "low_vol_atr_pct": 0.7,
    "mid_vol_atr_pct": 2.0,
    "high_vol_atr_pct": 4.0,
}

sizer = DynamicGridSizer(cfg, logger)

# Calculate grid count
atr_pct = 2.5  # 2.5% ATR
num_grids = sizer.grid_count_for(atr_pct)  # Returns 7 (high volatility)
```

### 3. PnL Tracker v2.0

**Purpose**: Real-time profit/loss tracking with daily/weekly/monthly aggregation

**Location**: `risk/pnl_tracker.py`

**Features**:
- Realized P&L (from closed trades)
- Unrealized P&L (from open positions)
- Total fees paid
- Daily/weekly/monthly P&L percentage
- Equity curve tracking

**Example**:
```python
from risk.pnl_tracker import RealtimePnLTracker
from core.models import TradeFill
from decimal import Decimal

tracker = RealtimePnLTracker(starting_balance=Decimal("1000"))

# Process trade
fill = TradeFill(
    symbol="BTC-EUR",
    side="buy",
    price=Decimal("50000"),
    size=Decimal("0.01"),
    fee=Decimal("1.0"),
    ts=1234567890
)
tracker.on_trade_fill(fill)

# Update unrealized P&L
tracker.update_unrealized({"BTC-EUR": Decimal("52000")})

# Get summary
summary = tracker.get_summary()
print(f"Equity: €{summary['equity']:.2f}")
print(f"Daily P&L: {summary['daily_pnl_pct']:+.2f}%")
```

### 4. Risk Guard v2.0

**Purpose**: Multi-layer kill switch protection

**Location**: `risk/risk_guard.py`

**Features**:
- Daily loss limit (3% default)
- Weekly loss limit (8% default)
- Monthly loss limit (12% default)
- Absolute EUR loss limit
- Position size limits
- Total exposure limits
- Automatic trading disabling

**Example**:
```python
from risk.risk_guard import RiskGuardV2

cfg = {
    "max_daily_loss_pct": 3.0,
    "max_weekly_loss_pct": 8.0,
    "max_monthly_loss_pct": 12.0,
    "max_daily_loss_eur": 50.0,
    "max_exposure_per_coin_pct": 40,
    "max_total_exposure_pct": 80,
}

guard = RiskGuardV2(cfg, pnl_tracker, telegram_alerter, logger)

# Check before trading
if guard.check_limits():
    # Safe to trade
    pass
else:
    # Kill switch activated - stop all trading
    logger.critical(f"Kill switch: {guard.kill_reason}")
```

### 5. Telegram Alerter

**Purpose**: Send critical notifications via Telegram

**Location**: `alerts/telegram_alerter.py`

**Setup**:
1. Create bot with @BotFather on Telegram
2. Get bot token (format: `123456:ABC-DEF...`)
3. Send message to bot
4. Get chat_id from `https://api.telegram.org/bot<TOKEN>/getUpdates`

**Example**:
```python
from alerts.telegram_alerter import TelegramAlerter

alerter = TelegramAlerter(
    bot_token="123456:ABC-DEF...",
    chat_id="123456789"
)

alerter.critical("Kill switch activated!")
alerter.trade("BUY 0.01 BTC-EUR @ €50,000")
alerter.pnl_update(equity=1050.0, daily_pct=+5.0, realized=40.0, unrealized=10.0)
```

### 6. Coin Selector

**Purpose**: Dynamic coin discovery and filtering

**Location**: `logic/coin_selector.py`

**Features**:
- Volume filtering (min €300k default)
- Spread filtering (max 0.5% default)
- Blacklist support
- Fallback to core_universe
- Manual mode support

---

## ⚙️ Configuration

### config.prod.yaml Structure

```yaml
# ==============================================================================
# HYBRID GRID BOT V2.0 - PRODUCTION CONFIG
# ==============================================================================

log_level: INFO
connector_name: kraken
quote_asset: EUR
paper_trading: false

# Dynamic Discovery
use_dynamic_pair_discovery: true
max_coins_to_monitor: 25
min_24h_volume_eur: 300000

# SmartEntry Filter (base config)
use_smart_entry_filter: true
smart_entry_filter:
  rsi_buy_max: 60.0
  rsi_extreme_low: 25.0
  rsi_block_min: 70.0
  vwap_max_deviation_pct: 3.0
  min_wick_ratio: 0.30
  max_atr_pct_for_grid: 6.0
  min_atr_pct_for_grid: 0.5
  max_5m_spike_pct: 2.5
  max_down_accel_pct: -1.0
  max_up_accel_pct: 1.5
  max_trend_24h_pct: 8.0
  min_trend_24h_pct: -12.0

# Coin Profiles (per-coin overrides)
coin_profiles:
  ATOM-EUR:
    min_wick_ratio: 0.20
    max_atr_pct_for_grid: 6
  SOL-EUR:
    min_wick_ratio: 0.45
    max_atr_pct_for_grid: 5

# Dynamic Grid Sizer
use_dynamic_grid_sizer: true
dynamic_grid_sizer:
  min_grids: 3
  max_grids: 7
  low_vol_atr_pct: 0.7
  mid_vol_atr_pct: 2.0
  high_vol_atr_pct: 4.0

# Grid Configuration
use_atr_grid_ranges: true
atr_multiplier_down: 1.5
atr_multiplier_up: 2.0
use_asymmetric_grids: true

# Capital & Risk
total_amount_quote: 80
min_order_amount_quote: 10
risk_reference_balance_quote: 100
max_exposure_per_coin_pct: 25
max_total_exposure_pct: 60

# Kill Switch Limits
max_daily_loss_pct: 3.0
max_weekly_loss_pct: 8.0
max_monthly_loss_pct: 12.0
max_daily_loss_eur: 30.0

# Blacklist
blacklist:
  - USDT-EUR
  - MON-EUR
  - FARTCOIN-EUR

# Optional: Telegram (remove if not using)
# telegram:
#   bot_token: "123456:ABC-DEF..."
#   chat_id: "123456789"
```

---

## 🔧 Integration Guide

### Step 1: Update Existing Controller

Your existing controller at `controllers/multi_coin_grid_controller.py` needs to integrate the new components.

**Add imports**:
```python
from multi_coin_grid_pro.core.config_loader import load_config
from multi_coin_grid_pro.logic.smart_entry import SmartEntryFilter, SmartEntryBaseConfig
from multi_coin_grid_pro.logic.grid_sizer import DynamicGridSizer
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2
from multi_coin_grid_pro.alerts.telegram_alerter import TelegramAlerter
```

**In `__init__` method**:
```python
def __init__(self, config: MultiCoinGridConfig, ...):
    # ... existing code ...

    # Initialize Telegram
    telegram_cfg = getattr(config, 'telegram', {})
    self.telegram = TelegramAlerter(
        bot_token=telegram_cfg.get('bot_token', ''),
        chat_id=telegram_cfg.get('chat_id', ''),
        logger=self.logger()
    )

    # Initialize P&L tracker
    self.pnl_tracker = RealtimePnLTracker(
        starting_balance=Decimal(str(config.risk_reference_balance_quote)),
        logger=self.logger()
    )

    # Initialize Risk Guard
    self.risk_guard = RiskGuardV2(
        cfg={
            'max_daily_loss_pct': config.max_daily_loss_pct,
            'max_weekly_loss_pct': config.max_weekly_loss_pct,
            'max_monthly_loss_pct': config.max_monthly_loss_pct,
            'max_daily_loss_eur': config.max_daily_loss_eur,
            'max_exposure_per_coin_pct': config.max_exposure_per_coin_pct,
            'max_total_exposure_pct': config.max_total_exposure_pct,
        },
        pnl_tracker=self.pnl_tracker,
        alerter=self.telegram,
        logger=self.logger()
    )

    # Initialize SmartEntry filter
    base_cfg = SmartEntryBaseConfig(**config.smart_entry_filter)
    coin_profiles = getattr(config, 'coin_profiles', {})
    self.smart_entry = SmartEntryFilter(base_cfg, coin_profiles, self.logger())

    # Initialize Grid Sizer
    self.grid_sizer = DynamicGridSizer(config.dynamic_grid_sizer, self.logger())
```

**In main trading loop** (replace existing SmartEntry logic):
```python
async def control_loop_body(self):
    # Check risk limits first
    if not self.risk_guard.check_limits():
        self.logger().critical("Trading disabled by kill switch")
        return

    # ... existing coin selection ...

    for symbol in active_coins:
        # Get indicators (from your existing trend calculator)
        indicators = self._get_indicators(symbol)

        # Check SmartEntry v2
        allowed, reason = self.smart_entry.allows_entry(symbol, indicators)
        self.logger().info(reason)

        if not allowed:
            continue

        # Check position size limits
        position_size_eur = self._calculate_position_size(symbol)
        allowed, reason = self.risk_guard.can_open_position(symbol, position_size_eur)
        if not allowed:
            self.logger().warning(f"Position rejected: {reason}")
            continue

        # Determine grid size
        atr_pct = indicators.atr_pct
        num_grids = self.grid_sizer.grid_count_for(atr_pct)

        # Build and place grid (use existing grid logic)
        await self._build_and_place_grid(symbol, num_grids, indicators)
```

---

## 🧪 Testing

### Run Unit Tests

```bash
cd /home/mo/repos/hummingbot

# Run all v2 tests
python -m pytest test/multi_coin_grid_pro_v2/ -v

# Run specific test file
python -m pytest test/multi_coin_grid_pro_v2/test_smart_entry.py -v

# Run with coverage
python -m pytest test/multi_coin_grid_pro_v2/ --cov=multi_coin_grid_pro --cov-report=html
```

### Test Coverage

Current test files:
- `test_smart_entry.py`: 12 tests for SmartEntry v2.0
- `test_grid_sizer.py`: 6 tests for DynamicGridSizer
- `test_pnl_and_risk.py`: 8 tests for PnL tracker and RiskGuard

---

## 🚀 Deployment

### Production Checklist

- [ ] Config validated (`config.prod.yaml` correct)
- [ ] Paper trading tested (`paper_trading: true`)
- [ ] All unit tests passing
- [ ] Historical data loading working (705+ points)
- [ ] SmartEntry profiles tuned for your coins
- [ ] Risk limits configured (3% daily, 8% weekly, 12% monthly)
- [ ] Telegram bot configured (optional)
- [ ] Blacklist updated with problem pairs
- [ ] Capital allocation set (`total_amount_quote`)
- [ ] Kill switch limits verified

### Start Bot

```bash
cd /home/mo/repos/hummingbot
python3 bin/hummingbot_quickstart.py --script multi_coin_grid_pro --conf conf/conf_arb_TEMPLATE.yml
```

---

## 📊 Monitoring

### Key Metrics to Watch

1. **Historical Data Loading**: Should see "📥 LOADING HISTORICAL DATA FROM KRAKEN..." at startup
2. **Data Points**: Each coin should have 705+ points (58+ hours)
3. **SmartEntry Rejections**: Check `"🧠 ... NO BUY"` messages - tune profiles if too strict
4. **Grid Sizes**: Should see 3-7 grids based on ATR
5. **P&L Tracking**: Monitor daily/weekly/monthly P&L percentages
6. **Kill Switch**: Watch for risk limit warnings

### Log Examples

**Good startup**:
```
📥 LOADING HISTORICAL DATA FROM KRAKEN...
✅ Historical data loaded - ready for accurate 24h trends!
  🔍 DEBUG SUI-EUR: 705 points, first=€1.2340, last=€1.2580, Δ+1.94%
  🔍 DEBUG LINK-EUR: 705 points, first=€14.2300, last=€14.1200, Δ-0.77%
```

**SmartEntry working**:
```
✅ ATOM-EUR: BUY ALLOWED – SmartEntry v2.0 passed (RSI=52.3, ATR=2.15%, wick=0.38)
🧠 SOL-EUR: NO BUY – ATR 8.23% > 5.0% (too chaotic)
```

**Grid sizing**:
```
📊 DynamicGridSizer: atr=2.5% → 7 grids (high volatility - choppy - ideal)
```

**Risk monitoring**:
```
💰 P&L Update: Equity=€1,045.20 | Daily: +4.52% | Realized: +€38.50 | Unrealized: +€6.70
```

---

## 📝 Summary

### What's New in v2.0

✅ **SmartEntry v2.0** with coin profiles
✅ **DynamicGridSizer** (ATR-based 3-7 grids)
✅ **Real-time P&L tracking**
✅ **Multi-layer kill switch** (daily/weekly/monthly)
✅ **Telegram integration**
✅ **Complete unit test coverage**
✅ **Professional architecture** (modular, testable, maintainable)

### Next Steps

1. **Review config.prod.yaml** - Tune parameters for your strategy
2. **Test in paper mode** - Verify all components work
3. **Monitor 24h** - Watch SmartEntry rejections, tune profiles
4. **Go live** - Set `paper_trading: false` when ready
5. **Scale up** - Increase capital as confidence grows

---

## 🆘 Troubleshooting

### SmartEntry too strict?

Lower thresholds in coin profiles:
```yaml
coin_profiles:
  ATOM-EUR:
    min_wick_ratio: 0.15  # Was 0.20
    max_atr_pct_for_grid: 7  # Was 6
```

### Too many grids?

Adjust DynamicGridSizer:
```yaml
dynamic_grid_sizer:
  max_grids: 5  # Was 7
```

### Historical data not loading?

Check logs for "📥 LOADING HISTORICAL DATA" - if missing, verify:
- Kraken API connectivity
- CCXT library installed (`pip install ccxt`)
- Pairs exist on Kraken (FTM-EUR, MATIC-EUR don't exist!)

---

**Built with ❤️ for professional crypto trading**
