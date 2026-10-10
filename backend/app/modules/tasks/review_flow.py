"""The guided weekly review: runs, queues, capacity and bulk release.

Spec 020, slice PR-11 (contracts/http.md §6, data-model E3, E5, E7). Built on
the pure rules in ``review_rules.py`` and ``formulation.py`` and composed over
``ReviewService``: every write runs under the same owner lock and idempotency
discipline (``serialized_write``) and stores one record whose body the
``review_session:``, ``bulk_release:`` and ``undo_bulk_release:`` reconcilers of
``ReviewService`` can re-apply.

Client ids are de-duplication inputs in exactly the matching-record form of
http "Retry after the idempotency retention": a run (``id``: ``mode``,
``origin``), a bulk release (``id``: ``kind``, the task set) and a progress
change (``progress_id``: the run and the body digest). The match is checked
first, before ``replace_open``, revisions and eligibility.

Logs go to ``app.modules.tasks.review`` with ids, codes, counts and timings
only (FR-044).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.exceptions import NotFoundError
from app.schemas.review import (
    BulkReleaseRequest,
    SessionFinishRequest,
    SessionProgressRequest,
    SessionStartRequest,
)
from app.utils.idempotency import request_fingerprint
from app.utils.identifiers import generate_id

from . import formulation, review_rules
from .domain import ProjectDocument, TaskDocument
from .repository import TaskRepository
from .review_domain import (
    BulkReleasedItemDocument,
    BulkSkippedItemDocument,
    ReleasedClockDocument,
    ReviewBulkReleaseDocument,
    ReviewReceiptDocument,
    ReviewRequestError,
    ReviewSessionDocument,
    SessionCountsDocument,
    StepStateDocument,
    task_clock,
    with_clock,
)
from .review_service import (
    SNAPSHOT_RETENTION,
    USAGE_RETENTION,
    BulkReleaseResultDocument,
    BulkUndoResultDocument,
    ReviewService,
    SessionResultDocument,
    review_error,
)
from .rust_review_facade import ReviewRefused, RustReviewFacade
from .service import serialized_write

logger = logging.getLogger("app.modules.tasks.review")

DATES_WINDOW_DAYS = 14
_OPEN_STATES = frozenset({"inbox", "next", "waiting", "someday"})
_STEP_RANK = {"pending": 0, "skipped": 1, "finished": 2}
_RELEASABLE: dict[str, Literal["next", "inbox"]] = {
    "restart": "next",
    "inbox_remainder": "inbox",
}
"""The list each bulk-release kind releases from (http §6, data-model E7)."""


class OpenSessionExistsError(ReviewRequestError):
    """409 ``open_session_exists``: the detail also names the open run (http §6)."""

    def __init__(self, session_id: str) -> None:
        super().__init__(409, "open_session_exists", "A review is already open.")
        self.session_id = session_id


class StepOutsideRunError(Exception):
    """A progress ``step`` or ``active_seconds`` code the run does not have.

    Rendered by the route as the 422 request-validation envelope with ``loc``
    ``["body", field, "code"]`` (http §6): a quick run has four steps, and a
    full-only code would add a step it never shows and could make it qualify.
    """

    def __init__(self, field: Literal["step", "active_seconds"]) -> None:
        super().__init__(f"{field}.code is not a step of this review")
        self.field = field


class _NoBody(BaseModel):
    """The bulk-release Undo has no body: its fingerprint is the command alone."""


@dataclass(frozen=True, slots=True)
class QueueView:
    """``GET /review/queues/{step}`` before mapping: tasks in order plus meta."""

    step: str
    items: list[TaskDocument]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """One read of an owner's tasks, receipts and settings at ``now``."""

    now: datetime
    tasks: list[TaskDocument]
    receipts: list[review_rules.Receipt]
    settings: formulation.OwnerClockSettings
    projects: list[ProjectDocument]

    def in_state(self, state: str) -> list[TaskDocument]:
        return sorted(
            (task for task in self.tasks if task.state == state), key=_manual_order
        )

    def pick(self, ids: Iterable[str]) -> list[TaskDocument]:
        """The tasks of ``ids`` in that order (an id no longer held is left out)."""

        by_id = {task.id: task for task in self.tasks}
        return [by_id[task_id] for task_id in ids if task_id in by_id]

    def review_tasks(self) -> list[review_rules.ReviewTask]:
        return [_review_task(task) for task in self.tasks]

    def asking_ids(self) -> list[str]:
        """The live ``asks_for_decision`` aggregate in formulation-clock §5 order."""

        return formulation.decision_queue(
            ((task.id, task_clock(task)) for task in self.in_state("next")),
            self.settings,
            self.now,
        )


@dataclass(frozen=True, slots=True)
class ReviewMetrics:
    """The post-release read-out of one owner (plan "Post-release acceptance").

    Counts and durations only, so nothing printed from it can carry content.
    """

    weeks: int
    weeks_with_counted_review: int
    answered_reviews: int
    answered_yes: int
    active_seconds_quick: list[int]
    active_seconds_full: list[int]
    sc005_since: date
    """First day of the cloud SC-005 share: ``since``, or the oldest retained
    ``navigator_usage`` day when ``since`` is older (35 days)."""
    shown_requests: int
    cloud_accepted: int
    device_decisions: int
    device_accepted: int
    parks: int
    parks_returned: int


_ACCEPTED = frozenset({"as_is", "edited"})


