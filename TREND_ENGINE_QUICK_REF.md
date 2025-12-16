# 🎯 Quick Reference: Trend Engine API

## 📦 Import

```python
from multi_coin_grid_pro.utils import (
    TrendCalculator,
    TrendSelection,
    TrendStatus,
    MIN_TREND_THRESHOLD,
    MIN_CANDLES_FOR_WARMUP,
)
```

---

## 🚀 Initialize

```python
calculator = TrendCalculator(
    connector=exchange_connector,
    lookback_minutes=1440,
    bot_start_time=time.time()
)

# Load historical OHLCV data (720 candles)
await calculator.load_historical_data(["BTC-EUR", "ETH-EUR", "XRP-EUR"])
```

---

## ✅ Validate Single Coin

```python
selection = calculator.validate_trend("BTC-EUR")

if selection.passes:
    print(f"✅ {selection.symbol}: {selection.trend_score_pct:+.2f}%")
else:
    print(f"❌ {selection.symbol}: {selection.status.value}")
```

---

## 📊 Get All Selections

```python
selections = calculator.get_all_selections()

# Filter passing coins
passing = [s for s in selections if s.passes]

# Top 3 by trend score
top_3 = sorted(passing, key=lambda x: x.trend_score_pct, reverse=True)[:3]
```

---

## 🖨️ Print Report

```python
calculator.print_selection_report()
```

---

## 📋 TrendSelection Fields

```python
selection.symbol           # "BTC-EUR"
selection.trend_1h         # 1-hour trend %
selection.trend_4h         # 4-hour trend %
selection.trend_24h        # 24-hour trend %
selection.trend_score_pct  # Composite score
selection.passes           # True/False
selection.status           # WARMUP/BEARISH/SIDEWAYS/BULLISH
selection.candle_count     # Number of candles
selection.consensus_pct    # Multi-indicator consensus
selection.volatility       # Current volatility
```

---

## 🎯 Status Enum

```python
TrendStatus.WARMUP    # < 360 candles
TrendStatus.BEARISH   # trend_score < -0.5%
TrendStatus.SIDEWAYS  # -0.5% to +0.5%
TrendStatus.BULLISH   # >= +0.5%
```

---

## ⚙️ Constants

```python
MIN_TREND_THRESHOLD = 0.5      # +0.5% minimum
MIN_CANDLES_FOR_WARMUP = 360   # 30 hours
TARGET_HISTORICAL_CANDLES = 720 # 60 hours
```

---

## 📈 Decision Logic

```
IF candle_count < 360:
    → status = WARMUP, passes = False

ELSE IF trend_score < -0.5%:
    → status = BEARISH, passes = False

ELSE IF trend_score < +0.5%:
    → status = SIDEWAYS, passes = False

ELSE:
    → status = BULLISH, passes = True
```

---

## 🧪 Test Script

```bash
python test_trend_engine.py
```

---

## 📖 Full Documentation

See: `TREND_ENGINE_IMPLEMENTATION.md`
