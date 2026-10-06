"""Spec 020: the formulation clock maintained by the existing task commands.

contracts/formulation-clock.md §3 applied by ``create_task``, ``smart_add_task``,
``update_task`` and ``transition_task``; ``TaskResponse.formulation`` built by
the shared ``task_mapping`` with derived instants that stay null before the
owner is activated (http §2, FR-051).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient
from pydantic import Field

from app.container import Container
from app.modules.tasks import formulation as rules
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import (
    ClockBeforeDocument,
    FormulationSettingsDocument,
    TaskParkDocument,
)
from app.schemas.common import StrictBaseModel
from app.schemas.tasks import TaskCreateRequest
from app.utils.idempotency import request_fingerprint

from .conftest import FrozenClock

DAY = timedelta(days=1)
FORM_A = "form_6b1e8a52-3f0c-4e7a-9d21-5c8b0f4a7e19"
FORM_B = "form_9d2a6c1e-4b7f-4e83-a0d5-7f1b3c8e2a64"
SERVER_FORM = re.compile(r"^form_[0-9a-f]{12}$")


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    return _iso(datetime.fromisoformat(value.replace("Z", "+00:00")))


class _Keys:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> dict[str, str]:
        self.count += 1
        return {"Idempotency-Key": f"clock-{self.count}"}


@pytest.fixture
def keys() -> _Keys:
    return _Keys()


def _activate(client: TestClient, at: datetime, **fields: Any) -> None:
    owner_id = client.get("/api/auth/me").json()["id"]
    _container(client).task_repo.save_review_settings(
        rd.ReviewSettingsDocument(owner_id=owner_id, activated_at=at, **fields)
    )


def _create(client: TestClient, keys: _Keys, **body: Any) -> dict[str, Any]:
    response = client.post(
        "/api/tasks", json={"title": "Call Bob", **body}, headers=keys()
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch(
    client: TestClient, keys: _Keys, task: dict[str, Any], **body: Any
) -> dict[str, Any]:
    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"expected_revision": task["revision"], **body},
        headers=keys(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _move(
    client: TestClient, keys: _Keys, task: dict[str, Any], **body: Any
) -> dict[str, Any]:
    response = client.post(
        f"/api/tasks/{task['id']}/transitions",
        json={"expected_revision": task["revision"], **body},
        headers=keys(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_020_FR_001_create_in_next_starts_a_formulation_with_the_client_id(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """A task created in Next adopts ``new_formulation_id`` and starts now."""

    with allure.step("POST /tasks in Next with a client formulation id"):
        task = _create(api_client, keys, state="next", new_formulation_id=FORM_A)
    formulation = task["formulation"]
    assert formulation["id"] == FORM_A
    assert _norm(formulation["started_at"]) == _iso(frozen_clock())
    assert formulation["consecutive_stalled"] == 0
    assert task["parked"] is None


def test_020_FR_051_derived_instants_are_null_before_activation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """No marker before the explainer: every derived instant is null (FR-051)."""

    task = _create(api_client, keys, state="next")
    formulation = task["formulation"]
    assert SERVER_FORM.match(formulation["id"])
    assert [
        formulation[name]
        for name in ("ageing_at", "ask_at", "park_due_at", "paused_until")
    ] == [None, None, None, None]


def test_020_FR_004_derived_instants_follow_the_threshold_once_activated(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Ageing at T/2, ask at T, park due at T + 7 (formulation-clock §4)."""

    _activate(api_client, frozen_clock() - 30 * DAY)
    task = _create(api_client, keys, state="next")
    start = frozen_clock()
    formulation = task["formulation"]
    assert _norm(formulation["ageing_at"]) == _iso(start + 7 * DAY)
    assert _norm(formulation["ask_at"]) == _iso(start + 14 * DAY)
    assert _norm(formulation["park_due_at"]) == _iso(start + 21 * DAY)
    assert formulation["paused_until"] is None

    listed = api_client.get("/api/tasks", params={"state": "next"}).json()["items"]
    assert listed[0]["formulation"] == formulation
    detail = api_client.get(f"/api/tasks/{task['id']}").json()
    assert detail["formulation"] == formulation


