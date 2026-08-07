# Momentum Signal Service — Technische Review

**Doel van dit document:** Een volledige, eerlijke beschrijving van hoe de
Momentum Signal Service gebouwd is, inclusief code, echte voorbeelden en
bekende beperkingen. Bedoeld voor externe review.

---

## 1. Wat doet de service?

De service scant elke ~80 seconden alle geconfigureerde exchanges op zoek naar
crypto-pairs met een **plotselinge prijsbeweging + volumepiek**. Als een pair
door alle filters komt én een voldoende score heeft, wordt er een melding
gestuurd (Telegram) en opgeslagen in een SQLite database.

**De service plaatst NOOIT orders.** Er bestaat een assertion bij startup:

```python
# momentum_signal_service.py
assert config.mode == "signal_only", (
    f"mode must be 'signal_only', got '{config.mode}'"
)
```

---

## 2. Architectuur — 5 stappen per scan

```
┌─────────────────────────────────────────────────────────────────┐
│  Elke ~80 seconden:                                             │
│                                                                 │
│  Stap 1: FETCH        │ REST API → ticker data van alle pairs   │
│  Stap 2: PRESELECT    │ Top N per exchange o.b.v. spread/volume │
│  Stap 3: ENRICH       │ 1m candles + orderbook ophalen          │
│  Stap 4: HARD FILTER  │ Verwerp o.b.v. harde drempelwaarden     │
│  Stap 5: SCORE        │ Geef score 0.0–1.0; ≥ 0.30 = signaal   │
│                                                                 │
│  Output: Telegram melding + SQLite opslag + JSON snapshot       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Stap-voor-stap uitleg met code

### Stap 1 — Fetch: ticker data ophalen

De service haalt van alle exchanges alle beschikbare trading pairs op via de
publieke ticker REST API. Geen authenticatie nodig.

**Exchanges geconfigureerd:**
| Exchange | Quote asset | Regio |
|---|---|---|
| Bitvavo | EUR | Europa |
| Kraken | USD | Globaal |
| OKX | USDC | Europa |
| Bitget | USDT | Globaal |

Elke exchange levert ~300–500 pairs op. Totaal universum per scan: **~1700 pairs**.

**Voorbeeld Bitvavo ticker response (vereenvoudigd):**
```json
{
  "market": "SAGA-EUR",
  "last": "0.01356",
  "bid": "0.01354",
  "ask": "0.01365",
  "open": "0.01298",
  "volumeQuote": "45230.5"
}
```

### Stap 2 — Preselect: beste kandidaten kiezen

Van de ~1700 pairs worden de meest liquide en beweeglijke pairs geselecteerd
voor duurdere API-calls (candles + orderbook). Max 50 per exchange.

Selectiecriteria voor preselection:
- Niet op blacklist
- Geen actieve grid-positie op die exchange
- Beste spread (hoe smaller, hoe beter)

### Stap 3 — Enrich: 1m candles + orderbook ophalen

Voor de ~50 geselecteerde pairs per exchange worden 20 candles van 1 minuut
opgehaald. Hieruit worden berekend:

```python
# momentum_indicators.py

def price_change_pct(candles, n_periods):
    """Procentuele prijsverandering over de laatste n_periods candles."""
    close_now = candles[-1].close
    close_ago = candles[-(n_periods + 1)].close
    return (close_now - close_ago) / close_ago * 100.0

def volume_ratio(candles, recent_n=5, baseline_n=15):
    """Gemiddeld volume laatste 5 candles ÷ gemiddeld volume 15 candles daarvoor."""
    recent_avg  = mean(candles[-5:].volume)
    baseline_avg = mean(candles[-20:-5].volume)
    return recent_avg / baseline_avg
```

**Stale candle bescherming** (toegevoegd na bug — zie §7):

```python
# momentum_indicators.py

_MAX_CANDLE_AGE_SECONDS = 120  # 1m candles: nieuwste mag max 2 min oud zijn

def apply_candle_metrics(candidate, candles, now):
    if not candles:
        return
    newest_candle_age = now - candles[-1].timestamp
    if newest_candle_age > _MAX_CANDLE_AGE_SECONDS:
        return  # Stale data → metrics blijven None → afgewezen als MISSING_PRICE_CHANGE_5M
    # ... metrics berekenen ...
