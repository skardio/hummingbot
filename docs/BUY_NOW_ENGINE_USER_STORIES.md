# Buy Now Engine — User Stories

**Product Owner:** Mo
**Status:** Sprint 1 gedeeltelijk geïmplementeerd
**Gebaseerd op:** Momentum Signal Service review (2026-06-04)

---

## Achtergrond

De huidige Momentum Signal Service stuurt meldingen over crypto-moves die
gemiddeld 10–15 minuten oud zijn op het moment van ontvangst. Daardoor is
handmatig instappen op het signaal meestal niet rendabel na fees en spread.

Dit document beschrijft wat er gebouwd moet worden zodat de meldingen
bruikbaar zijn voor handmatig instappen.

---

## Epics

| # | Epic | Doel |
|---|---|---|
| E1 | Betere data | Kortere tijdframes en liquiditeitsdata beschikbaar maken |
| E2 | Betere beslissing | Signaal classificeren als WATCH / BUY_NOW / TOO_LATE |
| E3 | Beter Telegram-bericht | Concreet handelsplan meesturen |
| E4 | Outcome tracking | Meten of signalen daadwerkelijk werken |
| E5 | Analyse | Inzicht in wat werkt en wat niet |

---

## E1 — Betere data

---

### ✅ US-101 — Δ3m beschikbaar als indicator

**Als** ontvanger van een koopsignaal
**wil ik** de prijsverandering van de laatste 3 minuten zien
**zodat ik** kan beoordelen of de move nu nog actief is (en niet 10 minuten geleden begon)

**Acceptatiecriteria:**
- `price_change_3m_pct` wordt berekend uit de 1m-candles die al opgehaald worden
- Het veld is beschikbaar in de database (`signals` tabel)
- Als er minder dan 4 candles zijn, is de waarde `null` (niet 0)
- De berekening is identiek aan de bestaande `price_change_5m_pct` logica

**Notities:**
- Geen extra API-call nodig — data is al aanwezig
- 1 regel code in `momentum_indicators.py`

---

### ✅ US-102 — Acceleration score beschikbaar als indicator

**Als** ontvanger van een koopsignaal
**wil ik** weten of de move van de afgelopen minuten versnelt of afvlakt
**zodat ik** geen signaal ontvang over een move die al uitgeput is

**Acceptatiecriteria:**
- Een `acceleration_score` wordt berekend per candidate (waarde 0.0 – 1.0)
- Definitie:
  - `1.0` als Δ1m ≥ 0.25% én Δ3m ≥ 0.7% én Δ5m ≥ 1.2% (move versnelt)
  - `0.7` als Δ3m ≥ 0.7% én Δ5m ≥ 1.2% (move stabiel)
  - `0.4` als alleen Δ5m ≥ 1.2% (move vlakt af)
  - `0.0` anders
- Het veld is opgeslagen in de database
- Als één van de vereiste deltas `null` is, is de score `0.0`

---

### ✅ US-103 — Slippage schatting beschikbaar als indicator

**Als** ontvanger van een koopsignaal
**wil ik** weten hoeveel ik kwijt ben aan slippage als ik markt koop
**zodat ik** signalen op dunne orderbooks niet opvolg

**Acceptatiecriteria:**
- `slippage_100eur` — geschatte slippage (%) voor een marktorder van €100
- `slippage_250eur` — geschatte slippage (%) voor een marktorder van €250
- Berekening op basis van het bestaande orderbook dat al opgehaald wordt
- Als er geen orderbook beschikbaar is, zijn beide waarden `null`
- Beide velden zijn opgeslagen in de database

**Notities:**
- Orderbook wordt al opgehaald — dit is alleen een berekening, geen nieuwe API-call
- Voor exchanges zonder EUR-denominatie: omrekening via prijs × hoeveelheid

---

### ✅ US-104 — Stale signaal onderdrukking (deduplicatie)

**Als** ontvanger van koopsignalen
**wil ik** geen herhaald signaal voor hetzelfde pair binnen 20 minuten ontvangen
**zodat ik** niet meerdere meldingen krijg over dezelfde move

