"""Contract tests for the Architect-owned Spec Kit planning review campaign."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path


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
            role="requirements-consistency",
            prompt="Review the planning artifacts.",
            schema_path=ROOT / ".specify" / "workflows" / "speckit" / "review.schema.json",
        )

        self.assertEqual(command[0:2], ["codex", "exec"])
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("--ephemeral", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("danger-full-access", command)

    def test_fable_review_command_uses_plan_mode_and_read_only_tools(self) -> None:
        module = load_module()
        command, env = module.build_review_command(
            role="adversarial-high-risk",
            prompt="Challenge the plan.",
            schema_path=ROOT / ".specify" / "workflows" / "speckit" / "review.schema.json",
        )

        self.assertEqual(command[0:2], ["claude", "-p"])
        self.assertEqual(command[command.index("--permission-mode") + 1], "plan")
        tools = command[command.index("--allowedTools") + 1]
        self.assertEqual(tools, "Read,Grep,Glob")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("--dangerously-skip-permissions", command)


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

    def test_digest_covers_every_reviewed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            feature_dir, _run_dir, digest = self.build(tmp)
            (feature_dir / "design.md").write_text("# Design\n", encoding="utf-8")
            self.assertNotEqual(
                self.module.review_artifacts_digest(feature_dir),
                digest,
                "adding a reviewed artifact must change the digest",
            )


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

    def test_no_model_carries_a_majority_of_the_panel(self) -> None:
        models: dict[str, int] = {}
        for role in self.module.STANDARD_ROLES:
            model = self.module.ROLE_CONFIGS[role]["model"]
            models[model] = models.get(model, 0) + 1
        worst = max(models.values())
        self.assertLessEqual(
            worst,
            len(self.module.STANDARD_ROLES) // 2,
            f"one model covers {worst} of {len(self.module.STANDARD_ROLES)} lenses: {models}",
        )

    def test_panel_spans_more_than_one_provider(self) -> None:
        providers = {
            self.module.ROLE_CONFIGS[role]["integration"]
            for role in self.module.STANDARD_ROLES
        }
        self.assertGreater(len(providers), 1, providers)

    def test_every_claude_lens_points_at_an_existing_rubric_file(self) -> None:
        for role, config in self.module.ROLE_CONFIGS.items():
            agent = config.get("agent")
            if agent is None:
                continue
            path = ROOT / ".claude" / "agents" / f"{agent}.md"
            self.assertTrue(path.is_file(), f"{role} points at missing {path}")


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
