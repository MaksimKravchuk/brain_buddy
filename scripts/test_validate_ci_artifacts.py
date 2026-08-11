import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_ci_artifacts.py"
MUTATION_EVIDENCE_SCRIPT = REPO_ROOT / "scripts" / "create_mutation_allure_evidence.py"


class ValidateCiArtifactsTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_native_product_result(
        self,
        results_dir: Path,
        index: int,
        story: str,
        *,
        status: str = "passed",
        include_evidence: bool = True,
    ) -> None:
        payload: dict[str, object] = {
            "uuid": f"case-{index}",
            "name": story,
            "fullName": f"native product {story}",
            "status": status,
            "labels": [
                {"name": "epic", "value": "BrainBuddy MVP loop"},
                {"name": "feature", "value": "Native tasks and Voice Brain Dump"},
                {"name": "story", "value": story},
            ],
        }
        if include_evidence:
            payload.update(
                {
                    "start": 1_784_324_000_000 + index,
                    "stop": 1_784_324_001_000 + index,
                    "steps": [
                        {"name": f"execute {story}", "status": "passed", "start": 1, "stop": 2}
                    ],
                }
            )
        (results_dir / f"case-{index}-result.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_results_requires_non_empty_allure_result_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "empty-result.json").write_text("", encoding="utf-8")

            completed = self.run_validator(
                "results", "--path", str(results_dir), "--label", "backend-pytest"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend-pytest", completed.stderr)
        self.assertIn("non-empty", completed.stderr)

    def test_results_accepts_non_empty_allure_result_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "case-result.json").write_text(
                '{"uuid":"case-1","name":"runs a journey","fullName":"spec runs a journey","status":"passed","start":100,"stop":125}',
                encoding="utf-8",
            )

            completed = self.run_validator(
                "results", "--path", str(results_dir), "--label", "frontend-vitest"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("frontend-vitest", completed.stdout)

    def test_results_rejects_skipped_only_allure_result_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "case-result.json").write_text(
                '{"uuid":"case-1","name":"skipped journey","fullName":"spec skipped journey","status":"skipped","start":100,"stop":125}',
                encoding="utf-8",
            )

            completed = self.run_validator(
                "results", "--path", str(results_dir), "--label", "playwright-e2e"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("playwright-e2e", completed.stderr)
        self.assertIn("executed", completed.stderr)

    def test_results_rejects_zero_executed_scenario_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "case-result.json").write_text(
                '{"uuid":"case-1","name":"zero duration journey","fullName":"spec zero duration journey","status":"passed","start":100,"stop":100}',
                encoding="utf-8",
            )

            completed = self.run_validator(
                "results", "--path", str(results_dir), "--label", "playwright-e2e"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("zero executed", completed.stderr)

    def test_results_rejects_list_only_json_without_case_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "list-result.json").write_text(
                '{"uuid":"list-1","name":"tests/example.spec.ts","status":"passed","start":100,"stop":125}',
                encoding="utf-8",
            )

            completed = self.run_validator(
                "results", "--path", str(results_dir), "--label", "playwright-e2e"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("list-only", completed.stderr)

    def test_results_rejects_files_older_than_run_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            result = results_dir / "case-result.json"
            result.write_text(
                '{"uuid":"case-1","name":"stale journey","fullName":"spec stale journey","status":"passed","start":100,"stop":125}',
                encoding="utf-8",
            )
            marker = results_dir / ".run-started-at"
            marker.write_text("started", encoding="utf-8")
            result.touch()
            marker.touch()

            completed = self.run_validator(
                "results",
                "--path",
                str(results_dir),
                "--label",
                "playwright-e2e",
                "--since-file",
                str(marker),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("stale", completed.stderr)

    def test_product_e2e_results_require_active_native_story_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            (results_dir / "legacy-result.json").write_text(
                json.dumps(
                    {
                        "name": "legacy /crt smoke",
                        "fullName": "legacy /crt smoke",
                        "status": "passed",
                        "start": 100,
                        "stop": 125,
                        "steps": [{"name": "execute", "status": "passed", "start": 1, "stop": 2}],
                        "labels": [],
                    }
                ),
                encoding="utf-8",
            )

            completed = self.run_validator(
                "product-e2e-results", "--path", str(results_dir)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected active native product scenarios", completed.stderr)

    def test_product_e2e_results_accept_native_tasks_and_voice_brain_dump_matrix(self) -> None:
        stories = [
            "Native task shell navigation",
            "Minimal native task management",
            "Voice Brain Dump happy path",
            "Voice Brain Dump idempotency and recovery",
            "Voice Brain Dump failure recovery",
            "Owner isolation",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            for index, story in enumerate(stories):
                self.write_native_product_result(results_dir, index, story)

            completed = self.run_validator(
                "product-e2e-results", "--path", str(results_dir)
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("native-product-e2e", completed.stdout)

    def test_product_e2e_results_reject_failed_required_story_evidence(self) -> None:
        stories = [
            "Native task shell navigation",
            "Minimal native task management",
            "Voice Brain Dump happy path",
            "Voice Brain Dump idempotency and recovery",
            "Voice Brain Dump failure recovery",
            "Owner isolation",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            for index, story in enumerate(stories):
                self.write_native_product_result(
                    results_dir,
                    index,
                    story,
                    status="failed" if story == "Voice Brain Dump happy path" else "passed",
                )

            completed = self.run_validator(
                "product-e2e-results", "--path", str(results_dir)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must pass", completed.stderr)
        self.assertIn("Voice Brain Dump happy path", completed.stderr)

    def test_product_e2e_results_reject_label_only_placeholder_evidence(self) -> None:
        stories = [
            "Native task shell navigation",
            "Minimal native task management",
            "Voice Brain Dump happy path",
            "Voice Brain Dump idempotency and recovery",
            "Voice Brain Dump failure recovery",
            "Owner isolation",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / "allure-results"
            results_dir.mkdir()
            for index, story in enumerate(stories):
                self.write_native_product_result(
                    results_dir, index, story, include_evidence=False
                )

            completed = self.run_validator(
                "product-e2e-results", "--path", str(results_dir)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("meaningful Playwright evidence", completed.stderr)

    def test_workflow_rejects_nested_workflow_and_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            nested = root / "frontend" / ".github" / "workflows" / "playwright.yml"
            workflow.parent.mkdir(parents=True)
            nested.parent.mkdir(parents=True)
            workflow.write_text("name: CI\njobs: {}\n", encoding="utf-8")
            nested.write_text("name: Playwright\n", encoding="utf-8")

            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--disallow-workflow",
                str(nested),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("nested workflow", completed.stderr)
        self.assertIn("backend-allure-results", completed.stderr)

    def test_workflow_rejects_missing_frontend_lint_and_coverage_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            vite_config = root / "frontend" / "vite.config.ts"
            workflow.parent.mkdir(parents=True)
            vite_config.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  frontend:
    steps:
      - run: npm run test -- --coverage
      - run: npm run build
  allure-report:
    steps:
      - run: python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/vitest --label frontend-vitest
      - run: npm run test:e2e
      - run: python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/playwright --label frontend-playwright
      - run: npx allure generate ../allure-results -o ../allure-report
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: backend-allure-results
          path: backend/allure-results
          retention-days: 30
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: frontend-allure-results
          path: frontend/allure-results
          retention-days: 30
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: e2e-allure-results
          path: frontend/allure-results/playwright
          retention-days: 30
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: allure-report-html
          path: allure-report
          retention-days: 30
""".strip(),
                encoding="utf-8",
            )
            vite_config.write_text(
                """
export default defineConfig({
  test: {
    coverage: {
      provider: "istanbul",
      reporter: ["text", "lcov"]
    }
  }
});
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(vite_config),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("frontend lint", completed.stderr)
        self.assertIn("frontend coverage threshold statements", completed.stderr)

    def test_workflow_rejects_missing_pr_scoped_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: CI\njobs: {}\n", encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("concurrency", completed.stderr)

    def test_workflow_rejects_unconditional_cancel_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
concurrency:
  group: ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
jobs: {}
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cancel-in-progress must cancel only pull_request runs", completed.stderr)

    def test_workflow_rejects_hardcoded_thirty_day_retention_without_pr_scoping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
concurrency:
  group: ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  backend:
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: backend-allure-results
          path: backend/allure-results
          retention-days: 30
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("PR-scoped expression", completed.stderr)

    def test_workflow_rejects_missing_docker_images_status_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
concurrency:
  group: ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  docker:
    name: Docker Build
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: backend-allure-results
          path: backend/allure-results
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Docker Images", completed.stderr)

    def test_workflow_rejects_stack_lane_chained_behind_an_unrelated_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(
                """
jobs:
  backend:
    needs:
      - spec-kit
      - changes
    steps:
      - run: pytest
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend job declares needs it does not consume", completed.stderr)
        self.assertIn("spec-kit", completed.stderr)

    def test_workflow_rejects_e2e_queued_behind_gates_that_do_not_guard_it(self) -> None:
        # Waiting on backend and frontend is allowed -- they are the cheap checks
        # that should fail before the stack is built. Waiting on the markdown
        # gate, or on a service that ships in neither image, is not.
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(
                """
jobs:
  e2e:
    name: Compose Playwright E2E
    needs:
      - backend
      - frontend
      - mobile
      - spec-kit
    steps:
      - run: make test-e2e
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("e2e job declares needs it does not consume", completed.stderr)
        self.assertIn("mobile", completed.stderr)
        self.assertIn("spec-kit", completed.stderr)
        # The legitimate cost gates must not be reported as surplus.
        self.assertNotIn("'backend'", completed.stderr)

    def test_workflow_accepts_expensive_lanes_gated_on_the_cheap_service_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(
                """
jobs:
  e2e:
    needs:
      - backend
      - frontend
    steps:
      - run: make test-e2e
  docker:
    needs: e2e
    steps:
      - run: docker buildx build .
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        # The fixture is a fragment, so other checks still fail it; what matters
        # is that the job-graph rule raised no complaint about these two.
        self.assertNotIn("declares needs it does not consume", completed.stderr)

    def test_workflow_rejects_docker_restating_the_edges_e2e_already_carries(self) -> None:
        # docker waits on e2e for cache locality. Naming backend/frontend as well
        # restates edges e2e already holds, which is the noise the rule exists to
        # keep out -- and it would let the pair drift back into running in
        # parallel and paying the identical image build twice.
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(
                """
jobs:
  docker:
    name: Docker Images
    needs:
      - e2e
      - backend
      - frontend
    steps:
      - run: docker buildx build .
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("docker job declares needs it does not consume", completed.stderr)
        self.assertIn("backend", completed.stderr)

    def test_workflow_rejects_a_job_absent_from_the_full_ci_gate(self) -> None:
        # A flat graph makes full-ci the only thing that makes a job required,
        # so a job missing from its needs is unchecked rather than lenient.
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(
                """
jobs:
  changes:
    steps:
      - run: echo decide
  security-scan:
    steps:
      - run: echo scan
  full-ci:
    needs:
      - changes
    steps:
      - run: echo "${{ contains(needs.*.result, 'skipped') }}"
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("full-ci does not require every job", completed.stderr)
        self.assertIn("security-scan", completed.stderr)

    def test_workflow_accepts_pr_scoped_concurrency_and_conditional_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows" / "ci.yml"
            vite_config = root / "frontend" / "vite.config.ts"
            workflow.parent.mkdir(parents=True)
            vite_config.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
concurrency:
  group: ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  changes:
    name: Changed stacks
    outputs:
      backend: ${{ steps.decide.outputs.backend }}
      frontend: ${{ steps.decide.outputs.frontend }}
      mobile: ${{ steps.decide.outputs.mobile }}
    steps:
      - id: decide
        run: echo decide
  backend:
    env:
      RUN: ${{ needs.changes.outputs.backend }}
    steps:
      - name: Ruff lint
        if: env.RUN == 'true'
        run: ruff check app tests
  mobile:
    env:
      RUN: ${{ needs.changes.outputs.mobile }}
    steps:
      - name: Type check
        if: env.RUN == 'true'
        run: npm run typecheck
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: mobile-allure-results
          path: mobile/allure-results
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
  mutation-base:
    name: Backend mutation base measurement
    env:
      RUN: ${{ needs.changes.outputs.mutation }}
    steps:
      - uses: actions/checkout@v4
        if: env.RUN == 'true'
        with:
          ref: ${{ github.event.pull_request.base.sha }}
          path: base
      - name: Measure the base revision
        if: env.RUN == 'true'
        run: |
          python3 scripts/mutation_gate.py scope \
            --enforced backend/mutation-enforced-scope.txt \
            --changed /tmp/base-scope.txt --apply-to base/backend/pyproject.toml
  mutation-head:
    name: Backend mutation head measurement
    env:
      RUN: ${{ needs.changes.outputs.mutation }}
    steps:
      - name: Measure the enforced scope at this revision
        if: env.RUN == 'true'
        run: |
          python3 scripts/mutation_gate.py scope \
            --enforced backend/mutation-enforced-scope.txt \
            --changed /tmp/head-scope.txt --apply-to backend/pyproject.toml
      - name: Create blocking-gate Allure evidence
        if: always() && env.RUN == 'true'
        run: |
          python3 scripts/create_mutation_allure_evidence.py --mode blocking-gate \
            --summary s.txt --survivors v.txt --output r.json
  mutation-gate:
    name: Backend mutation gate
    env:
      RUN: ${{ needs.changes.outputs.mutation }}
    steps:
      - name: Enforce the mutation gate
        if: env.RUN == 'true'
        run: |
          python3 scripts/mutation_gate.py check --stats stats.json --base-stats base.json
  full-ci:
    needs:
      - changes
      - backend
      - mobile
      - frontend
      - e2e
      - docker
      - allure-report
      - mutation-base
      - mutation-head
      - mutation-gate
    steps:
      - run: echo "${{ contains(needs.*.result, 'skipped') }}"
  frontend:
    env:
      RUN: ${{ needs.changes.outputs.frontend }}
    steps:
      - run: npm run lint
      - run: npm run test:coverage
      - run: npm run build
      - run: npm run test:e2e
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: backend-allure-results
          path: backend/allure-results
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: frontend-allure-results
          path: frontend/allure-results
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-allure-results
          path: frontend/allure-results/playwright
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: allure-report-html
          path: allure-report
          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}
  e2e:
    name: Compose Playwright E2E
    steps:
      - run: |
          make test-e2e
      - run: npx playwright install --with-deps chromium
      - run: |
          python3 scripts/validate_ci_artifacts.py results --path frontend/allure-results/playwright --label playwright-e2e
          python3 scripts/validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright
  docker:
    name: Docker Images
    steps:
      - run: echo build
  allure-report:
    steps:
      - run: python3 scripts/validate_allure_taxonomy.py
      - run: npx allure generate ../allure-results -o ../allure-report
""".strip(),
                encoding="utf-8",
            )
            vite_config.write_text(
                """
export default defineConfig({
  test: {
    coverage: {
      provider: "istanbul",
      thresholds: {
        statements: 98,
        branches: 97,
        functions: 98,
        lines: 98
      }
    }
  }
});
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(vite_config),
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def conformant_preview_workflow_text(self) -> str:
        return """
name: Fly Review App (Frontend)

on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled, closed]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}
  cancel-in-progress: true

env:
  PREVIEW_LABEL: preview:visual
  PRODUCTION_APP_NAMES: "brain-buddy-frontend brain-buddy-backend"
  FLY_APP_PREFIX: ${{ secrets.FLY_APP_PREFIX || 'brain-buddy-frontend-pr' }}

jobs:
  eligibility:
    name: Preview eligibility
    runs-on: ubuntu-latest
    steps:
      - name: Evaluate eligibility
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          if [ "$HEAD_REPO_FULL_NAME" != "$REPO" ]; then
            echo "fork PR ineligible for secret-bearing preview"
          fi
          if [ "$BASE_REF" != "main" ]; then
            echo "pull request does not target main"
          fi
          if [ "$STATE" != "open" ]; then
            echo "pull request is not open"
          fi
          if printf '%s\\n' "$LABELS" | grep -qx "$PREVIEW_LABEL"; then
            echo "has label"
          fi

  deploy:
    name: Deploy preview
    needs: eligibility
    runs-on: ubuntu-latest
    concurrency:
      group: preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    env:
      FLY_API_TOKEN: ${{ secrets.FLY_PREVIEW_API_TOKEN }}
    steps:
      - name: Re-verify before mutation
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          CURRENT_HEAD_SHA=$(gh api "repos/$REPO/pulls/$PR_NUMBER" --jq .head.sha)
          if [ "$CURRENT_HEAD_SHA" != "$EVENT_HEAD_SHA" ]; then
            echo "stale head sha, a newer run supersedes this one"
            exit 1
          fi

      - name: Reject production app target
        run: |
          for production_app in $PRODUCTION_APP_NAMES; do
            if [ "$APP_NAME" = "$production_app" ]; then
              echo "refusing to target production app $APP_NAME"
              exit 1
            fi
          done

      - name: Create-or-observe app
        run: |
          if ! flyctl status -a "$APP_NAME" >/dev/null 2>&1; then
            flyctl apps create "$APP_NAME"
          fi

      - name: Deploy review app
        run: flyctl deploy --app "$APP_NAME" --config fly.frontend.toml --remote-only

      - name: Smoke check preview reachability
        run: curl --fail --retry 5 "https://${APP_NAME}.fly.dev/"

      - name: Upsert PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const marker = '<!-- brain-buddy-preview -->';
            const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number });
            const existing = comments.find((comment) => comment.body?.includes(marker));
            if (existing) {
              await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
            } else {
              await github.rest.issues.createComment({ owner, repo, issue_number, body });
            }

  cleanup:
    name: Cleanup preview
    needs: eligibility
    runs-on: ubuntu-latest
    concurrency:
      group: preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}
      cancel-in-progress: true
    env:
      FLY_API_TOKEN: ${{ secrets.FLY_PREVIEW_API_TOKEN }}
    steps:
      - name: Reject production app target
        run: |
          for production_app in $PRODUCTION_APP_NAMES; do
            if [ "$APP_NAME" = "$production_app" ]; then
              echo "refusing to target production app $APP_NAME"
              exit 1
            fi
          done

      - name: Destroy review app
        run: |
          if flyctl status -a "$APP_NAME" >/dev/null 2>&1; then
            flyctl apps destroy "$APP_NAME" --yes
          else
            echo "already absent"
          fi

      - name: Verify absence
        run: |
          if flyctl status -a "$APP_NAME" >/dev/null 2>&1; then
            echo "destroy did not take effect"
            exit 1
          fi

      - name: Upsert PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const marker = '<!-- brain-buddy-preview -->';
            const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number });
            const existing = comments.find((comment) => comment.body?.includes(marker));
            if (existing) {
              await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
            } else {
              await github.rest.issues.createComment({ owner, repo, issue_number, body });
            }
""".strip()

    def test_preview_workflow_rejects_deploy_without_explicit_label_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            workflow.write_text(
                self.conformant_preview_workflow_text().replace("preview:visual", "always-deploy"),
                encoding="utf-8",
            )

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("preview:visual", completed.stderr)

    def test_preview_workflow_rejects_missing_per_pr_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text()
            text = text.replace(
                "group: preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}\n"
                "      cancel-in-progress: true\n",
                "",
            ).replace(
                "concurrency:\n  group: preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}\n"
                "  cancel-in-progress: true\n\n",
                "",
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("concurrency", completed.stderr)

    def test_preview_workflow_rejects_unconditional_cleanup_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                'flyctl apps destroy "$APP_NAME" --yes',
                'flyctl apps destroy "$APP_NAME" --yes || true',
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("|| true", completed.stderr)

    def test_preview_workflow_rejects_missing_fork_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                'if [ "$HEAD_REPO_FULL_NAME" != "$REPO" ]; then\n            echo "fork PR ineligible for secret-bearing preview"\n          fi\n',
                "",
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("fork", completed.stderr)

    def test_preview_workflow_rejects_missing_production_app_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                'PRODUCTION_APP_NAMES: "brain-buddy-frontend brain-buddy-backend"',
                'PRODUCTION_APP_NAMES: ""',
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("production app", completed.stderr)

    def test_preview_workflow_rejects_shared_preview_and_production_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                "secrets.FLY_PREVIEW_API_TOKEN", "secrets.FLY_API_TOKEN"
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("preview-only", completed.stderr)

    def test_preview_workflow_rejects_missing_latest_head_reverification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                "CURRENT_HEAD_SHA", "IGNORED_HEAD_SHA"
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("head sha", completed.stderr)

    def test_preview_workflow_rejects_missing_smoke_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            text = self.conformant_preview_workflow_text().replace(
                '- name: Smoke check preview reachability\n        run: curl --fail --retry 5 "https://${APP_NAME}.fly.dev/"\n\n',
                "",
            )
            workflow.write_text(text, encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("smoke", completed.stderr)

    def test_preview_workflow_accepts_conformant_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "fly-review-frontend.yml"
            workflow.write_text(self.conformant_preview_workflow_text(), encoding="utf-8")

            completed = self.run_validator("preview-workflow", "--workflow", str(workflow))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("preview-workflow", completed.stdout)

    def test_mutation_workflow_rejects_a_non_nightly_workflow_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "mutation.yml"
            workflow.write_text(
                "name: Mutation\non:\n  pull_request:\njobs: {}\n",
                encoding="utf-8",
            )

            completed = self.run_validator("mutation-workflow", "--workflow", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("schedule", completed.stderr)
        self.assertIn("report-only", completed.stderr)
        self.assertIn("mutation-summary", completed.stderr)

    def test_mutation_workflow_requires_the_frontend_campaign_and_its_evidence(self) -> None:
        workflow = REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"
        text = workflow.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            without_frontend = Path(tmp) / "mutation.yml"
            without_frontend.write_text(
                text.replace("  frontend-observed-mutation:", "  frontend-disabled:"),
                encoding="utf-8",
            )
            missing_job = self.run_validator(
                "mutation-workflow", "--workflow", str(without_frontend)
            )

            without_evidence = Path(tmp) / "mutation-no-evidence.yml"
            without_evidence.write_text(
                text.replace("name: frontend-mutation-report", "name: something-else"),
                encoding="utf-8",
            )
            missing_evidence = self.run_validator(
                "mutation-workflow", "--workflow", str(without_evidence)
            )

        self.assertNotEqual(missing_job.returncode, 0)
        self.assertIn("frontend observed-scope job", missing_job.stderr)
        self.assertNotEqual(missing_evidence.returncode, 0)
        self.assertIn("frontend-mutation-report", missing_evidence.stderr)

    def test_mutation_workflow_requires_the_mobile_campaign_and_its_evidence(self) -> None:
        workflow = REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"
        text = workflow.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            without_mobile = Path(tmp) / "mutation.yml"
            without_mobile.write_text(
                text.replace("  mobile-observed-mutation:", "  mobile-disabled:"),
                encoding="utf-8",
            )
            missing_job = self.run_validator(
                "mutation-workflow", "--workflow", str(without_mobile)
            )

            narrowed = Path(tmp) / "mutation-narrowed.yml"
            narrowed.write_text(
                text.replace("src/lifecycle/guards.ts", "src/lifecycle/nothing.ts"),
                encoding="utf-8",
            )
            missing_scope = self.run_validator("mutation-workflow", "--workflow", str(narrowed))

            without_evidence = Path(tmp) / "mutation-no-evidence.yml"
            without_evidence.write_text(
                text.replace("name: mobile-mutation-report", "name: something-else"),
                encoding="utf-8",
            )
            missing_evidence = self.run_validator(
                "mutation-workflow", "--workflow", str(without_evidence)
            )

        self.assertNotEqual(missing_job.returncode, 0)
        self.assertIn("mobile observed-scope job", missing_job.stderr)
        self.assertNotEqual(missing_scope.returncode, 0)
        self.assertIn("src/lifecycle/guards.ts", missing_scope.stderr)
        self.assertNotEqual(missing_evidence.returncode, 0)
        self.assertIn("mobile-mutation-report", missing_evidence.stderr)

    def test_the_repository_mutation_workflow_satisfies_every_campaign(self) -> None:
        completed = self.run_validator(
            "mutation-workflow",
            "--workflow",
            str(REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"),
            "--frontend-stryker-config",
            str(REPO_ROOT / "frontend" / "stryker.config.json"),
            "--mobile-stryker-config",
            str(REPO_ROOT / "mobile" / "stryker.config.json"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def _workflow_with_stryker_configs(self, tmp: Path, **mutate: list[str]) -> list[str]:
        """Validator args pointing at doctored copies of the Stryker configs."""

        args = [
            "mutation-workflow",
            "--workflow",
            str(REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"),
        ]
        for stack, flag in (("frontend", "--frontend-stryker-config"), ("mobile", "--mobile-stryker-config")):
            source = REPO_ROOT / stack / "stryker.config.json"
            config = json.loads(source.read_text(encoding="utf-8"))
            if stack in mutate:
                config["mutate"] = mutate[stack]
            target = tmp / f"{stack}-stryker.config.json"
            target.write_text(json.dumps(config), encoding="utf-8")
            args += [flag, str(target)]
        return args

    def test_narrowing_the_mobile_stryker_config_fails_even_with_the_workflow_intact(
        self,
    ) -> None:
        # The workflow's header comment names every mobile module, so a check
        # that only reads the workflow would pass here. The config is what the
        # campaign obeys.
        full = json.loads(
            (REPO_ROOT / "mobile" / "stryker.config.json").read_text(encoding="utf-8")
        )["mutate"]
        narrowed = [path for path in full if path != "src/lifecycle/guards.ts"]

        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_validator(
                *self._workflow_with_stryker_configs(Path(tmp), mobile=narrowed)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("src/lifecycle/guards.ts", completed.stderr)
        self.assertIn("mobile observed", completed.stderr)

    def test_narrowing_the_frontend_stryker_config_fails_the_same_way(self) -> None:
        full = json.loads(
            (REPO_ROOT / "frontend" / "stryker.config.json").read_text(encoding="utf-8")
        )["mutate"]
        narrowed = [path for path in full if path != "src/utils/error.ts"]

        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_validator(
                *self._workflow_with_stryker_configs(Path(tmp), frontend=narrowed)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("src/utils/error.ts", completed.stderr)
        self.assertIn("frontend observed", completed.stderr)

    def test_widening_a_stryker_config_past_the_known_scope_also_fails(self) -> None:
        # Widening without an ADR is a scope change too; it must not slip in
        # under a validator that only looks for missing entries.
        full = json.loads(
            (REPO_ROOT / "mobile" / "stryker.config.json").read_text(encoding="utf-8")
        )["mutate"]

        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_validator(
                *self._workflow_with_stryker_configs(
                    Path(tmp), mobile=[*full, "src/theme/tokens.ts"]
                )
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("src/theme/tokens.ts", completed.stderr)

    def test_an_unreadable_stryker_config_fails_rather_than_being_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "stryker.config.json"
            broken.write_text("{not json", encoding="utf-8")

            completed = self.run_validator(
                "mutation-workflow",
                "--workflow",
                str(REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"),
                "--mobile-stryker-config",
                str(broken),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("invalid Stryker config JSON", completed.stderr)

    def test_a_missing_stryker_config_fails_rather_than_being_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_validator(
                "mutation-workflow",
                "--workflow",
                str(REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml"),
                "--mobile-stryker-config",
                str(Path(tmp) / "absent.json"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not exist", completed.stderr)

    def test_mutation_evidence_carries_the_campaign_it_came_from(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "mutation-summary.txt"
            survivors = root / "mutation-survivors.txt"
            output = root / "mutation-evidence-result.json"
            summary.write_text("src/utils/error.ts: 97.69%\n", encoding="utf-8")
            survivors.write_text("No surviving mutants\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MUTATION_EVIDENCE_SCRIPT),
                    "--summary",
                    str(summary),
                    "--survivors",
                    str(survivors),
                    "--scope-label",
                    "frontend",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            evidence = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("frontend", evidence["name"])
        self.assertIn("report-only", evidence["name"])
        self.assertEqual(evidence["fullName"], "quality.mutation.frontend.report_only_evidence")

    def test_mutation_evidence_is_explicitly_informational_not_a_product_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "mutation-summary.txt"
            survivors = root / "mutation-survivors.txt"
            output = root / "mutation-evidence-result.json"
            summary.write_text("Mutation score: 95.0%\n", encoding="utf-8")
            survivors.write_text("No surviving mutants\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MUTATION_EVIDENCE_SCRIPT),
                    "--summary",
                    str(summary),
                    "--survivors",
                    str(survivors),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            evidence = output.read_text(encoding="utf-8") if output.exists() else ""

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Mutation campaign evidence", evidence)
        self.assertIn("not a product test", evidence)
        self.assertIn("mutation-summary.txt", evidence)
        self.assertIn("mutation-survivors.txt", evidence)

    def test_blocking_gate_evidence_is_not_labelled_report_only(self) -> None:
        # The nightly cannot fail anything and the pull-request gate can. Both
        # write Allure evidence, and a reader has to be able to tell which
        # campaign produced the number in front of them.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "mutation-summary.txt"
            survivors = root / "mutation-survivors.txt"
            output = root / "mutation-gate-result.json"
            summary.write_text("Mutation score: 97.9%\n", encoding="utf-8")
            survivors.write_text("28 non-behavioral survivors\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(MUTATION_EVIDENCE_SCRIPT),
                    "--mode",
                    "blocking-gate",
                    "--summary",
                    str(summary),
                    "--survivors",
                    str(survivors),
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            evidence = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Mutation gate evidence", evidence["name"])
        self.assertIn("blocking", evidence["name"])
        tags = {
            label["value"] for label in evidence["labels"] if label["name"] == "tag"
        }
        self.assertIn("blocking-gate", tags)
        self.assertNotIn("report-only", tags)

    def test_workflow_rejects_a_ci_file_that_dropped_the_mutation_gate(self) -> None:
        # The gate is only worth its presence in the workflow. A CI file that is
        # otherwise conformant but has no gate must not validate.
        conformant = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        without_gate = conformant.replace("  mutation-gate:", "  mutation-gate-x:", 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(without_gate, encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mutation gate job", completed.stderr)

    def test_workflow_rejects_a_gate_without_the_base_revision_comparison(self) -> None:
        conformant = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        without_base = conformant.replace("--base-stats", "--stats-only")

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(without_base, encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("base-revision comparison", completed.stderr)

    def test_workflow_rejects_chaining_the_two_mutation_measurements(self) -> None:
        # The measurements must overlap. Making one need the other doubles a
        # pull request's wall-clock, which is the shape this gate started as.
        conformant = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        head_job = (
            "  mutation-head:\n"
            "    name: Backend mutation head measurement\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 90\n"
            "    needs:\n"
            "      - changes\n"
            "      - backend\n"
        )
        serialised = conformant.replace(
            head_job, head_job + "      - mutation-base\n", 1
        )
        self.assertNotEqual(serialised, conformant, "fixture edit did not apply")

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(serialised, encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must not depend on mutation-base", completed.stderr)

    def test_mutation_workflow_must_report_the_enforced_tier(self) -> None:
        # The nightly's own scope is the observed tier and can never clear 95%.
        # Without this summary nothing scheduled measures the tier that blocks.
        nightly = (REPO_ROOT / ".github" / "workflows" / "mutation-quality.yml").read_text(
            encoding="utf-8"
        )
        without = nightly.replace("summarize-mutmut", "summarize-nothing")

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "mutation.yml"
            workflow.write_text(without, encoding="utf-8")

            completed = self.run_validator(
                "mutation-workflow", "--workflow", str(workflow)
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("summarize-mutmut", completed.stderr)

    def test_workflow_rejects_a_mutation_gate_hidden_behind_a_job_level_if(self) -> None:
        # A job-level `if` makes the gate report 'skipped', which is exactly the
        # result ADR-0008 requires Full CI to treat as a failure.
        conformant = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        skippable = conformant.replace(
            "  mutation-gate:\n    name: Backend mutation gate\n",
            "  mutation-gate:\n    name: Backend mutation gate\n"
            "    if: needs.changes.outputs.mutation == 'true'\n",
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / "ci.yml"
            workflow.write_text(skippable, encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mutation-gate job uses a job-level 'if'", completed.stderr)


class CoverageSuppressionTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_clean_source_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nested").mkdir()
            (root / "nested" / "widget.tsx").write_text(
                "export const widget = () => null;\n", encoding="utf-8"
            )

            completed = self.run_validator("coverage-suppressions", "--path", str(root))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("no blanket coverage exclusions", completed.stdout)

    def test_file_level_exclusion_is_rejected_with_its_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shell.tsx").write_text(
                "/* istanbul ignore file -- covered by Playwright */\n"
                "export const shell = () => null;\n",
                encoding="utf-8",
            )

            completed = self.run_validator("coverage-suppressions", "--path", str(root))

        self.assertEqual(completed.returncode, 1)
        self.assertIn("shell.tsx:1", completed.stderr)
        self.assertIn("blanket coverage suppression", completed.stderr)

    def test_range_and_v8_exclusions_are_rejected_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "range.ts").write_text(
                "/* c8 ignore start */\nconst hidden = 1;\n", encoding="utf-8"
            )
            (root / "v8.ts").write_text("/* v8 ignore file */\n", encoding="utf-8")

            completed = self.run_validator("coverage-suppressions", "--path", str(root))

        self.assertEqual(completed.returncode, 1)
        self.assertIn("c8 ignore start", completed.stderr)
        self.assertIn("v8 ignore file", completed.stderr)

    def test_narrow_exclusion_needs_a_justification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bare.ts").write_text(
                "/* istanbul ignore next */\nconst guard = 1;\n", encoding="utf-8"
            )
            (root / "explained.ts").write_text(
                "/* istanbul ignore next -- unreachable without a browser */\n"
                "const other = 1;\n",
                encoding="utf-8",
            )

            completed = self.run_validator("coverage-suppressions", "--path", str(root))

        self.assertEqual(completed.returncode, 1)
        self.assertIn("bare.ts:1", completed.stderr)
        self.assertNotIn("explained.ts", completed.stderr)

    def test_missing_directory_is_an_error_rather_than_a_pass(self) -> None:
        completed = self.run_validator(
            "coverage-suppressions", "--path", "frontend/does-not-exist"
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("does not exist", completed.stderr)

    def test_the_repository_frontend_and_mobile_sources_are_clean(self) -> None:
        completed = self.run_validator(
            "coverage-suppressions",
            "--path",
            "frontend/src",
            "--path",
            "mobile/src",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


class MutationScopeTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def build(self, root: Path, observed: list[str], enforced: list[str]) -> tuple[Path, Path]:
        for path in observed:
            source = root / path
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("export const value = 1;\n", encoding="utf-8")
        config = root / "stryker.config.json"
        config.write_text(json.dumps({"mutate": observed}), encoding="utf-8")
        scope = root / "mutation-enforced-scope.txt"
        scope.write_text("# the enforced tier\n" + "".join(f"{p}\n" for p in enforced), encoding="utf-8")
        return config, scope

    def test_an_enforced_subset_of_the_observed_scope_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, scope = self.build(
                Path(tmp), ["src/a.ts", "src/b.ts"], ["src/a.ts"]
            )
            completed = self.run_validator(
                "mutation-scope", "--config", str(config), "--enforced", str(scope)
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1 enforced file(s) within 2 observed file(s)", completed.stdout)

    def test_an_enforced_file_outside_the_observed_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, scope = self.build(root, ["src/a.ts"], ["src/a.ts", "src/gated.ts"])
            (root / "src" / "gated.ts").write_text("export const g = 1;\n", encoding="utf-8")
            completed = self.run_validator(
                "mutation-scope", "--config", str(config), "--enforced", str(scope)
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("never measure it", completed.stderr)

    def test_a_scope_entry_that_no_longer_exists_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, scope = self.build(root, ["src/a.ts", "src/moved.ts"], ["src/a.ts"])
            (root / "src" / "moved.ts").unlink()
            completed = self.run_validator(
                "mutation-scope", "--config", str(config), "--enforced", str(scope)
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("src/moved.ts does not exist", completed.stderr)

    def test_an_empty_enforced_list_is_rejected_rather_than_passing_vacuously(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, scope = self.build(Path(tmp), ["src/a.ts"], [])
            completed = self.run_validator(
                "mutation-scope", "--config", str(config), "--enforced", str(scope)
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("lists no files", completed.stderr)

    def test_the_repository_frontend_tiers_are_consistent(self) -> None:
        completed = self.run_validator(
            "mutation-scope",
            "--config",
            "frontend/stryker.config.json",
            "--enforced",
            "frontend/mutation-enforced-scope.txt",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
