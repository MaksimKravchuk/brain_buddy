"""Records of the native-task weekly review (spec 020, data-model E2 – E9).

Every record is owned by the Tasks module and stored in ``tasks.sqlite3``
(ADR-0027 §1). They are storage documents: unknown legacy fields are ignored,
and every id is an opaque label of the fixed shape the HTTP schemas validate.
This module also holds the two converters between ``TaskDocument`` and the pure
rule's ``TaskClock``, and the one review error type the API maps to the
``{"message", "detail": {"reason"}}`` envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.exceptions import BrainBuddyError
from app.schemas.common import StorageBaseModel

from . import formulation
from .domain import (
    ClockBeforeDocument,
    FormulationSettingsDocument,
    TaskDocument,
    TaskParkDocument,
)

ThresholdDays = Literal[7, 14, 21, 28]
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
StallReason = Literal[
    "unclear",
    "too_big",
    "missing_info",
    "waiting_on_someone",
    "no_energy",
    "no_longer_matters",
]
AiUse = Literal["none", "as_is", "edited", "not_used"]
CountBucket = Literal[
    "done",
    "reformulated",
    "first_step",
    "waiting",
    "someday",
    "cancelled",
    "extended",
    "inbox_processed",
    "kept",
    "moved_to_next",
]
ReceiptKind = Literal["waiting", "someday"]
ReceiptSource = Literal["keep", "release"]
ParkSource = Literal["sweep", "device"]
SessionStatus = Literal["open", "completed", "completed_empty", "partial", "abandoned"]

REVIEW_COUNTS_AS: dict[str, CountBucket] = {
    "complete": "done",
    "reformulate": "reformulated",
    "first_step": "first_step",
    "waiting": "waiting",
    "someday": "someday",
    "cancel": "cancelled",
    "extend": "extended",
    "keep_waiting": "kept",
    "keep_someday": "kept",
    "follow_up": "moved_to_next",
    "return_to_next": "moved_to_next",
}
"""data-model E4 ``review_counts_as`` (FR-033)."""

REVIEW_COMMAND_PREFIXES: tuple[str, ...] = (
    "decide_task:",
    "undo_decision:",
    "auto-park:",
    "bulk_release:",
    "undo_bulk_release:",
    "review_session:",
    "review_settings:",
    "explainer_ack:",
    "park_ack:",
)
"""Idempotency command prefixes owned by ``ReviewService`` (http §9, R7).

