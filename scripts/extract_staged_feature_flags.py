#!/usr/bin/env python3
"""Extract the canonical ``BRAIN_BUDDY_FEATURE_FLAGS`` rollout from a workflow.

Reads a revision of ``.github/workflows/deploy-fly-production.yml`` on stdin and
prints the one flag string that revision stages. The deploy workflow feeds it
the PREVIOUS revision (``git show "${TESTED_SHA}^:..."``) so a rollback can
restage the rollout the restored image was released with.

That previous revision is the only trustworthy source. Reading the live app's
secrets back would report whatever the failed release already staged, and a
remembered default would be a guess that silently rots; the workflow line is
the same one that is authoritative for production in the first place.

Parsing fails closed, because the caller runs before any Fly mutation and a
wrong answer here would be applied by the rollback at its worst moment: the
uncommented text must declare the rollout exactly once literally, its value
must be non-empty, and every ``flag_name=state`` entry must be well formed with
a name that appears once. Diagnostics are positional only — no flag name, state or value is
ever printed, so a caller may mask the captured string. Uses only the standard
library so it can run before any dependencies are installed.
"""

from __future__ import annotations

import re
import sys

ASSIGNMENT = re.compile(r'BRAIN_BUDDY_FEATURE_FLAGS="([^"]*)"')

#: A shell expansion marks an assignment that re-applies an already-captured
#: value — the rollback step's ``"${PREVIOUS_FEATURE_FLAGS}"`` restore — rather
#: than declaring a rollout. Only literal declarations are candidates, so a
#: revision that interpolates its rollout has none and fails closed.
INDIRECTION = "${"


class ExtractionError(Exception):
    """A value-free diagnostic explaining why no rollout could be extracted."""


def _uncommented(text: str) -> str:
    """Drop comment lines so prose about the rollout is never mistaken for it."""

    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def extract_staged_flags(text: str) -> str:
    """Return the single staged flag string, or raise ``ExtractionError``."""

    declared = [
        value
        for value in ASSIGNMENT.findall(_uncommented(text))
        if INDIRECTION not in value
    ]
    if len(declared) != 1:
        raise ExtractionError(
            "expected exactly one literal BRAIN_BUDDY_FEATURE_FLAGS assignment, "
            f"found {len(declared)}"
        )
    staged = declared[0]
    if not staged.strip():
        raise ExtractionError("the BRAIN_BUDDY_FEATURE_FLAGS assignment is empty")

    seen: set[str] = set()
    for position, entry in enumerate(staged.split(","), start=1):
        name, separator, state = entry.strip().partition("=")
        name = name.strip()
        if not separator or not name or not state.strip():
            raise ExtractionError(
                f"entry {position} is not of the form flag_name=state"
            )
        if name in seen:
            raise ExtractionError(f"entry {position} repeats an earlier flag name")
        seen.add(name)
    return staged


def main() -> int:
    try:
        staged = extract_staged_flags(sys.stdin.read())
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(staged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
