# 🚀 Futures Grid Strategy - Verbeter Roadmap

> **Datum**: 7 februari 2026
> **Strategie**: FuturesGridBitgetController v3.3
> **Status**: Production (live trading)
> **Reviewed by**: External risk consultant

---

## 📊 Huidige Strategie Analyse

### ✅ Wat al GOED is (professionele elementen)

| Element | Implementatie | Status |
|---------|---------------|--------|
| **RiskGuard** | 6 kill-switches (loss, time, depth, starvation, trend, ATR) | ✅ Done |
| **Multi-timeframe filtering** | 1h, 4h, 24h trend checks voor entry | ✅ Done |
| **Position sizing** | `risk_reference_balance × max_risk_per_trade` | ✅ Done |
| **Exchange-side TPSL** | Bitget SL order als safety net | ✅ Done |
| **AUTO direction** | LONG bij uptrend, SHORT bij downtrend | ✅ Done |
| **ATR-based grids** | Volatility-adaptive grid ranges | ✅ Done |
| **Leverage control** | Conservatief 5x default | ✅ Done |

### ⚠️ Verschil met Institutional Trading

| Aspect | Huidige Bot | Institutioneel |
|--------|-------------|----------------|
| Execution | 1 exchange (Bitget) | Multi-exchange, OTC, dark pools |
| Strategy | Grid (mean reversion) | Diversified portfolio |
| Data | Exchange API candles | Order flow, whale tracking, on-chain |
| Funding | Betalen (kost geld) | Verdienen of hedgen |
| Risk/trade | 5% van balance | 0.5-2% max |
| Correlation | Geen check | Portfolio-brede hedges |
| **Portfolio caps** | Alleen per-trade limits | Total exposure + notional caps |

---

## 🔴 HIGH PRIORITY Verbeteringen

### 1. Risk Per Trade + Portfolio Exposure Cap

**Probleem**: Bij 5x leverage en 5% risk = 25% echte exposure per positie.
**Extra probleem**: Alleen per-trade risk verlagen helpt niet als je 10 grids tegelijk opent!

**Huidige config**:
```yaml
risk_max_balance_per_trade_pct: 5.0  # Te hoog!
# Geen portfolio-brede caps!
```

**Aanbevolen** (drielaags bescherming):
```yaml
# LAAG 1: Per-trade risk
risk_max_balance_per_trade_pct: 2.0       # Max 2% risk per individuele trade

# LAAG 2: Portfolio position caps
max_open_positions: 4                      # Max 4 grids tegelijk
max_total_risk_pct: 8.0                    # Max 8% totale risk (4 × 2%)

# LAAG 3: Notional exposure cap (leverage-aware)
max_notional_exposure_pct: 150.0           # Max 150% van balance als notional
                                           # Bij 5x leverage en €1000 balance:
                                           # Max €1500 notional = €300 margin used
```

**Waarom alle 3 lagen?**
| Laag | Beschermt tegen |
|------|-----------------|
| Per-trade | Enkele grote loss |
| Total risk | Te veel simultane grids |
| Notional cap | Leverage explosion (margin call) |

**Impact**:
- Kleinere verliezen per mislukte trade
- Begrenst simultane exposure
- Voorkomt margin call bij flash crash
- Betere risk-adjusted returns (Sharpe ratio)

**Implementatie**:
- [x] Per-trade: Config change only ✅ **DONE** (2.0% in YAML)
- [x] Portfolio caps: Check in `_create_grid_action()` → `_check_portfolio_exposure_caps()` ✅ **DONE**
- [x] Notional cap: Check current notional vs balance × max_notional_exposure_pct ✅ **DONE**

**Files gewijzigd**:
- `futures_bitget/config_schema.py` - Nieuwe fields toegevoegd
- `futures_bitget/config/futures_grid_bitget.yaml` - Three-layer config
- `futures_bitget/controller.py` - `_check_portfolio_exposure_caps()` method

---

### 2. Funding Rate Filter (Direction-Aware)

**Probleem**: Je betaalt funding fees elke 8 uur. Bij hoge funding (0.1% = 0.3%/dag) eet dit winst op.

**BELANGRIJK**: Funding is niet altijd kosten! Het hangt af van je direction:
- **Positieve funding rate**: LONGS betalen, SHORTS ontvangen
- **Negatieve funding rate**: SHORTS betalen, LONGS ontvangen