``TaskService`` never reconciles these: their stored bodies are composite
review results, not ``TaskDocument`` snapshots.
"""

REVIEW_TABLES: tuple[str, ...] = (
    "review_settings",
    "review_sessions",
    "review_decisions",
    "review_receipts",
    "review_park_acks",
    "review_bulk_releases",
    "navigator_consents",
    "navigator_usage",
)


class ReviewRequestError(BrainBuddyError):
    """A review request refused with a reason code (contracts/http.md).

    Rendered as ``{"message": message, "detail": {"reason": reason}}`` with the
    given status. The message is fixed copy and never echoes request content.
    """

    def __init__(self, status_code: int, reason: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message


# ------------------------------------------------------------------- E2
class ReviewSettingsDocument(StorageBaseModel):
    """One row per owner (data-model E2)."""

    owner_id: str
    activated_at: datetime | None = None
    last_effective_sweep_at: datetime | None = None
    onboarded_at: datetime | None = None
    threshold_days: ThresholdDays = 14
    threshold_changed_at: datetime | None = None
    owner_park_floor_at: datetime | None = None
    review_weekday: int = Field(default=5, ge=1, le=7)
    review_time: str = Field(
        default="16:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
    )
    time_zone: str = Field(default="UTC", min_length=1, max_length=64)
    revision: int = Field(default=1, ge=1)

    def clock_settings(self) -> formulation.OwnerClockSettings:
        return formulation.OwnerClockSettings(
            threshold_days=self.threshold_days,
            time_zone=self.time_zone,
            owner_park_floor_at=self.owner_park_floor_at,
            activated_at=self.activated_at,
        )


# ------------------------------------------------------------------- E3
class SessionCountsDocument(StorageBaseModel):
    """The ten FR-033 summary counters."""

    done: int = Field(default=0, ge=0)
    reformulated: int = Field(default=0, ge=0)
    first_step: int = Field(default=0, ge=0)
    waiting: int = Field(default=0, ge=0)
    someday: int = Field(default=0, ge=0)
    cancelled: int = Field(default=0, ge=0)
    extended: int = Field(default=0, ge=0)
    inbox_processed: int = Field(default=0, ge=0)
    kept: int = Field(default=0, ge=0)
    moved_to_next: int = Field(default=0, ge=0)


class StepStateDocument(StorageBaseModel):
    status: Literal["pending", "finished", "skipped"] = "pending"
    finished_empty: bool = False


class ReviewSessionDocument(StorageBaseModel):
    """A guided review run (data-model E3); written by the flow slice."""

    id: str
    owner_id: str
    mode: Literal["quick", "full"]
    entry: Literal["list", "notification", "widget_decisions", "sidebar", "restart"]
    origin: Literal["ios", "web", "macos"]
    status: SessionStatus = "open"
    started_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None = None
    current_step: str | None = None
    steps: dict[str, StepStateDocument] = Field(default_factory=dict)
    active_seconds_by_step: dict[str, int] = Field(default_factory=dict)
    decision_queue: list[str] = Field(default_factory=list)
    set_aside_task_ids: list[str] = Field(default_factory=list)
    applied_progress: dict[str, str] = Field(default_factory=dict)
    counts: SessionCountsDocument = Field(default_factory=SessionCountsDocument)
    qualifying_activity: bool = False
    clear_start: Literal["yes", "not_really"] | None = None
    revision: int = Field(default=1, ge=1)


# ------------------------------------------------------------------- E4
class DecisionUndoDocument(StorageBaseModel):
    """The content-bearing undo snapshot; nulled 7 days after the decision."""

    task_before: TaskDocument
    created_task_id: str | None = None
    created_task_revision: int | None = None
    receipt_kind: ReceiptKind | None = None


class ReviewDecisionDocument(StorageBaseModel):
    """One recorded decision (data-model E4)."""

    id: str
    owner_id: str
    task_id: str
    session_id: str | None = None
    decided_at: datetime
    type: DecisionType
    stall_reason: StallReason | None = None
    substantive: bool | None = None
    ai_use: AiUse = "none"
    navigator_request_id: str | None = None
    formulation_id: str | None = None
    task_revision_before: int = Field(ge=1)
    task_revision_after: int = Field(ge=1)
    reason_text: str | None = Field(default=None, min_length=1, max_length=500)
    undo: DecisionUndoDocument | None = None
    client_decided_at: datetime | None = None
    review_counts_as: CountBucket
    yielded_auto_park: bool = False
    created_task_id: str | None = None


class DecisionResultDocument(StorageBaseModel):
    """One decision's outcome: the idempotency record body and the response.

    ``formulation_settings`` is the snapshot both tasks' ``formulation`` is
    projected with, so a replay is the original response (http "Mutations");
    ``None`` (an older record, or the matching-record replay built from the
    task as it now is) projects with the live settings.
    """

    decision: ReviewDecisionDocument
    task: TaskDocument
    created_task: TaskDocument | None = None
    receipt: ReviewReceiptDocument | None = None
    session_counts: SessionCountsDocument | None = None
    formulation_settings: FormulationSettingsDocument | None = None


class UndoResultDocument(StorageBaseModel):
    """One decision undo's outcome (http §3)."""

    task: TaskDocument
    undone_decision_id: str
    deleted_task_id: str | None = None
    session_counts: SessionCountsDocument | None = None
    formulation_settings: FormulationSettingsDocument | None = None


# ------------------------------------------------------------------- E5
class ReviewReceiptDocument(StorageBaseModel):
    """One current receipt per task and kind (data-model E5)."""

    owner_id: str
    task_id: str
    kind: ReceiptKind
    task_revision: int = Field(ge=1)
    reviewed_at: datetime
    hidden_until: datetime
    source: ReceiptSource
    decision_id: str | None = None
    bulk_id: str | None = None


