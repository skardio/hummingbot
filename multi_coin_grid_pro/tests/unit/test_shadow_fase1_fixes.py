"""Regression tests for the Fase-1 validation fixes to the A/B shadow runner:

1. Variant A must use the real 70% trend + 30% ATR blend (the exact
   production ranking signal), not silently fall back to a plain trend
   sort because `atr_selection_config` was omitted.
2. Each variant must exclude its own currently-open symbols from its next
   selection call.
3. A results-store row left `OPEN` by a crashed/killed previous process must
   be marked ORPHANED_ON_RESTART on the next startup, never silently
   resumed and never silently dropped.
4. The empirical-fee PnL annotation must be a full, separate net-PnL number,
   not just a fee delta, so nobody has to recompute it by hand (and nobody
   can mistake the config-assumed net_pnl_quote for the real-fee outcome).
"""
import time
from decimal import Decimal

from multi_coin_grid_pro.shadow.ab_shadow_runner import LIVE_MIRRORED_DEFAULTS
from multi_coin_grid_pro.shadow.results_store import ShadowResultsStore
from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualExitReason, VirtualGridPosition
from multi_coin_grid_pro.utils.trend_calculator import CandleData, CoinTrend, TrendCalculator


def _make_trend(symbol: str, deltas, consensus_trend_pct: float, volatile: bool = False) -> CoinTrend:
    candles, price_history = [], []
    base = 100.0
    now = time.time()
    for i, delta in enumerate(deltas):
        base += delta
        ts = now - (len(deltas) - i) * 300
        spread = Decimal("3.0") if volatile else Decimal("0.5")
        candles.append(CandleData(
            timestamp=ts, open=Decimal(str(base)), high=Decimal(str(base)) + spread,
            low=Decimal(str(base)) - spread, close=Decimal(str(base)), volume=Decimal("1000"),
        ))
        price_history.append({"price": base, "timestamp": ts})
    return CoinTrend(
        symbol=symbol, current_price=Decimal(str(base)),
        consensus_trend_pct=consensus_trend_pct, candles=candles, price_history=price_history,
    )


def _make_calculator(trends: dict) -> TrendCalculator:
    tc = TrendCalculator.__new__(TrendCalculator)
    tc.trends = trends
    tc.connector = type("FakeConnector", (), {"name": "kraken"})()
    tc._permanently_failed_symbols = set()
    return tc


def test_atr_selection_config_mirrors_the_production_values_exactly():
    """Pin the exact numbers reverse-engineered from production logs
    ("required_atr_pct=0.800% soft_threshold_pct=0.400%") — a silent drift
    here would quietly make variant A diverge from the real live ranking
    again without any test failing elsewhere."""
    cfg = LIVE_MIRRORED_DEFAULTS["atr_selection_config"]
    assert cfg["enabled"] is True
    assert cfg["required_atr_pct"] == 0.80
    assert cfg["prefilter_ratio"] == 0.50
    assert cfg["use_as_ranking_signal"] is True


def test_without_atr_selection_config_ranking_silently_degrades_to_plain_trend_sort():
    """Characterises the exact bug that was fixed: this is what happens if
    atr_selection_config is accidentally omitted again in the future."""
    tc = _make_calculator({
        "LOWATR-USD": _make_trend("LOWATR-USD", [0.05] * 60, consensus_trend_pct=3.0, volatile=False),
        "HIGHATR-USD": _make_trend("HIGHATR-USD", [0.05] * 60, consensus_trend_pct=2.9, volatile=True),
    })
    result = tc.get_top_n_coins(n=2, min_trend_pct=0.0, grid_scorer=None)  # bug reproduced: no atr_selection_config
    assert result[0] == "LOWATR-USD", "without the fix, pure trend sort wins regardless of ATR"


def test_with_atr_selection_config_the_real_70_30_blend_is_used():
    """The fixed call path: passing the mirrored atr_selection_config makes
    the higher-ATR coin win even with marginally lower raw trend — matching
    the real production ranking signal."""
    tc = _make_calculator({
        "LOWATR-USD": _make_trend("LOWATR-USD", [0.05] * 60, consensus_trend_pct=3.0, volatile=False),
        "HIGHATR-USD": _make_trend("HIGHATR-USD", [0.05] * 60, consensus_trend_pct=2.9, volatile=True),
    })
    result = tc.get_top_n_coins(
        n=2, min_trend_pct=0.0, grid_scorer=None,
        atr_selection_config=LIVE_MIRRORED_DEFAULTS["atr_selection_config"],
    )
    assert result[0] == "HIGHATR-USD", "the fixed call must reproduce the real 70/30 trend+ATR blend"


