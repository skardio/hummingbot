# Pre-Masterplan Backlog — Multi-Coin Grid Bot

> **Datum:** 2026-04-04
> **Aanleiding:** Post-Voorstel-A analyse (GridScore als primaire ranking, ATR/regime tuning 2026-04-03)
> **Bevinding:** Bot opereert als single-coin (ALGO-USD) bot door cascading overfiltering. Net PnL: -$3,96 over 10,4 uur.
> **Scope:** Van hotfix tot research — alles wat nodig is om de bot naar multi-coin productiekwaliteit te brengen.

---

## Samenvatting

| Laag | Wat | Items | Wanneer |
|------|-----|-------|---------|
| **Laag 0** | Config hotfix | 1 hotfix | Vandaag |
| **Laag 1** | Spikes (discovery) | 5 spikes | Parallel, elk 2-4 uur |
| **Laag 2** | P0 implementation | 8 stories (52 pt) | Na relevante spike |
| **Laag 3** | P1 implementation | 6 stories (31 pt) | Na laag 2 |
| **Laag 4** | Research | 1 epic (5 items) | Na stabilisatie |

### Uitvoervolgorde

```
Week 1:  HF-01 live → SP-01..05 parallel + ST-02 + ST-03 starten
Week 2:  ST-01 (na SP-01) → ST-04 + ST-05a (na SP-02/SP-03) → ST-06a
Week 3:  ST-05b (na SP-04) → ST-06b (na SP-05)
Week 4+: ST-07..ST-12
Later:   RE-01
```

> **Let op:** ST-02 en ST-03 hebben geen spike-afhankelijkheid en kunnen
> starten zodra HF-01 live is, parallel met de spikes.

> **Let op:** Story points op spike-afhankelijke stories (ST-04, ST-05b, ST-06b)
> zijn voorlopige ramingen en worden herijkt na spike-uitkomst.

---

## Laag 0 — Hotfix

### HF-01: ATR / BEAR-config validatie-hotfix

| | |
|---|---|
| **Type** | Hotfix |
| **Priority** | P0 |
| **Effort** | < 1 uur |

**Doel**
De live overfiltering direct verminderen en valideren of de bot weer meer bruikbare candidates toelaat.

**Wijzigingen**

| Parameter | Oud | Nieuw | Reden |
|---|---|---|---|
| `atr_min_pct` (baseline) | 1.5 | 0.15 | Filterde alle coins (typische ATR: 0.05–0.5%) |
| `min_atr_pct_for_grid` | 1.5 | 0.15 | Synchroniseren met baseline |
| `bear_allow_meanrev` | false | true | Bot was 99% in BEAR → 1.284 entries geblokkeerd |

> **Let op:** Dit is een tijdelijke live-validatie, geen definitieve strategiekeuze.
> De BEAR-validatie wordt geëvalueerd in ST-07.

**Acceptatiecriteria**
- [ ] Config is aangepast met bovenstaande exacte waarden
- [ ] Nieuwe run is gestart
- [ ] `atr_min` rejects dalen aantoonbaar
- [ ] Aantal valide candidates stijgt aantoonbaar (meer dan alleen ALGO-USD)
- [ ] Er wordt expliciet gemeten of BEAR nu nuttige bounce setups doorlaat zonder duidelijk extra top-buying gedrag

---

## Laag 1 — Spikes

> Spikes zijn timeboxed onderzoeken. Elke spike levert een concreet implementatievoorstel
> voor de bijbehorende delivery-story. Geen spike = geen delivery.

### SP-01: ATR confidence architecture

| | |
|---|---|
| **Type** | Spike |
| **Priority** | P0 |
| **Tijdbox** | 2-4 uur |
| **Levert input voor** | ST-01 |

**Vraag**
Moet ATR überhaupt mee in confidence scaling, en zo ja, hoe?

**Context**
Huidige formule: `effective = baseline + (regime - baseline) × confidence`.
Met baseline 1.5% en BEAR override 0.08% bij confidence 0.6 → effectieve threshold 0.648%.
Dit neutraliseerde alle regime-overrides.

**Output**
- Analyse van huidige formule en effect op alle regimes
- Impact op effectieve ATR-threshold per confidence-niveau
- Concreet implementatievoorstel voor ST-01

---

### SP-02: NO_ORDERBOOK_DATA root cause

