# Review: ChatGPT "Professionele Quant" Backlog vs. Werkelijkheid

> Gegenereerd: 2026-04-26 | Gebaseerd op: `000_The_masterPlan.md` (27 items)
> Doel: kritisch doorlichten wat al bestaat, wat ontbreekt, wat overdreven is
> **Gecontroleerd: 2026-04-28** - staged changes nagelopen tegen controller-code. Eerdere "gebouwd + ingehangen" claims waren te optimistisch: meerdere modules bestaan, maar zijn niet volledig end-to-end actief.

---

## Samenvatting

| Status | Aantal | Correctie na staged-code audit |
|--------|--------|-------------------------------|
| ✅ Aantoonbaar actief in productiepad | 7 | Vooral bestaande risk/liquidity/regime checks + Dynamic TP |
| 🟡 Module aanwezig of primair pad deels aangesloten | 12 | Let op: multi-coin vervolglus mist veel nieuwe gates |
| ❌ Niet geïmplementeerd of niet aangesloten | 4 | Item 13 gross turnover, item 16 ranker-hook, item 21 dashboard, plus delen van item 2 |
| 🗑️ Schrappen / niet prioriteit | 4 | Ongewijzigd |

## Audit 2026-04-28 — Claims "gebouwd" vs. staged werkelijkheid

| Item | Claim in dit document | Werkelijkheid in staged changes |
|------|-----------------------|---------------------------------|
| Item 1 | Gebouwd + controller | 🟡 `EntryGateway` is er en draait in het primaire entrypad, maar de multi-coin vervolglus gebruikt hem niet. Exit-type cooldown bestaat, maar closed-trade PnL wordt niet via `risk_manager.register_close_trade()` gevoed. |
| Item 3 | Daily kill switch klaar | 🟡 Logic en pre-entry checks bestaan, maar controller registreert gerealiseerde PnL niet in `GlobalRiskManager`; daardoor blijven per-coin -1R/-2R checks in live pad leeg. |
| Item 5 | Volledig scoremodel | 🟡 Scorer bestaat en draait in primair entrypad, maar geen fakeout/slippage component. `depth_multiple=1.0` en `btc_1h_pct=0.0` zijn hard-coded. |
| Item 6 | ATR calibrator actief | 🟡 Calibrator registreert ATR en logt suggesties; hij past grid multipliers nog niet automatisch toe. |
| Item 8 | Quality sizing actief | 🟡 Actief in primair entrypad. Niet in multi-coin vervolglus; bucket-check gebeurt bovendien vóór quality-upsize. |
| Item 9/10 | Bucket exposure actief | 🟡 Bucket tracker bestaat en werkt in primair pad, maar multi-coin vervolglus doet geen `can_add()`. Dit is bucket-blocking, geen size-down. |
| Item 13 | Gebouwd | ❌ Gross daily turnover per coin is niet gebouwd. Alleen bucket-exposure bestaat. |
| Item 14 | Trade labeling volledig | 🟡 In-memory labels worden toegevoegd bij close, maar `TradeLabelStore` wordt niet gebruikt en meerdere velden zijn placeholders (`timestamp_open`, regime, MFE/MAE, cycle). |
| Item 15/17 | Session edge / coin-session block | 🟡 SessionEdgeDetector is actief in primair entrypad en filtert per coin, maar gebruikt alleen in-memory labels en draait niet in de multi-coin vervolglus. |
| Item 16 | Meta ranking ingehangen | ❌ `MetaCoinRanker` is alleen geïnstantieerd; controller roept `.rank()` / `.get_preferred_coins()` nergens aan. |
| Item 18 | Fill monitor volledig | 🟡 Monitor bestaat, maar controller registreert één synthetische close-sample met config start/end price, niet elke echte fill. |
| Item 19 | Reserve architectuur | 🟡 Config en helper bestaan, maar controller gebruikt `capital_reserve_pct` / `get_deployable_balance()` niet. |
| Item 20 | Niet geïmplementeerd | 🟡 Monte Carlo tool + tests bestaan in staged changes; nog geen operationele runbook/data-koppeling. |

---

