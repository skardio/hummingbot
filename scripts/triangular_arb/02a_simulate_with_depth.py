#!/usr/bin/env python3
"""Run depth-based simulations for top20 routes (ETH and USDC) using €50 starting amounts.

This script loads `logs/top20_routes_ETH.json` and `logs/top20_routes_USDC.json` (created by
`find_top20_routes_from_assets.py`), computes how much base asset equals €50 using Kraken tickers
with fallbacks, then calls the existing `scripts/tri_depth_sim.py` simulation routine per route.

Outputs:
 - logs/tri_depth_top20_ETH.jsonl
 - logs/tri_depth_top20_USDC.jsonl
 - logs/tri_depth_top20_ETH_summary.csv
 - logs/tri_depth_top20_USDC_summary.csv
"""
import json
import os
import time
import urllib.request
from datetime import datetime
from decimal import Decimal, getcontext

getcontext().prec = 18

ROOT = os.getcwd()
LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# local copy of helper functions from tri_depth_sim to avoid importing hummingbot modules
TAKER_FEE = Decimal('0.0026')  # default fallback (0.26%) if not available from config


def fetch_kraken_hb_pairs_local() -> dict:
    try:
        url = 'https://api.kraken.com/0/public/AssetPairs'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        pairs = data.get('result', {})
        hb_map = {}
        for pair_code, info in pairs.items():
            ws = info.get('wsname')
            if ws and '/' in ws:
                parts = ws.split('/')
                if len(parts) == 2:
                    base_hb = parts[0].upper()
                    quote_hb = parts[1].upper()
                    hb = f"{base_hb}-{quote_hb}"
                    hb_map[hb] = pair_code
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


def fetch_order_book(kr_pair: str, depth: int = 200):
    url = f"https://api.kraken.com/0/public/Depth?pair={urllib.request.quote(kr_pair)}&count={depth}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    res = data.get('result') or {}
    if not res:
        raise Exception("Empty depth result from Kraken")
    first = next(iter(res.values()))
    bids = [(Decimal(str(p[0])), Decimal(str(p[2]))) for p in first.get('b', [])]
    asks = [(Decimal(str(p[0])), Decimal(str(p[2]))) for p in first.get('a', [])]
    return bids, asks


def simulate_cycle_local(triple, hb2kr_map, amount_a: Decimal, taker_fee: Decimal = TAKER_FEE):
    a_b, b_c, a_c = triple
    report = {
        "triple": triple,
        "timestamp": datetime.utcnow().isoformat(),
        "order_amount_a": str(amount_a),
        "legs": {},
        "final_a": None,
        "profit_a": None,
        "profit_pct": None,
        "status": "ok",
        "notes": [],
    }

    def sell_base_via_bids(pair_hb, amount_base):
        kr = hb2kr_map.get(pair_hb)
        if not kr:
            raise Exception(f"No Kraken mapping for {pair_hb}")
        bids, asks = fetch_order_book(kr)
        remaining = amount_base
        received_quote = Decimal('0')
        depth_used = 0
        for price, vol_base in bids:
            if remaining <= 0:
                break
            take = min(remaining, vol_base)
            received_quote += take * price
            remaining -= take
            depth_used += 1
        filled = (remaining == 0)
        received_quote_after_fee = received_quote * (Decimal('1') - taker_fee)
        return received_quote_after_fee, filled, bids[:depth_used]

    def buy_base_via_asks(pair_hb, amount_quote):
        kr = hb2kr_map.get(pair_hb)
        if not kr:
            raise Exception(f"No Kraken mapping for {pair_hb}")
        bids, asks = fetch_order_book(kr)
        remaining_funds = amount_quote
        total_base_bought = Decimal('0')
        depth_used = 0
        for price, vol_base in asks:
            if remaining_funds <= 0:
                break
            cost = price * vol_base
            if remaining_funds >= cost:
                total_base_bought += vol_base
                remaining_funds -= cost
                depth_used += 1
            else:
                base_buy = remaining_funds / price
                total_base_bought += base_buy
                remaining_funds = Decimal('0')
                depth_used += 1
                break
        bought_after_fee = total_base_bought * (Decimal('1') - taker_fee)
        filled = (remaining_funds == 0)
        return bought_after_fee, filled, asks[:depth_used]

    try:
        # A->B
        amount_b, filled_ab, depth_ab = sell_base_via_bids(a_b, amount_a)
        report['legs']['A->B'] = {"received_b_after_fee": str(amount_b), "filled": filled_ab}
        # B->C (sell base B)
        amount_c, filled_bc, depth_bc = sell_base_via_bids(b_c, amount_b)
        report['legs']['B->C'] = {"received_c_after_fee": str(amount_c), "filled": filled_bc}
        # C->A (buy A with C)
        amount_a_final, filled_ca, depth_ca = buy_base_via_asks(a_c, amount_c)
        report['legs']['C->A'] = {"final_a_after_fee": str(amount_a_final), "filled": filled_ca}
        report['final_a'] = str(amount_a_final)
        profit = amount_a_final - amount_a
        report['profit_a'] = str(profit)
        try:
            report['profit_pct'] = str((profit / amount_a) * Decimal('100'))
        except Exception:
            report['profit_pct'] = None
        if not (filled_ab and filled_bc and filled_ca):
            report['status'] = 'partial_fill_or_insufficient_depth'
            report['notes'].append('One or more legs not fully filled by top depth')
    except Exception as e:
        report['status'] = 'error'
        report['notes'].append(str(e))

    return report


