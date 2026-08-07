"""
Parser and analyzer for momentum sleeve paper trade log lines.

Parses three log prefixes:
  [MOMENTUM_PAPER_ENTRY]   — position opened
  [MOMENTUM_PAPER_EXIT]    — position closed
  [MOMENTUM_PAPER_SUMMARY] — periodic summary (informational only)
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Regex patterns matching the logger.info format in MomentumSleeveManager
# ---------------------------------------------------------------------------

_RE_ENTRY = re.compile(
    r"\[MOMENTUM_PAPER_ENTRY\]\s+"
    r"pair=(\S+)\s+score=([\d.]+)\s+entry=([\d.]+)\s+"
    r"sl=([\d.]+)\s+tp=([\d.]+)\s+trail_act=([\d.]+)\s+"
    r"size_quote=([\d.]+)\s+regime=(\S+)\s+vol_exp=([\d.]+)"
)

_RE_EXIT = re.compile(
    r"\[MOMENTUM_PAPER_EXIT\]\s+"
    r"pair=(\S+)\s+reason=(\S+)\s+"
    r"entry=([\d.]+)\s+exit=([\d.]+)\s+"
    r"pnl_quote=(-?[\d.]+)\s+pnl_pct=(-?[\d.]+)%%?\s+"
    r"hold=(\d+)s\s+mfe=([\d.]+)%%?\s+mae=([\d.]+)%%?"
)

_RE_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PaperEntry:
    timestamp: str
    pair: str
    score: float
    entry_price: float
    regime: str
    vol_exp: float
    size_quote: float


@dataclass
class PaperExit:
    timestamp: str
    pair: str
    exit_reason: str
    entry_price: float
    exit_price: float
    pnl_quote: float
    pnl_pct: float
    hold_sec: int
    mfe_pct: float
    mae_pct: float


@dataclass
class MatchedTrade:
    entry: PaperEntry
    exit: PaperExit


@dataclass
class AnalysisResult:
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate_pct: Optional[float]
    total_pnl_quote: float
    avg_pnl_pct: Optional[float]
    best_pnl_pct: Optional[float]
    worst_pnl_pct: Optional[float]
    avg_hold_minutes: Optional[float]
    by_exit_reason: Dict[str, dict]
    by_regime: Dict[str, dict]
    by_pair: Dict[str, dict]
    unmatched_exits: int
    trades: List[MatchedTrade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _ts(line: str) -> str:
    m = _RE_TS.match(line)
    return m.group(1) if m else ""


def parse_lines(lines) -> Tuple[List[PaperEntry], List[PaperExit]]:
    """
    Parse an iterable of log lines.

    Returns (entries, exits).  Lines without the expected prefixes are skipped.
    """
    entries: List[PaperEntry] = []
    exits: List[PaperExit] = []

    for line in lines:
        if "[MOMENTUM_PAPER_ENTRY]" in line:
            m = _RE_ENTRY.search(line)
            if m:
                entries.append(PaperEntry(
                    timestamp=_ts(line),
                    pair=m.group(1),
                    score=float(m.group(2)),
                    entry_price=float(m.group(3)),
                    regime=m.group(8),
                    vol_exp=float(m.group(9)),
                    size_quote=float(m.group(7)),
                ))
        elif "[MOMENTUM_PAPER_EXIT]" in line:
            m = _RE_EXIT.search(line)
            if m:
                exits.append(PaperExit(
                    timestamp=_ts(line),
                    pair=m.group(1),
                    exit_reason=m.group(2),
                    entry_price=float(m.group(3)),
                    exit_price=float(m.group(4)),
                    pnl_quote=float(m.group(5)),
                    pnl_pct=float(m.group(6)),
                    hold_sec=int(m.group(7)),
                    mfe_pct=float(m.group(8)),
                    mae_pct=float(m.group(9)),
                ))

    return entries, exits


def parse_log_files(file_paths) -> Tuple[List[PaperEntry], List[PaperExit]]:
    """Read and parse one or more log files."""
    all_entries: List[PaperEntry] = []
    all_exits: List[PaperExit] = []

    for path in file_paths:
        with open(path, errors="replace") as fh:
            entries, exits = parse_lines(fh)
            all_entries.extend(entries)
            all_exits.extend(exits)

    return all_entries, all_exits


# ---------------------------------------------------------------------------
# Matching entries → exits
# ---------------------------------------------------------------------------

def match_trades(entries: List[PaperEntry], exits: List[PaperExit]) -> Tuple[List[MatchedTrade], int]:
    """
    Match entries to exits by (pair, entry_price).

    Returns (matched_trades, unmatched_exit_count).
    A position is open (not yet exited) if no matching exit is found.
    """
    # Build lookup: (pair, entry_price_str) -> list of entries (FIFO)
    entry_map: Dict[Tuple[str, str], List[PaperEntry]] = {}
    for e in entries:
        key = (e.pair, f"{e.entry_price:.6f}")
        entry_map.setdefault(key, []).append(e)

    matched: List[MatchedTrade] = []
    unmatched = 0

    for ex in exits:
        key = (ex.pair, f"{ex.entry_price:.6f}")
        queue = entry_map.get(key, [])
        if queue:
            matched.append(MatchedTrade(entry=queue.pop(0), exit=ex))
        else:
            unmatched += 1

    return matched, unmatched


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _bucket_stats(trades: List[MatchedTrade], key_fn) -> Dict[str, dict]:
    """Group trades by key_fn and compute per-bucket stats."""
    buckets: Dict[str, List[MatchedTrade]] = {}
    for t in trades:
        k = key_fn(t)
        buckets.setdefault(k, []).append(t)

    result = {}
    for k, bucket in sorted(buckets.items()):
        pnls = [t.exit.pnl_pct for t in bucket]
        wins = [p for p in pnls if p > 0]
        result[k] = {
            "trades": len(bucket),
            "wins": len(wins),
            "win_rate_pct": round(len(wins) / len(bucket) * 100, 1),
            "total_pnl_quote": round(sum(t.exit.pnl_quote for t in bucket), 4),
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 3),
        }
    return result


def analyze(trades: List[MatchedTrade], unmatched_exits: int = 0) -> AnalysisResult:
    """Compute aggregate statistics over a list of matched trades."""
    n = len(trades)
    if n == 0:
        return AnalysisResult(
            total_trades=0, win_trades=0, loss_trades=0,
            win_rate_pct=None, total_pnl_quote=0.0,
            avg_pnl_pct=None, best_pnl_pct=None, worst_pnl_pct=None,
            avg_hold_minutes=None,
            by_exit_reason={}, by_regime={}, by_pair={},
            unmatched_exits=unmatched_exits,
        )

    pnl_quotes = [t.exit.pnl_quote for t in trades]
    pnl_pcts = [t.exit.pnl_pct for t in trades]
    wins = [p for p in pnl_pcts if p > 0]
    holds = [t.exit.hold_sec for t in trades]

    return AnalysisResult(
        total_trades=n,
        win_trades=len(wins),
        loss_trades=n - len(wins),
        win_rate_pct=round(len(wins) / n * 100, 1),
        total_pnl_quote=round(sum(pnl_quotes), 4),
        avg_pnl_pct=round(sum(pnl_pcts) / n, 3),
        best_pnl_pct=round(max(pnl_pcts), 3),
        worst_pnl_pct=round(min(pnl_pcts), 3),
        avg_hold_minutes=round(sum(holds) / n / 60, 1),
        by_exit_reason=_bucket_stats(trades, lambda t: t.exit.exit_reason),
        by_regime=_bucket_stats(trades, lambda t: t.entry.regime),
        by_pair=_bucket_stats(trades, lambda t: t.entry.pair),
        unmatched_exits=unmatched_exits,
        trades=trades,
    )


def format_report(result: AnalysisResult) -> str:
    """Return a human-readable multi-line report string."""
    lines = []
    a = lines.append

    a("=" * 60)
    a("  MOMENTUM SLEEVE — PAPER TRADE REPORT")
    a("=" * 60)

    if result.total_trades == 0:
        a("  No completed trades found in logs.")
        a("=" * 60)
        return "\n".join(lines)

    a(f"  Total trades     : {result.total_trades}")
    a(f"  Wins / Losses    : {result.win_trades} / {result.loss_trades}")
    a(f"  Win rate         : {result.win_rate_pct:.1f}%")
    a(f"  Total PnL        : {result.total_pnl_quote:+.4f} quote")
    a(f"  Avg PnL          : {result.avg_pnl_pct:+.3f}%")
    a(f"  Best trade       : {result.best_pnl_pct:+.3f}%")
    a(f"  Worst trade      : {result.worst_pnl_pct:+.3f}%")
    a(f"  Avg hold time    : {result.avg_hold_minutes:.1f} min")
    if result.unmatched_exits:
        a(f"  ⚠ Unmatched exits: {result.unmatched_exits} (position open at log end?)")

    def _table(title, bucket):
        if not bucket:
            return
        a("")
        a(f"  {title}")
        a(f"  {'Key':<20} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalPnL':>10} {'AvgPnL%':>8}")
        a("  " + "-" * 60)
        for k, s in bucket.items():
            a(f"  {k:<20} {s['trades']:>6} {s['wins']:>5} {s['win_rate_pct']:>5.1f}% "
              f"{s['total_pnl_quote']:>+10.4f} {s['avg_pnl_pct']:>+7.3f}%")

    _table("BY EXIT REASON", result.by_exit_reason)
    _table("BY REGIME", result.by_regime)
    _table("BY PAIR", result.by_pair)

    a("")
    a("=" * 60)
    return "\n".join(lines)
