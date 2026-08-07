# Epic: Entry Quality & Cooldown Verbeteringen — Fase 2

> **Datum:** 2026-05-22
> **Aanleiding:** Kraken USD run 2026-05-22, start 23:04:53 lokaal, netto -$2.23 ondanks US1–US10 allemaal DONE
> **Scope:** Kraken USD primair; principes gelden voor alle actieve exchange-instances
> **Voorgaande epic:** `EPIC_GRID_BOT_RISK_AND_EDGE_IMPROVEMENTS.md` (US1–US10, allemaal ✅ DONE)

---

## 1. Context

De vorige epic (US1–US10) heeft vooral de **exit-kant** van de gridbot verbeterd:

- stop-loss
- early-stop
- no-progress detectie
- trailing exit
- cooldowns
- graceful unwind
- orphan cleanup
- betere risk controls

De run van 2026-05-22 laat echter zien dat de verliezen niet primair door slechte exits kwamen. De exits deden grotendeels hun werk. Het probleem zit vooral in **entry quality**.

De bot opent nog steeds posities in situaties waar de verwachte beweging onvoldoende is om fees, spread en slippage te dragen. Daardoor kan de bot technisch correct functioneren, maar economisch nog steeds negatieve expected value hebben.

---

## 2. Probleemanalyse

| Trade | Close type | Netto | Waarschijnlijke root cause |
|---|---|---|---|
| HYPE-USD | EARLY_STOP | -$0.83 | Recidive verliezer, ook verlies op 2026-05-18, niet automatisch geblokkeerd |
| NEX-USD #2 | STOP_LOSS | -$0.91 | Re-entry 77 minuten na TAKE_PROFIT, onvoldoende cooldown na winst |
| SOL-USD | EARLY_STOP | -$0.17 | Kleine verliestrade in CHOP omgeving |
| TAO-USD | TERMINATED | -$0.34 | Lange hold, langzame graceful unwind |

### Conclusie

US3 (stop-loss) voorkwam dat NEX erger werd. Maar de entry had waarschijnlijk nooit mogen plaatsvinden.

De bot moet niet alleen beschermen tegen slechte exits, maar vooral voorkomen dat hij entries opent met negatieve verwachte waarde na fees.

```
EV = P(win) × gemiddelde_winst − P(loss) × gemiddeld_verlies − fees
```

Op basis van de run:

```
1 win:       +$0.50
3 verliezen: −$0.83  −$0.91  −$0.34
Netto:       negatief
```

De conclusie is dat de entry-filters sterker moeten worden, met name rondom:

- fee coverage
- ATR versus kosten
- spread
- recidive verliezers
- re-entry na recente exit
- betere logging van entrybeslissingen

---

## 3. Vandaag al uitgevoerd (2026-05-22)

| Wijziging | Type | Status | Effect |
|---|---|---|---|
| `take_profit_sec: 7200` toegevoegd aan `close_cooldowns` | Config + code | ✅ DONE | 2u cooldown per coin na TAKE_PROFIT |
| TAKE_PROFIT routeert naar `take_profit_sec` in code | Code | ✅ DONE | Was eerder generieke rotation cooldown (5 min) |
| HYPE-USD toegevoegd aan Kraken USD blacklist | Config | ✅ DONE | Recidive verliezer geblokkeerd |
| Unit tests voor TAKE_PROFIT cooldown logica | Tests | ✅ DONE | 4 tests, alle groen |

### Impact

Deze wijzigingen hadden het grootste deel van de run-schade voorkomen:

```
HYPE verlies:    −$0.83
NEX #2 verlies:  −$0.91
Totaal voorkomen: −$1.74 van −$2.23
```

---

# User Stories

---

## — Verlaag loss-streak blacklist drempel van 3 naar 2

### Doel

Als bot wil ik een coin tijdelijk blokkeren na 2 opeenvolgende verliestrades, zodat recidive verliezers sneller uit de rotatie verdwijnen.

### Aanleiding

HYPE-USD verloor op 2026-05-18 en opnieuw op 2026-05-22. De bestaande `_loss_streaks` tracker werkt al, maar de drempel staat op 3. Daardoor werd HYPE pas na een derde verlies automatisch geblokkeerd.

Voor een live bot met kleine gridmarges is 2 opeenvolgende verliezen voldoende bewijs om tijdelijk te stoppen met die coin.

### Type

Config-only.

### Scope

Aanpassen in alle actieve exchange-configs:

- Kraken USD
- Kraken EUR
- OKX
- Bitget

### Configwijziging

