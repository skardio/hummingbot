#!/usr/bin/env python3
"""
Analyze market data to optimize Multi-Coin Grid Bot
"""

DB_PATH = '/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite'


def analyze_trading_conditions():
    """Analyze which coins have best conditions for grid trading"""
    conn = sqlite3.connect(DB_PATH)

    print("=" * 70)
    print("🎯 GRID BOT OPTIMIZATION ANALYSIS")
    print("=" * 70)

    # 1. Best coins by spread
    print("\n📊 TOP 10 COINS BY SPREAD (smaller = better):")
    print("-" * 70)
    cursor = conn.execute("""
        SELECT
            trading_pair,
            AVG((best_ask - best_bid) / mid_price * 100) as avg_spread_pct,
            MIN((best_ask - best_bid) / mid_price * 100) as min_spread_pct,
            MAX((best_ask - best_bid) / mid_price * 100) as max_spread_pct,
            COUNT(*) as samples
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 86400) * 1000  -- Last 24h
        GROUP BY trading_pair
        HAVING samples > 10
        ORDER BY avg_spread_pct ASC
        LIMIT 10
    """)

    for row in cursor:
        pair, avg, min_s, max_s, samples = row
        print(f"  {pair:12s} Avg: {avg:.3f}% | Min: {min_s:.3f}% | Max: {max_s:.3f}% | ({samples} samples)")

    # 2. Most volatile coins (good for grid trading)
    print("\n📈 TOP 10 MOST VOLATILE COINS (good for grids):")
    print("-" * 70)
    cursor = conn.execute("""
        SELECT
            trading_pair,
            (MAX(mid_price) - MIN(mid_price)) / AVG(mid_price) * 100 as volatility_pct,
            AVG(mid_price) as avg_price,
            COUNT(*) as samples
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 86400) * 1000
        GROUP BY trading_pair
        HAVING samples > 10
        ORDER BY volatility_pct DESC
        LIMIT 10
    """)

    for row in cursor:
        pair, vol, avg_price, samples = row
        print(f"  {pair:12s} Volatility: {vol:.2f}% | Avg Price: €{avg_price:.4f} | ({samples} samples)")

    # 3. Liquidity analysis
    print("\n💧 LIQUIDITY ANALYSIS (top bid/ask sizes):")
    print("-" * 70)
    cursor = conn.execute("""
        SELECT
            trading_pair,
            AVG(CAST(json_extract(order_book, '$.bid[0][1]') AS REAL)) as avg_top_bid_size,
            AVG(CAST(json_extract(order_book, '$.ask[0][1]') AS REAL)) as avg_top_ask_size
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 3600) * 1000  -- Last hour
          AND order_book IS NOT NULL
        GROUP BY trading_pair
        ORDER BY avg_top_bid_size DESC
        LIMIT 10
    """)

    for row in cursor:
        pair, bid_size, ask_size = row
        if bid_size and ask_size:
            print(f"  {pair:12s} Top Bid: {bid_size:>8.2f} | Top Ask: {ask_size:>8.2f}")

    # 4. Best time to trade
    print("\n⏰ BEST TRADING HOURS (by liquidity):")
    print("-" * 70)
    cursor = conn.execute("""
        SELECT
            strftime('%H', datetime(timestamp / 1000, 'unixepoch')) as hour,
            AVG((best_ask - best_bid) / mid_price * 100) as avg_spread,
            COUNT(*) as samples
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 604800) * 1000  -- Last week
        GROUP BY hour
        ORDER BY avg_spread ASC
    """)

    print("  Hour | Avg Spread | Samples")
    print("  -----|------------|--------")
    for row in cursor:
        hour, spread, samples = row
        if samples > 10:
            print(f"  {hour}:00 | {spread:.3f}%    | {samples}")

    # 5. Recommendation
    print("\n" + "=" * 70)
    print("💡 RECOMMENDATIONS FOR YOUR GRID BOT:")
    print("=" * 70)

    # Find best coin
    best_coin = conn.execute("""
        SELECT
            trading_pair,
            AVG((best_ask - best_bid) / mid_price * 100) as avg_spread,
            (MAX(mid_price) - MIN(mid_price)) / AVG(mid_price) * 100 as volatility
        FROM MarketData
        WHERE exchange = 'kraken'
          AND timestamp > (strftime('%s', 'now') - 86400) * 1000
        GROUP BY trading_pair
        HAVING COUNT(*) > 50
        ORDER BY (avg_spread * 0.5 + (100 - volatility) * 0.5) ASC  -- Balance spread and volatility
        LIMIT 1
    """).fetchone()

    if best_coin:
        pair, spread, vol = best_coin
        print(f"\n  🎯 BEST COIN: {pair}")
        print(f"     - Spread: {spread:.3f}% (low = good)")
        print(f"     - Volatility: {vol:.2f}% (moderate = good)")
        print(f"     - Recommended grid spacing: {vol * 0.1:.3f}% per level")

    conn.close()


if __name__ == '__main__':
    analyze_trading_conditions()