class ReviewFlowService:
    """Review runs, their queues, bulk releases and the metrics read-out."""

    def __init__(self, review: ReviewService) -> None:
        self.review = review

    # ``serialized_write`` reads these (the ``SerializedWriter`` protocol): the
    # flow shares the review service's repository, clock and reconcilers.
    @property
    def task_repo(self) -> TaskRepository:
        return self.review.task_repo

    @property
    def clock(self) -> Callable[[], datetime]:
        return self.review.clock

    def _reconcile_idempotent_result(self, *, owner_id: str, key: str) -> None:
        self.review._reconcile_idempotent_result(owner_id=owner_id, key=key)

    # ------------------------------------------------------------------ runs
    @serialized_write
    def start_session(
        self,
        payload: SessionStartRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewSessionDocument:
        """``POST /review/sessions`` (http §6, FR-027, FR-029).

        Order: the Idempotency-Key replay, then the matching-record check on a
        supplied ``id`` (same ``mode`` and ``origin`` answers the stored run
        and replaces nothing), and only then ``replace_open``.
        """

        started = time.monotonic()
        command = "review_session:start"
        request_hash = request_fingerprint(command, payload)
        record = self.review._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return SessionResultDocument.model_validate(record.response_body).session
        rust = self.review.rust(owner_id)
        if rust is not None:
            return self._start_with_rust(
                rust,
                payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                command=command,
                request_hash=request_hash,
                started=started,
            )
        if payload.id is not None:
            stored = self.task_repo.get_review_session(owner_id, payload.id)
            if stored is not None:
                if (stored.mode, stored.origin) != (payload.mode, payload.origin):
                    _log_refusal(owner_id, stored.id, "id_conflict")
                    raise review_error("id_conflict")
                _log_run(stored, event="start", outcome="already_applied", t0=started)
                return stored
        now = self.clock()
        open_runs = self.task_repo.list_open_review_sessions(owner_id)
        if open_runs and not payload.replace_open:
            _log_refusal(owner_id, open_runs[-1].id, "open_session_exists")
            raise OpenSessionExistsError(open_runs[-1].id)
        replaced = [_ended(run, "replace", ended_at=now) for run in open_runs]
        steps = review_rules.review_steps(payload.mode)
        skip = set(payload.skip_steps)
        session = ReviewSessionDocument(
            id=payload.id or generate_id("review"),
            owner_id=owner_id,
            mode=payload.mode,
            entry=payload.entry,
            origin=payload.origin,
            started_at=now,
            last_activity_at=now,
            current_step=next((code for code in steps if code not in skip), None),
            steps={
                code: StepStateDocument(status="skipped" if code in skip else "pending")
                for code in steps
            },
        )
        result = SessionResultDocument(session=session, replaced=replaced)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=session.id,
            response=result,
        )
        self.review.write_sessions(result, owner_id=owner_id)
        for run in replaced:
            _log_run(run, event="replaced", outcome="applied", t0=started)
        _log_run(session, event="start", outcome="applied", t0=started)
        return session

    def _start_with_rust(  # noqa: PLR0913 - the command's whole context
        self,
        rust: RustReviewFacade,
        payload: SessionStartRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        command: str,
        request_hash: str,
        started: float,
    ) -> ReviewSessionDocument:
        """A run started by the shared core, with any open run it replaces."""

        try:
            outcome = rust.start_session(payload, owner_id=owner_id, now=self.clock())
        except ReviewRefused as refused:
            _log_refusal(owner_id, refused.entity_id or "-", refused.reason)
            if refused.reason == "open_session_exists":
                raise OpenSessionExistsError(refused.entity_id or "") from None
            raise review_error(refused.reason) from None
        session = outcome.session
        if not outcome.changed:
            _log_run(session, event="start", outcome="already_applied", t0=started)
            return session
        result = SessionResultDocument(session=session, replaced=outcome.replaced)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=session.id,
            response=result,
        )
        self.review.write_sessions(result, owner_id=owner_id)
        for run in outcome.replaced:
            _log_run(run, event="replaced", outcome="applied", t0=started)
        _log_run(session, event="start", outcome="applied", t0=started)
        return session

    def get_session(self, session_id: str, *, owner_id: str) -> ReviewSessionDocument:
        """The owner's run; unknown and foreign ids are the same 404."""

        session = self.task_repo.get_review_session(owner_id, session_id)
        if session is None:
            raise NotFoundError("Review session", session_id)
        return session

    @serialized_write
    def progress_session(
        self,
        session_id: str,
        payload: SessionProgressRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewSessionDocument:
        """``PATCH /review/sessions/{id}``: merged, never version-checked.

        Replay-safe by ``progress_id`` at any age (http §6): a known id with
        the same body digest merges nothing and answers the current run; with
        another digest it is ``id_conflict``. Progress on an ended run is
        accepted and ignored. A ``step`` or ``active_seconds`` code that is not
        one of the run's steps is refused first (``StepOutsideRunError``,
        422), whatever the run's status: the mode never changes.
        """

        started = time.monotonic()
        command = f"review_session:{session_id}:progress"
        request_hash = request_fingerprint(command, payload)
        record = self.review._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return SessionResultDocument.model_validate(record.response_body).session
        rust = self.review.rust(owner_id)
        if rust is not None:
            return self._progress_with_rust(
                rust,
                session_id,
                payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                command=command,
                request_hash=request_hash,
                started=started,
            )
        session = self.get_session(session_id, owner_id=owner_id)
        _require_run_steps(session, payload)
        digest = progress_digest(payload)
        known = session.applied_progress.get(payload.progress_id)
        if known is not None and known != digest:
            _log_refusal(owner_id, session.id, "id_conflict")
            raise review_error("id_conflict")
        if known is not None:
            merged, outcome = session, "already_applied"
        elif session.status != "open":
            merged, outcome = session, "ignored"
        else:
            merged = self._merged(session, payload, digest, owner_id=owner_id)
            outcome = "applied"
        result = SessionResultDocument(session=merged)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=session.id,
            response=result,
        )
        self.review.write_sessions(result, owner_id=owner_id)
        _log_run(merged, event="progress", outcome=outcome, t0=started)
        return merged

    def _progress_with_rust(  # noqa: PLR0913 - the command's whole context
        self,
        rust: RustReviewFacade,
        session_id: str,
        payload: SessionProgressRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        command: str,
        request_hash: str,
        started: float,
    ) -> ReviewSessionDocument:
        """A progress change merged by the shared core, replay-safe by id."""

        try:
            outcome = rust.progress_session(
                session_id, payload, owner_id=owner_id, now=self.clock()
            )
        except ReviewRefused as refused:
            _log_refusal(owner_id, session_id, refused.reason)
            if refused.reason == "step_outside_run":
                raise StepOutsideRunError(
                    "active_seconds" if refused.field == "active_seconds" else "step"
                ) from None
            raise review_error(refused.reason) from None
        merged = outcome.session
        if outcome.changed:
            label = "applied"
        elif payload.progress_id in merged.applied_progress:
            label = "already_applied"
        else:
            label = "ignored"
        result = SessionResultDocument(session=merged)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=session_id,
            response=result,
        )
        self.review.write_sessions(result, owner_id=owner_id)
        _log_run(merged, event="progress", outcome=label, t0=started)
        return merged

    def _merged(
        self,
        session: ReviewSessionDocument,
        payload: SessionProgressRequest,
        digest: str,
        *,
        owner_id: str,
    ) -> ReviewSessionDocument:
        now = self.clock()
        steps = dict(session.steps)
        counts = session.counts
        update: dict[str, Any] = {}
        if payload.current_step is not None:
            update["current_step"] = payload.current_step
        if payload.step is not None:
            code, status = payload.step.code, payload.step.status
            before = steps.get(code, StepStateDocument())
            empty = before.finished_empty or (
                status == "finished" and self._nothing_to_decide(code, owner_id, now)
            )
            steps[code] = StepStateDocument(
                status=max(before.status, status, key=_STEP_RANK.__getitem__),
                finished_empty=empty,
            )
        seconds = dict(session.active_seconds_by_step)
        if payload.active_seconds is not None:
            code = payload.active_seconds.code
            seconds[code] = seconds.get(code, 0) + payload.active_seconds.seconds
        set_aside = list(session.set_aside_task_ids)
        aside = payload.set_aside_task_id
        if aside is not None and aside not in set_aside:
            task = self.review._task_or_none(owner_id, aside)
            if task is not None and task.state in _OPEN_STATES:
                set_aside.append(aside)
        if payload.inbox_processed_delta is not None:
            processed = counts.inbox_processed + payload.inbox_processed_delta
            counts = counts.model_copy(update={"inbox_processed": max(0, processed)})
        if payload.snapshot_decision_queue and session.decision_queue is None:
            update["decision_queue"] = self._snapshot(owner_id, now).asking_ids()
        progress = {
            code: review_rules.StepProgress(step.status, step.finished_empty)
            for code, step in steps.items()
        }
        qualifying = session.qualifying_activity or review_rules.qualifying_activity(
            sum(counts.model_dump().values()), progress
        )
        return session.model_copy(
            update={
                **update,
                "steps": steps,
                "active_seconds_by_step": seconds,
                "set_aside_task_ids": set_aside,
                "counts": counts,
                "qualifying_activity": qualifying,
                "applied_progress": {
                    **session.applied_progress,
                    payload.progress_id: digest,
                },
                "last_activity_at": max(session.last_activity_at, now),
                "revision": session.revision + 1,
            }
        )

    @serialized_write
    def finish_session(
        self,
        session_id: str,
        payload: SessionFinishRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewSessionDocument:
        """Done on the summary: ``completed`` or ``completed_empty`` (FR-029).

        Idempotent by state: an ended run is returned unchanged.
        """

        started = time.monotonic()
        command = f"review_session:{session_id}:finish"
        request_hash = request_fingerprint(command, payload)
        record = self.review._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return SessionResultDocument.model_validate(record.response_body).session
        rust = self.review.rust(owner_id)
        if rust is not None:
            done = rust.finish_session(
                session_id, payload, owner_id=owner_id, now=self.clock()
            )
            return self._finished(
                done.session,
                "applied" if done.changed else "already_ended",
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                command=command,
                request_hash=request_hash,
                started=started,
            )
        session = self.get_session(session_id, owner_id=owner_id)
        if session.status == "open":
            now = self.clock()
            finished = _ended(session, "finish", ended_at=now).model_copy(
                update={
                    "clear_start": payload.clear_start,
                    "last_activity_at": max(session.last_activity_at, now),
                }
            )
            outcome = "applied"
        else:
            finished, outcome = session, "already_ended"
        return self._finished(
            finished,
            outcome,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            command=command,
            request_hash=request_hash,
            started=started,
        )

    def _finished(  # noqa: PLR0913 - the command's whole context
        self,
        finished: ReviewSessionDocument,
        outcome: str,
        *,
        owner_id: str,
        idempotency_key: str,
        command: str,
        request_hash: str,
        started: float,
    ) -> ReviewSessionDocument:
        """Store and write the run a finish answers, and log it."""

        result = SessionResultDocument(session=finished)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=finished.id,
            response=result,
        )
        self.review.write_sessions(result, owner_id=owner_id)
        _log_run(finished, event="finish", outcome=outcome, t0=started)
        return finished

    def close_idle_sessions(self, owner_id: str, now: datetime) -> int:
        """Close runs idle for 7 days: partial or abandoned (http §9, E3).

        The sweep's retention hook: candidates are read outside the lock and
        re-read under it. The run ends 7 days after its last activity.
        """

        candidates = [
            session.id
            for session in self.task_repo.list_open_review_sessions(owner_id)
            if review_rules.idle_close_due(session.last_activity_at, now)
        ]
        closed = 0
        if not candidates:
            return closed
        with self.task_repo.command_lock(owner_id):
            for session_id in candidates:
                session = self.task_repo.get_review_session(owner_id, session_id)
                if (
                    session is None
                    or session.status != "open"
                    or not review_rules.idle_close_due(session.last_activity_at, now)
                ):
                    continue
                ended = _ended(
                    session,
                    "idle_close",
                    ended_at=session.last_activity_at + review_rules.IDLE_CLOSE_AFTER,
                )
                self.task_repo.save_review_session(ended)
                _log_run(ended, event="idle_close", outcome="applied", t0=None)
                closed += 1
        return closed

    # ---------------------------------------------------------------- queues
    def queue(self, step: str, *, owner_id: str, session_id: str | None) -> QueueView:
        """``GET /review/queues/{step}`` (http §6) at the service clock."""

        rust = self.review.rust(owner_id)
        if rust is not None:
            answer = rust.queue(
                step, owner_id=owner_id, session_id=session_id, now=self.clock()
            )
            return QueueView(step, answer.items, answer.meta)
        session = (
            None
            if session_id is None
            else self.get_session(session_id, owner_id=owner_id)
        )
        build = _QUEUES.get(step)
        if build is None:  # mind_sweep and summary show no tasks
            return QueueView(step, [])
        view = build(session, self._snapshot(owner_id, self.clock()))
        if step == "decisions":
            return replace(view, meta=self._handled_decisions(owner_id, session, view))
        return view

    def _handled_decisions(
        self,
        owner_id: str,
        session: ReviewSessionDocument | None,
        view: QueueView,
    ) -> dict[str, list[str]]:
        """Which cards of the run are handled already, and how (http §6).

        ``decided_task_ids``: a decision of this run exists for the task (an
        Undo deletes it, so the card is not handled any more).
        ``set_aside_task_ids``: "Not now" (FR-050), unless the task was decided
        after. Both follow the queue's order and name only tasks it lists, so a
        run resumed on any device, in any browser, shows only the cards left.
        """

        if session is None:
            return {"decided_task_ids": [], "set_aside_task_ids": []}
        decided = {
            decision.task_id
            for decision in self.task_repo.list_review_decisions_for_session(
                owner_id, session.id
            )
        }
        aside = set(session.set_aside_task_ids)
        ids = [task.id for task in view.items]
        return {
            "decided_task_ids": [task_id for task_id in ids if task_id in decided],
            "set_aside_task_ids": [
                task_id for task_id in ids if task_id in aside - decided
            ],
        }

    def _snapshot(self, owner_id: str, now: datetime) -> _Snapshot:
        return _Snapshot(
            now=now,
            tasks=self.task_repo.list_for_owner(owner_id=owner_id),
            receipts=[
                review_rules.Receipt(
                    task_id=receipt.task_id,
                    kind=receipt.kind,
                    task_revision=receipt.task_revision,
                    reviewed_at=receipt.reviewed_at,
                    hidden_until=receipt.hidden_until,
                    source=receipt.source,
                )
                for receipt in self.task_repo.list_review_receipts(owner_id)
            ],
            settings=self.review.settings_for(owner_id).clock_settings(),
            projects=self.review.tasks.list_projects(owner_id=owner_id),
        )

    def _nothing_to_decide(self, step: str, owner_id: str, now: datetime) -> bool:
        """E3 / FR-029: finishing ``step`` now is qualifying activity.

        Steps that only show (wins, mind sweep, rest of Next, dates) have
        nothing to decide; a deciding step only when its queue is empty; the
        summary never qualifies (as the iOS core's ``hasNothingToDecide``).
        """

        if step == "summary":
            return False
        if step in ("wins", "mind_sweep", "rest_of_next", "dates"):
            return True
        view = self._snapshot(owner_id, now)
        if step == "inbox":
            return not view.in_state("inbox")
        if step == "decisions":
            return not view.asking_ids()
        if step == "waiting":
            return not review_rules.waiting_queue(
                view.review_tasks(), view.receipts, view.now
            )
        if step == "someday":
            queue = review_rules.someday_queue(
                view.review_tasks(), view.receipts, view.now
            )
            return queue.eligible_total == 0
        return not _stuck_projects(view)

    # --------------------------------------------------------------- metrics
    def metrics(self, owner_id: str, *, since: date) -> ReviewMetrics:
        """Aggregates from ``since`` (UTC midnight) to now; a read, no writes.

        SC-001: weeks (7-day spans from ``since``) holding a counted review's
        regularity instant. SC-003: runs started in the window with a
        clear-start answer. SC-004: total active seconds of completed runs per
        mode. SC-005: decisions naming a server request accepted as is or
        edited over the shown requests (``navigator_usage.shown``, so a shown
        and then abandoned request stays in the denominator), both counted
        from ``sc005_since``: ``navigator_usage`` rows live 35 days, so an
        older ``since`` would count decisions over a denominator that lost
        their shown requests (a share above 100%). And the
        on-device share over decisions without a request id that saw a
        proposal (an upper bound: abandoned on-device proposals are unseen).
        Parks: rows parked in the window and how many were returned.
        """

        now = self.clock()
        start = datetime.combine(since, dt_time.min, tzinfo=UTC)
        repo = self.task_repo
        weeks = max(1, -(-(now - start) // review_rules.WEEK))
        sessions = repo.list_review_sessions(owner_id)
        counted = {
            (instant - start) // review_rules.WEEK
            for instant in (_regularity_instant(s) for s in sessions)
            if instant is not None and start <= instant <= now
        }
        in_window = [s for s in sessions if s.started_at >= start]
        answered = [s for s in in_window if s.clear_start is not None]
        completed = [s for s in in_window if s.status == "completed"]
        decisions = [
            d for d in repo.list_review_decisions(owner_id) if d.decided_at >= start
        ]
        device = [
            d
            for d in decisions
            if d.navigator_request_id is None and d.ai_use != "none"
        ]
        parks = [p for p in repo.list_park_acks(owner_id) if p.parked_at >= start]
        # Both sides of the cloud share start where the usage rows still exist.
        sc005_since = max(since, (now - USAGE_RETENTION).date())
        sc005_start = datetime.combine(sc005_since, dt_time.min, tzinfo=UTC)
        return ReviewMetrics(
            weeks=weeks,
            weeks_with_counted_review=len(counted),
            answered_reviews=len(answered),
            answered_yes=sum(s.clear_start == "yes" for s in answered),
            active_seconds_quick=_active_seconds(completed, "quick"),
            active_seconds_full=_active_seconds(completed, "full"),
            sc005_since=sc005_since,
            shown_requests=sum(
                usage.shown
                for usage in repo.list_navigator_usage(owner_id)
                if usage.day >= sc005_since
            ),
            cloud_accepted=sum(
                d.navigator_request_id is not None
                and d.ai_use in _ACCEPTED
                and d.decided_at >= sc005_start
                for d in decisions
            ),
            device_decisions=len(device),
            device_accepted=sum(d.ai_use in _ACCEPTED for d in device),
            parks=len(parks),
            parks_returned=sum(p.returned_at is not None for p in parks),
        )

    # ---------------------------------------------------------- bulk release
    @serialized_write
    def bulk_release(
        self,
        payload: BulkReleaseRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewBulkReleaseDocument:
        """``POST /review/bulk-releases`` (http §6, FR-017, FR-030).

        Eligibility is the server's, per item, under the owner lock: restart →
        in Next and ``restart_eligible``; Inbox remainder → in Inbox (an item
        processed in the run has left Inbox). Unknown, foreign and ineligible
        ids are all ``not_eligible``; an eligible item at another revision is
        ``stale``. A supplied ``id`` already stored is matched first.
        """

        started = time.monotonic()
        command = f"bulk_release:{owner_id}"
        request_hash = request_fingerprint(command, payload)
        record = self.review._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            stored = BulkReleaseResultDocument.model_validate(record.response_body)
            return stored.release
        rust = self.review.rust(owner_id)
        if rust is not None:
            return self._release_with_rust(
                rust,
                payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                command=command,
                request_hash=request_hash,
                started=started,
            )
        expected: dict[str, int] = {}
        for item in payload.items:
            expected.setdefault(item.task_id, item.expected_revision)
        if payload.id is not None:
            existing = self.task_repo.get_bulk_release(owner_id, payload.id)
            if existing is not None:
                if existing.kind != payload.kind or _task_set(existing) != set(
                    expected
                ):
                    _log_refusal(owner_id, existing.id, "id_conflict")
                    raise review_error("id_conflict")
                _log_bulk(
                    existing, event="release", outcome="already_applied", t0=started
                )
                return existing
        result = self._released(payload, expected, owner_id=owner_id)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=result.release.id,
            response=result,
        )
        self.review.write_bulk_release(result, owner_id=owner_id)
        _log_bulk(result.release, event="release", outcome="applied", t0=started)
        return result.release

    def _release_with_rust(  # noqa: PLR0913 - the command's whole context
        self,
        rust: RustReviewFacade,
        payload: BulkReleaseRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        command: str,
        request_hash: str,
        started: float,
    ) -> ReviewBulkReleaseDocument:
        """A bulk release decided by the shared core; the subset commits once."""

        try:
            outcome = rust.bulk_release(payload, owner_id=owner_id, now=self.clock())
        except ReviewRefused as refused:
            _log_refusal(owner_id, refused.entity_id or "-", refused.reason)
            raise review_error(refused.reason) from None
        if not outcome.changed:
            _log_bulk(
                outcome.release, event="release", outcome="already_applied", t0=started
            )
            return outcome.release
        result = BulkReleaseResultDocument(
            release=outcome.release, tasks=outcome.tasks, receipts=outcome.receipts
        )
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=result.release.id,
            response=result,
        )
        self.review.write_bulk_release(result, owner_id=owner_id)
        _log_bulk(result.release, event="release", outcome="applied", t0=started)
        return result.release

    def _released(
        self,
        payload: BulkReleaseRequest,
        expected: dict[str, int],
        *,
        owner_id: str,
    ) -> BulkReleaseResultDocument:
        now = self.clock()
        settings = self.review.settings_for(owner_id).clock_settings()
        bulk_id = payload.id or generate_id("bulk")
        released: list[BulkReleasedItemDocument] = []
        skipped: list[BulkSkippedItemDocument] = []
        tasks: list[TaskDocument] = []
        receipts: list[ReviewReceiptDocument] = []
        for task_id, revision in expected.items():
            task = self.review._task_or_none(owner_id, task_id)
            if task is None or not _eligible(task, payload.kind, settings, now):
                skipped.append(
                    BulkSkippedItemDocument(task_id=task_id, reason="not_eligible")
                )
                continue
            if task.revision != revision:
                skipped.append(BulkSkippedItemDocument(task_id=task_id, reason="stale"))
                continue
            clock, snapshot = formulation.release(
                task_clock(task), settings=settings, now=now
            )
            moved = with_clock(
                self.review.tasks._validated_task_update(
                    task, state="someday", revision=clock.revision, updated_at=now
                ),
                clock,
            )
            tasks.append(moved)
            receipt = self.review._receipt(moved, "someday", "release", now)
            receipts.append(receipt.model_copy(update={"bulk_id": bulk_id}))
            released.append(
                BulkReleasedItemDocument(
                    task_id=task_id,
                    revision_after=moved.revision,
                    previous_state=_RELEASABLE[payload.kind],
                    clock_before=_released_document(snapshot),
                )
            )
        release = ReviewBulkReleaseDocument(
            id=bulk_id,
            owner_id=owner_id,
            kind=payload.kind,
            session_id=self.review._known_session(owner_id, payload.session_id),
            released=released,
            skipped=skipped,
            created_at=now,
        )
        return BulkReleaseResultDocument(
            release=release, tasks=tasks, receipts=receipts
        )

    @serialized_write
    def undo_bulk_release(
        self,
        bulk_id: str,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """``POST /review/bulk-releases/{id}/undo`` (http §6, formulation-clock §3).

        Each released task still at ``revision_after`` returns to its list with
        its stored clock exactly; the others are ``stale``. An already undone
        release answers its stored ``undo_result`` at any age and changes
        nothing; a never-undone release whose snapshot was purged (7 days) is
        ``undo_unavailable``.
        """

        started = time.monotonic()
        command = f"undo_bulk_release:{bulk_id}"
        request_hash = request_fingerprint(command, _NoBody())
        record = self.review._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            stored = BulkUndoResultDocument.model_validate(record.response_body)
            return dict(stored.release.undo_result or {})
        rust = self.review.rust(owner_id)
        if rust is not None:
            return self._undo_release_with_rust(
                rust,
                bulk_id,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                command=command,
                request_hash=request_hash,
                started=started,
            )
        release = self.task_repo.get_bulk_release(owner_id, bulk_id)
        if release is None:
            raise NotFoundError("Review bulk release", bulk_id)
        if release.undone_at is not None and release.undo_result is not None:
            _log_bulk(release, event="undo", outcome="already_undone", t0=started)
            return dict(release.undo_result)
        now = self.clock()
        if _snapshot_purged(release, now):
            _log_refusal(owner_id, release.id, "undo_unavailable")
            raise ReviewRequestError(
                409, "undo_unavailable", "This release can no longer be undone."
            )
        result = self._undone(release, owner_id=owner_id, now=now)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=release.id,
            response=result,
        )
        self.review.write_bulk_undo(result, owner_id=owner_id)
        _log_bulk(result.release, event="undo", outcome="applied", t0=started)
        return dict(result.release.undo_result or {})

    def _undo_release_with_rust(  # noqa: PLR0913 - the command's whole context
        self,
        rust: RustReviewFacade,
        bulk_id: str,
        *,
        owner_id: str,
        idempotency_key: str,
        command: str,
        request_hash: str,
        started: float,
    ) -> dict[str, Any]:
        """A bulk-release Undo decided by the shared core."""

        try:
            outcome = rust.undo_bulk_release(
                bulk_id, owner_id=owner_id, now=self.clock()
            )
        except ReviewRefused as refused:
            _log_refusal(owner_id, bulk_id, refused.reason)
            raise ReviewRequestError(
                409, "undo_unavailable", "This release can no longer be undone."
            ) from None
        if not outcome.changed:
            _log_bulk(
                outcome.release, event="undo", outcome="already_undone", t0=started
            )
            return dict(outcome.release.undo_result or {})
        result = BulkUndoResultDocument(release=outcome.release, tasks=outcome.tasks)
        self.review._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=bulk_id,
            response=result,
        )
        self.review.write_bulk_undo(result, owner_id=owner_id)
        _log_bulk(result.release, event="undo", outcome="applied", t0=started)
        return dict(result.release.undo_result or {})

    def _undone(
        self, release: ReviewBulkReleaseDocument, *, owner_id: str, now: datetime
    ) -> BulkUndoResultDocument:
        restored: list[str] = []
        skipped: list[dict[str, str]] = []
        tasks: list[TaskDocument] = []
        for item in release.released:
            task = self.review._task_or_none(owner_id, item.task_id)
            if task is None or task.revision != item.revision_after:
                skipped.append({"task_id": item.task_id, "reason": "stale"})
                continue
            clock = formulation.undo_release(
                task_clock(task),
                previous_state=item.previous_state,
                released=_released_clock(item.clock_before),
            )
            tasks.append(
                with_clock(
                    self.review.tasks._validated_task_update(
                        task,
                        state=item.previous_state,
                        revision=clock.revision,
                        updated_at=now,
                    ),
                    clock,
                )
            )
            restored.append(item.task_id)
        undone = release.model_copy(
            update={
                "undone_at": now,
                "undo_result": {"restored": restored, "skipped": skipped},
            }
        )
        return BulkUndoResultDocument(release=undone, tasks=tasks)


