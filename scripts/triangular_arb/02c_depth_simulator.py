#!/usr/bin/env python3
"""Depth-based REST orderbook simulator for configured triples.

Reads CONFIG from scripts/triangular_arbitrage_bot.py, fetches Kraken pair mapping (cached),
queries order book depth for each pair and simulates fills for order_amount (base A).
Writes results to logs/tri_depth.log and a CSV-like summary.
"""
import importlib.util
import json
import os
import urllib.request
from datetime import datetime
from decimal import Decimal, getcontext

# increase decimal precision for price math
getcontext().prec = 18

# load the triangular_arbitrage_bot module without running it as __main__
script_dir = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tri_bot", os.path.join(script_dir, "03_monitor_continuous_24h.py"))
tri_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tri_mod)

CONFIG = tri_mod.CONFIG
EXCHANGE = CONFIG.get("exchange", "kraken")
TRIPLES = CONFIG.get("triples", [])
ORDER_AMOUNT = CONFIG.get("order_amount", Decimal("0.03"))
TAKER_FEE = (CONFIG.get("taker_fee_pct", Decimal("0")) / Decimal("100"))

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "tri_depth.log")


def fetch_kraken_hb_pairs():
    # use the existing helper (it has an internal cache)
    return tri_mod._fetch_kraken_hb_pairs()


def fetch_order_book(kr_pair: str, depth: int = 200):
    url = f"https://api.kraken.com/0/public/Depth?pair={urllib.parse.quote(kr_pair)}&count={depth}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    res = data.get("result") or {}
    if not res:
        raise Exception("Empty depth result from Kraken")
    first = next(iter(res.values()))
    # bids and asks lists of [price, vol, ...]
    bids = [(Decimal(str(p[0])), Decimal(str(p[2]))) for p in first.get("b", [])]
    asks = [(Decimal(str(p[0])), Decimal(str(p[2]))) for p in first.get("a", [])]
    return bids, asks


def simulate_cycle(triple, hb2kr_map, amount_a: Decimal):
    # triple: [A-B, B-C, A-C]
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
        # sell base for quote using bids
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
        # apply taker fee on received quote
        received_quote_after_fee = received_quote * (Decimal('1') - TAKER_FEE)
        return received_quote_after_fee, filled, bids[:depth_used]

    def sell_quote_via_bids(pair_hb, amount_quote):
        # selling quote B for C: treating quote as 'base' for B-C pair? Actually trading B-C where B is base.
        # Here amount_quote is B amount in base B units -> sell as base across bids
        kr = hb2kr_map.get(pair_hb)
        if not kr:
            raise Exception(f"No Kraken mapping for {pair_hb}")
        bids, asks = fetch_order_book(kr)
        remaining = amount_quote
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
        received_after_fee = received_quote * (Decimal('1') - TAKER_FEE)
        return received_after_fee, filled, bids[:depth_used]

    def buy_base_via_asks(pair_hb, amount_quote):
        # buy base using quote via asks; amount_quote is quote currency available
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
                # partial fill
                base_buy = remaining_funds / price
                total_base_bought += base_buy
                remaining_funds = Decimal('0')
                depth_used += 1
                break
        bought_after_fee = total_base_bought * (Decimal('1') - TAKER_FEE)
        filled = (remaining_funds == 0)
        return bought_after_fee, filled, asks[:depth_used]

    try:
        hb2kr = hb2kr_map
        # leg A->B: sell A (base) on A-B bids -> receive B
        amount_b, filled_ab, depth_ab = sell_base_via_bids(a_b, amount_a)
        report['legs']['A->B'] = {"received_b_after_fee": str(amount_b), "filled": filled_ab}

        # leg B->C: sell B (base) on B-C bids -> receive C
        amount_c, filled_bc, depth_bc = sell_base_via_bids(b_c, amount_b)
        report['legs']['B->C'] = {"received_c_after_fee": str(amount_c), "filled": filled_bc}

        # leg C->A: buy A with C at A-C asks
        amount_a_final, filled_ca, depth_ca = buy_base_via_asks(a_c, amount_c)
        report['legs']['C->A'] = {"final_a_after_fee": str(amount_a_final), "filled": filled_ca}

        report['final_a'] = str(amount_a_final)
        profit = amount_a_final - amount_a
        report['profit_a'] = str(profit)
        try:
            report['profit_pct'] = str((profit / amount_a) * Decimal('100'))
        except Exception:
            report['profit_pct'] = None
        # if any leg not fully filled, note it
        if not (filled_ab and filled_bc and filled_ca):
            report['status'] = 'partial_fill_or_insufficient_depth'
            report['notes'].append('One or more legs not fully filled by top depth')
    except Exception as e:
        report['status'] = 'error'
        report['notes'].append(str(e))

    return report


def main():
    hb2kr = fetch_kraken_hb_pairs()
    # write header for human log
    with open(LOG_FILE, 'a') as lf:
        lf.write(f"\n--- Depth simulation run at {datetime.utcnow().isoformat()} ---\n")

    summaries = []
    for triple in TRIPLES:
        try:
            rep = simulate_cycle(triple, hb2kr, ORDER_AMOUNT)
        except Exception as e:
            rep = {"triple": triple, "status": "error", "notes": [str(e)]}
        # write to log
        with open(LOG_FILE, 'a') as lf:
            lf.write(json.dumps(rep) + "\n")
        summaries.append(rep)

    # also write a compact CSV-like summary
    csv_file = os.path.join(LOG_DIR, 'tri_depth_summary.csv')
    with open(csv_file, 'w') as cf:
        cf.write('triple,order_amount_a,final_a,profit_a,profit_pct,status,notes\n')
        for s in summaries:
            triple = '|'.join(s.get('triple', []))
            cf.write(','.join([
                triple,
                s.get('order_amount_a', ''),
                s.get('final_a', ''),
                s.get('profit_a', ''),
                s.get('profit_pct', ''),
                s.get('status', ''),
                '"' + ';'.join(s.get('notes', [])) + '"'
            ]) + '\n')

    print(f"Depth simulation complete. Logs: {LOG_FILE}, summary: {csv_file}")


if __name__ == '__main__':
    main()
