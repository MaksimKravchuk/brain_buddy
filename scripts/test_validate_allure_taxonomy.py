"""TDD suite for the Allure taxonomy validator.

The validator reads generated Allure ``*-result.json`` files and fails when any
emitted test result is missing a non-empty epic, feature, story, human-readable
title, or at least one named step. It uses only the Python standard library so
it can run in CI before backend/frontend dependencies are installed.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_allure_taxonomy.py"


def _valid_result() -> dict:
    return {
        "name": "Create a tree from a valid capture",
        "fullName": "tests.test_tree_service#test_create_tree",
        "status": "passed",
        "labels": [
            {"name": "epic", "value": "Reality Tree"},
            {"name": "feature", "value": "Tree service"},
            {"name": "story", "value": "Tree lifecycle"},
            {"name": "suite", "value": "test_tree_service"},
        ],
        "steps": [
            {"name": "Create a tree from a valid capture", "status": "passed"}
        ],
    }


class ValidateAllureTaxonomyTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _write(self, directory: Path, name: str, payload: dict) -> None:
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_accepts_fully_tagged_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            self._write(results, "a-result.json", _valid_result())

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("backend-pytest", completed.stdout)
        self.assertIn("1", completed.stdout)

    def test_rejects_result_without_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload.pop("steps")
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("step", completed.stderr.lower())

    def test_rejects_step_without_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload["steps"] = [{"name": "", "status": "passed"}]
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("step", completed.stderr.lower())

    def test_rejects_childless_no_op_verify_placeholder_as_only_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload["steps"] = [
                {
                    "name": "Verify: desktop task shell matches the source surface",
                    "status": "passed",
                    "start": 1000,
                    "stop": 1000,
                    "steps": [],
                    "attachments": [],
                    "parameters": [],
                }
            ]
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "frontend-playwright"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("placeholder", completed.stderr.lower())
        self.assertIn("meaningful step", completed.stderr.lower())

    def test_rejects_nested_childless_no_op_verify_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload["steps"] = [
                {
                    "name": "Before Hooks",
                    "status": "passed",
                    "start": 1000,
                    "stop": 1010,
                    "steps": [
                        {
                            "name": 'Fixture "allureTaxonomy"',
                            "status": "passed",
                            "start": 1001,
                            "stop": 1001,
                            "steps": [
                                {
                                    "name": "Verify: mobile shell opens",
                                    "status": "passed",
                                    "start": 1001,
                                    "stop": 1001,
                                    "steps": [],
                                    "attachments": [],
                                    "parameters": [],
                                }
                            ],
                            "attachments": [],
                            "parameters": [],
                        }
                    ],
                    "attachments": [],
                    "parameters": [],
                },
                {
                    "name": 'Click getByRole("button", { name: "Open" })',
                    "status": "passed",
                    "start": 1011,
                    "stop": 1040,
                    "steps": [],
                    "attachments": [],
                    "parameters": [],
                },
            ]
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "frontend-playwright"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("placeholder", completed.stderr.lower())

    def test_rejects_missing_epic_feature_story(self) -> None:
        for missing in ("epic", "feature", "story"):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as tmp:
                    results = Path(tmp)
                    payload = _valid_result()
                    payload["labels"] = [
                        label
                        for label in payload["labels"]
                        if label["name"] != missing
                    ]
                    self._write(results, "a-result.json", payload)

                    completed = self.run_validator(
                        "--path", str(results), "--label", "backend-pytest"
                    )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(missing, completed.stderr)

    def test_rejects_empty_label_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            for label in payload["labels"]:
                if label["name"] == "story":
                    label["value"] = "   "
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("story", completed.stderr)

    def test_rejects_raw_pytest_function_name_as_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload["name"] = "test_create_tree"
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("title", completed.stderr.lower())

    def test_rejects_empty_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            payload = _valid_result()
            payload["name"] = ""
            self._write(results, "a-result.json", payload)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("title", completed.stderr.lower())

    def test_rejects_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_validator(
                "--path", str(tmp), "--label", "frontend-vitest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("frontend-vitest", completed.stderr)

    def test_missing_directory_fails(self) -> None:
        completed = self.run_validator(
            "--path", "/nonexistent/allure-results", "--label", "e2e"
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_discovers_results_in_nested_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vitest = root / "vitest"
            playwright = root / "playwright"
            vitest.mkdir()
            playwright.mkdir()
            self._write(vitest, "a-result.json", _valid_result())
            self._write(playwright, "b-result.json", _valid_result())

            completed = self.run_validator(
                "--path", str(root), "--label", "frontend-all"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("2", completed.stdout)

    def test_validates_multiple_paths_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            self._write(backend, "ok-result.json", _valid_result())
            broken = _valid_result()
            broken.pop("steps")
            self._write(frontend, "bad-result.json", broken)

            completed = self.run_validator(
                "--path",
                str(backend),
                "--path",
                str(frontend),
                "--label",
                "all-layers",
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("bad-result.json", completed.stderr)

    def test_reports_every_failing_file_not_just_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            first = _valid_result()
            first.pop("steps")
            second = _valid_result()
            second["labels"] = [
                label for label in second["labels"] if label["name"] != "epic"
            ]
            self._write(results, "a-result.json", first)
            self._write(results, "b-result.json", second)

            completed = self.run_validator(
                "--path", str(results), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("a-result.json", completed.stderr)
        self.assertIn("b-result.json", completed.stderr)


if __name__ == "__main__":
    unittest.main()
