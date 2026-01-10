#!/usr/bin/env python3
"""
Professional 4-day analysis for €5000 trading decision
Focus: Real performance metrics, risk assessment, scaling readiness
"""

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


def get_recent_trades(days=4):
    """Get trades from last N days with proper decimal handling"""
    db_path = "data/multi_coin_grid_v2.sqlite"

    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get cutoff timestamp (4 days ago) - database uses milliseconds
    cutoff_time = (datetime.now() - timedelta(days=days)).timestamp() * 1_000

    query = """
    SELECT
        symbol,
        trade_type,
        amount,
        price,
        trade_fee_in_quote,
        timestamp,
        market
    FROM TradeFill
    WHERE timestamp > ?
    ORDER BY timestamp DESC
    """

    cursor.execute(query, (int(cutoff_time),))
    trades = cursor.fetchall()
    conn.close()

    return trades


def safe_decimal(value, divisor=100_000_000):
    """Safely convert microsecond integer to decimal"""
    try:
        if value is None:
            return Decimal('0')
        # Database stores values as integers (price * 1e8)
        return Decimal(str(value)) / Decimal(str(divisor))
    except:
        return Decimal('0')


def analyze_trading_performance(trades):
    """Comprehensive trading analysis"""

    if not trades:
        return None

    # By exchange
    kraken_trades = [t for t in trades if 'kraken' in t[6].lower()]
    bitget_trades = [t for t in trades if 'bitget' in t[6].lower()]

    # By symbol
    symbol_data = defaultdict(lambda: {
        'buys': [],
        'sells': [],
        'fees': Decimal('0'),
        'buy_volume': Decimal('0'),
        'sell_volume': Decimal('0')
    })

    total_fees = Decimal('0')

    for trade in trades:
        symbol, side, amount, price, fee, ts, market = trade

        # Convert to decimals
        amount_dec = safe_decimal(amount)
        price_dec = safe_decimal(price)
        fee_dec = safe_decimal(fee)

        total_fees += fee_dec

        s = symbol_data[symbol]
        s['fees'] += fee_dec

        if side == 'BUY':
            s['buys'].append({'amount': amount_dec, 'price': price_dec})
            s['buy_volume'] += amount_dec
        else:
            s['sells'].append({'amount': amount_dec, 'price': price_dec})
            s['sell_volume'] += amount_dec

    # Calculate P&L per symbol
    realized_pnl = Decimal('0')
    unrealized_inventory = {}

    for symbol, data in symbol_data.items():
        # Match buys and sells for realized P&L
        buys_sorted = sorted(data['buys'], key=lambda x: x['price'])
        sells_sorted = sorted(data['sells'], key=lambda x: x['price'], reverse=True)

        # Calculate realized P&L from matched trades
        matched_volume = Decimal('0')
        for i in range(min(len(buys_sorted), len(sells_sorted))):
            buy_vol = buys_sorted[i]['amount']
            sell_vol = sells_sorted[i]['amount']
            matched = min(buy_vol, sell_vol)

            pnl = (sells_sorted[i]['price'] - buys_sorted[i]['price']) * matched
            realized_pnl += pnl
            matched_volume += matched

        # Calculate remaining inventory
        remaining = data['buy_volume'] - data['sell_volume']
        if abs(remaining) > Decimal('0.001'):
            avg_buy_price = sum(b['price'] * b['amount'] for b in data['buys']) / data['buy_volume'] if data['buy_volume'] > 0 else Decimal('0')
            unrealized_inventory[symbol] = {
                'amount': remaining,
                'avg_cost': avg_buy_price,
                'value': remaining * avg_buy_price
            }

    return {
        'total_trades': len(trades),
        'kraken_count': len(kraken_trades),
        'bitget_count': len(bitget_trades),
        'total_fees': total_fees,
        'realized_pnl': realized_pnl,
        'net_pnl': realized_pnl - total_fees,
        'symbol_data': dict(symbol_data),
        'unrealized_inventory': unrealized_inventory
    }


