"""Spec 020: the guided weekly review over HTTP (contracts/http.md §6).

Runs (``POST/GET/PATCH /review/sessions``, ``…/finish``): client ids,
``replace_open``, merged and replay-safe progress (``progress_id``), Done-only
finish with ``completed_empty``, the 7-day idle close through the maintenance
sweep, and the matching-record replay of a start retried after the 24 h
idempotency retention. Queues (``GET /review/queues/{step}``): wins, the
decision-queue snapshot, the capacity mirror, Waiting and Someday eligibility,
projects without a next action and dates. Bulk release with server-side
eligibility and its clock-exact, idempotent Undo. Unknown and foreign ids
answer byte-identically (``second_api_client``).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import allure
import pytest
from fastapi.testclient import TestClient

from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import IdempotencyRecord, TaskDocument, TaskParkDocument
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION
from app.utils.time import from_isoformat

from .conftest import FrozenClock
from .test_review_auto_park import keep_alive, sweep
from .test_review_decisions_api import ReviewApi, new_id, norm

DAY = timedelta(days=1)
RETENTION_PASSED = IDEMPOTENCY_RETENTION + timedelta(hours=1)

SESSION_FIELDS = {
    "id",
    "mode",
    "entry",
    "origin",
    "status",
    "started_at",
    "last_activity_at",
    "ended_at",
    "current_step",
    "steps",
    "active_seconds_by_step",
    "counts",
    "set_aside_count",
    "qualifying_activity",
    "clear_start",
    "revision",
}
QUICK = ["wins", "inbox", "decisions", "summary"]
FULL = [
    "wins",
    "mind_sweep",
    "inbox",
    "decisions",
    "rest_of_next",
    "waiting",
    "projects",
    "someday",
    "dates",
    "summary",
]


class FlowApi(ReviewApi):
    """``ReviewApi`` plus the run, queue and bulk-release calls."""

    def start_raw(self, *, headers: dict[str, str] | None = None, **body: Any) -> Any:
        payload = {
            "mode": "quick",
            "entry": "list",
            "origin": "ios",
            "replace_open": False,
            **body,
        }
        return self.client.post(
            "/api/review/sessions", json=payload, headers=headers or self.key()
        )

    def start(self, **body: Any) -> dict[str, Any]:
        response = self.start_raw(**body)
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    def progress_raw(
        self,
        session_id: str,
        *,
        headers: dict[str, str] | None = None,
        **body: Any,
    ) -> Any:
        payload = {"progress_id": new_id("progress"), **body}
        return self.client.patch(
            f"/api/review/sessions/{session_id}",
            json=payload,
            headers=headers or self.key(),
        )

    def progress(self, session_id: str, **body: Any) -> dict[str, Any]:
        response = self.progress_raw(session_id, **body)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def finish_raw(
        self, session_id: str, *, headers: dict[str, str] | None = None, **body: Any
    ) -> Any:
        return self.client.post(
            f"/api/review/sessions/{session_id}/finish",
            json=body,
            headers=headers or self.key(),
        )

    def finish(self, session_id: str, **body: Any) -> dict[str, Any]:
        response = self.finish_raw(session_id, **body)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def get_session(self, session_id: str) -> Any:
        return self.client.get(f"/api/review/sessions/{session_id}")

    def queue_raw(self, step: str, session_id: str | None = None) -> Any:
        params = {} if session_id is None else {"session_id": session_id}
        return self.client.get(f"/api/review/queues/{step}", params=params)

    def queue(self, step: str, session_id: str | None = None) -> dict[str, Any]:
        response = self.queue_raw(step, session_id)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def bulk_raw(
        self,
        kind: str,
        items: list[dict[str, Any]],
        *,
        headers: dict[str, str] | None = None,
        **body: Any,
    ) -> Any:
        return self.client.post(
            "/api/review/bulk-releases",
            json={"kind": kind, "items": items, **body},
            headers=headers or self.key(),
        )

    def bulk(self, kind: str, items: list[dict[str, Any]], **body: Any) -> Any:
        response = self.bulk_raw(kind, items, **body)
        assert response.status_code == 200, response.text
        return response.json()

    def undo_bulk_raw(self, bulk_id: str, headers: dict[str, str] | None = None) -> Any:
        return self.client.post(
            f"/api/review/bulk-releases/{bulk_id}/undo",
            json={},
            headers=headers or self.key(),
        )

    def state(self) -> dict[str, Any]:
        response = self.client.get("/api/review/state")
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def stored_session(self, session_id: str) -> rd.ReviewSessionDocument:
        session = self.container.task_repo.get_review_session(self.owner_id, session_id)
        assert session is not None
        return session

    def sessions(self) -> list[rd.ReviewSessionDocument]:
        return self.container.task_repo.list_review_sessions(self.owner_id)

    def seed(
        self, state: str = "next", title: str = "Seeded task", **fields: Any
    ) -> TaskDocument:
        """A task written straight to the repository (volume seeds)."""

        now = self.clock()
        repo = self.container.task_repo
        values: dict[str, Any] = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "owner_id": self.owner_id,
            "title": title,
            "state": state,
            "order_key": repo.next_order_key(owner_id=self.owner_id, state=state),
            "created_at": now,
            "updated_at": now,
        }
        if state == "next":
            values["formulation_id"] = f"form_{uuid.uuid4().hex[:12]}"
            values["formulation_started_at"] = now
        values.update(fields)
        task = TaskDocument.model_validate(values)
        with repo.command_lock(self.owner_id):
            repo.create(task)
        return task

    def rewrite(self, task_id: str, **fields: Any) -> TaskDocument:
        repo = self.container.task_repo
        task = self.stored(task_id).model_copy(update=fields)
        with repo.command_lock(self.owner_id):
            repo.save(task)
        return task

    def ids(self, queue: dict[str, Any]) -> list[str]:
        return [item["id"] for item in queue["items"]]


@pytest.fixture
def flow(api_client: TestClient, frozen_clock: FrozenClock) -> FlowApi:
    review_api = FlowApi(api_client, frozen_clock)
    review_api.activate_at(frozen_clock() - 30 * DAY)
    review_api.flag("on")
    return review_api


def _without_reference(response: Any, *ids: str) -> str:
    """The response body with its correlation id dropped and ``ids`` masked."""

    body = response.json()
    body.pop("reference_id", None)
    text = json.dumps(body, sort_keys=True)
    for value in ids:
        text = text.replace(value, "<id>")
    return text


# ===================================================================== T126 runs
def test_020_FR_027_020_FR_028_quick_and_full_runs_start_with_their_steps(
    flow: FlowApi,
) -> None:
    """A run starts at any time; quick has four steps, full all ten."""

    session_id = new_id("review")
    with allure.step("Start a quick review offline-style with a client id"):
        response = flow.start_raw(
            id=session_id, mode="quick", entry="widget_decisions", skip_steps=["wins"]
        )
    assert response.status_code == 201, response.text
    assert response.headers.get("X-Correlation-ID")
    quick = response.json()
    assert set(quick) == SESSION_FIELDS
    assert quick["id"] == session_id
    assert quick["status"] == "open"
    assert list(quick["steps"]) == QUICK
    assert quick["steps"]["wins"] == "skipped"
    assert {quick["steps"][code] for code in QUICK[1:]} == {"pending"}
    assert quick["current_step"] == "inbox"
    assert quick["entry"] == "widget_decisions"
    assert quick["counts"] == dict.fromkeys(
        [
            "done",
            "reformulated",
            "first_step",
            "waiting",
            "someday",
            "cancelled",
            "extended",
            "inbox_processed",
            "kept",
            "moved_to_next",
        ],
        0,
    )
    assert quick["qualifying_activity"] is False
    assert quick["set_aside_count"] == 0
    assert quick["active_seconds_by_step"] == {}
    assert norm(quick["started_at"]) == norm(quick["last_activity_at"])

    with allure.step("A full review from the web gets a server-minted id"):
        full = flow.start(mode="full", origin="web", entry="sidebar", replace_open=True)
    assert list(full["steps"]) == FULL
    assert re.match(r"^review_[0-9a-f]{12}$", full["id"])
    assert full["current_step"] == "wins"
    fetched = flow.get_session(full["id"])
    assert fetched.status_code == 200
    assert fetched.json() == full


def test_020_FR_029_an_open_run_without_replace_open_is_open_session_exists(
    flow: FlowApi,
) -> None:
    first = flow.start()
    response = flow.start_raw(origin="web")
    assert response.status_code == 409
    assert response.headers.get("X-Correlation-ID")
    assert response.json()["detail"] == {
        "reason": "open_session_exists",
        "session_id": first["id"],
    }
    assert [s.id for s in flow.sessions()] == [first["id"]]


@pytest.mark.parametrize(
    ("activity", "status"), [(False, "abandoned"), (True, "partial")]
)
def test_020_FR_029_replace_open_ends_the_open_run_by_the_e3_rule(
    flow: FlowApi, activity: bool, status: str
) -> None:
    """Replaced without Done: partial with qualifying activity, else abandoned."""

    first = flow.start()
    if activity:
        flow.progress(first["id"], step={"code": "wins", "status": "finished"})
    flow.clock.advance(minutes=5)
    second = flow.start(replace_open=True, origin="web")
    ended = flow.get_session(first["id"]).json()
    assert ended["status"] == status
    assert norm(ended["ended_at"]) == norm(second["started_at"])
    assert second["status"] == "open"
    assert flow.state()["open_session"]["id"] == second["id"]


def test_020_FR_011_a_start_replays_by_key_and_a_reused_id_matches_or_conflicts(
    flow: FlowApi,
) -> None:
    session_id = new_id("review")
    headers = flow.key()
    first = flow.start_raw(headers=headers, id=session_id)
    with allure.step("Same key and body: the original response"):
        replay = flow.start_raw(headers=headers, id=session_id)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    other_body = flow.start_raw(headers=headers, id=session_id, mode="full")
    assert other_body.status_code == 409
    assert other_body.json()["detail"] == {"reason": "idempotency_conflict"}

    with allure.step("Another key, same id, same mode and origin: already applied"):
        matched = flow.start_raw(id=session_id)
    assert matched.status_code == 201
    assert matched.json() == flow.get_session(session_id).json()
    assert len(flow.sessions()) == 1

    for mismatch in ({"mode": "full"}, {"origin": "web"}):
        conflict = flow.start_raw(id=session_id, replace_open=True, **mismatch)
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == {"reason": "id_conflict"}
    assert len(flow.sessions()) == 1
    assert flow.stored_session(session_id).status == "open"


def test_020_FR_011_a_start_retried_after_the_retention_is_applied_once(
    flow: FlowApi,
) -> None:
    """The match is checked before ``replace_open``: nothing is replaced again."""

    session_id = new_id("review")
    headers = flow.key()
    body = {"id": session_id, "replace_open": True}
    first = flow.start_raw(headers=headers, **body)
    assert first.status_code == 201
    flow.clock.advance(minutes=10)
    later = flow.start(replace_open=True, origin="web")
    assert flow.stored_session(session_id).status == "abandoned"

    flow.clock.advance(RETENTION_PASSED)
    with allure.step("The lost first delivery is retried a day later"):
        retry = flow.start_raw(headers=headers, **body)
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == session_id
    assert retry.json()["status"] == "abandoned"
    assert flow.stored_session(later["id"]).status == "open"
    assert len(flow.sessions()) == 2

    mismatch = flow.start_raw(headers=headers, id=session_id, mode="full")
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == {"reason": "id_conflict"}


def test_020_FR_029_020_SC_004_progress_merges_monotonically_without_conflict(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Two devices move one run: no version conflict, statuses only move up."""

    first, second = second_api_client
    flow = FlowApi(first, frozen_clock)
    flow.activate_at(frozen_clock() - 30 * DAY)
    other = FlowApi(second, frozen_clock)
    session = flow.start(mode="full")
    sid = session["id"]
    own = flow.create("Call the plumber", state="next")
    theirs = other.create("Their task", state="next")

    flow.progress(sid, step={"code": "wins", "status": "finished"})
    merged = flow.progress(sid, step={"code": "wins", "status": "pending"})
    assert merged["steps"]["wins"] == "finished"
    flow.progress(sid, step={"code": "inbox", "status": "skipped"})
    merged = flow.progress(sid, step={"code": "inbox", "status": "finished"})
    assert merged["steps"]["inbox"] == "finished"
    merged = flow.progress(sid, step={"code": "inbox", "status": "skipped"})
    assert merged["steps"]["inbox"] == "finished"

    flow.progress(sid, current_step="decisions")
    merged = flow.progress(sid, current_step="inbox")
    assert merged["current_step"] == "inbox"

    flow.progress(sid, active_seconds={"code": "wins", "seconds": 40})
    merged = flow.progress(sid, active_seconds={"code": "wins", "seconds": 2})
    assert merged["active_seconds_by_step"]["wins"] == 42

    flow.progress(sid, inbox_processed_delta=2)
    merged = flow.progress(sid, inbox_processed_delta=-1)
    assert merged["counts"]["inbox_processed"] == 1
    merged = flow.progress(sid, inbox_processed_delta=-5)
    assert merged["counts"]["inbox_processed"] == 0

    flow.progress(sid, set_aside_task_id=own["id"])
    flow.progress(sid, set_aside_task_id=own["id"])
    flow.progress(sid, set_aside_task_id=theirs["id"])
    merged = flow.progress(sid, set_aside_task_id="task_000000000000")
    assert merged["set_aside_count"] == 1
    assert flow.stored_session(sid).set_aside_task_ids == [own["id"]]
    assert merged["revision"] > session["revision"]
    assert merged["status"] == "open"


