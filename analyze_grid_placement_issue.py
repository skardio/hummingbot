#!/usr/bin/env python3
"""
Deep Grid Placement Analysis - Find Root Cause of TAO Losses
Focus on: tick rounding, grid levels, orderbook spread, actual fees
"""


DB_PATH = "/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite"
LOG_DIR = Path("/home/mo/repos/hummingbot/logs")


def parse_order_created_events(log_files):
    """Extract order creation data: intended price, grid level, orderbook state"""
    order_events = {}

    for log_file in log_files:
        if not log_file.exists():
            continue

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for BuyOrderCreated and SellOrderCreated events
                if 'EVENT_LOG' not in line:
                    continue

                if 'BuyOrderCreatedEvent' in line or 'SellOrderCreatedEvent' in line:
                    try:
                        json_start = line.find('{"timestamp"')
                        if json_start == -1:
                            continue

                        json_str = line[json_start:]
                        event_data = json.loads(json_str)

                        order_id = event_data.get('order_id', '')
                        if not order_id:
                            continue

                        order_events[order_id] = {
                            'type': event_data.get('type', ''),
                            'price': float(event_data.get('price', 0)),
                            'amount': float(event_data.get('amount', 0)),
                            'timestamp': event_data.get('timestamp', 0),
                            'trading_pair': event_data.get('trading_pair', ''),
                        }
                    except Exception:
                        continue

    return order_events


def parse_orderbook_snapshots(log_files, symbol='TAO-EUR'):
    """Extract orderbook snapshots near order placements"""
    snapshots = []

    for log_file in log_files:
        if not log_file.exists():
            continue

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Look for orderbook or mid-price logs
                if symbol in line and ('mid' in line.lower() or 'bid' in line.lower() or 'ask' in line.lower()):
                    # Extract timestamp and prices if available
                    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    if timestamp_match:
                        try:
                            dt = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                            snapshots.append({
                                'timestamp': dt.timestamp(),
                                'line': line
                            })
                        except BaseException:
                            pass

    return snapshots


def parse_fills_with_details(log_files):
    """Extract fill details including actual exchange fees"""
    fills = {}

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

                    # Extract ACTUAL fee from exchange
                    trade_fee = event_data.get('trade_fee', {})
                    flat_fees = trade_fee.get('flat_fees', [])
                    fee_amount = 0.0

                    for fee_item in flat_fees:
                        if fee_item.get('token') == 'EUR':
                            fee_amount += float(fee_item.get('amount', 0))

                    # Calculate fee percentage
                    total_value = price * amount
                    fee_pct = (fee_amount / total_value * 100) if total_value > 0 else 0

                    fills[exchange_trade_id] = {
                        'price': price,
                        'amount': amount,
                        'fee_eur': fee_amount,
                        'fee_pct': fee_pct,
                        'total_eur': total_value,
                        'order_id': event_data.get('order_id', ''),
                        'exchange_order_id': event_data.get('exchange_order_id', ''),
                        'trade_type': event_data.get('trade_type', ''),
                        'timestamp': event_data.get('timestamp', 0),
                        'trading_pair': event_data.get('trading_pair', '')
                    }

                except (json.JSONDecodeError, ValueError, KeyError):
                    continue

    return fills


