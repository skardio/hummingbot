#!/usr/bin/env python3
"""
ST-06b post-run SQLite report.

Reads Hummingbot's trading database directly and reports executor/fill
completeness, basic performance, and previous-window comparison.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

DECIMAL_SCALE = 100_000_000.0

CLOSE_TYPE_NAMES = {
    1: "TIME_LIMIT",
    2: "STOP_LOSS",
    3: "TAKE_PROFIT",
    4: "EXPIRED",
    5: "EARLY_STOP",
    6: "TRAILING_STOP",
    7: "INSUFFICIENT_BALANCE",
    8: "FAILED",
    9: "COMPLETED",
    10: "POSITION_HOLD",
    11: "NO_FILL_TIMEOUT",
    12: "NO_PROGRESS_TIMEOUT",
    13: "HARD_CAP_TIME_LIMIT",
    14: "RISK_KILL_SWITCH",
    15: "MANUAL",
    16: "SWITCH",
}

BOT_DATABASES = {
    "kraken-eur": "data/multi_coin_grid_v2.sqlite",
    "kraken-usd": "data/multi_coin_grid_v2_usd.sqlite",
    "bitget": "data/spot_grid_bitget.sqlite",
    "bitget-spot": "data/spot_grid_bitget.sqlite",
    "bitget-futures": "data/futures_grid_bitget.sqlite",
}


@dataclass(frozen=True)
class TimeWindow:
    since_sec: Optional[float]
    until_sec: Optional[float]

    @property
    def since_ms(self) -> Optional[int]:
        return int(self.since_sec * 1000) if self.since_sec is not None else None

    @property
    def until_ms(self) -> Optional[int]:
        return int(self.until_sec * 1000) if self.until_sec is not None else None


def resolve_db_path(bot_or_path: str, repo_root: Optional[Path] = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    configured = BOT_DATABASES.get(bot_or_path, bot_or_path)
    path = Path(configured)
    return path if path.is_absolute() else root / path


def _one(cur: sqlite3.Cursor, query: str, params: Iterable[Any] = ()) -> Any:
    row = cur.execute(query, tuple(params)).fetchone()
    return row[0] if row else None


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    return bool(_one(cur, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def _window_predicate(column: str, window: TimeWindow, millis: bool = False) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    since = window.since_ms if millis else window.since_sec
    until = window.until_ms if millis else window.until_sec
    if since is not None:
        clauses.append(f"{column} >= ?")
        params.append(since)
    if until is not None:
        clauses.append(f"{column} < ?")
        params.append(until)
    return (" AND ".join(clauses) if clauses else "1=1", params)


def _executor_window_predicate(window: TimeWindow) -> tuple[str, list[Any]]:
    timestamp_pred, timestamp_params = _window_predicate("timestamp", window)
    close_pred, close_params = _window_predicate("close_timestamp", window)
    if timestamp_pred == "1=1" and close_pred == "1=1":
        return "1=1", []
    return f"(({timestamp_pred}) OR ({close_pred}))", timestamp_params + close_params


def _executor_window_predicate_for_alias(alias: str, window: TimeWindow) -> tuple[str, list[Any]]:
    timestamp_pred, timestamp_params = _window_predicate(f"{alias}.timestamp", window)
    close_pred, close_params = _window_predicate(f"{alias}.close_timestamp", window)
    if timestamp_pred == "1=1" and close_pred == "1=1":
        return "1=1", []
    return f"(({timestamp_pred}) OR ({close_pred}))", timestamp_params + close_params


def _summary_for_window(cur: sqlite3.Cursor, window: TimeWindow) -> Dict[str, Any]:
    executor_pred, executor_params = _executor_window_predicate(window)
    fill_pred, fill_params = _window_predicate("timestamp", window, millis=True)

    summary: Dict[str, Any] = {}
    if _table_exists(cur, "Executors"):
        row = cur.execute(
            f"""
            SELECT
                COUNT(*) AS executors,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) AS closed,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) AS filled,
                COALESCE(SUM(net_pnl_quote), 0.0) AS net_pnl,
                COALESCE(SUM(cum_fees_quote), 0.0) AS fees,
                COALESCE(SUM(filled_amount_quote), 0.0) AS executor_volume
            FROM Executors
            WHERE {executor_pred}
            """,
            executor_params,
        ).fetchone()
        keys = ["executors", "closed", "active", "filled", "net_pnl", "fees", "executor_volume"]
        summary.update(dict(zip(keys, row)))
    else:
        summary.update({k: 0 for k in ["executors", "closed", "active", "filled"]})
        summary.update({"net_pnl": 0.0, "fees": 0.0, "executor_volume": 0.0})

    if _table_exists(cur, "TradeFill"):
        row = cur.execute(
            f"""
            SELECT
                COUNT(*) AS fills,
                SUM(CASE WHEN trade_type = 'BUY' THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN trade_type = 'SELL' THEN 1 ELSE 0 END) AS sells,
                COALESCE(SUM((price / ?) * (amount / ?)), 0.0) AS gross_turnover,
                COALESCE(SUM(trade_fee_in_quote / ?), 0.0) AS fill_fees
            FROM TradeFill
            WHERE {fill_pred}
            """,
            [DECIMAL_SCALE, DECIMAL_SCALE, DECIMAL_SCALE] + fill_params,
        ).fetchone()
        keys = ["fills", "buys", "sells", "gross_turnover", "fill_fees"]
        summary.update(dict(zip(keys, row)))
    else:
        summary.update({k: 0 for k in ["fills", "buys", "sells"]})
        summary.update({"gross_turnover": 0.0, "fill_fees": 0.0})

    return summary


def _quality_checks(cur: sqlite3.Cursor, window: TimeWindow) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    executor_pred, executor_params = _executor_window_predicate(window)
    fill_pred, fill_params = _window_predicate("timestamp", window, millis=True)

    if _table_exists(cur, "Executors"):
        checks["closed_missing_close_timestamp"] = _one(
            cur,
            f"SELECT COUNT(*) FROM Executors WHERE {executor_pred} AND is_active = 0 AND close_timestamp IS NULL",
            executor_params,
        ) or 0
        checks["closed_before_open"] = _one(
            cur,
            f"""
            SELECT COUNT(*) FROM Executors
            WHERE {executor_pred}
              AND close_timestamp IS NOT NULL
              AND close_timestamp < timestamp
            """,
            executor_params,
        ) or 0
        checks["missing_trading_pair"] = _one(
            cur,
            f"""
            SELECT COUNT(*) FROM Executors
            WHERE {executor_pred}
              AND json_extract(config, '$.trading_pair') IS NULL
            """,
            executor_params,
        ) or 0
        latest_executor_ts = _one(
            cur,
            f"""
            SELECT MAX(ts) FROM (
                SELECT timestamp AS ts FROM Executors WHERE {executor_pred}
                UNION ALL
                SELECT close_timestamp AS ts FROM Executors
                WHERE {executor_pred} AND close_timestamp IS NOT NULL
            )
            """,
            executor_params + executor_params,
        ) or 0
    else:
        latest_executor_ts = 0

    if _table_exists(cur, "TradeFill"):
        if _table_exists(cur, "Order"):
            checks["fills_without_order"] = _one(
                cur,
                f"""
                SELECT COUNT(*) FROM TradeFill tf
                LEFT JOIN "Order" o ON o.id = tf.order_id
                WHERE {fill_pred} AND o.id IS NULL
                """,
                fill_params,
            ) or 0
        latest_fill_ms = _one(
            cur,
            f"SELECT MAX(timestamp) FROM TradeFill WHERE {fill_pred}",
            fill_params,
        ) or 0
        checks["latest_fill_after_executor_activity_sec"] = max(
            0.0,
            (float(latest_fill_ms) / 1000.0) - float(latest_executor_ts or 0.0),
        )

    if _table_exists(cur, "Executors") and _table_exists(cur, "TradeFill"):
        executor_pred_e, executor_params_e = _executor_window_predicate_for_alias("e", window)
        checks["active_executors_with_untracked_fills"] = _one(
            cur,
            f"""
            SELECT COUNT(*) FROM Executors e
            WHERE {executor_pred_e}
              AND e.is_active = 1
              AND COALESCE(e.filled_amount_quote, 0.0) <= 0.0
              AND EXISTS (
                  SELECT 1 FROM TradeFill tf
                  WHERE tf.symbol = json_extract(e.config, '$.trading_pair')
                    AND tf.timestamp >= CAST(e.timestamp * 1000 AS INTEGER)
                    AND tf.timestamp <= COALESCE(CAST(e.close_timestamp * 1000 AS INTEGER), ?)
              )
            """,
            executor_params_e + [window.until_ms or 9_999_999_999_999],
        ) or 0
        checks["failed_insufficient_balance_positive_pnl"] = _one(
            cur,
            f"""
            SELECT COUNT(*) FROM Executors
            WHERE {executor_pred}
              AND close_type = 8
              AND net_pnl_quote > 0
              AND json_extract(custom_info, '$.early_stop_reason') = 'INSUFFICIENT_BALANCE'
            """,
            executor_params,
        ) or 0

    return checks


def analyze_database(db_path: Path, hours: int = 24, now_sec: Optional[float] = None) -> Dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    now = now_sec if now_sec is not None else datetime.now(tz=timezone.utc).timestamp()
    current = TimeWindow(since_sec=now - hours * 3600, until_sec=now)
    previous = TimeWindow(since_sec=now - (hours * 2) * 3600, until_sec=now - hours * 3600)

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.cursor()
        report = {
            "db_path": str(db_path),
            "hours": hours,
            "current": _summary_for_window(cur, current),
            "previous": _summary_for_window(cur, previous),
            "quality": _quality_checks(cur, current),
            "top_pairs": _top_pairs(cur, current),
            "close_types": _close_types(cur, current),
            "outcome_classes": _outcome_classes(cur, current),
            "active_fill_mismatches": _active_fill_mismatches(cur, current),
        }
    return report


def _top_pairs(cur: sqlite3.Cursor, window: TimeWindow, limit: int = 10) -> list[Dict[str, Any]]:
    if not _table_exists(cur, "Executors"):
        return []
    pred, params = _executor_window_predicate(window)
    rows = cur.execute(
        f"""
        SELECT
            COALESCE(json_extract(config, '$.trading_pair'), '?') AS pair,
            COUNT(*) AS executors,
            SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) AS filled,
            COALESCE(SUM(net_pnl_quote), 0.0) AS pnl,
            COALESCE(SUM(cum_fees_quote), 0.0) AS fees
        FROM Executors
        WHERE {pred}
        GROUP BY pair
        ORDER BY ABS(COALESCE(SUM(net_pnl_quote), 0.0)) DESC, executors DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [
        {"pair": r[0], "executors": r[1], "filled": r[2], "pnl": r[3], "fees": r[4]}
        for r in rows
    ]


