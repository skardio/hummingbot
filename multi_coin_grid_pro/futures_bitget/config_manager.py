"""
Config manager dedicated to the Bitget futures grid setup.
"""

from pathlib import Path
from typing import Optional

from multi_coin_grid_pro.config.config_manager import ConfigManager


class FuturesGridConfigManager(ConfigManager):
    """
    Same behavior as the shared ConfigManager but scoped to the futures_grid_bitget config folder.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent / "config"
        super().__init__(config_dir=config_dir)

    def get_environment(self) -> str:
        """
        Allow overriding the environment used by the futures grid via BITGET_BOT_ENV without
        affecting the spot bot.
        """
        from os import getenv

        return getenv("BITGET_BOT_ENV", super().get_environment())
