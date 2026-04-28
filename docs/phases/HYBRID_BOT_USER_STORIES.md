# Hybrid Quant Bot — User Stories

> **Datum:** 2026-04-28
> **Aanleiding:** Rally van 28 april — bot miste APE-USD (+28%), ORCA-USD (+28%) door structurele mismatch:
> grid sleeve is mean-reversion, momentum rallies worden niet gepakt.
> Regime detector stuurde slot manager niet aan (altijd `baseline`).
> **Besluit:** Bouw aparte momentum sleeve naast bestaande grid sleeve. Grid sleeve ongewijzigd.
> **Review:** Plan beoordeeld op 8.8/10. Na correcties reviewer: 9.5/10.
> **Eis:** Eerst detect-only, dan paper, dan live-small. Geen automatische promotie.

---

## Architectuuroverzicht

```
Controller (main loop)
├── GridSleeve  (bestaand, ongewijzigd)
│   ├── SmartEntryFilter
│   ├── DynamicSlotManager   ← US-F1: koppelen aan regime
│   └── GridExecutors
└── MomentumSleeve  (nieuw)
    ├── MomentumCandidateScorer   ← US-F2
    ├── MomentumSleeveManager     ← US-F3
    └── MomentumExecutors         ← US-F6: echte orders (na live-small + alt-breadth validatie)

Gedeeld:
├── RegimeDetector      ← US-F1: fix + REGIME_ROUTE logging
├── CapitalAllocator    ← US-F3: harde budgetscheiding
└── EventLogger         ← US-F4: momentum events
```

---

## Volgorde en afhankelijkheden

```
US-F1 (regime routing) → VOLTOOID + bewezen met logs
    ↓
US-F2 (scorer detect-only) → minimaal 48 uur data verzamelen
    ↓
US-F3 (paper sleeve manager) → minimaal X trades met positieve sim-PnL
    ↓
US-F4 (logging uitbreiding) → parallel met F2 en F3
    ↓
US-F5 (live-small gate + alt-breadth regime) → handmatig go/no-go door operator
    ↓
US-F6 (echte momentum orders) → aparte executor, minimaal 30 dagen live_small data
```

> **Regel:** Geen fase starten zonder bewijs van de vorige fase in de logs.
> **Regel:** Geen automatische promotie van `detect_only` → `paper` → `live_small`.
> **Regel:** Grid thresholds worden niet gewijzigd in deze implementatie.

---

## Fase 1 — Regime Routing Fix

> **Doel:** Regime detectie stuurt echt de slot manager en toekomstige momentum gate aan.
> Nog geen momentum orders. Alleen routing + logging.

---

### US-F1-01: BTC als primaire regime-input

| | |
|---|---|
| **Type** | Fix |
| **Priority** | P0 |
| **Effort** | S (< 1 uur) |
| **Bestand** | `controllers/multi_coin_grid_controller.py` |

**Probleem**
`_detect_current_regime()` zoekt BTC/ETH/SOL binnen `monitored_coins[:5]`.
`monitored_coins` bevat altcoins — BTC-USD staat er nooit in.
Fallback is `monitored_coins[0]` (willekeurige altcoin, bijv. APE).
Regime detectie meet dus de altcoin rally zelf, niet de macromarkt.

**Oplossing**
Zoek eerst direct in `trend_calculator.trends` naar `BTC-{quote}`, dan `SOL-{quote}`.
Alleen als geen van beide beschikbaar is, gebruik de bestaande altcoin-fallback.
Log welke coin als regime-input wordt gebruikt bij elke detectie.

**Acceptatiecriteria**
- [ ] `_detect_current_regime()` probeert eerst `BTC-USD` direct uit `trend_calculator.trends`
- [ ] Als BTC-USD niet beschikbaar: probeert `SOL-USD`
- [ ] Als geen van beide: valt terug op bestaande `monitored_coins[0]` logica
- [ ] Log bij startup: welke coin als regime-input gekozen is
- [ ] Bestaande smoothing (3× bevestiging) blijft intact

**Niet doen**
- BTC niet toevoegen aan `monitored_coins` (andere betekenis)
- Geen nieuwe config parameters voor deze fix

---

### US-F1-02: Slot manager ontvangt echte regime

| | |
|---|---|
| **Type** | Fix |
| **Priority** | P0 |
| **Effort** | XS (< 30 min) |
| **Bestand** | `controllers/multi_coin_grid_controller.py` |

**Probleem**
`_get_dynamic_slots_count()` gebruikt alleen `market_regime_filter` voor het regime.
`market_regime_filter` is `None` (niet geconfigureerd).
Gevolg: altijd `regime="baseline"`, altijd basislijn aantal slots.
In BULL: geen extra slots. In BEAR: geen bescherming.

**Oplossing**
Als `market_regime_filter` geen resultaat geeft: fallback naar `self._last_detected_regime`.
`_last_detected_regime` is al smoothed (3× bevestigd) en veilig om direct te gebruiken.

```python
# Na het bestaande market_regime_filter blok:
else:
    current_regime = self._last_detected_regime or "baseline"
```

