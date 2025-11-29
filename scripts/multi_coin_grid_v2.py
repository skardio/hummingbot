"""
Multi-Coin Grid Trading Strategy V2

Entry point script for running the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

from pathlib import Path
from typing import Dict, List

from hummingbot.connector.connector_base import ConnectorBase

# Import from symlinked modules in hummingbot package
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


class MultiCoinGridStrategyConfig(StrategyV2ConfigBase):
    """
    Minimal config for Strategy V2
    Controller handles all trading logic
    """
    # Empty config - markets defined at class level below
    markets: Dict = {}
    candles_config: List = []


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

    # Class variable - used by Hummingbot to initialize connectors BEFORE strategy __init__
    # Format: {"exchange_name": {"trading_pair1", "trading_pair2"}}
    # We use a dummy pair just to initialize the Kraken connector
    # Note: This will be overridden by init_markets() if paper trading is enabled
    markets = {"kraken": {"BTC-EUR"}}

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

        # Load controller config from YAML (validation only - controller loads it separately)
        # Note: ConfigManager handles the actual loading in initialize_controllers()
        try:
            import yaml
            config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / "multi_coin_grid.yml"
            if config_path.exists():
                with open(config_path) as f:
                    yaml.safe_load(f)  # Config loaded but not stored - controller loads it separately
        except Exception:
            # Config loading will be handled by ConfigManager in initialize_controllers()
            pass

        self.logger().info("=" * 70)
        self.logger().info("  MULTI-COIN GRID STRATEGY V2.0 INITIALIZED")
        self.logger().info("=" * 70)

    def initialize_controllers(self):
        """
        Initialize controllers - called by StrategyV2Base
        """
        try:
            # Use ConfigManager to load environment-specific config
            from multi_coin_grid_pro.config.config_manager import ConfigManager

            self.logger().info("🔧 Loading controller config...")

            # Load config using ConfigManager (supports dev/test/prod)
            config_manager = ConfigManager()
            env = config_manager.get_environment()
            config_data = config_manager.load_config('multi_coin_grid', env)

            config_path = config_manager.get_config_path('multi_coin_grid')
            self.logger().info(f"📁 Config path: {config_path}")
            self.logger().info(f"🌍 Environment: {env}")

            self.logger().info("📝 Creating controller config...")

            # Check if paper trading is enabled
            paper_trading = config_data.get('paper_trading', False)
            connector_name = config_data.get('connector_name', 'kraken')

            # CRITICAL: For paper trading, adjust connector name BEFORE creating config
            # Hummingbot will create the paper trade connector automatically if kraken is in paper_trade_exchanges
            if paper_trading:
                # Use paper trade connector name - Hummingbot will create it if configured
                paper_connector_name = f"{connector_name}_paper_trade"
                connector_name = paper_connector_name
                self.logger().info("=" * 80)
                self.logger().info("📝 PAPER TRADING MODE ENABLED - No real money will be used!")
                self.logger().info(f"   Using connector: {connector_name}")
                self.logger().info("=" * 80)
                self.logger().info("💡 Note: Make sure 'kraken' is in paper_trade_exchanges in Hummingbot config")
            else:
                self.logger().info("=" * 80)
                self.logger().info("💰 LIVE TRADING MODE - Real money will be used!")
                self.logger().info(f"   Connector: {connector_name}")
                self.logger().info("=" * 80)

            # CRITICAL: Update config_data with adjusted connector name BEFORE creating config
            config_data['connector_name'] = connector_name
            config_data['paper_trading'] = paper_trading  # Store actual paper trading status

            # Create controller config
            controller_config = MultiCoinGridConfig(
                controller_name="multi_coin_grid",
                **config_data
            )

            self.logger().info("🚀 Creating controller instance...")
            self.logger().info(f"DEBUG: self.controllers = {type(self.controllers)}")
            self.logger().info(f"DEBUG: market_data_provider = {type(self.market_data_provider)}")
            self.logger().info(f"DEBUG: actions_queue = {type(self.actions_queue)}")
            self.logger().info(f"DEBUG: self.connectors = {self.connectors}")
            self.logger().info(f"DEBUG: self.connectors keys = {list(self.connectors.keys()) if self.connectors else 'None'}")

            # Add controller to strategy
            controller = MultiCoinGridController(
                config=controller_config,
                market_data_provider=self.market_data_provider,
                actions_queue=self.actions_queue,
                connectors=self.connectors,  # Pass connectors dict from strategy
                update_interval=10.0  # Update every 10 seconds
            )

            self.logger().info(f"DEBUG: Controller object created: {type(controller)}")
            self.logger().info(f"DEBUG: Controller has __init__: {hasattr(controller, '__init__')}")
            self.logger().info(f"DEBUG: Controller class: {controller.__class__.__name__}")
            self.logger().info(f"DEBUG: Controller module: {controller.__class__.__module__}")
            self.controllers["multi_coin_grid"] = controller
            self.logger().info(f"DEBUG: Controller added to dict, count = {len(self.controllers)}")
            self.logger().info(f"DEBUG: Controllers in dict: {list(self.controllers.keys())}")

            # Try to access controller's config
            try:
                self.logger().info(f"DEBUG: Controller config: {controller.config.connector_name}")
            except Exception as e:
                self.logger().error(f"DEBUG: Failed to access controller.config: {e}")

            mode_str = "📝 PAPER TRADING" if paper_trading else "💰 LIVE TRADING"
            self.logger().info(f"✅ Controller initialized: {controller_config.connector_name} ({mode_str})")
            self.logger().info(f"💰 Capital: €{controller_config.total_amount_quote}")
            self.logger().info(f"⚠️  Stop Loss: {controller_config.stop_loss_pct * 100}%")
        except Exception as e:
            self.logger().error(f"❌ Failed to initialize controller: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    @classmethod
    def init_markets(cls, config: MultiCoinGridConfig = None):
        """
        Initialize markets for the strategy

        This is called by Hummingbot to determine which markets to connect to.
        """
        if config is None:
            # Use ConfigManager to load environment-specific config
            connector_name = "kraken"
            quote_asset = "EUR"
            paper_trading = False

            try:
                from multi_coin_grid_pro.config.config_manager import ConfigManager
                config_manager = ConfigManager()
                env = config_manager.get_environment()
                yaml_config = config_manager.load_config('multi_coin_grid', env)
                connector_name = yaml_config.get('connector_name', 'kraken')
                quote_asset = yaml_config.get('quote_asset', 'EUR')
                paper_trading = yaml_config.get('paper_trading', False)
            except Exception as e:
                # Use defaults if config loading fails
                import logging
                logging.getLogger(__name__).warning(f"Failed to load config in init_markets: {e}")

            # CRITICAL: For paper trading, adjust connector name BEFORE setting markets
            # Hummingbot needs to know which connector to initialize
            # IMPORTANT: Paper trading connector must be created by Hummingbot's connector manager
            # The connector name should end with '_paper_trade' for Hummingbot to recognize it
            if paper_trading:
                # Use paper trade connector name
                paper_connector_name = f"{connector_name}_paper_trade"
                cls.markets = {paper_connector_name: {quote_asset}}
                # Log warning if paper trading is enabled but connector might not be configured
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"📝 PAPER TRADING MODE: Using connector '{paper_connector_name}'\n"
                    f"   Make sure '{connector_name}' is in paper_trade_exchanges in Hummingbot config!\n"
                    f"   If connector is not found, bot will fall back to LIVE trading!"
                )
            else:
                cls.markets = {connector_name: {quote_asset}}
        else:
            cls.markets = {config.connector_name: {config.quote_asset}}

    def start(self, clock, timestamp):
        """Override start to add logging"""
        self.logger().info(f"🚀 Strategy.start() called - {len(self.controllers)} controllers to start")

        # Check controller status before starting
        for name, controller in self.controllers.items():
            self.logger().info(f"DEBUG: Controller '{name}' status BEFORE start: {controller.status}")

        super().start(clock, timestamp)

        # Check controller status after starting
        for name, controller in self.controllers.items():
            self.logger().info(f"DEBUG: Controller '{name}' status AFTER start: {controller.status}")

        self.logger().info("✅ Strategy.start() completed - controllers should be running")

    def on_tick(self):
        """
        Called on every tick (regular interval)

        The actual trading logic is handled by the controller.
        """
        super().on_tick()  # Controller handles all trading logic

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

        # Get controller status
        for controller in self.controllers.values():
            if isinstance(controller, MultiCoinGridController):
                lines.extend(controller.to_format_status())

        # Add executor status
        if self.executor_orchestrator:
            # Get executor report from orchestrator
            try:
                executors_report = self.executor_orchestrator.get_executors_report()
                active_executors = []

                # Flatten all executors from all controllers
                for controller_id, executor_list in executors_report.items():
                    active_executors.extend([e for e in executor_list if e.is_active])

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
            except Exception:
                # If there's an error getting executor info, just skip it
                # The controller status above is more important
                pass

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
