"""Tests for .github/scripts/check_trading_strategy_docs.py."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "check_trading_strategy_docs.py"
spec = importlib.util.spec_from_file_location("check_trading_strategy_docs", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

DOC = "docs/TRADING_STRATEGY.md"
CONTROLLER = "multi_coin_grid_pro/controllers/multi_coin_grid_controller.py"
REASON = "pure rename of private helpers, no behaviour change"


@pytest.mark.parametrize("path", [
    CONTROLLER,
    "multi_coin_grid_pro/core/global_risk_manager.py",
    "multi_coin_grid_pro/risk/professional_risk_manager.py",
    "multi_coin_grid_pro/utils/trend_calculator.py",
    "hummingbot/strategy_v2/executors/grid_executor/grid_executor.py",
    "multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml",
    "multi_coin_grid_pro/spot_okx/config/spot_grid_okx.yaml",
    "multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml",
])
def test_strategy_files_are_relevant(path):
    assert checker.is_strategy_relevant(path)


@pytest.mark.parametrize("path", [
    DOC,
    "README.md",
    "multi_coin_grid_pro/tests/unit/test_pre_deploy_risk_safety.py",
    "test/hummingbot/strategy_v2/executors/grid_executor/test_grid_executor_base_fee_realized_pnl.py",
    "multi_coin_grid_pro/config/Oud/config.dev.yaml",
    "multi_coin_grid_pro/controllers/notes.md",
    "multi_coin_grid_pro/utils/log_archiver.py",
    "multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml",
    ".github/workflows/strategy-docs.yml",
])
def test_other_files_are_not_relevant(path):
    assert not checker.is_strategy_relevant(path)


class TestEvaluate:
    def test_no_relevant_change_passes(self):
        assert checker.evaluate(["README.md", "multi_coin_grid_pro/tests/unit/test_x.py"]).status == "ok"

    def test_relevant_change_with_doc_passes(self):
        assert checker.evaluate([CONTROLLER, DOC]).status == "ok"

    def test_relevant_yaml_without_doc_fails(self):
        result = checker.evaluate(["multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml"])
        assert result.status == "fail"
        assert result.relevant == ["multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml"]

    def test_relevant_code_without_doc_fails(self):
        assert checker.evaluate([CONTROLLER]).status == "fail"

    def test_trailer_exception_skips_with_reason(self):
        result = checker.evaluate([CONTROLLER], [f"refactor\n\nStrategy-Docs: not-needed - {REASON}\n"])
        assert (result.status, result.reason) == ("skip", REASON)

    def test_trailer_is_case_insensitive(self):
        message = f"x\n\nstrategy-docs: NOT-NEEDED - {REASON}"
        assert checker.evaluate([CONTROLLER], [message]).status == "skip"

    def test_short_reason_is_rejected(self):
        assert checker.evaluate([CONTROLLER], ["x\n\nStrategy-Docs: not-needed - refactor"]).status == "fail"

    def test_missing_reason_is_rejected(self):
        assert checker.evaluate([CONTROLLER], ["x\n\nStrategy-Docs: not-needed"]).status == "fail"

    def test_environment_exception(self):
        assert checker.evaluate([CONTROLLER], [], REASON).status == "skip"
        assert checker.evaluate([CONTROLLER], [], "short").status == "fail"

    def test_windows_paths_are_normalised(self):
        assert checker.evaluate([CONTROLLER.replace("/", "\\")]).status == "fail"


class TestMain:
    def test_exit_codes(self, capsys):
        assert checker.main(["--files", CONTROLLER]) == 1
        assert "TRADING_STRATEGY.md" in capsys.readouterr().err
        assert checker.main(["--files", CONTROLLER, DOC]) == 0
        assert checker.main(["--files", "README.md"]) == 0
        assert checker.main(["--files", CONTROLLER, "--message", f"Strategy-Docs: not-needed - {REASON}"]) == 0
        assert REASON in capsys.readouterr().out

    def test_commit_msg_file_is_read(self, tmp_path):
        message = tmp_path / "COMMIT_EDITMSG"
        message.write_text(f"refactor\n\nStrategy-Docs: not-needed - {REASON}\n")
        assert checker.main([str(message), "--files", CONTROLLER]) == 0
        message.write_text("refactor only\n")
        assert checker.main([str(message), "--files", CONTROLLER]) == 1

    def test_environment_variable(self, monkeypatch):
        monkeypatch.setenv("STRATEGY_DOCS_NOT_NEEDED", REASON)
        assert checker.main(["--files", CONTROLLER]) == 0


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


class TestGit:
    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        _git(tmp_path, "init", "-q")
        (tmp_path / "multi_coin_grid_pro" / "controllers").mkdir(parents=True)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "TRADING_STRATEGY.md").write_text("v1\n")
        (tmp_path / CONTROLLER).write_text("x = 1\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "base")
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def test_staged_without_doc_fails_and_with_doc_passes(self, repo):
        (repo / CONTROLLER).write_text("x = 2\n")
        _git(repo, "add", "-A")
        assert checker.main(["--staged"]) == 1
        (repo / DOC).write_text("v2\n")
        _git(repo, "add", "-A")
        assert checker.main(["--staged"]) == 0

    def test_range_checks_whole_branch_and_honours_trailer_in_any_commit(self, repo):
        (repo / CONTROLLER).write_text("x = 2\n")
        _git(repo, "commit", "-q", "-am", "change")
        assert checker.main(["--base", "HEAD~1"]) == 1
        (repo / CONTROLLER).write_text("x = 3\n")
        _git(repo, "commit", "-q", "-am", f"tidy\n\nStrategy-Docs: not-needed - {REASON}")
        assert checker.main(["--base", "HEAD~2"]) == 0

    def test_range_with_doc_update_passes(self, repo):
        (repo / CONTROLLER).write_text("x = 2\n")
        (repo / DOC).write_text("v2\n")
        _git(repo, "commit", "-q", "-am", "change with docs")
        assert checker.main(["--base", "HEAD~1"]) == 0

    def test_unknown_base_is_an_error_not_a_pass(self, repo, capsys):
        assert checker.main(["--base", "does-not-exist"]) == 2
        assert "could not read git state" in capsys.readouterr().err
