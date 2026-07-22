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


def _strip_comments(text: str) -> str:
    """Blank out YAML/shell comments, both full-line and inline trailing.

    A structural check that only verifies a required snippet appears
    *somewhere* in the workflow can be satisfied by hiding that snippet in a
    comment while the executed step actually does something else — e.g. it
    scans a different, already-clean root but leaves the expected `--path`
    sitting inert in a `#`-prefixed line nearby, or even trailing on the same
    line as the real (different) command. Blanking every comment, not just
    full-line ones, before any pattern matching closes both gaps without
    needing a full YAML/shell parser. A `#` only starts a comment when it is
    unquoted and preceded by whitespace or the start of the line, so this
    does not clip `${var#pattern}`-style shell substitutions or `#`
    characters inside quoted strings. Line count (and therefore reported
    positions) is preserved.
    """

    stripped_lines = []
    for line in text.split("\n"):
        in_single = False
        in_double = False
        cut = None
        for index, char in enumerate(line):
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "#" and not in_single and not in_double:
                if index == 0 or line[index - 1].isspace():
                    cut = index
                    break
        stripped_lines.append(line[:cut] if cut is not None else line)
    return "\n".join(stripped_lines)


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


def _scan_step_position(job_text: str, step_id: str, scan_paths: tuple[str, ...]) -> int | None:
    """Return the start offset of the layer's privacy scan step, or None if absent.

    A step qualifies only if, within ONE step body as parsed by
    `_split_job_steps`, it carries `id: <step_id>`, runs with `if: always()`,
    and calls the maintainable scanner against every one of the layer's
    exact, ordered `--path` arguments. Matching id/if and the scanner
    invocation independently against the whole job text (rather than one
    step's own body, bounded the same way every other step-scoped check in
    this module is) let a named decoy step's `id: <step_id>` / `if:
    always()` be satisfied by a scanner call that actually lives in a later,
    distinct step — including a nameless or `if: false`/skipped one that
    never runs with that id or guard at all. Each path must not be
    immediately followed by another word character or hyphen, not just a
    `\b` word boundary: a hyphen is itself a non-word character, so `\b`
    alone would let `--path backend/allure-results-clean` (an unrelated,
    already-clean directory) satisfy a required `backend/allure-results`
    argument as a same-boundary prefix match.
    """

    for start, body in _split_job_steps(job_text):
        if not re.search(r"^\s*id:\s*" + re.escape(step_id) + r"\s*$", body, re.MULTILINE):
            continue
        if not re.search(r"^\s*if:\s*always\(\)\s*$", body, re.MULTILINE):
            continue
        run_body = _step_run_body(body)
        if run_body is None or not _has_scanner_invocation(run_body):
            continue
        if all(
            re.search(r"--path\s+" + re.escape(path) + r"(?![\w-])", run_body)
            for path in scan_paths
        ):
            return start
    return None


def _sanitize_step_position(job_text: str, scan_paths: tuple[str, ...]) -> int | None:
    """Return the start offset of the layer's sanitize step, or None if absent.

    A step qualifies only if it runs with `if: always()` and calls
    `sanitize_privacy_evidence.py` against every one of the layer's exact
    scan paths — mirroring the privacy scan's own exact-path requirement, so
    a sanitize call scoped to a different (or partial) root cannot be
    credited as covering this layer. Generated evidence carries real
    credential/email/absolute-path/audio-transcript/task-content leaks by
    default; this step must exist and run before the privacy scan step so
    that scan can actually pass on freshly generated evidence instead of
    perpetually failing closed (ADR-0008).
    """

    for start, body in _split_job_steps(job_text):
        run_body = _step_run_body(body)
        if run_body is None or not _has_sanitizer_invocation(run_body):
            continue
        if not re.search(r"^\s*if:\s*always\(\)\s*$", body, re.MULTILINE):
            continue
        if all(
            re.search(r"--path\s+" + re.escape(path) + r"(?![\w-])", run_body)
            for path in scan_paths
        ):
            return start
    return None


def _output_pattern(step_id: str) -> re.Pattern[str]:
    return re.compile(
        r"privacy_scan_outcome:\s*\$\{\{\s*steps\." + re.escape(step_id) + r"\.outcome\s*\}\}"
    )


