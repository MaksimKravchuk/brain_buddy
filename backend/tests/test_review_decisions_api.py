"""Spec 020: card decisions and their Undo (contracts/http.md §3, FR-006 – FR-011).

``POST /tasks/{task_id}/decisions`` applies one row of the http §3 type table
as one owner-serialized, idempotent command: the task change, the decision row
with its stall-reason code and ``ai_use``, the undo snapshot, any receipt or
follow-up task, and the linked session's counter. The matching-record replay
answers a retry after the 24 h idempotency retention as already applied.
``POST /review/decisions/{decision_id}/undo`` restores the task field for field.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import IdempotencyRecord
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION

from .conftest import FrozenClock

DAY = timedelta(days=1)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(value: str | None) -> str | None:
    if value is None:
        return None
    return iso(datetime.fromisoformat(value.replace("Z", "+00:00")))


class ReviewApi:
    """A signed-in client plus the helpers every review API test needs."""

    def __init__(self, client: TestClient, clock: FrozenClock) -> None:
        self.client = client
        self.clock = clock
        self.count = 0
        self.owner_id: str = client.get("/api/auth/me").json()["id"]

    @property
    def container(self) -> Container:
        return self.client.app.state.container  # type: ignore[attr-defined]

    def key(self) -> dict[str, str]:
        self.count += 1
        return {"Idempotency-Key": f"key-{uuid.uuid4()}-{self.count}"}

    def flag(self, mode: str) -> None:
        self.container.feature_flag_service.set_mode(
            "weekly_review", mode, operator_id="test-operator"
        )

    def activate_at(self, at: datetime, **fields: Any) -> None:
        """Seed an activated owner without the explainer route."""

        stored = self.container.task_repo.get_review_settings(self.owner_id)
        base = stored or rd.ReviewSettingsDocument(owner_id=self.owner_id)
        self.container.task_repo.save_review_settings(
            base.model_copy(
                update={"activated_at": at, "last_effective_sweep_at": at, **fields}
            )
        )

    def create(
        self, title: str = "Renovate the bathroom", **body: Any
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/tasks", json={"title": title, **body}, headers=self.key()
        )
        assert response.status_code == 201, response.text
        return response.json()

    def task(self, task_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def move(self, task: dict[str, Any], to_state: str, **body: Any) -> dict[str, Any]:
        response = self.client.post(
            f"/api/tasks/{task['id']}/transitions",
            json={
                "action": "move",
                "to_state": to_state,
                "expected_revision": task["revision"],
                **body,
            },
            headers=self.key(),
        )
        assert response.status_code == 200, response.text
        return response.json()

    def patch(self, task: dict[str, Any], **body: Any) -> dict[str, Any]:
        response = self.client.patch(
            f"/api/tasks/{task['id']}",
            json={"expected_revision": task["revision"], **body},
            headers=self.key(),
        )
        assert response.status_code == 200, response.text
        return response.json()

    def decide_raw(
        self,
        task: dict[str, Any],
        decision_type: str,
        *,
        headers: dict[str, str] | None = None,
        **body: Any,
    ) -> Any:
        payload: dict[str, Any] = {
            "type": decision_type,
            "expected_revision": task["revision"],
            **body,
        }
        formulation = task.get("formulation")
        if formulation is not None:
            payload.setdefault("formulation_id", formulation["id"])
        return self.client.post(
            f"/api/tasks/{task['id']}/decisions",
            json=payload,
            headers=headers or self.key(),
        )

    def decide(
        self, task: dict[str, Any], decision_type: str, **body: Any
    ) -> dict[str, Any]:
        response = self.decide_raw(task, decision_type, **body)
        assert response.status_code == 200, response.text
        return response.json()

    def undo_raw(
        self, decision_id: str, revision: int, headers: dict[str, str] | None = None
    ) -> Any:
        return self.client.post(
            f"/api/review/decisions/{decision_id}/undo",
            json={"expected_task_revision": revision},
            headers=headers or self.key(),
        )

    def session(self, **fields: Any) -> rd.ReviewSessionDocument:
        now = self.clock()
        values: dict[str, Any] = {
            "id": new_id("review"),
            "owner_id": self.owner_id,
            "mode": "quick",
            "entry": "list",
            "origin": "ios",
            "started_at": now,
            "last_activity_at": now,
            **fields,
        }
        session = rd.ReviewSessionDocument.model_validate(values)
        self.container.task_repo.save_review_session(session)
        return session

    def decisions(self) -> list[rd.ReviewDecisionDocument]:
        return self.container.task_repo.list_review_decisions(self.owner_id)

    def stored(self, task_id: str) -> Any:
        return self.container.task_repo.get_for_owner(task_id, owner_id=self.owner_id)


@pytest.fixture
def api(api_client: TestClient, frozen_clock: FrozenClock) -> ReviewApi:
    review_api = ReviewApi(api_client, frozen_clock)
    review_api.activate_at(frozen_clock() - 30 * DAY)
    return review_api


def _asking(
    api: ReviewApi, title: str = "Renovate the bathroom", **body: Any
) -> dict[str, Any]:
    """A Next task 15 days into a 14-day threshold: it asks for a decision."""

    task = api.create(title, state="next", **body)
    api.clock.advance(days=15)
    return api.task(task["id"])


def _waiting(api: ReviewApi) -> dict[str, Any]:
    task = api.create("Quote from the plumber", state="waiting", waiting_for="Ann")
    return task


def _someday(api: ReviewApi) -> dict[str, Any]:
    return api.create("Learn the cello", state="someday")


# --------------------------------------------------------------- type table
@pytest.mark.parametrize(
    ("decision_type", "start", "body", "state", "bucket"),
    [
        ("complete", "next", {}, "completed", "done"),
        ("complete", "waiting", {}, "completed", "done"),
        (
            "reformulate",
            "next",
            {"title": "Measure the bathroom wall"},
            "next",
            "reformulated",
        ),
        ("first_step", "next", {"title": "Measure the wall"}, "next", "first_step"),
        ("waiting", "next", {"waiting_for": "Ann"}, "waiting", "waiting"),
        ("someday", "next", {}, "someday", "someday"),
        ("cancel", "next", {}, "cancelled", "cancelled"),
        ("cancel", "someday", {}, "cancelled", "cancelled"),
        ("extend", "next", {"reason": "Quote due Friday"}, "next", "extended"),
        ("keep_waiting", "waiting", {}, "waiting", "kept"),
        (
            "follow_up",
            "waiting",
            {"title": "Call Ann about the quote"},
            "waiting",
            "moved_to_next",
        ),
        (
            "return_to_next",
            "waiting",
            {"title": "Quote from the plumber"},
            "next",
            "moved_to_next",
        ),
        (
            "return_to_next",
            "someday",
            {"title": "Learn the cello"},
            "next",
            "moved_to_next",
        ),
        ("keep_someday", "someday", {}, "someday", "kept"),
    ],
)
def test_020_FR_006_020_FR_033_every_decision_type_and_its_counter(
    api: ReviewApi,
    decision_type: str,
    start: str,
    body: dict[str, Any],
    state: str,
    bucket: str,
) -> None:
    """Each http §3 row moves the task and bumps its ``review_counts_as``."""

    task = {"next": _asking, "waiting": _waiting, "someday": _someday}[start](api)
    session = api.session()
    with allure.step(f"Decide {decision_type} on a {start} task inside a review"):
        result = api.decide(task, decision_type, session_id=session.id, **body)
    assert result["task"]["state"] == state
    assert result["decision"]["type"] == decision_type
    assert result["decision"]["session_id"] == session.id
    counts = result["session_counts"]
    assert counts[bucket] == 1
    assert sum(counts.values()) == 1
    stored = api.decisions()
    assert [d.review_counts_as for d in stored] == [bucket]
    assert stored[0].task_revision_before == task["revision"]
    assert stored[0].task_revision_after == result["task"]["revision"]
    stored_session = api.container.task_repo.get_review_session(
        api.owner_id, session.id
    )
    assert stored_session is not None and stored_session.qualifying_activity


def test_020_FR_010_a_decision_outside_a_review_is_recorded_the_same_way(
    api: ReviewApi,
) -> None:
    """Card decisions from the task itself are rows too, with no session."""

    task = _asking(api)
    result = api.decide(task, "complete", stall_reason="no_longer_matters")
    assert result["decision"]["session_id"] is None
    assert result["session_counts"] is None
    assert api.decisions()[0].stall_reason == "no_longer_matters"


def test_020_FR_002_cosmetic_save_anyway_is_a_reformulate_without_a_clock_change(
    api: ReviewApi,
) -> None:
    """``substantive: false``, same formulation, the task keeps asking."""

    task = _asking(api, "Call Bob")
    result = api.decide(task, "reformulate", title="call bob.")
    assert result["decision"]["substantive"] is False
    assert result["task"]["formulation"]["id"] == task["formulation"]["id"]
    assert (
        result["task"]["formulation"]["started_at"] == task["formulation"]["started_at"]
    )
    assert result["task"]["title"] == "call bob."


def test_020_FR_002_substantive_reformulate_adopts_the_client_formulation_id(
    api: ReviewApi,
) -> None:
    """A substantive reformulation starts the formulation the client named."""

    task = _asking(api, "Call Bob")
    form = new_id("form")
    result = api.decide(
        task, "reformulate", title="Email Bob the quote", new_formulation_id=form
    )
    assert result["decision"]["substantive"] is True
    assert result["task"]["formulation"]["id"] == form
    assert norm(result["task"]["formulation"]["started_at"]) == iso(api.clock())
    assert result["task"]["formulation"]["consecutive_stalled"] == 1


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (None, "Was: Renovate the bathroom"),
        ("Tiles from Ann", "Was: Renovate the bathroom\n\nTiles from Ann"),
    ],
)
def test_020_FR_008_first_step_keeps_the_old_title_in_the_notes(
    api: ReviewApi, details: str | None, expected: str
) -> None:
    """``Was: <old title>`` then a blank line and the old notes, if any."""

    task = _asking(api, details=details)
    form = new_id("form")
    result = api.decide(
        task,
        "first_step",
        title="Measure the wall",
        stall_reason="too_big",
        new_formulation_id=form,
    )
    assert result["task"]["details"] == expected
    assert result["task"]["title"] == "Measure the wall"
    assert result["task"]["formulation"]["id"] == form


def test_020_FR_009_extend_needs_a_due_formulation_and_works_once(
    api: ReviewApi,
) -> None:
    """Not before it asks; once per formulation; the reason stays on the row."""

    fresh = api.create(state="next")
    early = api.decide_raw(fresh, "extend", reason="Not yet")
    assert early.status_code == 400
    assert early.json()["detail"] == {"reason": "extension_not_due"}

    api.clock.advance(days=15)
    task = api.task(fresh["id"])
    extended = api.decide(task, "extend", reason="Quote due Friday")
    formulation = extended["task"]["formulation"]
    assert norm(formulation["extended_at"]) == iso(api.clock())
    assert formulation["extension_reason"] == "Quote due Friday"
    assert norm(formulation["ask_at"]) == iso(api.clock() + 7 * DAY)
    assert api.decisions()[0].reason_text == "Quote due Friday"

    again = api.decide_raw(extended["task"], "extend", reason="More time")
    assert again.status_code == 400
    assert again.json()["detail"] == {"reason": "extension_already_used"}


def test_020_FR_009_extend_is_allowed_while_the_park_is_due_but_not_applied(
    api: ReviewApi,
) -> None:
    """``park_due`` before the sweep ran still accepts the extension (FR-013)."""

    task = api.create(state="next")
    api.clock.advance(days=22)
    result = api.decide(api.task(task["id"]), "extend", reason="Back next week")
    assert result["task"]["state"] == "next"


def test_020_FR_009_extend_requires_a_reason(api: ReviewApi) -> None:
    """``reason`` (1..500) is required: missing or blank is 422."""

    task = _asking(api)
    assert api.decide_raw(task, "extend").status_code == 422
    assert api.decide_raw(task, "extend", reason="   ").status_code == 422
    assert api.decide_raw(task, "extend", reason="x" * 501).status_code == 422


def test_020_FR_032_someday_is_a_release_receipt_not_a_park(api: ReviewApi) -> None:
    """``parked`` stays null; a 30-day ``source: release`` receipt is written."""

    task = _asking(api)
    result = api.decide(task, "someday")
    assert result["task"]["parked"] is None
    assert result["receipt"]["kind"] == "someday"
    assert norm(result["receipt"]["hidden_until"]) == iso(api.clock() + 30 * DAY)
    receipt = api.container.task_repo.get_review_receipt(
        api.owner_id, task["id"], "someday"
    )
    assert receipt is not None and receipt.source == "release"


def test_020_FR_032_keep_waiting_and_keep_someday_write_keep_receipts(
    api: ReviewApi,
) -> None:
    """Waiting hidden 7 days, Someday 30 days, both ``source: keep``."""

    waiting = api.decide(_waiting(api), "keep_waiting")
    someday = api.decide(_someday(api), "keep_someday")
    assert norm(waiting["receipt"]["hidden_until"]) == iso(api.clock() + 7 * DAY)
    assert norm(someday["receipt"]["hidden_until"]) == iso(api.clock() + 30 * DAY)
    assert {
        r.source for r in api.container.task_repo.list_review_receipts(api.owner_id)
    } == {"keep"}


def test_020_FR_006_follow_up_creates_a_next_task_in_the_same_project(
    api: ReviewApi,
) -> None:
    """The follow-up adopts the client id and project; the original gets a receipt."""

    project = api.client.post("/api/projects", json={"name": "Flat"}, headers=api.key())
    task = api.create(
        "Quote from the plumber",
        state="waiting",
        waiting_for="Ann",
        project_id=project.json()["id"],
    )
    follow_up_id = new_id("task")
    form = new_id("form")
    result = api.decide(
        task,
        "follow_up",
        title="Call Ann about the quote",
        follow_up_task_id=follow_up_id,
        new_formulation_id=form,
    )
    created = result["created_task"]
    assert created["id"] == follow_up_id
    assert created["state"] == "next"
    assert created["project_id"] == project.json()["id"]
    assert created["formulation"]["id"] == form
    assert result["receipt"]["task_id"] == task["id"]
    assert result["task"]["revision"] == task["revision"]


@pytest.mark.parametrize("decision_type", ["follow_up", "return_to_next"])
def test_020_FR_006_project_archived_blocks_moving_work_into_an_archived_project(
    api: ReviewApi, decision_type: str
) -> None:
    """Fixture only: archiving clears ``project_id`` today (plan inconsistency 1)."""

    project = api.client.post(
        "/api/projects", json={"name": "Old flat"}, headers=api.key()
    )
    project_id = project.json()["id"]
    task = _waiting(api)
    repo = api.container.task_repo
    stored = repo.get_project_for_owner(project_id, owner_id=api.owner_id)
    repo.save_project(stored.model_copy(update={"state": "archived"}))
    repo.save(api.stored(task["id"]).model_copy(update={"project_id": project_id}))

    response = api.decide_raw(task, decision_type, title="Call Ann")
    assert response.status_code == 400
    assert response.json()["detail"] == {"reason": "project_archived"}
    assert api.decisions() == []


# --------------------------------------------------------------- stale, rules
def test_020_FR_011_stale_revision_or_formulation_is_409_and_nothing_applies(
    api: ReviewApi,
) -> None:
    """The card saw an older task: 409, task and decisions unchanged."""

    stale = _asking(api)
    task = api.patch(stale, details="Edited on another device")
    stale_revision = api.decide_raw(stale, "complete")
    assert stale_revision.status_code == 409
    stale_form = api.decide_raw(
        task, "waiting", waiting_for="Ann", formulation_id=new_id("form")
    )
    assert stale_form.status_code == 409
    assert stale_form.json()["detail"] == {"resource": "Task", "id": task["id"]}
    assert api.task(task["id"])["revision"] == task["revision"]
    assert api.decisions() == []


def test_020_FR_006_a_type_the_list_does_not_allow_is_decision_not_allowed(
    api: ReviewApi,
) -> None:
    """``keep_waiting`` on a Next task, ``extend`` on a Waiting task: 400."""

    task = _asking(api)
    response = api.decide_raw(task, "keep_waiting")
    assert response.status_code == 400
    assert response.json() == {
        "message": "This decision isn't available for this task's current list. "
        "Nothing was changed.",
        "detail": {"reason": "decision_not_allowed"},
        "reference_id": response.headers["X-Correlation-ID"],
    }
    waiting = _waiting(api)
    response = api.decide_raw(
        waiting, "extend", reason="x", formulation_id=new_id("form")
    )
    assert response.json()["detail"] == {"reason": "decision_not_allowed"}


def test_020_FR_011_another_owners_task_is_404(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Ownership: a foreign task id answers like an unknown one."""

    first, second = second_api_client
    owner = ReviewApi(first, frozen_clock)
    stranger = ReviewApi(second, frozen_clock)
    task = owner.create(state="next")
    foreign = stranger.decide_raw(task, "complete")
    unknown = stranger.decide_raw({**task, "id": "task_000000000000"}, "complete")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["detail"]["resource"] == unknown.json()["detail"]["resource"]


