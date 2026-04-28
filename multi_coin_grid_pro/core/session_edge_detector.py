"""
Session Edge Detector — per-session win rate & PnL analysis.

Reads historical ``TradeLabel`` records and computes per-session (Asia/EU/US/weekend)
statistics to identify which sessions have a positive edge for each coin.

Part of the 17-upgrade trading bot roadmap:
  Item 13 — Session Edge Detector
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from multi_coin_grid_pro.persistence.trade_label_store import TradeLabel

log = logging.getLogger(__name__)

SESSIONS = ("Asia", "EU", "US", "weekend")


@dataclass
class SessionStats:
    """Aggregated statistics for a single trading session."""

    session: str
    trade_count: int
    win_rate: float     # 0.0 – 1.0
    avg_pnl: float      # average per-trade PnL in quote currency
    total_pnl: float    # sum of all PnL in quote currency

    @property
    def has_edge(self) -> bool:
        """True if the session shows a meaningful positive edge."""
        return (
            self.trade_count >= 5
            and self.win_rate >= 0.55
            and self.avg_pnl > 0
        )


class SessionEdgeDetector:
    """
    Compute per-session statistics from historical trade labels.

    Requires at least ``min_trades`` trades per session to draw conclusions.
    """

    def __init__(self, min_trades: int = 5):
        self.min_trades = min_trades

    def compute(
        self,
        labels: "List[TradeLabel]",
        coin: Optional[str] = None,
    ) -> Dict[str, SessionStats]:
        """
        Compute session statistics from trade labels.

        Parameters
        ----------
        labels : list[TradeLabel]
            Full trade history to analyse.
        coin : str, optional
            Filter to a single coin.  ``None`` = all coins.

        Returns
        -------
        Dict[str, SessionStats]
            Keyed by session name; only sessions with at least one trade are
            included.
        """
        filtered = [
            lbl for lbl in labels
            if coin is None or lbl.coin == coin
        ]

        buckets: Dict[str, List[float]] = {s: [] for s in SESSIONS}
        for lbl in filtered:
            if lbl.session in buckets:
                buckets[lbl.session].append(lbl.pnl_quote)

        result: Dict[str, SessionStats] = {}
        for session, pnls in buckets.items():
            if not pnls:
                continue
            wins = sum(1 for p in pnls if p > 0)
            result[session] = SessionStats(
                session=session,
                trade_count=len(pnls),
                win_rate=wins / len(pnls),
                avg_pnl=sum(pnls) / len(pnls),
                total_pnl=sum(pnls),
            )
        return result

    def best_session(
        self,
        labels: "List[TradeLabel]",
        coin: Optional[str] = None,
    ) -> Optional[str]:
        """
        Return the session with the best edge, or ``None`` if insufficient data.

        A session qualifies if it has >= ``min_trades`` trades and positive avg PnL.
        The winner is selected by highest avg PnL.
        """
        stats = self.compute(labels, coin)
        candidates = [
            s for s in stats.values()
            if s.trade_count >= self.min_trades and s.avg_pnl > 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.avg_pnl).session

    def should_avoid_session(
        self,
        session: str,
        labels: "List[TradeLabel]",
        coin: Optional[str] = None,
    ) -> bool:
        """
        Return ``True`` if *session* has a consistently negative edge.

        Threshold: >= ``min_trades`` trades, win_rate < 0.40, avg_pnl < 0.
        """
        stats = self.compute(labels, coin)
        if session not in stats:
            return False
        s = stats[session]
        return (
            s.trade_count >= self.min_trades
            and s.win_rate < 0.40
            and s.avg_pnl < 0
        )
