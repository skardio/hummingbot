#!/usr/bin/env python3
"""
Fail when strategy-relevant files change without a change to docs/TRADING_STRATEGY.md.

Usage (standard library only, looks at changed file names and commit messages, nothing else):
    python3 .github/scripts/check_trading_strategy_docs.py --staged [COMMIT_MSG_FILE]
    python3 .github/scripts/check_trading_strategy_docs.py --base origin/main [--head HEAD]
    python3 .github/scripts/check_trading_strategy_docs.py --files a.py b.yaml [--message "..."]

Pre-commit: runs in the `commit-msg` stage (see .pre-commit-config.yaml), so install it with
    pre-commit install --hook-type commit-msg

Explicit exception for changes without behaviour impact (e.g. a pure refactor), either
    - a commit-message trailer:  Strategy-Docs: not-needed - <reason of at least 15 characters>
    - or the environment:        STRATEGY_DOCS_NOT_NEEDED="<reason of at least 15 characters>"
The reason is printed so the exception stays reviewable.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys
from typing import List, NamedTuple, Optional, Sequence

DOC_PATH = "docs/TRADING_STRATEGY.md"
MIN_REASON_CHARS = 15

# Directory prefixes whose .py/.yaml/.yml files shape trading behaviour.
STRATEGY_PREFIXES = (
    "multi_coin_grid_pro/controllers/",
    "multi_coin_grid_pro/core/",
    "multi_coin_grid_pro/risk/",
    "multi_coin_grid_pro/logic/",
    "multi_coin_grid_pro/filters/",
    "multi_coin_grid_pro/scoring/",
    "multi_coin_grid_pro/execution/",
    "multi_coin_grid_pro/indicators/",
    "multi_coin_grid_pro/spot_bitget/",
    "multi_coin_grid_pro/spot_okx/",
    "hummingbot/strategy_v2/executors/grid_executor/",
)
# Individual modules that influence selection, sizing or entries.
STRATEGY_FILES = tuple("multi_coin_grid_pro/utils/" + name for name in (
    "trend_calculator.py", "grid_suitability_scorer.py", "regime_detector.py", "dynamic_pair_manager.py",
    "dynamic_grid_sizer.py", "coin_discovery.py", "budget_allocator.py", "adaptive_filter_resolver.py",
    "adaptive_timeout.py", "order_validator.py", "staleness_guard.py", "universe_quality_gate.py",
    "pair_health_monitor.py",
))
# Bot configuration (fnmatch: '*' also spans '/').
STRATEGY_YAML_GLOBS = (
    "multi_coin_grid_pro/config/spot_grid_*.yaml",
    "multi_coin_grid_pro/config/spot_grid_*.yml",
    "multi_coin_grid_pro/spot_bitget/config/*.yaml",
    "multi_coin_grid_pro/spot_bitget/config/*.yml",
    "multi_coin_grid_pro/spot_okx/config/*.yaml",
    "multi_coin_grid_pro/spot_okx/config/*.yml",
)
CODE_SUFFIXES = (".py", ".yaml", ".yml")
IGNORED_PARTS = ("/tests/", "/test/", "/__pycache__/", "/Oud/")

TRAILER_RE = re.compile(r"^\s*Strategy-Docs:\s*not-needed\s*-\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


class Result(NamedTuple):
    status: str  # "ok" | "skip" | "fail"
    relevant: List[str]
    reason: str


def is_strategy_relevant(path: str) -> bool:
    path = path.replace("\\", "/")
    padded = "/" + path
    if any(part in padded for part in IGNORED_PARTS) or not path.endswith(CODE_SUFFIXES):
        return False
    if path.startswith(STRATEGY_PREFIXES) or path in STRATEGY_FILES:
        return True
    return any(fnmatch.fnmatch(path, glob) for glob in STRATEGY_YAML_GLOBS)


def find_exception_reason(messages: Sequence[str], env_reason: Optional[str]) -> Optional[str]:
    candidates = [env_reason or ""]
    for message in messages:
        candidates.extend(TRAILER_RE.findall(message))
    for reason in candidates:
        if len(reason.strip()) >= MIN_REASON_CHARS:
            return reason.strip()
    return None


def evaluate(changed_files: Sequence[str], messages: Sequence[str] = (), env_reason: Optional[str] = None) -> Result:
    files = [f.replace("\\", "/").strip() for f in changed_files if f.strip()]
    relevant = sorted(f for f in files if is_strategy_relevant(f))
    if not relevant or DOC_PATH in files:
        return Result("ok", relevant, "")
    reason = find_exception_reason(messages, env_reason)
    if reason:
        return Result("skip", relevant, reason)
    return Result("fail", relevant, "")


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _lines(text: str) -> List[str]:
    return [line for line in text.splitlines() if line.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--staged", action="store_true", help="check the staged files")
    source.add_argument("--base", help="base revision; compares merge-base(base, head)..head")
    source.add_argument("--files", nargs="+", help="explicit list of changed files")
    parser.add_argument("--head", default="HEAD", help="head revision for --base (default HEAD)")
    parser.add_argument("--message", action="append", default=[], help="commit message text (repeatable)")
    parser.add_argument("commit_msg_file", nargs="?", help="commit message file (passed by pre-commit)")
    args = parser.parse_args(argv)

    messages = list(args.message)
    if args.commit_msg_file:
        with open(args.commit_msg_file, encoding="utf-8") as handle:
            messages.append(handle.read())
    try:
        if args.staged:
            changed = _lines(_git("diff", "--cached", "--name-only", "--no-renames"))
        elif args.base:
            changed = _lines(_git("diff", "--name-only", "--no-renames", f"{args.base}...{args.head}"))
            messages.extend(_git("log", "--no-merges", "--format=%B%x00", f"{args.base}..{args.head}").split("\x00"))
        else:
            changed = list(args.files)
    except RuntimeError as error:
        print(f"strategy-docs check could not read git state: {error}", file=sys.stderr)
        return 2

    result = evaluate(changed, messages, os.environ.get("STRATEGY_DOCS_NOT_NEEDED"))
    if result.status == "fail":
        print(f"ERROR: strategy-relevant files changed without updating {DOC_PATH}:", file=sys.stderr)
        for path in result.relevant:
            print(f"  - {path}", file=sys.stderr)
        print(
            f"Update {DOC_PATH} (incl. its 'Strategiewijzigingen' table) in the same change, or, for changes without\n"
            f"behaviour impact, add the commit trailer:\n"
            f"  Strategy-Docs: not-needed - <reason of at least {MIN_REASON_CHARS} characters>",
            file=sys.stderr,
        )
        return 1
    if result.status == "skip":
        print(f"strategy-docs check skipped for {len(result.relevant)} file(s): {result.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
