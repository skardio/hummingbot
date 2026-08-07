# momentum_market_data.py — read-only REST fetcher + enrichment engine.
# Fetches public ticker, candle, and orderbook data from Kraken, OKX, Bitget.
# No orders. No authentication. No writes to any grid DB.
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from multi_coin_grid_pro.signals.momentum_indicators import apply_candle_metrics, apply_orderbook_metrics
from multi_coin_grid_pro.signals.momentum_models import CandleSnapshot, EnrichedCandidate, OrderBookSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------

class _BaseFetcher:
    """Shared HTTP helper and pair utilities."""

    def __init__(
        self,
        api_url: str,
        quote_assets: List[str],
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._quote_assets = set(quote_assets)
        self._session = session
        self._semaphore = semaphore
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    def _is_wanted_pair(self, pair: str) -> bool:
        """Return True if pair's quote asset is in the configured set."""
        parts = pair.split("-")
        return len(parts) == 2 and parts[1] in self._quote_assets

    async def _get_json(self, url: str, params: Optional[Dict] = None) -> Any:
        """HTTP GET protected by semaphore and timeout."""
        async with self._semaphore:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    # Subclasses override these for enrichment
    async def fetch_candles(
        self, internal_pair: str, limit: int = 20
    ) -> List[CandleSnapshot]:
        return []

    async def fetch_orderbook(
        self, internal_pair: str, count: int = 20
    ) -> Optional[OrderBookSnapshot]:
        return None


# ---------------------------------------------------------------------------
# Kraken
# ---------------------------------------------------------------------------

_KRAKEN_ASSET_MAP: Dict[str, str] = {
    "XBT": "BTC",
    "XDG": "DOGE",
}

_KRAKEN_BATCH_SIZE = 100


class KrakenFetcher(_BaseFetcher):
    """Fetch spot tickers, candles and orderbook from Kraken REST API.

    Pair-name mapping is built during fetch_candidates() and reused for
    subsequent fetch_candles() / fetch_orderbook() calls.
    """

    ASSET_PAIRS_URL = "/0/public/AssetPairs"
    TICKER_URL = "/0/public/Ticker"
    OHLC_URL = "/0/public/OHLC"
    DEPTH_URL = "/0/public/Depth"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # internal_pair (e.g. "BTC-USD") → kraken pair name (e.g. "XXBTZUSD")
        self._pair_name_map: Dict[str, str] = {}

    async def fetch_candidates(self) -> List[EnrichedCandidate]:
        try:
            pairs_raw = await self._get_json(self._api_url + self.ASSET_PAIRS_URL)
        except Exception as exc:
            logger.warning("Kraken AssetPairs fetch failed: %s", exc)
            return []

        pairs = self._filter_asset_pairs(pairs_raw)
        if not pairs:
            return []

        # Build reverse mapping: internal_pair → kraken_pair_name
        self._pair_name_map = {
            f"{base}-{quote}": kname for kname, (base, quote) in pairs.items()
        }

        kraken_names = list(pairs.keys())
        candidates: List[EnrichedCandidate] = []
        for i in range(0, len(kraken_names), _KRAKEN_BATCH_SIZE):
            batch = kraken_names[i: i + _KRAKEN_BATCH_SIZE]
            try:
                ticker_raw = await self._get_json(
                    self._api_url + self.TICKER_URL,
                    params={"pair": ",".join(batch)},
                )
            except Exception as exc:
                logger.warning("Kraken Ticker fetch failed (batch %d): %s", i, exc)
                continue
            for kname, data in ticker_raw.get("result", {}).items():
                pair_info = pairs.get(kname)
                if pair_info is None:
                    continue
                candidate = self._make_candidate(pair_info, data)
                if candidate is not None:
                    candidates.append(candidate)

        return candidates

    def _filter_asset_pairs(
        self, raw: Dict
    ) -> Dict[str, Tuple[str, str]]:
        """Return {kraken_pair_name: (base_symbol, quote_symbol)} for wanted pairs."""
        result: Dict[str, Tuple[str, str]] = {}
        for kname, info in raw.get("result", {}).items():
            if info.get("status") != "online":
                continue
            wsname = info.get("wsname", "")
            if "/" not in wsname:
                continue
            base_ws, quote_ws = wsname.split("/", 1)
            base = _KRAKEN_ASSET_MAP.get(base_ws, base_ws)
            quote = _KRAKEN_ASSET_MAP.get(quote_ws, quote_ws)
            if quote in self._quote_assets:
                result[kname] = (base, quote)
        return result

    def _make_candidate(
        self, pair_info: Tuple[str, str], data: Dict
    ) -> Optional[EnrichedCandidate]:
        base, quote = pair_info
        try:
            bid = float(data["b"][0])
            ask = float(data["a"][0])
            price = float(data["c"][0])
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        if bid <= 0 or ask <= 0 or price <= 0:
            return None
        # 24h data: v[1]=24h base volume, p[1]=24h VWAP, o=today open, h=24h high, l=24h low
        quote_volume_24h: Optional[float] = None
        price_change_24h_pct: Optional[float] = None
        high_24h: Optional[float] = None
        low_24h: Optional[float] = None
        try:
            v_24h = float(data["v"][1])
            p_24h = float(data["p"][1])
            if v_24h > 0 and p_24h > 0:
                quote_volume_24h = v_24h * p_24h
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        try:
            o_today = float(data["o"])
            if o_today > 0:
                price_change_24h_pct = (price - o_today) / o_today * 100.0
        except (KeyError, ValueError, TypeError):
            pass
        try:
            high_24h = float(data["h"][1])
            low_24h = float(data["l"][1])
            if high_24h <= 0 or low_24h <= 0:
                high_24h = None
                low_24h = None
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        return EnrichedCandidate(
            exchange="kraken",
            trading_pair=f"{base}-{quote}",
            price=price,
            bid=bid,
            ask=ask,
            spread_pct=(ask - bid) / bid * 100.0,
            quote_volume_24h=quote_volume_24h,
            price_change_24h_pct=price_change_24h_pct,
            high_24h=high_24h,
            low_24h=low_24h,
        )

    async def fetch_candles(
        self, internal_pair: str, limit: int = 20
    ) -> List[CandleSnapshot]:
        kraken_name = self._pair_name_map.get(internal_pair)
        if not kraken_name:
            logger.debug("Kraken: geen pair-naam voor %s", internal_pair)
            return []
        try:
            raw = await self._get_json(
                self._api_url + self.OHLC_URL,
                params={"pair": kraken_name, "interval": 1},
            )
        except Exception as exc:
            logger.warning("Kraken candles fetch failed (%s): %s", internal_pair, exc)
            return []
        result = raw.get("result", {})
        ohlc_data = None
        for k, v in result.items():
            if k != "last" and isinstance(v, list):
                ohlc_data = v
                break
        if not ohlc_data:
            return []
        # Each row: [ts, open, high, low, close, vwap, volume, count]
        candles: List[CandleSnapshot] = []
        for row in ohlc_data[-limit:]:
            try:
                candles.append(CandleSnapshot(
                    timestamp=float(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[6]),
                ))
            except (IndexError, ValueError, TypeError):
                continue
        return candles

    async def fetch_orderbook(
        self, internal_pair: str, count: int = 20
    ) -> Optional[OrderBookSnapshot]:
        kraken_name = self._pair_name_map.get(internal_pair)
        if not kraken_name:
            logger.debug("Kraken: geen pair-naam voor %s", internal_pair)
            return None
        try:
            raw = await self._get_json(
                self._api_url + self.DEPTH_URL,
                params={"pair": kraken_name, "count": count},
            )
        except Exception as exc:
            logger.warning("Kraken orderbook fetch failed (%s): %s", internal_pair, exc)
            return None
        result = raw.get("result", {})
        data = next(iter(result.values()), None) if result else None
        if not data:
            return None
        try:
            bids = [[float(p), float(a)] for p, a, *_ in data.get("bids", [])]
            asks = [[float(p), float(a)] for p, a, *_ in data.get("asks", [])]
        except (ValueError, TypeError):
            return None
        return OrderBookSnapshot(fetched_at=time.time(), bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# OKX
# ---------------------------------------------------------------------------

class OKXFetcher(_BaseFetcher):
    """Fetch spot tickers, candles and orderbook from OKX REST API.

    OKX instId format is already "BASE-QUOTE" (e.g. "BTC-USDT").
    """

    TICKERS_URL = "/api/v5/market/tickers"
    CANDLES_URL = "/api/v5/market/candles"
    BOOKS_URL = "/api/v5/market/books"

    async def fetch_candidates(self) -> List[EnrichedCandidate]:
        try:
            raw = await self._get_json(
                self._api_url + self.TICKERS_URL,
                params={"instType": "SPOT"},
            )
        except Exception as exc:
            logger.warning("OKX ticker fetch failed: %s", exc)
            return []

        candidates: List[EnrichedCandidate] = []
        for item in raw.get("data", []):
            try:
                candidate = self._parse_item(item)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:
                logger.debug("OKX parse error: %s", exc)
        return candidates

    def _parse_item(self, item: Dict) -> Optional[EnrichedCandidate]:
        inst_id = item.get("instId", "")
        if not self._is_wanted_pair(inst_id):
            return None
        bid = float(item.get("bidPx") or 0)
        ask = float(item.get("askPx") or 0)
        price = float(item.get("last") or 0)
        if bid <= 0 or ask <= 0 or price <= 0:
            return None
        # 24h data: open24h, volCcy24h, high24h, low24h
        quote_volume_24h: Optional[float] = None
        price_change_24h_pct: Optional[float] = None
        high_24h: Optional[float] = None
        low_24h: Optional[float] = None
        try:
            open_24h = float(item.get("open24h") or 0)
            if open_24h > 0:
                price_change_24h_pct = (price - open_24h) / open_24h * 100.0
        except (ValueError, TypeError):
            pass
        try:
            vol_ccy = float(item.get("volCcy24h") or 0)
            if vol_ccy > 0:
                quote_volume_24h = vol_ccy
        except (ValueError, TypeError):
            pass
        try:
            h = float(item.get("high24h") or 0)
            low = float(item.get("low24h") or 0)
            if h > 0 and low > 0:
                high_24h = h
                low_24h = low
        except (ValueError, TypeError):
            pass
        return EnrichedCandidate(
            exchange="okx",
            trading_pair=inst_id,
            price=price,
            bid=bid,
            ask=ask,
            spread_pct=(ask - bid) / bid * 100.0,
            quote_volume_24h=quote_volume_24h,
            price_change_24h_pct=price_change_24h_pct,
            high_24h=high_24h,
            low_24h=low_24h,
        )

    async def fetch_candles(
        self, internal_pair: str, limit: int = 20
    ) -> List[CandleSnapshot]:
        try:
            raw = await self._get_json(
                self._api_url + self.CANDLES_URL,
                params={"instId": internal_pair, "bar": "1m", "limit": str(limit)},
            )
        except Exception as exc:
            logger.warning("OKX candles fetch failed (%s): %s", internal_pair, exc)
            return []
        # data is newest-first: [ts_ms, o, h, l, c, vol, volCcyCoin, volCcyQuote, confirm]
        candles: List[CandleSnapshot] = []
        for row in reversed(raw.get("data", [])):
            try:
                candles.append(CandleSnapshot(
                    timestamp=float(row[0]) / 1000.0,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))
            except (IndexError, ValueError, TypeError):
                continue
        return candles

    async def fetch_orderbook(
        self, internal_pair: str, count: int = 20
    ) -> Optional[OrderBookSnapshot]:
        try:
            raw = await self._get_json(
                self._api_url + self.BOOKS_URL,
                params={"instId": internal_pair, "sz": str(count)},
            )
        except Exception as exc:
            logger.warning("OKX orderbook fetch failed (%s): %s", internal_pair, exc)
            return None
        data = raw.get("data", [])
        if not data:
            return None
        ob = data[0]
        try:
            bids = [[float(b[0]), float(b[1])] for b in ob.get("bids", [])]
            asks = [[float(a[0]), float(a[1])] for a in ob.get("asks", [])]
        except (ValueError, TypeError, IndexError):
            return None
        return OrderBookSnapshot(fetched_at=time.time(), bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# Bitget
# ---------------------------------------------------------------------------

_BITGET_QUOTE_SUFFIXES = ["USDT", "USDC", "USD", "EUR", "BTC", "ETH"]


def _normalize_bitget_pair(symbol: str) -> str:
    """Convert 'BTCUSDT' → 'BTC-USDT'."""
    for q in _BITGET_QUOTE_SUFFIXES:
        if symbol.endswith(q):
            return f"{symbol[:-len(q)]}-{q}"
    return symbol


def _internal_to_bitget_symbol(internal_pair: str) -> str:
    """Convert 'SOL-USDT' → 'SOLUSDT'."""
    return internal_pair.replace("-", "")


class BitgetFetcher(_BaseFetcher):
    """Fetch spot tickers, candles and orderbook from Bitget REST API."""

    TICKERS_URL = "/api/v2/spot/market/tickers"
    CANDLES_URL = "/api/v2/spot/market/candles"
    ORDERBOOK_URL = "/api/v2/spot/market/orderbook"

    async def fetch_candidates(self) -> List[EnrichedCandidate]:
        try:
            raw = await self._get_json(self._api_url + self.TICKERS_URL)
        except Exception as exc:
            logger.warning("Bitget ticker fetch failed: %s", exc)
            return []

        candidates: List[EnrichedCandidate] = []
        for item in raw.get("data", []):
            try:
                candidate = self._parse_item(item)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:
                logger.debug("Bitget parse error: %s", exc)
        return candidates

    def _parse_item(self, item: Dict) -> Optional[EnrichedCandidate]:
        symbol = item.get("symbol", "")
        pair = _normalize_bitget_pair(symbol)
        if not self._is_wanted_pair(pair):
            return None
        bid = float(item.get("bidPr") or 0)
        ask = float(item.get("askPr") or 0)
        price = float(item.get("lastPr") or 0)
        if bid <= 0 or ask <= 0 or price <= 0:
            return None
        # 24h data: open, quoteVolume, high24h, low24h
        quote_volume_24h: Optional[float] = None
        price_change_24h_pct: Optional[float] = None
        high_24h: Optional[float] = None
        low_24h: Optional[float] = None
        try:
            open_24h = float(item.get("open") or 0)
            if open_24h > 0:
                price_change_24h_pct = (price - open_24h) / open_24h * 100.0
        except (ValueError, TypeError):
            pass
        try:
            qvol = float(item.get("quoteVolume") or 0)
            if qvol > 0:
                quote_volume_24h = qvol
        except (ValueError, TypeError):
            pass
        try:
            h = float(item.get("high24h") or 0)
            low = float(item.get("low24h") or 0)
            if h > 0 and low > 0:
                high_24h = h
                low_24h = low
        except (ValueError, TypeError):
            pass
        return EnrichedCandidate(
            exchange="bitget",
            trading_pair=pair,
            price=price,
            bid=bid,
            ask=ask,
            spread_pct=(ask - bid) / bid * 100.0,
            quote_volume_24h=quote_volume_24h,
            price_change_24h_pct=price_change_24h_pct,
            high_24h=high_24h,
            low_24h=low_24h,
        )

    async def fetch_candles(
        self, internal_pair: str, limit: int = 20
    ) -> List[CandleSnapshot]:
        symbol = _internal_to_bitget_symbol(internal_pair)
        try:
            raw = await self._get_json(
                self._api_url + self.CANDLES_URL,
                params={"symbol": symbol, "granularity": "1min", "limit": str(limit)},
            )
        except Exception as exc:
            logger.warning("Bitget candles fetch failed (%s): %s", internal_pair, exc)
            return []
        # data is OLDEST-first: [ts_ms, open, high, low, close, baseVol, quoteVol]
        # (API docs claim newest-first but actual response is ascending — no reversal needed)
        candles: List[CandleSnapshot] = []
        for row in raw.get("data", []):
            try:
                candles.append(CandleSnapshot(
                    timestamp=float(row[0]) / 1000.0,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))
            except (IndexError, ValueError, TypeError):
                continue
        return candles

    async def fetch_orderbook(
        self, internal_pair: str, count: int = 20
    ) -> Optional[OrderBookSnapshot]:
        symbol = _internal_to_bitget_symbol(internal_pair)
        try:
            raw = await self._get_json(
                self._api_url + self.ORDERBOOK_URL,
                params={"symbol": symbol, "type": "step0", "limit": str(count)},
            )
        except Exception as exc:
            logger.warning("Bitget orderbook fetch failed (%s): %s", internal_pair, exc)
            return None
        data = raw.get("data", {})
        if not data:
            return None
        try:
            bids = [[float(b[0]), float(b[1])] for b in data.get("bids", [])]
            asks = [[float(a[0]), float(a[1])] for a in data.get("asks", [])]
        except (ValueError, TypeError, IndexError):
            return None
        return OrderBookSnapshot(fetched_at=time.time(), bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# Bitvavo
# ---------------------------------------------------------------------------

class BitvavoFetcher(_BaseFetcher):
    """Fetch spot tickers, candles and orderbook from Bitvavo REST API.

    Bitvavo market format is already "BASE-QUOTE" (e.g. "BTC-EUR").
    """

    TICKERS_URL = "/v2/ticker/24h"

    async def fetch_candidates(self) -> List[EnrichedCandidate]:
        try:
            raw = await self._get_json(self._api_url + self.TICKERS_URL)
        except Exception as exc:
            logger.warning("Bitvavo ticker fetch failed: %s", exc)
            return []

        candidates: List[EnrichedCandidate] = []
        for item in (raw if isinstance(raw, list) else []):
            try:
                candidate = self._parse_item(item)
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:
                logger.debug("Bitvavo parse error: %s", exc)
        return candidates

    def _parse_item(self, item: Dict) -> Optional[EnrichedCandidate]:
        market = item.get("market", "")
        if not self._is_wanted_pair(market):
            return None
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        price = float(item.get("last") or 0)
        if bid <= 0 or ask <= 0 or price <= 0:
            return None
        quote_volume_24h: Optional[float] = None
        price_change_24h_pct: Optional[float] = None
        try:
            vol_q = float(item.get("volumeQuote") or 0)
            if vol_q > 0:
                quote_volume_24h = vol_q
        except (ValueError, TypeError):
            pass
        try:
            open_24h = float(item.get("open") or 0)
            if open_24h > 0:
                price_change_24h_pct = (price - open_24h) / open_24h * 100.0
        except (ValueError, TypeError):
            pass
        high_24h: Optional[float] = None
        low_24h: Optional[float] = None
        try:
            h = float(item.get("high") or 0)
            low = float(item.get("low") or 0)
            if h > 0 and low > 0:
                high_24h = h
                low_24h = low
        except (ValueError, TypeError):
            pass
        return EnrichedCandidate(
            exchange="bitvavo",
            trading_pair=market,
            price=price,
            bid=bid,
            ask=ask,
            spread_pct=(ask - bid) / bid * 100.0,
            quote_volume_24h=quote_volume_24h,
            price_change_24h_pct=price_change_24h_pct,
            high_24h=high_24h,
            low_24h=low_24h,
        )

    async def fetch_candles(
        self, internal_pair: str, limit: int = 20
    ) -> List[CandleSnapshot]:
        url = f"{self._api_url}/v2/{internal_pair}/candles"
        try:
            raw = await self._get_json(url, params={"interval": "1m", "limit": str(limit)})
        except Exception as exc:
            logger.warning("Bitvavo candles fetch failed (%s): %s", internal_pair, exc)
            return []
        # data is newest-first: [timestamp_ms, open, high, low, close, volume]
        candles: List[CandleSnapshot] = []
        for row in reversed(raw if isinstance(raw, list) else []):
            try:
                candles.append(CandleSnapshot(
                    timestamp=float(row[0]) / 1000.0,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))
            except (IndexError, ValueError, TypeError):
                continue
        return candles

    async def fetch_orderbook(
        self, internal_pair: str, count: int = 20
    ) -> Optional[OrderBookSnapshot]:
        url = f"{self._api_url}/v2/{internal_pair}/book"
        try:
            raw = await self._get_json(url)
        except Exception as exc:
            logger.warning("Bitvavo orderbook fetch failed (%s): %s", internal_pair, exc)
            return None
        try:
            bids = [[float(b[0]), float(b[1])] for b in raw.get("bids", [])[:count]]
            asks = [[float(a[0]), float(a[1])] for a in raw.get("asks", [])[:count]]
        except (ValueError, TypeError, IndexError):
            return None
        return OrderBookSnapshot(fetched_at=time.time(), bids=bids, asks=asks)


# ---------------------------------------------------------------------------
# Fetcher registry
# ---------------------------------------------------------------------------

_FETCHER_MAP = {
    "kraken": KrakenFetcher,
    "okx": OKXFetcher,
    "bitget": BitgetFetcher,
    "bitvavo": BitvavoFetcher,
}


# ---------------------------------------------------------------------------
# MarketDataFetcher — orchestrates ticker + enrichment
# ---------------------------------------------------------------------------

class MarketDataFetcher:
    """Fetch EnrichedCandidates from all configured exchanges concurrently,
    then optionally enrich them with candles and orderbook data.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        max_concurrency: int = 5,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._session = session
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout_seconds
        # Populated during fetch_all — reused for enrichment
        self._fetchers: Dict[str, _BaseFetcher] = {}

    def get_fetcher(self, exchange: str) -> Optional[_BaseFetcher]:
        """Return the cached fetcher for an exchange (populated after fetch_all)."""
        return self._fetchers.get(exchange.lower())

    async def fetch_exchange(
        self,
        exchange: str,
        api_url: str,
        quote_assets: List[str],
    ) -> List[EnrichedCandidate]:
        fetcher_cls = _FETCHER_MAP.get(exchange.lower())
        if fetcher_cls is None:
            logger.warning("Geen fetcher beschikbaar voor exchange: %s", exchange)
            return []
        fetcher = fetcher_cls(
            api_url=api_url,
            quote_assets=quote_assets,
            session=self._session,
            semaphore=self._semaphore,
            timeout_seconds=self._timeout,
        )
        self._fetchers[exchange.lower()] = fetcher
        return await fetcher.fetch_candidates()

    async def fetch_all(self, exchange_configs: List) -> List[EnrichedCandidate]:
        """Fetch all exchanges concurrently. Logs (not raises) per-exchange errors."""
        tasks = []
        for cfg in exchange_configs:
            if not cfg.enabled:
                logger.info("[SKIP] Exchange %s is disabled — skipping fetch", cfg.exchange)
                continue
            tasks.append(self.fetch_exchange(cfg.exchange, cfg.api_url, cfg.effective_quote_assets()))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: List[EnrichedCandidate] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Exchange fetch error: %s", result)
            else:
                candidates.extend(result)
        return candidates

    async def enrich_all(
        self,
        candidates: List[EnrichedCandidate],
        market_data_config,
        exchange_configs: List,
        now: float,
    ) -> List[EnrichedCandidate]:
        """Enrich candidates with candles and orderbook data (in-place mutation).

        Uses the fetcher instances cached by fetch_all() so Kraken's pair
        name map is already populated.
        """
        by_exchange: Dict[str, List[EnrichedCandidate]] = {}
        for c in candidates:
            by_exchange.setdefault(c.exchange.lower(), []).append(c)

        tasks = []
        for cfg in exchange_configs:
            exc_name = cfg.exchange.lower()
            exc_candidates = by_exchange.get(exc_name, [])
            if not exc_candidates:
                continue
            fetcher = self._fetchers.get(exc_name)
            if fetcher is None:
                logger.warning("Geen fetcher voor enrichment van '%s'", exc_name)
                continue
            tasks.append(
                self._enrich_exchange(exc_candidates, fetcher, market_data_config, now)
            )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return candidates

    async def _enrich_exchange(
        self,
        candidates: List[EnrichedCandidate],
        fetcher: _BaseFetcher,
        cfg,
        now: float,
    ) -> None:
        """Enrich candidates for one exchange with candles + orderbook."""
        mode = cfg.mode
        max_n = cfg.max_enriched_pairs_per_exchange

        if mode == "sample" and len(candidates) > max_n:
            # Fallback sort by spread when no preselection has already limited the list
            to_enrich = sorted(candidates, key=lambda c: c.spread_pct)[:max_n]
        else:
            # Either full mode, or already preselected (len <= max_n)
            to_enrich = list(candidates)

        if not to_enrich:
            return

        exc_name = fetcher.__class__.__name__.replace("Fetcher", "").lower()
        logger.info(
            "[ENRICH] %s: %d pairs (mode=%s)", exc_name, len(to_enrich), mode
        )
        min_ob_delay = cfg.rate_limits.min_seconds_between_orderbook_calls

        # 1. Fetch all candles concurrently
        candle_tasks = [
            fetcher.fetch_candles(c.trading_pair, limit=20) for c in to_enrich
        ]
        candle_results = await asyncio.gather(*candle_tasks, return_exceptions=True)

        for candidate, result in zip(to_enrich, candle_results):
            if isinstance(result, Exception):
                logger.debug(
                    "Candle fetch error for %s: %s", candidate.trading_pair, result
                )
            elif result:
                apply_candle_metrics(candidate, result, now)

        # 2. Fetch orderbooks sequentially with per-call delay
        for i, candidate in enumerate(to_enrich):
            if i > 0:
                await asyncio.sleep(min_ob_delay)
            try:
                ob = await fetcher.fetch_orderbook(candidate.trading_pair)
                if ob is not None:
                    apply_orderbook_metrics(candidate, ob)
            except Exception as exc:
                logger.debug(
                    "OB fetch error for %s: %s", candidate.trading_pair, exc
                )
