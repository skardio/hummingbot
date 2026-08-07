"""
Safety guard tests for the momentum signal service.

These tests are designed to FAIL if any forbidden symbol is ever imported
or referenced in the new signals/reporters/services modules.  They use AST
analysis so they do NOT import the modules at runtime — the modules can be
empty stubs and the tests still run correctly.

Forbidden symbols are drawn directly from the patch-plan contract:
docs/MOMENTUM_SIGNAL_SERVICE_PATCHPLAN.md § 6 "Verboden imports"
"""

import ast
import hashlib
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent  # multi_coin_grid_pro/

# All new modules that the safety contract covers.
SIGNAL_MODULES = [
    REPO_ROOT / "signals" / "momentum_config.py",
    REPO_ROOT / "signals" / "momentum_models.py",
    REPO_ROOT / "signals" / "momentum_indicators.py",
    REPO_ROOT / "signals" / "momentum_market_data.py",
    REPO_ROOT / "signals" / "momentum_signal_scorer.py",
    REPO_ROOT / "signals" / "momentum_filters.py",
    REPO_ROOT / "signals" / "grid_position_reader.py",
    REPO_ROOT / "signals" / "blacklist_reader.py",
    REPO_ROOT / "signals" / "momentum_signal_store.py",
    REPO_ROOT / "reporters" / "momentum_signal_reporter.py",
    REPO_ROOT / "services" / "momentum_signal_service.py",
]

FORBIDDEN_SYMBOLS = [
    "CreateExecutorAction",
    "StopExecutorAction",
    "GridExecutorConfig",
    "TripleBarrierConfig",
    "EntryGateway",
    "BudgetAllocator",
    "MomentumSleeveManager",
    "MomentumPosition",
    "MultiCoinGridController",
    "MultiCoinGridControllerConfig",
    "CooldownStore",
    "GlobalRiskManager",
]

FORBIDDEN_CALL_PATTERNS = [
    ".buy(",
    ".sell(",
    ".cancel(",
    "connector.buy",
    "connector.sell",
    "connector.cancel",
]

