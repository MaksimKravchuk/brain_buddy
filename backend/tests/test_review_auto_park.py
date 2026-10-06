"""Spec 020 US2: activation, the review sweep, device parks, park acknowledgements.

- Activation (FR-016, FR-051): the first ``POST /review/explainer/acknowledge``
  clamps every Next clock without bumping a revision; later ones change nothing.
- The sweep (FR-012 – FR-014, SC-006, http §9): driven by
  ``_run_review_maintenance_sweep(container)`` under ``frozen_clock``; a park is
  always preceded by a visible 24-hour "moves to Someday tomorrow" marker.
- Device parks and the yield rule (FR-013, http §3 – §4).
- Park acknowledgements and returning a parked task (FR-015).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.container import Container
from app.modules.tasks import formulation as rules
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import IdempotencyRecord, TaskDocument
from app.modules.tasks.review_service import ReviewService

from .conftest import FrozenClock
from .test_review_decisions_api import ReviewApi, iso, new_id, norm

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
ACK = "/api/review/explainer/acknowledge"


def sweep(container: Container, *, continuous: bool = True) -> Any:
    """One sweep run; ``continuous`` models the 60 s loop having kept running.

    Tests jump the clock by days; without this, every jump would be a sweep
    gap and the gap floor (SC-006) would hold every park back 7 days, which
    is exactly what ``continuous=False`` tests.
    """

    if continuous:
        keep_alive(container)
    return app_main._run_review_maintenance_sweep(container)


def keep_alive(container: Container) -> None:
    """Record an effective sweep a minute ago for every activated owner."""

    repo = container.task_repo
    just_now = container.task_service.clock() - timedelta(minutes=1)
    for settings in repo.list_review_settings():
        if settings.activated_at is not None:
            repo.save_review_settings(
                settings.model_copy(update={"last_effective_sweep_at": just_now})
            )


def acknowledge(api: ReviewApi, **body: Any) -> Any:
    return api.client.post(ACK, json=body, headers=api.key())


def state(api: ReviewApi) -> dict[str, Any]:
    response = api.client.get("/api/review/state")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def seed_old_next_task(
    api: ReviewApi, *, age: timedelta, clock: bool = True, title: str = "Old task"
) -> TaskDocument:
    """A Next task created ``age`` ago (before activation), straight in storage."""

    created = api.clock() - age
    task = TaskDocument(
        id=f"task_{uuid.uuid4().hex[:12]}",
        owner_id=api.owner_id,
        title=title,
        state="next",
        order_key=0,
        created_at=created,
        updated_at=created,
        revision=3,
        formulation_id=f"form_{uuid.uuid4().hex[:12]}" if clock else None,
        formulation_started_at=created if clock else None,
    )
    api.container.task_repo.save(task)
    return task


@pytest.fixture
def api(api_client: TestClient, frozen_clock: FrozenClock) -> ReviewApi:
    review_api = ReviewApi(api_client, frozen_clock)
    review_api.flag("on")
    return review_api


# ===================================================================== T077
def test_020_FR_016_first_acknowledgement_activates_and_clamps_without_revisions(
    api: ReviewApi, caplog: pytest.LogCaptureFixture
) -> None:
    """``activated_at`` = server now; clamp + 14-day floor; no revision moves."""

    old = seed_old_next_task(api, age=60 * DAY)
    missing = seed_old_next_task(api, age=40 * DAY, clock=False, title="No clock")
    waiting = api.create("Quote", state="waiting", waiting_for="Ann")
    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        response = acknowledge(api, time_zone="Europe/Berlin")
    assert response.status_code == 200, response.text
    body = response.json()
    now = api.clock()
    assert body["explainer_seen"] is True
    assert norm(body["settings"]["activated_at"]) == iso(now)
    assert body["settings"]["time_zone"] == "Europe/Berlin"
    assert norm(body["grace_until"]) == iso(now + 14 * DAY)
    assert body["counts"] == {"asks_for_decision": 0, "moves_tomorrow": 0}

    clamped = api.stored(old.id)
    assert clamped.formulation_id == old.formulation_id
    assert clamped.formulation_started_at == now
    assert clamped.formulation_park_floor_at == now + 14 * DAY
    assert (clamped.revision, clamped.updated_at) == (old.revision, old.updated_at)
    started = api.stored(missing.id)
    assert started.formulation_id is not None
    assert started.formulation_started_at == now
    assert started.revision == missing.revision
    assert api.stored(waiting["id"]).formulation_id is None
    assert any("review_activated" in r.getMessage() for r in caplog.records)


def test_020_FR_051_later_acknowledgements_change_nothing_including_the_zone(
    api: ReviewApi,
) -> None:
    """First wins: a later or duplicate acknowledgement is a no-op."""

    acknowledge(api, time_zone="Europe/Berlin")
    first = state(api)["settings"]
    task = api.create(state="next")
    api.clock.advance(days=3)
    again = acknowledge(api, time_zone="Pacific/Honolulu")
    assert again.status_code == 200
    assert again.json()["settings"] == first
    assert (
        api.task(task["id"])["formulation"]["started_at"]
        == task["formulation"]["started_at"]
    )


def test_020_FR_051_acknowledgement_rejects_a_non_iana_zone(api: ReviewApi) -> None:
    response = acknowledge(api, time_zone="Mars/Olympus")
    assert response.status_code == 400
    assert response.json()["detail"] == {"reason": "invalid_time_zone"}
    assert state(api)["explainer_seen"] is False


def test_020_FR_018_acknowledgement_with_the_flag_off_still_activates(
    api: ReviewApi,
) -> None:
    """Not gated: an acknowledgement queued before a rollback is never lost."""

    api.flag("off")
    response = acknowledge(api)
    assert response.status_code == 200, response.text
    assert response.json()["explainer_seen"] is True


def test_020_FR_014_no_derived_instants_and_no_park_before_activation(
    api: ReviewApi,
) -> None:
    """Flag on but never acknowledged: 30 days of sweeps park nothing."""

    old = seed_old_next_task(api, age=60 * DAY)
    for _ in range(30):
        api.clock.advance(days=1)
        sweep(api.container)
    assert api.stored(old.id).state == "next"
    assert api.task(old.id)["formulation"]["ask_at"] is None
    acknowledge(api)
    assert state(api)["counts"]["asks_for_decision"] == 0  # none asks on day one
    api.clock.advance(days=13, hours=23)
    sweep(api.container)
    assert api.stored(old.id).state == "next"
    assert state(api)["counts"]["asks_for_decision"] == 0
    api.clock.advance(hours=2)
    sweep(api.container)
    assert api.stored(old.id).state == "next"
    assert state(api)["counts"]["asks_for_decision"] == 1


def test_020_FR_051_acknowledgement_replays_and_a_lost_activation_repairs(
    api: ReviewApi,
) -> None:
    headers = api.key()
    first = api.client.post(ACK, json={"time_zone": "Europe/Berlin"}, headers=headers)
    with api.container.task_repo.command_lock(api.owner_id):
        conn = api.container.task_repo._thread_state.conn  # type: ignore[attr-defined]
        conn.execute("DELETE FROM review_settings WHERE owner_id = ?", (api.owner_id,))
    replay = api.client.post(ACK, json={"time_zone": "Europe/Berlin"}, headers=headers)
    assert replay.status_code == 200
    assert (
        replay.json()["settings"]["activated_at"]
        == first.json()["settings"]["activated_at"]
    )


# ===================================================================== T079
def _activated(api: ReviewApi, **body: Any) -> datetime:
    assert acknowledge(api, **body).status_code == 200
    return api.clock()


def test_020_FR_012_sweep_parks_a_due_formulation_and_keeps_everything_else(
    api: ReviewApi, caplog: pytest.LogCaptureFixture
) -> None:
    """Due at T + 7; project, tags, notes, due date and priority are kept."""

    _activated(api)
    project = api.client.post("/api/projects", json={"name": "Flat"}, headers=api.key())
    tag = api.client.post("/api/tags", json={"name": "home"}, headers=api.key())
    task = api.create(
        state="next",
        details="Tiles from Ann",
        project_id=project.json()["id"],
        tag_ids=[tag.json()["id"]],
        priority="high",
    )
    api.clock.advance(days=20, hours=23)
    sweep(api.container)
    assert api.stored(task["id"]).state == "next"

    api.clock.advance(hours=1)
    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        result = sweep(api.container)
    parked = api.stored(task["id"])
    assert parked.state == "someday"
    assert parked.revision == task["revision"] + 1
    assert (parked.details, parked.project_id, parked.tag_ids, parked.priority) == (
        "Tiles from Ann",
        project.json()["id"],
        [tag.json()["id"]],
        "high",
    )
    assert parked.parked is not None
    assert parked.parked.formulation_id == task["formulation"]["id"]
    assert parked.parked.from_revision == task["revision"]
    assert (
        parked.parked.clock_before.started_at
        == api.stored(task["id"]).parked.clock_before.started_at
    )
    assert norm(api.task(task["id"])["parked"]["at"]) == iso(api.clock())
    ack = api.container.task_repo.get_park_ack(
        api.owner_id, task["id"], task["formulation"]["id"]
    )
    assert ack is not None
    assert (ack.parked_at, ack.from_revision, ack.source) == (
        api.clock(),
        task["revision"],
        "sweep",
    )
    assert result.parked == 1
    lines = [r.getMessage() for r in caplog.records]
    assert any("review_auto_park applied=True source=sweep" in line for line in lines)
    assert any(line.startswith("review_sweep owners=1 parked=1") for line in lines)


def test_020_FR_013_a_second_park_of_the_same_formulation_is_a_no_op(
    api: ReviewApi,
) -> None:
    _activated(api)
    task = api.create(state="next")
    api.clock.advance(days=21)
    sweep(api.container)
    parked = api.stored(task["id"])
    api.clock.advance(hours=1)
    sweep(api.container)
    assert api.stored(task["id"]) == parked
    assert len(api.container.task_repo.list_park_acks(api.owner_id)) == 1


@pytest.mark.parametrize("change", ["reformulate", "move", "extend"])
def test_020_FR_013_sweep_skips_a_formulation_changed_after_its_park_became_due(
    api: ReviewApi, change: str
) -> None:
    _activated(api)
    task = api.create("Call Bob", state="next")
    api.clock.advance(days=22)
    current = api.task(task["id"])
    if change == "reformulate":
        api.patch(current, title="Email Bob the quote")
    elif change == "move":
        api.move(current, "waiting", waiting_for="Bob")
    else:
        api.decide(current, "extend", reason="Bob is away")
    sweep(api.container)
    assert api.stored(task["id"]).parked is None


def test_020_FR_014_sweep_repairs_a_missing_clock_with_a_14_day_floor(
    api: ReviewApi,
) -> None:
    """Old-client save after activation: clock starts now, floor now + 14 d."""

    _activated(api)
    task = seed_old_next_task(api, age=5 * DAY, clock=False)
    api.clock.advance(hours=2)
    result = sweep(api.container)
    repaired = api.stored(task.id)
    assert repaired.formulation_started_at == api.clock()
    assert repaired.formulation_park_floor_at == api.clock() + 14 * DAY
    assert repaired.revision == task.revision
    assert result.repaired == 1


def test_020_SC_006_every_park_follows_a_24_hour_marker_and_reaches_while_away(
    api: ReviewApi,
) -> None:
    """Hourly sweeps through activation, extension, threshold, gap and zone floors.

    For every task the sweep parks, each hourly observation in the 24 hours
    before the park classified it ``moves_tomorrow`` (the visible marker), and
    the park is listed in ``unseen_parks``.
    """

    old = seed_old_next_task(api, age=60 * DAY, title="Activation clamp")
    start = _activated(api, time_zone="Europe/Berlin")
    plain = api.create("Plain", state="next")
    dated = api.create("Dated", state="next", due_date="2026-10-25")
    extended = api.create("Extended", state="next")
    ids = {old.id, plain["id"], dated["id"], extended["id"]}
    marker_since: dict[str, datetime | None] = dict.fromkeys(ids)
    parked_at: dict[str, datetime] = {}

    def observe() -> None:
        now = api.clock()
        settings = api.container.review_service.settings_for(api.owner_id)
        for task_id in ids - set(parked_at):
            stored = api.stored(task_id)
            if stored.state != "next":
                parked_at[task_id] = now
                assert stored.parked is not None
                since = marker_since[task_id]
                assert since is not None, task_id
                assert now - since >= 24 * HOUR, (task_id, now, since)
                continue
            klass = rules.classify(
                rd.task_clock(stored), settings.clock_settings(), now
            )
            if klass in ("moves_tomorrow", "park_due"):
                marker_since[task_id] = marker_since[task_id] or now
            else:
                marker_since[task_id] = None

    with allure.step("Run hourly sweeps for 45 days with every floor event"):
        for hour in range(45 * 24):
            if hour == 15 * 24:
                api.decide(api.task(extended["id"]), "extend", reason="Away")
            if hour == 18 * 24:
                settings = state(api)["settings"]
                api.client.put(
                    "/api/review/settings",
                    json={
                        "threshold_days": 7,
                        "expected_revision": settings["revision"],
                    },
                    headers=api.key(),
                )
            if hour == 26 * 24:
                api.flag("off")
            if hour == 28 * 24:
                api.flag("on")
            if hour == 30 * 24:
                settings = state(api)["settings"]
                api.client.put(
                    "/api/review/settings",
                    json={
                        "time_zone": "Asia/Tokyo",
                        "expected_revision": settings["revision"],
                    },
                    headers=api.key(),
                )
            observe()
            sweep(api.container, continuous=False)
            observe()
            api.clock.advance(HOUR)

    assert set(parked_at) == ids
    assert all(at >= start + 14 * DAY for at in parked_at.values())  # activation grace
    assert parked_at[plain["id"]] >= start + 25 * DAY  # threshold change floor
    assert not any(
        start + 28 * DAY <= at < start + 35 * DAY for at in parked_at.values()
    )
    assert parked_at[dated["id"]] >= start + 37 * DAY  # zone-change floor
    unseen = {park["task_id"] for park in state(api)["unseen_parks"]}
    assert unseen == ids


def test_020_FR_043_retention_runs_with_the_flag_off(api: ReviewApi) -> None:
    """Undo snapshots after 7 days, bulk clocks after 7, usage rows after 35."""

    _activated(api)
    task = api.create(state="next")
    decision = api.decide(task, "complete")
    repo = api.container.task_repo
    repo.save_bulk_release(
        rd.ReviewBulkReleaseDocument(
            id=new_id("bulk"),
            owner_id=api.owner_id,
            kind="restart",
            created_at=api.clock(),
            released=[
                rd.BulkReleasedItemDocument(
                    task_id=task["id"],
                    revision_after=5,
                    previous_state="next",
                    clock_before=rd.ReleasedClockDocument(
                        formulation_id=task["formulation"]["id"],
                        started_at=api.clock(),
                        extension_reason="Away",
                    ),
                )
            ],
        )
    )
    api.flag("off")
    api.clock.advance(days=6)
    sweep(api.container)
    stored = repo.get_review_decision(api.owner_id, decision["decision"]["id"])
    assert stored is not None and stored.undo is not None
    api.clock.advance(days=2)
    for days_ago in (36, 34):
        repo.save_navigator_usage(
            rd.NavigatorUsageDocument(
                owner_id=api.owner_id,
                day=(api.clock() - days_ago * DAY).date(),
                calls=1,
            )
        )
    result = sweep(api.container)
    stored = repo.get_review_decision(api.owner_id, decision["decision"]["id"])
    assert stored is not None and stored.undo is None
    assert repo.list_bulk_releases(api.owner_id)[0].released[0].clock_before is None
    assert [u.day for u in repo.list_navigator_usage(api.owner_id)] == [
        (api.clock() - 34 * DAY).date()
    ]
    assert result.snapshots_nulled == 2


def test_020_FR_014_one_owner_failure_is_isolated_and_logged_by_type(
    second_api_client: tuple[TestClient, TestClient],
    frozen_clock: FrozenClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first, second = second_api_client
    broken = ReviewApi(first, frozen_clock)
    healthy = ReviewApi(second, frozen_clock)
    broken.flag("on")
    _activated(broken)
    _activated(healthy)
    bad = broken.create(state="next")
    good = healthy.create(state="next")
    container = broken.container

    def failing(owner_id: str) -> list[TaskDocument]:
        if owner_id == broken.owner_id:
            raise RuntimeError("storage exploded with SENTINEL-OWNER-TEXT")
        return original(owner_id)

    original = container.task_repo.list_next_tasks
    container.task_repo.list_next_tasks = failing  # type: ignore[method-assign]
    frozen_clock.advance(days=22)
    with caplog.at_level(logging.INFO):
        sweep(container)
    assert healthy.stored(good["id"]).state == "someday"
    assert broken.stored(bad["id"]).state == "next"
    failures = [
        r.getMessage()
        for r in caplog.records
        if "review_sweep_owner_failed" in r.getMessage()
    ]
    assert failures == [
        f"review_sweep_owner_failed owner_id={broken.owner_id} error=RuntimeError "
        "reason=exposure"
    ]
    assert "SENTINEL-OWNER-TEXT" not in caplog.text


def test_020_FR_014_the_sweep_resolves_a_user_per_owner_for_the_flag(
    api: ReviewApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``is_effective`` gets that owner's ``User``; a missing user is skipped."""

    _activated(api)
    task = api.create(state="next")
    api.clock.advance(days=22)
    service = api.container.feature_flag_service
    seen: list[str] = []
    real = service.is_effective

    def spy(name: str, user: Any) -> bool:
        seen.append(f"{name}:{user.id}")
        return real(name, user)

    monkeypatch.setattr(service, "is_effective", spy)
    users = api.container.user_repo
    monkeypatch.setattr(users, "get_by_id", lambda owner_id: None)
    sweep(api.container)
    assert api.stored(task["id"]).state == "next"
    monkeypatch.undo()
    monkeypatch.setattr(service, "is_effective", spy)
    sweep(api.container)
    assert f"weekly_review:{api.owner_id}" in seen
    assert api.stored(task["id"]).state == "someday"


