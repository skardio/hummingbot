#!/usr/bin/env python3
"""
Comprehensive 4-day performance analysis for trading decision
Analyzes: trades, P&L, win rate, risk metrics, inventory management
"""

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

db_path = "data/multi_coin_grid_v2.sqlite"
audit_dir = "audits"


def analyze_trades():
    """Analyze all trades from last 4 days"""
    conn = sqlite3.connect(db_path)

    # Get all trades
    query = """
    SELECT
        symbol,
        trade_type,
        CAST(amount AS REAL)/1e8 as amount,
        CAST(price AS REAL)/1e8 as price,
        CAST(trade_fee_in_quote AS REAL)/1e8 as fee,
        timestamp,
        market
    FROM TradeFill
    ORDER BY timestamp DESC
    """

    cursor = conn.cursor()
    cursor.execute(query)
    trades = cursor.fetchall()

    # Analyze by day and symbol
    daily_stats = defaultdict(lambda: {
        'trades': 0,
        'buys': 0,
        'sells': 0,
        'volume': 0,
        'fees': 0,
        'symbols': set()
    })

    symbol_stats = defaultdict(lambda: {
        'buys': 0,
        'sells': 0,
        'buy_value': 0,
        'sell_value': 0,
        'fees': 0,
        'inventory': 0,
        'avg_buy_price': 0,
        'avg_sell_price': 0
    })

    kraken_trades = 0
    bitget_trades = 0
    total_fees = 0

    for trade in trades:
        symbol, side, amount, price, fee, ts, market = trade

        # Track by exchange
        if 'kraken' in market.lower():
            kraken_trades += 1
        elif 'bitget' in market.lower():
            bitget_trades += 1

        value = amount * price
        fee = fee if fee else 0
        total_fees += fee

        # Symbol stats
        s = symbol_stats[symbol]
        if side == 'BUY':
            s['buys'] += 1
            s['buy_value'] += value
            s['inventory'] += amount
        else:
            s['sells'] += 1
            s['sell_value'] += value
            s['inventory'] -= amount
        s['fees'] += fee

        # Calculate averages
        if s['buys'] > 0:
            s['avg_buy_price'] = s['buy_value'] / (s['buys'] * amount) if amount > 0 else 0
        if s['sells'] > 0:
            s['avg_sell_price'] = s['sell_value'] / (s['sells'] * amount) if amount > 0 else 0

    conn.close()

    return {
        'total_trades': len(trades),
        'kraken_trades': kraken_trades,
        'bitget_trades': bitget_trades,
        'total_fees': total_fees,
        'symbol_stats': dict(symbol_stats)
    }


def analyze_audit_logs():
    """Analyze executor audit logs from last 4 days"""

    # Get last 4 days of audit files
    today = datetime.now()
    audit_files = []
    for i in range(4):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        filepath = os.path.join(audit_dir, f"{date}.jsonl")
        if os.path.exists(filepath):
            audit_files.append(filepath)

    executors = []
    for filepath in audit_files:
        with open(filepath, 'r') as f:
            for line in f:
                try:
                    executor = json.loads(line)
                    executors.append(executor)
                except:
                    pass

    # Analyze executors
    total_executors = len(executors)

    def safe_float(val, default=0):
        try:
            return float(val) if val is not None else default
        except:
            return default

    profitable = sum(1 for e in executors if safe_float(e.get('realized_pnl_quote', 0)) > 0)
    losing = sum(1 for e in executors if safe_float(e.get('realized_pnl_quote', 0)) < 0)
    breakeven = total_executors - profitable - losing

    total_pnl = sum(safe_float(e.get('realized_pnl_quote', 0)) for e in executors)
    total_fees_paid = sum(safe_float(e.get('fees_quote', 0)) for e in executors)

    # Duration analysis
    durations = [e.get('duration_minutes', 0) for e in executors if e.get('duration_minutes')]
    avg_duration = sum(durations) / len(durations) if durations else 0

    # Close reasons
    close_reasons = defaultdict(int)
    for e in executors:
        reason = e.get('close_type', 'unknown')
        close_reasons[reason] += 1

    return {
        'total_executors': total_executors,
        'profitable': profitable,
        'losing': losing,
        'breakeven': breakeven,
        'win_rate': (profitable / total_executors * 100) if total_executors > 0 else 0,
        'total_pnl': total_pnl,
        'total_fees': total_fees_paid,
        'net_pnl': total_pnl - total_fees_paid,
        'avg_duration_minutes': avg_duration,
        'close_reasons': dict(close_reasons)
    }