## ✅ Al Geïmplementeerd — Niet opnieuw bouwen

### Item 4 — Hard Pre-Trade Risk Gateway
**Status: GROTENDEELS KLAAR**
- `GlobalRiskManager.can_open_trade()` blokkeert op: max exposure, exit cooldown, switch cooldown
- `SmartEntryFilter` controleert: spread, orderboekdiepte, RSI, regime
- `MarketRegimeFilter` blokkeert bij BTC dump
- `EntryGateway` is toegevoegd voor het primaire entrypad
- ❗ Niet één centraal entry point: de multi-coin vervolglus omzeilt de nieuwe gateway nog

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
**Wat er nieuw is:** `EntryGateway` (`core/entry_gateway.py`) gebouwd en in het primaire entrypad gehangen. `ExitType` + per-type cooldown bestaat in `GlobalRiskManager`.
**Wat ontbreekt:** niet alle entrypaden gebruiken `EntryGateway`; de multi-coin vervolglus omzeilt hem. De close-PnL route roept `risk_manager.register_close_trade()` niet aan, waardoor exit-type cooldown, failed-cycle state en daily coin PnL niet volledig end-to-end gevoed worden.
**Status: GEDEELTELIJK GEÏMPLEMENTEERD**

### Item 2 — State-Aware Re-entry Machine
**Wat er is:** basisachtige exit-tracking via `_last_exit_time` en `note_exit()`.
**Wat er nieuw is:** `GlobalRiskManager` heeft helpers voor failed-cycle count en lock na 2 losses.
**Wat ontbreekt:** geen expliciete state machine (WIN_EXIT / LOSS_EXIT / 2_FAILED_CYCLES). In controller wordt close-PnL niet naar `register_close_trade()` gestuurd, dus de failed-cycle lock wordt in live close-pad niet betrouwbaar gevuld.
**Echte gap:** medium — state-model en close-wiring ontbreken.

### Item 3 — Daily Coin Kill Switch
**Wat er is:** `GlobalRiskManager` tracks per-coin gerealiseerde PnL.
**Wat er nieuw is:** -1R halve size en -2R hard block bestaan als helpers en primaire pre-entry checks.
**Wat ontbreekt:** gerealiseerde close-PnL wordt niet naar `GlobalRiskManager` gevoed in de controller. Daardoor is de live per-coin teller leeg, tenzij een andere caller expliciet `record_coin_pnl()` of `register_close_trade()` aanroept.
**Status: GEDEELTELIJK / BUG IN WIRING**

### Item 5 — Trade Quality Filter (scoremodel)
**Status: GEDEELTELIJK GEBOUWD + PRIMAIR PAD INGEHANGEN (2026-04-26)**
- `TradeQualityScorer` (`scoring/trade_quality_scorer.py`) geeft 0–100 score op: regime, RSI, spread, diepte, volatiliteit, BTC-trend
- `quality_size_multiplier()` converteert score naar positie-multiplier (0.5x–1.25x)
- Ingehangen vóór `_create_grid_action()` in het primaire entrypad — score opgeslagen als `self._quality_score`
- ❗ Geen fakeout/slippage component. In controller zijn `rsi=50.0`, `depth_multiple=1.0` en `btc_1h_pct=0.0` hard-coded.

### Item 9 — Inventory-Aware Sizing
**Status: GEDEELTELIJK GEBOUWD + PRIMAIR PAD INGEHANGEN (2026-04-26)**
- `BucketExposureTracker` (`core/risk_buckets.py`) groepeert coins in bucket-categorieën (meme/L1/altcoin/stablecoin)
- `can_add(coin, notional)` blokkeert als bucket-cap bereikt is
- Ingehangen vóór `_create_grid_action()` in het primaire entrypad — blokkeert entry als bucket vol is
- ❗ Geen size-down bij bucket-cap; alleen block. Multi-coin vervolglus doet geen `can_add()` en quality-upsize gebeurt na de bucket-check.

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
**Status: GEDEELTELIJK GEBOUWD + PRIMAIR PAD INGEHANGEN (2026-04-26)**
- `quality_size_multiplier(score, halved)` in `scoring/trade_quality_scorer.py`
- Score <40 → 0.5x, 40-60 → 0.75x, 60-80 → 1.0x, >=80 → 1.25x
- Ingehangen na entry gateway, vóór `_create_grid_action()` in primair entrypad
- ❗ Niet toegepast in de multi-coin vervolglus

