#!/usr/bin/env python3
"""
Find ALL possible triangular arbitrage routes starting with EUR on Kraken
"""

import json
import os
from itertools import permutations

import ccxt


def main():
    exchange = ccxt.kraken({
        'apiKey': os.getenv('KRAKEN_API_KEY'),
        'secret': os.getenv('KRAKEN_SECRET_KEY')
    })

    print("\n🔍 Loading all Kraken markets...")
    markets = exchange.load_markets()

    # Find all EUR pairs
    eur_pairs = {}
    all_currencies = set()

    for symbol, market in markets.items():
        if market['quote'] == 'EUR' and market['active']:
            base = market['base']
            eur_pairs[base] = symbol
            all_currencies.add(base)

    print(f"\n✅ Found {len(eur_pairs)} active EUR pairs:")
    for base, symbol in sorted(eur_pairs.items()):
        print(f"   {symbol}")

    # Find all possible triangular routes starting with EUR
    print(f"\n🔄 Finding triangular routes...")
    print(f"   Currencies with EUR pairs: {len(all_currencies)}")

    all_routes = []

    # For each EUR pair, try to find triangles
    for curr1 in all_currencies:
        pair1 = eur_pairs[curr1]  # EUR -> curr1

        # Find all pairs where curr1 is base or quote
        for curr2 in all_currencies:
            if curr1 == curr2:
                continue

            # Check if curr1/curr2 or curr2/curr1 exists
            pair2_forward = f"{curr1}/{curr2}"
            pair2_reverse = f"{curr2}/{curr1}"

            pair2 = None
            if pair2_forward in markets and markets[pair2_forward]['active']:
                pair2 = pair2_forward
            elif pair2_reverse in markets and markets[pair2_reverse]['active']:
                pair2 = pair2_reverse

            if pair2 is None:
                continue

            # Check if curr2/EUR exists
            if curr2 in eur_pairs:
                pair3 = eur_pairs[curr2]  # curr2 -> EUR

                # We have a triangle!
                route = {
                    'currencies': ['EUR', curr1, curr2, 'EUR'],
                    'pairs': [pair1, pair2, pair3],
                    'description': f"EUR → {curr1} → {curr2} → EUR"
                }

                # Avoid duplicates (reverse routes)
                route_key = tuple(sorted([curr1, curr2]))
                if not any(tuple(sorted([r['currencies'][1], r['currencies'][2]])) == route_key for r in all_routes):
                    all_routes.append(route)

    print(f"\n✅ Found {len(all_routes)} unique triangular routes!")

    # Format routes for monitor config
    print("\n" + "=" * 80)
    print("ROUTES FOR MONITOR CONFIG:")
    print("=" * 80)

    monitor_routes = []
    for route in all_routes:
        # Convert to monitor format (pair-pair-pair)
        pairs = route['pairs']
        # Normalize pair names to Kraken format (remove /)
        normalized = [p.replace('/', '-') for p in pairs]
        monitor_routes.append(normalized)
        print(f"{route['description']:<40} {normalized}")

    # Save to JSON
    output = {
        'total_routes': len(all_routes),
        'routes': all_routes,
        'monitor_format': monitor_routes
    }

    output_file = 'opportunities/all_eur_routes.json'
    os.makedirs('opportunities', exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n💾 Saved to: {output_file}")

    # Group by first currency
    print("\n" + "=" * 80)
    print("GROUPED BY FIRST LEG:")
    print("=" * 80)

    from collections import defaultdict
    grouped = defaultdict(list)
    for route in all_routes:
        first_curr = route['currencies'][1]
        grouped[first_curr].append(route)

    for curr in sorted(grouped.keys()):
        routes = grouped[curr]
        print(f"\nEUR → {curr} ({len(routes)} routes):")
        for r in routes:
            print(f"  {r['description']}")

    print("\n" + "=" * 80)
    print(f"TOTAAL: {len(all_routes)} triangular arbitrage routes gevonden!")
    print("=" * 80)


if __name__ == "__main__":
    main()
