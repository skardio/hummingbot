#!/usr/bin/env python3
"""
Script B: Calculate slippage risk for your order sizes
Simulate fills against real orderbook snapshots

Usage:
    python3 calculate_slippage_risk.py BTC-EUR 1000 SELL
    python3 calculate_slippage_risk.py BTC-EUR 1000 SELL data/my_bot.sqlite
"""


def find_database():
    """Auto-detect most recent database"""
    db_pattern = 'data/*.sqlite'
    dbs = glob.glob(db_pattern)
    if not dbs:
        return None
    return max(dbs, key=os.path.getmtime)


def calculate_slippage(pair, order_size_eur, side='SELL', db_path=None):
    """
    Calculate expected slippage for given order size

    Args:
        pair: Trading pair (e.g., 'BTC-EUR')
        order_size_eur: Order size in EUR
        side: 'BUY' or 'SELL'
        db_path: Path to database (auto-detect if None)
    """
    if not db_path:
        db_path = find_database()

    if not db_path or not os.path.exists(db_path):
        print(f"\n⚠️  Database not found: {db_path}")
        return

    print(f"📁 Using: {db_path}")
    conn = sqlite3.connect(db_path)

    # Get recent orderbook snapshots
    cursor = conn.execute("""
        SELECT timestamp, mid_price, order_book
        FROM MarketData
        WHERE trading_pair = ?
          AND exchange = 'kraken'
          AND order_book IS NOT NULL
          AND timestamp > (strftime('%s', 'now') - 3600) * 1000  -- Last hour
        ORDER BY timestamp DESC
        LIMIT 20
    """, (pair,))

    results = cursor.fetchall()

    if not results:
        print(f"\n⚠️  No orderbook data for {pair}")
        return

    print("=" * 80)
    print(f"💧 SLIPPAGE ANALYSIS: {pair}")
    print(f"   Order Size: €{order_size_eur:.2f}")
    print(f"   Side: {side}")
    print("=" * 80)

    slippages = []

    for ts, mid_price, ob_json in results:
        ob = json.loads(ob_json)

        # Select bid or ask side
        if side == 'SELL':
            levels = ob.get('bid', [])
            direction = -1  # Price goes down
        else:
            levels = ob.get('ask', [])
            _direction = 1  # Price goes up

        if not levels:
            continue

        # Simulate fill
        cumulative_eur = 0
        cumulative_qty = 0
        weighted_price = 0
        levels_needed = 0

        for price_str, qty_str in levels[:20]:  # Top 20 levels
            price = float(price_str)
            qty = float(qty_str)

            remaining = order_size_eur - cumulative_eur
            if remaining <= 0:
                break

            # How much can we fill at this level?
            eur_at_level = price * qty
            take_eur = min(eur_at_level, remaining)
            take_qty = take_eur / price

            weighted_price += price * take_qty
            cumulative_eur += take_eur
            cumulative_qty += take_qty
            levels_needed += 1

            if cumulative_eur >= order_size_eur:
                break

        # Calculate average fill price
        if cumulative_qty > 0:
            avg_fill_price = weighted_price / cumulative_qty
            slippage_abs = abs(avg_fill_price - mid_price)
            slippage_pct = (slippage_abs / mid_price) * 100
            coverage_pct = (cumulative_eur / order_size_eur) * 100

            slippages.append({
                'timestamp': ts,
                'mid_price': mid_price,
                'avg_fill': avg_fill_price,
                'slippage_pct': slippage_pct,
                'levels': levels_needed,
                'coverage': coverage_pct
            })

    if not slippages:
        print("\n⚠️  Could not calculate slippage (insufficient orderbook data)\n")
        return

    # Statistics
    avg_slippage = sum(s['slippage_pct'] for s in slippages) / len(slippages)
    max_slippage = max(s['slippage_pct'] for s in slippages)
    min_slippage = min(s['slippage_pct'] for s in slippages)
    avg_levels = sum(s['levels'] for s in slippages) / len(slippages)
    avg_coverage = sum(s['coverage'] for s in slippages) / len(slippages)

    print(f"\n📊 SLIPPAGE STATISTICS (from {len(slippages)} snapshots):")
    print(f"   • Average Slippage: {avg_slippage:.3f}%")
    print(f"   • Min Slippage: {min_slippage:.3f}%")
    print(f"   • Max Slippage: {max_slippage:.3f}%")
    print(f"   • Avg Levels Needed: {avg_levels:.1f}")
    print(f"   • Avg Coverage: {avg_coverage:.1f}%")

    # Risk assessment
    print("\n💡 RISK ASSESSMENT:")
    if avg_slippage < 0.1:
        print("   🟢 LOW RISK: Slippage < 0.1%")
        print("      → Market orders are safe for this size")
    elif avg_slippage < 0.3:
        print("   🟡 MODERATE RISK: Slippage 0.1-0.3%")
        print("      → Consider limit orders in non-urgent cases")
    else:
        print("   🔴 HIGH RISK: Slippage > 0.3%")
        print("      → Use limit orders or reduce position size")

    if avg_coverage < 95:
        print(f"   ⚠️  WARNING: Only {avg_coverage:.1f}% coverage")
        print("      → Not enough liquidity for this size!")

    # Recommendation
    safe_size = order_size_eur * 0.5 if avg_slippage > 0.3 else order_size_eur
    print("\n📋 RECOMMENDATION:")
    print(f"   Max safe order size: €{safe_size:.2f}")
    print(f"   Expected cost: €{(order_size_eur * avg_slippage / 100):.2f} ({avg_slippage:.3f}%)")

    # Worst case scenario
    worst = max(slippages, key=lambda x: x['slippage_pct'])
    print("\n🔥 WORST CASE (from sample):")
    print(f"   Slippage: {worst['slippage_pct']:.3f}%")
    print(f"   Cost: €{(order_size_eur * worst['slippage_pct'] / 100):.2f}")
    print(f"   Levels: {worst['levels']}")

    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("\nUsage: python calculate_slippage_risk.py <PAIR> <SIZE_EUR> [SIDE] [DB_PATH]")
        print("Example: python calculate_slippage_risk.py BTC-EUR 1000 SELL")
        print("Example: python calculate_slippage_risk.py BTC-EUR 1000 SELL data/my_bot.sqlite\n")
        sys.exit(1)

    pair = sys.argv[1]
    size = float(sys.argv[2])
    side = sys.argv[3] if len(sys.argv) > 3 else 'SELL'
    db_path = sys.argv[4] if len(sys.argv) > 4 else None

    calculate_slippage(pair, size, side, db_path)
