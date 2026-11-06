import asyncio
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Dict, List, NoReturn, Optional

from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS, bitget_web_utils as web_utils
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest, WSPlainTextRequest
from hummingbot.core.web_assistant.rest_assistant import RESTAssistant
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant

if TYPE_CHECKING:
    from hummingbot.connector.exchange.bitget.bitget_exchange import BitgetExchange


class BitgetAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """
    Data source for retrieving order book data from the Bitget exchange via REST and WebSocket APIs.
    """

    def __init__(
        self,
        trading_pairs: List[str],
        connector: 'BitgetExchange',
        api_factory: WebAssistantsFactory,
    ) -> None:
        super().__init__(trading_pairs)
        self._connector: 'BitgetExchange' = connector
        self._api_factory: WebAssistantsFactory = api_factory
        self._ping_task: Optional[asyncio.Task] = None
        self._v3_pairs: set[str] = set()
        self._v3_books: Dict[str, OrderBook] = {}
        self._v3_books_ready = asyncio.Event()
        self._snapshot_retry_at: Dict[str, float] = {}
        self._snapshot_rate_limit_until = 0.0
        self._snapshot_disabled_pairs: set[str] = set()
        self._snapshot_locks: Dict[str, asyncio.Lock] = {}

    async def get_new_order_book(self, trading_pair: str) -> OrderBook:
        book = await super().get_new_order_book(trading_pair)
        if trading_pair in self._v3_pairs:
            # Keep the tracker-owned object fresh, including dynamically added pairs.
            self._v3_books[trading_pair] = book
            self._v3_books_ready.set()
        return book

    async def _refresh_v3_order_books(self) -> None:
        while True:
            await self._v3_books_ready.wait()
            for pair, book in list(self._v3_books.items()):
                if pair not in self._trading_pairs:
                    del self._v3_books[pair]
                    continue
                if pair in self._snapshot_disabled_pairs:
                    continue
                if self._time() < max(self._snapshot_rate_limit_until, self._snapshot_retry_at.get(pair, 0)):
                    book.apply_snapshot([], [], book.snapshot_uid)
                    continue
                try:
                    snapshot = await self._order_book_snapshot(pair)
                    if snapshot.update_id <= book.snapshot_uid:
                        raise IOError(f"Non-increasing Bitget V3 snapshot timestamp for {pair}")
                    book.apply_snapshot(snapshot.bids, snapshot.asks, snapshot.update_id)
                except asyncio.CancelledError:
                    raise
                except (IOError, ValueError, TypeError, KeyError) as exc:
                    # Consumers must not mistake an old REST-only book for live depth.
                    book.apply_snapshot([], [], book.snapshot_uid)
                    self.logger().warning("Bitget V3 order book unavailable for %s: %s", pair, exc)
                    self._snapshot_retry_at[pair] = self._time() + CONSTANTS.ORDERBOOK_ERROR_BACKOFF_SECONDS
            if not self._v3_books:
                self._v3_books_ready.clear()
            await self._sleep(CONSTANTS.ORDERBOOK_V3_REFRESH_SECONDS)

    async def get_last_traded_prices(
        self,
        trading_pairs: List[str],
        domain: Optional[str] = None
    ) -> Dict[str, float]:
        return await self._connector.get_last_traded_prices(trading_pairs=trading_pairs)

    async def _parse_pong_message(self) -> None:
        self.logger().debug("PING-PONG message for order book completed")

    async def _process_message_for_unknown_channel(
        self,
        event_message: Dict[str, Any],
        websocket_assistant: WSAssistant,
    ) -> None:
        if event_message == CONSTANTS.PUBLIC_WS_PONG_RESPONSE:
            await self._parse_pong_message()
        elif "event" in event_message:
            if event_message["event"] == "error":
                message = event_message.get("msg", "Unknown error")
                error_code = event_message.get("code", "Unknown code")
                raise IOError(f"Failed to subscribe to public channels: {message} ({error_code})")

            if event_message["event"] == "subscribe":
                channel: str = event_message["arg"]["channel"]
                self.logger().info(f"Subscribed to public channel: {channel.upper()}")
        else:
            self.logger().info(f"Message for unknown channel received: {event_message}")

    def _channel_originating_message(self, event_message: Dict[str, Any]) -> Optional[str]:
        channel: Optional[str] = None

        if "arg" in event_message and "action" in event_message:
            arg: Dict[str, Any] = event_message["arg"]
            response_channel: Optional[str] = arg.get("channel")

            if response_channel == CONSTANTS.PUBLIC_WS_BOOKS:
                action: Optional[str] = event_message.get("action")
                channels = {
                    "snapshot": self._snapshot_messages_queue_key,
                    "update": self._diff_messages_queue_key
                }
                channel = channels.get(action)
            elif response_channel == CONSTANTS.PUBLIC_WS_TRADE:
                channel = self._trade_messages_queue_key

        return channel

    async def _parse_any_order_book_message(
        self,
        data: Dict[str, Any],
        symbol: str,
        message_type: OrderBookMessageType,
    ) -> OrderBookMessage:
        """
        Parse a WebSocket message into an OrderBookMessage for snapshots or diffs.

        :param raw_message: The raw WebSocket message.
        :param message_type: The type of order book message (SNAPSHOT or DIFF).

        :return: The parsed order book message.
        """
        trading_pair: str = await self._connector.trading_pair_associated_to_exchange_symbol(symbol)
        if trading_pair in self._v3_pairs:
            raise IOError(f"V2 depth cannot update REST-only V3 order book {trading_pair}")
        update_id: int = int(data["ts"])
        timestamp: float = update_id * 1e-3

        order_book_message_content: Dict[str, Any] = {
            "trading_pair": trading_pair,
            "update_id": update_id,
            "bids": data["bids"],
            "asks": data["asks"],
        }

        return OrderBookMessage(
            message_type=message_type,
            content=order_book_message_content,
            timestamp=timestamp
        )

    async def _parse_order_book_diff_message(
        self,
        raw_message: Dict[str, Any],
        message_queue: asyncio.Queue
    ) -> None:
        diffs_data: Dict[str, Any] = raw_message["data"]
        symbol: str = raw_message["arg"]["instId"]

        for diff in diffs_data:
            if await self._is_v3_symbol(symbol):
                return
            diff_message: OrderBookMessage = await self._parse_any_order_book_message(
                data=diff,
                symbol=symbol,
                message_type=OrderBookMessageType.DIFF
            )

            message_queue.put_nowait(diff_message)

    async def _parse_order_book_snapshot_message(
        self,
        raw_message: Dict[str, Any],
        message_queue: asyncio.Queue
    ) -> None:
        snapshot_data: Dict[str, Any] = raw_message["data"]
        symbol: str = raw_message["arg"]["instId"]

        for snapshot in snapshot_data:
            if await self._is_v3_symbol(symbol):
                return
            snapshot_message: OrderBookMessage = await self._parse_any_order_book_message(
                data=snapshot,
                symbol=symbol,
                message_type=OrderBookMessageType.SNAPSHOT
            )

            message_queue.put_nowait(snapshot_message)

    async def _is_v3_symbol(self, symbol: str) -> bool:
        # V2 acknowledgements can uppercase a case-sensitive r-symbol.
        for pair in self._v3_pairs:
            if (await self._connector.exchange_symbol_associated_to_pair(pair)).casefold() == symbol.casefold():
                return True
        return False

    async def _parse_trade_message(
        self,
        raw_message: Dict[str, Any],
        message_queue: asyncio.Queue
    ) -> None:
        data: List[Dict[str, Any]] = raw_message["data"]
        symbol: str = raw_message["arg"]["instId"]
        if await self._is_v3_symbol(symbol):
            return
        trading_pair: str = await self._connector.trading_pair_associated_to_exchange_symbol(symbol)

        for trade_data in data:
            trade_type: float = float(TradeType.BUY.value) \
                if trade_data["side"] == "buy" else float(TradeType.SELL.value)
            message_content: Dict[str, Any] = {
                "trade_id": int(trade_data["tradeId"]),
                "trading_pair": trading_pair,
                "trade_type": trade_type,
                "amount": trade_data["size"],
                "price": trade_data["price"],
            }
            trade_message = OrderBookMessage(
                message_type=OrderBookMessageType.TRADE,
                content=message_content,
                timestamp=int(trade_data["ts"]) * 1e-3,
            )
            message_queue.put_nowait(trade_message)

    async def _connected_websocket_assistant(self) -> WSAssistant:
        websocket_assistant: WSAssistant = await self._api_factory.get_ws_assistant()

        await websocket_assistant.connect(
            ws_url=web_utils.public_ws_url(),
            message_timeout=CONSTANTS.SECONDS_TO_WAIT_TO_RECEIVE_MESSAGE,
        )

        return websocket_assistant

    async def _subscribe_channels(self, ws: WSAssistant) -> None:
        try:
            subscription_topics: List[Dict[str, str]] = []

            for trading_pair in self._trading_pairs:
                if trading_pair in self._v3_pairs:
                    continue
                symbol: str = await self._connector.exchange_symbol_associated_to_pair(
                    trading_pair
                )
                for channel in [CONSTANTS.PUBLIC_WS_BOOKS, CONSTANTS.PUBLIC_WS_TRADE]:
                    subscription_topics.append({
                        "instType": "SPOT",
                        "channel": channel,
                        "instId": symbol
                    })

            if subscription_topics:
                await ws.send(
                    WSJSONRequest({
                        "op": "subscribe",
                        "args": subscription_topics,
                    })
                )
                self.logger().info("Subscribed to public channels...")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger().exception("Unexpected error occurred subscribing to public channels...")
            raise

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        lock = self._snapshot_locks.setdefault(trading_pair, asyncio.Lock())
        async with lock:
            return await self._request_order_book_snapshot_locked(trading_pair)

    async def _request_order_book_snapshot_locked(self, trading_pair: str) -> Dict[str, Any]:
        if trading_pair in self._snapshot_disabled_pairs:
            raise IOError(f"Bitget V3 order book disabled after 40502 for {trading_pair}")
        if self._time() < max(self._snapshot_rate_limit_until, self._snapshot_retry_at.get(trading_pair, 0)):
            raise IOError(f"Bitget order book request in backoff for {trading_pair}")
        symbol: str = await self._connector.exchange_symbol_associated_to_pair(trading_pair)
        rest_assistant: RESTAssistant = await self._api_factory.get_rest_assistant()
        for _ in range(2):
            use_v3 = trading_pair in self._v3_pairs
            endpoint = CONSTANTS.PUBLIC_ORDERBOOK_V3_ENDPOINT if use_v3 else CONSTANTS.PUBLIC_ORDERBOOK_ENDPOINT
            params = {"symbol": symbol, "limit": "100"}
            if use_v3:
                params["category"] = "SPOT"
            response = await rest_assistant.execute_request_and_get_response(
                url=web_utils.public_rest_url(path_url=endpoint),
                params=params,
                method=RESTMethod.GET,
                throttler_limit_id=endpoint,
                return_err=True,
                timeout=CONSTANTS.ORDERBOOK_SNAPSHOT_TIMEOUT_SECONDS,
            )
            if response.status == 429:
                delay = self._connector._retry_after_seconds(response.headers)
                self._snapshot_rate_limit_until = self._time() + max(
                    CONSTANTS.ORDERBOOK_ERROR_BACKOFF_SECONDS, delay or 0)
                raise IOError(f"Bitget order book HTTP 429 for {trading_pair}")
            try:
                data = await response.json()
            except (ValueError, TypeError) as exc:
                raise IOError(f"Invalid Bitget order book JSON for {trading_pair}") from exc
            if isinstance(data, dict) and str(data.get("code")) == "429":
                delay = self._connector._retry_after_seconds(response.headers)
                self._snapshot_rate_limit_until = self._time() + max(
                    CONSTANTS.ORDERBOOK_ERROR_BACKOFF_SECONDS, delay or 0)
                raise IOError(f"Bitget order book rate limited for {trading_pair}")
            if isinstance(data, dict) and str(data.get("code")) == CONSTANTS.RET_CODE_V3_REQUIRED:
                if use_v3:
                    self._snapshot_disabled_pairs.add(trading_pair)
                    raise IOError(f"Bitget V3 order book also returned 40502 for {trading_pair}")
                self._v3_pairs.add(trading_pair)
                self.logger().warning("Bitget order book %s requires V3; using full REST snapshots only", trading_pair)
                continue
            if response.status >= 400 or not isinstance(data, dict) or data.get("code") != CONSTANTS.RET_CODE_OK:
                self._snapshot_retry_at[trading_pair] = self._time() + CONSTANTS.ORDERBOOK_ERROR_BACKOFF_SECONDS
                raise IOError(f"Bitget order book request failed for {trading_pair}: HTTP {response.status}, {data}")
            if use_v3:
                depth = data.get("data")
                if not isinstance(depth, dict):
                    raise IOError(f"Invalid Bitget V3 order book data for {trading_pair}")
                data = {**data, "data": {"bids": depth.get("b"), "asks": depth.get("a"), "ts": depth.get("ts")}}
            return data
        raise IOError(f"Bitget order book version negotiation failed for {trading_pair}")

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        snapshot_response: Dict[str, Any] = await self._request_order_book_snapshot(trading_pair)
        snapshot_data: Dict[str, Any] = snapshot_response["data"]
        try:
            update_id = int(snapshot_data["ts"])
            if update_id <= 0 or str(update_id) != str(snapshot_data["ts"]):
                raise ValueError("Invalid timestamp")
            for side, descending in (("bids", True), ("asks", False)):
                levels = snapshot_data[side]
                if not isinstance(levels, list) or not levels:
                    raise ValueError(f"Missing {side}")
                prices = []
                for level in levels:
                    if not isinstance(level, (list, tuple)) or len(level) != 2:
                        raise ValueError("Invalid price level")
                    price, size = (Decimal(str(v)) for v in level)
                    if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
                        raise ValueError("Invalid price or size")
                    prices.append(price)
                if prices != sorted(set(prices), reverse=descending):
                    raise ValueError(f"Unordered or duplicate {side}")
            if Decimal(str(snapshot_data["bids"][0][0])) >= Decimal(str(snapshot_data["asks"][0][0])):
                raise ValueError("Crossed order book")
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise IOError(f"Invalid Bitget order book snapshot for {trading_pair}: {exc}") from exc
        timestamp: float = update_id * 1e-3

        order_book_message_content: Dict[str, Any] = {
            "trading_pair": trading_pair,
            "update_id": update_id,
            "bids": snapshot_data["bids"],
            "asks": snapshot_data["asks"],
        }

        return OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            timestamp
        )

    async def _send_ping(self, websocket_assistant: WSAssistant) -> None:
        ping_request = WSPlainTextRequest(CONSTANTS.PUBLIC_WS_PING_REQUEST)

        await websocket_assistant.send(ping_request)

    async def send_interval_ping(self, websocket_assistant: WSAssistant) -> None:
        """
        Coroutine to send PING messages periodically.

        :param websocket_assistant: The websocket assistant to use to send the PING message.
        """
        try:
            while True:
                await self._send_ping(websocket_assistant)
                await asyncio.sleep(CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL)
        except asyncio.CancelledError:
            self.logger().info("Interval PING task cancelled")
            raise
        except Exception:
            self.logger().exception("Error sending interval PING")

    async def listen_for_subscriptions(self) -> NoReturn:
        refresh_task = asyncio.create_task(self._refresh_v3_order_books())
        stream_task = asyncio.create_task(self._listen_for_v2_subscriptions())
        try:
            await asyncio.gather(refresh_task, stream_task)
        finally:
            refresh_task.cancel()
            stream_task.cancel()
            await asyncio.gather(refresh_task, stream_task, return_exceptions=True)

    async def _listen_for_v2_subscriptions(self) -> NoReturn:
        ws: Optional[WSAssistant] = None
        while True:
            try:
                ws: WSAssistant = await self._connected_websocket_assistant()
                await self._subscribe_channels(ws)
                self._ping_task = asyncio.create_task(self.send_interval_ping(ws))
                await self._process_websocket_messages(websocket_assistant=ws)
            except asyncio.CancelledError:
                raise
            except ConnectionError as connection_exception:
                self.logger().warning(
                    f"The websocket connection was closed ({connection_exception})"
                )
            except Exception:
                self.logger().exception(
                    "Unexpected error occurred when listening to order book streams. "
                    "Retrying in 5 seconds...",
                )
                await self._sleep(1.0)
            finally:
                if self._ping_task is not None:
                    self._ping_task.cancel()
                    try:
                        await self._ping_task
                    except asyncio.CancelledError:
                        pass
                    self._ping_task = None
                await self._on_order_stream_interruption(websocket_assistant=ws)