def get_trades_from_db():
    """Get trades from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cutoff_time = (datetime.now().timestamp() - (15 * 3600)) * 1000

    query = """
    SELECT
        timestamp,
        symbol,
        trade_type,
        price,
        amount,
        exchange_trade_id,
        order_id
    FROM TradeFill
    WHERE timestamp >= ? AND symbol = 'TAO-EUR'
    ORDER BY timestamp ASC
    """

    cursor.execute(query, (cutoff_time,))
    trades = cursor.fetchall()
    conn.close()

    return trades


def analyze_tao_grid_issue():
    """Deep analysis of TAO grid placement issues"""

    print("=" * 80)
    print("🔬 TAO-EUR GRID PLACEMENT DEEP DIVE")
    print("=" * 80)
    print()

    # Get log files
    log_files = sorted(LOG_DIR.glob("logs_multi_coin_grid_v2_*.log*"))

    print("📖 Parsing fills with actual fees...")
    fills = parse_fills_with_details(log_files)

    tao_fills = {k: v for k, v in fills.items() if v['trading_pair'] == 'TAO-EUR'}

    if not tao_fills:
        print("❌ No TAO-EUR fills found in logs")
        return

    print(f"✅ Found {len(tao_fills)} TAO-EUR fills")
    print()

    # Analyze actual fees
    print("=" * 80)
    print("💰 ACTUAL FEE ANALYSIS")
    print("=" * 80)
    print()

    fee_pcts = [f['fee_pct'] for f in tao_fills.values()]
    avg_fee_pct = sum(fee_pcts) / len(fee_pcts)
    min_fee_pct = min(fee_pcts)
    max_fee_pct = max(fee_pcts)

    print(f"Average fee per trade: {avg_fee_pct:.4f}%")
    print(f"Min fee: {min_fee_pct:.4f}%")
    print(f"Max fee: {max_fee_pct:.4f}%")
    print(f"Round-trip fee (buy + sell): {avg_fee_pct * 2:.4f}%")
    print()

    # Calculate MINIMUM profitable spacing
    roundtrip_fee = avg_fee_pct * 2
    slippage_buffer = 0.05  # 5 bps
    rounding_buffer = 0.05  # 5 bps
    min_spacing = roundtrip_fee + slippage_buffer + rounding_buffer

    print("📊 BREAKEVEN CALCULATION:")
    print(f"   Round-trip fees:     {roundtrip_fee:.4f}%")
    print(f"   Slippage buffer:     {slippage_buffer:.4f}%")
    print(f"   Rounding buffer:     {rounding_buffer:.4f}%")
    print(f"   {'─' * 50}")
    print(f"   MINIMUM spacing:     {min_spacing:.4f}%")
    print(f"   SAFE spacing:        {min_spacing * 1.5:.4f}% (1.5x buffer)")
    print(f"   RECOMMENDED spacing: {min_spacing * 2:.0f}% (2x buffer)")
    print()

    # Analyze buy/sell pairs
    print("=" * 80)
    print("🔍 TRADE PAIR ANALYSIS - BUY vs SELL PRICES")
    print("=" * 80)
    print()

    # Group by buy/sell
    buys = sorted([f for f in tao_fills.values() if 'BUY' in f['trade_type']],
                  key=lambda x: x['timestamp'])
    sells = sorted([f for f in tao_fills.values() if 'SELL' in f['trade_type']],
                   key=lambda x: x['timestamp'])

    print(f"Buys:  {len(buys)}")
    print(f"Sells: {len(sells)}")
    print()

    # Match pairs and analyze
    for i, sell in enumerate(sells, 1):
        # Find most recent buy before this sell
        matching_buy = None
        for buy in reversed(buys):
            if buy['timestamp'] < sell['timestamp']:
                matching_buy = buy
                break

        if not matching_buy:
            continue

        # Calculate price spread
        buy_price = matching_buy['price']
        sell_price = sell['price']
        price_spread_pct = ((sell_price - buy_price) / buy_price * 100)

        # Calculate P&L
        buy_cost = matching_buy['total_eur'] + matching_buy['fee_eur']
        sell_revenue = sell['total_eur'] - sell['fee_eur']
        pnl = sell_revenue - buy_cost

        # Calculate actual fees paid
        total_fees = matching_buy['fee_eur'] + sell['fee_eur']
        total_fees_pct = (total_fees / matching_buy['total_eur'] * 100)

        # Determine if profitable
        is_profitable = pnl > 0
        emoji = "✅" if is_profitable else "❌"

        print(f"Pair #{i}: {emoji}")
        print(f"  {'─' * 76}")
        print(f"  🟢 BUY  @ €{buy_price:.4f} ({datetime.fromtimestamp(matching_buy['timestamp']).strftime('%H:%M:%S')})")
        print(f"     Amount: {matching_buy['amount']:.8f} TAO")
        print(f"     Cost:   €{buy_cost:.4f} (incl €{matching_buy['fee_eur']:.4f} fee = {matching_buy['fee_pct']:.4f}%)")
        print()
        print(f"  🔴 SELL @ €{sell_price:.4f} ({datetime.fromtimestamp(sell['timestamp']).strftime('%H:%M:%S')})")
        print(f"     Amount: {sell['amount']:.8f} TAO")
        print(f"     Revenue: €{sell_revenue:.4f} (after €{sell['fee_eur']:.4f} fee = {sell['fee_pct']:.4f}%)")
        print()
        print("  📊 METRICS:")
        print(f"     Price movement:       {price_spread_pct:+.4f}%")
        print(f"     Total fees paid:      €{total_fees:.4f} ({total_fees_pct:.4f}%)")
        print(f"     Net P&L:              €{pnl:+.4f}")
        print(f"     Minimum needed:       {min_spacing:.4f}% (current: {price_spread_pct:+.4f}%)")

        if price_spread_pct < 0:
            print("     ⚠️  GRID LOGIC ERROR: Sold BELOW buy price!")
            print("     ⚠️  This is NOT an orderbook spread issue!")
            print("     ⚠️  This is a GRID LEVEL PLACEMENT BUG!")
        elif 0 <= price_spread_pct < min_spacing:
            shortfall = min_spacing - price_spread_pct
            print(f"     ⚠️  Grid spacing TOO SMALL by {shortfall:.4f}%")
            print(f"     ⚠️  Fees ate all profit: {total_fees_pct:.4f}% fees vs {price_spread_pct:.4f}% gain")

        print()

    # Summary
    print("=" * 80)
    print("🩺 DIAGNOSIS")
    print("=" * 80)
    print()

    negative_spreads = sum(1 for sell in sells
                           if any(buy['timestamp'] < sell['timestamp'] and
                                  ((sell['price'] - buy['price']) / buy['price'] * 100) < 0
                                  for buy in buys))

    if negative_spreads > 0:
        print(f"🔴 CRITICAL: {negative_spreads} trades sold BELOW buy price!")
        print()
        print("ROOT CAUSE: Grid level placement logic error")
        print()
        print("LIKELY CAUSES:")
        print("  1. Tick rounding error (TAO has large tick size)")
        print("  2. Grid anchor drifting (using last_trade instead of mid)")
        print("  3. Price offset too aggressive (crossing into negative)")
        print("  4. Inventory forced sell (panic selling at loss)")
        print()
        print("REQUIRED FIXES:")
        print("  1. Add invariant: sell_price > buy_price + min_profit_ticks")
        print("  2. Never place sell below avg_entry_price + fees + buffer")
        print("  3. Check TAO tick_size and round properly")
        print("  4. Use mid_price for grid anchor, not last_trade")
        print()

    print("💡 RECOMMENDED CONFIG:")
    print(f"   min_spacing_bps: {int(min_spacing * 2 * 100)}  # {min_spacing * 2:.2f}%")
    print(f"   grid_spacing_mult: {min_spacing * 2 / 0.25:.1f}  # Assuming base 0.25%")
    print()


def main():
    analyze_tao_grid_issue()


if __name__ == "__main__":
    main()