**Oplossing**: Direction-aware filter die alleen blokkeert als JIJ betaalt.

**Nieuwe config parameters**:
```yaml
# Funding Rate Filter (Direction-Aware)
funding_rate_filter_enabled: true
max_funding_cost_pct: 0.03            # Skip als JIJ > 0.03% moet betalen
                                       # Maar accepteer als je ONTVANGT!
funding_rate_cache_seconds: 300        # Cache funding rate 5 min
log_funding_decision: true             # Log: "LONG skipped: funding=+0.05% (pay)"
                                       # Log: "SHORT entered: funding=+0.05% (receive)"
```

**Logica**:
```python
def should_skip_for_funding(symbol: str, direction: str) -> bool:
    funding_rate = get_funding_rate(symbol)  # e.g., +0.05%

    if direction == "LONG":
        # Positive funding = LONGS pay
        cost = funding_rate if funding_rate > 0 else 0
    else:  # SHORT
        # Positive funding = SHORTS receive (negative cost)
        cost = -funding_rate if funding_rate > 0 else abs(funding_rate)

    if cost > max_funding_cost_pct:
        log(f"{direction} skipped: funding={funding_rate}% (pay {cost}%)")
        return True
    elif cost < 0:
        log(f"{direction} bonus: funding={funding_rate}% (receive {abs(cost)}%)")
    return False
```

**Implementatie**:
- [x] API call naar Bitget funding rate endpoint (`/api/mix/v1/market/current-fundRate`) ✅ **DONE**
- [x] Cache mechanism (funding verandert max elke 8h) ✅ **DONE**
- [x] Direction-aware check: LONG vs SHORT betaalt/ontvangt ✅ **DONE**
- [x] Filter in `_check_funding_rate_filter()` method ✅ **DONE**
- [x] Logging met `funding_side=pay/receive` ✅ **DONE**

**Files gewijzigd**:
- `futures_bitget/config_schema.py` - Funding filter config fields
- `futures_bitget/config/futures_grid_bitget.yaml` - Funding rate config
- `futures_bitget/controller.py` - `_check_funding_rate_filter()`, `_get_cached_funding_rate()`, `_update_funding_rate_cache()` methods

---

### 3. Correlatie Check

**Probleem**: BTC en ETH dumpen vaak samen. Als je beide tradt, verlies je dubbel.

**Oplossing**: Max 1 positie per correlatie-groep.

**Nieuwe config**:
```yaml
# Correlation Filter
correlation_filter_enabled: true
max_correlated_positions: 1

correlation_groups:
  major_caps:
    - BTC-USDT
    - ETH-USDT

  layer1_alts:
    - SOL-USDT
    - AVAX-USDT
    - DOT-USDT
    - NEAR-USDT

  layer2:
    - ARB-USDT
    - OP-USDT
    - POL-USDT

  meme_coins:
    - DOGE-USDT
    - SHIB-USDT
    - PEPE-USDT
    - WIF-USDT

  ai_tokens:
    - FET-USDT
    - TAO-USDT
    - WLD-USDT
```

**Implementatie**:
- [x] Config schema update voor correlation_groups ✅ **DONE**
- [x] Check in `_check_correlation_filter()` of correlatie groep al bezet is ✅ **DONE**
- [x] `_get_correlation_group()` helper method ✅ **DONE**
- [x] Logging van skipped coins door correlatie ✅ **DONE**

**Files gewijzigd**:
- `futures_bitget/config_schema.py` - `correlation_groups: dict` field
- `futures_bitget/config/futures_grid_bitget.yaml` - Correlation groups config
- `futures_bitget/controller.py` - `_check_correlation_filter()`, `_get_correlation_group()` methods

---

## 🟠 MEDIUM PRIORITY Verbeteringen

### 4. Trailing Stop (Profit Lock)

**Probleem**: Bij +3% unrealized PnL kan de markt draaien en verlies je alles.

**Oplossing**: Trailing stop die winst lockt.

**Nieuwe config**:
```yaml
# Profit Protection
trailing_stop_enabled: true
trailing_stop_activation_pct: 2.0   # Activeer na +2% profit
trailing_stop_distance_pct: 1.0     # Max 1% teruggeven van top
```

