"""Isolated persistence + restart-resume behaviour for the A/B shadow
sandbox's SQLite results store."""
import time
from decimal import Decimal

import pytest

from multi_coin_grid_pro.shadow.results_store import ShadowResultsStore
from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualExitReason, VirtualGridPosition


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "shadow_ab_results.db")


def _position() -> VirtualGridPosition:
    p = VirtualGridPosition(
        symbol="XRP-USD", notional_quote=Decimal("100"), stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), max_hold_seconds=3600.0,
        limit_price=Decimal("1.0"), created_at=time.time(),
    )
    now = time.time()
    p.try_fill_entry(Decimal("1.0"), now)
    p.try_fill_entry(Decimal("1.0"), now + 1)
    return p


def test_schema_creation_is_idempotent(db_path):
    store1 = ShadowResultsStore(db_path)
    store1.close()
    # Re-opening an existing DB must not raise (CREATE TABLE IF NOT EXISTS).
    store2 = ShadowResultsStore(db_path)
    store2.close()


def test_record_selection_is_queryable(db_path):
    store = ShadowResultsStore(db_path)
    store.record_selection(ts=1000.0, variant="A_trend_atr", symbol="XRP-USD", rank=1, trend_pct=5.0, grid_score=None)
    rows = store._conn.execute("SELECT variant, symbol, rank FROM shadow_selections").fetchall()
    store.close()
    assert rows == [("A_trend_atr", "XRP-USD", 1)]


def test_position_open_then_close_updates_the_same_row(db_path):
    store = ShadowResultsStore(db_path)
    position = _position()
    row_id = store.record_position_open("A_trend_atr", position)

    position.close(Decimal("1.05"), time.time() + 60, VirtualExitReason.TAKE_PROFIT_NET)
    store.record_position_close(row_id, position)

    rows = store.fetch_closed_positions(variant="A_trend_atr")
    store.close()

    assert len(rows) == 1
    # status column (last field) must read CLOSED, not still OPEN.
    assert rows[0][-1] == "CLOSED"


def test_state_survives_process_restart_simulated_by_new_store_instance(db_path):
    """Simulates a shadow-process restart: a brand-new ShadowResultsStore
    pointed at the same file must see everything the previous instance
    wrote, with no double-write and no data loss."""
    store1 = ShadowResultsStore(db_path)
    position = _position()
    row_id = store1.record_position_open("B_grid_suitability", position)
    store1.close()  # simulate process exit

    # "Restart": fresh object, same file.
    store2 = ShadowResultsStore(db_path)
    position.close(Decimal("1.05"), time.time() + 60, VirtualExitReason.STOP_LOSS)
    store2.record_position_close(row_id, position)

    closed = store2.fetch_closed_positions(variant="B_grid_suitability")
    store2.close()

    assert len(closed) == 1


def test_variant_filter_does_not_leak_between_variants(db_path):
    store = ShadowResultsStore(db_path)
    pos_a = _position()
    pos_b = _position()
    row_a = store.record_position_open("A_trend_atr", pos_a)
    row_b = store.record_position_open("B_grid_suitability", pos_b)
    pos_a.close(Decimal("1.05"), time.time(), VirtualExitReason.TAKE_PROFIT_NET)
    pos_b.close(Decimal("0.95"), time.time(), VirtualExitReason.STOP_LOSS)
    store.record_position_close(row_a, pos_a)
    store.record_position_close(row_b, pos_b)

    only_a = store.fetch_closed_positions(variant="A_trend_atr")
    only_b = store.fetch_closed_positions(variant="B_grid_suitability")
    store.close()

    assert len(only_a) == 1 and only_a[0][1] == "A_trend_atr"
    assert len(only_b) == 1 and only_b[0][1] == "B_grid_suitability"
