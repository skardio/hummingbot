"""
Coin Discovery Utility

Discovers tradeable coins on the exchange based on volume and liquidity criteria.
"""

import logging
from decimal import Decimal
from typing import List

from hummingbot.connector.connector_base import ConnectorBase

logger = logging.getLogger(__name__)


class CoinDiscovery:
    """
    Discovers and filters tradeable coins on an exchange

    This class identifies viable trading pairs based on:
    - Volume requirements
    - Quote asset (e.g., EUR, USDT)
    - Price filtering (exclude very expensive coins)
    """

    def __init__(
        self,
        connector: ConnectorBase,
        quote_asset: str,
        min_24h_volume: Decimal,
        max_coins: int = 20,
        exclude_expensive: bool = True
    ):
        """
        Initialize coin discovery

        Args:
            connector: Exchange connector
            quote_asset: Quote currency (e.g., "EUR", "USDT")
            min_24h_volume: Minimum 24h volume in quote asset
            max_coins: Maximum number of coins to monitor
            exclude_expensive: Whether to exclude BTC/ETH
        """
        self.connector = connector
        self.quote_asset = quote_asset.upper()
        self.min_24h_volume = min_24h_volume
        self.max_coins = max_coins
        self.exclude_expensive = exclude_expensive

        # Priority coins to check first (most liquid)
        self.priority_coins = [
            "BTC", "ETH", "SOL", "XRP", "ADA",
            "DOT", "AVAX", "LINK", "MATIC", "UNI",
            "ATOM", "LTC", "BCH", "NEAR", "APT",
            "ARB", "OP", "SUI", "ALGO", "FIL"
        ]

    async def discover_coins(self) -> List[str]:
        """
        Discover tradeable coins on the exchange

        Returns:
            List of trading pair symbols (e.g., ["XRP/EUR", "ADA/EUR"])
        """
        try:
            trading_pair_map = await self.connector.trading_pair_symbol_map()
            all_markets = list(trading_pair_map.keys())

            # Filter pairs by quote asset
            quote_pairs = [p for p in all_markets if f"-{self.quote_asset}" in p or f"/{self.quote_asset}" in p]
            logger.info(f"Discovered {len(quote_pairs)} {self.quote_asset} pairs")

            # Return first 20
            result = quote_pairs[:20]
            return result

        except Exception as e:
            logger.error(f"Exception in discover_coins: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # DO NOT RETURN FALLBACK - LET IT FAIL SO WE SEE THE ERROR!
            raise

        # OLD CODE BELOW - keeping for reference
        print(f"\n{'=' * 80}")
        print("🔍 COIN DISCOVERY START")
        print(f"{'=' * 80}")
        logger.info("🔍 Starting coin discovery...")
        logger.info(
            f"DEBUG: quote_asset={
                self.quote_asset}, max_coins={
                self.max_coins}, min_volume={
                self.min_24h_volume}")
        logger.info(f"DEBUG: connector type={type(self.connector)}, ready={self.connector.ready}")
        print(f"DEBUG: quote_asset={self.quote_asset}, connector ready={self.connector.ready}")

        try:
            # Get ALL trading pairs from the exchange via trading_pair_symbol_map
            # This is the CORRECT way to get all available pairs, not just the ones we're initialized with
            print("   Getting trading_pair_symbol_map from connector...")
            logger.info("   Getting all trading pairs via trading_pair_symbol_map...")

            # Wait for the symbol map to be loaded
            trading_pair_map = await self.connector.trading_pair_symbol_map()
            print(f"   Got trading_pair_symbol_map with {len(trading_pair_map)} pairs")
            logger.info(f"   Got {len(trading_pair_map)} trading pairs from symbol map")

            # Get all trading pairs (these are in Hummingbot format like "BTC-EUR")
            all_markets = list(trading_pair_map.keys())
            logger.info(f"   Total available markets: {len(all_markets)}")

            # Filter to quote asset pairs
            quote_pairs = [
                pair for pair in all_markets
                if f"-{self.quote_asset}" in pair or f"/{self.quote_asset}" in pair
            ]

            logger.info(f"   Found {len(quote_pairs)} {self.quote_asset} pairs")

            # Build priority list
            available_pairs = []
            for base in self.priority_coins:
                # Try different formats
                for pair_format in [f"{base}/{self.quote_asset}", f"{base}-{self.quote_asset}"]:
                    if pair_format in quote_pairs:
                        available_pairs.append(pair_format)
                        break

            logger.info(f"   Checking {len(available_pairs)} priority pairs for volume...")

            # Fetch volume data and filter
            coin_data = []
            for symbol in available_pairs:
                try:
                    # Get 24h ticker data
                    logger.info(f"      Testing {symbol}...")
                    ticker = await self.connector.get_quote_volume_for_base_amount(
                        symbol, Decimal("1")
                    )

                    # Get price
                    price = await self.connector.get_price_by_type(
                        symbol,
                        price_type=self.connector.PriceType.MidPrice
                    )

                    # Estimate 24h volume (rough approximation)
                    # In real implementation, would use proper volume endpoint
                    volume_estimate = ticker * price if ticker else Decimal("0")

                    if volume_estimate >= self.min_24h_volume:
                        coin_data.append({
                            'symbol': symbol,
                            'volume': volume_estimate,
                            'price': price
                        })
                        logger.info(f"      ✓ {symbol:12} | Volume: €{volume_estimate:,.0f} | Price: €{price:.4f}")
                        print(f"      ✓ {symbol:12} | Volume: €{volume_estimate:,.0f} | Price: €{price:.4f}")

                except Exception as e:
                    logger.warning(f"      ✗ Skip {symbol}: {e}")
                    print(f"      ✗ Skip {symbol}: {e}")
                    continue

            # Filter expensive coins if requested
            if self.exclude_expensive:
                btc_eth_pairs = [f"BTC/{self.quote_asset}", f"ETH/{self.quote_asset}",
                                 f"BTC-{self.quote_asset}", f"ETH-{self.quote_asset}"]
                coin_data = [c for c in coin_data if c['symbol'] not in btc_eth_pairs]
                logger.info("   🚫 Excluded BTC/ETH (too expensive)")

            # Sort by price (lowest first - more volatile)
            coin_data.sort(key=lambda x: x['price'])

            # Take top N
            selected = coin_data[:self.max_coins]
            symbols = [c['symbol'] for c in selected]

            # If no coins passed filter, use fallback
            if not symbols:
                logger.warning("⚠️  No coins passed volume filter")
                return self._get_fallback_coins()

            logger.info(f"\n✅ Selected {len(symbols)} coins:")
            for i, coin in enumerate(selected, 1):
                logger.info(
                    f"   {i:2}. {coin['symbol']:12} | "
                    f"Volume: €{coin['volume']:>12,.0f} | "
                    f"Price: €{coin['price']:.4f}"
                )

            return symbols

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"❌ Error discovering coins: {e}")
            logger.error(f"Traceback:\n{error_trace}")
            # Fallback to hardcoded list
            logger.warning("⚠️  Using fallback coin list")
            return self._get_fallback_coins()

    def _get_fallback_coins(self) -> List[str]:
        """Fallback coin list if discovery fails"""
        fallback = [
            f"XRP/{self.quote_asset}",
            f"ADA/{self.quote_asset}",
            f"DOT/{self.quote_asset}",
            f"SOL/{self.quote_asset}",
            f"LINK/{self.quote_asset}",
            f"STRK/{self.quote_asset}",  # Starknet - goede volume
            f"FIS/{self.quote_asset}",   # Stafi Protocol
            f"ALCX/{self.quote_asset}",  # Alchemix
            f"OGN/{self.quote_asset}",   # Origin Protocol
            f"VELODROME/{self.quote_asset}",  # Velodrome Finance
            f"0G/{self.quote_asset}",    # 0G - goede volume
            f"ATOM/{self.quote_asset}",  # Cosmos (altijd goed)
            f"MATIC/{self.quote_asset}",  # Polygon
            f"AVAX/{self.quote_asset}",  # Avalanche
            f"UNI/{self.quote_asset}"    # Uniswap
        ]
        logger.info(f"   Fallback: {', '.join(fallback)}")
        return fallback
