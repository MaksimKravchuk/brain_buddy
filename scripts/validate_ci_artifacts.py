#!/usr/bin/env python3
"""Validate CI workflow shape and Allure result artifacts.

This intentionally uses only the Python standard library so it can run before
backend or frontend dependencies are installed in GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_ARTIFACTS = {
    "backend-allure-results": "backend/allure-results",
    "frontend-allure-results": "frontend/allure-results",
    "native-product-e2e-allure-results": "frontend/allure-results/playwright",
    "allure-report-html": "allure-report",
}

MUTATION_SCOPE = (
    "app/services/tree_service.py",
    "app/services/version_service.py",
    "app/services/relation_service.py",
    "app/repositories/tree.py",
    "app/repositories/version.py",
    "app/repositories/index.py",
)

MUTATION_EVIDENCE = (
    "mutation-summary.txt",
    "mutation-survivors.txt",
    "mutation-evidence",
    "name: mutation-raw-results",
    "retention-days: 30",
)

FRONTEND_CI_REQUIREMENTS = (
    ("frontend lint step", "npm run lint"),
    ("frontend coverage test step", "npm run test:coverage"),
    ("frontend build step", "npm run build"),
)
FRONTEND_COVERAGE_THRESHOLD = 95
FRONTEND_COVERAGE_METRICS = ("statements", "branches", "functions", "lines")
NATIVE_PRODUCT_E2E_STORIES = (
    "Native task shell navigation",
    "Minimal native task management",
    "Voice Brain Dump happy path",
    "Voice Brain Dump idempotency and recovery",
    "Voice Brain Dump failure recovery",
    "Owner isolation",
)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def validate_results(path: Path, label: str) -> int:
    if not path.is_dir():
        return _fail(f"{label}: Allure results directory does not exist: {path}")

    result_files = sorted(path.glob("*-result.json"))
    non_empty = [file for file in result_files if file.is_file() and file.stat().st_size > 0]
    if not non_empty:
        return _fail(
            f"{label}: expected at least one non-empty Allure *-result.json in {path}"
        )

    print(f"{label}: found {len(non_empty)} non-empty Allure result file(s) in {path}")
    return 0


def _allure_result_payloads(path: Path) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for file in sorted(path.glob("*-result.json")):
        if not file.is_file() or file.stat().st_size == 0:
            continue
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Allure result JSON in {file}: {exc}") from exc
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _allure_label_values(payload: dict[str, object], name: str) -> set[str]:
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return set()
    values: set[str] = set()
    for label in labels:
        if not isinstance(label, dict):
            continue
        if label.get("name") == name and isinstance(label.get("value"), str):
            values.add(str(label["value"]))
    return values


def _has_meaningful_allure_step(steps: object) -> bool:
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = step.get("name")
        status = step.get("status")
        start = step.get("start")
        stop = step.get("stop")
        has_timing = isinstance(start, int) and isinstance(stop, int) and stop >= start
        if isinstance(name, str) and name.strip() and status == "passed" and has_timing:
            return True
        if _has_meaningful_allure_step(step.get("steps")):
            return True
    return False


def _has_meaningful_playwright_evidence(payload: dict[str, object]) -> bool:
    start = payload.get("start")
    stop = payload.get("stop")
    has_timing = isinstance(start, int) and isinstance(stop, int) and stop > start
    return has_timing and _has_meaningful_allure_step(payload.get("steps"))


def validate_native_product_e2e_results(path: Path) -> int:
    """Require active Playwright evidence for the native tasks/voice product suite."""

    if not path.is_dir():
        return _fail(f"native-product-e2e: Allure results directory does not exist: {path}")

    try:
        payloads = _allure_result_payloads(path)
    except ValueError as exc:
        return _fail(f"native-product-e2e: {exc}")
    if not payloads:
        return _fail(f"native-product-e2e: expected non-empty Allure result JSON in {path}")

    active = [payload for payload in payloads if payload.get("status") != "skipped"]
    if len(active) < len(NATIVE_PRODUCT_E2E_STORIES):
        return _fail(
            "native-product-e2e: expected active native product scenarios, "
            f"found {len(active)} active result(s)"
        )

    required_story_payloads: dict[str, list[dict[str, object]]] = {
        story: [] for story in NATIVE_PRODUCT_E2E_STORIES
    }
    for payload in active:
        for story in _allure_label_values(payload, "story"):
            if story in required_story_payloads:
                required_story_payloads[story].append(payload)

    failed_stories = [
        story
        for story, story_payloads in required_story_payloads.items()
        if any(payload.get("status") != "passed" for payload in story_payloads)
    ]
    if failed_stories:
        return _fail(
            "native-product-e2e: required story result(s) must pass: "
            + ", ".join(failed_stories)
        )

    missing_meaningful_evidence = [
        story
        for story, story_payloads in required_story_payloads.items()
        if story_payloads
        and not any(_has_meaningful_playwright_evidence(payload) for payload in story_payloads)
    ]
    if missing_meaningful_evidence:
        return _fail(
            "native-product-e2e: required story result(s) need meaningful Playwright evidence: "
            + ", ".join(missing_meaningful_evidence)
        )

    meaningful = [payload for payload in active if _has_meaningful_playwright_evidence(payload)]
    stories = set().union(*(_allure_label_values(payload, "story") for payload in meaningful))
    missing_stories = [story for story in NATIVE_PRODUCT_E2E_STORIES if story not in stories]
    if missing_stories:
        return _fail(
            "native-product-e2e: missing required passing Allure story label(s): "
            + ", ".join(missing_stories)
        )

    epics = set().union(*(_allure_label_values(payload, "epic") for payload in meaningful))
    features = set().union(*(_allure_label_values(payload, "feature") for payload in meaningful))
    if "BrainBuddy MVP loop" not in epics:
        return _fail("native-product-e2e: missing BrainBuddy MVP loop epic label")
    if "Native tasks and Voice Brain Dump" not in features:
        return _fail("native-product-e2e: missing Native tasks and Voice Brain Dump feature label")

    names = "\n".join(str(payload.get("name", "")) for payload in active).lower()
    if "/crt" in names or "crt" in names:
        return _fail("native-product-e2e: legacy CRT evidence cannot satisfy this suite")

    print(
        "native-product-e2e: found "
        f"{len(meaningful)} meaningful passing result(s) covering "
        f"{len(NATIVE_PRODUCT_E2E_STORIES)} required stories"
    )
    return 0


def _missing_artifact_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for name, path in REQUIRED_ARTIFACTS.items():
        if f"name: {name}" not in workflow_text:
            errors.append(f"missing required artifact {name}")
        if path not in workflow_text:
            errors.append(f"missing required artifact path {path}")
    return errors


def _missing_frontend_ci_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    if "  frontend:" not in workflow_text:
        errors.append("missing frontend CI job")
    for label, snippet in FRONTEND_CI_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet}")
    if "- frontend" not in workflow_text:
        errors.append("missing frontend job dependency in downstream CI gates")
    if "native-product-e2e:" not in workflow_text:
        errors.append("missing native product Compose E2E CI job")
    if "npm run test:e2e:compose" not in workflow_text:
        errors.append("missing native product Compose E2E test command")
    if "product-e2e-results" not in workflow_text:
        errors.append("missing native product E2E Allure validator")
    return errors


def _coverage_threshold_errors(vite_config: Path) -> list[str]:
    if not vite_config.is_file():
        return [f"frontend Vitest config does not exist: {vite_config}"]

    config_text = vite_config.read_text(encoding="utf-8")
    errors: list[str] = []
    if "thresholds" not in config_text:
        errors.append("missing frontend coverage thresholds")
    for metric in FRONTEND_COVERAGE_METRICS:
        matches = [
            int(match)
            for match in re.findall(rf"\b{metric}\s*:\s*(\d+)", config_text)
        ]
        if not matches or max(matches) < FRONTEND_COVERAGE_THRESHOLD:
            errors.append(
                f"frontend coverage threshold {metric} must be >= {FRONTEND_COVERAGE_THRESHOLD}"
            )
    return errors


def validate_workflow(
    ci: Path, disallowed_workflows: list[Path], frontend_vite_config: Path | None
) -> int:
    errors: list[str] = []
    if not ci.is_file():
        errors.append(f"CI workflow does not exist: {ci}")
        workflow_text = ""
    else:
        workflow_text = ci.read_text(encoding="utf-8")
        errors.extend(_missing_artifact_errors(workflow_text))
        errors.extend(_missing_frontend_ci_errors(workflow_text))
        if "retention-days: 30" not in workflow_text:
            errors.append("missing 30-day artifact retention")
        if "if: always()" not in workflow_text:
            errors.append("missing if: always() artifact upload guard")
        if "validate_ci_artifacts.py results" not in workflow_text:
            errors.append("missing artifact-specific Allure results validation")
        if "allure generate" not in workflow_text:
            errors.append("missing aggregate Allure report generation")

    if frontend_vite_config is not None:
        errors.extend(_coverage_threshold_errors(frontend_vite_config))

    for workflow in disallowed_workflows:
        if workflow.exists():
            errors.append(f"nested workflow must be removed: {workflow}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"workflow validation passed: {ci}")
    return 0


def validate_mutation_workflow(workflow: Path) -> int:
    """Reject a mutation workflow that can misrepresent its scope or evidence."""

    if not workflow.is_file():
        return _fail(f"mutation workflow does not exist: {workflow}")

    workflow_text = workflow.read_text(encoding="utf-8")
    errors: list[str] = []
    if "schedule:" not in workflow_text:
        errors.append("mutation workflow must include a nightly schedule")
    if "workflow_dispatch:" not in workflow_text:
        errors.append("mutation workflow must support workflow_dispatch")
    if "pull_request:" in workflow_text or "push:" in workflow_text:
        errors.append("mutation workflow must remain report-only until a blocking gate is approved")
    if "mutmut run" not in workflow_text or "mutmut results" not in workflow_text:
        errors.append("mutation workflow must run mutmut and save its results")
    for path in MUTATION_SCOPE:
        if path not in workflow_text:
            errors.append(f"mutation workflow is missing deterministic-core scope: {path}")
    for evidence in MUTATION_EVIDENCE:
        if evidence not in workflow_text:
            errors.append(f"mutation workflow is missing evidence artifact: {evidence}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"mutation workflow validation passed: {workflow}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    results = subparsers.add_parser("results", help="validate an Allure results directory")
    results.add_argument("--path", type=Path, required=True)
    results.add_argument("--label", required=True)

    product_e2e = subparsers.add_parser(
        "product-e2e-results",
        help="validate native tasks and Voice Brain Dump Playwright Allure evidence",
    )
    product_e2e.add_argument("--path", type=Path, required=True)

    workflow = subparsers.add_parser("workflow", help="validate CI workflow requirements")
    workflow.add_argument("--ci", type=Path, required=True)
    workflow.add_argument(
        "--disallow-workflow",
        type=Path,
        action="append",
        default=[],
        help="workflow path that must not exist (repeatable)",
    )
    workflow.add_argument(
        "--frontend-vite-config",
        type=Path,
        help="frontend Vite/Vitest config that must enforce coverage thresholds",
    )

    mutation_workflow = subparsers.add_parser(
        "mutation-workflow", help="validate report-only mutation workflow requirements"
    )
    mutation_workflow.add_argument("--workflow", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "results":
        return validate_results(args.path, args.label)
    if args.command == "product-e2e-results":
        return validate_native_product_e2e_results(args.path)
    if args.command == "workflow":
        return validate_workflow(args.ci, args.disallow_workflow, args.frontend_vite_config)
    if args.command == "mutation-workflow":
        return validate_mutation_workflow(args.workflow)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
