# Review: ChatGPT "Professionele Quant" Backlog vs. Werkelijkheid

> Gegenereerd: 2026-04-26 | Gebaseerd op: `000_The_masterPlan.md` (27 items)
> Doel: kritisch doorlichten wat al bestaat, wat ontbreekt, wat overdreven is
> **Gecontroleerd: 2026-04-28** - staged changes nagelopen tegen controller-code. Eerdere "gebouwd + ingehangen" claims waren te optimistisch: meerdere modules bestaan, maar zijn niet volledig end-to-end actief.

---

## Samenvatting

| Status | Aantal | Correctie na staged-code audit |
|--------|--------|-------------------------------|
| ✅ Aantoonbaar actief in productiepad | 17 | Incl. register_close_trade wiring, capital_reserve_pct, MetaCoinRanker, ST-02 universe gate, gedeelde entry-gates, ST-05a funnel, ST-05b soft unwind wiring en ST-06b SQLite flush/post-run basis (2026-05-09) |
| 🟡 Module aanwezig of primair pad deels aangesloten | 4 | Vooral dashboarding en scoremodel-restgaps |
| ❌ Niet geïmplementeerd of niet aangesloten | 3 | Item 13 gross turnover, item 21 dashboard, Monte Carlo operationalisering |
| 🗑️ Schrappen / niet prioriteit | 4 | Ongewijzigd |

## Audit 2026-04-28 — Claims "gebouwd" vs. staged werkelijkheid

| Item | Claim in dit document | Werkelijkheid in staged changes |
|------|-----------------------|---------------------------------|
| Item 1 | Gebouwd + controller | ✅ **2026-05-09**: `register_close_trade()` voedt exit-type cooldown/failed-cycle state én `EntryGateway` draait nu via één gedeelde admission-helper voor slot 1 en de multi-coin vervolglus. |
| Item 3 | Daily kill switch klaar | 🟡 Logic + pre-entry checks bestaan. ✅ **2026-05-09**: gerealiseerde close-PnL wordt nu naar `GlobalRiskManager.register_close_trade()` gestuurd via `_sync_risk_state()` — per-coin -1R/-2R checks zijn live actief. |
| Item 5 | Volledig scoremodel | 🟡 Scorer draait nu in alle entry-slots met echte RSI uit candles, spread%, orderbook depth multiple, ATR% en BTC 1h trend. Restgap: geen fakeout/slippage component. |
| Item 6 | ATR calibrator actief | 🟡 Calibrator registreert ATR en logt suggesties; hij past grid multipliers nog niet automatisch toe. |
| Item 8 | Quality sizing actief | ✅ Quality sizing draait via gedeelde admission-helper voor slot 1/2/3 en wordt na resize opnieuw door EntryGateway gevalideerd. |
| Item 9/10 | Bucket exposure actief | 🟡 Bucket tracker draait nu in alle entrypaden en checkt ná quality sizing. Dit is nog bucket-blocking, geen size-down. |
| Item 13 | Gebouwd | ❌ Gross daily turnover per coin is niet gebouwd. Alleen bucket-exposure bestaat. |
| Item 14 | Trade labeling volledig | 🟡 `TradeLabelStore` wordt geïnitialiseerd, labels worden bij startup geladen en bij close persistent opgeslagen. Restgap: MFE/MAE blijven placeholders. |
| Item 15/17 | Session edge / coin-session block | ✅ SessionEdgeDetector gebruikt persistente labels en draait via gedeelde admission-helper voor alle entry-slots. |
| Item 16 | Meta ranking ingehangen | ✅ **2026-05-09**: `MetaCoinRanker.rank()` aangeroepen na grid-suitability filter; `top_coins` hergesorteerd op historische win-rate/PnL vóór `pick_first_inactive()`. |
| Item 18 | Fill monitor volledig | 🟡 Monitor bestaat, maar controller registreert één synthetische close-sample met config start/end price, niet elke echte fill. |
| Item 19 | Reserve architectuur | ✅ **2026-05-09**: `get_deployable_balance()` nu aangeroepen na `_get_quote_balances_for_allocation()`; `available_balance` verminderd met `capital_reserve_pct` vóór doorgave aan `calculate_optimal_allocation()`. |
| Item 20 | Niet geïmplementeerd | 🟡 Monte Carlo tool + tests bestaan in staged changes; nog geen operationele runbook/data-koppeling. |

