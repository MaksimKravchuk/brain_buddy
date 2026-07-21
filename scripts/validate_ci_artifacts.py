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
from typing import cast

REQUIRED_ARTIFACTS = {
    "backend-allure-results": "backend/allure-results",
    "frontend-allure-results": "frontend/allure-results",
    "playwright-allure-results": "frontend/allure-results/playwright",
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
EXECUTED_ALLURE_STATUSES = {"passed", "failed", "broken"}
E2E_CI_REQUIREMENTS = (
    ("e2e CI job", "  e2e:"),
    ("Compose Playwright E2E job name", "Compose Playwright E2E"),
    ("e2e Makefile target", "make test-e2e"),
    ("Playwright Chromium install", "npx playwright install --with-deps chromium"),
    (
        "Playwright Allure validation",
        "--path frontend/allure-results/playwright --label playwright-e2e",
    ),
    ("native product E2E Allure validator", "product-e2e-results"),
)
NATIVE_PRODUCT_E2E_STORIES = (
    "Native task shell navigation",
    "Minimal native task management",
    "Voice Brain Dump happy path",
    "Voice Brain Dump idempotency and recovery",
    "Voice Brain Dump failure recovery",
    "Owner isolation",
)
MOBILE_CI_REQUIREMENTS = (
    # Fresh, unlocked `pip install` can silently resolve a newer FastAPI/
    # Pydantic than the committed OpenAPI snapshot was generated against,
    # reintroducing non-deterministic drift (see docs/api-compatibility.md).
    ("locked backend contract dependency install", "uv sync --locked --extra dev"),
    ("committed OpenAPI drift gate", "python -m scripts.openapi_snapshot check"),
    (
        "maintainable mobile privacy evidence scanner (ADR-0008)",
        "scripts/validate_mobile_privacy_evidence.py",
    ),
)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _executed_result_error(result: object) -> str | None:
    if not isinstance(result, dict):
        return "result JSON must be an object"

    status = result.get("status")
    if status not in EXECUTED_ALLURE_STATUSES:
        return f"expected an executed status, got {status!r}"

    name = result.get("name")
    if not _is_non_empty_string(name):
        return "executed scenario is missing a non-empty name"

    if not any(_is_non_empty_string(result.get(key)) for key in ("fullName", "historyId", "testCaseId")):
        return "result looks list-only: missing fullName/historyId/testCaseId"

    start = result.get("start")
    stop = result.get("stop")
    if not isinstance(start, (int, float)) or not isinstance(stop, (int, float)):
        return "executed scenario is missing start/stop timestamps"
    if stop <= start:
        return "zero executed scenario duration"

    return None


def validate_results(path: Path, label: str, since_file: Path | None = None) -> int:
    if not path.is_dir():
        return _fail(f"{label}: Allure results directory does not exist: {path}")

    since_mtime = None
    if since_file is not None:
        if not since_file.is_file():
            return _fail(f"{label}: freshness marker does not exist: {since_file}")
        since_mtime = since_file.stat().st_mtime

    result_files = sorted(path.glob("*-result.json"))
    non_empty = [file for file in result_files if file.is_file() and file.stat().st_size > 0]
    if not non_empty:
        return _fail(
            f"{label}: expected at least one non-empty Allure *-result.json in {path}"
        )

    executed_files: list[Path] = []
    invalid_errors: list[str] = []
    for file in non_empty:
        if since_mtime is not None and file.stat().st_mtime <= since_mtime:
            invalid_errors.append(f"{file.name}: stale result older than {since_file}")
            continue

        try:
            result = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            invalid_errors.append(f"{file.name}: invalid JSON: {error.msg}")
            continue

        error = _executed_result_error(result)
        if error is None:
            executed_files.append(file)
        else:
            invalid_errors.append(f"{file.name}: {error}")

    if not executed_files:
        details = "; ".join(invalid_errors[:5])
        return _fail(
            f"{label}: expected at least one fresh executed Allure scenario in {path}. {details}"
        )

    print(f"{label}: found {len(executed_files)} executed Allure result file(s) in {path}")
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
        has_timing = isinstance(start, (int, float)) and isinstance(
            stop, (int, float)
        ) and stop >= start
        if isinstance(name, str) and name.strip() and status == "passed" and has_timing:
            return True
        if _has_meaningful_allure_step(step.get("steps")):
            return True
    return False


def _has_meaningful_playwright_evidence(payload: dict[str, object]) -> bool:
    start = payload.get("start")
    stop = payload.get("stop")
    has_timing = isinstance(start, (int, float)) and isinstance(
        stop, (int, float)
    ) and stop > start
    return has_timing and _has_meaningful_allure_step(payload.get("steps"))


def validate_native_product_e2e_results(path: Path) -> int:
    """Require passing Playwright evidence for the native tasks/voice product suite."""

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


def _missing_mobile_ci_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    if "  mobile:" not in workflow_text:
        errors.append("missing mobile CI job")
    for label, snippet in MOBILE_CI_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet}")
    if "pip install -e ./backend" in workflow_text:
        errors.append(
            "mobile job must install backend contract dependencies via 'uv sync --locked', "
            "not an unlocked pip install"
        )
    return errors


