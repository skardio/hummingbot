#!/usr/bin/env python3
"""
Continuous 24h Triangular Arbitrage Monitor for Bitvavo (ccxt-based).

This script:
- Uses ccxt to fetch order books and tickers from Bitvavo
- Maintains paper-trade balances (initial seed: 50 EUR, 50 USDT, etc.)
- Continuously polls for triangular arbitrage opportunities
- Simulates execution with slippage and fees
- Logs detected candidates to logs/tri_candidates_bitvavo_ccxt.log
- Does NOT execute real trades (paper-trade only, execute_trades=False)

Usage:
  source ~/.venvs/bot/bin/activate
  pip install ccxt
  python3 scripts/triangular_arb_bitvavo/03_monitor_continuous_24h_bitvavo.py

Logs:
  logs/tri_candidates_bitvavo_ccxt.log (JSON lines, one candidate per line)

Stop:
  Ctrl+C or kill the process
"""

import asyncio
import json
import logging
import os
import sys
import time
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


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BitvavoPaperTradeMonitor:
    """Triangular arbitrage monitor for Bitvavo using ccxt."""

    CONFIG = {
        'exchange_name': 'bitvavo',
        'poll_interval': 5.0,  # seconds between polls
        'taker_fee_pct': Decimal('0.2'),  # Bitvavo typical fee
        'slippage_pct_per_leg': Decimal('0.2'),  # conservative 0.2% per leg
        'execute_trades': False,  # SAFETY: never execute real trades in this mode
        'use_paper_trade': True,
        'min_edge_pct_to_log': Decimal('0.05'),  # only log if edge > 0.05%
        'order_amount_pct': Decimal('1.0'),  # use 100% of available base balance per cycle
    }

    # Initial paper-trade balances (seed)
    INITIAL_BALANCES = {
        'EUR': Decimal('50'),
        'USDT': Decimal('50'),
        'USD': Decimal('50'),
        'GBP': Decimal('30'),
        'CAD': Decimal('50'),
        'AUD': Decimal('70'),
        'BTC': Decimal('0.001'),
        'ETH': Decimal('0.01'),
        'XRP': Decimal('100'),
    }

    def __init__(self):
        config = {
            'enableRateLimit': True,
            'rateLimit': 250,
        }

        # Optionally add API keys if provided via environment
        api_key = os.environ.get('BITVAVO_API_KEY')
        api_secret = os.environ.get('BITVAVO_API_SECRET')
        if api_key and api_secret:
            config['apiKey'] = api_key
            config['secret'] = api_secret
            logger.info("Using provided API keys (from BITVAVO_API_KEY / BITVAVO_API_SECRET)")
        else:
            logger.info("No API keys provided (BITVAVO_API_KEY / BITVAVO_API_SECRET env vars)")
            logger.info("→ Using public data only (no authenticated calls)")

        self.exchange = ccxt.bitvavo(config)
        self.markets = {}
        self.paper_balances = self.INITIAL_BALANCES.copy()
        self.triangles = []
        self.poll_count = 0
        self.candidates_found = 0

        # Setup JSON logger for candidates
        logs_dir = os.path.join(ROOT, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        self.log_file = os.path.join(logs_dir, 'tri_candidates_bitvavo_ccxt.log')

        logger.info(f"Initialized. Log file: {self.log_file}")

    def load_markets(self):
        """Load trading pairs from Bitvavo."""
        try:
            self.markets = self.exchange.load_markets()
            logger.info(f"Loaded {len(self.markets)} pairs from Bitvavo")
            return True
        except Exception as e:
            logger.error(f"Failed to load markets: {e}")
            return False

    def find_triangles(self):
        """Find all possible triangle routes."""
        triangles = []
        pair_list = list(self.markets.keys())

        # General triangles (A/B -> B/C -> C/A)
        for p1, p2, p3 in permutations(pair_list, 3):
            try:
                a, b = p1.split('/')
                b2, c = p2.split('/')
                c2, a2 = p3.split('/')

                if b == b2 and c == c2 and a == a2:
                    triangles.append((p1, p2, p3))
            except ValueError:
                continue

        # EUR-centric triangles (EUR/Token1 -> Token1/Token2 -> Token2/EUR)
        eur_pairs = [p for p in pair_list if 'EUR' in p]
        non_eur_pairs = [p for p in pair_list if 'EUR' not in p]

        eur_base_pairs = {}
        for pair in eur_pairs:
            base, quote = pair.split('/')
            if base == 'EUR':
                eur_base_pairs[pair] = quote

        eur_quote_pairs = {}
        for pair in eur_pairs:
            base, quote = pair.split('/')
            if quote == 'EUR':
                eur_quote_pairs[pair] = base

        for eur_a_pair, token_a in eur_base_pairs.items():
            for token_b_eur_pair, token_b in eur_quote_pairs.items():
                for pair in non_eur_pairs:
                    base, quote = pair.split('/')
                    if base == token_a and quote == token_b:
                        triangles.append((eur_a_pair, pair, token_b_eur_pair))
                        break
                    elif base == token_b and quote == token_a:
                        triangles.append((eur_a_pair, pair, token_b_eur_pair))
                        break

        self.triangles = triangles
        logger.info(f"Found {len(self.triangles)} triangle routes (general + EUR-centric)")

    def get_mid_price(self, pair):
        """Fetch mid-price for a pair (bid+ask)/2."""
        try:
            order_book = self.exchange.fetch_order_book(pair, limit=5)
            bids = order_book.get('bids', [])
            asks = order_book.get('asks', [])

            if not bids or not asks:
                # Fallback to ticker
                ticker = self.exchange.fetch_ticker(pair)
                return Decimal(str(ticker['last']))

            best_bid = Decimal(str(bids[0][0]))
            best_ask = Decimal(str(asks[0][0]))
            mid = (best_bid + best_ask) / Decimal('2')
            return mid
        except Exception as e:
            logger.warning(f"Failed to fetch mid-price for {pair}: {e}")
            # Fallback
            try:
                ticker = self.exchange.fetch_ticker(pair)
                return Decimal(str(ticker['last']))
            except:
                return None

    def simulate_triangle_execution(self, pair1, pair2, pair3, start_amount):
        """
        Simulate executing a triangular route with slippage and fees.

        Returns: {
            'route': (pair1, pair2, pair3),
            'start_amount': start_amount,
            'final_amount': final_amount,
            'edge_pct': edge_pct,
            'mid_prices': (p1, p2, p3),
        }
        """
        try:
            # Get mid prices
            p1 = self.get_mid_price(pair1)
            p2 = self.get_mid_price(pair2)
            p3 = self.get_mid_price(pair3)

            if not all([p1, p2, p3]):
                return None

            # Simulate execution with slippage
            amount = start_amount
            slippage = Decimal('1') + (self.CONFIG['slippage_pct_per_leg'] / Decimal('100'))

            # Leg 1: Buy with slippage and fee
            amount_after_leg1 = amount / (p1 * slippage)
            fee1 = amount_after_leg1 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg1 -= fee1

            # Leg 2: Buy with slippage and fee
            amount_after_leg2 = amount_after_leg1 / (p2 * slippage)
            fee2 = amount_after_leg2 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg2 -= fee2

            # Leg 3: Sell with slippage and fee
            amount_after_leg3 = amount_after_leg2 * p3 / slippage
            fee3 = amount_after_leg3 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg3 -= fee3

            edge = amount_after_leg3 - amount
            edge_pct = (edge / amount) * Decimal('100') if amount != 0 else Decimal('0')

            return {
                'route': (pair1, pair2, pair3),
                'start_amount': float(amount),
                'final_amount': float(amount_after_leg3),
                'edge': float(edge),
                'edge_pct': float(edge_pct),
                'mid_prices': (float(p1), float(p2), float(p3)),
            }
        except Exception as e:
            logger.warning(f"Error simulating triangle {pair1}/{pair2}/{pair3}: {e}")
            return None

    def log_candidate(self, candidate, available_balance):
        """Log a profitable candidate to JSON file."""
        record = {
            'timestamp': datetime.utcnow().isoformat(),
            'pair1': candidate['route'][0],
            'pair2': candidate['route'][1],
            'pair3': candidate['route'][2],
            'available_balance': available_balance,
            'start_amount': candidate['start_amount'],
            'final_amount': candidate['final_amount'],
            'edge': candidate['edge'],
            'edge_pct': candidate['edge_pct'],
            'mid_prices': candidate['mid_prices'],
        }
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(record) + '\n')
            self.candidates_found += 1
        except Exception as e:
            logger.error(f"Failed to log candidate: {e}")

    def run_poll_cycle(self):
        """Run a single poll cycle: check all triangles for opportunities."""
        self.poll_count += 1
        candidates_this_cycle = 0

        # Try to get a starting balance (use EUR as primary, fallback to USDT)
        start_currency = 'EUR' if 'EUR' in self.paper_balances else 'USDT'
        available = self.paper_balances.get(start_currency, Decimal('0'))

        if available <= Decimal('0'):
            logger.debug(f"Poll #{self.poll_count}: No available balance in {start_currency}")
            return

        # Use 100% of available
        start_amount = available * self.CONFIG['order_amount_pct']

        for pair1, pair2, pair3 in self.triangles:
            result = self.simulate_triangle_execution(pair1, pair2, pair3, start_amount)
            if result is None:
                continue

            edge_pct = Decimal(str(result['edge_pct']))
            if edge_pct > self.CONFIG['min_edge_pct_to_log']:
                self.log_candidate(result, float(available))
                candidates_this_cycle += 1

        logger.info(f"Poll #{self.poll_count} complete: checked {len(self.triangles)} triples, found {candidates_this_cycle} candidate(s)")

    async def run(self):
        """Main loop: continuously poll for arbitrage opportunities."""
        logger.info("Starting Bitvavo triangular arbitrage monitor (24h paper-trade mode)")
        logger.info(f"Configuration: {self.CONFIG}")
        logger.info(f"Initial paper-trade balances: {self.INITIAL_BALANCES}")

        # Load markets once at startup
        if not self.load_markets():
            logger.error("Failed to load markets. Exiting.")
            return

        # Find triangles once
        self.find_triangles()

        if not self.triangles:
            logger.error("No triangles found. Exiting.")
            return

        # Poll loop
        try:
            while True:
                try:
                    self.run_poll_cycle()
                    await asyncio.sleep(self.CONFIG['poll_interval'])
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"Error in poll cycle: {e}", exc_info=True)
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Monitor stopped by user (Ctrl+C)")
            logger.info(f"Total candidates found: {self.candidates_found}")


def main():
    monitor = BitvavoPaperTradeMonitor()
    asyncio.run(monitor.run())


if __name__ == '__main__':
    main()
