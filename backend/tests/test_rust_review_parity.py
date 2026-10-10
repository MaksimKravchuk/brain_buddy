"""Spec 026 T019 (PR-19): the Rust-backed Review facade changes no HTTP outcome.

With ``rust_core_sync`` ON the Review and formulation-clock commands and reads
are decided by the shared Rust rules (``RustReviewFacade``); OFF they keep their
Python rules. Each journey below is one scripted run of the existing Review
API, driven through two otherwise identical apps. They prove

* every status and body (success, refusal, replay) is the same once generated
  IDs are named by order of appearance, and the stored rows match too (tasks,
  decisions with their Undo snapshot, receipts, park rows, runs, bulk releases,
  settings and the idempotency records that carry the results), as do the log
  lines the Review service writes;
* each Review command asks the core at most once, a replay asks it zero times,
  and the OFF app never does;
* a bridge failure fails closed (no Python fallback, nothing written), and the
  flag takes effect per command in both directions;
* server-only data (Undo snapshots, park clock-before, progress digests) is
  absent from what the core answers a client.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections import Counter
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

import allure
import pytest

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TaskDocument
from app.modules.tasks.review_service import is_iana_zone
from app.modules.tasks.rust_adapter import DomainRefusal, RustBridgeError, RustCore
from app.modules.tasks.rust_review_facade import (
    ReviewRefused,
    _first_of_run,
    _records,
    _refusal_error,
    decode_ack,
    decode_decision,
    encode_settings_private,
)
from app.modules.tasks.rust_task_facade import _envelope, _inputs
from app.schemas.review import DecisionRequest

from .allure_evidence import attach_json, check_equal
from .conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    FrozenClock,
    _build_authenticated_client,
)
from .test_review_auto_park import keep_alive, sweep
from .test_review_flow_api import FlowApi

DAY = timedelta(days=1)
_NAMESPACE = uuid.UUID("5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11")
_ID = re.compile(
    r"\b(task|project|tag|form|decision|review|bulk|progress|subtask|comment|user)_"
    r"(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12})\b"
)
_OWNER = re.compile(r"user_[0-9a-f]{12}")
_DURATION = re.compile(r"duration_ms=\d+")


class IdNamer:
    """Names generated IDs by order of first appearance, per run."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def __call__(self, text: str) -> str:
        def name(match: re.Match[str]) -> str:
            return self._names.setdefault(
                match.group(0), f"<{match.group(1)}#{len(self._names) + 1}>"
            )

        return _ID.sub(name, text)

    def data(self, value: Any) -> Any:
        return json.loads(self(json.dumps(value, sort_keys=True, default=str)))


def _without_owner(value: Any) -> Any:
    """A stored document without the (per-app) owner ID, at any depth."""

    if isinstance(value, dict):
        return {k: _without_owner(v) for k, v in value.items() if k != "owner_id"}
    if isinstance(value, list):
        return [_without_owner(v) for v in value]
    return value


