# Codex Pipeline Audit — Resultaten 25 mei 2026

> **Bron**: Codex (GitHub Copilot agent mode), read-only audit op basis van `FULL_PIPELINE_AUDIT_PROMPT.md`
> **Geen codewijzigingen gemaakt tijdens audit.**

---

## Top 10 Bevindingen

1. **`CoinSelector.filter_pairs()` niet actief in controller**
   `CoinSelector.filter_pairs()` bestaat met quote/blacklist/volume/spread-filtering (`multi_coin_grid_pro/logic/coin_selector.py:62-128`), maar de controller gebruikt bij actieve discovery een eigen pad (`multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:3368-3517`). Alleen initialisatie van `coin_selector_v2` (`multi_coin_grid_controller.py:690-706`), geen actieve `filter_pairs()` call.

2. **Grid suitability is post-filter, niet primaire ranking**
   `get_top_n_coins()` ondersteunt grid-ranking (`multi_coin_grid_pro/utils/trend_calculator.py:1750-1798`), maar de controller geeft geen `grid_scorer` mee (`multi_coin_grid_controller.py:4471-4478`) en filtert pas daarna de al gekozen `top_coins` (`multi_coin_grid_controller.py:4480-4489`).

3. **SmartEntry v2 actief, legacy guards niet bereikbaar** ⚠️ KRITIEK
   SmartEntry v2 is de actieve route, legacy alleen fallback (`multi_coin_grid_controller.py:8715-8721`). VWAP-slope en parabolic gates zijn daardoor **niet actief** in de normale flow, hoewel legacy ze implementeert (`multi_coin_grid_pro/filters/smart_entry_filter.py:454-476`) en v2 alleen gates 0–7 uitvoert (`multi_coin_grid_pro/logic/smart_entry.py:423-610`).

4. **VWAP slope guard passeert bij ontbrekende slope**
   In legacy: passeert bij ontbrekende 5m of 15m slope (`smart_entry_filter.py:599-608`). In v2: 15m slope wordt doorgegeven (`multi_coin_grid_controller.py:9186-9196`) maar niet gebruikt als gate in `logic/smart_entry.py`.

5. **ATR-selectie en SmartEntry gebruiken verschillende ATR-logica**
   Selectie gebruikt `_calculate_atr_pct()` en cached `trend.atr_pct` (`trend_calculator.py:1694-1698`). SmartEntry berekent ATR opnieuw via `CandleIndicatorsCalculator` (`multi_coin_grid_controller.py:9309-9313`). Die calculator eist `period + 1` closes (`candle_indicators.py:119-133`), terwijl trend-calculator al met 2 candles een ATR-achtig gemiddelde retourneert (`trend_calculator.py:1510-1526`).

6. **Candle-window comment vs `since_ms` inconsistentie**
   Comment zegt 60h/720 candles, `since_ms` haalt 30h terug (`trend_calculator.py:332-359`). Live updates houden wel maximaal 720 5m-candles bij (`trend_calculator.py:900-927`).

7. **ATR soft pre-filter strenger dan hard min gate**
   `prefilter_ratio: 0.50` in spot-configs (`spot_grid_kraken_usd.yaml:1188-1191`, `spot_grid_kraken_eur.yaml:993-996`, `spot_grid_okx.yaml:404-407`). Bij best-case maker 0.20% en multiplier 2.0: required ATR 0.80%, soft threshold 0.40% (`multi_coin_grid_controller.py:8807-8827`). Hard min vaak 0.03–0.15% afhankelijk van regime.

8. **ATR 70/30 ranking gebruikt `abs(tv)`**
   In `auto` kan een −8% trend dus boven +2% ranken (`trend_calculator.py:1808-1814`). In `long` niet, want threshold vereist positieve waarde (`trend_calculator.py:1719-1724`).

9. **Orders niet post-only — maker-fee aanname onjuist** ⚠️ KRITIEK
   Controller forceert `OrderType.LIMIT`, expliciet omdat Bitget geen `LIMIT_MAKER` ondersteunt (`multi_coin_grid_controller.py:10850-10869`). `best_case` maker-fee aannames in USD/EUR/OKX configs zijn daardoor optimistisch (`spot_grid_kraken_usd.yaml:1111-1114`, `spot_grid_kraken_eur.yaml:958-961`, `spot_grid_okx.yaml:344-349`).

10. **`session_blacklist` inconsistente timestamp-semantiek** ⚠️ HOOG
    `_add_to_blacklist()` slaat **expiry** op (`multi_coin_grid_controller.py:6735-6737`), maar selectie-cleanup behandelt dezelfde waarde als `blacklisted_at` (`multi_coin_grid_controller.py:4440-4464`).