# ------------------------------------------------------------------ helpers
def progress_digest(payload: SessionProgressRequest) -> str:
    """SHA-256 of the canonical progress body without ``progress_id`` (http §6)."""

    body = payload.model_dump(mode="json", exclude={"progress_id"}, exclude_none=True)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_run_steps(
    session: ReviewSessionDocument, payload: SessionProgressRequest
) -> None:
    """Refuse a progress change naming a step outside the run's mode (http §6)."""

    if payload.step is not None and payload.step.code not in session.steps:
        _log_refusal(session.owner_id, session.id, "step_outside_run")
        raise StepOutsideRunError("step")
    active = payload.active_seconds
    if active is not None and active.code not in session.steps:
        _log_refusal(session.owner_id, session.id, "step_outside_run")
        raise StepOutsideRunError("active_seconds")


def _ended(
    session: ReviewSessionDocument, end: str, *, ended_at: datetime
) -> ReviewSessionDocument:
    """A run ended by Done, replacement or the idle close (E3 transitions)."""

    return session.model_copy(
        update={
            "status": review_rules.ended_status(end, session.qualifying_activity),
            "ended_at": ended_at,
            "applied_progress": {},
            "revision": session.revision + 1,
        }
    )


def _regularity_instant(session: ReviewSessionDocument) -> datetime | None:
    """A counted run's regularity instant (data-model E3), else ``None``."""

    if not review_rules.is_counted(session.status, session.qualifying_activity):
        return None
    if session.status == "completed" and session.ended_at is not None:
        return session.ended_at
    return session.last_activity_at


