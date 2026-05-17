import asyncio
import logging
import time
import uuid
from collections import deque
from decimal import Decimal
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from hummingbot.connector.markets_recorder import MarketsRecorder
from hummingbot.core.data_type.common import PositionAction, PositionMode, PriceType, TradeType
from hummingbot.logger import HummingbotLogger
from hummingbot.model.position import Position

if TYPE_CHECKING:
    from hummingbot.strategy.strategy_v2_base import StrategyV2Base

from hummingbot.strategy_v2.executors.arbitrage_executor.arbitrage_executor import ArbitrageExecutor
from hummingbot.strategy_v2.executors.data_types import PositionSummary
from hummingbot.strategy_v2.executors.dca_executor.dca_executor import DCAExecutor
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.order_executor.order_executor import OrderExecutor
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor
from hummingbot.strategy_v2.executors.twap_executor.twap_executor import TWAPExecutor
from hummingbot.strategy_v2.executors.xemm_executor.xemm_executor import XEMMExecutor
from hummingbot.strategy_v2.models.executor_actions import (
    CreateExecutorAction,
    ExecutorAction,
    StopExecutorAction,
    StoreExecutorAction,
)
from hummingbot.strategy_v2.models.executors import CloseType
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, PerformanceReport


class PositionHold:
    def __init__(self, connector_name: str, trading_pair: str, side: TradeType):
        self.connector_name = connector_name
        self.trading_pair = trading_pair
        self.side = side
        # Store only client order IDs
        self.order_ids = set()

        # Pre-calculated metrics
        self.volume_traded_quote = Decimal("0")
        self.cum_fees_quote = Decimal("0")

        # Separate tracking for buys and sells
        self.buy_amount_base = Decimal("0")
        self.buy_amount_quote = Decimal("0")
        self.sell_amount_base = Decimal("0")
        self.sell_amount_quote = Decimal("0")

    def add_orders_from_executor(self, executor: ExecutorInfo):
        custom_info = executor.custom_info
        if "held_position_orders" not in custom_info or len(custom_info["held_position_orders"]) == 0:
            return

        for order in custom_info["held_position_orders"]:
            # Skip if we've already processed this order
            order_id = order.get("client_order_id")
            if order_id in self.order_ids:
                continue

            # Add the order ID to our set
            self.order_ids.add(order_id)

            # Update metrics incrementally
            executed_amount_base = Decimal(str(order.get("executed_amount_base", 0)))
            executed_amount_quote = Decimal(str(order.get("executed_amount_quote", 0)))
            is_buy = order.get("trade_type") == "BUY"

            # Update volume traded in quote
            self.volume_traded_quote += executed_amount_quote

            # Update buy/sell amounts
            if is_buy:
                self.buy_amount_base += executed_amount_base
                self.buy_amount_quote += executed_amount_quote
            else:
                self.sell_amount_base += executed_amount_base
                self.sell_amount_quote += executed_amount_quote

            # Update fees
            self.cum_fees_quote += Decimal(str(order.get("cumulative_fee_paid_quote", 0)))

    def get_position_summary(self, mid_price: Decimal):
        # Handle NaN quote amounts by calculating them lazily
        if self.buy_amount_quote.is_nan() and self.buy_amount_base > 0:
            self.buy_amount_quote = self.buy_amount_base * mid_price
        if self.sell_amount_quote.is_nan() and self.sell_amount_base > 0:
            self.sell_amount_quote = self.sell_amount_base * mid_price

        # Calculate buy and sell breakeven prices
        buy_breakeven_price = self.buy_amount_quote / self.buy_amount_base if self.buy_amount_base > 0 else Decimal("0")
        sell_breakeven_price = self.sell_amount_quote / self.sell_amount_base if self.sell_amount_base > 0 else Decimal("0")

        # Calculate matched volume (minimum of buy and sell base amounts)
        matched_amount_base = min(self.buy_amount_base, self.sell_amount_base)

        # Calculate realized PnL from matched volume
        realized_pnl_quote = (sell_breakeven_price - buy_breakeven_price) * matched_amount_base if matched_amount_base > 0 else Decimal("0")

        # Calculate net position amount and direction
        net_amount_base = self.buy_amount_base - self.sell_amount_base
        is_net_long = net_amount_base >= 0

        # Calculate unrealized PnL for the remaining unmatched volume
        unrealized_pnl_quote = Decimal("0")
        breakeven_price = Decimal("0")
        if net_amount_base != 0:
            if is_net_long:
                # Long position: remaining buy amount
                remaining_base = net_amount_base
                remaining_quote = self.buy_amount_quote - (matched_amount_base * buy_breakeven_price)
                breakeven_price = remaining_quote / remaining_base
                unrealized_pnl_quote = (mid_price - breakeven_price) * remaining_base
            else:
                # Short position: remaining sell amount
                remaining_base = abs(net_amount_base)
                remaining_quote = self.sell_amount_quote - (matched_amount_base * sell_breakeven_price)
                breakeven_price = remaining_quote / remaining_base
                unrealized_pnl_quote = (breakeven_price - mid_price) * remaining_base

        return PositionSummary(
            connector_name=self.connector_name,
            trading_pair=self.trading_pair,
            volume_traded_quote=self.volume_traded_quote,
            amount=abs(net_amount_base),
            side=TradeType.BUY if is_net_long else TradeType.SELL,
            breakeven_price=breakeven_price,
            unrealized_pnl_quote=unrealized_pnl_quote,
            realized_pnl_quote=realized_pnl_quote,
            cum_fees_quote=self.cum_fees_quote)


