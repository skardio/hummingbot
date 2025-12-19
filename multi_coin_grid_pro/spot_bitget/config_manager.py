"""
Configuration manager for Bitget SPOT grid strategy.
Handles loading/saving YAML configs with environment support (dev/test/prod).
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from multi_coin_grid_pro.config.config_manager import ConfigManager as BaseConfigManager


class SpotGridBitgetConfigManager(BaseConfigManager):
    """
    Config manager for Bitget SPOT grid.
    Inherits from base ConfigManager with Bitget-specific paths.
    """

    def __init__(self):
        super().__init__()
        # Override config directory for Bitget spot
        self.config_dir = Path(__file__).parent / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def get_default_config_name(self) -> str:
        """Default config name for Bitget spot"""
        return "spot_grid_bitget"

    def get_config_path(self, config_name: str = "spot_grid_bitget", environment: Optional[str] = None) -> Path:
        """
        Get path to config file.

        Args:
            config_name: Base name of config
            environment: Environment (dev/test/prod) - defaults to prod

        Returns:
            Path to config file
        """
        if environment is None:
            environment = self.get_environment()

        # Try environment-specific config first
        if environment:
            env_config = self.config_dir / f"{config_name}.{environment}.yaml"
            if env_config.exists():
                return env_config

        # Fallback to base config
        base_config = self.config_dir / f"{config_name}.yaml"
        if base_config.exists():
            return base_config

        # If nothing exists, return the default path
        return self.config_dir / f"{config_name}.yaml"

    def load_config(self, config_name: str = "spot_grid_bitget", environment: Optional[str] = None) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Args:
            config_name: Name of config to load
            environment: Environment (dev/test/prod)

        Returns:
            Dict with configuration
        """
        config_path = self.get_config_path(config_name, environment)

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        return config or {}

    def save_config(self, config: Dict[str, Any], config_name: str = "spot_grid_bitget",
                    environment: Optional[str] = None) -> Path:
        """
        Save configuration to YAML file.

        Args:
            config: Configuration dict
            config_name: Name for config file
            environment: Environment (dev/test/prod)

        Returns:
            Path where config was saved
        """
        config_path = self.get_config_path(config_name, environment)

        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        return config_path
