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

    def test_workflow_rejects_missing_mobile_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: CI\njobs: {}\n", encoding="utf-8")

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("missing mobile CI job", completed.stderr)

    def test_workflow_rejects_unlocked_backend_install_in_mobile_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    steps:
      - name: Install backend contract dependencies
        run: |
          pip install -e ./backend[dev]
      - name: Verify committed OpenAPI semantic and generated-client drift
        run: python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
      - name: Scan publishable mobile evidence for privacy leaks
        run: python3 ../scripts/validate_mobile_privacy_evidence.py
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("uv sync --locked", completed.stderr)
        self.assertIn("unlocked pip install", completed.stderr)

    def test_workflow_rejects_inline_privacy_scan_without_the_maintainable_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    steps:
      - name: Install backend contract dependencies
        run: uv sync --locked --extra dev
      - name: Verify committed OpenAPI semantic and generated-client drift
        run: python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
      - name: Scan mobile artifacts for credential-shaped values
        run: |
          python3 - <<'PY'
          print("inline scan, not the maintainable validator")
          PY
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("validate_mobile_privacy_evidence.py", completed.stderr)

    def test_workflow_rejects_mobile_privacy_scan_missing_if_always_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    steps:
      - name: Install backend contract dependencies
        run: uv sync --locked --extra dev
      - name: Verify committed OpenAPI semantic and generated-client drift
        run: python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
      - name: Scan publishable mobile evidence for privacy leaks
        id: mobile_privacy_scan
        run: python3 ../scripts/validate_mobile_privacy_evidence.py
      - name: Upload mobile Allure results
        if: steps.mobile_privacy_scan.outcome == 'success'
        with:
          name: mobile-allure-results
  allure-report:
    steps:
      - name: Require explicit mobile privacy scan success
        if: needs.mobile.outputs.privacy_scan_outcome != 'success'
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("if: always()", completed.stderr)
        self.assertIn("ADR-0008", completed.stderr)

    def test_workflow_rejects_mobile_privacy_scan_without_success_publication_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    steps:
      - name: Install backend contract dependencies
        run: uv sync --locked --extra dev
      - name: Verify committed OpenAPI semantic and generated-client drift
        run: python -m scripts.openapi_snapshot check --snapshot ../mobile/api/openapi.json
      - name: Scan publishable mobile evidence for privacy leaks
        id: mobile_privacy_scan
        if: always()
        run: python3 ../scripts/validate_mobile_privacy_evidence.py
      - name: Upload mobile Allure results
        with:
          name: mobile-allure-results
  allure-report:
    steps:
      - name: Generate Allure Report
        run: npx allure generate ../allure-results -o ../allure-report
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("successful-scan gate for mobile Allure upload", completed.stderr)
        self.assertIn("aggregate Allure report publication gate", completed.stderr)

    def test_workflow_rejects_when_only_backend_layer_is_wired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  backend:
    outputs:
      privacy_scan_outcome: ${{ steps.backend_privacy_scan.outcome }}
    steps:
      - name: Scan backend Allure evidence for privacy leaks
        id: backend_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path backend/allure-results \\
            --label backend-evidence
      - name: Upload backend Allure results
        if: steps.backend_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: backend-allure-results
          path: backend/allure-results
  allure-report:
    steps:
      - name: Require explicit privacy scan success for all layers
        if: needs.backend.outputs.privacy_scan_outcome != 'success'
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("frontend layer privacy scan step", completed.stderr)
        self.assertIn("playwright layer privacy scan step", completed.stderr)
        self.assertIn("mobile layer privacy scan step", completed.stderr)
        # A fully wired backend layer must not itself be reported as missing.
        self.assertNotIn("backend layer privacy scan step must set id", completed.stderr)
        self.assertNotIn(
            "missing backend job output privacy_scan_outcome", completed.stderr
        )
        self.assertNotIn(
            "missing successful-scan gate for backend Allure upload", completed.stderr
        )
        self.assertNotIn(
            "missing aggregate Allure report publication gate on backend",
            completed.stderr,
        )

    def test_workflow_rejects_backend_layer_scan_step_scoped_to_wrong_allure_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  backend:
    outputs:
      privacy_scan_outcome: ${{ steps.backend_privacy_scan.outcome }}
    steps:
      - name: Scan backend Allure evidence for privacy leaks
        id: backend_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/allure-results/vitest \\
            --label backend-evidence
      - name: Upload backend Allure results
        if: steps.backend_privacy_scan.outcome == 'success'
        with:
          name: backend-allure-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend layer privacy scan step", completed.stderr)
        self.assertIn("backend/allure-results", completed.stderr)

    def test_workflow_rejects_frontend_and_playwright_layers_missing_upload_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  frontend:
    outputs:
      privacy_scan_outcome: ${{ steps.frontend_privacy_scan.outcome }}
    steps:
      - name: Scan frontend Allure evidence for privacy leaks
        id: frontend_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/allure-results/vitest \\
            --label frontend-evidence
      - name: Upload frontend Allure results
        if: always()
        with:
          name: frontend-allure-results
  e2e:
    outputs:
      privacy_scan_outcome: ${{ steps.playwright_privacy_scan.outcome }}
    steps:
      - name: Scan Playwright Allure evidence for privacy leaks
        id: playwright_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/allure-results/playwright \\
            --label playwright-evidence
      - name: Upload Playwright Allure results
        if: always()
        with:
          name: playwright-allure-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "missing successful-scan gate for frontend Allure upload", completed.stderr
        )
        self.assertIn(
            "missing successful-scan gate for playwright Allure upload", completed.stderr
        )

    def test_workflow_rejects_aggregate_gate_missing_non_mobile_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    outputs:
      privacy_scan_outcome: ${{ steps.mobile_privacy_scan.outcome }}
    steps:
      - name: Scan publishable mobile evidence for privacy leaks
        id: mobile_privacy_scan
        if: always()
        run: |
          python3 ../scripts/validate_mobile_privacy_evidence.py \\
            --path allure-results \\
            --label mobile-evidence
      - name: Upload mobile Allure results
        if: steps.mobile_privacy_scan.outcome == 'success'
        with:
          name: mobile-allure-results
  allure-report:
    steps:
      - name: Require explicit mobile privacy scan success
        if: needs.mobile.outputs.privacy_scan_outcome != 'success'
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "aggregate Allure report publication gate on backend", completed.stderr
        )
        self.assertIn(
            "aggregate Allure report publication gate on frontend", completed.stderr
        )
        self.assertIn(
            "aggregate Allure report publication gate on playwright", completed.stderr
        )
        self.assertNotIn(
            "aggregate Allure report publication gate on mobile", completed.stderr
        )

    def test_workflow_rejects_upload_gate_weakened_with_or_true_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  backend:
    outputs:
      privacy_scan_outcome: ${{ steps.backend_privacy_scan.outcome }}
    steps:
      - name: Scan backend Allure evidence for privacy leaks
        id: backend_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path backend/allure-results \\
            --label backend-evidence
      - name: Upload backend Allure results
        if: steps.backend_privacy_scan.outcome == 'success' || true
        uses: actions/upload-artifact@v4
        with:
          name: backend-allure-results
          path: backend/allure-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "missing successful-scan gate for backend Allure upload", completed.stderr
        )

    def test_workflow_rejects_scan_of_clean_root_when_real_path_is_only_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  e2e:
    outputs:
      privacy_scan_outcome: ${{ steps.playwright_privacy_scan.outcome }}
    steps:
      - name: Scan Playwright Allure evidence for privacy leaks
        id: playwright_privacy_scan
        if: always()
        run: |
          # python3 scripts/validate_mobile_privacy_evidence.py --path frontend/allure-results/playwright --path frontend/playwright-report --path frontend/test-results --label playwright-evidence
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/already-clean-dir \\
            --label playwright-evidence
      - name: Upload Playwright Allure results
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-allure-results
          path: frontend/allure-results/playwright
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("playwright layer privacy scan step", completed.stderr)
        self.assertIn("frontend/allure-results/playwright", completed.stderr)

    def test_workflow_rejects_aggregate_gate_weakened_with_and_false_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  allure-report:
    steps:
      - name: Require explicit privacy scan success for all layers
        if: needs.backend.outputs.privacy_scan_outcome != 'success' || needs.frontend.outputs.privacy_scan_outcome != 'success' || needs.e2e.outputs.privacy_scan_outcome != 'success' || needs.mobile.outputs.privacy_scan_outcome != 'success' && false
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py
          exit 1
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "must not be weakened with an additional '&&' condition", completed.stderr
        )
        self.assertIn("backend", completed.stderr)
        self.assertIn("mobile", completed.stderr)

    def test_workflow_rejects_playwright_layer_omitting_sibling_artifact_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  e2e:
    outputs:
      privacy_scan_outcome: ${{ steps.playwright_privacy_scan.outcome }}
    steps:
      - name: Scan Playwright Allure evidence for privacy leaks
        id: playwright_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/allure-results/playwright \\
            --label playwright-evidence
      - name: Upload Playwright Allure results
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-allure-results
          path: frontend/allure-results/playwright
      - name: Upload Playwright HTML report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-html-report
          path: frontend/playwright-report
      - name: Upload Playwright failure artifacts and Compose logs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-test-results
          path: frontend/test-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("playwright layer privacy scan step", completed.stderr)
        self.assertIn("frontend/playwright-report", completed.stderr)
        self.assertIn("frontend/test-results", completed.stderr)
        self.assertIn(
            "missing successful-scan gate for playwright Allure upload "
            "(Upload Playwright HTML report)",
            completed.stderr,
        )
        self.assertIn(
            "missing successful-scan gate for playwright Allure upload "
            "(Upload Playwright failure artifacts and Compose logs)",
            completed.stderr,
        )

    def test_workflow_rejects_privacy_scan_step_wired_under_the_wrong_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  mobile:
    outputs:
      privacy_scan_outcome: ${{ steps.mobile_privacy_scan.outcome }}
    steps:
      - name: Install mobile dependencies
        run: npm ci
  docker:
    steps:
      - name: Scan publishable mobile evidence for privacy leaks
        id: mobile_privacy_scan
        if: always()
        run: |
          python3 ../scripts/validate_mobile_privacy_evidence.py \\
            --path allure-results \\
            --label mobile-evidence
      - name: Upload mobile Allure results
        if: steps.mobile_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: mobile-allure-results
          path: mobile/allure-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mobile layer privacy scan step must set id: mobile_privacy_scan", completed.stderr)
        self.assertIn(
            "missing successful-scan gate for mobile Allure upload", completed.stderr
        )

    def test_workflow_rejects_privacy_scan_when_owning_job_is_entirely_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  docker:
    steps:
      - name: Scan publishable mobile evidence for privacy leaks
        id: mobile_privacy_scan
        if: always()
        run: |
          python3 ../scripts/validate_mobile_privacy_evidence.py \\
            --path allure-results \\
            --label mobile-evidence
      - name: Upload mobile Allure results
        if: steps.mobile_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: mobile-allure-results
          path: mobile/allure-results
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mobile layer privacy scan step must set id: mobile_privacy_scan", completed.stderr)
        self.assertIn("under the mobile job", completed.stderr)

    def test_workflow_rejects_wrong_root_scanned_for_playwright_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  e2e:
    outputs:
      privacy_scan_outcome: ${{ steps.playwright_privacy_scan.outcome }}
    steps:
      - name: Scan Playwright Allure evidence for privacy leaks
        id: playwright_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/coverage \\
            --label playwright-evidence
      - name: Upload Playwright Allure results
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-allure-results
          path: frontend/allure-results/playwright
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("playwright layer privacy scan step", completed.stderr)
        self.assertIn("frontend/allure-results/playwright", completed.stderr)

    def test_workflow_rejects_duplicate_ungated_raw_upload_of_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
