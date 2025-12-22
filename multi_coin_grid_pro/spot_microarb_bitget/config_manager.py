"""
Config manager for Bitget Spot Micro-Arb.
Uses the shared BaseConfigManager to load YAML configs.
"""
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from multi_coin_grid_pro.config.config_manager import ConfigManager as BaseConfigManager


class MicroArbBitgetConfigManager(BaseConfigManager):
    def __init__(self):
        super().__init__()
        self.config_dir = Path(__file__).parent / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def get_default_config_name(self) -> str:
        return "spot_microarb_bitget"

    def get_config_path(self, config_name: str = "spot_microarb_bitget", environment: Optional[str] = None) -> Path:
        if environment is None:
            environment = self.get_environment()
        if environment:
            env_path = self.config_dir / f"{config_name}.{environment}.yaml"
            if env_path.exists():
                return env_path
        return self.config_dir / f"{config_name}.yaml"

    def load_config(self, config_name: str = "spot_microarb_bitget", environment: Optional[str] = None) -> Dict[str, Any]:
        path = self.get_config_path(config_name, environment)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
        return data

    def save_config(self, config: Dict[str, Any], config_name: str = "spot_microarb_bitget", environment: Optional[str] = None) -> Path:
        path = self.get_config_path(config_name, environment)
        with path.open("w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
        return path
