"""Read-only SQLite access for the Evidence Engine.

Read-only is enforced by three independent mechanisms, not by convention:

1. The connection is opened through a ``file:...?mode=ro`` URI.
2. ``PRAGMA query_only = ON`` is set immediately after connecting.
3. An authorizer callback denies every non-read action, including ``ATTACH``,
   ``PRAGMA`` writes and temporary-table creation.

Any attempted mutation raises :class:`ReadOnlyViolation` before it reaches the
file. This is the only module in the package that performs I/O.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set

#: Decimal scaling of the BIGINT columns. Verified by matching a single order
#: present in both tables: TradeFill.amount 12162587330 / 1e8 == 121.62587330,
#: which is exactly custom_info.filled_orders[].executed_amount_base.
#: The /1e9 figure documented elsewhere in this repository is wrong.
SCALE_AMOUNT = Decimal("1e8")
SCALE_PRICE = Decimal("1e8")
SCALE_FEE_QUOTE = Decimal("1e8")

#: Order lists inside custom_info that may reference a filled order.
ORDER_LIST_KEYS = ("filled_orders", "held_position_orders", "canceled_orders", "failed_orders")

#: SQLite has a bound-parameter limit; ids are queried in chunks.
PARAM_CHUNK = 500


def _sql_scale(scale: Decimal) -> str:
    """Render a scale as a SQL REAL literal.

    Written as ``1e8`` rather than ``100000000``: SQLite performs integer
    division when both operands are integers, which silently truncates
    ``price/100000000`` to zero.
    """
    return format(scale, "e").replace("e+0", "e").replace("e+", "e")


#: sqlite3 authorizer actions that only read. Everything else is denied.
ALLOWED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)


class ReadOnlyViolation(RuntimeError):
    """Raised when any non-read database action is attempted."""


def _authorizer(action: int, arg1: Optional[str], arg2: Optional[str], dbname: Optional[str],
                source: Optional[str]) -> int:
    """Deny every action that is not a plain read."""
    if action in ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


@contextmanager
def read_only_connection(database: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a strictly read-only connection to a SQLite database."""
    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(f"database not found: {path}")

    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorizer)
        connection.row_factory = sqlite3.Row
        yield connection
    finally:
        connection.set_authorizer(None)
        connection.close()


def execute_read(connection: sqlite3.Connection, sql: str,
                 parameters: Sequence[Any] = ()) -> List[sqlite3.Row]:
    """Run a read query, converting an authorizer denial into a clear error."""
    try:
        return connection.execute(sql, parameters).fetchall()
    except sqlite3.DatabaseError as exc:
        if "not authorized" in str(exc).lower():
            raise ReadOnlyViolation(f"non-read statement rejected: {sql.strip()[:80]}") from exc
        raise


@dataclass(frozen=True)
class RawExecutor:
    """One row of the ``Executors`` table, with JSON already parsed."""

    executor_id: str
    timestamp: float
    close_timestamp: Optional[int]
    close_type: Optional[int]
    status: Optional[int]
    controller_id: Optional[str]
    net_pnl_quote: Decimal
    cum_fees_quote: Decimal
    filled_amount_quote: Decimal
    config: Mapping[str, Any]
    custom_info: Mapping[str, Any]

    @property
    def trading_pair(self) -> str:
        return str(self.config.get("trading_pair", "UNKNOWN"))

    @property
    def connector_name(self) -> str:
        return str(self.config.get("connector_name", "UNKNOWN"))


def _parse_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001 - any malformed value becomes zero
        return Decimal(0)
    return parsed if parsed.is_finite() else Decimal(0)


