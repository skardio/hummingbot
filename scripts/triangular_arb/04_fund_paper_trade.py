#!/usr/bin/env python3
"""
Fund paper-trade account with initial balances for triangular arbitrage testing.

This script initializes the paper-trade connector with starting capital
for each base currency (ETH, USDC, EUR, AUD) so the monitor bot can
execute trades.
"""

import asyncio
import os
import sys
from datetime import datetime
from decimal import Decimal

# Add hummingbot to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from hummingbot.connector.paper_trade.paper_trade_connector import PaperTradeConnector
from hummingbot.core.event_forwarder import EventForwarder
from hummingbot.core.utils.async_utils import safe_ensure_future


async def fund_paper_trade_account(exchange: str, balances: dict):
    """
    Fund a paper-trade account with initial balances.

    Args:
        exchange: Exchange name (e.g., 'kraken')
        balances: Dict of {currency: amount_as_Decimal}

    Example:
        balances = {
            'ETH': Decimal('1.0'),
            'USDC': Decimal('100.0'),
            'EUR': Decimal('50.0'),
            'AUD': Decimal('50.0'),
        }
    """

    # Create trading pairs set from all possible combinations
    # (simplified - just use common pairs)
    trading_pairs = [
        'ETH-USD', 'ETH-EUR', 'ETH-USDC', 'ETH-USDT', 'ETH-GBP', 'ETH-CAD', 'ETH-AUD', 'ETH-CHF',
        'USDC-USD', 'USDC-EUR', 'USDC-USDT', 'USDC-GBP', 'USDC-CAD', 'USDC-AUD', 'USDC-CHF',
        'USDT-USD', 'USDT-EUR', 'USDT-GBP', 'USDT-CAD', 'USDT-AUD', 'USDT-CHF',
        'EUR-USD', 'EUR-GBP', 'EUR-CAD', 'EUR-AUD', 'EUR-CHF', 'EUR-JPY',
        'GBP-USD', 'GBP-JPY', 'GBP-CAD', 'GBP-AUD', 'GBP-CHF',
        'USD-CAD', 'USD-AUD', 'USD-CHF', 'USD-JPY',
        'CAD-AUD', 'CAD-CHF', 'CAD-JPY',
        'AUD-USD', 'AUD-JPY', 'AUD-CAD', 'AUD-CHF',
        'CHF-JPY',
    ]

    print(f"Initializing paper-trade connector for {exchange}...")
    print(f"Trading pairs: {len(trading_pairs)}")

    try:
        connector = PaperTradeConnector(exchange=exchange, trading_pairs=trading_pairs)

        # Set initial balances
        print(f"\nSetting initial balances:")
        for currency, amount in balances.items():
            print(f"  {currency}: {amount}")
            connector.set_balance(currency, float(amount))

        # Verify balances were set
        print(f"\nVerifying balances:")
        all_ok = True
        for currency, expected_amount in balances.items():
            actual_balance = Decimal(str(connector.get_balance(currency)))
            matches = actual_balance == expected_amount
            status = "✓" if matches else "✗"
            print(f"  {status} {currency}: {actual_balance} (expected: {expected_amount})")
            if not matches:
                all_ok = False

        if all_ok:
            print(f"\n✅ Paper-trade account successfully funded!")
            print(f"\nYou can now run the monitor bot:")
            print(f"  python3 scripts/triangular_arb/03_monitor_continuous_24h.py")
            print(f"\nOr with nohup:")
            print(f"  cd /home/mo/repos/hummingbot")
            print(f"  nohup python3 scripts/triangular_arb/03_monitor_continuous_24h.py > logs/bot_stdout.log 2>&1 &")
        else:
            print(f"\n⚠️  Some balances were not set correctly!")
            return False

    except Exception as e:
        print(f"❌ Error initializing paper-trade connector: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


def main():
    """Main entry point."""

    # Define initial balances for paper-trade testing
    # These values represent starting capital for each base currency
    starting_balances = {
        'ETH': Decimal('0.5'),      # ~€50 at current rates
        'USDC': Decimal('50.0'),    # ~€50
        'EUR': Decimal('50.0'),     # €50
        'AUD': Decimal('50.0'),     # ~€30 AUD
        'USD': Decimal('50.0'),     # ~€50
        'GBP': Decimal('40.0'),     # ~€50
        'CAD': Decimal('65.0'),     # ~€50
        'CHF': Decimal('45.0'),     # ~€50
        'JPY': Decimal('5500.0'),   # ~€50
        'USDT': Decimal('50.0'),    # ~€50
    }

    print("=" * 60)
    print("Paper-Trade Account Funding Tool")
    print("=" * 60)
    print(f"Exchange: kraken")
    print(f"Starting capital per currency:")
    for currency, amount in starting_balances.items():
        print(f"  - {currency}: {amount}")
    print("=" * 60)

    # Run the funding
    success = asyncio.run(fund_paper_trade_account('kraken', starting_balances))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
