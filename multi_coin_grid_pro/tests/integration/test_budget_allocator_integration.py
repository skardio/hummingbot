"""
Integration Tests - Budget Allocator + Controller

Tests that the BudgetAllocator is properly integrated with the controller:
1. BudgetAllocator is initialized on controller startup
2. check_budget() is called before grid creation
3. reserve() is called after successful grid creation
4. release() is called when executor terminates
5. Overallocation is prevented when creating multiple grids

This prevents the bug where bot allocated $237 across 3 grids when only $83 was available.
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from multi_coin_grid_pro.utils.budget_allocator import BudgetAllocator  # noqa: E402


class TestBudgetAllocatorIntegration:
    """Integration tests for BudgetAllocator with controller."""

    @pytest.fixture
    def budget_allocator(self):
        """Create a BudgetAllocator instance."""
        return BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),
            quote_reserve_pct=Decimal("0.05"),
            logger=MagicMock(),
        )

    def test_allocator_prevents_overallocation(self, budget_allocator):
        """
        Test that allocator prevents creating grids when budget is exhausted.

        Scenario: $100 available (with 5% reserve = $95 usable), 3 coins each needing $50
        - Coin 1: $50 allowed (remaining: $45)
        - Coin 2: $50 blocked (only $45 available)
        - Coin 3: $50 blocked (only $45 available)
        """
        total_balance = Decimal("100")
        grid_cost = Decimal("50")

        # First coin - should be allowed
        result1 = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=grid_cost,
            symbol="PEPE-USD",
        )
        assert result1.is_allowed, f"First coin should be allowed: {result1.reason}"

        # Reserve for first coin
        budget_allocator.reserve(
            executor_id="exec-pepe-1",
            symbol="PEPE-USD",
            amount=grid_cost,
            grid_levels=5,
            timestamp=1000.0,
        )

        # Second coin - should be blocked (no room left)
        result2 = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=grid_cost,
            symbol="DOGE-USD",
        )
        assert not result2.is_allowed, "Second coin should be blocked - insufficient budget"
        assert "Insufficient" in result2.reason

        # Third coin - also blocked
        result3 = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=grid_cost,
            symbol="SHIB-USD",
        )
        assert not result3.is_allowed, "Third coin should be blocked - insufficient budget"

    def test_allocator_allows_after_release(self, budget_allocator):
        """
        Test that releasing a reservation frees up capital for new grids.
        """
        total_balance = Decimal("100")
        grid_cost = Decimal("50")

        # Reserve first grid
        budget_allocator.reserve("exec-1", "BTC-USD", grid_cost, 5, 1000.0)

        # Check - should allow second grid (100 - 50 - 5% reserve = 45, need 50 -> blocked)
        result_before = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=grid_cost,
            symbol="ETH-USD",
        )
        assert not result_before.is_allowed, "Should be blocked before release"

        # Release first grid
        budget_allocator.release("exec-1")

        # Check again - should allow now
        result_after = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=grid_cost,
            symbol="ETH-USD",
        )
        assert result_after.is_allowed, f"Should be allowed after release: {result_after.reason}"

    def test_allocator_tracks_multiple_symbols(self, budget_allocator):
        """
        Test that allocator correctly tracks reservations across multiple symbols.
        """
        total_balance = Decimal("300")

        # Reserve for 3 different symbols
        budget_allocator.reserve("exec-btc", "BTC-USD", Decimal("80"), 5, 1000.0)
        budget_allocator.reserve("exec-eth", "ETH-USD", Decimal("70"), 5, 1001.0)
        budget_allocator.reserve("exec-sol", "SOL-USD", Decimal("60"), 5, 1002.0)

        # Total reserved: 210
        assert budget_allocator.total_reserved == Decimal("210")
        assert budget_allocator.active_executor_count == 3

        # Available: 300 - 210 - 15 (5% reserve) = 75
        result = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=Decimal("80"),
            symbol="DOGE-USD",
        )
        assert not result.is_allowed, "Should be blocked - need 80, have 75"

        # But a smaller grid should work
        result_small = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=Decimal("70"),
            symbol="DOGE-USD",
        )
        assert result_small.is_allowed, f"Smaller grid should be allowed: {result_small.reason}"

    def test_allocator_respects_quote_reserve(self, budget_allocator):
        """
        Test that allocator keeps quote reserve buffer.

        With 5% reserve on $100, only $95 is available for trading.
        """
        total_balance = Decimal("100")

        # Try to allocate entire balance
        result = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=Decimal("100"),
            symbol="BTC-USD",
        )
        assert not result.is_allowed, "Should not allow allocating entire balance"

        # 95 should work (100 - 5% reserve)
        result_95 = budget_allocator.check_budget(
            total_balance=total_balance,
            required_quote=Decimal("95"),
            symbol="BTC-USD",
        )
        assert result_95.is_allowed, f"95% should be allowed: {result_95.reason}"

    def test_exact_kraken_scenario(self, budget_allocator):
        """
        Reproduce the exact Kraken USD bot scenario (adjusted for 5% reserve):
        - Balance: $100 (usable: $95 after 5% reserve)
        - Bot tries to create 3 grids at $50 each = $150 total
        - Should only create 1 grid (uses $50, leaving $45 which is < $50)

        This test ensures the fix prevents the overallocation.
        """
        total_balance = Decimal("100")
        grid_cost_per_coin = Decimal("50")
        coins = ["PEPE-USD", "DOGE-USD", "SHIB-USD"]

        grids_created = 0
        grids_blocked = 0

        for i, coin in enumerate(coins):
            result = budget_allocator.check_budget(
                total_balance=total_balance,
                required_quote=grid_cost_per_coin,
                symbol=coin,
            )

            if result.is_allowed:
                budget_allocator.reserve(
                    executor_id=f"exec-{coin}-{i}",
                    symbol=coin,
                    amount=grid_cost_per_coin,
                    grid_levels=5,
                    timestamp=1000.0 + i,
                )
                grids_created += 1
            else:
                grids_blocked += 1

        # Should only create 1 grid (not 3!)
        assert grids_created == 1, f"Expected 1 grid created, got {grids_created}"
        assert grids_blocked == 2, f"Expected 2 grids blocked, got {grids_blocked}"

        # Total reserved should be $50, not $150
        assert budget_allocator.total_reserved == Decimal("50")

    def test_sync_cleans_orphaned_reservations(self, budget_allocator):
        """
        Test that sync removes reservations for executors that no longer exist.
        """
        # Create 3 reservations
        budget_allocator.reserve("exec-1", "BTC-USD", Decimal("50"), 5, 1000.0)
        budget_allocator.reserve("exec-2", "ETH-USD", Decimal("50"), 5, 1001.0)
        budget_allocator.reserve("exec-3", "SOL-USD", Decimal("50"), 5, 1002.0)

        assert budget_allocator.total_reserved == Decimal("150")

        # Simulate: only exec-2 is still active
        active_executor_ids = {"exec-2"}
        cleaned = budget_allocator.sync_with_active_executors(active_executor_ids, 2000.0)

        assert cleaned == 2, "Should have cleaned up 2 orphaned reservations"
        assert budget_allocator.total_reserved == Decimal("50")
        assert budget_allocator.active_executor_count == 1


class TestControllerBudgetAllocatorHooks:
    """
    Test that the controller has the BudgetAllocator hooks in place.

    These tests verify the integration points exist without needing
    to instantiate the full controller (which has many dependencies).
    """

    def test_controller_imports_budget_allocator(self):
        """Verify controller imports BudgetAllocator."""
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController  # noqa: F401

        # If import succeeds, the module has the import
        assert MultiCoinGridController is not None

    def test_budget_allocator_class_has_required_methods(self):
        """Verify BudgetAllocator has all required methods."""
        allocator = BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),
            quote_reserve_pct=Decimal("0.05"),
            logger=MagicMock(),
        )

        # Required methods
        assert hasattr(allocator, 'check_budget')
        assert hasattr(allocator, 'reserve')
        assert hasattr(allocator, 'release')
        assert hasattr(allocator, 'sync_with_active_executors')
        assert hasattr(allocator, 'total_reserved')
        assert hasattr(allocator, 'active_executor_count')

    def test_controller_source_has_budget_allocator_integration(self):
        """
        Verify the controller source code contains budget allocator integration.

        This is a static check that the hooks are present.
        """
        controller_path = Path(__file__).parent.parent.parent / "controllers" / "multi_coin_grid_controller.py"

        if not controller_path.exists():
            pytest.skip("Controller file not found at expected path")

        content = controller_path.read_text()

        # Check for import
        assert "from multi_coin_grid_pro.utils.budget_allocator import BudgetAllocator" in content, \
            "Controller should import BudgetAllocator"

        # Check for initialization
        assert "self.budget_allocator" in content, \
            "Controller should initialize budget_allocator"

        # Check for check_budget usage
        assert "check_budget" in content, \
            "Controller should call check_budget before grid creation"

        # Check for reserve usage
        assert "budget_allocator.reserve" in content, \
            "Controller should call reserve after grid creation"

        # Check for release usage
        assert "budget_allocator.release" in content, \
            "Controller should call release when executor terminates"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
