#!/usr/bin/env python3
"""
BUY_NOW v5 Paper Tracking Report
=================================
Frozen v5 rules (do not modify until 100 v5 signals collected):
  - volume_ratio < 15
  - price_change_5m_pct / price_change_15m_pct < 0.75
  - market_regime_at_signal >= 0
  - market_breadth_15m >= 40

Run: python track_v5_paper.py
"""
import sqlite3
from datetime import UTC, datetime, timezone

DB = "data/momentum_signals.sqlite"
LEDGER_DB = "data/v5_paper_ledger.sqlite"  # write-only for paper trades, never touches live DB

V5_WHERE = """
    s.volume_ratio < 15
    AND s.price_change_5m_pct / NULLIF(s.price_change_15m_pct, 0) < 0.75
    AND s.market_regime_at_signal >= 0
    AND s.market_breadth_15m >= 40
"""

FEE = {
    "TP1": 0.70,
    "TP2": 2.00,
    "STOP": -2.00,
}


def ev(first_hit, best_exit_pct):
    if first_hit in FEE:
        return FEE[first_hit]
    if first_hit == "TIMEOUT":
        return (best_exit_pct or 0) - 0.50
    return None


def losing_streak(trades):
    """Return (max_streak_length, max_streak_ev_sum) from list of (ev,) tuples."""
    max_len, max_ev = 0, 0.0
    cur_len, cur_ev = 0, 0.0
    for (e,) in trades:
        if e is not None and e < 0:
            cur_len += 1
            cur_ev += e
            if cur_len > max_len:
                max_len, max_ev = cur_len, cur_ev
        else:
            cur_len, cur_ev = 0, 0.0
    return max_len, round(max_ev, 3)


def fmt_pct(n, total):
    if total == 0:
        return "—"
    return f"{100 * n / total:.1f}%"


def block_stats(rows):
    """Return a dict of all metrics for a group of rows."""
    n = len(rows)
    if n == 0:
        return {}
    tp = sum(1 for r in rows if r["first_hit"] in ("TP1", "TP2"))
    st = sum(1 for r in rows if r["first_hit"] == "STOP")
    to = sum(1 for r in rows if r["first_hit"] == "TIMEOUT")
    evs = [ev(r["first_hit"], r["best_exit_pct"]) for r in rows]
    evs_clean = [e for e in evs if e is not None]
    avg_ev = round(sum(evs_clean) / len(evs_clean), 3) if evs_clean else None
    cum_ev = round(sum(evs_clean), 3) if evs_clean else 0.0
    streak_len, streak_ev = losing_streak([(e,) for e in evs_clean])
    avg_best = round(sum(r["best_exit_pct"] or 0 for r in rows) / n, 3)
    avg_dd = round(sum(r["worst_drawdown_pct"] or 0 for r in rows) / n, 3)

    # Timing: stop_hit_at_seconds holds time-to-first-hit for both TP and STOP
    tp_times = [r["stop_hit_at_seconds"] for r in rows
                if r["first_hit"] in ("TP1", "TP2") and r["stop_hit_at_seconds"]]
    st_times = [r["stop_hit_at_seconds"] for r in rows
                if r["first_hit"] == "STOP" and r["stop_hit_at_seconds"]]
    avg_min_to_tp = round(sum(tp_times) / len(tp_times) / 60, 1) if tp_times else None
    avg_min_to_stop = round(sum(st_times) / len(st_times) / 60, 1) if st_times else None

    # Max adverse excursion before TP: worst_drawdown_pct for TP1 rows
    mae_tp = [r["worst_drawdown_pct"] for r in rows
              if r["first_hit"] in ("TP1", "TP2") and r["worst_drawdown_pct"] is not None]
    avg_mae_before_tp = round(sum(mae_tp) / len(mae_tp), 3) if mae_tp else None

    return dict(n=n, tp=tp, st=st, to=to, avg_ev=avg_ev, cum_ev=cum_ev,
                streak_len=streak_len, streak_ev=streak_ev,
                avg_best=avg_best, avg_dd=avg_dd,
                avg_min_to_tp=avg_min_to_tp, avg_min_to_stop=avg_min_to_stop,
                avg_mae_before_tp=avg_mae_before_tp)


