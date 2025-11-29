#!/usr/bin/env python3
"""
Check which trading pairs are available in the paper trading order book
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hummingbot.client.settings import AllConnectorSettings
from hummingbot.connector.exchange.paper_trade import create_paper_trade_market


async def main():
    print("=" * 70)
    print("  PAPER TRADING ORDER BOOK - TRADING PAIRS CHECK")
    print("=" * 70)
    print()

    # Get connector settings
    connector_name = "kraken"
    print(f"📡 Getting connector settings for {connector_name}...")

    try:
        conn_setting = AllConnectorSettings.get_connector_settings()[connector_name]

        # Create non-trading connector instance to get trading pairs
        print("🔧 Creating non-trading connector instance...")
        base_connector = conn_setting.non_trading_connector_instance_with_default_configuration(
            trading_pairs=[]  # Empty list - connector will populate with available pairs
        )

        await base_connector.start_network()
        print("✅ Connected to Kraken")

        # Wait for trading pairs to be loaded
        await asyncio.sleep(3)

        # Get trading pairs from base connector
        base_trading_pairs = list(base_connector.trading_pairs)
        print(f"\n📊 Base connector has {len(base_trading_pairs)} trading pairs")
        if len(base_trading_pairs) > 0:
            print(f"   Sample (first 20): {base_trading_pairs[:20]}")

        # Show EUR pairs from base connector
        eur_pairs_base = [pair for pair in base_trading_pairs if pair.endswith('-EUR')]
        print(f"\n💰 EUR pairs in base connector ({len(eur_pairs_base)}):")
        for pair in sorted(eur_pairs_base)[:30]:  # Show first 30
            print(f"   - {pair}")
        if len(eur_pairs_base) > 30:
            print(f"   ... and {len(eur_pairs_base) - 30} more")

        # Create paper trading connector with these pairs
        print(f"\n🔧 Creating paper trading connector with {len(base_trading_pairs)} trading pairs...")
        paper_connector = create_paper_trade_market(
            exchange_name=connector_name,
            trading_pairs=base_trading_pairs
        )

        # Initialize paper trade market
        paper_connector.init_paper_trade_market()

        # Wait a moment for order books to initialize
        await asyncio.sleep(3)

        # Get order books from paper trading connector
        paper_order_books = paper_connector.order_books
        paper_trading_pairs = list(paper_order_books.keys())

        print("\n✅ Paper trading connector initialized")
        print(f"📚 Paper trading order book has {len(paper_trading_pairs)} trading pairs")
        print()

        # Show EUR pairs specifically
        eur_pairs = [pair for pair in paper_trading_pairs if pair.endswith('-EUR')]
        print(f"💰 EUR pairs in paper trading order book ({len(eur_pairs)}):")
        for pair in sorted(eur_pairs)[:50]:  # Show first 50
            print(f"   - {pair}")
        if len(eur_pairs) > 50:
            print(f"   ... and {len(eur_pairs) - 50} more")

        # Check for WLFI-EUR specifically
        if 'WLFI-EUR' in paper_trading_pairs:
            print("\n✅ WLFI-EUR is available in paper trading order book")
        else:
            print("\n❌ WLFI-EUR is NOT available in paper trading order book")
            if 'WLFI-EUR' in base_trading_pairs:
                print("   (But it IS in base connector trading pairs)")
            else:
                print("   (And it's also NOT in base connector trading pairs)")

        print()
        print("=" * 70)
        print("NOTE: Only trading pairs in the base connector's trading_pairs")
        print("      are available in the paper trading order book.")
        print("=" * 70)

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'base_connector' in locals():
            await base_connector.stop_network()


if __name__ == "__main__":
    asyncio.run(main())