---

## ✅ Al Geïmplementeerd — Niet opnieuw bouwen

### ST-02 — Universe Quality Gate vóór ranking
**Status: ✅ INGEHANGEN (2026-05-09)**
- `utils/universe_quality_gate.py` filtert stablecoins, leveraged/inverse tokens, wrapped duplicates, blacklist, lage 24h-volume en brede spreads.
- Controller past de gate toe vóór `trend_calculator.get_top_n_coins()` en dus vóór GridScore ranking.
- Logs tonen hoeveel coins vóór ranking afvallen met reden-tellingen.
- Update 2026-05-09: `PLAY-USD` staat op de Kraken USD blacklist na structurele `SPREAD_TOO_WIDE` concentratie in live events.

### ST-05a / ST-06a — Funnel en selectie-observability
**Status: ✅ EERSTE PRODUCTIESLICE ACTIEF (2026-05-09)**
- `_log_selection_trace()` logt per tick monitored pool, active grids, qualifying/top coins, rejection counts en selected/no-selection outcome.
- `ExecutionFunnelTracker` telt rolling considered, allowed, rejected, approved en started, inclusief `started/approved`.
- DecisionLogger krijgt selection-funnel snapshots wanneer structured observability aan staat.
- Restgap: automatische run-over-run analyse.

### ST-05b — Timeout soft unwind
**Status: ✅ TECHNISCH AANGESLOTEN (2026-05-09)**
- `NO_PROGRESS_TIMEOUT` start de bestaande B1 two-phase unwind: eerst `GRACEFUL` limit close, daarna pas `AGGRESSIVE` slippage-guarded close.
- Controller geeft `close_grace_sec`, `aggressive_close_method` en `aggressive_close_slippage_guard_pct` door aan de executor.
- Update 2026-05-09: fee-aware exit guard krijgt een timeout-bypass voor `NO_PROGRESS_TIMEOUT` na `fee_aware_timeout_bypass_sec` of automatisch na 2× `no_progress_timeout_sec`, zodat een slot niet eindeloos in `FEE_AWARE_EXIT_BLOCKED` blijft hangen.
- Restgap: live bewijs dat timeout-loss kleiner wordt dan de forced-exit baseline.

### Item 4 — Hard Pre-Trade Risk Gateway
**Status: ✅ CENTRAAL ACTIEF (2026-05-09)**
- `GlobalRiskManager.can_open_trade()` blokkeert op: max exposure, exit cooldown, switch cooldown
- `SmartEntryFilter` controleert: spread, orderboekdiepte, RSI, regime
- `MarketRegimeFilter` blokkeert bij BTC dump
- `EntryGateway` is toegevoegd en draait via gedeelde admission-helper voor primaire entry en multi-coin vervolglus

### Item 6 — Adaptive Grid Width
**Status: GEDEELTELIJK GEÏMPLEMENTEERD + ATR CALIBRATOR TELEMETRIE**
- ATR-gebaseerde grid levels al actief in controller
- `atr_pct` bepaalt grid spread per coin
- **Nieuw (2026-04-26):** `ATRCalibrator` module gebouwd (`scoring/atr_calibrator.py`) en ingehangen — slaat ATR-observaties op per coin en berekent `suggest()` na 20+ samples
- ❗ Suggesties worden alleen gelogd; multipliers worden nog niet automatisch toegepast

### Item 11 — Correlation Guard (BTC dump block)
**Status: VOLLEDIG**
- `MarketRegimeFilter` meet BTC trend 1h/4h/24h
- Blokkeert alt-entries bij dump, herstelt bij recovery
- Persistente cooldown na dump

### Item 12 (deels) — Liquidity auto-block bij entry
**Status: AANWEZIG**
- Spread check + orderboekdiepte check in `SmartEntryFilter`
- NL-restriction auto-blacklist aanwezig en persistent
- Volume minimum in `CoinSelector`

### Item 26 — Stop Trading Risky Alts During BTC Dump
**Status: VOLLEDIG** (zelfde als item 11)

---

## 🟡 Gedeeltelijk Aanwezig — Verbetering nodig, niet van nul