def print_block(label, s, indent=""):
    """Print a formatted block_stats dict."""
    n = s["n"]
    print(f"{indent}{label}")
    print(f"{indent}  n={n}  TP={fmt_pct(s['tp'], n)}({s['tp']})  "
          f"STOP={fmt_pct(s['st'], n)}({s['st']})  "
          f"TIMEOUT={fmt_pct(s['to'], n)}({s['to']})")
    print(f"{indent}  avg EV/trade={s['avg_ev']}%  cum EV={s['cum_ev']:+.3f}%")
    print(f"{indent}  avg best_exit={s['avg_best']}%  avg worst_dd={s['avg_dd']}%")
    tp_t = f"{s['avg_min_to_tp']}m" if s["avg_min_to_tp"] else "—"
    st_t = f"{s['avg_min_to_stop']}m" if s["avg_min_to_stop"] else "—"
    mae = f"{s['avg_mae_before_tp']}%" if s["avg_mae_before_tp"] is not None else "—"
    print(f"{indent}  avg min→TP={tp_t}  avg min→STOP={st_t}  "
          f"avg MAE before TP={mae}")
    print(f"{indent}  max losing streak={s['streak_len']} trades "
          f"(cum EV={s['streak_ev']}%)")


def print_summary(label, rows, indent=""):
    print_block(label, block_stats(rows), indent=indent)


def open_ledger():
    """Open (or create) the paper ledger and return a connection."""
    led = sqlite3.connect(LEDGER_DB)
    led.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            signal_id       INTEGER PRIMARY KEY,
            recorded_at     TEXT    NOT NULL,
            signal_ts       TEXT    NOT NULL,
            exchange        TEXT    NOT NULL,
            trading_pair    TEXT    NOT NULL,
            entry_price     REAL,
            volume_ratio    REAL,
            d5d15_ratio     REAL,
            regime          REAL,
            breadth         REAL,
            outcome         TEXT,
            tp_hit          INTEGER,
            stop_hit        INTEGER,
            timeout_hit     INTEGER,
            ev_pct          REAL,
            best_exit_pct   REAL,
            worst_dd_pct    REAL,
            min_to_hit      REAL,
            btc_15m_pct     REAL,
            eth_15m_pct     REAL
        )
    """)
    led.commit()
    return led


def sync_ledger(led, source_con):
    """Insert any new v5 signals not yet in the ledger. Returns count of new rows."""
    existing = {row[0] for row in led.execute("SELECT signal_id FROM paper_trades")}
    new_rows = source_con.execute(f"""
        SELECT s.id, s.timestamp, s.exchange, s.trading_pair,
               COALESCE(s.entry_max, s.price) AS entry_price,
               s.volume_ratio,
               s.price_change_5m_pct / NULLIF(s.price_change_15m_pct, 0) AS d5d15,
               s.market_regime_at_signal, s.market_breadth_15m,
               o.first_hit, o.best_exit_pct, o.worst_drawdown_pct,
               o.stop_hit_at_seconds,
               s.btc_15m_change_pct, s.eth_15m_change_pct
        FROM signal_outcomes o JOIN signals s ON s.id=o.signal_id
        WHERE o.evaluated_at IS NOT NULL AND s.signal_label='BUY_NOW'
          AND {V5_WHERE}
        ORDER BY s.timestamp
    """).fetchall()
    inserted = 0
    for r in new_rows:
        if r[0] in existing:
            continue
        sid, ts, exc, pair, entry, vol, d5d15, regime, breadth, outcome, best, dd, hit_secs, btc_d15m, eth_d15m = r
        tp_h = 1 if outcome in ("TP1", "TP2") else 0
        st_h = 1 if outcome == "STOP" else 0
        to_h = 1 if outcome == "TIMEOUT" else 0
        e = ev(outcome, best)
        min_hit = round(hit_secs / 60, 1) if hit_secs else None
        sig_dt = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S")
        rec_dt = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        led.execute("""
            INSERT INTO paper_trades
              (signal_id, recorded_at, signal_ts, exchange, trading_pair,
               entry_price, volume_ratio, d5d15_ratio, regime, breadth,
               outcome, tp_hit, stop_hit, timeout_hit,
               ev_pct, best_exit_pct, worst_dd_pct, min_to_hit,
               btc_15m_pct, eth_15m_pct)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (sid, rec_dt, sig_dt, exc, pair, entry, vol, d5d15, regime, breadth,
              outcome, tp_h, st_h, to_h, e, best, dd, min_hit, btc_d15m, eth_d15m))
        inserted += 1
    led.commit()
    return inserted


