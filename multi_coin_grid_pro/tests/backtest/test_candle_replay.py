from decimal import Decimal

from multi_coin_grid_pro.backtesting.replay import (
    Candle,
    CandleReplay,
    OrderIntent,
    ReplayAssumptions,
    compare_scenarios,
    split_research_validation,
)

D = Decimal


def assumptions(**overrides):
    values = {
        "maker_fee_rate": D("0.001"),
        "taker_fee_rate": D("0.002"),
        "spread_rate": D("0.002"),
    }
    values.update(overrides)
    return ReplayAssumptions(**values)


def candle(ts, open_, high, low, close, volume=None):
    return Candle(ts, D(open_), D(high), D(low), D(close), None if volume is None else D(volume))


def order(order_id, placed, side, price, amount, order_type="LIMIT_MAKER"):
    return OrderIntent(order_id, placed, side, D(price), D(amount), order_type)


def test_marketable_post_only_is_cancelled_without_fill_or_inventory():
    replay = CandleReplay("BTC", "USD", D("1000"), assumptions())

    result = replay.run(
        [candle(10, "100", "105", "95", "101")],
        [order("crossing-buy", 0, "BUY", "101", "1")],
    )

    assert result.cancelled_order_ids == ["crossing-buy"]
    assert result.report.fill_count == 0
    assert result.report.inventory_base == D("0")


def test_conservative_touch_requires_penetration():
    replay = CandleReplay("BTC", "USD", D("1000"), assumptions())

    result = replay.run(
        [candle(10, "100", "105", "90", "100")],
        [order("touch-only", 0, "BUY", "90", "1")],
    )

    assert result.report.fill_count == 0
    assert result.open_order_ids == ["touch-only"]


def test_partial_fill_can_continue_across_candles():
    replay = CandleReplay(
        "BTC",
        "USD",
        D("1000"),
        assumptions(max_fill_fraction_per_candle=D("0.5")),
    )

    result = replay.run(
        [
            candle(10, "100", "101", "89", "95"),
            candle(20, "95", "98", "88", "96"),
        ],
        [order("partial", 0, "BUY", "90", "1")],
    )

    assert result.report.fill_count == 2
    assert result.report.inventory_base == D("0.75")
    assert result.open_order_ids == ["partial"]


def test_last_tick_fill_is_included_in_equity_and_inventory():
    replay = CandleReplay("BTC", "USD", D("1000"), assumptions())

    result = replay.run(
        [
            candle(10, "100", "101", "95", "100"),
            candle(20, "100", "102", "89", "95"),
        ],
        [order("last-tick", 10, "BUY", "90", "1")],
    )

    assert result.filled_order_ids == ["last-tick"]
    assert result.report.inventory_base == D("1")
    assert result.report.total_equity_quote == D("1004.910")


def test_market_order_uses_taker_fee_and_slippage():
    replay = CandleReplay(
        "BTC",
        "USD",
        D("1000"),
        assumptions(market_slippage_rate=D("0.01")),
    )

    result = replay.run(
        [candle(10, "100", "105", "95", "100")],
        [order("market-buy", 0, "BUY", "100", "1", order_type="MARKET")],
    )

    assert result.report.inventory_base == D("1")
    assert result.report.cash_quote == D("898.798")
    assert result.accuracy_level == "A_CONSERVATIVE_CANDLE"
    assert result.limitations


def test_order_created_on_candle_is_not_filled_using_same_candle():
    replay = CandleReplay("BTC", "USD", D("1000"), assumptions())

    result = replay.run(
        [candle(10, "100", "105", "80", "90")],
        [order("no-lookahead", 10, "BUY", "85", "1")],
    )

    assert result.report.fill_count == 0


def test_research_validation_split_is_chronological_and_non_overlapping():
    candles = [
        candle(10, "100", "101", "99", "100"),
        candle(20, "100", "101", "99", "100"),
        candle(30, "100", "101", "99", "100"),
    ]

    research, validation = split_research_validation(candles, 20)

    assert [item.timestamp for item in research] == [10]
    assert [item.timestamp for item in validation] == [20, 30]


def test_scenarios_share_market_data_capital_and_cost_model():
    candles = [candle(10, "100", "105", "89", "100")]
    results = compare_scenarios(
        candles=candles,
        scenario_orders={
            "baseline": [order("buy-a", 0, "BUY", "90", "1")],
            "less_accumulation": [],
        },
        base_asset="BTC",
        quote_asset="USD",
        initial_cash_quote=D("1000"),
        assumptions=assumptions(),
    )

    assert results["baseline"].report.initial_cash_quote == D("1000")
    assert results["less_accumulation"].report.initial_cash_quote == D("1000")
    assert len(results["baseline"].equity_curve) == len(candles)
