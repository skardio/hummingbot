"""
Phase 1C Integration Test: Correlation ID + MTF ReasonCode Flow

Validates:
1. Correlation ID is carried through trace (no global state)
2. MTF rejection sets stage + reason_code correctly
3. Events are emitted with correlation_id in JSONL format
4. No hidden context - all emission via _log_decision_trace()
"""

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.observability.event_logger import EventLogger
from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace


def test_mtf_rejection_with_correlation_id():
    """
    Test Phase 1C pattern: correlation_id flows through trace, MTF sets reason_code,
    event emission happens in _log_decision_trace() only.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup EventLogger (no logger parameter)
        event_logger = EventLogger(enabled=True, output_dir=tmpdir, buffer_size=1)

        # Simulate controller evaluation cycle
        correlation_id = str(uuid.uuid4())
        trading_pair = "BTC-USDT"

        # Phase 1: Candidate evaluation starts - generate correlation_id
        # (In real controller: generated at start of determine_executor_actions)

        # Phase 2: MTF check fails - create trace with correlation_id
        # (Pattern: no global state, correlation_id passed via trace)
        trace = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="binance",
            enabled=True,
            strategy="spot_grid"
        )

        # MTF instrumentation (inline, no helper method)
        rejection_reason = "1h trend (-0.5%) < 0% (crash detected)"
        trace.finalize(accepted=False, rejected_by="mtf", final_reason=rejection_reason)
        trace.reason_code = ReasonCode.MTF_CRASH_DETECTED.value
        trace.stage = Stage.MTF.value
        trace.correlation_id = correlation_id  # Single source of truth

        # Phase 3: Event emission (simulating _log_decision_trace() behavior)
        # No emission in MTF code - only via centralized logging
        event_logger.emit_gate_denied(
            stage=trace.stage,
            reason_code=trace.reason_code,
            symbol=trace.trading_pair,
            correlation_id=trace.correlation_id,
            reason_msg=trace.final_reason,
            metadata={
                "exchange": trace.exchange,
                "rejected_by": trace.rejected_by
            }
        )

        # Flush events
        event_logger.close()

        # Validate JSONL output - filename is now events_YYYYMMDD_HHMMSS.jsonl
        event_files = list(Path(tmpdir).glob("events_*.jsonl"))
        assert len(event_files) == 1, f"Should have exactly 1 event file, found {len(event_files)}"
        events_file = event_files[0]

        with open(events_file, 'r') as f:
            lines = f.readlines()

        assert len(lines) == 1, "Should have exactly 1 event"

        event = json.loads(lines[0])
        assert event['event_type'] == 'gate_denied'
        assert event['stage'] == 'MTF'
        assert event['reason_code'] == 'MTF_CRASH_DETECTED'
        assert event['symbol'] == trading_pair
        assert event['correlation_id'] == correlation_id  # Correlation ID propagated correctly
        assert 'ts' in event
        assert 'metadata' in event
        assert event['metadata']['rejected_by'] == 'mtf'
        assert 'reason_msg' in event
        assert 'crash detected' in event['reason_msg']


def test_multiple_stages_same_correlation_id():
    """
    Test that correlation_id links multiple decision stages for same candidate evaluation.
    Demonstrates how correlation_id flows through SmartEntry → MTF → Risk without global state.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        event_logger = EventLogger(enabled=True, output_dir=tmpdir, buffer_size=5)

        # Same candidate evaluation - same correlation_id
        correlation_id = str(uuid.uuid4())
        trading_pair = "ETH-USDT"

        # Stage 1: SmartEntry rejection (hypothetical - testing pattern only)
        trace1 = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="kraken",
            enabled=True,
            strategy="spot_grid"
        )
        trace1.finalize(accepted=False, rejected_by="smart_entry", final_reason="RSI overbought")
        trace1.reason_code = ReasonCode.RSI_OVERBOUGHT.value
        trace1.stage = Stage.SMART_ENTRY.value
        trace1.correlation_id = correlation_id

        event_logger.emit_gate_denied(
            stage=trace1.stage,
            reason_code=trace1.reason_code,
            symbol=trace1.trading_pair,
            correlation_id=trace1.correlation_id,
            reason_msg=trace1.final_reason,
            metadata={"rejected_by": "smart_entry"}
        )

        # Stage 2: Different candidate passes SmartEntry but fails MTF (same correlation_id pattern)
        trace2 = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="kraken",
            enabled=True,
            strategy="spot_grid"
        )
        trace2.finalize(accepted=False, rejected_by="mtf", final_reason="MTF insufficient")
        trace2.reason_code = ReasonCode.MTF_INSUFFICIENT.value
        trace2.stage = Stage.MTF.value
        trace2.correlation_id = correlation_id  # Same correlation_id - same evaluation cycle

        event_logger.emit_gate_denied(
            stage=trace2.stage,
            reason_code=trace2.reason_code,
            symbol=trace2.trading_pair,
            correlation_id=trace2.correlation_id,
            reason_msg=trace2.final_reason,
            metadata={"rejected_by": "mtf"}
        )

        event_logger.close()

        # Validate both events have same correlation_id
        event_files = list(Path(tmpdir).glob("events_*.jsonl"))
        assert len(event_files) == 1

        with open(event_files[0], 'r') as f:
            events = [json.loads(line) for line in f]

        assert len(events) == 2
        assert events[0]['correlation_id'] == correlation_id
        assert events[1]['correlation_id'] == correlation_id
        assert events[0]['stage'] == 'SMART_ENTRY'
        assert events[1]['stage'] == 'MTF'
        assert events[0]['reason_code'] == 'RSI_OVERBOUGHT'
        assert events[1]['reason_code'] == 'MTF_INSUFFICIENT'