# --------------------------------------------------------------- idempotency
def test_020_FR_011_same_key_replays_and_another_body_conflicts(api: ReviewApi) -> None:
    """Idempotency-Key replay returns the original; another body is 409."""

    task = _asking(api)
    headers = api.key()
    first = api.decide_raw(task, "complete", headers=headers)
    replay = api.decide_raw(task, "complete", headers=headers)
    assert first.status_code == replay.status_code == 200
    assert first.json()["decision"]["id"] == replay.json()["decision"]["id"]
    assert len(api.decisions()) == 1
    other = api.decide_raw(task, "cancel", headers=headers)
    assert other.status_code == 409
    assert other.json()["detail"] == {"reason": "idempotency_conflict"}


def test_020_FR_011_missing_idempotency_key_is_400(api: ReviewApi) -> None:
    task = _asking(api)
    response = api.client.post(
        f"/api/tasks/{task['id']}/decisions",
        json={"type": "complete", "expected_revision": task["revision"]},
    )
    assert response.status_code == 400


def test_020_FR_045_client_ids_are_adopted_and_free_text_ids_are_422(
    api: ReviewApi,
) -> None:
    """``decision_<uuid>`` is adopted; any other shape is refused."""

    task = _asking(api)
    decision_id = new_id("decision")
    result = api.decide(task, "complete", decision_id=decision_id)
    assert result["decision"]["id"] == decision_id
    other = _asking(api)
    for bad in (
        "decision_free text",
        "review_" + str(uuid.uuid4()),
        "decision_" + "a" * 60,
    ):
        assert api.decide_raw(other, "complete", decision_id=bad).status_code == 422
    assert (
        api.decide_raw(other, "complete", navigator_request_id="abc").status_code == 422
    )


