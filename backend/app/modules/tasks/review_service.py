"""Weekly-review commands over native tasks (spec 020, ADR-0027).

``ReviewService`` composes ``TaskService``: every review command runs under the
same owner lock and idempotency discipline (``serialized_write``) and calls the
task service's undecorated helpers inside it, so a decision and its task change
are one transaction with one idempotency record (research R7). It owns the
idempotency prefixes in ``REVIEW_COMMAND_PREFIXES`` and their reconcilers.

Logs go to ``app.modules.tasks.review`` and carry ids, codes, counts and
timings only: never a title, notes, waiting-for text, extension reason or the
stall reason (FR-044).
"""

from __future__ import annotations

import hashlib
import logging
import time
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.exceptions import ConflictError, IdempotencyConflictError, NotFoundError
from app.schemas.common import StorageBaseModel
from app.schemas.review import (
    AutoParkRequest,
    DecisionRequest,
    ExplainerAcknowledgeRequest,
    ParkAcknowledgeRequest,
    ReviewSettingsUpdateRequest,
    UndoDecisionRequest,
)
from app.utils.idempotency import request_fingerprint
from app.utils.identifiers import generate_id

from . import formulation, review_rules
from .domain import FormulationSettingsDocument, IdempotencyRecord, TaskDocument
from .repository import IDEMPOTENCY_RETENTION, TaskRepository
from .review_domain import (
    REVIEW_COMMAND_PREFIXES,
    REVIEW_COUNTS_AS,
    AutoParkResultDocument,
    DecisionResultDocument,
    DecisionUndoDocument,
    FormulationView,
    ParkAckKeyDocument,
    ParkAcknowledgeResultDocument,
    ReviewBulkReleaseDocument,
    ReviewDecisionDocument,
    ReviewParkAckDocument,
    ReviewReceiptDocument,
    ReviewRequestError,
    ReviewSessionDocument,
    ReviewSettingsDocument,
    UndoResultDocument,
    task_clock,
    with_clock,
)
from .service import TaskService, serialized_write

logger = logging.getLogger("app.modules.tasks.review")


# ------------------------------------------------- review-flow result records
# Slice PR-11: the bodies the ``review_session:``, ``bulk_release:`` and
# ``undo_bulk_release:`` idempotency records keep. They live here, beside their
# reconcilers, because ``review_flow`` sits above this module (import-linter).
class SessionResultDocument(StorageBaseModel):
    """One run command's outcome (http §6): the run, and any run it replaced."""

    session: ReviewSessionDocument
    replaced: list[ReviewSessionDocument] = Field(default_factory=list)


class BulkReleaseResultDocument(StorageBaseModel):
    """One bulk release (data-model E7) with the tasks and receipts it wrote."""

    release: ReviewBulkReleaseDocument
    tasks: list[TaskDocument] = Field(default_factory=list)
    receipts: list[ReviewReceiptDocument] = Field(default_factory=list)


class BulkUndoResultDocument(StorageBaseModel):
    """One bulk-release Undo: the record as undone and the restored tasks."""

    release: ReviewBulkReleaseDocument
    tasks: list[TaskDocument] = Field(default_factory=list)


_FLOW_RESULTS: dict[str, type[StorageBaseModel]] = {
    "review_session:": SessionResultDocument,
    "bulk_release:": BulkReleaseResultDocument,
    "undo_bulk_release:": BulkUndoResultDocument,
}

ACTIVATION_GRACE = formulation.ACTIVATION_GRACE
WAITING_RECEIPT = timedelta(days=7)
SOMEDAY_RECEIPT = timedelta(days=30)
DETAILS_MAX_LENGTH = 20_000
SNAPSHOT_RETENTION = timedelta(days=7)
USAGE_RETENTION = timedelta(days=35)
SWEEP_GAP = timedelta(hours=24)
SWEEP_BATCH = 50


@dataclass(frozen=True, slots=True)
class ReviewSweepResult:
    """Counts of one review sweep run (the ``review_sweep`` log line)."""

    owners: int
    parked: int
    repaired: int
    closed: int
    gap_floors: int
    snapshots_nulled: int
    duration_ms: int

    @property
    def changed(self) -> bool:
        return bool(
            self.parked
            or self.repaired
            or self.closed
            or self.gap_floors
            or self.snapshots_nulled
        )