def _missing_e2e_ci_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for label, snippet in E2E_CI_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet}")
    return errors


# Every raw publishable Allure layer must independently run the ADR-0008
# privacy scan against every exact root it publishes, expose the outcome as a
# job output, and gate every one of its raw uploads on that outcome — a
# workflow that only wires up one layer (e.g. mobile), or that scans the
# Playwright Allure root but leaves the raw playwright-report/test-results
# siblings unscanned, must not be accepted as covering the others.
# `scan_paths` are the exact, ordered --path arguments the scan step must
# pass for that layer (mobile's step already runs with
# `working-directory: mobile`, so its path is the mobile-relative
# "allure-results", not a repo-relative one). `uploads` are the
# (step name, artifact `path:`) pairs that must each be gated on that layer's
# scan outcome.
PRIVACY_SCAN_LAYERS: tuple[dict[str, object], ...] = (
    {
        "key": "backend",
        "job": "backend",
        "step_id": "backend_privacy_scan",
        "scan_paths": ("backend/allure-results",),
        "uploads": (("Upload backend Allure results", "backend/allure-results"),),
    },
    {
        "key": "frontend",
        "job": "frontend",
        "step_id": "frontend_privacy_scan",
        "scan_paths": ("frontend/allure-results/vitest",),
        "uploads": (("Upload frontend Allure results", "frontend/allure-results/vitest"),),
    },
    {
        "key": "playwright",
        "job": "e2e",
        "step_id": "playwright_privacy_scan",
        "scan_paths": (
            "frontend/allure-results/playwright",
            "frontend/playwright-report",
            "frontend/test-results",
        ),
        "uploads": (
            ("Upload Playwright Allure results", "frontend/allure-results/playwright"),
            ("Upload Playwright HTML report", "frontend/playwright-report"),
            ("Upload Playwright failure artifacts and Compose logs", "frontend/test-results"),
        ),
    },
    {
        "key": "mobile",
        "job": "mobile",
        "step_id": "mobile_privacy_scan",
        "scan_paths": ("allure-results",),
        "uploads": (("Upload mobile Allure results", "mobile/allure-results"),),
    },
)


def _strip_full_line_comments(text: str) -> str:
    """Blank out lines that are entirely a YAML or shell comment.

    A structural check that only verifies a required snippet appears
    *somewhere* in the workflow can be satisfied by hiding that snippet in a
    comment while the executed step actually does something else — e.g. it
    scans a different, already-clean root but leaves the expected `--path`
    sitting inert in a `#`-prefixed line nearby. Blanking comment-only lines
    before any pattern matching closes that gap without needing a full
    YAML/shell parser. Line count (and therefore reported positions) is
    preserved.
    """

    return "\n".join(
        "" if line.lstrip().startswith("#") else line for line in text.split("\n")
    )


def _job_block(workflow_text: str, job_name: str) -> str | None:
    """Return the text of one top-level job body, or None if it doesn't exist.

    Job keys are 2-space indented directly under `jobs:` (e.g. `  backend:`);
    the next job at that same indentation ends the block. Scoping the
    step/output/upload checks to this block is what prevents a
    correctly-shaped step from being credited to the wrong job — e.g. a
    `playwright_privacy_scan` step and its gated upload wired up under
    `docker` instead of `e2e`, where they never actually gate the Playwright
    job's own output or its Playwright uploads.
    """

    start_match = re.search(rf"^  {re.escape(job_name)}:[ \t]*$", workflow_text, re.MULTILINE)
    if start_match is None:
        return None
    rest = workflow_text[start_match.end():]
    next_match = re.search(r"^  [A-Za-z_][\w-]*:[ \t]*$", rest, re.MULTILINE)
    return rest[: next_match.start()] if next_match else rest