### Item 1 — Re-entry Control Engine
**Wat er is:** stop-loss cooldown via `last_switch_time` + `min_switch_interval_seconds` (5 min). Exit cooldown in `GlobalRiskManager`.
**Wat er nieuw is:** `EntryGateway` (`core/entry_gateway.py`) gebouwd, close-PnL wordt geregistreerd, en alle nieuwe entry-slots gebruiken dezelfde admission-helper.
**Wat ontbreekt:** geen groot production gap meer; restpunten zitten in observability en latere pattern-aware cooldowns.
**Status: ✅ IN PRODUCTIEPAD**

### Item 2 — State-Aware Re-entry Machine
**Wat er is:** basisachtige exit-tracking via `_last_exit_time` en `note_exit()`.
**Wat er nieuw is:** `GlobalRiskManager` heeft expliciete `CoinCycleState` (`READY`, `WIN_EXIT`, `LOSS_EXIT`, `TWO_FAILED_CYCLES`) plus `get_coin_cycle_status()`. Close-PnL voedt de state via `register_close_trade()`, en de controller blokkeert `TWO_FAILED_CYCLES` vroeg in de gedeelde admission-helper.
**Wat ontbreekt:** alleen uitgebreidere reporting/visualisatie van states.
**Status: ✅ AFGEROND VOOR RE-ENTRY LOCK**

### Item 3 — Daily Coin Kill Switch
**Wat er is:** `GlobalRiskManager` tracks per-coin gerealiseerde PnL.
**Wat er nieuw is:** -1R halve size en -2R hard block bestaan als helpers en primaire pre-entry checks.
**Wat ontbreekt:** gerealiseerde close-PnL wordt niet naar `GlobalRiskManager` gevoed in de controller. Daardoor is de live per-coin teller leeg, tenzij een andere caller expliciet `record_coin_pnl()` of `register_close_trade()` aanroept.
**Status: GEDEELTELIJK / BUG IN WIRING**

### Item 5 — Trade Quality Filter (scoremodel)
**Status: GEDEELTELIJK GEBOUWD + ALLE ENTRY-SLOTS INGEHANGEN (2026-05-09)**
- `TradeQualityScorer` (`scoring/trade_quality_scorer.py`) geeft 0–100 score op: regime, RSI, spread, diepte, volatiliteit, BTC-trend
- `quality_size_multiplier()` converteert score naar positie-multiplier (0.5x–1.25x)
- Ingehangen in gedeelde admission-helper vóór `_create_grid_action()` voor primaire en multi-coin vervolglus
- ✅ Inputs zijn niet langer blind constants: RSI komt uit candles, spread uit cached pair spread, depth uit orderbook, ATR uit candles/fallback-volatility, BTC-trend uit `BTC-{quote}` 1h trend
- ❗ Geen fakeout/slippage component.

### Item 9 — Inventory-Aware Sizing
**Status: GEDEELTELIJK GEBOUWD + ALLE ENTRY-SLOTS INGEHANGEN (2026-05-09)**
- `BucketExposureTracker` (`core/risk_buckets.py`) groepeert coins in bucket-categorieën (meme/L1/altcoin/stablecoin)
- `can_add(coin, notional)` blokkeert als bucket-cap bereikt is
- Ingehangen in gedeelde admission-helper — blokkeert entry als bucket vol is
- ✅ Check draait nu ná quality sizing en ook in de multi-coin vervolglus
- ❗ Geen size-down bij bucket-cap; alleen block.

### Item 10 — Portfolio Exposure Engine
**Wat er is:** max open allocations, max per-coin notional in `GlobalRiskManager`.
**Wat ontbreekt:** risk bucket concept (meme beta / L1-L2 / illiquid smallcap). Geen bucket-level cap.
**Oordeel:** Bouw de architectuur nu. Bij €25k+ met 10+ coins tegelijk is bucket-exposure een harde vereiste. €300 is de validatiefase, niet het eindpunt.
**Update (2026-04-28):** Bucket-architectuur aanwezig via `BucketExposureTracker`, maar niet in `GlobalRiskManager`, niet in alle entrypaden, en niet als size-down mechanisme — zie item 9.

### Item 13 — Per-Coin Daily Exposure Cap
**Wat er is:** max open notional per coin.
**Wat ontbreekt:** gross daily turnover per coin (som van alle buys die dag).
**Echte gap:** klein — één teller bijhouden.
**Status: NIET GEÏMPLEMENTEERD** — staged changes voegen geen gross daily turnover teller toe. Bucket-level cap is iets anders.

