"""
Tests for AI-F1: DecisionLogger + snapshot builders.

Covers:
- DecisionSnapshot creation and serialization
- DecisionLogger buffering, flush, rotation, close
- Logging failure never raises
- Snapshot builder helpers
- < 5ms per log call (latency gate)
"""

import json
import os
import shutil
import tempfile
import time

import pytest

from multi_coin_grid_pro.observability.decision_logger import SCHEMA_VERSION, DecisionLogger, DecisionSnapshot
from multi_coin_grid_pro.observability.snapshot_builders import (
    build_bot_state,
    build_filter_checks_from_trace,
    build_market_features,
    build_risk_context,
    build_rotation_context,
    build_strategy_state,
)

# ─── fixtures ────────────────────────────────────────────────────


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def logger(tmp_dir):
    return DecisionLogger(enabled=True, output_dir=tmp_dir, buffer_size=5)


@pytest.fixture
def disabled_logger(tmp_dir):
    return DecisionLogger(enabled=False, output_dir=tmp_dir)


# ─── DecisionSnapshot tests ─────────────────────────────────────

class TestDecisionSnapshot:

    def test_create_snapshot_has_uuid(self):
        snap = DecisionSnapshot(
            decision_id="abc-123",
            timestamp=time.time(),
            decision_type="entry",
            symbol="BTC-EUR",
            exchange="kraken",
        )
        assert snap.decision_id == "abc-123"
        assert snap.schema_version == SCHEMA_VERSION

    def test_to_dict_roundtrip(self):
        snap = DecisionSnapshot(
            decision_id="test-id",
            timestamp=1234567890.0,
            decision_type="rotation",
            symbol="ETH-EUR",
            exchange="bitget",
            outcome="accepted",
            market={"trend_1h": 2.5},
            rotation={"from_coin": "BTC-EUR", "to_coin": "ETH-EUR"},
        )
        d = snap.to_dict()
        assert d["decision_id"] == "test-id"
        assert d["market"]["trend_1h"] == 2.5
        assert d["rotation"]["from_coin"] == "BTC-EUR"

    def test_to_dict_is_json_serializable(self):
        snap = DecisionSnapshot(
            decision_id="ser-test",
            timestamp=time.time(),
            decision_type="entry",
            symbol="DOT-EUR",
            exchange="kraken",
        )
        result = json.dumps(snap.to_dict())
        assert '"decision_id": "ser-test"' in result


# ─── DecisionLogger tests ───────────────────────────────────────

