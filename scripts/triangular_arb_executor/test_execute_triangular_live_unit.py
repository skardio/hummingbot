from decimal import Decimal

from scripts.triangular_arb_executor.execute_triangular_live import LiveExecutor


def test_pair_to_ccxt_symbol_converts_dash_format():
    assert LiveExecutor._pair_to_ccxt_symbol("ETH-EUR") == "ETH/EUR"


def test_candidate_profit_prefers_net_profit_after_fees():
    executor = LiveExecutor()
    record = {
        "edge_pct": 0.35,
        "profit_pct_after_fees": 0.11,
    }

    assert executor._candidate_profit_pct(record) == Decimal("0.11")


def test_candidate_profit_falls_back_to_edge_pct():
    executor = LiveExecutor()
    record = {
        "edge_pct": 0.35,
    }

    assert executor._candidate_profit_pct(record) == Decimal("0.35")


def test_candidate_key_uses_timestamp_when_available():
    executor = LiveExecutor()
    record = {
        "triple": ["ETH-EUR", "EUR-USD", "ETH-USD"],
        "timestamp": "2026-04-22T10:00:00Z",
        "edge_pct": 0.2,
    }

    assert executor._candidate_key(record) == (
        ("ETH-EUR", "EUR-USD", "ETH-USD"),
        "2026-04-22T10:00:00Z",
    )


def test_candidate_key_falls_back_to_edge_when_no_timestamp():
    executor = LiveExecutor()
    record = {
        "triple": ["ETH-EUR", "EUR-USD", "ETH-USD"],
        "edge_pct": 0.2,
    }

    assert executor._candidate_key(record) == (
        ("ETH-EUR", "EUR-USD", "ETH-USD"),
        0.2,
    )