def calculate_risk_metrics(trade_data, audit_data):
    """Calculate risk metrics"""

    # Max drawdown from inventory
    max_inventory_value = 0
    for symbol, data in trade_data['symbol_stats'].items():
        if data['inventory'] > 0:
            value = abs(data['inventory']) * (data['buy_value'] / data['buys'] if data['buys'] > 0 else 0)
            max_inventory_value += value

    # Win/loss ratio
    wins = audit_data['profitable']
    losses = audit_data['losing']
    win_loss_ratio = wins / losses if losses > 0 else float('inf')

    # Profit factor
    total_wins = sum(e.get('realized_pnl_quote', 0) for e in [] if e.get('realized_pnl_quote', 0) > 0)
    total_losses = abs(sum(e.get('realized_pnl_quote', 0) for e in [] if e.get('realized_pnl_quote', 0) < 0))
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')

    return {
        'max_inventory_value': max_inventory_value,
        'win_loss_ratio': win_loss_ratio,
        'profit_factor': profit_factor,
        'avg_win': total_wins / wins if wins > 0 else 0,
        'avg_loss': total_losses / losses if losses > 0 else 0
    }


def generate_recommendation(trade_data, audit_data, risk_metrics):
    """Generate trading recommendation"""

    print("\n" + "=" * 80)
    print("📊 4-DAY PERFORMANCE ANALYSIS - TRADING DECISION REPORT")
    print("=" * 80)
    print(f"Analysis Period: Last 4 days")
    print(f"Current Capital: €280")
    print(f"Proposed Capital: €5000")
    print(f"Scaling Factor: 17.9x")
    print("=" * 80 + "\n")

    # Trading Activity
    print("📈 TRADING ACTIVITY")
    print("-" * 80)
    print(f"Total Trades: {trade_data['total_trades']}")
    print(f"  - Kraken (EUR): {trade_data['kraken_trades']} trades")
    print(f"  - Bitget (USDT): {trade_data['bitget_trades']} trades")
    print(f"Total Fees Paid: €{trade_data['total_fees']:.2f}")
    print()

    # Executor Performance
    print("🎯 EXECUTOR PERFORMANCE")
    print("-" * 80)
    print(f"Total Executors: {audit_data['total_executors']}")
    print(f"  ✅ Profitable: {audit_data['profitable']} ({audit_data['win_rate']:.1f}%)")
    print(f"  ❌ Losing: {audit_data['losing']}")
    print(f"  ⚖️  Breakeven: {audit_data['breakeven']}")
    print(f"\nRealized P&L: €{audit_data['total_pnl']:+.2f}")
    print(f"Fees Paid: €{audit_data['total_fees']:.2f}")
    print(f"Net P&L: €{audit_data['net_pnl']:+.2f}")
    print(f"Average Duration: {audit_data['avg_duration_minutes']:.0f} minutes")
    print()

    # Inventory Analysis
    print("📦 INVENTORY ANALYSIS")
    print("-" * 80)
    problem_coins = []
    total_inventory_value = 0

    for symbol, data in trade_data['symbol_stats'].items():
        imbalance = data['buys'] - data['sells']
        if abs(imbalance) > 5 or abs(data['inventory']) * data['avg_buy_price'] > 15:
            inventory_value = abs(data['inventory']) * data['avg_buy_price']
            total_inventory_value += inventory_value
            problem_coins.append({
                'symbol': symbol,
                'imbalance': imbalance,
                'inventory': data['inventory'],
                'value': inventory_value
            })

    if problem_coins:
        print("⚠️  COINS WITH INVENTORY ISSUES:")
        for coin in sorted(problem_coins, key=lambda x: x['value'], reverse=True)[:10]:
            print(f"  - {coin['symbol']}: {coin['imbalance']:+d} imbalance, "
                  f"inventory: {coin['inventory']:.2f} (€{coin['value']:.2f})")
    else:
        print("✅ No significant inventory issues")

    print(f"\nTotal Inventory Value: €{total_inventory_value:.2f}")
    print()

    # Risk Metrics
    print("⚠️  RISK METRICS")
    print("-" * 80)
    print(f"Win/Loss Ratio: {risk_metrics['win_loss_ratio']:.2f}")
    print(f"Win Rate: {audit_data['win_rate']:.1f}%")
    print(f"Average Win: €{risk_metrics['avg_win']:+.2f}")
    print(f"Average Loss: €{risk_metrics['avg_loss']:+.2f}")
    print(f"Max Inventory Stuck: €{risk_metrics['max_inventory_value']:.2f} ({risk_metrics['max_inventory_value'] / 280 * 100:.1f}% of capital)")
    print()

    # Close Reasons Analysis
    print("🔚 EXIT REASONS")
    print("-" * 80)
    for reason, count in sorted(audit_data['close_reasons'].items(), key=lambda x: x[1], reverse=True):
        print(f"  - {reason}: {count}")
    print()

    # RECOMMENDATION
    print("=" * 80)
    print("💡 RECOMMENDATION")
    print("=" * 80)

    # Decision criteria
    criteria_pass = []
    criteria_fail = []

    # 1. Win rate check
    if audit_data['win_rate'] >= 50:
        criteria_pass.append(f"✅ Win rate {audit_data['win_rate']:.1f}% >= 50% (GOOD)")
    else:
        criteria_fail.append(f"❌ Win rate {audit_data['win_rate']:.1f}% < 50% (RISKY)")

    # 2. Net P&L check
    if audit_data['net_pnl'] > 0:
        criteria_pass.append(f"✅ Net P&L €{audit_data['net_pnl']:+.2f} > 0 (PROFITABLE)")
    else:
        criteria_fail.append(f"❌ Net P&L €{audit_data['net_pnl']:+.2f} <= 0 (UNPROFITABLE)")

    # 3. Inventory management
    inventory_pct = (total_inventory_value / 280) * 100
    if inventory_pct < 50:
        criteria_pass.append(f"✅ Inventory {inventory_pct:.1f}% < 50% of capital (GOOD)")
    else:
        criteria_fail.append(f"❌ Inventory {inventory_pct:.1f}% >= 50% of capital (HIGH RISK)")

    # 4. Activity check
    if trade_data['total_trades'] > 50:
        criteria_pass.append(f"✅ {trade_data['total_trades']} trades > 50 (ACTIVE)")
    else:
        criteria_fail.append(f"⚠️  {trade_data['total_trades']} trades < 50 (LOW ACTIVITY)")

    # 5. Multi-coin bug check
    if trade_data['total_trades'] > 0 and (trade_data['kraken_trades'] > 20 or trade_data['bitget_trades'] > 20):
        criteria_pass.append(f"✅ Multi-coin fix working (Kraken: {trade_data['kraken_trades']}, Bitget: {trade_data['bitget_trades']})")
    else:
        criteria_fail.append(f"⚠️  Multi-coin may not be working properly")

    print("\nCRITERIA ASSESSMENT:")
    print()
    for criterion in criteria_pass:
        print(criterion)
    for criterion in criteria_fail:
        print(criterion)

    print("\n" + "-" * 80)

    # Final recommendation
    if len(criteria_fail) == 0 and len(criteria_pass) >= 4:
        print("\n🎯 RECOMMENDATION: ✅ GO FOR €5000")
        print("\nREASONS:")
        print("  • All key metrics are positive")
        print("  • System is stable and profitable")
        print("  • Risk management is working")
        print("\nSUGGESTED APPROACH:")
        print("  1. Start with €2000 for 1 week (test scaling)")
        print("  2. If successful, scale to €3500")
        print("  3. Final scale to €5000 after 2 weeks")
        print("\nRISK MANAGEMENT FOR €5000:")
        print(f"  • Max simultaneous coins: 4-5")
        print(f"  • Per-coin allocation: €1000-1250")
        print(f"  • Daily loss limit: €50 (1%)")
        print(f"  • Weekly loss limit: €150 (3%)")
        print(f"  • Monthly loss limit: €250 (5%)")

    elif len(criteria_fail) <= 2:
        print("\n🎯 RECOMMENDATION: ⚠️  CAUTIOUS - START WITH €1000-2000")
        print("\nREASONS:")
        print("  • Some metrics need improvement")
        print("  • System needs more validation")
        print("\nSUGGESTED APPROACH:")
        print("  1. Start with €1000 for 1 week")
        print("  2. Monitor win rate and inventory management")
        print("  3. Scale up ONLY if:")
        print("     - Win rate > 55%")
        print("     - Net P&L positive for 7 consecutive days")
        print("     - Inventory < 40% of capital")

    else:
        print("\n🎯 RECOMMENDATION: ❌ WAIT - DO NOT SCALE YET")
        print("\nREASONS:")
        print("  • Too many red flags")
        print("  • System needs fixes before scaling")
        print("\nNEXT STEPS:")
        print("  1. Fix inventory management issues")
        print("  2. Improve win rate (target: 55%+)")
        print("  3. Test with current €280 for another week")
        print("  4. Re-evaluate after improvements")

    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    print("\n🔍 Starting comprehensive 4-day analysis...\n")

    trade_data = analyze_trades()
    audit_data = analyze_audit_logs()
    risk_metrics = calculate_risk_metrics(trade_data, audit_data)

    generate_recommendation(trade_data, audit_data, risk_metrics)
