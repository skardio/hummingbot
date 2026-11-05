import sqlite3
import threading
import time

from multi_coin_grid_pro.observability.decision_telemetry import DecisionTelemetryEvent, DecisionTelemetryWriter


def _event(event_id="event-1", **overrides):
    values = {
        "event_id": event_id,
        "event_type": "BUY_DECISION_ALLOW",
        "event_timestamp": 1_800_000_000.0,
        "exchange": "bitget",
        "strategy": "multi_coin_grid_pro",
        "executor_id": "executor-1",
        "trading_pair": "BTC-USDT",
        "configured_cap": 4,
    }
    values.update(overrides)
    return DecisionTelemetryEvent(**values)


def test_writer_persists_nulls_and_is_idempotent(tmp_path):
    db_path = tmp_path / "decision.db"
    writer = DecisionTelemetryWriter(str(db_path), retention_days=90)
    assert writer.emit(_event())
    assert writer.emit(_event())
    assert writer.flush()
    writer.close()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*), reason_code, regime FROM DecisionTelemetryEvent WHERE event_id = ?",
            ("event-1",),
        ).fetchone()
        columns = {item[1] for item in conn.execute("PRAGMA table_info(DecisionTelemetryEvent)")}
    assert row == (1, None, None)
    assert "credentials" not in columns
    assert "api_key" not in columns


class _BlockingWriter(DecisionTelemetryWriter):
    def __init__(self, *args, **kwargs):
        self.release = threading.Event()
        super().__init__(*args, **kwargs)

    def _connect(self):
        self.release.wait(timeout=2)
        return super()._connect()


def test_queue_is_bounded_and_drops_without_blocking(tmp_path):
    writer = _BlockingWriter(str(tmp_path / "bounded.db"), queue_size=1)
    assert writer.emit(_event("first"))
    deadline = time.monotonic() + 1
    while writer.stats["queued"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert writer.emit(_event("second"))
    started = time.monotonic()
    assert not writer.emit(_event("third"))
    assert time.monotonic() - started < 0.1
    assert writer.stats["dropped"] == 1
    writer.release.set()
    assert writer.flush()
    writer.close()


def test_database_failure_is_non_fatal_and_counted(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("x")
    writer = DecisionTelemetryWriter(str(parent_file / "decision.db"))
    assert writer.emit(_event())
    assert writer.flush()
    assert writer.stats["write_failures"] == 1
    writer.close()


def test_unknown_event_type_is_rejected_without_raise(tmp_path):
    writer = DecisionTelemetryWriter(str(tmp_path / "invalid.db"))
    assert not writer.emit(_event(event_type="UNSAFE_UNKNOWN_EVENT"))
    assert writer.stats["dropped"] == 1
    writer.close()
