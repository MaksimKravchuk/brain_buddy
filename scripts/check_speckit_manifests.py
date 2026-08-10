#!/usr/bin/env python3
"""Guard the Spec Kit files BrainBuddy deliberately diverges from upstream.

`docs/spec-kit-workflow.md` documents `specify integration upgrade <agent>
--force` as the refresh path. That command overwrites installed assets with
the pinned upstream release, which silently reverts every BrainBuddy override
it touches. Nothing verified those files afterwards, so a refresh could quietly
undo a policy decision — most consequentially the implement-directly policy,
which three other authorities depend on.

Each protected file carries a marker string that exists only in the BrainBuddy
version. Upstream content cannot contain it, so a reverted file fails here
immediately and loudly.

Run via `make check-specs`, or directly:

    python3 scripts/check_speckit_manifests.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# path -> (why it diverges, marker that only the BrainBuddy version contains)
PRESERVED_OVERRIDES: dict[str, tuple[str, str]] = {
    ".claude/skills/speckit-implement/SKILL.md": (
        "Implements directly from tasks.md instead of refusing and routing to "
        "Hermes; upstream has neither policy.",
        "preserved BrainBuddy override",
    ),
    ".agents/skills/speckit-implement/SKILL.md": (
        "Codex twin of the implement-directly policy.",
        "preserved BrainBuddy override",
    ),
    ".specify/templates/spec-template.md": (
        "Adds consent/local-first and mobile-first callouts required by the "
        "constitution.",
        "BrainBuddy specs must also call out",
    ),
    ".specify/templates/plan-template.md": (
        "Carries the real repository source tree and the Constitution Check, "
        "including the requirement that the plan cite design.md.",
        "BrainBuddy override: real repository layout",
    ),
    ".specify/templates/tasks-template.md": (
        "Groups tasks by independently testable user story with real file "
        "paths and BrainBuddy delivery gates.",
        "BrainBuddy override: delivery gates",
    ),
    ".specify/templates/checklist-template.md": (
        "Encodes the BrainBuddy constitution gates.",
        "BrainBuddy constitution gates",
    ),
}


def project_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / ".specify").is_dir():
        raise SystemExit("Run from an initialized BrainBuddy Spec Kit worktree")
    return root


def check(root: Path) -> list[str]:
    failures: list[str] = []
    for relative, (reason, marker) in sorted(PRESERVED_OVERRIDES.items()):
        path = root / relative
        if not path.is_file():
            failures.append(f"{relative}: MISSING. {reason}")
            continue
        if marker not in path.read_text(encoding="utf-8"):
            failures.append(
                f"{relative}: lost its override marker {marker!r}. This is what a "
                f"`specify integration upgrade --force` reversion looks like. "
                f"{reason} Restore the override before merging."
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the protected files and exit",
    )
    args = parser.parse_args(argv)
    root = project_root()

    if args.list:
        for relative, (reason, marker) in sorted(PRESERVED_OVERRIDES.items()):
            print(f"{relative}\n  reason: {reason}\n  marker: {marker!r}")
        return 0

    failures = check(root)
    if failures:
        print("Spec Kit preserved-override check FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"Spec Kit preserved overrides intact ({len(PRESERVED_OVERRIDES)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