def test_020_FR_050_not_now_sets_a_card_aside_and_leaves_it_asking(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """ "Not now" is progress, not a decision: the task keeps asking, unchanged.

    A set-aside id that is not an open task of the owner is ignored, and an
    unknown and a foreign id give the same answer (http §6, "Ownership").
    """

    first, second = second_api_client
    flow = FlowApi(first, frozen_clock)
    other = FlowApi(second, frozen_clock)
    flow.activate_at(frozen_clock() - 30 * DAY)
    flow.flag("on")
    asking = _asking_seeds(flow)
    sid = flow.start()["id"]
    flow.progress(sid, snapshot_decision_queue=True, current_step="decisions")
    card = flow.task(asking[0].id)
    with allure.step("Not now on the first card"):
        merged = flow.progress(sid, set_aside_task_id=card["id"])
    assert merged["set_aside_count"] == 1
    assert sum(merged["counts"].values()) == 0
    assert flow.decisions() == []
    after = flow.task(card["id"])
    assert after["revision"] == card["revision"]
    assert after["formulation"] == card["formulation"]
    assert card["id"] in flow.ids(flow.queue("decisions"))
    assert flow.ids(flow.queue("decisions", sid))[0] == card["id"]

    with allure.step("Another owner names a foreign and an unknown task"):
        foreign_run = other.start()["id"]
        foreign = other.progress_raw(foreign_run, set_aside_task_id=card["id"])
        unknown_run = other.start(replace_open=True)["id"]
        unknown = other.progress_raw(unknown_run, set_aside_task_id="task_0123456789ab")
    assert foreign.status_code == unknown.status_code == 200
    assert foreign.json()["set_aside_count"] == unknown.json()["set_aside_count"] == 0
    assert _without_reference(foreign, foreign_run) == _without_reference(
        unknown, unknown_run
    )


@pytest.mark.parametrize(
    "change",
    [
        {"step": {"code": "dates", "status": "finished"}},
        {"step": {"code": "mind_sweep", "status": "skipped"}},
        {"active_seconds": {"code": "rest_of_next", "seconds": 30}},
    ],
    ids=["step-finished", "step-skipped", "active-seconds"],
)
@pytest.mark.parametrize("ended", [False, True], ids=["open", "ended"])
def test_020_FR_028_a_quick_run_refuses_progress_for_a_step_outside_its_mode(
    flow: FlowApi, change: dict[str, Any], ended: bool
) -> None:
    """A step code not in the run's ``steps`` is 422, the validation envelope.

    A quick run has four steps; a full-only code would otherwise add a step
    the run never shows, and could make it qualify (FR-028, FR-029). The
    check comes first, so an ended run refuses it too instead of ignoring it.
    """

    sid = flow.start()["id"]
    if ended:
        flow.finish(sid)
    before = flow.stored_session(sid)
    with allure.step("Progress names a step only a full review has"):
        response = flow.progress_raw(sid, **change)
    assert response.status_code == 422, response.text
    assert response.headers.get("X-Correlation-ID")
    body = response.json()
    assert body["message"] == "Request validation failed."
    field = next(iter(change))
    assert [error["loc"] for error in body["detail"]] == [["body", field, "code"]]
    assert flow.stored_session(sid) == before

    with allure.step("A full review accepts the same change"):
        full = flow.start(mode="full", replace_open=True)["id"]
        accepted = flow.progress_raw(full, **change)
    assert accepted.status_code == 200, accepted.text


def test_020_FR_028_a_quick_run_accepts_its_own_steps(flow: FlowApi) -> None:
    sid = flow.start()["id"]
    for code in QUICK:
        flow.progress(sid, active_seconds={"code": code, "seconds": 1})
        flow.progress(sid, step={"code": code, "status": "skipped"})
    stored = flow.stored_session(sid)
    assert stored.active_seconds_by_step == dict.fromkeys(QUICK, 1)
    assert set(stored.steps) == set(QUICK)
    assert {step.status for step in stored.steps.values()} == {"skipped"}


def test_020_FR_029_progress_without_a_progress_id_is_422(flow: FlowApi) -> None:
    session = flow.start()
    response = flow.client.patch(
        f"/api/review/sessions/{session['id']}",
        json={"current_step": "decisions"},
        headers=flow.key(),
    )
    assert response.status_code == 422
    free_text = flow.progress_raw(session["id"], progress_id="progress_SENTINEL")
    assert free_text.status_code == 422


def test_020_FR_011_020_SC_004_a_progress_change_resent_is_merged_once(
    flow: FlowApi,
) -> None:
    """Within and after the 24 h retention, one ``progress_id`` counts once."""

    sid = flow.start()["id"]
    progress_id = new_id("progress")
    body = {
        "progress_id": progress_id,
        "current_step": "inbox",
        "active_seconds": {"code": "wins", "seconds": 30},
        "inbox_processed_delta": 1,
    }
    headers = flow.key()
    first = flow.progress_raw(sid, headers=headers, **body).json()
    flow.clock.advance(minutes=3)
    moved = flow.progress(sid, current_step="decisions")

    with allure.step("The same change under a new key (lost response)"):
        again = flow.progress_raw(sid, **body)
    assert again.status_code == 200
    resent = again.json()
    assert resent["active_seconds_by_step"]["wins"] == 30
    assert resent["counts"]["inbox_processed"] == 1
    assert resent["current_step"] == "decisions"
    assert resent["revision"] == moved["revision"]
    assert norm(resent["last_activity_at"]) == norm(moved["last_activity_at"])

    with allure.step("The same key and body a day later, after the retention"):
        flow.clock.advance(RETENTION_PASSED)
        late = flow.progress_raw(sid, headers=headers, **body)
    assert late.status_code == 200, late.text
    assert late.json()["active_seconds_by_step"]["wins"] == 30
    assert late.json()["counts"]["inbox_processed"] == 1
    assert late.json()["current_step"] == "decisions"
    assert first["counts"]["inbox_processed"] == 1


def test_020_FR_011_the_same_progress_id_with_another_body_is_id_conflict(
    flow: FlowApi,
) -> None:
    sid = flow.start()["id"]
    progress_id = new_id("progress")
    flow.progress(sid, progress_id=progress_id, inbox_processed_delta=1)
    conflict = flow.progress_raw(sid, progress_id=progress_id, inbox_processed_delta=2)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"reason": "id_conflict"}
    assert flow.get_session(sid).json()["counts"]["inbox_processed"] == 1


