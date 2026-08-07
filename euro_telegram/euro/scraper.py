from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from .models import Draw

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.lotto.net/eurojackpot/results/{year}"
DATE_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) "
    r"[A-Za-z]+ \d{1,2}(?:st|nd|rd|th) \d{4}$"
)
WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
DATE_REST_RE = re.compile(r"^[A-Za-z]+ \d{1,2}(?:st|nd|rd|th) \d{4}$")
ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)")


class ScrapeError(RuntimeError):
    pass


class EuroScraper:
    def __init__(
        self,
        timeout_seconds: int = 20,
        retries: int = 3,
        retry_sleep_seconds: float = 2.0,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_sleep_seconds = retry_sleep_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 EuroHistoricalAnalyzer/0.1 "
                    "(local personal analysis script)"
                )
            }
        )

    def scrape_years(self, years: Iterable[int]) -> list[Draw]:
        draws: list[Draw] = []
        for year in years:
            try:
                year_draws = self.scrape_year(year)
            except ScrapeError:
                LOGGER.exception("Could not scrape Euro results for %s", year)
                continue
            draws.extend(year_draws)
        unique = {draw.draw_date.isoformat(): draw for draw in draws}
        return sorted(unique.values(), key=lambda draw: draw.draw_date)

    def scrape_year(self, year: int) -> list[Draw]:
        url = BASE_URL.format(year=year)
        html = self._fetch(url)
        draws = self._parse_results_page(html, year=year, source_url=url)
        LOGGER.info("Scraped %s Euro draws for %s", len(draws), year)
        return draws

    def _fetch(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning(
                    "Fetch failed for %s on attempt %s/%s: %s",
                    url,
                    attempt,
                    self.retries,
                    exc,
                )
                if attempt < self.retries:
                    time.sleep(self.retry_sleep_seconds * attempt)
        raise ScrapeError(f"Failed to fetch {url}") from last_error

    def _parse_results_page(self, html: str, year: int, source_url: str) -> list[Draw]:
        soup = BeautifulSoup(html, "html.parser")
        lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
        date_indexes = self._date_indexes(lines)

        draws: list[Draw] = []
        for pos, (idx, content_idx, date_line) in enumerate(date_indexes):
            next_idx = date_indexes[pos + 1][0] if pos + 1 < len(date_indexes) else len(lines)
            block = lines[content_idx:next_idx]
            numbers = self._first_seven_integer_lines(block)
            draw_date = self._parse_date(date_line)
            if draw_date.year != year:
                continue
            if len(numbers) < 7:
                if draw_date >= date.today():
                    LOGGER.info("Skipping upcoming draw %s: no result numbers yet", date_line)
                else:
                    LOGGER.warning("Skipping %s: found only %s numbers", date_line, len(numbers))
                continue

            main_numbers = tuple(sorted(numbers[:5]))
            euro_numbers = tuple(sorted(numbers[5:7]))
            if not self._valid_numbers(main_numbers, euro_numbers):
                LOGGER.warning(
                    "Skipping %s due to invalid numbers: main=%s euro=%s",
                    date_line,
                    main_numbers,
                    euro_numbers,
                )
                continue

            draws.append(
                Draw(
                    draw_date=draw_date,
                    main_numbers=main_numbers,  # type: ignore[arg-type]
                    euro_numbers=euro_numbers,  # type: ignore[arg-type]
                    source_year=year,
                    source_url=source_url,
                )
            )
        return draws

    @staticmethod
    def _date_indexes(lines: list[str]) -> list[tuple[int, int, str]]:
        indexes: list[tuple[int, int, str]] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if DATE_RE.match(line):
                indexes.append((idx, idx + 1, line))
                idx += 1
                continue
            if line in WEEKDAYS and idx + 1 < len(lines) and DATE_REST_RE.match(lines[idx + 1]):
                indexes.append((idx, idx + 2, f"{line} {lines[idx + 1]}"))
                idx += 2
                continue
            idx += 1
        return indexes

    @staticmethod
    def _first_seven_integer_lines(lines: list[str]) -> list[int]:
        numbers: list[int] = []
        skip_next_integer = False
        for line in lines:
            if line == "Draw Number:":
                skip_next_integer = True
                continue
            if skip_next_integer and re.fullmatch(r"\d+", line):
                skip_next_integer = False
                continue
            if re.fullmatch(r"\d{1,2}", line):
                numbers.append(int(line))
                if len(numbers) == 7:
                    break
        return numbers

    @staticmethod
    def _parse_date(date_line: str):
        normalized = ORDINAL_RE.sub(r"\1", date_line)
        return datetime.strptime(normalized, "%A %B %d %Y").date()

    @staticmethod
    def _valid_numbers(main_numbers: tuple[int, ...], euro_numbers: tuple[int, ...]) -> bool:
        return (
            len(main_numbers) == 5
            and len(euro_numbers) == 2
            and len(set(main_numbers)) == 5
            and len(set(euro_numbers)) == 2
            and all(1 <= number <= 50 for number in main_numbers)
            and all(1 <= number <= 12 for number in euro_numbers)
        )
