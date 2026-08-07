from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    run_day: str
    run_time: str
    db_path: Path
    log_file: Path
    bot_state_path: Path
    start_year: int = 2012

    @property
    def end_year(self) -> int:
        return datetime.now().year


def _project_path(value: str, default: str) -> Path:
    raw = value or default
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(env_file: str | Path | None = None) -> Config:
    env_path = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    return Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        run_day=os.getenv("RUN_DAY", "friday").strip().lower(),
        run_time=os.getenv("RUN_TIME", "10:00").strip(),
        db_path=_project_path(os.getenv("DB_PATH", ""), "data/euro.sqlite"),
        log_file=_project_path(os.getenv("LOG_FILE", ""), "logs/euro.log"),
        bot_state_path=_project_path(os.getenv("BOT_STATE_PATH", ""), "data/telegram_offset.txt"),
    )
