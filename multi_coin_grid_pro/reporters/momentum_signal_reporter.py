# momentum_signal_reporter.py — console/log formatter for ScanResult.
# Pure formatting — no I/O, no HTTP, no orders.
import datetime
import logging
from typing import List, Optional

from multi_coin_grid_pro.signals.momentum_models import (
    DataCoverageReport,
    MomentumSignal,
    PreselectionReport,
    ScanResult,
)

logger = logging.getLogger(__name__)

DISCLAIMER = "SIGNAL ONLY — GEEN ORDERS WORDEN GEPLAATST"

_SEP_WIDE = "=" * 72
_SEP_THIN = "-" * 72


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "   n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _fmt_vol(value: Optional[float]) -> str:
    if value is None:
        return "  n/a"
    return f"{value:4.1f}x"


def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:>10,.2f}"
    if price >= 1:
        return f"{price:>10.4f}"
    return f"{price:>10.6f}"


def _fmt_ts(ts: float) -> str:
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _signal_row(sig: MomentumSignal) -> str:
    rank = f"{sig.rank:>2}" if sig.rank is not None else " -"
    exchange = f"{sig.exchange:<8}"
    pair = f"{sig.trading_pair:<14}"
    price = _fmt_price(sig.price)
    spread = f"{sig.spread_pct:6.3f}%"
    score = f"{sig.score:5.2f}"
    d5m = _fmt_pct(sig.price_change_5m_pct)
    d15m = _fmt_pct(sig.price_change_15m_pct)
    vol = _fmt_vol(sig.volume_ratio)
    return f"  {rank}  {exchange}  {pair}  {price}  {spread}  {score}  {d5m}  {d15m}  {vol}"


def _rejection_summary(breakdown: dict) -> str:
    if not breakdown:
        return "  (geen)"
    parts = [f"{k}={v}" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])]
    return "  " + "  ".join(parts)


def _fmt_int(value: int, width: int = 4) -> str:
    return f"{value:{width}d}"


def _fmt_coverage(cov: DataCoverageReport) -> str:
    lines: List[str] = []
    lines.append(_SEP_WIDE)
    lines.append("  DATA COVERAGE REPORT")
    lines.append(_SEP_THIN)
    hdr = (
        f"  {'Exchange':<12}  {'Pairs':>5}  {'Ticker':>6}  {'OB':>4}  "
        f"{'C1m':>4}  {'C5m':>4}  {'C15m':>5}  {'VolR':>4}  "
        f"{'Complete':>8}  {'Missing':>7}  {'OK':>4}  {'Reject':>6}"
    )
    lines.append(hdr)
    lines.append("  " + "-" * (len(hdr) - 2))
    for s in cov.by_exchange:
        lines.append(
            f"  {s.exchange:<12}  {s.pairs_total:>5}  {s.tickers_ok:>6}  "
            f"{s.orderbook_ok:>4}  {s.candles_1m_ok:>4}  {s.candles_5m_ok:>4}  "
            f"{s.candles_15m_ok:>5}  {s.volume_ratio_ok:>4}  "
            f"{s.momentum_data_complete:>8}  {s.missing_momentum_data:>7}  "
            f"{s.accepted:>4}  {s.rejected:>6}"
        )
    lines.append(_SEP_THIN)
    if cov.sample_mode:
        lines.append(
            f"  [SAMPLE MODE] {cov.enriched_total} pairs enriched  "
            f"({cov.enriched_complete} complete, {cov.enriched_incomplete} incomplete)"
        )
        # Per-exchange enriched summary
        for s in cov.by_exchange:
            lines.append(
                f"    {s.exchange:<12}  complete {s.momentum_data_complete}/{s.orderbook_ok}"
            )
        if cov.blind_warning:
            lines.append(_SEP_THIN)
            lines.append(
                "  ⚠ [MOMENTUM_DATA_WARNING] More than 20% of enriched pairs are incomplete."
            )
            lines.append("    Check candle/volume fetchers for enriched pairs.")
    else:
        if cov.missing_reason_breakdown:
            lines.append("  Missing breakdown:")
            for reason, count in sorted(cov.missing_reason_breakdown.items(), key=lambda x: -x[1]):
                lines.append(f"    {reason:<30} {count}")
        if cov.blind_warning:
            lines.append(_SEP_THIN)
            lines.append(
                "  ⚠ [MOMENTUM_DATA_WARNING] More than 80% of pairs are missing momentum data."
            )
            lines.append("    Scanner may be blind. Check candle/volume fetchers.")
    lines.append(_SEP_WIDE)
    return "\n".join(lines)


