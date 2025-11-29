# Data Storage - Waar Wordt Alles Opgeslagen?

**Laatste Update:** 21-11-2025

---

## 📊 OVERZICHT

De bot gebruikt **3 soorten data storage**:

1. **In-Memory (RAM)** - Verloren bij restart
2. **SQLite Database** - Persistent, blijft behouden
3. **Config Files (YAML)** - Persistent, blijft behouden

---

## 🧠 IN-MEMORY DATA (Verloren bij Restart)

### 1. Trend Data (`TrendCalculator`)
**Locatie:** `self.trend_calculator.trends: Dict[str, CoinTrend]`

**Wat wordt opgeslagen:**
- `price_history`: List van {price, timestamp} dicts (laatste 24 uur)
- `current_price`: Huidige prijs
- `trend_pct`: Trend percentage
- `trend_60m`, `trend_240m`, `trend_1440m`: Multi-timeframe trends
- `trend_score`: Composite score
- `volatility`: Rolling standard deviation
- `last_updated`: Timestamp van laatste update

**Voorbeeld:**
```python
trends = {
    "BTC-EUR": CoinTrend(
        symbol="BTC-EUR",
        price_history=[{price: 50000, timestamp: 1234567890}, ...],
        trend_pct=2.5,
        trend_60m=1.2,
        trend_240m=2.1,
        trend_1440m=2.5,
        ...
    ),
    ...
}
```

**Verlies bij restart:** ✅ **JA** - Alle trend data wordt opnieuw opgebouwd

---

### 2. Coin Performance Tracking (`MultiCoinGridController`)
**Locatie:** `self.coin_performance: Dict[str, int]`

**Wat wordt opgeslagen:**
- Counter per coin: hoeveel updates zonder trades
- Gebruikt voor coin rotation

**Voorbeeld:**
```python
coin_performance = {
    "BTC-EUR": 45,  # 45 updates zonder trades
    "ETH-EUR": 12,  # 12 updates zonder trades
    ...
}
```

**Verlies bij restart:** ✅ **JA** - Counters worden gereset

---

### 3. Pair Volumes & Spreads (`MultiCoinGridController`)
**Locatie:**
- `self.pair_volumes: Dict[str, float]` - 24h volumes per pair
- `self.pair_spreads: Dict[str, float]` - Spreads per pair

**Wat wordt opgeslagen:**
- 24h volume data voor alle beschikbare pairs
- Spread data voor coin discovery

**Voorbeeld:**
```python
pair_volumes = {
    "BTC-EUR": 50000000.0,  # €50M volume
    "ETH-EUR": 30000000.0,  # €30M volume
    ...
}
pair_spreads = {
    "BTC-EUR": 0.0001,  # 0.01% spread
    "ETH-EUR": 0.0002,  # 0.02% spread
    ...
}
```

**Verlies bij restart:** ✅ **JA** - Wordt opnieuw opgehaald bij startup

---

### 4. Monitored Coins List (`MultiCoinGridController`)
**Locatie:** `self.monitored_coins: List[str]`

**Wat wordt opgeslagen:**
- Lijst van 50 coins die worden gemonitord
- Wordt bepaald bij startup op basis van volume/spread

**Voorbeeld:**
```python
monitored_coins = ["BTC-EUR", "ETH-EUR", "SOL-EUR", ...]
```

**Verlies bij restart:** ✅ **JA** - Wordt opnieuw bepaald bij startup

---

## 💾 PERSISTENT DATA (SQLite Database)

### 1. Trades (`TradeFill` Table)
**Locatie:** `data/multi_coin_grid_v2.sqlite` (of andere database)

**Wat wordt opgeslagen:**
- Alle trades (buy/sell)
- Prijs, hoeveelheid, fees
- Timestamp, order ID
- Trading pair, base/quote asset

**Database Schema:**
```sql
CREATE TABLE TradeFill (
    config_file_path TEXT,
    strategy TEXT,
    market TEXT,
    symbol TEXT,
    base_asset TEXT,
    quote_asset TEXT,
    timestamp BIGINT,
    order_id TEXT,
    trade_type TEXT,
    order_type TEXT,
    price DECIMAL(6),
    amount DECIMAL(6),
    trade_fee JSON,
    trade_fee_in_quote DECIMAL(6),
    exchange_trade_id TEXT,
    position TEXT
)
```

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

**Toegang:**
```python
# Via Hummingbot's database
from hummingbot.model.trade_fill import TradeFill
trades = session.query(TradeFill).filter_by(strategy="multi_coin_grid_v2").all()
```

---

### 2. Orders (`Order` Table)
**Locatie:** `data/multi_coin_grid_v2.sqlite`

**Wat wordt opgeslagen:**
- Alle orders (open, filled, cancelled)
- Order status, type, side
- Timestamps, prices, amounts

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

---

### 3. Positions (`Position` Table)
**Locatie:** `data/multi_coin_grid_v2.sqlite`

