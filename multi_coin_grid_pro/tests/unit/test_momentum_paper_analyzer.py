"""
Unit tests for momentum_paper_analyzer.
"""

import pytest

from multi_coin_grid_pro.tools.momentum_paper_analyzer import (
    MatchedTrade,
    PaperEntry,
    PaperExit,
    analyze,
    format_report,
    match_trades,
    parse_lines,
)

# ---------------------------------------------------------------------------
# Sample log lines matching the exact logger.info format in
# MomentumSleeveManager (Python %-style formatting)
# ---------------------------------------------------------------------------

ENTRY_LINE = (
    "2026-05-25 10:00:00,123 INFO "
    "[MOMENTUM_PAPER_ENTRY] pair=SOL-USD score=82.5 entry=100.123456 "
    "sl=98.901810 tp=102.125925 trail_act=101.324927 size_quote=25.00 "
    "regime=BULL vol_exp=1.80"
)

EXIT_WIN_LINE = (
    "2026-05-25 11:05:00,456 INFO "
    "[MOMENTUM_PAPER_EXIT] pair=SOL-USD reason=TAKE_PROFIT "
    "entry=100.123456 exit=102.200000 pnl_quote=0.5213 pnl_pct=2.074% "
    "hold=3900s mfe=2.07% mae=0.30%"
)

EXIT_LOSS_LINE = (
    "2026-05-25 12:00:00,789 INFO "
    "[MOMENTUM_PAPER_EXIT] pair=ETH-USD reason=STOP_LOSS "
    "entry=2000.000000 exit=1975.000000 pnl_quote=-0.3125 pnl_pct=-1.250% "
    "hold=1800s mfe=0.50% mae=1.25%"
)

ENTRY_LINE_2 = (
    "2026-05-25 11:30:00,000 INFO "
    "[MOMENTUM_PAPER_ENTRY] pair=ETH-USD score=76.0 entry=2000.000000 "
    "sl=1976.000000 tp=2040.000000 trail_act=2024.000000 size_quote=25.00 "
    "regime=CHOP vol_exp=1.20"
)

TRAILING_EXIT_LINE = (
    "2026-05-25 13:00:00,000 INFO "
    "[MOMENTUM_PAPER_EXIT] pair=SOL-USD reason=TRAILING_STOP "
    "entry=100.123456 exit=101.500000 pnl_quote=0.3500 pnl_pct=1.375% "
    "hold=5400s mfe=2.10% mae=0.10%"
)

MAXHOLD_EXIT_LINE = (
    "2026-05-25 14:00:00,000 INFO "
    "[MOMENTUM_PAPER_EXIT] pair=SOL-USD reason=MAX_HOLD "
    "entry=100.123456 exit=99.800000 pnl_quote=-0.0820 pnl_pct=-0.323% "
    "hold=5400s mfe=0.80% mae=0.50%"
)

GARBAGE_LINE = "2026-05-25 10:00:00 INFO Some unrelated log line"
SUMMARY_LINE = (
    "2026-05-25 11:00:00 INFO [MOMENTUM_PAPER_SUMMARY] "
    "open=0(—) trades=1 win_rate=100.0% total_pnl=0.5213 avg_pnl=2.074% "
    "best=2.074% worst=2.074%"
)


# ---------------------------------------------------------------------------
# parse_lines tests
# ---------------------------------------------------------------------------

