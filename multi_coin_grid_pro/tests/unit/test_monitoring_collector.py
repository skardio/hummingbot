"""
Unit tests for Monitoring Data Collector
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from multi_coin_grid_pro.monitoring.collector import DataCollector
except ImportError:
    from monitoring.collector import DataCollector


class TestDataCollector:
    """Test DataCollector class"""

    @pytest.fixture
    def temp_log_file(self):
        """Create temporary log file"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
            f.write("2024-01-01 10:00:00 - INFO - Bot started\n")
            f.write("2024-01-01 10:01:00 - INFO - Selected coin: XRP-EUR\n")
            f.flush()
            yield Path(f.name)
        Path(f.name).unlink(missing_ok=True)

    @pytest.fixture
    def mock_db(self):
        """Create mock database"""
        db = MagicMock()
        db.insert_event = Mock()
        db.insert_status = Mock()
        return db

    @pytest.fixture
    def collector(self, mock_db, temp_log_file):
        """Create collector instance"""
        return DataCollector(db=mock_db, log_file=str(temp_log_file))

    def test_read_new_log_lines(self, collector, temp_log_file):
        """Test reading new log lines"""
        # Write new line to log file
        with open(temp_log_file, 'a') as f:
            f.write("2024-01-01 10:02:00 - INFO - New line\n")

        lines = collector.read_new_log_lines()

        assert len(lines) > 0
        assert any("New line" in line for line in lines)

    def test_parse_log_line_stop_loss(self, collector):
        """Test parsing stop-loss event"""
        line = "2024-01-01 10:00:00 - CRITICAL - STOP LOSS TRIGGERED for XRP-EUR"
        event = collector.parse_log_line(line)

        assert event is not None
        assert event["event_type"] == "stop_loss"
        assert "XRP-EUR" in event.get("message", "")

    def test_parse_log_line_trend_switch(self, collector):
        """Test parsing trend switch event"""
        line = "2024-01-01 10:00:00 - INFO - Selected coin: ADA-EUR"
        event = collector.parse_log_line(line)

        assert event is not None
        assert event["event_type"] == "trend_switch"
        assert event.get("coin") == "ADA-EUR"

    def test_parse_log_line_executor_created(self, collector):
        """Test parsing executor created event"""
        line = "2024-01-01 10:00:00 - INFO - Creating grid executor for XRP-EUR"
        event = collector.parse_log_line(line)

        assert event is not None
        assert event["event_type"] == "executor_created"

    def test_parse_log_line_error(self, collector):
        """Test parsing error event"""
        line = "2024-01-01 10:00:00 - ERROR - Something went wrong"
        event = collector.parse_log_line(line)

        assert event is not None
        assert event["event_type"] == "error"

    def test_parse_log_line_no_event(self, collector):
        """Test parsing line with no event"""
        line = "2024-01-01 10:00:00 - INFO - Normal log message"
        event = collector.parse_log_line(line)

        assert event is None

    def test_collect_and_store(self, collector, mock_db, temp_log_file):
        """Test collecting and storing events from log file"""
        # Write events to log file
        with open(temp_log_file, 'a') as f:
            f.write("2024-01-01 10:02:00 - CRITICAL - STOP LOSS TRIGGERED for XRP-EUR\n")
            f.write("2024-01-01 10:03:00 - INFO - Selected coin: ADA-EUR\n")

        collector.collect_and_store()

        # Should have added events
        assert mock_db.add_event.called
