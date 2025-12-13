#!/usr/bin/env python3
"""
Bitget Triangular Arbitrage - Profitability Simulator

Simulates real profitability including:
- Actual bid/ask spreads
- Order book depth
- Trading fees

Fee structure (Bitget Spot VIP0):
  - Taker: 0.10% per trade
  - Total: 0.30% for 3 trades

Usage:
  python3 scripts/triangular_arb_bitget/02_simulate_profitability.py
"""

import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import ccxt
except ImportError:
    print("❌ ccxt not installed. Run: pip install ccxt")
    sys.exit(1)


class ProfitabilitySimulator:
    """Simulate triangular arbitrage profitability on Bitget."""

    # Bitget fees
    TAKER_FEE = Decimal("0.001")  # 0.10%

    def __init__(self):
        self.exchange = ccxt.bitget({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        self.exchange.load_markets()

    def get_order_book_depth(self, symbol: str, limit: int = 10) -> Optional[Dict]:
        """Fetch order book for a symbol."""
        try:
            ob = self.exchange.fetch_order_book(symbol, limit=limit)
            return {
                'bids': [(Decimal(str(p)), Decimal(str(a))) for p, a in ob['bids'][:limit]],
                'asks': [(Decimal(str(p)), Decimal(str(a))) for p, a in ob['asks'][:limit]],
            }
        except Exception as e:
            print(f"   ⚠️ Failed to fetch order book for {symbol}: {e}")
            return None

    def simulate_market_buy(self, order_book: Dict, spend_amount: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Simulate a market buy order.
        Returns: (amount_received, effective_price)
        """
        asks = order_book['asks']
        remaining = spend_amount
        received = Decimal("0")

        for price, size in asks:
            if remaining <= 0:
                break
            cost = price * size
            if cost <= remaining:
                received += size
                remaining -= cost
            else:
                # Partial fill
                partial_size = remaining / price
                received += partial_size
                remaining = Decimal("0")

        if received > 0:
            effective_price = spend_amount / received
            # Apply taker fee
            received_after_fee = received * (Decimal("1") - self.TAKER_FEE)
            return received_after_fee, effective_price
        return Decimal("0"), Decimal("0")

    def simulate_market_sell(self, order_book: Dict, sell_amount: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Simulate a market sell order.
        Returns: (usdt_received, effective_price)
        """
        bids = order_book['bids']
        remaining = sell_amount
        received = Decimal("0")

        for price, size in bids:
            if remaining <= 0:
                break
            if size <= remaining:
                received += size * price
                remaining -= size
            else:
                # Partial fill
                received += remaining * price
                remaining = Decimal("0")

        if received > 0:
            effective_price = received / sell_amount
            # Apply taker fee
            received_after_fee = received * (Decimal("1") - self.TAKER_FEE)
            return received_after_fee, effective_price
        return Decimal("0"), Decimal("0")

    def simulate_triangle(self, triangle: Tuple[str, str, str],
                          start_amount_usdt: Decimal = Decimal("100")) -> Dict:
        """
        Simulate a full triangular trade.

        Triangle: (pair1, pair2, pair3)
        Example: BTC/USDT, ETH/BTC, ETH/USDT

        Flow:
          1. Buy BTC with USDT (buy on pair1)
          2. Buy ETH with BTC (buy on pair2)
          3. Sell ETH for USDT (sell on pair3)
        """
        pair1, pair2, pair3 = triangle

        # Fetch order books
        ob1 = self.get_order_book_depth(pair1)
        ob2 = self.get_order_book_depth(pair2)
        ob3 = self.get_order_book_depth(pair3)

        if not all([ob1, ob2, ob3]):
            return {
                'success': False,
                'error': 'Failed to fetch order books',
                'triangle': triangle,
            }

        # Step 1: Buy asset1 with USDT
        asset1_received, price1 = self.simulate_market_buy(ob1, start_amount_usdt)

        if asset1_received <= 0:
            return {
                'success': False,
                'error': f'Insufficient liquidity on {pair1}',
                'triangle': triangle,
            }

        # Step 2: Buy asset2 with asset1
        # We need to calculate how much asset1 to spend
        # For pair2 (e.g., ETH/BTC), we're buying ETH with BTC
        asset2_received, price2 = self.simulate_market_buy(ob2, asset1_received)

        if asset2_received <= 0:
            return {
                'success': False,
                'error': f'Insufficient liquidity on {pair2}',
                'triangle': triangle,
            }

        # Step 3: Sell asset2 for USDT
        final_usdt, price3 = self.simulate_market_sell(ob3, asset2_received)

        if final_usdt <= 0:
            return {
                'success': False,
                'error': f'Insufficient liquidity on {pair3}',
                'triangle': triangle,
            }

        # Calculate profit
        profit_usdt = final_usdt - start_amount_usdt
        profit_pct = (profit_usdt / start_amount_usdt) * Decimal("100")

        # Calculate implied spreads
        spread1 = self._calculate_spread(ob1)
        spread2 = self._calculate_spread(ob2)
        spread3 = self._calculate_spread(ob3)

        return {
            'success': True,
            'triangle': triangle,
            'start_usdt': float(start_amount_usdt),
            'final_usdt': float(final_usdt),
            'profit_usdt': float(profit_usdt),
            'profit_pct': float(profit_pct),
            'prices': {
                'leg1': float(price1),
                'leg2': float(price2),
                'leg3': float(price3),
            },
            'spreads_pct': {
                'leg1': float(spread1),
                'leg2': float(spread2),
                'leg3': float(spread3),
            },
            'fees_paid_pct': float(self.TAKER_FEE * 3 * 100),
            'amounts': {
                'asset1_received': float(asset1_received),
                'asset2_received': float(asset2_received),
            }
        }

    def _calculate_spread(self, order_book: Dict) -> Decimal:
        """Calculate bid-ask spread percentage."""
        if not order_book['bids'] or not order_book['asks']:
            return Decimal("100")

        best_bid = order_book['bids'][0][0]
        best_ask = order_book['asks'][0][0]
        mid = (best_bid + best_ask) / 2

        if mid > 0:
            return ((best_ask - best_bid) / mid) * Decimal("100")
        return Decimal("100")


def main():
    print("=" * 70)
    print("  BITGET TRIANGULAR ARBITRAGE - PROFITABILITY SIMULATOR")
    print("=" * 70)
    print()

    # Load routes from discovery
    routes_file = 'logs/bitget_top_routes.json'

    if not os.path.exists(routes_file):
        print(f"❌ Routes file not found: {routes_file}")
        print("   Run 01_discover_routes.py first")
        return

    with open(routes_file, 'r') as f:
        routes = json.load(f)

    print(f"📊 Loaded {len(routes)} routes from {routes_file}")
    print()

    simulator = ProfitabilitySimulator()

    # Test amounts
    test_amounts = [Decimal("50"), Decimal("100"), Decimal("500")]

    results = []
    profitable_count = 0

    print(f"🔍 Simulating top 30 routes with order book depth...")
    print()

    for i, route in enumerate(routes[:30]):
        triangle = (route['pair1'], route['pair2'], route['pair3'])

        print(f"[{i + 1}/30] Testing {triangle[0]} → {triangle[1]} → {triangle[2]}")

        # Test with $100
        result = simulator.simulate_triangle(triangle, Decimal("100"))

        if result['success']:
            results.append(result)
            if result['profit_pct'] > 0:
                profitable_count += 1
                print(f"   ✅ PROFITABLE: {result['profit_pct']:.4f}% (${result['profit_usdt']:.4f})")
            else:
                print(f"   ❌ Loss: {result['profit_pct']:.4f}% (${result['profit_usdt']:.4f})")
        else:
            print(f"   ⚠️ Failed: {result.get('error', 'Unknown')}")

        time.sleep(0.3)  # Rate limiting

    print()
    print("=" * 70)
    print("  SIMULATION RESULTS")
    print("=" * 70)
    print()

    # Sort by profitability
    successful = [r for r in results if r['success']]
    successful.sort(key=lambda x: x['profit_pct'], reverse=True)

    print(f"Total routes tested: {len(routes[:30])}")
    print(f"Successful simulations: {len(successful)}")
    print(f"Profitable routes: {profitable_count}")
    print()

    if successful:
        # Show top 10 by profit
        print("TOP 10 BY PROFITABILITY:")
        print("-" * 70)
        print(f"{'#':>3} {'Route':<35} {'Profit %':>10} {'Profit $':>10} {'Spreads':>12}")
        print("-" * 70)

        for i, r in enumerate(successful[:10], 1):
            t = r['triangle']
            route_str = f"{t[0].split('/')[0]}→{t[1].split('/')[0]}→USDT"
            spreads = sum(r['spreads_pct'].values())

            profit_color = "✅" if r['profit_pct'] > 0 else "❌"
            print(f"{i:>3}. {route_str:<35} {profit_color} {r['profit_pct']:>8.4f}% ${r['profit_usdt']:>8.4f} {spreads:>10.4f}%")

        print()

        # Calculate statistics
        profits = [r['profit_pct'] for r in successful]
        avg_profit = sum(profits) / len(profits)
        max_profit = max(profits)
        min_profit = min(profits)

        print("STATISTICS:")
        print(f"  Average profit: {avg_profit:.4f}%")
        print(f"  Best profit:    {max_profit:.4f}%")
        print(f"  Worst profit:   {min_profit:.4f}%")
        print()

        # Profitable routes summary
        profitable_routes = [r for r in successful if r['profit_pct'] > 0]
        if profitable_routes:
            print(f"🎯 FOUND {len(profitable_routes)} PROFITABLE ROUTES!")
            print()
            for r in profitable_routes[:5]:
                t = r['triangle']
                print(f"   {t[0]} → {t[1]} → {t[2]}")
                print(f"   Profit: {r['profit_pct']:.4f}% (${r['profit_usdt']:.4f} on $100)")
                print()
        else:
            print("❌ No profitable routes found at current prices")
            print("   This is normal - opportunities are rare and fleeting")

    # Save results
    output_file = 'logs/bitget_simulation_results.json'
    with open(output_file, 'w') as f:
        json.dump(successful, f, indent=2)

    print(f"💾 Results saved to {output_file}")
    print()
    print("=" * 70)
    print("Next step: Run 03_monitor_continuous.py to watch for opportunities")
    print("=" * 70)


if __name__ == '__main__':
    main()
