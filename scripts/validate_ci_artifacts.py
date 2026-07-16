#!/usr/bin/env python3
"""Validate CI workflow shape and Allure result artifacts.

This intentionally uses only the Python standard library so it can run before
backend or frontend dependencies are installed in GitHub Actions.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_ARTIFACTS = {
    "backend-allure-results": "backend/allure-results",
    "frontend-allure-results": "frontend/allure-results",
    "e2e-allure-results": "frontend/allure-results/playwright",
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
    ("Playwright e2e test step", "npm run test:e2e"),
)
FRONTEND_COVERAGE_THRESHOLD = 95
FRONTEND_COVERAGE_METRICS = ("statements", "branches", "functions", "lines")


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
        if "validate_allure_taxonomy.py" not in workflow_text:
            errors.append("missing generated Allure taxonomy validation")
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
    if args.command == "workflow":
        return validate_workflow(args.ci, args.disallow_workflow, args.frontend_vite_config)
    if args.command == "mutation-workflow":
        return validate_mutation_workflow(args.workflow)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