**Logica**:
```
1. Grid heeft +2.5% unrealized PnL
2. Trailing stop activeert (threshold = 2%)
3. High water mark = +2.5%
4. Prijs daalt, PnL = +1.8%
5. Distance van high = 0.7% (< 1% allowed)
6. Prijs daalt meer, PnL = +1.4%
7. Distance = 1.1% (> 1% allowed)
8. TRAILING STOP TRIGGERED → close grid met +1.4% profit
```

**Implementatie**:
- [x] Track high water mark per grid in `_trailing_stop_state` dict ✅ **DONE**
- [x] Check in `determine_executor_actions()` voor trailing stop trigger ✅ **DONE**
- [x] Nieuwe exit reason: `TRAILING_STOP` ✅ **DONE**
- [x] `_check_trailing_stop()` method geïmplementeerd ✅ **DONE**
- [x] `_reset_trailing_stop()` voor cleanup na close ✅ **DONE**

**Files gewijzigd**:
- `futures_bitget/config_schema.py` - Trailing stop config fields
- `futures_bitget/config/futures_grid_bitget.yaml` - Trailing stop config
- `futures_bitget/controller.py` - `_check_trailing_stop()`, `_reset_trailing_stop()` methods

---

### 5. Grid Timeout Dynamisch op Volatiliteit

**Probleem**: Vaste 1 uur timeout. In sideways market kan grid 4-6 uur nodig hebben.

**Oplossing**: Timeout baseren op ATR/volatiliteit.

**Nieuwe config**:
```yaml
# Dynamic Timeout
dynamic_timeout_enabled: true
base_grid_timeout_seconds: 3600     # 1 uur basis
low_volatility_multiplier: 2.0      # 2 uur bij lage vol
high_volatility_multiplier: 0.5     # 30 min bij hoge vol
volatility_threshold_low: 0.5       # ATR < 0.5% = laag
volatility_threshold_high: 2.0      # ATR > 2.0% = hoog
```

**Implementatie**:
- [x] `_get_dynamic_timeout()` method geïmplementeerd ✅ **DONE**
- [x] Volatility-based timeout multiplier ✅ **DONE**
- [x] Integration met `_create_grid_action()` ✅ **DONE**

**Files gewijzigd**:
- `futures_bitget/config_schema.py` - Dynamic timeout config fields
- `futures_bitget/config/futures_grid_bitget.yaml` - Dynamic timeout config
- `futures_bitget/controller.py` - `_get_dynamic_timeout()` method

---

### 6. Liquidation Heatmap Awareness

**Probleem**: Je weet niet waar grote liquidatie clusters zitten.

**Oplossing**: Gebruik Bitget's liquidation data of externe API (Coinglass).

**Data sources**:
- Bitget API: Geen publieke liquidation data
- Coinglass API: $50-200/maand voor liquidation heatmaps
- Alternatief: Track large Open Interest changes als proxy

**Implementatie**:
```yaml
# Liquidation Awareness (requires external data)
liquidation_awareness_enabled: false  # Requires Coinglass subscription
coinglass_api_key: ""
avoid_liquidation_clusters: true
```

**Geschatte tijd**: 8+ uur (complex, externe API)

---

## 🟡 LOW PRIORITY / Nice-to-Have

### 7. Order Flow Analysis

**Wat het is**: Analyseer buy/sell pressure op orderbook.

**Waarom nuttig**: Detecteer whale accumulation/distribution.

**Complexiteit**: Hoog - vereist tick-level data processing.

**Status**: Future consideration

---

### 8. Multi-Exchange Arbitrage

**Wat het is**: Dezelfde positie op meerdere exchanges voor betere prijzen.

**Waarom nuttig**: Betere execution, lagere slippage.

**Complexiteit**: Zeer hoog - funding, settlement, capital efficiency.

**Status**: Out of scope voor solo trader

---

### 9. Options Hedging

**Wat het is**: Koop puts om downside te hedgen.

**Waarom nuttig**: Defined risk, behoud upside.

**Complexiteit**: Hoog - vereist options kennis en capital.

**Status**: Future consideration

---

## 📁 Code Architectuur Vraag

### Moet Futures gescheiden zijn van Spot?

**Huidige structuur**:
```
multi_coin_grid_pro/
├── controllers/
│   └── multi_coin_grid_controller.py  # Base (shared logic)
├── spot_bitget/
│   └── controller.py                   # Spot-specific
├── futures_bitget/
│   └── controller.py                   # Futures-specific (inherits base)
```

**Analyse**:

