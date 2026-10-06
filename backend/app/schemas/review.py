"""HTTP contracts of the weekly review (spec 020, contracts/http.md §3 – §7).

Pinned by ``tests/fixtures/review_wire_fixtures.json``, whose byte-identical
copies the iOS DTO tests and Vitest decode. Every model forbids unknown fields
(``StrictBaseModel``). Client-supplied ids have one fixed shape per field
(``<prefix>_<lowercase uuid>``, at most 64 characters), so no free text can
travel in an id into tables, exports or logs; fields that refer to an existing
record also accept the server-minted ``<prefix>_<12 hex>`` shape.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from .common import StrictBaseModel
from .tasks import TaskResponse

__all__ = [
    "AutoParkRequest",
    "AutoParkResponse",
    "BulkReleaseRequest",
    "BulkReleaseResponse",
    "BulkReleaseUndoResponse",
    "DecisionRequest",
    "DecisionResponse",
    "ExplainerAcknowledgeRequest",
    "NavigatorConsentGrantRequest",
    "NavigatorStatusResponse",
    "NavigatorSuggestionRequest",
    "NavigatorSuggestionResponse",
    "ParkAcknowledgeRequest",
    "QueueResponse",
    "ReviewSettingsResponse",
    "ReviewSettingsUpdateRequest",
    "ReviewStateResponse",
    "SessionFinishRequest",
    "SessionProgressRequest",
    "SessionResponse",
    "SessionStartRequest",
    "UndoDecisionRequest",
    "UndoDecisionResponse",
]

CLIENT_ID_MAX_LENGTH = 64
NAVIGATOR_NOTES_BUDGET_CHARS = 6_000
"""contracts/navigator.md §1 ``NOTES_BUDGET_CHARS``: clients send reduced notes."""

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SERVER_ID = r"[0-9a-f]{12}"


def _client_id(prefix: str) -> StringConstraints:
    """A client-supplied id: ``<prefix>_<lowercase uuid>`` only."""

    return StringConstraints(
        pattern=rf"^{prefix}_{_UUID}$", max_length=CLIENT_ID_MAX_LENGTH
    )


def _reference(prefix: str) -> StringConstraints:
    """A reference to an existing record: the client or the server-minted shape."""

    return StringConstraints(
        pattern=rf"^{prefix}_(?:{_UUID}|{_SERVER_ID})$",
        max_length=CLIENT_ID_MAX_LENGTH,
    )


ReviewSessionId = Annotated[str, _client_id("review")]
DecisionId = Annotated[str, _client_id("decision")]
BulkReleaseId = Annotated[str, _client_id("bulk")]
NewFormulationId = Annotated[str, _client_id("form")]
FollowUpTaskId = Annotated[str, _client_id("task")]
ProgressId = Annotated[str, _client_id("progress")]
SessionRef = Annotated[str, _reference("review")]
FormulationRef = Annotated[str, _reference("form")]
TaskRef = Annotated[str, _reference("task")]
NavigatorRequestId = Annotated[
    str, StringConstraints(pattern=rf"^{_UUID}$", min_length=36, max_length=36)
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=500)]
ReviewTime = Annotated[
    str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
]
TimeZoneName = Annotated[str, StringConstraints(min_length=1, max_length=64)]

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
SessionStatus = Literal["open", "completed", "completed_empty", "partial", "abandoned"]
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
StepStatus = Literal["pending", "finished", "skipped"]
ReviewMode = Literal["quick", "full"]
ReviewEntry = Literal["list", "notification", "widget_decisions", "sidebar", "restart"]
ReviewOrigin = Literal["ios", "web", "macos"]
ClearStart = Literal["yes", "not_really"]
ReceiptKind = Literal["waiting", "someday"]
ThresholdDays = Literal[7, 14, 21, 28]
NavigatorKind = Literal["first_step", "reformulate", "project_next_action"]

# http §3: the required-fields column, and the types that decide on the
# task's current formulation (they must name it; a mismatch is stale).
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "reformulate": ("title",),
    "first_step": ("title",),
    "waiting": ("waiting_for",),
    "extend": ("reason",),
    "follow_up": ("title",),
    "return_to_next": ("title",),
}
_NEXT_ONLY = frozenset({"reformulate", "first_step", "waiting", "someday", "extend"})


# ------------------------------------------------------------- §3 decisions
class DecisionRequest(StrictBaseModel):
    """``POST /tasks/{task_id}/decisions``."""

    decision_id: DecisionId | None = None
    type: DecisionType
    expected_revision: int = Field(ge=1)
    formulation_id: FormulationRef | None = None
    stall_reason: StallReason | None = None
    title: ShortText | None = None
    waiting_for: ShortText | None = None
    reason: ShortText | None = None
    session_id: SessionRef | None = None
    ai_use: AiUse = "none"
    navigator_request_id: NavigatorRequestId | None = None
    client_decided_at: datetime | None = None
    new_formulation_id: NewFormulationId | None = None
    follow_up_task_id: FollowUpTaskId | None = None

    @model_validator(mode="after")
    def require_type_fields(self) -> DecisionRequest:
        missing = [
            name
            for name in _REQUIRED_FIELDS.get(self.type, ())
            if getattr(self, name) is None
        ]
        if self.type in _NEXT_ONLY and self.formulation_id is None:
            missing.append("formulation_id")
        if missing:
            raise PydanticCustomError(
                "review_decision_fields",
                "Decision {decision_type} needs: {fields}.",
                {"decision_type": self.type, "fields": ", ".join(missing)},
            )
        return self


class SessionCounts(StrictBaseModel):
    """The ten FR-033 summary counters, in the summary's fixed order."""

    done: int = Field(ge=0)
    reformulated: int = Field(ge=0)
    first_step: int = Field(ge=0)
    waiting: int = Field(ge=0)
    someday: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    extended: int = Field(ge=0)
    inbox_processed: int = Field(ge=0)
    kept: int = Field(ge=0)
    moved_to_next: int = Field(ge=0)