def analyze_audit_logs(days=4):
    """Analyze executor audit logs"""

    audit_dir = Path("audits")
    if not audit_dir.exists():
        print(f"⚠️  Audit directory not found: {audit_dir}")
        return None

    # Get recent audit files
    today = datetime.now()
    audit_data = []

    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        filepath = audit_dir / f"{date}.jsonl"

        if filepath.exists():
            with open(filepath, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        audit_data.append(data)
                    except:
                        pass

    if not audit_data:
        return None

    # Analyze executors
    profitable = 0
    losing = 0
    total_pnl = Decimal('0')
    total_fees = Decimal('0')

    close_reasons = defaultdict(int)
    symbols_traded = set()
    durations = []

    for executor in audit_data:
        # Get close type
        close_type = executor.get('close_type', 'unknown')
        close_reasons[close_type] += 1

        # Track symbol
        config = executor.get('config', {})
        symbol = config.get('trading_pair', 'unknown')
        symbols_traded.add(symbol)

        # Duration
        duration = executor.get('duration_minutes', 0)
        if duration:
            try:
                durations.append(float(duration))
            except:
                pass

        # P&L
        try:
            pnl = Decimal(str(executor.get('realized_pnl_quote', 0)))
            fees = Decimal(str(executor.get('fees_quote', 0)))

            if pnl > 0:
                profitable += 1
            elif pnl < 0:
                losing += 1

            total_pnl += pnl
            total_fees += fees
        except:
            pass

    win_rate = (profitable / len(audit_data) * 100) if audit_data else 0
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        'total_executors': len(audit_data),
        'profitable': profitable,
        'losing': losing,
        'breakeven': len(audit_data) - profitable - losing,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'total_fees': total_fees,
        'net_pnl': total_pnl - total_fees,
        'close_reasons': dict(close_reasons),
        'symbols_traded': len(symbols_traded),
        'avg_duration_minutes': avg_duration
    }


