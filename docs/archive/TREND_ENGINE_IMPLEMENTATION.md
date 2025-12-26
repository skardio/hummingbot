# 🎯 Multi-Indicator, Multi-Timeframe Trend Engine - Implementation Complete

## 📋 Overview

De trend engine is nu **volledig geïmplementeerd** volgens de specificatie. Dit document beschrijft wat er is gebouwd en hoe het te gebruiken.

---

## ✅ Wat Is Geïmplementeerd

### 1️⃣ **Data Input & Historische Warm-up** ✅

**OHLCV Candle Loading:**
```python
# Load 30 hours of 5-minute OHLCV candles (720 candles)
await trend_calculator.load_historical_data(symbols)

# Result: Full OHLCV history per coin
# - timestamp, open, high, low, close, volume
# - Stored in CandleData objects
# - Max 720 candles = 60 hours coverage
```

**Warm-up Validation:**
```python
MIN_CANDLES_FOR_WARMUP = 360  # 30 hours × 60min / 5min

if coin.candle_count < MIN_CANDLES_FOR_WARMUP:
    status = TrendStatus.WARMUP
    passes = False
```

**Features:**
- ✅ Fetches 720 × 5m candles (60 hours)
- ✅ Uses ccxt/Kraken for historical data
- ✅ Stores full OHLCV (not just close price)
- ✅ Validates minimum 360 candles before trends are valid

---

### 2️⃣ **Real-Time Price Updates** ✅

**Update Mechanism:**
```python
# Updates elke ~30 seconden via update_coin_trend()
trend.price_history.append({
    "price": current_price,
    "timestamp": now,
    "high": max(current_price, prev_price),
    "low": min(current_price, prev_price)
})

# Data retentie: 65 uur
cutoff = now - lookback_seconds
price_history = [p for p in price_history if p["timestamp"] > cutoff]
```

**Features:**
- ✅ Real-time price tracking
- ✅ High/Low per tick
- ✅ 65-hour rolling window
- ✅ OHLCV candles bijwerken (5m intervals)

---

### 3️⃣ **Indicatoren (4 Indicators per Timeframe)** ✅

#### **Indicator 1: Raw Trend (5%)** ✅
```python
raw_trend_pct = ((last_price - first_price) / first_price) * 100
```

#### **Indicator 2: Volatility-Normalized Trend (15%)** ✅
```python
volatility = stdev(pct_changes)
normalized_trend = raw_trend_pct / volatility if volatility > 0 else raw_trend_pct
```

#### **Indicator 3: EMA Distance Trend (40%)** ✅
```python
ema30 = calculate_ema(prices, 30)
ema60 = calculate_ema(prices, 60)
ema_trend_pct = ((ema30 - ema60) / ema60) * 100
```

#### **Indicator 4: Linear Regression Trend (40%)** ✅
```python
# Fit least-squares regression
slope = covariance(x, y) / variance(x)
linreg_trend_pct = (slope / mean_price) * 100 * len(prices)
```

---

### 4️⃣ **Consensus Trend (Weighted Average)** ✅

```python
consensus_trend_pct = (
    ema_trend_pct        * 0.40 +  # Momentum & alignment
    linreg_trend_pct     * 0.40 +  # Structural direction
    normalized_trend_pct * 0.15 +  # Context-adjusted
    raw_trend_pct        * 0.05    # Baseline
)
```

**Eigenschappen:**
- ✅ EMA = snelheid & momentum
- ✅ LinReg = stabiliteit, filtert noise
- ✅ Normalized = volatiliteitscontext
- ✅ Raw = controle & baseline

---

### 5️⃣ **Multi-Timeframe Analyse** ✅

**Berekening per Timeframe:**
```python
trend_60m   = calculate_timeframe_trend(60 * 60)    # 1 uur
trend_240m  = calculate_timeframe_trend(240 * 60)   # 4 uur
trend_1440m = calculate_timeframe_trend(1440 * 60)  # 24 uur
```

**Composite Score:**
```python
trend_score = (
    trend_60m   * 0.20 +  # Short-term timing
    trend_240m  * 0.40 +  # Mid-term confirmation
    trend_1440m * 0.40    # Long-term macro trend
)
```

**Features:**
- ✅ 3 timeframes: 1h, 4h, 24h
- ✅ Weighted consensus score
- ✅ Warm-up fallback voor 24h (eerste 24h)

---

### 6️⃣ **Validatie & Blokkeerregels** ✅

