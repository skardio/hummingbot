#!/usr/bin/env python3
"""
Bitget Triangular Arbitrage - LIVE EXECUTOR

⚠️ WARNING: THIS SCRIPT PLACES REAL ORDERS ON BITGET ⚠️

Reads opportunities from the monitor and executes real trades.

Usage:
  export BITGET_API_KEY="your_key"
  export BITGET_SECRET_KEY="your_secret"
  export BITGET_PASSPHRASE="your_passphrase"

  # Dry run (default - no real trades):
  python3 scripts/triangular_arb_bitget/04_execute_live.py

  # Live execution:
  export BITGET_EXECUTE_TRADES=true
  python3 scripts/triangular_arb_bitget/04_execute_live.py

Environment variables:
  BITGET_API_KEY      - Bitget API key
  BITGET_SECRET_KEY   - Bitget API secret
  BITGET_PASSPHRASE   - Bitget API passphrase
  BITGET_EXECUTE_TRADES - Set to 'true' for live execution (default: false)
  BITGET_ORDER_SIZE   - Order size in USDT (default: 50)
  BITGET_MIN_PROFIT   - Minimum profit % to execute (default: 0.1)

Safety features:
  - Dry-run mode by default
  - Configurable order size
  - Minimum profit threshold
  - Trade logging
  - Telegram notifications
"""

import asyncio
import json
import os
import sys
import time
from collections import deque
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import ccxt.async_support as ccxt_async
except ImportError:
    print("❌ ccxt not installed. Run: pip install ccxt")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None


