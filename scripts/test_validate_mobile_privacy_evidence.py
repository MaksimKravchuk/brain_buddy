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

    def test_rejects_unreadable_binary_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "screenshots"
            evidence.mkdir()
            (evidence / "device-capture.png").write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x01\xffnot-a-real-png"
            )
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

    def test_rejects_unreadable_binary_crash_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "crash-artifacts"
            evidence.mkdir()
            (evidence / "core.dump").write_bytes(b"\x00\x01\x02\xff\xfeundecodable")
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

    def test_allows_unreadable_binary_build_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "dist"
            vendored = evidence / "assets" / "node_modules" / "expo-router" / "assets"
            vendored.mkdir(parents=True)
            (vendored / "back-icon.png").write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x01\xffnot-a-real-png"
            )
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_unreadable_binary_attachment_directly_in_allure_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            evidence.mkdir()
            (evidence / "mystery.bin").write_bytes(b"\x00\x01\x02\xff\xfeundecodable")
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

    def test_rejects_unreadable_binary_attachment_in_arbitrary_allure_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "allure-results"
            attachment_dir = evidence / "attachments" / "arbitrary"
            attachment_dir.mkdir(parents=True)
            (attachment_dir / "diagnostic.bin").write_bytes(
                b"\x00\x01\x02\xff\xfeundecodable"
            )
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

    def test_rejects_unreadable_binary_directly_in_nested_vitest_allure_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "frontend" / "allure-results" / "vitest"
            evidence.mkdir(parents=True)
            (evidence / "mystery.bin").write_bytes(b"\x00\x01\x02\xff\xfeundecodable")
            completed = self.run_validator(
                "--path", str(evidence), "--label", "frontend-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

    def test_rejects_unreadable_binary_directly_in_nested_playwright_allure_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "frontend" / "allure-results" / "playwright"
            evidence.mkdir(parents=True)
            (evidence / "mystery.bin").write_bytes(b"\x00\x01\x02\xff\xfeundecodable")
            completed = self.run_validator(
                "--path", str(evidence), "--label", "playwright-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unreadable_binary_evidence", completed.stderr)

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

    def test_rejects_short_transcript_fixture_field_without_printing_it(self) -> None:
        fake_transcript = "buy milk"
        completed = self.scan_text(
            "case-result.json", json.dumps({"transcript": fake_transcript})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("audio_transcript_content", completed.stderr)
        self.assertNotIn(fake_transcript, completed.stderr)
        self.assertNotIn(fake_transcript, completed.stdout)

    def test_rejects_long_task_content_field(self) -> None:
        completed = self.scan_text(
            "case-result.json", json.dumps({"details": "task detail " * 10})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("task_content", completed.stderr)

    def test_rejects_short_task_title_without_printing_it(self) -> None:
        fake_title = "buy milk"
        completed = self.scan_text(
            "case-result.json", json.dumps({"title": fake_title})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("task_content", completed.stderr)
        self.assertNotIn(fake_title, completed.stderr)
        self.assertNotIn(fake_title, completed.stdout)

    def test_rejects_short_task_comment_body_without_printing_it(self) -> None:
        fake_body = "call mom back"
        completed = self.scan_text(
            "case-result.json", json.dumps({"body": fake_body})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("task_content", completed.stderr)
        self.assertNotIn(fake_body, completed.stderr)
        self.assertNotIn(fake_body, completed.stdout)

    def test_allows_empty_task_content_field(self) -> None:
        completed = self.scan_text("case-result.json", json.dumps({"title": ""}))

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_developer_absolute_path(self) -> None:
        completed = self.scan_text(
            "bundle.js",
            json.dumps({"sourceRoot": "/Users/exampledev/Code/brain_buddy/mobile"}),
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("absolute_path", completed.stderr)

    def test_rejects_ios_device_absolute_path(self) -> None:
        completed = self.scan_text(
            "crash-log.txt",
            json.dumps(
                {
                    "path": "/var/mobile/Containers/Data/Application/"
                    "5C1B2E7A-0000-0000-0000-000000000000/tmp/expo.log"
                }
            ),
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("absolute_path", completed.stderr)

    def test_rejects_android_device_absolute_path(self) -> None:
        completed = self.scan_text(
            "crash-log.txt",
            json.dumps({"path": "/data/user/0/com.brainbuddy.app/files/expo.log"}),
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

    def test_never_leaks_sensitive_value_via_malicious_filename(self) -> None:
        fake_credential = "fake-opaque-session-token-abcdef0123456789abcdef0123456789"
        fake_email = "someone@fixture-example.test"
        fake_transcript = "buy_milk_before_the_store_closes_tonight"
        malicious_name = f"{fake_credential}-{fake_email}-{fake_transcript}.json"
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            evidence.mkdir()
            (evidence / malicious_name).write_text(
                json.dumps({"log": f"Authorization: Bearer {fake_credential}"}),
                encoding="utf-8",
            )
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("credential", completed.stderr)
        for secret in (fake_credential, fake_email, fake_transcript, malicious_name):
            self.assertNotIn(secret, completed.stdout)
            self.assertNotIn(secret, completed.stderr)

    def test_finding_diagnostic_is_actionable_without_raw_filename(self) -> None:
        fake_email = "someone@fixture-example.test"
        completed = self.scan_text(
            "case-result.json", json.dumps({"description": f"owner {fake_email}"})
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("email", completed.stderr)
        self.assertIn("file #1 of 1", completed.stderr)
        self.assertNotIn("case-result.json", completed.stderr)
        self.assertNotIn("case-result.json", completed.stdout)

    def test_never_leaks_sensitive_value_via_evidence_root_path(self) -> None:
        fake_email = "someone@fixture-example.test"
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / fake_email
            evidence.mkdir()
            (evidence / "entry.json").write_text(
                json.dumps({"description": f"owner {fake_email}"}), encoding="utf-8"
            )
            completed = self.run_validator(
                "--path", str(evidence), "--label", "mobile-evidence"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("email", completed.stderr)
        self.assertNotIn(fake_email, completed.stdout)
        self.assertNotIn(fake_email, completed.stderr)

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
