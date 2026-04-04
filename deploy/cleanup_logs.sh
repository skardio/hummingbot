#!/bin/bash
# T2-O6: Log cleanup — compress >7d, delete >14d
# Install: crontab -e → 30 3 * * * /home/mo/repos/hummingbot/deploy/cleanup_logs.sh
set -e

REPO_DIR="/home/mo/repos/hummingbot"
LOG_DIR="${REPO_DIR}/logs"

if [ ! -d "${LOG_DIR}" ]; then
    exit 0
fi

# Delete JSONL files older than 14 days
find "${LOG_DIR}" -name "*.jsonl" -mtime +14 -delete 2>/dev/null || true

# Compress log files older than 7 days (skip already compressed)
find "${LOG_DIR}" -name "*.log" -mtime +7 ! -name "*.gz" -exec gzip {} \; 2>/dev/null || true

# Delete compressed logs older than 30 days
find "${LOG_DIR}" -name "*.log.gz" -mtime +30 -delete 2>/dev/null || true

echo "$(date -Iseconds) log-cleanup: done"