---

## Risicomatrix

| Prio | Risico |
|------|--------|
| **Kritiek** | VWAP/parabolic guards live ingesteld, maar niet actief in v2-flow — kunnen niet blokkeren |
| **Kritiek** | Maker-fee/best-case config botst met `OrderType.LIMIT`; taker fills zijn mogelijk zonder fee-correctie |
| **Hoog** | Grid suitability mist kandidaten — filtert pas ná `top_n` trend/ATR-selectie |
| **Hoog** | `session_blacklist` expiry vs start-tijd verwarring — loopt langer of vreemd |
| **Hoog** | `max_streak_before_blacklist` logt alleen streaks; **geen actie** bij threshold (`multi_coin_grid_controller.py:7259-7268`) |
| Medium | HYPE-USD en SUI-USD expliciet uit blacklist gehaald (`spot_grid_kraken_usd.yaml:81`, `:88`) |
| Medium | EUR/OKX missen `take_profit_sec`; TP valt terug op rotation cooldown (`multi_coin_grid_controller.py:7197-7223`) |
| Medium | Bitget futures mist SmartEntry/ATR/fee keys; gebruikt defaults (`multi_coin_grid_config.py:774-790`, `:933-978`) |
| Medium | `[ENTRY_APPROVED]` bestaat niet; success is `"BUY ALLOWED"` (`logic/smart_entry.py:604-610`) |
| Medium | Spread zit in discovery, SmartEntry, ST-12 en momentum-score — geen consistent economisch model |

---

## Pipeline Status

| Stap | Status |
|------|--------|
| Discovery | Actief in controller direct, niet via `CoinSelector.filter_pairs()` |
| Trends/candles | Actief, 5m candles, max 720 live candles |
| `get_top_n_coins()` | Actief met exclusions, optional depth, ATR soft filter, trend threshold, ATR blend |
| Grid suitability | Actief als **post-filter**, niet als primaire universe ranking |
| SmartEntry | v2 actief; legacy alleen fallback. Staleness/orderbook preguards actief |
| Economic edge | Actieve ST-12 gate (`multi_coin_grid_controller.py:5070-5168`) |
| Execution | GridExecutor met `LIMIT`, niet `LIMIT_MAKER` |
| Momentum sleeve | Paper mode actief via controller: `maybe_enter()`, `update_positions()`, summary (`multi_coin_grid_controller.py:8941-9010`) |

---

## ATR Per Bot

| Bot | SmartEntry hard gate | Regime min ATR | ATR fee/selectie |
|-----|---------------------|---------------|-----------------|
| Kraken USD | min 0.15, max 7.0 (`spot_grid_kraken_usd.yaml:366-367`) | BULL 0.05, CHOP 0.06, BEAR 0.08 | required 0.80%, soft 0.40% (stale comments op `:1177-1190`) |
| Kraken EUR | min 0.15, max 7.0 (`spot_grid_kraken_eur.yaml:407-408`) | BULL 0.08, CHOP 0.10, BEAR 0.15 | global worst-case, connector override best-case |
| OKX | min 0.06, max 7.0 (`spot_grid_okx.yaml:447-448`) | BULL 0.03, CHOP 0.06, BEAR 0.08 | required 0.80%, soft 0.40% |
| Bitget futures | Geen SmartEntry/ATR config gevonden | n.v.t. | n.v.t. |

---

## Fees en Spacing

| Bot | `min_grid_level_spacing_pct` | Fee-realistisch bij taker? |
|-----|-----------------------------:|---------------------------|
| USD | 0.80 global en override | Net boven 2× taker 0.70%, krap zonder edge/slippage |
| EUR | 1.50 global, 0.80 override | Override is krapper dan comment/global |
| OKX | 0.60 | **Lager dan 2× taker 0.70% bij taker fills** |
| Bitget futures | Key ontbreekt; default 1.0 | Onzeker |

---

## Cooldowns en Blacklists

- **TAKE_PROFIT**: apart `take_profit_sec` als aanwezig (`multi_coin_grid_controller.py:7197-7211`)
- **STOP_LOSS / EARLY_STOP / NO_PROGRESS / FAILED**: `_get_close_cooldown_sec()` (`multi_coin_grid_controller.py:10222-10261`)
- **USD**: `take_profit_sec: 7200`, `max_streak_before_blacklist: 2` (`spot_grid_kraken_usd.yaml:1165-1172`)
- **EUR/OKX**: geen `take_profit_sec` — valt terug op rotation cooldown

