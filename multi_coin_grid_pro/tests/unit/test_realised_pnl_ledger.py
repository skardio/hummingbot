"""FIX-002: tests for the durable realised-PnL claim ledger.

The ledger is what turns "the kill switch never sees the PnL" into "the kill
switch sees it exactly once". These tests pin that guarantee, including across
simulated restarts.
"""
from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from multi_coin_grid_pro.persistence.realised_pnl_ledger import RealisedPnlLedger  # noqa: E402


@pytest.fixture
def ledger_path(tmp_path):
    return str(tmp_path / "realised_pnl_ledger.db")


@pytest.fixture
def ledger(ledger_path):
    return RealisedPnlLedger(ledger_path)


def test_first_claim_succeeds(ledger):
    assert ledger.claim("exec-1") is True
    assert ledger.is_processed("exec-1") is True


def test_second_claim_is_refused(ledger):
    assert ledger.claim("exec-1") is True
    assert ledger.claim("exec-1") is False
    assert ledger.count() == 1


def test_repeated_claims_never_double_count(ledger):
    """A tick loop that runs many times must still deliver once."""
    results = [ledger.claim("exec-1") for _ in range(50)]
    assert results.count(True) == 1
    assert results.count(False) == 49
    assert ledger.count() == 1


def test_restart_does_not_double_count(ledger_path):
    """A fresh instance on the same file refuses an already-claimed executor."""
    first = RealisedPnlLedger(ledger_path)
    assert first.claim("exec-1") is True

    restarted = RealisedPnlLedger(ledger_path)
    assert restarted.claim("exec-1") is False
    assert restarted.is_processed("exec-1") is True
    assert restarted.count() == 1


def test_distinct_executors_each_claim_once(ledger):
    ids = [f"exec-{i}" for i in range(10)]
    assert all(ledger.claim(i) for i in ids)
    assert not any(ledger.claim(i) for i in ids)
    assert ledger.count() == 10


def test_metadata_is_stored(ledger, ledger_path):
    ledger.claim(
        "exec-xdc",
        controller_id="multi_coin_grid_usd",
        trading_pair="XDC-USD",
        close_timestamp=1791260419,
        realised_pnl=Decimal("-33.3897"),
    )
    with sqlite3.connect(ledger_path) as connection:
        row = connection.execute(
            "SELECT controller_id, trading_pair, close_timestamp, realised_pnl "
            "FROM realised_pnl_processed WHERE executor_id = ?",
            ("exec-xdc",),
        ).fetchone()
    assert row == ("multi_coin_grid_usd", "XDC-USD", 1791260419, "-33.3897")


def test_pnl_stored_as_string_not_float(ledger, ledger_path):
    """Decimal precision must survive; floats would corrupt financial values."""
    ledger.claim("exec-precise", realised_pnl=Decimal("0.123456789012345678"))
    with sqlite3.connect(ledger_path) as connection:
        value = connection.execute(
            "SELECT realised_pnl FROM realised_pnl_processed WHERE executor_id = ?",
            ("exec-precise",),
        ).fetchone()[0]
    assert value == "0.123456789012345678"
    assert Decimal(value) == Decimal("0.123456789012345678")


def test_empty_executor_id_is_refused(ledger):
    assert ledger.claim("") is False
    assert ledger.claim(None) is False
    assert ledger.count() == 0


def test_claim_fails_closed_on_database_error(tmp_path, monkeypatch):
    """A broken ledger must refuse, never allow a possible double count."""
    ledger = RealisedPnlLedger(str(tmp_path / "ledger.db"))
    assert ledger.claim("exec-1") is True

    def broken_connect():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ledger, "_connect", broken_connect)
    assert ledger.claim("exec-2") is False
    assert ledger.is_processed("exec-1") is False  # lookup also fails closed
    assert ledger.count() == 0


def test_claim_survives_a_corrupt_file(tmp_path):
    """An unreadable database refuses claims rather than raising."""
    path = tmp_path / "subdir" / "ledger.db"
    ledger = RealisedPnlLedger(str(path))
    assert ledger.claim("exec-1") is True

    # Replace the database and its WAL with rubbish.
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.write_text("not a sqlite database")

    assert ledger.claim("exec-2") is False


def test_is_processed_is_false_for_unknown(ledger):
    assert ledger.is_processed("never-seen") is False


def test_schema_survives_reopen(ledger_path):
    RealisedPnlLedger(ledger_path)
    second = RealisedPnlLedger(ledger_path)
    assert second.count() == 0
    assert second.claim("exec-1") is True
