"""
Bitget SPOT Multi-Coin Grid Strategy

Production-ready grid strategy for Bitget SPOT with USDT pairs.
Uses the same architecture as your Kraken spot grid bot.

Usage:
    start --script spot_grid_bitget.py

Configuration:
    multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
"""

import os
from pathlib import Path
from typing import Dict, Set

from hummingbot.connector.connector_base import ConnectorBase
from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
from multi_coin_grid_pro.spot_bitget.controller import SpotGridBitgetController


class BitgetSpotGridStrategyConfig(MultiCoinGridStrategyConfig):
    """
    Config wrapper for Bitget SPOT strategy.
    """
    script_file_name: str = os.path.basename(__file__)


class BitgetSpotGridStrategy(MultiCoinGridStrategyV2):
    """
    Bitget SPOT Grid Strategy

    Same proven controller architecture as your Kraken bot, adapted for Bitget:
    - Multi-coin grid trading
    - Trend-following entry
    - Dynamic grid sizing
    - Risk management
    - Stop loss / take profit

    Key Differences from Kraken:
    - Connector: bitget (spot)
    - Quote: USDT (not EUR)
    - Fees: 0.1% maker/taker
    - Rate limits: 10 orders/sec
    """

    CONFIG_NAME: str = "spot_grid_bitget"
    CONFIG_MANAGER_CLASS = SpotGridBitgetConfigManager
    CONTROLLER_CLASS = SpotGridBitgetController
    CONTROLLER_CONFIG_CLASS = SpotGridBitgetConfig
    CONFIG_FALLBACK_DIR = Path(__file__).parent.parent / "spot_bitget" / "config"
    CONFIG_FALLBACK_EXT = ".yaml"

    # Markets are set dynamically, but define default for initialization
    markets: Dict[str, Set[str]] = {
        "bitget": {
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT",
        }
    }

    @classmethod
    def init_markets(cls, config: SpotGridBitgetConfig = None):
        """
        Initialize markets - ensure bitget connector is included with trading pairs.

        This is called by Hummingbot to determine which connectors to initialize.
        Same pattern as Kraken: only pass quote asset for dynamic discovery, or
        common pairs for paper trading to ensure order books are available.
        """
        connector_name = "bitget"
        quote_asset = "USDT"
        paper_trading = False

        # Try to load config to check for paper trading
        try:
            config_manager = cls.CONFIG_MANAGER_CLASS()
            yaml_config = config_manager.load_config()
            connector_name = yaml_config.get('connector_name', connector_name)
            quote_asset = yaml_config.get('quote_asset', quote_asset)
            paper_trading = yaml_config.get('paper_trading', paper_trading)
        except Exception:
            pass  # Use defaults

        # Adjust connector name for paper trading
        if paper_trading and not connector_name.endswith('_paper_trade'):
            connector_name = f"{connector_name}_paper_trade"

        if config is not None:
            # Use config values if provided
            connector_name = config.connector_name
            quote_asset = config.quote_asset

        # For paper trading: pass common trading pairs so order books are initialized
        if paper_trading:
            common_usdt_pairs = {
                "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT",
                "DOT-USDT", "AVAX-USDT", "LINK-USDT", "MATIC-USDT", "UNI-USDT",
                "ATOM-USDT", "LTC-USDT", "BCH-USDT", "NEAR-USDT", "APT-USDT",
                "ARB-USDT", "OP-USDT", "SUI-USDT", "ALGO-USDT", "FIL-USDT",
            }
            cls.markets = {connector_name: common_usdt_pairs}
        else:
            # Live trading: only pass quote asset (connector will discover pairs dynamically)
            cls.markets = {connector_name: {quote_asset}}


def create_strategy(connectors: Dict[str, ConnectorBase]) -> BitgetSpotGridStrategy:
    """
    Factory function called by Hummingbot.

    Args:
        connectors: Dict of initialized connectors

    Returns:
        BitgetSpotGridStrategy instance

    Usage:
        start --script spot_grid_bitget.py
    """
    config = BitgetSpotGridStrategyConfig()
    return BitgetSpotGridStrategy(connectors, config)


# Make sure function is named 'create' for compatibility
create = create_strategy