### Item 22 — Stop Random Smallcap Trading
**Wat er is:** volume minimum, spread filter, blacklist in `CoinSelector`.
**Wat ontbreekt:** geen kwaliteitsranking — alleen volume-drempel. Geen fakeout-rate of slippage profiel.
**Oordeel:** basisbeveiliging aanwezig, kwantitatieve ranking is nice-to-have.

---

## Backlogitems 7-21 — Gecorrigeerde Status

### Item 7 — Dynamic Profit Taking
**Status: GEÏMPLEMENTEERD** — controller berekent dynamic TP op basis van trendsterkte en schrijft dit naar `GridExecutorConfig`.
**Restgap:** geen echte scale-out logica; dit is dynamische TP, geen volledige position-management layer.

### Item 8 — Position Sizing op Kwaliteit
**Status: ✅ ALLE ENTRY-SLOTS INGEHANGEN (2026-05-09)**
- `quality_size_multiplier(score, halved)` in `scoring/trade_quality_scorer.py`
- Score <40 → 0.5x, 40-60 → 0.75x, 60-80 → 1.0x, >=80 → 1.25x
- Ingehangen via gedeelde admission-helper vóór `_create_grid_action()` in primair entrypad én multi-coin vervolglus
- Na resize volgt opnieuw EntryGateway-validatie zodat upsize niet langs risk caps glipt

### Item 14 — Learn From Logs Engine (trade labeling)
**Status: 🟡 PERSISTENTIE INGEHANGEN (2026-05-09)**
- `TradeLabel` dataclass + `TradeLabelStore` bestaan
- Controller laadt bij startup recente labels uit `data/trade_labels_<instance>.db`
- Controller schrijft bij close naar in-memory buffer én `TradeLabelStore`
- ✅ `timestamp_open`, sessie, regime, spread, depth, quality, reentry en cycle-number worden uit entry-context gevuld
- ❗ MFE/MAE blijven placeholders.

### Item 15 — Session Edge Detection
**Status: ✅ ALLE ENTRY-SLOTS + PERSISTENTE LABELS (2026-05-09)**
- `SessionEdgeDetector` (`core/session_edge_detector.py`) analyseert TradeLabel history per sessie (Asia/EU/US/weekend)
- `session_from_utc()` bepaalt huidige sessie
- Ingehangen in gedeelde admission-helper — blokkeert entry als sessie historisch slecht presteert voor die coin
- Gebruikt bij startup geladen `TradeLabelStore` labels en draait ook in de multi-coin vervolglus

### Item 16 — Meta Ranking Engine
**Status: ✅ INGEHANGEN (2026-05-09)**
- `MetaCoinRanker` (`core/meta_coin_ranker.py`) rankt coins op historische PnL + win rate uit TradeLabel buffer
- `.rank(labels)` geeft gesorteerde lijst terug
- ✅ Controller roept `.rank(self._trade_labels)` aan na grid-suitability filter; `top_coins` hergesorteerd op score vóór `pick_first_inactive()`. Faalt stil als er < `min_trades=5` trades per coin zijn.

### Item 17 — Session + Coin Auto Block
**Gap:** geen `coin × sessie` combinatie tracking.
**Prioriteit:** LAAG — vereist data van item 15 first.
**Update (2026-05-09):** SessionEdgeDetector filtert per coin en sessie in alle entrypaden en gebruikt persistente TradeLabelStore history. Specifieke coin×sessie metrics blijven een later analysepunt.

### Item 18 — Fill Quality Monitor
**Status: MODULE GEBOUWD + BEPERKT INGEHANGEN (2026-04-26)**
- `FillQualityMonitor` (`core/fill_quality_monitor.py`) vergelijkt expected vs actual fill price
- `record_fill(*, symbol, expected_price, actual_price, side, size_quote, timestamp)` wordt bij terminated executor aangeroepen als start/end price beschikbaar is
- `.avg_slippage_pct()` en `.summary()` beschikbaar voor analyse
- ❗ Niet elke echte fill wordt geregistreerd; controller gebruikt config start/end price als proxy, niet werkelijke fill-prijzen

