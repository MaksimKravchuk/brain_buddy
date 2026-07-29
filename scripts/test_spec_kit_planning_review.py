"""Contract tests for the Architect-owned Spec Kit planning review campaign."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
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
            role="architecture-consistency",
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

        summary = self.module.aggregate_reviews(reviews, risk="standard")
        self.assertEqual(summary["status"], "product-decision-required")
        self.assertEqual(len(summary["product_decisions"]), 1)
        self.assertEqual(len(summary["technical_findings"]), 1)

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
                "risk": "standard",
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

    def test_validate_handoff_rejects_dependency_cycle(self) -> None:
        handoff = {
            "schema_version": "speckit-hermes-handoff/v1",
            "root_outcome": "Cycle example.",
            "artifacts": {"spec": "s", "plan": "p", "tasks": "t", "checklist": "c", "adrs": []},
            "planning_review": {
                "run_id": "abc123",
                "risk": "standard",
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


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_bounded_planning_only_and_shell_safe(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self.assertNotIn("speckit.implement", workflow_text)
        self.assertNotIn("taskstoissues", workflow_text)
        self.assertNotRegex(workflow_text, r"(?m)^\s*type:\s*gate\s*$")
        self.assertNotRegex(workflow_text, r"(?m)^\s*run:.*\{\{\s*inputs\.")

        self.assertRegex(
            workflow_text,
            r"max_concurrency:\s*[123]\b",
        )
        for role in (
            "requirements-consistency",
            "architecture-consistency",
            "testability-evidence",
        ):
            self.assertIn(f'- "{role}"', workflow_text)

        result = subprocess.run(
            ["specify", "workflow", "info", str(WORKFLOW_PATH)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
