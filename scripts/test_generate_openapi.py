"""Tests for deterministic OpenAPI generation (spec 004 T011/T012).

Requires backend dependencies (FastAPI/Pydantic/...) on the interpreter's
path -- run via the backend virtualenv, e.g.:

    cd backend && python3 -m unittest ../scripts/test_generate_openapi.py -v

This mirrors ``make check-api-contract``/``make generate-openapi``, which
invoke this same module from ``backend/``.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any, cast

SCRIPT_PATH = Path(__file__).with_name("generate_openapi.py")
spec = importlib.util.spec_from_file_location("generate_openapi", SCRIPT_PATH)
assert spec is not None
generate_openapi = cast(Any, importlib.util.module_from_spec(spec))
assert spec.loader is not None
sys.modules["generate_openapi"] = generate_openapi
spec.loader.exec_module(generate_openapi)


class GenerateOpenapiTests(unittest.TestCase):
    def test_generation_is_deterministic_across_independent_runs(self) -> None:
        first = generate_openapi._dump(generate_openapi._generate_schema())
        second = generate_openapi._dump(generate_openapi._generate_schema())
        self.assertEqual(first, second)

    def test_generation_uses_ephemeral_app_and_contains_no_persisted_data(self) -> None:
        schema = generate_openapi._generate_schema()
        rendered = generate_openapi._dump(schema).lower()
        # No seeded/admin/test-fixture account or credential-like data may
        # leak into a document generated from an ephemeral app/data root.
        for leaked in (
            "primary@example.com",
            "secondary@example.com",
            "correct-horse-battery-staple",
            "user_test_owner",
        ):
            self.assertNotIn(leaked, rendered)

    def test_semantic_version_is_pinned(self) -> None:
        schema = generate_openapi._generate_schema()
        self.assertEqual(schema["info"]["version"], "1.0.0")

    def test_canonical_and_deprecated_brain_dump_routes_are_present(self) -> None:
        schema = generate_openapi._generate_schema()
        paths = schema["paths"]
        canonical = paths["/api/brain-dump-operations/{operation_id}/commands/{action}"]["post"]
        self.assertIsNot(canonical.get("deprecated"), True)
        bare_action = paths["/api/brain-dump-operations/{operation_id}/{action}"]["post"]
        self.assertTrue(bare_action.get("deprecated"))
        for path, method in (
            ("/api/brain-dump-operations/{operation_id}/commit", "post"),
            ("/api/brain-dump-operations/{operation_id}/finish", "post"),
            ("/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}", "patch"),
        ):
            self.assertTrue(paths[path][method].get("deprecated"), (path, method))

    def test_check_mode_via_cli_detects_drift_and_matches_when_clean(self) -> None:
        import subprocess

        clean = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(clean.returncode, 0, clean.stderr)

        original = generate_openapi.SNAPSHOT_PATH.read_bytes()
        try:
            generate_openapi.SNAPSHOT_PATH.write_text('{"drift": true}\n', encoding="utf-8")
            drifted = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--check"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(drifted.returncode, 0)
        finally:
            generate_openapi.SNAPSHOT_PATH.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