def _active_seconds(sessions: list[ReviewSessionDocument], mode: str) -> list[int]:
    return [
        sum(session.active_seconds_by_step.values())
        for session in sessions
        if session.mode == mode
    ]


def _manual_order(task: TaskDocument) -> tuple[int, str, str]:
    return (task.order_key, task.created_at.isoformat(), task.id)


def _review_task(task: TaskDocument) -> review_rules.ReviewTask:
    return review_rules.ReviewTask(
        id=task.id,
        state=task.state,
        revision=task.revision,
        completed_at=task.completed_at,
        waiting_since=task.waiting_since,
        updated_at=task.updated_at,
        parked_at=None if task.parked is None else task.parked.at,
    )


def _decision_ids(session: ReviewSessionDocument | None, view: _Snapshot) -> list[str]:
    """The run's snapshot once taken, else the live aggregate (http §6)."""

    if session is not None and session.decision_queue is not None:
        return list(session.decision_queue)
    return view.asking_ids()


def _stuck_projects(view: _Snapshot) -> list[list[TaskDocument]]:
    """Active projects without a Next task, each as its open tasks in order.

    A project with no open task at all is stuck too (an empty list), as the
    iOS core's ``needsNextAction``.
    """

    stuck: list[list[TaskDocument]] = []
    for project in view.projects:
        open_tasks = sorted(
            (
                task
                for task in view.tasks
                if task.project_id == project.id and task.state in _OPEN_STATES
            ),
            key=_manual_order,
        )
        if not any(task.state == "next" for task in open_tasks):
            stuck.append(open_tasks)
    return stuck