def _close_types(cur: sqlite3.Cursor, window: TimeWindow) -> list[Dict[str, Any]]:
    if not _table_exists(cur, "Executors"):
        return []
    pred, params = _executor_window_predicate(window)
    rows = cur.execute(
        f"""
        SELECT close_type, COUNT(*) AS n, COALESCE(SUM(net_pnl_quote), 0.0) AS pnl
        FROM Executors
        WHERE {pred}
        GROUP BY close_type
        ORDER BY n DESC
        """,
        params,
    ).fetchall()
    return [
        {
            "close_type": r[0],
            "name": CLOSE_TYPE_NAMES.get(r[0], "UNKNOWN"),
            "count": r[1],
            "pnl": r[2],
        }
        for r in rows
    ]


def _outcome_classes(cur: sqlite3.Cursor, window: TimeWindow) -> list[Dict[str, Any]]:
    if not _table_exists(cur, "Executors"):
        return []
    pred, params = _executor_window_predicate(window)
    rows = cur.execute(
        f"""
        SELECT
            CASE
                WHEN close_type = 8
                     AND json_extract(custom_info, '$.early_stop_reason') = 'INSUFFICIENT_BALANCE'
                    THEN 'ERROR_FAILED_INSUFFICIENT_BALANCE'
                WHEN close_type = 7
                    THEN 'ERROR_INSUFFICIENT_BALANCE'
                WHEN close_type = 8
                    THEN 'ERROR_FAILED_OTHER'
                WHEN close_type = 2
                    THEN 'LOSS_STOP_LOSS'
                WHEN net_pnl_quote > 0
                    THEN 'NORMAL_WIN'
                WHEN net_pnl_quote < 0
                    THEN 'NORMAL_LOSS'
                ELSE 'NEUTRAL_OR_NO_FILL'
            END AS outcome_class,
            COUNT(*) AS n,
            COALESCE(SUM(net_pnl_quote), 0.0) AS pnl,
            COALESCE(SUM(filled_amount_quote), 0.0) AS volume
        FROM Executors
        WHERE {pred}
        GROUP BY outcome_class
        ORDER BY n DESC
        """,
        params,
    ).fetchall()
    return [{"class": r[0], "count": r[1], "pnl": r[2], "volume": r[3]} for r in rows]


