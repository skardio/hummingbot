#!/usr/bin/env python3
"""
Momentum Scalper Trade Analyzer

Analyzes JSON-based trade logs from your hybrid scalper.
Expected file format in momentum_trades.json:
{
  "timestamp": "...",
  "symbol": "SOL/USDT",
  "direction": "long",
  "entry_price": ...,
  "exit_price": ...,
  "gross_pnl_pct": ...,
  "net_pnl_pct": ...,
  "net_pnl_usdt": ...,
  "fees_pct": ...,
  "reason": "...",
  "hold_time": ...
}

Usage:
  python3 analyze_trades.py [path_to_trades.json]

  Default: logs/momentum_trades.json
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

try:
    import numpy as np
except ImportError:
    print("❌ numpy required. Run: pip install numpy")
    sys.exit(1)


def load_trades(path: str) -> List[Dict]:
    """Load trades from JSON log file."""
    trades = []
    if not os.path.exists(path):
        print(f"❌ File not found: {path}")
        return trades

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ Skipped invalid JSON line: {e}")
                continue

    return trades


def compute_equity_curve(trades: List[Dict]) -> List[float]:
    """Compute cumulative equity curve."""
    equity = []
    total = 0.0
    for t in trades:
        total += t.get("net_pnl_usdt", 0)
        equity.append(total)
    return equity


def max_drawdown(equity: List[float]) -> float:
    """Calculate maximum drawdown from equity curve."""
    if not equity:
        return 0.0

    peak = equity[0]
    max_dd = 0.0

    for value in equity:
        if value > peak:
            peak = value
        dd = peak - value
        max_dd = max(max_dd, dd)

    return max_dd


def sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from list of returns."""
    if not returns or len(returns) < 2:
        return 0.0

    mean_return = np.mean(returns)
    std_return = np.std(returns)

    if std_return == 0:
        return 0.0

    return (mean_return - risk_free_rate) / std_return