def _stuck_project_tasks(view: _Snapshot) -> list[TaskDocument]:
    """The ``projects`` queue: the open tasks of the stuck projects."""

    return [task for tasks in _stuck_projects(view) for task in tasks]


_Session = ReviewSessionDocument | None


def _wins_queue(session: _Session, view: _Snapshot) -> QueueView:
    """FR-028: completed in the last 7 days, most recent first, with the count."""

    del session
    wins = review_rules.wins(view.review_tasks(), view.now)
    return QueueView("wins", view.pick(wins), {"count": len(wins)})


def _inbox_queue(session: _Session, view: _Snapshot) -> QueueView:
    del session
    return QueueView("inbox", view.in_state("inbox"))


def _decisions_queue(session: _Session, view: _Snapshot) -> QueueView:
    return QueueView("decisions", view.pick(_decision_ids(session, view)))


def _rest_of_next(session: _Session, view: _Snapshot) -> QueueView:
    """FR-031: Next beyond the decisions, with the capacity mirror."""

    next_tasks = view.in_state("next")
    asking = set(_decision_ids(session, view))
    mirror = review_rules.capacity_mirror(
        len(next_tasks),
        [task.completed_at for task in view.tasks if task.completed_at],
        view.now,
    )
    return QueueView(
        "rest_of_next",
        [task for task in next_tasks if task.id not in asking],
        {
            "next_count": mirror.next_count,
            "weekly_average_4w": mirror.weekly_average_4w,
            "weeks_of_history": mirror.weeks_of_history,
            "implied_weeks": mirror.implied_weeks,
        },
    )


