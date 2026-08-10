#!/usr/bin/env python3
"""Render a Stryker JSON report as a summary and a survivor list.

The mobile campaign's evidence has to be readable without opening a browser or
a 5 MB JSON file, and it has to name every survivor: ADR-0004's rule is that a
survivor is either killed by a focused test or documented as a non-behavioral
mutation, and neither is possible if nobody can see them.

Score is killed over (killed + survived): timeouts and errors say nothing about
assertion strength, and folding them in would move the number for reasons
unrelated to the tests. It is the same definition ``scripts/mutation_gate.py``
uses for the backend, so the two stacks' scores mean the same thing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KILLED_STATUSES = ("Killed", "Timeout")
SURVIVED_STATUSES = ("Survived", "NoCoverage")


def load_report(path: Path) -> dict[str, object]:
    """Read a Stryker JSON mutation report."""

    return json.loads(path.read_text(encoding="utf-8"))


def iter_mutants(report: dict[str, object]):
    """Yield ``(file_path, mutant)`` for every mutant in the report."""

    files = report.get("files") or {}
    if not isinstance(files, dict):
        return
    for file_path, entry in files.items():
        if not isinstance(entry, dict):
            continue
        for mutant in entry.get("mutants") or []:
            if isinstance(mutant, dict):
                yield file_path, mutant


def counts(report: dict[str, object]) -> dict[str, int]:
    """Count mutants by outcome bucket."""

    tally = {"killed": 0, "survived": 0, "other": 0, "total": 0}
    for _, mutant in iter_mutants(report):
        tally["total"] += 1
        status = mutant.get("status")
        if status in KILLED_STATUSES:
            tally["killed"] += 1
        elif status in SURVIVED_STATUSES:
            tally["survived"] += 1
        else:
            tally["other"] += 1
    return tally


def score(tally: dict[str, int]) -> float | None:
    """Killed over checked, or None when nothing was checked."""

    checked = tally["killed"] + tally["survived"]
    if checked == 0:
        return None
    return tally["killed"] / checked


def survivors(report: dict[str, object]) -> list[str]:
    """One line per surviving mutant: where it is and what it changed."""

    lines: list[str] = []
    for file_path, mutant in iter_mutants(report):
        if mutant.get("status") not in SURVIVED_STATUSES:
            continue
        location = (mutant.get("location") or {}).get("start") or {}
        lines.append(
            f"{file_path}:{location.get('line', '?')}:{location.get('column', '?')} "
            f"[{mutant.get('status')}] {mutant.get('mutatorName')} -> "
            f"{mutant.get('replacement', '')!r}"
        )
    return sorted(lines)


def summarize(report: dict[str, object]) -> str:
    """The human-readable summary block."""

    tally = counts(report)
    value = score(tally)
    rendered = "n/a (no mutants checked)" if value is None else f"{value:.2%}"
    return "\n".join(
        [
            "Mobile deterministic-core mutation campaign is report-only; "
            "it is not a product-test gate.",
            f"mutants: {tally['total']}",
            f"killed (incl. timeouts): {tally['killed']}",
            f"survived (incl. no coverage): {tally['survived']}",
            f"not checked (errors, ignored, compile failures): {tally['other']}",
            f"score (killed / (killed + survived)): {rendered}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--survivors", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.report.is_file():
        print(f"stryker report does not exist: {args.report}", file=sys.stderr)
        return 1

    report = load_report(args.report)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(summarize(report) + "\n", encoding="utf-8")

    found = survivors(report)
    body = "\n".join(found) if found else "No surviving mutants."
    args.survivors.parent.mkdir(parents=True, exist_ok=True)
    args.survivors.write_text(body + "\n", encoding="utf-8")

    print(summarize(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