**Wat wordt opgeslagen:**
- Huidige posities per executor
- Unrealized PnL
- Breakeven price
- Volume traded, fees

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

---

### 4. Market Data (`MarketData` Table)
**Locatie:** `data/multi_coin_grid_v2.sqlite`

**Wat wordt opgeslagen:**
- Order book snapshots
- Best bid/ask prices
- Mid prices

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

---

## 📝 CONFIG FILES (YAML)

### 1. Blacklist (`multi_coin_grid.yml`)
**Locatie:** `multi_coin_grid_pro/config/multi_coin_grid.yml`

**Wat wordt opgeslagen:**
- Blacklisted coins
- Wordt automatisch bijgewerkt bij auto-blacklisting

**Voorbeeld:**
```yaml
blacklist:
  - GIGA-EUR
  - USELESS-EUR
  - 0G-EUR
  ...
```

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

---

### 2. Settings (`multi_coin_grid.yml`)
**Locatie:** `multi_coin_grid_pro/config/multi_coin_grid.yml`

**Wat wordt opgeslagen:**
- Alle configuratie instellingen
- Volume thresholds, trend settings
- Grid configuratie, risk management

**Verlies bij restart:** ❌ **NEE** - Blijft behouden

---

## 🔄 DATA LIFECYCLE

### Bij Bot Start:
1. ✅ **Config laden** uit YAML
2. ✅ **Database connecten** (SQLite)
3. ❌ **Trend data** - Leeg, wordt opgebouwd
4. ❌ **Coin performance** - Leeg, wordt getrackt
5. ✅ **Coin discovery** - Opnieuw uitgevoerd

### Tijdens Runtime:
1. ✅ **Trend data** - Wordt elke ~10 seconden bijgewerkt
2. ✅ **Coin performance** - Wordt elke update getrackt
3. ✅ **Trades** - Wordt direct naar database geschreven
4. ✅ **Orders** - Wordt direct naar database geschreven
5. ✅ **Blacklist** - Wordt bijgewerkt bij auto-blacklisting

### Bij Bot Restart:
1. ✅ **Config** - Blijft behouden
2. ✅ **Database** - Blijft behouden (trades, orders, positions)
3. ❌ **Trend data** - Verloren, wordt opnieuw opgebouwd
4. ❌ **Coin performance** - Verloren, wordt gereset
5. ✅ **Coin discovery** - Wordt opnieuw uitgevoerd

---

## 📊 DATA VOLUME

### In-Memory:
- **Trend data:** ~50 coins × ~100 datapunten × ~50 bytes = ~250 KB
- **Coin performance:** ~50 coins × 4 bytes = ~200 bytes
- **Pair volumes:** ~200 pairs × 8 bytes = ~1.6 KB
- **Totaal:** ~252 KB (zeer klein)

### Database:
- **Trades:** ~1 KB per trade
- **Orders:** ~500 bytes per order
- **Positions:** ~200 bytes per position
- **Geschat:** ~10-100 MB na maanden draaien

---

## ⚠️ BELANGRIJKE PUNTEN

### 1. Trend Data Verlies
**Probleem:** Trend data wordt verloren bij restart
**Impact:** Bot moet ~10-20 minuten wachten voor voldoende data
**Oplossing:** Geen (by design - trends zijn real-time)

### 2. Coin Performance Reset
**Probleem:** Coin performance counters worden gereset
**Impact:** Coin rotation werkt niet direct na restart
**Oplossing:** Geen (by design - counters zijn runtime-only)

### 3. Database Groei
**Probleem:** Database groeit continu
**Impact:** Kan groot worden na maanden
**Oplossing:** Periodieke cleanup (niet geïmplementeerd)

---

## 🔍 TOEGANG TOT DATA

### Trades Analyseren:
```bash
# Via script
python multi_coin_grid_pro/scripts/analyze_trades_sqlite.py --hours 24

# Via Hummingbot CLI
history --days 1
```

### Database Locatie:
```bash
# Standaard locatie
data/multi_coin_grid_v2.sqlite

# Of via config
data/{config_name}.sqlite
```

### Config Bestand:
```bash
# Config locatie
multi_coin_grid_pro/config/multi_coin_grid.yml
```

---

## 💡 AANBEVELINGEN

### 1. Backup Database
**Aanbevolen:** Maak regelmatig backup van SQLite database
```bash
cp data/multi_coin_grid_v2.sqlite backups/multi_coin_grid_v2_$(date +%Y%m%d).sqlite
```

### 2. Monitor Database Grootte
**Aanbevolen:** Check regelmatig database grootte
```bash
ls -lh data/*.sqlite
```

### 3. Trend Data (Optioneel)
**Mogelijk:** Persistent maken van trend data (niet geïmplementeerd)
- Voordeel: Snellere startup
- Nadeel: Oude data kan misleidend zijn

---

**Gegenereerd:** 21-11-2025
**Database Locatie:** `data/multi_coin_grid_v2.sqlite`
**Config Locatie:** `multi_coin_grid_pro/config/multi_coin_grid.yml`
