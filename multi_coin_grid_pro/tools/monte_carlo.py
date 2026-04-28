"""
Monte Carlo drawdown survival analysis.

Shuffles historical trade PnL sequences to estimate worst-case drawdown
distributions and ruin probability.

Usage
-----
    python -m multi_coin_grid_pro.tools.monte_carlo \\
        --db data/trade_labels.db \\
        --runs 10000 \\
        --capital 300 \\
        --ruin 30

Output
------
    P95 max drawdown  — 95 % of runs experienced <= this drawdown
    P99 max drawdown  — 99 % of runs experienced <= this drawdown
    Ruin probability  — fraction of runs with drawdown > ruin_threshold %

Part of the 17-upgrade trading bot roadmap:
  Item 17 — Monte Carlo Risk Test
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MonteCarloResult:
    """Aggregate results from a Monte Carlo simulation run."""

    n_runs: int
    p5_max_drawdown_pct: float    # 95 % of runs had <= this drawdown
    p1_max_drawdown_pct: float    # 99 % of runs had <= this drawdown
    ruin_probability_pct: float   # % of runs with drawdown > ruin_threshold
    avg_max_drawdown_pct: float
    ruin_threshold_pct: float


def simulate_single_run(trade_pnls: List[float], starting_capital: float) -> float:
    """
    Simulate one random permutation of *trade_pnls* and return the maximum
    drawdown percentage experienced during that sequence.

    Parameters
    ----------
    trade_pnls : list[float]
        Realised per-trade PnL values (can be positive or negative).
    starting_capital : float
        Starting capital in the same currency as PnL values.

    Returns
    -------
    float
        Maximum drawdown experienced, as a percentage of the peak capital.
    """
    sequence = random.sample(trade_pnls, len(trade_pnls))
    capital = starting_capital
    peak = capital
    max_dd = 0.0
    for pnl in sequence:
        capital += pnl
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def run_monte_carlo(
    trade_pnls: List[float],
    starting_capital: float,
    n_runs: int = 10_000,
    ruin_threshold_pct: float = 30.0,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """
    Run a Monte Carlo simulation on *trade_pnls*.

    Parameters
    ----------
    trade_pnls : list[float]
        Historical per-trade PnL values.
    starting_capital : float
        Capital at simulation start (same units as PnL).
    n_runs : int
        Number of Monte Carlo paths to simulate.
    ruin_threshold_pct : float
        A run is considered "ruin" if its max drawdown exceeds this percentage.
    seed : int, optional
        Random seed for deterministic / reproducible results.

    Returns
    -------
    MonteCarloResult

    Raises
    ------
    ValueError
        If fewer than 10 trades are provided.
    """
    if len(trade_pnls) < 10:
        raise ValueError(f"Need at least 10 trades, got {len(trade_pnls)}")
    if seed is not None:
        random.seed(seed)

    drawdowns = [simulate_single_run(trade_pnls, starting_capital) for _ in range(n_runs)]
    drawdowns.sort()

    p5_idx = int(0.95 * n_runs)
    p1_idx = int(0.99 * n_runs)
    ruin_count = sum(1 for d in drawdowns if d > ruin_threshold_pct)

    return MonteCarloResult(
        n_runs=n_runs,
        p5_max_drawdown_pct=drawdowns[min(p5_idx, len(drawdowns) - 1)],
        p1_max_drawdown_pct=drawdowns[min(p1_idx, len(drawdowns) - 1)],
        ruin_probability_pct=ruin_count / n_runs * 100.0,
        avg_max_drawdown_pct=sum(drawdowns) / len(drawdowns),
        ruin_threshold_pct=ruin_threshold_pct,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo drawdown survival analysis"
    )
    parser.add_argument(
        "--db", default="data/trade_labels.db",
        help="Trade labels SQLite DB path",
    )
    parser.add_argument(
        "--runs", type=int, default=10_000,
        help="Number of Monte Carlo simulation runs",
    )
    parser.add_argument(
        "--capital", type=float, default=300.0,
        help="Starting capital in EUR (or quote currency)",
    )
    parser.add_argument(
        "--ruin", type=float, default=30.0,
        help="Ruin threshold %% (drawdown that constitutes ruin)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducible results",
    )
    args = parser.parse_args()

    import sqlite3
    try:
        conn = sqlite3.connect(args.db)
        rows = conn.execute(
            "SELECT pnl_quote FROM trade_labels ORDER BY timestamp_close"
        ).fetchall()
        conn.close()
        pnls = [row[0] for row in rows]
    except Exception as exc:
        print(f"ERROR loading {args.db}: {exc}", file=sys.stderr)
        sys.exit(1)

    if len(pnls) < 10:
        print(f"ERROR: Need at least 10 trades, found {len(pnls)}", file=sys.stderr)
        sys.exit(1)

    print(f"Running {args.runs:,} simulations on {len(pnls)} trades...")
    result = run_monte_carlo(pnls, args.capital, args.runs, args.ruin, args.seed)

    print(f"\n=== Monte Carlo Results ({result.n_runs:,} runs) ===")
    print(f"Starting capital:      \u20ac{args.capital:.2f}")
    print(f"Trades sampled:        {len(pnls)}")
    print(f"P95 max drawdown:      {result.p5_max_drawdown_pct:.1f}%  (95% of runs had less)")
    print(f"P99 max drawdown:      {result.p1_max_drawdown_pct:.1f}%  (99% of runs had less)")
    print(f"Avg max drawdown:      {result.avg_max_drawdown_pct:.1f}%")
    print(
        f"Ruin probability:      {result.ruin_probability_pct:.2f}%"
        f"  (drawdown > {result.ruin_threshold_pct:.0f}%)"
    )


if __name__ == "__main__":
    main()
