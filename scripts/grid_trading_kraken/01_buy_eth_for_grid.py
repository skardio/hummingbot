#!/usr/bin/env python3
"""
Quick buy ETH for grid trading
Buy €50 worth of ETH to get 50/50 balance
"""

import os

import ccxt

api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_SECRET_KEY')

if not api_key or not api_secret:
    print("❌ Set API keys first!")
    exit(1)

exchange = ccxt.kraken({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True
})

print("\n" + "=" * 70)
print("  BUY ETH FOR GRID TRADING")
print("=" * 70)

# Get current balances
balance = exchange.fetch_balance()
eur = balance.get('EUR', {}).get('free', 0)
eth_spot = balance.get('ETH', {}).get('free', 0) if 'ETH' in balance else 0
eth_staked = balance.get('ETH.F', {}).get('free', 0) if 'ETH.F' in balance else 0

# Get ETH price
ticker = exchange.fetch_ticker('ETH/EUR')
eth_price = ticker['last']

print(f"\nCurrent Situation:")
print(f"  💶 EUR available: €{eur:.2f}")
print(f"  💎 ETH (spot): {eth_spot:.6f} (€{eth_spot * eth_price:.2f})")
if eth_staked > 0:
    print(f"  🔒 ETH (staked): {eth_staked:.6f} (€{eth_staked * eth_price:.2f}) - LOCKED")
print(f"\n  ETH Price: €{eth_price:.2f}")

# For grid trading, need ~50 EUR in ETH
target_eth_value = 50
current_eth_value = eth_spot * eth_price

needed_eur = target_eth_value - current_eth_value

if needed_eur > 0:
    needed_eth = needed_eur / eth_price

    print(f"\n💡 For grid trading you need:")
    print(f"   ~€50 in EUR (for BUY orders)")
    print(f"   ~€50 in ETH (for SELL orders)")

    print(f"\n📊 Rebalance Plan:")
    print(f"   Current ETH value: €{current_eth_value:.2f}")
    print(f"   Target ETH value: €{target_eth_value:.2f}")
    print(f"   Need to buy: {needed_eth:.6f} ETH (€{needed_eur:.2f})")
    print(f"   After: €{eur - needed_eur:.2f} EUR + ~{eth_spot + needed_eth:.6f} ETH")

    if eur < needed_eur:
        print(f"\n⚠️  Not enough EUR! You have €{eur:.2f}, need €{needed_eur:.2f}")
        exit(1)

    print("\n" + "=" * 70)
    response = input("Buy ETH now? Type 'YES' to confirm: ")

    if response == 'YES':
        print(f"\n🔄 Placing market BUY order...")

        try:
            order = exchange.create_market_order(
                symbol='ETH/EUR',
                side='buy',
                amount=needed_eth
            )

            print(f"✅ ORDER EXECUTED!")
            print(f"   Order ID: {order['id']}")
            print(f"   Bought: {order['amount']:.6f} ETH")
            print(f"   Price: €{order.get('average', eth_price):.2f}")
            print(f"   Cost: €{order['cost']:.2f}")

            # Show new balance
            import time
            time.sleep(2)
            balance = exchange.fetch_balance()
            new_eur = balance.get('EUR', {}).get('free', 0)
            new_eth = balance.get('ETH', {}).get('free', 0) if 'ETH' in balance else 0

            print(f"\n✅ NEW BALANCES:")
            print(f"   EUR: €{new_eur:.2f}")
            print(f"   ETH: {new_eth:.6f} (€{new_eth * eth_price:.2f})")
            print(f"\n🎯 Ready for grid trading!")
            print(f"   Now run: python3 scripts/grid_trading_kraken/06_grid_live_trade.py")

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
    else:
        print("\n❌ Cancelled")
else:
    print(f"\n✅ You already have enough ETH!")
    print(f"   ETH value: €{current_eth_value:.2f} >= €{target_eth_value:.2f}")
    print(f"   EUR: €{eur:.2f}")
    print(f"\n🎯 Ready for grid trading!")

print("=" * 70 + "\n")
