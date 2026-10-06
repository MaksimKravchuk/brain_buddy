"""Spec 020: every section of the shared review-flow vectors, run once in PR-02.

``tests/fixtures/review_flow_vectors.json`` is consumed by the iOS core and the
web as well; running every section here against the pure
``app.modules.tasks.review_rules`` means no lane relies on a vector that has
never run (plan Test strategy, review c2 TE-06).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.tasks import review_rules as flow
from app.modules.tasks.review_rules import (
    Receipt,
    ReviewTask,
    SessionSummary,
    StepProgress,
)
from app.utils.time import from_isoformat

from .test_review_formulation_vectors import (
    clock_from,
    instant,
    iso,
    load_fixture,
    settings_from,
)

VECTORS = load_fixture("review_flow_vectors.json")
SECTIONS = {
    "steps",
    "wins",
    "capacity",
    "waiting_queue",
    "someday_queue",
    "restart",
    "session_status",
    "idle_close",
    "qualifying_activity",
    "counted_review",
    "regularity",
    "next_review",
    "decision_queue",
    "stall_recommendation",
    "active_time",
    "while_away",
    "duplicate_filter",
}


def _cases(section: str) -> Any:
    return pytest.mark.parametrize(
        "vector", VECTORS[section], ids=[vector["id"] for vector in VECTORS[section]]
    )


def _task(raw: dict[str, Any]) -> ReviewTask:
    return ReviewTask(
        id=raw["id"],
        state=raw["state"],
        revision=raw.get("revision", 1),
        completed_at=instant(raw.get("completed_at")),
        waiting_since=instant(raw.get("waiting_since")),
        updated_at=instant(raw.get("updated_at")),
        parked_at=instant(raw.get("parked_at")),
    )


def _receipt(raw: dict[str, Any]) -> Receipt:
    return Receipt(
        task_id=raw["task_id"],
        kind=raw["kind"],
        task_revision=raw["task_revision"],
        reviewed_at=from_isoformat(raw["reviewed_at"]),
        hidden_until=from_isoformat(raw["hidden_until"]),
        source=raw["source"],
    )


def test_020_FR_028_every_flow_vector_section_runs() -> None:
    """The file holds exactly the sections this module runs, none empty."""

    sections = {key for key, value in VECTORS.items() if isinstance(value, list)}
    assert VECTORS["schema"] == "brainbuddy-review-flow-vectors/v1"
    assert sections == SECTIONS
    assert all(VECTORS[section] for section in sections)


@_cases("steps")
def test_020_FR_028_review_steps_vector(vector: dict[str, Any]) -> None:
    """Quick and full reviews have their fixed step order (020-FR-028)."""

    assert list(flow.review_steps(vector["mode"])) == vector["expect"]


@_cases("wins")
def test_020_FR_028_wins_window_vector(vector: dict[str, Any]) -> None:
    """Wins are tasks completed in the last 7 days (020-FR-028)."""

    tasks = [_task(task) for task in vector["tasks"]]
    assert flow.wins(tasks, from_isoformat(vector["now"])) == vector["expect"]


@_cases("capacity")
def test_020_FR_031_capacity_mirror_vector(vector: dict[str, Any]) -> None:
    """Next count, 4-week pace and implied weeks; Next only without history."""

    mirror = flow.capacity_mirror(
        vector["next_count"],
        [from_isoformat(value) for value in vector["completed_at"]],
        from_isoformat(vector["now"]),
    )
    assert {
        "next_count": mirror.next_count,
        "weeks_of_history": mirror.weeks_of_history,
        "weekly_average_4w": mirror.weekly_average_4w,
        "implied_weeks": mirror.implied_weeks,
    } == vector["expect"]


@_cases("waiting_queue")
def test_020_FR_032_waiting_queue_vector(vector: dict[str, Any]) -> None:
    """Waiting older than 7 days, unhidden, oldest first (020-FR-032)."""

    queue = flow.waiting_queue(
        [_task(task) for task in vector["tasks"]],
        [_receipt(receipt) for receipt in vector["receipts"]],
        from_isoformat(vector["now"]),
    )
    assert queue == vector["expect"]


@_cases("someday_queue")
def test_020_FR_032_someday_queue_vector(vector: dict[str, Any]) -> None:
    """At most 7 Someday tasks, never-reviewed first (020-FR-032)."""

    queue = flow.someday_queue(
        [_task(task) for task in vector["tasks"]],
        [_receipt(receipt) for receipt in vector["receipts"]],
        from_isoformat(vector["now"]),
        limit=vector["limit"],
    )
    assert {"eligible_total": queue.eligible_total, "shown": queue.shown} == vector[
        "expect"
    ]


@_cases("restart")
def test_020_FR_017_restart_anchor_vector(vector: dict[str, Any]) -> None:
    """21 days from the last counted review, or from onboarding (020-FR-017)."""

    assert (
        flow.restart_mode(
            onboarded_at=instant(vector["onboarded_at"]),
            last_counted_review_at=instant(vector["last_counted_review_at"]),
            now=from_isoformat(vector["now"]),
        )
        is vector["expect"]
    )


@_cases("session_status")
def test_020_FR_029_session_status_vector(vector: dict[str, Any]) -> None:
    """Done → completed / completed_empty; otherwise partial / abandoned."""

    status = flow.ended_status(vector["end"], vector["qualifying_activity"])
    assert status == vector["expect"]


@_cases("idle_close")
def test_020_FR_029_idle_close_vector(vector: dict[str, Any]) -> None:
    """A review idle for 7 days is closed by the sweep (020-FR-029)."""

    due = flow.idle_close_due(
        from_isoformat(vector["last_activity_at"]), from_isoformat(vector["now"])
    )
    assert due is vector["expect"]


@_cases("qualifying_activity")
def test_020_FR_029_qualifying_activity_vector(vector: dict[str, Any]) -> None:
    """A decision, or a non-summary step finished with nothing to decide."""

    steps = {
        code: StepProgress(status=step["status"], finished_empty=step["finished_empty"])
        for code, step in vector["steps"].items()
    }
    assert flow.qualifying_activity(vector["item_decisions"], steps) is vector["expect"]


@_cases("counted_review")
def test_020_FR_029_counted_review_vector(vector: dict[str, Any]) -> None:
    """Only completed, partial and qualifying open reviews count (020-FR-029)."""

    counted = flow.is_counted(vector["status"], vector["qualifying_activity"])
    assert counted is vector["expect"]


@_cases("regularity")
def test_020_FR_029_regularity_instant_vector(vector: dict[str, Any]) -> None:
    """The latest counted-review instant drives restart, skip and Last review."""

    sessions = [
        SessionSummary(
            status=session["status"],
            qualifying_activity=session["qualifying_activity"],
            last_activity_at=from_isoformat(session["last_activity_at"]),
            ended_at=instant(session["ended_at"]),
        )
        for session in vector["sessions"]
    ]
    assert iso(flow.last_counted_review_at(sessions)) == vector["expect"]


@_cases("next_review")
def test_020_FR_036_next_review_and_notification_skip_vector(
    vector: dict[str, Any],
) -> None:
    """Weekly slot in the zone, skipped after a review in the 6 days before."""

    settings = vector["settings"]
    slot = flow.next_review_at(
        review_weekday=settings["review_weekday"],
        review_time=settings["review_time"],
        time_zone=settings["time_zone"],
        now=from_isoformat(vector["now"]),
        last_counted_review_at=instant(vector["last_counted_review_at"]),
    )
    assert iso(slot) == vector["expect"]


@_cases("decision_queue")
def test_020_FR_004_decision_queue_vector(vector: dict[str, Any]) -> None:
    """The decision step's queue: the aggregate, earliest-asking first."""

    tasks = [
        (task["id"], clock_from(task, task_id=task["id"])) for task in vector["tasks"]
    ]
    order = flow.decision_queue(
        tasks, settings_from(vector["settings"]), from_isoformat(vector["now"])
    )
    assert order == vector["expect"]


