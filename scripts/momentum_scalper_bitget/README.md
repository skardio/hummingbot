# B2 Hybrid Scalper Bot

**Professional orderflow + momentum scalper with AI-adaptive features**

---

## 🎯 Strategy Overview

The B2 Hybrid Scalper combines **orderflow analysis** (real-time orderbook + taker flow) with **candle momentum indicators** (RSI, EMA, VWAP) to identify high-probability scalping opportunities.

### Key Differentiators

| Feature | Description |
|---------|-------------|
| **Orderflow Momentum Score** | 0-100 score combining orderbook imbalance, taker buy/sell ratio, spread quality, and micro price movement |
| **AI-Adaptive ATR** | Dynamically lowers ATR requirements when orderflow is strong (65+ → 60%, 80+ → 40%) |
| **AI-Adaptive Position Sizing** | Scales position size 0.5x-3.0x based on trade quality, symbol hot/cold score, and daily P&L |
| **Per-Symbol Cooldown** | Automatically pauses trading a symbol after 3 losses or hot_score < 0.3 for 1 hour |
| **Hot/Cold Tracking** | Tracks last 10 trades per symbol to identify "hot" (winning) vs "cold" (losing) symbols |
| **ATR-based TP/SL** | Dynamic take profit & stop loss based on market volatility (ATR × multiplier) |

---

## 📁 File Structure

```
momentum_scalper_bitget/
├── momentum_scalper.py      # Main bot
├── config.yaml              # Configuration file
├── analyze_trades.py        # Trade analyzer
├── README.md                # This file
└── tests/                   # Unit tests
    └── test_scalper.py
```

---

## ⚙️ Configuration

Edit `config.yaml` to tune the strategy:

### Core Parameters

```yaml
# Trading
base_order_size_usdt: 20.0  # Base position size
max_positions: 3            # Max concurrent positions
position_timeout_seconds: 900  # 15 min max hold

# Signal Detection
momentum_threshold: 35      # Minimum signal strength (0-100)
min_orderflow_score: 30     # Minimum orderflow momentum

# Orderflow Filters
min_imbalance_long: 0.52    # >52% bids = bullish
min_taker_buy_ratio_long: 0.52  # >52% taker buys = bullish
max_spread_bps: 20          # Max 0.20% spread

# ATR-based TP/SL
atr_tp_multiplier: 0.8      # TP = ATR × 0.8
atr_sl_multiplier: 1.1      # SL = ATR × 1.1

# AI-Adaptive Features
enable_adaptive_sizing: true
enable_cooldown: true
base_atr_threshold: 0.03    # Base ATR minimum (3 basis points)
```

---

## 🚀 Usage

### Prerequisites

```bash
pip install ccxt numpy pyyaml requests
```

### Environment Variables

```bash
export BITGET_API_KEY="your_key"
export BITGET_SECRET_KEY="your_secret"
export BITGET_PASSPHRASE="your_passphrase"
export TELEGRAM_BOT_TOKEN="optional"
export TELEGRAM_CHAT_ID="optional"
export EXECUTE_TRADES="false"  # Set to "true" for live trading
```

### Run the Bot

```bash
cd /home/mo/repos/hummingbot/scripts/momentum_scalper_bitget
python3 momentum_scalper.py
```

### Analyze Results

```bash
python3 analyze_trades.py
```

---

## 📊 Signal Generation Pipeline

```
1. Fetch Candles (OHLCV 1m)
   ↓
2. Calculate Indicators
   - RSI (14)
   - EMA fast (10) / EMA slow (25)
   - VWAP
   - ATR (14)
   - Volume ratio
   ↓
3. Fetch Orderflow
   - Orderbook imbalance (bid/ask ratio)
   - Taker buy/sell ratio (from trades)
   - Spread (bid-ask)
   - Micro price movement
   ↓
4. Compute Scores
   - Candle signal strength (0-100)
     • RSI extreme: +20
     • EMA trend: +15
     • VWAP position: +10
     • Price momentum: +20
     • Volume: +10
   - Orderflow momentum score (0-100)
     • Imbalance distance: +35
     • Taker flow distance: +35
     • Spread quality: +20
     • Micro move: ±10
   ↓
5. Apply Filters
   - Signal strength >= threshold (35)
   - Orderflow score >= threshold (30)
   - Spread < 20 bps
   - AI-adaptive ATR check
   - Symbol cooldown check
   ↓
6. Generate Signal
   - Direction: LONG or SHORT
   - Entry price
   - ATR-based TP/SL
   ↓
7. Execute with Adaptive Sizing
   - Base size × quality × hot_score × safety
   - Range: 0.5x - 3.0x base
```

---

## 🎯 Exit Strategy

### Multi-Layer Exit System

1. **Take Profit**: ATR × 0.8 (clamped 0.5-1.2%)
2. **Stop Loss**: ATR × 1.1 (clamped 0.7-1.5%)
3. **Trailing Stop**: 0.35% below peak (activated after 0.5% profit)
4. **Timeout**: 15 minutes max hold time