def fetch_ticker(kr_pair: str):
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={urllib.request.quote(kr_pair)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        res = data.get('result') or {}
        if not res:
            return None
        first = next(iter(res.values()))
        bid = float(first.get('b', [None])[0]) if first.get('b') else None
        ask = float(first.get('a', [None])[0]) if first.get('a') else None
        vol24 = None
        if first.get('v'):
            try:
                vol24 = float(first.get('v')[1])
            except Exception:
                vol24 = float(first.get('v')[0])
        mid = None
        if bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        else:
            last = first.get('c', [None])[0] if first.get('c') else None
            mid = float(last) if last is not None else None
        return {'mid': mid, 'vol24': vol24}
    except Exception:
        return None


def compute_start_amount_for_asset(asset: str, eur_amount: float, hb2kr: dict):
    """Compute base-asset amount equivalent to eur_amount EUR.

    Prefer direct <ASSET>-EUR pair; fallback to <ASSET>-USD + EUR-USD conversion.
    Returns Decimal amount or None.
    """
    # try direct ASSET-EUR
    pair = f"{asset}-EUR"
    kr = hb2kr.get(pair)
    if kr:
        t = fetch_ticker(kr)
        if t and t.get('mid'):
            mid = t['mid']
            return Decimal(str(eur_amount / mid))

    # fallback: ASSET-USD and EUR-USD
    pair_us = f"{asset}-USD"
    kr_us = hb2kr.get(pair_us)
    eur_us_kr = hb2kr.get('EUR-USD') or hb2kr.get('EURUSD')
    if kr_us and eur_us_kr:
        t1 = fetch_ticker(kr_us)
        t2 = fetch_ticker(eur_us_kr)
        if t1 and t2 and t1.get('mid') and t2.get('mid'):
            mid_asset_usd = t1['mid']
            mid_eur_usd = t2['mid']
            # EUR -> USD: multiply by mid_eur_usd (EUR in USD), then USD -> asset: divide
            usd_amount = eur_amount * mid_eur_usd
            return Decimal(str(usd_amount / mid_asset_usd))

    # Last resort: if asset is stablecoin-like (USDC) assume 1:1 to USD and map EUR->USD
    if asset in ('USDC', 'USDT'):
        # try EUR-USD ticker
        eur_us = hb2kr.get('EUR-USD') or hb2kr.get('EURUSD')
        if eur_us:
            t = fetch_ticker(eur_us)
            if t and t.get('mid'):
                mid = t['mid']
                usd_equiv = eur_amount * mid
                return Decimal(str(usd_equiv))

    return None


def run_for_start(start_asset: str, eur_amount: float):
    in_path = os.path.join(LOG_DIR, f'top20_routes_{start_asset}.json')
    if not os.path.exists(in_path):
        print(f"Missing {in_path}, run find_top20_routes_from_assets.py first")
        return
    with open(in_path, 'r') as f:
        data = json.load(f)
    hb2kr = fetch_kraken_hb_pairs_local()
    out_jsonl = os.path.join(LOG_DIR, f'tri_depth_top20_{start_asset}.jsonl')
    out_csv = os.path.join(LOG_DIR, f'tri_depth_top20_{start_asset}_summary.csv')
    with open(out_jsonl, 'w') as jf, open(out_csv, 'w') as cf:
        cf.write('rank,route,order_amount_a,final_a,profit_a,profit_pct,status,notes\n')
        for rank, entry in enumerate(data, start=1):
            route = entry.get('route') if isinstance(entry, dict) else entry
            # compute amount_a in base A units
            A = route[0].split('-')[0]
            amount_a = compute_start_amount_for_asset(A, eur_amount, hb2kr)
            if amount_a is None:
                note = 'could_not_compute_start_amount'
                print(f"Skipping route {route} because start amount for {A} could not be computed")
                jf.write(json.dumps({'route': route, 'status': 'skipped', 'note': note}) + '\n')
                cf.write(f"{rank},'{route}',,,,'skipped','{note}'\n")
                continue
            # small sleep to avoid hammering Kraken
            time.sleep(0.1)
            # run simulate_cycle from tri_depth_sim module
            try:
                rep = simulate_cycle_local(route, hb2kr, Decimal(str(amount_a)))
            except Exception as e:
                rep = {'route': route, 'status': 'error', 'notes': [str(e)]}
            # augment with computed amount
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
            print(f"Done {start_asset} rank {rank}: route={route} status={rep.get('status')}")


def main():
    # user specified amounts in EUR
    eur_amount = 50.0
    # run for ETH and USDC
    run_for_start('ETH', eur_amount)
    run_for_start('USDC', eur_amount)
    print('All done. Check logs/*.jsonl and *_summary.csv for results')


if __name__ == '__main__':
    main()
