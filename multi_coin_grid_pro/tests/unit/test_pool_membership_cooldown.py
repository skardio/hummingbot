"""
ST-03: Tests for pool membership cooldown (anti-churn).

Verifies that coins stay in the monitored pool for at least
pool_membership_cooldown_seconds before being rotated out,
preventing rapid in/out flipping (e.g. ICNT-USD 29× in 10h).
"""
import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    from controllers.multi_coin_grid_config import MultiCoinGridConfig
    from controllers.multi_coin_grid_controller import MultiCoinGridController


# ── helpers ──────────────────────────────────────────────────────────────

def _make_controller(cooldown: int = 1800, max_coins: int = 3):
    """Create a minimal controller for pool tests."""
    config = MultiCoinGridConfig(
        connector_name="kraken",
        quote_asset="EUR",
        max_coins_to_monitor=max_coins,
        min_24h_volume_eur=Decimal("1000"),
        coin_rotation_threshold=5,
        pool_membership_cooldown_seconds=cooldown,
        blacklist=[],
    )

    mock_connector = AsyncMock()
    mock_connector.name = "kraken"

    with patch(
        'multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'
    ), patch(
        'multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'
    ):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=MagicMock(),
            actions_queue=MagicMock(),
            connectors={"kraken": mock_connector},
            update_interval=1.0,
        )

    controller.coin_discovery = MagicMock()
    controller.trend_calculator = MagicMock()
    controller.trend_calculator.load_historical_data = AsyncMock()
    controller.all_available_pairs = [
        "XRP-EUR", "ADA-EUR", "SOL-EUR", "BTC-EUR", "DOGE-EUR",
    ]
    controller.pair_volumes = {
        "XRP-EUR": 5000.0,
        "ADA-EUR": 3000.0,
        "SOL-EUR": 4000.0,
        "BTC-EUR": 10000.0,
        "DOGE-EUR": 2000.0,
    }
    controller.pair_spreads = {
        "XRP-EUR": 0.001,
        "ADA-EUR": 0.002,
        "SOL-EUR": 0.0015,
        "BTC-EUR": 0.001,
        "DOGE-EUR": 0.003,
    }
    controller.coin_performance = {}
    controller.auto_blacklisted_coins = set()
    return controller


# ── _update_monitored_coins_from_pool tests ──────────────────────────────

