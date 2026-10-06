"""Pure formulation-clock rule (spec 020, contracts/formulation-clock.md).

Normative for the backend; the iOS core (``Formulation.swift``) and the web
(``formulation.ts``) implement the same rule and run the same vector file
(``tests/fixtures/review_formulation_vectors.json``, §6). Everything here is a
pure function of its arguments: no I/O, no clock of its own, no storage types.
Every instant is an aware UTC ``datetime``; "days" are exact 86 400-second
spans, and only the start of a due day uses the owner's local calendar (§4).

Transition helpers return a new ``TaskClock``. The ones that are a normal task
write bump ``revision``; the clock-bookkeeping ones (activation clamp, repair,
sweep-gap floor, time-zone floor) never do (§2 "Revision rule").
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FormulationClass = Literal[
    "none", "paused", "park_due", "moves_tomorrow", "asks", "ageing", "fresh"
]
DecisionType = Literal[
    "complete",
    "reformulate",
    "first_step",
    "waiting",
    "someday",
    "cancel",
    "extend",
    "keep_waiting",
    "follow_up",
    "return_to_next",
    "keep_someday",
]

ALLOWED_THRESHOLD_DAYS: frozenset[int] = frozenset({7, 14, 21, 28})
ASKS_FOR_DECISION: frozenset[str] = frozenset({"asks", "moves_tomorrow", "park_due"})
"""The one "asks for a decision" aggregate of §5 (FR-004)."""

EXTENDABLE: frozenset[str] = ASKS_FOR_DECISION
PUNCTUATION_CATEGORIES: frozenset[str] = frozenset(
    {"Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po"}
)

DAY = timedelta(days=1)
PARK_AFTER_ASK = 7 * DAY
EXTENSION = 7 * DAY
MOVES_TOMORROW_WINDOW = DAY
DUE_DATE_FLOOR = 7 * DAY
THRESHOLD_CHANGE_FLOOR = 7 * DAY
SWEEP_GAP_FLOOR = 7 * DAY
ACTIVATION_GRACE = 14 * DAY
REPAIR_GRACE = 14 * DAY
RESTART_AGE = 28 * DAY
STALLS_BEFORE_THIRD = 2

_OPEN_STATES = frozenset({"inbox", "next", "waiting", "someday"})
_DECISION_STATES: dict[str, frozenset[str]] = {
    "complete": _OPEN_STATES,
    "cancel": _OPEN_STATES,
    "reformulate": frozenset({"next"}),
    "first_step": frozenset({"next"}),
    "waiting": frozenset({"next"}),
    "someday": frozenset({"next"}),
    "extend": frozenset({"next"}),
    "keep_waiting": frozenset({"waiting"}),
    "follow_up": frozenset({"waiting"}),
    "return_to_next": frozenset({"waiting", "someday"}),
    "keep_someday": frozenset({"someday"}),
}
_DECISION_MOVES: dict[str, str] = {
    "complete": "completed",
    "cancel": "cancelled",
    "waiting": "waiting",
    "someday": "someday",
    "return_to_next": "next",
}
assert set(_DECISION_STATES) == set(get_args(DecisionType))


class FormulationRuleError(ValueError):
    """A decision the rule refuses; ``reason`` is the HTTP ``detail.reason``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {name!r}") from exc


def _check_threshold(days: int) -> None:
    if days not in ALLOWED_THRESHOLD_DAYS:
        raise ValueError(f"threshold must be one of 7, 14, 21, 28 days, not {days}")


@dataclass(frozen=True, slots=True)
class OwnerClockSettings:
    """Owner-level inputs of the rule (§2), a projection of ``review_settings``."""

    threshold_days: int
    time_zone: str
    owner_park_floor_at: datetime | None = None
    activated_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_threshold(self.threshold_days)
        _zone(self.time_zone)


@dataclass(frozen=True, slots=True)
class ClockBefore:
    """The clock immediately before an auto-park closed it (``parked.clock_before``)."""

    started_at: datetime
    extended_at: datetime | None
    extension_reason: str | None
    park_floor_at: datetime | None
    stalled_before: int


