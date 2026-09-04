"""Canonical records owned by the external-agent relay module.

An Execution run is *evidence attached to* a Task, never part of it: nothing
here can complete, reopen, or otherwise mutate a canonical Task (FR-012). The
projection deliberately keeps three things apart — what the connector last
authenticated as (``reported_state``), what BrainBuddy derived from the clock
(``Stopped reporting``), and what the user asked for but has not been confirmed
(reply/cancel) — so no surface has to guess which of them it is looking at.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    model_serializer,
    model_validator,
)

from app.modules.agents.a2a.card import (
    AGENT_CARD_CHANGED,
    AgentCardSummary,
)
from app.modules.agents.a2a.card import (
    AuthScheme as AgentAuthScheme,
)
from app.modules.agents.a2a.card import (
    GuaranteeTier as AgentGuaranteeTier,
)
from app.modules.agents.authority import validate_endpoint_authority
from app.modules.agents.validation import sanitize_endpoint_input
from app.schemas.common import StorageBaseModel, StrictBaseModel

from .headers import validate_auth_header_name
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

AgentDisconnectReason = Literal["owner", "superseded_wire_contract"]
"""Why a connection is disconnected (spec 014, FR-012, SC-010)."""

AgentExchangeState = Literal["none", "queued", "open", "closed", "interrupted"]
AgentExchangeKind = Literal["start", "reply"]
"""Which kind of held exchange a run's `exchange_state` describes."""

AgentPushRegistration = Literal["unregistered", "registered", "refused", "unsupported"]
"""Whether the agent accepted the per-run push callback. Silent to the user: a
push only accelerates an observation the schedule performs anyway, so a refusal
is not something the owner can or should act on."""

A2A_PROTOCOL_VERSION = "1.0"
"""The protocol version a 014 manifest states, and the only one this build
speaks. Distinct from `PROTOCOL_VERSION`, which named the retired bespoke wire
and survives only in the inert rollback placeholder."""

"""What BrainBuddy knows about a held SendMessage exchange (spec 014, FR-006).

The distinction that matters is ``queued`` vs ``open``: a queued exchange has
provably never been sent, so a restart settles it as **Not sent** and re-offers
the hand-off. An open one may already be at the agent, so a restart resolves it
by lookup and never by resending (AC-032).
"""

#: Documents rewritten by the A2A wire migration carry this version, so a row
#: written by the 014 image is distinguishable from a 007 one without guessing
#: from its contents.
A2A_SCHEMA_VERSION = 2

AgentCommandKind = Literal["start", "reply", "cancel"]
AgentCommandDelivery = Literal["unconfirmed", "confirmed"]

TERMINAL_REPORTED_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled"}
)

PROTOCOL_VERSION = "2026-08-09"
"""Version of the connector wire contract this build speaks."""

REPORTING_INSTRUCTIONS_VERSION = "v2"

_ASCII_ENDPOINT_PATH_RE = re.compile(r"(?:/(?:[A-Za-z0-9._~!$&'()*+,;=:@%-])*)*")


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


def _reject_endpoint_unsafe_components(value: str) -> str:
    if any(not 0x21 <= ord(character) <= 0x7E for character in value) or "\\" in value:
        raise ValueError("agent endpoint is not a valid URL")
    if "?" in value:
        raise ValueError("agent endpoint must not contain a query string")
    if "#" in value:
        raise ValueError("agent endpoint must not contain a fragment")
    try:
        parts = urlsplit(value)
    except ValueError:
        parts = None
    if parts is None:
        raise ValueError("agent endpoint is not a valid URL")
    port = None
    invalid_port = False
    try:
        port = parts.port
    except ValueError:
        invalid_port = True
    if invalid_port:
        raise ValueError("agent endpoint is not a valid URL")
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("agent endpoint must be an absolute HTTP(S) URL")
    host = parts.hostname
    assert host is not None
    validate_endpoint_authority(parts.netloc, host)
    if _ASCII_ENDPOINT_PATH_RE.fullmatch(parts.path) is None or re.search(
        r"%(?![0-9A-Fa-f]{2})", parts.path
    ):
        raise ValueError("agent endpoint is not a valid URL")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("agent endpoint port is not valid")
    if parts.username is not None or parts.password is not None:
        raise ValueError("agent endpoint must not contain user information")
    return value


NonBlankStr = Annotated[str, AfterValidator(_require_nonblank)]
AuthHeaderName = Annotated[str, AfterValidator(validate_auth_header_name)]

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
    """What the agent's own card declared it can do.

    Only the card's two booleans (spec 014, FR-002). ``reply``/``cancel`` are not
    here on purpose: A2A cards do not advertise either, so BrainBuddy offers both
    controls on every tested connection and the run projection withdraws them
    once an agent has actually refused. Keeping a *product* decision out of a
    model named "capabilities" is what stops it being read as an agent claim.

    ``progress`` is gone with the bespoke wire: A2A carries no progress figure,
    and a flag for something nothing can report is a promise, not a fact.
    """

    streaming: bool = False
    push_notifications: bool = False