def test_each_variant_excludes_its_own_open_symbols_from_the_next_selection():
    tc = _make_calculator({
        "A-USD": _make_trend("A-USD", [0.3] * 60, consensus_trend_pct=10.0),
        "B-USD": _make_trend("B-USD", [0.2] * 60, consensus_trend_pct=5.0),
    })
    without_exclusion = tc.get_top_n_coins(n=2, min_trend_pct=0.0, grid_scorer=None)
    assert without_exclusion[0] == "A-USD"

    with_a_excluded = tc.get_top_n_coins(n=2, min_trend_pct=0.0, grid_scorer=None, exclude_coins=["A-USD"])
    assert "A-USD" not in with_a_excluded
    assert with_a_excluded[0] == "B-USD"


def test_restart_marks_leftover_open_rows_as_orphaned_not_resumed_not_dropped(tmp_path):
    db_path = str(tmp_path / "shadow.db")
    store = ShadowResultsStore(db_path)
    position = VirtualGridPosition(
        symbol="XRP-USD", notional_quote=Decimal("100"), stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), max_hold_seconds=3600.0,
        limit_price=Decimal("1.0"), created_at=time.time(),
    )
    store.record_position_open("A_trend_atr", position)  # never closed -> simulates a crash
    store.close()

    # "Restart": fresh store instance, same file.
    store2 = ShadowResultsStore(db_path)
    orphaned_count = store2.mark_all_open_as_orphaned()
    still_open = store2._conn.execute("SELECT COUNT(*) FROM shadow_positions WHERE status='OPEN'").fetchone()[0]
    orphaned_rows = store2._conn.execute(
        "SELECT COUNT(*) FROM shadow_positions WHERE status='ORPHANED_ON_RESTART'"
    ).fetchone()[0]
    store2.close()

    assert orphaned_count == 1
    assert still_open == 0, "no row may be left silently counted as still-open after a restart"
    assert orphaned_rows == 1, "the orphan must remain visible/queryable, not deleted"


def test_orphaned_rows_are_excluded_from_closed_position_queries(tmp_path):
    db_path = str(tmp_path / "shadow.db")
    store = ShadowResultsStore(db_path)
    position = VirtualGridPosition(
        symbol="XRP-USD", notional_quote=Decimal("100"), stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), max_hold_seconds=3600.0,
        limit_price=Decimal("1.0"), created_at=time.time(),
    )
    store.record_position_open("A_trend_atr", position)
    store.mark_all_open_as_orphaned()

    closed = store.fetch_closed_positions(variant="A_trend_atr")
    store.close()

    assert closed == [], "an orphaned (never actually closed) position must not appear as a realised CLOSED result"


def test_empirical_fee_annotation_includes_a_full_secondary_net_pnl_not_just_a_fee_delta():
    """Guards against quietly reading the config-assumed net_pnl_quote as if
    it were the real-fee outcome: a full, separately-computed net PnL at the
    empirical rate must exist and must differ from the config-assumed one
    whenever the two fee assumptions differ."""
    position = VirtualGridPosition(
        symbol="XRP-USD", notional_quote=Decimal("100"), stop_loss_pct=Decimal("0.015"),
        required_take_profit_net_pct=Decimal("0.02"), maker_fee_pct=Decimal("0.0020"),
        taker_fee_pct=Decimal("0.0035"), max_hold_seconds=3600.0,
        limit_price=Decimal("100"), created_at=time.time(),
    )
    now = time.time()
    position.try_fill_entry(Decimal("100"), now)
    position.try_fill_entry(Decimal("100"), now + 1)
    position.close(Decimal("103"), now + 60, VirtualExitReason.TAKE_PROFIT_NET)

    assert position.annotated_net_pnl_quote_at_empirical_rate is not None
    assert position.annotated_net_pnl_quote_at_empirical_rate != position.net_pnl_quote

    # Sanity check the formula directly: higher empirical fee (0.29% vs
    # 0.20%/0.35% blended) on this profitable trade must lower net PnL.
    assert position.annotated_net_pnl_quote_at_empirical_rate < position.gross_pnl_quote
