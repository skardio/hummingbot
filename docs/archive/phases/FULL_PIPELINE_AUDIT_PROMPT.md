# Full Pipeline Technical Audit — Multi-Coin Grid Bot

> **Doel van dit document:** Geef dit als prompt aan Codex of Claude Opus voor een volledige technische analyse.
> De context hieronder is vooringevuld zodat de agent direct in de code kan duiken.
> **Geen codewijzigingen maken — alleen analyseren en rapporteren.**

---

## Agent-instructies

- Activeer de venv vóór elk Python-commando: `source ~/.venvs/bot/bin/activate`
- Codebase root: `/home/mo/repos/hummingbot/`
- Strategie-code: `multi_coin_grid_pro/`
- Lees altijd de échte bestanden. Citeer bestand + regelnummer.
- Geen aannames zonder bewijs uit de code.
- Geen codewijzigingen. Alleen analyse, tabellen en aanbevelingen.

---

## Bekend architectuuroverzicht (controleer en vul aan)

### Pipeline van pair discovery tot order

```
1. UPDATE TRENDS (alle symbolen)
   └─ trend_calculator.py → update_all_trends()
      - Fetch prijzen (batch ticker)
      - Update candles (OHLCV, 5m, max 720 candles = 60h)
      - ATR(14) berekenen en cachen op CoinTrend.atr_pct

2. COIN SELECTIE → get_top_n_coins() [trend_calculator.py ~L1527]
   ├─ 2a. Depth pre-filter (orderbook liquiditeit, optioneel)
   ├─ 2b. ATR soft pre-filter: sla over als atr_pct < (required × 0.75)
   ├─ 2c. Trend check: consensus_trend_pct vs min_trend_pct
   ├─ 2d. Ranking:
   │      - Als grid_scorer actief → GridSuitabilityScore
   │      - Als atr_use_ranking actief → 70% trend + 30% ATR blend
   │      - Else → trend strength sort
   └─ 2e. Return top N coins

3. COIN SELECTOR FILTER → filter_pairs() [logic/coin_selector.py ~L51]
   ├─ Quote asset check
   ├─ Blacklist check (handmatig in config)
   ├─ Volume check (min_24h_volume_quote)
   └─ Spread check (max_entry_spread_pct)

4. COOLDOWN CHECK
   └─ Exclude coins met actieve cooldown (get_best_coin() parameter)

5. SMARTENTRY GATES → allows_entry() [filters/smart_entry_filter.py ~L400]
   ├─ Gate 0A: Spread ≤ max_entry_spread_pct (hard reject)
   ├─ Gate 0B: Orderbook depth ≥ min_depth_multiplier × order_size (hard reject)
   ├─ Gate 1:  RSI < rsi_block_min (70) (hard reject)
   ├─ Gate 1b: RSI ≤ rsi_buy_max (72) (hard reject)
   ├─ Gate 1c: RSI > 25 (falling knife guard) (hard reject)
   ├─ Gate 2:  |VWAP dev| ≤ vwap_max_deviation_pct (12%) (hard reject)
   ├─ Gate 2A: VWAP slope guard 5m+15m (soft/shadow mode beschikbaar)
   ├─ Gate 2B: Parabolic detector (soft/shadow mode beschikbaar)
   ├─ Gate 3:  Wick ratio ≥ 0.25 (hard reject)
   ├─ Gate 4:  ATR in [min_atr_pct_for_grid, max_atr_pct_for_grid] (hard reject)
   ├─ Gate 5:  |5m spike| ≤ 2.5% (hard reject)
   ├─ Gate 6:  Trend accel 1h vs 4h ∈ [-6%, +5%] (hard reject)
   └─ Gate 7:  24h trend ∈ [-12%, +8%] (hard reject)

6. ORDER AANMAKEN
   └─ Grid executor starten met berekend grid range

7. PARALLELLE TRACK: MOMENTUM SLEEVE
   └─ momentum_candidate_scorer.py → score()
      - 25% T1h + 30% T4h + 20% vol_exp + 15% rel_strength + 5% spread + 5% rsi_wick
   └─ momentum_sleeve_manager.py → maybe_enter() (alleen paper mode)
      - Geen echte orders
      - Stop loss / take profit / trailing / max hold tracking
```

### Sleutelbestanden

| Component | Bestand | Sleutelfunctie |
|-----------|---------|----------------|
| Hoofd controller | `controllers/multi_coin_grid_controller.py` | `get_best_coin()` |
| Trend + ATR | `utils/trend_calculator.py` | `get_top_n_coins()`, `_calculate_atr_pct()` |
| Coin selector | `logic/coin_selector.py` | `filter_pairs()` |
| SmartEntry | `filters/smart_entry_filter.py` | `allows_entry()` |
| Grid suitability | `scoring/` | `GridSuitabilityScorer` |
| Momentum scorer | `logic/momentum_candidate_scorer.py` | `score()` |
| Momentum sleeve | `execution/momentum_sleeve_manager.py` | `maybe_enter()`, `update_positions()` |
| ATR calibrator | `scoring/atr_calibrator.py` | (onderzoeken) |
| Indicators | `indicators/momentum_indicators.py` | VWAP slopes, price accel |