def _split_job_steps(job_text: str) -> list[tuple[int, str]]:
    """Return (start_offset, step_text) for every top-level step in a job body.

    A step boundary is a line whose leading whitespace matches the first
    `- ` in the job's `steps:` list — not specifically `- name:`. Parsing only
    `- name:`-prefixed steps is what let a nameless step (`- if: always()`
    with `uses:`/`with:` on following lines, and no step-level `name:` at
    all) hide an `actions/upload-artifact` step from the upload contract
    checks entirely, since it was never even recognized as a step. Restricting
    parsing to the `steps:` list prevents unrelated job-level lists such as
    `needs:` from being mistaken for steps; matching on indentation then stops
    at nested `with:`/`env:` mapping keys, which sit deeper than the step's
    own `- ` marker.
    """

    steps_match = re.search(r"^[ \t]*steps:[ \t]*$", job_text, re.MULTILINE)
    if steps_match is None:
        return []
    steps_text = job_text[steps_match.end() :]
    starts = [
        match
        for match in re.finditer(r"^([ \t]*)-[ \t]", steps_text, re.MULTILINE)
    ]
    if not starts:
        return []
    indent = starts[0].group(1)
    boundaries = [match for match in starts if match.group(1) == indent]
    steps: list[tuple[int, str]] = []
    for index, match in enumerate(boundaries):
        start = match.start()
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(steps_text)
        steps.append((steps_match.end() + start, steps_text[start:end]))
    return steps


def _step_if_condition(body: str) -> str | None:
    """Return a step body's own `if:` key value, or None if it has none."""

    match = re.search(r"^\s*if:\s*(.+?)\s*$", body, re.MULTILINE)
    return match.group(1) if match else None


def _step_run_body(body: str) -> str | None:
    """Return only a step's executable ``run:`` value, never nested ``env:`` text."""

    lines = body.splitlines()
    if not lines:
        return None
    step_match = re.match(r"^([ \t]*)-[ \t]", lines[0])
    if step_match is None:
        return None
    property_indent = step_match.group(1) + "  "
    run_match = re.search(
        rf"^{re.escape(property_indent)}run:\s*(.*?)\s*$", body, re.MULTILINE
    )
    if run_match is None:
        return None
    value = run_match.group(1)
    if value not in {"|", "|-", "|+", ">", ">-", ">+"}:
        return value

    run_lines: list[str] = []
    for line in body[run_match.end() :].splitlines():
        if line and len(line) - len(line.lstrip(" \t")) <= len(property_indent):
            break
        run_lines.append(line)
    return "\n".join(run_lines)


_SHELL_BLOCK_OPENERS = {"if", "for", "while", "until", "case"}
_SHELL_BLOCK_CLOSERS = {"fi", "done", "esac"}


def _join_shell_line_continuations(run_body: str) -> list[str]:
    """Collapse ``\\``-continued shell lines into single logical lines.

    A required command such as the scanner invocation is conventionally
    spread across several backslash-continued physical lines (one flag per
    line); collapsing them first lets `_shell_top_level_statements` see one
    logical shell statement instead of a fragment of it.
    """

    logical_lines: list[str] = []
    buffer = ""
    for line in run_body.split("\n"):
        stripped = line.rstrip()
        if stripped.endswith("\\") and not stripped.endswith("\\\\"):
            buffer += stripped[:-1] + " "
            continue
        buffer += line
        logical_lines.append(buffer)
        buffer = ""
    if buffer:
        logical_lines.append(buffer)
    return logical_lines


def _shell_top_level_statements(run_body: str) -> list[str]:
    """Return a step's shell statements that are not nested in control flow.

    actionlint only validates workflow/YAML shape, not whether a `run:`
    script's own shell control flow ever reaches a given line — a command
    wrapped in e.g. ``if false; then <command>; fi`` is syntactically valid
    and still lets the step exit 0 without the wrapped command ever
    running. Tracking if/for/while/until/case openers against their
    fi/done/esac closers per logical statement (semicolon- and
    newline-separated, after joining backslash continuations) and only
    trusting statements seen while that depth is zero is what stops a step
    being credited for a required command it never actually executes.
    """

    statements: list[str] = []
    depth = 0
    for logical_line in _join_shell_line_continuations(run_body):
        for segment in logical_line.split(";"):
            statement = segment.strip()
            if not statement:
                continue
            word = statement.split(None, 1)[0]
            if word in _SHELL_BLOCK_CLOSERS:
                depth = max(0, depth - 1)
                continue
            if depth == 0:
                statements.append(statement)
            if word in _SHELL_BLOCK_OPENERS:
                depth += 1
    return statements


