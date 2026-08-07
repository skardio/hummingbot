#!/usr/bin/env python3
"""
Analyse geaccepteerde momentum-signalen: paper-trading resultaten.

Voor elk geaccepteerd signaal zoekt dit script de dichtstbijzijnde prijs
op +15m, +30m, +60m en +120m in de signals-tabel (dezelfde bron die de
scanner al schrijft — geen externe API nodig).

Gebruik:
    python analyze_momentum_signals.py
    python analyze_momentum_signals.py --since 2026-06-03  # datum filter
    python analyze_momentum_signals.py --days 3            # laatste N dagen
"""

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path("data/momentum_signals.sqlite")
HORIZONS_SEC = [15 * 60, 30 * 60, 60 * 60, 120 * 60]
HORIZON_LABELS = ["15m", "30m", "1h", "2h"]
# Een prijs-lookup is geldig als de gevonden scan ≤ dit aantal seconden afwijkt
LOOKUP_TOLERANCE_SEC = 120


def find_nearest_price(cur: sqlite3.Cursor, pair: str, exchange: str,
                       target_ts: float) -> float | None:
    """Zoek de prijs in de signals-tabel die het dichtst bij target_ts zit."""
    cur.execute(
        """
        SELECT price, ABS(timestamp - ?) AS diff
        FROM signals
        WHERE trading_pair = ? AND exchange = ?
          AND timestamp BETWEEN ? AND ?
        ORDER BY diff
        LIMIT 1
        """,
        (target_ts, pair, exchange,
         target_ts - LOOKUP_TOLERANCE_SEC,
         target_ts + LOOKUP_TOLERANCE_SEC),
    )
    row = cur.fetchone()
    return row[0] if row else None


def pct(entry: float, later: float | None) -> str:
    if later is None:
        return "    n/a"
    change = (later - entry) / entry * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:5.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="Datum vanaf (YYYY-MM-DD), UTC")
    parser.add_argument("--days", type=int, default=7,
                        help="Laatste N dagen (default: 7)")
    parser.add_argument("--exchange", help="Filter op exchange (bijv. bitvavo)")
    parser.add_argument("--pair", help="Filter op pair (bijv. SAGA-EUR)")
    args = parser.parse_args()

    if args.since:
        cutoff_ts = datetime.fromisoformat(args.since).replace(
            tzinfo=timezone.utc).timestamp()
    else:
        cutoff_ts = (datetime.now(timezone.utc)
                     - timedelta(days=args.days)).timestamp()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Haal geaccepteerde signalen op — één per (pair, exchange, scan-window)
    # Door GROUP BY voorkomen we dubbele entries als hetzelfde paar meermaals
    # achter elkaar geaccepteerd wordt in hetzelfde uur.
    where = "WHERE accepted=1 AND timestamp >= ?"
    params: list = [cutoff_ts]
    if args.exchange:
        where += " AND exchange = ?"
        params.append(args.exchange)
    if args.pair:
        where += " AND trading_pair = ?"
        params.append(args.pair)

    cur.execute(
        f"""
        SELECT id, trading_pair, exchange, timestamp, price, score,
               volume_ratio, price_change_5m_pct, price_change_15m_pct,
               score_breakdown
        FROM signals
        {where}
        ORDER BY timestamp DESC
        """,
        params,
    )
    rows = cur.fetchall()

    if not rows:
        print("Geen geaccepteerde signalen gevonden in de opgegeven periode.")
        return

    header = (f"{'Tijdstip (UTC)':<20} {'Pair':<14} {'Exch':<8} "
              f"{'Score':>5} {'VolR':>5} {'Δ15m':>6}  "
              + "  ".join(f"{lb:>7}" for lb in HORIZON_LABELS))
    print(header)
    print("-" * len(header))

    results = []
    for r in rows:
        later_prices = [
            find_nearest_price(cur, r["trading_pair"], r["exchange"],
                               r["timestamp"] + h)
            for h in HORIZONS_SEC
        ]
        ts_str = datetime.fromtimestamp(
            r["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

        line = (f"{ts_str:<20} {r['trading_pair']:<14} {r['exchange']:<8} "
                f"{r['score']:5.3f} {(r['volume_ratio'] or 0):5.1f}x "
                f"{(r['price_change_15m_pct'] or 0):5.1f}%  "
                + "  ".join(pct(r["price"], p) for p in later_prices))
        print(line)

        results.append({
            "pair": r["trading_pair"],
            "exchange": r["exchange"],
            "ts": ts_str,
            "entry_price": r["price"],
            "score": r["score"],
            "volume_ratio": r["volume_ratio"],
            "returns": {
                lb: ((lp - r["price"]) / r["price"] * 100
                     if lp else None)
                for lb, lp in zip(HORIZON_LABELS, later_prices)
            },
        })

    # Samenvatting per horizon
    print()
    print("=== Samenvatting (gemiddeld rendement per horizon) ===")
    for i, lb in enumerate(HORIZON_LABELS):
        valid = [r["returns"][lb] for r in results if r["returns"][lb] is not None]
        if valid:
            avg = sum(valid) / len(valid)
            positive = sum(1 for v in valid if v > 0)
            print(f"  {lb}: gemiddeld {avg:+.2f}%  |  "
                  f"positief: {positive}/{len(valid)} signalen")
        else:
            print(f"  {lb}: nog geen data (te vroeg na signaal)")

    # Score_breakdown van de meest recente geaccepteerde signalen
    print()
    print("=== Score breakdown (meest recente 3 signalen) ===")
    for r in rows[:3]:
        bd = json.loads(r["score_breakdown"]) if r["score_breakdown"] else {}
        ts_str = datetime.fromtimestamp(
            r["timestamp"], tz=timezone.utc).strftime("%H:%M UTC")
        print(f"  {r['trading_pair']} @ {ts_str} (score={r['score']:.3f})")
        for k, v in bd.items():
            bar = "█" * int(v * 20)
            print(f"    {k:<18} {v:.3f}  {bar}")

    con.close()


if __name__ == "__main__":
    main()
