"""
Pure detect-only momentum candidate scoring.

This module has no exchange, order, persistence, or controller dependencies.
It converts existing trend/indicator inputs into a scored candidate and a
deterministic rejection reason list.
"""

import time
from dataclasses import dataclass
from typing import Optional

from multi_coin_grid_pro.core.reason_codes import ReasonCode

DEFAULT_SCORER_WEIGHTS = {
    "trend_1h": 0.25,
    "trend_4h": 0.30,
    "volume_expansion": 0.20,
    "relative_strength": 0.15,
    "spread": 0.05,
    "rsi_wick_risk": 0.05,
}


DEFAULT_MOMENTUM_CONFIG = {
    "mode": "detect_only",
    "min_score_to_enter": 55.0,
    "momentum_1h_min_pct": 0.5,
    "momentum_4h_min_pct": 1.0,
    "momentum_max_rsi": 80.0,
    "momentum_min_volume_expansion": 1.2,
    "momentum_regime_gate": ["BULL", "CHOP"],
    "momentum_max_spread_pct": 0.5,
    "momentum_max_wick_risk": 0.7,
    "rejected_log_throttle_seconds": 300,
    "scorer_weights": DEFAULT_SCORER_WEIGHTS,
}


REJECTION_PRIORITY = [
    ReasonCode.MOMENTUM_REGIME_BLOCKED.value,
    ReasonCode.MOMENTUM_DUPLICATE.value,
    ReasonCode.MOMENTUM_COOLDOWN.value,
    ReasonCode.MOMENTUM_POSITION_LIMIT.value,
    ReasonCode.MOMENTUM_RSI_TOO_HIGH.value,
    ReasonCode.MOMENTUM_VOLUME_TOO_LOW.value,
    ReasonCode.MOMENTUM_SPREAD_TOO_WIDE.value,
    ReasonCode.MOMENTUM_WICK_RISK_TOO_HIGH.value,
    ReasonCode.MOMENTUM_SCORE_TOO_LOW.value,
]


@dataclass
class MomentumCandidate:
    symbol: str
    score: float
    trend_1h: float
    trend_4h: float
    trend_24h: float
    volume_expansion: float
    relative_strength: float
    spread_pct: float
    rsi: float
    wick_risk: float
    entry_allowed: bool
    primary_rejection_reason: Optional[str]
    all_rejection_reasons: list[str]
    regime_at_score: str
    scored_at: float