**Acceptatiecriteria:**
- Na een `BUY_NOW` of `WATCH` signaal voor pair X wordt gedurende 20 minuten geen nieuw signaal gestuurd voor pair X op dezelfde exchange
- Uitzondering: als de prijs minstens 1.5% is gedaald t.o.v. het vorige signaal, mag een nieuw signaal gestuurd worden (nieuwe kans)
- De onderdrukking geldt alleen voor Telegram-meldingen — de database blijft alle scans opslaan
- De cooldown-status is in-memory (niet persistent over service-restarts)

**Notities:**
- Dit lost het probleem op van 49 identieke SAGA-EUR meldingen in 71 minuten

---

## E2 — Betere beslissing

---

### ✅ US-201 — Signaal classificatie: WATCH / BUY_NOW / TOO_LATE

**Als** ontvanger van een koopsignaal
**wil ik** direct weten of ik nu moet handelen, afwachten, of het te laat is
**zodat ik** geen tijd verlies aan beoordelen

**Acceptatiecriteria:**
- Elk geaccepteerd signaal krijgt één van drie labels:
  - `BUY_NOW` — instapmoment nu, actie vereist
  - `WATCH` — momentum begint, nog niet sterk genoeg om in te stappen
  - `TOO_LATE` — momentum bevestigd maar instap-risico te hoog
- `BUY_NOW` en `WATCH` signalen worden via Telegram verstuurd (elk met eigen opmaak)
- `TOO_LATE` wordt opgeslagen in de database maar niet naar Telegram gestuurd
- Het label is opgeslagen als kolom in de `signals` tabel

---

### ✅ US-202 — Buy Now Scorer vervangt huidige scorer

**Als** systeem
**wil ik** een scorer die gebaseerd is op wat beschikbaar is in de REST-service
**zodat ik** geen 55% van de score structureel op nul laat staan

**Acceptatiecriteria:**
- Nieuwe scorer met gewichten gebaseerd op beschikbare data:
  - `short_momentum` (Δ3m + Δ5m): gewicht 30%
  - `acceleration`: gewicht 25%
  - `volume_spike` (VolR): gewicht 20%
  - `liquidity` (spread + slippage): gewicht 15%
  - `risk` (lateness + spike): gewicht 10%
- Drempelwaarden:
  - `WATCH`: score ≥ 0.55
  - `BUY_NOW`: score ≥ 0.72
- Score is altijd berekend op basis van gevulde data; geen component die structureel altijd 0 is
- De oude scorer blijft beschikbaar maar wordt niet meer gebruikt voor classificatie

**Notities:**
- De exacte drempelwaarden (0.55 / 0.72) zijn startpunten en worden bijgesteld na outcome data

---

### ✅ US-203 — "Too late" filter op basis van move-uitputting

**Als** systeem
**wil ik** signalen onderdrukken als de move duidelijk uitgeput is
**zodat ik** geen `BUY_NOW` stuur terwijl de koper exit-liquidity wordt

**Acceptatiecriteria:**
- Een signaal krijgt label `TOO_LATE` (niet `BUY_NOW`) als aan één van deze condities voldaan is:
  - Δ15m > 9% (grote move al voorbij)
  - Δ5m > 4.5% in één candle (spike, niet duurzaam)
  - Δ15m > 6% én acceleration_score < 0.4 (move vlakt af)
- `TOO_LATE` wordt opgeslagen in de database maar niet naar Telegram gestuurd
- De drempelwaarden zijn configureerbaar in YAML

---

### ✅ US-204 — Entry zone berekening

**Als** ontvanger van een `BUY_NOW` signaal
**wil ik** een concrete prijszone zien waarbinnen ik een limit order kan plaatsen
**zodat ik** niet markt koop op een tijdelijke spike

**Acceptatiecriteria:**
- `entry_min` = huidige bid × 0.997 (licht onder markt)
- `entry_max` = huidige ask × 1.002 (max betaalprijs)
- `max_chase_price` = entry_max × 1.008 (als prijs hier al boven zit: niet kopen)
- Alle drie de prijzen worden opgeslagen in de database per signaal
- Als het orderbook niet beschikbaar is, worden de velden op `null` gezet en wordt geen `BUY_NOW` label gegeven

---

### ✅ US-205 — Invalidation en take profit niveaus

**Als** ontvanger van een `BUY_NOW` signaal
**wil ik** een stopprijs en twee winstniveaus zien
**zodat ik** mijn risico vooraf begrensd heb