**Acceptatiecriteria**
- [ ] `_get_dynamic_slots_count()` gebruikt `_last_detected_regime` als fallback
- [ ] Als `_last_detected_regime` is `None` (startup): gebruikt `"baseline"`
- [ ] BULL regime → slot multiplier > 1.0 (meer slots)
- [ ] BEAR regime → slot multiplier < 1.0 (minder slots)
- [ ] Geen wijziging aan de smoothing of het regime detectie algoritme zelf

**Niet doen**
- Geen bypass van de smoothing
- Geen directe regime detectie in deze functie (regime staat al in `_last_detected_regime`)

---

### US-F1-03: REGIME_ROUTE logging per slot-beslissing

| | |
|---|---|
| **Type** | Observability |
| **Priority** | P1 |
| **Effort** | S (1-2 uur) |
| **Bestand** | `controllers/multi_coin_grid_controller.py` |

**Probleem**
De `🌡️ REGIME:` log verschijnt alleen bij een regime-**wijziging**.
Het is daardoor onzichtbaar welk regime elke slot-beslissing aanstuurt.
Na restart weet je niet wat het initieel gedetecteerde regime is.

**Oplossing**
Voeg `[REGIME_ROUTE]` log toe elke keer dat `_get_dynamic_slots_count()` een beslissing maakt:

```
[REGIME_ROUTE] source=adaptive_detector detected=BULL normalized=BULL slots=4 balance=$1148
[REGIME_ROUTE] source=baseline (no detector) detected=None normalized=baseline slots=3 balance=$1148
[REGIME_ROUTE] source=adaptive_detector detected=BEAR normalized=BEAR slots=2 balance=$1148
```

Voeg ook een boot-log toe na de eerste succesvolle regime detectie:
```
🌡️  REGIME (initial boot): CHOP (score: 2.1, confidence: 0.71, source: BTC-USD)
```

**Acceptatiecriteria**
- [ ] `[REGIME_ROUTE]` log verschijnt bij elke aanroep van `_get_dynamic_slots_count()`
- [ ] Log bevat: `source`, `detected`, `normalized`, `slots`, `balance`
- [ ] Boot-log verschijnt na eerste succesvolle detectie (niet alleen bij wijziging)
- [ ] Log niveau: `INFO` voor `[REGIME_ROUTE]`, `INFO` voor boot-log
- [ ] Geen dubbele logs bij ongewijzigd regime (de bestaande `🌡️` log blijft alleen bij wijziging)

**Niet doen**
- Geen DEBUG logs voor deze flow (moet zichtbaar zijn in productie)
- Log niet elke seconde (alleen bij `_get_dynamic_slots_count()` aanroep)

---

### US-F1-04: Tests voor regime routing

| | |
|---|---|
| **Type** | Test |
| **Priority** | P0 |
| **Effort** | M (2-3 uur) |
| **Bestand** | `tests/unit/test_controller_methods.py` |

**Scope**
Drie unit tests in een nieuwe klasse `TestRegimeRouting`.

**Tests**

| Test | Scenario | Verwacht resultaat |
|------|----------|--------------------|
| `test_slot_manager_receives_bull_regime` | `_last_detected_regime = "BULL"`, `market_regime_filter = None` | `current_regime == "BULL"` |
| `test_slot_manager_falls_back_to_baseline_when_none` | `_last_detected_regime = None` | `current_regime == "baseline"` |
| `test_detect_regime_prefers_btc_over_altcoin` | BTC-USD en APE-USD beide in `trend_calculator.trends` | BTC-USD wordt gekozen als `sample_pair` |
| `test_detect_regime_falls_back_to_sol` | Geen BTC-USD in trends, wel SOL-USD | SOL-USD wordt gekozen |
| `test_detect_regime_falls_back_to_altcoin` | Geen BTC of SOL in trends | `monitored_coins[0]` wordt gekozen |

**Acceptatiecriteria**
- [ ] Alle 5 tests aanwezig en groen
- [ ] Tests gebruiken geen netwerk of echte exchange
- [ ] `flake8` slaagt op het testbestand

**Proof gate Fase 1**

Na implementatie van US-F1-01 t/m F1-04 geldt Fase 1 als bewezen als:
- [ ] Alle tests groen (inclusief bestaande 1641)
- [ ] `flake8` slaagt
- [ ] In de live log: `[REGIME_ROUTE]` zichtbaar per cycle
- [ ] In de live log: `🌡️ REGIME (initial boot)` zichtbaar na restart
- [ ] `regime=baseline` verdwenen uit `Dynamic slots:` debug logs
- [ ] Minimaal 1 uur live data met correcte regime in slot beslissingen

---

## Fase 2 — MomentumCandidateScorer (detect-only)

> **Doel:** Scoren en loggen van momentum kandidaten. Geen orders, geen paper posities.
> **Proof gate Fase 1 vereist** voordat Fase 2 gestart wordt.

---

### US-F2-01: MomentumCandidate datamodel

| | |
|---|---|
| **Type** | Datamodel |
| **Priority** | P0 |
| **Effort** | S |
| **Bestand** | `logic/momentum_candidate_scorer.py` (nieuw) |

**Dataclass**