def _fmt_top_rejected_enriched(signals: List[MomentumSignal]) -> str:
    """Format enriched rejected candidates (all have complete momentum data)."""
    if not signals:
        return ""
    lines: List[str] = []
    lines.append(_SEP_WIDE)
    lines.append(f"  TOP {len(signals)} REJECTED ENRICHED CANDIDATES (complete data, best score eerst)")
    lines.append(_SEP_THIN)
    lines.append(
        f"  {'Exchange':<8}  {'Pair':<14}  {'Score':>5}  {'Δ5m':>6}  {'Δ15m':>6}  "
        f"{'VolR':>5}  {'Spread':>7}  {'Depth':>10}  Reason"
    )
    lines.append(_SEP_THIN)
    for sig in signals:
        depth = f"{sig.orderbook_depth_quote:>10,.0f}" if sig.orderbook_depth_quote is not None else "       n/a"
        lines.append(
            f"  {sig.exchange:<8}  {sig.trading_pair:<14}  {sig.score:>5.2f}  "
            f"{_fmt_pct(sig.price_change_5m_pct)}  {_fmt_pct(sig.price_change_15m_pct)}  "
            f"{_fmt_vol(sig.volume_ratio)}  {sig.spread_pct:>6.3f}%  {depth}  "
            f"{sig.rejection_reason or 'n/a'}"
        )
    lines.append(_SEP_WIDE)
    return "\n".join(lines)


def _fmt_missing_data_sample(signals: List[MomentumSignal]) -> str:
    """Format up to 10 n/a candidates for debug visibility."""
    if not signals:
        return ""
    lines: List[str] = []
    lines.append(_SEP_WIDE)
    lines.append(f"  MISSING DATA SAMPLE ({len(signals)} candidates with n/a metrics — debug only)")
    lines.append(_SEP_THIN)
    lines.append(
        f"  {'Exchange':<8}  {'Pair':<14}  {'Score':>5}  {'Δ5m':>6}  {'Δ15m':>6}  "
        f"{'VolR':>5}  {'Spread':>7}  {'Depth':>10}  Reason"
    )
    lines.append(_SEP_THIN)
    for sig in signals:
        depth = f"{sig.orderbook_depth_quote:>10,.0f}" if sig.orderbook_depth_quote is not None else "       n/a"
        lines.append(
            f"  {sig.exchange:<8}  {sig.trading_pair:<14}  {sig.score:>5.2f}  "
            f"{_fmt_pct(sig.price_change_5m_pct)}  {_fmt_pct(sig.price_change_15m_pct)}  "
            f"{_fmt_vol(sig.volume_ratio)}  {sig.spread_pct:>6.3f}%  {depth}  "
            f"{sig.rejection_reason or 'n/a'}"
        )
    lines.append(_SEP_WIDE)
    return "\n".join(lines)


