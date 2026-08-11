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

    def test_feature_qualified_id_counts_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                backend_test=(
                    "def test_006_FR_001_signs_in():\n    pass\n"
                    'allure.story("006-FR-002 signs out")\n'
                ),
            )
            result = self.module.coverage(root, feature_dir)
            self.assertTrue(result["FR-001"])
            self.assertTrue(result["FR-002"])

    def test_bare_id_does_not_count_as_covered(self) -> None:
        """Regression: bare ids let another feature's tests satisfy this gate.

        Every feature restarts numbering at FR-001, so an unqualified match
        against the whole test tree would score a feature green off unrelated
        tests while its own requirements went untested.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                backend_test=(
                    "def test_sign_in_FR_001():\n    pass\n"
                    'allure.story("FR-002 signs out")\n'
                ),
            )
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], [])
            self.assertEqual(result["FR-002"], [])

    def test_another_features_qualified_id_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp, backend_test="def test_003_FR_001_other_feature():\n    pass\n"
            )
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], [])

    def test_unnamed_requirement_is_uncovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp, backend_test="def test_covers_006_FR_001():\n    pass\n"
            )
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["SC-001"], [])
            self.assertEqual(result["FR-002"], [])

    def test_malformed_feature_directory_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "not-numbered"
            bad.mkdir()
            with self.assertRaises(SystemExit):
                self.module.feature_number(bad)

    def test_non_test_files_are_not_scanned(self) -> None:
        """A requirement id in product code is not coverage."""
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(tmp, backend_test="")
            source = root / "backend" / "app"
            source.mkdir(parents=True)
            (source / "auth.py").write_text(
                "# implements 006-FR-001\n", encoding="utf-8"
            )
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], [])

    def test_dedicated_test_tree_is_scanned_regardless_of_filename(self):
        """A tree that holds nothing but tests must not be re-filtered by name.

        `mobile/integration/run.ts` was listed as a test tree and then discarded
        by the filename hints, so every integration assertion in the repository
        was invisible to this gate: a feature could name an id only from an
        integration test and still be reported as untraced.
        """
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mobile" / "integration").mkdir(parents=True)
            (root / "mobile" / "integration" / "run.ts").write_text(
                'assert(ok, "006-FR-004 create-then-attach lands both");',
                encoding="utf-8",
            )

            found = {p.name for p in module.iter_test_files(root)}

        self.assertIn("run.ts", found)

    def test_mixed_tree_still_requires_a_filename_hint(self):
        """The hint filter must survive for trees that also hold product code."""
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mobile" / "src" / "features").mkdir(parents=True)
            (root / "mobile" / "src" / "features" / "widget.ts").write_text(
                "export const x = 1;", encoding="utf-8"
            )

            found = {p.name for p in module.iter_test_files(root)}

        self.assertNotIn("widget.ts", found)


if __name__ == "__main__":
    unittest.main()
