# momentum_signal_service.py — asyncio main loop for the momentum signal service.
# READ-ONLY. Signal-only. No orders. No executor actions.
import argparse
import asyncio
import logging
import time
import uuid
from typing import List, Optional

import aiohttp

from multi_coin_grid_pro.reporters.momentum_signal_reporter import DISCLAIMER, SignalReporter
from multi_coin_grid_pro.signals.grid_position_reader import GridPositionReader
from multi_coin_grid_pro.signals.momentum_buy_now_scorer import BuyNowScorer
from multi_coin_grid_pro.signals.momentum_config import ServiceConfig
from multi_coin_grid_pro.signals.momentum_entry_levels import compute_entry_levels
from multi_coin_grid_pro.signals.momentum_filters import REASON_SCORE_TOO_LOW, HardFilter
from multi_coin_grid_pro.signals.momentum_market_data import MarketDataFetcher
from multi_coin_grid_pro.signals.momentum_models import (
    DataCoverageReport,
    ExchangeCoverageStats,
    MomentumSignal,
    PreselectionReport,
    ScanResult,
)
from multi_coin_grid_pro.signals.momentum_notifier import MomentumSignalNotifier
from multi_coin_grid_pro.signals.momentum_outcome_tracker import OutcomeTracker
from multi_coin_grid_pro.signals.momentum_preselection import apply_preselection
from multi_coin_grid_pro.signals.momentum_signal_store import JsonSnapshotWriter, SignalStore

logger = logging.getLogger(__name__)

_BANNER = (
    "=" * 72 + "\n"
    + f"  {DISCLAIMER}\n"
    + "  This service is READ-ONLY. No orders will be placed.\n"
    + "=" * 72
)
REASON_SCORE_TOO_HIGH_ANALYSIS_VARIANT = "SCORE_TOO_HIGH_ANALYSIS_VARIANT"