class AgentConnectionDocument(StorageBaseModel):
    """An owner-scoped connector identity and its non-readable credential."""

    model_config = ConfigDict(
        **(StorageBaseModel.model_config | {"hide_input_in_errors": True})
    )

    @model_validator(mode="before")
    @classmethod
    def _sanitize_rejected_endpoint(cls, data: object) -> object:
        return sanitize_endpoint_input(
            cls.__name__, data, _reject_endpoint_unsafe_components
        )

    id: str
    owner_id: str
    name: Annotated[NonBlankStr, Field(max_length=200)]
    # Storage key unchanged from 007 on purpose. The API exposes it as
    # `agent_address`, but renaming the *stored* key would make every 014 row
    # unreadable by the 007 image, which is the one thing a rollback must not
    # discover (plan.md, Rollback boundary).
    endpoint_url: Annotated[
        str,
        Field(min_length=1, max_length=2_000),
        AfterValidator(_reject_endpoint_unsafe_components),
    ]
    # Which wire contract produced this record (spec 014, FR-012). A row whose
    # *stored payload* lacks the key predates the A2A contract and is rewritten
    # to disconnected by the startup migration, which reads the raw JSON rather
    # than this model — so the default here never masks a legacy row, it only
    # keeps the hundreds of in-code constructions from having to restate the one
    # value this build can produce.
    wire: Literal["a2a"] = "a2a"
    # Which of the two credential schemes the owner chose (FR-001). The header
    # the credential travels in follows from this plus the card, never from
    # anything typed.
    auth_scheme: AgentAuthScheme = "bearer"
    # Present *only* for an api_key connection, and only once discovery read it
    # off the card. A bearer connection stores no key at all — deliberately not
    # the string "Authorization", which this very validator rejects, and which a
    # rolled-back 007 image would refuse to parse (plan.md, Rollback boundary).
    auth_header_name: Annotated[AuthHeaderName, Field(max_length=128)] | None = None
    credential: SealedSecret | None = None
    inbound_secret: SealedSecret | None = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    # The bounded copy of the card the last *successful test* read. Kept for the
    # connection's lifetime and erased on disconnect with the credential — never
    # swept at 90 days, because a connection that cannot say where it points is
    # not a connection anyone can reason about (FR-016, AC-024).
    card: AgentCardSummary | None = None
    card_fingerprint: str | None = Field(default=None, max_length=64)
    # Set when a test, preview or dispatch finds the card has moved under the
    # connection; cleared by the next successful test.
    card_drift_at: datetime | None = None
    guarantee_tier: AgentGuaranteeTier | None = None
    # FR-003/AC-026: stamped by the first confirmed best-effort hand-off that
    # carried the acknowledgement, and cleared whenever the verified scope is,
    # so a destination change asks again.
    best_effort_acknowledged_at: datetime | None = None
    # None until the first SendMessage answer on this connection. False means
    # the agent did not keep the run's correlation ID, so an empty lookup there
    # proves nothing and BrainBuddy never auto-resends (FR-006).
    context_id_honoured: bool | None = None
    status: AgentConnectionStatus = "untested"
    last_test_error_code: str | None = Field(default=None, max_length=128)
    # Closed per-code shapes (data-model.md §1), bounded on write by the service.
    # Coarse metadata only — never card prose.
    last_test_error_detail: dict[str, Any] | None = None
    last_contact_at: datetime | None = None
    last_tested_at: datetime | None = None
    # When the owner last proved possession of their password for *this*
    # destination/credential scope, and whether content has already been sent
    # under it. Together these implement FR-003's "first content-bearing
    # dispatch in a new scope" re-authentication trigger.
    scope_verified_at: datetime | None = None
    first_dispatch_at: datetime | None = None
    disconnected_at: datetime | None = None
    # Why the connection is disconnected, when it is. "owner" is a deliberate
    # act; "superseded_wire_contract" is the 014 migration, and the two read
    # very differently to whoever finds a dead connection (D-01-S21).
    disconnect_reason: AgentDisconnectReason | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)

    @model_serializer(mode="wrap")
    def _omit_absent_header_name(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Write no ``auth_header_name`` key at all when there is none.

        Not cosmetic, and not the same as writing ``null``. A bearer connection
        has no header name, and the 007 model this row must still validate
        against after a rollback declares the field a non-optional string with a
        default — so a stored ``null`` would make every 014 row unparseable to
        the previous image, which is the one thing the rollback boundary must
        not discover (plan.md; data-model.md §1).
        """

        payload: dict[str, Any] = handler(self)
        if payload.get("auth_header_name") is None:
            payload.pop("auth_header_name", None)
        return payload

    @property
    def agent_changed(self) -> bool:
        """The fifth connection condition (FR-002, D-01-S20).

        Derived rather than stored: a second boolean beside
        ``last_test_error_code`` could disagree with it, and the surfaces would
        then have two answers to "did this agent move?".
        """

        return self.last_test_error_code == AGENT_CARD_CHANGED

    @property
    def content_bearing_scope_is_verified(self) -> bool:
        """Whether the destination and credential were proved by a test."""

        return self.status == "ready" and self.card_fingerprint is not None


MAX_TEST_ERROR_DETAIL_BYTES = 512
"""Hard bound on the coarse detail a failed test may record (data-model §1)."""


def bounded_test_error_detail(
    detail: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The detail as it may be stored, or nothing.

    A card chooses the values inside `found_version`, `scheme` and the drifted
    interface, so the bound is enforced here rather than trusted from discovery:
    an agent must not be able to grow a connection row by returning a very long
    version string.
    """

    if not detail:
        return None
    encoded = json.dumps(detail, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) <= MAX_TEST_ERROR_DETAIL_BYTES:
        return detail
    return {
        key: (value[:64] if isinstance(value, str) else value)
        for key, value in detail.items()
    }


class AgentManifestContextItem(StorageBaseModel):
    """One explicitly selected piece of context leaving BrainBuddy."""

    label: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=MAX_CONTEXT_ITEM_CHARS)