# ------------------------------------------------------------------- E6
class ReviewParkAckDocument(StorageBaseModel):
    """A park and whether the person saw it or returned it (data-model E6)."""

    owner_id: str
    task_id: str
    formulation_id: str
    parked_at: datetime
    from_revision: int = Field(ge=1)
    source: ParkSource
    seen_at: datetime | None = None
    returned_at: datetime | None = None


class AutoParkResultDocument(StorageBaseModel):
    """One auto-park attempt (http §4); ``applied: false`` is a success."""

    applied: bool
    task: TaskDocument
    from_revision: int | None = None
    ack: ReviewParkAckDocument | None = None
    formulation_settings: FormulationSettingsDocument | None = None


class ParkAckKeyDocument(StorageBaseModel):
    """One ``review_park_acks`` key (ids only)."""

    task_id: str
    formulation_id: str


class ParkAcknowledgeResultDocument(StorageBaseModel):
    """One park acknowledgement (http §5): the idempotency record body.

    ``marked`` lists the rows this request moved from unseen to seen at
    ``seen_at``; the ``park_ack:`` reconciler re-applies exactly those. Ids
    only: the request carries no content.
    """

    seen_at: datetime
    marked: list[ParkAckKeyDocument] = Field(default_factory=list)


# ------------------------------------------------------------------- E7
class ReleasedClockDocument(StorageBaseModel):
    formulation_id: str
    started_at: datetime
    extended_at: datetime | None = None
    extension_reason: str | None = None
    park_floor_at: datetime | None = None
    stalled_before: int = Field(default=0, ge=0)


class BulkReleasedItemDocument(StorageBaseModel):
    task_id: str
    revision_after: int = Field(ge=1)
    previous_state: Literal["next", "inbox"]
    clock_before: ReleasedClockDocument | None = None


class BulkSkippedItemDocument(StorageBaseModel):
    task_id: str
    reason: Literal["stale", "not_eligible"]


class ReviewBulkReleaseDocument(StorageBaseModel):
    """A restart or Inbox-remainder release (data-model E7)."""

    id: str
    owner_id: str
    kind: Literal["restart", "inbox_remainder"]
    session_id: str | None = None
    released: list[BulkReleasedItemDocument] = Field(default_factory=list)
    skipped: list[BulkSkippedItemDocument] = Field(default_factory=list)
    created_at: datetime
    undone_at: datetime | None = None
    undo_result: dict[str, Any] | None = None


# ------------------------------------------------------------------- E8, E9
class NavigatorConsentDocument(StorageBaseModel):
    owner_id: str
    provider: str
    granted_at: datetime
    revoked_at: datetime | None = None
    consent_text_version: int = Field(ge=1)
    history: list[dict[str, Any]] = Field(default_factory=list)


class NavigatorUsageDocument(StorageBaseModel):
    owner_id: str
    day: date
    calls: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)
    reserved_cost_usd: float = Field(default=0.0, ge=0)
    shown: int = Field(default=0, ge=0)


# ----------------------------------------------------- clock <-> task document
@dataclass(frozen=True, slots=True)
class FormulationView:
    """``TaskResponse.formulation``: raw clock plus advisory derived instants."""

    id: str
    started_at: datetime
    extended_at: datetime | None
    extension_reason: str | None
    park_floor_at: datetime | None
    consecutive_stalled: int
    ageing_at: datetime | None
    ask_at: datetime | None
    park_due_at: datetime | None
    paused_until: datetime | None