class MomentumCandidateScorer:
    """Config-driven pure scorer for momentum sleeve candidates."""

    def __init__(self, config: Optional[dict] = None):
        raw_config = config or {}
        merged = {
            key: value for key, value in DEFAULT_MOMENTUM_CONFIG.items()
            if key != "scorer_weights"
        }
        merged.update(raw_config)
        merged["scorer_weights"] = {
            **DEFAULT_SCORER_WEIGHTS,
            **(raw_config.get("scorer_weights") or {}),
        }
        self.config = merged
        self.weights = self._validated_weights(merged["scorer_weights"])

    def score(
        self,
        symbol,
        trend_obj,
        btc_trend_obj,
        spread,
        rsi,
        wick_risk,
        regime,
    ) -> MomentumCandidate:
        """Score one candidate from existing in-memory market features."""
        trend_1h = self._trend_value(trend_obj, "trend_60m", "trend_1h", "trend_1h_pct")
        trend_4h = self._trend_value(trend_obj, "trend_240m", "trend_4h", "trend_4h_pct")
        trend_24h = self._trend_value(trend_obj, "trend_1440m", "trend_24h", "trend_24h_pct")
        btc_4h = (
            self._trend_value(btc_trend_obj, "trend_240m", "trend_4h", "trend_4h_pct")
            if btc_trend_obj is not None else 0.0
        )

        volume_expansion = self._volume_expansion(trend_obj)
        relative_strength = 0.0 if btc_trend_obj is None else trend_4h - btc_4h
        spread_pct = self._to_float(spread)
        rsi_value = self._to_float(rsi, default=50.0)
        wick_risk_value = self._clamp(self._to_float(wick_risk), 0.0, 1.0)
        regime_value = (regime or "CHOP").upper()

        score = self._calculate_score(
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            volume_expansion=volume_expansion,
            relative_strength=relative_strength,
            spread_pct=spread_pct,
            rsi=rsi_value,
            wick_risk=wick_risk_value,
        )

        reasons = self._rejection_reasons(
            score=score,
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            volume_expansion=volume_expansion,
            spread_pct=spread_pct,
            rsi=rsi_value,
            wick_risk=wick_risk_value,
            regime=regime_value,
        )
        entry_allowed = len(reasons) == 0
        primary = None if entry_allowed else self._primary_reason(reasons)

        return MomentumCandidate(
            symbol=symbol,
            score=round(score, 2),
            trend_1h=trend_1h,
            trend_4h=trend_4h,
            trend_24h=trend_24h,
            volume_expansion=volume_expansion,
            relative_strength=relative_strength,
            spread_pct=spread_pct,
            rsi=rsi_value,
            wick_risk=wick_risk_value,
            entry_allowed=entry_allowed,
            primary_rejection_reason=primary,
            all_rejection_reasons=[] if entry_allowed else reasons,
            regime_at_score=regime_value,
            scored_at=time.time(),
        )

    def _calculate_score(
        self,
        trend_1h,
        trend_4h,
        volume_expansion,
        relative_strength,
        spread_pct,
        rsi,
        wick_risk,
    ) -> float:
        max_spread = float(self.config["momentum_max_spread_pct"])
        max_rsi = float(self.config["momentum_max_rsi"])

        subscores = {
            "trend_1h": self._positive_score(trend_1h, full_score_at=4.0),
            "trend_4h": self._positive_score(trend_4h, full_score_at=10.0),
            "volume_expansion": self._volume_score(volume_expansion),
            "relative_strength": self._relative_strength_score(relative_strength),
            "spread": self._spread_score(spread_pct, max_spread),
            "rsi_wick_risk": self._rsi_wick_score(rsi, max_rsi, wick_risk),
        }

        weight_sum = sum(self.weights.values())
        if weight_sum <= 0:
            return 0.0

        weighted = sum(subscores[key] * self.weights[key] for key in DEFAULT_SCORER_WEIGHTS)
        return self._clamp(weighted / weight_sum, 0.0, 100.0)

    def _rejection_reasons(
        self,
        score,
        trend_1h,
        trend_4h,
        volume_expansion,
        spread_pct,
        rsi,
        wick_risk,
        regime,
    ) -> list[str]:
        reasons: list[str] = []
        regime_gate = {str(item).upper() for item in self.config["momentum_regime_gate"]}

        if regime not in regime_gate:
            self._add_reason(reasons, ReasonCode.MOMENTUM_REGIME_BLOCKED.value)
        if rsi > float(self.config["momentum_max_rsi"]):
            self._add_reason(reasons, ReasonCode.MOMENTUM_RSI_TOO_HIGH.value)
        if volume_expansion < float(self.config["momentum_min_volume_expansion"]):
            self._add_reason(reasons, ReasonCode.MOMENTUM_VOLUME_TOO_LOW.value)
        if spread_pct > float(self.config["momentum_max_spread_pct"]):
            self._add_reason(reasons, ReasonCode.MOMENTUM_SPREAD_TOO_WIDE.value)
        if wick_risk > float(self.config["momentum_max_wick_risk"]):
            self._add_reason(reasons, ReasonCode.MOMENTUM_WICK_RISK_TOO_HIGH.value)
        if (
            score < float(self.config["min_score_to_enter"])
            or trend_1h < float(self.config["momentum_1h_min_pct"])
            or trend_4h < float(self.config["momentum_4h_min_pct"])
        ):
            self._add_reason(reasons, ReasonCode.MOMENTUM_SCORE_TOO_LOW.value)

        return sorted(reasons, key=self._priority_index)

    @staticmethod
    def _add_reason(reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    @staticmethod
    def _primary_reason(reasons: list[str]) -> Optional[str]:
        return reasons[0] if reasons else None

    @staticmethod
    def _priority_index(reason: str) -> int:
        try:
            return REJECTION_PRIORITY.index(reason)
        except ValueError:
            return len(REJECTION_PRIORITY)

    @staticmethod
    def _validated_weights(raw_weights: dict) -> dict:
        weights = {}
        for key, default in DEFAULT_SCORER_WEIGHTS.items():
            value = raw_weights.get(key, default)
            try:
                weights[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                weights[key] = default
        return weights

    @staticmethod
    def _trend_value(obj, *names) -> float:
        if obj is None:
            return 0.0
        for name in names:
            if hasattr(obj, name):
                return MomentumCandidateScorer._to_float(getattr(obj, name))
        return 0.0

    @staticmethod
    def _volume_expansion(trend_obj) -> float:
        if trend_obj is None:
            return 1.0
        for name in ("volume_expansion", "volume_expansion_ratio", "volume_ratio"):
            if hasattr(trend_obj, name):
                value = MomentumCandidateScorer._to_float(getattr(trend_obj, name), default=1.0)
                return max(0.0, value)

        candles = getattr(trend_obj, "candles", None) or []
        if len(candles) < 21:
            return 1.0

        # Live ticker-created candles may have volume=0 because ticker data
        # does not carry candle volume. Treat those as unavailable, not as a
        # real volume collapse, and compare the latest non-zero candle against
        # the preceding non-zero baseline.
        volumes = [
            MomentumCandidateScorer._to_float(getattr(candle, "volume", 0.0))
            for candle in candles[-60:]
        ]
        non_zero_volumes = [volume for volume in volumes if volume > 0]
        if len(non_zero_volumes) < 2:
            return 1.0

        recent_non_zero = non_zero_volumes[-21:]
        latest = recent_non_zero[-1]
        baseline_values = recent_non_zero[:-1]
        baseline = sum(baseline_values) / max(1, len(baseline_values))
        if baseline <= 0:
            return 1.0
        return max(0.0, latest / baseline)

    @staticmethod
    def _positive_score(value: float, full_score_at: float) -> float:
        if full_score_at <= 0:
            return 0.0
        return MomentumCandidateScorer._clamp((value / full_score_at) * 100.0, 0.0, 100.0)

    @staticmethod
    def _volume_score(volume_expansion: float) -> float:
        return MomentumCandidateScorer._clamp(((volume_expansion - 1.0) / 2.0) * 100.0, 0.0, 100.0)

    @staticmethod
    def _relative_strength_score(relative_strength: float) -> float:
        return MomentumCandidateScorer._clamp(50.0 + (relative_strength / 10.0) * 50.0, 0.0, 100.0)

    @staticmethod
    def _spread_score(spread_pct: float, max_spread_pct: float) -> float:
        if max_spread_pct <= 0:
            return 0.0
        return MomentumCandidateScorer._clamp(
            ((max_spread_pct - spread_pct) / max_spread_pct) * 100.0,
            0.0,
            100.0,
        )

    @staticmethod
    def _rsi_wick_score(rsi: float, max_rsi: float, wick_risk: float) -> float:
        rsi_penalty_window = max(1.0, max_rsi - 60.0)
        rsi_penalty = max(0.0, rsi - 60.0) / rsi_penalty_window
        rsi_score = MomentumCandidateScorer._clamp(100.0 - rsi_penalty * 50.0, 0.0, 100.0)
        wick_score = MomentumCandidateScorer._clamp(100.0 - wick_risk * 100.0, 0.0, 100.0)
        return (rsi_score + wick_score) / 2.0

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
