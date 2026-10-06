"""Loading and validation of the executable evidence policy.

The policy file is the single source of truth for every threshold used by the
Evidence Engine. This module performs no evidence logic of its own: it loads,
validates and exposes values. No threshold is defined here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import yaml

DEFAULT_POLICY_PATH = Path("config/evidence_policy.yaml")

# Structural contract only: which sections and keys must exist for the engine to
# run at all. The *values* live exclusively in the policy file.
REQUIRED_KEYS: Dict[str, Sequence[str]] = {
    "classification": (
        "dust_abs_quote",
        "dust_rel_pct",
        "dust_sensitivity_sweep",
        "require_verdict_stability",
        "max_heuristic_share_of_B",
        "zero_residual_epsilon_base",
        "dust_signature_epsilon_quote",
    ),
    "data_integrity": (
        "reconciliation_residual_rel",
        "reconciliation_residual_abs",
        "abc_identity_tolerance_abs",
        "allow_negative_fees",
        "fee_rate_plausible_range",
        "min_tradefill_attribution_for_exec_quality",
    ),
    "cohort": (
        "min_dominant_fingerprint_share",
        "require_same_venue",
        "require_same_quote",
        "require_same_controller_id",
        "forbid_period_overlap",
        "fingerprint_health_warn",
        "fingerprint_health_stale",
    ),
    "sample": (
        "min_matched_trades",
        "min_trading_days",
        "min_distinct_pairs",
        "max_pair_pnl_share",
        "max_single_trade_pnl_share",
    ),
    "operational": (
        "max_operational_share_of_total",
        "max_unmatched_buy_rate",
    ),
    "statistics": (
        "method",
        "n_resamples",
        "confidence_level",
        "random_seed",
        "require_ci_excludes_zero",
    ),
    "decision": (
        "primary_metric_allowlist",
        "forbidden_primary_metrics",
        "max_drawdown_ratio_vs_baseline",
        "require_positive_expectancy_after_fees",
        "require_operational_rate_not_worse",
    ),
    "regime": (
        "min_n_per_regime",
        "min_entry_regime_coverage",
    ),
    "fingerprint": (
        "hash_algorithm",
        "short_hash_length",
        "numeric_significant_digits",
        "denylist",
    ),
    "reporting": (
        "report_dir",
        "schema_version",
    ),
}


class PolicyError(ValueError):
    """Raised when the policy file is missing, malformed or incomplete."""


@dataclass(frozen=True)
class Policy:
    """Immutable view on the evidence policy."""

    version: str
    effective_from: str
    raw: Mapping[str, Any]
    source_path: str

    def section(self, name: str) -> Mapping[str, Any]:
        try:
            return self.raw[name]
        except KeyError as exc:  # pragma: no cover - guarded by validation
            raise PolicyError(f"missing policy section: {name}") from exc

    def get(self, dotted: str) -> Any:
        """Fetch a value by dotted path, e.g. ``sample.min_matched_trades``."""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                raise PolicyError(f"missing policy key: {dotted}")
            node = node[part]
        return node

    def decimal(self, dotted: str) -> Decimal:
        """Fetch a value as Decimal, going through str to avoid float artefacts."""
        return Decimal(str(self.get(dotted)))

    def denylist_patterns(self) -> List[str]:
        """Flatten the categorised fingerprint denylist into a pattern list."""
        denylist = self.get("fingerprint.denylist")
        if not isinstance(denylist, Mapping):
            raise PolicyError("fingerprint.denylist must be a mapping of categories")
        patterns: List[str] = []
        for category, entries in denylist.items():
            if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
                raise PolicyError(f"fingerprint.denylist.{category} must be a list")
            patterns.extend(str(entry) for entry in entries)
        return patterns


def validate_policy(raw: Mapping[str, Any]) -> None:
    """Validate the structural contract. Raises :class:`PolicyError`."""
    if not isinstance(raw, Mapping):
        raise PolicyError("policy root must be a mapping")
    for key in ("policy_version", "effective_from"):
        if key not in raw:
            raise PolicyError(f"missing policy key: {key}")

    for section, keys in REQUIRED_KEYS.items():
        if section not in raw:
            raise PolicyError(f"missing policy section: {section}")
        node = raw[section]
        if not isinstance(node, Mapping):
            raise PolicyError(f"policy section must be a mapping: {section}")
        for key in keys:
            if key not in node:
                raise PolicyError(f"missing policy key: {section}.{key}")

    forbidden = set(raw["decision"]["forbidden_primary_metrics"])
    allowed = set(raw["decision"]["primary_metric_allowlist"])
    overlap = forbidden & allowed
    if overlap:
        raise PolicyError(f"metric both allowed and forbidden as primary: {sorted(overlap)}")
    if "win_rate" not in forbidden:
        raise PolicyError("win_rate must stay in decision.forbidden_primary_metrics")

    sweep = raw["classification"]["dust_sensitivity_sweep"]
    for axis in ("abs_quote", "rel_pct"):
        values = sweep.get(axis)
        if not values:
            raise PolicyError(f"classification.dust_sensitivity_sweep.{axis} must be a non-empty list")


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> Policy:
    """Load and validate the policy file."""
    policy_path = Path(path)
    if not policy_path.is_file():
        raise PolicyError(f"policy file not found: {policy_path}")
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    validate_policy(raw)
    return Policy(
        version=str(raw["policy_version"]),
        effective_from=str(raw["effective_from"]),
        raw=raw,
        source_path=str(policy_path),
    )
