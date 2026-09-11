"""The A2A v1.0 subset BrainBuddy speaks, as validated models.

Two different strictness rules live here, and the difference is deliberate:

* **Outbound** request bodies are strict (:class:`~app.schemas.common.StrictBaseModel`).
  The a2a-sdk server rejects unknown params outright, so a stray field is not a
  harmless extra — it fails the whole hand-off. Forbidding extras here means a
  typo is caught in BrainBuddy's own tests rather than by a stranger's server.

* **Inbound** payloads ignore unknown fields (:class:`InboundModel`). Real
  agents add fields: Hermes serves ``capabilities.stateTransitionHistory`` and a
  legacy card security shape that A2A 1.0 does not define, and every part it
  returns carries a ``mediaType``. Refusing those would make BrainBuddy
  incompatible with the very runtimes FR-017 requires it to work against, while
  proving nothing — an unknown field is not a threat, an *unbounded* one is, and
  bounds are enforced where the value is used.

Nothing here performs I/O or trusts a value: the models say what a payload
*is*, and ``card``/``client``/``mapping`` decide what it *means*.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import StrictBaseModel

# --- JSON-RPC error codes (contracts/a2a-wire.md, A2A §5.4) -----------------
#
# Only these integers are ever written to a log line; anything else is recorded
# as "other", so an agent cannot use an error code as a log-injection channel or
# grow log cardinality without bound (research.md Decision K).

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004
CONTENT_TYPE_NOT_SUPPORTED = -32005
INVALID_AGENT_RESPONSE = -32006
EXTENDED_CARD_NOT_CONFIGURED = -32007
EXTENSION_SUPPORT_REQUIRED = -32008
VERSION_NOT_SUPPORTED = -32009

#: Agent-specific codes admitted through an explicit allowlist. A2A 1.0 defines
#: no authentication or rate-limit error, and these are Hermes' (research F5);
#: they are named here rather than pattern-matched so adding one is a decision.
UNAUTHORIZED = -32050
RATE_LIMITED = -32051
UNTRUSTED = -32052

LOGGABLE_ERROR_CODES: frozenset[int] = frozenset(
    {
        PARSE_ERROR,
        INVALID_REQUEST,
        METHOD_NOT_FOUND,
        INVALID_PARAMS,
        INTERNAL_ERROR,
        TASK_NOT_FOUND,
        TASK_NOT_CANCELABLE,
        PUSH_NOTIFICATION_NOT_SUPPORTED,
        UNSUPPORTED_OPERATION,
        CONTENT_TYPE_NOT_SUPPORTED,
        INVALID_AGENT_RESPONSE,
        EXTENDED_CARD_NOT_CONFIGURED,
        EXTENSION_SUPPORT_REQUIRED,
        VERSION_NOT_SUPPORTED,
    }
)
"""Codes safe to log verbatim. Everything else is logged as ``other``."""


def loggable_error_code(code: int | None) -> str:
    """Render an error code for a log line, collapsing anything unknown."""

    if code is None:
        return "none"
    return str(code) if code in LOGGABLE_ERROR_CODES else "other"


# --- shared model bases -----------------------------------------------------


class InboundModel(BaseModel):
    """Base for anything an agent sends us: lenient about unknown fields.

    ``populate_by_name`` lets the wire's camelCase and BrainBuddy's snake_case
    both address a field, so call sites read like Python without the parser
    diverging from the protocol.
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


