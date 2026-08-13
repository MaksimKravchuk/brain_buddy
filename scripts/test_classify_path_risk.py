#!/usr/bin/env python3
"""Contract tests for scripts/classify_path_risk.py.

The classifier is the mechanical Ship/Show/Ask gate (ADR-0008): a PR-less
trunk candidate must fail closed before any push when its changed paths touch
ASK-class surfaces (CI/workflows, delivery scripts, Fly/Docker/deploy config,
auth/session/user/invite code, migrations/destructive persistence, or
secrets/permissions surfaces). Ambiguity fails toward ASK; documentation-only
paths are SHIP.
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
    # CI / workflow surface
    ".github/workflows/ci.yml",
    ".github/workflows/deploy-fly-production.yml",
    ".github/actions/anything/action.yml",
    # Delivery / CI scripts (the whole scripts/ tree is CI-executed tooling)
    "scripts/submit_to_trunk.sh",
    "scripts/production_smoke.sh",
    "scripts/classify_path_risk.py",
    "scripts/new_helper.py",
    "Makefile",
    # Fly / Docker / deploy configuration
    "fly.backend.toml",
    "fly.frontend.toml",
    "backend/Dockerfile",
    "frontend/Dockerfile",
    "docker-compose.yml",
    "compose.yaml",
    ".dockerignore",
    "deploy/nginx.conf",
    ".env.example",
    "mobile/eas.json",
    # Auth / session / user / invite code
    "backend/app/api/auth.py",
    "backend/app/schemas/auth.py",
    "backend/app/services/session_service.py",
    "backend/app/repositories/user_repository.py",
    "backend/tests/test_auth.py",
    "frontend/src/components/LoginForm.tsx",
    "frontend/src/api/useSignup.ts",
    # API modules that wire session auth and per-owner privacy enforcement:
    # their names carry no auth token, so they are explicit ASK paths.
    "backend/app/api/dependencies.py",
    "backend/app/api/middleware.py",
    "backend/app/api/routes.py",
    "backend/app/api/tasks.py",
    # Migrations / destructive persistence
    "backend/migrations/0001_init.sql",
    "backend/alembic/env.py",
    "backend/data/tree_1.json",
    # Secrets / permissions surfaces
    "backend/app/core/secrets.py",
    "infra/permissions/policy.json",
)

SHIP_PATHS = (
    "backend/app/services/tree_service.py",
    "backend/app/modules/tasks/service.py",
    "backend/tests/test_tree_service.py",
    # Sibling API modules stay SHIP: the privacy-enforcement ASK list is
    # exact paths, not the whole backend/app/api/ tree.
    "backend/app/api/errors.py",
    "backend/app/api/contracts.py",
    "frontend/src/components/TreeCanvas.tsx",
    "frontend/src/stores/treeStore.ts",
    "feature.txt",
    # Documentation is SHIP even when it talks about risky topics: it cannot
    # change runtime or CI behavior.
    "README.md",
    "docs/auth.md",
    "docs/decisions/0008-verified-trunk-serial-landing.md",
    "specs/004-verified-trunk-delivery/spec.md",
    "docs/user-guide.md",
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

    def test_api_privacy_enforcement_paths_are_exact_matches(self) -> None:
        """The four wired auth/per-owner enforcement modules are ASK by exact
        path; lookalike names elsewhere must not be swept in."""

        for path in (
            "backend/app/api/dependencies.py",
            "backend/app/api/middleware.py",
            "backend/app/api/routes.py",
            "backend/app/api/tasks.py",
            "./backend/app/api/middleware.py",
        ):
            with self.subTest(path=path):
                classification, reason = classify_path(path)
                self.assertEqual(classification, ASK, f"{path}: {reason}")
                self.assertIn("privacy", reason)
        for path in (
            "backend/app/api/tasks_helpers.py",
            "frontend/src/api/routes.ts",
            "docs/api/routes-py.md",
        ):
            with self.subTest(path=path):
                classification, _ = classify_path(path)
                self.assertEqual(classification, SHIP)

    def test_eas_release_configuration_is_ask(self) -> None:
        classification, reason = classify_path("mobile/eas.json")
        self.assertEqual(classification, ASK)
        self.assertIn("mobile release", reason)

    def test_token_matching_is_exact_not_substring(self) -> None:
        """'useTreeStore' must not match 'user', 'usership' must not match, etc."""

        for path in (
            "frontend/src/stores/useTreeStore.ts",
            "backend/app/services/authoring_notes.py",
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
        result = _run(["docs/x.md", ".github/workflows/ci.yml"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(".github/workflows/ci.yml", result.stdout + result.stderr)
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

    def test_non_ascii_workflow_path_is_ask(self) -> None:
        result = _run_null([".github/workflows/évil.yml".encode(), b"docs/x.md"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK", result.stdout)
        self.assertIn("évil.yml".encode(), result.stdout)

    def test_rename_from_ask_path_lists_delete_and_add(self) -> None:
        """With --no-renames a rename appears as delete+add; the deleted ASK
        path must still fail the gate even when the new name is harmless."""

        result = _run_null([b".github/workflows/deploy.yml", b"harmless.txt"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK\t.github/workflows/deploy.yml", result.stdout)
        self.assertIn(b"SHIP\tharmless.txt", result.stdout)

    def test_empty_and_trailing_nul_input_exits_zero(self) -> None:
        self.assertEqual(_run_null([]).returncode, 0)
        self.assertEqual(_run_null([b"", b"feature.txt", b""]).returncode, 0)

    def test_undecodable_bytes_still_classify_by_prefix(self) -> None:
        """Invalid UTF-8 in an ASK-prefixed path must not crash or slip by."""

        result = _run_null([b".github/workflows/\xff\xfe.yml"])
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"ASK", result.stdout)


if __name__ == "__main__":
    unittest.main()