def test_020_FR_029_applied_progress_is_internal_and_dropped_when_the_run_ends(
    flow: FlowApi,
) -> None:
    sid = flow.start()["id"]
    progress_id = new_id("progress")
    merged = flow.progress(sid, progress_id=progress_id, current_step="decisions")
    assert "applied_progress" not in merged
    stored = flow.stored_session(sid).applied_progress
    assert list(stored) == [progress_id]
    assert re.match(r"^[0-9a-f]{64}$", stored[progress_id])
    flow.finish(sid)
    assert flow.stored_session(sid).applied_progress == {}


def test_020_FR_029_progress_on_a_finished_run_is_accepted_and_ignored(
    flow: FlowApi,
) -> None:
    sid = flow.start()["id"]
    finished = flow.finish(sid)
    ignored = flow.progress(sid, inbox_processed_delta=3, current_step="wins")
    assert ignored == finished


@pytest.mark.parametrize(
    ("progress", "status"),
    [
        ([], "completed_empty"),
        ([{"step": {"code": "wins", "status": "skipped"}}], "completed_empty"),
        ([{"step": {"code": "wins", "status": "finished"}}], "completed"),
        ([{"inbox_processed_delta": 1}], "completed"),
        ([{"step": {"code": "summary", "status": "finished"}}], "completed_empty"),
    ],
)
def test_020_FR_029_finish_means_done_completed_or_completed_empty(
    flow: FlowApi, progress: list[dict[str, Any]], status: str
) -> None:
    sid = flow.start()["id"]
    for change in progress:
        flow.progress(sid, **change)
    flow.clock.advance(minutes=4)
    with allure.step("Done on the summary"):
        finished = flow.finish(sid, clear_start="yes")
    assert finished["status"] == status
    assert finished["clear_start"] == "yes"
    assert norm(finished["ended_at"]) == norm(flow.clock().isoformat())
    with allure.step("Finishing again returns the run unchanged"):
        again = flow.finish(sid, clear_start="not_really")
    assert again == finished


def test_020_FR_029_a_step_with_items_left_to_decide_does_not_qualify(
    flow: FlowApi,
) -> None:
    """Finishing the Inbox step past items without deciding is no activity."""

    flow.create("Unprocessed", state="inbox")
    sid = flow.start()["id"]
    merged = flow.progress(sid, step={"code": "inbox", "status": "finished"})
    assert merged["qualifying_activity"] is False
    assert flow.finish(sid)["status"] == "completed_empty"


