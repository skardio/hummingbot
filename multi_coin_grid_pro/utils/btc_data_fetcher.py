"""
BTC Data Fetcher for Market Regime Filter

Fetches BTC price and trend data using the existing TrendCalculator infrastructure.
"""

import logging
from decimal import Decimal
from typing import Optional

from multi_coin_grid_pro.filters.market_regime_filter import BTCTrendData
from multi_coin_grid_pro.utils.trend_calculator import TrendCalculator

logger = logging.getLogger(__name__)


class BTCDataFetcher:
    """
    Fetches BTC trend data for Market Regime Filter.

    Wraps TrendCalculator to provide BTC-specific data in BTCTrendData format.
    """

    def __init__(self, trend_calculator: TrendCalculator, btc_symbol: str = "BTC-EUR"):
        """
        Initialize BTC data fetcher.

        Args:
            trend_calculator: Existing TrendCalculator instance
            btc_symbol: BTC trading pair symbol (default: BTC-EUR)
        """
        self.trend_calculator = trend_calculator
        self.btc_symbol = btc_symbol
        self._data_unavailable_logged = False  # Only log once
        logger.info(f"📊 BTCDataFetcher initialized for {btc_symbol}")

    def get_btc_trend_data(self) -> Optional[BTCTrendData]:
        """
        Get current BTC trend data.

        Returns:
            BTCTrendData object or None if data not available
        """
        # Get BTC trend from TrendCalculator
        btc_trend = self.trend_calculator.trends.get(self.btc_symbol)

        if not btc_trend:
            # Only log warning once during startup
            if not self._data_unavailable_logged:
                logger.info(f"⏳ Waiting for BTC trend data ({self.btc_symbol})... (collecting history)")
                self._data_unavailable_logged = True
            return None

        if not btc_trend.has_sufficient_data:
            if not self._data_unavailable_logged:
                logger.info(f"⏳ Collecting BTC history... ({len(getattr(btc_trend, 'price_history', []))} points)")
                self._data_unavailable_logged = True
            return None

        # Data available now - reset flag for next time it's unavailable
        if self._data_unavailable_logged:
            logger.info(f"✅ BTC trend data now available ({self.btc_symbol})")
            self._data_unavailable_logged = False

        # Extract trend data
        from datetime import datetime

        btc_data = BTCTrendData(
            price=btc_trend.current_price,
            trend_1h_pct=btc_trend.trend_60m,
            trend_4h_pct=btc_trend.trend_240m,
            trend_24h_pct=btc_trend.trend_1440m,
            timestamp=datetime.fromtimestamp(btc_trend.last_updated),
        )

        return btc_data

    async def ensure_btc_data_loaded(self) -> bool:
        """
        Ensure BTC historical data is loaded.

        Returns:
            True if BTC data is available, False otherwise
        """
        # Check if BTC data exists
        if self.btc_symbol not in self.trend_calculator.trends:
            logger.info(f"📥 Loading historical data for {self.btc_symbol}...")
            await self.trend_calculator.load_historical_data([self.btc_symbol])

        # Verify data is available
        btc_trend = self.trend_calculator.trends.get(self.btc_symbol)
        if btc_trend and btc_trend.has_sufficient_data:
            logger.info(f"✅ BTC data loaded: {len(btc_trend.price_history)} data points")
            return True
        else:
            logger.error(f"❌ Failed to load BTC data")
            return False