def _step_block_pattern(step_id: str, scan_paths: tuple[str, ...]) -> re.Pattern[str]:
    """Match a step block, not a document-wide substring soup.

    Requires `id: <step_id>` immediately followed by `if: always()`, and
    within that same step block (stopping at the next `- name:` step
    boundary) a call to the maintainable scanner against every one of the
    layer's exact, ordered `--path` arguments. This is what prevents one
    layer's fully-wired step from being mistaken for a different layer's
    missing one, and prevents a scan of a different (clean) root from being
    accepted just because the right `--path` string appears elsewhere in the
    block (e.g. a duplicate raw upload path only mentioned as a comment).
    """

    step_boundary = r"(?:(?!\n\s*- name:).)*?"
    path_clauses = "".join(
        step_boundary + r"--path\s+" + re.escape(path) + r"\b" for path in scan_paths
    )
    return re.compile(
        r"id:\s*" + re.escape(step_id) + r"\s*\n\s*if:\s*always\(\)"
        + step_boundary
        + r"validate_mobile_privacy_evidence\.py"
        + path_clauses,
        re.DOTALL,
    )


def _output_pattern(step_id: str) -> re.Pattern[str]:
    return re.compile(
        r"privacy_scan_outcome:\s*\$\{\{\s*steps\." + re.escape(step_id) + r"\.outcome\s*\}\}"
    )


def _upload_artifact_steps(job_text: str) -> list[tuple[str, str | None, str | None, int]]:
    """Return (name, condition, path, position) for each upload step in a job."""

    steps: list[tuple[str, str | None, str | None, int]] = []
    step_boundary = r"(?:(?!\n\s*- name:).)*"
    for match in re.finditer(
        r"-\s*name:\s*(?P<name>[^\n]+)\n(?P<body>" + step_boundary + r")(?=\n\s*- name:|\Z)",
        job_text,
        re.DOTALL,
    ):
        body = match.group("body")
        if "actions/upload-artifact" not in body:
            continue
        if_match = re.search(r"^\s*if:\s*(.+?)\s*$", body, re.MULTILINE)
        path_match = re.search(r"^\s*path:\s*(\S+)\s*$", body, re.MULTILINE)
        steps.append(
            (
                match.group("name").strip(),
                if_match.group(1) if if_match else None,
                path_match.group(1) if path_match else None,
                match.start(),
            )
        )
    return steps


def _upload_contract_errors(
    job_text: str,
    scan_position: int | None,
    label: str,
    step_id: str,
    uploads: tuple[tuple[str, str], ...],
) -> list[str]:
    """Require exact, scan-gated raw uploads after their scanner.

    Matching the step name alone leaves its `path:` mutable, while matching a
    correct scan step somewhere in the job still permits an earlier upload.
    Requiring the exact name/path/condition tuple and scanner-before-upload
    order closes both routes. Any extra upload-artifact step in one of these
    raw evidence jobs is rejected as an alternate publication path rather
    than assumed safe because its path spelling differs.
    """

    expected_condition = f"steps.{step_id}.outcome == 'success'"
    errors: list[str] = []
    steps = _upload_artifact_steps(job_text)
    for upload_name, upload_path in uploads:
        matching = [
            step
            for step in steps
            if step[0] == upload_name and step[2] == upload_path
        ]
        if len(matching) != 1 or matching[0][1] != expected_condition:
            errors.append(
                f"missing successful-scan gate for {label} Allure upload "
                f"({upload_name}): if: {expected_condition} (ADR-0008)"
            )
            continue
        if scan_position is not None and matching[0][3] < scan_position:
            errors.append(
                f"raw upload {upload_name} ({upload_path}) appears before its privacy scan "
                f"step {step_id} (ADR-0008)"
            )

        duplicate_paths = [step for step in steps if step[2] == upload_path]
        if len(duplicate_paths) > 1 and any(
            condition != expected_condition for _name, condition, _path, _position in duplicate_paths
        ):
            errors.append(
                f"duplicate or alternate raw upload step(s) publish {upload_path} without "
                f"the privacy scan gate ({expected_condition}) (ADR-0008)"
            )

    expected_uploads = set(uploads)
    for name, _condition, path, _position in steps:
        is_raw_evidence_path = path is not None and any(
            marker in path
            for marker in ("allure", "playwright", "test-results", "screenshots", "crash-artifacts")
        )
        if is_raw_evidence_path and (name, path) not in expected_uploads:
            errors.append(
                f"unexpected raw upload step {name} ({path}) bypasses the declared "
                f"privacy publication contract (ADR-0008)"
            )
    return errors