All exits account for fees (0.2% round-trip).

---

## 🔥 Hot/Cold System

### Hot Score Calculation

```
hot_score = (avg_result + 1) / 2
where avg_result = average of last 10 trades (-1 = loss, +1 = win)

hot_score = 0.0  → 100% losses
hot_score = 0.5  → neutral (50/50)
hot_score = 1.0  → 100% wins
```

### Cooldown Triggers

| Trigger | Action |
|---------|--------|
| 3 losses in a row | 1 hour cooldown |
| hot_score < 0.3 | 1 hour cooldown |
| 3 wins in a row + hot_score > 0.7 | Mark as HOT (1.25x size multiplier) |

---

## 🧠 AI-Adaptive Position Sizing

### Size Formula

```
final_size = base_size × quality_mult × hotness_mult × safety_mult

where:
  quality_mult = based on trade_quality (0.6×of_score + 0.4×signal_strength)
    - quality < 0.4: 0.5x
    - quality < 0.6: 1.0x
    - quality < 0.8: 1.5x
    - quality >= 0.8: 2.0x

  hotness_mult = based on hot_score
    - hot_score > 0.7: 1.25x
    - hot_score < 0.3: 0.7x
    - else: 1.0x

  safety_mult = based on daily_pnl
    - daily_pnl < -50 USDT: 0.5x
    - daily_pnl < -20 USDT: 0.7x
    - else: 1.0x
```

### Example

```
Base size: $20
Trade quality: 0.85 (strong) → 2.0x
Hot score: 0.75 (hot) → 1.25x
Daily P&L: -$10 (OK) → 1.0x

Final size = $20 × 2.0 × 1.25 × 1.0 = $50
```

---

## 📈 Performance Metrics

Run `analyze_trades.py` to get:

- Total P&L (gross & net after fees)
- Win rate
- Average win/loss
- Profit factor
- Expectancy per trade
- Max drawdown
- Sharpe ratio
- Per-symbol breakdown
- Hot/cold streaks
- Exit reason analysis
- Equity curve

---

## 🛡️ Risk Management

| Protection | Threshold |
|------------|-----------|
| Max Daily Loss | 4% of capital |
| Max Trades/Hour | 10 |
| Position Timeout | 15 minutes |
| Spread Filter | 0.20% max |
| ATR Minimum | 0.03% (adaptive) |
| Position Size | 0.5x - 3.0x base |

---

## 🔧 Troubleshooting

### Bot makes no trades

1. Check orderflow logs: `grep "🔍" logs/momentum_scalper.log | tail -20`
2. Check ATR rejects: `grep "ATR too low" logs/momentum_scalper.log | tail -10`
3. Lower `base_atr_threshold` in config.yaml (try 0.02 or 0.01)
4. Lower `momentum_threshold` to 30 or 25
5. Check if symbols are on cooldown: Look for `🧊` in logs

### Too many trades

1. Increase `momentum_threshold` to 45 or 50
2. Increase `min_orderflow_score` to 40 or 50
3. Tighten orderflow filters (e.g., `min_imbalance_long: 0.60`)
4. Increase `max_spread_bps` to skip more pairs

### Losing money

1. Run `analyze_trades.py` to see which symbols/exit reasons are losing
2. Add losing symbols to cooldown blacklist
3. Increase `atr_sl_multiplier` to 1.2 or 1.3 (wider stop loss)
4. Enable `enable_adaptive_sizing: false` to disable aggressive sizing

---

## 📝 Changelog

### v2.0 - B2 Hybrid (2025-12-06)

- ✅ Added orderflow momentum score (0-100)
- ✅ Implemented AI-adaptive ATR threshold
- ✅ Implemented AI-adaptive position sizing
- ✅ Added per-symbol hot/cold tracking
- ✅ Added automatic cooldown system
- ✅ Added config.yaml support
- ✅ Added analyze_trades.py tool
- ✅ NET P&L accounting (fees deducted)

### v1.0 - Initial (2025-12-05)

- ✅ Basic momentum + RSI strategy
- ✅ Simple orderflow integration
- ✅ Telegram alerts

---

## 📖 References

- **Orderflow Trading**: Larry Williams, "The Secret Science of Price and Volume"
- **ATR-based Stops**: J. Welles Wilder Jr., "New Concepts in Technical Trading Systems"
- **Adaptive Position Sizing**: Ralph Vince, "The Mathematics of Money Management"

---

## ⚠️ Disclaimer

This bot is for educational purposes. Trading cryptocurrencies involves significant risk. Always test in simulation mode first (`EXECUTE_TRADES=false`) and never trade more than you can afford to lose.

---

## 🤝 Support

For issues or questions, check the logs:
- Main log: `logs/momentum_scalper.log`
- Trade log: `logs/momentum_trades.json`

Run `analyze_trades.py` for detailed performance analysis.