@dataclass(frozen=True, slots=True)
class ParkMarker:
    """``TaskDocument.parked``: written only by auto-park."""

    at: datetime
    formulation_id: str
    from_revision: int
    clock_before: ClockBefore


@dataclass(frozen=True, slots=True)
class ReleasedClock:
    """A Next task's clock as a bulk-release record stores it (data-model E7)."""

    formulation_id: str
    started_at: datetime
    extended_at: datetime | None
    extension_reason: str | None
    park_floor_at: datetime | None
    stalled_before: int


@dataclass(frozen=True, slots=True)
class TaskClock:
    """The fields of a task the rule reads and writes (§2 plus state and title)."""

    state: str | None
    title: str | None
    revision: int
    formulation_id: str | None
    formulation_started_at: datetime | None
    formulation_extended_at: datetime | None
    formulation_extension_reason: str | None
    formulation_park_floor_at: datetime | None
    consecutive_stalled_formulations: int
    due_date: date | None
    parked: ParkMarker | None


@dataclass(frozen=True, slots=True)
class DerivedInstants:
    """§4 instants; ``start`` is the effective start (due day included)."""

    start: datetime
    ageing_at: datetime
    ask_at: datetime
    park_due_at: datetime
    tomorrow_at: datetime
    paused_until: datetime | None


# --------------------------------------------------------------------- §1 key
def formulation_key(title: str) -> str:
    """NFKC, punctuation to one space, whitespace collapse, full case folding.

    A sibling of ``repository.normalize_task_name`` with the one extra
    punctuation step (§1); symbols, digits, letters, marks and emoji are kept.
    """

    normalized = unicodedata.normalize("NFKC", title)
    spaced = "".join(
        " " if unicodedata.category(char) in PUNCTUATION_CATEGORIES else char
        for char in normalized
    )
    return " ".join(spaced.split()).casefold()


def is_substantive(old_title: str, new_title: str) -> bool:
    """A title change is substantive iff the formulation keys differ (FR-002)."""

    return formulation_key(old_title) != formulation_key(new_title)


# ---------------------------------------------------------- §4 derived instants
def due_start(due_date: date, time_zone: str) -> datetime:
    """The first instant of ``due_date`` in ``time_zone``, as UTC.

    A local midnight inside a DST gap resolves to the instant the day actually
    starts (the end of the gap).
    """

    local = datetime(
        due_date.year, due_date.month, due_date.day, tzinfo=_zone(time_zone)
    )
    return local.astimezone(UTC)


def derive_instants(
    clock: TaskClock, settings: OwnerClockSettings
) -> DerivedInstants | None:
    """§4 for a started clock in Next of an activated owner, else ``None``.

    ``paused_until = due_start`` if ``due_start > formulation_started_at``,
    else null; the class is ``paused`` iff ``paused_until`` is set and
    ``now < paused_until`` (``classify_instants``).
    """

    started = clock.formulation_started_at
    if settings.activated_at is None or clock.state != "next" or started is None:
        return None
    start = started
    paused_until = None
    if clock.due_date is not None:
        due = due_start(clock.due_date, settings.time_zone)
        if due > start:
            start = due
            paused_until = due
    threshold = timedelta(days=settings.threshold_days)
    ask_at = start + threshold
    if clock.formulation_extended_at is not None:
        ask_at = max(ask_at, clock.formulation_extended_at) + EXTENSION
    park_due_at = max(
        instant
        for instant in (
            ask_at + PARK_AFTER_ASK,
            clock.formulation_park_floor_at,
            settings.owner_park_floor_at,
        )
        if instant is not None
    )
    return DerivedInstants(
        start=start,
        ageing_at=start + threshold / 2,
        ask_at=ask_at,
        park_due_at=park_due_at,
        tomorrow_at=park_due_at - MOVES_TOMORROW_WINDOW,
        paused_until=paused_until,
    )


