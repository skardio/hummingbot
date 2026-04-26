#!/bin/bash
# T2-O6: Log cleanup — verplaats >7d naar archive/, jsonl bewaren tot 90d
# Install: crontab -e → 30 3 * * * /home/mo/repos/hummingbot/deploy/cleanup_logs.sh
set -e

REPO_DIR="/home/mo/repos/hummingbot"
LOG_DIR="${REPO_DIR}/logs"
ARCHIVE_DIR="${LOG_DIR}/archive"

if [ ! -d "${LOG_DIR}" ]; then
    exit 0
fi

mkdir -p "${ARCHIVE_DIR}"

# Verplaats log bestanden ouder dan 7 dagen naar archive/ (geen compressie)
find "${LOG_DIR}" -maxdepth 1 \( -name "*.log" -o -name "*.log.*" \) -mtime +7 -exec mv {} "${ARCHIVE_DIR}/" \; 2>/dev/null || true

# Verwijder gearchiveerde bestanden ouder dan 30 dagen
find "${ARCHIVE_DIR}" \( -name "*.log" -o -name "*.log.*" \) -mtime +30 -delete 2>/dev/null || true

# Verwijder JSONL bestanden ouder dan 90 dagen
find "${LOG_DIR}" -name "*.jsonl" -mtime +90 -delete 2>/dev/null || true
find "${ARCHIVE_DIR}" -name "*.jsonl" -mtime +90 -delete 2>/dev/null || true

echo "$(date -Iseconds) log-cleanup: done"
