"""Signal outcome analyse — uitvoering van SIGNAL_ANALYSIS_PLAN_2WK.md (§2A-§2L).

Gebruik:
    source ~/.venvs/bot/bin/activate
    python -m multi_coin_grid_pro.analysis.analyze_signal_outcomes [--days N] [--db PATH]

Analyses:
    §2A  first_hit strategie performance + netto EV
    §2B  Score calibratie per bucket
    §2C  WATCH analyse (early-warning + entry kwaliteit)
    §2D  Event-level deduplicatie (30-min window)
    §2E  TOO_LATE validatie
    §2F  Δ15m bucket analyse
    §2G  Volume ratio analyse
    §2H  Spread analyse
    §2I  Exchange performance
    §2J  Preselection bucket kwaliteit
    §2K  Market regime per dag
    §2L  Slechtste signalen (stop-first patronen)
    §2M  Config versies — performance per paramset
    §2N  Marktregime — TP-rate per kwartiel van market_regime_at_signal
    §2O  Entry zone reached — entry kwaliteit en time-to-first-hit stats
    §2P  Paper-test cohort rapport (baseline vs regime/exchange/entry-zone)

Wanneer de first_hit kolom nog ontbreekt (pre-service-restart) worden §2A/§2B/§2E/§2F/§2G
automatisch teruggeval op hit_tp1/hit_tp2/hit_stop als proxy (volgorde onbekend).
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

_DB_DEFAULT = "data/momentum_signals.sqlite"
_SEP = "─" * 72

# Fees + niveaus (percent)
_FEE_PCT = 0.50
_TP1_PCT = 1.2
_TP2_PCT = 2.5
_STOP_PCT = -1.5


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    return conn


def _has_first_hit(conn: sqlite3.Connection) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_outcomes)")}
    return "first_hit" in cols


def _cutoff(days: int) -> float:
    return time.time() - days * 86400 if days > 0 else 0.0


def _n_warn(n: int, minimum: int, label: str) -> str:
    if n < minimum:
        return f"  ⚠  n={n} < min {minimum} voor '{label}' — indicatief, geen harde conclusies"
    return f"  n={n} ✓"


def _header(title: str) -> None:
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


# ---------------------------------------------------------------------------
# §2A — first_hit performance + netto EV
# ---------------------------------------------------------------------------

def analyse_2a_first_hit(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2A  First-hit strategie performance + netto EV")
    has_fh = _has_first_hit(conn)

    if has_fh:
        rows = conn.execute("""
            SELECT first_hit,
                   COUNT(*) AS n,
                   ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct,
                   ROUND(AVG(best_exit_pct), 2) AS avg_best_exit
            FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
              AND s.timestamp > ?
            GROUP BY first_hit ORDER BY n DESC
        """, (cutoff,)).fetchall()

        total = sum(r["n"] for r in rows)
        print(_n_warn(total, 50, "TP1-first rate overall"))
        print()
        print(f"  {'first_hit':10s}  {'n':>5s}  {'%':>6s}  {'avg_best%':>10s}")
        print("  " + "-" * 40)
        for r in rows:
            print(f"  {str(r['first_hit']):10s}  {r['n']:>5d}  {r['pct']:>5.1f}%  "
                  f"{r['avg_best_exit']:>+9.2f}%")

        ev = conn.execute("""
            SELECT ROUND(AVG(
                CASE
                    WHEN o.first_hit = 'TP1'  THEN ? - ?
                    WHEN o.first_hit = 'TP2'  THEN ? - ?
                    WHEN o.first_hit = 'STOP' THEN ? - ?
                    ELSE o.best_exit_pct - ?
                END
            ), 3) AS avg_net_ev_pct
            FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
              AND s.timestamp > ?
        """, (_TP1_PCT, _FEE_PCT, _TP2_PCT, _FEE_PCT, _STOP_PCT, _FEE_PCT,
              _FEE_PCT, cutoff)).fetchone()

        tp1_n = next((r["n"] for r in rows if r["first_hit"] == "TP1"), 0)
        tp1_rate = tp1_n / total * 100 if total else 0.0
        breakeven_fee = (_FEE_PCT + abs(_STOP_PCT)) / (_TP1_PCT + _FEE_PCT + abs(_STOP_PCT))

        print()
        print(f"  Netto EV (incl. {_FEE_PCT}% fees)  : {ev['avg_net_ev_pct']:+.3f}%")
        print(f"  TP1-first rate               : {tp1_rate:.1f}%")
        print(f"  Breakeven TP1-rate (in fees) : {breakeven_fee * 100:.1f}%")
        if tp1_rate < 55:
            print("  ⚠  TP1-first rate < 55% — netto EV mogelijk negatief")
        else:
            print("  ✓  TP1-first rate ≥ 55%")
    else:
        print("  ℹ  first_hit kolom niet aanwezig — proxy via hit_tp1/hit_tp2/hit_stop")
        print("     Service-restart vereist voor volledige volgorde-analyse.")
        print()
        r = conn.execute("""
            SELECT COUNT(*) AS n,
                   ROUND(SUM(o.hit_tp1) * 100.0 / COUNT(*), 1) AS tp1_pct,
                   ROUND(SUM(o.hit_tp2) * 100.0 / COUNT(*), 1) AS tp2_pct,
                   ROUND(SUM(o.hit_stop) * 100.0 / COUNT(*), 1) AS stop_pct,
                   ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
                   ROUND(AVG(o.worst_drawdown_pct), 2) AS avg_dd
            FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
              AND s.timestamp > ?
        """, (cutoff,)).fetchone()

        print(_n_warn(r["n"], 50, "TP1 hit rate overall"))
        print()
        print(f"  BUY_NOW outcomes : {r['n']}")
        print(f"  TP1 geraakt      : {r['tp1_pct']}%")
        print(f"  TP2 geraakt      : {r['tp2_pct']}%")
        print(f"  Stop geraakt     : {r['stop_pct']}%")
        print(f"  Gem. best exit   : {r['avg_best']:+.2f}%")
        print(f"  Gem. worst dd    : {r['avg_dd']:+.2f}%")

        be = abs(_STOP_PCT) / (_TP1_PCT + abs(_STOP_PCT))
        print(f"\n  Breakeven TP1-rate (ex fees) : {be * 100:.1f}%")
        if r["tp1_pct"] < 55:
            print("  ⚠  TP1 hit-rate < 55% — kan netto EV negatief zijn (volgorde onbekend)")
        else:
            print("  ✓  TP1 hit-rate ≥ 55%")


# ---------------------------------------------------------------------------
# §2B — Score calibratie
# ---------------------------------------------------------------------------

def analyse_2b_score_calibratie(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2B  Score calibratie per bucket")
    has_fh = _has_first_hit(conn)
    tp_col = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_col = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN s.score >= 0.90 THEN '>=0.90'
                WHEN s.score >= 0.85 THEN '0.85-0.90'
                WHEN s.score >= 0.80 THEN '0.80-0.85'
                ELSE '<0.80'
            END AS score_bucket,
            COUNT(*) AS n,
            ROUND({tp_col} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND({stop_col} * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND s.timestamp > ?
        GROUP BY score_bucket ORDER BY score_bucket DESC
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Bucket':12s}  {'n':>5s}  {tp_label:>10s}  {'Stop%':>7s}  {'avg_best%':>10s}  Min n=15?")
    print("  " + "-" * 62)
    for r in rows:
        ok = "✓" if r["n"] >= 15 else "⚠ n<15"
        print(f"  {r['score_bucket']:12s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  "
              f"{r['stop_pct']:>6.1f}%  {r['avg_best']:>+9.2f}%  {ok}")

    if not has_fh:
        print("\n  ℹ  Proxy-mode: hit-rate ipv first_hit. Volgorde onbekend.")


# ---------------------------------------------------------------------------
# §2C — WATCH analyse
# ---------------------------------------------------------------------------

def analyse_2c_watch(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2C  WATCH analyse")

    fu = conn.execute("""
        SELECT COUNT(DISTINCT w.id) AS n_watch_total,
               COUNT(DISTINCT CASE WHEN b.id IS NOT NULL THEN w.id END) AS n_with_followup
        FROM signals w
        LEFT JOIN signals b ON w.exchange = b.exchange AND w.trading_pair = b.trading_pair
            AND b.signal_label = 'BUY_NOW'
            AND b.timestamp BETWEEN w.timestamp AND w.timestamp + 1800
        WHERE w.signal_label = 'WATCH' AND w.timestamp > ?
    """, (cutoff,)).fetchone()

    n_total = fu["n_watch_total"]
    n_followup = fu["n_with_followup"]
    pct = n_followup / n_total * 100 if n_total else 0.0

    print(f"  WATCH signals totaal           : {n_total}")
    print(f"  Gevolgd door BUY_NOW (<30min)  : {n_followup} ({pct:.1f}%)")
    print(_n_warn(n_total, 30, "WATCH follow-up"))
    if pct > 40:
        print("  ✓  >40% follow-up — waardevolle early warning")
    elif pct > 20:
        print("  ~  20-40% follow-up — beperkte early warning waarde")
    else:
        print("  ⚠  <20% follow-up — WATCH en BUY_NOW grotendeels onafhankelijk")

    timing = conn.execute("""
        SELECT ROUND(AVG((b.timestamp - w.timestamp) / 60.0), 1) AS avg_min,
               ROUND(MIN((b.timestamp - w.timestamp) / 60.0), 1) AS min_min,
               COUNT(*) AS n
        FROM signals w
        JOIN signals b ON w.exchange = b.exchange AND w.trading_pair = b.trading_pair
            AND b.signal_label = 'BUY_NOW'
            AND b.timestamp BETWEEN w.timestamp AND w.timestamp + 1800
        WHERE w.signal_label = 'WATCH' AND w.timestamp > ?
    """, (cutoff,)).fetchone()

    if timing["n"]:
        print(f"\n  Gem. tijd WATCH→BUY_NOW : {timing['avg_min']} min")
        print(f"  Min. tijd WATCH→BUY_NOW : {timing['min_min']} min")

    wq = conn.execute("""
        SELECT COUNT(*) AS n,
               ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
               ROUND(AVG(o.worst_drawdown_pct), 2) AS avg_dd
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'WATCH' AND o.evaluated_at IS NOT NULL
          AND s.timestamp > ?
    """, (cutoff,)).fetchone()

    print(f"\n  WATCH outcomes geëvalueerd     : {wq['n']}")
    if wq["n"]:
        print(f"  Gem. best exit (vs sig price)  : {wq['avg_best']:+.2f}%")
        print(f"  Gem. worst drawdown            : {wq['avg_dd']:+.2f}%")
    print(_n_warn(wq["n"], 30, "WATCH entry kwaliteit"))


# ---------------------------------------------------------------------------
# §2D — Event-level deduplicatie
# ---------------------------------------------------------------------------

def analyse_2d_events(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2D  Event-level deduplicatie (30-min window)")
    has_fh = _has_first_hit(conn)

    ec = conn.execute("""
        SELECT COUNT(*) AS total_signals,
               COUNT(DISTINCT exchange || '|' || trading_pair || '|' ||
                     CAST(CAST(timestamp / 1800 AS INTEGER) AS TEXT)) AS n_events
        FROM signals
        WHERE signal_label IN ('BUY_NOW', 'WATCH') AND timestamp > ?
    """, (cutoff,)).fetchone()

    total = ec["total_signals"]
    n_ev = ec["n_events"]
    print(f"  Totaal signalen (BUY_NOW+WATCH) : {total}")
    print(f"  Unieke events (30-min window)   : {n_ev}")
    if total and n_ev:
        ratio = total / n_ev
        print(f"  Gem. signalen per event         : {ratio:.1f}x")
        if ratio > 2:
            print("  ⚠  Hoge herhaling — event-level analyse vereist voor correcte EV schatting")
        else:
            print("  ✓  Beperkte herhaling")

    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_expr = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    ep = conn.execute(f"""
        WITH events AS (
            SELECT exchange, trading_pair, MIN(id) AS first_signal_id,
                   COUNT(*) AS signals_in_event
            FROM signals
            WHERE signal_label IN ('BUY_NOW', 'WATCH') AND timestamp > ?
            GROUP BY exchange, trading_pair, CAST(timestamp / 1800 AS INTEGER)
        )
        SELECT COUNT(*) AS n_events,
               ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
               ROUND({stop_expr} * 100.0 / COUNT(*), 1) AS stop_pct,
               ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
               ROUND(AVG(e.signals_in_event), 1) AS avg_per_event
        FROM events e
        JOIN signal_outcomes o ON e.first_signal_id = o.signal_id
        WHERE o.evaluated_at IS NOT NULL
    """, (cutoff,)).fetchone()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"\n  Event-level outcomes            : {ep['n_events']}")
    if ep["n_events"]:
        print(f"  Event {tp_label:22s}: {ep['tp_pct']}%")
        print(f"  Event stop%                     : {ep['stop_pct']}%")
        print(f"  Event avg_best                  : {ep['avg_best']:+.2f}%")
        print(f"  Gem. signalen per event         : {ep['avg_per_event']}")


# ---------------------------------------------------------------------------
# §2E — TOO_LATE validatie
# ---------------------------------------------------------------------------

def analyse_2e_too_late(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2E  TOO_LATE validatie")
    has_fh = _has_first_hit(conn)

    n_tot = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE signal_label='TOO_LATE' AND timestamp > ?",
        (cutoff,),
    ).fetchone()[0]
    n_out = conn.execute("""
        SELECT COUNT(*) FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label='TOO_LATE' AND s.timestamp > ? AND o.evaluated_at IS NOT NULL
    """, (cutoff,)).fetchone()[0]

    print(f"  TOO_LATE signalen               : {n_tot}")
    print(f"  Met geëvalueerd outcome         : {n_out}")
    print(_n_warn(n_out, 30, "TOO_LATE validatie"))

    if n_out == 0:
        print("  ℹ  Geen outcomes — service-restart vereist (TOO_LATE tracking is nieuw)")
        rej = conn.execute("""
            SELECT COUNT(*) AS n,
                   ROUND(AVG(price_change_15m_pct), 2) AS avg_d15,
                   ROUND(AVG(price_change_5m_pct), 2) AS avg_d5,
                   ROUND(AVG(score), 3) AS avg_score
            FROM signals WHERE rejection_reason = 'TOO_LATE_EXTENDED_MOVE' AND timestamp > ?
        """, (cutoff,)).fetchone()
        print(f"\n  TOO_LATE_EXTENDED_MOVE (rejected): n={rej['n']}, "
              f"avg_d15={rej['avg_d15']}%, avg_d5={rej['avg_d5']}%, avg_score={rej['avg_score']}")
        return

    if has_fh:
        row = conn.execute("""
            SELECT COUNT(*) AS n,
                   ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
                   ROUND(AVG(o.worst_drawdown_pct), 2) AS avg_dd,
                   ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_pct,
                   ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_pct
            FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'TOO_LATE' AND o.evaluated_at IS NOT NULL AND s.timestamp > ?
        """, (cutoff,)).fetchone()
    else:
        row = conn.execute("""
            SELECT COUNT(*) AS n,
                   ROUND(AVG(o.best_exit_pct), 2) AS avg_best,
                   ROUND(AVG(o.worst_drawdown_pct), 2) AS avg_dd,
                   ROUND(SUM(o.hit_tp1) * 100.0 / COUNT(*), 1) AS tp_pct,
                   ROUND(SUM(o.hit_stop) * 100.0 / COUNT(*), 1) AS stop_pct
            FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'TOO_LATE' AND o.evaluated_at IS NOT NULL AND s.timestamp > ?
        """, (cutoff,)).fetchone()

    print(f"\n  TP-hit%                         : {row['tp_pct']}%")
    print(f"  Stop-hit%                       : {row['stop_pct']}%")
    print(f"  Gem. best exit                  : {row['avg_best']:+.2f}%")
    print(f"  Gem. worst drawdown             : {row['avg_dd']:+.2f}%")

    if row["tp_pct"] > 50:
        print("  ⚠  TP >50% → filter te streng, drempel verhogen")
    elif row["stop_pct"] > 40:
        print("  ✓  Stop >40% → filter werkt correct")
    else:
        print("  ~  Gemengd beeld")


# ---------------------------------------------------------------------------
# §2F — Δ15m bucket analyse
# ---------------------------------------------------------------------------

def analyse_2f_delta15m(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2F  Δ15m bucket analyse (filter calibratie)")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_expr = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN s.price_change_15m_pct < 2.5 THEN '1_<2.5%'
                WHEN s.price_change_15m_pct < 4.0 THEN '2_2.5-4.0%'
                WHEN s.price_change_15m_pct < 5.5 THEN '3_4.0-5.5%'
                WHEN s.price_change_15m_pct < 6.0 THEN '4_5.5-6.0%'
                ELSE '5_>=6.0%(TOO_LATE)'
            END AS d15_bucket,
            COUNT(*) AS n,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND({stop_expr} * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label IN ('BUY_NOW', 'WATCH', 'TOO_LATE')
          AND o.evaluated_at IS NOT NULL AND s.timestamp > ?
        GROUP BY d15_bucket ORDER BY d15_bucket
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Δ15m bucket':22s}  {'n':>5s}  {tp_label:>10s}  {'Stop%':>7s}  {'avg_best%':>10s}")
    print("  " + "-" * 62)
    for r in rows:
        bucket = r["d15_bucket"][2:]
        print(f"  {bucket:22s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  "
              f"{r['stop_pct']:>6.1f}%  {r['avg_best']:>+9.2f}%")


# ---------------------------------------------------------------------------
# §2G — Volume ratio analyse
# ---------------------------------------------------------------------------

def analyse_2g_volume(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2G  Volume ratio analyse")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_expr = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN s.volume_ratio < 2.0 THEN '1_<2x'
                WHEN s.volume_ratio < 3.0 THEN '2_2-3x'
                WHEN s.volume_ratio < 5.0 THEN '3_3-5x'
                ELSE '4_>=5x'
            END AS vol_bucket,
            COUNT(*) AS n,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND({stop_expr} * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label IN ('BUY_NOW', 'WATCH')
          AND o.evaluated_at IS NOT NULL AND s.timestamp > ?
        GROUP BY vol_bucket ORDER BY vol_bucket
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Vol bucket':12s}  {'n':>5s}  {tp_label:>10s}  {'Stop%':>7s}  {'avg_best%':>10s}")
    print("  " + "-" * 52)
    for r in rows:
        bucket = r["vol_bucket"][2:]
        print(f"  {bucket:12s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  "
              f"{r['stop_pct']:>6.1f}%  {r['avg_best']:>+9.2f}%")

    if rows:
        high_vol = next((r for r in rows if ">=5x" in r["vol_bucket"]), None)
        low_vol = next((r for r in rows if "<2x" in r["vol_bucket"]), None)
        if high_vol and low_vol and high_vol["tp_pct"] < low_vol["tp_pct"] - 10:
            print("  ⚠  ≥5x volume significant slechter — overweeg max_volume_ratio filter")


# ---------------------------------------------------------------------------
# §2H — Spread analyse
# ---------------------------------------------------------------------------

def analyse_2h_spread(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2H  Spread analyse")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )

    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN s.spread_pct < 0.10 THEN '1_<0.10%'
                WHEN s.spread_pct < 0.20 THEN '2_0.10-0.20%'
                WHEN s.spread_pct < 0.30 THEN '3_0.20-0.30%'
                ELSE '4_>=0.30%'
            END AS spread_bucket,
            COUNT(*) AS n,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND s.timestamp > ?
        GROUP BY spread_bucket ORDER BY spread_bucket
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Spread bucket':16s}  {'n':>5s}  {tp_label:>10s}  {'avg_best%':>10s}")
    print("  " + "-" * 48)
    for r in rows:
        bucket = r["spread_bucket"][2:]
        print(f"  {bucket:16s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  {r['avg_best']:>+9.2f}%")


# ---------------------------------------------------------------------------
# §2I — Exchange performance
# ---------------------------------------------------------------------------

def analyse_2i_exchange(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2I  Exchange performance")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_expr = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    rows = conn.execute(f"""
        SELECT s.exchange,
            COUNT(*) AS n,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND({stop_expr} * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND s.timestamp > ?
        GROUP BY s.exchange ORDER BY tp_pct DESC
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Exchange':12s}  {'n':>5s}  {tp_label:>10s}  {'Stop%':>7s}  {'avg_best%':>10s}  Min n=20?")
    print("  " + "-" * 66)
    for r in rows:
        ok = "✓" if r["n"] >= 20 else "⚠ n<20"
        print(f"  {r['exchange']:12s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  "
              f"{r['stop_pct']:>6.1f}%  {r['avg_best']:>+9.2f}%  {ok}")


# ---------------------------------------------------------------------------
# §2J — Preselection bucket kwaliteit
# ---------------------------------------------------------------------------

def analyse_2j_preselection(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2J  Preselection bucket kwaliteit")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )

    rows = conn.execute(f"""
        SELECT s.preselection_bucket AS bucket,
            COUNT(*) AS n,
            ROUND(AVG(s.preselection_score), 3) AS avg_pre_score,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND s.preselection_bucket IS NOT NULL AND s.timestamp > ?
        GROUP BY bucket ORDER BY tp_pct DESC
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Bucket':28s}  {'n':>5s}  {'PreScore':>9s}  {tp_label:>10s}  {'avg_best%':>10s}  Min n=10?")
    print("  " + "-" * 76)
    for r in rows:
        ok = "✓" if r["n"] >= 10 else "⚠ n<10"
        bucket = str(r["bucket"] or "unknown")
        print(f"  {bucket:28s}  {r['n']:>5d}  {r['avg_pre_score']:>9.3f}  "
              f"{r['tp_pct']:>9.1f}%  {r['avg_best']:>+9.2f}%  {ok}")


# ---------------------------------------------------------------------------
# §2K — Market regime per dag
# ---------------------------------------------------------------------------

def analyse_2k_regime(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2K  Market regime per dag")
    has_fh = _has_first_hit(conn)
    tp_expr = (
        "SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_tp1)"
    )
    stop_expr = (
        "SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END)"
        if has_fh else "SUM(o.hit_stop)"
    )

    rows = conn.execute(f"""
        SELECT date(s.timestamp, 'unixepoch') AS dag,
            COUNT(*) AS n,
            ROUND({tp_expr} * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND({stop_expr} * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(AVG(o.best_exit_pct), 2) AS avg_best
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND s.timestamp > ?
        GROUP BY dag ORDER BY dag
    """, (cutoff,)).fetchall()  # noqa: S608

    tp_label = "TP-first%" if has_fh else "TP1-hit%"
    print(f"  {'Dag':12s}  {'n':>5s}  {tp_label:>10s}  {'Stop%':>7s}  {'avg_best%':>10s}")
    print("  " + "-" * 52)
    for r in rows:
        flag = " ⚠ n<5" if r["n"] < 5 else ""
        print(f"  {r['dag']:12s}  {r['n']:>5d}  {r['tp_pct']:>9.1f}%  "
              f"{r['stop_pct']:>6.1f}%  {r['avg_best']:>+9.2f}%{flag}")

    total = sum(r["n"] for r in rows)
    if total and rows:
        max_day = max(rows, key=lambda x: x["n"])
        if max_day["n"] / total > 0.4:
            print(f"\n  ⚠  {max_day['dag']} domineert ({max_day['n']}/{total} = "
                  f"{max_day['n'] / total * 100:.0f}%) — meer data nodig")


# ---------------------------------------------------------------------------
# §2L — Slechtste signalen
# ---------------------------------------------------------------------------

def analyse_2l_worst(conn: sqlite3.Connection, cutoff: float) -> None:
    _header("§2L  Slechtste signalen — stop-first patronen")
    has_fh = _has_first_hit(conn)
    stop_filter = "o.first_hit = 'STOP'" if has_fh else "o.hit_stop = 1"

    rows = conn.execute(f"""
        SELECT s.trading_pair, s.exchange, ROUND(s.score, 3) AS score,
            ROUND(s.price_change_5m_pct, 2) AS d5,
            ROUND(s.price_change_15m_pct, 2) AS d15,
            ROUND(s.volume_ratio, 1) AS vol_ratio,
            ROUND(s.spread_pct, 3) AS spread,
            ROUND(o.worst_drawdown_pct, 2) AS worst_dd,
            ROUND(o.best_exit_pct, 2) AS best_exit
        FROM signals s JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW' AND o.evaluated_at IS NOT NULL
          AND {stop_filter} AND s.timestamp > ?
        ORDER BY o.worst_drawdown_pct ASC LIMIT 20
    """, (cutoff,)).fetchall()  # noqa: S608

    n = len(rows)
    print(f"  Stop-hits getoond (max 20)      : {n}")
    if n == 0:
        print("  ✓  Geen stop-hits gevonden in periode")
        return

    print()
    print(f"  {'Pair':20s}  {'Exch':10s}  {'Score':6s}  {'Δ5m':6s}  {'Δ15m':6s}  "
          f"{'VolRatio':9s}  {'Spread':7s}  {'WorstDD':8s}  {'BestExit':9s}")
    print("  " + "-" * 98)
    for r in rows:
        print(f"  {r['trading_pair']:20s}  {r['exchange']:10s}  {r['score']:6.3f}  "
              f"{r['d5']:+5.1f}%  {r['d15']:+5.1f}%  {r['vol_ratio']:>9.1f}x  "
              f"{r['spread']:>6.3f}%  {r['worst_dd']:>+7.2f}%  {r['best_exit']:>+8.2f}%")

    exchanges = [r["exchange"] for r in rows]
    dom = max(set(exchanges), key=exchanges.count)
    if exchanges.count(dom) / n > 0.4:
        print(f"\n  ⚠  {dom} vertegenwoordigt {exchanges.count(dom) / n * 100:.0f}% van stops")
    high_spread = sum(1 for r in rows if (r["spread"] or 0) >= 0.20)
    if high_spread / n > 0.3:
        print(f"  ⚠  {high_spread}/{n} stops hadden spread ≥ 0.20% — spreadsfilter aanscherpen?")
    high_d15 = sum(1 for r in rows if (r["d15"] or 0) >= 4.0)
    if high_d15 / n > 0.3:
        print(f"  ⚠  {high_d15}/{n} stops hadden Δ15m ≥ 4.0% — TOO_LATE drempel verlagen?")


def _has_config_versions(conn: sqlite3.Connection) -> bool:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return "config_versions" in tables


def analyse_2m_config_versions(conn: sqlite3.Connection, cutoff: float) -> None:
    """§2M  Config versies — TP-first% per paramset om parameterwijzigingen te evalueren."""
    _header("§2M  Config versies — performance per paramset")
    if not _has_config_versions(conn):
        print("  ⚠  Tabel config_versions ontbreekt — service-restart vereist")
        return

    import json

    versions = conn.execute(
        "SELECT id, started_at, params_json FROM config_versions ORDER BY started_at"
    ).fetchall()

    if not versions:
        print("  ℹ  Nog geen config versies opgeslagen (service nog niet herstart na implementatie)")
        return

    print(f"  {'Ver':>4}  {'Actief vanaf':<20}  {'n':>5}  {'TP1%':>5}  {'Stop%':>5}  {'Timeout%':>8}  Sleutelwijzigingen")
    print("  " + "-" * 90)

    prev_params: dict = {}
    for ver in versions:
        ver_id = ver["id"]
        started = ver["started_at"]
        params = json.loads(ver["params_json"])

        import datetime
        dt = datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

        # Stats voor deze versie
        row = conn.execute(
            """
            SELECT
                COUNT(*) as n,
                SUM(CASE WHEN o.first_hit='TP1' OR o.first_hit='TP2' THEN 1 ELSE 0 END) as tp,
                SUM(CASE WHEN o.first_hit='STOP' THEN 1 ELSE 0 END) as stops,
                SUM(CASE WHEN o.first_hit='TIMEOUT' THEN 1 ELSE 0 END) as timeouts
            FROM signals s
            LEFT JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW'
              AND s.config_version_id = ?
              AND (? = 0 OR s.timestamp > ?)
              AND o.evaluated_at IS NOT NULL
            """,
            (ver_id, cutoff, cutoff),
        ).fetchone()

        n = row["n"] or 0
        tp = row["tp"] or 0
        stops = row["stops"] or 0
        timeouts = row["timeouts"] or 0
        tp_pct = f"{100 * tp / n:.0f}%" if n > 0 else " n/a"
        stop_pct = f"{100 * stops / n:.0f}%" if n > 0 else " n/a"
        timeout_pct = f"{100 * timeouts / n:.0f}%" if n > 0 else " n/a"

        # Toon alleen gewijzigde params t.o.v. vorige versie
        changed = []
        for k, v in params.items():
            old = prev_params.get(k)
            if old is not None and old != v:
                changed.append(f"{k}: {old}→{v}")
        changes_str = ", ".join(changed[:3]) if changed else ("(eerste versie)" if not prev_params else "")
        prev_params = params

        print(f"  {ver_id:>4}  {dt:<20}  {n:>5}  {tp_pct:>5}  {stop_pct:>5}  {timeout_pct:>8}  {changes_str}")

    print()
    # Toon volledige params van meest recente versie
    latest = versions[-1]
    latest_params = json.loads(latest["params_json"])
    print("  Huidige parameters (meest recente versie):")
    for k, v in sorted(latest_params.items()):
        print(f"    {k:<40} = {v}")


# ---------------------------------------------------------------------------
# §2N — Marktregime analyse
# ---------------------------------------------------------------------------

def analyse_2n_market_regime(conn: sqlite3.Connection, cutoff: float) -> None:
    """§2N  Marktregime — TP-rate per kwartiel van market_regime_at_signal."""
    _header("§2N  Marktregime — TP-rate per gem. Δ15m kwartiel")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    if "market_regime_at_signal" not in cols:
        print("  ⚠  Kolom market_regime_at_signal ontbreekt — service-restart vereist")
        return
    has_fh = _has_first_hit(conn)
    if not has_fh:
        print("  ⚠  first_hit kolom ontbreekt — analyse niet mogelijk")
        return

    rows = conn.execute(
        """
        WITH base AS (
            SELECT
                NTILE(4) OVER (ORDER BY s.market_regime_at_signal) AS quartile,
                s.market_regime_at_signal AS regime,
                o.first_hit
            FROM signals s
            JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW'
              AND s.accepted = 1
              AND s.market_regime_at_signal IS NOT NULL
              AND o.evaluated_at IS NOT NULL
              AND (? = 0 OR s.timestamp > ?)
        )
        SELECT
            quartile,
            ROUND(MIN(regime), 3) AS regime_min,
            ROUND(MAX(regime), 3) AS regime_max,
            COUNT(*) AS n,
            ROUND(SUM(CASE WHEN first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND(SUM(CASE WHEN first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(SUM(CASE WHEN first_hit = 'TIMEOUT' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS timeout_pct
        FROM base
        GROUP BY quartile
        ORDER BY quartile
        """,
        (cutoff, cutoff),
    ).fetchall()

    if not rows:
        print("  ⚠  Geen data met market_regime_at_signal — nog geen signalen na implementatie")
        return

    print(f"  {'Q':>2}  {'Regime (gem.Δ15m)':>20}  {'n':>5}  {'TP%':>5}  {'Stop%':>6}  {'Timeout%':>9}")
    print("  " + "-" * 60)
    for r in rows:
        print(f"  {r['quartile']:>2}  [{r['regime_min']:>+7.3f}% .. {r['regime_max']:>+7.3f}%]"
              f"  {r['n']:>5}  {r['tp_pct']:>4.1f}%  {r['stop_pct']:>5.1f}%  {r['timeout_pct']:>8.1f}%")
    print()
    print("  Interpretatie: Hoge marktregime (veel stijgende coins) = bullish scan-moment.")
    print("  Lage TP% in Q4 suggereert overbought markt bij te veel signalen tegelijk.")


# ---------------------------------------------------------------------------
# §2O — Entry zone reached
# ---------------------------------------------------------------------------

def analyse_2o_entry_zone(conn: sqlite3.Connection, cutoff: float) -> None:
    """§2O  Entry zone — TP-rate voor signalen waarbij prijs entry_max raakte vs niet."""
    _header("§2O  Entry zone reached — did price dip into entry zone?")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_outcomes)").fetchall()}
    if "entry_zone_reached" not in cols:
        print("  ⚠  Kolom entry_zone_reached ontbreekt — service-restart vereist")
        return
    has_fh = _has_first_hit(conn)
    if not has_fh:
        print("  ⚠  first_hit kolom ontbreekt — analyse niet mogelijk")
        return

    rows = conn.execute(
        """
        SELECT
            o.entry_zone_reached,
            COUNT(*) AS n,
            ROUND(SUM(CASE WHEN o.first_hit IN ('TP1','TP2') THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS tp_pct,
            ROUND(SUM(CASE WHEN o.first_hit = 'STOP' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS stop_pct,
            ROUND(SUM(CASE WHEN o.first_hit = 'TIMEOUT' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS timeout_pct,
            ROUND(AVG(o.time_to_first_hit_minutes), 1) AS avg_time_min
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.signal_label = 'BUY_NOW'
          AND s.accepted = 1
          AND o.evaluated_at IS NOT NULL
          AND o.entry_zone_reached IS NOT NULL
          AND (? = 0 OR s.timestamp > ?)
        GROUP BY o.entry_zone_reached
        ORDER BY o.entry_zone_reached DESC
        """,
        (cutoff, cutoff),
    ).fetchall()

    if not rows:
        print("  ⚠  Geen data met entry_zone_reached — nog geen signalen na implementatie")
        return

    print(f"  {'Entry zone':>12}  {'n':>5}  {'TP%':>5}  {'Stop%':>6}  {'Timeout%':>9}  {'Avg tijd':>9}")
    print("  " + "-" * 58)
    for r in rows:
        label = "Ja (bereikt)" if r["entry_zone_reached"] == 1 else "Nee (gemist)"
        avg_time = f"{r['avg_time_min']:.1f}m" if r["avg_time_min"] is not None else "  n/a"
        print(f"  {label:>12}  {r['n']:>5}  {r['tp_pct']:>4.1f}%  {r['stop_pct']:>5.1f}%  {r['timeout_pct']:>8.1f}%  {avg_time:>9}")
    print()

    # Ook time_to_first_hit stats per first_hit type
    cols2 = {r[1] for r in conn.execute("PRAGMA table_info(signal_outcomes)").fetchall()}
    if "time_to_first_hit_minutes" in cols2:
        t_rows = conn.execute(
            """
            SELECT
                o.first_hit,
                COUNT(*) AS n,
                ROUND(AVG(o.time_to_first_hit_minutes), 1) AS avg_min,
                ROUND(MIN(o.time_to_first_hit_minutes), 1) AS p_min,
                ROUND(MAX(o.time_to_first_hit_minutes), 1) AS p_max
            FROM signals s
            JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW'
              AND s.accepted = 1
              AND o.evaluated_at IS NOT NULL
              AND o.time_to_first_hit_minutes IS NOT NULL
              AND (? = 0 OR s.timestamp > ?)
            GROUP BY o.first_hit
            ORDER BY avg_min ASC
            """,
            (cutoff, cutoff),
        ).fetchall()
        if t_rows:
            print("  Time-to-first-hit per uitkomst:")
            print(f"  {'first_hit':>10}  {'n':>5}  {'gem (min)':>10}  {'min':>6}  {'max':>6}")
            print("  " + "-" * 44)
            for r in t_rows:
                print(f"  {str(r['first_hit']):>10}  {r['n']:>5}  {r['avg_min']:>9.1f}m  {r['p_min']:>5.1f}m  {r['p_max']:>5.1f}m")


# ---------------------------------------------------------------------------
# §2P — Paper-test cohort report
# ---------------------------------------------------------------------------

def analyse_2p_paper_cohorts(conn: sqlite3.Connection, cutoff: float) -> None:
    """§2P  Cohort-vergelijking voor conservatieve paper-test beslissingen."""
    _header("§2P  Paper-test cohort rapport (baseline/regime/exchange/entry-zone)")
    cols_s = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    cols_o = {r[1] for r in conn.execute("PRAGMA table_info(signal_outcomes)").fetchall()}
    if "market_regime_at_signal" not in cols_s:
        print("  ⚠  Kolom market_regime_at_signal ontbreekt — rapport niet mogelijk")
        return
    if "entry_zone_reached" not in cols_o:
        print("  ⚠  Kolom entry_zone_reached ontbreekt — rapport niet mogelijk")
        return
    if not _has_first_hit(conn):
        print("  ⚠  first_hit kolom ontbreekt — rapport niet mogelijk")
        return

    rows = conn.execute(
        """
        WITH base AS (
            SELECT
                s.id,
                s.exchange,
                date(s.timestamp, 'unixepoch', 'localtime') AS day,
                s.market_regime_at_signal,
                o.first_hit,
                o.best_exit_pct,
                o.entry_zone_reached,
                NTILE(4) OVER (ORDER BY s.market_regime_at_signal) AS regime_q
            FROM signals s
            JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.signal_label = 'BUY_NOW'
              AND s.accepted = 1
              AND o.evaluated_at IS NOT NULL
              AND s.market_regime_at_signal IS NOT NULL
              AND (? = 0 OR s.timestamp > ?)
        )
        SELECT * FROM base
        """,
        (cutoff, cutoff),
    ).fetchall()

    if not rows:
        print("  ⚠  Geen BUY_NOW outcomes in deze periode")
        return

    def _ev(first_hit: str, best_exit_pct: float) -> float:
        if first_hit == "TP1":
            return _TP1_PCT - _FEE_PCT
        if first_hit == "TP2":
            return _TP2_PCT - _FEE_PCT
        if first_hit == "STOP":
            return _STOP_PCT - _FEE_PCT
        return (best_exit_pct or 0.0) - _FEE_PCT

    def _print_cohort(name: str, cohort: list, n_min: int = 20) -> None:
        n = len(cohort)
        if n == 0:
            print(f"  {name}: n=0")
            return
        tp = sum(1 for r in cohort if r["first_hit"] in ("TP1", "TP2"))
        stop = sum(1 for r in cohort if r["first_hit"] == "STOP")
        timeout = sum(1 for r in cohort if r["first_hit"] == "TIMEOUT")
        ev = round(sum(_ev(r["first_hit"], r["best_exit_pct"]) for r in cohort) / n, 3)
        stable = "✓" if n >= n_min else f"⚠ n<{n_min}"
        print(
            f"  {name:28s} n={n:>3d}  TP={100 * tp / n:>5.1f}%  STOP={100 * stop / n:>5.1f}%"
            f"  TIMEOUT={100 * timeout / n:>5.1f}%  EV={ev:+.3f}%  {stable}"
        )

        ex_counts = {}
        for r in cohort:
            ex = r["exchange"]
            ex_counts[ex] = ex_counts.get(ex, 0) + 1
        ex_line = ", ".join(f"{k}:{v}" for k, v in sorted(ex_counts.items()))
        print(f"    exchange: {ex_line}")

        day_counts = {}
        for r in cohort:
            d = r["day"]
            day_counts[d] = day_counts.get(d, 0) + 1
        day_line = ", ".join(f"{k}:{v}" for k, v in sorted(day_counts.items()))
        print(f"    per dag : {day_line}")

    all_rows = list(rows)
    regime_not_q4 = [r for r in all_rows if r["regime_q"] != 4]
    bitget_only = [r for r in all_rows if r["exchange"] == "bitget"]
    bitget_regime_not_q4 = [r for r in all_rows if r["exchange"] == "bitget" and r["regime_q"] != 4]
    ez_true = [r for r in all_rows if r["entry_zone_reached"] == 1]
    ez_false = [r for r in all_rows if r["entry_zone_reached"] == 0]

    _print_cohort("1) all signals", all_rows)
    _print_cohort("2) regime != Q4", regime_not_q4)
    _print_cohort("3) bitget only", bitget_only)
    _print_cohort("4) bitget + regime != Q4", bitget_regime_not_q4)
    _print_cohort("5a) entry_zone_reached=1", ez_true)
    _print_cohort("5b) entry_zone_reached=0", ez_false)

    target = 200
    remaining = max(0, target - len(all_rows))
    print()
    print(f"  Evaluatie-target: {len(all_rows)}/{target} BUY_NOW evaluated ({remaining} te gaan)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Signal outcome analyse — SIGNAL_ANALYSIS_PLAN_2WK.md §2A-§2L"
    )
    parser.add_argument("--days", type=int, default=0,
                        help="Analyseer alleen signalen jonger dan N dagen (0 = alles)")
    parser.add_argument("--db", default=_DB_DEFAULT, help="Pad naar SQLite database")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB niet gevonden: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = _connect(str(db_path))
    cutoff = _cutoff(args.days)
    has_fh = _has_first_hit(conn)

    import datetime
    days_label = f"laatste {args.days} dagen" if args.days > 0 else "all-time"
    since_label = (
        datetime.datetime.fromtimestamp(cutoff, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if cutoff > 0 else "begin"
    )

    print("=" * 72)
    print("  SIGNAL OUTCOME ANALYSE  (SIGNAL_ANALYSIS_PLAN_2WK.md)")
    print(f"  Periode  : {days_label} (vanaf {since_label})")
    print(f"  Database : {db_path}")
    print(f"  first_hit: {'aanwezig ✓' if has_fh else 'ONTBREEKT — proxy-modus (service-restart vereist)'}")
    print("=" * 72)

    analyse_2a_first_hit(conn, cutoff)
    analyse_2b_score_calibratie(conn, cutoff)
    analyse_2c_watch(conn, cutoff)
    analyse_2d_events(conn, cutoff)
    analyse_2e_too_late(conn, cutoff)
    analyse_2f_delta15m(conn, cutoff)
    analyse_2g_volume(conn, cutoff)
    analyse_2h_spread(conn, cutoff)
    analyse_2i_exchange(conn, cutoff)
    analyse_2j_preselection(conn, cutoff)
    analyse_2k_regime(conn, cutoff)
    analyse_2l_worst(conn, cutoff)
    analyse_2m_config_versions(conn, cutoff)
    analyse_2n_market_regime(conn, cutoff)
    analyse_2o_entry_zone(conn, cutoff)
    analyse_2p_paper_cohorts(conn, cutoff)

    print()
    print("=" * 72)
    print("  ANALYSE KLAAR")
    print("=" * 72)
    conn.close()


if __name__ == "__main__":
    main()