def _fmt_preselection(report: PreselectionReport) -> str:
    """Format the pre-enrichment selection summary."""
    lines: List[str] = []
    lines.append(_SEP_WIDE)
    lines.append("  PRE-ENRICHMENT SELECTION")
    lines.append(_SEP_THIN)
    hdr = (
        f"  {'Exchange':<10}  {'Region':<8}  {'Quotes':<10}  {'Enabled':<7}"
        f"  {'Universe':>8}  {'Eligible':>8}  {'Selected':>8}"
    )
    lines.append(hdr)
    lines.append("  " + "-" * (len(hdr) - 2))
    for s in report.by_exchange:
        quotes = ",".join(s.allowed_quote_assets) if s.allowed_quote_assets else "—"
        enabled_str = "true" if s.enabled else "false"
        lines.append(
            f"  {s.exchange:<10}  {s.region:<8}  {quotes:<10}  {enabled_str:<7}"
            f"  {s.universe_total:>8}  {s.eligible:>8}  {s.selected:>8}"
        )
    lines.append(_SEP_THIN)
    lines.append(
        f"  Total: {report.total_universe} universe  \u2192  {report.total_selected} selected for enrichment"
    )
    # Top examples per exchange
    for s in report.by_exchange:
        if not s.top_examples:
            continue
        lines.append(_SEP_THIN)
        lines.append(f"  Top {len(s.top_examples)} selected — {s.exchange}")
        lines.append(
            f"  {'Pair':<16}  {'Spread':>7}  {'Vol24h(K)':>10}  {'Δ24h%':>7}  {'PreScore':>8}"
        )
        for ex in s.top_examples:
            vol_k = f"{ex.quote_volume_24h / 1000:>10,.1f}" if ex.quote_volume_24h is not None else "       n/a"
            chg = f"{ex.price_change_24h_pct:>+7.2f}%" if ex.price_change_24h_pct is not None else "    n/a"
            lines.append(
                f"  {ex.trading_pair:<16}  {ex.spread_pct:>6.3f}%  {vol_k}  {chg}  {ex.pre_score:>8.4f}"
            )
    lines.append(_SEP_WIDE)
    return "\n".join(lines)


class SignalReporter:
    """Format a :class:`ScanResult` as a plain-text table for logging or console."""

    def format_scan(self, scan_result: ScanResult) -> str:
        """Return the full formatted report as a single string."""
        lines: List[str] = []

        lines.append(_SEP_WIDE)
        lines.append(f"  {DISCLAIMER}")
        lines.append(_SEP_WIDE)

        # Header
        ts_str = _fmt_ts(scan_result.timestamp)
        dur = f"{scan_result.scan_duration_seconds:.1f}s"
        lines.append(
            f"  Scan  : {scan_result.scan_id}   {ts_str}   ({dur})"
        )
        lines.append(
            f"  Pairs : {scan_result.total_scanned} gescand  │  "
            f"{scan_result.total_accepted} geaccepteerd  │  "
            f"{scan_result.total_rejected} verworpen"
        )
        lines.append(_SEP_THIN)

        # Column header
        lines.append(
            "  Rk  Exchange    Pair              Prijs  Spread  Score"
            "    Δ5m    Δ15m   VolR"
        )
        lines.append(_SEP_THIN)

        # Signal rows
        top = scan_result.top_signals
        if top:
            for sig in top:
                lines.append(_signal_row(sig))
        else:
            lines.append(
                "  [MOMENTUM_SIGNAL] Geen geldige momentum candidates gevonden."
            )

        lines.append(_SEP_THIN)

        # Rejection breakdown
        lines.append("  Verworpen:")
        lines.append(_rejection_summary(scan_result.rejection_breakdown))
        lines.append(_SEP_WIDE)

        # Pre-enrichment selection section
        if scan_result.preselection_report is not None:
            lines.append(_fmt_preselection(scan_result.preselection_report))

        # Data coverage section
        if scan_result.coverage is not None:
            lines.append(_fmt_coverage(scan_result.coverage))

        # Top rejected enriched section (complete momentum data, no n/a)
        if scan_result.top_rejected:
            lines.append(_fmt_top_rejected_enriched(scan_result.top_rejected))

        # Missing data sample section (n/a candidates, debug only)
        if scan_result.missing_data_sample:
            lines.append(_fmt_missing_data_sample(scan_result.missing_data_sample))

        return "\n".join(lines)

    def log_scan(
        self,
        scan_result: ScanResult,
        log: Optional[logging.Logger] = None,
    ) -> None:
        """Log the formatted report line-by-line.

        Uses *log* if provided, otherwise the module-level logger.
        """
        target = log if log is not None else logger
        report = self.format_scan(scan_result)
        for line in report.splitlines():
            target.info(line)
