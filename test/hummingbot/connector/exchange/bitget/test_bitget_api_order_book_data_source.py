import asyncio
import json
import re
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from aioresponses import aioresponses
from bidict import bidict

import hummingbot.connector.exchange.bitget.bitget_constants as CONSTANTS
import hummingbot.connector.exchange.bitget.bitget_web_utils as web_utils
from hummingbot.client.config.client_config_map import ClientConfigMap
from hummingbot.client.config.config_helpers import ClientConfigAdapter
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange
from hummingbot.connector.test_support.network_mocking_assistant import NetworkMockingAssistant
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType


class BitgetAPIOrderBookDataSourceUnitTests(IsolatedAsyncioWrapperTestCase):
    """
    Unit tests for BitgetAPIOrderBookDataSource class
    """

    level: int = 0

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.base_asset: str = "COINALPHA"
        cls.quote_asset: str = "USDT"
        cls.trading_pair: str = f"{cls.base_asset}-{cls.quote_asset}"
        cls.exchange_trading_pair: str = f"{cls.base_asset}{cls.quote_asset}"

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        self.log_records: List[Any] = []
        self.listening_task: Optional[asyncio.Task] = None
        self.mocking_assistant: NetworkMockingAssistant = NetworkMockingAssistant()
        self.client_config_map: ClientConfigAdapter = ClientConfigAdapter(ClientConfigMap())

        self.connector = BitgetExchange(
            bitget_api_key="test_api_key",
            bitget_secret_key="test_secret_key",
            bitget_passphrase="test_passphrase",
            trading_pairs=[self.trading_pair]
        )
        self.data_source = BitgetAPIOrderBookDataSource(
            trading_pairs=[self.trading_pair],
            connector=self.connector,
            api_factory=self.connector._web_assistants_factory)

        self.data_source.logger().setLevel(1)
        self.data_source.logger().addHandler(self)

        self.connector._set_trading_pair_symbol_map(
            bidict({
                self.exchange_trading_pair: self.trading_pair
            })
        )

    def handle(self, record: Any) -> None:
        """
        Handle logging records by appending them to the log_records list.

        :param record: The log record to be handled.
        """
        self.log_records.append(record)

    def ws_trade_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock WebSocket response for trade updates.

        :return: Dict[str, Any]: Mock trade response data.
        """
        return {
            "arg": {
                "instType": "SPOT",
                "channel": CONSTANTS.PUBLIC_WS_TRADE,
                "instId": self.exchange_trading_pair
            },
            "data": [
                {
                    "ts": "1695709835822",
                    "price": "26293.4",
                    "size": "0.0013",
                    "side": "buy",
                    "tradeId": "1000000000"
                },
                {
                    "ts": "1695709835822",
                    "price": "24293.5",
                    "size": "0.0213",
                    "side": "sell",
                    "tradeId": "1000000001"
                }
            ]
        }

    def rest_last_traded_price_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock REST response for last traded price.

        :return: Dict[str, Any]: Mock last traded price response data.
        """
        return {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "symbol": self.exchange_trading_pair,
                    "lastPr": "2200.10",
                    "open24h": "0.00",
                    "high24h": "0.00",
                    "low24h": "0.00",
                    "change24h": "0.00",
                    "bidPr": "1792",
                    "askPr": "2200.1",
                    "bidSz": "0.0084",
                    "askSz": "19740.8811",
                    "baseVolume": "0.0000",
                    "quoteVolume": "0.0000",
                    "openUtc": "0.00",
                    "changeUtc24h": "0",
                    "ts": "1695702438018"
                }
            ]
        }

    def ws_order_book_snapshot_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock WebSocket response for order book snapshot.

        :return: Dict[str, Any]: Mock order book snapshot response data.
        """
        return {
            "action": "snapshot",
            "arg": {
                "instType": "SPOT",
                "channel": CONSTANTS.PUBLIC_WS_BOOKS,
                "instId": self.exchange_trading_pair
            },
            "data": [
                {
                    "asks": [
                        ["26274.9", "0.0009"],
                        ["26275.0", "0.0500"]
                    ],
                    "bids": [
                        ["26274.8", "0.0009"],
                        ["26274.7", "0.0027"]
                    ],
                    "checksum": 0,
                    "seq": 123,
                    "ts": "1695710946294"
                }
            ],
            "ts": 1695710946294
        }

    def ws_order_book_diff_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock WebSocket response for order book diff updates.

        :return: Dict[str, Any]: Mock order book diff response data.
        """
        snapshot: Dict[str, Any] = self.ws_order_book_snapshot_mock_response()
        snapshot["action"] = "update"

        return snapshot

    def ws_error_event_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock WebSocket response for error events.

        :return: Dict[str, Any]: Mock error event response data.
        """

        return {
            "event": "error",
            "code": "30005",
            "msg": "Invalid request"
        }

    def rest_order_book_snapshot_mock_response(self) -> Dict[str, Any]:
        """
        Create a mock REST response for order book snapshot.

        :return: Dict[str, Any]: Mock order book snapshot response data.
        """
        return {
            "code": "00000",
            "msg": "success",
            "requestTime": 1698303884579,
            "data": {
                "asks": [
                    ["26274.9", "0.0009"],
                    ["26275.0", "0.0500"]
                ],
                "bids": [
                    ["26274.8", "0.0009"],
                    ["26274.7", "0.0027"]
                ],
                "ts": "1695710946294"
            },
            "ts": 1695710946294
        }

    def _is_logged(self, log_level: str, message: str) -> bool:
        """
        Check if a specific log message with the given level exists in the log records.

        :param log_level: The log level to check (e.g., "INFO", "ERROR").
        :param message: The log message to check for.

        :return: True if the log message exists with the specified level, False otherwise.
        """
        return any(record.levelname == log_level and record.getMessage() == message
                   for record in self.log_records)

    def v3_snapshot_response(self, ts="1695710946294"):
        return {
            "code": "00000", "msg": "success",
            "data": {"b": [[100, 2], [99, 3]], "a": [[101, 4], [102, 5]], "ts": ts},
        }

    def snapshot_url(self, v3=False):
        endpoint = CONSTANTS.PUBLIC_ORDERBOOK_V3_ENDPOINT if v3 else CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT
        return re.compile(f"^{re.escape(web_utils.public_rest_url(endpoint))}")

    def snapshot_request_count(self, mock_get):
        return sum(
            len(calls) for (_, url), calls in mock_get.requests.items()
            if url.path in (CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT, CONSTANTS.PUBLIC_ORDERBOOK_V3_ENDPOINT)
        )

    @aioresponses()
    async def test_v3_required_pair_negotiates_once_preserves_case_and_timestamp(self, mock_get):
        pair = "rSPY-USDT"
        self.connector._set_trading_pair_symbol_map(bidict({"rSPYUSDT": pair}))
        mock_get.get(self.snapshot_url(), status=400, payload={"code": "40502", "data": None})
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(), repeat=True)
        book = await self.data_source.get_new_order_book(pair)
        self.assertEqual(1695710946294, book.snapshot_uid)
        self.assertEqual(100, list(book.bid_entries())[0].price)
        self.assertEqual(4, list(book.ask_entries())[0].amount)
        second = await self.data_source._order_book_snapshot(pair)
        self.assertEqual(1695710946294 * 1e-3, second.timestamp)
        requests = [(url, calls) for (_, url), calls in mock_get.requests.items()]
        v2_calls = [calls for url, calls in requests if url.path == CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT]
        v3_calls = [calls for url, calls in requests if url.path == CONSTANTS.PUBLIC_ORDERBOOK_V3_ENDPOINT]
        self.assertEqual(1, sum(map(len, v2_calls)))
        self.assertEqual(2, sum(map(len, v3_calls)))
        self.assertEqual({"category": "SPOT", "symbol": "rSPYUSDT", "limit": "100"},
                         v3_calls[0][0].kwargs["params"])
        self.assertIs(book, self.data_source._v3_books[pair])

    @aioresponses()
    async def test_v2_compatible_pair_never_calls_v3(self, mock_get):
        mock_get.get(self.snapshot_url(), payload=self.rest_order_book_snapshot_mock_response())
        await self.data_source.get_new_order_book(self.trading_pair)
        self.assertFalse(self.data_source._v3_pairs)
        self.assertEqual(1, self.snapshot_request_count(mock_get))

    @aioresponses()
    async def test_v3_failure_never_falls_back_to_v2_and_40502_disables_retries(self, mock_get):
        mock_get.get(self.snapshot_url(), status=400, payload={"code": "40502"})
        mock_get.get(self.snapshot_url(v3=True), status=400, payload={"code": "40502"})
        for _ in range(3):
            with self.assertRaisesRegex(IOError, "40502"):
                await self.data_source._order_book_snapshot(self.trading_pair)
        self.assertEqual(2, self.snapshot_request_count(mock_get))

    @aioresponses()
    async def test_http_429_honors_retry_after_globally_without_version_switch(self, mock_get):
        mock_get.get(self.snapshot_url(), status=429, headers={"Retry-After": "120"}, payload={"code": "429"})
        with patch.object(self.data_source, "_time", return_value=1000):
            with self.assertRaisesRegex(IOError, "429"):
                await self.data_source._order_book_snapshot(self.trading_pair)
            with self.assertRaisesRegex(IOError, "backoff"):
                await self.data_source._order_book_snapshot(self.trading_pair)
        self.assertEqual(1120, self.data_source._snapshot_rate_limit_until)
        self.assertFalse(self.data_source._v3_pairs)
        self.assertEqual(1, self.snapshot_request_count(mock_get))

    @aioresponses()
    async def test_v3_http_429_does_not_repeat_v2_probe(self, mock_get):
        mock_get.get(self.snapshot_url(), status=400, payload={"code": "40502"})
        mock_get.get(self.snapshot_url(v3=True), status=429, payload={"code": "429"})
        with self.assertRaisesRegex(IOError, "429"):
            await self.data_source._order_book_snapshot(self.trading_pair)
        with self.assertRaisesRegex(IOError, "backoff"):
            await self.data_source._order_book_snapshot(self.trading_pair)
        self.assertIn(self.trading_pair, self.data_source._v3_pairs)
        self.assertEqual(2, self.snapshot_request_count(mock_get))

    @aioresponses()
    async def test_http_200_with_40502_negotiates_v3_and_application_429_backs_off(self, mock_get):
        mock_get.get(self.snapshot_url(), payload={"code": "40502"})
        mock_get.get(self.snapshot_url(v3=True), payload={"code": "429"})
        with self.assertRaisesRegex(IOError, "rate limited"):
            await self.data_source._order_book_snapshot(self.trading_pair)
        with self.assertRaisesRegex(IOError, "backoff"):
            await self.data_source._order_book_snapshot(self.trading_pair)
        self.assertEqual(2, self.snapshot_request_count(mock_get))

    @aioresponses()
    async def test_v3_timeout_is_propagated_without_downgrade(self, mock_get):
        self.data_source._v3_pairs.add(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), exception=asyncio.TimeoutError)
        with self.assertRaises(asyncio.TimeoutError):
            await self.data_source._order_book_snapshot(self.trading_pair)
        self.assertEqual(1, self.snapshot_request_count(mock_get))
        self.assertIn(self.trading_pair, self.data_source._v3_pairs)

    @aioresponses()
    async def test_concurrent_requests_probe_v2_only_once(self, mock_get):
        mock_get.get(self.snapshot_url(), status=400, payload={"code": "40502"})
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(), repeat=True)
        await asyncio.gather(*(
            self.data_source._order_book_snapshot(self.trading_pair) for _ in range(2)
        ))
        v2_count = sum(len(calls) for (_, url), calls in mock_get.requests.items()
                       if url.path == CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT)
        self.assertEqual(1, v2_count)

    async def test_v3_pairs_are_not_subscribed_to_v2_stream(self):
        self.data_source._v3_pairs.add(self.trading_pair)
        ws = AsyncMock()
        await self.data_source._subscribe_channels(ws)
        ws.send.assert_not_called()

    @aioresponses()
    async def test_application_error_is_not_treated_as_depth(self, mock_get):
        mock_get.get(self.snapshot_url(), payload={"code": "40017", "data": None})
        with self.assertRaisesRegex(IOError, "request failed"):
            await self.data_source._order_book_snapshot(self.trading_pair)
        with self.assertRaisesRegex(IOError, "backoff"):
            await self.data_source._order_book_snapshot(self.trading_pair)

    async def test_invalid_v3_snapshots_fail_closed(self):
        invalid_depths = [
            None, [],
            {"a": [], "b": [[100, 1]], "ts": "1"},
            {"a": [[101, 1]], "b": [[100, -1]], "ts": "1"},
            {"a": [[101, 1]], "b": [[float("nan"), 1]], "ts": "1"},
            {"a": [[101, 1]], "b": [[100, float("inf")]], "ts": "1"},
            {"a": [[101, 1]], "b": [[100, 1, 2]], "ts": "1"},
            {"a": [[101, 1]], "b": [[102, 1]], "ts": "1"},
            {"a": [[101, 1]], "b": [[99, 1], [100, 1]], "ts": "1"},
            {"a": [[101, 1]], "b": [[100, 1]], "ts": "bad"},
            {"a": [[101, 1]], "b": [[100, 1]], "ts": "-1"},
            {"a": [[101, 1]], "b": [[100, 1]], "ts": "1.5"},
        ]
        self.data_source._v3_pairs.add(self.trading_pair)
        for depth in invalid_depths:
            with self.subTest(depth=depth), aioresponses() as mock_get:
                mock_get.get(self.snapshot_url(v3=True), payload={"code": "00000", "data": depth})
                with self.assertRaises(IOError):
                    await self.data_source._order_book_snapshot(self.trading_pair)

    @aioresponses()
    async def test_non_json_snapshot_is_rejected(self, mock_get):
        mock_get.get(self.snapshot_url(), body="<html>upstream unavailable</html>")
        with self.assertRaisesRegex(IOError, "Invalid Bitget order book JSON"):
            await self.data_source._order_book_snapshot(self.trading_pair)

    async def test_v2_diffs_and_snapshots_cannot_update_v3_book(self):
        self.data_source._v3_pairs.add(self.trading_pair)
        output = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(self.ws_order_book_diff_mock_response(), output)
        await self.data_source._parse_order_book_snapshot_message(self.ws_order_book_snapshot_mock_response(), output)
        self.assertTrue(output.empty())

    async def test_uppercase_v2_symbol_cannot_update_case_sensitive_v3_pair(self):
        self.connector._set_trading_pair_symbol_map(bidict({"rSPYUSDT": "rSPY-USDT"}))
        self.data_source._v3_pairs.add("rSPY-USDT")
        raw = self.ws_order_book_diff_mock_response()
        raw["arg"]["instId"] = "RSPYUSDT"
        output = asyncio.Queue()
        await self.data_source._parse_order_book_diff_message(raw, output)
        self.assertTrue(output.empty())

    @aioresponses()
    async def test_periodic_v3_refresh_updates_tracker_owned_book_then_invalidates_on_failure(self, mock_get):
        self.data_source._v3_pairs.add(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response())
        book = await self.data_source.get_new_order_book(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(ts="1695710947294"))
        with patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source._refresh_v3_order_books()
        self.assertEqual(1695710947294, book.snapshot_uid)
        mock_get.get(self.snapshot_url(v3=True), status=429, payload={"code": "429"})
        with patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source._refresh_v3_order_books()
        self.assertFalse(list(book.bid_entries()))
        self.assertFalse(list(book.ask_entries()))

    @aioresponses()
    async def test_old_v3_snapshot_is_not_applied_and_next_fresh_snapshot_recovers(self, mock_get):
        self.data_source._v3_pairs.add(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response())
        book = await self.data_source.get_new_order_book(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(ts="1695710946293"))
        with patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source._refresh_v3_order_books()
        self.assertFalse(list(book.bid_entries()))
        self.data_source._snapshot_retry_at.clear()
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(ts="1695710947294"))
        with patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source._refresh_v3_order_books()
        self.assertEqual(1695710947294, book.snapshot_uid)
        self.assertTrue(list(book.bid_entries()))

    @aioresponses()
    async def test_v3_refresh_diagnostics_show_success_failure_stale_without_spam(self, mock_get):
        self.data_source._v3_pairs.add(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response())
        book = await self.data_source.get_new_order_book(self.trading_pair)
        now = 1695710947.300
        responses = [
            self.v3_snapshot_response(ts="1695710947294"),
            self.v3_snapshot_response(ts="1695710947295"),
            self.v3_snapshot_response(ts="1695710947295"),
        ]
        for response in responses:
            mock_get.get(self.snapshot_url(v3=True), payload=response)
            with patch.object(self.data_source, "_time", return_value=now), \
                    patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await self.data_source._refresh_v3_order_books()
        messages = [record.getMessage() for record in self.log_records]
        self.assertEqual(1, sum("[V3_REFRESH_OK]" in message for message in messages))
        self.assertEqual(1, sum("[V3_REFRESH]" in message for message in messages))
        self.assertTrue(any("bids=2 asks=2" in message for message in messages))
        self.assertFalse(list(book.bid_entries()))
        with patch.object(self.data_source, "_time", return_value=now + 61):
            self.data_source._log_v3_refresh_summary()
        summary = self.log_records[-1].getMessage()
        self.assertIn("success=1 failed=1 stale=1", summary)
        self.assertIn("overdue_books=1", summary)
        self.assertIn("Non-increasing", summary)

    @aioresponses()
    async def test_increasing_but_old_v3_timestamp_is_diagnosed_not_logged_as_success(self, mock_get):
        self.data_source._v3_pairs.add(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response())
        await self.data_source.get_new_order_book(self.trading_pair)
        mock_get.get(self.snapshot_url(v3=True), payload=self.v3_snapshot_response(ts="1695710947294"))
        with patch.object(self.data_source, "_time", return_value=1695710970.0), \
                patch.object(self.data_source, "_sleep", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source._refresh_v3_order_books()
        messages = [record.getMessage() for record in self.log_records]
        self.assertFalse(any("[V3_REFRESH_OK]" in message for message in messages))
        self.assertTrue(any("success=0 failed=0 stale=1 overdue_books=1" in message for message in messages))

    async def test_v3_refresh_task_stops_with_subscription_listener(self):
        stopped = asyncio.Event()

        async def refresh():
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        with patch.object(self.data_source, "_refresh_v3_order_books", side_effect=refresh), \
                patch.object(self.data_source, "_listen_for_v2_subscriptions", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await self.data_source.listen_for_subscriptions()
        self.assertTrue(stopped.is_set())

    @aioresponses()
    def test_get_last_traded_prices(self, mock_get: aioresponses) -> None:
        """
        Test retrieval of last traded prices from the REST API.

        :param mock_get: Mocked HTTP response object.
        """
        mock_response: Dict[str, Any] = self.rest_last_traded_price_mock_response()
        url: str = web_utils.public_rest_url(CONSTANTS.PUBLIC_TICKERS_ENDPOINT)
        regex_url = re.compile(f"^{url}".replace(".", r"\.").replace("?", r"\?"))

        mock_get.get(regex_url, body=json.dumps(mock_response))

        results: List[Dict[str, float]] = self.local_event_loop.run_until_complete(
            asyncio.gather(self.data_source.get_last_traded_prices([self.trading_pair]))
        )
        result: Dict[str, float] = results[0]

        self.assertEqual(result[self.trading_pair], float("2200.1"))

    @aioresponses()
    def test_get_new_order_book_successful(self, mock_get: aioresponses) -> None:
        """
        Test successful retrieval of a new order book snapshot from the REST API.

        :param mock_get: Mocked HTTP response object.
        """
        mock_response: Dict[str, Any] = self.rest_order_book_snapshot_mock_response()
        url: str = web_utils.public_rest_url(CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT)
        regex_url = re.compile(f"^{url}".replace(".", r"\.").replace("?", r"\?"))

        mock_get.get(regex_url, body=json.dumps(mock_response))

        results: List[OrderBook] = self.local_event_loop.run_until_complete(
            asyncio.gather(self.data_source.get_new_order_book(self.trading_pair))
        )
        order_book: OrderBook = results[0]
        data: Dict[str, Any] = mock_response["data"]
        update_id: int = int(data["ts"])

        self.assertTrue(isinstance(order_book, OrderBook))
        self.assertEqual(order_book.snapshot_uid, update_id)

        bids = list(order_book.bid_entries())
        asks = list(order_book.ask_entries())

        self.assertEqual(2, len(bids))
        self.assertEqual(float(data["bids"][0][0]), bids[0].price)
        self.assertEqual(float(data["bids"][0][1]), bids[0].amount)
        self.assertEqual(update_id, bids[0].update_id)
        self.assertEqual(2, len(asks))
        self.assertEqual(float(data["asks"][0][0]), asks[0].price)
        self.assertEqual(float(data["asks"][0][1]), asks[0].amount)
        self.assertEqual(update_id, asks[0].update_id)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_subscriptions_subscribes_to_trades_and_order_diffs(
        self, mock_ws: AsyncMock
    ) -> None:
        """
        Test subscription to WebSocket channels for trades and order book diffs.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_ws.return_value = self.mocking_assistant.create_websocket_mock()
        subscription_topics: List[Dict[str, str]] = []

        for channel in [CONSTANTS.PUBLIC_WS_BOOKS, CONSTANTS.PUBLIC_WS_TRADE]:
            subscription_topics.append({
                "instType": "SPOT",
                "channel": channel,
                "instId": self.exchange_trading_pair
            })

        self.mocking_assistant.add_websocket_aiohttp_message(
            websocket_mock=mock_ws.return_value,
            message=json.dumps({
                "event": "subscribe",
                "args": subscription_topics
            })
        )

        self.listening_task = self.local_event_loop.create_task(
            self.data_source.listen_for_subscriptions()
        )

        await self.mocking_assistant.run_until_all_aiohttp_messages_delivered(
            mock_ws.return_value
        )

        sent_subscription_messages = self.mocking_assistant.json_messages_sent_through_websocket(
            websocket_mock=mock_ws.return_value
        )
        expected_ws_subscription: Dict[str, Any] = {
            "op": "subscribe",
            "args": [
                {
                    "instType": "SPOT",
                    "channel": CONSTANTS.PUBLIC_WS_BOOKS,
                    "instId": self.exchange_trading_pair
                },
                {
                    "instType": "SPOT",
                    "channel": CONSTANTS.PUBLIC_WS_TRADE,
                    "instId": self.exchange_trading_pair
                }
            ]
        }

        self.assertEqual(expected_ws_subscription, sent_subscription_messages[0])
        self.assertTrue(self._is_logged(
            "INFO",
            "Subscribed to public channels..."
        ))

    @patch("hummingbot.core.data_type.order_book_tracker_data_source.OrderBookTrackerDataSource._sleep")
    @patch("aiohttp.ClientSession.ws_connect")
    async def test_listen_for_subscriptions_raises_cancel_exception(
        self, mock_ws: MagicMock, _: MagicMock
    ) -> None:
        """
        Test that listen_for_subscriptions raises CancelledError when WebSocket connection is cancelled.

        :param mock_ws: Mocked WebSocket connection object.
        :param _: Mocked sleep function (unused).
        """
        mock_ws.side_effect = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source.listen_for_subscriptions()

    @patch("hummingbot.core.data_type.order_book_tracker_data_source.OrderBookTrackerDataSource._sleep")
    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_subscriptions_logs_exception_details(
        self, mock_ws: AsyncMock, sleep_mock: MagicMock
    ) -> None:
        """
        Test that listen_for_subscriptions logs exception details when an error occurs.

        :param mock_ws: Mocked WebSocket connection object.
        :param sleep_mock: Mocked sleep function.
        """
        mock_ws.side_effect = Exception("TEST ERROR.")
        sleep_mock.side_effect = asyncio.CancelledError

        try:
            await self.data_source.listen_for_subscriptions()
        except asyncio.CancelledError:
            pass

        self.assertTrue(self._is_logged(
            "ERROR",
            "Unexpected error occurred when listening to order book streams. "
            "Retrying in 5 seconds..."
        ))

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_subscribe_channels_raises_cancel_exception(self, mock_ws: AsyncMock) -> None:
        """
        Test that _subscribe_channels raises CancelledError when WebSocket send is cancelled.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_ws.send.side_effect = asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source._subscribe_channels(mock_ws)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_subscribe_channels_raises_exception_and_logs_error(
        self,
        mock_ws: AsyncMock
    ) -> None:
        """
        Test that _subscribe_channels logs an error when an unexpected exception occurs.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_ws.send.side_effect = Exception("Test Error")

        with self.assertRaises(Exception):
            await self.data_source._subscribe_channels(mock_ws)

        self.assertTrue(
            self._is_logged(
                "ERROR",
                "Unexpected error occurred subscribing to public channels..."
            )
        )

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_trades(self, mock_ws: AsyncMock) -> None:
        """
        Test processing of trade updates from WebSocket messages.

        :param mock_ws: Mocked WebSocket connection object.
        """
        msg_queue: asyncio.Queue = asyncio.Queue()
        mock_response: Dict[str, Any] = self.ws_trade_mock_response()

        mock_ws.get.side_effect = [mock_response, asyncio.CancelledError]
        self.data_source._message_queue[self.data_source._trade_messages_queue_key] = mock_ws

        self.listening_task = self.local_event_loop.create_task(
            self.data_source.listen_for_trades(self.local_event_loop, msg_queue)
        )

        trade1: OrderBookMessage = await msg_queue.get()
        trade2: OrderBookMessage = await msg_queue.get()

        self.assertTrue(msg_queue.empty())
        self.assertEqual(1000000000, trade1.trade_id)
        self.assertEqual(1000000001, trade2.trade_id)

    async def test_listen_for_trades_raises_cancelled_exception(self) -> None:
        """
        Test that listen_for_trades raises CancelledError when the message queue is cancelled.
        """
        mock_queue = MagicMock()
        mock_queue.get.side_effect = asyncio.CancelledError
        self.data_source._message_queue[self.data_source._trade_messages_queue_key] = mock_queue

        msg_queue: asyncio.Queue = asyncio.Queue()

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source.listen_for_trades(self.local_event_loop, msg_queue)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_order_book_diffs_successful(self, mock_ws: AsyncMock) -> None:
        """
        Test successful processing of order book diff updates from WebSocket messages.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_response: Dict[str, Any] = self.ws_order_book_diff_mock_response()

        mock_ws.get.side_effect = [mock_response, asyncio.CancelledError]
        self.data_source._message_queue[self.data_source._diff_messages_queue_key] = mock_ws

        msg_queue: asyncio.Queue = asyncio.Queue()

        self.listening_task = self.local_event_loop.create_task(
            self.data_source.listen_for_order_book_diffs(self.local_event_loop, msg_queue)
        )

        msg: OrderBookMessage = await msg_queue.get()
        data: Dict[str, Any] = mock_response["data"][0]
        expected_update_id: int = int(data["ts"])

        self.assertEqual(OrderBookMessageType.DIFF, msg.type)
        self.assertEqual(-1, msg.trade_id)
        self.assertEqual(int(data["ts"]) * 1e-3, msg.timestamp)
        self.assertEqual(expected_update_id, msg.update_id)

        bids = msg.bids
        asks = msg.asks

        self.assertEqual(2, len(bids))
        self.assertEqual(float(data["bids"][0][0]), bids[0].price)
        self.assertEqual(float(data["bids"][0][1]), bids[0].amount)
        self.assertEqual(expected_update_id, bids[0].update_id)
        self.assertEqual(2, len(asks))
        self.assertEqual(float(data["asks"][0][0]), asks[0].price)
        self.assertEqual(float(data["asks"][0][1]), asks[0].amount)
        self.assertEqual(expected_update_id, asks[0].update_id)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_order_book_snapshots_successful(self, mock_ws: AsyncMock) -> None:
        """
        Test successful processing of order book snapshot updates from WebSocket messages.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_response: Dict[str, Any] = self.ws_order_book_snapshot_mock_response()

        mock_ws.get.side_effect = [mock_response, asyncio.CancelledError]
        self.data_source._message_queue[self.data_source._snapshot_messages_queue_key] = mock_ws

        msg_queue: asyncio.Queue = asyncio.Queue()

        self.listening_task = self.local_event_loop.create_task(
            self.data_source.listen_for_order_book_snapshots(self.local_event_loop, msg_queue)
        )

        msg: OrderBookMessage = await msg_queue.get()
        data: Dict[str, Any] = mock_response["data"][0]
        expected_update_id: int = int(data["ts"])

        self.assertEqual(OrderBookMessageType.SNAPSHOT, msg.type)
        self.assertEqual(-1, msg.trade_id)
        self.assertEqual(int(data["ts"]) * 1e-3, msg.timestamp)
        self.assertEqual(expected_update_id, msg.update_id)

        bids = msg.bids
        asks = msg.asks

        self.assertEqual(2, len(bids))
        self.assertEqual(float(data["bids"][0][0]), bids[0].price)
        self.assertEqual(float(data["bids"][0][1]), bids[0].amount)
        self.assertEqual(expected_update_id, bids[0].update_id)
        self.assertEqual(2, len(asks))
        self.assertEqual(float(data["asks"][0][0]), asks[0].price)
        self.assertEqual(float(data["asks"][0][1]), asks[0].amount)
        self.assertEqual(expected_update_id, asks[0].update_id)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_order_book_snapshots_raises_cancelled_exception(
        self,
        mock_ws: AsyncMock
    ) -> None:
        """
        Test that listen_for_order_book_snapshots raises CancelledError when the message queue is cancelled.

        :param mock_ws: Mocked WebSocket connection object.
        """
        mock_ws.get.side_effect = asyncio.CancelledError
        self.data_source._message_queue[self.data_source._snapshot_messages_queue_key] = mock_ws

        msg_queue: asyncio.Queue = asyncio.Queue()

        with self.assertRaises(asyncio.CancelledError):
            await self.data_source.listen_for_order_book_snapshots(self.local_event_loop, msg_queue)

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_order_book_snapshots_logs_exception(self, mock_ws: AsyncMock) -> None:
        """
        Test that listen_for_order_book_snapshots logs an error
        when processing invalid snapshot data.

        :param mock_ws: Mocked WebSocket connection object.
        """
        incomplete_mock_response: Dict[str, Any] = self.ws_order_book_snapshot_mock_response()
        incomplete_mock_response["data"] = [
            {
                "instId": self.exchange_trading_pair,
                "ts": 1542337219120
            }
        ]

        mock_ws.get.side_effect = [incomplete_mock_response, asyncio.CancelledError]
        self.data_source._message_queue[self.data_source._snapshot_messages_queue_key] = mock_ws

        msg_queue: asyncio.Queue = asyncio.Queue()

        try:
            await self.data_source.listen_for_order_book_snapshots(self.local_event_loop, msg_queue)
        except asyncio.CancelledError:
            pass

        self.assertTrue(
            self._is_logged(
                "ERROR",
                "Unexpected error when processing public order book snapshots from exchange"
            )
        )

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    async def test_listen_for_trades_logs_exception(self, mock_ws: AsyncMock) -> None:
        """
        Test that listen_for_trades logs an error when processing invalid trade data.

        :param mock_ws: Mocked WebSocket connection object.
        """
        incomplete_mock_response: Dict[str, Any] = self.ws_trade_mock_response()
        incomplete_mock_response["data"] = [
            {
                "instId": self.exchange_trading_pair,
                "ts": 1542337219120
            }
        ]

        mock_ws.get.side_effect = [incomplete_mock_response, asyncio.CancelledError]
        self.data_source._message_queue[self.data_source._trade_messages_queue_key] = mock_ws

        msg_queue: asyncio.Queue = asyncio.Queue()

        try:
            await self.data_source.listen_for_trades(self.local_event_loop, msg_queue)
        except asyncio.CancelledError:
            pass

        self.assertTrue(
            self._is_logged(
                "ERROR",
                "Unexpected error when processing public trade updates from exchange"
            )
        )

    @patch("aiohttp.ClientSession.ws_connect", new_callable=AsyncMock)
    def test_process_message_for_unknown_channel_event_error_raises(
        self,
        mock_ws: AsyncMock
    ) -> None:
        """
        Verify that an event message with 'event': 'error'
        raises IOError in _process_message_for_unknown_channel.
        """
        mock_response = self.ws_error_event_mock_response()

        with self.assertRaises(IOError) as context:
            asyncio.get_event_loop().run_until_complete(
                self.data_source._process_message_for_unknown_channel(mock_response, mock_ws)
            )

        self.assertIn("Failed to subscribe to public channels", str(context.exception))
        self.assertIn("Invalid request", str(context.exception))