Van:
```yaml
close_cooldowns:
  max_streak_before_blacklist: 3
```

Naar:
```yaml
close_cooldowns:
  max_streak_before_blacklist: 2
```

### Belangrijk gedrag

Dit is geen permanente blacklist. Het werkt als tijdelijke performance-cooldown op basis van `failed_sec`.

### Acceptance criteria

- [x] `max_streak_before_blacklist: 2` staat in Kraken USD config
- [x] Dezelfde wijziging staat in Kraken EUR config
- [x] Dezelfde wijziging staat in OKX config
- [x] Dezelfde wijziging staat in Bitget config
- [x] Bestaande `_loss_streaks` logica blijft intact
- [x] Na 2 opeenvolgende verliezen wordt de coin tijdelijk geblokkeerd
- [ ] De log toont duidelijk dat de drempel is bereikt *(runtime validatie — config correct)*

### Gewenste log

```
⚠️  LOSS_STREAK HYPE-USD: 2/2 consecutive losses
🚫 TEMP_BLACKLIST HYPE-USD for 21600s due to loss streak
```

### Testscenario

1. Simuleer eerste verliestrade op `TEST-USD`
2. Controleer dat loss streak `1/2` wordt
3. Simuleer tweede verliestrade op `TEST-USD`
4. Controleer dat loss streak `2/2` wordt
5. Controleer dat `TEST-USD` tijdelijk wordt uitgesloten van nieuwe entries
6. Controleer dat de cooldownduur overeenkomt met `failed_sec`

### Risico

Laag. Er is kans dat een coin tijdelijk te vroeg wordt geblokkeerd door pech, maar dat is acceptabel omdat het geen permanente blacklist is.

---

## US12 — Verhoog minimum grid spacing naar fee-realistisch niveau

### Doel

Als bot wil ik alleen grids openen met voldoende afstand tussen grid-levels, zodat een trade na fees, spread en mogelijk taker-fill nog steeds economisch zinvol kan zijn.

### Aanleiding

De huidige Kraken USD waarde van `min_grid_level_spacing_pct: 0.60` is te krap als één kant van de trade taker wordt.

Voor Kraken:
```
Maker fee:              ~0.16%
Taker fee:              ~0.26%
Worst case roundtrip:   ~0.42%
```

Bij 0.60% spacing blijft slechts ~0.18% bruto marge over — te krap zodra spread, slippage of partial fills meespelen. Bij 0.80% spacing is de marge realistischer (~0.38%).

### Type

Config-only.

### Scope

Primair Kraken USD. Andere exchanges moeten fee-realistisch gecontroleerd worden en niet blind dezelfde waarde krijgen als hun fee-model anders is.

### Configwijziging Kraken USD

Van:
```yaml
min_grid_level_spacing_pct: 0.60
```

Naar:
```yaml
min_grid_level_spacing_pct: 0.80
```

### Aandachtspunt

In de Kraken USD config staan **twee** locaties met deze waarde:

- regel 870 (globale sectie)
- regel 1158 (connector-specifieke sectie US5)

Beide moeten worden bijgewerkt. Een resterende `0.60` kan de nieuwe waarde overrulen.

### Richtlijn voor andere exchanges

Niet blind 0.80 toepassen zonder check. Gebruik:
```
target_min_spacing_pct >= expected_roundtrip_fee_pct + spread_buffer + safety_margin
```

### Acceptance criteria

- [x] Beide Kraken USD locaties met `min_grid_level_spacing_pct` staan op `0.80`
- [x] Kraken EUR connector-sectie aangepast: `0.75 → 0.80`
- [x] OKX gecontroleerd: 0.60 behouden (RT fee 0.20%, 3× = 0.60% correct)
- [x] Bitget gecontroleerd: 0.60 behouden (RT fee 0.20%, 3× = 0.60% correct)
- [x] Er blijft geen oude actieve `0.60` over die de nieuwe gate kan overrulen
- [x] Tests groen (1372 passed, 0 failures)
- [x] Flake8 groen

### Gewenste log

```
[GRID_REJECTED] pair=NEX-USD reason=GRID_SPACING_TOO_LOW
  spacing_pct=0.62  required_min_spacing_pct=0.80
```

### Risico

Laag tot middel. De bot zal minder setups accepteren. Dat is gewenst als de oude setups economisch te krap waren.

---

## US13 — Implementeer ATR-fee gate voor entry quality

### Doel

Als bot wil ik nieuwe entries blokkeren wanneer de verwachte 1u volatiliteit onvoldoende is om fees en spread te dragen, zodat ik geen trades open met negatieve expected value.