```python
@dataclass
class MomentumCandidate:
    symbol: str
    score: float              # 0-100 composiet
    trend_1h: float           # % change 1 uur
    trend_4h: float           # % change 4 uur
    trend_24h: float          # % change 24 uur
    volume_expansion: float   # huidig volume / 24h gemiddelde (bijv. 2.1 = 2.1×)
    relative_strength: float  # coin 4h trend - BTC 4h trend
    spread_pct: float         # bid-ask spread %
    rsi: float
    wick_risk: float          # 0-1, hoog = bearish wick
    entry_allowed: bool
    primary_rejection_reason: Optional[str]  # None als entry_allowed=True; hoogste prioriteit reden
    all_rejection_reasons: list[str]          # alle gefaalde checks; leeg als entry_allowed=True
    regime_at_score: str      # regime op moment van scoring
    scored_at: float          # unix timestamp
```

**Acceptatiecriteria**
- [ ] Dataclass aanwezig met alle velden
- [ ] Alle velden hebben een type annotatie
- [ ] `primary_rejection_reason` is `None` als `entry_allowed=True`
- [ ] `all_rejection_reasons` is lege lijst als `entry_allowed=True`

---

### US-F2-02: MomentumCandidateScorer implementatie

| | |
|---|---|
| **Type** | Feature |
| **Priority** | P0 |
| **Effort** | L (4-6 uur) |
| **Bestand** | `logic/momentum_candidate_scorer.py` (nieuw) |

**Scoringdimensies**

| Dimensie | Gewicht | Input | Bereik |
|----------|---------|-------|--------|
| 1h trend | 25% | `trend_obj.trend_60m` | >1% = vol punten, cap bij 15% |
| 4h trend | 30% | `trend_obj.trend_240m` | >0.5% = vol punten, cap bij 10% |
| Volume expansie | 20% | `trend_obj.volume_ratio` of batch | >1.5× = vol punten, cap bij 4× |
| Relative strength vs BTC | 15% | `coin_4h - btc_4h` | positief = goed |
| Spread penalty | 5% | orderbook spread % | <0.1% = vol, >0.5% = 0 |
| RSI + wick risicopenalty | 5% | RSI, wick_ratio | hoog RSI of hoog wick = negatief |

**Alle gewichten zijn config-driven** via `momentum_sleeve.scorer_weights` in YAML.

**Entrycriteria (alles vereist voor `entry_allowed=True`)**

| Parameter | Config key | Standaard detect_only | Standaard paper | Standaard live_small |
|-----------|------------|----------------------|-----------------|----------------------|
| Min composietscore | `min_score_to_enter` | 55 | 65 | 75 |
| Min 1h trend | `momentum_1h_min_pct` | 0.5% | 0.8% | 1.0% |
| Min 4h trend | `momentum_4h_min_pct` | 1.0% | 1.5% | 2.0% |
| Max RSI | `momentum_max_rsi` | 80 | 76 | 74 |
| Min volume expansie | `momentum_min_volume_expansion` | 1.2× | 1.4× | 1.5× |
| Toegestane regimes | `momentum_regime_gate` | `["BULL", "CHOP"]` | `["BULL"]` | `["BULL"]` |

**Verhouding tot SmartEntryFilter**
De scorer hergebruikt **geen** SmartEntry code. SmartEntry is voor grid (mean reversion).
MomentumScorer heeft andere thresholds en andere afwijzing-logica.

**Rejection prioriteit (vaste volgorde; eerste gefaalde check = primary)**

| Prioriteit | Reason code |
|-----------|-------------|
| 1 (hoogst) | `MOMENTUM_REGIME_BLOCKED` |
| 2 | `MOMENTUM_DUPLICATE` |
| 3 | `MOMENTUM_COOLDOWN` |
| 4 | `MOMENTUM_POSITION_LIMIT` |
| 5 | `MOMENTUM_RSI_TOO_HIGH` |
| 6 | `MOMENTUM_VOLUME_TOO_LOW` |
| 7 | `MOMENTUM_SPREAD_TOO_WIDE` |
| 8 | `MOMENTUM_WICK_RISK_TOO_HIGH` |
| 9 (laagst) | `MOMENTUM_SCORE_TOO_LOW` |

**Acceptatiecriteria**
- [ ] `MomentumCandidateScorer.score(symbol, trend_obj, btc_trend_obj, spread, rsi, wick_risk, regime)` → `MomentumCandidate`
- [ ] Alle gewichten zijn config-driven (geen magic constants)
- [ ] `entry_allowed=False` + `primary_rejection_reason` (hoogste prioriteit) + `all_rejection_reasons` als een of meer criteria falen
- [ ] `primary_rejection_reason` volgt de vaste prioriteittabel hierboven
- [ ] Scorer is pure functie: geen netwerk, geen exchange calls
- [ ] Werkt als `btc_trend_obj` is `None` (RS = 0.0, niet crashen)

---

### US-F2-03: Detect-only kandidaat logging

| | |
|---|---|
| **Type** | Observability |
| **Priority** | P0 |
| **Effort** | S |
| **Bestand** | `controllers/multi_coin_grid_controller.py` (integratie) |

**Logformaat**

