#!/usr/bin/env python3
"""Contract tests for the secret-leak guardrails.

Two defects are under test, both of which leave the scan reporting success on
exactly the change it exists to catch.

1. A secret scan that runs as its own workflow is ADVISORY for the landing
   path. BrainBuddy SHIP/SHOW candidates land through ``trunk-candidate/<sha>``
   and the only verdict the default-branch release workflow consumes is CI's
   ``Full CI`` join (ADR-0008), so a red standalone scan does not stop a
   candidate. The scan therefore has to be a job inside ``ci.yml``'s required
   graph -- called from ``secret-scan.yml`` so the checksum-pinned Gitleaks
   install stays defined once and runs once per event. The range logic is
   executed here for real, because a candidate ref is CREATED by the push that
   starts its run: ``github.event.before`` is the null SHA on that push, and a
   range derivation that fails closed on it makes the required job impossible
   to pass on the one path it must cover.

2. A Gitleaks allowlist keyed on a field name exempts the FIELD, not the
   fixture: replacing a synthetic value with a live credential leaves the field
   name untouched and the scan stays green. Worse, a global allowlist that
   names ``paths`` is applied as a path filter BEFORE any rule runs -- gitleaks
   8.30.1 skips the whole file and never evaluates ``condition`` or
   ``regexes``, so ``paths`` plus a narrow regex exempts every line of that
   file forever. Both shapes are rejected below.

Standard library only: this runs in the workflow-lint lane before any
dependency is installed.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"
SECRET_SCAN_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "secret-scan.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Substituted for the synthetic value on an allowlisted line to stand in for
#: "someone put a real credential here". Deliberately not credential-shaped:
#: the assertion is about the allowlist regex, and a high-entropy literal in
#: this file would be a finding of its own.
ROTATED_VALUE = "ROTATED-CREDENTIAL-PLACEHOLDER"

NULL_SHA = "0" * 40
RANGE_STEP = "Determine safe scan range"

#: The Gitleaks release the workflow is pinned to, by version AND by digest.
#: An unpinned or unverified download is a scan an attacker can replace.
PINNED_GITLEAKS = (
    "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/"
    "gitleaks_8.30.1_linux_x64.tar.gz"
)
PINNED_GITLEAKS_SHA256 = (
    "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
)


def _tracked_text_files() -> list[tuple[str, str]]:
    """Every tracked file that decodes as text, as (path, contents)."""

    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    files: list[tuple[str, str]] = []
    for name in listing.split("\0"):
        if not name:
            continue
        path = REPO_ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            files.append((name, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return files


def _rotate_last_literal(line: str) -> str:
    """The same line with the value of its last quoted literal replaced."""

    matches = list(re.finditer(r'"([^"]*)"', line))
    if not matches:
        return line
    last = matches[-1]
    return f'{line[: last.start()]}"{ROTATED_VALUE}"{line[last.end():]}'


def _top_level_block(text: str, key: str) -> str:
    """One top-level YAML mapping value, up to the next top-level key."""

    match = re.search(
        rf"^{re.escape(key)}:$(?P<body>.*?)(?=^[A-Za-z_][\w-]*:|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _job_needs(text: str, job: str) -> set[str]:
    block = re.search(
        rf"^  {re.escape(job)}:$(?P<body>.*?)(?=^  [a-z0-9-]+:$|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not block:
        return set()
    listed = re.search(
        r"^    needs:[ \t]*\n(?P<items>(?:^      - .+\n)+)",
        block.group("body"),
        flags=re.MULTILINE,
    )
    if not listed:
        return set()
    return {line.strip().removeprefix("- ").strip() for line in listed.group("items").splitlines() if line.strip()}


def _step_script(text: str, step_name: str) -> str:
    """The shell body of one named step, dedented so bash can run it."""

    marker = f"      - name: {step_name}\n"
    start = text.index(marker)
    body_at = text.index("        run: |\n", start) + len("        run: |\n")
    lines: list[str] = []
    for line in text[body_at:].splitlines(keepends=True):
        if line.strip() and not line.startswith("          "):
            break
        lines.append(line[10:] if line.startswith("          ") else "\n")
    return "".join(lines)


class GitleaksAllowlistTest(unittest.TestCase):
    """Each allowlist must exempt one known line, not a field or a file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
        cls.allowlists = cls.config.get("allowlists", [])
        cls.tracked = _tracked_text_files()

    def test_allowlists_exist(self) -> None:
        self.assertTrue(self.allowlists, "no [[allowlists]] found in .gitleaks.toml")
        self.assertNotIn(
            "allowlist",
            self.config,
            "a singular [allowlist] table is a second, unchecked exemption "
            "surface; keep every exemption in [[allowlists]]",
        )

    def test_no_allowlist_declares_paths(self) -> None:
        for entry in self.allowlists:
            with self.subTest(entry["description"]):
                self.assertNotIn(
                    "paths",
                    entry,
                    "a global allowlist naming `paths` is applied as a path "
                    "filter before any rule runs: gitleaks skips the whole "
                    "file and never evaluates `condition` or `regexes`, so "
                    "every line of that file is exempt forever. Pin the line "
                    "with `regexTarget = \"line\"` instead.",
                )

    def test_every_allowlist_pins_whole_lines(self) -> None:
        for entry in self.allowlists:
            with self.subTest(entry["description"]):
                self.assertEqual(entry.get("regexTarget"), "line")
                self.assertTrue(entry.get("regexes"), "an allowlist with no regex")
                for pattern in entry["regexes"]:
                    self.assertTrue(
                        pattern.startswith("^") and pattern.endswith("$"),
                        f"{pattern!r} is not anchored to a whole line",
                    )

    def test_every_allowlist_matches_a_real_fixture_line(self) -> None:
        """A pattern that matches nothing is a stale exemption nobody notices."""

        for entry in self.allowlists:
            for pattern in entry["regexes"]:
                with self.subTest(entry["description"], pattern=pattern):
                    compiled = re.compile(pattern)
                    hits = [
                        (name, line)
                        for name, text in self.tracked
                        for line in text.splitlines()
                        if compiled.search(line)
                    ]
                    self.assertTrue(
                        hits,
                        f"{pattern!r} matches no tracked line; delete the "
                        "exemption or repair it",
                    )

    def test_rotating_the_value_defeats_every_allowlist(self) -> None:
        """The whole point: a new value on an exempt line must be scanned."""

        compiled = [
            re.compile(pattern)
            for entry in self.allowlists
            for pattern in entry["regexes"]
        ]
        checked = 0
        for entry in self.allowlists:
            for pattern in entry["regexes"]:
                probe = re.compile(pattern)
                for _, text in self.tracked:
                    for line in text.splitlines():
                        if not probe.search(line):
                            continue
                        rotated = _rotate_last_literal(line)
                        self.assertNotEqual(
                            rotated, line, f"no quoted literal to rotate in {line!r}"
                        )
                        checked += 1
                        for other in compiled:
                            self.assertIsNone(
                                other.search(rotated),
                                f"{other.pattern!r} still exempts the line after "
                                "its value changed, so a real credential put "
                                "here would never be reported",
                            )
        self.assertGreaterEqual(checked, len(self.allowlists))


