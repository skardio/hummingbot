# Momentum Signal Service — Runbook

Praktische referentie: starten, stoppen, resultaten inzien.

---

## Starten (stil, op de achtergrond)

```bash
cd /home/mo/repos/hummingbot
source .venv/bin/activate

python -m multi_coin_grid_pro.services.momentum_signal_service \
  --config multi_coin_grid_pro/config/momentum_signal_service.yaml \
  --log-level WARNING \
  >> data/momentum_service.log 2>&1 &

echo $! > data/momentum_service.pid
echo "Gestart met PID $(cat data/momentum_service.pid)"
```

## Stoppen

```bash
kill $(cat data/momentum_service.pid) && rm data/momentum_service.pid
```

## Status checken (draait het nog?)

```bash
kill -0 $(cat data/momentum_service.pid) 2>/dev/null && echo "actief" || echo "gestopt"
```

---

## Resultaten inzien

### Laatste scan — JSON (meest recent)

```bash
python -c "
import json
d = json.load(open('data/momentum_signals.json'))
import datetime
ts = datetime.datetime.fromtimestamp(d.get('timestamp', 0))
print(f'Scan: {d.get(\"scan_id\")}  ({ts:%Y-%m-%d %H:%M})')
for s in d.get('top_signals', []):
    print(f'  {s[\"rank\"]}. {s[\"exchange\"]:8}  {s[\"trading_pair\"]:14}  score={s[\"score\"]:.2f}')
"
```

### Alle geaccepteerde signalen van de afgelopen 12 uur — SQLite

```bash
sqlite3 data/momentum_signals.sqlite "
SELECT datetime(timestamp,'unixepoch','localtime') AS ts,
       exchange, trading_pair, score, rank
FROM   signals
WHERE  accepted = 1
  AND  timestamp > strftime('%s','now','-12 hours')
ORDER  BY timestamp DESC, rank;
"
```

### Top-5 beste signalen van gisteren

```bash
sqlite3 data/momentum_signals.sqlite "
SELECT datetime(timestamp,'unixepoch','localtime') AS ts,
       exchange, trading_pair, score, rank
FROM   signals
WHERE  accepted = 1
  AND  date(timestamp,'unixepoch','localtime') = date('now','localtime','-1 day')
ORDER  BY score DESC
LIMIT  5;
"
```

### Hoeveel scans zijn er gedraaid vannacht?

```bash
sqlite3 data/momentum_signals.sqlite "
SELECT COUNT(DISTINCT scan_id) AS scans,
       datetime(MIN(timestamp),'unixepoch','localtime') AS eerste,
       datetime(MAX(timestamp),'unixepoch','localtime') AS laatste
FROM   signals
WHERE  timestamp > strftime('%s','now','-12 hours');
"
```

### Welke pairs zijn het vaakst geaccepteerd?

```bash
sqlite3 data/momentum_signals.sqlite "
SELECT exchange, trading_pair, COUNT(*) AS keer, ROUND(AVG(score),3) AS gem_score
FROM   signals
WHERE  accepted = 1
  AND  timestamp > strftime('%s','now','-24 hours')
GROUP  BY exchange, trading_pair
ORDER  BY keer DESC
LIMIT  10;
"
```

### Wat waren de afwijzingsredenen?

```bash
sqlite3 data/momentum_signals.sqlite "
SELECT rejection_reason, COUNT(*) AS n
FROM   signals
WHERE  accepted = 0
  AND  timestamp > strftime('%s','now','-12 hours')
GROUP  BY rejection_reason
ORDER  BY n DESC;
"
```

### Errors/warnings in de logfile

```bash
grep -E "ERROR|WARNING" data/momentum_service.log | tail -30
```

---

## Databronnen

| Bestand                          | Inhoud                                    | Overschreven? |
|----------------------------------|-------------------------------------------|---------------|
| `data/momentum_signals.sqlite`   | Alle historische scans (SQLite)           | Nee, groeit   |
| `data/momentum_signals.json`     | Laatste scan (JSON snapshot)              | Ja, elke scan |
| `data/momentum_service.log`      | Warnings/errors van de service            | Nee, groeit   |
| `data/momentum_service.pid`      | PID van het achtergrondproces             | Per start     |

`signals` wordt na 7 dagen gepurged (`SignalStore.purge_old`). Definitieve BUY_NOW-outcomes
staan permanent in `buy_now_shadow_archive` (zelfde DB), zie hieronder.

---

## v5 shadow-archief en schone cohort

- **Archive-write:** `OutcomeTracker` schrijft bij de definitieve evaluatie (≥30 min) van elk
  BUY_NOW-signaal één rij naar `buy_now_shadow_archive`, in dezelfde SQLite-transactie als de
  outcome-update. Idempotent (`signal_id` PK, `INSERT OR IGNORE`); rijen worden nooit herschreven.
- **Recovery:** bij tracker-start en vóór elke `purge_old` archiveert een backfill alles wat nog
  ontbreekt. Faalt die, dan wordt niets gepurged (fail closed). BUY_NOW die nooit geëvalueerd
  konden worden (>45 min, geen outcome) krijgen `archive_status='UNEVALUATED'` → gat blijft zichtbaar.
- **T+30 exit:** `exit_30m_price/pct/at_seconds` = prijs van de eerste tracker-tick op/na 30 min
  (nooit max/min). Tolerantie: [1800, 2400) s door de 40-min grace; typisch 1800–1900 s.
  Precisie: `exit_30m_at_seconds` = tracker-tick (einde scan) − signaal-`timestamp` (start scan);
  de prijs zelf is tijdens die scan opgehaald, dus de werkelijke prijs-leeftijd ligt in
  [at_seconds − scanduur, at_seconds] (scanduur ~80 s). Dit geldt identiek voor alle `*_hit_at_seconds`
  en is bewust niet aangepast (zou CURRENT-timing wijzigen).
- **Historische 69 (pre-fix):** het 30m-venster wordt in de tracker uitsluitend op de finale
  evaluatietick geschreven (daarna niet meer pending), dus `max_price_30m` = exit-prijs en
  `evaluated_at − timestamp` = exit-tijd. Geborgd door
  `test_max_price_30m_written_once_on_evaluation_tick`. Voor gepurgde signalen is de signaaltijd
  alleen tot op de seconde bekend (ledger `signal_ts`).
- **v5_pass** wordt bij archiveren berekend met de frozen v5-SQL (`momentum_shadow_archive.V5_SQL`).
- **Cohort:** de eerste servicestart met deze code legt `cohort_start_ts` + frozen definitie vast in
  `shadow_archive_meta`. `shadow_scan_coverage` telt tracker-updates per uur (downtime-detectie).

```bash
python track_v5_cohort.py             # integriteit + CURRENT vs WIDE (bruto/netto)
python track_v5_cohort.py --legacy69  # dry-run oude 69 shadow-trades met echte T+30
```

`track_v5_paper.py` is legacy: TIMEOUT = MFE − 0.5 en STOP = vast −2.00 (methodologisch onjuist).

---

## CLI opties

```
--config PATH           YAML config (verplicht)
--db-path PATH          SQLite pad (default: data/momentum_signals.sqlite)
--snapshot-path PATH    JSON pad    (default: data/momentum_signals.json)
--log-level LEVEL       DEBUG / INFO / WARNING / ERROR (default: INFO)
--debug-pair EX:PAIR    Eenmalige debug fetch, bijv. okx:SOL-USDC
```
