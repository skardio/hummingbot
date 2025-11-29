"""
SQLite Database Setup and Helpers for Bot Monitoring

Creates and manages the monitoring database with 3 tables:
- bot_events: Events and errors
- bot_status: Current bot status snapshots
- trades: Trade history
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MonitoringDatabase:
    """SQLite database for bot monitoring"""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database connection

        Args:
            db_path: Path to SQLite database file. Defaults to data/monitoring.db
        """
        if db_path is None:
            # Default to multi_coin_grid_pro/data/monitoring.db
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "monitoring.db")

        self.db_path = db_path
        self.conn = None
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        """Ensure database directory exists"""
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

    def _init_database(self):
        """Initialize database tables and indexes"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dict-like objects

        cursor = self.conn.cursor()

        # Table 1: bot_events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                event_type TEXT NOT NULL,
                coin TEXT,
                message TEXT NOT NULL,
                data TEXT,  -- JSON string for extra data
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 2: bot_status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                active_coin TEXT,
                pnl REAL DEFAULT 0.0,
                exposure REAL DEFAULT 0.0,
                mode TEXT DEFAULT 'running',  -- running / paused / error_safe_mode
                grid_level INTEGER,
                heartbeat_latency REAL,  -- milliseconds
                connection_status TEXT DEFAULT 'ok',  -- ok / reconnecting / down
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Table 3: trades
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                coin TEXT NOT NULL,
                side TEXT NOT NULL,  -- buy / sell
                price REAL NOT NULL,
                amount REAL NOT NULL,
                pnl REAL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
            ON bot_events(timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type
            ON bot_events(event_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status_timestamp
            ON bot_status(timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp
            ON trades(timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_coin
            ON trades(coin)
        """)

        self.conn.commit()

    def add_event(
        self,
        event_type: str,
        message: str,
        coin: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Add an event to bot_events table

        Args:
            event_type: Type of event (error, stop_loss, trend_switch, etc.)
            message: Event message
            coin: Coin symbol (optional)
            data: Additional data as dict (will be JSON encoded)

        Returns:
            Event ID
        """
        cursor = self.conn.cursor()
        data_json = json.dumps(data) if data else None

        cursor.execute("""
            INSERT INTO bot_events (timestamp, event_type, coin, message, data)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), event_type, coin, message, data_json))

        self.conn.commit()
        return cursor.lastrowid

    def add_status(
        self,
        active_coin: Optional[str] = None,
        pnl: float = 0.0,
        exposure: float = 0.0,
        mode: str = "running",
        grid_level: Optional[int] = None,
        heartbeat_latency: Optional[float] = None,
        connection_status: str = "ok"
    ) -> int:
        """
        Add a status snapshot to bot_status table

        Args:
            active_coin: Currently active coin
            pnl: Current P&L
            exposure: Current exposure
            mode: Bot mode (running/paused/error_safe_mode)
            grid_level: Current grid level
            heartbeat_latency: Latency in milliseconds
            connection_status: Connection status

        Returns:
            Status ID
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO bot_status
            (timestamp, active_coin, pnl, exposure, mode, grid_level,
             heartbeat_latency, connection_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            active_coin,
            pnl,
            exposure,
            mode,
            grid_level,
            heartbeat_latency,
            connection_status
        ))

        self.conn.commit()
        return cursor.lastrowid

    def add_trade(
        self,
        coin: str,
        side: str,
        price: float,
        amount: float,
        pnl: float = 0.0
    ) -> int:
        """
        Add a trade to trades table

        Args:
            coin: Coin symbol
            side: buy or sell
            price: Trade price
            amount: Trade amount
            pnl: P&L for this trade

        Returns:
            Trade ID
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO trades (timestamp, coin, side, price, amount, pnl)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), coin, side, price, amount, pnl))

        self.conn.commit()
        return cursor.lastrowid

    def get_latest_status(self) -> Optional[Dict[str, Any]]:
        """Get the latest bot status"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM bot_status
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def get_recent_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Get recent events"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM bot_events
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_trades_today(self) -> List[Dict[str, Any]]:
        """Get all trades from today"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM trades
            WHERE DATE(timestamp) = DATE('now')
            ORDER BY timestamp DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_pnl_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get P&L history for chart"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timestamp, pnl, active_coin
            FROM bot_status
            WHERE timestamp >= datetime('now', '-' || ? || ' hours')
            ORDER BY timestamp ASC
        """, (hours,))
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
