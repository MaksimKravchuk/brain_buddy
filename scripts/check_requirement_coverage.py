#!/usr/bin/env python3
"""Fail when a spec requirement has no test that names it.

The acceptance auditor builds its traceability matrix by hand. This script is
the mechanical floor underneath that judgement: it proves the *link* exists.
It does not prove the test is meaningful — a test that names FR-001 and
asserts nothing still passes here. Judging meaning is the auditor's job; this
script only guarantees the auditor is never guessing which test to read.

A requirement is covered when its id appears in a test file: in a test
function name, a docstring, an Allure `story`/`title` label, or a `describe`/
`it` string. Naming the requirement in the test is the convention that makes
delivered work traceable at all.

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

TEST_TREES = (
    "backend/tests",
    "frontend/src",
    "frontend/tests",
    "mobile/src",
    "mobile/integration",
)
TEST_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")
TEST_NAME_HINTS = ("test", "spec", "__tests__")


def iter_test_files(root: Path):
    for tree in TEST_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in TEST_SUFFIXES:
                continue
            lowered = str(path.relative_to(root)).lower()
            if any(hint in lowered for hint in TEST_NAME_HINTS):
                yield path


def requirements(spec_path: Path) -> list[str]:
    return sorted(set(DEFINITION_RE.findall(spec_path.read_text(encoding="utf-8"))))


def coverage(root: Path, feature_dir: Path) -> dict[str, list[str]]:
    spec_path = feature_dir / "spec.md"
    if not spec_path.is_file():
        raise SystemExit(f"{feature_dir}: spec.md is missing")

    wanted = requirements(spec_path)
    found: dict[str, list[str]] = {req: [] for req in wanted}
    if not wanted:
        return found

    pattern = re.compile("|".join(re.escape(req) for req in wanted))
    for path in iter_test_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for req in set(pattern.findall(text)):
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

    result = coverage(REPO_ROOT, feature_dir)
    uncovered = sorted(req for req, paths in result.items() if not paths)

    if args.json:
        print(json.dumps({"coverage": result, "uncovered": uncovered}, indent=2))
    else:
        for req in sorted(result):
            paths = result[req]
            mark = "ok  " if paths else "MISS"
            detail = ", ".join(paths[:3]) if paths else "no test names this id"
            more = f" (+{len(paths) - 3} more)" if len(paths) > 3 else ""
            print(f"{mark} {req}: {detail}{more}")

    if not result:
        print(
            f"{feature_dir.name}: spec.md defines no FR-###/SC-### requirements "
            "in the expected `- **FR-001**: ...` form",
            file=sys.stderr,
        )
        return 1

    if uncovered:
        print(
            f"\nRequirement coverage FAILED: {len(uncovered)} of {len(result)} "
            f"requirements have no test naming them: {', '.join(uncovered)}\n"
            "Add the id to the test name, docstring, or Allure story so "
            "acceptance can trace it.",
            file=sys.stderr,
        )
        return 1

    print(f"\nRequirement coverage passed: {len(result)}/{len(result)} traced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
