#!/usr/bin/env python3
"""Filter top20 routes by non-empty Kraken Depth and re-run depth-sim on those.

Checks A->B bids, B->C bids, A->C asks are non-empty. If all three legs have depth,
runs the local simulate_cycle and writes JSONL + CSV summaries to logs/.
"""
# Reuse functions from run_depth_on_top20.py by importing it as a module
import importlib.util
import json
import os
import time
import urllib.request
from decimal import Decimal
from runpy import run_path

ROOT = os.getcwd()
LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# load 02a_simulate_with_depth as module to access helpers
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('rd', os.path.join(script_dir, '02a_simulate_with_depth.py'))
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def pair_has_bids(kr_pair: str, count: int = 200) -> bool:
    try:
        url = f"https://api.kraken.com/0/public/Depth?pair={urllib.request.quote(kr_pair)}&count={count}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        res = data.get('result') or {}
        if not res:
            return False
        first = next(iter(res.values()))
        return len(first.get('b', [])) > 0
    except Exception:
        return False


def pair_has_asks(kr_pair: str, count: int = 200) -> bool:
    try:
        url = f"https://api.kraken.com/0/public/Depth?pair={urllib.request.quote(kr_pair)}&count={count}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        res = data.get('result') or {}
        if not res:
            return False
        first = next(iter(res.values()))
        return len(first.get('a', [])) > 0
    except Exception:
        return False


def process_start(start_asset: str, eur_amount: float):
    in_path = os.path.join(LOG_DIR, f'top20_routes_{start_asset}.json')
    if not os.path.exists(in_path):
        print(f"Missing {in_path}; run find_top20_routes_from_assets.py first")
        return
    with open(in_path, 'r') as f:
        data = json.load(f)

    hb2kr = rd.fetch_kraken_hb_pairs_local()
    out_jsonl = os.path.join(LOG_DIR, f'filtered_tri_depth_{start_asset}.jsonl')
    out_csv = os.path.join(LOG_DIR, f'filtered_tri_depth_{start_asset}_summary.csv')
    filtered = []

    for entry in data:
        route = entry.get('route') if isinstance(entry, dict) else entry
        a_b, b_c, a_c = route
        kr_ab = hb2kr.get(a_b)
        kr_bc = hb2kr.get(b_c)
        kr_ac = hb2kr.get(a_c)
        if not (kr_ab and kr_bc and kr_ac):
            continue
        # Check A->B bids, B->C bids, A->C asks
        has_ab = pair_has_bids(kr_ab, count=200)
        has_bc = pair_has_bids(kr_bc, count=200)
        has_ac = pair_has_asks(kr_ac, count=200)
        if has_ab and has_bc and has_ac:
            filtered.append(route)
        # be polite
        time.sleep(0.2)

    print(f"{len(filtered)} routes passed depth-presence checks for start {start_asset}")

    # simulate on filtered
    with open(out_jsonl, 'w') as jf, open(out_csv, 'w') as cf:
        cf.write('rank,route,order_amount_a,final_a,profit_a,profit_pct,status,notes\n')
        for rank, route in enumerate(filtered, start=1):
            A = route[0].split('-')[0]
            amount_a = rd.compute_start_amount_for_asset(A, eur_amount, hb2kr)
            if amount_a is None:
                print(f"Cannot compute start amount for {A}, skipping {route}")
                continue
            rep = rd.simulate_cycle_local(route, hb2kr, Decimal(str(amount_a)))
            rep['computed_order_amount_a'] = str(amount_a)
            jf.write(json.dumps(rep) + '\n')
            triple = '|'.join(route)
            cf.write(','.join([
                str(rank),
                f'"{triple}"',
                str(amount_a),
                rep.get('final_a', ''),
                rep.get('profit_a', ''),
                rep.get('profit_pct', ''),
                rep.get('status', ''),
                '"' + ';'.join(rep.get('notes', [])) + '"'
            ]) + '\n')
            print(f"Simulated {start_asset} route rank {rank}: {route} status={rep.get('status')}")
            time.sleep(0.1)


def main():
    eur_amount = 50.0
    process_start('ETH', eur_amount)
    process_start('USDC', eur_amount)
    print('Filtered simulation complete. Check logs/filtered_tri_depth_*.jsonl and *_summary.csv')


if __name__ == '__main__':
    main()
