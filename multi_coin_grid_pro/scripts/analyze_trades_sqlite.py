#!/usr/bin/env python3
"""
Uitgebreide Trade Analyse vanuit SQLite Database
Analyseert TradeFill records voor eerste en laatste koop
"""

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def format_price(price: float) -> str:
    """Format price with appropriate decimals"""
    if price >= 1000:
        return f"€{price:,.2f}"
    elif price >= 1:
        return f"€{price:.4f}"
    else:
        return f"€{price:.6f}"


def format_timestamp(ts: int) -> str:
    """Convert timestamp (milliseconds) to readable format"""
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return str(ts)


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


def analyze_trades_from_sqlite(hours: int = 8):
    """Analyze trades from SQLite database"""

    print(f"\n{'=' * 90}")
    print(f"  UITGEBREIDE TRADE ANALYSE - LAATSTE {hours} UUR")
    print(f"{'=' * 90}\n")

    # Connect to database
    db_path = Path(__file__).parent.parent.parent / "data" / "multi_coin_grid_v2.sqlite"

    if not db_path.exists():
        print(f"❌ Database niet gevonden: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Calculate time threshold (in milliseconds)
    time_threshold_ms = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)

    # Query TradeFill records
    cursor.execute("""
        SELECT * FROM TradeFill
        WHERE config_file_path LIKE '%multi_coin_grid_v2%'
        AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (time_threshold_ms,))

    rows = cursor.fetchall()

    if not rows:
        print("⚠️  Geen trades gevonden in de laatste 8 uur.")
        conn.close()
        return

    # Convert to list of dicts
    trades = []
    for row in rows:
        trade = dict(row)
        # Convert price and amount from stored format (might be integers representing decimals)
        # Hummingbot stores prices as integers (multiplied by 1000000)
        try:
            price = float(trade['price']) / 1000000 if trade['price'] > 1000 else float(trade['price'])
            amount = float(trade['amount']) / 1000000 if trade['amount'] > 1000 else float(trade['amount'])
        except Exception:
            price = float(trade['price'])
            amount = float(trade['amount'])

        trade['price'] = price
        trade['amount'] = amount
        # Fee parsing - might be stored as integer (multiplied) or already as decimal
        fee_raw = trade.get('trade_fee_in_quote', 0) or 0
        try:
            fee_float = float(fee_raw)
            # If fee seems too large (>1000), it might be stored as integer (multiplied by 1000000)
            if fee_float > 1000:
                fee_float = fee_float / 1000000
            trade['fee'] = fee_float
        except Exception:
            trade['fee'] = 0.0
        trades.append(trade)

    print("📊 TOTAAL OVERZICHT")
    print(f"   Totaal aantal trades: {len(trades)}")
    print(f"   Periode: {format_timestamp(trades[0]['timestamp'])} tot {format_timestamp(trades[-1]['timestamp'])}")
    print()

    # Separate buys and sells
    buys = [t for t in trades if t['trade_type'] == 'BUY']
    sells = [t for t in trades if t['trade_type'] == 'SELL']

    print(f"   Buys: {len(buys)}")
    print(f"   Sells: {len(sells)}")
    print()

    # Analyze by coin
    coin_trades = defaultdict(lambda: {'buys': [], 'sells': []})

    for trade in trades:
        coin_trades[trade['symbol']]['buys' if trade['trade_type'] == 'BUY' else 'sells'].append(trade)

    # Find first and last trades
    first_trade = trades[0]
    last_trade = trades[-1]

    print(f"{'=' * 90}")
    print("  EERSTE TRADE ANALYSE")
    print(f"{'=' * 90}\n")

    print(f"🪙 Coin: {first_trade['symbol']}")
    print(f"📅 Tijdstip: {format_timestamp(first_trade['timestamp'])}")
    print(f"📊 Type: {first_trade['trade_type']}")
    print(f"💰 Prijs: {format_price(first_trade['price'])}")
    print(f"📦 Hoeveelheid: {first_trade['amount']:.6f} {first_trade['base_asset']}")
    print(f"💵 Totale waarde: {format_price(first_trade['price'] * first_trade['amount'])}")
    print(f"💳 Order Type: {first_trade['order_type']}")
    print(f"💸 Fee: {format_price(first_trade['fee'])}")
    print(f"🆔 Order ID: {first_trade['order_id']}")
    print(f"🆔 Exchange Order ID: {first_trade['exchange_trade_id']}")

    # Find first buy
    first_buy = buys[0] if buys else None
    if first_buy:
        print("\n💰 EERSTE KOOP:")
        print(f"   Coin: {first_buy['symbol']}")
        print(f"   Tijdstip: {format_timestamp(first_buy['timestamp'])}")
        print(f"   Prijs: {format_price(first_buy['price'])}")
        print(f"   Hoeveelheid: {first_buy['amount']:.6f} {first_buy['base_asset']}")
        print(f"   Totale waarde: {format_price(first_buy['price'] * first_buy['amount'])}")
        print(f"   Fee: {format_price(first_buy['fee'])}")
        print(f"   Order Type: {first_buy['order_type']}")

    print(f"\n{'=' * 90}")
    print("  LAATSTE TRADE ANALYSE")
    print(f"{'=' * 90}\n")

    print(f"🪙 Coin: {last_trade['symbol']}")
    print(f"📅 Tijdstip: {format_timestamp(last_trade['timestamp'])}")
    print(f"📊 Type: {last_trade['trade_type']}")
    print(f"💰 Prijs: {format_price(last_trade['price'])}")
    print(f"📦 Hoeveelheid: {last_trade['amount']:.6f} {last_trade['base_asset']}")
    print(f"💵 Totale waarde: {format_price(last_trade['price'] * last_trade['amount'])}")
    print(f"💳 Order Type: {last_trade['order_type']}")
    print(f"💸 Fee: {format_price(last_trade['fee'])}")
    print(f"🆔 Order ID: {last_trade['order_id']}")
    print(f"🆔 Exchange Order ID: {last_trade['exchange_trade_id']}")

    # Find last sell
    last_sell = sells[-1] if sells else None
    if last_sell:
        print("\n💸 LAATSTE VERKOOP:")
        print(f"   Coin: {last_sell['symbol']}")
        print(f"   Tijdstip: {format_timestamp(last_sell['timestamp'])}")
        print(f"   Prijs: {format_price(last_sell['price'])}")
        print(f"   Hoeveelheid: {last_sell['amount']:.6f} {last_sell['base_asset']}")
        print(f"   Totale waarde: {format_price(last_sell['price'] * last_sell['amount'])}")
        print(f"   Fee: {format_price(last_sell['fee'])}")
        print(f"   Order Type: {last_sell['order_type']}")

    # Analyze GIGA-EUR specifically
    if 'GIGA-EUR' in coin_trades:
        print(f"\n{'=' * 90}")
        print("  GIGA-EUR GEDETAILLEERDE ANALYSE")
        print(f"{'=' * 90}\n")

        giga_buys = coin_trades['GIGA-EUR']['buys']
        giga_sells = coin_trades['GIGA-EUR']['sells']

        print("📊 GIGA-EUR STATISTIEKEN:")
        print(f"   Totaal buys: {len(giga_buys)}")
        print(f"   Totaal sells: {len(giga_sells)}")
        print()

        if giga_buys:
            first_giga_buy = giga_buys[0]
            print("💰 EERSTE GIGA-EUR KOOP:")
            print(f"   Tijdstip: {format_timestamp(first_giga_buy['timestamp'])}")
            print(f"   Prijs: {format_price(first_giga_buy['price'])}")
            print(f"   Hoeveelheid: {first_giga_buy['amount']:.6f} GIGA")
            print(f"   Totale waarde: {format_price(first_giga_buy['price'] * first_giga_buy['amount'])}")
            print(f"   Fee: {format_price(first_giga_buy['fee'])}")
            print(f"   Order Type: {first_giga_buy['order_type']}")
            print()

        if giga_sells:
            last_giga_sell = giga_sells[-1]
            print("💸 LAATSTE GIGA-EUR VERKOOP:")
            print(f"   Tijdstip: {format_timestamp(last_giga_sell['timestamp'])}")
            print(f"   Prijs: {format_price(last_giga_sell['price'])}")
            print(f"   Hoeveelheid: {last_giga_sell['amount']:.6f} GIGA")
            print(f"   Totale waarde: {format_price(last_giga_sell['price'] * last_giga_sell['amount'])}")
            print(f"   Fee: {format_price(last_giga_sell['fee'])}")
            print(f"   Order Type: {last_giga_sell['order_type']}")
            print()

        # Calculate totals
        if giga_buys and giga_sells:
            total_buy_amount = sum(b['amount'] for b in giga_buys)
            total_sell_amount = sum(s['amount'] for s in giga_sells)
            total_buy_value = sum(b['price'] * b['amount'] for b in giga_buys)
            total_sell_value = sum(s['price'] * s['amount'] for s in giga_sells)
            total_buy_fees = sum(b['fee'] for b in giga_buys)
            total_sell_fees = sum(s['fee'] for s in giga_sells)
            total_fees = total_buy_fees + total_sell_fees

            # Calculate average prices
            avg_buy_price = total_buy_value / total_buy_amount if total_buy_amount > 0 else 0
            avg_sell_price = total_sell_value / total_sell_amount if total_sell_amount > 0 else 0

            print("📈 GIGA-EUR PRIJS ANALYSE:")
            print(f"   Eerste koop prijs: {format_price(giga_buys[0]['price'])}")
            print(f"   Laatste verkoop prijs: {format_price(giga_sells[-1]['price'])}")
            print(f"   Gemiddelde koop prijs: {format_price(avg_buy_price)}")
            print(f"   Gemiddelde verkoop prijs: {format_price(avg_sell_price)}")

            all_prices = [t['price'] for t in giga_buys + giga_sells]
            min_price = min(all_prices)
            max_price = max(all_prices)
            print(f"   Min prijs: {format_price(min_price)}")
            print(f"   Max prijs: {format_price(max_price)}")

            if avg_buy_price > 0:
                total_change = ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
                price_change_first_last = ((giga_sells[-1]['price'] - giga_buys[0]
                                           ['price']) / giga_buys[0]['price']) * 100
                print(f"   Totale prijs verandering (gemiddeld): {total_change:+.2f}%")
                print(f"   Prijs verandering (eerste koop → laatste verkoop): {price_change_first_last:+.2f}%")

            # Calculate profit
            total_profit = total_sell_value - total_buy_value
            net_profit = total_profit - total_fees

            print("\n💰 GIGA-EUR FINANCIEEL OVERZICHT:")
            print(f"   Totaal gekocht: {format_price(total_buy_value)} ({total_buy_amount:.2f} GIGA)")
            print(f"   Totaal verkocht: {format_price(total_sell_value)} ({total_sell_amount:.2f} GIGA)")
            print(f"   Bruto profit: {format_price(total_profit)}")
            print(f"   Totaal fees: {format_price(total_fees)}")
            print(f"   Netto profit: {format_price(net_profit)}")

            if total_buy_value > 0:
                roi = (net_profit / total_buy_value) * 100
                print(f"   ROI: {roi:+.2f}%")

            # Show all buy-sell pairs
            print("\n📋 GIGA-EUR TRADE DETAILS:")
            print("   Alle buys:")
            for i, buy in enumerate(giga_buys[:10], 1):  # Show first 10
                print(
                    f"   {i}. {
                        format_timestamp(
                            buy['timestamp'])} - {
                        format_price(
                            buy['price'])} - {
                        buy['amount']:.2f} GIGA - {
                            format_price(
                                buy['price']
                                * buy['amount'])}")
            if len(giga_buys) > 10:
                print(f"   ... en {len(giga_buys) - 10} meer buys")

            print("\n   Alle sells:")
            for i, sell in enumerate(giga_sells[:10], 1):  # Show first 10
                print(
                    f"   {i}. {
                        format_timestamp(
                            sell['timestamp'])} - {
                        format_price(
                            sell['price'])} - {
                        sell['amount']:.2f} GIGA - {
                            format_price(
                                sell['price']
                                * sell['amount'])}")
            if len(giga_sells) > 10:
                print(f"   ... en {len(giga_sells) - 10} meer sells")

    # Analyze all coins
    print(f"\n{'=' * 90}")
    print("  ALLE COINS ANALYSE")
    print(f"{'=' * 90}\n")

    for coin in sorted(coin_trades.keys()):
        buys = coin_trades[coin]['buys']
        sells = coin_trades[coin]['sells']

        if not buys and not sells:
            continue

        print(f"🪙 {coin}")
        print(f"   Buys: {len(buys)}, Sells: {len(sells)}")

        if buys:
            first_buy = buys[0]
            last_buy = buys[-1]
            total_buy_value = sum(b['price'] * b['amount'] for b in buys)
            print(f"   Eerste koop: {format_timestamp(first_buy['timestamp'])} @ {format_price(first_buy['price'])}")
            print(f"   Laatste koop: {format_timestamp(last_buy['timestamp'])} @ {format_price(last_buy['price'])}")
            print(f"   Totaal gekocht: {format_price(total_buy_value)}")

        if sells:
            first_sell = sells[0]
            last_sell = sells[-1]
            total_sell_value = sum(s['price'] * s['amount'] for s in sells)
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
            print(f"   Totaal verkocht: {format_price(total_sell_value)}")

        if buys and sells:
            total_buy_value = sum(b['price'] * b['amount'] for b in buys)
            total_sell_value = sum(s['price'] * s['amount'] for s in sells)
            total_fees = sum(b['fee'] for b in buys) + sum(s['fee'] for s in sells)
            net_profit = total_sell_value - total_buy_value - total_fees

            print(f"   Netto profit: {format_price(net_profit)}")
            if total_buy_value > 0:
                roi = (net_profit / total_buy_value) * 100
                print(f"   ROI: {roi:+.2f}%")

        print()

    # Overall statistics
    print(f"{'=' * 90}")
    print("  TOTALE STATISTIEKEN")
    print(f"{'=' * 90}\n")

    total_buy_value = sum(t['price'] * t['amount'] for t in buys)
    total_sell_value = sum(t['price'] * t['amount'] for t in sells)
    total_fees = sum(t['fee'] for t in trades)
    net_profit = total_sell_value - total_buy_value - total_fees

    print(f"💰 Totaal gekocht: {format_price(total_buy_value)}")
    print(f"💰 Totaal verkocht: {format_price(total_sell_value)}")
    print(f"💸 Totaal fees: {format_price(total_fees)}")
    print(f"📈 Netto profit: {format_price(net_profit)}")

    if total_buy_value > 0:
        roi = (net_profit / total_buy_value) * 100
        print(f"📊 ROI: {roi:+.2f}%")

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Analyze trades from SQLite database')
    parser.add_argument('--hours', type=int, default=8, help='Number of hours to analyze (default: 8)')

    args = parser.parse_args()
    analyze_trades_from_sqlite(hours=args.hours)
