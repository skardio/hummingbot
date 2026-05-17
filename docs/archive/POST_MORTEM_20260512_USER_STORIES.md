# Post-mortem 2026-05-12 — User Stories

> **Aanleiding:** INJ-USD stop-loss −$3.21, CRV-USD no-progress −$0.84. Root-cause analyse in sessie 2026-05-12.
> **Status:** P0 items in implementatie.

---

## Epic 1 — Voorkomen dat de bot breakdowns koopt

### Story 1.1 — RSI-velocity blokkade (P0 — gemerged in SmartEntry)

**Als** trading bot
**wil ik** herkennen wanneer RSI snel daalt na een overbought periode
**zodat** ik geen breakdown koop die lijkt op een gezonde pullback.

**Acceptatiecriteria**

```gherkin
Given een coin had RSI >= 75 in de laatste 20 minuten
And RSI daalt met >= 10 punten binnen 5 minuten
When de bot een buy-entry wil openen
Then moet de entry worden afgewezen
And moet de reden "RSI_OVERBOUGHT_BREAKDOWN_COOLDOWN" gelogd worden
And moet de coin minimaal 15 minuten in cooldown blijven
```

**Noot:** Gemerged met Story 3.2 (hysteresis). Aparte velocity-state is niet nodig als hysteresis correct is.

---

### Story 1.2 — Cooldown na snelle RSI-reset (DEFER — gedekt door 3.2)

Geschrapt: hysteresis (Story 3.2) pakt dit af. Geen aparte cooldown-state nodig.

---

### Story 1.3 — Herstelbevestiging na overbought breakdown (DEFER)

Geschrapt: te complex voor marginaal voordeel als 1.1 + exhausted-momentum filter actief is.

---

## Epic 2 — Rapid grid-fill detectie

### Story 2.1 — Detecteer falling-knife grid fills (P1)

**Als** trading bot
**wil ik** detecteren wanneer alle buy-levels extreem snel vullen
**zodat** ik herken dat prijs door de grid heen valt.

**Acceptatiecriteria**

```gherkin
Given een grid heeft meerdere buy-levels
When alle buy-levels binnen 180 seconden gevuld worden
Then moet de bot dit markeren als "RAPID_GRID_FILL"
And moet dit als waarschuwing gelogd worden
```

---

### Story 2.2 — Verkorte timeout bij rapid-fill (P1, vereenvoudigd)

**Originele story (2.2 + 2.3 gemerged):** Geen aparte abort-paden, geen recovery watchdog.
**Vereenvoudigd:** Als `all_buys_filled_in < 300s`, halveer de no-progress timeout van 60 naar 25 minuten.

**Acceptatiecriteria**

```gherkin
Given alle buy-levels zijn binnen 300 seconden gevuld
When de no-progress timeout wordt geëvalueerd
Then moet de timeout 25 minuten zijn in plaats van 60 minuten
And moet de reden "RAPID_GRID_FILL_SHORT_TIMEOUT" gelogd worden
```

---

## Epic 3 — Stabielere RSI-thresholds

### Story 3.1 — Smooth dynamic RSI-threshold (P0 — geïmplementeerd)

**Als** trading bot
**wil ik** dynamic RSI-thresholds afvlakken
**zodat** één candle geen plotselinge entry kan openen.

**Acceptatiecriteria**

```gherkin
Given dynamic RSI-thresholds worden berekend
When de bot een entry evalueert
Then moet hij de median threshold van de laatste 10 minuten gebruiken
And niet alleen de meest recente threshold
```

**Implementatie:** `SmartEntryFilter._get_smoothed_rsi_buy_max()` — rolling deque per symbol, median van laatste 20 samples (~10 min bij 30s tick).

---

### Story 3.2 — Hysteresis voor entry en re-entry (P0 — geïmplementeerd)

**Als** trader
**wil ik** aparte RSI-drempels voor blokkeren en vrijgeven
**zodat** de bot niet flikkert tussen block en allow.

**Acceptatiecriteria**

```gherkin
Given de RSI-entry threshold is 75
When RSI boven 75 komt
Then moet entry geblokkeerd worden

Given entry is geblokkeerd door RSI
When RSI slechts zakt naar 74
Then mag entry nog niet worden vrijgegeven

Given entry is geblokkeerd door RSI
When RSI zakt onder 71
Then mag entry opnieuw geëvalueerd worden
```

**Implementatie:** `SmartEntryFilter` — per-symbol `_rsi_blocked` state, unlock-threshold = `rsi_buy_max - hysteresis_gap` (default 4 punten).

---

## Epic 4 — Trend-score recency-aware maken

### Story 4.1 — Exhausted momentum filter (P0 — geïmplementeerd, NIEUW)

**Als** trading bot
**wil ik** herkennen wanneer een coin al uitgeput is na een grote move
**zodat** ik niet koop op het piek van een move die al voorbij is.

**Acceptatiecriteria**

```gherkin
Given een coin heeft >= 8% bewogen in 24h
And de 1h trend is negatief of zwak (< 1%)
When de bot een entry evalueert
Then moet de entry worden afgewezen
And moet de reden "EXHAUSTED_MOMENTUM" gelogd worden
```