class MomentumSignalService:
    """Asyncio service: fetch → filter → score → store → report.

    The service runs until cancelled. It never places orders.
    ``config.mode`` must be ``"signal_only"`` — asserted at construction.
    """

    def __init__(
        self,
        config: ServiceConfig,
        db_path: str = "data/momentum_signals.sqlite",
        snapshot_path: str = "data/momentum_signals.json",
    ) -> None:
        assert config.mode == "signal_only", (
            f"mode must be 'signal_only', got '{config.mode}'"
        )
        self._config = config
        self._db_path = db_path
        self._snapshot_path = snapshot_path
        self._hard_filter = HardFilter()
        self._reporter = SignalReporter()
        self._notifier = MomentumSignalNotifier(config.notifications.telegram)
        if self._notifier.ready():
            logger.info("[NOTIFY] Telegram-notificaties ingeschakeld.")
        else:
            logger.info("[NOTIFY] Telegram-notificaties uitgeschakeld (geen token/chat_id of enabled=false).")
        self._session: Optional[aiohttp.ClientSession] = None
        self._store: Optional[SignalStore] = None
        self._writer: Optional[JsonSnapshotWriter] = None
        self._outcome_tracker: Optional[OutcomeTracker] = None
        self._config_version_id: Optional[int] = None

    def _build_config_params(self) -> dict:
        """Extract key filter+scoring params for config versioning."""
        cf = self._config.candidate_filters
        cl = self._config.classification
        sc = self._config.scoring
        return {
            "min_price_change_1m_pct": cf.min_price_change_1m_pct,
            "min_price_change_3m_pct": cf.min_price_change_3m_pct,
            "min_price_change_5m_pct": cf.min_price_change_5m_pct,
            "min_price_change_15m_pct": cf.min_price_change_15m_pct,
            "max_price_change_5m_pct": cf.max_price_change_5m_pct,
            "min_volume_ratio": cf.min_volume_ratio,
            "max_spread_pct": cf.max_spread_pct,
            "max_spread_pct_entry": cf.max_spread_pct_entry,
            "max_too_late_price_change_15m_pct": cf.max_too_late_price_change_15m_pct,
            "max_volume_ratio": cf.max_volume_ratio,
            "min_score": sc.min_score,
            "watch_min_score": cl.watch_min_score,
            "buy_now_min_score": cl.buy_now_min_score,
            "too_late_delta_15m_pct": cl.too_late_delta_15m_pct,
            "too_late_delta_15m_soft": cl.too_late_delta_15m_soft,
            "paper_test_enabled": cl.paper_test_enabled,
            "paper_watch_min_score_override": cl.paper_watch_min_score_override,
            "paper_block_buy_now_when_market_regime_ge_pct": cl.paper_block_buy_now_when_market_regime_ge_pct,
            "paper_prefer_exchange_enabled": cl.paper_prefer_exchange_enabled,
            "paper_preferred_exchange": cl.paper_preferred_exchange,
            "paper_preferred_exchange_rank_bonus": cl.paper_preferred_exchange_rank_bonus,
            "analysis_max_score_filter_enabled": cl.analysis_max_score_filter_enabled,
            "analysis_max_score": cl.analysis_max_score,
        }

    async def start(self) -> None:
        """Start the service. Runs until cancelled."""
        logger.info(_BANNER)
        self._session = aiohttp.ClientSession()
        self._store = SignalStore(db_path=self._db_path)
        self._writer = JsonSnapshotWriter(snapshot_path=self._snapshot_path)
        self._outcome_tracker = OutcomeTracker(db_path=self._db_path)
        params = self._build_config_params()
        self._config_version_id = self._store.get_or_create_config_version(params)
        logger.info("[CONFIG_VERSION] id=%d params=%s", self._config_version_id, params)
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("Service gestopt via CancelledError.")
        finally:
            await self._close()

    async def _run_loop(self) -> None:
        last_heartbeat = time.time()
        hb_buy_now = 0
        hb_watch = 0
        hb_scans = 0
        while True:
            loop_start = time.time()
            scan_id = uuid.uuid4().hex[:12]
            try:
                scan_result = await self._run_scan(scan_id, loop_start)
                # Only persist enriched signals: skip non-enriched universe pairs
                # (MISSING_PRICE_CHANGE_5M) — they carry no data and cause DB bloat.
                # ~1720 non-enriched pairs per scan × 1440 scans/day = ~2.5M dead rows/day.
                enriched_signals = [
                    s for s in scan_result.signals
                    if s.rejection_reason != "MISSING_PRICE_CHANGE_5M"
                ]
                self._store.save_batch(enriched_signals)
                self._writer.write(scan_result)
                self._reporter.log_scan(scan_result)
                self._notifier.notify_accepted(scan_result.signals)
                self._notifier.check_do_not_chase(scan_result.signals)
                # US-402: update outcome tracking for BUY_NOW signals
                if self._outcome_tracker is not None:
                    price_lookup = {
                        (s.exchange, s.trading_pair): s.price
                        for s in scan_result.signals
                    }
                    self._outcome_tracker.update(price_lookup)
                self._store.purge_old(retention_days=7)
                # Heartbeat counters
                hb_scans += 1
                for s in scan_result.signals:
                    if s.accepted and s.signal_label == "BUY_NOW":
                        hb_buy_now += 1
                    elif s.accepted and s.signal_label == "WATCH":
                        hb_watch += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Scan-fout (scan=%s): %s", scan_id, exc, exc_info=True
                )
            # Periodic heartbeat
            hb_interval = self._config.notifications.telegram.heartbeat_interval_seconds
            if hb_interval > 0 and time.time() - last_heartbeat >= hb_interval:
                self._notifier.send_heartbeat(hb_buy_now, hb_watch, hb_scans)
                logger.info(
                    "[HEARTBEAT] Verstuurd: %d BUY_NOW, %d WATCH, %d scans",
                    hb_buy_now, hb_watch, hb_scans,
                )
                last_heartbeat = time.time()
                hb_buy_now = 0
                hb_watch = 0
                hb_scans = 0
            elapsed = time.time() - loop_start
            sleep = max(0.0, self._config.scan_interval_seconds - elapsed)
            await asyncio.sleep(sleep)

    async def _run_scan(self, scan_id: str, start_ts: float) -> ScanResult:
        exchanges = [e.exchange for e in self._config.exchanges]
        logger.info("[SCAN %s] Start — exchanges: %s", scan_id, exchanges)
        _cv_id = self._config_version_id  # config version for all signals this scan

        # 1. Fetch candidates from all exchanges (ticker data + 24h fields)
        fetcher = MarketDataFetcher(session=self._session, max_concurrency=10)
        candidates = await fetcher.fetch_all(self._config.exchanges)
        logger.info("[SCAN %s] Tickers: %d candidates", scan_id, len(candidates))

        # 2. Annotate blacklist/grid flags — needed before preselection
        candidates = self._annotate(candidates)

        # 3. Pre-enrichment selection: filter + rank; pick top N per exchange
        preselection_report: Optional[PreselectionReport] = None
        ps_cfg = self._config.preselection
        max_per_exchange = self._config.market_data.max_enriched_pairs_per_exchange
        if ps_cfg.enabled:
            selected, preselection_report = apply_preselection(
                candidates, self._config, max_per_exchange
            )
            for exch_stats in preselection_report.by_exchange:
                logger.info(
                    "[PRESELECT] %s: %d universe → %d eligible → %d selected",
                    exch_stats.exchange,
                    exch_stats.universe_total,
                    exch_stats.eligible,
                    exch_stats.selected,
                )
        else:
            selected = candidates

        # 4. Enrich selected candidates with candles and orderbook data
        # 4a. Voeg één BTC- en één ETH-ref toe per exchange voor contextberekening.
        #     Ze worden NOOIT signalen: de filter gooit ze weg via EXCLUDED_MAJOR_ASSET.
        selected = selected + self._pick_btc_eth_refs(candidates, selected)

        selected = await fetcher.enrich_all(
            selected, self._config.market_data, self._config.exchanges, start_ts
        )
        enriched = sum(
            1 for c in selected if c.candles_fetched_at > 0 or c.ob_fetched_at > 0
        )
        logger.info(
            "[SCAN %s] Enriched: %d/%d selected (%d total universe)",
            scan_id, enriched, len(selected), len(candidates),
        )

        # 4b. Bereken marktcontext eenmalig per scan; alle signals in deze scan delen dezelfde waarden.
        _cv_market = self._compute_market_context(selected)

        # 5. Apply hard filter to ALL candidates (selected enriched + rest)
        #    Non-selected will be rejected for MISSING_* (no candle/OB data)
        # Rebuild full candidate list: selected (may be enriched) + remainder
        selected_set = set(id(c) for c in selected)
        remainder = [c for c in candidates if id(c) not in selected_set]
        all_for_filter = selected + remainder

        filter_result = self._hard_filter.apply(
            all_for_filter, self._config, now=start_ts
        )

        # 4. Score accepted candidates with BuyNowScorer (US-202)
        #    Old SignalScorer is kept for backward compat but no longer drives ranking.
        buy_now_scorer = BuyNowScorer()
        cls_cfg = self._config.classification
        min_score = cls_cfg.watch_min_score  # WATCH threshold = entry gate
        if cls_cfg.paper_test_enabled and cls_cfg.paper_watch_min_score_override > 0.0:
            min_score = cls_cfg.paper_watch_min_score_override
        ranked: List = []
        score_rejected: List = []
        score_too_high_rejected: List = []
        for candidate in filter_result.accepted:
            score = buy_now_scorer.score_candidate(candidate)
            if (
                cls_cfg.paper_test_enabled
                and cls_cfg.analysis_max_score_filter_enabled
                and score > cls_cfg.analysis_max_score
            ):
                score_too_high_rejected.append((candidate, score))
                continue
            if score >= min_score:
                breakdown_obj = buy_now_scorer.score_breakdown(candidate)
                breakdown = {
                    "short_momentum": breakdown_obj.short_momentum,
                    "acceleration": breakdown_obj.acceleration,
                    "volume_spike": breakdown_obj.volume_spike,
                    "liquidity": breakdown_obj.liquidity,
                    "risk": breakdown_obj.risk,
                }
                rank_score = score
                if (
                    cls_cfg.paper_test_enabled
                    and cls_cfg.paper_prefer_exchange_enabled
                    and candidate.exchange.lower() == cls_cfg.paper_preferred_exchange.lower()
                ):
                    rank_score += cls_cfg.paper_preferred_exchange_rank_bonus
                ranked.append((candidate, score, breakdown, rank_score))
            else:
                score_rejected.append((candidate, score))

        ranked.sort(key=lambda x: (-x[3], -x[1]))

        # 5. Build signal list (accepted signals get WATCH/BUY_NOW/TOO_LATE label)
        signals: List[MomentumSignal] = []
        for rank_idx, (c, score, breakdown, _rank_score) in enumerate(
            ranked[: self._config.top_n], start=1
        ):
            label = self._classify_label(c, score, market_regime=_cv_market["regime"])
            # US-204: compute entry levels for BUY_NOW signals
            levels = None
            if label == "BUY_NOW":
                levels = compute_entry_levels(c.bid, c.ask, self._config.entry)
                if levels is None:
                    label = "WATCH"  # no valid bid/ask → can't provide entry zone
            signals.append(
                MomentumSignal(
                    scan_id=scan_id,
                    timestamp=start_ts,
                    exchange=c.exchange,
                    trading_pair=c.trading_pair,
                    price=c.price,
                    spread_pct=c.spread_pct,
                    price_change_1m_pct=c.price_change_1m_pct,
                    price_change_3m_pct=c.price_change_3m_pct,
                    price_change_5m_pct=c.price_change_5m_pct,
                    price_change_15m_pct=c.price_change_15m_pct,
                    acceleration_score=c.acceleration_score,
                    volume_ratio=c.volume_ratio,
                    slippage_100eur=c.slippage_100eur,
                    slippage_250eur=c.slippage_250eur,
                    score=score,
                    accepted=True,
                    rank=rank_idx,
                    score_breakdown=breakdown or {},
                    signal_label=label,
                    entry_min=levels.entry_min if levels else None,
                    entry_max=levels.entry_max if levels else None,
                    max_chase_price=levels.max_chase_price if levels else None,
                    invalidation_price=levels.invalidation_price if levels else None,
                    take_profit_1=levels.take_profit_1 if levels else None,
                    take_profit_2=levels.take_profit_2 if levels else None,
                    preselection_score=c.preselection_score,
                    preselection_rank=c.preselection_rank,
                    preselection_bucket=c.preselection_bucket,
                    preselection_breakdown=c.preselection_breakdown,
                    config_version_id=_cv_id,
                    market_regime_at_signal=_cv_market["regime"],
                    market_breadth_15m=_cv_market["breadth"],
                    btc_15m_change_pct=_cv_market["btc_d15m"],
                    eth_15m_change_pct=_cv_market["eth_d15m"],
                )
            )

        for rejected in filter_result.rejected:
            c = rejected.candidate
            signals.append(
                MomentumSignal(
                    scan_id=scan_id,
                    timestamp=start_ts,
                    exchange=c.exchange,
                    trading_pair=c.trading_pair,
                    price=c.price,
                    spread_pct=c.spread_pct,
                    price_change_1m_pct=c.price_change_1m_pct,
                    price_change_3m_pct=c.price_change_3m_pct,
                    price_change_5m_pct=c.price_change_5m_pct,
                    price_change_15m_pct=c.price_change_15m_pct,
                    acceleration_score=c.acceleration_score,
                    volume_ratio=c.volume_ratio,
                    orderbook_depth_quote=c.orderbook_depth_quote,
                    slippage_100eur=c.slippage_100eur,
                    slippage_250eur=c.slippage_250eur,
                    score=0.0,
                    accepted=False,
                    rejection_reason=rejected.rejection_reason,
                    all_reasons=rejected.all_reasons,
                    preselection_score=c.preselection_score,
                    preselection_rank=c.preselection_rank,
                    preselection_bucket=c.preselection_bucket,
                    preselection_breakdown=c.preselection_breakdown,
                    config_version_id=_cv_id,
                    market_regime_at_signal=_cv_market["regime"],
                    market_breadth_15m=_cv_market["breadth"],
                    btc_15m_change_pct=_cv_market["btc_d15m"],
                    eth_15m_change_pct=_cv_market["eth_d15m"],
                )
            )

        # Score-rejected candidates (passed hard filter but score < min_score)
        for c, score in score_rejected:
            signals.append(
                MomentumSignal(
                    scan_id=scan_id,
                    timestamp=start_ts,
                    exchange=c.exchange,
                    trading_pair=c.trading_pair,
                    price=c.price,
                    spread_pct=c.spread_pct,
                    price_change_1m_pct=c.price_change_1m_pct,
                    price_change_3m_pct=c.price_change_3m_pct,
                    price_change_5m_pct=c.price_change_5m_pct,
                    price_change_15m_pct=c.price_change_15m_pct,
                    acceleration_score=c.acceleration_score,
                    volume_ratio=c.volume_ratio,
                    orderbook_depth_quote=c.orderbook_depth_quote,
                    slippage_100eur=c.slippage_100eur,
                    slippage_250eur=c.slippage_250eur,
                    score=score,
                    accepted=False,
                    rejection_reason=REASON_SCORE_TOO_LOW,
                    all_reasons=[REASON_SCORE_TOO_LOW],
                    config_version_id=_cv_id,
                    market_regime_at_signal=_cv_market["regime"],
                    market_breadth_15m=_cv_market["breadth"],
                    btc_15m_change_pct=_cv_market["btc_d15m"],
                    eth_15m_change_pct=_cv_market["eth_d15m"],
                )
            )

        # Analysis-variant rejected: score above optional max-score cap (paper only).
        for c, score in score_too_high_rejected:
            signals.append(
                MomentumSignal(
                    scan_id=scan_id,
                    timestamp=start_ts,
                    exchange=c.exchange,
                    trading_pair=c.trading_pair,
                    price=c.price,
                    spread_pct=c.spread_pct,
                    price_change_1m_pct=c.price_change_1m_pct,
                    price_change_3m_pct=c.price_change_3m_pct,
                    price_change_5m_pct=c.price_change_5m_pct,
                    price_change_15m_pct=c.price_change_15m_pct,
                    acceleration_score=c.acceleration_score,
                    volume_ratio=c.volume_ratio,
                    orderbook_depth_quote=c.orderbook_depth_quote,
                    slippage_100eur=c.slippage_100eur,
                    slippage_250eur=c.slippage_250eur,
                    score=score,
                    accepted=False,
                    rejection_reason=REASON_SCORE_TOO_HIGH_ANALYSIS_VARIANT,
                    all_reasons=[REASON_SCORE_TOO_HIGH_ANALYSIS_VARIANT],
                    config_version_id=_cv_id,
                    market_regime_at_signal=_cv_market["regime"],
                    market_breadth_15m=_cv_market["breadth"],
                    btc_15m_change_pct=_cv_market["btc_d15m"],
                    eth_15m_change_pct=_cv_market["eth_d15m"],
                )
            )

        # 6. Data coverage report (based on enriched/selected candidates)
        out = self._config.output
        coverage: Optional[DataCoverageReport] = None
        sample_mode = self._config.market_data.mode == "sample"
        if out.log_data_coverage:
            coverage = self._build_coverage(selected, signals, start_ts, sample_mode=sample_mode)
            if coverage.sample_mode:
                logger.info(
                    "[MOMENTUM_SAMPLE_MODE] %d/%d candidates enriched. "
                    "Coverage warning suppressed for non-enriched candidates.",
                    enriched, len(candidates),
                )
            elif coverage.blind_warning:
                logger.warning(
                    "[MOMENTUM_DATA_WARNING] More than 80%% of pairs are missing momentum data."
                    " Scanner may be blind. Check candle/volume fetchers."
                )

        # 7. Top rejected: enriched only (no n/a candidates) + missing data sample
        top_rejected: List[MomentumSignal] = []
        missing_data_sample: List[MomentumSignal] = []
        if out.log_top_rejected_candidates:
            rej_signals = [s for s in signals if not s.accepted]
            rej_enriched = [
                s for s in rej_signals
                if s.price_change_5m_pct is not None
                and s.price_change_15m_pct is not None
                and s.volume_ratio is not None
            ]
            top_rejected = sorted(
                rej_enriched,
                key=lambda s: (-s.score, -(s.price_change_5m_pct or 0.0), -(s.volume_ratio or 0.0)),
            )[: out.top_rejected_n]
            rej_missing = [
                s for s in rej_signals
                if s.price_change_5m_pct is None
                or s.price_change_15m_pct is None
                or s.volume_ratio is None
            ]
            missing_data_sample = rej_missing[:10]

        duration = time.time() - start_ts
        return ScanResult(
            scan_id=scan_id,
            timestamp=start_ts,
            scan_duration_seconds=duration,
            signals=signals,
            coverage=coverage,
            top_rejected=top_rejected,
            missing_data_sample=missing_data_sample,
            preselection_report=preselection_report,
        )

    @staticmethod
    def _pick_btc_eth_refs(candidates: List, already_selected: List) -> List:
        """Geef max. één BTC- en één ETH-candidate per exchange terug voor context-verrijking.

        Deze candidates worden nooit signalen: EXCLUDED_MAJOR_ASSET filtert ze weg.
        """
        already_ids = {id(c) for c in already_selected}
        refs: dict = {}  # (exchange, base) → candidate
        for c in candidates:
            if id(c) in already_ids:
                continue
            base = c.trading_pair.split("-")[0].upper()
            if base not in ("BTC", "ETH"):
                continue
            key = (c.exchange, base)
            if key not in refs:
                refs[key] = c
        return list(refs.values())

    @staticmethod
    def _compute_market_context(enriched_candidates: List) -> dict:
        """Bereken marktcontext-metrics over alle verrijkte candidates van deze scan.

        Returns een dict met:
          regime  — gemiddelde Δ15m van verrijkte paren (markttemperatuur, float of None)
          breadth — % paren met positieve Δ15m (0.0–100.0, float of None)
          btc_d15m — Δ15m van BTC (eerste BTC-pair gevonden, float of None)
          eth_d15m — Δ15m van ETH (eerste ETH-pair gevonden, float of None)
        """
        d15m_values = [
            c.price_change_15m_pct
            for c in enriched_candidates
            if c.price_change_15m_pct is not None
        ]
        regime: Optional[float] = None
        breadth: Optional[float] = None
        if d15m_values:
            regime = round(sum(d15m_values) / len(d15m_values), 4)
            positive = sum(1 for v in d15m_values if v > 0)
            breadth = round(100.0 * positive / len(d15m_values), 1)

        btc_d15m: Optional[float] = None
        eth_d15m: Optional[float] = None
        for c in enriched_candidates:
            base = c.trading_pair.split("-")[0].upper()
            if btc_d15m is None and base == "BTC" and c.price_change_15m_pct is not None:
                btc_d15m = c.price_change_15m_pct
            if eth_d15m is None and base == "ETH" and c.price_change_15m_pct is not None:
                eth_d15m = c.price_change_15m_pct
            if btc_d15m is not None and eth_d15m is not None:
                break

        return {"regime": regime, "breadth": breadth, "btc_d15m": btc_d15m, "eth_d15m": eth_d15m}

    def _build_coverage(
        self,
        candidates: List,
        signals: List[MomentumSignal],
        now: float,
        sample_mode: bool = False,
    ) -> DataCoverageReport:
        """Compute per-exchange data-coverage stats from enriched candidates."""
        staleness_s = self._config.candidate_filters.max_orderbook_staleness_seconds
        ex_map: dict = {}
        enriched_total = 0
        enriched_complete = 0
        enriched_incomplete = 0
        for c in candidates:
            if c.exchange not in ex_map:
                ex_map[c.exchange] = ExchangeCoverageStats(exchange=c.exchange)
            stats = ex_map[c.exchange]
            stats.pairs_total += 1
            stats.tickers_ok += 1
            if c.orderbook_depth_quote is not None:
                stats.orderbook_ok += 1
            if c.price_change_1m_pct is not None:
                stats.candles_1m_ok += 1
            if c.price_change_3m_pct is not None:
                stats.candles_3m_ok += 1
            if c.price_change_5m_pct is not None:
                stats.candles_5m_ok += 1
            if c.price_change_15m_pct is not None:
                stats.candles_15m_ok += 1
            if c.volume_ratio is not None:
                stats.volume_ratio_ok += 1
            complete = (
                c.price_change_5m_pct is not None
                and c.price_change_15m_pct is not None
                and c.volume_ratio is not None
            )
            if complete:
                stats.momentum_data_complete += 1
            else:
                stats.missing_momentum_data += 1
            # Track enriched candidates (any market-data was fetched)
            is_enriched = c.candles_fetched_at > 0 or c.ob_fetched_at > 0
            if is_enriched:
                enriched_total += 1
                if complete:
                    enriched_complete += 1
                else:
                    enriched_incomplete += 1

        for sig in signals:
            if sig.exchange in ex_map:
                if sig.accepted:
                    ex_map[sig.exchange].accepted += 1
                else:
                    ex_map[sig.exchange].rejected += 1

        # Missing breakdown from raw candidate fields
        breakdown: dict = {}
        for c in candidates:
            if c.price_change_5m_pct is None:
                breakdown["MISSING_PRICE_CHANGE_5M"] = breakdown.get("MISSING_PRICE_CHANGE_5M", 0) + 1
            if c.price_change_15m_pct is None:
                breakdown["MISSING_PRICE_CHANGE_15M"] = breakdown.get("MISSING_PRICE_CHANGE_15M", 0) + 1
            if c.volume_ratio is None:
                breakdown["MISSING_VOLUME_RATIO"] = breakdown.get("MISSING_VOLUME_RATIO", 0) + 1
            if c.candles_fetched_at == 0.0:
                breakdown["MISSING_CANDLES"] = breakdown.get("MISSING_CANDLES", 0) + 1
            if c.orderbook_depth_quote is None:
                breakdown["MISSING_ORDERBOOK"] = breakdown.get("MISSING_ORDERBOOK", 0) + 1
            if c.ob_fetched_at > 0 and (now - c.ob_fetched_at) > staleness_s:
                breakdown["STALE_ORDERBOOK"] = breakdown.get("STALE_ORDERBOOK", 0) + 1

        total = len(candidates)
        total_missing = sum(s.missing_momentum_data for s in ex_map.values())
        if sample_mode:
            # In sample mode only a subset is enriched — warn only if enriched data is bad
            blind = enriched_total > 0 and (enriched_incomplete / enriched_total) > 0.20
        else:
            blind = total > 0 and (total_missing / total) > 0.80

        return DataCoverageReport(
            by_exchange=list(ex_map.values()),
            missing_reason_breakdown={k: v for k, v in sorted(breakdown.items()) if v > 0},
            blind_warning=blind,
            sample_mode=sample_mode,
            enriched_total=enriched_total,
            enriched_complete=enriched_complete,
            enriched_incomplete=enriched_incomplete,
        )

    def _classify_label(
        self,
        candidate,
        score: float,
        market_regime: Optional[float] = None,
    ) -> str:
        """Classify an accepted signal as BUY_NOW, WATCH, or TOO_LATE (US-201).

        Priority order:
        1. TOO_LATE  — move already too large; suppress from Telegram.
        2. BUY_NOW   — high score AND move not yet extended (< buy_now_delta_15m_max_pct).
        3. WATCH     — early momentum; sent to Telegram for manual review.
        """
        cls_cfg = self._config.classification
        p15 = candidate.price_change_15m_pct or 0.0
        p5 = candidate.price_change_5m_pct or 0.0
        accel = candidate.acceleration_score or 0.0

        too_late = (
            p15 > cls_cfg.too_late_delta_15m_pct
            or p5 > cls_cfg.too_late_delta_5m_pct
            or (p15 > cls_cfg.too_late_delta_15m_soft and accel < cls_cfg.too_late_acceleration_threshold)
        )
        if too_late:
            return "TOO_LATE"
        # Downgrade BUY_NOW → WATCH if 15m move is borderline extended
        bn_max = getattr(cls_cfg, "buy_now_delta_15m_max_pct", 0.0)
        if score >= cls_cfg.buy_now_min_score and (bn_max <= 0.0 or p15 < bn_max):
            # Conservative paper-test gate: block BUY_NOW in strong bullish regime
            # (Q4 proxy via absolute market_regime threshold).
            q4_cutoff = cls_cfg.paper_block_buy_now_when_market_regime_ge_pct
            if (
                cls_cfg.paper_test_enabled
                and q4_cutoff > 0.0
                and market_regime is not None
                and market_regime >= q4_cutoff
            ):
                return "WATCH"
            return "BUY_NOW"
        return "WATCH"

    def _annotate(self, candidates):
        """Mark candidates with grid-position and blacklist flags (read-only).

        Blacklist: uitsluitend de eigen ``scanner_blacklist`` uit de service-config.
        Grid-posities: optioneel, alleen als ``grid_db_path`` is opgegeven per exchange.
        De grid-bot ``blacklist_yaml`` wordt bewust NIET gelezen — de scanner is
        onafhankelijk van de grid-bot configuratie.
        """
        # Eigen scanner-blacklist (staat in momentum_signal_service.yaml)
        blacklisted: set = set(self._config.scanner_blacklist)

        # Optioneel: actieve grid-posities per exchange (read-only SQLite)
        active_pairs: set = set()
        for cfg in self._config.exchanges:
            if cfg.grid_db_path:
                reader = GridPositionReader(cfg.grid_db_path)
                active_pairs.update(reader.get_active_pairs())
                reader.close()

        for c in candidates:
            c.active_grid_position = c.trading_pair in active_pairs
            c.blacklisted = c.trading_pair in blacklisted
        return candidates

    async def _close(self) -> None:
        if self._session:
            await self._session.close()
        if self._store:
            self._store.close()
        if self._outcome_tracker:
            self._outcome_tracker.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _async_main(
    config_path: str, db_path: str, snapshot_path: str
) -> None:
    config = ServiceConfig.from_yaml(config_path)
    service = MomentumSignalService(
        config=config, db_path=db_path, snapshot_path=snapshot_path
    )
    await service.start()


