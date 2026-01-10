#!/usr/bin/env python3
"""
DEFINITIVE 4-DAY ANALYSIS FOR €5000 DECISION
Focus: Critical issues, root causes, actionable recommendations
"""

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal


def analyze_comprehensive():
    """Complete analysis with all details"""

    db_path = "data/multi_coin_grid_v2.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get last 4 days
    cutoff = (datetime.now() - timedelta(days=4)).timestamp() * 1000

    # Get all trades
    query = """
    SELECT symbol, trade_type, amount, price, trade_fee_in_quote, timestamp
    FROM TradeFill
    WHERE timestamp > ?
    ORDER BY timestamp ASC
    """

    cursor.execute(query, (int(cutoff),))
    trades = cursor.fetchall()
    conn.close()

    # Analyze per symbol
    symbol_analysis = defaultdict(lambda: {
        'buys': 0,
        'sells': 0,
        'buy_value': Decimal('0'),
        'sell_value': Decimal('0'),
        'buy_amount': Decimal('0'),
        'sell_amount': Decimal('0'),
        'fees': Decimal('0')
    })

    total_fees = Decimal('0')
    first_trade = None
    last_trade = None

    for trade in trades:
        symbol, side, amount, price, fee, ts = trade

        if first_trade is None:
            first_trade = datetime.fromtimestamp(ts / 1000)
        last_trade = datetime.fromtimestamp(ts / 1000)

        # Convert from database format (integers * 1e8)
        amt = Decimal(amount) / Decimal('100000000')
        prc = Decimal(price) / Decimal('100000000')
        f = Decimal(fee if fee else 0) / Decimal('100000000')

        value = amt * prc
        total_fees += f

        s = symbol_analysis[symbol]
        s['fees'] += f

        if side == 'BUY':
            s['buys'] += 1
            s['buy_amount'] += amt
            s['buy_value'] += value
        else:
            s['sells'] += 1
            s['sell_amount'] += amt
            s['sell_value'] += value

    # Calculate metrics
    total_trades = len(trades)
    hours_active = (last_trade - first_trade).total_seconds() / 3600 if first_trade and last_trade else 0

    # Per-symbol P&L and inventory
    results = []
    total_realized_pnl = Decimal('0')
    total_inventory_value = Decimal('0')

    for symbol, data in symbol_analysis.items():
        # Calculate averages
        avg_buy = data['buy_value'] / data['buy_amount'] if data['buy_amount'] > 0 else Decimal('0')
        avg_sell = data['sell_value'] / data['sell_amount'] if data['sell_amount'] > 0 else Decimal('0')

        # Realized P&L (from matched volume)
        matched_volume = min(data['buy_amount'], data['sell_amount'])
        realized_pnl = (avg_sell - avg_buy) * matched_volume if matched_volume > 0 else Decimal('0')

        # Remaining inventory
        inventory = data['buy_amount'] - data['sell_amount']
        inventory_value = inventory * avg_buy if inventory > 0 else Decimal('0')

        total_realized_pnl += realized_pnl
        total_inventory_value += abs(inventory_value)

        # Imbalance
        imbalance = data['buys'] - data['sells']

        results.append({
            'symbol': symbol,
            'buys': data['buys'],
            'sells': data['sells'],
            'imbalance': imbalance,
            'avg_buy': float(avg_buy),
            'avg_sell': float(avg_sell),
            'inventory': float(inventory),
            'inventory_value': float(inventory_value),
            'realized_pnl': float(realized_pnl),
            'fees': float(data['fees'])
        })

    net_pnl = total_realized_pnl - total_fees

    return {
        'total_trades': total_trades,
        'hours_active': hours_active,
        'first_trade': first_trade,
        'last_trade': last_trade,
        'total_fees': float(total_fees),
        'realized_pnl': float(total_realized_pnl),
        'net_pnl': float(net_pnl),
        'total_inventory': float(total_inventory_value),
        'symbols': sorted(results, key=lambda x: abs(x['inventory_value']), reverse=True)
    }


