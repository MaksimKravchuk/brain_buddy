#!/usr/bin/env python3
"""Contract tests for scripts/check_smoke_identity_cohort.py.

The deploy preflight must fail closed — printing variable names only, never
values — when a smoke identity secret is missing, when the admin email or any
cohort entry is not email-shaped (backend startup would reject them after the
deploy mutated production), when the admin password violates the backend
password policy (seeding would fail at startup), or when the normalized admin
email is not a member of the normalized comma-separated internal cohort.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_smoke_identity_cohort.py")

_SPEC = importlib.util.spec_from_file_location("check_smoke_identity_cohort", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
is_cohort_member = _MODULE.is_cohort_member
preflight_errors = _MODULE.preflight_errors

ADMIN_EMAIL = "Deploy.Admin@Example.COM"
ADMIN_PASSWORD = "super-secret-admin-password"


def _run(env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "BRAIN_BUDDY_ADMIN_EMAIL": ADMIN_EMAIL,
        "BRAIN_BUDDY_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS": (
            f"other@example.com, {ADMIN_EMAIL.lower()}"
        ),
    }
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class IsCohortMemberTest(unittest.TestCase):
    def test_membership_is_case_and_whitespace_insensitive(self) -> None:
        self.assertTrue(
            is_cohort_member(
                "  Admin@Example.COM ", "x@example.com , admin@example.com "
            )
        )

    def test_non_member_is_rejected(self) -> None:
        self.assertFalse(
            is_cohort_member("admin@example.com", "someone-else@example.com")
        )

    def test_empty_cohort_is_rejected(self) -> None:
        self.assertFalse(is_cohort_member("admin@example.com", ""))
        self.assertFalse(is_cohort_member("admin@example.com", " , ,"))

    def test_blank_admin_email_is_rejected(self) -> None:
        self.assertFalse(is_cohort_member("  ", "admin@example.com"))


class PreflightErrorsTest(unittest.TestCase):
    """The pure preflight mirrors backend startup validation so a deploy can
    only proceed when the seeded admin identity would actually come up."""

    def _errors(
        self,
        email: str = "admin@example.com",
        password: str = "long-enough-password",
        cohort: str = "admin@example.com",
    ) -> list[str]:
        return preflight_errors(email, password, cohort)

    def test_valid_identity_has_no_errors(self) -> None:
        self.assertEqual(self._errors(), [])

    def test_admin_email_without_at_sign_is_rejected(self) -> None:
        errors = self._errors(email="not-an-email", cohort="not-an-email")
        self.assertTrue(any("BRAIN_BUDDY_ADMIN_EMAIL" in e for e in errors))
        self.assertFalse(any("not-an-email" in e for e in errors))

    def test_non_email_cohort_entry_is_rejected(self) -> None:
        errors = self._errors(cohort="admin@example.com, bogus-entry")
        self.assertTrue(
            any("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS" in e for e in errors)
        )
        self.assertFalse(any("bogus-entry" in e for e in errors))

    def test_short_password_is_rejected(self) -> None:
        errors = self._errors(password="eleven-char")
        self.assertTrue(any("BRAIN_BUDDY_ADMIN_PASSWORD" in e for e in errors))
        self.assertFalse(any("eleven-char" in e for e in errors))

    def test_twelve_character_password_passes(self) -> None:
        """The backend password policy floor is 12 characters."""

        self.assertEqual(self._errors(password="a" * 12), [])
        self.assertNotEqual(self._errors(password="a" * 11), [])

    def test_overlong_password_is_rejected(self) -> None:
        """The backend password policy ceiling is 128 characters; seeding a
        longer password would fail backend startup after the deploy."""

        self.assertEqual(self._errors(password="a" * 128), [])
        self.assertNotEqual(self._errors(password="a" * 129), [])

    def test_non_member_admin_is_rejected(self) -> None:
        errors = self._errors(cohort="someone-else@example.com")
        self.assertTrue(
            any("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS" in e for e in errors)
        )


class PreflightScriptTest(unittest.TestCase):
    def test_member_identity_passes(self) -> None:
        result = _run({})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_missing_secret_fails_and_is_named(self) -> None:
        for missing in (
            "BRAIN_BUDDY_ADMIN_EMAIL",
            "BRAIN_BUDDY_ADMIN_PASSWORD",
            "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS",
        ):
            for value in (None, "", "   "):
                with self.subTest(missing=missing, value=value):
                    result = _run({missing: value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(missing, result.stderr)

    def test_non_member_admin_fails_closed(self) -> None:
        result = _run(
            {"BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS": "outsider@example.com"}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", result.stderr)

    def test_non_email_admin_fails_closed_and_names_the_variable(self) -> None:
        result = _run(
            {
                "BRAIN_BUDDY_ADMIN_EMAIL": "deploy-admin-no-at-sign",
                "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS": "deploy-admin-no-at-sign",
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BRAIN_BUDDY_ADMIN_EMAIL", result.stderr)
        self.assertNotIn("deploy-admin-no-at-sign", result.stdout + result.stderr)

    def test_non_email_cohort_entry_fails_closed(self) -> None:
        result = _run(
            {
                "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS": (
                    f"{ADMIN_EMAIL}, cohort-bogus-entry"
                )
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", result.stderr)
        self.assertNotIn("cohort-bogus-entry", result.stdout + result.stderr)

    def test_policy_violating_password_fails_closed(self) -> None:
        result = _run({"BRAIN_BUDDY_ADMIN_PASSWORD": "eleven-char"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BRAIN_BUDDY_ADMIN_PASSWORD", result.stderr)
        self.assertNotIn("eleven-char", result.stdout + result.stderr)

    def test_output_never_contains_secret_values(self) -> None:
        for overrides in (
            {},
            {"BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS": "outsider@example.com"},
            {"BRAIN_BUDDY_ADMIN_PASSWORD": None},
            {"BRAIN_BUDDY_ADMIN_PASSWORD": "shortpw"},
        ):
            with self.subTest(overrides=overrides):
                result = _run(dict(overrides))
                combined = result.stdout + result.stderr
                self.assertNotIn(ADMIN_PASSWORD, combined)
                self.assertNotIn(ADMIN_EMAIL.lower(), combined.lower())


if __name__ == "__main__":
    unittest.main()