**Constanten:**
```python
MIN_TREND_THRESHOLD = 0.5  # +0.5% minimum voor selectie
MIN_CANDLES_FOR_WARMUP = 360  # 30 uur × 60/5m = 360 candles
```

**Validatie Logica:**
```python
def validate_trend(symbol: str) -> TrendSelection:
    # Check 1: Candle count
    if candle_count < MIN_CANDLES_FOR_WARMUP:
        return TrendSelection(status=TrendStatus.WARMUP, passes=False)

    # Check 2: Trend threshold
    if trend_score < MIN_TREND_THRESHOLD:
        if trend_score < -MIN_TREND_THRESHOLD:
            status = TrendStatus.BEARISH
        else:
            status = TrendStatus.SIDEWAYS
        return TrendSelection(status=status, passes=False)

    # Passes all checks
    return TrendSelection(status=TrendStatus.BULLISH, passes=True)
```

**Beslislogica:**
- ❌ **WARMUP**: `candle_count < 360` → geen selectie
- ❌ **BEARISH**: `trend_score < -0.5%` → geen selectie
- ❌ **SIDEWAYS**: `trend_score between -0.5% and +0.5%` → geen selectie
- ✅ **BULLISH**: `trend_score >= +0.5%` → selectie toegestaan

---

### 7️⃣ **Output Contract** ✅

**TrendSelection Dataclass:**
```python
@dataclass
class TrendSelection:
    symbol: str               # "BTC/EUR"
    trend_1h: float          # -0.8
    trend_4h: float          # -1.4
    trend_24h: float         # -2.9
    trend_score_pct: float   # -1.96
    passes: bool             # False
    status: TrendStatus      # BEARISH
    candle_count: int        # 350
    consensus_pct: float     # -2.1
    volatility: float        # 0.85
```

**JSON Output Voorbeeld:**
```json
{
  "symbol": "BTC/EUR",
  "trend_1h": -0.8,
  "trend_4h": -1.4,
  "trend_24h": -2.9,
  "trend_score_pct": -1.96,
  "passes": false,
  "status": "BEARISH",
  "candle_count": 350,
  "consensus_pct": -2.1,
  "volatility": 0.85
}
```

---

### 8️⃣ **Niet-Functionele Eisen** ✅

- ✅ **Deterministisch**: Geen randomness, geen ML black-box
- ✅ **Uitlegbaar**: Elke indicator is traceerbaar
- ✅ **Warmup-safe**: Expliciete warmup status
- ✅ **Performance**: Efficient circular buffers
- ✅ **Production-ready**: Error handling, logging, validatie

---

## 🚀 Gebruik

### **Basic Usage**

```python
from multi_coin_grid_pro.utils import (
    TrendCalculator,
    TrendSelection,
    TrendStatus,
    MIN_TREND_THRESHOLD
)

# 1. Initialize
calculator = TrendCalculator(
    connector=exchange_connector,
    lookback_minutes=1440,  # 24 hours
    bot_start_time=time.time()
)

# 2. Load historical OHLCV data
await calculator.load_historical_data(["BTC-EUR", "ETH-EUR"])

# 3. Validate trends
for symbol in symbols:
    selection = calculator.validate_trend(symbol)

    if selection.passes:
        print(f"✅ {symbol}: {selection.trend_score_pct:+.2f}% - SELECTED")
    else:
        print(f"❌ {symbol}: {selection.status.value} - REJECTED")
```

### **Advanced: Get All Selections**

```python
# Get structured output for all coins
selections = calculator.get_all_selections()

# Filter only passing coins
passing_coins = [s for s in selections if s.passes]

# Sort by trend score
passing_coins.sort(key=lambda x: x.trend_score_pct, reverse=True)

# Select top 3
top_3 = passing_coins[:3]
```

### **Print Report**

```python
# Print formatted report to logs
calculator.print_selection_report()

# Output:
# ================================================================================
# 📊 TREND SELECTION REPORT
# ================================================================================
# Total coins tracked: 10
# Minimum threshold: +0.50%
# Minimum candles: 360
#
# Status Distribution:
#   WARMUP:   2 coins (insufficient data)
#   BEARISH:  3 coins (< -0.50%)
#   SIDEWAYS: 2 coins (-0.50% to +0.50%)
#   BULLISH:  3 coins (>= +0.50%)
#
#  1. 📈 BTC-EUR      | Score: +2.45% | 1h: +0.8% | 4h: +1.9% | 24h: +3.2% | Candles: 650 | ✅ BULLISH
#  2. 📈 ETH-EUR      | Score: +1.85% | 1h: +0.5% | 4h: +1.2% | 24h: +2.8% | Candles: 620 | ✅ BULLISH
#  ...
```

