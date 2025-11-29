"""
Unit tests for backtesting engine
"""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from multi_coin_grid_pro.tests.backtest.backtest_engine import BacktestEngine, BacktestResult
except ImportError:
    # Fallback for direct import
    from tests.backtest.backtest_engine import BacktestEngine, BacktestResult


class TestBacktestEngine:
    """Test backtesting engine"""

    @pytest.fixture
    def sample_historical_data(self):
        """Create sample historical price data"""
        base_time = datetime(2025, 1, 1)
        data = {}

        # XRP-EUR: starts at 1.0, goes to 1.1 (+10%)
        xrp_prices = []
        for i in range(100):
            timestamp = (base_time + timedelta(hours=i)).timestamp()
            price = Decimal("1.0") + Decimal(str(i * 0.001))  # Gradual increase
            xrp_prices.append((timestamp, price))
        data["XRP-EUR"] = xrp_prices

        # ADA-EUR: starts at 0.8, goes to 0.85 (+6.25%)
        ada_prices = []
        for i in range(100):
            timestamp = (base_time + timedelta(hours=i)).timestamp()
            price = Decimal("0.8") + Decimal(str(i * 0.0005))
            ada_prices.append((timestamp, price))
        data["ADA-EUR"] = ada_prices

        return data

    @pytest.fixture
    def config(self):
        """Test configuration"""
        return {
            "maker_fee_pct": 0.0016,  # 0.16%
            "total_amount_quote": 120,
        }

    def test_backtest_initialization(self, sample_historical_data, config):
        """Test backtest engine initialization"""
        engine = BacktestEngine(
            initial_capital=Decimal("120"),
            config=config,
            historical_data=sample_historical_data
        )

        assert engine.initial_capital == Decimal("120")
        assert len(engine.historical_data) == 2

    def test_get_price_at_time(self, sample_historical_data, config):
        """Test price retrieval at specific time"""
        engine = BacktestEngine(
            initial_capital=Decimal("120"),
            config=config,
            historical_data=sample_historical_data
        )

        target_time = datetime(2025, 1, 1, 12, 0, 0)
        price = engine._get_price_at_time("XRP-EUR", target_time)

        assert price is not None
        assert price > Decimal("0")

    def test_backtest_run(self, sample_historical_data, config):
        """Test full backtest run"""
        engine = BacktestEngine(
            initial_capital=Decimal("120"),
            config=config,
            historical_data=sample_historical_data
        )

        start_date = datetime(2025, 1, 1)
        end_date = datetime(2025, 1, 2)

        result = engine.run(start_date, end_date, interval_minutes=60)

        assert isinstance(result, BacktestResult)
        assert result.start_date == start_date
        assert result.end_date == end_date
        assert result.initial_capital == Decimal("120")
        assert result.num_trades >= 0

    def test_calculate_max_drawdown(self, sample_historical_data, config):
        """Test max drawdown calculation"""
        engine = BacktestEngine(
            initial_capital=Decimal("120"),
            config=config,
            historical_data=sample_historical_data
        )

        # Add some equity curve data
        base_time = datetime(2025, 1, 1).timestamp()
        engine.equity_curve = [
            (base_time, Decimal("120")),
            (base_time + 3600, Decimal("125")),  # Peak
            (base_time + 7200, Decimal("115")),  # Drop
            (base_time + 10800, Decimal("130")),  # Recovery
        ]

        max_dd = engine._calculate_max_drawdown()
        assert max_dd >= 0
        assert max_dd <= 100  # Should be percentage
