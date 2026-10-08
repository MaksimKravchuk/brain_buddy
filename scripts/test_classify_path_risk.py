#!/usr/bin/env python3
"""Contract tests for scripts/classify_path_risk.py.

The classifier is the mechanical Ship/Show/Ask gate (ADR-0008): a PR-less
trunk candidate must fail closed before any push when its changed paths touch
ASK-class surfaces. ADR-0030 narrows ASK, while there are no real users, to
persisted data and migrations, secrets, GDPR account deletion/export, the
Allure gate rules, every GitHub workflow (they can read repository
secrets) and the landing machinery itself. Ambiguity fails toward
ASK; documentation-only paths are SHIP.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("classify_path_risk.py")

_SPEC = importlib.util.spec_from_file_location("classify_path_risk", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
classify_path = _MODULE.classify_path
ASK = _MODULE.ASK
SHIP = _MODULE.SHIP

ASK_PATHS = (
    # Migrations / destructive persistence
    "backend/migrations/0001_init.sql",
    "backend/alembic/env.py",
    "backend/data/tree_1.json",
    # Secrets
    ".env.example",
    ".env",
    "backend/app/core/secrets.py",
    "deploy/credentials.json",
    # GDPR account deletion/export
    "backend/app/services/account_service.py",
    # 008-FR-007. The aggregate Allure quality gate's rules: this file decides what
    # "passing" means for a whole CI run, yet its name carries no ASK token
    # and it sits under no ASK prefix.
    "allurerc.mjs",
    # The landing machinery that enforces this classification.
    "scripts/classify_path_risk.py",
    "scripts/check_gate_integrity.py",
    ".specify/gate-integrity.json",
    # Any workflow can read repository secrets.
    ".github/workflows/deploy-fly-production.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/claude.yml",
    ".github/actions/anything/action.yml",
)

SHIP_PATHS = (
    "backend/app/services/tree_service.py",
    "backend/app/modules/tasks/service.py",
    "backend/tests/test_tree_service.py",
    "frontend/src/components/TreeCanvas.tsx",
    "frontend/src/stores/treeStore.ts",
    "feature.txt",
    # ADR-0030: CI, delivery scripts, Docker/Fly configuration and auth code
    # are SHIP while there are no real users; CI and review still guard them.
    "scripts/submit_to_trunk.sh",
    "scripts/production_smoke.sh",
    "scripts/new_helper.py",
    "Makefile",
    "fly.backend.toml",
    "backend/Dockerfile",
    "compose.yaml",
    "deploy/nginx.conf",
    "backend/app/api/auth.py",
    "backend/app/api/routes.py",
    "backend/app/api/middleware.py",
    "backend/app/services/session_service.py",
    "backend/app/repositories/user_repository.py",
    "frontend/src/components/LoginForm.tsx",
    "infra/permissions/policy.json",
    # Documentation is SHIP even when it talks about risky topics: it cannot
    # change runtime or CI behavior.
    "README.md",
    "docs/auth.md",
    "docs/secrets.md",
    "docs/decisions/0008-verified-trunk-serial-landing.md",
    "specs/004-verified-trunk-delivery/spec.md",
)


def _run(paths: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="\n".join(paths) + ("\n" if paths else ""),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_null(paths: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    """Run the classifier in NUL-separated mode with raw byte input, the way
    ``git diff --no-renames --name-only -z`` feeds it."""

    return subprocess.run(
        [sys.executable, str(SCRIPT), "--null"],
        input=b"\x00".join(paths) + (b"\x00" if paths else b""),
        capture_output=True,
        timeout=30,
    )


class ClassifyPathTest(unittest.TestCase):
    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "classify_path_risk.py must exist")

    def test_ask_class_paths(self) -> None:
        for path in ASK_PATHS:
            with self.subTest(path=path):
                classification, reason = classify_path(path)
                self.assertEqual(classification, ASK, f"{path}: {reason}")
                self.assertTrue(reason)

    def test_ship_class_paths(self) -> None:
        for path in SHIP_PATHS:
            with self.subTest(path=path):
                classification, reason = classify_path(path)
                self.assertEqual(classification, SHIP, f"{path}: {reason}")

    def test_landing_gate_paths_are_exact_matches(self) -> None:
        """The gate machinery is ASK by exact path so a candidate cannot widen
        SHIP for itself; sibling scripts and workflows must not be swept in."""

        for path in (
            "scripts/classify_path_risk.py",
            "./scripts/check_gate_integrity.py",
            ".specify/gate-integrity.json",
        ):
            with self.subTest(path=path):
                classification, reason = classify_path(path)
                self.assertEqual(classification, ASK, f"{path}: {reason}")
                self.assertIn("landing gate", reason)
        for path in (
            "scripts/test_classify_path_risk.py",
            "scripts/check_gate_integrity_notes.py",
            "backend/app/services/account_service_helpers.py",
        ):
            with self.subTest(path=path):
                classification, _ = classify_path(path)
                self.assertEqual(classification, SHIP)

    def test_token_matching_is_exact_not_substring(self) -> None:
        """'secretary' must not match 'secret', 'immigration' not 'migration'."""

        for path in (
            "frontend/src/components/Secretary.tsx",
            "backend/app/services/immigration_notes.py",
            "frontend/src/components/Tokenizer.tsx",
        ):
            with self.subTest(path=path):
                classification, _ = classify_path(path)
                self.assertEqual(classification, SHIP)

    def test_classification_is_deterministic(self) -> None:
        for path in ASK_PATHS + SHIP_PATHS:
            self.assertEqual(classify_path(path), classify_path(path))


class ClassifyMainTest(unittest.TestCase):
    def test_all_ship_input_exits_zero(self) -> None:
        result = _run(["backend/app/services/tree_service.py", "docs/x.md"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHIP", result.stdout)
        self.assertNotIn("ASK\t", result.stdout)

    def test_any_ask_input_exits_nonzero_and_names_the_paths(self) -> None:
        result = _run(["docs/x.md", "backend/migrations/0002.sql"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/migrations/0002.sql", result.stdout + result.stderr)
        self.assertIn("reviewed PR", result.stderr)

    def test_empty_input_exits_zero(self) -> None:
        result = _run([])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blank_lines_are_ignored(self) -> None:
        result = _run(["", "  ", "feature.txt"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quoted_path_output_fails_closed_as_ask(self) -> None:
        """git quotes non-ASCII/special paths in newline mode (core.quotepath);
        a quoted listing cannot be classified reliably, so it must be ASK."""

        result = _run(['"\\303\\251vil.yml"'])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ASK", result.stdout)
        self.assertIn("NUL", result.stdout + result.stderr)

    def test_backslash_escaped_path_fails_closed_as_ask(self) -> None:
        result = _run(["docs\\notes.md"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("ASK", result.stdout)


class ClassifyNullModeTest(unittest.TestCase):
    """NUL-separated input is the machine-facing mode used by both the local
    submit preflight and the trusted promotion gate: it never quotes, so
    non-ASCII and otherwise unprintable paths classify on their real names."""

    def test_all_ship_input_exits_zero(self) -> None:
        result = _run_null([b"backend/app/services/tree_service.py", b"docs/x.md"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_ascii_data_path_is_ask(self) -> None:
        result = _run_null(["backend/data/évil.json".encode(), b"docs/x.md"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK", result.stdout)
        self.assertIn("évil.json".encode(), result.stdout)

    def test_rename_from_ask_path_lists_delete_and_add(self) -> None:
        """With --no-renames a rename appears as delete+add; the deleted ASK
        path must still fail the gate even when the new name is harmless."""

        result = _run_null([b"backend/data/tree_1.json", b"harmless.txt"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK\tbackend/data/tree_1.json", result.stdout)
        self.assertIn(b"SHIP\tharmless.txt", result.stdout)

    def test_empty_and_trailing_nul_input_exits_zero(self) -> None:
        self.assertEqual(_run_null([]).returncode, 0)
        self.assertEqual(_run_null([b"", b"feature.txt", b""]).returncode, 0)

    def test_undecodable_bytes_still_classify_by_prefix(self) -> None:
        """Invalid UTF-8 in an ASK-prefixed path must not crash or slip by."""

        result = _run_null([b"backend/data/\xff\xfe.json"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK", result.stdout)


if __name__ == "__main__":
    unittest.main()
