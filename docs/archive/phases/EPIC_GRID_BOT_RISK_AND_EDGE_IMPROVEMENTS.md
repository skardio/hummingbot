# Epic: Multi-Exchange Grid Bot — winstgevendheid en risicobeheer verbeteren

> **Datum:** 2026-05-20
> **Scope:** Kraken (USD + EUR), Bitget, OKX — alle actieve grid bot instances.
> **Aanleiding:** Run-analyse Kraken USD 2026-05-18 23:33:19 bracht structurele problemen aan het licht die op alle exchanges van toepassing zijn.
> **Run (trigger):** `logs_multi_coin_grid_v2_usd_2026-05-18-23-33-19.log`, 11 trades, 72.7% win rate, netto -$1.44.
> **Gerelateerd:** PRE_MASTERPLAN_BACKLOG.md ST-07 (US8), ST-12 DONE (US1 deels).

## Context

### Aanleiding: Kraken USD run-analyse

De trigger voor deze epic was de Kraken USD run van 2026-05-18. De bevindingen zijn echter structureel en gelden voor alle exchange-instances:

**Kraken USD run (concreet bewijs):**

| Observatie | Cijfer |
|---|---|
| Bruto P&L | +$0.33 |
| Fees | -$1.77 |
| Netto P&L | **-$1.44** |
| `FEE_AWARE_EXIT_BLOCKED` triggers | 68.143× in één run |
| `NO_PROGRESS_TIMEOUT` triggers | 130.121× in één run |
| Grootste verlies (XDC-USD #2) | -$1.72 (prijs -2.9%, positie 158 min vast) |
| Langste positie (HYPE-USD #4) | 755 minuten open |
| Gem. winner vs. gem. loser | $0.17 vs. -$0.93 (ratio 1:5.5) |

### Waarom dit voor alle exchanges geldt

Deze problemen zijn niet Kraken-specifiek:

| Probleem | Kraken USD | Bitget / OKX |
|---|---|---|
| Fees eten winst op | 0.20% per kant | Andere tarieven, zelfde risico |
| `FEE_AWARE_EXIT` houdt posities vast | Bewezen in logs | Zelfde logica actief |
| Geen hard stop-loss ondergrens | XDC -$1.72 | Potentieel op elke exchange |
| Posities blijven uren open | 755 min (HYPE) | Zelfde timeout-mechanisme |
| Blacklist/config-inconsistentie | Kraken USD config | Elk config-bestand |

---

## Epic-omschrijving

Doel van deze epic is om alle actieve grid bot instances (Kraken USD, Kraken EUR, Bitget, OKX) robuuster te maken door:

- netto edge na fees strenger te bewaken, **per exchange gecalibreerd**
- verliesposities sneller af te kappen via een **exchange-agnostische stop-loss**
- fee-aware exit veilig te begrenzen met configureerbare tijdlimieten
- grid spacing en positiegrootte **per connector instelbaar** te maken
- performance-gebaseerde blacklisting toe te passen **per exchange-instance**
- de configuratie op alle instances voorspelbaar en consistent te maken

De verbeteringen worden één keer in de kern geïmplementeerd en via per-connector config-overrides ingesteld per exchange.

---

## Prioriteitsoverzicht

| Prio | User story | Reden | Status |
|---|---|---|---|
| P1 | US3 — Hard stop-loss overrult fee-aware exit | Voorkomt grote verliezers (-$1.72 type) | ✅ DONE 2026-05-22 |
| P1 | US2 — Fee-aware exit max hold | Voorkomt vastzittende posities (68k blocks) | ✅ DONE 2026-05-22 |
| P1 | US4 — Absolute max hold time | Voorkomt 12+ uur open posities | ✅ DONE 2026-05-22 |
| P2 | US1 — Netto edge na fees verplicht maken | Verbetert winstgevendheid per entry | ✅ DONE 2026-05-20 |
| P2 | US5 — Grid spacing kalibreren per exchange | Elke exchange heeft andere fee-structuur | ✅ DONE 2026-05-22 |
| P2 | US8 — BEAR-regime eenduidig maken | Minder onvoorspelbaar gedrag | ✅ DONE 2026-05-20 |
| P3 | US6 — Performance-gebaseerde blacklisting per exchange | Vermijdt recidive verliezers per bot-instance | ✅ DONE 2026-05-22 |
| P3 | US7 — Blacklist en coin profiles consistent | Betere debugbaarheid | ✅ DONE 2026-05-22 |
| P3 | US9 — Positiegrootte tijdelijk verlagen | Minder schade tijdens tuning | ✅ DONE 2026-05-20 |
| P3 | US10 — Logging exit-beslissingen verbeteren | Snellere post-run analyse | ✅ DONE 2026-05-22 |

---

## User Stories

### US1: Netto edge na fees verplicht maken ✅ DONE 2026-05-20

> **Implementatie:** Per-connector overrides worden nu toegepast op `fee_aware_filter` EN `economic_edge_gate` in de ST-12 edge gate (controller ~line 4991). De controller leest via `resolve_connector_config()` de connector-specifieke waarden op en merget ze over de globale config heen (`{**global_fee_cfg, **conn_fee_cfg}`). Connector-overrides zijn actief in beide YAML-configs (`connector_overrides.kraken_spot.fee_aware_filter` en `.economic_edge_gate`). Rejectie-log toont nu ook `fee_model` en `connector`. Tests: `TestUS1EdgeGatePerConnector` (5 tests, allen groen).

> **Opmerking:** Overlapt deels met ST-12 (Economic edge gate — reeds DONE in PRE_MASTERPLAN_BACKLOG).
> US1 voegt het geconfigureerde fee-model (`average` i.p.v. best-case maker) toe als nieuwe eis.

**Als** bot-owner
**wil ik** dat de bot alleen nieuwe grid-posities opent wanneer de verwachte netto edge na fees voldoende positief is
**zodat** kleine bruto winsten niet meer worden opgegeten door exchange-fees, ongeacht de exchange.

**Acceptatiecriteria**

- De bot berekent vóór entry de verwachte roundtrip-fees, gebruik makend van de werkelijke fee-structuur van de actieve connector.
- De bot gebruikt niet alleen best-case maker fees, maar een geconfigureerd fee-model (`maker`, `taker`, of `average`).
- Een entry wordt geweigerd als de verwachte netto winst lager is dan de ingestelde minimale edge.
- De logs tonen duidelijk: bruto verwachte profit, verwachte fees, netto edge, reden acceptatie/afwijzing.
- Het fee-model en de minimale edge zijn **per connector instelbaar** (exchanges hebben verschillende fee-structuren).

**Voorstel configuratie**

```yaml
# Globale defaults (gelden als er geen connector-override is)
economic_edge_gate:
  enabled: true
  fee_model: average       # maker | taker | average
  min_edge_pct: 0.20

# Per-connector overrides
connector_overrides:
  kraken_spot:
    economic_edge_gate:
      fee_model: taker     # Kraken rekent meestal taker-fee
      min_edge_pct: 0.25   # hogere drempel vanwege hogere Kraken-fees
  bitget_spot:
    economic_edge_gate:
      fee_model: maker
      min_edge_pct: 0.15
  okx_spot:
    economic_edge_gate:
      fee_model: maker
      min_edge_pct: 0.15
```

---

### US2: Fee-aware exit mag posities niet onbeperkt vasthouden ✅ DONE 2026-05-22

> **Implementatie:** `fee_aware_timeout_bypass_sec` toegevoegd aan `custom_info`. In `grid_executor._fee_aware_close_allowed`: als `age_sec >= bypass_sec` wordt de fee-guard overgeslagen en `True` teruggegeven. Log: `⏰ FEE_AWARE_BYPASS_FORCED`. Geconfigureerd in `spot_grid_kraken_usd.yaml` (3600s) en `spot_grid_kraken_eur.yaml` (5400s). Tests: `TestUS2FeeAwareBypass` (3 tests, allen groen).

**Als** bot-owner
**wil ik** dat `FEE_AWARE_EXIT` een exit slechts tijdelijk mag blokkeren
**zodat** de bot niet blijft hangen in verliesposities die steeds verder tegen mij in bewegen.

**Achtergrond:** In de laatste run werden 68.143 `FEE_AWARE_EXIT_BLOCKED`-events gelogd. Combinatie met `NO_PROGRESS_TIMEOUT` hield verliesposities onbeperkt open.

**Acceptatiecriteria**

- `FEE_AWARE_EXIT_BLOCKED` mag maximaal een ingestelde periode actief blijven.
- Na deze periode wordt de positie alsnog gesloten.
- De sluiting wordt expliciet gelogd als force-exit na fee-aware blokkade.
- De bot toont in de logs hoe lang de exit geblokkeerd is geweest.

**Voorstel configuratie**

```yaml
fee_aware_exit_enabled: true
fee_aware_exit_max_hold_minutes: 60
force_exit_overrides_fee_aware: true
```

---

### US3: Hard stop-loss moet fee-aware exit altijd overrulen ✅ DONE 2026-05-22

> **Implementatie:** `stop_loss_pct` verlaagd van 0.03 naar 0.015, `min_stop_pct` naar 0.010, `max_stop_pct` naar 0.020 in `spot_grid_kraken_usd.yaml`. STOP_LOSS is nooit fee-guarded (geborgd via `_is_fee_guarded_close_type`). `fee_aware_timeout_bypass_sec` toegevoegd als aanvullende vangnet (US2).

**Als** bot-owner
**wil ik** dat een hard stop-loss altijd voorrang heeft op fee-aware exit
**zodat** de bot verliesposities direct kan sluiten wanneer het maximale verliesniveau bereikt is.

**Achtergrond:** XDC-USD #2 verloor $1.72 doordat de prijs 2.9% daalde terwijl `FEE_AWARE_EXIT_BLOCKED` de positie vasthield. Er was geen hard ondergrens.

**Acceptatiecriteria**

- Wanneer een positie onder de ingestelde stop-loss komt, sluit de bot altijd.
- `FEE_AWARE_EXIT` mag een stop-loss niet blokkeren.
- De logs tonen duidelijk dat de stop-loss de fee-aware logic heeft overruled.
- De positie wordt niet opnieuw verlengd nadat stop-loss is geraakt.

**Voorstel configuratie**

```yaml
stop_loss_pct: 0.015
stop_loss_overrides_fee_aware: true
```

---

### US4: Absolute maximale hold time per positie ✅ DONE 2026-05-22

> **Implementatie:** `HARD_CAP_TIME_LIMIT` verwijderd uit de fee-guarded set in `_is_fee_guarded_close_type()`. Dit close_type passeert de fee-aware guard altijd, zodat de absolute max-hold nooit geblokkeerd kan worden. Tests: `TestUS4HardCapNotFeeGuarded` (5 tests, allen groen).

**Als** bot-owner
**wil ik** een absolute maximale looptijd per positie
**zodat** geen enkele grid-positie urenlang open blijft door timeouts, extensions of fee-aware blokkades.

**Achtergrond:** HYPE-USD #4 stond 755 minuten open (~12.5 uur). De `max_extension` van 120 minuten werkte niet omdat `FEE_AWARE_EXIT_BLOCKED` herhaaldelijk blokkeerde.

**Acceptatiecriteria**

- Elke positie krijgt een maximale hold time.
- Na het bereiken van deze limiet wordt de positie gesloten, ongeacht P&L.
- Fee-aware exit, no-progress timeout of grid extension mogen deze limiet niet resetten.
- De logs tonen: openingstijd, sluitingstijd, totale hold duration, reden `MAX_POSITION_HOLD_REACHED`.

**Voorstel configuratie**

```yaml
max_position_hold_minutes: 180
max_position_hold_overrides_fee_aware: true
```

---

### US5: Grid spacing kalibreren per exchange ✅ DONE 2026-05-22

> **Implementatie:** `connector_overrides` field + `resolve_connector_config()` toegevoegd aan `MultiCoinGridConfig`. Op twee plaatsen in `multi_coin_grid_controller.py` waar `min_grid_level_spacing_pct` wordt uitgelezen, wordt eerst de connector-override geraadpleegd. Tests: `TestUS5ConnectorOverrides` (4 tests, allen groen).

**Als** bot-owner
**wil ik** dat de minimale grid spacing per exchange instelbaar is en aansluit op de werkelijke fee-structuur van die exchange
**zodat** elke roundtrip op elke exchange na fees winstgevend kan zijn.

**Achtergrond:** Kraken USD run: gem. fee/volume was 0.20% per kant = 0.40% roundtrip. Gem. bruto winst per winner was 0.33% — ruim onder de fee-drempel. Bitget en OKX hebben lagere fees (~0.10% per kant), waardoor een andere minimale spacing geldt.

**Richtlijn per exchange:**

| Exchange | Typische fee per kant | Minimale roundtrip | Aanbevolen min spacing |
|---|---|---|---|
| Kraken | ~0.20–0.26% | ~0.52% | 0.75% |
| Bitget | ~0.08–0.10% | ~0.20% | 0.40% |
| OKX | ~0.08–0.10% | ~0.20% | 0.40% |

**Acceptatiecriteria**

- `min_grid_level_spacing_pct` is per connector instelbaar.
- Een globale default geldt als er geen connector-override aanwezig is.
- De bot opent geen grid als de verwachte spacing te klein is.
- De bot logt wanneer een coin wordt afgewezen door onvoldoende grid spacing, inclusief welke drempel gold.
- De eenheden zijn ondubbelzinnig gedocumenteerd: `0.75` = 0.75% (let op: controleer bij implementatie of de codebase dit als `0.0075` verwacht).

**Voorstel configuratie**

```yaml
# Globale default
min_grid_level_spacing_pct: 0.50

# Per-connector overrides
connector_overrides:
  kraken_spot:
    min_grid_level_spacing_pct: 0.75
  bitget_spot:
    min_grid_level_spacing_pct: 0.40
  okx_spot:
    min_grid_level_spacing_pct: 0.40
```

---

### US6: Performance-gebaseerde blacklisting per exchange-instance ✅ DONE 2026-05-22

> **Implementatie:** `get_effective_blacklist(connector_name)` toegevoegd aan `MultiCoinGridConfig`: geeft de unie terug van de globale `blacklist` en de connector-specifieke blacklist in `connector_overrides[connector_name]['blacklist']`. Alle 9 locaties in de controller die een blacklist opbouwen zijn gemigreerd naar deze methode. Tests: `TestUS6EffectiveBlacklist` (6 tests, allen groen).

**Als** bot-owner
**wil ik** dat coins die op een specifieke exchange structureel slecht presteren tijdelijk worden uitgesloten op dié exchange
**zodat** de bot niet opnieuw dezelfde zwakke setups opent, zonder dat de coin ook op andere exchanges geblokkeerd wordt.

**Aanleiding (Kraken USD run):**

| Coin | Netto P&L | Duur | Oorzaak |
|---|---|---|---|
| XDC-USD | -$1.72 | 158 min | Prijs -2.9%, vast door FEE_AWARE |
| PENGU-USD | -$0.58 | 120 min | NO_PROGRESS + FEE_AWARE blokkade |
| HYPE-USD | -$0.49 | 92 min | ATR adverse move, blokkade |

**Ontwerp-principe:** Een coin die op Kraken USD slecht presteert kan op Bitget prima werken (andere liquiditeit, spread, fees). De blacklist is daarom **per exchange-instance**, niet globaal.

**Acceptatiecriteria**

- Coins kunnen per exchange-instance worden geblacklist (niet alleen globaal).
- Bij evaluatie van een coin wordt de `gerealiseerde P&L per exchange` uit vorige runs meegenomen.
- Coins met slechte performance op een specifieke exchange worden tijdelijk geblacklist op dié exchange.
- Blacklisted coins mogen niet meer via dynamic discovery terugkomen op die instance.
- Als een coin zowel in `blacklist` als in `coin_profiles` staat, geeft de config-validatie een waarschuwing (zie ook US7).
- De reden en vervaldatum van de blacklist worden gelogd.

**Voorstel configuratie**

```yaml
# Globale blacklist (geldt op alle exchanges)
global_blacklist:
  - SCAM-USD

# Per-exchange blacklist (alleen op die instance)
connector_overrides:
  kraken_spot:
    blacklist:
      - HYPE-USD    # tijdelijk: slechte run 2026-05-18
      - XDC-USD     # tijdelijk: -$1.72 verlies door FEE_AWARE lock
      - PENGU-USD   # tijdelijk: NO_PROGRESS blokkade
  bitget_spot:
    blacklist: []   # niet geblacklist op Bitget
  okx_spot:
    blacklist: []   # niet geblacklist op OKX
```

---

### US7: Blacklist en coin profiles consistent maken ✅ DONE 2026-05-22

> **Implementatie:** `_warn_blacklist_profile_overlap()` toegevoegd aan `MultiCoinGridController`. Controleert bij startup of een coin uit `coin_profiles` ook in de effectieve blacklist staat (globaal + connector). Logt `⚠️ US7 CONFIG INCONSISTENCY` per overlap. Wordt aangeroepen in `on_start()`. Tests: `TestUS7BlacklistProfileOverlap` (4 tests, allen groen).

**Als** bot-owner
**wil ik** dat blacklisted coins niet tegelijk actieve coin profiles hebben
**zodat** debugging en configuratiegedrag voorspelbaar blijven.

**Acceptatiecriteria**

- De bot of config-validator detecteert coins die tegelijk in `blacklist` en `coin_profiles` staan.
- Bij overlap wordt een duidelijke waarschuwing gelogd bij startup.
- Optioneel faalt de bot-start als deze inconsistentie kritisch is.
- Blacklisted profiles worden verplaatst naar `disabled_coin_profiles` of verwijderd.

**Voorstel structuur**

```yaml
# Globale blacklist
global_blacklist:
  - SCAM-USD

# Per-exchange blacklist (zie US6)
connector_overrides:
  kraken_spot:
    blacklist:
      - HYPE-USD
      - XDC-USD
      - PENGU-USD

# Coin profiles die overeenkomen met een blacklisted coin
# worden verplaatst naar disabled_coin_profiles
disabled_coin_profiles:
  HYPE-USD:
    reason: "Temporarily disabled after poor performance on kraken_spot (2026-05-18 run)"
  XDC-USD:
    reason: "Temporarily disabled after -$1.72 loss on kraken_spot (2026-05-18 run)"
```

---

### US8: BEAR-regime logica eenduidig maken ✅ DONE 2026-05-20

> **Implementatie:** `_validate_bear_config()` toegevoegd aan `MultiCoinGridController`. Wordt aangeroepen in `on_start()`. Detecteert en logt drie scenarios: (1) conservatief — beide flags False → INFO; (2) tegenstrijdig — `bear_allow_meanrev=True` maar `max_active_grids=0` → WARNING; (3) redundant — zowel `bear_allow_meanrev` als `bear_auto_light_enabled` actief → WARNING. De BEAR kill-switch logica zelf was al correct; de methode voegt startup-validatie toe. Tests: `TestUS8BearConfigValidation` (5 tests, allen groen).

> **Opmerking:** Inhoudelijk gelijk aan **ST-07** in PRE_MASTERPLAN_BACKLOG (P1, 5 pt).
> Dit is de concrete config-uitwerking hiervan.

**Als** bot-owner
**wil ik** dat alle BEAR-regime instellingen hetzelfde beleid volgen
**zodat** de bot niet afhankelijk is van module-volgorde of conflicterende configuratie.

**Acceptatiecriteria**

- Er is één duidelijk BEAR-beleid.
- In conservatieve live mode wordt BEAR trading volledig geblokkeerd.
- Er zijn geen tegenstrijdige instellingen (bijv. BEAR max_grids=1 én bear_allow_trading=false tegelijk).
- De bot logt bij BEAR-regime duidelijk dat trading geblokkeerd is.

**Voorstel configuratie**

```yaml
adaptive_regime_detection:
  bear_meanrev_policy: block
  bear_auto_light_enabled: false

adaptive_filters:
  BEAR:
    max_active_grids: 0

regime_coin_selection:
  bear_allow_trading: false
  bear_max_grids: 0
```

---

### US9: Positiegrootte tijdelijk verlagen tot edge bewezen is ✅ DONE 2026-05-20

> **Implementatie:** Puur config — beide fields (`total_amount_quote`, `max_simultaneous_coins`) bestonden al en zijn `is_updatable: True`. In beide YAML-configs zijn commentaarregels toegevoegd met de US9-doelwaarden voor wanneer edge bewezen is (USD: 2 coins/$200; EUR: 3 coins/€200). De huidige live-waarden zijn NIET gewijzigd om de draaiende bot niet te verstoren. Tests: `TestUS9PositionSizeConfig` (5 tests, allen groen).

**Als** bot-owner
**wil ik** de positiegrootte tijdelijk verlagen
**zodat** verliezen beperkt blijven totdat de aangepaste strategie bewezen winstgevend is.

**Achtergrond:** Kraken USD trades zaten op ~$52 (full slot). Met -$0.93 gem. verlies is dit te groot voor de huidige configuratie. Elke exchange heeft een andere quote-currency (USD, EUR, USDT) en fee-structuur, dus de drempels verschillen per instance.

**Acceptatiecriteria**

- De bot draait tijdelijk met lagere exposure per positie, **per exchange instelbaar**.
- Het maximum aantal actieve coins is beperkt per exchange-instance.
- De bot rapporteert P&L per positie, per coin, en per exchange.
- Positiegrootte mag pas omhoog wanneer meerdere opeenvolgende runs op die instance netto positief zijn.
- De configuratie gebruikt de juiste quote-currency per exchange (USD voor Kraken USD, EUR voor Kraken EUR, USDT voor Bitget/OKX).

**Voorstel configuratie**

```yaml
# Per exchange-instance instellen in het bijbehorende config-bestand

# Kraken USD (conf/config_multi_coin_grid_v2_usd.yml)
total_amount_quote: 200      # tijdelijk verlaagd van ~500
max_simultaneous_coins: 2

# Kraken EUR (conf/config_multi_coin_grid_v2.yml)
total_amount_quote: 200      # EUR
max_simultaneous_coins: 2

# Bitget / OKX (conf/config_multi_coin_grid_v2_bitget.yml etc.)
total_amount_quote: 200      # USDT
max_simultaneous_coins: 2
```

---

### US10: Betere logging voor exit-beslissingen ✅ DONE 2026-05-22

> **Implementatie:** `FEE_AWARE_EXIT_BLOCKED`-log is rate-limited tot 1× per 60 seconden per `close_type`. Implementatie via twee state-dicts in `GridExecutor.__init__`: `_fee_aware_block_last_log` en `_fee_aware_block_count`. Bij het loggen wordt het geaccumuleerde aantal geblokkeerde calls als `×N` weergegeven. Tests: `TestUS10LogRateLimiting` (4 tests, allen groen).

**Als** bot-owner
**wil ik** per exit-beslissing duidelijke en niet-spammende logs zien
**zodat** ik direct kan begrijpen waarom een positie wel of niet gesloten wordt.

**Achtergrond:** 68.143 `FEE_AWARE_EXIT_BLOCKED`-regels in één run maakt de logs onleesbaar en maskeert echte problemen.

**Acceptatiecriteria**

- Elke exit-check logt: trading pair, current P&L, break-even prijs, fees, hold duration, exit reason, blocked reason.
- `FEE_AWARE_EXIT_BLOCKED` wordt niet onbeperkt gespamd (bijv. maximaal 1× per minuut per coin).
- Er komt een periodieke samenvatting per coin (bijv. elk uur).
- De bot toont aparte counters voor: stop-loss exits, fee-aware blocked exits, forced exits, max hold exits, no-progress exits.

**Voorbeeld log**

```text
[EXIT_DECISION] XDC-USD | pnl=-1.24% | hold=74m | reason=FEE_AWARE_BLOCKED
[FORCE_EXIT] XDC-USD | pnl=-1.61% | hold=81m | reason=STOP_LOSS_OVERRIDES_FEE_AWARE
```

---

## Dependency graph

```
US3 (stop-loss override)            ──→ implementeer eerst: blokkeert grootste verliezen
US2 (fee-aware max hold)            ──→ parallel met US3
US4 (absolute max hold)             ──→ parallel met US3, US2
US5 (grid spacing per exchange)     ──→ onafhankelijk, snel
US1 (edge gate per connector)       ──→ na US5 (spacing) voor consistente drempel
US8 (BEAR-regime)                   ──→ ST-07 in masterplan, onafhankelijk
US6 (performance blacklist)         ──→ config-only, direct; vereist US7 voor validatie
US7 (blacklist vs profiles)         ──→ na US6
US9 (positiegrootte per exchange)   ──→ config-only per instance, direct
US10 (logging)                      ──→ parallel met alles, geen blocker
```

---

## Totalen

| Laag | Items | Prioriteit |
|---|---|---|
| Risk / exit fixes | US2, US3, US4 | P1 |
| Edge / entry quality | US1, US5, US8 | P2 |
| Config / observability | US6, US7, US9, US10 | P3 |
| **Totaal** | **10 user stories** | |
