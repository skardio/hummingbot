"""
Futures-specific extensions for the Bitget grid controller.
"""

from typing import Optional

from hummingbot.core.data_type.common import PositionMode
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.futures_bitget.config_schema import FuturesGridBitgetConfig, FuturesPositionMode


class FuturesGridBitgetController(MultiCoinGridController):
    """
    Adds Bitget-perpetual specific connector management (leverage + position mode).

    Also implements less restrictive multi-timeframe buy conditions for futures trading,
    allowing trading in bear markets with lower trend thresholds.
    """

    def __init__(self, *args, config: FuturesGridBitgetConfig, **kwargs):
        super().__init__(*args, config=config, **kwargs)
        self._position_mode_set = False

    def _initialize_components(self):
        initialized = super()._initialize_components()
        if self.connector and not self._position_mode_set:
            self._configure_position_mode()
        return initialized

    def _configure_position_mode(self):
        desired_mode = getattr(self.config, "position_mode", FuturesPositionMode.ONEWAY)
        if desired_mode is None:
            return

        target_mode = _convert_position_mode(desired_mode)
        connector_modes = getattr(self.connector, "supported_position_modes", lambda: [])()
        if connector_modes and target_mode not in connector_modes:
            self.logger().warning(
                f"⚠️  Desired position mode {target_mode.name} not supported by connector; "
                f"supported={connector_modes}"
            )
            self._position_mode_set = True
            return

        try:
            if hasattr(self.connector, "set_position_mode"):
                self.connector.set_position_mode(target_mode)
                self.logger().info(f"✅ Position mode set to {target_mode.name} for connector.")
        except Exception as e:
            self.logger().warning(f"⚠️  Failed to set position mode {target_mode.name}: {e}")
        finally:
            self._position_mode_set = True

    def _create_grid_action(self, symbol: str):
        action = super()._create_grid_action(symbol)
        if action is None:
            return None

        self._apply_leverage(symbol)
        return action

    def _apply_leverage(self, symbol: Optional[str]):
        leverage = getattr(self.config, "derivative_leverage", None)
        if leverage is None or symbol is None:
            return

        if hasattr(self.connector, "set_leverage"):
            try:
                self.connector.set_leverage(symbol, leverage)
                self.logger().debug(f"🎚️  Leverage set to x{leverage} for {symbol}.")
            except Exception as e:
                self.logger().warning(f"⚠️  Failed to set leverage x{leverage} for {symbol}: {e}")

    def _check_multi_timeframe_buy_conditions(self, coin: str) -> bool:
        """
        Override parent method with less restrictive conditions for futures trading.

        Futures-specific adjustments:
        - Lower thresholds for bear markets (0.1% instead of 1.0%)
        - Less strict warm-up mode requirements
        - Allow trading with weaker trends for futures volatility

        Args:
            coin: Coin symbol to check

        Returns:
            True if coin meets buy conditions
        """
        try:
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return False

            # Check if multi-timeframe data is available
            if not hasattr(trend, 'trend_60m'):
                # Multi-timeframe fields don't exist - fallback to old logic
                self.logger().debug(f"⚠️  Multi-timeframe fields not available for {coin} - allowing (fallback)")
                return True

            # FUTURES-SPECIFIC: Less restrictive warm-up mode
            if hasattr(trend, 'long_trend_warmup') and trend.long_trend_warmup:
                # Reduced requirements for futures during warm-up:
                # 1. 240m trend must be positive (> +0.3%) - was > +1.5% (further reduced)
                # 2. 60m trend must be >= -0.1% - was >= 0% (allow slight negative)
                # 3. Both must be positive (reject if both negative)

                warmup_240m_ok = trend.trend_240m > 0.3  # Further reduced from 0.5% to 0.3%
                warmup_60m_ok = trend.trend_60m >= -0.1  # Allow slight negative (-0.1%)
                both_positive = trend.trend_240m > 0.0 and trend.trend_60m > 0.0

                if warmup_240m_ok and warmup_60m_ok and both_positive:
                    self.logger().info(
                        f"[DECISION] ✅ {coin} BUY APPROVED (futures warm-up mode):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% (warm-up fallback) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                        f"   [SCORE] Composite: {trend.trend_score:+.2f}%\n"
                        f"   [NOTE] Futures mode: Using relaxed thresholds for bear markets"
                    )
                    return True
                else:
                    reasons = []
                    if not warmup_240m_ok:
                        reasons.append(f"4h trend ({trend.trend_240m:+.2f}%) <= +0.3% (futures warm-up requires > +0.3%)")
                    if not warmup_60m_ok:
                        reasons.append(f"1h trend ({trend.trend_60m:+.2f}%) < -0.1% (futures warm-up requires >= -0.1%)")
                    if not both_positive:
                        reasons.append(f"Both trends negative (4h: {trend.trend_240m:+.2f}%, 1h: {trend.trend_60m:+.2f}%)")

                    self.logger().warning(
                        f"[DECISION] ❌ {coin} BUY REJECTED (futures warm-up mode):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% (warm-up fallback) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                        f"   [REASON] {' | '.join(reasons)}"
                    )
                    return False

            # FUTURES-SPECIFIC: Lower thresholds for normal trading
            # Reduced from 1.0% to 0.1% to allow trading in bear markets
            trend_1440m_ok = trend.trend_1440m > 0.1  # Reduced from 1.0%
            trend_240m_ok = trend.trend_240m > 0.1  # Reduced from 1.0%
            trend_60m_ok = trend.trend_60m >= -0.2  # Allow slight negative (was >= 0%)

            # Still reject if both short-term trends are strongly negative
            declining_trend = trend.trend_60m < -1.0 and trend.trend_240m < -0.5

            if declining_trend:
                self.logger().warning(
                    f"[DECISION] ❌ {coin} BUY REJECTED: Strong declining trend detected!\n"
                    f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                    f"   [REASON] 1h trend ({trend.trend_60m:+.2f}%) < -1.0% AND 4h trend ({trend.trend_240m:+.2f}%) < -0.5%\n"
                    f"   [NOTE] Avoiding trade during strong declining trends"
                )
                return False

            if not trend_1440m_ok:
                self.logger().debug(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 24h trend ({trend.trend_1440m:+.2f}%) <= +0.1% (futures threshold)"
                )
                return False

            if not trend_240m_ok:
                self.logger().debug(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 4h trend ({trend.trend_240m:+.2f}%) <= +0.1% (futures threshold)"
                )
                return False

            if not trend_60m_ok:
                self.logger().debug(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 1h trend ({trend.trend_60m:+.2f}%) < -0.2% (futures threshold)"
                )
                return False

            # All conditions met
            self.logger().info(
                f"[DECISION] ✅ {coin} BUY APPROVED (futures mode):\n"
                f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                f"   [SCORE] Composite: {trend.trend_score:+.2f}%\n"
                f"   [NOTE] Futures mode: Using relaxed thresholds"
            )
            return True

        except Exception as e:
            self.logger().error(f"❌ Error checking multi-timeframe buy conditions for {coin}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # On error, allow (fail open)
            return True


def _convert_position_mode(mode: FuturesPositionMode) -> PositionMode:
    if isinstance(mode, FuturesPositionMode):
        return PositionMode[mode.name]
    if isinstance(mode, PositionMode):
        return mode
    return PositionMode[str(mode).upper()]