async def _async_debug_pair(config_path: str, debug_pair: str) -> None:
    """Fetch and display all data for a single pair. READ-ONLY diagnostic tool."""
    from multi_coin_grid_pro.signals.momentum_buy_now_scorer import BuyNowScorer as _BuyNowScorer
    from multi_coin_grid_pro.signals.momentum_filters import HardFilter
    from multi_coin_grid_pro.signals.momentum_market_data import _FETCHER_MAP, KrakenFetcher, _internal_to_bitget_symbol

    if ":" not in debug_pair:
        print("ERROR: --debug-pair must be in format 'exchange:PAIR', e.g. okx:SOL-USDT")
        return

    exchange, pair = debug_pair.split(":", 1)
    config = ServiceConfig.from_yaml(config_path)

    exc_cfg = next(
        (e for e in config.exchanges if e.exchange.lower() == exchange.lower()), None
    )
    if exc_cfg is None:
        print(f"ERROR: exchange '{exchange}' not found in config")
        return

    fetcher_cls = _FETCHER_MAP.get(exchange.lower())
    if fetcher_cls is None:
        print(f"ERROR: no fetcher available for exchange '{exchange}'")
        return

    print("\n" + "=" * 68)
    print(f"  DEBUG PAIR: {exchange.upper()}:{pair}")
    print("=" * 68)

    semaphore = asyncio.Semaphore(5)
    async with aiohttp.ClientSession() as session:
        fetcher = fetcher_cls(
            api_url=exc_cfg.api_url,
            quote_assets=exc_cfg.quote_assets,
            session=session,
            semaphore=semaphore,
            timeout_seconds=10.0,
        )

        # Fetch full universe (also populates Kraken pair_name_map)
        print("\n[TICKER] Fetching universe...")
        candidates = await fetcher.fetch_candidates()
        candidate = next((c for c in candidates if c.trading_pair == pair), None)

        if candidate is None:
            print(f"  ERROR: pair '{pair}' not found in {exchange} universe")
            print(f"  Available pairs (first 10): {[c.trading_pair for c in candidates[:10]]}")
            return

        # Resolve exchange-native symbol
        if isinstance(fetcher, KrakenFetcher):
            native_symbol = fetcher._pair_name_map.get(pair, "n/a")
        elif exchange.lower() == "bitget":
            native_symbol = _internal_to_bitget_symbol(pair)
        else:
            native_symbol = pair   # OKX uses same format

        print(f"  exchange:        {exchange.upper()}")
        print(f"  pair (internal): {pair}")
        print(f"  symbol at exch:  {native_symbol}")
        print("  ticker status:   found")
        print(f"  price:           {candidate.price}")
        print(f"  bid:             {candidate.bid}")
        print(f"  ask:             {candidate.ask}")
        print(f"  spread_pct:      {candidate.spread_pct:.4f}%")

        # Fetch candles
        print("\n[CANDLES] Fetching 1m candles (limit=20)...")
        candles = await fetcher.fetch_candles(pair, limit=20)
        print(f"  candles fetched:       {len(candles)}")
        now = time.time()
        if candles:
            print(f"  latest close:          {candles[-1].close}")
            print(f"  close 5m ago:          {candles[-6].close if len(candles) >= 6 else 'N/A (too few)'}")
            print(f"  close 15m ago:         {candles[-16].close if len(candles) >= 16 else 'N/A (too few)'}")
            from multi_coin_grid_pro.signals.momentum_indicators import apply_candle_metrics
            apply_candle_metrics(candidate, candles, now)
        print(f"  price_change_5m_pct:   {candidate.price_change_5m_pct}")
        print(f"  price_change_15m_pct:  {candidate.price_change_15m_pct}")
        print(f"  volume_ratio:          {candidate.volume_ratio}")
        print(f"  volatility_pct:        {candidate.volatility_pct}")

        # Fetch orderbook
        print("\n[ORDERBOOK] Fetching depth (count=20)...")
        ob = await fetcher.fetch_orderbook(pair, count=20)
        if ob is not None:
            from multi_coin_grid_pro.signals.momentum_indicators import apply_orderbook_metrics
            apply_orderbook_metrics(candidate, ob)
            print(f"  orderbook levels bid:  {len(ob.bids)}")
            print(f"  orderbook levels ask:  {len(ob.asks)}")
            print(f"  best bid:              {ob.bids[0] if ob.bids else 'N/A'}")
            print(f"  best ask:              {ob.asks[0] if ob.asks else 'N/A'}")
            print(f"  orderbook_depth_quote: {candidate.orderbook_depth_quote:.2f}")
            print(f"  orderbook_imbalance:   {candidate.orderbook_imbalance:.4f}")
        else:
            print("  ERROR: orderbook fetch returned None")

        # Score and filter
        print("\n[FILTER + SCORE]")
        hard_filter = HardFilter()
        fr = hard_filter.apply([candidate], config, now=now)
        if fr.accepted:
            scorer = _BuyNowScorer()
            score = scorer.score_candidate(candidate)
            cls_cfg = config.classification
            accepted = score >= cls_cfg.watch_min_score
            print("  hard filter:      PASS")
            print(f"  score (BuyNow):   {score:.4f}")
            print(f"  accepted:         {accepted}")
            print("  rejection_reason: n/a")
        else:
            rej = fr.rejected[0]
            print("  hard filter:      FAIL")
            print("  score:            0.0000")
            print("  accepted:         False")
            print(f"  rejection_reason: {rej.rejection_reason}")
            print(f"  all_reasons:      {rej.all_reasons}")

    print("\n" + "=" * 68 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Momentum signal service (read-only, signal_only mode)"
    )
    parser.add_argument(
        "--config",
        default="multi_coin_grid_pro/config/momentum_signal_service.yaml",
        help="Path to momentum_signal_service.yaml",
    )
    parser.add_argument(
        "--db-path",
        default="data/momentum_signals.sqlite",
        help="SQLite database path for signal storage",
    )
    parser.add_argument(
        "--snapshot-path",
        default="data/momentum_signals.json",
        help="JSON snapshot output path",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--debug-pair",
        default=None,
        metavar="EXCHANGE:PAIR",
        help="Fetch and display all data for a single pair, e.g. okx:SOL-USDT",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )
    if args.debug_pair:
        asyncio.run(_async_debug_pair(args.config, args.debug_pair))
    else:
        asyncio.run(_async_main(args.config, args.db_path, args.snapshot_path))


if __name__ == "__main__":
    main()
