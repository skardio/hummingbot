"""
Configuration for Monitoring Module
"""

import os
from pathlib import Path
from typing import Optional


class MonitoringConfig:
    """Configuration for monitoring system"""

    # Database
    DB_PATH: Optional[str] = None  # Auto-determined if None

    # Collector settings
    COLLECTOR_INTERVAL: int = 10  # seconds

    # Log file to monitor
    LOG_FILE: str = "/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2.log"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN", "8310424124:AAGc--tOZvhucvyfJnoKeIucm6aD9L9N1Jk")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID", "8586283471")

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