def analyze(trade_file: str = None):
    """Analyze all trades and print comprehensive report."""
    # Auto-detect trade log location
    if trade_file is None:
        possible_paths = [
            "logs/momentum_trades.json",  # Local
            "../../logs/momentum_trades.json",  # From script dir to repo root
            "/home/mo/repos/hummingbot/logs/momentum_trades.json",  # Absolute
        ]

        for path in possible_paths:
            if os.path.exists(path):
                trade_file = path
                break

        if trade_file is None:
            trade_file = "logs/momentum_trades.json"  # Fallback

    trades = load_trades(trade_file)

    if not trades:
        print("⚠️ No trades found.")
        return

    print()
    print("=" * 70)
    print("  MOMENTUM SCALPER - TRADE ANALYSIS")
    print("=" * 70)
    print()
    print(f"📁 File: {trade_file}")
    print(f"📊 Loaded {len(trades)} trades")
    print()

    # Separate wins/losses
    wins = [t for t in trades if t.get("net_pnl_usdt", 0) > 0]
    losses = [t for t in trades if t.get("net_pnl_usdt", 0) <= 0]

    # Calculate metrics
    total_pnl = sum(t.get("net_pnl_usdt", 0) for t in trades)
    avg_win = np.mean([t["net_pnl_usdt"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["net_pnl_usdt"] for t in losses]) if losses else 0
    winrate = len(wins) / len(trades) * 100 if trades else 0

    win_total = abs(sum(t["net_pnl_usdt"] for t in wins))
    loss_total = abs(sum(t["net_pnl_usdt"] for t in losses))
    profit_factor = win_total / loss_total if loss_total > 0 else float("inf")

    expectancy = (winrate / 100) * avg_win + (1 - winrate / 100) * avg_loss

    # Equity curve & drawdown
    equity = compute_equity_curve(trades)
    max_dd = max_drawdown(equity)

    # Hold time
    avg_hold = np.mean([t.get("hold_time", 0) for t in trades])

    # Returns for Sharpe
    returns = [t.get("net_pnl_pct", 0) for t in trades]
    sharpe = sharpe_ratio(returns) if len(returns) >= 2 else 0.0

    # Print results
    print("=" * 70)
    print("  📈 PERFORMANCE METRICS")
    print("=" * 70)
    print()
    print(f"{'Total PNL:':<25} {total_pnl:>10.2f} USDT")
    print(f"{'Trades:':<25} {len(trades):>10}")
    print(f"{'Wins:':<25} {len(wins):>10} ({winrate:.1f}%)")
    print(f"{'Losses:':<25} {len(losses):>10} ({100 - winrate:.1f}%)")
    print()
    print(f"{'Average Win:':<25} {avg_win:>10.3f} USDT")
    print(f"{'Average Loss:':<25} {avg_loss:>10.3f} USDT")
    print(f"{'Profit Factor:':<25} {profit_factor:>10.2f}")
    print(f"{'Expectancy/trade:':<25} {expectancy:>10.4f} USDT")
    print()
    print(f"{'Avg Hold Time:':<25} {avg_hold / 60:>10.1f} minutes")
    print(f"{'Max Drawdown:':<25} {max_dd:>10.2f} USDT")
    print(f"{'Sharpe Ratio:':<25} {sharpe:>10.2f}")
    print()

    # Per-symbol breakdown
    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t["symbol"]].append(t)

    print("=" * 70)
    print("  📊 PER-SYMBOL PERFORMANCE")
    print("=" * 70)
    print()
    print(f"{'Symbol':<12} | {'Trades':>6} | {'Winrate':>7} | {'Avg Win':>8} | {'Avg Loss':>9} | {'Total PNL':>10}")
    print("-" * 70)

    for sym in sorted(by_symbol.keys()):
        tlist = by_symbol[sym]
        pnl = sum(x.get("net_pnl_usdt", 0) for x in tlist)
        wins_s = [x for x in tlist if x.get("net_pnl_usdt", 0) > 0]
        wr = len(wins_s) / len(tlist) * 100 if tlist else 0
        avg_w = np.mean([x["net_pnl_usdt"] for x in wins_s]) if wins_s else 0
        losses_s = [x for x in tlist if x.get("net_pnl_usdt", 0) <= 0]
        avg_l = np.mean([x["net_pnl_usdt"] for x in losses_s]) if losses_s else 0

        print(f"{sym:<12} | {len(tlist):>6} | {wr:>6.1f}% | {avg_w:>8.3f} | {avg_l:>9.3f} | {pnl:>10.2f}")

    print()

    # Hot/Cold streaks
    print("=" * 70)
    print("  🔥 HOT/COLD ANALYSIS")
    print("=" * 70)
    print()

    streak = 0
    longest_win_streak = 0
    for t in trades:
        if t.get("net_pnl_usdt", 0) > 0:
            streak += 1
            longest_win_streak = max(longest_win_streak, streak)
        else:
            streak = 0

    streak = 0
    longest_loss_streak = 0
    for t in trades:
        if t.get("net_pnl_usdt", 0) <= 0:
            streak += 1
            longest_loss_streak = max(longest_loss_streak, streak)
        else:
            streak = 0

    print(f"Longest Win Streak:  {longest_win_streak}")
    print(f"Longest Loss Streak: {longest_loss_streak}")
    print()

    # Exit reason breakdown
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t.get("reason", "Unknown")].append(t.get("net_pnl_usdt", 0))

    print("=" * 70)
    print("  📤 EXIT REASON BREAKDOWN")
    print("=" * 70)
    print()
    print(f"{'Reason':<25} | {'Count':>6} | {'Avg PNL':>10} | {'Total':>10}")
    print("-" * 70)

    for reason in sorted(by_reason.keys(), key=lambda r: len(by_reason[r]), reverse=True):
        pnls = by_reason[reason]
        avg = np.mean(pnls)
        total = sum(pnls)
        print(f"{reason:<25} | {len(pnls):>6} | {avg:>10.3f} | {total:>10.2f}")

    print()

    # Equity curve
    if len(equity) > 0:
        print("=" * 70)
        print("  💰 EQUITY CURVE (Last 100 trades)")
        print("=" * 70)
        print()
        for i, eq in enumerate(equity[-100:], start=max(1, len(equity) - 99)):
            bar_len = int(abs(eq) / max(abs(max(equity)), 1) * 40)
            bar = "█" * bar_len
            sign = "+" if eq >= 0 else ""
            print(f"  #{i:3d}: {sign}{eq:>8.2f} USDT {bar}")
        print()

    print("=" * 70)
    print()


if __name__ == "__main__":
    trade_file = sys.argv[1] if len(sys.argv) > 1 else None
    analyze(trade_file)
