#!/usr/bin/env python3
"""Automated rehearsal driver for the Apple pilot scenarios (spec 026, S1).

``python3 scripts/rehearsal/run.py [--target local|prod]``. Results go to
``specs/026-rust-core-sync/evidence/rehearsal-<date>.md``; rehearsal results are
NOT reference-device evidence and never edit ``apple-pilot.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence  # noqa: E402
import scenarios  # noqa: E402
from client import Api, LocalBackend  # noqa: E402
from guard import (  # noqa: E402
    PROD_HOSTS,
    PROD_REQUEST_BUDGET,
    GuardError,
    RequestBudget,
    check_capabilities,
    check_identity,
    check_prod_preconditions,
)

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO / "specs" / "026-rust-core-sync" / "evidence"
KEYCHAIN_SERVICE = "brainbuddy-rehearsal"

DEVICE_ONLY = {
    "Q01": (
        "offline capture",
        "needs real phone/Mac clients (airplane mode, kill/reopen)",
    ),
    "Q02": ("concurrent edits", "needs two native devices and the conflict UI"),
    "Q03": (
        "delivery faults",
        "needs process-kill fault injection in a native client; covered by cargo/pytest suites",
    ),
    "Q04": (
        "reset with live edits",
        "needs a native client capturing during snapshot paging",
    ),
    "Q06": ("import", "needs the legacy Apple stores and the native import path"),
    "Q09": ("AI", "needs on-device models; paid providers are out of scope"),
    "Q12": ("user recovery", "needs human participants and VoiceOver"),
}


def keychain_password(name: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            name,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise GuardError(f"no Keychain item {KEYCHAIN_SERVICE}/{name}")
    return done.stdout.strip()


def prod_context(base_url: str, run_id: str) -> scenarios.Ctx:
    check_prod_preconditions("prod", base_url)
    emails = {n: os.environ.get(f"BB_REHEARSAL_EMAIL_{n}", "") for n in ("A", "B")}
    if not all(emails.values()):
        raise GuardError("set BB_REHEARSAL_EMAIL_A and BB_REHEARSAL_EMAIL_B")
    api = Api(base_url, RequestBudget(PROD_REQUEST_BUDGET), prod=True)
    accts: dict[str, scenarios.Acct] = {}
    for name, email in emails.items():
        acct = scenarios.Acct(name, email, keychain_password(name), "")
        login = scenarios._login(api, acct)
        if login.status != 200 or not acct.cookie:
            raise GuardError(f"login for {name} answered {login.status}")
        me = api.call("GET", "/api/auth/me", acct.cookie)
        body = me.json() or {}
        check_identity(me.status, body.get("email"), {emails[name].lower()})
        acct.owner_id = body["id"]
        caps = api.call(
            "GET", f"/api/sync/v1/capabilities?scope_id={acct.owner_id}", acct.cookie
        )
        check_capabilities(caps.status, caps.json())
        accts[name] = acct
    return scenarios.Ctx(api, accts, run_id, prod=True)


def local_context(root: Path, run_id: str) -> tuple[scenarios.Ctx, LocalBackend]:
    server = LocalBackend(root / "main", "on")
    return scenarios._fresh_ctx(server.start(), run_id), server


def guarded(fn: Any, *args: Any) -> dict[str, Any]:
    try:
        out: dict[str, Any] = fn(*args)
        return out
    except GuardError:
        raise
    except Exception as exc:  # noqa: BLE001 - a crashed scenario is a FAIL, not a pass
        name = getattr(fn, "__name__", "scenario").upper()
        return scenarios.result(name, "crashed", "FAIL", f"{type(exc).__name__}: {exc}")


def run(target: str, base_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_id = uuid.uuid4().hex[:8]
    date, stamp = evidence.stamp()
    results: list[dict[str, Any]] = []
    server: LocalBackend | None = None
    root = Path(tempfile.mkdtemp(prefix="bb-rehearsal-"))
    try:
        if target == "prod":
            ctx = prod_context(base_url, run_id)
        else:
            ctx, server = local_context(root, run_id)
        try:
            results += [
                guarded(s, ctx) for s in (scenarios.q05, scenarios.q07, scenarios.q11)
            ]
        finally:
            cleaned = ctx.cleanup()
            for acct in ctx.accts.values():
                ctx.api.call("POST", "/api/auth/logout", acct.cookie)
        results.append(
            scenarios.result("CLEANUP", "rehearsal data removed", "PASS", str(cleaned))
        )
        requests = ctx.api.budget.used
        if server:
            server.stop()
            server = None
        local_only = "prod: local-only scenario (needs data-dir/CLI access)"
        if target == "local":
            for fn in (scenarios.q08, scenarios.q10, scenarios.cutover):
                results.append(guarded(fn, root, run_id))
        else:
            for sid, title in (
                ("Q08", "jobs and restore"),
                ("Q10", "retention"),
                ("CUTOVER", "cutover drill"),
            ):
                results.append(scenarios.not_automated(sid, title, local_only))
        for sid, (title, why) in DEVICE_ONLY.items():
            results.append(scenarios.not_automated(sid, title, why))
    finally:
        if server:
            server.stop()
        if not os.environ.get("BB_REHEARSAL_KEEP"):
            shutil.rmtree(root, ignore_errors=True)
    results.sort(key=lambda r: r["id"])
    identity = {
        "date": date,
        "target": target,
        "git_sha": os.environ.get("BB_REHEARSAL_GIT_SHA")
        or evidence.read_git_sha(REPO),
        "machine": evidence.MACHINE,
        "timestamp": stamp,
        "run_id": run_id,
        "requests": requests,
    }
    return results, identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "prod"), default="local")
    parser.add_argument("--base-url", default=f"https://{sorted(PROD_HOSTS)[0]}")
    parser.add_argument("--out-dir", type=Path, default=EVIDENCE_DIR)
    args = parser.parse_args(argv)
    try:
        results, identity = run(args.target, args.base_url)
    except GuardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    path = evidence.write(results, identity, args.out_dir)
    print(json.dumps({r["id"]: r["status"] for r in results}))
    print(f"evidence: {path}")
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