def _leaf_diff(off: Any, on: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Where two decoded bodies differ, as (path, OFF value, ON value)."""

    if isinstance(off, dict) and isinstance(on, dict):
        return [
            diff
            for key in sorted(off.keys() | on.keys())
            for diff in _leaf_diff(off.get(key), on.get(key), f"{path}/{key}")
        ]
    if isinstance(off, list) and isinstance(on, list) and len(off) == len(on):
        return [
            diff
            for index, (a, b) in enumerate(zip(off, on, strict=True))
            for diff in _leaf_diff(a, b, f"{path}[{index}]")
        ]
    return [] if off == on else [(path, off, on)]


@dataclass
class Exchange:
    method: str
    path: str
    status: int
    body: Any


class Scenario:
    """One app driven by a journey: recorded calls with deterministic client IDs."""

    def __init__(self, api: FlowApi, core_calls: Counter[str]) -> None:
        self.api = api
        self.core_calls = core_calls
        self.namer = IdNamer()
        self.exchanges: list[Exchange] = []
        self.deltas: list[tuple[str, int, int]] = []
        self._count = 0
        client = api.client
        original = client.request

        def recording(method: str, url: str, **kwargs: Any) -> Any:
            before = Counter(core_calls)
            response = original(method, url, **kwargs)
            decoded = response.json() if response.content else None
            if isinstance(decoded, dict):
                decoded.pop("reference_id", None)
            params = kwargs.get("params") or {}
            path = url + "".join(f"?{k}={v}" for k, v in sorted(params.items()))
            body = self.namer.data(decoded)
            if isinstance(body, dict) and isinstance(body.get("receipts"), list):
                # Receipts are listed by task ID, which each app generates at
                # random, so only their set is comparable.
                body["receipts"].sort(key=lambda r: json.dumps(r, sort_keys=True))
            self.exchanges.append(
                Exchange(method, self.namer(path), response.status_code, body)
            )
            self.deltas.append(
                (
                    f"{method} {self.namer(url)}",
                    core_calls["decide"] - before["decide"],
                    core_calls["query"] - before["query"],
                )
            )
            return response

        client.request = recording  # type: ignore[method-assign]

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """An Allure step that carries the requests it made as its evidence."""

        first = len(self.exchanges)
        with allure.step(name):
            yield
            attach_json(
                "requests",
                [(e.method, e.path, e.status) for e in self.exchanges[first:]],
            )

    # ----------------------------------------------------------- ids, time
    def nid(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}_{uuid.uuid5(_NAMESPACE, str(self._count))}"

    @property
    def clock(self) -> FrozenClock:
        return self.api.clock

    def tick(self, **delta: float) -> None:
        self.api.clock.advance(timedelta(**(delta or {"seconds": 1})))

    # ------------------------------------------------------------- calls
    @staticmethod
    def ok(response: Any) -> Any:
        assert response.status_code < 300, response.text
        return response.json() if response.content else None

    def post(self, path: str, body: Any = None, *, headers: Any = None) -> Any:
        self.tick()
        return self.api.client.post(
            f"/api{path}",
            json={} if body is None else body,
            headers=headers or self.api.key(),
        )

    def patch(self, path: str, body: Any, *, headers: Any = None) -> Any:
        self.tick()
        return self.api.client.patch(
            f"/api{path}", json=body, headers=headers or self.api.key()
        )

    def put(self, path: str, body: Any) -> Any:
        self.tick()
        return self.api.client.put(f"/api{path}", json=body, headers=self.api.key())

    def get(self, path: str, **params: Any) -> Any:
        return self.api.client.get(f"/api{path}", params=params or None)

    def task(self, title: str, *, state: str = "inbox", **body: Any) -> dict[str, Any]:
        """A task through the API, a second after the one before it."""

        created: dict[str, Any] = self.api.create(title, state=state, **body)
        self.tick()
        return created

    def fresh(self, task: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, Any] = self.ok(self.get(f"/tasks/{task['id']}"))
        return found

    def seed(
        self, n: int, state: str = "next", title: str | None = None, **fields: Any
    ) -> TaskDocument:
        """A task written straight to storage under a fixed id."""

        now = self.clock()
        repo = self.api.container.task_repo
        values: dict[str, Any] = {
            "id": f"task_{n:012x}",
            "owner_id": self.api.owner_id,
            "title": title or f"Seed {n}",
            "state": state,
            "order_key": n,
            "created_at": now,
            "updated_at": now,
            **fields,
        }
        if state == "next":
            values.setdefault("formulation_id", f"form_{n:012x}")
            values.setdefault("formulation_started_at", now)
        task = TaskDocument.model_validate(values)
        with repo.command_lock(self.api.owner_id):
            repo.create(task)
        return task

    def decide(self, task: dict[str, Any], kind: str, **body: Any) -> Any:
        self.tick()
        return self.api.decide_raw(task, kind, **body)

    def start(self, **body: Any) -> Any:
        self.tick()
        payload = {
            "mode": "quick",
            "entry": "list",
            "origin": "ios",
            "replace_open": False,
            **body,
        }
        return self.api.client.post(
            "/api/review/sessions", json=payload, headers=self.api.key()
        )

    def progress(self, sid: str, *, headers: Any = None, **body: Any) -> Any:
        self.tick()
        body.setdefault("progress_id", self.nid("progress"))
        return self.api.client.patch(
            f"/api/review/sessions/{sid}",
            json=body,
            headers=headers or self.api.key(),
        )

    def park(self, task: dict[str, Any], **kw: Any) -> Any:
        self.tick()
        return self.api.client.post(
            f"/api/tasks/{task['id']}/auto-park",
            json={"formulation_id": kw.get("form") or task["formulation"]["id"]},
            headers=kw.get("headers") or self.api.key(),
        )

    def undo(
        self, result: dict[str, Any], *, revision: int | None = None, **kw: Any
    ) -> Any:
        self.tick()
        return self.api.client.post(
            f"/api/review/decisions/{result['decision']['id']}/undo",
            json={"expected_task_revision": revision or result["task"]["revision"]},
            headers=kw.get("headers") or self.api.key(),
        )

    def bulk(self, kind: str, tasks: list[Any], **body: Any) -> Any:
        self.tick()
        items = [
            {
                "task_id": t.id if isinstance(t, TaskDocument) else t["id"],
                "expected_revision": (
                    t.revision if isinstance(t, TaskDocument) else t["revision"]
                ),
            }
            for t in tasks
        ]
        headers = body.pop("headers", None) or self.api.key()
        return self.api.client.post(
            "/api/review/bulk-releases",
            json={"kind": kind, "items": items, **body},
            headers=headers,
        )

    def undo_bulk(self, bulk_id: str, *, headers: Any = None) -> Any:
        self.tick()
        return self.api.client.post(
            f"/api/review/bulk-releases/{bulk_id}/undo",
            json={},
            headers=headers or self.api.key(),
        )

    def drop_sessions(self) -> None:
        repo = self.api.container.task_repo
        with repo.command_lock(self.api.owner_id):
            repo._thread_state.conn.execute(  # type: ignore[attr-defined]
                "DELETE FROM review_sessions WHERE owner_id = ?", (self.api.owner_id,)
            )

    def drop_park_rows(self) -> None:
        repo = self.api.container.task_repo
        with repo.command_lock(self.api.owner_id):
            repo._thread_state.conn.execute(  # type: ignore[attr-defined]
                "DELETE FROM review_park_acks WHERE owner_id = ?", (self.api.owner_id,)
            )

    def snapshot(self) -> Any:
        """Every stored row of the owner, named like the responses are."""

        repo = self.api.container.task_repo
        owner = self.api.owner_id
        docs = {
            "tasks": repo.list_for_owner(owner_id=owner),
            "projects": repo.list_projects_for_owner(owner_id=owner),
            "sessions": repo.list_review_sessions(owner),
            "decisions": repo.list_review_decisions(owner),
            "receipts": repo.list_review_receipts(owner),
            "acks": repo.list_park_acks(owner),
            "bulk": repo.list_bulk_releases(owner),
            "settings": [s for s in [repo.get_review_settings(owner)] if s],
            "idempotency": repo.list_idempotency_for_owner(owner_id=owner),
        }
        dumped: dict[str, list[Any]] = {}
        for kind, rows in docs.items():
            items = [
                _without_owner(
                    {
                        k: v
                        for k, v in json.loads(row.model_dump_json()).items()
                        if k not in {"key", "request_hash"}
                    }
                )
                for row in rows
            ]
            dumped[kind] = sorted(
                (self.namer.data(item) for item in items),
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        return dumped


@dataclass
class Apps:
    off: Scenario
    on: Scenario
    queries: list[Any] = field(default_factory=list)


@pytest.fixture
def apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Apps]:
    built = []
    for subdir in ("review-off", "review-on"):
        client, _ = _build_authenticated_client(
            tmp_path,
            monkeypatch,
            subdir=subdir,
            email=TEST_USER_EMAIL,
            password=TEST_USER_PASSWORD,
        )
        clock = FrozenClock()
        clock.install(client.app.state.container)  # type: ignore[attr-defined]
        api = FlowApi(client, clock)
        api.flag("on")
        built.append(api)
    off_api, on_api = built
    on_api.container.feature_flag_service.set_mode(
        "rust_core_sync", "on", operator_id="parity"
    )
    queries: list[Any] = []
    tallies = []
    for api in built:
        tally: Counter[str] = Counter()
        tallies.append(tally)
        facade = api.container.review_service._rust_facade
        assert facade is not None
        for name in ("decide", "query"):
            original = getattr(facade._core, name)

            def counted(
                *args: Any,
                _o: Callable[..., Any] = original,
                _n: str = name,
                _t: Counter[str] = tally,
                **kwargs: Any,
            ) -> Any:
                _t[_n] += 1
                answer = _o(*args, **kwargs)
                if _n == "query":
                    queries.append(answer)
                return answer

            monkeypatch.setattr(facade._core, name, counted)
    yield Apps(Scenario(off_api, tallies[0]), Scenario(on_api, tallies[1]), queries)
    for api in built:
        api.client.close()


def _evidence(name: str, content: object) -> None:
    attach_json(name, content)


def _log_lines(caplog: pytest.LogCaptureFixture, namer: IdNamer) -> list[str]:
    return [
        _DURATION.sub("duration_ms=N", _OWNER.sub("<owner>", namer(r.getMessage())))
        for r in caplog.records
        if r.name == "app.modules.tasks.review"
    ]


def _compare(
    apps: Apps, journey: Callable[[Scenario], None], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.modules.tasks.review")
    with allure.step("run the journey with rust_core_sync OFF and ON"):
        journey(apps.off)
        off_logs = _log_lines(caplog, apps.off.namer)
        caplog.clear()
        journey(apps.on)
        on_logs = _log_lines(caplog, apps.on.namer)
        _evidence("OFF", [(e.method, e.path, e.status) for e in apps.off.exchanges])
        _evidence("ON", [(e.method, e.path, e.status) for e in apps.on.exchanges])
        if os.environ.get("DUMP_EXCHANGES"):
            for e, (_, d, _q) in zip(apps.on.exchanges, apps.on.deltas, strict=True):
                body = e.body
                msg = (
                    body.get("detail") or body.get("message") or ""
                    if isinstance(body, dict)
                    else ""
                )
                print("EXCH", e.method, e.path[:70], e.status, d, str(msg)[:60])
    with allure.step("every status and body is identical"):
        assert len(apps.off.exchanges) == len(apps.on.exchanges) > 10
        for expected, actual in zip(apps.off.exchanges, apps.on.exchanges, strict=True):
            same = (actual.method, actual.path, actual.status, actual.body) == (
                expected.method,
                expected.path,
                expected.status,
                expected.body,
            )
            assert same, (
                f"{expected.method} {expected.path} {expected.status}/{actual.status}: "
                f"{_leaf_diff(expected.body, actual.body)}"
            )
        _evidence("compared", f"{len(apps.on.exchanges)} requests")
    with allure.step("the stored rows are identical"):
        on_rows, off_rows = apps.on.snapshot(), apps.off.snapshot()
        differing = {
            kind: {
                "only ON": [row for row in on_rows[kind] if row not in off_rows[kind]],
                "only OFF": [row for row in off_rows[kind] if row not in on_rows[kind]],
            }
            for kind in on_rows
            if on_rows[kind] != off_rows[kind]
        }
        attach_json("differing rows", differing)
        assert not differing, json.dumps(differing, indent=1, sort_keys=True)
        _evidence("rows", {kind: len(rows) for kind, rows in on_rows.items()})
    with allure.step("the Review log lines are identical"):
        check_equal("log lines", on_logs, off_logs)
        assert on_logs
    with allure.step("the OFF app never asks the core, the ON app asks once"):
        assert sum(apps.off.core_calls.values()) == 0
        assert all(decide <= 1 and query <= 1 for _, decide, query in apps.on.deltas)
        _evidence("core calls", dict(apps.on.core_calls))


# ------------------------------------------------------------------ journeys


def decisions(s: Scenario) -> None:
    """Every decision type, its refusals, its replays and its matching records."""

    api, ok = s.api, s.ok
    api.activate_at(s.clock() - 30 * DAY)
    garden = ok(s.post("/projects", {"name": "Garden"}))
    old = ok(s.post("/projects", {"name": "Old"}))
    sid = ok(s.start(id=s.nid("review"), mode="full", origin="web"))["id"]
    nxt = {
        name: s.task(name, state="next")
        for name in (
            "complete me",
            "reformulate me",
            "cosmetic Bob",
            "first step me",
            "go waiting",
            "go someday",
            "cancel me",
            "extend me",
            "wrong formulation",
        )
    }
    big = s.task("big notes", state="next", details="x" * 19_990)
    waiting = {
        name: s.task(name, state="waiting", waiting_for="Ann")
        for name in ("keep it", "follow up", "follow up again", "clash", "return me")
    }
    in_garden = s.task(
        "garden waiting", state="waiting", waiting_for="Ann", project_id=garden["id"]
    )
    old_waiting = s.task(
        "old waiting", state="waiting", waiting_for="Ann", project_id=old["id"]
    )
    old_someday = s.task("old someday", state="someday", project_id=old["id"])
    someday = {
        name: s.task(name, state="someday")
        for name in ("keep sd", "return sd", "cancel sd")
    }
    ok(s.post(f"/projects/{old['id']}/archive", {"expected_revision": old["revision"]}))
    s.tick(days=15)
    ask = {name: s.fresh(task) for name, task in nxt.items()}
    big = s.fresh(big)
    fresh_next = s.task("not due yet", state="next")
    d = s.decide

    with s.step("each type moves its task and counts in the run"):
        d(ask["complete me"], "complete", session_id=sid, stall_reason="unclear")
        d(
            ask["reformulate me"],
            "reformulate",
            session_id=sid,
            title="Reword the whole thing",
            ai_use="edited",
        )
        for title in ("cosmetic bob.", "cosmetic bob!", "cosmetic bob!!"):
            d(
                s.fresh(ask["cosmetic Bob"]),
                "reformulate",
                session_id=sid,
                title=title,
            )
        d(ask["first step me"], "first_step", session_id=sid, title="Open the file")
        d(big, "first_step", title="Overflow the notes")
        d(ask["go waiting"], "waiting", session_id=sid, waiting_for="  Sam  ")
        d(ask["go someday"], "someday", session_id=sid)
        d(ask["cancel me"], "cancel", session_id=sid)
        d(ask["extend me"], "extend", session_id=sid, reason="Quote due Friday")
        d(s.fresh(ask["extend me"]), "extend", reason="Again")
        d(fresh_next, "extend", reason="Too early")
    with s.step("keep, follow-up and return decisions, repeats and clashes"):
        keep = waiting["keep it"]
        d(keep, "keep_waiting", session_id=sid)
        d(keep, "keep_waiting", session_id=sid)
        follow_id = s.nid("task")
        follow = waiting["follow up"]
        d(
            follow,
            "follow_up",
            session_id=sid,
            title="Call Ann",
            follow_up_task_id=follow_id,
        )
        d(follow, "follow_up", session_id=sid, title="Call again")
        d(waiting["follow up again"], "follow_up", title="Chase Ann")
        d(waiting["clash"], "follow_up", title="Clash", follow_up_task_id=follow_id)
        d(in_garden, "follow_up", title="Follow in the garden")
        d(old_waiting, "follow_up", title="Follow in the old project")
        d(waiting["return me"], "return_to_next", session_id=sid, title="Renamed")
        d(old_someday, "return_to_next", title="Back from the old project")
        d(someday["keep sd"], "keep_someday", session_id=sid)
        d(
            someday["return sd"],
            "return_to_next",
            session_id=sid,
            title=someday["return sd"]["title"],
        )
        d(someday["cancel sd"], "cancel", session_id=sid)
    with s.step("refusals are reported in the order Python reports them"):
        wrong = ask["wrong formulation"]
        bad = {**wrong, "formulation": {**wrong["formulation"], "id": s.nid("form")}}
        d(bad, "reformulate", title="Different formulation")
        d({**wrong, "revision": wrong["revision"] + 5}, "complete")
        d({**wrong, "id": "task_000000000000"}, "complete")
        d(keep, "reformulate", title="Not allowed", formulation_id=s.nid("form"))
    with s.step("a stored decision id answers as it always did"):
        decision_id = s.nid("decision")
        again = s.fresh(wrong)
        d(again, "cancel", decision_id=decision_id)
        d(again, "cancel", decision_id=decision_id)
        d(s.fresh(keep), "keep_waiting", decision_id=decision_id)
    with s.step("a stored decision of a task that has gone is a missing task"):
        gone_id = s.nid("decision")
        gone = s.task("gone soon", state="waiting", waiting_for="Ann")
        d(gone, "keep_waiting", decision_id=gone_id)
        repo = api.container.task_repo
        with repo.command_lock(api.owner_id):
            repo.delete_task_record(api.owner_id, gone["id"])
        d(gone, "keep_waiting", decision_id=gone_id)
    with s.step("a decision names the request that proposed it"):
        proposed = s.task("proposed", state="next")
        s.tick(days=15)
        d(
            s.fresh(proposed),
            "cancel",
            ai_use="as_is",
            navigator_request_id=str(uuid.uuid5(_NAMESPACE, "navigator")),
            client_decided_at=(s.clock() + timedelta(minutes=5)).isoformat(),
        )
        s.get("/review/state")
    with s.step("the same key replays, another body conflicts"):
        headers = api.key()
        task = s.fresh(someday["keep sd"])
        body = {"type": "keep_someday", "expected_revision": task["revision"]}
        for payload in (body, body, {**body, "type": "cancel"}):
            s.tick()
            api.client.post(
                f"/api/tasks/{task['id']}/decisions", json=payload, headers=headers
            )


def undo(s: Scenario) -> None:
    """Decision Undo: success, replay, refusals, follow-ups, receipts and parks."""

    api, ok = s.api, s.ok
    api.activate_at(s.clock() - 30 * DAY)
    sid = ok(s.start())["id"]
    asking = [s.task(f"ask {i}", state="next") for i in range(7)]
    waiting = [
        s.task(f"wait {i}", state="waiting", waiting_for="Ann") for i in range(5)
    ]
    sleeper = s.task("sleep", state="someday")
    s.tick(days=15)
    asking = [s.fresh(t) for t in asking]
    results = [
        ok(s.decide(task, kind, session_id=sid, **body))
        for task, kind, body in (
            (asking[0], "complete", {}),
            (asking[1], "someday", {}),
            (asking[2], "first_step", {"title": "Open it"}),
            (waiting[0], "keep_waiting", {}),
            (waiting[1], "follow_up", {"title": "Chase"}),
            (waiting[2], "follow_up", {"title": "Chase two"}),
            (sleeper, "return_to_next", {"title": "sleep"}),
            (waiting[3], "follow_up", {"title": "Chase three"}),
            (asking[4], "someday", {}),
            (asking[5], "complete", {}),
            (asking[6], "complete", {}),
            (waiting[4], "follow_up", {"title": "Chase four"}),
        )
    ]
    headers = api.key()
    with s.step("Undo restores the task, its receipt and its counters"):
        s.undo(results[0], headers=headers)
        s.undo(results[0], headers=headers)
        for index in (1, 2, 3, 6):
            s.undo(results[index])
    with s.step("Undo refuses what changed since"):
        s.post(f"/tasks/{results[4]['created_task']['id']}/subtasks", {"title": "Mine"})
        s.undo(results[4])
        s.post(f"/tasks/{results[11]['created_task']['id']}/comments", {"body": "Mine"})
        s.undo(results[11])
        s.undo(results[5], revision=results[5]["task"]["revision"] + 3)
        s.undo(results[0])
        s.post(
            "/review/decisions/decision_000000000000/undo",
            {"expected_task_revision": 1},
        )
        s.undo(results[5])
        s.undo(results[5])
    with s.step("Undo copes with rows that vanished since the decision"):
        repo, owner = api.container.task_repo, api.owner_id
        with repo.command_lock(owner):
            repo.delete_task_record(owner, results[7]["created_task"]["id"])
            repo.delete_review_receipt(owner, results[8]["task"]["id"], "someday")
        s.undo(results[7])
        s.undo(results[8])
        s.drop_sessions()
        s.undo(results[9])
        with repo.command_lock(owner):
            repo.delete_task_record(owner, results[10]["task"]["id"])
        s.undo(results[10])
    with s.step("an Undo past its seven days is refused after the retention"):
        result = ok(s.decide(s.fresh(asking[3]), "cancel"))
        s.tick(days=8)
        sweep(api.container)
        s.undo(result)


def parks(s: Scenario) -> None:
    """Device parks, the yield rule, park rows and their return."""

    api, ok = s.api, s.ok
    api.activate_at(s.clock() - 60 * DAY)
    names = (
        "device",
        "yield extend",
        "yield someday",
        "wrong",
        "replay",
        "off",
        "gap",
        "undo return",
    )
    # Seeded under fixed IDs: the sweep parks several at one instant, and parks
    # that share an instant are listed by task ID.
    created = {
        name: s.seed(n, "next", title=name)
        for n, name in enumerate((*names, "no row"), start=1)
    }
    s.tick(days=21)
    keep_alive(api.container)
    due = {name: s.fresh({"id": task.id}) for name, task in created.items()}
    young = s.fresh({"id": s.seed(40, "next", title="not due").id})

    with s.step("a device park applies once and never conflicts"):
        s.park(due["device"])
        s.park(due["device"])
        for task in ("yield extend", "yield someday", "no row", "undo return"):
            s.park(due[task])
        headers = api.key()
        s.park(due["replay"], headers=headers)
        s.park(due["replay"], headers=headers)
    with s.step("the server must agree with the device"):
        s.park(due["wrong"], form=s.nid("form"))
        s.park(young)
        s.park({"id": "task_000000000000", "formulation": {"id": s.nid("form")}})
        api.flag("off")
        s.park(due["off"])
        api.flag("on")
    with s.step("a decision made before the park yields it"):
        before = (s.clock() - timedelta(hours=1)).isoformat()
        s.decide(due["yield extend"], "extend", reason="Away", client_decided_at=before)
        s.decide(due["yield someday"], "someday", client_decided_at=before)
        s.get("/review/state")
    with s.step("park rows are acknowledged once and returning stamps the row"):
        row = {
            "task_id": due["device"]["id"],
            "formulation_id": due["device"]["formulation"]["id"],
        }
        ghost = {"task_id": "task_000000000000", "formulation_id": s.nid("form")}
        ack_headers = api.key()
        for items in ([row, row, ghost], [row, row, ghost]):
            s.post("/review/parks/acknowledge", {"items": items}, headers=ack_headers)
        s.post("/review/parks/acknowledge", {"items": [row]})
        s.tick(hours=3)
        parked = s.fresh(due["device"])
        s.ok(
            s.post(
                f"/tasks/{parked['id']}/transitions",
                {
                    "action": "move",
                    "to_state": "next",
                    "expected_revision": parked["revision"],
                },
            )
        )
        s.get("/review/state")
    with s.step("Undo of a return puts the task back in its park"):
        parked = s.fresh(due["undo return"])
        returned = ok(s.decide(parked, "return_to_next", title=parked["title"]))
        s.undo(returned)
        s.get("/review/state")
    with s.step("a return without its park row writes none and warns"):
        s.drop_park_rows()
        s.decide(
            s.fresh(due["no row"]),
            "return_to_next",
            title=due["no row"]["title"],
        )
    with s.step("a park the sweep made yields to an earlier decision too"):
        swept = s.seed(41, "next", title="swept")
        s.tick(days=21)
        keep_alive(api.container)
        due_swept = s.fresh({"id": swept.id})
        sweep(api.container)
        s.get("/review/state")
        before = (s.clock() - timedelta(hours=1)).isoformat()
        s.decide(due_swept, "extend", reason="Away", client_decided_at=before)
        s.get("/review/state")
    with s.step("a sweep gap floors the park before the park is judged"):
        repo = api.container.task_repo
        settings = repo.get_review_settings(api.owner_id)
        assert settings is not None
        repo.save_review_settings(
            settings.model_copy(update={"last_effective_sweep_at": s.clock() - 5 * DAY})
        )
        s.park(due["gap"])
        s.get("/review/state")


def settings(s: Scenario) -> None:
    """Settings, activation and their clock-floor bookkeeping."""

    api, ok = s.api, s.ok
    now = s.clock()
    s.get("/review/state")
    s.seed(1, "next", formulation_started_at=now - 20 * DAY)
    s.seed(2, "next", formulation_id=None, formulation_started_at=None)
    s.seed(3, "next", due_date=(now + 9 * DAY).date())
    s.seed(4, "waiting", waiting_for="Ann")
    s.seed(
        5,
        "next",
        due_date=(now + 3 * DAY).date(),
        formulation_park_floor_at=now + 30 * DAY,
    )
    with s.step("a refused settings change or activation changes nothing"):
        s.put("/review/settings", {"expected_revision": 5, "threshold_days": 21})
        s.put("/review/settings", {"expected_revision": 1, "time_zone": "Mars/Olympus"})
        s.put("/review/settings", {"expected_revision": 1, "time_zone": "localtime"})
        s.post("/review/explainer/acknowledge", {"time_zone": "Mars/Olympus"})
    with s.step("the first acknowledgement activates and clamps every Next clock"):
        headers = api.key()
        s.post(
            "/review/explainer/acknowledge",
            {"time_zone": "Europe/Berlin"},
            headers=headers,
        )
        s.post(
            "/review/explainer/acknowledge",
            {"time_zone": "Europe/Berlin"},
            headers=headers,
        )
        s.tick(days=1)
        s.post("/review/explainer/acknowledge", {"time_zone": "Pacific/Honolulu"})
        s.post("/review/explainer/acknowledge", {})
        s.get("/review/state")
    with s.step("a changed value moves the revision and the floors, an equal one not"):
        put = s.put
        put("/review/settings", {"expected_revision": 2, "threshold_days": 21})
        put("/review/settings", {"expected_revision": 3, "threshold_days": 21})
        put(
            "/review/settings",
            {"expected_revision": 3, "review_weekday": 3, "review_time": "09:30"},
        )
        put("/review/settings", {"expected_revision": 4, "onboarded": True})
        put("/review/settings", {"expected_revision": 5, "onboarded": True})
        # A week after the clamp's floor lapses, a zone change raises it again.
        s.tick(days=8)
        put(
            "/review/settings",
            {"expected_revision": 5, "time_zone": "America/New_York"},
        )
        put(
            "/review/settings",
            {"expected_revision": 6, "time_zone": "America/New_York"},
        )
        put("/review/settings", {"expected_revision": 6})
        replay = api.key()
        for _ in range(2):
            s.tick()
            api.client.put(
                "/api/review/settings",
                json={"expected_revision": 6, "threshold_days": 7},
                headers=replay,
            )
        s.get("/review/state")
        assert ok(s.get("/review/state"))["settings"]["threshold_days"] == 7


def sessions(s: Scenario) -> None:
    """Runs, merged progress, queues and the review state."""

    api, ok = s.api, s.ok
    now = s.clock()
    api.activate_at(now - 60 * DAY)
    api.put_settings(time_zone="Pacific/Auckland")
    s.seed(1, "completed", completed_at=now - 2 * DAY)
    s.seed(2, "inbox")
    s.seed(3, "inbox")
    for n in (4, 5, 6):
        s.seed(n, "next", formulation_started_at=now - 15 * DAY)
    s.seed(7, "next", formulation_started_at=now - DAY)
    s.seed(
        8,
        "waiting",
        waiting_for="Ann",
        waiting_since=now - 9 * DAY,
        updated_at=now - 9 * DAY,
    )
    s.seed(9, "waiting", waiting_for="Bob", waiting_since=now - 2 * DAY)
    for n in range(10, 20):
        s.seed(n, "someday", updated_at=now - (n - 5) * DAY)
    s.seed(
        20,
        "next",
        due_date=(now + 3 * DAY).date(),
        formulation_started_at=now - 2 * DAY,
    )
    s.seed(21, "waiting", waiting_for="Ann", due_date=(now + 5 * DAY).date())
    ok(s.post("/projects", {"name": "Kitchen"}))
    s.get("/review/state")
    with s.step("a second open run needs replace_open, a reused id is matched"):
        first = ok(s.start(id=s.nid("review"), mode="full"))
        s.start()
        replaced = ok(s.start(id=s.nid("review"), replace_open=True))
        sid = replaced["id"]
        s.start(id=sid)
        s.start(id=sid, mode="full")
        s.start(id=first["id"], mode="quick")
        s.get(f"/review/sessions/{first['id']}")
    with s.step("every step has a queue, with and without a run"):
        for step in (
            "wins",
            "inbox",
            "decisions",
            "rest_of_next",
            "waiting",
            "projects",
            "someday",
            "dates",
            "mind_sweep",
            "summary",
        ):
            s.get(f"/review/queues/{step}")
            s.get(f"/review/queues/{step}", session_id=sid)
        s.get("/review/queues/wins", session_id=s.nid("review"))
    with s.step("progress merges and is replay-safe by its id"):
        steps = ("wins", "inbox", "decisions", "summary")
        for call in (
            {"current_step": "decisions"},
            {"step": {"code": "wins", "status": "finished"}},
            {"step": {"code": "wins", "status": "pending"}},
            {"step": {"code": "inbox", "status": "finished"}},
            {"step": {"code": "inbox", "status": "skipped"}},
            {"active_seconds": {"code": "wins", "seconds": 40}},
            {"inbox_processed_delta": 2},
            {"inbox_processed_delta": -5},
            {"set_aside_task_id": f"task_{4:012x}"},
            {"set_aside_task_id": f"task_{4:012x}"},
            {"set_aside_task_id": f"task_{1:012x}"},
            {"set_aside_task_id": "task_000000000000"},
            {"snapshot_decision_queue": True},
            {"snapshot_decision_queue": True},
            {"step": {"code": "decisions", "status": "finished"}},
            {"step": {"code": "waiting", "status": "finished"}},
            {"active_seconds": {"code": "waiting", "seconds": 5}},
        ):
            s.progress(sid, **call)
        _evidence("quick steps", steps)
        same = s.nid("progress")
        headers = api.key()
        s.progress(sid, progress_id=same, current_step="inbox", headers=headers)
        s.progress(sid, progress_id=same, current_step="inbox", headers=headers)
        s.progress(sid, progress_id=same, current_step="inbox")
        s.progress(sid, progress_id=same, current_step="summary")
        s.progress(s.nid("review"), current_step="wins")
        s.progress(sid)
    with s.step("a card decided or set aside shows in its queue"):
        card = s.fresh({"id": f"task_{5:012x}"})
        s.decide(card, "complete", session_id=sid)
        s.get("/review/queues/decisions", session_id=sid)
        s.get("/review/queues/rest_of_next", session_id=sid)
        s.get("/review/state")
    with s.step("a full run finishes every kind of step"):
        full = ok(s.start(mode="full", replace_open=True, id=s.nid("review")))["id"]
        for code in (
            "mind_sweep",
            "inbox",
            "decisions",
            "rest_of_next",
            "waiting",
            "projects",
            "someday",
            "dates",
            "summary",
        ):
            s.progress(full, step={"code": code, "status": "finished"})
        s.progress(full, active_seconds={"code": "someday", "seconds": 30})
        s.post(f"/review/sessions/{full}/finish", {"clear_start": "yes"})
        s.post(f"/review/sessions/{full}/finish", {})
        s.progress(full, current_step="wins")
        s.post(f"/review/sessions/{s.nid('review')}/finish", {})
        s.get("/review/state")
    with s.step("a run with nothing done ends empty, an idle one is closed"):
        empty = ok(s.start(id=s.nid("review")))["id"]
        replay = api.key()
        for _ in range(2):
            s.post(
                f"/review/sessions/{empty}/finish",
                {"clear_start": "not_really"},
                headers=replay,
            )
        idle = ok(s.start(id=s.nid("review")))["id"]
        s.progress(idle, inbox_processed_delta=1)
        s.tick(days=7, hours=1)
        sweep(api.container)
        s.get("/review/state")
        s.get(f"/review/sessions/{idle}")
    with s.step("a captured-empty decision queue stays empty"):
        for n in (4, 6, 7, 20):
            s.decide(s.fresh({"id": f"task_{n:012x}"}), "cancel")
        again = ok(s.start(id=s.nid("review")))["id"]
        s.progress(again, snapshot_decision_queue=True)
        s.get("/review/queues/decisions", session_id=again)


def bulk(s: Scenario) -> None:
    """Bulk release and its Undo: eligibility, matching records and expiry."""

    api, ok = s.api, s.ok
    now = s.clock()
    api.activate_at(now - 60 * DAY)
    api.put_settings(onboarded=True)
    extended = s.seed(
        1,
        formulation_started_at=now - 29 * DAY,
        formulation_extended_at=now - 14 * DAY,
        formulation_extension_reason="Waiting for the quote",
        consecutive_stalled_formulations=2,
    )
    floored = s.seed(
        2,
        formulation_started_at=now - 30 * DAY,
        formulation_park_floor_at=now + 3 * DAY,
    )
    paused = s.seed(
        3, formulation_started_at=now - 45 * DAY, due_date=(now - 29 * DAY).date()
    )
    young = s.seed(4, formulation_started_at=now - 20 * DAY)
    waiting = s.seed(5, "waiting", waiting_for="Ann")
    stale = s.seed(6, formulation_started_at=now - 35 * DAY)
    ghost = {"id": "task_000000000000", "revision": 1}
    bumped = {"id": stale.id, "revision": stale.revision + 1}
    sid = ok(s.start(entry="restart"))["id"]
    bulk_id = s.nid("bulk")
    with s.step("eligibility is the server's, per item"):
        s.bulk(
            "restart",
            [extended, floored, paused, young, waiting, bumped, ghost],
            id=bulk_id,
            session_id=sid,
        )
    with s.step("a run the owner does not hold is recorded without it"):
        s.bulk("restart", [young], session_id=s.nid("review"))
    with s.step("a stored id is matched before eligibility"):
        s.bulk("restart", [young, extended], id=bulk_id)
        s.bulk(
            "restart",
            [extended, floored, paused, young, waiting, bumped, ghost],
            id=bulk_id,
        )
        s.bulk("inbox_remainder", [extended], id=bulk_id)
        headers = api.key()
        for _ in range(2):
            s.bulk("restart", [young], headers=headers)
    with s.step("Undo restores each clock and skips what changed"):
        task = s.fresh({"id": paused.id})
        s.ok(
            s.patch(
                f"/tasks/{paused.id}",
                {"details": "Edited", "expected_revision": task["revision"]},
            )
        )
        undo_headers = api.key()
        s.undo_bulk(bulk_id, headers=undo_headers)
        s.undo_bulk(bulk_id, headers=undo_headers)
        s.undo_bulk(bulk_id)
        s.undo_bulk(s.nid("bulk"))
    with s.step("an Undo skips a released task that is gone"):
        pair = [
            s.seed(n, formulation_started_at=s.clock() - 40 * DAY) for n in (30, 31)
        ]
        both = ok(s.bulk("restart", pair))
        repo = api.container.task_repo
        with repo.command_lock(api.owner_id):
            repo.delete_task_record(api.owner_id, pair[1].id)
        s.undo_bulk(both["id"])
    with s.step("the Inbox remainder releases and undoes"):
        captured = [s.seed(n, "inbox") for n in (10, 11, 12)]
        processed = s.seed(13, "inbox")
        s.ok(
            s.post(
                f"/tasks/{processed.id}/transitions",
                {"action": "move", "to_state": "next", "expected_revision": 1},
            )
        )
        released = s.bulk(
            "inbox_remainder", [*captured, processed, young], session_id=sid
        )
        s.undo_bulk(ok(released)["id"])
    with s.step("an Undo past its seven days is refused, with or without a sweep"):
        late = s.bulk(
            "restart", [s.seed(20, formulation_started_at=s.clock() - 40 * DAY)]
        )
        inbox = s.bulk("inbox_remainder", [s.seed(21, "inbox")])
        s.tick(days=7, minutes=1)
        s.undo_bulk(ok(inbox)["id"])
        sweep(api.container)
        s.undo_bulk(ok(late)["id"])
        s.get("/review/state")


def due_dates(s: Scenario) -> None:
    """A due date set, moved, removed or kept on tasks in and out of Next."""

    api, ok = s.api, s.ok
    api.activate_at(s.clock() - 30 * DAY)
    in_next = s.task("in next", state="next")
    in_inbox = s.task("in inbox")
    with s.step("a due date changed in Next raises the floor and is logged"):
        for due in ("2026-11-01", "2026-11-05", None, None):
            fresh = s.fresh(in_next)
            s.ok(
                s.patch(
                    f"/tasks/{in_next['id']}",
                    {"due_date": due, "expected_revision": fresh["revision"]},
                )
            )
        s.ok(s.get(f"/tasks/{in_next['id']}"))
    with s.step("outside Next, or with the date kept, nothing is logged"):
        fresh = s.fresh(in_inbox)
        s.ok(
            s.patch(
                f"/tasks/{in_inbox['id']}",
                {"due_date": "2026-11-02", "expected_revision": fresh["revision"]},
            )
        )
        fresh = s.fresh(in_next)
        s.ok(
            s.patch(
                f"/tasks/{in_next['id']}",
                {"details": "Notes only", "expected_revision": fresh["revision"]},
            )
        )
    assert ok(s.get("/review/state"))["explainer_seen"] is True


JOURNEYS: dict[str, Callable[[Scenario], None]] = {
    "due_dates": due_dates,
    "decisions": decisions,
    "undo": undo,
    "parks": parks,
    "settings": settings,
    "sessions": sessions,
    "bulk": bulk,
}


@pytest.mark.parametrize("name", sorted(JOURNEYS))
def test_026_FR_002_026_FR_016_flag_on_and_off_give_identical_review_http_and_rows(
    apps: Apps, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    """026-SC-001: one journey, two engines, the same statuses, bodies and rows."""

    _compare(apps, JOURNEYS[name], caplog)


def test_026_FR_002_reads_ask_the_query_entry_point_and_commands_ask_decide(
    apps: Apps,
) -> None:
    """A read asks ``query`` once, a command ``decide`` at most once, a replay never."""

    sessions(apps.on)
    exchanges = list(zip(apps.on.exchanges, apps.on.deltas, strict=True))
    with allure.step("review state and queues are answered by the core's query"):
        reads = [
            (e, d)
            for e, d in exchanges
            if e.method == "GET"
            and ("/review/state" in e.path or "/review/queues/" in e.path)
        ]
        _evidence("reads", [(e.path, d[1], d[2]) for e, d in reads])
        assert len(reads) > 20
        assert all(d[1] == 0 and d[2] == 1 for _, d in reads)
    with allure.step("other reads of a run touch no rule"):
        runs = [
            d
            for e, d in exchanges
            if e.method == "GET" and "/review/sessions/" in e.path
        ]
        _evidence("runs", runs)
        assert runs and all(d[1] == 0 and d[2] == 0 for d in runs)
    with allure.step("a command asks decide once, and only a replay asks it never"):
        commands = [
            d
            for e, d in exchanges
            if e.method in {"POST", "PATCH", "PUT"} and "review/" in e.path
        ]
        asked = Counter(d[1] for d in commands)
        _evidence("decide calls per command", dict(asked))
        # The journey resends one progress change and one finish under its key.
        assert set(asked) == {0, 1} and asked[0] == 2 and asked[1] > 30


def test_026_FR_014_the_flag_applies_per_command_and_each_side_reads_the_others_rows(
    apps: Apps,
) -> None:
    """On, off, on: each decision follows the flag, and Undo crosses the epochs."""

    s, ok = apps.on, apps.on.ok
    flags = s.api.container.feature_flag_service
    s.api.activate_at(s.clock() - 30 * DAY)
    cards = [s.task(f"card {i}", state="next") for i in range(3)]
    s.tick(days=15)
    cards = [s.fresh(card) for card in cards]
    outcomes = []
    calls = []
    with allure.step("each decision is routed by the flag at that moment"):
        for mode, card in zip(("on", "off", "on"), cards, strict=True):
            flags.set_mode("rust_core_sync", mode, operator_id="parity")
            before = apps.on.core_calls["decide"]
            outcomes.append(ok(s.decide(card, "complete")))
            calls.append(apps.on.core_calls["decide"] - before)
        shapes = [outcome["decision"]["id"] for outcome in outcomes]
        _evidence("core calls per decision", calls)
        _evidence("decision ids", shapes)
        assert calls == [1, 0, 1]
        native = re.compile(r"^decision_[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
        legacy = re.compile(r"^decision_[0-9a-f]{12}$")
        assert native.match(shapes[0]) and legacy.match(shapes[1])
        assert native.match(shapes[2])
    with allure.step("the core undoes a Python decision and Python a core decision"):
        flags.set_mode("rust_core_sync", "on", operator_id="parity")
        python_made = s.undo(outcomes[1])
        flags.set_mode("rust_core_sync", "off", operator_id="parity")
        core_made = s.undo(outcomes[0])
        _evidence("statuses", [python_made.status_code, core_made.status_code])
        assert python_made.status_code == core_made.status_code == 200
        restored = [s.fresh(cards[index])["state"] for index in (0, 1, 2)]
        _evidence("states", restored)
        assert restored == ["next", "next", "completed"]
        flags.set_mode("rust_core_sync", "on", operator_id="parity")


def test_026_FR_014_every_review_command_fails_closed_when_the_core_is_down(
    apps: Apps,
) -> None:
    """A closed core is a retryable 503 for every command and read, with no write."""

    s, ok = apps.on, apps.on.ok
    api = s.api
    api.activate_at(s.clock() - 30 * DAY)
    cards = [s.task(f"card {i}", state="next") for i in range(2)]
    waiting = s.task("held", state="waiting", waiting_for="Ann")
    s.tick(days=15)
    cards = [s.fresh(card) for card in cards]
    sid = ok(s.start())["id"]
    decided = ok(s.decide(cards[0], "complete", session_id=sid))
    released = ok(
        s.bulk("restart", [s.seed(1, formulation_started_at=s.clock() - 40 * DAY)])
    )
    before = s.snapshot()
    facade = api.container.review_service._rust_facade
    assert facade is not None
    facade._core.close()
    fresh_run = s.nid("review")
    calls: dict[str, Callable[[], Any]] = {
        "decide": lambda: s.decide(cards[1], "complete"),
        "undo": lambda: s.undo(decided),
        "auto-park": lambda: s.park(cards[1]),
        "parks": lambda: s.post("/review/parks/acknowledge", {"items": []}),
        "settings": lambda: s.put("/review/settings", {"expected_revision": 1}),
        "explainer": lambda: s.post("/review/explainer/acknowledge", {}),
        "start": lambda: s.start(id=fresh_run),
        "progress": lambda: s.progress(sid, current_step="inbox"),
        "finish": lambda: s.post(f"/review/sessions/{sid}/finish", {}),
        "bulk release": lambda: s.bulk("inbox_remainder", [waiting]),
        "bulk undo": lambda: s.undo_bulk(released["id"]),
        "state": lambda: s.get("/review/state"),
        "queue": lambda: s.get("/review/queues/wins"),
    }
    with allure.step("each command and read is refused as unavailable"):
        statuses = {}
        for name, call in calls.items():
            response = call()
            statuses[name] = response.status_code
            assert "card 1" not in response.text
        _evidence("statuses", statuses)
        assert set(statuses.values()) == {503}
    with allure.step("nothing was written and nothing fell back to Python"):
        check_equal("rows after", s.snapshot(), before)


def test_026_FR_014_an_internal_core_failure_is_a_500_and_writes_nothing(
    apps: Apps, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = apps.on
    s.api.activate_at(s.clock() - 30 * DAY)
    card = s.task("card", state="next")
    s.tick(days=15)
    card = s.fresh(card)
    before = s.snapshot()
    facade = s.api.container.review_service._rust_facade
    assert facade is not None

    def poisoned(*_args: object, **_kwargs: object) -> Any:
        raise RustBridgeError("INTERNAL_ERROR", False, None)

    monkeypatch.setattr(facade._core, "decide", poisoned)
    with allure.step("a poisoned core turns a valid decision into a 500"):
        response = s.decide(card, "cancel")
        _evidence("status", response.status_code)
        assert response.status_code == 500
        assert "card" not in response.text
        check_equal("rows after", s.snapshot(), before)


def test_026_FR_024_the_core_answers_a_client_without_server_only_data(
    apps: Apps,
) -> None:
    """Undo snapshots, park clock-before and progress digests stay server-side."""

    parks(apps.on)
    forbidden = (
        "private",
        "clock_before",
        "task_before",
        "applied_progress",
        "finished_empty",
        "from_revision",
        "last_effective_sweep_at",
        "threshold_changed_at",
        "undo",
    )
    with allure.step("what the core answers a read carries none of it"):
        text = json.dumps(apps.queries)
        found = [key for key in forbidden if f'"{key}"' in text]
        _evidence("queries answered", len(apps.queries))
        _evidence("server-only keys found", found)
        assert apps.queries and not found
    with allure.step("no REST body carries it either"):
        bodies = json.dumps([e.body for e in apps.on.exchanges])
        leaked = [key for key in forbidden if f'"{key}"' in bodies]
        _evidence("server-only keys found", leaked)
        assert not leaked


def test_026_FR_024_every_zone_the_server_accepts_the_core_accepts() -> None:
    """The IANA check moved to the core: it must not narrow what Python allowed."""

    now = FrozenClock().now
    stored = encode_settings_private(rd.ReviewSettingsDocument(owner_id="owner"))
    names = sorted(available_timezones()) + ["localtime", "Mars/Olympus", "utc"]
    differing: list[str] = []
    with (
        RustCore() as core,
        allure.step("each zone name is judged by the core and by Python"),
    ):
        for name in names:
            decision = core.decide(
                {"settings": stored},
                _envelope(
                    "review.settings",
                    "rest",
                    {"time_zone": name},
                    now,
                    ("review_settings", "rest", 1),
                ),
                _inputs(now, "owner"),
            )
            if (decision.refusal is None) != is_iana_zone(name):
                differing.append(name)
        _evidence("zones judged", len(names))
        _evidence("zones judged differently", differing)
        assert len(names) > 400 and not differing


def test_026_FR_024_core_refusals_keep_the_errors_the_review_adapter_always_raised() -> (
    None
):
    def refusal(
        reason: str, field: str | None, entity: tuple[str, list[str]] | None
    ) -> DomainRefusal:
        return DomainRefusal(reason, field, entity, None)

    task = ("task", ["task_x"])
    cases: list[tuple[DomainRefusal, type[Exception], str]] = [
        (
            refusal("id_already_exists", "replace_open", ("review_session", ["r_x"])),
            ReviewRefused,
            "open_session_exists",
        ),
        (
            refusal("id_already_exists", "id", ("review_session", ["r_x"])),
            ReviewRefused,
            "id_conflict",
        ),
        (refusal("id_already_exists", None, task), ReviewRefused, "id_conflict"),
        (
            refusal("step_not_in_review", "step", None),
            ReviewRefused,
            "step_outside_run",
        ),
        (refusal("text_length", "details", None), ReviewRefused, "details_too_long"),
        (refusal("undo_unavailable", None, task), ReviewRefused, "undo_unavailable"),
        (
            refusal("formulation_changed", None, task),
            ConflictError,
            "Task 'task_x' has newer changes; reload before saving.",
        ),
        (
            refusal("revision_conflict", None, ("review_settings", ["rest"])),
            ConflictError,
            "Review settings have newer changes; reload before saving.",
        ),
        (
            refusal("not_found", None, ("review_decision", ["decision_x"])),
            NotFoundError,
            "Review decision 'decision_x' was not found.",
        ),
        (
            refusal("not_found", None, ("review_bulk_release", ["bulk_x"])),
            NotFoundError,
            "Review bulk release 'bulk_x' was not found.",
        ),
        (
            refusal("session_not_found", None, ("review_session", ["review_x"])),
            NotFoundError,
            "Review session 'review_x' was not found.",
        ),
        (
            refusal("not_found", None, ("somewhere_new", ["x"])),
            NotFoundError,
            "Record 'x' was not found.",
        ),
        (
            refusal("incomplete_read_set", None, ("project", ["project_x"])),
            NotFoundError,
            "Project 'project_x' was not found.",
        ),
        (
            refusal("incomplete_read_set", None, task),
            RustBridgeError,
            "The Rust core is unavailable (INTERNAL_ERROR).",
        ),
        (
            refusal("reason_from_a_newer_core", "title", None),
            ValidationFailure,
            "Command failed validation.",
        ),
    ]
    with allure.step("each refusal maps to the exception Python always raised"):
        for item, kind, text in cases:
            error = _refusal_error(item, "owner-1")
            attach_json(
                item.reason,
                {
                    "entity": item.entity,
                    "error": type(error).__name__,
                    "text": str(error),
                },
            )
            assert isinstance(error, kind)
            if isinstance(error, ReviewRefused):
                assert error.reason == text
            else:
                assert str(error) == text


def test_026_FR_024_a_change_the_facade_cannot_place_is_refused_not_applied() -> None:
    odd = {
        "outcome": "applied",
        "changes": [
            {
                "operation": "upsert",
                "entity_type": "review_navigator_consent",
                "value": {},
            }
        ],
    }
    gone = {
        "outcome": "applied",
        "changes": [
            {"operation": "tombstone", "entity_type": "task", "record_key": ["task_x"]}
        ],
    }
    with allure.step("an unknown record kind is a validation failure, not a write"):
        with pytest.raises(ValidationFailure) as refused:
            _records(odd)
        _evidence("detail", refused.value.detail)
        assert refused.value.detail == {"reason": "unexpected_record"}
    with allure.step("a tombstone is kept apart from the upserts"):
        records = _records(gone)
        _evidence("tombstones", records.tombstones)
        assert records.tombstones == [("task", ["task_x"])] and not records.tasks


def test_026_FR_024_stored_rows_without_their_private_members_decode_as_public() -> (
    None
):
    with allure.step("a park row keeps the private members of the stored row"):
        value = {
            "task_id": "task_x",
            "formulation_id": "form_x",
            "parked_at": "2026-10-09T12:00:00Z",
            "seen_at": None,
            "returned_at": "2026-10-10T12:00:00Z",
        }
        stored = rd.ReviewParkAckDocument(
            owner_id="owner-1",
            task_id="task_x",
            formulation_id="form_x",
            parked_at=FrozenClock().now,
            from_revision=3,
            source="sweep",
        )
        ack = decode_ack(value, owner_id="owner-1", before=stored)
        _evidence("ack", ack.model_dump(mode="json"))
        assert (ack.from_revision, ack.source) == (3, "sweep")
        assert ack.returned_at is not None
    with allure.step("a decision without the Undo snapshot decodes without one"):
        decision = decode_decision(
            {
                "id": "decision_x",
                "type": "keep_waiting",
                "task_id": "task_x",
                "session_id": None,
                "decided_at": "2026-10-09T12:00:00Z",
                "substantive": None,
                "stall_reason": None,
                "ai_use": "none",
                "yielded_auto_park": False,
                "formulation_id": None,
                "task_revision_before": "1",
                "task_revision_after": "1",
                "created_task_id": None,
                "navigator_request_id": None,
                "review_counts_as": "kept",
                "client_decided_at": None,
                "reason_text": None,
                "undo_available_until": None,
            },
            owner_id="owner-1",
            task=None,
        )
        _evidence("undo", decision.undo)
        assert decision.undo is None


def test_026_FR_024_the_repeat_locator_names_only_what_the_core_named() -> None:
    def stored(kind: str, **fields: Any) -> rd.ReviewDecisionDocument:
        return rd.ReviewDecisionDocument.model_validate(
            {
                "id": f"decision_{kind}",
                "owner_id": "owner-1",
                "task_id": "task_x",
                "decided_at": FrozenClock().now,
                "type": kind,
                "task_revision_before": 1,
                "task_revision_after": 1,
                "review_counts_as": "kept",
                **fields,
            }
        )

    task = TaskDocument.model_validate(
        {
            "id": "task_x",
            "owner_id": "owner-1",
            "title": "t",
            "state": "waiting",
            "order_key": 0,
            "created_at": FrozenClock().now,
            "updated_at": FrozenClock().now,
        }
    )
    reform = DecisionRequest.model_validate(
        {
            "type": "reformulate",
            "expected_revision": 1,
            "formulation_id": "form_000000000001",
            "title": "t",
        }
    )
    keep = DecisionRequest.model_validate(
        {"type": "keep_waiting", "expected_revision": 1}
    )
    cosmetic = stored(
        "reformulate", substantive=False, formulation_id="form_000000000001"
    )
    with allure.step("a cosmetic reformulate of the same formulation is the repeat"):
        elsewhere = stored(
            "reformulate", substantive=False, formulation_id="form_000000000002"
        )
        found = _first_of_run(reform, task, [stored("complete"), elsewhere, cosmetic])
        _evidence("found", found and found.id)
        assert found == cosmetic
        assert _first_of_run(reform, task, [elsewhere]) is None
    with allure.step("a keep or follow-up of the task as it is now is the repeat"):
        moved = stored("keep_waiting", task_revision_after=4)
        same = stored("follow_up")
        assert _first_of_run(keep, task, [stored("complete"), moved, same]) == same
        assert _first_of_run(keep, task, [moved]) is None
        _evidence("found", same.id)


def test_026_FR_014_a_repeat_the_adapter_cannot_find_fails_closed(
    apps: Apps, monkeypatch: pytest.MonkeyPatch
) -> None:
    s, ok = apps.on, apps.on.ok
    s.api.activate_at(s.clock() - 30 * DAY)
    sid = ok(s.start())["id"]
    card = s.task("Call Bob", state="next")
    s.tick(days=15)
    card = s.fresh(card)
    first = ok(s.decide(card, "reformulate", session_id=sid, title="call bob."))
    before = s.snapshot()
    monkeypatch.setattr(
        "app.modules.tasks.rust_review_facade._first_of_run", lambda *a: None
    )
    with allure.step("the core names a repeat the adapter cannot place"):
        response = s.decide(
            s.fresh(first["task"]), "reformulate", session_id=sid, title="call bob!"
        )
        _evidence("status", response.status_code)
        assert response.status_code == 500
        check_equal("rows after", s.snapshot(), before)


def test_026_FR_024_a_query_refusal_other_than_a_missing_run_is_passed_on(
    apps: Apps, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = apps.on
    facade = s.api.container.review_service._rust_facade
    assert facade is not None

    def refused(*_args: object, **_kwargs: object) -> Any:
        raise ValidationFailure("Query refused.", {"reason": "review_unavailable"})

    monkeypatch.setattr(facade._core, "query", refused)
    with allure.step("the refusal reaches the client as a validation error"):
        response = s.get("/review/queues/wins")
        _evidence("status", response.status_code)
        _evidence("body", response.json())
        assert response.status_code == 400


def test_026_FR_024_a_follow_up_reads_its_project_only_when_it_exists(
    apps: Apps,
) -> None:
    s = apps.on
    facade = s.api.container.review_service._rust_facade
    assert facade is not None
    owner = s.api.owner_id
    orphan = TaskDocument.model_validate(
        {
            "id": "task_00000000beef",
            "owner_id": owner,
            "title": "Orphan",
            "state": "waiting",
            "project_id": "project_00000000dead",
            "order_key": 0,
            "created_at": s.clock(),
            "updated_at": s.clock(),
        }
    )
    payload = DecisionRequest.model_validate(
        {"type": "follow_up", "expected_revision": 1, "title": "Chase"}
    )
    read_set: dict[str, Any] = {"tasks": {}, "projects": {}}
    with allure.step("a project that is not stored is simply absent"):
        facade._decide_references(read_set, orphan, payload, owner)
        _evidence("read set", read_set)
        assert read_set["projects"] == {}
        assert facade._project_or_none(owner, "project_00000000dead") is None


def test_026_FR_016_a_due_date_moved_in_next_logs_the_same_line_with_the_flag_on_and_off(
    apps: Apps, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-046: the content-free event is written where the floor moves."""

    caplog.set_level(logging.INFO, logger="app.modules.tasks.review")
    lines: dict[str, list[str]] = {}
    with allure.step("run the due-date journey with rust_core_sync OFF and ON"):
        for label, scenario in (("OFF", apps.off), ("ON", apps.on)):
            caplog.clear()
            due_dates(scenario)
            lines[label] = [
                _OWNER.sub("<owner>", scenario.namer(r.getMessage()))
                for r in caplog.records
                if "review_due_date_moved" in r.getMessage()
            ]
        _evidence("lines", lines)
    with allure.step("three changes in Next are logged identically"):
        check_equal("ON lines", lines["ON"], lines["OFF"])
        assert len(lines["ON"]) == 3


def test_026_FR_016_a_settings_write_between_two_reads_cannot_split_the_state_response(
    apps: Apps, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The state answer is derived from one settings snapshot, and says so."""

    s, ok = apps.on, apps.on.ok
    api = s.api
    api.activate_at(s.clock() - 30 * DAY)
    repo = api.container.task_repo
    original = repo.get_review_settings
    reads: list[int] = []

    def read_then_change(owner_id: str) -> Any:
        stored = original(owner_id)
        reads.append(1)
        if len(reads) == 1:
            # A PUT /review/settings commits right after the first read.
            assert stored is not None
            repo.save_review_settings(
                stored.model_copy(
                    update={
                        "review_weekday": 2,
                        "review_time": "09:30",
                        "revision": stored.revision + 1,
                    }
                )
            )
        return stored

    monkeypatch.setattr(repo, "get_review_settings", read_then_change)
    with allure.step("a write lands after the first settings read of a state read"):
        body = ok(s.get("/review/state"))
        monkeypatch.undo()
        _evidence("settings", body["settings"])
        _evidence("next_review_at", body["next_review_at"])
        _evidence("settings reads", len(reads))
    with allure.step("the settings and what was derived from them agree"):
        due = datetime.fromisoformat(body["next_review_at"].replace("Z", "+00:00"))
        slot = (due.isoweekday(), f"{due:%H:%M}")
        shown = (body["settings"]["review_weekday"], body["settings"]["review_time"])
        check_equal("next review slot", slot, shown)
        assert len(reads) == 1
    with allure.step("the next read sees the committed change"):
        later = ok(s.get("/review/state"))
        check_equal("settings revision", later["settings"]["revision"], 2)
        assert later["settings"]["review_weekday"] == 2
