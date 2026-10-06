"""Pure review-flow rules (spec 020; no I/O, no clock of its own).

Executed by ``tests/fixtures/review_flow_vectors.json``, which the iOS core and
the web run as well; the guided-review service (slice PR-11) is built on these
functions. Instants are aware UTC ``datetime`` values; "days" are exact
86 400-second spans; calendar days are local ``date`` values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from .formulation import decision_queue, formulation_key

__all__ = [
    "ActiveTimeAccumulator",
    "CapacityMirror",
    "Receipt",
    "ReviewTask",
    "SessionSummary",
    "SomedayQueue",
    "StepProgress",
    "capacity_mirror",
    "decision_queue",
    "drop_duplicate_proposals",
    "ended_status",
    "idle_close_due",
    "is_counted",
    "last_counted_review_at",
    "next_review_at",
    "qualifying_activity",
    "restart_mode",
    "review_steps",
    "show_while_away",
    "someday_queue",
    "stall_recommendation",
    "waiting_queue",
    "wins",
]

StepCode = Literal[
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
ReviewStatus = Literal["open", "completed", "completed_empty", "partial", "abandoned"]
SessionEnd = Literal["finish", "replace", "idle_close"]

QUICK_STEPS: tuple[StepCode, ...] = ("wins", "inbox", "decisions", "summary")
FULL_STEPS: tuple[StepCode, ...] = (
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
)

WINS_WINDOW = timedelta(days=7)
CAPACITY_WEEKS = 4
WEEK = timedelta(days=7)
WAITING_AGE = timedelta(days=7)
RECENT_PARK = timedelta(days=30)
SOMEDAY_SHOWN = 7
RESTART_AFTER = timedelta(days=21)
IDLE_CLOSE_AFTER = timedelta(days=7)
NOTIFICATION_SKIP = timedelta(days=6)
ACTIVE_GAP_LIMIT = timedelta(minutes=2)

_COUNTED_STATUSES = frozenset({"completed", "partial"})
_STALL_RECOMMENDATION: dict[str, str] = {
    "unclear": "reformulate",
    "too_big": "first_step",
    "missing_info": "first_step",
    "no_energy": "first_step",
    "waiting_on_someone": "waiting",
    "no_longer_matters": "cancel",
}


@dataclass(frozen=True, slots=True)
class ReviewTask:
    """The task fields the review queues read (ids, states, instants only)."""

    id: str
    state: str
    revision: int = 1
    completed_at: datetime | None = None
    waiting_since: datetime | None = None
    updated_at: datetime | None = None
    parked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Receipt:
    """A review receipt (data-model E5)."""

    task_id: str
    kind: str
    task_revision: int
    reviewed_at: datetime
    hidden_until: datetime
    source: str

    def hides(self, task: ReviewTask, now: datetime) -> bool:
        """Hidden while not expired and the task is unchanged since."""

        return now < self.hidden_until and task.revision == self.task_revision


@dataclass(frozen=True, slots=True)
class StepProgress:
    status: str
    finished_empty: bool = False


@dataclass(frozen=True, slots=True)
class SessionSummary:
    status: str
    qualifying_activity: bool
    last_activity_at: datetime
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CapacityMirror:
    next_count: int
    weeks_of_history: int
    weekly_average_4w: float | None
    implied_weeks: float | None


@dataclass(frozen=True, slots=True)
class SomedayQueue:
    eligible_total: int
    shown: list[str]


def review_steps(mode: str) -> tuple[StepCode, ...]:
    """FR-028: quick = wins, Inbox, decisions, summary; full = all ten steps."""

    if mode == "quick":
        return QUICK_STEPS
    if mode == "full":
        return FULL_STEPS
    raise ValueError(f"unknown review mode {mode!r}")


def wins(tasks: Iterable[ReviewTask], now: datetime) -> list[str]:
    """Tasks completed in the last 7 days, most recent first, then id."""

    since = now - WINS_WINDOW
    done = [
        (task.completed_at, task.id)
        for task in tasks
        if task.state == "completed"
        and task.completed_at is not None
        and since <= task.completed_at <= now
    ]
    done.sort(key=lambda item: (-item[0].timestamp(), item[1]))
    return [task_id for _, task_id in done]


def capacity_mirror(
    next_count: int, completed_at: Sequence[datetime], now: datetime
) -> CapacityMirror:
    """FR-031: the pace needs 4 full weeks since the first completion and at
    least one completion in the last 4 weeks; otherwise only the Next count."""

    weeks = 0
    if completed_at:
        weeks = int((now - min(completed_at)) // WEEK)
    window_start = now - CAPACITY_WEEKS * WEEK
    recent = sum(1 for instant in completed_at if window_start <= instant <= now)
    if weeks < CAPACITY_WEEKS or recent == 0:
        return CapacityMirror(next_count, weeks, None, None)
    average = recent / CAPACITY_WEEKS
    return CapacityMirror(next_count, weeks, average, next_count / average)


def _current_receipts(receipts: Iterable[Receipt], kind: str) -> dict[str, Receipt]:
    return {receipt.task_id: receipt for receipt in receipts if receipt.kind == kind}


def waiting_queue(
    tasks: Iterable[ReviewTask], receipts: Iterable[Receipt], now: datetime
) -> list[str]:
    """Waiting tasks waiting more than 7 days, unhidden, oldest first (FR-032)."""

    by_task = _current_receipts(receipts, "waiting")
    due: list[tuple[datetime, str]] = []
    for task in tasks:
        since = task.waiting_since
        if task.state != "waiting" or since is None or now - since <= WAITING_AGE:
            continue
        receipt = by_task.get(task.id)
        if receipt is not None and receipt.hides(task, now):
            continue
        due.append((since, task.id))
    return [task_id for _, task_id in sorted(due)]


def someday_queue(
    tasks: Iterable[ReviewTask],
    receipts: Iterable[Receipt],
    now: datetime,
    *,
    limit: int = SOMEDAY_SHOWN,
) -> SomedayQueue:
    """FR-032: unhidden Someday tasks not auto-parked in the last 30 days.

    Never-reviewed first (oldest ``updated_at``, then id), then the oldest
    receipt ``reviewed_at``; at most ``limit`` shown.
    """

    by_task = _current_receipts(receipts, "someday")
    never: list[tuple[datetime, str]] = []
    reviewed: list[tuple[datetime, datetime, str]] = []
    oldest = datetime.min.replace(tzinfo=UTC)
    for task in tasks:
        if task.state != "someday":
            continue
        if task.parked_at is not None and now - task.parked_at < RECENT_PARK:
            continue
        receipt = by_task.get(task.id)
        updated = task.updated_at or oldest
        if receipt is None:
            never.append((updated, task.id))
        elif not receipt.hides(task, now):
            reviewed.append((receipt.reviewed_at, updated, task.id))
    order = [task_id for _, task_id in sorted(never)]
    order += [task_id for _, _, task_id in sorted(reviewed)]
    return SomedayQueue(eligible_total=len(order), shown=order[:limit])


def restart_mode(
    *,
    onboarded_at: datetime | None,
    last_counted_review_at: datetime | None,
    now: datetime,
) -> bool:
    """FR-017: onboarded, and 21 days since the last counted review or onboarding."""

    if onboarded_at is None:
        return False
    anchor = last_counted_review_at or onboarded_at
    return now - anchor >= RESTART_AFTER


def ended_status(end: str, qualifying: bool) -> ReviewStatus:
    """FR-029: Done → completed / completed_empty; replaced or idle-closed →
    partial / abandoned."""

    if end == "finish":
        return "completed" if qualifying else "completed_empty"
    if end in ("replace", "idle_close"):
        return "partial" if qualifying else "abandoned"
    raise ValueError(f"unknown session end {end!r}")


def idle_close_due(last_activity_at: datetime, now: datetime) -> bool:
    return now - last_activity_at >= IDLE_CLOSE_AFTER


def qualifying_activity(item_decisions: int, steps: Mapping[str, StepProgress]) -> bool:
    """At least one item decision, or a non-summary step finished (not skipped)
    with nothing to decide (FR-029)."""

    if item_decisions > 0:
        return True
    return any(
        code != "summary" and step.status == "finished" and step.finished_empty
        for code, step in steps.items()
    )


def is_counted(status: str, qualifying: bool) -> bool:
    """Counted reviews: completed, partial, and open once it qualifies."""

    return status in _COUNTED_STATUSES or (status == "open" and qualifying)


def last_counted_review_at(sessions: Iterable[SessionSummary]) -> datetime | None:
    """The regularity instant: latest completed ``ended_at``, partial or
    qualifying open ``last_activity_at`` (data-model E3)."""

    instants: list[datetime] = []
    for session in sessions:
        if not is_counted(session.status, session.qualifying_activity):
            continue
        if session.status == "completed" and session.ended_at is not None:
            instants.append(session.ended_at)
        else:
            instants.append(session.last_activity_at)
    return max(instants, default=None)


def next_review_at(
    *,
    review_weekday: int,
    review_time: str,
    time_zone: str,
    now: datetime,
    last_counted_review_at: datetime | None,
) -> datetime:
    """The first weekly slot strictly after ``now`` (ISO weekday, local wall
    time in ``time_zone``), skipping a slot with a counted review in the 6 days
    before it (FR-036)."""

    zone = ZoneInfo(time_zone)
    wall = time.fromisoformat(review_time)
    local_today = now.astimezone(zone).date()
    days_ahead = (review_weekday - local_today.isoweekday()) % 7
    day = local_today + timedelta(days=days_ahead)
    slot = _slot(day, wall, zone)
    if slot <= now:
        day += WEEK
        slot = _slot(day, wall, zone)
    if last_counted_review_at is not None and last_counted_review_at >= (
        slot - NOTIFICATION_SKIP
    ):
        slot = _slot(day + WEEK, wall, zone)
    return slot


def _slot(day: date, wall: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, wall, tzinfo=zone).astimezone(UTC)


def stall_recommendation(stall_reason: str | None) -> str | None:
    """FR-007: the decision a stall reason recommends (choice is never limited)."""

    if stall_reason is None:
        return None
    return _STALL_RECOMMENDATION[stall_reason]


@dataclass(slots=True)
class ActiveTimeAccumulator:
    """SC-004 active time per step (data-model E3), fed with timed events.

    The time since the last counted event is added to the step on screen when
    it is at most 2 minutes; a longer gap adds 0. ``background`` and ``leave``
    pause counting until ``foreground`` or ``resume``.
    """

    seconds_by_step: dict[str, int] = field(default_factory=dict)
    _step: str | None = None
    _last: datetime | None = None

    def record(self, kind: str, at: datetime, step: str | None = None) -> None:
        if self._step is not None and self._last is not None:
            gap = at - self._last
            if gap <= ACTIVE_GAP_LIMIT:
                self.seconds_by_step[self._step] += int(gap.total_seconds())
        if kind in ("enter_step", "resume"):
            if step is None:
                raise ValueError(f"{kind} needs a step")
            self._step = step
            self.seconds_by_step.setdefault(step, 0)
            self._last = at
        elif kind in ("background", "leave"):
            self._last = None
        elif kind in ("interaction", "foreground"):
            self._last = at if self._step is not None else None
        else:
            raise ValueError(f"unknown active-time event {kind!r}")


def show_while_away(
    *,
    context: str,
    has_unseen: bool,
    last_shown_day: date | None,
    today: date,
) -> bool:
    """FR-015: always first in a review; at app open at most once a day."""

    if not has_unseen:
        return False
    if context == "review_start":
        return True
    return last_shown_day is None or today > last_shown_day


def drop_duplicate_proposals(
    proposals: Iterable[str], *, current_title: str, open_titles: Iterable[str]
) -> list[str]:
    """FR-019: drop proposals whose formulation key equals the current title,
    any open task of the project (not only the 20 sent) or an earlier proposal."""

    seen = {formulation_key(current_title)}
    seen.update(formulation_key(title) for title in open_titles)
    kept: list[str] = []
    for proposal in proposals:
        key = formulation_key(proposal)
        if key in seen:
            continue
        seen.add(key)
        kept.append(proposal)
    return kept
