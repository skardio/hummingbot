#!/usr/bin/env python3
"""Buy-fill accumulation robustness analysis, built on top of analyze_trading_performance.py.

Reuses load_trades()/tradefill_pnl() from analyze_trading_performance.py (same DB,
same TradeFill-corrected PnL). No MCP, no network calls.

Two independent modes:
  1. DB mode (default): analyzes closed Executors from the sqlite DB, same as before.
  2. --log-file mode: parses [FILL_RISK_LOG] shadow-mode lines (FASE 1A, added
     2026-09-12 to grid_executor.py) emitted on every BUY fill across ANY of the
     4 spot bots (Bitget/OKX/Kraken USD/Kraken EUR - the logging is generic/shared
     code, so log lines are tagged with exchange/quote_currency/bot_instance_id).
     This mode does NOT touch the DB and is meant for later offline comparison of
     candidate soft-risk stop-tightening factors (shadow_stop_mild/medium/strong)
     once enough real fill-level data has been collected.
  3. --snapshot-db mode (FASE 1B, added 2026-09-13): reads directly from the
     shared FillRiskSnapshot SQLite store (data/fill_risk_snapshots.db) written
     by grid_executor.py on every BUY fill across all 4 spot bots - no logs
     needed at all for this comparison.

Usage:
    python tools/analyze_fill_risk.py [--db PATH] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
    python tools/analyze_fill_risk.py --log-file logs/spot_grid_bitget.log
    python tools/analyze_fill_risk.py --snapshot-db data/fill_risk_snapshots.db
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import analyze_trading_performance as base  # noqa: E402

FILL_RISK_LOG_PATTERN = re.compile(
    r"\[FILL_RISK_LOG\]\s+"
    r"executor_id=(?P<executor_id>\S+)\s+"
    r"exchange=(?P<exchange>\S+)\s+"
    r"quote_currency=(?P<quote_currency>\S+)\s+"
    r"bot_instance_id=(?P<bot_instance_id>\S+)\s+"
    r"pair=(?P<pair>\S+)\s+"
    r"fill_number=(?P<fill_number>\d+)\s+"
    r"timestamp=(?P<timestamp>[\d.]+)\s+"
    r"fill_price=(?P<fill_price>[\d.]+)\s+"
    r"fill_amount_base=(?P<fill_amount_base>[\d.]+)\s+"
    r"fill_amount_quote=(?P<fill_amount_quote>[\d.]+)\s+"
    r"avg_entry_price=(?P<avg_entry_price>[\d.]+)\s+"
    r"position_size_quote=(?P<position_size_quote>[\d.]+)\s+"
    r"unrealized_pnl_quote=(?P<unrealized_pnl_quote>-?[\d.]+)\s+"
    r"unrealized_drawdown_pct=(?P<unrealized_drawdown_pct>-?[\d.]+)\s+"
    r"current_price=(?P<current_price>[\d.]+)\s+"
    r"entry_atr_pct=(?P<entry_atr_pct>[\d.]+)\s+"
    r"entry_trend_score=(?P<entry_trend_score>\S+)\s+"
    r"effective_stop_pct=(?P<effective_stop_pct>[\d.]+)\s+"
    r"risk_state=(?P<risk_state>\S+)\s+"
    r"shadow_stop_mild=(?P<shadow_stop_mild>[\d.]+)\s+"
    r"shadow_stop_medium=(?P<shadow_stop_medium>[\d.]+)\s+"
    r"shadow_stop_strong=(?P<shadow_stop_strong>[\d.]+)\s+"
    r"soft_risk_state_enabled=(?P<soft_risk_state_enabled>\S+)"
)


def parse_fill_risk_log(log_path: Path) -> list[dict]:
    """Parse all [FILL_RISK_LOG] lines from a bot log file into structured records."""
    records = []
    with open(log_path, "r", errors="replace") as f:
        for line in f:
            m = FILL_RISK_LOG_PATTERN.search(line)
            if not m:
                continue
            d = m.groupdict()
            records.append({
                "executor_id": d["executor_id"],
                "exchange": d["exchange"],
                "quote_currency": d["quote_currency"],
                "bot_instance_id": d["bot_instance_id"],
                "pair": d["pair"],
                "fill_number": int(d["fill_number"]),
                "timestamp": float(d["timestamp"]),
                "fill_price": float(d["fill_price"]),
                "position_size_quote": float(d["position_size_quote"]),
                "unrealized_pnl_quote": float(d["unrealized_pnl_quote"]),
                "unrealized_drawdown_pct": float(d["unrealized_drawdown_pct"]),
                "entry_atr_pct": float(d["entry_atr_pct"]),
                "entry_trend_score": None if d["entry_trend_score"] == "None" else d["entry_trend_score"],
                "effective_stop_pct": float(d["effective_stop_pct"]),
                "risk_state": d["risk_state"],
                "shadow_stop_mild": float(d["shadow_stop_mild"]),
                "shadow_stop_medium": float(d["shadow_stop_medium"]),
                "shadow_stop_strong": float(d["shadow_stop_strong"]),
                "soft_risk_state_enabled": d["soft_risk_state_enabled"] == "True",
            })
    return records


def load_snapshots_from_db(db_path: Path) -> list[dict]:
    """Read all rows from the shared FillRiskSnapshot store directly (no logs).

    Returns the same dict shape as parse_fill_risk_log() for the fields that
    exist in both (shadow_stop_mild/medium/strong are log-only and intentionally
    not persisted to keep the table minimal - not needed by section_shadow_log_summary).
    """
    from multi_coin_grid_pro.persistence.fill_risk_snapshot_store import FillRiskSnapshotStore
    store = FillRiskSnapshotStore(str(db_path))
    try:
        snaps = store.query_recent(days=100_000)  # effectively "all"
    finally:
        store.close()
    return [{
        "executor_id": s.executor_id,
        "exchange": s.exchange,
        "quote_currency": s.quote_currency,
        "bot_instance_id": s.bot_instance_id,
        "pair": s.trading_pair,
        "fill_number": s.fill_number,
        "timestamp": s.timestamp,
        "fill_price": s.fill_price,
        "position_size_quote": s.position_size_quote,
        "unrealized_pnl_quote": s.unrealized_pnl_quote,
        "unrealized_drawdown_pct": s.unrealized_drawdown_pct,
        "entry_atr_pct": s.entry_atr_pct,
        "entry_trend_score": s.entry_trend_score,
        "effective_stop_pct": s.effective_stop_pct,
        "risk_state": s.risk_state,
        "soft_risk_state_enabled": None,  # not persisted per-row; check config instead
    } for s in snaps]


def section_shadow_log_summary(records: list[dict]) -> None:
    """Summarize parsed FILL_RISK_LOG records: per exchange/bot coverage and
    per-risk_state distribution. Does NOT compute PF/winrate - shadow log
    records are per-fill snapshots, not closed-trade outcomes; join with the
    DB (Executors.id == executor_id) once enough data exists to evaluate
    candidate stop-tightening factors against real trade outcomes."""
    base.print_header("SHADOW-LOG COVERAGE (FILL_RISK_LOG records)")
    if not records:
        print("  Geen [FILL_RISK_LOG] records gevonden in dit logbestand.")
        return
    by_bot = defaultdict(int)
    by_state = defaultdict(int)
    executors_seen = set()
    for r in records:
        by_bot[f"{r['exchange']}/{r['quote_currency']} ({r['bot_instance_id']})"] += 1
        by_state[r["risk_state"]] += 1
        executors_seen.add(r["executor_id"])
    print(f"  Totaal records: {len(records)}  |  Unieke executors: {len(executors_seen)}")
    print("\n  Per bot:")
    for bot, n in sorted(by_bot.items(), key=lambda kv: -kv[1]):
        print(f"    {bot:<40} {n:>6} records")
    print("\n  Per risk_state:")
    for state, n in sorted(by_state.items(), key=lambda kv: -kv[1]):
        print(f"    {state:<20} {n:>6} records")


def pct(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def group_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnls = [t["corrected_pnl"] for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    gross_win = sum(winners)
    gross_loss = abs(sum(losers))
    sl = sum(1 for t in trades if t["close_type_name"] == "STOP_LOSS")
    pnl_pcts = [pct(t["corrected_pnl"], t["filled_quote"]) for t in trades if t["filled_quote"]]
    return {
        "n": n,
        "wins": len(winners),
        "losses": len(losers),
        "winrate": pct(len(winners), n),
        "total_pnl": sum(pnls),
        "avg_pnl": statistics.mean(pnls),
        "median_pnl": statistics.median(pnls),
        "avg_winner": statistics.mean(winners) if winners else 0.0,
        "avg_loser": statistics.mean(losers) if losers else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "sl_pct": pct(sl, n),
        "avg_filled": statistics.mean([t["filled_quote"] for t in trades]),
        "avg_pnl_pct": statistics.mean(pnl_pcts) if pnl_pcts else 0.0,
    }


def print_group_table(rows: list[tuple[str, dict]]):
    hdr = (f"  {'Groep':<8}{'N':>4}{'Win':>5}{'Loss':>5}{'WR%':>7}{'TotPnL':>10}{'AvgPnL':>9}"
           f"{'MedPnL':>9}{'AvgWin':>9}{'AvgLoss':>9}{'PF':>7}{'SL%':>7}{'AvgFill':>9}{'AvgPnL%':>9}")
    print(hdr)
    print("  " + "-" * len(hdr.strip()))
    for label, s in rows:
        if s["n"] == 0:
            print(f"  {label:<8}{0:>4}  (geen trades)")
            continue
        flag = " *klein N*" if s["n"] < 10 else ""
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        print(f"  {label:<8}{s['n']:>4}{s['wins']:>5}{s['losses']:>5}{s['winrate']:>6.1f}%"
              f"{s['total_pnl']:>+10.3f}{s['avg_pnl']:>+9.3f}{s['median_pnl']:>+9.3f}"
              f"{s['avg_winner']:>+9.3f}{s['avg_loser']:>+9.3f}{pf:>7}{s['sl_pct']:>6.1f}%"
              f"{s['avg_filled']:>9.2f}{s['avg_pnl_pct']:>+8.2f}%{flag}")


def price_stats(conn: sqlite3.Connection, pair: str, start_ts: float, end_ts: float, pad: float = 5.0):
    start_ms = int((start_ts - pad) * 1000)
    end_ms = int((end_ts + pad) * 1000)
    rows = conn.execute(
        "SELECT trade_type, price FROM TradeFill WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
        (pair, start_ms, end_ms),
    ).fetchall()
    buys = [r[1] * base.TRADEFILL_SCALE for r in rows if r[0] == "BUY"]
    sells = [r[1] * base.TRADEFILL_SCALE for r in rows if r[0] == "SELL"]
    return buys, sells


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/spot_grid_bitget.sqlite")
    parser.add_argument("--start", default="2026-08-08")
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--log-file", default=None,
        help="Parse [FILL_RISK_LOG] shadow-mode lines from this log file instead of the DB."
    )
    parser.add_argument(
        "--snapshot-db", default=None,
        help="Read fill-risk telemetry directly from the shared FillRiskSnapshot "
             "SQLite store (data/fill_risk_snapshots.db) - no logs needed."
    )
    args = parser.parse_args()

    if args.snapshot_db:
        snap_path = Path(args.snapshot_db)
        if not snap_path.exists():
            raise SystemExit(f"Snapshot DB not found: {snap_path}")
        records = load_snapshots_from_db(snap_path)
        section_shadow_log_summary(records)
        return

    if args.log_file:
        log_path = Path(args.log_file)
        if not log_path.exists():
            raise SystemExit(f"Log file not found: {log_path}")
        records = parse_fill_risk_log(log_path)
        section_shadow_log_summary(records)
        return

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    start_ts = dt.datetime.strptime(args.start, "%Y-%m-%d").timestamp()
    end_ts = dt.datetime.strptime(args.end, "%Y-%m-%d").timestamp() if args.end else dt.datetime.now().timestamp()

    conn = sqlite3.connect(str(db_path))
    all_trades = base.load_trades(conn, start_ts, end_ts)
    active = [t for t in all_trades if t["n_buy_fills"] > 0]

    print(f"\nFill-risk robustheidsanalyse: {args.start} t/m "
          f"{dt.datetime.fromtimestamp(end_ts, dt.timezone.utc).strftime('%Y-%m-%d')}  "
          f"(actieve grids met >0 buy fills: {len(active)}/{len(all_trades)})")

    # 1. gross profit/loss/net/PF over ALL trades (not just active)
    all_pnls = [t["corrected_pnl"] for t in all_trades]
    gross_profit = sum(p for p in all_pnls if p > 0)
    gross_loss = abs(sum(p for p in all_pnls if p <= 0))
    net = sum(all_pnls)
    pf = (gross_profit / gross_loss) if gross_loss else float("inf")
    base.print_header("1. GROSS PROFIT / GROSS LOSS / NET / PF (alle trades)")
    print(f"  Gross profit: {gross_profit:+.3f}   Gross loss: {gross_loss:.3f}   "
          f"Net PnL: {net:+.3f}   Profit factor: {pf:.2f}")

    # 2. range buckets
    base.print_header("2. FILL-BUCKETS (1-2 / 3-4 / 5+ en <5 / >=5)")
    b_1_2 = [t for t in active if t["n_buy_fills"] <= 2]
    b_3_4 = [t for t in active if 3 <= t["n_buy_fills"] <= 4]
    b_5p = [t for t in active if t["n_buy_fills"] >= 5]
    b_lt5 = [t for t in active if t["n_buy_fills"] < 5]
    b_ge5 = b_5p
    print_group_table([
        ("1-2", group_stats(b_1_2)), ("3-4", group_stats(b_3_4)), ("5+", group_stats(b_5p)),
        ("<5", group_stats(b_lt5)), (">=5", group_stats(b_ge5)),
    ])

    # 3. exact groups
    base.print_header("3. EXACTE FILL-GROEPEN (2,3,4,5,6,7+)")
    exact_rows = []
    for k in (2, 3, 4, 5, 6):
        exact_rows.append((str(k), group_stats([t for t in active if t["n_buy_fills"] == k])))
    exact_rows.append(("7+", group_stats([t for t in active if t["n_buy_fills"] >= 7])))
    print_group_table(exact_rows)
    print("  (*klein N* = N < 10, statistisch zwak)")

    # 4. gross loss decomposition
    base.print_header("4. GROSS LOSS DECOMPOSITIE")
    losers_sorted = sorted([t for t in all_trades if t["corrected_pnl"] <= 0], key=lambda t: t["corrected_pnl"])

    def loss_share(cond):
        s = abs(sum(t["corrected_pnl"] for t in losers_sorted if cond(t)))
        return s, pct(s, gross_loss)

    sl_loss, sl_pct = loss_share(lambda t: t["close_type_name"] == "STOP_LOSS")
    f5_loss, f5_pct = loss_share(lambda t: t["n_buy_fills"] >= 5)
    f4_loss, f4_pct = loss_share(lambda t: t["n_buy_fills"] >= 4)
    top1 = abs(sum(t["corrected_pnl"] for t in losers_sorted[:1]))
    top3 = abs(sum(t["corrected_pnl"] for t in losers_sorted[:3]))
    top5 = abs(sum(t["corrected_pnl"] for t in losers_sorted[:5]))
    print(f"  % van gross loss uit STOP_LOSS:   {sl_pct:6.1f}%  ({sl_loss:.3f})")
    print(f"  % van gross loss uit >=5 fills:   {f5_pct:6.1f}%  ({f5_loss:.3f})")
    print(f"  % van gross loss uit >=4 fills:   {f4_pct:6.1f}%  ({f4_loss:.3f})")
    print(f"  % van gross loss uit top-1:       {pct(top1, gross_loss):6.1f}%  ({top1:.3f})")
    print(f"  % van gross loss uit top-3:       {pct(top3, gross_loss):6.1f}%  ({top3:.3f})")
    print(f"  % van gross loss uit top-5:       {pct(top5, gross_loss):6.1f}%  ({top5:.3f})")

    # 5. overlap
    base.print_header("5. OVERLAP >=5 FILLS <-> STOP_LOSS")
    f5_trades = [t for t in all_trades if t["n_buy_fills"] >= 5]
    sl_trades = [t for t in all_trades if t["close_type_name"] == "STOP_LOSS"]
    f5_and_sl = sum(1 for t in f5_trades if t["close_type_name"] == "STOP_LOSS")
    sl_and_f5 = sum(1 for t in sl_trades if t["n_buy_fills"] >= 5)
    print(f"  >=5-fill trades die eindigen in STOP_LOSS: {f5_and_sl}/{len(f5_trades)}")
    print(f"  STOP_LOSS trades met >=5 fills:            {sl_and_f5}/{len(sl_trades)}")

    # 6. all STOP_LOSS trade detail
    base.print_header("6. ALLE STOP_LOSS TRADES (detail)")
    print(f"  {'Pair':<13}{'Fills':>6}{'Filled':>9}{'PnL':>9}{'PnL%':>8}{'Hold':>7}"
          f"{'1e buy':>10}{'lst buy':>10}{'avg buy':>10}{'close':>10}")
    for t in sl_trades:
        buys, sells = price_stats(conn, t["pair"], t["ts"], t["cts"] or t["ts"])
        first_buy = buys[0] if buys else 0.0
        last_buy = buys[-1] if buys else 0.0
        avg_buy = statistics.mean(buys) if buys else 0.0
        close_p = statistics.mean(sells) if sells else 0.0
        loss_pct_v = pct(t["corrected_pnl"], t["filled_quote"]) if t["filled_quote"] else 0.0
        print(f"  {t['pair']:<13}{t['n_buy_fills']:>6}{t['filled_quote']:>9.2f}{t['corrected_pnl']:>+9.3f}"
              f"{loss_pct_v:>+7.2f}%{t['hold_min'] / 60:>6.1f}h"
              f"{first_buy:>10.5f}{last_buy:>10.5f}{avg_buy:>10.5f}{close_p:>10.5f}")

    conn.close()


if __name__ == "__main__":
    main()