_OPEN = frozenset({"inbox", "next", "waiting", "someday"})
_ALLOWED_STATES: dict[str, frozenset[str]] = {
    "complete": _OPEN,
    "cancel": _OPEN,
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
"""http §3 "allowed when task is"."""

_ON_FORMULATION = frozenset(
    {"reformulate", "first_step", "waiting", "someday", "extend"}
)
"""Types decided on the current formulation: a different id is stale."""

_MESSAGES: dict[str, str] = {
    "decision_not_allowed": (
        "This decision isn't available for this task's current list. "
        "Nothing was changed."
    ),
    "extension_already_used": "This task was already kept 7 more days.",
    "extension_not_due": "This task doesn't ask for a decision yet.",
    "project_archived": "This task's project is archived.",
    "details_too_long": "The notes would be too long with the previous title.",
    "id_conflict": "This id is already used by another record.",
    "undo_unavailable": "This decision can no longer be undone.",
    "invalid_time_zone": "This isn't a time zone we know.",
}
_STATUS: dict[str, int] = {"id_conflict": 409, "undo_unavailable": 409}


def review_error(reason: str) -> ReviewRequestError:
    """The fixed, content-free refusal for one reason code (http §3 – §5)."""

    return ReviewRequestError(_STATUS.get(reason, 400), reason, _MESSAGES[reason])


@dataclass(frozen=True, slots=True)
class UnseenPark:
    task_id: str
    formulation_id: str
    parked_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewStateView:
    """``GET /review/state`` before mapping (contracts/http.md §5)."""

    settings: ReviewSettingsDocument
    explainer_seen: bool
    grace_until: datetime | None
    last_counted_review_at: datetime | None
    last_counted_review: ReviewSessionDocument | None
    next_review_at: datetime
    restart_mode: bool
    open_session: ReviewSessionDocument | None
    unseen_parks: list[UnseenPark]
    asks_for_decision: int
    moves_tomorrow: int
    receipts: list[ReviewReceiptDocument]
    server_now: datetime


def _no_exposure(owner_id: str) -> bool:
    del owner_id
    return False


def _no_idle_close(owner_id: str, now: datetime) -> int:
    del owner_id, now
    return 0


class ReviewService:
    """Decisions, undo, settings, activation, auto-park and the review sweep."""

    def __init__(
        self,
        tasks: TaskService,
        *,
        is_exposed: Callable[[str], bool] = _no_exposure,
    ) -> None:
        self.tasks = tasks
        # Resolves the owner's ``User`` and asks ``FeatureFlagService`` whether
        # ``weekly_review`` is effective (http §9); a missing user is False.
        self.is_exposed = is_exposed
        # The idle-run close belongs to the review flow (slice PR-11); the
        # container points this at ``ReviewFlowService`` (a no-op until then).
        self.idle_session_closer: Callable[[str, datetime], int] = _no_idle_close

    # The one clock seam (research R21): the review service reads the task
    # service's injected clock, so ``frozen_clock`` drives both.
    @property
    def clock(self) -> Callable[[], datetime]:
        return self.tasks.clock

    @property
    def task_repo(self) -> TaskRepository:
        return self.tasks.task_repo

    def formulation_views(
        self,
        owner_id: str,
        tasks: list[TaskDocument],
        *,
        settings: FormulationSettingsDocument | None = None,
    ) -> dict[str, FormulationView]:
        return self.tasks.formulation_views(owner_id, tasks, settings=settings)

    # ------------------------------------------------------------ decisions
    @serialized_write
    def decide(
        self,
        task_id: str,
        payload: DecisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> DecisionResultDocument:
        """``POST /tasks/{task_id}/decisions`` (http §3) as one command.

        Order of checks (http "Retry after the idempotency retention"): the
        Idempotency-Key replay, then the matching-record check on a supplied
        ``decision_id``, and only then ownership, the auto-park yield rule or
        ``expected_revision``, the list eligibility, the formulation and the
        type's own rule. Everything is written in this owner-locked transaction.
        """

        started = time.monotonic()
        command = f"decide_task:{task_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return DecisionResultDocument.model_validate(record.response_body)
        if payload.decision_id is not None:
            existing = self.task_repo.get_review_decision(owner_id, payload.decision_id)
            if existing is not None:
                if not _decision_matches(existing, task_id, payload):
                    raise self._refuse(
                        "review_decision", owner_id, task_id, "id_conflict"
                    )
                result = self._stored_decision_result(existing, owner_id=owner_id)
                self._log_decision(result, outcome="already_applied", started=started)
                return result
        task = self.tasks.get_task(task_id, owner_id=owner_id)
        now = self.clock()
        settings = self.settings_for(owner_id).clock_settings()
        yielded = _yields(task, payload)
        if yielded:
            task = _reverse_park(task)
        else:
            try:
                self.tasks._assert_current(task, payload.expected_revision)
            except ConflictError:
                self._log_rejection(owner_id, task_id, payload.type, "stale")
                raise
        self._check_decision(task, payload, owner_id=owner_id)
        result = self._apply_decision(
            task,
            payload,
            owner_id=owner_id,
            now=now,
            settings=settings,
            yielded=yielded,
        )
        self.tasks._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=result.decision.id,
            response=result,
        )
        self._write_decision(result, owner_id=owner_id, previous=task)
        self._log_decision(result, outcome="applied", started=started)
        return result

    def _check_decision(
        self, task: TaskDocument, payload: DecisionRequest, *, owner_id: str
    ) -> None:
        if task.state not in _ALLOWED_STATES[payload.type]:
            raise self._refuse(
                "review_decision", owner_id, task.id, "decision_not_allowed"
            )
        on_formulation = payload.type in _ON_FORMULATION or (
            task.state == "next" and payload.formulation_id is not None
        )
        if on_formulation and payload.formulation_id != task.formulation_id:
            self._log_rejection(owner_id, task.id, payload.type, "stale")
            raise ConflictError(
                "Task",
                task.id,
                f"Task '{task.id}' has newer changes; reload before saving.",
            )
        if payload.type in ("follow_up", "return_to_next") and task.project_id:
            project = self.task_repo.get_project_for_owner(
                task.project_id, owner_id=owner_id
            )
            if project.state != "active":
                raise self._refuse(
                    "review_decision", owner_id, task.id, "project_archived"
                )

    def _apply_decision(  # noqa: PLR0913 - the decision's whole context
        self,
        task: TaskDocument,
        payload: DecisionRequest,
        *,
        owner_id: str,
        now: datetime,
        settings: formulation.OwnerClockSettings,
        yielded: bool,
    ) -> DecisionResultDocument:
        decision_type = payload.type
        updated = task
        created: TaskDocument | None = None
        receipt: ReviewReceiptDocument | None = None
        substantive: bool | None = None
        if decision_type in ("complete", "cancel"):
            updated = self._transition(
                task, decision_type, None, payload, owner_id, now
            )
        elif decision_type in ("waiting", "someday"):
            updated = self._transition(
                task, "move", decision_type, payload, owner_id, now
            )
            if decision_type == "someday":
                receipt = self._receipt(updated, "someday", "release", now)
        elif decision_type == "return_to_next":
            updated = self._transition(task, "move", "next", payload, owner_id, now)
            if payload.title is not None and payload.title != updated.title:
                updated = self.tasks._validated_task_update(
                    updated, title=payload.title
                )
        elif decision_type == "reformulate":
            title = _required(payload.title)
            substantive = formulation.is_substantive(task.title, title)
            clock = formulation.change_title(
                task_clock(task),
                title=title,
                settings=settings,
                now=now,
                new_formulation_id=self.tasks._formulation_id(
                    payload.new_formulation_id
                ),
            )
            updated = self._edited(task, clock, now, title=title)
        elif decision_type == "first_step":
            title = _required(payload.title)
            details = f"Was: {task.title}" + (
                f"\n\n{task.details}" if task.details else ""
            )
            if len(details) > DETAILS_MAX_LENGTH:
                raise self._refuse(
                    "review_decision", owner_id, task.id, "details_too_long"
                )
            substantive = True
            clock = formulation.first_step(
                task_clock(task),
                title=title,
                settings=settings,
                now=now,
                new_formulation_id=self.tasks._formulation_id(
                    payload.new_formulation_id
                ),
            )
            updated = self._edited(task, clock, now, title=title, details=details)
        elif decision_type == "extend":
            try:
                clock = formulation.extend(
                    task_clock(task),
                    reason=_required(payload.reason),
                    settings=settings,
                    now=now,
                )
            except formulation.FormulationRuleError as exc:
                raise self._refuse(
                    "review_decision", owner_id, task.id, exc.reason
                ) from None
            updated = self._edited(task, clock, now)
        elif decision_type == "keep_waiting":
            receipt = self._receipt(task, "waiting", "keep", now)
        elif decision_type == "keep_someday":
            receipt = self._receipt(task, "someday", "keep", now)
        else:  # follow_up
            created = self._follow_up(task, payload, owner_id=owner_id, now=now)
            receipt = self._receipt(task, "waiting", "keep", now)
        decision = ReviewDecisionDocument(
            id=payload.decision_id or generate_id("decision"),
            owner_id=owner_id,
            task_id=task.id,
            session_id=self._known_session(owner_id, payload.session_id),
            decided_at=now,
            type=decision_type,
            stall_reason=payload.stall_reason,
            substantive=substantive,
            ai_use=payload.ai_use,
            navigator_request_id=payload.navigator_request_id,
            formulation_id=payload.formulation_id,
            task_revision_before=task.revision,
            task_revision_after=updated.revision,
            reason_text=payload.reason if decision_type == "extend" else None,
            undo=DecisionUndoDocument(
                task_before=task,
                created_task_id=created.id if created else None,
                created_task_revision=created.revision if created else None,
                receipt_kind=receipt.kind if receipt else None,
            ),
            client_decided_at=payload.client_decided_at,
            review_counts_as=REVIEW_COUNTS_AS[decision_type],
            yielded_auto_park=yielded,
            created_task_id=created.id if created else None,
        )
        if receipt is not None:
            receipt = receipt.model_copy(update={"decision_id": decision.id})
        return DecisionResultDocument(
            decision=decision,
            task=updated,
            created_task=created,
            receipt=receipt,
            session_counts=self._counted_session_counts(owner_id, decision, delta=1),
            formulation_settings=FormulationSettingsDocument.of(settings),
        )

    def _transition(  # noqa: PLR0913 - mirrors the transition request
        self,
        task: TaskDocument,
        action: str,
        to_state: str | None,
        payload: DecisionRequest,
        owner_id: str,
        now: datetime,
    ) -> TaskDocument:
        return self.tasks._transitioned(
            task,
            action=action,
            to_state=to_state,
            waiting_for=payload.waiting_for,
            new_formulation_id=payload.new_formulation_id,
            owner_id=owner_id,
            now=now,
        )

    def _edited(
        self,
        task: TaskDocument,
        clock: formulation.TaskClock,
        now: datetime,
        **updates: Any,
    ) -> TaskDocument:
        changed = self.tasks._validated_task_update(
            task, **updates, updated_at=now, revision=task.revision + 1
        )
        return with_clock(changed, clock)

    def _receipt(
        self, task: TaskDocument, kind: str, source: str, now: datetime
    ) -> ReviewReceiptDocument:
        """A receipt hiding the task from its review step (data-model E5)."""

        span = WAITING_RECEIPT if kind == "waiting" else SOMEDAY_RECEIPT
        return ReviewReceiptDocument.model_validate(
            {
                "owner_id": task.owner_id,
                "task_id": task.id,
                "kind": kind,
                "task_revision": task.revision,
                "reviewed_at": now,
                "hidden_until": now + span,
                "source": source,
            }
        )

    def _follow_up(
        self,
        task: TaskDocument,
        payload: DecisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TaskDocument:
        task_id = payload.follow_up_task_id or generate_id("task")
        try:
            self.tasks.get_task(task_id, owner_id=owner_id)
        except NotFoundError:
            pass
        else:
            raise self._refuse("review_decision", owner_id, task.id, "id_conflict")
        created = TaskDocument(
            id=task_id,
            owner_id=owner_id,
            title=_required(payload.title),
            state="next",
            project_id=task.project_id,
            order_key=self.task_repo.next_order_key(owner_id=owner_id, state="next"),
            created_at=now,
            updated_at=now,
        )
        return self.tasks._started_if_next(created, payload.new_formulation_id, now=now)

    def _known_session(self, owner_id: str, session_id: str | None) -> str | None:
        """A session the owner holds, else ``None`` (never 404, SC-007)."""

        if session_id is None:
            return None
        session = self.task_repo.get_review_session(owner_id, session_id)
        return None if session is None else session.id

    def _counted_session_counts(
        self, owner_id: str, decision: ReviewDecisionDocument, *, delta: int
    ) -> Any:
        """The linked session's counters after this decision (or its undo)."""

        if decision.session_id is None:
            return None
        session = self.task_repo.get_review_session(owner_id, decision.session_id)
        if session is None:
            return None
        bucket = decision.review_counts_as
        counts = session.counts.model_copy(
            update={bucket: max(0, getattr(session.counts, bucket) + delta)}
        )
        return counts

    def _write_decision(
        self,
        result: DecisionResultDocument,
        *,
        owner_id: str,
        previous: TaskDocument,
    ) -> None:
        if result.task != previous or result.task.revision != previous.revision:
            self.task_repo.save(result.task)
            self.tasks._note_park_return(
                previous, result.task, owner_id=owner_id, now=result.decision.decided_at
            )
        decision = result.decision
        if decision.yielded_auto_park and decision.formulation_id is not None:
            # A yield reverses the park itself; it is not a return (E6).
            self._set_park_returned(owner_id, decision.task_id, decision.formulation_id)
        if result.created_task is not None:
            self.task_repo.create(result.created_task)
        if result.receipt is not None:
            self.task_repo.save_review_receipt(result.receipt)
        self.task_repo.save_review_decision(result.decision)
        self._update_session(owner_id, result.decision, result.session_counts)

    def _update_session(
        self,
        owner_id: str,
        decision: ReviewDecisionDocument,
        counts: Any,
    ) -> None:
        if decision.session_id is None or counts is None:
            return
        session = self.task_repo.get_review_session(owner_id, decision.session_id)
        if session is None:
            return
        steps = {
            code: review_rules.StepProgress(step.status, step.finished_empty)
            for code, step in session.steps.items()
        }
        total = sum(counts.model_dump().values())
        update: dict[str, Any] = {
            "counts": counts,
            "qualifying_activity": review_rules.qualifying_activity(total, steps),
            "revision": session.revision + 1,
        }
        if session.status == "open":
            update["last_activity_at"] = self.clock()
        self.task_repo.save_review_session(session.model_copy(update=update))

    def _stored_decision_result(
        self, decision: ReviewDecisionDocument, *, owner_id: str
    ) -> DecisionResultDocument:
        """A first delivery's answer built from the stored decision (http §3)."""

        task = self.tasks.get_task(decision.task_id, owner_id=owner_id)
        created = None
        if decision.created_task_id is not None:
            try:
                created = self.tasks.get_task(
                    decision.created_task_id, owner_id=owner_id
                )
            except NotFoundError:
                created = None
        receipt = None
        for kind in ("waiting", "someday"):
            stored = self.task_repo.get_review_receipt(owner_id, task.id, kind)
            if stored is not None and stored.decision_id == decision.id:
                receipt = stored
        counts = None
        if decision.session_id is not None:
            session = self.task_repo.get_review_session(owner_id, decision.session_id)
            counts = None if session is None else session.counts
        return DecisionResultDocument(
            decision=decision,
            task=task,
            created_task=created,
            receipt=receipt,
            session_counts=counts,
        )

    # ------------------------------------------------------------------ undo
    @serialized_write
    def undo_decision(
        self,
        decision_id: str,
        payload: UndoDecisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> UndoResultDocument:
        """``POST /review/decisions/{id}/undo`` (FR-048, data-model E4 "Undo")."""

        started = time.monotonic()
        command = f"undo_decision:{decision_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return UndoResultDocument.model_validate(record.response_body)
        decision = self.task_repo.get_review_decision(owner_id, decision_id)
        if decision is None:
            raise NotFoundError("Review decision", decision_id)
        undo = decision.undo
        task = self.tasks.get_task(decision.task_id, owner_id=owner_id)
        available = (
            undo is not None
            and task.revision == decision.task_revision_after
            and payload.expected_task_revision == task.revision
            and self._created_task_unchanged(owner_id, undo)
        )
        if not available or undo is None:
            raise self._refuse("review_undo", owner_id, task.id, "undo_unavailable")
        now = self.clock()
        restored = self._restored_task(undo.task_before, task, owner_id=owner_id)
        restored = restored.model_copy(
            update={"revision": task.revision + 1, "updated_at": now}
        )
        result = UndoResultDocument(
            task=restored,
            undone_decision_id=decision.id,
            deleted_task_id=undo.created_task_id,
            session_counts=self._counted_session_counts(owner_id, decision, delta=-1),
            formulation_settings=self.tasks.formulation_settings(owner_id),
        )
        self.tasks._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=decision.id,
            response=result,
        )
        self._write_undo(result, decision, owner_id=owner_id)
        logger.info(
            "review_undo owner_id=%s decision_id=%s task_id=%s type=%s "
            "deleted_task=%s outcome=applied duration_ms=%d",
            owner_id,
            decision.id,
            decision.task_id,
            decision.type,
            undo.created_task_id is not None,
            _elapsed_ms(started),
        )
        return result

    def _created_task_unchanged(
        self, owner_id: str, undo: DecisionUndoDocument
    ) -> bool:
        """The follow-up is still exactly as the decision created it (E4).

        Its revision is unchanged **and** it holds no tag link, subtask or
        comment: adding a subtask or comment does not bump the revision, and
        deleting the task would cascade-delete that row.
        """

        if undo.created_task_id is None:
            return True
        try:
            created = self.tasks.get_task(undo.created_task_id, owner_id=owner_id)
        except NotFoundError:
            return True
        return (
            created.revision == undo.created_task_revision
            and not self.task_repo.task_has_child_rows(owner_id, created.id)
        )

    def _restored_task(
        self, snapshot: TaskDocument, current: TaskDocument, *, owner_id: str
    ) -> TaskDocument:
        """formulation-clock §3 "decision undo": the snapshot, floors kept.

        The time-zone floor and the activation clamp are clock bookkeeping
        written without a revision bump, so they can land after the decision
        and still leave its Undo available. A task restored into Next keeps
        ``max(snapshot floor, current floor)``, and a restored formulation that
        started before ``activated_at`` gets the activation clamp.
        """

        if snapshot.state != "next":
            return snapshot
        restored = snapshot
        floors = [
            floor
            for floor in (
                snapshot.formulation_park_floor_at,
                current.formulation_park_floor_at if current.state == "next" else None,
            )
            if floor is not None
        ]
        if floors:
            restored = restored.model_copy(
                update={"formulation_park_floor_at": max(floors)}
            )
        activated_at = self.settings_for(owner_id).activated_at
        started = restored.formulation_started_at
        if activated_at is not None and started is not None and started < activated_at:
            clock = formulation.activate_clock(
                task_clock(restored),
                activated_at=activated_at,
                formulation_id=generate_id("form"),
            )
            restored = with_clock(restored, clock)
        return restored

    def _set_park_returned(
        self,
        owner_id: str,
        task_id: str,
        formulation_id: str,
        returned_at: datetime | None = None,
    ) -> None:
        """Set one park row's ``returned_at`` (data-model E6); a missing row stays."""

        ack = self.task_repo.get_park_ack(owner_id, task_id, formulation_id)
        if ack is not None and ack.returned_at != returned_at:
            self.task_repo.save_park_ack(
                ack.model_copy(update={"returned_at": returned_at})
            )

    def _write_undo(
        self,
        result: UndoResultDocument,
        decision: ReviewDecisionDocument,
        *,
        owner_id: str,
    ) -> None:
        self.task_repo.save(result.task)
        parked = result.task.parked
        if result.task.state == "someday" and parked is not None:
            # Back in its park (e.g. Undo of return_to_next): the row reads as
            # it did while the task was parked, not returned (E6).
            self._set_park_returned(owner_id, result.task.id, parked.formulation_id)
        if result.deleted_task_id is not None:
            self.task_repo.delete_task_record(owner_id, result.deleted_task_id)
        undo = decision.undo
        if undo is not None and undo.receipt_kind is not None:
            receipt = self.task_repo.get_review_receipt(
                owner_id, decision.task_id, undo.receipt_kind
            )
            if receipt is not None and receipt.decision_id == decision.id:
                self.task_repo.delete_review_receipt(
                    owner_id, decision.task_id, undo.receipt_kind
                )
        self.task_repo.delete_review_decision(owner_id, decision.id)
        self._update_session(owner_id, decision, result.session_counts)

    # ------------------------------------------------------------- settings
    @serialized_write
    def update_settings(
        self,
        payload: ReviewSettingsUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewSettingsDocument:
        """``PUT /review/settings`` (http §5, FR-035, FR-039, FR-046).

        A field equal to the stored value is no change: an equal zone raises no
        floor, an equal threshold sets no owner floor, and a body whose every
        field is equal leaves ``revision`` alone (``expected_revision`` is still
        checked). Floors are clock bookkeeping: no task revision moves.
        """

        command = f"review_settings:{owner_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return ReviewSettingsDocument.model_validate(record.response_body)
        current = self.settings_for(owner_id)
        if payload.expected_revision != current.revision:
            raise ConflictError(
                "Review settings",
                owner_id,
                "Review settings have newer changes; reload before saving.",
            )
        if payload.time_zone is not None and not is_iana_zone(payload.time_zone):
            raise self._refuse("review_settings", owner_id, "-", "invalid_time_zone")
        now = self.clock()
        updated = _changed_settings(current, payload, now=now)
        zone_changed = updated.time_zone != current.time_zone
        if updated != current:
            updated = updated.model_copy(update={"revision": current.revision + 1})
        self._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=owner_id,
            response=updated,
        )
        if updated.revision == current.revision:
            return current
        self.task_repo.save_review_settings(updated)
        floored = self._floor_due_dated(owner_id, now=now) if zone_changed else 0
        logger.info(
            "review_settings_changed owner_id=%s threshold_old=%d threshold_new=%d "
            "zone_changed=%s due_floors=%d schedule_changed=%s onboarded=%s",
            owner_id,
            current.threshold_days,
            updated.threshold_days,
            zone_changed,
            floored,
            (updated.review_weekday, updated.review_time)
            != (current.review_weekday, current.review_time),
            updated.onboarded_at is not None,
        )
        return updated

    # ----------------------------------------------------------- activation
    @serialized_write
    def acknowledge_explainer(
        self,
        payload: ExplainerAcknowledgeRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ReviewSettingsDocument:
        """``POST /review/explainer/acknowledge`` (http §5, FR-016, FR-051).

        First wins: the activating acknowledgement sets ``activated_at`` to the
        server's now, stores the supplied zone and runs the activation clamp in
        this transaction; any later one changes nothing, its zone included. The
        clamp is clock bookkeeping: no task revision or ``updated_at`` moves.
        """

        command = f"explainer_ack:{owner_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return self.settings_for(owner_id)
        if payload.time_zone is not None and not is_iana_zone(payload.time_zone):
            raise self._refuse("review_activated", owner_id, "-", "invalid_time_zone")
        settings = self.settings_for(owner_id)
        if settings.activated_at is None:
            settings = self._activated_settings(
                settings, at=self.clock(), time_zone=payload.time_zone
            )
        self._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=owner_id,
            response=settings,
        )
        if self.settings_for(owner_id).activated_at is None:
            self._activate(settings)
        return settings

    @staticmethod
    def _activated_settings(
        settings: ReviewSettingsDocument, *, at: datetime, time_zone: str | None
    ) -> ReviewSettingsDocument:
        return settings.model_copy(
            update={
                "activated_at": at,
                "last_effective_sweep_at": at,
                "time_zone": time_zone or settings.time_zone,
                "revision": settings.revision + 1,
            }
        )

    def _activate(self, settings: ReviewSettingsDocument) -> None:
        """The activation transition for every Next task (formulation-clock §3)."""

        at = settings.activated_at
        assert at is not None
        self.task_repo.save_review_settings(settings)
        clamped = 0
        for task in self.task_repo.list_next_tasks(settings.owner_id):
            clock = formulation.activate_clock(
                task_clock(task), activated_at=at, formulation_id=generate_id("form")
            )
            if clock != task_clock(task):
                self.task_repo.save(with_clock(task, clock))
                clamped += 1
        logger.info(
            "review_activated owner_id=%s tasks_clamped=%d", settings.owner_id, clamped
        )

    # ------------------------------------------------------------ auto-park
    @serialized_write
    def auto_park(
        self,
        task_id: str,
        payload: AutoParkRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        exposed: bool,
    ) -> AutoParkResultDocument:
        """``POST /tasks/{task_id}/auto-park``: a park a device observed (http §4).

        The server re-evaluates with its own clock and settings and parks iff
        the flag is effective (``exposed``), the owner is activated, the task is
        in Next on the named formulation and classifies ``park_due``. Anything
        else is ``applied: false``, a success; a second park of the same
        formulation is therefore a no-op by state (FR-013). For an exposed,
        activated owner the sweep-gap bookkeeping runs first, exactly as in
        the sweep, so a device park never skips the gap floor (SC-006).
        """

        command = f"auto-park:{task_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return AutoParkResultDocument.model_validate(record.response_body)
        task = self.tasks.get_task(task_id, owner_id=owner_id)
        result: AutoParkResultDocument | None = None
        if exposed and self.settings_for(owner_id).activated_at is not None:
            self._note_effective_sweep(owner_id, self.clock())
        if exposed and task.formulation_id == payload.formulation_id:
            result = self._parked(task, owner_id=owner_id, source="device")
        if result is None:
            result = AutoParkResultDocument(applied=False, task=task)
        # After the sweep-gap bookkeeping above, which can raise the owner floor.
        result = result.model_copy(
            update={"formulation_settings": self.tasks.formulation_settings(owner_id)}
        )
        self._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=task.id,
            response=result,
        )
        self._write_park(result)
        _log_park(owner_id, task.id, applied=result.applied, source="device")
        return result

    def _parked(
        self, task: TaskDocument, *, owner_id: str, source: str
    ) -> AutoParkResultDocument | None:
        """The park of a ``park_due`` Next task of an activated owner, or None."""

        settings = self.settings_for(owner_id).clock_settings()
        if task.state != "next" or settings.activated_at is None:
            return None
        now = self.clock()
        clock = formulation.auto_park(task_clock(task), settings=settings, now=now)
        if clock is None or clock.parked is None:
            return None
        parked = with_clock(task, clock).model_copy(
            update={
                "state": "someday",
                "updated_at": now,
                "revision": task.revision + 1,
            }
        )
        # A repeat park of the same formulation (after a yield, T-046) upserts
        # the row afresh, so ``seen_at`` and ``returned_at`` start null again and
        # the task shows on "While you were away" again (data-model E6).
        ack = ReviewParkAckDocument.model_validate(
            {
                "owner_id": owner_id,
                "task_id": task.id,
                "formulation_id": clock.parked.formulation_id,
                "parked_at": now,
                "from_revision": task.revision,
                "source": source,
            }
        )
        return AutoParkResultDocument(
            applied=True, task=parked, from_revision=task.revision, ack=ack
        )

    def _write_park(self, result: AutoParkResultDocument) -> None:
        if result.applied and result.ack is not None:
            self.task_repo.save(result.task)
            self.task_repo.save_park_ack(result.ack)

    @serialized_write
    def acknowledge_parks(
        self,
        payload: ParkAcknowledgeRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> None:
        """``POST /review/parks/acknowledge`` (http §5, FR-015).

        Idempotent by state (an acknowledged park stays acknowledged) and by
        the stored Idempotency-Key record (http "Mutations"): the same key and
        body replay, another body is ``idempotency_conflict``. Unknown and
        foreign ids are ignored identically (no existence oracle), and marking
        a park seen never bumps a task revision (data-model E6).
        """

        command = f"park_ack:{owner_id}"
        request_hash = request_fingerprint(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, hash_=request_hash
        )
        if record is not None:
            return
        keys = {(item.task_id, item.formulation_id): None for item in payload.items}
        marked = []
        for task_id, formulation_id in keys:
            ack = self.task_repo.get_park_ack(owner_id, task_id, formulation_id)
            if ack is not None and ack.seen_at is None:
                marked.append(
                    ParkAckKeyDocument(task_id=task_id, formulation_id=formulation_id)
                )
        result = ParkAcknowledgeResultDocument(seen_at=self.clock(), marked=marked)
        self._store(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=owner_id,
            response=result,
        )
        self._write_parks_seen(result, owner_id=owner_id)
        logger.info(
            "review_parks_acknowledged owner_id=%s items=%d marked=%d",
            owner_id,
            len(payload.items),
            len(marked),
        )

    def _write_parks_seen(
        self, result: ParkAcknowledgeResultDocument, *, owner_id: str
    ) -> None:
        """Mark the recorded rows seen; also the ``park_ack:`` reconciler.

        Only a row still unseen and parked no later than ``seen_at`` is
        marked: a repeat park upserted after the acknowledgement (E6 resets
        ``seen_at``) is a park the person has not seen, so a replay leaves it.
        """

        for key in result.marked:
            ack = self.task_repo.get_park_ack(owner_id, key.task_id, key.formulation_id)
            if (
                ack is not None
                and ack.seen_at is None
                and ack.parked_at <= result.seen_at
            ):
                self.task_repo.save_park_ack(
                    ack.model_copy(update={"seen_at": result.seen_at})
                )

    # ---------------------------------------------------------------- sweep
    def run_maintenance_sweep(self) -> ReviewSweepResult:
        """One review sweep run: retention for everyone, then exposure (http §9)."""

        started = time.monotonic()
        now = self.clock()
        nulled, closed = self.run_review_retention(now)
        owners, parked, repaired, gaps = self.run_auto_park_sweep(now)
        result = ReviewSweepResult(
            owners=owners,
            parked=parked,
            repaired=repaired,
            closed=closed,
            gap_floors=gaps,
            snapshots_nulled=nulled,
            duration_ms=_elapsed_ms(started),
        )
        level = logging.INFO if result.changed else logging.DEBUG
        logger.log(
            level,
            "review_sweep owners=%d parked=%d repaired=%d closed=%d gap_floors=%d "
            "snapshots_nulled=%d duration_ms=%d",
            result.owners,
            result.parked,
            result.repaired,
            result.closed,
            result.gap_floors,
            result.snapshots_nulled,
            result.duration_ms,
        )
        return result

    def run_review_retention(self, now: datetime) -> tuple[int, int]:
        """Null 7-day snapshots, drop 35-day usage rows, close idle runs, and
        purge idempotency records past their 24 h.

        Runs for every owner holding review rows, or an expired idempotency
        record, whatever the flag state, so a rollback never suspends the
        bound and an owner who stops writing still loses the copies (FR-043,
        research R15, docs/data-retention.md).
        """

        owners = self.task_repo.review_owner_ids()
        owners |= self.task_repo.idempotency_owner_ids(
            created_before=now - IDEMPOTENCY_RETENTION
        )
        nulled = closed = 0
        for owner_id in sorted(owners):
            try:
                nulled += self._retain(owner_id, now)
                closed += self.idle_session_closer(owner_id, now)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the sweep
                _log_owner_failure(owner_id, exc, "retention")
        return nulled, closed

    def _retain(self, owner_id: str, now: datetime) -> int:
        cutoff = now - SNAPSHOT_RETENTION
        decisions = [
            decision.id
            for decision in self.task_repo.list_review_decisions(
                owner_id, decided_before=cutoff
            )
            if decision.undo is not None
        ]
        releases = [
            release.id
            for release in self.task_repo.list_bulk_releases(
                owner_id, created_before=cutoff
            )
            if any(item.clock_before is not None for item in release.released)
        ]
        nulled = 0
        with self.task_repo.command_lock(owner_id):
            # The records hold whole result documents (titles, notes, an
            # extension reason in ``clock_before``): they go at 24 h, not 7 d.
            self.task_repo.purge_expired_idempotency(owner_id=owner_id, now=now)
            for decision_id in decisions:
                decision = self.task_repo.get_review_decision(owner_id, decision_id)
                if decision is not None and decision.undo is not None:
                    self.task_repo.save_review_decision(
                        decision.model_copy(update={"undo": None})
                    )
                    nulled += 1
            for bulk_id in releases:
                release = self.task_repo.get_bulk_release(owner_id, bulk_id)
                if release is None:
                    continue
                items = [
                    item.model_copy(update={"clock_before": None})
                    for item in release.released
                ]
                self.task_repo.save_bulk_release(
                    release.model_copy(update={"released": items})
                )
                nulled += 1
            self.task_repo.delete_navigator_usage_before(
                owner_id, (now - USAGE_RETENTION).date()
            )
        return nulled

    def run_auto_park_sweep(self, now: datetime) -> tuple[int, int, int, int]:
        """The exposure part: activated owners whose flag is effective.

        Per owner: the sweep-gap floor, then clock repair and parks in owner-
        locked batches of at most 50 tasks that re-read before writing.
        Candidates are selected outside the lock; nothing here does I/O other
        than SQLite under the lock.
        """

        owners = parked = repaired = gaps = 0
        for settings in self.task_repo.list_review_settings():
            owner_id = settings.owner_id
            if settings.activated_at is None:
                continue
            try:
                if not self.is_exposed(owner_id):
                    continue
                owners += 1
                gap, owner_repaired, owner_parked = self._expose_owner(owner_id, now)
            except Exception as exc:  # noqa: BLE001 - one owner never stops the sweep
                _log_owner_failure(owner_id, exc, "exposure")
                continue
            gaps += gap
            repaired += owner_repaired
            parked += owner_parked
        return owners, parked, repaired, gaps

    def _note_effective_sweep(self, owner_id: str, now: datetime) -> bool:
        """Record an effective exposure evaluation; floor parks after a gap.

        The one sweep-gap rule (formulation-clock §3, SC-006), shared by the
        sweep and the device auto-park; the caller holds the owner lock. A gap
        of 24 h or more since ``last_effective_sweep_at`` raises
        ``owner_park_floor_at`` to ``max(existing, now + 7 d)``; either way
        ``last_effective_sweep_at`` becomes ``now``. Bookkeeping, not a
        settings change: ``revision`` stays. Returns whether there was a gap.
        """

        current = self.settings_for(owner_id)
        last = current.last_effective_sweep_at
        gap = last is None or now - last >= SWEEP_GAP
        update: dict[str, Any] = {"last_effective_sweep_at": now}
        if gap:
            floored = formulation.apply_sweep_gap(current.clock_settings(), now=now)
            update["owner_park_floor_at"] = floored.owner_park_floor_at
        self.task_repo.save_review_settings(current.model_copy(update=update))
        return gap

    def _expose_owner(self, owner_id: str, now: datetime) -> tuple[int, int, int]:
        candidates = self.task_repo.list_next_tasks(owner_id)
        with self.task_repo.command_lock(owner_id):
            current = self.task_repo.get_review_settings(owner_id)
            if current is None or current.activated_at is None:
                # Purge may finish after the preliminary exposure read. Never
                # recreate its deleted settings from the default document.
                return 0, 0, 0
            gap = self._note_effective_sweep(owner_id, now)
        clock_settings = self.settings_for(owner_id).clock_settings()
        due = [
            task.id
            for task in candidates
            if task.formulation_started_at is None
            or formulation.classify(task_clock(task), clock_settings, now) == "park_due"
        ]
        repaired = parked = 0
        for start in range(0, len(due), SWEEP_BATCH):
            batch_repaired, batch_parked = self._sweep_batch(
                owner_id, due[start : start + SWEEP_BATCH], now=now
            )
            repaired += batch_repaired
            parked += batch_parked
        return int(gap), repaired, parked

    def _sweep_batch(
        self, owner_id: str, task_ids: list[str], *, now: datetime
    ) -> tuple[int, int]:
        repaired = parked = 0
        with self.task_repo.command_lock(owner_id):
            self.task_repo.purge_expired_idempotency(owner_id=owner_id, now=now)
            for task_id in task_ids:
                try:
                    task = self.tasks.get_task(task_id, owner_id=owner_id)
                except NotFoundError:
                    continue
                if task.state != "next":
                    continue
                if task.formulation_started_at is None:
                    clock = formulation.repair_clock(
                        task_clock(task), now=now, formulation_id=generate_id("form")
                    )
                    self.task_repo.save(with_clock(task, clock))
                    repaired += 1
                    continue
                parked += self._sweep_park(task, owner_id=owner_id)
        return repaired, parked

    def _sweep_park(self, task: TaskDocument, *, owner_id: str) -> int:
        """Park with the deterministic ``auto-park:<task>:<form>:<rev>`` key (§4)."""

        key = f"auto-park:{task.id}:{task.formulation_id}:{task.revision}"
        command = f"auto-park:{task.id}"
        self._reconcile_idempotent_result(owner_id=owner_id, key=key)
        if self.task_repo.get_idempotency(owner_id=owner_id, key=key) is not None:
            return 0
        result = self._parked(task, owner_id=owner_id, source="sweep")
        if result is None:
            return 0
        self._store(
            owner_id=owner_id,
            key=key,
            command=command,
            request_hash=_sweep_hash(key),
            resource_id=task.id,
            response=result,
        )
        self._write_park(result)
        _log_park(owner_id, task.id, applied=True, source="sweep")
        return 1

    def _floor_due_dated(self, owner_id: str, *, now: datetime) -> int:
        """A zone change floors every due-dated Next task (formulation-clock §3)."""

        floored = 0
        for task in self.task_repo.list_next_tasks(owner_id):
            clock = formulation.raise_due_floor(task_clock(task), now=now)
            if clock != task_clock(task):
                self.task_repo.save(with_clock(task, clock))
                floored += 1
        return floored

    # ------------------------------------------------------------ idempotency
    def _idempotency_record(
        self, *, owner_id: str, key: str, command: str, hash_: str
    ) -> IdempotencyRecord | None:
        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is None:
            return None
        if record.command != command or record.request_hash != hash_:
            raise IdempotencyConflictError()
        return record

    def _store(  # noqa: PLR0913 - the idempotency record's fields
        self,
        *,
        owner_id: str,
        key: str,
        command: str,
        request_hash: str,
        resource_id: str,
        response: BaseModel,
    ) -> None:
        self.tasks._store_idempotency(
            owner_id=owner_id,
            key=key,
            command=command,
            request_hash=request_hash,
            resource_id=resource_id,
            response=response,
        )

    def _reconcile_idempotent_result(self, *, owner_id: str, key: str) -> None:
        """Apply one review key's recorded result left durable before its write."""

        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is not None and record.command.startswith(REVIEW_COMMAND_PREFIXES):
            self._apply_idempotent_record(record, owner_id=owner_id)

    def _apply_idempotent_record(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> None:
        """The review prefixes' reconcilers (http §9, research R7)."""

        command = record.command
        if command.startswith("decide_task:"):
            self._repair_decision(
                DecisionResultDocument.model_validate(record.response_body),
                owner_id=owner_id,
            )
        elif command.startswith("undo_decision:"):
            self._repair_undo(
                UndoResultDocument.model_validate(record.response_body),
                owner_id=owner_id,
            )
        elif command.startswith("auto-park:"):
            parked = AutoParkResultDocument.model_validate(record.response_body)
            if not parked.applied or parked.ack is None:
                return
            current = self.tasks.get_task(parked.task.id, owner_id=owner_id)
            # Re-apply only while the task is still in Next at the revision the
            # park was applied from; never over a restored task (http §4).
            if current.state == "next" and current.revision == parked.from_revision:
                self._write_park(parked)
        elif command.startswith("explainer_ack:"):
            stored = ReviewSettingsDocument.model_validate(record.response_body)
            if stored.activated_at is not None and (
                self.settings_for(owner_id).activated_at is None
            ):
                self._activate(stored)
        elif command.startswith("review_settings:"):
            stored = ReviewSettingsDocument.model_validate(record.response_body)
            if self.settings_for(owner_id).revision < stored.revision:
                self.task_repo.save_review_settings(stored)
        elif command.startswith("park_ack:"):
            self._write_parks_seen(
                ParkAcknowledgeResultDocument.model_validate(record.response_body),
                owner_id=owner_id,
            )
        else:
            self._apply_flow_record(record, owner_id=owner_id)

    def _apply_flow_record(self, record: IdempotencyRecord, *, owner_id: str) -> None:
        """The review-flow reconcilers (slice PR-11): runs and bulk releases.

        A body that does not read as its result document (a stray record) is
        left alone and logged by type only, never by its text.
        """

        prefix = next((p for p in _FLOW_RESULTS if record.command.startswith(p)), None)
        if prefix is None:
            return
        try:
            result = _FLOW_RESULTS[prefix].model_validate(record.response_body)
        except ValidationError as exc:
            logger.warning(
                "review_reconcile_skipped owner_id=%s command=%s error=%s",
                owner_id,
                prefix.rstrip(":"),
                type(exc).__name__,
            )
            return
        if isinstance(result, SessionResultDocument):
            self.write_sessions(result, owner_id=owner_id)
        elif isinstance(result, BulkReleaseResultDocument):
            self.write_bulk_release(result, owner_id=owner_id)
        elif isinstance(result, BulkUndoResultDocument):
            self.write_bulk_undo(result, owner_id=owner_id)

    # ------------------------------------------------------- review-flow writes
    def write_sessions(self, result: SessionResultDocument, *, owner_id: str) -> None:
        """Persist a run command's sessions; also the ``review_session:`` repair.

        A stored session at the same or a later revision already holds this
        write (or a later one), so it is never overwritten.
        """

        for session in (*result.replaced, result.session):
            current = self.task_repo.get_review_session(owner_id, session.id)
            if current is None or current.revision < session.revision:
                self.task_repo.save_review_session(session)

    def write_bulk_release(
        self, result: BulkReleaseResultDocument, *, owner_id: str
    ) -> None:
        """Persist a bulk release; also the ``bulk_release:`` repair.

        Applied only while its record row is absent, and per task only while
        the task is still at the revision the release was applied from.
        """

        release = result.release
        if self.task_repo.get_bulk_release(owner_id, release.id) is not None:
            return
        written: set[str] = set()
        for task in result.tasks:
            current = self._task_or_none(owner_id, task.id)
            if current is not None and current.revision == task.revision - 1:
                self.task_repo.save(task)
                written.add(task.id)
        for receipt in result.receipts:
            if receipt.task_id in written:
                self.task_repo.save_review_receipt(receipt)
        self.task_repo.save_bulk_release(release)

    def write_bulk_undo(self, result: BulkUndoResultDocument, *, owner_id: str) -> None:
        """Persist a bulk-release Undo; also the ``undo_bulk_release:`` repair.

        Applied only while the stored release is not yet undone; each task only
        while it is still at the revision the Undo restored it from. The
        release receipt is deleted only when this release wrote it (E5).
        """

        release = result.release
        current_release = self.task_repo.get_bulk_release(owner_id, release.id)
        if current_release is None or current_release.undone_at is not None:
            return
        for task in result.tasks:
            current = self._task_or_none(owner_id, task.id)
            if current is None or current.revision != task.revision - 1:
                continue
            self.task_repo.save(task)
            receipt = self.task_repo.get_review_receipt(owner_id, task.id, "someday")
            if receipt is not None and receipt.bulk_id == release.id:
                self.task_repo.delete_review_receipt(owner_id, task.id, "someday")
        self.task_repo.save_bulk_release(release)

    def _task_or_none(self, owner_id: str, task_id: str) -> TaskDocument | None:
        try:
            return self.tasks.get_task(task_id, owner_id=owner_id)
        except NotFoundError:
            return None

    def _repair_decision(
        self, result: DecisionResultDocument, *, owner_id: str
    ) -> None:
        """Re-apply a decision whose record outlived its write; never twice.

        A decision row that exists means the write landed; a task that moved
        past the stored revision (an Undo, a later edit) is never overwritten.
        """

        if self.task_repo.get_review_decision(owner_id, result.decision.id) is not None:
            return
        try:
            current = self.tasks.get_task(result.task.id, owner_id=owner_id)
        except NotFoundError:
            return
        if current.revision >= result.task.revision:
            return
        self._write_decision(result, owner_id=owner_id, previous=current)

    def _repair_undo(self, result: UndoResultDocument, *, owner_id: str) -> None:
        decision = self.task_repo.get_review_decision(
            owner_id, result.undone_decision_id
        )
        if decision is None:
            return
        current = self.tasks.get_task(result.task.id, owner_id=owner_id)
        if current.revision >= result.task.revision:
            return
        self._write_undo(result, decision, owner_id=owner_id)

    # ------------------------------------------------------------------ logs
    def _refuse(
        self, event: str, owner_id: str, task_id: str, reason: str
    ) -> ReviewRequestError:
        logger.info(
            "%s owner_id=%s task_id=%s outcome=%s", event, owner_id, task_id, reason
        )
        return review_error(reason)

    @staticmethod
    def _log_rejection(
        owner_id: str, task_id: str, decision_type: str, reason: str
    ) -> None:
        logger.info(
            "review_decision owner_id=%s task_id=%s type=%s outcome=%s",
            owner_id,
            task_id,
            decision_type,
            reason,
        )

    @staticmethod
    def _log_decision(
        result: DecisionResultDocument, *, outcome: str, started: float
    ) -> None:
        decision = result.decision
        logger.info(
            "review_decision owner_id=%s decision_id=%s task_id=%s type=%s "
            "session_linked=%s ai_use=%s yielded=%s outcome=%s duration_ms=%d",
            decision.owner_id,
            decision.id,
            decision.task_id,
            decision.type,
            decision.session_id is not None,
            decision.ai_use,
            decision.yielded_auto_park,
            outcome,
            _elapsed_ms(started),
        )

    # ------------------------------------------------------------------ reads
    def settings_for(self, owner_id: str) -> ReviewSettingsDocument:
        stored = self.task_repo.get_review_settings(owner_id)
        return (
            stored if stored is not None else ReviewSettingsDocument(owner_id=owner_id)
        )

    def state(self, *, owner_id: str) -> ReviewStateView:
        """The review state of one owner at the service clock (http §5)."""

        now = self.clock()
        settings = self.settings_for(owner_id)
        clock_settings = settings.clock_settings()
        tasks = self.task_repo.list_for_owner(owner_id=owner_id)
        # A receipt hides its task only while the task is still at the revision
        # it was written for (data-model E5); a changed task is listed again.
        revisions = {task.id: task.revision for task in tasks}
        asks = moves_tomorrow = 0
        for task in tasks:
            klass = formulation.classify(task_clock(task), clock_settings, now)
            asks += formulation.asks_for_decision(klass)
            moves_tomorrow += klass == "moves_tomorrow"
        sessions = self.task_repo.list_review_sessions(owner_id)
        last_counted_at = review_rules.last_counted_review_at(
            _summary(session) for session in sessions
        )
        return ReviewStateView(
            settings=settings,
            explainer_seen=settings.activated_at is not None,
            grace_until=(
                None
                if settings.activated_at is None
                else settings.activated_at + ACTIVATION_GRACE
            ),
            last_counted_review_at=last_counted_at,
            last_counted_review=_last_counted_review(sessions),
            next_review_at=review_rules.next_review_at(
                review_weekday=settings.review_weekday,
                review_time=settings.review_time,
                time_zone=settings.time_zone,
                now=now,
                last_counted_review_at=last_counted_at,
            ),
            restart_mode=review_rules.restart_mode(
                onboarded_at=settings.onboarded_at,
                last_counted_review_at=last_counted_at,
                now=now,
            ),
            open_session=_open_session(sessions),
            unseen_parks=self._unseen_parks(owner_id, tasks),
            asks_for_decision=asks,
            moves_tomorrow=moves_tomorrow,
            receipts=[
                receipt
                for receipt in self.task_repo.list_review_receipts(owner_id)
                if now < receipt.hidden_until
                and revisions.get(receipt.task_id) == receipt.task_revision
            ],
            server_now=now,
        )

    def _unseen_parks(
        self, owner_id: str, tasks: list[TaskDocument]
    ) -> list[UnseenPark]:
        """Tasks parked automatically whose park the person has not seen (E6)."""

        unseen: list[UnseenPark] = []
        for task in tasks:
            parked = task.parked
            if parked is None or task.state != "someday":
                continue
            ack = self.task_repo.get_park_ack(owner_id, task.id, parked.formulation_id)
            if ack is not None and ack.seen_at is not None:
                continue
            unseen.append(UnseenPark(task.id, parked.formulation_id, parked.at))
        return sorted(unseen, key=lambda park: (park.parked_at, park.task_id))


_NOT_IANA = frozenset({"localtime", "posixrules", "Factory"})
"""Files some hosts keep beside the tz database that are not IANA zone names."""


@lru_cache(maxsize=1)
def _iana_zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones()) - _NOT_IANA


def is_iana_zone(name: str) -> bool:
    """An IANA zone name the server can evaluate (``zoneinfo``), nothing else."""

    return name in _iana_zones()


def _changed_settings(
    current: ReviewSettingsDocument,
    payload: ReviewSettingsUpdateRequest,
    *,
    now: datetime,
) -> ReviewSettingsDocument:
    """The settings after a PUT, before any revision bump (equal is no change)."""

    update: dict[str, Any] = {}
    if payload.threshold_days is not None and (
        payload.threshold_days != current.threshold_days
    ):
        changed = formulation.change_threshold(
            current.clock_settings(), to=payload.threshold_days, now=now
        )
        update["threshold_days"] = payload.threshold_days
        update["threshold_changed_at"] = now
        update["owner_park_floor_at"] = changed.owner_park_floor_at
    if payload.review_weekday is not None:
        update["review_weekday"] = payload.review_weekday
    if payload.review_time is not None:
        update["review_time"] = payload.review_time
    if payload.time_zone is not None:
        update["time_zone"] = payload.time_zone
    if payload.onboarded and current.onboarded_at is None:
        update["onboarded_at"] = now
    return current.model_copy(update=update)


def _sweep_hash(key: str) -> str:
    """The request hash of a sweep park: its deterministic key says it all."""

    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _log_park(owner_id: str, task_id: str, *, applied: bool, source: str) -> None:
    logger.info(
        "review_auto_park applied=%s source=%s yielded=False owner_id=%s task_id=%s",
        applied,
        source,
        owner_id,
        task_id,
    )


def _log_owner_failure(owner_id: str, exc: Exception, reason: str) -> None:
    """Exception type and a reason code only: never ``str(exc)`` (http §9)."""

    logger.warning(
        "review_sweep_owner_failed owner_id=%s error=%s reason=%s",
        owner_id,
        type(exc).__name__,
        reason,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _required(value: str | None) -> str:
    if value is None:  # pragma: no cover - the request schema requires it
        raise ValueError("this decision needs its text field")
    return value


def _decision_matches(
    stored: ReviewDecisionDocument, task_id: str, payload: DecisionRequest
) -> bool:
    """Identifying fields of a decision (http "Retry after the retention")."""

    return (
        stored.task_id == task_id
        and stored.type == payload.type
        and stored.formulation_id == payload.formulation_id
    )


def _yields(task: TaskDocument, payload: DecisionRequest) -> bool:
    """The auto-park yield rule (http §3, research R9).

    The park reverses for a card decision on the parked formulation, made
    before the park (device time), whose ``expected_revision`` lies between the
    park's ``from_revision`` and the current revision: plain edits replayed onto
    the parked task in between do not defeat it.
    """

    parked = task.parked
    decided = payload.client_decided_at
    return (
        task.state == "someday"
        and parked is not None
        and decided is not None
        and "next" in _ALLOWED_STATES[payload.type]
        and payload.formulation_id == parked.formulation_id
        and parked.from_revision <= payload.expected_revision <= task.revision
        and decided < parked.at
    )


def _reverse_park(task: TaskDocument) -> TaskDocument:
    """Restore ``parked.clock_before`` exactly, back in Next (no revision bump)."""

    clock = formulation.reverse_park(task_clock(task))
    return with_clock(task, clock).model_copy(update={"state": "next"})


def _summary(session: ReviewSessionDocument) -> review_rules.SessionSummary:
    return review_rules.SessionSummary(
        status=session.status,
        qualifying_activity=session.qualifying_activity,
        last_activity_at=session.last_activity_at,
        ended_at=session.ended_at,
    )


def _counted_instant(session: ReviewSessionDocument) -> datetime:
    if session.status == "completed" and session.ended_at is not None:
        return session.ended_at
    return session.last_activity_at


def _last_counted_review(
    sessions: list[ReviewSessionDocument],
) -> ReviewSessionDocument | None:
    """The most recent completed or partial session (http §5, SC-007)."""

    ended = [s for s in sessions if s.status in ("completed", "partial")]
    if not ended:
        return None
    return max(ended, key=lambda session: (_counted_instant(session), session.id))


def _open_session(
    sessions: list[ReviewSessionDocument],
) -> ReviewSessionDocument | None:
    open_ones = [s for s in sessions if s.status == "open"]
    if not open_ones:
        return None
    return max(open_ones, key=lambda session: (session.started_at, session.id))


__all__ = ["ReviewService", "ReviewStateView", "UnseenPark"]
