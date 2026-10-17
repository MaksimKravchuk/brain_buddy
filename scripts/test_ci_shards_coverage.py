"""Coverage integration regression, required after the aggregator installs coverage."""
from __future__ import annotations

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

import coverage

from scripts.ci_shards import _merge_coverage
from scripts.select_backend_tests import build_map


class CoverageIntegrationTests(unittest.TestCase):
    def test_036_FR_002_036_SC_001_combined_relative_data_reports_real_hits_and_test_contexts(self) -> None:
        """036-SC-001: shard data from other workspaces preserves coverage and map owners."""
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                files = []
                source = "def choose(flag):\n    if flag:\n        return 1\n    return 2\n"
                for index in range(2):
                    workspace = root / f"runner-{index}"
                    (workspace / "app").mkdir(parents=True)
                    (workspace / "app/example.py").write_text(source)
                    os.chdir(workspace)
                    data = workspace / ".coverage"
                    cov = coverage.Coverage(data_file=str(data), branch=True, source=["app"])
                    cov.set_option("run:relative_files", True)
                    cov.set_option("run:core", "ctrace")
                    cov.start()
                    cov.switch_context(f"tests/test_example.py::test_{index}|run")
                    runpy.run_path("app/example.py")["choose"](bool(index))
                    cov.stop()
                    cov.save()
                    files.append(data)
                output = root / "aggregate/backend"
                (output / "app").mkdir(parents=True)
                (output / "app/example.py").write_text(source)
                (output / "tests").mkdir()
                (output / "tests/test_example.py").write_text("")
                # Reporting starts from the repository root, not backend, like Actions.
                os.chdir(output.parent)
                _merge_coverage(files, output, coverage.__version__)
                report = ElementTree.parse(output / "coverage.xml").getroot()
                self.assertEqual(float(report.attrib["line-rate"]), 1.0)
                self.assertEqual(float(report.attrib["branch-rate"]), 1.0)
                os.chdir(output)
                mapped = build_map(output / ".coverage", output, "a" * 40)
                self.assertEqual(mapped["files"]["app/example.py"], ["tests/test_example.py"])
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
