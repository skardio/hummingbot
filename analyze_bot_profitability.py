#!/usr/bin/env python3
"""
Bot Profitability Analysis - Find the Root Causes of Low Profit/Loss
Analyzes trades, fees, grid spacing, and filters to identify problems
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
                if 'EVENT_LOG' not in line or 'OrderFilledEvent' not in line:
                    continue

                try:
                    json_start = line.find('{"timestamp"')
                    if json_start == -1:
                        continue

                    json_str = line[json_start:]
                    event_data = json.loads(json_str)

                    if event_data.get('event_name') != 'OrderFilledEvent':
                        continue

                    exchange_trade_id = event_data.get('exchange_trade_id', '')
                    if not exchange_trade_id:
                        continue

                    price = float(event_data.get('price', 0))
                    amount = float(event_data.get('amount', 0))

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
                    }

                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    continue

    return price_data


def get_all_trades():
    """Get all trades from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get trades from last 15 hours
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

    timestamp_sec = timestamp / 1000

    if exchange_id in price_data:
        price = price_data[exchange_id]['price']
        amount = price_data[exchange_id]['amount']
        fee = price_data[exchange_id]['fee']
        total = price_data[exchange_id]['total']
    else:
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

    dt = datetime.fromtimestamp(timestamp_sec)

    return {
        'time': dt,
        'timestamp': timestamp_sec,
        'symbol': symbol,
        'type': trade_type,
        'price': price,
        'amount': amount,
        'fee': fee,
        'total': total,
        'exchange_id': exchange_id
    }


def match_buy_sell_pairs(formatted_trades):
    """Match buy and sell trades based on amount similarity"""
    by_symbol = defaultdict(lambda: {'buys': [], 'sells': []})

    for trade in formatted_trades:
        symbol = trade['symbol']
        if trade['type'] == 'BUY':
            by_symbol[symbol]['buys'].append(trade)
        else:
            by_symbol[symbol]['sells'].append(trade)

    pairs = []

    for symbol, trades in by_symbol.items():
        buys = trades['buys'][:]
        sells = trades['sells'][:]

        for sell in sells:
            best_match = None
            best_match_score = float('inf')

            for i, buy in enumerate(buys):
                if buy['timestamp'] < sell['timestamp']:
                    amount_diff = abs(buy['amount'] - sell['amount']) / max(buy['amount'], sell['amount'])
                    time_diff = sell['timestamp'] - buy['timestamp']
                    score = amount_diff * 1000 + (time_diff / 3600)

                    if score < best_match_score:
                        best_match_score = score
                        best_match = (i, buy)

            if best_match:
                buy_idx, buy = best_match

                buy_cost = buy['total'] + buy['fee']
                sell_revenue = sell['total'] - sell['fee']
                pnl = sell_revenue - buy_cost
                pnl_pct = (pnl / buy_cost * 100) if buy_cost > 0 else 0

                # Calculate price spread
                price_spread_pct = ((sell['price'] - buy['price']) / buy['price'] * 100)

                # Calculate time held
                time_held_mins = (sell['timestamp'] - buy['timestamp']) / 60

                pairs.append({
                    'symbol': symbol,
                    'buy': buy,
                    'sell': sell,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'price_spread_pct': price_spread_pct,
                    'time_held_mins': time_held_mins,
                    'total_fees': buy['fee'] + sell['fee']
                })

                buys.pop(buy_idx)

    return pairs


