import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_mobile_privacy_evidence.py"


class ValidateMobilePrivacyEvidenceTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def scan_text(self, filename: str, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            evidence.mkdir()
            (evidence / filename).write_text(text, encoding="utf-8")
            return self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

    def test_passes_on_clean_evidence(self) -> None:
        completed = self.scan_text("entry.js", "console.log('hello world');")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("privacy scan passed", completed.stdout)

    def test_rejects_bearer_credential_without_printing_it(self) -> None:
        fake_credential = "fake-opaque-session-token-0123456789abcdef0123456789"
        completed = self.scan_text(
            "case-result.json",
            json.dumps({"log": f"Authorization: Bearer {fake_credential}"}),
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("credential", completed.stderr)
        self.assertNotIn(fake_credential, completed.stderr)
        self.assertNotIn(fake_credential, completed.stdout)

    def test_rejects_jwt_shaped_credential_without_printing_it(self) -> None:
        fake_jwt = "eyJ" + "a" * 32
        completed = self.scan_text("bundle.js", json.dumps({"token": fake_jwt}))

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("credential", completed.stderr)
        self.assertNotIn(fake_jwt, completed.stderr)

    def test_rejects_email_without_printing_it(self) -> None:
        fake_email = "someone@fixture-example.test"
        completed = self.scan_text(
            "case-result.json", json.dumps({"description": f"owner {fake_email}"})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("email", completed.stderr)
        self.assertNotIn(fake_email, completed.stderr)

    def test_rejects_raw_audio_file_by_extension_even_if_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "crash-artifacts"
            evidence.mkdir()
            (evidence / "recording.m4a").write_bytes(b"\x00\x01\x02not-real-audio-bytes")
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("audio_transcript_content", completed.stderr)

    def test_rejects_audio_data_uri(self) -> None:
        completed = self.scan_text(
            "bundle.js", "const uri = 'data:audio/m4a;base64,ZmFrZQ==';"
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("audio_transcript_content", completed.stderr)

    def test_rejects_long_transcript_field(self) -> None:
        completed = self.scan_text(
            "case-result.json", json.dumps({"transcript": "word " * 60})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("audio_transcript_content", completed.stderr)

    def test_allows_short_transcript_fixture_field(self) -> None:
        completed = self.scan_text(
            "case-result.json", json.dumps({"transcript": "buy milk"})
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_long_task_content_field(self) -> None:
        completed = self.scan_text(
            "case-result.json", json.dumps({"details": "task detail " * 10})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("task_content", completed.stderr)

    def test_rejects_developer_absolute_path(self) -> None:
        completed = self.scan_text(
            "bundle.js",
            json.dumps({"sourceRoot": "/Users/exampledev/Code/brain_buddy/mobile"}),
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("absolute_path", completed.stderr)

    def test_allows_shared_github_runner_home_path(self) -> None:
        completed = self.scan_text(
            "bundle.js",
            json.dumps({"sourceRoot": "/home/runner/work/brain_buddy/mobile"}),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_sha256_content_hash(self) -> None:
        completed = self.scan_text(
            "case-result.json", json.dumps({"chunkHash": "a" * 64})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("content_hash", completed.stderr)

    def test_allows_allure_history_ids(self) -> None:
        completed = self.scan_text(
            "case-result.json",
            json.dumps(
                {
                    "historyId": "7e08e0f36cda8f60b939f4509a5db4af:d41d8cd98f00b204e9800998ecf8427e",
                    "testCaseId": "7e08e0f36cda8f60b939f4509a5db4af",
                }
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_skips_missing_optional_roots_but_requires_at_least_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            present = Path(tmp) / "dist"
            present.mkdir()
            (present / "entry.js").write_text("ok", encoding="utf-8")
            missing = Path(tmp) / "crash-artifacts"
            completed = self.run_validator(
                "--path", str(present), "--path", str(missing), "--label", "mobile-evidence"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("skipping", completed.stderr)

    def test_fails_when_no_requested_roots_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            completed = self.run_validator(
                "--path", str(missing), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("none of the requested evidence roots exist", completed.stderr)


if __name__ == "__main__":
    unittest.main()
