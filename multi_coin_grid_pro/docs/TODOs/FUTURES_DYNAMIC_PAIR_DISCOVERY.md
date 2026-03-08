# 🔍 Futures Dynamic Pair Discovery - Technisch Voorstel

> **Datum**: 8 februari 2026
> **Status**: VOORSTEL (awaiting review)
> **Auteur**: GitHub Copilot
> **Reviewer**: Mo

---

## 📋 Inhoudsopgave

1. [Probleem](#probleem)
2. [Doelstellingen](#doelstellingen)
3. [Architectuur Overzicht](#architectuur-overzicht)
4. [Bitget API Analyse](#bitget-api-analyse)
5. [Filter Criteria](#filter-criteria)
6. [Implementatie Plan](#implementatie-plan)
7. [Config Wijzigingen](#config-wijzigingen)
8. [Fallback Mechanisme](#fallback-mechanisme)
9. [Risico's & Mitigatie](#risicos--mitigatie)
10. [Tijdslijn](#tijdslijn)

---

## 🔴 Probleem

### Huidige Situatie

De futures bot gebruikt een **hardcoded lijst** van 40+ trading pairs:

```yaml
manual_trading_pairs:
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
  # ... 40+ pairs
```

### Nadelen

| Probleem | Impact |
|----------|--------|
| **Statische lijst** | Mist nieuwe trending coins (memes, AI tokens) |
| **Geen volume filtering** | Kan illiquide pairs selecteren |
| **Handmatig onderhoud** | Moet config updaten voor nieuwe coins |
| **Geen Open Interest check** | Mist high-activity futures opportunities |
| **Geen funding rate awareness** | Kan pairs met extreme funding kiezen |

### Gewenste Situatie

Dynamische discovery die:
- Automatisch alle USDT perpetual pairs ophaalt van Bitget
- Filtert op volume, open interest, en spread
- Valt terug op de handmatige lijst bij API failures
- Periodiek (bijv. elke 1 uur) de pool ververst

---

## 🎯 Doelstellingen

### Must Have (P0)
1. ✅ Automatisch alle USDT-FUTURES pairs ophalen van Bitget API
2. ✅ Filteren op 24h volume (min $1M voor futures)
3. ✅ Fallback naar `manual_trading_pairs` bij API failure
4. ✅ Blacklist support (exclude specifieke pairs)
5. ✅ Caching om API rate limits te respecteren

### Should Have (P1)
6. 🟡 Filteren op Open Interest (min $10M OI = liquide markt)
7. 🟡 Filteren op spread (max 0.1% voor perps)
8. 🟡 Funding rate awareness (geen extreme funding pairs)

### Could Have (P2)
9. ⚪ Hot coin detection (pairs met >50% volume spike)
10. ⚪ New listing detection (eerste 7 dagen = hoge volatiliteit)

---

## 🏗️ Architectuur Overzicht

```
┌─────────────────────────────────────────────────────────────────┐
│                    FuturesGridBitgetController                   │
│                                                                  │
│  ┌─────────────────────┐      ┌─────────────────────────────┐   │
│  │ FuturesPairDiscovery│◀────▶│  Bitget Perpetual API       │   │
│  │                     │      │  /api/v2/mix/market/...     │   │
│  │  - fetch_all_pairs()│      └─────────────────────────────┘   │
│  │  - filter_by_volume │                                        │
│  │  - filter_by_oi     │      ┌─────────────────────────────┐   │
│  │  - apply_blacklist  │      │  Cache Layer (5 min TTL)    │   │
│  │  - fallback_manual  │◀────▶│  - contracts_cache          │   │
│  └─────────────────────┘      │  - tickers_cache            │   │
│            │                   │  - oi_cache                 │   │
│            ▼                   └─────────────────────────────┘   │
│  ┌─────────────────────┐                                        │
│  │ monitored_coins     │◀─── Final filtered list                │
│  │ (dynamic or manual) │                                        │
│  └─────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📡 Bitget API Analyse

### Beschikbare Endpoints

| Endpoint | Data | Rate Limit | Gebruik |
|----------|------|------------|---------|
| `/api/v2/mix/market/contracts` | Alle perpetual contracts | 20/sec | Pair list + trading rules |
| `/api/v2/mix/market/tickers` | 24h volume, last price | 20/sec | Volume filtering |
| `/api/v2/mix/market/open-interest` | Open Interest per symbol | 20/sec | Liquiditeit check |
| `/api/v2/mix/market/current-fund-rate` | Current funding rate | 20/sec | Funding awareness |

### API Response Voorbeelden

#### 1. Contracts Endpoint
```json
GET /api/v2/mix/market/contracts?productType=USDT-FUTURES

{
  "code": "00000",
  "data": [
    {
      "symbol": "BTCUSDT",
      "baseCoin": "BTC",
      "quoteCoin": "USDT",
      "minTradeNum": "0.001",
      "maxSymbolOrderNum": "300",
      "maxProductOrderNum": "600",
      "volumePlace": "3",
      "pricePlace": "1",
      "supportMarginCoins": ["USDT"],
      "status": "normal"  // ← Alleen "normal" pairs!
    }
  ]
}
```

#### 2. Tickers Endpoint (Volume)
```json
GET /api/v2/mix/market/tickers?productType=USDT-FUTURES

{
  "code": "00000",
  "data": [
    {
      "symbol": "BTCUSDT",
      "lastPr": "97500.5",
      "askPr": "97500.6",
      "bidPr": "97500.4",
      "baseVolume": "12500.5",       // 24h BTC volume
      "quoteVolume": "1218797500.0", // 24h USDT volume ← FILTER OP DIT!
      "high24h": "98500.0",
      "low24h": "96000.0",
      "change24h": "0.0156"
    }
  ]
}
```

#### 3. Open Interest Endpoint
```json
GET /api/v2/mix/market/open-interest?productType=USDT-FUTURES&symbol=BTCUSDT

{
  "code": "00000",
  "data": {
    "symbol": "BTCUSDT",
    "amount": "45000.5",    // OI in BTC
    "value": "4387548750"   // OI in USDT ← FILTER OP DIT!
  }
}
```

### Rate Limit Strategie

- **Contracts**: 1x bij startup + 1x per uur refresh
- **Tickers**: 1x per 5 minuten (cachen)
- **Open Interest**: 1x per 10 minuten (optioneel, P1)
- **Funding Rate**: Al geïmplementeerd in Sprint 2

**Totaal**: ~15 API calls/uur = ruim binnen limits (20/sec)

---

## 🎚️ Filter Criteria

### Voorgestelde Filters (in volgorde)

```
1. PRODUCT TYPE = "USDT-FUTURES"
   └── Alleen USDT margined perpetuals

2. STATUS = "normal"
   └── Exclude delisted/suspended pairs

3. 24H VOLUME >= $1,000,000
   └── Liquiditeit garantie
   └── Config: min_24h_volume_usdt

4. SPREAD <= 0.1%
   └── Betere execution
   └── Config: max_spread_pct

5. NOT IN BLACKLIST
   └── Manual exclusions
   └── Config: blacklist

6. (Optioneel P1) OPEN INTEREST >= $10,000,000
   └── Active trading
   └── Config: min_open_interest_usdt

7. (Optioneel P2) FUNDING RATE <= 0.1%
   └── Geen extreme funding
   └── Al geïmplementeerd in Sprint 2!
```

### Volume Tiers

| Tier | Volume Range | Verwachte Pairs | Use Case |
|------|--------------|-----------------|----------|
| **Mega** | >$100M | ~5-10 | BTC, ETH, SOL |
| **Large** | $10M-$100M | ~20-30 | Top altcoins |
| **Medium** | $1M-$10M | ~50-100 | Mid-caps, memes |
| **Small** | <$1M | ~100+ | ❌ Te illiquide |

**Aanbeveling**: Start met `min_24h_volume_usdt: 1000000` ($1M)

---

## 📦 Implementatie Plan

### Nieuwe Files

```
multi_coin_grid_pro/
└── futures_bitget/
    ├── pair_discovery.py    # 🆕 FuturesPairDiscovery class
    ├── controller.py        # Wijzigen: integrate discovery
    └── config_schema.py     # Wijzigen: nieuwe config params
```

### FuturesPairDiscovery Class

```python
# multi_coin_grid_pro/futures_bitget/pair_discovery.py

class FuturesPairDiscovery:
    """
    Dynamische pair discovery voor Bitget Perpetual Futures.

    Features:
    - Haalt alle USDT-FUTURES contracts op
    - Filtert op volume, spread, OI
    - Cache met TTL om rate limits te respecteren
    - Fallback naar manual_trading_pairs
    """

    CONTRACTS_ENDPOINT = "/api/v2/mix/market/contracts"
    TICKERS_ENDPOINT = "/api/v2/mix/market/tickers"
    OI_ENDPOINT = "/api/v2/mix/market/open-interest"

    CACHE_TTL_CONTRACTS = 3600  # 1 hour
    CACHE_TTL_TICKERS = 300     # 5 minutes

    def __init__(
        self,
        connector: BitgetPerpetualDerivative,
        config: FuturesGridBitgetConfig,
        logger: logging.Logger
    ):
        self.connector = connector
        self.config = config
        self.logger = logger

        # Cache
        self._contracts_cache: Optional[List[dict]] = None
        self._contracts_cache_time: float = 0
        self._tickers_cache: Optional[Dict[str, dict]] = None
        self._tickers_cache_time: float = 0

    async def discover_pairs(self) -> List[str]:
        """
        Discover and filter trading pairs.

        Returns:
            List of trading pairs (e.g., ["BTC-USDT", "ETH-USDT", ...])
            Falls back to manual_trading_pairs on error.
        """
        try:
            # 1. Fetch all contracts
            contracts = await self._get_contracts()

            # 2. Fetch ticker data (volumes)
            tickers = await self._get_tickers()

            # 3. Apply filters
            filtered = self._apply_filters(contracts, tickers)

            if not filtered:
                self.logger.warning("⚠️ No pairs after filtering, using fallback")
                return self._get_fallback_pairs()

            self.logger.info(
                f"✅ Discovered {len(filtered)} futures pairs "
                f"(from {len(contracts)} total)"
            )
            return filtered

        except Exception as e:
            self.logger.error(f"❌ Discovery failed: {e}, using fallback")
            return self._get_fallback_pairs()

    async def _get_contracts(self) -> List[dict]:
        """Fetch all USDT-FUTURES contracts with caching."""
        now = time.time()
        if (self._contracts_cache and
            now - self._contracts_cache_time < self.CACHE_TTL_CONTRACTS):
            return self._contracts_cache

        response = await self.connector._api_get(
            path_url=self.CONTRACTS_ENDPOINT,
            params={"productType": "USDT-FUTURES"}
        )

        if response.get("code") != "00000":
            raise Exception(f"API error: {response.get('msg')}")

        self._contracts_cache = response.get("data", [])
        self._contracts_cache_time = now
        return self._contracts_cache

    async def _get_tickers(self) -> Dict[str, dict]:
        """Fetch all tickers with caching."""
        now = time.time()
        if (self._tickers_cache and
            now - self._tickers_cache_time < self.CACHE_TTL_TICKERS):
            return self._tickers_cache

        response = await self.connector._api_get(
            path_url=self.TICKERS_ENDPOINT,
            params={"productType": "USDT-FUTURES"}
        )

        if response.get("code") != "00000":
            raise Exception(f"API error: {response.get('msg')}")

        # Convert to dict keyed by symbol
        self._tickers_cache = {
            t["symbol"]: t for t in response.get("data", [])
        }
        self._tickers_cache_time = now
        return self._tickers_cache

    def _apply_filters(
        self,
        contracts: List[dict],
        tickers: Dict[str, dict]
    ) -> List[str]:
        """Apply all configured filters."""

        min_volume = getattr(self.config, 'min_24h_volume_usdt', 1_000_000)
        max_spread = getattr(self.config, 'max_spread_pct', 0.1)
        blacklist = set(getattr(self.config, 'blacklist', []))

        results = []

        for contract in contracts:
            symbol = contract.get("symbol", "")

            # Must be USDT pair and active
            if not symbol.endswith("USDT"):
                continue
            if contract.get("status") != "normal":
                continue

            # Convert to Hummingbot format: BTCUSDT → BTC-USDT
            base = contract.get("baseCoin", "")
            trading_pair = f"{base}-USDT"

            # Check blacklist
            if trading_pair in blacklist:
                self.logger.debug(f"  ❌ {trading_pair}: blacklisted")
                continue

            # Check volume
            ticker = tickers.get(symbol, {})
            volume = float(ticker.get("quoteVolume", 0))
            if volume < min_volume:
                self.logger.debug(
                    f"  ❌ {trading_pair}: volume ${volume/1e6:.1f}M < "
                    f"${min_volume/1e6:.1f}M"
                )
                continue

            # Check spread
            bid = float(ticker.get("bidPr", 0))
            ask = float(ticker.get("askPr", 0))
            if bid > 0:
                spread_pct = (ask - bid) / bid * 100
                if spread_pct > max_spread:
                    self.logger.debug(
                        f"  ❌ {trading_pair}: spread {spread_pct:.3f}% > "
                        f"{max_spread}%"
                    )
                    continue

            # Passed all filters!
            results.append(trading_pair)
            self.logger.debug(
                f"  ✅ {trading_pair}: vol=${volume/1e6:.1f}M, "
                f"spread={spread_pct:.3f}%"
            )

        # Sort by volume descending
        results.sort(
            key=lambda p: float(
                tickers.get(p.replace("-", ""), {}).get("quoteVolume", 0)
            ),
            reverse=True
        )

        return results

    def _get_fallback_pairs(self) -> List[str]:
        """Return manual trading pairs as fallback."""
        manual = getattr(self.config, 'manual_trading_pairs', [])
        blacklist = set(getattr(self.config, 'blacklist', []))

        result = [p for p in manual if p not in blacklist]
        self.logger.info(f"📋 Using {len(result)} fallback pairs from config")
        return result
```

### Controller Integratie

```python
# In FuturesGridBitgetController.__init__():

# Initialize pair discovery
self.pair_discovery = FuturesPairDiscovery(
    connector=self.connector,
    config=self.config,
    logger=self.logger()
)

# In _initialize_coins() or start():

async def _discover_trading_pairs(self) -> List[str]:
    """Discover pairs (dynamic or manual based on config)."""

    use_dynamic = getattr(self.config, 'use_dynamic_pair_discovery', False)

    if use_dynamic:
        self.logger().info("🔍 Starting dynamic pair discovery...")
        pairs = await self.pair_discovery.discover_pairs()

        # Apply max_coins_to_monitor limit
        max_coins = getattr(self.config, 'max_coins_to_monitor', 50)
        if len(pairs) > max_coins:
            pairs = pairs[:max_coins]
            self.logger().info(
                f"📊 Limited to top {max_coins} pairs by volume"
            )

        return pairs
    else:
        self.logger().info("📋 Using manual trading pairs from config")
        return self.pair_discovery._get_fallback_pairs()
```

---

## ⚙️ Config Wijzigingen

### Nieuwe Config Parameters

```yaml
# futures_bitget/config/futures_grid_bitget.yaml

# ============================================================
# DYNAMIC PAIR DISCOVERY (NEW!)
# ============================================================
# Automatisch alle liquide USDT perpetual pairs ontdekken
# Fallback naar manual_trading_pairs bij API failure
# ============================================================

use_dynamic_pair_discovery: true      # 🆕 Enable/disable dynamic discovery
min_24h_volume_usdt: 1000000          # 🆕 Min $1M 24h volume
max_spread_pct: 0.1                   # 🆕 Max 0.1% bid-ask spread
max_coins_to_monitor: 50              # 🆕 Limit discovered pairs
discovery_refresh_interval_sec: 3600  # 🆕 Refresh every 1 hour

# Fallback list (used when dynamic fails OR disabled)
manual_trading_pairs:
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
  # ... existing list ...
```

### Config Schema Update

```python
# futures_bitget/config_schema.py

# Add new fields:
use_dynamic_pair_discovery: bool = Field(
    default=False,  # Default OFF for safety
    description="Enable dynamic pair discovery from Bitget API"
)

min_24h_volume_usdt: float = Field(
    default=1_000_000,
    ge=0,
    description="Minimum 24h volume in USDT for pair selection"
)

max_spread_pct: float = Field(
    default=0.1,
    ge=0,
    le=5.0,
    description="Maximum bid-ask spread percentage"
)

max_coins_to_monitor: int = Field(
    default=50,
    ge=1,
    le=200,
    description="Maximum number of pairs to monitor"
)

discovery_refresh_interval_sec: int = Field(
    default=3600,
    ge=300,
    description="How often to refresh discovered pairs (seconds)"
)
```

---

## 🔄 Fallback Mechanisme

### Fallback Triggers

| Trigger | Actie | Log Level |
|---------|-------|-----------|
| API request fails | Use manual list | WARNING |
| API returns empty | Use manual list | WARNING |
| API rate limited | Use cached data | INFO |
| All pairs filtered out | Use manual list | WARNING |
| `use_dynamic_pair_discovery: false` | Use manual list | INFO |

### Fallback Flow

```
Discovery Start
     │
     ▼
┌─────────────┐
│ Fetch API   │──── Error? ────▶ FALLBACK
└─────────────┘
     │
     ▼
┌─────────────┐
│ Apply       │──── Empty? ────▶ FALLBACK
│ Filters     │
└─────────────┘
     │
     ▼
┌─────────────┐
│ Use Dynamic │
│ Pairs       │
└─────────────┘
```

### Fallback Guarantee

```python
def _get_fallback_pairs(self) -> List[str]:
    """
    ALWAYS returns a non-empty list.

    Priority:
    1. manual_trading_pairs from config
    2. CORE_UNIVERSE hardcoded list (last resort)
    """
    manual = getattr(self.config, 'manual_trading_pairs', [])

    if manual:
        return [p for p in manual if p not in self.blacklist]

    # Hardcoded fallback (should never reach here)
    CORE_UNIVERSE = [
        "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT",
        "BNB-USDT", "DOGE-USDT", "ADA-USDT", "AVAX-USDT"
    ]
    return CORE_UNIVERSE
```

---

## ⚠️ Risico's & Mitigatie

### Risico Matrix

| Risico | Impact | Kans | Mitigatie |
|--------|--------|------|-----------|
| **API failure** | Medium | Low | Fallback naar manual list + cache |
| **Rate limiting** | Low | Medium | 5 min cache TTL, sparse calls |
| **New delisted coin** | High | Low | Check `status: normal` |
| **Extreme volatility coin** | High | Medium | Volume filter + blacklist |
| **Flash crash coin** | High | Low | ATR-based stops al in Sprint 3 |

### Mitigatie Strategieën

1. **Dual-layer fallback**: API fail → Cache → Manual list → Core universe
2. **Conservative defaults**: `use_dynamic_pair_discovery: false`
3. **Volume floor**: $1M minimum = excludes low-liquidity pumps
4. **Blacklist support**: Manually exclude problematic pairs
5. **Max coins cap**: Limit to top 50 prevents resource exhaustion

---

## 📅 Tijdslijn

### Fase 1: Core Implementation (2-3 uur)
- [ ] `FuturesPairDiscovery` class
- [ ] Config schema updates
- [ ] Basic API integration

### Fase 2: Controller Integration (1-2 uur)
- [ ] Integrate in `FuturesGridBitgetController`
- [ ] Periodic refresh mechanism
- [ ] Logging improvements

### Fase 3: Testing (1-2 uur)
- [ ] Unit tests voor discovery
- [ ] Integration test met live API
- [ ] Fallback scenario tests

### Fase 4: Documentation & Deployment (30 min)
- [ ] Config documentation
- [ ] README update
- [ ] Deploy with `use_dynamic_pair_discovery: false` (safe)

**Totaal: ~5-7 uur development time**

---

## ✅ Acceptatie Criteria

1. ✅ Dynamic discovery haalt 50+ USDT pairs op van Bitget
2. ✅ Filtering reduceert naar ~30-50 liquide pairs
3. ✅ Fallback werkt wanneer API faalt
4. ✅ Geen rate limit errors na 24 uur runtime
5. ✅ Unit tests coverage >80%
6. ✅ Config default is `false` (opt-in)

---

## 📝 Review Checklist

**Voor Mo om te reviewen:**

- [ ] Akkoord met filter criteria (volume $1M, spread 0.1%)?
- [ ] Wil je Open Interest filtering (P1)?
- [ ] Max coins to monitor: 50 is OK?
- [ ] Refresh interval: 1 uur is OK?
- [ ] Andere blacklist entries toevoegen?
- [ ] Wil je hot coin detection (P2)?

**Na review → Start implementatie**

---

*Document laatst bijgewerkt: 8 februari 2026*