```
[MOMENTUM_CANDIDATE_ALLOWED]  APE-USD  | score=72.3 | 1h=+3.2% | 4h=+8.1% | vol_exp=2.1× | rs_vs_btc=+4.3% | rsi=58 | spread=0.08% | regime=BULL
[MOMENTUM_CANDIDATE_REJECTED] ORCA-USD | score=81.2 | primary=MOMENTUM_REGIME_BLOCKED    | all=[MOMENTUM_REGIME_BLOCKED] | regime=BEAR
[MOMENTUM_CANDIDATE_REJECTED] DOGE-USD | score=42.1 | primary=MOMENTUM_SCORE_TOO_LOW    | all=[MOMENTUM_SCORE_TOO_LOW]
[MOMENTUM_CANDIDATE_REJECTED] ZBT-USD  | score=68.4 | primary=MOMENTUM_RSI_TOO_HIGH     | all=[MOMENTUM_RSI_TOO_HIGH, MOMENTUM_SCORE_TOO_LOW] | rsi=82
```

> **Fase-onderscheid:** `[MOMENTUM_CANDIDATE_ALLOWED]` = kandidaat toegestaan, **geen positie geopend** (dat is Fase 3).
> Pas in Fase 3 verschijnen `[MOMENTUM_ENTRY_SIM]` en `[MOMENTUM_EXIT_SIM]`.

**Frequentie en throttling**
- `[MOMENTUM_CANDIDATE_ALLOWED]`: altijd loggen (verwacht: max enkele per cycle)
- `[MOMENTUM_CANDIDATE_REJECTED]`: max 1× per coin per 5 minuten (throttle per symbol); aggregate tellingen wel elke cycle
- Coins die niet gescoord worden (geen trend data) genereren geen log

**Acceptatiecriteria**
- [ ] `[MOMENTUM_CANDIDATE_ALLOWED]` gelogd voor elke coin die scoort én wordt toegelaten
- [ ] `[MOMENTUM_CANDIDATE_REJECTED]` gelogd voor elke coin die scoort maar afgewezen wordt (throttled: max 1× per coin per 5 min)
- [ ] Log bevat `primary` en `all` rejection reasons
- [ ] Log niveau: `INFO`
- [ ] Momentum logs zijn duidelijk te onderscheiden van grid logs

---

### US-F2-04: Nieuwe reason codes voor momentum

| | |
|---|---|
| **Type** | Uitbreiding |
| **Priority** | P0 |
| **Effort** | XS |
| **Bestand** | `core/reason_codes.py` |

**Toe te voegen**

```python
class Stage(str, Enum):
    MOMENTUM = "MOMENTUM"          # nieuw

class ReasonCode(str, Enum):
    # Momentum entry rejection (10 codes)
    MOMENTUM_SCORE_TOO_LOW      = "MOMENTUM_SCORE_TOO_LOW"
    MOMENTUM_REGIME_BLOCKED     = "MOMENTUM_REGIME_BLOCKED"
    MOMENTUM_CAPITAL_LIMIT      = "MOMENTUM_CAPITAL_LIMIT"
    MOMENTUM_POSITION_LIMIT     = "MOMENTUM_POSITION_LIMIT"
    MOMENTUM_COOLDOWN           = "MOMENTUM_COOLDOWN"
    MOMENTUM_DUPLICATE          = "MOMENTUM_DUPLICATE"
    MOMENTUM_RSI_TOO_HIGH       = "MOMENTUM_RSI_TOO_HIGH"
    MOMENTUM_VOLUME_TOO_LOW     = "MOMENTUM_VOLUME_TOO_LOW"
    MOMENTUM_SPREAD_TOO_WIDE    = "MOMENTUM_SPREAD_TOO_WIDE"
    MOMENTUM_WICK_RISK_TOO_HIGH = "MOMENTUM_WICK_RISK_TOO_HIGH"
    # Momentum exit reasons (4 codes)
    MOMENTUM_STOP_LOSS     = "MOMENTUM_STOP_LOSS"
    MOMENTUM_TRAILING_STOP = "MOMENTUM_TRAILING_STOP"
    MOMENTUM_TIME_STOP     = "MOMENTUM_TIME_STOP"
    MOMENTUM_REGIME_EXIT   = "MOMENTUM_REGIME_EXIT"
```

**Acceptatiecriteria**
- [ ] 1 nieuwe `Stage` waarde
- [ ] 14 nieuwe `ReasonCode` waarden (10 entry + 4 exit)
- [ ] `get_stage_for_reason()` werkt voor alle nieuwe codes

---

### US-F2-05: Tests voor MomentumCandidateScorer

| | |
|---|---|
| **Type** | Test |
| **Priority** | P0 |
| **Effort** | M |
| **Bestand** | `tests/unit/test_momentum_candidate_scorer.py` (nieuw) |

| Test | Scenario | Verwacht |
|------|----------|---------|
| `test_score_high_momentum_coin` | 1h=+3%, 4h=+8%, vol=2.5×, rsi=60 | score > 70, `entry_allowed=True` |
| `test_score_rejects_low_volume` | vol_exp=0.8× | `entry_allowed=False`, reason=`MOMENTUM_SCORE_TOO_LOW` |
| `test_score_rejects_overbought` | rsi=84 | `entry_allowed=False`, reason bevat RSI |
| `test_score_penalizes_wide_spread` | spread=0.8% | score lager dan bij spread=0.05% |
| `test_relative_strength_vs_btc` | coin_4h=+8%, btc_4h=+1% → RS=+7% | hogere score dan coin_4h=+8%, btc_4h=+7% |
| `test_no_crash_without_btc` | `btc_trend_obj=None` | geen exception, RS=0.0 |
| `test_regime_gate_blocks_bear` | `regime="BEAR"`, hoge score | `entry_allowed=False`, reason=`MOMENTUM_REGIME_BLOCKED` |
| `test_all_weights_configurable` | custom gewichten via config | gewichten toegepast in score |