| | |
|---|---|
| **Type** | Spike |
| **Priority** | P0 |
| **Tijdbox** | 2-4 uur |
| **Levert input voor** | ST-04 |

**Vraag**
Waarom ontbreekt orderbook-data bij ~50% van SmartEntry evaluaties?

**Mogelijke oorzaken**
- Te veel subscriptions vs. Kraken rate limits
- Subscription-lifecycle (subscribe → sync → ready) te traag
- Candidate pool breder dan subscription-capaciteit
- Race condition bij pool-rotatie

**Output**
- Root cause met bewijs
- Geprioriteerde fix-opties
- Implementatievoorstel voor ST-04

---

### SP-03: Execution funnel leak

| | |
|---|---|
| **Type** | Spike |
| **Priority** | P0 |
| **Tijdbox** | 2-4 uur |
| **Levert input voor** | ST-05a |

**Vraag**
Waar vallen candidates weg tussen considered → allowed → approved → started?

**Methode**
Parseer logs van meest recente run. Kwantificeer conversieratio per stap.
Identificeer het grootste lek.

**Output**
- Funnel-metrics per stap
- Grootste drop-off met root cause
- Concreet implementatievoorstel voor ST-05a

---

### SP-04: NO_PROGRESS_TIMEOUT economics

| | |
|---|---|
| **Type** | Spike |
| **Priority** | P0 |
| **Tijdbox** | 2-4 uur |
| **Levert input voor** | ST-05b |

**Vraag**
Wat kost timeout-exit gedrag echt aan PnL en wat is een betere unwind-variant?

**Context**
Huidige data: 2 timeout-exits kosten -$4,41 (gem. -$2,21 per exit).
TAKE_PROFIT exits leveren gem. +$0,22. Risk/reward ratio 1:10.

**Output**
- PnL-impact analyse over alle beschikbare runs
- Typische timeout-scenario's (marktomstandigheid, holdtijd, inventory)
- Concreet voorstel voor nieuwe exitlogica (ST-05b)

---

### SP-05: Database logging failure

| | |
|---|---|
| **Type** | Spike |
| **Priority** | P0 |
| **Tijdbox** | 2-4 uur |
| **Levert input voor** | ST-06b |

**Vraag**
Waarom worden executors/fills niet correct opgeslagen in SQLite?

**Context**
Oude root cause: Strategy V2 hield gesloten executors in een buffer en schreef ze pas weg zodra de buffer groter werd dan de default `closed_executors_buffer`. Bij lage tradefrequentie bleef de laatste run daardoor onzichtbaar in `Executors`, terwijl `TradeFill` wel doorliep.

**Output**
- ✅ Technische root cause: executor-buffer + geen initial snapshot bij create.
- ✅ Fix: `closed_executors_buffer=0` voor EUR/USD scripts en initial executor snapshot bij `create_executor()`.
- ✅ Impactanalyse via `multi_coin_grid_pro/scripts/post_run_sqlite_report.py`.

---

## Laag 2 — P0 Implementation Stories

> Zuivere delivery. Discovery is afgerond in de bijbehorende spike.

### ST-01: ATR framework fix

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 5 |
| **Depends on** | SP-01, HF-01 |

**Als** quant/developer
**wil ik** dat ATR-filtering logisch, transparant en regime-consistent werkt
**zodat** de bot niet bijna alle candidates onterecht afwijst.

**Acceptatiecriteria**
- [ ] Effectieve ATR-threshold is zichtbaar per evaluatie (baseline, regime, confidence, effectief)
- [ ] ATR confidence-scaling is aangepast conform spike-uitkomst
- [ ] ATR-regimegedrag is technisch gedocumenteerd
- [ ] `atr_min` rejects dalen aantoonbaar t.o.v. pre-fix runs

---

### ST-02: Universe quality gate vóór ranking

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 8 |
| **Depends on** | — (kan direct starten na HF-01) |

**Als** quant/trader
**wil ik** dat alleen kwalitatieve en echt tradebare coins de ranking ingaan
**zodat** GridScore niet wordt verspild aan zwakke of ongeschikte candidates.

**Scope**
- Hard quality prefilter vóór GridScore ranking
- Exchange-specific universe policy
- Whitelist / allowed asset classes

