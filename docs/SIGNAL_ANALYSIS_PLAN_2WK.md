# Signal Analyse Plan — 2-weeks review

**Doel**: Na ~2 weken productie-data bepalen of de signaalfilters, preselection en drempelwaarden goed zijn afgesteld, en of het signaal betrouwbaar genoeg is om er daadwerkelijk mee te handelen.

**Review-status**: v2 — verwerkt feedback op volgorde-problematiek, event-deduplicatie, netto EV en uitgebreide filters.

---

## 0. Context voor externe lezer (lees dit eerst)

Dit document is volledig zelfstandig: je hebt alleen toegang tot de SQLite-database nodig om alle analyses uit te voeren.

### 0A. Wat doet dit systeem?

Een live momentum-signaalservice scant elke ~80 seconden alle crypto-spotmarkten op Bitvavo en Kraken. Voor elke kandidaat berekent het een score op basis van prijsmomentum, volume, spread en technische filters. Sterk scorende kandidaten krijgen een label:

| Label | Betekenis |
|---|---|
| `BUY_NOW` | Sterk momentum-signaal — directe entry is interessant |
| `WATCH` | Opkomend signaal — potentieel, maar nog niet rijp genoeg |
| `TOO_LATE` | Momentum al te ver gevorderd — entry te risicovol |
| `NULL` | Kandidaat niet door de filters gekomen (de bulk van de rijen) |

Na het labelen volgt de **outcome tracker**: 30 minuten na elk gelabeld signaal wordt gemeten of de prijs TP1, TP2 of de stop heeft geraakt, en in welke volgorde.

### 0B. Database

**Locatie**: `data/momentum_signals.sqlite` (SQLite, WAL-mode)

Voer eerst een WAL-checkpoint uit zodat de data volledig gespoeld is:
```bash
sqlite3 data/momentum_signals.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
```

Of via Python:
```python
import sqlite3
conn = sqlite3.connect('data/momentum_signals.sqlite')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.commit()
```

### 0C. Schema

