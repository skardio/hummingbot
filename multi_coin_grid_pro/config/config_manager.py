"""
Configuration Management

Handles environment-specific configs (dev/test/prod) with validation.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages configuration files for different environments

    Supports:
    - Environment-specific configs (dev/test/prod)
    - Validation on startup
    - No hardcoded values
    - Override via environment variables
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize config manager

        Args:
            config_dir: Directory containing config files (default: multi_coin_grid_pro/config)
        """
        if config_dir is None:
            config_dir = Path(__file__).parent

        self.config_dir = config_dir
        self.config_cache: Dict[str, Dict] = {}

    def get_environment(self) -> str:
        """
        Get current environment from env var

        Returns:
            Environment name (dev/test/prod), defaults to 'dev'
        """
        return os.getenv("BOT_ENV", "dev").lower()

    def load_config(
        self,
        config_name: str = "multi_coin_grid",
        environment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load configuration file

        Args:
            config_name: Base name of config file (without extension)
            environment: Environment name (dev/test/prod), defaults to current env

        Returns:
            Configuration dictionary
        """
        if environment is None:
            environment = self.get_environment()

        cache_key = f"{config_name}_{environment}"
        if cache_key in self.config_cache:
            return self.config_cache[cache_key]

        # Prefer config files that match the requested config_name before falling back to shared env configs
        specific_env_path = self.config_dir / f"{config_name}.{environment}.yaml"
        base_config_path = self.config_dir / f"{config_name}.yaml"
        env_config_path = self.config_dir / f"config.{environment}.yaml"

        if specific_env_path.exists():
            config_path = specific_env_path
        elif base_config_path.exists():
            config_path = base_config_path
        elif env_config_path.exists():
            config_path = env_config_path
        else:
            raise FileNotFoundError(
                f"Config file not found. Tried:\n"
                f"  - {specific_env_path}\n"
                f"  - {base_config_path}\n"
                f"  - {env_config_path}"
            )

        logger.info(f"Loading config from {config_path} (env: {environment})")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Override with environment variables
        config = self._apply_env_overrides(config)

        # Cache config
        self.config_cache[cache_key] = config

        return config

    def _apply_env_overrides(self, config: Dict) -> Dict:
        """
        Apply environment variable overrides to config

        Environment variables format: BOT_<SECTION>_<KEY>
        Example: BOT_RISK_STOP_LOSS_PCT=0.1

        Args:
            config: Configuration dictionary

        Returns:
            Updated configuration dictionary
        """
        for key, value in os.environ.items():
            if not key.startswith("BOT_"):
                continue

            # Parse BOT_<SECTION>_<KEY>
            parts = key[4:].split("_")  # Remove "BOT_" prefix
            if len(parts) < 2:
                continue

            section = parts[0].lower()
            config_key = "_".join(parts[1:]).lower()

            # Convert value to appropriate type
            if isinstance(value, str):
                # Try to convert to number
                try:
                    if '.' in value:
                        value = float(value)
                    else:
                        value = int(value)
                except ValueError:
                    # Keep as string
                    pass

            # Set nested config value
            if section in config:
                config[section][config_key] = value
                logger.debug(f"Override: {key} = {value}")

        return config

    def validate_config(self, config: Dict, config_class: type) -> bool:
        """
        Validate configuration against Pydantic model

        Args:
            config: Configuration dictionary
            config_class: Pydantic model class

        Returns:
            True if valid, raises ValidationError if not
        """
        try:
            config_class(**config)
            logger.info("✅ Configuration validated successfully")
            return True
        except ValidationError as e:
            logger.error(f"❌ Configuration validation failed: {e}")
            raise

    def get_config_path(self, config_name: str = "multi_coin_grid") -> Path:
        """
        Get path to config file for current environment

        Args:
            config_name: Base name of config file

        Returns:
            Path to config file
        """
        environment = self.get_environment()
        # Try config.{env}.yaml format first
        env_config_path = self.config_dir / f"config.{environment}.yaml"

        if env_config_path.exists():
            return env_config_path

        # Try config_name.{env}.yaml format
        alt_env_config_path = self.config_dir / f"{config_name}.{environment}.yaml"
        if alt_env_config_path.exists():
            return alt_env_config_path

        # Fallback to base config
        base_config_path = self.config_dir / f"{config_name}.yaml"
        if base_config_path.exists():
            return base_config_path

        # Fallback to .yml extension
        base_config_yml_path = self.config_dir / f"{config_name}.yml"
        if base_config_yml_path.exists():
            return base_config_yml_path

        # Return default path (will raise error if accessed)
        return base_config_path
