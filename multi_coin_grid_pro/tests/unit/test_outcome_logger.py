"""
Tests for AI-F2: OutcomeLogger.

Covers:
- OutcomeRecord creation and serialization
- register_pending → record_outcome linking
- Unlinked outcomes (missing_outcome=True)
- Buffered JSONL flush, close, rotation
- Disabled logger does nothing
- Logging failure never raises
- < 5ms latency per record_outcome call
"""

import json
import os
import shutil
import tempfile
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from multi_coin_grid_pro.observability.outcome_logger import OUTCOME_SCHEMA_VERSION, OutcomeLogger, OutcomeRecord

# ─── fixtures ────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def logger(tmp_dir):
    return OutcomeLogger(enabled=True, output_dir=tmp_dir, buffer_size=5)


@pytest.fixture
def disabled_logger(tmp_dir):
    return OutcomeLogger(enabled=False, output_dir=tmp_dir)


def _make_executor_info(
    executor_id="exec-001",
    trading_pair="BTC-EUR",
    net_pnl_quote=1.5,
    net_pnl_pct=0.03,
    cum_fees_quote=0.12,
    filled_amount_quote=50.0,
    close_type_name="TAKE_PROFIT",
    timestamp=None,
    close_timestamp=None,
    custom_info=None,
):
    """Create a mock executor_info object."""
    ts = timestamp or time.time() - 600
    cts = close_timestamp or time.time()

    ct = SimpleNamespace(name=close_type_name)
    ct.__str__ = lambda self: self.name

    config = SimpleNamespace(
        trading_pair=trading_pair,
        total_amount_quote=Decimal("50.0"),
    )

    return SimpleNamespace(
        id=executor_id,
        config=config,
        timestamp=ts,
        close_timestamp=cts,
        net_pnl_quote=Decimal(str(net_pnl_quote)),
        net_pnl_pct=Decimal(str(net_pnl_pct)),
        cum_fees_quote=Decimal(str(cum_fees_quote)),
        filled_amount_quote=Decimal(str(filled_amount_quote)),
        close_type=ct,
        custom_info=custom_info or {
            "realized_buy_size_quote": 25.0,
            "realized_sell_size_quote": 26.5,
            "levels_by_state": {"FILLED": 3, "OPEN": 2},
        },
    )


# ─── OutcomeRecord tests ────────────────────────────────────────

class TestOutcomeRecord:

    def test_defaults(self):
        rec = OutcomeRecord(decision_id="d-1")
        assert rec.decision_id == "d-1"
        assert rec.schema_version == OUTCOME_SCHEMA_VERSION
        assert rec.filled is False
        assert rec.missing_outcome is False
        assert rec.net_pnl_quote == 0.0

    def test_to_dict_is_json_serializable(self):
        rec = OutcomeRecord(
            decision_id="d-2",
            executor_id="e-1",
            symbol="ETH-EUR",
            net_pnl_quote=2.5,
            filled=True,
        )
        result = json.dumps(rec.to_dict())
        assert '"decision_id": "d-2"' in result
        assert '"filled": true' in result


# ─── OutcomeLogger tests ────────────────────────────────────────