```

### Stap 4 — Hard filter: harde drempels

Alle candidates worden door een reeks harde filters gehaald. Een candidate
wordt afgewezen als hij ook maar één reden heeft.

```python
# momentum_filters.py (vereenvoudigd)

def _collect_reasons(self, candidate, cf, now, universe):
    reasons = []

    # 1. Toestandscontroles
    if candidate.blacklisted:           reasons.append("BLACKLISTED")
    if candidate.active_grid_position:  reasons.append("ACTIVE_GRID_POSITION")
    if candidate.in_cooldown:           reasons.append("IN_COOLDOWN")

    # 2. Universe filter (geen stablecoins, forex, metalen, major assets)
    if base in STABLECOINS:             reasons.append("STABLECOIN_OR_FOREX")
    if base in ["BTC","ETH","BNB",...]: reasons.append("EXCLUDED_MAJOR_ASSET")

    # 3. Data kwaliteit (geen candles → afgewezen)
    if candidate.price_change_5m_pct is None:  reasons.append("MISSING_PRICE_CHANGE_5M")
    if candidate.volume_ratio is None:         reasons.append("MISSING_VOLUME_RATIO")

    # 4. Numerieke drempels
    if candidate.price_change_5m_pct  < 1.5:   reasons.append("MOMENTUM_TOO_LOW")
    if candidate.price_change_15m_pct < 2.5:   reasons.append("MOMENTUM_TOO_LOW")
    if candidate.volume_ratio         < 2.0:   reasons.append("VOLUME_TOO_LOW")
    if candidate.spread_pct           > 0.35:  reasons.append("SPREAD_TOO_HIGH")

    return reasons
```

**Actuele filterdrempels** (uit `momentum_signal_service.yaml`):

```yaml
candidate_filters:
  min_price_change_5m_pct:  1.5    # Δ5m ≥ 1.5%
  min_price_change_15m_pct: 2.5    # Δ15m ≥ 2.5%
  max_price_change_15m_pct: 35.0   # Extreme pump filter
  min_volume_ratio:         2.0    # Volume 2× boven normaal
  max_spread_pct:           0.35   # Max 0.35% bid-ask spread
```

### Stap 5 — Score: gecombineerde kwaliteitsscore

Candidates die alle hard filters passeren krijgen een score van 0.0 tot 1.0.
Drempel: **0.30** (anders afgewezen als `SCORE_TOO_LOW`).

```python
# momentum_candidate_scorer.py (MomentumCandidateScorer)

DEFAULT_SCORER_WEIGHTS = {
    "trend_1h":         0.25,   # ← NIET beschikbaar in REST service (altijd 0)
    "trend_4h":         0.30,   # ← NIET beschikbaar in REST service (altijd 0)
    "volume_expansion": 0.20,   # ← Gebruikt volume_ratio als fallback
    "relative_strength":0.15,   # ← Niet beschikbaar (altijd 50%)
    "spread":           0.05,
    "rsi_wick_risk":    0.05,
}

def _volume_score(volume_expansion):
    # VolR=1× → 0 pts, VolR=3× → 100 pts, VolR=2× → 50 pts
    return clamp((volume_expansion - 1.0) / 2.0 * 100.0, 0, 100)

def _spread_score(spread_pct, max_spread_pct):
    # Spread=0% → 100 pts, spread=max → 0 pts
    return clamp((max_spread_pct - spread_pct) / max_spread_pct * 100.0, 0, 100)

def _rsi_wick_score(rsi, max_rsi, wick_risk):
    # RSI < 60 → geen aftrek; boven 60 → straf; wick_risk 0→100%, 1→0%
    rsi_score = clamp(100.0 - max(0, rsi - 60) / (max_rsi - 60) * 50.0, 0, 100)
    wick_score = clamp(100.0 - wick_risk * 100.0, 0, 100)
    return (rsi_score + wick_score) / 2.0
```

**Score voorbeeld — SAGA-EUR 2026-06-04 18:33 UTC:**

```
Input:
  volume_ratio    = 3.0  (VolR: 3× boven normaal)
  spread_pct      = 0.07% (smal)
  rsi             = 50   (neutraal, aangenomen)
  trend_1h_pct    = None → 0.0
  trend_4h_pct    = None → 0.0