class DecisionRecordResponse(StrictBaseModel):
    id: str
    type: DecisionType
    task_id: str
    session_id: str | None
    decided_at: datetime
    substantive: bool | None
    stall_reason: StallReason | None
    ai_use: AiUse
    yielded_auto_park: bool = False


class ReviewReceiptResponse(StrictBaseModel):
    task_id: str
    kind: ReceiptKind
    hidden_until: datetime
    task_revision: int = Field(ge=1)


class DecisionResponse(StrictBaseModel):
    decision: DecisionRecordResponse
    task: TaskResponse
    created_task: TaskResponse | None
    receipt: ReviewReceiptResponse | None
    session_counts: SessionCounts | None


class UndoDecisionRequest(StrictBaseModel):
    """``POST /review/decisions/{decision_id}/undo``."""

    expected_task_revision: int = Field(ge=1)


class UndoDecisionResponse(StrictBaseModel):
    task: TaskResponse
    undone_decision_id: str
    deleted_task_id: str | None
    session_counts: SessionCounts | None


# --------------------------------------------------------------- §4 auto-park
class AutoParkRequest(StrictBaseModel):
    """``POST /tasks/{task_id}/auto-park``: no expected_revision by design."""

    formulation_id: FormulationRef


class AutoParkResponse(StrictBaseModel):
    applied: bool
    task: TaskResponse


# ------------------------------------------------------- §5 state, settings
class ReviewSettingsResponse(StrictBaseModel):
    threshold_days: ThresholdDays
    review_weekday: int = Field(ge=1, le=7)
    review_time: ReviewTime
    time_zone: str
    onboarded_at: datetime | None
    activated_at: datetime | None
    owner_park_floor_at: datetime | None
    revision: int = Field(ge=1)


class LastCountedReviewResponse(StrictBaseModel):
    session_id: str
    status: Literal["completed", "partial"]
    origin: ReviewOrigin
    ended_at: datetime | None
    counts: SessionCounts
    clear_start: ClearStart | None


class UnseenParkResponse(StrictBaseModel):
    task_id: str
    formulation_id: str
    parked_at: datetime


