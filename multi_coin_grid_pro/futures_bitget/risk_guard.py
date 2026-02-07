"""
RiskGuard: Centralized kill-switch logic voor futures grids.

Principe:
- Één verantwoordelijkheid: "Mag deze grid nog leven?"
- Stateless voor marktdata, stateful per coin
- Retourneert óf None óf een StopExecutorAction

Guards:
1. Hard loss: maximaal verlies overschreden
2. Max time: grid draait te lang zonder winst
3. Grid depth: te veel buy orders gevuld (zitten vast in dalende markt)
4. Sell starvation: geen sells = geen profit = stuck
5. Trend break: 1h trend breekt negatief = markt keert om
6. ATR explosion: volatiliteit explodeert = te gevaarlijk
"""

from decimal import Decimal
from typing import Dict, Optional

from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction


class RiskGuard:
    """Base interface voor risk guards."""

    def evaluate(self, coin: str) -> Optional[StopExecutorAction]:
        """Evalueer of coin gestopt moet worden. Retourneer StopExecutorAction of None."""
        raise NotImplementedError


class FuturesGridRiskGuard(RiskGuard):
    """
    Centralized kill-switch logic for futures grids.

    Houdt per coin bij:
    - Wanneer grid gestart is
    - Wanneer laatste sell was
    - ATR baseline voor volatiliteit check
    """

    def __init__(self, controller):
        """
        Args:
            controller: FuturesGridBitgetController instance met toegang tot:
                - market_data_provider.time()
                - position_manager.get_unrealized_pnl(coin)
                - grid_state.get(coin)
                - trend_calculator.get_trend(coin)
                - volatility_calculator.get_atr(coin)
                - config (met alle risk_guard_* parameters)
                - logger()
        """
        self.c = controller
        self.grid_start_ts: Dict[str, float] = {}
        self.last_sell_ts: Dict[str, float] = {}
        self.atr_baseline: Dict[str, Decimal] = {}

    def notify_grid_started(self, coin: str):
        """
        Notificatie: nieuwe grid is gestart voor coin.
        Reset alle tracking timestamps.
        """
        now = self.c.market_data_provider.time()
        self.grid_start_ts[coin] = now
        self.last_sell_ts[coin] = now

        # Sla huidige ATR op als baseline voor volatiliteit check
        atr = self.c.volatility_calculator.get_atr(coin) if hasattr(self.c, 'volatility_calculator') else None
        if atr:
            self.atr_baseline[coin] = atr

    def notify_sell_filled(self, coin: str):
        """
        Notificatie: sell order is gevuld voor coin.
        Update timestamp om sell starvation te voorkomen.
        """
        self.last_sell_ts[coin] = self.c.market_data_provider.time()

    def notify_grid_stopped(self, coin: str):
        """
        Notificatie: grid is gestopt voor coin.
        Cleanup alle tracking data.
        """
        self.grid_start_ts.pop(coin, None)
        self.last_sell_ts.pop(coin, None)
        self.atr_baseline.pop(coin, None)

    # ============================================================
    # GUARD CHECKS - Elke check retourneert bool: True = stop grid
    # ============================================================

    def _hard_loss(self, coin: str) -> bool:
        """
        Check 1: Hard loss - maximaal verlies overschreden.
        Gebruikt: risk_guard_max_loss_pct (default -8.0%)

        TEMPORARY DISABLED: position_manager.get_unrealized_pnl() not available
        TODO: Implement after verifying position_manager API
        """
        return False  # DISABLED - uncomment after implementing PnL tracking

    def _max_time(self, coin: str) -> bool:
        """
        Check 2: Max time - grid draait te lang.
        Gebruikt: risk_guard_max_grid_time_seconds (default 3600s = 1h)
        """
        start = self.grid_start_ts.get(coin)
        if not start:
            return False

        max_time = self.c.config.risk_guard_max_grid_time_seconds
        elapsed = self.c.market_data_provider.time() - start

        if elapsed > max_time:
            self.c.logger().warning(
                f"⏰ {coin} max time: {elapsed:.0f}s > {max_time}s"
            )
            return True
        return False

    def _grid_depth(self, coin: str) -> bool:
        """
        Check 3: Grid depth - te veel buy orders gevuld.
        Gebruikt: risk_guard_max_grid_depth_pct (default 0.65 = 65%)

        TEMPORARY DISABLED: grid_state not available
        TODO: Implement after verifying grid tracking API
        """
        return False  # DISABLED - uncomment after implementing grid depth tracking

    def _sell_starvation(self, coin: str) -> bool:
        """
        Check 4: Trade starvation - geen profit-taking trades.
        Gebruikt: risk_guard_sell_starvation_seconds (default 900s = 15min)

        Set to 0 to DISABLE this check (recommended for grid trading where
        sells are tracked internally by the grid executor).

        LONG: geen sells = geen profit (we verkopen om winst te nemen)
        SHORT: geen buys = geen profit (we kopen terug om winst te nemen)

        Voor nu: disabled voor SHORT mode omdat we geen buy tracking hebben.
        """
        # Disable voor SHORT mode - zou buy starvation moeten zijn
        trade_direction = getattr(self.c.config, 'trade_direction', 'long').lower()
        if trade_direction == 'short':
            return False  # TODO: implement buy starvation tracking for shorts

        max_starvation = self.c.config.risk_guard_sell_starvation_seconds

        # 0 = disabled
        if max_starvation <= 0:
            return False

        last = self.last_sell_ts.get(coin)
        if not last:
            return False

        time_since_sell = self.c.market_data_provider.time() - last

        if time_since_sell > max_starvation:
            self.c.logger().warning(
                f"🚫 {coin} sell starvation: {time_since_sell:.0f}s > {max_starvation}s sinds laatste sell"
            )
            return True
        return False

    def _trend_break(self, coin: str) -> bool:
        """
        Check 5: Trend break - trend keert om tegen je positie.

        Voor LONG: 1h trend < -1.5% = markt daalt = slecht
        Voor SHORT: 1h trend > +1.5% = markt stijgt = slecht

        Gebruikt: risk_guard_trend_break_pct (default -1.5% for LONG)
        """
        if not hasattr(self.c, 'trend_calculator'):
            return False

        trend = self.c.trend_calculator.get_trend(coin)
        if not trend or not hasattr(trend, 'trend_60m'):
            return False

        threshold = abs(self.c.config.risk_guard_trend_break_pct)
        trade_direction = getattr(self.c.config, 'trade_direction', 'long').lower()

        if trade_direction == 'short':
            # SHORT: trend break als markt STIJGT (positieve trend)
            if trend.trend_60m > threshold:
                self.c.logger().warning(
                    f"📈 {coin} trend break (SHORT): 1h {trend.trend_60m:+.2f}% > +{threshold:.2f}%"
                )
                return True
        else:
            # LONG: trend break als markt DAALT (negatieve trend)
            if trend.trend_60m < -threshold:
                self.c.logger().warning(
                    f"📉 {coin} trend break (LONG): 1h {trend.trend_60m:+.2f}% < -{threshold:.2f}%"
                )
                return True
        return False

    def _atr_explosion(self, coin: str) -> bool:
        """
        Check 6: ATR explosion - volatiliteit explodeert.
        Gebruikt: risk_guard_atr_explosion_multiplier (default 2.2x)

        TEMPORARY DISABLED: volatility_calculator not available
        TODO: Implement after verifying ATR calculation API
        """
        return False  # DISABLED - uncomment after implementing ATR tracking

    # ============================================================
    # PUBLIC API
    # ============================================================

    def evaluate(self, coin: str) -> Optional[StopExecutorAction]:
        """
        Evalueer alle risk guards voor coin.

        Returns:
            StopExecutorAction als één of meer guards triggeren
            None als alles OK is
        """
        # Skip als risk guard disabled
        if not self.c.config.risk_guard_enabled:
            return None

        reasons = []

        # Check alle guards
        if self._hard_loss(coin):
            reasons.append("hard_loss")
        if self._max_time(coin):
            reasons.append("max_time")
        if self._grid_depth(coin):
            reasons.append("grid_depth")
        if self._sell_starvation(coin):
            reasons.append("sell_starvation")
        if self._trend_break(coin):
            reasons.append("trend_break")
        if self._atr_explosion(coin):
            reasons.append("atr_explosion")

        # Als één of meer guards triggeren = stop grid
        if reasons:
            self.c.logger().critical(
                f"🛑 RiskGuard STOP voor {coin}: {', '.join(reasons)}"
            )
            return StopExecutorAction(
                executor_id=coin,  # Assuming executor_id is coin symbol
                reason=f"risk_guard: {', '.join(reasons)}"
            )

        return None
