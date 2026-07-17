#!/usr/bin/env python3
"""Fail CI when generated Allure results miss required taxonomy.

The BrainBuddy quality contract requires that *every* emitted automated test
result (backend pytest, frontend Vitest, Playwright e2e) carries meaningful,
test-specific Allure metadata:

* a non-empty ``epic`` label,
* a non-empty ``feature`` label,
* a non-empty ``story`` label,
* a human-readable ``title`` (the Allure result ``name``), and
* at least one named step.

This validator reads the generated ``*-result.json`` files directly so the gate
cannot be faked by tagging the source without actually emitting the metadata.
It intentionally uses only the Python standard library so it can run in GitHub
Actions before backend or frontend dependencies are installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_LABELS = ("epic", "feature", "story")

# A "human-readable" title must not be a raw framework identifier. pytest emits
# the bare ``test_snake_case`` function name unless a title is supplied, and the
# Allure ``fullName`` (``module#test_case``) is a technical id, never a title.
_RAW_PYTEST_NAME = re.compile(r"^test[_A-Z0-9]")
_PLACEHOLDER_STEP_NAME = re.compile(r"^(Verify|Scenario|Action):\s+", re.IGNORECASE)
_PLAYWRIGHT_HOOK_STEP_NAME = re.compile(r"^(Before Hooks|After Hooks)$")
_PLAYWRIGHT_FIXTURE_STEP_NAME = re.compile(r'^Fixture ".+"$')


def _iter_result_files(path: Path) -> list[Path]:
    # Recurse so a single parent directory (e.g. ``frontend/allure-results``)
    # validates every layer's subdirectory (``vitest``, ``playwright``) together.
    return sorted(p for p in path.rglob("*-result.json") if p.is_file())


def _label_values(result: dict) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for label in result.get("labels", []) or []:
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        value = label.get("value")
        if isinstance(name, str):
            values.setdefault(name, []).append(value if isinstance(value, str) else "")
    return values


def _title_errors(result: dict) -> list[str]:
    title = result.get("name")
    if not isinstance(title, str) or not title.strip():
        return ["missing human-readable title (empty result name)"]
    if _RAW_PYTEST_NAME.match(title.strip()):
        return [
            f"title is a raw framework identifier, not human-readable: {title!r}"
        ]
    full_name = result.get("fullName")
    if isinstance(full_name, str) and title.strip() == full_name.strip():
        return [f"title duplicates the technical fullName: {title!r}"]
    return []


def _label_errors(result: dict) -> list[str]:
    errors: list[str] = []
    values = _label_values(result)
    for required in REQUIRED_LABELS:
        present = [value for value in values.get(required, []) if value.strip()]
        if not present:
            errors.append(f"missing non-empty {required} label")
    return errors


def _step_errors(result: dict) -> list[str]:
    steps = result.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["missing at least one step"]
    errors: list[str] = []
    meaningful_steps = 0
    for path, step in _walk_steps(steps):
        name = step.get("name") if isinstance(step, dict) else None
        if not isinstance(name, str) or not name.strip():
            errors.append(f"step {path} has an empty name")
            continue
        if _is_fixture_or_hook_scaffolding_step(step):
            continue
        if _is_zero_duration_childless_step_without_evidence(step):
            if _is_placeholder_step_name(name):
                errors.append(f"step {path} is an empty placeholder: {name!r}")
            else:
                errors.append(
                    f"step {path} is a zero-duration no-op without evidence: {name!r}"
                )
            continue
        meaningful_steps += 1
    if meaningful_steps == 0:
        errors.append("missing at least one meaningful step")
    if errors:
        return errors
    return []


def _walk_steps(steps: list, prefix: str = "") -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for index, step in enumerate(steps):
        path = f"{prefix}.{index}" if prefix else f"#{index}"
        if not isinstance(step, dict):
            found.append((path, {}))
            continue
        found.append((path, step))
        child_steps = step.get("steps")
        if isinstance(child_steps, list) and child_steps:
            found.extend(_walk_steps(child_steps, path))
    return found


def _is_placeholder_step_name(name: str) -> bool:
    return bool(_PLACEHOLDER_STEP_NAME.match(name.strip()))


def _is_zero_duration_childless_step_without_evidence(step: dict) -> bool:
    start = step.get("start")
    stop = step.get("stop")
    has_zero_duration = isinstance(start, int) and isinstance(stop, int) and start == stop
    if not has_zero_duration:
        return False
    for evidence_key in ("steps", "attachments", "parameters"):
        evidence = step.get(evidence_key)
        if isinstance(evidence, list) and evidence:
            return False
    return True


def _is_fixture_or_hook_scaffolding_step(step: dict) -> bool:
    """Return True for Playwright fixture/hook wrapper steps.

    Playwright's Allure reporter emits scaffolding containers such as
    ``Before Hooks`` and ``Fixture "allureTaxonomy"`` around test execution.
    Those wrappers are useful chronology, but they are not product actions,
    assertions, or evidence by themselves. Child steps are walked separately, so
    a real action/assertion nested under a hook still satisfies the taxonomy.
    """

    name = step.get("name")
    if not isinstance(name, str):
        return False
    stripped = name.strip()
    return bool(
        _PLAYWRIGHT_HOOK_STEP_NAME.match(stripped)
        or _PLAYWRIGHT_FIXTURE_STEP_NAME.match(stripped)
    )


def _result_errors(result: dict) -> list[str]:
    errors: list[str] = []
    errors.extend(_title_errors(result))
    errors.extend(_label_errors(result))
    errors.extend(_step_errors(result))
    return errors


def validate(paths: list[Path], label: str) -> int:
    for path in paths:
        if not path.is_dir():
            print(
                f"error: {label}: Allure results directory does not exist: {path}",
                file=sys.stderr,
            )
            return 1

    result_files: list[Path] = []
    for path in paths:
        result_files.extend(_iter_result_files(path))
    if not result_files:
        searched = ", ".join(str(path) for path in paths)
        print(
            f"error: {label}: no Allure *-result.json files found in {searched}",
            file=sys.stderr,
        )
        return 1

    failures = 0
    for result_file in result_files:
        raw = result_file.read_text(encoding="utf-8").strip()
        if not raw:
            failures += 1
            print(f"error: {label}: {result_file.name}: empty result file", file=sys.stderr)
            continue
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures += 1
            print(
                f"error: {label}: {result_file.name}: invalid JSON ({exc})",
                file=sys.stderr,
            )
            continue
        if not isinstance(result, dict):
            failures += 1
            print(
                f"error: {label}: {result_file.name}: result is not a JSON object",
                file=sys.stderr,
            )
            continue

        errors = _result_errors(result)
        if errors:
            failures += 1
            display = result.get("name") or result.get("fullName") or result_file.name
            for error in errors:
                print(
                    f"error: {label}: {result_file.name} [{display}]: {error}",
                    file=sys.stderr,
                )

    if failures:
        print(
            f"error: {label}: {failures} of {len(result_files)} Allure result(s) "
            "missing required taxonomy (epic/feature/story/title/steps)",
            file=sys.stderr,
        )
        return 1

    searched = ", ".join(str(path) for path in paths)
    print(
        f"{label}: taxonomy OK for {len(result_files)} Allure result file(s) "
        f"in {searched}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        action="append",
        help="Allure results dir (repeatable; scanned recursively)",
    )
    parser.add_argument("--label", required=True, help="layer label for messages")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return validate(args.path, args.label)


if __name__ == "__main__":
    raise SystemExit(main())
