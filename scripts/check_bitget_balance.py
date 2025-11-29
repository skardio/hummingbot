#!/usr/bin/env python3
"""
Check Bitget Balance Script
Shows balances for both Spot and Futures wallets
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

# Add hummingbot to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.derivative.bitget_perpetual.bitget_perpetual_derivative import BitgetPerpetualDerivative
from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange


async def check_bitget_balances():
    """Check Bitget spot and futures balances"""

    # Get API keys from environment or config
    api_key = os.getenv("BITGET_API_KEY", "")
    api_secret = os.getenv("BITGET_SECRET_KEY", "")
    passphrase = os.getenv("BITGET_PASSPHRASE", "")

    if not api_key or not api_secret or not passphrase:
        print("❌ BITGET API KEYS NOT FOUND!")
        print("\nPlease set environment variables:")
        print("  export BITGET_API_KEY='your_api_key'")
        print("  export BITGET_SECRET_KEY='your_secret_key'")
        print("  export BITGET_PASSPHRASE='your_passphrase'")
        print("\nOr check your Hummingbot config for Bitget credentials.")
        return

    print("=" * 70)
    print("  BITGET BALANCE CHECKER")
    print("=" * 70)
    print()

    # Check Spot Wallet first
    spot_usdt = Decimal("0")
    try:
        print("🔌 Connecting to Bitget Spot Exchange...")
        spot_connector = BitgetExchange(
            client_config_map=ClientConfigAdapter({}),
            bitget_api_key=api_key,
            bitget_secret_key=api_secret,
            bitget_passphrase=passphrase,
            trading_pairs=["BTC-USDT", "ETH-USDT"],  # Dummy pairs for connection
        )

        await spot_connector.start_network()
        await spot_connector._update_balances()

        spot_usdt = spot_connector.get_available_balance("USDT")
        spot_total = spot_connector.get_balance("USDT")

        print()
        print("=" * 70)
        print("  SPOT WALLET BALANCES")
        print("=" * 70)
        print()
        print("💰 USDT:")
        print(f"   Total:     {spot_total:,.4f} USDT")
        print(f"   Available: {spot_usdt:,.4f} USDT")
        print()

        await spot_connector.stop_network()
    except Exception as e:
        print(f"⚠️  Could not check Spot wallet: {e}")
        print()

    # Check Futures Wallet
    try:
        print("🔌 Connecting to Bitget Perpetual (Futures)...")
        perpetual_connector = BitgetPerpetualDerivative(
            client_config_map=ClientConfigAdapter({}),
            bitget_api_key=api_key,
            bitget_secret_key=api_secret,
            bitget_passphrase=passphrase,
            trading_pairs=["BTC-USDT", "ETH-USDT", "SOL-USDT"],  # Dummy pairs for connection
        )

        # Start connector
        await perpetual_connector.start_network()

        # Update balances
        print("📊 Fetching balances...")
        await perpetual_connector._update_balances()

        # Get balances
        account_balances = perpetual_connector._account_balances
        available_balances = perpetual_connector._account_available_balances

        print()
        print("=" * 70)
        print("  FUTURES WALLET BALANCES")
        print("=" * 70)
        print()

        # Show USDT balance first (most important)
        usdt_total = account_balances.get("USDT", Decimal("0"))
        usdt_available = available_balances.get("USDT", Decimal("0"))
        usdt_locked = usdt_total - usdt_available

        print("💰 USDT:")
        print(f"   Total:     {usdt_total:,.4f} USDT")
        print(f"   Available: {usdt_available:,.4f} USDT")
        print(f"   Locked:    {usdt_locked:,.4f} USDT")
        print()

        if usdt_available < Decimal("100"):
            print("⚠️  WARNING: Less than 100 USDT available!")
            print("   The futures grid needs at least 100 USDT to trade.")
            print()

        # Show other balances
        print("📊 Other Assets:")
        other_assets = sorted([(k, v) for k, v in account_balances.items() if k != "USDT" and v > Decimal("0.0001")])
        if other_assets:
            for asset, balance in other_assets:
                available = available_balances.get(asset, Decimal("0"))
                locked = balance - available
                print(f"   {asset:6s}: {balance:>15,.8f} (Available: {available:>15,.8f}, Locked: {locked:>15,.8f})")
        else:
            print("   (No other assets)")

        print()
        print("=" * 70)
        print("  SUMMARY")
        print("=" * 70)
        print()

        print(f"📊 Spot Wallet:    {spot_usdt:,.2f} USDT")
        print(f"📊 Futures Wallet: {usdt_available:,.2f} USDT")
        print()

        if usdt_available >= Decimal("100"):
            print("✅ SUFFICIENT BALANCE for futures grid trading!")
            print(f"   Futures wallet has {usdt_available:,.2f} USDT (needed: 100 USDT)")
        else:
            print("❌ INSUFFICIENT BALANCE for futures grid trading!")
            print(f"   Futures wallet has {usdt_available:,.2f} USDT (needed: 100 USDT)")
            print()

            if spot_usdt >= Decimal("100"):
                print("💡 SOLUTION:")
                print(f"   ✅ You have {spot_usdt:,.2f} USDT in your Spot wallet!")
                print("   → Transfer USDT from Spot to Futures wallet:")
                print()
                print("   1. Go to Bitget website: https://www.bitget.com/")
                print("   2. Login to your account")
                print("   3. Go to: Assets → Futures → Transfer")
                print("   4. Select: From Spot → To Futures")
                print(f"   5. Transfer: {min(spot_usdt, Decimal('100')):,.0f} USDT")
                print("   6. Click Transfer")
                print()
            else:
                print("💡 SOLUTION:")
                print("   1. Deposit more USDT to your Bitget account")
                print("   2. Then transfer from Spot to Futures wallet")
                print("   3. Check Bitget website: https://www.bitget.com/")
                print("      Go to: Assets → Futures → Transfer")

        # Stop connector
        await perpetual_connector.stop_network()

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("💡 TROUBLESHOOTING:")
        print("   1. Check if API keys are correct")
        print("   2. Check if API keys have 'Read' permission")
        print("   3. Check if passphrase is correct")
        print("   4. Try connecting via Hummingbot CLI first:")
        print("      >>> connect bitget_perpetual")


if __name__ == "__main__":
    print()
    print("🔍 Checking Bitget Futures Wallet Balance...")
    print()
    asyncio.run(check_bitget_balances())
    print()
