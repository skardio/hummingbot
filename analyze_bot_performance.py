#!/usr/bin/env python3
"""
Scherpe analyse van bot performance - waarom maakt de bot verlies?
"""


def parse_log_file():
    """Parse het log bestand en analyseer alle trades."""

    log_file = "logs/logs_multi_coin_grid_v2_2025-12-27-13-02-50.log"

    # Data verzamelen
    buy_orders = []
    sell_orders = []
    grid_created = []
    realized_pnl = []

    print("=" * 80)
    print("🔍 BOT PERFORMANCE ANALYSE - WAAROM VERLIES?")
    print("=" * 80)
    print()

    with open(log_file, 'r') as f:
        for line in f:
            # BUY orders
            if 'OrderFilledEvent' in line and 'TradeType.BUY' in line:
                try:
                    data = json.loads(line.split('EVENT_LOG - ')[1])
                    buy_orders.append({
                        'timestamp': data['timestamp'],
                        'symbol': data['trading_pair'],
                        'amount': float(data['amount']),
                        'price': float(data['price']),
                        'fee': float(data['trade_fee']['flat_fees'][0]['amount'])
                    })
                except BaseException:
                    pass

            # SELL orders
            if 'OrderFilledEvent' in line and 'TradeType.SELL' in line:
                try:
                    data = json.loads(line.split('EVENT_LOG - ')[1])
                    sell_orders.append({
                        'timestamp': data['timestamp'],
                        'symbol': data['trading_pair'],
                        'amount': float(data['amount']),
                        'price': float(data['price']),
                        'fee': float(data['trade_fee']['flat_fees'][0]['amount'])
                    })
                except Exception:
                    pass

            # Trade closed met PnL
            if 'Trade closed:' in line and 'P&L:' in line:
                match = re.search(r'Trade closed: (\S+) \| P&L: €([-\d.]+)', line)
                if match:
                    realized_pnl.append({
                        'symbol': match.group(1),
                        'pnl': float(match.group(2))
                    })

            # Grid created
            if 'Grid created' in line or 'CreateExecutorAction' in line:
                if 'SUI-EUR' in line:
                    grid_created.append({'symbol': 'SUI-EUR', 'line': line})
                if 'BCH-EUR' in line:
                    grid_created.append({'symbol': 'BCH-EUR', 'line': line})

    # ANALYSE 1: Overzicht van orders
    print("📊 ORDERS OVERZICHT:")
    print(f"   BUY orders: {len(buy_orders)}")
    print(f"   SELL orders: {len(sell_orders)}")
    print()

    # ANALYSE 2: Per symbol breakdown
    symbols = set([o['symbol'] for o in buy_orders + sell_orders])

    for symbol in sorted(symbols):
        print(f"\n💰 {symbol} ANALYSE:")
        print("=" * 80)

        symbol_buys = [o for o in buy_orders if o['symbol'] == symbol]
        symbol_sells = [o for o in sell_orders if o['symbol'] == symbol]

        total_bought = sum(o['amount'] for o in symbol_buys)
        total_sold = sum(o['amount'] for o in symbol_sells)

        buy_cost = sum(o['amount'] * o['price'] for o in symbol_buys)
        sell_revenue = sum(o['amount'] * o['price'] for o in symbol_sells)

        buy_fees = sum(o['fee'] for o in symbol_buys)
        sell_fees = sum(o['fee'] for o in symbol_sells)

        avg_buy_price = buy_cost / total_bought if total_bought > 0 else 0
        avg_sell_price = sell_revenue / total_sold if total_sold > 0 else 0

        print("\n📈 KOOP TRADES:")
        print(f"   Aantal: {len(symbol_buys)}")
        print(f"   Totaal volume: {total_bought:.6f} {symbol.split('-')[0]}")
        print(f"   Totaal bedrag: €{buy_cost:.2f}")
        print(f"   Gemiddelde prijs: €{avg_buy_price:.6f}")
        print(f"   Totaal fees: €{buy_fees:.6f}")

        print("\n📉 VERKOOP TRADES:")
        print(f"   Aantal: {len(symbol_sells)}")
        print(f"   Totaal volume: {total_sold:.6f} {symbol.split('-')[0]}")
        print(f"   Totaal bedrag: €{sell_revenue:.2f}")
        print(f"   Gemiddelde prijs: €{avg_sell_price:.6f}")
        print(f"   Totaal fees: €{sell_fees:.6f}")

        # PnL berekening
        gross_pnl = sell_revenue - buy_cost
        net_pnl = gross_pnl - (buy_fees + sell_fees)

        print("\n💵 PNL BREAKDOWN:")
        print(f"   Bruto P&L: €{gross_pnl:.6f}")
        print(f"   Totaal fees: €{(buy_fees + sell_fees):.6f}")
        print(f"   Netto P&L: €{net_pnl:.6f}")

        # Prijs delta
        if avg_buy_price > 0 and avg_sell_price > 0:
            price_delta_pct = ((avg_sell_price - avg_buy_price) / avg_buy_price) * 100
            print(f"   Prijs delta: {price_delta_pct:+.4f}%")

        # Fee percentage
        if buy_cost > 0:
            fee_pct = ((buy_fees + sell_fees) / buy_cost) * 100
            print(f"   Fee percentage: {fee_pct:.4f}%")

        # Remaining position
        remaining = total_bought - total_sold
        if abs(remaining) > 0.001:
            print("\n⚠️  OPEN POSITIE:")
            print(f"   Nog te verkopen: {remaining:.6f} {symbol.split('-')[0]}")
            print(f"   Waarde bij avg buy: €{remaining * avg_buy_price:.2f}")

    # ANALYSE 3: Totaal overzicht
    print("\n\n")
    print("=" * 80)
    print("📊 TOTAAL OVERZICHT")
    print("=" * 80)

    total_buy_cost = sum(o['amount'] * o['price'] for o in buy_orders)
    total_sell_revenue = sum(o['amount'] * o['price'] for o in sell_orders)
    total_buy_fees = sum(o['fee'] for o in buy_orders)
    total_sell_fees = sum(o['fee'] for o in sell_orders)

    total_gross_pnl = total_sell_revenue - total_buy_cost
    total_fees = total_buy_fees + total_sell_fees
    total_net_pnl = total_gross_pnl - total_fees

    print(f"\n💰 TOTAAL GEÏNVESTEERD: €{total_buy_cost:.2f}")
    print(f"💵 TOTAAL VERKOCHT: €{total_sell_revenue:.2f}")
    print(f"💸 TOTAAL FEES: €{total_fees:.6f}")
    print(f"\n🎯 BRUTO P&L: €{total_gross_pnl:+.4f}")
    print(f"🎯 NETTO P&L: €{total_net_pnl:+.4f}")

    # ANALYSE 4: Realized PnL van performance tracker
    if realized_pnl:
        print("\n\n📈 PERFORMANCE TRACKER REALIZED PNL:")
        for pnl in realized_pnl:
            print(f"   {pnl['symbol']}: €{pnl['pnl']:+.2f}")

    # ANALYSE 5: Waarom verlies?
    print("\n\n")
    print("=" * 80)
    print("🔬 DIAGNOSE: WAAROM VERLIES?")
    print("=" * 80)

    if total_net_pnl < 0:
        print(f"\n❌ Bot maakt verlies van €{abs(total_net_pnl):.4f}")
        print("\nMogelijke oorzaken:")

        # 1. Fees te hoog?
        if total_fees > abs(total_gross_pnl):
            print(f"   🚨 PROBLEEM 1: Fees (€{total_fees:.6f}) zijn HOGER dan bruto winst")
            print("      → Fees eten alle winst op!")

        # 2. Prijs delta te klein?
        if total_gross_pnl < total_fees:
            print(f"   🚨 PROBLEEM 2: Bruto winst (€{total_gross_pnl:.4f}) < Fees (€{total_fees:.6f})")
            print("      → Prijsbeweging te klein om fees te compenseren")

        # 3. Grid spacing te klein?
        avg_order_size = total_buy_cost / len(buy_orders) if buy_orders else 0
        avg_fee_per_order = total_buy_fees / len(buy_orders) if buy_orders else 0
        if avg_order_size > 0:
            fee_pct_per_order = (avg_fee_per_order / avg_order_size) * 100
            print("\n   📊 GEMIDDELD PER ORDER:")
            print(f"      Order grootte: €{avg_order_size:.2f}")
            print(f"      Fee per order: €{avg_fee_per_order:.6f} ({fee_pct_per_order:.4f}%)")

            # Bereken minimale grid spacing
            min_profit_pct = (total_fees / total_buy_cost) * 100 * 2  # *2 voor round-trip
            print("\n   💡 MINIMALE GRID SPACING NODIG:")
            print(f"      {min_profit_pct:.4f}% om break-even te zijn")
            print(f"      {min_profit_pct + 0.5:.4f}% om 0.5% netto winst te maken")

    elif total_net_pnl > 0:
        print(f"\n✅ Bot maakt winst van €{total_net_pnl:.4f}")
    else:
        print("\n⚪ Bot is break-even")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    parse_log_file()
