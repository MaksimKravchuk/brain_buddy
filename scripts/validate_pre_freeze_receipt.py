#!/usr/bin/env python3
"""Fail-closed admission check for a writer-owned pre-freeze receipt."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

CONTRACT = "brainbuddy.pre-freeze-writer-receipt/v1"
GATE_IDS = frozenset(
    {
        "writer.tests",
        "writer.verify_all",
        "writer.path_classification",
        "writer.diff_review",
    }
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_GATE_FIELDS = frozenset({"id", "status", "command", "observation", "evidence"})
RECEIPT_FIELDS = frozenset({"contract", "implementation_sha", "inventory", "gates"})


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def validate_receipt(payload: Any, expected_sha: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError("receipt must be a JSON object")
    unknown_fields = set(payload) - RECEIPT_FIELDS
    if unknown_fields:
        raise ValueError(f"unknown receipt fields: {sorted(unknown_fields)}")
    if payload.get("contract") != CONTRACT:
        raise ValueError(f"contract must be {CONTRACT!r}")
    actual_sha = _text(payload.get("implementation_sha"), "implementation_sha")
    if not SHA_RE.fullmatch(actual_sha) or actual_sha != expected_sha:
        raise ValueError("implementation_sha must be the full lowercase exact SHA")
    inventory = payload.get("inventory")
    if not isinstance(inventory, list) or not inventory or any(
        not isinstance(item, str) or not item.strip() for item in inventory
    ):
        raise ValueError("inventory must be a non-empty list of paths")
    gates = payload.get("gates")
    if not isinstance(gates, list) or len(gates) != len(GATE_IDS):
        raise ValueError("gates must contain each required gate exactly once")
    seen: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict):
            raise ValueError("each gate must be an object")
        unknown_gate_fields = set(gate) - REQUIRED_GATE_FIELDS - {"justification"}
        if unknown_gate_fields:
            raise ValueError(f"unknown gate fields: {sorted(unknown_gate_fields)}")
        missing = REQUIRED_GATE_FIELDS - gate.keys()
        if missing:
            raise ValueError(f"gate missing required fields: {sorted(missing)}")
        gate_id = _text(gate.get("id"), "gate.id")
        if gate_id not in GATE_IDS:
            raise ValueError(f"unknown gate id: {gate_id}")
        if gate_id in seen:
            raise ValueError(f"duplicate gate id: {gate_id}")
        seen.add(gate_id)
        status = gate.get("status")
        if status not in {"PASS", "NOT_APPLICABLE"}:
            raise ValueError(f"gate {gate_id} has prohibited status")
        for field in ("command", "observation", "evidence"):
            _text(gate.get(field), f"gate.{field}")
        if status == "NOT_APPLICABLE":
            justification = gate.get("justification")
            if not isinstance(justification, str) or len(justification.strip()) < 10:
                raise ValueError(f"gate {gate_id} needs a concrete justification for N/A")
    if seen != GATE_IDS:
        raise ValueError("receipt is missing one or more required gate ids")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--sha", required=True, help="full lowercase implementation SHA")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.receipt.read_text(encoding="utf-8"))
        validate_receipt(payload, args.sha)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Pre-freeze receipt REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"Pre-freeze receipt admitted for {args.sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
