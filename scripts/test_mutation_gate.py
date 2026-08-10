"""Tests for the enforced-scope mutation gate."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# `scripts/` is not a package and not on sys.path when this runs from the
# repository root, which is how the Makefile and the docs invoke it.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_gate import (  # noqa: E402
    load_enforced_scope,
    mutation_score,
    rewrite_only_mutate,
    scope_for_changes,
    validate_stats,
)

ENFORCED = [
    "app/services/tree_service.py",
    "app/services/version_service.py",
    "app/repositories/index.py",
]


class LoadEnforcedScopeTests(unittest.TestCase):
    def test_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scope.txt"
            path.write_text(
                "# the enforced tier\n"
                "app/services/tree_service.py\n"
                "\n"
                "app/repositories/index.py  # calibrated 2026-08\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_enforced_scope(path),
                ["app/services/tree_service.py", "app/repositories/index.py"],
            )

    def test_rejects_an_empty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scope.txt"
            path.write_text("# nothing here\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_enforced_scope(path)


class ScopeForChangesTests(unittest.TestCase):
    def test_selects_only_touched_enforced_files(self) -> None:
        changed = [
            "app/services/tree_service.py",
            "backend/README.md",
            "app/modules/tasks/repository.py",
        ]
        self.assertEqual(
            scope_for_changes(ENFORCED, changed), ["app/services/tree_service.py"]
        )

    def test_untouched_scope_is_empty(self) -> None:
        self.assertEqual(scope_for_changes(ENFORCED, ["docs/decisions/0011.md"]), [])

    def test_preserves_allow_list_order(self) -> None:
        changed = ["app/repositories/index.py", "app/services/tree_service.py"]
        self.assertEqual(
            scope_for_changes(ENFORCED, changed),
            ["app/services/tree_service.py", "app/repositories/index.py"],
        )


class MutationScoreTests(unittest.TestCase):
    def test_score_counts_only_decided_mutants(self) -> None:
        # skipped/timeout/no_tests say nothing about assertion strength, so they
        # must not move the score in either direction.
        stats = {
            "killed": 19,
            "survived": 1,
            "skipped": 50,
            "timeout": 3,
            "no_tests": 7,
            "total": 80,
        }
        killed, checked, score = mutation_score(stats)
        self.assertEqual((killed, checked), (19, 20))
        self.assertAlmostEqual(score, 0.95)

    def test_no_decided_mutants_scores_zero(self) -> None:
        self.assertEqual(mutation_score({"killed": 0, "survived": 0}), (0, 0, 0.0))


class ValidateStatsTests(unittest.TestCase):
    def test_accepts_a_score_at_the_threshold(self) -> None:
        validate_stats({"killed": 19, "survived": 1})

    def test_rejects_a_score_below_the_threshold(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_stats({"killed": 18, "survived": 2})
        self.assertIn("90.00%", str(caught.exception))

    def test_rejects_a_campaign_that_checked_nothing(self) -> None:
        # A gate that passes when it mutated nothing is worse than no gate.
        with self.assertRaises(ValueError) as caught:
            validate_stats({"killed": 0, "survived": 0, "skipped": 200})
        self.assertIn("no mutants", str(caught.exception))


class RewriteOnlyMutateTests(unittest.TestCase):
    def test_narrows_the_scope_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text(
                "[tool.mutmut]\n"
                'source_paths = ["app"]\n'
                "only_mutate = [\n"
                '  "app/services/tree_service.py",\n'
                '  "app/modules/tasks/repository.py",\n'
                "]\n"
                "mutate_only_covered_lines = true\n",
                encoding="utf-8",
            )
            rewrite_only_mutate(path, ["app/services/tree_service.py"])
            text = path.read_text(encoding="utf-8")
            self.assertIn('only_mutate = [\n  "app/services/tree_service.py",\n]', text)
            self.assertNotIn("tasks/repository.py", text)
            self.assertIn("mutate_only_covered_lines = true", text)

    def test_refuses_an_empty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text("only_mutate = [\n]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                rewrite_only_mutate(path, [])

    def test_reports_a_missing_scope_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pyproject.toml"
            path.write_text("[tool.mutmut]\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                rewrite_only_mutate(path, ["app/services/tree_service.py"])


class StatsFileRoundTripTests(unittest.TestCase):
    def test_validates_a_real_mutmut_stats_payload(self) -> None:
        # Shape as written by `mutmut export-cicd-stats`.
        payload = {
            "killed": 96,
            "survived": 4,
            "total": 120,
            "no_tests": 0,
            "skipped": 20,
            "suspicious": 0,
            "timeout": 0,
            "check_was_interrupted_by_user": False,
            "segfault": 0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            stats = json.loads(path.read_text(encoding="utf-8"))
            validate_stats(stats)


if __name__ == "__main__":
    unittest.main()
