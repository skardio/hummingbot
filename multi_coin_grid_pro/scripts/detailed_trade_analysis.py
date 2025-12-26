#!/usr/bin/env python3
"""
Uitgebreide Trade Analyse - Eerste en Laatste Koop Analyse
"""

import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from multi_coin_grid_pro.monitoring.database import MonitoringDatabase

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def format_price(price: float) -> str:
    """Format price with appropriate decimals"""
    if price >= 1000:
        return f"€{price:,.2f}"
    elif price >= 1:
        return f"€{price:.4f}"
    else:
        return f"€{price:.6f}"


def format_timestamp(ts: str) -> str:
    """Format timestamp to readable format"""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return ts


def calculate_profit_loss(buy_price: float, sell_price: float, amount: float) -> tuple:
    """Calculate profit/loss from buy and sell"""
    if buy_price == 0 or sell_price == 0:
        return 0.0, 0.0, "N/A"

    profit_abs = (sell_price - buy_price) * amount
    profit_pct = ((sell_price - buy_price) / buy_price) * 100

    if profit_abs > 0:
        status = "Winst 📈"
    elif profit_abs < 0:
        status = "Verlies 📉"
    else:
        status = "Break-even ➡️"

    return profit_abs, profit_pct, status


def analyze_trades(hours: int = 8):
    """Analyze trades from last N hours"""

    print(f"\n{'=' * 90}")
    print(f"  UITGEBREIDE TRADE ANALYSE - LAATSTE {hours} UUR")
    print(f"{'=' * 90}\n")

    db = MonitoringDatabase()
    time_threshold = datetime.now() - timedelta(hours=hours)
    time_threshold_str = time_threshold.isoformat()

    cursor = db.conn.cursor()

    # Get all trades
    cursor.execute("""
        SELECT * FROM trades
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (time_threshold_str,))

    trades = [dict(row) for row in cursor.fetchall()]

    # Get status snapshots for context
    cursor.execute("""
        SELECT * FROM bot_status
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (time_threshold_str,))

    status_snapshots = [dict(row) for row in cursor.fetchall()]

    # Get events
    cursor.execute("""
        SELECT * FROM bot_events
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    """, (time_threshold_str,))

    events = [dict(row) for row in cursor.fetchall()]

    if not trades:
        print("⚠️  Geen trades gevonden in de laatste 8 uur.")
        db.close()
        return

    print("📊 TOTAAL OVERZICHT")
    print(f"   Totaal aantal trades: {len(trades)}")
    print(f"   Periode: {format_timestamp(trades[0]['timestamp'])} tot {format_timestamp(trades[-1]['timestamp'])}")
    print()

    # Analyze by coin
    coin_trades = defaultdict(lambda: {'buys': [], 'sells': [], 'pairs': []})

    for trade in trades:
        coin = trade['coin']
        if trade['side'] == 'buy':
            coin_trades[coin]['buys'].append(trade)
        else:
            coin_trades[coin]['sells'].append(trade)

    # Match buys and sells to create pairs
    for coin, data in coin_trades.items():
        buys = sorted(data['buys'], key=lambda x: x['timestamp'])
        sells = sorted(data['sells'], key=lambda x: x['timestamp'])

        # Simple matching: first buy with first sell, etc.
        for i, buy in enumerate(buys):
            if i < len(sells):
                sell = sells[i]
                data['pairs'].append({
                    'buy': buy,
                    'sell': sell,
                    'coin': coin
                })

    # Find first and last trades
    first_trade = trades[0]
    last_trade = trades[-1]

    print(f"{'=' * 90}")
    print("  EERSTE TRADE ANALYSE")
    print(f"{'=' * 90}\n")

    print(f"🪙 Coin: {first_trade['coin']}")
    print(f"📅 Tijdstip: {format_timestamp(first_trade['timestamp'])}")
    print(f"📊 Type: {first_trade['side'].upper()}")
    print(f"💰 Prijs: {format_price(first_trade['price'])}")
    print(f"📦 Hoeveelheid: {first_trade['amount']:.6f} {first_trade['coin'].split('-')[0]}")
    print(f"💵 Totale waarde: {format_price(first_trade['price'] * first_trade['amount'])}")
    if first_trade.get('pnl') is not None:
        pnl = first_trade['pnl']
        pnl_sign = "📈" if pnl >= 0 else "📉"
        print(f"📈 P&L: {pnl_sign} {format_price(pnl)}")

    # Find context around first trade
    print("\n📋 CONTEXT ROND EERSTE TRADE:")
    first_time = datetime.fromisoformat(first_trade['timestamp'].replace('Z', '+00:00'))

    # Find status before and after
    status_before = None
    status_after = None
    for status in status_snapshots:
        status_time = datetime.fromisoformat(status['timestamp'].replace('Z', '+00:00'))
        if status_time < first_time and (
            status_before is None or status_time > datetime.fromisoformat(
                status_before['timestamp'].replace(
                    'Z',
                '+00:00'))):
            status_before = status
        if status_time > first_time and status_after is None:
            status_after = status

    if status_before:
        print("   Status voor trade:")
        print(f"   - Actieve coin: {status_before.get('active_coin', 'N/A')}")
        print(f"   - P&L: {format_price(status_before.get('pnl', 0))}")
        print(f"   - Exposure: {format_price(status_before.get('exposure', 0))}")

    if status_after:
        print("   Status na trade:")
        print(f"   - Actieve coin: {status_after.get('active_coin', 'N/A')}")
        print(f"   - P&L: {format_price(status_after.get('pnl', 0))}")
        print(f"   - Exposure: {format_price(status_after.get('exposure', 0))}")

    # Find events around first trade
    events_around = []
    for event in events:
        event_time = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
        time_diff = abs((event_time - first_time).total_seconds())
        if time_diff < 300:  # Within 5 minutes
            events_around.append(event)

    if events_around:
        print("\n   Events rond eerste trade (±5 min):")
        for event in events_around[:5]:
            print(f"   - {format_timestamp(event['timestamp'])}: {event['event_type']} - {event['message'][:60]}")

    print(f"\n{'=' * 90}")
    print("  LAATSTE TRADE ANALYSE")
    print(f"{'=' * 90}\n")

    print(f"🪙 Coin: {last_trade['coin']}")
    print(f"📅 Tijdstip: {format_timestamp(last_trade['timestamp'])}")
    print(f"📊 Type: {last_trade['side'].upper()}")
    print(f"💰 Prijs: {format_price(last_trade['price'])}")
    print(f"📦 Hoeveelheid: {last_trade['amount']:.6f} {last_trade['coin'].split('-')[0]}")
    print(f"💵 Totale waarde: {format_price(last_trade['price'] * last_trade['amount'])}")
    if last_trade.get('pnl') is not None:
        pnl = last_trade['pnl']
        pnl_sign = "📈" if pnl >= 0 else "📉"
        print(f"📈 P&L: {pnl_sign} {format_price(pnl)}")

    # Find context around last trade
    print("\n📋 CONTEXT ROND LAATSTE TRADE:")
    last_time = datetime.fromisoformat(last_trade['timestamp'].replace('Z', '+00:00'))

    # Find latest status
    latest_status = status_snapshots[-1] if status_snapshots else None
    if latest_status:
        print("   Huidige status:")
        print(f"   - Actieve coin: {latest_status.get('active_coin', 'N/A')}")
        print(f"   - P&L: {format_price(latest_status.get('pnl', 0))}")
        print(f"   - Exposure: {format_price(latest_status.get('exposure', 0))}")
        print(f"   - Mode: {latest_status.get('mode', 'N/A')}")

    # Find events around last trade
    events_around_last = []
    for event in events:
        event_time = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
        time_diff = abs((event_time - last_time).total_seconds())
        if time_diff < 300:  # Within 5 minutes
            events_around_last.append(event)

    if events_around_last:
        print("\n   Events rond laatste trade (±5 min):")
        for event in events_around_last[:5]:
            print(f"   - {format_timestamp(event['timestamp'])}: {event['event_type']} - {event['message'][:60]}")

    # Analyze GIGA-EUR specifically
    if 'GIGA-EUR' in coin_trades:
        print(f"\n{'=' * 90}")
        print("  GIGA-EUR GEDETAILLEERDE ANALYSE")
        print(f"{'=' * 90}\n")

        giga_trades = coin_trades['GIGA-EUR']
        giga_buys = giga_trades['buys']
        giga_sells = giga_trades['sells']
        giga_pairs = giga_trades['pairs']

        print("📊 GIGA-EUR STATISTIEKEN:")
        print(f"   Totaal buys: {len(giga_buys)}")
        print(f"   Totaal sells: {len(giga_sells)}")
        print(f"   Gepaarde trades: {len(giga_pairs)}")
        print()

        if giga_buys:
            print("💰 EERSTE GIGA-EUR KOOP:")
            first_buy = giga_buys[0]
            print(f"   Tijdstip: {format_timestamp(first_buy['timestamp'])}")
            print(f"   Prijs: {format_price(first_buy['price'])}")
            print(f"   Hoeveelheid: {first_buy['amount']:.6f} GIGA")
            print(f"   Totale waarde: {format_price(first_buy['price'] * first_buy['amount'])}")
            print()

        if giga_sells:
            print("💸 LAATSTE GIGA-EUR VERKOOP:")
            last_sell = giga_sells[-1]
            print(f"   Tijdstip: {format_timestamp(last_sell['timestamp'])}")
            print(f"   Prijs: {format_price(last_sell['price'])}")
            print(f"   Hoeveelheid: {last_sell['amount']:.6f} GIGA")
            print(f"   Totale waarde: {format_price(last_sell['price'] * last_sell['amount'])}")
            print()

        if giga_pairs:
            print("📈 GIGA-EUR TRADE PAIRS:")
            total_profit = 0.0
            for i, pair in enumerate(giga_pairs, 1):
                buy = pair['buy']
                sell = pair['sell']
                profit_abs, profit_pct, status = calculate_profit_loss(
                    buy['price'], sell['price'], buy['amount']
                )
                total_profit += profit_abs

                print(f"\n   Pair {i}:")
                print(
                    f"   Koop:  {format_timestamp(buy['timestamp'])} @ {format_price(buy['price'])} - {buy['amount']:.6f} GIGA")  # noqa: E501
                print(
                    f"   Verkoop: {format_timestamp(sell['timestamp'])} @ {format_price(sell['price'])} - {sell['amount']:.6f} GIGA")  # noqa: E501
                print(f"   Resultaat: {status} {format_price(profit_abs)} ({profit_pct:+.2f}%)")

            print(f"\n   💰 TOTAAL GIGA-EUR PROFIT: {format_price(total_profit)}")

        # Price analysis
        if giga_buys and giga_sells:
            all_prices = [t['price'] for t in giga_buys + giga_sells]
            min_price = min(all_prices)
            max_price = max(all_prices)
            first_price = giga_buys[0]['price']
            last_price = giga_sells[-1]['price']

            print("\n📊 GIGA-EUR PRIJS ANALYSE:")
            print(f"   Eerste koop prijs: {format_price(first_price)}")
            print(f"   Laatste verkoop prijs: {format_price(last_price)}")
            print(f"   Min prijs: {format_price(min_price)}")
            print(f"   Max prijs: {format_price(max_price)}")

            if first_price > 0:
                total_change = ((last_price - first_price) / first_price) * 100
                print(f"   Totale prijs verandering: {total_change:+.2f}%")

    # Analyze all coins
    print(f"\n{'=' * 90}")
    print("  ALLE COINS ANALYSE")
    print(f"{'=' * 90}\n")

    for coin, data in sorted(coin_trades.items()):
        buys = data['buys']
        sells = data['sells']
        pairs = data['pairs']

        print(f"🪙 {coin}")
        print(f"   Buys: {len(buys)}, Sells: {len(sells)}, Pairs: {len(pairs)}")

        if buys:
            first_buy = buys[0]
            last_buy = buys[-1]
            print(f"   Eerste koop: {format_timestamp(first_buy['timestamp'])} @ {format_price(first_buy['price'])}")
            print(f"   Laatste koop: {format_timestamp(last_buy['timestamp'])} @ {format_price(last_buy['price'])}")

        if sells:
            first_sell = sells[0]
            last_sell = sells[-1]
            print(
                f"   Eerste verkoop: {
                    format_timestamp(
                        first_sell['timestamp'])} @ {
                    format_price(
                        first_sell['price'])}")
            print(
                f"   Laatste verkoop: {
                    format_timestamp(
                        last_sell['timestamp'])} @ {
                    format_price(
                        last_sell['price'])}")

        if pairs:
            total_profit = sum(
                calculate_profit_loss(p['buy']['price'], p['sell']['price'], p['buy']['amount'])[0]
                for p in pairs
            )
            print(f"   Totaal profit: {format_price(total_profit)}")

        print()

    # Overall statistics
    print(f"{'=' * 90}")
    print("  TOTALE STATISTIEKEN")
    print(f"{'=' * 90}\n")

    total_buy_value = sum(t['price'] * t['amount'] for t in trades if t['side'] == 'buy')
    total_sell_value = sum(t['price'] * t['amount'] for t in trades if t['side'] == 'sell')
    total_pnl = sum(t.get('pnl', 0) for t in trades)

    print(f"💰 Totaal gekocht: {format_price(total_buy_value)}")
    print(f"💰 Totaal verkocht: {format_price(total_sell_value)}")
    print(f"📈 Totaal P&L: {format_price(total_pnl)}")

    if total_buy_value > 0:
        roi = ((total_sell_value - total_buy_value) / total_buy_value) * 100
        print(f"📊 ROI: {roi:+.2f}%")

    db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Detailed trade analysis')
    parser.add_argument('--hours', type=int, default=8, help='Number of hours to analyze (default: 8)')

    args = parser.parse_args()
    analyze_trades(hours=args.hours)
