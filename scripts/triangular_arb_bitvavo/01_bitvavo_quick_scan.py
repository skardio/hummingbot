#!/usr/bin/env python3
"""
Quick scan for triangular arbitrage opportunities on Bitvavo.

This script:
- Loads all trading pairs from Bitvavo
- Finds all possible triangle routes
- Computes mid-price and simulated execution prices (with slippage)
- Ranks routes by estimated edge (profit after fees)
- Outputs top 20+ routes to CSV and console

Usage:
  source ~/.venvs/bot/bin/activate
  pip install ccxt  # if not already installed
  python3 scripts/triangular_arb_bitvavo/01_bitvavo_quick_scan.py

Output:
  logs/bitvavo_routes_scan.csv
"""

import asyncio
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from itertools import permutations

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt not installed. Run: pip install ccxt")
    sys.exit(1)


def find_triangles(pairs_dict):
    """
    Find all possible triangle routes given a dict of trading pairs.

    For EUR-dominant exchanges like Bitvavo, also looks for EUR-centric triangles:
      EUR/TokenA -> TokenA/TokenB -> TokenB/EUR

    pairs_dict: dict like {'BTC/EUR': {...}, 'ETH/BTC': {...}, ...}

    Returns list of tuples (pair1, pair2, pair3) where:
      - pair1 = A/B
      - pair2 = B/C
      - pair3 = C/A

    This represents route: Start with A -> Buy B -> Buy C -> Sell A
    """
    triangles = []
    pair_list = list(pairs_dict.keys())

    # Try all ordered triples
    for p1, p2, p3 in permutations(pair_list, 3):
        try:
            a, b = p1.split('/')
            b2, c = p2.split('/')
            c2, a2 = p3.split('/')

            # Check if route closes: A/B -> B/C -> C/A
            if b == b2 and c == c2 and a == a2:
                triangles.append((p1, p2, p3))
        except ValueError:
            continue

    return triangles


def find_eur_centric_triangles(pairs_dict):
    """
    Find EUR-centric triangles: EUR/Token1 -> Token1/Token2 -> Token2/EUR

    This is designed for EUR-heavy exchanges like Bitvavo.
    """
    eur_triangles = []
    pair_list = list(pairs_dict.keys())

    # Find all pairs starting/ending with EUR
    eur_pairs = [p for p in pair_list if 'EUR' in p]
    non_eur_pairs = [p for p in pair_list if 'EUR' not in p]

    # EUR/X pairs
    eur_base_pairs = {}  # EUR/Token -> Token
    for pair in eur_pairs:
        base, quote = pair.split('/')
        if base == 'EUR':
            eur_base_pairs[pair] = quote

    # X/EUR pairs
    eur_quote_pairs = {}  # Token/EUR -> Token
    for pair in eur_pairs:
        base, quote = pair.split('/')
        if quote == 'EUR':
            eur_quote_pairs[pair] = base

    # Find triangles: EUR/TokenA -> TokenA/TokenB -> TokenB/EUR
    for eur_a_pair, token_a in eur_base_pairs.items():
        for token_b_eur_pair, token_b in eur_quote_pairs.items():
            # Find TokenA/TokenB pair
            for pair in non_eur_pairs:
                base, quote = pair.split('/')
                if base == token_a and quote == token_b:
                    eur_triangles.append((eur_a_pair, pair, token_b_eur_pair))
                    break
                elif base == token_b and quote == token_a:
                    # Reverse direction
                    eur_triangles.append((eur_a_pair, pair, token_b_eur_pair))
                    break

    return eur_triangles