```sql
CREATE TABLE signals (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id               TEXT    NOT NULL,   -- uniek per scan-ronde
    timestamp             REAL    NOT NULL,   -- Unix epoch (seconden)
    exchange              TEXT    NOT NULL,   -- 'bitvavo' | 'kraken'
    trading_pair          TEXT    NOT NULL,   -- bijv. 'BTC-EUR', 'ETH-USDC'
    price                 REAL    NOT NULL,   -- prijs op moment van scan
    spread_pct            REAL,              -- bid-ask spread als % van midprice
    price_change_1m_pct   REAL,              -- prijsverandering afgelopen 1 minuut
    price_change_3m_pct   REAL,
    price_change_5m_pct   REAL,
    price_change_15m_pct  REAL,              -- cruciaal voor TOO_LATE grens
    volume_ratio          REAL,              -- huidig volume / gemiddeld volume
    score                 REAL    NOT NULL,  -- composiet score 0.0–1.0
    accepted              INTEGER NOT NULL,  -- 1 = gepasseerd alle filters
    rank                  INTEGER,           -- rank binnen scan-ronde
    rejection_reason      TEXT,              -- eerste reden van afwijzing
    all_reasons           TEXT,              -- JSON array van alle afwijzingen
    score_breakdown       TEXT,              -- JSON object met deelscores
    signal_label          TEXT,              -- 'BUY_NOW' | 'WATCH' | 'TOO_LATE' | NULL
    entry_min             REAL,              -- ondergrens entry-zone (absoluut)
    entry_max             REAL,              -- bovengrens entry-zone (absoluut)
    max_chase_price       REAL,              -- max prijs waarboven niet meer instappen
    invalidation_price    REAL,              -- stop-loss niveau (absoluut)
    take_profit_1         REAL,              -- TP1 niveau (absoluut, ~+1.2% boven entry)
    take_profit_2         REAL,              -- TP2 niveau (absoluut, ~+2.5% boven entry)
    slippage_100eur       REAL,              -- geschatte slippage bij €100 order
    slippage_250eur       REAL,
    acceleration_score    REAL,
    preselection_score    REAL,              -- score uit de preselection-fase
    preselection_rank     INTEGER,
    preselection_bucket   TEXT,              -- 'A' | 'B' | 'C' | etc.
    preselection_breakdown TEXT,             -- JSON met deelscores preselection
    created_at            REAL    NOT NULL
);

CREATE TABLE signal_outcomes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id            INTEGER NOT NULL,         -- FK → signals.id
    entry_price          REAL    NOT NULL,          -- entry_max uit signals (worst-case)
    -- max/min prijzen per tijdsvenster na entry:
    max_price_1m         REAL,  max_price_3m  REAL,  max_price_5m  REAL,
    max_price_10m        REAL,  max_price_30m REAL,
    min_price_1m         REAL,  min_price_3m  REAL,  min_price_5m  REAL,
    min_price_10m        REAL,  min_price_30m REAL,
    -- of levels geraakt zijn (0/1, ONAFHANKELIJK van volgorde):
    hit_tp1              INTEGER DEFAULT 0,         -- 1 = TP1 ooit geraakt in 30min
    hit_tp2              INTEGER DEFAULT 0,
    hit_stop             INTEGER DEFAULT 0,
    -- %-rendement t.o.v. entry_price:
    best_exit_pct        REAL,   -- (max_price_30m - entry_price) / entry_price * 100
    worst_drawdown_pct   REAL,   -- (min_price_30m - entry_price) / entry_price * 100
    evaluated_at         REAL,   -- Unix epoch wanneer outcome berekend (NULL = nog niet)
    -- VOLGORDE-velden (v2 — crucial):
    first_hit            TEXT,   -- 'TP1' | 'TP2' | 'STOP' | 'TIMEOUT' | NULL
    tp1_hit_at_seconds   REAL,   -- seconden na entry waarop TP1 voor het eerst geraakt
    tp2_hit_at_seconds   REAL,
    stop_hit_at_seconds  REAL
);
```

### 0D. Drempelwaarden in het systeem

Deze constanten zijn geconfigureerd in de signaalservice en worden als gegeven beschouwd in de analyse:

| Parameter | Waarde | Uitleg |
|---|---|---|
| TP1 boven entry | +1.2% | Eerste winstdoel |
| TP2 boven entry | +2.5% | Tweede winstdoel |
| Stop onder entry | −1.5% | Verliesgrens |
| Uitboeking venster | 30 minuten | Na dit venster: TIMEOUT |
| Round-trip fee | 0.50% | Taker fee heen + terug (maker korting buiten beschouwing) |
| TOO_LATE grens | Δ15m ≥ 6.0% | Boven dit momentum: te laat voor entry |
| Score drempel | ≥ 0.80 | Minimale score voor BUY_NOW label |

### 0E. Hoe werkt `first_hit`?

`hit_tp1=1` én `hit_stop=1` kunnen allebei waar zijn in één 30-minuten venster — de coin steeg eerst, daalde daarna (of andersom). **Alleen de volgorde bepaalt of het een winnende of verliezende trade is**.

De `first_hit` kolom lost dit op:
- `TP1`: prijs bereikte +1.2% vóórdat −1.5% geraakt werd → **winnend**
- `TP2`: prijs bereikte +2.5% als eerste → **winnend**
- `STOP`: prijs bereikte −1.5% als eerste → **verliezend**
- `TIMEOUT`: geen van de niveaus geraakt in 30min → **neutraal** (gebruik `best_exit_pct`)
- `NULL`: outcome nog niet berekend (service niet herstart na v2-upgrade)

**Breakeven winrate** (met 0.50% round-trip fee):
$$\text{winrate}_{\min} = \frac{|\text{stop}| + \text{fee}}{(\text{TP1} - \text{fee}) + (|\text{stop}| + \text{fee})} = \frac{2.0}{0.7 + 2.0} \approx 74\%$$

