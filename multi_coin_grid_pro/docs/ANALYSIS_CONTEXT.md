 # 🔍 Analysis Context Document

Dit document bevat alle paden, locaties en commando's die nodig zijn voor analyse van de multi-coin grid trading bots.

---

## 📂 Workspace Structuur

```
/home/mo/repos/hummingbot/
├── multi_coin_grid_pro/          # Hoofd strategie code
│   ├── controllers/              # Controller logic
│   ├── utils/                    # Utilities (trend_calculator, etc.)
│   ├── filters/                  # SmartEntry, time-based filters
│   ├── core/                     # Core components (reason_codes, etc.)
│   ├── persistence/              # SQLite stores (cooldowns, etc.)
│   ├── observability/            # Event logging, metrics
│   ├── config/                   # Kraken configs
│   ├── spot_bitget/config/       # Bitget configs
│   ├── data/                     # Monitoring database
│   └── tests/                    # Unit/integration tests
├── logs/                         # Alle log files
├── data/                         # SQLite databases
└── hummingbot/                   # Hummingbot core framework
```

---

## 🤖 Bot Configuraties

### Bot 1: Kraken EUR
| Item | Locatie |
|------|---------|
| **Config** | `/home/mo/repos/hummingbot/multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml` |
| **Log (current)** | `/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2026-01-16-23-31-07.log` |
| **Log (rotated)** | `logs/logs_multi_coin_grid_v2_2026-01-16-23-31-07.log.1` ... `.log.4` |
| **Report** | `/home/mo/repos/hummingbot/logs/kraken_multi_coin_grid_report_20260116.log` |
| **Quote Asset** | EUR |
| **Connector** | `kraken` |

### Bot 2: Bitget USDT
| Item | Locatie |
|------|---------|
| **Config** | `/home/mo/repos/hummingbot/multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml` |
| **Log (current)** | `/home/mo/repos/hummingbot/logs/logs_spot_grid_bitget_2026-01-16-23-31-48.log` |
| **Log (rotated)** | `logs/logs_spot_grid_bitget_2026-01-16-23-31-48.log.1` ... `.log.4` |
| **Report** | `/home/mo/repos/hummingbot/logs/bitget_multi_coin_grid_report_20260116.log` |
| **Quote Asset** | USDT |
| **Connector** | `bitget` |

---

## 📊 Log Files

### Belangrijke Log Locaties

```bash
# Alle multi-coin grid logs
ls -la /home/mo/repos/hummingbot/logs/*multi_coin*.log*
ls -la /home/mo/repos/hummingbot/logs/*grid*.log*

# Rotated logs (oudste data = hoogste nummer)
# .log     = meest recent
# .log.1   = 1 rotatie geleden
# .log.2   = 2 rotaties geleden
# .log.4   = oudste (4 rotaties geleden)
```

### Log File Grootte (per file ~20MB, roteert automatisch)

| Log Type | Pattern | Max Size |
|----------|---------|----------|
| Kraken main | `logs_multi_coin_grid_v2_*.log*` | ~20MB per file |
| Bitget main | `logs_spot_grid_bitget_*.log*` | ~20MB per file |
| Reports | `*_report_*.log` | Variable |

---

## 🗄️ Databases

### Monitoring Database
```
/home/mo/repos/hummingbot/multi_coin_grid_pro/data/monitoring.db
```

**Tables:**
- `trades` - Trade history
- `performance` - PnL tracking
- `events` - System events

### Cooldown Store
```
/home/mo/repos/hummingbot/data/cooldowns.db
```

**Tables:**
- `cooldowns` - Parabolic/loss cooldowns per coin

### Main Hummingbot Database
```
/home/mo/repos/hummingbot/data/spot_grid_bitget.sqlite
/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite
```

---

## 📝 Events & Audits

### Event Logs (JSONL format)
```
/home/mo/repos/hummingbot/logs/events/events_YYYYMMDD_HHMMSS.jsonl
```

### Query Events
```bash
# Recent events
tail -100 /home/mo/repos/hummingbot/logs/events/events_*.jsonl

# Filter by type
grep "gate_denied" /home/mo/repos/hummingbot/logs/events/events_*.jsonl
grep "trade_executed" /home/mo/repos/hummingbot/logs/events/events_*.jsonl
```

---

## 🔧 Nuttige Analyse Commando's

### Log Analyse

