"""A/B shadow-validation runner: 70/30 trend+ATR ranking (variant A) vs
GridSuitability ranking (variant B), on the same public market data, with
fully independent virtual portfolios.

Run as a SEPARATE PROCESS, never imported by the live strategy:

    python -m multi_coin_grid_pro.shadow.ab_shadow_runner \\
        --pairs BTC-USD,ETH-USD,SOL-USD,... \\
        --capital-quote 300 --max-slots 3 --poll-seconds 30

Stop with Ctrl+C (SIGINT) or `kill <pid>` (SIGTERM) — both trigger a clean
shutdown that flushes open-position state to the results DB and closes the
public market-data client. There is no live state to reconcile: this process
never touches the live bot's files, connectors, or controller.

If this process crashes, raises, or is killed, the live bot is entirely
unaffected — they do not share a process, a connector, a nonce, or a
database file.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time
from decimal import Decimal
from typing import Dict, List, Optional

from multi_coin_grid_pro.shadow.public_market_data import PublicKrakenMarketAdapter
from multi_coin_grid_pro.shadow.results_store import ShadowResultsStore
from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualGridPosition, VirtualPositionStatus
from multi_coin_grid_pro.shadow.virtual_portfolio import VirtualPortfolio
from multi_coin_grid_pro.utils.grid_suitability_scorer import GridSuitabilityScorer
from multi_coin_grid_pro.utils.trend_calculator import TrendCalculator

logger = logging.getLogger("shadow_ab_runner")

# Mirrored (duplicated, read-only) from multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml.
# These constants are NOT read from the live config object or any live instance —
# changing the live config has no effect on this file, and vice versa. Kept in
# sync manually and intentionally, exactly as instructed ("dezelfde fees,
# kapitaalrestricties en risicoregels hanteren").
LIVE_MIRRORED_DEFAULTS = {
    "trend_min_change_pct": 0.007,
    "stop_loss_pct": Decimal("0.015"),
    "maker_fee_pct": Decimal("0.0020"),
    "taker_fee_pct": Decimal("0.0035"),
    "required_take_profit_net_pct": Decimal("0.02"),
    "max_hold_seconds": 6 * 3600,
    "entry_edge_pct": Decimal("0.0008"),
    "grid_suitability_config": {
        "enabled": True,
        "logging_only": False,
        "min_grid_score": 0.50,
        "range_efficiency_max": 0.70,
        "lookback_candles": 48,
    },
    # VALIDATION FIX: without this, variant A silently falls back to a plain
    # descending-trend sort inside get_top_n_coins() — NOT the live 70% trend
    # + 30% ATR blend — because `atr_use_ranking` defaults to False when
    # atr_selection_config is omitted (see trend_calculator.py line ~1577).
    # Values below are the exact output of the live controller's
    # _build_atr_selection_config(), reconstructed from
    # atr_fee_gate.min_atr_fee_multiplier=2.0, atr_coin_selection.prefilter_ratio=0.50,
    # fee_aware_filter.fee_model=best_case, maker_fee_pct=0.20 — confirmed to
    # match production logs exactly: "required_atr_pct=0.800% soft_threshold_pct=0.400%".
    "atr_selection_config": {
        "enabled": True,
        "required_atr_pct": 0.80,
        "prefilter_ratio": 0.50,
        "use_as_ranking_signal": True,
    },
    # KNOWN, DELIBERATE LIMITATION: live orderbook_liquidity depth-filtering
    # (orderbook_liquidity.enabled=true in production config) is NOT
    # reproduced. PublicKrakenMarketAdapter does not implement the L2
    # order-book snapshot interface get_top_n_coins()'s depth pre-filter
    # requires, and forcing it on would silently fail every tick rather than
    # filter correctly. Candidates are therefore NOT liquidity/depth-filtered
    # in this shadow sandbox — see the Fase-2 validation report for the
    # planned remediation (would require either public L2 snapshots or an
    # explicit decision to skip this signal permanently).
    "orderbook_config": None,
}


class ABShadowRunner:
    def __init__(
        self,
        pairs: List[str],
        capital_quote: Decimal,
        max_slots: int,
        poll_seconds: float,
        results_db_path: str,
        candidate_multiplier: int = 3,
    ):
        self.pairs = pairs
        self.poll_seconds = poll_seconds
        self.candidate_multiplier = candidate_multiplier

        self.market = PublicKrakenMarketAdapter()
        self.trend_calculator = TrendCalculator(connector=self.market)
        # Two separate GridSuitabilityScorer instances — one feeds variant B's
        # actual ranking decision, the other is used purely for post-hoc
        # observability logging of variant A's picks. Kept separate (even
        # though score_coin() is a pure function of `candles` and would be
        # harmless to share) to remove any ambiguity about shared mutable
        # state (`last_scores` cache) between the two variants' code paths.
        self.grid_scorer_for_ranking = GridSuitabilityScorer(
            config=LIVE_MIRRORED_DEFAULTS["grid_suitability_config"], logger=logger,
        )
        self.grid_scorer_for_logging = GridSuitabilityScorer(
            config=LIVE_MIRRORED_DEFAULTS["grid_suitability_config"], logger=logger,
        )

        self.portfolio_a = VirtualPortfolio(variant_label="A_trend_atr", capital_quote=capital_quote, max_slots=max_slots)
        self.portfolio_b = VirtualPortfolio(variant_label="B_grid_suitability", capital_quote=capital_quote, max_slots=max_slots)

        self.store = ShadowResultsStore(results_db_path)
        # symbol -> DB row id, per variant, only while a position is open — used to
        # correlate the close-update with the row the open-insert created.
        self._open_row_ids: Dict[str, Dict[str, int]] = {"A_trend_atr": {}, "B_grid_suitability": {}}

        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def handle_restart_orphans(self) -> None:
        """Safety, not silence: any row still `status='OPEN'` in the results
        DB at process start belonged to a PREVIOUS run whose in-memory
        portfolio state is gone (virtual positions are never persisted with
        enough fields — thresholds, limit price — to safely reconstruct a
        ticking VirtualGridPosition). Rather than silently treating them as
        still-open (wrong: nothing is tracking them anymore) or silently
        dropping them (wrong: looks like they never existed), mark them with
        an explicit terminal status so they are visible in any KPI query but
        excluded from the CLOSED-only PnL aggregates."""
        orphaned = self.store.mark_all_open_as_orphaned()
        if orphaned:
            logger.warning(
                f"⚠️  {orphaned} position(s) left OPEN by a previous shadow-runner process "
                f"marked ORPHANED_ON_RESTART (not resumed, not counted as closed PnL)."
            )

    async def _bootstrap(self) -> None:
        logger.info(f"📥 Loading historical candles for {len(self.pairs)} pairs (public data only)...")
        await self.trend_calculator.load_historical_data(self.pairs)

    async def _refresh(self) -> None:
        await self.trend_calculator.update_all_trends_v2(self.pairs, retry_on_failure=False)

    def _select_variant_a(self) -> List[str]:
        return self.trend_calculator.get_top_n_coins(
            n=self.portfolio_a.max_slots,
            min_trend_pct=LIVE_MIRRORED_DEFAULTS["trend_min_change_pct"],
            exclude_coins=list(self.portfolio_a.open_positions.keys()),
            # Reproduces the live 70% trend + 30% ATR blend (see
            # LIVE_MIRRORED_DEFAULTS comment) — grid_scorer=None here is the
            # live wiring-gap, reproduced deliberately for variant A.
            atr_selection_config=LIVE_MIRRORED_DEFAULTS["atr_selection_config"],
            orderbook_config=LIVE_MIRRORED_DEFAULTS["orderbook_config"],
            grid_scorer=None,
        )

    def _select_variant_b(self) -> List[str]:
        return self.trend_calculator.get_top_n_coins(
            n=self.portfolio_b.max_slots * self.candidate_multiplier,
            min_trend_pct=LIVE_MIRRORED_DEFAULTS["trend_min_change_pct"],
            exclude_coins=list(self.portfolio_b.open_positions.keys()),
            atr_selection_config=LIVE_MIRRORED_DEFAULTS["atr_selection_config"],
            orderbook_config=LIVE_MIRRORED_DEFAULTS["orderbook_config"],
            grid_scorer=self.grid_scorer_for_ranking,  # the fix under test
        )[: self.portfolio_b.max_slots]

    def _maybe_open(self, variant: str, portfolio: VirtualPortfolio, candidates: List[str], now: float) -> None:
        for rank, symbol in enumerate(candidates, start=1):
            trend = self.trend_calculator.get_trend(symbol)
            grid_score = None
            if trend and getattr(trend, "candles", None):
                gs = self.grid_scorer_for_logging.score_coin(symbol, trend.candles)
                grid_score = gs.score if gs else None
            self.store.record_selection(
                ts=now, variant=variant, symbol=symbol, rank=rank,
                trend_pct=float(trend.consensus_trend_pct) if trend else None,
                grid_score=grid_score,
            )

        if not portfolio.can_open("", Decimal("0")):
            pass  # no-op guard kept simple; real check happens per-symbol below
        for symbol in candidates:
            if symbol in portfolio.open_positions:
                continue
            notional = portfolio.capital_quote / portfolio.max_slots
            if not portfolio.can_open(symbol, notional):
                continue
            current_price = self.trend_calculator.get_trend(symbol)
            if not current_price or not current_price.current_price:
                continue
            mid = current_price.current_price
            limit_price = mid * (Decimal("1") - LIVE_MIRRORED_DEFAULTS["entry_edge_pct"])
            position = VirtualGridPosition(
                symbol=symbol,
                notional_quote=notional,
                stop_loss_pct=LIVE_MIRRORED_DEFAULTS["stop_loss_pct"],
                required_take_profit_net_pct=LIVE_MIRRORED_DEFAULTS["required_take_profit_net_pct"],
                maker_fee_pct=LIVE_MIRRORED_DEFAULTS["maker_fee_pct"],
                taker_fee_pct=LIVE_MIRRORED_DEFAULTS["taker_fee_pct"],
                max_hold_seconds=LIVE_MIRRORED_DEFAULTS["max_hold_seconds"],
                limit_price=limit_price,
                created_at=now,
            )
            portfolio.open_position(position)
            row_id = self.store.record_position_open(variant, position)
            self._open_row_ids[variant][symbol] = row_id
            logger.info(f"🟢 [{variant}] opened virtual position {symbol} @ limit {limit_price}")
            break  # one new entry per tick per variant, mirrors live's single-entry-per-cycle behaviour

    def _tick_positions(self, variant: str, portfolio: VirtualPortfolio, now: float) -> None:
        for symbol in list(portfolio.open_positions.keys()):
            position = portfolio.open_positions[symbol]
            trend = self.trend_calculator.get_trend(symbol)
            if not trend or not trend.current_price:
                continue
            current_price = trend.current_price

            if position.status == VirtualPositionStatus.PENDING_ENTRY:
                position.try_fill_entry(current_price, now)
                continue

            exit_reason = position.tick(current_price, now)
            if exit_reason:
                position.close(current_price, now, exit_reason)
                portfolio.close_position(symbol)
                row_id = self._open_row_ids[variant].pop(symbol, None)
                if row_id is not None:
                    self.store.record_position_close(row_id, position)
                logger.info(
                    f"🔴 [{variant}] closed {symbol} reason={exit_reason.value} "
                    f"net_pnl={position.net_pnl_quote}"
                )

    async def run(self, max_iterations: Optional[int] = None) -> None:
        self.handle_restart_orphans()
        await self._bootstrap()
        iteration = 0
        try:
            while not self._stop_requested:
                now = time.time()
                try:
                    await self._refresh()
                    candidates_a = self._select_variant_a()
                    candidates_b = self._select_variant_b()
                    self._maybe_open("A_trend_atr", self.portfolio_a, candidates_a, now)
                    self._maybe_open("B_grid_suitability", self.portfolio_b, candidates_b, now)
                    self._tick_positions("A_trend_atr", self.portfolio_a, now)
                    self._tick_positions("B_grid_suitability", self.portfolio_b, now)
                except Exception as e:
                    # Fail-safe: a shadow-loop error never propagates beyond this
                    # process. Log and continue to the next poll, never raise
                    # into anything the live bot could observe (there is none —
                    # separate process — but keep the loop itself resilient too).
                    logger.error(f"⚠️  shadow loop iteration failed, continuing: {e}", exc_info=True)

                iteration += 1
                if max_iterations is not None and iteration >= max_iterations:
                    break
                await asyncio.sleep(self.poll_seconds)
        finally:
            await self.market.close()
            self.store.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A/B shadow coin-selection validator (read-only, public data only)")
    parser.add_argument("--pairs", type=str, required=True, help="Comma-separated trading pairs, e.g. BTC-USD,ETH-USD")
    parser.add_argument("--capital-quote", type=str, default="300")
    parser.add_argument("--max-slots", type=int, default=3)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--results-db", type=str, default="data/shadow_ab_results.db")
    parser.add_argument("--max-iterations", type=int, default=None, help="For testing; omit for continuous run")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - shadow - %(levelname)s - %(message)s")
    args = _build_arg_parser().parse_args()
    runner = ABShadowRunner(
        pairs=[p.strip() for p in args.pairs.split(",") if p.strip()],
        capital_quote=Decimal(args.capital_quote),
        max_slots=args.max_slots,
        poll_seconds=args.poll_seconds,
        results_db_path=args.results_db,
    )

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.request_stop)
        except NotImplementedError:
            pass  # Windows: Ctrl+C still raises KeyboardInterrupt, handled by run()

    try:
        loop.run_until_complete(runner.run(max_iterations=args.max_iterations))
    except KeyboardInterrupt:
        runner.request_stop()


if __name__ == "__main__":
    main()
