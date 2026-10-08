#!/usr/bin/env python3
"""Measure a slice branch against its declared PR-срезы v2 budget.

A slice implementer runs this before opening the slice PR:

    python3 scripts/check_slice_budget.py specs/NNN-slug/tasks.md PR-03

It diffs ``HEAD`` against ``--base`` (default ``origin/main``), counts changed
lines and files of *product* code, and exits 1 when either exceeds the slice's
``budget`` without an ``oversize_reason``. Tests, docs, specs and lockfiles do
not count: the budget limits what a reviewer has to reason about, and those
are not where review effort goes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath

NON_PRODUCT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)__tests__/"),
    re.compile(r"(^|/)[^/]*Tests/"),
    re.compile(r"(^|/)test_[^/]*\.py$"),
    re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$"),
    re.compile(r"^(docs|specs)/"),
    re.compile(r"\.md$"),
    re.compile(r"(^|/)(package-lock\.json|uv\.lock|Package\.resolved)$"),
    re.compile(r"\.snap$"),
)


def is_product_path(path: str) -> bool:
    posix = PurePosixPath(path).as_posix()
    return not any(pattern.search(posix) for pattern in NON_PRODUCT_PATTERNS)


def load_slice(tasks_text: str, slice_id: str) -> dict[str, object]:
    section = re.search(r"(?ms)^## PR-срезы[ \t]*\n(.*?)(?=^## |\Z)", tasks_text)
    if section is None:
        raise ValueError("tasks.md has no PR-срезы section")
    fenced = re.search(r"(?ms)^```json[ \t]*\n(.*?)\n```", section.group(1))
    if fenced is None:
        raise ValueError("PR-срезы section has no fenced JSON map")
    payload = json.loads(fenced.group(1))
    for item in payload.get("slices", []):
        if isinstance(item, dict) and item.get("id") == slice_id:
            return item
    raise ValueError(f"{slice_id} is not in the slice map")


def product_changes(numstat: str) -> tuple[int, int]:
    """Return (changed product lines, changed product files) from numstat."""
    lines = files = 0
    for row in numstat.splitlines():
        parts = row.split("\t")
        if len(parts) != 3 or not is_product_path(parts[2]):
            continue
        added, deleted = parts[0], parts[1]
        files += 1
        if added != "-":  # binary files count as a file, not as lines
            lines += int(added) + int(deleted)
    return lines, files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", help="path to specs/NNN-slug/tasks.md")
    parser.add_argument("slice_id", help="slice id, e.g. PR-03")
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)

    try:
        with open(args.tasks, encoding="utf-8") as handle:
            item = load_slice(handle.read(), args.slice_id)
    except (OSError, ValueError) as exc:
        print(f"slice budget: {exc}", file=sys.stderr)
        return 2
    budget = item.get("budget")
    if not isinstance(budget, dict):
        print(f"slice budget: {args.slice_id} declares no budget (v1 map?)", file=sys.stderr)
        return 2

    numstat = subprocess.run(
        ["git", "diff", "--numstat", "--no-renames", f"{args.base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lines, files = product_changes(numstat)
    print(
        f"{args.slice_id}: {lines}/{budget.get('product_loc')} product lines, "
        f"{files}/{budget.get('files')} product files"
    )
    over = lines > int(budget.get("product_loc", 0)) or files > int(budget.get("files", 0))
    if over and not str(item.get("oversize_reason", "")).strip():
        print(
            "slice budget exceeded: split the slice, or amend the approved map "
            "with an oversize_reason",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
