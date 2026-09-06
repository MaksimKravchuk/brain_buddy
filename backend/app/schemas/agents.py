"""HTTP contracts for the external-agent relay.

Two rules shape every model here. A saved credential is never a response field —
there is deliberately no schema that can carry one outward (FR-003). And the run
projection keeps connector-reported facts, BrainBuddy-derived conditions, and
pending user commands in separate fields, so no client has to infer which is
which or invent a blended progress number (FR-008, FR-011).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import (
    AfterValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.agents.domain import (
    AgentPrimaryStateLabel,
    _reject_endpoint_unsafe_components,
)
from app.modules.agents.headers import validate_auth_header_name
from app.modules.agents.validation import sanitize_endpoint_input

from .common import StrictBaseModel

AgentConnectionStatus = Literal[
    "untested",
    "ready",
    "invalid_credentials",
    "unreachable",
    "unsupported",
    "disconnected",
]
AgentDispatchState = Literal["not_sent", "sent", "delivery_unconfirmed"]
AgentReportedState = Literal[
    "accepted", "running", "blocked", "completed", "failed", "cancelled"
]
AgentCommandKind = Literal["start", "reply", "cancel"]
AgentCommandDelivery = Literal["unconfirmed", "confirmed", "rejected"]
"""How a command ended. ``rejected`` only ever comes from an explicit agent
error correlated to *this* command — never from a timeout, which proves
nothing about whether the agent acted (data-model.md §4)."""

AgentRunEventTrigger = Literal["dispatch", "schedule", "push", "command"]
AgentRunEventKind = Literal["observation", "task_succession"]
AgentCancelOutcome = Literal[
    "none",
    "requested",
    "unconfirmed",
    "accepted",
    "unsupported",
    "not_cancelable",
    "task_missing",
]
"""What became of a cancellation request (AC-018, AC-029).

``unsupported`` and ``not_cancelable`` come only from an explicit agent
answer and withdraw the control; ``unconfirmed`` is the ambiguous outcome
and deliberately keeps it, because a timeout is not a refusal."""

AgentResultAvailability = Literal["available", "too_large"]
AgentArtifactKind = Literal["text", "file", "data", "link"]

AGENT_PRIMARY_STATE_LABELS: tuple[str, ...] = get_args(AgentPrimaryStateLabel)
"""The same vocabulary as a sequence, derived rather than restated.

Two literal lists would be one careless edit away from disagreeing, and the
disagreement would surface as a 500 on a run the user is already worried about.
"""

AgentExchangeState = Literal["none", "queued", "open", "closed", "interrupted"]
AgentExchangeKind = Literal["start", "reply"]
AgentPushRegistration = Literal["unregistered", "registered", "refused", "unsupported"]
AgentAuthScheme = Literal["bearer", "api_key"]
"""The two credential schemes BrainBuddy can present to an agent (FR-001).

