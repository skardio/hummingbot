from decimal import Decimal
from enum import Enum
from typing import Optional

from hummingbot.core.data_type.in_flight_order import InFlightOrder


class CloseType(Enum):
    TIME_LIMIT = 1
    STOP_LOSS = 2
    TAKE_PROFIT = 3
    EXPIRED = 4
    EARLY_STOP = 5
    TRAILING_STOP = 6
    INSUFFICIENT_BALANCE = 7
    FAILED = 8
    COMPLETED = 9
    POSITION_HOLD = 10
    # Story A1: Multi-Timeout Lifecycle
    NO_FILL_TIMEOUT = 11           # No fills after no_fill_timeout_sec → cancel + close
    NO_PROGRESS_TIMEOUT = 12       # No progress after no_progress_timeout_sec → unwind
    HARD_CAP_TIME_LIMIT = 13       # Hit max_hold_time_seconds → forced unwind
    RISK_KILL_SWITCH = 14          # Global risk manager triggered → emergency unwind
    # Story B1: Manual close
    MANUAL = 15                    # Manual forced close by operator
    # Story B2: Switch close (coin swap)
    SWITCH = 16                    # Position closed to switch to different coin


# Story B1: Close reason priority for idempotent forced exits
# Higher priority = keeps reason if multiple forced closes triggered
# (e.g., RISK_KILL_SWITCH overrides TIME_LIMIT)
CLOSE_TYPE_PRIORITY = {
    CloseType.RISK_KILL_SWITCH: 100,      # Highest priority - risk override
    CloseType.STOP_LOSS: 90,              # High priority - hard loss limit
    CloseType.HARD_CAP_TIME_LIMIT: 80,    # High priority - absolute time limit
    CloseType.TIME_LIMIT: 70,             # Medium-high priority - triple barrier time
    CloseType.NO_PROGRESS_TIMEOUT: 60,    # Medium priority - stagnation
    CloseType.NO_FILL_TIMEOUT: 50,        # Lower priority - never got filled
    CloseType.MANUAL: 40,                 # Lower priority - operator requested
    CloseType.TRAILING_STOP: 30,          # Low priority - profit protection
    CloseType.INSUFFICIENT_BALANCE: 20,   # Very low priority - balance issue
    CloseType.TAKE_PROFIT: 10,            # Lowest priority - normal completion
    CloseType.COMPLETED: 10,
    CloseType.EARLY_STOP: 10,
    CloseType.EXPIRED: 10,
    CloseType.FAILED: 10,
    CloseType.POSITION_HOLD: 10,
}


def get_close_type_priority(close_type: CloseType) -> int:
    """Get priority for a close type (higher = more important)"""
    return CLOSE_TYPE_PRIORITY.get(close_type, 0)


class TrackedOrder:
    def __init__(self, order_id: Optional[str] = None):
        self._order_id = order_id
        self._order = None

    @property
    def order_id(self):
        return self._order_id

    @order_id.setter
    def order_id(self, order_id: str):
        self._order_id = order_id

    @property
    def order(self):
        return self._order

    @order.setter
    def order(self, order: InFlightOrder):
        self._order = order

    @property
    def creation_timestamp(self):
        if self.order:
            return self.order.creation_timestamp
        else:
            return None

    @property
    def price(self):
        if self.order:
            return self.order.price
        else:
            return None

    @property
    def last_update_timestamp(self):
        if self.order:
            return self.order.last_update_timestamp
        else:
            return None

    @property
    def average_executed_price(self):
        if self.order:
            return self.order.average_executed_price or self.order.price
        else:
            return Decimal("0")

    @property
    def executed_amount_base(self):
        if self.order:
            return self.order.executed_amount_base
        else:
            return Decimal("0")

    @property
    def executed_amount_quote(self):
        if self.order:
            return self.order.executed_amount_quote
        else:
            return Decimal("0")

    @property
    def fee_asset(self):
        if self.order and len(self.order.order_fills) > 0:
            return list(self.order.order_fills.values())[0].fee_asset
        else:
            return None

    @property
    def cum_fees_base(self):
        if self.order:
            return self.order.cumulative_fee_paid(token=self.order.base_asset)
        else:
            return Decimal("0")

    @property
    def cum_fees_quote(self):
        if self.order:
            return self.order.cumulative_fee_paid(token=self.order.quote_asset)
        else:
            return Decimal("0")

    @property
    def is_done(self):
        if self.order:
            return self.order.is_done
        else:
            return False

    @property
    def is_open(self):
        if self.order:
            return self.order.is_open
        else:
            return False

    @property
    def is_filled(self):
        if self.order:
            return self.order.is_filled
        else:
            return False