class TestParseLines:
    def test_parses_entry(self):
        entries, exits = parse_lines([ENTRY_LINE])
        assert len(entries) == 1
        e = entries[0]
        assert e.pair == "SOL-USD"
        assert e.score == pytest.approx(82.5)
        assert e.entry_price == pytest.approx(100.123456)
        assert e.regime == "BULL"
        assert e.vol_exp == pytest.approx(1.80)
        assert e.size_quote == pytest.approx(25.0)
        assert e.timestamp == "2026-05-25 10:00:00"

    def test_parses_exit_win(self):
        _, exits = parse_lines([EXIT_WIN_LINE])
        assert len(exits) == 1
        ex = exits[0]
        assert ex.pair == "SOL-USD"
        assert ex.exit_reason == "TAKE_PROFIT"
        assert ex.entry_price == pytest.approx(100.123456)
        assert ex.exit_price == pytest.approx(102.2)
        assert ex.pnl_quote == pytest.approx(0.5213)
        assert ex.pnl_pct == pytest.approx(2.074)
        assert ex.hold_sec == 3900
        assert ex.mfe_pct == pytest.approx(2.07)
        assert ex.mae_pct == pytest.approx(0.30)

    def test_parses_exit_loss(self):
        _, exits = parse_lines([EXIT_LOSS_LINE])
        assert len(exits) == 1
        ex = exits[0]
        assert ex.pnl_pct == pytest.approx(-1.250)
        assert ex.pnl_quote == pytest.approx(-0.3125)

    def test_garbage_lines_ignored(self):
        entries, exits = parse_lines([GARBAGE_LINE, SUMMARY_LINE])
        assert entries == []
        assert exits == []

    def test_mixed_lines(self):
        lines = [ENTRY_LINE, GARBAGE_LINE, EXIT_WIN_LINE, SUMMARY_LINE, ENTRY_LINE_2]
        entries, exits = parse_lines(lines)
        assert len(entries) == 2
        assert len(exits) == 1

    def test_negative_pnl_parsed(self):
        _, exits = parse_lines([EXIT_LOSS_LINE])
        assert exits[0].pnl_pct < 0


# ---------------------------------------------------------------------------
# match_trades tests
# ---------------------------------------------------------------------------

class TestMatchTrades:
    def _parse(self, lines):
        return parse_lines(lines)

    def test_basic_match(self):
        entries, exits = self._parse([ENTRY_LINE, EXIT_WIN_LINE])
        trades, unmatched = match_trades(entries, exits)
        assert len(trades) == 1
        assert unmatched == 0
        assert trades[0].entry.pair == "SOL-USD"
        assert trades[0].exit.exit_reason == "TAKE_PROFIT"

    def test_unmatched_exit_counted(self):
        # Exit without a corresponding entry
        _, exits = self._parse([EXIT_WIN_LINE])
        trades, unmatched = match_trades([], exits)
        assert trades == []
        assert unmatched == 1

    def test_open_position_not_counted(self):
        # Entry without exit = still open, not matched
        entries, _ = self._parse([ENTRY_LINE])
        trades, unmatched = match_trades(entries, [])
        assert trades == []
        assert unmatched == 0

    def test_fifo_matching_same_pair(self):
        # Two entries at same price, two exits → matched in order
        entries, exits = self._parse([
            ENTRY_LINE, ENTRY_LINE,
            EXIT_WIN_LINE, TRAILING_EXIT_LINE,
        ])
        trades, unmatched = match_trades(entries, exits)
        assert len(trades) == 2
        assert unmatched == 0
        assert trades[0].exit.exit_reason == "TAKE_PROFIT"
        assert trades[1].exit.exit_reason == "TRAILING_STOP"

    def test_two_different_pairs(self):
        entries, exits = self._parse([ENTRY_LINE, ENTRY_LINE_2, EXIT_WIN_LINE, EXIT_LOSS_LINE])
        trades, unmatched = match_trades(entries, exits)
        assert len(trades) == 2
        assert unmatched == 0


# ---------------------------------------------------------------------------
# analyze tests
# ---------------------------------------------------------------------------

