"""
Configuration for Monitoring Module
"""

import glob
import os
from pathlib import Path
from typing import Optional


class MonitoringConfig:
    """Configuration for monitoring system"""

    # Database
    DB_PATH: Optional[str] = None  # Auto-determined if None

    # Collector settings
    COLLECTOR_INTERVAL: int = 10  # seconds

    # Log file to monitor - automatically finds the most recent timestamped log
    @staticmethod
    def get_latest_log_file() -> str:
        """Find the most recent logs_multi_coin_grid_v2*.log file"""
        log_dir = "/home/mo/repos/hummingbot/logs"
        pattern = f"{log_dir}/logs_multi_coin_grid_v2*.log"

        log_files = glob.glob(pattern)
        if not log_files:
            # Fallback to base name if no timestamped files found
            return f"{log_dir}/logs_multi_coin_grid_v2.log"

        # Sort by modification time (most recent first)
        log_files.sort(key=os.path.getmtime, reverse=True)
        return log_files[0]

    LOG_FILE: str = get_latest_log_file.__func__()

    # Telegram Bot - Always use environment variables (set in .env file)
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")

    # Alert thresholds
    PNL_ALERT_THRESHOLD: float = 5.0  # Alert if P&L swing > 5%
    LATENCY_WARNING_MS: float = 1000.0  # Warn if latency > 1 second

    # Dashboard
    DASHBOARD_HOST: str = "127.0.0.1"
    DASHBOARD_PORT: int = 5000

    @classmethod
    def validate(cls) -> bool:
        """Validate configuration"""
        if not Path(cls.LOG_FILE).exists():
            print(f"⚠️  Warning: Log file not found: {cls.LOG_FILE}")

        if not cls.TELEGRAM_BOT_TOKEN:
            print("⚠️  Warning: TELEGRAM_BOT_TOKEN not set - Telegram alerts disabled")

        if not cls.TELEGRAM_CHAT_ID:
            print("⚠️  Warning: TELEGRAM_CHAT_ID not set - Telegram alerts disabled")

        return True