def test_020_FR_026_ai_use_and_navigator_request_are_recorded(api: ReviewApi) -> None:
    """Whether an AI proposal was used is stored as a code, never text."""

    task = _asking(api)
    request_id = str(uuid.uuid4())
    result = api.decide(
        task,
        "first_step",
        title="Measure the wall",
        ai_use="edited",
        navigator_request_id=request_id,
    )
    assert result["decision"]["ai_use"] == "edited"
    stored = api.decisions()[0]
    assert stored.ai_use == "edited"
    assert stored.navigator_request_id == request_id


def test_020_FR_011_reused_decision_id_matches_or_conflicts(api: ReviewApi) -> None:
    """Same id under another key: matching fields answer 200, others 409."""

    task = _asking(api)
    decision_id = new_id("decision")
    first = api.decide(task, "waiting", waiting_for="Ann", decision_id=decision_id)

    matching = api.decide_raw(
        task, "waiting", waiting_for="Ann", decision_id=decision_id
    )
    assert matching.status_code == 200, matching.text
    assert matching.json()["decision"] == first["decision"]
    assert matching.json()["task"]["revision"] == first["task"]["revision"]
    assert len(api.decisions()) == 1

    other_type = api.decide_raw(task, "someday", decision_id=decision_id)
    assert other_type.status_code == 409
    assert other_type.json()["detail"] == {"reason": "id_conflict"}
    other_task = api.decide_raw(
        _asking(api), "waiting", waiting_for="Ann", decision_id=decision_id
    )
    assert other_task.json()["detail"] == {"reason": "id_conflict"}
    assert len(api.decisions()) == 1


