"""Deterministic configuration fingerprinting.

The fingerprint hashes the *full* executor config minus a denylist supplied by
the policy. A new strategy parameter is therefore included automatically, so
cohorts split instead of silently merging - failure in the safe direction.

All functions in this module are pure.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .policy import Policy

NULL_TOKEN = "null"
TRUE_TOKEN = "true"
FALSE_TOKEN = "false"


@dataclass(frozen=True)
class Fingerprint:
    """Result of fingerprinting a single executor config."""

    short: str
    full: str
    fields: Tuple[Tuple[str, str], ...]

    @property
    def field_count(self) -> int:
        return len(self.fields)


@dataclass(frozen=True)
class FingerprintDistribution:
    """Distribution of fingerprints across a cohort."""

    counts: Mapping[str, int]
    total: int
    dominant: str
    dominant_count: int

    @property
    def dominant_share(self) -> float:
        return self.dominant_count / self.total if self.total else 0.0

    @property
    def distinct(self) -> int:
        return len(self.counts)

    @property
    def health(self) -> float:
        """distinct fingerprints / n executors; high values suggest a stale denylist."""
        return self.distinct / self.total if self.total else 0.0


def flatten(obj: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten a nested mapping into dotted keys. Lists collapse to ``<list:n>``."""
    out: Dict[str, Any] = {}
    for key, value in obj.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            out.update(flatten(value, dotted))
        elif isinstance(value, (list, tuple)):
            out[dotted] = f"<list:{len(value)}>"
        else:
            out[dotted] = value
    return out


def canonical_value(value: Any, significant_digits: int) -> str:
    """Canonicalise a single value to a stable string.

    Numeric values - including numeric strings - are parsed as Decimal and
    quantised to ``significant_digits``, which removes float artefacts such as
    ``0.07500000000000001`` versus ``0.075``.
    """
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return TRUE_TOKEN if value else FALSE_TOKEN
    if isinstance(value, (int, float, Decimal, str)):
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not parsed.is_finite():
            return str(value)
        if parsed == 0:
            return "0"
        exponent = parsed.adjusted() - (significant_digits - 1)
        quantised = parsed.quantize(Decimal(1).scaleb(exponent)).normalize()
        return format(quantised, "f")
    return str(value)


def is_denied(key: str, patterns: Iterable[str]) -> bool:
    """Return True when a flattened key matches a denylist pattern.

    A pattern ending in ``*`` is a prefix match; anything else is exact.
    """
    for pattern in patterns:
        if pattern.endswith("*"):
            if key.startswith(pattern[:-1]):
                return True
        elif key == pattern:
            return True
    return False


def fingerprint_fields(config: Mapping[str, Any], policy: Policy) -> Tuple[Tuple[str, str], ...]:
    """Return the sorted (key, canonical_value) pairs that enter the hash."""
    patterns = policy.denylist_patterns()
    digits = int(policy.get("fingerprint.numeric_significant_digits"))
    flat = flatten(config)
    return tuple(
        (key, canonical_value(flat[key], digits))
        for key in sorted(flat)
        if not is_denied(key, patterns)
    )


def fingerprint_config(config: Mapping[str, Any], policy: Policy) -> Fingerprint:
    """Compute the deterministic fingerprint of one executor config."""
    algorithm = str(policy.get("fingerprint.hash_algorithm"))
    short_len = int(policy.get("fingerprint.short_hash_length"))
    fields = fingerprint_fields(config, policy)
    payload = json.dumps([list(pair) for pair in fields], sort_keys=True, separators=(",", ":"))
    digest = hashlib.new(algorithm, payload.encode("utf-8")).hexdigest()
    return Fingerprint(short=digest[:short_len], full=digest, fields=fields)


def fingerprint_distribution(fingerprints: Sequence[str]) -> FingerprintDistribution:
    """Summarise a sequence of fingerprint strings."""
    counts = Counter(fingerprints)
    total = len(fingerprints)
    if not counts:
        return FingerprintDistribution(counts={}, total=0, dominant="", dominant_count=0)
    dominant, dominant_count = max(sorted(counts.items()), key=lambda item: item[1])
    return FingerprintDistribution(
        counts=dict(counts),
        total=total,
        dominant=dominant,
        dominant_count=dominant_count,
    )


def diff_fingerprints(a: Fingerprint, b: Fingerprint) -> List[Tuple[str, str, str]]:
    """Return (key, value_a, value_b) for every field that differs."""
    map_a = dict(a.fields)
    map_b = dict(b.fields)
    keys = sorted(set(map_a) | set(map_b))
    return [
        (key, map_a.get(key, "<absent>"), map_b.get(key, "<absent>"))
        for key in keys
        if map_a.get(key) != map_b.get(key)
    ]


@dataclass(frozen=True)
class FieldVolatility:
    """How much one fingerprinted field varies across a cohort."""

    key: str
    distinct: int
    total: int
    examples: Tuple[str, ...]

    @property
    def volatility(self) -> float:
        return self.distinct / self.total if self.total else 0.0


def field_volatility(
    configs: Sequence[Mapping[str, Any]],
    policy: Policy,
    top_n: int = 10,
) -> List[FieldVolatility]:
    """Rank fingerprinted fields by how many distinct values they take.

    Needed because the aggregate ``fingerprint_health`` ratio does not catch a
    *semi*-volatile field. On Bitget ``triple_barrier_config.stop_loss`` takes 13
    distinct ATR-derived values over 348 executors: enough to shatter cohorts,
    not enough to push health past the stale threshold.

    The engine only diagnoses. Whether a field is a parameter or a per-trade
    observation is an operator decision, because the same key can be either -
    ``stop_loss`` is a fixed parameter on Kraken and market-derived on Bitget.
    """
    seen: Dict[str, set] = {}
    total = 0
    for config in configs:
        total += 1
        for key, value in fingerprint_fields(config, policy):
            seen.setdefault(key, set()).add(value)

    ranked = [
        FieldVolatility(key=key, distinct=len(values), total=total, examples=tuple(sorted(values)[:3]))
        for key, values in seen.items()
        if len(values) > 1
    ]
    ranked.sort(key=lambda item: (-item.distinct, item.key))
    return ranked[:top_n]