class ReviewStateCounts(StrictBaseModel):
    asks_for_decision: int = Field(ge=0)
    moves_tomorrow: int = Field(ge=0)


class SessionResponse(StrictBaseModel):
    """The exact http §6 field list (no set_aside_task_ids, no decision_queue,
    no finished_empty flags, no applied_progress)."""

    id: str
    mode: ReviewMode
    entry: ReviewEntry
    origin: ReviewOrigin
    status: SessionStatus
    started_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None
    current_step: StepCode | None
    steps: dict[StepCode, StepStatus]
    active_seconds_by_step: dict[StepCode, Annotated[int, Field(ge=0)]]
    counts: SessionCounts
    set_aside_count: int = Field(ge=0)
    qualifying_activity: bool
    clear_start: ClearStart | None
    revision: int = Field(ge=1)


class ReviewStateResponse(StrictBaseModel):
    """``GET /review/state``."""

    settings: ReviewSettingsResponse
    explainer_seen: bool
    grace_until: datetime | None
    last_counted_review_at: datetime | None
    last_counted_review: LastCountedReviewResponse | None
    next_review_at: datetime
    restart_mode: bool
    open_session: SessionResponse | None
    unseen_parks: list[UnseenParkResponse]
    counts: ReviewStateCounts
    receipts: list[ReviewReceiptResponse]
    server_now: datetime


class ExplainerAcknowledgeRequest(StrictBaseModel):
    """``POST /review/explainer/acknowledge``: the device zone, if known."""

    time_zone: TimeZoneName | None = None


class ReviewSettingsUpdateRequest(StrictBaseModel):
    """``PUT /review/settings``; the IANA check is the service's (400)."""

    threshold_days: ThresholdDays | None = None
    review_weekday: int | None = Field(default=None, ge=1, le=7)
    review_time: ReviewTime | None = None
    time_zone: TimeZoneName | None = None
    onboarded: Literal[True] | None = None
    expected_revision: int = Field(ge=1)


class ParkAcknowledgement(StrictBaseModel):
    task_id: TaskRef
    formulation_id: FormulationRef


class ParkAcknowledgeRequest(StrictBaseModel):
    """``POST /review/parks/acknowledge`` (204)."""

    items: list[ParkAcknowledgement] = Field(max_length=200)


# --------------------------------------------------------- §6 sessions, queues
class SessionStartRequest(StrictBaseModel):
    """``POST /review/sessions``."""

    id: ReviewSessionId | None = None
    mode: ReviewMode
    entry: ReviewEntry
    origin: ReviewOrigin
    skip_steps: list[StepCode] = Field(default_factory=list, max_length=10)
    replace_open: bool


class StepUpdate(StrictBaseModel):
    code: StepCode
    status: StepStatus


class ActiveSecondsUpdate(StrictBaseModel):
    code: StepCode
    seconds: int = Field(ge=0)


class SessionProgressRequest(StrictBaseModel):
    """``PATCH /review/sessions/{id}``: merged, replay-safe by ``progress_id``."""

    progress_id: ProgressId
    current_step: StepCode | None = None
    step: StepUpdate | None = None
    active_seconds: ActiveSecondsUpdate | None = None
    set_aside_task_id: TaskRef | None = None
    inbox_processed_delta: int | None = None
    snapshot_decision_queue: Literal[True] | None = None


class SessionFinishRequest(StrictBaseModel):
    """``POST /review/sessions/{id}/finish``."""

    clear_start: ClearStart | None = None


class WinsQueueMeta(StrictBaseModel):
    count: int = Field(ge=0)


class RestOfNextQueueMeta(StrictBaseModel):
    """FR-031 capacity mirror; pace and implied weeks need 4 weeks of history."""

    next_count: int = Field(ge=0)
    weekly_average_4w: float | None
    weeks_of_history: int = Field(ge=0)
    implied_weeks: float | None


class SomedayQueueMeta(StrictBaseModel):
    eligible_total: int = Field(ge=0)
    shown: int = Field(ge=0, le=7)


class DatesQueueDay(StrictBaseModel):
    day: date
    task_ids: list[str]


