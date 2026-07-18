"""Validate backend line and branch coverage from coverage.py XML output."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.etree import ElementTree


def validate_coverage(coverage_xml: Path, *, threshold: float = 0.95) -> None:
    """Raise when either line or branch coverage falls below ``threshold``."""
    root = ElementTree.parse(coverage_xml).getroot()
    for metric in ("line", "branch"):
        rate = float(root.attrib[f"{metric}-rate"])
        if rate < threshold:
            raise ValueError(
                f"{metric} coverage {rate:.2%} is below required {threshold:.2%}."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path)
    parser.add_argument("--threshold", type=float, default=0.95)
    args = parser.parse_args()
    validate_coverage(args.coverage_xml, threshold=args.threshold)
    print(f"backend line and branch coverage meet {args.threshold:.0%} threshold")


if __name__ == "__main__":
    main()
