"""Spec 020: review settings and the review state (contracts/http.md §5).

``PUT /review/settings`` validates and applies the threshold, schedule, time
zone and onboarding with optimistic concurrency; a threshold change floors
every park for 7 days (FR-039), a real time-zone change floors due-dated Next
tasks (FR-046), and a field equal to the stored value is no change.
``GET /review/state`` reports the derived counts, the regularity instant from
counted reviews only, the next slot, restart mode and the open session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.modules.tasks import review_domain as rd

from .conftest import FrozenClock
from .test_review_decisions_api import ReviewApi, iso, new_id, norm

DAY = timedelta(days=1)
SETTINGS = "/api/review/settings"
STATE = "/api/review/state"


@pytest.fixture
def api(api_client: TestClient, frozen_clock: FrozenClock) -> ReviewApi:
    review_api = ReviewApi(api_client, frozen_clock)
    review_api.flag("on")
    review_api.activate_at(frozen_clock() - 30 * DAY)
    return review_api


def _put(api: ReviewApi, headers: dict[str, str] | None = None, **body: Any) -> Any:
    body.setdefault("expected_revision", _settings(api)["revision"])
    return api.client.put(SETTINGS, json=body, headers=headers or api.key())


def _settings(api: ReviewApi) -> dict[str, Any]:
    response = api.client.get(STATE)
    assert response.status_code == 200, response.text
    settings: dict[str, Any] = response.json()["settings"]
    return settings


def _state(api: ReviewApi) -> dict[str, Any]:
    response = api.client.get(STATE)
    assert response.status_code == 200, response.text
    state: dict[str, Any] = response.json()
    return state


@pytest.mark.parametrize(
    "body",
    [
        {"threshold_days": 10},
        {"review_weekday": 8},
        {"review_weekday": 0},
        {"review_time": "25:00"},
        {"review_time": "4pm"},
        {"onboarded": False},
    ],
)
def test_020_FR_039_settings_reject_values_outside_the_contract(
    api: ReviewApi, body: dict[str, Any]
) -> None:
    """Threshold 7/14/21/28, weekday 1..7, ``HH:MM``, ``onboarded: true`` only."""

    assert _put(api, **body).status_code == 422


def test_020_FR_035_a_non_iana_time_zone_is_400_invalid_time_zone(
    api: ReviewApi,
) -> None:
    for zone in ("Mars/Olympus", "localtime", "+02:00"):
        response = _put(api, time_zone=zone)
        assert response.status_code == 400, zone
        assert response.json()["detail"] == {"reason": "invalid_time_zone"}


def test_020_FR_039_a_stale_expected_revision_is_409(api: ReviewApi) -> None:
    assert _put(api, threshold_days=21).status_code == 200
    response = _put(api, threshold_days=7, expected_revision=1)
    assert response.status_code == 409
    assert _settings(api)["threshold_days"] == 21


def test_020_FR_039_threshold_change_updates_markers_and_floors_parks_7_days(
    api: ReviewApi, caplog: pytest.LogCaptureFixture
) -> None:
    """Markers move at once; nothing parks before change + 7 days."""

    task = api.create(state="next")
    api.clock.advance(days=10)
    assert _state(api)["counts"]["asks_for_decision"] == 0
    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        response = _put(api, threshold_days=7)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["threshold_days"] == 7
    assert norm(body["owner_park_floor_at"]) == iso(api.clock() + 7 * DAY)
    assert body["revision"] == 2
    formulation = api.task(task["id"])["formulation"]
    assert norm(formulation["ask_at"]) == iso(api.clock() - 3 * DAY)
    assert norm(formulation["park_due_at"]) == iso(api.clock() + 7 * DAY)
    assert _state(api)["counts"]["asks_for_decision"] == 1
    lines = [
        r.getMessage()
        for r in caplog.records
        if "review_settings_changed" in r.getMessage()
    ]
    assert lines and "threshold_old=14" in lines[0] and "threshold_new=7" in lines[0]


def test_020_FR_046_a_time_zone_change_floors_due_dated_next_tasks_only(
    api: ReviewApi,
) -> None:
    """``max(existing, now + 7 d)`` on due-dated Next tasks, no revision bump."""

    dated = api.create(state="next", due_date="2026-10-20")
    plain = api.create("Call Bob", state="next")
    api.clock.advance(days=1)
    response = _put(api, time_zone="Asia/Tokyo")
    assert response.status_code == 200, response.text
    dated_after = api.stored(dated["id"])
    plain_after = api.stored(plain["id"])
    assert iso(dated_after.formulation_park_floor_at) == iso(api.clock() + 7 * DAY)
    assert plain_after.formulation_park_floor_at is None
    assert dated_after.revision == dated["revision"]
    assert dated_after.updated_at == api.stored(dated["id"]).updated_at


def test_020_FR_035_values_equal_to_the_stored_ones_are_no_change(
    api: ReviewApi,
) -> None:
    """Equal zone: no floor. Equal threshold: no owner floor. All equal: same revision."""

    first = _put(api, time_zone="Europe/Berlin", review_weekday=5).json()
    dated = api.create(state="next", due_date="2026-10-20")
    api.clock.advance(days=1)
    same = _put(
        api,
        time_zone="Europe/Berlin",
        threshold_days=14,
        review_weekday=5,
        review_time="16:00",
    )
    assert same.status_code == 200
    assert same.json()["revision"] == first["revision"]
    assert same.json()["owner_park_floor_at"] is None
    assert api.stored(dated["id"]).formulation_park_floor_at is None
    stale = _put(
        api, time_zone="Europe/Berlin", expected_revision=first["revision"] - 1
    )
    assert stale.status_code == 409


def test_020_FR_035_onboarding_records_the_first_onboarded_instant(
    api: ReviewApi,
) -> None:
    onboarded = _put(api, onboarded=True, review_weekday=1, review_time="09:30").json()
    assert norm(onboarded["onboarded_at"]) == iso(api.clock())
    api.clock.advance(days=3)
    again = _put(api, onboarded=True).json()
    assert again["onboarded_at"] == onboarded["onboarded_at"]
    assert again["revision"] == onboarded["revision"]


def test_020_FR_042_settings_are_accepted_with_the_flag_off(api: ReviewApi) -> None:
    api.flag("off")
    response = api.client.put(
        SETTINGS, json={"threshold_days": 21, "expected_revision": 1}, headers=api.key()
    )
    assert response.status_code == 200, response.text
    assert response.json()["threshold_days"] == 21


def test_020_FR_039_settings_replay_and_a_lost_write_repair(api: ReviewApi) -> None:
    """Same key returns the original; a record left before its write re-applies."""

    headers = api.key()
    first = _put(api, headers=headers, threshold_days=21, expected_revision=1)
    replay = _put(api, headers=headers, threshold_days=21, expected_revision=1)
    assert first.json() == replay.json()

    repo = api.container.task_repo
    stored = repo.get_review_settings(api.owner_id)
    assert stored is not None
    repo.save_review_settings(
        stored.model_copy(update={"threshold_days": 14, "revision": 1})
    )
    _put(api, headers=headers, threshold_days=21, expected_revision=1)
    assert _settings(api)["threshold_days"] == 21


# ------------------------------------------------------------------- state
def _session(api: ReviewApi, **fields: Any) -> rd.ReviewSessionDocument:
    return api.session(**fields)


def test_020_FR_004_state_counts_the_asks_for_decision_aggregate(
    api: ReviewApi,
) -> None:
    """``asks_for_decision`` = asks + moves tomorrow + not-yet-applied park due."""

    api.create("A", state="next")
    api.clock.advance(days=7)
    api.create("B", state="next")
    api.clock.advance(days=7)
    api.create("C", state="next")
    api.clock.advance(days=7, hours=1)
    # A: 21 d (park due), B: 14 d (asks), C: 7 d (ageing).
    counts = _state(api)["counts"]
    assert counts == {"asks_for_decision": 2, "moves_tomorrow": 0}
    api.clock.advance(days=6)
    # B: 20 d + 1 h (moves tomorrow), C: 13 d (ageing).
    assert _state(api)["counts"] == {"asks_for_decision": 2, "moves_tomorrow": 1}


def test_020_FR_038_last_counted_review_uses_counted_reviews_only(
    api: ReviewApi,
) -> None:
    """``completed_empty`` and ``abandoned`` never count (FR-029, FR-038)."""

    now = api.clock()
    _session(
        api,
        status="completed",
        ended_at=now - 9 * DAY,
        last_activity_at=now - 9 * DAY,
        qualifying_activity=True,
        clear_start="yes",
    )
    _session(
        api,
        status="completed_empty",
        ended_at=now - 2 * DAY,
        last_activity_at=now - 2 * DAY,
    )
    _session(api, status="abandoned", last_activity_at=now - DAY)
    state = _state(api)
    assert norm(state["last_counted_review_at"]) == iso(now - 9 * DAY)
    summary = state["last_counted_review"]
    assert summary["status"] == "completed"
    assert summary["clear_start"] == "yes"
    assert state["open_session"] is None


def test_020_SC_007_last_counted_review_summary_and_open_session(
    api: ReviewApi,
) -> None:
    """A review finished offline on iOS shows its summary; an open one is listed."""

    now = api.clock()
    finished = _session(
        api,
        status="completed",
        ended_at=now - DAY,
        last_activity_at=now - DAY,
        qualifying_activity=True,
        counts=rd.SessionCountsDocument(done=3, kept=1),
    )
    open_one = _session(api, qualifying_activity=False)
    state = _state(api)
    assert state["last_counted_review"]["session_id"] == finished.id
    assert state["last_counted_review"]["counts"]["done"] == 3
    assert state["last_counted_review"]["origin"] == "ios"
    assert state["open_session"]["id"] == open_one.id
    assert state["open_session"]["set_aside_count"] == 0


def test_020_FR_017_restart_mode_counts_from_onboarding_and_the_last_review(
    api: ReviewApi,
) -> None:
    """Not onboarded: no restart. Onboarded 21 days ago, never reviewed: restart."""

    assert _state(api)["restart_mode"] is False
    _put(api, onboarded=True)
    api.clock.advance(days=20)
    assert _state(api)["restart_mode"] is False
    api.clock.advance(days=1)
    assert _state(api)["restart_mode"] is True
    _session(
        api,
        status="partial",
        last_activity_at=api.clock() - DAY,
        qualifying_activity=True,
    )
    assert _state(api)["restart_mode"] is False


def test_020_FR_035_next_review_at_is_the_slot_in_the_stored_zone_with_the_skip(
    api: ReviewApi,
) -> None:
    """Friday 16:00 Berlin; a counted review in the 6 days before skips it."""

    _put(api, time_zone="Europe/Berlin", review_weekday=5, review_time="16:00")
    # Now is Friday 2026-10-09 16:02 in Berlin: the next slot is a week later.
    assert norm(_state(api)["next_review_at"]) == "2026-10-16T14:00:00Z"
    _session(
        api,
        status="completed",
        ended_at=datetime(2026, 10, 12, tzinfo=UTC),
        last_activity_at=datetime(2026, 10, 12, tzinfo=UTC),
        qualifying_activity=True,
    )
    assert norm(_state(api)["next_review_at"]) == "2026-10-23T14:00:00Z"


def test_020_FR_051_state_reports_activation_grace_receipts_and_server_now(
    api: ReviewApi,
) -> None:
    activated = api.clock() - 30 * DAY
    state = _state(api)
    assert state["explainer_seen"] is True
    assert norm(state["grace_until"]) == iso(activated + 14 * DAY)
    assert norm(state["server_now"]) == iso(api.clock())
    waiting = api.create("Quote", state="waiting", waiting_for="Ann")
    api.decide(waiting, "keep_waiting")
    receipts = _state(api)["receipts"]
    assert [(r["task_id"], r["kind"]) for r in receipts] == [(waiting["id"], "waiting")]
    api.clock.advance(days=8)
    assert _state(api)["receipts"] == []
    assert new_id("x")


def test_020_FR_032_a_receipt_for_a_task_changed_since_is_not_returned(
    api: ReviewApi,
) -> None:
    """data-model E5: a receipt hides its task only at ``task_revision``."""

    waiting = api.create("Quote", state="waiting", waiting_for="Ann")
    kept = api.create("Invoice", state="waiting", waiting_for="Bob")
    body = api.decide(waiting, "keep_waiting")
    api.decide(kept, "keep_waiting")
    with allure.step("Edit one kept task: its revision moves past the receipt"):
        api.patch(body["task"], details="Ann called back")
    receipts = _state(api)["receipts"]
    assert [r["task_id"] for r in receipts] == [kept["id"]]
    assert receipts[0]["task_revision"] == api.task(kept["id"])["revision"]
    stored = api.container.task_repo.list_review_receipts(api.owner_id)
    assert {r.task_id for r in stored} == {waiting["id"], kept["id"]}


def test_020_FR_051_an_owner_never_activated_sees_no_markers(
    api_client: TestClient, frozen_clock: FrozenClock
) -> None:
    """Before the explainer nothing asks, whatever the age (FR-051)."""

    api = ReviewApi(api_client, frozen_clock)
    api.flag("on")
    api.create(state="next")
    frozen_clock.advance(days=60)
    with allure.step("GET /review/state before any acknowledgement"):
        state = _state(api)
    assert state["explainer_seen"] is False
    assert state["grace_until"] is None
    assert state["counts"] == {"asks_for_decision": 0, "moves_tomorrow": 0}
    assert state["settings"]["revision"] == 1