class TestOutcomeLogger:

    def test_register_and_record(self, logger, tmp_dir):
        """Full lifecycle: register pending → record outcome → flush."""
        logger.register_pending("dec-1", "exec-1", "BTC-EUR", "kraken")
        assert len(logger._pending) == 1

        executor = _make_executor_info(executor_id="exec-1")
        logger.record_outcome("exec-1", executor, time.time())

        # Pending should be consumed
        assert len(logger._pending) == 0

        logger.flush()

        files = os.listdir(tmp_dir)
        assert len(files) == 1
        assert files[0].startswith("outcomes_")

        with open(os.path.join(tmp_dir, files[0])) as f:
            record = json.loads(f.readline())

        assert record["decision_id"] == "dec-1"
        assert record["executor_id"] == "exec-1"
        assert record["symbol"] == "BTC-EUR"
        assert record["exchange"] == "kraken"
        assert record["missing_outcome"] is False
        assert record["filled"] is True
        assert record["grid_levels_filled"] == 3
        assert record["schema_version"] == OUTCOME_SCHEMA_VERSION

    def test_unlinked_outcome(self, logger, tmp_dir):
        """Outcome without register_pending → missing_outcome=True."""
        executor = _make_executor_info(executor_id="orphan-1")
        logger.record_outcome("orphan-1", executor, time.time())
        logger.flush()

        with open(os.path.join(tmp_dir, os.listdir(tmp_dir)[0])) as f:
            record = json.loads(f.readline())

        assert record["decision_id"] == ""
        assert record["missing_outcome"] is True
        assert logger.stats["total_missing"] == 1

    def test_auto_flush_on_buffer_full(self, logger, tmp_dir):
        """Buffer size is 5 — after 5 records, should auto-flush."""
        for i in range(5):
            executor = _make_executor_info(executor_id=f"exec-{i}")
            logger.record_outcome(f"exec-{i}", executor, time.time())

        files = os.listdir(tmp_dir)
        assert len(files) == 1
        with open(os.path.join(tmp_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_close_flushes_remaining(self, logger, tmp_dir):
        executor = _make_executor_info()
        logger.record_outcome("exec-001", executor, time.time())
        # Not yet flushed (buffer_size=5)
        assert len(os.listdir(tmp_dir)) == 0

        logger.close()

        files = os.listdir(tmp_dir)
        assert len(files) == 1
        with open(os.path.join(tmp_dir, files[0])) as f:
            assert len(f.readlines()) == 1

    def test_disabled_logger_does_nothing(self, disabled_logger, tmp_dir):
        disabled_logger.register_pending("d-1", "e-1", "BTC-EUR", "kraken")
        executor = _make_executor_info()
        disabled_logger.record_outcome("e-1", executor, time.time())
        disabled_logger.flush()
        assert len(os.listdir(tmp_dir)) == 0
        assert disabled_logger.stats["total_logged"] == 0

    def test_stats(self, logger):
        logger.register_pending("d-1", "e-1", "BTC-EUR", "kraken")
        logger.register_pending("d-2", "e-2", "ETH-EUR", "kraken")

        executor1 = _make_executor_info(executor_id="e-1")
        logger.record_outcome("e-1", executor1, time.time())

        executor_orphan = _make_executor_info(executor_id="e-unknown")
        logger.record_outcome("e-unknown", executor_orphan, time.time())

        logger.flush()
        s = logger.stats
        assert s["total_logged"] == 2
        assert s["total_missing"] == 1
        assert s["pending_count"] == 1  # e-2 still pending
        assert s["total_errors"] == 0

    def test_decimal_serialization(self, logger, tmp_dir):
        executor = _make_executor_info(
            net_pnl_quote=Decimal("1.23456"),
            cum_fees_quote=Decimal("0.05"),
        )
        logger.record_outcome("e-1", executor, time.time())
        logger.flush()

        with open(os.path.join(tmp_dir, os.listdir(tmp_dir)[0])) as f:
            record = json.loads(f.readline())

        assert isinstance(record["net_pnl_quote"], float)
        assert isinstance(record["cum_fees_quote"], float)

    def test_rotation_retention(self, tmp_dir):
        lgr = OutcomeLogger(enabled=True, output_dir=tmp_dir, retention_days=0)
        old_file = os.path.join(tmp_dir, "outcomes_2020-01-01.jsonl")
        with open(old_file, "w") as f:
            f.write("{}\n")
        os.utime(old_file, (0, 0))
        lgr.rotate()
        assert not os.path.exists(old_file)

    def test_record_never_raises(self, tmp_dir):
        """Even if output dir is invalid, record_outcome must not raise."""
        lgr = OutcomeLogger(
            enabled=True, output_dir="/dev/null/impossible", buffer_size=1
        )
        executor = _make_executor_info()
        # This MUST NOT raise
        lgr.record_outcome("e-1", executor, time.time())
        lgr.flush()
        lgr.close()

    def test_close_type_mapping(self, logger, tmp_dir):
        """Test various close_type strings are mapped correctly."""
        cases = [
            ("STOP_LOSS", "stop_loss"),
            ("TAKE_PROFIT", "take_profit"),
            ("NO_FILL_TIMEOUT", "no_fill_timeout"),
            ("NO_PROGRESS_TIMEOUT", "no_progress_timeout"),
            ("TIME_LIMIT", "time_limit"),
            ("HARD_CAP_TIME_LIMIT", "time_limit"),
            ("SWITCH", "switch"),
            ("FAILED", "failed"),
        ]
        for close_type_name, expected_reason in cases:
            executor = _make_executor_info(
                executor_id=f"e-{close_type_name}",
                close_type_name=close_type_name,
            )
            logger.record_outcome(f"e-{close_type_name}", executor, time.time())

        logger.flush()

        with open(os.path.join(tmp_dir, os.listdir(tmp_dir)[0])) as f:
            lines = f.readlines()

        assert len(lines) == len(cases)
        for line, (_, expected_reason) in zip(lines, cases):
            record = json.loads(line)
            assert record["close_reason"] == expected_reason

    def test_hold_time_calculation(self, logger, tmp_dir):
        entry_ts = 1000.0
        close_ts = 1600.0
        executor = _make_executor_info(
            timestamp=entry_ts, close_timestamp=close_ts,
        )
        logger.register_pending("d-1", "exec-001", "BTC-EUR", "kraken")
        # Manually set entry_ts in pending to match
        logger._pending["exec-001"]["entry_ts"] = entry_ts

        logger.record_outcome("exec-001", executor, close_ts)
        logger.flush()

        with open(os.path.join(tmp_dir, os.listdir(tmp_dir)[0])) as f:
            record = json.loads(f.readline())
        assert record["hold_time_sec"] == 600.0

    def test_no_fill_detection(self, logger, tmp_dir):
        """Executor with filled_amount_quote < 1.0 → filled=False."""
        executor = _make_executor_info(filled_amount_quote=0.5)
        logger.record_outcome("e-1", executor, time.time())
        logger.flush()

        with open(os.path.join(tmp_dir, os.listdir(tmp_dir)[0])) as f:
            record = json.loads(f.readline())
        assert record["filled"] is False

    def test_latency_under_5ms(self, logger):
        """AI-F2 gate: each record_outcome call should take < 5ms."""
        logger.register_pending("d-bench", "e-bench", "BTC-EUR", "kraken")

        times = []
        for i in range(100):
            eid = f"e-lat-{i}"
            logger.register_pending(f"d-lat-{i}", eid, "BTC-EUR", "kraken")
            ex = _make_executor_info(executor_id=eid)
            t0 = time.perf_counter()
            logger.record_outcome(eid, ex, time.time())
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)
        logger.flush()

        avg_ms = sum(times) / len(times)
        assert avg_ms < 5.0, f"Average record_outcome latency {avg_ms:.2f}ms exceeds 5ms gate"
