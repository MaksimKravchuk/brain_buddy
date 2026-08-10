from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
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


def _valid_handoff() -> dict[str, Any]:
    return {
        "schema_version": "speckit-hermes-handoff/v1",
        "root_outcome": "Deliver a reviewed planning change.",
        "artifacts": {
            "spec": "specs/005-new-feature/spec.md",
            "plan": "specs/005-new-feature/plan.md",
            "tasks": "specs/005-new-feature/tasks.md",
            "checklist": "specs/005-new-feature/checklists/requirements.md",
            "adrs": [],
        },
        "planning_review": {
            "run_id": "run123",
            "risk": "medium",
            "status": "approved",
            "reviewers": [
                "requirements-consistency",
                "architecture-consistency",
                "testability-evidence",
                "privacy-consent-security",
                "ux-accessibility-mobile",
            ],
        },
        "product_decisions": [],
        "lanes": [
            {
                "id": "backend-contract",
                "outcome": "Implement the backend contract.",
                "depends_on": [],
                "task_refs": ["T001"],
                "scope_paths": ["backend/app/example.py"],
                "exclusive_writer_scope": ["backend/app/example.py"],
                "acceptance_evidence": ["Targeted backend tests pass."],
            },
            {
                "id": "frontend-flow",
                "outcome": "Implement the frontend flow.",
                "depends_on": ["backend-contract"],
                "task_refs": ["T002"],
                "scope_paths": ["frontend/src/example.tsx"],
                "exclusive_writer_scope": ["frontend/src/example.tsx"],
                "acceptance_evidence": ["Targeted frontend tests pass."],
            },
        ],
        "risks": [],
        "non_goals": ["No deployment change."],
    }


def _high_risk_handoff() -> dict[str, Any]:
    """A high-risk handoff carrying everything the class demands.

    Every gate `high` adds is satisfied here — the adversarial lens, the
    sign-off record, and the panel provenance — so each test below can remove
    exactly one and fail on the property it is about instead of on whichever
    requirement the validator happens to reach first.
    """
    handoff = _valid_handoff()
    review = handoff["planning_review"]
    review["risk"] = "high"
    review["reviewers"].append("adversarial-high-risk")
    # A clean panel states that it was clean. `[]` and `false` are the record;
    # an absent field is unknown provenance, which at this class is not the
    # same claim.
    review["degraded_lenses"] = []
    review["oracle_unknown_lenses"] = []
    review["single_provider_panel"] = False
    review["human_signoff"] = {
        "approved_by": "maksim.v.kravchuk@gmail.com",
        "approved_on": "2026-08-10",
        "run_id": "run123",
        "artifacts_digest": "a" * 64,
        "rationale": "Reviewed the high-risk surface and accept the residual risk.",
    }
    return handoff


class CheckSpecKitSpecsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.specs_dir = self.repo_root / "specs"
        self.specs_dir.mkdir()
        check_spec_kit_specs.REPO_ROOT = self.repo_root
        check_spec_kit_specs.SPECS_DIR = self.specs_dir
        self._validator_path = check_spec_kit_specs.HANDOFF_VALIDATOR_PATH
        self._validator_module = check_spec_kit_specs.HANDOFF_VALIDATOR_MODULE

    def tearDown(self) -> None:
        check_spec_kit_specs.HANDOFF_VALIDATOR_PATH = self._validator_path
        check_spec_kit_specs.HANDOFF_VALIDATOR_MODULE = self._validator_module
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

    def _write_planned_feature(self, tasks_text: str) -> Path:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "006-delivery-gate"
        (feature / "checklists").mkdir(parents=True)
        (feature / "intake.md").write_text("# Intake\n")
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "checklists" / "requirements.md").write_text("# Checklist\n")
        (feature / "design.md").write_text("# Design\n")
        (feature / "plan.md").write_text("# Plan\n")
        (feature / "tasks.md").write_text(tasks_text)
        return feature

    def test_planned_but_unbuilt_feature_does_not_require_acceptance(self) -> None:
        """Demanding acceptance.md at planning time would force a fabricated verdict."""
        self._write_planned_feature("# Tasks\n\n- [x] T001 done\n- [ ] T002 not yet\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)

    def test_delivered_feature_requires_acceptance_evidence(self) -> None:
        self._write_planned_feature("# Tasks\n\n- [x] T001 done\n- [x] T002 done\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        for name in ("acceptance.md", "traceability.md", "report.md"):
            self.assertIn(name, stderr)

    def test_tasks_without_checkboxes_is_not_treated_as_delivered(self) -> None:
        self._write_planned_feature("# Tasks\n\nProse plan with no checkboxes.\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)

    def test_delivered_feature_passes_with_full_evidence(self) -> None:
        feature = self._write_planned_feature("# Tasks\n\n- [x] T001 done\n")
        (feature / "acceptance.md").write_text("VERDICT: accept\n")
        (feature / "traceability.md").write_text("| FR-001 | ... |\n")
        (feature / "report.md").write_text("# Report\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)

    def test_new_feature_does_not_require_legacy_handoff(self) -> None:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "004-new-feature"
        (feature / "checklists").mkdir(parents=True)
        (feature / "intake.md").write_text("# Intake\n")
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "checklists" / "requirements.md").write_text("# Checklist\n")
        (feature / "design.md").write_text("# Design\n")
        (feature / "plan.md").write_text("# Plan\n")
        (feature / "tasks.md").write_text("# Tasks\n")

        result, stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)
        self.assertIn("Spec Kit artifact check passed.", stdout)

    def _write_feature_with_handoff(self, handoff_text: str) -> Path:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "005-new-feature"
        (feature / "checklists").mkdir(parents=True)
        (feature / "intake.md").write_text("# Intake\n")
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "checklists" / "requirements.md").write_text("# Checklist\n")
        (feature / "design.md").write_text("# Design\n")
        (feature / "plan.md").write_text("# Plan\n")
        (feature / "tasks.md").write_text("# Tasks\n")
        (feature / "hermes-handoff.json").write_text(handoff_text)
        return feature

    def test_valid_handoff_passes(self) -> None:
        self._write_feature_with_handoff(json.dumps(_valid_handoff()))

        result, stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)
        self.assertIn("Spec Kit artifact check passed.", stdout)

    def test_malformed_handoff_json_fails(self) -> None:
        self._write_feature_with_handoff("{not json\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("specs/005-new-feature/hermes-handoff.json: invalid JSON", stderr)

    def test_empty_handoff_object_fails(self) -> None:
        self._write_feature_with_handoff("{}\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "specs/005-new-feature/hermes-handoff.json: invalid Hermes handoff "
            "(unsupported handoff schema_version)",
            stderr,
        )

    def test_handoff_json_array_fails(self) -> None:
        self._write_feature_with_handoff("[]\n")

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("handoff must be a JSON object", stderr)

    def test_unapproved_planning_review_status_fails(self) -> None:
        handoff = _valid_handoff()
        handoff["planning_review"]["status"] = "technical-changes-required"
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("planning_review.status must be approved", stderr)

    def test_missing_required_reviewer_role_fails(self) -> None:
        handoff = _valid_handoff()
        handoff["planning_review"]["reviewers"] = [
            "requirements-consistency",
            "architecture-consistency",
            "privacy-consent-security",
            "ux-accessibility-mobile",
            "some-other-role",
        ]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "planning_review.reviewers missing ['testability-evidence']", stderr
        )

    def test_high_risk_handoff_requires_adversarial_reviewer(self) -> None:
        handoff = _valid_handoff()
        handoff["planning_review"]["risk"] = "high"
        # A valid sign-off, so this test reaches the assertion it is about.
        # Without it the newer high-risk sign-off requirement fires first.
        handoff["planning_review"]["human_signoff"] = {
            "approved_by": "maksim.v.kravchuk@gmail.com",
            "approved_on": "2026-08-10",
            "run_id": "run123",
            "artifacts_digest": "a" * 64,
            "rationale": "Reviewed the high-risk surface and accept the residual risk.",
        }
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "high-risk handoff requires adversarial-high-risk reviewer", stderr
        )

    def test_high_risk_handoff_without_signoff_fails_the_spec_gate(self) -> None:
        """The bypass Codex found: approved high-risk with no approval record."""
        handoff = _valid_handoff()
        handoff["planning_review"]["risk"] = "high"
        handoff["planning_review"]["reviewers"].append("adversarial-high-risk")
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("requires a human_signoff record", stderr)

    def test_high_risk_degraded_handoff_carries_the_degradation(self) -> None:
        """ADR-0014: a degraded panel may pass the gate. It may not pass unsaid."""
        handoff = _high_risk_handoff()
        handoff["planning_review"]["degraded_lenses"] = [
            "requirements-consistency",
            "testability-evidence",
        ]
        handoff["planning_review"]["single_provider_panel"] = True
        self._write_feature_with_handoff(json.dumps(handoff))

        result, stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)
        self.assertIn("Spec Kit artifact check passed.", stdout)

    def test_high_risk_handoff_omitting_degraded_lenses_fails(self) -> None:
        """ADR-0012 correction D in mirror image: the gate measured degradation
        and the authorizing artifact could not carry it."""
        handoff = _high_risk_handoff()
        del handoff["planning_review"]["degraded_lenses"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("must state planning_review.degraded_lenses", stderr)

    def test_high_risk_handoff_omitting_unknown_provenance_fails(self) -> None:
        """The hole the other two fields leave open on their own.

        A panel of hand-written reviews carries no `oracle` at all, so
        `summarize` reports no degraded lenses and — with an empty histogram —
        `single_provider_panel: false`. Both fields are then honestly `[]` and
        `false` while nothing about the panel was ever measured. Only naming
        the unmeasured lenses separates that from a verified clean panel.
        """
        handoff = _high_risk_handoff()
        del handoff["planning_review"]["oracle_unknown_lenses"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("must state planning_review.oracle_unknown_lenses", stderr)

    def test_high_risk_handoff_omitting_single_provider_panel_fails(self) -> None:
        handoff = _high_risk_handoff()
        del handoff["planning_review"]["single_provider_panel"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("must state planning_review.single_provider_panel", stderr)

    def test_high_risk_clean_panel_must_say_so_explicitly(self) -> None:
        """The cost of requiring the fields: `[]` and `false` get written out.

        A configured, uncorrelated high-risk campaign is the case that pays for
        this rule, so it is asserted rather than assumed.
        """
        self._write_feature_with_handoff(json.dumps(_high_risk_handoff()))

        result, stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)
        self.assertIn("Spec Kit artifact check passed.", stdout)

    def test_degraded_lens_missing_from_the_panel_fails(self) -> None:
        """A misspelled role is degradation recorded under a name nobody reads."""
        handoff = _valid_handoff()
        handoff["planning_review"]["degraded_lenses"] = ["testability_evidence"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("is not in planning_review.reviewers", stderr)

    def test_medium_risk_may_state_provenance_without_being_required_to(self) -> None:
        """Below high the panel is sufficient evidence on its own, so provenance
        is welcome but not owed — and must not be rejected as an unknown key."""
        handoff = _valid_handoff()
        handoff["planning_review"]["degraded_lenses"] = ["testability-evidence"]
        handoff["planning_review"]["single_provider_panel"] = True
        self._write_feature_with_handoff(json.dumps(handoff))

        result, stdout, stderr = self._run_check()

        self.assertEqual(result, 0, stderr)
        self.assertIn("Spec Kit artifact check passed.", stdout)

    def test_lane_dependency_cycle_fails(self) -> None:
        handoff = _valid_handoff()
        handoff["lanes"][0]["depends_on"] = ["frontend-flow"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("lane dependency cycle detected", stderr)

    def test_unknown_lane_dependency_fails(self) -> None:
        handoff = _valid_handoff()
        handoff["lanes"][1]["depends_on"] = ["missing-lane"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn(
            "lane frontend-flow has unknown dependencies: ['missing-lane']", stderr
        )

    def test_overlapping_exclusive_writer_scope_fails(self) -> None:
        handoff = _valid_handoff()
        handoff["lanes"][1]["exclusive_writer_scope"] = ["backend/app/example.py"]
        self._write_feature_with_handoff(json.dumps(handoff))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("exclusive writer scope reused across lanes", stderr)

    def test_missing_handoff_validator_fails_closed(self) -> None:
        check_spec_kit_specs.HANDOFF_VALIDATOR_PATH = (
            self.repo_root / "scripts" / "does_not_exist.py"
        )
        check_spec_kit_specs.HANDOFF_VALIDATOR_MODULE = "absent_handoff_validator"
        self._write_feature_with_handoff(json.dumps(_valid_handoff()))

        result, _stdout, stderr = self._run_check()

        self.assertEqual(result, 1)
        self.assertIn("handoff validator unavailable", stderr)

    def test_directory_shaped_required_artifact_fails(self) -> None:
        check_spec_kit_specs.GRANDFATHERED = {}
        feature = self.specs_dir / "003-new-feature"
        (feature / "checklists" / "requirements.md").mkdir(parents=True)
        (feature / "intake.md").write_text("# Intake\n")
        (feature / "spec.md").write_text("# Spec\n")
        (feature / "design.md").write_text("# Design\n")
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
