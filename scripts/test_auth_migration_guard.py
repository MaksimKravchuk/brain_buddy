"""Identity migration must never roll back into JSON authority."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("auth_migration_guard.py")


class AuthMigrationGuardTests(unittest.TestCase):
    def _module(self):
        self.assertTrue(SCRIPT.is_file(), "Migration rollback guard must exist")
        spec = importlib.util.spec_from_file_location("auth_guard", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_023_SC_002_legacy_volume_can_restore_its_captured_image(self):
        guard = self._module()
        self.assertTrue(guard.restore_allowed(0, 0))

    def test_023_SC_002_sqlite_epoch_blocks_json_even_without_import(self):
        guard = self._module()
        self.assertFalse(guard.restore_allowed(1, 0))
        self.assertTrue(guard.restore_allowed(1, 1))
        self.assertFalse(guard.restore_allowed(2, 1))

    def test_023_SC_008_unknown_state_never_authorizes_restore(self):
        guard = self._module()
        for current, captured in [(None, 1), (1, None), (-1, 1), (True, 1)]:
            with self.subTest(current=current, captured=captured):
                self.assertFalse(guard.restore_allowed(current, captured))

    def test_023_SC_002_probe_reads_only_coarse_ledger_and_source_capability(self):
        guard = self._module()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            data = root / "data"
            data.mkdir()
            image = root / "auth_store.py"
            image.write_text("AUTH_SCHEMA_EPOCH = 1\n")
            db = data / "auth.sqlite3"
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TABLE auth_migration_ledger "
                    "(id INTEGER, schema_epoch INTEGER, import_committed INTEGER, "
                    "cleanup_complete INTEGER)"
                )
                connection.execute(
                    "INSERT INTO auth_migration_ledger VALUES (1, 1, 1, 1)"
                )
                connection.execute("CREATE TABLE users(secret TEXT)")
                connection.execute("INSERT INTO users VALUES ('private@example.test')")
            report = guard.probe_storage(data, image)
            self.assertEqual(
                report,
                {
                    "schema_epoch": 1,
                    "import_committed": True,
                    "cleanup_complete": True,
                    "image_schema_epoch": 1,
                },
            )
            self.assertNotIn("private", json.dumps(report))
            self.assertNotIn(str(data), json.dumps(report))
            with sqlite3.connect(db) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1
                )

    def test_023_SC_008_probe_unknown_database_or_forged_marker_fails_closed(self):
        guard = self._module()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            root.joinpath("auth.sqlite3").write_text("private malformed data")
            image = root / "marker.py"
            image.write_text("AUTH_SCHEMA_EPOCH = '1'\n")
            with self.assertRaises(guard.GuardError) as failure:
                guard.probe_storage(root, image)
            self.assertNotIn("private", str(failure.exception))
            self.assertNotIn(str(root), str(failure.exception))

    def test_023_SC_008_remote_probe_is_stdlib_and_emits_only_json(self):
        guard = self._module()
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run(
                [sys.executable, "-c", guard.remote_probe_source()],
                env={"BRAIN_BUDDY_DATA_DIR": root},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema_epoch"], 0)

    def test_023_SC_008_release_handler_guards_before_restaging_or_image_restore(self):
        source = SCRIPT.parent.parent.joinpath(
            ".github/workflows/deploy-fly-production.yml"
        ).read_text()
        handler = source.split("name: Roll back to the captured images and verify", 1)[
            1
        ]
        self.assertIn("auth_migration_guard.py restore", handler)
        self.assertLess(
            handler.index("auth_migration_guard.py restore"),
            handler.index("flyctl secrets set"),
        )
        self.assertIn("auth_migration_guard.py capture", source)
        self.assertIn("auth_migration_guard.py forward", source)

    def test_023_SC_002_commit_after_capture_blocks_real_restore_driver(self):
        guard = self._module()
        image = "registry.fly.io/brainbuddy-backend@sha256:" + "a" * 64
        machine = {"id": "0123456789abcd", "config": {"image": image}}
        before = {
            "schema_epoch": 0,
            "import_committed": False,
            "cleanup_complete": True,
            "image_schema_epoch": 0,
        }
        after = dict(before, schema_epoch=1, import_committed=True)
        with tempfile.TemporaryDirectory() as root:
            evidence = Path(root) / "capture.json"
            with patch.object(guard, "_fly", side_effect=[[machine], before]):
                guard.capture("brainbuddy-backend", image, evidence)
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
            with (
                patch.object(guard, "_fly", side_effect=[[machine], after]),
                self.assertRaises(guard.GuardError),
            ):
                guard.check("brainbuddy-backend", evidence)

    def test_023_SC_008_capture_rejects_image_mismatch_and_unknown_machine(self):
        guard = self._module()
        image = "registry.fly.io/brainbuddy-backend@sha256:" + "a" * 64
        for config in [None, {"image": image + "unexpected"}]:
            machine = {"id": "0123456789abcd", "config": config}
            with tempfile.TemporaryDirectory() as root:
                evidence = Path(root) / "capture.json"
                with (
                    patch.object(guard, "_fly", return_value=[machine]),
                    self.assertRaises(guard.GuardError),
                ):
                    guard.capture("brainbuddy-backend", image, evidence)
                self.assertFalse(evidence.exists())

    def test_023_SC_008_unknown_fresh_probe_blocks_compatible_capture(self):
        guard = self._module()
        image = "registry.fly.io/brainbuddy-backend@sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as root:
            evidence = Path(root) / "capture.json"
            evidence.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "app": "brainbuddy-backend",
                        "image": image,
                        "image_schema_epoch": 1,
                    }
                )
            )
            with patch.object(
                guard, "_fly", side_effect=guard.GuardError("Unavailable")
            ), self.assertRaises(guard.GuardError):
                guard.check("brainbuddy-backend", evidence)


if __name__ == "__main__":
    unittest.main()