Blacklist-lagen:
1. Config blacklist + connector override (`multi_coin_grid_config.py:885-896`)
2. Session/performance blacklist (`multi_coin_grid_controller.py:6724-6755`)
3. Auto-blacklist na 5 errors (`multi_coin_grid_controller.py:530-533`, `6138-6157`)
4. NL-restriction persistence (`multi_coin_grid_controller.py:6099-6118`)
5. Parabolic cooldown-store (`multi_coin_grid_controller.py:595-612`, `2014-2027`) — kan SQLite-persistent zijn

---

## Momentum Sleeve

| Config | `min_score_to_enter` | Spread threshold |
|--------|---------------------:|----------------:|
| Kraken USD | 55 | default |
| Kraken EUR | 55 | default |
| OKX | **25** | 0.15 |
| Bitget | 55 | default |

Scoring weights: 25/30/20/15/5/5 (`momentum_candidate_scorer.py:18-25`).
Paper manager logt `[MOMENTUM_PAPER_ENTRY]`, `[MOMENTUM_PAPER_EXIT]`, `[MOMENTUM_PAPER_SUMMARY]` (`momentum_sleeve_manager.py:86-147`, `197-220`, `251-309`).

---

## Aanbevelingen

1. Maak één expliciete discovery-flow: gebruik `CoinSelector.filter_pairs()` echt, of verwijder het uit het schema
2. Wire grid suitability als ranking over ruimer universum (`n × 3`), of geef `grid_scorer` direct mee aan `get_top_n_coins()`
3. **Port VWAP slope en parabolic gates naar SmartEntry v2** of schakel v2 uit waar legacy live-guards bedoeld zijn
4. **Harmoniseer ATR**: één calculator, minimaal 15 candles voor ATR(14), expliciete candle-staleness
5. **Kies fee-model op basis van echte order semantics**: post-only/LIMIT_MAKER per connector, of `average/worst_case` waar LIMIT taker kan fillen
6. **Fix `session_blacklist`**: één betekenis overal — óf expiry timestamp, óf start timestamp
7. **Implementeer echte actie bij `max_streak_before_blacklist`**, niet alleen logging
8. Maak grid-only blacklist en momentum-only universe apart (HYPE/SUI)
9. Voeg `take_profit_sec` toe aan EUR/OKX of documenteer rotation fallback
10. Maak Bitget futures expliciet: SmartEntry/ATR/fee disabled by design, of volledig configureren

---

## Ontbrekende Tests

1. Controller-test dat `grid_scorer` full-universe ranking krijgt, niet alleen post-filtert
2. SmartEntry v2 test voor VWAP slope en parabolic live reject
3. ATR soft pre-filter test met 14 vs 15 candles en threshold `required × prefilter_ratio`
4. Session blacklist expiry-regressietest voor `_add_to_blacklist()` plus selectie-cleanup
5. Loss-streak test: tweede verlies bij `max_streak_before_blacklist: 2` escaleert naar blacklist/cooldown

**Bestaande dekking:**
- Cooldown mapping: `test_multi_coin_grid_controller_extended.py:474-560`
- ATR fee gate: `test_multi_coin_grid_controller_extended.py:566-599`
- Grid-ranking helper: `test_grid_ranking.py:123-178`
- Controller-wiring en ATR blend 70/30: **niet gedekt**

---

## Live-Run Analyse

```bash
# Log grep
rg "\[COIN_SELECTION_ATR_SUMMARY\]|\[ENTRY_REJECTED\]|\[SMART_ENTRY_REJECT\]|\[HOURLY_REJECT_SUMMARY\]|\[MOMENTUM_PAPER_(ENTRY|EXIT|SUMMARY)\]|BLACKLIST_|LOSS_STREAK|ST-12 EDGE GATE" logs/

# Cooldown databases
sqlite3 data/cooldowns_usd.db "select connector,symbol,reason,datetime(expires_at,'unixepoch') from symbol_cooldowns order by expires_at;"
sqlite3 data/cooldowns_eur.db "select connector,symbol,reason,datetime(expires_at,'unixepoch') from symbol_cooldowns order by expires_at;"
```

---

## Top-3 Implementatie (volgende sessie)

```text
Voer alleen implementatie uit voor de top-3 auditbevindingen:
1. Port VWAP slope guard en parabolic detector naar SmartEntry v2, inclusief live/shadow gedrag en tests.
2. Fix grid suitability zodat de controller full-universe of n×3 kandidaten rankt/filtert in plaats van alleen top_n post-filter.
3. Harmoniseer ATR berekening tussen selectie en SmartEntry: minimaal 15 candles, één calculator, tests voor soft pre-filter en hard gate.

Geen unrelated refactors. Citeer gewijzigde bestanden, draai relevante unit tests met:
    source ~/.venvs/bot/bin/activate
```
