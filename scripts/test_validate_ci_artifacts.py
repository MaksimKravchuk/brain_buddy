import shutil
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_ci_artifacts.py"
MUTATION_EVIDENCE_SCRIPT = REPO_ROOT / "scripts" / "create_mutation_allure_evidence.py"

# Used by the inline-early-exit mutation tests below to additionally prove
# each mutation is actionlint-valid, not just structurally rejected by our own
# validator. actionlint is an external tool this repo does not vendor, so its
# absence must not fail the suite -- it only narrows coverage to the
# structural validator, and that narrowing is reported via stderr so it is
# visible in CI/test output rather than silently skipped.
ACTIONLINT_BIN = shutil.which("actionlint")


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

    def test_workflow_accepts_pr_scoped_concurrency_and_conditional_retention(self) -> None:
        # The real workflow is the only fixture guaranteed to satisfy every
        # current requirement at once (PR-scoped concurrency/retention from
        # main plus the mobile job and full ADR-0008 privacy-gate contract
        # from PR-113); a hand-rolled minimal workflow would need to grow in
        # lockstep with the privacy-gate contract to stay accepted here.
        source = self.real_ci_workflow_text()
        self.assertIn(
            "group: ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' "
            "&& github.event.pull_request.number || github.ref }}",
            source,
        )
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", source)
        self.assertIn(
            "retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}",
            source,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, source)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
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

    def write_mutated_ci_workflow(self, tmp: str, mutated_text: str) -> Path:
        workflow = Path(tmp) / ".github" / "workflows" / "ci.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(mutated_text, encoding="utf-8")
        return workflow

    def real_ci_workflow_text(self) -> str:
        return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def real_aggregate_gate_step_text(self, source: str) -> str:
        start = source.index("      - name: Require explicit privacy scan success for all layers")
        end = source.index("      - name: Download Allure results")
        return source[start:end]

    def test_workflow_rejects_aggregate_gate_moved_to_full_ci_job(self) -> None:
        # Mutation: the aggregate privacy gate step is moved out of
        # allure-report and into the downstream full-ci job, where it can no
        # longer prevent the aggregate report from being downloaded,
        # generated, uploaded, or published.
        source = self.real_ci_workflow_text()
        gate_step = self.real_aggregate_gate_step_text(source)
        mutated = source.replace(gate_step, "")
        full_ci_steps_marker = "    steps:\n      - name: Require successful CI, Docker, E2E, and Allure report"
        self.assertIn(full_ci_steps_marker, mutated)
        mutated = mutated.replace(
            full_ci_steps_marker,
            "    steps:\n" + gate_step + "      - name: Require successful CI, Docker, E2E, and Allure report",
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report publication gate on backend", completed.stderr)
        self.assertIn("aggregate Allure report publication gate on mobile", completed.stderr)

    def test_workflow_rejects_aggregate_gate_moved_after_publication_steps(self) -> None:
        # Mutation: the gate step stays inside allure-report but is moved
        # past the download/generate/upload/publish steps it is supposed to
        # protect, so it never actually stops the aggregate report from
        # being published.
        source = self.real_ci_workflow_text()
        gate_step = self.real_aggregate_gate_step_text(source)
        mutated = source.replace(gate_step, "")
        after_publish_marker = "      - name: Post PR Allure report link"
        self.assertIn(after_publish_marker, mutated)
        mutated = mutated.replace(after_publish_marker, gate_step + after_publish_marker, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "aggregate Allure report privacy gate must run before the allure-report job's "
            "download/generate/upload/publication steps",
            completed.stderr,
        )

    def test_workflow_rejects_scan_step_id_and_command_split_across_a_nameless_step(self) -> None:
        # Mutation: the step carrying `id: backend_privacy_scan` / `if:
        # always()` is turned into an inert decoy, and the real scanner
        # invocation is moved into a distinct, later nameless step (further
        # disabled here with `if: false`) instead of living in that step's
        # own body. A step-block matcher that only stops at `- name:`
        # boundaries can be walked straight through a nameless step into the
        # real command, wrongly crediting the decoy id/if as though the
        # scanner actually ran under it.
        source = self.real_ci_workflow_text()
        old = (
            "      - name: Scan backend Allure evidence for privacy leaks\n"
            "        id: backend_privacy_scan\n"
            "        if: always()\n"
            "        working-directory: .\n"
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "      - name: Scan backend Allure evidence for privacy leaks\n"
            "        id: backend_privacy_scan\n"
            "        if: always()\n"
            "        working-directory: .\n"
            "        run: echo \"scan placeholder\"\n"
            "      - if: false\n"
            "        working-directory: .\n"
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend layer privacy scan step must set id: backend_privacy_scan", completed.stderr)

    def test_workflow_rejects_scan_invocation_wrapped_in_unreachable_shell_conditional(
        self,
    ) -> None:
        # Mutation: the step keeps its correct id/if: always()/command/path
        # text verbatim, but wraps the scanner invocation in an
        # actionlint-valid `if false; then ...; fi` shell block. Bash's
        # `if` construct with a false condition and no `else` still exits 0,
        # so the step reports success without the scanner ever running —
        # a shell-level control-flow bypass the workflow YAML shape alone
        # cannot reveal.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          if false; then\n"
            "            python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "              --path backend/allure-results \\\n"
            "              --label backend-evidence\n"
            "          fi\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_aggregate_exit_one_wrapped_in_unreachable_shell_conditional(
        self,
    ) -> None:
        # Mutation: the aggregate gate step keeps its exact required
        # `needs.*.outputs.privacy_scan_outcome != 'success'` GitHub
        # expression and a lexical `exit 1` in its run script, but wraps
        # that `exit 1` in an actionlint-valid `if false; then ...; fi`
        # shell block, so the gate step exits 0 (never hard-failing) even
        # when a layer's privacy scan did not succeed.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          if false; then\n"
            "            exit 1\n"
            "          fi\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report privacy gate must hard-fail", completed.stderr)

    def test_workflow_rejects_scanner_command_and_paths_hidden_only_in_env(self) -> None:
        source = self.real_ci_workflow_text()
        old = (
            "      - name: Scan backend Allure evidence for privacy leaks\n"
            "        id: backend_privacy_scan\n"
            "        if: always()\n"
            "        working-directory: .\n"
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "      - name: Scan backend Allure evidence for privacy leaks\n"
            "        id: backend_privacy_scan\n"
            "        if: always()\n"
            "        env:\n"
            "          DECOY_SCAN: python3 scripts/validate_mobile_privacy_evidence.py --path backend/allure-results\n"
            "        run: true\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend layer privacy scan step", completed.stderr)

    def test_workflow_rejects_aggregate_predicates_hidden_in_false_function(self) -> None:
        source = self.real_ci_workflow_text()
        old_condition = (
            "        if: needs.backend.outputs.privacy_scan_outcome != 'success' || "
            "needs.frontend.outputs.privacy_scan_outcome != 'success' || "
            "needs.e2e.outputs.privacy_scan_outcome != 'success' || "
            "needs.mobile.outputs.privacy_scan_outcome != 'success'\n"
        )
        decoy_condition = (
            "        if: false && contains(\"needs.backend.outputs.privacy_scan_outcome != 'success' "
            "needs.frontend.outputs.privacy_scan_outcome != 'success' "
            "needs.e2e.outputs.privacy_scan_outcome != 'success' "
            "needs.mobile.outputs.privacy_scan_outcome != 'success'\", 'privacy')\n"
        )
        self.assertIn(old_condition, source)
        mutated = source.replace(old_condition, decoy_condition, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must not be weakened with an additional '&&' condition", completed.stderr)

    def test_workflow_rejects_aggregate_exit_one_hidden_only_in_env(self) -> None:
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        self.assertIn(old, source)
        new = (
            "        env:\n"
            "          EXIT_ONE: exit 1\n"
            "        run: echo \"privacy scan outcome recorded\"\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator("workflow", "--ci", str(workflow))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report privacy gate must hard-fail", completed.stderr)

    def test_workflow_rejects_aggregate_gate_disabled_via_if_false_env_string_decoy(self) -> None:
        # Mutation: the real gate step's `if:` is disabled (`if: false`, so
        # the step — and its `exit 1` — never actually runs), while the four
        # needs.*.outputs.privacy_scan_outcome != 'success' checks are moved
        # into an `env:` block instead of the step's own `if:` condition.
        # Line-based matching anywhere in the job text credited any line
        # containing the check text, regardless of whether it lived inside a
        # real, executable `if:` key or a step that was itself skipped.
        source = self.real_ci_workflow_text()
        gate_step = self.real_aggregate_gate_step_text(source)
        decoy_step = (
            "      - name: Require explicit privacy scan success for all layers\n"
            "        if: false\n"
            "        env:\n"
            "          BACKEND_CHECK: needs.backend.outputs.privacy_scan_outcome != 'success'\n"
            "          FRONTEND_CHECK: needs.frontend.outputs.privacy_scan_outcome != 'success'\n"
            "          PLAYWRIGHT_CHECK: needs.e2e.outputs.privacy_scan_outcome != 'success'\n"
            "          MOBILE_CHECK: needs.mobile.outputs.privacy_scan_outcome != 'success'\n"
            "        run: |\n"
            "          exit 1\n"
            "\n"
        )
        mutated = source.replace(gate_step, decoy_step, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report publication gate on backend", completed.stderr)
        self.assertIn("aggregate Allure report publication gate on frontend", completed.stderr)
        self.assertIn("aggregate Allure report publication gate on playwright", completed.stderr)
        self.assertIn("aggregate Allure report publication gate on mobile", completed.stderr)

    def test_workflow_rejects_clean_root_scan_with_required_root_only_in_trailing_comment(
        self,
    ) -> None:
        # Mutation: the scan step is retargeted at an already-clean
        # directory, and the real required --path arguments are pushed into
        # a trailing inline shell comment on the same line rather than a
        # dedicated full-line comment.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path frontend/allure-results/playwright \\\n"
            "            --path frontend/playwright-report \\\n"
            "            --path frontend/test-results \\\n"
            "            --label playwright-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path frontend/already-clean-dir \\\n"
            "            --label playwright-evidence # --path frontend/allure-results/playwright "
            "--path frontend/playwright-report --path frontend/test-results\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("playwright layer privacy scan step", completed.stderr)
        self.assertIn("frontend/allure-results/playwright", completed.stderr)

    def test_workflow_rejects_clean_root_scan_when_required_root_is_only_a_hyphenated_superset(
        self,
    ) -> None:
        # Mutation: the scan step is retargeted at an unrelated directory
        # whose name happens to start with the required root followed by a
        # hyphen (e.g. backend/allure-results-clean), which a plain `\b`
        # word-boundary check would wrongly credit as the required root.
        source = self.real_ci_workflow_text()
        old = (
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results-clean \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("backend layer privacy scan step", completed.stderr)
        self.assertIn("backend/allure-results", completed.stderr)

    def test_workflow_rejects_raw_evidence_copied_to_an_innocent_upload_path(self) -> None:
        # Mutation: raw Playwright evidence is copied/renamed to a
        # non-evidence-shaped directory name and uploaded unconditionally,
        # bypassing a path-spelling-based ("allure"/"playwright"/etc.)
        # detection heuristic entirely.
        source = self.real_ci_workflow_text()
        insertion_point = (
            "      - name: Upload Playwright failure artifacts and Compose logs\n"
            "        if: steps.playwright_privacy_scan.outcome == 'success'\n"
            "        uses: actions/upload-artifact@v4\n"
            "        with:\n"
            "          name: playwright-test-results\n"
            "          path: frontend/test-results\n"
            "          if-no-files-found: warn\n"
            "          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}\n"
        )
        self.assertIn(insertion_point, source)
        extra_steps = (
            "      - name: Stage extra evidence\n"
            "        if: always()\n"
            "        run: cp -r frontend/test-results frontend/evidence-cache\n\n"
            "      - name: Upload extra evidence\n"
            "        if: always()\n"
            "        uses: actions/upload-artifact@v4\n"
            "        with:\n"
            "          name: playwright-extra-evidence\n"
            "          path: frontend/evidence-cache\n"
            "          if-no-files-found: warn\n"
            "          retention-days: 30\n"
        )
        mutated = source.replace(insertion_point, insertion_point + extra_steps, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unexpected raw upload step Upload extra evidence", completed.stderr)
        self.assertIn("frontend/evidence-cache", completed.stderr)

    def test_workflow_rejects_scanner_invocation_suffixed_with_or_true(self) -> None:
        # Mutation: the scan step keeps its exact id/if: always()/--path
        # arguments, but the scanner invocation itself is suffixed with the
        # actionlint-valid `|| true`, so the step (and therefore
        # steps.backend_privacy_scan.outcome) reports success even when the
        # scanner actually found and reported privacy leaks.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence || true\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_scanner_invocation_followed_by_masking_statement(self) -> None:
        # Mutation: the scanner invocation itself is untouched, but a
        # trailing, unconditionally-run `true` statement is appended to the
        # same step after it. A shell without errexit (or one where a prior
        # `set +e` has disabled it) would let this later, always-succeeding
        # statement determine the step's exit status regardless of whether
        # the scanner call actually failed.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
            "          true\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_scanner_invocation_after_set_plus_e_directive(self) -> None:
        # Mutation: `set +e` is added ahead of the scanner invocation in the
        # same step, disabling bash's default errexit for the rest of the
        # script so the scanner's own non-zero exit no longer fails the step.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          set +e\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_scanner_invocation_piped_to_swallow_exit_status(self) -> None:
        # Mutation: the scanner invocation is piped into `cat`, so — absent
        # `pipefail` — the pipeline's exit status becomes `cat`'s (always 0)
        # instead of the scanner's own.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence | cat\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_scanner_invocation_backgrounded_with_ampersand(self) -> None:
        # Mutation: the scanner invocation is backgrounded, so the step
        # moves on (and can succeed) without ever waiting on — or failing
        # for — the scanner's own exit status.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence &\n"
            "          wait\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_aggregate_gate_hard_fail_suffixed_with_or_true(self) -> None:
        # Mutation: the aggregate gate step keeps its exact required
        # predicate, but its `exit 1` is suffixed with an actionlint-valid
        # `|| true`, so the gate step never actually hard-fails.
        source = self.real_ci_workflow_text()
        old = (
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        self.assertIn(old, source)
        new = (
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1 || true\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report privacy gate must hard-fail", completed.stderr)

    def test_workflow_rejects_sanitizer_invocation_wrapped_in_unreachable_shell_conditional(
        self,
    ) -> None:
        # Mutation: the sanitize step keeps its exact if: always()/--path
        # arguments verbatim, but the sanitizer invocation is wrapped in an
        # actionlint-valid `if false; then ...; fi` block, so it never
        # actually runs even though the step reports success.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          if false; then\n"
            "            python3 scripts/sanitize_privacy_evidence.py \\\n"
            "              --path backend/allure-results \\\n"
            "              --label backend-evidence\n"
            "          fi\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer must run sanitize_privacy_evidence.py", completed.stderr
        )

    def test_workflow_rejects_sanitizer_invocation_suffixed_with_or_true(self) -> None:
        # Mutation: the sanitizer invocation itself is suffixed with the
        # actionlint-valid `|| true`, so the step reports success even when
        # sanitization actually failed and left raw evidence unredacted.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence || true\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer must run sanitize_privacy_evidence.py", completed.stderr
        )

    def test_workflow_rejects_nameless_upload_artifact_step_for_raw_evidence(self) -> None:
        # Mutation: an extra actions/upload-artifact step for a raw
        # Playwright root is added without a step-level `name:` key at all,
        # bypassing a `- name:`-only step parser entirely.
        source = self.real_ci_workflow_text()
        insertion_point = (
            "      - name: Upload Playwright failure artifacts and Compose logs\n"
            "        if: steps.playwright_privacy_scan.outcome == 'success'\n"
            "        uses: actions/upload-artifact@v4\n"
            "        with:\n"
            "          name: playwright-test-results\n"
            "          path: frontend/test-results\n"
            "          if-no-files-found: warn\n"
            "          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}\n"
        )
        self.assertIn(insertion_point, source)
        extra_step = (
            "      - if: always()\n"
            "        uses: actions/upload-artifact@v4\n"
            "        with:\n"
            "          name: playwright-nameless-evidence\n"
            "          path: frontend/test-results\n"
            "          if-no-files-found: warn\n"
            "          retention-days: ${{ github.event_name == 'pull_request' && 7 || 30 }}\n"
        )
        mutated = source.replace(insertion_point, insertion_point + extra_step, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unexpected raw upload step <nameless step>", completed.stderr)
        self.assertIn("frontend/test-results", completed.stderr)

    def test_workflow_rejects_scanner_step_masked_by_exit_trap(self) -> None:
        # Mutation: the scan step keeps its exact id/if: always()/--path
        # arguments and its scanner invocation as the final statement, but
        # registers `trap 'exit 0' EXIT` first. actionlint accepts this; bash
        # runs the trap handler on every exit path (including a failing
        # scanner) and lets it force the step's final exit code to 0
        # regardless of what the scanner actually reported.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          trap 'exit 0' EXIT\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_sanitizer_step_masked_by_exit_trap(self) -> None:
        # Mutation: same EXIT-trap masking, applied to the sanitize step
        # instead of the scan step.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          trap 'exit 0' EXIT\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer must run sanitize_privacy_evidence.py", completed.stderr
        )

    def test_workflow_rejects_aggregate_gate_masked_by_exit_trap(self) -> None:
        # Mutation: the aggregate gate step keeps its exact required
        # predicate and a lexical `exit 1`, but first registers
        # `trap 'exit 0' EXIT`, which bash runs on every exit path
        # (including the explicit `exit 1`) and can force the job to report
        # success regardless.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          trap 'exit 0' EXIT\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report privacy gate must hard-fail", completed.stderr)

    def test_workflow_rejects_scanner_invocation_preceded_by_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: the scanner invocation is untouched and remains the
        # final top-level statement, but an unconditional `exit 0` is
        # inserted as an earlier top-level statement in the same run body.
        # actionlint accepts this; bash terminates the script at that
        # `exit 0` and never reaches the scanner call at all, yet the
        # current last-statement check does not notice the required command
        # is dead code.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          exit 0\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_scanner_invocation_masked_by_reachable_conditional_early_exit(
        self,
    ) -> None:
        # Mutation: the scanner invocation is untouched and remains the
        # final top-level statement, but is preceded by an
        # actionlint-valid `if true; then exit 0; fi` block. Unlike
        # `if false; then <required command>; fi` (already rejected), this
        # conditional's branch is always taken at runtime, so bash exits 0
        # before the scanner call ever executes -- yet the current control
        # flow tracker only inspects statements at depth zero and never
        # flags a masking `exit` sitting inside an (always-taken) block.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          if true; then\n"
            "            exit 0\n"
            "          fi\n"
            "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer privacy scan step must set id: backend_privacy_scan",
            completed.stderr,
        )

    def test_workflow_rejects_sanitizer_invocation_preceded_by_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: same early-`exit 0`-before-the-required-command bypass,
        # applied to the sanitize step instead of the scan step.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          exit 0\n"
            "          python3 scripts/sanitize_privacy_evidence.py \\\n"
            "            --path backend/allure-results \\\n"
            "            --label backend-evidence\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "backend layer must run sanitize_privacy_evidence.py", completed.stderr
        )

    def test_workflow_rejects_aggregate_exit_one_preceded_by_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: the aggregate gate step keeps its exact required
        # predicate and its lexical `exit 1` as the final statement, but an
        # unconditional bare `exit` is inserted right after the `echo`
        # line. Bash terminates there (propagating the `echo`'s own zero
        # exit status), so the job reports success and the real `exit 1`
        # never runs -- even though "exit 1" is still textually present in
        # the run body.
        source = self.real_ci_workflow_text()
        old = (
            "        run: |\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit 1\n"
        )
        self.assertIn(old, source)
        new = (
            "        run: |\n"
            "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
            "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
            "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
            "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
            "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
            "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
            "          exit\n"
            "          exit 1\n"
        )
        mutated = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("aggregate Allure report privacy gate must hard-fail", completed.stderr)

    def assert_actionlint_valid_if_available(self, workflow_path: Path) -> None:
        """Prove a mutation is actionlint-valid where actionlint is available.

        Structural rejection of an actionlint-valid mutation is the whole
        point of these tests -- if actionlint itself would already reject
        the mutated workflow, our validator catching it too proves nothing
        about the fail-closed gap being tested. When actionlint is not
        installed, this narrows to testing the structural validator alone
        and reports that narrowing on stderr so it stays visible instead of
        silently skipped.
        """

        if ACTIONLINT_BIN is None:
            print(
                "warning: actionlint not found on PATH; verifying only the "
                f"structural validator's rejection of {workflow_path.name}",
                file=sys.stderr,
            )
            return

        completed = subprocess.run(
            [ACTIONLINT_BIN, str(workflow_path)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "mutation must remain actionlint-valid so the structural rejection "
            f"below is meaningful: {completed.stdout}{completed.stderr}",
        )

    def assert_early_exit_mutation_rejected(
        self,
        old_run_body: str,
        inserted_line: str,
        expected_error: str,
    ) -> None:
        """Insert `inserted_line` as the run body's first statement and
        assert the mutated real workflow is both actionlint-valid (where
        actionlint is available) and rejected by the structural validator
        with `expected_error`.
        """

        source = self.real_ci_workflow_text()
        self.assertIn(old_run_body, source)
        marker = "        run: |\n"
        self.assertIn(marker, old_run_body)
        new_run_body = old_run_body.replace(marker, marker + inserted_line, 1)
        mutated = source.replace(old_run_body, new_run_body, 1)

        with tempfile.TemporaryDirectory() as tmp:
            workflow = self.write_mutated_ci_workflow(tmp, mutated)
            self.assert_actionlint_valid_if_available(workflow)
            completed = self.run_validator(
                "workflow",
                "--ci",
                str(workflow),
                "--frontend-vite-config",
                str(REPO_ROOT / "frontend" / "vite.config.ts"),
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(expected_error, completed.stderr)

    # Real run-body text for each of the three privacy-gate routes this
    # module must fail closed on, paired with the structural error each
    # mutation must still surface. Declared once and shared by every inline
    # early-exit mutation test below (both forms x all three routes).
    SCANNER_RUN_BODY = (
        "        run: |\n"
        "          python3 scripts/validate_mobile_privacy_evidence.py \\\n"
        "            --path backend/allure-results \\\n"
        "            --label backend-evidence\n"
    )
    SCANNER_EXPECTED_ERROR = "backend layer privacy scan step must set id: backend_privacy_scan"

    SANITIZER_RUN_BODY = (
        "        run: |\n"
        "          python3 scripts/sanitize_privacy_evidence.py \\\n"
        "            --path backend/allure-results \\\n"
        "            --label backend-evidence\n"
    )
    SANITIZER_EXPECTED_ERROR = "backend layer must run sanitize_privacy_evidence.py"

    AGGREGATE_RUN_BODY = (
        "        run: |\n"
        "          echo \"::error::One or more layer privacy scans did not explicitly succeed "
        "(backend=${{ needs.backend.outputs.privacy_scan_outcome }}, "
        "frontend=${{ needs.frontend.outputs.privacy_scan_outcome }}, "
        "playwright=${{ needs.e2e.outputs.privacy_scan_outcome }}, "
        "mobile=${{ needs.mobile.outputs.privacy_scan_outcome }}); refusing to download, "
        "generate, upload, or publish the aggregate Allure report (ADR-0008).\" >&2\n"
        "          exit 1\n"
    )
    AGGREGATE_EXPECTED_ERROR = "aggregate Allure report privacy gate must hard-fail"

    # The two actionlint-valid early-exit forms the structural validator
    # previously missed: a statically-always-taken inline `if`, and an
    # inline conditional bare `exit` -- both packed onto one
    # semicolon-separated physical line rather than actionlint's
    # already-covered multi-line `if ...; then\n  exit 0\nfi` shape.
    INLINE_UNCONDITIONAL_EARLY_EXIT = "          if true; then exit 0; fi\n"
    INLINE_CONDITIONAL_BARE_EARLY_EXIT = (
        '          if [ -z "${PRIVACY_SCANNER_ENABLED:-}" ]; then exit; fi\n'
    )

    def test_workflow_rejects_scanner_invocation_masked_by_inline_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: the scanner invocation is untouched and remains the
        # final top-level statement, but is preceded by an actionlint-valid,
        # single-line `if true; then exit 0; fi`. Bash takes this branch
        # unconditionally and exits 0 before the scanner call ever executes.
        # Splitting only on whole physical lines (the pre-fix behavior)
        # never detects this: `exit 0` never sits alone on its own line
        # here, it is packed onto the same line as `if true; then` and `;
        # fi`.
        self.assert_early_exit_mutation_rejected(
            self.SCANNER_RUN_BODY,
            self.INLINE_UNCONDITIONAL_EARLY_EXIT,
            self.SCANNER_EXPECTED_ERROR,
        )

    def test_workflow_rejects_scanner_invocation_masked_by_inline_conditional_bare_exit(
        self,
    ) -> None:
        # Mutation: same masking route, but the guard is a real
        # (non-statically-true) condition and the exit is bare (no explicit
        # `0`). We cannot evaluate whether `PRIVACY_SCAN_OVERRIDE` is set at
        # validation time, so this must be treated as unsafe regardless
        # (ADR-0008 fail-closed).
        self.assert_early_exit_mutation_rejected(
            self.SCANNER_RUN_BODY,
            self.INLINE_CONDITIONAL_BARE_EARLY_EXIT,
            self.SCANNER_EXPECTED_ERROR,
        )

    def test_workflow_rejects_sanitizer_invocation_masked_by_inline_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: identical inline `if true; then exit 0; fi` masking,
        # applied to the sanitize step instead of the scan step.
        self.assert_early_exit_mutation_rejected(
            self.SANITIZER_RUN_BODY,
            self.INLINE_UNCONDITIONAL_EARLY_EXIT,
            self.SANITIZER_EXPECTED_ERROR,
        )

    def test_workflow_rejects_sanitizer_invocation_masked_by_inline_conditional_bare_exit(
        self,
    ) -> None:
        # Mutation: identical inline conditional bare `exit` masking,
        # applied to the sanitize step instead of the scan step.
        self.assert_early_exit_mutation_rejected(
            self.SANITIZER_RUN_BODY,
            self.INLINE_CONDITIONAL_BARE_EARLY_EXIT,
            self.SANITIZER_EXPECTED_ERROR,
        )

    def test_workflow_rejects_aggregate_exit_one_masked_by_inline_unconditional_early_exit(
        self,
    ) -> None:
        # Mutation: the aggregate gate step keeps its exact required
        # predicate and its lexical `exit 1` as the final statement, but an
        # inline `if true; then exit 0; fi` is inserted right after the
        # `echo`, unconditionally short-circuiting the job to success before
        # the real `exit 1` ever runs.
        self.assert_early_exit_mutation_rejected(
            self.AGGREGATE_RUN_BODY,
            self.INLINE_UNCONDITIONAL_EARLY_EXIT,
            self.AGGREGATE_EXPECTED_ERROR,
        )

    def test_workflow_rejects_aggregate_exit_one_masked_by_inline_conditional_bare_exit(
        self,
    ) -> None:
        # Mutation: same aggregate route, guarded by a real
        # (non-statically-true) condition and a bare `exit` instead of
        # `exit 0`.
        self.assert_early_exit_mutation_rejected(
            self.AGGREGATE_RUN_BODY,
            self.INLINE_CONDITIONAL_BARE_EARLY_EXIT,
            self.AGGREGATE_EXPECTED_ERROR,
        )


if __name__ == "__main__":
    unittest.main()