### Item 19 — Capital Efficiency Layer
**Status: ✅ INGEHANGEN (2026-05-09)**
- `capital_reserve_pct` (default 10%) wordt nu toegepast: `get_deployable_balance()` vermindert `available_balance` vóór `calculate_optimal_allocation()`.
- 2026-05-09 follow-up: dit geldt nu voor het primaire slot én de multi-coin vervolglus.
- Bij 10% reserve op €300 = €270 deployable. Debug-log toont verschil.
- Nog te doen: budget_allocator gebruikt nog `raw_available_balance` voor de interne check — consistent houden bij hogere schaal.

### Item 20 — Monte Carlo Risk Test
**Status: TOOL GEBOUWD, NOG NIET OPERATIONEEL IN PROCES**
- `multi_coin_grid_pro/tools/monte_carlo.py` + unit tests bestaan in staged changes
- Restgap: geen runbook, geen automatische koppeling aan trade-label database, geen periodieke rapportage
**Prioriteit:** LAAG — research/backtesting tool, niet productiepad.

### Item 21 — Execution Quality Dashboard
**Gap:** geen unified dashboard. Alles verspreid over logs.
**Prioriteit:** LAAG — operationeel comfort, geen direct PnL impact.
**Statusupdate 2026-05-09:** bewust niet vandaag gebouwd; eerst entry-gates en persistente labels afgerond. Dashboard blijft later item.

---

## 🗑️ Schrappen of Later — Niet nu

### Item 23 — "Stop Fixed Cooldown"
Al gedeeltelijk opgelost. Hoeft geen apart project te worden — valt onder item 1.

---

## ⚠️ Tijdlijn-gebonden items — Bouwen, maar faseren

> Doelkapitaal is €25.000+. €300 is de validatiefase. Deze items zijn **geen overkill** — ze zijn noodzakelijk vóór schaling.
> Bouw de architectuur nu zodat aanzetten op schaal geen refactor vereist.

### Item 10 — Risk Buckets (meme beta / L1 / smallcap)
**Fase:** Architectuur nu, activeren bij >€5k
Bij €25k met 10+ coins simultaan is bucket-exposure een harde vereiste. Zonder dit is vijf meme-coins tegelijk één geconcentreerde bet, niet diversificatie.
**Wat te doen nu:** bucket-check is consistent in alle entrypaden en draait ná quality sizing. Later nog beslissen of bucket-cap moet blokkeren of size reduceren. Integratie in `GlobalRiskManager` is nog niet gedaan.

### Item 19 — Capital Efficiency Reserve
**Fase:** Activeren bij >€10k
Bij hogere kapitaalschalen is permanent volledig deployed zijn suboptimaal — betere setups komen terwijl je vastzit in middelmatige trades.
**Wat te doen nu:** `capital_reserve_pct` bestaat al; pas hem toe in de allocatieberekening (`available_balance` / `DynamicSlotManager`) en test dat budget allocator dezelfde deployable balance gebruikt.

### Item 20 — Monte Carlo Risk Test
**Fase:** Uitvoeren na 500+ trades (genoeg historische data)
Bij €25k wil je weten of het systeem een drawdown-reeks van 10 losers overleeft zonder margin call. Zonder dit is schalen blind vertrouwen.
**Wat te doen nu:** trade-label persistence is actief. Later nog runbook/command toevoegen voor periodieke Monte Carlo analyse.

---

## Prioriteitenlijst voor Implementatie

> Gesorteerd op PnL-impact × uitvoerbaarheid. Niet op ChatGPT-nummering.
> **Gecontroleerd 2026-04-28** — meerdere P-items hebben alleen module- of primair-pad dekking. Zie statuskolom.

