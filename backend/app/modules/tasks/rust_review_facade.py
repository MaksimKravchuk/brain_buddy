"""Python facade that delegates Review and formulation-clock rules to the Rust core.

Spec 026 T019, the Review counterpart of ``rust_task_facade``. While the
``rust_core_sync`` flag is on for an owner, ``ReviewService`` and
``ReviewFlowService`` ask this facade for the decision of ``review.decide``,
``review.undo_decision``, ``review.auto_park``, ``review.parks_ack``,
``review.settings``, ``review.explainer_ack``, the three ``review.session_*``
commands and the two ``review.bulk_*`` commands, and for the ``ReviewState`` and
``ReviewQueue`` reads. The formulation-clock, park, decision and session rules
all live behind that one call; nothing here repeats one of them.

The Python half of the boundary (runtime-ffi.md "Pure core") stays Python:

* the protected read set is loaded from the existing repositories, scoped to the
  records the command needs, under the owner lock the service already holds;
* the private Undo snapshot, the park clock-before and the progress digests ride
  in the read set's ``private`` members and come back in the returned records,
  which are mapped to the stored documents; the shared core never sees a
  password, provider reservation, cost cap or storage handle;
* the idempotency record, the legacy matching-record replay, the reconcilers and
  every write stay with the services, which write the returned documents inside
  their own transaction. Nothing here commits a second one.

Native IDs for created records (``review_<uuid>``, ``decision_<uuid>``,
``bulk_<uuid>``, ``task_<uuid>``) are minted here, because the core's creation
rules refuse the legacy 12-hex shape for a new record.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.schemas.review import (
    AutoParkRequest,
    BulkReleaseRequest,
    DecisionRequest,
    ExplainerAcknowledgeRequest,
    ParkAcknowledgeRequest,
    ReviewSettingsUpdateRequest,
    SessionFinishRequest,
    SessionProgressRequest,
    SessionStartRequest,
    UndoDecisionRequest,
)
from app.utils.identifiers import generate_id

from .domain import (
    ProjectDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from .repository import TaskRepository
from .review_domain import (
    AutoParkResultDocument,
    BulkReleasedItemDocument,
    BulkSkippedItemDocument,
    DecisionResultDocument,
    DecisionUndoDocument,
    ParkAckKeyDocument,
    ParkAcknowledgeResultDocument,
    ReleasedClockDocument,
    ReviewBulkReleaseDocument,
    ReviewDecisionDocument,
    ReviewParkAckDocument,
    ReviewReceiptDocument,
    ReviewSessionDocument,
    ReviewSettingsDocument,
    SessionCountsDocument,
    StepStateDocument,
    UndoResultDocument,
)
from .rust_adapter import Decision, DomainRefusal, RustBridgeError, RustCore
from .rust_task_facade import (
    _encode_park_ack,
    _envelope,
    _inputs,
    _native_id,
    _parse_instant,
    _refused,
    decode_task,
    encode_project,
    encode_settings,
    encode_task,
    instant,
)

review_logger = logging.getLogger("app.modules.tasks.review")

# Reasons the Review REST adapter answers with its own fixed-copy error type
# (contracts/http.md §3 - §6); the service turns a ``ReviewRefused`` into it.
_REVIEW_REASONS: Final = frozenset(
    {
        "decision_not_allowed",
        "extension_already_used",
        "extension_not_due",
        "project_archived",
        "undo_unavailable",
        "invalid_time_zone",
    }
)
_RESOURCES: Final[dict[str, str]] = {
    "task": "Task",
    "project": "Project",
    "review_decision": "Review decision",
    "review_bulk_release": "Review bulk release",
    "review_session": "Review session",
}
# The owner-wide singleton commands name the REST scope as their entity.
_OWNER_SCOPE: Final = "rest"
# Types that leave the task's revision alone: the locator of a repeated decision.
_LEAVES_REVISION: Final = frozenset({"keep_waiting", "keep_someday", "follow_up"})

Json = dict[str, Any]


class ReviewRefused(Exception):
    """A refusal that Review answers with its own error type.

    ``reason`` is the stable code of contracts/http.md (``id_conflict``,
    ``open_session_exists``, ``step_outside_run`` ...); ``entity_id`` names the
    record the refusal is about and ``field`` the request field, when it has one.
    """

    def __init__(
        self, reason: str, *, entity_id: str | None = None, field: str | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.entity_id = entity_id
        self.field = field


# ------------------------------------------------------------------ outcomes


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """One decided ``review.decide``.

    ``applied``: ``result`` is new and ``previous`` is the task as the decision
    saw it (after an auto-park yield). ``matching``: the decision id was already
    stored and ``stored`` is that record. ``repeated``: the run already holds
    this card's decision, ``stored`` is the first one.
    """

    kind: Literal["applied", "matching", "repeated"]
    result: DecisionResultDocument | None = None
    previous: TaskDocument | None = None
    acks: list[ReviewParkAckDocument] = field(default_factory=list)
    session: ReviewSessionDocument | None = None
    stored: ReviewDecisionDocument | None = None


@dataclass(frozen=True, slots=True)
class UndoOutcome:
    result: UndoResultDocument
    decision: ReviewDecisionDocument
    acks: list[ReviewParkAckDocument]
    session: ReviewSessionDocument | None


@dataclass(frozen=True, slots=True)
class SettingsOutcome:
    """Settings after ``review.settings`` or ``review.explainer_ack``."""

    current: ReviewSettingsDocument
    updated: ReviewSettingsDocument
    tasks: list[TaskDocument]
    changed: bool


@dataclass(frozen=True, slots=True)
class ParkOutcome:
    result: AutoParkResultDocument
    settings: ReviewSettingsDocument | None


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    """A session command: the run, any run it replaced, and whether it changed."""

    session: ReviewSessionDocument
    replaced: list[ReviewSessionDocument]
    changed: bool


@dataclass(frozen=True, slots=True)
class BulkReleaseOutcome:
    release: ReviewBulkReleaseDocument
    tasks: list[TaskDocument]
    receipts: list[ReviewReceiptDocument]
    changed: bool


@dataclass(frozen=True, slots=True)
class BulkUndoOutcome:
    release: ReviewBulkReleaseDocument
    tasks: list[TaskDocument]
    changed: bool


@dataclass(frozen=True, slots=True)
class StateAnswer:
    """``ReviewState`` decoded: ids resolved to the stored documents."""

    explainer_seen: bool
    grace_until: datetime | None
    last_counted_review_at: datetime | None
    last_counted_review: ReviewSessionDocument | None
    next_review_at: datetime
    restart_mode: bool
    open_session: ReviewSessionDocument | None
    unseen_parks: list[tuple[str, str, datetime]]
    asks_for_decision: int
    moves_tomorrow: int
    receipts: list[ReviewReceiptDocument]
    server_now: datetime


@dataclass(frozen=True, slots=True)
class QueueAnswer:
    items: list[TaskDocument]
    meta: Json


# ------------------------------------------------------- read-set encoding


def encode_settings_private(settings: ReviewSettingsDocument) -> Json:
    """Owner settings with the server-private sweep bookkeeping."""

    return {
        **encode_settings(settings),
        "private": {
            "last_effective_sweep_at": _optional(settings.last_effective_sweep_at),
            "threshold_changed_at": _optional(settings.threshold_changed_at),
        },
    }


def _optional(value: datetime | None) -> str | None:
    return None if value is None else instant(value)


def encode_session(session: ReviewSessionDocument) -> Json:
    return {
        "id": session.id,
        "mode": session.mode,
        "entry": session.entry,
        "origin": session.origin,
        "status": session.status,
        "started_at": instant(session.started_at),
        "last_activity_at": instant(session.last_activity_at),
        "ended_at": _optional(session.ended_at),
        "current_step": session.current_step,
        "steps": {code: step.status for code, step in session.steps.items()},
        "active_seconds_by_step": dict(session.active_seconds_by_step),
        "counts": session.counts.model_dump(),
        "set_aside_count": len(session.set_aside_task_ids),
        "qualifying_activity": session.qualifying_activity,
        "clear_start": session.clear_start,
        "revision": str(session.revision),
        "private": {
            "applied_progress": dict(session.applied_progress),
            "finished_empty": [
                code for code, step in session.steps.items() if step.finished_empty
            ],
        },
    }


def encode_queue(session: ReviewSessionDocument) -> Json:
    """The stored decision queue of a run (its snapshot and its set-aside list)."""

    return {
        "session_id": session.id,
        "task_ids": session.decision_queue,
        "decided_task_ids": [],
        "set_aside_task_ids": list(session.set_aside_task_ids),
    }


def encode_decision(decision: ReviewDecisionDocument, *, private: bool) -> Json:
    """A stored decision; ``private`` adds the server-only Undo snapshot."""

    undo = decision.undo
    return {
        "id": decision.id,
        "type": decision.type,
        "task_id": decision.task_id,
        "session_id": decision.session_id,
        "decided_at": instant(decision.decided_at),
        "substantive": decision.substantive,
        "stall_reason": decision.stall_reason,
        "ai_use": decision.ai_use,
        "yielded_auto_park": decision.yielded_auto_park,
        "formulation_id": decision.formulation_id,
        "task_revision_before": str(decision.task_revision_before),
        "task_revision_after": str(decision.task_revision_after),
        "created_task_id": decision.created_task_id,
        "navigator_request_id": decision.navigator_request_id,
        "review_counts_as": decision.review_counts_as,
        "client_decided_at": _optional(decision.client_decided_at),
        "reason_text": decision.reason_text,
        "undo_available_until": None,
        **(
            {}
            if not private or undo is None
            else {
                "private": {
                    "task_before": encode_task(undo.task_before),
                    "created_task_revision": (
                        None
                        if undo.created_task_revision is None
                        else str(undo.created_task_revision)
                    ),
                    "receipt_kind": undo.receipt_kind,
                }
            }
        ),
    }


def encode_receipt(receipt: ReviewReceiptDocument) -> Json:
    return {
        "task_id": receipt.task_id,
        "kind": receipt.kind,
        "hidden_until": instant(receipt.hidden_until),
        "task_revision": str(receipt.task_revision),
        "reviewed_at": instant(receipt.reviewed_at),
        "source": receipt.source,
        "decision_id": receipt.decision_id,
        "bulk_id": receipt.bulk_id,
    }


def _encode_released_clock(clock: ReleasedClockDocument | None) -> Json | None:
    if clock is None:
        return None
    return {
        "formulation_id": clock.formulation_id,
        "started_at": instant(clock.started_at),
        "extended_at": _optional(clock.extended_at),
        "extension_reason": clock.extension_reason,
        "park_floor_at": _optional(clock.park_floor_at),
        "stalled_before": clock.stalled_before,
    }


def encode_release(release: ReviewBulkReleaseDocument) -> Json:
    return {
        "id": release.id,
        "kind": release.kind,
        "session_id": release.session_id,
        "created_at": instant(release.created_at),
        "undone_at": _optional(release.undone_at),
        "released": [
            {
                "task_id": item.task_id,
                "revision_after": str(item.revision_after),
                "private": {
                    "previous_state": item.previous_state,
                    "clock_before": _encode_released_clock(item.clock_before),
                },
            }
            for item in release.released
        ],
        "skipped": [
            {"task_id": item.task_id, "reason": item.reason} for item in release.skipped
        ],
        "undo": release.undo_result,
    }


def _encode_subtask(subtask: TaskSubtaskDocument) -> Json:
    return {
        "id": subtask.id,
        "task_id": subtask.task_id,
        "title": subtask.title,
        "state": subtask.state,
        "order_key": str(subtask.order_key),
        "revision": str(subtask.revision),
    }


def _encode_comment(comment: TaskCommentDocument) -> Json:
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "body": comment.body,
        "actor_id": comment.actor_id,
        "created_at": instant(comment.created_at),
        "edited_at": _optional(comment.edited_at),
        "revision": str(comment.revision),
    }


# ------------------------------------------------------- change decoding


@dataclass(frozen=True, slots=True)
class _Records:
    """The records of one change set by kind, in the core's write order."""

    tasks: list[Json] = field(default_factory=list)
    acks: list[Json] = field(default_factory=list)
    sessions: list[Json] = field(default_factory=list)
    queues: list[Json] = field(default_factory=list)
    decisions: list[Json] = field(default_factory=list)
    receipts: list[Json] = field(default_factory=list)
    settings: list[Json] = field(default_factory=list)
    releases: list[Json] = field(default_factory=list)
    tombstones: list[tuple[str, list[str]]] = field(default_factory=list)