**Acceptatiecriteria**
- [ ] Alle 8 tests aanwezig en groen
- [ ] Geen netwerk of exchange calls
- [ ] `flake8` slaagt

**Proof gate Fase 2**

- [ ] Alle tests groen
- [ ] `flake8` slaagt
- [ ] In live log: `[MOMENTUM_CANDIDATE_ALLOWED]` en `[MOMENTUM_CANDIDATE_REJECTED]` zichtbaar
- [ ] Minimaal 48 uur detect-only data verzameld
- [ ] Handmatige review: wijst de scorer de juiste coins aan? (operator besluit)

---

## Fase 3 — MomentumSleeveManager (paper)

> **Doel:** Gesimuleerde entries/exits bijhouden met realistische PnL (inclusief fees/slippage).
> Geen echte orders.
> **Proof gate Fase 2 vereist** (minimaal 48 uur + operator review).

---

### US-F3-01: CapitalAllocator

| | |
|---|---|
| **Type** | Feature |
| **Priority** | P0 |
| **Effort** | M |
| **Bestand** | `core/capital_allocator.py` (nieuw) |

**Harde budgetscheiding**

```yaml
# Config structuur
capital_allocation:
  grid_sleeve_pct: 0.80     # 80% van totaal
  momentum_sleeve_pct: 0.15 # 15% van totaal
  reserve_pct: 0.05         # 5% altijd onaangeroerd
```

**Invariant:** momentum sleeve mag **nooit** grid capital gebruiken.
`momentum_budget = total_balance × momentum_sleeve_pct`

**Acceptatiecriteria**
- [ ] `CapitalAllocator.get_grid_budget(balance)` → `Decimal`
- [ ] `CapitalAllocator.get_momentum_budget(balance)` → `Decimal`
- [ ] `CapitalAllocator.get_reserve(balance)` → `Decimal`
- [ ] Alle percentages intern opgeslagen als `Decimal` (niet `float`; gebruik `Decimal("0.80")` etc.)
- [ ] `capital_allocation` config is de **enige** bron voor budget-percentages — geen `capital_pct` in `momentum_sleeve:`
- [ ] Som van drie budgets = `balance` (verschil ≤ `Decimal("0.01")`)
- [ ] Als `momentum_sleeve_pct + grid_sleeve_pct + reserve_pct != Decimal("1.0")`: fout bij init

---

### US-F3-02: MomentumPosition datamodel

| | |
|---|---|
| **Type** | Datamodel |
| **Priority** | P0 |
| **Effort** | XS |
| **Bestand** | `execution/momentum_sleeve_manager.py` (nieuw) |

```python
@dataclass
class MomentumPosition:
    symbol: str
    entry_price: float
    entry_time: float         # unix timestamp
    size_quote: float         # in quote asset (USD)
    peak_price: float         # bijgewerkt elke tick voor trailing stop
    stop_price: float         # dynamisch: trailing stop of hard stop
    source_score: float       # score van de MomentumCandidate bij entry
    mode: str                 # "paper" | "live"
    simulated_entry_fee: float  # voor realistische paper PnL
```

---

### US-F3-03: MomentumSleeveManager implementatie

| | |
|---|---|
| **Type** | Feature |
| **Priority** | P0 |
| **Effort** | XL (6-8 uur) |
| **Bestand** | `execution/momentum_sleeve_manager.py` (nieuw) |

**Config keys (onder `momentum_sleeve:` in YAML)**

```yaml
momentum_sleeve:
  mode: detect_only           # disabled | detect_only | paper | live_small
  # capital wordt bepaald door capital_allocation.momentum_sleeve_pct (US-F3-01)
  max_positions: 2
  max_position_size_pct: 0.10 # max per positie als % van momentum budget
  stop_loss_pct: 0.025        # 2.5% hard stop (conservatief voor eerste fase)
  trailing_stop_pct: 0.030    # 3% trailing
  max_hold_minutes: 240
  cooldown_after_loss_minutes: 60
  slippage_model_pct: 0.001   # 0.1% voor paper PnL realistiek
  fee_pct: 0.0016             # Kraken taker fee
```

**Exit prioriteit (aflopend)**

1. Hard stop: `current_price < entry_price × (1 - stop_loss_pct)`
2. Trailing stop: `current_price < peak_price × (1 - trailing_stop_pct)` (peak bijwerken elke tick)
3. Time stop: `age_minutes > max_hold_minutes`
4. Regime exit: `_last_detected_regime == "BEAR"` → forceer exit op alle posities

**Duplicate prevention**
- `_active_positions: Dict[str, MomentumPosition]`
- Guard: `if symbol in _active_positions: return` (reason=`MOMENTUM_DUPLICATE`)
- `_cooldown_symbols: Dict[str, float]` (symbol → `cooldown_expires_at`)