| Aspect | Samen houden | Splitsen |
|--------|--------------|----------|
| **Code reuse** | ✅ Grid logic is 70% identiek | ❌ Duplicatie |
| **Maintenance** | ✅ 1 plek voor bug fixes | ❌ 2 plekken |
| **Complexity** | ❌ Meer `if futures:` checks | ✅ Schonere code |
| **Config** | ❌ Verwarrend (spot + futures params) | ✅ Duidelijk |
| **Testing** | ✅ Shared test suite | ❌ Aparte tests |
| **Risk** | ❌ Spot bug kan futures breken | ✅ Isolatie |

**AANBEVELING**:

**Houd de huidige structuur** (inheritance model) maar:

1. **Maak duidelijke scheiding in config files**:
   - `spot_bitget/config/` → alleen spot params
   - `futures_bitget/config/` → alleen futures params (al zo!)

2. **Documenteer welke base methods overridden zijn**:
   ```python
   # In futures_bitget/controller.py
   # OVERRIDDEN METHODS:
   # - _get_executor_actions()  → adds TPSL logic
   # - _can_open_new_grid()     → adds leverage checks
   # - _create_grid_proposal()  → adds SHORT support
   ```

3. **Als futures significant groeit** (>50% unieke code):
   - Dan pas splitsen naar apart project
   - Nu is ~30% uniek (TPSL, leverage, SHORT)

**Conclusie**: Huidige architectuur is prima. Niet splitsen tenzij futures >50% unieke code krijgt.

---

## 📅 Implementatie Roadmap

### Sprint 1 (✅ COMPLETE - 7 feb 2026)
- [x] **Risk per trade** verlagen naar 2% (config change) ✅
- [x] **Portfolio exposure caps** implementeren (3 lagen) ✅
- [x] **Config schema** uitgebreid met nieuwe parameters ✅

### Sprint 2 (✅ COMPLETE - 7 feb 2026)
- [x] **Funding rate filter** geïmplementeerd ✅
  - API call naar Bitget funding rate endpoint
  - Cache mechanism met 5 min expiry
  - Direction-aware check (LONG betaalt bij positief, SHORT ontvangt)
  - Integrated in `_create_grid_action()`
- [x] **Correlatie filter** geïmplementeerd ✅
  - Correlation groups in config schema (dict type)
  - `_check_correlation_filter()` method
  - `_get_correlation_group()` helper
  - Max 1 positie per correlatie groep

### Sprint 3 (✅ COMPLETE - 7 feb 2026)
- [x] **Trailing stop** geïmplementeerd ✅
  - `_trailing_stop_state` dict voor high water mark tracking
  - `_check_trailing_stop()` method met activation en distance logic
  - Integrated in `determine_executor_actions()`
  - `_reset_trailing_stop()` voor cleanup
- [x] **Dynamic timeout** op volatiliteit ✅
  - `_get_dynamic_timeout()` method
  - Volatility-based multipliers (low/high)
  - Integrated in `_create_grid_action()`

### 📝 Unit Tests (✅ COMPLETE)
- [x] **32 unit tests** in `tests/unit/test_futures_sprint_features.py` ✅
  - 5 tests voor Portfolio Exposure Caps
  - 6 tests voor Funding Rate Filter
  - 5 tests voor Correlation Filter
  - 6 tests voor Trailing Stop
  - 4 tests voor Dynamic Timeout
  - 2 tests voor Integration
  - 4 tests voor Config Schema

### Backlog (Not Started)
- Liquidation awareness (requires subscription)
- Order flow analysis
- Multi-exchange support

---

## 📈 Expected Impact

| Verbetering | Risk Reduction | Profit Impact |
|-------------|----------------|---------------|
| Risk 5%→2% | -60% max loss | -20% trade size |
| Funding filter | Vermijdt -0.3%/dag | +5-10% netto |
| Correlatie | -50% correlated loss | Neutral |
| Trailing stop | Lock +50% van unrealized | +10-20% realized |

**Totaal verwacht**:
- **Risk**: 40-50% reductie in max drawdown
- **Returns**: +10-15% netto door betere exits en minder fees

---

## 📝 Notities

- Altijd eerst paper trading testen bij grote changes
- Monitor funding rates handmatig voor nu
- Correlatie groepen moeten periodiek geüpdatet worden (markt verandert)

---

*Document laatst bijgewerkt: 7 februari 2026*
