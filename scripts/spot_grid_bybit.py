"""
Bybit SPOT Multi-Coin Grid Strategy

Production-ready grid strategy for Bybit SPOT with USDT pairs.
MiCA-compliant via Bybit.eu (Netherlands registration).
Uses the same architecture as Kraken, Bitget and OKX spot grid bots.

Usage:
    start --script spot_grid_bybit.py

Configuration:
    multi_coin_grid_pro/spot_bybit/config/spot_grid_bybit.yaml
"""

import os
from pathlib import Path
from typing import Dict, Set

from hummingbot.connector.connector_base import ConnectorBase
from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import (
    MultiCoinGridStrategyConfig as _MultiCoinGridStrategyConfig,
    MultiCoinGridStrategyV2 as _BaseStrategyV2,
)
from multi_coin_grid_pro.spot_bybit.config_manager import SpotGridBybitConfigManager
from multi_coin_grid_pro.spot_bybit.config_schema import SpotGridBybitConfig
from multi_coin_grid_pro.spot_bybit.controller import SpotGridBybitController
from multi_coin_grid_pro.utils.log_archiver import archive_bot_logs


class BybitSpotGridStrategyConfig(_MultiCoinGridStrategyConfig):
    """
    Config wrapper for Bybit SPOT strategy.
    """
    script_file_name: str = os.path.basename(__file__)


class BybitSpotGridStrategy(_BaseStrategyV2):
    """
    Bybit SPOT Grid Strategy

    Same proven controller architecture as Kraken, Bitget and OKX bots, adapted for Bybit:
    - Multi-coin grid trading
    - Trend-following entry
    - Dynamic grid sizing
    - Risk management
    - Stop loss / take profit

    Key differences from OKX:
    - Connector: bybit (spot)
    - Fees: 0.10% maker / 0.10% taker (standard) — same RT cost as Bitget
    - LIMIT_MAKER: Supported (unlike Bitget)
    - MiCA: Registered in Netherlands via bybit.eu
    - Auth: API Key + Secret only (no passphrase unlike OKX/Bitget)
    - Rate limit: 20 orders/sec SPOT
    """

    CONFIG_NAME: str = "spot_grid_bybit"
    CONFIG_MANAGER_CLASS = SpotGridBybitConfigManager
    CONTROLLER_CLASS = SpotGridBybitController
    CONTROLLER_CONFIG_CLASS = SpotGridBybitConfig
    CONFIG_FALLBACK_DIR = Path(__file__).parent.parent / "multi_coin_grid_pro" / "spot_bybit" / "config"
    CONFIG_FALLBACK_EXT = ".yaml"

    def __init__(self, connectors: Dict[str, ConnectorBase], config=None):
        # Archive old Bybit logs before this run starts
        try:
            archive_bot_logs("bybit")
        except Exception:
            pass  # Never block startup due to log archiving
        super().__init__(connectors, config)

    # Markets are set dynamically; define sensible defaults for initialization
    markets: Dict[str, Set[str]] = {
        "bybit": {
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT",
        }
    }

    @classmethod
    def init_markets(cls, config: SpotGridBybitConfig = None):
        """
        Initialize markets — ensure bybit connector is included with trading pairs.

        Called by Hummingbot to determine which connectors to initialize.
        """
        connector_name = "bybit"
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
            connector_name = config.connector_name
            quote_asset = config.quote_asset

        # For paper trading: pass common trading pairs so order books are initialized
        if paper_trading:
            common_usdt_pairs = {
                "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT",
                "DOT-USDT", "AVAX-USDT", "LINK-USDT", "UNI-USDT", "DOGE-USDT",
                "LTC-USDT", "ATOM-USDT", "NEAR-USDT", "APT-USDT", "SUI-USDT",
                "OP-USDT", "ARB-USDT", "TAO-USDT", "BONK-USDT", "WIF-USDT",
            }
            cls.markets = {connector_name: common_usdt_pairs}
        else:
            # Live trading: only pass quote asset (connector discovers pairs dynamically)
            cls.markets = {connector_name: {quote_asset}}


def create_strategy(connectors: Dict[str, ConnectorBase]) -> BybitSpotGridStrategy:
    """
    Factory function called by Hummingbot.

    Args:
        connectors: Dict of initialized connectors

    Returns:
        BybitSpotGridStrategy instance

    Usage:
        start --script spot_grid_bybit.py
    """
    config = BybitSpotGridStrategyConfig()
    return BybitSpotGridStrategy(connectors, config)


# Make sure function is named 'create' for compatibility
create = create_strategy
