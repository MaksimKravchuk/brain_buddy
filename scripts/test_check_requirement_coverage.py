"""Contract tests for the requirement-to-test coverage gate."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_requirement_coverage.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_requirement_coverage", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SPEC = (
    "## Requirements\n"
    "- **FR-001**: System MUST sign the user in.\n"
    "- **FR-002**: System MUST sign the user out.\n"
    "## Success Criteria\n"
    "- **SC-001**: Sign-in completes in under two seconds.\n"
)


class RequirementCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def build(self, tmp: str, *, backend_test: str) -> tuple[Path, Path]:
        root = Path(tmp)
        feature_dir = root / "specs" / "006-example"
        feature_dir.mkdir(parents=True)
        (feature_dir / "spec.md").write_text(SPEC, encoding="utf-8")
        tests = root / "backend" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_auth.py").write_text(backend_test, encoding="utf-8")
        return root, feature_dir

    def test_requirements_are_read_from_definitions_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _root, feature_dir = self.build(tmp, backend_test="")
            self.assertEqual(
                self.module.requirements(feature_dir / "spec.md"),
                ["FR-001", "FR-002", "SC-001"],
            )

    def test_id_named_in_a_test_counts_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                backend_test=(
                    "def test_sign_in_FR_001():\n    pass\n"
                    "def test_covers_FR-001_and_FR-002():\n    pass\n"
                ),
            )
            result = self.module.coverage(root, feature_dir)
            self.assertTrue(result["FR-001"])
            self.assertTrue(result["FR-002"])

    def test_unnamed_requirement_is_uncovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp, backend_test="def test_covers_FR-001():\n    pass\n"
            )
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["SC-001"], [])
            self.assertEqual(result["FR-002"], [])

    def test_non_test_files_are_not_scanned(self) -> None:
        """A requirement id in product code is not coverage."""
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(tmp, backend_test="")
            source = root / "backend" / "app"
            source.mkdir(parents=True)
            (source / "auth.py").write_text("# implements FR-001\n", encoding="utf-8")
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], [])


if __name__ == "__main__":
    unittest.main()
