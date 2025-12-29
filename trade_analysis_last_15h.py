#!/usr/bin/env python3
"""
Trade Analysis Script - Laatste 15 uur
Analyseert alle trades met correcte prijzen uit de logs
"""


# Parse log files voor echte prijzen

def parse_log_prices(log_file):
    """Extract real prices from log files"""
    price_map = {}  # exchange_trade_id -> (price, amount, total)

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                # Zoek OrderFilledEvent
                if 'OrderFilledEvent' in line and 'exchange_trade_id' in line:
                    try:
                        # Extract JSON deel
                        json_start = line.find('{"timestamp"')
                        if json_start > 0:
                            import json
                            event_data = json.loads(line[json_start:])

                            trade_id = event_data.get('exchange_trade_id')
                            price = float(event_data.get('price', 0))
                            amount = float(event_data.get('amount', 0))

                            if trade_id and price > 0 and amount > 0:
                                total = price * amount
                                price_map[trade_id] = {
                                    'price': price,
                                    'amount': amount,
                                    'total': total,
                                    'trading_pair': event_data.get('trading_pair'),
                                    'trade_type': str(event_data.get('trade_type'))
                                }
                    except Exception:
    except FileNotFoundError:
        pass

    return price_map


def main():
    # Parse alle log files
    print("📖 Reading log files...")
    price_data = {}

    for log_file in [
        '/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2025-12-28-02-31-33.log',
        '/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2025-12-28-02-31-33.log.1',
        '/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2025-12-28-02-31-33.log.2',
    ]:
        log_prices = parse_log_prices(log_file)
        price_data.update(log_prices)

    print(f"✅ Found {len(price_data)} trades with real prices\\n")

    # Query database
    db_path = '/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff_time = (datetime.now() - timedelta(hours=15)).timestamp() * 1000

    cursor.execute('''
        SELECT timestamp, symbol, base_asset, quote_asset,
               order_id, trade_type, price, amount,
               trade_fee_in_quote, exchange_trade_id
        FROM TradeFill
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
    ''', (cutoff_time,))

    trades = cursor.fetchall()

    print('=' * 140)
    print('📊 ALLE TRADES LAATSTE 15 UUR - MET CORRECTE PRIJZEN UIT LOGS')
    print('=' * 140)
    print()

    # Group by symbol
    by_symbol = defaultdict(list)
    all_trades = []

    for trade in trades:
        ts, symbol, base, quote, order_id, trade_type, price_db, amount_db, fee_db, exchange_id = trade
        dt = datetime.fromtimestamp(ts / 1000)

        # Get real price from logs
        if exchange_id in price_data:
            price = price_data[exchange_id]['price']
            amount = price_data[exchange_id]['amount']
            total = price * amount
        else:
            # Fallback to database conversion (maar deze is FOUT voor PEPE!)
            if symbol == 'PEPE-EUR':
                price = price_db / 1e6  # Dit is vaak fout!
                amount = amount_db / 1e8
            elif symbol == 'TAO-EUR':
                price = price_db / 1e8
                amount = amount_db / 1e8
            else:
                price = price_db / 1e8
                amount = amount_db / 1e8
            total = price * amount

        fee_eur = fee_db / 1e8 if fee_db else 0

        trade_info = {
            'time': dt,
            'symbol': symbol,
            'base': base,
            'type': trade_type,
            'price': price,
            'amount': amount,
            'total': total,
            'fee': fee_eur,
            'order_id': order_id,
            'exchange_id': exchange_id,
            'has_log_data': exchange_id in price_data
        }

        by_symbol[symbol].append(trade_info)
        all_trades.append(trade_info)

    # Print per coin
    total_profit_eur = 0

    for symbol in sorted(by_symbol.keys()):
        symbol_trades = by_symbol[symbol]
        print(f'\\n🪙 {symbol}')
        print('-' * 140)

        buys = [t for t in symbol_trades if t['type'] == 'BUY']
        sells = [t for t in symbol_trades if t['type'] == 'SELL']

        for trade in symbol_trades:
            emoji = '🟢' if trade['type'] == 'BUY' else '🔴'
            source = '📖' if trade['has_log_data'] else '💾'

            if 'PEPE' in symbol:
                print(f"{emoji}{source} {trade['type']:4s} | {trade['time'].strftime('%d-%m %H:%M:%S')} | "
                      f"€{trade['price']:.9f} | {trade['amount']:,.0f} {trade['base']:4s} | "
                      f"Total: €{trade['total']:,.2f} | Fee: €{trade['fee']:.4f}")
            else:
                print(f"{emoji}{source} {trade['type']:4s} | {trade['time'].strftime('%d-%m %H:%M:%S')} | "
                      f"€{trade['price']:,.6f} | {trade['amount']:.6f} {trade['base']:4s} | "
                      f"Total: €{trade['total']:,.2f} | Fee: €{trade['fee']:.4f}")

        # Stats
        print()
        print(f'   📈 Total BUYS:  {len(buys)} trades')
        print(f'   📉 Total SELLS: {len(sells)} trades')

        if buys and sells:
            total_bought = sum(b['amount'] for b in buys)
            total_sold = sum(s['amount'] for s in sells)

            buy_value = sum(b['total'] + b['fee'] for b in buys)
            sell_value = sum(s['total'] - s['fee'] for s in sells)

            profit = sell_value - buy_value
            total_profit_eur += profit

            if 'PEPE' in symbol:
                print(f"   📊 Bought:   {total_bought:,.0f} {trade['base']}")
                print(f"   📊 Sold:     {total_sold:,.0f} {trade['base']}")
                diff = total_sold - total_bought
                diff_pct = (diff / total_bought * 100) if total_bought > 0 else 0
                print(f"   📊 Verschil: {diff:,.0f} {trade['base']} ({diff_pct:.4f}%)")
            else:
                print(f"   📊 Bought:   {total_bought:.6f} {trade['base']}")
                print(f"   📊 Sold:     {total_sold:.6f} {trade['base']}")
                diff = total_sold - total_bought
                print(f"   📊 Verschil: {diff:.6f} {trade['base']}")

            print(f'   💵 Buy Cost: €{buy_value:.4f} (incl fees)')
            print(f'   💵 Sell Rev: €{sell_value:.4f} (na fees)')

            if profit >= 0:
                profit_pct = (profit / buy_value * 100) if buy_value > 0 else 0
                print(f'   ✅ PROFIT: €{profit:.4f} ({profit_pct:.2f}%)')
            else:
                loss_pct = (profit / buy_value * 100) if buy_value > 0 else 0
                print(f'   ❌ LOSS: €{profit:.4f} ({loss_pct:.2f}%)')

    print()
    print('=' * 140)
    print(f'📊 Totaal aantal trades: {len(all_trades)}')
    print(f'📖 Trades met log data: {sum(1 for t in all_trades if t["has_log_data"])}')
    print(f'💾 Trades zonder log data: {sum(1 for t in all_trades if not t["has_log_data"])}')
    print(f'🏆 TOTAAL PROFIT/LOSS: €{total_profit_eur:.4f}')
    print('=' * 140)
    print()
    print('Legend: 📖 = Prijs uit logs (betrouwbaar), 💾 = Prijs uit database (mogelijk fout)')

    conn.close()


if __name__ == '__main__':
    main()