```bash
# === FILLS/TRADES ===
# Tel fills per bot
grep -iE "FILL|filled|OrderFilledEvent" logs/logs_spot_grid_bitget_*.log* | wc -l
grep -iE "FILL|filled|OrderFilledEvent" logs/logs_multi_coin_grid_v2_*.log* | wc -l

# === CANDLE DATA ISSUES ===
# Check insufficient candle warnings
grep -E "Insufficient candle data" logs/logs_multi_coin_grid_v2_*.log* | head -20

# === COIN ROTATION ===
# Bekijk coin swaps
grep -E "→|SWAP|rotate" logs/logs_multi_coin_grid_v2_*.log* | head -20

# === HISTORICAL DATA LOADING ===
grep -E "LOADING HISTORICAL|Historical data loaded" logs/logs_multi_coin_grid_v2_*.log*

# === STARTUP EVENTS ===
head -100 logs/logs_multi_coin_grid_v2_*.log.4  # Oudste log = startup

# === ERRORS ===
grep -iE "ERROR|Exception|Failed" logs/logs_multi_coin_grid_v2_*.log | tail -50

# === SMARTENTRY REJECTIONS ===
grep -E "SmartEntry.*rejected|🧠.*Insufficient" logs/logs_multi_coin_grid_v2_*.log | tail -20

# === NETWORK/CONNECTION ===
grep -E "NetworkStatus|CONNECTED|reconnect" logs/logs_multi_coin_grid_v2_*.log | wc -l
```

### Database Queries

```bash
# === TRADES AFGELOPEN 7 DAGEN ===
sqlite3 multi_coin_grid_pro/data/monitoring.db \
  "SELECT COUNT(*) FROM trades WHERE timestamp > datetime('now', '-7 days')"

# === ACTIVE COOLDOWNS ===
sqlite3 data/cooldowns.db "SELECT * FROM cooldowns WHERE expires_at > datetime('now')"

# === RECENT TRADES ===
sqlite3 multi_coin_grid_pro/data/monitoring.db \
  "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10"
```

---

## 🎯 Key Config Parameters

### Kraken Config Highlights
```yaml
# /home/mo/repos/hummingbot/multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml
use_dynamic_pair_discovery: true
manual_trading_pairs: []  # Empty = dynamic mode
coin_rotation_threshold: 180  # Rotates underperforming coins
coin_discovery_refresh_interval_seconds: 3600  # 1 hour
```

### Bitget Config Highlights
```yaml
# /home/mo/repos/hummingbot/multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
use_dynamic_pair_discovery: true
manual_trading_pairs: []  # Empty = dynamic mode
coin_rotation_threshold: 180
coin_discovery_refresh_interval_seconds: 3600
```

---

## 🐛 Bekende Issues & Fixes

### Issue 1: Insufficient Candle Data After Rotation
**Symptoom:** `Insufficient candle data for SmartEntry v2 (X candles)`
**Oorzaak:** Coin rotatie voegt nieuwe coins toe zonder historische data
**Fix:** `_ensure_historical_data_loaded()` in controller (auto-laadt data na rotatie)
**Locatie:** `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:2220`

### Issue 2: Historical Data Not Checked Correctly
**Symptoom:** Historical data wordt niet geladen voor nieuwe coins
**Oorzaak:** Check was op `price_history` ipv `candles`
**Fix:** Check nu op `len(candles) < 14`
**Locatie:** `multi_coin_grid_pro/utils/trend_calculator.py:260`

---

## 📈 Performance Vergelijking

| Metric | Bitget | Kraken |
|--------|--------|--------|
| Fills (laatste run) | 8,151 | 469 |
| "Insufficient candle" warnings | 9 | Duizenden |
| Coin rotatie | Minder actief | Actief (elke ~3u) |

---

## 🧪 Test Commands

```bash
# Run alle tests
cd /home/mo/repos/hummingbot
pytest multi_coin_grid_pro/tests/ -v

# Run specifieke test
pytest multi_coin_grid_pro/tests/utils/test_staleness_guard.py -v

# Run met coverage
pytest multi_coin_grid_pro/tests/ --cov=multi_coin_grid_pro --cov-report=html
```

---

## 📁 Key Code Files

| Component | File |
|-----------|------|
| **Main Controller** | `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` |
| **Config Model** | `multi_coin_grid_pro/controllers/multi_coin_grid_config.py` |
| **Trend Calculator** | `multi_coin_grid_pro/utils/trend_calculator.py` |
| **SmartEntry Filter** | `multi_coin_grid_pro/filters/smart_entry_filter.py` |
| **Reason Codes** | `multi_coin_grid_pro/core/reason_codes.py` |
| **Event Logger** | `multi_coin_grid_pro/observability/event_logger.py` |
| **Staleness Guard** | `multi_coin_grid_pro/utils/staleness_guard.py` |
| **Config Validator** | `multi_coin_grid_pro/utils/config_validator.py` |
| **Pair Health Monitor** | `multi_coin_grid_pro/utils/pair_health_monitor.py` |
| **Trace Generator** | `multi_coin_grid_pro/utils/trace_generator.py` |

---

## 🔄 Update dit document

Wanneer je nieuwe locaties ontdekt of de structuur verandert, update dit document:

```bash
# Dit document bewerken
code /home/mo/repos/hummingbot/multi_coin_grid_pro/docs/ANALYSIS_CONTEXT.md
```

---

*Laatste update: 2026-01-17*