def _waiting_queue(session: _Session, view: _Snapshot) -> QueueView:
    """FR-032: Waiting more than 7 days, unhidden, oldest first."""

    del session
    ids = review_rules.waiting_queue(view.review_tasks(), view.receipts, view.now)
    return QueueView("waiting", view.pick(ids))


def _projects_queue(session: _Session, view: _Snapshot) -> QueueView:
    del session
    return QueueView("projects", _stuck_project_tasks(view))


def _someday_queue(session: _Session, view: _Snapshot) -> QueueView:
    """FR-032: at most 7 unhidden Someday tasks, longest-unreviewed first."""

    del session
    someday = review_rules.someday_queue(view.review_tasks(), view.receipts, view.now)
    return QueueView(
        "someday",
        view.pick(someday.shown),
        {"eligible_total": someday.eligible_total, "shown": len(someday.shown)},
    )


def _dates_queue(session: _Session, view: _Snapshot) -> QueueView:
    del session
    return _dates(view)


_QUEUES: dict[str, Callable[[_Session, _Snapshot], QueueView]] = {
    "wins": _wins_queue,
    "inbox": _inbox_queue,
    "decisions": _decisions_queue,
    "rest_of_next": _rest_of_next,
    "waiting": _waiting_queue,
    "projects": _projects_queue,
    "someday": _someday_queue,
    "dates": _dates_queue,
}


