from __future__ import annotations

import logging
import random
from collections.abc import Sequence
from typing import Literal

import pandas as pd

from .analyzer import EuroAnalyzer
from .models import Combination, ComboKey

LOGGER = logging.getLogger(__name__)
Strategy = Literal["hot", "cold"]


DISCLAIMER = (
    "Let op: deze combinaties zijn gebaseerd op historische analyse, maar "
    "Euro blijft volledig willekeurig. Er is geen garantie op winst."
)


class CombinationGenerator:
    def __init__(self, analyzer: EuroAnalyzer, seed: int | None = None) -> None:
        self.analyzer = analyzer
        self.random = random.Random(seed)

    def generate(
        self,
        count: int = 10,
        strategy: Strategy = "cold",
        exclude_keys: set[ComboKey] | None = None,
        max_attempts: int = 25_000,
    ) -> list[Combination]:
        main_counts, euro_counts = self.analyzer.number_frequencies()
        existing = self.analyzer.database.existing_combinations()

        main_numbers = list(range(1, 51))
        euro_numbers = list(range(1, 13))
        main_weights = self._weights(main_counts, main_numbers, strategy)
        euro_weights = self._weights(euro_counts, euro_numbers, strategy)

        generated: list[Combination] = []
        generated_keys: set[ComboKey] = set(exclude_keys or set())
        attempts = 0

        while len(generated) < count and attempts < max_attempts:
            attempts += 1
            main = tuple(sorted(self._weighted_sample(main_numbers, main_weights, 5)))
            euro = tuple(sorted(self._weighted_sample(euro_numbers, euro_weights, 2)))
            combo = Combination(
                main_numbers=main,  # type: ignore[arg-type]
                euro_numbers=euro,  # type: ignore[arg-type]
            )
            if combo.combo_key in existing or combo.combo_key in generated_keys:
                continue
            if not self._valid_combo(combo):
                continue
            generated.append(combo)
            generated_keys.add(combo.combo_key)

        if len(generated) < count:
            raise RuntimeError(
                f"Only generated {len(generated)} valid combinations after {attempts} attempts"
            )

        LOGGER.info(
            "Generated %s %s-bias combinations after %s attempts",
            len(generated),
            strategy,
            attempts,
        )
        return generated

    @staticmethod
    def _weights(counts: pd.Series, values: Sequence[int], strategy: Strategy) -> list[float]:
        if counts.empty or counts.sum() == 0:
            return [1.0 for _ in values]

        mean_count = float(counts.mean())
        smoothing = max(mean_count * 0.35, 1.0)
        weights: list[float] = []
        for value in values:
            count = float(counts.get(value, 0))
            if strategy == "hot":
                raw_weight = (count + smoothing) / (mean_count + smoothing)
                weights.append(min(1.35, max(0.75, raw_weight)))
            else:
                raw_weight = (mean_count + smoothing) / (count + smoothing)
                weights.append(min(1.45, max(0.65, raw_weight)))
        return weights

    def _weighted_sample(self, values: Sequence[int], weights: Sequence[float], k: int) -> list[int]:
        remaining_values = list(values)
        remaining_weights = list(weights)
        selected: list[int] = []
        for _ in range(k):
            choice = self.random.choices(remaining_values, weights=remaining_weights, k=1)[0]
            idx = remaining_values.index(choice)
            selected.append(choice)
            del remaining_values[idx]
            del remaining_weights[idx]
        return selected

    def _valid_combo(self, combo: Combination) -> bool:
        main = list(combo.main_numbers)
        if len(set(main)) != 5 or len(set(combo.euro_numbers)) != 2:
            return False

        low_count = sum(number <= 25 for number in main)
        if low_count not in (2, 3):
            return False

        if self._is_arithmetic_pattern(main):
            return False

        if self._has_five_consecutive(main):
            return False

        main_sum = sum(main)
        if main_sum < 80 or main_sum > 180:
            return False

        return True

    @staticmethod
    def _has_five_consecutive(numbers: Sequence[int]) -> bool:
        return all(numbers[idx + 1] - numbers[idx] == 1 for idx in range(len(numbers) - 1))

    @staticmethod
    def _is_arithmetic_pattern(numbers: Sequence[int]) -> bool:
        diffs = [numbers[idx + 1] - numbers[idx] for idx in range(len(numbers) - 1)]
        return len(set(diffs)) == 1


def generate_hybrid_combinations(generator: CombinationGenerator, count: int = 10) -> list[tuple[str, list[Combination]]]:
    hot_count = count // 2
    cold_count = count - hot_count

    hot = generator.generate(count=hot_count, strategy="hot")
    exclude_keys = {combo.combo_key for combo in hot}
    cold = generator.generate(count=cold_count, strategy="cold", exclude_keys=exclude_keys)

    return [
        ("Jouw idee - vaker gevallen nummers", hot),
        ("Huidige idee - minder vaak gevallen nummers", cold),
    ]


def format_grouped_combinations_message(groups: Sequence[tuple[str, Sequence[Combination]]]) -> str:
    lines = ["Euro combinaties voor deze week:", ""]
    index = 1
    for title, combinations in groups:
        lines.append(f"{title}:")
        for combo in combinations:
            lines.append(combo.format_line(index))
            index += 1
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def format_combinations_message(combinations: Sequence[Combination]) -> str:
    return format_grouped_combinations_message([("Combinaties", combinations)])