> Noot: als `first_hit` grotendeels `NULL` is, draait de service nog op de oude code. Gebruik dan `hit_tp1` en `hit_stop` als proxy (minder nauwkeurig).

### 0F. Huidig data-volume (2026-06-07)

| Tabel | Rijen |
|---|---|
| signals (totaal) | ~483.000+ |
| signals met label | ~200+ (service gestart 2026-06-05) |
| signal_outcomes | ~141 |

De service is recent gestart — volledige 2-weeks analyse pas mogelijk na ~2026-06-19.

---

---

## 1. Wat hebben we dan

Na 2 weken verwachten we:

| Gegeven | Schatting |
|---|---|
| Scans | ~20.000 (1 per ~80s) |
| Geanalyseerde candidates | ~4 miljoen rijen in `signals` |
| BUY_NOW signals | 800–2.000 (afhankelijk van markt) |
| WATCH signals | 500–1.500 |
| TOO_LATE signals (met outcome) | 400–1.000 |
| Outcomes (alle labels) | ~alle labeled signals |
| Preselection breakdown | aanwezig op alle signals |

Database: `data/momentum_signals.sqlite`
Tabellen: `signals`, `signal_outcomes`

### Nieuwe velden in `signal_outcomes` (v2)

Naast de bestaande `hit_tp1/tp2/stop` zijn er nu tijdsvelden:

| Veld | Betekenis |
|---|---|
| `first_hit` | `TP1` / `TP2` / `STOP` / `TIMEOUT` / `NONE` |
| `tp1_hit_at_seconds` | seconden na entry waarop TP1 geraakt |
| `tp2_hit_at_seconds` | seconden na entry waarop TP2 geraakt |
| `stop_hit_at_seconds` | seconden na entry waarop stop geraakt |

**Waarom dit cruciaal is**: `hit_tp1=1` én `hit_stop=1` kan allebei waar zijn in 30 minuten. Alleen de volgorde bepaalt of het een winnende of verliezende trade is.

---

## 2. De kernvragen

### 2A. Wat is de echte strategy performance? (first_hit volgorde)

Dit is de **meest kritische meting**. Zonder volgorde overschat je performance.

```sql
SELECT
    first_hit,
    COUNT(*) AS n,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct,
    ROUND(AVG(best_exit_pct), 2) AS avg_best_exit
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
GROUP BY first_hit ORDER BY n DESC;
```

**Netto EV berekening** (na fees + slippage):

```sql
SELECT
    ROUND(AVG(
        CASE
            WHEN o.first_hit = 'TP1'  THEN 1.2 - 0.50  -- TP1 bruto - round-trip fee
            WHEN o.first_hit = 'TP2'  THEN 2.5 - 0.50
            WHEN o.first_hit = 'STOP' THEN -1.5 - 0.50 -- stop bruto - fee
            ELSE o.best_exit_pct - 0.50                 -- timeout: beste prijs - fee
        END
    ), 3) AS avg_net_ev_pct,
    COUNT(*) AS n
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL;
```

Noot: gebruik `slippage_100eur` uit `signals` voor meer precieze slippage per signaal.

**Breakeven TP1-first rate** (exclusief fees):
$$\text{winrate}_{\min} = \frac{|\text{stop}|}{\text{TP1} + |\text{stop}|} = \frac{1.5}{1.2 + 1.5} \approx 56\%$$

Met 0.50% round-trip fees (fee verlaagt netto winst, verhoogt netto verlies):
$$\text{winrate}_{\min} = \frac{|\text{stop}| + \text{fee}}{\text{TP1} - \text{fee} + |\text{stop}| + \text{fee}} = \frac{2.0}{0.7 + 2.0} \approx 74\%$$

**Alarmbel**: `TP1-first rate < 65%` → netto EV negatief bij huidige fees. Streven: ≥ 74% voor breakeven.