# ----------------------------------------------------------- §5 classification
def classify_instants(
    instants: DerivedInstants | None, now: datetime
) -> FormulationClass:
    """§5 from the derived instants alone (the web's ``classifyFromInstants``)."""

    if instants is None:
        return "none"
    if instants.paused_until is not None and now < instants.paused_until:
        return "paused"
    if now >= instants.park_due_at:
        return "park_due"
    if now >= instants.tomorrow_at:
        return "moves_tomorrow"
    if now >= instants.ask_at:
        return "asks"
    if now >= instants.ageing_at:
        return "ageing"
    return "fresh"


def classify(
    clock: TaskClock, settings: OwnerClockSettings, now: datetime
) -> FormulationClass:
    return classify_instants(derive_instants(clock, settings), now)


def asks_for_decision(klass: str) -> bool:
    return klass in ASKS_FOR_DECISION


def restart_eligible(
    clock: TaskClock, settings: OwnerClockSettings, now: datetime
) -> bool:
    """FR-017: not paused and at least 28 days since the effective start."""

    instants = derive_instants(clock, settings)
    klass = classify_instants(instants, now)
    if instants is None or klass == "paused":
        return False
    return now - instants.start >= RESTART_AGE


def third_stall(clock: TaskClock, settings: OwnerClockSettings, now: datetime) -> bool:
    """FR-005: asking with at least two stalled formulations before this one."""

    return (
        asks_for_decision(classify(clock, settings, now))
        and clock.consecutive_stalled_formulations >= STALLS_BEFORE_THIRD
    )


def decision_queue(
    tasks: Iterable[tuple[str, TaskClock]], settings: OwnerClockSettings, now: datetime
) -> list[str]:
    """Ids of the tasks that ask for a decision, earliest-asking first (§5).

    Order: ascending ``ask_at``, then ascending ``formulation_started_at``,
    then task id.
    """

    asking: list[tuple[datetime, datetime, str]] = []
    for task_id, clock in tasks:
        instants = derive_instants(clock, settings)
        if instants is None or not asks_for_decision(classify_instants(instants, now)):
            continue
        started = clock.formulation_started_at
        assert started is not None
        asking.append((instants.ask_at, started, task_id))
    return [task_id for _, _, task_id in sorted(asking)]


# -------------------------------------------------------------- §3 transitions
def start_formulation(
    clock: TaskClock, *, formulation_id: str, now: datetime
) -> TaskClock:
    """A new formulation at ``now``; extension, floor and park cleared."""

    return replace(
        clock,
        formulation_id=formulation_id,
        formulation_started_at=now,
        formulation_extended_at=None,
        formulation_extension_reason=None,
        formulation_park_floor_at=None,
        parked=None,
    )


def close_formulation(
    clock: TaskClock, *, settings: OwnerClockSettings, now: datetime
) -> TaskClock:
    """Close the current formulation with the FR-005 stalled-count rule.

    It reached "asks for a decision" iff it was extended (only possible once it
    asked) or ``now >= ask_at``; then the count goes up by one, otherwise it
    resets to 0. A clock that never started leaves the count alone.
    """

    stalled = clock.consecutive_stalled_formulations
    if clock.formulation_started_at is not None:
        instants = derive_instants(replace(clock, state="next"), settings)
        reached = clock.formulation_extended_at is not None or (
            instants is not None and now >= instants.ask_at
        )
        stalled = stalled + 1 if reached else 0
    return replace(
        clock,
        formulation_id=None,
        formulation_started_at=None,
        formulation_extended_at=None,
        formulation_extension_reason=None,
        formulation_park_floor_at=None,
        consecutive_stalled_formulations=stalled,
    )


def _bump(clock: TaskClock) -> TaskClock:
    return replace(clock, revision=clock.revision + 1)


