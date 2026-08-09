"""Canonical records owned by the external-agent relay module.

An Execution run is *evidence attached to* a Task, never part of it: nothing
here can complete, reopen, or otherwise mutate a canonical Task (FR-012). The
projection deliberately keeps three things apart — what the connector last
authenticated as (``reported_state``), what BrainBuddy derived from the clock
(``Stopped reporting``), and what the user asked for but has not been confirmed
(reply/cancel) — so no surface has to guess which of them it is looking at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, TypeAdapter, model_validator

from app.schemas.common import StorageBaseModel, StrictBaseModel

from .secrets import SealedSecret

AgentConnectionStatus = Literal[
    "untested",
    "ready",
    "invalid_credentials",
    "unreachable",
    # The connector answered but does not meet the wire contract — most often
    # because it cannot promise start deduplication (FR-006).
    "unsupported",
    "disconnected",
]
"""Result of the last connection test. Staleness is derived, never stored."""

AgentDispatchState = Literal["not_sent", "sent", "delivery_unconfirmed"]
"""What BrainBuddy knows about its own outbound start request (FR-006)."""

AgentReportedState = Literal[
    "accepted", "running", "blocked", "completed", "failed", "cancelled"
]
"""The last state an authenticated connector report claimed."""

AgentCommandKind = Literal["start", "reply", "cancel"]
AgentCommandDelivery = Literal["unconfirmed", "confirmed"]

TERMINAL_REPORTED_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"}
)

PROTOCOL_VERSION = "2026-08-09"
"""Version of the connector wire contract this build speaks."""

REPORTING_INSTRUCTIONS_VERSION = "v1"

MAX_PROGRESS_CHARS = 2_000
MAX_QUESTION_CHARS = 4_000
MAX_RESULT_CHARS = 20_000
MAX_REPLY_CHARS = 4_000
MAX_CONTEXT_ITEMS = 20
MAX_CONTEXT_ITEM_CHARS = 4_000


# --- the inbound event envelope (FR-009) -------------------------------------
#
# This is the connector wire contract ``PROTOCOL_VERSION`` versions, not an HTTP
# API model: the route hands the service raw signed bytes and never parses them.
# It is strict on purpose. An inbound event arrives from a caller with no
# session, so once the signature proves *who* sent it the body is still only
# authentic, not well formed. Every model below forbids unknown fields and
# refuses type coercion, and each event type declares exactly the payload it may
# carry — a `running` report with a `result` is not a completion, so it is a
# protocol error rather than something to partially apply.


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_require_nonblank)]

_ProgressText = Annotated[str, Field(max_length=MAX_PROGRESS_CHARS)]
_QuestionText = Annotated[NonBlankStr, Field(max_length=MAX_QUESTION_CHARS)]
_ResultText = Annotated[NonBlankStr, Field(max_length=MAX_RESULT_CHARS)]
_ReasonText = Annotated[NonBlankStr, Field(max_length=MAX_RESULT_CHARS)]
_ResultLink = Annotated[NonBlankStr, Field(max_length=2_000)]


class AgentEventEnvelopeBase(StrictBaseModel):
    """The fields every report carries, whatever its type.

    ``protocol_version`` and ``connection_id`` live *inside* the signed body so
    the envelope states its own scope: the signature then binds a report to one
    connection and one protocol version, and a body lifted onto a different
    route cannot be replayed as if it belonged there.
    """

    model_config = StrictBaseModel.model_config | {"strict": True}

    protocol_version: NonBlankStr = Field(max_length=64)
    connection_id: NonBlankStr = Field(max_length=200)
    event_id: NonBlankStr = Field(max_length=200)
    run_id: NonBlankStr = Field(max_length=200)
    run_version: int = Field(ge=1)


class AgentAcceptedEvent(AgentEventEnvelopeBase):
    """The agent has taken the work but has not started reporting on it."""

    type: Literal["accepted"]
    progress: _ProgressText | None = None


class AgentRunningEvent(AgentEventEnvelopeBase):
    """Work is under way; optional free text, never a percentage or an ETA."""

    type: Literal["running"]
    progress: _ProgressText | None = None


class AgentBlockedEvent(AgentEventEnvelopeBase):
    """The agent needs an answer, so it has to say what it is asking."""

    type: Literal["blocked"]
    question: _QuestionText


class AgentCompletedEvent(AgentEventEnvelopeBase):
    """The agent claims it finished, and points at what it produced."""

    type: Literal["completed"]
    result: _ResultText | None = None
    result_link: _ResultLink | None = None

    @model_validator(mode="after")
    def _requires_a_result(self) -> AgentCompletedEvent:
        if self.result is None and self.result_link is None:
            raise ValueError("completed requires result or result_link")
        return self


class AgentFailedEvent(AgentEventEnvelopeBase):
    """The agent gave up, and has to say why."""

    type: Literal["failed"]
    reason: _ReasonText


class AgentCancelledEvent(AgentEventEnvelopeBase):
    """The agent stopped on request. There is nothing else to report."""

    type: Literal["cancelled"]


AgentEventEnvelope = Annotated[
    AgentAcceptedEvent
    | AgentRunningEvent
    | AgentBlockedEvent
    | AgentCompletedEvent
    | AgentFailedEvent
    | AgentCancelledEvent,
    Field(discriminator="type"),
]

AGENT_EVENT_ENVELOPE_ADAPTER: TypeAdapter[AgentEventEnvelope] = TypeAdapter(
    AgentEventEnvelope
)
"""Parses one inbound report, or refuses it whole."""


class AgentCapabilities(StorageBaseModel):
    """What a connector said it can do. Absent capability means no control."""

    progress: bool = False
    reply: bool = False
    cancel: bool = False


class AgentConnectionDocument(StorageBaseModel):
    """An owner-scoped connector identity and its non-readable credential."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=200)
    endpoint_url: str = Field(min_length=1, max_length=2_000)
    auth_header_name: str = Field(default="Authorization", min_length=1, max_length=128)
    credential: SealedSecret | None = None
    inbound_secret: SealedSecret | None = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    status: AgentConnectionStatus = "untested"
    last_test_error_code: str | None = Field(default=None, max_length=128)
    last_contact_at: datetime | None = None
    last_tested_at: datetime | None = None
    # When the owner last proved possession of their password for *this*
    # destination/credential scope, and whether content has already been sent
    # under it. Together these implement FR-003's "first content-bearing
    # dispatch in a new scope" re-authentication trigger.
    scope_verified_at: datetime | None = None
    first_dispatch_at: datetime | None = None
    disconnected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class AgentManifestContextItem(StorageBaseModel):
    """One explicitly selected piece of context leaving BrainBuddy."""

    label: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_CONTEXT_ITEM_CHARS)


