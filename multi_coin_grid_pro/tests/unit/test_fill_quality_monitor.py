"""
Unit tests for FillQualityMonitor.

Item 15 — Fill Quality / Slippage Monitor
"""
import pytest

from multi_coin_grid_pro.core.fill_quality_monitor import FillQualityMonitor, FillRecord

TS = 1_700_000_000.0


def make_monitor(max_records: int = 500) -> FillQualityMonitor:
    return FillQualityMonitor(max_records=max_records)


class TestFillRecord:
    def test_buy_slippage_positive_when_paid_more(self):
        rec = FillRecord(
            symbol="BTC-EUR",
            expected_price=100.0,
            actual_price=101.0,
            side="buy",
            size_quote=50.0,
            timestamp=TS,
        )
        assert rec.slippage_pct == pytest.approx(1.0)

    def test_sell_slippage_positive_when_received_less(self):
        rec = FillRecord(
            symbol="BTC-EUR",
            expected_price=100.0,
            actual_price=99.0,
            side="sell",
            size_quote=50.0,
            timestamp=TS,
        )
        assert rec.slippage_pct == pytest.approx(1.0)

    def test_perfect_fill_zero_slippage(self):
        rec = FillRecord("ETH-EUR", 200.0, 200.0, "buy", 100.0, TS)
        assert rec.slippage_pct == pytest.approx(0.0)

    def test_zero_expected_price_returns_zero(self):
        rec = FillRecord("BTC-EUR", 0.0, 50.0, "buy", 10.0, TS)
        assert rec.slippage_pct == pytest.approx(0.0)


class TestRecordFill:
    def test_record_fill_returns_fill_record(self):
        mon = make_monitor()
        rec = mon.record_fill(
            symbol="BTC-EUR", expected_price=100.0, actual_price=100.5,
            side="buy", size_quote=50.0, timestamp=TS,
        )
        assert isinstance(rec, FillRecord)
        assert rec.slippage_pct == pytest.approx(0.5)

    def test_records_accumulate(self):
        mon = make_monitor()
        for _ in range(10):
            mon.record_fill(
                symbol="BTC-EUR", expected_price=100.0, actual_price=100.0,
                side="buy", size_quote=10.0, timestamp=TS,
            )
        assert mon.summary()["total_fills"] == 10

    def test_circular_buffer_respects_max(self):
        mon = make_monitor(max_records=5)
        for i in range(10):
            mon.record_fill(
                symbol="BTC-EUR", expected_price=100.0, actual_price=100.0,
                side="buy", size_quote=10.0, timestamp=TS + i,
            )
        assert mon.summary()["total_fills"] == 5


class TestAvgSlippage:
    def test_avg_slippage_all_fills(self):
        mon = make_monitor()
        mon.record_fill(symbol="BTC-EUR", expected_price=100.0, actual_price=101.0,
                        side="buy", size_quote=50.0, timestamp=TS)      # 1%
        mon.record_fill(symbol="BTC-EUR", expected_price=100.0, actual_price=100.0,
                        side="buy", size_quote=50.0, timestamp=TS + 1)  # 0%
        assert mon.avg_slippage_pct() == pytest.approx(0.5)

    def test_avg_slippage_filtered_by_symbol(self):
        mon = make_monitor()
        mon.record_fill(symbol="BTC-EUR", expected_price=100.0, actual_price=102.0,
                        side="buy", size_quote=50.0, timestamp=TS)  # 2%
        mon.record_fill(symbol="ETH-EUR", expected_price=50.0, actual_price=50.0,
                        side="buy", size_quote=50.0, timestamp=TS + 1)   # 0%
        assert mon.avg_slippage_pct(symbol="BTC-EUR") == pytest.approx(2.0)
        assert mon.avg_slippage_pct(symbol="ETH-EUR") == pytest.approx(0.0)

    def test_empty_returns_zero(self):
        mon = make_monitor()
        assert mon.avg_slippage_pct() == 0.0


class TestWorstSlippage:
    def test_worst_slippage_picks_max(self):
        mon = make_monitor()
        mon.record_fill(symbol="BTC-EUR", expected_price=100.0, actual_price=101.0,
                        side="buy", size_quote=50.0, timestamp=TS)      # 1%
        mon.record_fill(symbol="BTC-EUR", expected_price=100.0, actual_price=103.0,
                        side="buy", size_quote=50.0, timestamp=TS + 1)  # 3%
        assert mon.worst_slippage_pct() == pytest.approx(3.0)

    def test_worst_slippage_empty_returns_zero(self):
        mon = make_monitor()
        assert mon.worst_slippage_pct() == 0.0


class TestSummary:
    def test_summary_keys(self):
        mon = make_monitor()
        s = mon.summary()
        assert "total_fills" in s
        assert "avg_slippage_pct" in s
        assert "worst_slippage_pct" in s

    def test_summary_empty(self):
        mon = make_monitor()
        s = mon.summary()
        assert s["total_fills"] == 0
        assert s["avg_slippage_pct"] == 0.0
        assert s["worst_slippage_pct"] == 0.0
