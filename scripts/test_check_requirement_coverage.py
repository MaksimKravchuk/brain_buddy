"""Contract tests for the requirement-to-test coverage gate."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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
    def test_script_unit_tests_count_but_product_gate_scripts_do_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(tmp, backend_test="")
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "test_delivery.py").write_text('"""006-FR-001"""')
            (scripts / "check_spec.py").write_text("# 006-FR-002")
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], ["scripts/test_delivery.py"])
            self.assertEqual(result["FR-002"], [])

    def test_rust_integration_tests_count_but_product_source_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(tmp, backend_test="")
            tests = root / "cli/tests"
            tests.mkdir(parents=True)
            (tests / "journey.rs").write_text("fn journey_006_fr_001() {}")
            source = root / "cli/src"
            source.mkdir(parents=True)
            (source / "main.rs").write_text("// 006-FR-002")
            result = self.module.coverage(root, feature_dir)
            self.assertEqual(result["FR-001"], ["cli/tests/journey.rs"])
            self.assertEqual(result["FR-002"], [])

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

        The (since removed) Expo client's `mobile/integration/run.ts` was listed
        as a test tree and then discarded by the filename hints, so every
        integration assertion in the repository was invisible to this gate: a
        feature could name an id only from an integration test and still be
        reported as untraced. The remaining dedicated trees happen to carry a
        hint in their own path, so the property is pinned with a hint-free
        tree patched in.
        """
        module = load_module()
        module.DEDICATED_TEST_TREES = ("client/integration",)
        module.TEST_TREES = module.DEDICATED_TEST_TREES + module.MIXED_TEST_TREES
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "client" / "integration").mkdir(parents=True)
            (root / "client" / "integration" / "run.ts").write_text(
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
            (root / "frontend" / "src" / "features").mkdir(parents=True)
            (root / "frontend" / "src" / "features" / "widget.ts").write_text(
                "export const x = 1;", encoding="utf-8"
            )

            found = {p.name for p in module.iter_test_files(root)}

        self.assertNotIn("widget.ts", found)


# Feature 020 has requirements whose only honest evidence is Swift (research
# R19): the iOS package tests and the macOS host tests.
SWIFT_SPEC = (
    "## Requirements\n"
    "- **FR-001**: Formulation clock.\n"
    "- **FR-002**: Substantive change.\n"
    "- **FR-041**: Mac shows a coming-later row.\n"
    "- **FR-047**: Account-less iOS parks on device.\n"
    "## Success Criteria\n"
    "- **SC-002**: Decisions are fast.\n"
)


class SwiftAndSliceCoverageTests(unittest.TestCase):
    """The gate traces Swift test trees and can check one PR slice's ids."""

    def setUp(self) -> None:
        self.module = load_module()

    def build(self, tmp: str, files: dict[str, str]) -> tuple[Path, Path]:
        root = Path(tmp)
        feature_dir = root / "specs" / "020-weekly-review"
        feature_dir.mkdir(parents=True)
        (feature_dir / "spec.md").write_text(SWIFT_SPEC, encoding="utf-8")
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root, feature_dir

    def run_main(self, root: Path, argv: list[str]) -> tuple[int, str, str]:
        self.module.REPO_ROOT = root
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.module.main(argv)
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def report(out: str) -> dict:
        # `--json` prints the report, then the pass line, on stdout.
        return json.JSONDecoder().raw_decode(out)[0]

    def test_swift_tests_in_ios_package_and_macos_trees_satisfy_the_gate(self) -> None:
        ios_test = "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/LocalParkTests.swift"
        mac_test = "macos/Tests/BrainBuddyMacTests/SidebarEntriesTests.swift"
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    ios_test: "func test_020_FR_047_accountLessDeviceParks() {}\n",
                    mac_test: (
                        '@Test("020-FR-041 weekly review row is coming later")\n'
                        "func comingLaterRow() {}\n"
                    ),
                },
            )

            result = self.module.coverage(root, feature_dir)

        self.assertEqual(result["FR-047"], [ios_test])
        self.assertEqual(result["FR-041"], [mac_test])

    def test_swift_outside_the_test_trees_is_not_coverage(self) -> None:
        """App and package sources are product code, not evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    "ios/BrainBuddy/App/RootView.swift": "// 020-FR-047\n",
                    "ios/BrainBuddyKit/Sources/BrainBuddyCore/Park.swift": (
                        "// 020-FR-047\n"
                    ),
                    "macos/Sources/BrainBuddyMac/ContentView.swift": "// 020-FR-041\n",
                },
            )

            result = self.module.coverage(root, feature_dir)

        self.assertEqual(result["FR-047"], [])
        self.assertEqual(result["FR-041"], [])

    def test_requirements_filter_checks_only_the_listed_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    "backend/tests/test_review_formulation.py": (
                        "def test_020_FR_001_clock_starts():\n    pass\n"
                        'allure.story("020-SC-002 decisions are fast")\n'
                    ),
                },
            )

            code, out, err = self.run_main(
                root,
                [
                    str(feature_dir),
                    "--requirements",
                    "020-FR-001,020-SC-002",
                    "--json",
                ],
            )

        self.assertEqual(code, 0, err)
        report = self.report(out)
        self.assertEqual(sorted(report["coverage"]), ["FR-001", "SC-002"])
        self.assertEqual(report["uncovered"], [])
        # A consumer must be able to tell a slice check from the full gate.
        self.assertEqual(report["requirements_filter"], ["FR-001", "SC-002"])

    def test_requirements_filter_still_fails_a_listed_uncovered_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    "backend/tests/test_review_formulation.py": (
                        "def test_020_FR_001_clock_starts():\n    pass\n"
                    ),
                },
            )

            code, out, err = self.run_main(
                root, [str(feature_dir), "--requirements", "020-FR-001, 020-SC-002"]
            )

        self.assertEqual(code, 1)
        self.assertIn("020-SC-002", err)
        self.assertNotIn("020-FR-002", out + err)
        self.assertNotIn("020-FR-041", out + err)

    def test_without_the_filter_every_defined_id_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    "backend/tests/test_review_formulation.py": (
                        "def test_020_FR_001_clock_starts():\n    pass\n"
                        'allure.story("020-SC-002 decisions are fast")\n'
                    ),
                },
            )

            code, out, _err = self.run_main(root, [str(feature_dir), "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(self.report(out)["uncovered"], ["FR-002", "FR-041", "FR-047"])
        self.assertIsNone(self.report(out)["requirements_filter"])

    def test_requirements_filter_rejects_an_id_spec_does_not_define(self) -> None:
        """A typo or a stale manifest id must not pass as 'nothing to check'."""
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(
                tmp,
                {
                    "backend/tests/test_review_formulation.py": (
                        "def test_020_FR_001_clock_starts():\n    pass\n"
                    ),
                },
            )

            with self.assertRaises(SystemExit) as raised:
                self.run_main(
                    root,
                    [str(feature_dir), "--requirements", "020-FR-001,020-FR-099"],
                )

        self.assertIn("020-FR-099", str(raised.exception.code))

    def test_requirements_filter_rejects_bare_and_foreign_ids(self) -> None:
        """The filter keeps the feature-qualified rule of the gate itself."""
        with tempfile.TemporaryDirectory() as tmp:
            root, feature_dir = self.build(tmp, {})

            for value in ("FR-001", "019-FR-001", "020-XX-001", ""):
                with self.subTest(value=value):
                    with self.assertRaises(SystemExit) as raised:
                        self.run_main(
                            root, [str(feature_dir), "--requirements", value]
                        )
                    # The script's own rejection, not an argparse usage error.
                    self.assertIsInstance(raised.exception.code, str)
                    self.assertIn("--requirements", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
