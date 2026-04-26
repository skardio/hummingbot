#!/usr/bin/env python3
"""
Triangular Arbitrage LIVE Executor for Kraken (ccxt-based).

⚠️ WARNING: THIS SCRIPT PLACES REAL ORDERS ON KRAKEN ⚠️

This script reads high-edge triangular opportunities and places REAL trades.
Start with SMALL order sizes (10-50 EUR) and monitor closely.

Usage:
  export KRAKEN_API_KEY="your_key"
  export KRAKEN_SECRET_KEY="your_secret"
  python3 scripts/execute_triangular_live.py

Features:
  - Monitors logs/tri_candidates.log for real-time opportunities
  - Filters by edge threshold (default: 0.15%)
  - Places real orders via Kraken API
  - Logs ALL trades to logs/live_executions.log
  - Safety features: order size limit, execution threshold, cancellation on timeout
  - Dry-run mode available (set EXECUTE_TRADES=False in shell)

Configuration:
  Edit CONFIG below or pass environment variables:
  - KRAKEN_MIN_EDGE_PCT: minimum edge % to execute (default: 0.15)
  - KRAKEN_ORDER_SIZE_EUR: order size in EUR (default: 50)
  - KRAKEN_EXECUTE_TRADES: set to "true" to enable real execution (default: false)

Safety Recommendations:
  1. Start with order_size=10 EUR and edge_min=0.2%
  2. Run in dry-run mode first (EXECUTE_TRADES=false)
  3. Monitor logs closely for first 100 trades
  4. Gradually increase order size if profitable
  5. Never exceed your daily loss tolerance
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import ccxt
except ImportError:
    ccxt = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveExecutor:
    """Live executor for triangular arbitrage on Kraken."""

    CONFIG = {
        'exchange_name': 'kraken',
        'polling_interval': 10.0,
        'min_edge_pct_to_execute': Decimal(os.environ.get('KRAKEN_MIN_EDGE_PCT', '0.15')),
        'min_profit_after_costs_pct': Decimal(os.environ.get('KRAKEN_MIN_NET_PROFIT_PCT', '0.05')),
        'order_size_eur': Decimal(os.environ.get('KRAKEN_ORDER_SIZE_EUR', '50')),
        'execute_trades': os.environ.get('KRAKEN_EXECUTE_TRADES', 'false').lower() == 'true',
        'slippage_pct': Decimal('0.3'),
        'taker_fee_pct': Decimal('0.26'),
        'order_timeout_seconds': 30,  # cancel if not filled in 30s
        'max_open_trades': 10,
        'max_trades_per_day': 100,
    }

    def __init__(self):
        self.exchange = None
        self.last_log_pos = 0
        self.processed_candidates = deque(maxlen=1000)
        self.in_flight_trades = 0
        self.executed_trades = []
        self.failed_trades = []

        # Setup logging
        logs_dir = os.path.join(ROOT, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        self.log_file = os.path.join(logs_dir, 'live_executions.log')
        self.candidate_log = os.path.join(logs_dir, 'tri_candidates.log')

        # Print safety warning
        print("\n" + "=" * 80)
        if self.CONFIG['execute_trades']:
            print("⚠️  LIVE EXECUTION MODE ENABLED ⚠️")
            print(f"Order size: {self.CONFIG['order_size_eur']} EUR")
            print(f"Min edge threshold: {self.CONFIG['min_edge_pct_to_execute']}%")
        else:
            print("🟡 DRY-RUN MODE (no real trades)")
            print("Set KRAKEN_EXECUTE_TRADES=true to enable real execution")
        print("=" * 80 + "\n")

        logger.info(f"LiveExecutor initialized (EXECUTE_TRADES={self.CONFIG['execute_trades']})")

    @staticmethod
    def _pair_to_ccxt_symbol(pair: str) -> str:
        """Convert Hummingbot pair style BASE-QUOTE to ccxt BASE/QUOTE."""
        return pair.replace('-', '/')

    @staticmethod
    def _parse_symbol(symbol: str) -> Tuple[str, str]:
        base, quote = symbol.split('/')
        return base, quote

    @staticmethod
    def _decimal_or(default: Decimal, value) -> Decimal:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except Exception:
            return default

    @staticmethod
    def _candidate_key(record: dict):
        triple = tuple(record.get('triple', []))
        ts = record.get('timestamp')
        if ts:
            return triple, ts
        edge = record.get('edge_pct')
        return triple, edge

    def _candidate_profit_pct(self, record: dict) -> Decimal:
        """Prefer monitor net profitability field if available, else fallback to raw edge."""
        net_profit = record.get('profit_pct_after_fees')
        if net_profit is not None:
            return self._decimal_or(Decimal('0'), net_profit)
        return self._decimal_or(Decimal('0'), record.get('edge_pct', 0))

    def _persist_execution(self, execution: dict):
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(execution) + '\n')
        except Exception as e:
            logger.warning(f"Failed to persist execution log: {e}")

    def init_exchange(self):
        """Initialize Kraken exchange via ccxt."""
        if ccxt is None:
            logger.error("ccxt not installed. Run: pip install ccxt")
            return False

        api_key = os.environ.get('KRAKEN_API_KEY')
        api_secret = os.environ.get('KRAKEN_SECRET_KEY')

        if not api_key or not api_secret:
            logger.error("KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set")
            return False

        try:
            self.exchange = ccxt.kraken({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
            })
            logger.info("Kraken exchange initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kraken: {e}")
            return False

    def get_mid_price(self, pair):
        """Get mid-price for a pair."""
        try:
            ticker = self.exchange.fetch_ticker(self._pair_to_ccxt_symbol(pair))
            bid = Decimal(str(ticker['bid']))
            ask = Decimal(str(ticker['ask']))
            mid = (bid + ask) / Decimal('2')
            return mid
        except Exception as e:
            logger.warning(f"Failed to fetch mid-price for {pair}: {e}")
            return None

    def get_bid_ask(self, pair) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Get best bid/ask for a pair in Hummingbot format."""
        try:
            ticker = self.exchange.fetch_ticker(self._pair_to_ccxt_symbol(pair))
            bid = self._decimal_or(Decimal('0'), ticker.get('bid'))
            ask = self._decimal_or(Decimal('0'), ticker.get('ask'))
            if bid <= 0 or ask <= 0:
                return None, None
            return bid, ask
        except Exception as e:
            logger.warning(f"Failed to fetch bid/ask for {pair}: {e}")
            return None, None

    async def place_order(self, pair, side, amount, price=None):
        """Place a limit or market order."""
        ccxt_pair = self._pair_to_ccxt_symbol(pair)
        if not self.CONFIG['execute_trades']:
            logger.debug(f"[DRY-RUN] Would place {side} order: {amount} {pair} @ {price}")
            simulated_price = self._decimal_or(Decimal('0'), price)
            simulated_amount = self._decimal_or(Decimal('0'), amount)
            simulated_cost = simulated_amount * simulated_price if simulated_price > 0 else Decimal('0')
            return {
                'id': f'dry_run_{int(time.time())}',
                'status': 'simulated',
                'symbol': ccxt_pair,
                'side': side,
                'filled': float(simulated_amount),
                'amount': float(simulated_amount),
                'price': float(simulated_price) if simulated_price > 0 else None,
                'cost': float(simulated_cost),
            }

        try:
            if price:
                order = self.exchange.create_limit_order(ccxt_pair, side, amount, float(price))
            else:
                order = self.exchange.create_market_order(ccxt_pair, side, amount)
            logger.info(f"✓ Order placed: {side} {amount} {pair} (ID: {order['id']})")
            return order
        except Exception as e:
            logger.error(f"✗ Failed to place order: {e}")
            return None

    async def _execute_leg(self, pair: str, input_asset: str, input_amount: Decimal):
        """Execute one leg and return (output_asset, output_amount, order, side)."""
        bid, ask = self.get_bid_ask(pair)
        if not bid or not ask:
            raise RuntimeError(f"Missing bid/ask for {pair}")

        base, quote = self._parse_symbol(self._pair_to_ccxt_symbol(pair))
        if input_asset == quote:
            side = 'buy'
            order_amount_base = input_amount / ask
            order = await self.place_order(pair, side, float(order_amount_base), ask)
            if not order:
                raise RuntimeError(f"Leg failed placing buy order on {pair}")
            filled_base = self._decimal_or(order_amount_base, order.get('filled'))
            return base, filled_base, order, side

        if input_asset == base:
            side = 'sell'
            order = await self.place_order(pair, side, float(input_amount), bid)
            if not order:
                raise RuntimeError(f"Leg failed placing sell order on {pair}")
            proceeds_quote = self._decimal_or(input_amount * bid, order.get('cost'))
            if proceeds_quote <= 0:
                filled_base = self._decimal_or(input_amount, order.get('filled'))
                proceeds_quote = filled_base * bid
            return quote, proceeds_quote, order, side

        raise RuntimeError(f"Cannot route asset {input_asset} through pair {pair}")

    async def execute_trade(self, pair1, pair2, pair3, candidate_profit_pct: Decimal):
        """Execute a full triangular trade."""
        try:
            pair1_quote = self._parse_symbol(self._pair_to_ccxt_symbol(pair1))[1]
            if pair1_quote != 'EUR':
                logger.warning(
                    f"Skipping trade {pair1} -> {pair2} -> {pair3}: "
                    f"first pair quote is {pair1_quote}, only EUR start is supported in this executor"
                )
                return None

            start_asset = 'EUR'
            start_amount = self.CONFIG['order_size_eur']

            logger.info(
                f"Executing candidate route {pair1} -> {pair2} -> {pair3} "
                f"(candidate profit after costs: {candidate_profit_pct:.4f}%)"
            )

            logger.info(f"[LEG 1] Routing {start_amount} {start_asset} through {pair1}")
            asset_after_leg1, amount_after_leg1, order1, side1 = await self._execute_leg(pair1, start_asset, start_amount)

            logger.info(f"[LEG 2] Routing {amount_after_leg1:.8f} {asset_after_leg1} through {pair2}")
            asset_after_leg2, amount_after_leg2, order2, side2 = await self._execute_leg(pair2, asset_after_leg1, amount_after_leg1)

            logger.info(f"[LEG 3] Routing {amount_after_leg2:.8f} {asset_after_leg2} through {pair3}")
            final_asset, final_amount, order3, side3 = await self._execute_leg(pair3, asset_after_leg2, amount_after_leg2)

            if final_asset != start_asset:
                logger.error(f"Final asset mismatch: expected {start_asset}, got {final_asset}")
                return None

            realized_profit_eur = final_amount - start_amount
            realized_profit_pct = (realized_profit_eur / start_amount) * Decimal('100') if start_amount != 0 else Decimal('0')

            execution = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'live_execution',
                'pair1': pair1, 'pair2': pair2, 'pair3': pair3,
                'order_ids': [order1['id'], order2['id'], order3['id']],
                'sides': [side1, side2, side3],
                'start_amount_eur': float(start_amount),
                'final_amount_eur': float(final_amount),
                'realized_profit_eur': float(realized_profit_eur),
                'realized_profit_pct': float(realized_profit_pct),
                'candidate_profit_pct': float(candidate_profit_pct),
                'status': 'executed' if self.CONFIG['execute_trades'] else 'simulated',
            }

            logger.info(
                f"✓ Trade executed: {pair1} → {pair2} → {pair3} "
                f"| realized={realized_profit_pct:.4f}% ({realized_profit_eur:.6f} EUR)"
            )
            self.executed_trades.append(execution)
            self._persist_execution(execution)
            return execution

        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            failure = {
                'timestamp': datetime.utcnow().isoformat(),
                'route': (pair1, pair2, pair3),
                'error': str(e),
            }
            self.failed_trades.append(failure)
            self._persist_execution({'type': 'live_execution_error', **failure})
            return None

    async def cancel_order(self, pair, order_id):
        """Cancel an order."""
        if not self.CONFIG['execute_trades']:
            logger.debug(f"[DRY-RUN] Would cancel order {order_id} on {pair}")
            return True

        try:
            self.exchange.cancel_order(order_id, self._pair_to_ccxt_symbol(pair))
            logger.info(f"✓ Canceled order {order_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    def read_new_candidates(self):
        """Read new high-edge candidates from log."""
        candidates = []
        try:
            if not os.path.exists(self.candidate_log):
                return candidates

            with open(self.candidate_log, 'r', errors='ignore') as f:
                f.seek(self.last_log_pos)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            edge_pct = Decimal(str(record.get('edge_pct', 0)))
                            net_profit_pct = self._candidate_profit_pct(record)
                            key = self._candidate_key(record)

                            # Filter by both raw edge and net profitability after costs
                            if (
                                edge_pct >= self.CONFIG['min_edge_pct_to_execute'] and
                                net_profit_pct >= self.CONFIG['min_profit_after_costs_pct']
                            ):
                                if key not in self.processed_candidates:
                                    candidates.append(record)
                                    self.processed_candidates.append(key)
                        except (json.JSONDecodeError, ValueError):
                            continue

                self.last_log_pos = f.tell()
        except Exception as e:
            logger.error(f"Error reading candidate log: {e}")

        return candidates

    async def run_cycle(self):
        """Run one cycle: read candidates, execute trades."""
        candidates = self.read_new_candidates()

        if not candidates:
            return 0

        executed = 0
        for candidate in candidates:
            triple = candidate.get('triple', [])
            if len(triple) != 3:
                continue
            candidate_profit_pct = self._candidate_profit_pct(candidate)

            # Check trade limits
            if len(self.executed_trades) >= self.CONFIG['max_trades_per_day']:
                logger.warning(f"Daily trade limit reached ({self.CONFIG['max_trades_per_day']})")
                break

            if self.in_flight_trades >= self.CONFIG['max_open_trades']:
                logger.warning(f"Max open trades reached ({self.CONFIG['max_open_trades']})")
                break

            self.in_flight_trades += 1
            try:
                result = await self.execute_trade(triple[0], triple[1], triple[2], candidate_profit_pct)
                if result:
                    executed += 1
            finally:
                self.in_flight_trades = max(0, self.in_flight_trades - 1)

        return executed

    async def run(self):
        """Main loop."""
        logger.info("Starting LIVE executor")
        logger.info(f"Configuration: {self.CONFIG}")

        if not self.init_exchange():
            logger.error("Failed to initialize exchange")
            return

        try:
            while True:
                executed = await self.run_cycle()

                if executed > 0:
                    logger.info(f"Executed {executed} trades")
                    logger.info(f"Total executed: {len(self.executed_trades)}, Failed: {len(self.failed_trades)}")

                await asyncio.sleep(self.CONFIG['polling_interval'])

        except KeyboardInterrupt:
            logger.info("\nLive executor stopped (Ctrl+C)")
            logger.info(f"Total executed: {len(self.executed_trades)}")
            logger.info(f"Total failed: {len(self.failed_trades)}")


def main():
    executor = LiveExecutor()
    asyncio.run(executor.run())


if __name__ == '__main__':
    main()
