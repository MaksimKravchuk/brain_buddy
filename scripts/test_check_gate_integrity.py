"""Contract tests for the gate-integrity guard.

The guard exists because an agent that can edit the gates it is judged by can
quietly make itself pass. These tests assert that the two layers actually bite:
invariants cannot be waived, and a changed guarded file is reported.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_gate_integrity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_gate_integrity", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GateIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_repository_invariants_hold(self) -> None:
        self.assertEqual(self.module.check_invariants(ROOT), [])

    def test_repository_hashes_match_the_manifest(self) -> None:
        failures, _current = self.module.check_hashes(ROOT)
        self.assertEqual(failures, [])

    def test_every_guarded_file_exists(self) -> None:
        for relative in self.module.GUARDED_FILES:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_the_guard_guards_itself(self) -> None:
        """A guard that does not protect its own source is trivially removable."""
        self.assertIn("scripts/check_gate_integrity.py", self.module.GUARDED_FILES)

    def test_manifest_covers_exactly_the_guarded_files(self) -> None:
        manifest = self.module.load_manifest()
        self.assertEqual(set(manifest), set(self.module.GUARDED_FILES))

    def test_no_script_test_file_is_orphaned(self) -> None:
        """A test nothing runs is documentation that looks like enforcement.

        This class of defect showed up three times in one change: the
        gate-integrity guard was absent from CI, the report renderer's tests
        were written and never wired up, and `test_validate_backend_coverage`
        was referenced by nothing at all. Each looked enforced from the inside.
        Guarding the class is cheaper than finding the next instance.
        """
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        orphans = [
            path.name
            for path in sorted((ROOT / "scripts").glob("test_*.py"))
            if path.name not in makefile
        ]
        self.assertEqual(orphans, [], f"script tests no make target runs: {orphans}")


class InvariantEnforcementTests(unittest.TestCase):
    """Each invariant must actually fail when its property is removed."""

    def setUp(self) -> None:
        self.module = load_module()

    def _fake_root(self, tmp: str) -> Path:
        """A copy of every file an invariant reads, editable in isolation.

        Deliberately the union of the guarded files and the invariant paths.
        Copying only `GUARDED_FILES` would leave any invariant on an unhashed
        file — the CI ones, for instance — reporting MISSING in every mutation
        test, so `_assert_invariant_fires` would see a non-empty failure list
        no matter what the mutation did and stop proving anything.
        """
        fake = Path(tmp)
        wanted = set(self.module.GUARDED_FILES)
        wanted.update(invariant.path for invariant in self.module.INVARIANTS)
        for relative in sorted(wanted):
            source = ROOT / relative
            target = fake / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        return fake

    def test_the_fake_root_starts_clean(self) -> None:
        """The mutation harness must prove the mutation caused the failure."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.module.check_invariants(self._fake_root(tmp)), [])

    def _assert_invariant_fires(self, tmp: str, relative: str, mutate) -> str:
        fake = self._fake_root(tmp)
        path = fake / relative
        path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
        failures = self.module.check_invariants(fake)
        self.assertTrue(failures, f"mutating {relative} did not trip any invariant")
        return "\n".join(failures)

    def test_removing_the_verdict_check_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace('"changes-required" in verdicts or ', ""),
            )
            self.assertIn("changes-required blocks the gate", report)

    def test_lowering_the_default_risk_class_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace('DEFAULT_RISK = "medium"', 'DEFAULT_RISK = "low"'),
            )
            self.assertIn("unknown risk defaults to medium", report)

    def test_dropping_the_missing_evidence_escalation_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    'elif missing_roles or unknown_oracle_roles:\n        status = "escalated"',
                    'elif False:\n        status = "escalated"',
                ),
            )
            self.assertIn("missing mandatory evidence escalates", report)

    def test_removing_the_acceptance_expiry_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace("founder_acceptance.expires_on", "removed"),
            )
            self.assertIn("time-bounded", report)

    def test_trusting_the_stored_digest_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "current_digest = review_artifacts_digest(feature_dir)",
                    "current_digest = recorded_digest",
                ),
            )
            self.assertIn("recomputed, not trusted", report)

    def test_dropping_the_artifact_drift_escalation_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    'if artifacts_changed:\n        status = "escalated"',
                    'if False:\n        status = "escalated"',
                ),
            )
            self.assertIn("drift after preflight", report)

    def test_dropping_the_high_risk_signoff_requirement_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "if risk == HUMAN_SIGNOFF_REQUIRED_AT:\n        if not isinstance(signoff, dict):",
                    "if False:\n        if not isinstance(signoff, dict):",
                ),
            )
            self.assertIn("require the sign-off record", report)

    def test_blanket_shell_permission_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".claude/settings.json",
                lambda text: text.replace('"Bash(make:*)"', '"Bash(*)"'),
            )
            self.assertIn("no blanket shell permission", report)

    def test_preapproving_git_push_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".claude/settings.json",
                lambda text: text.replace(
                    '"Bash(git fetch:*)"', '"Bash(git fetch:*)",\n      "Bash(git push:*)"'
                ),
            )
            self.assertIn("landing and push stay gated", report)

    def test_dropping_a_validator_from_check_specs_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "Makefile",
                lambda text: text.replace(
                    "\tpython3 scripts/check_speckit_manifests.py\n", ""
                ),
            )
            self.assertIn("check-specs runs the spec and manifest guards", report)

    def test_dropping_feature_requirement_coverage_from_check_specs_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "Makefile",
                lambda text: text.replace(
                    "\tpython3 scripts/check_requirement_coverage.py specs/019-miro-like-crt-canvas\n",
                    "",
                ),
            )
            self.assertIn("check-specs runs feature requirement coverage", report)

    def test_skipping_external_adapter_pin_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "if measured != adapter_sha256:", "if False:",
                ),
            )
            self.assertIn("external adapter rejects a wrong executable hash", report)

    def test_claiming_verified_model_identity_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    '"integration": "external-unverified",\n            "model": "unverified",',
                    '"integration": "external",\n            "model": model,',
                ),
            )
            self.assertIn("external model identity is marked unverified", report)

    def test_replacing_the_resolved_executable_with_a_bare_name_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "            executable,\n            \"exec\",",
                    "            INTEGRATION_CLI[\"codex\"],\n            \"exec\",",
                ),
            )
            self.assertIn("resolved reviewer executable is used", report)

    def test_removing_the_summarize_preflight_boundary_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "    if not context_path.is_file():\n"
                    "        raise ReviewError(\"Planning preflight was not completed for this run\")",
                    "    if False:\n"
                    "        raise ReviewError(\"Planning preflight was not completed for this run\")",
                ),
            )
            self.assertIn("summarize requires preflight context", report)

    def test_trusting_cached_risk_instead_of_recomputing_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "    derived = derive_risk(feature_dir)\n"
                    "    if isinstance(derived, str) and derived in DERIVABLE_RISKS:\n"
                    "        risk = stricter_risk(risk, derived)",
                    "    derived = context.get(\"derived_risk\")\n"
                    "    if isinstance(derived, str) and derived in DERIVABLE_RISKS:\n"
                    "        risk = stricter_risk(risk, derived)",
                ),
            )
            self.assertIn("summarize recomputes derived risk", report)

    def test_allowing_unknown_oracle_provenance_to_pass_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "    elif missing_roles or unknown_oracle_roles:",
                    "    elif missing_roles:",
                ),
            )
            self.assertIn("unknown reviewer provenance escalates", report)

    def test_weakening_codex_oracle_validation_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    'payload.get("integration") != "codex"',
                    'payload.get("integration") != "claude"',
                ),
            )
            self.assertIn("Codex oracle provenance is validated", report)

    def test_dropping_the_provenance_stamp_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace('review["oracle"] = oracle', "pass"),
            )
            self.assertIn("stamps reviewer provenance", report)

    def test_dropping_degradation_from_the_summary_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    'summary["degraded_lenses"] = degraded', "pass"
                ),
            )
            self.assertIn("degradation reaches the summary", report)

    def test_ignoring_a_failed_reviewer_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/spec_kit_planning_review.py",
                lambda text: text.replace(
                    "    if result.returncode != 0:\n"
                    "        # Reviewer failures stay hard failures.",
                    "    if False:\n"
                    "        # Reviewer failures stay hard failures.",
                ),
            )
            self.assertIn("reviewer failure stays a hard error", report)

    def test_dropping_provenance_from_the_report_is_caught(self) -> None:
        """Keep the write, drop the render: the trade ADR-0014 made, undone."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                "scripts/render_feature_report.py",
                lambda text: text.replace('"stale_reviews"', '"unused_key"'),
            )
            self.assertIn("renders panel provenance", report)

    def test_dropping_the_integrity_guard_from_ci_is_caught(self) -> None:
        """The Makefile target is only enforcement if CI invokes it."""
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".github/workflows/ci.yml",
                lambda text: text.replace(
                    "          python3 scripts/check_gate_integrity.py\n", ""
                ),
            )
            self.assertIn("CI runs the gate-integrity guard", report)

    def test_dropping_the_manifest_guard_from_ci_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".github/workflows/ci.yml",
                lambda text: text.replace(
                    "          python3 scripts/check_speckit_manifests.py\n", ""
                ),
            )
            self.assertIn("CI runs the preserved-override guard", report)

    def test_dropping_authoritative_check_specs_target_from_ci_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".github/workflows/ci.yml",
                lambda text: text.replace("          make check-specs\n", ""),
            )
            self.assertIn("CI runs the authoritative check-specs target", report)

    def test_removing_a_mandatory_lens_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = self._assert_invariant_fires(
                tmp,
                ".specify/workflows/speckit/review.schema.json",
                lambda text: text.replace('        "privacy-consent-security",\n', ""),
            )
            self.assertIn("mandatory lenses", report)


class HashLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_a_changed_guarded_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "scripts").mkdir(parents=True)
            target = fake / "scripts" / "classify_path_risk.py"
            target.write_text("original\n", encoding="utf-8")

            original_files = self.module.GUARDED_FILES
            original_manifest = self.module.MANIFEST_PATH
            try:
                self.module.GUARDED_FILES = ("scripts/classify_path_risk.py",)
                self.module.MANIFEST_PATH = fake / "manifest.json"
                _failures, current = self.module.check_hashes(fake)
                self.module.write_manifest(current)

                self.assertEqual(self.module.check_hashes(fake)[0], [])

                target.write_text("weakened\n", encoding="utf-8")
                failures, _ = self.module.check_hashes(fake)
                self.assertTrue(any("changed since the manifest" in f for f in failures))
            finally:
                self.module.GUARDED_FILES = original_files
                self.module.MANIFEST_PATH = original_manifest

    def test_manifest_is_valid_json_with_a_files_map(self) -> None:
        data = json.loads(self.module.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertIsInstance(data["files"], dict)
        self.assertTrue(data["files"])


if __name__ == "__main__":
    unittest.main()