def test_020_FR_001_inbox_tasks_and_native_inbox_tasks_never_start_a_clock(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Inbox has no clock; the Brain Dump port never starts one either."""

    inbox = _create(api_client, keys)
    assert inbox["formulation"] is None
    owner_id = api_client.get("/api/auth/me").json()["id"]
    native = _container(api_client).task_service.create_native_inbox_task(
        owner_id=owner_id,
        title="From a brain dump",
        source_capture_ids=[],
        idempotency_key="native-1",
    )
    assert native.formulation_id is None
    assert native.formulation_started_at is None


def test_020_FR_001_smart_add_in_next_starts_a_server_minted_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Smart Add into Next starts a formulation like ``POST /tasks``."""

    response = api_client.post(
        "/api/tasks/smart-add",
        json={"title": "Call Bob", "state": "next"},
        headers=keys(),
    )
    assert response.status_code == 201, response.text
    formulation = response.json()["task"]["formulation"]
    assert SERVER_FORM.match(formulation["id"])
    assert _norm(formulation["started_at"]) == _iso(frozen_clock())


def test_020_FR_001_moving_or_reopening_into_next_starts_a_new_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Move from Inbox and reopen into Next each start a formulation."""

    inbox = _create(api_client, keys)
    frozen_clock.advance(hours=2)
    moved = _move(
        api_client,
        keys,
        inbox,
        action="move",
        to_state="next",
        new_formulation_id=FORM_A,
    )
    assert moved["formulation"]["id"] == FORM_A
    assert _norm(moved["formulation"]["started_at"]) == _iso(frozen_clock())

    done = _move(api_client, keys, moved, action="complete")
    assert done["formulation"] is None
    frozen_clock.advance(hours=2)
    reopened = _move(api_client, keys, done, action="reopen", to_state="next")
    assert SERVER_FORM.match(reopened["formulation"]["id"])
    assert _norm(reopened["formulation"]["started_at"]) == _iso(frozen_clock())


def test_020_FR_002_cosmetic_title_change_keeps_the_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Case and punctuation only: same id and start (FR-002)."""

    task = _create(
        api_client, keys, title="Call Bob", state="next", new_formulation_id=FORM_A
    )
    frozen_clock.advance(days=3)
    patched = _patch(
        api_client, keys, task, title="call bob.", new_formulation_id=FORM_B
    )
    assert patched["title"] == "call bob."
    assert patched["formulation"]["id"] == FORM_A
    assert patched["formulation"]["started_at"] == task["formulation"]["started_at"]


def test_020_FR_002_substantive_title_change_starts_a_new_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """A substantive change closes the clock and starts the supplied one."""

    task = _create(
        api_client, keys, title="Call Bob", state="next", new_formulation_id=FORM_A
    )
    frozen_clock.advance(days=3)
    patched = _patch(
        api_client, keys, task, title="Email Bob the quote", new_formulation_id=FORM_B
    )
    assert patched["formulation"]["id"] == FORM_B
    assert _norm(patched["formulation"]["started_at"]) == _iso(frozen_clock())


def test_020_FR_003_notes_tags_project_priority_subtask_and_comment_keep_the_clock(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Edits to everything but the title and due date leave the clock alone."""

    project = api_client.post("/api/projects", json={"name": "Flat"}, headers=keys())
    tag = api_client.post("/api/tags", json={"name": "home"}, headers=keys())
    task = _create(api_client, keys, state="next", new_formulation_id=FORM_A)
    clock = task["formulation"]
    frozen_clock.advance(days=2)
    task = _patch(
        api_client,
        keys,
        task,
        details="Measure first",
        project_id=project.json()["id"],
        tag_ids=[tag.json()["id"]],
        priority="high",
    )
    assert task["formulation"] == clock
    subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks", json={"title": "Tape"}, headers=keys()
    )
    comment = api_client.post(
        f"/api/tasks/{task['id']}/comments", json={"body": "Ask Ann"}, headers=keys()
    )
    assert subtask.status_code == comment.status_code == 201
    assert api_client.get(f"/api/tasks/{task['id']}").json()["formulation"] == clock


def test_020_FR_046_due_date_change_in_next_raises_the_park_floor(
    api_client: TestClient,
    frozen_clock: FrozenClock,
    keys: _Keys,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Set, move or remove: floor = max(existing, now + 7 d); start unchanged."""

    _activate(api_client, frozen_clock() - 30 * DAY, time_zone="Europe/Berlin")
    task = _create(api_client, keys, state="next", new_formulation_id=FORM_A)
    started = task["formulation"]["started_at"]

    frozen_clock.advance(days=1)
    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        task = _patch(api_client, keys, task, due_date="2026-11-01")
    first_floor = frozen_clock() + 7 * DAY
    assert task["formulation"]["started_at"] == started
    assert _norm(task["formulation"]["park_floor_at"]) == _iso(first_floor)
    assert _norm(task["formulation"]["paused_until"]) == "2026-10-31T23:00:00Z"
    moved = [
        r.getMessage()
        for r in caplog.records
        if "review_due_date_moved" in r.getMessage()
    ]
    assert len(moved) == 1
    assert task["id"] in moved[0]

    frozen_clock.advance(days=2)
    task = _patch(api_client, keys, task, due_date=None)
    assert _norm(task["formulation"]["park_floor_at"]) == _iso(frozen_clock() + 7 * DAY)
    assert task["formulation"]["paused_until"] is None

    frozen_clock.set(frozen_clock() - 2 * DAY)
    task = _patch(api_client, keys, task, due_date="2026-10-20")
    # An earlier instant never lowers the floor (max of existing and now + 7 d).
    assert _norm(task["formulation"]["park_floor_at"]) == _iso(first_floor + 2 * DAY)


def test_020_FR_046_due_date_change_outside_next_sets_no_floor(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Outside Next there is no clock to floor."""

    task = _create(api_client, keys)
    task = _patch(api_client, keys, task, due_date="2026-11-01")
    assert task["formulation"] is None
    owner_id = api_client.get("/api/auth/me").json()["id"]
    stored = _container(api_client).task_repo.get_for_owner(
        task["id"], owner_id=owner_id
    )
    assert stored.formulation_park_floor_at is None


def test_020_FR_005_leaving_next_while_asking_counts_a_stalled_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Closed after it asked: count + 1, surviving the trip out and back."""

    _activate(api_client, frozen_clock() - 30 * DAY)
    task = _create(api_client, keys, state="next", new_formulation_id=FORM_A)
    frozen_clock.advance(days=15)
    waiting = _move(
        api_client, keys, task, action="move", to_state="waiting", waiting_for="Ann"
    )
    assert waiting["formulation"] is None
    back = _move(api_client, keys, waiting, action="move", to_state="next")
    assert back["formulation"]["consecutive_stalled"] == 1

    frozen_clock.advance(days=2)
    done = _move(api_client, keys, back, action="complete")
    owner_id = api_client.get("/api/auth/me").json()["id"]
    stored = _container(api_client).task_repo.get_for_owner(
        done["id"], owner_id=owner_id
    )
    assert stored.consecutive_stalled_formulations == 0
    assert stored.formulation_id is None


def test_020_FR_001_parked_task_returned_to_next_starts_a_new_formulation(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """Leaving Someday clears ``parked``; entering Next starts a formulation."""

    task = _create(api_client, keys, state="someday")
    owner_id = api_client.get("/api/auth/me").json()["id"]
    repo = _container(api_client).task_repo
    stored = repo.get_for_owner(task["id"], owner_id=owner_id)
    repo.save(
        stored.model_copy(
            update={
                "parked": TaskParkDocument(
                    at=frozen_clock(),
                    formulation_id=FORM_A,
                    from_revision=1,
                    clock_before=ClockBeforeDocument(
                        started_at=frozen_clock() - 21 * DAY
                    ),
                )
            }
        )
    )
    parked = api_client.get(f"/api/tasks/{task['id']}").json()["parked"]
    assert parked["formulation_id"] == FORM_A
    assert _norm(parked["at"]) == _iso(frozen_clock())
    assert set(parked) == {"at", "formulation_id"}
    returned = _move(
        api_client,
        keys,
        task,
        action="move",
        to_state="next",
        new_formulation_id=FORM_B,
    )
    assert returned["parked"] is None
    assert returned["formulation"]["id"] == FORM_B


def test_020_FR_001_new_formulation_id_has_one_fixed_shape(
    api_client: TestClient, keys: _Keys
) -> None:
    """Free text cannot travel in a formulation id (422)."""

    response = api_client.post(
        "/api/tasks",
        json={"title": "Call Bob", "state": "next", "new_formulation_id": "form_x"},
        headers=keys(),
    )
    assert response.status_code == 422


class _LegacyTaskCreateRequest(StrictBaseModel):
    """``TaskCreateRequest`` as it was before spec 020 added a field."""

    title: str = Field(min_length=1, max_length=500)
    details: str | None = None
    state: str = "inbox"
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    due_date: str | None = None
    priority: str = "none"
    waiting_for: str | None = None
    source_capture_ids: list[str] = Field(default_factory=list)


def test_020_FR_001_old_clients_keep_their_replay_fingerprint(
    api_client: TestClient,
) -> None:
    """A body without ``new_formulation_id`` hashes as before the field existed.

    So an idempotent retry that crosses the deploy is still a replay, not a 409.
    """

    body = {"title": "Call Bob", "state": "next"}
    service = _container(api_client).task_service
    assert service._request_hash(
        "create_task", TaskCreateRequest.model_validate(body)
    ) == request_fingerprint(
        "create_task", _LegacyTaskCreateRequest.model_validate(body)
    )
    assert service._request_hash(
        "create_task",
        TaskCreateRequest.model_validate({**body, "new_formulation_id": FORM_A}),
    ) != request_fingerprint(
        "create_task", _LegacyTaskCreateRequest.model_validate(body)
    )


def _task_command(
    client: TestClient, keys: _Keys, route: str
) -> tuple[str, str, dict[str, Any]]:
    """One task command whose response projects a Next task's formulation."""

    if route == "create":
        return "POST", "/api/tasks", {"title": "Call Bob", "state": "next"}
    if route == "smart_add":
        return "POST", "/api/tasks/smart-add", {"title": "Call Bob", "state": "next"}
    if route == "patch":
        task = _create(client, keys, state="next")
        return (
            "PATCH",
            f"/api/tasks/{task['id']}",
            {"expected_revision": task["revision"], "details": "Ask about Friday"},
        )
    task = _create(client, keys)
    return (
        "POST",
        f"/api/tasks/{task['id']}/transitions",
        {"expected_revision": task["revision"], "action": "move", "to_state": "next"},
    )


def _put_threshold(client: TestClient, keys: _Keys, days: int) -> None:
    owner_id = client.get("/api/auth/me").json()["id"]
    stored = _container(client).task_repo.get_review_settings(owner_id)
    assert stored is not None
    response = client.put(
        "/api/review/settings",
        json={"threshold_days": days, "expected_revision": stored.revision},
        headers=keys(),
    )
    assert response.status_code == 200, response.text


def _response_task(route: str, body: dict[str, Any]) -> dict[str, Any]:
    task: dict[str, Any] = body["task"] if route == "smart_add" else body
    return task


@pytest.mark.parametrize("route", ["create", "smart_add", "patch", "transition"])
def test_020_FR_004_020_FR_011_a_task_command_replay_returns_the_original_projection(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys, route: str
) -> None:
    """Same key and body after a threshold change: the original ``formulation``.

    The derived instants depend on the owner's settings (http §2); a replay
    returns the original response (http "Mutations"), not a re-projection of
    the stored task with the live settings.
    """

    _activate(api_client, frozen_clock() - 30 * DAY)
    method, path, body = _task_command(api_client, keys, route)
    headers = keys()
    with allure.step(f"Send the {route} command"):
        first = api_client.request(method, path, json=body, headers=headers)
    assert first.status_code in (200, 201), first.text
    original = _response_task(route, first.json())
    assert original["formulation"]["ask_at"] is not None
    with allure.step("Raise the threshold to 28 days"):
        _put_threshold(api_client, keys, 28)
    live = api_client.get(f"/api/tasks/{original['id']}").json()
    assert live["formulation"] != original["formulation"]

    with allure.step("Replay the same Idempotency-Key and body"):
        replay = api_client.request(method, path, json=body, headers=headers)
    assert replay.status_code == first.status_code, replay.text
    assert _response_task(route, replay.json()) == original
    if route != "smart_add":
        assert replay.content == first.content


def test_020_FR_011_a_task_record_without_a_settings_snapshot_projects_live(
    api_client: TestClient, frozen_clock: FrozenClock, keys: _Keys
) -> None:
    """A ``create_task`` record stored before the snapshot still replays."""

    _activate(api_client, frozen_clock() - 30 * DAY)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    repo = _container(api_client).task_repo
    headers = keys()
    body = {"title": "Call Bob", "state": "next"}
    first = api_client.post("/api/tasks", json=body, headers=headers)
    assert first.status_code == 201, first.text
    with allure.step("Drop the snapshot, as a record written before it was added"):
        record = repo.get_idempotency(owner_id=owner_id, key=headers["Idempotency-Key"])
        assert record is not None
        stored = dict(record.response_body)
        assert stored.pop("formulation_settings") is not None
        with repo.command_lock(owner_id):
            repo.save_idempotency(
                owner_id=owner_id,
                record=record.model_copy(update={"response_body": stored}),
            )
    _put_threshold(api_client, keys, 28)

    replay = api_client.post("/api/tasks", json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    live = api_client.get(f"/api/tasks/{first.json()['id']}").json()
    assert replay.json()["formulation"] == live["formulation"]
    assert replay.json()["formulation"] != first.json()["formulation"]
    assert {**replay.json(), "formulation": None} == {
        **first.json(),
        "formulation": None,
    }


def test_020_FR_011_the_stored_settings_snapshot_keeps_every_clock_input() -> None:
    """Threshold, zone, owner floor and activation survive the stored JSON."""

    settings = rules.OwnerClockSettings(
        threshold_days=21,
        time_zone="Asia/Tokyo",
        owner_park_floor_at=datetime(2026, 10, 9, 8, 0, tzinfo=UTC),
        activated_at=datetime(2026, 9, 1, 12, 30, tzinfo=UTC),
    )
    stored = FormulationSettingsDocument.of(settings).model_dump(mode="json")
    loaded = FormulationSettingsDocument.model_validate(stored)
    assert loaded.clock_settings() == settings


def test_020_FR_004_both_routers_share_the_public_task_mapper() -> None:
    """``TaskResponse`` comes from ``app.api.task_mapping`` for every router."""

    from app.api import review, task_mapping, tasks

    assert tasks._to_response is task_mapping.task_response
    assert review.task_response is task_mapping.task_response
