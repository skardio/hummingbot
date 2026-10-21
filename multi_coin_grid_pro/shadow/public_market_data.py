"""Public, unauthenticated market-data adapter for the A/B shadow sandbox.

Uses ``ccxt.async_support.kraken`` with **no API key or secret ever
configured** — every method it exposes only touches Kraken's public ticker
endpoints. This is a completely independent HTTP client from
``hummingbot.connector.exchange.kraken.kraken_exchange`` and
``hummingbot.connector.exchange.kraken.kraken_auth`` — it shares no code,
no nonce generator, and no connection pool with the live, authenticated bot.

Exposes exactly the three methods ``TrendCalculator`` needs from a
"connector" (``name``, ``get_last_traded_prices``, ``get_mid_price``), so the
real, already-tested ``TrendCalculator``/``GridSuitabilityScorer`` can be
reused unmodified for both ranking variants.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _to_ccxt_symbol(trading_pair: str) -> str:
    """"BASE-QUOTE" (Hummingbot convention) -> "BASE/QUOTE" (ccxt convention)."""
    return trading_pair.replace("-", "/")


def _to_hb_symbol(ccxt_symbol: str) -> str:
    """"BASE/QUOTE" (ccxt convention) -> "BASE-QUOTE" (Hummingbot convention)."""
    return ccxt_symbol.replace("/", "-")


class PublicKrakenMarketAdapter:
    """Read-only, public-data-only stand-in for a Hummingbot connector.

    SAFETY: never pass ``apiKey``/``secret`` to the underlying ccxt client.
    This class intentionally does not accept credentials in its constructor.
    """

    name = "kraken"

    def __init__(self):
        import ccxt.async_support as ccxt_async

        # No apiKey / secret — public endpoints only. ccxt raises on
        # unauthenticated calls to private endpoints, which this adapter
        # never calls, so there is no risk of an accidental private call
        # silently succeeding with blank credentials.
        self._exchange = ccxt_async.kraken({"enableRateLimit": True})
        self._last_prices: Dict[str, Decimal] = {}

    async def close(self) -> None:
        await self._exchange.close()

    async def get_last_traded_prices(self, trading_pairs: List[str]) -> Dict[str, Decimal]:
        """Batch-fetch last-traded prices via Kraken's public ticker endpoint."""
        ccxt_symbols = [_to_ccxt_symbol(tp) for tp in trading_pairs]
        result: Dict[str, Decimal] = {}
        try:
            tickers = await self._exchange.fetch_tickers(ccxt_symbols)
        except Exception as e:
            logger.warning(f"⚠️  shadow public market data: fetch_tickers failed: {e}")
            return result
        for ccxt_symbol, ticker in tickers.items():
            last = ticker.get("last") or ticker.get("close")
            if last is None:
                continue
            hb_symbol = _to_hb_symbol(ccxt_symbol)
            price = Decimal(str(last))
            result[hb_symbol] = price
            self._last_prices[hb_symbol] = price
        return result

    def get_mid_price(self, trading_pair: str) -> Optional[Decimal]:
        """Synchronous fallback using the last price seen by get_last_traded_prices.

        TrendCalculator only calls this as a fallback path; the cache is
        populated by the async batch call above.
        """
        return self._last_prices.get(trading_pair)

    async def fetch_ohlcv(self, trading_pair: str, timeframe: str = "5m", limit: int = 720):
        """Public 5-minute OHLCV candles, same data TrendCalculator.load_historical_data()
        already fetches via ccxt for the live bot — reused here verbatim, independently."""
        ccxt_symbol = _to_ccxt_symbol(trading_pair)
        try:
            return await self._exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            logger.warning(f"⚠️  shadow public market data: fetch_ohlcv({trading_pair}) failed: {e}")
            return []
