#!/bin/bash
# T2-O4: Daily database backup with 7-day retention
# Install: crontab -e → 0 3 * * * /home/mo/repos/hummingbot/deploy/backup_dbs.sh
set -e

REPO_DIR="/home/mo/repos/hummingbot"
BACKUP_DIR="${REPO_DIR}/backups/db"
RETENTION_DAYS=90
DATE=$(date +%Y-%m-%d)

mkdir -p "${BACKUP_DIR}"

# Databases to back up (relative to REPO_DIR)
DBS=(
    "data/multi_coin_grid_v2.sqlite"
    "data/multi_coin_grid_v2_usd.sqlite"
    "data/spot_grid_bitget.sqlite"
    "data/futures_grid_bitget.sqlite"
    "data/cooldowns.db"
    "data/cooldowns_eur.db"
    "data/cooldowns_usd.db"
    "data/entry_prices_usd.db"
    "multi_coin_grid_pro/data/monitoring.db"
)

backed_up=0
for db in "${DBS[@]}"; do
    src="${REPO_DIR}/${db}"
    if [ -f "${src}" ]; then
        base=$(basename "${db}" | sed 's/\.[^.]*$//')
        ext="${db##*.}"
        dest="${BACKUP_DIR}/${base}_${DATE}.${ext}"
        # Use sqlite3 .backup for crash-safe copy (WAL-safe)
        if command -v sqlite3 &>/dev/null; then
            sqlite3 "${src}" ".backup '${dest}'"
        else
            cp "${src}" "${dest}"
        fi
        backed_up=$((backed_up + 1))
    fi
done

# Verwijder backups ouder dan 90 dagen
find "${BACKUP_DIR}" \( -name "*.sqlite" -o -name "*.db" \) -mtime +${RETENTION_DAYS} -delete 2>/dev/null || true

echo "$(date -Iseconds) backup: ${backed_up} databases backed up, pruned >${RETENTION_DAYS}d"
