"""Tests for the backend line and branch coverage contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate_backend_coverage import validate_coverage


class ValidateBackendCoverageTests(unittest.TestCase):
    def test_accepts_line_and_branch_rates_at_or_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coverage_xml = Path(tmp) / "coverage.xml"
            coverage_xml.write_text(
                '<coverage line-rate="0.95" branch-rate="0.9524" />', encoding="utf-8"
            )

            validate_coverage(coverage_xml, threshold=0.95)

    def test_rejects_a_branch_rate_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coverage_xml = Path(tmp) / "coverage.xml"
            coverage_xml.write_text(
                '<coverage line-rate="0.99" branch-rate="0.9499" />', encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "branch coverage"):
                validate_coverage(coverage_xml, threshold=0.95)


if __name__ == "__main__":
    unittest.main()
