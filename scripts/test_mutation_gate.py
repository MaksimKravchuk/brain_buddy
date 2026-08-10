"""Tests for the enforced-scope mutation gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.mutation_gate import (
    load_enforced_scope,
    main,
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


class BaseRevisionComparisonTests(unittest.TestCase):
    """ADR-0004 requirement 2: the PR is compared to the base revision."""

    def test_rejects_a_regression_that_still_clears_the_threshold(self) -> None:
        # 96% passes the absolute bar but sheds three points against a base at
        # 99%. Without this comparison a well-defended module can be quietly
        # worn down one pull request at a time.
        with self.assertRaises(ValueError) as caught:
            validate_stats(
                {"killed": 96, "survived": 4},
                base_stats={"killed": 99, "survived": 1},
            )
        message = str(caught.exception)
        self.assertIn("96.00%", message)
        self.assertIn("99.00%", message)
        self.assertIn("may not regress", message)

    def test_accepts_an_unchanged_score(self) -> None:
        validate_stats(
            {"killed": 99, "survived": 1}, base_stats={"killed": 99, "survived": 1}
        )

    def test_accepts_an_improvement(self) -> None:
        validate_stats(
            {"killed": 100, "survived": 0}, base_stats={"killed": 96, "survived": 4}
        )

    def test_skips_the_comparison_when_the_base_checked_nothing(self) -> None:
        # A file the base revision does not contain cannot be measured there.
        # Treating that as a base score of 0% would compare against nothing.
        validate_stats(
            {"killed": 99, "survived": 1}, base_stats={"killed": 0, "survived": 0}
        )

    def test_the_absolute_threshold_still_applies_below_a_weak_base(self) -> None:
        # A base that is already under the bar does not license staying under
        # it: the threshold is checked before the comparison.
        with self.assertRaises(ValueError) as caught:
            validate_stats(
                {"killed": 90, "survived": 10},
                base_stats={"killed": 80, "survived": 20},
            )
        self.assertIn("below the required", str(caught.exception))


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


class CheckCommandTests(unittest.TestCase):
    """The CLI surface CI calls, including how it fails."""

    @staticmethod
    def _write(directory: Path, name: str, payload: dict[str, int]) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_passes_and_reports_both_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self._write(root, "head.json", {"killed": 99, "survived": 1})
            base = self._write(root, "base.json", {"killed": 96, "survived": 4})
            self.assertEqual(
                main(
                    ["check", "--stats", str(head), "--base-stats", str(base)],
                ),
                0,
            )

    def test_fails_when_the_base_stats_file_is_missing(self) -> None:
        # The workflow always passes --base-stats on a pull request. If the
        # base measurement did not produce a file, that is a broken gate, not a
        # licence to fall back to a threshold-only check.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self._write(root, "head.json", {"killed": 99, "survived": 1})
            self.assertEqual(
                main(
                    [
                        "check",
                        "--stats",
                        str(head),
                        "--base-stats",
                        str(root / "absent.json"),
                    ],
                ),
                1,
            )

    def test_fails_on_a_regression_against_the_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self._write(root, "head.json", {"killed": 96, "survived": 4})
            base = self._write(root, "base.json", {"killed": 99, "survived": 1})
            self.assertEqual(
                main(["check", "--stats", str(head), "--base-stats", str(base)]),
                1,
            )

    def test_passes_without_a_base_on_the_landing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            head = self._write(Path(tmp), "head.json", {"killed": 99, "survived": 1})
            self.assertEqual(main(["check", "--stats", str(head)]), 0)


if __name__ == "__main__":
    unittest.main()
