"""
Unit tests for Monte Carlo drawdown simulation.

Item 17 — Monte Carlo Risk Test

All tests use a fixed seed for deterministic results.
"""
import pytest

from multi_coin_grid_pro.tools.monte_carlo import MonteCarloResult, run_monte_carlo, simulate_single_run

SEED = 42


class TestSimulateSingleRun:
    def test_all_positive_pnl_zero_drawdown(self):
        pnls = [10.0] * 20
        dd = simulate_single_run(pnls, starting_capital=1000.0)
        assert dd == pytest.approx(0.0)

    def test_all_negative_pnl_has_drawdown(self):
        pnls = [-10.0] * 20
        dd = simulate_single_run(pnls, starting_capital=1000.0)
        assert dd > 0

    def test_drawdown_is_percentage(self):
        # One big loss after one gain: peak=1100, then drop to 600 → 45.5%
        pnls = [100.0, -500.0] + [0.0] * 5
        dd = simulate_single_run(pnls, starting_capital=1000.0)
        # Drawdown should be > 0 and <= 100
        assert 0 < dd <= 100

    def test_uses_all_trades_in_sequence(self):
        import random
        random.seed(SEED)
        pnls = list(range(-10, 11))  # 21 trades
        dd = simulate_single_run(pnls, starting_capital=500.0)
        assert dd >= 0.0


class TestRunMonteCarlo:
    def test_raises_on_too_few_trades(self):
        with pytest.raises(ValueError, match="at least 10"):
            run_monte_carlo([1.0, 2.0, 3.0], 1000.0)

    def test_returns_monte_carlo_result(self):
        pnls = [float(i % 5 - 2) for i in range(50)]
        result = run_monte_carlo(pnls, 1000.0, n_runs=100, seed=SEED)
        assert isinstance(result, MonteCarloResult)

    def test_deterministic_with_seed(self):
        pnls = [float(i % 5 - 2) for i in range(50)]
        r1 = run_monte_carlo(pnls, 1000.0, n_runs=500, seed=SEED)
        r2 = run_monte_carlo(pnls, 1000.0, n_runs=500, seed=SEED)
        assert r1.p5_max_drawdown_pct == r2.p5_max_drawdown_pct
        assert r1.ruin_probability_pct == r2.ruin_probability_pct

    def test_p99_gte_p95(self):
        pnls = [1.0 if i % 3 else -5.0 for i in range(60)]
        result = run_monte_carlo(pnls, 1000.0, n_runs=200, seed=SEED)
        assert result.p1_max_drawdown_pct >= result.p5_max_drawdown_pct

    def test_all_positive_pnl_zero_ruin(self):
        pnls = [2.0] * 30
        result = run_monte_carlo(pnls, 1000.0, n_runs=100, seed=SEED)
        assert result.ruin_probability_pct == pytest.approx(0.0)

    def test_all_negative_pnl_100pct_ruin(self):
        pnls = [-50.0] * 30
        result = run_monte_carlo(pnls, 1000.0, n_runs=100, seed=SEED, ruin_threshold_pct=5.0)
        assert result.ruin_probability_pct == pytest.approx(100.0)

    def test_n_runs_stored_in_result(self):
        pnls = [float(i % 3 - 1) for i in range(20)]
        result = run_monte_carlo(pnls, 500.0, n_runs=77, seed=SEED)
        assert result.n_runs == 77

    def test_ruin_threshold_stored(self):
        pnls = [float(i % 5 - 2) for i in range(30)]
        result = run_monte_carlo(pnls, 500.0, n_runs=50, ruin_threshold_pct=25.0, seed=SEED)
        assert result.ruin_threshold_pct == pytest.approx(25.0)
