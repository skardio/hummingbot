# Pre-Masterplan v2 — Optimalisatie Backlog

> **Datum:** 2026-04-07
> **Bijgewerkt:** 2026-04-25
> **Aanleiding:** Implementatie van 5 features (regime-first selectie, fee-aware filter, enhanced cooldowns, dual selection models, regime-based timeouts) is **live**. Dit document bevat de volgende ronde verbeteringen, geprioriteerd van hoog naar laag impact.
> **Status:** Architectuur correct, nu optimalisatie en intelligentie toevoegen.

---

## Samengevat

| # | Verbetering | Prioriteit | Complexiteit | Wanneer |
|---|-------------|-----------|-------------|---------|
| V2-01 | ~~Dynamic fee model~~ | ✅ **DONE** | — | Fase A: `fee_model: worst_case \| average \| best_case` |
| V2-02 | ~~Regime smoothing (anti-nervositeit)~~ | ✅ **DONE** | — | `regime_smoothing_count: 3` — vereist 3 opeenvolgende detections |
| V2-03 | ~~CHOP ranking niet hard genoeg~~ | ✅ **DONE** | — | Opgelost: `chop_max_trend_pct` filter |
| V2-04 | ~~Expected-fill profitability model~~ | ✅ **DONE** | — | Shadow mode actief — `hourly_profit_check_enabled: false` |
| V2-05 | Pattern-aware cooldowns | P2 | Medium | Na 100+ trades data |
| V2-06 | ~~BEAR-light mode~~ | ✅ **DONE** | — | Auto BEAR-light actief (`bear_auto_light_enabled: true`) |
| V2-07 | Per-coin adaptive timeouts | P3 | Medium | Na ATR-data per coin beschikbaar |

---

## V2-01: Dynamic Fee Model

**Probleem:** Vaste 0.52% round-trip (taker) is conservatief maar niet accuraat.
- Soms ben je maker (0.32% RT) → filter is te streng, mist goede trades
- Fee kan veranderen per volume tier op Kraken/Bitget
- Mix van maker+taker per grid (buy=maker, sell=taker) is realistischer

**Oplossing:**
1. **Fase A:** Configureerbare worst-case vs best-case (`fee_model: worst_case | average | best_case`)
2. **Fase B:** Dynamic fee uit exchange API (`GET /0/private/TradeVolume` op Kraken)
3. **Fase C:** Per-order fee tracking: log actual fee per fill, update model real-time

**Acceptance criteria:**
- [x] Fee model configureerbaar in yaml (worst/avg/best) — ✅ Fase A geïmplementeerd
- [ ] Kraken API call voor actual fee tier (Fase B — toekomstig)
- [x] Unit tests met mock exchange data

**Prioriteit:** P1 — directe impact op filter accuracy
**Afhankelijkheid:** Geen

---

## V2-02: Regime Detector Anti-Nervositeit ✅ DONE

**Geïmplementeerd:** 2026-04-25

**Probleem:** Als regime detector te vaak switcht:
- Bot gaat van momentum → chop → niets → momentum
- Inconsistent gedrag, slechte timing
- Klassiek overfitting op korte termijn

**Huidige mitigatie:** Hysteresis al ingebouwd (bull ≥5.0, bear <-3.0, min duration 30m).

**Geïmplementeerde oplossing:**
1. **Smoothing:** Require N consecutive regime detections before switching (`regime_smoothing_count: 3`)
2. Backward-compatible: `regime_smoothing_count: 1` = oud gedrag (direct switchen)
3. Candidate-state tracking: `_regime_candidate` + `_regime_candidate_count`

**Acceptance criteria:**
- [x] Log regime switch frequentie (switches/uur)
- [x] Optionele `regime_smoothing_count: 3` config (require N consistent detections)
- [ ] Dashboard metric: regime stability score

**Tests:** 13 unit tests — alle pass
**Bestanden:** beide controller-bestanden + USD/EUR YAML configs

---

## V2-03: CHOP Ranking — Trending Coins Uitsluiten ✅ DONE

**Probleem:** `min_trend_pct` filter in CHOP filterde sideways coins WEG in plaats van ze te SELECTEREN.

**Oplossing geïmplementeerd (2026-04-07):**
- `chop_min_trend_pct: 0.001` — bijna-nul drempel zodat flat coins doorkomen
- `chop_max_trend_pct: 3.0` — coins met |trend| > 3% worden uitgefilterd (te trendy voor grid)
- Post-filter stap na `get_top_n_coins()` die sterke trending coins verwijdert
- Over-fetch (n×3) om headroom te geven na post-filter