### Aanleiding

Een gridbot verdient alleen als de markt voldoende beweegt binnen de gridrange. Als de ATR lager is dan de minimale kostenbasis, dan is de verwachte waarde van de entry negatief.

### Type

Code + config.

### Config

```yaml
atr_fee_gate:
  enabled: true
  timeframe: "1h"
  min_atr_fee_multiplier: 2.0
  use_roundtrip_fee: true
  include_spread_buffer: true
  reject_when_below_threshold: true
```

### Beslisregel

```
required_atr_pct = (roundtrip_fee_pct × min_atr_fee_multiplier) + spread_pct

als atr_1h_pct < required_atr_pct:
    reject entry
anders:
    allow entry richting volgende filters
```

### Voorbeeld Kraken

```
roundtrip_fee_pct        = 0.52%
min_atr_fee_multiplier   = 2.0
spread_pct               = 0.15%

required_atr_pct         = 0.52 × 2.0 + 0.15 = 1.19%

ATR 1h = 0.70% → REJECT
ATR 1h = 1.35% → ALLOW
```

### Technische notes

- De gate moet plaatsvinden vóór het openen van een nieuwe grid-entry
- Bestaande posities worden niet gesloten — uitsluitend een entry-filter
- `enabled: false` schakelt de gate volledig uit zonder andere gedragswijziging
- **Let op dubbele spreadcorrectie:** controleer of spread al wordt meegenomen in `economic_edge_gate`, `smart_entry_filter`, `orderbook_liquidity` of `grid_suitability`. Dubbele afwijzing is acceptabel maar moet duidelijk gelogd worden.

### Acceptance criteria

- [x] Nieuwe configsectie `atr_fee_gate` wordt correct geladen
- [x] `enabled: false` schakelt de gate volledig uit
- [x] ATR wordt berekend voor het geconfigureerde timeframe
- [x] `required_atr_pct` wordt correct berekend
- [x] Entry wordt geblokkeerd als `atr_1h_pct < required_atr_pct`
- [x] Entry mag verder als `atr_1h_pct >= required_atr_pct`
- [x] Bestaande open posities worden niet beïnvloed
- [x] Unit test dekt lage ATR (`test_atr_fee_gate_blocks_low_atr`)
- [x] Unit test dekt hoge ATR (`test_atr_fee_gate_allows_sufficient_atr`)
- [x] Unit test dekt `enabled: false` (`test_atr_fee_gate_disabled`)
- [x] Flake8 groen
- [x] Tests groen (31 passed)

### Gewenste reject log

```
[ENTRY_REJECTED] pair=NEX-USD reason=ATR_BELOW_FEE_EDGE
  atr_1h_pct=0.70  roundtrip_fee_pct=0.52
  min_atr_fee_multiplier=2.0  spread_pct=0.15
  required_atr_pct=1.19  regime=CHOP
```

### Gewenste approved log

```
[ENTRY_APPROVED] pair=SOL-USD reason=ENTRY_GATES_PASSED
  atr_1h_pct=1.35  roundtrip_fee_pct=0.52
  spread_pct=0.12  required_atr_pct=1.16  regime=CHOP
```

### Risico

Middel. De bot opent minder trades. Dat is gewenst. Na implementatie monitoren of het aantal trades niet onbedoeld naar bijna nul gaat.

---

## US14 — Breid decision logging uit voor entry rejects en approvals

### Doel

Als operator wil ik kunnen zien waarom de bot een entry afwijst of goedkeurt, zodat ik filters kan tunen op basis van bewijs in plaats van gevoel.

### Aanleiding

ATR-fee gate zonder logging is blind. De huidige logs zijn soms te mager om te beoordelen of de bot terecht weinig doet of te streng filtert.

### Type

Code. Implementeer tegelijk met US13.

### Functionele eis

Elke rejected entry logt minimaal:

- pair, reason, regime, timestamp
- spread, ATR, required ATR, fee basis
- grid score en liquidity score indien beschikbaar

Elke approved entry logt minimaal:

- pair, reason, regime
- ATR, required ATR, spread
- selected grid parameters, expected edge indien beschikbaar

### Gewenste reject log

```
[ENTRY_REJECTED] pair=NEX-USD reason=ATR_BELOW_FEE_EDGE
  atr_1h_pct=0.70  roundtrip_fee_pct=0.52
  spread_pct=0.15  required_atr_pct=1.19
  regime=CHOP  grid_score=0.58  liquidity_score=0.74
```

### Hourly summary