class TestAnalyze:
    def _make_trade(self, pair="SOL-USD", regime="BULL", reason="TAKE_PROFIT",
                    pnl_pct=2.0, pnl_quote=0.5, hold_sec=3600,
                    score=80.0, mfe=2.0, mae=0.3):
        entry = PaperEntry("2026-05-25 10:00:00", pair, score, 100.0, regime, 1.5, 25.0)
        exit_ = PaperExit("2026-05-25 11:00:00", pair, reason,
                          100.0, 102.0, pnl_quote, pnl_pct, hold_sec, mfe, mae)
        return MatchedTrade(entry=entry, exit=exit_)

    def test_empty_trades(self):
        result = analyze([])
        assert result.total_trades == 0
        assert result.win_rate_pct is None
        assert result.total_pnl_quote == 0.0

    def test_single_win(self):
        t = self._make_trade(pnl_pct=2.0, pnl_quote=0.5)
        result = analyze([t])
        assert result.total_trades == 1
        assert result.win_trades == 1
        assert result.loss_trades == 0
        assert result.win_rate_pct == 100.0
        assert result.total_pnl_quote == pytest.approx(0.5)
        assert result.avg_pnl_pct == pytest.approx(2.0)
        assert result.best_pnl_pct == pytest.approx(2.0)
        assert result.worst_pnl_pct == pytest.approx(2.0)

    def test_single_loss(self):
        t = self._make_trade(pnl_pct=-1.2, pnl_quote=-0.3, reason="STOP_LOSS")
        result = analyze([t])
        assert result.win_trades == 0
        assert result.loss_trades == 1
        assert result.win_rate_pct == 0.0
        assert result.total_pnl_quote == pytest.approx(-0.3)

    def test_win_rate_mixed(self):
        win = self._make_trade(pnl_pct=2.0, pnl_quote=0.5)
        loss = self._make_trade(pnl_pct=-1.0, pnl_quote=-0.25, reason="STOP_LOSS")
        result = analyze([win, loss])
        assert result.win_rate_pct == pytest.approx(50.0)
        assert result.total_pnl_quote == pytest.approx(0.25)

    def test_by_exit_reason_breakdown(self):
        tp = self._make_trade(reason="TAKE_PROFIT", pnl_pct=2.0, pnl_quote=0.5)
        sl = self._make_trade(reason="STOP_LOSS", pnl_pct=-1.2, pnl_quote=-0.3)
        result = analyze([tp, sl])
        assert "TAKE_PROFIT" in result.by_exit_reason
        assert "STOP_LOSS" in result.by_exit_reason
        assert result.by_exit_reason["TAKE_PROFIT"]["wins"] == 1
        assert result.by_exit_reason["STOP_LOSS"]["wins"] == 0

    def test_by_regime_breakdown(self):
        bull = self._make_trade(regime="BULL", pnl_pct=2.0, pnl_quote=0.5)
        chop = self._make_trade(regime="CHOP", pnl_pct=-1.0, pnl_quote=-0.25)
        result = analyze([bull, chop])
        assert "BULL" in result.by_regime
        assert "CHOP" in result.by_regime

    def test_by_pair_breakdown(self):
        sol = self._make_trade(pair="SOL-USD", pnl_pct=2.0, pnl_quote=0.5)
        eth = self._make_trade(pair="ETH-USD", pnl_pct=-1.0, pnl_quote=-0.25)
        result = analyze([sol, eth])
        assert "SOL-USD" in result.by_pair
        assert "ETH-USD" in result.by_pair

    def test_avg_hold_minutes(self):
        t1 = self._make_trade(hold_sec=3600)   # 60 min
        t2 = self._make_trade(hold_sec=1800)   # 30 min
        result = analyze([t1, t2])
        assert result.avg_hold_minutes == pytest.approx(45.0)

    def test_unmatched_exits_passed_through(self):
        result = analyze([], unmatched_exits=3)
        assert result.unmatched_exits == 3


# ---------------------------------------------------------------------------
# format_report tests
# ---------------------------------------------------------------------------

class TestFormatReport:
    def _result_with_trades(self):
        entry = PaperEntry("2026-05-25 10:00:00", "SOL-USD", 82.5, 100.0, "BULL", 1.8, 25.0)
        exit_ = PaperExit("2026-05-25 11:00:00", "SOL-USD", "TAKE_PROFIT",
                          100.0, 102.0, 0.5, 2.0, 3600, 2.0, 0.3)
        trade = MatchedTrade(entry=entry, exit=exit_)
        return analyze([trade])

    def test_report_contains_key_sections(self):
        result = self._result_with_trades()
        report = format_report(result)
        assert "MOMENTUM SLEEVE" in report
        assert "Win rate" in report
        assert "BY EXIT REASON" in report
        assert "BY REGIME" in report
        assert "BY PAIR" in report

    def test_empty_report_message(self):
        report = format_report(analyze([]))
        assert "No completed trades" in report

    def test_unmatched_warning_shown(self):
        result = analyze([], unmatched_exits=2)
        # Force total_trades=1 to bypass empty-report path
        entry = PaperEntry("2026-05-25 10:00:00", "SOL-USD", 80.0, 100.0, "BULL", 1.5, 25.0)
        exit_ = PaperExit("2026-05-25 11:00:00", "SOL-USD", "TAKE_PROFIT",
                          100.0, 102.0, 0.5, 2.0, 3600, 2.0, 0.3)
        result = analyze([MatchedTrade(entry=entry, exit=exit_)], unmatched_exits=2)
        report = format_report(result)
        assert "Unmatched exits" in report