def _dates(view: _Snapshot) -> QueueView:
    """Open tasks due from today to today + 13 in the stored zone, by day."""

    today = view.now.astimezone(ZoneInfo(view.settings.time_zone)).date()
    last = today + timedelta(days=DATES_WINDOW_DAYS - 1)
    by_day: dict[str, list[TaskDocument]] = {}
    for task in view.tasks:
        due = task.due_date
        if task.state in _OPEN_STATES and due is not None and today <= due <= last:
            by_day.setdefault(due.isoformat(), []).append(task)
    days = []
    items: list[TaskDocument] = []
    for day in sorted(by_day):
        ordered = sorted(by_day[day], key=lambda task: (task.order_key, task.id))
        days.append({"day": day, "task_ids": [task.id for task in ordered]})
        items.extend(ordered)
    return QueueView("dates", items, {"days": days})


def _eligible(
    task: TaskDocument,
    kind: str,
    settings: formulation.OwnerClockSettings,
    now: datetime,
) -> bool:
    if task.state != _RELEASABLE[kind]:
        return False
    if kind == "restart":
        return formulation.restart_eligible(task_clock(task), settings, now)
    return True


def _task_set(release: ReviewBulkReleaseDocument) -> set[str]:
    """The task ids a stored release was asked about (released and skipped)."""

    return {item.task_id for item in release.released} | {
        item.task_id for item in release.skipped
    }


