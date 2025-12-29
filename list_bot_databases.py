#!/usr/bin/env python3
"""
List all available bot databases and their MarketData status
Useful when you have multiple bots
"""


def list_databases():
    """List all SQLite databases in data/ folder"""
    db_files = glob.glob('data/*.sqlite')

    if not db_files:
        print("\n⚠️  No databases found in data/\n")
        return

    print("=" * 90)
    print("🤖 AVAILABLE BOT DATABASES")
    print("=" * 90)
    print(f"\nFound {len(db_files)} database(s):\n")

    for db_path in sorted(db_files):
        db_name = os.path.basename(db_path)
        db_size = os.path.getsize(db_path) / 1024 / 1024  # MB

        print(f"📊 {db_name}")
        print(f"   Path: {db_path}")
        print(f"   Size: {db_size:.2f} MB")

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Check MarketData
            try:
                cursor.execute("SELECT COUNT(*) FROM MarketData")
                md_count = cursor.fetchone()[0]

                if md_count > 0:
                    # Get date range
                    cursor.execute("""
                        SELECT MIN(timestamp), MAX(timestamp),
                               COUNT(DISTINCT trading_pair)
                        FROM MarketData
                    """)
                    min_ts, max_ts, pairs = cursor.fetchone()

                    first_dt = datetime.fromtimestamp(min_ts / 1000)
                    last_dt = datetime.fromtimestamp(max_ts / 1000)
                    days = (max_ts - min_ts) / 1000 / 86400

                    print(f"   ✅ MarketData: {md_count:,} records")
                    print(f"      • Trading pairs: {pairs}")
                    print(f"      • Date range: {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')} ({days:.1f} days)")
                    print(f"      • Records/day: {md_count / days:.0f}" if days > 0 else "")
                else:
                    print("   ⚪ MarketData: Empty (collection not enabled or just started)")
            except sqlite3.OperationalError:
                print("   ❌ MarketData: Table doesn't exist")

            # Check other tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            main_tables = ['"Order"', 'TradeFill', 'MarketState']
            table_display = ['Order', 'TradeFill', 'MarketState']

            for i, table in enumerate(main_tables):
                if table_display[i] in [t.strip('"') for t in tables]:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    if count > 0:
                        print(f"   • {table_display[i]}: {count:,} records")

            conn.close()

        except Exception as e:
            print(f"   ⚠️  Error reading database: {e}")

        print()

    print("=" * 90)
    print("💡 USAGE:")
    print("=" * 90)
    print("\nTo analyze specific database:")
    print(f"  python3 find_best_grid_pairs.py {db_files[0]}")
    print(f"  python3 calculate_slippage_risk.py BTC-EUR 1000 SELL {db_files[0]}")
    print(f"  python3 optimize_market_data_db.py {db_files[0]}")
    print()


if __name__ == '__main__':
    list_databases()
