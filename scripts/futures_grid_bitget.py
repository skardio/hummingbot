"""
Bitget Futures Multi-Coin Grid Strategy

Runs the existing multi-coin grid controller against the bitget_perpetual connector with a
USDT collateral configuration. Spot bot remains untouched; launch this script in a separate
Hummingbot instance to trade futures concurrently.
"""

import os
from pathlib import Path
from typing import Dict, Set

from hummingbot.connector.connector_base import ConnectorBase
from multi_coin_grid_pro.futures_bitget.config_manager import FuturesGridConfigManager
from multi_coin_grid_pro.futures_bitget.config_schema import FuturesGridBitgetConfig
from multi_coin_grid_pro.futures_bitget.controller import FuturesGridBitgetController
from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2


class BitgetFuturesGridStrategyConfig(MultiCoinGridStrategyConfig):
    """
    Config wrapper so the script filename shown in logs/CLI reflects this entrypoint.
    """

    script_file_name: str = os.path.basename(__file__)


class BitgetFuturesGridStrategy(MultiCoinGridStrategyV2):
    """
    Same strategy/controller stack as the spot bot, but loading `futures_grid_bitget` config.
    """

    CONFIG_NAME: str = "futures_grid_bitget"
    CONFIG_MANAGER_CLASS = FuturesGridConfigManager
    CONTROLLER_CLASS = FuturesGridBitgetController
    CONTROLLER_CONFIG_CLASS = FuturesGridBitgetConfig
    CONFIG_FALLBACK_DIR = Path(__file__).parent.parent / "multi_coin_grid_pro" / "futures_bitget" / "config"
    CONFIG_FALLBACK_EXT = ".yaml"

    # Set markets directly so Hummingbot knows which connector to initialize
    # This is needed because init_markets() may not be called in all cases
    # Use full trading pairs (not just quote asset) to avoid "not enough values to unpack" error
    markets: Dict[str, Set[str]] = {
        "bitget_perpetual": {
            "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT",
            "AVAX-USDT", "DOGE-USDT", "ARB-USDT", "OP-USDT", "SUI-USDT"
        }
    }

    @classmethod
    def init_markets(cls, config=None):
        """Initialize markets - ensure bitget_perpetual connector is included with full trading pairs"""
        connector_name = "bitget_perpetual"

        # Try to load trading pairs from config
        trading_pairs = set()

        if config is not None:
            # Use trading pairs from config if available
            if hasattr(config, 'manual_trading_pairs') and config.manual_trading_pairs:
                trading_pairs = set(config.manual_trading_pairs)
            elif hasattr(config, 'connector_name'):
                connector_name = config.connector_name
                if hasattr(config, 'quote_asset'):
                    # Fallback: use common USDT pairs if manual_trading_pairs not available
                    trading_pairs = {
                        "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT",
                        "AVAX-USDT", "DOGE-USDT", "ARB-USDT", "OP-USDT", "SUI-USDT"
                    }
        else:
            # Try to load from config file
            try:
                config_manager = cls.CONFIG_MANAGER_CLASS()
                yaml_config = config_manager.load_config(cls.CONFIG_NAME)
                if 'manual_trading_pairs' in yaml_config and yaml_config['manual_trading_pairs']:
                    trading_pairs = set(yaml_config['manual_trading_pairs'])
                else:
                    # Fallback to common USDT pairs
                    trading_pairs = {
                        "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT",
                        "AVAX-USDT", "DOGE-USDT", "ARB-USDT", "OP-USDT", "SUI-USDT"
                    }
                if 'connector_name' in yaml_config:
                    connector_name = yaml_config['connector_name']
            except Exception:
                # Final fallback: use common USDT pairs
                trading_pairs = {
                    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT",
                    "AVAX-USDT", "DOGE-USDT", "ARB-USDT", "OP-USDT", "SUI-USDT"
                }

        # Ensure we have at least some trading pairs
        if not trading_pairs:
            trading_pairs = {"BTC-USDT", "ETH-USDT", "SOL-USDT"}

        # Set markets with full trading pairs (not just quote asset)
        cls.markets = {connector_name: trading_pairs}

        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"✅ Initialized markets for {connector_name} with {len(trading_pairs)} trading pairs")


def create_strategy(connectors: Dict[str, ConnectorBase]) -> BitgetFuturesGridStrategy:
    """
    Factory used by Hummingbot when `start --script futures_grid_bitget.py` is executed.
    """

    config = BitgetFuturesGridStrategyConfig()
    return BitgetFuturesGridStrategy(connectors, config)
