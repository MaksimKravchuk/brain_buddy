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

# ADR-0004's blocking gate, once promoted, is only worth as much as its
# presence in CI. These keep the five requirements it was promoted under from
# being quietly unpicked: it must be wired, it must compute its own narrow
# scope rather than inherit the stack filter, it must compare against the base
# revision, it must keep its evidence even when it fails, and Full CI must
# depend on both of its jobs so neither can be dropped or left skipped.
MUTATION_GATE_REQUIREMENTS = (
    ("mutation gate job", "  mutation-gate:"),
    ("mutation base measurement job", "  mutation-base:"),
    ("mutation gate job name", "name: Backend mutation gate"),
    ("enforced-scope allow-list", "backend/mutation-enforced-scope.txt"),
    ("scope computed from the changed files", "mutation_gate.py scope"),
    ("verdict step", "mutation_gate.py check"),
    ("base-revision comparison", "--base-stats"),
    ("base revision checked out by sha", "ref: ${{ github.event.pull_request.base.sha }}"),
    ("blocking-gate Allure evidence", "--mode blocking-gate"),
    ("full-CI gate covers the mutation gate", "      - mutation-gate\n"),
    ("full-CI gate covers the base measurement", "      - mutation-base\n"),
)

# The frontend campaign (ADR-0013) is held to the same shape as the backend one:
# a named observed scope, a report-only run, and evidence retained whether or
# not the run scored well.
FRONTEND_MUTATION_SCOPE = (
    "src/api/client.ts",
    "src/api/account.ts",
    "src/api/auth.ts",
    "src/api/taskHooks.ts",
    "src/features/tasks/smartAdd.ts",
    "src/features/brain-dump/brainDumpNavigation.ts",
    "src/stores/authStore.ts",
    "src/utils/error.ts",
    "src/utils/telemetry.ts",
)

FRONTEND_MUTATION_EVIDENCE = (
    "npx stryker run",
    "summarize-stryker",
    "--scope-label frontend",
    "name: frontend-mutation-report",
    "name: frontend-mutation-evidence-allure-results",
)

FRONTEND_CI_REQUIREMENTS = (
    ("frontend lint step", "npm run lint"),
    ("frontend coverage test step", "npm run test:coverage"),
    ("frontend build step", "npm run build"),
    ("Playwright e2e test step", "npm run test:e2e"),
)
FRONTEND_COVERAGE_THRESHOLD = 97
FRONTEND_COVERAGE_METRICS = ("statements", "branches", "functions", "lines")

# Blanket coverage suppressions do not lower a coverage number -- they delete
# the file from the measurement entirely, which reads as "covered" in every
# report. Four frontend modules once carried one, hiding 2,385 lines from the
# floor; the floor was met while a third of the source was unmeasured. These
# patterns are rejected outright, in the same spirit as ADR-0004's rule that a
# broad mutation exclusion is not an acceptable remedy for a survivor.
BLANKET_COVERAGE_SUPPRESSIONS = (
    ("istanbul ignore file", re.compile(r"istanbul\s+ignore\s+file")),
    ("istanbul ignore start", re.compile(r"istanbul\s+ignore\s+start")),
    ("c8 ignore start", re.compile(r"c8\s+ignore\s+start")),
    ("v8 ignore file", re.compile(r"v8\s+ignore\s+file")),
    ("v8 ignore start", re.compile(r"v8\s+ignore\s+start")),
    ("node:coverage disable", re.compile(r"node:coverage\s+disable")),
)
# A narrow suppression is allowed only where it says what it is suppressing,
# so review sees a claim it can check rather than a bare pragma.
NARROW_COVERAGE_SUPPRESSION = re.compile(
    r"(?:istanbul|c8|v8)\s+ignore\s+(?:next|else|if)\b(?P<justification>.*)"
)
SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
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
# Path filtering must never be expressed as a job-level ``if``. A skipped job
# is exactly what ADR-0008 requires Full CI to treat as a failure, so the stack
# jobs always run and gate their expensive *steps* on the ``changes`` outputs
# instead. These requirements keep that shape from being "simplified" back into
# job-level conditions, which would look tidier and silently let a candidate
# land on checks that never executed.
PATH_FILTER_REQUIREMENTS = (
    ("changed-stacks job", "  changes:"),
    ("changed-stacks outputs", "backend: ${{ steps.decide.outputs.backend }}"),
    ("step-level path guard", "if: env.RUN == 'true'"),
    ("full-CI gate covers the filter job", "      - changes\n"),
)