name: CI
jobs:
  e2e:
    outputs:
      privacy_scan_outcome: ${{ steps.playwright_privacy_scan.outcome }}
    steps:
      - name: Scan Playwright Allure evidence for privacy leaks
        id: playwright_privacy_scan
        if: always()
        run: |
          python3 scripts/validate_mobile_privacy_evidence.py \\
            --path frontend/allure-results/playwright \\
            --path frontend/playwright-report \\
            --path frontend/test-results \\
            --label playwright-evidence
      - name: Upload Playwright Allure results
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-allure-results
          path: frontend/allure-results/playwright
      - name: Upload Playwright HTML report
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-html-report
          path: frontend/playwright-report
      - name: Upload Playwright failure artifacts and Compose logs
        if: steps.playwright_privacy_scan.outcome == 'success'
        uses: actions/upload-artifact@v4
        with:
          name: playwright-test-results
          path: frontend/test-results
      - name: Mirror Playwright HTML report to a legacy artifact name
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-html-report-legacy
          path: frontend/playwright-report
""".strip(),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("duplicate or alternate raw upload step(s)", completed.stderr)
        self.assertIn("frontend/playwright-report", completed.stderr)
        self.assertIn("Mirror Playwright HTML report to a legacy artifact name", completed.stderr)

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

    def test_workflow_rejects_unexpected_alternate_raw_upload_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            source = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
                encoding="utf-8"
            )
            workflow.write_text(
                source.replace(
                    "  allure-report:\n",
                    """      - name: Alternate raw upload
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: alternate-raw-evidence
          path: frontend/alternate-test-results

  allure-report:
""",
                    1,
                ),
                encoding="utf-8",
            )

            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unexpected raw upload step Alternate raw upload", completed.stderr)


if __name__ == "__main__":
    unittest.main()
