#!/usr/bin/env python3
"""Check recent bot performance and provide recommendations"""

import sqlite3

db_path = "data/multi_coin_grid_v2.sqlite"


def analyze_performance():
    conn = sqlite3.connect(db_path)

    # Get trades from last 24 hours
    query = """
    SELECT
        symbol,
        trade_type,
        CAST(amount AS REAL)/1e8 as amount,
        CAST(price AS REAL)/1e8 as price,
        CAST(trade_fee_in_quote AS REAL)/1e8 as fee,
        timestamp
    FROM TradeFill
    ORDER BY timestamp DESC
    LIMIT 200
    """

    cursor = conn.cursor()
    cursor.execute(query)
    trades = cursor.fetchall()

    # Analyze by symbol
    symbols = {}
    total_fees = 0

    for trade in trades:
        symbol, side, amount, price, fee, ts = trade

        if symbol not in symbols:
            symbols[symbol] = {
                'buys': 0,
                'sells': 0,
                'buy_volume': 0,
                'sell_volume': 0,
                'fees': 0,
                'inventory': 0,
                'buy_value': 0,
                'sell_value': 0
            }

        value = amount * price
        symbols[symbol]['fees'] += fee if fee else 0
        total_fees += fee if fee else 0

        if side == 'BUY':
            symbols[symbol]['buys'] += 1
            symbols[symbol]['buy_volume'] += amount
            symbols[symbol]['buy_value'] += value
            symbols[symbol]['inventory'] += amount
        else:
            symbols[symbol]['sells'] += 1
            symbols[symbol]['sell_volume'] += amount
            symbols[symbol]['sell_value'] += value
            symbols[symbol]['inventory'] -= amount

    print("\n" + "=" * 80)
    print("📊 RECENT TRADING PERFORMANCE (Last 200 trades)")
    print("=" * 80 + "\n")

    for symbol, data in sorted(symbols.items(), key=lambda x: x[1]['buys'] + x[1]['sells'], reverse=True):
        total_trades = data['buys'] + data['sells']
        imbalance = data['buys'] - data['sells']

        # Calculate REALIZED PnL (only from completed buy-sell cycles)
        # Note: This does NOT include unrealized inventory value!
        avg_buy_price = data['buy_value'] / data['buy_volume'] if data['buy_volume'] > 0 else 0
        avg_sell_price = data['sell_value'] / data['sell_volume'] if data['sell_volume'] > 0 else 0

        # For pairs: realized PnL = (avg_sell_price - avg_buy_price) × min(buys, sells)
        completed_cycles = min(data['buys'], data['sells'])
        realized_pnl = (avg_sell_price - avg_buy_price) * data['sell_volume'] - data['fees'] if completed_cycles > 0 else -data['fees']

        # Inventory value (at average buy price - NOT current market price!)
        inventory_cost = abs(data['inventory']) * avg_buy_price if data['inventory'] != 0 else 0

        print(f"📈 {symbol}:")
        print(f"   Trades: {total_trades} ({data['buys']} buys, {data['sells']} sells)")
        print(f"   Imbalance: {imbalance:+d} ({'📉 Buying more' if imbalance > 0 else '📈 Selling more' if imbalance < 0 else '✅ Balanced'})")
        print(f"   Inventory: {data['inventory']:.4f} {symbol.split('-')[0]} (cost: €{inventory_cost:.2f})")
        print(f"   Fees: €{data['fees']:.2f}")
        print(f"   Realized PnL: €{realized_pnl:+.2f} (from {completed_cycles} completed cycles)")
        if abs(data['inventory']) > 0.01:
            print(f"   ⚠️  Unrealized: €{inventory_cost:.2f} in inventory (market value unknown)")
        print()

    print(f"\n💰 Total Fees Paid: €{total_fees:.2f}")
    print("\n" + "=" * 80)
    print("💡 RECOMMENDATIONS FOR VOLATILE MARKETS")
    print("=" * 80 + "\n")

    # Check for issues
    issues = []
    for symbol, data in symbols.items():
        imbalance = data['buys'] - data['sells']
        if abs(imbalance) > 10:
            issues.append(f"⚠️  {symbol}: Large imbalance ({imbalance:+d}) - inventory risk!")

    if issues:
        print("🚨 ISSUES DETECTED:")
        for issue in issues:
            print(f"   {issue}")
        print()

    print("📋 VOLATILITY ADJUSTMENTS:")
    print("   1. ✅ Widen grid ranges (allow more price movement)")
    print("      - Down: 4% → 6%")
    print("      - Up: 8% → 10%")
    print()
    print("   2. ✅ Increase take_profit (capture larger moves)")
    print("      - Current: 7%")
    print("      - Recommended: 10-12% in volatile markets")
    print()
    print("   3. ✅ Tighten stop losses (limit downside)")
    print("      - Enable: emergency_stop_loss_pct: -8%")
    print()
    print("   4. ✅ Reduce simultaneous coins (focus on best)")
    print("      - Current: 4 coins")
    print("      - Volatile: 2-3 coins (better risk control)")
    print()
    print("   5. ⚠️  Lower capital per coin (reduce exposure)")
    print("      - Current: €70 per coin")
    print("      - Volatile: €50 per coin")
    print()

    conn.close()


if __name__ == "__main__":
    analyze_performance()
