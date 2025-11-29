#!/usr/bin/env python3
"""
Script om monitored coins uit logs of database te halen
"""

import re
from pathlib import Path


def get_coins_from_logs(log_file="logs/logs_multi_coin_grid_v2.log"):
    """Haal monitored coins uit logs"""
    log_path = Path(log_file)

    if not log_path.exists():
        print(f"❌ Log file niet gevonden: {log_file}")
        return []

    coins = []
    with open(log_path, 'r') as f:
        lines = f.readlines()

        # Zoek naar de laatste "All X selected coins" sectie
        last_discovery_idx = -1
        for i, line in enumerate(lines):
            if "All" in line and "selected coins by 24h volume" in line:
                last_discovery_idx = i

        if last_discovery_idx >= 0:
            # Pak de volgende 60 regels vanaf de discovery regel
            for j in range(last_discovery_idx + 1, min(last_discovery_idx + 61, len(lines))):
                # Format: "   1. USDC-EUR: €96,380,793 (spread: 0.012%)"
                # Of: "INFO -    1. USDC-EUR: €96,380,793 (spread: 0.012%)"
                match = re.search(r'(\d+)\.\s+([A-Z0-9-]+-EUR)', lines[j])
                if match:
                    coin = match.group(2)
                    if coin not in coins:  # Voorkom duplicaten
                        coins.append(coin)

    return coins


def get_coins_from_config():
    """Haal coins uit config (als manual_trading_pairs is ingesteld)"""
    config_path = Path("multi_coin_grid_pro/config/multi_coin_grid.yml")

    if not config_path.exists():
        return None

    with open(config_path, 'r') as f:
        content = f.read()

        # Zoek naar manual_trading_pairs
        match = re.search(r'manual_trading_pairs:\s*\[(.*?)\]', content, re.DOTALL)
        if match:
            pairs_str = match.group(1)
            coins = [c.strip().strip('"').strip("'") for c in pairs_str.split(',') if c.strip()]
            return coins

    return None


def main():
    print("📊 Monitored Coins:")
    print("=" * 50)

    # Probeer eerst uit config (als manual pairs zijn ingesteld)
    manual_coins = get_coins_from_config()
    if manual_coins:
        print("✅ Manual Trading Pairs (uit config):")
        for i, coin in enumerate(manual_coins, 1):
            print(f"  {i}. {coin}")
        return

    # Anders uit logs
    coins = get_coins_from_logs()

    if coins:
        print(f"✅ Gevonden {len(coins)} coins (uit logs):")
        for i, coin in enumerate(coins, 1):
            print(f"  {i}. {coin}")
    else:
        print("❌ Geen coins gevonden in logs")
        print("💡 Tip: Bot moet eerst draaien voor coin discovery")


if __name__ == "__main__":
    main()