def _snapshot_purged(release: ReviewBulkReleaseDocument, now: datetime) -> bool:
    """The undo snapshot is gone: past 7 days, or a Next clock was nulled (E7)."""

    if now - release.created_at >= SNAPSHOT_RETENTION:
        return True
    return any(
        item.previous_state == "next" and item.clock_before is None
        for item in release.released
    )


def _released_document(
    snapshot: formulation.ReleasedClock | None,
) -> ReleasedClockDocument | None:
    if snapshot is None:
        return None
    return ReleasedClockDocument(
        formulation_id=snapshot.formulation_id,
        started_at=snapshot.started_at,
        extended_at=snapshot.extended_at,
        extension_reason=snapshot.extension_reason,
        park_floor_at=snapshot.park_floor_at,
        stalled_before=snapshot.stalled_before,
    )


def _released_clock(
    document: ReleasedClockDocument | None,
) -> formulation.ReleasedClock | None:
    if document is None:
        return None
    return formulation.ReleasedClock(
        formulation_id=document.formulation_id,
        started_at=document.started_at,
        extended_at=document.extended_at,
        extension_reason=document.extension_reason,
        park_floor_at=document.park_floor_at,
        stalled_before=document.stalled_before,
    )


def _counts_text(counts: SessionCountsDocument) -> str:
    return ",".join(f"{name}:{value}" for name, value in counts.model_dump().items())


def _log_run(
    session: ReviewSessionDocument, *, event: str, outcome: str, t0: float | None
) -> None:
    """``review_run`` (plan Observability): mode, status and counts only."""

    logger.info(
        "review_run owner_id=%s session_id=%s event=%s mode=%s status=%s "
        "counts=%s qualifying=%s outcome=%s duration_ms=%d",
        session.owner_id,
        session.id,
        event,
        session.mode,
        session.status,
        _counts_text(session.counts),
        session.qualifying_activity,
        outcome,
        0 if t0 is None else int((time.monotonic() - t0) * 1000),
    )


def _log_bulk(
    release: ReviewBulkReleaseDocument, *, event: str, outcome: str, t0: float
) -> None:
    logger.info(
        "review_bulk_release owner_id=%s bulk_id=%s event=%s kind=%s released=%d "
        "skipped=%d outcome=%s duration_ms=%d",
        release.owner_id,
        release.id,
        event,
        release.kind,
        len(release.released),
        len(release.skipped),
        outcome,
        int((time.monotonic() - t0) * 1000),
    )


def _log_refusal(owner_id: str, record_id: str, reason: str) -> None:
    logger.info(
        "review_flow_refused owner_id=%s id=%s outcome=%s", owner_id, record_id, reason
    )


__all__ = [
    "OpenSessionExistsError",
    "QueueView",
    "ReviewFlowService",
    "ReviewMetrics",
    "StepOutsideRunError",
    "progress_digest",
]
