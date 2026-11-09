#!/usr/bin/env python3
"""
v5 shadow-cohort: integriteitscontrole + CURRENT vs WIDE_TP (bruto/netto gescheiden).

Leest alleen (SQLite mode=ro). Bron: permanente tabel ``buy_now_shadow_archive``.

  python track_v5_cohort.py            # schone cohort sinds cohort_start_ts
  python track_v5_cohort.py --legacy69 # dry-run: 69 oude shadow-trades met echte T+30

Payoff (bruto): TP1 +1.2 | TP2 +2.5 | WIDE_TP +1.5 | STOP = invalidation_price/entry-1 |
TIMEOUT = exit_30m_pct (eerste observatie op/na 30 min, nooit MFE).
Netto = bruto − 0.50 (round-trip kostenaanname, uniform).
"""
import argparse
import json
import sqlite3
import statistics
import time
from datetime import UTC, datetime

from multi_coin_grid_pro.signals import momentum_shadow_archive as sa

DB = "data/momentum_signals.sqlite"
LEDGER_DB = "data/v5_paper_ledger.sqlite"
SHADOW_START = "2026-09-20 03:15:58"
TARGET = 100


def _ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _dt(ts):
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def summarize(rows):
    """rows: dicts met entry_price, invalidation_price, tp1/tp2_price, exit_30m_pct,
    current_outcome, wide_outcome."""
    for variant, key in (("CURRENT", "current_outcome"), ("WIDE", "wide_outcome")):
        gross = [sa.gross_return_pct(variant, r[key], r["entry_price"], r["invalidation_price"],
                                     r["exit_30m_pct"], r.get("tp1_price"), r.get("tp2_price"))
                 for r in rows]
        val = [g for g in gross if g is not None]
        n = len(rows)
        tp = sum(r[key] in ("TP1", "TP2", "WIDE_TP") for r in rows)
        st = sum(r[key] == "STOP" for r in rows)
        to = sum(r[key] == "TIMEOUT" for r in rows)
        if not val:
            print(f"  {variant:<8} n={n} — niet waardeerbaar")
            continue
        net = [sa.net_return_pct(g) for g in val]
        print(f"  {variant:<8} n={n} gewaardeerd={len(val)}  TP {tp} ({100 * tp / n:.1f}%)  "
              f"STOP {st} ({100 * st / n:.1f}%)  TIMEOUT {to} ({100 * to / n:.1f}%)")
        print(f"  {'':<8} bruto gem {statistics.mean(val):+.3f}%  | netto gem {statistics.mean(net):+.3f}%"
              f"  | netto cum {sum(net):+.2f}%")


