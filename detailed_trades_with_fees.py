#!/usr/bin/env python3
"""
Detailed Trade Analysis - Individual Trades with Buy/Sell Pairs and Fees
Shows each trade with exact prices, fees, and P&L per pair
"""


# Database path
DB_PATH = "/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite"

# Log file directory
LOG_DIR = Path("/home/mo/repos/hummingbot/logs")


def parse_log_prices_with_fees(log_files):
    """Extract prices, amounts, and fees from OrderFilledEvent in log files"""
    price_data = {}

    for log_file in log_files:
        if not log_file.exists():
            continue

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for EVENT_LOG with OrderFilledEvent
                if 'EVENT_LOG' not in line or 'OrderFilledEvent' not in line:
                    continue

                # Extract JSON part after EVENT_LOG -
                try:
                    json_start = line.find('{"timestamp"')
                    if json_start == -1:
                        continue

                    json_str = line[json_start:]
                    event_data = json.loads(json_str)

                    # Check if this is an OrderFilledEvent
                    if event_data.get('event_name') != 'OrderFilledEvent':
                        continue

                    # Extract trade data
                    exchange_order_id = event_data.get('exchange_order_id', '')
                    exchange_trade_id = event_data.get('exchange_trade_id', '')

                    if not exchange_trade_id:
                        continue

                    price = float(event_data.get('price', 0))
                    amount = float(event_data.get('amount', 0))

                    # Extract fee from trade_fee structure
                    trade_fee = event_data.get('trade_fee', {})
                    flat_fees = trade_fee.get('flat_fees', [])
                    fee_amount = 0.0

                    for fee_item in flat_fees:
                        if fee_item.get('token') == 'EUR':
                            fee_amount += float(fee_item.get('amount', 0))

                    price_data[exchange_trade_id] = {
                        'price': price,
                        'amount': amount,
                        'fee': fee_amount,
                        'total': price * amount,
                        'exchange_order_id': exchange_order_id
                    }

                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    continue

    return price_data


