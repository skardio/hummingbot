"""
Event Aggregator for analyzing rejection reasons from JSONL event logs.

Phase 4: US-E3 "Why No Trade?" Summary Report
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AggregationPeriod:
    """Time period for aggregation"""
    start_time: datetime
    end_time: datetime

    def __str__(self):
        return f"{self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')}"


@dataclass
class RejectionStats:
    """Statistics for a specific rejection reason"""
    reason_code: str
    stage: str
    count: int
    percentage: float

    def __str__(self):
        return f"{self.reason_code}: {self.count} ({self.percentage:.1f}%)"


@dataclass
class PeriodSummary:
    """Summary statistics for a time period"""
    period: AggregationPeriod
    total_intents: int
    denied: int
    approved: int
    denial_rate: float
    top_rejections: List[RejectionStats]
    rejections_by_stage: Dict[str, int]
    rejections_by_symbol: Dict[str, int]

    def __str__(self):
        lines = [
            f"\n[WHY-NO-TRADE] {self.period}",
            f"  Total intents evaluated: {self.total_intents}",
            f"  Denied: {self.denied} ({self.denial_rate:.1f}%)",
        ]

        for rejection in self.top_rejections[:10]:  # Top 10
            lines.append(f"    - {rejection.reason_code}: {rejection.count} ({rejection.percentage:.1f}%) [{rejection.stage}]")

        if self.total_intents > 0:
            lines.append(f"  Approved: {self.approved} ({100 - self.denial_rate:.1f}%)")

        return "\n".join(lines)


class EventAggregator:
    """Aggregates and analyzes events from JSONL logs"""

    def __init__(self, log_dir: Path):
        """
        Initialize aggregator.

        Args:
            log_dir: Directory containing events_*.jsonl files
        """
        self.log_dir = Path(log_dir)

    def read_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[dict]:
        """
        Read events from JSONL files within time range.

        Args:
            start_time: Filter events after this time (inclusive)
            end_time: Filter events before this time (exclusive)

        Returns:
            List of event dictionaries
        """
        events = []

        # Find all JSONL files
        jsonl_files = sorted(self.log_dir.glob("events_*.jsonl"))

        for jsonl_file in jsonl_files:
            try:
                with open(jsonl_file, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue

                        event = json.loads(line)

                        # Apply time filters
                        if start_time or end_time:
                            # Handle both 'ts' (unix timestamp) and 'timestamp' (ISO format)
                            if 'ts' in event:
                                event_time = datetime.fromtimestamp(event['ts'])
                            elif 'timestamp' in event:
                                event_time = datetime.fromisoformat(event['timestamp'])
                            else:
                                # Skip events without timestamp
                                continue

                            if start_time and event_time < start_time:
                                continue
                            if end_time and event_time >= end_time:
                                continue

                        events.append(event)
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                # Skip corrupt/missing files
                continue

        return events

    def aggregate_hourly(
        self,
        date: Optional[datetime] = None,
        hours: int = 24
    ) -> List[PeriodSummary]:
        """
        Aggregate events by hour for the specified date.

        Args:
            date: Date to aggregate (defaults to today)
            hours: Number of hours to look back

        Returns:
            List of PeriodSummary objects, one per hour
        """
        if date is None:
            date = datetime.now()

        # Start from beginning of the day or X hours ago
        start_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if hours < 24:
            start_time = date - timedelta(hours=hours)

        summaries = []

        for hour_offset in range(hours):
            hour_start = start_time + timedelta(hours=hour_offset)
            hour_end = hour_start + timedelta(hours=1)

            period = AggregationPeriod(hour_start, hour_end)
            summary = self._aggregate_period(period)
            summaries.append(summary)

        return summaries

    def aggregate_daily(
        self,
        days: int = 7
    ) -> List[PeriodSummary]:
        """
        Aggregate events by day.

        Args:
            days: Number of days to look back

        Returns:
            List of PeriodSummary objects, one per day
        """
        summaries = []
        now = datetime.now()

        for day_offset in range(days):
            day_start = (now - timedelta(days=day_offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = day_start + timedelta(days=1)

            period = AggregationPeriod(day_start, day_end)
            summary = self._aggregate_period(period)
            summaries.append(summary)

        return summaries

    def _aggregate_period(self, period: AggregationPeriod) -> PeriodSummary:
        """
        Aggregate events for a specific time period.

        Args:
            period: Time period to aggregate

        Returns:
            PeriodSummary with statistics
        """
        events = self.read_events(period.start_time, period.end_time)

        # Count events by type
        total_intents = len(events)
        denied = sum(1 for e in events if e.get('event_type') == 'gate_denied')
        approved = sum(1 for e in events if e.get('event_type') == 'gate_passed')

        # Count rejections by reason code
        rejection_counts = Counter()
        rejection_stages = {}
        rejections_by_stage = defaultdict(int)
        rejections_by_symbol = defaultdict(int)

        for event in events:
            if event.get('event_type') != 'gate_denied':
                continue

            reason_code = event.get('reason_code', 'UNKNOWN')
            stage = event.get('stage', 'UNKNOWN')
            symbol = event.get('symbol', 'UNKNOWN')

            rejection_counts[reason_code] += 1
            rejection_stages[reason_code] = stage
            rejections_by_stage[stage] += 1
            rejections_by_symbol[symbol] += 1

        # Calculate percentages and create RejectionStats
        top_rejections = []
        for reason_code, count in rejection_counts.most_common():
            percentage = (count / total_intents * 100) if total_intents > 0 else 0
            stage = rejection_stages.get(reason_code, 'UNKNOWN')

            top_rejections.append(RejectionStats(
                reason_code=reason_code,
                stage=stage,
                count=count,
                percentage=percentage
            ))

        denial_rate = (denied / total_intents * 100) if total_intents > 0 else 0

        return PeriodSummary(
            period=period,
            total_intents=total_intents,
            denied=denied,
            approved=approved,
            denial_rate=denial_rate,
            top_rejections=top_rejections,
            rejections_by_stage=dict(rejections_by_stage),
            rejections_by_symbol=dict(rejections_by_symbol)
        )

    def get_summary_stats(
        self,
        hours: int = 24
    ) -> Dict[str, any]:
        """
        Get high-level summary statistics.

        Args:
            hours: Number of hours to look back

        Returns:
            Dictionary with summary statistics
        """
        summaries = self.aggregate_hourly(hours=hours)

        # Aggregate across all periods
        total_intents = sum(s.total_intents for s in summaries)
        total_denied = sum(s.denied for s in summaries)
        total_approved = sum(s.approved for s in summaries)

        # Combine all rejections
        all_rejections = Counter()
        all_stages = {}

        for summary in summaries:
            for rejection in summary.top_rejections:
                all_rejections[rejection.reason_code] += rejection.count
                all_stages[rejection.reason_code] = rejection.stage

        # Top 10 rejection reasons across all periods
        top_reasons = []
        for reason_code, count in all_rejections.most_common(10):
            percentage = (count / total_intents * 100) if total_intents > 0 else 0
            top_reasons.append({
                'reason_code': reason_code,
                'stage': all_stages.get(reason_code, 'UNKNOWN'),
                'count': count,
                'percentage': percentage
            })

        return {
            'period_hours': hours,
            'total_intents': total_intents,
            'total_denied': total_denied,
            'total_approved': total_approved,
            'denial_rate': (total_denied / total_intents * 100) if total_intents > 0 else 0,
            'top_rejection_reasons': top_reasons
        }

    def get_missed_opportunities(
        self,
        hours: int = 24,
        top_n: int = 10
    ) -> List[Dict[str, any]]:
        """
        Get top missed trading opportunities from SLOT_FULL events.

        Args:
            hours: Number of hours to look back
            top_n: Number of top symbols to return

        Returns:
            List of dicts with symbol and count
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        events = self.read_events(start_time, end_time)

        # Count missed candidates from SLOT_FULL events
        missed_symbols = Counter()

        for event in events:
            if event.get('event_type') == 'gate_denied' and event.get('reason_code') == 'SLOT_FULL':
                # Check for direct symbol
                symbol = event.get('symbol')
                if symbol and symbol != 'N/A':
                    missed_symbols[symbol] += 1

                # Also extract from missed_candidates metadata
                metadata = event.get('metadata', {})
                candidates = metadata.get('missed_candidates', [])
                for candidate in candidates:
                    if candidate and candidate != 'N/A':
                        missed_symbols[candidate] += 1

        # Return top N
        result = []
        for symbol, count in missed_symbols.most_common(top_n):
            result.append({
                'symbol': symbol,
                'count': count
            })

        return result