**Acceptatiecriteria:**
- `invalidation_price` = entry_min × 0.985 (–1.5% stop)
- `take_profit_1` = entry_max × 1.012 (+1.2%, dekt fees en spread terug)
- `take_profit_2` = entry_max × 1.025 (+2.5%, winst)
- Alle niveaus worden opgeslagen in de database
- De percentages zijn configureerbaar in YAML

---

### ✅ US-206 — "Do not chase" detectie

**Als** ontvanger van een signaal
**wil ik** een waarschuwing ontvangen als de prijs al te ver gestegen is sinds het signaal
**zodat ik** niet instap op een al uitgelopen move

**Acceptatiecriteria:**
- Als bij een volgende scan de prijs van een eerder `BUY_NOW` pair al boven `max_chase_price` staat, wordt een `DO_NOT_CHASE` Telegram-bericht gestuurd
- Het `DO_NOT_CHASE` bericht vermeldt: huidige prijs, de originele entry zone, en een suggestie om te wachten op pullback naar entry_min
- Dit bericht wordt maximaal 1× per signaal gestuurd

---

### ✅ US-207 — Nieuwe hard filters

**Als** systeem
**wil ik** filters die aansluiten op het doel (handmatig instappen)
**zodat ik** geen signalen geef op illiquide of al-uitgelopen pairs

**Acceptatiecriteria:**
- Nieuwe filterdrempels (configureerbaar in YAML):
  - `min_price_change_1m_pct: 0.20`
  - `min_price_change_3m_pct: 0.70`
  - `min_price_change_5m_pct: 1.20`
  - `max_price_change_5m_pct: 4.50`
  - `max_price_change_15m_pct: 9.00`
  - `min_volume_ratio: 2.50`
  - `max_spread_pct: 0.25`
  - `max_estimated_slippage_pct: 0.40`
- Nieuwe rejection reasons:
  - `TOO_LATE_EXTENDED_MOVE` (Δ15m > max)
  - `SPIKE_NO_CONTINUATION` (Δ5m > max)
  - `NO_SHORT_TERM_ACCELERATION` (acceleration_score = 0)
  - `ORDERBOOK_TOO_THIN` (slippage > max)
  - `SPREAD_TOO_HIGH_FOR_ENTRY`
- Alle rejection reasons worden opgeslagen in de database

---

## E3 — Beter Telegram-bericht

---

### ✅ US-301 — BUY_NOW bericht met volledig handelsplan

**Als** ontvanger van een `BUY_NOW` melding
**wil ik** in één bericht alle informatie zien die ik nodig heb
**zodat ik** niet zelf hoef uit te rekenen wat de entry, stop en TP zijn

**Acceptatiecriteria:**
Het Telegram-bericht voor `BUY_NOW` bevat:
- Exchange en trading pair
- Huidige prijs
- Score en label
- Δ1m, Δ3m, Δ5m, Δ15m
- Volume Ratio
- Spread percentage
- Entry zone (min – max)
- Stop / invalidation prijs
- TP1 en TP2
- Max chase prijs met expliciete "niet kopen boven X" tekst

Voorbeeldopmaak:
```
🟢 BUY NOW — SAGA-EUR (Bitvavo)

Prijs:  €0.01356    Score: 0.78
Δ1m:   +0.34%      Δ3m:  +0.91%
Δ5m:   +1.72%      Δ15m: +3.10%
VolR:   3.4×        Spread: 0.08%

Entry:   €0.01345 – €0.01360
Stop:    €0.01328  (–1.5%)
TP1:     €0.01377  (+1.2%)
TP2:     €0.01394  (+2.5%)

❌ Niet kopen boven €0.01370
```

---

### US-302 — WATCH bericht (informatief, geen actie)

**Als** ontvanger van een `WATCH` melding
**wil ik** weten dat er momentum opbouwt maar dat ik nog niet moet handelen
**zodat ik** me kan voorbereiden zonder overhaast in te stappen

**Acceptatiecriteria:**
- `WATCH` berichten worden verstuurd als score ≥ 0.55 maar < 0.72
- Het bericht is visueel duidelijk anders dan `BUY_NOW` (ander emoji/kleur)
- Het bericht bevat géén entry zone, stop of TP (want nog niet koopwaardig)
- Het bericht bevat wel: pair, prijs, Δ5m, Δ15m, VolR, acceleration_score