### Item 14 — Learn From Logs Engine (trade labeling)
**Status: GEDEELTELIJK GEBOUWD + IN-MEMORY INGEHANGEN (2026-04-26)**
- `TradeLabel` dataclass + `TradeLabelStore` bestaan
- Controller vult een in-memory buffer `self._trade_labels` (max 500) bij terminated executors
- ❗ `TradeLabelStore` wordt niet geïnitialiseerd of aangeroepen door de controller
- ❗ Meerdere velden zijn placeholders: `timestamp_open=_now_ts-3600`, `regime=""`, `depth_at_entry=0.0`, `mfe_pct=0.0`, `mae_pct=0.0`, `cycle_number=1`

### Item 15 — Session Edge Detection
**Status: GEDEELTELIJK GEBOUWD + PRIMAIR PAD INGEHANGEN (2026-04-26)**
- `SessionEdgeDetector` (`core/session_edge_detector.py`) analyseert TradeLabel history per sessie (Asia/EU/US/weekend)
- `session_from_utc()` bepaalt huidige sessie
- Ingehangen vóór `_create_grid_action()` in primair entrypad — blokkeert entry als sessie historisch slecht presteert voor die coin
- ❗ Gebruikt alleen in-memory labels van de huidige runtime en draait niet in de multi-coin vervolglus

### Item 16 — Meta Ranking Engine
**Status: MODULE GEBOUWD, NIET INGEHANGEN (2026-04-28)**
- `MetaCoinRanker` (`core/meta_coin_ranker.py`) rankt coins op historische PnL + win rate uit TradeLabel buffer
- `.rank(labels)` geeft gesorteerde lijst terug
- ❌ Controller instantieert `self.meta_ranker`, maar roept `.rank()` / `.get_preferred_coins()` nergens aan. Coin selectie gebruikt ranking dus nog niet.

### Item 17 — Session + Coin Auto Block
**Gap:** geen `coin × sessie` combinatie tracking.
**Prioriteit:** LAAG — vereist data van item 15 first.
**Update (2026-04-28):** SessionEdgeDetector filtert per coin en sessie in primair entrypad. Nog niet persistent en niet in multi-coin vervolglus.

### Item 18 — Fill Quality Monitor
**Status: MODULE GEBOUWD + BEPERKT INGEHANGEN (2026-04-26)**
- `FillQualityMonitor` (`core/fill_quality_monitor.py`) vergelijkt expected vs actual fill price
- `record_fill(*, symbol, expected_price, actual_price, side, size_quote, timestamp)` wordt bij terminated executor aangeroepen als start/end price beschikbaar is
- `.avg_slippage_pct()` en `.summary()` beschikbaar voor analyse
- ❗ Niet elke echte fill wordt geregistreerd; controller gebruikt config start/end price als proxy, niet werkelijke fill-prijzen

### Item 19 — Capital Efficiency Layer
**Gap:** `capital_reserve_pct` config en `GlobalRiskManager.get_deployable_balance()` bestaan, maar controller gebruikt ze niet in allocatie.
**Prioriteit:** LAAG — pas relevant bij échte opportunity-kosten.

### Item 20 — Monte Carlo Risk Test
**Status: TOOL GEBOUWD, NOG NIET OPERATIONEEL IN PROCES**
- `multi_coin_grid_pro/tools/monte_carlo.py` + unit tests bestaan in staged changes
- Restgap: geen runbook, geen automatische koppeling aan trade-label database, geen periodieke rapportage
**Prioriteit:** LAAG — research/backtesting tool, niet productiepad.