class AgentReportingContract(StorageBaseModel):
    """A frozen placeholder reproducing the 007 callback contract's *shape*.

    Feature 014 replaced the bespoke inbound-event wire with A2A: nothing in
    this build reads any field below, no route exposes it, and no agent is ever
    told about it. It survives for exactly one reason -- **rollback**. The 007
    image's `AgentRunManifest` requires a `reporting` block, so a 014 run row
    written without one would be unparseable to it, and a rollback would find
    every relay row broken rather than merely idle (plan.md, Rollback boundary;
    research.md Decision F).

    So 014 writes it inert: an empty `callback_url`, the run's connection id,
    and the 007 defaults. ``callback_url`` therefore has a default here where
    007 required a value -- the empty string is not an address, which is the
    point: a rolled-back image reading it finds nowhere to send anything rather
    than an endpoint 014 has stopped serving.
    """

    callback_url: str = ""
    connection_id: str
    connection_header: Literal["X-BrainBuddy-Connection"] = "X-BrainBuddy-Connection"
    timestamp_header: Literal["X-BrainBuddy-Timestamp"] = "X-BrainBuddy-Timestamp"
    signature_header: Literal["X-BrainBuddy-Signature"] = "X-BrainBuddy-Signature"
    timestamp_format: Literal[
        "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero"
    ] = "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero"
    signature_algorithm: Literal["hmac-sha256"] = "hmac-sha256"
    signing_bytes: Literal["timestamp_bytes + b'.' + raw_body"] = (
        "timestamp_bytes + b'.' + raw_body"
    )
    signature_format: Literal["v1=<lowercase hex>"] = "v1=<lowercase hex>"
    body_envelope_version: str = PROTOCOL_VERSION


class AgentPushCallback(StorageBaseModel):
    """What the review says about the per-run push callback (FR-005, AC-007).

    The address is stored with its token already masked, because the manifest is
    read back on every run projection and the token must appear in no response,
    log line or audit row. `registered: False` carries neither an address nor a
    disclosure: there is nothing to disclose, and a masked address for a
    callback that does not exist would read as one that does.
    """

    registered: bool = False
    url_preview: str | None = None
    disclosure: str | None = None


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
    # Inert under 014 and present only so a frozen 007 `AgentRunManifest`
    # validates a 014 row after a rollback. Never read by this build, never
    # exposed by the API. See `AgentReportingContract`.
    reporting: AgentReportingContract = Field(
        default_factory=lambda: AgentReportingContract(connection_id="")
    )
    reporting_instructions: str = ""
    instructions_version: str = REPORTING_INSTRUCTIONS_VERSION
    # The A2A protocol version, not the retired bespoke wire version. Defaulted
    # so a frozen 007 row still parses, but every 014 manifest states "1.0".
    protocol_version: str = A2A_PROTOCOL_VERSION
    # --- 014 additions -----------------------------------------------------
    #
    # All defaulted, because a 007 row read after a rollforward has none of
    # them and must still parse; a 014 row always sets them.
    message_id: str = ""
    correlation_id: str = ""
    destination_interface: str = ""
    guarantee_tier: AgentGuaranteeTier = "best_effort"
    tier_disclosure: str = ""
    tier_disclosure_url: str = ""
    cancellation_disclosure: str = ""
    # True only while this connection is best-effort and the owner has not yet
    # acknowledged the duplicate risk. Frozen into the manifest so a retry of a
    # settled hand-off asks exactly what the original review asked (AC-026).
    acknowledgement_required: bool = False
    push_callback: AgentPushCallback = Field(default_factory=AgentPushCallback)