class ExecutorOrchestrator:
    """
    Orchestrator for various executors.
    """
    _logger = None
    _executor_mapping = {
        "position_executor": PositionExecutor,
        "grid_executor": GridExecutor,
        "dca_executor": DCAExecutor,
        "arbitrage_executor": ArbitrageExecutor,
        "twap_executor": TWAPExecutor,
        "xemm_executor": XEMMExecutor,
        "order_executor": OrderExecutor,
    }

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self,
                 strategy: "StrategyV2Base",
                 executors_update_interval: float = 1.0,
                 executors_max_retries: int = 10,
                 initial_positions_by_controller: Optional[dict] = None):
        self.strategy = strategy
        self.executors_update_interval = executors_update_interval
        self.executors_max_retries = executors_max_retries
        self.active_executors = {}
        self.positions_held = {}
        self.executors_ids_position_held = deque(maxlen=50)
        self.cached_performance = {}
        self.initial_positions_by_controller = initial_positions_by_controller or {}
        self._skipped_position_pairs: set = set()  # throttle "not in markets" warnings
        self._last_active_executor_snapshot_ts = 0.0
        self.active_executor_snapshot_interval_sec = 30.0
        self._initialize_cached_performance()

    def _initialize_cached_performance(self):
        """
        Initialize cached performance by querying the database for stored executors and positions.
        If initial positions are provided for a controller, skip loading database positions for that controller.
        """
        for controller_id in self.strategy.controllers.keys():
            if controller_id not in self.cached_performance:
                self.cached_performance[controller_id] = PerformanceReport()
                self.active_executors[controller_id] = []
                self.positions_held[controller_id] = []
        db_executors = MarketsRecorder.get_instance().get_all_executors()
        run_db_executors = [
            executor for executor in db_executors
            if self._timestamp_in_current_run(executor.timestamp)
        ]
        for executor in run_db_executors:
            controller_id = executor.controller_id
            if controller_id not in self.strategy.controllers:
                continue
            self._update_cached_performance(controller_id, executor)

        # Compute and add orphan fill PnL (fills not tracked by any executor)
        self._apply_orphan_fill_adjustment(run_db_executors)

        # Create initial positions from config overrides first
        self._create_initial_positions()

        # Load positions from database only for controllers without initial position overrides
        db_positions = MarketsRecorder.get_instance().get_all_positions()
        for position in db_positions:
            if not self._timestamp_in_current_run(position.timestamp):
                continue
            controller_id = position.controller_id
            # Skip if this controller has initial position overrides
            if controller_id in self.initial_positions_by_controller or controller_id not in self.strategy.controllers:
                continue
            # Skip if the connector/trading pair is not in the current strategy markets
            if (position.connector_name not in self.strategy.markets or
                    position.trading_pair not in self.strategy.markets.get(position.connector_name, set())):
                self.logger().warning(f"Skipping position for {position.connector_name}.{position.trading_pair} - "
                                      f"not available in current strategy markets")
                continue
            self._load_position_from_db(controller_id, position)

    def _timestamp_in_current_run(self, timestamp: Optional[float]) -> bool:
        run_start = getattr(self.strategy, "strategy_start_time", None)
        if run_start is None or timestamp is None:
            return True
        try:
            ts = float(timestamp)
        except (TypeError, ValueError):
            return False
        if ts > 1_000_000_000_000:
            return ts >= float(run_start) * 1000
        return ts >= float(run_start)

    def _apply_orphan_fill_adjustment(self, db_executors: list):
        """
        Build PositionHold entries from TradeFill records not tracked by any executor.
        This fixes the tracking gap where orders fill on the exchange after their
        executor has already closed. Orphan fills are added as held positions so that
        generate_performance_report() can mark them to market properly, rather than
        counting unsold crypto as realized loss.
        """
        controller_ids = list(self.strategy.controllers.keys())
        if len(controller_ids) != 1:
            if len(controller_ids) > 1:
                self.logger().warning(
                    "Orphan fill adjustment skipped: multiple controllers detected. "
                    "TradeFills cannot be reliably attributed to specific controllers."
                )
            return

        controller_id = controller_ids[0]

        # Collect all order IDs explicitly tracked by executors via filled_orders / held_position_orders
        tracked_order_ids = set()
        for executor_info in db_executors:
            if not executor_info.custom_info:
                continue
            for fo in executor_info.custom_info.get('filled_orders', []):
                client_id = fo.get('client_order_id', '')
                if client_id:
                    tracked_order_ids.add(client_id)
            for ho in executor_info.custom_info.get('held_position_orders', []):
                client_id = ho.get('client_order_id', '')
                if client_id:
                    tracked_order_ids.add(client_id)

        # Build executor time-windows per trading_pair.  A fill is NOT a true orphan if:
        #   (a) it falls within an executor's active period for the same pair (late-arriving fill),
        #   (b) the pair never had an executor (historical non-executor trading), or
        #   (c) the fill pre-dates the first executor ever opened for that pair.
        # Only fills that survive all three checks are genuine post-executor orphan fills.
        ORPHAN_BUFFER_MS = 60_000  # 60 s tolerance for late exchange confirmations
        pair_executor_windows: Dict[str, List[Tuple[int, int]]] = {}
        pair_first_open_ms: Dict[str, int] = {}
        for executor_info in db_executors:
            pair = executor_info.trading_pair
            if not pair:
                continue
            open_ms = int(executor_info.timestamp * 1000)
            if executor_info.close_timestamp:
                close_ms = int(executor_info.close_timestamp * 1000) + ORPHAN_BUFFER_MS
            else:
                close_ms = int(time.time() * 1000) + ORPHAN_BUFFER_MS
            pair_executor_windows.setdefault(pair, []).append((open_ms, close_ms))
            if pair not in pair_first_open_ms or open_ms < pair_first_open_ms[pair]:
                pair_first_open_ms[pair] = open_ms

        # Query all TradeFills
        try:
            all_fills = MarketsRecorder.get_instance().get_all_trade_fills()
        except Exception as e:
            self.logger().error(f"Failed to query TradeFills for orphan adjustment: {e}")
            return

        if not all_fills:
            return

        # Group orphan fills by trading pair.
        # A fill is considered tracked (non-orphan) if any of the following hold:
        #   1. Its order_id appears in an executor's filled_orders / held_position_orders.
        #   2. Its timestamp falls within any executor's active window for its trading_pair.
        #   3. The trading_pair never had any executor — the fill belongs to a different
        #      trading system entirely.
        #   4. The fill pre-dates the first executor ever opened for that pair — historical
        #      fill from before executor tracking was established for this pair.
        orphan_fills_by_pair: Dict[str, list] = {}
        orphan_count = 0
        for fill in all_fills:
            if not self._timestamp_in_current_run(fill.timestamp):
                continue
            if fill.order_id in tracked_order_ids:
                continue  # Matched by explicit order ID

            pair = fill.symbol
            fill_ts: int = fill.timestamp  # milliseconds

            windows = pair_executor_windows.get(pair)
            if windows is None:
                # Pair never traded via executor system; not our orphan to track
                continue

            if any(open_ms <= fill_ts <= close_ms for open_ms, close_ms in windows):
                continue  # Fill occurred during an executor's active period

            if fill_ts < pair_first_open_ms[pair]:
                # Fill pre-dates the first executor for this pair; it is a historical
                # fill unrelated to current executor tracking, not a true orphan.
                continue

            # True orphan: fill after executor tracking began, but outside all windows
            orphan_fills_by_pair.setdefault(pair, []).append(fill)
            orphan_count += 1

        if orphan_count == 0:
            return

        # Create PositionHold per trading pair from orphan fills
        connector_name = all_fills[0].market if all_fills else "unknown"
        positions = self.positions_held.get(controller_id, [])
        total_orphan_volume = Decimal("0")

        for pair, fills in orphan_fills_by_pair.items():
            position = PositionHold(connector_name, pair, TradeType.BUY)
            for fill in fills:
                vol = fill.price * fill.amount
                fee = fill.trade_fee_in_quote if fill.trade_fee_in_quote else Decimal("0")
                is_buy = fill.trade_type == 'BUY'
                if is_buy:
                    position.buy_amount_base += fill.amount
                    position.buy_amount_quote += vol
                else:
                    position.sell_amount_base += fill.amount
                    position.sell_amount_quote += vol
                position.cum_fees_quote += fee
                position.volume_traded_quote += vol
                total_orphan_volume += vol

            # Set side based on net direction
            net_base = position.buy_amount_base - position.sell_amount_base
            if net_base < 0:
                position.side = TradeType.SELL
            positions.append(position)

        self.positions_held[controller_id] = positions

        total_fills = len(all_fills)
        tracked_count = total_fills - orphan_count
        self.logger().info(
            f"Orphan fill adjustment: {orphan_count}/{total_fills} fills untracked by executors "
            f"across {len(orphan_fills_by_pair)} pairs. "
            f"Orphan volume: ${float(total_orphan_volume):,.2f}. "
            f"Executor-tracked fills: {tracked_count}. "
            f"Orphan positions will be marked-to-market in performance reports."
        )

    def _update_cached_performance(self, controller_id: str, executor_info: ExecutorInfo):
        """
        Update the cached performance for a specific controller with an executor's information.
        """
        report = self.cached_performance[controller_id]
        report.realized_pnl_quote += executor_info.net_pnl_quote
        report.volume_traded += executor_info.filled_amount_quote
        if executor_info.close_type:
            report.close_type_counts[executor_info.close_type] = report.close_type_counts.get(executor_info.close_type,
                                                                                              0) + 1

    def _load_position_from_db(self, controller_id: str, db_position: Position):
        """
        Load a position from the database and recreate it as a PositionHold object.
        Since the database only stores net position data, we reconstruct the PositionHold
        with the assumption that it represents the remaining net position.
        """
        # Convert the database position back to a PositionHold object
        side = TradeType.BUY if db_position.side == "BUY" else TradeType.SELL
        position_hold = PositionHold(db_position.connector_name, db_position.trading_pair, side)

        # Set the aggregated values from the database
        position_hold.volume_traded_quote = db_position.volume_traded_quote
        position_hold.cum_fees_quote = db_position.cum_fees_quote

        # Since the database stores the net position, we need to reconstruct the buy/sell amounts
        # We assume this represents the remaining unmatched position after any realized trades
        if db_position.side == "BUY":
            # This is a net long position
            position_hold.buy_amount_base = db_position.amount
            position_hold.buy_amount_quote = db_position.amount * db_position.breakeven_price
            position_hold.sell_amount_base = Decimal("0")
            position_hold.sell_amount_quote = Decimal("0")
        else:
            # This is a net short position
            position_hold.sell_amount_base = db_position.amount
            position_hold.sell_amount_quote = db_position.amount * db_position.breakeven_price
            position_hold.buy_amount_base = Decimal("0")
            position_hold.buy_amount_quote = Decimal("0")

        # Add to positions held
        self.positions_held[controller_id].append(position_hold)

    def _create_initial_positions(self):
        """
        Create initial positions from config overrides.
        Uses NaN for quote amounts initially - they will be calculated lazily when needed.
        """
        for controller_id, initial_positions in self.initial_positions_by_controller.items():
            if controller_id not in self.cached_performance:
                self.cached_performance[controller_id] = PerformanceReport()
                self.active_executors[controller_id] = []
                self.positions_held[controller_id] = []

            for position_config in initial_positions:
                # Create PositionHold object
                position_hold = PositionHold(
                    position_config.connector_name,
                    position_config.trading_pair,
                    position_config.side
                )

                # Set amounts based on side, using NaN for quote amounts
                if position_config.side == TradeType.BUY:
                    position_hold.buy_amount_base = position_config.amount
                    position_hold.buy_amount_quote = Decimal("NaN")  # Will be calculated lazily
                    position_hold.sell_amount_base = Decimal("0")
                    position_hold.sell_amount_quote = Decimal("0")
                else:
                    position_hold.sell_amount_base = position_config.amount
                    position_hold.sell_amount_quote = Decimal("NaN")  # Will be calculated lazily
                    position_hold.buy_amount_base = Decimal("0")
                    position_hold.buy_amount_quote = Decimal("0")

                # Set fees and volume to 0 (as specified - this is a fresh start)
                position_hold.volume_traded_quote = Decimal("0")
                position_hold.cum_fees_quote = Decimal("0")

                # Add to positions held
                self.positions_held[controller_id].append(position_hold)

                self.logger().info(f"Created initial position for controller {controller_id}: {position_config.amount} "
                                   f"{position_config.side.name} {position_config.trading_pair} on {position_config.connector_name}")

    async def stop(self, max_executors_close_attempts: int = 3):
        """
        Stop the orchestrator task and all active executors.
        """
        # first we stop all active executors
        for controller_id, executors_list in self.active_executors.items():
            for executor in executors_list:
                if not executor.is_closed:
                    executor.early_stop()
        for i in range(max_executors_close_attempts):
            if all([executor.executor_info.is_done for executors_list in self.active_executors.values()
                    for executor in executors_list]):
                continue
            await asyncio.sleep(2.0)
        # Store all positions
        self.store_all_positions()
        # Clear executors and trigger garbage collection
        self.active_executors.clear()

    def store_all_positions(self):
        """
        Store or update all positions in the database.
        """
        markets_recorder = MarketsRecorder.get_instance()
        for controller_id, positions_list in self.positions_held.items():
            for position in positions_list:
                # Skip if the connector/trading pair is not in the current strategy markets
                if (position.connector_name not in self.strategy.markets or
                        position.trading_pair not in self.strategy.markets.get(position.connector_name, set())):
                    self.logger().warning(f"Skipping position storage for {position.connector_name}.{position.trading_pair} - "
                                          f"not available in current strategy markets")
                    continue
                mid_price = self.strategy.market_data_provider.get_price_by_type(
                    position.connector_name, position.trading_pair, PriceType.MidPrice)
                position_summary = position.get_position_summary(mid_price)

                # Create a Position record (id will only be used for new positions)
                position_record = Position(
                    id=str(uuid.uuid4()),
                    controller_id=controller_id,
                    connector_name=position_summary.connector_name,
                    trading_pair=position_summary.trading_pair,
                    side=position_summary.side.name,
                    timestamp=int(self.strategy.current_timestamp * 1e3),
                    volume_traded_quote=position_summary.volume_traded_quote,
                    amount=position_summary.amount,
                    breakeven_price=position_summary.breakeven_price,
                    unrealized_pnl_quote=position_summary.unrealized_pnl_quote,
                    cum_fees_quote=position_summary.cum_fees_quote,
                )
                # Store or update the position in the database
                markets_recorder.update_or_store_position(position_record)

        # Clear all positions after storing (avoid modifying list while iterating)
        self.positions_held.clear()

    def store_all_executors(self):
        for controller_id, executors_list in self.active_executors.items():
            for executor in executors_list:
                # Store the executor in the database
                MarketsRecorder.get_instance().store_or_update_executor(executor)
        # Remove the executors from the list
        self.active_executors = {}

    def _store_active_executor_snapshots(self, force: bool = False):
        """
        Persist live executor snapshots periodically.

        Executors are stored when they are created and again when they close. If
        the process exits while an executor is still active, any fills that
        arrived after creation can otherwise be present in TradeFill but absent
        from the Executors row. Keeping a throttled live snapshot prevents that
        stale state from hiding active inventory in post-run analysis.
        """
        now = time.time()
        if not force and now - self._last_active_executor_snapshot_ts < self.active_executor_snapshot_interval_sec:
            return

        recorder = MarketsRecorder.get_instance()
        stored = 0
        for executors_list in self.active_executors.values():
            for executor in executors_list:
                if executor and not executor.is_closed:
                    try:
                        recorder.store_or_update_executor(executor)
                        stored += 1
                    except Exception as exc:
                        self.logger().warning(
                            f"Could not persist live executor snapshot "
                            f"{getattr(getattr(executor, 'config', None), 'id', '?')}: {exc}"
                        )
        self._last_active_executor_snapshot_ts = now
        if stored:
            self.logger().debug(f"Persisted {stored} live executor snapshot(s)")

    def execute_action(self, action: ExecutorAction):
        """
        Execute the action and handle executors based on action type.
        """
        controller_id = action.controller_id
        if controller_id not in self.cached_performance:
            self.active_executors[controller_id] = []
            self.positions_held[controller_id] = []
            self.cached_performance[controller_id] = PerformanceReport()

        if isinstance(action, CreateExecutorAction):
            self.create_executor(action)
        elif isinstance(action, StopExecutorAction):
            self.stop_executor(action)
        elif isinstance(action, StoreExecutorAction):
            self.store_executor(action)

    def execute_actions(self, actions: List[ExecutorAction]):
        """
        Execute a list of actions.
        """
        for action in actions:
            self.execute_action(action)

    def create_executor(self, action: CreateExecutorAction):
        """
        Create an executor based on the configuration in the action.
        """
        controller_id = action.controller_id
        executor_config = action.executor_config

        # For now, we replace the controller ID in the executor config with the actual controller object to mantain
        # compa
        executor_config.controller_id = controller_id

        executor_class = self._executor_mapping.get(executor_config.type)
        if executor_class is not None:
            executor = executor_class(
                strategy=self.strategy,
                config=executor_config,
                update_interval=self.executors_update_interval,
                max_retries=self.executors_max_retries,
            )
        else:
            raise ValueError("Unsupported executor config type")

        executor.start()
        self.active_executors[controller_id].append(executor)
        try:
            MarketsRecorder.get_instance().store_or_update_executor(executor)
        except Exception as e:
            self.logger().warning(
                f"Could not store initial executor snapshot {executor.config.id}: {e}"
            )
        self.logger().debug(f"Created {type(executor).__name__} for controller {controller_id}")

    def stop_executor(self, action: StopExecutorAction):
        """
        Stop an executor based on the action details.
        """
        controller_id = action.controller_id
        executor_id = action.executor_id

        executor = next(
            (executor for executor in self.active_executors[controller_id] if executor.config.id == executor_id),
            None)
        if not executor:
            self.logger().error(f"Executor ID {executor_id} not found for controller {controller_id}.")
            return

        # 🔧 CRITICAL FIX: Wrap early_stop in try-except to ensure it completes
        # If early_stop fails, position may be left hanging without close orders
        try:
            # US-006: Pass early_stop_reason if provided in action
            early_stop_reason = getattr(action, 'early_stop_reason', None)
            executor.early_stop(action.keep_position, reason=early_stop_reason)
        except Exception as e:
            self.logger().error(
                f"❌ CRITICAL: early_stop failed for {executor_id[:8]}... with error: {e}. "
                f"Position may need manual closure! keep_position={action.keep_position}"
            )
            # Even if early_stop failed, try to force status to TERMINATED to prevent stuck executor
            try:
                executor._status = executor.RunnableStatus.TERMINATED if hasattr(executor, 'RunnableStatus') else 3
                self.logger().warning(f"⚠️  Forced executor {executor_id[:8]}... status to TERMINATED after early_stop failure")
            except Exception as status_error:
                self.logger().error(f"❌ Could not force status update: {status_error}")

    def _update_positions_from_done_executors(self):
        """
        Update positions from executors that are done but haven't been processed yet.
        This is called before generating reports to ensure position state is current.
        """
        for controller_id, executors_list in self.active_executors.items():
            # Filter executors that need position updates
            executors_to_process = [
                executor for executor in executors_list
                if (executor.executor_info.is_done and
                    executor.executor_info.close_type == CloseType.POSITION_HOLD and
                    executor.executor_info.config.id not in self.executors_ids_position_held)
            ]

            # Skip if no executors to process
            if not executors_to_process:
                continue

            positions = self.positions_held.get(controller_id, [])

            for executor in executors_to_process:
                executor_info = executor.executor_info
                self.executors_ids_position_held.append(executor_info.config.id)

                # Determine position side (handling perpetual markets)
                position_side = self._determine_position_side(executor_info)

                # Find or create position
                existing_position = self._find_existing_position(positions, executor_info, position_side)

                if existing_position:
                    existing_position.add_orders_from_executor(executor_info)
                else:
                    # Create new position
                    position = PositionHold(
                        executor_info.connector_name,
                        executor_info.trading_pair,
                        position_side if position_side else executor_info.config.side
                    )
                    position.add_orders_from_executor(executor_info)
                    positions.append(position)

    def _determine_position_side(self, executor_info: ExecutorInfo) -> Optional[TradeType]:
        """
        Determine the position side for an executor, handling perpetual markets.
        """
        is_perpetual = "_perpetual" in executor_info.connector_name
        if not is_perpetual:
            return None

        market = self.strategy.connectors.get(executor_info.connector_name)
        if not market or not hasattr(market, 'position_mode'):
            return None

        position_mode = market.position_mode
        if hasattr(executor_info.config, "position_action") and position_mode == PositionMode.HEDGE:
            opposite_side = TradeType.BUY if executor_info.config.side == TradeType.SELL else TradeType.SELL
            return opposite_side if executor_info.config.position_action == PositionAction.CLOSE else executor_info.config.side

        return executor_info.config.side

    def _find_existing_position(self, positions: List[PositionHold],
                                executor_info: ExecutorInfo,
                                position_side: Optional[TradeType]) -> Optional[PositionHold]:
        """
        Find an existing position that matches the executor's trading pair and side.
        """
        for position in positions:
            if (position.trading_pair == executor_info.trading_pair and
                    position.connector_name == executor_info.connector_name):

                # If we have a specific position side, match it
                if position_side is not None:
                    if position.side == position_side:
                        return position
                else:
                    # No specific side requirement, return first match
                    return position

        return None

    def store_executor(self, action: StoreExecutorAction):
        """
        Store executor data based on the action details and update cached performance.
        """
        controller_id = action.controller_id
        executor_id = action.executor_id

        executor = next(
            (executor for executor in self.active_executors[controller_id] if executor.config.id == executor_id),
            None)
        if not executor:
            self.logger().error(f"Executor ID {executor_id} not found for controller {controller_id}.")
            return
        if executor.is_active:
            self.logger().error(f"Executor ID {executor_id} is still active.")
            return
        try:
            MarketsRecorder.get_instance().store_or_update_executor(executor)
            self._update_cached_performance(controller_id, executor.executor_info)
        except Exception as e:
            self.logger().error(f"Error storing executor id {executor_id}: {str(e)}.")
            self.logger().error(f"Executor info: {executor.executor_info} | Config: {executor.config}")

        self.active_executors[controller_id].remove(executor)
        del executor
        # Trigger garbage collection after executor cleanup

    def get_executors_report(self) -> Dict[str, List[ExecutorInfo]]:
        """
        Generate a report of all executors.
        """
        self._store_active_executor_snapshots()
        report = {}
        for controller_id, executors_list in self.active_executors.items():
            report[controller_id] = [executor.executor_info for executor in executors_list if executor]
        return report

    def get_positions_report(self) -> Dict[str, List[PositionSummary]]:
        """
        Generate a report of all positions held.
        """
        report = {}
        for controller_id, positions_list in self.positions_held.items():
            positions_summary = []
            for position in positions_list:
                try:
                    mid_price = self.strategy.market_data_provider.get_price_by_type(
                        position.connector_name, position.trading_pair, PriceType.MidPrice)
                except (ValueError, KeyError):
                    # Pair not in subscribed markets (e.g. orphan PositionHold) — skip
                    continue
                positions_summary.append(position.get_position_summary(mid_price))
            report[controller_id] = positions_summary
        return report

    def get_all_reports(self) -> Dict[str, Dict]:
        """
        Generate a unified report containing executors, positions, and performance for all controllers.
        Returns a dictionary with controller_id as key and a dict containing all reports as value.
        """
        # Update any pending position holds from done executors
        self._update_positions_from_done_executors()

        # Generate all reports
        executors_report = self.get_executors_report()
        positions_report = self.get_positions_report()

        # Get all controller IDs
        all_controller_ids = set(list(self.active_executors.keys()) +
                                 list(self.positions_held.keys()) +
                                 list(self.cached_performance.keys()))

        # Use dict comprehension to compile reports for each controller
        return {
            controller_id: {
                "executors": executors_report.get(controller_id, []),
                "positions": positions_report.get(controller_id, []),
                "performance": self.generate_performance_report(controller_id)
            }
            for controller_id in all_controller_ids
        }

    def generate_performance_report(self, controller_id: str) -> PerformanceReport:
        self._store_active_executor_snapshots()

        # Create a new report starting from cached base values
        report = PerformanceReport()
        cached_report = self.cached_performance.get(controller_id, PerformanceReport())

        # Start with cached values (from DB)
        report.realized_pnl_quote = cached_report.realized_pnl_quote
        report.volume_traded = cached_report.volume_traded
        report.close_type_counts = cached_report.close_type_counts.copy() if cached_report.close_type_counts else {}

        # Add data from active executors
        active_executors = self.active_executors.get(controller_id, [])
        positions = self.positions_held.get(controller_id, [])

        for executor in active_executors:
            executor_info = executor.executor_info
            if not executor_info.is_done:
                report.unrealized_pnl_quote += executor_info.net_pnl_quote
            else:
                report.realized_pnl_quote += executor_info.net_pnl_quote
                if executor_info.close_type:
                    report.close_type_counts[executor_info.close_type] = report.close_type_counts.get(executor_info.close_type, 0) + 1

            report.volume_traded += executor_info.filled_amount_quote

        # Add data from positions held and collect position summaries
        positions_summary = []
        for position in positions:
            # Skip if the connector/trading pair is not in the current strategy markets
            if (position.connector_name not in self.strategy.markets or
                    position.trading_pair not in self.strategy.markets.get(position.connector_name, set())):
                pair_key = f"{position.connector_name}.{position.trading_pair}"
                if pair_key not in self._skipped_position_pairs:
                    self._skipped_position_pairs.add(pair_key)
                    self.logger().warning(f"Skipping position for {pair_key} - not in strategy markets (logged once)")
                continue
            try:
                mid_price = self.strategy.market_data_provider.get_price_by_type(
                    position.connector_name, position.trading_pair, PriceType.MidPrice)
            except (ValueError, KeyError):
                # Order book not yet loaded during startup
                continue
            position_summary = position.get_position_summary(mid_price if not mid_price.is_nan() else Decimal("0"))

            # Update report with position data
            report.realized_pnl_quote += position_summary.realized_pnl_quote - position_summary.cum_fees_quote
            report.volume_traded += position_summary.volume_traded_quote
            report.unrealized_pnl_quote += position_summary.unrealized_pnl_quote
            positions_summary.append(position_summary)

        # Set the positions summary (don't use dynamic attribute)
        report.positions_summary = positions_summary

        # Calculate global PNL values
        report.global_pnl_quote = report.unrealized_pnl_quote + report.realized_pnl_quote
        report.global_pnl_pct = (report.global_pnl_quote / report.volume_traded) * 100 if report.volume_traded != 0 else Decimal(0)

        # Calculate individual PNL percentages
        report.unrealized_pnl_pct = (report.unrealized_pnl_quote / report.volume_traded) * 100 if report.volume_traded != 0 else Decimal(0)
        report.realized_pnl_pct = (report.realized_pnl_quote / report.volume_traded) * 100 if report.volume_traded != 0 else Decimal(0)

        return report