class SecretScanWorkflowTest(unittest.TestCase):
    """The scan must be reusable, pinned, and run exactly once per event."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SECRET_SCAN_WORKFLOW.read_text(encoding="utf-8")
        cls.triggers = _top_level_block(cls.text, "on")

    def test_is_callable_and_manually_dispatchable(self) -> None:
        self.assertIn("workflow_call:", self.triggers)
        self.assertIn("workflow_dispatch:", self.triggers)

    def test_no_duplicate_standalone_triggers(self) -> None:
        for trigger in ("pull_request", "push"):
            self.assertNotIn(
                trigger,
                self.triggers,
                f"a standalone {trigger} trigger scans the same ref a second "
                "time for one verdict; ci.yml already calls this workflow",
            )

    def test_gitleaks_install_stays_pinned_and_verified(self) -> None:
        self.assertIn(PINNED_GITLEAKS, self.text)
        self.assertIn(PINNED_GITLEAKS_SHA256, self.text)
        self.assertIn("sha256sum --check", self.text)

    def test_findings_are_redacted_and_least_privileged(self) -> None:
        self.assertNotIn("gitleaks git --verbose", self.text)
        self.assertEqual(self.text.count("gitleaks git --redact"), 2)
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("contents: write", self.text)


class RequiredGraphTest(unittest.TestCase):
    """Full CI is the only thing that makes a job required (ADR-0008)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = CI_WORKFLOW.read_text(encoding="utf-8")

    def test_ci_calls_the_secret_scan_workflow(self) -> None:
        self.assertIn("uses: ./.github/workflows/secret-scan.yml", self.text)

    def test_full_ci_requires_the_secret_scan(self) -> None:
        self.assertIn(
            "secret-scan",
            _job_needs(self.text, "full-ci"),
            "Full CI is the verdict the release workflow consumes; a scan "
            "missing from its needs cannot stop a leaking candidate landing",
        )

    def test_candidate_pushes_reach_the_scan(self) -> None:
        self.assertIn('branches: ["main", "trunk-candidate/**"]', self.text)