class OutboundModel(StrictBaseModel):
    """Base for anything BrainBuddy sends: strict, and camelCase on the wire."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        arbitrary_types_allowed=False,
        serialize_by_alias=True,
    )


# --- task and message shapes -------------------------------------------------


class TaskState(str, Enum):
    """A2A task lifecycle states (§3.4).

    ``UNSPECIFIED`` is a real wire value, not a parsing failure: an agent that
    sends it has told us it is alive and nothing more, which the projection
    records as a contact rather than as progress.
    """

    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    REJECTED = "TASK_STATE_REJECTED"
    CANCELED = "TASK_STATE_CANCELED"

    @classmethod
    def _missing_(cls, value: object) -> TaskState:
        """An unknown state is "alive, meaning unknown" — never an error.

        A future A2A state must not make an observation fail: failing would
        strand the run in its previous state, which the surfaces would render as
        the agent having gone quiet. Degrading to ``UNSPECIFIED`` refreshes
        contact and claims nothing.
        """

        return cls.UNSPECIFIED


TERMINAL_TASK_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.REJECTED,
        TaskState.CANCELED,
    }
)


class Part(InboundModel):
    """One piece of a message or artifact.

    A2A models a part as a oneof; this keeps the alternatives as optional
    fields because a lenient parser must survive an agent that sends a shape
    the spec does not name. ``kind`` reports which alternative was populated.
    """

    text: str | None = None
    url: str | None = None
    file: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    media_type: str | None = Field(default=None, alias="mediaType")
    name: str | None = None

    @property
    def kind(self) -> Literal["text", "link", "file", "data", "unknown"]:
        if self.text is not None:
            return "text"
        if self.url is not None:
            return "link"
        if self.file is not None:
            return "file"
        if self.data is not None:
            return "data"
        return "unknown"

    @property
    def effective_media_type(self) -> str | None:
        """Media type, preferring the part's own then the file descriptor's."""

        if self.media_type:
            return self.media_type
        if self.file:
            raw = self.file.get("mediaType") or self.file.get("mimeType")
            return raw if isinstance(raw, str) else None
        return None


class Message(InboundModel):
    """One message in a conversation, inbound or outbound."""

    message_id: str | None = Field(default=None, alias="messageId")
    context_id: str | None = Field(default=None, alias="contextId")
    task_id: str | None = Field(default=None, alias="taskId")
    role: str | None = None
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    extensions: list[str] = Field(default_factory=list)
    reference_task_ids: list[str] = Field(
        default_factory=list, alias="referenceTaskIds"
    )

    @property
    def text(self) -> str:
        """Text parts joined by a blank line; non-text parts are ignored."""

        return "\n\n".join(part.text for part in self.parts if part.text)


class TaskStatus(InboundModel):
    """The current state of a task, plus whatever the agent said about it."""

    state: TaskState = TaskState.UNSPECIFIED
    timestamp: str | None = None
    message: Message | None = None

    @property
    def text(self) -> str:
        return self.message.text if self.message is not None else ""


class Artifact(InboundModel):
    """A named output of a task."""

    artifact_id: str | None = Field(default=None, alias="artifactId")
    name: str | None = None
    description: str | None = None
    parts: list[Part] = Field(default_factory=list)


class Task(InboundModel):
    """One unit of agent work, addressed by ``id`` inside a ``contextId``."""

    id: str
    context_id: str | None = Field(default=None, alias="contextId")
    status: TaskStatus = Field(default_factory=TaskStatus)
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class TaskPushNotificationConfig(OutboundModel):
    """Where an agent should POST a push notification for a task.

    The token is part of the URL because Hermes stores only the URL of a push
    config and signs with a secret BrainBuddy cannot know; a header-only token
    would leave its pushes unverifiable. It is echoed in ``token`` as well for
    SDK servers, which send it back as ``X-A2A-Notification-Token``.
    """

    url: str
    token: str | None = None


# --- JSON-RPC 2.0 envelope ---------------------------------------------------


class JsonRpcRequest(OutboundModel):
    """One outbound call. ``method`` is PascalCase per the A2A binding."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcError(InboundModel):
    """A JSON-RPC error object. ``data`` is never logged or shown."""

    code: int
    message: str = ""
    data: Any = None


class JsonRpcResponse(InboundModel):
    """One inbound answer, carrying exactly one of ``result`` / ``error``.

    "Exactly one" is enforced rather than assumed. A body with both is not a
    partial success to salvage: BrainBuddy cannot tell which half the agent
    meant, and guessing on a hand-off is how a run acquires a state nobody
    reported. Such a body becomes ``a2a_response_invalid``, which for a start
    exchange means *delivery unconfirmed* — lookup before any resend.
    """

    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> JsonRpcResponse:
        if (self.result is None) == (self.error is None):
            raise ValueError(
                "a JSON-RPC response must carry exactly one of result / error"
            )
        return self


# --- agent card --------------------------------------------------------------
#
# Both accepted shapes live in one model rather than two, because a real card
# mixes them: Hermes serves 1.0 `supportedInterfaces` beside a legacy
# `securitySchemes` entry and a legacy top-level `url`.