```
[HOURLY_REJECT_SUMMARY]
  ATR_BELOW_FEE_EDGE: 14
  SPREAD_TOO_HIGH: 5
  LOSS_STREAK_BLACKLISTED: 2
  GRID_SPACING_TOO_LOW: 3
  REGIME_BLOCKED: 1
```

### Reason codes (minimaal ondersteunen)

```
ATR_BELOW_FEE_EDGE
SPREAD_TOO_HIGH
LOSS_STREAK_BLACKLISTED
GRID_SPACING_TOO_LOW
REGIME_BLOCKED
LIQUIDITY_TOO_LOW
MAX_ACTIVE_GRIDS_REACHED
COOLDOWN_ACTIVE
REENTRY_PRICE_GUARD
```

### Acceptance criteria

- [x] Iedere rejected entry heeft een duidelijke reason code
- [x] ATR-fee rejects tonen alle ATR-componenten
- [x] Spread rejects tonen actuele spread en drempel
- [x] Loss-streak rejects tonen huidige streak en drempel
- [x] Approved entries worden ook gelogd
- [x] Hourly reject-summary bevat aantallen per reason (`_record_entry_reject` + `[HOURLY_REJECT_SUMMARY]`)
- [x] Logs zijn compact genoeg om productiebruikbaar te blijven
- [x] Flake8 groen
- [x] Tests groen (31 passed — incl. `test_record_entry_reject_increments_counter`)

### Risico

Laag. Meer logging kan extra ruis geven, te beperken via loglevel of samenvattingen.

---

## US15 — Map STOP_LOSS naar eigen `stop_loss_sec` cooldown

### Doel

Als bot wil ik STOP_LOSS apart behandelen van EARLY_STOP, zodat een echte stop-loss leidt tot een langere cooldown dan een kleine early-stop.

### Aanleiding

Op dit moment mapt `_get_close_cooldown_sec()` zowel `STOP_LOSS` als `EARLY_STOP` naar `early_stop_sec` (3u). Een stop-loss betekent dat de markt duidelijk tegen de positie inging — dat verdient een langere cooldown (6u).

**LET OP:** Dit is **geen** config-only wijziging. De code in `_get_close_cooldown_sec()` moet aangepast worden. Zonder code-aanpassing heeft de config-key geen effect.

### Type

Code + config.

### Config

```yaml
close_cooldowns:
  failed_sec: 21600          # 6u
  early_stop_sec: 10800      # 3u
  no_progress_sec: 3600      # 1u
  take_profit_sec: 7200      # 2u  ← al geïmplementeerd
  stop_loss_sec: 21600       # 6u  ← nieuw
```

### Gewenste mapping

```
TAKE_PROFIT  → take_profit_sec
STOP_LOSS    → stop_loss_sec
EARLY_STOP   → early_stop_sec
NO_PROGRESS  → no_progress_sec
FAILED       → failed_sec
```

### Backward-compatible fallback

Als `stop_loss_sec` ontbreekt in een oudere config:

```python
stop_loss_sec = close_cooldowns.get(
    "stop_loss_sec",
    close_cooldowns.get("early_stop_sec", 10800),
)
```

### Acceptance criteria

- [x] `_get_close_cooldown_sec()` leest `stop_loss_sec` voor `STOP_LOSS`
- [x] `EARLY_STOP` blijft `early_stop_sec` gebruiken
- [x] `TAKE_PROFIT` blijft `take_profit_sec` gebruiken
- [x] `NO_PROGRESS` blijft `no_progress_sec` gebruiken
- [x] Ontbrekende `stop_loss_sec` breekt oudere configs niet (fallback geïmplementeerd)
- [x] Unit test dekt STOP_LOSS met `stop_loss_sec` (`test_get_close_cooldown_sec_stop_loss`)
- [x] Unit test dekt STOP_LOSS zonder `stop_loss_sec` (`test_get_close_cooldown_sec_stop_loss_fallback`)
- [x] Unit test dekt EARLY_STOP ongewijzigd (`test_get_close_cooldown_sec_early_stop_unchanged`)
- [x] Flake8 groen
- [x] Tests groen (23 passed)

### Gewenste log

```
[COOLDOWN_SET] pair=NEX-USD close_type=STOP_LOSS
  cooldown_key=stop_loss_sec  cooldown_sec=21600
```

### Risico

Laag. Corrigeert bestaande semantiek zonder de rest van de exitlogica te veranderen.

---

## US16 — Voeg re-entry prijscheck toe na recente close

### Doel

Als bot wil ik voorkomen dat ik opnieuw instap in een coin waarvan de prijs direct na mijn exit al duidelijk gedaald is, zodat ik geen vallend mes koop na een recente close.

