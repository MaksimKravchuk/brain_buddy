"""HTTP contracts for the external-agent relay.

Two rules shape every model here. A saved credential is never a response field —
there is deliberately no schema that can carry one outward (FR-003). And the run
projection keeps connector-reported facts, BrainBuddy-derived conditions, and
pending user commands in separate fields, so no client has to infer which is
which or invent a blended progress number (FR-008, FR-011).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints

from app.modules.agents.headers import validate_auth_header_name

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
AgentCommandDelivery = Literal["unconfirmed", "confirmed"]

ConnectionName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
AuthHeaderName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128),
    AfterValidator(validate_auth_header_name),
]


class AgentCapabilitiesResponse(StrictBaseModel):
    """What the connector disclosed. A false capability hides its control."""

    progress: bool = False
    reply: bool = False
    cancel: bool = False


class AgentConnectionCreateRequest(StrictBaseModel):
    name: ConnectionName
    endpoint_url: str = Field(min_length=1, max_length=2_000)
    auth_header_name: AuthHeaderName = "X-Agent-Key"
    credential: str = Field(min_length=1, max_length=4_000)
    current_password: str = Field(min_length=1, max_length=512)


class AgentConnectionRotateRequest(StrictBaseModel):
    credential: str = Field(min_length=1, max_length=4_000)
    current_password: str = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)


class AgentConnectionDisconnectRequest(StrictBaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)


class AgentConnectionRotateSigningSecretRequest(StrictBaseModel):
    """Replace the inbound signing secret, e.g. after a lost create response."""

    current_password: str = Field(min_length=1, max_length=512)
    expected_revision: int = Field(ge=1)


class AgentConnectionResponse(StrictBaseModel):
    """A saved connection. Structurally incapable of carrying its secret."""

    id: str
    name: str
    endpoint_url: str
    auth_header_name: str
    status: AgentConnectionStatus
    # Derived from the clock, not stored: a ready connection goes stale once its
    # last authenticated contact ages past the deployment threshold (FR-002).
    stale: bool
    ready_for_handoff: bool
    capabilities: AgentCapabilitiesResponse
    last_test_error_code: str | None = None
    last_contact_at: datetime | None = None
    last_tested_at: datetime | None = None
    stale_after_seconds: int
    created_at: datetime
    revision: int


class AgentConnectionSecretResponse(AgentConnectionResponse):
    """A connection plus a signing secret, shown for this response only.

    BrainBuddy generates the secret so the owner can configure their agent to
    sign its reports. It is stored sealed and never appears in an ordinary read
    — a lost secret is replaced, not recovered.
    """

    inbound_signing_secret: str


class AgentConnectionCreatedResponse(AgentConnectionSecretResponse):
    """Registration: the first and, absent a rotation, only issue of a secret."""


class AgentConnectionSigningSecretResponse(AgentConnectionSecretResponse):
    """Rotation: the replacement secret, and the retired connection revision."""


class AgentContextItemRequest(StrictBaseModel):
    label: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4_000)


class AgentContextItemResponse(StrictBaseModel):
    label: str
    body: str


class AgentReportingContractResponse(StrictBaseModel):
    callback_url: str
    connection_id: str
    connection_header: Literal["X-BrainBuddy-Connection"]
    timestamp_header: Literal["X-BrainBuddy-Timestamp"]
    signature_header: Literal["X-BrainBuddy-Signature"]
    timestamp_format: Literal[
        "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero"
    ]
    signature_algorithm: Literal["hmac-sha256"]
    signing_bytes: Literal["timestamp_bytes + b'.' + raw_body"]
    signature_format: Literal["v1=<lowercase hex>"]
    body_envelope_version: str


class AgentHandoffPreviewRequest(StrictBaseModel):
    connection_id: str = Field(min_length=1, max_length=200)
    include_details: bool = True
    context_items: list[AgentContextItemRequest] = Field(default_factory=list)


class AgentHandoffConfirmRequest(AgentHandoffPreviewRequest):
    """Confirmation names the reviewed manifest, so a changed payload re-reviews."""

    manifest_token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    current_password: str | None = Field(default=None, max_length=512)


class AgentManifestResponse(StrictBaseModel):
    """Exactly what will leave BrainBuddy, itemised for review (FR-005)."""

    token: str
    run_id: str
    task_id: str
    connection_id: str
    agent_name: str
    title: str
    details: str | None = None
    context_items: list[AgentContextItemResponse] = Field(default_factory=list)
    reporting: AgentReportingContractResponse
    reporting_instructions: str
    instructions_version: str
    protocol_version: str
    destination_endpoint: str
    external_copy_notice: str
    reauthentication_required: bool


class AgentReplyRequest(StrictBaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    expected_revision: int = Field(ge=1)


class AgentRunEventResponse(StrictBaseModel):
    id: str
    type: AgentReportedState
    run_version: int
    received_at: datetime
    summary: str | None = None


class AgentRunCommandResponse(StrictBaseModel):
    id: str
    kind: AgentCommandKind
    body: str | None = None
    delivery: AgentCommandDelivery
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
    primary_state_label: str

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
    capabilities: AgentCapabilitiesResponse
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
    primary_state_label: str
    needs_user: bool
    stopped_reporting: bool
    last_contact_at: datetime | None = None


class AgentEventIngestResponse(StrictBaseModel):
    accepted: bool
    run_version: int


__all__ = [
    "AgentCapabilitiesResponse",
    "AgentCommandDelivery",
    "AgentCommandKind",
    "AgentConnectionCreateRequest",
    "AgentConnectionCreatedResponse",
    "AgentConnectionDisconnectRequest",
    "AgentConnectionResponse",
    "AgentConnectionRotateRequest",
    "AgentConnectionRotateSigningSecretRequest",
    "AgentConnectionSecretResponse",
    "AgentConnectionSigningSecretResponse",
    "AgentConnectionStatus",
    "AgentContextItemRequest",
    "AgentContextItemResponse",
    "AgentDispatchState",
    "AgentEventIngestResponse",
    "AgentHandoffConfirmRequest",
    "AgentHandoffPreviewRequest",
    "AgentManifestResponse",
    "AgentReplyRequest",
    "AgentReportedState",
    "AgentReportingContractResponse",
    "AgentRunCommandResponse",
    "AgentRunEventResponse",
    "AgentRunResponse",
    "AgentRunSummaryResponse",
]
