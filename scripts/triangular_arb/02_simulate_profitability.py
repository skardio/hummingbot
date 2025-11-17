#!/usr/bin/env python3
"""Simulate triangular routes using Kraken Ticker mid-prices (bid+ask)/2.

Since Kraken public Depth API returns empty orderbooks, we use Ticker mid-prices
and apply conservative slippage and taker fees per leg. This gives a realistic
estimate of profit/loss for a €50 trade through each route.

Output: logs/midprice_sim_ETH.jsonl, logs/midprice_sim_USDC_summary.csv, etc.
"""
import json
import os
import time
import urllib.request
from datetime import datetime
from decimal import Decimal

ROOT = os.getcwd()
LOG_DIR = os.path.join(ROOT, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

TAKER_FEE = Decimal('0.0026')  # 0.26%
SLIPPAGE_PER_LEG = Decimal('0.002')  # 0.2% conservative per leg


def fetch_kraken_hb_pairs_local() -> dict:
    """Fetch Kraken AssetPairs and build HB-style mapping."""
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
                    hb = f"{parts[0].upper()}-{parts[1].upper()}"
                    hb_map[hb] = pair_code
        return hb_map
    except Exception:
        return {}


def fetch_ticker_mid(kr_pair: str):
    """Return mid-price (bid+ask)/2 or None."""
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={urllib.request.quote(kr_pair)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        res = data.get('result') or {}
        if not res:
            return None
        first = next(iter(res.values()))
        bid = first.get('b', [None])[0] if first.get('b') else None
        ask = first.get('a', [None])[0] if first.get('a') else None
        if bid and ask:
            mid = (float(bid) + float(ask)) / 2.0
            return mid
        # fallback to last trade
        last = first.get('c', [None])[0] if first.get('c') else None
        if last:
            return float(last)
        return None
    except Exception:
        return None


def compute_start_amount_for_asset(asset: str, eur_amount: float, hb2kr: dict):
    """Convert EUR amount to base asset quantity using EUR-asset mid-price."""
    # try direct ASSET-EUR
    pair = f"{asset}-EUR"
    kr = hb2kr.get(pair)
    if kr:
        mid = fetch_ticker_mid(kr)
        if mid and mid > 0:
            return Decimal(str(eur_amount / mid))

    # fallback: ASSET-USD + EUR-USD
    pair_us = f"{asset}-USD"
    kr_us = hb2kr.get(pair_us)
    kr_eur_usd = hb2kr.get('EUR-USD')
    if kr_us and kr_eur_usd:
        mid_asset_usd = fetch_ticker_mid(kr_us)
        mid_eur_usd = fetch_ticker_mid(kr_eur_usd)
        if mid_asset_usd and mid_eur_usd and mid_asset_usd > 0:
            usd_amount = eur_amount * mid_eur_usd
            return Decimal(str(usd_amount / mid_asset_usd))

    # stablecoin fallback
    if asset in ('USDC', 'USDT'):
        kr_eur_usd = hb2kr.get('EUR-USD')
        if kr_eur_usd:
            mid_eur_usd = fetch_ticker_mid(kr_eur_usd)
            if mid_eur_usd and mid_eur_usd > 0:
                return Decimal(str(eur_amount * mid_eur_usd))

    return None


def simulate_via_midprices(route, hb2kr, amount_a: Decimal):
    """Simulate using Kraken Ticker mid-prices + slippage + taker fees."""
    a_b, b_c, a_c = route

    report = {
        "route": route,
        "timestamp": datetime.utcnow().isoformat(),
        "order_amount_a": str(amount_a),
        "legs": {},
        "final_a": None,
        "profit_a": None,
        "profit_pct": None,
        "status": "ok",
        "notes": [],
    }

    try:
        # get mid prices
        kr_ab = hb2kr.get(a_b)
        kr_bc = hb2kr.get(b_c)
        kr_ac = hb2kr.get(a_c)
        if not (kr_ab and kr_bc and kr_ac):
            raise Exception(f"Missing Kraken mapping for one or more pairs in {route}")

        mid_ab = fetch_ticker_mid(kr_ab)
        mid_bc = fetch_ticker_mid(kr_bc)
        mid_ac = fetch_ticker_mid(kr_ac)

        if not (mid_ab and mid_bc and mid_ac):
            raise Exception(f"Could not fetch all mid-prices for {route}")

        # A -> B: sell A at mid_ab * (1 - slippage), apply fee
        effective_ab = mid_ab * (1.0 - float(SLIPPAGE_PER_LEG))
        amount_b = float(amount_a) * effective_ab * (1.0 - float(TAKER_FEE))
        report['legs']['A->B'] = {
            "price_ab": mid_ab,
            "effective_ab": effective_ab,
            "received_b": amount_b
        }

        # B -> C: sell B at mid_bc * (1 - slippage), apply fee
        effective_bc = mid_bc * (1.0 - float(SLIPPAGE_PER_LEG))
        amount_c = amount_b * effective_bc * (1.0 - float(TAKER_FEE))
        report['legs']['B->C'] = {
            "price_bc": mid_bc,
            "effective_bc": effective_bc,
            "received_c": amount_c
        }

        # C -> A: buy A at mid_ac * (1 + slippage), apply fee (worse price)
        effective_ac = mid_ac * (1.0 + float(SLIPPAGE_PER_LEG))
        amount_a_final = (amount_c / effective_ac) * (1.0 - float(TAKER_FEE)) if effective_ac > 0 else 0.0
        report['legs']['C->A'] = {
            "price_ac": mid_ac,
            "effective_ac": effective_ac,
            "final_a": amount_a_final
        }

        report['final_a'] = str(Decimal(str(amount_a_final)))
        profit = Decimal(str(amount_a_final)) - amount_a
        report['profit_a'] = str(profit)
        if amount_a != 0:
            profit_pct = (profit / amount_a) * Decimal('100')
            report['profit_pct'] = str(profit_pct)

    except Exception as e:
        report['status'] = 'error'
        report['notes'].append(str(e))

    return report


def process_start(start_asset: str, eur_amount: float):
    in_path = os.path.join(LOG_DIR, f'top20_routes_{start_asset}.json')
    if not os.path.exists(in_path):
        print(f"Missing {in_path}")
        return

    with open(in_path, 'r') as f:
        data = json.load(f)

    hb2kr = fetch_kraken_hb_pairs_local()
    out_jsonl = os.path.join(LOG_DIR, f'midprice_sim_{start_asset}.jsonl')
    out_csv = os.path.join(LOG_DIR, f'midprice_sim_{start_asset}_summary.csv')

    positive_count = 0
    with open(out_jsonl, 'w') as jf, open(out_csv, 'w') as cf:
        cf.write('rank,route,order_amount_a,final_a,profit_a,profit_pct,status,notes\n')
        for rank, entry in enumerate(data, start=1):
            route = entry.get('route') if isinstance(entry, dict) else entry

            A = route[0].split('-')[0]
            amount_a = compute_start_amount_for_asset(A, eur_amount, hb2kr)
            if amount_a is None:
                continue

            rep = simulate_via_midprices(route, hb2kr, amount_a)
            jf.write(json.dumps(rep) + '\n')

            triple_str = '|'.join(route)
            cf.write(','.join([
                str(rank),
                f'"{triple_str}"',
                str(amount_a),
                rep.get('final_a', ''),
                rep.get('profit_a', ''),
                rep.get('profit_pct', ''),
                rep.get('status', ''),
                '"' + ';'.join(rep.get('notes', [])) + '"'
            ]) + '\n')

            # count positive profit
            try:
                pct_val = float(rep.get('profit_pct', '0'))
                if pct_val > 0:
                    positive_count += 1
                    print(f"✓ {start_asset} rank {rank}: {route} profit={pct_val:.4f}%")
                else:
                    print(f"✗ {start_asset} rank {rank}: {route} profit={pct_val:.4f}%")
            except Exception:
                print(f"? {start_asset} rank {rank}: {route} (parse error)")

            time.sleep(0.1)

    print(f"\nSummary for {start_asset}: {positive_count}/{len(data)} routes with positive profit")


def main():
    eur_amount = 50.0
    process_start('ETH', eur_amount)
    process_start('USDC', eur_amount)
    print("\nMid-price simulation complete. Check logs/midprice_sim_*.jsonl and *_summary.csv")


if __name__ == '__main__':
    main()