---

## V2-04: Expected-Fill Profitability Model ✅ DONE

**Geïmplementeerd:** 2026-04-25

**Probleem:** Fee check kijkt alleen naar entry spread vs fees, niet naar verwachte fills.
- Trade kan theoretisch goed zijn maar praktisch weinig opleveren
- Hoeveel levels worden geraakt hangt af van ATR / volatiliteit
- Partial fills verlagen effective profit

**Geïmplementeerde oplossing:**
1. `estimate_hourly_profit()` in `FeeAwareFilter` (ATR fill-rate model):
   - `fills_per_hour = (atr_pct / grid_level_spacing_pct) × fills_calibration_factor`
   - `expected_hourly_profit_pct = fills_per_hour × (spacing - round_trip_fee)`
2. Controller integreert V2-04 check ná ST-12 Edge Gate (fail-open bij errors)
3. **Shadow mode standaard** — logt `📈 V2-04: ...` bij elke entry, blokkeert nog niet

**Acceptance criteria:**
- [x] `estimate_hourly_profit()` methode in FeeAwareFilter
- [x] Uses ATR + grid spacing om fill rate te schatten
- [x] Configureerbaar: `min_profit_per_hour_pct: 0.05` (0.05%/uur)
- [ ] Backtested en `fills_calibration_factor` gekalibreerd op live data (shadow logs)

**Config (alle 3 YAMLs):**
```yaml
fee_aware_filter:
  hourly_profit_check_enabled: false  # false = shadow mode, true = blokkeert
  min_profit_per_hour_pct: 0.05
  fills_calibration_factor: 1.0       # tune via shadow logs
```

**Tests:** 12 nieuwe unit tests (27 totaal in test_fee_aware_filter.py) — alle pass
**Bestanden:** `multi_coin_grid_pro/logic/fee_aware_filter.py` + beide controllers + alle 3 YAML configs

**Shadow data locatie:** `data/v204_shadow/v204_YYYY-MM-DD.jsonl` (dagelijks, geen rotatie)

### 🔜 Nog te doen: kalibratie + activeren

**Stap 1 — Na ≥1 week shadow data: analyseer de schattingen**
```bash
cat data/v204_shadow/v204_*.jsonl | python3 -c "
import sys, json, statistics
rows = [json.loads(l) for l in sys.stdin]
ratios = [r['expected_hourly_pct'] for r in rows]
actuals = [r['fills_per_h'] for r in rows]
print(f'Samples: {len(rows)}')
print(f'Median expected/h: {statistics.median(ratios):.3f}%')
print(f'P10 expected/h: {sorted(ratios)[len(ratios)//10]:.3f}%')
print(f'Median fills/h (model): {statistics.median(actuals):.2f}')
"
```

**Stap 2 — Vergelijk met werkelijke fills uit de SQLite:**
```bash
python3 -c "
import sqlite3, json
db = sqlite3.connect('data/multi_coin_grid_v2_usd.sqlite')
rows = db.execute('''
    SELECT timestamp, close_timestamp, custom_info
    FROM Executors WHERE is_active=0 AND filled_amount_quote > 0
''').fetchall()
fills_per_h = []
for ts, cts, ci in rows:
    orders = json.loads(ci).get('filled_orders', [])
    h = (cts - ts) / 3600
    if h > 0:
        fills_per_h.append(len(orders) / h)
import statistics
print(f'Werkelijke fills/h: median={statistics.median(fills_per_h):.2f}, '
      f'p10={sorted(fills_per_h)[len(fills_per_h)//10]:.2f}')
db.close()
"
```

**Stap 3 — Bereken `fills_calibration_factor`:**
```
calibration_factor = werkelijke_fills_per_h / model_fills_per_h
```
Pas aan in alle 3 YAMLs:
```yaml
fee_aware_filter:
  fills_calibration_factor: <berekende waarde>  # was 1.0
```

**Stap 4 — Activeer de filter:**
```yaml
fee_aware_filter:
  hourly_profit_check_enabled: true   # was false (shadow mode)
  min_profit_per_hour_pct: 0.05       # begin conservatief, verhoog na validatie
```

---

## V2-05: Pattern-Aware Cooldowns

