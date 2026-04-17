"""
ST-06b: Verify closed_executors_buffer override.

The framework default (100) means executors are never stored to DB
because the bot never accumulates that many. Setting to 5 ensures
DB writes happen after just 6 finished executors.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestClosedExecutorsBuffer:
    """Verify strategy classes override the framework default."""

    def test_eur_strategy_buffer(self):
        from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyV2
        assert MultiCoinGridStrategyV2.closed_executors_buffer == 5

    def test_usd_strategy_buffer(self):
        from multi_coin_grid_pro.scripts.multi_coin_grid_v2_usd import MultiCoinGridStrategyV2USD
        assert MultiCoinGridStrategyV2USD.closed_executors_buffer == 5

    def test_buffer_less_than_framework_default(self):
        from hummingbot.strategy.strategy_v2_base import StrategyV2Base
        from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyV2
        assert MultiCoinGridStrategyV2.closed_executors_buffer < StrategyV2Base.closed_executors_buffer
