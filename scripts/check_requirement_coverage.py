#!/usr/bin/env python3
"""Fail when a spec requirement has no test that names it.

The acceptance auditor builds its traceability matrix by hand. This script is
the mechanical floor underneath that judgement: it proves the *link* exists.
It does not prove the test is meaningful — a test that names FR-001 and
asserts nothing still passes here. Judging meaning is the auditor's job; this
script only guarantees the auditor is never guessing which test to read.

A requirement is covered when its **feature-qualified** id appears in a test
file: in a test function name, a docstring, an Allure `story`/`title` label, or
a `describe`/`it` string.

The qualifier is not decoration. Every feature restarts its numbering at
`FR-001`, so matching a bare id across the repository lets one feature's tests
satisfy another feature's gate — `003-smart-add-classification` would score
itself green off voice-brain-dump tests, and a genuinely untested requirement
would pass. The accepted marker is therefore the feature number joined to the
id:

    006-FR-001        # feature 006, requirement FR-001
    def test_006_FR_001_signs_the_user_in(): ...
    allure.story("006-SC-002 sign-in completes under two seconds")

Underscores are accepted in place of hyphens so Python test function names stay
idiomatic.

    python3 scripts/check_requirement_coverage.py specs/006-example
    python3 scripts/check_requirement_coverage.py specs/006-example --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Definitions look like `- **FR-001**: ...`; mentions elsewhere do not define.
DEFINITION_RE = re.compile(r"^\s*[-*]\s*\*\*((?:FR|SC)-\d+)\*\*", re.MULTILINE)
FEATURE_NUMBER_RE = re.compile(r"^(\d{3})-")

# Trees that hold nothing but tests: every file in them is evidence, whatever
# it is called. `mobile/integration/run.ts` is the case that exposed the bug —
# it was listed as a test tree and then filtered out again by the name hints
# below, so every integration assertion in the repository was invisible to this
# gate. A tree named here asserts its own contents; do not add a broad one.
DEDICATED_TEST_TREES = (
    "backend/tests",
    "frontend/tests",
    "mobile/integration",
)

# Trees that hold product code with tests mixed in, where a filename hint is
# the only way to tell them apart.
MIXED_TEST_TREES = (
    "frontend/src",
    "mobile/src",
)

TEST_TREES = DEDICATED_TEST_TREES + MIXED_TEST_TREES
TEST_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")
TEST_NAME_HINTS = ("test", "spec", "__tests__")


def iter_test_files(root: Path):
    for tree in TEST_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        dedicated = tree in DEDICATED_TEST_TREES
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in TEST_SUFFIXES:
                continue
            if dedicated:
                yield path
                continue
            lowered = str(path.relative_to(root)).lower()
            if any(hint in lowered for hint in TEST_NAME_HINTS):
                yield path


def requirements(spec_path: Path) -> list[str]:
    return sorted(set(DEFINITION_RE.findall(spec_path.read_text(encoding="utf-8"))))


def feature_number(feature_dir: Path) -> str:
    match = FEATURE_NUMBER_RE.match(feature_dir.name)
    if match is None:
        raise SystemExit(
            f"{feature_dir.name}: feature directory must be named NNN-kebab-slug"
        )
    return match.group(1)


def marker_pattern(number: str, requirement: str) -> re.Pattern[str]:
    """Match `006-FR-001`, `006_FR_001`, and the mixed forms in between.

    Hyphen and underscore are interchangeable at every separator so a Python
    test function name (`test_006_FR_001_...`) and an Allure story string
    (`006-FR-001 ...`) both satisfy the same requirement.
    """
    prefix, digits = requirement.split("-")
    # `\b` is wrong here: `_` is a word character, so `\b` never matches inside
    # `test_006_FR_001_signs_in` — the very form this is meant to accept.
    # Anchor on alphanumerics instead, which still rejects `2006-FR-001` and
    # `006-FR-0011`.
    return re.compile(
        rf"(?<![A-Za-z0-9]){number}[-_]{prefix}[-_]{digits}(?![A-Za-z0-9])"
    )


def coverage(root: Path, feature_dir: Path) -> dict[str, list[str]]:
    spec_path = feature_dir / "spec.md"
    if not spec_path.is_file():
        raise SystemExit(f"{feature_dir}: spec.md is missing")

    number = feature_number(feature_dir)
    wanted = requirements(spec_path)
    found: dict[str, list[str]] = {req: [] for req in wanted}
    if not wanted:
        return found

    patterns = {req: marker_pattern(number, req) for req in wanted}
    for path in iter_test_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for req, pattern in patterns.items():
            if pattern.search(text):
                found[req].append(str(path.relative_to(root)))

    return {req: sorted(paths) for req, paths in found.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_dir", help="path to specs/NNN-<slug>")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)

    feature_dir = Path(args.feature_dir)
    if not feature_dir.is_absolute():
        feature_dir = REPO_ROOT / feature_dir
    if not feature_dir.is_dir():
        raise SystemExit(f"{args.feature_dir}: not a directory")

    number = feature_number(feature_dir)
    result = coverage(REPO_ROOT, feature_dir)
    uncovered = sorted(req for req, paths in result.items() if not paths)

    if args.json:
        print(
            json.dumps(
                {"feature": number, "coverage": result, "uncovered": uncovered},
                indent=2,
            )
        )
    else:
        for req in sorted(result):
            paths = result[req]
            mark = "ok  " if paths else "MISS"
            detail = (
                ", ".join(paths[:3])
                if paths
                else f"no test names {number}-{req}"
            )
            more = f" (+{len(paths) - 3} more)" if len(paths) > 3 else ""
            print(f"{mark} {number}-{req}: {detail}{more}")

    if not result:
        print(
            f"{feature_dir.name}: spec.md defines no FR-###/SC-### requirements "
            "in the expected `- **FR-001**: ...` form",
            file=sys.stderr,
        )
        return 1

    if uncovered:
        qualified = ", ".join(f"{number}-{req}" for req in uncovered)
        print(
            f"\nRequirement coverage FAILED: {len(uncovered)} of {len(result)} "
            f"requirements have no test naming them: {qualified}\n"
            f"Add the feature-qualified id (e.g. {number}-{uncovered[0]}) to the "
            "test name, docstring, or Allure story so acceptance can trace it. "
            "A bare id is deliberately not accepted: every feature restarts at "
            "FR-001, so bare ids let another feature's tests satisfy this gate.",
            file=sys.stderr,
        )
        return 1

    print(f"\nRequirement coverage passed: {len(result)}/{len(result)} traced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