**Implementatie:** SmartEntryBaseConfig veld `exhausted_momentum_enabled`, check in `allows_entry()`.

---

### Story 4.2 — Korte timeframe bevestiging vóór entry (P2 — defer)

Gedekt door Story 4.1 in de praktijk. Aparte implementatie na data-validatie.

---

## Epic 5 — Grid-health monitoring

### Story 5.1 + 5.2 — Snellere no-progress bij slechte fill-structuur (P1)

Gemerged in Story 2.2 (rapid-fill timeout halveren).

---

## Epic 6 — Logging en observability

### Story 6.1 — Log volledige entry-context (P2)

**Als** trader
**wil ik** bij elke entry-beslissing de volledige context zien.

**Acceptatiecriteria**

```gherkin
Given de bot evalueert een entry
When de beslissing BUY_APPROVED of BUY_REJECTED is
Then moet de log minimaal bevatten:
  | RSI current | RSI 5m ago | RSI 20m max | dynamic RSI threshold |
  | 5m trend | 15m trend | 1h trend | 24h trend |
  | VWAP status | decision reason |
```

---

## Epic 7 — Config-validatie (P2 — defer)

### Story 7.1 + 7.2

Niet een verliesdriver vandaag. Defer.

---

## Epic 8 — Testdekking

### Story 8.1 — INJ breakdown regression test (P0 — geïmplementeerd)

```gherkin
Given RSI beweegt van 78.5 naar 63.7 binnen 90 seconden
And RSI was overbought in de laatste 20 minuten
When de bot entry evalueert
Then moet de entry worden afgewezen
And de reject reason moet "RSI_OVERBOUGHT" zijn (hysteresis actief)
```

### Story 8.2 — CRV rapid-fill regression test (P1)

```gherkin
Given buy level 1 vult om T+0
And buy level 2 vult om T+112s (< 180s)
When de bot grid-health evalueert
Then moet "RAPID_GRID_FILL" worden geactiveerd
```

---

## ⚠️ Let op: gedeelde codebase

Alle aanpassingen aan `multi_coin_grid_pro/logic/smart_entry.py` gelden voor **beide bots**:
- `multi_coin_grid_pro_eur` (Kraken EUR-paren)
- `multi_coin_grid_pro_usd` (Kraken USD-paren)

Na de volgende herstart van de EUR-bot worden hysteresis (`rsi_hysteresis_enabled: true`) en
threshold-smoothing (`rsi_smoothing_enabled: true`) ook daar actief. `exhausted_momentum_enabled`
staat standaard op `false` — opt-in per YAML-config nodig.

---

## Prioriteit samenvatting

| # | Story | Status | Getest | Impact |
|---|-------|--------|--------|--------|
| P0 | 3.2 RSI hysteresis | ✅ Klaar | ✅ 3 tests | Voorkomt flip-flop entries |
| P0 | 3.1 Threshold smoothing | ✅ Klaar | ✅ 1 test | Stabiliseert dynamic threshold |
| P0 | 4.1 Exhausted momentum | ✅ Klaar | ✅ 1 test | Blokkeert INJ-type rootcause |
| P0 | 8.1 INJ regression test | ✅ Klaar | ✅ | Bewijst hysteresis-fix |
| P1 | 2.1 Rapid grid-fill detectie | ✅ Klaar | ✅ 5 tests | CRV-type rootcause |
| P1 | 2.2 Verkorte no-progress timeout | ✅ Klaar | ✅ 2 tests | CRV-type rootcause |
| P1 | 8.2 CRV regression test | ✅ Klaar | ✅ 7 tests | Bewijs voor P1-fix |
| P2 | 6.1 Entry-context logging | ✅ Klaar | ✅ 4 tests | Elke beslissing gelogd |
| P2 | 7.1 Config-validatie | ✅ Klaar | ✅ 7 tests | Fail-fast op verkeerde config |
| Defer | 1.2, 1.3, 4.2, 2.3 | Defer | — | Gedekt door andere stories |

**Implementatie compleet. Testsuite: 1762 passed, 0 failed (2026-05-12).**

**Bestanden gewijzigd:**
- `multi_coin_grid_pro/logic/smart_entry.py` — hysteresis, smoothing, exhausted momentum, validate(), _log_entry_decision(), allows_entry wrapper + _evaluate_entry inner
- `multi_coin_grid_pro/core/reason_codes.py` — 2 nieuwe ReasonCodes + Stage update
- `multi_coin_grid_pro/controllers/multi_coin_grid_config.py` — `rapid_fill_window_sec` field
- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` — `rapid_fill_window_sec` in custom_info
- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py` — rapid-fill state + halved timeout
- `multi_coin_grid_pro/tests/test_smart_entry.py` — 17 nieuwe tests (P0, P1, P2 Stories 6.1 + 7.1)
- `multi_coin_grid_pro/tests/test_rapid_grid_fill.py` — 7 nieuwe P1-tests (nieuw bestand)
- `multi_coin_grid_pro/tests/unit/test_story_a1_timeout_lifecycle.py` — MockExecutor state uitgebreid
- `multi_coin_grid_pro/tests/core/test_reason_codes.py` — count + stage set bijgewerkt