def _display_step_seeds(flow: FlowApi) -> None:
    """Something in every display step's view, and a project left stuck.

    The stuck project (no Next task) makes the deciding-step fallthrough of
    ``_nothing_to_decide`` answer "something to decide", so a display step
    that lost its always-true rule cannot pass by falling through.
    """

    now = flow.clock()
    flow.seed("completed", title="Won this week", completed_at=now - 2 * DAY)
    flow.seed(title="Fresh Next task", formulation_started_at=now - 2 * DAY)
    flow.seed(
        "waiting", title="Due soon", waiting_for="Ann", due_date=(now + 3 * DAY).date()
    )
    flow.seed("inbox", title="Captured in the mind sweep")
    response = flow.client.post(
        "/api/projects", json={"name": "Kitchen"}, headers=flow.key()
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("step", ["wins", "mind_sweep", "rest_of_next", "dates"])
def test_020_FR_029_display_steps_always_nothing_to_decide(
    flow: FlowApi, step: str
) -> None:
    """Owner decision 2026-10-07: a display step finished is a counted review.

    Wins, Mind sweep, Rest of Next and Dates show items but ask for no
    decision, so finishing only that step, with items in its queue, is
    qualifying activity (data-model E3, FR-029).
    """

    start = flow.clock()
    flow.clock.set(start - 22 * DAY)
    flow.put_settings(onboarded=True)
    flow.clock.set(start)
    _display_step_seeds(flow)
    before = flow.state()
    assert before["restart_mode"] is True
    assert before["last_counted_review_at"] is None
    sid = flow.start(mode="full")["id"]
    if step != "mind_sweep":
        assert flow.queue(step, sid)["items"], f"{step} queue must not be empty"
    assert flow.queue("projects", sid)["items"] == []
    assert flow.container.review_service.tasks.list_projects(owner_id=flow.owner_id)

    with allure.step(f"Finish only the {step} step"):
        merged = flow.progress(
            sid, current_step=step, step={"code": step, "status": "finished"}
        )
    assert merged["qualifying_activity"] is True
    assert sum(merged["counts"].values()) == 0
    assert [
        code for code, status in merged["steps"].items() if status != "pending"
    ] == [step]

    flow.clock.advance(minutes=3)
    with allure.step("Done on the summary"):
        finished = flow.finish(sid)
    assert finished["status"] == "completed"
    after = flow.state()
    assert after["last_counted_review_at"] is not None
    assert norm(after["last_counted_review_at"]) == norm(finished["ended_at"])
    assert after["restart_mode"] is False


def test_020_FR_029_020_SC_001_leaving_keeps_the_run_open_and_counted_once_it_qualifies(
    flow: FlowApi,
) -> None:
    """There is no "left" outcome; an open run with activity is a counted review."""

    sid = flow.start()["id"]
    flow.clock.advance(minutes=2)
    assert flow.state()["last_counted_review_at"] is None
    task = flow.create("Call Bob", state="waiting", waiting_for="Bob")
    flow.clock.advance(minutes=1)
    flow.decide(task, "keep_waiting", session_id=sid)
    state = flow.state()
    assert state["open_session"]["id"] == sid
    assert state["open_session"]["status"] == "open"
    assert state["open_session"]["qualifying_activity"] is True
    assert norm(state["last_counted_review_at"]) == norm(flow.clock().isoformat())


@pytest.mark.parametrize(
    ("activity", "status"), [(False, "abandoned"), (True, "partial")]
)
def test_020_FR_029_the_seven_day_idle_close_runs_in_the_sweep(
    flow: FlowApi, activity: bool, status: str
) -> None:
    sid = flow.start()["id"]
    if activity:
        flow.progress(sid, inbox_processed_delta=1)
    last = flow.stored_session(sid).last_activity_at
    flow.clock.advance(days=6, hours=23)
    sweep(flow.container)
    assert flow.stored_session(sid).status == "open"
    flow.clock.advance(hours=2)
    with allure.step("The maintenance sweep closes the idle run"):
        result = sweep(flow.container)
    closed = flow.stored_session(sid)
    assert closed.status == status
    assert closed.ended_at == last + 7 * DAY
    assert closed.applied_progress == {}
    assert result.closed == 1
    assert sweep(flow.container).closed == 0


def test_020_FR_045_unknown_and_foreign_session_ids_give_the_same_404(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Queue ``session_id`` and the session path: no existence oracle."""

    first, second = second_api_client
    owner = FlowApi(first, frozen_clock)
    other = FlowApi(second, frozen_clock)
    owner.flag("on")
    foreign_id = owner.start()["id"]
    unknown_id = new_id("review")
    for step in ("decisions", "wins"):
        foreign = other.queue_raw(step, foreign_id)
        unknown = other.queue_raw(step, unknown_id)
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json()["detail"] == {
            "resource": "Review session",
            "id": foreign_id,
        }
        assert _without_reference(foreign, foreign_id) == _without_reference(
            unknown, unknown_id
        )
        assert foreign.headers.get("X-Correlation-ID")
    for call in (
        lambda sid: other.get_session(sid),
        lambda sid: other.progress_raw(sid, current_step="wins"),
        lambda sid: other.finish_raw(sid),
    ):
        foreign = call(foreign_id)
        unknown = call(unknown_id)
        assert foreign.status_code == unknown.status_code == 404
        assert foreign.json()["detail"] == {
            "resource": "Review session",
            "id": foreign_id,
        }
        assert _without_reference(foreign, foreign_id) == _without_reference(
            unknown, unknown_id
        )
    assert owner.stored_session(foreign_id).status == "open"


@pytest.mark.parametrize(
    "session_id",
    [
        "SENTINEL free text",
        "review_SENTINEL",
        f"decision_{uuid.uuid4()}",
        f"review_{str(uuid.uuid4()).upper()}",
        "review_" + "0" * 70,
    ],
    ids=["free-text", "bad-suffix", "other-prefix", "uppercase", "too-long"],
)
def test_020_FR_045_a_queue_session_id_of_another_shape_is_422(
    flow: FlowApi, session_id: str
) -> None:
    """The query ``session_id`` is a ``SessionRef`` (http "Client-supplied ids")."""

    with allure.step("Ask for a queue with a malformed session id"):
        response = flow.queue_raw("decisions", session_id)
    assert response.status_code == 422, response.text
    assert response.headers.get("X-Correlation-ID")
    body = response.json()
    assert body["message"] == "Request validation failed."
    assert [error["loc"] for error in body["detail"]] == [["query", "session_id"]]
    assert "SENTINEL" not in response.text


@pytest.mark.parametrize(
    "session_id",
    [f"review_{uuid.uuid4()}", "review_0123456789ab"],
    ids=["client-shape", "server-shape"],
)
def test_020_FR_045_a_queue_session_id_of_either_shape_is_looked_up(
    flow: FlowApi, session_id: str
) -> None:
    """Both accepted shapes pass validation and reach the ownership 404."""

    response = flow.queue_raw("wins", session_id)
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {"resource": "Review session", "id": session_id}


_BAD_PATH_IDS = ["SENTINEL free text", "{prefix}_SENTINEL", "{prefix}_" + "0" * 70]


@pytest.mark.parametrize("raw_id", _BAD_PATH_IDS, ids=["free-text", "bad", "long"])
@pytest.mark.parametrize("route", ["get", "progress", "finish", "undo"])
def test_020_FR_045_a_path_id_of_another_shape_is_422(
    flow: FlowApi, route: str, raw_id: str
) -> None:
    """Path ids are references too (http "Client-supplied ids"): 422, no echo.

    A session path takes a ``SessionRef``; the bulk-release Undo path the
    ``bulk_`` reference shape. Nothing reaches storage or the 404 body.
    """

    prefix = "bulk" if route == "undo" else "review"
    bad = raw_id.format(prefix=prefix)
    with allure.step(f"{route} with a malformed path id"):
        if route == "get":
            response = flow.get_session(bad)
        elif route == "progress":
            response = flow.progress_raw(bad, current_step="wins")
        elif route == "finish":
            response = flow.finish_raw(bad)
        else:
            response = flow.undo_bulk_raw(bad)
    assert response.status_code == 422, response.text
    assert response.headers.get("X-Correlation-ID")
    body = response.json()
    assert body["message"] == "Request validation failed."
    name = "bulk_id" if route == "undo" else "session_id"
    assert [error["loc"] for error in body["detail"]] == [["path", name]]
    assert "SENTINEL" not in response.text


@pytest.mark.parametrize("route", ["get", "finish", "undo"])
def test_020_FR_045_a_server_minted_path_id_reaches_the_lookup(
    flow: FlowApi, route: str
) -> None:
    """The server-minted ``<prefix>_<12 hex>`` shape is accepted on every path."""

    if route == "undo":
        response = flow.undo_bulk_raw("bulk_0123456789ab")
        resource = "Review bulk release"
    elif route == "get":
        response = flow.get_session("review_0123456789ab")
        resource = "Review session"
    else:
        response = flow.finish_raw("review_0123456789ab")
        resource = "Review session"
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["resource"] == resource


def test_020_FR_042_flag_off_hides_the_reads_and_accepts_the_writes(
    flow: FlowApi,
) -> None:
    flow.flag("off")
    with allure.step("Writes that finish started work are accepted"):
        session = flow.start()
        flow.progress(session["id"], current_step="decisions")
        flow.finish(session["id"])
    for response in (
        flow.get_session(session["id"]),
        flow.queue_raw("wins", session["id"]),
        flow.queue_raw("decisions"),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == {"reason": "weekly_review_disabled"}


def test_020_FR_045_session_writes_need_an_idempotency_key(flow: FlowApi) -> None:
    response = flow.client.post(
        "/api/review/sessions",
        json={"mode": "quick", "entry": "list", "origin": "ios", "replace_open": False},
    )
    assert response.status_code == 400
    assert response.headers.get("X-Correlation-ID")
    assert flow.sessions() == []


def test_020_FR_011_a_lost_run_write_is_repaired_by_its_replay(flow: FlowApi) -> None:
    """The ``review_session:`` reconciler re-applies a record left before its write."""

    headers = flow.key()
    session_id = new_id("review")
    flow.start_raw(headers=headers, id=session_id)
    progress_headers = flow.key()
    body = {"progress_id": new_id("progress"), "inbox_processed_delta": 1}
    merged = flow.progress_raw(session_id, headers=progress_headers, **body).json()
    repo = flow.container.task_repo
    stored = flow.stored_session(session_id)
    with repo.command_lock(flow.owner_id):
        repo.save_review_session(
            stored.model_copy(
                update={
                    "revision": 1,
                    "counts": rd.SessionCountsDocument(),
                    "applied_progress": {},
                }
            )
        )
    with allure.step("The replay of the progress repairs the lost merge"):
        replay = flow.progress_raw(session_id, headers=progress_headers, **body)
    assert replay.status_code == 200
    assert replay.json() == merged
    assert flow.get_session(session_id).json()["counts"]["inbox_processed"] == 1


# ===================================================================== T127 queues
def test_020_FR_028_wins_are_the_tasks_completed_in_the_last_seven_days(
    flow: FlowApi,
) -> None:
    now = flow.clock()
    old = flow.seed("completed", completed_at=now - 8 * DAY)
    recent = flow.seed("completed", completed_at=now - 2 * DAY)
    latest = flow.seed("completed", completed_at=now - DAY)
    flow.seed("cancelled", cancelled_at=now - DAY)
    sid = flow.start()["id"]
    wins = flow.queue("wins", sid)
    assert flow.ids(wins) == [latest.id, recent.id]
    assert old.id not in flow.ids(wins)
    assert wins["meta"] == {"count": 2}


def test_020_FR_028_inbox_and_steps_without_a_queue(flow: FlowApi) -> None:
    first = flow.create("First capture")
    second = flow.create("Second capture")
    flow.create("Not inbox", state="next")
    sid = flow.start(mode="full")["id"]
    inbox = flow.queue("inbox", sid)
    assert flow.ids(inbox) == [first["id"], second["id"]]
    assert inbox["meta"] == {}
    for step in ("mind_sweep", "summary"):
        assert flow.queue(step, sid) == {"items": [], "meta": {}}


def _asking_seeds(flow: FlowApi) -> list[TaskDocument]:
    """Three Next tasks asking at different instants, plus one fresh task."""

    now = flow.clock()
    late = flow.seed(title="Asks latest", formulation_started_at=now - 15 * DAY)
    early = flow.seed(title="Asks first", formulation_started_at=now - 19 * DAY)
    middle = flow.seed(title="Asks second", formulation_started_at=now - 17 * DAY)
    flow.seed(title="Fresh", formulation_started_at=now - 2 * DAY)
    return [early, middle, late]


def test_020_FR_028_020_FR_034_the_decision_queue_is_a_stable_snapshot(
    flow: FlowApi,
) -> None:
    """formulation-clock §5 order; a threshold change does not reshuffle it."""

    ordered = _asking_seeds(flow)
    sid = flow.start()["id"]
    flow.progress(sid, current_step="decisions", snapshot_decision_queue=True)
    queue = flow.queue("decisions", sid)
    assert flow.ids(queue) == [task.id for task in ordered]
    assert queue["meta"] == {"decided_task_ids": [], "set_aside_task_ids": []}
    assert flow.stored_session(sid).decision_queue == [task.id for task in ordered]

    with allure.step("The threshold changes to 28 days during the review"):
        flow.put_settings(threshold_days=28)
    assert flow.ids(flow.queue("decisions", sid)) == [task.id for task in ordered]
    assert flow.ids(flow.queue("decisions")) == []
    flow.progress(sid, snapshot_decision_queue=True)
    assert flow.stored_session(sid).decision_queue == [task.id for task in ordered]


def test_020_FR_048_020_FR_050_the_decision_queue_names_the_cards_already_handled(
    flow: FlowApi,
) -> None:
    """Any browser or device resuming the run learns which cards are done.

    A decision of the run marks its task decided (an Undo deletes it again);
    "Not now" marks it set aside unless it was decided afterwards; a read
    without a run, or another run, names none.
    """

    first, second, third = _asking_seeds(flow)
    sid = flow.start()["id"]
    flow.progress(sid, current_step="decisions", snapshot_decision_queue=True)
    flow.progress(sid, set_aside_task_id=first.id)
    flow.progress(sid, set_aside_task_id=third.id)

    with allure.step("A decision on the second card and on a set-aside card"):
        decided = flow.decide(flow.task(second.id), "someday", session_id=sid)
        flow.decide(flow.task(third.id), "cancel", session_id=sid)
    meta = flow.queue("decisions", sid)["meta"]
    assert meta == {
        "decided_task_ids": [second.id, third.id],
        "set_aside_task_ids": [first.id],
    }

    with allure.step("Undo takes the decision back, the card is not handled any more"):
        undone = flow.undo_raw(decided["decision"]["id"], decided["task"]["revision"])
        assert undone.status_code == 200, undone.text
    meta = flow.queue("decisions", sid)["meta"]
    assert meta["decided_task_ids"] == [third.id]
    assert meta["set_aside_task_ids"] == [first.id]

    with allure.step("Another run and a read without a run name nothing"):
        other = flow.start(replace_open=True, origin="web")["id"]
        flow.progress(other, snapshot_decision_queue=True)
        empty = {"decided_task_ids": [], "set_aside_task_ids": []}
        assert flow.queue("decisions", other)["meta"] == empty
        assert flow.queue("decisions")["meta"] == empty


def test_020_FR_028_without_a_snapshot_the_queue_is_the_live_aggregate(
    flow: FlowApi,
) -> None:
    ordered = _asking_seeds(flow)
    sid = flow.start()["id"]
    assert flow.ids(flow.queue("decisions", sid)) == [task.id for task in ordered]
    assert flow.stored_session(sid).decision_queue is None


def test_020_FR_028_020_FR_034_an_empty_snapshot_stays_taken(flow: FlowApi) -> None:
    """Taken with nothing asking is not "not taken": the queue stays empty.

    A later ``snapshot_decision_queue`` (another device opening the step, a
    resent change) must not fill it mid-review (http §6, data-model E3).
    """

    fresh = flow.seed(title="Ten days", formulation_started_at=flow.clock() - 10 * DAY)
    sid = flow.start()["id"]
    with allure.step("The decision step opens with nothing asking"):
        flow.progress(sid, current_step="decisions", snapshot_decision_queue=True)
    assert flow.stored_session(sid).decision_queue == []
    assert flow.queue("decisions", sid)["items"] == []

    with allure.step("A task starts asking, then the snapshot is asked for again"):
        flow.put_settings(threshold_days=7)
        assert flow.ids(flow.queue("decisions")) == [fresh.id]
        flow.progress(sid, snapshot_decision_queue=True)
    assert flow.stored_session(sid).decision_queue == []
    assert flow.queue("decisions", sid)["items"] == []
    repo = flow.container.task_repo
    with repo.command_lock(flow.owner_id):
        repo.save_review_session(flow.stored_session(sid))
    assert flow.stored_session(sid).decision_queue == []


def _completions(flow: FlowApi, count: int, *, first_days_ago: float) -> None:
    now = flow.clock()
    flow.seed("completed", completed_at=now - first_days_ago * DAY)
    for index in range(count - 1):
        flow.seed("completed", completed_at=now - (index % 27 + 1) * DAY)


def test_020_FR_031_capacity_mirror_with_four_weeks_of_history(flow: FlowApi) -> None:
    """41 Next and 36 completions in 4 weeks: 9 per week, about 4.5 weeks."""

    for _ in range(41):
        flow.seed()
    _completions(flow, 36, first_days_ago=27)
    flow.seed("completed", completed_at=flow.clock() - 63 * DAY)
    sid = flow.start(mode="full")["id"]
    meta = flow.queue("rest_of_next", sid)["meta"]
    assert meta["next_count"] == 41
    assert meta["weeks_of_history"] == 9
    assert meta["weekly_average_4w"] == 9.0
    assert meta["implied_weeks"] == pytest.approx(41 / 9)


@pytest.mark.parametrize("history", ["two_weeks", "none_recent", "never"])
def test_020_FR_031_capacity_mirror_shows_the_count_only_without_pace(
    flow: FlowApi, history: str
) -> None:
    for _ in range(12):
        flow.seed()
    if history == "two_weeks":
        _completions(flow, 6, first_days_ago=14)
    elif history == "none_recent":
        flow.seed("completed", completed_at=flow.clock() - 40 * DAY)
    sid = flow.start(mode="full")["id"]
    meta = flow.queue("rest_of_next", sid)["meta"]
    assert meta["next_count"] == 12
    assert meta["weekly_average_4w"] is None
    assert meta["implied_weeks"] is None


def test_020_FR_028_rest_of_next_lists_next_tasks_that_do_not_ask(
    flow: FlowApi,
) -> None:
    asking = _asking_seeds(flow)
    sid = flow.start(mode="full")["id"]
    rest = flow.queue("rest_of_next", sid)
    assert rest["meta"]["next_count"] == 4
    assert not {task.id for task in asking} & set(flow.ids(rest))
    assert len(rest["items"]) == 1


def test_020_FR_032_waiting_older_than_seven_days_without_a_receipt(
    flow: FlowApi,
) -> None:
    now = flow.clock()
    newest = flow.seed("waiting", waiting_for="Ann", waiting_since=now - 8 * DAY)
    oldest = flow.seed("waiting", waiting_for="Bob", waiting_since=now - 20 * DAY)
    flow.seed("waiting", waiting_for="Cid", waiting_since=now - 7 * DAY)
    kept = flow.seed("waiting", waiting_for="Dee", waiting_since=now - 30 * DAY)
    flow.decide(flow.task(kept.id), "keep_waiting")
    sid = flow.start(mode="full")["id"]
    assert flow.ids(flow.queue("waiting", sid)) == [oldest.id, newest.id]

    with allure.step("A change to the kept task makes its receipt stale"):
        flow.patch(flow.task(kept.id), details="Called again")
    assert flow.ids(flow.queue("waiting", sid)) == [kept.id, oldest.id, newest.id]


def test_020_FR_032_someday_pass_eligibility_and_order(flow: FlowApi) -> None:
    """quickstart Scenario 5 step 9: 12 eligible, 2 parked 5 days ago left out."""

    now = flow.clock()
    never = [
        flow.seed("someday", title=f"Never {i}", updated_at=now - (40 - i) * DAY)
        for i in range(8)
    ]
    reviewed = []
    for i in range(2):
        task = flow.seed("someday", title=f"Reviewed {i}")
        reviewed.append(task)
    receipts = flow.container.task_repo
    with receipts.command_lock(flow.owner_id):
        for i, task in enumerate(reviewed):
            receipts.save_review_receipt(
                rd.ReviewReceiptDocument(
                    owner_id=flow.owner_id,
                    task_id=task.id,
                    kind="someday",
                    task_revision=task.revision,
                    reviewed_at=now - (60 - i) * DAY,
                    hidden_until=now - (30 - i) * DAY,
                    source="keep",
                )
            )
    for i in range(2):
        flow.seed(
            "someday",
            title=f"Parked {i}",
            parked=TaskParkDocument.model_validate(
                {
                    "at": now - 5 * DAY,
                    "formulation_id": f"form_{uuid.uuid4().hex[:12]}",
                    "from_revision": 1,
                    "clock_before": {
                        "started_at": now - 40 * DAY,
                        "stalled_before": 0,
                    },
                }
            ),
        )
    sid = flow.start(mode="full")["id"]
    someday = flow.queue("someday", sid)
    assert someday["meta"] == {"eligible_total": 10, "shown": 7}
    assert flow.ids(someday) == [task.id for task in never[:7]]

    with allure.step("Tasks kept in Someday are left out for 30 days"):
        for task in never[:3]:
            flow.decide(flow.task(task.id), "keep_someday")
    later = flow.queue("someday", sid)
    assert later["meta"] == {"eligible_total": 7, "shown": 7}
    assert flow.ids(later) == [
        *[task.id for task in never[3:]],
        *[task.id for task in reviewed],
    ]


def test_020_FR_028_projects_without_a_next_action(flow: FlowApi) -> None:
    def project(name: str) -> str:
        response = flow.client.post(
            "/api/projects", json={"name": name}, headers=flow.key()
        )
        assert response.status_code == 201, response.text
        project_id: str = response.json()["id"]
        return project_id

    stuck = project("Kitchen")
    moving = project("Garden")
    waiting = flow.create(
        "Quote from Ann", state="waiting", waiting_for="Ann", project_id=stuck
    )
    flow.create("Prune the roses", state="next", project_id=moving)
    flow.create("Seeds", state="someday", project_id=moving)
    sid = flow.start(mode="full")["id"]
    projects = flow.queue("projects", sid)
    assert flow.ids(projects) == [waiting["id"]]
    assert projects["meta"] == {}


def test_020_FR_028_dates_in_the_next_fourteen_days_by_local_day(
    flow: FlowApi,
) -> None:
    """One entry per local day in the stored zone, in the manual order."""

    flow.put_settings(time_zone="Pacific/Auckland")
    today = flow.clock().astimezone(ZoneInfo("Pacific/Auckland")).date()
    assert today != flow.clock().date()
    second = flow.seed(title="Second", due_date=today, order_key=5)
    first = flow.seed("waiting", waiting_for="Ann", due_date=today, order_key=0)
    flow.seed(title="Yesterday", due_date=today - DAY)
    last = flow.seed("someday", due_date=today + 13 * DAY)
    flow.seed(title="Beyond", due_date=today + 14 * DAY)
    flow.seed("completed", due_date=today + DAY, completed_at=flow.clock())
    sid = flow.start(mode="full")["id"]
    dates = flow.queue("dates", sid)
    assert dates["meta"] == {
        "days": [
            {"day": str(today), "task_ids": [first.id, second.id]},
            {"day": str(today + 13 * DAY), "task_ids": [last.id]},
        ]
    }
    assert flow.ids(dates) == [first.id, second.id, last.id]


def test_020_SC_002_a_completed_run_leaves_no_asking_task_undecided(
    flow: FlowApi,
) -> None:
    """Every queued task that still asks has a decision on its current formulation."""

    _asking_seeds(flow)
    sid = flow.start()["id"]
    flow.progress(sid, snapshot_decision_queue=True, current_step="decisions")
    queue = flow.queue("decisions", sid)["items"]
    with allure.step("Decide every card; one keeps its wording (Save anyway)"):
        flow.decide(
            queue[0], "reformulate", title=queue[0]["title"] + ".", session_id=sid
        )
        flow.decide(queue[1], "complete", session_id=sid)
        flow.decide(queue[2], "first_step", title="Make the first call", session_id=sid)
    flow.progress(sid, step={"code": "decisions", "status": "finished"})
    finished = flow.finish(sid, clear_start="yes")
    assert finished["status"] == "completed"
    assert finished["set_aside_count"] == 0

    decided = {
        (d.task_id, d.formulation_id) for d in flow.decisions() if d.session_id == sid
    }
    queued = {task["id"] for task in queue}
    with allure.step("Every task that still asks was decided in this run"):
        still_asking = flow.ids(flow.queue("decisions"))
    assert still_asking == [queue[0]["id"]]
    for task_id in still_asking:
        assert task_id in queued
        assert (task_id, flow.stored(task_id).formulation_id) in decided
    assert flow.state()["counts"]["asks_for_decision"] == 1


@pytest.mark.parametrize(
    ("onboarded_days", "reviewed_days", "expected"),
    [
        (None, None, False),
        (22, None, True),
        (20, None, False),
        (40, 20, False),
        (40, 21, True),
    ],
)
def test_020_FR_017_restart_mode_anchors(
    flow: FlowApi,
    onboarded_days: int | None,
    reviewed_days: int | None,
    expected: bool,
) -> None:
    """21 days from the last counted review, else from onboarding; never before."""

    start = flow.clock()
    if onboarded_days is not None:
        flow.clock.set(start - onboarded_days * DAY)
        flow.put_settings(onboarded=True)
    if reviewed_days is not None:
        flow.clock.set(start - reviewed_days * DAY)
        sid = flow.start()["id"]
        flow.progress(sid, step={"code": "wins", "status": "finished"})
        flow.finish(sid)
        flow.clock.set(start - reviewed_days * DAY + timedelta(hours=1))
        empty = flow.start()["id"]
        flow.finish(empty)
    flow.clock.set(start)
    assert flow.state()["restart_mode"] is expected


# ===================================================================== T129 bulk
def _restart_seeds(flow: FlowApi) -> dict[str, TaskDocument]:
    """Restart candidates held in Next past 4 weeks, and two that are not."""

    now = flow.clock()
    extended = flow.seed(
        title="Held by an extension",
        formulation_started_at=now - 29 * DAY,
        formulation_extended_at=now - 14 * DAY,
        formulation_extension_reason="Waiting for the quote",
        consecutive_stalled_formulations=2,
    )
    floored = flow.seed(
        title="Held by a floor",
        formulation_started_at=now - 30 * DAY,
        formulation_park_floor_at=now + 3 * DAY,
    )
    paused = flow.seed(
        title="Pause ended",
        formulation_started_at=now - 45 * DAY,
        due_date=(now - 29 * DAY).date(),
    )
    young = flow.seed(title="Twenty days", formulation_started_at=now - 20 * DAY)
    still_paused = flow.seed(
        title="Still paused",
        formulation_started_at=now - 40 * DAY,
        due_date=(now + 3 * DAY).date(),
    )
    return {
        "extended": extended,
        "floored": floored,
        "paused": paused,
        "young": young,
        "still_paused": still_paused,
    }


def _items(*tasks: TaskDocument | dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for task in tasks:
        if isinstance(task, TaskDocument):
            items.append({"task_id": task.id, "expected_revision": task.revision})
        else:
            items.append({"task_id": task["id"], "expected_revision": task["revision"]})
    return items


def test_020_FR_017_020_FR_032_restart_release_with_server_side_eligibility(
    flow: FlowApi,
) -> None:
    seeds = _restart_seeds(flow)
    stale = flow.seed(
        title="Changed elsewhere", formulation_started_at=flow.clock() - 35 * DAY
    )
    unknown = "task_000000000000"
    bulk_id = new_id("bulk")
    body = _items(
        seeds["extended"],
        seeds["floored"],
        seeds["paused"],
        seeds["young"],
        seeds["still_paused"],
    ) + [
        {"task_id": stale.id, "expected_revision": stale.revision + 1},
        {"task_id": unknown, "expected_revision": 1},
    ]
    sid = flow.start(entry="restart")["id"]
    with allure.step("Release every Next task older than 4 weeks"):
        result = flow.bulk("restart", body, id=bulk_id, session_id=sid)
    assert result["id"] == bulk_id
    released = {item["task_id"]: item["revision_after"] for item in result["released"]}
    assert set(released) == {
        seeds["extended"].id,
        seeds["floored"].id,
        seeds["paused"].id,
    }
    assert result["skipped"] == [
        {"task_id": seeds["young"].id, "reason": "not_eligible"},
        {"task_id": seeds["still_paused"].id, "reason": "not_eligible"},
        {"task_id": stale.id, "reason": "stale"},
        {"task_id": unknown, "reason": "not_eligible"},
    ]
    for task_id, revision in released.items():
        task = flow.task(task_id)
        assert task["state"] == "someday"
        assert task["parked"] is None
        assert task["formulation"] is None
        assert task["revision"] == revision
        receipt = flow.container.task_repo.get_review_receipt(
            flow.owner_id, task_id, "someday"
        )
        assert receipt is not None
        assert receipt.source == "release"
        assert receipt.bulk_id == bulk_id
        assert receipt.hidden_until == flow.clock() + 30 * DAY
    record = flow.container.task_repo.get_bulk_release(flow.owner_id, bulk_id)
    assert record is not None
    assert record.session_id == sid
    assert {item.previous_state for item in record.released} == {"next"}
    snapshot = {item.task_id: item.clock_before for item in record.released}
    extended = snapshot[seeds["extended"].id]
    assert extended is not None
    assert extended.formulation_id == seeds["extended"].formulation_id
    assert extended.extension_reason == "Waiting for the quote"
    assert extended.stalled_before == 2
    with allure.step("Released tasks stay out of the Someday step (FR-032)"):
        assert not set(released) & set(flow.ids(flow.queue("someday", sid)))


def test_020_FR_017_undo_restores_each_clock_exactly_and_skips_changed_tasks(
    flow: FlowApi,
) -> None:
    seeds = _restart_seeds(flow)
    chosen = [seeds["extended"], seeds["floored"], seeds["paused"]]
    before = {task.id: flow.stored(task.id) for task in chosen}
    result = flow.bulk("restart", _items(*chosen))
    changed = flow.task(seeds["paused"].id)
    flow.patch(changed, details="Edited on the phone")
    flow.clock.advance(minutes=5)

    with allure.step("Undo the release"):
        undo = flow.undo_bulk_raw(result["id"])
    assert undo.status_code == 200, undo.text
    assert undo.json() == {
        "restored": [seeds["extended"].id, seeds["floored"].id],
        "skipped": [{"task_id": seeds["paused"].id, "reason": "stale"}],
    }
    for task in (seeds["extended"], seeds["floored"]):
        restored = flow.stored(task.id)
        original = before[task.id]
        assert restored.state == "next"
        assert restored.formulation_id == original.formulation_id
        assert restored.formulation_started_at == original.formulation_started_at
        assert restored.formulation_extended_at == original.formulation_extended_at
        assert (
            restored.formulation_extension_reason
            == original.formulation_extension_reason
        )
        assert restored.formulation_park_floor_at == original.formulation_park_floor_at
        assert (
            restored.consecutive_stalled_formulations
            == original.consecutive_stalled_formulations
        )
        assert restored.parked is None
        assert restored.revision == original.revision + 2
        assert (
            flow.container.task_repo.get_review_receipt(
                flow.owner_id, task.id, "someday"
            )
            is None
        )
    assert flow.stored(seeds["paused"].id).state == "someday"
    record = flow.container.task_repo.get_bulk_release(flow.owner_id, result["id"])
    assert record is not None and record.undone_at == flow.clock()
    assert record.undo_result == undo.json()


def test_020_FR_030_inbox_remainder_release_and_undo(flow: FlowApi) -> None:
    """Only Inbox tasks not processed in the run: a processed item has left Inbox."""

    remainder = [flow.create(f"Capture {i}") for i in range(3)]
    processed = flow.create("Processed in the run")
    sid = flow.start()["id"]
    processed = flow.move(processed, "next")
    flow.progress(sid, inbox_processed_delta=1)
    nxt = flow.create("Already next", state="next")
    result = flow.bulk(
        "inbox_remainder", _items(*remainder, processed, nxt), session_id=sid
    )
    assert [item["task_id"] for item in result["released"]] == [
        task["id"] for task in remainder
    ]
    assert result["skipped"] == [
        {"task_id": processed["id"], "reason": "not_eligible"},
        {"task_id": nxt["id"], "reason": "not_eligible"},
    ]
    record = flow.container.task_repo.get_bulk_release(flow.owner_id, result["id"])
    assert record is not None
    assert {item.previous_state for item in record.released} == {"inbox"}
    assert all(item.clock_before is None for item in record.released)
    assert {flow.task(t["id"])["state"] for t in remainder} == {"someday"}

    undo = flow.undo_bulk_raw(result["id"])
    assert undo.status_code == 200
    assert undo.json()["restored"] == [task["id"] for task in remainder]
    assert {flow.task(t["id"])["state"] for t in remainder} == {"inbox"}
    assert {flow.task(t["id"])["formulation"] is None for t in remainder} == {True}


def test_020_FR_011_an_undone_release_answers_its_stored_undo_result(
    flow: FlowApi,
) -> None:
    """A retried undo whose response was lost is a success, at any age."""

    seeds = _restart_seeds(flow)
    result = flow.bulk("restart", _items(seeds["extended"], seeds["floored"]))
    headers = flow.key()
    first = flow.undo_bulk_raw(result["id"], headers=headers)
    assert first.status_code == 200
    restored_revision = flow.stored(seeds["extended"].id).revision
    replay = flow.undo_bulk_raw(result["id"], headers=headers)
    assert replay.json() == first.json()

    with allure.step("A retry under another key, then after the retention"):
        again = flow.undo_bulk_raw(result["id"])
        assert again.status_code == 200
        assert again.json() == first.json()
        flow.clock.advance(days=8)
        flow.flag("off")  # retention still runs; nothing parks the restored tasks
        sweep(flow.container)
        late = flow.undo_bulk_raw(result["id"], headers=headers)
    assert late.status_code == 200, late.text
    assert late.json() == first.json()
    assert flow.stored(seeds["extended"].id).revision == restored_revision
    assert flow.stored(seeds["extended"].id).state == "next"


def test_020_FR_017_undo_is_unavailable_once_the_snapshot_was_purged(
    flow: FlowApi,
) -> None:
    seeds = _restart_seeds(flow)
    result = flow.bulk("restart", _items(seeds["extended"]))
    flow.clock.advance(days=7, minutes=1)
    sweep(flow.container)
    record = flow.container.task_repo.get_bulk_release(flow.owner_id, result["id"])
    assert record is not None and record.released[0].clock_before is None
    response = flow.undo_bulk_raw(result["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "undo_unavailable"}
    assert flow.stored(seeds["extended"].id).state == "someday"


def _assert_record_purged_by_the_sweep(
    flow: FlowApi, headers: dict[str, str], sentinel: str
) -> None:
    """The record holds ``sentinel`` until a sweep 8 days later removes it.

    The flag is off so only the retention part runs: the exposure part's own
    purge (and every later write's) cannot hide a missing retention purge.
    """

    repo = flow.container.task_repo
    key = headers["Idempotency-Key"]
    record = repo.get_idempotency(owner_id=flow.owner_id, key=key)
    assert record is not None
    assert sentinel in json.dumps(record.response_body)
    mirror = repo.idempotency_path(flow.owner_id, key)
    assert mirror.exists()
    flow.flag("off")
    flow.clock.advance(days=8)
    with allure.step("The maintenance sweep runs 8 days later, with no write"):
        sweep(flow.container)
    assert repo.get_idempotency(owner_id=flow.owner_id, key=key) is None
    assert not mirror.exists()
    stored = repo.list_idempotency_for_owner(owner_id=flow.owner_id)
    assert sentinel not in json.dumps([item.response_body for item in stored])


def test_020_FR_043_the_sweep_purges_a_bulk_release_idempotency_record(
    flow: FlowApi,
) -> None:
    """The record's ``clock_before`` holds the extension reason (E7, FR-043)."""

    seeds = _restart_seeds(flow)
    headers = flow.key()
    response = flow.bulk_raw("restart", _items(seeds["extended"]), headers=headers)
    assert response.status_code == 200, response.text
    _assert_record_purged_by_the_sweep(flow, headers, "Waiting for the quote")
    release = flow.container.task_repo.get_bulk_release(
        flow.owner_id, response.json()["id"]
    )
    assert release is not None
    assert [item.clock_before for item in release.released] == [None]


def test_020_FR_043_the_sweep_purges_a_decision_idempotency_record(
    flow: FlowApi,
) -> None:
    """A "keep 7 more days" record carries its reason text (FR-043)."""

    now = flow.clock()
    asking = flow.seed(title="Asks", formulation_started_at=now - 15 * DAY)
    headers = flow.key()
    response = flow.decide_raw(
        flow.task(asking.id), "extend", reason="SENTINEL-EXTEND-REASON", headers=headers
    )
    assert response.status_code == 200, response.text
    _assert_record_purged_by_the_sweep(flow, headers, "SENTINEL-EXTEND-REASON")


def test_020_FR_043_the_sweep_keeps_a_record_inside_its_24_hours(
    flow: FlowApi,
) -> None:
    capture = flow.create("Capture")
    headers = flow.key()
    flow.bulk_raw("inbox_remainder", _items(capture), headers=headers)
    flow.flag("off")
    flow.clock.advance(hours=23)
    sweep(flow.container)
    key = headers["Idempotency-Key"]
    repo = flow.container.task_repo
    assert repo.get_idempotency(owner_id=flow.owner_id, key=key) is not None


def test_020_FR_043_the_sweep_purges_records_of_an_owner_without_review_rows(
    api_client: TestClient, frozen_clock: FrozenClock
) -> None:
    """docs/data-retention.md "Task idempotency records": 24 h, by the sweep."""

    container = api_client.app.state.container  # type: ignore[attr-defined]
    owner_id = api_client.get("/api/auth/me").json()["id"]
    key = f"key-{uuid.uuid4()}"
    created = api_client.post(
        "/api/tasks", json={"title": "SENTINEL-TITLE"}, headers={"Idempotency-Key": key}
    )
    assert created.status_code == 201, created.text
    repo = container.task_repo
    assert owner_id not in repo.review_owner_ids()
    assert repo.get_idempotency(owner_id=owner_id, key=key) is not None
    frozen_clock.advance(RETENTION_PASSED)
    with allure.step("The maintenance sweep runs a day later, with no write"):
        sweep(container)
    assert repo.get_idempotency(owner_id=owner_id, key=key) is None
    assert not repo.idempotency_path(owner_id, key).exists()


def test_020_FR_043_the_sweep_visits_only_owners_with_a_purgeable_record(
    flow: FlowApi,
) -> None:
    """The owner query mirrors the purge: the cutoff, and the brain-dump exemption."""

    repo = flow.container.task_repo
    now = flow.clock()
    rows = {
        "user_expired": ("create_task", now - RETENTION_PASSED),
        "user_fresh": ("create_task", now - timedelta(hours=23)),
        "user_exempt": ("create_native_inbox_task", now - 30 * DAY),
    }
    for owner_id, (command, created_at) in rows.items():
        with repo.command_lock(owner_id):
            repo.save_idempotency(
                owner_id=owner_id,
                record=IdempotencyRecord(
                    key=f"key-{owner_id}",
                    command=command,
                    request_hash="0" * 64,
                    resource_id="x",
                    response_body={},
                    created_at=created_at,
                ),
            )
    cutoff = now - IDEMPOTENCY_RETENTION
    assert repo.idempotency_owner_ids(created_before=cutoff) == {"user_expired"}
    flow.flag("off")
    sweep(flow.container)
    for owner_id in rows:
        kept = repo.get_idempotency(owner_id=owner_id, key=f"key-{owner_id}")
        assert (kept is None) is (owner_id == "user_expired")


def test_020_FR_030_an_inbox_release_undo_is_unavailable_after_seven_days(
    flow: FlowApi,
) -> None:
    capture = flow.create("Capture")
    result = flow.bulk("inbox_remainder", _items(capture))
    flow.clock.advance(days=7)
    response = flow.undo_bulk_raw(result["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"reason": "undo_unavailable"}


def test_020_FR_011_a_bulk_release_retried_after_the_retention_is_applied_once(
    flow: FlowApi,
) -> None:
    """Matched before per-item revisions and eligibility; never released twice."""

    seeds = _restart_seeds(flow)
    bulk_id = new_id("bulk")
    headers = flow.key()
    items = _items(seeds["extended"], seeds["young"])
    first = flow.bulk_raw("restart", items, headers=headers, id=bulk_id)
    assert first.status_code == 200
    revision = flow.stored(seeds["extended"].id).revision

    with allure.step("Same id under another key within the retention"):
        matched = flow.bulk_raw("restart", list(reversed(items)), id=bulk_id)
    assert matched.status_code == 200
    assert matched.json() == first.json()

    flow.clock.advance(RETENTION_PASSED)
    with allure.step("The first delivery retried with its stale revisions"):
        retry = flow.bulk_raw("restart", items, headers=headers, id=bulk_id)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert flow.stored(seeds["extended"].id).revision == revision
    assert len(flow.container.task_repo.list_bulk_releases(flow.owner_id)) == 1

    for kind, mismatch in (
        ("inbox_remainder", items),
        ("restart", items[:1]),
    ):
        conflict = flow.bulk_raw(kind, mismatch, id=bulk_id)
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == {"reason": "id_conflict"}


def test_020_FR_011_a_bulk_release_replays_by_key(flow: FlowApi) -> None:
    seeds = _restart_seeds(flow)
    headers = flow.key()
    items = _items(seeds["floored"])
    first = flow.bulk_raw("restart", items, headers=headers)
    replay = flow.bulk_raw("restart", items, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    conflict = flow.bulk_raw("inbox_remainder", items, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"reason": "idempotency_conflict"}


def test_020_FR_045_bulk_ids_of_another_owner_answer_like_unknown_ids(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Task ids in a body never produce a 404: foreign equals unknown, byte for byte."""

    first, second = second_api_client
    owner = FlowApi(first, frozen_clock)
    other = FlowApi(second, frozen_clock)
    owner.activate_at(frozen_clock() - 30 * DAY)
    other.activate_at(frozen_clock() - 30 * DAY)
    theirs = owner.seed(
        title="Owner task", formulation_started_at=frozen_clock() - 40 * DAY
    )
    unknown = "task_0123456789ab"
    for kind in ("restart", "inbox_remainder"):
        foreign = other.bulk_raw(kind, [{"task_id": theirs.id, "expected_revision": 1}])
        missing = other.bulk_raw(kind, [{"task_id": unknown, "expected_revision": 1}])
        assert foreign.status_code == missing.status_code == 200
        assert _without_reference(
            foreign, theirs.id, foreign.json()["id"]
        ) == _without_reference(missing, unknown, missing.json()["id"])
    assert owner.stored(theirs.id).state == "next"

    release = owner.bulk("restart", _items(theirs))
    foreign_undo = other.undo_bulk_raw(release["id"])
    missing_id = new_id("bulk")
    unknown_undo = other.undo_bulk_raw(missing_id)
    assert foreign_undo.status_code == unknown_undo.status_code == 404
    assert foreign_undo.json()["detail"] == {
        "resource": "Review bulk release",
        "id": release["id"],
    }
    assert _without_reference(foreign_undo, release["id"]) == _without_reference(
        unknown_undo, missing_id
    )
    assert owner.stored(theirs.id).state == "someday"


def test_020_FR_030_a_bulk_body_holds_at_most_500_items(flow: FlowApi) -> None:
    items = [
        {"task_id": f"task_{index:012x}", "expected_revision": 1}
        for index in range(501)
    ]
    assert flow.bulk_raw("inbox_remainder", items).status_code == 422
    assert flow.bulk_raw("inbox_remainder", items[:500]).status_code == 200


def test_020_FR_042_bulk_releases_are_accepted_with_the_flag_off(
    flow: FlowApi,
) -> None:
    flow.flag("off")
    capture = flow.create("Capture")
    result = flow.bulk("inbox_remainder", _items(capture))
    assert flow.undo_bulk_raw(result["id"]).status_code == 200


def test_020_FR_011_lost_bulk_writes_are_repaired_by_their_replay(
    flow: FlowApi,
) -> None:
    """The ``bulk_release:`` and ``undo_bulk_release:`` reconcilers."""

    capture = flow.create("Capture")
    headers = flow.key()
    result = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers).json()
    repo = flow.container.task_repo
    released = flow.stored(capture["id"])
    with repo.command_lock(flow.owner_id):
        repo.save(released.model_copy(update={"state": "inbox", "revision": 1}))
        repo.delete_review_receipt(flow.owner_id, capture["id"], "someday")
        repo._review_execute(  # simulate the lost record row
            "Bulk release",
            "DELETE FROM review_bulk_releases WHERE owner_id = ? AND id = ?",
            (flow.owner_id, result["id"]),
        )
    replay = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers)
    assert replay.json() == result
    assert flow.stored(capture["id"]).state == "someday"
    assert repo.get_bulk_release(flow.owner_id, result["id"]) is not None
    assert repo.get_review_receipt(flow.owner_id, capture["id"], "someday") is not None

    undo_headers = flow.key()
    undone = flow.undo_bulk_raw(result["id"], headers=undo_headers).json()
    restored = flow.stored(capture["id"])
    record = repo.get_bulk_release(flow.owner_id, result["id"])
    assert record is not None
    with repo.command_lock(flow.owner_id):
        repo.save(restored.model_copy(update={"state": "someday", "revision": 2}))
        repo.save_bulk_release(
            record.model_copy(update={"undone_at": None, "undo_result": None})
        )
    again = flow.undo_bulk_raw(result["id"], headers=undo_headers)
    assert again.json() == undone
    assert flow.stored(capture["id"]).state == "inbox"
    record = repo.get_bulk_release(flow.owner_id, result["id"])
    assert record is not None and record.undone_at is not None


def _hidden_from_someday_for_30_days(flow: FlowApi, task_id: str) -> None:
    """A released task stays out of the Someday step until its receipt ends."""

    start = flow.clock()
    sid = flow.start(mode="full", replace_open=True)["id"]
    assert task_id not in flow.ids(flow.queue("someday", sid))
    flow.clock.set(start + 29 * DAY)
    assert task_id not in flow.ids(flow.queue("someday", sid))
    flow.clock.set(start + 31 * DAY)
    assert task_id in flow.ids(flow.queue("someday", sid))


def test_020_FR_032_a_release_interrupted_after_a_task_write_keeps_its_receipt(
    flow: FlowApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The receipt save fails after the task save; the retry leaves it hidden.

    The command runs in one owner-locked SQLite transaction, so the failure
    rolls the task and the record back and the retry applies the release
    whole.
    """

    capture = flow.create("Capture")
    headers = flow.key()
    repo = flow.container.task_repo
    real_save = repo.save_review_receipt

    def failing(receipt: rd.ReviewReceiptDocument) -> None:
        raise RuntimeError("storage stopped")

    monkeypatch.setattr(repo, "save_review_receipt", failing)
    with allure.step("The receipt write fails after the task write"):
        try:
            failed = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers)
        except RuntimeError:
            failed = None
    assert failed is None or failed.status_code >= 500
    monkeypatch.setattr(repo, "save_review_receipt", real_save)
    with allure.step("The same request is retried with its key"):
        retry = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers)
    assert retry.status_code == 200, retry.text
    receipt = repo.get_review_receipt(flow.owner_id, capture["id"], "someday")
    assert receipt is not None and receipt.bulk_id == retry.json()["id"]
    _hidden_from_someday_for_30_days(flow, capture["id"])


def test_020_FR_011_020_FR_032_a_release_replay_restores_a_receipt_it_lost(
    flow: FlowApi,
) -> None:
    """The record and the task survived, the receipt and the release row not.

    The task is already at its released revision, so it is not written again,
    but its receipt is recreated before the release row is saved.
    """

    capture = flow.create("Capture")
    headers = flow.key()
    result = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers).json()
    repo = flow.container.task_repo
    released = flow.stored(capture["id"])
    with repo.command_lock(flow.owner_id):
        repo.delete_review_receipt(flow.owner_id, capture["id"], "someday")
        repo._review_execute(  # simulate the lost rows
            "Bulk release",
            "DELETE FROM review_bulk_releases WHERE owner_id = ? AND id = ?",
            (flow.owner_id, result["id"]),
        )
    with allure.step("The release is retried with its key"):
        replay = flow.bulk_raw("inbox_remainder", _items(capture), headers=headers)
    assert replay.json() == result
    assert flow.stored(capture["id"]).revision == released.revision
    receipt = repo.get_review_receipt(flow.owner_id, capture["id"], "someday")
    assert receipt is not None and receipt.bulk_id == result["id"]
    assert repo.get_bulk_release(flow.owner_id, result["id"]) is not None
    _hidden_from_someday_for_30_days(flow, capture["id"])


def test_020_FR_011_a_release_undo_replay_drops_a_receipt_it_left(
    flow: FlowApi,
) -> None:
    capture = flow.create("Capture")
    result = flow.bulk("inbox_remainder", _items(capture))
    repo = flow.container.task_repo
    receipt = repo.get_review_receipt(flow.owner_id, capture["id"], "someday")
    release = repo.get_bulk_release(flow.owner_id, result["id"])
    assert receipt is not None and release is not None
    headers = flow.key()
    undone = flow.undo_bulk_raw(result["id"], headers=headers).json()
    with repo.command_lock(flow.owner_id):
        repo.save_review_receipt(receipt)
        repo.save_bulk_release(release)
    again = flow.undo_bulk_raw(result["id"], headers=headers)
    assert again.json() == undone
    assert flow.stored(capture["id"]).state == "inbox"
    assert repo.get_review_receipt(flow.owner_id, capture["id"], "someday") is None
    stored = repo.get_bulk_release(flow.owner_id, result["id"])
    assert stored is not None and stored.undone_at is not None


def test_020_FR_011_020_FR_029_a_decision_replay_restores_rows_it_lost(
    flow: FlowApi,
) -> None:
    """Task written, decision row, receipt and run counts lost: all restored."""

    now = flow.clock()
    asking = flow.seed(title="Asks", formulation_started_at=now - 15 * DAY)
    sid = flow.start()["id"]
    headers = flow.key()
    card = flow.task(asking.id)
    response = flow.decide_raw(card, "someday", session_id=sid, headers=headers)
    assert response.status_code == 200, response.text
    repo = flow.container.task_repo
    decision_id = response.json()["decision"]["id"]
    decided = flow.stored(asking.id)
    counted = flow.stored_session(sid)
    with repo.command_lock(flow.owner_id):
        repo.delete_review_decision(flow.owner_id, decision_id)
        repo.delete_review_receipt(flow.owner_id, asking.id, "someday")
        repo.save_review_session(
            counted.model_copy(
                update={"counts": rd.SessionCountsDocument(), "revision": 1}
            )
        )
    with allure.step("The decision is retried with its key"):
        replay = flow.decide_raw(card, "someday", session_id=sid, headers=headers)
    assert replay.status_code == 200, replay.text
    assert flow.stored(asking.id).revision == decided.revision
    assert repo.get_review_decision(flow.owner_id, decision_id) is not None
    receipt = repo.get_review_receipt(flow.owner_id, asking.id, "someday")
    assert receipt is not None and receipt.decision_id == decision_id
    assert flow.stored_session(sid).counts == counted.counts


def test_020_FR_048_an_undo_replay_finishes_the_rows_it_left(flow: FlowApi) -> None:
    """Task restored, decision row and receipt left: both removed on replay."""

    now = flow.clock()
    asking = flow.seed(title="Asks", formulation_started_at=now - 15 * DAY)
    decided = flow.decide(flow.task(asking.id), "someday")
    repo = flow.container.task_repo
    decision_id = decided["decision"]["id"]
    decision = repo.get_review_decision(flow.owner_id, decision_id)
    receipt = repo.get_review_receipt(flow.owner_id, asking.id, "someday")
    assert decision is not None and receipt is not None
    headers = flow.key()
    undo = flow.undo_raw(decision_id, decided["task"]["revision"], headers=headers)
    assert undo.status_code == 200, undo.text
    restored = flow.stored(asking.id)
    with repo.command_lock(flow.owner_id):
        repo.save_review_decision(decision)
        repo.save_review_receipt(receipt)
    with allure.step("The Undo is retried with its key"):
        again = flow.undo_raw(decision_id, decided["task"]["revision"], headers=headers)
    assert again.status_code == 200, again.text
    assert flow.stored(asking.id).revision == restored.revision
    assert repo.get_review_decision(flow.owner_id, decision_id) is None
    assert repo.get_review_receipt(flow.owner_id, asking.id, "someday") is None


def test_020_FR_013_an_auto_park_replay_restores_a_park_row_it_lost(
    flow: FlowApi,
) -> None:
    """Task parked, park acknowledgement row lost: recreated on replay (E6)."""

    task = flow.create("Call Bob", state="next")
    flow.clock.advance(days=21)
    keep_alive(flow.container)
    task = flow.task(task["id"])
    headers = flow.key()
    path = f"/api/tasks/{task['id']}/auto-park"
    body = {"formulation_id": task["formulation"]["id"]}
    first = flow.client.post(path, json=body, headers=headers)
    assert first.status_code == 200, first.text
    parked = flow.stored(task["id"])
    assert parked.state == "someday"
    repo = flow.container.task_repo
    with repo.command_lock(flow.owner_id):
        repo._review_execute(  # simulate the lost row
            "Park",
            "DELETE FROM review_park_acks WHERE owner_id = ? AND task_id = ?",
            (flow.owner_id, task["id"]),
        )
    with allure.step("The park is retried with its key"):
        replay = flow.client.post(path, json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert flow.stored(task["id"]).revision == parked.revision
    ack = repo.get_park_ack(flow.owner_id, task["id"], body["formulation_id"])
    assert ack is not None and ack.seen_at is None


def test_020_FR_011_flow_reconcilers_leave_an_unreadable_record_alone(
    flow: FlowApi, caplog: pytest.LogCaptureFixture
) -> None:
    """A stray record of a flow prefix is skipped by type, never by its text."""

    repo = flow.container.task_repo
    for command in (
        "bulk_release:x",
        "undo_bulk_release:x",
        "review_session:start",
    ):
        with repo.command_lock(flow.owner_id):
            repo.save_idempotency(
                owner_id=flow.owner_id,
                record=IdempotencyRecord(
                    key=f"stray-{command}",
                    command=command,
                    request_hash="0" * 64,
                    resource_id="x",
                    response_body={"SENTINEL": "SENTINEL-STRAY-TEXT"},
                    created_at=flow.clock(),
                ),
            )
            flow.container.review_service._reconcile_idempotent_result(
                owner_id=flow.owner_id, key=f"stray-{command}"
            )
    assert "SENTINEL-STRAY-TEXT" not in caplog.text
    assert flow.sessions() == []


def test_020_FR_044_flow_logs_carry_ids_and_counts_only(
    flow: FlowApi, caplog: pytest.LogCaptureFixture
) -> None:
    capture = flow.create("SENTINEL-TITLE-TEXT")
    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        sid = flow.start()["id"]
        flow.progress(sid, inbox_processed_delta=1)
        flow.finish(sid, clear_start="yes")
        result = flow.bulk("inbox_remainder", _items(capture))
        flow.undo_bulk_raw(result["id"])
    text = caplog.text
    assert f"review_run owner_id={flow.owner_id} session_id={sid}" in text
    assert "status=completed" in text
    assert "review_bulk_release" in text
    assert "SENTINEL-TITLE-TEXT" not in text


def test_020_FR_029_a_run_starts_at_the_server_instant(flow: FlowApi) -> None:
    """Clocks start where the server applies the request (formulation-clock §3)."""

    session = flow.start()
    assert from_isoformat(session["started_at"]) == flow.clock()
    assert from_isoformat(session["last_activity_at"]) == flow.clock()
    assert session["ended_at"] is None
