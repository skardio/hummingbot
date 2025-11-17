#!/usr/bin/env python3
"""
Verkoop USDC terug naar EUR
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.kraken.kraken_exchange import KrakenExchange


async def main():
    print("🔄 Connecting to Kraken...")

    kraken = KrakenExchange(
        client_config_map=ClientConfigAdapter({}),
        kraken_api_key="",
        kraken_secret_key="",
        trading_pairs=["USDC-EUR"],
    )

    try:
        await kraken.start_network()
        print("✓ Connected")

        # Get balance
        await kraken._update_balances()
        balances = kraken._account_balances

        usdc_balance = balances.get('USDC', Decimal('0'))
        eur_balance = balances.get('EUR', Decimal('0'))

        print(f"\n💰 HUIDIGE SALDO:")
        print(f"   EUR: {eur_balance}")
        print(f"   USDC: {usdc_balance}")

        if usdc_balance > Decimal('0.1'):
            print(f"\n🔄 Verkoop {usdc_balance} USDC voor EUR...")

            # Sell USDC for EUR (market order)
            order = await kraken.sell(
                trading_pair="USDC-EUR",
                amount=float(usdc_balance),
                order_type="market",
                price=Decimal('0')  # Market order
            )

            print(f"✓ Order geplaatst: {order}")

            # Wait a bit and check new balance
            await asyncio.sleep(2)
            await kraken._update_balances()
            balances = kraken._account_balances

            new_eur = balances.get('EUR', Decimal('0'))
            new_usdc = balances.get('USDC', Decimal('0'))

            print(f"\n💰 NIEUW SALDO:")
            print(f"   EUR: {new_eur} (was {eur_balance})")
            print(f"   USDC: {new_usdc} (was {usdc_balance})")
            print(f"\n✓ USDC verkocht!")
        else:
            print("\n⚠️  Geen USDC om te verkopen")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await kraken.stop_network()

if __name__ == "__main__":
    asyncio.run(main())
