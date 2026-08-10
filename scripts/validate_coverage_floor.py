#!/usr/bin/env python3
"""Validate a stack's coverage against its ratchet floor.

The floor file records the coverage a stack has already achieved, as
``metric name -> fraction 0..1``. Two things are checked:

1. every measured metric is at or above its floor;
2. the floor in this branch is not lower than the floor on the base branch,
   so the floor can only ratchet upward. A missing base floor file means the
   floor is new and there is nothing to compare against.

Two report formats are understood: cobertura XML (``line-rate`` and
``branch-rate`` on the root element, as coverage.py writes for the backend)
and istanbul ``coverage-summary.json`` (a ``total`` object whose metrics each
carry a ``pct`` out of 100, as both Vitest and Jest write).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

COBERTURA = "cobertura"
ISTANBUL_SUMMARY = "istanbul-summary"

COBERTURA_METRICS = ("line", "branch")
ISTANBUL_METRICS = ("statements", "branches", "functions", "lines")


def read_cobertura(report: Path) -> dict[str, float]:
    """Read line and branch rates from a cobertura XML report."""
    root = ElementTree.parse(report).getroot()
    return {
        metric: float(root.attrib[f"{metric}-rate"]) for metric in COBERTURA_METRICS
    }


def read_istanbul_summary(report: Path) -> dict[str, float]:
    """Read the ``total`` percentages from an istanbul JSON summary."""
    total = json.loads(report.read_text(encoding="utf-8"))["total"]
    return {metric: float(total[metric]["pct"]) / 100 for metric in ISTANBUL_METRICS}


READERS = {COBERTURA: read_cobertura, ISTANBUL_SUMMARY: read_istanbul_summary}


def load_floor(floor_path: Path) -> dict[str, float]:
    """Read a floor file mapping metric names to fractions between 0 and 1."""
    payload = json.loads(floor_path.read_text(encoding="utf-8"))
    return {metric: float(value) for metric, value in payload.items()}


def check_floor(
    stack: str, actual: dict[str, float], floor: dict[str, float]
) -> list[str]:
    """Report metrics that fall below the floor, or that the report lacks."""
    failures: list[str] = []
    for metric, minimum in sorted(floor.items()):
        rate = actual.get(metric)
        if rate is None:
            failures.append(
                f"{stack} floor requires metric {metric!r}, which the coverage "
                f"report does not measure (it has: {', '.join(sorted(actual))})."
            )
        elif rate < minimum:
            failures.append(
                f"{stack} {metric} coverage {rate:.2%} is below its "
                f"{minimum:.2%} floor."
            )
    return failures


def check_ratchet(
    stack: str, floor: dict[str, float], base_floor: dict[str, float]
) -> list[str]:
    """Report floors this branch lowered or dropped relative to the base."""
    failures: list[str] = []
    for metric, base_minimum in sorted(base_floor.items()):
        minimum = floor.get(metric)
        if minimum is None:
            failures.append(
                f"{stack} {metric} floor was removed; the base branch requires "
                f"{base_minimum:.2%} and the floor may only ratchet upward."
            )
        elif minimum < base_minimum:
            failures.append(
                f"{stack} {metric} floor {minimum:.2%} is below the base branch "
                f"floor {base_minimum:.2%}; the floor may only ratchet upward."
            )
    return failures


def validate_coverage_floor(
    report: Path,
    floor_path: Path,
    *,
    stack: str,
    report_format: str,
    base_floor_path: Path | None = None,
) -> dict[str, float]:
    """Raise when ``stack`` misses its floor or lowers it below the base branch.

    Returns the measured coverage so callers can report it.
    """
    actual = READERS[report_format](report)
    floor = load_floor(floor_path)

    failures = check_floor(stack, actual, floor)
    if base_floor_path is not None and base_floor_path.exists():
        failures += check_ratchet(stack, floor, load_floor(base_floor_path))
    if failures:
        raise ValueError("\n".join(failures))
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stack", choices=("backend", "frontend", "mobile"), required=True
    )
    parser.add_argument(
        "--format", dest="report_format", choices=tuple(READERS), required=True
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--floor", type=Path, required=True)
    parser.add_argument(
        "--base-floor",
        type=Path,
        default=None,
        help="floor file from the base branch; absent means the floor is new",
    )
    args = parser.parse_args(argv)

    try:
        actual = validate_coverage_floor(
            args.report,
            args.floor,
            stack=args.stack,
            report_format=args.report_format,
            base_floor_path=args.base_floor,
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    measured = ", ".join(
        f"{metric} {rate:.2%}" for metric, rate in sorted(actual.items())
    )
    print(f"{args.stack} coverage meets its floor: {measured}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
