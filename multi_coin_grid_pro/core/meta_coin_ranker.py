"""
Meta Coin Ranker — ranks coins by recent performance from trade-label history.

Computes a composite score per coin based on:
  - Recent win rate        (weighted 40 %)
  - Average PnL (scaled)  (weighted 40 %)
  - Average quality score (weighted 20 %)

Meaningful only after >= ``min_trades`` trades per coin in the lookback window.

Part of the 17-upgrade trading bot roadmap:
  Item 14 — Meta Coin Ranker
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from multi_coin_grid_pro.persistence.trade_label_store import TradeLabel

log = logging.getLogger(__name__)


@dataclass
class CoinRank:
    """Composite performance rank for a single coin."""

    coin: str
    score: float            # higher = better
    recent_win_rate: float  # 0.0 – 1.0
    recent_avg_pnl: float   # average per-trade PnL in quote currency
    quality_avg: float      # average quality score (0-100)
    trade_count: int


class MetaCoinRanker:
    """
    Ranks coins by recent performance using trade-label history.

    Only coins with >= ``min_trades`` trades in the lookback window are ranked.

    Parameters
    ----------
    lookback_days : int
        How many calendar days of trade history to consider.
    min_trades : int
        Minimum number of trades required to include a coin in the ranking.
    """

    def __init__(self, lookback_days: int = 7, min_trades: int = 5):
        self.lookback_days = lookback_days
        self.min_trades = min_trades

    def rank(
        self,
        labels: "List[TradeLabel]",
        now: Optional[float] = None,
    ) -> List[CoinRank]:
        """
        Rank all coins by composite score (best first).

        Parameters
        ----------
        labels : list[TradeLabel]
            Historical trade labels.
        now : float, optional
            Reference timestamp for the lookback window.  Defaults to
            ``time.time()`` — pass an explicit value in tests for determinism.

        Returns
        -------
        list[CoinRank]
            Sorted descending by score; empty if no coin meets the minimum
            trade count.
        """
        cutoff = (now if now is not None else time.time()) - self.lookback_days * 86400
        recent = [lbl for lbl in labels if lbl.timestamp_close >= cutoff]

        coin_data: Dict[str, List] = defaultdict(list)
        for lbl in recent:
            coin_data[lbl.coin].append(lbl)

        ranks: List[CoinRank] = []
        for coin, coin_labels in coin_data.items():
            if len(coin_labels) < self.min_trades:
                continue

            pnls = [lbl.pnl_quote for lbl in coin_labels]
            wins = sum(1 for p in pnls if p > 0)
            win_rate = wins / len(pnls)
            avg_pnl = sum(pnls) / len(pnls)
            quality_avg = sum(lbl.quality_score for lbl in coin_labels) / len(coin_labels)

            # Composite score: win_rate*40 + pnl_scaled*40 + quality*20
            pnl_scaled = min(max(avg_pnl / 5.0, -1.0), 1.0)
            score = (win_rate * 40) + (pnl_scaled * 40) + (quality_avg / 100.0 * 20)

            ranks.append(
                CoinRank(
                    coin=coin,
                    score=score,
                    recent_win_rate=win_rate,
                    recent_avg_pnl=avg_pnl,
                    quality_avg=quality_avg,
                    trade_count=len(coin_labels),
                )
            )

        return sorted(ranks, key=lambda r: r.score, reverse=True)

    def get_preferred_coins(
        self,
        labels: "List[TradeLabel]",
        top_n: int = 5,
        now: Optional[float] = None,
    ) -> List[str]:
        """Return the top *top_n* coin symbols ranked by recent performance."""
        return [r.coin for r in self.rank(labels, now=now)[:top_n]]

    def get_score(
        self,
        coin: str,
        labels: "List[TradeLabel]",
        now: Optional[float] = None,
    ) -> Optional[float]:
        """Return the composite score for *coin*, or ``None`` if insufficient data."""
        ranks = {r.coin: r for r in self.rank(labels, now=now)}
        return ranks[coin].score if coin in ranks else None
