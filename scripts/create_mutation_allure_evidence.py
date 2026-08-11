#!/usr/bin/env python3
"""Create an informational Allure result for a mutation campaign.

Evidence is written by campaigns that differ in two independent ways, and a
reader has to be able to tell them apart on both: which stack it measured
(``--scope-label``, e.g. backend or frontend) and whether the number was
allowed to block (``--mode``). The nightly is report-only and cannot fail
anything; the pull-request gate blocks. Everything stays `unknown` status
because ADR-0004 is explicit that mutation outcomes are evidence about test
strength, not user-facing product behaviour.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

#: mode -> (name stem, fullName leaf, qualifier, tag)
MODES = {
    "report-only": (
        "Mutation campaign evidence",
        "report_only_evidence",
        "report-only; not a product test",
        "report-only",
    ),
    "blocking-gate": (
        "Mutation gate evidence",
        "enforced_scope_gate",
        "blocking; the job result carries pass/fail",
        "blocking-gate",
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--survivors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scope-label",
        default=None,
        help="which campaign this evidence came from, e.g. 'frontend'; two "
        "campaigns otherwise produce indistinguishable Allure entries",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        default="report-only",
        help="whether this campaign was allowed to block; sets the name and tags",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    for evidence in (args.summary, args.survivors):
        if not evidence.is_file():
            raise SystemExit(f"evidence file does not exist: {evidence}")

    stem, leaf, qualifier, mode_tag = MODES[args.mode]
    scope = f" — {args.scope_label}" if args.scope_label else ""
    slug = f".{args.scope_label}" if args.scope_label else ""
    timestamp = int(datetime.now(UTC).timestamp() * 1000)
    result = {
        "uuid": str(uuid4()),
        "name": f"{stem}{scope} ({qualifier})",
        "fullName": f"quality.mutation{slug}.{leaf}",
        "status": "unknown",
        "stage": "finished",
        "start": timestamp,
        "stop": timestamp,
        "labels": [
            {"name": "suite", "value": "Quality evidence (not product tests)"},
            {"name": "tag", "value": "mutation-testing"},
            {"name": "tag", "value": mode_tag},
        ],
        "attachments": [
            {
                "name": "Mutation summary",
                "source": args.summary.name,
                "type": "text/plain",
            },
            {
                "name": "Mutation survivors",
                "source": args.survivors.name,
                "type": "text/plain",
            },
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
