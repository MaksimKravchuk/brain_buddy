"""Unit tests for scripts/select_backend_tests.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from select_backend_tests import (
    _changed_lines,
    _function_bodies,
    _function_body_lines,
    select,
)

SERVICE = '''"""Tree service."""
LIMIT = 16


class TreeService:
    cache_size = LIMIT

    def rename(self, tree, name):
        """Rename a tree."""
        tree.name = name
        return tree


def helper(value=LIMIT):
    return value + 1
'''

TEST_MAP = {
    "version": 2,
    "source_sha": "abc",
    "files": {
        "app/services/tree_service.py": [
            "tests/test_tree_service.py",
            "tests/test_api_trees.py",
        ],
        "app/registry.py": ["tests/test_registry.py"],
        "app/unused.py": [],
        "app/modules/tasks/rust_adapter.py": ["tests/test_sync.py"],
    },
    "import_executed": {"app/registry.py": ["helper"]},
    "tests": [
        "tests/test_api_trees.py",
        "tests/test_registry.py",
        "tests/test_rust_bridge.py",
        "tests/test_sync.py",
        "tests/test_tree_service.py",
    ],
}
HEAD_TESTS = set(TEST_MAP["tests"])


def _hunk(start: int, count: int = 1) -> str:
    return f"@@ -1 +{start},{count} @@\n"


BRIDGE = {"app/modules/tasks/rust_adapter.py", "tests/test_rust_bridge.py"}


def _select(
    changes,
    diff="",
    source=SERVICE,
    head_tests=HEAD_TESTS,
    bridge=BRIDGE,
    test_map=None,
):
    return select(
        test_map or TEST_MAP,
        changes,
        diff_for=lambda _path: diff,
        head_source_for=lambda _path: source,
        head_tests=set(head_tests),
        bridge_importers=set(bridge),
    )


class LineParsingTests(unittest.TestCase):
    def test_function_bodies_exclude_signatures_and_class_attributes(self) -> None:
        body = _function_body_lines(SERVICE)
        self.assertEqual(body, {9, 10, 11, 15})

    def test_function_bodies_name_the_innermost_function(self) -> None:
        owners = _function_bodies(SERVICE)
        self.assertEqual(owners[10], "TreeService.rename")
        self.assertEqual(owners[15], "helper")
        nested = "def outer():\n    x = 1\n    def inner():\n        return x\n    return inner\n"
        owners = _function_bodies(nested)
        self.assertEqual(
            (owners[2], owners[4], owners[5]), ("outer", "outer.inner", "outer")
        )

    def test_changed_lines_reads_new_side_of_hunks(self) -> None:
        diff = "@@ -3,2 +3,3 @@\n@@ -10 +11 @@\n@@ -20,4 +19,0 @@\n"
        self.assertEqual(_changed_lines(diff), {3, 4, 5, 11, 19})


class SelectionTests(unittest.TestCase):
    def test_body_change_selects_the_recorded_tests(self) -> None:
        tests, _ = _select(
            [("M", "backend/app/services/tree_service.py")], diff=_hunk(10)
        )
        self.assertEqual(
            tests, ["tests/test_api_trees.py", "tests/test_tree_service.py"]
        )

    def test_module_level_change_runs_everything(self) -> None:
        for line in (2, 5, 6):  # constant, class statement, class attribute
            with self.subTest(line=line):
                tests, reasons = _select(
                    [("M", "backend/app/services/tree_service.py")], diff=_hunk(line)
                )
                self.assertIsNone(tests)
                self.assertIn("module-level", reasons[0])

    def test_signature_and_decorator_changes_select_the_callers(self) -> None:
        for line in (8, 14):  # method signature, function default
            with self.subTest(line=line):
                tests, _ = _select(
                    [("M", "backend/app/services/tree_service.py")], diff=_hunk(line)
                )
                self.assertEqual(
                    tests, ["tests/test_api_trees.py", "tests/test_tree_service.py"]
                )
        decorated = (
            "import functools\n\n\n@functools.wraps(print)\ndef f():\n    return 1\n"
        )
        tests, _ = _select(
            [("M", "backend/app/services/tree_service.py")],
            diff=_hunk(4),
            source=decorated,
        )
        self.assertEqual(
            tests, ["tests/test_api_trees.py", "tests/test_tree_service.py"]
        )

    def test_import_changes_select_except_in_a_package_init(self) -> None:
        source = "import os\nfrom typing import (\n    Any,\n)\n\n\ndef f():\n    return os\n"
        tests, _ = _select(
            [("M", "backend/app/services/tree_service.py")],
            diff=_hunk(2, 3),
            source=source,
        )
        self.assertEqual(
            tests, ["tests/test_api_trees.py", "tests/test_tree_service.py"]
        )
        package = dict(
            TEST_MAP,
            files={
                **TEST_MAP["files"],
                "app/services/__init__.py": ["tests/test_x.py"],
            },
        )
        tests, _ = _select(
            [("M", "backend/app/services/__init__.py")],
            diff=_hunk(1),
            source=source,
            test_map=package,
        )
        self.assertIsNone(tests)

    def test_unsafe_changes_run_everything(self) -> None:
        cases = {
            "conftest": ("M", "backend/tests/conftest.py"),
            "fixture helper": ("M", "backend/tests/a2a_fakes.py"),
            "pyproject": ("M", "backend/pyproject.toml"),
            "new app file": ("A", "backend/app/new.py"),
            "deleted app file": ("D", "backend/app/services/tree_service.py"),
            "unmapped file": ("M", "backend/app/other.py"),
            "never executed": ("M", "backend/app/unused.py"),
            "non-python app file": ("M", "backend/app/prompts/system.txt"),
        }
        for label, change in cases.items():
            with self.subTest(label=label):
                tests, _ = _select([change], diff=_hunk(10))
                self.assertIsNone(tests)

    def test_memoizing_module_runs_everything(self) -> None:
        for source in (
            "from functools import lru_cache\n\n@lru_cache(maxsize=1)\ndef get():\n    return 1\n",
            "import functools\n\n@functools.cache\ndef get():\n    return 1\n",
            "_x = None\n\ndef get():\n    global _x\n    _x = 1\n    return _x\n",
        ):
            with self.subTest(source=source):
                tests, reasons = _select(
                    [("M", "backend/app/services/tree_service.py")],
                    diff=_hunk(5),
                    source=source,
                )
                self.assertIsNone(tests)
                self.assertIn("memoizes", reasons[0])

    def test_body_of_a_function_that_runs_at_import_runs_everything(self) -> None:
        tests, reasons = _select([("M", "backend/app/registry.py")], diff=_hunk(15))
        self.assertIsNone(tests)
        self.assertIn("helper also runs at import time", reasons[0])

    def test_other_bodies_in_a_file_with_import_time_code_are_selected(self) -> None:
        tests, _ = _select([("M", "backend/app/registry.py")], diff=_hunk(10))
        self.assertEqual(tests, ["tests/test_registry.py"])

    def test_rust_change_selects_the_bridge_callers(self) -> None:
        tests, _ = _select([("M", "rust/crates/bb-domain/src/lib.rs")])
        self.assertEqual(tests, ["tests/test_rust_bridge.py", "tests/test_sync.py"])

    def test_rust_change_without_a_trustworthy_bridge_runs_everything(self) -> None:
        unmeasured = dict(
            TEST_MAP,
            files={k: v for k, v in TEST_MAP["files"].items() if "rust" not in k},
        )
        for label, kwargs in {
            "no importer": {"bridge": {"tests/test_rust_bridge.py"}},
            "importer unmeasured": {"test_map": unmeasured},
            "importer memoizes": {
                "source": "import bb_core\n_x = None\n\ndef get():\n    global _x\n"
            },
        }.items():
            with self.subTest(label=label):
                tests, _ = _select([("M", "rust/Cargo.lock")], **kwargs)
                self.assertIsNone(tests)

    def test_changed_test_file_is_selected_alone(self) -> None:
        tests, _ = _select([("M", "backend/tests/test_registry.py")])
        self.assertEqual(tests, ["tests/test_registry.py"])

    def test_changed_test_file_brings_the_tests_that_import_it(self) -> None:
        sources = {
            "backend/tests/test_sync.py": "from tests.test_registry import Fake\n",
            "backend/tests/test_api_trees.py": "from .test_sync import helper\n",
            "backend/tests/test_tree_service.py": "import test_registry\n",
            "backend/tests/test_rust_bridge.py": "def broken(:\n",
        }
        tests, reasons = select(
            TEST_MAP,
            [("M", "backend/tests/test_registry.py")],
            diff_for=lambda _path: "",
            head_source_for=lambda path: sources.get(path, ""),
            head_tests=set(HEAD_TESTS),
            bridge_importers=set(BRIDGE),
        )
        # Direct, transitive, every import spelling, and the unparsable file.
        self.assertEqual(tests, sorted(HEAD_TESTS))
        self.assertIn("4 test file(s) import a changed test file", reasons)

    def test_test_files_the_map_has_not_seen_are_always_selected(self) -> None:
        head = HEAD_TESTS | {"tests/test_brand_new.py"}
        tests, _ = _select([("M", "backend/tests/test_registry.py")], head_tests=head)
        self.assertEqual(tests, ["tests/test_brand_new.py", "tests/test_registry.py"])

    def test_paths_outside_the_backend_are_ignored(self) -> None:
        tests, _ = _select(
            [("M", "frontend/src/App.tsx"), ("M", "backend/tests/test_registry.py")]
        )
        self.assertEqual(tests, ["tests/test_registry.py"])

    def test_empty_selection_runs_everything(self) -> None:
        tests, _ = _select([("M", "docs/readme.md")])
        self.assertIsNone(tests)


if __name__ == "__main__":
    unittest.main()
