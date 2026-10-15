#!/usr/bin/env python3
"""Check the 027 capability dispositions against the capability inventory.

    python3 scripts/check_capability_inventory.py [--final]
        [--python-report target/conformance/python.json]
        [--rust-report target/conformance/rust.json]

Structure checks always run: every inventory id has exactly one row, each row
has a known disposition, evidence kind, slice and evidence id, and every
change/remove row names its approval and reason. ``--final`` additionally fails
on any ``pending-owner`` row (a guard for future additions; none may remain).

Reports are written by the conformance harness: a JSON object whose
``results`` is either ``{"<test name>": "passed"}`` or a list of
``{"name": ..., "status": ...}``. A test proves a row when its name equals the
row's evidence id or starts with ``<evidence id>_``. When a report is given:

* port rows need green evidence in the Python and the Rust report, and the two
  reports must not differ for the row;
* change rows need green evidence in the Rust report only;
* remove rows need green (absence) evidence in the Rust report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE = ROOT / "specs" / "027-rust-server" / "contracts"
INVENTORY = FEATURE / "capability-inventory.md"
DISPOSITIONS = FEATURE / "capability-dispositions.json"

FINAL_DISPOSITIONS = {"port", "change", "remove"}
ALL_DISPOSITIONS = FINAL_DISPOSITIONS | {"pending-owner"}
EVIDENCE_KINDS = {"conformance", "integration", "config-test", "job-test", "deploy-check"}
NEEDS_APPROVAL = {"change", "remove"}
ID_RE = re.compile(r"^CAP-[A-Z]+-\d{3}$")
SLICE_RE = re.compile(r"^PR-\d{2,3}$")


def inventory_ids(path: Path = INVENTORY) -> list[str]:
    return re.findall(r"^\| (CAP-[A-Z]+-\d+) ", path.read_text(encoding="utf-8"), re.M)


def check_rows(rows: list[dict], ids: list[str], final: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        cid = str(row.get("id", ""))
        if not ID_RE.match(cid):
            errors.append(f"bad id {cid!r}")
            continue
        if cid in seen:
            errors.append(f"{cid}: duplicate row")
        seen.add(cid)
        if cid not in ids:
            errors.append(f"{cid}: not in the inventory")
        errors.extend(_check_row(cid, row, final))
    errors.extend(f"{cid}: missing row" for cid in ids if cid not in seen)
    return errors


def _check_row(cid: str, row: dict, final: bool) -> list[str]:
    errors: list[str] = []
    disposition = row.get("disposition")
    if disposition not in ALL_DISPOSITIONS:
        errors.append(f"{cid}: unknown disposition {disposition!r}")
    elif disposition == "pending-owner" and final:
        errors.append(f"{cid}: pending-owner is not allowed with --final")
    evidence = row.get("evidence") or {}
    if evidence.get("kind") not in EVIDENCE_KINDS:
        errors.append(f"{cid}: unknown evidence kind {evidence.get('kind')!r}")
    if not evidence.get("id"):
        errors.append(f"{cid}: missing evidence id")
    if not SLICE_RE.match(str(row.get("slice", ""))):
        errors.append(f"{cid}: missing owning slice")
    if disposition in NEEDS_APPROVAL and not (row.get("approval") and row.get("reason")):
        errors.append(f"{cid}: {disposition} row needs an approval reference and reason")
    return errors


def load_report(path: Path) -> dict[str, str]:
    results = json.loads(path.read_text(encoding="utf-8")).get("results", {})
    if isinstance(results, list):
        return {str(item["name"]): str(item["status"]) for item in results}
    return {str(name): str(status) for name, status in results.items()}


def matched_tests(report: dict[str, str], evidence_id: str) -> dict[str, str]:
    """Test name -> status for every test that proves ``evidence_id``."""
    prefix = evidence_id + "_"
    return {n: s for n, s in report.items() if n == evidence_id or n.startswith(prefix)}


def evidence_status(report: dict[str, str], evidence_id: str) -> str:
    """passed when at least one test matches and all match are green."""
    matched = matched_tests(report, evidence_id)
    if not matched:
        return "missing"
    return "passed" if all(s == "passed" for s in matched.values()) else "failed"


def check_reports(
    rows: list[dict], python: dict[str, str] | None, rust: dict[str, str] | None
) -> list[str]:
    errors: list[str] = []
    if rust is None:
        errors.append("a Rust report is required (--rust-report): every row needs it")
    if python is None and any(r.get("disposition") == "port" for r in rows):
        errors.append("a Python report is required (--python-report): port rows need it")
    if errors:
        return errors
    for row in rows:
        cid, disposition = row["id"], row.get("disposition")
        evidence_id = (row.get("evidence") or {}).get("id", "")
        want = {"rust": rust}
        if disposition == "port":
            want["python"] = python
        for side, report in want.items():
            status = evidence_status(report or {}, evidence_id)
            if status != "passed":
                errors.append(f"{cid}: {side} evidence {evidence_id} is {status}")
        if disposition == "port" and matched_tests(
            python or {}, evidence_id
        ) != matched_tests(rust or {}, evidence_id):
            errors.append(f"{cid}: Python and Rust conformance reports differ")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--dispositions", type=Path, default=DISPOSITIONS)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--python-report", type=Path)
    parser.add_argument("--rust-report", type=Path)
    args = parser.parse_args(argv)

    rows = json.loads(args.dispositions.read_text(encoding="utf-8"))["rows"]
    errors = check_rows(rows, inventory_ids(args.inventory), args.final)
    if not errors and (args.python_report or args.rust_report):
        python = load_report(args.python_report) if args.python_report else None
        rust = load_report(args.rust_report) if args.rust_report else None
        errors = check_reports(rows, python, rust)
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"capability dispositions OK: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
