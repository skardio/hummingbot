"""
Log Archiver Utility

Moves old log files belonging to a specific bot into the archive directory
at the start of each new run. Only archives logs matching the bot's own
prefixes — other bots' logs are left untouched.

Files that were modified within the last `min_age_seconds` (default: 120 s)
are skipped — this protects the current run's log file, which hummingbot
opens before calling the strategy's __init__.

Usage:
    from multi_coin_grid_pro.utils.log_archiver import archive_bot_logs

    archive_bot_logs("kraken_eur")   # in Kraken EUR __init__
    archive_bot_logs("kraken_usd")   # in Kraken USD __init__
    archive_bot_logs("bitget")       # in Bitget __init__
    archive_bot_logs("okx")          # in OKX __init__
"""

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Root of the hummingbot repo (two levels up from this file)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOGS_DIR = _REPO_ROOT / "logs"
_ARCHIVE_DIR = _LOGS_DIR / "archive"

# Minimum age (seconds) a log file must have before it is archived.
# The current run's log file is created seconds before __init__ runs,
# so 120 s is a safe margin.
_MIN_AGE_SECONDS = 120

# Log file glob patterns per bot.
# Matches both the main log and all rotated backups (.log.1, .log.2, …).
_BOT_PATTERNS: dict[str, list[str]] = {
    "kraken_eur": [
        "logs_multi_coin_grid_v2_[0-9]*.log*",
        "kraken_multi_coin_grid_report_*.log",
    ],
    "kraken_usd": [
        "logs_multi_coin_grid_v2_usd_[0-9]*.log*",
        "kraken_multi_coin_grid_usd_report_*.log",
    ],
    "bitget": [
        "logs_spot_grid_bitget_[0-9]*.log*",
        "bitget_multi_coin_grid_report_*.log",
    ],
    "okx": [
        "logs_spot_grid_okx_[0-9]*.log*",
        "okx_multi_coin_grid_report_*.log",
    ],
}


def archive_bot_logs(
    bot_name: str,
    logs_dir: Path = _LOGS_DIR,
    archive_dir: Path = _ARCHIVE_DIR,
    min_age_seconds: int = _MIN_AGE_SECONDS,
) -> int:
    """
    Move old log files for *bot_name* from *logs_dir* to *archive_dir*.

    Only files older than *min_age_seconds* are moved, so the current
    run's log file (freshly created by hummingbot) is never touched.

    Files are moved into a timestamped sub-folder inside archive_dir so
    that each run gets its own folder and nothing is ever overwritten.

    Args:
        bot_name:        One of "kraken_eur", "kraken_usd", "bitget", "okx".
        logs_dir:        Directory that contains the live log files.
        archive_dir:     Destination directory for archived logs.
        min_age_seconds: Minimum file age in seconds before archiving.

    Returns:
        Number of files moved.
    """
    if bot_name not in _BOT_PATTERNS:
        raise ValueError(
            f"Unknown bot_name '{bot_name}'. "
            f"Valid options: {list(_BOT_PATTERNS)}"
        )

    patterns = _BOT_PATTERNS[bot_name]
    now = time.time()

    # Collect matching files that are old enough to archive
    files_to_move: list[Path] = []
    for pattern in patterns:
        for f in sorted(logs_dir.glob(pattern)):
            age = now - f.stat().st_mtime
            if age >= min_age_seconds:
                files_to_move.append(f)
            else:
                logger.debug(
                    "[log_archiver] Skipping '%s' (age %.0fs < %ds — current run).",
                    f.name, age, min_age_seconds,
                )

    if not files_to_move:
        logger.info("[log_archiver] No old logs to archive for bot '%s'.", bot_name)
        return 0

    # Create timestamped subfolder: archive/<bot_name>/<YYYY-MM-DD_HH-MM-SS>/
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest_dir = archive_dir / bot_name / ts
    dest_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for src in files_to_move:
        dest = dest_dir / src.name
        try:
            shutil.move(str(src), str(dest))
            moved += 1
        except Exception as exc:
            logger.warning(
                "[log_archiver] Could not move '%s' → '%s': %s",
                src, dest, exc,
            )

    logger.info(
        "[log_archiver] Archived %d log file(s) for bot '%s' → %s",
        moved, bot_name, dest_dir,
    )
    return moved