GRID_DB_NAMES = [
    "multi_coin_grid_v2.sqlite",
    "multi_coin_grid_v2_usd.sqlite",
    "spot_grid_bitget.sqlite",
    "spot_grid_okx.sqlite",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _existing_modules() -> list[Path]:
    """Return only the modules that already exist on disk."""
    return [p for p in SIGNAL_MODULES if p.exists()]


def _ast_names(source: str) -> set[str]:
    """Walk an AST and collect every Name and attribute identifier used."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                if alias.asname:
                    names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.name)
                if alias.asname:
                    names.add(alias.asname)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


# ---------------------------------------------------------------------------
# Test: no forbidden imports / symbol references
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:
    """AST-scan: geen verboden symbols in nieuwe modules."""

    @pytest.mark.parametrize("module_path", SIGNAL_MODULES, ids=lambda p: p.name)
    def test_no_forbidden_symbol(self, module_path: Path) -> None:
        if not module_path.exists():
            pytest.skip(f"{module_path.name} not yet created (expected during step-by-step build)")

        source = module_path.read_text()
        names_in_file = _ast_names(source)

        violations = [sym for sym in FORBIDDEN_SYMBOLS if sym in names_in_file]
        assert not violations, (
            f"{module_path.name} references forbidden symbol(s): {violations}\n"
            "See patchplan §6 for the full forbidden-import list."
        )

    @pytest.mark.parametrize("module_path", SIGNAL_MODULES, ids=lambda p: p.name)
    def test_no_buy_sell_cancel_text(self, module_path: Path) -> None:
        if not module_path.exists():
            pytest.skip(f"{module_path.name} not yet created")

        source = module_path.read_text()
        violations = [pat for pat in FORBIDDEN_CALL_PATTERNS if pat in source]
        assert not violations, (
            f"{module_path.name} contains forbidden call pattern(s): {violations}"
        )


# ---------------------------------------------------------------------------
# Test: signal store must not accept grid DB paths
# ---------------------------------------------------------------------------

class TestSignalStorePathGuard:
    """
    Before SignalStore exists this test is skipped.
    Once it exists it must reject every known grid-DB filename.
    """

    def _import_signal_store(self):
        store_path = REPO_ROOT / "signals" / "momentum_signal_store.py"
        if not store_path.exists():
            pytest.skip("momentum_signal_store.py not yet created")
        # Import only when the module exists
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "momentum_signal_store", store_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.parametrize("grid_db_name", GRID_DB_NAMES)
    def test_grid_db_path_rejected(self, grid_db_name: str) -> None:
        mod = self._import_signal_store()
        SignalStore = getattr(mod, "SignalStore", None)
        if SignalStore is None:
            pytest.skip("SignalStore class not yet defined")

        with pytest.raises((ValueError, AssertionError)):
            SignalStore(db_path=f"data/{grid_db_name}")


# ---------------------------------------------------------------------------
# Test: existing grid DB must not be modified after read
# ---------------------------------------------------------------------------

class TestGridDbImmutability:
    """
    Once GridPositionReader exists, verify that opening and querying
    the grid DB leaves the file byte-for-byte identical.
    Uses a temp copy so the real bot DB is never touched.
    """

    def _make_minimal_grid_db(self, path: Path) -> None:
        """Create a minimal Executors table matching production schema."""
        conn = sqlite3.connect(str(path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Executors (
                id TEXT PRIMARY KEY,
                timestamp FLOAT NOT NULL,
                type TEXT NOT NULL,
                close_type INTEGER,
                close_timestamp BIGINT,
                status INTEGER NOT NULL,
                config JSON NOT NULL,
                net_pnl_pct FLOAT NOT NULL DEFAULT 0,
                net_pnl_quote FLOAT NOT NULL DEFAULT 0,
                cum_fees_quote FLOAT NOT NULL DEFAULT 0,
                filled_amount_quote FLOAT NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 0,
                is_trading BOOLEAN NOT NULL DEFAULT 0,
                custom_info JSON NOT NULL DEFAULT '{}',
                controller_id TEXT
            )
        """)
        conn.execute(
            "INSERT INTO Executors (id, timestamp, type, status, config, is_active, is_trading, "
            "net_pnl_pct, net_pnl_quote, cum_fees_quote, filled_amount_quote, custom_info) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("e1", 1.0, "GridExecutor", 1,
             '{"trading_pair": "BTC-USD"}', 1, 1, 0, 0, 0, 0, "{}"),
        )
        conn.execute(
            "INSERT INTO Executors (id, timestamp, type, status, config, is_active, is_trading, "
            "net_pnl_pct, net_pnl_quote, cum_fees_quote, filled_amount_quote, custom_info) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("e2", 2.0, "GridExecutor", 2,
             '{"trading_pair": "ETH-USD"}', 0, 0, 0, 0, 0, 0, "{}"),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _md5(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _import_reader(self):
        reader_path = REPO_ROOT / "signals" / "grid_position_reader.py"
        if not reader_path.exists():
            pytest.skip("grid_position_reader.py not yet created")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "grid_position_reader", reader_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_grid_db_checksum_unchanged(self, tmp_path: Path) -> None:
        mod = self._import_reader()
        GridPositionReader = getattr(mod, "GridPositionReader", None)
        if GridPositionReader is None:
            pytest.skip("GridPositionReader class not yet defined")

        db_path = tmp_path / "test_grid.sqlite"
        self._make_minimal_grid_db(db_path)
        checksum_before = self._md5(db_path)

        reader = GridPositionReader(db_path=str(db_path))
        reader.get_active_pairs()

        assert self._md5(db_path) == checksum_before, (
            "GridPositionReader modified the grid database — this is a safety violation!"
        )

    def test_readonly_uri_rejects_write(self, tmp_path: Path) -> None:
        mod = self._import_reader()
        GridPositionReader = getattr(mod, "GridPositionReader", None)
        if GridPositionReader is None:
            pytest.skip("GridPositionReader class not yet defined")

        db_path = tmp_path / "test_grid.sqlite"
        self._make_minimal_grid_db(db_path)

        reader = GridPositionReader(db_path=str(db_path))
        # The connection must be opened read-only: any write must fail.
        with pytest.raises(Exception):
            reader._conn.execute(
                "INSERT INTO Executors (id, timestamp, type, status, config, "
                "net_pnl_pct, net_pnl_quote, cum_fees_quote, filled_amount_quote, "
                "is_active, is_trading, custom_info) "
                "VALUES ('x',1,'T',1,'{}',0,0,0,0,0,0,'{}')"
            )
            reader._conn.commit()


# ---------------------------------------------------------------------------
# Test: ServiceConfig mode guard (once momentum_config.py exists)
# ---------------------------------------------------------------------------

class TestServiceConfigModeGuard:

    def _import_config(self):
        cfg_path = REPO_ROOT / "signals" / "momentum_config.py"
        if not cfg_path.exists():
            pytest.skip("momentum_config.py not yet created")
        import importlib.util
        spec = importlib.util.spec_from_file_location("momentum_config", cfg_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.parametrize("bad_mode", ["paper", "live", "detect_only", "dry_run", ""])
    def test_bad_mode_raises(self, bad_mode: str) -> None:
        mod = self._import_config()
        ServiceConfig = getattr(mod, "ServiceConfig", None)
        if ServiceConfig is None:
            pytest.skip("ServiceConfig not yet defined")

        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode=bad_mode)

    def test_allow_order_creation_true_raises(self) -> None:
        mod = self._import_config()
        ServiceConfig = getattr(mod, "ServiceConfig", None)
        if ServiceConfig is None:
            pytest.skip("ServiceConfig not yet defined")

        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only",
                          safety={"allow_order_creation": True})


