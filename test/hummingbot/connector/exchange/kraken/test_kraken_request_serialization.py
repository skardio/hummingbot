import asyncio
import base64
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from hummingbot.connector.exchange.kraken.kraken_auth import KrakenAuth
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest
from hummingbot.core.web_assistant.rest_assistant import RESTAssistant


class KrakenRequestSerializationTests(IsolatedAsyncioTestCase):
    def auth(self, key="key"):
        auth = KrakenAuth(key, base64.b64encode(b"secret").decode(), MagicMock())
        auth.rest_authenticate = AsyncMock(wraps=auth.rest_authenticate)
        return auth

    def assistant(self, auth, call):
        return RESTAssistant(MagicMock(call=call), AsyncThrottler([]), auth=auth)

    def request(self, private=True):
        return RESTRequest(method=RESTMethod.POST, url="https://api.kraken.com/0/private/Balance",
                           is_auth_required=private)

    async def scheduled_call(self, assistant, private=True):
        # FIFO loop marker runs after the newly scheduled task's first suspension.
        task = asyncio.create_task(assistant.call(self.request(private)))
        marker = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(marker.set_result, None)
        await marker
        return task

    async def test_same_key_serializes_nonce_and_send_across_auth_instances(self):
        started, release = asyncio.Event(), asyncio.Event()
        nonces = []

        async def send(request):
            nonces.append(int(request.data["nonce"]))
            started.set()
            await release.wait()
            return MagicMock()

        first_auth, second_auth = self.auth(), self.auth()
        first = asyncio.create_task(self.assistant(first_auth, send).call(self.request()))
        await started.wait()
        second = await self.scheduled_call(self.assistant(second_auth, send))
        self.assertEqual(1, len(nonces))
        second_auth.rest_authenticate.assert_not_awaited()
        self.assertFalse(second.done())
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(2, len(nonces))
        self.assertLess(nonces[0], nonces[1])

    async def test_lock_covers_authentication_before_http_starts(self):
        authenticated, release = asyncio.Event(), asyncio.Event()
        first_auth, second_auth = self.auth(), self.auth()
        original_authenticate = first_auth.rest_authenticate

        async def authenticate(request):
            request = await original_authenticate(request)
            authenticated.set()
            await release.wait()
            return request

        first_auth.rest_authenticate = authenticate
        send = AsyncMock(return_value=MagicMock())
        first = asyncio.create_task(self.assistant(first_auth, send).call(self.request()))
        await authenticated.wait()
        second = await self.scheduled_call(self.assistant(second_auth, send))
        send.assert_not_awaited()
        second_auth.rest_authenticate.assert_not_awaited()
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(2, send.await_count)

    async def assert_independent(self, private, second_key):
        started, release = asyncio.Event(), asyncio.Event()

        async def blocked_send(request):
            started.set()
            await release.wait()
            return MagicMock()

        first = asyncio.create_task(self.assistant(self.auth(), blocked_send).call(self.request()))
        await started.wait()
        other_auth = self.auth(second_key)
        other_send = AsyncMock(return_value=MagicMock())
        try:
            await asyncio.wait_for(self.assistant(other_auth, other_send).call(self.request(private)), 1)
            other_send.assert_awaited_once()
            self.assertFalse(first.done())
            if not private:
                other_auth.rest_authenticate.assert_not_awaited()
        finally:
            release.set()
            await first

    async def test_public_request_is_not_blocked(self):
        await self.assert_independent(False, "key")

    async def test_different_keys_are_not_blocked(self):
        await self.assert_independent(True, "other-key")

    async def test_http_exception_releases_lock_for_waiting_request(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def send(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                raise OSError("HTTP failure")
            return MagicMock()

        assistant = self.assistant(self.auth(), send)
        first = asyncio.create_task(assistant.call(self.request()))
        await started.wait()
        second = await self.scheduled_call(assistant)
        release.set()
        with self.assertRaises(OSError):
            await first
        await second
        self.assertEqual(2, calls)

    async def test_auth_exception_releases_lock(self):
        auth = self.auth()
        auth.rest_authenticate.side_effect = ValueError("authentication failure")
        assistant = self.assistant(auth, AsyncMock(return_value=MagicMock()))
        with self.assertRaises(ValueError):
            await assistant.call(self.request())
        auth.rest_authenticate.side_effect = None
        await assistant.call(self.request())

    async def test_cancellation_releases_lock(self):
        started = asyncio.Event()

        async def send(request):
            started.set()
            await asyncio.Event().wait()

        assistant = self.assistant(self.auth(), send)
        first = asyncio.create_task(assistant.call(self.request()))
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        assistant._connection.call = AsyncMock(return_value=MagicMock())
        await assistant.call(self.request())
