"""Tests for the per-stack coverage floor ratchet."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_coverage_floor import (
    COBERTURA,
    ISTANBUL_SUMMARY,
    main,
    validate_coverage_floor,
)

COBERTURA_XML = '<coverage line-rate="0.9847" branch-rate="0.955" />'

ISTANBUL_SUMMARY_JSON = json.dumps(
    {
        "total": {
            "statements": {"pct": 96.5},
            "branches": {"pct": 95.25},
            "functions": {"pct": 97.0},
            "lines": {"pct": 96.5},
        }
    }
)


def _write(directory: str, name: str, content: str) -> Path:
    path = Path(directory) / name
    path.write_text(content, encoding="utf-8")
    return path


def _write_json(directory: str, name: str, payload: dict[str, float]) -> Path:
    return _write(directory, name, json.dumps(payload))


class ValidateCoverageFloorTests(unittest.TestCase):
    def test_accepts_cobertura_rates_at_the_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847, "branch": 0.955})

            actual = validate_coverage_floor(
                report, floor, stack="backend", report_format=COBERTURA
            )

            self.assertEqual(actual, {"line": 0.9847, "branch": 0.955})

    def test_accepts_istanbul_percentages_above_the_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage-summary.json", ISTANBUL_SUMMARY_JSON)
            floor = _write_json(
                tmp,
                "floor.json",
                {
                    "statements": 0.96,
                    "branches": 0.95,
                    "functions": 0.96,
                    "lines": 0.96,
                },
            )

            actual = validate_coverage_floor(
                report, floor, stack="frontend", report_format=ISTANBUL_SUMMARY
            )

            self.assertEqual(actual["branches"], 0.9525)

    def test_rejects_a_metric_below_its_floor_naming_stack_and_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847, "branch": 0.96})

            with self.assertRaisesRegex(ValueError, "backend branch coverage"):
                validate_coverage_floor(
                    report, floor, stack="backend", report_format=COBERTURA
                )

    def test_rejects_a_floor_metric_the_report_does_not_measure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"functions": 0.9})

            with self.assertRaisesRegex(ValueError, "backend floor requires metric"):
                validate_coverage_floor(
                    report, floor, stack="backend", report_format=COBERTURA
                )

    def test_accepts_a_floor_raised_above_the_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847, "branch": 0.955})
            base_floor = _write_json(
                tmp, "base-floor.json", {"line": 0.98, "branch": 0.95}
            )

            validate_coverage_floor(
                report,
                floor,
                stack="backend",
                report_format=COBERTURA,
                base_floor_path=base_floor,
            )

    def test_rejects_a_floor_lowered_below_the_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9, "branch": 0.9})
            base_floor = _write_json(
                tmp, "base-floor.json", {"line": 0.9847, "branch": 0.955}
            )

            with self.assertRaisesRegex(ValueError, "backend line floor"):
                validate_coverage_floor(
                    report,
                    floor,
                    stack="backend",
                    report_format=COBERTURA,
                    base_floor_path=base_floor,
                )

    def test_rejects_a_floor_metric_dropped_since_the_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847})
            base_floor = _write_json(
                tmp, "base-floor.json", {"line": 0.9847, "branch": 0.955}
            )

            with self.assertRaisesRegex(ValueError, "backend branch floor was removed"):
                validate_coverage_floor(
                    report,
                    floor,
                    stack="backend",
                    report_format=COBERTURA,
                    base_floor_path=base_floor,
                )

    def test_accepts_a_new_floor_with_no_base_branch_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847, "branch": 0.955})

            validate_coverage_floor(
                report,
                floor,
                stack="backend",
                report_format=COBERTURA,
                base_floor_path=Path(tmp) / "missing-floor.json",
            )

    def test_main_exits_zero_when_the_floor_is_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage.xml", COBERTURA_XML)
            floor = _write_json(tmp, "floor.json", {"line": 0.9847, "branch": 0.955})

            exit_code = main(
                [
                    "--stack",
                    "backend",
                    "--format",
                    COBERTURA,
                    "--report",
                    str(report),
                    "--floor",
                    str(floor),
                ]
            )

            self.assertEqual(exit_code, 0)

    def test_main_exits_non_zero_when_a_metric_is_below_its_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = _write(tmp, "coverage-summary.json", ISTANBUL_SUMMARY_JSON)
            floor = _write_json(tmp, "floor.json", {"branches": 0.99})

            exit_code = main(
                [
                    "--stack",
                    "mobile",
                    "--format",
                    ISTANBUL_SUMMARY,
                    "--report",
                    str(report),
                    "--floor",
                    str(floor),
                ]
            )

            self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
