#!/usr/bin/env python3
"""
Cleanup old MarketData records to save space
Reads retention days from conf_client.yml or uses default

Usage:
    python3 cleanup_old_market_data.py                           # Auto-detect all
    python3 cleanup_old_market_data.py --execute                 # Actually delete
    python3 cleanup_old_market_data.py 14 --execute              # Keep 14 days
    python3 cleanup_old_market_data.py 30 --execute data/my_bot.sqlite
"""


def find_database():
    """Auto-detect most recent database"""
    db_pattern = 'data/*.sqlite'
    dbs = glob.glob(db_pattern)
    if not dbs:
        return None
    return max(dbs, key=os.path.getmtime)


def get_retention_days_from_config():
    """Get default retention days (Hummingbot doesn't have this setting built-in)"""
    # Default: 30 days retention
    # Override via command line: python cleanup_old_market_data.py 14 --execute
    return 30


def cleanup_old_data(days_to_keep=None, dry_run=True, db_path=None):
    """
    Delete MarketData older than specified days

    Args:
        days_to_keep: Keep data from last N days (None = read from config)
        dry_run: If True, only show what would be deleted
        db_path: Path to database (auto-detect if None)
    """
    # Get retention from config if not specified
    if days_to_keep is None:
        days_to_keep = get_retention_days_from_config()

    # Get DB path
    if not db_path:
        db_path = find_database()

    if not db_path or not os.path.exists(db_path):
        print(f"\n⚠️  Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff_timestamp = (datetime.now() - timedelta(days=days_to_keep)).timestamp() * 1000
    cutoff_dt = datetime.fromtimestamp(cutoff_timestamp / 1000)

    print("=" * 70)
    print("🗑️  MARKET DATA CLEANUP")
    print("=" * 70)
    print(f"\n  Database: {db_path}")
    print(f"  Keep data from: {cutoff_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Delete data older than: {days_to_keep} days")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE DELETE'}")

    # Check what would be deleted
    cursor.execute("""
        SELECT COUNT(*) FROM MarketData
        WHERE timestamp < ?
    """, (cutoff_timestamp,))
    delete_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM MarketData")
    total_count = cursor.fetchone()[0]

    print("\n📊 Statistics:")
    print(f"  Total records: {total_count:,}")
    print(f"  Records to delete: {delete_count:,}")
    print(f"  Records to keep: {(total_count - delete_count):,}")
    print(f"  Percentage to delete: {(delete_count / total_count * 100) if total_count > 0 else 0:.1f}%")

    if delete_count == 0:
        print("\n✅ Nothing to delete!")
        return

    # Get size estimate
    cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    current_size = cursor.fetchone()[0]
    estimated_savings = current_size * (delete_count / total_count) if total_count > 0 else 0

    print(f"  Current DB size: {current_size / 1024 / 1024:.2f} MB")
    print(f"  Estimated savings: {estimated_savings / 1024 / 1024:.2f} MB")

    if dry_run:
        print("\n⚠️  DRY RUN - No data will be deleted")
        print("   Run with --execute to actually delete")
        return

    # Confirm
    print("\n🚨 WARNING: This will permanently delete data!")
    confirm = input("   Type 'DELETE' to confirm: ")

    if confirm != 'DELETE':
        print("   Cancelled.")
        return

    # Delete
    print("\n🗑️  Deleting old records...")
    cursor.execute("DELETE FROM MarketData WHERE timestamp < ?", (cutoff_timestamp,))
    deleted = cursor.rowcount
    conn.commit()

    print(f"  ✓ Deleted {deleted:,} records")

    # Vacuum to reclaim space
    print("\n♻️  Vacuuming database to reclaim space...")
    cursor.execute("VACUUM")

    # Check new size
    cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    new_size = cursor.fetchone()[0]
    actual_savings = current_size - new_size

    print(f"  ✓ New size: {new_size / 1024 / 1024:.2f} MB")
    print(f"  ✓ Freed: {actual_savings / 1024 / 1024:.2f} MB")

    print("\n✅ Cleanup complete!")
    conn.close()


if __name__ == '__main__':
    days = None  # Will read from config
    execute = False
    db_path = None

    # Parse arguments
    args = [arg for arg in sys.argv[1:] if arg != '--execute']
    if '--execute' in sys.argv:
        execute = True

    # First arg could be days or db_path
    if len(args) >= 1:
        try:
            days = int(args[0])
            # If second arg exists, it's db_path
            if len(args) >= 2:
                db_path = args[1]
        except ValueError:
            # First arg is db_path
            db_path = args[0]

    # Show config value if using it
    if days is None:
        config_days = get_retention_days_from_config()
        print(f"📋 Using retention from config: {config_days} days\n")

    cleanup_old_data(days_to_keep=days, dry_run=not execute, db_path=db_path)
