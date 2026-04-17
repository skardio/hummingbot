"""
Regime-First Coin Selection

Selects coins based on detected market regime:
- BULL: Momentum-following — rank by trend consensus (strongest uptrend first)
- CHOP: Mean-reversion — rank by grid suitability score (best sideways mover)
- BEAR: Sit out — return empty list (capital preservation)

Usage:
    selector = RegimeCoinSelector(config, logger)
    coins = selector.select(
        regime="CHOP",
        trend_calculator=tc,
        grid_scorer=gs,
        n=2,
        min_trend_pct=0.007,
        exclude_coins=["FET-USD"],
        orderbook_config={...},
    )
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class RegimeCoinSelector:
    """Regime-first coin selection: market type determines ranking strategy."""

    def __init__(self, config: dict, log: Optional[logging.Logger] = None):
        """
        Args:
            config: Dict with keys:
                - bear_allow_trading: bool (default False)
                - bear_max_grids: int (default 0)
                - chop_use_grid_ranking: bool (default True)
                - bull_use_grid_ranking: bool (default False)
            log: Logger instance
        """
        self.config = config or {}
        self.log = log or logger

        self.bear_allow_trading = self.config.get('bear_allow_trading', False)
        self.bear_max_grids = self.config.get('bear_max_grids', 0)
        self.chop_use_grid_ranking = self.config.get(
            'chop_use_grid_ranking', True
        )
        self.bull_use_grid_ranking = self.config.get(
            'bull_use_grid_ranking', False
        )
        # CHOP trend bounds: lower floor + cap to exclude trending coins
        self.chop_min_trend_pct = self.config.get(
            'chop_min_trend_pct', 0.001  # Near-zero: accept flat coins
        )
        self.chop_max_trend_pct = self.config.get(
            'chop_max_trend_pct', 3.0  # >3% = too trendy for grid
        )

    def select(
        self,
        regime: str,
        trend_calculator,
        grid_scorer,
        n: int,
        min_trend_pct: float,
        exclude_coins: Optional[List[str]] = None,
        orderbook_config: Optional[dict] = None,
        trade_direction: str = "long",
    ) -> List[str]:
        """
        Select top N coins based on current regime.

        Args:
            regime: "BULL", "CHOP", or "BEAR"
            trend_calculator: TrendCalculator with get_top_n_coins()
            grid_scorer: GridSuitabilityScorer instance (may be None)
            n: Number of coins to return
            min_trend_pct: Minimum trend % for qualification
            exclude_coins: Coins to skip
            orderbook_config: Depth filtering config
            trade_direction: "long", "short", or "auto"

        Returns:
            List of symbol strings (may be empty)
        """
        regime = (regime or "CHOP").upper()

        if regime == "BEAR":
            return self._select_bear(
                trend_calculator, grid_scorer, n, min_trend_pct,
                exclude_coins, orderbook_config, trade_direction,
            )
        elif regime == "CHOP":
            return self._select_chop(
                trend_calculator, grid_scorer, n, min_trend_pct,
                exclude_coins, orderbook_config, trade_direction,
            )
        else:  # BULL or unknown → default to bull
            return self._select_bull(
                trend_calculator, grid_scorer, n, min_trend_pct,
                exclude_coins, orderbook_config, trade_direction,
            )

    def _select_bear(
        self, trend_calculator, grid_scorer, n, min_trend_pct,
        exclude_coins, orderbook_config, trade_direction,
    ) -> List[str]:
        """BEAR: Sit out entirely unless bear_allow_trading is True."""
        if not self.bear_allow_trading:
            self.log.info(
                "🐻 REGIME_SELECT: BEAR regime → no new entries "
                "(capital preservation)"
            )
            return []

        # If allowed, use grid ranking with reduced slots
        max_n = min(n, self.bear_max_grids) if self.bear_max_grids > 0 else 0
        if max_n <= 0:
            self.log.info(
                "🐻 REGIME_SELECT: BEAR regime → bear_max_grids=0, "
                "no entries"
            )
            return []

        self.log.info(
            f"🐻 REGIME_SELECT: BEAR regime → cautious mode, "
            f"max {max_n} grid(s), grid-ranked"
        )
        return trend_calculator.get_top_n_coins(
            n=max_n,
            min_trend_pct=min_trend_pct,
            exclude_coins=exclude_coins,
            orderbook_config=orderbook_config,
            trade_direction=trade_direction,
            grid_scorer=grid_scorer,
        )

    def _select_chop(
        self, trend_calculator, grid_scorer, n, min_trend_pct,
        exclude_coins, orderbook_config, trade_direction,
    ) -> List[str]:
        """CHOP/SIDEWAYS: Rank by grid suitability (mean-reversion fitness).

        Key difference from BULL:
        - Uses chop_min_trend_pct (default 0.001) instead of the normal
          min_trend_pct — this lets flat/sideways coins through.
        - Post-filters with chop_max_trend_pct to exclude coins that
          are trending too strongly (bad for grid/mean-reversion).
        """
        use_grid = (
            self.chop_use_grid_ranking
            and grid_scorer is not None
            and getattr(grid_scorer, 'enabled', False)
        )

        # CHOP uses a LOWER trend floor — sideways coins are what we want
        chop_floor = self.chop_min_trend_pct
        chop_cap = self.chop_max_trend_pct

        if use_grid:
            self.log.info(
                f"📐 REGIME_SELECT: CHOP regime → grid-suitability ranking "
                f"(min_trend={chop_floor}%, max_trend={chop_cap}%, "
                f"best mean-reverter wins)"
            )
            candidates = trend_calculator.get_top_n_coins(
                n=n * 3,  # Over-fetch to allow post-filter
                min_trend_pct=chop_floor,
                exclude_coins=exclude_coins,
                orderbook_config=orderbook_config,
                trade_direction=trade_direction,
                grid_scorer=grid_scorer,
            )
        else:
            self.log.info(
                f"📐 REGIME_SELECT: CHOP regime → trend ranking "
                f"(grid scorer unavailable, "
                f"min_trend={chop_floor}%, max_trend={chop_cap}%)"
            )
            candidates = trend_calculator.get_top_n_coins(
                n=n * 3,
                min_trend_pct=chop_floor,
                exclude_coins=exclude_coins,
                orderbook_config=orderbook_config,
                trade_direction=trade_direction,
            )

        # Post-filter: remove coins trending too strongly for grid
        if chop_cap > 0 and candidates:
            filtered = []
            for sym in candidates:
                trend = trend_calculator.get_trend(sym)
                if trend:
                    abs_trend = abs(trend.consensus_trend_pct)
                    if abs_trend <= chop_cap:
                        filtered.append(sym)
                    else:
                        self.log.info(
                            f"📐 CHOP_FILTER: {sym} excluded — "
                            f"|trend|={abs_trend:.2f}% > "
                            f"max {chop_cap}% (too trendy for grid)"
                        )
                else:
                    filtered.append(sym)  # No trend data → allow
            candidates = filtered

        return candidates[:n]

    def _select_bull(
        self, trend_calculator, grid_scorer, n, min_trend_pct,
        exclude_coins, orderbook_config, trade_direction,
    ) -> List[str]:
        """BULL: Rank by trend consensus (strongest momentum wins)."""
        # In bull mode, optionally also use grid ranking
        scorer = None
        if (self.bull_use_grid_ranking
                and grid_scorer is not None
                and getattr(grid_scorer, 'enabled', False)):
            scorer = grid_scorer
            self.log.info(
                "📈 REGIME_SELECT: BULL regime → grid-suitability ranking "
                "(configured for bull)"
            )
        else:
            self.log.info(
                "📈 REGIME_SELECT: BULL regime → trend-consensus ranking "
                "(strongest momentum wins)"
            )

        return trend_calculator.get_top_n_coins(
            n=n,
            min_trend_pct=min_trend_pct,
            exclude_coins=exclude_coins,
            orderbook_config=orderbook_config,
            trade_direction=trade_direction,
            grid_scorer=scorer,
        )

    def get_selection_mode(self, regime: str) -> str:
        """Return human-readable selection mode for logging."""
        regime = (regime or "CHOP").upper()
        if regime == "BEAR":
            if self.bear_allow_trading:
                return "BEAR:cautious_grid"
            return "BEAR:sit_out"
        elif regime == "CHOP":
            if self.chop_use_grid_ranking:
                return f"CHOP:grid_suitability(max{self.chop_max_trend_pct}%)"
            return "CHOP:trend_fallback"
        else:
            if self.bull_use_grid_ranking:
                return "BULL:grid_suitability"
            return "BULL:trend_momentum"
