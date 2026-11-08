"""
Regression tests for the frozen ICNT-USDT order book (Bitget, 2026-11-08).

Dynamically added Bitget pairs received one REST snapshot but (a) no live WS
subscription and (b) no tracker task to apply WS messages, so the book stayed
frozen. These offline tests drive the real BitgetAPIOrderBookDataSource and the
real OrderBookTracker with a fake websocket. They prove the wiring, not the
live Bitget stream.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_row import OrderBookRow
from hummingbot.core.data_type.order_book_tracker import OrderBookTracker
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

STATIC = "BTC-USDT"
DYNAMIC = "ICNT-USDT"
SYMBOLS = {STATIC: "BTCUSDT", DYNAMIC: "ICNTUSDT", "BAD-USDT": "BADUSDT"}
T0_MS = 1_794_135_000_000


class FakeWS:
    def __init__(self, fail_on_send=None):
        self.sent = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.fail_on_send = fail_on_send

    async def send(self, request):
        if self.fail_on_send and self.fail_on_send(request.payload):
            raise ConnectionError("send failed")
        self.sent.append(request.payload)

    async def iter_messages(self):
        while True:
            data = await self.inbox.get()
            if data is None:
                raise ConnectionError("simulated disconnect")
            yield SimpleNamespace(data=data)

    async def disconnect(self):
        pass

    def subscribed_args(self):
        return [arg for p in self.sent if p.get("op") == "subscribe" for arg in p["args"]]


def _connector():
    connector = MagicMock()
    connector.exchange_symbol_associated_to_pair = AsyncMock(side_effect=lambda pair: SYMBOLS[pair])
    reverse = {v: k for k, v in SYMBOLS.items()}
    connector.trading_pair_associated_to_exchange_symbol = AsyncMock(side_effect=lambda s: reverse[s])
    return connector


def _data_source(pairs=(STATIC,)):
    ds = BitgetAPIOrderBookDataSource(trading_pairs=list(pairs), connector=_connector(), api_factory=MagicMock())
    ds.send_interval_ping = AsyncMock()
    return ds


def _book(bid, ask, uid):
    book = OrderBook()
    book.apply_snapshot([OrderBookRow(bid, 10.0, uid)], [OrderBookRow(ask, 10.0, uid)], uid)
    return book


def _books_msg(symbol, action, bid, ask, ts_ms):
    return {
        "action": action,
        "arg": {"instType": "SPOT", "channel": CONSTANTS.PUBLIC_WS_BOOKS, "instId": symbol},
        "data": [{"bids": [[str(bid), "5"]], "asks": [[str(ask), "5"]], "ts": str(ts_ms)}],
    }


_BOUND = (
    "_ensure_book_tracking_task", "_initialize_orderbook", "_initialize_orderbook_once",
    "_orderbook_init_state", "_schedule_orderbook_init", "_record_orderbook_init_result",
    "_subscribe_to_orderbook", "_has_orderbook_subscription",
)


def _ctrl():
    ctrl = MagicMock()
    ctrl.monitored_coins = set()
    for name in _BOUND:
        setattr(ctrl, name, getattr(MultiCoinGridController, name).__get__(ctrl))
    ctrl._orderbook_init_retryable = MultiCoinGridController._orderbook_init_retryable
    for name in ("_OB_INIT_RETRY_BASE_S", "_OB_INIT_RETRY_MAX_S",
                 "_OB_INIT_RETRY_WINDOW_S", "_OB_INIT_RETRIES_PER_WINDOW"):
        setattr(ctrl, name, getattr(MultiCoinGridController, name))
    return ctrl


async def _until(cond, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def run(coro):
    # Private loop: asyncio.run() would reset the global loop to None and break later tests.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Harness:
    """Real data source + real tracker routing, fake websocket connections."""

    def __init__(self, sockets):
        self.ds = _data_source()
        self.tracker = OrderBookTracker(data_source=self.ds, trading_pairs=[STATIC])
        self.tracker._order_books_initialized.set()
        self.tracker._order_books[STATIC] = _book(60000.0, 60010.0, T0_MS)
        MultiCoinGridController._ensure_book_tracking_task(_ctrl(), STATIC, self.tracker)
        self.sockets = list(sockets)
        self.ds._connected_websocket_assistant = AsyncMock(side_effect=self.sockets)
        self.tasks = []

    def start(self):
        loop = asyncio.get_running_loop()
        self.tasks = [
            asyncio.ensure_future(self.ds._listen_for_v2_subscriptions()),
            asyncio.ensure_future(self.ds.listen_for_order_book_diffs(loop, self.tracker._order_book_diff_stream)),
            asyncio.ensure_future(
                self.ds.listen_for_order_book_snapshots(loop, self.tracker._order_book_snapshot_stream)),
            asyncio.ensure_future(self.tracker._order_book_diff_router()),
            asyncio.ensure_future(self.tracker._order_book_snapshot_router()),
        ]

    async def add_dynamic(self, pair=DYNAMIC, bid=0.3178, ask=0.3180):
        # Same entry point as the controller: tracker lists, REST snapshot, live subscribe.
        self.tracker._trading_pairs.append(pair)
        self.ds._trading_pairs.append(pair)
        self.ds.get_new_order_book = AsyncMock(return_value=_book(bid, ask, T0_MS))
        await MultiCoinGridController._initialize_orderbook(_ctrl(), pair, self.tracker)

    async def stop(self):
        for task in self.tasks + list(self.tracker._tracking_tasks.values()):
            task.cancel()
        await asyncio.gather(*self.tasks, *self.tracker._tracking_tasks.values(), return_exceptions=True)


class TestDynamicPairLiveFeed:
    def test_dynamic_icnt_receives_live_updates_price_and_timestamp_change(self):
        async def scenario():
            ws = FakeWS()
            h = _Harness([ws])
            h.start()
            await _until(lambda: h.ds._ws_assistant is ws)
            await h.add_dynamic()

            assert {"instType": "SPOT", "channel": "books", "instId": "ICNTUSDT"} in ws.subscribed_args()
            assert {"instType": "SPOT", "channel": "trade", "instId": "ICNTUSDT"} in ws.subscribed_args()
            book = h.tracker._order_books[DYNAMIC]
            assert book.get_price(False) == 0.3178

            ws.inbox.put_nowait(_books_msg("ICNTUSDT", "snapshot", 0.3500, 0.3510, T0_MS + 60_000))
            await _until(lambda: book.snapshot_uid == T0_MS + 60_000)
            assert book.get_price(False) == 0.35

            ws.inbox.put_nowait(_books_msg("ICNTUSDT", "update", 0.3700, 0.3710, T0_MS + 120_000))
            await _until(lambda: book.last_diff_uid == T0_MS + 120_000)
            assert book.get_price(False) == 0.37
            assert h.ds.last_ws_update_age(DYNAMIC) is not None
            await h.stop()

        run(scenario())

    def test_without_tracking_task_ws_diffs_never_reach_the_book(self):
        """Documents the second half of the root cause: WS data alone does not update a dynamic book."""
        async def scenario():
            ws = FakeWS()
            h = _Harness([ws])
            h.start()
            await _until(lambda: h.ds._ws_assistant is ws)
            h.tracker._order_books[DYNAMIC] = _book(0.3178, 0.3180, T0_MS)
            await h.ds.subscribe_to_trading_pair(DYNAMIC)
            ws.inbox.put_nowait(_books_msg("ICNTUSDT", "update", 0.3700, 0.3710, T0_MS + 120_000))
            await _until(lambda: len(h.tracker._saved_message_queues[DYNAMIC]) == 1)
            assert h.tracker._order_books[DYNAMIC].get_price(False) == 0.3178
            await h.stop()

        run(scenario())

    def test_reconnect_restores_all_subscriptions_once(self):
        async def scenario():
            ws1, ws2 = FakeWS(), FakeWS()
            h = _Harness([ws1, ws2])
            h.start()
            await _until(lambda: h.ds._ws_assistant is ws1)
            await h.add_dynamic()
            ws1.inbox.put_nowait(None)
            await _until(lambda: h.ds._ws_assistant is ws2)

            args = ws2.subscribed_args()
            assert len(ws2.sent) == 1
            assert sorted((a["channel"], a["instId"]) for a in args) == sorted(
                (c, s) for c in ("books", "trade") for s in ("BTCUSDT", "ICNTUSDT"))

            assert await h.ds.subscribe_to_trading_pair(DYNAMIC) is True
            assert len(ws2.sent) == 1

            book = h.tracker._order_books[DYNAMIC]
            ws2.inbox.put_nowait(_books_msg("ICNTUSDT", "snapshot", 0.3600, 0.3610, T0_MS + 300_000))
            await _until(lambda: book.snapshot_uid == T0_MS + 300_000)
            assert book.get_price(False) == 0.36
            await h.stop()

        run(scenario())

    def test_bad_pair_rejection_does_not_block_other_pairs(self):
        async def scenario():
            ws = FakeWS()
            h = _Harness([ws])
            h.start()
            await _until(lambda: h.ds._ws_assistant is ws)
            await h.add_dynamic()
            await h.add_dynamic(pair="BAD-USDT", bid=1.0, ask=1.01)
            with patch.object(BitgetAPIOrderBookDataSource, "logger") as lg:
                ws.inbox.put_nowait({"event": "error", "code": "30001", "msg": "instId not exist",
                                     "arg": {"instType": "SPOT", "channel": "books", "instId": "BADUSDT"}})
                await _until(lambda: "BAD-USDT" not in h.ds._ws_subscribed_pairs)
                assert any("SUBSCRIBE_FAILED pair=BAD-USDT" in str(c) for c in lg.return_value.error.call_args_list)
            assert h.ds._ws_assistant is ws  # stream not torn down
            book = h.tracker._order_books[DYNAMIC]
            ws.inbox.put_nowait(_books_msg("ICNTUSDT", "update", 0.3700, 0.3710, T0_MS + 120_000))
            await _until(lambda: book.last_diff_uid == T0_MS + 120_000)
            await h.stop()

        run(scenario())


class TestSubscribeToTradingPair:
    def test_concurrent_subscribes_send_once(self):
        async def scenario():
            ds = _data_source()
            ws = FakeWS()
            await ds._subscribe_channels(ws)
            results = await asyncio.gather(*[ds.subscribe_to_trading_pair(DYNAMIC) for _ in range(5)])
            assert all(results)
            assert len(ws.sent) == 2  # initial batch + exactly one dynamic subscribe
            assert ds._trading_pairs.count(DYNAMIC) == 1

        run(scenario())

    def test_without_active_stream_is_deferred_and_included_on_connect(self):
        async def scenario():
            ds = _data_source()
            assert await ds.subscribe_to_trading_pair(DYNAMIC) is False
            assert DYNAMIC in ds._trading_pairs
            ws = FakeWS()
            await ds._subscribe_channels(ws)
            assert {"instType": "SPOT", "channel": "books", "instId": "ICNTUSDT"} in ws.subscribed_args()

        run(scenario())

    def test_send_failure_is_visible_and_retryable(self):
        async def scenario():
            ds = _data_source()
            ws = FakeWS(fail_on_send=lambda p: p["args"][0]["instId"] == "ICNTUSDT")
            await ds._subscribe_channels(ws)
            with patch.object(BitgetAPIOrderBookDataSource, "logger") as lg:
                assert await ds.subscribe_to_trading_pair(DYNAMIC) is False
                assert any("SUBSCRIBE_FAILED pair=ICNT-USDT" in str(c)
                           for c in lg.return_value.warning.call_args_list)
            assert DYNAMIC not in ds._ws_subscribed_pairs
            ws.fail_on_send = None
            assert await ds.subscribe_to_trading_pair(DYNAMIC) is True

        run(scenario())

    def test_v3_pair_is_never_subscribed_on_v2_stream(self):
        async def scenario():
            ds = _data_source()
            ws = FakeWS()
            await ds._subscribe_channels(ws)
            ds._v3_pairs.add(DYNAMIC)
            assert await ds.subscribe_to_trading_pair(DYNAMIC) is False
            assert len(ws.sent) == 1

        run(scenario())

    def test_duplicate_trading_pairs_subscribe_once_on_connect(self):
        async def scenario():
            ds = _data_source(pairs=(STATIC, DYNAMIC, DYNAMIC))
            ws = FakeWS()
            await ds._subscribe_channels(ws)
            assert len(ws.subscribed_args()) == 4

        run(scenario())


class TestControllerSubscriptionWiring:
    def test_tracking_task_registered_before_subscribe_is_sent(self):
        async def scenario():
            ds = _data_source()
            tracker = OrderBookTracker(data_source=ds, trading_pairs=[STATIC, DYNAMIC])
            ds._trading_pairs.append(DYNAMIC)
            ds.get_new_order_book = AsyncMock(return_value=_book(0.3178, 0.318, T0_MS))
            seen = {}

            class OrderCheckingWS(FakeWS):
                async def send(self, request):
                    seen["queue_ready"] = DYNAMIC in tracker._tracking_message_queues
                    await super().send(request)

            await ds._subscribe_channels(FakeWS())
            ds._ws_assistant = OrderCheckingWS()
            ds._ws_subscribed_pairs.discard(DYNAMIC)
            await MultiCoinGridController._initialize_orderbook(_ctrl(), DYNAMIC, tracker)
            assert seen == {"queue_ready": True}
            assert not tracker._tracking_tasks[DYNAMIC].done()
            for t in tracker._tracking_tasks.values():
                t.cancel()

        run(scenario())

    def test_ensure_tracking_task_is_idempotent_and_drops_stale_saved_diffs(self):
        async def scenario():
            ds = _data_source()
            tracker = OrderBookTracker(data_source=ds, trading_pairs=[DYNAMIC])
            tracker._order_books[DYNAMIC] = _book(0.3178, 0.318, T0_MS)
            tracker._saved_message_queues[DYNAMIC].append(object())
            ctrl = _ctrl()
            MultiCoinGridController._ensure_book_tracking_task(ctrl, DYNAMIC, tracker)
            first = tracker._tracking_tasks[DYNAMIC]
            assert DYNAMIC not in tracker._saved_message_queues
            MultiCoinGridController._ensure_book_tracking_task(ctrl, DYNAMIC, tracker)
            assert tracker._tracking_tasks[DYNAMIC] is first
            first.cancel()

        run(scenario())

    def test_non_bitget_data_source_keeps_legacy_resubscribe_path(self):
        async def scenario():
            tracker = MagicMock()
            tracker._trading_pairs = [DYNAMIC]
            tracker._order_books = {}
            tracker._initial_order_book_for_trading_pair = AsyncMock(return_value=MagicMock())
            tracker._data_source = MagicMock(spec=["resubscribe_pair", "_trading_pairs"])
            tracker._data_source.resubscribe_pair = AsyncMock()
            ctrl = _ctrl()
            ctrl._ensure_book_tracking_task = MagicMock()
            await MultiCoinGridController._initialize_orderbook(ctrl, DYNAMIC, tracker)
            tracker._data_source.resubscribe_pair.assert_awaited_once_with(DYNAMIC)
            ctrl._ensure_book_tracking_task.assert_not_called()

        run(scenario())


class _InitHarness:
    """Real Bitget data source + real tracker; fake REST and clock. Live 17:57 failure replay."""

    PAIRS = ("ICNT-USDT", "JCT-USDT", "SKYAI-USDT")

    def __init__(self, ws=None):
        for pair in self.PAIRS:
            SYMBOLS.setdefault(pair, pair.replace("-", ""))
        self.clock = [1_794_157_053.0]
        self.ds = _data_source()
        self.ds._time = lambda: self.clock[0]
        self.ds._ws_assistant = ws
        self.rest_calls = []
        self.fail_pairs = set()
        rest = MagicMock()
        rest.execute_request_and_get_response = AsyncMock(side_effect=self._rest)
        self.ds._api_factory.get_rest_assistant = AsyncMock(return_value=rest)
        self.tracker = OrderBookTracker(data_source=self.ds, trading_pairs=[STATIC])
        self.ctrl = _ctrl()
        self.ctrl.connector = SimpleNamespace(order_book_tracker=self.tracker)

    async def _rest(self, url, params, **kwargs):
        symbol = params["symbol"]
        self.rest_calls.append(symbol)
        response = MagicMock(status=200, headers={})
        if symbol in self.fail_pairs:
            response.json = AsyncMock(return_value={"code": "50000", "msg": "boom"})
        else:
            ts = str(int(self.clock[0] * 1000))
            response.json = AsyncMock(return_value={
                "code": CONSTANTS.RET_CODE_OK,
                "data": {"bids": [["0.3590", "10"]], "asks": [["0.3600", "10"]], "ts": ts}})
        return response

    async def settle(self):
        for _ in range(20):
            await asyncio.sleep(0)

    def stop(self):
        for task in self.tracker._tracking_tasks.values():
            task.cancel()


class TestInitRetryAfterSharedBackoff:
    def test_live_failure_replay_backoff_then_single_retry_reaches_ws_subscribe(self):
        async def scenario():
            ws = FakeWS()
            h = _InitHarness(ws)
            h.ds._snapshot_rate_limit_until = h.clock[0] + 30.0  # shared 429 backoff from route probe
            h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            # Deferred locally (no exchange call, no ERROR); listed but not usable for entries.
            assert h.rest_calls == []
            assert DYNAMIC in h.tracker._trading_pairs and DYNAMIC not in h.tracker._order_books
            assert h.ctrl._has_orderbook_subscription(DYNAMIC) is False
            h.ctrl.logger().error.assert_not_called()
            # Repeated cycles during backoff: no request, no new init.
            for _ in range(5):
                h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert h.rest_calls == [] and not h.ctrl._ob_init_state["inflight"]
            # Backoff over: the next cycle retries once, then tracking + WS subscribe follow.
            h.clock[0] += 31.0
            for _ in range(3):
                h.ctrl._subscribe_to_orderbook(DYNAMIC)  # same tick: in-flight guard
            await h.settle()
            assert h.rest_calls == [SYMBOLS[DYNAMIC]]
            assert DYNAMIC in h.tracker._order_books
            assert h.ctrl._has_orderbook_subscription(DYNAMIC) is True
            assert DYNAMIC in h.tracker._tracking_tasks
            assert DYNAMIC not in h.ctrl._ob_init_state["failures"]
            assert ws.subscribed_args().count(
                {"instType": "SPOT", "channel": CONSTANTS.PUBLIC_WS_BOOKS, "instId": SYMBOLS[DYNAMIC]}) == 1
            first_task = h.tracker._tracking_tasks[DYNAMIC]
            # Healthy pair: further cycles do nothing (no REST, no re-subscribe, same task).
            for _ in range(3):
                h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert h.rest_calls == [SYMBOLS[DYNAMIC]] and len(ws.sent) == 1
            assert h.tracker._tracking_tasks[DYNAMIC] is first_task
            h.stop()

        run(scenario())

    def test_retry_uses_exponential_pair_backoff_and_failure_is_visible(self):
        async def scenario():
            h = _InitHarness(FakeWS())
            h.fail_pairs.add(SYMBOLS[DYNAMIC])
            h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert h.rest_calls == [SYMBOLS[DYNAMIC]]
            assert "INIT_FAILED pair=ICNT-USDT attempt=1 retry_in=10s" in h.ctrl.logger().warning.call_args.args[0]
            # Data source also sets its own 30 s pair retry; nothing before both expire.
            h.clock[0] += 29.0
            h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert len(h.rest_calls) == 1
            h.clock[0] += 2.0
            h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert len(h.rest_calls) == 2
            assert "attempt=2 retry_in=20s" in h.ctrl.logger().warning.call_args.args[0]
            assert DYNAMIC not in h.tracker._tracking_tasks
            assert h.ctrl._has_orderbook_subscription(DYNAMIC) is False

        run(scenario())

    def test_one_failing_pair_does_not_block_others_and_retries_are_rate_capped(self):
        async def scenario():
            ws = FakeWS()
            h = _InitHarness(ws)
            pairs = [f"P{i}-USDT" for i in range(8)]
            for p in pairs:
                SYMBOLS[p] = p.replace("-", "")
            h.ds._snapshot_rate_limit_until = h.clock[0] + 30.0
            for p in pairs + [DYNAMIC]:
                h.ctrl._subscribe_to_orderbook(p)
            await h.settle()
            assert h.rest_calls == []
            h.clock[0] += 31.0
            h.fail_pairs.add(SYMBOLS[pairs[0]])
            for p in pairs + [DYNAMIC]:
                h.ctrl._subscribe_to_orderbook(p)
            await h.settle()
            # At most 5 retries per 10 s window: no burst after the backoff ends.
            assert len(h.rest_calls) == 5
            h.clock[0] += 10.0
            for p in pairs + [DYNAMIC]:
                h.ctrl._subscribe_to_orderbook(p)
            await h.settle()
            assert len(h.rest_calls) == 9
            assert len(set(h.rest_calls)) == 9  # never the same pair twice
            ok = pairs[1:] + [DYNAMIC]
            assert all(p in h.tracker._order_books for p in ok)
            assert pairs[0] not in h.tracker._order_books
            subscribed = {a["instId"] for a in ws.subscribed_args() if a["channel"] == CONSTANTS.PUBLIC_WS_BOOKS}
            assert subscribed == {SYMBOLS[p] for p in ok}
            h.stop()

        run(scenario())

    def test_unsubscribe_clears_retry_state(self):
        async def scenario():
            h = _InitHarness(FakeWS())
            h.fail_pairs.add(SYMBOLS[DYNAMIC])
            h.ctrl._subscribe_to_orderbook(DYNAMIC)
            await h.settle()
            assert DYNAMIC in h.ctrl._ob_init_state["failures"]
            h.ctrl._unsubscribe_from_orderbook = MultiCoinGridController._unsubscribe_from_orderbook.__get__(h.ctrl)
            h.ctrl._unsubscribe_from_orderbook(DYNAMIC)
            assert DYNAMIC not in h.ctrl._ob_init_state["failures"]
            assert DYNAMIC not in h.ctrl._ob_init_state["retry_at"]
            assert DYNAMIC not in h.tracker._trading_pairs

        run(scenario())

    def test_non_bitget_tracker_keeps_legacy_already_subscribed(self):
        tracker = MagicMock()
        tracker._trading_pairs = [DYNAMIC]
        tracker._order_books = {}
        tracker._data_source = MagicMock(spec=["resubscribe_pair", "_trading_pairs"])
        ctrl = _ctrl()
        ctrl.connector = SimpleNamespace(order_book_tracker=tracker)
        with patch("multi_coin_grid_pro.controllers.multi_coin_grid_controller.safe_ensure_future") as sef:
            ctrl._subscribe_to_orderbook(DYNAMIC)
            sef.assert_not_called()
        assert ctrl._has_orderbook_subscription(DYNAMIC) is True
