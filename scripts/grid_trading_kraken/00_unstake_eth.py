#!/usr/bin/env python3
"""
Unstake ETH from Kraken Earn (ETH.F) to Spot (ETH)
"""

import os
import time

import ccxt

api_key = os.getenv('KRAKEN_API_KEY')
api_secret = os.getenv('KRAKEN_SECRET_KEY')

if not api_key or not api_secret:
    print("❌ API keys not set!")
    exit(1)

exchange = ccxt.kraken({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True
})

print("\n" + "=" * 70)
print("  UNSTAKE ETH - Transfer from Earn to Spot")
print("=" * 70)

# Get balances
balance = exchange.fetch_balance()

eth_staked = balance.get('ETH.F', {}).get('free', 0) if 'ETH.F' in balance else 0
eth_spot = balance.get('ETH', {}).get('free', 0) if 'ETH' in balance else 0
eur = balance.get('EUR', {}).get('free', 0)

ticker = exchange.fetch_ticker('ETH/EUR')
eth_price = ticker['last']

print(f"\nCurrent Balances:")
print(f"  ETH (Spot): {eth_spot:.6f} - Ready for trading")
print(f"  ETH.F (Staked): {eth_staked:.6f} (~€{eth_staked * eth_price:.2f}) - In Kraken Earn")
print(f"  EUR: €{eur:.2f}")
print(f"\nETH Price: €{eth_price:.2f}")

if eth_staked == 0:
    print("\n✓ No ETH in staking, nothing to unstake")
    exit(0)

print("\n" + "=" * 70)
print("IMPORTANT:")
print("  Kraken API doesn't support unstaking via ccxt")
print("  You need to manually unstake via:")
print("")
print("  1. Go to: https://www.kraken.com/earn")
print("  2. Find your ETH staking position")
print("  3. Click 'Unstake' or 'Redeem'")
print("  4. Select amount: 0.013314 ETH")
print("  5. Confirm unstaking")
print("")
print("  ⏱️  Flexible staking = instant unstake (available immediately)")
print("  ⏱️  Fixed staking = may take time to unstake")
print("")
print("  After unstaking, ETH.F will become ETH (tradeable)")
print("=" * 70)

print("\n💡 Alternative: Buy more ETH with your EUR")
print("   You have €100 EUR available")
print("   Current ETH: 0.013314 (~€40.68)")
print("   Buy €10 more ETH to reach €50 total")

print("\n" + "=" * 70)
response = input("\nBuy €10 worth of ETH now? [yes/NO]: ")

if response.lower() == 'yes':
    buy_amount_eur = 10
    buy_amount_eth = buy_amount_eur / eth_price

    print(f"\n🔄 Placing market BUY order for {buy_amount_eth:.6f} ETH...")

    try:
        order = exchange.create_market_order(
            symbol='ETH/EUR',
            side='buy',
            amount=buy_amount_eth
        )

        print(f"✓ Order executed!")
        print(f"  Order ID: {order['id']}")
        print(f"  Amount: {order['amount']:.6f} ETH")
        print(f"  Price: €{order.get('average', eth_price):.2f}")

        time.sleep(2)
        balance = exchange.fetch_balance()
        new_eth = balance.get('ETH', {}).get('free', 0) if 'ETH' in balance else 0
        new_eur = balance.get('EUR', {}).get('free', 0)

        print(f"\n✓ New Balances:")
        print(f"  ETH (Spot): {new_eth:.6f}")
        print(f"  EUR: €{new_eur:.2f}")
        print(f"\n💡 Still need to unstake ETH.F for full balance")

    except Exception as e:
        print(f"\n❌ Error: {e}")
else:
    print("\n✓ No action taken")
    print("  Please unstake ETH.F manually via Kraken website")

print("\n" + "=" * 70 + "\n")
EOF
