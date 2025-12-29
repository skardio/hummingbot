#!/usr/bin/env python3
"""
Script A: Find best pairs for grid trading
Score based on: low spread + moderate volatility + good depth

Usage:
    python3 find_best_grid_pairs.py                          # Auto-detect DB
    python3 find_best_grid_pairs.py <DB_PATH>                # Specify DB
    python3 find_best_grid_pairs.py data/my_bot.sqlite       # Custom path
"""


def find_database():
    """Auto-detect most recent database"""
    db_pattern = 'data/*.sqlite'
    dbs = glob.glob(db_pattern)
    if not dbs:
        print("⚠️  No database found in data/")
        return None
    # Return most recently modified
    return max(dbs, key=os.path.getmtime)


def get_db_path():
    """Get DB path from args or auto-detect"""
    if len(sys.argv) > 1:
        return sys.argv[1]
    return find_database()


def find_best_grid_pairs(db_path):
    if not db_path or not os.path.exists(db_path):
        print(f"\n⚠️  Database not found: {db_path}")
        return

    print(f"📁 Using database: {db_path}\n")
    conn = sqlite3.connect(db_path)

    # Check if data exists
    count = conn.execute("SELECT COUNT(*) FROM MarketData").fetchone()[0]
    if count == 0:
        print("\n⚠️  No MarketData found!")
        print("   Enable: market_data_collection_enabled: true in conf/conf_client.yml")
        print("   Restart bot and wait a few hours.\n")
        return

    print("=" * 85)
    print("🎯 BEST PAIRS FOR GRID TRADING")
    print("=" * 85)

    # Comprehensive grid suitability score
    cursor = conn.execute("""
        SELECT
            trading_pair,
            -- Spread metrics
            AVG((best_ask-best_bid)/mid_price)*100 AS avg_spread_pct,
            MAX((best_ask-best_bid)/mid_price)*100 AS max_spread_pct,

            -- Price movement (volatility)
            (MAX(mid_price)-MIN(mid_price))/AVG(mid_price)*100 AS price_range_pct,

            -- Liquidity (depth) - safely handle NULL
            COALESCE(AVG(CAST(json_extract(order_book, '$.bid[0][1]') AS REAL)), 0) AS avg_top_bid,

            -- Sample quality
            COUNT(*) AS samples
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 86400) * 1000  -- Last 24h
        GROUP BY trading_pair
        HAVING samples > 50  -- Minimum for reliability
        ORDER BY avg_spread_pct ASC
    """)

    results = cursor.fetchall()

    if not results:
        print("\n⚠️  Not enough data yet. Wait for more samples.\n")
        return

    print(f"\n📈 Analysis: {sum(r[5] for r in results)} samples from last 24h\n")
    print(f"{'Pair':<14} {'Spread%':<9} {'Vol%':<9} {'Depth':<10} {'Grade':<12} {'Recommendation'}")
    print("=" * 85)

    recommendations = []

    for row in results[:20]:  # Top 20
        pair, spread, max_spread, vol, depth, samples = row

        # Scoring logic
        if spread < 0.15 and vol > 2 and vol < 10 and depth > 50:
            grade = "🟢 Excellent"
            rec = f"Grid: {vol * 0.12:.3f}% spacing"
        elif spread < 0.3 and vol > 1 and vol < 15 and depth > 20:
            grade = "🟡 Good"
            rec = f"Grid: {vol * 0.15:.3f}% spacing"
        elif spread < 0.5 and vol > 0.5:
            grade = "🟠 OK"
            rec = f"Grid: {vol * 0.2:.3f}% spacing"
        else:
            grade = "🔴 Poor"
            rec = "❌ Avoid (too risky)"

        print(f"{pair:<14} {spread:>6.3f}%   {vol:>6.2f}%   {depth:>8.1f}   {grade:<12} {rec}")

        if grade in ["🟢 Excellent", "🟡 Good"]:
            recommendations.append((pair, spread, vol, depth))

    # Top recommendation
    if recommendations:
        print("\n" + "=" * 85)
        print("💡 TOP RECOMMENDATION:")
        print("=" * 85)

        best = recommendations[0]
        pair, spread, vol, depth = best

        grid_spacing = vol * 0.12  # 12% of daily volatility
        profit_per_grid = spread * 1.5  # 1.5x spread voor safety
        num_grids = min(int(vol / grid_spacing), 20)
        safe_size = depth * 0.3

        print(f"\n🎯 BEST PAIR: {pair}")
        print("\n   📊 Metrics:")
        print(f"      • Avg Spread: {spread:.3f}%")
        print(f"      • Volatility: {vol:.2f}% (24h)")
        print(f"      • Top Depth: {depth:.1f} units")
        print("\n   ⚙️  Suggested Config:")
        print(f"      grid_spacing_percentage: {grid_spacing:.3f}")
        print(f"      profit_per_grid: {profit_per_grid:.3f}")
        print(f"      number_of_grids: {num_grids}")
        print(f"      max_position_size: {safe_size:.1f} units")
        print("\n   💰 Expected:")
        print(f"      • Profit/grid: ~{profit_per_grid:.3f}%")
        print(f"      • Grids/day: ~{vol / grid_spacing:.1f} (if full volatility captured)")
        print(f"      • Daily potential: ~{(vol / grid_spacing) * profit_per_grid:.2f}%")

    conn.close()


if __name__ == '__main__':
    db_path = get_db_path()
    if db_path:
        find_best_grid_pairs(db_path)
    else:
        print("\nUsage: python3 find_best_grid_pairs.py [DB_PATH]")
        print("Example: python3 find_best_grid_pairs.py data/multi_coin_grid_v2.sqlite\n")
