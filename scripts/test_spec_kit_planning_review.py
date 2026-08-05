"""Contract tests for the Architect-owned Spec Kit planning review campaign."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "spec_kit_planning_review.py"
CHECKER_PATH = ROOT / "scripts" / "check_spec_kit_specs.py"
WORKFLOW_PATH = ROOT / ".specify" / "workflows" / "speckit" / "workflow.yml"
REVIEW_SCHEMA_PATH = ROOT / ".specify" / "workflows" / "speckit" / "review.schema.json"
CONSTITUTION_PATH = ROOT / ".specify" / "memory" / "constitution.md"
AGENTS_PATH = ROOT / "AGENTS.md"
CLAUDE_PATH = ROOT / "CLAUDE.md"
README_PATH = ROOT / "README.md"
WORKFLOW_DOC_PATH = ROOT / "docs" / "spec-kit-workflow.md"
PROPORTIONAL_ADR_PATH = (
    ROOT / "docs" / "decisions" / "0011-proportional-spec-kit-planning-policy.md"
)


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

    def test_prompt_keeps_reversible_acceptance_behavior_with_architect(self) -> None:
        module = load_module()
        prompt = module.build_prompt(
            role="requirements-consistency",
            feature_dir=ROOT / "specs" / "006-ai-research-delegation",
            root=ROOT,
        )

        self.assertIn("safest reversible pilot default", prompt)
        self.assertNotIn("acceptance-behavior", prompt)

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_reviewer_timeout_terminates_descendant_processes(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "child.pid"
            code = (
                "import pathlib,subprocess,time; "
                "child=\"import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)\"; "
                "p=subprocess.Popen(['python3','-c',child], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid)); time.sleep(60)"
            )
            with self.assertRaisesRegex(module.ReviewError, "timed out"):
                module.run_bounded_process(
                    ["python3", "-c", code], cwd=root, env=os.environ.copy(), timeout=0.2
                )
            child_pid = int(pid_path.read_text())
            for _ in range(50):
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail(f"reviewer descendant {child_pid} survived timeout cleanup")


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

    def test_product_decision_categories_match_output_schema(self) -> None:
        schema = json.loads(REVIEW_SCHEMA_PATH.read_text())
        categories = schema["properties"]["product_decisions"]["items"]["properties"][
            "category"
        ]["enum"]
        self.assertEqual(set(categories), self.module.PRODUCT_DECISION_CATEGORIES)
        self.assertNotIn("acceptance-behavior", categories)
        self.assertIn(
            "acceptance-behavior", self.module.HANDOFF_PRODUCT_DECISION_CATEGORIES
        )

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

    def test_validate_review_rejects_reversible_acceptance_behavior_question(self) -> None:
        review = self.valid_review(verdict="product-decision-required")
        review["product_decisions"] = [
            {
                "category": "acceptance-behavior",
                "question": "Should stale consent create a run?",
                "why_needed": "The current acceptance text is incomplete.",
                "options": ["reject without a run", "create a blocked run"],
                "affected_acceptance": "Run submission",
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


class PlanningReviewSnapshotTests(unittest.TestCase):
    def test_worktree_fingerprint_detects_tracked_and_untracked_drift(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "spec.md"
            tracked.write_text("first\n")
            subprocess.run(["git", "add", "spec.md"], cwd=root, check=True)

            first = module.worktree_fingerprint(root)
            tracked.write_text("second\n")
            second = module.worktree_fingerprint(root)
            self.assertNotEqual(first, second)

            tracked.write_text("first\n")
            tracked.chmod(0o755)
            mode_changed = module.worktree_fingerprint(root)
            self.assertNotEqual(first, mode_changed)

            tracked.chmod(0o644)
            untracked = root / "plan.md"
            untracked.write_text("new\n")
            third = module.worktree_fingerprint(root)
            self.assertNotEqual(first, third)

    def test_snapshot_assertion_rejects_mid_campaign_edits(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            artifact = root / "spec.md"
            artifact.write_text("stable\n")
            subprocess.run(["git", "add", "spec.md"], cwd=root, check=True)
            expected = module.worktree_fingerprint(root)
            artifact.write_text("changed\n")
            with self.assertRaisesRegex(module.ReviewError, "changed during planning review"):
                module.assert_worktree_snapshot(root, expected)


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
                        "category": "ux",
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


class ProportionalPlanningPolicyTests(unittest.TestCase):
    def test_policy_is_risk_proportional_and_never_creates_process_gate_cards(self) -> None:
        agents = AGENTS_PATH.read_text()
        constitution = CONSTITUTION_PATH.read_text()
        claude = CLAUDE_PATH.read_text()
        readme = README_PATH.read_text()
        workflow_doc = WORKFLOW_DOC_PATH.read_text()
        checker = CHECKER_PATH.read_text()
        self.assertTrue(PROPORTIONAL_ADR_PATH.is_file(), "proportional planning ADR is required")
        adr = PROPORTIONAL_ADR_PATH.read_text()

        self.assertIn("## Proportional Spec Kit Workflow", agents)
        self.assertIn("Small maintenance", agents)
        self.assertIn("must not create a separate process-gate card", agents)
        for policy_text in (agents, constitution, claude, readme, workflow_doc, adr):
            self.assertIn("payment", policy_text.lower())
            self.assertIn("safety/compliance", policy_text.lower())
        self.assertIn("high-risk effects always win", agents)
        self.assertIn("high-risk effect wins", constitution)
        self.assertIn("risk-proportional planning tool", constitution)
        self.assertIn("MUST NOT create separate process-gate cards", constitution)
        self.assertIn("**Version**: 1.2.0", constitution)
        self.assertIn("risk-proportional", claude)
        self.assertIn("must not create a separate", claude)
        self.assertIn("risk-proportional", readme)
        self.assertIn("Standard review failure does not block implementation", workflow_doc)
        self.assertIn("High-risk planning remains fail-closed", workflow_doc)
        self.assertIn("Committed Spec Kit packages must be complete", checker)
        self.assertIn("Status: Accepted", adr)
        self.assertIn("supersedes the mandatory-gate parts of ADR-0009", adr)
        self.assertIn("must not create a separate process-gate card", adr)


class WorkflowContractTests(unittest.TestCase):
    def test_workflow_is_bounded_planning_only_and_shell_safe(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self.assertIn('speckit_version: ">=0.15.0"', workflow_text)
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

    def test_reviewer_steps_outlive_the_reviewer_process_timeout(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self.assertGreaterEqual(
            workflow_text.count("timeout: 960"),
            2,
            "standard and high-risk reviewer shell steps must exceed the 900s reviewer timeout",
        )


if __name__ == "__main__":
    unittest.main()
