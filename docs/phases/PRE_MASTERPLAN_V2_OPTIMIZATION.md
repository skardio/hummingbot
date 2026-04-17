# Pre-Masterplan v2 — Optimalisatie Backlog

> **Datum:** 2026-04-07
> **Aanleiding:** Implementatie van 5 features (regime-first selectie, fee-aware filter, enhanced cooldowns, dual selection models, regime-based timeouts) is **live**. Dit document bevat de volgende ronde verbeteringen, geprioriteerd van hoog naar laag impact.
> **Status:** Architectuur correct, nu optimalisatie en intelligentie toevoegen.

---

## Samengevat

| # | Verbetering | Prioriteit | Complexiteit | Wanneer |
|---|-------------|-----------|-------------|---------|
| V2-01 | ~~Dynamic fee model~~ | ✅ **DONE** | — | Fase A: `fee_model: worst_case \| average \| best_case` |
| V2-02 | Regime smoothing (anti-nervositeit) | P2 | Low | Na observatie switch-frequentie |
| V2-03 | ~~CHOP ranking niet hard genoeg~~ | ✅ **DONE** | — | Opgelost: `chop_max_trend_pct` filter |
| V2-04 | Expected-fill profitability model | P2 | High | Na 100+ trades data |
| V2-05 | Pattern-aware cooldowns | P2 | Medium | Na 100+ trades data |
| V2-06 | BEAR-light mode | P3 | Low | Configureerbaar (al beschikbaar) |
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

## V2-02: Regime Detector Anti-Nervositeit

**Probleem:** Als regime detector te vaak switcht:
- Bot gaat van momentum → chop → niets → momentum
- Inconsistent gedrag, slechte timing
- Klassiek overfitting op korte termijn

**Huidige mitigatie:** Hysteresis al ingebouwd (bull ≥5.0, bear <-3.0, min duration 30m).

**Extra verbetering:**
1. **Smoothing:** Require 2-3 consecutive regime detections before switching
2. **Regime confidence decay:** Niet instant switchen, maar geleidelijk confidence verlagen
3. **Monitoring eerst:** Log regime switches + frequentie → data-driven beslissing of smoothing nodig is

**Acceptance criteria:**
- [ ] Log regime switch frequentie (switches/uur)
- [ ] Optionele `regime_smoothing_count: 3` config (require N consistent detections)
- [ ] Dashboard metric: regime stability score

**Prioriteit:** P2 — huidige hysteresis kan voldoende zijn
**Afhankelijkheid:** Productie-data over switch-frequentie nodig

---

## V2-03: CHOP Ranking — Trending Coins Uitsluiten ✅ DONE

**Probleem:** `min_trend_pct` filter in CHOP filterde sideways coins WEG in plaats van ze te SELECTEREN.

**Oplossing geïmplementeerd (2026-04-07):**
- `chop_min_trend_pct: 0.001` — bijna-nul drempel zodat flat coins doorkomen
- `chop_max_trend_pct: 3.0` — coins met |trend| > 3% worden uitgefilterd (te trendy voor grid)
- Post-filter stap na `get_top_n_coins()` die sterke trending coins verwijdert
- Over-fetch (n×3) om headroom te geven na post-filter

---

## V2-04: Expected-Fill Profitability Model

**Probleem:** Fee check kijkt alleen naar entry spread vs fees, niet naar verwachte fills.
- Trade kan theoretisch goed zijn maar praktisch weinig opleveren
- Hoeveel levels worden geraakt hangt af van ATR / volatiliteit
- Partial fills verlagen effective profit

**Oplossing:**
1. **Expected fills per uur** gebaseerd op ATR en grid spacing
2. **Expected profit = fills × (spread - fees) × capital per level**
3. **Minimum profit/hour threshold** als extra filter

**Acceptance criteria:**
- [ ] `estimate_hourly_profit()` methode in FeeAwareFilter
- [ ] Uses ATR + grid spacing om fill rate te schatten
- [ ] Configureerbaar: `min_profit_per_hour_pct: 0.05` (0.05%/uur)
- [ ] Backtested tegen historische grid data

**Prioriteit:** P2 — vereist voldoende trade data voor kalibratie
**Afhankelijkheid:** Minimaal 100 trades voor betrouwbare fill-rate schatting

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

## V2-06: BEAR-Light Mode

**Probleem:** BEAR = volledig uit is veilig maar kan kansen missen:
- Lokale pumps in bear market
- Mean-reversion kansen op oversold coins

**Huidige status:** Al configureerbaar!
- `bear_allow_trading: true` + `bear_max_grids: 1` = BEAR-light mode
- Selecteert dan via grid-suitability ranking met max 1 grid

**Verbetering:**
1. **Auto BEAR-light:** Automatisch 1 grid toestaan als bear_score > -5.0 (shallow bear)
2. **BEAR coin filter:** Alleen coins met positieve divergence (prijs daalt minder dan BTC)
3. **Smaller position:** Automatisch 50% position size in BEAR

**Acceptance criteria:**
- [ ] `bear_auto_light_threshold: -5.0` config
- [ ] Position sizing: `bear_size_multiplier: 0.5`
- [ ] Divergence filter: coin 24h > BTC 24h

**Prioriteit:** P3 — huidige "sit out" is veilig genoeg voor €300 fase
**Afhankelijkheid:** Geen

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
Week 1:    V2-01 (dynamic fee model — fase A: config worst/avg/best)
Week 1-2:  V2-02 (regime smoothing — eerst monitoring, dan smoothing)
Week 3+:   V2-04 + V2-05 (na 100+ trades data beschikbaar)
Later:     V2-06 + V2-07 (finetuning, lage prioriteit)
```

> **Principe:** Eerst data verzamelen met huidige v1 implementatie, dan data-driven optimaliseren.
