# 🔍 USD Bot Setup - Verificatie Checklist

Dit document beschrijft hoe je verifieert dat de EUR en USD bots correct geïsoleerd draaien.

---

## 📁 Gemaakte Files

| File | Doel |
|------|------|
| `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` | USD config |
| `multi_coin_grid_pro/scripts/multi_coin_grid_v2_usd.py` | USD strategy script |
| `start_bot_usd.sh` | USD start script |

---

## ✅ Pre-Start Verificatie

```bash
# 1. Check USD config bestaat
ls -la multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml

# 2. Check quote_asset is USD (niet EUR!)
grep "quote_asset:" multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml
# Expected: quote_asset: USD

# 3. Check instance_id is "usd"
grep "instance_id:" multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml
# Expected: instance_id: "usd"

# 4. Check EUR config heeft instance_id "eur"
grep "instance_id:" multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml
# Expected: instance_id: "eur"

# 5. Check USD script laadt juiste config
grep "CONFIG_NAME" multi_coin_grid_pro/scripts/multi_coin_grid_v2_usd.py
# Expected: CONFIG_NAME: str = "spot_grid_kraken_usd"
```

---

## 🚀 Start Commands

### Optie A: Via Shell Script (aanbevolen)

#### Terminal 1: EUR Bot
```bash
cd /home/mo/repos/hummingbot
./start_bot.sh
```

#### Terminal 2: USD Bot (apart terminal/tmux)
```bash
cd /home/mo/repos/hummingbot
./start_bot_usd.sh
```

### Optie B: Via Hummingbot CLI (interactief)

#### Terminal 1: EUR Bot
```bash
cd /home/mo/repos/hummingbot
./start
# In Hummingbot shell:
>>> connect kraken
>>> start --script multi_coin_grid_v2.py
```

#### Terminal 2: USD Bot
```bash
cd /home/mo/repos/hummingbot
./start
# In Hummingbot shell:
>>> connect kraken
>>> start --script multi_coin_grid_v2_usd.py
```

### Optie C: Met tmux (aanbevolen)
```bash
# Maak 2 sessies
tmux new-session -d -s eur_bot './start_bot.sh'
tmux new-session -d -s usd_bot './start_bot_usd.sh'

# Attach to EUR
tmux attach -t eur_bot

# Attach to USD (in andere terminal)
tmux attach -t usd_bot

# List sessies
tmux ls
```

---

## 🔍 Runtime Verificatie

### 1. Check Separate Cooldown DBs
```bash
# Na enkele minuten draaien:
ls -la data/cooldowns*.db
# Expected:
#   data/cooldowns.db       (legacy, EUR tot update)
#   data/cooldowns_eur.db   (EUR na herstart)
#   data/cooldowns_usd.db   (USD)
```

### 2. Check Separate Logs
```bash
# EUR logs
ls -la logs/logs_multi_coin_grid_v2_*.log | tail -3

# USD logs (via log filename of grep)
ls -la logs/logs_multi_coin_grid_usd_*.log | tail -3 2>/dev/null || \
  echo "USD logs in same pattern, check content for 'USD'"

# Verify quote currency in logs
grep "quote_asset\|Quote Asset" logs/logs_multi_coin_grid_v2_*.log | tail -3
```

### 3. Check Separate Events Directories
```bash
ls -la logs/events/      # EUR events
ls -la logs/events_usd/  # USD events
```

### 4. Check Geen Gedeelde Orders
```bash
# EUR orders
grep "ORDER_PLACED\|GRID_CREATED" logs/logs_multi_coin_grid_v2_*.log | grep "\-EUR" | tail -5

# USD orders
grep "ORDER_PLACED\|GRID_CREATED" logs/logs_multi_coin_grid_v2_*.log | grep "\-USD" | tail -5
```

### 5. Check Instance ID in Logs
```bash
# Zoek naar instance_id logging
grep -E "instance_id|Instance ID|cooldowns_usd|cooldowns_eur" logs/logs_multi_coin_grid_*.log | tail -10
```

---

## 🛡️ Guardrails

De `start_bot_usd.sh` heeft ingebouwde guardrails:

1. **Config existence check**: Script faalt als `spot_grid_kraken_usd.yaml` niet bestaat
2. **Quote asset check**: Script faalt als USD config "EUR" bevat
3. **Environment variables**: `BOT_ENV=usd` en `MULTI_COIN_GRID_CONFIG=spot_grid_kraken_usd`

---

## 📊 Key Config Differences

| Parameter | EUR | USD |
|-----------|-----|-----|
| `instance_id` | "eur" | "usd" |
| `quote_asset` | EUR | USD |
| `min_24h_volume_*` | 150000 EUR | 200000 USD |
| `total_amount_quote` | 280 | 300 |
| `btc_symbol` | BTC-EUR | BTC-USD |
| `altcoin_breadth_sample_pairs` | *-EUR | *-USD |
| `events_output_dir` | logs/events | logs/events_usd |
| Cooldowns DB | data/cooldowns_eur.db | data/cooldowns_usd.db |

---

## 🔧 Troubleshooting

### USD bot laadt EUR config?
```bash
# Check CONFIG_NAME in USD script
grep "CONFIG_NAME" multi_coin_grid_pro/scripts/multi_coin_grid_v2_usd.py
# Moet zijn: "spot_grid_kraken_usd"

# Check dat USD config correct is
head -20 multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml
```

### DBs zijn niet gescheiden?
```bash
# Check instance_id in configs
grep "instance_id" multi_coin_grid_pro/config/spot_grid_kraken_*.yaml

# Herstart beide bots - DB wordt aangemaakt bij eerste cooldown write
```

### Orders van verkeerde quote currency?
```bash
# Check welke pairs actief zijn
grep "SELECTED\|Creating grid" logs/logs_multi_coin_grid_*.log | tail -10

# EUR moet alleen *-EUR pairs hebben
# USD moet alleen *-USD pairs hebben
```

---

## 📝 Quick Status Check

```bash
#!/bin/bash
# save als: check_bot_status.sh

echo "=== EUR Bot ==="
grep "instance_id\|quote_asset" multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml | head -2
ls -la data/cooldowns_eur.db 2>/dev/null || echo "No EUR cooldowns DB yet"
pgrep -f "multi_coin_grid_v2.py" && echo "EUR bot: RUNNING" || echo "EUR bot: NOT RUNNING"

echo ""
echo "=== USD Bot ==="
grep "instance_id\|quote_asset" multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml | head -2
ls -la data/cooldowns_usd.db 2>/dev/null || echo "No USD cooldowns DB yet"
pgrep -f "multi_coin_grid_v2_usd.py" && echo "USD bot: RUNNING" || echo "USD bot: NOT RUNNING"
```

---

*Created: 2026-01-17*