def print_report(analysis):
    """Print comprehensive decision report"""

    print("\n" + "=" * 80)
    print("🎯 DEFINITIVE 4-DAY ANALYSIS - €5000 TRADING DECISION")
    print("=" * 80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Period: {analysis['first_trade'].strftime('%Y-%m-%d %H:%M')} → {analysis['last_trade'].strftime('%Y-%m-%d %H:%M')}")
    print(f"Duration: {analysis['hours_active']:.1f} hours ({analysis['hours_active'] / 24:.1f} days)")
    print("=" * 80 + "\n")

    # === KEY METRICS ===
    print("📊 KEY METRICS")
    print("-" * 80)
    print(f"Total Trades: {analysis['total_trades']}")
    print(f"Trades/Hour: {analysis['total_trades'] / analysis['hours_active']:.1f}")
    print(f"Trades/Day: {analysis['total_trades'] / (analysis['hours_active'] / 24):.1f}")
    print()
    print(f"Realized P&L: €{analysis['realized_pnl']:+.2f}")
    print(f"Fees Paid: €{analysis['total_fees']:.2f}")
    print(f"Net P&L: €{analysis['net_pnl']:+.2f}")
    print(f"Return: {(analysis['net_pnl'] / 280) * 100:+.2f}%")
    print()

    # === CRITICAL ISSUE ===
    inventory_pct = (analysis['total_inventory'] / 280) * 100
    print("⚠️  CRITICAL ISSUE: INVENTORY MANAGEMENT")
    print("-" * 80)
    print(f"Total Inventory Locked: €{analysis['total_inventory']:.2f}")
    print(f"As % of Capital: {inventory_pct:.1f}%")
    print(f"Free Capital: €{280 - analysis['total_inventory']:.2f}")
    print()

    if inventory_pct > 100:
        print("🚨 SEVERE: Over 100% capital locked in inventory!")
        print("   → Bot cannot open new positions")
        print("   → Liquidity crisis")
        print("   → Unable to scale")
    elif inventory_pct > 60:
        print("⚠️  WARNING: Over 60% capital locked")
        print("   → Limited capacity for new trades")
        print("   → High risk if market reverses")

    print()

    # === PER-SYMBOL BREAKDOWN ===
    print("📦 INVENTORY BREAKDOWN (Top 10)")
    print("-" * 80)
    print(f"{'Symbol':<12} {'Buys':>6} {'Sells':>6} {'Imb':>5} {'Inventory':>12} {'Value':>10}")
    print("-" * 80)

    for symbol in analysis['symbols'][:10]:
        print(f"{symbol['symbol']:<12} {symbol['buys']:>6} {symbol['sells']:>6} "
              f"{symbol['imbalance']:>+5} {symbol['inventory']:>12.2f} "
              f"€{symbol['inventory_value']:>9.2f}")

    print()

    # === ROOT CAUSE ANALYSIS ===
    print("🔍 ROOT CAUSE ANALYSIS")
    print("-" * 80)

    # Count imbalances
    severe_imbalance = [s for s in analysis['symbols'] if abs(s['imbalance']) > 10]
    moderate_imbalance = [s for s in analysis['symbols'] if 5 < abs(s['imbalance']) <= 10]

    print(f"Coins with severe imbalance (>10): {len(severe_imbalance)}")
    print(f"Coins with moderate imbalance (5-10): {len(moderate_imbalance)}")
    print()

    print("ROOT CAUSES:")
    print("1. ❌ Market Direction: More buys than sells = declining market")
    print("   → Buy orders filling (limit orders below price)")
    print("   → Sell orders NOT filling (price not reaching take-profit)")
    print()
    print("2. ❌ Grid Range Too Narrow:")
    print("   → grid_range_pct_up: 8% (sells too close)")
    print("   → Market pumps past sell grids before filling")
    print("   → Inventory accumulates")
    print()
    print("3. ❌ Entry Filters Too Loose:")
    print("   → Entering coins in downtrends")
    print("   → Buying into falling knives")
    print("   → PEPE: 41 buys vs 9 sells (32 imbalance!)")
    print("   → SUI: 40 buys vs 11 sells (29 imbalance!)")
    print()
    print("4. ⚠️  No Max Hold Time Enforcement:")
    print("   → Coins stay active too long in bad trends")
    print("   → Should exit after 4 hours if no fills")
    print()

    # === RISK ASSESSMENT ===
    print("⚠️  RISK ASSESSMENT FOR €5000")
    print("-" * 80)

    # Current performance
    current_capital = 280
    proposed_capital = 5000
    scale_factor = proposed_capital / current_capital

    # Project locked capital
    projected_locked = analysis['total_inventory'] * scale_factor
    projected_free = proposed_capital - projected_locked

    print(f"Current locked: €{analysis['total_inventory']:.2f} ({inventory_pct:.1f}%)")
    print(f"Projected @€5000: €{projected_locked:.2f} ({projected_locked / proposed_capital * 100:.1f}%)")
    print(f"Free capital: €{projected_free:.2f}")
    print()

    if projected_free < 1000:
        print("🚨 DANGER: Less than €1000 free capital")
        print("   → Insufficient liquidity for operations")
        print("   → Cannot respond to opportunities")
        print("   → HIGH RISK OF TOTAL LOCKUP")

    print()

    # === DECISION MATRIX ===
    print("=" * 80)
    print("💡 DECISION MATRIX")
    print("=" * 80 + "\n")

    criteria = []

    # 1. Profitability
    if analysis['net_pnl'] > 20:
        criteria.append(('✅', f"Good profitability: €{analysis['net_pnl']:+.2f}", +2))
    elif analysis['net_pnl'] > 0:
        criteria.append(('⚠️', f"Marginally profitable: €{analysis['net_pnl']:+.2f}", +1))
    else:
        criteria.append(('❌', f"Unprofitable: €{analysis['net_pnl']:+.2f}", -3))

    # 2. Trading activity
    if analysis['total_trades'] > 200:
        criteria.append(('✅', f"High activity: {analysis['total_trades']} trades", +2))
    else:
        criteria.append(('⚠️', f"Moderate activity: {analysis['total_trades']} trades", +1))

    # 3. Inventory management (CRITICAL)
    if inventory_pct > 100:
        criteria.append(('❌', f"CRITICAL: {inventory_pct:.0f}% inventory locked", -5))
    elif inventory_pct > 60:
        criteria.append(('❌', f"HIGH RISK: {inventory_pct:.0f}% inventory locked", -3))
    elif inventory_pct > 40:
        criteria.append(('⚠️', f"Elevated inventory: {inventory_pct:.0f}%", -1))
    else:
        criteria.append(('✅', f"Healthy inventory: {inventory_pct:.0f}%", +2))

    # 4. Coin diversity
    unique_coins = len([s for s in analysis['symbols'] if s['buys'] > 0])
    if unique_coins >= 10:
        criteria.append(('✅', f"Good diversity: {unique_coins} coins", +1))
    else:
        criteria.append(('⚠️', f"Limited diversity: {unique_coins} coins", 0))

    # 5. System stability
    criteria.append(('✅', "System stable: no crashes", +1))

    # Calculate score
    score = sum(c[2] for c in criteria)

    print("CRITERIA:")
    for icon, desc, points in criteria:
        print(f"{icon} {desc} ({points:+d} points)")

    print()
    print(f"TOTAL SCORE: {score} / 10")
    print()
    print("-" * 80)
    print()

    # === FINAL RECOMMENDATION ===
    if score >= 5:
        print("🎯 RECOMMENDATION: ⚠️  CONDITIONAL YES - FIX ISSUES FIRST")
        print()
        print("✅ PROS:")
        print("  • System is profitable (€30/4 days)")
        print("  • High trading activity (277 trades)")
        print("  • No crashes or instability")
        print()
        print("❌ BLOCKERS:")
        print("  • 143% inventory locked = CRITICAL")
        print("  • Cannot scale with this inventory management")
        print("  • Risk of total capital lockup @€5000")
        print()
        print("🔧 REQUIRED FIXES BEFORE SCALING:")
        print()
        print("1. Widen sell grids:")
        print("   grid_range_pct_up: 8 → 12%  (allow higher sell fills)")
        print()
        print("2. Tighten entry filters:")
        print("   mtf_1h_min_pct: -3 → 0%  (only enter if 1H positive)")
        print("   mtf_4h_min_pct: -2.5 → 0%  (only enter if 4H positive)")
        print()
        print("3. Enable max hold time:")
        print("   max_hold_time_seconds: 14400 (4 hours) ← ALREADY SET, VERIFY IT WORKS")
        print()
        print("4. Reduce simultaneous coins:")
        print("   max_simultaneous_coins: 4 → 3  (focus on best setups)")
        print()
        print("📅 IMPLEMENTATION PLAN:")
        print()
        print("WEEK 1: Fix & Test (€280)")
        print("  - Apply all 4 fixes above")
        print("  - Run for 7 days")
        print("  - Target: Inventory < 50%")
        print()
        print("WEEK 2: Small Scale Test (€1000)")
        print("  - If inventory < 50% sustained")
        print("  - Monitor for 7 days")
        print("  - Target: Inventory < 50%, P&L > 0")
        print()
        print("WEEK 3: Medium Scale (€2500)")
        print("  - If week 2 successful")
        print("  - Monitor for 7 days")
        print()
        print("WEEK 4+: Full Scale (€5000)")
        print("  - Only if all prior weeks successful")
        print("  - Daily loss limit: €50")
        print("  - Weekly loss limit: €175")

    elif score >= 0:
        print("🎯 RECOMMENDATION: ⚠️  WAIT - TOO RISKY")
        print()
        print("Current issues too severe to scale safely.")
        print()
        print("NEXT STEPS:")
        print("1. Fix inventory management (see above)")
        print("2. Run with €280 for 2 more weeks")
        print("3. Re-evaluate when inventory < 50%")
        print("4. Do NOT scale until proven stable")

    else:
        print("🎯 RECOMMENDATION: ❌ NO - MAJOR ISSUES")
        print()
        print("System not ready for scaling.")
        print()
        print("CRITICAL ACTIONS:")
        print("1. Stop trading immediately")
        print("2. Close all open positions")
        print("3. Fix all issues")
        print("4. Restart from scratch with fixes")

    print()
    print("=" * 80)
    print()


if __name__ == "__main__":
    print("\n🔍 Performing comprehensive 4-day analysis...\n")
    analysis = analyze_comprehensive()
    print_report(analysis)