PR_SCOPED_CANCEL_EXPRESSION = "${{ github.event_name == 'pull_request' }}"
PR_SCOPED_RETENTION_EXPRESSION = "${{ github.event_name == 'pull_request' && 7 || 30 }}"
REQUIRED_STATUS_CONTEXTS = ("Docker Images",)
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


def _concurrency_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    match = re.search(r"(?m)^concurrency:\n((?:^ {2}.+\n?)+)", workflow_text)
    if not match:
        errors.append(
            "missing top-level concurrency block that cancels superseded pull_request runs"
        )
        return errors

    block = match.group(1)
    if "github.event.pull_request.number" not in block or "pull_request" not in block:
        errors.append(
            "concurrency group must be scoped per pull request number so unrelated runs "
            "are never grouped together"
        )
    if f"cancel-in-progress: {PR_SCOPED_CANCEL_EXPRESSION}" not in block:
        errors.append(
            "cancel-in-progress must cancel only pull_request runs: expected exactly "
            f"cancel-in-progress: {PR_SCOPED_CANCEL_EXPRESSION}"
        )
    return errors


def _retention_errors(workflow_text: str) -> list[str]:
    retention_values = [value.strip() for value in re.findall(r"retention-days:\s*(.+)", workflow_text)]
    if not retention_values:
        return ["missing artifact retention configuration"]

    non_conforming = sorted({value for value in retention_values if value != PR_SCOPED_RETENTION_EXPRESSION})
    if non_conforming:
        return [
            "all artifact retention-days must use the PR-scoped expression "
            f"{PR_SCOPED_RETENTION_EXPRESSION} (7 days on pull_request, 30 on push/main); "
            f"found non-conforming value(s): {non_conforming}"
        ]
    return []


def _status_context_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for context in REQUIRED_STATUS_CONTEXTS:
        if f"name: {context}" not in workflow_text:
            errors.append(f"missing required {context} status context job name: {context}")
    return errors


def _mutation_gate_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for label, snippet in MUTATION_GATE_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet!r}")
    return errors


def _path_filter_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for label, snippet in PATH_FILTER_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet!r}")
    for job in ("backend", "frontend", "mobile", "docker", "mutation-base", "mutation-gate"):
        block = _job_block(workflow_text, job)
        if block is None:
            errors.append(f"missing {job} job")
        elif re.search(r"^    if:", block, flags=re.MULTILINE):
            errors.append(
                f"{job} job uses a job-level 'if'; path filtering must gate "
                "steps so the job still reports success rather than skipped"
            )
    return errors


