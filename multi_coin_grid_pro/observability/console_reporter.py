"""
Console Reporter for "Why No Trade?" summaries.

Phase 4: US-E3 "Why No Trade?" Summary Report
Phase 4.1: US-E3.x "Why No Trade?" v2 - Operator Grade
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from multi_coin_grid_pro.observability.event_aggregator import EventAggregator, PeriodSummary
from multi_coin_grid_pro.observability.why_no_trade_v2 import WhyNoTradeV2


class ConsoleReporter:
    """Reports aggregated event statistics to console and dedicated report log"""

    def __init__(
        self,
        log_dir: Path,
        logger: Optional[logging.Logger] = None,
        bot_name: str = "bot",
        config: Optional[dict] = None
    ):
        """
        Initialize console reporter.

        Args:
            log_dir: Directory containing events_*.jsonl files
            logger: Logger instance (defaults to module logger)
            bot_name: Name of the bot/strategy for report filename
            config: Bot configuration for threshold values
        """
        self.aggregator = EventAggregator(log_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.bot_name = bot_name
        self.config = config or {}

        # Setup dedicated report logger
        self.report_logger = self._setup_report_logger(log_dir)

        # Initialize v2 analyzer
        self.v2_analyzer = WhyNoTradeV2(log_dir, config=self.config)

    def _setup_report_logger(self, log_dir: Path) -> logging.Logger:
        """Setup dedicated logger for reports with separate file"""
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create report logger with bot-specific name
        logger_name = f'bot_reports_{self.bot_name}'
        report_logger = logging.getLogger(logger_name)
        report_logger.setLevel(logging.INFO)
        report_logger.propagate = False  # Don't propagate to root logger

        # Remove existing handlers
        report_logger.handlers.clear()

        # File handler for dedicated report log (per bot)
        timestamp = datetime.now().strftime('%Y%m%d')
        report_file = log_dir.parent / f'{self.bot_name}_report_{timestamp}.log'
        file_handler = logging.FileHandler(report_file, mode='a')
        file_handler.setLevel(logging.INFO)

        # Simple format for reports
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(formatter)
        report_logger.addHandler(file_handler)

        return report_logger

    def _log(self, message: str):
        """Log to both console logger and dedicated report file"""
        self.logger.info(message)
        self.report_logger.info(message)

    def report_last_hour(self):
        """Report statistics for the last hour"""
        summaries = self.aggregator.aggregate_hourly(hours=1)

        if not summaries:
            self._log("[WHY-NO-TRADE] No data available for last hour")
            return

        summary = summaries[0]
        self._print_summary(summary)

    def report_last_n_hours(self, hours: int = 24):
        """
        Report statistics for the last N hours.

        Args:
            hours: Number of hours to report
        """
        summaries = self.aggregator.aggregate_hourly(hours=hours)

        if not summaries:
            self._log(f"[WHY-NO-TRADE] No data available for last {hours} hours")
            return

        # Print each hour summary
        for summary in summaries:
            if summary.total_intents > 0:  # Only print hours with activity
                self._print_summary(summary)

    def report_summary(self, hours: int = 24):
        """
        Report high-level summary for the last N hours.

        Args:
            hours: Number of hours to summarize
        """
        stats = self.aggregator.get_summary_stats(hours=hours)

        self._log("\n" + "=" * 70)
        self._log(f"[WHY-NO-TRADE SUMMARY] Last {hours} hours")
        self._log("=" * 70)
        self._log(f"Total intents evaluated: {stats['total_intents']}")
        self._log(f"Denied: {stats['total_denied']} ({stats['denial_rate']:.1f}%)")
        self._log(f"Approved: {stats['total_approved']} ({100 - stats['denial_rate']:.1f}%)")

        if stats['top_rejection_reasons']:
            self._log("\nTop Rejection Reasons:")
            for idx, reason in enumerate(stats['top_rejection_reasons'], 1):
                self._log(
                    f"  {idx}. {reason['reason_code']}: "
                    f"{reason['count']} ({reason['percentage']:.1f}%) "
                    f"[{reason['stage']}]"
                )

        # Show missed opportunities from SLOT_FULL
        missed_opps = self.aggregator.get_missed_opportunities(hours=hours, top_n=10)
        if missed_opps:
            self._log("\n🚫 Top Missed Opportunities (SLOT_FULL):")
            for idx, opp in enumerate(missed_opps, 1):
                self._log(
                    f"   {idx}. {opp['symbol']:15s} {opp['count']:4d} times"
                )

        self._log("=" * 70 + "\n")

    def report_by_stage(self, hours: int = 24):
        """
        Report rejections grouped by stage.

        Args:
            hours: Number of hours to analyze
        """
        summaries = self.aggregator.aggregate_hourly(hours=hours)

        # Aggregate rejections by stage
        stage_totals = {}
        total_intents = 0

        for summary in summaries:
            total_intents += summary.total_intents
            for stage, count in summary.rejections_by_stage.items():
                stage_totals[stage] = stage_totals.get(stage, 0) + count

        if not stage_totals:
            self._log(f"[WHY-NO-TRADE] No rejections in last {hours} hours")
            return

        self._log("\n" + "=" * 70)
        self._log(f"[REJECTIONS BY STAGE] Last {hours} hours")
        self._log("=" * 70)

        # Sort stages by rejection count
        sorted_stages = sorted(stage_totals.items(), key=lambda x: x[1], reverse=True)

        for stage, count in sorted_stages:
            percentage = (count / total_intents * 100) if total_intents > 0 else 0
            self._log(f"  {stage}: {count} ({percentage:.1f}%)")

        self._log("=" * 70 + "\n")

    def report_by_symbol(self, hours: int = 24, top_n: int = 10):
        """
        Report top symbols with rejections.

        Args:
            hours: Number of hours to analyze
            top_n: Number of top symbols to show
        """
        summaries = self.aggregator.aggregate_hourly(hours=hours)

        # Aggregate rejections by symbol
        symbol_totals = {}

        for summary in summaries:
            for symbol, count in summary.rejections_by_symbol.items():
                symbol_totals[symbol] = symbol_totals.get(symbol, 0) + count

        if not symbol_totals:
            self._log(f"[WHY-NO-TRADE] No rejections in last {hours} hours")
            return

        self._log("\n" + "=" * 70)
        self._log(f"[TOP {top_n} REJECTED SYMBOLS] Last {hours} hours")
        self._log("=" * 70)

        # Sort symbols by rejection count
        sorted_symbols = sorted(symbol_totals.items(), key=lambda x: x[1], reverse=True)

        for idx, (symbol, count) in enumerate(sorted_symbols[:top_n], 1):
            self._log(f"  {idx}. {symbol}: {count} rejections")

        self._log("=" * 70 + "\n")

    def report_full_dashboard(self, hours: int = 24):
        """
        Print comprehensive dashboard with all statistics.

        Args:
            hours: Number of hours to analyze
        """
        self.report_summary(hours=hours)
        self.report_by_stage(hours=hours)
        self.report_by_symbol(hours=hours)

    def report_v2(self, window_minutes: int = 60, top_n_reasons: int = 10, top_n_symbols: int = 5):
        """
        Generate operator-grade Why-No-Trade report v2.

        Args:
            window_minutes: Analysis window (default 60 minutes)
            top_n_reasons: Number of top reasons to show
            top_n_symbols: Number of top symbols to show
        """
        try:
            report = self.v2_analyzer.analyze(
                window_minutes=window_minutes,
                top_n_reasons=top_n_reasons,
                top_n_symbols=top_n_symbols
            )

            # Log to both console and dedicated file
            for line in report.split('\n'):
                self._log(line)

        except Exception as e:
            self.logger.error(f"Error generating Why-No-Trade v2 report: {e}")
            self._log(f"[ERROR] Failed to generate v2 report: {e}")

    def _print_summary(self, summary: PeriodSummary):
        """
        Print a single period summary to console.

        Args:
            summary: PeriodSummary to print
        """
        self._log(str(summary))