**Acceptatiecriteria**
- [x] Quality prefilter draait vóór ranking — ✅ 2026-05-09: controller past `apply_quality_gate()` toe vóór `get_top_n_coins()` / GridScore.
- [x] Criteria omvatten minimaal:
  - Minimum 24h volume
  - Maximum gemiddelde spread
  - Orderbook/spread beschikbaarheid via cached spread-data
  - Minimale marktkwaliteit
  - Toegestane assetklasse per exchange (geen stablecoins, geen leveraged tokens)
- [x] Coins buiten beleid komen niet in ranking
- [x] Logs tonen hoeveel coins vóór ranking afvallen

**Statusupdate 2026-05-09**
- `utils/universe_quality_gate.py` filtert stablecoins, leveraged tokens, wrapped duplicates, blacklist, low-volume en wide-spread candidates.
- De gate wordt in de controller toegevoegd aan `excluded_coins_with_active` vóór ranking, zodat GridScore geen slechte universe-members meer ziet.
- Live tuning-update: `PLAY-USD` staat op de Kraken USD blacklist, omdat ruim 75% van zijn recente rejects `SPREAD_TOO_WIDE` was.
- Unit tests dekken assetclass-, volume- en spread-rejects.

---

### ST-03: Pool rotation control

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 8 |
| **Depends on** | — (kan direct starten na HF-01) |

**Als** quant/trader
**wil ik** dat pool-rotatie rustiger en selectiever wordt
**zodat** churn afneemt en de candidate pool stabieler wordt.

**Context**
Bestaande anti-churn (`switch_threshold_percent: 5.0`, `switch_grace_period_seconds: 600`)
beschermt de actieve coin, maar niet pool-membership. In de laatste run: 80 pool-rotaties
in 10,4 uur, met coins als ICNT-USD die 29× in/uit flipten.

**Acceptatiecriteria**
- [ ] Pool-membership cooldown is geïmplementeerd (coins blijven minimaal X minuten in pool)
- [ ] Churn guard is actief bij langdurig `Selected coin: None`
- [ ] Coins flippen niet meer direct in/uit de pool
- [ ] Rotaties per uur dalen aantoonbaar
- [ ] Rotatie-efficiëntie is zichtbaar (observability, niet kernimplementatie)

---

### ST-04: Data health and subscriptions fix

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 8 |
| **Depends on** | SP-02 |

> **Scopegrens:** ST-04 = data beschikbaar maken. Niet rapportage/tooling.

**Als** developer/operator
**wil ik** dat orderbook- en MTF-data betrouwbaar beschikbaar zijn voor top candidates
**zodat** de bot niet op runtime data-infra faalt.

**Acceptatiecriteria**
- [ ] Root cause uit SP-02 is opgelost of aantoonbaar gemitigeerd
- [ ] Top candidates krijgen prioriteit in subscriptions/dataflow
- [ ] `NO_ORDERBOOK_DATA` daalt aantoonbaar
- [ ] `MTF_INSUFFICIENT` daalt aantoonbaar
- [ ] Runtime data health is technisch aantoonbaar verbeterd

> **Story points worden herijkt na SP-02 uitkomst.**

---

### ST-05a: Execution funnel visibility and fix

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 5 |
| **Depends on** | SP-03 |

**Als** quant/developer
**wil ik** dat de execution funnel logisch en uitlegbaar werkt
**zodat** toegestane candidates vaker leiden tot een echte grid-start.

**Acceptatiecriteria**
- [x] Funnel considered → allowed → approved → started is zichtbaar — ✅ 2026-05-09: `ExecutionFunnelTracker` is aangesloten op selectie, admission en executor-start.
- [ ] Grootste drop-off uit SP-03 is opgelost of aantoonbaar verkleind
- [x] Redenen voor uitval zijn eenduidig voor de huidige selectie/admission laag
- [ ] Ratio `started / approved` verbetert aantoonbaar

**Statusupdate 2026-05-09**
- Controller logt een compacte selection funnel per tick via `_log_selection_trace()`.
- `ExecutionFunnelTracker` houdt rolling counters bij voor considered, allowed, rejected, approved en started, inclusief `started/approved`.
- Nog open: drop-off verbetering aantonen op run-data en eventueel koppelen aan post-run rapportage.

---

### ST-05b: Timeout exit redesign and softer unwind

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 8 |
| **Depends on** | SP-04 |