Deliberately closed. A card may *offer* OAuth2, OIDC or mutual TLS; naming those
here would imply BrainBuddy can complete them, and the honest answer is to report
the offered scheme back to the owner as unsupported instead.
"""

AgentGuaranteeTier = Literal["guaranteed", "best_effort"]
AgentDisconnectReason = Literal["owner", "superseded_wire_contract"]
AgentSchemeKind = Literal["bearer", "api_key", "oauth2", "oidc", "mtls", "other"]

ConnectionName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
AuthHeaderName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128),
    AfterValidator(validate_auth_header_name),
]


class AgentCapabilitiesResponse(StrictBaseModel):
    """What the *card* declared. Nothing here is BrainBuddy's own claim.

    Kept apart from ``AgentControlsResponse`` on purpose (FR-002): these two
    booleans are the agent's statements about itself, and blending them with the
    controls BrainBuddy offers would turn a product decision into something that
    reads as an agent capability.
    """

    streaming: bool = False
    push_notifications: bool = False


class AgentControlsResponse(StrictBaseModel):
    """The controls BrainBuddy offers on this connection's runs (FR-010).

    Always true for a tested A2A connection, because agent cards do not advertise
    cancellation and BrainBuddy offers the control regardless — the run
    projection is what withdraws it per run, once an agent has actually refused.
    """

    reply: bool = False
    cancel: bool = False


class AgentSkillResponse(StrictBaseModel):
    """One advertised skill. Untrusted agent text, rendered inertly (AC-031)."""

    id: str | None = None
    name: str | None = None
    description: str | None = None


class AgentAuthSchemeOfferResponse(StrictBaseModel):
    """One security scheme the card offers, named back to the owner verbatim."""

    name: str
    kind: AgentSchemeKind
    header_name: str | None = None


class AgentCardResponse(StrictBaseModel):
    """The bounded discovery result shown on the connection (FR-002).

    Every string is untrusted agent text returned verbatim within the
    ``data-model.md`` §1 bounds: both clients render it as inert plain text,
    never an anchor or ``Linking`` target and never auto-linkified (FR-016,
    AC-031). ``interface_url`` is included precisely so the owner can see where
    their content would go — which is why it is shown, not made navigable.
    """

    name: str | None = None
    version: str | None = None
    description: str | None = None
    protocol_version: str | None = None
    interface_url: str | None = None
    streaming: bool = False
    push_notifications: bool = False
    skills: list[AgentSkillResponse] = Field(default_factory=list)
    auth_schemes_offered: list[AgentAuthSchemeOfferResponse] = Field(
        default_factory=list
    )
    extension_uris: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None


class AgentConnectionCreateRequest(StrictBaseModel):
    model_config = ConfigDict(
        **(StrictBaseModel.model_config | {"hide_input_in_errors": True})
    )

    @model_validator(mode="before")
    @classmethod
    def _sanitize_rejected_endpoint(cls, data: object) -> object:
        return sanitize_endpoint_input(
            cls.__name__,
            data,
            _reject_endpoint_unsafe_components,
            field="agent_address",
        )

    name: ConnectionName
    # The agent *origin* the owner typed. BrainBuddy fetches the card below it
    # and learns the interface from there, so this is the only address a person
    # ever has to know.
    agent_address: str = Field(min_length=1, max_length=2_000)
    auth_scheme: AgentAuthScheme = "bearer"
    credential: str = Field(min_length=1, max_length=4_000)
    current_password: str = Field(min_length=1, max_length=512)


class AgentConnectionRotateRequest(StrictBaseModel):
    credential: str = Field(min_length=1, max_length=4_000)
    current_password: str = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)


class AgentConnectionUpdateRequest(StrictBaseModel):
    """Bounded metadata/destination update; credentials have their own operation."""

    model_config = ConfigDict(
        **(StrictBaseModel.model_config | {"hide_input_in_errors": True})
    )

    @model_validator(mode="before")
    @classmethod
    def _sanitize_rejected_endpoint(cls, data: object) -> object:
        return sanitize_endpoint_input(
            cls.__name__,
            data,
            _reject_endpoint_unsafe_components,
            field="agent_address",
        )

    name: ConnectionName | None = None
    agent_address: str | None = Field(default=None, min_length=1, max_length=2_000)
    # A scheme change is a scope change exactly as an address change is: the
    # credential is presented differently, so the owner has to prove possession
    # again before content moves under it (FR-004).
    auth_scheme: AgentAuthScheme | None = None
    current_password: str | None = Field(default=None, min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def _requires_an_update(self) -> AgentConnectionUpdateRequest:
        if (
            self.name is None
            and self.agent_address is None
            and self.auth_scheme is None
        ):
            raise ValueError("name, agent_address or auth_scheme is required")
        return self


class AgentConnectionDisconnectRequest(StrictBaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)


class AgentConnectionResponse(StrictBaseModel):
    """A saved connection. Structurally incapable of carrying its secret."""

    id: str
    name: str
    agent_address: str
    auth_scheme: AgentAuthScheme
    # Present only for an ``api_key`` connection, and only once discovery has
    # read it off the card. A bearer connection derives ``Authorization`` from
    # the scheme, so it has no header name to show and shows none.
    auth_header_name: str | None = None
    status: AgentConnectionStatus
    # Derived from the clock, not stored: a ready connection goes stale once its
    # last authenticated contact ages past the deployment threshold (FR-002).
    stale: bool
    ready_for_handoff: bool
    capabilities: AgentCapabilitiesResponse
    controls_offered: AgentControlsResponse = Field(
        default_factory=AgentControlsResponse
    )
    card: AgentCardResponse | None = None
    guarantee_tier: AgentGuaranteeTier | None = None
    # Server-owned sentences, rendered verbatim on both clients (FR-014). They
    # are computed here rather than assembled client-side so web and iOS cannot
    # drift into two different promises about the same agent.
    tier_disclosure: str | None = None
    tier_disclosure_url: str | None = None
    cancellation_disclosure: str | None = None
    # The fifth connection condition (FR-002): true exactly when the last test
    # found the card had moved under the connection.
    agent_changed: bool = False
    best_effort_acknowledged_at: datetime | None = None
    # False once an agent's first answer failed to keep the run's correlation
    # ID. BrainBuddy never auto-resends on such a connection, because an empty
    # lookup there proves nothing (FR-006).
    correlation_id_honoured: bool | None = None
    disconnect_reason: AgentDisconnectReason | None = None
    last_test_error_code: str | None = None
    # Closed per-code shapes, bounded (data-model.md §1). Coarse metadata only —
    # never card text beyond the values the codes name.
    last_test_error_detail: dict[str, object] | None = None
    last_contact_at: datetime | None = None
    last_tested_at: datetime | None = None
    stale_after_seconds: int
    created_at: datetime
    revision: int


class AgentContextItemRequest(StrictBaseModel):
    """One supporting item the owner chose to include (ADR-0006 vocabulary)."""

    label: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4_000)


class AgentContextItemResponse(StrictBaseModel):
    label: str
    body: str


class AgentPushCallbackResponse(StrictBaseModel):
    """The private per-run callback address, disclosed in the review (FR-005).

    Shown with its token masked, and only when the agent's card says it can push
    at all. An unregistered callback carries no address and no disclosure: a
    masked address for something that does not exist would read as one that
    does. The token itself appears in no response, ever (AC-007).
    """

    registered: bool = False
    url_preview: str | None = None
    disclosure: str | None = None


class AgentHandoffPreviewRequest(StrictBaseModel):
    connection_id: str = Field(min_length=1, max_length=200)
    include_details: bool = True
    supporting_items: list[AgentContextItemRequest] = Field(default_factory=list)


class AgentHandoffConfirmRequest(AgentHandoffPreviewRequest):
    """Confirmation names the reviewed manifest, so a changed payload re-reviews."""

    manifest_token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    current_password: str | None = Field(default=None, max_length=512)
    # Part of the canonical request identity, not a header: a retry that quietly
    # dropped it would be a *different* request wearing the same
    # Idempotency-Key, and the acknowledgement is the thing the user actually
    # gave (AC-026). It defaults to false because an unstated acknowledgement is
    # not an acknowledgement.
    acknowledge_duplicate_risk: bool = False


class AgentCheckDeliveryRequest(StrictBaseModel):
    """**Check again**: re-run *this* run's own lookup-before-resend (AC-027).

    Deliberately carries no identifiers and no content. Everything the check
    needs is already on the run, and a body that could name a different run — or
    carry new content — would make "check again" capable of being a second send.

    What it does carry is the revision the user was looking at when they asked.
    The check can end in a message on the wire, so it is a mutation like any
    other, and every mutation names the state it was composed against
    (`mobile/AGENTS.md`): a check replayed from a stale cached run would resend
    for a state nobody is being shown any more. Optional, so a client that has
    not adopted it yet still checks exactly as before.
    """

    current_password: str | None = Field(default=None, max_length=512)
    expected_revision: int | None = Field(default=None, ge=1)


class AgentManifestResponse(StrictBaseModel):
    """Exactly what will leave BrainBuddy, itemised for review (FR-005).

    This is the consent boundary, so it is itemised in full rather than
    summarised: every field is something a user could object to before it
    leaves. The bespoke reporting block is gone with the wire that needed it —
    an A2A agent is told nothing about how to report back, because it reports by
    answering.
    """

    token: str
    run_id: str
    task_id: str
    connection_id: str
    agent_name: str
    title: str
    details: str | None = None
    supporting_items: list[AgentContextItemResponse] = Field(default_factory=list)
    message_id: str
    correlation_id: str
    destination_interface: str
    protocol_version: str
    guarantee_tier: AgentGuaranteeTier
    tier_disclosure: str
    tier_disclosure_url: str
    # True only for a best-effort connection whose owner has not yet
    # acknowledged the duplicate risk. Asked once per connection, and again
    # whenever its verified scope resets (AC-026).
    acknowledgement_required: bool = False
    cancellation_disclosure: str
    push_callback: AgentPushCallbackResponse | None = None
    external_copy_notice: str
    reauthentication_required: bool
    # The exact text of each part that will be sent, in order. The review claims
    # to show what leaves; this is that claim made checkable.
    parts_preview: list[str] = Field(default_factory=list)


class AgentReplyRequest(StrictBaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    expected_revision: int = Field(ge=1)


class AgentArtifactSummaryResponse(StrictBaseModel):
    """A placeholder for something the agent produced and BrainBuddy never fetched.

    Names the content type rather than the content: the relay stores no
    attachment, and a row that implied otherwise would promise a download that
    does not exist (D-03-S11).
    """

    name: str | None = None
    media_type: str | None = None
    kind: AgentArtifactKind


class AgentRunEventResponse(StrictBaseModel):
    """One row of the run timeline.

    ``kind`` and ``type`` answer different questions and are kept apart on
    purpose: ``type`` is the run's projected state at that moment, while
    ``kind`` says whether the row *is* that observation or the note that the
    agent moved the work into a new task (D-03-S27).
    """

    id: str
    type: AgentReportedState
    run_version: int
    received_at: datetime
    summary: str | None = None
    trigger: AgentRunEventTrigger = "schedule"
    kind: AgentRunEventKind = "observation"
    # Only ever populated on a `task_succession` row; identifier tier, so both
    # go null at 90 days with the rest of the run's identifiers.
    previous_agent_task_id: str | None = None
    new_agent_task_id: str | None = None


class AgentRunCommandResponse(StrictBaseModel):
    id: str
    kind: AgentCommandKind
    body: str | None = None
    delivery: AgentCommandDelivery
    # The agent's own answer, as a coarse code. Absent for every ambiguous
    # ending, because "we never heard back" is not an outcome the agent gave.
    outcome_code: str | None = None
    created_at: datetime
    confirmed_at: datetime | None = None


class AgentRunResponse(StrictBaseModel):
    """The owner-facing projection of one external run."""

    id: str
    task_id: str
    connection_id: str
    agent_name: str

    # What BrainBuddy knows about its own outbound request.
    dispatch_state: AgentDispatchState
    dispatch_error_code: str | None = None

    # What the connector last authenticated as, and its authoritative version.
    reported_state: AgentReportedState | None = None
    run_version: int

    # Conditions BrainBuddy derived or the user requested — never blended into
    # the reported state above.
    stopped_reporting: bool
    connection_disconnected: bool
    reply_pending: bool
    cancel_requested: bool
    needs_user: bool

    # A single label clients render verbatim, so web and iOS cannot drift.
    primary_state_label: AgentPrimaryStateLabel

    progress_text: str | None = None
    question_text: str | None = None
    result_text: str | None = None
    result_link: str | None = None
    result_link_interactive: bool = False
    failure_reason: str | None = None

    content_expired: bool
    content_expires_at: datetime
    last_contact_at: datetime | None = None
    reporting_window_seconds: int
    # The controls still offered on *this* run. `progress` is gone with the
    # bespoke wire (api-deltas.md): A2A carries no progress percentage, and a
    # capability flag for something nothing can report is a promise, not a fact.
    capabilities: AgentControlsResponse

    # --- the A2A exchange this run is waiting on (FR-006) ------------------
    #
    # `exchange_state` is the difference between **Queued** and **Sent**, and
    # that is the one distinction this projection exists to keep: a queued
    # exchange has provably not been sent, so collapsing it into `sent` would be
    # precisely the lie the feature is built to avoid.
    guarantee_tier: AgentGuaranteeTier | None = None
    message_id: str | None = None
    correlation_id: str | None = None
    agent_task_id: str | None = None
    exchange_open: bool = False
    exchange_state: AgentExchangeState = "none"
    exchange_kind: AgentExchangeKind | None = None
    push_registration: AgentPushRegistration = "unregistered"
    # --- what observation established (spec 014, FR-008, FR-009) -----------
    #
    # Every default below is the absence of a claim, not a neutral-looking
    # state: a run nobody has observed yet says only that.
    agent_task_missing: bool = False
    cancel_outcome: AgentCancelOutcome = "none"
    blocked_reason: str | None = None
    artifacts_summary: list[AgentArtifactSummaryResponse] = Field(default_factory=list)
    # `too_large` is an honest marker, never **Stopped reporting**: the state
    # was observed, only the result exceeded what BrainBuddy stores.
    result_availability: AgentResultAvailability | None = None
    last_observed_at: datetime | None = None
    # The configured *base* interval. The server may observe less often after
    # the reporting window (FR-008 backoff); the client polls at this rate and
    # is never told a schedule the server is not keeping.
    observation_interval_seconds: int = 60
    identifiers_expired: bool = False

    manifest: AgentManifestResponse | None = None
    events: list[AgentRunEventResponse] = Field(default_factory=list)
    commands: list[AgentRunCommandResponse] = Field(default_factory=list)
    created_at: datetime
    revision: int


class AgentRunSummaryResponse(StrictBaseModel):
    """The compact Task surface: latest run only, no timeline (FR-010)."""

    id: str
    task_id: str
    agent_name: str
    primary_state_label: AgentPrimaryStateLabel
    needs_user: bool
    stopped_reporting: bool
    last_contact_at: datetime | None = None
    # The compact row states the tier in full and shows the same withdrawals
    # the full projection does, so the two surfaces cannot disagree about what
    # the user may still do (D-03-S21).
    guarantee_tier: AgentGuaranteeTier | None = None
    cancel_outcome: AgentCancelOutcome = "none"
    agent_task_missing: bool = False


__all__ = [
    "AGENT_PRIMARY_STATE_LABELS",
    "AgentArtifactKind",
    "AgentArtifactSummaryResponse",
    "AgentAuthScheme",
    "AgentCancelOutcome",
    "AgentPrimaryStateLabel",
    "AgentResultAvailability",
    "AgentRunEventKind",
    "AgentRunEventTrigger",
    "AgentCheckDeliveryRequest",
    "AgentExchangeKind",
    "AgentExchangeState",
    "AgentPushCallbackResponse",
    "AgentPushRegistration",
    "AgentAuthSchemeOfferResponse",
    "AgentCapabilitiesResponse",
    "AgentCardResponse",
    "AgentCommandDelivery",
    "AgentCommandKind",
    "AgentControlsResponse",
    "AgentDisconnectReason",
    "AgentGuaranteeTier",
    "AgentSkillResponse",
    "AgentConnectionCreateRequest",
    "AgentConnectionDisconnectRequest",
    "AgentConnectionResponse",
    "AgentConnectionRotateRequest",
    "AgentConnectionStatus",
    "AgentConnectionUpdateRequest",
    "AgentContextItemRequest",
    "AgentContextItemResponse",
    "AgentDispatchState",
    "AgentHandoffConfirmRequest",
    "AgentHandoffPreviewRequest",
    "AgentManifestResponse",
    "AgentReplyRequest",
    "AgentReportedState",
    "AgentRunCommandResponse",
    "AgentRunEventResponse",
    "AgentRunResponse",
    "AgentRunSummaryResponse",
]
