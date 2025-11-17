#!/usr/bin/env python3
import math
import os

import ccxt

exchange = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_SECRET_KEY'),
    'enableRateLimit': True
})

# Get current price
ticker = exchange.fetch_ticker('XRP/EUR')
current_price = ticker['last']

# Get balances
balance = exchange.fetch_balance()
eur = balance.get('EUR', {}).get('free', 0)
xrp = balance.get('XRP', {}).get('free', 0)

# Calculate grid levels (logarithmic)
start, end, num = 2.05, 2.40, 10
log_start = math.log(start)
log_end = math.log(end)
log_step = (log_end - log_start) / (num - 1)
levels = [math.exp(log_start + log_step * i) for i in range(num)]

print("\n" + "=" * 70)
print("  🔍 GRID DIAGNOSTIC")
print("=" * 70)
print(f"\n📊 Current XRP Price: €{current_price:.4f}")
print(f"\n💰 Balances:")
print(f"   EUR: €{eur:.2f}")
print(f"   XRP: {xrp:.2f}")

print(f"\n📐 Grid Levels (€{start:.2f} - €{end:.2f}):")
print("-" * 70)
for i, level in enumerate(levels):
    marker = " ← CURRENT" if abs(level - current_price) < 0.05 else ""
    side = "BUY " if level < current_price else "SELL"
    print(f"  {i + 1:2}. {side} @ €{level:.4f}{marker}")

# Calculate how many orders we should place
buy_levels = [l for l in levels if l < current_price * 0.995]  # BUY below price (0.5% buffer)
sell_levels = [l for l in levels if l > current_price * 1.005]  # SELL above price (0.5% buffer)

print(f"\n📊 Expected Orders:")
print(f"   BUY levels:  {len(buy_levels)} (below €{current_price * 0.995:.4f})")
print(f"   SELL levels: {len(sell_levels)} (above €{current_price * 1.005:.4f})")

# Check minimum order size
min_order_xrp = 10
min_order_eur = min_order_xrp * current_price
capital_per_level = 100 / num

print(f"\n⚙️  Order Sizing:")
print(f"   Capital per level: €{capital_per_level:.2f}")
print(f"   Min XRP order: {min_order_xrp} XRP (€{min_order_eur:.2f})")

if capital_per_level < min_order_eur:
    print(f"\n❌ PROBLEEM GEVONDEN!")
    print(f"   Capital per level: €{capital_per_level:.2f}")
    print(f"   Kraken minimum: €{min_order_eur:.2f}")
    print(f"   Tekort: €{min_order_eur - capital_per_level:.2f} per order")
    print(f"\n   Oplossingen:")
    print(f"   1. Verhoog total_capital: 100 → {math.ceil(min_order_eur * num)}")
    print(f"   2. Verlaag num_grids: 10 → {int(100 / min_order_eur)}")
else:
    print(f"\n✅ Order size OK: €{capital_per_level:.2f} >= €{min_order_eur:.2f}")

# Check if we have enough balance
eur_needed = len(buy_levels) * capital_per_level
xrp_needed = len(sell_levels) * min_order_xrp

print(f"\n💵 Balance Check:")
print(f"   EUR needed:  €{eur_needed:.2f} (have €{eur:.2f}) {'✅' if eur >= eur_needed else '❌'}")
print(f"   XRP needed:  {xrp_needed:.0f} XRP (have {xrp:.2f} XRP) {'✅' if xrp >= xrp_needed else '❌'}")

print("\n" + "=" * 70)
