"""
Multi-Coin Grid Trading Strategy V2 - USD Variant

USD version of the multi-coin grid strategy.
Start with: start --script multi_coin_grid_v2_usd.py

ISOLATION:
- Config: spot_grid_kraken_usd.yaml
- Cooldowns: data/cooldowns_usd.db
- Quote: USD (not EUR!)
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from hummingbot.connector.connector_base import ConnectorBase

# Import from symlinked modules in hummingbot package
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from multi_coin_grid_pro.utils.log_archiver import archive_bot_logs


def expand_env_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively expand environment variables in config dict.
    Supports ${VAR_NAME} and $VAR_NAME syntax.
    """
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    elif isinstance(config, str):
        def replace_env(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))
        return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)', replace_env, config)
    else:
        return config


class MultiCoinGridStrategyConfig(StrategyV2ConfigBase):
    """
    Minimal config for Strategy V2 - USD Variant
    Controller handles all trading logic
    """
    markets: Dict = {}
    candles_config: List = []


class MultiCoinGridStrategyV2USD(StrategyV2Base):
    """
    Multi-Coin Grid Trading Strategy V2 - USD Variant

    This is an INDEPENDENT instance from the EUR bot:
    - Separate config file (spot_grid_kraken_usd.yaml)
    - Separate cooldowns database (data/cooldowns_usd.db)
    - No shared executors or state

    Start with: start --script multi_coin_grid_v2_usd.py
    """

    # ST-06b: Write executors to DB immediately on close (crash-safe).
    # Buffer=0 means every closed executor is persisted within one tick.
    # Framework default=100; set to 0 so crash never loses executor records.
    closed_executors_buffer: int = 0

    # ============ CRITICAL: USD CONFIG ============
    CONFIG_NAME = "spot_grid_kraken_usd"  # USD config!
    # ==============================================

    # Class variable - used by Hummingbot to initialize connectors BEFORE strategy __init__
    # Format: {"exchange_name": {"trading_pair1", "trading_pair2"}}
    markets = {}

    @classmethod
    def _load_markets_from_config(cls) -> Dict[str, set]:
        """Load initial markets for WebSocket subscription - USD pairs"""
        import yaml

        # Default USD seed pairs
        default_pairs = {
            "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD",
            "DOGE-USD", "LINK-USD", "DOT-USD", "AVAX-USD", "SUI-USD"
        }

        config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / f"{cls.CONFIG_NAME}.yaml"

        if not config_path.exists():
            return {"kraken": default_pairs}

        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            connector_name = config.get('connector_name', 'kraken')
            paper_trading = config.get('paper_trading', False)
            if paper_trading:
                connector_name = f"{connector_name}_paper_trade"

            # Try manual pairs first
            manual_pairs = config.get('manual_trading_pairs', [])
            if manual_pairs:
                return {connector_name: set(manual_pairs)}

            # Use default USD pairs
            return {connector_name: default_pairs}

        except Exception:
            return {"kraken": default_pairs}

    def __init__(self, connectors: Dict[str, ConnectorBase]):
        super().__init__(connectors, MultiCoinGridStrategyConfig())

        # Archive old logs from the previous run before writing new ones
        try:
            archive_bot_logs("kraken_usd")
        except Exception:
            pass  # Never block startup due to log archiving

        # Pre-load config for info display only
        try:
            config_data = self._load_config()
            config_data = expand_env_vars(config_data)

            quote_asset = config_data.get('quote_asset', 'UNKNOWN')
            instance_id = config_data.get('instance_id', 'unknown')

            if quote_asset != 'USD':
                self.logger().warning(f"⚠️  WARNING: Expected USD config but got quote_asset={quote_asset}")

            self.logger().info("=" * 70)
            self.logger().info("  MULTI-COIN GRID STRATEGY V2 - USD VARIANT")
            self.logger().info(f"  Config: {self.CONFIG_NAME}")
            self.logger().info(f"  Quote: {quote_asset}")
            self.logger().info(f"  Instance ID: {instance_id}")
            self.logger().info("=" * 70)
        except Exception as e:
            self.logger().warning(f"Could not pre-load config: {e}")

    def initialize_controllers(self):
        """
        Initialize controllers - called by StrategyV2Base
        Uses market_data_provider and actions_queue from base class
        """
        try:
            # Use ConfigManager to load environment-specific config
            from multi_coin_grid_pro.config.config_manager import ConfigManager

            self.logger().info("🔧 Loading USD controller config...")

            # Load config using ConfigManager
            config_manager = ConfigManager()
            config_data = config_manager.load_config(self.CONFIG_NAME)

            # Expand environment variables in config
            config_data = expand_env_vars(config_data)

            config_path = config_manager.get_config_path(self.CONFIG_NAME)
            self.logger().info(f"📁 Config path: {config_path}")

            self.logger().info("📝 Creating USD controller config...")

            # Check if paper trading is enabled
            paper_trading = config_data.get('paper_trading', False)
            connector_name = config_data.get('connector_name', 'kraken')

            # CRITICAL: For paper trading, adjust connector name BEFORE creating config
            if paper_trading:
                paper_connector_name = f"{connector_name}_paper_trade"
                connector_name = paper_connector_name
                self.logger().info("=" * 80)
                self.logger().info("📝 PAPER TRADING MODE ENABLED - No real money will be used!")
                self.logger().info(f"   Using connector: {connector_name}")
                self.logger().info("=" * 80)
            else:
                self.logger().info("=" * 80)
                self.logger().info("💰 LIVE TRADING MODE - Real money will be used!")
                self.logger().info(f"   Connector: {connector_name}")
                self.logger().info("=" * 80)

            # Update config_data with adjusted connector name
            config_data['connector_name'] = connector_name
            config_data['paper_trading'] = paper_trading

            # Create controller config
            controller_config = MultiCoinGridConfig(
                controller_name="multi_coin_grid_usd",
                **config_data
            )

            self.logger().info("🚀 Creating USD controller instance...")
            self.logger().info(f"DEBUG: self.controllers = {type(self.controllers)}")
            self.logger().info(f"DEBUG: market_data_provider = {type(self.market_data_provider)}")
            self.logger().info(f"DEBUG: actions_queue = {type(self.actions_queue)}")
            self.logger().info(f"DEBUG: self.connectors = {self.connectors}")
            self.logger().info(f"DEBUG: self.connectors keys = {list(self.connectors.keys()) if self.connectors else 'None'}")

            # Create controller with correct parameters (same as EUR version)
            controller = MultiCoinGridController(
                config=controller_config,
                market_data_provider=self.market_data_provider,
                actions_queue=self.actions_queue,
                connectors=self.connectors,  # Pass connectors dict from strategy
                update_interval=10.0  # Update every 10 seconds
            )

            self.logger().info(f"DEBUG: Controller object created: {type(controller)}")
            self.logger().info(f"DEBUG: Controller class: {controller.__class__.__name__}")
            self.controllers["multi_coin_grid_usd"] = controller
            self.logger().info(f"DEBUG: Controllers in dict: {list(self.controllers.keys())}")

            mode_str = "📝 PAPER TRADING" if paper_trading else "💰 LIVE TRADING"
            self.logger().info(f"✅ USD Controller initialized: {controller_config.connector_name} ({mode_str})")
            self.logger().info(f"💰 Capital: ${controller_config.total_amount_quote}")
            self.logger().info(f"📊 Max coins to monitor: {controller_config.max_coins_to_monitor}")

        except Exception as e:
            self.logger().error(f"❌ Failed to initialize USD controllers: {e}")
            import traceback
            self.logger().error(f"Traceback: {traceback.format_exc()}")
            raise

    def _load_config(self) -> Dict[str, Any]:
        """Load USD config from YAML"""
        import yaml

        # Try ConfigManager first
        try:
            from multi_coin_grid_pro.config.config_manager import ConfigManager
            config_manager = ConfigManager()
            return config_manager.load_config(self.CONFIG_NAME)
        except Exception:
            pass

        # Fallback to direct file load
        config_paths = [
            Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / f"{self.CONFIG_NAME}.yaml",
            Path(__file__).parent / "multi_coin_grid_pro" / "config" / f"{self.CONFIG_NAME}.yaml",
            Path("multi_coin_grid_pro") / "config" / f"{self.CONFIG_NAME}.yaml",
        ]

        for config_path in config_paths:
            if config_path.exists():
                with open(config_path) as f:
                    self.logger().info(f"✅ Loaded USD config from {config_path}")
                    return yaml.safe_load(f)

        raise FileNotFoundError(f"USD config not found: {self.CONFIG_NAME}.yaml")

    def create_actions_proposal(self) -> List:
        """
        Create action proposals - required by StrategyV2Base

        Returns empty list because actions come from controllers.
        """
        return []

    def stop_actions_proposal(self) -> List:
        """
        Stop action proposals - required by StrategyV2Base

        Returns empty list because actions come from controllers.
        """
        return []


# Initialize markets at module load time (required by Hummingbot)
MultiCoinGridStrategyV2USD.markets = MultiCoinGridStrategyV2USD._load_markets_from_config()