Berekening per component:
  trend_1h         = _positive_score(0.0, full_at=4.0)  = 0.0   × 0.25 = 0.000
  trend_4h         = _positive_score(0.0, full_at=10.0) = 0.0   × 0.30 = 0.000
  volume_expansion = _volume_score(3.0)                 = 100.0 × 0.20 = 20.0
  relative_strength= _rs_score(0.0)                    = 50.0  × 0.15 = 7.5
  spread           = _spread_score(0.07, 0.5)           = 86.0  × 0.05 = 4.3
  rsi_wick_risk    = _rsi_wick_score(50, 80, 0)         = 100.0 × 0.05 = 5.0

Totaal: 36.8 / 100 → score = 0.368  ✅ (≥ drempel 0.30)
```

---

## 4. Echte signaalvoorbeelden uit de database

### Geaccepteerd signaal — SAGA-EUR (Bitvavo, 2026-06-04)

```
Tijdstip (UTC): 2026-06-04 18:33
Trading pair:   SAGA-EUR (Bitvavo)
Prijs:          €0.01356
Δ5m:           +1.71%
Δ15m:          +4.27%
Volume Ratio:   3.0× (3× boven het 15m gemiddelde)
Score:          0.359

Score breakdown:
  trend_1h         0.000  ░░░░░░░░░░░░░░░░░░░░  (REST service: nooit beschikbaar)
  trend_4h         0.000  ░░░░░░░░░░░░░░░░░░░░  (REST service: nooit beschikbaar)
  volume_expansion 1.000  ████████████████████
  relative_strength 0.500 ██████████            (aangenomen, geen BTC-benchmark)
  spread           0.705  ██████████████
  rsi_wick_risk    1.000  ████████████████████
```

### Geaccepteerd signaal — GRASS-EUR (Bitvavo, 2026-06-04)

```
Tijdstip (UTC): 2026-06-04 19:16
Trading pair:   GRASS-EUR (Bitvavo)
Prijs:          €0.34666
Δ5m:           +2.15%
Δ15m:          +2.61%
Volume Ratio:   3.0×
Score:          0.355
```

### Afgewezen kandidaten (zelfde periode)

```
HEI-EUR   (Bitvavo) — Δ15m=+4.18%, VolR=0.7×  → VOLUME_TOO_LOW   (< 2.0×)
DOG-USD   (Kraken)  — Δ15m=+10.5%, VolR=0.8×  → VOLUME_TOO_LOW   (< 2.0×)
WIF-EUR   (Bitvavo) — Δ5m=+1.54%,  Δ15m=+2.5% → MOMENTUM_TOO_LOW (Δ5m < 1.5%)
WLD-USD   (Kraken)  — Δ15m=+3.3%,  VolR=0.8×  → VOLUME_TOO_LOW
```

### Afwijzingsredenen afgelopen uur (typisch beeld)

```
MOMENTUM_TOO_LOW       6210×  ← Δ5m of Δ15m onder drempel (normaal)
STABLECOIN_OR_FOREX     836×  ← USDT, EUR, USDC pairs (normaal)
EXCLUDED_MAJOR_ASSET    484×  ← BTC, ETH, BNB (normaal)
MISSING_VOLUME_RATIO    328×  ← Te weinig candle-history (nieuwe pairs)
ACTIVE_GRID_POSITION    220×  ← Bot heeft al een positie in dit pair
EXCLUDED_ASSET_TYPE     176×  ← Tokenized metalen (XAUT etc.)
VOLUME_TOO_LOW           12×  ← VolR < 2.0× (bewust afgewezen)
```

---

## 5. Bekende beperkingen — eerlijk

### Beperking 1: 55% van de score is structureel blind

De scorer heeft gewichten voor `trend_1h` (25%) en `trend_4h` (30%) — samen
55% van de totale score. De REST-only service haalt **geen 1h/4h candles op**.
Die componenten zijn dus altijd 0.

**Gevolg:** Max haalbare score = 37.5/100 = **0.375**.
De drempel staat op 0.30 — dus een pair moet bijna de maximale score halen.

**Workaround toegepast:** `volume_ratio` (wel beschikbaar) wordt gebruikt als
fallback voor `volume_expansion`. Maar structureel zijn de zwaarste
gewichten (55%) altijd leeg.

```python
# momentum_signal_scorer.py — volume_ratio fallback
vol = (
    candidate.volume_expansion          # Nooit gevuld door REST service
    if candidate.volume_expansion is not None
    else candidate.volume_ratio         # Wel gevuld — wordt gebruikt als proxy
)
```

### Beperking 2: Signalen zijn 15 minuten oud bij ontvangst

De `min_price_change_15m_pct` filter vereist dat een move **al 15 minuten
heeft plaatsgevonden** voordat er een signaal wordt gegeven. Praktijktest:

```
SAGA-EUR prijs tijdlijn:
  18:17 UTC: prijs = €0.01336  (+3.7% over 15m) → afgewezen (Δ5m te laag)
  18:29 UTC: prijs = €0.01354  (+3.9% over 15m) → afgewezen (Δ5m te laag)
  18:33 UTC: prijs = €0.01356  (+4.3% over 15m) → ✅ SIGNAAL
  18:56 UTC: prijs = €0.01362  (+2.2% over 15m) → afgewezen

