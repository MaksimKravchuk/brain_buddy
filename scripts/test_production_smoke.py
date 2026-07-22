#!/usr/bin/env python3
"""Deterministic contract tests for scripts/production_smoke.sh.

Runs the real script against a local in-process stub of the production API so
the contract (login, /auth/me flag payload, temp-tree lifecycle, cleanup
verification, logout, credential redaction) is verified offline without
touching production.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "production_smoke.sh"

SMOKE_EMAIL = "smoke-user@example.com"
SMOKE_PASSWORD = "super-secret-smoke-password"
SESSION_TOKEN = "stub-session-token-value"


class _StubState:
    """Mutable per-server state describing the stubbed backend."""

    def __init__(self) -> None:
        self.trees: dict[str, dict[str, str]] = {}
        self.logged_in = False
        self.include_feature_flags = True
        self.canary_enabled = True
        self.fail_delete = False
        self.fail_tree_read = False
        self.requests: list[str] = []


class _StubHandler(BaseHTTPRequestHandler):
    state: _StubState

    def log_message(self, *args: object) -> None:  # silence stderr noise
        pass

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _send(self, status: int, payload: dict[str, object] | None = None,
              set_cookie: str | None = None) -> None:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie is not None:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authed(self) -> bool:
        cookies = self.headers.get("Cookie") or ""
        return self.state.logged_in and SESSION_TOKEN in cookies

    def _me_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"id": "user_1", "email": SMOKE_EMAIL}
        if self.state.include_feature_flags:
            payload["feature_flags"] = {"delivery_canary": self.state.canary_enabled}
        return payload

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        self.state.requests.append(f"POST {self.path}")
        if self.path == "/api/auth/login":
            body = self._body()
            if (
                body.get("email") == SMOKE_EMAIL
                and body.get("password") == SMOKE_PASSWORD
            ):
                self.state.logged_in = True
                self._send(
                    200,
                    self._me_payload(),
                    set_cookie=f"brainbuddy_session={SESSION_TOKEN}; Path=/",
                )
            else:
                self._send(401, {"detail": "Invalid credentials."})
        elif self.path == "/api/auth/logout":
            self.state.logged_in = False
            self._send(204)
        elif self.path == "/api/trees":
            if not self._authed():
                self._send(401, {"detail": "Authentication required."})
                return
            name = str(self._body().get("name", ""))
            tree_id = f"tree_{len(self.state.trees) + 1}"
            self.state.trees[tree_id] = {"id": tree_id, "name": name}
            self._send(201, {"id": tree_id, "name": name})
        else:
            self._send(404, {"detail": "Not found."})

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.state.requests.append(f"GET {self.path}")
        if self.path == "/api/auth/me":
            if self._authed():
                self._send(200, self._me_payload())
            else:
                self._send(401, {"detail": "Authentication required."})
        elif self.path.startswith("/api/trees/"):
            tree_id = self.path.rsplit("/", 1)[-1]
            if not self._authed():
                self._send(401, {"detail": "Authentication required."})
            elif tree_id in self.state.trees:
                if self.state.fail_tree_read:
                    self._send(500, {"detail": "Injected read failure."})
                else:
                    self._send(
                        200,
                        {**self.state.trees[tree_id], "nodes": [], "relations": []},
                    )
            else:
                self._send(404, {"detail": "Tree not found."})
        else:
            self._send(404, {"detail": "Not found."})

    def do_DELETE(self) -> None:  # noqa: N802 - http.server API
        self.state.requests.append(f"DELETE {self.path}")
        if self.path.startswith("/api/trees/"):
            tree_id = self.path.rsplit("/", 1)[-1]
            if not self._authed():
                self._send(401, {"detail": "Authentication required."})
            elif tree_id in self.state.trees:
                if not self.state.fail_delete:
                    del self.state.trees[tree_id]
                self._send(204)
            else:
                self._send(404, {"detail": "Tree not found."})
        else:
            self._send(404, {"detail": "Not found."})


class ProductionSmokeScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = _StubState()
        handler = type("Handler", (_StubHandler,), {"state": self.state})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _run(self, env_overrides: dict[str, str | None] | None = None
             ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "BRAIN_BUDDY_SMOKE_EMAIL": SMOKE_EMAIL,
            "BRAIN_BUDDY_SMOKE_PASSWORD": SMOKE_PASSWORD,
            "SMOKE_BASE_URL": self.base_url,
            "SMOKE_RETRY_DELAY_SECONDS": "0",
        }
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(
            ["bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def test_script_is_executable_and_never_prints_secrets(self) -> None:
        self.assertTrue(SCRIPT.exists(), "production_smoke.sh must exist")
        self.assertTrue(os.access(SCRIPT, os.X_OK), "script must be executable")
        script_text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", script_text)
        self.assertIn("trap", script_text, "must clean up its temp files via trap")
        self.assertNotIn("--verbose", script_text)

    def test_happy_path_creates_and_cleans_up_tree(self) -> None:
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertEqual(self.state.trees, {}, "temporary tree must be deleted")
        self.assertFalse(self.state.logged_in, "session must be logged out")
        self.assertIn("GET /api/auth/me", self.state.requests)
        deletes = [r for r in self.state.requests if r.startswith("DELETE /api/trees/")]
        self.assertEqual(len(deletes), 1)
        # Cleanup verification must re-read the deleted tree.
        delete_index = self.state.requests.index(deletes[0])
        tree_path = deletes[0].split(" ", 1)[1]
        self.assertIn(f"GET {tree_path}", self.state.requests[delete_index:])

    def test_output_never_contains_credentials_or_session_cookie(self) -> None:
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertNotIn(SMOKE_PASSWORD, combined)
        self.assertNotIn(SESSION_TOKEN, combined)

    def test_missing_credentials_fail_closed_before_any_request(self) -> None:
        for missing in ("BRAIN_BUDDY_SMOKE_EMAIL", "BRAIN_BUDDY_SMOKE_PASSWORD"):
            with self.subTest(missing=missing):
                self.state.requests.clear()
                result = self._run({missing: None})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stdout + result.stderr)
                self.assertNotIn(SMOKE_PASSWORD, result.stdout + result.stderr)
                self.assertEqual(self.state.requests, [])

    def test_wrong_credentials_fail_closed(self) -> None:
        result = self._run({"BRAIN_BUDDY_SMOKE_PASSWORD": "wrong-password-value"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("wrong-password-value", result.stdout + result.stderr)

    def test_missing_feature_flag_payload_fails(self) -> None:
        self.state.include_feature_flags = False
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("feature_flags", result.stdout + result.stderr)

    def test_disabled_delivery_canary_fails(self) -> None:
        """A bool map alone is not enough: the canary must be effectively on."""

        self.state.canary_enabled = False
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("delivery_canary", result.stdout + result.stderr)

    def test_required_flag_is_overridable(self) -> None:
        result = self._run({"SMOKE_REQUIRED_FLAG": "not_a_real_flag"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not_a_real_flag", result.stdout + result.stderr)

    def test_unverified_tree_deletion_fails_and_trap_retries_delete(self) -> None:
        """When the DELETE is accepted but the follow-up GET does not confirm
        404, the run must fail AND the EXIT trap must retry the DELETE: the
        cleanup is only proven once the 404 read-back succeeds."""

        self.state.fail_delete = True
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, "must fail when cleanup unverified")
        self.assertIn("cleanup verification failed", combined)
        deletes = [
            r for r in self.state.requests if r.startswith("DELETE /api/trees/")
        ]
        self.assertEqual(
            len(deletes), 2, f"trap must retry the DELETE: {self.state.requests}"
        )

    def test_interrupted_smoke_still_sends_cleanup_delete(self) -> None:
        """A failure after tree creation must still best-effort DELETE the tree
        from the EXIT trap, without masking the original failure or leaking
        secrets."""

        self.state.fail_tree_read = True
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        # The original failure stays the reported one.
        self.assertIn("not readable", combined)
        deletes = [
            r for r in self.state.requests if r.startswith("DELETE /api/trees/")
        ]
        self.assertEqual(len(deletes), 1, self.state.requests)
        self.assertEqual(
            self.state.trees, {}, "trap cleanup must delete the temporary tree"
        )
        self.assertNotIn(SMOKE_PASSWORD, combined)
        self.assertNotIn(SESSION_TOKEN, combined)

    def test_trap_cleanup_failure_never_masks_the_original_failure(self) -> None:
        """Even when the best-effort DELETE cannot remove the tree, the run
        still fails with the original error."""

        self.state.fail_tree_read = True
        self.state.fail_delete = True
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not readable", combined)
        self.assertNotIn(SMOKE_PASSWORD, combined)


if __name__ == "__main__":
    unittest.main()