**Als** quant/trader
**wil ik** dat timeout-exits minder destructief zijn
**zodat** de bot niet structureel kleine winsten en grote verlies-exits produceert.

**Acceptatiecriteria**
- [x] Nieuwe `NO_PROGRESS_TIMEOUT` exitlogica is geïmplementeerd
- [x] Zachtere unwind-strategie is toegevoegd (bijv. limietorders, gefaseerde exit)
- [x] Forced-exit gedrag is uitlegbaar in logs
- [ ] Gemiddelde verliesgrootte bij timeout-exits daalt aantoonbaar

> **Story points worden herijkt na SP-04 uitkomst.**

**Statusupdate 2026-05-09**
- De `GridExecutor` gebruikt `start_forced_close(CloseType.NO_PROGRESS_TIMEOUT)` en het B1 two-phase protocol: `GRACEFUL` limit unwind met `close_grace_sec`, daarna `AGGRESSIVE` slippage-guarded close.
- Controller geeft nu ook `aggressive_close_method` en `aggressive_close_slippage_guard_pct` door in `custom_info`, zodat configwaarden de executor echt bereiken.
- `FEE_AWARE_EXIT_BLOCKED` krijgt een begrensde wachttijd voor `NO_PROGRESS_TIMEOUT`: standaard 2× `no_progress_timeout_sec`, configureerbaar via `fee_aware_timeout_bypass_sec`.
- Nog open: live-run bewijs dat gemiddelde timeout-loss kleiner wordt dan de oude forced-exit baseline.

---

### ST-06a: Selection trace and Top-N observability

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 5 |
| **Depends on** | — (soft dependency op ST-02 voor volledige trace) |

> **Scopegrens:** ST-06a = selectie zichtbaar maken. Niet database bugfixes.

**Als** quant/trader
**wil ik** selectie en ranking volledig kunnen volgen
**zodat** tuning sneller en objectiever gebeurt.

**Acceptatiecriteria**
- [x] Besluitketen per candidate is zichtbaar (universe → quality → ranking → SmartEntry → approval)
- [x] Top-N ranking is uitlegbaar (score, subscores, status)
- [x] Afvalredenen per stap zijn eenduidig
- [ ] Run-analyse kan selectiegedrag met vorige run vergelijken

> **Noot:** Volledige trace inclusief quality-gate pas compleet nadat ST-02 live is.
> Eerste versie tracet de huidige pipeline; wordt aangevuld na ST-02.

**Statusupdate 2026-05-09**
- ST-02 quality-gate logging, trend debug-info, MTF traces en `_log_selection_trace()` vormen nu één uitlegbare selectieflow.
- DecisionLogger krijgt selection-funnel snapshots wanneer structured observability aan staat.
- Nog open: automatische run-over-run vergelijking.

---

### ST-06b: Database logging fix and post-run analysis foundation

| | |
|---|---|
| **Type** | Story |
| **Priority** | P0 |
| **Story points** | 5 |
| **Depends on** | SP-05 |

> **Scopegrens:** ST-06b = data opslaan en bruikbaar maken. Niet runtime subscriptions.

**Als** quant/researcher
**wil ik** dat executors en fills correct worden opgeslagen en standaard geanalyseerd kunnen worden
**zodat** run-vergelijking en historische analyse betrouwbaar worden.

**Acceptatiecriteria**
- [x] Executors en fills worden weer correct weggeschreven
- [x] Datakwaliteit is gecontroleerd (timestamps, foreign keys, completeness)
- [x] Basale post-run analyse werkt op deze data
- [x] Run-analyse kan automatisch vergelijken met de vorige run

> **Story points worden herijkt na SP-05 uitkomst.**

**Statusupdate 2026-05-09**
- ✅ Subscope `TradeLabelStore aansluiten`: controller initialiseert `TradeLabelStore`, laadt recente labels bij startup en schrijft labels bij close.
- ✅ Label bug gefixt: sessie gebruikt een unix timestamp; `session_from_utc()` accepteert nu ook `datetime` voor backward compatibility.
- ✅ Label context is rijker: `timestamp_open`, sessie, regime, spread, depth, quality score, reentry en cycle-number komen uit entry/close context.
- ✅ Executor SQLite root cause aangepakt: gesloten executors worden direct opgeslagen (`closed_executors_buffer=0`) en nieuwe executors krijgen bij creatie een eerste SQLite snapshot.
- ✅ Basale post-run analyse toegevoegd: `python multi_coin_grid_pro/scripts/post_run_sqlite_report.py --bot kraken-usd --hours 24`.