@_cases("stall_recommendation")
def test_020_FR_007_stall_recommendation_vector(vector: dict[str, Any]) -> None:
    """Each stall reason recommends one decision; none recommends nothing."""

    assert flow.stall_recommendation(vector["stall_reason"]) == vector["expect"]


@_cases("active_time")
def test_020_SC_004_active_time_vector(vector: dict[str, Any]) -> None:
    """Active seconds per step: idle gaps over 2 minutes and background count 0."""

    accumulator = flow.ActiveTimeAccumulator()
    for event in vector["events"]:
        accumulator.record(
            event["kind"], from_isoformat(event["at"]), event.get("step")
        )
    assert accumulator.seconds_by_step == vector["expect"]


@_cases("while_away")
def test_020_FR_015_while_away_once_a_day_vector(vector: dict[str, Any]) -> None:
    """At app open at most once a calendar day; always first in a review."""

    last = vector["last_shown_day"]
    shown = flow.show_while_away(
        context=vector["context"],
        has_unseen=vector["has_unseen"],
        last_shown_day=None if last is None else date.fromisoformat(last),
        today=date.fromisoformat(vector["today"]),
    )
    assert shown is vector["expect"]


@_cases("duplicate_filter")
def test_020_FR_019_project_wide_duplicate_filter_vector(
    vector: dict[str, Any],
) -> None:
    """Proposals equal to any open project title are dropped, sent or not."""

    assert len(vector["sent_titles"]) <= 20
    kept = flow.drop_duplicate_proposals(
        vector["proposals"],
        current_title=vector["current_title"],
        open_titles=vector["project_open_titles"],
    )
    assert kept == vector["expect"]


# ------------------------------------------------- inputs outside the vectors
def test_020_FR_028_unknown_review_mode_or_end_is_refused() -> None:
    """Modes and session ends are closed sets (020-FR-028, 020-FR-029)."""

    with pytest.raises(ValueError, match="mode"):
        flow.review_steps("weekly")
    with pytest.raises(ValueError, match="session end"):
        flow.ended_status("left", qualifying=True)


def test_020_SC_004_active_time_rejects_malformed_events() -> None:
    """A step event needs its step; an unknown event kind is a client bug."""

    accumulator = flow.ActiveTimeAccumulator()
    at = from_isoformat("2026-10-09T14:00:00Z")
    with pytest.raises(ValueError, match="needs a step"):
        accumulator.record("resume", at)
    with pytest.raises(ValueError, match="unknown"):
        accumulator.record("scroll", at)


def test_020_SC_004_interaction_outside_a_step_counts_nothing() -> None:
    """Before the first step and after leaving, time is not attributed."""

    accumulator = flow.ActiveTimeAccumulator()
    start = from_isoformat("2026-10-09T14:00:00Z")
    accumulator.record("interaction", start)
    accumulator.record("foreground", start)
    accumulator.record("enter_step", start, "inbox")
    accumulator.record("leave", from_isoformat("2026-10-09T14:00:30Z"))
    accumulator.record("interaction", from_isoformat("2026-10-09T14:00:40Z"))
    assert accumulator.seconds_by_step == {"inbox": 30}
