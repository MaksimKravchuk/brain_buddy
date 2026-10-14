"""Rehearsal scenarios Q05, Q07, Q11 (any target) and Q08/Q10/cutover (local)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from client import Api, LocalBackend, Resp, run_cli
from guard import RequestBudget

SCOPE_VERSION = 1


@dataclass
class Acct:
    name: str
    email: str
    password: str
    cookie: str
    owner_id: str = ""


@dataclass
class Ctx:
    api: Api
    accts: dict[str, Acct]
    run_id: str
    prod: bool
    created: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        return f"rehearsal-{self.run_id}"

    def rest(
        self, who: str, method: str, path: str, body: Any = None, key: bool = True
    ) -> Resp:
        headers = {"Idempotency-Key": str(uuid.uuid4())} if key else {}
        return self.api.call(method, path, self.accts[who].cookie, body, headers)

    def make(self, who: str, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        path = {"task": "/api/tasks", "project": "/api/projects", "tag": "/api/tags"}
        resp = self.rest(who, "POST", path[kind], body)
        data = resp.json() or {}
        if resp.status != 201:
            raise RuntimeError(f"create {kind} answered {resp.status}")
        self.created.append((who, kind, data["id"]))
        return dict(data)

    def cleanup(self) -> dict[str, int]:
        """Cancel tasks, archive projects, delete tags through the normal API."""
        done: dict[str, int] = {}
        for who, kind, ident in reversed(self.created):
            base = f"/api/{kind}s/{ident}"
            current = (self.rest(who, "GET", base, key=False).json() or {}).get(
                "revision"
            )
            if current is None:
                continue
            if kind == "task":
                r = self.rest(
                    who,
                    "POST",
                    base + "/transitions",
                    {"action": "cancel", "expected_revision": current},
                )
            elif kind == "project":
                r = self.rest(
                    who, "POST", base + "/archive", {"expected_revision": current}
                )
            else:
                r = self.rest(who, "DELETE", f"{base}?expected_revision={current}")
            done[f"{kind}:{r.status}"] = done.get(f"{kind}:{r.status}", 0) + 1
        return done


def result(
    sid: str, title: str, status: str, summary: str, **extra: Any
) -> dict[str, Any]:
    return {"id": sid, "title": title, "status": status, "summary": summary, **extra}


def not_automated(sid: str, title: str, reason: str) -> dict[str, Any]:
    return result(sid, title, "NOT_AUTOMATED", reason, reason=reason)


def normalize(body: Any, *redact: str) -> Any:
    """Drop correlation IDs and redact requested identifiers from a body."""
    text = json.dumps(body, sort_keys=True)
    text = re.sub(r'"(correlation_id|reference_id)": "[^"]*"', r'"\1": "<CID>"', text)
    for value in redact:
        text = text.replace(value, "<ID>")
    return json.loads(text)


def snapshot(ctx: Ctx, who: str) -> Resp:
    return ctx.api.call(
        "POST",
        "/api/sync/v1/snapshots",
        ctx.accts[who].cookie,
        {
            "scope_id": ctx.accts[who].owner_id,
            "projection_schema_version": SCOPE_VERSION,
        },
    )


def _isolation_probes(
    ctx: Ctx, viewer: str, owner: str
) -> list[tuple[str, Resp, Resp, str, str]]:
    """(probe, foreign response, unknown response, foreign id, unknown id)."""
    v, o = ctx.accts[viewer], ctx.accts[owner]
    task = ctx.make(owner, "task", {"title": f"{ctx.prefix}-q05-{owner}"})
    project = ctx.make(owner, "project", {"name": f"{ctx.prefix}-q05-{owner}"})
    ghost = str(uuid.uuid4())
    own_snap = snapshot(ctx, owner).json() or {}
    probes: list[tuple[str, Resp, Resp, str, str]] = []

    def pair(name: str, method: str, tmpl: str, foreign: str, body: Any = None) -> None:
        live = "hints" in tmpl
        a = ctx.api.call(method, tmpl.format(ID=foreign), v.cookie, body, _key(), live)
        b = ctx.api.call(method, tmpl.format(ID=ghost), v.cookie, body, _key(), live)
        probes.append((name, a, b, foreign, ghost))

    pair("GET task", "GET", "/api/tasks/{ID}", task["id"])
    pair(
        "PATCH task",
        "PATCH",
        "/api/tasks/{ID}",
        task["id"],
        {"title": "x", "expected_revision": 1},
    )
    pair(
        "transition task",
        "POST",
        "/api/tasks/{ID}/transitions",
        task["id"],
        {"action": "complete", "expected_revision": 1},
    )
    pair("GET project", "GET", "/api/projects/{ID}", project["id"])
    sc = "?scope_id={ID}"
    pair(
        "sync capabilities (scope)", "GET", "/api/sync/v1/capabilities" + sc, o.owner_id
    )
    pair(
        "sync changes (scope)",
        "GET",
        "/api/sync/v1/changes" + sc + "&cursor=e30",
        o.owner_id,
    )
    probes.append(_snapshot_create(ctx, v, o.owner_id, ghost))
    pair(
        "sync device command lookup (scope)",
        "GET",
        "/api/sync/v1/commands/" + str(uuid.uuid4()) + sc,
        o.owner_id,
    )
    pair("sync SSE hints (scope)", "GET", "/api/sync/v1/hints" + sc, o.owner_id)
    sid, token = own_snap.get("snapshot_id", ""), own_snap.get("first_page_token", "x")
    mine = snapshot(ctx, viewer).json() or {}
    probes.append(_foreign_snapshot(ctx, v, mine, sid, token, ghost))
    return probes


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _snapshot_create(
    ctx: Ctx, v: Acct, foreign: str, ghost: str
) -> tuple[str, Resp, Resp, str, str]:
    def go(scope: str) -> Resp:
        return ctx.api.call(
            "POST",
            "/api/sync/v1/snapshots",
            v.cookie,
            {"scope_id": scope, "projection_schema_version": SCOPE_VERSION},
        )

    return ("sync snapshot create (scope)", go(foreign), go(ghost), foreign, ghost)


def _foreign_snapshot(
    ctx: Ctx, v: Acct, mine: dict[str, Any], sid: str, token: str, ghost: str
) -> tuple[str, Resp, Resp, str, str]:
    path = "/api/sync/v1/snapshots/{ID}?scope_id=" + v.owner_id + "&page_token=" + token
    a = ctx.api.call("GET", path.format(ID=sid), v.cookie)
    b = ctx.api.call("GET", path.format(ID=ghost), v.cookie)
    return ("sync foreign snapshot id", a, b, sid, ghost)


def q05(ctx: Ctx) -> dict[str, Any]:
    ctx.api.cids.clear()
    for who in ctx.accts:
        ctx.accts[who].owner_id = ctx.accts[who].owner_id or (
            ctx.api.call("GET", "/api/auth/me", ctx.accts[who].cookie).json() or {}
        ).get("id", "")
    rows, failures = [], []
    for viewer, owner in (("B", "A"), ("A", "B")):
        for name, foreign, unknown, fid, gid in _isolation_probes(ctx, viewer, owner):
            same = foreign.status == unknown.status and normalize(
                foreign.json(), fid
            ) == normalize(unknown.json(), gid)
            leak = (fid in foreign.text) != (gid in unknown.text)
            ok = same and foreign.status == 404 and not leak
            rows.append(
                {
                    "direction": f"{viewer}->{owner}",
                    "probe": name,
                    "foreign_status": foreign.status,
                    "unknown_status": unknown.status,
                    "identical_body": same,
                    "id_echoed": leak,
                    "foreign_cid": foreign.cid,
                }
            )
            if not same:
                rows[-1]["foreign_body"] = normalize(foreign.json(), fid)
                rows[-1]["unknown_body"] = normalize(unknown.json(), gid)
            if not ok:
                failures.append(f"{viewer}->{owner} {name}")
    status = "FAIL" if failures else "PASS"
    summary = (
        f"{len(rows)} probes, all foreign == unknown 404"
        if not failures
        else "differs: " + "; ".join(failures)
    )
    note = "foreign sync command ID needs a device-protocol command; not exercised"
    return result(
        "Q05",
        "isolation (REST + sync, API part)",
        status,
        summary,
        observed={"probes": rows, "not_covered": note},
        correlation_ids=list(dict.fromkeys(ctx.api.cids)),
    )


def _feed(ctx: Ctx, who: str, cursor: str) -> tuple[list[dict[str, Any]], list[int]]:
    txs: list[dict[str, Any]] = []
    codes: list[int] = []
    for _ in range(50):
        r = ctx.api.call(
            "GET",
            f"/api/sync/v1/changes?scope_id={ctx.accts[who].owner_id}&cursor={cursor}",
            ctx.accts[who].cookie,
        )
        codes.append(r.status)
        page = r.json() or {}
        txs += page.get("transactions", [])
        if r.status != 200 or not page.get("has_more"):
            break
        cursor = page["next_cursor"]
    return txs, codes


def _records(txs: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    return [t for t in txs if needle in json.dumps(t)]


def q07(ctx: Ctx) -> dict[str, Any]:
    ctx.api.cids.clear()
    me = ctx.accts["A"]
    me.owner_id = me.owner_id or (
        ctx.api.call("GET", "/api/auth/me", me.cookie).json() or {}
    ).get("id", "")
    base = snapshot(ctx, "A")
    if base.status != 200:
        return result(
            "Q07", "REST writers in the sync feed", "FAIL", f"snapshot {base.status}"
        )
    cursor = (base.json() or {})["cursor"]
    task = ctx.make("A", "task", {"title": f"{ctx.prefix}-q07-new", "state": "next"})
    edit = (
        ctx.rest(
            "A",
            "PATCH",
            f"/api/tasks/{task['id']}",
            {
                "title": f"{ctx.prefix}-q07-edited",
                "expected_revision": task["revision"],
            },
        ).json()
        or {}
    )
    move = (
        ctx.rest(
            "A",
            "POST",
            f"/api/tasks/{task['id']}/transitions",
            {
                "action": "move",
                "to_state": "someday",
                "expected_revision": edit.get("revision", 0),
            },
        ).json()
        or {}
    )
    txs, codes = _feed(ctx, "A", cursor)
    mine = _records(txs, task["id"])
    text = json.dumps(mine)
    checks = {
        "feed answered 200": set(codes) == {200},
        "at least 3 transactions name the task": len(mine) >= 3,
        "edited title appears": f"{ctx.prefix}-q07-edited" in text,
        "moved state appears": "someday" in text,
    }
    shape = _shape(mine, task["id"], move)
    status = "PASS" if all(checks.values()) else "FAIL"
    differ = [k for k, v in shape["shared_fields_equal"].items() if not v]
    return result(
        "Q07",
        "REST writers visible in A's sync feed (create/edit/move)",
        status,
        f"{len(mine)} transactions for the task; checks: "
        + ", ".join(f"{k}={v}" for k, v in checks.items())
        + f"; shared fields that differ from REST: {differ or 'none'}",
        observed={
            "checks": checks,
            "feed_statuses": codes,
            "transactions_total": len(txs),
            "transaction_keys": sorted({k for t in mine for k in t}),
            "shape_compare": shape,
        },
        correlation_ids=list(dict.fromkeys(ctx.api.cids)),
    )


def _walk(node: Any, ident: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if node.get("id") == ident or ident in node.get("record_key", []):
            return node
        for value in node.values():
            found = _walk(value, ident)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _walk(value, ident)
            if found:
                return found
    return None


def _shape(mine: list[dict[str, Any]], ident: str, rest_task: dict[str, Any]) -> Any:
    found = _walk(mine[-1], ident) if mine else None
    value = (found or {}).get("value", found) or {}
    feed_keys = set(value) if isinstance(value, dict) else set()
    rest_keys = set(rest_task)
    return {
        "last_record_keys": sorted(found or {}),
        "rest_only_fields": sorted(rest_keys - feed_keys),
        "feed_only_fields": sorted(feed_keys - rest_keys),
        "shared_fields_equal": {
            k: _same(value.get(k), rest_task.get(k))
            for k in sorted(feed_keys & rest_keys)
            if isinstance(value, dict)
        },
    }


def _same(feed: Any, rest: Any) -> bool:
    """Sync v1 sends counters as decimal strings, REST as integers (data-model.md)."""
    if isinstance(feed, str) and isinstance(rest, int) and not isinstance(rest, bool):
        return feed == str(rest)
    return bool(feed == rest)


SMOKE = (
    ("GET", "/api/health", 200, False),
    ("GET", "/api/auth/me", 200, True),
    ("GET", "/api/tasks", 200, True),
    ("GET", "/api/tasks?state=next", 200, True),
    ("GET", "/api/projects", 200, True),
    ("GET", "/api/tags", 200, True),
    ("GET", "/api/review/state", 200, True),
    ("GET", "/api/sync/v1/capabilities?scope_id={SCOPE}", 200, True),
    ("GET", "/api/tasks/not-a-task", 404, True),
    ("GET", "/api/tasks", 401, "anon"),
)


def q11(ctx: Ctx) -> dict[str, Any]:
    ctx.api.cids.clear()
    a = ctx.accts["A"]
    scope = a.owner_id or (
        ctx.api.call("GET", "/api/auth/me", a.cookie).json() or {}
    ).get("id", "")
    rows = []
    for method, path, expect, auth in SMOKE:
        cookie = a.cookie if auth is True else None
        resp = ctx.api.call(method, path.format(SCOPE=scope), cookie)
        body = resp.json()
        rows.append(
            {
                "request": f"{method} {path.split('{')[0]}",
                "status": resp.status,
                "expected": expect,
                "body_keys": (
                    sorted(body)[:12] if isinstance(body, dict) else type(body).__name__
                ),
                "cid": resp.cid,
            }
        )
    task = ctx.make("A", "task", {"title": f"{ctx.prefix}-q11"})
    stale = ctx.rest(
        "A",
        "PATCH",
        f"/api/tasks/{task['id']}",
        {"title": "y", "expected_revision": 99},
    )
    empty = ctx.rest(
        "A", "PATCH", f"/api/tasks/{task['id']}", {"title": "", "expected_revision": 1}
    )
    nokey = ctx.rest("A", "POST", "/api/tasks", {"title": "z"}, key=False)
    for name, resp, expect in (
        ("stale revision write", stale, 409),
        ("empty title write", empty, 422),
        ("missing Idempotency-Key write", nokey, 400),
    ):
        rows.append(
            {
                "request": name,
                "status": resp.status,
                "expected": expect,
                "cid": resp.cid,
            }
        )
    bad = [r["request"] for r in rows if r["status"] != r["expected"]]
    return result(
        "Q11",
        "read-light web regression smoke",
        "FAIL" if bad else "PASS",
        f"{len(rows)} requests; mismatches: {bad or 'none'}",
        observed={"rows": rows, "shape_note": "key lists are response top-level keys"},
        correlation_ids=list(dict.fromkeys(ctx.api.cids)),
    )


# ---------------------------------------------------------------- local only


def _backup(src: Path, dst: Path) -> None:
    """Consistent copy of a data dir (sqlite files through the backup API).

    Modes are preserved: the auth store refuses a data dir with loosened modes.
    """
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)
    os.chmod(dst, src.stat().st_mode & 0o777)
    for item in sorted(src.rglob("*")):
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.suffix in {".sqlite3", ".db", ".sqlite"}:
            one, two = sqlite3.connect(item), sqlite3.connect(target)
            one.backup(two)
            # A WAL-flagged copy without -shm cannot be opened read-only, which the
            # startup auth migration check does; ship the copy in rollback mode.
            two.execute("PRAGMA journal_mode=DELETE")
            two.close()
            one.close()
        elif not item.name.endswith(("-wal", "-shm")):
            shutil.copy2(item, target)
        else:
            continue
        os.chmod(target, item.stat().st_mode & 0o777)


def _restore(backup: Path, live: Path) -> None:
    shutil.rmtree(live, ignore_errors=True)
    shutil.copytree(backup, live)


def _login(api: Api, acct: Acct) -> Resp:
    resp = api.call(
        "POST",
        "/api/auth/login",
        None,
        {"email": acct.email, "password": acct.password},
    )
    cookie = resp.headers.get("set-cookie", "").split(";", 1)[0]
    if resp.status == 200 and cookie:
        acct.cookie = cookie
    return resp


def _tasks(api: Api, acct: Acct) -> dict[str, Any]:
    items = (
        api.call(
            "GET",
            "/api/tasks?include_completed=true&include_cancelled=true",
            acct.cookie,
        ).json()
        or {}
    ).get("items", [])
    return {t["id"]: t for t in items}


def _fresh_ctx(info: dict[str, Any], run_id: str) -> Ctx:
    accts = {
        n: Acct(n, v["email"], v["password"], v["cookie"])
        for n, v in info["accounts"].items()
    }
    ctx = Ctx(Api(info["base_url"], RequestBudget(10**6)), accts, run_id, False)
    for a in accts.values():
        a.owner_id = (ctx.api.call("GET", "/api/auth/me", a.cookie).json() or {}).get(
            "id", ""
        )
    return ctx


def q08(root: Path, run_id: str) -> dict[str, Any]:
    live, bak = root / "q08-live", root / "q08-backup"
    server = LocalBackend(live, "on")
    ctx = _fresh_ctx(server.start(), run_id)
    try:
        a = ctx.accts["A"]
        t1 = ctx.make("A", "task", {"title": f"{ctx.prefix}-q08-before"})
        revoked = Acct("A", a.email, a.password, "")
        _login(ctx.api, revoked)
        taken = datetime.now(UTC)
        _backup(live, bak)
        t2 = ctx.make("A", "task", {"title": f"{ctx.prefix}-q08-after-backup"})
        old = (snapshot(ctx, "A").json() or {}).get("cursor", "")
        ctx.api.call("POST", "/api/auth/logout", revoked.cookie)
        stale_session = ctx.api.call("GET", "/api/auth/me", revoked.cookie).status
    finally:
        server.stop()
    _restore(bak, live)
    code1, out1 = run_cli(
        live,
        "sync-restore-control-plane",
        "--writers-stopped",
        "--backup-taken-at",
        taken.isoformat(),
    )
    code2, out2 = run_cli(
        live,
        "sync-restore-control-plane",
        "--writers-stopped",
        "--reopen",
        "--external-effects-reconciled",
    )
    server = LocalBackend(live, "on", resume=True)
    try:
        ctx = _fresh_ctx(server.start(), run_id)
        a = ctx.accts["A"]
        after_session = ctx.api.call("GET", "/api/auth/me", revoked.cookie).status
        titles = {t["title"] for t in _tasks(ctx.api, a).values()}
        feed = ctx.api.call(
            "GET",
            f"/api/sync/v1/changes?scope_id={a.owner_id}&cursor={old}",
            a.cookie,
        )
        fresh = snapshot(ctx, "A").status
        cids = list(dict.fromkeys(ctx.api.cids))
    finally:
        server.stop()
    checks = {
        "replay CLI exit 0": code1 == 0,
        "reopen CLI exit 0": code2 == 0,
        "session revoked after backup stays rejected": after_session == 401,
        "pre-backup task present": f"{ctx.prefix}-q08-before" in titles,
        "post-backup task absent (reported lost commit)": f"{ctx.prefix}-q08-after-backup"
        not in titles,
        "pre-restore cursor not accepted as-is": feed.status != 200
        or bool((feed.json() or {}).get("reset")),
        "fresh snapshot works": fresh == 200,
    }
    return result(
        "Q08",
        "restore drill (control-plane replay, revoked session, old cursor)",
        "PASS" if all(checks.values()) else "FAIL",
        ", ".join(f"{k}={v}" for k, v in checks.items()),
        observed={
            "checks": checks,
            "tasks": {"before_backup": t1["id"], "after_backup_lost": t2["id"]},
            "session_before_restore_status": stale_session,
            "session_after_restore_status": after_session,
            "old_cursor_feed": {"status": feed.status, "body": normalize(feed.json())},
            "cli_replay": {"exit": code1, "output": out1},
            "cli_reopen": {"exit": code2, "output": out2},
            "not_automated": "worker lease expiry/fences and external-effect reconciliation",
            "finding": "a restored WAL-flagged auth.sqlite3 without -shm makes startup "
            "fail with 'Authentication migration operation failed' (read-only open); "
            "the drill ships backup copies in rollback journal mode",
        },
        correlation_ids=cids,
    )


def cutover(root: Path, run_id: str) -> dict[str, Any]:
    live, pre = root / "cut-live", root / "cut-pre"
    server = LocalBackend(live, "off")
    ctx = _fresh_ctx(server.start(), run_id)
    try:
        a = ctx.accts["A"]
        before = ctx.make("A", "task", {"title": f"{ctx.prefix}-cut-pre"})
        off_caps = ctx.api.call(
            "GET", f"/api/sync/v1/capabilities?scope_id={a.owner_id}", a.cookie
        )
        off_feed = ctx.api.call(
            "GET", f"/api/sync/v1/changes?scope_id={a.owner_id}&cursor=e30", a.cookie
        )
        pre_tasks = _tasks(ctx.api, a)
    finally:
        server.stop()
    _backup(live, pre)
    server = LocalBackend(live, "on", resume=True)
    try:
        ctx = _fresh_ctx(server.start(), run_id)
        a = ctx.accts["A"]
        on_caps = ctx.api.call(
            "GET", f"/api/sync/v1/capabilities?scope_id={a.owner_id}", a.cookie
        )
        ctx.make("A", "task", {"title": f"{ctx.prefix}-cut-post"})
        snap = snapshot(ctx, "A")
        on_tasks = _tasks(ctx.api, a)
    finally:
        server.stop()
    _restore(pre, live)
    server = LocalBackend(live, "off", resume=True)
    try:
        ctx = _fresh_ctx(server.start(), run_id)
        a = ctx.accts["A"]
        back = _tasks(ctx.api, a)
        back_caps = ctx.api.call(
            "GET", f"/api/sync/v1/capabilities?scope_id={a.owner_id}", a.cookie
        )
        cids = list(dict.fromkeys(ctx.api.cids))
    finally:
        server.stop()
    checks = {
        "flag OFF: scope_enabled false": (off_caps.json() or {}).get("scope_enabled")
        is False,
        "flag OFF: feed refused": off_feed.status in (403, 404),
        "flag ON: scope_enabled true": (on_caps.json() or {}).get("scope_enabled")
        is True,
        "ON: snapshot lists both tasks": snap.status == 200
        and len(on_tasks) == len(pre_tasks) + 1,
        "restore: record set equals pre-enable copy": back == pre_tasks,
        "restore: flag OFF again": (back_caps.json() or {}).get("scope_enabled")
        is False,
    }
    return result(
        "CUTOVER",
        "cutover and rollback drill (local copy, flag off -> on -> restore)",
        "PASS" if all(checks.values()) else "FAIL",
        ", ".join(f"{k}={v}" for k, v in checks.items()),
        observed={
            "checks": checks,
            "pre_enable_task": before["id"],
            "statuses": {
                "off_capabilities": off_caps.status,
                "off_changes": off_feed.status,
                "on_capabilities": on_caps.status,
                "on_snapshot": snap.status,
            },
            "restored_equals_pre_enable": back == pre_tasks,
            "drill_step_4_note": "the post-enable write is absent after restore: a lossy rollback, as documented",
            "not_automated": "PostgreSQL staging import (separate ASK authorization)",
        },
        correlation_ids=cids,
    )


def q10(root: Path, run_id: str) -> dict[str, Any]:
    live = root / "q10-live"
    server = LocalBackend(live, "on")
    info = server.start()
    ctx = _fresh_ctx(info, run_id)
    server.stop()
    code, seeded = run_cli(
        live,
        "review-seed-aged-task",
        "--email",
        ctx.accts["A"].email,
        "--days",
        "8",
        "--title",
        f"{ctx.prefix}-q10",
    )
    sweep_code, sweep = run_cli(live, "review-run-sweep")
    reason = (
        "Q10 needs a controlled server clock across the 24-hour response and "
        "seven-day Review content expiry, then receipt/feed/snapshot reads, export "
        "and purge. The test CLI only seeds an aged formulation and runs the Review "
        "sweep; no seam advances the clock that governs sync receipts. "
        f"Partial seed+sweep observed: seed exit {code}, sweep exit {sweep_code}."
    )
    out = not_automated("Q10", "retention", reason)
    out["observed"] = {
        "seed": {"exit": code, "output": seeded},
        "sweep": {"exit": sweep_code, "output": sweep},
    }
    return out