def test_020_FR_014_privacy_sweep_runs_the_review_sweep_and_keeps_its_shape(
    api: ReviewApi,
) -> None:
    """``_run_privacy_maintenance_sweep`` still returns its 3-tuple."""

    _activated(api)
    task = api.create(state="next")
    api.clock.advance(days=22)
    keep_alive(api.container)
    result = app_main._run_privacy_maintenance_sweep(api.container)
    assert isinstance(result, tuple) and len(result) == 3
    assert api.stored(task["id"]).state == "someday"


def test_020_FR_014_a_failing_review_sweep_never_stops_the_privacy_sweep(
    api: ReviewApi, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom() -> None:
        raise RuntimeError("SENTINEL-SWEEP-TEXT")

    monkeypatch.setattr(api.container.review_service, "run_maintenance_sweep", boom)
    with caplog.at_level(logging.ERROR):
        assert len(app_main._run_privacy_maintenance_sweep(api.container)) == 3
    assert "review_sweep_failed error=RuntimeError" in caplog.text
    assert "SENTINEL-SWEEP-TEXT" not in caplog.text


# ===================================================================== T081
def _due(api: ReviewApi, title: str = "Call Bob") -> dict[str, Any]:
    """A task 21 days into a 14-day threshold, the sweep loop having kept running.

    Without ``keep_alive`` the jump is a sweep gap, and a device park would
    meet the gap floor first (SC-006), as the gap tests below show.
    """

    task = api.create(title, state="next")
    api.clock.advance(days=21)
    keep_alive(api.container)
    return api.task(task["id"])


def _device_park(api: ReviewApi, task: dict[str, Any]) -> Any:
    return api.client.post(
        f"/api/tasks/{task['id']}/auto-park",
        json={"formulation_id": task["formulation"]["id"]},
        headers=api.key(),
    )


def test_020_FR_013_device_park_applies_once_and_is_never_a_conflict(
    api: ReviewApi,
) -> None:
    """Two devices: one park, both answered 200."""

    _activated(api)
    task = _due(api)
    first = _device_park(api, task)
    second = _device_park(api, task)
    assert first.status_code == second.status_code == 200
    assert first.json()["applied"] is True
    assert first.json()["task"]["state"] == "someday"
    assert first.json()["task"]["parked"]["formulation_id"] == task["formulation"]["id"]
    assert second.json()["applied"] is False
    ack = api.container.task_repo.get_park_ack(
        api.owner_id, task["id"], task["formulation"]["id"]
    )
    assert ack is not None and ack.source == "device"


def test_020_FR_013_device_park_is_applied_false_unless_the_server_agrees(
    api: ReviewApi,
) -> None:
    """Flag off, not activated, not due, or another formulation: ``applied: false``."""

    not_activated = api.create(state="next")
    api.clock.advance(days=30)
    assert _device_park(api, api.task(not_activated["id"])).json()["applied"] is False

    _activated(api)
    fresh = api.create(state="next")
    assert _device_park(api, fresh).json()["applied"] is False
    due = _due(api)
    stale = {**due, "formulation": {**due["formulation"], "id": new_id("form")}}
    assert _device_park(api, stale).json()["applied"] is False
    api.flag("off")
    off = _device_park(api, due)
    assert off.status_code == 200
    assert off.json() == {"applied": False, "task": api.task(due["id"])}
    assert api.stored(due["id"]).state == "next"


def test_020_SC_006_a_device_park_after_a_sweep_gap_applies_the_gap_floor_first(
    api: ReviewApi,
) -> None:
    """Flag off for 5 days, then a device park lands before the first sweep.

    The device path applies the same sweep-gap floor under the owner lock as
    the sweep does, so the park waits behind a visible "moves to Someday
    tomorrow" marker instead of landing at once (SC-006).
    """

    now = api.clock()
    api.activate_at(now - 60 * DAY, last_effective_sweep_at=now - 5 * DAY)
    task = seed_old_next_task(api, age=40 * DAY)
    with allure.step("Device asks to park a task the gap made due"):
        response = api.client.post(
            f"/api/tasks/{task.id}/auto-park",
            json={"formulation_id": task.formulation_id},
            headers=api.key(),
        )
    assert response.status_code == 200, response.text
    assert response.json()["applied"] is False
    assert response.json()["task"]["state"] == "next"
    assert norm(response.json()["task"]["formulation"]["park_due_at"]) == iso(
        now + 7 * DAY
    )
    settings = api.container.review_service.settings_for(api.owner_id)
    assert settings.owner_park_floor_at == now + 7 * DAY
    assert settings.last_effective_sweep_at == now
    assert settings.revision == 1

    with allure.step("The next sweep finds no gap and parks nothing yet"):
        api.clock.advance(minutes=1)
        result = app_main._run_review_maintenance_sweep(api.container)
    assert (result.gap_floors, result.parked) == (0, 0)
    assert api.container.review_service.settings_for(
        api.owner_id
    ).owner_park_floor_at == (now + 7 * DAY)


def test_020_SC_006_a_device_park_without_a_gap_leaves_the_owner_floor_alone(
    api: ReviewApi,
) -> None:
    """A sweep ran a minute ago: no floor, the due task parks at once."""

    _activated(api)
    task = _due(api)
    keep_alive(api.container)
    assert _device_park(api, task).json()["applied"] is True
    settings = api.container.review_service.settings_for(api.owner_id)
    assert settings.owner_park_floor_at is None
    assert settings.last_effective_sweep_at == api.clock()


def _park_with_sweep(api: ReviewApi) -> tuple[dict[str, Any], dict[str, Any]]:
    """A due task parked by the sweep: (the task before, the parked task)."""

    _activated(api)
    before = _due(api)
    decided_at = api.clock() - HOUR
    sweep(api.container)
    parked = api.task(before["id"])
    assert parked["state"] == "someday"
    return {**before, "decided_at": decided_at}, parked


def test_020_FR_013_an_offline_decision_before_the_park_wins_the_yield(
    api: ReviewApi,
) -> None:
    """Clock restored from ``clock_before``, decision applied, ``yielded`` true."""

    before, parked = _park_with_sweep(api)
    result = api.decide(
        before,
        "someday",
        client_decided_at=iso(before["decided_at"]),
    )
    assert result["decision"]["yielded_auto_park"] is True
    assert result["task"]["state"] == "someday"
    assert result["task"]["parked"] is None
    assert result["receipt"]["kind"] == "someday"
    assert api.stored(before["id"]).consecutive_stalled_formulations == 1


def test_020_FR_013_an_offline_extend_before_the_park_is_accepted(
    api: ReviewApi,
) -> None:
    before, parked = _park_with_sweep(api)
    result = api.decide(
        before, "extend", reason="Away", client_decided_at=iso(before["decided_at"])
    )
    formulation = result["task"]["formulation"]
    assert result["task"]["state"] == "next"
    assert formulation["id"] == before["formulation"]["id"]
    assert formulation["started_at"] == before["formulation"]["started_at"]
    assert formulation["extension_reason"] == "Away"
    assert (
        formulation["consecutive_stalled"]
        == before["formulation"]["consecutive_stalled"]
    )


def test_020_SC_007_notes_queued_before_a_decision_survive_the_yield(
    api: ReviewApi,
) -> None:
    """Offline notes edit, offline card decision, server park between them."""

    before, parked = _park_with_sweep(api)
    stale_notes = api.client.patch(
        f"/api/tasks/{before['id']}",
        json={
            "details": "Ann prefers mornings",
            "expected_revision": before["revision"],
        },
        headers=api.key(),
    )
    assert stale_notes.status_code == 409
    replayed = api.patch(parked, details="Ann prefers mornings")
    assert replayed["state"] == "someday" and replayed["parked"] is not None
    result = api.decide(
        before,
        "waiting",
        waiting_for="Ann",
        client_decided_at=iso(before["decided_at"]),
    )
    assert result["decision"]["yielded_auto_park"] is True
    assert result["task"]["details"] == "Ann prefers mornings"
    assert result["task"]["state"] == "waiting"


def test_020_FR_013_a_decision_made_after_the_park_does_not_yield(
    api: ReviewApi,
) -> None:
    before, parked = _park_with_sweep(api)
    late = api.decide_raw(before, "someday", client_decided_at=iso(api.clock() + HOUR))
    assert late.status_code == 409
    assert api.task(before["id"])["parked"] is not None


def test_020_FR_013_yield_then_cosmetic_save_is_parked_again_and_shown_again(
    api: ReviewApi,
) -> None:
    """New ``from_revision``, new key; the E6 row is reset so it shows again."""

    before, parked = _park_with_sweep(api)
    acked = api.client.post(
        "/api/review/parks/acknowledge",
        json={
            "items": [
                {"task_id": before["id"], "formulation_id": before["formulation"]["id"]}
            ]
        },
        headers=api.key(),
    )
    assert acked.status_code == 204
    result = api.decide(
        before,
        "reformulate",
        title="call bob.",
        client_decided_at=iso(before["decided_at"]),
    )
    assert result["decision"]["substantive"] is False
    assert result["task"]["state"] == "next"
    api.clock.advance(minutes=1)
    sweep(api.container)
    again = api.stored(before["id"])
    assert again.state == "someday"
    assert again.parked is not None
    assert again.parked.from_revision == result["task"]["revision"]
    ack = api.container.task_repo.get_park_ack(
        api.owner_id, before["id"], before["formulation"]["id"]
    )
    assert ack is not None
    assert ack.from_revision == result["task"]["revision"]
    assert ack.seen_at is None and ack.returned_at is None
    assert [p["task_id"] for p in state(api)["unseen_parks"]] == [before["id"]]


def test_020_FR_048_undo_of_a_yielded_decision_returns_to_next_and_parks_again(
    api: ReviewApi,
) -> None:
    """The snapshot is taken after the yield reversal (formulation-clock §3)."""

    before, parked = _park_with_sweep(api)
    result = api.decide(before, "complete", client_decided_at=iso(before["decided_at"]))
    undone = api.undo_raw(result["decision"]["id"], result["task"]["revision"])
    assert undone.status_code == 200, undone.text
    task = undone.json()["task"]
    assert task["state"] == "next" and task["parked"] is None
    assert task["formulation"]["id"] == before["formulation"]["id"]
    sweep(api.container)
    assert api.stored(before["id"]).state == "someday"


# ===================================================================== T083
def test_020_FR_015_unseen_parks_and_their_acknowledgement(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> None:
    """Idempotent; unknown and foreign ids are ignored identically."""

    first, second = second_api_client
    owner = ReviewApi(first, frozen_clock)
    other = ReviewApi(second, frozen_clock)
    owner.flag("on")
    _activated(owner)
    _activated(other)
    task = owner.create(state="next")
    frozen_clock.advance(days=21)
    sweep(owner.container)
    unseen = state(owner)["unseen_parks"]
    assert [p["task_id"] for p in unseen] == [task["id"]]
    assert norm(unseen[0]["parked_at"]) == iso(frozen_clock())

    item = {"task_id": task["id"], "formulation_id": task["formulation"]["id"]}
    foreign = other.client.post(
        "/api/review/parks/acknowledge", json={"items": [item]}, headers=other.key()
    )
    unknown = other.client.post(
        "/api/review/parks/acknowledge",
        json={
            "items": [
                {"task_id": "task_000000000000", "formulation_id": "form_000000000000"}
            ]
        },
        headers=other.key(),
    )
    assert foreign.status_code == unknown.status_code == 204
    assert foreign.content == unknown.content == b""
    assert len(state(owner)["unseen_parks"]) == 1

    for _ in range(2):
        response = owner.client.post(
            "/api/review/parks/acknowledge", json={"items": [item]}, headers=owner.key()
        )
        assert response.status_code == 204
    assert state(owner)["unseen_parks"] == []
    ack = owner.container.task_repo.get_park_ack(
        owner.owner_id, task["id"], item["formulation_id"]
    )
    assert ack is not None and ack.seen_at == frozen_clock()


def test_020_FR_015_acknowledgement_is_at_most_200_items_and_works_flag_off(
    api: ReviewApi,
) -> None:
    item = {"task_id": "task_000000000000", "formulation_id": "form_000000000000"}
    too_many = api.client.post(
        "/api/review/parks/acknowledge", json={"items": [item] * 201}, headers=api.key()
    )
    assert too_many.status_code == 422
    api.flag("off")
    ok = api.client.post(
        "/api/review/parks/acknowledge", json={"items": [item]}, headers=api.key()
    )
    assert ok.status_code == 204


def _ack_body(*items: tuple[str, str]) -> dict[str, Any]:
    return {
        "items": [
            {"task_id": task_id, "formulation_id": formulation_id}
            for task_id, formulation_id in items
        ]
    }


def test_020_FR_015_park_acknowledgement_same_key_replays_another_body_conflicts(
    api: ReviewApi,
) -> None:
    """http "Mutations": the Idempotency-Key is stored like every other write."""

    headers = api.key()
    first_body = _ack_body(("task_aaaaaaaaaaaa", "form_aaaaaaaaaaaa"))
    first = api.client.post(
        "/api/review/parks/acknowledge", json=first_body, headers=headers
    )
    replay = api.client.post(
        "/api/review/parks/acknowledge", json=first_body, headers=headers
    )
    assert (first.status_code, replay.status_code) == (204, 204)
    assert replay.content == b""
    with allure.step("Reuse the key with another body"):
        other = api.client.post(
            "/api/review/parks/acknowledge",
            json=_ack_body(("task_bbbbbbbbbbbb", "form_bbbbbbbbbbbb")),
            headers=headers,
        )
    assert other.status_code == 409, other.text
    assert other.json()["detail"] == {"reason": "idempotency_conflict"}


def test_020_FR_015_a_lost_park_acknowledgement_write_is_repaired_by_its_replay(
    api: ReviewApi,
) -> None:
    """The ``park_ack:`` reconciler re-marks what the stored record marked."""

    _activated(api)
    task = _due(api)
    sweep(api.container)
    body = _ack_body((task["id"], task["formulation"]["id"]))
    headers = api.key()
    acked_at = api.clock()
    first = api.client.post("/api/review/parks/acknowledge", json=body, headers=headers)
    assert first.status_code == 204
    repo = api.container.task_repo
    ack = repo.get_park_ack(api.owner_id, task["id"], task["formulation"]["id"])
    assert ack is not None and ack.seen_at == acked_at
    repo.save_park_ack(ack.model_copy(update={"seen_at": None}))

    api.clock.advance(minutes=5)
    with allure.step("Replay the key after the write was lost"):
        replay = api.client.post(
            "/api/review/parks/acknowledge", json=body, headers=headers
        )
    assert replay.status_code == 204
    repaired = repo.get_park_ack(api.owner_id, task["id"], task["formulation"]["id"])
    assert repaired is not None and repaired.seen_at == acked_at
    assert state(api)["unseen_parks"] == []


def test_020_FR_015_a_yield_reversal_is_not_a_return(api: ReviewApi) -> None:
    """data-model E6: the yield reverses the park; ``returned_at`` is null."""

    before, parked = _park_with_sweep(api)
    repo = api.container.task_repo
    form = before["formulation"]["id"]
    ack = repo.get_park_ack(api.owner_id, before["id"], form)
    assert ack is not None
    # A row that drifted (e.g. an older build's return) must not survive the yield.
    repo.save_park_ack(ack.model_copy(update={"returned_at": api.clock()}))
    with allure.step("An offline extend made before the park yields"):
        result = api.decide(
            before, "extend", reason="Away", client_decided_at=iso(before["decided_at"])
        )
    assert result["decision"]["yielded_auto_park"] is True
    after = repo.get_park_ack(api.owner_id, before["id"], form)
    assert after is not None
    assert after.returned_at is None
    assert (after.parked_at, after.from_revision, after.source) == (
        ack.parked_at,
        ack.from_revision,
        ack.source,
    )


def test_020_FR_015_020_FR_048_undo_of_a_return_restores_the_park_row(
    api: ReviewApi,
) -> None:
    """Undo of ``return_to_next`` from a park puts ``returned_at`` back to null."""

    _activated(api)
    task = _due(api)
    sweep(api.container)
    parked = api.task(task["id"])
    repo = api.container.task_repo
    form = task["formulation"]["id"]
    result = api.decide(parked, "return_to_next", title=parked["title"])
    returned = repo.get_park_ack(api.owner_id, task["id"], form)
    assert returned is not None and returned.returned_at == api.clock()

    api.clock.advance(minutes=2)
    with allure.step("Undo the return"):
        undone = api.undo_raw(result["decision"]["id"], result["task"]["revision"])
    assert undone.status_code == 200, undone.text
    assert undone.json()["task"]["state"] == "someday"
    assert undone.json()["task"]["parked"]["formulation_id"] == form
    restored = repo.get_park_ack(api.owner_id, task["id"], form)
    assert restored is not None
    assert restored.returned_at is None
    assert restored.parked_at == returned.parked_at
    assert [p["task_id"] for p in state(api)["unseen_parks"]] == [task["id"]]


def test_020_FR_015_returning_a_parked_task_starts_a_formulation_and_records_it(
    api: ReviewApi,
) -> None:
    """Move → Next: new formulation, ``parked`` cleared, ``returned_at`` upserted."""

    _activated(api)
    task = _due(api)
    sweep(api.container)
    parked = api.task(task["id"])
    api.clock.advance(hours=3)
    form = new_id("form")
    returned = api.move(parked, "next", new_formulation_id=form)
    assert returned["parked"] is None
    assert returned["formulation"]["id"] == form
    assert norm(returned["formulation"]["started_at"]) == iso(api.clock())
    ack = api.container.task_repo.get_park_ack(
        api.owner_id, task["id"], task["formulation"]["id"]
    )
    assert ack is not None and ack.returned_at == api.clock()
    assert state(api)["unseen_parks"] == []


def test_020_FR_015_return_to_next_decision_on_a_parked_task_records_the_return(
    api: ReviewApi,
) -> None:
    _activated(api)
    task = _due(api)
    sweep(api.container)
    parked = api.task(task["id"])
    result = api.decide(parked, "return_to_next", title=parked["title"])
    assert result["task"]["state"] == "next"
    ack = api.container.task_repo.get_park_ack(
        api.owner_id, task["id"], task["formulation"]["id"]
    )
    assert ack is not None and ack.returned_at == api.clock()


def test_020_FR_015_a_return_without_its_park_row_writes_none_and_warns(
    api: ReviewApi, caplog: pytest.LogCaptureFixture
) -> None:
    """No made-up ``source``: the missing row stays missing, the log is ids only."""

    _activated(api)
    task = _due(api, title="SENTINEL-RETURN-TITLE")
    sweep(api.container)
    repo = api.container.task_repo
    with repo.command_lock(api.owner_id):
        repo._thread_state.conn.execute(  # type: ignore[attr-defined]
            "DELETE FROM review_park_acks WHERE owner_id = ?", (api.owner_id,)
        )
    with caplog.at_level(logging.WARNING, logger="app.modules.tasks"):
        returned = api.move(api.task(task["id"]), "next")
    assert returned["state"] == "next"
    assert repo.list_park_acks(api.owner_id) == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        f"review_park_return_unrecorded owner_id={api.owner_id} "
        f"task_id={task['id']} formulation_id={task['formulation']['id']}"
    ]
    assert "SENTINEL-RETURN-TITLE" not in caplog.text


def test_020_SC_006_a_parked_task_returns_in_one_action(api: ReviewApi) -> None:
    """The return is one ordinary transition, accepted with the flag on or off."""

    _activated(api)
    task = _due(api)
    sweep(api.container)
    api.flag("off")
    assert api.move(api.task(task["id"]), "next")["state"] == "next"


# ===================================================================== edges
def test_020_FR_014_a_review_service_without_wiring_exposes_no_one(
    api: ReviewApi,
) -> None:
    """Unwired defaults fail closed: no owner exposed, no session closed."""

    _activated(api)
    bare = ReviewService(api.container.task_service)
    assert bare.run_auto_park_sweep(api.clock()) == (0, 0, 0, 0)
    assert bare.run_review_retention(api.clock()) == (0, 0)


def test_020_FR_014_owners_never_activated_are_skipped_by_exposure(
    api: ReviewApi,
) -> None:
    """A settings row alone (onboarding before the explainer) never parks."""

    put = api.client.put(
        "/api/review/settings",
        json={"threshold_days": 7, "expected_revision": 1},
        headers=api.key(),
    )
    assert put.status_code == 200
    task = api.create(state="next")
    api.clock.advance(days=30)
    assert sweep(api.container).owners == 0
    assert api.stored(task["id"]).state == "next"


def test_020_FR_013_sweep_rechecks_each_candidate_under_the_lock(
    api: ReviewApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Candidates read outside the lock that moved, vanished or changed are skipped."""

    _activated(api)
    moved = api.create("Moved", state="next")
    changed = api.create("Changed", state="next")
    api.clock.advance(days=22)
    stale = [api.stored(moved["id"]), api.stored(changed["id"])]
    ghost = stale[0].model_copy(update={"id": "task_000000000000"})
    api.move(api.task(moved["id"]), "waiting", waiting_for="Ann")
    api.patch(api.task(changed["id"]), title="Something else entirely")
    repo = api.container.task_repo
    monkeypatch.setattr(repo, "list_next_tasks", lambda owner_id: [*stale, ghost])
    result = sweep(api.container)
    assert result.parked == 0
    assert api.stored(moved["id"]).state == "waiting"
    assert api.stored(changed["id"]).state == "next"


def test_020_FR_013_a_sweep_key_already_recorded_is_not_parked_twice(
    api: ReviewApi,
) -> None:
    """The deterministic key replays: a park already recorded writes nothing."""

    _activated(api)
    task = _due(api)
    stored = api.stored(task["id"])
    key = f"auto-park:{stored.id}:{stored.formulation_id}:{stored.revision}"
    repo = api.container.task_repo
    with repo.command_lock(api.owner_id):
        repo.save_idempotency(
            owner_id=api.owner_id,
            record=IdempotencyRecord(
                key=key,
                command=f"auto-park:{stored.id}",
                request_hash="0" * 64,
                resource_id=stored.id,
                response_body=rd.AutoParkResultDocument(
                    applied=False, task=stored
                ).model_dump(mode="json"),
                created_at=api.clock(),
            ),
        )
    assert sweep(api.container).parked == 0
    assert api.stored(task["id"]).state == "next"


def test_020_FR_013_device_park_replays_and_a_lost_park_write_repairs(
    api: ReviewApi,
) -> None:
    """Same key returns the original; a record left before its write re-applies."""

    _activated(api)
    task = _due(api)
    headers = api.key()
    body = {"formulation_id": task["formulation"]["id"]}
    path = f"/api/tasks/{task['id']}/auto-park"
    first = api.client.post(path, json=body, headers=headers)
    assert first.json()["applied"] is True
    repo = api.container.task_repo
    before = api.stored(task["id"])
    repo.save(
        before.model_copy(
            update={"state": "next", "parked": None, "revision": task["revision"]}
        )
    )
    replay = api.client.post(path, json=body, headers=headers)
    assert replay.status_code == 200 and replay.json()["applied"] is True
    assert api.stored(task["id"]).state == "someday"

    fresh = api.create("Fresh", state="next")
    not_applied = api.key()
    fresh_body = {"formulation_id": fresh["formulation"]["id"]}
    fresh_path = f"/api/tasks/{fresh['id']}/auto-park"
    assert api.client.post(fresh_path, json=fresh_body, headers=not_applied).json() == {
        "applied": False,
        "task": api.task(fresh["id"]),
    }
    again = api.client.post(fresh_path, json=fresh_body, headers=not_applied)
    assert again.json()["applied"] is False


def test_020_FR_016_activation_leaves_an_already_clamped_clock_alone(
    api: ReviewApi,
) -> None:
    """A clock already at the instant with a later floor needs no write."""

    task = seed_old_next_task(api, age=0 * DAY)
    stored = api.stored(task.id)
    api.container.task_repo.save(
        stored.model_copy(update={"formulation_park_floor_at": api.clock() + 60 * DAY})
    )
    acknowledge(api)
    after = api.stored(task.id)
    assert after.formulation_park_floor_at == api.clock() + 60 * DAY
    assert after.formulation_started_at == stored.formulation_started_at


def test_020_FR_051_a_replayed_acknowledgement_of_an_active_owner_is_a_no_op(
    api: ReviewApi,
) -> None:
    headers = api.key()
    first = api.client.post(ACK, json={}, headers=headers).json()
    api.clock.advance(days=1)
    again = api.client.post(ACK, json={}, headers=headers).json()
    assert again["settings"] == first["settings"]


def test_020_FR_043_retention_failure_for_one_owner_is_logged_by_type(
    api: ReviewApi, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _activated(api)

    def closer(owner_id: str, now: datetime) -> int:
        raise ValueError("SENTINEL-RETENTION-TEXT")

    monkeypatch.setattr(api.container.review_service, "idle_session_closer", closer)
    with caplog.at_level(logging.WARNING):
        sweep(api.container)
    assert (
        f"review_sweep_owner_failed owner_id={api.owner_id} error=ValueError "
        "reason=retention"
    ) in caplog.text
    assert "SENTINEL-RETENTION-TEXT" not in caplog.text
