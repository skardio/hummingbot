"""Read-only enforcement tests for the database adapter.

These tests build a throwaway database in ``tmp_path`` and then try to mutate it
through the Evidence Engine's connection. Every attempt must fail.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal

import pytest

from tools.evidence.db import (
    SCALE_AMOUNT,
    SCALE_FEE_QUOTE,
    SCALE_PRICE,
    ReadOnlyViolation,
    execute_read,
    executor_order_ids,
    load_closed_executors,
    read_only_connection,
    tradefill_attribution,
)


@pytest.fixture
def sample_db(tmp_path):
    """A minimal database with the real Executors and TradeFill shape."""
    path = tmp_path / "sample.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE Executors (id TEXT PRIMARY KEY, timestamp FLOAT, type TEXT, close_type INTEGER, "
        "close_timestamp BIGINT, status INTEGER, config JSON, net_pnl_pct FLOAT, net_pnl_quote FLOAT, "
        "cum_fees_quote FLOAT, filled_amount_quote FLOAT, is_active BOOLEAN, is_trading BOOLEAN, "
        "custom_info JSON, controller_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE TradeFill (market TEXT, order_id TEXT, exchange_trade_id TEXT, symbol TEXT, "
        "timestamp BIGINT, trade_type TEXT, order_type TEXT, price BIGINT, amount BIGINT, "
        "trade_fee JSON, trade_fee_in_quote BIGINT)"
    )
    config = json.dumps({"trading_pair": "APE-USD", "connector_name": "kraken"})
    custom_info = json.dumps(
        {
            "filled_orders": [
                {
                    "client_order_id": "b1",
                    "trade_type": "BUY",
                    "executed_amount_base": "100",
                    "executed_amount_quote": "100.00",
                    "cumulative_fee_paid_quote": "0.10",
                },
                {
                    "client_order_id": "s1",
                    "trade_type": "SELL",
                    "executed_amount_base": "100",
                    "executed_amount_quote": "110.00",
                    "cumulative_fee_paid_quote": "0.10",
                },
            ],
            "held_position_orders": [],
            "realized_buy_size_quote": "100.00",
            "realized_sell_size_quote": "110.00",
            "position_size_quote": "0",
        }
    )
    connection.execute(
        "INSERT INTO Executors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("e1", 1.0, "grid_executor", 3, 1767225600, 4, config, 0.1, 9.8, 0.2, 210.0, 0, 0,
         custom_info, "multi_coin_grid_usd"),
    )
    connection.execute(
        "INSERT INTO Executors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("e2", 2.0, "grid_executor", 7, None, 4, config, 0.0, 0.0, 0.0, 0.0, 1, 0,
         json.dumps({}), "multi_coin_grid_usd"),
    )
    connection.execute(
        "INSERT INTO TradeFill VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("kraken", "b1", "t1", "APE-USD", 1767225600000, "BUY", "LIMIT",
         10000000, 100000000000, "{}", 100000000),
    )
    connection.commit()
    connection.close()
    return path


def test_select_works(sample_db):
    with read_only_connection(sample_db) as connection:
        rows = execute_read(connection, "SELECT COUNT(*) AS n FROM Executors")
    assert rows[0]["n"] == 2


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO Executors (id) VALUES ('x')",
        "UPDATE Executors SET net_pnl_quote = 999",
        "DELETE FROM Executors",
        "DROP TABLE Executors",
        "ALTER TABLE Executors ADD COLUMN hacked TEXT",
        "CREATE TABLE evil (a TEXT)",
        "CREATE TEMP TABLE evil (a TEXT)",
        "CREATE INDEX idx ON Executors(id)",
        "REPLACE INTO Executors (id) VALUES ('x')",
        "PRAGMA query_only = OFF",
        "PRAGMA journal_mode = DELETE",
        "ATTACH DATABASE ':memory:' AS other",
        "VACUUM",
        "ANALYZE",
    ],
)
def test_every_mutation_is_rejected(sample_db, statement):
    with read_only_connection(sample_db) as connection:
        with pytest.raises((ReadOnlyViolation, sqlite3.DatabaseError)):
            execute_read(connection, statement)


def test_database_is_unchanged_after_attempts(sample_db):
    before = sample_db.read_bytes()
    with read_only_connection(sample_db) as connection:
        for statement in ("DELETE FROM Executors", "UPDATE Executors SET net_pnl_quote = 1"):
            with pytest.raises((ReadOnlyViolation, sqlite3.DatabaseError)):
                execute_read(connection, statement)
    assert sample_db.read_bytes() == before


def test_missing_database_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        with read_only_connection(tmp_path / "nope.sqlite"):
            pass


def test_load_closed_executors_skips_open_ones(sample_db):
    executors = load_closed_executors(sample_db)
    assert [e.executor_id for e in executors] == ["e1"]
    assert executors[0].trading_pair == "APE-USD"
    assert executors[0].connector_name == "kraken"
    assert executors[0].net_pnl_quote == Decimal("9.8")
    assert executors[0].custom_info["realized_buy_size_quote"] == "100.00"


def test_load_closed_executors_filters(sample_db):
    assert load_closed_executors(sample_db, controller_id="other") == []
    assert len(load_closed_executors(sample_db, period_start=0, period_end=1767225600)) == 1
    assert load_closed_executors(sample_db, period_start=1767225601) == []


def test_malformed_json_degrades_safely(tmp_path, sample_db):
    connection = sqlite3.connect(sample_db)
    connection.execute(
        "INSERT INTO Executors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("e3", 3.0, "grid_executor", 3, 1767225600, 4, "{not json", 0.0, 0.0, 0.0, 0.0, 0, 0,
         "also not json", "multi_coin_grid_usd"),
    )
    connection.commit()
    connection.close()

    executors = load_closed_executors(sample_db)
    broken = [e for e in executors if e.executor_id == "e3"][0]
    assert broken.config == {}
    assert broken.custom_info == {}
    assert broken.trading_pair == "UNKNOWN"


# ------------------------------------------------------------ scaling ---
def test_scaling_constants_are_1e8():
    """Regression: TradeFill.amount is /1e8, not /1e9.

    Proven by matching one order present in both tables:
    TradeFill.amount 12162587330 / 1e8 == 121.62587330, which is exactly
    custom_info.filled_orders[].executed_amount_base for that order.
    """
    assert SCALE_AMOUNT == Decimal("1e8")
    assert SCALE_PRICE == Decimal("1e8")
    assert SCALE_FEE_QUOTE == Decimal("1e8")


def test_real_world_scaling_example():
    """The exact row that disproved the /1e9 documentation."""
    raw_amount = Decimal("12162587330")
    raw_price = Decimal("16630000")
    assert raw_amount / SCALE_AMOUNT == Decimal("121.62587330")
    assert raw_price / SCALE_PRICE == Decimal("0.16630000")
    notional = (raw_amount / SCALE_AMOUNT) * (raw_price / SCALE_PRICE)
    assert abs(notional - Decimal("20.22638272979")) < Decimal("0.00001")
    # The /1e9 reading is off by exactly a factor ten.
    assert raw_amount / Decimal("1e9") * 10 == raw_amount / SCALE_AMOUNT


def test_fee_scaling_matches_the_json_fee_amount():
    """trade_fee_in_quote is /1e8, proven against the JSON flat_fees value.

    The fee *rate* cannot settle this: it is scale-invariant, because fee and
    amount scale together. The absolute value can. Real Kraken row: APE-USD
    SELL with trade_fee_in_quote 11997200 and
    trade_fee.flat_fees[0].amount "0.119972".
    """
    raw_fee = Decimal("11997200")
    json_fee = Decimal("0.119972")
    assert raw_fee / SCALE_FEE_QUOTE == json_fee
    assert raw_fee / Decimal("1e9") != json_fee


# -------------------------------------------------------- attribution ---
def test_executor_order_ids_covers_every_order_list(sample_db):
    executors = load_closed_executors(sample_db)
    ids = executor_order_ids(executors)
    assert ids == {"b1", "s1"}


def test_tradefill_attribution_matches_on_order_id(sample_db):
    executors = load_closed_executors(sample_db)
    attribution = tradefill_attribution(sample_db, executors)
    assert attribution.attributable
    assert attribution.reason == "matched on TradeFill.order_id"
    assert attribution.n_order_ids == 2
    assert attribution.n_matched_fills == 1
    assert attribution.n_total_fills == 1
    assert attribution.executor_volume == Decimal("210")
    # fixture fill: amount 100000000000 / 1e8 = 1000, price 10000000 / 1e8 = 0.1
    assert attribution.attributed_volume == Decimal("100")
    assert attribution.controller_ids == ("multi_coin_grid_usd",)


def test_attribution_ratio_and_fee_rate(sample_db):
    attribution = tradefill_attribution(sample_db, load_closed_executors(sample_db))
    assert attribution.attribution_ratio == Decimal("100") / Decimal("210")
    # fixture fee 100000000 / 1e8 = 1.0 over 100 notional
    assert attribution.effective_fee_rate == Decimal("0.01")


def test_attribution_not_measurable_without_order_ids(sample_db):
    """Without recorded client order ids the metric is suppressed, not guessed."""
    executors = [e for e in load_closed_executors(sample_db)]
    stripped = [
        type(e)(**{**e.__dict__, "custom_info": {}}) for e in executors
    ]
    attribution = tradefill_attribution(sample_db, stripped)
    assert attribution.attributable is False
    assert "no client order ids" in attribution.reason
    assert attribution.attribution_ratio is None
    assert attribution.effective_fee_rate is None