### Actieve configs

| Bot | Config |
|-----|--------|
| Kraken USD | `multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml` |
| Kraken EUR | `multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml` |
| OKX | `multi_coin_grid_pro/spot_okx/config/spot_grid_okx.yaml` |
| Bitget | `multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml` |

### Bekende ATR drempels (controleer of dit nog klopt)

| Gate | Drempel | Configuratie key |
|------|---------|-----------------|
| Soft pre-filter selectie | `atr_pct < required × 0.75` → overgeslagen | `atr_soft_threshold` / `atr_required` |
| ATR ranking gewicht | 30% van blended score | hardcoded in trend_calculator.py |
| Trend ranking gewicht | 70% van blended score | hardcoded in trend_calculator.py |
| ATR hard gate (min) | 0.15% (CHOP) / 0.5% (default) | `min_atr_pct_for_grid` (regime-afhankelijk) |
| ATR hard gate (max) | 7.0% | `max_atr_pct_for_grid` |
| ATR(14) berekening | SMA van true ranges, 5m candles | `_calculate_atr_pct()`, period=14 |

### Bekende risico's (verifieer)

1. **abs(trend) inconsistentie:** In "long" modus gebruikt ranking raw `trend_value`, in "auto" modus `abs(tv)`. In ATR-blend wél `abs(tv)`. → Kan negatieve trend coin te hoog ranken.
2. **Blacklist dubbele laag:** Config-blacklist in `filter_pairs()` + cooldown-excludes in `get_best_coin()` — geen single source of truth.
3. **Parabolic cooldown verdwijnt bij herstart:** In-memory only, SQLite store optioneel. Gevaarlijk als bot frequent herstart.
4. **VWAP slope guard:** Als één van de twee slopes (5m of 15m) `None` is, **passeert de gate**. Beide zouden verplicht moeten zijn.
5. **ATR soft pre-filter te agressief?** Bij `required=0.80%` worden coins onder `0.60%` al overgeslagen, terwijl hard gate pas bij `0.15%` afwijst.

---

## Onderzoeksvragen

### 1. Volledige pipeline verificatie
Controleer het bovenstaande pipeline-schema:
- Klopt de volgorde en zijn er stappen midden die ontbreken?
- Zijn er stappen die in het schema staan maar in de praktijk uitgeschakeld zijn?
- Zijn er stappen die wél actief zijn maar niet in het schema staan?
- Geef per stap: bestand, functie, regelnummers, type (hard/soft/logging), en status (actief/shadow/disabled).

### 2. ATR — volledige audit
- Controleer `_calculate_atr_pct()` in `trend_calculator.py`:
  - Welk candle-interval? (5m, 1h?)
  - Hoeveel candles minimaal voor betrouwbare ATR(14)?
  - Wat retourneert de functie als `candles < 2`? En als `candles = 1`?
  - Is er een staleness-check op candles (maximale leeftijd)?
- Controleer hoe ATR soft pre-filter en hard gate samenwerken:
  - Kan een coin de soft pre-filter passeren maar de hard gate niet? Of andersom?
  - Zijn de drempels consistent tussen de twee filters?
- Is ATR consistent tussen `get_top_n_coins()` (selectie) en `allows_entry()` (SmartEntry)?
  - Wordt dezelfde `atr_pct` waarde gebruikt, of opnieuw berekend?
- Wat zijn de precieze ATR-drempels per exchange/regime? Citeer de config-waarden.

### 3. Coin selectie — 70/30 ranking audit
- Citeer de exacte blending-formule (trend_norm en atr_quality_norm berekening).
- Wordt `abs(tv)` gebruikt voor trend in de blend? En in de trend-threshold check?
- Controleer het `abs(trend)` risico: kan een coin met -8% trend hoger ranken dan een coin met +2%?
- Is dit afgevangen door regime-filter, SmartEntry trend-gate (Gate 6/7), of ergens anders?
- Worden CHOP-regime coins anders behandeld in de ranking?
- Wat is de ranking bij `grid_scorer_enabled=true`? Wordt ATR-blend dan genegeerd?

### 4. Fees, spread en grid spacing
- Hoe worden maker/taker fees ingelezen? Welk bestand, welke functie?
- Wordt `fee_model` (best-case/average/worst-case) consistent toegepast?
- Is `min_grid_level_spacing_pct` overal aanwezig en fee-realistisch?
  - Wat zijn de exacte waarden in alle 4 configs?
  - Is er een risico dat spacing kleiner is dan 2× taker fee?