class TestDecisionLogger:

    def test_log_and_flush(self, logger, tmp_dir):
        snap = logger.create_snapshot("entry", "BTC-EUR", "kraken")
        snap.outcome = "accepted"
        snap.market = {"trend_1h": 3.0}
        logger.log(snap)
        logger.flush()

        files = list(os.listdir(tmp_dir))
        assert len(files) == 1
        assert files[0].startswith("decisions_")
        assert files[0].endswith(".jsonl")

        with open(os.path.join(tmp_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["decision_type"] == "entry"
        assert record["symbol"] == "BTC-EUR"
        assert record["market"]["trend_1h"] == 3.0
        assert "decision_id" in record

    def test_auto_flush_on_buffer_full(self, logger, tmp_dir):
        """Buffer size is 5 — after 5 logs, should auto-flush."""
        for i in range(5):
            snap = logger.create_snapshot("entry", f"COIN{i}-EUR", "kraken")
            snap.outcome = "rejected"
            logger.log(snap)

        # Buffer should have been flushed
        files = list(os.listdir(tmp_dir))
        assert len(files) == 1
        with open(os.path.join(tmp_dir, files[0])) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_close_flushes_remaining(self, logger, tmp_dir):
        snap = logger.create_snapshot("entry", "XRP-EUR", "kraken")
        snap.outcome = "accepted"
        logger.log(snap)
        # Not yet flushed (buffer_size=5)
        assert len(os.listdir(tmp_dir)) == 0

        logger.close()

        files = list(os.listdir(tmp_dir))
        assert len(files) == 1
        with open(os.path.join(tmp_dir, files[0])) as f:
            assert len(f.readlines()) == 1

    def test_disabled_logger_does_nothing(self, disabled_logger, tmp_dir):
        snap = DecisionSnapshot(
            decision_id="noop",
            timestamp=time.time(),
            decision_type="entry",
            symbol="X",
            exchange="test",
        )
        disabled_logger.log(snap)
        disabled_logger.flush()
        assert len(os.listdir(tmp_dir)) == 0

    def test_stats(self, logger):
        for _ in range(3):
            snap = logger.create_snapshot("entry", "A-EUR", "kraken")
            logger.log(snap)
        logger.flush()
        s = logger.stats
        assert s["total_logged"] == 3
        assert s["total_errors"] == 0
        assert s["buffer_size"] == 0

    def test_decimal_serialization(self, logger, tmp_dir):
        from decimal import Decimal
        snap = logger.create_snapshot("entry", "BTC-EUR", "kraken")
        snap.market = {"price": Decimal("12345.678")}
        logger.log(snap)
        logger.flush()

        files = list(os.listdir(tmp_dir))
        with open(os.path.join(tmp_dir, files[0])) as f:
            record = json.loads(f.readline())
        assert record["market"]["price"] == 12345.678

    def test_rotation_retention(self, tmp_dir):
        """Test that rotate() deletes old files."""
        lgr = DecisionLogger(enabled=True, output_dir=tmp_dir, retention_days=0)
        # Create a fake old file
        old_file = os.path.join(tmp_dir, "decisions_2020-01-01.jsonl")
        with open(old_file, "w") as f:
            f.write("{}\n")
        # Set mtime to the past
        os.utime(old_file, (0, 0))
        lgr.rotate()
        assert not os.path.exists(old_file)

    def test_log_never_raises(self, tmp_dir):
        """Even if output dir is invalid, log() must not raise."""
        lgr = DecisionLogger(enabled=True, output_dir="/dev/null/impossible", buffer_size=1)
        # enabled should have been set to False by failed init
        snap = DecisionSnapshot(
            decision_id="crash-test",
            timestamp=time.time(),
            decision_type="entry",
            symbol="X",
            exchange="test",
        )
        # This MUST NOT raise
        lgr.log(snap)
        lgr.flush()
        lgr.close()

    def test_latency_under_5ms(self, logger):
        """AI-F1 gate: each log call should take < 5ms."""
        snap = logger.create_snapshot("entry", "BTC-EUR", "kraken")
        snap.market = {"trend_1h": 1.5, "rsi": 55.0, "atr_pct": 2.3}
        snap.strategy = {"active_coins": ["BTC-EUR"], "slots_used": 1, "max_slots": 3}
        snap.risk = {"daily_loss_pct": 0.5}

        times = []
        for _ in range(100):
            s = logger.create_snapshot("entry", "BTC-EUR", "kraken")
            s.market = snap.market
            s.strategy = snap.strategy
            s.risk = snap.risk
            t0 = time.perf_counter()
            logger.log(s)
            elapsed = (time.perf_counter() - t0) * 1000  # ms
            times.append(elapsed)
        logger.flush()

        avg_ms = sum(times) / len(times)
        assert avg_ms < 5.0, f"Average log latency {avg_ms:.2f}ms exceeds 5ms gate"


# ─── Snapshot builder tests ──────────────────────────────────────

class TestSnapshotBuilders:

    def test_build_market_features_no_data(self):
        result = build_market_features("BTC-EUR", None)
        assert result == {"symbol": "BTC-EUR"}

    def test_build_strategy_state(self):
        class FakeConfig:
            trend_min_change_pct = 0.5
            use_smart_entry_filter = True
            use_multi_timeframe = True

        result = build_strategy_state(
            active_coins={"BTC-EUR": "id1", "ETH-EUR": "id2"},
            max_slots=3,
            monitored_coins=["BTC-EUR", "ETH-EUR", "SOL-EUR"],
            config=FakeConfig(),
        )
        assert result["slots_used"] == 2
        assert result["max_slots"] == 3
        assert len(result["active_coins"]) == 2

    def test_build_bot_state(self):
        result = build_bot_state(
            bot_start_time=time.time() - 3600,
            circuit_breaker_active=False,
            api_error_paused=False,
            paper_trading=True,
        )
        assert result["uptime_sec"] >= 3599  # Allow small delta
        assert result["paper_trading"] is True
        assert result["circuit_breaker_active"] is False

    def test_build_risk_context_empty(self):
        result = build_risk_context(None, None)
        assert result == {}

    def test_build_rotation_context(self):
        result = build_rotation_context(
            from_coin="BTC-EUR",
            to_coin="ETH-EUR",
            from_trend_pct=1.5,
            to_trend_pct=4.2,
            hold_time_sec=600.0,
            switch_cost=0.35,
        )
        assert result["from_coin"] == "BTC-EUR"
        assert result["to_coin"] == "ETH-EUR"
        assert abs(result["trend_difference_pct"] - 2.7) < 0.01
        assert result["hold_time_sec"] == 600.0

    def test_build_filter_checks_from_trace_none(self):
        assert build_filter_checks_from_trace(None) == []

    def test_build_filter_checks_from_real_trace(self):
        from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace
        trace = PairDecisionTrace(
            trading_pair="BTC-EUR", exchange="kraken", enabled=True
        )
        trace.add_check("rsi", value=65.0, threshold=72.0, passed=True, operator="<=")
        trace.add_check("atr_min", value=0.3, threshold=1.0, passed=False, operator=">=")

        result = build_filter_checks_from_trace(trace)
        assert len(result) == 2
        assert result[0]["filter"] == "rsi"
        assert result[0]["passed"] is True
        assert result[1]["filter"] == "atr_min"
        assert result[1]["passed"] is False
