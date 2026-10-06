"""Spec 020: the shared formulation vectors, and the copy drift guard.

Runs every section of ``tests/fixtures/review_formulation_vectors.json``
(contracts/formulation-clock.md §6) against ``app.modules.tasks.formulation``,
and fails when any byte-identical copy in the Swift or web test tree is missing
or differs from its canonical file (§6 "Drift guard"). The helpers below are
shared with ``test_review_flow_vectors.py``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.modules.tasks import formulation as rules
from app.modules.tasks.formulation import (
    ClockBefore,
    FormulationRuleError,
    OwnerClockSettings,
    ParkMarker,
    ReleasedClock,
    TaskClock,
)
from app.utils.time import from_isoformat

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
FIXTURES = BACKEND_DIR / "tests" / "fixtures"

# contracts/formulation-clock.md §6 "Who lands the copies" (tasks.md T023):
# every canonical fixture and its byte-identical copies.
FIXTURE_COPIES: dict[str, tuple[str, ...]] = {
    "review_formulation_vectors.json": (
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/"
        "review_formulation_vectors.json",
        "frontend/src/features/review/__tests__/review_formulation_vectors.json",
    ),
    "review_flow_vectors.json": (
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/Resources/"
        "review_flow_vectors.json",
        "frontend/src/features/review/__tests__/review_flow_vectors.json",
    ),
    "review_wire_fixtures.json": (
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/Resources/"
        "review_wire_fixtures.json",
        "frontend/src/features/review/__tests__/review_wire_fixtures.json",
    ),
    # Slice PR-15 (tasks.md T086): the decision and park traces, replayed by
    # the Swift sync tests against BrainBuddyFakeServer (T173).
    "review_traces_tasks.json": (
        "ios/BrainBuddyKit/Tests/BrainBuddySyncTests/Resources/"
        "review_traces_tasks.json",
    ),
}


# --------------------------------------------------------------- shared helpers
def load_fixture(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def instant(value: str | None) -> datetime | None:
    return None if value is None else from_isoformat(value)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%SZ")


def day(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def settings_from(raw: dict[str, Any]) -> OwnerClockSettings:
    return OwnerClockSettings(
        threshold_days=raw["threshold_days"],
        time_zone=raw["time_zone"],
        owner_park_floor_at=instant(raw.get("owner_park_floor_at")),
        activated_at=instant(raw.get("activated_at")),
    )


def settings_to(settings: OwnerClockSettings) -> dict[str, Any]:
    return {
        "threshold_days": settings.threshold_days,
        "time_zone": settings.time_zone,
        "owner_park_floor_at": iso(settings.owner_park_floor_at),
        "activated_at": iso(settings.activated_at),
    }


def _clock_before(raw: dict[str, Any]) -> ClockBefore:
    return ClockBefore(
        started_at=from_isoformat(raw["started_at"]),
        extended_at=instant(raw["extended_at"]),
        extension_reason=raw["extension_reason"],
        park_floor_at=instant(raw["park_floor_at"]),
        stalled_before=raw["stalled_before"],
    )


def _released(raw: dict[str, Any]) -> ReleasedClock:
    return ReleasedClock(
        formulation_id=raw["formulation_id"],
        started_at=from_isoformat(raw["started_at"]),
        extended_at=instant(raw["extended_at"]),
        extension_reason=raw["extension_reason"],
        park_floor_at=instant(raw["park_floor_at"]),
        stalled_before=raw["stalled_before"],
    )


def _released_to(value: ReleasedClock) -> dict[str, Any]:
    return {
        "formulation_id": value.formulation_id,
        "started_at": iso(value.started_at),
        "extended_at": iso(value.extended_at),
        "extension_reason": value.extension_reason,
        "park_floor_at": iso(value.park_floor_at),
        "stalled_before": value.stalled_before,
    }


def clock_from(raw: dict[str, Any], *, task_id: str = "task_vector") -> TaskClock:
    """A clock from a transition ``before`` or a classification ``task``."""

    started = instant(raw.get("formulation_started_at"))
    parked = raw.get("parked")
    default_id = f"form_{task_id}" if started is not None else None
    return TaskClock(
        state=raw.get("state"),
        title=raw.get("title"),
        revision=raw.get("revision", 1),
        formulation_id=raw.get("formulation_id", default_id),
        formulation_started_at=started,
        formulation_extended_at=instant(raw.get("formulation_extended_at")),
        formulation_extension_reason=raw.get("formulation_extension_reason"),
        formulation_park_floor_at=instant(raw.get("formulation_park_floor_at")),
        consecutive_stalled_formulations=raw.get("consecutive_stalled_formulations", 0),
        due_date=day(raw.get("due_date")),
        parked=(
            None
            if parked is None
            else ParkMarker(
                at=from_isoformat(parked["at"]),
                formulation_id=parked["formulation_id"],
                from_revision=parked["from_revision"],
                clock_before=_clock_before(parked["clock_before"]),
            )
        ),
    )


def clock_to(clock: TaskClock) -> dict[str, Any]:
    parked = clock.parked
    return {
        "state": clock.state,
        "title": clock.title,
        "revision": clock.revision,
        "formulation_id": clock.formulation_id,
        "formulation_started_at": iso(clock.formulation_started_at),
        "formulation_extended_at": iso(clock.formulation_extended_at),
        "formulation_extension_reason": clock.formulation_extension_reason,
        "formulation_park_floor_at": iso(clock.formulation_park_floor_at),
        "consecutive_stalled_formulations": clock.consecutive_stalled_formulations,
        "due_date": None if clock.due_date is None else clock.due_date.isoformat(),
        "parked": (
            None
            if parked is None
            else {
                "at": iso(parked.at),
                "formulation_id": parked.formulation_id,
                "from_revision": parked.from_revision,
                "clock_before": {
                    "started_at": iso(parked.clock_before.started_at),
                    "extended_at": iso(parked.clock_before.extended_at),
                    "extension_reason": parked.clock_before.extension_reason,
                    "park_floor_at": iso(parked.clock_before.park_floor_at),
                    "stalled_before": parked.clock_before.stalled_before,
                },
            }
        ),
    }


def derived_view(
    clock: TaskClock, settings: OwnerClockSettings, now: datetime
) -> dict[str, Any]:
    """Class, derived instants and aggregates as a classification ``expect``."""

    instants = rules.derive_instants(clock, settings)
    klass = rules.classify(clock, settings, now)
    return {
        "class": klass,
        "ageing_at": iso(instants.ageing_at) if instants else None,
        "ask_at": iso(instants.ask_at) if instants else None,
        "park_due_at": iso(instants.park_due_at) if instants else None,
        "paused_until": iso(instants.paused_until) if instants else None,
        "asks_for_decision": rules.asks_for_decision(klass),
        "restart_eligible": rules.restart_eligible(clock, settings, now),
        "third_stall": rules.third_stall(clock, settings, now),
    }


VECTORS = load_fixture("review_formulation_vectors.json")


def _ids(section: str) -> list[str]:
    return [vector["id"] for vector in VECTORS[section]]


# ------------------------------------------------------------- normalisation
@pytest.mark.parametrize("vector", VECTORS["normalisation"], ids=_ids("normalisation"))
def test_020_FR_002_normalisation_vector(vector: dict[str, Any]) -> None:
    """A title change is substantive iff the formulation keys differ (020-FR-002)."""

    assert rules.formulation_key(vector["old"]) == vector["old_key"]
    assert rules.formulation_key(vector["new"]) == vector["new_key"]
    assert rules.is_substantive(vector["old"], vector["new"]) is vector["substantive"]


# ------------------------------------------------------------ classification
@pytest.mark.parametrize(
    "vector", VECTORS["classification"], ids=_ids("classification")
)
def test_020_FR_004_classification_vector(vector: dict[str, Any]) -> None:
    """Class, instants and aggregates (020-FR-004, 020-FR-005, 020-FR-009,
    020-FR-012, 020-FR-016, 020-FR-017, 020-FR-039, 020-FR-046, 020-FR-051)."""

    clock = clock_from(vector["task"])
    settings = settings_from(vector["settings"])
    now = from_isoformat(vector["now"])
    assert derived_view(clock, settings, now) == vector["expect"]


# --------------------------------------------------------------- transitions
def _decide(
    clock: TaskClock,
    decision: dict[str, Any],
    settings: OwnerClockSettings,
    now: datetime,
) -> TaskClock:
    return rules.decide(
        clock,
        decision["decision_type"],
        settings=settings,
        now=now,
        title=decision.get("title"),
        waiting_for=decision.get("waiting_for"),
        reason=decision.get("reason"),
        new_formulation_id=decision.get("new_formulation_id"),
    )


def apply_event(
    clock: TaskClock,
    settings: OwnerClockSettings,
    event: dict[str, Any],
    now: datetime,
) -> tuple[TaskClock | None, OwnerClockSettings, dict[str, Any]]:
    """Interpret one vector event; ``None`` clock means "auto-park not applied"."""

    kind = event["type"]
    extras: dict[str, Any] = {}
    result: TaskClock | None
    if kind == "create_in_next":
        result = rules.create_in_next(
            title=event["title"], formulation_id=event["new_formulation_id"], now=now
        )
    elif kind == "update_title":
        result = rules.change_title(
            clock,
            title=event["title"],
            settings=settings,
            now=now,
            new_formulation_id=event["new_formulation_id"],
        )
    elif kind == "update_due_date":
        result = rules.change_due_date(clock, due_date=day(event["due_date"]), now=now)
    elif kind == "update_other":
        result = rules.edit_without_clock(clock)
    elif kind == "transition":
        result = rules.move(
            clock,
            to_state=event["to"],
            settings=settings,
            now=now,
            new_formulation_id=event.get("new_formulation_id"),
        )
    elif kind == "decide":
        result = _decide(clock, event, settings, now)
    elif kind == "undo_decision":
        result = rules.restore(clock, clock_from(event["task_before"]))
    elif kind == "auto_park":
        result = rules.auto_park(clock, settings=settings, now=now)
    elif kind == "yield_reversal":
        result = _decide(rules.reverse_park(clock), event["decision"], settings, now)
    elif kind == "bulk_release":
        result, released = rules.release(clock, settings=settings, now=now)
        assert released is not None
        extras["bulk_clock_before"] = _released_to(released)
    elif kind == "undo_bulk_release":
        result = rules.undo_release(
            clock,
            previous_state=event["previous_state"],
            released=_released(event["clock_before"]),
        )
    elif kind == "activate":
        activated = rules.activate_owner(
            settings,
            at=from_isoformat(event["at"]),
            time_zone=event.get("time_zone"),
        )
        result = clock
        if activated is not settings:
            result = rules.activate_clock(
                clock,
                activated_at=from_isoformat(event["at"]),
                formulation_id=event["new_formulation_id"],
            )
        settings = activated
    elif kind == "repair":
        result = rules.repair_clock(
            clock, now=now, formulation_id=event["new_formulation_id"]
        )
    elif kind == "sweep_gap":
        result, settings = clock, rules.apply_sweep_gap(settings, now=now)
    elif kind == "threshold_change":
        result, settings = clock, rules.change_threshold(
            settings, to=event["to"], now=now
        )
    elif kind == "time_zone_change":
        changed = rules.change_time_zone(settings, to=event["to"])
        result = clock
        if changed is not settings:
            result = rules.raise_due_floor(clock, now=now)
        settings = changed
    else:  # pragma: no cover - a vector with an unknown event is a fixture bug
        raise AssertionError(f"unknown event {kind!r}")
    return result, settings, extras


_SPECIAL_EXPECT = {"error", "applied", "bulk_clock_before"}


def _run_transition(
    vector: dict[str, Any],
) -> tuple[TaskClock | None, OwnerClockSettings, dict[str, Any]]:
    return apply_event(
        clock_from(vector["before"]),
        settings_from(vector["settings"]),
        vector["event"],
        from_isoformat(vector["now"]),
    )


_TRANSITIONS = {vector["id"]: vector for vector in VECTORS["transitions"]}


@pytest.mark.parametrize("vector", VECTORS["transitions"], ids=_ids("transitions"))
def test_020_FR_001_transition_vector(vector: dict[str, Any]) -> None:
    """Every writer applies §3 the same way (020-FR-001, 020-FR-002, 020-FR-003,
    020-FR-005, 020-FR-009, 020-FR-012, 020-FR-016, 020-FR-039, 020-FR-046,
    020-FR-051)."""

    before = vector["before"]
    expect = vector["expect"]
    if "error" in expect:
        with pytest.raises(FormulationRuleError) as refused:
            _run_transition(vector)
        assert refused.value.reason == expect["error"]
        return

    result, settings, extras = _run_transition(vector)
    if expect.get("applied") is False:
        assert result is None
        return

    assert result is not None
    expected = {
        **before,
        **{k: v for k, v in expect.items() if k not in _SPECIAL_EXPECT},
    }
    assert clock_to(result) == expected
    if "bulk_clock_before" in expect:
        assert extras["bulk_clock_before"] == expect["bulk_clock_before"]
    expected_settings = {**vector["settings"], **vector.get("expect_settings", {})}
    assert settings_to(settings) == expected_settings
    if "expect_derived" in vector:
        derived = derived_view(result, settings, from_isoformat(vector["now"]))
        assert {key: derived[key] for key in vector["expect_derived"]} == vector[
            "expect_derived"
        ]


@pytest.mark.parametrize(
    "vector",
    [vector for vector in VECTORS["transitions"] if "follows" in vector],
    ids=lambda vector: vector["id"],
)
def test_020_FR_005_chained_transition_starts_where_its_predecessor_ended(
    vector: dict[str, Any],
) -> None:
    """A ``follows`` vector's ``before`` is its predecessor's result (020-FR-005)."""

    previous, _, _ = _run_transition(_TRANSITIONS[vector["follows"]])
    assert previous is not None
    assert clock_to(previous) == vector["before"]


# --------------------------------------------------------------- queue order
@pytest.mark.parametrize("vector", VECTORS["queue_order"], ids=_ids("queue_order"))
def test_020_FR_004_queue_order_vector(vector: dict[str, Any]) -> None:
    """The asks_for_decision aggregate, earliest-asking first (020-FR-004)."""

    tasks = [
        (task["id"], clock_from(task, task_id=task["id"])) for task in vector["tasks"]
    ]
    order = rules.decision_queue(
        tasks, settings_from(vector["settings"]), from_isoformat(vector["now"])
    )
    assert order == vector["expect"]


def test_020_FR_004_every_vector_section_is_exercised() -> None:
    """The file holds exactly the sections this module runs, none empty."""

    sections = {key for key, value in VECTORS.items() if isinstance(value, list)}
    assert VECTORS["schema"] == "brainbuddy-formulation-vectors/v1"
    assert sections == {"normalisation", "classification", "transitions", "queue_order"}
    assert all(VECTORS[section] for section in sections)
    ids = [vector["id"] for section in sections for vector in VECTORS[section]]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- drift guard
def copy_drift(canonical: Path, copy: Path) -> str | None:
    """Why ``copy`` is not a byte-identical copy of ``canonical`` (None if it is)."""

    if not copy.is_file():
        return f"{copy} is missing"
    if copy.read_bytes() != canonical.read_bytes():
        return f"{copy} differs from {canonical}"
    return None


_COPY_CASES = [
    (canonical, copy) for canonical, copies in FIXTURE_COPIES.items() for copy in copies
]


@pytest.mark.parametrize(
    ("canonical", "copy"), _COPY_CASES, ids=[copy for _, copy in _COPY_CASES]
)
def test_020_FR_004_fixture_copy_is_byte_identical(canonical: str, copy: str) -> None:
    """Every Swift and web copy equals its canonical fixture (020-FR-004 drift guard)."""

    assert copy_drift(FIXTURES / canonical, REPO_ROOT / copy) is None


def test_020_FR_004_drift_guard_rejects_an_edited_or_missing_copy(
    tmp_path: Path,
) -> None:
    """The guard fails on a deliberately edited copy and on a missing one."""

    canonical = FIXTURES / "review_formulation_vectors.json"
    identical = tmp_path / "identical.json"
    identical.write_bytes(canonical.read_bytes())
    edited = tmp_path / "edited.json"
    edited.write_bytes(canonical.read_bytes().replace(b'"asks"', b'"ageing"', 1))

    assert copy_drift(canonical, identical) is None
    assert copy_drift(canonical, edited) == f"{edited} differs from {canonical}"
    missing = tmp_path / "missing.json"
    assert copy_drift(canonical, missing) == f"{missing} is missing"
