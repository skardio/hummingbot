# TODO: Bitget Volume Data Workaround

## Probleem
Bitget connector in Hummingbot levert geen 24h volume/spread data via standaard API.
Dit blokkeert volume-based coin filtering in dynamic discovery.

## Oplossing: Externe Volume Cache (Workaround)
Implementeer een standalone volume-fetcher die elke 5-10 minuten Bitget ticker data ophaalt
en cached, zodat de bot deze kan gebruiken voor coin pre-filtering.

---

## Implementatie Stappen

### 1. Volume Fetcher Script (`multi_coin_grid_pro/utils/bitget_volume_fetcher.py`)

**Functionaliteit:**
- Haalt 24h volume op via Bitget REST API: `/api/spot/v1/market/tickers`
- Optioneel: Fallback naar CoinGecko API (rate-limited)
- Cached data naar JSON: `/tmp/bitget_volumes.json` of `~/.hummingbot/cache/bitget_volumes.json`
- Refresh interval: 5-10 minuten

**Data formaat (JSON):**
```json
{
  "timestamp": 1702837200,
  "pairs": {
    "BTC-USDT": {
      "volume_24h": 1234567.89,
      "volume_quote": 85000000000,
      "last_price": 42000.50,
      "spread": 0.0012,
      "bid": 41995.00,
      "ask": 42005.00
    },
    "ETH-USDT": { ... }
  }
}
```

**API Endpoint:**
```
GET https://api.bitget.com/api/spot/v1/market/tickers
Response: List van { symbol, vol, close, bid1, ask1, ... }
```

---

### 2. Background Task (Optional maar Recommended)

**Optie A: Systemd Service**
- Maak systemd timer die script elke 5 min draait
- Service: `/etc/systemd/system/bitget-volume-fetcher.service`
- Timer: `/etc/systemd/system/bitget-volume-fetcher.timer`

**Optie B: Cron Job**
```bash
*/5 * * * * /home/mo/repos/hummingbot/venv/bin/python /home/mo/repos/hummingbot/multi_coin_grid_pro/utils/bitget_volume_fetcher.py
```

**Optie C: Threading in Bot (Eenvoudigst)**
- Start thread in controller __init__
- Thread fetcht elke 5 min op achtergrond
- Schrijft naar cache file

---

### 3. Integreer Cache in Coin Discovery

**Locatie:** `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
**Functie:** `_discover_coins_from_exchange()`
**Lijn:** ~1100-1200

**Huidige flow:**
1. Get trading pairs van connector
2. Try get ticker_data (faalt bij Bitget)
3. Build pair_volumes (blijft leeg)
4. Fallback: gebruik alle pairs zonder filter

**Nieuwe flow:**
1. Get trading pairs van connector
2. Try get ticker_data (faalt bij Bitget)
3. **IF ticker_data empty: Try load from cache file**
4. Build pair_volumes van cache data
5. Filter op volume zoals normaal

**Code wijziging:**
```python
# Na regel ~1135 waar ticker_data wordt opgehaald:
if not ticker_data or len(ticker_data) == 0:
    # Try load from external cache
    cache_file = os.path.expanduser("~/.hummingbot/cache/bitget_volumes.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            # Check if cache is fresh (< 15 min old)
            cache_age = time.time() - cache_data.get('timestamp', 0)
            if cache_age < 900:  # 15 minutes
                self.logger().info(f"✅ Using cached volume data (age: {cache_age:.0f}s)")

                # Build pair_volumes from cache
                for pair, data in cache_data.get('pairs', {}).items():
                    if pair in eur_pairs:  # Only USDT pairs we care about
                        pair_volumes[pair] = data.get('volume_quote', 0)

                        # Also store spread if available
                        if 'spread' in data:
                            pair_spreads[pair] = data['spread']
            else:
                self.logger().warning(f"⚠️  Cache too old ({cache_age:.0f}s), skipping")
        except Exception as e:
            self.logger().warning(f"⚠️  Failed to load volume cache: {e}")
```

---

## Referentie: Bitget API Documentatie

**Base URL:** `https://api.bitget.com`

**Endpoint:** `/api/spot/v1/market/tickers`
- Method: GET
- Rate Limit: 20 requests/second
- Auth: Niet nodig voor public market data

**Response voorbeeld:**
```json
{
  "code": "00000",
  "msg": "success",
  "data": [
    {
      "symbol": "BTCUSDT",
      "high24h": "43500.00",
      "low24h": "41800.00",
      "open": "42100.00",
      "close": "42350.50",
      "quoteVol": "850000000.00",
      "baseVol": "20100.50",
      "ts": "1702837200000",
      "bidPr": "42345.00",
      "askPr": "42355.00",
      "openUtc": "42200.00"
    }
  ]
}
```

**Mapping naar Hummingbot format:**
- `symbol`: "BTCUSDT" → "BTC-USDT"
- `quoteVol`: 24h volume in quote currency (USDT)
- `close`: Last price
- `bidPr`: Best bid
- `askPr`: Best ask

---

## Testing

### Test 1: Verify API Access
```bash
curl -X GET "https://api.bitget.com/api/spot/v1/market/tickers" | jq '.data | length'
# Should return ~750 pairs
```

### Test 2: Manual Script Run
```bash
python multi_coin_grid_pro/utils/bitget_volume_fetcher.py
cat ~/.hummingbot/cache/bitget_volumes.json | jq '.pairs | length'
# Should show cached pairs
```

### Test 3: Bot Integration
```bash
# Start bot, check logs for:
# "✅ Using cached volume data (age: XXXs)"
# "📊 Found N USDT pairs with volume > 50,000"
```

---

## Prioriteit: MEDIUM
- Bot werkt nu met fallback (alle coins, geen volume filter)
- Volume filtering is nice-to-have, niet kritisch
- Implementeer wanneer je volume-based selection wilt

---

## Geschatte Tijd: 2-3 uur
- 1h: Volume fetcher script + testing
- 30m: Systemd/cron setup
- 1h: Integratie in controller + testing

---

## Alternatief: CoinGecko API
Als Bitget API problemen geeft, gebruik CoinGecko:
- Endpoint: `https://api.coingecko.com/api/v3/coins/markets`
- Params: `vs_currency=usdt&order=volume_desc`
- Rate limit: 10-50 calls/min (free tier)
- Pro: Universeel, betrouwbaar
- Con: Langzamer, rate-limited

---

## Notities
- Cache file locatie: `~/.hummingbot/cache/bitget_volumes.json`
- Fallback blijft actief: als cache fails → gebruik alle pairs
- Thread-safe: gebruik file locking bij schrijven (fcntl.flock)
- Log volume data age in bot voor debugging

---

**Status:** TODO
**Created:** 2025-12-17
**Priority:** MEDIUM
**Effort:** 2-3 hours
