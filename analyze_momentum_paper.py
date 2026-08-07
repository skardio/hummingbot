#!/usr/bin/env python3
"""
Analyze momentum sleeve paper trade results from bot logs.

Usage:
    python analyze_momentum_paper.py                    # last 7 days, all bots
    python analyze_momentum_paper.py --since 1          # only today's logs
    python analyze_momentum_paper.py --since 0          # all-time (slow: scans all archives)
    python analyze_momentum_paper.py --bot usd          # Kraken USD only
    python analyze_momentum_paper.py --bot okx          # OKX only
    python analyze_momentum_paper.py --bot bitget       # Bitget only
    python analyze_momentum_paper.py --log path/to/file.log [more.log ...]
"""

import argparse
import glob
import os
import sys
import time
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from multi_coin_grid_pro.tools.momentum_paper_analyzer import (  # noqa: E402
    analyze,
    format_report,
    match_trades,
    parse_log_files,
)

LOG_GLOBS = {
    "usd": ["logs/**/logs_multi_coin_grid_v2_usd_*.log*"],
    "eur": ["logs/**/logs_multi_coin_grid_v2_20*.log*"],
    "okx": ["logs/**/logs_spot_grid_okx_*.log*"],
    "bitget": ["logs/**/logs_spot_grid_bitget_*.log*"],
}


def _find_logs(bot: str, since_days: float) -> list:
    all_files = []
    for pattern in LOG_GLOBS[bot]:
        all_files.extend(glob.glob(pattern, recursive=True))

    if since_days > 0:
        cutoff = time.time() - since_days * 86400
        all_files = [f for f in all_files if os.path.getmtime(f) >= cutoff]

    # Sort rotated files so oldest (.log.N, highest N) come first, current .log last.
    rotated = sorted([f for f in all_files if not f.endswith(".log")],
                     key=lambda x: -int(x.rsplit(".", 1)[-1]))
    base = [f for f in all_files if f.endswith(".log")]
    return rotated + base


def main():
    parser = argparse.ArgumentParser(description="Momentum paper trade log analyzer")
    parser.add_argument("--bot", choices=["usd", "eur", "okx", "bitget", "all"], default="all",
                        help="Which bot's logs to analyze (default: all)")
    parser.add_argument("--since", type=float, default=7,
                        metavar="DAYS",
                        help="Only scan files modified within N days (default: 7). "
                             "Use 0 for all-time (slow).")
    parser.add_argument("--log", nargs="+", metavar="FILE",
                        help="Explicit log file(s) to parse (overrides --bot/--since)")
    args = parser.parse_args()

    if args.log:
        log_files = args.log
    else:
        explicit = args.bot != "all"
        bots = ["usd", "eur", "okx", "bitget"] if args.bot == "all" else [args.bot]
        log_files = []
        for bot in bots:
            found = _find_logs(bot, since_days=args.since)
            if not found and explicit:
                patterns = ", ".join(LOG_GLOBS[bot])
                print(f"⚠  No log files found for {bot} bot (patterns: {patterns})")
            log_files.extend(found)

    if not log_files:
        label = f"last {args.since}d" if args.since > 0 else "all-time"
        print(f"No log files to analyze ({label}).")
        sys.exit(0)

    label = f"last {args.since}d" if args.since > 0 else "all-time"
    print(f"Parsing {len(log_files)} log file(s) ({label})...")
    entries, exits = parse_log_files(log_files)
    print(f"  Found {len(entries)} entries, {len(exits)} exits")

    trades, unmatched = match_trades(entries, exits)
    result = analyze(trades, unmatched_exits=unmatched)

    print(format_report(result))


if __name__ == "__main__":
    main()
