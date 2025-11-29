#!/usr/bin/env python3
"""
Simple Bitget Balance Checker
Uses Bitget API directly to check Spot and Futures wallets
"""
import hashlib
import hmac
import os
import time
from decimal import Decimal

import requests


def generate_signature(timestamp, method, request_path, body, secret_key):
    """Generate Bitget API signature"""
    message = str(timestamp) + method + request_path + body
    mac = hmac.new(
        bytes(secret_key, encoding='utf8'),
        bytes(message, encoding='utf8'),
        digestmod=hashlib.sha256
    )
    return mac.hexdigest()


def check_bitget_balances():
    """Check Bitget spot and futures balances"""

    # Get API keys from environment
    api_key = os.getenv("BITGET_API_KEY", "")
    api_secret = os.getenv("BITGET_SECRET_KEY", "")
    passphrase = os.getenv("BITGET_PASSPHRASE", "")

    if not api_key or not api_secret or not passphrase:
        print("❌ BITGET API KEYS NOT FOUND!")
        print("\nPlease set environment variables:")
        print("  export BITGET_API_KEY='your_api_key'")
        print("  export BITGET_SECRET_KEY='your_secret_key'")
        print("  export BITGET_PASSPHRASE='your_passphrase'")
        print("\nOr get them from Hummingbot config:")
        print("  cat ~/.hummingbot/connectors/bitget_perpetual.yml")
        return

    base_url = "https://api.bitget.com"

    print("=" * 70)
    print("  BITGET BALANCE CHECKER")
    print("=" * 70)
    print()

    # Check Spot Wallet
    spot_usdt = Decimal("0")
    try:
        print("🔌 Checking Spot Wallet...")
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        request_path = "/api/v2/spot/account/assets"
        body = ""

        signature = generate_signature(timestamp, method, request_path, body, api_secret)

        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

        response = requests.get(base_url + request_path, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("code") == "00000":
            assets = data.get("data", [])
            for asset in assets:
                if asset.get("coin") == "USDT":
                    spot_usdt = Decimal(asset.get("available", "0"))
                    spot_total = Decimal(asset.get("total", "0"))

                    print()
                    print("=" * 70)
                    print("  SPOT WALLET BALANCES")
                    print("=" * 70)
                    print()
                    print("💰 USDT:")
                    print(f"   Total:     {spot_total:,.4f} USDT")
                    print(f"   Available: {spot_usdt:,.4f} USDT")
                    print()
                    break
        else:
            print(f"⚠️  Error checking Spot wallet: {data.get('msg', 'Unknown error')}")
    except Exception as e:
        print(f"⚠️  Could not check Spot wallet: {e}")
        print()

    # Check Futures Wallet
    futures_usdt = Decimal("0")
    try:
        print("🔌 Checking Futures Wallet...")
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        request_path = "/api/v2/mix/account/accounts"
        body = ""

        signature = generate_signature(timestamp, method, request_path, body, api_secret)

        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

        # Check USDT-M futures
        params = {"productType": "USDT-FUTURES"}
        response = requests.get(base_url + request_path, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get("code") == "00000":
            accounts = data.get("data", [])
            for account in accounts:
                if account.get("marginCoin") == "USDT":
                    futures_usdt = Decimal(account.get("crossedMaxAvailable", "0"))
                    futures_total = Decimal(account.get("accountEquity", "0"))
                    futures_locked = futures_total - futures_usdt

                    print()
                    print("=" * 70)
                    print("  FUTURES WALLET BALANCES")
                    print("=" * 70)
                    print()
                    print("💰 USDT:")
                    print(f"   Total:     {futures_total:,.4f} USDT")
                    print(f"   Available: {futures_usdt:,.4f} USDT")
                    print(f"   Locked:    {futures_locked:,.4f} USDT")
                    print()
                    break
        else:
            print(f"⚠️  Error checking Futures wallet: {data.get('msg', 'Unknown error')}")
    except Exception as e:
        print(f"⚠️  Could not check Futures wallet: {e}")
        import traceback
        traceback.print_exc()
        print()

    # Summary
    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()

    print(f"📊 Spot Wallet:    {spot_usdt:,.2f} USDT")
    print(f"📊 Futures Wallet: {futures_usdt:,.2f} USDT")
    print()

    if futures_usdt >= Decimal("100"):
        print("✅ SUFFICIENT BALANCE for futures grid trading!")
        print(f"   Futures wallet has {futures_usdt:,.2f} USDT (needed: 100 USDT)")
    else:
        print("❌ INSUFFICIENT BALANCE for futures grid trading!")
        print(f"   Futures wallet has {futures_usdt:,.2f} USDT (needed: 100 USDT)")
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
            transfer_amount = min(spot_usdt, Decimal("100"))
            print(f"   5. Transfer: {transfer_amount:,.0f} USDT")
            print("   6. Click Transfer")
            print()
            print("   After transfer, run this script again to verify!")
        else:
            print("💡 SOLUTION:")
            print("   1. Deposit more USDT to your Bitget account")
            print("   2. Then transfer from Spot to Futures wallet")
            print("   3. Check Bitget website: https://www.bitget.com/")
            print("      Go to: Assets → Futures → Transfer")


if __name__ == "__main__":
    print()
    print("🔍 Checking Bitget Wallets Balance...")
    print()
    check_bitget_balances()
    print()
