"""
Dynamic Pair Manager

Professional two-tier system for managing trading pairs:
- Tier 1 (WebSocket): Active trading pairs with real-time order books (max 25-30)
- Tier 2 (REST API): All available pairs scanned periodically for discovery

This allows the bot to:
1. Monitor ALL available pairs (500+) via REST API
2. Trade only the best 25-30 via WebSocket
3. Dynamically rotate pairs based on performance
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PairMetrics:
    """Metrics for a trading pair from REST API scan"""
    symbol: str
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    spread_pct: float = 0.0
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    last_scanned: float = 0.0
    score: float = 0.0  # Composite score for ranking

    def calculate_score(
            self,
            volume_weight: float = 0.4,
            trend_weight: float = 0.4,
            spread_weight: float = 0.2) -> float:
        """
        Calculate composite score for pair ranking

        Higher score = better candidate for trading
        """
        # Normalize volume (log scale, 0-100)
        volume_score = min(100, max(0, (self.volume_24h / 100000) * 10)) if self.volume_24h > 0 else 0

        # Trend score: positive trend is better (-10% to +10% mapped to 0-100)
        trend_score = min(100, max(0, (self.price_change_24h + 10) * 5))

        # Spread score: lower spread is better (0% to 1% mapped to 100-0)
        spread_score = max(0, 100 - (self.spread_pct * 100))

        self.score = (
            volume_score * volume_weight
            + trend_score * trend_weight
            + spread_score * spread_weight
        )
        return self.score


class DynamicPairManager:
    """
    Manages dynamic pair discovery and selection

    This class scans ALL available pairs via REST API and selects
    the best candidates for WebSocket subscription.
    """

    def __init__(
        self,
        connector,
        quote_asset: str = "EUR",
        max_active_pairs: int = 25,
        min_volume_24h: float = 100000,  # €100k minimum
        max_spread_pct: float = 0.5,  # 0.5% max spread
        scan_interval_seconds: int = 300,  # Scan every 5 minutes
        blacklist: Optional[List[str]] = None
    ):
        self.connector = connector
        self.quote_asset = quote_asset.upper()
        self.max_active_pairs = max_active_pairs
        self.min_volume_24h = min_volume_24h
        self.max_spread_pct = max_spread_pct
        self.scan_interval_seconds = scan_interval_seconds
        self.blacklist = set(blacklist or [])

        # State
        self.all_pairs: Dict[str, PairMetrics] = {}  # All scanned pairs
        self.active_pairs: Set[str] = set()  # Currently active (Tier 1)
        self.candidate_pairs: List[str] = []  # Ranked candidates for promotion
        self.last_full_scan: float = 0.0
        self._scan_lock = asyncio.Lock()

    async def initialize(self) -> Set[str]:
        """
        Initialize by scanning all pairs and selecting initial active set

        Returns:
            Set of pairs to subscribe to via WebSocket
        """
        logger.info("=" * 80)
        logger.info("🔍 DYNAMIC PAIR MANAGER: Initial Scan Starting")
        logger.info("=" * 80)

        await self.full_scan()

        # Select initial active pairs
        self.active_pairs = self._select_best_pairs(self.max_active_pairs)

        logger.info(f"✅ Selected {len(self.active_pairs)} pairs for WebSocket subscription")
        logger.info(f"   Active pairs: {sorted(self.active_pairs)[:10]}...")

        return self.active_pairs

    async def full_scan(self) -> int:
        """
        Scan ALL available pairs via REST API

        Returns:
            Number of pairs scanned
        """
        async with self._scan_lock:
            try:
                start_time = time.time()

                # Get all trading pairs from exchange
                logger.info(f"📊 Fetching all {self.quote_asset} pairs from exchange...")

                # Get trading pair map
                # bidict: keys = exchange native format (e.g. "ADAEUR"),
                #         values = hummingbot format (e.g. "ADA-EUR")
                trading_pair_map = await self.connector.trading_pair_symbol_map()
                all_symbols = list(trading_pair_map.values())

                # Filter to quote asset pairs (values are already in "BASE-QUOTE" format)
                quote_pairs = [
                    p for p in all_symbols
                    if p.endswith(f"-{self.quote_asset}") or p.endswith(f"/{self.quote_asset}")
                ]

                # Normalize format (use - instead of /)
                quote_pairs = [p.replace("/", "-") for p in quote_pairs]

                # Remove blacklisted pairs
                quote_pairs = [p for p in quote_pairs if p not in self.blacklist]

                logger.info(f"📊 Found {len(quote_pairs)} {self.quote_asset} pairs (excluding blacklist)")

                # Fetch ticker data for all pairs
                # IMPORTANT: Use batch API call to avoid rate limits
                ticker_data = await self._fetch_all_tickers(quote_pairs)

                # Update pair metrics
                scanned_count = 0
                for symbol, ticker in ticker_data.items():
                    if symbol not in self.all_pairs:
                        self.all_pairs[symbol] = PairMetrics(symbol=symbol)

                    metrics = self.all_pairs[symbol]
                    metrics.volume_24h = ticker.get("volume_24h", 0)
                    metrics.price_change_24h = ticker.get("price_change_24h", 0)
                    metrics.last_price = ticker.get("last_price", 0)
                    metrics.bid = ticker.get("bid", 0)
                    metrics.ask = ticker.get("ask", 0)

                    # Calculate spread
                    if metrics.bid > 0 and metrics.ask > 0:
                        metrics.spread_pct = ((metrics.ask - metrics.bid) / metrics.bid) * 100

                    metrics.last_scanned = time.time()
                    metrics.calculate_score()
                    scanned_count += 1

                elapsed = time.time() - start_time
                self.last_full_scan = time.time()

                # Log summary
                qualified_pairs = [
                    p for p in self.all_pairs.values()
                    if p.volume_24h >= self.min_volume_24h and p.spread_pct <= self.max_spread_pct
                ]

                logger.info(f"✅ Full scan complete in {elapsed:.1f}s")
                logger.info(f"   Total pairs scanned: {scanned_count}")
                logger.info(
                    f"   Qualified pairs (vol>€{
                        self.min_volume_24h
                        / 1000:.0f}k, spread<{
                        self.max_spread_pct}%): {
                        len(qualified_pairs)}")

                # Log top 10
                top_10 = sorted(qualified_pairs, key=lambda x: x.score, reverse=True)[:10]
                logger.info("   Top 10 by score:")
                for i, p in enumerate(top_10, 1):
                    logger.info(
                        f"     {i}. {p.symbol}: score={p.score:.1f}, "
                        f"vol=€{p.volume_24h / 1000:.0f}k, trend={p.price_change_24h:+.2f}%, "
                        f"spread={p.spread_pct:.3f}%"
                    )

                return scanned_count

            except Exception as e:
                logger.error(f"❌ Error during full scan: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return 0

    async def _fetch_all_tickers(self, pairs: List[str]) -> Dict[str, dict]:
        """
        Fetch ticker data for all pairs via REST API.

        Routes to the exchange-specific implementation based on connector.name
        so that OKX instances never call the Kraken endpoint.
        """
        exchange = getattr(self.connector, "name", "").replace("_paper_trade", "").lower()
        if "okx" in exchange:
            return await self._fetch_okx_tickers()
        return await self._fetch_kraken_tickers(pairs)

    async def _fetch_okx_tickers(self) -> Dict[str, dict]:
        """
        Fetch all SPOT tickers from OKX public REST API.

        Field semantics (verified against live OKX API):
          vol24h     = 24h base-asset volume (e.g. OKB units)
          volCcy24h  = 24h quote-asset volume (USDC); this is what we want
          spread     = (askPx - bidPx) / bidPx  → stored as fraction (0.001 = 0.1%)
        """
        import aiohttp

        result: Dict[str, dict] = {}
        try:
            url = "https://www.okx.com/api/v5/market/tickers"
            params = {"instType": "SPOT"}
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        logger.warning(f"OKX tickers API returned status {response.status}")
                        return result
                    data = await response.json()

            for ticker in data.get("data", []):
                inst_id = ticker.get("instId", "")
                if not inst_id.endswith(f"-{self.quote_asset}"):
                    continue
                try:
                    bid = float(ticker.get("bidPx") or 0)
                    ask = float(ticker.get("askPx") or 0)
                    last = float(ticker.get("last") or 0)
                    # volCcy24h is the 24h quote-currency volume (USDC / EUR / …)
                    vol_quote = float(ticker.get("volCcy24h") or 0)
                    open24h = float(ticker.get("open24h") or 0)
                    price_change_24h = ((last - open24h) / open24h * 100) if open24h > 0 else 0.0
                    # spread stored as fraction so callers can do * 100 → pct (consistent with Kraken path)
                    spread = (ask - bid) / bid if bid > 0 else 0.0
                    result[inst_id] = {
                        "volume_24h": vol_quote,
                        "price_change_24h": price_change_24h,
                        "last_price": last,
                        "bid": bid,
                        "ask": ask,
                        "spread_frac": spread,
                    }
                except (ValueError, TypeError) as exc:
                    logger.debug(f"OKX ticker parse error for {inst_id}: {exc}")
                    continue

            logger.info(f"📊 Fetched OKX ticker data for {len(result)} {self.quote_asset} pairs")
        except Exception as exc:
            logger.error(f"Error fetching OKX tickers: {exc}")
        return result

    async def _fetch_kraken_tickers(self, pairs: List[str]) -> Dict[str, dict]:
        """Existing Kraken ticker fetch (unchanged)."""
        result = {}

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                url = "https://api.kraken.com/0/public/Ticker"

                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()

                        if data.get("error"):
                            logger.warning(f"Kraken API error: {data['error']}")
                            return result

                        ticker_data = data.get("result", {})

                        # Process ticker data
                        for kraken_symbol, ticker in ticker_data.items():
                            # Convert Kraken symbol to our format
                            # Kraken uses formats like "XXRPZEUR" -> "XRP-EUR"
                            symbol = self._convert_kraken_symbol(kraken_symbol)

                            if symbol and (symbol in pairs or symbol.replace("-", "/") in pairs):
                                try:
                                    # Kraken ticker format:
                                    # a = ask [price, whole lot volume, lot volume]
                                    # b = bid [price, whole lot volume, lot volume]
                                    # c = last trade closed [price, lot volume]
                                    # v = volume [today, last 24 hours]
                                    # p = volume weighted avg price [today, last 24 hours]
                                    # o = opening price [today]

                                    ask = float(ticker.get("a", [0])[0])
                                    bid = float(ticker.get("b", [0])[0])
                                    last = float(ticker.get("c", [0])[0])
                                    volume_24h = float(ticker.get("v", [0, 0])[1])
                                    open_price = float(ticker.get("o", 0))

                                    # Calculate 24h change
                                    price_change_24h = 0
                                    if open_price > 0:
                                        price_change_24h = ((last - open_price) / open_price) * 100

                                    # Volume in quote (EUR) - approximate
                                    volume_eur = volume_24h * last

                                    result[symbol] = {
                                        "volume_24h": volume_eur,
                                        "price_change_24h": price_change_24h,
                                        "last_price": last,
                                        "bid": bid,
                                        "ask": ask
                                    }
                                except (IndexError, ValueError, TypeError) as e:
                                    logger.debug(f"Error parsing ticker for {symbol}: {e}")
                                    continue

                        logger.info(f"📊 Fetched ticker data for {len(result)} pairs")
                    else:
                        logger.warning(f"Kraken API returned status {response.status}")

        except Exception as e:
            logger.error(f"Error fetching tickers: {e}")

        return result

    def _convert_kraken_symbol(self, kraken_symbol: str) -> Optional[str]:
        """
        Convert Kraken's internal symbol format to standard format

        Examples:
            XXRPZEUR -> XRP-EUR
            XETHZEUR -> ETH-EUR
            SOLUSD -> SOL-USD
        """
        # Common Kraken prefixes to strip

        # Known quote assets
        quote_assets = ["EUR", "USD", "USDT", "USDC", "BTC", "ETH"]

        symbol = kraken_symbol.upper()

        # Try to find the quote asset
        for quote in quote_assets:
            # Try with Z prefix (ZEUR)
            if symbol.endswith(f"Z{quote}"):
                base = symbol[:-len(f"Z{quote}")]
                # Remove X prefix from base if present
                if base.startswith("XX"):
                    base = base[2:]
                elif base.startswith("X") and len(base) > 3:
                    base = base[1:]
                return f"{base}-{quote}"

            # Try without Z prefix
            if symbol.endswith(quote):
                base = symbol[:-len(quote)]
                # Remove X prefix from base if present
                if base.startswith("XX"):
                    base = base[2:]
                elif base.startswith("X") and len(base) > 3:
                    base = base[1:]
                return f"{base}-{quote}"

        return None

    def _select_best_pairs(self, count: int) -> Set[str]:
        """
        Select the best pairs based on score

        Returns:
            Set of pair symbols
        """
        # Filter qualified pairs
        qualified = [
            p for p in self.all_pairs.values()
            if p.volume_24h >= self.min_volume_24h
            and p.spread_pct <= self.max_spread_pct
            and p.symbol not in self.blacklist
        ]

        # Sort by score (descending)
        sorted_pairs = sorted(qualified, key=lambda x: x.score, reverse=True)

        # Take top N
        selected = {p.symbol for p in sorted_pairs[:count]}

        # Update candidate list (pairs that didn't make it but are close)
        self.candidate_pairs = [p.symbol for p in sorted_pairs[count:count + 20]]

        return selected

    def get_promotion_candidates(self, current_underperformers: List[str]) -> List[Tuple[str, str]]:
        """
        Get pairs that could replace underperforming active pairs

        Args:
            current_underperformers: List of active pairs that are underperforming

        Returns:
            List of (old_pair, new_pair) tuples for recommended swaps
        """
        if not current_underperformers or not self.candidate_pairs:
            return []

        swaps = []
        candidates = self.candidate_pairs.copy()

        for old_pair in current_underperformers:
            if candidates:
                new_pair = candidates.pop(0)

                # Check if new pair is actually better
                old_metrics = self.all_pairs.get(old_pair)
                new_metrics = self.all_pairs.get(new_pair)

                if old_metrics and new_metrics and new_metrics.score > old_metrics.score * 1.2:
                    # New pair is at least 20% better
                    swaps.append((old_pair, new_pair))
                    logger.info(
                        f"📈 Recommending swap: {old_pair} (score={old_metrics.score:.1f}) -> "
                        f"{new_pair} (score={new_metrics.score:.1f})"
                    )

        return swaps

    def should_rescan(self) -> bool:
        """Check if it's time for a new full scan"""
        return time.time() - self.last_full_scan > self.scan_interval_seconds

    def get_active_pairs_list(self) -> List[str]:
        """Get sorted list of active pairs"""
        return sorted(self.active_pairs)

    def get_pair_metrics(self, symbol: str) -> Optional[PairMetrics]:
        """Get metrics for a specific pair"""
        return self.all_pairs.get(symbol)

    def get_summary(self) -> str:
        """Get a summary of the current state"""
        qualified = len([
            p for p in self.all_pairs.values()
            if p.volume_24h >= self.min_volume_24h and p.spread_pct <= self.max_spread_pct
        ])

        return (
            f"DynamicPairManager Summary:\n"
            f"  Total pairs scanned: {len(self.all_pairs)}\n"
            f"  Qualified pairs: {qualified}\n"
            f"  Active pairs (Tier 1): {len(self.active_pairs)}\n"
            f"  Candidate pairs: {len(self.candidate_pairs)}\n"
            f"  Last scan: {time.strftime('%H:%M:%S', time.localtime(self.last_full_scan))}\n"
        )