### Aanleiding

NEX-USD werd 77 minuten na een TAKE_PROFIT opnieuw geopend en sloot daarna met STOP_LOSS. De `take_profit_sec` cooldown pakt de tijdsdimensie aan, maar niet de prijsdimensie.

Als de prijs na onze exit al 0.5% lager staat, kan dat betekenen dat de beweging voorbij is en de bot opnieuw instapt in een neerwaartse draai.

### Type

Code + config.

### Config

```yaml
reentry_price_guard:
  enabled: true
  max_drop_below_last_exit_pct: 0.50
  apply_after_close_types:
    - TAKE_PROFIT
    - STOP_LOSS
    - EARLY_STOP
```

### Beslisregel

```
als laatste_exit_prijs bekend
en huidige_prijs < laatste_exit_prijs × (1 − max_drop_below_last_exit_pct / 100):
    reject entry

Voorbeeld:
  last_exit_price = 10.00
  max_drop = 0.50%
  min_allowed  = 9.95

  current = 9.93 → REJECT
  current = 9.97 → ALLOW
```

### Functionele eisen

- Bot slaat de laatste exitprijs per pair op
- Uitsluitend een entry-filter; bestaande grids worden niet gesloten
- `enabled: false` geeft bestaand gedrag
- Onbekende exitprijs blokkeert nooit

### Acceptance criteria

- [x] Configsectie `reentry_price_guard` wordt geladen
- [x] `enabled: false` geeft bestaand gedrag
- [x] Bij te grote prijsdaling → entry geblokkeerd
- [x] Bij acceptabele prijs → entry niet geblokkeerd
- [x] Bij onbekende exitprijs → entry niet geblokkeerd
- [x] Log toont `REENTRY_PRICE_GUARD` met alle componenten
- [x] Unit test dekt daling groter dan drempel (`test_reentry_price_guard_blocks_drop`)
- [x] Unit test dekt daling kleiner dan drempel (`test_reentry_price_guard_allows_small_drop`)
- [x] Unit test dekt onbekende exitprijs (`test_reentry_price_guard_no_exit_price`)
- [x] Flake8 groen
- [x] Tests groen (31 passed)

### Gewenste log

```
[ENTRY_REJECTED] pair=NEX-USD reason=REENTRY_PRICE_GUARD
  last_exit_price=10.00  current_price=9.93
  max_drop_below_last_exit_pct=0.50  close_type=TAKE_PROFIT
```

### Risico

Middel. De bot kan sommige geldige dip-entries missen. Daarom conservatief beginnen en goed monitoren via US14 logging.

---

## US17 — Evalueer CHOP entry policy na ATR-fee gate

### Doel

Als operator wil ik na implementatie van US13 meten of CHOP-entries nog steeds verliesgevend zijn, zodat ik CHOP niet onnodig blokkeer maar wel slechte CHOP kan filteren.

### Aanleiding

Grid trading is juist ontworpen voor mean-reverting CHOP-markten. Volledig blokkeren is te bot.

Het echte probleem is slechte CHOP:
```
lage ATR + hoge spread + fees > verwachte beweging
```

De ATR-fee gate (US13) pakt dit grotendeels al af. Pas na live data wordt beslist of aanvullende CHOP-regels nodig zijn.

### Type

Analyse. Daarna pas mogelijk config/code.

### Beslissing nu

Niet implementeren als harde block.

Niet:
```yaml
block_new_entries_in_chop: true
```

Maar eventueel later, als data dit onderbouwen:
```yaml
chop_entry_policy:
  allow_chop_entries: true
  require_atr_fee_gate_pass: true
  max_spread_pct_in_chop: 0.25
  min_grid_score_in_chop: 0.65
```

### Meetpunten (na US13 + US14)

- Aantal approved en rejected entries in CHOP
- PnL van CHOP entries uitgesplitst van andere regimes
- Gemiddelde ATR en spread bij CHOP entries
- Close type verdeling en gemiddelde hold time in CHOP
- Aantal no-progress exits in CHOP

### Acceptance criteria

- [ ] Minimaal één volledige live run geanalyseerd na US13 en US14
- [ ] CHOP entries zijn apart zichtbaar in logs
- [ ] CHOP PnL is uitgesplitst per regime
- [ ] Er is bewijs of aanvullende CHOP-filtering nodig is
- [ ] Geen harde CHOP-block zonder data

### Risico

Laag. Dit is bewust een meet-story, geen directe blokkade.

---

# Prioriteitenlijst