_ERROR_SUPPRESSION_DIRECTIVE_RE = re.compile(
    r"(?m)^\s*set\s+(?:[a-zA-Z]*\+e\b|.*\+o\s+errexit\b)"
)


def _run_body_has_error_suppression_directive(run_body: str) -> bool:
    """Return True if the script disables bash's default errexit anywhere.

    `set +e` (or `set +o errexit`) does not itself touch the required
    command's own text, so no per-statement check can see it: it silently
    changes whether a *later* failing command still stops the script. If it
    appears anywhere in the run body we cannot trust any statement in that
    body to be fail-closed, regardless of where the directive sits relative
    to the required command.
    """

    return bool(_ERROR_SUPPRESSION_DIRECTIVE_RE.search(run_body))


_EXIT_TRAP_DIRECTIVE_RE = re.compile(r"(?m)^\s*trap\b.*\b(?:EXIT|0)\s*$")


def _run_body_has_exit_trap_directive(run_body: str) -> bool:
    """Return True if the script registers an EXIT (or numeric-0) trap.

    A `trap ... EXIT` (bash also accepts the POSIX pseudo-signal number `0`
    for the same hook) always runs when the shell exits, regardless of the
    exit code of the step's own commands, and can force success (e.g.
    `trap 'exit 0' EXIT`) no matter what the required scanner/sanitizer/
    hard-fail command actually reported. We cannot evaluate what a trap
    handler does, so any EXIT trap registration anywhere in the run body is
    treated as unsafe (ADR-0008 fail-closed) — this mirrors the `set +e`
    check above, which is unsafe for the identical reason: it changes
    whether a later command's own exit status can still stop the script.
    """

    return bool(_EXIT_TRAP_DIRECTIVE_RE.search(run_body))


_EARLY_SUCCESS_EXIT_RE = re.compile(r"(?m)^\s*exit(?:\s+0)?\s*$")


def _run_body_has_early_success_exit(run_body: str) -> bool:
    """Return True if the script contains a bare `exit` or explicit `exit 0`.

    An unconditional `exit` (implicitly propagating the previous command's
    own exit status) or explicit `exit 0`, placed ahead of the required
    scanner/sanitizer/hard-fail command, ends the script successfully
    before that command ever runs — whether it sits at the run body's top
    level or is nested inside an actionlint-valid `if`/`for`/`while`/`case`
    block whose condition is statically always taken (e.g.
    `if true; then exit 0; fi`), which `_shell_top_level_statements`
    deliberately does not surface as a top-level statement at all. We
    cannot verify shell control-flow reachability with a regex, so any such
    statement anywhere in the run body — nested or not — is treated as an
    unsafe early-success bypass (ADR-0008 fail-closed).
    """

    return bool(_EARLY_SUCCESS_EXIT_RE.search(run_body))


def _statement_has_disallowed_shell_wrapping(statement: str) -> bool:
    """Return True if a statement is anything but a single trivial command.

    A regex anchored with ``^`` only proves the statement *starts with* the
    required command — it says nothing about what follows. That gap is what
    let a scanner invocation suffixed with the actionlint-valid `` || true ``
    be credited as "the scanner ran successfully" even though `` || true ``
    makes the statement's exit status always 0 regardless of the scanner's
    own result. Scanning the full statement, quote-aware, for any shell
    metacharacter that can chain another command, swallow an exit status, or
    otherwise change what "this statement failed" means — `` && ``, `` || ``,
    a pipe, backgrounding with `` & ``, subshell/grouping/function
    parentheses, command substitution, backticks, or a leading `` ! ``
    negation — closes it without needing to model shell semantics at all:
    only a bare, unwrapped command is ever accepted.
    """

    in_single = False
    in_double = False
    for index, char in enumerate(statement):
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char in "|&();`":
            return True
        if char == "!" and (index == 0 or statement[index - 1].isspace()):
            return True
    return False