**Paper PnL berekening (bid/ask/spread-aware)**
```
# Simuleer entry op ask-zijde en exit op bid-zijde:
entry_price_sim = entry_mid  × (1 + spread_pct/2 + slippage_model_pct)
exit_price_sim  = exit_mid   × (1 - spread_pct/2 - slippage_model_pct)

coins_bought = size_quote / entry_price_sim
entry_cost   = size_quote × (1 + fee_pct)
exit_value   = coins_bought × exit_price_sim × (1 - fee_pct)
paper_pnl    = exit_value - entry_cost
```

> `spread_pct` = actuele bid-ask spread op het moment van entry/exit (uit orderbook).
> Bij ontbrekende spread: gebruik `slippage_model_pct` als minimale proxy.

**Persistent state (vereist voor live_small)**
In-memory is voldoende voor `detect_only` en `paper`.
Voor `live_small`: state MOET persistent zijn (JSONL of SQLite).
Als `mode == "live_small"` en geen persistent state backend geconfigureerd: **weigeren te starten**.

> **Noot:** Persistent state implementatie is onderdeel van US-F5, niet van US-F3.

**Acceptatiecriteria**
- [ ] `maybe_enter(candidate, current_price)` → opent paper positie of logt reden
- [ ] `update_positions(prices_dict)` → bijwerken peak, stop, checken exit-condities
- [ ] `check_exits()` → retourneert lijst van te sluiten posities met exitreden
- [ ] `get_paper_pnl_summary()` → totale sim-PnL, win rate, gemiddelde hold-tijd
- [ ] Hard stop, trailing stop, time stop, regime exit werken correct
- [ ] Duplicate prevention werkt correct
- [ ] Cooldown werkt correct na verlies
- [ ] PnL berekening bevat fees en slippage

---

### US-F3-04: Paper logging

| | |
|---|---|
| **Type** | Observability |
| **Priority** | P0 |
| **Effort** | S |
| **Bestand** | `execution/momentum_sleeve_manager.py` |

**Logformaat**

```
[MOMENTUM_ENTRY_SIM]   APE-USD | price=$1.234 | size=$115 | stop=$1.203 (-2.5%) | trailing=$1.197 (-3%) | score=72.3
[MOMENTUM_EXIT_SIM]    APE-USD | reason=TRAILING_STOP | entry=$1.234 | exit=$1.289 | gross=+$4.50 | fees=$0.37 | net=+$4.13 | hold=47min
[MOMENTUM_EXIT_SIM]    ZBT-USD | reason=STOP_LOSS | entry=$0.821 | exit=$0.800 | gross=-$2.42 | fees=$0.26 | net=-$2.68 | hold=12min
[MOMENTUM_EXIT_SIM]    ORCA-USD| reason=REGIME_EXIT | entry=$1.512 | exit=$1.489 | gross=-$1.38 | fees=$0.24 | net=-$1.62 | hold=31min
[MOMENTUM_DAILY_SIM]   trades=7 | winners=5 | losers=2 | net_pnl=+$12.40 | win_rate=71.4% | avg_hold=52min
```

**Acceptatiecriteria**
- [ ] `[MOMENTUM_ENTRY_SIM]` bij elke paper entry
- [ ] `[MOMENTUM_EXIT_SIM]` bij elke paper exit inclusief netto PnL na fees/slippage
- [ ] `[MOMENTUM_DAILY_SIM]` dagelijks (zelfde interval als WHY-NO-TRADE)
- [ ] Exit-reden altijd vermeld

---

### US-F3-05: WHY-NO-TRADE uitbreiding met momentum sectie

| | |
|---|---|
| **Type** | Observability |
| **Priority** | P1 |
| **Effort** | M |
| **Bestand** | `observability/why_no_trade_v2.py` |

**Aanpassing:** voeg aparte momentum sectie toe aan het uursrapport.
Grid statistieken en momentum statistieken worden **niet** gemengd.

```
[MOMENTUM SUMMARY] Last 1 hours
  Candidates evaluated: 34
  Simulated entries: 3 (APE-USD ×2, ORCA-USD ×1)
  Open paper positions: 1 (APE-USD, hold=34min, unrealized=+$2.10)
  Rejected: 31
    MOMENTUM_REGIME_BLOCKED: 18 (52.9%)
    MOMENTUM_SCORE_TOO_LOW:  13 (38.2%)
```

**Acceptatiecriteria**
- [ ] Momentum sectie verschijnt apart van grid sectie in WHY-NO-TRADE
- [ ] Telt candidates, simulated entries, open posities, en rejection breakdown
- [ ] Als momentum mode `disabled` of `detect_only`: sectie vermeldt dit expliciet

---

### US-F3-06: Tests voor MomentumSleeveManager

| | |
|---|---|
| **Type** | Test |
| **Priority** | P0 |
| **Effort** | L |
| **Bestand** | `tests/unit/test_momentum_sleeve_manager.py` (nieuw) |