class LiveExecutor:
    """Live executor for triangular arbitrage on Bitget."""

    def __init__(self):
        # Configuration from environment
        self.execute_trades = os.getenv('BITGET_EXECUTE_TRADES', 'false').lower() == 'true'
        self.order_size_usdt = Decimal(os.getenv('BITGET_ORDER_SIZE', '50'))
        self.min_profit_pct = Decimal(os.getenv('BITGET_MIN_PROFIT', '0.1'))

        # API keys
        self.api_key = os.getenv('BITGET_API_KEY')
        self.api_secret = os.getenv('BITGET_SECRET_KEY')
        self.passphrase = os.getenv('BITGET_PASSPHRASE')

        # Telegram
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat = os.getenv('TELEGRAM_CHAT_ID')

        # Exchange
        self.exchange = None

        # Tracking
        self.executed_trades: List[Dict] = []
        self.failed_trades: List[Dict] = []
        self.processed_candidates = deque(maxlen=1000)
        self.last_log_pos = 0

        # File paths
        os.makedirs('logs', exist_ok=True)
        self.candidate_log = 'logs/bitget_tri_candidates.log'
        self.execution_log = 'logs/bitget_executions.log'

        # Statistics
        self.total_profit_usdt = Decimal("0")
        self.start_time = datetime.now()

    async def init_exchange(self):
        """Initialize exchange connection."""
        if not all([self.api_key, self.api_secret, self.passphrase]):
            if self.execute_trades:
                raise ValueError("API keys required for live execution!")
            print("⚠️ API keys not set - can only run in dry-run mode")
            return False

        self.exchange = ccxt_async.bitget({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'password': self.passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })

        await self.exchange.load_markets()
        print("✅ Exchange connected")
        return True

    async def close_exchange(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()

    async def get_balance(self, asset: str) -> Decimal:
        """Get available balance for an asset."""
        try:
            balance = await self.exchange.fetch_balance()
            return Decimal(str(balance.get(asset, {}).get('free', 0)))
        except Exception as e:
            print(f"⚠️ Failed to get balance for {asset}: {e}")
            return Decimal("0")

    async def place_order(self, symbol: str, side: str, amount: Decimal,
                          price: Optional[Decimal] = None) -> Optional[Dict]:
        """
        Place an order.
        Returns order result or None on failure.
        """
        if not self.execute_trades:
            # Dry run
            return {
                'id': f'dry_run_{int(time.time() * 1000)}',
                'status': 'simulated',
                'symbol': symbol,
                'side': side,
                'amount': float(amount),
                'price': float(price) if price else None,
            }

        try:
            if price:
                order = await self.exchange.create_limit_order(
                    symbol, side, float(amount), float(price)
                )
            else:
                order = await self.exchange.create_market_order(
                    symbol, side, float(amount)
                )
            return order
        except Exception as e:
            print(f"❌ Order failed: {e}")
            return None

    async def execute_triangle(self, opportunity: Dict) -> Dict:
        """
        Execute a triangular arbitrage trade.

        Flow:
          Leg 1: Buy asset1 with USDT
          Leg 2: Buy asset2 with asset1
          Leg 3: Sell asset2 for USDT
        """
        triangle = opportunity['triangle']
        pair1, pair2, pair3 = triangle

        result = {
            'timestamp': datetime.utcnow().isoformat(),
            'triangle': triangle,
            'start_usdt': float(self.order_size_usdt),
            'expected_profit_pct': opportunity['profit_pct'],
            'legs': [],
            'success': False,
            'final_usdt': 0,
            'actual_profit_usdt': 0,
            'actual_profit_pct': 0,
        }

        try:
            # Check USDT balance
            if self.execute_trades:
                usdt_balance = await self.get_balance('USDT')
                if usdt_balance < self.order_size_usdt:
                    result['error'] = f"Insufficient USDT: {usdt_balance} < {self.order_size_usdt}"
                    return result

            # Leg 1: Buy asset1 with USDT
            asset1 = pair1.split('/')[0]
            ask1 = Decimal(str(opportunity['prices']['ask1']))
            amount1 = self.order_size_usdt / ask1

            print(f"   [Leg 1] Buying {float(amount1):.6f} {asset1} at {float(ask1)}")
            order1 = await self.place_order(pair1, 'buy', amount1)

            if not order1:
                result['error'] = "Leg 1 order failed"
                return result

            result['legs'].append({
                'pair': pair1,
                'side': 'buy',
                'amount': float(amount1),
                'order_id': order1.get('id'),
            })

            # Small delay to ensure order is processed
            await asyncio.sleep(0.1)

            # Leg 2: Buy asset2 with asset1
            asset2 = pair2.split('/')[0]
            ask2 = Decimal(str(opportunity['prices']['ask2']))
            # Account for 0.1% fee from leg 1
            amount1_after_fee = amount1 * Decimal("0.999")
            amount2 = amount1_after_fee / ask2

            print(f"   [Leg 2] Buying {float(amount2):.6f} {asset2} at {float(ask2)}")
            order2 = await self.place_order(pair2, 'buy', amount2)

            if not order2:
                result['error'] = "Leg 2 order failed"
                # TODO: Consider selling back asset1 to recover
                return result

            result['legs'].append({
                'pair': pair2,
                'side': 'buy',
                'amount': float(amount2),
                'order_id': order2.get('id'),
            })

            await asyncio.sleep(0.1)

            # Leg 3: Sell asset2 for USDT
            bid3 = Decimal(str(opportunity['prices']['bid3']))
            # Account for 0.1% fee from leg 2
            amount2_after_fee = amount2 * Decimal("0.999")

            print(f"   [Leg 3] Selling {float(amount2_after_fee):.6f} {asset2} at {float(bid3)}")
            order3 = await self.place_order(pair3, 'sell', amount2_after_fee)

            if not order3:
                result['error'] = "Leg 3 order failed"
                return result

            result['legs'].append({
                'pair': pair3,
                'side': 'sell',
                'amount': float(amount2_after_fee),
                'order_id': order3.get('id'),
            })

            # Calculate final result
            # Expected: amount2_after_fee * bid3 * 0.999 (leg 3 fee)
            final_usdt = amount2_after_fee * bid3 * Decimal("0.999")
            actual_profit = final_usdt - self.order_size_usdt
            actual_profit_pct = (actual_profit / self.order_size_usdt) * Decimal("100")

            result['success'] = True
            result['final_usdt'] = float(final_usdt)
            result['actual_profit_usdt'] = float(actual_profit)
            result['actual_profit_pct'] = float(actual_profit_pct)

            # Update totals
            self.total_profit_usdt += actual_profit

            return result

        except Exception as e:
            result['error'] = str(e)
            return result

    def read_new_candidates(self) -> List[Dict]:
        """Read new candidates from monitor log."""
        candidates = []

        if not os.path.exists(self.candidate_log):
            return candidates

        try:
            with open(self.candidate_log, 'r') as f:
                f.seek(self.last_log_pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        candidate = json.loads(line)
                        triangle = tuple(candidate.get('triangle', []))
                        profit = Decimal(str(candidate.get('profit_pct', 0)))

                        # Filter by profit threshold and dedup
                        if profit >= self.min_profit_pct:
                            if triangle not in self.processed_candidates:
                                candidates.append(candidate)
                                self.processed_candidates.append(triangle)
                    except (json.JSONDecodeError, ValueError):
                        continue

                self.last_log_pos = f.tell()

        except Exception as e:
            print(f"⚠️ Error reading candidates: {e}")

        return candidates

    def log_execution(self, result: Dict):
        """Log execution result."""
        with open(self.execution_log, 'a') as f:
            f.write(json.dumps(result) + '\n')

    def send_telegram(self, message: str):
        """Send Telegram notification."""
        if not self.telegram_token or not self.telegram_chat or not requests:
            return

        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={
                'chat_id': self.telegram_chat,
                'text': message,
                'parse_mode': 'HTML',
            }, timeout=5)
        except Exception:
            pass

    async def run_cycle(self) -> int:
        """Run one execution cycle."""
        candidates = self.read_new_candidates()

        if not candidates:
            return 0

        executed = 0

        for candidate in candidates:
            triangle = candidate['triangle']
            profit_pct = candidate['profit_pct']

            print()
            print(f"🎯 Opportunity: {triangle[0]} → {triangle[1]} → {triangle[2]}")
            print(f"   Expected profit: {profit_pct:.4f}%")

            result = await self.execute_triangle(candidate)

            if result['success']:
                executed += 1
                self.executed_trades.append(result)
                print(f"   ✅ SUCCESS: {result['actual_profit_pct']:.4f}% (${result['actual_profit_usdt']:.4f})")

                # Telegram notification
                self.send_telegram(
                    f"✅ <b>Trade Executed</b>\n"
                    f"Route: {triangle[0]} → {triangle[1]} → {triangle[2]}\n"
                    f"Profit: {result['actual_profit_pct']:.4f}% (${result['actual_profit_usdt']:.4f})"
                )
            else:
                self.failed_trades.append(result)
                print(f"   ❌ FAILED: {result.get('error', 'Unknown error')}")

            self.log_execution(result)

            # Small delay between executions
            await asyncio.sleep(0.5)

        return executed

    async def run(self, interval_seconds: float = 2.0):
        """Main execution loop."""
        print()
        print("=" * 70)
        print("  BITGET TRIANGULAR ARBITRAGE - LIVE EXECUTOR")
        print("=" * 70)
        print()

        if self.execute_trades:
            print("⚠️  MODE: LIVE EXECUTION (REAL TRADES!)")
        else:
            print("🔄 MODE: DRY RUN (no real trades)")

        print()
        print(f"📊 Order size: ${self.order_size_usdt} USDT")
        print(f"💰 Min profit: {self.min_profit_pct}%")
        print(f"📝 Candidate log: {self.candidate_log}")
        print(f"📝 Execution log: {self.execution_log}")
        print()

        # Initialize exchange
        connected = await self.init_exchange()

        if self.execute_trades and not connected:
            print("❌ Cannot run in live mode without API keys")
            return

        # Check balance
        if connected:
            usdt_balance = await self.get_balance('USDT')
            print(f"💰 USDT Balance: ${usdt_balance:.2f}")
            print()

        print("-" * 70)
        print("Watching for opportunities... Press Ctrl+C to stop")
        print("-" * 70)

        # Startup notification
        self.send_telegram(
            f"🚀 <b>Executor Started</b>\n"
            f"Mode: {'LIVE' if self.execute_trades else 'Dry Run'}\n"
            f"Order size: ${self.order_size_usdt}"
        )

        try:
            while True:
                executed = await self.run_cycle()

                if executed == 0:
                    # Print status every 10 seconds if no trades
                    print(f"\r[{datetime.now().strftime('%H:%M:%S')}] Waiting for opportunities... "
                          f"Executed: {len(self.executed_trades)} | "
                          f"Failed: {len(self.failed_trades)} | "
                          f"Total P&L: ${float(self.total_profit_usdt):.4f}",
                          end='', flush=True)

                await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n")
            print("=" * 70)
            print("  EXECUTOR STOPPED")
            print("=" * 70)
            print()
            print(f"Total executed: {len(self.executed_trades)}")
            print(f"Total failed: {len(self.failed_trades)}")
            print(f"Total profit: ${float(self.total_profit_usdt):.4f}")
            print()

            # Final notification
            self.send_telegram(
                f"🛑 <b>Executor Stopped</b>\n"
                f"Executed: {len(self.executed_trades)}\n"
                f"Total P&L: ${float(self.total_profit_usdt):.4f}"
            )

        finally:
            await self.close_exchange()


def main():
    executor = LiveExecutor()
    asyncio.run(executor.run())


if __name__ == '__main__':
    main()
