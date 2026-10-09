"""Spec 026 T018 (PR-18): the Rust-backed task facade changes no HTTP outcome.

With ``rust_core_sync`` ON the task and organization commands are decided by the
shared Rust rules (``RustTaskFacade``); OFF they keep their Python rules. These
tests drive one scripted journey through two otherwise identical apps and prove

* every status and body (success, refusal, replay) is the same once generated
  IDs are named by order of appearance, and the stored documents match too;
* each supported command asks the core exactly once, and the OFF app never does;
* a bridge failure fails closed (no Python fallback, nothing written), and the
  flag takes effect per command in both directions.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.exceptions import ConflictError, ValidationFailure
from app.modules.tasks.domain import (
    ClockBeforeDocument,
    TaskDocument,
    TaskParkDocument,
)
from app.modules.tasks.review_domain import ReviewParkAckDocument
from app.modules.tasks.rust_adapter import (
    Decision,
    DomainRefusal,
    RustBridgeError,
    RustCore,
)
from app.modules.tasks.rust_task_facade import (
    RustTaskFacade,
    _envelope,
    _inputs,
    _parse_instant,
    _refused,
)
from app.schemas.tasks import TaskCreateRequest

from .conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    FrozenClock,
    _build_authenticated_client,
)

SEED_FORMULATION = "form_00000000000a"
CLIENT_FORMULATION = "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11"
_ID = re.compile(
    r"\b(task|project|tag|form)_(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{12})\b"
)


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _evidence(name: str, content: object) -> None:
    allure.attach(
        content if isinstance(content, str) else json.dumps(content, indent=2),
        name=name,
        attachment_type=allure.attachment_type.TEXT,
    )


class IdNamer:
    """Names generated IDs by order of first appearance, per run."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def __call__(self, text: str) -> str:
        def name(match: re.Match[str]) -> str:
            kind = match.group(1)
            known = self._names.setdefault(
                match.group(0), f"<{kind}#{len(self._names) + 1}>"
            )
            return known

        return _ID.sub(name, text)


@dataclass
class Outcome:
    label: str
    status: int
    body: Any
    decisions: int


@dataclass
class Run:
    """One scripted journey against one app."""

    client: TestClient
    clock: FrozenClock
    decisions: Callable[[], int]
    namer: IdNamer = field(default_factory=IdNamer)
    outcomes: list[Outcome] = field(default_factory=list)
    alias: dict[str, str] = field(default_factory=dict)
    revision: dict[str, int] = field(default_factory=dict)
    counter: int = 0

    def rev(self, name: str) -> int:
        return self.revision[self.alias[name]]

    def call(
        self,
        method: str,
        path: str,
        label: str,
        *,
        body: dict[str, Any] | Callable[[Run], dict[str, Any]] | None = None,
        bind: str | None = None,
        key: str | None = None,
        params: dict[str, Any] | Callable[[Run], dict[str, Any]] | None = None,
    ) -> Outcome:
        self.counter += 1
        self.clock.advance(minutes=1)
        url = "/api" + path.format(**self.alias)
        payload = body(self) if callable(body) else body
        before = self.decisions()
        response = self.client.request(
            method,
            url,
            json=payload,
            params=params(self) if callable(params) else params,
            headers={
                "Idempotency-Key": key or f"key-{self.counter}",
                "X-Correlation-ID": f"corr-{self.counter}",
            },
        )
        decoded = response.json() if response.content else None
        if isinstance(decoded, dict) and "id" in decoded and "revision" in decoded:
            self.revision[decoded["id"]] = decoded["revision"]
            if bind is not None:
                self.alias[bind] = decoded["id"]
        outcome = Outcome(
            label,
            response.status_code,
            json.loads(self.namer(json.dumps(decoded, sort_keys=True))),
            self.decisions() - before,
        )
        self.outcomes.append(outcome)
        return outcome


def _journey(r: Run) -> None:
    """Task, project and tag commands: success, refusal, replay and ordering."""

    _creations(r)
    _updates(r)
    _transitions(r)
    _projects(r)
    _tags(r)


