import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SANITIZER = REPO_ROOT / "scripts" / "sanitize_privacy_evidence.py"
SCANNER = REPO_ROOT / "scripts" / "validate_mobile_privacy_evidence.py"


class SanitizePrivacyEvidenceTests(unittest.TestCase):
    def run_script(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_redacts_every_scanner_text_category_before_publication(self) -> None:
        credential = "fake-opaque-session-token-0123456789abcdef0123456789"
        email = "person@fixture-example.test"
        transcript = "buy milk"
        task_body = "call mom"
        absolute_path = "/home/privateuser/brain_buddy"
        content_hash = "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            evidence.mkdir()
            (evidence / "result.json").write_text(
                json.dumps(
                    {
                        "authorization": f"Bearer {credential}",
                        "email": email,
                        "path": absolute_path,
                        "chunkHash": content_hash,
                        "transcript": transcript,
                        "body": task_body,
                        "audio": "data:audio/m4a;base64,ZmFrZQ==",
                    }
                ),
                encoding="utf-8",
            )

            before = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )
            sanitized = self.run_script(
                SANITIZER, "--path", str(evidence), "--label", "test-evidence"
            )
            after = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )

        self.assertNotEqual(before.returncode, 0)
        self.assertEqual(sanitized.returncode, 0, sanitized.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertIn("sanitized", sanitized.stdout)
        for sensitive_value in (
            credential,
            email,
            transcript,
            task_body,
            absolute_path,
            content_hash,
        ):
            self.assertNotIn(sensitive_value, sanitized.stdout)
            self.assertNotIn(sensitive_value, sanitized.stderr)

    def test_leaves_unreadable_allure_binary_for_scanner_to_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            evidence.mkdir()
            (evidence / "attachment.bin").write_bytes(b"\x00\x01\xffundecodable")

            sanitized = self.run_script(
                SANITIZER, "--path", str(evidence), "--label", "test-evidence"
            )
            scanned = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )

        self.assertEqual(sanitized.returncode, 0, sanitized.stderr)
        self.assertNotEqual(scanned.returncode, 0)
        self.assertIn("unreadable_binary_evidence", scanned.stderr)

    def test_redacts_task_and_transcript_fields_nested_inside_a_serialized_json_string(
        self,
    ) -> None:
        # A step parameter or log line can echo an entire task/transcript
        # object as a JSON-encoded string value: the field names are
        # themselves backslash-escaped in the raw file text (e.g.
        # `\"body\"`, not `"body"`), which the scanner must detect and this
        # sanitizer must redact while keeping both the outer file and the
        # nested payload valid, parseable JSON.
        task_body = "call mom back"
        transcript = "buy milk"
        nested = json.dumps({"body": task_body, "transcript": transcript})
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            evidence.mkdir()
            result_file = evidence / "result.json"
            result_file.write_text(
                json.dumps({"stepDescription": nested}), encoding="utf-8"
            )

            before = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )
            sanitized = self.run_script(
                SANITIZER, "--path", str(evidence), "--label", "test-evidence"
            )
            after_text = result_file.read_text(encoding="utf-8")
            after = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )

        self.assertNotEqual(before.returncode, 0)
        self.assertEqual(sanitized.returncode, 0, sanitized.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertNotIn(task_body, sanitized.stdout)
        self.assertNotIn(transcript, sanitized.stdout)

        outer = json.loads(after_text)
        inner = json.loads(outer["stepDescription"])
        self.assertEqual(inner, {"body": "", "transcript": ""})

    def test_redacts_only_the_field_with_real_content_among_empty_nested_siblings(
        self,
    ) -> None:
        # Regression for a greedy/overrunning value match: once a nested
        # `body` field is redacted to an empty string, a naive pattern can
        # walk straight through its own (now immediately-adjacent) empty
        # closing quote and latch onto a neighboring field's escaped quotes
        # instead, corrupting the nested JSON payload.
        task_body = "call mom back"
        nested = json.dumps({"title": "", "body": task_body, "details": ""})
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            evidence.mkdir()
            result_file = evidence / "result.json"
            result_file.write_text(
                json.dumps({"stepDescription": nested}), encoding="utf-8"
            )

            sanitized = self.run_script(
                SANITIZER, "--path", str(evidence), "--label", "test-evidence"
            )
            after_text = result_file.read_text(encoding="utf-8")
            after = self.run_script(
                SCANNER, "--path", str(evidence), "--label", "test-evidence"
            )

        self.assertEqual(sanitized.returncode, 0, sanitized.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)

        outer = json.loads(after_text)
        inner = json.loads(outer["stepDescription"])
        self.assertEqual(inner, {"title": "", "body": "", "details": ""})


if __name__ == "__main__":
    unittest.main()
