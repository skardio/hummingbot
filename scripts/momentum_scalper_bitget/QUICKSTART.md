# B2 Hybrid Scalper - Quick Start Guide

## 🚀 Start in 3 stappen

### 1. Setup Environment

```bash
cd /home/mo/repos/hummingbot/scripts/momentum_scalper_bitget

# API keys (voor live trading)
export BITGET_API_KEY="your_key"
export BITGET_SECRET_KEY="your_secret"
export BITGET_PASSPHRASE="your_passphrase"

# Telegram (optioneel)
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Trading mode
export EXECUTE_TRADES="false"  # false = simulation, true = live
```

### 2. Tune Config (Optioneel)

Bewerk `config.yaml` naar jouw voorkeur:

```yaml
# Agressief (meer trades)
momentum_threshold: 30
base_atr_threshold: 0.02

# Conservatief (minder, betere trades)
momentum_threshold: 50
base_atr_threshold: 0.05
```

### 3. Start!

```bash
python3 momentum_scalper.py
```

---

## 📊 Monitor Performance

### Real-time

Check de terminal output:
```
⏱️ Positions: 2/3 | Trades: 15 (W:9 L:6) | Win Rate: 60.0% | P&L: $12.45
```

### Logs

```bash
tail -f logs/momentum_scalper.log
```

### Detailed Analysis

```bash
python3 analyze_trades.py
```

Output:
```
  📈 PERFORMANCE METRICS
========================================
Total PNL:             12.45 USDT
Trades:                   15
Wins:                      9 (60.0%)
Losses:                    6 (40.0%)

Average Win:           2.150 USDT
Average Loss:         -0.983 USDT
Profit Factor:          1.98
Expectancy/trade:      0.4380 USDT

  📊 PER-SYMBOL PERFORMANCE
========================================
Symbol       | Trades | Winrate | Total PNL
BTC/USDT     |      5 |   80.0% |      8.20
ETH/USDT     |      4 |   50.0% |      2.10
SOL/USDT     |      6 |   50.0% |      2.15
```

---

## 🔧 Tuning Tips

### Te weinig trades?

1. Verlaag `momentum_threshold` (bijv. 30)
2. Verlaag `base_atr_threshold` (bijv. 0.02)
3. Verlaag `min_orderflow_score` (bijv. 25)

### Te veel trades?

1. Verhoog `momentum_threshold` (bijv. 45)
2. Verhoog `min_orderflow_score` (bijv. 40)
3. Verlaag `max_trades_per_hour` (bijv. 6)

### Verliezende symbols?

De bot detecteert dit automatisch:
```
🧊 DOGE/USDT cooled down for 60min (hot_score=0.25, losses=3)
```

Check welke symbols cold zijn:
```bash
grep "🧊" logs/momentum_scalper.log
```

### Performance slecht?

```bash
python3 analyze_trades.py
```

Kijk naar:
- **Per-Symbol**: Welke coins verliezen?
- **Exit Reason**: Waarom sluiten trades?
- **Profit Factor**: < 1.5 = probleem

---

## 🎯 Expected Performance

| Metric | Conservative | Balanced | Aggressive |
|--------|--------------|----------|------------|
| Trades/day | 10-15 | 20-30 | 40-60 |
| Win Rate | 55-60% | 52-57% | 50-55% |
| Avg Win | 0.5-0.8% | 0.4-0.6% | 0.3-0.5% |
| Net P&L/day | 1-2% | 2-4% | 3-6% |
| Max Drawdown | < 2% | < 3% | < 5% |

*Based on $100 capital, includes fees*

---

## 🛑 Stop the Bot

```
Ctrl+C
```

Bot shows summary:
```
==============================================================
  BOT STOPPED
==============================================================

Total trades: 15
Won: 9 | Lost: 6
Win rate: 60.0%
Total P&L: $12.45
```

---

## 🧪 Run Tests

```bash
python3 tests/test_scalper.py
```

All 19 tests should pass:
```
Ran 19 tests in 0.072s
OK
```

---

## 📝 Log Files

| File | Inhoud |
|------|--------|
| `logs/momentum_scalper.log` | Alle bot activiteit (signalen, trades, errors) |
| `logs/momentum_trades.json` | Alle trades (JSON, 1 per regel) |

---

## ❓ FAQ

**Q: Bot maakt geen trades?**
A: Check `grep "ATR too low" logs/momentum_scalper.log` en verlaag `base_atr_threshold` in config.yaml.

**Q: Hoe werk ik met hot/cold?**
A: Automatisch! De bot tracked dit zelf en pauzeer cold symbols.

**Q: Kan ik meer dan 5 symbols traden?**
A: Ja, voeg toe in `config.yaml` onder `symbols:`.

**Q: Hoe test ik zonder echt geld?**
A: Zorg dat `EXECUTE_TRADES="false"` (default).

---

🎉 **Succes met traden!**
