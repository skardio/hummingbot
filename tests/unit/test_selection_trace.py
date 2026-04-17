"""
ST-06a: Tests for _log_selection_trace() — selection funnel observability.

Verifies that the structured funnel summary logs correctly and
handles edge cases without raising.
"""
import logging
from unittest.mock import MagicMock


def _make_controller():
    """Build a minimal mock controller with the real _log_selection_trace method."""
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    ctrl = MagicMock(spec=MultiCoinGridController)
    ctrl.monitored_coins = ["BTC-EUR", "ETH-EUR", "SOL-EUR", "DOGE-EUR"]
    ctrl.active_coins = {"BTC-EUR": MagicMock(), "ETH-EUR": MagicMock()}
    ctrl.trend_calculator = MagicMock()
    ctrl.trend_calculator._debug_info = {
        "sufficient": 18,
        "total": 25,
        "all_count": 10,
        "depth_filtered": 5,
    }
    ctrl.config = MagicMock()
    ctrl.config.connector_name = "kraken"

    # Wire the real logger
    ctrl.logger.return_value = logging.getLogger("test_selection_trace")

    # Wire decision_logger
    mock_dl = MagicMock()
    mock_snap = MagicMock()
    mock_dl.create_snapshot.return_value = mock_snap
    ctrl.decision_logger = mock_dl

    # Bind the real method
    ctrl._log_selection_trace = MultiCoinGridController._log_selection_trace.__get__(
        ctrl, MultiCoinGridController
    )
    return ctrl, mock_dl, mock_snap


class TestSelectionTraceLogging:
    """ST-06a: Selection funnel summary tests."""

    def test_logs_funnel_with_best_coin(self, caplog):
        """Funnel log includes all stages and the selected coin."""
        ctrl, mock_dl, snap = _make_controller()
        rejections = [
            {"symbol": "SOL-EUR", "filter": "smart_entry", "passed": False},
            {"symbol": "DOGE-EUR", "filter": "smart_entry", "passed": False},
        ]

        with caplog.at_level(logging.INFO):
            ctrl._log_selection_trace(
                top_coins=["BTC-EUR", "SOL-EUR", "DOGE-EUR"],
                best_coin="BTC-EUR",
                candidate_rejections=rejections,
                rejection_reason=None,
            )

        assert "Selection funnel" in caplog.text
        assert "'best_coin': 'BTC-EUR'" in caplog.text
        assert "'smart_entry': 2" in caplog.text

    def test_logs_funnel_no_selection(self, caplog):
        """Funnel correctly records no selection."""
        ctrl, mock_dl, snap = _make_controller()

        with caplog.at_level(logging.INFO):
            ctrl._log_selection_trace(
                top_coins=[],
                best_coin=None,
                candidate_rejections=[],
                rejection_reason="All top coins rejected by SmartEntry filters",
            )

        assert "'best_coin': None" in caplog.text
        assert "All top coins rejected" in caplog.text

    def test_decision_logger_snapshot_created(self):
        """DecisionLogger receives a selection_funnel snapshot."""
        ctrl, mock_dl, snap = _make_controller()

        ctrl._log_selection_trace(
            top_coins=["BTC-EUR"],
            best_coin="BTC-EUR",
            candidate_rejections=[],
            rejection_reason=None,
        )

        mock_dl.create_snapshot.assert_called_once_with(
            "selection_funnel", "BTC-EUR", "kraken"
        )
        assert snap.outcome == "selected"
        assert snap.reason_msg is None
        mock_dl.log.assert_called_once_with(snap)

    def test_decision_logger_no_selection_snapshot(self):
        """Snapshot records 'no_selection' when no coin is picked."""
        ctrl, mock_dl, snap = _make_controller()

        ctrl._log_selection_trace(
            top_coins=[],
            best_coin=None,
            candidate_rejections=[],
            rejection_reason="All slots full",
        )

        mock_dl.create_snapshot.assert_called_once_with(
            "selection_funnel", "NONE", "kraken"
        )
        assert snap.outcome == "no_selection"
        assert snap.reason_msg == "All slots full"

    def test_filter_checks_contains_funnel_dict(self):
        """The snapshot's filter_checks field holds the full funnel dict."""
        ctrl, mock_dl, snap = _make_controller()

        ctrl._log_selection_trace(
            top_coins=["BTC-EUR", "SOL-EUR"],
            best_coin="BTC-EUR",
            candidate_rejections=[
                {"symbol": "SOL-EUR", "filter": "smart_entry", "passed": False},
            ],
            rejection_reason=None,
        )

        funnel = snap.filter_checks
        assert funnel["monitored_pool"] == 4
        assert funnel["active_grids"] == 2
        assert funnel["sufficient_data"] == 18
        assert funnel["qualifying_coins"] == 10
        assert funnel["depth_filtered"] == 5
        assert funnel["top_coins"] == 2
        assert funnel["rejections"] == {"smart_entry": 1}

    def test_multiple_rejection_types_counted(self):
        """Different rejection filters are counted separately."""
        ctrl, mock_dl, snap = _make_controller()
        rejections = [
            {"symbol": "A", "filter": "smart_entry", "passed": False},
            {"symbol": "B", "filter": "blacklist", "passed": False},
            {"symbol": "C", "filter": "smart_entry", "passed": False},
            {"symbol": "D", "filter": "mtf_conditions", "passed": False},
            {"symbol": "E", "filter": "active", "passed": False},
        ]

        ctrl._log_selection_trace(
            top_coins=["X"],
            best_coin="X",
            candidate_rejections=rejections,
            rejection_reason=None,
        )

        funnel = snap.filter_checks
        assert funnel["rejections"] == {
            "smart_entry": 2,
            "blacklist": 1,
            "mtf_conditions": 1,
            "active": 1,
        }

    def test_no_crash_without_debug_info(self, caplog):
        """Handles missing _debug_info gracefully (e.g. cold start)."""
        ctrl, mock_dl, snap = _make_controller()
        del ctrl.trend_calculator._debug_info

        with caplog.at_level(logging.INFO):
            ctrl._log_selection_trace(
                top_coins=[],
                best_coin=None,
                candidate_rejections=[],
                rejection_reason=None,
            )

        # Should still log, with zeros for debug info fields
        assert "Selection funnel" in caplog.text
        assert "'sufficient_data': 0" in caplog.text

    def test_no_crash_without_decision_logger(self, caplog):
        """If decision_logger is None, still logs to logger without error."""
        ctrl, _, _ = _make_controller()
        ctrl.decision_logger = None

        with caplog.at_level(logging.INFO):
            ctrl._log_selection_trace(
                top_coins=["BTC-EUR"],
                best_coin="BTC-EUR",
                candidate_rejections=[],
                rejection_reason=None,
            )

        assert "Selection funnel" in caplog.text
