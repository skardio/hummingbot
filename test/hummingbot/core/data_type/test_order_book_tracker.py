import asyncio
from collections import deque
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from unittest.mock import AsyncMock, MagicMock

from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker import OrderBookTracker


def message(pair, uid=2, kind=OrderBookMessageType.DIFF):
    return OrderBookMessage(kind, {
        "trading_pair": pair, "update_id": uid, "bids": [["10", "1"]], "asks": [["11", "1"]],
    }, timestamp=uid)


def book(uid=1):
    result = OrderBook()
    snapshot = message("", uid, OrderBookMessageType.SNAPSHOT)
    result.apply_snapshot(snapshot.bids, snapshot.asks, uid)
    return result


class OrderBookTrackerLifecycleTests(IsolatedAsyncioWrapperTestCase):
    async def asyncSetUp(self):
        self.pairs = ["BTC-USDT", "ICNT-USDT", "ARX-USDT", "MMT-USDT", "BREV-USDT"]
        self.source = MagicMock()
        self.source._trading_pairs = self.pairs
        self.source.get_new_order_book = AsyncMock(side_effect=lambda pair: book())
        self.tracker = OrderBookTracker(self.source, self.pairs)
        self.tracker._sleep = AsyncMock()
        self.tasks = []

    async def asyncTearDown(self):
        self.tracker.stop()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await asyncio.sleep(0)

    async def settle(self):
        for _ in range(30):
            await asyncio.sleep(0)

    async def test_reconnect_rotation_does_not_skip_mmt_or_block_btc(self):
        await self.tracker._init_order_books()
        await self.settle()
        old_tasks = list(self.tracker._tracking_tasks.values())
        self.tracker.stop()
        await asyncio.gather(*old_tasks, return_exceptions=True)
        # A stale MMT queue survived stop() in the incident. Keep this queue tiny
        # to reproduce the 5,000-message backlog without thousands of iterations.
        if "MMT-USDT" in self.tracker._tracking_message_queues:
            self.tracker._tracking_message_queues["MMT-USDT"] = asyncio.Queue(maxsize=1)

        async def snapshot(pair):
            if pair == "ARX-USDT":
                self.pairs.remove("ICNT-USDT")
                self.pairs.append("NES-USDT")
            return book()

        self.source.get_new_order_book.side_effect = snapshot
        await self.tracker._init_order_books()
        await self.settle()
        router = asyncio.create_task(self.tracker._order_book_diff_router())
        self.tasks.append(router)
        for pair in ("MMT-USDT", "MMT-USDT", "BTC-USDT"):
            self.tracker._order_book_diff_stream.put_nowait(message(pair))
        await self.settle()
        # Old code leaves MMT without a consumer and BTC stuck behind its queue.
        assert self.tracker._order_books["BTC-USDT"].last_diff_uid == 2, (
            "MMT has no active consumer; its full pair queue blocks BTC in the shared router"
        )
        assert all(not self.tracker._tracking_tasks[p].done() for p in self.pairs)
        assert set(self.tracker._tracking_tasks) == set(self.pairs)
        assert set(self.tracker._order_books) == set(self.pairs)

    async def test_pair_removed_during_snapshot_is_not_registered(self):
        async def snapshot(pair):
            if pair == "ICNT-USDT":
                self.pairs.remove(pair)
                self.pairs.append("NES-USDT")
                await asyncio.sleep(0)
            return book()

        self.source.get_new_order_book.side_effect = snapshot
        await self.tracker._init_order_books()
        assert "ICNT-USDT" not in self.tracker._order_books
        assert "ICNT-USDT" not in self.tracker._tracking_tasks
        assert set(self.tracker._order_books) == set(self.pairs)

    async def test_full_pair_queue_invalidates_and_recovers_without_blocking_btc(self):
        release_consumer = asyncio.Event()
        release_snapshot = asyncio.Event()
        original_consumer = self.tracker._track_single_book

        async def consumer(pair):
            if pair == "MMT-USDT":
                await release_consumer.wait()
            await original_consumer(pair)

        self.tracker._track_single_book = consumer
        await self.tracker._init_order_books()
        await self.settle()
        old_book = self.tracker._order_books["MMT-USDT"]
        old_consumer = self.tracker._tracking_tasks["MMT-USDT"]
        queue = self.tracker._tracking_message_queues["MMT-USDT"]
        for _ in range(queue.maxsize):
            queue.put_nowait(message("MMT-USDT", 2))

        async def fresh_snapshot(pair):
            await release_snapshot.wait()
            return book(10)

        self.source.get_new_order_book.side_effect = fresh_snapshot
        self.tasks.append(asyncio.create_task(self.tracker._order_book_diff_router()))
        self.tasks.append(asyncio.create_task(self.tracker._order_book_snapshot_router()))
        self.tracker._order_book_diff_stream.put_nowait(message("MMT-USDT", 3))
        self.tracker._order_book_diff_stream.put_nowait(message("BTC-USDT", 3))
        await self.settle()
        assert self.tracker._order_books["BTC-USDT"].last_diff_uid == 3
        assert not self.tracker.is_order_book_valid("MMT-USDT")
        assert "MMT-USDT" not in self.tracker.order_books
        assert list(old_book.bid_entries()) == []  # Cached references cannot price orders.
        assert old_consumer.cancelled()

        # A diff received during recovery must be replayed after the REST snapshot.
        self.tracker._order_book_diff_stream.put_nowait(message("MMT-USDT", 11))
        self.tracker._order_book_snapshot_stream.put_nowait(
            message("MMT-USDT", 12, OrderBookMessageType.SNAPSHOT))
        self.tracker._order_book_diff_stream.put_nowait(message("MMT-USDT", 13))
        await self.settle()
        release_consumer.set()
        release_snapshot.set()
        await self.settle()
        assert self.tracker.is_order_book_valid("MMT-USDT")
        assert self.tracker._order_books["MMT-USDT"].snapshot_uid == 12
        assert self.tracker._order_books["MMT-USDT"].last_diff_uid == 13
        assert self.tracker._tracking_tasks["MMT-USDT"] is not old_consumer

    async def test_unsubscribe_resubscribe_cancels_old_snapshot_and_consumer(self):
        await self.tracker._init_order_books()
        await self.settle()
        pair = "ICNT-USDT"
        old_consumer = self.tracker._tracking_tasks[pair]
        old_book = self.tracker._order_books[pair]
        self.tracker.remove_trading_pair(pair)
        self.pairs.append(pair)
        gate = asyncio.Event()
        started = asyncio.Event()

        async def delayed_snapshot(pair):
            started.set()
            await gate.wait()
            return book(10)

        self.source.get_new_order_book.side_effect = delayed_snapshot
        old_init = asyncio.create_task(self.tracker.initialize_order_book(pair))
        self.tasks.append(old_init)
        await started.wait()
        self.tracker.remove_trading_pair(pair)
        self.pairs.append(pair)
        self.source.get_new_order_book.side_effect = lambda pair: book(20)
        new_book, same_book = await asyncio.gather(
            self.tracker.initialize_order_book(pair), self.tracker.initialize_order_book(pair))
        gate.set()
        await self.settle()
        assert old_init.cancelled()
        assert old_consumer.cancelled()
        assert list(old_book.bid_entries()) == []
        assert new_book is same_book is self.tracker.order_books[pair]
        assert new_book.snapshot_uid == 20
        consumer = self.tracker._tracking_tasks[pair]
        self.tracker.ensure_tracking_task(pair)
        assert consumer is self.tracker._tracking_tasks[pair]
        assert not consumer.done()
        self.tracker.remove_trading_pair(pair)
        await self.settle()
        assert consumer.cancelled()
        for state in (self.tracker._tracking_message_queues, self.tracker._saved_message_queues,
                      self.tracker._past_diffs_windows, self.tracker._book_initialization_tasks):
            assert pair not in state

    async def test_resubscribe_during_reconnect_cannot_publish_old_membership_snapshot(self):
        started = asyncio.Event()
        calls = 0

        async def snapshot(pair):
            nonlocal calls
            if pair == "ICNT-USDT":
                calls += 1
                if calls == 1:
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        return book(1)  # Simulate an in-flight response completing after removal.
            return book(20)

        self.source.get_new_order_book.side_effect = snapshot
        init = asyncio.create_task(self.tracker._init_order_books())
        self.tasks.append(init)
        await started.wait()
        self.tracker.remove_trading_pair("ICNT-USDT")
        self.pairs.append("ICNT-USDT")
        await init
        assert calls == 2
        assert self.tracker.is_order_book_valid("ICNT-USDT")
        assert self.tracker.order_books["ICNT-USDT"].snapshot_uid == 20
        assert all(self.tracker.is_order_book_valid(pair) for pair in self.pairs)

    async def test_lost_updates_require_snapshot_at_least_as_new_and_retry_failure(self):
        await self.tracker._init_order_books()
        retry = asyncio.Queue()

        async def wait_retry(*args):
            await retry.get()

        self.tracker._sleep = AsyncMock(side_effect=wait_retry)
        self.source.get_new_order_book.side_effect = [OSError("snapshot unavailable"), book(2), book(10)]
        pair = "MMT-USDT"
        self.tracker._invalidate_order_book(pair, "lost update", 3)
        await self.settle()
        assert pair not in self.tracker.order_books
        assert not self.tracker.is_order_book_valid(pair)
        # Release only one retry, then pause again after the stale snapshot.
        retry.put_nowait(None)
        await self.settle()
        assert pair not in self.tracker.order_books
        assert not self.tracker.is_order_book_valid(pair)
        retry.put_nowait(None)
        await self.settle()
        assert self.tracker.is_order_book_valid(pair)
        assert self.tracker.order_books[pair].snapshot_uid == 10

    async def test_initialization_buffer_overflow_invalidates_instead_of_losing_diffs_silently(self):
        pair = "MMT-USDT"
        self.tracker._saved_message_queues[pair] = deque(maxlen=1)
        self.tracker._saved_message_queues[pair].append(message(pair, 2))
        gate = asyncio.Event()

        async def fresh_snapshot(pair):
            await gate.wait()
            return book(10)

        self.source.get_new_order_book.side_effect = fresh_snapshot
        self.tracker.logger = MagicMock()
        self.tasks.append(asyncio.create_task(self.tracker._order_book_diff_router()))
        self.tracker._order_book_diff_stream.put_nowait(message(pair, 3))
        await self.settle()
        assert self.tracker._resync_min_update_id[pair] == 2
        assert not self.tracker.is_order_book_valid(pair)
        assert self.tracker.logger().warning.call_args.args[2] == "initialization buffer full"
        gate.set()
        await self.settle()
        assert self.tracker.is_order_book_valid(pair)
        assert self.tracker.order_books[pair].snapshot_uid == 10

    async def test_connector_sequence_gap_invalidates_and_recovers_from_fresh_snapshot(self):
        await self.tracker._init_order_books()
        await self.settle()
        pair = "MMT-USDT"
        old_book = self.tracker._order_books[pair]
        old_consumer = self.tracker._tracking_tasks[pair]
        gate = asyncio.Event()
        snapshots = iter([book(5), book(30)])

        async def fresh_snapshot(pair):
            await gate.wait()
            return next(snapshots)

        retry = asyncio.Queue()

        async def wait_retry(*args):
            await retry.get()

        self.tracker._sleep = AsyncMock(side_effect=wait_retry)
        self.source.get_new_order_book.side_effect = fresh_snapshot
        self.tasks.append(asyncio.create_task(self.tracker._order_book_diff_router()))
        gap = message(pair, 4)
        gap.content["sequence_gap"] = True
        self.tracker._order_book_diff_stream.put_nowait(message(pair, 3))
        self.tracker._order_book_diff_stream.put_nowait(gap)
        self.tracker._order_book_diff_stream.put_nowait(message("BTC-USDT", 3))
        await self.settle()
        # The gapped diff is never applied; the book is invalid until a fresh snapshot arrives.
        assert old_book.last_diff_uid == 3
        assert list(old_book.bid_entries()) == []
        assert not self.tracker.is_order_book_valid(pair)
        assert pair not in self.tracker.order_books
        assert old_consumer.done()
        assert self.tracker._order_books["BTC-USDT"].last_diff_uid == 3
        # Another gap after the first recovery snapshot (uid 5) forces a newer snapshot.
        later_gap = message(pair, 8)
        later_gap.content["sequence_gap"] = True
        self.tracker._order_book_diff_stream.put_nowait(message(pair, 6))
        self.tracker._order_book_diff_stream.put_nowait(later_gap)
        await self.settle()
        gate.set()
        await self.settle()
        assert not self.tracker.is_order_book_valid(pair)
        assert self.tracker._resync_min_update_id[pair] == 8
        retry.put_nowait(None)
        await self.settle()
        assert self.tracker.is_order_book_valid(pair)
        assert self.tracker.order_books[pair].snapshot_uid == 30
        assert self.tracker._tracking_tasks[pair] is not old_consumer
        self.tracker._order_book_diff_stream.put_nowait(message(pair, 31))
        await self.settle()
        assert self.tracker.order_books[pair].last_diff_uid == 31
