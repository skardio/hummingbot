"""
Multi-Coin Grid Trading Strategy V2

Entry point script for running the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

import os
from pathlib import Path
from typing import Dict, List, Set

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig

# Import from symlinked modules in hummingbot package
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


class MultiCoinGridStrategyConfig(StrategyV2ConfigBase):
    """
    Strategy V2 configuration for Multi-Coin Grid Bot
    """
    script_file_name: str = os.path.basename(__file__)
    candles_config: List[CandlesConfig] = []
    markets: Dict[str, Set[str]] = {}


class MultiCoinGridStrategyV2(StrategyV2Base):
    """
    Multi-Coin Grid Trading Strategy V2

    This strategy automatically:
    1. Discovers tradeable coins on the exchange
    2. Monitors their price trends
    3. Creates grid trading setups on the best trending coin
    4. Switches to different coins as trends change

    Built on Hummingbot's Strategy V2 architecture with:
    - GridExecutor for order management
    - Stop-loss protection
    - Event-driven async architecture
    - Automatic risk management
    """

    # Strategy configuration - markets will be set dynamically by controllers
    CONFIG_NAME: str = "spot_grid_kraken_eur"  # Kraken EUR spot grid config
    CONFIG_MANAGER_CLASS = None
    CONTROLLER_CLASS = MultiCoinGridController
    CONTROLLER_CONFIG_CLASS = MultiCoinGridConfig
    CONFIG_FALLBACK_DIR = Path(__file__).parent.parent / "config"
    CONFIG_FALLBACK_EXT = ".yml"
    markets: Dict[str, Set[str]] = {}

    @classmethod
    def _get_config_manager_instance(cls):
        manager_cls = getattr(cls, "CONFIG_MANAGER_CLASS", None)
        if manager_cls is not None:
            return manager_cls()
        from multi_coin_grid_pro.config.config_manager import ConfigManager
        return ConfigManager()

    @classmethod
    def _config_file_path(cls) -> Path:
        return cls.CONFIG_FALLBACK_DIR / f"{cls.CONFIG_NAME}{cls.CONFIG_FALLBACK_EXT}"

    @classmethod
    def _load_config_from_file(cls):
        import yaml

        config_path = cls._config_file_path()
        with open(config_path) as f:
            config_data = yaml.safe_load(f)
        return config_data, config_path

    def __init__(self, connectors: Dict[str, ConnectorBase], config: MultiCoinGridStrategyConfig = None):
        """
        Initialize the strategy

        Args:
            connectors: Dictionary of exchange connectors
            config: Strategy configuration (optional, will create default if None)
        """
        if config is None:
            config = MultiCoinGridStrategyConfig()
        super().__init__(connectors, config)
        self.config = config

        # Configure logging levels
        import logging

        # Reduce SQLAlchemy logging verbosity
        sqlalchemy_logger = logging.getLogger('sqlalchemy')
        sqlalchemy_logger.setLevel(logging.WARNING)
        sqlalchemy_engine_logger = logging.getLogger('sqlalchemy.engine')
        sqlalchemy_engine_logger.setLevel(logging.WARNING)

        # Configure strategy-specific loggers
        # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
        # Set to DEBUG for detailed debugging, INFO for normal operation
        # Priority: 1) Environment variable, 2) YAML config, 3) Default INFO
        strategy_log_level = os.getenv('MULTI_COIN_GRID_LOG_LEVEL', None)

        # Load YAML config to check for log_level setting
        try:
            config_manager = self._get_config_manager_instance()
            yaml_config = config_manager.load_config(self.CONFIG_NAME)
            if strategy_log_level is None and 'log_level' in yaml_config:
                strategy_log_level = str(yaml_config['log_level']).upper()
        except Exception:
            try:
                yaml_config, _ = self._load_config_from_file()
                if strategy_log_level is None and 'log_level' in yaml_config:
                    strategy_log_level = str(yaml_config['log_level']).upper()
            except Exception:
                pass  # Use default if YAML read fails

        if strategy_log_level is None:
            strategy_log_level = 'INFO'
        else:
            strategy_log_level = strategy_log_level.upper()

        # Set root logger level (affects all loggers)
        root_logger = logging.getLogger()
        if strategy_log_level == 'DEBUG':
            root_logger.setLevel(logging.DEBUG)
        elif strategy_log_level == 'INFO':
            root_logger.setLevel(logging.INFO)
        elif strategy_log_level == 'WARNING':
            root_logger.setLevel(logging.WARNING)
        else:
            root_logger.setLevel(logging.INFO)

        # Set specific loggers for multi-coin grid components
        multi_coin_logger = logging.getLogger('hummingbot.multi_coin_grid_controllers')
        multi_coin_logger.setLevel(getattr(logging, strategy_log_level, logging.INFO))

        multi_coin_utils_logger = logging.getLogger('hummingbot.multi_coin_grid_utils')
        multi_coin_utils_logger.setLevel(getattr(logging, strategy_log_level, logging.INFO))

        self.logger().info(f"✅ Logging configured - Level: {strategy_log_level}")
        self.logger().info("✅ SQLAlchemy logging set to WARNING level")

        # Load controller config using ConfigManager
        try:
            config_manager = self._get_config_manager_instance()
            config_data = config_manager.load_config(self.CONFIG_NAME)
            config_path = config_manager.get_config_path(self.CONFIG_NAME)
            self.logger().info(f"✅ Loaded config from {config_path}")
        except Exception as e:
            self.logger().warning(f"⚠️  ConfigManager failed, using fallback: {e}")
            config_data, config_path = self._load_config_from_file()
            self.logger().info(f"✅ Loaded config from {config_path} (fallback)")

        self.logger().info("=" * 70)
        self.logger().info("  MULTI-COIN GRID STRATEGY V2.0 INITIALIZED")
        self.logger().info("=" * 70)

    def initialize_controllers(self):
        """
        Initialize controllers - called by StrategyV2Base
        """
        # Load controller config using ConfigManager
        try:
            config_manager = self._get_config_manager_instance()
            config_data = config_manager.load_config(self.CONFIG_NAME)
            config_path = config_manager.get_config_path(self.CONFIG_NAME)
            self.logger().info(f"✅ Loaded controller config from {config_path}")
        except Exception as e:
            self.logger().warning(f"⚠️  ConfigManager failed, using fallback: {e}")
            config_data, config_path = self._load_config_from_file()
            self.logger().info(f"✅ Loaded controller config from {config_path} (fallback)")

        # Check if paper trading is enabled
        paper_trading = config_data.get('paper_trading', False)
        connector_name = config_data.get('connector_name', 'kraken')
        original_connector_name = connector_name

        # Adjust connector name for paper trading
        if paper_trading:
            if not connector_name.endswith('_paper_trade'):
                connector_name = f"{connector_name}_paper_trade"
                self.logger().info("=" * 80)
                self.logger().info("📝 PAPER TRADING MODE ENABLED - No real money will be used!")
                self.logger().info(f"   Connector adjusted: {original_connector_name} → {connector_name}")
                self.logger().info("=" * 80)
            else:
                self.logger().info("=" * 80)
                self.logger().info("📝 PAPER TRADING MODE ENABLED - No real money will be used!")
                self.logger().info(f"   Connector: {connector_name}")
                self.logger().info("=" * 80)
        else:
            self.logger().info("=" * 80)
            self.logger().info("💰 LIVE TRADING MODE - Real money will be used!")
            self.logger().info(f"   Connector: {connector_name}")
            self.logger().info("=" * 80)

        # Update config_data with adjusted connector name
        config_data['connector_name'] = connector_name

        # Ensure controller_name is present exactly once
        controller_name = config_data.get("controller_name", "multi_coin_grid")
        config_data["controller_name"] = controller_name

        # Log available connectors for debugging
        self.logger().info(
            f"🔍 Strategy connectors available: {
                list(
                    self.connectors.keys()) if self.connectors else 'NONE'}")
        self.logger().info(f"🔍 Strategy connectors dict type: {type(self.connectors)}, empty: {not self.connectors}")
        self.logger().info(f"🔍 Expected connector name: '{connector_name}'")

        if not self.connectors:
            self.logger().error("❌ WARNING: No connectors available in strategy! Make sure to connect the exchange first:")  # noqa: E501
            self.logger().error(f"   1. In Hummingbot CLI, run: connect {connector_name}")
            self.logger().error("   2. Enter your API keys when prompted")
            self.logger().error("   3. Verify with: list connectors")
            self.logger().error("   4. Then run: start --script futures_grid_bitget.py")
        elif connector_name not in self.connectors:
            self.logger().error(f"❌ WARNING: Connector '{connector_name}' not found in available connectors!")
            self.logger().error(f"   Available connectors: {list(self.connectors.keys())}")
            self.logger().error(f"   To fix: connect {connector_name} in Hummingbot CLI")

        controller_config = self.CONTROLLER_CONFIG_CLASS(**config_data)

        self.controllers[controller_name] = self.CONTROLLER_CLASS(
            config=controller_config,
            market_data_provider=self.market_data_provider,
            actions_queue=self.actions_queue,
            connectors=self.connectors,
            update_interval=10.0
        )

        mode_str = "📝 PAPER TRADING" if paper_trading else "💰 LIVE TRADING"
        self.logger().info(
            f"✅ Controller '{controller_name}' initialized: "
            f"{controller_config.connector_name} ({mode_str})"
        )
        self.logger().info(f"💰 Capital: €{controller_config.total_amount_quote}")
        if controller_config.stop_loss_pct is not None:
            self.logger().info(f"⚠️  Stop Loss: {controller_config.stop_loss_pct * 100}%")
        else:
            self.logger().info("⚠️  Stop Loss: DISABLED")

    @classmethod
    def init_markets(cls, config: MultiCoinGridConfig = None):
        """
        Initialize markets for the strategy

        This is called by Hummingbot to determine which markets to connect to.
        """
        # Try to load config to check for paper trading
        connector_name = "kraken"
        quote_asset = "EUR"
        paper_trading = False

        try:
            config_manager = cls._get_config_manager_instance()
            yaml_config = config_manager.load_config(cls.CONFIG_NAME)
            connector_name = yaml_config.get('connector_name', connector_name)
            quote_asset = yaml_config.get('quote_asset', quote_asset)
            paper_trading = yaml_config.get('paper_trading', paper_trading)
        except Exception:
            try:
                yaml_config, _ = cls._load_config_from_file()
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
        # This ensures paper trading connector has order books for coins we'll likely trade
        if paper_trading:
            # Common EUR trading pairs that are likely to be discovered
            common_eur_pairs = {
                "BTC-EUR", "ETH-EUR", "SOL-EUR", "XRP-EUR", "ADA-EUR",
                "DOT-EUR", "AVAX-EUR", "LINK-EUR", "MATIC-EUR", "UNI-EUR",
                "ATOM-EUR", "LTC-EUR", "BCH-EUR", "NEAR-EUR", "APT-EUR",
                "ARB-EUR", "OP-EUR", "SUI-EUR", "ALGO-EUR", "FIL-EUR",
                "FET-EUR", "BAT-EUR", "DASH-EUR", "STRK-EUR", "TNSR-EUR",
                "WLFI-EUR", "TRUST-EUR", "SAPIEN-EUR", "CCD-EUR", "GIGA-EUR"
            }
            cls.markets = {connector_name: common_eur_pairs}
            # Log for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"📝 Paper trading: Initializing {len(common_eur_pairs)} trading pairs for order books")
        else:
            # Live trading: only pass quote asset (connector will discover pairs dynamically)
            cls.markets = {connector_name: {quote_asset}}

    def on_tick(self):
        """
        Called on every tick (regular interval)

        The actual trading logic is handled by the controller.
        """
        super().on_tick()

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

    def format_status(self) -> str:
        """
        Format strategy status for display

        Returns:
            Formatted status string
        """
        lines = []

        # Debug: check if controllers exist
        self.logger().info(f"🔍 format_status called: {len(self.controllers)} controllers")

        # Get controller status
        for controller_id, controller in self.controllers.items():
            self.logger().info(f"🔍 Checking controller {controller_id}: type={type(controller).__name__}")
            # Check if controller has to_format_status method instead of isinstance check
            # (isinstance fails with symlinked imports in different module paths)
            if hasattr(controller, 'to_format_status') and callable(getattr(controller, 'to_format_status')):
                try:
                    status_lines = controller.to_format_status()
                    self.logger().info(f"✅ Got {len(status_lines)} status lines from controller")
                    lines.extend(status_lines)
                except Exception as e:
                    self.logger().error(f"❌ Error getting status from controller: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())
            else:
                self.logger().warning(f"⚠️  Controller {controller_id} has no to_format_status method")

        # Add executor status
        if self.executor_orchestrator:
            # Get all executors from all controllers
            executors_report = self.executor_orchestrator.get_executors_report()
            active_executors = []
            for controller_id, executors_list in executors_report.items():
                active_executors.extend([
                    e for e in executors_list
                    if e.is_active
                ])

            if active_executors:
                lines.append("\n╔═══════════════════════════════════════════════════════════════╗")
                lines.append("║                    ACTIVE EXECUTORS                           ║")
                lines.append("╠═══════════════════════════════════════════════════════════════╣")

                for executor in active_executors:
                    lines.append(
                        f"║ ID: {executor.id[:8]}... | "
                        f"Status: {executor.status.name:10} | "
                        f"P&L: {float(executor.net_pnl_pct) * 100:+.2f}%   ║"
                    )

                lines.append("╚═══════════════════════════════════════════════════════════════╝\n")

        return "\n".join(lines)


# For running directly via Hummingbot CLI
def create_strategy(connectors: Dict[str, ConnectorBase]) -> MultiCoinGridStrategyV2:
    """
    Factory function to create strategy instance

    This is called by Hummingbot's trading core when loading the strategy.

    Args:
        connectors: Dictionary of exchange connectors

    Returns:
        Strategy instance
    """
    config = MultiCoinGridStrategyConfig()
    return MultiCoinGridStrategyV2(connectors, config)
# Force reload: Sat Nov 15 20:43:00 CET 2025