def _creations(r: Run) -> None:
    """Project, tag and task creation."""

    p, post = r.call, "POST"
    p(
        post,
        "/projects",
        "project create",
        bind="garden",
        body={"name": "Garden", "color": "green", "desired_outcome": "  Veg by June "},
    )
    p(post, "/projects", "project duplicate name", body={"name": " garden "})
    p(post, "/projects", "project errands", bind="errands", body={"name": "Errands"})
    p(post, "/tags", "tag create", bind="work", body={"name": "@Work"})
    p(post, "/tags", "tag duplicate", body={"name": "work"})
    p(post, "/tags", "tag home", bind="home", body={"name": "Home"})
    p(
        post,
        "/tasks",
        "task inbox",
        bind="a",
        body={"title": "Inbox task", "details": "d"},
    )
    p(post, "/tasks", "task second inbox", bind="a2", body={"title": "Second inbox"})
    p(
        post,
        "/tasks",
        "task next with references",
        bind="b",
        body=lambda r: {
            "title": "Plan trip",
            "state": "next",
            "project_id": r.alias["garden"],
            "tag_ids": [r.alias["work"], r.alias["home"]],
            "due_date": "2026-10-20",
            "priority": "high",
        },
    )
    p(
        post,
        "/tasks",
        "task next client formulation",
        bind="n2",
        body={
            "title": "Client formulation",
            "state": "next",
            "new_formulation_id": CLIENT_FORMULATION,
        },
    )
    p(
        post,
        "/tasks",
        "task waiting needs a note",
        body={"title": "w", "state": "waiting"},
    )
    p(
        post,
        "/tasks",
        "task waiting",
        bind="d",
        body={"title": "Wait for reply", "state": "waiting", "waiting_for": "  Sam  "},
    )
    p(
        post,
        "/tasks",
        "task unknown project",
        body={"title": "x", "project_id": "project_000000000000"},
    )
    p(
        post,
        "/tasks",
        "task duplicate tags",
        body=lambda r: {"title": "x", "tag_ids": [r.alias["work"], r.alias["work"]]},
    )
    p(
        post,
        "/tasks",
        "task source captures",
        body={"title": "x", "source_capture_ids": ["capture_1"]},
    )
    p(
        post,
        "/tasks",
        "task someday",
        bind="s",
        body={"title": "Maybe", "state": "someday"},
    )
    p(post, "/tasks", "task replay first", key="replay-1", body={"title": "Replayed"})
    p(
        post,
        "/tasks",
        "task replay same key",
        key="replay-1",
        body={"title": "Replayed"},
    )
    p(post, "/tasks", "task replay other body", key="replay-1", body={"title": "Other"})


