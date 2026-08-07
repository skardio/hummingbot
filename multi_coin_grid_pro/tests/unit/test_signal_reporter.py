# test_signal_reporter.py — unit tests for momentum_signal_reporter.py
import logging

from multi_coin_grid_pro.reporters.momentum_signal_reporter import (
    DISCLAIMER,
    SignalReporter,
    _fmt_pct,
    _fmt_price,
    _fmt_vol,
)
from multi_coin_grid_pro.signals.momentum_models import MomentumSignal, ScanResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_signal(
    trading_pair: str = "BTC-USD",
    exchange: str = "kraken",
    accepted: bool = True,
    rank: int = 1,
    score: float = 0.82,
    price: float = 30000.0,
    spread_pct: float = 0.007,
    price_change_5m_pct: float = 3.1,
    price_change_15m_pct: float = 5.2,
    volume_ratio: float = 4.2,
    rejection_reason: str = None,
) -> MomentumSignal:
    return MomentumSignal(
        scan_id="scan-001",
        timestamp=1_748_000_000.0,
        exchange=exchange,
        trading_pair=trading_pair,
        price=price,
        spread_pct=spread_pct,
        price_change_5m_pct=price_change_5m_pct,
        price_change_15m_pct=price_change_15m_pct,
        volume_ratio=volume_ratio,
        score=score,
        accepted=accepted,
        rank=rank if accepted else None,
        rejection_reason=rejection_reason,
        all_reasons=[rejection_reason] if rejection_reason else [],
    )


def make_scan(signals=None) -> ScanResult:
    return ScanResult(
        scan_id="scan-001",
        timestamp=1_748_000_000.0,
        scan_duration_seconds=2.3,
        signals=signals or [],
    )


def reporter() -> SignalReporter:
    return SignalReporter()


# ---------------------------------------------------------------------------
# Pure formatting helpers
# ---------------------------------------------------------------------------

class TestFmtPct:

    def test_positive(self) -> None:
        assert "+3.1%" in _fmt_pct(3.1)

    def test_negative(self) -> None:
        result = _fmt_pct(-1.5)
        assert "-1.5%" in result
        assert "+" not in result

    def test_zero(self) -> None:
        assert "+0.0%" in _fmt_pct(0.0)

    def test_none(self) -> None:
        assert "n/a" in _fmt_pct(None)


class TestFmtVol:

    def test_normal(self) -> None:
        assert "4.2x" in _fmt_vol(4.2)

    def test_none(self) -> None:
        assert "n/a" in _fmt_vol(None)


class TestFmtPrice:

    def test_large_price(self) -> None:
        result = _fmt_price(30000.0)
        assert "30,000.00" in result

    def test_medium_price(self) -> None:
        result = _fmt_price(2.5)
        assert "2.5000" in result

    def test_small_price(self) -> None:
        result = _fmt_price(0.000123)
        assert "0.000123" in result


# ---------------------------------------------------------------------------
# SignalReporter.format_scan
# ---------------------------------------------------------------------------