# ---------------------------------------------------------------------------
# Test: score normalization (once momentum_signal_scorer.py exists)
# ---------------------------------------------------------------------------

class TestScoreNormalization:

    def _import_scorer(self):
        scorer_path = REPO_ROOT / "signals" / "momentum_signal_scorer.py"
        if not scorer_path.exists():
            pytest.skip("momentum_signal_scorer.py not yet created")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "momentum_signal_scorer", scorer_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_score_never_exceeds_1(self) -> None:
        mod = self._import_scorer()
        SignalScorer = getattr(mod, "SignalScorer", None)
        if SignalScorer is None:
            pytest.skip("SignalScorer not yet defined")

        scorer = SignalScorer()
        # Feed an obviously high-momentum candidate
        result = scorer.score_raw(
            trend_1h=5.0, trend_4h=12.0, volume_expansion=8.0,
            relative_strength=3.0, spread_pct=0.05,
            rsi=55.0, wick_risk=0.1, regime="BULL",
        )
        assert result <= 1.0, f"Score {result} exceeds 1.0 — normalization broken"

    def test_score_non_negative(self) -> None:
        mod = self._import_scorer()
        SignalScorer = getattr(mod, "SignalScorer", None)
        if SignalScorer is None:
            pytest.skip("SignalScorer not yet defined")

        scorer = SignalScorer()
        result = scorer.score_raw(
            trend_1h=0.0, trend_4h=0.0, volume_expansion=0.0,
            relative_strength=0.0, spread_pct=1.0,
            rsi=90.0, wick_risk=1.0, regime="BEAR",
        )
        assert result >= 0.0, f"Score {result} is negative — clamping broken"

    def test_score_deterministic(self) -> None:
        mod = self._import_scorer()
        SignalScorer = getattr(mod, "SignalScorer", None)
        if SignalScorer is None:
            pytest.skip("SignalScorer not yet defined")

        scorer = SignalScorer()
        kwargs = dict(
            trend_1h=3.0, trend_4h=8.0, volume_expansion=4.0,
            relative_strength=2.0, spread_pct=0.15,
            rsi=60.0, wick_risk=0.2, regime="BULL",
        )
        assert scorer.score_raw(**kwargs) == scorer.score_raw(**kwargs)