def get_all_trades():
    """Get all trades from database with proper conversions"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get trades from last 15 hours (timestamp is in milliseconds!)
    cutoff_time = (datetime.now().timestamp() - (15 * 3600)) * 1000

    query = """
    SELECT
        timestamp,
        symbol,
        trade_type,
        price,
        amount,
        exchange_trade_id
    FROM TradeFill
    WHERE timestamp >= ?
    ORDER BY timestamp ASC
    """

    cursor.execute(query, (cutoff_time,))
    trades = cursor.fetchall()
    conn.close()

    return trades


def format_trade(trade, price_data):
    """Format a single trade with all details"""
    timestamp, symbol, trade_type, db_price, db_amount, exchange_id = trade

    # Convert timestamp from milliseconds to seconds
    timestamp_sec = timestamp / 1000

    # Get real price and fee from logs
    if exchange_id in price_data:
        price = price_data[exchange_id]['price']
        amount = price_data[exchange_id]['amount']
        fee = price_data[exchange_id]['fee']
        total = price_data[exchange_id]['total']
        source = "📖"
    else:
        # Fallback to database (with conversions)
        if 'PEPE' in symbol:
            price = db_price / 1_000_000
            amount = db_amount / 100_000_000
        elif 'TAO' in symbol:
            price = db_price / 100_000_000
            amount = db_amount / 100_000_000
        else:
            price = db_price / 100_000_000
            amount = db_amount / 100_000_000

        fee = 0.0
        total = price * amount
        source = "💾"

    # Format timestamp
    dt = datetime.fromtimestamp(timestamp_sec)
    time_str = dt.strftime("%H:%M:%S")

    # Trade type emoji
    type_emoji = "🟢" if trade_type == "BUY" else "🔴"

    return {
        'time': time_str,
        'timestamp': timestamp_sec,
        'symbol': symbol,
        'type': trade_type,
        'type_emoji': type_emoji,
        'price': price,
        'amount': amount,
        'fee': fee,
        'total': total,
        'source': source,
        'exchange_id': exchange_id
    }


def match_buy_sell_pairs(formatted_trades):
    """Match buy and sell trades to calculate P&L per pair"""
    by_symbol = defaultdict(lambda: {'buys': [], 'sells': []})

    for trade in formatted_trades:
        symbol = trade['symbol']
        if trade['type'] == 'BUY':
            by_symbol[symbol]['buys'].append(trade)
        else:
            by_symbol[symbol]['sells'].append(trade)

    pairs = []

    for symbol, trades in by_symbol.items():
        buys = trades['buys'][:]  # Copy to avoid modifying original
        sells = trades['sells'][:]

        # Match sells with buys based on amount similarity and time
        for sell in sells:
            # Find buy with closest amount that happened before this sell
            best_match = None
            best_match_score = float('inf')

            for i, buy in enumerate(buys):
                if buy['timestamp'] < sell['timestamp']:
                    # Calculate match score based on amount difference and time difference
                    amount_diff = abs(buy['amount'] - sell['amount']) / max(buy['amount'], sell['amount'])
                    time_diff = sell['timestamp'] - buy['timestamp']

                    # Prioritize amount similarity over time proximity
                    score = amount_diff * 1000 + (time_diff / 3600)  # Amount diff weighted heavily

                    if score < best_match_score:
                        best_match_score = score
                        best_match = (i, buy)

            if best_match:
                buy_idx, buy = best_match

                # Calculate P&L
                buy_cost = buy['total'] + buy['fee']
                sell_revenue = sell['total'] - sell['fee']
                pnl = sell_revenue - buy_cost
                pnl_pct = (pnl / buy_cost * 100) if buy_cost > 0 else 0

                pairs.append({
                    'symbol': symbol,
                    'buy': buy,
                    'sell': sell,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })

                # Remove matched buy to avoid duplicate matching
                buys.pop(buy_idx)

    return pairs


def main():
    print("=" * 80)
    print("GEDETAILLEERDE TRADE ANALYSE - LAATSTE 15 UUR")
    print("=" * 80)
    print()

    # Find log files
    log_files = sorted(LOG_DIR.glob("logs_multi_coin_grid_v2_*.log*"))
    print(f"📁 Gevonden log files: {len(log_files)}")

    # Parse prices from logs
    print("📖 Parsing prijzen uit logs...")
    price_data = parse_log_prices_with_fees(log_files)
    print(f"✅ {len(price_data)} trades met prijsdata gevonden in logs")
    print()

    # Get trades from database
    print("💾 Ophalen trades uit database...")
    trades = get_all_trades()
    print(f"✅ {len(trades)} trades gevonden in database")
    print()

    # Format all trades
    formatted_trades = []
    for trade in trades:
        formatted_trades.append(format_trade(trade, price_data))

    # Group by symbol
    by_symbol = defaultdict(list)
    for trade in formatted_trades:
        by_symbol[trade['symbol']].append(trade)

    # Print all trades by symbol
    print("=" * 80)
    print("ALLE TRADES (CHRONOLOGISCH PER COIN)")
    print("=" * 80)
    print()

    for symbol in sorted(by_symbol.keys()):
        print(f"\n{'=' * 80}")
        print(f"  {symbol}")
        print(f"{'=' * 80}\n")

        trades_list = by_symbol[symbol]

        for i, trade in enumerate(trades_list, 1):
            print(f"{trade['type_emoji']} Trade #{i} - {trade['type']} om {trade['time']}")
            print(f"   Bedrag: {trade['amount']:,.2f} {symbol.split('-')[0]}")
            print(f"   Prijs:  €{trade['price']:.10f}")
            print(f"   Totaal: €{trade['total']:.4f}")
            print(f"   Fees:   €{trade['fee']:.4f}")

            if trade['type'] == 'BUY':
                print(f"   💰 Totale kosten: €{trade['total'] + trade['fee']:.4f}")
            else:
                print(f"   💰 Netto ontvangen: €{trade['total'] - trade['fee']:.4f}")

            print(f"   Bron: {trade['source']}")
            print()

    # Match buy/sell pairs
    print("\n" + "=" * 80)
    print("TRADE PAIRS - KOOP/VERKOOP MET WINST/VERLIES")
    print("=" * 80)
    print()

    pairs = match_buy_sell_pairs(formatted_trades)

    total_pnl = 0.0

    for symbol in sorted(set(p['symbol'] for p in pairs)):
        symbol_pairs = [p for p in pairs if p['symbol'] == symbol]

        print(f"\n{'=' * 80}")
        print(f"  {symbol} - {len(symbol_pairs)} trade pairs")
        print(f"{'=' * 80}\n")

        symbol_pnl = 0.0

        for i, pair in enumerate(symbol_pairs, 1):
            buy = pair['buy']
            sell = pair['sell']
            pnl = pair['pnl']
            pnl_pct = pair['pnl_pct']

            symbol_pnl += pnl

            # Determine if profit or loss
            if pnl >= 0:
                result_emoji = "✅"
                result_text = "WINST"
            else:
                result_emoji = "❌"
                result_text = "VERLIES"

            print(f"Pair #{i}: {result_emoji} {result_text}")
            print(f"  {'─' * 76}")
            print(f"  🟢 GEKOCHT om {buy['time']}")
            print(f"     Bedrag:  {buy['amount']:,.2f} {symbol.split('-')[0]}")
            print(f"     Prijs:   €{buy['price']:.10f}")
            print(f"     Totaal:  €{buy['total']:.4f}")
            print(f"     Fees:    €{buy['fee']:.4f}")
            print(f"     💰 TOTALE KOSTEN: €{buy['total'] + buy['fee']:.4f}")
            print()
            print(f"  🔴 VERKOCHT om {sell['time']}")
            print(f"     Bedrag:  {sell['amount']:,.2f} {symbol.split('-')[0]}")
            print(f"     Prijs:   €{sell['price']:.10f}")
            print(f"     Totaal:  €{sell['total']:.4f}")
            print(f"     Fees:    €{sell['fee']:.4f}")
            print(f"     💰 NETTO ONTVANGEN: €{sell['total'] - sell['fee']:.4f}")
            print()
            print("  📊 RESULTAAT:")
            print(f"     P&L:     €{pnl:+.4f} ({pnl_pct:+.2f}%)")
            print()

        print(f"{'─' * 80}")
        print(f"Totaal {symbol}: €{symbol_pnl:+.4f}")
        print()

        total_pnl += symbol_pnl

    # Overall summary
    print("\n" + "=" * 80)
    print("TOTAAL OVERZICHT")
    print("=" * 80)
    print(f"\nTotaal aantal trade pairs: {len(pairs)}")

    wins = [p for p in pairs if p['pnl'] >= 0]
    losses = [p for p in pairs if p['pnl'] < 0]

    print(f"✅ Winst trades: {len(wins)}")
    print(f"❌ Verlies trades: {len(losses)}")
    print()
    print(f"{'─' * 80}")
    print(f"TOTALE P&L (incl. alle fees): €{total_pnl:+.4f}")
    print(f"{'─' * 80}")
    print()


if __name__ == "__main__":
    main()
