"""Unit tests for scripts/classify_changed_scripts.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from classify_changed_scripts import (
    Corpus,
    Unclassifiable,
    classify,
    search_terms,
    workflow_jobs,
)

WORKFLOW = """\
name: CI
jobs:
  changes:
    steps:
      - run: python3 scripts/mutation_gate.py scope
  workflow-lint:
    steps:
      - run: python3 scripts/validate_ci_artifacts.py workflow
  spec-kit:
    steps:
      - run: make check-specs
  backend:
    steps:
      - run: python3 scripts/validate_coverage_floor.py --stack backend
  frontend:
    steps:
      - run: python3 scripts/validate_coverage_floor.py --stack frontend
  cli-native:
    steps:
      - run: python3 scripts/check_cli_native.py
"""

LANES = {
    "backend": "",
    "frontend": 'const fixtures = "../scripts/fixtures/allure-quality-gate";',
    "ios": "",
    "ios_kit": "",
    "macos": "include Makefile",  # The Mac app's own Makefile.
    "rust": 'join("../../../scripts/validate_allure_taxonomy.py")',
    "cli": "",
}

TOOLING = {
    "Makefile": "check-specs:\n\tpython3 scripts/check_spec_kit_specs.py\n",
    "scripts/check_spec_kit_specs.py": "import spec_helpers\n",
    "scripts/spec_helpers.py": "",
    "scripts/validate_coverage_floor.py": "import coverage_math\n",
    "scripts/coverage_math.py": "",
    "scripts/check_cli_native.py": "",
    "scripts/validate_allure_taxonomy.py": "",
    "scripts/mutation_gate.py": "",
    "scripts/fixtures/allure-quality-gate/passing/result.json": "{}",
    "scripts/rehearsal/run.py": "",
    "scripts/standalone.py": "",
}


def _classify(*paths: str, workflow: str = WORKFLOW, tooling=None):
    corpus = Corpus(workflow_jobs(workflow), dict(LANES), dict(tooling or TOOLING))
    lanes = classify(paths, corpus)
    return None if lanes is None else sorted(lanes)


class SearchTermTests(unittest.TestCase):
    def test_a_top_level_module_is_named_by_path_file_and_import_name(self) -> None:
        self.assertEqual(
            search_terms("scripts/check_cli_native.py"),
            ["check_cli_native", "check_cli_native.py", "scripts/check_cli_native.py"],
        )

    def test_a_nested_module_is_imported_dotted_never_bare(self) -> None:
        terms = search_terms("scripts/rehearsal/run.py")
        self.assertIn("rehearsal.run", terms)
        self.assertNotIn("run", terms)
        self.assertIn("scripts/rehearsal", terms)

    def test_a_fixture_is_named_through_its_directories(self) -> None:
        terms = search_terms("scripts/fixtures/allure-quality-gate/passing/result.json")
        self.assertIn("scripts/fixtures/allure-quality-gate", terms)
        self.assertIn("scripts/fixtures", terms)


class ClassifyTests(unittest.TestCase):
    def test_a_script_a_lane_job_runs_widens_that_lane(self) -> None:
        self.assertEqual(_classify("scripts/check_cli_native.py"), ["cli"])

    def test_a_module_imported_by_a_lane_script_widens_its_lanes(self) -> None:
        self.assertEqual(_classify("scripts/coverage_math.py"), ["backend", "frontend"])

    def test_a_script_read_from_a_lane_source_tree_widens_that_lane(self) -> None:
        self.assertEqual(_classify("scripts/validate_allure_taxonomy.py"), ["rust"])
        self.assertEqual(
            _classify("scripts/fixtures/allure-quality-gate/passing/result.json"),
            ["frontend"],
        )

    def test_tooling_only_the_always_running_jobs_use_widens_nothing(self) -> None:
        self.assertEqual(_classify("scripts/spec_helpers.py"), [])
        self.assertEqual(_classify("scripts/standalone.py"), [])

    def test_the_makefile_is_read_only_by_jobs_that_run_make(self) -> None:
        # No stack job runs make; the Mac tree naming its own Makefile is not a
        # reader of this one.
        self.assertEqual(_classify("Makefile"), [])
        running = WORKFLOW.replace(
            "python3 scripts/check_cli_native.py", "make cli-native"
        )
        self.assertEqual(_classify("Makefile", workflow=running), ["cli"])
        chained = WORKFLOW.replace(
            "python3 scripts/check_cli_native.py", "cd cli && make native"
        )
        self.assertEqual(_classify("Makefile", workflow=chained), ["cli"])
        prose = WORKFLOW.replace(
            "python3 scripts/check_cli_native.py",
            "true\n      # Surviving mutants make mutmut exit non-zero",
        )
        self.assertEqual(_classify("Makefile", workflow=prose), [])

    def test_inputs_of_the_deciding_job_run_everything(self) -> None:
        self.assertIsNone(_classify("scripts/mutation_gate.py"))

    def test_a_referrer_cycle_terminates(self) -> None:
        tooling = dict(TOOLING)
        tooling["scripts/spec_helpers.py"] = "import check_spec_kit_specs\n"
        self.assertEqual(_classify("scripts/spec_helpers.py", tooling=tooling), [])

    def test_paths_outside_the_tooling_are_ignored(self) -> None:
        self.assertEqual(_classify("backend/app/main.py", "docs/readme.md"), [])

    def test_the_union_is_taken_over_every_changed_file(self) -> None:
        self.assertEqual(
            _classify(
                "scripts/check_cli_native.py", "scripts/validate_allure_taxonomy.py"
            ),
            ["cli", "rust"],
        )

    def test_a_workflow_without_the_deciding_job_cannot_be_classified(self) -> None:
        with self.assertRaises(Unclassifiable):
            workflow_jobs("jobs:\n  backend:\n    steps: []\n")


if __name__ == "__main__":
    unittest.main()
