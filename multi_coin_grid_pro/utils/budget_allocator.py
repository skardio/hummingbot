"""
US-004: Budget Allocator

Prevents "Insufficient balance" errors by:
1. Tracking reserved capital per active executor
2. Checking available balance before creating new executors
3. Blocking executor creation if insufficient free capital

The allocator uses a pessimistic reservation model:
- Each executor reserves: grid_levels × order_amount + fee_buffer
- Free capital = total_balance - reserved_capital
- New executor only starts if free_capital >= required_capital
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional


@dataclass
class BudgetReservation:
    """Represents capital reserved for an executor."""
    executor_id: str
    symbol: str
    reserved_amount: Decimal  # Quote currency
    grid_levels: int
    timestamp: float


@dataclass
class BudgetCheckResult:
    """Result of budget availability check."""
    is_allowed: bool
    available_quote: Decimal
    required_quote: Decimal
    reason: Optional[str] = None
    reserved_by_others: Decimal = Decimal("0")


class BudgetAllocator:
    """
    Manages capital allocation across multiple concurrent executors.

    Key principles:
    1. Pessimistic reservation: assume worst-case capital needs
    2. Fee buffer: reserve extra for trading fees (configurable)
    3. Quote reserve: keep minimum buffer in account (safety margin)

    Example:
        allocator = BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),  # 0.2% for fees
            quote_reserve_pct=Decimal("0.05"),  # Keep 5% reserve
            logger=my_logger
        )

        # Before creating executor:
        result = allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("100"),
        )

        if result.is_allowed:
            # Create executor
            allocator.reserve("exec-123", "BTC-USDT", Decimal("100"), grid_levels=3, timestamp=now)
    """

    def __init__(
        self,
        fee_buffer_pct: Decimal = Decimal("0.002"),  # 0.2% default
        quote_reserve_pct: Decimal = Decimal("0.05"),  # 5% safety buffer
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize budget allocator.

        Args:
            fee_buffer_pct: Extra % to reserve for fees per executor
            quote_reserve_pct: % of total balance to keep as safety reserve
            logger: Logger instance
        """
        self.fee_buffer_pct = fee_buffer_pct
        self.quote_reserve_pct = quote_reserve_pct
        self.logger = logger or logging.getLogger(__name__)

        # Active reservations: executor_id -> BudgetReservation
        self._reservations: Dict[str, BudgetReservation] = {}

    @property
    def total_reserved(self) -> Decimal:
        """Total capital currently reserved across all executors."""
        return sum(r.reserved_amount for r in self._reservations.values())

    @property
    def active_executor_count(self) -> int:
        """Number of executors with active reservations."""
        return len(self._reservations)

    def calculate_required_quote(
        self,
        base_amount: Decimal,
        grid_levels: int = 3,
        include_fee_buffer: bool = True,
    ) -> Decimal:
        """
        Calculate total quote required for an executor.

        Args:
            base_amount: Base capital allocation (total_amount_quote from config)
            grid_levels: Number of grid levels
            include_fee_buffer: Whether to add fee buffer

        Returns:
            Total quote currency required
        """
        required = base_amount

        if include_fee_buffer:
            # Add fee buffer per level (buy + sell = 2 trades per level)
            fee_per_trade = base_amount * self.fee_buffer_pct
            total_fee_buffer = fee_per_trade * Decimal(str(grid_levels * 2))
            required += total_fee_buffer

        return required

    def check_budget(
        self,
        total_balance: Decimal,
        required_quote: Decimal,
        symbol: Optional[str] = None,
    ) -> BudgetCheckResult:
        """
        Check if budget is available for a new executor.

        Args:
            total_balance: Current total quote balance from exchange
            required_quote: Quote amount needed for new executor
            symbol: Optional symbol for logging

        Returns:
            BudgetCheckResult with decision and details
        """
        # Calculate reserve requirement
        min_reserve = total_balance * self.quote_reserve_pct

        # Calculate available after reservations and safety buffer
        reserved = self.total_reserved
        available = total_balance - reserved - min_reserve

        if available < Decimal("0"):
            available = Decimal("0")

        # Check if we have enough
        if available >= required_quote:
            self.logger.debug(
                f"✅ US-004 BUDGET OK | {symbol or 'new'}: "
                f"need {required_quote:.2f}, have {available:.2f} free "
                f"(balance={total_balance:.2f}, reserved={reserved:.2f}, "
                f"safety_buffer={min_reserve:.2f})"
            )
            return BudgetCheckResult(
                is_allowed=True,
                available_quote=available,
                required_quote=required_quote,
                reserved_by_others=reserved,
            )
        else:
            reason = (
                f"Insufficient free capital: need {required_quote:.2f}, "
                f"have {available:.2f} (balance={total_balance:.2f}, "
                f"reserved={reserved:.2f}, safety={min_reserve:.2f})"
            )
            self.logger.warning(
                f"🚫 US-004 BUDGET BLOCKED | {symbol or 'new'}: {reason}"
            )
            return BudgetCheckResult(
                is_allowed=False,
                available_quote=available,
                required_quote=required_quote,
                reason=reason,
                reserved_by_others=reserved,
            )

    def reserve(
        self,
        executor_id: str,
        symbol: str,
        amount: Decimal,
        grid_levels: int,
        timestamp: float,
    ) -> bool:
        """
        Reserve capital for an executor.

        Should be called after check_budget() returns is_allowed=True
        and before executor is actually created.

        Args:
            executor_id: Unique executor ID
            symbol: Trading pair
            amount: Quote amount to reserve
            grid_levels: Number of grid levels
            timestamp: Current timestamp

        Returns:
            True if reservation was made
        """
        if executor_id in self._reservations:
            self.logger.warning(
                f"⚠️ US-004: Executor {executor_id[:8]}... already has reservation"
            )
            return False

        reservation = BudgetReservation(
            executor_id=executor_id,
            symbol=symbol,
            reserved_amount=amount,
            grid_levels=grid_levels,
            timestamp=timestamp,
        )
        self._reservations[executor_id] = reservation

        self.logger.info(
            f"💰 US-004 RESERVED | {symbol}: €{amount:.2f} for executor {executor_id[:8]}... "
            f"(total reserved: €{self.total_reserved:.2f}, {self.active_executor_count} executors)"
        )
        return True

    def release(self, executor_id: str) -> Optional[Decimal]:
        """
        Release reservation when executor completes/stops.

        Args:
            executor_id: Executor ID to release

        Returns:
            Amount that was released, or None if not found
        """
        reservation = self._reservations.pop(executor_id, None)

        if reservation:
            self.logger.info(
                f"💰 US-004 RELEASED | {reservation.symbol}: €{reservation.reserved_amount:.2f} "
                f"from executor {executor_id[:8]}... "
                f"(remaining reserved: €{self.total_reserved:.2f}, {self.active_executor_count} executors)"
            )
            return reservation.reserved_amount
        else:
            self.logger.debug(
                f"⚠️ US-004: No reservation found for executor {executor_id[:8]}..."
            )
            return None

    def get_reservation(self, executor_id: str) -> Optional[BudgetReservation]:
        """Get reservation details for an executor."""
        return self._reservations.get(executor_id)

    def get_symbol_reservations(self, symbol: str) -> Decimal:
        """Get total reserved amount for a specific symbol."""
        return sum(
            r.reserved_amount
            for r in self._reservations.values()
            if r.symbol == symbol
        )

    def cleanup_stale_reservations(self, max_age_seconds: float, current_time: float) -> int:
        """
        Remove reservations older than max_age (safety cleanup).

        Args:
            max_age_seconds: Maximum age before considering stale
            current_time: Current timestamp

        Returns:
            Number of reservations cleaned up
        """
        stale_ids = [
            eid for eid, r in self._reservations.items()
            if (current_time - r.timestamp) > max_age_seconds
        ]

        for eid in stale_ids:
            reservation = self._reservations.pop(eid)
            self.logger.warning(
                f"🧹 US-004 STALE CLEANUP | {reservation.symbol}: "
                f"Released €{reservation.reserved_amount:.2f} from stale executor {eid[:8]}... "
                f"(age: {(current_time - reservation.timestamp) / 3600:.1f}h)"
            )

        return len(stale_ids)

    def sync_with_active_executors(
        self,
        active_executor_ids: set,
        current_time: float,
    ) -> int:
        """
        Sync reservations with actually active executors.

        Removes reservations for executors that are no longer active.

        Args:
            active_executor_ids: Set of currently active executor IDs
            current_time: Current timestamp (for logging)

        Returns:
            Number of orphaned reservations cleaned up
        """
        orphaned_ids = [
            eid for eid in self._reservations.keys()
            if eid not in active_executor_ids
        ]

        for eid in orphaned_ids:
            reservation = self._reservations.pop(eid)
            self.logger.info(
                f"🧹 US-004 SYNC | Released orphaned reservation for {reservation.symbol}: "
                f"€{reservation.reserved_amount:.2f} (executor {eid[:8]}... no longer active)"
            )

        return len(orphaned_ids)

    def get_summary(self) -> Dict:
        """Get summary of current allocations."""
        return {
            "total_reserved": float(self.total_reserved),
            "executor_count": self.active_executor_count,
            "reservations": {
                eid: {
                    "symbol": r.symbol,
                    "amount": float(r.reserved_amount),
                    "grid_levels": r.grid_levels,
                }
                for eid, r in self._reservations.items()
            }
        }