| Prio | Item | Omschrijving | Status |
|------|------|-------------|--------|
| **P1** | Item 1 (gap) | Exit-type differentiatie in cooldown (TP=15m, SL=4h, trend=block) | ✅ Close-PnL gevoed en EntryGateway gedeeld over alle entry-slots (2026-05-09) |
| **P2** | Item 3 | Daily coin kill switch (-1R halve size, -2R block) | ✅ Live gevoed via `register_close_trade()` (2026-05-09); per-coin teller actief |
| **P3** | Item 7 | Dynamic TP (bounce-strength scale-out) | ✅ Dynamic TP actief; geen scale-out |
| **P4** | Item 14 | Trade labeling (regime, spread, reentry, MFE/MAE → in-memory buffer) | 🟡 Store + echte contextvelden actief; MFE/MAE missen |
| **P5** | Item 2 | State-aware re-entry (2 failed cycles → coin lock) | ✅ Expliciete `CoinCycleState`; live gevoed via close-PnL en gehandhaafd in admission-helper |
| **P6** | Item 9 | BucketExposureTracker (bucket-cap block) | 🟡 Alle entrypaden; blokkeert i.p.v. size-down |
| **P7** | Item 8 | Quality-based sizing (na score-systeem) | ✅ Alle entrypaden |
| **P8** | Item 15/16 | Session edge + coin ranking | ✅ Session edge alle entrypaden + persistente labels; MetaCoinRanker reordert `top_coins` |
| **P9** | Item 18 | Fill quality monitor | 🟡 Beperkte close-proxy, geen echte per-fill monitoring |
| **P10** | Item 5 (score) | Geaggregeerde 0–100 trade quality score | 🟡 Scorer alle entrypaden; inputs live behalve fakeout/slippage |
| **P11** | ST-06b | SQLite executor/fill basis + post-run analyse | ✅ Directe executor flush + initial/live snapshots + `post_run_sqlite_report.py` |

### Resterende backlog (nog niet geïmplementeerd)

| Item | Omschrijving | Prioriteit |
|------|-------------|-----------|
| Item 1/2/3 | ~~Close-PnL naar `risk_manager.register_close_trade()`~~ | ✅ KLAAR (2026-05-09) |
| Item 2 | ~~State machine (WIN_EXIT/LOSS_EXIT/2_FAILED) volledig~~ | ✅ KLAAR (2026-05-09) |
| ST-05a/ST-06a | ~~Funnel + selection trace eerste productieslice~~ | ✅ KLAAR (2026-05-09); run-over-run analyse later |
| ST-05b | ~~NO_PROGRESS_TIMEOUT soft unwind wiring~~ | ✅ KLAAR (2026-05-09); live verliesvalidatie later |
| ST-06b | ~~Executor/fill SQLite logging fix + basale post-run analyse~~ | ✅ KLAAR (2026-05-10); live snapshots + mismatch/error-classificatie toegevoegd; historische gaten blijven historisch |
| ST-07 | ~~Definitief BEAR-beleid kiezen~~ | ✅ KLAAR (2026-05-09): conditioneel BEAR-light |
| Item 13 | Gross daily turnover teller per coin | LAAG |
| Item 16 | ~~`MetaCoinRanker` echt gebruiken in coin selectie~~ | ✅ KLAAR (2026-05-09) |
| Item 19 | ~~`capital_reserve_pct` toepassen in allocatie/budget~~ | ✅ KLAAR (2026-05-09) |
| Item 20 | Monte Carlo tool koppelen aan persistente labels + runbook | LAAG (na 500+ trades) |
| Item 21 | Execution quality dashboard | LAAG |
| Cross-cutting | ~~Nieuwe gates ook toepassen in multi-coin vervolglus~~ | ✅ KLAAR (2026-05-09) |

---

## Kritische Observaties

**Wat ChatGPT goed zag:**
- Re-entry differentiation (P1) is de meest urgente gap — RAVE verlies was exact dit patroon
- Daily coin kill switch is qua helpers gebouwd, maar de echte gap is close-PnL wiring naar `GlobalRiskManager`
- Trade labeling (P4) is de investering die alles daarna goedkoper maakt

**Wat ChatGPT overdreef qua timing (maar correct van intentie):**
- Risk Buckets / Monte Carlo / Capital Reserve — **niet overkill**, wel fase-gebonden. Staged changes bevatten al delen hiervan; nu moet de wiring betrouwbaarder worden. Doelkapitaal is €25k+.
- "Stop Random Smallcap Trading" — al grotendeels afgedicht
- "Pre-Trade Risk Gateway" als groot project — al substantieel aanwezig

**Wat ontbreekt in de ChatGPT-lijst:**
- Pattern-aware cooldown (V2-05 in backlog) — specifiek voor herkennen van dalende markt ná entry
- ATR-kalibratie toepassen — calibrator registreert data, maar past grid-breedte nog niet automatisch aan
- Warmup guard versterking — bot kan handelen met onvolledige data
- Cross-path consistentie — nieuwe gates moeten ook draaien voor extra coins in multi-coin mode
