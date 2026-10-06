"""Spec 020: unit tests of the pure formulation rule (contracts/formulation-clock.md).

The shared vectors (``test_review_formulation_vectors.py``) pin the contract's
examples; these tests pin the rule's edges directly, one second either side of
every boundary, for every allowed threshold.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.tasks import formulation as rules
from app.modules.tasks.formulation import (
    FormulationRuleError,
    OwnerClockSettings,
    TaskClock,
)

START = datetime(2026, 9, 24, 9, 14, tzinfo=UTC)
ACTIVATED = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)
DAY = timedelta(days=1)


def _settings(threshold: int = 14, **changes: object) -> OwnerClockSettings:
    base = OwnerClockSettings(
        threshold_days=threshold, time_zone="Europe/Berlin", activated_at=ACTIVATED
    )
    return replace(base, **changes)


def _clock(**changes: object) -> TaskClock:
    base = TaskClock(
        state="next",
        title="Call Bob",
        revision=3,
        formulation_id="form_a",
        formulation_started_at=START,
        formulation_extended_at=None,
        formulation_extension_reason=None,
        formulation_park_floor_at=None,
        consecutive_stalled_formulations=0,
        due_date=None,
        parked=None,
    )
    return replace(base, **changes)


# ------------------------------------------------------------ formulation key
@pytest.mark.parametrize(
    ("old", "new", "substantive"),
    [
        ("Call Bob", "call bob.", False),
        ("Follow-up with Ann", "follow up with ann", False),
        ("e-mail Ann", "email Ann", True),
        ("Straße", "STRASSE", False),
        ("Ёлка", "Елка", True),
        ("Купить хлеб", "купить  хлеб!", False),
    ],
)
def test_020_FR_002_cosmetic_title_change_keeps_formulation(
    old: str, new: str, substantive: bool
) -> None:
    """The §1 examples: case, whitespace and punctuation are cosmetic (020-FR-002)."""

    assert rules.is_substantive(old, new) is substantive


def test_020_FR_002_formulation_key_folds_case_space_and_punctuation_only() -> None:
    """NFKC, punctuation to one space, whitespace collapse, casefold (020-FR-002)."""

    assert rules.formulation_key("  «Ｃａｌｌ» BOB…  ") == "call bob"
    assert rules.formulation_key("C++ & $5 📞") == "c++ $5 📞"
    assert rules.formulation_key("İ") == "i̇"
    assert rules.formulation_key("") == ""


# ----------------------------------------------------------------- due start
@pytest.mark.parametrize(
    ("zone", "due", "expected"),
    [
        ("Europe/Berlin", date(2026, 3, 29), datetime(2026, 3, 28, 23, tzinfo=UTC)),
        ("Europe/Berlin", date(2026, 3, 30), datetime(2026, 3, 29, 22, tzinfo=UTC)),
        ("America/New_York", date(2026, 11, 2), datetime(2026, 11, 2, 5, tzinfo=UTC)),
        ("America/Santiago", date(2026, 9, 6), datetime(2026, 9, 6, 4, tzinfo=UTC)),
        ("UTC", date(2026, 10, 9), datetime(2026, 10, 9, tzinfo=UTC)),
    ],
)
def test_020_FR_046_due_start_is_the_first_instant_of_the_local_day(
    zone: str, due: date, expected: datetime
) -> None:
    """The due day starts at local midnight, or the gap's end (020-FR-046)."""

    assert rules.due_start(due, zone) == expected


