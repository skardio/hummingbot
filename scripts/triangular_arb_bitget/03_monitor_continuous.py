#!/usr/bin/env python3
"""
Bitget Triangular Arbitrage - Continuous Monitor

Continuously monitors top triangular routes for profitable opportunities.
When an opportunity is found, logs it for potential execution.

Features:
- Real-time price monitoring
- Order book depth analysis
- Telegram notifications (optional)
- Candidate logging for executor

Usage:
  python3 scripts/triangular_arb_bitget/03_monitor_continuous.py

Environment variables:
  TELEGRAM_BOT_TOKEN - Telegram bot token for notifications (optional)
  TELEGRAM_CHAT_ID - Telegram chat ID for notifications (optional)
"""

import asyncio
import json
import os
import sys
import time
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


class ContinuousMonitor:
    """Continuously monitor triangular arbitrage opportunities on Bitget."""

    TAKER_FEE = Decimal("0.001")  # 0.10%
    MIN_PROFIT_PCT = Decimal("0.05")  # Minimum 0.05% profit to log

    def __init__(self, routes: List[Dict], telegram_token: str = None, telegram_chat: str = None):
        self.routes = routes
        self.exchange = None
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat = telegram_chat or os.getenv('TELEGRAM_CHAT_ID')

        # Statistics
        self.scans = 0
        self.opportunities_found = 0
        self.best_opportunity = None
        self.start_time = datetime.now()

        # Logging
        os.makedirs('logs', exist_ok=True)
        self.candidate_log = 'logs/bitget_tri_candidates.log'
        self.stats_file = 'logs/bitget_monitor_stats.json'

    async def init_exchange(self):
        """Initialize async exchange."""
        self.exchange = ccxt_async.bitget({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })
        await self.exchange.load_markets()
        print("✅ Exchange initialized")

    async def close_exchange(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()

    async def get_order_book(self, symbol: str, limit: int = 5) -> Optional[Dict]:
        """Fetch order book asynchronously."""
        try:
            ob = await self.exchange.fetch_order_book(symbol, limit=limit)
            return {
                'bids': [(Decimal(str(p)), Decimal(str(a))) for p, a in ob['bids'][:limit]],
                'asks': [(Decimal(str(p)), Decimal(str(a))) for p, a in ob['asks'][:limit]],
            }
        except Exception:
            return None

    async def check_triangle(self, route: Dict) -> Optional[Dict]:
        """
        Check a single triangle for profitability.
        Returns opportunity dict if profitable, None otherwise.
        """
        triangle = (route['pair1'], route['pair2'], route['pair3'])

        try:
            # Fetch all order books concurrently
            ob1, ob2, ob3 = await asyncio.gather(
                self.get_order_book(triangle[0]),
                self.get_order_book(triangle[1]),
                self.get_order_book(triangle[2]),
            )

            if not all([ob1, ob2, ob3]):
                return None

            # Quick profitability check using best prices
            # Leg 1: Buy asset1 with USDT at ask price
            ask1 = ob1['asks'][0][0] if ob1['asks'] else None
            # Leg 2: Buy asset2 with asset1 at ask price
            ask2 = ob2['asks'][0][0] if ob2['asks'] else None
            # Leg 3: Sell asset2 for USDT at bid price
            bid3 = ob3['bids'][0][0] if ob3['bids'] else None

            if not all([ask1, ask2, bid3]) or ask1 == 0 or ask2 == 0:
                return None

            # Calculate: 1 USDT -> asset1 -> asset2 -> USDT
            # (1/ask1) * (1/ask2) * bid3 = final USDT
            amount_asset1 = Decimal("1") / ask1
            amount_asset2 = amount_asset1 / ask2
            final_usdt = amount_asset2 * bid3

            # Apply fees (3 trades × 0.10%)
            final_usdt_after_fees = final_usdt * (Decimal("1") - self.TAKER_FEE) ** 3

            profit_pct = (final_usdt_after_fees - Decimal("1")) * Decimal("100")

            if profit_pct > self.MIN_PROFIT_PCT:
                return {
                    'timestamp': datetime.utcnow().isoformat(),
                    'triangle': triangle,
                    'profit_pct': float(profit_pct),
                    'prices': {
                        'ask1': float(ask1),
                        'ask2': float(ask2),
                        'bid3': float(bid3),
                    },
                    'depth': {
                        'leg1_ask_size': float(ob1['asks'][0][1]),
                        'leg2_ask_size': float(ob2['asks'][0][1]),
                        'leg3_bid_size': float(ob3['bids'][0][1]),
                    }
                }

            return None

        except Exception as e:
            return None

    async def scan_all_routes(self) -> List[Dict]:
        """Scan all routes and return profitable opportunities."""
        opportunities = []

        # Check routes in batches to avoid rate limits
        batch_size = 5

        for i in range(0, len(self.routes), batch_size):
            batch = self.routes[i:i + batch_size]
            tasks = [self.check_triangle(route) for route in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, dict) and result is not None:
                    opportunities.append(result)

            await asyncio.sleep(0.2)  # Rate limit between batches

        return opportunities

    def log_opportunity(self, opp: Dict):
        """Log opportunity to file."""
        with open(self.candidate_log, 'a') as f:
            f.write(json.dumps(opp) + '\n')

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

    def save_stats(self):
        """Save monitoring statistics."""
        stats = {
            'start_time': self.start_time.isoformat(),
            'total_scans': self.scans,
            'opportunities_found': self.opportunities_found,
            'best_opportunity': self.best_opportunity,
            'routes_monitored': len(self.routes),
            'last_update': datetime.utcnow().isoformat(),
        }
        with open(self.stats_file, 'w') as f:
            json.dump(stats, f, indent=2)

    async def run(self, interval_seconds: float = 5.0):
        """Main monitoring loop."""
        print()
        print("=" * 70)
        print("  BITGET TRIANGULAR ARBITRAGE - CONTINUOUS MONITOR")
        print("=" * 70)
        print()
        print(f"📊 Monitoring {len(self.routes)} routes")
        print(f"⏱️  Scan interval: {interval_seconds} seconds")
        print(f"💰 Min profit threshold: {self.MIN_PROFIT_PCT}%")
        print(f"📝 Candidates logged to: {self.candidate_log}")
        print()

        telegram_enabled = bool(self.telegram_token and self.telegram_chat)
        print(f"📱 Telegram notifications: {'✅ Enabled' if telegram_enabled else '❌ Disabled'}")
        print()
        print("Press Ctrl+C to stop")
        print()
        print("-" * 70)

        await self.init_exchange()

        # Send startup notification
        if telegram_enabled:
            self.send_telegram(
                f"🔍 <b>Bitget Triangular Arb Monitor Started</b>\n"
                f"Monitoring {len(self.routes)} routes\n"
                f"Min profit: {self.MIN_PROFIT_PCT}%"
            )

        try:
            while True:
                scan_start = time.time()
                self.scans += 1

                opportunities = await self.scan_all_routes()

                scan_time = time.time() - scan_start

                # Status line
                status = f"[{datetime.now().strftime('%H:%M:%S')}] " \
                         f"Scan #{self.scans} | " \
                         f"Time: {scan_time:.2f}s | " \
                         f"Found: {len(opportunities)}"

                if opportunities:
                    # Sort by profit
                    opportunities.sort(key=lambda x: x['profit_pct'], reverse=True)
                    best = opportunities[0]

                    status += f" | Best: {best['profit_pct']:.4f}%"

                    # Log opportunities
                    for opp in opportunities:
                        self.opportunities_found += 1
                        self.log_opportunity(opp)

                        # Update best opportunity
                        if self.best_opportunity is None or \
                           opp['profit_pct'] > self.best_opportunity.get('profit_pct', 0):
                            self.best_opportunity = opp

                    # Print detailed info for best opportunity
                    print(status)
                    t = best['triangle']
                    print(f"   🎯 {t[0]} → {t[1]} → {t[2]}")
                    print(f"   💰 Profit: {best['profit_pct']:.4f}%")

                    # Send Telegram for significant opportunities
                    if best['profit_pct'] >= 0.1 and telegram_enabled:
                        self.send_telegram(
                            f"🎯 <b>Arbitrage Opportunity!</b>\n"
                            f"Route: {t[0]} → {t[1]} → {t[2]}\n"
                            f"Profit: <b>{best['profit_pct']:.4f}%</b>\n"
                            f"Time: {datetime.now().strftime('%H:%M:%S')}"
                        )
                else:
                    # Clear line and print status
                    print(f"\r{status}", end='', flush=True)

                # Save stats periodically
                if self.scans % 100 == 0:
                    self.save_stats()
                    print(f"\n📊 Stats saved (Total opportunities: {self.opportunities_found})")

                # Wait for next scan
                await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n")
            print("=" * 70)
            print("  MONITOR STOPPED")
            print("=" * 70)
            print()
            print(f"Total scans: {self.scans}")
            print(f"Total opportunities found: {self.opportunities_found}")
            if self.best_opportunity:
                print(f"Best opportunity: {self.best_opportunity['profit_pct']:.4f}%")
                print(f"  Route: {self.best_opportunity['triangle']}")
            print()

            self.save_stats()

            if telegram_enabled:
                self.send_telegram(
                    f"🛑 <b>Monitor Stopped</b>\n"
                    f"Scans: {self.scans}\n"
                    f"Opportunities: {self.opportunities_found}"
                )

        finally:
            await self.close_exchange()


def main():
    # Load routes
    routes_file = 'logs/bitget_top_routes.json'

    if not os.path.exists(routes_file):
        print(f"❌ Routes file not found: {routes_file}")
        print("   Run 01_discover_routes.py first")
        return

    with open(routes_file, 'r') as f:
        routes = json.load(f)

    # Use top 50 routes by volume
    top_routes = routes[:50]

    monitor = ContinuousMonitor(top_routes)
    asyncio.run(monitor.run(interval_seconds=3.0))


if __name__ == '__main__':
    main()