def _missing_mobile_privacy_gate_errors(workflow_text: str) -> list[str]:
    """Guard the ADR-0008 privacy scan publication contract for every layer.

    Each raw publishable Allure layer (backend, frontend Vitest, Playwright,
    mobile) must independently, within its own job: run the scanner against
    every one of its own exact publishable roots with `if: always()` under a
    unique step id, expose that step's outcome as a job output, and gate
    every one of its raw uploads on that outcome — including the Playwright
    job's raw `playwright-report`/`test-results` siblings, not just its
    Allure root. The aggregate Allure report job must additionally refuse to
    proceed unless ALL FOUR layer outputs explicitly equal 'success', with
    that condition not weakened by an extra `&&` clause — checking mobile's
    outcome alone is not sufficient (aggregate-only scanning previously left
    backend/frontend/Playwright evidence unscanned).
    """

    errors: list[str] = []
    if "validate_mobile_privacy_evidence.py" not in workflow_text:
        return errors

    workflow_text = _strip_full_line_comments(workflow_text)

    for layer in PRIVACY_SCAN_LAYERS:
        label = cast(str, layer["key"])
        step_id = cast(str, layer["step_id"])
        scan_paths = cast(tuple[str, ...], layer["scan_paths"])
        uploads = cast(tuple[tuple[str, str], ...], layer["uploads"])
        path_args = ", ".join(f"--path {path}" for path in scan_paths)

        job_name = cast(str, layer["job"])
        job_text = _job_block(workflow_text, job_name)
        if job_text is None:
            errors.append(
                f"{label} layer privacy scan step must set id: {step_id}, run with if: always(), "
                f"and call validate_mobile_privacy_evidence.py against {path_args} under the "
                f"{job_name} job so its outcome is captured even after upstream step "
                "failures (ADR-0008)"
            )
            continue

        scan_match = _step_block_pattern(step_id, scan_paths).search(job_text)
        if scan_match is None:
            errors.append(
                f"{label} layer privacy scan step must set id: {step_id}, run with if: always(), "
                f"and call validate_mobile_privacy_evidence.py against {path_args} "
                "so its outcome is captured even after upstream step failures (ADR-0008)"
            )
        if not _output_pattern(step_id).search(job_text):
            errors.append(
                f"missing {label} job output privacy_scan_outcome sourced from "
                f"steps.{step_id}.outcome (ADR-0008)"
            )
        errors.extend(
            _upload_contract_errors(
                job_text,
                scan_match.start() if scan_match is not None else None,
                label,
                step_id,
                uploads,
            )
        )

    for layer in PRIVACY_SCAN_LAYERS:
        needs_expr = f"needs.{layer['job']}.outputs.privacy_scan_outcome != 'success'"
        line = next((candidate for candidate in workflow_text.split("\n") if needs_expr in candidate), None)
        if line is None:
            errors.append(
                f"missing aggregate Allure report publication gate on {layer['key']} privacy "
                f"scan outcome: {needs_expr} (ADR-0008)"
            )
        elif "&&" in line:
            errors.append(
                f"aggregate Allure report publication gate on {layer['key']} privacy scan "
                f"outcome must not be weakened with an additional '&&' condition: {needs_expr} "
                "(ADR-0008)"
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
        errors.extend(_missing_mobile_ci_errors(workflow_text))
        errors.extend(_missing_mobile_privacy_gate_errors(workflow_text))
        errors.extend(_missing_e2e_ci_errors(workflow_text))
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
    results.add_argument(
        "--since-file",
        type=Path,
        help="optional marker file; result JSON must be newer than this run marker",
    )

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

    product_e2e_results = subparsers.add_parser(
        "product-e2e-results",
        help="validate native tasks and Voice Brain Dump Playwright evidence",
    )
    product_e2e_results.add_argument("--path", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "results":
        return validate_results(args.path, args.label, args.since_file)
    if args.command == "workflow":
        return validate_workflow(args.ci, args.disallow_workflow, args.frontend_vite_config)
    if args.command == "mutation-workflow":
        return validate_mutation_workflow(args.workflow)
    if args.command == "product-e2e-results":
        return validate_native_product_e2e_results(args.path)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
