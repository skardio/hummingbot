# test_signal_store.py — unit tests for momentum_signal_store.py
import json
import sqlite3
from pathlib import Path

import pytest

from multi_coin_grid_pro.signals.momentum_models import MomentumSignal, ScanResult
from multi_coin_grid_pro.signals.momentum_signal_store import _GRID_DB_NAMES, JsonSnapshotWriter, SignalStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GRID_DB_NAMES = list(_GRID_DB_NAMES)


def make_signal(
    trading_pair: str = "BTC-USD",
    accepted: bool = True,
    rank: int = 1,
    score: float = 0.82,
    rejection_reason: str = None,
) -> MomentumSignal:
    return MomentumSignal(
        scan_id="scan-001",
        timestamp=1_700_000_000.0,
        exchange="kraken",
        trading_pair=trading_pair,
        price=100.0,
        spread_pct=0.10,
        price_change_5m_pct=3.0,
        price_change_15m_pct=5.0,
        volume_ratio=4.0,
        score=score,
        accepted=accepted,
        rank=rank if accepted else None,
        rejection_reason=rejection_reason,
        all_reasons=[] if accepted else [rejection_reason or "SCORE_TOO_LOW"],
        score_breakdown={"trend_1h": 0.8, "trend_4h": 0.9},
    )