| Test | Scenario | Verwacht |
|------|----------|---------|
| `test_capital_allocation_respects_pct` | budget = 15% van $1000 | `momentum_budget == $150` |
| `test_max_positions_blocks_entry` | 2 open posities, max=2 | derde entry geweigerd, reason=`MOMENTUM_POSITION_LIMIT` |
| `test_stop_loss_triggers` | prijs daalt 3% onder entry | positie gesloten, reason=STOP_LOSS |
| `test_trailing_stop_updates_peak` | prijs stijgt → daalt | peak bijgewerkt, trailing stop berekend van peak |
| `test_trailing_stop_triggers` | prijs 5% boven peak, daalt 3% van peak | positie gesloten |
| `test_time_stop_triggers` | hold time overschreden | positie gesloten, reason=TIME_STOP |
| `test_cooldown_prevents_reentry` | verlies gesloten → directe reentry | geweigerd, reason=`MOMENTUM_COOLDOWN` |
| `test_duplicate_position_prevented` | APE-USD al open → nieuw entry APE-USD | geweigerd, reason=`MOMENTUM_DUPLICATE` |
| `test_regime_gate_blocks_bear` | `regime="BEAR"` | entry geweigerd, reason=`MOMENTUM_REGIME_BLOCKED` |
| `test_bear_regime_forces_exit` | open positie, regime wisselt naar BEAR | positie gesloten, reason=REGIME_EXIT |
| `test_paper_pnl_includes_fees` | exit met winst | netto PnL = bruto - fees - slippage |
| `test_capital_allocator_sum` | grid + momentum + reserve = balance | geen afwijking buiten afrondingsfout |

**Proof gate Fase 3**

- [ ] Alle tests groen (inclusief F1 en F2)
- [ ] `flake8` slaagt
- [ ] In live log: `[MOMENTUM_ENTRY_SIM]`, `[MOMENTUM_EXIT_SIM]`, `[MOMENTUM_DAILY_SIM]` zichtbaar
- [ ] WHY-NO-TRADE bevat aparte momentum sectie
- [ ] Minimaal X dagen paper trades verzameld (operator beslist)
- [ ] Sim win-rate > 50% en positieve netto sim-PnL (minimale lat voor live-small)

---

## Fase 4 — EventLogger uitbreiding

> Loopt parallel met Fase 2 en 3. Geen afhankelijkheid van live-small gate.

---

### US-F4-01: Momentum events in EventLogger

| | |
|---|---|
| **Type** | Observability |
| **Priority** | P1 |
| **Effort** | S |
| **Bestand** | `observability/event_logger.py` |

**Uitbreiding:** voeg `emit_momentum_candidate()`, `emit_momentum_entry_sim()`, `emit_momentum_exit_sim()` toe.
Zelfde JSONL structuur als bestaande events.

**Acceptatiecriteria**
- [ ] Drie nieuwe emit-methoden aanwezig
- [ ] JSONL events bevatten `stage=MOMENTUM` en de juiste velden
- [ ] Feature-flagged: alleen actief als `observability.structured_events_enabled=true`

---

## Fase 5 — Live-Small Gate

> **Proof gate Fase 3 vereist** + handmatig go/no-go door operator.
> Persistent state is verplicht voordat live_small geactiveerd kan worden.

---

### US-F5-01: Persistent position state voor live-small

| | |
|---|---|
| **Type** | Feature |
| **Priority** | P0 (blocker voor live_small) |
| **Effort** | M |
| **Bestand** | `execution/momentum_sleeve_manager.py` + nieuw `persistence/momentum_state.py` |

**Vereiste:** als `mode == "live_small"` en geen persistent state backend: bot weigert te starten met duidelijke foutmelding.

**Persistentiestrategie:** twee bestanden (auditeerbaar + snel herstelbaar).

```
momentum_state_snapshot.json   ← actuele open posities (overschreven na elke mutatie)
momentum_state_events.jsonl    ← audit trail van alle entries/exits
```

Bij herstart: laad open posities uit snapshot, herbereken stop-prices en trailing stops,
log wat er was. Gebruik events-JSONL niet als primaire herstel-bron (foutgevoelig bij replay).

**Acceptatiecriteria**
- [ ] Open posities worden opgeslagen in snapshot na elke entry/exit
- [ ] Elke mutatie wordt ook geappendeerd aan events-JSONL (audit trail)
- [ ] Bij herstart: posities herladen uit snapshot, niet JSONL-replay
- [ ] Als snapshot ontbreekt bij `live_small` mode: weigeren te starten
- [ ] Herladen positions loggen zodat operator weet wat er was

---

### US-F5-02: Live-small mode gate in config

| | |
|---|---|
| **Type** | Config |
| **Priority** | P0 |
| **Effort** | S |
| **Bestand** | `controllers/multi_coin_grid_config.py` |

**Config voor live_small (conservatief beginnen)**

```yaml
momentum_sleeve:
  mode: live_small
  # capital_pct staat NIET hier; zie capital_allocation.momentum_sleeve_pct: 0.05
  max_positions: 1            # 1 tegelijk — NIET 2
  max_position_size_pct: 0.05 # max 5% per positie
  min_score_to_enter: 75      # hoge drempel
  stop_loss_pct: 0.025
  trailing_stop_pct: 0.030
  max_hold_minutes: 240
  cooldown_after_loss_minutes: 60
  regime_gate: ["BULL"]       # alleen BULL — NIET CHOP
```

**Validatie bij startup**
- [ ] Als `mode == "live_small"` en `min_score_to_enter < 70`: waarschuwing + weigeren
- [ ] Als `mode == "live_small"` en `capital_pct > 0.10`: waarschuwing + weigeren
- [ ] Als `mode == "live_small"` en geen persistent state: ERROR + weigeren

---