class TestPoolMembershipCooldownRefresh:
    """Test cooldown logic in _update_monitored_coins_from_pool."""

    @pytest.mark.asyncio
    async def test_cooldown_keeps_coin_that_fell_out_of_topn(self):
        """A coin within cooldown must NOT be removed from the pool."""
        ctrl = _make_controller(cooldown=1800, max_coins=2)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR"]
        # XRP joined 600s ago (< 1800 cooldown)
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "XRP-EUR": now - 600,
        }
        # Volume changed: SOL now outranks XRP
        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "XRP-EUR": 1500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "XRP-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # XRP should still be in pool (cooldown protects it)
        assert "XRP-EUR" in ctrl.monitored_coins
        # SOL should also be added (max_coins=2, but cooldown kept XRP → 3 total)
        assert "BTC-EUR" in ctrl.monitored_coins

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_removal(self):
        """After cooldown expires, coin can be removed normally."""
        ctrl = _make_controller(cooldown=1800, max_coins=2)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR"]
        now = time.time()
        # XRP joined 2000s ago (> 1800 cooldown)
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "XRP-EUR": now - 2000,
        }
        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "XRP-EUR": 1500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "XRP-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # XRP should be gone (cooldown expired, volume too low for top-2)
        assert "XRP-EUR" not in ctrl.monitored_coins
        assert "SOL-EUR" in ctrl.monitored_coins
        assert "BTC-EUR" in ctrl.monitored_coins

    @pytest.mark.asyncio
    async def test_join_time_set_for_new_coins(self):
        """Newly added coins get a join timestamp."""
        ctrl = _make_controller(cooldown=1800, max_coins=3)
        ctrl.monitored_coins = ["BTC-EUR"]
        ctrl._pool_join_time = {"BTC-EUR": time.time() - 5000}

        volumes = {
            "BTC-EUR": 10000, "XRP-EUR": 5000,
            "SOL-EUR": 4000,
        }
        spreads = {
            "BTC-EUR": 0.001, "XRP-EUR": 0.001,
            "SOL-EUR": 0.001,
        }

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # XRP and SOL should have join times set
        assert "XRP-EUR" in ctrl._pool_join_time
        assert "SOL-EUR" in ctrl._pool_join_time
        assert ctrl._pool_join_time["XRP-EUR"] > 0
        assert ctrl._pool_join_time["SOL-EUR"] > 0

    @pytest.mark.asyncio
    async def test_removed_coins_cleaned_from_join_times(self):
        """Coins removed from pool should have their join time cleaned up."""
        ctrl = _make_controller(cooldown=1800, max_coins=2)
        now = time.time()
        ctrl.monitored_coins = ["BTC-EUR", "DOGE-EUR"]
        # DOGE cooldown expired
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "DOGE-EUR": now - 3600,
        }
        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "DOGE-EUR": 500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "DOGE-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # DOGE removed → join time cleaned
        assert "DOGE-EUR" not in ctrl._pool_join_time

    @pytest.mark.asyncio
    async def test_cooldown_zero_disables_protection(self):
        """cooldown=0 should not protect any coin from removal."""
        ctrl = _make_controller(cooldown=0, max_coins=2)
        now = time.time()
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR"]
        ctrl._pool_join_time = {
            "BTC-EUR": now - 10,
            "XRP-EUR": now - 10,  # Very recent
        }
        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "XRP-EUR": 1500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "XRP-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # XRP should be removed despite recent join (cooldown=0)
        assert "XRP-EUR" not in ctrl.monitored_coins

    @pytest.mark.asyncio
    async def test_active_coins_always_kept(self):
        """Active coins (with executor) are kept regardless of cooldown."""
        ctrl = _make_controller(cooldown=1800, max_coins=2)
        now = time.time()
        ctrl.monitored_coins = ["BTC-EUR", "DOGE-EUR"]
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "DOGE-EUR": now - 3600,
        }
        # DOGE has active executor
        mock_exec = MagicMock()
        mock_exec.trading_pair = "DOGE-EUR"
        ctrl.executors_info = [mock_exec]

        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "DOGE-EUR": 500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "DOGE-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # DOGE kept because active executor
        assert "DOGE-EUR" in ctrl.monitored_coins

    @pytest.mark.asyncio
    async def test_seed_join_times_on_first_run(self):
        """On first run, all monitored coins should get join times."""
        ctrl = _make_controller(cooldown=1800, max_coins=3)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR", "SOL-EUR"]
        ctrl._pool_join_time = {}  # Empty — first run

        volumes = {"BTC-EUR": 10000, "XRP-EUR": 5000, "SOL-EUR": 4000}
        spreads = {"BTC-EUR": 0.001, "XRP-EUR": 0.001, "SOL-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        # All coins should have join times
        for coin in ["BTC-EUR", "XRP-EUR", "SOL-EUR"]:
            assert coin in ctrl._pool_join_time


# ── _rotate_underperforming_coins tests ──────────────────────────────────

class TestPoolMembershipCooldownRotation:
    """Test cooldown logic in _rotate_underperforming_coins."""

    def test_cooldown_blocks_rotation(self):
        """Coin within cooldown cannot be rotated out even if underperforming."""
        ctrl = _make_controller(cooldown=1800, max_coins=3)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
        # XRP exceeded rotation threshold
        ctrl.coin_performance = {"BTC-EUR": 0, "XRP-EUR": 10, "ADA-EUR": 0}
        ctrl.rotation_threshold = 5
        # But XRP joined recently
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "XRP-EUR": now - 600,  # < 1800 cooldown
            "ADA-EUR": now - 3600,
        }

        ctrl._rotate_underperforming_coins()

        # XRP should NOT be rotated (cooldown active)
        assert "XRP-EUR" in ctrl.monitored_coins

    def test_cooldown_expired_allows_rotation(self):
        """After cooldown, underperforming coin can be rotated."""
        ctrl = _make_controller(cooldown=1800, max_coins=3)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
        ctrl.coin_performance = {"BTC-EUR": 0, "XRP-EUR": 10, "ADA-EUR": 0}
        ctrl.rotation_threshold = 5
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "XRP-EUR": now - 2000,  # > 1800 cooldown
            "ADA-EUR": now - 3600,
        }

        ctrl._rotate_underperforming_coins()

        # XRP should be rotated (cooldown expired + underperforming)
        assert "XRP-EUR" not in ctrl.monitored_coins

    def test_rotated_in_coin_gets_join_time(self):
        """Newly rotated-in coin should get a pool join time."""
        ctrl = _make_controller(cooldown=1800, max_coins=3)
        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
        ctrl.coin_performance = {"BTC-EUR": 0, "XRP-EUR": 10, "ADA-EUR": 0}
        ctrl.rotation_threshold = 5
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 3600,
            "XRP-EUR": now - 3600,
            "ADA-EUR": now - 3600,
        }

        ctrl._rotate_underperforming_coins()

        # New coin (SOL or DOGE) should have join time
        new_coins = set(ctrl.monitored_coins) - {"BTC-EUR", "ADA-EUR"}
        assert len(new_coins) == 1
        new_coin = new_coins.pop()
        assert new_coin in ctrl._pool_join_time
        # Old coin should be cleaned up
        assert "XRP-EUR" not in ctrl._pool_join_time


# ── Config field test ────────────────────────────────────────────────────

class TestPoolMembershipCooldownConfig:
    """Test that config field works correctly."""

    def test_config_default(self):
        """Default cooldown is 1800 seconds."""
        config = MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
        )
        assert config.pool_membership_cooldown_seconds == 1800

    def test_config_custom_value(self):
        """Custom cooldown value is accepted."""
        config = MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            pool_membership_cooldown_seconds=3600,
        )
        assert config.pool_membership_cooldown_seconds == 3600

    def test_config_zero_disables(self):
        """Cooldown of 0 is valid (disables protection)."""
        config = MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            pool_membership_cooldown_seconds=0,
        )
        assert config.pool_membership_cooldown_seconds == 0