def print_ledger(led):
    rows = led.execute("""
        SELECT signal_ts, exchange, trading_pair, entry_price,
               volume_ratio, d5d15_ratio, regime, breadth,
               outcome, ev_pct, best_exit_pct, worst_dd_pct, min_to_hit
        FROM paper_trades ORDER BY signal_ts
    """).fetchall()
    if not rows:
        print("  (leeg — nog geen v5 trades geregistreerd)")
        return
    h = (f"  {'#':>3} {'Datum':<11} {'Exch':<7} {'Pair':<11}"
         f" {'Vol':>5} {'d5/15':>5} {'Reg':>6}"
         f" {'Hit':<6} {'EV%':>6} {'Min':>5}")
    print(h)
    print("  " + "─" * (len(h) - 2))
    cum = 0.0
    for i, r in enumerate(rows, 1):
        (sig_ts, exc, pair, entry, vol, d5d15, regime, breadth,
         outcome, e, best, dd, min_hit) = r
        if e is not None:
            cum = round(cum + e, 3)
        marker = " ◄" if outcome == "STOP" else ""
        vol_s = f"{vol:.1f}x" if vol else "—"
        d5d15_s = f"{d5d15:.3f}" if d5d15 else "—"
        reg_s = f"{regime:+.3f}" if regime is not None else "—"
        ev_s = f"{e:+.3f}" if e is not None else "—"
        min_s = f"{min_hit}m" if min_hit else "—"
        dt_s = sig_ts[5:16]    # MM-DD HH:MM
        pair_s = pair[:11]
        print(f"  {i:>3} {dt_s:<11} {exc:<7} {pair_s:<11}"
              f" {vol_s:>5} {d5d15_s:>5} {reg_s:>6}"
              f" {outcome:<6} {ev_s:>6} {min_s:>5}{marker}")
    print()
    print(f"  Cumulatief EV: {cum:+.3f}%  over {len(rows)} trades")


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    led = open_ledger()
    new_count = sync_ledger(led, con)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print("=" * 68)
    print(f"  BUY_NOW v5 Paper Tracking Report  —  {now_str}")
    print("=" * 68)
    print()
    print("Frozen v5 rules:")
    print("  volume_ratio < 15  |  d5/d15 < 0.75  |  regime >= 0  |  breadth >= 40")

    # ── All evaluated BUY_NOW ──────────────────────────────────────────────
    base_query = """
        SELECT s.timestamp, date(s.timestamp,'unixepoch') AS dag,
               s.exchange, s.trading_pair, o.first_hit,
               s.volume_ratio, s.price_change_5m_pct, s.price_change_15m_pct,
               s.market_regime_at_signal, s.market_breadth_15m,
               o.best_exit_pct, o.worst_drawdown_pct, o.stop_hit_at_seconds
        FROM signal_outcomes o JOIN signals s ON s.id=o.signal_id
        WHERE o.evaluated_at IS NOT NULL AND s.signal_label='BUY_NOW'
    """
    all_rows = [dict(r) for r in con.execute(base_query + " ORDER BY s.timestamp")]
    # V5_WHERE is the single source of truth for the frozen filter
    v5_rows = [dict(r) for r in con.execute(
        base_query + f"AND {V5_WHERE} ORDER BY s.timestamp"
    )]

    first_ts = min(r["timestamp"] for r in v5_rows) if v5_rows else None
    last_ts = max(r["timestamp"] for r in v5_rows) if v5_rows else None

    print()
    print(f"Data range: {datetime.fromtimestamp(first_ts, UTC).strftime('%Y-%m-%d')} "
          f"→ {datetime.fromtimestamp(last_ts, UTC).strftime('%Y-%m-%d %H:%M')}")
    print(f"v5 signals collected: {len(v5_rows)} / 100 target  "
          f"({'█' * len(v5_rows) + '░' * (100 - len(v5_rows))})" if len(v5_rows) <= 100
          else f"v5 signals: {len(v5_rows)} (target reached)")
    print()

    # ── Per-20-trades blocks: side-by-side baseline vs v5 ──────────────────
    print("─" * 68)
    print("PER-20-TRADE BLOCKS: BASELINE vs V5")
    print("─" * 68)
    block_size = 20
    n_all = len(all_rows)
    n_v5 = len(v5_rows)
    n_blocks_all = (n_all + block_size - 1) // block_size
    n_blocks_v5 = (n_v5 + block_size - 1) // block_size
    n_blocks = max(n_blocks_all, n_blocks_v5)

    for i in range(n_blocks):
        bslice = all_rows[i * block_size: (i + 1) * block_size]
        vslice = v5_rows[i * block_size: (i + 1) * block_size]
        print(f"  Block {i + 1}")
        if bslice:
            s_dt = datetime.fromtimestamp(bslice[0]["timestamp"], UTC).strftime("%Y-%m-%d")
            e_dt = datetime.fromtimestamp(bslice[-1]["timestamp"], UTC).strftime("%Y-%m-%d")
            print_block(f"  Baseline (trades {i * block_size + 1}\u2013{i * block_size + len(bslice)}, {s_dt}\u2192{e_dt})",
                        block_stats(bslice), indent="    ")
        else:
            print("    Baseline: geen data")
        print()
        if vslice:
            s_dt = datetime.fromtimestamp(vslice[0]["timestamp"], UTC).strftime("%Y-%m-%d")
            e_dt = datetime.fromtimestamp(vslice[-1]["timestamp"], UTC).strftime("%Y-%m-%d")
            print_block(f"  v5 (trades {i * block_size + 1}\u2013{i * block_size + len(vslice)}, {s_dt}\u2192{e_dt})",
                        block_stats(vslice), indent="    ")
        else:
            print(f"    v5: [{block_size - (n_v5 - i * block_size)} meer v5-signalen nodig voor block {i + 1}]")
        print()

    if n_v5 < 100:
        print(f"  [v5: nog {100 - n_v5} signalen tot doelstelling van 100]")
    print()

    # ── Overall comparison ──────────────────────────────────────────────────
    print("─" * 68)
    print("OVERALL TOTAAL: BASELINE vs V5")
    print("─" * 68)
    print_summary("Baseline (all BUY_NOW)", all_rows)
    print()
    print_summary("v5 filtered", v5_rows)
    print()

    # ── Daily EV ────────────────────────────────────────────────────────────
    print("─" * 68)
    print("v5: DAILY EV BREAKDOWN")
    print("─" * 68)
    days = {}
    for r in v5_rows:
        days.setdefault(r["dag"], []).append(r)
    print(f"  {'Dag':<12} {'n':>4} {'TP%':>7} {'STOP%':>7} {'EV/trade':>10}")
    print(f"  {'─' * 12} {'─' * 4} {'─' * 7} {'─' * 7} {'─' * 10}")
    for dag in sorted(days):
        rr = days[dag]
        n = len(rr)
        tp = sum(1 for r in rr if r["first_hit"] in ("TP1", "TP2"))
        st = sum(1 for r in rr if r["first_hit"] == "STOP")
        evs = [ev(r["first_hit"], r["best_exit_pct"]) for r in rr]
        evs = [e for e in evs if e is not None]
        avg = round(sum(evs) / len(evs), 3) if evs else None
        flag = " ✓" if avg and avg >= 0 else " ✗" if avg else ""
        print(f"  {dag:<12} {n:>4} {fmt_pct(tp, n):>7} {fmt_pct(st, n):>7} {str(avg) + '%':>10}{flag}")
    days_pos = sum(1 for d in days if any(
        ev(r["first_hit"], r["best_exit_pct"]) is not None
        and ev(r["first_hit"], r["best_exit_pct"]) >= 0
        for r in days[d]
    ))
    print(f"\n  Positive days: {days_pos}/{len(days)}")
    print()

    # ── Per-exchange ────────────────────────────────────────────────────────
    print("─" * 68)
    print("v5: PER EXCHANGE")
    print("─" * 68)
    exchanges = {}
    for r in v5_rows:
        exchanges.setdefault(r["exchange"], []).append(r)
    print(f"  {'Exchange':<12} {'n':>4} {'TP%':>7} {'STOP%':>7} {'TO%':>7} {'EV/trade':>10}")
    print(f"  {'─' * 12} {'─' * 4} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 10}")
    for exc in sorted(exchanges, key=lambda x: -len(exchanges[x])):
        rr = exchanges[exc]
        n = len(rr)
        tp = sum(1 for r in rr if r["first_hit"] in ("TP1", "TP2"))
        st = sum(1 for r in rr if r["first_hit"] == "STOP")
        to = sum(1 for r in rr if r["first_hit"] == "TIMEOUT")
        evs = [ev(r["first_hit"], r["best_exit_pct"]) for r in rr]
        evs = [e for e in evs if e is not None]
        avg = round(sum(evs) / len(evs), 3) if evs else None
        note = " (n<10)" if n < 10 else ""
        print(f"  {exc:<12} {n:>4} {fmt_pct(tp, n):>7} {fmt_pct(st, n):>7} "
              f"{fmt_pct(to, n):>7} {str(avg) + '%':>10}{note}")
    print()

    # ── Per-coin (top appearances) ──────────────────────────────────────────
    print("─" * 68)
    print("v5: PER COIN (≥2 signalen)")
    print("─" * 68)
    coins = {}
    for r in v5_rows:
        key = f"{r['exchange']}:{r['trading_pair']}"
        coins.setdefault(key, []).append(r)
    coins_filtered = {k: v for k, v in coins.items() if len(v) >= 2}
    if coins_filtered:
        print(f"  {'Coin':<24} {'n':>4} {'TP%':>7} {'STOP%':>7} {'EV/trade':>10}")
        print(f"  {'─' * 24} {'─' * 4} {'─' * 7} {'─' * 7} {'─' * 10}")
        for coin in sorted(coins_filtered, key=lambda x: -len(coins_filtered[x])):
            rr = coins_filtered[coin]
            n = len(rr)
            tp = sum(1 for r in rr if r["first_hit"] in ("TP1", "TP2"))
            st = sum(1 for r in rr if r["first_hit"] == "STOP")
            evs = [ev(r["first_hit"], r["best_exit_pct"]) for r in rr]
            evs = [e for e in evs if e is not None]
            avg = round(sum(evs) / len(evs), 3) if evs else None
            print(f"  {coin:<24} {n:>4} {fmt_pct(tp, n):>7} {fmt_pct(st, n):>7} {str(avg) + '%':>10}")
    else:
        print("  Geen coins met ≥2 v5-signalen in huidig venster.")
    print()

    # ── Chronological trade log ─────────────────────────────────────────────
    print("─" * 68)
    print("v5: ALLE TRADES CHRONOLOGISCH")
    print("─" * 68)
    cum_ev = 0.0
    streak_cur = 0
    header = f"  {'#':>4} {'Datum':>10} {'Exchange':<9} {'Pair':<15} {'Hit':<8} " \
             f"{'EV%':>7} {'CumEV%':>8} {'Strk':>5}"
    print(header)
    print("  " + "─" * (len(header) - 2))
    for i, r in enumerate(v5_rows, 1):
        e = ev(r["first_hit"], r["best_exit_pct"])
        cum_ev_str = ""
        streak_str = ""
        if e is not None:
            cum_ev = round(cum_ev + e, 3)
            cum_ev_str = f"{cum_ev:+.3f}"
            if e < 0:
                streak_cur += 1
            else:
                streak_cur = 0
            streak_str = str(streak_cur) if streak_cur > 0 else ""
        dag = datetime.fromtimestamp(r["timestamp"], UTC).strftime("%m-%d %H:%M")
        marker = "◄" if r["first_hit"] == "STOP" else ""
        print(f"  {i:>4} {dag:>10} {r['exchange']:<9} {r['trading_pair']:<15} "
              f"{r['first_hit']:<8} {str(round(e, 3)) + '%' if e else '—':>7} "
              f"{cum_ev_str:>8} {streak_str:>5} {marker}")

    print()
    print(f"  Totaal cumulatief EV: {cum_ev:+.3f}%  ({len(v5_rows)} trades)")
    print()

    # ── Paper ledger ────────────────────────────────────────────────────────
    print("─" * 68)
    new_label = f"  (+{new_count} nieuw deze run)" if new_count else ""
    print(f"PAPER TRADING LEDGER{new_label}")
    print("─" * 68)
    print_ledger(led)
    print()

    # ── Status ──────────────────────────────────────────────────────────────
    print("─" * 68)
    print("STATUS")
    print("─" * 68)
    print(f"  v5 signalen verzameld : {len(v5_rows)}")
    print("  Target voor conclusie : 100")
    print(f"  Nog te wachten        : {max(0, 100 - len(v5_rows))}")
    evs_all = [ev(r["first_hit"], r["best_exit_pct"]) for r in v5_rows]
    evs_all = [e for e in evs_all if e is not None]
    avg_ev_all = round(sum(evs_all) / len(evs_all), 3) if evs_all else None
    print(f"  Huidige avg EV/trade  : {avg_ev_all}%")
    print("  Break-even vereist    : ~74% TP-first (bij TP=+0.7%, STOP=-2.0%)")
    print()
    print("  Volgende milestone    : 20 v5 signalen → eerste block-analyse")
    print("  Conclusie pas bij     : 100 v5 signalen")
    print("=" * 68)

    led.close()
    con.close()


if __name__ == "__main__":
    main()
