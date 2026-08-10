"""Tests for the mobile mutation campaign's evidence summarizer."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "summarize_stryker_report.py"

# `scripts/` is not a package and not on sys.path when this runs from the
# repository root, which is how the Makefile and the docs invoke it.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from summarize_stryker_report import (  # noqa: E402
    counts,
    score,
    summarize,
    survivors,
)


def report(*mutants: dict[str, object]) -> dict[str, object]:
    """A minimal Stryker report holding the given mutants in one file."""

    return {
        "schemaVersion": "1.0",
        "files": {
            "src/lifecycle/guards.ts": {
                "language": "typescript",
                "source": "export const x = 1;\n",
                "mutants": list(mutants),
            }
        },
    }


def mutant(status: str, line: int = 3, name: str = "EqualityOperator") -> dict[str, object]:
    return {
        "id": f"{status}-{line}",
        "mutatorName": name,
        "status": status,
        "replacement": "a < b",
        "location": {"start": {"line": line, "column": 5}, "end": {"line": line, "column": 9}},
    }


class SummarizeStrykerReportTest(unittest.TestCase):
    def test_timeouts_count_as_kills_and_no_coverage_counts_as_survival(self) -> None:
        tally = counts(
            report(
                mutant("Killed"),
                mutant("Timeout", line=4),
                mutant("Survived", line=5),
                mutant("NoCoverage", line=6),
            )
        )

        self.assertEqual(tally["killed"], 2)
        self.assertEqual(tally["survived"], 2)
        self.assertEqual(tally["total"], 4)
        self.assertEqual(score(tally), 0.5)

    def test_unchecked_mutants_move_neither_side_of_the_score(self) -> None:
        tally = counts(
            report(
                mutant("Killed"),
                mutant("CompileError", line=4),
                mutant("Ignored", line=5),
                mutant("RuntimeError", line=6),
            )
        )

        self.assertEqual(tally["other"], 3)
        self.assertEqual(score(tally), 1.0)

    def test_a_campaign_that_checked_nothing_has_no_score_rather_than_a_perfect_one(self) -> None:
        self.assertIsNone(score(counts(report())))
        self.assertIn("no mutants checked", summarize(report()))

    def test_every_survivor_is_named_with_its_location_and_replacement(self) -> None:
        lines = survivors(report(mutant("Survived", line=7), mutant("Killed", line=8)))

        self.assertEqual(len(lines), 1)
        self.assertIn("src/lifecycle/guards.ts:7:5", lines[0])
        self.assertIn("EqualityOperator", lines[0])
        self.assertIn("a < b", lines[0])

    def test_the_summary_says_it_is_report_only(self) -> None:
        text = summarize(report(mutant("Killed"), mutant("Survived", line=4)))

        self.assertIn("report-only", text)
        self.assertIn("not a product-test gate", text)
        self.assertIn("50.00%", text)

    def test_it_writes_both_files_and_reports_no_survivors_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "mutation-report.json"
            source.write_text(json.dumps(report(mutant("Killed"))), encoding="utf-8")
            summary = root / "summary.txt"
            found = root / "survivors.txt"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--report",
                    str(source),
                    "--summary",
                    str(summary),
                    "--survivors",
                    str(found),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("100.00%", summary.read_text(encoding="utf-8"))
            self.assertEqual(found.read_text(encoding="utf-8").strip(), "No surviving mutants.")

    def test_a_missing_report_fails_loudly_instead_of_writing_an_empty_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--report",
                    str(root / "absent.json"),
                    "--summary",
                    str(root / "summary.txt"),
                    "--survivors",
                    str(root / "survivors.txt"),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not exist", completed.stderr)
        self.assertFalse((Path(tmp) / "summary.txt").exists())


if __name__ == "__main__":
    unittest.main()