def load_closed_executors(
    database: str | Path,
    *,
    controller_id: Optional[str] = None,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
) -> List[RawExecutor]:
    """Load every closed executor, optionally restricted to a cohort window."""
    clauses = ["close_timestamp IS NOT NULL"]
    params: List[Any] = []
    if controller_id is not None:
        clauses.append("controller_id = ?")
        params.append(controller_id)
    if period_start is not None:
        clauses.append("close_timestamp >= ?")
        params.append(period_start)
    if period_end is not None:
        clauses.append("close_timestamp <= ?")
        params.append(period_end)

    sql = (
        "SELECT id, timestamp, close_timestamp, close_type, status, controller_id, "
        "net_pnl_quote, cum_fees_quote, filled_amount_quote, config, custom_info "
        "FROM Executors WHERE " + " AND ".join(clauses) + " ORDER BY close_timestamp"
    )

    with read_only_connection(database) as connection:
        rows = execute_read(connection, sql, params)

    return [
        RawExecutor(
            executor_id=str(row["id"]),
            timestamp=float(row["timestamp"] or 0),
            close_timestamp=int(row["close_timestamp"]) if row["close_timestamp"] is not None else None,
            close_type=int(row["close_type"]) if row["close_type"] is not None else None,
            status=int(row["status"]) if row["status"] is not None else None,
            controller_id=row["controller_id"],
            net_pnl_quote=_decimal(row["net_pnl_quote"]),
            cum_fees_quote=_decimal(row["cum_fees_quote"]),
            filled_amount_quote=_decimal(row["filled_amount_quote"]),
            config=_parse_json(row["config"]),
            custom_info=_parse_json(row["custom_info"]),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class TradeFillAttribution:
    """How much of the executors' claimed volume is confirmed in TradeFill.

    ``TradeFill`` is linked to an executor through ``order_id``, which is a
    declared foreign key to ``Order.id`` and matches the ``client_order_id``
    values stored in ``custom_info``. That link is per-executor and therefore
    inherently controller-scoped.

    The reverse question - what share of TradeFill belongs to this controller -
    is deliberately not answered. TradeFill contains fills from orders the
    executors never recorded, so that denominator is not meaningful.
    """

    attributable: bool
    reason: str
    n_order_ids: int
    n_matched_fills: int
    n_total_fills: int
    attributed_volume: Decimal
    executor_volume: Decimal
    attributed_fees: Decimal
    controller_ids: Sequence[str] = ()

    @property
    def attribution_ratio(self) -> Optional[Decimal]:
        """Executor volume confirmed in TradeFill. Measured: Kraken 96.4%, Bitget 99.8%."""
        if not self.attributable or self.executor_volume <= 0:
            return None
        return self.attributed_volume / self.executor_volume

    @property
    def effective_fee_rate(self) -> Optional[Decimal]:
        """Per-side fee rate over attributed notional. Measured: Bitget exactly 0.1000%."""
        if not self.attributable or self.attributed_volume <= 0:
            return None
        return self.attributed_fees / self.attributed_volume


def executor_order_ids(executors: Iterable[RawExecutor]) -> Set[str]:
    """Collect every client order id referenced by the given executors."""
    ids: Set[str] = set()
    for executor in executors:
        for key in ORDER_LIST_KEYS:
            for entry in (executor.custom_info.get(key) or []):
                value = entry.get("client_order_id") if isinstance(entry, Mapping) else entry
                if value:
                    ids.add(str(value))
    return ids


def tradefill_attribution(
    database: str | Path,
    executors: Sequence[RawExecutor],
) -> TradeFillAttribution:
    """Attribute TradeFill rows to the supplied executors via ``order_id``."""
    order_ids = sorted(executor_order_ids(executors))
    executor_volume = sum((e.filled_amount_quote for e in executors), Decimal(0))

    with read_only_connection(database) as connection:
        total = execute_read(connection, "SELECT COUNT(*) AS n FROM TradeFill")[0]
        controllers = [
            str(row["controller_id"])
            for row in execute_read(
                connection,
                "SELECT DISTINCT controller_id FROM Executors WHERE controller_id IS NOT NULL",
            )
        ]
        if not order_ids:
            return TradeFillAttribution(
                attributable=False,
                reason="no client order ids recorded in custom_info",
                n_order_ids=0,
                n_matched_fills=0,
                n_total_fills=int(total["n"]),
                attributed_volume=Decimal(0),
                executor_volume=executor_volume,
                attributed_fees=Decimal(0),
                controller_ids=tuple(sorted(controllers)),
            )

        matched_fills = 0
        volume = Decimal(0)
        fees = Decimal(0)
        for start in range(0, len(order_ids), PARAM_CHUNK):
            chunk = order_ids[start:start + PARAM_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            row = execute_read(
                connection,
                "SELECT COUNT(*) AS n, "
                f"COALESCE(SUM((amount/{_sql_scale(SCALE_AMOUNT)})*(price/{_sql_scale(SCALE_PRICE)})), 0) AS volume, "
                f"COALESCE(SUM(trade_fee_in_quote/{_sql_scale(SCALE_FEE_QUOTE)}), 0) AS fees "
                f"FROM TradeFill WHERE order_id IN ({placeholders})",
                chunk,
            )[0]
            matched_fills += int(row["n"])
            volume += _decimal(row["volume"])
            fees += _decimal(row["fees"])

    return TradeFillAttribution(
        attributable=True,
        reason="matched on TradeFill.order_id",
        n_order_ids=len(order_ids),
        n_matched_fills=matched_fills,
        n_total_fills=int(total["n"]),
        attributed_volume=volume,
        executor_volume=executor_volume,
        attributed_fees=fees,
        controller_ids=tuple(sorted(controllers)),
    )
