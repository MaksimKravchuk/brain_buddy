"""Executable contract tests for writer-owned pre-freeze receipts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_pre_freeze_receipt.py"
SHA = "a" * 40


def valid_receipt() -> dict:
    return {
        "contract": "brainbuddy.pre-freeze-writer-receipt/v1",
        "implementation_sha": SHA,
        "inventory": ["docs/example.md"],
        "gates": [
            {
                "id": gate_id,
                "status": "PASS",
                "command": "printf observed",
                "observation": "observed successfully",
                "evidence": "terminal output captured in writer log",
            }
            for gate_id in (
                "writer.tests",
                "writer.verify_all",
                "writer.path_classification",
                "writer.diff_review",
            )
        ],
    }


class PreFreezeReceiptTests(unittest.TestCase):
    def run_receipt(self, payload: dict, sha: str = SHA) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(path), "--sha", sha],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_valid_receipt_is_admitted(self) -> None:
        result = self.run_receipt(valid_receipt())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_required_receipt_is_rejected(self) -> None:
        result = self.run_receipt({})
        self.assertNotEqual(result.returncode, 0)

    def test_fail_and_unverified_statuses_are_rejected(self) -> None:
        for status in ("FAIL", "UNVERIFIED"):
            payload = valid_receipt()
            payload["gates"][0]["status"] = status
            result = self.run_receipt(payload)
            self.assertNotEqual(result.returncode, 0, status)

    def test_sha_must_be_full_lowercase_exact_match(self) -> None:
        for sha in ("b" * 40, SHA[:39], SHA.upper()):
            result = self.run_receipt(valid_receipt(), sha=sha)
            self.assertNotEqual(result.returncode, 0, sha)

    def test_duplicate_and_unknown_gate_are_rejected(self) -> None:
        duplicate = valid_receipt()
        duplicate["gates"][1]["id"] = duplicate["gates"][0]["id"]
        self.assertNotEqual(self.run_receipt(duplicate).returncode, 0)
        unknown = valid_receipt()
        unknown["gates"][0]["id"] = "writer.unknown"
        self.assertNotEqual(self.run_receipt(unknown).returncode, 0)

    def test_not_applicable_requires_justification(self) -> None:
        payload = valid_receipt()
        gate = payload["gates"][0]
        gate["status"] = "NOT_APPLICABLE"
        self.assertNotEqual(self.run_receipt(payload).returncode, 0)
        gate["justification"] = "No product code changed; this is a documentation-only candidate."
        self.assertEqual(self.run_receipt(payload).returncode, 0)


if __name__ == "__main__":
    unittest.main()
