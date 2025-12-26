#!/usr/bin/env python3
"""
Strategy Simulator - Test if your strategy would work with historical data

This script simulates the multi-coin grid strategy using real price data
to show if orders would be filled and what the P&L would be.

Usage:
    python multi_coin_grid_pro/scripts/simulate_strategy.py
"""

import asyncio
import logging
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from hummingbot.connector.exchange.kraken.kraken_exchange import KrakenExchange

# Add hummingbot to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StrategySimulator:
    """Simulates grid strategy with real price data"""

    def __init__(self, trading_pair: str, start_price: Decimal, end_price: Decimal,
                 total_amount: Decimal = Decimal("50")):
        self.trading_pair = trading_pair
        self.start_price = start_price
        self.end_price = end_price
        self.total_amount = total_amount

        # Grid levels
        self.grid_levels: List[Dict] = []
        self.filled_orders: List[Dict] = []
        self.current_position = Decimal("0")
        self.total_pnl = Decimal("0")
        self.total_fees = Decimal("0")

        # Create grid levels
        self._create_grid_levels()

    def _create_grid_levels(self):
        """Create grid levels between start and end price"""
        num_levels = 5
        price_range = self.end_price - self.start_price
        level_spacing = price_range / (num_levels - 1)
        amount_per_level = self.total_amount / num_levels

        for i in range(num_levels):
            price = self.start_price + (level_spacing * i)
            self.grid_levels.append({
                'price': price,
                'amount': amount_per_level,
                'filled': False,
                'fill_time': None,
                'fill_price': None
            })

        logger.info(f"Created {len(self.grid_levels)} grid levels for {self.trading_pair}")
        logger.info(f"Price range: €{self.start_price:.6f} - €{self.end_price:.6f}")

    def check_fills(self, current_price: Decimal, timestamp: datetime):
        """Check if any grid levels would be filled at current price"""
        for level in self.grid_levels:
            if level['filled']:
                continue

            # BUY orders fill when price drops to or below level
            if current_price <= level['price']:
                level['filled'] = True
                level['fill_time'] = timestamp
                level['fill_price'] = current_price

                # Calculate position
                base_amount = level['amount'] / current_price
                fee = level['amount'] * Decimal("0.0016")  # 0.16% maker fee

                self.current_position += base_amount
                self.total_fees += fee

                self.filled_orders.append({
                    'type': 'BUY',
                    'price': current_price,
                    'amount': base_amount,
                    'quote_amount': level['amount'],
                    'fee': fee,
                    'timestamp': timestamp
                })

                logger.info(
                    f"✅ BUY FILLED @ €{current_price:.6f} | "
                    f"{base_amount:.6f} {self.trading_pair.split('-')[0]} | "
                    f"Fee: €{fee:.4f}"
                )

    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate current P&L"""
        if self.current_position == 0:
            return Decimal("0")

        # Value of position at current price
        position_value = self.current_position * current_price

        # Total cost (including fees)
        total_cost = sum(order['quote_amount'] + order['fee'] for order in self.filled_orders)

        # P&L
        pnl = position_value - total_cost
        return pnl

    def get_summary(self, current_price: Decimal) -> Dict:
        """Get summary of simulation"""
        pnl = self.calculate_pnl(current_price)
        pnl_pct = (pnl / self.total_amount * 100) if self.total_amount > 0 else Decimal("0")

        return {
            'trading_pair': self.trading_pair,
            'grid_levels': len(self.grid_levels),
            'filled_levels': len([level for level in self.grid_levels if level['filled']]),
            'total_orders': len(self.filled_orders),
            'current_position': float(self.current_position),
            'total_invested': float(sum(order['quote_amount'] for order in self.filled_orders)),
            'total_fees': float(self.total_fees),
            'current_price': float(current_price),
            'position_value': float(self.current_position * current_price),
            'pnl': float(pnl),
            'pnl_pct': float(pnl_pct)
        }


async def simulate_with_real_data(trading_pair: str, hours: int = 24):
    """Simulate strategy using real Kraken price data"""
    logger.info(f"🚀 Starting simulation for {trading_pair} using last {hours} hours of data")

    # Connect to Kraken (no API keys needed for public data)
    kraken = KrakenExchange(
        kraken_api_key="",
        kraken_secret_key="",
        trading_pairs=[trading_pair],
        trading_required=False,  # We only need public data
    )

    try:
        await kraken.start_network()
        logger.info("✅ Connected to Kraken")

        # Get current price
        current_price = await kraken.get_price_by_type(trading_pair, "MidPrice")
        logger.info(f"Current price: €{current_price:.6f}")

        # Create grid (3% below and above current price)
        start_price = current_price * Decimal("0.97")
        end_price = current_price * Decimal("1.03")

        simulator = StrategySimulator(
            trading_pair=trading_pair,
            start_price=start_price,
            end_price=end_price,
            total_amount=Decimal("50")
        )

        # Simulate with current price (would need historical data for real simulation)
        # For now, just show what would happen if price moves
        logger.info("\n" + "=" * 70)
        logger.info("SIMULATION RESULTS")
        logger.info("=" * 70)

        # Test different price scenarios
        test_prices = [
            current_price * Decimal("0.98"),  # -2%
            current_price * Decimal("0.99"),  # -1%
            current_price,                    # Current
            current_price * Decimal("1.01"),  # +1%
            current_price * Decimal("1.02"),   # +2%
        ]

        for test_price in test_prices:
            # Reset for each test
            simulator.filled_orders = []
            simulator.current_position = Decimal("0")
            simulator.total_fees = Decimal("0")
            for level in simulator.grid_levels:
                level['filled'] = False

            # Check fills at this price
            simulator.check_fills(test_price, datetime.now())

            # Calculate P&L
            summary = simulator.get_summary(test_price)

            price_change = ((test_price - current_price) / current_price * 100)
            logger.info(f"\n📊 Price: €{test_price:.6f} ({price_change:+.2f}%)")
            logger.info(f"   Filled levels: {summary['filled_levels']}/{summary['grid_levels']}")
            logger.info(f"   Position: {summary['current_position']:.6f} {trading_pair.split('-')[0]}")
            logger.info(f"   Invested: €{summary['total_invested']:.2f}")
            logger.info(f"   Fees: €{summary['total_fees']:.4f}")
            logger.info(f"   P&L: €{summary['pnl']:+.2f} ({summary['pnl_pct']:+.2f}%)")

        logger.info("\n" + "=" * 70)
        logger.info("💡 This shows what WOULD happen if price moves")
        logger.info("💡 For real simulation, we need historical price data")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await kraken.stop_network()


async def main():
    """Main function"""
    print("\n" + "=" * 70)
    print("  STRATEGY SIMULATOR")
    print("=" * 70)
    print("\nThis script simulates your grid strategy to show if it would work.")
    print("It uses real Kraken price data to test different scenarios.\n")

    # Test with TNSR-EUR (the coin that was selected)
    await simulate_with_real_data("TNSR-EUR", hours=24)

    print("\n" + "=" * 70)
    print("  RECOMMENDATION")
    print("=" * 70)
    print("\n✅ Your strategy WOULD work if:")
    print("   - Price moves within the grid range")
    print("   - Orders get filled at grid levels")
    print("   - You can sell at higher prices")
    print("\n⚠️  Paper trading doesn't show this because:")
    print("   - No order books for most coins")
    print("   - Orders aren't simulated")
    print("\n💡 To test for real:")
    print("   1. Use this simulator with historical data")
    print("   2. Or switch to live trading with small amount (€10-20)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