def generate_report(trade_analysis, audit_analysis):
    """Generate comprehensive decision report"""

    print("\n" + "=" * 80)
    print("📊 4-DAY PERFORMANCE ANALYSIS - €5000 TRADING DECISION")
    print("=" * 80)
    print(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Period: Last 4 days")
    print(f"Current Capital: €280 (Kraken)")
    print(f"Proposed Capital: €5000")
    print(f"Scaling Factor: 17.9x")
    print("=" * 80 + "\n")

    # === TRADING ACTIVITY ===
    print("📈 TRADING ACTIVITY")
    print("-" * 80)

    if trade_analysis:
        print(f"Total Trades: {trade_analysis['total_trades']}")
        print(f"  - Kraken (EUR): {trade_analysis['kraken_count']}")
        print(f"  - Bitget (USDT): {trade_analysis['bitget_count']}")

        trades_per_day = trade_analysis['total_trades'] / 4
        print(f"  - Average: {trades_per_day:.1f} trades/day")

        print(f"\nFees Paid: €{float(trade_analysis['total_fees']):.2f}")
        print(f"Realized P&L: €{float(trade_analysis['realized_pnl']):+.2f}")
        print(f"Net P&L: €{float(trade_analysis['net_pnl']):+.2f}")
    else:
        print("❌ No trade data available")

    print()

    # === EXECUTOR PERFORMANCE ===
    print("🎯 EXECUTOR PERFORMANCE")
    print("-" * 80)

    if audit_analysis:
        print(f"Total Executors: {audit_analysis['total_executors']}")
        print(f"  ✅ Profitable: {audit_analysis['profitable']} ({audit_analysis['win_rate']:.1f}%)")
        print(f"  ❌ Losing: {audit_analysis['losing']}")
        print(f"  ⚖️  Breakeven: {audit_analysis['breakeven']}")

        print(f"\nExecutor P&L: €{float(audit_analysis['total_pnl']):+.2f}")
        print(f"Executor Fees: €{float(audit_analysis['total_fees']):.2f}")
        print(f"Executor Net: €{float(audit_analysis['net_pnl']):+.2f}")

        print(f"\nAverage Duration: {audit_analysis['avg_duration_minutes']:.0f} minutes")
        print(f"Unique Symbols: {audit_analysis['symbols_traded']}")

        print("\nClose Reasons:")
        for reason, count in sorted(audit_analysis['close_reasons'].items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = (count / audit_analysis['total_executors'] * 100)
            print(f"  - {reason}: {count} ({pct:.1f}%)")
    else:
        print("❌ No audit data available")

    print()

    # === INVENTORY ANALYSIS ===
    print("📦 INVENTORY ANALYSIS")
    print("-" * 80)

    if trade_analysis and trade_analysis['unrealized_inventory']:
        total_inventory_value = Decimal('0')
        problem_coins = []

        for symbol, inv in trade_analysis['unrealized_inventory'].items():
            value = abs(inv['value'])
            total_inventory_value += value

            if value > Decimal('10'):  # Only show > €10
                problem_coins.append({
                    'symbol': symbol,
                    'amount': float(inv['amount']),
                    'avg_cost': float(inv['avg_cost']),
                    'value': float(value)
                })

        if problem_coins:
            print("⚠️  OPEN POSITIONS:")
            for coin in sorted(problem_coins, key=lambda x: x['value'], reverse=True)[:10]:
                print(f"  - {coin['symbol']}: {coin['amount']:+.2f} @ €{coin['avg_cost']:.4f} = €{coin['value']:.2f}")

            print(f"\nTotal Inventory: €{float(total_inventory_value):.2f}")
            inventory_pct = (total_inventory_value / Decimal('280')) * 100
            print(f"As % of Capital: {float(inventory_pct):.1f}%")
        else:
            print("✅ No significant open positions")
    else:
        print("✅ No inventory data or minimal positions")

    print()

    # === DECISION CRITERIA ===
    print("=" * 80)
    print("💡 DECISION CRITERIA")
    print("=" * 80 + "\n")

    criteria_pass = []
    criteria_fail = []
    criteria_warn = []

    # 1. Trading Activity
    if trade_analysis and trade_analysis['total_trades'] > 100:
        criteria_pass.append(f"✅ High activity: {trade_analysis['total_trades']} trades in 4 days")
    elif trade_analysis and trade_analysis['total_trades'] > 50:
        criteria_warn.append(f"⚠️  Moderate activity: {trade_analysis['total_trades']} trades")
    else:
        criteria_fail.append(f"❌ Low activity: {trade_analysis['total_trades'] if trade_analysis else 0} trades")

    # 2. Profitability
    if trade_analysis and trade_analysis['net_pnl'] > Decimal('10'):
        criteria_pass.append(f"✅ Profitable: €{float(trade_analysis['net_pnl']):+.2f} net P&L")
    elif trade_analysis and trade_analysis['net_pnl'] > Decimal('0'):
        criteria_warn.append(f"⚠️  Marginally profitable: €{float(trade_analysis['net_pnl']):+.2f}")
    else:
        criteria_fail.append(f"❌ Unprofitable: €{float(trade_analysis['net_pnl']) if trade_analysis else 0:+.2f}")

    # 3. Win Rate
    if audit_analysis and audit_analysis['win_rate'] >= 50:
        criteria_pass.append(f"✅ Good win rate: {audit_analysis['win_rate']:.1f}%")
    elif audit_analysis and audit_analysis['win_rate'] >= 40:
        criteria_warn.append(f"⚠️  Acceptable win rate: {audit_analysis['win_rate']:.1f}%")
    else:
        criteria_fail.append(f"❌ Low win rate: {audit_analysis['win_rate']:.1f}%" if audit_analysis else "❌ No win rate data")

    # 4. Inventory Management
    if trade_analysis and trade_analysis['unrealized_inventory']:
        total_inv = sum(abs(inv['value']) for inv in trade_analysis['unrealized_inventory'].values())
        inv_pct = (total_inv / Decimal('280')) * 100

        if inv_pct < 40:
            criteria_pass.append(f"✅ Good inventory control: {float(inv_pct):.1f}% locked")
        elif inv_pct < 60:
            criteria_warn.append(f"⚠️  High inventory: {float(inv_pct):.1f}% locked")
        else:
            criteria_fail.append(f"❌ Excessive inventory: {float(inv_pct):.1f}% locked")
    else:
        criteria_pass.append("✅ Minimal inventory")

    # 5. Multi-coin capability
    if trade_analysis and (trade_analysis['kraken_count'] > 50 or trade_analysis['bitget_count'] > 50):
        criteria_pass.append(f"✅ Multi-coin working (Kraken: {trade_analysis['kraken_count']}, Bitget: {trade_analysis['bitget_count']})")
    else:
        criteria_warn.append("⚠️  Multi-coin needs verification")

    # 6. Executor efficiency
    if audit_analysis and audit_analysis['avg_duration_minutes'] > 0:
        if audit_analysis['avg_duration_minutes'] < 120:
            criteria_pass.append(f"✅ Efficient execution: {audit_analysis['avg_duration_minutes']:.0f} min avg")
        else:
            criteria_warn.append(f"⚠️  Slow execution: {audit_analysis['avg_duration_minutes']:.0f} min avg")

    # Print assessment
    for criterion in criteria_pass:
        print(criterion)
    for criterion in criteria_warn:
        print(criterion)
    for criterion in criteria_fail:
        print(criterion)

    print("\n" + "-" * 80 + "\n")

    # === FINAL RECOMMENDATION ===
    score = len(criteria_pass) * 2 + len(criteria_warn) * 1 - len(criteria_fail) * 3

    if score >= 8 and len(criteria_fail) == 0:
        print("🎯 RECOMMENDATION: ✅ GO - READY FOR €5000")
        print("\n📋 SCALING PLAN:")
        print("  Phase 1: €1000 for 3 days (test scaling)")
        print("  Phase 2: €2500 for 1 week (if P&L > 0)")
        print("  Phase 3: €5000 full deployment (if win rate > 50%)")
        print("\n⚙️  CONFIGURATION FOR €5000:")
        print("  • max_simultaneous_coins: 5-6")
        print("  • total_amount_quote: 5000")
        print("  • Per-coin: €833-1000")
        print("  • Daily loss limit: €50 (1%)")
        print("  • Weekly loss limit: €175 (3.5%)")
        print("  • Kill switch: -€250 total")

    elif score >= 4:
        print("🎯 RECOMMENDATION: ⚠️  CAUTIOUS - START WITH €1000-2000")
        print("\n📋 CONSERVATIVE PLAN:")
        print("  Week 1: €1000 (monitor closely)")
        print("  Week 2: €1500 (if profitable)")
        print("  Week 3: €2000 (if consistent)")
        print("  Month 2: Consider €5000 (after validation)")
        print("\n🎯 REQUIREMENTS TO SCALE:")
        print("  • Win rate > 50%")
        print("  • Net P&L positive every week")
        print("  • Inventory < 40% of capital")
        print("  • No drawdowns > 3%")

    else:
        print("🎯 RECOMMENDATION: ❌ WAIT - DO NOT SCALE")
        print("\n🔧 ISSUES TO FIX FIRST:")
        print("  • Improve win rate (target: 55%+)")
        print("  • Better inventory management")
        print("  • More consistent profitability")
        print("\n📅 NEXT STEPS:")
        print("  1. Continue with €280 for another week")
        print("  2. Monitor and fix issues")
        print("  3. Re-evaluate next week")
        print("  4. Scale ONLY after sustained improvement")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    print("\n🔍 Analyzing last 4 days of trading performance...\n")

    trades = get_recent_trades(days=4)
    trade_analysis = analyze_trading_performance(trades)
    audit_analysis = analyze_audit_logs(days=4)

    generate_report(trade_analysis, audit_analysis)
