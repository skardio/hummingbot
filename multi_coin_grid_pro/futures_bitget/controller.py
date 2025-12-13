"""
Futures-specific extensions for the Bitget grid controller.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from hummingbot.core.data_type.common import PositionMode
from hummingbot.strategy_v2.models.executor_actions import ExecutorAction, StopExecutorAction
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.futures_bitget.config_schema import FuturesGridBitgetConfig, FuturesPositionMode
from multi_coin_grid_pro.futures_bitget.risk_guard import FuturesGridRiskGuard


class FuturesGridBitgetController(MultiCoinGridController):
    """
    Adds Bitget-perpetual specific connector management (leverage + position mode).

    Also implements less restrictive multi-timeframe buy conditions for futures trading,
    allowing trading in bear markets with lower trend thresholds.
    """

    def __init__(self, *args, config: FuturesGridBitgetConfig, **kwargs):
        super().__init__(*args, config=config, **kwargs)
        self._position_mode_set = False
        self.liquidation_prices: Dict[str, Dict[str, Decimal]] = {}

        # Risk Guard: centralized kill-switch logic
        self.risk_guard = FuturesGridRiskGuard(self)

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
            self.liquidation_prices.pop(symbol, None)
            return None

        self._apply_leverage(symbol)
        self._calculate_liquidation_buffer(symbol)

        # Notificeer RiskGuard: nieuwe grid gestart
        self.risk_guard.notify_grid_started(symbol)

        return action

    def _apply_leverage(self, symbol: Optional[str]):
        leverage = getattr(self.config, "derivative_leverage", None)
        if leverage is None or symbol is None:
            return

        if hasattr(self.connector, "set_leverage"):
            try:
                buffer_pct = float(getattr(self.config, "liquidation_buffer_pct", 0.2))
                safe_leverage = max(1, int(leverage * (1 - buffer_pct)))
                if safe_leverage < leverage:
                    self.logger().info(
                        f"⚖️  Adjusting leverage from x{leverage} to x{safe_leverage} "
                        f"to preserve {buffer_pct:.0%} liquidation buffer."
                    )
                self.connector.set_leverage(symbol, safe_leverage)
                self.logger().debug(f"🎚️  Leverage set to x{safe_leverage} for {symbol}.")
            except Exception as e:
                self.logger().warning(f"⚠️  Failed to set leverage x{leverage} for {symbol}: {e}")

    def _calculate_liquidation_buffer(self, symbol: str) -> None:
        """
        Approximate liquidation distance for the active futures grid and
        track a warning threshold that triggers a defensive exit.
        """
        leverage = getattr(self.config, "derivative_leverage", None)
        entry_price = self.entry_prices.get(symbol)
        if leverage in (None, 0) or entry_price is None:
            self.liquidation_prices.pop(symbol, None)
            return

        entry_price_dec = Decimal(str(entry_price))
        leverage_dec = Decimal(str(leverage))
        if leverage_dec <= 1:
            self.liquidation_prices.pop(symbol, None)
            return

        # Simple isolated-margin approximation where liquidation occurs when loss equals margin
        baseline_liq = entry_price_dec * (Decimal("1") - (Decimal("1") / leverage_dec))
        baseline_liq = max(baseline_liq, Decimal("0"))

        buffer_pct = Decimal(str(getattr(self.config, "liquidation_buffer_pct", 0.2)))
        buffer_price = entry_price_dec * (Decimal("1") - buffer_pct)

        # Gebruik config: hoeveel % van de afstand tot liquidatie willen we veilig houden
        safety_distance = Decimal(str(self.config.liquidation_safety_distance_pct))
        safe_exit_price = entry_price_dec - (entry_price_dec - baseline_liq) * safety_distance
        warning_price = max(buffer_price, safe_exit_price)

        self.liquidation_prices[symbol] = {
            "entry": entry_price_dec,
            "liquidation": baseline_liq,
            "warning": warning_price,
        }

        self.logger().info(
            f"🛡️  {symbol} liquidation guard set: "
            f"entry={entry_price_dec:.4f}, "
            f"liquidation≈{baseline_liq:.4f}, "
            f"warning_exit={warning_price:.4f}"
        )

    def _monitor_liquidation_risk(self) -> Optional[StopExecutorAction]:
        if not self.active_coin or self.active_coin not in self.liquidation_prices:
            return None

        buffer = self.liquidation_prices[self.active_coin]
        trend = self.trend_calculator.get_trend(self.active_coin)
        if not trend or not trend.current_price:
            return None

        current_price = Decimal(str(trend.current_price))
        warning_price = buffer["warning"]
        liquidation_price = buffer["liquidation"]

        if current_price <= warning_price:
            self.logger().critical(
                f"🚨 {self.active_coin} at {current_price:.4f} "
                f"breached liquidation buffer ({warning_price:.4f}); "
                f"liquidation≈{liquidation_price:.4f}. Initiating emergency stop."
            )
            self.liquidation_prices.pop(self.active_coin, None)
            return self._create_stop_action()

        return None

    def determine_executor_actions(self) -> List[ExecutorAction]:
        # PRIORITEIT 1: RiskGuard check (meest kritisch)
        if self.active_coin:
            risk_stop = self.risk_guard.evaluate(self.active_coin)
            if risk_stop:
                # Cleanup liquidation tracking
                self.liquidation_prices.pop(self.active_coin, None)
                self.risk_guard.notify_grid_stopped(self.active_coin)
                return [risk_stop]

        # PRIORITEIT 2: Liquidation risk monitoring
        liquidation_action = self._monitor_liquidation_risk()
        if liquidation_action:
            if self.active_coin:
                self.risk_guard.notify_grid_stopped(self.active_coin)
            return [liquidation_action]

        # PRIORITEIT 3: Normale grid logic
        return super().determine_executor_actions()

    def should_exit_position(self, coin: str) -> Optional[str]:
        """
        Tighten emergency and hard-stop thresholds for leveraged futures positions.
        """
        original_emergency = getattr(self.config, "emergency_exit_pct", -2.0)
        original_hard = getattr(self.config, "hard_stop_pct", -3.0)
        futures_emergency = getattr(self.config, "futures_emergency_exit_pct", -1.5)
        futures_hard = getattr(self.config, "futures_hard_stop_pct", -2.5)

        setattr(self.config, "emergency_exit_pct", futures_emergency)
        setattr(self.config, "hard_stop_pct", futures_hard)
        try:
            return super().should_exit_position(coin)
        finally:
            setattr(self.config, "emergency_exit_pct", original_emergency)
            setattr(self.config, "hard_stop_pct", original_hard)

    def _check_multi_timeframe_buy_conditions(self, coin: str) -> bool:
        """
        Tightened futures entry gating aligned with liquidation-aware risk rules.

        Requirements:
        - Trend data must be fresh and produce a normalized strength above the configured minimum.
        - Warm-up mode (still loading 24h signal) demands 4h > +1.0% and 1h ≥ +0.5%.
        - Normal trading requires 24h > +1.5%, 4h > +1.0%, 1h ≥ 0.0%.
        """
        try:
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return False

            staleness_threshold = getattr(self.config, "price_update_interval", 30) * 4
            data_age = self.market_data_provider.time() - trend.last_updated
            if data_age > staleness_threshold:
                self.logger().debug(
                    f"⚠️  Futures entry rejected for {coin}: trend data stale "
                    f"({data_age:.1f}s > {staleness_threshold}s)"
                )
                return False

            strength = self._compute_trend_strength(trend)
            if strength < self.config.trend_min_entry_strength:
                self.logger().debug(
                    f"⚠️  Futures entry rejected for {coin}: strength "
                    f"{strength:+.2f} < {self.config.trend_min_entry_strength:+.2f}"
                )
                return False

            if not hasattr(trend, "trend_60m") or not hasattr(trend, "trend_240m"):
                self.logger().warning(
                    f"⚠️  Futures entry rejected for {coin}: multi-timeframe fields missing"
                )
                return False

            # Gebruik config parameters (geen hardcoded values meer)
            min_24h = float(self.config.futures_min_entry_strength_24h)
            min_4h = float(self.config.futures_min_entry_strength_4h)
            min_1h = float(self.config.futures_min_entry_strength_1h)

            if getattr(trend, "long_trend_warmup", False):
                # Warmup thresholds uit config
                warmup_240m_threshold = float(self.config.warmup_min_4h_trend_pct)
                warmup_60m_threshold = float(self.config.warmup_min_1h_trend_pct)
                warmup_240m_ok = trend.trend_240m > warmup_240m_threshold
                warmup_60m_ok = trend.trend_60m >= warmup_60m_threshold
                if warmup_240m_ok and warmup_60m_ok:
                    self.logger().info(
                        f"[FUTURES] ✅ {coin} warm-up entry allowed: "
                        f"4h={trend.trend_240m:+.2f}% (>{warmup_240m_threshold:+.2f}), "
                        f"1h={trend.trend_60m:+.2f}% (≥{warmup_60m_threshold:+.2f})"
                    )
                    return True

                reasons = []
                if not warmup_240m_ok:
                    reasons.append(
                        f"4h {trend.trend_240m:+.2f}% ≤ {warmup_240m_threshold:+.2f}% (warm-up min)"
                    )
                if not warmup_60m_ok:
                    reasons.append(
                        f"1h {trend.trend_60m:+.2f}% < {warmup_60m_threshold:+.2f}% (warm-up min)"
                    )
                self.logger().info(
                    f"[FUTURES] ❌ {coin} warm-up entry blocked: {'; '.join(reasons)}"
                )
                return False

            trend_1440m_ok = getattr(trend, "trend_1440m", 0.0) > min_24h
            trend_240m_ok = trend.trend_240m > min_4h
            trend_60m_ok = trend.trend_60m >= min_1h

            if trend_1440m_ok and trend_240m_ok and trend_60m_ok:
                self.logger().info(
                    f"[FUTURES] ✅ {coin} entry confirmed: "
                    f"24h={getattr(trend, 'trend_1440m', 0.0):+.2f}%, "
                    f"4h={trend.trend_240m:+.2f}%, "
                    f"1h={trend.trend_60m:+.2f}%"
                )
                return True

            reasons = []
            if not trend_1440m_ok:
                reasons.append(f"24h {getattr(trend, 'trend_1440m', 0.0):+.2f}% ≤ +1.5%")
            if not trend_240m_ok:
                reasons.append(f"4h {trend.trend_240m:+.2f}% ≤ +1.0%")
            if not trend_60m_ok:
                reasons.append(f"1h {trend.trend_60m:+.2f}% < 0.0%")
            self.logger().info(
                f"[FUTURES] ❌ {coin} entry blocked: {'; '.join(reasons)}"
            )
            return False

        except Exception as e:
            self.logger().error(f"❌ Error checking multi-timeframe buy conditions for {coin}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # Fail closed on unexpected errors
            return False


def _convert_position_mode(mode: FuturesPositionMode) -> PositionMode:
    if isinstance(mode, FuturesPositionMode):
        return PositionMode[mode.name]
    if isinstance(mode, PositionMode):
        return mode
    return PositionMode[str(mode).upper()]