def create_in_next(*, title: str, formulation_id: str, now: datetime) -> TaskClock:
    """A task created in Next starts its first formulation (revision 1)."""

    return TaskClock(
        state="next",
        title=title,
        revision=1,
        formulation_id=formulation_id,
        formulation_started_at=now,
        formulation_extended_at=None,
        formulation_extension_reason=None,
        formulation_park_floor_at=None,
        consecutive_stalled_formulations=0,
        due_date=None,
        parked=None,
    )


def change_title(
    clock: TaskClock,
    *,
    title: str,
    settings: OwnerClockSettings,
    now: datetime,
    new_formulation_id: str,
) -> TaskClock:
    """Title edit: a substantive change in Next closes and restarts the clock."""

    changed = clock
    if clock.state == "next" and is_substantive(clock.title or "", title):
        changed = close_formulation(clock, settings=settings, now=now)
        changed = start_formulation(changed, formulation_id=new_formulation_id, now=now)
    return _bump(replace(changed, title=title))


def change_due_date(
    clock: TaskClock, *, due_date: date | None, now: datetime
) -> TaskClock:
    """Due date set, moved or removed: in Next the task floor rises (FR-046)."""

    changed = replace(clock, due_date=due_date)
    if clock.state == "next":
        changed = _raise_task_floor(changed, now + DUE_DATE_FLOOR)
    return _bump(changed)


def edit_without_clock(clock: TaskClock) -> TaskClock:
    """Notes, tags, project, priority, subtasks, comments, waiting-for (FR-003)."""

    return _bump(clock)


def _raise_task_floor(clock: TaskClock, floor: datetime) -> TaskClock:
    existing = clock.formulation_park_floor_at
    return replace(
        clock,
        formulation_park_floor_at=floor if existing is None else max(existing, floor),
    )


def _relocate(
    clock: TaskClock,
    *,
    to_state: str,
    settings: OwnerClockSettings,
    now: datetime,
    new_formulation_id: str | None,
) -> TaskClock:
    """Move between lists without bumping the revision."""

    if to_state == clock.state:
        return clock
    changed = clock
    if clock.state == "next":
        changed = close_formulation(changed, settings=settings, now=now)
    if clock.state == "someday":
        changed = replace(changed, parked=None)
    if to_state == "next":
        if new_formulation_id is None:
            raise ValueError("moving into Next needs a new_formulation_id")
        changed = start_formulation(changed, formulation_id=new_formulation_id, now=now)
    return replace(changed, state=to_state)


def move(
    clock: TaskClock,
    *,
    to_state: str,
    settings: OwnerClockSettings,
    now: datetime,
    new_formulation_id: str | None = None,
) -> TaskClock:
    """A move, reopen, completion or cancellation (one task write)."""

    return _bump(
        _relocate(
            clock,
            to_state=to_state,
            settings=settings,
            now=now,
            new_formulation_id=new_formulation_id,
        )
    )


def extend(
    clock: TaskClock, *, reason: str, settings: OwnerClockSettings, now: datetime
) -> TaskClock:
    """The one-time "keep 7 more days" (FR-009), checked in a fixed order."""

    if clock.state != "next":
        raise FormulationRuleError("decision_not_allowed")
    if clock.formulation_extended_at is not None:
        raise FormulationRuleError("extension_already_used")
    if classify(clock, settings, now) not in EXTENDABLE:
        raise FormulationRuleError("extension_not_due")
    return _bump(
        replace(
            clock,
            formulation_extended_at=now,
            formulation_extension_reason=reason,
        )
    )


def first_step(
    clock: TaskClock,
    *,
    title: str,
    settings: OwnerClockSettings,
    now: datetime,
    new_formulation_id: str,
) -> TaskClock:
    """ "Find a first step" always starts a new formulation (FR-008)."""

    closed = close_formulation(clock, settings=settings, now=now)
    started = start_formulation(closed, formulation_id=new_formulation_id, now=now)
    return _bump(replace(started, title=title))


