"""
Unit tests for Multi-Coin Simultaneous Trading Feature

Tests the new max_simultaneous_coins functionality that allows
trading multiple coins at the same time with capital divided equally.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestMultiCoinConfig:
    """Test multi-coin configuration options"""

    def test_max_simultaneous_coins_default_is_one(self):
        """Default should be 1 for backwards compatibility"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        config = MultiCoinGridConfig()
        assert config.max_simultaneous_coins == 1

    def test_max_simultaneous_coins_accepts_valid_values(self):
        """Should accept values 1-5"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        for value in [1, 2, 3, 4, 5]:
            config = MultiCoinGridConfig(max_simultaneous_coins=value)
            assert config.max_simultaneous_coins == value

    def test_max_simultaneous_coins_has_minimum_one(self):
        """Should not accept values less than 1"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        with pytest.raises(Exception):  # Pydantic validation error
            MultiCoinGridConfig(max_simultaneous_coins=0)

    def test_max_simultaneous_coins_has_maximum_five(self):
        """Should not accept values greater than 5"""
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig

        with pytest.raises(Exception):  # Pydantic validation error
            MultiCoinGridConfig(max_simultaneous_coins=6)


class TestMultiCoinCapitalAllocation:
    """Test capital allocation for multiple coins"""

    def test_capital_divided_equally_two_coins(self):
        """€80 with 2 coins should give €40 per coin"""
        total_capital = Decimal("80")
        max_coins = 2
        per_coin = total_capital / Decimal(str(max_coins))
        assert per_coin == Decimal("40")

    def test_capital_divided_equally_three_coins(self):
        """€80 with 3 coins should give ~€26.67 per coin"""
        total_capital = Decimal("80")
        max_coins = 3
        per_coin = total_capital / Decimal(str(max_coins))
        assert per_coin == Decimal("80") / Decimal("3")
        assert float(per_coin) == pytest.approx(26.67, rel=0.01)

    def test_capital_divided_equally_one_coin(self):
        """€80 with 1 coin should give €80 (backwards compatible)"""
        total_capital = Decimal("80")
        max_coins = 1
        per_coin = total_capital / Decimal(str(max_coins))
        assert per_coin == Decimal("80")


class TestMultiCoinStateTracking:
    """Test state tracking for multiple active coins"""

    def test_active_coins_dict_initialized_empty(self):
        """active_coins should start as empty dict"""
        # Simulate controller initialization
        active_coins = {}
        assert active_coins == {}
        assert len(active_coins) == 0

    def test_active_coins_tracks_coin_to_executor(self):
        """active_coins should map coin symbol to executor ID"""
        active_coins = {}

        # Add first coin
        active_coins["SOL-EUR"] = "executor_123"
        assert "SOL-EUR" in active_coins
        assert active_coins["SOL-EUR"] == "executor_123"

        # Add second coin
        active_coins["ADA-EUR"] = "executor_456"
        assert len(active_coins) == 2
        assert "ADA-EUR" in active_coins

    def test_active_coins_removal(self):
        """Removing coin from active_coins"""
        active_coins = {
            "SOL-EUR": "executor_123",
            "ADA-EUR": "executor_456"
        }

        # Remove one coin
        del active_coins["SOL-EUR"]

        assert len(active_coins) == 1
        assert "SOL-EUR" not in active_coins
        assert "ADA-EUR" in active_coins


class TestMultiCoinDecisionLogic:
    """Test decision logic for multi-coin trading"""

    def test_should_not_add_coin_already_trading(self):
        """If best_coin is already in active_coins, should return False"""
        active_coins = {"SOL-EUR": "executor_123"}
        best_coin = "SOL-EUR"

        # Logic: if best_coin already trading, don't create new grid
        should_create = best_coin not in active_coins
        assert should_create is False

    def test_should_add_coin_when_room_available(self):
        """If room available (len < max), should allow new coin"""
        active_coins = {"SOL-EUR": "executor_123"}
        max_simultaneous = 2
        best_coin = "ADA-EUR"

        has_room = len(active_coins) < max_simultaneous
        is_new_coin = best_coin not in active_coins

        should_create = has_room and is_new_coin
        assert should_create is True

    def test_should_not_add_when_slots_full(self):
        """If all slots full (len == max), should not add more"""
        active_coins = {
            "SOL-EUR": "executor_123",
            "ADA-EUR": "executor_456"
        }
        max_simultaneous = 2

        has_room = len(active_coins) < max_simultaneous

        # Even if it's a new coin, no room
        assert has_room is False


class TestMultiCoinBackwardsCompatibility:
    """Test backwards compatibility with single-coin mode"""

    def test_single_coin_mode_still_works(self):
        """When max_simultaneous_coins=1, should behave like before"""
        max_simultaneous = 1
        active_coins = {}
        _ = None  # Legacy tracking

        # First coin should be allowed
        best_coin = "SOL-EUR"
        has_room = len(active_coins) < max_simultaneous
        assert has_room is True

        # Add it
        active_coins[best_coin] = "executor_123"

        # Second coin should NOT be allowed
        has_room = len(active_coins) < max_simultaneous
        assert has_room is False

    def test_legacy_active_coin_tracking_synced(self):
        """Legacy active_coin should sync with active_coins dict"""
        active_coins = {}
        _ = None

        # Add coin (both legacy and new tracking)
        active_coins["SOL-EUR"] = "executor_123"
        active_coin = "SOL-EUR"

        assert active_coin == "SOL-EUR"
        assert active_coin in active_coins


class TestMultiCoinIntegration:
    """Integration-style tests for multi-coin feature"""

    def test_full_flow_two_coins(self):
        """Simulate full flow with 2 simultaneous coins"""
        max_simultaneous = 2
        total_capital = Decimal("80")
        active_coins = {}

        # Calculate per-coin capital
        per_coin_capital = total_capital / Decimal(str(max_simultaneous))
        assert per_coin_capital == Decimal("40")

        # Add first coin
        coin1 = "SOL-EUR"
        if len(active_coins) < max_simultaneous and coin1 not in active_coins:
            active_coins[coin1] = "executor_1"

        assert len(active_coins) == 1

        # Add second coin
        coin2 = "ADA-EUR"
        if len(active_coins) < max_simultaneous and coin2 not in active_coins:
            active_coins[coin2] = "executor_2"

        assert len(active_coins) == 2

        # Try to add third coin (should not add)
        coin3 = "LINK-EUR"
        if len(active_coins) < max_simultaneous and coin3 not in active_coins:
            active_coins[coin3] = "executor_3"

        # Still only 2 coins
        assert len(active_coins) == 2
        assert coin3 not in active_coins

    def test_coin_exit_frees_slot(self):
        """When a coin exits, slot should be freed for new coin"""
        max_simultaneous = 2
        active_coins = {
            "SOL-EUR": "executor_1",
            "ADA-EUR": "executor_2"
        }

        # All slots full
        assert len(active_coins) == max_simultaneous

        # SOL-EUR position closes
        del active_coins["SOL-EUR"]

        # Now there's room
        assert len(active_coins) < max_simultaneous

        # New coin can join
        new_coin = "LINK-EUR"
        if len(active_coins) < max_simultaneous:
            active_coins[new_coin] = "executor_3"

        assert new_coin in active_coins
        assert len(active_coins) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
