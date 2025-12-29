#!/usr/bin/env python3
"""
Optimize MarketData database performance with indexes
Run this after enabling MarketData collection

Usage:
    python3 optimize_market_data_db.py                    # Auto-detect DB
    python3 optimize_market_data_db.py <DB_PATH>          # Specify DB
"""


def find_database():
    """Auto-detect most recent database"""
    db_pattern = 'data/*.sqlite'
    dbs = glob.glob(db_pattern)
    if not dbs:
        return None
    return max(dbs, key=os.path.getmtime)


def optimize_database(db_path):
    if not db_path or not os.path.exists(db_path):
        print(f"\n⚠️  Database not found: {db_path}")
        return

    print("=" * 70)
    print("⚙️  DATABASE OPTIMIZATION")
    print("=" * 70)
    print(f"\n📁 Database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current size
    cursor.execute("SELECT COUNT(*) FROM MarketData")
    count = cursor.fetchone()[0]
    print(f"\n📊 Current MarketData records: {count:,}")

    if count == 0:
        print("\n⚠️  No data yet. Enable collection first!")
        return

    # Create indexes
    print("\n🔧 Creating indexes...")

    indexes = [
        ("idx_md_pair_time", "MarketData(exchange, trading_pair, timestamp)"),
        ("idx_md_exchange", "MarketData(exchange)"),
        ("idx_md_timestamp", "MarketData(timestamp)"),
    ]

    for idx_name, idx_def in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            print(f"  ✓ {idx_name}")
        except Exception as e:
            print(f"  ✗ {idx_name}: {e}")

    conn.commit()

    # Analyze table statistics
    print("\n📈 Table statistics:")
    cursor.execute("ANALYZE MarketData")

    # Get size info
    cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
    db_size = cursor.fetchone()[0]
    print(f"  Database size: {db_size / 1024 / 1024:.2f} MB")

    # Get date range
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM MarketData")
    min_ts, max_ts = cursor.fetchone()

    if min_ts and max_ts:
        from datetime import datetime
        min_dt = datetime.fromtimestamp(min_ts / 1000)
        max_dt = datetime.fromtimestamp(max_ts / 1000)
        days = (max_ts - min_ts) / 1000 / 86400

        print(f"  Date range: {min_dt.strftime('%Y-%m-%d')} to {max_dt.strftime('%Y-%m-%d')}")
        print(f"  Days of data: {days:.1f}")
        print(f"  Records/day: {count / days:.0f}" if days > 0 else "")

    # Cleanup old data (optional)
    print("\n🗑️  Cleanup options:")
    cursor.execute("""
        SELECT COUNT(*) FROM MarketData
        WHERE timestamp < (strftime('%s', 'now') - 2592000) * 1000
    """)
    old_count = cursor.fetchone()[0]

    if old_count > 0:
        print(f"  Found {old_count:,} records older than 30 days")
        print("  To delete: python cleanup_old_market_data.py")
    else:
        print("  No old data to clean ✓")

    print("\n✅ Optimization complete!")
    conn.close()


if __name__ == '__main__':
    db_path = sys.argv[1] if len(sys.argv) > 1 else find_database()

    if db_path:
        optimize_database(db_path)
    else:
        print("\nUsage: python3 optimize_market_data_db.py [DB_PATH]")
        print("Example: python3 optimize_market_data_db.py data/multi_coin_grid_v2.sqlite\n")
