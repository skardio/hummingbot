#!/usr/bin/env python3
"""
Script C: Explain why bot didn't trade at specific times
Join bot decision timestamps with MarketData to see market context

Usage:
    python3 explain_no_trade_decisions.py <TIMESTAMP_MS> [PAIR] [DB_PATH]
    python3 explain_no_trade_decisions.py 1735481234000
    python3 explain_no_trade_decisions.py 1735481234000 BTC-EUR data/my_bot.sqlite
"""


def find_database():
    """Auto-detect most recent database"""
    db_pattern = 'data/*.sqlite'
    dbs = glob.glob(db_pattern)
    if not dbs:
        return None
    return max(dbs, key=os.path.getmtime)


def explain_no_trade(timestamp_ms, pair=None, db_path=None):
    """
    Explain market conditions at given timestamp

    Args:
        timestamp_ms: Timestamp in milliseconds
        pair: Specific trading pair (optional)
        db_path: Path to database (auto-detect if None)
    """
    if not db_path:
        db_path = find_database()

    if not db_path or not os.path.exists(db_path):
        print(f"\n⚠️  Database not found: {db_path}")
        return

    print(f"📁 Using: {db_path}")
    conn = sqlite3.connect(db_path)

    # Convert to readable time
    dt = datetime.fromtimestamp(timestamp_ms / 1000)

    print("=" * 80)
    print("🔍 MARKET CONTEXT ANALYSIS")
    print(f"   Time: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Timestamp: {timestamp_ms}")
    if pair:
        print(f"   Pair: {pair}")
    print("=" * 80)

    # Find market data within ±30 seconds
    query = """
        SELECT
            trading_pair,
            timestamp,
            mid_price,
            best_bid,
            best_ask,
            (best_ask - best_bid) as spread_abs,
            (best_ask - best_bid) / mid_price * 100 as spread_pct,
            order_book
        FROM MarketData
        WHERE timestamp BETWEEN ? AND ?
    """

    params = [timestamp_ms - 30000, timestamp_ms + 30000]

    if pair:
        query += " AND trading_pair = ?"
        params.append(pair)

    query += " ORDER BY ABS(timestamp - ?) ASC"
    params.append(timestamp_ms)

    cursor = conn.execute(query, params)
    results = cursor.fetchall()

    if not results:
        print("\n⚠️  No market data found for this timestamp")
        print("   • Is MarketData collection enabled?")
        print("   • Is timestamp within data range?")
        print("\nCheck available data:")
        conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM MarketData").fetchone()
        return

    print(f"\n📊 FOUND {len(results)} MARKET SNAPSHOTS (±30s window)\n")

    # Analyze each pair
    for row in results[:10]:  # Limit to 10 pairs
        pair, ts, mid, bid, ask, spread_abs, spread_pct, ob_json = row

        time_diff = abs(ts - timestamp_ms) / 1000

        print(f"\n{'=' * 80}")
        print(f"  {pair}")
        print(f"{'=' * 80}")
        print(f"  Time diff: {time_diff:.1f}s")
        print(f"  Mid Price: €{mid:.6f}")
        print(f"  Spread: €{spread_abs:.6f} ({spread_pct:.3f}%)")

        # Analyze spread
        if spread_pct > 0.5:
            print(f"  🔴 SPREAD TOO HIGH ({spread_pct:.3f}% > 0.5%)")
            print("     → Bot likely rejected due to high cost")
        elif spread_pct > 0.3:
            print(f"  🟡 SPREAD MODERATE ({spread_pct:.3f}%)")
        else:
            print(f"  🟢 SPREAD OK ({spread_pct:.3f}%)")

        # Analyze orderbook depth
        if ob_json:
            try:
                ob = json.loads(ob_json)
                bids = ob.get('bid', [])
                asks = ob.get('ask', [])

                if bids and asks:
                    top_bid_size = float(bids[0][1]) if len(bids) > 0 else 0
                    top_ask_size = float(asks[0][1]) if len(asks) > 0 else 0

                    # Calculate depth in top 5 levels
                    bid_depth_5 = sum(float(b[1]) for b in bids[:5])
                    ask_depth_5 = sum(float(a[1]) for a in asks[:5])

                    print("  Liquidity:")
                    print(f"     Top Bid: {top_bid_size:.2f} units")
                    print(f"     Top Ask: {top_ask_size:.2f} units")
                    print(f"     Top 5 Bid Depth: {bid_depth_5:.2f} units")
                    print(f"     Top 5 Ask Depth: {ask_depth_5:.2f} units")

                    if bid_depth_5 < 10 or ask_depth_5 < 10:
                        print("  🔴 LOW LIQUIDITY (< 10 units in top 5)")
                        print("     → Bot likely rejected due to thin orderbook")
                    elif bid_depth_5 < 50 or ask_depth_5 < 50:
                        print("  🟡 MODERATE LIQUIDITY")
                    else:
                        print("  🟢 GOOD LIQUIDITY")
            except json.JSONDecodeError:
                print("  ⚠️  Could not parse orderbook")

    # Summary
    print(f"\n{'=' * 80}")
    print("💡 LIKELY REASONS FOR NO TRADE:")
    print(f"{'=' * 80}")

    # Calculate averages
    avg_spread = sum(r[6] for r in results) / len(results)

    reasons = []
    if avg_spread > 0.5:
        reasons.append(f"• Spread too high (avg: {avg_spread:.3f}%)")
    if len(results) < 3:
        reasons.append(f"• Insufficient market data (only {len(results)} snapshots)")

    if reasons:
        for reason in reasons:
            print(f"  {reason}")
    else:
        print("  • Market conditions looked OK")
        print("  • Check bot logs for other filters:")
        print("     - Insufficient balance?")
        print("     - Max position reached?")
        print("     - Cooldown period active?")
        print("     - Trend filter rejection?")

    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("\nUsage: python explain_no_trade_decisions.py <TIMESTAMP_MS> [PAIR] [DB_PATH]")
        print("Example: python explain_no_trade_decisions.py 1735481234000")
        print("Example: python explain_no_trade_decisions.py 1735481234000 BTC-EUR")
        print("Example: python explain_no_trade_decisions.py 1735481234000 BTC-EUR data/my_bot.sqlite\n")

        # Show recent data range
        db_path = find_database()
        if db_path and os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            result = conn.execute("""
                SELECT
                    MIN(timestamp) as first,
                    MAX(timestamp) as last,
                    COUNT(*) as count
                FROM MarketData
            """).fetchone()

            if result and result[2] > 0:
                first_dt = datetime.fromtimestamp(result[0] / 1000)
                last_dt = datetime.fromtimestamp(result[1] / 1000)
                print(f"Available data in {db_path}:")
                print(f"  First: {first_dt} ({result[0]})")
                print(f"  Last:  {last_dt} ({result[1]})")
                print(f"  Total: {result[2]} records\n")
            conn.close()

        sys.exit(1)

    ts = int(sys.argv[1])
    pair = sys.argv[2] if len(sys.argv) > 2 else None
    db_path = sys.argv[3] if len(sys.argv) > 3 else None

    explain_no_trade(ts, pair, db_path)
