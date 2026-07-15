#!/usr/bin/env python3
"""Create an informational Allure result for a report-only mutation campaign."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--survivors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    for evidence in (args.summary, args.survivors):
        if not evidence.is_file():
            raise SystemExit(f"evidence file does not exist: {evidence}")

    timestamp = int(datetime.now(UTC).timestamp() * 1000)
    result = {
        "uuid": str(uuid4()),
        "name": "Mutation campaign evidence (report-only; not a product test)",
        "fullName": "quality.mutation.report_only_evidence",
        "status": "unknown",
        "stage": "finished",
        "start": timestamp,
        "stop": timestamp,
        "labels": [
            {"name": "suite", "value": "Quality evidence (not product tests)"},
            {"name": "tag", "value": "mutation-testing"},
            {"name": "tag", "value": "report-only"},
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
