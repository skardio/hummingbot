# Operations Guide — Trading Bot

> Laatst bijgewerkt: 15 maart 2026

Praktische handleiding voor het dagelijks beheer van de trading bot.

---

## Inhoudsopgave

1. [Bot starten & stoppen](#1-bot-starten--stoppen)
2. [Configuratie bestanden](#2-configuratie-bestanden)
3. [Database beheer](#3-database-beheer)
4. [Log beheer](#4-log-beheer)
5. [Monitoring & Health checks](#5-monitoring--health-checks)
6. [Backup & Restore](#6-backup--restore)
7. [Systemd services](#7-systemd-services)
8. [Veelvoorkomende problemen](#8-veelvoorkomende-problemen)
9. [Belangrijke paden](#9-belangrijke-paden)

---

## 1. Bot starten & stoppen

### Venv activeren (altijd eerst!)
```bash
source ~/.venvs/bot/bin/activate
```

### Interactief starten (met terminal UI)
```bash
cd /home/mo/repos/hummingbot
python bin/hummingbot.py
```
Daarna in de Hummingbot CLI:
```
start --script multi_coin_grid_v2.py --conf spot_grid_kraken_usd.yaml
```

### Headless starten via systemd
```bash
sudo systemctl start bot-kraken-eur
```

### Bot stoppen

**⚠️ BELANGRIJK: Stop de bot ALTIJD zelf via de terminal of systemctl. Laat scripts of tools dit NOOIT automatisch doen.**

**Interactieve bot:**
```
# In de Hummingbot CLI:
stop
exit
```

**Systemd bot:**
```bash
sudo systemctl stop bot-kraken-eur
```

### Huidige status bekijken
```bash
# Welke bots draaien er?
ps aux | grep hummingbot | grep -v grep

# Systemd status
sudo systemctl status bot-kraken-eur
sudo systemctl status bot-kraken-usd
```

---

## 2. Configuratie bestanden

| Bot | Config bestand |
|-----|---------------|
| Kraken USD | `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` |
| Kraken EUR | `multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml` |
| Bitget Spot | `multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml` |
| Bitget Futures | `multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml` |
| Risk Monitor | `multi_coin_grid_pro/config/risk_monitor.yaml` |

**Na een config-wijziging moet de bot herstart worden om de nieuwe waarden op te pikken.**

### Belangrijke config parameters

```yaml
# Risk limieten
daily_loss_limit_pct: 0.03      # Max 3% dagelijks verlies → kill switch
stop_loss_pct: 0.05             # Stop-loss per grid positie
grid_timeout_seconds: 3600      # Auto-cancel na 1 uur inactiviteit

# Smart Entry filters (T3-F3)
smart_entry_filter:
  rsi_buy_max: 72               # RSI baseline drempel
  max_entry_spread_pct: 0.5     # Max bid-ask spread voor entry

# Adaptive filters per regime
adaptive_filters:
  rsi_buy_max:
    BEAR: 66
    CHOP: 72
    BULL: 76
```

---

## 3. Database beheer

### Database locaties

| Database | Pad | Grootte | Doel |
|----------|-----|---------|------|
| Monitoring | `multi_coin_grid_pro/data/monitoring.db` | 320 MB | Bot status & events |
| Cooldowns USD | `data/cooldowns_usd.db` | 16 KB | Blacklist/cooldown timers |
| Cooldowns EUR | `data/cooldowns_eur.db` | 16 KB | Blacklist/cooldown timers |
| Entry Prices USD | `data/entry_prices_usd.db` | 4 KB | Entry price persistence |
| Entry Prices EUR | `data/entry_prices_eur.db` | 12 KB | Entry price persistence |
| Trade DB USD | `data/multi_coin_grid_v2_usd.sqlite` | ~8 MB | Hummingbot trades |
| Trade DB EUR | `data/multi_coin_grid_v2.sqlite` | ~12 MB | Hummingbot trades |

### Automatische retentie
De monitoring database wordt automatisch opgeschoond bij het starten van de bot (`prune_old_data()` in `monitoring/database.py`). Oude records worden verwijderd.

### Handmatige VACUUM (schijfruimte vrijmaken)
Na het prunen van data blijft het `.db` bestand even groot. Om daadwerkelijk schijfruimte vrij te maken:

```bash
# ⚠️ STOP DE BOT EERST voordat je VACUUM uitvoert!
sqlite3 multi_coin_grid_pro/data/monitoring.db "VACUUM;"
```
Dit kan de monitoring.db van 320 MB terugbrengen naar een fractie daarvan.

### WAL-modus
Alle databases draaien in WAL-modus (Write-Ahead Logging) voor betere performance en crash-safety. Dit is automatisch geconfigureerd.

Controleren:
```bash
sqlite3 data/cooldowns_usd.db "PRAGMA journal_mode;"
# Verwacht: wal
```

---

## 4. Log beheer

### Log locatie
```
logs/                          # Alle bot logs (huidige grootte: 3.2 GB)
```

### Automatische opschoning (cron)
Er draait een dagelijkse cron job om 03:30:
- Logs ouder dan 7 dagen → gecomprimeerd (`.gz`)
- Gecomprimeerde logs ouder dan 30 dagen → verwijderd
- JSONL bestanden ouder dan 14 dagen → verwijderd

### Handmatig opschonen
```bash
# Script direct uitvoeren:
/home/mo/repos/hummingbot/deploy/cleanup_logs.sh

# Of specifiek oude logs verwijderen:
find logs/ -name "*.log" -mtime +7 -exec gzip {} \;
find logs/ -name "*.log.gz" -mtime +30 -delete
```

### Cron job controleren
```bash
crontab -l
# Verwacht:
# 30 3 * * * /home/mo/repos/hummingbot/deploy/cleanup_logs.sh >> /tmp/logclean.log 2>&1
```

### Log output van cleanup bekijken
```bash
cat /tmp/logclean.log
```

---

## 5. Monitoring & Health checks

### Health endpoint
De monitoring dashboard heeft een `/health` endpoint:
```bash
curl http://localhost:5000/health
```
Response:
```json
{"status": "healthy", "age_seconds": 12, "max_age_seconds": 600}
```
- HTTP 200 + `"healthy"` → alles OK
- HTTP 503 + `"unhealthy"` → data is te oud of database niet bereikbaar

### Handmatige checks
```bash
# Is de bot actief?
ps aux | grep hummingbot | grep -v grep

# Geheugengebruik
ps aux | grep hummingbot | awk '{print $6/1024 " MB"}'

# Database grootte
ls -lh multi_coin_grid_pro/data/monitoring.db

# Laatste trades controleren (in SQLite)
sqlite3 data/multi_coin_grid_v2_usd.sqlite \
  "SELECT * FROM TradeFill ORDER BY timestamp DESC LIMIT 5;"
```

---

## 6. Backup & Restore

### Automatische backup (cron)
Dagelijks om 03:00 worden alle databases gebackupt:
- Script: `deploy/backup_dbs.sh`
- Backups in: `backups/db/`
- Retentie: 7 dagen (oudere backups worden automatisch verwijderd)
- Methode: `sqlite3 .backup` (crash-safe, WAL-compatible)

### Handmatige backup
```bash
/home/mo/repos/hummingbot/deploy/backup_dbs.sh
```

### Backup controleren
```bash
ls -lh backups/db/
# Verwacht: bestanden met datum van vandaag

cat /tmp/backup.log
# Verwacht: "9 databases backed up, pruned >7d"
```

### Restore uit backup
```bash
# ⚠️ STOP DE BOT EERST!

# Voorbeeld: restore monitoring database van 15 maart
cp backups/db/monitoring_2026-03-15.db multi_coin_grid_pro/data/monitoring.db

# Voorbeeld: restore trade database
cp backups/db/multi_coin_grid_v2_usd_2026-03-15.sqlite data/multi_coin_grid_v2_usd.sqlite
```

### Cron job controleren
```bash
crontab -l
# Verwacht:
# 0 3 * * * /home/mo/repos/hummingbot/deploy/backup_dbs.sh >> /tmp/backup.log 2>&1
```

---

## 7. Systemd services

### Overzicht

| Service | Bestand | Status |
|---------|---------|--------|
| `bot-kraken-eur` | `/etc/systemd/system/bot-kraken-eur.service` | **enabled** |
| `bot-kraken-usd` | `/etc/systemd/system/bot-kraken-usd.service` | disabled |
| `bot-bitget-spot` | `/etc/systemd/system/bot-bitget-spot.service` | disabled |
| `bot-bitget-futures` | `/etc/systemd/system/bot-bitget-futures.service` | disabled |

### Commando's
```bash
# Status bekijken
sudo systemctl status bot-kraken-eur

# Starten
sudo systemctl start bot-kraken-eur

# Stoppen
sudo systemctl stop bot-kraken-eur

# Inschakelen bij boot
sudo systemctl enable bot-kraken-eur

# Uitschakelen bij boot
sudo systemctl disable bot-kraken-eur

# Logs bekijken (systemd journal)
sudo journalctl -u bot-kraken-eur -f          # live volgen
sudo journalctl -u bot-kraken-eur --since today  # vandaag
sudo journalctl -u bot-kraken-eur -n 100      # laatste 100 regels
```

### Service herstarten na config wijziging
```bash
sudo systemctl restart bot-kraken-eur
```

### Nieuwe service activeren
Om bijv. de USD bot via systemd te laten draaien:
```bash
sudo systemctl enable bot-kraken-usd
sudo systemctl start bot-kraken-usd
```

---

## 8. Veelvoorkomende problemen

### Bot start niet op
1. Check of de venv geactiveerd is: `which python` → moet `/home/mo/.venvs/bot/bin/python` zijn
2. Check of er al een bot draait: `ps aux | grep hummingbot`
3. Check de logs: `tail -50 logs/logs_multi_coin_grid_v2_usd_*.log`

### Kill switch geactiveerd
De bot stopt met handelen als:
- Dagelijks verlies > 3% (`daily_loss_limit_pct`)
- De drawdown limiet is bereikt

Check de logs op "kill switch" of "drawdown" berichten. Na een kill switch activatie:
1. Analyseer wat er gebeurd is
2. Herstart de bot (kill switch reset bij herstart)

### "Insufficient funds" errors
- Controleer beschikbaar saldo op de exchange
- Check of er te veel open orders/posities zijn die kapitaal locken
- Verlaag `max_grids_per_coin` of `max_active_slots` in de config

### Database locked errors
- Controleer of er maar één bot-instantie per database draait
- WAL-modus zou dit grotendeels moeten voorkomen
- Als het blijft: stop de bot, controleer met `fuser data/*.db`

### Monitoring.db te groot
```bash
# Stop de bot eerst!
sqlite3 multi_coin_grid_pro/data/monitoring.db "VACUUM;"
# Start de bot weer
```

### Coin zit op blacklist/cooldown
```bash
sqlite3 data/cooldowns_usd.db "SELECT * FROM cooldowns WHERE expires_at > strftime('%s','now');"
```
Om een cooldown handmatig te verwijderen:
```bash
sqlite3 data/cooldowns_usd.db "DELETE FROM cooldowns WHERE symbol='COIN-USD';"
```

---

## 9. Belangrijke paden

```
/home/mo/repos/hummingbot/                    # Project root
├── bin/
│   ├── hummingbot.py                         # Interactieve start
│   └── hummingbot_quickstart.py              # Headless start (systemd)
├── multi_coin_grid_pro/
│   ├── controllers/
│   │   └── multi_coin_grid_controller.py     # Hoofdcontroller (alle logica)
│   ├── config/
│   │   ├── spot_grid_kraken_usd.yaml         # USD config
│   │   ├── spot_grid_kraken_eur.yaml         # EUR config
│   │   └── risk_monitor.yaml                 # Risk config
│   ├── spot_bitget/config/
│   │   └── spot_grid_bitget.yaml             # Bitget spot config
│   ├── futures_bitget/config/
│   │   └── futures_grid_bitget.yaml          # Bitget futures config
│   ├── persistence/
│   │   └── entry_price_store.py              # Entry price SQLite store
│   ├── monitoring/
│   │   ├── dashboard.py                      # Flask dashboard + /health
│   │   └── database.py                       # Monitoring DB + auto-prune
│   └── data/
│       └── monitoring.db                     # Monitoring database (320 MB)
├── data/
│   ├── cooldowns_usd.db                      # Cooldown database
│   ├── cooldowns_eur.db
│   ├── entry_prices_usd.db                   # Entry price database
│   ├── entry_prices_eur.db
│   ├── multi_coin_grid_v2.sqlite             # Hummingbot trade DB (EUR)
│   └── multi_coin_grid_v2_usd.sqlite         # Hummingbot trade DB (USD)
├── deploy/
│   ├── backup_dbs.sh                         # Dagelijkse backup (cron 03:00)
│   ├── cleanup_logs.sh                       # Log opschoning (cron 03:30)
│   └── systemd/                              # Systemd service templates
├── backups/db/                               # Database backups (7d retentie)
├── logs/                                     # Bot logs (3.2 GB)
├── docs/
│   ├── phases/MASTER_IMPLEMENTATION_PLAN.md  # Master plan v5
│   ├── IMPLEMENTATION_STATUS.md              # Wat er gebouwd is
│   └── OPERATIONS_GUIDE.md                   # Dit document
└── conf/                                     # Hummingbot framework configs
```

---

## Dagelijks onderhoud checklist

- [ ] Check of de bot draait: `ps aux | grep hummingbot`
- [ ] Bekijk recente errors: `tail -100 logs/logs_multi_coin_grid_v2_usd_*.log | grep -i error`
- [ ] Check backup log: `tail -1 /tmp/backup.log`
- [ ] Check cleanup log: `tail -1 /tmp/logclean.log`
- [ ] Disk usage: `df -h /home/mo` en `du -sh logs/ backups/`

## Wekelijks onderhoud

- [ ] VACUUM monitoring.db als deze > 200 MB is (stop bot eerst!)
- [ ] Controleer of de 7-dag backup retentie werkt: `ls -la backups/db/`
- [ ] Bekijk kill switch / drawdown events in de logs
- [ ] Review PnL en fill rates