def _job_block(workflow_text: str, job: str) -> str | None:
    """Return the text of one top-level job, excluding the next job's header."""

    match = re.search(
        rf"^  {re.escape(job)}:$(?P<body>.*?)(?=^  [a-z0-9-]+:$|\Z)",
        workflow_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else None


def _missing_e2e_ci_errors(workflow_text: str) -> list[str]:
    errors: list[str] = []
    for label, snippet in E2E_CI_REQUIREMENTS:
        if snippet not in workflow_text:
            errors.append(f"missing {label}: {snippet}")
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
        errors.extend(_missing_e2e_ci_errors(workflow_text))
        errors.extend(_path_filter_errors(workflow_text))
        errors.extend(_mutation_gate_errors(workflow_text))
        errors.extend(_concurrency_errors(workflow_text))
        errors.extend(_retention_errors(workflow_text))
        errors.extend(_status_context_errors(workflow_text))
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
        # The blocking gate lives in ci.yml over the narrower ENFORCED tier
        # (ADR-0011). This nightly measures the OBSERVED tier, which still
        # contains modules under calibration, so it must stay report-only
        # permanently rather than "for now".
        errors.append("mutation workflow measures the observed tier and must stay report-only")
    if "mutmut run" not in workflow_text or "mutmut results" not in workflow_text:
        errors.append("mutation workflow must run mutmut and save its results")
    for path in MUTATION_SCOPE:
        if path not in workflow_text:
            errors.append(f"mutation workflow is missing deterministic-core scope: {path}")
    for evidence in MUTATION_EVIDENCE:
        if evidence not in workflow_text:
            errors.append(f"mutation workflow is missing evidence artifact: {evidence}")

    if "  frontend-observed-mutation:" not in workflow_text:
        errors.append("mutation workflow is missing the frontend observed-scope job")
    for path in FRONTEND_MUTATION_SCOPE:
        if path not in workflow_text:
            errors.append(f"mutation workflow is missing frontend observed scope: {path}")
    for evidence in FRONTEND_MUTATION_EVIDENCE:
        if evidence not in workflow_text:
            errors.append(
                f"mutation workflow is missing frontend evidence artifact: {evidence}"
            )

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"mutation workflow validation passed: {workflow}")
    return 0


PREVIEW_LABEL = "preview:visual"
PREVIEW_CONCURRENCY_GROUP = (
    "preview-${{ github.repository_id }}-${{ github.event.pull_request.number }}"
)
PRODUCTION_APP_NAMES = ("brain-buddy-frontend", "brain-buddy-backend")
PREVIEW_TRIGGER_TYPES = (
    "opened",
    "synchronize",
    "reopened",
    "labeled",
    "unlabeled",
    "closed",
)


def validate_preview_workflow(workflow: Path) -> int:
    """Fail closed unless the Fly preview workflow matches ADR-0003's label-gated policy."""

    if not workflow.is_file():
        return _fail(f"preview workflow does not exist: {workflow}")

    workflow_text = workflow.read_text(encoding="utf-8")
    errors: list[str] = []

    if PREVIEW_LABEL not in workflow_text:
        errors.append(
            f"missing explicit {PREVIEW_LABEL} label trigger; paths or events alone must "
            "never authorize a deploy"
        )
    for trigger in PREVIEW_TRIGGER_TYPES:
        if trigger not in workflow_text:
            errors.append(f"missing pull_request trigger type: {trigger}")

    if PREVIEW_CONCURRENCY_GROUP not in workflow_text:
        errors.append(f"missing per-PR concurrency group {PREVIEW_CONCURRENCY_GROUP}")
    if "cancel-in-progress: true" not in workflow_text:
        errors.append(
            "missing cancel-in-progress: true for the per-PR preview concurrency group"
        )

    if "fork" not in workflow_text.lower():
        errors.append("missing same-repository/fork guard before any secret-bearing mutation")

    for app_name in PRODUCTION_APP_NAMES:
        if app_name not in workflow_text:
            errors.append(f"missing hard exclusion of production app target: {app_name}")

    if "secrets.FLY_PREVIEW_API_TOKEN" not in workflow_text:
        errors.append(
            "deploy and cleanup must use a preview-only credential "
            "(secrets.FLY_PREVIEW_API_TOKEN), not the production Fly token"
        )

    if "CURRENT_HEAD_SHA" not in workflow_text:
        errors.append(
            "missing immediate pre-mutation head sha re-verification against the event head sha"
        )

    if "smoke" not in workflow_text.lower():
        errors.append("missing smoke verification step for the deployed preview")

    if "|| true" in workflow_text:
        errors.append("cleanup/destroy must never be masked with an unconditional `|| true`")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"preview-workflow validation passed: {workflow}")
    return 0