class CardInterface(InboundModel):
    """One transport the agent offers.

    The legacy shape has no per-interface ``protocolVersion``; the card's
    top-level one applies then. ``card.py`` resolves that, not this model.
    """

    url: str
    protocol_binding: str | None = Field(default=None, alias="protocolBinding")
    preferred_transport: str | None = Field(default=None, alias="preferredTransport")
    protocol_version: str | None = Field(default=None, alias="protocolVersion")
    tenant: str | None = None

    @property
    def binding(self) -> str:
        """The transport name, from either the 1.0 or the legacy field."""

        return (self.protocol_binding or self.preferred_transport or "").strip()


class CardExtension(InboundModel):
    """A declared protocol extension (A2A §4.6)."""

    uri: str
    description: str | None = None
    required: bool = False
    params: dict[str, Any] | None = None


class CardCapabilities(InboundModel):
    """Declared capabilities. Unknown ones (Hermes adds two) are ignored."""

    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    extensions: list[CardExtension] = Field(default_factory=list)


class CardSecurityScheme(InboundModel):
    """A security scheme in either the 1.0 or the legacy shape.

    1.0 nests the detail under ``httpAuthSecurityScheme`` /
    ``apiKeySecurityScheme``; the legacy shape is flat with ``type`` plus
    ``scheme`` / ``in`` + ``name``. Both are kept verbatim and normalised in
    ``card.py``, so this model never has to decide which one is "right".
    """

    type: str | None = None
    scheme: str | None = None
    location: str | None = Field(default=None, alias="in")
    name: str | None = None
    http_auth: dict[str, Any] | None = Field(
        default=None, alias="httpAuthSecurityScheme"
    )
    api_key: dict[str, Any] | None = Field(default=None, alias="apiKeySecurityScheme")


class CardSkill(InboundModel):
    """One advertised skill. Every string here is untrusted agent text."""

    id: str | None = None
    name: str | None = None
    description: str | None = None


class AgentCard(InboundModel):
    """A parsed agent card, in whichever of the two shapes it arrived."""

    name: str | None = None
    version: str | None = None
    description: str | None = None
    protocol_version: str | None = Field(default=None, alias="protocolVersion")
    url: str | None = None
    preferred_transport: str | None = Field(default=None, alias="preferredTransport")
    supported_interfaces: list[CardInterface] = Field(
        default_factory=list, alias="supportedInterfaces"
    )
    capabilities: CardCapabilities = Field(default_factory=CardCapabilities)
    security_schemes: dict[str, CardSecurityScheme] = Field(
        default_factory=dict, alias="securitySchemes"
    )
    security_requirements: list[dict[str, Any]] = Field(
        default_factory=list, alias="securityRequirements"
    )
    security: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[CardSkill] = Field(default_factory=list)

    @property
    def interfaces(self) -> list[CardInterface]:
        """Every offered interface, including the legacy top-level ``url``.

        A legacy card states its transport once, at the top level; presenting it
        as an interface here means selection logic has exactly one shape to
        reason about instead of two.
        """

        if self.supported_interfaces:
            return list(self.supported_interfaces)
        if self.url:
            return [
                CardInterface(
                    url=self.url,
                    preferredTransport=self.preferred_transport or "JSONRPC",
                    protocolVersion=self.protocol_version,
                )
            ]
        return []

    @property
    def declared_requirements(self) -> list[dict[str, Any]]:
        """Security requirements from either the 1.0 or the legacy key."""

        return self.security_requirements or self.security


__all__ = [
    "CONTENT_TYPE_NOT_SUPPORTED",
    "EXTENDED_CARD_NOT_CONFIGURED",
    "EXTENSION_SUPPORT_REQUIRED",
    "INTERNAL_ERROR",
    "INVALID_AGENT_RESPONSE",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "LOGGABLE_ERROR_CODES",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PUSH_NOTIFICATION_NOT_SUPPORTED",
    "RATE_LIMITED",
    "TASK_NOT_CANCELABLE",
    "TASK_NOT_FOUND",
    "TERMINAL_TASK_STATES",
    "UNAUTHORIZED",
    "UNSUPPORTED_OPERATION",
    "UNTRUSTED",
    "VERSION_NOT_SUPPORTED",
    "AgentCard",
    "Artifact",
    "CardCapabilities",
    "CardExtension",
    "CardInterface",
    "CardSecurityScheme",
    "CardSkill",
    "InboundModel",
    "JsonRpcError",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "Message",
    "OutboundModel",
    "Part",
    "Task",
    "TaskPushNotificationConfig",
    "TaskState",
    "TaskStatus",
    "loggable_error_code",
]
