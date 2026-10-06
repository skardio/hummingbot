"""Block bootstrap confidence intervals.

Trades are not independent: concurrent executors run on correlated pairs within
the same market regime. A classical t-test would therefore be overconfident.
Resampling whole calendar days keeps intra-day correlation intact, which is the
cheapest honest correction available from this data.

No power analysis is performed. Variance is non-stationary (the configuration
changed six times within 34 trades on Kraken USD), so any power figure would be
false precision. The engine relies on conservative fixed thresholds from the
policy instead.

Given the same inputs and seed the output is bit-identical.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of a block bootstrap on the per-trade mean."""

    method: str
    n_resamples: int
    confidence_level: float
    seed: int
    n_blocks: int
    n_observations: int
    point_estimate: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]

    @property
    def available(self) -> bool:
        return self.ci_low is not None and self.ci_high is not None

    @property
    def excludes_zero(self) -> Optional[bool]:
        if not self.available:
            return None
        return self.ci_low > 0.0 or self.ci_high < 0.0

    @property
    def lower_bound_above(self) -> Optional[float]:
        return self.ci_low


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile on an already sorted sequence."""
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def block_bootstrap_mean(
    daily_values: Mapping[str, Sequence[Decimal]],
    n_resamples: int,
    confidence_level: float,
    seed: int,
    method: str = "block_bootstrap_day",
) -> BootstrapResult:
    """Bootstrap the pooled per-observation mean, resampling whole days.

    ``daily_values`` maps a day key to that day's observations. Days are drawn
    with replacement; the statistic is the pooled mean across the drawn days.
    """
    blocks: List[Tuple[float, int]] = []
    n_observations = 0
    for day in sorted(daily_values):
        values = daily_values[day]
        if not values:
            continue
        blocks.append((float(sum(values)), len(values)))
        n_observations += len(values)

    n_blocks = len(blocks)
    if n_blocks == 0 or n_observations == 0:
        return BootstrapResult(
            method=method,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=seed,
            n_blocks=n_blocks,
            n_observations=n_observations,
            point_estimate=None,
            ci_low=None,
            ci_high=None,
        )

    total_sum = sum(block[0] for block in blocks)
    point_estimate = total_sum / n_observations

    rng = random.Random(seed)
    means: List[float] = []
    indices = range(n_blocks)
    for _ in range(n_resamples):
        drawn_sum = 0.0
        drawn_count = 0
        for _ in indices:
            block_sum, block_count = blocks[rng.randrange(n_blocks)]
            drawn_sum += block_sum
            drawn_count += block_count
        if drawn_count:
            means.append(drawn_sum / drawn_count)

    if not means:
        return BootstrapResult(
            method=method,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=seed,
            n_blocks=n_blocks,
            n_observations=n_observations,
            point_estimate=point_estimate,
            ci_low=None,
            ci_high=None,
        )

    means.sort()
    alpha = (1.0 - confidence_level) / 2.0
    return BootstrapResult(
        method=method,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        seed=seed,
        n_blocks=n_blocks,
        n_observations=n_observations,
        point_estimate=point_estimate,
        ci_low=_percentile(means, alpha),
        ci_high=_percentile(means, 1.0 - alpha),
    )


def block_bootstrap_difference(
    test_daily: Mapping[str, Sequence[Decimal]],
    baseline_daily: Mapping[str, Sequence[Decimal]],
    n_resamples: int,
    confidence_level: float,
    seed: int,
) -> BootstrapResult:
    """Bootstrap the difference in pooled means between test and baseline.

    Both cohorts are resampled independently with the same seed stream, which
    keeps the result reproducible without pairing days that are unrelated.
    """
    test = block_bootstrap_mean(test_daily, n_resamples, confidence_level, seed)
    base = block_bootstrap_mean(baseline_daily, n_resamples, confidence_level, seed + 1)
    if not test.available or not base.available or test.point_estimate is None or base.point_estimate is None:
        return BootstrapResult(
            method="block_bootstrap_day_difference",
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            seed=seed,
            n_blocks=min(test.n_blocks, base.n_blocks),
            n_observations=test.n_observations + base.n_observations,
            point_estimate=None,
            ci_low=None,
            ci_high=None,
        )

    rng_test = random.Random(seed)
    rng_base = random.Random(seed + 1)
    diffs: List[float] = []
    test_blocks = _blocks_of(test_daily)
    base_blocks = _blocks_of(baseline_daily)
    for _ in range(n_resamples):
        diffs.append(_pooled_mean(test_blocks, rng_test) - _pooled_mean(base_blocks, rng_base))

    diffs.sort()
    alpha = (1.0 - confidence_level) / 2.0
    return BootstrapResult(
        method="block_bootstrap_day_difference",
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        seed=seed,
        n_blocks=min(test.n_blocks, base.n_blocks),
        n_observations=test.n_observations + base.n_observations,
        point_estimate=test.point_estimate - base.point_estimate,
        ci_low=_percentile(diffs, alpha),
        ci_high=_percentile(diffs, 1.0 - alpha),
    )


def _blocks_of(daily_values: Mapping[str, Sequence[Decimal]]) -> List[Tuple[float, int]]:
    return [
        (float(sum(daily_values[day])), len(daily_values[day]))
        for day in sorted(daily_values)
        if daily_values[day]
    ]


def _pooled_mean(blocks: Sequence[Tuple[float, int]], rng: random.Random) -> float:
    drawn_sum = 0.0
    drawn_count = 0
    for _ in range(len(blocks)):
        block_sum, block_count = blocks[rng.randrange(len(blocks))]
        drawn_sum += block_sum
        drawn_count += block_count
    return drawn_sum / drawn_count if drawn_count else 0.0