**Statusupdate 2026-05-10**
- ✅ Actieve executors krijgen nu periodiek een live SQLite snapshot, zodat fills die tijdens een actieve grid binnenkomen niet alleen in `TradeFill` staan maar ook in de `Executors`-snapshot zichtbaar worden.
- ✅ `post_run_sqlite_report.py` markeert actieve executor/TradeFill mismatches, bijvoorbeeld een actieve FIL-executor met `executor_volume=0` maar wel een FIL-buy in `TradeFill`.
- ✅ `FAILED + INSUFFICIENT_BALANCE` wordt apart geclassificeerd als data/uitvoering-error en telt niet meer stilzwijgend mee als normale win.
- Restgap: bestaande historische runs blijven incompleet waar executors destijds niet geflusht zijn; het rapport toont deze gaten nu expliciet.

---

## Laag 3 — P1 Stories

> Pas na laag 2. Kleinere, gerichte verbeteringen.

### ST-07: BEAR regime logic cleanup

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 5 |

**Als** quant/trader
**wil ik** dat BEAR-regime gedrag strategisch consistent is
**zodat** mean-reversion in dalende markten bewust en uitlegbaar blijft.

**Acceptatiecriteria**
- [x] Tijdelijke HF-01 validatie is geëvalueerd op live data
- [x] Definitief BEAR-beleid is gekozen (true / false / conditioneel)
- [x] Regime-blocking is consistent (geen verborgen bypasses)
- [x] Regime-beslissingen zijn traceerbaar in logs

**Statusupdate 2026-05-09**
- Definitief beleid gekozen: **conditioneel**. Diepe BEAR blokkeert nieuwe entries; ondiepe BEAR mag alleen via BEAR-light (`score > bear_auto_light_threshold`), met size multiplier en BTC-divergence check.
- `bear_allow_meanrev` is teruggezet naar `false`; de actieve policy is `adaptive_regime_detection.bear_meanrev_policy: conditional`.
- Regime-blocks emitten nu `REGIME_BEAR_BLOCKED` met policy/score/threshold metadata.

---

### ST-08: Inventory and grid symmetry monitoring

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 5 |

**Als** quant/trader
**wil ik** scheve grids en inventory build-up vroeg zien
**zodat** one-sided risk sneller zichtbaar wordt.

**Acceptatiecriteria**
- [ ] Per actieve grid zijn zichtbaar: buys, sells, inventory, avg entry, unrealized PnL
- [ ] Buy/sell ratio en roundtrips zijn zichtbaar
- [ ] One-sided grids worden gemarkeerd

---

### ST-09: Selection efficiency metrics

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 5 |

**Als** quant/trader
**wil ik** de efficiency van selectie en rotatie meten
**zodat** zichtbaar wordt hoeveel engine-werk echt bruikbare trades oplevert.

**Acceptatiecriteria**
- [ ] Metrics beschikbaar: selected/eligible, approved/selected, started/approved, rotations/grids, time in `Selected coin: None`
- [ ] Rapport per run beschikbaar

---

### ST-10: Fee-to-edge visibility

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 3 |

**Als** quant/trader
**wil ik** fees, spread en netto edge zichtbaar hebben
**zodat** economische gezondheid per run snel beoordeeld kan worden.

**Acceptatiecriteria**
- [ ] Fee/profit ratio standaard zichtbaar
- [ ] Netto en bruto PnL zichtbaar
- [ ] Runs met economisch ongezonde ratio's worden gemarkeerd

---

### ST-11: Low-trade / idle mode ✅ DONE

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 5 |
| **Status** | ✅ **DONE** (2026-04-12) |

**Als** quant/trader
**wil ik** dat de bot naar een gecontroleerde idle mode kan gaan
**zodat** hij niet nutteloos blijft scannen en roteren bij gebrek aan edge.

**Acceptatiecriteria**
- [x] Idle mode activeert onder duidelijke, configureerbare voorwaarden
- [x] Gedrag in idle mode is configureerbaar (scan-interval, pool freeze, etc.)
- [x] Modewissels zijn zichtbaar in logs

---

### ST-12: Economic edge gate ✅ DONE