class AgentRunManifest(StorageBaseModel):
    """The exact, frozen set of content-bearing values a hand-off sends.

    ``token`` is a hash over every content-bearing value plus the destination and
    run ID. Confirmation names the token, so changing anything the user reviewed
    invalidates the confirmation instead of silently sending something else
    (FR-005).
    """

    token: str = Field(min_length=64, max_length=64)
    run_id: str
    task_id: str
    connection_id: str
    agent_name: str
    title: str
    details: str | None = None
    context_items: list[AgentManifestContextItem] = Field(default_factory=list)
    reporting_instructions: str
    instructions_version: str = REPORTING_INSTRUCTIONS_VERSION
    protocol_version: str = PROTOCOL_VERSION


class AgentRunDocument(StorageBaseModel):
    """One external attempt linked to, but not owned by, a Task."""

    id: str
    owner_id: str
    connection_id: str
    task_id: str
    agent_name: str
    # The manifest carries the only copy of the run's content-derived token, so
    # erasing the manifest at retention erases the fingerprint with it (FR-015).
    manifest: AgentRunManifest | None = None
    # A run exists as an invisible *reservation* from the moment its ID and
    # idempotency key are durably claimed at review time (FR-006), and becomes a
    # real, listable external run only once a confirmed dispatch is attempted.
    # Reviewing and then cancelling therefore creates no run the user can see.
    dispatched_at: datetime | None = None
    dispatch_state: AgentDispatchState = "not_sent"
    dispatch_error_code: str | None = Field(default=None, max_length=128)
    reported_state: AgentReportedState | None = None
    # Authoritative, strictly increasing connector-side version. An event at or
    # below this number is a duplicate or a straggler and changes nothing.
    run_version: int = Field(default=0, ge=0)
    progress_text: str | None = Field(default=None, max_length=MAX_PROGRESS_CHARS)
    question_text: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)
    result_text: str | None = Field(default=None, max_length=MAX_RESULT_CHARS)
    result_link: str | None = Field(default=None, max_length=2_000)
    failure_reason: str | None = Field(default=None, max_length=MAX_RESULT_CHARS)
    last_contact_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    reply_pending_command_id: str | None = None
    connection_disconnected_at: datetime | None = None
    content_expires_at: datetime
    content_expired: bool = False
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class AgentRunEventDocument(StorageBaseModel):
    """One authenticated connector report, kept for the run timeline."""

    id: str
    owner_id: str
    run_id: str
    connection_id: str
    type: AgentReportedState
    run_version: int = Field(ge=1)
    received_at: datetime
    # Redacted at retention time along with the rest of the relayed content.
    summary: str | None = Field(default=None, max_length=MAX_RESULT_CHARS)


