from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class BearPolicyDecision:
    policy: str
    block_new_entries: bool
    in_bear_light: bool
    score: Optional[float]
    threshold: float
    size_multiplier: float
    reason: str

    def metadata(self) -> Dict[str, Any]:
        return {
            "bear_policy": self.policy,
            "bear_light": self.in_bear_light,
            "regime_score": self.score,
            "bear_light_threshold": self.threshold,
            "bear_size_multiplier": self.size_multiplier,
        }


def _normalize_policy(raw_policy: Optional[Any], legacy_allow_meanrev: bool, auto_light_enabled: bool) -> str:
    if raw_policy is not None:
        normalized = str(raw_policy).strip().lower()
        if normalized in {"conditional", "bear_light", "bear-light", "auto"}:
            return "conditional"
        if normalized in {"allow", "true", "on", "always"}:
            return "allow"
        if normalized in {"block", "false", "off", "never"}:
            return "block"

    if legacy_allow_meanrev:
        return "allow"
    if auto_light_enabled:
        return "conditional"
    return "block"


def decide_bear_policy(
    regime: Optional[str],
    score: Optional[float],
    regime_cfg: Optional[Dict[str, Any]],
    adaptive_filters_cfg: Optional[Dict[str, Any]],
) -> BearPolicyDecision:
    """Return the definitive BEAR entry policy decision.

    Policy meanings:
    - block: no new entries in BEAR
    - allow: legacy always-allow mean-reversion
    - conditional: only shallow BEAR via BEAR-light may enter
    """
    cfg = regime_cfg or {}
    bear_cfg = (adaptive_filters_cfg or {}).get("BEAR", {})
    auto_light_enabled = bool(cfg.get("bear_auto_light_enabled", False))
    threshold = float(cfg.get("bear_auto_light_threshold", -5.0))
    size_multiplier = float(cfg.get("bear_size_multiplier", 0.5))
    legacy_allow = bool(bear_cfg.get("bear_allow_meanrev", False))
    raw_policy = cfg.get("bear_meanrev_policy", bear_cfg.get("bear_meanrev_policy"))
    policy = _normalize_policy(raw_policy, legacy_allow, auto_light_enabled)

    if regime != "BEAR":
        return BearPolicyDecision(
            policy=policy,
            block_new_entries=False,
            in_bear_light=False,
            score=score,
            threshold=threshold,
            size_multiplier=1.0,
            reason="non-BEAR regime",
        )

    in_bear_light = bool(auto_light_enabled and score is not None and score > threshold)

    if policy == "allow":
        return BearPolicyDecision(
            policy=policy,
            block_new_entries=False,
            in_bear_light=False,
            score=score,
            threshold=threshold,
            size_multiplier=1.0,
            reason="BEAR mean-reversion explicitly allowed",
        )

    if policy == "conditional":
        if in_bear_light:
            return BearPolicyDecision(
                policy=policy,
                block_new_entries=False,
                in_bear_light=True,
                score=score,
                threshold=threshold,
                size_multiplier=size_multiplier,
                reason="shallow BEAR allowed via BEAR-light",
            )
        return BearPolicyDecision(
            policy=policy,
            block_new_entries=True,
            in_bear_light=False,
            score=score,
            threshold=threshold,
            size_multiplier=1.0,
            reason="deep BEAR blocks new entries",
        )

    return BearPolicyDecision(
        policy="block",
        block_new_entries=True,
        in_bear_light=False,
        score=score,
        threshold=threshold,
        size_multiplier=1.0,
        reason="BEAR entries disabled",
    )


def bear_light_divergence_passes(
    in_bear_light: bool,
    coin_trend_24h: Optional[float],
    btc_trend_24h: Optional[float],
) -> bool:
    """In BEAR-light, require the coin to hold up better than BTC."""
    if not in_bear_light:
        return True
    if coin_trend_24h is None or btc_trend_24h is None:
        return True
    return coin_trend_24h > btc_trend_24h
