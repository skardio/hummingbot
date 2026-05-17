from multi_coin_grid_pro.observability.execution_funnel import ExecutionFunnelTracker


def test_execution_funnel_rates_and_reasons():
    tracker = ExecutionFunnelTracker(window_sec=900)

    tracker.record_tick()
    tracker.record_considered(4)
    tracker.record_allowed("BTC-EUR")
    tracker.record_rejected("ETH-EUR", "SmartEntry")
    tracker.record_approved("BTC-EUR")
    tracker.record_started("BTC-EUR")

    summary = tracker.get_summary()

    assert summary["ticks"] == 1
    assert summary["considered"] == 4
    assert summary["allowed"] == 1
    assert summary["rejected"] == 1
    assert summary["approved"] == 1
    assert summary["started"] == 1
    assert summary["allow_rate_pct"] == 50.0
    assert summary["start_rate_pct"] == 100.0
    assert summary["reject_reasons"] == {"SmartEntry": 1}


def test_execution_funnel_empty_rates_are_zero():
    tracker = ExecutionFunnelTracker(window_sec=900)

    summary = tracker.get_summary()

    assert summary["allow_rate_pct"] == 0.0
    assert summary["start_rate_pct"] == 0.0
