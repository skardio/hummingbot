"""
Why-No-Trade Report v2 - Operator-Grade Analysis

US-E3.x: Funnel + Thresholds + Top Symbols + Regime breakdown
"""

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class FunnelMetrics:
    """Pipeline funnel metrics"""
    intents_total: int = 0
    smartentry_pass: int = 0
    mtf_pass: int = 0
    risk_allow: int = 0
    orders_submitted: int = 0
    fills: int = 0

    def conversion_rate(self, numerator: int, denominator: int) -> float:
        """Calculate conversion rate"""
        return (numerator / denominator * 100) if denominator > 0 else 0.0


@dataclass
class ThresholdStats:
    """Threshold vs reality statistics"""
    reason_code: str
    metric_name: str
    threshold: float
    threshold_direction: str  # ">" or "<"
    p50: float
    p90: float
    min_val: float
    max_val: float
    sample_count: int

    def __str__(self):
        direction_symbol = "≥" if self.threshold_direction == ">" else "≤"
        return (
            f"  {self.reason_code} ({self.metric_name}):\n"
            f"    Threshold: {direction_symbol} {self.threshold:.2f}\n"
            f"    Reality: p50={self.p50:.2f}, p90={self.p90:.2f}, "
            f"range=[{self.min_val:.2f}–{self.max_val:.2f}] (n={self.sample_count})"
        )


@dataclass
class SymbolRejectionStats:
    """Per-symbol rejection statistics"""
    symbol: str
    total_denied: int
    total_evaluated: int
    denial_rate: float
    top_reason: str
    top_stage: str
    reason_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class RegimeBreakdown:
    """Rejection breakdown per regime"""
    regime: str
    total_intents: int
    denied: int
    top_reasons: List[Tuple[str, int, float]]  # (reason, count, pct)


