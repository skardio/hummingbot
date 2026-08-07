# Momentum Signal Service — Volledig Patchplan

**Status:** Design goedgekeurd, implementatie nog niet gestart
**Datum:** 2026-05-25
**Mode:** `signal_only` — GEEN automatische trading, GEEN paper trading
**Doel:** Aparte read-only service die periodiek een shortlist geeft van coins met momentum-potentie voor handmatige beoordeling.

---

## Inhoudsopgave

1. [Architectuurkeuzes (definitief)](#1-architectuurkeuzes-definitief)
2. [Kritieke bevindingen uit code-audit](#2-kritieke-bevindingen-uit-code-audit)
3. [Files toegevoegd](#3-files-toegevoegd)
4. [Files ongewijzigd](#4-files-ongewijzigd)
5. [Bestaande modules hergebruikt (read-only)](#5-bestaande-modules-hergebruikt-read-only)
6. [Verboden imports](#6-verboden-imports)
7. [Configuratievoorstel](#7-configuratievoorstel)
8. [SQLite-schema (eigen database)](#8-sqlite-schema-eigen-database)
9. [JSON-snapshot voorbeeld](#9-json-snapshot-voorbeeld)
10. [Console/log output voorbeeld](#10-consolelog-output-voorbeeld)
11. [Testplan](#11-testplan)
12. [Implementatievolgorde](#12-implementatievolgorde)
13. [Architectuurdiagram](#13-architectuurdiagram)
14. [Samenvatting verboden vs. toegestaan](#14-samenvatting-verboden-vs-toegestaan)

---

## 1. Architectuurkeuzes (definitief)

- **Geen automatische trading.**
- **Geen paper trading in deze fase.**
- **Alleen `signal_only`.**
- De service draait als **apart Python process** binnen dezelfde repo.
- De bestaande embedded `momentum_sleeve` in de gridcontroller wordt **niet** verder uitgebreid.
- De service produceert alleen een shortlist van coins met potentie voor handmatige beoordeling/trading.

### Bestandsstructuur (nieuwe files)

```
multi_coin_grid_pro/
├── signals/
│   ├── __init__.py
│   ├── momentum_config.py
│   ├── momentum_models.py
│   ├── momentum_market_data.py
│   ├── momentum_signal_scorer.py
│   ├── momentum_filters.py
│   ├── grid_position_reader.py
│   ├── blacklist_reader.py
│   └── momentum_signal_store.py
│
├── reporters/
│   └── momentum_signal_reporter.py
│
├── services/
│   └── momentum_signal_service.py
│
└── config/
    └── momentum_signal_service.yaml

tests/multi_coin_grid_pro/signals/
├── __init__.py
├── test_momentum_config.py
├── test_momentum_models.py
├── test_momentum_signal_scorer.py
├── test_momentum_filters.py
├── test_grid_position_reader.py
├── test_blacklist_reader.py
├── test_momentum_signal_store.py
├── test_momentum_signal_reporter.py
└── test_safety_guards.py

data/
    momentum_signals.sqlite          # Auto-aangemaakt bij eerste run
    latest_momentum_signals.json     # Atomisch overschreven na elke scan

logs/
    momentum_signal_service.log      # Eigen log, nooit gedeeld met grid-bots
```

---

## 2. Kritieke bevindingen uit code-audit

### 2a. Scorer-schaal: 0–100 (niet 0.0–1.0)

De bestaande `MomentumCandidateScorer._calculate_score()` retourneert:
```python
return self._clamp(weighted / weight_sum, 0.0, 100.0)   # ← 0–100 schaal
```
En `DEFAULT_MOMENTUM_CONFIG` heeft `min_score_to_enter: 55.0`.

**Gevolg:** `momentum_signal_scorer.py` bevat een wrapper die de ruwe score deelt door 100.0,
zodat de service intern altijd **0.0–1.0** werkt en `min_score: 0.70` in config overeenkomt
met score 70 in de legacy scorer.

### 2b. CooldownStore mag NIET worden geïnstantieerd

`CooldownStore.__init__` doet `PRAGMA journal_mode=WAL` + `_create_table()` — dat zijn **writes**.
De nieuwe service instantieert deze klasse nooit. In plaats daarvan komt een eigen
`CooldownReader` die via een read-only SQLite-URI queryt.

### 2c. Executors-tabel schema (grid-DB)

De grid-DB heeft tabel **`Executors`** (hoofdletter E). De trading pair zit in de JSON `config`-kolom:
```sql
SELECT json_extract(config, '$.trading_pair') AS trading_pair
FROM Executors
WHERE is_active = 1
```
Kolommen: `id`, `timestamp`, `type`, `close_type`, `close_timestamp`, `status`,
`config` (JSON), `net_pnl_pct`, `net_pnl_quote`, `cum_fees_quote`,
`filled_amount_quote`, `is_active` (BOOLEAN), `is_trading` (BOOLEAN),
`custom_info` (JSON), `controller_id`.

---

## 3. Files toegevoegd

| File | Inhoud |
|------|--------|
| `multi_coin_grid_pro/signals/__init__.py` | Leeg — maakt package |
| `multi_coin_grid_pro/signals/momentum_config.py` | `ServiceConfig` dataclass + YAML loader; asserteert `mode == "signal_only"` |
| `multi_coin_grid_pro/signals/momentum_models.py` | `RawTicker`, `EnrichedCandidate`, `MomentumSignal`, `FilterResult`, `ScanResult` dataclasses |
| `multi_coin_grid_pro/signals/momentum_market_data.py` | `aiohttp`-based REST fetcher voor tickers/candles/orderbook (public endpoints) |
| `multi_coin_grid_pro/signals/momentum_signal_scorer.py` | Wrapper om `MomentumCandidateScorer` → normaliseert naar 0.0–1.0 |
| `multi_coin_grid_pro/signals/momentum_filters.py` | `HardFilter`: stateless pure functies, geen I/O |
| `multi_coin_grid_pro/signals/grid_position_reader.py` | Leest actieve pairs uit grid-DB via read-only URI |
| `multi_coin_grid_pro/signals/blacklist_reader.py` | Parseert YAML-blacklist via `yaml.safe_load` |
| `multi_coin_grid_pro/signals/momentum_signal_store.py` | Schrijft naar EIGEN `data/momentum_signals.sqlite` + JSON snapshot |
| `multi_coin_grid_pro/reporters/momentum_signal_reporter.py` | Log/console formatter voor top-N |
| `multi_coin_grid_pro/services/momentum_signal_service.py` | Asyncio orchestrator + CLI entry-point |
| `multi_coin_grid_pro/config/momentum_signal_service.yaml` | Eigen config (los van alle grid-configs) |
| `tests/multi_coin_grid_pro/signals/__init__.py` | Leeg |
| `tests/multi_coin_grid_pro/signals/test_safety_guards.py` | AST-scan + write-protection tests |
| `tests/multi_coin_grid_pro/signals/test_momentum_config.py` | Config validatie |
| `tests/multi_coin_grid_pro/signals/test_momentum_models.py` | Dataclass sanity checks |
| `tests/multi_coin_grid_pro/signals/test_momentum_signal_scorer.py` | Schaal, determinisme, ranking |
| `tests/multi_coin_grid_pro/signals/test_momentum_filters.py` | Filter-logica |
| `tests/multi_coin_grid_pro/signals/test_grid_position_reader.py` | RO-URI, active pairs, geen schrijven |
| `tests/multi_coin_grid_pro/signals/test_blacklist_reader.py` | YAML parsing, missing file |
| `tests/multi_coin_grid_pro/signals/test_momentum_signal_store.py` | SQLite write, JSON atomisch, purge |
| `tests/multi_coin_grid_pro/signals/test_momentum_signal_reporter.py` | Formatteer output |

---

## 4. Files ongewijzigd

| File | Reden |
|------|-------|
| `multi_coin_grid_pro/logic/momentum_candidate_scorer.py` | Hergebruikt read-only als dependency |
| `multi_coin_grid_pro/indicators/momentum_indicators.py` | Niet hergebruikt (Hummingbot connector-dep) |
| `multi_coin_grid_pro/execution/momentum_sleeve_manager.py` | Verboden: paper trading engine |
| `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | Verboden: plaatst orders |
| `multi_coin_grid_pro/persistence/cooldown_store.py` | Verboden: `__init__` schrijft DB (WAL + tabel) |
| `multi_coin_grid_pro/utils/staleness_guard.py` | Hergebruikt read-only als dependency |
| `multi_coin_grid_pro/core/reason_codes.py` | Hergebruikt read-only als dependency |
| `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` | Alleen gelezen via `blacklist_reader.py` |
| Alle andere `config/*.yaml` grid-configs | Idem: alleen gelezen via `yaml.safe_load` |
| `data/multi_coin_grid_v2*.sqlite` | Alleen via read-only URI, nooit geschreven |
| `data/spot_grid_*.sqlite` | Idem |

---

## 5. Bestaande modules hergebruikt (read-only)

| Module | Gebruik in nieuwe service | Instantiatie-concern |
|--------|--------------------------|---------------------|
| `logic/momentum_candidate_scorer.py` → `MomentumCandidateScorer` | `momentum_signal_scorer.py` wraps this; roept `scorer.score()` aan met duck-typed trend_obj gebouwd vanuit REST-candles | Veilig: `__init__` doet geen I/O |
| `logic/momentum_candidate_scorer.py` → `DEFAULT_SCORER_WEIGHTS` | Importeren als constante voor config-defaults | Veilig |
| `core/reason_codes.py` → `ReasonCode` | Rejection strings in `MomentumSignal.rejection_reason` | Veilig: alleen enum |
| `utils/staleness_guard.py` → `StalenessGuard` | `momentum_market_data.py` bewaakt data-versheid per pair | Veilig: geen I/O in `__init__` |

**Niet hergebruikt:**
- `TrendCalculator` — diep gekoppeld aan `ConnectorBase` en Hummingbot event loops
- `MomentumIndicatorService` — constructor verwacht Hummingbot connector
- `CooldownStore` — `__init__` doet WAL pragma + `_create_table()` (writes)

---

## 6. Verboden imports

De volgende symbols mogen in **geen enkel nieuw bestand** geïmporteerd worden.
`test_safety_guards.py` verifieert dit via AST-analyse op elke nieuwe module.

```python
FORBIDDEN_SYMBOLS = [
    # Order placement
    "CreateExecutorAction",
    "StopExecutorAction",
    "GridExecutorConfig",
    "TripleBarrierConfig",
    "EntryGateway",
    # Capital allocation
    "BudgetAllocator",
    # Exchange write methods (string-match op aanroepen, niet alleen imports)
    "connector.buy",
    "connector.sell",
    "connector.cancel",
    # Paper trading engine
    "MomentumSleeveManager",
    "MomentumPosition",
    # Grid controller
    "MultiCoinGridController",
    "MultiCoinGridControllerConfig",
    # CooldownStore (schrijft bij __init__)
    "CooldownStore",
    # GlobalRiskManager
    "GlobalRiskManager",
]
```

---

## 7. Configuratievoorstel

```yaml
# multi_coin_grid_pro/config/momentum_signal_service.yaml

momentum_signal_service:
  enabled: true
  mode: signal_only          # Enige geldige waarde — hardcoded assertion bij startup

  scan_interval_seconds: 60  # Hoe vaak alle exchanges worden gescand
  top_n: 10                  # Max kandidaten in output per scan

  # ─── Exchanges ────────────────────────────────────────────────────────────
  exchanges:
    - exchange: kraken
      api_url: https://api.kraken.com
      quote_assets: [USD]
      # Grid-DB: alleen lezen via read-only URI (file:path?mode=ro&uri=True)
      grid_db_path: data/multi_coin_grid_v2_usd.sqlite
      # Blacklist-YAML: gelezen via yaml.safe_load, nooit als Config-object
      blacklist_yaml: multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml
      # Cooldown-DB: eigen read-only query (NOOIT CooldownStore instantiëren)
      cooldown_db_path: data/cooldowns_usd.db

    - exchange: okx
      api_url: https://www.okx.com
      quote_assets: [USDT, USDC]
      grid_db_path: data/spot_grid_okx.sqlite
      blacklist_yaml: multi_coin_grid_pro/spot_okx/config/spot_grid_okx.yaml
      cooldown_db_path: data/cooldowns_okx.db

    - exchange: bitget
      api_url: https://api.bitget.com
      quote_assets: [USDT]
      grid_db_path: data/spot_grid_bitget.sqlite
      blacklist_yaml: multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
      cooldown_db_path: data/cooldowns_bitget.db

  # ─── Safety (harde grenzen, geasserteerd bij startup) ─────────────────────
  safety:
    read_only: true
    allow_order_creation: false
    allow_executor_actions: false
    allow_budget_reservation: false
    allow_grid_state_writes: false

  # ─── Hard filters (verwerpen vóór scoring) ────────────────────────────────
  candidate_filters:
    min_price_change_5m_pct: 2.0       # Minimaal momentum in 5 minuten
    min_price_change_15m_pct: 4.0      # Minimaal momentum in 15 minuten
    max_price_change_15m_pct: 35.0     # Pump-gate: extreem = mogelijk manipulatie
    min_volume_ratio: 3.0              # volume_now / volume_avg_20_candles
    max_spread_pct: 0.35               # Spread te hoog = illiquide
    min_orderbook_depth_quote: 5000    # Minimale bid-diepte binnen 1% in quote
    max_orderbook_staleness_seconds: 5
    exclude_blacklisted: true
    exclude_active_grid_positions: true
    exclude_cooldown_pairs: true

  # ─── Scoring (na hard filter) ─────────────────────────────────────────────
  scoring:
    # min_score is in 0.0-1.0 schaal.
    # De wrapper normaliseert legacy 0-100 scorer: score_01 = raw / 100.0
    # 0.70 hier = score 70 in de legacy MomentumCandidateScorer
    min_score: 0.70
    weights:
      # Laat leeg om DEFAULT_SCORER_WEIGHTS te gebruiken
      trend_1h: 0.25
      trend_4h: 0.30
      volume_expansion: 0.20
      relative_strength: 0.15
      spread: 0.05
      rsi_wick_risk: 0.05

  # ─── Output ───────────────────────────────────────────────────────────────
  output:
    log_path: logs/momentum_signal_service.log
    database_path: data/momentum_signals.sqlite  # NOOIT een grid-DB pad
    json_snapshot_path: data/latest_momentum_signals.json
    write_sqlite: true
    write_json_snapshot: true
    log_accepted: true
    log_rejected: false        # Vermijd flood bij honderden verworpen coins
    summary_interval_seconds: 300

  # ─── HTTP / rate-limiting ─────────────────────────────────────────────────
  http:
    request_timeout_seconds: 5
    max_concurrent_requests: 5
    candle_count: 20           # 1m-candles per pair (15m lookback + buffer)
    retry_on_rate_limit: true
    backoff_seconds: 2.0

  # ─── Data retention ───────────────────────────────────────────────────────
  retention_days: 7            # Verwijder signalen ouder dan 7 dagen bij elke schrijf
```

---

## 8. SQLite-schema (eigen database)

```sql
-- data/momentum_signals.sqlite
-- NOOIT het pad van een bestaande grid-database

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS momentum_signals (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id                  TEXT    NOT NULL,   -- UUID per scan-run
    timestamp                REAL    NOT NULL,   -- Unix epoch van de scan

    exchange                 TEXT    NOT NULL,   -- "kraken" | "okx" | "bitget"
    trading_pair             TEXT    NOT NULL,   -- "WIF-USDT"
    rank                     INTEGER,            -- 1 = beste (NULL als verworpen)

    -- Prijs & momentum
    price                    REAL    NOT NULL,
    price_change_1m_pct      REAL,
    price_change_5m_pct      REAL,
    price_change_15m_pct     REAL,

    -- Volume
    volume_ratio             REAL,               -- volume_now / volume_avg_20_candles

    -- Liquiditeit & spread
    spread_pct               REAL,
    orderbook_depth_quote    REAL,               -- bid-diepte binnen 1% in quote
    orderbook_imbalance      REAL,               -- (bid_vol - ask_vol) / totaal

    -- Volatiliteit
    volatility_pct           REAL,               -- std(1m-returns) * sqrt(annualisatie)

    -- Context (gelezen van grid-state, read-only)
    active_grid_position     INTEGER NOT NULL DEFAULT 0,  -- 0/1
    blacklisted              INTEGER NOT NULL DEFAULT 0,  -- 0/1
    in_cooldown              INTEGER NOT NULL DEFAULT 0,  -- 0/1

    -- Scoring (0.0–1.0 schaal)
    score                    REAL    NOT NULL,
    accepted                 INTEGER NOT NULL DEFAULT 0,  -- 0/1

    -- Rejection
    rejection_reason         TEXT,               -- NULL als geaccepteerd
    all_reasons_json         TEXT,               -- JSON array van alle redenen

    -- Score breakdown (voor debugging)
    score_breakdown_json     TEXT                -- JSON object met subscore per dimensie
);

CREATE INDEX IF NOT EXISTS idx_ms_timestamp   ON momentum_signals (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ms_accepted    ON momentum_signals (accepted, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ms_scan_id     ON momentum_signals (scan_id);
CREATE INDEX IF NOT EXISTS idx_ms_exchange    ON momentum_signals (exchange);
CREATE INDEX IF NOT EXISTS idx_ms_pair        ON momentum_signals (trading_pair, timestamp DESC);
```

---

## 9. JSON-snapshot voorbeeld

```json
{
  "generated_at": 1748615400.123,
  "generated_at_human": "2026-05-30 14:30:00 UTC",
  "scan_id": "a3f2c1d0-8b4e-4f1a-9c3d-2e7f0a1b5c8d",
  "scan_duration_seconds": 4.7,
  "top_signals": [
    {
      "rank": 1,
      "exchange": "okx",
      "trading_pair": "WIF-USDT",
      "price": 2.3412,
      "score": 0.87,
      "price_change_1m_pct": 1.2,
      "price_change_5m_pct": 4.8,
      "price_change_15m_pct": 9.3,
      "volume_ratio": 6.4,
      "spread_pct": 0.17,
      "orderbook_depth_quote": 14800,
      "orderbook_imbalance": 0.38,
      "volatility_pct": 12.1,
      "active_grid_position": false,
      "blacklisted": false,
      "in_cooldown": false,
      "accepted": true,
      "rejection_reason": null,
      "score_breakdown": {
        "trend_1h": 0.85,
        "trend_4h": 0.91,
        "volume_expansion": 0.82,
        "relative_strength": 0.78,
        "spread": 0.95,
        "rsi_wick_risk": 0.88
      }
    },
    {
      "rank": 2,
      "exchange": "kraken",
      "trading_pair": "PEPE-USD",
      "price": 0.00001342,
      "score": 0.79,
      "price_change_1m_pct": 0.8,
      "price_change_5m_pct": 3.1,
      "price_change_15m_pct": 6.7,
      "volume_ratio": 4.1,
      "spread_pct": 0.22,
      "orderbook_depth_quote": 8200,
      "orderbook_imbalance": 0.21,
      "volatility_pct": 18.4,
      "active_grid_position": false,
      "blacklisted": false,
      "in_cooldown": false,
      "accepted": true,
      "rejection_reason": null,
      "score_breakdown": {
        "trend_1h": 0.71,
        "trend_4h": 0.80,
        "volume_expansion": 0.75,
        "relative_strength": 0.65,
        "spread": 0.89,
        "rsi_wick_risk": 0.82
      }
    }
  ],
  "summary": {
    "total_scanned": 243,
    "total_accepted": 2,
    "total_rejected": 241,
    "rejection_breakdown": {
      "SCORE_TOO_LOW": 124,
      "MOMENTUM_VOLUME_TOO_LOW": 67,
      "SPREAD_TOO_HIGH": 23,
      "BLACKLISTED": 14,
      "ACTIVE_GRID_POSITION": 8,
      "STALE_ORDERBOOK": 3,
      "EXTREME_PUMP": 2
    }
  }
}
```

---

## 10. Console/log output voorbeeld

```
2026-05-30 14:30:00,123 INFO  [MOMENTUM_SIGNAL_SERVICE] ════════════════════════════════════
2026-05-30 14:30:00,124 INFO  [MOMENTUM_SIGNAL_SERVICE] scan_id=a3f2c1d0 scanned=243 accepted=2 duration=4.7s
2026-05-30 14:30:00,125 INFO  [MOMENTUM_SIGNAL_SERVICE]
2026-05-30 14:30:00,126 INFO  [MOMENTUM_SIGNAL_SERVICE]  RANK  EXCHANGE  PAIR           SCORE   PRICE       5m%    15m%  VOL_X  SPREAD
2026-05-30 14:30:00,127 INFO  [MOMENTUM_SIGNAL_SERVICE]  ─────────────────────────────────────────────────────────────────────────────────
2026-05-30 14:30:00,128 INFO  [MOMENTUM_SIGNAL_SERVICE]   #1   okx       WIF-USDT       0.87   2.3412     +4.8%  +9.3%   6.4x  0.17%
2026-05-30 14:30:00,129 INFO  [MOMENTUM_SIGNAL_SERVICE]   #2   kraken    PEPE-USD       0.79   0.00001342 +3.1%  +6.7%   4.1x  0.22%
2026-05-30 14:30:00,130 INFO  [MOMENTUM_SIGNAL_SERVICE]
2026-05-30 14:30:00,131 INFO  [MOMENTUM_SIGNAL_SERVICE] !! SIGNAL ONLY — GEEN ORDERS WORDEN GEPLAATST. HANDMATIGE BEOORDELING VEREIST. !!
2026-05-30 14:30:00,132 INFO  [MOMENTUM_SIGNAL_SERVICE] ════════════════════════════════════
```

Elke 5 minuten (summary_interval_seconds):
```
2026-05-30 14:35:00,000 INFO  [MOMENTUM_SIGNAL_SERVICE] [5m SUMMARY] scans=5 avg_accepted=1.8 avg_duration=4.4s top_coin=WIF-USDT(5x)
```

---

## 11. Testplan

### 11a. Veiligheidstests (`test_safety_guards.py`) — blokkeren bij CI als ze falen

```python
def test_no_forbidden_imports_in_service_modules():
    """
    AST-scan op alle nieuwe modules: geen verboden symbols geïmporteerd.
    Gebruikt ast.parse() — geen runtime import van de modules zelf.
    """
    new_modules = [
        "multi_coin_grid_pro/signals/momentum_config.py",
        "multi_coin_grid_pro/signals/momentum_models.py",
        "multi_coin_grid_pro/signals/momentum_market_data.py",
        "multi_coin_grid_pro/signals/momentum_signal_scorer.py",
        "multi_coin_grid_pro/signals/momentum_filters.py",
        "multi_coin_grid_pro/signals/grid_position_reader.py",
        "multi_coin_grid_pro/signals/blacklist_reader.py",
        "multi_coin_grid_pro/signals/momentum_signal_store.py",
        "multi_coin_grid_pro/reporters/momentum_signal_reporter.py",
        "multi_coin_grid_pro/services/momentum_signal_service.py",
    ]
    forbidden = [
        "CreateExecutorAction", "StopExecutorAction", "GridExecutorConfig",
        "TripleBarrierConfig", "EntryGateway", "BudgetAllocator",
        "MomentumSleeveManager", "MultiCoinGridController", "CooldownStore",
    ]
    # Per file: ast.walk() alle Import/ImportFrom nodes, check names

def test_no_buy_sell_cancel_calls_in_source():
    """Tekstscan op verboden method-aanroepen in alle nieuwe modules."""
    patterns = [".buy(", ".sell(", ".cancel(", "connector.buy", "connector.sell"]

def test_signal_store_path_is_not_grid_db():
    """SignalStore weigert een grid-DB pad."""
    forbidden_paths = [
        "multi_coin_grid_v2.sqlite", "multi_coin_grid_v2_usd.sqlite",
        "spot_grid_bitget.sqlite", "spot_grid_okx.sqlite",
    ]
    for path in forbidden_paths:
        with pytest.raises((ValueError, AssertionError)):
            SignalStore(db_path=f"data/{path}")

def test_mode_not_signal_only_raises():
    """ServiceConfig raises ValueError als mode != 'signal_only'."""
    for bad_mode in ["paper", "live", "detect_only", "dry_run", ""]:
        with pytest.raises(ValueError, match="signal_only"):
            ServiceConfig(mode=bad_mode, ...)

def test_safety_flags_true_raises():
    """allow_order_creation=True raises ValueError."""
    with pytest.raises(ValueError):
        ServiceConfig(safety={"allow_order_creation": True, ...}, ...)
```

### 11b. Grid-position reader tests (`test_grid_position_reader.py`)

```python
def test_grid_position_reader_uses_readonly_uri(tmp_path):
    """
    GridPositionReader opent SQLite via 'file:path?mode=ro&uri=True'.
    Schrijfpoging faalt met OperationalError.
    """
    db_path = tmp_path / "test_grid.sqlite"
    _create_test_grid_db(db_path, active_pairs=["BTC-USD"])
    reader = GridPositionReader(db_path=str(db_path))
    with pytest.raises(Exception):
        reader._conn.execute("INSERT INTO Executors VALUES (...)")

def test_grid_position_reader_returns_active_pairs(tmp_path):
    db_path = tmp_path / "test_grid.sqlite"
    _create_test_grid_db(db_path,
                         active_pairs=["BTC-USD", "ETH-USD"],
                         inactive_pairs=["SOL-USD"])
    reader = GridPositionReader(db_path=str(db_path))
    pairs = reader.get_active_pairs()
    assert "BTC-USD" in pairs
    assert "ETH-USD" in pairs
    assert "SOL-USD" not in pairs

def test_grid_position_reader_missing_db_returns_empty():
    """Bot offline → lege set, geen exception."""
    reader = GridPositionReader(db_path="/nonexistent/path.sqlite")
    assert reader.get_active_pairs() == set()

def test_existing_grid_db_not_modified(tmp_path):
    """MD5 checksum van grid-DB is identiek voor en na gebruik."""
    db_path = tmp_path / "grid.sqlite"
    _create_test_grid_db(db_path, active_pairs=["BTC-USD"])
    checksum_before = _md5(db_path)
    GridPositionReader(db_path=str(db_path)).get_active_pairs()
    assert _md5(db_path) == checksum_before
```

### 11c. Blacklist reader tests (`test_blacklist_reader.py`)

```python
def test_blacklist_reader_parses_yaml(tmp_path):
    yaml_content = "blacklisted_pairs: [SCAM-USD, RUGPULL-USD]"
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)
    bl = BlacklistReader(yaml_path=str(yaml_file)).get_blacklist()
    assert "SCAM-USD" in bl
    assert "RUGPULL-USD" in bl

def test_blacklist_reader_missing_file_returns_empty():
    assert BlacklistReader(yaml_path="/nonexistent.yaml").get_blacklist() == set()

def test_blacklist_reader_does_not_import_controller_config():
    """yaml.safe_load gebruikt, nooit MultiCoinGridControllerConfig."""
    import sys
    BlacklistReader(yaml_path="/dev/null").get_blacklist()
    assert "multi_coin_grid_pro.controllers.multi_coin_grid_config" not in sys.modules
```

### 11d. Filter tests (`test_momentum_filters.py`)

```python
def test_blacklisted_pair_excluded():
    c = make_candidate("SCAM-USD", blacklisted=True)
    result = HardFilter({"exclude_blacklisted": True}).apply([c])
    assert len(result.accepted) == 0
    assert result.rejected[0].rejection_reason == "BLACKLISTED"

def test_active_grid_pair_excluded():
    c = make_candidate("BTC-USD", active_grid_position=True)
    result = HardFilter({"exclude_active_grid_positions": True}).apply([c])
    assert result.rejected[0].rejection_reason == "ACTIVE_GRID_POSITION"

def test_spread_too_high_excluded():
    c = make_candidate("XRP-USD", spread_pct=0.50)
    result = HardFilter({"max_spread_pct": 0.35}).apply([c])
    assert result.rejected[0].rejection_reason == "SPREAD_TOO_HIGH"

def test_stale_orderbook_excluded():
    c = make_candidate("SOL-USD", ob_age_seconds=10.0)
    result = HardFilter({"max_orderbook_staleness_seconds": 5}).apply([c])
    assert result.rejected[0].rejection_reason == "STALE_ORDERBOOK"

def test_pump_gate_rejects_extreme_move():
    c = make_candidate("PEPE-USD", price_change_15m_pct=40.0)
    result = HardFilter({"max_price_change_15m_pct": 35.0}).apply([c])
    assert result.rejected[0].rejection_reason == "EXTREME_PUMP"

def test_volume_too_low_excluded():
    c = make_candidate("DOGE-USD", volume_ratio=1.5)
    result = HardFilter({"min_volume_ratio": 3.0}).apply([c])
    assert result.rejected[0].rejection_reason == "VOLUME_TOO_LOW"
```

### 11e. Scorer tests (`test_momentum_signal_scorer.py`)

```python
def test_score_is_in_0_to_1_range():
    scorer = SignalScorer()
    result = scorer.score(make_enriched_candidate())
    assert 0.0 <= result.score <= 1.0

def test_score_normalized_from_legacy_0_100():
    """Legacy scorer output 0-100 → wrapper geeft 0.0-1.0."""
    scorer = SignalScorer()
    result = scorer.score(make_enriched_candidate())
    assert result.score <= 1.0   # nooit boven 1.0

def test_score_is_deterministic():
    scorer = SignalScorer()
    c = make_enriched_candidate()
    assert scorer.score(c).score == scorer.score(c).score

def test_score_below_min_not_accepted():
    scorer = SignalScorer(min_score=0.70)
    c = make_enriched_candidate(trend_1h_pct=0.1, volume_ratio=1.1)
    result = scorer.score(c)
    assert not result.accepted
    assert result.rejection_reason == "SCORE_TOO_LOW"

def test_ranking_top_n():
    signals = [make_signal(score=s) for s in [0.91, 0.72, 0.85, 0.95, 0.68]]
    ranked = rank_signals(signals, top_n=3)
    assert len(ranked) == 3
    assert ranked[0].score == 0.95
    assert [s.rank for s in ranked] == [1, 2, 3]
```

### 11f. Store tests (`test_momentum_signal_store.py`)

```python
def test_signal_store_creates_own_db(tmp_path):
    store = SignalStore(db_path=str(tmp_path / "momentum_signals.sqlite"))
    store.write([make_signal()])
    conn = sqlite3.connect(str(tmp_path / "momentum_signals.sqlite"))
    assert conn.execute("SELECT COUNT(*) FROM momentum_signals").fetchone()[0] == 1

def test_json_snapshot_atomic_write(tmp_path):
    writer = JsonSnapshotWriter(path=str(tmp_path / "signals.json"))
    writer.write(make_scan_result())
    data = json.loads((tmp_path / "signals.json").read_text())
    assert "top_signals" in data
    assert "scan_id" in data
    assert "generated_at" in data

def test_retention_purge_removes_old_records(tmp_path):
    store = SignalStore(db_path=str(tmp_path / "momentum_signals.sqlite"),
                       retention_days=7)
    old_ts = time.time() - (8 * 86400)
    store._insert_raw(make_signal(timestamp=old_ts))
    store._purge_old()
    conn = sqlite3.connect(str(tmp_path / "momentum_signals.sqlite"))
    assert conn.execute("SELECT COUNT(*) FROM momentum_signals").fetchone()[0] == 0
```

---

## 12. Implementatievolgorde

### Stap 1 — Package-skeleton + safety test fundament
**Files:** `signals/__init__.py`, `reporters/__init__.py`, `services/__init__.py`,
`tests/signals/__init__.py`, `test_safety_guards.py` (skeleton, alle assertions groen door lege modules)

**Gate:** `pytest tests/multi_coin_grid_pro/signals/test_safety_guards.py` → groen

---

### Stap 2 — `momentum_models.py` + modeltests
**Files:** `signals/momentum_models.py`, `tests/signals/test_momentum_models.py`

Bevat: `RawTicker`, `EnrichedCandidate`, `MomentumSignal`, `FilterResult`, `ScanResult`.
Geen I/O. Geen imports buiten stdlib en `dataclasses`.

**Gate:** modeltests groen, AST safety check groen

---

### Stap 3 — `momentum_config.py` + configtests
**Files:** `signals/momentum_config.py`, `config/momentum_signal_service.yaml`,
`tests/signals/test_momentum_config.py`

`ServiceConfig`:
- `__post_init__` asserteert `mode == "signal_only"`, anders `ValueError`
- Asserteert alle `safety.*` flags zijn `false`, anders `ValueError`
- Laadt YAML via `yaml.safe_load` (geen Hummingbot config-klassen)

**Gate:** `test_mode_not_signal_only_raises` en `test_safety_flags_true_raises` groen

---

### Stap 4 — `grid_position_reader.py` + `blacklist_reader.py` + tests
**Files:** `signals/grid_position_reader.py`, `signals/blacklist_reader.py`,
`tests/signals/test_grid_position_reader.py`, `tests/signals/test_blacklist_reader.py`

`GridPositionReader`:
```python
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
cursor = conn.execute(
    "SELECT json_extract(config, '$.trading_pair') FROM Executors WHERE is_active = 1"
)
```
Vangt `OperationalError` af als DB niet bestaat → retourneert lege set.

`BlacklistReader`: `yaml.safe_load(open(path))`, extraheert `blacklisted_pairs`.
Vangt `FileNotFoundError` af → lege set.

**Gate:** alle state-reader tests groen, inclusief `test_existing_grid_db_not_modified`

---

### Stap 5 — `momentum_signal_scorer.py` + scorertests
**Files:** `signals/momentum_signal_scorer.py`, `tests/signals/test_momentum_signal_scorer.py`

```python
from multi_coin_grid_pro.logic.momentum_candidate_scorer import MomentumCandidateScorer

class SignalScorer:
    def __init__(self, config):
        # Vertaal 0.0-1.0 min_score naar 0-100 voor legacy scorer
        legacy_config = {..., "min_score_to_enter": config.min_score * 100.0}
        self._legacy = MomentumCandidateScorer(config=legacy_config)

    def score(self, candidate: EnrichedCandidate) -> MomentumSignal:
        trend_obj = _build_trend_obj(candidate)   # duck-typed vanuit REST-data
        raw = self._legacy.score(symbol=..., trend_obj=trend_obj, ...)
        return MomentumSignal(
            score=round(raw.score / 100.0, 4),    # ← normalisatie 0-100 → 0.0-1.0
            accepted=raw.score / 100.0 >= config.min_score,
            ...
        )
```

**Gate:** `test_score_is_in_0_to_1_range`, `test_score_is_deterministic`,
`test_score_normalized_from_legacy_0_100` groen

---

### Stap 6 — `momentum_filters.py` + filtertests
**Files:** `signals/momentum_filters.py`, `tests/signals/test_momentum_filters.py`

Pure stateless functies — geen I/O. Retourneert `FilterResult(accepted=[], rejected=[])`.

**Gate:** alle 6 filter-tests groen

---

### Stap 7 — `momentum_signal_store.py` + outputtests
**Files:** `signals/momentum_signal_store.py`, `tests/signals/test_momentum_signal_store.py`

`SignalStore.__init__` valideert dat `db_path` geen bekende grid-DB-naam bevat,
anders `ValueError`. JSON-snapshot: atomisch via `os.replace(tmp → final)`.

**Gate:** store-tests groen, forbidden-path test groen

---

### Stap 8 — `momentum_market_data.py` (REST fetcher)
**Files:** `signals/momentum_market_data.py`

`aiohttp`-based async REST fetcher. Geen Hummingbot connector. Public endpoints:
- Kraken: `GET /0/public/Ticker`, `GET /0/public/OHLC`
- OKX: `GET /api/v5/market/tickers`, `GET /api/v5/market/candles`
- Bitget: `GET /api/v2/spot/market/tickers`, `GET /api/v2/spot/market/candles`

Rate-limit guard: `asyncio.Semaphore(max_concurrent_requests)`.
Integreert `StalenessGuard` voor data-age tracking.

**Gate:** unittests met `aioresponses` mock (geen echte netwerkcalls)

---

### Stap 9 — `momentum_signal_reporter.py`
**Files:** `reporters/momentum_signal_reporter.py`,
`tests/signals/test_momentum_signal_reporter.py`

Formatter die `ScanResult` omzet naar tabel-output. Geen I/O — neemt `logging.Logger`
als dependency.

---

### Stap 10 — `momentum_signal_service.py` (main orchestrator)
**Files:** `services/momentum_signal_service.py`

```python
async def run(config: ServiceConfig) -> None:
    assert config.mode == "signal_only"      # redundante runtime guard
    logger.info("!! SIGNAL ONLY MODE — GEEN ORDERS WORDEN GEPLAATST !!")
    while True:
        result = await pipeline.scan()
        store.write(result)
        reporter.log(result)
        await asyncio.sleep(config.scan_interval_seconds)

if __name__ == "__main__":
    # python -m multi_coin_grid_pro.services.momentum_signal_service \
    #   --config multi_coin_grid_pro/config/momentum_signal_service.yaml
    asyncio.run(run(load_config(args.config)))
```

**Gate:** integratietest met volledig gemockte REST + mock grid-DBs.
Volledige AST safety check groen op alle 10 nieuwe modules.

---

### Stap 11 — Volledige suite + flake8

```bash
pytest tests/multi_coin_grid_pro/signals/ -v
flake8 multi_coin_grid_pro/signals/ \
       multi_coin_grid_pro/reporters/ \
       multi_coin_grid_pro/services/momentum_signal_service.py
```

Alle tests groen, geen flake8-fouten.

---

## 13. Architectuurdiagram

```
┌─────────────────────────────────────────────────────────────────┐
│              momentum_signal_service.py                          │
│    (apart Python process — geen Hummingbot runtime vereist)     │
│                                                                  │
│  ┌──────────────────────┐    ┌──────────────────────────────┐  │
│  │   UniverseScanner    │    │      SignalScheduler         │  │
│  │  (REST tickers)      │    │  (asyncio.sleep loop)        │  │
│  └──────────┬───────────┘    └──────────────┬───────────────┘  │
│             │                               │                   │
│  ┌──────────▼───────────────────────────────▼─────────────────┐ │
│  │                    SignalPipeline                           │ │
│  │  scan → enrich → annotate → filter → score → rank         │ │
│  └──────────────────────────────┬──────────────────────────────┘ │
│                                 │                                │
│  ┌──────────────────────────────▼────────────────────────────┐  │
│  │              ReadOnlyStateAnnotator                        │  │
│  │  GridPositionReader  BlacklistReader  CooldownReader       │  │
│  │  (read-only SQLite URI)  (yaml.safe_load)  (read-only SQL) │  │
│  └──────────────────────────────┬────────────────────────────┘  │
│                                 │                                │
│  ┌──────────────────────────────▼────────────────────────────┐  │
│  │                  SignalOutputWriter                        │  │
│  │  data/momentum_signals.sqlite  (EIGEN DB)                 │  │
│  │  data/latest_momentum_signals.json  (atomisch)            │  │
│  │  logs/momentum_signal_service.log                         │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘

[BESTAANDE BOTS — apart process, volledig ongewijzigd]
┌──────────────────┐  ┌───────────────┐  ┌──────────────────┐
│  Kraken USD bot  │  │   OKX bot     │  │   Bitget bot     │
│  (multi_coin...) │  │  (spot_okx..) │  │  (spot_bitget..) │
└──────────────────┘  └───────────────┘  └──────────────────┘
       ↑ read-only SQLite (is_active=1)
       ↑ read-only YAML (blacklist_pairs)
       ↑ read-only cooldown DB (SELECT only)
```

---

## 14. Samenvatting verboden vs. toegestaan

| Categorie | Verboden | Toegestaan |
|-----------|---------|------------|
| **Schrijven** | grid-DB, cooldown-DB, `active_coins` muteren | eigen `data/momentum_signals.sqlite`, `data/latest_momentum_signals.json` |
| **Importeren** | `CreateExecutorAction`, `StopExecutorAction`, `GridExecutorConfig`, `EntryGateway`, `BudgetAllocator`, `MomentumSleeveManager`, `CooldownStore`, `MultiCoinGridController` | `MomentumCandidateScorer`, `StalenessGuard`, `ReasonCode`, `yaml`, `aiohttp`, `sqlite3` |
| **Aanroepen** | `.buy()`, `.sell()`, `.cancel()`, `.reserve()`, `_create_table()` | `.score()`, `yaml.safe_load()`, `sqlite3.connect(uri=True)` |
| **SQLite openen** | grid-DB zonder `?mode=ro` | `file:path?mode=ro&uri=True` voor alle externe DBs |
| **Config laden** | `MultiCoinGridControllerConfig(...)` instantiëren | `yaml.safe_load(open(path))` direct |
| **Score-schaal** | 0–100 schaal extern doorgeven | Altijd 0.0–1.0 intern; wrapper normaliseert legacy scorer |
