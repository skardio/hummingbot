# momentum_buy_now_scorer.py — Buy Now Engine scorer (US-202).
# Pure function scorer based only on data available from the REST service.
# Replaces the legacy MomentumCandidateScorer for signal classification.
# The old SignalScorer wrapper is kept intact for backward compatibility.
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BuyNowScoreBreakdown:
    """Per-component scores (0.0 – 1.0) for a BuyNow scoring run."""
    short_momentum: float = 0.0   # weight 0.30 — Δ3m + Δ5m combined
    acceleration: float = 0.0    # weight 0.25 — 0/0.4/0.7/1.0 from acceleration_score
    volume_spike: float = 0.0    # weight 0.20 — volume_ratio normalized
    liquidity: float = 0.0       # weight 0.15 — spread + slippage
    risk: float = 0.0            # weight 0.10 — lateness + spike penalty
    total: float = 0.0
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Component weights (must sum to 1.0)
# ---------------------------------------------------------------------------
_W_SHORT_MOMENTUM = 0.30
_W_ACCELERATION = 0.25
_W_VOLUME_SPIKE = 0.20
_W_LIQUIDITY = 0.15
_W_RISK = 0.10


def _short_momentum_score(
    price_change_3m_pct: Optional[float],
    price_change_5m_pct: Optional[float],
) -> float:
    """Score based on 3m and 5m price changes (0.0 – 1.0).

    Thresholds designed for the "buy now" use case: moves that are strong
    enough to act on but not yet exhausted.

    Both deltas contribute equally.  Full score at Δ3m≥1.5% and Δ5m≥2.5%.
    Returns 0.0 if either delta is None.
    """
    if price_change_3m_pct is None or price_change_5m_pct is None:
        return 0.0
    # Clamp to 0.0 — negative moves score 0
    p3 = max(0.0, price_change_3m_pct)
    p5 = max(0.0, price_change_5m_pct)
    # Linear scale: full score (1.0) at 1.5% for 3m and 2.5% for 5m
    s3 = min(1.0, p3 / 1.5)
    s5 = min(1.0, p5 / 2.5)
    return (s3 + s5) / 2.0


def _acceleration_component(acceleration_score: Optional[float]) -> float:
    """Normalize acceleration_score (0/0.4/0.7/1.0) to 0.0–1.0.

    The acceleration_score from US-102 is already 0.0–1.0; use it directly.
    Returns 0.0 if None.
    """
    if acceleration_score is None:
        return 0.0
    return max(0.0, min(1.0, acceleration_score))


def _volume_spike_score(volume_ratio: Optional[float]) -> float:
    """Score based on volume_ratio (0.0 – 1.0).

    Full score at VolR ≥ 5×.  Linear between 1× and 5×.
    Returns 0.0 if None or ≤ 1.0 (no volume expansion).
    """
    if volume_ratio is None:
        return 0.0
    # Below 1× (or exactly 1×): no expansion
    if volume_ratio <= 1.0:
        return 0.0
    return min(1.0, (volume_ratio - 1.0) / 4.0)


def _liquidity_score(
    spread_pct: float,
    slippage_100eur: Optional[float],
) -> float:
    """Score based on spread and slippage (0.0 – 1.0).

    Lower spread and lower slippage → higher score.
    Spread: full score at 0%, zero at 0.35%.
    Slippage (100 EUR order): full score at 0%, zero at 0.50%.
    Weighted 60/40.  Uses only spread if slippage is unavailable.
    """
    spread_score = max(0.0, 1.0 - spread_pct / 0.35)
    if slippage_100eur is None:
        return spread_score
    slip_score = max(0.0, 1.0 - slippage_100eur / 0.50)
    return 0.6 * spread_score + 0.4 * slip_score


def _risk_score(
    price_change_5m_pct: Optional[float],
    price_change_15m_pct: Optional[float],
) -> float:
    """Penalize late/exhausted moves (0.0 – 1.0, higher = lower risk).

    Starts at 1.0 and decays as 5m and 15m moves grow.
    Zero at Δ5m ≥ 4.5% (spike) or Δ15m ≥ 9% (extended move).
    """
    score = 1.0
    if price_change_5m_pct is not None:
        p5 = max(0.0, price_change_5m_pct)
        score *= max(0.0, 1.0 - p5 / 4.5)
    if price_change_15m_pct is not None:
        p15 = max(0.0, price_change_15m_pct)
        score *= max(0.0, 1.0 - p15 / 9.0)
    return score


class BuyNowScorer:
    """Score a momentum candidate for the Buy Now Engine (US-202).

    All inputs come from the REST-only momentum pipeline; no 1h/4h candles
    or RSI are required.  The score is always computable from available data.

    Usage::

        scorer = BuyNowScorer()
        score = scorer.score_candidate(candidate)
        breakdown = scorer.score_breakdown(candidate)
    """

    def score_candidate(self, candidate) -> float:
        """Return a 0.0–1.0 score for *candidate*."""
        return self._compute(
            price_change_3m_pct=candidate.price_change_3m_pct,
            price_change_5m_pct=candidate.price_change_5m_pct,
            price_change_15m_pct=candidate.price_change_15m_pct,
            acceleration_score=candidate.acceleration_score,
            volume_ratio=candidate.volume_ratio,
            spread_pct=candidate.spread_pct,
            slippage_100eur=candidate.slippage_100eur,
        )

    def score_breakdown(self, candidate) -> BuyNowScoreBreakdown:
        """Return a full per-component breakdown for *candidate*."""
        p3 = candidate.price_change_3m_pct
        p5 = candidate.price_change_5m_pct
        p15 = candidate.price_change_15m_pct
        accel = candidate.acceleration_score
        volr = candidate.volume_ratio
        spread = candidate.spread_pct
        slip = candidate.slippage_100eur

        sm = _short_momentum_score(p3, p5)
        ac = _acceleration_component(accel)
        vs = _volume_spike_score(volr)
        lq = _liquidity_score(spread, slip)
        rk = _risk_score(p5, p15)

        total = (
            _W_SHORT_MOMENTUM * sm
            + _W_ACCELERATION * ac
            + _W_VOLUME_SPIKE * vs
            + _W_LIQUIDITY * lq
            + _W_RISK * rk
        )
        return BuyNowScoreBreakdown(
            short_momentum=round(sm, 4),
            acceleration=round(ac, 4),
            volume_spike=round(vs, 4),
            liquidity=round(lq, 4),
            risk=round(rk, 4),
            total=round(total, 4),
            details={
                "price_change_3m_pct": p3,
                "price_change_5m_pct": p5,
                "price_change_15m_pct": p15,
                "acceleration_score": accel,
                "volume_ratio": volr,
                "spread_pct": spread,
                "slippage_100eur": slip,
            },
        )

    def _compute(
        self,
        price_change_3m_pct: Optional[float],
        price_change_5m_pct: Optional[float],
        price_change_15m_pct: Optional[float],
        acceleration_score: Optional[float],
        volume_ratio: Optional[float],
        spread_pct: float,
        slippage_100eur: Optional[float],
    ) -> float:
        sm = _short_momentum_score(price_change_3m_pct, price_change_5m_pct)
        ac = _acceleration_component(acceleration_score)
        vs = _volume_spike_score(volume_ratio)
        lq = _liquidity_score(spread_pct, slippage_100eur)
        rk = _risk_score(price_change_5m_pct, price_change_15m_pct)
        return (
            _W_SHORT_MOMENTUM * sm
            + _W_ACCELERATION * ac
            + _W_VOLUME_SPIKE * vs
            + _W_LIQUIDITY * lq
            + _W_RISK * rk
        )