Conclusie: van de +4.3% totale move was +3.7% al voorbij bij het signaal.
Rendement ná signaal: +0.4% over 23 minuten.
Na fees (0.25% maker + taker) en spread: nauwelijks positief.
```

**Dit systeem is niet bedoeld voor handmatig instappen op het signaal.**
Het is gebouwd als input voor een grid-bot die de oscillatie ná de move benut.

### Beperking 3: Scan duurt ~80s terwijl interval 60s is

```
scan_interval_seconds: 60   # Config
Werkelijke interval:   ~80s  # Gemeten in database
```

De scan zelf kost ~20 seconden (REST calls). Na de scan wacht de service nog
60 seconden — waardoor de effectieve frequentie 1 scan per 80s is in plaats
van 60s. Dit is inherent aan de architectuur (sequentieel: scan → wachten).

### Beperking 4: Geen 1h/4h candle data

De service gebruikt alleen 1m candles (de laatste 20). Hierdoor:
- Geen trendrichting op langere termijn
- Geen RSI (vereist minimaal 14 periodes van het juiste timeframe)
- Geen echte `volume_expansion` (vs. 24h baseline)

Al deze velden staan wel in het datamodel maar worden nooit gevuld.

---

## 6. Data opslag

**SQLite tabel `signals`:**

```sql
CREATE TABLE signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       TEXT    NOT NULL,   -- UUID per scan
    timestamp     REAL    NOT NULL,   -- Unix epoch
    exchange      TEXT    NOT NULL,
    trading_pair  TEXT    NOT NULL,
    price         REAL    NOT NULL,
    spread_pct    REAL,
    price_change_5m_pct   REAL,
    price_change_15m_pct  REAL,
    volume_ratio  REAL,
    score         REAL    NOT NULL,
    accepted      INTEGER NOT NULL,   -- 0 of 1
    rank          INTEGER,
    rejection_reason TEXT,
    all_reasons   TEXT,               -- JSON array
    score_breakdown TEXT,             -- JSON object
    created_at    REAL    NOT NULL
);
```

**Retentie:** 7 dagen. Elke scan schrijft ~344 rijen (alleen enriched pairs,
niet-enriched pairs worden gefilterd voor opslag).

---

## 7. Bugs gevonden en opgelost

### Bug 1 — Stale candle bug (ontdekt 2026-06-04)

**Probleem:** Low-volume pairs die na een pump inactief worden, leveren
dezelfde oude candles opnieuw via de API. De service merkte dit niet en
meldde een move die 70+ minuten oud was.

```
SAGA-EUR voorbeeld:
  15:56 UTC: Pump plaatsvindt (+5.15% in 15m)
  17:07 UTC: Nog steeds exact dezelfde d5m/d15m/price in elke scan
  Duur: 71 minuten bevroren data, 49 opeenvolgende valse meldingen