---

## 🧪 Testen

**Run Test Script:**
```bash
cd /home/mo/repos/hummingbot
python test_trend_engine.py
```

**Expected Output:**
- Laadt 720 candles per coin
- Berekent 4 indicatoren
- Genereert multi-timeframe trends
- Valideert volgens MIN_TREND_THRESHOLD
- Print structured output

---

## 📊 Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. OHLCV Candle Loading (30 hours)                        │
│    - Fetch 720 × 5m candles via ccxt                       │
│    - Store in CandleData objects                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Real-Time Updates (~30s intervals)                      │
│    - Update price_history                                   │
│    - Update OHLCV candles (5m intervals)                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Calculate 4 Indicators (per timeframe)                  │
│    - Raw Trend (5%)                                         │
│    - Volatility-Normalized (15%)                            │
│    - EMA Distance (40%)                                     │
│    - Linear Regression (40%)                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Consensus Trend (weighted average)                      │
│    consensus = 0.4×EMA + 0.4×LinReg + 0.15×Norm + 0.05×Raw│
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Multi-Timeframe Analysis                                │
│    - trend_60m (1h)                                         │
│    - trend_240m (4h)                                        │
│    - trend_1440m (24h)                                      │
│    - trend_score = 0.2×1h + 0.4×4h + 0.4×24h               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Validation & Selection                                   │
│    - Check candle_count >= 360                              │
│    - Check trend_score >= +0.5%                             │
│    - Determine status: WARMUP/BEARISH/SIDEWAYS/BULLISH     │
│    - Set passes = True/False                                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Output Contract                                          │
│    TrendSelection {                                         │
│      symbol, trend_1h, trend_4h, trend_24h,                │
│      trend_score_pct, passes, status, candle_count         │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Samenvatting

### **✅ Volledig Geïmplementeerd:**
1. ✅ OHLCV candle loading (720 candles)
2. ✅ Real-time price updates met data retentie
3. ✅ 4 indicatoren (Raw, Normalized, EMA, LinReg)
4. ✅ Consensus trend (gewogen gemiddelde)
5. ✅ Multi-timeframe analyse (1h, 4h, 24h)
6. ✅ Validatie met MIN_TREND_THRESHOLD (+0.5%)
7. ✅ Output contract (TrendSelection dataclass)
8. ✅ WARMUP status voor insufficient data
9. ✅ Production-ready (error handling, logging)

### **🚀 Klaar Voor Gebruik:**
- Import vanuit `multi_coin_grid_pro.utils`
- Gebruik `validate_trend()` voor individuele coins
- Gebruik `get_all_selections()` voor bulk validatie
- Gebruik `print_selection_report()` voor debug output

### **📈 Verwacht Gedrag:**
- ❌ Bearish markt → geen selectie (`status=BEARISH`)
- ❌ Sideways markt → geen forced trades (`status=SIDEWAYS`)
- ❌ Insufficient data → warmup mode (`status=WARMUP`)
- ✅ Alleen duidelijke bullish consensus → selectie toegestaan (`status=BULLISH`)

---

## 🔧 Configuration

**Constants (edit in `trend_calculator.py`):**
```python
MIN_TREND_THRESHOLD = 0.5  # +0.5% minimum
MIN_CANDLES_FOR_WARMUP = 360  # 30 hours
TARGET_HISTORICAL_CANDLES = 720  # 60 hours
```

**Weights (edit in `_calculate_consensus_trend()`):**
```python
weight_ema = 0.40
weight_linreg = 0.40
weight_normalized = 0.15
weight_raw = 0.05
```

**Timeframe Weights (edit in `_calculate_multi_timeframe_trends()`):**
```python
trend_score = (
    0.2 * trend_60m +   # 1h
    0.4 * trend_240m +  # 4h
    0.4 * trend_1440m   # 24h
)
```

---

## ✅ Implementation Complete!

Alle features uit de specificatie zijn geïmplementeerd en production-ready. De trend engine is nu een **robuust, multi-indicator, multi-timeframe systeem** dat alleen structureel bullish markten selecteert en bearish/sideways markten actief blokkeert.
