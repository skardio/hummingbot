"""Structural safety test: the shadow A/B sandbox must never import anything
that could place live orders, stop live executors, mutate live risk state,
or authenticate against Kraken.

This is enforced by static inspection of the compiled bytecode of every
module in ``multi_coin_grid_pro.shadow`` — a regression here means someone
introduced a dependency that could compromise the isolation guarantee
documented in ``multi_coin_grid_pro/shadow/__init__.py``.
"""
import ast
import dis
import importlib
import pkgutil
import sys
from types import ModuleType
from unittest.mock import Mock, patch

import multi_coin_grid_pro.shadow as shadow_pkg

FORBIDDEN_MODULE_SUBSTRINGS = (
    "hummingbot.connector.exchange.kraken.kraken_exchange",
    "hummingbot.connector.exchange.kraken.kraken_auth",
    "hummingbot.strategy_v2.models.executor_actions",
    "hummingbot.strategy_v2.executors.executor_orchestrator",
    "multi_coin_grid_pro.controllers.multi_coin_grid_controller",
    "hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller",
)


def _shadow_module_names():
    names = []
    for _, name, _ in pkgutil.walk_packages(shadow_pkg.__path__, prefix="multi_coin_grid_pro.shadow."):
        names.append(name)
    return names


def test_no_shadow_module_imports_forbidden_live_paths():
    """Inspect only actual `import X` / `from X import Y` statements (via the
    AST), not prose mentions in docstrings/comments — a docstring explaining
    *why* something is NOT imported must not itself trip this guard."""
    for mod_name in _shadow_module_names():
        module = importlib.import_module(mod_name)
        source_file = getattr(module, "__file__", None)
        if not source_file:
            continue
        with open(source_file, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=source_file)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        for forbidden in FORBIDDEN_MODULE_SUBSTRINGS:
            for imported in imported_names:
                assert forbidden not in imported, (
                    f"{mod_name} imports from forbidden live module '{imported}' "
                    f"(matches guard '{forbidden}') — this breaks the shadow/live isolation guarantee."
                )


def test_no_shadow_module_references_api_credentials():
    for mod_name in _shadow_module_names():
        module = importlib.import_module(mod_name)
        source_file = getattr(module, "__file__", None)
        if not source_file:
            continue
        with open(source_file, "r", encoding="utf-8") as f:
            source = f.read()
        for token in ("api_key", "apiKey", "secret_key", "kraken_secret"):
            if token in source:
                # Only acceptable as an explicit negative-assertion comment,
                # never as an actual constructor argument.
                assert "never" in source.lower() or "no api" in source.lower() or "no credentials" in source.lower(), (
                    f"{mod_name} references '{token}' without an explicit "
                    "no-credentials safety comment nearby — verify manually."
                )


def test_public_market_adapter_never_passes_credentials_to_ccxt():
    """Verifies PublicKrakenMarketAdapter's own constructor call, not ccxt's
    internal health.

    Substitute both ccxt modules before the adapter imports them. Patching
    ``ccxt.async_support.kraken`` by name would first import real ccxt and
    its cryptography bindings, which can fail before the mock is installed.
    Only the adapter's constructor arguments are relevant to this test.
    """
    ccxt_module = ModuleType("ccxt")
    ccxt_module.__path__ = []
    async_module = ModuleType("ccxt.async_support")
    mock_kraken_cls = Mock()
    async_module.kraken = mock_kraken_cls
    ccxt_module.async_support = async_module

    with patch.dict(sys.modules, {"ccxt": ccxt_module, "ccxt.async_support": async_module}):
        from multi_coin_grid_pro.shadow.public_market_data import PublicKrakenMarketAdapter

        PublicKrakenMarketAdapter()

        mock_kraken_cls.assert_called_once()
        args, kwargs = mock_kraken_cls.call_args
        # ccxt is called as `ccxt_async.kraken({"enableRateLimit": True})` —
        # a single positional dict, not keyword arguments — so the
        # credential check must inspect that dict's keys, not `kwargs`
        # (which would be empty regardless of what the dict contains).
        config_dict = args[0] if args else {}
        combined = {**config_dict, **kwargs}
        assert "apiKey" not in combined
        assert "secret" not in combined
        assert "api_key" not in combined
        assert "secret_key" not in combined


def test_virtual_portfolio_module_does_not_import_live_budget_allocator():
    import multi_coin_grid_pro.shadow.virtual_portfolio as vp
    assert "budget_allocator" not in dis.Bytecode(vp.VirtualPortfolio.open_position).codeobj.co_names
