from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

SCRIPT_PATH = Path(__file__).with_name("check_spec_kit_specs.py")
spec = importlib.util.spec_from_file_location("check_spec_kit_specs", SCRIPT_PATH)
assert spec is not None
check_spec_kit_specs = cast(Any, importlib.util.module_from_spec(spec))
assert spec.loader is not None
sys.modules["check_spec_kit_specs"] = check_spec_kit_specs
spec.loader.exec_module(check_spec_kit_specs)


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class CheckSpecKitSpecsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.specs_dir = self.repo_root / "specs"
        self.specs_dir.mkdir()
        check_spec_kit_specs.REPO_ROOT = self.repo_root
        check_spec_kit_specs.SPECS_DIR = self.specs_dir

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_check(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = check_spec_kit_specs.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def _set_grandfathered_baseline(self, baseline: dict[str, str]) -> None:
        check_spec_kit_specs.GRANDFATHERED = {
            "002-async-voice-workflows": {
                "reason": "test grandfathered package",
                "baseline_sha256": baseline,
            }
        }

    def test_deleted_grandfathered_normative_file_fails(self) -> None:
        original_spec = "original historical spec\n"
        feature = self.specs_dir / "002-async-voice-workflows"
        feature.mkdir()
        (feature / "spec.md").write_text(original_spec)
        self._set_grandfathered_baseline(
            {
                "spec.md": _sha256_text(original_spec),
                "acceptance-tests.md": _sha256_text("original acceptance tests\n"),
            }
        )

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "missing grandfathered normative acceptance-tests.md",
            stderr,
        )

    def test_modified_grandfathered_spec_requires_current_artifacts(self) -> None:
        feature = self.specs_dir / "002-async-voice-workflows"
        feature.mkdir()
        (feature / "spec.md").write_text("modified historical spec\n")
        (feature / "acceptance-tests.md").write_text("original acceptance tests\n")
        self._set_grandfathered_baseline(
            {
                "spec.md": _sha256_text("original historical spec\n"),
                "acceptance-tests.md": _sha256_text("original acceptance tests\n"),
            }
        )

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("missing plan.md", stderr)
        self.assertIn("missing tasks.md", stderr)
        self.assertIn("/speckit-checklist -> /speckit-tasks", stderr)

    def test_new_feature_requires_validated_handoff_artifact(self) -> None:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "004-new-feature"
        (feature / "checklists").mkdir(parents=True)
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "checklists" / "requirements.md").write_text("# Checklist\n")
        (feature / "plan.md").write_text("# Plan\n")
        (feature / "tasks.md").write_text("# Tasks\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("missing hermes-handoff.json", stderr)

    def test_directory_shaped_required_artifact_fails(self) -> None:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "003-new-feature"
        (feature / "checklists" / "requirements.md").mkdir(parents=True)
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "plan.md").write_text("# Plan\n")
        (feature / "tasks.md").write_text("# Tasks\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "specs/003-new-feature/checklists/requirements.md: must be a regular file",
            stderr,
        )


if __name__ == "__main__":
    unittest.main()
