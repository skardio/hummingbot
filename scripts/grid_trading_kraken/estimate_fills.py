#!/usr/bin/env python3
import os

import ccxt

ex = ccxt.kraken({
    'apiKey': os.getenv('KRAKEN_API_KEY'),
    'secret': os.getenv('KRAKEN_SECRET_KEY'),
    'enableRateLimit': True
})

ticker = ex.fetch_ticker('XRP/EUR')
current = ticker['last']
high_24h = ticker['high']
low_24h = ticker['low']
change_24h = ticker['percentage']

print("\n" + "=" * 70)
print("  ⏱️  FILL TIME ESTIMATE")
print("=" * 70)

print(f"\n📊 XRP/EUR nu: €{current:.4f}")
print(f"   24h High: €{high_24h:.4f} (+{((high_24h / current) - 1) * 100:.1f}%)")
print(f"   24h Low:  €{low_24h:.4f} ({((low_24h / current) - 1) * 100:.1f}%)")
print(f"   24h Change: {change_24h:.1f}%")

daily_range = high_24h - low_24h
daily_range_pct = (daily_range / current) * 100

print(f"\n📈 Volatiliteit:")
print(f"   24h range: €{daily_range:.4f} ({daily_range_pct:.1f}%)")

# Your order levels (4 grids)
buy_levels = [2.05, 2.16]
sell_levels = [2.28, 2.40]

print(f"\n🎯 Jouw Orders:")
print(f"\n   BUY orders:")
for price in buy_levels:
    distance = ((current - price) / current) * 100
    print(f"   • €{price:.2f} ({distance:.1f}% onder huidige prijs)")

print(f"\n   SELL orders:")
for price in sell_levels:
    distance = ((price - current) / current) * 100
    print(f"   • €{price:.2f} (+{distance:.1f}% boven huidige prijs)")

# Estimate fill time
closest_buy = max(buy_levels)
closest_sell = min(sell_levels)
buy_distance = ((current - closest_buy) / current) * 100
sell_distance = ((closest_sell - current) / current) * 100

print(f"\n⏱️  Geschatte Fill Tijd:")
print(f"\n   Dichtstbijzijnde BUY:  €{closest_buy:.2f} ({buy_distance:.1f}% weg)")
print(f"   Dichtstbijzijnde SELL: €{closest_sell:.2f} (+{sell_distance:.1f}% weg)")

# Estimate based on 24h volatility
if daily_range_pct > 10:
    estimate = "paar uur"
    emoji = "🟢"
    speed = "SNEL"
elif daily_range_pct > 5:
    estimate = "vandaag/morgen"
    emoji = "🟡"
    speed = "NORMAAL"
else:
    estimate = "paar dagen"
    emoji = "🔴"
    speed = "LANGZAAM"

print(f"\n   {emoji} Met {daily_range_pct:.1f}% daily volatility: {speed}")
print(f"      Eerste fill: waarschijnlijk binnen {estimate}")

# Check if price is in range today
if low_24h <= closest_buy:
    print(f"\n   ✅ BUY €{closest_buy:.2f} was binnen 24h bereik (low: €{low_24h:.4f})")
    print(f"      Dit level wordt waarschijnlijk vaker geraakt!")

if high_24h >= closest_sell:
    print(f"\n   ✅ SELL €{closest_sell:.2f} was binnen 24h bereik (high: €{high_24h:.4f})")
    print(f"      Dit level wordt waarschijnlijk vaker geraakt!")

print(f"\n💡 Tips:")
print(f"   • Dichterbij = sneller fills maar minder winst per trade")
print(f"   • Verder weg = langzamer maar meer winst per trade")
print(f"   • Grid trading = geduld! Laat bot 24/7 draaien")
print(f"   • Meer volatiliteit = meer fills = meer winst")

print("\n" + "=" * 70)