def task_clock(task: TaskDocument) -> formulation.TaskClock:
    """The pure rule's view of a task document."""

    parked = task.parked
    return formulation.TaskClock(
        state=task.state,
        title=task.title,
        revision=task.revision,
        formulation_id=task.formulation_id,
        formulation_started_at=task.formulation_started_at,
        formulation_extended_at=task.formulation_extended_at,
        formulation_extension_reason=task.formulation_extension_reason,
        formulation_park_floor_at=task.formulation_park_floor_at,
        consecutive_stalled_formulations=task.consecutive_stalled_formulations,
        due_date=task.due_date,
        parked=(
            None
            if parked is None
            else formulation.ParkMarker(
                at=parked.at,
                formulation_id=parked.formulation_id,
                from_revision=parked.from_revision,
                clock_before=formulation.ClockBefore(
                    started_at=parked.clock_before.started_at,
                    extended_at=parked.clock_before.extended_at,
                    extension_reason=parked.clock_before.extension_reason,
                    park_floor_at=parked.clock_before.park_floor_at,
                    stalled_before=parked.clock_before.stalled_before,
                ),
            )
        ),
    )


def clock_fields(clock: formulation.TaskClock) -> dict[str, Any]:
    """The clock fields of a ``TaskClock`` as ``TaskDocument`` updates.

    State, title and revision are deliberately left out: the task commands own
    those, the rule only decides the clock.
    """

    parked = clock.parked
    return {
        "formulation_id": clock.formulation_id,
        "formulation_started_at": clock.formulation_started_at,
        "formulation_extended_at": clock.formulation_extended_at,
        "formulation_extension_reason": clock.formulation_extension_reason,
        "formulation_park_floor_at": clock.formulation_park_floor_at,
        "consecutive_stalled_formulations": clock.consecutive_stalled_formulations,
        "parked": (
            None
            if parked is None
            else TaskParkDocument(
                at=parked.at,
                formulation_id=parked.formulation_id,
                from_revision=parked.from_revision,
                clock_before=ClockBeforeDocument(
                    started_at=parked.clock_before.started_at,
                    extended_at=parked.clock_before.extended_at,
                    extension_reason=parked.clock_before.extension_reason,
                    park_floor_at=parked.clock_before.park_floor_at,
                    stalled_before=parked.clock_before.stalled_before,
                ),
            )
        ),
    }


def with_clock(task: TaskDocument, clock: formulation.TaskClock) -> TaskDocument:
    """``task`` with the clock fields of ``clock`` (no other field changes)."""

    return task.model_copy(update=clock_fields(clock))


def formulation_view(
    task: TaskDocument, settings: formulation.OwnerClockSettings
) -> FormulationView | None:
    """http §2: null unless the task is in Next with a started clock."""

    started = task.formulation_started_at
    if task.state != "next" or started is None or task.formulation_id is None:
        return None
    instants = formulation.derive_instants(task_clock(task), settings)
    return FormulationView(
        id=task.formulation_id,
        started_at=started,
        extended_at=task.formulation_extended_at,
        extension_reason=task.formulation_extension_reason,
        park_floor_at=task.formulation_park_floor_at,
        consecutive_stalled=task.consecutive_stalled_formulations,
        ageing_at=instants.ageing_at if instants else None,
        ask_at=instants.ask_at if instants else None,
        park_due_at=instants.park_due_at if instants else None,
        paused_until=instants.paused_until if instants else None,
    )


DecisionResultDocument.model_rebuild()

__all__ = [
    "REVIEW_COMMAND_PREFIXES",
    "REVIEW_COUNTS_AS",
    "AutoParkResultDocument",
    "DecisionResultDocument",
    "UndoResultDocument",
    "REVIEW_TABLES",
    "BulkReleasedItemDocument",
    "BulkSkippedItemDocument",
    "DecisionUndoDocument",
    "FormulationView",
    "NavigatorConsentDocument",
    "NavigatorUsageDocument",
    "ParkAckKeyDocument",
    "ParkAcknowledgeResultDocument",
    "ReleasedClockDocument",
    "ReviewBulkReleaseDocument",
    "ReviewDecisionDocument",
    "ReviewParkAckDocument",
    "ReviewReceiptDocument",
    "ReviewRequestError",
    "ReviewSessionDocument",
    "ReviewSettingsDocument",
    "SessionCountsDocument",
    "StepStateDocument",
    "clock_fields",
    "formulation_view",
    "task_clock",
    "with_clock",
]
