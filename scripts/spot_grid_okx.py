"""
OKX SPOT Multi-Coin Grid Strategy

Production-ready grid strategy for OKX SPOT with USD pairs.
Uses the same architecture as Kraken and Bitget spot grid bots.

Usage:
    start --script spot_grid_okx.py

Configuration:
    multi_coin_grid_pro/spot_okx/config/spot_grid_okx.yaml
"""

import os
from pathlib import Path
from typing import Dict, Set

from hummingbot.connector.connector_base import ConnectorBase
from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import (
    MultiCoinGridStrategyConfig as _MultiCoinGridStrategyConfig,
    MultiCoinGridStrategyV2 as _BaseStrategyV2,
)
from multi_coin_grid_pro.spot_okx.config_manager import SpotGridOKXConfigManager
from multi_coin_grid_pro.spot_okx.config_schema import SpotGridOKXConfig
from multi_coin_grid_pro.spot_okx.controller import SpotGridOKXController
from multi_coin_grid_pro.utils.log_archiver import archive_bot_logs


class OKXSpotGridStrategyConfig(_MultiCoinGridStrategyConfig):
    """
    Config wrapper for OKX SPOT strategy.
    """
    script_file_name: str = os.path.basename(__file__)


class OKXSpotGridStrategy(_BaseStrategyV2):
    """
    OKX SPOT Grid Strategy

    Same proven controller architecture as Kraken and Bitget bots, adapted for OKX:
    - Multi-coin grid trading
    - Trend-following entry
    - Dynamic grid sizing
    - Risk management
    - Stop loss / take profit

    Key Differences from Bitget:
    - Connector: okx (spot)
    - Fees: 0.08% maker / 0.10% taker (VIP0) — lower than Bitget
    - Liquidity: top-3 globally, extremely tight spreads
    - Rate limits: 60 orders/sec (generous)
    """

    CONFIG_NAME: str = "spot_grid_okx"
    CONFIG_MANAGER_CLASS = SpotGridOKXConfigManager
    CONTROLLER_CLASS = SpotGridOKXController
    CONTROLLER_CONFIG_CLASS = SpotGridOKXConfig
    CONFIG_FALLBACK_DIR = Path(__file__).parent.parent / "multi_coin_grid_pro" / "spot_okx" / "config"
    CONFIG_FALLBACK_EXT = ".yaml"

    def __init__(self, connectors: Dict[str, ConnectorBase], config=None):
        # Archive old OKX logs before this run starts
        try:
            archive_bot_logs("okx")
        except Exception:
            pass  # Never block startup due to log archiving
        super().__init__(connectors, config)

    # Markets are set dynamically; define sensible USD defaults for initialization.
    markets: Dict[str, Set[str]] = {
        "okx": {
            "BTC-USD",
            "ETH-USD",
            "XRP-USD",
        }
    }

    @classmethod
    def init_markets(cls, config: SpotGridOKXConfig = None):
        """
        Initialize markets — ensure okx connector is included with trading pairs.

        Called by Hummingbot to determine which connectors to initialize.
        """
        connector_name = "okx"
        quote_asset = "USD"
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
            connector_name = config.connector_name
            quote_asset = config.quote_asset

        # For paper trading: pass common trading pairs so order books are initialized
        if paper_trading:
            common_bases = {
                "BTC", "ETH", "XRP", "ADA", "LINK",
                "AVAX", "LTC", "NEAR", "SUI", "HYPE",
                "ONDO", "ZEC", "INJ", "TON", "PAXG",
                "EDGE",
            }
            common_pairs = {f"{base}-{quote_asset}" for base in common_bases}
            cls.markets = {connector_name: common_pairs}
        else:
            # Live trading: only pass quote asset (connector discovers pairs dynamically)
            cls.markets = {connector_name: {quote_asset}}


def create_strategy(connectors: Dict[str, ConnectorBase]) -> OKXSpotGridStrategy:
    """
    Factory function called by Hummingbot.

    Args:
        connectors: Dict of initialized connectors

    Returns:
        OKXSpotGridStrategy instance

    Usage:
        start --script spot_grid_okx.py
    """
    config = OKXSpotGridStrategyConfig()
    return OKXSpotGridStrategy(connectors, config)


# Make sure function is named 'create' for compatibility
create = create_strategy