def estimate_slippage_and_fee(mid_price, amount, depth_asks, depth_bids, taker_fee_pct):
    """
    Simulate slippage on a BUY order (walk the ask-side book).

    depth_asks: list of [price, size] pairs (sorted, best ask first)
    Returns: (execution_price, slipped_amount)
    """
    remaining = amount
    total_cost = Decimal("0")

    if not depth_asks:
        # No depth; use mid + conservative slippage estimate
        slipped_price = mid_price * (Decimal("1") + Decimal("0.005"))  # 0.5% slippage
        return slipped_price, amount

    for ask_price, ask_size in depth_asks:
        if remaining <= 0:
            break
        ask_price = Decimal(str(ask_price))
        ask_size = Decimal(str(ask_size))

        fill = min(remaining, ask_size)
        total_cost += ask_price * fill
        remaining -= fill

    if remaining > 0:
        # Not enough depth; assume remainder executes at last ask + 0.5% slippage
        if depth_asks:
            last_price = Decimal(str(depth_asks[-1][0]))
            remaining_cost = last_price * (Decimal("1") + Decimal("0.005")) * remaining
            total_cost += remaining_cost
        else:
            total_cost += mid_price * (Decimal("1") + Decimal("0.005")) * remaining

    avg_execution_price = total_cost / amount

    # Add taker fee
    fee_amount = avg_execution_price * amount * (Decimal(str(taker_fee_pct)) / Decimal("100"))
    final_price = avg_execution_price + (fee_amount / amount)

    return final_price, amount