def _has_required_top_level_command(run_body: str, pattern: re.Pattern[str]) -> bool:
    """Return True only if the pattern matches an unwrapped, final statement.

    Requiring the match to be the run body's last top-level statement closes
    a related masking route: an unconditionally-run trailing statement (e.g.
    a bare ``true``) added after a correctly-invoked command would, without
    bash's default `` -e ``, decide the step's exit status instead of the
    required command — so a workflow author (or shell) that doesn't rely on
    that default can still silently neutralize a failing scan or sanitize
    call. Refusing to credit anything but the final statement removes the
    need to reason about shell-specific errexit behavior at all.
    """

    if _run_body_has_error_suppression_directive(run_body):
        return False
    if _run_body_has_exit_trap_directive(run_body):
        return False
    if _run_body_has_early_success_exit(run_body):
        return False

    statements = _shell_top_level_statements(run_body)
    if not statements:
        return False

    last_statement = statements[-1]
    return bool(pattern.match(last_statement)) and not _statement_has_disallowed_shell_wrapping(
        last_statement
    )


def _has_scanner_invocation(run_body: str) -> bool:
    pattern = re.compile(
        r"^python(?:3)?\s+(?:\.\./)?scripts/"
        r"validate_mobile_privacy_evidence\.py(?:\s|$)"
    )
    return _has_required_top_level_command(run_body, pattern)


def _has_sanitizer_invocation(run_body: str) -> bool:
    pattern = re.compile(
        r"^python(?:3)?\s+(?:\.\./)?scripts/"
        r"sanitize_privacy_evidence\.py(?:\s|$)"
    )
    return _has_required_top_level_command(run_body, pattern)


def _upload_artifact_steps(job_text: str) -> list[tuple[str | None, str | None, str | None, int]]:
    """Return (name, condition, path, position) for each upload step in a job.

    `name` is the step's own display name (its top-level `name:` key, found
    before any nested `with:` mapping so the artifact's own `with: name:`
    value is never mistaken for it) and is `None` for a nameless step.
    """

    steps: list[tuple[str | None, str | None, str | None, int]] = []
    for start, body in _split_job_steps(job_text):
        if "actions/upload-artifact" not in body:
            continue
        top_part = re.split(r"^[ \t]*with:[ \t]*$", body, maxsplit=1, flags=re.MULTILINE)[0]
        name_match = re.search(r"^[ \t]*-?[ \t]*name:[ \t]*(.+?)[ \t]*$", top_part, re.MULTILINE)
        path_match = re.search(r"^\s*path:\s*(\S+)\s*$", body, re.MULTILINE)
        steps.append(
            (
                name_match.group(1).strip() if name_match else None,
                _step_if_condition(body),
                path_match.group(1) if path_match else None,
                start,
            )
        )
    return steps


# Non-evidence upload-artifact steps that legitimately coexist with the
# privacy-gated evidence uploads in an evidence-producing job (e.g. code
# coverage reports, which are not capture/attachment evidence and are not
# in scope for the ADR-0008 scan). Every other upload-artifact step in one
# of these jobs must be one of its PRIVACY_SCAN_LAYERS `uploads` entries.
_NON_EVIDENCE_UPLOADS: dict[str, tuple[tuple[str, str], ...]] = {
    "backend": (("Upload coverage artifact", "backend/coverage.xml"),),
    "frontend": (("Upload coverage artifact", "frontend/coverage/lcov.info"),),
    "e2e": (),
    "mobile": (),
}


