#!/usr/bin/env python3
"""Dry-run tests for scripts/fly_cutover.sh (027-FR-019).

A stateful fake ``flyctl`` is placed on PATH; no real Fly call is ever made.
The fake logs every invocation so the tests assert step order: the running
side is stopped and verified stopped before the other side starts.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("fly_cutover.sh")

FAKE_FLYCTL = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")

def app():
    return args[args.index("-a") + 1]

def save():
    json.dump(state, open(state_path, "w"))

cmd = " ".join(a for a in args[:3] if not a.startswith("-"))
if args[0] == "machines":
    n = state["machines"].get(app(), 0)
    print(json.dumps([{"id": "m%d" % i, "state": "started"} for i in range(n)]))
elif args[0] == "scale":
    spec = [a for a in args[2:] if "=" in a]
    n = sum(int(s.split("=")[1]) for s in spec) if spec else int(args[2])
    if not (app() in state.get("stuck", [])) or n != 0:
        state["machines"][app()] = n
    save()
elif args[0] == "deploy":
    if os.environ.get("FAKE_FAIL_DEPLOY") == app():
        sys.exit(1)
elif args[:2] == ["volumes", "list"]:
    print(json.dumps([{"id": v} for v in state["volumes"].get(app(), [])]))
elif args[:3] == ["volumes", "snapshots", "list"]:
    print(json.dumps([{"id": "snap-" + args[3]}]))
elif args[:2] == ["volumes", "destroy"]:
    state["volumes"][app()].remove(args[2])
    save()
elif args[:2] == ["apps", "destroy"]:
    state["apps"].remove(args[2])
    save()
elif args[:2] == ["apps", "list"]:
    print(json.dumps([{"Name": a} for a in state["apps"]]))
'''


class FlyCutoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "flyctl"
        fake.write_text(FAKE_FLYCTL)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.log = tmp / "calls.log"
        self.evidence = tmp / "evidence.log"
        self.state = tmp / "state.json"
        self.state.write_text(
            json.dumps(
                {
                    "machines": {"brain-buddy-backend": 1, "brain-buddy-api": 0},
                    "volumes": {"brain-buddy-backend": ["vol_1", "vol_fork"]},
                    "apps": ["brain-buddy-backend", "brain-buddy-api"],
                }
            )
        )
        self.env = {
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.state),
            "FAKE_LOG": str(self.log),
            "EVIDENCE_FILE": str(self.evidence),
            "VERIFY_ATTEMPTS": "2",
            "VERIFY_SLEEP": "0",
            "SMOKE_CMD": "true",
        }

    def run_script(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **extra}
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def index(self, prefix: str, start: int = 0) -> int:
        for i, c in enumerate(self.calls()):
            if i >= start and c.startswith(prefix):
                return i
        self.fail(f"no call starting {prefix!r} in {self.calls()}")

    def test_027_FR_019_cutover_stops_python_first_then_deploys(self) -> None:
        r = self.run_script("cutover")
        self.assertEqual(r.returncode, 0, r.stderr)
        stop = self.index("scale count 0 -a brain-buddy-backend")
        verify = self.index("machines list -a brain-buddy-backend", stop)
        deploy = self.index("deploy -c fly.api.toml -a brain-buddy-api")
        front = self.index("deploy -c fly.frontend.toml")
        self.assertLess(stop, verify)
        self.assertLess(verify, deploy)
        self.assertLess(deploy, front)
        self.assertIn("BACKEND_ORIGIN=https://brain-buddy-api.fly.dev", self.calls()[front])
        self.assertIn("scale count serve=1 worker=1", "\n".join(self.calls()))
        self.assertNotIn("destroy", "\n".join(self.calls()))
        self.assertIn("cutover-done", self.evidence.read_text())

    def test_027_FR_019_cutover_refuses_when_old_app_will_not_stop(self) -> None:
        state = json.loads(self.state.read_text())
        state["stuck"] = ["brain-buddy-backend"]
        self.state.write_text(json.dumps(state))
        r = self.run_script("cutover")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("deploy", "\n".join(self.calls()))

    def test_027_FR_019_failed_smoke_rolls_back_stop_first(self) -> None:
        r = self.run_script("cutover", SMOKE_CMD="false", ERASE_OLD="1")
        self.assertNotEqual(r.returncode, 0)
        calls = self.calls()
        smoke_fail = self.index("scale count serve=1")
        stop_new = self.index("scale count 0 -a brain-buddy-api", smoke_fail)
        verify = self.index("machines list -a brain-buddy-api", stop_new)
        origin_back = self.index("deploy -c fly.frontend.toml", verify)
        start_old = self.index("scale count 1 -a brain-buddy-backend", origin_back)
        self.assertIn("BACKEND_ORIGIN=https://brain-buddy-backend.fly.dev", calls[origin_back])
        self.assertLess(stop_new, start_old)
        self.assertNotIn("destroy", "\n".join(calls))
        self.assertEqual(json.loads(self.state.read_text())["machines"]["brain-buddy-backend"], 1)

    def test_027_FR_019_rollback_subcommand_is_stop_first(self) -> None:
        state = json.loads(self.state.read_text())
        state["machines"] = {"brain-buddy-backend": 0, "brain-buddy-api": 2}
        self.state.write_text(json.dumps(state))
        r = self.run_script("rollback")
        self.assertEqual(r.returncode, 0, r.stderr)
        stop = self.index("scale count 0 -a brain-buddy-api")
        start = self.index("scale count 1 -a brain-buddy-backend")
        self.assertLess(stop, start)
        self.assertLess(self.index("machines list -a brain-buddy-api", stop), start)

    def test_027_FR_019_erase_destroys_volumes_forks_and_app_with_listing(self) -> None:
        state = json.loads(self.state.read_text())
        state["volumes"]["other"] = ["vol_copy"]
        self.state.write_text(json.dumps(state))
        r = self.run_script(
            "erase",
            FORK_VOLUMES="other:vol_copy",
            OFFPLATFORM_COPIES="laptop-backup,s3-dump",
            OFFPLATFORM_CONFIRMED="1",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = "\n".join(self.calls())
        for expected in (
            "volumes destroy vol_1 -a brain-buddy-backend",
            "volumes destroy vol_fork -a brain-buddy-backend",
            "volumes destroy vol_copy -a other",
            "apps destroy brain-buddy-backend",
        ):
            self.assertIn(expected, calls)
        self.assertLess(
            self.index("scale count 0 -a brain-buddy-backend"),
            self.index("volumes destroy vol_1"),
        )
        self.assertLess(self.index("volumes destroy vol_1"), self.index("apps destroy"))
        ev = self.evidence.read_text()
        self.assertIn("snapshot-destroyed-with-volume volume=vol_1 snapshot=snap-vol_1", ev)
        self.assertIn("name=laptop-backup", ev)
        self.assertIn("final-listing app=brain-buddy-backend remaining=0", ev)
        self.assertEqual(
            json.loads(self.state.read_text())["apps"], ["brain-buddy-api"]
        )

    def test_027_FR_019_erase_blocks_on_unconfirmed_offplatform_copy(self) -> None:
        r = self.run_script("erase", OFFPLATFORM_COPIES="laptop-backup")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("destroy", "\n".join(self.calls()))

    def test_027_FR_019_cutover_with_erase_runs_erase_after_smoke(self) -> None:
        r = self.run_script("cutover", ERASE_OLD="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(
            self.index("deploy -c fly.frontend.toml"), self.index("volumes destroy vol_1")
        )

    def test_027_FR_019_unknown_subcommand_fails(self) -> None:
        self.assertNotEqual(self.run_script("bogus").returncode, 0)


if __name__ == "__main__":
    unittest.main()