def make_scan_result(n_accepted: int = 2, n_rejected: int = 1) -> ScanResult:
    signals = []
    for i in range(n_accepted):
        signals.append(make_signal(trading_pair=f"C{i}-USD", rank=i + 1))
    for i in range(n_rejected):
        signals.append(make_signal(
            trading_pair=f"R{i}-USD", accepted=False,
            rejection_reason="SCORE_TOO_LOW",
        ))
    return ScanResult(
        scan_id="scan-001",
        timestamp=1_700_000_000.0,
        scan_duration_seconds=2.5,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# SignalStore — path guard
# ---------------------------------------------------------------------------

class TestSignalStorePathGuard:

    @pytest.mark.parametrize("grid_db_name", GRID_DB_NAMES)
    def test_grid_db_path_rejected(self, grid_db_name: str) -> None:
        with pytest.raises((ValueError, AssertionError)):
            SignalStore(db_path=f"data/{grid_db_name}")

    def test_custom_path_accepted(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "momentum_signals.sqlite"))
        assert store.count() == 0
        store.close()

    def test_parent_dir_created_automatically(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "signals.sqlite"
        store = SignalStore(db_path=str(nested))
        store.close()
        assert nested.exists()


# ---------------------------------------------------------------------------
# SignalStore — schema
# ---------------------------------------------------------------------------

class TestSignalStoreSchema:

    def test_signals_table_exists(self, tmp_path: Path) -> None:
        db = tmp_path / "s.sqlite"
        store = SignalStore(db_path=str(db))
        store.close()
        conn = sqlite3.connect(str(db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "signals" in tables
        conn.close()

    def test_wal_mode_set(self, tmp_path: Path) -> None:
        db = tmp_path / "s.sqlite"
        store = SignalStore(db_path=str(db))
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        store.close()


# ---------------------------------------------------------------------------
# SignalStore — save / save_batch
# ---------------------------------------------------------------------------

class TestSignalStoreSave:

    def test_save_returns_integer_id(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        row_id = store.save(make_signal())
        assert isinstance(row_id, int)
        assert row_id >= 1
        store.close()

    def test_save_sets_signal_id(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        sig = make_signal()
        assert sig.id is None
        store.save(sig)
        assert sig.id is not None
        store.close()

    def test_save_increments_count(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        store.save(make_signal())
        store.save(make_signal(trading_pair="ETH-USD"))
        assert store.count() == 2
        store.close()

    def test_save_batch_returns_ids(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        signals = [make_signal(trading_pair=f"C{i}-USD") for i in range(5)]
        ids = store.save_batch(signals)
        assert len(ids) == 5
        assert all(isinstance(i, int) for i in ids)
        store.close()

    def test_save_batch_sets_signal_ids(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        signals = [make_signal(trading_pair=f"C{i}-USD") for i in range(3)]
        store.save_batch(signals)
        assert all(s.id is not None for s in signals)
        store.close()

    def test_rejected_signal_stored(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        sig = make_signal(accepted=False, rejection_reason="SPREAD_TOO_HIGH")
        store.save(sig)
        assert store.count() == 1
        store.close()

    def test_all_reasons_stored_as_json(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        sig = make_signal(accepted=False, rejection_reason="BLACKLISTED")
        sig.all_reasons = ["BLACKLISTED", "SPREAD_TOO_HIGH"]
        store.save(sig)
        row = store.load_recent(1)[0]
        parsed = json.loads(row["all_reasons"])
        assert "BLACKLISTED" in parsed
        store.close()

    def test_score_breakdown_stored_as_json(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        sig = make_signal()
        sig.score_breakdown = {"trend_1h": 0.75, "trend_4h": 0.85}
        store.save(sig)
        row = store.load_recent(1)[0]
        parsed = json.loads(row["score_breakdown"])
        assert parsed["trend_1h"] == pytest.approx(0.75)
        store.close()


# ---------------------------------------------------------------------------
# SignalStore — load_recent
# ---------------------------------------------------------------------------

class TestSignalStoreLoad:

    def test_load_recent_returns_list(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        store.save(make_signal())
        rows = store.load_recent()
        assert isinstance(rows, list)
        assert len(rows) == 1
        store.close()

    def test_load_recent_respects_limit(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        for i in range(10):
            store.save(make_signal(trading_pair=f"C{i}-USD"))
        rows = store.load_recent(limit=3)
        assert len(rows) == 3
        store.close()

    def test_load_recent_empty_db(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        assert store.load_recent() == []
        store.close()


# ---------------------------------------------------------------------------
# SignalStore — purge_old
# ---------------------------------------------------------------------------

class TestSignalStorePurge:

    def test_purge_removes_old_records(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        store.save(make_signal())
        # Force created_at to be ancient
        store._conn.execute(
            "UPDATE signals SET created_at = 0"
        )
        store._conn.commit()
        deleted = store.purge_old(retention_days=30)
        assert deleted == 1
        assert store.count() == 0
        store.close()

    def test_purge_keeps_recent_records(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        store.save(make_signal())
        deleted = store.purge_old(retention_days=30)
        assert deleted == 0
        assert store.count() == 1
        store.close()

    def test_purge_returns_count(self, tmp_path: Path) -> None:
        store = SignalStore(db_path=str(tmp_path / "s.sqlite"))
        for _ in range(3):
            store.save(make_signal())
        store._conn.execute("UPDATE signals SET created_at = 0")
        store._conn.commit()
        count = store.purge_old(retention_days=1)
        assert count == 3
        store.close()


# ---------------------------------------------------------------------------
# JsonSnapshotWriter
# ---------------------------------------------------------------------------

class TestJsonSnapshotWriter:

    def test_writes_json_file(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result())
        assert Path(path).exists()

    def test_json_is_valid(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result())
        with open(path) as fh:
            data = json.load(fh)
        assert "scan_id" in data
        assert "top_signals" in data

    def test_disclaimer_present(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result())
        with open(path) as fh:
            data = json.load(fh)
        assert "GEEN ORDERS" in data["disclaimer"]

    def test_tmp_file_not_left_behind(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result())
        assert not Path(path + ".tmp").exists()

    def test_overwrite_is_atomic(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result(n_accepted=1))
        writer.write(make_scan_result(n_accepted=3))
        with open(path) as fh:
            data = json.load(fh)
        assert data["total_accepted"] == 3

    def test_parent_dir_created_automatically(self, tmp_path: Path) -> None:
        path = str(tmp_path / "sub" / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        writer.write(make_scan_result())
        assert Path(path).exists()

    def test_scan_metadata_correct(self, tmp_path: Path) -> None:
        path = str(tmp_path / "latest.json")
        writer = JsonSnapshotWriter(snapshot_path=path)
        scan = make_scan_result(n_accepted=2, n_rejected=1)
        writer.write(scan)
        with open(path) as fh:
            data = json.load(fh)
        assert data["total_scanned"] == 3
        assert data["total_accepted"] == 2
        assert data["total_rejected"] == 1
