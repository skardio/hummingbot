# test_signal_readers.py — unit tests for grid_position_reader.py and blacklist_reader.py
import sqlite3
from pathlib import Path

import pytest
import yaml

from multi_coin_grid_pro.signals.blacklist_reader import BlacklistReader
from multi_coin_grid_pro.signals.grid_position_reader import GridPositionReader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REAL_BLACKLIST_YAML = "multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml"


def _make_grid_db(path: Path) -> None:
    """Create a minimal Executors table matching production schema."""
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS Executors (
            id TEXT PRIMARY KEY,
            timestamp FLOAT NOT NULL,
            type TEXT NOT NULL,
            close_type INTEGER,
            close_timestamp BIGINT,
            status INTEGER NOT NULL,
            config JSON NOT NULL,
            net_pnl_pct FLOAT NOT NULL DEFAULT 0,
            net_pnl_quote FLOAT NOT NULL DEFAULT 0,
            cum_fees_quote FLOAT NOT NULL DEFAULT 0,
            filled_amount_quote FLOAT NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 0,
            is_trading BOOLEAN NOT NULL DEFAULT 0,
            custom_info JSON NOT NULL DEFAULT '{}',
            controller_id TEXT
        )
    """)
    rows = [
        ("e1", 1.0, "GridExecutor", 1, '{"trading_pair": "BTC-USD"}', 1, 1),
        ("e2", 2.0, "GridExecutor", 2, '{"trading_pair": "ETH-USD"}', 1, 0),
        ("e3", 3.0, "GridExecutor", 2, '{"trading_pair": "SOL-USD"}', 0, 0),  # inactive
    ]
    for row_id, ts, typ, status, config, is_active, is_trading in rows:
        conn.execute(
            "INSERT INTO Executors "
            "(id, timestamp, type, status, config, is_active, is_trading, "
            "net_pnl_pct, net_pnl_quote, cum_fees_quote, filled_amount_quote, custom_info) "
            "VALUES (?,?,?,?,?,?,?,0,0,0,0,'{}')",
            (row_id, ts, typ, status, config, is_active, is_trading),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# GridPositionReader
# ---------------------------------------------------------------------------

class TestGridPositionReader:

    def test_returns_active_pairs(self, tmp_path: Path) -> None:
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        reader = GridPositionReader(db_path=str(db))
        pairs = reader.get_active_pairs()
        assert "BTC-USD" in pairs
        assert "ETH-USD" in pairs

    def test_excludes_inactive_pairs(self, tmp_path: Path) -> None:
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        reader = GridPositionReader(db_path=str(db))
        pairs = reader.get_active_pairs()
        assert "SOL-USD" not in pairs

    def test_missing_db_returns_empty_set(self, tmp_path: Path) -> None:
        reader = GridPositionReader(db_path=str(tmp_path / "nonexistent.sqlite"))
        assert reader.get_active_pairs() == set()

    def test_missing_db_conn_is_none(self, tmp_path: Path) -> None:
        reader = GridPositionReader(db_path=str(tmp_path / "nonexistent.sqlite"))
        assert reader._conn is None

    def test_conn_is_readonly_rejects_insert(self, tmp_path: Path) -> None:
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        reader = GridPositionReader(db_path=str(db))
        with pytest.raises(Exception):
            reader._conn.execute(
                "INSERT INTO Executors "
                "(id, timestamp, type, status, config, "
                "net_pnl_pct, net_pnl_quote, cum_fees_quote, filled_amount_quote, "
                "is_active, is_trading, custom_info) "
                "VALUES ('x',1,'T',1,'{}',0,0,0,0,0,0,'{}')"
            )
            reader._conn.commit()

    def test_checksum_unchanged_after_read(self, tmp_path: Path) -> None:
        import hashlib
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        checksum_before = hashlib.md5(db.read_bytes()).hexdigest()
        reader = GridPositionReader(db_path=str(db))
        reader.get_active_pairs()
        assert hashlib.md5(db.read_bytes()).hexdigest() == checksum_before

    def test_empty_table_returns_empty_set(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE Executors "
            "(id TEXT, timestamp FLOAT, type TEXT, status INT, "
            "config JSON, is_active BOOLEAN, is_trading BOOLEAN, "
            "net_pnl_pct FLOAT, net_pnl_quote FLOAT, cum_fees_quote FLOAT, "
            "filled_amount_quote FLOAT, custom_info JSON)"
        )
        conn.commit()
        conn.close()
        reader = GridPositionReader(db_path=str(db))
        assert reader.get_active_pairs() == set()

    def test_close_sets_conn_to_none(self, tmp_path: Path) -> None:
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        reader = GridPositionReader(db_path=str(db))
        assert reader._conn is not None
        reader.close()
        assert reader._conn is None

    def test_returns_set_type(self, tmp_path: Path) -> None:
        db = tmp_path / "grid.sqlite"
        _make_grid_db(db)
        reader = GridPositionReader(db_path=str(db))
        result = reader.get_active_pairs()
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# BlacklistReader
# ---------------------------------------------------------------------------

class TestBlacklistReader:

    def _write_yaml(self, path: Path, content: dict) -> None:
        with open(path, "w") as fh:
            yaml.dump(content, fh)

    def test_returns_blacklisted_pairs(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        self._write_yaml(f, {"blacklist": ["BTC-USD", "ETH-USD", "USDT-USD"]})
        reader = BlacklistReader(yaml_path=str(f))
        pairs = reader.get_blacklisted_pairs()
        assert "BTC-USD" in pairs
        assert "USDT-USD" in pairs

    def test_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        reader = BlacklistReader(yaml_path=str(tmp_path / "nonexistent.yaml"))
        assert reader.get_blacklisted_pairs() == set()

    def test_missing_blacklist_key_returns_empty_set(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        self._write_yaml(f, {"other_key": ["BTC-USD"]})
        reader = BlacklistReader(yaml_path=str(f))
        assert reader.get_blacklisted_pairs() == set()

    def test_empty_blacklist_returns_empty_set(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        self._write_yaml(f, {"blacklist": []})
        reader = BlacklistReader(yaml_path=str(f))
        assert reader.get_blacklisted_pairs() == set()

    def test_returns_set_type(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        self._write_yaml(f, {"blacklist": ["BTC-USD"]})
        reader = BlacklistReader(yaml_path=str(f))
        assert isinstance(reader.get_blacklisted_pairs(), set)

    def test_real_config_loads_without_error(self) -> None:
        reader = BlacklistReader(yaml_path=REAL_BLACKLIST_YAML)
        pairs = reader.get_blacklisted_pairs()
        # Stablecoins are always in the blacklist
        assert "USDT-USD" in pairs
        assert "USDC-USD" in pairs

    def test_real_config_returns_set_of_strings(self) -> None:
        reader = BlacklistReader(yaml_path=REAL_BLACKLIST_YAML)
        pairs = reader.get_blacklisted_pairs()
        assert all(isinstance(p, str) for p in pairs)
