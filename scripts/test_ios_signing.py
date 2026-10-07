"""Exercise signing credential failures with real synthetic PKCS#12 data.

Only macOS Security.framework is substituted; certificate decoding, signed OU
and fingerprint checks use real OpenSSL. This does not establish Xcode signing.
"""

import base64
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "ios/ci/install_signing_identity.sh"


class SigningIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = os.environ | {
            "RUNNER_TEMP": str(self.root),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "APPLE_TEAM_ID": "TESTTEAM01",
            "P12_PASSWORD": "synthetic-password",
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
        }
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(self.root / "key.pem"),
                "-out",
                str(self.root / "cert.pem"),
                "-days",
                "1",
                "-subj",
                "/CN=Apple Development: Synthetic/OU=TESTTEAM01",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkcs12",
                "-export",
                "-inkey",
                str(self.root / "key.pem"),
                "-in",
                str(self.root / "cert.pem"),
                "-out",
                str(self.root / "input.p12"),
                "-passout",
                "env:P12_PASSWORD",
            ],
            env=self.env,
            check=True,
            capture_output=True,
        )
        fingerprint = (
            subprocess.check_output(
                [
                    "openssl",
                    "x509",
                    "-in",
                    str(self.root / "cert.pem"),
                    "-noout",
                    "-fingerprint",
                    "-sha1",
                ],
                text=True,
            )
            .split("=", 1)[1]
            .strip()
            .replace(":", "")
        )
        self.identity = fingerprint
        self.env["BUILD_CERTIFICATE_BASE64"] = base64.b64encode(
            (self.root / "input.p12").read_bytes()
        ).decode()
        self.env["VALID_IDENTITIES"] = (
            f'  1) {fingerprint} "Apple Development: Synthetic (TESTTEAM01)"'
        )
        security = self.root / "security"
        security.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "command = sys.argv[1]\n"
            "keychain = pathlib.Path(os.environ['RUNNER_TEMP']) / 'brainbuddy-development.keychain-db'\n"
            "if command == 'create-keychain': keychain.touch()\n"
            "if command in os.environ.get('FAIL_SECURITY_COMMAND', '').split(','): sys.exit(1)\n"
            "if command == 'delete-keychain': keychain.unlink(missing_ok=True)\n"
            "if command == 'find-identity': print(os.environ['VALID_IDENTITIES'])\n"
        )
        security.chmod(0o700)

    def run_installer(self):
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotIn(self.env["P12_PASSWORD"], result.stdout + result.stderr)
        self.assertFalse((self.root / "brainbuddy-development.p12").exists())
        self.assertFalse((self.root / "brainbuddy-development.pem").exists())
        return result

    def assert_rejected(self):
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertFalse((self.root / "brainbuddy-development.keychain-db").exists())
        self.assertFalse((self.root / "output").exists())

    def test_valid_identity_is_selected_without_retaining_pkcs12(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(
            (self.root / "output").read_text(), f"identity={self.identity}\n"
        )
        self.assertTrue((self.root / "brainbuddy-development.keychain-db").exists())

    def test_missing_untrusted_or_expired_identity_is_rejected(self):
        self.env["VALID_IDENTITIES"] = "0 valid identities found"
        self.assert_rejected()

    def test_ambiguous_identities_are_rejected(self):
        self.env["VALID_IDENTITIES"] += "\n" + self.env["VALID_IDENTITIES"]
        self.assert_rejected()

    def test_wrong_team_ou_is_rejected_even_if_display_name_matches(self):
        self.env["APPLE_TEAM_ID"] = "OTHERTEAM1"
        self.env["VALID_IDENTITIES"] = self.env["VALID_IDENTITIES"].replace(
            "TESTTEAM01", "OTHERTEAM1"
        )
        self.assert_rejected()

    def test_non_development_identity_is_rejected(self):
        self.env["VALID_IDENTITIES"] = self.env["VALID_IDENTITIES"].replace(
            "Apple Development", "Apple Distribution"
        )
        self.assert_rejected()

    def test_import_failure_removes_partial_keychain(self):
        self.env["FAIL_SECURITY_COMMAND"] = "import"
        self.assert_rejected()

    def test_partition_failure_removes_imported_keychain(self):
        self.env["FAIL_SECURITY_COMMAND"] = "set-key-partition-list"
        self.assert_rejected()

    def test_wrong_pkcs12_password_is_rejected(self):
        self.env["P12_PASSWORD"] = "wrong-synthetic-password"
        self.assert_rejected()

    def test_a_different_identity_fingerprint_is_rejected(self):
        self.env["VALID_IDENTITIES"] = self.env["VALID_IDENTITIES"].replace(
            self.identity, "A" * 40
        )
        self.assert_rejected()

    def test_failed_cleanup_does_not_report_a_usable_identity(self):
        self.env["FAIL_SECURITY_COMMAND"] = "import,delete-keychain"
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertFalse((self.root / "output").exists())
        self.assertTrue((self.root / "brainbuddy-development.keychain-db").exists())

    def test_invalid_base64_is_rejected_before_keychain_creation(self):
        self.env["BUILD_CERTIFICATE_BASE64"] = "invalid base64"
        self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