def analyze_profitability_issues(pairs):
    """Analyze pairs to find profitability issues"""

    print("=" * 80)
    print("🔍 PROFITABILITY ANALYSIS - ROOT CAUSE INVESTIGATION")
    print("=" * 80)
    print()

    # Group by symbol
    by_symbol = defaultdict(list)
    for pair in pairs:
        by_symbol[pair['symbol']].append(pair)

    for symbol, symbol_pairs in by_symbol.items():
        print(f"\n{'=' * 80}")
        print(f"📊 {symbol} - DETAILED ANALYSIS")
        print(f"{'=' * 80}\n")

        wins = [p for p in symbol_pairs if p['pnl'] >= 0]
        losses = [p for p in symbol_pairs if p['pnl'] < 0]

        print(f"Total pairs: {len(symbol_pairs)} (✅ {len(wins)} wins, ❌ {len(losses)} losses)")
        print()

        # Calculate statistics
        avg_pnl = sum(p['pnl'] for p in symbol_pairs) / len(symbol_pairs)
        avg_price_spread = sum(p['price_spread_pct'] for p in symbol_pairs) / len(symbol_pairs)
        avg_time_held = sum(p['time_held_mins'] for p in symbol_pairs) / len(symbol_pairs)
        avg_fees = sum(p['total_fees'] for p in symbol_pairs) / len(symbol_pairs)
        total_fees = sum(p['total_fees'] for p in symbol_pairs)
        total_pnl = sum(p['pnl'] for p in symbol_pairs)

        print("📈 Statistics:")
        print(f"   Avg P&L per pair:    €{avg_pnl:+.4f}")
        print(f"   Avg price spread:    {avg_price_spread:+.4f}%")
        print(f"   Avg time held:       {avg_time_held:.1f} minutes ({avg_time_held / 60:.1f} hours)")
        print(f"   Avg fees per pair:   €{avg_fees:.4f}")
        print(f"   Total fees paid:     €{total_fees:.4f}")
        print(f"   Total P&L:           €{total_pnl:+.4f}")
        print()

        # Calculate fee-to-profit ratio
        gross_profit = sum(p['sell']['total'] - p['buy']['total'] for p in symbol_pairs)
        net_profit = total_pnl
        fee_impact_pct = (total_fees / gross_profit * 100) if gross_profit != 0 else 0

        print("💰 Fee Impact:")
        print(f"   Gross profit (before fees): €{gross_profit:+.4f}")
        print(f"   Fees paid:                  €{total_fees:.4f}")
        print(f"   Net profit (after fees):    €{net_profit:+.4f}")
        print(f"   Fee impact:                 {fee_impact_pct:.1f}% of gross profit")
        print()

        # Analyze individual pairs
        print("🔎 Individual Pair Analysis:\n")

        for i, pair in enumerate(symbol_pairs, 1):
            buy = pair['buy']
            sell = pair['sell']

            # Calculate what the profit would be without fees
            profit_without_fees = sell['total'] - buy['total']
            profit_with_fees = pair['pnl']

            # Calculate minimum price movement needed to break even
            fee_total = pair['total_fees']
            min_price_move_pct = (fee_total / buy['total'] * 100)

            result_emoji = "✅" if pair['pnl'] >= 0 else "❌"

            print(f"Pair #{i}: {result_emoji}")
            print(f"  Buy:  €{buy['price']:.10f} @ {buy['time'].strftime('%H:%M:%S')}")
            print(f"  Sell: €{sell['price']:.10f} @ {sell['time'].strftime('%H:%M:%S')}")
            print(f"  Price spread: {pair['price_spread_pct']:+.4f}%")
            print(f"  Time held: {pair['time_held_mins']:.0f} min ({pair['time_held_mins'] / 60:.1f}h)")
            print(f"  Profit without fees: €{profit_without_fees:+.4f}")
            print(f"  Fees paid: €{fee_total:.4f}")
            print(f"  Net P&L: €{profit_with_fees:+.4f} ({pair['pnl_pct']:+.2f}%)")
            print(f"  ⚠️  Min price move needed to break even: {min_price_move_pct:.4f}%")
            print()

        # DIAGNOSIS
        print(f"{'=' * 80}")
        print(f"🩺 DIAGNOSIS - {symbol}")
        print(f"{'=' * 80}\n")

        issues_found = []

        # Issue 1: Grid spacing too small
        if avg_price_spread < 0.10:
            issues_found.append({
                'severity': '🔴 CRITICAL',
                'issue': 'Grid spacing TE KLEIN',
                'details': f'Gemiddelde spread {avg_price_spread:.4f}% is veel te klein!',
                'recommendation': f'Verhoog grid spacing naar minimaal 0.15-0.20% (nu {avg_price_spread:.4f}%)'
            })
        elif avg_price_spread < 0.15:
            issues_found.append({
                'severity': '🟡 WARNING',
                'issue': 'Grid spacing MARGINAAL',
                'details': f'Spread {avg_price_spread:.4f}% is aan de lage kant',
                'recommendation': f'Overweeg verhoging naar 0.20-0.25% voor meer buffer'
            })

        # Issue 2: Fee impact too high
        if fee_impact_pct > 80:
            issues_found.append({
                'severity': '🔴 CRITICAL',
                'issue': 'Fees eten alle winst op',
                'details': f'Fees zijn {fee_impact_pct:.1f}% van gross profit!',
                'recommendation': 'Verhoog grid spacing EN/OF verlaag trade frequency'
            })
        elif fee_impact_pct > 50:
            issues_found.append({
                'severity': '🟡 WARNING',
                'issue': 'Fee impact te hoog',
                'details': f'Fees zijn {fee_impact_pct:.1f}% van gross profit',
                'recommendation': 'Optimaliseer grid spacing of trade selectie'
            })

        # Issue 3: Too many small profit trades
        tiny_profits = [p for p in symbol_pairs if 0 < p['pnl'] < 0.10]
        if len(tiny_profits) > len(symbol_pairs) * 0.5:
            issues_found.append({
                'severity': '🟡 WARNING',
                'issue': 'Te veel trades met minimale winst',
                'details': f'{len(tiny_profits)}/{len(symbol_pairs)} trades < €0.10 profit',
                'recommendation': 'Verhoog trade size OF grid spacing'
            })

        # Issue 4: Time held too short
        if avg_time_held < 30:
            issues_found.append({
                'severity': '🟡 WARNING',
                'issue': 'Trades te snel gesloten',
                'details': f'Gemiddeld {avg_time_held:.0f} minuten held',
                'recommendation': 'Verlaag trade frequency - wacht op betere price movements'
            })

        if issues_found:
            for issue in issues_found:
                print(f"{issue['severity']}: {issue['issue']}")
                print(f"   Details: {issue['details']}")
                print(f"   💡 Oplossing: {issue['recommendation']}")
                print()
        else:
            print(f"✅ Geen kritieke issues gevonden voor {symbol}")
            print()


