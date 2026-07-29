#!/usr/bin/env python3
"""Deterministic contract tests for scripts/submit_to_trunk.sh.

Runs the real script inside throwaway git repositories with a local bare
"origin" so the candidate-submission contract (clean tree, current base,
single commit, unique trunk-candidate ref, no force pushes, never main)
is verified offline.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "submit_to_trunk.sh"


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


def _git_env() -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "GIT_AUTHOR_NAME": "Contract Test",
        "GIT_AUTHOR_EMAIL": "contract-test@example.com",
        "GIT_COMMITTER_NAME": "Contract Test",
        "GIT_COMMITTER_EMAIL": "contract-test@example.com",
    }
    return env


class SubmitToTrunkScriptTest(unittest.TestCase):
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

    def _commit(self, name: str, content: str = "change\n") -> str:
        path = self.clone / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(self.clone, "add", name)
        _git(self.clone, "commit", "-m", f"feat: {name}")
        return _git(self.clone, "rev-parse", "HEAD")

    def _run(self, env_overrides: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess[str]:
        env = _git_env()
        env["SUBMIT_TRUNK_SKIP_CHECKS"] = "1"
        env.update(env_overrides or {})
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.clone,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def _origin_refs(self) -> dict[str, str]:
        out = _git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")
        refs: dict[str, str] = {}
        for line in out.splitlines():
            name, sha = line.split(" ", 1)
            refs[name] = sha
        return refs

    def test_script_never_force_pushes_or_targets_main(self) -> None:
        self.assertTrue(SCRIPT.exists(), "submit_to_trunk.sh must exist")
        self.assertTrue(os.access(SCRIPT, os.X_OK), "script must be executable")
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertNotIn("--force", text)
        self.assertNotIn("push -f", text)
        self.assertNotIn("refs/heads/main", text.replace("refuse", ""))

    def test_happy_path_pushes_unique_candidate_ref(self) -> None:
        sha = self._commit("feature.txt")
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        refs = self._origin_refs()
        candidate_ref = f"refs/heads/trunk-candidate/{sha}"
        self.assertIn(candidate_ref, refs)
        self.assertEqual(refs[candidate_ref], sha)
        self.assertIn(f"trunk-candidate/{sha}", combined)
        # main is untouched by submission
        self.assertNotEqual(refs["refs/heads/main"], sha)

    def test_dirty_working_tree_fails_closed(self) -> None:
        self._commit("feature.txt")
        (self.clone / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_no_new_commit_fails_closed(self) -> None:
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_multi_commit_series_fails_closed(self) -> None:
        self._commit("one.txt")
        self._commit("two.txt")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one commit", result.stdout + result.stderr)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_stale_base_fails_closed(self) -> None:
        self._commit("feature.txt")
        # Advance origin/main from a second clone so the candidate is stale.
        other = Path(self.tmp.name) / "other"
        subprocess.run(
            ["git", "clone", str(self.origin), str(other)],
            check=True,
            capture_output=True,
            env=_git_env(),
        )
        (other / "mainline.txt").write_text("moved\n", encoding="utf-8")
        _git(other, "add", "mainline.txt")
        _git(other, "commit", "-m", "feat: mainline moved")
        _git(other, "push", "origin", "main")

        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin/main", result.stdout + result.stderr)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_merge_commit_fails_closed(self) -> None:
        self._commit("feature.txt")
        _git(self.clone, "checkout", "-b", "side", "origin/main")
        (self.clone / "side.txt").write_text("side\n", encoding="utf-8")
        _git(self.clone, "add", "side.txt")
        _git(self.clone, "commit", "-m", "feat: side")
        _git(self.clone, "checkout", "feature")
        _git(self.clone, "merge", "--no-ff", "-m", "merge side", "side")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_ask_class_workflow_path_fails_closed(self) -> None:
        """The Ship/Show/Ask gate is mechanical and not skippable: an
        ASK-class path fails the submission even with fast checks skipped
        (the default in these tests) and pushes nothing."""

        self._commit(".github/workflows/evil.yml", "on: push\n")
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ASK", combined)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_ask_class_auth_path_fails_closed(self) -> None:
        self._commit("backend/app/api/auth.py", "# auth surface\n")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ASK", result.stdout + result.stderr)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_non_ascii_ask_workflow_path_fails_closed(self) -> None:
        """git quotes non-ASCII paths in newline output; the gate must use
        NUL-separated listing so the real path still classifies as ASK."""

        self._commit(".github/workflows/évil.yml", "on: push\n")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ASK", result.stdout + result.stderr)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_rename_of_ask_path_to_harmless_name_fails_closed(self) -> None:
        """A rename must classify as delete+add (--no-renames): removing an
        ASK-class workflow is itself an ASK change even when the new path is
        harmless."""

        _git(self.clone, "checkout", "main")
        workflow = self.clone / ".github" / "workflows" / "deploy.yml"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("on: push\n", encoding="utf-8")
        _git(self.clone, "add", ".github/workflows/deploy.yml")
        _git(self.clone, "commit", "-m", "ci: add workflow")
        _git(self.clone, "push", "origin", "main")
        _git(self.clone, "checkout", "-B", "feature", "main")
        _git(self.clone, "mv", ".github/workflows/deploy.yml", "harmless.txt")
        _git(self.clone, "commit", "-m", "refactor: rename workflow away")

        result = self._run()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ASK", combined)
        self.assertIn(".github/workflows/deploy.yml", combined)
        self.assertNotIn("trunk-candidate", "".join(self._origin_refs()))

    def test_ship_class_docs_path_is_submitted(self) -> None:
        sha = self._commit("docs/notes.md", "notes\n")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"refs/heads/trunk-candidate/{sha}", self._origin_refs())

    def test_resubmitting_same_sha_is_idempotent(self) -> None:
        self._commit("feature.txt")
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self._run()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)


if __name__ == "__main__":
    unittest.main()