Voorbeeldopmaak:
```
🟡 WATCH — GRASS-EUR (Bitvavo)

Prijs:  €0.3467    Score: 0.61
Δ5m:   +1.8%      Δ15m: +2.6%
VolR:   3.0×       Spread: 0.12%

Momentum opbouwend. Wacht op versterking.
```

---

### ✅ US-303 — DO_NOT_CHASE bericht

**Als** ontvanger van een eerder `BUY_NOW` signaal
**wil ik** een waarschuwing als de prijs al te ver gestegen is
**zodat ik** niet te laat instap en verlies lijd

**Acceptatiecriteria:**
- Bericht wordt gestuurd als de prijs > `max_chase_price` van het originele signaal
- Maximaal 1× per signaal
- Bevat: huidige prijs, originele entry zone, suggestie voor pullback

Voorbeeldopmaak:
```
🔴 NIET KOPEN — SAGA-EUR

Prijs nu:     €0.01382
Was entry:    €0.01345 – €0.01360
Te duur.      Wacht op terugval naar €0.01355
```

---

## E4 — Outcome tracking

---

### ✅ US-401 — Outcome tabel in database

**Als** analist
**wil ik** voor elk `BUY_NOW` signaal de prijsontwikkeling erna bijhouden
**zodat ik** kan meten of de signalen daadwerkelijk winstgevend zijn

**Acceptatiecriteria:**
- Nieuwe tabel `signal_outcomes` in de bestaande SQLite database:

```sql
CREATE TABLE signal_outcomes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id        INTEGER NOT NULL REFERENCES signals(id),
    entry_price      REAL NOT NULL,
    max_price_1m     REAL,
    max_price_3m     REAL,
    max_price_5m     REAL,
    max_price_10m    REAL,
    max_price_30m    REAL,
    min_price_1m     REAL,
    min_price_3m     REAL,
    min_price_5m     REAL,
    min_price_10m    REAL,
    min_price_30m    REAL,
    hit_tp1          INTEGER,
    hit_tp2          INTEGER,
    hit_stop         INTEGER,
    best_exit_pct    REAL,
    worst_drawdown_pct REAL,
    evaluated_at     REAL
);
```

- De tabel wordt aangemaakt bij service-start als die nog niet bestaat

---

### ✅ US-402 — Automatische outcome evaluatie

**Als** systeem
**wil ik** dat de service zelf de outcomes invult
**zodat ik** geen handmatig werk hoef te doen

**Acceptatiecriteria:**
- Elke scan controleert of er `BUY_NOW` signalen zijn ouder dan 1, 3, 5, 10 en 30 minuten waarvoor nog geen outcome staat
- De prijs van het pair uit de huidige scan wordt gebruikt als evaluatiepunt
- `hit_tp1`, `hit_tp2`, `hit_stop` worden op `1` gezet zodra de prijs die grens gepasseerd heeft in een latere scan
- `best_exit_pct` = hoogste `max_price_Xm` t.o.v. `entry_price`
- `worst_drawdown_pct` = laagste `min_price_Xm` t.o.v. `entry_price`
- Evaluatie stopt na 30 minuten (outcome is dan compleet)

---

## E5 — Analyse

---

### ✅ US-501 — Analyse script voor outcome resultaten

**Als** product owner
**wil ik** een overzicht kunnen draaien van hoe goed de `BUY_NOW` signalen presteren
**zodat ik** de drempelwaarden kan bijstellen op basis van echte data

**Acceptatiecriteria:**
- Een bestaand of nieuw analyse-script toont:
  - Totaal aantal `BUY_NOW` signalen per exchange
  - % waarbij TP1 gehaald werd vóór de stop
  - % waarbij TP2 gehaald werd
  - % waarbij de stop geraakt werd
  - Gemiddelde maximale winst binnen 5 en 10 minuten
  - Gemiddelde maximale drawdown binnen 3 minuten
- Filterbaar op exchange, datum en VolR-range
- Uitvoer in terminal (geen grafische interface nodig)

---

### ✅ US-502 — Analyse: welke rejection reason voorspelt toch een goede trade

**Als** product owner
**wil ik** weten of afgewezen signalen (bijv. `TOO_LATE`) later alsnog goede kansen waren
**zodat ik** de filters kan aanscherpen of versoepelen