def analyze_smart_entry_rejections(log_files):
    """Analyze SmartEntry filter rejections to see if filters are too strict"""

    print("\n" + "=" * 80)
    print("🔍 SMARTENTRY FILTER ANALYSIS")
    print("=" * 80)
    print()

    rejection_reasons = defaultdict(int)
    rejection_coins = defaultdict(lambda: defaultdict(int))

    for log_file in log_files:
        if not log_file.exists():
            continue

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for rejection messages
                if 'REJECTED by' in line or 'NO BUY' in line:
                    # Extract coin symbol
                    coin_match = re.search(r'([A-Z]+-EUR)', line)
                    if not coin_match:
                        continue
                    coin = coin_match.group(1)

                    # Extract rejection reason
                    if 'REJECTED by' in line:
                        reason_match = re.search(r'REJECTED by (\w+)', line)
                        if reason_match:
                            reason = reason_match.group(1)
                            rejection_reasons[reason] += 1
                            rejection_coins[coin][reason] += 1
                    elif 'NO BUY' in line:
                        # Extract specific reason from message
                        if 'VWAP dev' in line:
                            reason = 'vwap_deviation'
                        elif 'ATR' in line:
                            reason = 'atr'
                        elif 'RSI' in line:
                            reason = 'rsi'
                        elif '24h trend' in line:
                            reason = 'trend_24h_max'
                        else:
                            reason = 'other'

                        rejection_reasons[reason] += 1
                        rejection_coins[coin][reason] += 1

    if rejection_reasons:
        print("📊 Top Rejection Reasons (Last 15h):\n")
        sorted_reasons = sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)

        for reason, count in sorted_reasons[:10]:
            print(f"   {reason:.<30} {count:>4} rejections")

        print()

        # Analyze if filters are too strict
        total_rejections = sum(rejection_reasons.values())
        print(f"Total rejections: {total_rejections}")
        print()

        if total_rejections > 100:
            print("⚠️  ZEER HOOG aantal rejections - filters zijn waarschijnlijk TE STRENG!")
            print()
            print("💡 Aanbevelingen:")

            top_3_reasons = sorted_reasons[:3]
            for reason, count in top_3_reasons:
                pct = (count / total_rejections * 100)
                print(f"   - {reason}: {pct:.1f}% van alle rejections")

                if reason == 'vwap_deviation':
                    print("     → Verhoog vwap_max_deviation_pct in config")
                elif reason == 'trend_24h_max':
                    print("     → Verhoog max_trend_24h_pct limiet")
                elif reason == 'rsi_block' or reason == 'rsi_buy_max':
                    print("     → Pas RSI limieten aan (nu te conservatief)")
                elif reason == 'atr':
                    print("     → Pas ATR range aan (min/max te streng)")
            print()
    else:
        print("✅ Geen rejection data gevonden in logs")
        print()


def main():
    print("=" * 80)
    print("🔍 BOT PROFITABILITY ROOT CAUSE ANALYSIS")
    print("=" * 80)
    print()

    # Find log files
    log_files = sorted(LOG_DIR.glob("logs_multi_coin_grid_v2_*.log*"))
    print(f"📁 Analyzing {len(log_files)} log files")

    # Parse prices from logs
    print("📖 Parsing trade data from logs...")
    price_data = parse_log_prices_with_fees(log_files)
    print(f"✅ {len(price_data)} trades found with price data")

    # Get trades from database
    print("💾 Loading trades from database...")
    trades = get_all_trades()
    print(f"✅ {len(trades)} trades found")
    print()

    # Format all trades
    formatted_trades = []
    for trade in trades:
        formatted_trades.append(format_trade(trade, price_data))

    # Match buy/sell pairs
    pairs = match_buy_sell_pairs(formatted_trades)

    if pairs:
        # Analyze profitability issues
        analyze_profitability_issues(pairs)
    else:
        print("⚠️  No trade pairs found to analyze")

    # Analyze SmartEntry filter rejections
    analyze_smart_entry_rejections(log_files)

    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
