#!/usr/bin/env python3
"""Contract tests for scripts/check_slice_budget.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_slice_budget.py")
_SPEC = importlib.util.spec_from_file_location("check_slice_budget", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
budget = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(budget)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _tasks(product_loc: int, files: int, reason: str = "") -> str:
    item = {"id": "PR-01", "budget": {"product_loc": product_loc, "files": files}}
    if reason:
        item["oversize_reason"] = reason
    payload = {"schema_version": "brainbuddy-pr-slices/v2", "slices": [item]}
    return "- [ ] T001 x\n\n## PR-срезы\n\n```json\n" + json.dumps(payload) + "\n```\n"


class ProductPathTest(unittest.TestCase):
    def test_tests_docs_and_lockfiles_do_not_count(self) -> None:
        for path in (
            "backend/tests/test_auth.py",
            "frontend/src/features/review/__tests__/Flow.test.tsx",
            "frontend/src/flow.spec.ts",
            "ios/BrainBuddyKitTests/SyncTests.swift",
            "docs/auth.md",
            "specs/020-weekly-review/tasks.md",
            "frontend/package-lock.json",
            "README.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(budget.is_product_path(path))

    def test_product_code_counts(self) -> None:
        for path in (
            "backend/app/services/tree_service.py",
            "frontend/src/features/review/Flow.tsx",
            "ios/BrainBuddyKit/Sync.swift",
            "scripts/check_slice_budget.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(budget.is_product_path(path))

    def test_numstat_counts_lines_and_files_and_binary_as_file(self) -> None:
        numstat = "10\t2\tbackend/app/a.py\n5\t0\tbackend/tests/test_a.py\n-\t-\tfrontend/logo.png\n"
        self.assertEqual(budget.product_changes(numstat), (12, 2))


class BudgetCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "seed.txt").write_text("seed\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "seed")
        _git(self.repo, "checkout", "-qb", "slice")
        app = self.repo / "app"
        app.mkdir()
        (app / "a.py").write_text("x = 1\n" * 30)
        tests = self.repo / "tests"
        tests.mkdir()
        (tests / "test_a.py").write_text("assert True\n" * 500)
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "slice")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, tasks_text: str) -> subprocess.CompletedProcess[str]:
        tasks = self.repo / "tasks.md"
        tasks.write_text(tasks_text, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(tasks), "PR-01", "--base", "main"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_within_budget_passes_and_ignores_tests(self) -> None:
        result = self._run(_tasks(40, 2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("30/40 product lines", result.stdout)

    def test_over_budget_fails(self) -> None:
        result = self._run(_tasks(20, 2))
        self.assertEqual(result.returncode, 1)
        self.assertIn("split the slice", result.stderr)

    def test_over_budget_with_reason_passes(self) -> None:
        result = self._run(_tasks(20, 2, reason="Generated client"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_slice_is_a_usage_error(self) -> None:
        tasks = self.repo / "tasks.md"
        tasks.write_text(_tasks(40, 2), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(tasks), "PR-09", "--base", "main"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