def validate_mutation_scope(config: Path, enforced: Path) -> int:
    """Require the enforced mutation tier to be a subset of the observed one.

    An enforced file the nightly campaign does not mutate would be gated on a
    number nothing produces, and a path that no longer exists would silently
    shrink the scope. Both fail here rather than in a pull request.
    """

    errors: list[str] = []
    if not config.is_file():
        return _fail(f"mutation-scope: Stryker config does not exist: {config}")
    if not enforced.is_file():
        return _fail(f"mutation-scope: enforced scope file does not exist: {enforced}")

    try:
        observed = json.loads(config.read_text(encoding="utf-8")).get("mutate")
    except json.JSONDecodeError as exc:
        return _fail(f"mutation-scope: invalid Stryker config JSON: {exc}")
    if not isinstance(observed, list) or not observed:
        return _fail(f"mutation-scope: {config} declares no observed 'mutate' scope")

    enforced_paths = [
        line.split("#", 1)[0].strip()
        for line in enforced.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    ]
    if not enforced_paths:
        return _fail(f"mutation-scope: {enforced} lists no files")

    root = config.parent
    for path in enforced_paths:
        if path not in observed:
            errors.append(
                f"enforced scope {path} is not in the observed scope of {config}; "
                "the nightly campaign would never measure it"
            )
        if not (root / path).is_file():
            errors.append(f"enforced scope {path} does not exist under {root}")
    for path in observed:
        if not (root / str(path)).is_file():
            errors.append(f"observed scope {path} does not exist under {root}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"mutation-scope: {len(enforced_paths)} enforced file(s) within "
        f"{len(observed)} observed file(s)"
    )
    return 0


def _coverage_suppression_errors(path: Path) -> list[str]:
    """Report blanket coverage suppressions and unjustified narrow ones."""

    errors: list[str] = []
    for source in sorted(path.rglob("*")):
        if source.suffix not in SOURCE_SUFFIXES or not source.is_file():
            continue
        for number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for label, pattern in BLANKET_COVERAGE_SUPPRESSIONS:
                if pattern.search(line):
                    errors.append(
                        f"{source}:{number}: blanket coverage suppression "
                        f"({label}); cover the code or delete it -- a whole file "
                        "excluded from the report reads as covered."
                    )
            narrow = NARROW_COVERAGE_SUPPRESSION.search(line)
            if narrow and "--" not in narrow.group("justification"):
                errors.append(
                    f"{source}:{number}: coverage suppression without a "
                    "justification; write `ignore next -- why this cannot be "
                    "exercised`."
                )
    return errors


def validate_coverage_suppressions(paths: list[Path]) -> int:
    """Fail when source hides itself from the coverage report."""

    errors: list[str] = []
    for path in paths:
        if not path.is_dir():
            return _fail(f"coverage-suppressions: source directory does not exist: {path}")
        errors.extend(_coverage_suppression_errors(path))

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    scanned = ", ".join(str(path) for path in paths)
    print(f"coverage-suppressions: no blanket coverage exclusions in {scanned}")
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

    preview_workflow = subparsers.add_parser(
        "preview-workflow",
        help="validate the ADR-0003 label-gated Fly preview workflow",
    )
    preview_workflow.add_argument("--workflow", type=Path, required=True)

    mutation_scope = subparsers.add_parser(
        "mutation-scope",
        help="require the enforced mutation tier to sit inside the observed one",
    )
    mutation_scope.add_argument("--config", type=Path, required=True)
    mutation_scope.add_argument("--enforced", type=Path, required=True)

    coverage_suppressions = subparsers.add_parser(
        "coverage-suppressions",
        help="reject source that excludes itself from the coverage report",
    )
    coverage_suppressions.add_argument(
        "--path",
        type=Path,
        action="append",
        required=True,
        help="source directory to scan (repeatable)",
    )

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
    if args.command == "preview-workflow":
        return validate_preview_workflow(args.workflow)
    if args.command == "mutation-scope":
        return validate_mutation_scope(args.config, args.enforced)
    if args.command == "coverage-suppressions":
        return validate_coverage_suppressions(args.path)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
