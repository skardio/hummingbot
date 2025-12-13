# B2 Hybrid Scalper - Usage Guide

## 🎯 Belangrijkste Commands

### Start Bot

```bash
cd /home/mo/repos/hummingbot/scripts/momentum_scalper_bitget

# Simulatie mode (default - GEEN echte trades)
python3 momentum_scalper.py

# Live trading (PAS OP!)
export EXECUTE_TRADES="true"
python3 momentum_scalper.py
```

### Analyze Trades

```bash
# Analyseert automatisch /home/mo/repos/hummingbot/logs/momentum_trades.json
python3 analyze_trades.py

# Of specifiek bestand
python3 analyze_trades.py /path/to/trades.json
```

### Run Tests

```bash
python3 tests/test_scalper.py
```

---

## 📁 Log Locaties

Het bot detecteert automatisch de juiste log directory:

| Locatie | Doel |
|---------|------|
| `/home/mo/repos/hummingbot/logs/momentum_scalper.log` | Bot activiteit |
| `/home/mo/repos/hummingbot/logs/momentum_trades.json` | Alle trades (1 per regel) |

Je kunt ook absolute paths opgeven in `config.yaml`:

```yaml
log_file: /home/mo/logs/my_bot.log
trade_log_file: /home/mo/logs/my_trades.json
```

---

## 🔍 Real-time Monitoring

### Tail Logs

```bash
# Bot logs (met kleuren)
tail -f /home/mo/repos/hummingbot/logs/momentum_scalper.log | grep -E "🎯|✅|❌|🔥|🧊"

# Alleen signals
tail -f /home/mo/repos/hummingbot/logs/momentum_scalper.log | grep "📊 SIGNAL"

# Alleen trades
tail -f /home/mo/repos/hummingbot/logs/momentum_scalper.log | grep -E "OPEN|CLOSE"
```

### Check Status

```bash
# Zie laatste 20 regels
tail -20 /home/mo/repos/hummingbot/logs/momentum_scalper.log

# Zie laatste trades
tail -5 /home/mo/repos/hummingbot/logs/momentum_trades.json | python3 -m json.tool
```

### Check Cooldowns

```bash
grep "🧊" /home/mo/repos/hummingbot/logs/momentum_scalper.log | tail -10
```

### Check Hot Symbols

```bash
grep "🔥" /home/mo/repos/hummingbot/logs/momentum_scalper.log | tail -10
```

---

## ⚙️ Config Aanpassen

Edit `config.yaml`:

```bash
nano config.yaml
```

De bot herlaadt de config bij **restart** (niet hot-reload).

### Belangrijkste Parameters

**Meer trades gewenst?**
```yaml
momentum_threshold: 30          # Was 35
base_atr_threshold: 0.02        # Was 0.03
min_orderflow_score: 25         # Was 30
```

**Minder trades gewenst?**
```yaml
momentum_threshold: 45          # Was 35
min_orderflow_score: 40         # Was 30
max_trades_per_hour: 6          # Was 10
```

**Agressievere sizing?**
```yaml
max_position_multiplier: 5.0    # Was 3.0
```

**Langere cooldown?**
```yaml
cooldown_duration_seconds: 7200  # 2 uur i.p.v. 1 uur
```

---

## 📊 Performance Checken

### Quick Check

```bash
python3 analyze_trades.py | grep -A 10 "PERFORMANCE METRICS"
```

### Per Symbol

```bash
python3 analyze_trades.py | grep -A 20 "PER-SYMBOL"
```

### Exit Reasons

```bash
python3 analyze_trades.py | grep -A 10 "EXIT REASON"
```

---

## 🐛 Troubleshooting

### Bot maakt geen trades

```bash
# Check ATR rejects
grep "ATR too low" /home/mo/repos/hummingbot/logs/momentum_scalper.log | tail -10

# Check strength rejects
grep "strength.*<" /home/mo/repos/hummingbot/logs/momentum_scalper.log | tail -10
```

**Fix**: Verlaag thresholds in config.yaml

### Bot stopt meteen

```bash
# Check errors
grep "ERROR\|Exception\|Traceback" /home/mo/repos/hummingbot/logs/momentum_scalper.log | tail -20
```

**Fix**: Check API credentials

### Te veel losses

```bash
# Analyze per symbol
python3 analyze_trades.py | grep -A 20 "PER-SYMBOL"
```

**Fix**: De bot zet slechte symbols automatisch op cooldown

### Kan analyze_trades.py niet draaien

```bash
# Check of trade log bestaat
ls -lh /home/mo/repos/hummingbot/logs/momentum_trades.json

# Run analyzer met debug
python3 analyze_trades.py 2>&1
```

---

## 🔄 Bot Herstarten

```bash
# Stop bot (in terminal waar het draait)
Ctrl+C

# Of force kill
pkill -f momentum_scalper.py

# Start opnieuw
python3 momentum_scalper.py
```

---

## 📈 Exporting Data

### Export trades naar CSV

```bash
python3 << 'EOF'
import json
import csv

with open('/home/mo/repos/hummingbot/logs/momentum_trades.json', 'r') as f:
    trades = [json.loads(line) for line in f if line.strip()]

with open('trades_export.csv', 'w', newline='') as f:
    if trades:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)

print(f"✅ Exported {len(trades)} trades to trades_export.csv")
EOF
```

### Backup logs

```bash
# Backup met timestamp
cp /home/mo/repos/hummingbot/logs/momentum_trades.json \
   ~/backups/momentum_trades_$(date +%Y%m%d_%H%M%S).json
```

---

## 🎓 Advanced

### Custom Config

```bash
python3 momentum_scalper.py --config my_custom_config.yaml
```

(Nog niet geïmplementeerd - gebruik standaard config.yaml)

### Run in Background

```bash
# Met nohup
nohup python3 momentum_scalper.py > bot.out 2>&1 &

# Check process
ps aux | grep momentum_scalper

# Stop
pkill -f momentum_scalper.py
```

### Multiple Bots

```bash
# Bot 1 (conservative)
cp config.yaml config_conservative.yaml
# Edit config_conservative.yaml

# Start (requires code change to accept --config)
python3 momentum_scalper.py  # Uses config.yaml
```

---

## 📞 Support Checklist

Als je hulp nodig hebt, verzamel:

1. ✅ Laatste 50 regels van bot log:
   ```bash
   tail -50 /home/mo/repos/hummingbot/logs/momentum_scalper.log
   ```

2. ✅ Trade analyzer output:
   ```bash
   python3 analyze_trades.py
   ```

3. ✅ Config settings:
   ```bash
   cat config.yaml
   ```

4. ✅ Bot versie:
   ```bash
   grep "B2 Hybrid" momentum_scalper.py | head -1
   ```

---

**Last updated: 2025-12-06**
