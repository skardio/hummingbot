#!/usr/bin/env python3
"""
Quick script to rebalance account: Buy ETH with half of EUR
Prepares account for two-sided grid trading
"""

import os

import ccxt

# Get API keys
api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_SECRET_KEY')

if not api_key or not api_secret:
    print("❌ API keys not set!")
    print("Run: export KRAKEN_API_KEY=...")
    exit(1)

exchange = ccxt.kraken({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True
})

print("\n" + "=" * 70)
print("  ACCOUNT REBALANCE - Prepare for Grid Trading")
print("=" * 70)

# Get balances
balance = exchange.fetch_balance()
eur = balance.get('EUR', {}).get('free', 0)
eth = balance.get('ETH', {}).get('free', 0)

# Get ETH price
ticker = exchange.fetch_ticker('ETH/EUR')
eth_price = ticker['last']
eth_value_eur = eth * eth_price
total_value = eur + eth_value_eur

print(f"\nCurrent Balances:")
print(f"  EUR: €{eur:.2f}")
print(f"  ETH: {eth:.6f} (€{eth_value_eur:.2f})")
print(f"  Total: €{total_value:.2f}")
print(f"\nETH Price: €{eth_price:.2f}")

# Calculate target 50/50 split
target_eth_value = total_value / 2
target_eur_value = total_value / 2

current_eth_pct = (eth_value_eur / total_value) * 100 if total_value > 0 else 0
target_eth_pct = 50.0

print(f"\nCurrent allocation:")
print(f"  EUR: {100 - current_eth_pct:.1f}%")
print(f"  ETH: {current_eth_pct:.1f}%")

print(f"\nTarget allocation (50/50):")
print(f"  EUR: €{target_eur_value:.2f} (50%)")
print(f"  ETH: €{target_eth_value:.2f} (50%)")

# Calculate needed ETH purchase
if eth_value_eur < target_eth_value:
    buy_amount_eur = target_eth_value - eth_value_eur
    buy_amount_eth = buy_amount_eur / eth_price

    print(f"\n💡 Rebalance needed:")
    print(f"   Buy {buy_amount_eth:.6f} ETH (€{buy_amount_eur:.2f})")

    print("\n" + "=" * 70)
    response = input("Execute this rebalance? [yes/NO]: ")

    if response.lower() == 'yes':
        print("\n🔄 Placing market BUY order...")
        try:
            order = exchange.create_market_order(
                symbol='ETH/EUR',
                side='buy',
                amount=buy_amount_eth
            )
            print(f"✓ Order executed!")
            print(f"  Order ID: {order['id']}")
            print(f"  Amount: {order['amount']} ETH")
            print(f"  Price: €{order.get('average', eth_price):.2f}")

            # Show new balance
            import time
            time.sleep(2)
            balance = exchange.fetch_balance()
            new_eur = balance.get('EUR', {}).get('free', 0)
            new_eth = balance.get('ETH', {}).get('free', 0)

            print(f"\n✓ New Balances:")
            print(f"  EUR: €{new_eur:.2f}")
            print(f"  ETH: {new_eth:.6f}")
            print(f"\n✅ Account ready for grid trading!")

        except Exception as e:
            print(f"\n❌ Error: {e}")
    else:
        print("\n❌ Cancelled")

elif eth_value_eur > target_eth_value:
    sell_amount_eur = eth_value_eur - target_eth_value
    sell_amount_eth = sell_amount_eur / eth_price

    print(f"\n💡 Rebalance needed:")
    print(f"   Sell {sell_amount_eth:.6f} ETH (€{sell_amount_eur:.2f})")

    print("\n" + "=" * 70)
    response = input("Execute this rebalance? [yes/NO]: ")

    if response.lower() == 'yes':
        print("\n🔄 Placing market SELL order...")
        try:
            order = exchange.create_market_order(
                symbol='ETH/EUR',
                side='sell',
                amount=sell_amount_eth
            )
            print(f"✓ Order executed!")
            print(f"  Order ID: {order['id']}")
            print(f"  Amount: {order['amount']} ETH")
            print(f"  Price: €{order.get('average', eth_price):.2f}")

            # Show new balance
            import time
            time.sleep(2)
            balance = exchange.fetch_balance()
            new_eur = balance.get('EUR', {}).get('free', 0)
            new_eth = balance.get('ETH', {}).get('free', 0)

            print(f"\n✓ New Balances:")
            print(f"  EUR: €{new_eur:.2f}")
            print(f"  ETH: {new_eth:.6f}")
            print(f"\n✅ Account ready for grid trading!")

        except Exception as e:
            print(f"\n❌ Error: {e}")
    else:
        print("\n❌ Cancelled")
else:
    print(f"\n✅ Account already balanced (~50/50)")
    print(f"   Ready for grid trading!")

print("\n" + "=" * 70)
