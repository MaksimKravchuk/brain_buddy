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
    mutmut_results_score,
    mutmut_summary,
    mutmut_survivors,
    rewrite_only_mutate,
    scope_for_changes,
    scope_module_prefixes,
    stryker_score,
    validate_stats,
    validate_stryker,
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
                main(["check", "--stats", str(head), "--base-stats", str(base)]), 0
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
                    ]
                ),
                1,
            )

    def test_fails_on_a_regression_against_the_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self._write(root, "head.json", {"killed": 96, "survived": 4})
            base = self._write(root, "base.json", {"killed": 99, "survived": 1})
            self.assertEqual(
                main(["check", "--stats", str(head), "--base-stats", str(base)]), 1
            )

    def test_passes_without_a_base_on_the_landing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            head = self._write(Path(tmp), "head.json", {"killed": 99, "survived": 1})
            self.assertEqual(main(["check", "--stats", str(head)]), 0)


#: An observed-tier dump: the enforced modules plus the two ADR-0016 admitted
#: under calibration, which is exactly the shape the nightly produces.
OBSERVED_DUMP = "\n".join(
    [
        "app.services.tree_service.xǁTreeServiceǁget_tree__mutmut_1: killed",
        "app.services.tree_service.xǁTreeServiceǁget_tree__mutmut_2: survived",
        "app.repositories.tree.xǁTreeRepositoryǁload__mutmut_1: killed",
        "app.modules.tasks.repository.xǁTaskRepositoryǁ_get__mutmut_1: survived",
        "app.modules.tasks.repository.xǁTaskRepositoryǁ_get__mutmut_2: survived",
        "app.services.auth_service.xǁAuthServiceǁlogin__mutmut_1: survived",
        "app.services.tree_service.xǁTreeServiceǁget_tree__mutmut_3: not checked",
    ]
)

ENFORCED_TWO = ["app/services/tree_service.py", "app/repositories/tree.py"]


class ScopeModulePrefixTests(unittest.TestCase):
    def test_a_path_becomes_a_dotted_prefix_with_a_trailing_dot(self) -> None:
        self.assertEqual(
            scope_module_prefixes(["app/services/tree_service.py"]),
            ["app.services.tree_service."],
        )

    def test_the_trailing_dot_stops_a_sibling_module_being_claimed(self) -> None:
        # Without it `app.repositories.tree` would swallow every mutant of
        # `app.repositories.tree_service` as well.
        dump = "app.repositories.tree_service.xǁXǁf__mutmut_1: survived"
        self.assertEqual(
            mutmut_results_score(dump, ["app/repositories/tree.py"]), (0, 0, 0.0)
        )


class MutmutResultsScoreTests(unittest.TestCase):
    """One campaign, two tier scores: the enforced number is a filter over the
    observed run's per-mutant verdicts, not a second campaign."""

    def test_the_observed_tier_counts_every_module(self) -> None:
        self.assertEqual(mutmut_results_score(OBSERVED_DUMP)[:2], (2, 6))

    def test_the_enforced_tier_excludes_modules_under_calibration(self) -> None:
        killed, checked, score = mutmut_results_score(OBSERVED_DUMP, ENFORCED_TWO)
        self.assertEqual((killed, checked), (2, 3))
        self.assertAlmostEqual(score, 2 / 3)

    def test_undecided_verdicts_stay_out_of_the_denominator(self) -> None:
        # `not checked` says nothing about assertion strength, exactly as
        # skipped and timed-out mutants do not in the aggregate stats.
        self.assertEqual(mutmut_results_score(OBSERVED_DUMP, ENFORCED_TWO)[1], 3)

    def test_an_empty_intersection_reports_nothing_checked_not_a_pass(self) -> None:
        self.assertEqual(
            mutmut_results_score(OBSERVED_DUMP, ["app/repositories/version.py"]),
            (0, 0, 0.0),
        )


class MutmutSummaryTests(unittest.TestCase):
    def test_summary_names_the_tier_and_lists_each_enforced_module(self) -> None:
        summary = mutmut_summary(OBSERVED_DUMP, ENFORCED_TWO)
        self.assertIn("app/services/tree_service.py: 50.00% (1/2 killed)", summary)
        self.assertIn("app/repositories/tree.py: 100.00% (1/1 killed)", summary)
        self.assertIn("TOTAL (enforced scope): 66.67% (2/3 killed)", summary)

    def test_the_observed_summary_says_which_tier_it_is(self) -> None:
        self.assertIn("TOTAL (observed scope):", mutmut_summary(OBSERVED_DUMP))

    def test_survivors_are_limited_to_the_scope(self) -> None:
        survivors = mutmut_survivors(OBSERVED_DUMP, ENFORCED_TWO)
        self.assertIn("tree_service.xǁTreeServiceǁget_tree__mutmut_2", survivors)
        self.assertNotIn("tasks.repository", survivors)
        self.assertNotIn("auth_service", survivors)

    def test_no_survivors_says_so_rather_than_writing_an_empty_file(self) -> None:
        clean = "app.services.tree_service.xǁTreeServiceǁget_tree__mutmut_1: killed"
        self.assertEqual(
            mutmut_survivors(clean, ["app/services/tree_service.py"]),
            "No surviving mutants\n",
        )


