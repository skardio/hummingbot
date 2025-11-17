#!/usr/bin/env python3
"""Find top N triangular routes on Kraken that start from specified assets.

This re-uses the Kraken AssetPairs mapping helper from
`scripts/triangular_arbitrage_bot.py` to enumerate Hummingbot-style pairs
and then queries Kraken's Ticker endpoint to estimate 24h liquidity.

Output: writes JSON files to `logs/top20_routes_<ASSET>.json` and prints a
short summary to stdout.
"""
import json
import math
import os
import time
import urllib.request
from collections import defaultdict
from typing import List


def _fetch_kraken_hb_pairs_local() -> dict:
    """Fetch Kraken AssetPairs and build a mapping of HB-style 'BASE-QUOTE' -> kraken pair code.

    This mirrors the logic in the triangular_arbitrage_bot helper but is self-contained.
    """
    try:
        url = 'https://api.kraken.com/0/public/AssetPairs'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        pairs = data.get('result', {})
        hb_map = {}
        # Try to map using wsname if available
        for pair_code, info in pairs.items():
            ws = info.get('wsname')
            if ws and '/' in ws:
                parts = ws.split('/')
                if len(parts) == 2:
                    base_hb = parts[0].upper()
                    quote_hb = parts[1].upper()
                    hb = f"{base_hb}-{quote_hb}"
                    hb_map[hb] = pair_code
                    continue
        # Fallback pass using Assets endpoint mapping
        try:
            assets_resp = json.load(urllib.request.urlopen('https://api.kraken.com/0/public/Assets', timeout=10))
            assets = {k: v.get('altname', k).upper() for k, v in assets_resp.get('result', {}).items()}
        except Exception:
            assets = {}
        for pair_code, info in pairs.items():
            try:
                base = info.get('base')
                quote = info.get('quote')
                if base in assets and quote in assets:
                    base_hb = assets[base].upper()
                    quote_hb = assets[quote].upper()
                    hb = f"{base_hb}-{quote_hb}"
                    hb_map[hb] = pair_code
            except Exception:
                continue

        return hb_map
    except Exception:
        return {}


def fetch_ticker_for_kraken_pair(kr_pair: str):
    """Return parsed ticker dict for kraken pair or None on failure."""
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={urllib.request.quote(kr_pair)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        res = data.get("result") or {}
        if not res:
            return None
        # get first entry
        first = next(iter(res.values()))
        # volume: 'v' -> [today, last24h]
        vol_24 = None
        if first.get('v'):
            try:
                vol_24 = float(first.get('v')[1])
            except Exception:
                try:
                    vol_24 = float(first.get('v')[0])
                except Exception:
                    vol_24 = None

        # mid price from bid/ask if available
        bid = float(first.get('b', [None])[0]) if first.get('b') else None
        ask = float(first.get('a', [None])[0]) if first.get('a') else None
        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        else:
            # fallback to last trade 'c'
            last = first.get('c', [None])[0] if first.get('c') else None
            mid = float(last) if last is not None else None

        return {"vol_24": vol_24, "mid": mid, "raw": first}
    except Exception:
        return None


def enumerate_triangles(hb_pairs_map: dict) -> List[List[str]]:
    """Enumerate triples [A-B, B-C, A-C] where all three HB pair keys exist in hb_pairs_map."""
    assets = set()
    pair_exists = set(hb_pairs_map.keys())
    pair_by_assets = defaultdict(set)
    for p in pair_exists:
        a, b = p.split('-')
        assets.add(a)
        assets.add(b)
        pair_by_assets[(a, b)].add(p)

    triples = []
    assets_list = list(assets)
    for A in assets_list:
        for B in assets_list:
            if B == A:
                continue
            for C in assets_list:
                if C == A or C == B:
                    continue
                p_ab = f"{A}-{B}"
                p_bc = f"{B}-{C}"
                p_ac = f"{A}-{C}"
                if p_ab in pair_exists and p_bc in pair_exists and p_ac in pair_exists:
                    triples.append([p_ab, p_bc, p_ac])
    return triples


def score_route(triple: List[str], hb2kr: dict):
    """Compute a simple liquidity score for triple using Kraken ticker: min(volume*mid) across the three pairs."""
    scores = []
    for hb in triple:
        kr = hb2kr.get(hb)
        if not kr:
            return 0.0
        t = fetch_ticker_for_kraken_pair(kr)
        if not t or t.get('vol_24') is None or t.get('mid') is None:
            return 0.0
        vol_usd_equiv = t['vol_24'] * t['mid']
        scores.append(vol_usd_equiv)
        # be polite to Kraken public API
        time.sleep(0.1)
    if not scores:
        return 0.0
    # use minimum leg liquidity as bottleneck
    return float(min(scores))


def main():
    hb2kr = _fetch_kraken_hb_pairs_local()
    if not hb2kr:
        print("Failed to fetch Kraken mapping; aborting.")
        return

    triples = enumerate_triangles(hb2kr)
    print(f"Found {len(triples)} candidate triangular triples on Kraken (HB-style pairs).")

    # Filter for starting assets: major currencies for maximum coverage
    starts = ["ETH", "USDC", "EUR", "USD", "GBP", "CAD", "AUD", "CHF"]
    results = {s: [] for s in starts}

    # Precompute triples that start with given asset (first pair base == start)
    for t in triples:
        first_base = t[0].split('-')[0]
        if first_base in starts:
            results[first_base].append(t)

    os.makedirs('logs', exist_ok=True)

    for s in starts:
        routes = results[s]
        print(f"\nScanning {len(routes)} routes that start with {s}... this may take a minute")
        scored = []
        for i, r in enumerate(routes):
            sc = score_route(r, hb2kr)
            if sc > 0:
                scored.append((sc, r))
        # sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        top20 = [r for _, r in scored][:20]
        out_path = os.path.join('logs', f'top20_routes_{s}.json')
        with open(out_path, 'w') as f:
            json.dump([{'route': r, 'score': sc} for sc, r in scored[:20]], f, indent=2)
        print(f"Wrote top {min(20, len(scored))} routes for {s} to {out_path}")
        for rank, (sc, r) in enumerate(scored[:20], start=1):
            print(f"{rank:2d}. {r}  score~{sc:.0f}")


if __name__ == '__main__':
    main()