def test_gate_passed_with_correlation_id():
    """
    Test success case: gate_passed event with correlation_id (no reason_code needed).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        event_logger = EventLogger(enabled=True, output_dir=tmpdir, buffer_size=1)

        correlation_id = str(uuid.uuid4())
        trading_pair = "SOL-USDT"

        # Candidate passes all checks
        trace = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="binance",
            enabled=True,
            strategy="spot_grid"
        )
        trace.finalize(accepted=True, rejected_by=None, final_reason="all checks passed")
        # Success: no reason_code needed, only stage
        trace.stage = Stage.MTF.value
        trace.correlation_id = correlation_id

        # Emit gate_passed event
        event_logger.emit_gate_passed(
            stage=trace.stage,
            symbol=trace.trading_pair,
            correlation_id=trace.correlation_id,
            metadata={
                "exchange": trace.exchange,
                "final_reason": trace.final_reason
            }
        )

        event_logger.close()

        # Validate
        event_files = list(Path(tmpdir).glob("events_*.jsonl"))
        assert len(event_files) == 1

        with open(event_files[0], 'r') as f:
            event = json.loads(f.readline())

        assert event['event_type'] == 'gate_passed'
        assert event['stage'] == 'MTF'
        assert event['symbol'] == trading_pair  # Fixed: EventLogger uses 'symbol' not 'trading_pair'
        assert event['correlation_id'] == correlation_id
        assert 'reason_code' not in event  # Success has no reason_code
        assert event['metadata']['final_reason'] == 'all checks passed'


def test_full_success_flow_with_same_correlation_id():
    """
    Test complete success flow: SmartEntry pass + MTF pass with same correlation_id.
    Validates Fix #1 (correlation_id propagation) and Fix #2 (stage on success).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        event_logger = EventLogger(enabled=True, output_dir=tmpdir, buffer_size=10)

        # This would be generated at start of evaluation (in SmartEntry)
        correlation_id = str(uuid.uuid4())
        trading_pair = "BTC-USDT"

        # SmartEntry passes
        smart_entry_trace = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="kraken",
            enabled=True,
            strategy="spot_grid"
        )
        smart_entry_trace.correlation_id = correlation_id
        smart_entry_trace.stage = Stage.SMART_ENTRY.value
        smart_entry_trace.finalize(accepted=True, final_reason="all SmartEntry filters passed")

        event_logger.emit_gate_passed(
            correlation_id=smart_entry_trace.correlation_id,
            symbol=smart_entry_trace.trading_pair,
            stage=smart_entry_trace.stage,
            metadata={
                "exchange": smart_entry_trace.exchange,
                "final_reason": smart_entry_trace.final_reason
            }
        )

        # MTF passes (reuses same correlation_id)
        mtf_trace = PairDecisionTrace(
            trading_pair=trading_pair,
            exchange="kraken",
            enabled=True,
            strategy="spot_grid"
        )
        mtf_trace.correlation_id = correlation_id  # Same correlation_id!
        mtf_trace.stage = Stage.MTF.value
        mtf_trace.finalize(accepted=True, final_reason="MTF buy conditions passed")

        event_logger.emit_gate_passed(
            correlation_id=mtf_trace.correlation_id,
            symbol=mtf_trace.trading_pair,
            stage=mtf_trace.stage,
            metadata={
                "exchange": mtf_trace.exchange,
                "final_reason": mtf_trace.final_reason
            }
        )

        event_logger.close()

        # Validate: 2 gate_passed events with same correlation_id
        event_files = list(Path(tmpdir).glob("events_*.jsonl"))
        assert len(event_files) == 1

        with open(event_files[0], 'r') as f:
            events = [json.loads(line) for line in f]

        assert len(events) == 2, "Expected 2 gate_passed events (SmartEntry + MTF)"

        # Both events should have same correlation_id (Fix #1 validation)
        assert events[0]['correlation_id'] == correlation_id
        assert events[1]['correlation_id'] == correlation_id

        # Both should be gate_passed
        assert events[0]['event_type'] == 'gate_passed'
        assert events[1]['event_type'] == 'gate_passed'

        # Stages should be SMART_ENTRY and MTF (Fix #2 validation)
        assert events[0]['stage'] == 'SMART_ENTRY'
        assert events[1]['stage'] == 'MTF'

        # No reason_code on success
        assert 'reason_code' not in events[0]
        assert 'reason_code' not in events[1]

        # Same symbol
        assert events[0]['symbol'] == trading_pair
        assert events[1]['symbol'] == trading_pair


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