---

### 2B. Score calibratie (met `ELSE` correctie)

```sql
SELECT
    CASE
        WHEN s.score >= 0.90 THEN '>=0.90'
        WHEN s.score >= 0.85 THEN '0.85-0.90'
        WHEN s.score >= 0.80 THEN '0.80-0.85'
        ELSE '<0.80'
    END AS score_bucket,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit = 'TP1' OR o.first_hit = 'TP2' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
GROUP BY score_bucket ORDER BY score_bucket DESC;
```

*Buckets met n < 15: markeer als "onvoldoende data", trek geen conclusies.*

**Verwachting**: Hogere score → hogere TP-first rate. Als dit patroon ontbreekt → scorer weights herzien.

---

### 2C. WATCH analyse: entry kwaliteit vs. BUY_NOW

Twee aparte vragen:

**Vraag 1**: Wordt WATCH gevolgd door BUY_NOW (early warning waarde)?

```sql
SELECT
    w.exchange, w.trading_pair,
    ROUND((b.timestamp - w.timestamp) / 60.0, 1) AS minutes_between,
    ROUND((b.price - w.price) * 100.0 / w.price, 2) AS price_move_pct,
    ow.best_exit_pct AS watch_best_exit,
    ob.best_exit_pct AS buy_now_best_exit,
    ob.first_hit AS buy_now_first_hit
FROM signals w
JOIN signals b ON w.exchange = b.exchange AND w.trading_pair = b.trading_pair
    AND b.signal_label = 'BUY_NOW'
    AND b.timestamp BETWEEN w.timestamp AND w.timestamp + 1800
LEFT JOIN signal_outcomes ow ON w.id = ow.signal_id
LEFT JOIN signal_outcomes ob ON b.id = ob.signal_id
WHERE w.signal_label = 'WATCH'
ORDER BY minutes_between;
```

**Vraag 2**: Is WATCH-entry zelf al beter dan wachten op BUY_NOW?

```sql
SELECT
    ROUND(AVG(o.best_exit_pct), 2) AS avg_watch_best_exit,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_from_watch_pct,
    COUNT(*) AS n
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'WATCH' AND o.evaluated_at IS NOT NULL;
```

**Verwachting**: Als WATCH ≥ 3% eerder komt dan BUY_NOW en `best_exit_pct` vergelijkbaar is → WATCH is de betere entry. Dan verschuiven we focus naar WATCH-triggered execution.

---

### 2D. Event-level deduplicatie

**Probleem**: Dezelfde coin kan in 10 minuten 3–5 BUY_NOW signalen geven (één momentum-event). Zonder deduplicatie vertekent één sterke move je statistieken.

**Definitie**: één event = zelfde exchange + trading_pair, signalen binnen 30 minuten van elkaar.

```sql
WITH events AS (
    SELECT
        exchange, trading_pair, signal_label,
        MIN(id) AS first_signal_id,
        COUNT(*) AS signals_in_event,
        MIN(timestamp) AS event_start_ts
    FROM signals
    WHERE signal_label IN ('BUY_NOW', 'WATCH')
    GROUP BY exchange, trading_pair,
             CAST(timestamp / 1800 AS INTEGER)  -- 30-min window bucket
)
SELECT
    e.exchange, e.trading_pair, e.signal_label,
    e.signals_in_event,
    o.first_hit, o.best_exit_pct, o.worst_drawdown_pct
FROM events e
JOIN signal_outcomes o ON e.first_signal_id = o.signal_id
WHERE o.evaluated_at IS NOT NULL
ORDER BY e.event_start_ts;
```

**Rapporteer naast alle signalen ook**: event-level TP-first rate, event-level EV.

Als event-level performance significant lager is dan signal-level → herhalende signalen vertekenen de analyse en moeten gewogen worden.

---

### 2E. TOO_LATE validatie (geautomatiseerd)

