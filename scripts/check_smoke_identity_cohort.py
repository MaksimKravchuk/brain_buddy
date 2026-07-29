#!/usr/bin/env python3
"""Fail closed unless the provisioned smoke identity can pass the canary smoke.

Reads ``BRAIN_BUDDY_ADMIN_EMAIL``, ``BRAIN_BUDDY_ADMIN_PASSWORD``, and
``BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`` from the environment and exits
non-zero — naming variable names only, never values — when any is missing or
blank, or when the identity would not survive backend startup validation,
which this preflight mirrors:

- the normalized (trimmed, lower-cased) admin email must be email-shaped
  (contain ``@``) — ``seed_admin`` normalizes the same way;
- every normalized entry of the comma-separated internal cohort must be
  email-shaped — ``FeatureFlagSettings`` rejects non-email entries at
  startup;
- the admin password must satisfy the backend password policy (12–128
  characters) — ``seed_admin`` raises at startup otherwise;
- the normalized admin email must be a member of the normalized cohort —
  otherwise the ``delivery_canary`` smoke assertion could never pass.

The production deploy workflow runs this before any remote mutation: any of
these failures could otherwise only surface AFTER mutating production.
Standard library only.
"""

from __future__ import annotations

import os
import sys

REQUIRED_VARS = (
    "BRAIN_BUDDY_ADMIN_EMAIL",
    "BRAIN_BUDDY_ADMIN_PASSWORD",
    "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS",
)

# Mirrors app.core.config.PasswordPolicy (min_length=12, max_length=128),
# enforced by AuthService.seed_admin at backend startup.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def normalize_email(value: str) -> str:
    return value.strip().lower()


def parse_cohort(raw: str) -> frozenset[str]:
    return frozenset(
        normalize_email(entry) for entry in raw.split(",") if entry.strip()
    )


def is_cohort_member(admin_email: str, cohort_raw: str) -> bool:
    admin = normalize_email(admin_email)
    return bool(admin) and admin in parse_cohort(cohort_raw)


def preflight_errors(
    admin_email: str, admin_password: str, cohort_raw: str
) -> list[str]:
    """Backend-startup-mirroring checks; messages never contain values."""

    errors: list[str] = []
    if "@" not in normalize_email(admin_email):
        errors.append(
            "BRAIN_BUDDY_ADMIN_EMAIL is not email-shaped (no '@'); the "
            "backend would seed an unusable admin account."
        )
    if any("@" not in entry for entry in parse_cohort(cohort_raw)):
        errors.append(
            "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS contains an entry that "
            "is not email-shaped (no '@'); backend startup would reject the "
            "cohort configuration."
        )
    if not MIN_PASSWORD_LENGTH <= len(admin_password) <= MAX_PASSWORD_LENGTH:
        errors.append(
            "BRAIN_BUDDY_ADMIN_PASSWORD violates the backend password policy "
            f"({MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters); "
            "backend startup would fail while seeding the admin account."
        )
    if not is_cohort_member(admin_email, cohort_raw):
        errors.append(
            "BRAIN_BUDDY_ADMIN_EMAIL is not a member of "
            "BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS (comparison is trimmed "
            "and case-insensitive). The delivery_canary smoke assertion could "
            "only fail after deploy."
        )
    return errors


def main() -> int:
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name, "").strip()]
    if missing:
        print(
            "Missing or blank required secrets: "
            + ", ".join(missing)
            + ". Refusing to deploy a revision that cannot be smoke-verified.",
            file=sys.stderr,
        )
        return 1
    errors = preflight_errors(
        os.environ["BRAIN_BUDDY_ADMIN_EMAIL"],
        os.environ["BRAIN_BUDDY_ADMIN_PASSWORD"],
        os.environ["BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS"],
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(
            "Smoke identity preflight failed; failing closed before any "
            "remote mutation.",
            file=sys.stderr,
        )
        return 1
    print(
        "Smoke identity preflight passed: all secrets are set, the identity "
        "satisfies backend startup validation, and the admin email is in the "
        "internal cohort."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
