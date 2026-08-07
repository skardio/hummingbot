# momentum_signal_scorer.py — wrapper around MomentumCandidateScorer
# Normalizes the legacy 0–100 score to 0.0–1.0 for the signal service.
# min_score in config (0.0–1.0)  ↔  min_score_to_enter * 100 in legacy scorer.
from typing import Optional

from multi_coin_grid_pro.logic.momentum_candidate_scorer import MomentumCandidateScorer


class SignalScorer:
    """Normalized (0.0–1.0) scorer for the read-only momentum signal service.

    Wraps ``MomentumCandidateScorer`` and divides its raw 0–100 output by
    100.0.  The service therefore uses 0.70 where the legacy scorer uses 70.

    ``score_raw`` is the low-level entry point used by both the service
    pipeline and the safety-guard test suite.
    """

    def __init__(self, min_score: float = 0.70) -> None:
        """
        Args:
            min_score: acceptance threshold in 0.0–1.0 scale.
                       Converted to ``min_score_to_enter * 100`` internally.
        """
        self.min_score = min_score
        self._scorer = MomentumCandidateScorer(config={
            "min_score_to_enter": min_score * 100.0,
            "mode": "detect_only",
        })

    def score_raw(
        self,
        trend_1h: float,
        trend_4h: float,
        volume_expansion: float,
        relative_strength: float,
        spread_pct: float,
        rsi: float,
        wick_risk: float,
        regime: str = "CHOP",  # accepted for API symmetry; not used in score
    ) -> float:
        """Return a score in *0.0–1.0* for the given market features.

        ``regime`` is accepted so callers can pass it for future use, but the
        underlying ``_calculate_score`` does not include regime in the numeric
        score (only in rejection-reason logic).
        """
        raw = self._scorer._calculate_score(
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            volume_expansion=volume_expansion,
            relative_strength=relative_strength,
            spread_pct=spread_pct,
            rsi=rsi,
            wick_risk=wick_risk,
        )
        return max(0.0, min(1.0, raw / 100.0))

    def score_candidate(self, candidate, regime: str = "CHOP") -> float:
        """Score an ``EnrichedCandidate`` and return a 0.0–1.0 float.

        The REST-only service does not fetch 1h/4h candles, so trend_1h_pct,
        trend_4h_pct, rsi, and wick_risk are always None. volume_expansion is
        also None; fall back to volume_ratio (candle-based short-term volume
        ratio) so the volume dimension is not permanently blind.
        """
        vol = (
            candidate.volume_expansion
            if candidate.volume_expansion is not None
            else candidate.volume_ratio  # candle volume_now / avg_20; populated for enriched pairs
        )
        return self.score_raw(
            trend_1h=candidate.trend_1h_pct or 0.0,
            trend_4h=candidate.trend_4h_pct or 0.0,
            volume_expansion=vol if vol is not None else 1.0,
            relative_strength=0.0,    # no BTC benchmark in REST-only service
            spread_pct=candidate.spread_pct,
            rsi=candidate.rsi if candidate.rsi is not None else 50.0,
            wick_risk=candidate.wick_risk or 0.0,
            regime=regime,
        )

    def accepts(self, score: float) -> bool:
        """Return True if *score* meets the configured threshold."""
        return score >= self.min_score

    def score_breakdown(
        self,
        trend_1h: float,
        trend_4h: float,
        volume_expansion: float,
        relative_strength: float,
        spread_pct: float,
        rsi: float,
        wick_risk: float,
    ) -> Optional[dict]:
        """Return per-component sub-scores for reporting (all in 0.0–1.0)."""
        s = self._scorer
        max_spread = float(s.config["momentum_max_spread_pct"])
        max_rsi = float(s.config["momentum_max_rsi"])
        raw = {
            "trend_1h": s._positive_score(trend_1h, full_score_at=4.0),
            "trend_4h": s._positive_score(trend_4h, full_score_at=10.0),
            "volume_expansion": s._volume_score(volume_expansion),
            "relative_strength": s._relative_strength_score(relative_strength),
            "spread": s._spread_score(spread_pct, max_spread),
            "rsi_wick_risk": s._rsi_wick_score(rsi, max_rsi, wick_risk),
        }
        return {k: round(v / 100.0, 4) for k, v in raw.items()}
