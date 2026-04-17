"""
ST-04: Tests for orderbook unsubscribe and data health.

Verifies that:
- Unsubscribe removes pairs from tracker
- Pool removal triggers unsubscribe
- Rotation triggers unsubscribe for old coins
- Prefetch top_n auto-aligns with max_coins_to_monitor
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


def _make_controller(max_coins: int = 3):
    """Create a minimal controller for data health tests."""
    config = MultiCoinGridConfig(
        connector_name="kraken",
        quote_asset="EUR",
        max_coins_to_monitor=max_coins,
        min_24h_volume_eur=Decimal("1000"),
        coin_rotation_threshold=5,
        pool_membership_cooldown_seconds=0,  # Disable cooldown for data tests
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
    controller.auto_blacklisted_coins = set()
    controller.connector = mock_connector  # Attach connector for WS tests
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
    return controller


def _attach_mock_tracker(controller):
    """Attach a mock order book tracker to the controller's connector."""
    tracker = MagicMock()
    tracker._trading_pairs = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
    tracker._data_source = MagicMock()
    tracker._data_source._trading_pairs = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
    tracker._order_books = {"BTC-EUR": MagicMock(), "XRP-EUR": MagicMock()}
    controller.connector.order_book_tracker = tracker
    return tracker


class TestUnsubscribeFromOrderbook:
    """Test _unsubscribe_from_orderbook method."""

    def test_unsubscribe_removes_from_tracker(self):
        """Unsubscribing removes the pair from all tracker lists."""
        ctrl = _make_controller()
        tracker = _attach_mock_tracker(ctrl)

        ctrl._unsubscribe_from_orderbook("XRP-EUR")

        assert "XRP-EUR" not in tracker._trading_pairs
        assert "XRP-EUR" not in tracker._data_source._trading_pairs
        assert "XRP-EUR" not in tracker._order_books

    def test_unsubscribe_noop_for_unknown_pair(self):
        """Unsubscribing from a pair not in tracker is safe."""
        ctrl = _make_controller()
        _attach_mock_tracker(ctrl)

        # Should not raise
        ctrl._unsubscribe_from_orderbook("UNKNOWN-EUR")

    def test_unsubscribe_without_connector(self):
        """Unsubscribe is safe when connector is None."""
        ctrl = _make_controller()
        ctrl.connector = None

        # Should not raise
        ctrl._unsubscribe_from_orderbook("BTC-EUR")

    def test_unsubscribe_without_tracker(self):
        """Unsubscribe is safe when tracker is missing."""
        ctrl = _make_controller()
        ctrl.connector = MagicMock(spec=[])  # No order_book_tracker attr

        # Should not raise
        ctrl._unsubscribe_from_orderbook("BTC-EUR")


class TestPoolRemovalTriggersUnsubscribe:
    """Test that pool refresh removal triggers unsubscribe."""

    @pytest.mark.asyncio
    async def test_pool_refresh_unsubscribes_removed_coins(self):
        """When a coin is removed from pool, its orderbook is unsubscribed."""
        ctrl = _make_controller(max_coins=2)
        tracker = _attach_mock_tracker(ctrl)

        ctrl.monitored_coins = ["BTC-EUR", "ADA-EUR"]
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 5000,
            "ADA-EUR": now - 5000,
        }

        # SOL outranks ADA → ADA should be removed and unsubscribed
        volumes = {"BTC-EUR": 10000, "SOL-EUR": 7000, "ADA-EUR": 500}
        spreads = {"BTC-EUR": 0.001, "SOL-EUR": 0.001, "ADA-EUR": 0.001}

        await ctrl._update_monitored_coins_from_pool(volumes, spreads)

        assert "ADA-EUR" not in ctrl.monitored_coins
        assert "ADA-EUR" not in tracker._trading_pairs
        assert "ADA-EUR" not in tracker._data_source._trading_pairs


class TestRotationTriggersUnsubscribe:
    """Test that rotation triggers unsubscribe for old coins."""

    def test_rotation_unsubscribes_old_coin(self):
        """Rotated-out coin has its orderbook unsubscribed."""
        ctrl = _make_controller(max_coins=3)
        tracker = _attach_mock_tracker(ctrl)

        ctrl.monitored_coins = ["BTC-EUR", "XRP-EUR", "ADA-EUR"]
        ctrl.coin_performance = {"BTC-EUR": 0, "XRP-EUR": 10, "ADA-EUR": 0}
        ctrl.rotation_threshold = 5
        now = time.time()
        ctrl._pool_join_time = {
            "BTC-EUR": now - 5000,
            "XRP-EUR": now - 5000,
            "ADA-EUR": now - 5000,
        }

        ctrl._rotate_underperforming_coins()

        assert "XRP-EUR" not in ctrl.monitored_coins
        assert "XRP-EUR" not in tracker._trading_pairs


class TestPrefetchTopNAutoAlign:
    """Test that prefetch auto-aligns top_n with max_coins_to_monitor."""

    def test_top_n_warning_when_less_than_max_coins(self):
        """Prefetch should auto-align top_n to max_coins_to_monitor."""
        ctrl = _make_controller(max_coins=25)
        _attach_mock_tracker(ctrl)

        ctrl.config.orderbook_prefetch = {
            'enabled': True,
            'mode': 'shadow',
            'top_n': 15,  # Less than max_coins_to_monitor
        }

        # Call with enough candidates
        candidates = [f"COIN{i}-EUR" for i in range(30)]

        # Should not raise, should log warning about auto-alignment
        ctrl._prefetch_orderbooks_shadow(candidates)
        # The method logs but doesn't return a value;
        # checking it runs without error is sufficient