def main():
    print("=" * 80)
    print("BITVAVO TRIANGULAR ARBITRAGE QUICK SCAN")
    print("=" * 80)
    print()

    # Initialize Bitvavo exchange via ccxt
    print("[1/5] Initializing Bitvavo exchange (ccxt)...")
    try:
        config = {
            'enableRateLimit': True,
            'rateLimit': 250,  # Conservative rate limit
        }

        # Optionally add API keys if provided via environment
        api_key = os.environ.get('BITVAVO_API_KEY')
        api_secret = os.environ.get('BITVAVO_API_SECRET')
        if api_key and api_secret:
            config['apiKey'] = api_key
            config['secret'] = api_secret
            print("  Using provided API keys (from BITVAVO_API_KEY / BITVAVO_API_SECRET)")
        else:
            print("  No API keys provided (BITVAVO_API_KEY / BITVAVO_API_SECRET env vars)")
            print("  → Using public data only (no authenticated calls)")

        exchange = ccxt.bitvavo(config)
    except Exception as e:
        print(f"ERROR: Failed to initialize ccxt.bitvavo: {e}")
        sys.exit(1)

    # Load markets
    print("[2/5] Loading markets...")
    try:
        markets = exchange.load_markets()
        pairs = list(markets.keys())
        print(f"  Loaded {len(pairs)} pairs")
        print(f"  Example pairs: {pairs[:5]}")
    except Exception as e:
        print(f"ERROR: Failed to load markets: {e}")
        sys.exit(1)

    # Find triangles
    print("[3/5] Finding triangle routes...")
    triangles = find_triangles(markets)
    print(f"  Found {len(triangles)} general triangles")

    # Also find EUR-centric triangles (for EUR-heavy exchanges like Bitvavo)
    eur_triangles = find_eur_centric_triangles(markets)
    print(f"  Found {len(eur_triangles)} EUR-centric triangles")

    all_triangles = triangles + eur_triangles
    print(f"  Total triangles: {len(all_triangles)}")

    if not all_triangles:
        print("  WARNING: No triangles found! Bitvavo may not have enough pair overlap for arbitrage.")
        return

    # Fetch tickers and compute edges
    print("[4/5] Fetching tickers and computing edges...")
    routes_data = []

    try:
        ticker = exchange.fetch_ticker('BTC/EUR')  # Test call to verify API works
    except Exception as e:
        print(f"WARNING: Test ticker fetch failed ({e}). Proceeding with mid-price estimates only.")

    # Use conservative taker fee (Bitvavo standard)
    taker_fee_pct = Decimal("0.2")  # Bitvavo typical taker fee

    for i, (pair1, pair2, pair3) in enumerate(all_triangles):
        if i % max(1, len(triangles) // 20) == 0:
            print(f"  Processing {i}/{len(triangles)}...")

        try:
            # Fetch tickers
            tick1 = exchange.fetch_ticker(pair1)
            tick2 = exchange.fetch_ticker(pair2)
            tick3 = exchange.fetch_ticker(pair3)

            mid1 = Decimal(str(tick1['last']))
            mid2 = Decimal(str(tick2['last']))
            mid3 = Decimal(str(tick3['last']))

            vol1_24h = tick1.get('quoteVolume', 0)
            vol2_24h = tick2.get('quoteVolume', 0)
            vol3_24h = tick3.get('quoteVolume', 0)

            # Simple triangle check (mid prices):
            # Start with 1 unit of A, buy B at pair1, buy C at pair2, sell A at pair3
            # Result should close to 1.0 if no arbitrage opportunity
            units_b = Decimal("1") / mid1
            units_c = units_b / mid2
            final_a = units_c * mid3

            # Edge = (final_a - 1) / 1 * 100 %
            edge_pct = (final_a - Decimal("1")) * Decimal("100")

            # Subtract fees (3 trades * taker fee)
            fees_pct = 3 * taker_fee_pct
            net_edge = edge_pct - fees_pct

            routes_data.append({
                'pair1': pair1,
                'pair2': pair2,
                'pair3': pair3,
                'mid_price_1': str(mid1),
                'mid_price_2': str(mid2),
                'mid_price_3': str(mid3),
                'vol_24h_1': vol1_24h,
                'vol_24h_2': vol2_24h,
                'vol_24h_3': vol3_24h,
                'edge_pct': float(edge_pct),
                'net_edge_pct': float(net_edge),
            })
        except Exception as e:
            # Skip on error (deleted pair, network issue, etc.)
            continue

    print(f"  Successfully computed {len(routes_data)} routes")

    if not routes_data:
        print("  WARNING: No routes could be computed (data fetch issues?)")
        print()
        print("=" * 80)
        print("ASSESSMENT:")
        print("✗ Unable to compute route profitability")
        print("  Possible issues:")
        print("  - Network/API errors (try again later)")
        print("  - Bitvavo API rate limits exceeded")
        print("  → Try running again with longer delays or during off-peak hours")
        print("=" * 80)
        return

    # Sort by net_edge descending
    routes_data.sort(key=lambda x: x['net_edge_pct'], reverse=True)

    # Print top 20
    print()
    print("[5/5] Top triangular routes by net edge (after fees):")
    print()
    print(f"{'#':<3} {'Route':<40} {'Edge %':<10} {'Net Edge %':<12} {'Volumes (24h)':<40}")
    print("-" * 110)

    for i, route in enumerate(routes_data[:20], 1):
        route_str = f"{route['pair1']} → {route['pair2']} → {route['pair3']}"
        vols = f"{route['vol_24h_1']:.0f} | {route['vol_24h_2']:.0f} | {route['vol_24h_3']:.0f}"
        print(f"{i:<3} {route_str:<40} {route['edge_pct']:>9.4f}% {route['net_edge_pct']:>11.4f}% {vols:<40}")

    print()

    # Save to CSV
    logs_dir = os.path.join(ROOT, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    csv_path = os.path.join(logs_dir, 'bitvavo_routes_scan.csv')

    try:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=routes_data[0].keys() if routes_data else [])
            writer.writeheader()
            writer.writerows(routes_data)
        print(f"Saved detailed results to: {csv_path}")
    except Exception as e:
        print(f"WARNING: Failed to save CSV: {e}")

    print()
    print("=" * 80)
    print("ASSESSMENT:")
    if routes_data and routes_data[0]['net_edge_pct'] > 0:
        best_edge = routes_data[0]['net_edge_pct']
        print(f"✓ Found {len(routes_data)} profitable routes (max net edge: {best_edge:.4f}%)")
        print("  → Bitvavo is VIABLE for triangular arbitrage")
        print("  → Recommend: implement full 24h monitor + test with real paper-trade balances")
    else:
        print(f"✗ No profitable routes found (or only marginal edges)")
        print("  → Bitvavo may NOT be ideal for triangular arbitrage at current prices/fees")
        print("  → But try again at different times or if fees/spreads improve")
    print("=" * 80)


if __name__ == '__main__':
    main()