def _updates(r: Run) -> None:
    """Task updates: references, patches, ordering and replay."""

    p, patch = r.call, "PATCH"
    p(patch, "/tasks/{a}", "update stale", body={"title": "x", "expected_revision": 99})
    p(
        patch,
        "/tasks/{a}",
        "update null title",
        body={"title": None, "expected_revision": 1},
    )
    p(
        patch,
        "/tasks/{a}",
        "update null title stale",
        body={"title": None, "expected_revision": 9},
    )
    p(
        patch,
        "/tasks/{a}",
        "update null priority",
        body={"priority": None, "expected_revision": 1},
    )
    p(
        patch,
        "/tasks/{a}",
        "update waiting_for off waiting",
        body={"waiting_for": "x", "expected_revision": 1},
    )
    p(
        patch,
        "/tasks/{a}",
        "update details and priority",
        body={"details": None, "priority": "low", "expected_revision": 1},
    )
    p(
        patch,
        "/tasks/{a}",
        "update replay",
        key="upd-1",
        body=lambda r: {"title": "Inbox task v2", "expected_revision": r.rev("a")},
    )
    p(
        patch,
        "/tasks/{a}",
        "update replay same key",
        key="upd-1",
        body=lambda r: {"title": "Inbox task v2", "expected_revision": r.rev("a") - 1},
    )
    p(
        patch,
        "/tasks/{b}",
        "update tag order",
        body=lambda r: {
            "tag_ids": [r.alias["home"], r.alias["work"]],
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update duplicate tags",
        body=lambda r: {
            "tag_ids": [r.alias["work"], r.alias["work"]],
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update unknown tag",
        body=lambda r: {
            "tag_ids": ["tag_000000000000"],
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update substantive title in next",
        body=lambda r: {
            "title": "Plan the whole trip",
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update cosmetic title in next",
        body=lambda r: {
            "title": "plan the whole trip!",
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update due date",
        body=lambda r: {"due_date": "2026-11-01", "expected_revision": r.rev("b")},
    )
    p(
        patch,
        "/tasks/{b}",
        "update clear due date",
        body=lambda r: {"due_date": None, "expected_revision": r.rev("b")},
    )
    p(
        patch,
        "/tasks/{b}",
        "update project",
        body=lambda r: {
            "project_id": r.alias["errands"],
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update unknown project",
        body=lambda r: {
            "project_id": "project_000000000000",
            "expected_revision": r.rev("b"),
        },
    )
    p(
        patch,
        "/tasks/{b}",
        "update clear project",
        body=lambda r: {"project_id": None, "expected_revision": r.rev("b")},
    )
    p(
        patch,
        "/tasks/{b}",
        "update clear tags",
        body=lambda r: {"tag_ids": None, "expected_revision": r.rev("b")},
    )
    p(
        patch,
        "/tasks/{b}",
        "update nothing",
        body=lambda r: {"expected_revision": r.rev("b")},
    )
    p(
        patch,
        "/tasks/{d}",
        "update waiting note",
        body=lambda r: {"waiting_for": "  Pat ", "expected_revision": r.rev("d")},
    )
    p(
        patch,
        "/tasks/{d}",
        "update blank waiting note",
        body=lambda r: {"waiting_for": "   ", "expected_revision": r.rev("d")},
    )
    p(
        patch,
        "/tasks/{d}",
        "update null waiting note",
        body=lambda r: {"waiting_for": None, "expected_revision": r.rev("d")},
    )
    p(
        patch,
        "/tasks/task_000000000000",
        "update unknown task",
        body={"title": "x", "expected_revision": 1},
    )


def _transitions(r: Run) -> None:
    """Task transitions across the four lists and the closed states."""

    p, post = r.call, "POST"

    def move(state: str | None, action: str = "move", **more: Any):
        return lambda r: {
            "action": action,
            "to_state": state,
            "expected_revision": r.rev("a"),
            **more,
        }

    p(post, "/tasks/{a}/transitions", "move to next", body=move("next"))
    p(post, "/tasks/{a}/transitions", "move to same list", body=move("next"))
    p(post, "/tasks/{a}/transitions", "move without destination", body=move(None))
    p(
        post,
        "/tasks/{a}/transitions",
        "move to waiting without note",
        body=move("waiting"),
    )
    p(
        post,
        "/tasks/{a}/transitions",
        "move stale",
        body={"action": "move", "to_state": "someday", "expected_revision": 1},
    )
    p(post, "/tasks/{a}/transitions", "complete", body=move(None, "complete"))
    p(post, "/tasks/{a}/transitions", "complete again", body=move(None, "complete"))
    p(post, "/tasks/{a}/transitions", "cancel closed", body=move(None, "cancel"))
    p(post, "/tasks/{a}/transitions", "move closed", body=move("inbox"))
    p(
        post,
        "/tasks/{a}/transitions",
        "reopen without destination",
        body=move(None, "reopen"),
    )
    p(
        post,
        "/tasks/{a}/transitions",
        "reopen to waiting without note",
        body=move("waiting", "reopen"),
    )
    p(
        post,
        "/tasks/{a}/transitions",
        "reopen to waiting",
        body=move("waiting", "reopen", waiting_for=" Lee "),
    )
    p(post, "/tasks/{a}/transitions", "reopen open task", body=move("inbox", "reopen"))
    p(post, "/tasks/{a}/transitions", "cancel", body=move(None, "cancel"))
    p(
        post,
        "/tasks/{a}/transitions",
        "reopen to next with client id",
        body=move(
            "next",
            "reopen",
            new_formulation_id=CLIENT_FORMULATION.replace("5b0f", "6b0f"),
        ),
    )
    p(
        post,
        "/tasks/{a2}/transitions",
        "move to next server formulation",
        body=lambda r: {
            "action": "move",
            "to_state": "next",
            "expected_revision": r.rev("a2"),
        },
    )
    p(
        post,
        "/tasks/{n2}/transitions",
        "next to someday",
        body=lambda r: {
            "action": "move",
            "to_state": "someday",
            "expected_revision": r.rev("n2"),
        },
    )
    p(
        post,
        "/tasks/{n2}/transitions",
        "someday back to next",
        body=lambda r: {
            "action": "move",
            "to_state": "next",
            "expected_revision": r.rev("n2"),
        },
    )
    p(
        post,
        "/tasks/{d}/transitions",
        "waiting to inbox",
        body=lambda r: {
            "action": "move",
            "to_state": "inbox",
            "expected_revision": r.rev("d"),
        },
    )
    p(
        post,
        "/tasks/{d}/transitions",
        "replay",
        key="move-1",
        body=lambda r: {"action": "complete", "expected_revision": r.rev("d")},
    )
    p(
        post,
        "/tasks/{d}/transitions",
        "replay same key",
        key="move-1",
        body=lambda r: {"action": "complete", "expected_revision": r.rev("d") - 1},
    )
    p(
        post,
        "/tasks/task_000000000000/transitions",
        "transition unknown task",
        body={"action": "complete", "expected_revision": 1},
    )


def _projects(r: Run) -> None:
    """Project update, archive and unarchive."""

    p, post, patch = r.call, "POST", "PATCH"
    p(
        patch,
        "/projects/{errands}",
        "project update clash",
        body=lambda r: {"name": "GARDEN", "expected_revision": r.rev("errands")},
    )
    p(
        patch,
        "/projects/{garden}",
        "project update stale",
        body={"name": "x", "expected_revision": 9},
    )
    p(
        patch,
        "/projects/{garden}",
        "project rename",
        body=lambda r: {
            "name": "  Garden  Beds ",
            "color": None,
            "desired_outcome": "  ",
            "expected_revision": r.rev("garden"),
        },
    )
    p(
        patch,
        "/projects/{garden}",
        "project outcome",
        body=lambda r: {
            "desired_outcome": " Tomatoes ",
            "expected_revision": r.rev("garden"),
        },
    )
    p(
        post,
        "/projects/{garden}/archive",
        "project archive stale",
        body={"expected_revision": 99},
    )
    p(
        post,
        "/projects/{garden}/archive",
        "project archive",
        body=lambda r: {"expected_revision": r.rev("garden")},
    )
    p(
        post,
        "/projects/{garden}/archive",
        "project archive repeat",
        body=lambda r: {"expected_revision": r.rev("garden")},
    )
    p(
        patch,
        "/projects/{garden}",
        "archived project rename",
        body=lambda r: {"name": "Beds", "expected_revision": r.rev("garden")},
    )
    p(
        post,
        "/tasks",
        "task in archived project",
        body=lambda r: {"title": "x", "project_id": r.alias["garden"]},
    )
    p(
        patch,
        "/tasks/{s}",
        "update to archived project",
        body=lambda r: {
            "project_id": r.alias["garden"],
            "expected_revision": r.rev("s"),
        },
    )
    p(
        post,
        "/projects",
        "project takes archived name",
        bind="beds",
        body={"name": "Beds"},
    )
    p(
        post,
        "/projects/{garden}/unarchive",
        "project unarchive clash",
        body=lambda r: {"expected_revision": r.rev("garden")},
    )
    p(
        post,
        "/projects/{beds}/unarchive",
        "project unarchive active",
        body={"expected_revision": 99},
    )
    p(
        patch,
        "/projects/{beds}",
        "project rename away",
        body=lambda r: {"name": "Beds 2", "expected_revision": r.rev("beds")},
    )
    p(
        post,
        "/projects/{garden}/unarchive",
        "project unarchive stale",
        body={"expected_revision": 99},
    )
    p(
        post,
        "/projects/{garden}/unarchive",
        "project unarchive",
        body=lambda r: {"expected_revision": r.rev("garden")},
    )
    p(
        post,
        "/projects/project_000000000000/archive",
        "archive unknown project",
        body={"expected_revision": 1},
    )


def _tags(r: Run) -> None:
    """Tag update and delete, and the reads that follow."""

    p, post, patch = r.call, "POST", "PATCH"
    p(
        patch,
        "/tags/{home}",
        "tag update clash",
        body=lambda r: {"name": "work", "expected_revision": r.rev("home")},
    )
    p(
        patch,
        "/tags/{home}",
        "tag update stale",
        body={"name": "x", "expected_revision": 9},
    )
    p(
        patch,
        "/tags/{home}",
        "tag rename",
        body=lambda r: {"name": " @House  Chores ", "expected_revision": r.rev("home")},
    )
    p(
        post,
        "/tasks",
        "task with tags",
        bind="t1",
        body=lambda r: {
            "title": "Tagged",
            "tag_ids": [r.alias["work"], r.alias["home"]],
        },
    )
    p(
        "DELETE",
        "/tags/{work}",
        "tag delete stale",
        params=lambda r: {"expected_revision": 99},
    )
    p(
        "DELETE",
        "/tags/{work}",
        "tag delete",
        params=lambda r: {"expected_revision": r.rev("work")},
    )
    p("GET", "/tasks/{t1}", "task lost the deleted tag")
    p("GET", "/tasks/{b}", "other task untouched by delete")
    p(
        "DELETE",
        "/tags/{work}",
        "tag delete repeat",
        params=lambda r: {"expected_revision": r.rev("work")},
    )
    p(
        patch,
        "/tags/{work}",
        "deleted tag rename",
        body=lambda r: {"name": "Work again", "expected_revision": r.rev("work")},
    )
    p(
        post,
        "/tasks",
        "task with deleted tag",
        body=lambda r: {"title": "x", "tag_ids": [r.alias["work"]]},
    )
    p(
        "DELETE",
        "/tags/tag_000000000000",
        "delete unknown tag",
        params={"expected_revision": 1},
    )
    p("GET", "/tasks", "list tasks")
    p("GET", "/projects", "list projects", params={"state": "all"})
    p("GET", "/tags", "list tags")


def _edges(r: Run) -> None:
    """Refusal order, a stored review setting and parked tasks: the rarer arms."""

    p, post, patch = r.call, "POST", "PATCH"
    absent_project, absent_tag = "project_000000000000", "tag_000000000000"
    p(post, "/projects", "edge project", bind="garden", body={"name": "Garden"})
    p(post, "/tags", "edge tag", bind="work", body={"name": "Work"})
    p(
        post,
        "/tasks",
        "edge task in next",
        bind="t",
        body=lambda r: {
            "title": "Plan trip",
            "state": "next",
            "tag_ids": [r.alias["work"]],
        },
    )
    p(
        patch,
        "/tasks/{t}",
        "null title and null priority",
        body=lambda r: {
            "title": None,
            "priority": None,
            "expected_revision": r.rev("t"),
        },
    )
    p(
        patch,
        "/tasks/{t}",
        "null title before an unknown project",
        body=lambda r: {
            "title": None,
            "project_id": absent_project,
            "expected_revision": r.rev("t"),
        },
    )
    p(
        patch,
        "/tasks/{t}",
        "duplicate tags before an unknown tag",
        body=lambda r: {
            "tag_ids": [absent_tag, absent_tag],
            "expected_revision": r.rev("t"),
        },
    )
    p(
        patch,
        "/tasks/{t}",
        "substantive title with a client formulation",
        body=lambda r: {
            "title": "Plan the whole summer trip",
            "new_formulation_id": CLIENT_FORMULATION.replace("5b0f", "7b0f"),
            "expected_revision": r.rev("t"),
        },
    )
    # The review clock settings are stored lazily; once they are, every task
    # decision reads them.
    p("GET", "/review/state", "review state stores the settings")
    p(
        patch,
        "/tasks/{t}",
        "update with stored review settings",
        body=lambda r: {"details": "Book trains", "expected_revision": r.rev("t")},
    )
    p(
        post,
        "/tasks/{t}/transitions",
        "move with stored review settings",
        body=lambda r: {
            "action": "move",
            "to_state": "someday",
            "expected_revision": r.rev("t"),
        },
    )
    p(
        patch,
        "/tasks/task_seedparked01",
        "update a parked task keeps its park",
        body={"details": "still parked", "expected_revision": 4},
    )
    p(
        post,
        "/tasks/task_seedparked02/transitions",
        "return a parked task without its acknowledgement",
        body={"action": "move", "to_state": "next", "expected_revision": 4},
    )


def _seed_parked(
    client: TestClient, task_id: str = "task_seedparked01", *, ack: bool = True
) -> str:
    """A parked Someday task (and, unless ``ack`` is off, its park ack) in the store."""

    owner = client.get("/api/account").json()["id"]
    repo = _container(client).task_service.task_repo
    at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    repo.create(
        TaskDocument(
            id=task_id,
            owner_id=owner,
            title="Parked",
            state="someday",
            order_key=0,
            created_at=at,
            updated_at=at,
            revision=4,
            consecutive_stalled_formulations=2,
            parked=TaskParkDocument(
                at=at,
                formulation_id=SEED_FORMULATION,
                from_revision=3,
                clock_before=ClockBeforeDocument(
                    started_at=at, extended_at=None, stalled_before=1
                ),
            ),
        )
    )
    if ack:
        repo.save_park_ack(
            ReviewParkAckDocument(
                owner_id=owner,
                task_id=task_id,
                formulation_id=SEED_FORMULATION,
                parked_at=at,
                from_revision=3,
                source="sweep",
            )
        )
    return task_id


def _without_owner(document: Any) -> Any:
    """A stored document as JSON without its (per-app) owner ID."""

    dumped = (
        json.loads(document.model_dump_json())
        if hasattr(document, "model_dump_json")
        else document
    )
    return {key: value for key, value in dumped.items() if key != "owner_id"}


def _snapshot(client: TestClient, namer: IdNamer) -> Any:
    """Every stored document of the owner, named like the responses are."""

    owner = client.get("/api/account").json()["id"]
    repo = _container(client).task_service.task_repo
    documents = [
        *(("task", t.title, t) for t in repo.list_for_owner(owner_id=owner)),
        *(("project", p.name, p) for p in repo.list_projects_for_owner(owner_id=owner)),
        *(("tag", g.name, g) for g in repo.list_tags_for_owner(owner_id=owner)),
        *(("ack", a.task_id, a) for a in repo.list_park_acks(owner)),
    ]
    dumped = [
        (kind, name, _without_owner(doc))
        for kind, name, doc in sorted(documents, key=lambda item: item[:2])
    ]
    return json.loads(namer(json.dumps(dumped, sort_keys=True)))


@dataclass
class Apps:
    off: TestClient
    on: TestClient
    clocks: tuple[FrozenClock, FrozenClock]
    on_decisions: list[int]


@pytest.fixture
def apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Apps]:
    clients = []
    for subdir in ("parity-off", "parity-on"):
        client, _ = _build_authenticated_client(
            tmp_path,
            monkeypatch,
            subdir=subdir,
            email=TEST_USER_EMAIL,
            password=TEST_USER_PASSWORD,
        )
        clients.append(client)
    off, on = clients
    clocks = (FrozenClock(), FrozenClock())
    for client, clock in zip(clients, clocks, strict=True):
        clock.install(_container(client))
    _container(on).feature_flag_service.set_mode(
        "rust_core_sync", "on", operator_id="parity"
    )
    counter = [0]
    facade = _container(on).task_service._rust_facade
    assert facade is not None
    core = facade._core
    original = core.decide

    def counted(*args: Any, **kwargs: Any) -> Any:
        counter[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(core, "decide", counted)
    yield Apps(off, on, clocks, counter)
    for client in clients:
        client.close()


def _run(client: TestClient, clock: FrozenClock, decisions: Callable[[], int]) -> Run:
    return Run(client, clock, decisions)


def test_026_FR_002_flag_on_and_off_give_identical_task_and_organization_http(
    apps: Apps,
) -> None:
    """026-SC-001: one journey, two engines, the same statuses, bodies and rows."""

    off = _run(apps.off, apps.clocks[0], lambda: 0)
    on = _run(apps.on, apps.clocks[1], lambda: apps.on_decisions[0])
    with allure.step("run the journey with rust_core_sync OFF and ON"):
        _journey(off)
        _journey(on)
        _evidence("OFF outcomes", [(o.label, o.status) for o in off.outcomes])
        _evidence("ON outcomes", [(o.label, o.status) for o in on.outcomes])
    assert len(off.outcomes) == len(on.outcomes) > 90
    with allure.step("every status and body is identical"):
        for expected, actual in zip(off.outcomes, on.outcomes, strict=True):
            assert (actual.label, actual.status, actual.body) == (
                expected.label,
                expected.status,
                expected.body,
            )
        _evidence("compared", f"{len(on.outcomes)} requests")
    with allure.step("both apps cover refusals as well as successes"):
        statuses = {o.status for o in on.outcomes}
        assert {200, 201, 400, 404, 409} <= statuses
        _evidence("statuses", sorted(statuses))
    with allure.step("the stored documents are identical"):
        assert _snapshot(apps.on, on.namer) == _snapshot(apps.off, off.namer)
        _evidence("rows", "tasks, projects, tags and park acknowledgements match")


def test_026_FR_002_each_command_asks_the_rust_core_exactly_once(apps: Apps) -> None:
    off = _run(apps.off, apps.clocks[0], lambda: 0)
    on = _run(apps.on, apps.clocks[1], lambda: apps.on_decisions[0])
    _journey(off)
    _journey(on)
    with allure.step("decisions per request"):
        deltas = [(o.label, o.status, o.decisions) for o in on.outcomes]
        _evidence("decisions", deltas)
        assert all(o.decisions == 0 for o in off.outcomes)
        assert all(decisions <= 1 for _, _, decisions in deltas)
        # every request that reached the rules (not a 404 on load, a replay,
        # a read or a request-shape 422) asked the core once.
        decided = [(label, d) for label, status, d in deltas if d == 1]
        assert len(decided) >= 70
        for label in (
            "project create",
            "task inbox",
            "update substantive title in next",
            "complete",
            "project archive",
            "project unarchive",
            "tag rename",
            "tag delete",
            "tag update clash",
        ):
            assert (label, 1) in decided, label
    with allure.step("a replay or a read never asks the core"):
        replays = {
            o.label: o.decisions
            for o in on.outcomes
            if "replay same key" in o.label
            or o.label.startswith(("list ", "task lost"))
        }
        assert replays and set(replays.values()) == {0}
        _evidence("replays", replays)


def test_026_FR_002_parked_task_returning_to_next_stamps_its_acknowledgement(
    apps: Apps,
) -> None:
    for client, clock in ((apps.off, apps.clocks[0]), (apps.on, apps.clocks[1])):
        _seed_parked(client)
        clock.set(datetime(2026, 10, 9, 14, 2, tzinfo=UTC))
    results = []
    for client in (apps.off, apps.on):
        with allure.step("move the parked task back to Next"):
            response = client.post(
                "/api/tasks/task_seedparked01/transitions",
                headers={"Idempotency-Key": "park-1"},
                json={"action": "move", "to_state": "next", "expected_revision": 4},
            )
            assert response.status_code == 200, response.text
            repo = _container(client).task_service.task_repo
            owner = client.get("/api/account").json()["id"]
            ack = repo.get_park_ack(owner, "task_seedparked01", SEED_FORMULATION)
            assert ack is not None and ack.returned_at is not None
            stored = repo.get_for_owner("task_seedparked01", owner_id=owner)
            namer = IdNamer()
            results.append(
                [
                    json.loads(namer(json.dumps(_without_owner(doc), sort_keys=True)))
                    for doc in (response.json(), stored, ack)
                ]
            )
            _evidence("returned_at", str(ack.returned_at))
    assert results[0] == results[1]
    assert apps.on_decisions[0] == 1


def test_026_FR_014_flag_applies_per_command_in_both_directions(apps: Apps) -> None:
    flags = _container(apps.on).feature_flag_service
    shapes = []
    for mode in ("on", "off", "on"):
        with allure.step(f"rust_core_sync {mode}: create a task"):
            flags.set_mode("rust_core_sync", mode, operator_id="parity")
            response = apps.on.post(
                "/api/tasks",
                headers={"Idempotency-Key": f"flip-{len(shapes)}"},
                json={"title": f"Flip {len(shapes)}"},
            )
            assert response.status_code == 201, response.text
            shapes.append(response.json()["id"])
            _evidence("id", shapes[-1])
    native = re.compile(r"^task_[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
    legacy = re.compile(r"^task_[0-9a-f]{12}$")
    assert (
        native.match(shapes[0]) and legacy.match(shapes[1]) and native.match(shapes[2])
    )
    assert apps.on_decisions[0] == 2


def test_026_FR_014_a_bridge_failure_fails_closed_without_writing(apps: Apps) -> None:
    facade = _container(apps.on).task_service._rust_facade
    assert facade is not None
    facade._core.close()
    with allure.step("a closed core refuses the write and nothing is stored"):
        service = _container(apps.on).task_service
        owner = apps.on.get("/api/account").json()["id"]
        with pytest.raises(RustBridgeError) as failure:
            service.create_task_result(
                TaskCreateRequest(title="Never stored"),
                owner_id=owner,
                idempotency_key="closed-1",
            )
        _evidence("code", failure.value.code)
        assert failure.value.code == "WORKSPACE_CLOSED"
        assert "Never stored" not in str(failure.value)
        assert service.task_repo.list_for_owner(owner_id=owner) == []
        assert service.task_repo.get_idempotency(owner_id=owner, key="closed-1") is None


def _fresh_decision(core: RustCore, read_set: dict[str, Any], title: str) -> Any:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    envelope = _envelope(
        "task.create",
        "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12",
        {"title": title},
        now,
        None,
    )
    return core.decide(read_set, envelope, _inputs(now, "owner-1"))


def test_026_FR_024_bridge_returns_typed_values_and_concurrent_calls_agree() -> None:
    with RustCore() as core:
        with allure.step("a command decides into an owned change set"):
            decision = _fresh_decision(core, {}, "Buy milk")
            assert decision.refusal is None and decision.change_set is not None
            task = decision.change_set["changes"][0]["value"]
            assert (task["title"], task["revision"], task["order_key"]) == (
                "Buy milk",
                "1",
                "0",
            )
            _evidence("task", task)
        with allure.step("a malformed read set is a content-free validation error"):
            with pytest.raises(ValidationFailure) as bad:
                _fresh_decision(core, {"tasks": 7}, "SECRET-TITLE")
            assert "SECRET-TITLE" not in repr(bad.value.detail) + str(bad.value)
            _evidence("detail", bad.value.detail)
        with allure.step("an unsupported command type is an upgrade error"):
            with pytest.raises(RustBridgeError) as unsupported:
                core.decide(
                    {},
                    {
                        "protocol_version": 1,
                        "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
                        "scope_id": "s",
                        "device_id": "d",
                        "device_epoch": "e",
                        "local_sequence": "0",
                        "type": "task.from_the_future",
                        "command_version": 1,
                        "entity_id": "x",
                        "preconditions": [],
                        "depends_on": [],
                        "issued_at": "2026-10-09T12:00:00Z",
                        "payload": {},
                    },
                    _inputs(datetime(2026, 10, 9, tzinfo=UTC), "owner-1"),
                )
            assert unsupported.value.code == "UPGRADE_REQUIRED"
            _evidence("unsupported command code", unsupported.value.code)
        with allure.step("threads share one runtime and all get the same answer"):
            answers: list[str] = []

            def work() -> None:
                for _ in range(20):
                    decided = _fresh_decision(core, {}, "Same")
                    assert decided.change_set is not None
                    answers.append(decided.change_set["changes"][0]["value"]["title"])

            threads = [threading.Thread(target=work) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert answers == ["Same"] * 80
            _evidence("answers", str(len(answers)))
    with allure.step("a closed runtime refuses further decisions"):
        with pytest.raises(RustBridgeError) as closed:
            _fresh_decision(core, {}, "Late")
        assert closed.value.code == "WORKSPACE_CLOSED"
        _evidence("closed runtime code", closed.value.code)


def test_026_FR_024_core_refusal_is_a_value_not_an_exception() -> None:
    with RustCore() as core:
        now = datetime(2026, 10, 9, tzinfo=UTC)
        refused = core.decide(
            {},
            _envelope("task.create", "task-legacy-shape", {"title": "x"}, now, None),
            _inputs(now, "owner-1"),
        )
        assert refused.change_set is None and refused.refusal is not None
        assert refused.refusal.reason == "invalid_value"
        _evidence("refusal", refused.refusal.reason)


def test_026_FR_014_refusal_order_and_stored_state_edges_match_the_python_rules(
    apps: Apps, caplog: pytest.LogCaptureFixture
) -> None:
    for client, clock in ((apps.off, apps.clocks[0]), (apps.on, apps.clocks[1])):
        _seed_parked(client)
        _seed_parked(client, "task_seedparked02", ack=False)
        clock.set(datetime(2026, 10, 9, 14, 2, tzinfo=UTC))
    off = _run(apps.off, apps.clocks[0], lambda: 0)
    on = _run(apps.on, apps.clocks[1], lambda: apps.on_decisions[0])
    with caplog.at_level(logging.WARNING, logger="app.modules.tasks.review"):
        with allure.step("run the edge journey with rust_core_sync OFF"):
            _edges(off)
            _evidence("OFF outcomes", [(o.label, o.status) for o in off.outcomes])
        caplog.clear()
        with allure.step("run the same journey with rust_core_sync ON"):
            _edges(on)
            _evidence("ON outcomes", [(o.label, o.status) for o in on.outcomes])
        unrecorded = [
            r.getMessage() for r in caplog.records if "park_return_unrecorded" in r.msg
        ]
    with allure.step("every status and body is identical"):
        assert len(off.outcomes) == len(on.outcomes) > 10
        for expected, actual in zip(off.outcomes, on.outcomes, strict=True):
            assert (actual.label, actual.status, actual.body) == (
                expected.label,
                expected.status,
                expected.body,
            )
        _evidence("compared", f"{len(on.outcomes)} requests")
    with allure.step("a refusal is reported in the order Python reports it"):
        by_label = {o.label: o for o in on.outcomes}
        assert by_label["null title and null priority"].status == 400
        assert "title" in str(by_label["null title and null priority"].body)
        assert by_label["null title before an unknown project"].status == 400
        assert "title" in str(by_label["null title before an unknown project"].body)
        assert by_label["duplicate tags before an unknown tag"].status == 400
        assert "duplicates" in str(
            by_label["duplicate tags before an unknown tag"].body
        )
        _evidence(
            "statuses",
            {label: outcome.status for label, outcome in by_label.items()},
        )
    with allure.step("a stored setting and a parked task are decided by the core"):
        assert all(
            by_label[label].status == 200
            for label in (
                "update with stored review settings",
                "move with stored review settings",
                "update a parked task keeps its park",
                "return a parked task without its acknowledgement",
            )
        )
        assert by_label["update a parked task keeps its park"].body["state"] == (
            "someday"
        )
        assert len(unrecorded) == 1 and "task_seedparked02" in unrecorded[0]
        _evidence("warning", unrecorded)
    assert all(o.decisions == 0 for o in off.outcomes)


def _upsert(entity_type: str, value: dict[str, Any]) -> dict[str, Any]:
    return {"operation": "upsert", "entity_type": entity_type, "value": value}


def test_026_FR_016_a_park_ack_change_is_applied_only_to_a_stored_acknowledgement() -> (
    None
):
    at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    stored = ReviewParkAckDocument(
        owner_id="owner-1",
        task_id="task_seedparked01",
        formulation_id=SEED_FORMULATION,
        parked_at=at,
        from_revision=3,
        source="sweep",
    )
    change_set = {
        "outcome": "changed",
        "changes": [_upsert("review_park_ack", {"returned_at": None})],
    }
    decision = Decision(change_set=change_set, refusal=None)
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    with allure.step("with a stored acknowledgement the core's instant is applied"):
        applied = RustTaskFacade._decode(decision, "owner-1", now, {}, stored)
        assert [ack.returned_at for ack in applied.park_acks] == [None]
        assert applied.park_acks[0].task_id == stored.task_id
        assert _parse_instant("2026-10-09T14:02:00Z") == datetime(
            2026, 10, 9, 14, 2, tzinfo=UTC
        )
        _evidence("acks", [ack.model_dump(mode="json") for ack in applied.park_acks])
    with allure.step("without a stored acknowledgement the change is not invented"):
        ignored = RustTaskFacade._decode(decision, "owner-1", now, {}, None)
        assert ignored.park_acks == [] and ignored.tasks == []
        _evidence("acks", "none")


def test_026_FR_024_a_tombstone_from_the_core_is_refused_not_applied() -> None:
    tombstone = Decision(
        change_set={
            "outcome": "changed",
            "changes": [{"operation": "delete", "entity_type": "task", "value": {}}],
        },
        refusal=None,
    )
    with allure.step("none of these commands may delete, so a tombstone is refused"):
        with pytest.raises(ValidationFailure) as refused:
            RustTaskFacade._decode(
                tombstone, "owner-1", datetime(2026, 10, 9, tzinfo=UTC), {}
            )
        _evidence("detail", refused.value.detail)
        assert refused.value.detail == {"reason": "unexpected_tombstone"}


def test_026_FR_024_core_refusals_keep_the_errors_the_rest_adapter_always_raised() -> (
    None
):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    task_id = "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12"
    with RustCore() as core:
        created = _fresh_decision(core, {}, "Taken")
        assert created.change_set is not None
        stored = created.change_set["changes"][0]["value"]
        with allure.step("creating over an existing id is a conflict naming the id"):
            again = core.decide(
                {"tasks": {task_id: stored}},
                _envelope("task.create", task_id, {"title": "Again"}, now, None),
                _inputs(now, "owner-1"),
            )
            assert again.refusal is not None
            error = _refused(again.refusal)
            _evidence("refusal", [again.refusal.reason, str(error)])
            assert again.refusal.reason == "id_already_exists"
            assert isinstance(error, ConflictError)
            assert task_id in str(error)
        with allure.step("a refusal without a legacy message keeps its reason"):
            invalid = core.decide(
                {},
                _envelope(
                    "task.create", "task-legacy-shape", {"title": "x"}, now, None
                ),
                _inputs(now, "owner-1"),
            )
            assert invalid.refusal is not None
            error = _refused(invalid.refusal)
            _evidence("refusal", [invalid.refusal.reason, str(error)])
            assert isinstance(error, ValidationFailure)
            assert error.detail == {
                "reason": "invalid_value",
                "field": invalid.refusal.field,
            }
        with allure.step("an unrecognised reason is a generic validation failure"):
            odd = DomainRefusal("reason_from_a_newer_core", "title", None, None)
            error = _refused(odd)
            assert isinstance(error, ValidationFailure)
            assert error.detail == {
                "reason": "reason_from_a_newer_core",
                "field": "title",
            }
            _evidence("detail", error.detail)