def _active_fill_mismatches(cur: sqlite3.Cursor, window: TimeWindow, limit: int = 10) -> list[Dict[str, Any]]:
    if not (_table_exists(cur, "Executors") and _table_exists(cur, "TradeFill")):
        return []
    pred, params = _executor_window_predicate_for_alias("e", window)
    rows = cur.execute(
        f"""
        SELECT
            e.id,
            COALESCE(json_extract(e.config, '$.trading_pair'), '?') AS pair,
            COALESCE(e.filled_amount_quote, 0.0) AS executor_volume,
            COUNT(tf.order_id) AS fill_count,
            COALESCE(SUM((tf.price / ?) * (tf.amount / ?)), 0.0) AS fill_turnover
        FROM Executors e
        JOIN TradeFill tf
          ON tf.symbol = json_extract(e.config, '$.trading_pair')
         AND tf.timestamp >= CAST(e.timestamp * 1000 AS INTEGER)
         AND tf.timestamp <= COALESCE(CAST(e.close_timestamp * 1000 AS INTEGER), ?)
        WHERE {pred}
          AND e.is_active = 1
          AND COALESCE(e.filled_amount_quote, 0.0) <= 0.0
        GROUP BY e.id, pair, executor_volume
        HAVING fill_count > 0
        ORDER BY fill_turnover DESC
        LIMIT ?
        """,
        [DECIMAL_SCALE, DECIMAL_SCALE, window.until_ms or 9_999_999_999_999] + params + [limit],
    ).fetchall()
    return [
        {
            "executor_id": r[0],
            "pair": r[1],
            "executor_volume": r[2],
            "fill_count": r[3],
            "fill_turnover": r[4],
        }
        for r in rows
    ]


