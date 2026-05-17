import sqlite3

from multi_coin_grid_pro.scripts.post_run_sqlite_report import analyze_database, render_report


def _create_test_db(path):
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE Executors (
                id TEXT PRIMARY KEY,
                timestamp FLOAT NOT NULL,
                type TEXT NOT NULL,
                close_type INTEGER,
                close_timestamp BIGINT,
                status INTEGER NOT NULL,
                config JSON NOT NULL,
                net_pnl_pct FLOAT NOT NULL,
                net_pnl_quote FLOAT NOT NULL,
                cum_fees_quote FLOAT NOT NULL,
                filled_amount_quote FLOAT NOT NULL,
                is_active BOOLEAN NOT NULL,
                is_trading BOOLEAN NOT NULL,
                custom_info JSON NOT NULL,
                controller_id TEXT
            );
            CREATE TABLE "Order" (
                id TEXT PRIMARY KEY
            );
            CREATE TABLE TradeFill (
                config_file_path TEXT NOT NULL,
                strategy TEXT NOT NULL,
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                base_asset TEXT NOT NULL,
                quote_asset TEXT NOT NULL,
                timestamp BIGINT NOT NULL,
                order_id TEXT NOT NULL,
                trade_type TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price BIGINT NOT NULL,
                amount BIGINT NOT NULL,
                leverage INTEGER NOT NULL,
                trade_fee JSON NOT NULL,
                trade_fee_in_quote BIGINT,
                exchange_trade_id TEXT NOT NULL,
                position TEXT,
                PRIMARY KEY (market, order_id, exchange_trade_id)
            );
            """
        )
        conn.execute('INSERT INTO "Order" (id) VALUES (?)', ("order-1",))
        conn.execute(
            """
            INSERT INTO Executors VALUES (
                'exec-1', 1000, 'grid_executor', 3, 1100, 4,
                '{"trading_pair":"INJ-USD"}',
                0.01, 0.42, 0.08, 50.0, 0, 0, '{}', 'controller-1'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TradeFill VALUES (
                'multi_coin_grid_v2_usd', 'multi_coin_grid_v2_usd', 'kraken',
                'INJ-USD', 'INJ', 'USD', 1050000, 'order-1', 'BUY', 'LIMIT',
                400000000, 1250000000, 1, '{}', 10000000, 'trade-1', NULL
            )
            """
        )


def _insert_active_executor_with_untracked_fill(path):
    with sqlite3.connect(str(path)) as conn:
        conn.execute('INSERT INTO "Order" (id) VALUES (?)', ("order-fil",))
        conn.execute(
            """
            INSERT INTO Executors VALUES (
                'exec-fil', 2000, 'grid_executor', NULL, NULL, 2,
                '{"trading_pair":"FIL-USD"}',
                0.0, 0.0, 0.0, 0.0, 1, 1, '{}', 'controller-1'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO TradeFill VALUES (
                'multi_coin_grid_v2_usd', 'multi_coin_grid_v2_usd', 'kraken',
                'FIL-USD', 'FIL', 'USD', 2100000, 'order-fil', 'BUY', 'LIMIT',
                121900000, 1402010783, 1, '{}', 3418000, 'trade-fil', NULL
            )
            """
        )


def _insert_failed_insufficient_balance_positive_pnl(path):
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            INSERT INTO Executors VALUES (
                'exec-ai', 2200, 'grid_executor', 8, 2300, 4,
                '{"trading_pair":"AI-USD"}',
                0.003, 0.1666, 0.1032, 51.5958, 0, 0,
                '{"early_stop_reason":"INSUFFICIENT_BALANCE"}',
                'controller-1'
            )
            """
        )


def test_post_run_report_summarizes_executor_and_fill_data(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    _create_test_db(db_path)

    report = analyze_database(db_path, hours=1, now_sec=4600)

    assert report["current"]["executors"] == 1
    assert report["current"]["fills"] == 1
    assert report["current"]["gross_turnover"] == 50.0
    assert report["quality"]["closed_missing_close_timestamp"] == 0


def test_render_report_contains_quality_section(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    _create_test_db(db_path)

    rendered = render_report(analyze_database(db_path, hours=1, now_sec=4600))

    assert "Data quality" in rendered
    assert "latest_fill_after_executor_activity_sec" in rendered
    assert "INJ-USD" in rendered


def test_report_flags_active_executor_tradefill_mismatch(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    _create_test_db(db_path)
    _insert_active_executor_with_untracked_fill(db_path)

    report = analyze_database(db_path, hours=1, now_sec=4600)

    assert report["quality"]["active_executors_with_untracked_fills"] == 1
    mismatch = report["active_fill_mismatches"][0]
    assert mismatch["executor_id"] == "exec-fil"
    assert mismatch["pair"] == "FIL-USD"
    assert mismatch["executor_volume"] == 0.0
    assert mismatch["fill_count"] == 1
    assert round(mismatch["fill_turnover"], 4) == 17.0905

    rendered = render_report(report)
    assert "Active executor / TradeFill mismatches" in rendered
    assert "FIL-USD exec-fil..." in rendered


def test_report_classifies_failed_insufficient_balance_separately(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    _create_test_db(db_path)
    _insert_failed_insufficient_balance_positive_pnl(db_path)

    report = analyze_database(db_path, hours=1, now_sec=4600)

    assert report["quality"]["failed_insufficient_balance_positive_pnl"] == 1
    outcome = {
        row["class"]: row
        for row in report["outcome_classes"]
    }
    assert outcome["ERROR_FAILED_INSUFFICIENT_BALANCE"]["count"] == 1
    assert outcome["ERROR_FAILED_INSUFFICIENT_BALANCE"]["pnl"] == 0.1666

    rendered = render_report(report)
    assert "8 FAILED" in rendered
    assert "ERROR_FAILED_INSUFFICIENT_BALANCE" in rendered
