#!/usr/bin/env python3
"""Gate a pull request on the mutation score of the enforced scope.

ADR-0004 specified this gate and its calibration precondition; ADR-0011 split
scope into an observed tier (what the nightly campaign measures) and an enforced
tier (what may block a pull request). This script implements the enforced tier.

It runs only over the intersection of the enforced scope and the files a pull
request actually changed, so a change that touches none of them costs nothing,
and one that touches a single module does not pay for the whole campaign.

Two failure modes are treated as equally disqualifying: a score below the
threshold, and a run that checked no mutants at all. The second matters more
than it looks -- a campaign that silently mutates nothing reports a perfect
score, which is exactly how a gate comes to mean nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.95


def load_enforced_scope(path: Path) -> list[str]:
    """Read the enforced allow-list, one repository-relative path per line."""

    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    if not entries:
        raise ValueError(f"enforced scope file is empty: {path}")
    return entries


def scope_for_changes(enforced: list[str], changed: list[str]) -> list[str]:
    """The enforced files this change actually touches, in allow-list order."""

    touched = {entry.strip() for entry in changed if entry.strip()}
    return [entry for entry in enforced if entry in touched]


def mutation_score(stats: dict[str, object]) -> tuple[int, int, float]:
    """Return (killed, checked, score) from mutmut's CI/CD stats.

    ``checked`` counts only mutants with a verdict about the tests: killed plus
    survived. Skipped, timed-out and no-test mutants say nothing about assertion
    strength either way, so folding them in would move the score for reasons
    unrelated to the tests.
    """

    killed = int(stats.get("killed", 0) or 0)
    survived = int(stats.get("survived", 0) or 0)
    checked = killed + survived
    if checked == 0:
        return killed, 0, 0.0
    return killed, checked, killed / checked


def validate_stats(
    stats: dict[str, object], *, threshold: float = DEFAULT_THRESHOLD
) -> None:
    """Raise when the campaign checked nothing or scored below ``threshold``."""

    killed, checked, score = mutation_score(stats)
    if checked == 0:
        raise ValueError(
            "mutation gate checked no mutants; a campaign that mutates nothing "
            "reports a perfect score and proves nothing."
        )
    if score < threshold:
        raise ValueError(
            f"mutation score {score:.2%} ({killed}/{checked} killed) is below "
            f"the required {threshold:.2%}."
        )


def rewrite_only_mutate(pyproject: Path, scope: list[str]) -> None:
    """Narrow ``[tool.mutmut] only_mutate`` to ``scope`` in place.

    The committed list is the observed scope; the gate must measure the enforced
    subset that this change touches, and mutmut takes its scope from the config
    file rather than the command line.
    """

    if not scope:
        raise ValueError("refusing to rewrite the scope to an empty list")
    text = pyproject.read_text(encoding="utf-8")
    replacement = "only_mutate = [\n" + "".join(
        f'  "{entry}",\n' for entry in scope
    ) + "]"
    updated, count = re.subn(
        r"only_mutate = \[[^\]]*\]", replacement, text, count=1
    )
    if count != 1:
        raise ValueError(f"could not find only_mutate in {pyproject}")
    pyproject.write_text(updated, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scope = sub.add_parser("scope", help="print the enforced files a change touches")
    scope.add_argument("--enforced", type=Path, required=True)
    scope.add_argument(
        "--changed",
        type=Path,
        required=True,
        help="file holding the changed paths, one per line",
    )
    scope.add_argument(
        "--apply-to",
        type=Path,
        help="rewrite this pyproject.toml's only_mutate to the computed scope",
    )

    check = sub.add_parser("check", help="validate a mutmut CI/CD stats file")
    check.add_argument("--stats", type=Path, required=True)
    check.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    args = parser.parse_args(argv)

    if args.command == "scope":
        enforced = load_enforced_scope(args.enforced)
        changed = args.changed.read_text(encoding="utf-8").splitlines()
        selected = scope_for_changes(enforced, changed)
        for entry in selected:
            print(entry)
        if selected and args.apply_to is not None:
            rewrite_only_mutate(args.apply_to, selected)
        return 0

    if not args.stats.is_file():
        print(f"error: stats file does not exist: {args.stats}", file=sys.stderr)
        return 1
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    try:
        validate_stats(stats, threshold=args.threshold)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    killed, checked, score = mutation_score(stats)
    print(f"mutation gate passed: {score:.2%} ({killed}/{checked} mutants killed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
