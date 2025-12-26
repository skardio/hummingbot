"""
Pytest configuration for multi_coin_grid_pro tests

Handles:
- Ignoring tests that require hummingbot when it's not available
- Common fixtures
- Test markers
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def hummingbot_available():
    """Check if hummingbot modules are importable"""
    try:
        pass

        return True
    except (ImportError, KeyError, ModuleNotFoundError):
        return False


# =============================================================================
# IGNORE TEST FILES THAT REQUIRE HUMMINGBOT
# =============================================================================
# This runs BEFORE pytest collects tests, preventing import errors

if not hummingbot_available():
    # List of test files/directories that require hummingbot
    # Keep working tests (market_regime, monitoring, paper_trading, etc)
    collect_ignore = [
        "unit/test_coin_discovery.py",
        "unit/test_controller_methods.py",
        "unit/test_controller_rotation.py",
        "unit/test_futures_grid_bitget_strategy.py",
        "unit/test_grid_executor_balance_check.py",
        "unit/test_multi_coin_grid_controller.py",
        "unit/test_multi_coin_grid_controller_extended.py",
        "unit/test_multi_coin_grid_v2_strategy.py",
        "unit/test_multi_coin_simultaneous.py",
        "unit/test_multi_timeframe_trends.py",
        "unit/test_phase1_slippage_protection.py",
        "unit/test_pro_exit_system.py",
        "unit/test_trend_calculator.py",
        "unit/test_warmup_override.py",
        "integration/",
        "stress/",
        "backtest/",
        "test_bot_ready.py",
    ]
else:
    collect_ignore = []


# Register markers
def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "requires_hummingbot: mark test as requiring full hummingbot environment"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_ticker_data():
    """Sample Kraken ticker data for testing"""
    return {
        "SOLEUR": {
            "a": ["100.0", "1", "1.0"],
            "b": ["99.9", "1", "1.0"],
            "c": ["100.0", "1.0"],
            "v": ["1000", "10000"],
            "o": "95.0"
        },
        "XXBTZEUR": {
            "a": ["50000.0", "1", "1.0"],
            "b": ["49999.0", "1", "1.0"],
            "c": ["50000.0", "1.0"],
            "v": ["100", "1000"],
            "o": "49000.0"
        }
    }


@pytest.fixture
def sample_pair_list():
    """Sample trading pairs for testing"""
    return [
        "SOL-EUR", "BTC-EUR", "ETH-EUR", "ADA-EUR", "XRP-EUR",
        "DOGE-EUR", "LINK-EUR", "DOT-EUR", "SUI-EUR", "AVAX-EUR"
    ]
