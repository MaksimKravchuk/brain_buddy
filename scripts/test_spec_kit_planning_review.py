"""Contract tests for the portable Spec Kit planning review campaign."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "spec_kit_planning_review.py"
WORKFLOW_PATH = ROOT / ".specify" / "workflows" / "speckit" / "workflow.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("spec_kit_planning_review", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlanningReviewCommandTests(unittest.TestCase):
    def test_codex_review_command_is_read_only_and_ephemeral(self) -> None:
        module = load_module()
        command, _env = module.build_review_command(
            prompt="Review the planning artifacts.",
            schema_path=ROOT / ".specify" / "workflows" / "speckit" / "review.schema.json",
            config=module.ROLE_CONFIGS["requirements-consistency"],
            executable="/resolved/codex",
        )

        self.assertEqual(command[0:2], ["/resolved/codex", "exec"])
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--ephemeral", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("danger-full-access", command)

    def test_adversarial_review_command_uses_codex_read_only_mode(self) -> None:
        module = load_module()
        command, _env = module.build_review_command(
            prompt="Challenge the plan.",
            schema_path=ROOT / ".specify" / "workflows" / "speckit" / "review.schema.json",
            config=module.ROLE_CONFIGS["adversarial-high-risk"],
            executable="/resolved/codex",
        )

        self.assertEqual(command[0:2], ["/resolved/codex", "exec"])
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--ephemeral", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("claude", command)

    def test_run_review_executes_the_same_resolved_binary_it_records(self) -> None:
        module = load_module()
        review = {
            "role": "requirements-consistency",
            "verdict": "pass",
            "summary": "No concerns.",
            "reviewed_files": ["specs/123-example/spec.md"],
            "findings": [],
            "product_decisions": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_dir = root / "specs" / "123-example"
            feature_dir.mkdir(parents=True)
            (feature_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
            (feature_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
            run_dir = root / ".specify" / "workflows" / "runs" / "run1"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(
                json.dumps(
                    {
                        "feature_dir": str(feature_dir),
                        "artifacts_digest": module.review_artifacts_digest(feature_dir),
                    }
                ),
                encoding="utf-8",
            )
            resolved = "/opt/review-tools/codex"
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(review), stderr=""
            )
            with mock.patch.object(module.shutil, "which", return_value=resolved), mock.patch.object(
                module.subprocess, "run", return_value=completed
            ) as run:
                target = module.run_review(
                    root=root,
                    run_id="run1",
                    role="requirements-consistency",
                )

            self.assertTrue(target.is_file())
            self.assertEqual(run.call_args.args[0][0], resolved)
            persisted = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(persisted["oracle"]["executable"], resolved)


class PlanningReviewValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def valid_review(self, *, verdict: str = "pass") -> dict:
        return {
            "role": "architecture-consistency",
            "verdict": verdict,
            "summary": "The plan is internally consistent.",
            "reviewed_files": ["specs/123-example/spec.md", "specs/123-example/plan.md"],
            "findings": [],
            "product_decisions": [],
        }

    def test_validate_review_accepts_clear_review(self) -> None:
        review = self.module.validate_review(
            self.valid_review(), expected_role="architecture-consistency"
        )
        self.assertEqual(review["verdict"], "pass")

    def test_validate_review_rejects_role_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "role"):
            self.module.validate_review(
                self.valid_review(), expected_role="requirements-consistency"
            )

    def test_validate_review_rejects_product_decision_for_technical_category(self) -> None:
        review = self.valid_review(verdict="product-decision-required")
        review["product_decisions"] = [
            {
                "category": "database-index",
                "question": "Which index implementation should we use?",
                "why_needed": "The query needs an index.",
                "options": ["btree", "hash"],
                "affected_acceptance": "Response time",
            }
        ]
        with self.assertRaisesRegex(ValueError, "product decision category"):
            self.module.validate_review(
                review, expected_role="architecture-consistency"
            )

    def test_validate_review_requires_questions_for_product_decision_verdict(self) -> None:
        review = self.valid_review(verdict="product-decision-required")
        with self.assertRaisesRegex(ValueError, "product_decisions"):
            self.module.validate_review(
                review, expected_role="architecture-consistency"
            )

    def test_parse_review_extracts_structured_output_wrapper(self) -> None:
        expected = self.valid_review()
        raw = json.dumps({"structured_output": expected})
        self.assertEqual(self.module.parse_review_output(raw), expected)


class PlanningReviewAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_aggregate_prefers_product_decision_over_technical_changes(self) -> None:
        reviews = [
            {
                "role": "architecture-consistency",
                "verdict": "changes-required",
                "summary": "Technical correction needed.",
                "reviewed_files": ["spec.md"],
                "findings": [
                    {
                        "severity": "blocking",
                        "category": "technical",
                        "description": "Contract mismatch",
                        "evidence": ["plan.md:42"],
                        "recommendation": "Align the contracts",
                    }
                ],
                "product_decisions": [],
            },
            {
                "role": "requirements-consistency",
                "verdict": "product-decision-required",
                "summary": "Acceptance behavior is ambiguous.",
                "reviewed_files": ["spec.md"],
                "findings": [],
                "product_decisions": [
                    {
                        "category": "acceptance-behavior",
                        "question": "Should partial success be visible to the user?",
                        "why_needed": "The acceptance criteria conflict.",
                        "options": ["show partial", "all-or-nothing"],
                        "affected_acceptance": "Submission result",
                    }
                ],
            },
        ]

        summary = self.module.aggregate_reviews(reviews, risk="medium")
        self.assertEqual(summary["status"], "product-decision-required")
        self.assertEqual(len(summary["product_decisions"]), 1)
        self.assertEqual(len(summary["technical_findings"]), 1)

    def test_aggregate_honors_changes_required_verdict_without_blocking_finding(
        self,
    ) -> None:
        """A reviewer's verdict is gate-blocking on its own.

        Regression: the gate used to be derived purely from finding severity,
        so `changes-required` carrying only `important` findings was silently
        aggregated to `approved`.
        """
        reviews = [
            {
                "role": "requirements-consistency",
                "verdict": "changes-required",
                "summary": "Acceptance coverage is incomplete.",
                "reviewed_files": ["specs/123-example/spec.md"],
                "findings": [
                    {
                        "severity": "important",
                        "category": "requirements",
                        "description": "FR-004 has no acceptance scenario.",
                        "evidence": ["specs/123-example/spec.md:88"],
                        "recommendation": "Add an acceptance scenario for FR-004.",
                    }
                ],
                "product_decisions": [],
            },
            {
                "role": "architecture-consistency",
                "verdict": "pass",
                "summary": "Boundaries hold.",
                "reviewed_files": ["specs/123-example/plan.md"],
                "findings": [],
                "product_decisions": [],
            },
            {
                "role": "testability-evidence",
                "verdict": "pass",
                "summary": "Evidence is proportionate.",
                "reviewed_files": ["specs/123-example/plan.md"],
                "findings": [],
                "product_decisions": [],
            },
        ]

        summary = self.module.aggregate_reviews(reviews, risk="medium")
        self.assertEqual(summary["status"], "technical-changes-required")

    def test_aggregate_approves_only_when_every_reviewer_passes(self) -> None:
        reviews = [
            {
                "role": role,
                "verdict": "pass",
                "summary": "No concerns.",
                "reviewed_files": ["specs/123-example/spec.md"],
                "findings": [
                    {
                        "severity": "advisory",
                        "category": "style",
                        "description": "Wording nit.",
                        "evidence": ["specs/123-example/spec.md:12"],
                        "recommendation": "Reword.",
                    }
                ],
                "product_decisions": [],
            }
            for role in self.module.STANDARD_ROLES
        ]

        summary = self.module.aggregate_reviews(reviews, risk="medium")
        self.assertEqual(summary["status"], "approved")

    def _passing_panel(self) -> list[dict]:
        return [
            {
                "role": role,
                "verdict": "pass",
                "summary": "No concerns.",
                "reviewed_files": ["specs/123-example/spec.md"],
                "findings": [],
                "product_decisions": [],
            }
            for role in self.module.STANDARD_ROLES
        ]

    def test_missing_reviewer_escalates_and_never_passes(self) -> None:
        """Missing mandatory evidence is Escalated, not majority-green."""
        summary = self.module.aggregate_reviews(
            self._passing_panel()[:-1],
            risk="medium",
            missing_roles=("ux-accessibility-mobile",),
        )
        self.assertEqual(summary["status"], "escalated")
        self.assertIn("ux-accessibility-mobile", summary["architect_action"])

    def test_unknown_reviewer_provenance_escalates_and_never_passes(self) -> None:
        summary = self.module.aggregate_reviews(
            self._passing_panel(),
            risk="medium",
            unknown_oracle_roles=("privacy-consent-security",),
        )
        self.assertEqual(summary["status"], "escalated")
        self.assertIn("privacy-consent-security", summary["architect_action"])
        self.assertIn("provenance", summary["architect_action"].lower())

    def test_high_risk_without_human_signoff_escalates(self) -> None:
        summary = self.module.aggregate_reviews(self._passing_panel(), risk="high")
        self.assertEqual(summary["status"], "escalated")
        self.assertIn("human sign-off", summary["architect_action"])

    def test_high_risk_with_human_signoff_can_approve(self) -> None:
        summary = self.module.aggregate_reviews(
            self._passing_panel(), risk="high", human_signoff=True
        )
        self.assertEqual(summary["status"], "approved")

    def test_medium_risk_needs_no_signoff(self) -> None:
        summary = self.module.aggregate_reviews(self._passing_panel(), risk="medium")
        self.assertEqual(summary["status"], "approved")

    def test_missing_evidence_outranks_a_clean_panel(self) -> None:
        """A campaign cannot be clean when part of it never ran."""
        summary = self.module.aggregate_reviews(
            self._passing_panel(),
            risk="low",
            missing_roles=("privacy-consent-security",),
        )
        self.assertEqual(summary["status"], "escalated")

    def test_parse_workflow_inputs_uses_engine_envelope(self) -> None:
        self.assertEqual(
            self.module.parse_workflow_inputs({"inputs": {"risk": "high"}}),
            {"risk": "high"},
        )

    def test_validate_handoff_accepts_compact_acyclic_lanes(self) -> None:
        handoff = {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Deliver a reviewed planning change.",
            "artifacts": {
                "spec": "specs/123-example/spec.md",
                "plan": "specs/123-example/plan.md",
                "tasks": "specs/123-example/tasks.md",
                "checklist": "specs/123-example/checklists/requirements.md",
                "adrs": [],
            },
            "planning_review": {
                "run_id": "abc123",
                "risk": "medium",
                "status": "approved",
                "reviewers": list(self.module.STANDARD_ROLES),
            },
            "product_decisions": [],
            "lanes": [
                {
                    "id": "backend-contract",
                    "outcome": "Implement the backend contract.",
                    "depends_on": [],
                    "task_refs": ["T001", "T002"],
                    "scope_paths": ["backend/app/example.py"],
                    "exclusive_writer_scope": ["backend/app/example.py"],
                    "acceptance_evidence": ["Targeted backend tests pass."],
                },
                {
                    "id": "frontend-flow",
                    "outcome": "Implement the frontend flow.",
                    "depends_on": ["backend-contract"],
                    "task_refs": ["T003", "T004"],
                    "scope_paths": ["frontend/src/example.tsx"],
                    "exclusive_writer_scope": ["frontend/src/example.tsx"],
                    "acceptance_evidence": ["Targeted frontend tests pass."],
                },
            ],
            "risks": [],
            "non_goals": ["No deployment change."],
        }
        validated = self.module.validate_handoff(handoff)
        self.assertEqual(len(validated["lanes"]), 2)
        self.assertEqual(validated["planning_review"]["status"], "approved")
        self.assertNotIn("founder_acceptance", validated["planning_review"])

    def test_validate_handoff_preserves_founder_acceptance_round_trip(self) -> None:
        """`founder-accepted` must survive validation intact.

        Regression: the validated handoff used to hardcode
        `status: "approved"` and drop `founder_acceptance`, laundering an
        honest unconverged review into a clean approval and discarding the
        campaign history that makes the status defensible.
        """
        acceptance = {
            "accepted_by": "maksim.v.kravchuk@gmail.com",
            "accepted_on": "2026-07-29",
            "expires_on": "2026-10-29",
            "compensating_measures": [
                "Weekly manual smoke of the multilingual capture path.",
                "Alert on transcription error rate above the INTERNAL floor.",
            ],
            "rationale": (
                "Five campaigns re-litigated the package from scratch without "
                "converging; every verified defect was fixed and the remaining "
                "findings were re-raised duplicates, so the founder closed the "
                "loop for a single-user deployment."
            ),
            "campaign_history": [
                {"run_id": "run1", "status": "technical-changes-required"},
                {"run_id": "run5", "status": "technical-changes-required"},
            ],
        }
        handoff = {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Deliver a reviewed planning change.",
            "artifacts": {
                "spec": "specs/123-example/spec.md",
                "plan": "specs/123-example/plan.md",
                "tasks": "specs/123-example/tasks.md",
                "checklist": "specs/123-example/checklists/requirements.md",
                "adrs": [],
            },
            "planning_review": {
                "run_id": "abc123",
                "risk": "medium",
                "status": "founder-accepted",
                "reviewers": list(self.module.STANDARD_ROLES),
                "founder_acceptance": acceptance,
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
                }
            ],
            "risks": [],
            "non_goals": ["No deployment change."],
        }

        validated = self.module.validate_handoff(handoff, today=date(2026, 8, 1))
        review = validated["planning_review"]
        self.assertEqual(review["status"], "founder-accepted")
        self.assertEqual(review["founder_acceptance"], acceptance)

    def test_validate_handoff_rejects_dependency_cycle(self) -> None:
        handoff = {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Cycle example.",
            "artifacts": {"spec": "s", "plan": "p", "tasks": "t", "checklist": "c", "adrs": []},
            "planning_review": {
                "run_id": "abc123",
                "risk": "medium",
                "status": "approved",
                "reviewers": list(self.module.STANDARD_ROLES),
            },
            "product_decisions": [],
            "lanes": [
                {
                    "id": "lane-a", "outcome": "A", "depends_on": ["lane-b"],
                    "task_refs": ["T001"], "scope_paths": ["a"],
                    "exclusive_writer_scope": ["a"], "acceptance_evidence": ["A passes"],
                },
                {
                    "id": "lane-b", "outcome": "B", "depends_on": ["lane-a"],
                    "task_refs": ["T002"], "scope_paths": ["b"],
                    "exclusive_writer_scope": ["b"], "acceptance_evidence": ["B passes"],
                },
            ],
            "risks": [],
            "non_goals": [],
        }
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.module.validate_handoff(handoff)

    def test_write_json_atomic_replaces_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "summary.json"
            self.module.write_json_atomic(target, {"status": "first"})
            self.module.write_json_atomic(target, {"status": "second"})
            self.assertEqual(json.loads(target.read_text()), {"status": "second"})
            self.assertEqual(list(target.parent.glob("*.tmp")), [])


class HumanSignoffTests(unittest.TestCase):
    """High-risk sign-off must be evidence, not a flag the caller sets.

    Regression: `human_signoff` was a workflow input coerced with `bool(...)`,
    so the same automated actor that ran the campaign could self-certify the
    human gate on exactly the ASK-class surfaces the gate exists to protect.
    """

    def setUp(self) -> None:
        self.module = load_module()

    def build(self, tmp: str) -> tuple[Path, Path, str]:
        root = Path(tmp)
        feature_dir = root / "specs" / "006-example"
        (feature_dir / "checklists").mkdir(parents=True)
        (feature_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        (feature_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
        run_dir = root / "runs" / "run1"
        run_dir.mkdir(parents=True)
        digest = self.module.review_artifacts_digest(feature_dir)
        return feature_dir, run_dir, digest

    def record(self, **overrides) -> dict:
        base = {
            "approved_by": "maksim.v.kravchuk@gmail.com",
            "approved_on": "2026-08-10",
            "run_id": "run1",
            "artifacts_digest": "",
            "rationale": "Reviewed the session-rotation surface personally and accept the residual risk.",
        }
        base.update(overrides)
        return base

    def write(self, run_dir: Path, record: dict) -> None:
        (run_dir / "human-signoff.json").write_text(json.dumps(record), encoding="utf-8")

    def load(self, run_dir: Path, digest: str):
        return self.module.load_human_signoff(
            run_dir, run_id="run1", artifacts_digest=digest
        )

    def test_absent_record_is_no_signoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _feature, run_dir, digest = self.build(tmp)
            self.assertIsNone(self.load(run_dir, digest))

    def test_valid_record_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _feature, run_dir, digest = self.build(tmp)
            self.write(run_dir, self.record(artifacts_digest=digest))
            loaded = self.load(run_dir, digest)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["approved_by"], "maksim.v.kravchuk@gmail.com")

    def test_signoff_from_another_run_is_rejected(self) -> None:
        """An approval must not be replayed across campaigns."""
        with tempfile.TemporaryDirectory() as tmp:
            _feature, run_dir, digest = self.build(tmp)
            self.write(run_dir, self.record(run_id="run-other", artifacts_digest=digest))
            self.assertIsNone(self.load(run_dir, digest))

    def test_signoff_goes_stale_when_the_artifacts_change(self) -> None:
        """Approving one spec must not silently approve its rewrite."""
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir, run_dir, digest = self.build(tmp)
            self.write(run_dir, self.record(artifacts_digest=digest))
            self.assertIsNotNone(self.load(run_dir, digest))

            (feature_dir / "spec.md").write_text("# Spec, rewritten\n", encoding="utf-8")
            new_digest = self.module.review_artifacts_digest(feature_dir)
            self.assertNotEqual(new_digest, digest)
            self.assertIsNone(self.load(run_dir, new_digest))

    def test_anonymous_or_unreasoned_signoff_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _feature, run_dir, digest = self.build(tmp)
            for bad in (
                self.record(approved_by="", artifacts_digest=digest),
                self.record(rationale="ok", artifacts_digest=digest),
                self.record(approved_on="", artifacts_digest=digest),
            ):
                self.write(run_dir, bad)
                self.assertIsNone(self.load(run_dir, digest))

    def test_malformed_record_is_not_an_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _feature, run_dir, digest = self.build(tmp)
            (run_dir / "human-signoff.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(self.load(run_dir, digest))

    def test_digest_must_be_recomputed_not_trusted_from_preflight(self) -> None:
        """Regression: the mechanism was defeated by its own cache.

        `summarize()` used to compare the sign-off against the digest stored in
        planning-context.json at preflight. Editing the spec afterwards left the
        stored digest matching the sign-off, so the campaign approved content
        nobody reviewed. The digest must be recomputed from the artifacts as
        they stand at summarization time.
        """
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir, run_dir, preflight_digest = self.build(tmp)
            self.write(run_dir, self.record(artifacts_digest=preflight_digest))

            (feature_dir / "spec.md").write_text("# Spec, edited\n", encoding="utf-8")
            recomputed = self.module.review_artifacts_digest(feature_dir)

            # Against the stale stored digest the sign-off still "matches" —
            # that is the bug.
            self.assertIsNotNone(self.load(run_dir, preflight_digest))
            # Against the recomputed digest it is correctly rejected.
            self.assertIsNone(self.load(run_dir, recomputed))

    def test_digest_covers_every_reviewed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir, _run_dir, digest = self.build(tmp)
            (feature_dir / "design.md").write_text("# Design\n", encoding="utf-8")
            self.assertNotEqual(
                self.module.review_artifacts_digest(feature_dir),
                digest,
                "adding a reviewed artifact must change the digest",
            )


class HighRiskHandoffSignoffTests(unittest.TestCase):
    """A high-risk handoff must carry the approval, not merely allow it.

    Regression: `human_signoff` was added to handoff.schema.json but
    `validate_handoff()` never checked it, so a hand-written handoff with
    risk `high` and status `approved` validated with no approval record at
    all — reachable from CI, since check_spec_kit_specs.py delegates here.
    """

    def setUp(self) -> None:
        self.module = load_module()

    def signoff(self, **overrides) -> dict:
        record = {
            "approved_by": "maksim.v.kravchuk@gmail.com",
            "approved_on": "2026-08-10",
            "run_id": "run123",
            "artifacts_digest": "a" * 64,
            "rationale": "Reviewed the session-rotation surface and accept the residual risk.",
        }
        record.update(overrides)
        return record

    def handoff(self, *, risk: str, signoff: object = "omit") -> dict:
        review: dict = {
            "run_id": "run123",
            "risk": risk,
            "status": "approved",
            "reviewers": [*self.module.STANDARD_ROLES, "adversarial-high-risk"],
            # Panel provenance is required at `high`. These are the clean-panel
            # values, so the assertions below fail on the sign-off rather than
            # on whichever high-risk requirement the validator reaches first.
            "degraded_lenses": [],
            "oracle_unknown_lenses": [],
            "single_provider_panel": False,
        }
        if signoff != "omit":
            review["human_signoff"] = signoff
        return {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Deliver a reviewed planning change.",
            "artifacts": {
                "spec": "specs/123-example/spec.md",
                "plan": "specs/123-example/plan.md",
                "tasks": "specs/123-example/tasks.md",
                "checklist": "specs/123-example/checklists/requirements.md",
                "adrs": [],
            },
            "planning_review": review,
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
                }
            ],
            "risks": [],
            "non_goals": ["No deployment change."],
        }

    def test_high_risk_without_signoff_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a human_signoff"):
            self.module.validate_handoff(self.handoff(risk="high"))

    def test_high_risk_with_signoff_is_accepted_and_carried(self) -> None:
        record = self.signoff()
        validated = self.module.validate_handoff(
            self.handoff(risk="high", signoff=record)
        )
        self.assertEqual(validated["planning_review"]["human_signoff"], record)

    def test_signoff_from_another_run_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.module.validate_handoff(
                self.handoff(risk="high", signoff=self.signoff(run_id="other-run"))
            )

    def test_anonymous_or_unreasoned_signoff_is_rejected(self) -> None:
        for bad, pattern in (
            (self.signoff(approved_by=""), "approved_by"),
            (self.signoff(rationale="ok"), "residual risk"),
            (self.signoff(artifacts_digest="not-a-digest"), "sha256"),
        ):
            with self.assertRaisesRegex(ValueError, pattern):
                self.module.validate_handoff(self.handoff(risk="high", signoff=bad))

    def test_medium_risk_needs_no_signoff(self) -> None:
        validated = self.module.validate_handoff(self.handoff(risk="medium"))
        self.assertNotIn("human_signoff", validated["planning_review"])


class HandoffProvenanceTests(unittest.TestCase):
    """The authorizing artifact must be able to repeat what the gate measured.

    ADR-0012 correction D was a schema describing a sign-off that nothing
    enforced. This is the mirror image: a gate measuring degradation that the
    handoff could not carry. The spec-gate tests cover the rejections; these
    cover carry-through, which a subprocess exit code cannot assert.
    """

    def setUp(self) -> None:
        self.module = load_module()

    def handoff(self, **review_overrides) -> dict:
        review: dict = {
            "run_id": "run123",
            "risk": "medium",
            "status": "approved",
            "reviewers": list(self.module.STANDARD_ROLES),
        }
        review.update(review_overrides)
        return {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Deliver a reviewed planning change.",
            "artifacts": {
                "spec": "specs/123-example/spec.md",
                "plan": "specs/123-example/plan.md",
                "tasks": "specs/123-example/tasks.md",
                "checklist": "specs/123-example/checklists/requirements.md",
                "adrs": [],
            },
            "planning_review": review,
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
                }
            ],
            "risks": [],
            "non_goals": ["No deployment change."],
        }

    def test_degradation_is_carried_into_the_validated_handoff(self) -> None:
        validated = self.module.validate_handoff(
            self.handoff(
                degraded_lenses=["requirements-consistency"],
                oracle_unknown_lenses=[],
                single_provider_panel=True,
            )
        )
        review = validated["planning_review"]
        self.assertEqual(review["degraded_lenses"], ["requirements-consistency"])
        self.assertIs(review["single_provider_panel"], True)

    def test_a_false_single_provider_flag_is_carried_not_dropped(self) -> None:
        """`false` is a measurement. Truthiness would silently discard it."""
        validated = self.module.validate_handoff(
            self.handoff(degraded_lenses=[], single_provider_panel=False)
        )
        self.assertIs(validated["planning_review"]["single_provider_panel"], False)

    def test_a_degraded_lens_absent_from_the_panel_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.module.validate_handoff(
                self.handoff(degraded_lenses=["testability_evidence"])
            )
        self.assertIn("cannot have been degraded", str(caught.exception))

    def test_medium_risk_may_omit_provenance(self) -> None:
        """Below high the panel is accepted as sufficient on its own."""
        validated = self.module.validate_handoff(self.handoff())
        self.assertNotIn("degraded_lenses", validated["planning_review"])


class ArtifactDriftTests(unittest.TestCase):
    """Reviews describe the artifacts as they stood when they ran."""

    def setUp(self) -> None:
        self.module = load_module()

    def passing_panel(self) -> list[dict]:
        return [
            {
                "role": role,
                "verdict": "pass",
                "summary": "No concerns.",
                "reviewed_files": ["specs/123-example/spec.md"],
                "findings": [],
                "product_decisions": [],
            }
            for role in self.module.STANDARD_ROLES
        ]

    def test_artifacts_changing_after_preflight_escalates(self) -> None:
        summary = self.module.aggregate_reviews(
            self.passing_panel(), risk="medium", artifacts_changed=True
        )
        self.assertEqual(summary["status"], "escalated")
        self.assertIn("changed after preflight", summary["architect_action"])

    def test_drift_outranks_a_clean_signed_panel(self) -> None:
        summary = self.module.aggregate_reviews(
            self.passing_panel(),
            risk="high",
            human_signoff=True,
            artifacts_changed=True,
        )
        self.assertEqual(summary["status"], "escalated")


class FounderAcceptanceBoundsTests(unittest.TestCase):
    """A risk acceptance must be bounded in time and carry mitigations.

    Without an expiry it is not an acceptance, it is a permanent hole in the
    gate signed once by whoever happened to be blocked that day.
    """

    def setUp(self) -> None:
        self.module = load_module()

    def acceptance(self, **overrides) -> dict:
        record = {
            "accepted_by": "maksim.v.kravchuk@gmail.com",
            "accepted_on": "2026-07-29",
            "expires_on": "2026-10-29",
            "rationale": (
                "Five campaigns re-litigated the package from scratch without "
                "converging; every verified defect was fixed and the remaining "
                "findings were re-raised duplicates, so the founder closed the "
                "loop for a single-user deployment."
            ),
            "compensating_measures": [
                "Weekly manual smoke of the multilingual capture path.",
            ],
            "campaign_history": [{"run_id": "run1", "status": "changes-required"}],
        }
        record.update(overrides)
        return record

    def handoff(self, acceptance: dict | None) -> dict:
        review: dict = {
            "run_id": "abc123",
            "risk": "medium",
            "status": "founder-accepted",
            "reviewers": list(self.module.STANDARD_ROLES),
        }
        if acceptance is not None:
            review["founder_acceptance"] = acceptance
        return {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Deliver a reviewed planning change.",
            "artifacts": {
                "spec": "specs/123-example/spec.md",
                "plan": "specs/123-example/plan.md",
                "tasks": "specs/123-example/tasks.md",
                "checklist": "specs/123-example/checklists/requirements.md",
                "adrs": [],
            },
            "planning_review": review,
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
                }
            ],
            "risks": [],
            "non_goals": ["No deployment change."],
        }

    def validate(self, acceptance: dict | None, *, today=date(2026, 8, 1)):
        return self.module.validate_handoff(self.handoff(acceptance), today=today)

    def test_bounded_acceptance_is_accepted(self) -> None:
        validated = self.validate(self.acceptance())
        self.assertEqual(validated["planning_review"]["status"], "founder-accepted")

    def test_missing_expiry_is_rejected(self) -> None:
        record = self.acceptance()
        del record["expires_on"]
        with self.assertRaisesRegex(ValueError, "expires_on"):
            self.validate(record)

    def test_missing_compensating_measures_is_rejected(self) -> None:
        record = self.acceptance()
        del record["compensating_measures"]
        with self.assertRaisesRegex(ValueError, "compensating_measures"):
            self.validate(record)

    def test_placeholder_compensating_measure_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "concrete mitigation"):
            self.validate(self.acceptance(compensating_measures=["TBD"]))

    def test_expiry_before_acceptance_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "after accepted_on"):
            self.validate(self.acceptance(expires_on="2026-07-01"))

    def test_expired_acceptance_no_longer_closes_the_review(self) -> None:
        with self.assertRaisesRegex(ValueError, "expired"):
            self.validate(self.acceptance(), today=date(2026, 12, 1))

    def test_non_iso_dates_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "ISO date"):
            self.validate(self.acceptance(expires_on="next quarter"))


class ReviewerIndependenceTests(unittest.TestCase):
    """Formal plurality is not independence.

    Three lenses on one model produce one opinion counted three times, and the
    aggregation rule would read correlated blind spots as corroboration.
    """

    def setUp(self) -> None:
        self.module = load_module()

    def test_every_configured_lens_uses_the_available_codex_runtime(self) -> None:
        for role, config in self.module.ROLE_CONFIGS.items():
            self.assertEqual(config["integration"], "codex", role)
            self.assertEqual(config["model"], "gpt-5.6-sol", role)
            self.assertNotIn("fallback", config, role)

    def test_claude_is_not_a_supported_review_integration(self) -> None:
        self.assertEqual(self.module.INTEGRATION_CLI, {"codex": "codex"})

    def test_every_rubric_lens_points_at_an_existing_portable_file(self) -> None:
        for role, config in self.module.ROLE_CONFIGS.items():
            agent = config.get("agent")
            if agent is None:
                continue
            path = ROOT / ".specify" / "review-rubrics" / f"{agent}.md"
            self.assertTrue(path.is_file(), f"{role} points at missing {path}")


class ReviewerPromptPortabilityTests(unittest.TestCase):
    """The prompt must not contradict the authorities that govern the gate.

    Until 2026-08-13 every reviewer prompt asserted "Hermes Kanban remains the
    sole execution runtime". CLAUDE.md, docs/spec-kit-workflow.md, .hermes.md
    and the speckit-implement skill all make Hermes strictly opt-in, so the
    campaign shipped a contradiction of its own repository into every review —
    invisibly, because nobody reads a prompt that a script assembles.
    """

    def setUp(self) -> None:
        self.module = load_module()
        self.root = ROOT
        self.feature_dir = ROOT / "specs" / "006-mobile-task-classification"

    def _prompts(self) -> dict[str, str]:
        return {
            role: self.module.build_prompt(
                role=role, feature_dir=self.feature_dir, root=self.root
            )
            for role in self.module.ROLE_CONFIGS
        }

    def test_no_prompt_assumes_a_managed_execution_runtime(self) -> None:
        forbidden = ("Hermes", "Kanban", "sole execution runtime", "second scheduler")
        for role, prompt in self._prompts().items():
            for phrase in forbidden:
                self.assertNotIn(
                    phrase,
                    prompt,
                    f"{role} prompt assumes a managed runtime via {phrase!r}; "
                    "the gate is portable (ADR-0011)",
                )

    def test_every_prompt_still_forbids_mutating_the_repository(self) -> None:
        """Dropping the runtime claim must not drop the read-only boundary."""
        for role, prompt in self._prompts().items():
            self.assertIn("read-only review", prompt, role)
            self.assertIn("Do not edit files", prompt, role)

    def test_rubric_lenses_are_pointed_at_their_agent_file(self) -> None:
        prompts = self._prompts()
        for role, config in self.module.ROLE_CONFIGS.items():
            agent = config.get("agent")
            if agent is None:
                continue
            self.assertIn(f".specify/review-rubrics/{agent}.md", prompts[role], role)


class OracleRuntimeTests(unittest.TestCase):
    """Every lens uses the installed Codex CLI and records that provenance."""

    def setUp(self) -> None:
        self.module = load_module()

    def which(self, *installed: str):
        """Patch PATH lookup so only the named executables exist."""
        return mock.patch.object(
            self.module.shutil,
            "which",
            lambda name: f"/usr/bin/{name}" if name in installed else None,
        )

    def test_every_role_resolves_to_codex_without_degradation(self) -> None:
        with self.which("codex"):
            for role in self.module.ROLE_CONFIGS:
                config, oracle = self.module.resolve_oracle(role)
                self.assertEqual(config["integration"], "codex", role)
                self.assertEqual(oracle["model"], "gpt-5.6-sol", role)
                self.assertFalse(oracle["degraded"], role)
                self.assertEqual(oracle["executable"], "/usr/bin/codex", role)

    def test_missing_codex_runtime_fails_closed(self) -> None:
        with self.which():
            with self.assertRaises(self.module.ReviewError) as caught:
                self.module.resolve_oracle("requirements-consistency")
        self.assertIn("codex", str(caught.exception))
        self.assertIn("not installed", str(caught.exception))

    def test_empty_partial_and_non_codex_oracles_are_rejected(self) -> None:
        digest = "a" * 64
        invalid = (
            {},
            {"integration": "codex"},
            {
                "integration": "claude",
                "model": "opus",
                "degraded": False,
                "executable": "/usr/bin/claude",
                "artifacts_digest": digest,
            },
        )
        for oracle in invalid:
            with self.subTest(oracle=oracle):
                self.assertIsNone(
                    self.module.validate_oracle_provenance(
                        oracle,
                        role="requirements-consistency",
                        artifacts_digest=digest,
                    )
                )

    def test_complete_codex_oracle_is_accepted(self) -> None:
        digest = "a" * 64
        oracle = {
            "integration": "codex",
            "model": "gpt-5.6-sol",
            "degraded": False,
            "executable": "/opt/review-tools/codex",
            "artifacts_digest": digest,
        }
        self.assertEqual(
            self.module.validate_oracle_provenance(
                oracle,
                role="requirements-consistency",
                artifacts_digest=digest,
            ),
            oracle,
        )

    def test_a_reviewer_cannot_author_its_own_provenance(self) -> None:
        """Provenance is stamped by the harness, never by the model.

        `validate_review` rebuilds the payload from known keys, so an `oracle`
        block emitted by the reviewer is discarded before the harness writes
        the real one.
        """
        forged = {
            "role": "requirements-consistency",
            "verdict": "pass",
            "summary": "No concerns.",
            "reviewed_files": ["specs/006-example/spec.md"],
            "findings": [],
            "product_decisions": [],
            "oracle": {"integration": "codex", "model": "gpt-5.6-sol", "degraded": False},
        }
        validated = self.module.validate_review(
            forged, expected_role="requirements-consistency"
        )
        self.assertNotIn("oracle", validated)


class ExternalReviewerTests(unittest.TestCase):
    """Any agent can supply the review protocol without a vendor CLI."""

    def setUp(self) -> None:
        self.module = load_module()

    def test_real_external_adapter_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".specify/workflows/runs/run1"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(json.dumps({
                "feature_dir": str(root / "specs/006-example"),
                "artifacts_digest": "digest-1",
            }))
            adapter = root / "reviewer.py"
            adapter.write_text(
                "import json, os, sys\n"
                "prompt = sys.stdin.read()\n"
                "assert 'Focus:' in prompt\n"
                "assert os.environ['SPECKIT_REVIEW_SCHEMA'].endswith('review.schema.json')\n"
                "print(json.dumps({'role': os.environ['SPECKIT_REVIEW_ROLE'], "
                "'verdict': 'pass', 'summary': 'Synthetic adapter test', "
                "'reviewed_files': ['specs/006-example/spec.md'], "
                "'findings': [], 'product_decisions': []}))\n"
            )
            path = self.module.run_review(
                root=root, run_id="run1", role="requirements-consistency",
                reviewer_command=f"{sys.executable} {adapter}",
                provider="test-provider", model="test-model",
            )
            review = json.loads(path.read_text())
            self.assertEqual(review["oracle"]["adapter"], "external-stdin-v1")
            self.assertEqual(review["oracle"]["integration"], "external-unverified")
            self.assertEqual(review["oracle"]["claimed_provider"], "test-provider")
            self.assertTrue(review["oracle"]["degraded"])

    def test_external_adapter_records_exact_prompt_and_actual_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".specify/workflows/runs/run1"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(json.dumps({
                "feature_dir": str(root / "specs/006-example"),
                "artifacts_digest": "digest-1",
            }))
            payload = {
                "role": "requirements-consistency",
                "verdict": "pass",
                "summary": "No concerns.",
                "reviewed_files": ["specs/006-example/spec.md"],
                "findings": [],
                "product_decisions": [],
                "oracle": {"integration": "forged", "model": "forged"},
            }
            with mock.patch.object(self.module, "build_prompt", return_value="PROMPT"), \
                 mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/reviewer"), \
                 mock.patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess(
                     ["reviewer"], 0, json.dumps(payload), ""
                 )) as runner:
                path = self.module.run_review(
                    root=root, run_id="run1", role="requirements-consistency",
                    reviewer_command="reviewer --json", provider="independent-provider",
                    model="model-a",
                )
            review = json.loads(path.read_text())
            self.assertEqual(review["oracle"]["integration"], "external-unverified")
            self.assertEqual(review["oracle"]["model"], "unverified")
            self.assertEqual(review["oracle"]["claimed_provider"], "independent-provider")
            self.assertEqual(review["oracle"]["claimed_model"], "model-a")
            self.assertTrue(review["oracle"]["degraded"])
            self.assertEqual(review["oracle"]["configured_integration"], "codex")
            self.assertEqual(review["oracle"]["artifacts_digest"], "digest-1")
            self.assertEqual(runner.call_args.kwargs["input"], "PROMPT")
            self.assertEqual(runner.call_args.kwargs["env"]["SPECKIT_REVIEW_ROLE"], "requirements-consistency")
            self.assertEqual(runner.call_args.args[0], ["reviewer", "--json"])

    def test_external_adapter_cannot_self_certify_configured_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".specify/workflows/runs/run1"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(json.dumps({
                "feature_dir": str(root / "specs/006-example"),
                "artifacts_digest": "digest-1",
            }))
            payload = {
                "role": "requirements-consistency", "verdict": "pass", "summary": "ok",
                "reviewed_files": ["specs/006-example/spec.md"], "findings": [],
                "product_decisions": [],
            }
            with mock.patch.object(self.module, "build_prompt", return_value="PROMPT"), \
                 mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/reviewer"), \
                 mock.patch.object(self.module.subprocess, "run", return_value=subprocess.CompletedProcess(
                     ["reviewer"], 0, json.dumps(payload), ""
                 )) as runner, \
                 mock.patch.dict(os.environ, {"DATABASE_URL": "test-only-placeholder"}):
                path = self.module.run_review(
                    root=root, run_id="run1", role="requirements-consistency",
                    reviewer_command="reviewer", provider="codex", model="gpt-5.3-codex",
                )
            oracle = json.loads(path.read_text())["oracle"]
            self.assertTrue(oracle["degraded"])
            self.assertEqual(oracle["integration"], "external-unverified")
            self.assertEqual(oracle["claimed_provider"], "codex")
            self.assertNotIn("DATABASE_URL", runner.call_args.kwargs["env"])

    def test_missing_provenance_fails_before_running_any_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".specify/workflows/runs/run1"
            run_dir.mkdir(parents=True)
            (run_dir / "planning-context.json").write_text(json.dumps({
                "feature_dir": str(root / "specs/006-example"),
            }))
            with mock.patch.object(self.module, "build_prompt", return_value="PROMPT"), \
                 mock.patch.object(self.module.subprocess, "run") as runner:
                with self.assertRaisesRegex(self.module.ReviewError, "--provider and --model"):
                    self.module.run_review(
                        root=root, run_id="run1", role="requirements-consistency",
                        reviewer_command="reviewer", provider="x",
                    )
                runner.assert_not_called()

class DegradationVisibilityTests(unittest.TestCase):
    """A degraded panel may pass, but it may never pass quietly."""

    def setUp(self) -> None:
        self.module = load_module()

    def high_risk_roles(self) -> list[str]:
        return [*self.module.STANDARD_ROLES, "adversarial-high-risk"]

    def panel(
        self, oracles: dict[str, dict] | None = None, roles: list[str] | None = None
    ) -> list[dict]:
        reviews = []
        for role in roles or list(self.module.STANDARD_ROLES):
            review = {
                "role": role,
                "verdict": "pass",
                "summary": "No concerns.",
                "reviewed_files": ["specs/006-example/spec.md"],
                "findings": [],
                "product_decisions": [],
            }
            if oracles and role in oracles:
                review["oracle"] = oracles[role]
            reviews.append(review)
        return reviews

    def test_degradation_does_not_block_but_is_named_in_the_action(self) -> None:
        summary = self.module.aggregate_reviews(
            self.panel(),
            risk="medium",
            degraded_roles=("requirements-consistency",),
        )
        self.assertEqual(summary["status"], "approved")
        self.assertIn("requirements-consistency", summary["architect_action"])
        self.assertIn("fallback oracle", summary["architect_action"])
        self.assertEqual(summary["degraded_lenses"], ["requirements-consistency"])

    def test_an_undegraded_panel_has_no_legacy_fallback_note(self) -> None:
        summary = self.module.aggregate_reviews(self.panel(), risk="medium")
        self.assertNotIn("fallback oracle", summary["architect_action"])
        self.assertEqual(summary["degraded_lenses"], [])

    def build_run(
        self,
        tmp: str,
        oracles: dict[str, dict] | None,
        risk: str = "medium",
        roles: list[str] | None = None,
    ) -> Path:
        root = Path(tmp)
        feature_dir = root / "specs" / "006-example"
        feature_dir.mkdir(parents=True, exist_ok=True)
        spec_path = feature_dir / "spec.md"
        plan_path = feature_dir / "plan.md"
        if not spec_path.exists():
            spec_path.write_text(
                "# Spec\n\n## User Scenarios & Testing\n\n"
                "## Requirements\n\n- **FR-001**: Safe.\n\n"
                "## Success Criteria\n\n- **SC-001**: Safe.\n",
                encoding="utf-8",
            )
        if not plan_path.exists():
            plan_path.write_text("# Plan\n", encoding="utf-8")
        checklist_dir = feature_dir / "checklists"
        checklist_dir.mkdir(exist_ok=True)
        checklist_path = checklist_dir / "requirements.md"
        if not checklist_path.exists():
            checklist_path.write_text("- [x] complete\n", encoding="utf-8")
        run_dir = root / ".specify" / "workflows" / "runs" / "run1"
        (run_dir / "reviews").mkdir(parents=True)
        (run_dir / "inputs.json").write_text(
            json.dumps({"inputs": {"risk": risk}}), encoding="utf-8"
        )
        digest = self.module.review_artifacts_digest(feature_dir)
        (run_dir / "planning-context.json").write_text(
            json.dumps(
                {
                    "feature_dir": str(feature_dir),
                    "derived_risk": None,
                    "artifacts_digest": digest,
                }
            ),
            encoding="utf-8",
        )
        for review in self.panel(oracles, roles):
            oracle = review.get("oracle")
            if isinstance(oracle, dict):
                oracle.setdefault("executable", "/usr/bin/codex")
                oracle.setdefault("artifacts_digest", digest)
            path = run_dir / "reviews" / f"{review['role']}.json"
            path.write_text(json.dumps(review), encoding="utf-8")
        return root

    def historical_degraded_claude_panel(self) -> dict[str, dict]:
        """Legacy review files remain reportable after runtime policy changes."""
        return {
            role: {
                "integration": "claude",
                "model": "sonnet",
                "degraded": True,
                "reason": "historical fallback record",
            }
            for role in self.module.STANDARD_ROLES
        }

    def test_historical_degraded_oracles_do_not_satisfy_current_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, self.historical_degraded_claude_panel())
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "escalated")
        self.assertEqual(
            sorted(summary["oracle_unknown_lenses"]),
            sorted(self.module.STANDARD_ROLES),
        )
        self.assertEqual(summary["degraded_lenses"], [])
        self.assertIsNone(summary["panel_correlated"])
        self.assertEqual(summary["panel_oracles"], {})

    def test_the_configured_codex_only_panel_is_reported_as_correlated(self) -> None:
        oracles = {
            role: {
                "integration": self.module.ROLE_CONFIGS[role]["integration"],
                "model": self.module.ROLE_CONFIGS[role]["model"],
                "degraded": False,
            }
            for role in self.module.STANDARD_ROLES
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, oracles)
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["degraded_lenses"], [])
        self.assertTrue(summary["panel_correlated"])
        self.assertTrue(summary["single_provider_panel"])
        self.assertEqual(summary["panel_providers"], {"codex": 5})

    def test_a_review_with_no_oracle_is_unknown_not_clean(self) -> None:
        """Silence is not evidence that a lens ran as configured.

        Treating an absent oracle as undegraded would repeat the defect
        ADR-0012 removed from risk derivation.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, None)
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(
            sorted(summary["oracle_unknown_lenses"]),
            sorted(self.module.STANDARD_ROLES),
        )
        self.assertEqual(summary["degraded_lenses"], [])
        # `null`, not `false`. An unmeasured panel and a measured-and-diverse
        # one must not share a value, or the field answers a question it never
        # asked.
        self.assertIsNone(summary["panel_correlated"])
        # The same rule, and it was not applied to this field: with no lens
        # carrying provenance `provider_counts` is empty, so the old
        # `len(...) == 1 and known > 1` returned `false` and the report
        # rendered "more than one provider is represented" for a panel where
        # nothing at all was measured.
        self.assertIsNone(summary["single_provider_panel"])
        self.assertIn("Provenance note", summary["architect_action"])
        self.assertIn("unmeasured, not verified", summary["architect_action"])

    def test_one_lens_with_provenance_cannot_answer_the_provider_question(
        self,
    ) -> None:
        """One known oracle is not a measurement of panel diversity.

        The boundary the old expression got wrong: `known_oracles > 1` is the
        right guard against claiming collapse from a single data point, but
        routing that insufficiency into `false` put it in the same bucket as a
        verified cross-provider panel.
        """
        role = self.module.STANDARD_ROLES[0]
        oracles = {role: {"integration": "claude", "model": "opus", "degraded": False}}
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, oracles)
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["panel_providers"], {})
        self.assertIsNone(summary["single_provider_panel"])
        self.assertEqual(
            sorted(summary["oracle_unknown_lenses"]),
            sorted(self.module.STANDARD_ROLES),
        )
        # Not claimed as collapsed either — unknown is unknown in both
        # directions, so the action must not assert one vendor.
        self.assertNotIn("one vendor", summary["architect_action"])

    def test_non_codex_provider_is_rejected_from_current_panel(self) -> None:
        oracles = {
            role: {
                "integration": "codex" if index % 2 == 0 else "historical-other",
                "model": "gpt-5.6-sol" if index % 2 == 0 else "review-model",
                "degraded": False,
            }
            for index, role in enumerate(self.module.STANDARD_ROLES)
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, oracles)
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "escalated")
        self.assertEqual(summary["panel_providers"], {"codex": 3})
        self.assertIs(summary["single_provider_panel"], True)
        self.assertEqual(len(summary["oracle_unknown_lenses"]), 2)

    def test_historical_high_risk_panel_cannot_satisfy_current_gate(self) -> None:
        oracles = self.historical_degraded_claude_panel()
        oracles["adversarial-high-risk"] = {
            "integration": "claude",
            "model": "fable",
            "degraded": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, oracles, risk="high", roles=self.high_risk_roles())
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "escalated")
        self.assertEqual(summary["panel_oracles"], {})
        self.assertIsNone(summary["panel_correlated"])
        self.assertIsNone(summary["single_provider_panel"])
        self.assertEqual(summary["panel_providers"], {})
        self.assertEqual(len(summary["oracle_unknown_lenses"]), 6)

    def test_a_review_stamped_with_another_digest_escalates(self) -> None:
        """Re-running preflight on one run id used to clear the drift flag.

        `summarize` compared a single recorded digest against the artifacts on
        disk, and `preflight` rewrites that record without touching
        `reviews/`. Editing the spec, re-running preflight and summarizing
        therefore reported no drift over reviews of the original content. The
        per-review stamp survives that, and also catches a panel of mixed
        vintage when one lens is rerun on its own.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_dir = root / "specs" / "006-example"
            (feature_dir / "checklists").mkdir(parents=True)
            (feature_dir / "spec.md").write_text(
                "# Spec\n\n## User Scenarios & Testing\n\n"
                "## Requirements\n\n- **FR-001**: Safe.\n\n"
                "## Success Criteria\n\n- **SC-001**: Safe.\n",
                encoding="utf-8",
            )
            (feature_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (feature_dir / "checklists" / "requirements.md").write_text(
                "- [x] complete\n", encoding="utf-8"
            )
            digest = self.module.review_artifacts_digest(feature_dir)

            oracles = {
                role: {
                    "integration": "codex",
                    "model": "gpt-5.6-sol",
                    "degraded": False,
                    # What a review written before the spec was edited carries.
                    "artifacts_digest": "0" * 64,
                }
                for role in self.module.STANDARD_ROLES
            }
            self.build_run(tmp, oracles)
            run_dir = root / ".specify" / "workflows" / "runs" / "run1"
            # A context freshly rewritten by a second preflight: it agrees with
            # the artifacts on disk, so the run-level drift check sees nothing.
            (run_dir / "planning-context.json").write_text(
                json.dumps(
                    {"feature_dir": str(feature_dir), "artifacts_digest": digest}
                ),
                encoding="utf-8",
            )
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "escalated")
        self.assertEqual(
            sorted(summary["stale_reviews"]), sorted(self.module.STANDARD_ROLES)
        )
        self.assertTrue(summary["artifacts_changed_since_preflight"])

    def test_cross_provider_oracles_are_not_accepted_by_codex_only_policy(self) -> None:
        oracles = {
            role: {
                "integration": "codex" if index % 2 == 0 else "historical-other",
                "model": "gpt-5.6-sol" if index % 2 == 0 else "review-model",
                "degraded": False,
            }
            for index, role in enumerate(self.module.STANDARD_ROLES)
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_run(tmp, oracles)
            target = self.module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "escalated")
        self.assertEqual(summary["panel_providers"], {"codex": 3})
        self.assertTrue(summary["single_provider_panel"])
        self.assertEqual(len(summary["oracle_unknown_lenses"]), 2)


class SummarizePreflightBoundaryTests(unittest.TestCase):
    def test_summarize_rejects_a_run_without_preflight_context(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".specify" / "workflows" / "runs" / "run1"
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir(parents=True)
            for role in module.STANDARD_ROLES:
                (reviews_dir / f"{role}.json").write_text(
                    json.dumps(
                        {
                            "role": role,
                            "verdict": "pass",
                            "summary": "No concerns.",
                            "reviewed_files": ["specs/123-example/spec.md"],
                            "findings": [],
                            "product_decisions": [],
                        }
                    ),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(module.ReviewError, "preflight"):
                module.summarize(root=root, run_id="run1")

    def test_summarize_recomputes_ask_risk_instead_of_trusting_context(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feature_dir = root / "specs" / "123-example"
            (feature_dir / "checklists").mkdir(parents=True)
            (feature_dir / "spec.md").write_text(
                "# Spec\n\n## User Scenarios & Testing\n\n"
                "## Requirements\n\n- **FR-001**: Safe.\n\n"
                "## Success Criteria\n\n- **SC-001**: Safe.\n",
                encoding="utf-8",
            )
            (feature_dir / "plan.md").write_text(
                "# Plan\n\nChange scripts/spec_kit_planning_review.py.\n",
                encoding="utf-8",
            )
            (feature_dir / "checklists" / "requirements.md").write_text(
                "- [x] complete\n", encoding="utf-8"
            )
            digest = module.review_artifacts_digest(feature_dir)
            run_dir = root / ".specify" / "workflows" / "runs" / "run1"
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir(parents=True)
            (run_dir / "inputs.json").write_text(
                json.dumps({"inputs": {"risk": "low"}}), encoding="utf-8"
            )
            (run_dir / "planning-context.json").write_text(
                json.dumps(
                    {
                        "feature_dir": str(feature_dir),
                        "project_root": str(root),
                        "derived_risk": None,
                        "review_artifacts": module.review_artifacts(feature_dir),
                        "artifacts_digest": digest,
                    }
                ),
                encoding="utf-8",
            )
            for role in (*module.STANDARD_ROLES, "adversarial-high-risk"):
                (reviews_dir / f"{role}.json").write_text(
                    json.dumps(
                        {
                            "role": role,
                            "verdict": "pass",
                            "summary": "No concerns.",
                            "reviewed_files": ["specs/123-example/spec.md"],
                            "findings": [],
                            "product_decisions": [],
                            "oracle": {
                                "integration": "codex",
                                "model": "gpt-5.6-sol",
                                "degraded": False,
                                "executable": "/usr/bin/codex",
                                "artifacts_digest": digest,
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            target = module.summarize(root=root, run_id="run1")
            summary = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(summary["risk"], "high")
        self.assertEqual(summary["status"], "escalated")
        self.assertIn("human sign-off", summary["architect_action"])


class DeterministicPreflightTests(unittest.TestCase):
    """The preflight must catch regex-findable defects before a model runs."""

    def setUp(self) -> None:
        self.module = load_module()

    def write_feature(self, tmp: str, *, spec: str, checklist: str = "- [x] done") -> Path:
        feature_dir = Path(tmp) / "specs" / "123-example"
        (feature_dir / "checklists").mkdir(parents=True)
        (feature_dir / "spec.md").write_text(spec, encoding="utf-8")
        (feature_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
        (feature_dir / "checklists" / "requirements.md").write_text(
            checklist, encoding="utf-8"
        )
        return feature_dir

    def clean_spec(self) -> str:
        return (
            "# Feature Specification: Example\n"
            "## User Scenarios & Testing *(mandatory)*\n"
            "A user signs in.\n"
            "## Requirements *(mandatory)*\n"
            "- **FR-001**: System MUST sign the user in.\n"
            "## Success Criteria *(mandatory)*\n"
            "- **SC-001**: Sign-in completes in under two seconds.\n"
        )

    def test_clean_spec_has_no_defects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=self.clean_spec())
            self.assertEqual(self.module.deterministic_defects(feature_dir), [])

    def test_unresolved_clarification_marker_is_a_defect(self) -> None:
        spec = self.clean_spec() + "- **FR-002**: [NEEDS CLARIFICATION: which flow?]\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            defects = self.module.deterministic_defects(feature_dir)
            self.assertTrue(any("NEEDS CLARIFICATION" in item for item in defects))

    def test_missing_mandatory_section_is_a_defect(self) -> None:
        spec = self.clean_spec().replace("## Success Criteria *(mandatory)*\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            defects = self.module.deterministic_defects(feature_dir)
            self.assertTrue(any("Success Criteria" in item for item in defects))

    def test_duplicate_requirement_definition_is_a_defect(self) -> None:
        spec = self.clean_spec() + "- **FR-001**: System MUST also do something else.\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            defects = self.module.deterministic_defects(feature_dir)
            self.assertTrue(any("duplicate requirement id" in item for item in defects))

    def test_repeated_reference_to_a_requirement_is_not_a_defect(self) -> None:
        spec = self.clean_spec() + "FR-001 is verified by the sign-in test (FR-001).\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            self.assertEqual(self.module.deterministic_defects(feature_dir), [])

    def test_unchecked_checklist_item_is_a_defect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(
                tmp, spec=self.clean_spec(), checklist="- [ ] not done yet"
            )
            defects = self.module.deterministic_defects(feature_dir)
            self.assertTrue(any("unchecked item" in item for item in defects))

    def test_placeholder_text_is_a_defect(self) -> None:
        spec = self.clean_spec() + "- **FR-002**: TODO decide the retention window.\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            defects = self.module.deterministic_defects(feature_dir)
            self.assertTrue(any("placeholder" in item for item in defects))

    def test_ask_class_surface_derives_high_risk(self) -> None:
        spec = self.clean_spec() + "Touches backend/app/api/dependencies.py for auth.\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            self.assertEqual(self.module.derive_risk(feature_dir), "high")

    def test_unclassifiable_change_has_no_derived_opinion(self) -> None:
        """Derivation stays silent; the campaign then runs at the default.

        Treating silence as safety would let exactly the work nobody could
        classify take the cheapest path through the gate, so the default is
        medium and derivation never argues it down.
        """
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=self.clean_spec())
            self.assertIsNone(self.module.derive_risk(feature_dir))
            self.assertEqual(self.module.DEFAULT_RISK, "medium")

    def test_derivation_never_lowers_the_class(self) -> None:
        """Regression: a real false low on the worst possible surface.

        An earlier version returned `low` when every mentioned path was inert.
        A spec rotating session tokens while merely *citing* docs/auth.md as
        background therefore derived `low` — a mention is not a change, and at
        spec-review time there is no diff to tell them apart.
        """
        spec = (
            self.clean_spec()
            + "Rotates session tokens. See docs/auth.md and docs/data-retention.md.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            self.assertIsNone(self.module.derive_risk(feature_dir))
        self.assertEqual(self.module.DERIVABLE_RISKS, ("high",))

    def test_only_high_is_derivable(self) -> None:
        for risk in self.module.DERIVABLE_RISKS:
            self.assertEqual(
                risk,
                self.module.stricter_risk(risk, self.module.DEFAULT_RISK),
                "a derivable class must be at least as strict as the default",
            )

    def test_plain_code_path_alone_does_not_raise_the_class(self) -> None:
        spec = self.clean_spec() + "Touches frontend/src/components/Canvas.tsx only.\n"
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=spec)
            self.assertIsNone(self.module.derive_risk(feature_dir))

    def test_risk_escalates_and_never_de_escalates(self) -> None:
        self.assertEqual(self.module.stricter_risk("low", "high"), "high")
        self.assertEqual(self.module.stricter_risk("high", "low"), "high")
        self.assertEqual(self.module.stricter_risk("medium", "low"), "medium")
        self.assertEqual(self.module.stricter_risk("low", "low"), "low")

    def test_review_artifacts_include_optional_files_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir = self.write_feature(tmp, spec=self.clean_spec())
            (feature_dir / "design.md").write_text("# Design\n", encoding="utf-8")
            artifacts = self.module.review_artifacts(feature_dir)
            self.assertIn("design.md", artifacts)
            self.assertIn("checklists/requirements.md", artifacts)
            self.assertNotIn("tasks.md", artifacts)


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_bounded_planning_only_and_shell_safe(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self.assertNotIn("speckit.implement", workflow_text)
        self.assertNotIn("taskstoissues", workflow_text)
        self.assertNotRegex(workflow_text, r"(?m)^\s*type:\s*gate\s*$")
        self.assertNotRegex(workflow_text, r"(?m)^\s*run:.*\{\{\s*inputs\.")

        module = load_module()
        for role in module.STANDARD_ROLES:
            self.assertIn(f'- "{role}"', workflow_text)

        # The real invariant is that the fan-out stays bounded by the declared
        # roster, not that it equals any particular number: an unbounded or
        # over-provisioned concurrency would let the campaign outrun the
        # reviewer roles it is allowed to run.
        concurrency = re.search(r"max_concurrency:\s*(\d+)\b", workflow_text)
        self.assertIsNotNone(concurrency)
        assert concurrency is not None
        self.assertEqual(int(concurrency.group(1)), len(module.STANDARD_ROLES))

        # The contract assertions above are pure text and always run. Parsing
        # the workflow with the real CLI is an integration check: skip it where
        # the CLI is not installed rather than erroring, so `make check-specs`
        # stays runnable on a machine that only has one agent runtime.
        if shutil.which("specify") is None:
            self.skipTest("specify CLI not installed; skipping engine parse check")

        result = subprocess.run(
            ["specify", "workflow", "info", str(WORKFLOW_PATH)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