| | |
|---|---|
| **Type** | Story |
| **Priority** | P1 |
| **Story points** | 8 |
| **Status** | ✅ **DONE** (2026-04-12) |

**Als** quant/trader
**wil ik** dat trades alleen worden toegestaan als verwachte capture boven kosten ligt
**zodat** de bot geen economisch zinloze setups neemt.

**Acceptatiecriteria**
- [x] Eerste edge/EV-proxy is toegevoegd
- [x] Fees, spread en slippage worden meegenomen
- [x] Trades kunnen op economische gronden worden afgewezen

---

## Laag 4 — Research Epic

> Pas doen als de bot weer gezond draait en voldoende data genereert.

### RE-01: GridScore and feature validation

| | |
|---|---|
| **Type** | Research Epic |
| **Priority** | P2 |

**Onderzoeken:**

| # | Onderwerp | Doel |
|---|---|---|
| RE-01a | GridScore feature evaluatie | Welke score-componenten correleren met echte grid-uitkomsten? |
| RE-01b | Robuustere mean-reversion metrics | Hurst exponent, variance ratio, half-life — toepasbaarheid beoordelen |
| RE-01c | Data-driven score weights | Gewichten baseren op historische feature→PnL relaties |
| RE-01d | Backtest candidate filters | ATR-regels en quality filters toetsen op historische data |
| RE-01e | Out-of-sample validatie | Overfitting-risico beoordelen, train/test split |

---

## Overzicht: wat is geschrapt of samengevoegd

De oorspronkelijke 40-story backlog is teruggebracht tot 20 items door:

### Geschrapt (bestaat al in codebase)

| Onderwerp | Waar het al zit |
|---|---|
| Reject-overzicht per filter | `observability/why_no_trade_v2.py` — per-filter funnel, threshold-vs-reality stats |
| Regime logging per evaluatie | `AdaptiveFilterResolver.explain_active_filters()` + regime in dynamic slots logs |
| Blacklist basismechanisme | Session blacklist + parabolic blacklist + SQLite persistent cooldowns |
| Switch-threshold op actieve coin | `switch_threshold_percent: 5.0` + `switch_grace_period_seconds: 600` |
| Switch-hysteresis | `switch_hysteresis_pct` in config model |
| Why-no-trade rapportage | `observability/why_no_trade_v2.py` — per-uur rapporten, al actief in productie |

### Samengevoegd

| Oorspronkelijk (US-nummers) | Geworden |
|---|---|
| US-01, US-02, US-03, US-04, US-05 | **ST-01** (ATR framework fix) |
| US-09, US-10, US-11, US-12 | **ST-02** (Universe quality gate) |
| US-13, US-14, US-15, US-16, US-17 | **ST-03** (Pool rotation control) |
| US-18, US-19, US-20, US-21 | **ST-04** (Data health fix) |
| US-22, US-24, US-25 | **ST-05a + ST-05b** (Execution funnel + timeout redesign) |
| US-29, US-30, US-32, US-33, US-34 | **ST-06a + ST-06b** (Observability + database fix) |

---

## Dependency graph

```
HF-01 (vandaag)
  │
  ├──→ SP-01 ──→ ST-01
  ├──→ SP-02 ──→ ST-04
  ├──→ SP-03 ──→ ST-05a
  ├──→ SP-04 ──→ ST-05b
  ├──→ SP-05 ──→ ST-06b
  │
  ├──→ ST-02 (geen spike nodig)
  ├──→ ST-03 (geen spike nodig)
  └──→ ST-06a (soft dep op ST-02 voor volledige trace)

ST-07..ST-12: na laag 2
RE-01: na stabilisatie
```

---

## Totalen

| Laag | Items | Story points | Dependencies |
|------|-------|-------------|--------------|
| **Laag 0** | 1 hotfix | — | Geen |
| **Laag 1** | 5 spikes | — (timeboxed 2-4u elk) | HF-01 |
| **Laag 2** | 8 stories | 52 pt * | Per story: zie dependency graph |
| **Laag 3** | 6 stories | 31 pt | Laag 2 compleet |
| **Laag 4** | 1 research epic | — | Bot stabiel + voldoende data |
| **Totaal** | **21 items** | **83 pt** | |

\* *Story points op spike-afhankelijke stories zijn voorlopig en worden herijkt na spike-uitkomst.*