def _upload_contract_errors(
    job_text: str,
    scan_position: int | None,
    label: str,
    step_id: str,
    job_name: str,
    uploads: tuple[tuple[str, str], ...],
) -> list[str]:
    """Require exact, scan-gated raw uploads after their scanner.

    Matching the step name alone leaves its `path:` mutable, while matching a
    correct scan step somewhere in the job still permits an earlier upload.
    Requiring the exact name/path/condition tuple and scanner-before-upload
    order closes both routes. Any extra upload-artifact step in one of these
    raw evidence jobs is rejected as an alternate publication path rather
    than assumed safe — including a step that copies/renames the raw
    evidence to an innocent-looking path first (an evidence-shaped-path
    heuristic would miss the rename) and a nameless step (`- if:
    always()` / `- uses: ...` with no step-level `name:`), which is why the
    allowlist check below matches on the exact (name, path) tuple rather
    than guessing from path spelling.
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

    allowlist = set(uploads) | set(_NON_EVIDENCE_UPLOADS.get(job_name, ()))
    for name, _condition, path, _position in steps:
        if name is None or path is None or (name, path) not in allowlist:
            display_name = name if name is not None else "<nameless step>"
            errors.append(
                f"unexpected raw upload step {display_name} ({path}) bypasses the declared "
                f"privacy publication contract (ADR-0008)"
            )
    return errors


def _missing_mobile_privacy_gate_errors(workflow_text: str) -> list[str]:
    """Guard the ADR-0008 privacy scan publication contract for every layer.

    Each raw publishable Allure layer (backend, frontend Vitest, Playwright,
    mobile) must independently, within its own job: run
    sanitize_privacy_evidence.py against every one of its own exact
    publishable roots with `if: always()` before its privacy scan step (so
    freshly generated evidence — which routinely carries real
    credential/email/absolute-path/audio-transcript/task-content leaks — is
    redacted in place instead of perpetually failing the scan), then run the
    scanner against those same roots with `if: always()` under a unique step
    id, expose that step's outcome as a job output, and gate every one of its
    raw uploads on that outcome — including the Playwright
    job's raw `playwright-report`/`test-results` siblings, not just its
    Allure root. The aggregate Allure report job must additionally refuse to
    proceed unless ALL FOUR layer outputs explicitly equal 'success', with
    that condition not weakened by an extra `&&` clause — checking mobile's
    outcome alone is not sufficient (aggregate-only scanning previously left
    backend/frontend/Playwright evidence unscanned). That gate must also live
    inside the allure-report job itself (not, say, the downstream full-ci
    job, where it can no longer prevent the aggregate report from being
    downloaded/generated/uploaded/published) and must run — and hard-fail —
    before every one of that job's aggregate download/generate/upload/
    publication steps, not after them.
    """

    errors: list[str] = []
    if "validate_mobile_privacy_evidence.py" not in workflow_text:
        return errors

    workflow_text = _strip_comments(workflow_text)

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

        scan_pos = _scan_step_position(job_text, step_id, scan_paths)
        if scan_pos is None:
            errors.append(
                f"{label} layer privacy scan step must set id: {step_id}, run with if: always(), "
                f"and call validate_mobile_privacy_evidence.py against {path_args} "
                "so its outcome is captured even after upstream step failures (ADR-0008)"
            )

        sanitize_pos = _sanitize_step_position(job_text, scan_paths)
        if sanitize_pos is None:
            errors.append(
                f"{label} layer must run sanitize_privacy_evidence.py against {path_args} "
                "with if: always() before its privacy scan step, so freshly generated "
                "evidence is redacted rather than perpetually failing the scan (ADR-0008)"
            )
        elif scan_pos is not None and sanitize_pos > scan_pos:
            errors.append(
                f"{label} layer sanitize_privacy_evidence.py step must run before its "
                "privacy scan step, not after it (ADR-0008)"
            )

        if not _output_pattern(step_id).search(job_text):
            errors.append(
                f"missing {label} job output privacy_scan_outcome sourced from "
                f"steps.{step_id}.outcome (ADR-0008)"
            )
        errors.extend(
            _upload_contract_errors(
                job_text,
                scan_pos,
                label,
                step_id,
                job_name,
                uploads,
            )
        )

    # Scoped to the allure-report job itself: a needs-condition living
    # anywhere else in the document (e.g. moved to the downstream full-ci
    # job) can no longer prevent that job's own download/generate/upload/
    # publication steps from running, so it must not be credited here.
    report_job_text = _job_block(workflow_text, "allure-report") or ""
    # The earliest position of any aggregate download/generate/upload/
    # publication step in that job — the gate must run (and hard-fail)
    # before all of them, not merely exist somewhere in the same job.
    publication_positions = [
        pos
        for pos in (
            report_job_text.find("actions/download-artifact"),
            report_job_text.find("allure generate"),
            report_job_text.find("actions/upload-artifact"),
            report_job_text.find("actions/github-script"),
        )
        if pos != -1
    ]
    earliest_publication_pos = min(publication_positions) if publication_positions else None

    needs_exprs = {
        cast(str, layer["key"]): f"needs.{layer['job']}.outputs.privacy_scan_outcome != 'success'"
        for layer in PRIVACY_SCAN_LAYERS
    }

    # The gate must be ONE actual step (per _split_job_steps, the same
    # step-boundary rule every other check in this module uses) whose own
    # `if:` key structurally contains all four checks. Scoping to a single
    # step's real `if:` value — not any line anywhere in the job text — is
    # what rejects an `if: false`/skipped step whose body merely mentions the
    # check strings, and an `env:`-string decoy where the actual `if:` is
    # harmless (e.g. `always()` or `false`) and the checks sit unused in a
    # variable instead of gating anything.
    gate_step: tuple[int, str, str] | None = None
    invalid_gate_condition: str | None = None
    for start, body in _split_job_steps(report_job_text):
        condition = _step_if_condition(body)
        if condition is None or not all(expr in condition for expr in needs_exprs.values()):
            continue
        if _is_exact_aggregate_gate_condition(condition, tuple(needs_exprs.values())):
            gate_step = (start, condition, body)
            break
        invalid_gate_condition = condition

    if gate_step is None and invalid_gate_condition is not None:
        if "&&" in invalid_gate_condition:
            for layer_key, needs_expr in needs_exprs.items():
                errors.append(
                    f"aggregate Allure report publication gate on {layer_key} privacy scan "
                    f"outcome must not be weakened with an additional '&&' condition: {needs_expr} "
                    "(ADR-0008)"
                )
        else:
            errors.append(
                "aggregate Allure report publication gate must use exactly the four required "
                "privacy-scan outcome comparisons joined by '||', not predicate text inside a "
                "function, string, or other non-gating expression (ADR-0008)"
            )
    elif gate_step is None:
        covered_layers: set[str] = set()
        for _start, body in _split_job_steps(report_job_text):
            condition = _step_if_condition(body)
            if condition is None:
                continue
            covered_layers.update(
                key for key, expr in needs_exprs.items() if expr in condition
            )
        for layer_key, needs_expr in needs_exprs.items():
            if layer_key in covered_layers:
                continue
            errors.append(
                f"missing aggregate Allure report publication gate on {layer_key} privacy "
                f"scan outcome: {needs_expr}, evaluated inside the allure-report job before its "
                "download/generate/upload/publication steps (ADR-0008)"
            )
    else:
        gate_pos, condition, step_body = gate_step
        if earliest_publication_pos is not None and gate_pos > earliest_publication_pos:
            errors.append(
                "aggregate Allure report privacy gate must run before the allure-report job's "
                "download/generate/upload/publication steps, not after them (ADR-0008)"
            )
        run_body = _step_run_body(step_body)
        has_required_exit_one = run_body is not None and any(
            re.fullmatch(r"exit\s+1", statement)
            for statement in _shell_top_level_statements(run_body)
        )
        if (
            run_body is None
            or not has_required_exit_one
            or _run_body_has_exit_trap_directive(run_body)
            or _run_body_has_early_success_exit(run_body)
        ):
            errors.append(
                "aggregate Allure report privacy gate must hard-fail the job (e.g. exit 1) "
                "when a layer privacy scan outcome is not explicitly 'success', not merely "
                "record it (ADR-0008)"
            )

    return errors


def _is_exact_aggregate_gate_condition(
    condition: str, required_expressions: tuple[str, ...]
) -> bool:
    """Accept only the four-way OR predicate that can select the hard-fail step."""

    terms = tuple(term.strip() for term in condition.split("||"))
    return len(terms) == len(required_expressions) and set(terms) == set(required_expressions)


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
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