TOO_LATE signals krijgen nu ook outcomes, zodat we niet handmatig charts hoeven te bekijken.

```sql
SELECT
    COUNT(*) AS n,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
    ROUND(AVG(o.worst_drawdown_pct), 2) AS avg_dd,
    ROUND(SUM(CASE WHEN o.first_hit = 'TP1' OR o.first_hit = 'TP2' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS would_have_tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS would_have_stop_first_pct
FROM signals s
JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'TOO_LATE' AND o.evaluated_at IS NOT NULL;
```

**Beslissing**:
- TOO_LATE TP-first > 50% → filter is te streng, drempel verhogen
- TOO_LATE stop-first > 40% → filter werkt correct, drempel bewaren of verlagen

---

### 2F. Δ15m bucket analyse (filter calibratie)

```sql
SELECT
    CASE
        WHEN s.price_change_15m_pct < 2.5 THEN '<2.5%'
        WHEN s.price_change_15m_pct < 4.0 THEN '2.5-4.0%'
        WHEN s.price_change_15m_pct < 5.5 THEN '4.0-5.5%'
        WHEN s.price_change_15m_pct < 6.0 THEN '5.5-6.0%'
        ELSE '>=6.0% (TOO_LATE zone)'
    END AS d15_bucket,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label IN ('BUY_NOW', 'WATCH', 'TOO_LATE') AND o.evaluated_at IS NOT NULL
GROUP BY d15_bucket ORDER BY d15_bucket;
```

Geeft direct antwoord op: is `too_late_delta_15m_pct: 6.0%` de juiste grens?

---

### 2G. Volume ratio analyse

```sql
SELECT
    CASE
        WHEN s.volume_ratio < 2.0 THEN '<2x'
        WHEN s.volume_ratio < 3.0 THEN '2-3x'
        WHEN s.volume_ratio < 5.0 THEN '3-5x'
        ELSE '>=5x'
    END AS vol_bucket,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label IN ('BUY_NOW', 'WATCH') AND o.evaluated_at IS NOT NULL
GROUP BY vol_bucket;
```

Mogelijke uitkomst: ≥5x volume is blow-off top → slechtere performance. Dan `max_volume_ratio` toevoegen als filter.

---

### 2H. Spread analyse

```sql
SELECT
    CASE
        WHEN s.spread_pct < 0.10 THEN '<0.10%'
        WHEN s.spread_pct < 0.20 THEN '0.10-0.20%'
        WHEN s.spread_pct < 0.30 THEN '0.20-0.30%'
        ELSE '>=0.30%'
    END AS spread_bucket,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
GROUP BY spread_bucket;
```

Als hogere spread → slechtere performance: `max_spread_pct` aanscherpen van 0.30% naar 0.20%.

---

### 2I. Exchange performance

```sql
SELECT s.exchange,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
GROUP BY s.exchange ORDER BY tp_first_pct DESC;
```

*Min. n = 20 per exchange voor conclusies.*

---

### 2J. Preselection bucket kwaliteit

```sql
SELECT
    JSON_EXTRACT(s.preselection_breakdown, '$.selected_bucket') AS bucket,
    COUNT(*) AS n,
    ROUND(AVG(s.preselection_score), 3) AS avg_pre_score,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
    AND s.preselection_breakdown IS NOT NULL
GROUP BY bucket;
```

---

### 2K. Market regime per dag

```sql
SELECT
    date(s.timestamp, 'unixepoch') AS dag,
    COUNT(*) AS n,
    ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_first_pct,
    ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_first_pct,
    ROUND(AVG(o.best_exit_pct), 2) AS avg_best
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
GROUP BY dag ORDER BY dag;
```

**Doel**: Detecteer of één slechte dag de hele analyse bepaalt. Als ja → voorzichtig met conclusies, meer data nodig.

---

### 2L. Slechtste signalen (filter tuning)

