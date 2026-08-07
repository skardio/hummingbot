from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ComboKey = tuple[tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True)
class Draw:
    draw_date: date
    main_numbers: tuple[int, int, int, int, int]
    euro_numbers: tuple[int, int]
    source_year: int
    source_url: str

    @property
    def combo_key(self) -> ComboKey:
        return (tuple(sorted(self.main_numbers)), tuple(sorted(self.euro_numbers)))


@dataclass(frozen=True)
class Combination:
    main_numbers: tuple[int, int, int, int, int]
    euro_numbers: tuple[int, int]

    @property
    def combo_key(self) -> ComboKey:
        return (tuple(sorted(self.main_numbers)), tuple(sorted(self.euro_numbers)))

    def format_line(self, index: int) -> str:
        main = ", ".join(str(n) for n in self.main_numbers)
        euro = ", ".join(str(n) for n in self.euro_numbers)
        return f"{index}. {main} | {euro}"