def decide(  # noqa: PLR0913 - one keyword per decision field of http §3
    clock: TaskClock,
    decision_type: str,
    *,
    settings: OwnerClockSettings,
    now: datetime,
    title: str | None = None,
    waiting_for: str | None = None,
    reason: str | None = None,
    new_formulation_id: str | None = None,
) -> TaskClock:
    """The clock effect of a decision of the http §3 type table.

    ``keep_waiting``, ``keep_someday`` and ``follow_up`` leave the decided task
    unchanged (they write a receipt or create another task). ``waiting_for``
    is accepted for symmetry; it is not a clock field.
    """

    del waiting_for
    allowed = _DECISION_STATES.get(decision_type)
    if allowed is None or clock.state not in allowed:
        raise FormulationRuleError("decision_not_allowed")
    if decision_type == "extend":
        return extend(clock, reason=reason or "", settings=settings, now=now)
    if decision_type == "reformulate":
        return change_title(
            clock,
            title=_required(title, "title"),
            settings=settings,
            now=now,
            new_formulation_id=_required(new_formulation_id, "new_formulation_id"),
        )
    if decision_type == "first_step":
        return first_step(
            clock,
            title=_required(title, "title"),
            settings=settings,
            now=now,
            new_formulation_id=_required(new_formulation_id, "new_formulation_id"),
        )
    target = _DECISION_MOVES.get(decision_type)
    if target is None:
        return clock
    moved = move(
        clock,
        to_state=target,
        settings=settings,
        now=now,
        new_formulation_id=new_formulation_id,
    )
    if decision_type == "return_to_next" and title is not None:
        moved = replace(moved, title=title)
    return moved


def _required(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"this decision needs {name}")
    return value


def auto_park(
    clock: TaskClock, *, settings: OwnerClockSettings, now: datetime
) -> TaskClock | None:
    """Park a task whose own evaluation is ``park_due``; ``None`` if not due.

    The clock is captured in ``parked.clock_before`` before it is closed, so a
    yield reversal can restore it without closing the formulation twice.
    """

    if classify(clock, settings, now) != "park_due":
        return None
    started = clock.formulation_started_at
    formulation_id = clock.formulation_id
    assert started is not None and formulation_id is not None
    marker = ParkMarker(
        at=now,
        formulation_id=formulation_id,
        from_revision=clock.revision,
        clock_before=ClockBefore(
            started_at=started,
            extended_at=clock.formulation_extended_at,
            extension_reason=clock.formulation_extension_reason,
            park_floor_at=clock.formulation_park_floor_at,
            stalled_before=clock.consecutive_stalled_formulations,
        ),
    )
    closed = close_formulation(clock, settings=settings, now=now)
    return _bump(replace(closed, state="someday", parked=marker))


def reverse_park(clock: TaskClock) -> TaskClock:
    """Yield reversal: restore ``clock_before`` exactly (no revision bump).

    The yielding decision is applied to the result and bumps the revision.
    """

    marker = clock.parked
    if marker is None:
        raise ValueError("the task is not parked")
    before = marker.clock_before
    return replace(
        clock,
        state="next",
        formulation_id=marker.formulation_id,
        formulation_started_at=before.started_at,
        formulation_extended_at=before.extended_at,
        formulation_extension_reason=before.extension_reason,
        formulation_park_floor_at=before.park_floor_at,
        consecutive_stalled_formulations=before.stalled_before,
        parked=None,
    )


def release(
    clock: TaskClock, *, settings: OwnerClockSettings, now: datetime
) -> tuple[TaskClock, ReleasedClock | None]:
    """A person's release to Someday (restart or Inbox-remainder bulk release).

    Returns the released task and, for a Next task with a clock, the clock the
    bulk-release record stores so its Undo restores it exactly.
    """

    snapshot = None
    started = clock.formulation_started_at
    if clock.state == "next" and started is not None and clock.formulation_id:
        snapshot = ReleasedClock(
            formulation_id=clock.formulation_id,
            started_at=started,
            extended_at=clock.formulation_extended_at,
            extension_reason=clock.formulation_extension_reason,
            park_floor_at=clock.formulation_park_floor_at,
            stalled_before=clock.consecutive_stalled_formulations,
        )
    released = _relocate(
        clock, to_state="someday", settings=settings, now=now, new_formulation_id=None
    )
    return _bump(replace(released, parked=None)), snapshot


