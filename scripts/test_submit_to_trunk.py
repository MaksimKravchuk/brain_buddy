#!/usr/bin/env python3
"""Contract tests for the retired scripts/submit_to_trunk.sh (ADR-0035).

PR-less trunk-candidate landing is retired: every change lands as a pull
request through the merge queue. The script is kept only so stale callers
fail loudly. These tests run it inside a throwaway git repository with a
local bare "origin" and an otherwise valid candidate, and assert that it
fails fast, points at ADR-0035 and the merge-queue path, and pushes nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "submit_to_trunk.sh"


def _git_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "GIT_AUTHOR_NAME": "Contract Test",
        "GIT_AUTHOR_EMAIL": "contract-test@example.com",
        "GIT_COMMITTER_NAME": "Contract Test",
        "GIT_COMMITTER_EMAIL": "contract-test@example.com",
    }


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    )
    return result.stdout.strip()


class RetiredSubmitToTrunkScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        self.clone = base / "clone"
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(self.origin)],
            check=True,
            capture_output=True,
            env=_git_env(),
        )
        subprocess.run(
            ["git", "clone", str(self.origin), str(self.clone)],
            check=True,
            capture_output=True,
            env=_git_env(),
        )
        (self.clone / "README.md").write_text("hello\n", encoding="utf-8")
        _git(self.clone, "add", "README.md")
        _git(self.clone, "commit", "-m", "chore: initial commit")
        _git(self.clone, "push", "origin", "main")
        _git(self.clone, "checkout", "-b", "feature")

    def _valid_candidate(self) -> dict[str, str]:
        """One SHIP commit on current origin/main plus a matching receipt:
        everything the retired script used to accept."""

        (self.clone / "docs").mkdir()
        (self.clone / "docs" / "notes.md").write_text("notes\n", encoding="utf-8")
        _git(self.clone, "add", "docs/notes.md")
        _git(self.clone, "commit", "-m", "docs: notes")
        sha = _git(self.clone, "rev-parse", "HEAD")
        receipt = Path(self.tmp.name) / "pre-freeze-receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "contract": "brainbuddy.pre-freeze-writer-receipt/v1",
                    "implementation_sha": sha,
                    "inventory": ["docs/notes.md"],
                    "gates": [
                        {
                            "id": gate_id,
                            "status": "PASS",
                            "command": "test",
                            "observation": "passed",
                            "evidence": "captured",
                        }
                        for gate_id in (
                            "writer.tests",
                            "writer.verify_all",
                            "writer.path_classification",
                            "writer.diff_review",
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        env = _git_env()
        env["SUBMIT_TRUNK_SKIP_CHECKS"] = "1"
        env["SUBMIT_TRUNK_PRE_FREEZE_RECEIPT"] = str(receipt)
        return env

    def _run(self, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )

    def _origin_refs(self) -> dict[str, str]:
        out = _git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")
        refs: dict[str, str] = {}
        for line in out.splitlines():
            name, sha = line.split(" ", 1)
            refs[name] = sha
        return refs

    def test_script_is_kept_executable_and_never_pushes(self) -> None:
        self.assertTrue(SCRIPT.exists(), "submit_to_trunk.sh must be kept")
        self.assertTrue(os.access(SCRIPT, os.X_OK), "script must be executable")
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertIn("ADR-0035", text)
        self.assertNotIn("git push", text)
        self.assertNotIn("git fetch", text)
        self.assertNotIn("--force", text)

    def test_valid_candidate_fails_fast_and_pushes_nothing(self) -> None:
        refs_before = self._origin_refs()
        result = self._run(self.clone, self._valid_candidate())
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertEqual(self._origin_refs(), refs_before)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_failure_message_points_at_adr_and_merge_queue(self) -> None:
        result = self._run(self.clone, self._valid_candidate())
        message = result.stderr
        self.assertIn("retired", message)
        self.assertIn("docs/decisions/0035-merge-queue-pr-landing.md", message)
        self.assertIn("merge queue", message)
        self.assertIn("pull request", message)
        self.assertIn("Full CI", message)
        self.assertIn("Docker Images", message)
        self.assertIn("ASK", message)
        self.assertIn("Nothing was pushed", message)

    def test_fails_fast_outside_a_git_repository(self) -> None:
        outside = Path(self.tmp.name) / "not-a-repo"
        outside.mkdir()
        result = self._run(outside, _git_env())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ADR-0035", result.stderr)
        self.assertNotIn("not inside a git repository", result.stderr)


if __name__ == "__main__":
    unittest.main()