class TestSignalReporterFormat:

    def test_disclaimer_present(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert DISCLAIMER in out

    def test_scan_id_present(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert "scan-001" in out

    def test_duration_present(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert "2.3s" in out

    def test_totals_present(self) -> None:
        signals = [
            make_signal(rank=1),
            make_signal(trading_pair="ETH-USD", rank=2),
            make_signal(trading_pair="SOL-USD", accepted=False, rejection_reason="SCORE_TOO_LOW"),
        ]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "3" in out   # total scanned
        assert "2" in out   # accepted
        assert "1" in out   # rejected

    def test_top_signal_trading_pair_present(self) -> None:
        signals = [make_signal(trading_pair="BTC-USD", rank=1)]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "BTC-USD" in out

    def test_top_signal_exchange_present(self) -> None:
        signals = [make_signal(exchange="okx", rank=1)]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "okx" in out

    def test_top_signal_score_present(self) -> None:
        signals = [make_signal(score=0.82, rank=1)]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "0.82" in out

    def test_signal_price_change_present(self) -> None:
        signals = [make_signal(price_change_5m_pct=3.1, rank=1)]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "+3.1%" in out

    def test_signal_volume_ratio_present(self) -> None:
        signals = [make_signal(volume_ratio=4.2, rank=1)]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "4.2x" in out

    def test_signals_sorted_by_rank(self) -> None:
        signals = [
            make_signal(trading_pair="ETH-USD", rank=2, score=0.77),
            make_signal(trading_pair="BTC-USD", rank=1, score=0.85),
        ]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        # BTC (rank 1) should appear before ETH (rank 2)
        assert out.index("BTC-USD") < out.index("ETH-USD")

    def test_no_accepted_signals_message(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan([]))
        assert "geen" in out.lower()

    def test_rejection_breakdown_shown(self) -> None:
        signals = [
            make_signal(accepted=False, rejection_reason="SCORE_TOO_LOW",
                        trading_pair="C1-USD"),
            make_signal(accepted=False, rejection_reason="SCORE_TOO_LOW",
                        trading_pair="C2-USD"),
            make_signal(accepted=False, rejection_reason="SPREAD_TOO_HIGH",
                        trading_pair="C3-USD"),
        ]
        r = reporter()
        out = r.format_scan(make_scan(signals))
        assert "SCORE_TOO_LOW=2" in out
        assert "SPREAD_TOO_HIGH=1" in out

    def test_none_price_changes_show_na(self) -> None:
        sig = make_signal()
        sig.price_change_5m_pct = None
        sig.price_change_15m_pct = None
        r = reporter()
        out = r.format_scan(make_scan([sig]))
        assert "n/a" in out

    def test_none_volume_ratio_shows_na(self) -> None:
        sig = make_signal()
        sig.volume_ratio = None
        r = reporter()
        out = r.format_scan(make_scan([sig]))
        assert "n/a" in out

    def test_returns_string(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert isinstance(out, str)

    def test_multiple_lines(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert out.count("\n") >= 5

    def test_negative_price_change_no_plus_sign(self) -> None:
        sig = make_signal(price_change_5m_pct=-2.0)
        r = reporter()
        out = r.format_scan(make_scan([sig]))
        assert "-2.0%" in out

    def test_column_header_present(self) -> None:
        r = reporter()
        out = r.format_scan(make_scan())
        assert "Score" in out
        assert "Spread" in out


# ---------------------------------------------------------------------------
# SignalReporter.log_scan
# ---------------------------------------------------------------------------

class TestSignalReporterLogScan:

    def test_log_scan_uses_provided_logger(self) -> None:
        mock_log = logging.getLogger("test_reporter")
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        mock_log.addHandler(handler)
        mock_log.setLevel(logging.INFO)

        reporter().log_scan(make_scan([make_signal()]), log=mock_log)

        mock_log.removeHandler(handler)
        combined = "\n".join(records)
        assert DISCLAIMER in combined
        assert "scan-001" in combined

    def test_log_scan_produces_multiple_records(self) -> None:
        mock_log = logging.getLogger("test_reporter_multi")
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        mock_log.addHandler(handler)
        mock_log.setLevel(logging.INFO)

        reporter().log_scan(make_scan([make_signal()]), log=mock_log)
        mock_log.removeHandler(handler)

        assert len(records) >= 5

    def test_log_scan_without_logger_does_not_raise(self) -> None:
        # Should fall back to module logger without raising
        reporter().log_scan(make_scan())


# ---------------------------------------------------------------------------
# Sample mode — coverage report + rejected sections
# ---------------------------------------------------------------------------

from multi_coin_grid_pro.reporters.momentum_signal_reporter import (  # noqa: E402
    _fmt_missing_data_sample,
    _fmt_top_rejected_enriched,
)
from multi_coin_grid_pro.signals.momentum_models import (  # noqa: E402
    DataCoverageReport,
    ExchangeCoverageStats,
    ScanResult,
)


def _make_coverage(
    *,
    sample_mode: bool = False,
    enriched_total: int = 75,
    enriched_complete: int = 70,
    enriched_incomplete: int = 5,
    blind_warning: bool = False,
) -> DataCoverageReport:
    stats = ExchangeCoverageStats(
        exchange="kraken",
        pairs_total=659,
        tickers_ok=659,
        orderbook_ok=25,
        candles_5m_ok=25,
        candles_15m_ok=25,
        volume_ratio_ok=23,
        momentum_data_complete=23,
        missing_momentum_data=636,
    )
    return DataCoverageReport(
        by_exchange=[stats],
        blind_warning=blind_warning,
        sample_mode=sample_mode,
        enriched_total=enriched_total,
        enriched_complete=enriched_complete,
        enriched_incomplete=enriched_incomplete,
    )


def _make_enriched_signal(
    trading_pair: str = "SOL-USDT",
    score: float = 0.45,
    rejection_reason: str = "MOMENTUM_TOO_LOW",
) -> MomentumSignal:
    """Rejected signal with complete momentum data."""
    return MomentumSignal(
        scan_id="s1",
        timestamp=1_748_000_000.0,
        exchange="kraken",
        trading_pair=trading_pair,
        price=100.0,
        spread_pct=0.05,
        price_change_5m_pct=1.2,
        price_change_15m_pct=2.3,
        volume_ratio=2.1,
        score=score,
        accepted=False,
        rejection_reason=rejection_reason,
    )


def _make_na_signal(trading_pair: str = "ZZZ-USDT") -> MomentumSignal:
    """Rejected signal with missing momentum data (n/a)."""
    return MomentumSignal(
        scan_id="s1",
        timestamp=1_748_000_000.0,
        exchange="kraken",
        trading_pair=trading_pair,
        price=1.0,
        spread_pct=0.05,
        price_change_5m_pct=None,
        price_change_15m_pct=None,
        volume_ratio=None,
        score=0.0,
        accepted=False,
        rejection_reason="MISSING_PRICE_CHANGE_5M",
    )


class TestCoverageReportSampleMode:

    def test_sample_mode_shows_sample_mode_label(self) -> None:
        from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_coverage
        cov = _make_coverage(sample_mode=True)
        out = _fmt_coverage(cov)
        assert "SAMPLE MODE" in out

    def test_sample_mode_shows_enriched_count(self) -> None:
        from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_coverage
        cov = _make_coverage(sample_mode=True, enriched_total=75, enriched_complete=70)
        out = _fmt_coverage(cov)
        assert "75" in out
        assert "70" in out

    def test_sample_mode_no_global_blind_warning(self) -> None:
        from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_coverage

        # blind_warning is False (as expected when enriched data is fine)
        cov = _make_coverage(sample_mode=True, blind_warning=False)
        out = _fmt_coverage(cov)
        assert "Scanner may be blind" not in out

    def test_non_sample_mode_blind_warning_shows(self) -> None:
        from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_coverage
        cov = _make_coverage(sample_mode=False, blind_warning=True)
        out = _fmt_coverage(cov)
        assert "Scanner may be blind" in out

    def test_sample_mode_enriched_blind_warning_shows_enriched_text(self) -> None:
        from multi_coin_grid_pro.reporters.momentum_signal_reporter import _fmt_coverage
        cov = _make_coverage(sample_mode=True, blind_warning=True, enriched_incomplete=20, enriched_total=25)
        out = _fmt_coverage(cov)
        assert "enriched pairs are incomplete" in out
        assert "Scanner may be blind" not in out


class TestTopRejectedEnrichedSection:

    def test_enriched_section_contains_complete_pairs(self) -> None:
        sig = _make_enriched_signal("SOL-USDT", score=0.45)
        out = _fmt_top_rejected_enriched([sig])
        assert "SOL-USDT" in out
        assert "+1.2%" in out
        assert "2.1x" in out

    def test_enriched_section_header_indicates_enriched(self) -> None:
        sig = _make_enriched_signal()
        out = _fmt_top_rejected_enriched([sig])
        assert "ENRICHED" in out

    def test_enriched_section_empty_returns_empty_string(self) -> None:
        assert _fmt_top_rejected_enriched([]) == ""

    def test_enriched_section_no_na_metrics(self) -> None:
        """Signals in enriched section must show numeric Δ5m, Δ15m and VolR (no n/a there)."""
        sigs = [_make_enriched_signal(f"C{i}-USDT") for i in range(3)]
        out = _fmt_top_rejected_enriched(sigs)
        lines = [line for line in out.splitlines() if "-USDT" in line]
        assert len(lines) == 3
        for line in lines:
            assert "+1.2%" in line    # Δ5m present
            assert "+2.3%" in line    # Δ15m present
            assert "2.1x" in line     # VolR present


class TestMissingDataSampleSection:

    def test_missing_sample_shows_na(self) -> None:
        sig = _make_na_signal("OBSCURE-USDT")
        out = _fmt_missing_data_sample([sig])
        assert "OBSCURE-USDT" in out
        assert "n/a" in out

    def test_missing_sample_header_indicates_debug(self) -> None:
        sig = _make_na_signal()
        out = _fmt_missing_data_sample([sig])
        assert "MISSING DATA SAMPLE" in out

    def test_missing_sample_empty_returns_empty_string(self) -> None:
        assert _fmt_missing_data_sample([]) == ""

    def test_format_scan_shows_both_sections(self) -> None:
        enriched_sig = _make_enriched_signal()
        na_sig = _make_na_signal()
        scan = ScanResult(
            scan_id="s1",
            timestamp=1_748_000_000.0,
            scan_duration_seconds=1.0,
            signals=[enriched_sig, na_sig],
            top_rejected=[enriched_sig],
            missing_data_sample=[na_sig],
        )
        out = reporter().format_scan(scan)
        assert "ENRICHED" in out
        assert "MISSING DATA SAMPLE" in out