def test_020_FR_011_retry_after_the_idempotency_retention_is_already_applied(
    api: ReviewApi,
) -> None:
    """Lost response, 24 h+ offline: the same request answers 200, applied once."""

    task = _asking(api)
    headers = api.key()
    decision_id = new_id("decision")
    body = {
        "waiting_for": "Ann",
        "decision_id": decision_id,
        "stall_reason": "waiting_on_someone",
    }
    first = api.decide_raw(task, "waiting", headers=headers, **body)
    assert first.status_code == 200

    api.clock.advance(IDEMPOTENCY_RETENTION + timedelta(hours=1))
    with allure.step("Retry with the same key and the now-stale expected revision"):
        retry = api.decide_raw(task, "waiting", headers=headers, **body)
    assert retry.status_code == 200, retry.text
    assert retry.json()["decision"]["id"] == decision_id
    assert retry.json()["task"]["revision"] == first.json()["task"]["revision"]
    assert api.task(task["id"])["revision"] == first.json()["task"]["revision"]
    assert len(api.decisions()) == 1

    other_type = api.decide_raw(
        task, "someday", headers=headers, decision_id=decision_id
    )
    assert other_type.status_code == 409
    assert other_type.json()["detail"] == {"reason": "id_conflict"}


def test_020_FR_011_a_decision_id_is_never_matched_across_owners(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Another owner's identical id is processed as unknown, not as a match."""

    first, second = second_api_client
    owner = ReviewApi(first, frozen_clock)
    other = ReviewApi(second, frozen_clock)
    decision_id = new_id("decision")
    owner.decide(owner.create(state="next"), "complete", decision_id=decision_id)
    theirs = other.create(state="next")
    result = other.decide(theirs, "complete", decision_id=decision_id)
    assert result["task"]["state"] == "completed"
    assert len(owner.decisions()) == len(other.decisions()) == 1


def test_020_FR_011_unknown_session_is_recorded_without_a_session(
    api: ReviewApi,
) -> None:
    """An offline review's session the server never saw: 200, ``session_id`` null."""

    result = api.decide(_asking(api), "complete", session_id=new_id("review"))
    assert result["decision"]["session_id"] is None
    assert api.decisions()[0].session_id is None


def test_020_SC_007_a_finished_session_still_counts_a_late_decision(
    api: ReviewApi,
) -> None:
    """An offline decision arriving after another device finished the review."""

    session = api.session(status="completed", ended_at=api.clock())
    result = api.decide(_asking(api), "cancel", session_id=session.id)
    assert result["session_counts"]["cancelled"] == 1


def test_020_FR_042_decisions_are_accepted_with_the_flag_off(api: ReviewApi) -> None:
    """Exposure only: a queued decision never fails because the flag is off."""

    api.flag("off")
    assert api.decide(_asking(api), "complete")["task"]["state"] == "completed"


# --------------------------------------------------------------- undo
def test_020_FR_048_undo_restores_the_task_and_its_clock_field_for_field(
    api: ReviewApi,
) -> None:
    """Revision + 1, clock included, decision row and receipt gone, counter down."""

    task = _asking(api, details="Tiles from Ann")
    before = api.stored(task["id"])
    session = api.session()
    result = api.decide(
        task, "someday", session_id=session.id, stall_reason="no_energy"
    )
    undone = api.undo_raw(result["decision"]["id"], result["task"]["revision"])
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert body["undone_decision_id"] == result["decision"]["id"]
    assert body["deleted_task_id"] is None
    assert body["session_counts"]["someday"] == 0
    restored = api.stored(task["id"])
    assert restored.revision == result["task"]["revision"] + 1
    for field in (
        "state",
        "title",
        "details",
        "formulation_id",
        "formulation_started_at",
        "formulation_extended_at",
        "formulation_park_floor_at",
        "consecutive_stalled_formulations",
        "parked",
    ):
        assert getattr(restored, field) == getattr(before, field), field
    assert body["task"]["formulation"] == task["formulation"]
    assert api.decisions() == []
    assert api.container.task_repo.list_review_receipts(api.owner_id) == []


def test_020_FR_048_undo_of_a_follow_up_deletes_the_unchanged_follow_up(
    api: ReviewApi,
) -> None:
    """The created task goes only while its revision is the one created."""

    task = _waiting(api)
    result = api.decide(task, "follow_up", title="Call Ann")
    created_id = result["created_task"]["id"]
    body = api.undo_raw(result["decision"]["id"], result["task"]["revision"]).json()
    assert body["deleted_task_id"] == created_id
    assert api.client.get(f"/api/tasks/{created_id}").status_code == 404


def test_020_FR_048_undo_after_the_follow_up_changed_is_unavailable(
    api: ReviewApi,
) -> None:
    """An edit made to the follow-up elsewhere is never lost."""

    task = _waiting(api)
    result = api.decide(task, "follow_up", title="Call Ann")
    api.patch(result["created_task"], details="Ann prefers mornings")
    response = api.undo_raw(result["decision"]["id"], result["task"]["revision"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "undo_unavailable"}
    assert api.task(result["created_task"]["id"])["details"] == "Ann prefers mornings"
    assert len(api.decisions()) == 1


def test_020_FR_048_undo_after_the_task_changed_or_the_snapshot_was_purged(
    api: ReviewApi,
) -> None:
    """Any later change, or a nulled 7-day snapshot: 409, nothing changes."""

    task = _asking(api)
    result = api.decide(task, "waiting", waiting_for="Ann")
    changed = api.patch(result["task"], details="Called twice")
    response = api.undo_raw(result["decision"]["id"], changed["revision"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "undo_unavailable"}

    other = api.decide(_asking(api), "complete")
    repo = api.container.task_repo
    stored = repo.get_review_decision(api.owner_id, other["decision"]["id"])
    assert stored is not None
    repo.save_review_decision(stored.model_copy(update={"undo": None}))
    purged = api.undo_raw(other["decision"]["id"], other["task"]["revision"])
    assert purged.status_code == 409
    assert purged.json()["detail"] == {"reason": "undo_unavailable"}


def test_020_FR_048_undo_is_404_when_already_undone_or_not_owned(
    api: ReviewApi,
) -> None:
    """Including a retried undo whose first delivery applied, after 24 h."""

    task = _asking(api)
    result = api.decide(task, "complete")
    headers = api.key()
    first = api.undo_raw(result["decision"]["id"], result["task"]["revision"], headers)
    assert first.status_code == 200
    replay = api.undo_raw(result["decision"]["id"], result["task"]["revision"], headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()

    api.clock.advance(IDEMPOTENCY_RETENTION + timedelta(hours=1))
    revision = api.task(task["id"])["revision"]
    late = api.undo_raw(result["decision"]["id"], result["task"]["revision"], headers)
    assert late.status_code == 404
    assert late.json()["detail"]["resource"] == "Review decision"
    assert api.task(task["id"])["revision"] == revision
    assert api.undo_raw(new_id("decision"), 1).status_code == 404


def test_020_FR_048_undo_is_accepted_with_the_flag_off(api: ReviewApi) -> None:
    api.flag("off")
    result = api.decide(_asking(api), "complete")
    assert (
        api.undo_raw(result["decision"]["id"], result["task"]["revision"]).status_code
        == 200
    )


# --------------------------------------------------------------- reconcile
def test_020_FR_011_a_lost_decision_write_is_repaired_by_its_replay(
    api: ReviewApi,
) -> None:
    """The ``decide_task:`` reconciler re-applies a record left before its write."""

    task = _asking(api)
    headers = api.key()
    result = api.decide_raw(task, "complete", headers=headers).json()
    repo = api.container.task_repo
    before = api.stored(task["id"]).model_copy(
        update={"state": "next", "completed_at": None, "revision": task["revision"]}
    )
    repo.save(before)
    repo.delete_review_decision(api.owner_id, result["decision"]["id"])

    replay = api.decide_raw(task, "complete", headers=headers)
    assert replay.status_code == 200
    assert api.task(task["id"])["state"] == "completed"
    assert [d.id for d in api.decisions()] == [result["decision"]["id"]]


@pytest.mark.parametrize(
    "command",
    [
        "decide_task:task_x",
        "undo_decision:decision_x",
        "auto-park:task_x",
        "bulk_release:user_x",
        "undo_bulk_release:bulk_x",
        "review_session:user_x",
        "review_settings:user_x",
        "explainer_ack:user_x",
    ],
)
def test_020_FR_011_task_reconciliation_never_misreads_a_review_record(
    api: ReviewApi, command: str
) -> None:
    """Every review prefix is ReviewService's: ``TaskService`` skips it.

    Its default branch would validate the composite review body as a task
    snapshot and fail the next command that reuses the key (http §9).
    """

    repo = api.container.task_repo
    key = f"reconcile-{command}"
    with repo.command_lock(api.owner_id):
        repo.save_idempotency(
            owner_id=api.owner_id,
            record=IdempotencyRecord(
                key=key,
                command=command,
                request_hash="0" * 64,
                resource_id="x",
                response_body={"composite": "review result"},
                created_at=api.clock(),
            ),
        )
        api.container.task_service._reconcile_idempotent_result(
            owner_id=api.owner_id, key=key
        )
        api.container.task_service._reconcile_idempotent_results(owner_id=api.owner_id)


@pytest.mark.parametrize(
    "command",
    ["bulk_release:user_x", "undo_bulk_release:bulk_x", "review_session:user_x"],
)
def test_020_FR_011_flow_prefixes_are_registered_and_inert_until_the_flow_slice(
    api: ReviewApi, command: str
) -> None:
    """The review-flow prefixes are in ReviewService's registry (PR-11 fills them)."""

    repo = api.container.task_repo
    with repo.command_lock(api.owner_id):
        repo.save_idempotency(
            owner_id=api.owner_id,
            record=IdempotencyRecord(
                key="flow-key",
                command=command,
                request_hash="0" * 64,
                resource_id="x",
                response_body={"composite": "review result"},
                created_at=api.clock(),
            ),
        )
        api.container.review_service._reconcile_idempotent_result(
            owner_id=api.owner_id, key="flow-key"
        )
    assert api.decisions() == []


# --------------------------------------------------------------- edge cases
def test_020_FR_006_return_to_next_can_change_the_title(api: ReviewApi) -> None:
    result = api.decide(_waiting(api), "return_to_next", title="Chase the plumber")
    assert result["task"]["title"] == "Chase the plumber"
    assert result["task"]["state"] == "next"


def test_020_FR_008_first_step_refuses_notes_that_would_overflow(
    api: ReviewApi,
) -> None:
    """Notes are never truncated to fit "Was: <old title>" (400, nothing applied)."""

    task = _asking(api, details="n" * 19_995)
    response = api.decide_raw(task, "first_step", title="Measure the wall")
    assert response.status_code == 400
    assert response.json()["detail"] == {"reason": "details_too_long"}
    assert api.decisions() == []


def test_020_FR_011_a_follow_up_id_already_used_is_id_conflict(api: ReviewApi) -> None:
    follow_up_id = new_id("task")
    api.decide(
        _waiting(api), "follow_up", title="Call Ann", follow_up_task_id=follow_up_id
    )
    again = api.decide_raw(
        _waiting(api), "follow_up", title="Call Ann", follow_up_task_id=follow_up_id
    )
    assert again.status_code == 409
    assert again.json()["detail"] == {"reason": "id_conflict"}


def test_020_FR_011_matching_replay_of_a_follow_up_returns_its_stored_parts(
    api: ReviewApi,
) -> None:
    """Follow-up, receipt and session counts come from what is stored now."""

    session = api.session()
    decision_id = new_id("decision")
    task = _waiting(api)
    first = api.decide(
        task,
        "follow_up",
        title="Call Ann",
        decision_id=decision_id,
        session_id=session.id,
    )
    replay = api.decide_raw(
        task,
        "follow_up",
        title="Call Ann",
        decision_id=decision_id,
        session_id=session.id,
    ).json()
    assert replay["created_task"]["id"] == first["created_task"]["id"]
    assert replay["receipt"] == first["receipt"]
    assert replay["session_counts"]["moved_to_next"] == 1

    api.container.task_repo.delete_task_record(
        api.owner_id, first["created_task"]["id"]
    )
    gone = api.decide_raw(
        task,
        "follow_up",
        title="Call Ann",
        decision_id=decision_id,
        session_id=session.id,
    ).json()
    assert gone["created_task"] is None


def test_020_FR_048_undo_when_the_follow_up_or_session_is_already_gone(
    api: ReviewApi,
) -> None:
    """A missing follow-up or session never blocks the undo of the task."""

    session = api.session()
    result = api.decide(
        _waiting(api), "follow_up", title="Call Ann", session_id=session.id
    )
    repo = api.container.task_repo
    repo.delete_task_record(api.owner_id, result["created_task"]["id"])
    with repo.command_lock(api.owner_id):
        repo._thread_state.conn.execute(  # type: ignore[attr-defined]
            "DELETE FROM review_sessions WHERE owner_id = ?", (api.owner_id,)
        )
    undone = api.undo_raw(result["decision"]["id"], result["task"]["revision"])
    assert undone.status_code == 200, undone.text
    assert undone.json()["session_counts"] is None


def test_020_FR_048_undo_keeps_a_receipt_a_later_decision_wrote(api: ReviewApi) -> None:
    """Only the receipt this decision wrote is removed by its undo."""

    task = _waiting(api)
    first = api.decide(task, "keep_waiting")
    second = api.decide(task, "keep_waiting")
    assert (
        api.undo_raw(first["decision"]["id"], first["task"]["revision"]).status_code
        == 200
    )
    receipt = api.container.task_repo.get_review_receipt(
        api.owner_id, task["id"], "waiting"
    )
    assert receipt is not None and receipt.decision_id == second["decision"]["id"]


def test_020_FR_011_replays_after_an_undo_and_a_lost_undo_repair(
    api: ReviewApi,
) -> None:
    """A decide replay never re-applies over an undo; a lost undo re-applies."""

    task = _asking(api)
    decide_key = api.key()
    result = api.decide_raw(task, "complete", headers=decide_key).json()
    undo_key = api.key()
    undone = api.undo_raw(
        result["decision"]["id"], result["task"]["revision"], undo_key
    )
    assert undone.status_code == 200
    replay = api.decide_raw(task, "complete", headers=decide_key)
    assert replay.status_code == 200
    assert api.task(task["id"])["state"] == "next"

    repo = api.container.task_repo
    decision = rd.ReviewDecisionDocument.model_validate(
        {
            **result["decision"],
            "owner_id": api.owner_id,
            "task_revision_before": 1,
            "task_revision_after": result["task"]["revision"],
            "review_counts_as": "done",
            "undo": {"task_before": api.stored(task["id"]).model_dump()},
        }
    )
    repo.save_review_decision(decision)
    repo.save(
        api.stored(task["id"]).model_copy(
            update={"revision": result["task"]["revision"]}
        )
    )
    again = api.undo_raw(result["decision"]["id"], result["task"]["revision"], undo_key)
    assert again.status_code == 200
    assert repo.get_review_decision(api.owner_id, result["decision"]["id"]) is None
    assert api.stored(task["id"]).revision == undone.json()["task"]["revision"]