### Item 21 — Execution Quality Dashboard
**Gap:** geen unified dashboard. Alles verspreid over logs.
**Prioriteit:** LAAG — operationeel comfort, geen direct PnL impact.

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
**Wat te doen nu:** maak de bucket-check consistent in alle entrypaden, check opnieuw na quality sizing, en beslis of bucket-cap moet blokkeren of size reduceren. Integratie in `GlobalRiskManager` is nog niet gedaan.

### Item 19 — Capital Efficiency Reserve
**Fase:** Activeren bij >€10k
Bij hogere kapitaalschalen is permanent volledig deployed zijn suboptimaal — betere setups komen terwijl je vastzit in middelmatige trades.
**Wat te doen nu:** `capital_reserve_pct` bestaat al; pas hem toe in de allocatieberekening (`available_balance` / `DynamicSlotManager`) en test dat budget allocator dezelfde deployable balance gebruikt.

### Item 20 — Monte Carlo Risk Test
**Fase:** Uitvoeren na 500+ trades (genoeg historische data)
Bij €25k wil je weten of het systeem een drawdown-reeks van 10 losers overleeft zonder margin call. Zonder dit is schalen blind vertrouwen.
**Wat te doen nu:** tool bestaat; maak trade-label persistence echt en voeg een runbook/command toe voor periodieke analyse.

---

## Prioriteitenlijst voor Implementatie

> Gesorteerd op PnL-impact × uitvoerbaarheid. Niet op ChatGPT-nummering.
> **Gecontroleerd 2026-04-28** — meerdere P-items hebben alleen module- of primair-pad dekking. Zie statuskolom.

| Prio | Item | Omschrijving | Status |
|------|------|-------------|--------|
| **P1** | Item 1 (gap) | Exit-type differentiatie in cooldown (TP=15m, SL=4h, trend=block) | 🟡 Module + primair EntryGateway-pad; close-PnL en multi-coin pad missen |
| **P2** | Item 3 | Daily coin kill switch (-1R halve size, -2R block) | 🟡 Logic + pre-entry check; gerealiseerde PnL wordt niet gevoed |
| **P3** | Item 7 | Dynamic TP (bounce-strength scale-out) | ✅ Dynamic TP actief; geen scale-out |
| **P4** | Item 14 | Trade labeling (regime, spread, reentry, MFE/MAE → in-memory buffer) | 🟡 In-memory basis; store en echte contextvelden missen |
| **P5** | Item 2 | State-aware re-entry (2 failed cycles → coin lock) | 🟡 Helpers bestaan; geen volledige state machine en niet live gevoed |
| **P6** | Item 9 | BucketExposureTracker (bucket-cap block) | 🟡 Primair pad; blokkeert i.p.v. size-down; multi-coin pad mist check |
| **P7** | Item 8 | Quality-based sizing (na score-systeem) | 🟡 Actief in primair pad; niet in multi-coin pad |
| **P8** | Item 15/16 | Session edge + coin ranking | 🟡 Session edge primair pad; ❌ ranker niet gebruikt |
| **P9** | Item 18 | Fill quality monitor | 🟡 Beperkte close-proxy, geen echte per-fill monitoring |
| **P10** | Item 5 (score) | Geaggregeerde 0–100 trade quality score | 🟡 Scorer actief primair pad; inputs deels hard-coded |

### Resterende backlog (nog niet geïmplementeerd)

| Item | Omschrijving | Prioriteit |
|------|-------------|-----------|
| Item 1/2/3 | Close-PnL naar `risk_manager.register_close_trade()` sturen zodat cooldowns, failed cycles en daily coin kill switch live data krijgen | HOOG |
| Item 2 | State machine (WIN_EXIT/LOSS_EXIT/2_FAILED) volledig | MEDIUM |
| Item 13 | Gross daily turnover teller per coin | LAAG |
| Item 16 | `MetaCoinRanker` echt gebruiken in coin selectie | MEDIUM |
| Item 19 | `capital_reserve_pct` toepassen in allocatie/budget | LAAG |
| Item 20 | Monte Carlo tool koppelen aan persistente labels + runbook | LAAG (na 500+ trades) |
| Item 21 | Execution quality dashboard | LAAG |
| Cross-cutting | Nieuwe gates ook toepassen in multi-coin vervolglus | HOOG |

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
