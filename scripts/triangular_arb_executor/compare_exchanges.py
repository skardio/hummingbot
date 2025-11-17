#!/usr/bin/env python3
"""
Analyze and compare triangular arbitrage candidates from Kraken and Bitstamp logs.

Usage:
  python3 scripts/compare_exchanges.py

Output:
  - Statistics (candidate count, edge distribution)
  - Top 10 routes by edge % for each exchange
  - Pair overlap analysis
  - Side-by-side comparison
"""

import json
import os
from collections import Counter, defaultdict
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def load_candidates(log_file):
    """Load candidates from JSON log file (newline-separated JSON objects)."""
    candidates = []
    if not os.path.exists(log_file):
        return candidates

    try:
        with open(log_file, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        candidates.append(record)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        print(f"Warning: Failed to load {log_file}: {e}")

    return candidates


def analyze_candidates(candidates, exchange_name):
    """Compute statistics on candidates."""
    if not candidates:
        return None

    edges = [c.get('edge_pct', 0) for c in candidates]
    triples = [tuple(c.get('triple', [])) for c in candidates]

    stats = {
        'exchange': exchange_name,
        'total_candidates': len(candidates),
        'unique_routes': len(set(triples)),
        'avg_edge_pct': sum(edges) / len(edges),
        'max_edge_pct': max(edges),
        'min_edge_pct': min(edges),
        'median_edge_pct': sorted(edges)[len(edges) // 2],
        'candidates_profitable_0_1': sum(1 for e in edges if e > 0.1),
        'candidates_profitable_0_05': sum(1 for e in edges if e > 0.05),
        'candidates_profitable_0_01': sum(1 for e in edges if e > 0.01),
    }
    return stats


def get_top_candidates(candidates, n=10):
    """Get top N candidates by edge %."""
    sorted_cands = sorted(candidates, key=lambda c: c.get('edge_pct', 0), reverse=True)
    return sorted_cands[:n]


def extract_currencies(triple):
    """Extract unique currencies from a triple."""
    if not triple:
        return set()
    currencies = set()
    for pair in triple:
        try:
            base, quote = pair.split('-')
            currencies.add(base)
            currencies.add(quote)
        except:
            pass
    return currencies


def main():
    print("=" * 100)
    print("KRAKEN vs BITSTAMP - TRIANGULAR ARBITRAGE COMPARISON")
    print("=" * 100)
    print()

    logs_dir = os.path.join(ROOT, 'logs')
    kraken_log = os.path.join(logs_dir, 'tri_candidates.log')
    bitstamp_log = os.path.join(logs_dir, 'tri_candidates_bitstamp.log')

    # Load candidates
    print("[1/4] Loading candidate logs...")
    kraken_cands = load_candidates(kraken_log)
    bitstamp_cands = load_candidates(bitstamp_log)
    print(f"  Kraken: {len(kraken_cands)} candidates")
    print(f"  Bitstamp: {len(bitstamp_cands)} candidates")
    print()

    # Analyze
    print("[2/4] Analyzing statistics...")
    kraken_stats = analyze_candidates(kraken_cands, "Kraken")
    bitstamp_stats = analyze_candidates(bitstamp_cands, "Bitstamp")

    if not kraken_stats or not bitstamp_stats:
        print("ERROR: Could not load candidate data. Logs may be empty or corrupted.")
        return

    print(f"{'Metric':<40} {'Kraken':<20} {'Bitstamp':<20}")
    print("-" * 80)
    for key in ['total_candidates', 'unique_routes', 'avg_edge_pct', 'max_edge_pct',
                'candidates_profitable_0_1', 'candidates_profitable_0_05']:
        k_val = kraken_stats.get(key, 'N/A')
        b_val = bitstamp_stats.get(key, 'N/A')

        if isinstance(k_val, float):
            print(f"{key:<40} {k_val:<20.6f} {b_val:<20.6f}")
        else:
            print(f"{key:<40} {str(k_val):<20} {str(b_val):<20}")
    print()

    # Top candidates
    print("[3/4] Top 10 candidates by edge %...")
    print()

    kraken_top = get_top_candidates(kraken_cands, 10)
    bitstamp_top = get_top_candidates(bitstamp_cands, 10)

    print(f"{'#':<3} {'Kraken Route':<45} {'Edge %':<12} {'Bitstamp Route':<45} {'Edge %':<12}")
    print("-" * 120)

    max_len = max(len(kraken_top), len(bitstamp_top))
    for i in range(max_len):
        k_idx = i if i < len(kraken_top) else None
        b_idx = i if i < len(bitstamp_top) else None

        k_route = " → ".join(kraken_top[k_idx]['triple']) if k_idx is not None else ""
        k_edge = f"{kraken_top[k_idx]['edge_pct']:.6f}%" if k_idx is not None else ""

        b_route = " → ".join(bitstamp_top[b_idx]['triple']) if b_idx is not None else ""
        b_edge = f"{bitstamp_top[b_idx]['edge_pct']:.6f}%" if b_idx is not None else ""

        print(f"{i + 1:<3} {k_route:<45} {k_edge:<12} {b_route:<45} {b_edge:<12}")
    print()

    # Currency overlap
    print("[4/4] Currency overlap analysis...")

    kraken_currencies = set()
    for c in kraken_cands:
        for cur in extract_currencies(c.get('triple', [])):
            kraken_currencies.add(cur)

    bitstamp_currencies = set()
    for c in bitstamp_cands:
        for cur in extract_currencies(c.get('triple', [])):
            bitstamp_currencies.add(cur)

    overlap = kraken_currencies & bitstamp_currencies

    print(f"  Kraken active currencies: {len(kraken_currencies)} → {sorted(kraken_currencies)[:15]}{'...' if len(kraken_currencies) > 15 else ''}")
    print(f"  Bitstamp active currencies: {len(bitstamp_currencies)} → {sorted(bitstamp_currencies)[:15]}{'...' if len(bitstamp_currencies) > 15 else ''}")
    print(f"  Overlapping currencies: {len(overlap)} → {sorted(overlap)}")
    print()

    # Summary & recommendations
    print("=" * 100)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 100)
    print()

    if kraken_stats['max_edge_pct'] > 0.1:
        print(f"✓ Kraken: Found {kraken_stats['candidates_profitable_0_1']} opportunities > 0.1% edge (max: {kraken_stats['max_edge_pct']:.4f}%)")
    else:
        print(f"○ Kraken: Max edge is {kraken_stats['max_edge_pct']:.4f}% (marginal, < 0.1%)")

    if bitstamp_stats['max_edge_pct'] > 0.1:
        print(f"✓ Bitstamp: Found {bitstamp_stats['candidates_profitable_0_1']} opportunities > 0.1% edge (max: {bitstamp_stats['max_edge_pct']:.4f}%)")
    else:
        print(f"○ Bitstamp: Max edge is {bitstamp_stats['max_edge_pct']:.4f}% (marginal, < 0.1%)")

    print()

    if kraken_stats['max_edge_pct'] > bitstamp_stats['max_edge_pct']:
        winner = "Kraken"
        diff = kraken_stats['max_edge_pct'] - bitstamp_stats['max_edge_pct']
    else:
        winner = "Bitstamp"
        diff = bitstamp_stats['max_edge_pct'] - kraken_stats['max_edge_pct']

    print(f"Best exchange: {winner} (by {diff:.4f}% edge difference)")
    print()
    print("Recommendations:")
    if kraken_stats['max_edge_pct'] > 0.15 or bitstamp_stats['max_edge_pct'] > 0.15:
        print("  1. Both exchanges show good arbitrage potential (> 0.15% net edge)")
        print("  2. Consider running live trades on the higher-edge exchange")
        print("  3. Monitor fee changes and liquidity to optimize execution")
    elif kraken_stats['max_edge_pct'] > 0.05 or bitstamp_stats['max_edge_pct'] > 0.05:
        print("  1. Moderate arbitrage potential found (0.05-0.15% edge)")
        print("  2. May be profitable but lower margin; careful with slippage/fees")
        print("  3. Continue monitoring for better opportunities")
    else:
        print("  1. Limited arbitrage potential (< 0.05% edge)")
        print("  2. Current market conditions may not support profitable live trading")
        print("  3. Wait for increased volatility or market moves")
    print()
    print("=" * 100)


if __name__ == '__main__':
    main()