class SummarizeMutmutCommandTests(unittest.TestCase):
    def test_writes_both_files_and_reports_the_enforced_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results.txt"
            results.write_text(OBSERVED_DUMP, encoding="utf-8")
            enforced = root / "enforced.txt"
            enforced.write_text("\n".join(ENFORCED_TWO) + "\n", encoding="utf-8")
            summary_out = root / "out" / "summary.txt"
            survivors_out = root / "out" / "survivors.txt"

            self.assertEqual(
                main(
                    [
                        "summarize-mutmut",
                        "--results",
                        str(results),
                        "--enforced",
                        str(enforced),
                        "--summary-out",
                        str(summary_out),
                        "--survivors-out",
                        str(survivors_out),
                    ]
                ),
                0,
            )
            self.assertIn(
                "TOTAL (enforced scope): 66.67%",
                summary_out.read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "tasks.repository", survivors_out.read_text(encoding="utf-8")
            )

    def test_a_missing_results_file_fails_rather_than_writing_a_clean_report(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                main(
                    [
                        "summarize-mutmut",
                        "--results",
                        str(root / "absent.txt"),
                        "--summary-out",
                        str(root / "s.txt"),
                        "--survivors-out",
                        str(root / "v.txt"),
                    ]
                ),
                1,
            )


def stryker_report(files: dict[str, list[str]]) -> dict[str, object]:
    """A minimal Stryker report: file path -> the status of each of its mutants."""

    return {
        "schemaVersion": "1.0",
        "files": {
            path: {
                "language": "typescript",
                "source": "",
                "mutants": [
                    {"id": f"{path}-{index}", "mutatorName": "ConditionalExpression", "status": status}
                    for index, status in enumerate(statuses)
                ],
            }
            for path, statuses in files.items()
        },
    }


class StrykerScoreTests(unittest.TestCase):
    def test_counts_only_mutants_with_a_verdict_about_the_tests(self) -> None:
        report = stryker_report(
            {
                "src/utils/error.ts": [
                    "Killed",
                    "Timeout",
                    "Survived",
                    "CompileError",
                    "Ignored",
                    "RuntimeError",
                ]
            }
        )

        self.assertEqual(stryker_score(report), (2, 3, 2 / 3))

    def test_an_unreached_mutant_counts_against_the_score(self) -> None:
        report = stryker_report({"src/utils/error.ts": ["Killed", "NoCoverage"]})

        self.assertEqual(stryker_score(report), (1, 2, 0.5))

    def test_scope_restricts_the_count_to_the_enforced_files(self) -> None:
        report = stryker_report(
            {
                "src/utils/error.ts": ["Killed", "Killed"],
                "src/api/client.ts": ["Survived", "Survived"],
            }
        )

        self.assertEqual(stryker_score(report, ["src/utils/error.ts"]), (2, 2, 1.0))

    def test_an_enforced_file_absent_from_the_report_is_an_error(self) -> None:
        report = stryker_report({"src/utils/error.ts": ["Killed"]})

        with self.assertRaises(ValueError) as caught:
            stryker_score(report, ["src/api/client.ts"])
        self.assertIn("src/api/client.ts", str(caught.exception))

    def test_a_report_without_files_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            stryker_score({"schemaVersion": "1.0"})


class ValidateStrykerTests(unittest.TestCase):
    def test_a_report_at_the_threshold_passes(self) -> None:
        report = stryker_report({"src/utils/error.ts": ["Killed"] * 19 + ["Survived"]})

        validate_stryker(report, threshold=0.95)

    def test_a_report_below_the_threshold_is_rejected_with_its_score(self) -> None:
        report = stryker_report({"src/utils/error.ts": ["Killed"] * 18 + ["Survived"] * 2})

        with self.assertRaises(ValueError) as caught:
            validate_stryker(report, threshold=0.95)
        self.assertIn("90.00%", str(caught.exception))

    def test_a_report_that_checked_nothing_is_rejected(self) -> None:
        report = stryker_report({"src/utils/error.ts": ["CompileError"]})

        with self.assertRaises(ValueError) as caught:
            validate_stryker(report)
        self.assertIn("checked no mutants", str(caught.exception))


class CheckStrykerCommandTests(unittest.TestCase):
    def write(self, root: Path, statuses: dict[str, list[str]]) -> Path:
        report = root / "mutation-report.json"
        report.write_text(json.dumps(stryker_report(statuses)), encoding="utf-8")
        return report

    def test_passes_over_the_enforced_scope_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.write(
                root,
                {
                    "src/utils/error.ts": ["Killed"] * 20,
                    "src/features/tasks/smartAdd.ts": ["Survived"] * 20,
                },
            )
            scope = root / "enforced.txt"
            scope.write_text("src/utils/error.ts\n", encoding="utf-8")

            self.assertEqual(
                main(
                    [
                        "check-stryker",
                        "--report",
                        str(report),
                        "--enforced",
                        str(scope),
                    ]
                ),
                0,
            )

    def test_fails_when_the_enforced_scope_misses_the_bar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.write(root, {"src/utils/error.ts": ["Killed"] * 9 + ["Survived"]})
            scope = root / "enforced.txt"
            scope.write_text("src/utils/error.ts\n", encoding="utf-8")

            self.assertEqual(
                main(["check-stryker", "--report", str(report), "--enforced", str(scope)]),
                1,
            )

    def test_a_missing_report_fails_rather_than_passing_vacuously(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                main(["check-stryker", "--report", str(Path(tmp) / "absent.json")]), 1
            )


if __name__ == "__main__":
    unittest.main()
