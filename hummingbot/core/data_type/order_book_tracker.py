import asyncio
import logging
import time
from collections import defaultdict, deque
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

import pandas as pd

from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.event.events import OrderBookTradeEvent
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger


class OrderBookTrackerDataSourceType(Enum):
    REMOTE_API = 2
    EXCHANGE_API = 3


class OrderBookTracker:
    PAST_DIFF_WINDOW_SIZE: int = 32
    _obt_logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._obt_logger is None:
            cls._obt_logger = logging.getLogger(__name__)
        return cls._obt_logger

    def __init__(self, data_source: OrderBookTrackerDataSource, trading_pairs: List[str], domain: Optional[str] = None):
        self._domain: Optional[str] = domain
        self._data_source: OrderBookTrackerDataSource = data_source
        self._trading_pairs: List[str] = trading_pairs
        self._order_books_initialized: asyncio.Event = asyncio.Event()
        self._tracking_tasks: Dict[str, asyncio.Task] = {}
        self._order_books: Dict[str, OrderBook] = {}
        self._tracking_message_queues: Dict[str, asyncio.Queue] = {}
        self._past_diffs_windows: Dict[str, Deque] = defaultdict(lambda: deque(maxlen=self.PAST_DIFF_WINDOW_SIZE))
        # FIX: Bounded queues to prevent memory leak (was unbounded asyncio.Queue())
        self._order_book_diff_stream: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._order_book_snapshot_stream: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._order_book_trade_stream: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._ev_loop: asyncio.BaseEventLoop = asyncio.get_event_loop()
        self._saved_message_queues: Dict[str, Deque[OrderBookMessage]] = defaultdict(lambda: deque(maxlen=1000))
        self._book_initialization_tasks: Dict[str, asyncio.Task] = {}
        self._book_recovery_tasks: Dict[str, asyncio.Task] = {}
        self._book_generations: Dict[str, object] = {}
        self._resync_min_update_id: Dict[str, int] = {}

        self._emit_trade_event_task: Optional[asyncio.Task] = None
        self._init_order_books_task: Optional[asyncio.Task] = None
        self._order_book_diff_listener_task: Optional[asyncio.Task] = None
        self._order_book_trade_listener_task: Optional[asyncio.Task] = None
        self._order_book_snapshot_listener_task: Optional[asyncio.Task] = None
        self._order_book_diff_router_task: Optional[asyncio.Task] = None
        self._order_book_snapshot_router_task: Optional[asyncio.Task] = None
        self._update_last_trade_prices_task: Optional[asyncio.Task] = None
        self._order_book_stream_listener_task: Optional[asyncio.Task] = None

    @property
    def data_source(self) -> OrderBookTrackerDataSource:
        return self._data_source

    @property
    def order_books(self) -> Dict[str, OrderBook]:
        return self._order_books

    @property
    def ready(self) -> bool:
        return self._order_books_initialized.is_set()

    @property
    def snapshot(self) -> Dict[str, Tuple[pd.DataFrame, pd.DataFrame]]:
        return {
            trading_pair: order_book.snapshot
            for trading_pair, order_book in self._order_books.items()
        }

    def start(self):
        self.stop()
        self._init_order_books_task = safe_ensure_future(
            self._init_order_books()
        )
        self._emit_trade_event_task = safe_ensure_future(
            self._emit_trade_event_loop()
        )
        self._order_book_diff_listener_task = safe_ensure_future(
            self._data_source.listen_for_order_book_diffs(self._ev_loop, self._order_book_diff_stream)
        )
        self._order_book_trade_listener_task = safe_ensure_future(
            self._data_source.listen_for_trades(self._ev_loop, self._order_book_trade_stream)
        )
        self._order_book_snapshot_listener_task = safe_ensure_future(
            self._data_source.listen_for_order_book_snapshots(self._ev_loop, self._order_book_snapshot_stream)
        )
        self._order_book_stream_listener_task = safe_ensure_future(
            self._data_source.listen_for_subscriptions()
        )
        self._order_book_diff_router_task = safe_ensure_future(
            self._order_book_diff_router()
        )
        self._order_book_snapshot_router_task = safe_ensure_future(
            self._order_book_snapshot_router()
        )
        self._update_last_trade_prices_task = safe_ensure_future(
            self._update_last_trade_prices_loop()
        )

    def stop(self):
        if self._init_order_books_task is not None:
            self._init_order_books_task.cancel()
            self._init_order_books_task = None
        if self._emit_trade_event_task is not None:
            self._emit_trade_event_task.cancel()
            self._emit_trade_event_task = None
        if self._order_book_diff_listener_task is not None:
            self._order_book_diff_listener_task.cancel()
            self._order_book_diff_listener_task = None
        if self._order_book_snapshot_listener_task is not None:
            self._order_book_snapshot_listener_task.cancel()
            self._order_book_snapshot_listener_task = None
        if self._order_book_trade_listener_task is not None:
            self._order_book_trade_listener_task.cancel()
            self._order_book_trade_listener_task = None

        if self._order_book_diff_router_task is not None:
            self._order_book_diff_router_task.cancel()
            self._order_book_diff_router_task = None
        if self._order_book_snapshot_router_task is not None:
            self._order_book_snapshot_router_task.cancel()
            self._order_book_snapshot_router_task = None
        if self._update_last_trade_prices_task is not None:
            self._update_last_trade_prices_task.cancel()
            self._update_last_trade_prices_task = None
        if self._order_book_stream_listener_task is not None:
            self._order_book_stream_listener_task.cancel()
            self._order_book_stream_listener_task = None
        if len(self._tracking_tasks) > 0:
            for _, task in self._tracking_tasks.items():
                task.cancel()
            self._tracking_tasks.clear()
        for task in list(self._book_initialization_tasks.values()) + list(self._book_recovery_tasks.values()):
            task.cancel()
        self._book_initialization_tasks.clear()
        self._book_recovery_tasks.clear()
        self._book_generations.clear()
        for book in self._order_books.values():
            book.apply_snapshot([], [], 0)
        self._order_books.clear()
        self._tracking_message_queues.clear()
        self._saved_message_queues.clear()
        self._past_diffs_windows.clear()
        self._resync_min_update_id.clear()
        for queue in (self._order_book_diff_stream, self._order_book_snapshot_stream, self._order_book_trade_stream):
            while not queue.empty():
                queue.get_nowait()
        self._order_books_initialized.clear()

    def remove_trading_pair(self, trading_pair: str) -> None:
        for pairs in (self._trading_pairs, self._data_source._trading_pairs):
            while trading_pair in pairs:
                pairs.remove(trading_pair)
        for tasks in (self._tracking_tasks, self._book_initialization_tasks, self._book_recovery_tasks):
            task = tasks.pop(trading_pair, None)
            if task is not None:
                task.cancel()
        self._book_generations.pop(trading_pair, None)
        book = self._order_books.pop(trading_pair, None)
        if book is not None:
            book.apply_snapshot([], [], 0)
        self._tracking_message_queues.pop(trading_pair, None)
        self._saved_message_queues.pop(trading_pair, None)
        self._past_diffs_windows.pop(trading_pair, None)
        self._resync_min_update_id.pop(trading_pair, None)

    def is_order_book_valid(self, trading_pair: str) -> bool:
        task = self._tracking_tasks.get(trading_pair)
        return (
            trading_pair in self._trading_pairs and trading_pair in self._order_books
            and task is not None and not task.done() and not task.cancelling()
        )

    async def initialize_order_book(self, trading_pair: str) -> Optional[OrderBook]:
        """One snapshot/consumer per membership generation, including dynamic pairs."""
        if trading_pair not in self._trading_pairs:
            return None
        if self.is_order_book_valid(trading_pair):
            return self._order_books[trading_pair]
        task = self._book_initialization_tasks.get(trading_pair)
        if task is None or task.done():
            generation = self._book_generations.setdefault(trading_pair, object())
            task = safe_ensure_future(self._initialize_order_book(trading_pair, generation))
            self._book_initialization_tasks[trading_pair] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._book_initialization_tasks.get(trading_pair) is task:
                self._book_initialization_tasks.pop(trading_pair)

    async def _initialize_order_book(self, trading_pair: str, generation: object) -> Optional[OrderBook]:
        book = await self._initial_order_book_for_trading_pair(trading_pair)
        if trading_pair not in self._trading_pairs or self._book_generations.get(trading_pair) is not generation:
            return None
        if book.snapshot_uid < self._resync_min_update_id.get(trading_pair, 0):
            raise IOError(f"Snapshot for {trading_pair} predates lost order book updates")
        # Replay only updates newer than the connector's fresh REST snapshot.
        # The connector supplies its own snapshot format/update-id semantics.
        past_diffs: List[OrderBookMessage] = []
        saved = list(self._saved_message_queues.pop(trading_pair, ()))
        if any(m.content.get("sequence_gap") and m.update_id > book.snapshot_uid for m in saved):
            # The connector saw lost updates after this snapshot; require a newer one.
            self._resync_min_update_id[trading_pair] = max(
                [m.update_id for m in saved] + [self._resync_min_update_id.get(trading_pair, 0)])
            raise IOError(f"Order book updates for {trading_pair} were lost after the snapshot")
        for message in saved:
            if message.type is OrderBookMessageType.DIFF and message.update_id > book.snapshot_uid:
                book.apply_diffs(message.bids, message.asks, message.update_id)
                past_diffs.append(message)
            elif message.type is OrderBookMessageType.SNAPSHOT and message.update_id >= book.snapshot_uid:
                book.restore_from_snapshot_and_diffs(message, past_diffs)
        self._order_books[trading_pair] = book
        self.ensure_tracking_task(trading_pair)
        self._past_diffs_windows[trading_pair].extend(past_diffs)
        self._resync_min_update_id.pop(trading_pair, None)
        return book

    def ensure_tracking_task(self, trading_pair: str) -> None:
        if self.is_order_book_valid(trading_pair):
            return
        if trading_pair not in self._trading_pairs or trading_pair not in self._order_books:
            return
        task = self._tracking_tasks.pop(trading_pair, None)
        if task is not None:
            task.cancel()
        self._tracking_message_queues[trading_pair] = asyncio.Queue(maxsize=5000)
        self._past_diffs_windows.pop(trading_pair, None)
        self._saved_message_queues.pop(trading_pair, None)
        self._tracking_tasks[trading_pair] = safe_ensure_future(self._track_single_book(trading_pair))
        self.logger().info("[ORDERBOOK] Live book tracking registered for %s", trading_pair)

    def _invalidate_order_book(self, trading_pair: str, reason: str, lost_update_id: int = 0) -> None:
        self.logger().warning("[ORDERBOOK_INVALID] pair=%s reason=%s; requesting fresh snapshot", trading_pair, reason)
        book = self._order_books.pop(trading_pair, None)
        if book is not None:
            book.apply_snapshot([], [], 0)  # Cached references must not expose stale depth either.
        task = self._tracking_tasks.pop(trading_pair, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        queue = self._tracking_message_queues.pop(trading_pair, None)
        if queue is not None:
            while not queue.empty():
                lost_update_id = max(lost_update_id, queue.get_nowait().update_id)
        self._past_diffs_windows.pop(trading_pair, None)
        for message in self._saved_message_queues.pop(trading_pair, ()):
            lost_update_id = max(lost_update_id, message.update_id)
        self._book_generations[trading_pair] = object()
        self._resync_min_update_id[trading_pair] = max(
            lost_update_id, self._resync_min_update_id.get(trading_pair, 0))
        recovery = self._book_recovery_tasks.get(trading_pair)
        if recovery is None or recovery.done():
            self._book_recovery_tasks[trading_pair] = safe_ensure_future(self._recover_order_book(trading_pair))

    async def _recover_order_book(self, trading_pair: str) -> None:
        while trading_pair in self._trading_pairs:
            try:
                if await self.initialize_order_book(trading_pair) is not None:
                    self.logger().info("[ORDERBOOK_RECOVERED] pair=%s", trading_pair)
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Order book recovery failed for %s; retrying in 5 seconds", trading_pair)
            await self._sleep(5.0)

    def _buffer_order_book_message(self, message: OrderBookMessage) -> None:
        trading_pair = message.trading_pair
        if trading_pair in self._order_books:
            self._invalidate_order_book(trading_pair, "order book without consumer", message.update_id)
        saved = self._saved_message_queues[trading_pair]
        if len(saved) == saved.maxlen:
            self._invalidate_order_book(trading_pair, "initialization buffer full",
                                        max(msg.update_id for msg in saved))
        self._saved_message_queues[trading_pair].append(message)

    async def wait_ready(self):
        await self._order_books_initialized.wait()

    async def _update_last_trade_prices_loop(self):
        '''
        Updates last trade price for all order books through REST API, it is to initiate last_trade_price and as
        fall-back mechanism for when the web socket update channel fails.
        '''
        await self._order_books_initialized.wait()
        while True:
            try:
                outdateds = [t_pair for t_pair, o_book in self._order_books.items()
                             if o_book.last_applied_trade < time.perf_counter() - (60. * 3)
                             and o_book.last_trade_price_rest_updated < time.perf_counter() - 5]
                if outdateds:
                    args = {"trading_pairs": outdateds}
                    if self._domain is not None:
                        args["domain"] = self._domain
                    last_prices = await self._data_source.get_last_traded_prices(**args)
                    for trading_pair, last_price in last_prices.items():
                        if trading_pair not in self._order_books:
                            # Some connectors may return cached prices for additional pairs.
                            # Ignore untracked pairs to avoid crashing the refresh loop.
                            continue
                        self._order_books[trading_pair].last_trade_price = last_price
                        self._order_books[trading_pair].last_trade_price_rest_updated = time.perf_counter()
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network("Unexpected error while fetching last trade price.", exc_info=True)
                await asyncio.sleep(30)

    async def _initial_order_book_for_trading_pair(self, trading_pair: str) -> OrderBook:
        return await self._data_source.get_new_order_book(trading_pair)

    async def _init_order_books(self):
        """
        Initialize order books
        """
        attempted: Dict[str, object] = {}
        while pending := [
            pair for pair in list(self._trading_pairs)
            if (pair not in attempted or attempted[pair] is not self._book_generations.get(pair))
            and (pair not in self._book_recovery_tasks or self._book_recovery_tasks[pair].done())
        ]:
            for trading_pair in pending:
                attempted[trading_pair] = self._book_generations.setdefault(trading_pair, object())
                try:
                    book = await self.initialize_order_book(trading_pair)
                except asyncio.CancelledError:
                    current_task = asyncio.current_task()
                    if current_task is not None and current_task.cancelling():
                        raise
                    continue
                except Exception:
                    self.logger().exception("Initial order book failed for %s", trading_pair)
                    self._invalidate_order_book(trading_pair, "initial snapshot failed")
                    continue
                if book is not None:
                    self.logger().info(f"Initialized order book for {trading_pair}. "
                                       f"{len(self._order_books)}/{len(self._trading_pairs)} completed.")
                await self._sleep(delay=1)
        for trading_pair in set(self._order_books) | set(self._book_generations):
            if trading_pair not in self._trading_pairs:
                self.remove_trading_pair(trading_pair)
        self._order_books_initialized.set()

    async def _order_book_diff_router(self):
        """
        Routes the real-time order book diff messages to the correct order book.
        """
        last_message_timestamp: float = time.time()
        messages_queued: int = 0
        messages_accepted: int = 0
        messages_rejected: int = 0

        while True:
            try:
                ob_message: OrderBookMessage = await self._order_book_diff_stream.get()
                trading_pair: str = ob_message.trading_pair

                if trading_pair not in self._trading_pairs:
                    continue
                if trading_pair not in self._tracking_message_queues:
                    messages_queued += 1
                    self._buffer_order_book_message(ob_message)
                    continue
                message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
                # Check the order book's initial update ID. If it's larger, don't bother.
                if trading_pair not in self._order_books:
                    self._invalidate_order_book(trading_pair, "queue without order book", ob_message.update_id)
                    continue
                order_book: OrderBook = self._order_books[trading_pair]

                if order_book.snapshot_uid > ob_message.update_id:
                    messages_rejected += 1
                    continue
                if message_queue.full() or not self.is_order_book_valid(trading_pair):
                    self._invalidate_order_book(trading_pair, "pair queue full or consumer missing", ob_message.update_id)
                    continue
                message_queue.put_nowait(ob_message)
                messages_accepted += 1

                # Log some statistics.
                now: float = time.time()
                if int(now / 60.0) > int(last_message_timestamp / 60.0):
                    self.logger().debug(f"Diff messages processed: {messages_accepted}, "
                                        f"rejected: {messages_rejected}, queued: {messages_queued}")
                    messages_accepted = 0
                    messages_rejected = 0
                    messages_queued = 0

                last_message_timestamp = now
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unexpected error routing order book messages.",
                    exc_info=True,
                    app_warning_msg="Unexpected error routing order book messages. Retrying after 5 seconds."
                )
                await asyncio.sleep(5.0)

    async def _order_book_snapshot_router(self):
        """
        Route the real-time order book snapshot messages to the correct order book.
        """
        while True:
            try:
                ob_message: OrderBookMessage = await self._order_book_snapshot_stream.get()
                trading_pair: str = ob_message.trading_pair
                if trading_pair not in self._trading_pairs:
                    continue
                if trading_pair not in self._tracking_message_queues:
                    self._buffer_order_book_message(ob_message)
                    continue
                message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
                if message_queue.full() or not self.is_order_book_valid(trading_pair):
                    self._invalidate_order_book(trading_pair, "snapshot queue full or consumer missing",
                                                ob_message.update_id)
                    continue
                message_queue.put_nowait(ob_message)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unknown error. Retrying after 5 seconds.", exc_info=True)
                await asyncio.sleep(5.0)

    async def _track_single_book(self, trading_pair: str):
        past_diffs_window = self._past_diffs_windows[trading_pair]

        message_queue: asyncio.Queue = self._tracking_message_queues[trading_pair]
        order_book: OrderBook = self._order_books[trading_pair]
        last_message_timestamp: float = time.time()
        diff_messages_accepted: int = 0

        while True:
            try:
                saved_messages: Deque[OrderBookMessage] = self._saved_message_queues[trading_pair]

                # Process saved messages first if there are any
                if len(saved_messages) > 0:
                    message = saved_messages.popleft()
                else:
                    message = await message_queue.get()

                if message.type is OrderBookMessageType.DIFF and message.content.get("sequence_gap"):
                    self._invalidate_order_book(trading_pair, "update sequence gap", message.update_id)
                    return
                if message.type is OrderBookMessageType.DIFF:
                    order_book.apply_diffs(message.bids, message.asks, message.update_id)
                    past_diffs_window.append(message)
                    diff_messages_accepted += 1

                    # Output some statistics periodically.
                    now: float = time.time()
                    if int(now / 60.0) > int(last_message_timestamp / 60.0):
                        self.logger().debug(f"Processed {diff_messages_accepted} order book diffs for {trading_pair}.")
                        diff_messages_accepted = 0
                    last_message_timestamp = now
                elif message.type is OrderBookMessageType.SNAPSHOT:
                    past_diffs: List[OrderBookMessage] = list(past_diffs_window)
                    order_book.restore_from_snapshot_and_diffs(message, past_diffs)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    f"Unexpected error tracking order book for {trading_pair}.",
                    exc_info=True,
                    app_warning_msg="Order book invalid; recovering from a fresh snapshot."
                )
                self._invalidate_order_book(trading_pair, "failed to apply order book update", message.update_id)
                return

    async def _emit_trade_event_loop(self):
        last_message_timestamp: float = time.time()
        messages_accepted: int = 0
        messages_rejected: int = 0
        await self._order_books_initialized.wait()
        while True:
            try:
                trade_message: OrderBookMessage = await self._order_book_trade_stream.get()
                trading_pair: str = trade_message.trading_pair

                if trading_pair not in self._order_books:
                    messages_rejected += 1
                    continue

                order_book: OrderBook = self._order_books[trading_pair]
                order_book.apply_trade(OrderBookTradeEvent(
                    trading_pair=trade_message.trading_pair,
                    timestamp=trade_message.timestamp,
                    price=float(trade_message.content["price"]),
                    amount=float(trade_message.content["amount"]),
                    trade_id=trade_message.trade_id,
                    type=TradeType.SELL if
                    trade_message.content["trade_type"] == float(TradeType.SELL.value) else TradeType.BUY
                ))

                messages_accepted += 1

                # Log some statistics.
                now: float = time.time()
                if int(now / 60.0) > int(last_message_timestamp / 60.0):
                    self.logger().debug(f"Trade messages processed: {messages_accepted}, rejected: {messages_rejected}")
                    messages_accepted = 0
                    messages_rejected = 0

                last_message_timestamp = now
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unexpected error routing order book messages.",
                    exc_info=True,
                    app_warning_msg="Unexpected error routing order book messages. Retrying after 5 seconds."
                )
                await asyncio.sleep(5.0)

    @staticmethod
    async def _sleep(delay: float):
        await asyncio.sleep(delay=delay)