class AgentRunCommandDocument(StorageBaseModel):
    """An idempotent owner request to start, reply to, or cancel a run."""

    id: str
    owner_id: str
    run_id: str
    kind: AgentCommandKind
    body: str | None = Field(default=None, max_length=MAX_REPLY_CHARS)
    delivery: AgentCommandDelivery = "unconfirmed"
    created_at: datetime
    confirmed_at: datetime | None = None


class AgentAuditEntryDocument(StorageBaseModel):
    """A bounded operational fact: IDs, outcome, and timing only.

    Never carries a credential or any relayed user/agent content (FR-017), which
    is why it may outlive the content it describes.
    """

    id: str
    owner_id: str
    action: str = Field(min_length=1, max_length=64)
    outcome: str = Field(min_length=1, max_length=64)
    connection_id: str | None = None
    run_id: str | None = None
    correlation_id: str | None = Field(default=None, max_length=128)
    created_at: datetime


class AgentIdempotencyRecord(StorageBaseModel):
    """Persisted result pointer for one owner-scoped relay command.

    Nothing here is reversible into what the request contained. ``key_hash`` and
    ``request_hash`` are both keyed fingerprints (see ``SecretBox.fingerprint``),
    so the row can answer "same key, same request?" without ever holding the key
    or the payload.

    ``command_id`` and ``completed`` are what make a network-bearing command
    crash-safe: the reservation is written with ``completed=False`` *before* the
    connector is called, so a retry after an ambiguous attempt reuses the exact
    command ID rather than minting a second one.
    """

    key_hash: str
    command: str
    request_hash: str
    resource_id: str
    command_id: str | None = None
    completed: bool = True
    response_body: dict[str, object]
    created_at: datetime


__all__ = [
    "AGENT_EVENT_ENVELOPE_ADAPTER",
    "MAX_CONTEXT_ITEMS",
    "MAX_CONTEXT_ITEM_CHARS",
    "MAX_PROGRESS_CHARS",
    "MAX_QUESTION_CHARS",
    "MAX_REPLY_CHARS",
    "MAX_RESULT_CHARS",
    "PROTOCOL_VERSION",
    "REPORTING_INSTRUCTIONS_VERSION",
    "TERMINAL_REPORTED_STATES",
    "AgentAcceptedEvent",
    "AgentAuditEntryDocument",
    "AgentBlockedEvent",
    "AgentCancelledEvent",
    "AgentCapabilities",
    "AgentCommandDelivery",
    "AgentCommandKind",
    "AgentCompletedEvent",
    "AgentConnectionDocument",
    "AgentConnectionStatus",
    "AgentDispatchState",
    "AgentEventEnvelope",
    "AgentEventEnvelopeBase",
    "AgentFailedEvent",
    "AgentIdempotencyRecord",
    "AgentManifestContextItem",
    "AgentReportedState",
    "AgentRunningEvent",
    "AgentRunCommandDocument",
    "AgentRunDocument",
    "AgentRunEventDocument",
    "AgentRunManifest",
]
