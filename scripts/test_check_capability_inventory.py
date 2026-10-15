#!/usr/bin/env python3
"""Contract tests for scripts/check_capability_inventory.py."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_capability_inventory.py")
_SPEC = importlib.util.spec_from_file_location("check_capability_inventory", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)

OWNER_REMOVED = {
    "CAP-CFG-004", "CAP-CFG-011", "CAP-CFG-012",
    "CAP-CLI-006", "CAP-CLI-007", "CAP-JOB-008",
}  # fmt: skip
OWNER_PORTED = {"CAP-STORE-013", "CAP-CFG-092"}
PR02_ROWS = {"CAP-CLI-004", "CAP-JOB-004", "CAP-JOB-021", "CAP-STORE-015"}


def _row(cid: str, disposition: str = "port", **extra: object) -> dict:
    row: dict = {
        "id": cid,
        "disposition": disposition,
        "evidence": {"kind": "conformance", "id": cid.lower().replace("-", "_")},
        "slice": "PR-39",
    }
    row.update(extra)
    return row


class RecordedDispositionsTest(unittest.TestCase):
    def setUp(self) -> None:
        doc = json.loads(checker.DISPOSITIONS.read_text(encoding="utf-8"))
        self.rows = {row["id"]: row for row in doc["rows"]}

    def test_027_FR_001_every_inventory_id_has_a_final_row(self) -> None:
        ids = checker.inventory_ids()
        self.assertEqual(len(ids), 337)
        self.assertEqual(checker.check_rows(list(self.rows.values()), ids, True), [])

    def test_027_SC_003_default_and_final_modes_pass(self) -> None:
        self.assertEqual(checker.main([]), 0)
        self.assertEqual(checker.main(["--final"]), 0)

    def test_027_FR_001_owner_dispositions_are_recorded(self) -> None:
        for cid in OWNER_REMOVED:
            self.assertEqual(self.rows[cid]["disposition"], "remove", cid)
        for cid in OWNER_PORTED:
            self.assertEqual(self.rows[cid]["disposition"], "port", cid)

    def test_027_FR_001_pr02_rows_are_owned_and_removed(self) -> None:
        for cid in PR02_ROWS:
            self.assertEqual(self.rows[cid]["slice"], "PR-02", cid)
            self.assertEqual(self.rows[cid]["disposition"], "remove", cid)

    def test_027_FR_001_no_pending_owner_row_remains(self) -> None:
        self.assertNotIn("pending-owner", {r["disposition"] for r in self.rows.values()})


class StructureTest(unittest.TestCase):
    IDS = ["CAP-HTTP-001", "CAP-HTTP-002"]

    def errors(self, rows: list[dict], final: bool = False) -> list[str]:
        return checker.check_rows(rows, self.IDS, final)

    def test_missing_row_is_reported(self) -> None:
        self.assertIn("CAP-HTTP-002: missing row", self.errors([_row("CAP-HTTP-001")]))

    def test_missing_evidence_id_is_reported(self) -> None:
        bad = _row("CAP-HTTP-001")
        bad["evidence"]["id"] = ""
        self.assertTrue(any("missing evidence id" in e for e in self.errors([bad])))

    def test_change_and_remove_need_an_approval_reference(self) -> None:
        for disposition in ("change", "remove"):
            rows = [_row("CAP-HTTP-001", disposition), _row("CAP-HTTP-002")]
            self.assertTrue(any("needs an approval" in e for e in self.errors(rows)))
            rows[0].update(approval="027-FR-001", reason="x")
            self.assertEqual(self.errors(rows), [])

    def test_pending_owner_fails_only_in_final_mode(self) -> None:
        rows = [_row("CAP-HTTP-001", "pending-owner"), _row("CAP-HTTP-002")]
        self.assertEqual(self.errors(rows), [])
        self.assertTrue(any("pending-owner" in e for e in self.errors(rows, True)))

    def test_duplicate_and_unknown_ids_are_reported(self) -> None:
        rows = [_row("CAP-HTTP-001"), _row("CAP-HTTP-001"), _row("CAP-HTTP-002")]
        self.assertTrue(any("duplicate" in e for e in self.errors(rows)))
        rows = [*rows[1:], _row("CAP-HTTP-099")]
        self.assertTrue(any("not in the inventory" in e for e in self.errors(rows)))


class ReportTest(unittest.TestCase):
    def test_port_row_needs_both_servers_green_and_equal(self) -> None:
        row = _row("CAP-HTTP-001")
        green = {"cap_http_001_health": "passed"}
        self.assertEqual(checker.check_reports([row], green, green), [])
        red = {"cap_http_001_health": "failed"}
        errors = checker.check_reports([row], green, red)
        self.assertTrue(any("rust evidence" in e for e in errors))
        self.assertTrue(any("differ" in e for e in errors))
        errors = checker.check_reports([row], {}, green)
        self.assertTrue(any("missing" in e for e in errors))

    def test_change_and_remove_rows_need_rust_evidence_only(self) -> None:
        rust = {"cap_http_001": "passed"}
        for disposition in ("change", "remove"):
            rows = [_row("CAP-HTTP-001", disposition, approval="a", reason="r")]
            self.assertEqual(checker.check_reports(rows, {}, rust), [])
            self.assertTrue(checker.check_reports(rows, rust, {}))

    def test_027_fr_001_differing_matched_test_names_are_rejected(self) -> None:
        row = _row("CAP-HTTP-001")
        python = {"cap_http_001_python_only": "passed"}
        rust = {"cap_http_001_rust_only": "passed"}
        errors = checker.check_reports([row], python, rust)
        self.assertTrue(any("differ" in e for e in errors))

    def test_027_fr_001_partial_report_input_is_rejected(self) -> None:
        port = _row("CAP-HTTP-001")
        green = {"cap_http_001": "passed"}
        errors = checker.check_reports([port], None, green)
        self.assertTrue(any("Python report" in e for e in errors))
        errors = checker.check_reports([port], green, None)
        self.assertTrue(any("Rust report" in e for e in errors))
        change = _row("CAP-HTTP-001", "change", approval="a", reason="r")
        self.assertEqual(checker.check_reports([change], None, green), [])
        self.assertTrue(checker.check_reports([change], green, None))

    def test_027_fr_001_cli_fails_when_only_one_report_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps({"results": {}}))
            self.assertEqual(checker.main(["--python-report", str(path)]), 1)
            self.assertEqual(checker.main(["--rust-report", str(path)]), 1)

    def test_evidence_name_must_match_the_id_boundary(self) -> None:
        report = {"cap_http_0010": "passed"}
        self.assertEqual(checker.evidence_status(report, "cap_http_001"), "missing")

    def test_report_loader_accepts_dict_and_list_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps({"results": [{"name": "a", "status": "passed"}]}))
            self.assertEqual(checker.load_report(path), {"a": "passed"})
            path.write_text(json.dumps({"results": {"b": "failed"}}))
            self.assertEqual(checker.load_report(path), {"b": "failed"})


if __name__ == "__main__":
    unittest.main()
