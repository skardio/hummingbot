"""
Trade Quality Scorer — 0-100 composite entry quality metric.

Scores each potential entry on 6 weighted components:
  - Regime       (0-25)
  - RSI          (0-20)
  - Spread       (0-20)
  - Depth        (0-15)
  - Volatility   (0-10)
  - BTC trend    (0-10)

Total max = 100.

Part of the 17-upgrade trading bot roadmap:
  Item 5 — Trade Quality Scorer
  Item 8 — Quality-Based Position Sizing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class QualityScore:
    """Breakdown of the 0-100 composite quality score."""

    total: int              # 0-100
    regime: int             # 0-25
    rsi: int                # 0-20
    spread: int             # 0-20
    depth: int              # 0-15
    volatility: int         # 0-10
    btc_trend: int          # 0-10
    details: Dict[str, str] = field(default_factory=dict)


class TradeQualityScorer:
    """
    Scores a potential trade entry on 6 weighted components.

    All inputs are required keyword arguments; see ``score()`` for docs.
    Suitable for use in filters, position sizing, and audit logging.
    """

    # ------------------------------------------------------------------ #
    # Component scorers (pure functions for easy testing)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _score_regime(regime: str) -> tuple[int, str]:
        if regime == "BULL":
            return 25, "BULL → 25"
        if regime == "NEUTRAL":
            return 15, "NEUTRAL → 15"
        # BEAR or anything else
        return 0, f"{regime} → 0"

    @staticmethod
    def _score_rsi(rsi: float) -> tuple[int, str]:
        if 30.0 <= rsi <= 50.0:
            return 20, f"RSI {rsi:.1f} in [30,50] → 20"
        if 50.0 < rsi <= 60.0:
            return 15, f"RSI {rsi:.1f} in (50,60] → 15"
        if 60.0 < rsi <= 70.0:
            return 5, f"RSI {rsi:.1f} in (60,70] → 5"
        return 0, f"RSI {rsi:.1f} outside range → 0"

    @staticmethod
    def _score_spread(spread_pct: float) -> tuple[int, str]:
        if spread_pct <= 0.1:
            return 20, f"spread {spread_pct:.3f}% ≤ 0.1% → 20"
        if spread_pct <= 0.2:
            return 15, f"spread {spread_pct:.3f}% ≤ 0.2% → 15"
        if spread_pct <= 0.3:
            return 10, f"spread {spread_pct:.3f}% ≤ 0.3% → 10"
        if spread_pct <= 0.5:
            return 5, f"spread {spread_pct:.3f}% ≤ 0.5% → 5"
        return 0, f"spread {spread_pct:.3f}% > 0.5% → 0"

    @staticmethod
    def _score_depth(depth_multiple: float) -> tuple[int, str]:
        if depth_multiple >= 10.0:
            return 15, f"depth {depth_multiple:.1f}x ≥ 10x → 15"
        if depth_multiple >= 5.0:
            return 10, f"depth {depth_multiple:.1f}x ≥ 5x → 10"
        if depth_multiple >= 3.0:
            return 5, f"depth {depth_multiple:.1f}x ≥ 3x → 5"
        return 0, f"depth {depth_multiple:.1f}x < 3x → 0"

    @staticmethod
    def _score_volatility(atr_pct: float) -> tuple[int, str]:
        if 1.0 <= atr_pct <= 3.0:
            return 10, f"ATR {atr_pct:.2f}% in [1,3] → 10"
        if 0.5 <= atr_pct < 1.0 or 3.0 < atr_pct <= 4.0:
            return 7, f"ATR {atr_pct:.2f}% in [0.5,1) or (3,4] → 7"
        return 0, f"ATR {atr_pct:.2f}% outside [0.5,4] → 0"

    @staticmethod
    def _score_btc_trend(btc_1h_pct: float) -> tuple[int, str]:
        if btc_1h_pct > 0.0:
            return 10, f"BTC 1h {btc_1h_pct:+.2f}% > 0% → 10"
        if btc_1h_pct > -1.0:
            return 5, f"BTC 1h {btc_1h_pct:+.2f}% in (-1,0] → 5"
        return 0, f"BTC 1h {btc_1h_pct:+.2f}% ≤ -1% → 0"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def score(
        self,
        *,
        regime: str,
        rsi: float,
        spread_pct: float,
        depth_multiple: float,
        atr_pct: float,
        btc_1h_pct: float,
    ) -> QualityScore:
        """
        Compute composite trade quality score.

        Parameters
        ----------
        regime : str
            Market regime label ("BULL", "NEUTRAL", "BEAR", …).
        rsi : float
            RSI(14), range 0-100.
        spread_pct : float
            Bid-ask spread as a percentage of mid price.
        depth_multiple : float
            Order-book depth expressed as a multiple of the planned order size
            (e.g. 5.0 means 5× the order size is available on each side).
        atr_pct : float
            ATR(14) as a percentage of current price.
        btc_1h_pct : float
            BTC 1-hour price change in percent.

        Returns
        -------
        QualityScore
            Dataclass with per-component scores and a human-readable details dict.
        """
        r_score, r_detail = self._score_regime(regime)
        rsi_score, rsi_detail = self._score_rsi(rsi)
        spread_score, spread_detail = self._score_spread(spread_pct)
        depth_score, depth_detail = self._score_depth(depth_multiple)
        vol_score, vol_detail = self._score_volatility(atr_pct)
        btc_score, btc_detail = self._score_btc_trend(btc_1h_pct)

        total = r_score + rsi_score + spread_score + depth_score + vol_score + btc_score

        return QualityScore(
            total=min(100, total),
            regime=r_score,
            rsi=rsi_score,
            spread=spread_score,
            depth=depth_score,
            volatility=vol_score,
            btc_trend=btc_score,
            details={
                "regime": r_detail,
                "rsi": rsi_detail,
                "spread": spread_detail,
                "depth": depth_detail,
                "volatility": vol_detail,
                "btc_trend": btc_detail,
            },
        )


# ------------------------------------------------------------------ #
# Item 8: Quality-Based Position Sizing helper
# ------------------------------------------------------------------ #

def quality_size_multiplier(score: int, halved: bool = False) -> float:
    """
    Convert a 0-100 quality score to a position-size multiplier.

    Thresholds
    ----------
    score >= 80 → 1.25x  (strong setup)
    score >= 60 → 1.00x  (normal)
    score >= 40 → 0.75x  (weak setup)
    score <  40 → 0.50x  (poor setup)

    If *halved* is True (coin hit -1R today), the result is halved further.

    Parameters
    ----------
    score : int
        Quality score in [0, 100].
    halved : bool
        Whether the daily -1R flag is active for this coin.

    Returns
    -------
    float
        Multiplier to apply to the base position size.
    """
    if score >= 80:
        mult = 1.25
    elif score >= 60:
        mult = 1.0
    elif score >= 40:
        mult = 0.75
    else:
        mult = 0.5
    return mult * (0.5 if halved else 1.0)
