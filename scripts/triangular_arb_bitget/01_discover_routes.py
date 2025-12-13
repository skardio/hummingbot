#!/usr/bin/env python3
"""
Bitget Triangular Arbitrage - Route Discovery

Discovers and ranks triangular arbitrage routes on Bitget Spot.
Routes are ordered by liquidity (24h volume in USDT).

Output: logs/bitget_top_routes.json

Fee structure (Bitget Spot VIP0):
  - Maker: 0.10%
  - Taker: 0.10% (same as maker for spot)

Total roundtrip: 0.30% (3 trades × 0.10%)
Target edge: > 0.35% to be profitable after fees
"""

import json
import os
import sys
import time
from collections import defaultdict
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


class BitgetRouteDiscovery:
    """Discover and rank triangular arbitrage routes on Bitget."""

    # Bitget spot fees (VIP0)
    MAKER_FEE = Decimal("0.001")  # 0.10%
    TAKER_FEE = Decimal("0.001")  # 0.10%

    # We use taker fees for all legs (market orders for speed)
    TOTAL_FEES = TAKER_FEE * 3  # 0.30% for 3 trades

    def __init__(self):
        self.exchange = ccxt.bitget({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        self.markets: Dict = {}
        self.tickers: Dict = {}

    def load_markets(self) -> int:
        """Load all Bitget spot markets."""
        print("📊 Loading Bitget markets...")
        self.markets = self.exchange.load_markets()

        # Filter for active spot markets only
        spot_markets = {
            k: v for k, v in self.markets.items()
            if v.get('spot') and v.get('active')
        }
        print(f"   Found {len(spot_markets)} active spot markets")
        return len(spot_markets)

    def fetch_all_tickers(self) -> int:
        """Fetch all tickers for volume data."""
        print("📊 Fetching all tickers (this may take a moment)...")
        try:
            self.tickers = self.exchange.fetch_tickers()
            print(f"   Fetched {len(self.tickers)} tickers")
            return len(self.tickers)
        except Exception as e:
            print(f"   ⚠️ Batch ticker fetch failed: {e}")
            print("   Falling back to individual ticker fetches...")
            return 0

    def enumerate_triangles(self, base_asset: str = "USDT") -> List[Tuple[str, str, str]]:
        """
        Enumerate all valid triangular routes starting from base_asset.

        Triangle: base_asset -> asset1 -> asset2 -> base_asset

        Example (starting from USDT):
          USDT -> BTC -> ETH -> USDT
          Trade 1: Buy BTC with USDT (BTC/USDT)
          Trade 2: Buy ETH with BTC (ETH/BTC)
          Trade 3: Sell ETH for USDT (ETH/USDT)
        """
        print(f"🔍 Enumerating triangular routes starting from {base_asset}...")

        # Build adjacency graph
        pairs_by_quote: Dict[str, set] = defaultdict(set)  # quote -> {bases}
        pairs_by_base: Dict[str, set] = defaultdict(set)   # base -> {quotes}

        for symbol, market in self.markets.items():
            if not market.get('spot') or not market.get('active'):
                continue
            base = market['base']
            quote = market['quote']
            pairs_by_quote[quote].add(base)
            pairs_by_base[base].add(quote)

        triangles = []

        # Pattern 1: USDT -> A (buy A/USDT) -> B (buy B/A) -> USDT (sell B/USDT)
        # We need: A/USDT, B/A, B/USDT

        assets_with_usdt = pairs_by_quote.get(base_asset, set())

        for asset1 in assets_with_usdt:
            # asset1 can be bought with USDT
            # Now find assets that can be bought with asset1
            assets_with_asset1 = pairs_by_quote.get(asset1, set())

            for asset2 in assets_with_asset1:
                if asset2 == base_asset:
                    continue
                # Check if asset2 can be sold for USDT
                if base_asset in pairs_by_base.get(asset2, set()):
                    # Valid triangle found
                    pair1 = f"{asset1}/{base_asset}"   # Buy asset1 with USDT
                    pair2 = f"{asset2}/{asset1}"       # Buy asset2 with asset1
                    pair3 = f"{asset2}/{base_asset}"   # Sell asset2 for USDT

                    # Verify all pairs exist
                    if pair1 in self.markets and pair2 in self.markets and pair3 in self.markets:
                        triangles.append((pair1, pair2, pair3))

        print(f"   Found {len(triangles)} valid triangular routes")
        return triangles

    def get_volume_usdt(self, symbol: str) -> Decimal:
        """Get 24h volume in USDT for a symbol."""
        try:
            if symbol in self.tickers:
                ticker = self.tickers[symbol]
            else:
                ticker = self.exchange.fetch_ticker(symbol)
                time.sleep(0.05)  # Rate limit

            quote_volume = ticker.get('quoteVolume') or 0

            # If quote is USDT, use directly
            market = self.markets.get(symbol, {})
            quote = market.get('quote', '')

            if quote == 'USDT':
                return Decimal(str(quote_volume))
            elif quote == 'BTC':
                # Convert BTC to USDT
                btc_price = self.get_mid_price('BTC/USDT') or Decimal("90000")
                return Decimal(str(quote_volume)) * btc_price
            elif quote == 'ETH':
                eth_price = self.get_mid_price('ETH/USDT') or Decimal("3000")
                return Decimal(str(quote_volume)) * eth_price
            else:
                return Decimal(str(quote_volume))

        except Exception:
            return Decimal("0")

    def get_mid_price(self, symbol: str) -> Optional[Decimal]:
        """Get mid-price for a symbol."""
        try:
            if symbol in self.tickers:
                ticker = self.tickers[symbol]
            else:
                ticker = self.exchange.fetch_ticker(symbol)
                time.sleep(0.05)

            bid = ticker.get('bid')
            ask = ticker.get('ask')

            if bid and ask:
                return (Decimal(str(bid)) + Decimal(str(ask))) / 2
            elif ticker.get('last'):
                return Decimal(str(ticker['last']))
            return None
        except Exception:
            return None

    def score_triangle(self, triangle: Tuple[str, str, str]) -> Dict:
        """
        Score a triangle by:
        1. Minimum leg volume (bottleneck)
        2. Theoretical edge (without execution)
        """
        pair1, pair2, pair3 = triangle

        # Get volumes for each leg
        vol1 = self.get_volume_usdt(pair1)
        vol2 = self.get_volume_usdt(pair2)
        vol3 = self.get_volume_usdt(pair3)

        # Minimum volume is the bottleneck
        min_volume = min(vol1, vol2, vol3)

        # Get mid prices for theoretical edge calculation
        p1 = self.get_mid_price(pair1)
        p2 = self.get_mid_price(pair2)
        p3 = self.get_mid_price(pair3)

        edge_pct = Decimal("0")
        if p1 and p2 and p3 and p1 > 0 and p2 > 0 and p3 > 0:
            # Starting with 1 USDT:
            # Step 1: Buy asset1 with USDT -> get 1/p1 of asset1
            # Step 2: Buy asset2 with asset1 -> get (1/p1)/p2 of asset2
            # Step 3: Sell asset2 for USDT -> get ((1/p1)/p2)*p3 USDT
            final_value = (Decimal("1") / p1 / p2) * p3
            edge_pct = (final_value - Decimal("1")) * Decimal("100")

        return {
            'triangle': triangle,
            'pair1': pair1,
            'pair2': pair2,
            'pair3': pair3,
            'min_volume_usdt': float(min_volume),
            'vol1_usdt': float(vol1),
            'vol2_usdt': float(vol2),
            'vol3_usdt': float(vol3),
            'theoretical_edge_pct': float(edge_pct),
            'fees_pct': float(self.TOTAL_FEES * 100),
            'net_edge_pct': float(edge_pct - (self.TOTAL_FEES * 100)),
        }

    def discover_top_routes(self, base_asset: str = "USDT", limit: int = 50) -> List[Dict]:
        """
        Discover and rank top triangular routes.
        Returns routes sorted by minimum leg volume (liquidity).
        """
        # Load markets and tickers
        self.load_markets()
        self.fetch_all_tickers()

        # Find all triangles
        triangles = self.enumerate_triangles(base_asset)

        if not triangles:
            print("❌ No valid triangular routes found")
            return []

        # Score each triangle (with progress)
        print(f"📊 Scoring {len(triangles)} triangles...")
        scored = []

        for i, triangle in enumerate(triangles):
            if (i + 1) % 100 == 0:
                print(f"   Scored {i + 1}/{len(triangles)}...")

            score = self.score_triangle(triangle)

            # Filter out low volume routes (< $50k daily)
            if score['min_volume_usdt'] >= 50000:
                scored.append(score)

        # Sort by volume (highest first)
        scored.sort(key=lambda x: x['min_volume_usdt'], reverse=True)

        print(f"✅ Found {len(scored)} routes with > $50k daily volume")

        return scored[:limit]


def main():
    print("=" * 70)
    print("  BITGET TRIANGULAR ARBITRAGE - ROUTE DISCOVERY")
    print("=" * 70)
    print()
    print(f"Fee structure (Bitget Spot):")
    print(f"  - Maker fee: 0.10%")
    print(f"  - Taker fee: 0.10%")
    print(f"  - Total roundtrip: 0.30% (3 trades)")
    print(f"  - Target edge: > 0.35% to be profitable")
    print()

    discovery = BitgetRouteDiscovery()

    # Discover routes starting from USDT
    routes = discovery.discover_top_routes("USDT", limit=100)

    if not routes:
        print("❌ No routes found")
        return

    # Save to file
    os.makedirs('logs', exist_ok=True)
    output_file = 'logs/bitget_top_routes.json'

    with open(output_file, 'w') as f:
        json.dump(routes, f, indent=2)

    print()
    print(f"💾 Saved {len(routes)} routes to {output_file}")
    print()

    # Print top 20
    print("=" * 70)
    print("  TOP 20 ROUTES BY LIQUIDITY")
    print("=" * 70)
    print()
    print(f"{'#':>3} {'Route':<40} {'Min Vol (USDT)':>15} {'Edge %':>8}")
    print("-" * 70)

    for i, route in enumerate(routes[:20], 1):
        pair1 = route['pair1'].replace('/USDT', '').replace('/BTC', '')
        pair2 = route['pair2'].replace('/', '→')
        pair3 = route['pair3'].replace('/USDT', '')

        route_str = f"USDT→{pair1}→{pair2.split('→')[0]}"
        vol_str = f"${route['min_volume_usdt']:,.0f}"
        edge_str = f"{route['theoretical_edge_pct']:.3f}%"

        print(f"{i:>3}. {route_str:<40} {vol_str:>15} {edge_str:>8}")

    print()
    print("=" * 70)
    print(f"Note: Theoretical edge is mid-price based.")
    print(f"Real edge depends on spread and slippage.")
    print(f"Next step: Run 02_simulate_profitability.py")
    print("=" * 70)


if __name__ == '__main__':
    main()