_KINDS: Final[dict[str, str]] = {
    "task": "tasks",
    "review_park_ack": "acks",
    "review_session": "sessions",
    "review_decision_queue": "queues",
    "review_decision": "decisions",
    "review_receipt": "receipts",
    "review_settings": "settings",
    "review_bulk_release": "releases",
}


def _records(change_set: Json) -> _Records:
    records = _Records()
    for change in change_set["changes"]:
        if change["operation"] == "upsert":
            attribute = _KINDS.get(change["entity_type"])
            if attribute is None:
                raise ValidationFailure(
                    "Command failed validation.", {"reason": "unexpected_record"}
                )
            getattr(records, attribute).append(change["value"])
        else:
            records.tombstones.append((change["entity_type"], change["record_key"]))
    return records


def decode_settings(value: Json, *, owner_id: str) -> ReviewSettingsDocument:
    private = value.get("private") or {}
    return ReviewSettingsDocument.model_validate(
        {
            "owner_id": owner_id,
            "activated_at": value["activated_at"],
            "last_effective_sweep_at": private.get("last_effective_sweep_at"),
            "onboarded_at": value["onboarded_at"],
            "threshold_days": value["threshold_days"],
            "threshold_changed_at": private.get("threshold_changed_at"),
            "owner_park_floor_at": value["owner_park_floor_at"],
            "review_weekday": value["review_weekday"],
            "review_time": value["review_time"],
            "time_zone": value["time_zone"],
            "revision": int(value["revision"]),
        }
    )


