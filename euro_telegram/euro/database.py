from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .models import ComboKey, Draw

LOGGER = logging.getLogger(__name__)


class DrawDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS draws (
                    draw_date TEXT PRIMARY KEY,
                    main_1 INTEGER NOT NULL,
                    main_2 INTEGER NOT NULL,
                    main_3 INTEGER NOT NULL,
                    main_4 INTEGER NOT NULL,
                    main_5 INTEGER NOT NULL,
                    euro_1 INTEGER NOT NULL,
                    euro_2 INTEGER NOT NULL,
                    source_year INTEGER NOT NULL,
                    source_url TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    UNIQUE(main_1, main_2, main_3, main_4, main_5, euro_1, euro_2)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_draws_source_year ON draws(source_year)")

    def upsert_draws(self, draws: list[Draw]) -> int:
        if not draws:
            LOGGER.warning("No draws to store")
            return 0

        scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = [
            (
                draw.draw_date.isoformat(),
                *draw.main_numbers,
                *draw.euro_numbers,
                draw.source_year,
                draw.source_url,
                scraped_at,
            )
            for draw in draws
        ]

        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO draws (
                    draw_date,
                    main_1, main_2, main_3, main_4, main_5,
                    euro_1, euro_2,
                    source_year, source_url, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draw_date) DO UPDATE SET
                    main_1=excluded.main_1,
                    main_2=excluded.main_2,
                    main_3=excluded.main_3,
                    main_4=excluded.main_4,
                    main_5=excluded.main_5,
                    euro_1=excluded.euro_1,
                    euro_2=excluded.euro_2,
                    source_year=excluded.source_year,
                    source_url=excluded.source_url,
                    scraped_at=excluded.scraped_at
                """,
                rows,
            )
        LOGGER.info("Stored/updated %s Euro draws in %s", len(rows), self.db_path)
        return len(rows)

    def draw_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM draws").fetchone()
        return int(row["n"])

    def latest_draw_date(self) -> date | None:
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(draw_date) AS latest FROM draws").fetchone()
        if not row["latest"]:
            return None
        return date.fromisoformat(row["latest"])

    def load_dataframe(self) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                """
                SELECT
                    draw_date,
                    main_1, main_2, main_3, main_4, main_5,
                    euro_1, euro_2,
                    source_year,
                    source_url,
                    scraped_at
                FROM draws
                ORDER BY draw_date
                """,
                conn,
            )

    def existing_combinations(self) -> set[ComboKey]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT main_1, main_2, main_3, main_4, main_5, euro_1, euro_2
                FROM draws
                """
            ).fetchall()
        return {
            (
                tuple(row[f"main_{idx}"] for idx in range(1, 6)),
                tuple(row[f"euro_{idx}"] for idx in range(1, 3)),
            )
            for row in rows
        }