def cohort_report():
    con = _ro(DB)
    if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'shadow_archive_meta'").fetchone() is None:
        print("Cohort nog niet gestart: service draait nog zonder archiefcode (herstart nodig).")
        return
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM shadow_archive_meta")}
    if "cohort_start_ts" not in meta:
        print("Cohort nog niet gestart (service draait nog zonder archiefcode).")
        return
    start = float(meta["cohort_start_ts"])
    now = time.time()
    print(f"Cohort start: {_dt(start)}")
    stored = json.loads(meta["cohort_definition"])
    defn_ok = (stored["v5_sql"] == " ".join(sa.V5_SQL.split())
               and stored["wide"]["tp_pct"] == sa.WIDE_TP_PCT
               and stored["fee_round_trip_pct"] == sa.FEE_ROUND_TRIP_PCT
               and stored["timeout_horizon_min"] == sa.TIMEOUT_HORIZON_MIN)
    print(f"Definitie ongewijzigd t.o.v. code: {'JA' if defn_ok else 'NEE — cohort ongeldig'}")

    rows = [dict(r) for r in con.execute(
        "SELECT * FROM buy_now_shadow_archive WHERE signal_ts >= ? ORDER BY signal_ts", (start,))]
    ev = [r for r in rows if r["archive_status"] == "EVALUATED"]
    v5 = [r for r in ev if r["v5_pass"] == 1]
    unev_v5 = [r for r in rows if r["archive_status"] == "UNEVALUATED" and r["v5_pass"] == 1]
    no_exit = [r["signal_id"] for r in v5 if r["exit_30m_price"] is None]
    late = [r["signal_id"] for r in v5 if r["exit_30m_at_seconds"] is not None
            and not 1800 <= r["exit_30m_at_seconds"] < 2400]
    unarchived = sa.unarchived_signal_ids(con, now)
    cov = {r[0]: r[1] for r in con.execute(
        "SELECT hour_bucket, scans FROM shadow_scan_coverage WHERE hour_bucket >= ?", (int(start // 3600),))}
    hours = range(int(start // 3600) + 1, int(now // 3600))  # volle uren
    missing_hours = [h for h in hours if cov.get(h, 0) == 0]
    thin_hours = [h for h in hours if 0 < cov.get(h, 0) < 30]

    print("\nINTEGRITEIT")
    print(f"  BUY_NOW gearchiveerd: {len(rows)}  (geëvalueerd {len(ev)}, v5-pass {len(v5)})")
    print(f"  v5 UNEVALUATED (gemist): {len(unev_v5)}")
    print(f"  v5 zonder exit_30m: {len(no_exit)}  | exit buiten [1800,2400)s: {len(late)}")
    print(f"  Definitief maar niet gearchiveerd (nu in signals): {len(unarchived)}")
    print(f"  Uren zonder scan: {len(missing_hours)}  | uren <30 scans: {len(thin_hours)}"
          f"  (van {len(hours)})")
    for h in missing_hours[:10]:
        print(f"    gat: {_dt(h * 3600)}")
    clean = defn_ok and not (unev_v5 or no_exit or late or unarchived or missing_hours)
    print(f"  Status: {'SCHOON' if clean else 'CONTROLEREN'}  | voortgang {len(v5)}/{TARGET}")
    if v5:
        print("\nPERFORMANCE (v5, geëvalueerd)")
        summarize(v5)


def legacy69():
    led = _ro(LEDGER_DB)
    src = _ro(DB)
    rows = [dict(r) for r in led.execute(
        "SELECT * FROM paper_trades WHERE signal_ts >= ? ORDER BY signal_ts", (SHADOW_START,))]
    ok, bad, secs = [], [], []
    for r in rows:
        o = src.execute(
            "SELECT entry_price, max_price_30m, min_price_30m, evaluated_at FROM signal_outcomes "
            "WHERE signal_id = ?", (r["signal_id"],)).fetchone()
        ts = datetime.strptime(r["signal_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
        reason = None
        # Bewijs dat max_price_30m de exit-prijs is komt uit het codepad (venster alleen op de
        # evaluatietick geschreven; zie test_max_price_30m_written_once_on_evaluation_tick).
        # max==min, entry, tijd en MAE<=exit<=MFE zijn alleen consistentiechecks.
        if o is None or o["max_price_30m"] is None:
            reason = "geen outcome-rij/30m-prijs"
        elif o["max_price_30m"] != o["min_price_30m"]:
            reason = "meerdere observaties in 30m-venster"
        elif abs(o["entry_price"] - r["entry_price"]) > 1e-12:
            reason = "entry mismatch"
        elif not (r["worst_dd_pct"] - 1e-3
                  <= (o["max_price_30m"] / r["entry_price"] - 1) * 100
                  <= r["best_exit_pct"] + 1e-3):
            reason = "exit buiten MAE/MFE"
        else:
            age = o["evaluated_at"] - ts  # signal_ts afgekapt op seconden → ±1 s
            if not 1799 <= age < 2401:
                reason = f"exit-tijd {age:.0f}s buiten tolerantie"
        if reason:
            bad.append((r["signal_id"], reason))
            continue
        secs.append(age)
        ok.append({
            "entry_price": r["entry_price"], "invalidation_price": r["invalidation_price"],
            "tp1_price": r["tp1_price"], "tp2_price": r["tp2_price"],
            "exit_30m_pct": (o["max_price_30m"] / r["entry_price"] - 1) * 100,
            "current_outcome": r["outcome"], "wide_outcome": r["wide_outcome"],
            "legacy_ev": r["ev_pct"],
        })
    print(f"Legacy shadow-trades sinds {SHADOW_START} UTC: {len(rows)}")
    print(f"  T+30 herstelbaar: {len(ok)}  | niet: {len(bad)}")
    for sid, why in bad:
        print(f"    {sid}: {why}")
    if secs:
        print(f"  exit_30m_at_seconds: min {min(secs):.0f}  mediaan {statistics.median(secs):.0f}"
              f"  max {max(secs):.0f}")
        print("\nHERBEREKEND (echte STOP-afstand, TIMEOUT = T+30)")
        summarize(ok)
        legacy = [r["legacy_ev"] for r in ok]
        print(f"  Ter vergelijking oud model (TIMEOUT=MFE−0.5, STOP=−2.00): "
              f"gem {statistics.mean(legacy):+.3f}%  cum {sum(legacy):+.2f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy69", action="store_true")
    legacy69() if ap.parse_args().legacy69 else cohort_report()
