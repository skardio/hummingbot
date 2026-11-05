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


def _resolved_path(path: Path) -> Path:
    """Resolve a test path relative to the repository without creating it."""
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


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


@pytest.fixture(autouse=True)
def isolate_realised_pnl_ledger(tmp_path, monkeypatch):
    """Keep the FIX-002 ledger out of the production database during tests.

    The controller creates a RealisedPnlLedger on a fixed path under data/.
    Without isolation, tests would claim real executor ids in the live ledger -
    permanently suppressing those ids in production - and would also block each
    other, since a claim is by design one-shot.

    Only the production default is redirected. A test that passes an explicit
    path (its own tmp_path, for instance) keeps it.
    """
    import multi_coin_grid_pro.persistence.realised_pnl_ledger as ledger_module

    original_init = ledger_module.RealisedPnlLedger.__init__
    production_dir = str(Path("data"))

    def isolated_init(self, db_path=None, logger=None):
        if db_path is None or str(db_path).startswith(production_dir):
            db_path = str(tmp_path / "test_realised_pnl_ledger.db")
        original_init(self, db_path, logger)

    monkeypatch.setattr(ledger_module.RealisedPnlLedger, "__init__", isolated_init)
    yield


@pytest.fixture(autouse=True)
def isolate_operational_test_artifacts(tmp_path, monkeypatch):
    """Redirect production-default persistence and event paths during tests.

    Controller tests construct real persistence helpers. Without this guard,
    ``_create_grid_action`` writes synthetic entry prices to ``data/`` and
    enabled observability creates empty JSONL files under ``logs/``. Explicit
    temporary paths supplied by a test remain unchanged.
    """
    import multi_coin_grid_pro.observability.event_logger as event_logger_module
    import multi_coin_grid_pro.persistence.entry_price_store as entry_price_module

    production_data_dir = (project_root / "data").resolve()
    production_logs_dir = (project_root / "logs").resolve()

    original_entry_init = entry_price_module.EntryPriceStore.__init__

    def isolated_entry_init(self, db_path=None, logger=None):
        requested = Path(db_path or entry_price_module.EntryPriceStore.DEFAULT_DB_PATH)
        resolved = _resolved_path(requested)
        if _is_below(resolved, production_data_dir):
            db_path = str(tmp_path / "operational-data" / resolved.name)
        original_entry_init(self, db_path, logger)

    original_event_init = event_logger_module.EventLogger.__init__

    def isolated_event_init(
        self,
        enabled=False,
        output_dir="logs/events",
        buffer_size=100,
        config_hash=None,
    ):
        requested = Path(output_dir)
        resolved = _resolved_path(requested)
        if _is_below(resolved, production_logs_dir):
            relative = resolved.relative_to(production_logs_dir)
            output_dir = str(tmp_path / "operational-logs" / relative)
        original_event_init(
            self,
            enabled=enabled,
            output_dir=output_dir,
            buffer_size=buffer_size,
            config_hash=config_hash,
        )

    monkeypatch.setattr(entry_price_module.EntryPriceStore, "__init__", isolated_entry_init)
    monkeypatch.setattr(event_logger_module.EventLogger, "__init__", isolated_event_init)
    yield
