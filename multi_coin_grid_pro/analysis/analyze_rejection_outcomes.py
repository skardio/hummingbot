#!/usr/bin/env python3
"""analyze_rejection_outcomes.py — Welke rejection reason had goede kansen? (US-502/602).

Vergelijkt de prijs van afgewezen candidates na 5m en 15m met de prijs op
het moment van afwijzing — op basis van de signalen die de scanner zelf
heeft opgeslagen.

Includes a TOO_LATE sectie (US-602): toont of de TOO_LATE grens te streng of
te soepel is door de werkelijke prijsontwikkeling na afwijzing te analyseren.

Gebruik:
    python -m multi_coin_grid_pro.analysis.analyze_rejection_outcomes
    python -m multi_coin_grid_pro.analysis.analyze_rejection_outcomes --since 2026-06-01
    python -m multi_coin_grid_pro.analysis.analyze_rejection_outcomes --min-count 10
    python -m multi_coin_grid_pro.analysis.analyze_rejection_outcomes --too-late-window 15

Kalibratie (US-602 TOO_LATE): Als too_late gem% positief is, worden winstgevende
moves weggefilterd. Overweeg too_late_delta_15m_pct te verhogen.
"""
import argparse
import sqlite3
import sys
from datetime import datetime


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rejection reason outcome analysis (US-502)")
    p.add_argument("--db", default="data/momentum_signals.sqlite", help="SQLite database path")
    p.add_argument("--since", help="Analyse vanaf datum YYYY-MM-DD")
    p.add_argument("--min-count", type=int, default=5,
                   help="Minimum aantal afwijzingen voor een reason om getoond te worden")
    p.add_argument("--window", type=int, default=5,
                   help="Tijdvenster in minuten om prijsontwikkeling te meten (default: 5)")
    p.add_argument("--too-late-window", type=int, default=15,
                   help="Extra tijdvenster in minuten voor TOO_LATE sectie (default: 15)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    window_sec = args.window * 60
    slack = 60  # ± 60s around the target window

    try:
        conn = sqlite3.connect(args.db)
    except Exception as exc:
        print(f"Kan database niet openen: {exc}", file=sys.stderr)
        sys.exit(1)

    where = ["r.accepted = 0", "r.rejection_reason IS NOT NULL", "r.price > 0"]
    params: list = []
    if args.since:
        ts = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        where.append("r.timestamp >= ?")
        params.append(ts)

    where_sql = " AND ".join(where)

    # For each rejection, find the price ~window_sec later from any signal for the same pair
    rows = conn.execute(f"""
        SELECT
            r.rejection_reason,
            COUNT(*) AS n_rejections,
            COUNT(later.id) AS n_with_followup,
            ROUND(AVG((later.price - r.price) / r.price * 100), 3) AS avg_price_change_pct,
            ROUND(MIN((later.price - r.price) / r.price * 100), 3) AS min_price_change_pct,
            ROUND(MAX((later.price - r.price) / r.price * 100), 3) AS max_price_change_pct,
            ROUND(100.0 * SUM(CASE WHEN later.price > r.price * 1.005 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(later.id), 0), 1) AS pct_rose_05pct
        FROM signals r
        LEFT JOIN signals later ON later.exchange = r.exchange
            AND later.trading_pair = r.trading_pair
            AND later.timestamp BETWEEN r.timestamp + ? AND r.timestamp + ?
        WHERE {where_sql}
        GROUP BY r.rejection_reason
        HAVING n_rejections >= ?
        ORDER BY avg_price_change_pct DESC
    """, [window_sec - slack, window_sec + slack] + params + [args.min_count]).fetchall()  # noqa: S608

    if not rows:
        print(f"\nGeen data gevonden (min-count={args.min_count}, window={args.window}m).")
        print("Wacht tot de service meer data heeft verzameld.")
        return

    title = f"\nRejection reason analyse — prijs {args.window}m na afwijzing"
    print(title)
    print("=" * len(title))
    hdr = (f"\n{'Reason':<35} {'N':>6} {'Met-follow':>10} "
           f"{'Gem%':>8} {'Min%':>8} {'Max%':>8} {'>0.5%':>7}")
    print(hdr)
    print("-" * len(hdr.rstrip()))

    for reason, n_rej, n_fol, avg_pct, min_pct, max_pct, pct_rose in rows:
        print(
            f"{reason:<35} {n_rej:>6} {(n_fol or 0):>10} "
            f"{(avg_pct or 0):>+7.2f}% {(min_pct or 0):>+7.2f}% "
            f"{(max_pct or 0):>+7.2f}% {(pct_rose or 0):>6.1f}%"
        )

    print("\nInterpretatie:")
    print("  Gem% > 0  → pair steeg gemiddeld na afwijzing (misschien filter te strikt)")
    print("  Gem% < 0  → pair daalde gemiddeld (filter terecht)")
    print("  >0.5%     → % van gevallen waarbij prijs >0.5% steeg (false negatives)")

    # --- TOO_LATE sectie (US-602 kalibratie) ---
    tl_window_sec = args.too_late_window * 60
    tl_where = ["r.signal_label = 'TOO_LATE'", "r.accepted = 1", "r.price > 0"]
    tl_params: list = []
    if args.since:
        ts = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        tl_where.append("r.timestamp >= ?")
        tl_params.append(ts)
    tl_where_sql = " AND ".join(tl_where)

    tl_rows = conn.execute(f"""
        SELECT
            COUNT(*) AS n,
            COUNT(f5.id) AS n_with_5m,
            COUNT(f15.id) AS n_with_15m,
            ROUND(AVG((f5.price - r.price) / r.price * 100), 3) AS avg_5m,
            ROUND(AVG((f15.price - r.price) / r.price * 100), 3) AS avg_15m,
            ROUND(100.0 * SUM(CASE WHEN f5.price > r.price THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(f5.id), 0), 1) AS pct_rose_5m,
            ROUND(100.0 * SUM(CASE WHEN f15.price > r.price THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(f15.id), 0), 1) AS pct_rose_15m
        FROM signals r
        LEFT JOIN signals f5 ON f5.exchange = r.exchange
            AND f5.trading_pair = r.trading_pair
            AND f5.timestamp BETWEEN r.timestamp + 240 AND r.timestamp + 360
        LEFT JOIN signals f15 ON f15.exchange = r.exchange
            AND f15.trading_pair = r.trading_pair
            AND f15.timestamp BETWEEN r.timestamp + {tl_window_sec - 60}
                                   AND r.timestamp + {tl_window_sec + 60}
        WHERE {tl_where_sql}
    """, tl_params).fetchone()  # noqa: S608

    if tl_rows and tl_rows[0]:
        n_tl, n5, n15, avg5, avg15, rose5, rose15 = tl_rows
        print(f"\n--- TOO_LATE kalibratie (US-602) — {args.too_late_window}m venster ---")
        print(f"  Afgewezen als TOO_LATE: {n_tl} signalen")
        if n5:
            print(f"  Gem. prijs 5m later:  {(avg5 or 0):+.2f}%  ({n5} met follow-up, {(rose5 or 0):.0f}% steeg)")
        if n15:
            print(f"  Gem. prijs {args.too_late_window}m later: {(avg15 or 0):+.2f}%  ({n15} met follow-up, {(rose15 or 0):.0f}% steeg)")
        print("")
        if avg5 is not None and avg5 > 1.0:
            print("  ADVIES: TOO_LATE filter filtert winstgevende moves weg.")
            print("          Overweeg too_late_delta_15m_pct te verhogen.")
        elif avg5 is not None and avg5 < -0.5:
            print("  ADVIES: TOO_LATE filter werkt goed — pairs daalden na afwijzing.")
        else:
            print("  ADVIES: Resultaat mixed — meer data nodig voor betrouwbare conclusie.")

    conn.close()


if __name__ == "__main__":
    main()