def inert_reporting_contract(connection_id: str) -> AgentReportingContract:
    """The rollback-compatibility placeholder for one connection.

    A helper rather than a literal at each call site, so the "this is inert"
    decision is stated once and a future caller cannot accidentally put a real
    callback URL back into a manifest.
    """

    return AgentReportingContract(callback_url="", connection_id=connection_id)


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
    # --- the A2A wire identifiers (spec 014) -------------------------------
    #
    # Additive, and safe on rollback: `StorageBaseModel` ignores unknown fields,
    # so a 007 image reads a row carrying these without noticing them.
    #
    # `context_id` is the wire conversation identifier, and it *is* the run id
    # (FR-006). It is deliberately not identifier-tier: it is embedded in the
    # push callback URL the agent keeps and in a run row no sweep deletes, so
    # nulling it at 90 days would erase nothing anyone actually holds. Saying so
    # is the honest version of SC-007.
    context_id: str | None = None
    agent_task_id: str | None = Field(default=None, max_length=512)
    card_fingerprint: str | None = Field(default=None, max_length=64)
    # Kept until identifier expiry rather than cleared at terminal: some agents
    # push exactly once, on the terminal transition, so a valid push racing
    # BrainBuddy's own terminal observation is the common case. With the
    # fingerprint still present it is classified `push_after_close` instead of
    # being reported as a forged token (SC-003).
    push_token_fingerprint: str | None = Field(default=None, max_length=128)
    exchange_state: AgentExchangeState = "none"
    #: Which exchange `exchange_state` describes. Restart recovery treats a
    #: `reply` exchange differently from a `start` one: a reply is never resent,
    #: only confirmed by succession evidence (AC-033).
    exchange_kind: AgentExchangeKind | None = None
    #: Stamped when a worker *starts* the exchange, never when it is submitted.
    #: The gap between the two is exactly the window in which nothing has left
    #: BrainBuddy, and the whole **Queued** state depends on keeping it visible.
    exchange_started_at: datetime | None = None
    exchange_deadline_at: datetime | None = None
    interface_url: str | None = Field(default=None, max_length=2_000)
    guarantee_tier: AgentGuaranteeTier | None = None
    message_id: str | None = Field(default=None, max_length=256)
    push_registration: AgentPushRegistration = "unregistered"
    last_observed_at: datetime | None = None
    next_observation_at: datetime | None = None
    #: Set once an agent answered that this task does not exist. Durable, and
    #: checked before any lookup: there is nothing left to look for, so looking
    #: again would only be a request made to produce the same answer.
    agent_task_missing_at: datetime | None = None
    identifiers_expire_at: datetime | None = None
    identifiers_expired: bool = False
    content_expires_at: datetime
    content_expired: bool = False
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


def project_run_for_access(run: AgentRunDocument, *, now: datetime) -> AgentRunDocument:
    """Pure authoritative projection: due content is inaccessible before sweep."""

    if run.content_expired or run.content_expires_at <= now:
        return run.model_copy(
            update={
                "manifest": None,
                "progress_text": None,
                "question_text": None,
                "result_text": None,
                "result_link": None,
                "failure_reason": None,
                "reply_pending_command_id": None,
                "content_expired": True,
            }
        )
    return run


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

    ``command_id``, ``delivery_attempted``, and ``completed`` make a
    network-bearing command crash-safe. The reservation is durable before the
    attempt marker, and the marker is durable before connector I/O. A retry can
    therefore resend a never-attempted command, but must reconcile an attempted
    command as unconfirmed instead of risking a duplicate external action.
    """

    key_hash: str
    command: str
    request_hash: str
    resource_id: str
    command_id: str | None = None
    delivery_attempted: bool = False
    completed: bool = True
    response_body: dict[str, object]
    created_at: datetime


__all__ = [
    "A2A_PROTOCOL_VERSION",
    "AGENT_EVENT_ENVELOPE_ADAPTER",
    "AgentExchangeKind",
    "AgentPushCallback",
    "AgentPushRegistration",
    "MAX_CONTEXT_ITEMS",
    "MAX_TEST_ERROR_DETAIL_BYTES",
    "AgentAuthScheme",
    "AgentGuaranteeTier",
    "bounded_test_error_detail",
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
    "AgentReportingContract",
    "AgentRunningEvent",
    "AgentRunCommandDocument",
    "AgentRunDocument",
    "AgentRunEventDocument",
    "AgentRunManifest",
    "project_run_for_access",
]
