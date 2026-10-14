"""Writes the "S3 Swift driver" section of the pilot rehearsal evidence file (spec 026, rehearsal S3).

``python3 ios/scripts/rehearsal_report.py [out_dir] [markdown_path]`` reads every
``rehearsal-s3-*.json`` record the Swift drivers (the kit's Rehearsal tests and the Mac's
MacRehearsalTests) left in ``out_dir`` (default ``$BB_REHEARSAL_OUT`` or ``/tmp``) and replaces
that one section of ``specs/026-rust-core-sync/evidence/rehearsal-<date>.md`` (created when
absent), leaving any other driver's section as it is. The records are rehearsal results, never
reference-device evidence: ``evidence/apple-pilot.md`` is not touched.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

HEADING = "## S3 Swift driver"
ROOT = Path(__file__).resolve().parents[2]


def escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def section(records: list[dict]) -> str:
    lines = [
        HEADING,
        "",
        (
            "Automated rehearsal (headless Swift driver), not reference-device "
            "evidence. Sources: "
            "`ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Rehearsal`, "
            "`macos/Tests/BrainBuddyMacTests/MacRehearsalTests.swift`."
        ),
        "",
        "| Target | Scenario | Verdict | Config | Observed | Correlation IDs | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        observed = "; ".join(f"{k}={v}" for k, v in sorted(r["observed"].items()))
        note = " ".join([r["note"]] + [f"FAILED: {f}" for f in r["failures"]]).strip()
        lines.append(
            f"| {r['target']} | {r['id']} {r['title']} | {r['verdict']} | {r['configuration']} "
            f"| {escape(observed)} | {escape(', '.join(r['correlationIDs']))} | {escape(note)} |"
        )
    return "\n".join(lines) + "\n"


def replace_section(document: str, text: str) -> str:
    lines = document.split("\n")
    if HEADING in lines:
        start = lines.index(HEADING)
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        return "\n".join(lines[:start] + text.split("\n") + lines[end:])
    if not document:
        document = (
            "# Pilot rehearsal results\n\n"
            "Automated rehearsal; not reference-device evidence.\n\n"
        )
    return document.rstrip("\n") + "\n\n" + text


def main() -> None:
    out = Path(
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BB_REHEARSAL_OUT", "/tmp")
    )
    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    target = Path(
        sys.argv[2]
        if len(sys.argv) > 2
        else ROOT / f"specs/026-rust-core-sync/evidence/rehearsal-{today}.md"
    )
    records = [
        json.loads(p.read_text()) for p in sorted(out.glob("rehearsal-s3-*.json"))
    ]
    records.sort(key=lambda r: (r["target"], r["id"], r["configuration"]))
    existing = target.read_text() if target.exists() else ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(replace_section(existing, section(records)))
    print(f"{len(records)} records -> {target}")


if __name__ == "__main__":
    main()