```sql
SELECT s.trading_pair, s.exchange, s.score,
    s.price_change_5m_pct, s.price_change_15m_pct, s.volume_ratio, s.spread_pct,
    o.first_hit, o.stop_hit_at_seconds, o.best_exit_pct, o.worst_drawdown_pct
FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
WHERE s.signal_label = 'BUY_NOW'
    AND o.evaluated_at IS NOT NULL
    AND o.first_hit = 'STOP'
ORDER BY o.worst_drawdown_pct ASC
LIMIT 20;
```

Patroon zoeken: zelfde exchange? Hoge spread? Hoge Δ15m? Lage volumeratio?

---

## 3. Hoe voeren we de analyse uit

**Stappenplan**:

1. **Wacht tot service ≥ 14 dagen draait** (minimaal 100 BUY_NOW outcomes)
2. **WAL checkpoint** voor accurate data:
   ```bash
   python3 -c "import sqlite3; conn=sqlite3.connect('data/momentum_signals.sqlite'); conn.execute('PRAGMA wal_checkpoint(TRUNCATE)'); conn.commit()"
   ```
3. **Analysescript draaien**:
   ```bash
   source ~/.venvs/bot/bin/activate
   python -m multi_coin_grid_pro.analysis.analyze_signal_outcomes --days 14
   ```
4. **Altijd rapporteren**: n per segment — buckets met n < 15 zijn indicatief, geen harde conclusies
5. **Altijd twee views**: signal-level én event-level (deduplicatie)
6. **Beslissingen vastleggen** met bewijs

---

## 4. Minimale n voor betrouwbare conclusies

| Analyse | Minimum n | Anders |
|---|---|---|
| TP1-first rate overall | 50 BUY_NOW | wacht langer |
| Per exchange | 20 per exchange | indicatief |
| Per score bucket | 15 per bucket | indicatief |
| Preselection bucket | 10 per bucket | indicatief |
| WATCH entry kwaliteit | 30 WATCH outcomes | indicatief |
| TOO_LATE validatie | 30 TOO_LATE outcomes | indicatief |
| Per dag (regime) | 5 per dag | trend zichtbaar |

---

## 5. Verwachte uitkomsten en beslissingen

| Scenario | Conclusie | Actie |
|---|---|---|
| TP1-first ≥ 55%, netto EV > 0% | Signaal veelbelovend | Paper execution bot starten |
| TP1-first 45–55%, netto EV ≈ 0% | Matig, marginaal | Filters aanscherpen, meer data |
| TP1-first < 45% of stop-first > 35% | Onbetrouwbaar | Geen execution, scorer herzien |
| Hogere score = betere first_hit | Score heeft waarde | Threshold optimaliseren |
| Score heeft geen patroon | Score heeft weinig waarde | Weights herzien |
| WATCH-entry beter dan BUY_NOW | BUY_NOW komt te laat | WATCH als entry-trigger onderzoeken |
| TOO_LATE TP-first > 50% | Filter te streng | Drempel verhogen |
| TOO_LATE stop-first > 40% | Filter werkt correct | Drempel behouden/verlagen |
| Volume ≥5x slechter | Blow-off top effect | Max volume ratio filter toevoegen |
| Spread ≥0.20% slechter | Spread te hoog | max_spread_pct verlagen |
| Één dag domineert resultaat | Regime-gevoelig | Meer data nodig, niet generaliseren |

---

## 6. Wat we NIET besluiten op basis van 2 weken

- **Live trading activeren**: daarvoor willen we ≥ 4 weken + aparte paper trade validatie
- **Kapitaal allocatie**: signal performance ≠ strategy performance (ordertype, timing, fees variëren per markt)
- **Exchanges definitief uitzetten**: te weinig data per exchange voor harde conclusies
- **Segmenten met n < 15**: indicatief, geen parameterwijzigingen op gebaseerd

---

*Opgesteld: 2026-06-06 | v2: first_hit volgorde, event-deduplicatie, netto EV, TOO_LATE, regime-analyse toegevoegd*