### US-F5-03: Alt-breadth regime (verplicht vóór Fase 6)

| | |
|---|---|
| **Type** | Feature |
| **Priority** | P0 (blocker voor F6) |
| **Effort** | M |
| **Bestand** | `controllers/multi_coin_grid_controller.py` (uitbreiding van US-F1-01) |

**Probleem**
BTC-USD als enige regime-input is onvoldoende voor alt momentum. BTC kan rustig zijn
terwijs ORCA/APE/PENGU uitbreken. Alt-breadth meet hoeveel altcoins tegelijk momentum hebben.

**Oplossing**
`alt_breadth_score = (coins met momentum_1h > threshold) / len(monitored_coins)`
Combineer met macro-regime (BTC) tot een `composite_regime`:
- BTC=BULL + alt_breadth > 0.4 → `composite_regime = BULL`
- BTC=CHOP + alt_breadth > 0.5 → `composite_regime = BULL`
- alt_breadth < 0.2 → `composite_regime = BEAR` (ongeacht BTC)

**Acceptatiecriteria**
- [ ] `alt_breadth_score` berekend op basis van `monitored_coins` in elk regime-detectie cycle
- [ ] `composite_regime` combineert BTC-trend en alt-breadth
- [ ] `[REGIME_ROUTE]` log uitgebreid met `alt_breadth=X.XX`
- [ ] Config key `momentum_sleeve.alt_breadth_threshold` (standaard: 0.40)
- [ ] Bestaande BTC/SOL fallback blijft intact

**Niet doen**
- Geen wijziging aan grid sleeve gedrag op basis van alt-breadth

---

## Fase 6 — MomentumExecutor (echte orders)

> **Buiten scope van huidige implementatie.**
> **Proof gate Fase 5 vereist** + minimaal 30 dagen live_small paper data + handmatig go/no-go.
> **Alt-breadth regime verplicht** (US-F5-03 voltooid).

---

### US-F6-01: MomentumExecutor live-small

| | |
|---|---|
| **Type** | Toekomstige fase |
| **Priority** | OUT OF SCOPE (gepland na Fase 5) |

**Vereisten**
- Apart executor type — momentum trades gebruiken **geen** `GridExecutors`
- Alt-breadth regime actief (US-F5-03 voltooid)
- Minimaal 30 dagen positieve paper sim-PnL
- Handmatig go/no-go door operator

> Dit wordt pas gepland na 30+ dagen live_small data.

---

## Overzicht alle stories

| ID | Titel | Fase | Effort | Priority | Status |
|----|-------|------|--------|----------|--------|
| US-F1-01 | BTC als regime-input | 1 | S | P0 | ⬜ |
| US-F1-02 | Slot manager ontvangt regime | 1 | XS | P0 | ⬜ |
| US-F1-03 | REGIME_ROUTE logging | 1 | S | P1 | ⬜ |
| US-F1-04 | Tests regime routing | 1 | M | P0 | ⬜ |
| US-F2-01 | MomentumCandidate datamodel | 2 | S | P0 | ⬜ |
| US-F2-02 | MomentumCandidateScorer | 2 | L | P0 | ⬜ |
| US-F2-03 | Detect-only kandidaat logging | 2 | S | P0 | ⬜ |
| US-F2-04 | Nieuwe reason codes | 2 | XS | P0 | ⬜ |
| US-F2-05 | Tests MomentumCandidateScorer | 2 | M | P0 | ⬜ |
| US-F3-01 | CapitalAllocator | 3 | M | P0 | ⬜ |
| US-F3-02 | MomentumPosition datamodel | 3 | XS | P0 | ⬜ |
| US-F3-03 | MomentumSleeveManager | 3 | XL | P0 | ⬜ |
| US-F3-04 | Paper logging | 3 | S | P0 | ⬜ |
| US-F3-05 | WHY-NO-TRADE uitbreiding | 3 | M | P1 | ⬜ |
| US-F3-06 | Tests MomentumSleeveManager | 3 | L | P0 | ⬜ |
| US-F4-01 | EventLogger uitbreiding | 4 | S | P1 | ⬜ |
| US-F5-01 | Persistent position state | 5 | M | P0 | ⬜ |
| US-F5-02 | Live-small config gate | 5 | S | P0 | ⬜ |
| US-F5-03 | Alt-breadth regime | 5 | M | P0 (blocker F6) | ⬜ |
| US-F6-01 | MomentumExecutor live-small | 6 | — | OUT OF SCOPE | 🔒 |

---

## Niet-functionele eisen

| Eis | Geldig voor |
|-----|-------------|
| Geen wijzigingen aan grid entry thresholds | Alle fasen |
| Momentum trades gebruiken geen GridExecutors | Fase 6+ |
| Alle nieuwe code slaagt voor `flake8` | Alle fasen |
| Geen netwerk/exchange calls in unit tests | Alle fasen |
| Config-driven: geen magic constants | Alle fasen |
| Fail-closed: als momentum module faalt → grid gaat door, momentum stopt | Fase 2+ |
| Persistent state verplicht bij `live_small` | Fase 5 |
| Geen automatische promotie tussen modes | Alle fasen |
| Alt-breadth regime verplicht vóór echte momentum orders | Fase 6 (blocker) |
| `Decimal` voor alle capital/budget berekeningen | Fase 3+ |