```

**Fix:** In `apply_candle_metrics` wordt nu de timestamp van de nieuwste
candle gecontroleerd. Als die ouder is dan 120 seconden (2 minuten), worden
geen metrics ingevuld en valt het pair als `MISSING_PRICE_CHANGE_5M` weg.

### Bug 2 — Scorer structureel onmogelijk (ontdekt 2026-06-03)

**Probleem:** De min_score drempel stond op 0.70 (70/100), maar de maximum
haalbare score was 0.175 (17.5/100) omdat 55% van de score-gewichten
afhankelijk zijn van data die de REST service nooit ophaalt.

**Gevolg:** 0 signalen in 9+ dagen ondanks actieve kandidaten.

**Fix:**
1. `volume_ratio` gebruikt als fallback voor `volume_expansion`
2. `min_score` verlaagd van 0.70 naar 0.30 (onder het nieuwe maximum van 0.375)

### Bug 3 — DB bloat (ontdekt 2026-06-01)

**Probleem:** Elke scan sloeg ~1720 niet-verrijkte pairs op als
`MISSING_PRICE_CHANGE_5M` rij. Na een week: 15.9M+ rijen, 3.5 GB.

**Fix:** Filteren vóór `save_batch()` — niet-verrijkte pairs worden niet
meer opgeslagen in de database.

---

## 8. Wat ontbreekt / aanbevelingen voor review

De reviewer wordt gevraagd specifiek te kijken naar:

1. **Scorer-architectuur:** Is het zinvol om een scorer te hebben waarvan 55%
   van de gewichten structureel altijd 0 zijn? Of moet de scorer worden
   herschreven voor alleen de beschikbare dimensies?

2. **Timing van signalen:** De `min_price_change_15m_pct` filter garandeert
   dat signalen altijd 10–15 minuten oud zijn. Is er een betere aanpak voor
   tijdige signalering (bijv. focus op Δ5m + VolR)?

3. **REST vs. WebSocket:** De service gebruikt alleen REST polling (elke 80s).
   Een WebSocket-gebaseerde aanpak zou real-time candle-updates geven en de
   stale-candle bug structureel oplossen.

4. **Gebruik van signalen:** De signalen worden nu naar Telegram gestuurd maar
   er is geen koppeling met de grid-bot. De grid-bot opent momenteel grids op
   basis van eigen logica, niet op basis van momentum-signalen. Is die
   koppeling de bedoeling?

5. **Score breakdown inconsistentie:** De `score_breakdown` in de database
   toont `volume_expansion: 0.0` bij pairs waarvoor de scorer intern
   `volume_ratio` als fallback gebruikt. Dit is een logging-inconsistentie
   (de beslissing is correct, maar de rapportage is misleidend).
   Fix is geïmplementeerd maar vereist service-herstart om actief te worden.

---

## 9. Hoe te starten/stoppen

```bash
cd /home/mo/repos/hummingbot
source .venv/bin/activate

# Starten
python -m multi_coin_grid_pro.services.momentum_signal_service \
  --config multi_coin_grid_pro/config/momentum_signal_service.yaml \
  --log-level WARNING \
  >> data/momentum_service.log 2>&1 &
echo $! > data/momentum_service.pid

# Status
kill -0 $(cat data/momentum_service.pid) 2>/dev/null && echo "actief" || echo "gestopt"

# Stoppen
kill $(cat data/momentum_service.pid) && rm data/momentum_service.pid
```

**Relevante bestanden:**
| Bestand | Rol |
|---|---|
| `multi_coin_grid_pro/services/momentum_signal_service.py` | Hoofd service loop |
| `multi_coin_grid_pro/signals/momentum_market_data.py` | REST API fetchers |
| `multi_coin_grid_pro/signals/momentum_indicators.py` | Candle-berekeningen (incl. stale fix) |
| `multi_coin_grid_pro/signals/momentum_filters.py` | Hard filter pipeline |
| `multi_coin_grid_pro/signals/momentum_signal_scorer.py` | Score wrapper (0.0–1.0) |
| `multi_coin_grid_pro/logic/momentum_candidate_scorer.py` | Score berekening |
| `multi_coin_grid_pro/config/momentum_signal_service.yaml` | Alle configuratie |
| `data/momentum_signals.sqlite` | Historische signalen (SQLite) |
| `data/momentum_signals.json` | Laatste scan (JSON snapshot) |
