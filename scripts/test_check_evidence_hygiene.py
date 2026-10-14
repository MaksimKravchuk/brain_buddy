#!/usr/bin/env python3
"""Contract tests for scripts/check_evidence_hygiene.py (027-FR-016, 027-SC-004)."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_evidence_hygiene.py")
_SPEC = importlib.util.spec_from_file_location("check_evidence_hygiene", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
hygiene = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hygiene)

PLANTED = {
    "email": "owner: someone@example.com",
    "invite code": 'invite_code = "ABCD1234"',
    "credential": "Authorization: Bearer abcdefghijklmnop",
    "local path": "saved to /home/max/Code/x.png",
    "content hash": "a" * 64,
}
CLEAN = (
    "correlation_id: 7f3c2d1e-0000-4000-8000-000000000001\n"
    "elapsed_ms: 42\ncount: 3\ncommit: " + "b" * 40 + "\n"
)


class EvidenceHygieneTest(unittest.TestCase):
    def test_027_FR_016_each_planted_violation_is_reported(self) -> None:
        for rule, text in PLANTED.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, [n for _, n in hygiene.scan_text(text)])

    def test_027_SC_004_clean_evidence_passes(self) -> None:
        self.assertEqual(hygiene.scan_text(CLEAN), [])

    def test_scan_roots_walks_files_and_skips_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.md").write_text(CLEAN, encoding="utf-8")
            (root / "tone.wav").write_bytes(b"\xff\xfe\x00\x80" * 8)
            self.assertEqual(hygiene.scan_roots([root]), [])
            (root / "bad.json").write_text(PLANTED["email"], encoding="utf-8")
            problems = hygiene.scan_roots([root])
            self.assertEqual(len(problems), 1)
            self.assertIn("bad.json:1: email", problems[0])

    def test_main_exit_codes_and_missing_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(hygiene.main([str(Path(tmp) / "absent")]), 0)
            (Path(tmp) / "x.txt").write_text(PLANTED["local path"], encoding="utf-8")
            self.assertEqual(hygiene.main([tmp]), 1)

    def test_current_tree_passes(self) -> None:
        repo = SCRIPT.parent.parent
        roots = [repo / r for r in hygiene.DEFAULT_ROOTS]
        self.assertEqual(hygiene.scan_roots([r for r in roots if r.exists()]), [])


if __name__ == "__main__":
    unittest.main()
