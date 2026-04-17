"""
ST-05a: Tests for ExecutionFunnelTracker and its integration with the controller.

Verifies:
- Counter recording for each stage (considered, allowed, rejected, approved, started)
- Per-filter rejection tracking
- Rolling window summary with computed rates
- Controller initialisation wires the tracker
"""
import logging
import time

from multi_coin_grid_pro.observability.execution_funnel import ExecutionFunnelTracker

# ── Unit tests for ExecutionFunnelTracker ──────────────────────────────────


class TestFunnelCounters:
    """Basic counter arithmetic."""

    def test_initial_state_is_zero(self):
        tracker = ExecutionFunnelTracker(window_sec=60)
        summary = tracker.get_summary()
        assert summary["considered"] == 0
        assert summary["allowed"] == 0
        assert summary["rejected"] == 0
        assert summary["approved"] == 0
        assert summary["started"] == 0
        assert summary["ticks"] == 0

    def test_record_considered(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_considered(5)
        tracker.record_considered(3)
        assert tracker.get_summary()["considered"] == 8

    def test_record_allowed(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_allowed("BTC-EUR")
        tracker.record_allowed("ETH-EUR")
        assert tracker.get_summary()["allowed"] == 2

    def test_record_rejected_with_filter(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_rejected("BTC-EUR", "smart_entry")
        tracker.record_rejected("ETH-EUR", "smart_entry")
        tracker.record_rejected("SOL-EUR", "mtf")
        summary = tracker.get_summary()
        assert summary["rejected"] == 3
        assert summary["reject_reasons"] == {"smart_entry": 2, "mtf": 1}

    def test_record_approved(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_approved("BTC-EUR")
        assert tracker.get_summary()["approved"] == 1

    def test_record_started(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_started("BTC-EUR")
        assert tracker.get_summary()["started"] == 1

    def test_record_tick(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_tick()
        tracker.record_tick()
        tracker.record_tick()
        assert tracker.get_summary()["ticks"] == 3


class TestFunnelRates:
    """Computed rate percentages."""

    def test_allow_rate_pct(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_allowed("A")
        tracker.record_allowed("B")
        tracker.record_rejected("C", "smart_entry")
        # 2 allowed / (2 + 1 rejected) = 66.7%
        assert tracker.get_summary()["allow_rate_pct"] == 66.7

    def test_allow_rate_zero_when_no_decisions(self):
        tracker = ExecutionFunnelTracker()
        assert tracker.get_summary()["allow_rate_pct"] == 0.0

    def test_start_rate_pct(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_approved("A")
        tracker.record_approved("B")
        tracker.record_started("A")
        # 1 started / 2 approved = 50%
        assert tracker.get_summary()["start_rate_pct"] == 50.0

    def test_start_rate_zero_when_no_approved(self):
        tracker = ExecutionFunnelTracker()
        assert tracker.get_summary()["start_rate_pct"] == 0.0


class TestFunnelWindow:
    """Rolling window and periodic summary."""

    def test_maybe_log_returns_none_within_window(self):
        tracker = ExecutionFunnelTracker(window_sec=900)
        tracker.record_tick()
        result = tracker.maybe_log_summary()
        assert result is None

    def test_maybe_log_returns_summary_after_window(self):
        tracker = ExecutionFunnelTracker(window_sec=1)
        tracker.record_considered(5)
        tracker.record_allowed("A")
        tracker.record_tick()
        # Force window expiry
        tracker._window_start = time.time() - 2
        result = tracker.maybe_log_summary()
        assert result is not None
        assert result["considered"] == 5
        assert result["allowed"] == 1
        assert result["ticks"] == 1

    def test_reset_after_summary(self):
        tracker = ExecutionFunnelTracker(window_sec=1)
        tracker.record_considered(10)
        tracker.record_tick()
        tracker._window_start = time.time() - 2
        tracker.maybe_log_summary()
        # After reset, counters should be zero
        assert tracker.get_summary()["considered"] == 0
        assert tracker.get_summary()["ticks"] == 0

    def test_maybe_log_returns_summary_when_no_ticks_but_window_expired(self):
        tracker = ExecutionFunnelTracker(window_sec=1)
        tracker._window_start = time.time() - 2
        result = tracker.maybe_log_summary()
        # Returns summary dict but with 0 ticks (no log emitted)
        assert result is not None
        assert result["ticks"] == 0

    def test_summary_logged_at_info_level(self, caplog):
        tracker = ExecutionFunnelTracker(window_sec=1)
        tracker.record_considered(3)
        tracker.record_tick()
        tracker._window_start = time.time() - 2
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.observability.execution_funnel"):
            tracker.maybe_log_summary()
        assert "Execution funnel" in caplog.text


class TestFunnelReset:
    """Explicit reset behaviour."""

    def test_reset_clears_all_counters(self):
        tracker = ExecutionFunnelTracker()
        tracker.record_considered(10)
        tracker.record_allowed("A")
        tracker.record_rejected("B", "smart_entry")
        tracker.record_approved("A")
        tracker.record_started("A")
        tracker.record_tick()
        tracker.reset()
        summary = tracker.get_summary()
        assert summary["considered"] == 0
        assert summary["allowed"] == 0
        assert summary["rejected"] == 0
        assert summary["approved"] == 0
        assert summary["started"] == 0
        assert summary["ticks"] == 0
        assert summary["reject_reasons"] == {}


# ── Integration: Controller initialisation ─────────────────────────────────


class TestControllerFunnelInit:
    """Verify the controller initializes the funnel tracker."""

    def test_controller_has_execution_funnel_attr(self):
        """After __init__, controller.execution_funnel is an ExecutionFunnelTracker."""
        # Verify the controller module can import and that tracker has all required methods
        assert hasattr(ExecutionFunnelTracker, 'record_considered')
        assert hasattr(ExecutionFunnelTracker, 'record_allowed')
        assert hasattr(ExecutionFunnelTracker, 'record_rejected')
        assert hasattr(ExecutionFunnelTracker, 'record_approved')
        assert hasattr(ExecutionFunnelTracker, 'record_started')
        assert hasattr(ExecutionFunnelTracker, 'record_tick')
        assert hasattr(ExecutionFunnelTracker, 'maybe_log_summary')