def undo_release(
    clock: TaskClock, *, previous_state: str, released: ReleasedClock | None
) -> TaskClock:
    """Return a released task to its list with its stored clock, exactly."""

    restored = replace(clock, state=previous_state, parked=None)
    if released is not None:
        restored = replace(
            restored,
            formulation_id=released.formulation_id,
            formulation_started_at=released.started_at,
            formulation_extended_at=released.extended_at,
            formulation_extension_reason=released.extension_reason,
            formulation_park_floor_at=released.park_floor_at,
            consecutive_stalled_formulations=released.stalled_before,
        )
    return _bump(restored)


def restore(clock: TaskClock, snapshot: TaskClock) -> TaskClock:
    """Decision Undo: the snapshot field for field, at ``revision + 1`` (FR-048)."""

    return replace(snapshot, revision=clock.revision + 1)


# ------------------------------------------------- clock bookkeeping (no bump)
def activate_clock(
    clock: TaskClock, *, activated_at: datetime, formulation_id: str
) -> TaskClock:
    """The activation clamp for one task (FR-016); never bumps the revision."""

    if clock.state != "next":
        return clock
    started = clock.formulation_started_at
    if started is None:
        changed = start_formulation(
            clock, formulation_id=formulation_id, now=activated_at
        )
    else:
        changed = replace(clock, formulation_started_at=max(started, activated_at))
    return _raise_task_floor(changed, activated_at + ACTIVATION_GRACE)


def repair_clock(clock: TaskClock, *, now: datetime, formulation_id: str) -> TaskClock:
    """Start a missing clock on a Next task (old-client save, rollback)."""

    if clock.state != "next" or clock.formulation_started_at is not None:
        return clock
    started = start_formulation(clock, formulation_id=formulation_id, now=now)
    return replace(started, formulation_park_floor_at=now + REPAIR_GRACE)


def raise_due_floor(clock: TaskClock, *, now: datetime) -> TaskClock:
    """Time-zone change: a due-dated Next task cannot park within 7 days."""

    if clock.state != "next" or clock.due_date is None:
        return clock
    return _raise_task_floor(clock, now + DUE_DATE_FLOOR)


# ---------------------------------------------------------- owner settings
def activate_owner(
    settings: OwnerClockSettings, *, at: datetime, time_zone: str | None = None
) -> OwnerClockSettings:
    """First acknowledgement wins; a later one returns ``settings`` unchanged."""

    if settings.activated_at is not None:
        return settings
    return replace(
        settings,
        activated_at=at,
        time_zone=settings.time_zone if time_zone is None else time_zone,
    )


def _raise_owner_floor(
    settings: OwnerClockSettings, floor: datetime
) -> OwnerClockSettings:
    existing = settings.owner_park_floor_at
    return replace(
        settings,
        owner_park_floor_at=floor if existing is None else max(existing, floor),
    )


def apply_sweep_gap(
    settings: OwnerClockSettings, *, now: datetime
) -> OwnerClockSettings:
    """After a sweep gap of 24 h or more, no park within 7 days (SC-006)."""

    return _raise_owner_floor(settings, now + SWEEP_GAP_FLOOR)


def change_threshold(
    settings: OwnerClockSettings, *, to: int, now: datetime
) -> OwnerClockSettings:
    """FR-039: a real change floors every park for 7 days; equal is no change."""

    _check_threshold(to)
    if to == settings.threshold_days:
        return settings
    return _raise_owner_floor(
        replace(settings, threshold_days=to), now + THRESHOLD_CHANGE_FLOOR
    )


def change_time_zone(settings: OwnerClockSettings, *, to: str) -> OwnerClockSettings:
    """A zone equal to the stored one is no change (returns ``settings``)."""

    _zone(to)
    if to == settings.time_zone:
        return settings
    return replace(settings, time_zone=to)