def _pct(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100.0) if denominator else 0.0


def render_report(report: Dict[str, Any]) -> str:
    cur = report["current"]
    prev = report["previous"]
    quality = report["quality"]

    lines = [
        f"SQLite post-run report: {report['db_path']}",
        f"Window: last {report['hours']}h",
        "",
        "Summary",
        f"- Executors: {cur['executors']} closed={cur['closed']} active={cur['active']} filled={cur['filled']} "
        f"fill_rate={_pct(cur['filled'], cur['executors']):.1f}%",
        f"- Executor PnL: {cur['net_pnl']:.4f} fees={cur['fees']:.4f} volume={cur['executor_volume']:.4f}",
        f"- TradeFill: {cur['fills']} buys={cur['buys']} sells={cur['sells']} "
        f"turnover={cur['gross_turnover']:.4f} fill_fees={cur['fill_fees']:.4f}",
        "",
        "Previous-window delta",
        f"- Executors: {cur['executors'] - prev['executors']:+}",
        f"- TradeFill: {cur['fills'] - prev['fills']:+}",
        f"- PnL: {cur['net_pnl'] - prev['net_pnl']:+.4f}",
        "",
        "Data quality",
    ]

    for key, value in quality.items():
        status = "OK" if float(value or 0) == 0 else "CHECK"
        if key == "latest_fill_after_executor_activity_sec":
            status = "OK" if float(value or 0) <= 300 else "CHECK"
            lines.append(f"- {key}: {float(value):.0f}s [{status}]")
        else:
            lines.append(f"- {key}: {value} [{status}]")

    if report["close_types"]:
        lines.extend(["", "Close types"])
        for row in report["close_types"]:
            lines.append(
                f"- {row['close_type']} {row['name']}: n={row['count']} pnl={row['pnl']:.4f}"
            )

    if report["outcome_classes"]:
        lines.extend(["", "Outcome classes"])
        for row in report["outcome_classes"]:
            lines.append(
                f"- {row['class']}: n={row['count']} pnl={row['pnl']:.4f} "
                f"volume={row['volume']:.4f}"
            )

    if report["active_fill_mismatches"]:
        lines.extend(["", "Active executor / TradeFill mismatches"])
        for row in report["active_fill_mismatches"]:
            lines.append(
                f"- {row['pair']} {row['executor_id'][:8]}...: "
                f"executor_volume={row['executor_volume']:.4f} "
                f"tradefills={row['fill_count']} turnover={row['fill_turnover']:.4f}"
            )

    if report["top_pairs"]:
        lines.extend(["", "Top pairs by PnL impact"])
        for row in report["top_pairs"]:
            lines.append(
                f"- {row['pair']}: executors={row['executors']} filled={row['filled']} "
                f"pnl={row['pnl']:.4f} fees={row['fees']:.4f}"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-run SQLite report for multi-coin grid bots")
    parser.add_argument("--bot", default="kraken-usd", help="Bot key or SQLite path")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    args = parser.parse_args()

    db_path = resolve_db_path(args.bot)
    report = analyze_database(db_path=db_path, hours=args.hours)
    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