- Wordt spread eenmalig of meerdere keren meegenomen (Gate 0A + in economic edge)?
- Is er een "economic edge" gate die afzonderlijk van spread checkt?

### 5. Exit logica en cooldowns
- Controleer de cooldown-mapping per close type:
  - `TAKE_PROFIT` → welke config key? (`take_profit_sec`?)
  - `STOP_LOSS` → welke config key?
  - `EARLY_STOP` → welke config key?
  - `NO_PROGRESS` → welke config key?
  - `FAILED` → welke config key?
- Is `stop_loss_sec` geïmplementeerd of nog niet?
- Werkt de TAKE_PROFIT cooldown per coin (niet globaal)?
- Controleer `_loss_streaks`:
  - Waar bijgehouden?
  - Hoe wordt `max_streak_before_blacklist` gecontroleerd?
  - Wat is de huidige waarde in de USD config?
- Zijn er conflicten tussen exit-regels (bv. trailing stop + take profit tegelijk actief)?

### 6. Blacklist audit
- Welke blacklists bestaan er? (handmatig in config, tijdelijke performance blacklist, parabolic, loss streak)
- Zijn ze onafhankelijk of kunnen ze conflicteren?
- Zijn HYPE-USD en SUI-USD correct uitgesloten van de grid maar beschikbaar voor momentum sleeve?
- Kan een blacklisted coin via een ander codepad alsnog geselecteerd worden?
- Hoe lang is de tijdelijke performance blacklist actief? Persisteert die over herstarts?

### 7. Order execution — maker/taker risico
- Worden orders post-only geplaatst?
- Wat gebeurt er bij een LIMIT_MAKER reject?
- Kan retry-logica een order alsnog taker maken?
- Zijn partial fills correct verwerkt?

### 8. Momentum sleeve integratie (nieuw, nog geen live data)
- Controleer `momentum_sleeve_manager.py`:
  - Worden `maybe_enter()` en `update_positions()` correct aangeroepen vanuit de controller?
  - Welke log-prefixen worden geëmitteerd? (`[MOMENTUM_PAPER_ENTRY]`, `[MOMENTUM_PAPER_EXIT]`, `[MOMENTUM_PAPER_SUMMARY]`)
  - Is de scoredrempel (`min_score_to_enter`) per exchange correct geconfigureerd?
- Controleer de momentum_sleeve sectie in alle 4 configs:
  - Is `mode: paper` correct ingesteld?
  - Zijn `stop_loss_pct`, `take_profit_pct`, `trailing_activation_pct`, `trailing_distance_pct`, `max_hold_minutes` aanwezig?
  - Zijn de drempels realistisch voor elk exchange?

### 9. Logging en observability
- Bestaan de volgende log-prefixen en zijn ze bruikbaar:
  - `[COIN_SELECTION_ATR_SUMMARY]`
  - `[ENTRY_REJECTED]` / `[ENTRY_APPROVED]`
  - `[HOURLY_REJECT_SUMMARY]`
  - `[MOMENTUM_PAPER_ENTRY]` / `[MOMENTUM_PAPER_EXIT]` / `[MOMENTUM_PAPER_SUMMARY]`
  - cooldown logs
  - loss-streak / blacklist logs
- Welke beslissingen zijn nog onvoldoende zichtbaar in de logs?

### 10. Configconsistentie
- Vergelijk alle 4 configs op:
  - Aanwezigheid van `momentum_sleeve` sectie
  - `min_grid_level_spacing_pct` waarden
  - ATR drempels (min/max) per regime
  - Blacklist volledigheid
  - `max_streak_before_blacklist` (moet 2 zijn, was 3)
  - Stale of onjuiste comments

### 11. Tests
- Welke tests dekken de ATR soft pre-filter?
- Welke tests dekken de 70/30 ranking?
- Welke tests dekken de cooldown-mapping per close type?
- Welke tests dekken de loss streak → blacklist logica?
- Wat zijn de top 5 ontbrekende tests met hoogste prioriteit?

### 12. Live-run analyseplan
Na een dag paper trading, welke logs en database-velden zijn het meest informatief?
Stel een concreet analyseplan op met:
- Welke log-grep commando's runnen?
- Welke SQLite queries uitvoeren?
- Wat meten per scan, per gate, per trade?

---

## Gewenste output

1. **Top 10 bevindingen** (feitelijk, met bestand:regel citaten)
2. **Top 10 risico's** (met prioriteit: kritiek / hoog / medium)
3. **Concrete aanbevelingen** per component
4. **Configwijzigingen** die eventueel nodig zijn (geen implementatie, alleen beschrijving)
5. **Codewijzigingen** die eventueel nodig zijn (geen implementatie, alleen beschrijving)
6. **Ontbrekende tests** met concrete testcases
7. **Volgende Codex-prompt** voor implementatie van de top-3 bevindingen

Geen aannames. Citeer altijd bestand + regelnummer.
