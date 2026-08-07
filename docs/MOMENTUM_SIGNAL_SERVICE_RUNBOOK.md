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

---

## CLI opties

```
--config PATH           YAML config (verplicht)
--db-path PATH          SQLite pad (default: data/momentum_signals.sqlite)
--snapshot-path PATH    JSON pad    (default: data/momentum_signals.json)
--log-level LEVEL       DEBUG / INFO / WARNING / ERROR (default: INFO)
--debug-pair EX:PAIR    Eenmalige debug fetch, bijv. okx:SOL-USDC
```