| Prio | ID | Actie | Type | Status |
|---|---|---|---|---|
| ✅ | — | `take_profit_sec: 7200` + HYPE blacklist + code routing | Config + code | DONE |
| ✅ | US11 | `max_streak_before_blacklist: 3 → 2` (alle configs) | Config | DONE |
| ✅ | US12 | `min_grid_level_spacing_pct` fee-realistisch (beide locaties Kraken USD) | Config | DONE |
| ✅ | US13 | ATR-fee gate implementeren | Code + config | DONE |
| ✅ | US14 | Decision logging uitbreiden (tegelijk met US13) | Code | DONE |
| ✅ | US15 | `stop_loss_sec` correct mappen in `_get_close_cooldown_sec()` | Code + config | DONE |
| ✅ | US16 | Re-entry prijscheck na close | Code + config | DONE |
| 7 | US17 | CHOP entry policy evalueren (na data van US13/US14) | Analyse | LATER |

---

# Definition of Done

Een user story is DONE als:

- [ ] Config is aangepast waar nodig
- [ ] Code is aangepast waar nodig
- [ ] Unit tests toegevoegd of bijgewerkt
- [ ] Bestaande tests groen
- [ ] Flake8 groen
- [ ] Logs voldoende bewijs geven van het nieuwe gedrag
- [ ] Geen regressie in bestaande exitlogica
- [ ] De wijziging is veilig op Kraken USD live
- [ ] Exchange-specifieke verschillen expliciet gecontroleerd

---

# Aanbevolen implementatievolgorde

## Stap 1 — Snelle config hardening

```
US11 — max_streak_before_blacklist naar 2
US12 — min_grid_level_spacing_pct naar 0.80 (alle locaties)
```

Waarom eerst: laag risico, direct effect, geen kans op regressie, betere basis voordat nieuwe code live gaat.

## Stap 2 — Entry quality root cause

```
US13 + US14 — ATR-fee gate én decision logging tegelijk
```

Waarom samen: ATR-gate zonder logging is blind. Logging zonder gate lost root cause niet op. Samen leveren ze meetbare entrykwaliteit.

## Stap 3 — Cooldown semantiek corrigeren

```
US15 — stop_loss_sec mapping
```

Waarom: kleine codewijziging, maakt close-type cooldowns semantisch correct, voorkomt dat STOP_LOSS te licht wordt behandeld.

## Stap 4 — Re-entry prijsdimensie

```
US16 — re-entry price guard
```

Waarom: aanvullende bescherming. Iets meer risico op gemiste dip-entries, daarom pas na betere logging (US14).

## Stap 5 — CHOP evaluatie

```
US17 — CHOP entry policy evalueren
```

Waarom als laatste: CHOP is niet per definitie slecht voor grid. Eerst data verzamelen na ATR-fee gate, daarna pas extra CHOP-regels.

---

# Kernprincipe van deze epic

Deze fase draait niet om meer trades.

Deze fase draait om:

```
minder slechte entries
betere fee coverage
minder recidive verliezers
betere re-entry discipline
bewijsbare decision logs
```

De bot moet pas traden als de setup aantoonbaar genoeg ruimte heeft om fees, spread en risico te dragen.


---

## Aanleiding: Waarom verliezen ondanks US1–US10?

De 10 user stories verbeterden **exit-mechanismen**. De verliezen zijn echter een **entry-kwaliteitsprobleem**:

| Trade | Close type | Netto | Root cause |
|---|---|---|---|
| HYPE-USD | EARLY_STOP | -$0.83 | Recidive verliezer (ook -$0.49 op 2026-05-18), nooit geblacklist |
| NEX-USD #2 | STOP_LOSS | -$0.91 | Re-entry 77 min na TAKE_PROFIT, geen cooldown na winst |
| SOL-USD | EARLY_STOP | -$0.17 | Klein verlies, CHOP omgeving |
| TAO-USD | TERMINATED | -$0.34 | 7u hold, langzame graceful unwind |

**Conclusie:** US3 (stop-loss) voorkwam dat NEX erger werd. Maar de entries hadden nooit mogen plaatsvinden. De bot heeft op dit moment geen aantoonbare positieve verwachte waarde (EV) na fees in CHOP-markten.

$$EV = P(\text{win}) \times \bar{w} - P(\text{verlies}) \times \bar{l} - \text{fees}$$

Met huidige data: 1 win ($0.50) vs 3 verliezen ($0.83 + $0.91 + $0.34) → **EV negatief**.

---

## Vandaag al uitgevoerd (2026-05-22)

