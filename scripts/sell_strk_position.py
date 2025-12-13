#!/usr/bin/env python3
"""
Verkoop STRK positie terug naar EUR
Gebruik dit script om een open STRK positie te verkopen die de bot heeft achtergelaten
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
        trading_pairs=["STRK-EUR"],
    )

    try:
        await kraken.start_network()
        print("✓ Connected")

        # Get balance
        await kraken._update_balances()
        balances = kraken._account_balances

        strk_balance = balances.get('STRK', Decimal('0'))
        eur_balance = balances.get('EUR', Decimal('0'))

        print(f"\n💰 HUIDIGE SALDO:")
        print(f"   EUR: {eur_balance}")
        print(f"   STRK: {strk_balance}")

        if strk_balance > Decimal('0.1'):
            # Get current price
            current_price = await kraken.get_price_by_type("STRK-EUR", "midPrice")
            estimated_value = float(strk_balance) * float(current_price)

            print(f"\n📊 HUIDIGE PRIJS:")
            print(f"   STRK-EUR: €{current_price}")
            print(f"   Geschatte waarde: €{estimated_value:.2f}")

            response = input(f"\n❓ Verkoop {strk_balance} STRK voor EUR? (ja/nee): ")

            if response.lower() in ['ja', 'j', 'yes', 'y']:
                print(f"\n🔄 Verkoop {strk_balance} STRK voor EUR...")

                # Sell STRK for EUR (market order)
                order = await kraken.sell(
                    trading_pair="STRK-EUR",
                    amount=float(strk_balance),
                    order_type="market",
                    price=Decimal('0')  # Market order
                )

                print(f"✓ Order geplaatst: {order}")

                # Wait a bit and check new balance
                await asyncio.sleep(3)
                await kraken._update_balances()
                balances = kraken._account_balances

                new_eur = balances.get('EUR', Decimal('0'))
                new_strk = balances.get('STRK', Decimal('0'))

                print(f"\n💰 NIEUW SALDO:")
                print(f"   EUR: {new_eur} (was {eur_balance})")
                print(f"   STRK: {new_strk} (was {strk_balance})")

                if new_strk < Decimal('0.1'):
                    print(f"\n✅ STRK succesvol verkocht!")
                else:
                    print(f"\n⚠️  Nog {new_strk} STRK over. Mogelijk order nog niet volledig uitgevoerd.")
            else:
                print("\n❌ Verkoop geannuleerd")
        else:
            print("\n✅ Geen STRK om te verkopen")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await kraken.stop_network()

if __name__ == "__main__":
    asyncio.run(main())
