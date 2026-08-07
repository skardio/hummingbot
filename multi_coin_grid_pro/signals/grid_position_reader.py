# grid_position_reader.py — read active trading pairs from a grid-bot SQLite DB.
# Opens via read-only URI (file:path?mode=ro) — never writes to the grid DB.
import sqlite3
from pathlib import Path
from typing import Optional, Set


class GridPositionReader:
    """Return the set of trading pairs that currently have an active grid position.

    Opens the database via a read-only URI so the OS rejects any write attempt.
    If the database file does not exist, ``get_active_pairs()`` returns an empty
    set — no exception is raised.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        if Path(db_path).exists():
            self._conn = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True
            )

    def get_active_pairs(self) -> Set[str]:
        """Return trading pairs with ``is_active = 1`` in the Executors table."""
        if self._conn is None:
            return set()
        try:
            cursor = self._conn.execute(
                "SELECT json_extract(config, '$.trading_pair') "
                "FROM Executors WHERE is_active = 1"
            )
            return {row[0] for row in cursor.fetchall() if row[0]}
        except Exception:
            return set()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