**Acceptatiecriteria:**
- Het analyse-script toont per rejection reason de gemiddelde prijsontwikkeling na het moment van afwijzing (op basis van de prijssnapshots die de scanner al bijhoudt)
- Alleen mogelijk voor rejection reasons die wél in de database staan (niet-opgeslagen pairs zijn niet analyseerbaar)

---

## E6 — Operationeel bewustzijn (voor later)

### US-601 — Scan-duur monitoring

**Als** operator van de scanner
**wil ik** weten hoe lang elke scan duurt
**zodat ik** kan detecteren of scans vertraging oplopen of elkaars vervolg overlappen

**Achtergrond:**
De geconfigureerde scan-interval is 60 s, maar scans duren in de praktijk ~80 s. Dit is momenteel acceptabel (geen overlap door de `sleep(max(0, interval - elapsed))` logica), maar als de duur groeit is er geen signalering.

**Acceptatiecriteria:**
- Service logt scan-duur als `INFO` aan het einde van elke scan: `"[SCAN %s] duur: %.1fs"`
- Als scan-duur > `max_scan_duration_warn_seconds` (default 120 s, configureerbaar), log een `WARNING`
- Als scan-duur > geconfigureerde `scan_interval_seconds`, log een `WARNING` met tekst: `"Scan duurde langer dan interval; volgende scan start meteen"`
- De drie drempelwaarden zijn configureerbaar in YAML (geen magic constants)

**Scope:** Alleen logging en config — geen dashboards, geen externe alerts.

---

### US-602 — Post-hoc drempelkalibratie

**Als** product owner
**wil ik** na 2–4 weken dataverzameling de BUY_NOW en WATCH drempelwaarden kunnen herijken
**zodat ik** het percentage valse positieven kan verlagen zonder echte kansen te missen

**Achtergrond:**
De huidige drempelwaarden (score ≥ 0.72 BUY_NOW, TOO_LATE bij Δ15m > 9%) zijn startpunten gebaseerd op aannames. Na 2–4 weken bevatten de tabellen `signals` en `signal_outcomes` voldoende data om objectief te kalibreren.

**Acceptatiecriteria:**
- `analyze_signal_outcomes.py` rapporteert voor elke score-bucket (bijv. 0.70–0.75, 0.75–0.80, …) de TP1- en TP2-hitrate en de gemiddelde max drawdown
- Script heeft een `--score-buckets` optie om de breedte van de buckets in te stellen
- Documentatie beschrijft het kalibratie-proces: "draai dit script na N weken, vergelijk hitrates per bucket, stel `buy_now_min_score` bij"
- De TOO_LATE grens (`too_late_delta_15m_pct`) wordt meegenomen in de analyse: script toont voor afgewezen TOO_LATE signalen de werkelijke prijsontwikkeling zodat duidelijk is of de grens te streng of te soepel is

**Deliverables:**
1. Update `analyze_signal_outcomes.py` met `--score-buckets` argument
2. Update `analyze_rejection_outcomes.py` om TOO_LATE specifiek te highlighten
3. Sectie "Kalibratie" toevoegen aan de service-documentatie

---

## Niet in scope (bewust weggelaten)

- Exchange-specifieke liquiditeitsdrempels (te vroeg, eerst data verzamelen)
- Koppeling met de grid-bot (apart product)
- Grafische interface of dashboard
- Backtesting op historische data buiten de scanner

---

## Openstaande vragen voor PO review

1. **Drempelwaarden** — de voorgestelde drempelwaarden (score ≥ 0.72 voor BUY_NOW, stop –1.5%, TP1 +1.2%) zijn startpunten. Klopt dit met hoe jij handmatig handelt?

2. **WATCH berichten** — wil je deze ontvangen, of alleen BUY_NOW? Ze kunnen afleiden als er veel WATCH-kandidaten zijn.

3. **Exchanges** — wil je BUY_NOW signalen voor alle vier exchanges (Bitvavo, Kraken, OKX, Bitget) of alleen Bitvavo voor handmatig kopen?

4. **Bedraggrootte** — de slippage berekening gebruikt €100 en €250. Klopt dit met de bedragen waarmee je handmatig instapt?

5. **Stop percentage** — –1.5% stop is vrij strak voor kleine volatile coins. Wil je dit configureerbaar per exchange of per pair?
