"""
Unit tests for Monitoring Database
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from multi_coin_grid_pro.monitoring.database import MonitoringDatabase
except ImportError:
    from monitoring.database import MonitoringDatabase


class TestMonitoringDatabase:
    """Test MonitoringDatabase class"""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database path"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            yield Path(f.name)
        Path(f.name).unlink(missing_ok=True)

    @pytest.fixture
    def db(self, temp_db_path):
        """Create database instance"""
        return MonitoringDatabase(db_path=str(temp_db_path))

    def test_database_initialization(self, db):
        """Test database initialization"""
        assert db.db_path is not None
        # Check if tables exist by trying to query
        events = db.get_recent_events(limit=1)
        assert isinstance(events, list)

    def test_insert_event(self, db):
        """Test inserting event"""
        db.add_event(
            event_type="stop_loss",
            coin="XRP-EUR",
            message="Stop loss triggered"
        )

        events = db.get_recent_events(limit=1)
        assert len(events) > 0
        assert events[0]["event_type"] == "stop_loss"

    def test_insert_status(self, db):
        """Test inserting status"""
        db.add_status(
            active_coin="XRP-EUR",
            mode="running"
        )

        status = db.get_latest_status()
        assert status is not None
        assert status["active_coin"] == "XRP-EUR"

    def test_get_recent_events(self, db):
        """Test getting recent events"""
        # Insert multiple events
        for i in range(5):
            db.add_event(
                event_type="test",
                coin=f"COIN{i}-EUR",
                message=f"Test event {i}"
            )

        events = db.get_recent_events(limit=3)
        assert len(events) <= 3
        assert all("event_type" in e for e in events)

    def test_get_latest_status(self, db):
        """Test getting latest status"""
        # Insert multiple statuses
        for i in range(5):
            db.add_status(
                active_coin=f"COIN{i}-EUR",
                mode="running"
            )

        status = db.get_latest_status()
        assert status is not None
        assert "active_coin" in status
        assert status["active_coin"] == "COIN4-EUR"  # Last one inserted

    def test_get_events_by_type(self, db):
        """Test getting events by type"""
        db.add_event(event_type="stop_loss", coin="XRP-EUR", message="Stop loss")
        db.add_event(event_type="error", coin="ADA-EUR", message="Error")
        db.add_event(event_type="stop_loss", coin="SOL-EUR", message="Stop loss")

        # Get all events and filter by type
        all_events = db.get_recent_events(limit=10)
        stop_loss_events = [e for e in all_events if e["event_type"] == "stop_loss"]
        assert len(stop_loss_events) >= 2
        assert all(e["event_type"] == "stop_loss" for e in stop_loss_events)
