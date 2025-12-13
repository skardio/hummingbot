"""
Market Regime Integration

Integrates Market Regime Filter into the coin selection process.
This module wraps the trend calculator's get_best_coin() to add market regime awareness.
"""

import logging
from typing import Dict, List, Optional

from multi_coin_grid_pro.filters.market_regime_filter import MarketRegimeConfig, MarketRegimeFilter, MarketRegimeState
from multi_coin_grid_pro.utils.btc_data_fetcher import BTCDataFetcher
from multi_coin_grid_pro.utils.trend_calculator import TrendCalculator

logger = logging.getLogger(__name__)


class MarketRegimeIntegration:
    """
    Integrates Market Regime Filter with coin selection.

    Adds macro-level market filtering BEFORE coin-level analysis.
    """

    def __init__(
        self,
        trend_calculator: TrendCalculator,
        regime_config: MarketRegimeConfig,
        enabled: bool = True,
    ):
        """
        Initialize market regime integration.

        Args:
            trend_calculator: Existing TrendCalculator instance
            regime_config: Market regime filter configuration
            enabled: Whether market regime filtering is enabled
        """
        self.trend_calculator = trend_calculator
        self.regime_config = regime_config
        self.enabled = enabled

        if self.enabled:
            self.regime_filter = MarketRegimeFilter(regime_config)
            self.btc_fetcher = BTCDataFetcher(
                trend_calculator=trend_calculator,
                btc_symbol=regime_config.btc_reference_pair,
            )
            logger.info("✅ Market Regime Integration enabled")
        else:
            self.regime_filter = None
            self.btc_fetcher = None
            logger.info("⚠️  Market Regime Integration disabled")

    def get_market_regime_state(self) -> Optional[MarketRegimeState]:
        """
        Get current market regime state.

        Returns:
            MarketRegimeState or None if disabled/unavailable
        """
        if not self.enabled or not self.regime_filter:
            return None

        # Get BTC trend data
        btc_data = self.btc_fetcher.get_btc_trend_data()
        if not btc_data:
            logger.warning("⚠️ BTC data not available for regime check")
            return None

        # Get altcoin trends for breadth calculation
        altcoin_trends = self._get_altcoin_trends()

        # Check market regime
        regime_state = self.regime_filter.check_market_regime(
            btc_trend_data=btc_data,
            altcoin_trends=altcoin_trends,
        )

        return regime_state

    def get_best_coin_with_regime_check(
        self,
        min_trend_pct: float,
        exclude_coins: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Get best coin with market regime check.

        This is the MAIN method to use instead of trend_calculator.get_best_coin().
        It adds market regime awareness on top of coin-level selection.

        Args:
            min_trend_pct: Minimum trend percentage required
            exclude_coins: Optional list of coin symbols to exclude

        Returns:
            Symbol of best coin or None if market regime is unfavorable
        """
        # Check market regime first (macro filter)
        if self.enabled:
            regime_state = self.get_market_regime_state()

            if regime_state and not regime_state.is_favorable:
                logger.warning(f"🌍 Market Regime UNFAVORABLE: {regime_state.reason}")
                logger.info("   ⏸️  Skipping coin selection (waiting for better market conditions)")
                return None
            elif regime_state:
                # Only log if favorable (avoid spam)
                if not hasattr(self, '_last_favorable_log') or \
                   (regime_state.last_updated - self._last_favorable_log).total_seconds() > 300:
                    logger.info(f"🌍 Market Regime OK: {regime_state.reason}")
                    self._last_favorable_log = regime_state.last_updated

        # Market regime is OK (or disabled) - proceed with normal coin selection
        best_coin = self.trend_calculator.get_best_coin(
            min_trend_pct=min_trend_pct,
            exclude_coins=exclude_coins,
        )

        return best_coin

    def _get_altcoin_trends(self) -> Dict[str, float]:
        """
        Get 1h trends for altcoins (for breadth calculation).

        Returns:
            Dict of {symbol: trend_1h_pct}
        """
        altcoin_trends = {}

        for symbol in self.regime_config.altcoin_breadth_pairs:
            trend = self.trend_calculator.trends.get(symbol)
            if trend and trend.has_sufficient_data:
                altcoin_trends[symbol] = trend.trend_60m

        return altcoin_trends

    async def initialize(self) -> bool:
        """
        Initialize market regime filter (load BTC data).

        Should be called during bot startup after trend calculator is ready.

        Returns:
            True if successfully initialized, False otherwise
        """
        if not self.enabled:
            logger.info("⚠️ Market regime filter disabled, skipping initialization")
            return True

        logger.info("🌍 Initializing Market Regime Filter...")

        # Ensure BTC data is loaded
        success = await self.btc_fetcher.ensure_btc_data_loaded()

        if success:
            logger.info("✅ Market Regime Filter initialized successfully")

            # Get initial regime state
            regime_state = self.get_market_regime_state()
            if regime_state:
                logger.info(f"   Initial state: {regime_state.reason}")
        else:
            logger.error("❌ Failed to initialize Market Regime Filter")

        return success

    def get_cached_regime_state(self) -> Optional[MarketRegimeState]:
        """Get last cached regime state (for monitoring)"""
        if self.enabled and self.regime_filter:
            return self.regime_filter.get_cached_state()
        return None

    def reset_cooldown(self):
        """Manually reset dump cooldown (emergency override)"""
        if self.enabled and self.regime_filter:
            self.regime_filter.reset_cooldown()

    def force_pause(self, reason: str, duration_minutes: int = 60):
        """Manually force a pause (for manual intervention)"""
        if self.enabled and self.regime_filter:
            self.regime_filter.force_pause(reason, duration_minutes)
