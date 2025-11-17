#!/usr/bin/env python3
"""Quick balance check via Hummingbot connector"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Add hummingbot to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.client.config.config_var import ConfigVar
from hummingbot.connector.exchange.kraken.kraken_exchange import KrakenExchange


async def main():
    # Create exchange instance
    kraken = KrakenExchange(
        client_config_map=ClientConfigAdapter({}),
        kraken_api_key="",
        kraken_secret_key="",
        trading_pairs=["ETH-EUR", "USDC-EUR"],
    )

    try:
        await kraken._update_balances()
        balances = kraken._account_balances

        print("\n💰 KRAKEN SALDO:")
        for currency in ['EUR', 'USDC', 'USDT', 'ETH', 'XRP', 'SOL', 'ADA']:
            balance = balances.get(currency, Decimal('0'))
            if balance > Decimal('0.0001'):
                print(f"  {currency}: {balance}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await kraken.stop_network()

if __name__ == "__main__":
    asyncio.run(main())
