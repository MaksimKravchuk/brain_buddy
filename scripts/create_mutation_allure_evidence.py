#!/usr/bin/env python3
"""Create an informational Allure result for a mutation campaign.

Two campaigns produce evidence and they must not be confused for each other:
the nightly is report-only and cannot fail anything, while the pull-request
gate blocks. Both stay `unknown` status because ADR-0004 is explicit that
mutation outcomes are evidence about test strength, not user-facing product
behaviour -- but the name and tags have to say which campaign wrote the file,
or a reader cannot tell whether the number was allowed to block.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MODES = {
    "report-only": (
        "Mutation campaign evidence (report-only; not a product test)",
        "quality.mutation.report_only_evidence",
        "report-only",
    ),
    "blocking-gate": (
        "Mutation gate evidence (blocking; the job result carries pass/fail)",
        "quality.mutation.enforced_scope_gate",
        "blocking-gate",
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--survivors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        default="report-only",
        help="which campaign wrote this evidence; sets the name and tags",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    for evidence in (args.summary, args.survivors):
        if not evidence.is_file():
            raise SystemExit(f"evidence file does not exist: {evidence}")

    name, full_name, mode_tag = MODES[args.mode]
    timestamp = int(datetime.now(UTC).timestamp() * 1000)
    result = {
        "uuid": str(uuid4()),
        "name": name,
        "fullName": full_name,
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
