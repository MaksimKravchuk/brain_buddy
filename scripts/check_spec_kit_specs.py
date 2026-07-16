#!/usr/bin/env python3
"""Validate BrainBuddy Spec Kit feature directories.

This check is intentionally deterministic and offline. It does not regenerate
Spec Kit output; it only rejects new feature-spec directories that omit the
minimum artifacts BrainBuddy requires after adopting github/spec-kit v0.12.17.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "specs"

REQUIRED_FILES = (
    "spec.md",
    "checklists/requirements.md",
    "plan.md",
    "tasks.md",
)

GRANDFATHERED = {
    "002-async-voice-workflows": (
        "Pre-v0.12.17 adoption ADR/spec package; acceptance-tests.md is its "
        "normative checklist. Do not fabricate missing generated artifacts "
        "unless this feature is materially changed."
    ),
}

FEATURE_DIR_PATTERN = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def main() -> int:
    if not SPECS_DIR.exists():
        print("Spec Kit check failed: specs/ directory is missing", file=sys.stderr)
        return 1

    failures: list[str] = []
    grandfathered_seen: list[str] = []

    for spec_dir in sorted(path for path in SPECS_DIR.iterdir() if path.is_dir()):
        name = spec_dir.name
        if not FEATURE_DIR_PATTERN.match(name):
            failures.append(
                f"{_relative(spec_dir)}: directory name must match "
                "NNN-kebab-case-feature"
            )
            continue

        spec_file = spec_dir / "spec.md"
        if not spec_file.exists():
            failures.append(f"{_relative(spec_dir)}: missing spec.md")
            continue

        if name in GRANDFATHERED:
            grandfathered_seen.append(f"{_relative(spec_dir)} ({GRANDFATHERED[name]})")
            continue

        for required_file in REQUIRED_FILES:
            candidate = spec_dir / required_file
            if not candidate.exists():
                failures.append(f"{_relative(spec_dir)}: missing {required_file}")
            elif candidate.is_file() and candidate.stat().st_size == 0:
                failures.append(f"{_relative(candidate)}: file is empty")

    if failures:
        print("Spec Kit artifact check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        print(
            "\nNew or materially changed features must follow: constitution -> "
            "/speckit-specify -> /speckit-clarify or /speckit-checklist -> "
            "/speckit-plan -> /speckit-tasks.",
            file=sys.stderr,
        )
        return 1

    print("Spec Kit artifact check passed.")
    if grandfathered_seen:
        print("Grandfathered historical specs:")
        for entry in grandfathered_seen:
            print(f"- {entry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