class ScanRangeTest(unittest.TestCase):
    """Run the range derivation for real; a candidate ref has no `before`."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _step_script(
            SECRET_SCAN_WORKFLOW.read_text(encoding="utf-8"), RANGE_STEP
        )
        cls._tmp = tempfile.TemporaryDirectory()
        repo = Path(cls._tmp.name) / "repo"
        repo.mkdir()
        run = lambda *args: subprocess.run(  # noqa: E731
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )
        run("init", "--quiet")
        run("config", "user.email", "test@example.invalid")
        run("config", "user.name", "Range Test")
        run("commit", "--quiet", "--allow-empty", "-m", "base")
        run("commit", "--quiet", "--allow-empty", "-m", "head")
        cls.repo = repo
        cls.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        cls.base = subprocess.run(
            ["git", "rev-parse", "HEAD~1"], cwd=repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _derive(self, **env: str) -> tuple[int, dict[str, str]]:
        with tempfile.NamedTemporaryFile("w+", delete=False) as handle:
            output = Path(handle.name)
        try:
            proc = subprocess.run(
                ["bash", "-c", self.script],
                cwd=self.repo,
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin",
                    "GITHUB_OUTPUT": str(output),
                    "PR_BASE": "",
                    "PUSH_BEFORE": "",
                    "EVENT_HEAD": "",
                    **env,
                },
            )
            parsed = dict(
                line.split("=", 1)
                for line in output.read_text().splitlines()
                if "=" in line
            )
            return proc.returncode, parsed
        finally:
            output.unlink(missing_ok=True)

    def test_created_candidate_ref_scans_full_history(self) -> None:
        """The regression: `before` is the null SHA on a candidate's push."""

        code, out = self._derive(
            EVENT_NAME="push", PUSH_BEFORE=NULL_SHA, EVENT_HEAD=self.head
        )
        self.assertEqual(code, 0, "a created ref must not fail the required scan")
        self.assertEqual(out.get("mode"), "full")

    def test_manual_dispatch_scans_full_history(self) -> None:
        code, out = self._derive(EVENT_NAME="workflow_dispatch")
        self.assertEqual(code, 0)
        self.assertEqual(out.get("mode"), "full")

    def test_push_derives_the_incremental_range(self) -> None:
        code, out = self._derive(
            EVENT_NAME="push", PUSH_BEFORE=self.base, EVENT_HEAD=self.head
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.get("mode"), "range")
        self.assertEqual(out.get("log_opts"), f"{self.base}..{self.head}")

    def test_pull_request_derives_the_incremental_range(self) -> None:
        code, out = self._derive(
            EVENT_NAME="pull_request", PR_BASE=self.base, EVENT_HEAD=self.head
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.get("mode"), "range")
        self.assertEqual(out.get("log_opts"), f"{self.base}..{self.head}")

    def test_unsafe_ranges_fail_closed(self) -> None:
        cases = {
            "unsupported event": {"EVENT_NAME": "schedule"},
            "malformed base": {
                "EVENT_NAME": "push",
                "PUSH_BEFORE": "not-a-sha",
                "EVENT_HEAD": self.head,
            },
            "unknown commit": {
                "EVENT_NAME": "push",
                "PUSH_BEFORE": "f" * 40,
                "EVENT_HEAD": self.head,
            },
            "base is not an ancestor": {
                "EVENT_NAME": "push",
                "PUSH_BEFORE": self.head,
                "EVENT_HEAD": self.base,
            },
        }
        for label, env in cases.items():
            with self.subTest(label):
                code, out = self._derive(**env)
                self.assertNotEqual(code, 0, "an unsafe range must fail the scan")
                self.assertNotIn("mode", out)


if __name__ == "__main__":
    unittest.main()