class WhyNoTradeV2:
    """
    Operator-grade Why-No-Trade analyzer.

    Features:
    - Pipeline funnel (stage-by-stage conversion)
    - Threshold vs reality stats (p50/p90)
    - Top rejected symbols ("log vampires")
    - Regime breakdown (optional)
    """

    # Metric mappings: reason_code → (metadata_key, threshold_config_key, direction)
    METRIC_MAPPINGS = {
        'ATR_TOO_LOW': ('atr_pct', 'min_atr_pct_for_grid', '>'),
        'ATR_TOO_HIGH': ('atr_pct', 'max_atr_pct_for_grid', '<'),
        'VWAP_DEVIATION_TOO_HIGH': ('vwap_dev_pct', 'vwap_max_deviation_pct', '<'),
        'RSI_OVERBOUGHT': ('rsi', 'rsi_block_min', '<'),
        'RSI_EXTREME_LOW': ('rsi', 'rsi_extreme_low', '>'),
    }

    def __init__(self, log_dir: Path, config: Optional[Dict] = None):
        """
        Initialize analyzer.

        Args:
            log_dir: Directory containing events_*.jsonl files
            config: Bot config for threshold values
        """
        self.log_dir = Path(log_dir)
        self.config = config or {}
        self._metadata_warning_logged = set()  # Track warnings to avoid spam

    def analyze(
        self,
        window_minutes: int = 60,
        top_n_reasons: int = 10,
        top_n_symbols: int = 5
    ) -> str:
        """
        Generate comprehensive Why-No-Trade report.

        Args:
            window_minutes: Analysis window (default 60min)
            top_n_reasons: Number of top reasons to show
            top_n_symbols: Number of top symbols to show

        Returns:
            Formatted report string
        """
        # Read events in window
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=window_minutes)
        events = self._read_events(start_time, end_time)

        if not events:
            return f"[WHY-NO-TRADE v2] No events in last {window_minutes} minutes"

        # Build report sections
        report = []
        report.append("=" * 80)
        report.append("WHY-NO-TRADE REPORT v2 - Operator Grade")
        report.append("=" * 80)
        report.append(f"Window: {start_time.strftime('%H:%M')} → {end_time.strftime('%H:%M')} ({window_minutes}m)")
        report.append("")

        # 1) Funnel metrics
        funnel = self._calculate_funnel(events)
        report.append(self._format_funnel(funnel))
        report.append("")

        # 2) Top rejection reasons (overall + per stage)
        top_reasons = self._calculate_top_reasons(events, top_n_reasons)
        report.append(self._format_top_reasons(top_reasons))
        report.append("")

        # 3) Thresholds vs Reality (top 3 blockers)
        threshold_stats = self._calculate_threshold_stats(events, top_reasons[:3])
        if threshold_stats:
            report.append(self._format_threshold_stats(threshold_stats))
            report.append("")

        # 4) Top symbols
        symbol_stats = self._calculate_symbol_stats(events, top_n_symbols)
        if symbol_stats:
            report.append(self._format_symbol_stats(symbol_stats))
            report.append("")

        # 5) Regime breakdown (optional)
        regime_breakdown = self._calculate_regime_breakdown(events, top_n_reasons)
        if regime_breakdown:
            report.append(self._format_regime_breakdown(regime_breakdown))
            report.append("")

        report.append("=" * 80)

        return "\n".join(report)

    def _read_events(self, start_time: datetime, end_time: datetime) -> List[dict]:
        """Read events from JSONL files within time range"""
        events = []
        jsonl_files = sorted(self.log_dir.glob("events_*.jsonl"))

        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, 'r') as f:
                    for line in f:
                        try:
                            event = json.loads(line.strip())
                            # Parse timestamp
                            event_time = datetime.fromisoformat(event.get('timestamp', ''))
                            if start_time <= event_time < end_time:
                                events.append(event)
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception:
                continue

        return events

    def _calculate_funnel(self, events: List[dict]) -> FunnelMetrics:
        """Calculate pipeline funnel metrics"""
        funnel = FunnelMetrics()

        # Track unique correlation_ids per stage
        all_correlation_ids = set()
        smartentry_passed_ids = set()
        mtf_passed_ids = set()
        risk_passed_ids = set()

        for event in events:
            event_type = event.get('event_type')
            stage = event.get('stage', '')
            correlation_id = event.get('correlation_id')

            if not correlation_id:
                continue

            # Track all intents
            if event_type in ('gate_denied', 'gate_passed'):
                all_correlation_ids.add(correlation_id)

            # Track stage passes
            if event_type == 'gate_passed':
                if 'SMART_ENTRY' in stage or 'ENTRY_FILTER' in stage:
                    smartentry_passed_ids.add(correlation_id)
                elif 'TIMEFRAME' in stage or 'MTF' in stage:
                    mtf_passed_ids.add(correlation_id)
                elif 'RISK' in stage:
                    risk_passed_ids.add(correlation_id)

            # Track execution
            if event_type == 'order_submitted':
                funnel.orders_submitted += 1
            elif event_type == 'order_filled':
                funnel.fills += 1

        funnel.intents_total = len(all_correlation_ids)
        funnel.smartentry_pass = len(smartentry_passed_ids)
        funnel.mtf_pass = len(mtf_passed_ids)
        funnel.risk_allow = len(risk_passed_ids)

        return funnel

    def _format_funnel(self, funnel: FunnelMetrics) -> str:
        """Format funnel metrics for display"""
        lines = [
            "📊 PIPELINE FUNNEL",
            "-" * 80,
            f"Total Intents:        {funnel.intents_total:6d}",
        ]

        if funnel.intents_total > 0:
            # SmartEntry
            se_rate = funnel.conversion_rate(funnel.smartentry_pass, funnel.intents_total)
            lines.append(
                f"  ↓ SmartEntry Pass:  {funnel.smartentry_pass:6d}  "
                f"({se_rate:5.1f}% of intents)"
            )

            # MTF
            if funnel.smartentry_pass > 0:
                mtf_rate = funnel.conversion_rate(funnel.mtf_pass, funnel.smartentry_pass)
                lines.append(
                    f"    ↓ MTF Pass:       {funnel.mtf_pass:6d}  "
                    f"({mtf_rate:5.1f}% of SE-pass)"
                )
            else:
                lines.append(f"    ↓ MTF Pass:       {funnel.mtf_pass:6d}  (N/A)")

            # Risk
            if funnel.mtf_pass > 0:
                risk_rate = funnel.conversion_rate(funnel.risk_allow, funnel.mtf_pass)
                lines.append(
                    f"      ↓ Risk Allow:   {funnel.risk_allow:6d}  "
                    f"({risk_rate:5.1f}% of MTF-pass)"
                )
            else:
                lines.append(f"      ↓ Risk Allow:   {funnel.risk_allow:6d}  (N/A)")

            # Orders
            lines.append(f"        ↓ Orders:     {funnel.orders_submitted:6d}")
            lines.append(f"          ↓ Fills:    {funnel.fills:6d}")

        lines.append("-" * 80)
        return "\n".join(lines)

    def _calculate_top_reasons(
        self,
        events: List[dict],
        top_n: int
    ) -> List[Tuple[str, str, int, float]]:
        """
        Calculate top rejection reasons.

        Returns:
            List of (reason_code, stage, count, percentage)
        """
        denied_events = [e for e in events if e.get('event_type') == 'gate_denied']

        if not denied_events:
            return []

        # Count by reason
        reason_counter = Counter()
        reason_stage_map = {}  # reason -> most common stage
        stage_for_reason = defaultdict(list)

        for event in denied_events:
            reason = event.get('reason_code', 'UNKNOWN')
            stage = event.get('stage', 'UNKNOWN')
            reason_counter[reason] += 1
            stage_for_reason[reason].append(stage)

        # Determine most common stage per reason
        for reason, stages in stage_for_reason.items():
            reason_stage_map[reason] = Counter(stages).most_common(1)[0][0]

        # Build result
        total = len(denied_events)
        result = []
        for reason, count in reason_counter.most_common(top_n):
            pct = (count / total * 100)
            stage = reason_stage_map.get(reason, 'UNKNOWN')
            result.append((reason, stage, count, pct))

        return result

    def _format_top_reasons(self, top_reasons: List[Tuple[str, str, int, float]]) -> str:
        """Format top reasons for display"""
        if not top_reasons:
            return "🔍 TOP REJECTION REASONS\n" + "-" * 80 + "\nNo rejections"

        lines = [
            "🔍 TOP REJECTION REASONS",
            "-" * 80,
        ]

        for idx, (reason, stage, count, pct) in enumerate(top_reasons, 1):
            lines.append(
                f"  {idx:2d}. {reason:30s}  {count:5d} ({pct:5.1f}%)  [{stage}]"
            )

        lines.append("-" * 80)
        return "\n".join(lines)

    def _calculate_threshold_stats(
        self,
        events: List[dict],
        top_reasons: List[Tuple[str, str, int, float]]
    ) -> List[ThresholdStats]:
        """Calculate threshold vs reality stats for top blockers"""
        stats = []

        for reason_code, _, _, _ in top_reasons:
            if reason_code not in self.METRIC_MAPPINGS:
                continue

            metric_key, config_key, direction = self.METRIC_MAPPINGS[reason_code]

            # Extract metric values from denied events
            values = []
            for event in events:
                if (event.get('event_type') == 'gate_denied' and
                        event.get('reason_code') == reason_code):
                    metadata = event.get('metadata', {})
                    if metric_key in metadata:
                        try:
                            values.append(float(metadata[metric_key]))
                        except (ValueError, TypeError):
                            pass

            if not values:
                # Log warning once per metric
                if reason_code not in self._metadata_warning_logged:
                    self._metadata_warning_logged.add(reason_code)
                    # Warning will be logged by caller
                continue

            # Get threshold from config
            threshold = self.config.get(config_key)
            if threshold is None:
                threshold = 0.0  # Default if not in config

            # Calculate stats
            stat = ThresholdStats(
                reason_code=reason_code,
                metric_name=metric_key,
                threshold=float(threshold),
                threshold_direction=direction,
                p50=statistics.median(values),
                p90=statistics.quantiles(values, n=10)[8] if len(values) >= 10 else max(values),
                min_val=min(values),
                max_val=max(values),
                sample_count=len(values)
            )
            stats.append(stat)

        return stats

    def _format_threshold_stats(self, stats: List[ThresholdStats]) -> str:
        """Format threshold stats for display"""
        if not stats:
            return ""

        lines = [
            "📐 THRESHOLDS vs REALITY (Top Blockers)",
            "-" * 80,
        ]

        for stat in stats:
            lines.append(str(stat))
            lines.append("")

        lines.append("-" * 80)
        return "\n".join(lines)

    def _calculate_symbol_stats(
        self,
        events: List[dict],
        top_n: int
    ) -> List[SymbolRejectionStats]:
        """Calculate per-symbol rejection statistics"""
        # Count per symbol
        symbol_denied = Counter()
        symbol_total = Counter()
        symbol_reasons = defaultdict(Counter)
        symbol_stages = defaultdict(Counter)

        for event in events:
            event_type = event.get('event_type')
            symbol = event.get('symbol')

            if not symbol or event_type not in ('gate_denied', 'gate_passed'):
                continue

            symbol_total[symbol] += 1

            if event_type == 'gate_denied':
                symbol_denied[symbol] += 1
                reason = event.get('reason_code', 'UNKNOWN')
                stage = event.get('stage', 'UNKNOWN')
                symbol_reasons[symbol][reason] += 1
                symbol_stages[symbol][stage] += 1

        # Build stats
        stats = []
        for symbol, denied_count in symbol_denied.most_common(top_n):
            total = symbol_total[symbol]
            denial_rate = (denied_count / total * 100) if total > 0 else 0

            # Get top reason and stage
            top_reason = symbol_reasons[symbol].most_common(1)[0][0] if symbol_reasons[symbol] else "UNKNOWN"
            top_stage = symbol_stages[symbol].most_common(1)[0][0] if symbol_stages[symbol] else "UNKNOWN"

            stat = SymbolRejectionStats(
                symbol=symbol,
                total_denied=denied_count,
                total_evaluated=total,
                denial_rate=denial_rate,
                top_reason=top_reason,
                top_stage=top_stage,
                reason_counts=dict(symbol_reasons[symbol])
            )
            stats.append(stat)

        return stats

    def _format_symbol_stats(self, stats: List[SymbolRejectionStats]) -> str:
        """Format symbol stats for display"""
        if not stats:
            return ""

        lines = [
            "🎯 TOP REJECTED SYMBOLS (\"Log Vampires\")",
            "-" * 80,
        ]

        for idx, stat in enumerate(stats, 1):
            vampire_marker = "🧛" if stat.denial_rate > 95 else ""
            lines.append(
                f"  {idx}. {stat.symbol:15s}  "
                f"{stat.total_denied:4d}/{stat.total_evaluated:4d} rejected "
                f"({stat.denial_rate:5.1f}%)  {vampire_marker}"
            )
            lines.append(
                f"     Top reason: {stat.top_reason} [{stat.top_stage}]"
            )

        lines.append("-" * 80)
        return "\n".join(lines)

    def _calculate_regime_breakdown(
        self,
        events: List[dict],
        top_n: int
    ) -> List[RegimeBreakdown]:
        """Calculate rejection breakdown per regime (if available)"""
        # Check if any events have regime metadata
        has_regime = any(
            'regime' in event.get('metadata', {})
            for event in events
            if event.get('event_type') in ('gate_denied', 'gate_passed')
        )

        if not has_regime:
            return []

        # Group by regime
        regime_data = defaultdict(lambda: {
            'total': 0,
            'denied': 0,
            'reasons': Counter()
        })

        for event in events:
            if event.get('event_type') not in ('gate_denied', 'gate_passed'):
                continue

            metadata = event.get('metadata', {})
            regime = metadata.get('regime', 'UNKNOWN')

            regime_data[regime]['total'] += 1

            if event.get('event_type') == 'gate_denied':
                regime_data[regime]['denied'] += 1
                reason = event.get('reason_code', 'UNKNOWN')
                regime_data[regime]['reasons'][reason] += 1

        # Build breakdown
        breakdowns = []
        for regime, data in regime_data.items():
            # Get top reasons for this regime
            top_reasons = []
            total_denied = data['denied']
            for reason, count in data['reasons'].most_common(top_n):
                pct = (count / total_denied * 100) if total_denied > 0 else 0
                top_reasons.append((reason, count, pct))

            breakdown = RegimeBreakdown(
                regime=regime,
                total_intents=data['total'],
                denied=data['denied'],
                top_reasons=top_reasons
            )
            breakdowns.append(breakdown)

        return sorted(breakdowns, key=lambda x: x.denied, reverse=True)

    def _format_regime_breakdown(self, breakdowns: List[RegimeBreakdown]) -> str:
        """Format regime breakdown for display"""
        if not breakdowns:
            return ""

        lines = [
            "🌡️  REGIME BREAKDOWN (Experimental)",
            "-" * 80,
        ]

        for breakdown in breakdowns:
            denial_rate = (breakdown.denied / breakdown.total_intents * 100) if breakdown.total_intents > 0 else 0
            lines.append(f"\n{breakdown.regime}:")
            lines.append(f"  Intents: {breakdown.total_intents}, Denied: {breakdown.denied} ({denial_rate:.1f}%)")

            if breakdown.top_reasons:
                lines.append("  Top reasons:")
                for reason, count, pct in breakdown.top_reasons[:5]:
                    lines.append(f"    - {reason}: {count} ({pct:.1f}%)")

        lines.append("")
        lines.append("-" * 80)
        return "\n".join(lines)