def decode_session(
    value: Json,
    *,
    owner_id: str,
    before: ReviewSessionDocument | None,
    queue: Json | None,
) -> ReviewSessionDocument:
    """A run from the core's record plus the queue row that changed with it."""

    private = value.get("private") or {"applied_progress": {}, "finished_empty": []}
    empty = set(private["finished_empty"])
    decision_queue = None if before is None else before.decision_queue
    set_aside = [] if before is None else list(before.set_aside_task_ids)
    if queue is not None:
        decision_queue = queue["task_ids"]
        set_aside = list(queue["set_aside_task_ids"])
    return ReviewSessionDocument(
        id=value["id"],
        owner_id=owner_id,
        mode=value["mode"],
        entry=value["entry"],
        origin=value["origin"],
        status=value["status"],
        started_at=value["started_at"],
        last_activity_at=value["last_activity_at"],
        ended_at=value["ended_at"],
        current_step=value["current_step"],
        steps={
            code: StepStateDocument(status=status, finished_empty=code in empty)
            for code, status in value["steps"].items()
        },
        active_seconds_by_step=dict(value["active_seconds_by_step"]),
        decision_queue=decision_queue,
        set_aside_task_ids=set_aside,
        applied_progress=dict(private["applied_progress"]),
        counts=SessionCountsDocument.model_validate(value["counts"]),
        qualifying_activity=value["qualifying_activity"],
        clear_start=value["clear_start"],
        revision=int(value["revision"]),
    )


def decode_receipt(value: Json, *, owner_id: str) -> ReviewReceiptDocument:
    return ReviewReceiptDocument.model_validate(
        {
            "owner_id": owner_id,
            "task_id": value["task_id"],
            "kind": value["kind"],
            "task_revision": int(value["task_revision"]),
            "reviewed_at": value["reviewed_at"],
            "hidden_until": value["hidden_until"],
            "source": value["source"],
            "decision_id": value["decision_id"],
            "bulk_id": value["bulk_id"],
        }
    )


def decode_ack(
    value: Json, *, owner_id: str, before: ReviewParkAckDocument | None = None
) -> ReviewParkAckDocument:
    """A park row; the server-private members fall back to the stored row."""

    private = value.get("private")
    return ReviewParkAckDocument.model_validate(
        {
            "owner_id": owner_id,
            "task_id": value["task_id"],
            "formulation_id": value["formulation_id"],
            "parked_at": value["parked_at"],
            "from_revision": (
                int(private["from_revision"])
                if private is not None
                else before.from_revision if before is not None else None
            ),
            "source": (
                private["source"]
                if private is not None
                else before.source if before is not None else None
            ),
            "seen_at": value["seen_at"],
            "returned_at": value["returned_at"],
        }
    )


def decode_release(value: Json, *, owner_id: str) -> ReviewBulkReleaseDocument:
    released = []
    for item in value["released"]:
        private = item["private"]
        clock = private["clock_before"]
        released.append(
            BulkReleasedItemDocument(
                task_id=item["task_id"],
                revision_after=int(item["revision_after"]),
                previous_state=private["previous_state"],
                clock_before=(
                    None
                    if clock is None
                    else ReleasedClockDocument.model_validate(clock)
                ),
            )
        )
    return ReviewBulkReleaseDocument(
        id=value["id"],
        owner_id=owner_id,
        kind=value["kind"],
        session_id=value["session_id"],
        released=released,
        skipped=[
            BulkSkippedItemDocument(task_id=item["task_id"], reason=item["reason"])
            for item in value["skipped"]
        ],
        created_at=value["created_at"],
        undone_at=value["undone_at"],
        undo_result=value["undo"],
    )


def decode_decision(
    value: Json, *, owner_id: str, task: TaskDocument | None
) -> ReviewDecisionDocument:
    """A recorded decision with its Undo snapshot (the writer is authoritative)."""

    private = value.get("private")
    undo = None
    if private is not None:
        revision = private["created_task_revision"]
        undo = DecisionUndoDocument(
            task_before=decode_task(
                private["task_before"], before=task, owner_id=owner_id
            ),
            created_task_id=value["created_task_id"],
            created_task_revision=None if revision is None else int(revision),
            receipt_kind=private["receipt_kind"],
        )
    return ReviewDecisionDocument.model_validate(
        {
            "id": value["id"],
            "owner_id": owner_id,
            "task_id": value["task_id"],
            "session_id": value["session_id"],
            "decided_at": value["decided_at"],
            "type": value["type"],
            "stall_reason": value["stall_reason"],
            "substantive": value["substantive"],
            "ai_use": value["ai_use"],
            "navigator_request_id": value["navigator_request_id"],
            "formulation_id": value["formulation_id"],
            "task_revision_before": int(value["task_revision_before"]),
            "task_revision_after": int(value["task_revision_after"]),
            "reason_text": value["reason_text"],
            "undo": undo,
            "client_decided_at": value["client_decided_at"],
            "review_counts_as": value["review_counts_as"],
            "yielded_auto_park": value["yielded_auto_park"],
            "created_task_id": value["created_task_id"],
        }
    )


