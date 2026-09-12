#!/usr/bin/env python3
"""Standalone Bitget spot-grid performance analysis (no AI cost, no MCP needed).

Analyzes data/spot_grid_bitget.sqlite for a given date range and reports:
  1. Overall totals (executor PnL vs TradeFill-corrected PnL, winrate, expectancy)
  2. Breakdown per close_type
  3. Top-N real losing trades
  4. Buy-fill accumulation buckets (winrate/PnL as fills increase)
  5. Outlier sensitivity (result with/without top-N losers)

Known bookkeeping bug (BCH-USDT, 2026-09-08, fixed in grid_executor.py 2026-09-10):
a close-order race condition could leave `Executors.net_pnl_quote` showing a
near-total phantom loss for a trade that was actually sold normally on the
exchange. This script detects that exact signature
(realized_buy_size_quote > 0 AND realized_sell_size_quote == 0) and
recomputes the real PnL directly from `TradeFill` for those trades.

Usage:
    python tools/analyze_trading_performance.py [--db PATH] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--top N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

CLOSE_TYPE_NAMES = {
    1: "TAKE_PROFIT",
    2: "STOP_LOSS",
    3: "TIME_LIMIT",
    4: "EARLY_STOP",
    5: "TRAILING_STOP",
    6: "FAILED",
    7: "FAILED_CANCELLED",
    8: "EXPIRED",
    9: "POSITION_HOLD",
    10: "INSUFFICIENT_BALANCE",
    11: "NO_FILL_TIMEOUT",
    12: "NO_PROGRESS_TIMEOUT",
    13: "LIQUIDATION",
    14: "HARD_CAP_TIME_LIMIT",
}

TRADEFILL_SCALE = 1e-8  # price/amount encoding, see memories/repo/tradefill-encoding.md


def close_type_name(code: Optional[int]) -> str:
    if code is None:
        return "UNKNOWN"
    return CLOSE_TYPE_NAMES.get(code, f"OTHER({code})")


def safe_json(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def tradefill_pnl(
    conn: sqlite3.Connection, symbol: str, start_ts: float, end_ts: float, pad_sec: float = 5.0
) -> Optional[float]:
    """Recompute real economic PnL for one trade window directly from TradeFill.

    Returns None if no fills found. Caller is responsible for only trusting
    this for isolated (non-overlapping) trades of that symbol.
    """
    start_ms = int((start_ts - pad_sec) * 1000)
    end_ms = int((end_ts + pad_sec) * 1000)
    cur = conn.execute(
        "SELECT trade_type, price, amount, trade_fee FROM TradeFill "
        "WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
        (symbol, start_ms, end_ms),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    buys_q = sells_q = 0.0
    for trade_type, price_raw, amount_raw, fee_raw in rows:
        price = price_raw * TRADEFILL_SCALE
        amount = amount_raw * TRADEFILL_SCALE
        fee_amt = 0.0
        try:
            fee = json.loads(fee_raw) if fee_raw else {}
            fee_amt = sum(float(f["amount"]) for f in fee.get("flat_fees", []))
        except Exception:
            pass
        quote_val = price * amount
        if trade_type == "BUY":
            buys_q += quote_val + fee_amt
        else:
            sells_q += quote_val - fee_amt
    return sells_q - buys_q


def load_trades(conn: sqlite3.Connection, start_ts: float, end_ts: float) -> list[dict]:
    cur = conn.execute(
        "SELECT id, timestamp, close_timestamp, close_type, net_pnl_quote, "
        "cum_fees_quote, filled_amount_quote, config, custom_info "
        "FROM Executors WHERE timestamp>=? AND timestamp<=? "
        "AND is_active=0 AND close_type IS NOT NULL ORDER BY timestamp",
        (start_ts, end_ts),
    )
    rows = cur.fetchall()

    # Build per-symbol time windows so we can detect true temporal overlap
    # (not just "traded more than once in the period") before trusting a
    # TradeFill-based correction for a suspect trade.
    symbol_windows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for eid, ts, cts, ct_int, pnl, fees, filled, cfg_raw, ci_raw in rows:
        cfg = safe_json(cfg_raw)
        symbol_windows[cfg.get("trading_pair", "?")].append((ts, cts or ts))

    def has_overlap(pair: str, ts: float, cts: float, pad: float = 5.0) -> bool:
        lo, hi = ts - pad, cts + pad
        overlaps = 0
        for w_start, w_end in symbol_windows[pair]:
            if w_start <= hi and w_end >= lo:
                overlaps += 1
        return overlaps > 1  # itself always overlaps; >1 means another trade overlaps too

    trades = []
    for eid, ts, cts, ct_int, pnl, fees, filled, cfg_raw, ci_raw in rows:
        cfg = safe_json(cfg_raw)
        ci = safe_json(ci_raw)
        pair = cfg.get("trading_pair", "?")
        filled_orders = ci.get("filled_orders", [])
        n_buy = sum(1 for fo in filled_orders if fo.get("trade_type") == "BUY")
        n_sell = sum(1 for fo in filled_orders if fo.get("trade_type") == "SELL")
        realized_buy = safe_float(ci.get("realized_buy_size_quote"))
        realized_sell = safe_float(ci.get("realized_sell_size_quote"))
        db_pnl = safe_float(pnl)
        fees_f = safe_float(fees)
        filled_f = safe_float(filled)
        hold_min = ((cts or ts) - ts) / 60.0

        is_bug_signature = realized_buy > 0.5 and realized_sell == 0 and n_buy > 0
        corrected_pnl = db_pnl
        correction_note = ""
        if is_bug_signature:
            # Only trust a TradeFill-based correction if no OTHER trade for
            # this symbol temporally overlaps this trade's window (avoids
            # attributing a neighboring trade's fills to this one).
            if not has_overlap(pair, ts, cts or ts):
                real = tradefill_pnl(conn, pair, ts, cts or ts)
                if real is not None:
                    corrected_pnl = real
                    correction_note = "TradeFill-corrected (bookkeeping bug signature)"
            else:
                correction_note = "SUSPECT bug signature but overlapping same-symbol trade - not auto-corrected"

        trades.append({
            "id": eid, "ts": ts, "cts": cts, "pair": pair,
            "close_type": ct_int, "close_type_name": close_type_name(ct_int),
            "db_pnl": db_pnl, "corrected_pnl": corrected_pnl, "correction_note": correction_note,
            "fees": fees_f, "filled_quote": filled_f, "hold_min": hold_min,
            "n_buy_fills": n_buy, "n_sell_fills": n_sell,
        })
    return trades


def pct(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def print_header(title: str):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def section_overall(trades: list[dict]):
    print_header("1. TOTAAL RESULTAAT")
    n = len(trades)
    db_total = sum(t["db_pnl"] for t in trades)
    corr_total = sum(t["corrected_pnl"] for t in trades)
    fees_total = sum(t["fees"] for t in trades)
    winners = [t for t in trades if t["corrected_pnl"] > 0]
    losers = [t for t in trades if t["corrected_pnl"] <= 0]
    winrate = pct(len(winners), n)
    avg_win = statistics.mean([t["corrected_pnl"] for t in winners]) if winners else 0.0
    avg_loss = statistics.mean([t["corrected_pnl"] for t in losers]) if losers else 0.0
    gross_win = sum(t["corrected_pnl"] for t in winners)
    gross_loss = abs(sum(t["corrected_pnl"] for t in losers))
    profit_factor = (gross_win / gross_loss) if gross_loss else float("inf")
    expectancy = corr_total / n if n else 0.0

    print(f"  Gesloten trades:              {n}")
    print(f"  Executor PnL (DB, RAW):       {db_total:+.4f} USDT")
    print(f"  Gecorrigeerde werkelijke PnL: {corr_total:+.4f} USDT")
    print(f"  Totale fees:                  {fees_total:.4f} USDT")
    print(f"  Winrate:                      {winrate:.1f}% ({len(winners)}/{n})")
    print(f"  Gemiddelde winsttrade:        {avg_win:+.4f} USDT")
    print(f"  Gemiddelde verliestrade:      {avg_loss:+.4f} USDT")
    print(f"  Profit factor:                {profit_factor:.2f}")
    print(f"  Expectancy per trade:         {expectancy:+.4f} USDT")

    corrections = [t for t in trades if t["correction_note"].startswith("TradeFill")]
    if corrections:
        print(f"\n  Boekhoud-correcties toegepast: {len(corrections)}")
        for t in corrections:
            print(f"    {t['pair']:<12} DB={t['db_pnl']:+.4f}  Corrected={t['corrected_pnl']:+.4f}  "
                  f"(diff {t['corrected_pnl'] - t['db_pnl']:+.4f})")
    return {"n": n, "db_total": db_total, "corr_total": corr_total, "fees_total": fees_total,
            "winrate": winrate, "profit_factor": profit_factor, "expectancy": expectancy}


def section_by_close_type(trades: list[dict], total_loss: float):
    print_header("2. RESULTAAT PER CLOSE_TYPE")
    by_type = defaultdict(list)
    for t in trades:
        by_type[t["close_type_name"]].append(t)

    print(f"  {'Type':<20} {'N':>4}  {'Totaal PnL':>11}  {'Gem PnL':>9}  {'Gem hold':>9}  {'% v/h verlies':>13}")
    print("  " + "-" * 78)
    for name, ts in sorted(by_type.items(), key=lambda kv: sum(t["corrected_pnl"] for t in kv[1])):
        total = sum(t["corrected_pnl"] for t in ts)
        avg = total / len(ts)
        avg_hold = statistics.mean([t["hold_min"] for t in ts]) / 60.0
        share = pct(-min(total, 0), abs(total_loss)) if total_loss else 0.0
        print(f"  {name:<20} {len(ts):>4}  {total:>+11.4f}  {avg:>+9.4f}  {avg_hold:>8.1f}h  {share:>12.1f}%")


def section_top_losers(trades: list[dict], top_n: int):
    print_header(f"3. TOP {top_n} ECHTE VERLIESTRADES")
    losers = sorted(trades, key=lambda t: t["corrected_pnl"])[:top_n]
    print(f"  {'Datum':<12} {'Pair':<12} {'Type':<16} {'PnL':>9}  {'Fees':>7}  {'Hold':>7}  "
          f"{'Buys':>5}  {'Sells':>5}  {'Filled':>8}  {'Loss%':>7}")
    print("  " + "-" * 100)
    for t in losers:
        d = dt.datetime.fromtimestamp(t["ts"], dt.timezone.utc).strftime("%Y-%m-%d")
        loss_pct = pct(t["corrected_pnl"], t["filled_quote"]) if t["filled_quote"] else 0.0
        print(f"  {d:<12} {t['pair']:<12} {t['close_type_name']:<16} {t['corrected_pnl']:>+9.4f}  "
              f"{t['fees']:>7.4f}  {t['hold_min'] / 60:>6.1f}h  {t['n_buy_fills']:>5}  "
              f"{t['n_sell_fills']:>5}  {t['filled_quote']:>8.2f}  {loss_pct:>6.1f}%")
        if t["correction_note"]:
            print(f"       note: {t['correction_note']}")
    return losers


def section_buy_fill_buckets(trades: list[dict]):
    print_header("6b. WINRATE / PnL PER AANTAL BUY-FILLS")
    print(f"  {'Buy fills':>10}  {'N':>5}  {'Winrate':>8}  {'Gem PnL':>9}  {'Totaal PnL':>11}")
    print("  " + "-" * 55)
    for n_fills in range(0, 8):
        bucket = [t for t in trades if t["n_buy_fills"] == n_fills]
        if not bucket:
            continue
        wins = sum(1 for t in bucket if t["corrected_pnl"] > 0)
        wr = pct(wins, len(bucket))
        total = sum(t["corrected_pnl"] for t in bucket)
        avg = total / len(bucket)
        label = f"{n_fills}" if n_fills < 7 else "7+"
        print(f"  {label:>10}  {len(bucket):>5}  {wr:>7.1f}%  {avg:>+9.4f}  {total:>+11.4f}")


def section_winners_vs_losers(trades: list[dict]):
    print_header("6a. WINNAARS VS VERLIEZERS")
    winners = [t for t in trades if t["corrected_pnl"] > 0]
    losers = [t for t in trades if t["corrected_pnl"] <= 0]

    def avg(lst, key):
        return statistics.mean([t[key] for t in lst]) if lst else 0.0

    print(f"  {'Metric':<28} {'Winnaars':>12}  {'Verliezers':>12}")
    print("  " + "-" * 56)
    print(f"  {'Aantal':<28} {len(winners):>12}  {len(losers):>12}")
    print(f"  {'Gem. hold time (h)':<28} {avg(winners, 'hold_min') / 60:>12.1f}  {avg(losers, 'hold_min') / 60:>12.1f}")
    print(f"  {'Gem. buy fills':<28} {avg(winners, 'n_buy_fills'):>12.2f}  {avg(losers, 'n_buy_fills'):>12.2f}")
    print(f"  {'Gem. positieomvang':<28} {avg(winners, 'filled_quote'):>12.2f}  {avg(losers, 'filled_quote'):>12.2f}")
    print(f"  {'Gem. fees':<28} {avg(winners, 'fees'):>12.4f}  {avg(losers, 'fees'):>12.4f}")

    win_pairs = defaultdict(int)
    loss_pairs = defaultdict(int)
    for t in winners:
        win_pairs[t["pair"]] += 1
    for t in losers:
        loss_pairs[t["pair"]] += 1
    print("\n  Top pairs (winnaars):", sorted(win_pairs.items(), key=lambda x: -x[1])[:5])
    print("  Top pairs (verliezers):", sorted(loss_pairs.items(), key=lambda x: -x[1])[:5])


def section_outliers(trades: list[dict]):
    print_header("7. OUTLIER-ANALYSE")
    sorted_by_pnl = sorted(trades, key=lambda t: t["corrected_pnl"])
    total = sum(t["corrected_pnl"] for t in trades)
    print(f"  Resultaat inclusief alle trades:        {total:+.4f} USDT")
    for n in (1, 3, 5):
        excl = sorted_by_pnl[n:]
        excl_total = sum(t["corrected_pnl"] for t in excl)
        removed = [f"{t['pair']}({t['corrected_pnl']:+.2f})" for t in sorted_by_pnl[:n]]
        print(f"  Zonder top {n} verlies{'zen' if n > 1 else ''} ({', '.join(removed)}): {excl_total:+.4f} USDT")


def section_categories(trades: list[dict], losers: list[dict]):
    print_header("5. VERLIESCATEGORIEEN (top losers geclassificeerd)")
    categories = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    total_loss_all = sum(t["corrected_pnl"] for t in trades if t["corrected_pnl"] < 0)
    for t in losers:
        if t["correction_note"].startswith("TradeFill"):
            cat = "execution/bookkeeping"
        elif t["n_buy_fills"] >= 4:
            cat = "accumulation / te veel fills"
        elif t["hold_min"] >= 240:
            cat = "te lange holding / late exit"
        elif t["close_type_name"] in ("STOP_LOSS", "TRAILING_STOP"):
            cat = "normale markt/SL-verliezen"
        else:
            cat = "fees / onvoldoende edge"
        categories[cat]["n"] += 1
        categories[cat]["pnl"] += t["corrected_pnl"]

    print(f"  (Gebaseerd op de geanalyseerde top-verliezers; totaal verlies alle trades: {total_loss_all:+.4f})")
    print(f"  {'Categorie':<32} {'N':>4}  {'PnL':>10}  {'% v/h verlies':>13}")
    print("  " + "-" * 65)
    for cat, d in sorted(categories.items(), key=lambda kv: kv[1]["pnl"]):
        share = pct(-d["pnl"], abs(total_loss_all)) if total_loss_all else 0.0
        print(f"  {cat:<32} {d['n']:>4}  {d['pnl']:>+10.4f}  {share:>12.1f}%")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/spot_grid_bitget.sqlite")
    parser.add_argument("--start", default="2026-08-08")
    parser.add_argument("--end", default=None, help="Default: now")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    start_ts = dt.datetime.strptime(args.start, "%Y-%m-%d").timestamp()
    end_ts = dt.datetime.strptime(args.end, "%Y-%m-%d").timestamp() if args.end else dt.datetime.now().timestamp()

    conn = sqlite3.connect(str(db_path))
    trades = load_trades(conn, start_ts, end_ts)
    conn.close()

    if not trades:
        print("Geen gesloten trades gevonden in deze periode.")
        return

    print(f"\nBitget spot-grid analyse: {args.start} t/m "
          f"{dt.datetime.fromtimestamp(end_ts, dt.timezone.utc).strftime('%Y-%m-%d')}")

    summary = section_overall(trades)
    loss_total = (
        summary["corr_total"] if summary["corr_total"] < 0
        else sum(t["corrected_pnl"] for t in trades if t["corrected_pnl"] < 0)
    )
    section_by_close_type(trades, loss_total)
    losers = section_top_losers(trades, args.top)
    section_categories(trades, losers)
    section_winners_vs_losers(trades)
    section_buy_fill_buckets(trades)
    section_outliers(trades)
    print()


if __name__ == "__main__":
    main()