| Wijziging | Type | Effect |
|---|---|---|
| `take_profit_sec: 7200` in `close_cooldowns` | Config + code | Na TAKE_PROFIT 2u cooldown per coin (was 5 min) |
| HYPE-USD toegevoegd aan Kraken USD blacklist | Config | Recidive verliezer permanent geblokkeerd |
| Code: TAKE_PROFIT routeert naar `take_profit_sec` | Code | Was altijd de generieke rotation-cooldown (300s) |
| 4 unit tests toegevoegd | Tests | Dekt TAKE_PROFIT cooldown logica |

Had dit de run gered? HYPE (-$0.83) + NEX #2 (-$0.91) = **$1.74 van de $2.23 verlies voorkomen**.

---

## Fase 1: Config-only (nu uitvoeren)

### F1-01: `max_streak_before_blacklist: 3 → 2`

**Wat:** Na 2 opeenvolgende verliezen op dezelfde coin → auto-blacklist met `failed_sec` cooldown.

**Waarom:** De `_loss_streaks` tracker is al geïmplementeerd in de code. Drempel was 3, maar 2 opeenvolgende verliezen is voldoende bewijs van negatieve edge. HYPE had dit automatisch gevangen (verlies op 18 mei én 22 mei).

**Waar:** `close_cooldowns.max_streak_before_blacklist` in alle exchange configs.

**Risico:** Laag. Kan in theorie een coin te vroeg blokkeren bij pech, maar de cooldown is tijdelijk (niet permanent).

---

### F1-02: `min_grid_level_spacing_pct: 0.60 → 0.80`

**Wat:** Minimum afstand tussen grid-levels verhogen van 0.60% naar 0.80%.

**Waarom:** Bij Kraken maker/taker risico:
- Maker fee: ~0.16%, taker fee: ~0.26%
- Roundtrip worst case (maker buy + taker sell): 0.42%
- Bij 0.60% spacing is de marge slechts 0.18% — te krap als één kant taker wordt
- Bij 0.80% spacing is de marge 0.38% — acceptabel

**Aandachtspunt:** Er zijn **twee** plaatsen in de Kraken USD config met deze waarde (regel 870 en 1158). Beide moeten bijgewerkt worden.

**Risico:** Laag. Vermindert het aantal posities dat door de suitability gate komt, maar die posities waren marginaal.

---

## Fase 2: Code-wijzigingen (volgorde)

### F2-01: ATR-fee gate (HOOGSTE PRIORITEIT)

**Wat:** Blokkeeer entry als de 1u ATR kleiner is dan de vereiste minimumbeweging om fees + spread te dragen.

**Beslisregel:**
```
required_atr_pct = (roundtrip_fee_pct × min_atr_fee_multiplier) + spread_pct

als atr_1h_pct < required_atr_pct → reject entry
```

**Voorbeeld Kraken:**
```
roundtrip_fee_pct  = 0.52%   (0.26% × 2, worst case taker)
min_atr_fee_multiplier = 2.0
spread_pct         = 0.15%   (actueel uit orderbook)

required_atr_pct   = 0.52 × 2.0 + 0.15 = 1.19%

als ATR(1h) = 0.70% → REJECT (volatiliteit dekt fees niet)
als ATR(1h) = 1.35% → ALLOW
```

**Config:**
```yaml
atr_fee_gate:
  enabled: true
  timeframe: "1h"
  min_atr_fee_multiplier: 2.0
  use_roundtrip_fee: true
  include_spread_buffer: true
  reject_when_below_threshold: true
```

**Waarom nu:** Dit pakt de root cause aan. Alle andere filters zijn zinloos als de fundamentele EV-berekening negatief is.

---

### F2-02: Decision logging uitbreiden (TEGELIJK MET F2-01)

**Wat:** Gestructureerde logs bij elke rejected entry, inclusief alle componenten.

**Gewenste log:**
```
[ENTRY_REJECTED] pair=NEX-USD reason=ATR_BELOW_FEE_EDGE
  atr_1h_pct=0.70  roundtrip_fee_pct=0.52  spread_pct=0.15
  required_atr_pct=1.19  regime=CHOP
```

**Waarom tegelijk:** ATR-gate zonder logging maakt het onmogelijk te beoordelen of de gate te streng staat of juist werkt. Dit is de bewijsvoering.

**Hourly summary toevoegen:**
```
[HOURLY_REJECT_SUMMARY]
  ATR_BELOW_FEE_EDGE: 14  SPREAD_TOO_HIGH: 5
  LOSS_STREAK_BLACKLISTED: 2  GRID_SPACING_TOO_LOW: 3
```