**Probleem:** Cooldown begrijpt niet WAAROM iets faalde. Het zegt alleen "coin slecht" maar niet "type situatie slecht".

Voorbeelden:
- Coin faalde omdat trend te sterk was → cooldown voor die coin in BULL, niet in CHOP
- Coin faalde door spread te klein → permanent blacklist tot spread verbetert
- Coin faalde in BEAR → langere cooldown dan zelfde coin in CHOP

**Oplossing:**
1. **Cooldown key wordt `(coin, regime, close_reason)` ipv alleen `coin`**
2. **Pattern database:** Track welke (coin, regime) combinaties slecht presteren
3. **Adaptive blacklist:** Als coin 3× faalt in CHOP maar OK is in BULL → alleen CHOP-blacklist

**Acceptance criteria:**
- [ ] Cooldown dict key = `f"{coin}:{regime}:{close_type}"`
- [ ] Pattern tracking: `_coin_regime_history: Dict[str, List[TradeOutcome]]`
- [ ] Config: `pattern_aware_cooldowns: true`
- [ ] Fallback naar bestaande simple cooldown als disabled

**Prioriteit:** P2 — verhoogt intelligence significant, maar vereist trade data
**Afhankelijkheid:** 100+ trades voor patronen; V2-01 (accurate fees) voor betere failure attribution

---

## V2-06: BEAR-Light Mode ✅ DONE

**Geïmplementeerd:** 2026-04-25

**Probleem:** BEAR = volledig uit is veilig maar kan kansen missen:
- Lokale pumps in bear market
- Mean-reversion kansen op oversold coins

**Geïmplementeerde oplossing:**
1. **Auto BEAR-light:** Automatisch 1 grid toestaan als `bear_score > bear_auto_light_threshold (-5.0)` (shallow bear)
2. **BEAR coin filter:** Alleen coins met positieve divergence (coin 24h-trend > BTC 24h-trend)
3. **Smaller position:** Automatisch 50% position size in BEAR (`bear_size_multiplier: 0.5`)
4. **Actief:** `bear_auto_light_enabled: true` in alle drie configs (Kraken USD, Kraken EUR, Bitget)

**Acceptance criteria:**
- [x] `bear_auto_light_threshold: -5.0` config
- [x] Position sizing: `bear_size_multiplier: 0.5`
- [x] Divergence filter: coin 24h > BTC 24h

**Tests:** 18 unit tests — alle pass
**Bestanden:** beide controller-bestanden + USD/EUR/Bitget YAML configs

---

## V2-07: Per-Coin Adaptive Timeouts

**Probleem:** Timeouts zijn per-regime maar niet per-coin. Sommige coins bewegen sneller.

**Huidige status:** Al gelaagd:
- `get_recommended_timeout()` berekent ATR-based timeout per coin
- Regime-timeouts zijn een extra laag eroverheen

**Verbetering:**
1. **Coin speed classification:** Fast (BTC, ETH) vs Medium (LINK, DOT) vs Slow (ADA, XRP)
2. **Historical fill-time:** Track gemiddelde tijd tot eerste fill per coin
3. **Timeout = base × regime_factor × coin_speed_factor**

**Acceptance criteria:**
- [ ] `coin_speed_cache: Dict[str, float]` — rolling average fill-time
- [ ] Timeout formula: `regime_timeout × (avg_fill_time / global_avg_fill_time)`
- [ ] Config: `per_coin_timeout_enabled: true`
- [ ] Minimum 10 trades per coin voor betrouwbare schatting

**Prioriteit:** P3 — ATR-based timeout is al redelijk adaptief
**Afhankelijkheid:** Fill-time data per coin (minimaal 10 trades/coin)

---

## Uitvoervolgorde

```
Nu:        V2-03 ✅ DONE (CHOP ranking fix)
Week 1:    V2-01 ✅ DONE (dynamic fee model — fase A: config worst/avg/best)
Week 1-2:  V2-02 ✅ DONE (regime smoothing — 3 consecutive detections)
Week 2:    V2-06 ✅ DONE (BEAR-light mode — auto actief, score > -5.0)
Week 3+:   V2-04 + V2-05 (na 100+ trades data beschikbaar)
Later:     V2-07 (finetuning, lage prioriteit)
```

> **Principe:** Eerst data verzamelen met huidige v1 implementatie, dan data-driven optimaliseren.