class DatesQueueMeta(StrictBaseModel):
    """The next 14 days grouped by local day."""

    days: list[DatesQueueDay] = Field(max_length=14)


class EmptyQueueMeta(StrictBaseModel):
    """Steps without meta: inbox, decisions, waiting, projects."""


class QueueResponse(StrictBaseModel):
    """``GET /review/queues/{step}``."""

    items: list[TaskResponse]
    meta: (
        WinsQueueMeta
        | RestOfNextQueueMeta
        | SomedayQueueMeta
        | DatesQueueMeta
        | EmptyQueueMeta
    )


class BulkReleaseItem(StrictBaseModel):
    task_id: TaskRef
    expected_revision: int = Field(ge=1)


class BulkReleaseRequest(StrictBaseModel):
    """``POST /review/bulk-releases``; eligibility is the server's."""

    id: BulkReleaseId | None = None
    kind: Literal["restart", "inbox_remainder"]
    session_id: SessionRef | None = None
    items: list[BulkReleaseItem] = Field(max_length=500)


class BulkReleasedItem(StrictBaseModel):
    task_id: str
    revision_after: int = Field(ge=1)


class BulkSkippedItem(StrictBaseModel):
    task_id: str
    reason: Literal["stale", "not_eligible"]


class BulkReleaseResponse(StrictBaseModel):
    id: str
    released: list[BulkReleasedItem]
    skipped: list[BulkSkippedItem]


class BulkUndoSkippedItem(StrictBaseModel):
    task_id: str
    reason: Literal["stale"]


class BulkReleaseUndoResponse(StrictBaseModel):
    """``POST /review/bulk-releases/{id}/undo``."""

    restored: list[str]
    skipped: list[BulkUndoSkippedItem]


# -------------------------------------------------------------- §7 navigator
class NavigatorConsentResponse(StrictBaseModel):
    granted_at: datetime
    revoked_at: datetime | None
    consent_text_version: int = Field(ge=1)


class NavigatorStatusResponse(StrictBaseModel):
    """``GET /review/navigator`` (never gated)."""

    provider: Literal["openai"] | None
    consent: NavigatorConsentResponse | None
    consent_current: bool
    consent_text_version: int = Field(ge=1)
    available: bool


class NavigatorConsentGrantRequest(StrictBaseModel):
    provider: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    consent_text_version: int = Field(ge=1)


class NavigatorRequestConsent(StrictBaseModel):
    external_processing_allowed: bool
    provider: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class NavigatorTaskInput(StrictBaseModel):
    title: ShortText
    notes: (
        Annotated[str, StringConstraints(max_length=NAVIGATOR_NOTES_BUDGET_CHARS)]
        | None
    ) = None
    stall_reason: StallReason | None = None


class NavigatorProjectInput(StrictBaseModel):
    name: ShortText
    open_task_titles: list[ShortText] = Field(max_length=20)


class NavigatorSuggestionRequest(StrictBaseModel):
    """The strict FR-019 input: nothing else can be sent (no language field)."""

    kind: NavigatorKind
    consent: NavigatorRequestConsent
    task: NavigatorTaskInput | None = None
    project: NavigatorProjectInput | None = None

    @model_validator(mode="after")
    def match_kind(self) -> NavigatorSuggestionRequest:
        if self.kind == "project_next_action":
            valid = self.task is None and self.project is not None
        else:
            valid = self.task is not None
        if not valid:
            raise PydanticCustomError(
                "navigator_input_shape",
                "A project next action has a project and no task; "
                "other kinds need a task.",
            )
        return self


class NavigatorSuggestionResponse(StrictBaseModel):
    request_id: NavigatorRequestId
    provider: str
    notes_truncated: bool
    proposals: list[ShortText] | None = Field(min_length=1, max_length=3)
    clarifying_question: ShortText | None

    @model_validator(mode="after")
    def exactly_one_answer(self) -> NavigatorSuggestionResponse:
        if (self.proposals is None) == (self.clarifying_question is None):
            raise PydanticCustomError(
                "navigator_answer_shape",
                "Exactly one of proposals or clarifying_question is set.",
            )
        return self