# ------------------------------------------------------------- classification
_BOUNDARIES = [
    ("ageing", lambda t: timedelta(seconds=t * 86400 // 2), "fresh"),
    ("asks", lambda t: t * DAY, "ageing"),
    ("moves_tomorrow", lambda t: (t + 6) * DAY, "asks"),
    ("park_due", lambda t: (t + 7) * DAY, "moves_tomorrow"),
]


@pytest.mark.parametrize("threshold", [7, 14, 21, 28])
@pytest.mark.parametrize(("klass", "offset", "before"), _BOUNDARIES)
def test_020_FR_004_each_class_starts_exactly_at_its_boundary(
    threshold: int, klass: str, offset: object, before: str
) -> None:
    """One second before a boundary keeps the earlier class (020-FR-004, 020-FR-012)."""

    assert callable(offset)
    boundary = START + offset(threshold)
    settings = _settings(threshold)
    assert rules.classify(_clock(), settings, boundary - SECOND) == before
    assert rules.classify(_clock(), settings, boundary) == klass


def test_020_FR_012_park_due_is_threshold_plus_seven_days() -> None:
    """Without extension or floors the park is due at T + 7 (020-FR-012)."""

    instants = rules.derive_instants(_clock(), _settings())
    assert instants is not None
    assert instants.park_due_at == START + 21 * DAY
    assert instants.tomorrow_at == START + 20 * DAY
    assert instants.paused_until is None


def test_020_FR_046_paused_until_the_due_day_then_aged_from_it() -> None:
    """A future due date pauses; age counts from the due day (020-FR-046)."""

    clock = _clock(due_date=date(2026, 10, 20))
    due = datetime(2026, 10, 19, 22, tzinfo=UTC)
    settings = _settings()
    assert rules.classify(clock, settings, due - SECOND) == "paused"
    assert rules.classify(clock, settings, due) == "fresh"
    instants = rules.derive_instants(clock, settings)
    assert instants is not None
    assert instants.paused_until == due
    assert instants.ask_at == due + 14 * DAY
    assert not rules.restart_eligible(clock, settings, due - SECOND)


@pytest.mark.parametrize(
    "clock",
    [
        _clock(state="waiting"),
        _clock(formulation_started_at=None, formulation_id=None),
    ],
    ids=["outside-next", "no-clock"],
)
def test_020_FR_051_tasks_without_a_running_clock_classify_as_none(
    clock: TaskClock,
) -> None:
    """Only a started clock in Next is classified (020-FR-051)."""

    assert rules.derive_instants(clock, _settings()) is None
    assert rules.classify(clock, _settings(), START + 30 * DAY) == "none"


def test_020_FR_051_before_activation_nothing_asks_or_parks() -> None:
    """A not-activated owner sees no class and no instants (020-FR-051)."""

    settings = _settings(activated_at=None)
    late = START + 40 * DAY
    assert rules.derive_instants(_clock(), settings) is None
    assert rules.classify(_clock(), settings, late) == "none"
    assert rules.auto_park(_clock(), settings=settings, now=late) is None
    assert not rules.restart_eligible(_clock(), settings, late)
    assert not rules.third_stall(
        _clock(consecutive_stalled_formulations=5), settings, late
    )


def test_020_FR_009_extension_moves_ask_and_park_from_the_extension_day() -> None:
    """ask = max(start + T, extended) + 7 d; park = ask + 7 d (020-FR-009)."""

    extended = START + 18 * DAY
    instants = rules.derive_instants(
        _clock(formulation_extended_at=extended), _settings()
    )
    assert instants is not None
    assert instants.ask_at == START + 25 * DAY
    assert instants.park_due_at == START + 32 * DAY
    assert instants.ageing_at == START + 7 * DAY


def test_020_FR_039_floors_only_ever_postpone_the_park() -> None:
    """Task and owner floors raise park_due_at, never lower it (020-FR-039)."""

    late = START + 30 * DAY
    early = START + DAY
    for clock, settings in [
        (_clock(formulation_park_floor_at=late), _settings()),
        (_clock(), _settings(owner_park_floor_at=late)),
    ]:
        instants = rules.derive_instants(clock, settings)
        assert instants is not None
        assert instants.park_due_at == late
        assert instants.ask_at == START + 14 * DAY
    instants = rules.derive_instants(
        _clock(formulation_park_floor_at=early), _settings(owner_park_floor_at=early)
    )
    assert instants is not None
    assert instants.park_due_at == START + 21 * DAY


def test_020_FR_017_restart_eligible_from_28_days_unless_paused() -> None:
    """Restart offers tasks whose clock is at least 28 days old (020-FR-017)."""

    clock = _clock(formulation_park_floor_at=START + 60 * DAY)
    settings = _settings()
    assert not rules.restart_eligible(clock, settings, START + 28 * DAY - SECOND)
    assert rules.restart_eligible(clock, settings, START + 28 * DAY)


@pytest.mark.parametrize(
    ("stalled", "offset", "expected"),
    [(2, 14 * DAY, True), (1, 14 * DAY, False), (2, 13 * DAY, False)],
)
def test_020_FR_005_third_stall_needs_two_stalled_and_an_asking_formulation(
    stalled: int, offset: timedelta, expected: bool
) -> None:
    """The third consecutive asking formulation offers Someday (020-FR-005)."""

    clock = _clock(consecutive_stalled_formulations=stalled)
    assert rules.third_stall(clock, _settings(), START + offset) is expected


# ------------------------------------------------------------ closing a clock
@pytest.mark.parametrize(
    ("offset", "extended", "expected"),
    [
        (14 * DAY - SECOND, False, 0),
        (14 * DAY, False, 2),
        (10 * DAY, True, 2),
    ],
    ids=["before-ask", "at-ask", "extended-before-new-ask"],
)
def test_020_FR_005_closing_counts_a_stall_only_once_it_asked(
    offset: timedelta, extended: bool, expected: int
) -> None:
    """Reached asking = extended or now >= ask_at at close (020-FR-005)."""

    clock = _clock(
        consecutive_stalled_formulations=1,
        formulation_extended_at=START + 9 * DAY if extended else None,
        formulation_extension_reason="Quote pending" if extended else None,
    )
    closed = rules.close_formulation(clock, settings=_settings(), now=START + offset)
    assert closed.consecutive_stalled_formulations == expected
    assert closed.formulation_id is None
    assert closed.formulation_started_at is None
    assert closed.formulation_extended_at is None
    assert closed.formulation_extension_reason is None
    assert closed.formulation_park_floor_at is None
    assert closed.revision == clock.revision


def test_020_FR_005_closing_an_unstarted_clock_keeps_the_count() -> None:
    """A clock that never started neither stalls nor resets (020-FR-005)."""

    clock = _clock(
        formulation_id=None,
        formulation_started_at=None,
        consecutive_stalled_formulations=2,
    )
    closed = rules.close_formulation(clock, settings=_settings(), now=START)
    assert closed.consecutive_stalled_formulations == 2


def test_020_FR_001_start_formulation_clears_extension_floor_and_park() -> None:
    """A new formulation starts clean, keeping the stalled count (020-FR-001)."""

    clock = _clock(
        formulation_extended_at=START,
        formulation_extension_reason="x",
        formulation_park_floor_at=START + 30 * DAY,
        consecutive_stalled_formulations=2,
    )
    started = rules.start_formulation(clock, formulation_id="form_new", now=START + DAY)
    assert started.formulation_id == "form_new"
    assert started.formulation_started_at == START + DAY
    assert started.formulation_extended_at is None
    assert started.formulation_extension_reason is None
    assert started.formulation_park_floor_at is None
    assert started.parked is None
    assert started.consecutive_stalled_formulations == 2


def test_020_FR_001_moving_into_next_needs_a_formulation_id() -> None:
    """Every start names its formulation id, so replay is deterministic."""

    with pytest.raises(ValueError, match="new_formulation_id"):
        rules.move(
            _clock(state="inbox", formulation_id=None, formulation_started_at=None),
            to_state="next",
            settings=_settings(),
            now=START,
        )


# ---------------------------------------------------------------- decisions
def test_020_FR_009_extension_refusals_are_checked_in_order() -> None:
    """Not in Next, then already used, then not due (020-FR-009)."""

    asking = START + 15 * DAY
    cases = [
        (_clock(state="waiting"), "decision_not_allowed"),
        (
            _clock(
                formulation_extended_at=START + 2 * DAY,
                formulation_extension_reason="x",
            ),
            "extension_already_used",
        ),
        (_clock(), None),
    ]
    for clock, reason in cases:
        if reason is None:
            extended = rules.extend(
                clock, reason="Quote", settings=_settings(), now=asking
            )
            assert extended.formulation_extended_at == asking
            assert extended.revision == clock.revision + 1
            continue
        with pytest.raises(FormulationRuleError) as refused:
            rules.extend(clock, reason="Quote", settings=_settings(), now=asking)
        assert refused.value.reason == reason
    with pytest.raises(FormulationRuleError) as early:
        rules.extend(_clock(), reason="Quote", settings=_settings(), now=START + DAY)
    assert early.value.reason == "extension_not_due"


@pytest.mark.parametrize(
    ("state", "decision_type", "allowed"),
    [
        ("next", "keep_waiting", False),
        ("waiting", "keep_waiting", True),
        ("waiting", "follow_up", True),
        ("someday", "keep_someday", True),
        ("next", "keep_someday", False),
        ("inbox", "complete", True),
        ("completed", "cancel", False),
        ("someday", "first_step", False),
    ],
)
def test_020_FR_006_decision_types_follow_the_state_table(
    state: str, decision_type: str, allowed: bool
) -> None:
    """Decisions outside their list are refused; keeps change nothing (020-FR-006)."""

    clock = _clock(state=state, formulation_id=None, formulation_started_at=None)
    if not allowed:
        with pytest.raises(FormulationRuleError) as refused:
            rules.decide(clock, decision_type, settings=_settings(), now=START)
        assert refused.value.reason == "decision_not_allowed"
        return
    decided = rules.decide(
        clock, decision_type, settings=_settings(), now=START, title="Next step"
    )
    if decision_type in {"keep_waiting", "keep_someday", "follow_up"}:
        assert decided == clock
    else:
        assert decided.state == "completed"
        assert decided.revision == clock.revision + 1


def test_020_FR_012_auto_park_snapshots_the_clock_and_reversal_restores_it() -> None:
    """Park keeps clock_before; the yield reversal puts it back exactly."""

    clock = _clock(
        formulation_park_floor_at=START + 10 * DAY,
        consecutive_stalled_formulations=1,
    )
    due = START + 21 * DAY
    assert rules.auto_park(clock, settings=_settings(), now=due - SECOND) is None
    parked = rules.auto_park(clock, settings=_settings(), now=due)
    assert parked is not None
    assert parked.state == "someday"
    assert parked.revision == 4
    assert parked.consecutive_stalled_formulations == 2
    assert parked.parked is not None
    assert parked.parked.from_revision == 3
    assert parked.parked.clock_before.stalled_before == 1
    reversed_ = rules.reverse_park(parked)
    assert reversed_ == replace(clock, revision=4)
    with pytest.raises(ValueError, match="not parked"):
        rules.reverse_park(clock)


# ------------------------------------------------------------- owner settings
@pytest.mark.parametrize("threshold", [0, 6, 10, 30])
def test_020_FR_039_only_the_four_thresholds_are_valid(threshold: int) -> None:
    """Threshold is one of 7, 14, 21 or 28 days (020-FR-039)."""

    with pytest.raises(ValueError, match="threshold"):
        OwnerClockSettings(threshold_days=threshold, time_zone="UTC")
    with pytest.raises(ValueError, match="threshold"):
        rules.change_threshold(_settings(), to=threshold, now=START)


def test_020_FR_046_an_unknown_time_zone_is_refused() -> None:
    """The stored zone is an IANA name (020-FR-046)."""

    with pytest.raises(ValueError, match="time zone"):
        OwnerClockSettings(threshold_days=14, time_zone="Mars/Olympus_Mons")
    with pytest.raises(ValueError, match="time zone"):
        rules.change_time_zone(_settings(), to="Not/AZone")


def test_020_FR_039_threshold_change_floors_parks_for_seven_days() -> None:
    """A real change sets owner_park_floor_at = now + 7 d; the same value nothing."""

    settings = _settings()
    assert rules.change_threshold(settings, to=14, now=START) is settings
    changed = rules.change_threshold(settings, to=7, now=START)
    assert changed.threshold_days == 7
    assert changed.owner_park_floor_at == START + 7 * DAY


def test_020_FR_016_activation_is_first_wins_and_clamps_clocks() -> None:
    """The first activation sets the instant; clocks clamp to it (020-FR-016)."""

    settings = _settings(activated_at=None)
    at = START + 5 * DAY
    activated = rules.activate_owner(settings, at=at, time_zone="Pacific/Honolulu")
    assert activated.activated_at == at
    assert activated.time_zone == "Pacific/Honolulu"
    assert rules.activate_owner(activated, at=at + DAY) is activated
    clamped = rules.activate_clock(_clock(), activated_at=at, formulation_id="form_x")
    assert clamped.formulation_id == "form_a"
    assert clamped.formulation_started_at == at
    assert clamped.formulation_park_floor_at == at + 14 * DAY
    assert clamped.revision == 3


def test_020_FR_004_decision_queue_breaks_ties_by_start_then_id() -> None:
    """Equal ask_at sorts by formulation start, then task id (020-FR-004)."""

    now = START + 15 * DAY
    due_day_start = datetime(2026, 9, 23, 22, tzinfo=UTC)
    tasks = [
        ("task_b", _clock()),
        ("task_a", _clock()),
        ("task_p", _clock(formulation_started_at=due_day_start)),
        (
            "task_q",
            _clock(
                formulation_started_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
                due_date=date(2026, 9, 24),
            ),
        ),
        ("task_z", _clock(state="waiting")),
    ]
    order = rules.decision_queue(tasks, _settings(), now)
    assert order == ["task_q", "task_p", "task_a", "task_b"]


def test_020_FR_003_a_move_to_the_same_list_keeps_the_clock() -> None:
    """Re-saving the list a task is already in restarts nothing (020-FR-003)."""

    moved = rules.move(_clock(), to_state="next", settings=_settings(), now=START)
    assert moved == replace(_clock(), revision=4)


def test_020_FR_001_return_to_next_starts_a_formulation_with_the_new_title() -> None:
    """Returning from Waiting or Someday starts a new clock (020-FR-001)."""

    waiting = _clock(state="waiting", formulation_id=None, formulation_started_at=None)
    returned = rules.decide(
        waiting,
        "return_to_next",
        settings=_settings(),
        now=START,
        title="Call Bob about the quote",
        new_formulation_id="form_back",
    )
    assert returned.state == "next"
    assert returned.title == "Call Bob about the quote"
    assert returned.formulation_id == "form_back"
    assert returned.formulation_started_at == START


@pytest.mark.parametrize(
    ("decision_type", "missing"),
    [("reformulate", "title"), ("first_step", "new_formulation_id")],
)
def test_020_FR_002_a_decision_without_its_fields_is_a_programming_error(
    decision_type: str, missing: str
) -> None:
    """The schema refuses these with 422; the rule refuses them too."""

    fields = {"title": "Email Bob", "new_formulation_id": "form_b"}
    fields.pop(missing)
    with pytest.raises(ValueError, match=missing):
        rules.decide(_clock(), decision_type, settings=_settings(), now=START, **fields)


def test_020_FR_017_an_inbox_remainder_release_has_no_clock_to_store() -> None:
    """Inbox tasks have no clock; undo puts them back in Inbox unchanged."""

    inbox = _clock(state="inbox", formulation_id=None, formulation_started_at=None)
    released, snapshot = rules.release(inbox, settings=_settings(), now=START)
    assert snapshot is None
    assert released.state == "someday"
    assert released.revision == 4
    undone = rules.undo_release(released, previous_state="inbox", released=None)
    assert undone == replace(inbox, revision=5)