# ----------------------------------------------------------- refusal mapping


def _refusal_error(refusal: DomainRefusal, owner_id: str) -> Exception:
    """The exception the Review REST adapter has always raised for a refusal."""

    entity_type, key = refusal.entity or ("", [])
    identifier = key[0] if key else ""
    review = _review_refusal(refusal, entity_type, identifier)
    if review is not None:
        return review
    reason = refusal.reason
    if reason == "formulation_changed":
        return _stale_task(identifier)
    if reason == "revision_conflict" and entity_type == "review_settings":
        return ConflictError(
            "Review settings",
            owner_id,
            "Review settings have newer changes; reload before saving.",
        )
    if reason in {"not_found", "session_not_found"}:
        return NotFoundError(_RESOURCES.get(entity_type, "Record"), identifier)
    if reason == "incomplete_read_set":
        if entity_type == "project":
            return NotFoundError("Project", identifier)
        # A fact this facade should have loaded: a server defect, never input.
        return RustBridgeError("INTERNAL_ERROR", False, None)
    return _refused(refusal)


def _review_refusal(
    refusal: DomainRefusal, entity_type: str, identifier: str
) -> ReviewRefused | None:
    """The refusals Review answers with a fixed reason code of its own."""

    reason = refusal.reason
    if reason in _REVIEW_REASONS:
        return ReviewRefused(reason, entity_id=identifier or None)
    if reason == "text_length" and refusal.field == "details":
        return ReviewRefused("details_too_long")
    if reason == "step_not_in_review":
        return ReviewRefused("step_outside_run", field=refusal.field)
    if reason != "id_already_exists":
        return None
    if entity_type == "review_session" and refusal.field == "replace_open":
        return ReviewRefused("open_session_exists", entity_id=identifier)
    return ReviewRefused("id_conflict", entity_id=identifier or None)


def _stale_task(task_id: str) -> ConflictError:
    return ConflictError(
        "Task", task_id, f"Task '{task_id}' has newer changes; reload before saving."
    )


def _first_of_run(
    payload: DecisionRequest,
    task: TaskDocument,
    earlier: list[ReviewDecisionDocument],
) -> ReviewDecisionDocument | None:
    """The run's first decision the core named a repeat of.

    The core decides that this card was decided already; the adapter only finds
    the stored record to answer with: a cosmetic reformulate of the same
    formulation, or a keep/follow-up of the task as that decision left it.
    """

    for decision in earlier:
        if payload.type == "reformulate":
            if (
                decision.type == "reformulate"
                and decision.substantive is False
                and decision.formulation_id == payload.formulation_id
            ):
                return decision
        elif (
            decision.type in _LEAVES_REVISION
            and decision.task_revision_after == task.revision
        ):
            return decision
    return None


# ---------------------------------------------------------------- the facade