---

### F2-03: `stop_loss_sec` correct mappen in code

**Wat:** `STOP_LOSS` close type apart afhandelen met eigen `stop_loss_sec` key in `close_cooldowns`.

**Huidig probleem:** `_get_close_cooldown_sec()` mapt `STOP_LOSS` naar `early_stop_sec` (3u). Een stop-loss is ernstiger dan een early_stop — verdient een langere cooldown (6u).

**LET OP:** Dit is **niet** alleen een config-wijziging. De code in `_get_close_cooldown_sec()` moet aangepast worden om `stop_loss_sec` te lezen. Zonder code-aanpassing heeft het config-key geen effect.

**Config:**
```yaml
close_cooldowns:
  failed_sec: 21600          # 6u
  early_stop_sec: 10800      # 3u
  no_progress_sec: 3600      # 1u
  take_profit_sec: 7200      # 2u  ← al geïmplementeerd
  stop_loss_sec: 21600       # 6u  ← nieuw
```

---

### F2-04: Re-entry prijscheck (LATER)

**Wat:** Na een close (vooral TAKE_PROFIT), geen re-entry als de prijs al onder de exit-prijs gedaald is.

**Beslisregel:**
```
als laatste_exit_prijs bekend EN huidige_prijs < laatste_exit_prijs × (1 - 0.005):
    reject entry  # prijs is al 0.5% gedaald na onze exit
```

**Waarom:** Voorkomt "vallend mes" herentry — NEX was juist aan het dalen toen de bot opnieuw instapte. De `take_profit_sec` cooldown pakt de tijdsdimensie aan; deze check pakt de prijsdimensie.

---

## CHOP-entries: later beoordelen

**Beslissing:** CHOP niet volledig blokkeren. Grid trading is ontworpen voor CHOP (mean reversion).

**Slechte CHOP** is:
```
lage ATR (< fee drempel) + hoge spread + regime=CHOP
```

**De ATR-fee gate (F2-01) pakt dit indirect al aan.** Na implementatie van F2-01: meten hoeveel CHOP-entries nog plaatsvinden en of ze nog verliezen. Dan pas eventueel:

```yaml
chop_entry_policy:
  allow_chop_entries: true
  require_atr_fee_gate_pass: true   # gate al afgedwongen door F2-01
  max_spread_pct_in_chop: 0.25      # extra spread-eis in CHOP
```

---

## Volledige prioriteitenlijst

| Prio | ID | Actie | Type | Status |
|---|---|---|---|---|
| ✅ | – | `take_profit_sec: 7200` + HYPE blacklist | Config + code | DONE |
| 1 | F1-01 | `max_streak_before_blacklist: 3 → 2` | Config | TODO |
| 2 | F1-02 | `min_grid_level_spacing_pct: 0.60 → 0.80` (beide locaties) | Config | TODO |
| 3 | F2-01 | ATR-fee gate implementeren | Code | TODO |
| 4 | F2-02 | Decision logging uitbreiden | Code | TODO (tegelijk met F2-01) |
| 5 | F2-03 | `stop_loss_sec` correct mappen in code | Code | TODO |
| 6 | F2-04 | Re-entry prijscheck na close | Code | TODO |
| 7 | – | CHOP entry policy evalueren | Config/code | LATER (na bewijs F2-01) |

---

## Acceptance criteria per item

### F1-01
- [ ] `max_streak_before_blacklist: 2` in Kraken USD config
- [ ] Zelfde wijziging in EUR, OKX, Bitget configs
- [ ] Log toont: `⚠️ LOSS_STREAK NEX-USD: 2/2 consecutive losses` → auto-blacklist

### F1-02
- [ ] Beide `min_grid_level_spacing_pct` locaties in Kraken USD config → 0.80
- [ ] Zelfde check en aanpassing in EUR, OKX, Bitget configs
- [ ] Flake8 groen, tests groen

### F2-01 + F2-02
- [ ] `atr_fee_gate.enabled` in config werkt als kill-switch
- [ ] Bij ATR < drempel: log toont `[ENTRY_REJECTED] reason=ATR_BELOW_FEE_EDGE` met alle componenten
- [ ] Hourly reject-summary in logs aanwezig
- [ ] Unit tests: gate blokkeert bij lage ATR, laat door bij hoge ATR
- [ ] Flake8 groen

### F2-03
- [ ] `_get_close_cooldown_sec()` leest `stop_loss_sec` apart van `early_stop_sec`
- [ ] Bestaand gedrag voor EARLY_STOP ongewijzigd
- [ ] Unit test dekt beide paden
