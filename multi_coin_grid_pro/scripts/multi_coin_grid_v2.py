"""
Multi-Coin Grid Trading Strategy V2

Entry point script for running the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.data_feed.market_data_provider import MarketDataProvider

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
    markets: Dict[str, Set[str]] = {}

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

        # Reduce SQLAlchemy logging verbosity
        import logging
        sqlalchemy_logger = logging.getLogger('sqlalchemy')
        sqlalchemy_logger.setLevel(logging.WARNING)
        sqlalchemy_engine_logger = logging.getLogger('sqlalchemy.engine')
        sqlalchemy_engine_logger.setLevel(logging.WARNING)
        self.logger().info("✅ Set SQLAlchemy logging to WARNING level")

        # Load controller config from YAML
        import yaml
        config_path = Path(__file__).parent.parent / "conf" / "multi_coin_grid.yml"
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        self.logger().info("=" * 70)
        self.logger().info("  MULTI-COIN GRID STRATEGY V2.0 INITIALIZED")
        self.logger().info("=" * 70)

    def initialize_controllers(self):
        """
        Initialize controllers - called by StrategyV2Base
        """
        import yaml

        # Load controller config from YAML
        config_path = Path(__file__).parent.parent / "conf" / "multi_coin_grid.yml"
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        # Create controller config
        controller_config = MultiCoinGridConfig(
            controller_name="multi_coin_grid",
            **config_data
        )

        # Add controller to strategy
        self.controllers["multi_coin_grid"] = MultiCoinGridController(
            config=controller_config,
            market_data_provider=self.market_data_provider,
            actions_queue=self.actions_queue,
            connectors=self.connectors,  # Pass connectors dict from strategy
            update_interval=10.0  # Update every 10 seconds
        )

        self.logger().info(f"✅ Controller initialized: {controller_config.connector_name}")
        self.logger().info(f"💰 Capital: €{controller_config.total_amount_quote}")
        self.logger().info(f"⚠️  Stop Loss: {controller_config.stop_loss_pct * 100}%")

    @classmethod
    def init_markets(cls, config: MultiCoinGridConfig = None):
        """
        Initialize markets for the strategy

        This is called by Hummingbot to determine which markets to connect to.
        """
        if config is None:
            # Default config for market initialization
            cls.markets = {"kraken": {"EUR"}}
        else:
            cls.markets = {config.connector_name: {config.quote_asset}}

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

        # Get controller status
        for controller in self.controllers.values():
            if isinstance(controller, MultiCoinGridController):
                lines.extend(controller.to_format_status())

        # Add executor status
        if self.executor_orchestrator:
            active_executors = [
                e for e in self.executor_orchestrator.executors_info
                if e.is_active
            ]

            if active_executors:
                lines.append("\n╔═══════════════════════════════════════════════════════════════╗")
                lines.append("║                    ACTIVE EXECUTORS                           ║")
                lines.append("╠═══════════════════════════════════════════════════════════════╣")

                for executor in active_executors:
                    lines.append(
                        f"║ ID: {executor.id[:8]}... | "
                        f"Status: {executor.status.name:10} | "
                        f"P&L: {executor.net_pnl_pct * 100:+.2f}%   ║"
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