class RustReviewFacade:
    """Decides Review and formulation-clock commands with the shared Rust rules."""

    def __init__(self, core: RustCore, task_repo: TaskRepository) -> None:
        self._core = core
        self._repo = task_repo

    # ------------------------------------------------------------ decisions

    def decide(
        self,
        task_id: str,
        payload: DecisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> DecisionOutcome:
        """``POST /tasks/{id}/decisions``.

        The core settles the matching stored decision first, then the task, so a
        retry after the retention answers as it always has.
        """

        repo = self._repo
        task = self._task_or_none(owner_id, task_id)
        decision_id = payload.decision_id or _native_id("decision")
        matching = (
            None
            if payload.decision_id is None
            else repo.get_review_decision(owner_id, decision_id)
        )
        session = (
            None
            if payload.session_id is None
            else repo.get_review_session(owner_id, payload.session_id)
        )
        earlier = (
            []
            if session is None
            else [
                d
                for d in repo.list_review_decisions_for_session(owner_id, session.id)
                if d.task_id == task_id
            ]
        )
        read_set = self._read_set(
            owner_id, tasks=[] if task is None else [task], settings=True
        )
        stored_acks: dict[tuple[str, str], ReviewParkAckDocument] = {}
        if task is not None:
            stored_acks = self._acks_of(
                owner_id,
                task.id,
                [None if task.parked is None else task.parked.formulation_id]
                + [payload.formulation_id],
            )
            self._decide_references(read_set, task, payload, owner_id)
        read_set["park_acks"] = [_encode_park_ack(a) for a in stored_acks.values()]
        stored_decisions = {d.id: d for d in earlier}
        if matching is not None:
            stored_decisions[matching.id] = matching
        if stored_decisions:
            read_set["decisions"] = {
                d.id: encode_decision(d, private=False)
                for d in stored_decisions.values()
            }
        if session is not None:
            read_set["sessions"] = {session.id: encode_session(session)}
        allocated = [generate_id("form")]
        if payload.type == "follow_up" and payload.follow_up_task_id is None:
            allocated.insert(0, _native_id("task"))
        change_set = self._call(
            "review.decide",
            task_id,
            _decide_body(payload, decision_id),
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=("task", task_id, payload.expected_revision),
            allocated=allocated,
        )
        if change_set["outcome"] == "no_op" and matching is not None:
            # The stored decision of this id: the service answers from it, as it
            # always did, even when its task has gone since.
            return DecisionOutcome("matching", stored=matching)
        assert task is not None
        if change_set["outcome"] == "no_op":
            first = _first_of_run(payload, task, earlier)
            if first is None:
                raise RustBridgeError("INTERNAL_ERROR", False, None)
            return DecisionOutcome("repeated", stored=first)
        return self._applied_decision(change_set, task, owner_id, stored_acks, session)

    def _decide_references(
        self,
        read_set: Json,
        task: TaskDocument,
        payload: DecisionRequest,
        owner_id: str,
    ) -> None:
        """What a follow-up or a return to Next reads besides the task itself."""

        if payload.type not in ("follow_up", "return_to_next"):
            return
        if task.project_id is not None:
            project = self._project_or_none(owner_id, task.project_id)
            if project is not None:
                read_set["projects"][project.id] = encode_project(project)
        if payload.type != "follow_up":
            return
        # The new task's order key follows the Next list; its id must be free.
        for other in self._repo.list_next_tasks(owner_id):
            read_set["tasks"][other.id] = encode_task(other)
        if payload.follow_up_task_id is not None:
            taken = self._task_or_none(owner_id, payload.follow_up_task_id)
            if taken is not None:
                read_set["tasks"][taken.id] = encode_task(taken)

    @staticmethod
    def _applied_decision(
        change_set: Json,
        task: TaskDocument,
        owner_id: str,
        stored_acks: dict[tuple[str, str], ReviewParkAckDocument],
        session: ReviewSessionDocument | None,
    ) -> DecisionOutcome:
        records = _records(change_set)
        decision = decode_decision(records.decisions[0], owner_id=owner_id, task=task)
        assert decision.undo is not None
        previous = decision.undo.task_before
        updated, created = previous, None
        for value in records.tasks:
            if value["id"] == task.id:
                updated = decode_task(value, before=task, owner_id=owner_id)
            else:
                created = decode_task(value, before=None, owner_id=owner_id)
        acks = [
            decode_ack(
                value,
                owner_id=owner_id,
                before=stored_acks.get((value["task_id"], value["formulation_id"])),
            )
            for value in records.acks
        ]
        if (
            previous.parked is not None
            and previous.state == "someday"
            and updated.state == "next"
            and not acks
        ):
            review_logger.warning(
                "review_park_return_unrecorded owner_id=%s task_id=%s formulation_id=%s",
                owner_id,
                task.id,
                previous.parked.formulation_id,
            )
        return DecisionOutcome(
            "applied",
            result=DecisionResultDocument(
                decision=decision,
                task=updated,
                created_task=created,
                receipt=(
                    decode_receipt(records.receipts[0], owner_id=owner_id)
                    if records.receipts
                    else None
                ),
                session_counts=_counts_of(records),
            ),
            previous=previous,
            acks=acks,
            session=_session_of(records, owner_id, session),
        )

    def undo_decision(
        self,
        decision_id: str,
        payload: UndoDecisionRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> UndoOutcome:
        """``POST /review/decisions/{id}/undo``."""

        repo = self._repo
        decision = repo.get_review_decision(owner_id, decision_id)
        read_set = self._read_set(owner_id, settings=True)
        expected = None
        task = None
        linked: ReviewSessionDocument | None = None
        stored_acks: dict[tuple[str, str], ReviewParkAckDocument] = {}
        if decision is not None:
            expected = ("task", decision.task_id, payload.expected_task_revision)
            task = self._task_or_none(owner_id, decision.task_id)
            if task is not None:
                read_set["tasks"][task.id] = encode_task(task)
            read_set["decisions"] = {
                decision.id: encode_decision(decision, private=True)
            }
            undo = decision.undo
            if decision.created_task_id is not None:
                self._created_task_into(read_set, owner_id, decision.created_task_id)
            if undo is not None and undo.receipt_kind is not None:
                receipt = repo.get_review_receipt(
                    owner_id, decision.task_id, undo.receipt_kind
                )
                if receipt is not None:
                    read_set["receipts"] = [encode_receipt(receipt)]
            if undo is not None and undo.task_before.parked is not None:
                stored_acks = self._acks_of(
                    owner_id,
                    decision.task_id,
                    [undo.task_before.parked.formulation_id],
                )
                read_set["park_acks"] = [
                    _encode_park_ack(a) for a in stored_acks.values()
                ]
            if decision.session_id is not None:
                linked = repo.get_review_session(owner_id, decision.session_id)
                if linked is not None:
                    read_set["sessions"] = {linked.id: encode_session(linked)}
        change_set = self._call(
            "review.undo_decision",
            decision_id,
            {},
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=expected,
        )
        records = _records(change_set)
        assert decision is not None and task is not None
        restored = decode_task(records.tasks[0], before=task, owner_id=owner_id)
        return UndoOutcome(
            UndoResultDocument(
                task=restored,
                undone_decision_id=decision.id,
                deleted_task_id=change_set["result"]["deleted_task_id"],
                session_counts=_counts_of(records),
            ),
            decision,
            [
                decode_ack(
                    value,
                    owner_id=owner_id,
                    before=stored_acks.get((value["task_id"], value["formulation_id"])),
                )
                for value in records.acks
            ],
            _session_of(records, owner_id, linked),
        )

    def _created_task_into(
        self, read_set: Json, owner_id: str, created_id: str
    ) -> None:
        """The follow-up a decision created, with the rows an Undo must not delete."""

        created = self._task_or_none(owner_id, created_id)
        if created is None:
            return
        read_set["tasks"][created.id] = encode_task(created)
        read_set["subtasks"] = {
            s.id: _encode_subtask(s)
            for s in self._repo.list_subtasks(owner_id=owner_id, task_id=created.id)
        }
        read_set["comments"] = {
            c.id: _encode_comment(c)
            for c in self._repo.list_comments(owner_id=owner_id, task_id=created.id)
        }

    # ------------------------------------------------- settings, activation

    def update_settings(
        self,
        payload: ReviewSettingsUpdateRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> SettingsOutcome:
        """``PUT /review/settings``."""

        read_set = self._read_set(owner_id, settings=True)
        floored: list[TaskDocument] = []
        if payload.time_zone is not None:
            # A zone change floors every due-dated Next task.
            floored = self._next_tasks_into(read_set, owner_id)
        body = payload.model_dump(mode="json", exclude_none=True)
        del body["expected_revision"]
        change_set = self._call(
            "review.settings",
            _OWNER_SCOPE,
            body,
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            expected=("review_settings", _OWNER_SCOPE, payload.expected_revision),
        )
        return self._settings_outcome(change_set, owner_id, floored)

    def acknowledge_explainer(
        self,
        payload: ExplainerAcknowledgeRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> SettingsOutcome:
        """``POST /review/explainer/acknowledge``: the first one activates."""

        read_set = self._read_set(owner_id, settings=True)
        next_tasks = self._next_tasks_into(read_set, owner_id)
        change_set = self._call(
            "review.explainer_ack",
            _OWNER_SCOPE,
            payload.model_dump(mode="json", exclude_none=True),
            owner_id=owner_id,
            now=now,
            read_set=read_set,
            # A Next task without a clock starts one with the next of these.
            allocated=[generate_id("form") for _ in next_tasks],
        )
        return self._settings_outcome(change_set, owner_id, next_tasks)

    def _settings_outcome(
        self, change_set: Json, owner_id: str, loaded: list[TaskDocument]
    ) -> SettingsOutcome:
        current = self._current_settings(owner_id)
        if change_set["outcome"] == "no_op":
            return SettingsOutcome(current, current, [], False)
        records = _records(change_set)
        before = {task.id: task for task in loaded}
        return SettingsOutcome(
            current,
            decode_settings(records.settings[0], owner_id=owner_id),
            [
                decode_task(value, before=before[value["id"]], owner_id=owner_id)
                for value in records.tasks
            ],
            True,
        )

    # ------------------------------------------------------------ auto-park

    def auto_park(
        self,
        task: TaskDocument,
        payload: AutoParkRequest,
        *,
        owner_id: str,
        now: datetime,
        exposed: bool,
    ) -> ParkOutcome:
        """``POST /tasks/{id}/auto-park``: a park a device observed."""

        change_set = self._call(
            "review.auto_park",
            task.id,
            {"formulation_id": payload.formulation_id},
            owner_id=owner_id,
            now=now,
            read_set=self._read_set(owner_id, tasks=[task], settings=True),
            exposed=exposed,
        )
        records = _records(change_set)
        settings = (
            decode_settings(records.settings[0], owner_id=owner_id)
            if records.settings
            else None
        )
        if not change_set["result"]["applied"]:
            return ParkOutcome(
                AutoParkResultDocument(applied=False, task=task), settings
            )
        ack = decode_ack(records.acks[0], owner_id=owner_id)
        parked = decode_task(records.tasks[0], before=task, owner_id=owner_id)
        return ParkOutcome(
            AutoParkResultDocument(
                applied=True, task=parked, from_revision=ack.from_revision, ack=ack
            ),
            settings,
        )

    def acknowledge_parks(
        self,
        payload: ParkAcknowledgeRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> ParkAcknowledgeResultDocument:
        """``POST /review/parks/acknowledge``: unseen rows named by the request."""

        keys = list(dict.fromkeys((i.task_id, i.formulation_id) for i in payload.items))
        stored = [
            ack
            for task_id, formulation_id in keys
            if (ack := self._repo.get_park_ack(owner_id, task_id, formulation_id))
        ]
        read_set = self._read_set(owner_id)
        read_set["park_acks"] = [_encode_park_ack(ack) for ack in stored]
        change_set = self._call(
            "review.parks_ack",
            _OWNER_SCOPE,
            {
                "items": [
                    {"task_id": task_id, "formulation_id": formulation_id}
                    for task_id, formulation_id in keys
                ]
            },
            owner_id=owner_id,
            now=now,
            read_set=read_set,
        )
        seen = {
            (value["task_id"], value["formulation_id"])
            for value in _records(change_set).acks
        }
        return ParkAcknowledgeResultDocument(
            seen_at=now,
            marked=[
                ParkAckKeyDocument(task_id=task_id, formulation_id=formulation_id)
                for task_id, formulation_id in keys
                if (task_id, formulation_id) in seen
            ],
        )

    # ------------------------------------------------------------- sessions

    def start_session(
        self,
        payload: SessionStartRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> SessionOutcome:
        """``POST /review/sessions``: a run, and any open run it replaces."""

        session_id = payload.id or _native_id("review")
        stored = (
            None
            if payload.id is None
            else self._repo.get_review_session(owner_id, payload.id)
        )
        runs = {run.id: run for run in self._repo.list_open_review_sessions(owner_id)}
        if stored is not None:
            runs[stored.id] = stored
        body = payload.model_dump(mode="json", exclude_none=True)
        body.pop("id", None)
        change_set = self._call(
            "review.session_start",
            session_id,
            body,
            owner_id=owner_id,
            now=now,
            read_set={"sessions": {r.id: encode_session(r) for r in runs.values()}},
        )
        if change_set["outcome"] == "no_op":
            assert stored is not None
            return SessionOutcome(stored, [], False)
        sessions = [
            decode_session(
                value, owner_id=owner_id, before=runs.get(value["id"]), queue=None
            )
            for value in _records(change_set).sessions
        ]
        return SessionOutcome(sessions[-1], sessions[:-1], True)

    def progress_session(
        self,
        session_id: str,
        payload: SessionProgressRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> SessionOutcome:
        """``PATCH /review/sessions/{id}``: merged, replay-safe by ``progress_id``."""

        session = self._repo.get_review_session(owner_id, session_id)
        read_set = self._read_set(owner_id, settings=True)
        if session is not None:
            read_set["sessions"] = {session.id: encode_session(session)}
            read_set["decision_queues"] = {session.id: encode_queue(session)}
        if payload.set_aside_task_id is not None:
            aside = self._task_or_none(owner_id, payload.set_aside_task_id)
            if aside is not None:
                read_set["tasks"][aside.id] = encode_task(aside)
        finishes = payload.step is not None and payload.step.status == "finished"
        if finishes or payload.snapshot_decision_queue:
            # The step's queue and the decision aggregate read the whole owner.
            self._snapshot_into(read_set, owner_id)
        change_set = self._call(
            "review.session_progress",
            session_id,
            payload.model_dump(mode="json", exclude_none=True),
            owner_id=owner_id,
            now=now,
            read_set=read_set,
        )
        return self._session_outcome(change_set, session, owner_id)

    def finish_session(
        self,
        session_id: str,
        payload: SessionFinishRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> SessionOutcome:
        """``POST /review/sessions/{id}/finish``: Done on the summary."""

        session = self._repo.get_review_session(owner_id, session_id)
        read_set: Json = {}
        if session is not None:
            read_set["sessions"] = {session.id: encode_session(session)}
        change_set = self._call(
            "review.session_finish",
            session_id,
            payload.model_dump(mode="json", exclude_none=True),
            owner_id=owner_id,
            now=now,
            read_set=read_set,
        )
        return self._session_outcome(change_set, session, owner_id)

    @staticmethod
    def _session_outcome(
        change_set: Json, session: ReviewSessionDocument | None, owner_id: str
    ) -> SessionOutcome:
        assert session is not None
        if change_set["outcome"] == "no_op":
            return SessionOutcome(session, [], False)
        records = _records(change_set)
        queue = records.queues[0] if records.queues else None
        return SessionOutcome(
            decode_session(
                records.sessions[0], owner_id=owner_id, before=session, queue=queue
            ),
            [],
            True,
        )

    # --------------------------------------------------------- bulk release

    def bulk_release(
        self,
        payload: BulkReleaseRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> BulkReleaseOutcome:
        """``POST /review/bulk-releases``: the accepted subset commits once."""

        repo = self._repo
        bulk_id = payload.id or _native_id("bulk")
        existing = (
            None if payload.id is None else repo.get_bulk_release(owner_id, payload.id)
        )
        named = list(dict.fromkeys(item.task_id for item in payload.items))
        tasks = [
            task
            for task_id in named
            if (task := self._task_or_none(owner_id, task_id)) is not None
        ]
        read_set = self._read_set(owner_id, tasks=tasks, settings=True)
        if existing is not None:
            read_set["bulk_releases"] = {existing.id: encode_release(existing)}
        if payload.session_id is not None:
            session = repo.get_review_session(owner_id, payload.session_id)
            if session is not None:
                read_set["sessions"] = {session.id: encode_session(session)}
        body: Json = {
            "kind": payload.kind,
            "items": [
                {"task_id": i.task_id, "expected_revision": str(i.expected_revision)}
                for i in payload.items
            ],
        }
        if payload.session_id is not None:
            body["session_id"] = payload.session_id
        change_set = self._call(
            "review.bulk_release",
            bulk_id,
            body,
            owner_id=owner_id,
            now=now,
            read_set=read_set,
        )
        if change_set["outcome"] == "no_op":
            assert existing is not None
            return BulkReleaseOutcome(existing, [], [], False)
        records = _records(change_set)
        before = {t.id: t for t in tasks}
        return BulkReleaseOutcome(
            decode_release(records.releases[0], owner_id=owner_id),
            [
                decode_task(v, before=before[v["id"]], owner_id=owner_id)
                for v in records.tasks
            ],
            [decode_receipt(v, owner_id=owner_id) for v in records.receipts],
            True,
        )

    def undo_bulk_release(
        self, bulk_id: str, *, owner_id: str, now: datetime
    ) -> BulkUndoOutcome:
        """``POST /review/bulk-releases/{id}/undo``."""

        repo = self._repo
        release = repo.get_bulk_release(owner_id, bulk_id)
        read_set = self._read_set(owner_id)
        tasks: dict[str, TaskDocument] = {}
        if release is not None:
            read_set["bulk_releases"] = {release.id: encode_release(release)}
            receipts = []
            for item in release.released:
                task = self._task_or_none(owner_id, item.task_id)
                if task is not None:
                    tasks[task.id] = task
                    read_set["tasks"][task.id] = encode_task(task)
                receipt = repo.get_review_receipt(owner_id, item.task_id, "someday")
                if receipt is not None:
                    receipts.append(encode_receipt(receipt))
            read_set["receipts"] = receipts
        change_set = self._call(
            "review.bulk_undo",
            bulk_id,
            {},
            owner_id=owner_id,
            now=now,
            read_set=read_set,
        )
        assert release is not None
        if change_set["outcome"] == "no_op":
            return BulkUndoOutcome(release, [], False)
        records = _records(change_set)
        return BulkUndoOutcome(
            decode_release(records.releases[0], owner_id=owner_id),
            [
                decode_task(v, before=tasks[v["id"]], owner_id=owner_id)
                for v in records.tasks
            ],
            True,
        )

    # ---------------------------------------------------------------- reads

    def state(self, *, owner_id: str, now: datetime) -> StateAnswer:
        """``GET /review/state``: the derived view of the owner's Review rows."""

        repo = self._repo
        sessions = {s.id: s for s in repo.list_review_sessions(owner_id)}
        receipts = repo.list_review_receipts(owner_id)
        read_set = self._read_set(
            owner_id, tasks=repo.list_for_owner(owner_id=owner_id), settings=True
        )
        read_set["sessions"] = {s.id: encode_session(s) for s in sessions.values()}
        read_set["receipts"] = [encode_receipt(r) for r in receipts]
        read_set["park_acks"] = [
            _encode_park_ack(a) for a in repo.list_park_acks(owner_id)
        ]
        value = self._query(read_set, {"kind": "review_state"}, now)
        held = {(r.task_id, r.kind): r for r in receipts}
        last = value["last_counted_review"]
        opened = value["open_session"]
        return StateAnswer(
            explainer_seen=value["explainer_seen"],
            grace_until=_parse_instant(value["grace_until"]),
            last_counted_review_at=_parse_instant(value["last_counted_review_at"]),
            last_counted_review=None if last is None else sessions[last["session_id"]],
            next_review_at=_required(_parse_instant(value["next_review_at"])),
            restart_mode=value["restart_mode"],
            open_session=None if opened is None else sessions[opened["id"]],
            unseen_parks=[
                (
                    p["task_id"],
                    p["formulation_id"],
                    _required(_parse_instant(p["parked_at"])),
                )
                for p in value["unseen_parks"]
            ],
            asks_for_decision=value["counts"]["asks_for_decision"],
            moves_tomorrow=value["counts"]["moves_tomorrow"],
            receipts=[held[(r["task_id"], r["kind"])] for r in value["receipts"]],
            server_now=_required(_parse_instant(value["server_now"])),
        )

    def queue(
        self, step: str, *, owner_id: str, session_id: str | None, now: datetime
    ) -> QueueAnswer:
        """``GET /review/queues/{step}``: the cards and the step's own metadata."""

        repo = self._repo
        tasks = {t.id: t for t in repo.list_for_owner(owner_id=owner_id)}
        read_set = self._read_set(owner_id, tasks=list(tasks.values()), settings=True)
        read_set["projects"] = {
            p.id: encode_project(p)
            for p in repo.list_projects_for_owner(owner_id=owner_id)
        }
        read_set["receipts"] = [
            encode_receipt(r) for r in repo.list_review_receipts(owner_id)
        ]
        session = (
            None
            if session_id is None
            else repo.get_review_session(owner_id, session_id)
        )
        if session is not None:
            read_set["sessions"] = {session.id: encode_session(session)}
            read_set["decision_queues"] = {session.id: encode_queue(session)}
            read_set["decisions"] = {
                d.id: encode_decision(d, private=False)
                for d in repo.list_review_decisions_for_session(owner_id, session.id)
            }
        try:
            value = self._query(
                read_set,
                {"kind": "review_queue", "step": step, "session_id": session_id},
                now,
            )
        except ValidationFailure as refused:
            if refused.detail == {"reason": "session_not_found"}:
                raise NotFoundError("Review session", session_id or "") from None
            raise
        return QueueAnswer(
            [tasks[item["id"]] for item in value["items"]], value["meta"]
        )

    # ------------------------------------------------------------ internals

    def _call(
        self,
        command_type: str,
        entity_id: str,
        body: Json,
        *,
        owner_id: str,
        now: datetime,
        read_set: Json,
        expected: tuple[str, str, int] | None = None,
        allocated: list[str] | None = None,
        exposed: bool = False,
    ) -> Json:
        """One command asked of the core once; a refusal raises its exception."""

        inputs = _inputs(now, owner_id)
        if allocated is not None:
            inputs["allocated_ids"] = allocated
        inputs["policy"]["weekly_review"] = exposed
        decision: Decision = self._core.decide(
            read_set, _envelope(command_type, entity_id, body, now, expected), inputs
        )
        if decision.refusal is not None:
            raise _refusal_error(decision.refusal, owner_id)
        assert decision.change_set is not None
        return decision.change_set

    def _query(self, read_set: Json, query: Json, now: datetime) -> Json:
        """A Review read; the weekly-review gate is the route's, so it is open."""

        inputs = {
            "now": instant(now),
            "device_zone": "UTC",
            "policy": {
                "weekly_review": True,
                "navigator_provider": None,
                "navigator_available": False,
                "consent_text_version": 1,
            },
        }
        value: Json = self._core.query(read_set, query, inputs)["value"]
        return value

    def _read_set(
        self,
        owner_id: str,
        *,
        tasks: list[TaskDocument] | None = None,
        settings: bool = False,
    ) -> Json:
        read_set: Json = {
            "tasks": {t.id: encode_task(t) for t in tasks or []},
            "projects": {},
        }
        if settings:
            stored = self._repo.get_review_settings(owner_id)
            if stored is not None:
                read_set["settings"] = encode_settings_private(stored)
        return read_set

    def _snapshot_into(self, read_set: Json, owner_id: str) -> None:
        """Every task, project and receipt of the owner (the Review snapshot)."""

        repo = self._repo
        for task in repo.list_for_owner(owner_id=owner_id):
            read_set["tasks"][task.id] = encode_task(task)
        for project in repo.list_projects_for_owner(owner_id=owner_id):
            read_set["projects"][project.id] = encode_project(project)
        read_set["receipts"] = [
            encode_receipt(r) for r in repo.list_review_receipts(owner_id)
        ]

    def _next_tasks_into(self, read_set: Json, owner_id: str) -> list[TaskDocument]:
        tasks = self._repo.list_next_tasks(owner_id)
        for task in tasks:
            read_set["tasks"][task.id] = encode_task(task)
        return tasks

    def _acks_of(
        self, owner_id: str, task_id: str, formulation_ids: list[str | None]
    ) -> dict[tuple[str, str], ReviewParkAckDocument]:
        acks: dict[tuple[str, str], ReviewParkAckDocument] = {}
        for formulation_id in formulation_ids:
            if formulation_id is None:
                continue
            ack = self._repo.get_park_ack(owner_id, task_id, formulation_id)
            if ack is not None:
                acks[(ack.task_id, ack.formulation_id)] = ack
        return acks

    def _current_settings(self, owner_id: str) -> ReviewSettingsDocument:
        stored = self._repo.get_review_settings(owner_id)
        return (
            stored if stored is not None else ReviewSettingsDocument(owner_id=owner_id)
        )

    def _task_or_none(self, owner_id: str, task_id: str) -> TaskDocument | None:
        try:
            return self._repo.get_for_owner(task_id, owner_id=owner_id)
        except NotFoundError:
            return None

    def _project_or_none(
        self, owner_id: str, project_id: str
    ) -> ProjectDocument | None:
        try:
            return self._repo.get_project_for_owner(project_id, owner_id=owner_id)
        except NotFoundError:
            return None


# ------------------------------------------------------------------ helpers


def _decide_body(payload: DecisionRequest, decision_id: str) -> Json:
    body = payload.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"expected_revision", "client_decided_at"},
    )
    body["decision_id"] = decision_id
    if payload.client_decided_at is not None:
        body["client_decided_at"] = instant(payload.client_decided_at)
    return body


def _session_of(
    records: _Records, owner_id: str, stored: ReviewSessionDocument | None
) -> ReviewSessionDocument | None:
    """The linked run a decision or its Undo moved, as the core wrote it."""

    if not records.sessions:
        return None
    return decode_session(
        records.sessions[0], owner_id=owner_id, before=stored, queue=None
    )


def _counts_of(records: _Records) -> SessionCountsDocument | None:
    if not records.sessions:
        return None
    return SessionCountsDocument.model_validate(records.sessions[0]["counts"])


def _required(value: datetime | None) -> datetime:
    assert value is not None
    return value


__all__ = [
    "BulkReleaseOutcome",
    "BulkUndoOutcome",
    "DecisionOutcome",
    "ParkOutcome",
    "QueueAnswer",
    "ReviewRefused",
    "RustReviewFacade",
    "SessionOutcome",
    "SettingsOutcome",
    "StateAnswer",
    "UndoOutcome",
]
