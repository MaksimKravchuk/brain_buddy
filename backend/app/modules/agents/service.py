"""Application service for the external-agent relay.

The organising rule of this module is that BrainBuddy only ever states what it
actually knows. There are three independent sources of truth about a run and
they are never blended: what BrainBuddy did (``dispatch_state``), what the
the agent's own Task says (``reported_state`` at ``run_version``), and what the
clock implies (``Stopped reporting``). A user request that has not been
acknowledged is a fourth, separate thing. Nothing here computes a percentage, an
ETA, or a completion BrainBuddy did not witness.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Protocol

from pydantic import BaseModel

from app.exceptions import (
    BrainBuddyError,
    ConflictError,
    NotFoundError,
    ValidationFailure,
)
from app.schemas.agents import (
    AgentArtifactSummaryResponse,
    AgentCapabilitiesResponse,
    AgentCardResponse,
    AgentCheckDeliveryRequest,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionUpdateRequest,
    AgentContextItemResponse,
    AgentControlsResponse,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentManifestResponse,
    AgentPushCallbackResponse,
    AgentReplyRequest,
    AgentRunCommandResponse,
    AgentRunEventResponse,
    AgentRunResponse,
    AgentRunSummaryResponse,
)
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .a2a.card import (
    A2A_AUTH_SCHEME_UNSUPPORTED,
    A2A_NO_SUPPORTED_INTERFACE,
    A2A_NOT_AN_AGENT,
    A2A_PROTOCOL_VERSION_UNSUPPORTED,
    A2A_UNREACHABLE,
    AGENT_CARD_CHANGED,
    SINGLE_START_EXTENSION_URI,
    AuthScheme,
    CardDiscovery,
    fetch_card,
)
from .a2a.client import (
    A2A_CONTENT_UNSUPPORTED,
    A2A_CREDENTIALS_REJECTED,
    A2A_EXTENSION_SUPPORT_REQUIRED,
    A2A_METHOD_NOT_FOUND,
    A2A_NOT_CANCELABLE,
    A2A_RATE_LIMITED,
    A2A_REQUEST_REJECTED,
    A2A_RESPONSE_INVALID,
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
    A2A_VERSION_NOT_SUPPORTED,
    A2AClientPort,
    A2AResult,
    A2ATarget,
)
from .a2a.mapping import Observation, ObservationLimits, project_observation
from .a2a.types import TERMINAL_TASK_STATES, Task, TaskState
from .domain import (
    A2A_PROTOCOL_VERSION,
    CANCEL_OUTCOMES_WITHDRAWING_THE_CONTROL,
    MAX_CONTEXT_ITEMS,
    TASK_SUCCESSION_SUMMARY,
    TERMINAL_REPORTED_STATES,
    AgentArtifactSummary,
    AgentAuditEntryDocument,
    AgentCancelOutcome,
    AgentCapabilities,
    AgentCommandDelivery,
    AgentCommandKind,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentManifestContextItem,
    AgentPrimaryStateLabel,
    AgentPushCallback,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
    AgentRunEventKind,
    AgentRunEventTrigger,
    AgentRunManifest,
    bounded_test_error_detail,
    cancel_control_offered,
    content_is_due,
    inert_reporting_contract,
    primary_state_label,
    project_run_for_access,
    reply_control_offered,
    stopped_reporting,
)
from .egress import (
    DestinationRejected,
    Resolver,
    interactive_result_link,
    validate_destination,
)
from .headers import usable_auth_header_name
from .repository import AgentRepository
from .secrets import (
    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
    SecretBox,
    SecretDecryptionFailed,
    derive_push_token,
    push_token_fingerprint,
    push_token_matches,
    secret_aad,
)

DEFAULT_STALE_AFTER = timedelta(days=7)
DEFAULT_REPORTING_WINDOW = timedelta(hours=1)
DEFAULT_OBSERVATION_INTERVAL = timedelta(seconds=60)

#: History length for the one case that needs it. Twenty messages is enough
#: to carry a question or a closing summary, and small enough that an agent
#: cannot make an ordinary poll expensive by talking a lot.
OBSERVATION_HISTORY_LENGTH = 20

#: Beyond this many doublings the cap has long since applied; computing
#: `2 ** missed` for a run silent for months would be an integer nobody
#: needs.
_MAX_BACKOFF_DOUBLINGS = 16

#: The states whose meaning is carried by text the user has to read: a
#: question they are being asked, or the agent's closing account of what it
#: did. Everything else is legible from the state alone.
TEXT_BEARING_TASK_STATES: frozenset[TaskState] = frozenset(
    {TaskState.INPUT_REQUIRED, *TERMINAL_TASK_STATES}
)


@dataclass(frozen=True, slots=True)
class PushOutcome:
    """What one inbound push turned out to be.

    Deliberately not a run and not a reason string. The route answers one
    opaque refusal for every failure, so anything richer crossing this
    boundary would be a fact waiting to leak into a response header, a
    timing difference or a log line.
    """

    owner_id: str | None
    verified: bool
    closed: bool


#: The answer for a run that does not exist, was never dispatched, or whose
#: identifiers have expired. No owner, so no row and no limiter key.
PUSH_UNKNOWN = PushOutcome(owner_id=None, verified=False, closed=False)

#: The only agent answers that may reject a *reply* outright: an explicit
#: statement that the task will not take one. Everything else leaves the
#: command unconfirmed, because silence is not a refusal.
REPLY_REJECTING_ERROR_CODES: frozenset[int] = frozenset({-32004, -32601})

#: One `CancelTask` answer to one outcome (a2a-wire.md, Error mapping). Only
#: an explicit agent answer appears here; every other ending falls through to
#: `unconfirmed`, which keeps the control and the command id.
CANCEL_OUTCOME_BY_ERROR_CODE: dict[str, AgentCancelOutcome] = {
    A2A_NOT_CANCELABLE: "not_cancelable",
    A2A_UNSUPPORTED_OPERATION: "unsupported",
    A2A_METHOD_NOT_FOUND: "unsupported",
    A2A_TASK_NOT_FOUND: "task_missing",
}

#: How each outcome reads on the command row. `rejected` only where the
#: agent answered about this command; `unconfirmed` everywhere else.
CANCEL_DELIVERY_BY_OUTCOME: dict[str, AgentCommandDelivery] = {
    "accepted": "confirmed",
    "not_cancelable": "rejected",
    "unsupported": "rejected",
    "task_missing": "rejected",
    "unconfirmed": "unconfirmed",
}
"""The base schedule, and the rate the clients are told to poll at.

The server may observe *less* often after the reporting window (the FR-008
backoff); it never observes more often on the schedule, so telling a client
this number is a promise the server can keep."""
DEFAULT_CONTENT_RETENTION = timedelta(days=30)
SCOPE_REAUTH_WINDOW = timedelta(minutes=15)
RESERVATION_TTL = timedelta(hours=1)
DEFAULT_REPLY_WINDOW = timedelta(minutes=5)

#: Failures that prove the message was refused before the agent could act on it.
#:
#: Everything *not* here is ambiguous by construction and becomes **Delivery
#: unconfirmed** — a timeout, a 5xx or a breached deadline all mean the request
#: may already be at the agent, and demoting one of those to "not sent" is the
#: single claim that turns an honest unknown into a lie the user acts on.
NOT_SENT_ERROR_CODES = frozenset(
    {
        A2A_UNREACHABLE,
        A2A_CREDENTIALS_REJECTED,
        A2A_RATE_LIMITED,
        A2A_REQUEST_REJECTED,
        A2A_METHOD_NOT_FOUND,
        A2A_UNSUPPORTED_OPERATION,
        A2A_CONTENT_UNSUPPORTED,
        A2A_EXTENSION_SUPPORT_REQUIRED,
        A2A_VERSION_NOT_SUPPORTED,
    }
)

EXTERNAL_COPY_NOTICE = (
    "Your agent receives its own copy of everything listed here. BrainBuddy "
    "cannot guarantee that its retention cleanup, disconnect, or account "
    "deletion erases that copy."
)

# --- server-owned disclosures (FR-003, FR-011, FR-014) -----------------------
#
# These three sentences are the product's promise about what a hand-off to this
# agent can and cannot guarantee, so they are minted here and rendered verbatim
# by both clients. Assembling them client-side would let web and iOS drift into
# two different promises about the same agent, and the drift would show up as a
# duplicate task rather than as a typo.

GUARANTEED_TIER_DISCLOSURE = (
    "Guaranteed single start. This agent's card declares BrainBuddy's "
    "single-start extension: it deduplicates by message ID inside one "
    "conversation and returns the original task on a replay, so a retry cannot "
    "start a second run."
)

BEST_EFFORT_TIER_DISCLOSURE = (
    "Best-effort single start. This agent's card does not declare BrainBuddy's "
    "single-start extension. Before any retry BrainBuddy checks the agent for an "
    "existing task and adopts it instead of sending again. A duplicate remains "
    "possible if the agent forgets its tasks."
)

PUSH_CALLBACK_DISCLOSURE = (
    "BrainBuddy also gives this agent a private callback address with a per-run "
    "token so it can tell BrainBuddy when to check on the run. The agent keeps "
    "that address until the run ends. It can only use it to ask BrainBuddy to "
    "check on the run — no task content ever comes back through it."
)

CANCELLATION_DISCLOSURE = (
    "Cancellation depends on the agent. Agent cards do not advertise whether "
    "cancellation works, so BrainBuddy can only find out once you request it. If "
    "the agent refuses, BrainBuddy says so and keeps the last state it observed."
)

TIER_DISCLOSURES: dict[str, str] = {
    "guaranteed": GUARANTEED_TIER_DISCLOSURE,
    "best_effort": BEST_EFFORT_TIER_DISCLOSURE,
}

#: Fallback discovery policy, used only when no `card_fetcher` is injected. The
#: container always injects one built from `AgentRelaySettings`; these exist so a
#: service constructed in a test still has a working, bounded default rather than
#: an unbounded fetch or none at all.
DEFAULT_CARD_TIMEOUT_SECONDS = 10.0
DEFAULT_CARD_MAX_RESPONSE_BYTES = 64_000

#: The sentinel task id of the ``GetTask`` fallback probe. Deliberately a name
#: no agent would mint: a ``-32001`` answer to it proves the credential was
#: accepted *before* the lookup failed, which is exactly what the test needs to
#: learn from an agent that does not implement ``ListTasks``.
PROBE_TASK_ID = "brainbuddy-probe"

#: Client failure codes that mean "the credential was refused", whatever the
#: transport said.
_CREDENTIALS_REJECTED = frozenset({A2A_CREDENTIALS_REJECTED})

#: Connection failures a hand-off refusal names verbatim instead of collapsing
#: into "not ready". Each one has a different corrective action, and a user who
#: is told only "not ready" about a rate limit will retest immediately and be
#: rate limited again (contracts/api-deltas.md, error reasons).
_DISPATCH_REFUSAL_REASONS = frozenset(
    {A2A_AUTH_SCHEME_UNSUPPORTED, A2A_RATE_LIMITED, AGENT_CARD_CHANGED}
)

#: Discovery failures that are the agent's *shape*, not its reachability. Each
#: one is its own sentence on D-01-S14..S17.
_UNSUPPORTED_DISCOVERY_CODES = frozenset(
    {
        A2A_NOT_AN_AGENT,
        A2A_NO_SUPPORTED_INTERFACE,
        A2A_PROTOCOL_VERSION_UNSUPPORTED,
        A2A_AUTH_SCHEME_UNSUPPORTED,
    }
)


class RelayKeyRotationUnsafe(BrainBuddyError):
    """A relay key was retired while records only it can find are still live.

    Raised instead of serving the request, because the alternative is worse than
    an outage: an Idempotency-Key whose record cannot be found reads as a first
    attempt, and the run is started, replied to, or cancelled on the user's
    agent a second time. Restoring the retired key id to the ring clears it.
    """

    def __init__(self, retired_key_ids: Sequence[str]) -> None:
        super().__init__(
            "BrainBuddy cannot currently guarantee this agent command runs only "
            "once, so it was not sent. Try again shortly."
        )
        # Key ids are configuration labels, safe for operators to act on; the
        # message the user sees deliberately carries neither them nor the key.
        self.retired_key_ids = tuple(retired_key_ids)


class RelayFingerprintUnreadable(BrainBuddyError):
    """Live idempotency rows are malformed, so replay cannot be proven safe."""

    def __init__(self, unreadable_records: int) -> None:
        super().__init__(
            "BrainBuddy cannot currently guarantee this agent command runs only "
            "once, so it was not sent. Try again shortly."
        )
        # Only a count is retained: hashes and key ids must not reach error
        # responses, logs, audit records, or account exports.
        self.unreadable_records = unreadable_records


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """The only thing the relay may read from a Task: never a write path."""

    id: str
    title: str
    details: str | None


class TaskSnapshotPort(Protocol):
    def __call__(self, task_id: str, *, owner_id: str) -> TaskSnapshot: ...


class ExchangeExecutorPort(Protocol):
    """The one method the exchange pool needs from an executor.

    A protocol rather than `concurrent.futures.Executor` for the usual reason,
    and for a sharper one. The usual: a test can pass a synchronous double and
    drive a state machine without threads or sleeps. The sharper: the pool this
    describes is deliberately *bounded* (`exchange_workers`, data-model §9)
    because a held `SendMessage` occupies a worker for up to the reply window,
    and an unbounded one would let a single slow agent consume the process. The
    narrow port keeps that bound a property of what is injected here rather than
    something the service could quietly opt out of.
    """

    def submit(
        self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> Future[Any]: ...


@dataclass(frozen=True)
class ExchangePolicy:
    """Everything the wire lanes need from deployment, in one object.

    Grouped rather than passed as five more constructor arguments because they
    are one decision, not five: who runs an exchange, how long the request
    thread waits on it, how long the agent gets, how often BrainBuddy looks
    afterwards, and how much of the agent's text an observation may keep. A
    deployment that changes one of these almost always means to change its
    neighbours — halving the reply window without touching the observation
    interval, for instance, just makes the schedule poll a run nobody is
    waiting on any more.
    """

    #: The bounded pool exchanges run on. ``None`` means nothing runs them here,
    #: which leaves confirmed hand-offs **Queued** — a true statement about
    #: them, and never mistaken for sent.
    executor: ExchangeExecutorPort | None = None
    #: How long the request thread waits on a submitted exchange before it
    #: answers with what is honestly known. Zero means "never block the
    #: request"; it never means "assume it was sent".
    dispatch_wait_seconds: float = 0.0
    #: FR-007's promise to the agent, and the bound on one exchange.
    reply_window: timedelta = DEFAULT_REPLY_WINDOW
    #: The base schedule, and the rate the clients are told to poll at. The
    #: server may observe *less* often after the reporting window (the FR-008
    #: backoff); it never observes more often on the schedule, so telling a
    #: client this number is a promise the server can keep.
    observation_interval: timedelta = DEFAULT_OBSERVATION_INTERVAL
    observation_limits: ObservationLimits = field(default_factory=ObservationLimits)


#: Shared because it is frozen: no caller can mutate another's policy.
DEFAULT_EXCHANGE_POLICY = ExchangePolicy()


class CardFetcherPort(Protocol):
    """Discovery, as the one call the service depends on.

    Narrow on purpose. Everything the real fetch needs from deployment — the
    timeout, the response cap, the private-destination opt-in, the resolver — is
    bound once by whoever constructs it, so the service never has to hold that
    policy and a test can hand it a scripted result without a socket.
    """

    def __call__(
        self,
        address: str,
        *,
        auth_scheme: AuthScheme,
        now: datetime | None = ...,
    ) -> CardDiscovery: ...


def _disconnected_refusal(
    connection: AgentConnectionDocument, message: str
) -> ValidationFailure:
    """Refuse on a disconnected connection, saying *who* disconnected it.

    "Disconnected" is true of a migrated 007 record but useless: the owner never
    disconnected it, an upgrade did, and the corrective action is to add the
    agent again by its address rather than to wonder what they clicked. So the
    reason travels with the refusal (FR-012, SC-010).
    """

    if connection.disconnect_reason == "superseded_wire_contract":
        return ValidationFailure(
            "This connection was made under BrainBuddy's previous agent wire, "
            "which no longer exists. Add the agent again by its address.",
            detail={"reason": "superseded_wire_contract"},
        )
    return ValidationFailure(message, detail={"reason": "connection_disconnected"})


class AgentRelayService:
    """Owns connections, runs, and the honest projection of both."""

    def __init__(
        self,
        agent_repo: AgentRepository,
        *,
        secret_box: SecretBox,
        task_snapshot: TaskSnapshotPort,
        # The origin the per-run push callback lives under. Part of the manifest
        # token, so a deployment that moved cannot let a stale confirmation hand
        # the agent an address BrainBuddy no longer answers on.
        push_base_url: str = "",
        # The A2A wire and its bounded exchange lane, injected here rather than
        # constructed inside the service. Both are optional for one transitional
        # reason: this build still speaks the bespoke 007 wire alongside them,
        # and the observer that drives them arrives later. Taking them in the
        # constructor now is what keeps the wiring acyclic — the container owns
        # every collaborator, so the client never needs a service and the
        # service never needs a container (plan.md, "Delivery boundary").
        a2a_client: A2AClientPort | None = None,
        exchange: ExchangePolicy = DEFAULT_EXCHANGE_POLICY,
        # Discovery. Optional so the container can bind deployment policy into
        # it once; when it is absent the service builds the default below from
        # the same settings, so there is never a service that cannot discover.
        card_fetcher: CardFetcherPort | None = None,
        tier_disclosure_url: str = SINGLE_START_EXTENSION_URI,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
        reporting_window: timedelta = DEFAULT_REPORTING_WINDOW,
        content_retention: timedelta = DEFAULT_CONTENT_RETENTION,
        allow_private_destinations: bool = False,
        resolver: Resolver | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.agent_repo = agent_repo
        self.a2a_client = a2a_client
        self.exchange_executor = exchange.executor
        self.dispatch_wait_seconds = exchange.dispatch_wait_seconds
        self.reply_window = exchange.reply_window
        self.observation_limits = exchange.observation_limits
        # Set by the container once the observer exists, so the service never
        # needs to know how exchanges are scheduled — only that they are.
        self.exchange_pump: Callable[[str, str], Future[Any] | None] | None = None
        # The dedicated control lane. A cancel is what *resolves* a blocked
        # exchange on some runtimes, so it must never queue behind the very
        # exchanges it ends (AC-035). `None` means "run it here", which is the
        # honest fallback for a service constructed without an observer.
        self.control_pump: Callable[[Callable[[], A2AResult]], Future[A2AResult]] | (
            None
        ) = None
        # Woken by a verified push so the observation it earns runs at once
        # rather than waiting out the interval. Narrow on purpose: a push may
        # only *accelerate* an observation, never supply one.
        self.observer_wake: Callable[[str], None] | None = None
        # Set by the route that owns the limiter, so the service can drop a
        # bucket for a run that can never be pushed for again without knowing
        # anything about how the limiter works.
        self.evict_push_limiter: Callable[[str], bool] | None = None
        self.secret_box = secret_box
        self.task_snapshot = task_snapshot
        self.push_base_url = push_base_url
        self.tier_disclosure_url = tier_disclosure_url
        self.stale_after = stale_after
        self.reporting_window = reporting_window
        self.observation_interval = exchange.observation_interval
        self.content_retention = content_retention
        self.allow_private_destinations = allow_private_destinations
        self._resolver = resolver
        self._now = now
        self._card_fetcher: CardFetcherPort = card_fetcher or partial(
            fetch_card,
            timeout_seconds=DEFAULT_CARD_TIMEOUT_SECONDS,
            max_response_bytes=DEFAULT_CARD_MAX_RESPONSE_BYTES,
            allow_private_destinations=allow_private_destinations,
            resolver=resolver,
        )

    # --- shared helpers -----------------------------------------------------

    @staticmethod
    def _canonical_request(
        command: str,
        payload: BaseModel | Mapping[str, Any],
        *,
        target: str | None,
    ) -> str:
        """The exact request this Idempotency-Key was spent on.

        ``target`` is part of the identity, not context around it: without it a
        key spent on one run or connection would silently satisfy the same
        command aimed at a *different* one, returning a success-shaped answer
        while the action the caller asked for never happened.
        """

        body = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else dict(payload)
        )
        # The password is a proof of possession, not part of the request's
        # identity: including it would make an otherwise identical replay look
        # different, and would put it in a stored fingerprint.
        body.pop("current_password", None)
        return json.dumps(
            {"v": 1, "command": command, "target": target, "payload": body},
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _idempotency_scope(owner_id: str, key: str) -> str:
        """The exact bytes one owner's Idempotency-Key is fingerprinted from."""

        return json.dumps(
            {"v": 1, "scope": "idempotency-key", "owner": owner_id, "key": key},
            sort_keys=True,
            separators=(",", ":"),
        )

    def _key_hashes(self, owner_id: str, key: str) -> list[str]:
        """Every form this key could already be stored under, for lookup only.

        Never use the head of this list as the form to *write*: it follows the
        active key, so two instances mid-rotation would file the same
        Idempotency-Key under two different rows. ``_key_fingerprint`` is the
        one identity a write, a lock, and a later lookup all agree on.
        """

        return self.secret_box.fingerprint_candidates(
            self._idempotency_scope(owner_id, key)
        )

    def _key_fingerprint(self, owner_id: str, key: str) -> str:
        """The single identity of this Idempotency-Key: row, lock, and replay.

        Anchored to the oldest configured key (see ``SecretBox.fingerprint``),
        so an instance that has the new key and one that does not both name the
        same row and take the same operation lock for the same command.
        """

        return self.secret_box.fingerprint(self._idempotency_scope(owner_id, key))

    def _require_intact_key_ring(self, now: datetime) -> None:
        """Refuse commands if any owner's live sealed reference needs a retired key.

        Key configuration is process-global, so checking only the requesting owner
        would let another quiet owner's credential become undecryptable. The
        repository reads only key labels and retention metadata: rotation never
        decrypts or logs plaintext.
        """

        live = self.agent_repo.live_sealed_key_ids(now=now)
        if live.unreadable:
            raise RelayFingerprintUnreadable(live.unreadable)
        retired = sorted(live.key_ids - set(self.secret_box.key_ids))
        if retired:
            raise RelayKeyRotationUnsafe(retired)

    def _replayed(
        self, *, owner_id: str, key: str, command: str, canonical: str
    ) -> tuple[str, AgentIdempotencyRecord | None]:
        """Resolve a key to its stored record, refusing a reused key.

        Returns the hash the record is (or would be) stored under, so a later
        write updates that row rather than creating a second one under a newer
        key id.
        """

        now = self._now()
        # Expired reservations must not answer for a key that is free again.
        self.agent_repo.purge_expired_idempotency(owner_id=owner_id, now=now)
        # Only what survived that purge can make a rotation unsafe.
        self._require_intact_key_ring(now)
        record = self.agent_repo.get_idempotency(
            owner_id=owner_id, key_hashes=self._key_hashes(owner_id, key)
        )
        if record is None:
            return self._key_fingerprint(owner_id, key), None
        if record.command != command or not self.secret_box.fingerprint_matches(
            record.request_hash, canonical
        ):
            raise ConflictError(
                # Never the key itself: this identifier reaches error responses.
                "Idempotency-Key",
                record.resource_id,
                "This Idempotency-Key was already used for a different request.",
            )
        return record.key_hash, record

    def _remember(
        self,
        *,
        owner_id: str,
        key_hash: str,
        command: str,
        canonical: str,
        resource_id: str,
        command_id: str | None = None,
        delivery_attempted: bool = False,
        completed: bool = True,
        request_hash: str | None = None,
        created_at: datetime | None = None,
        response_body: dict[str, object] | None = None,
    ) -> None:
        self.agent_repo.save_idempotency(
            owner_id=owner_id,
            record=AgentIdempotencyRecord(
                key_hash=key_hash,
                command=command,
                request_hash=(
                    request_hash
                    if request_hash is not None
                    else self.secret_box.fingerprint(canonical)
                ),
                resource_id=resource_id,
                command_id=command_id,
                delivery_attempted=delivery_attempted,
                completed=completed,
                # Only ever IDs and sealed blobs: this row is ordinary
                # application data and must stay readable to no one.
                response_body=(
                    response_body if response_body is not None else {"id": resource_id}
                ),
                created_at=created_at if created_at is not None else self._now(),
            ),
        )

    def _reserve_command(
        self,
        *,
        owner_id: str,
        key_hash: str,
        command: str,
        canonical: str,
        resource_id: str,
        record: AgentIdempotencyRecord | None,
        now: datetime,
        response_body: dict[str, object] | None = None,
    ) -> tuple[str, datetime]:
        """Pin one command ID for this key, durably, before any network I/O.

        A command that leaves the process can fail ambiguously: the agent may
        have taken it and the acknowledgement lost. The ID is therefore written
        first and reused on every retry of the same key, so the agent sees one
        logical command however many times BrainBuddy has to ask.

        Returns the ID and the reservation's original timestamp, so retrying
        does not push the record's 24-hour expiry further out.
        """

        if record is not None and record.command_id is not None:
            return record.command_id, record.created_at
        command_id = generate_id("agentcmd")
        created_at = record.created_at if record is not None else now
        self._remember(
            owner_id=owner_id,
            key_hash=key_hash,
            command=command,
            canonical=canonical,
            resource_id=resource_id,
            command_id=command_id,
            completed=False,
            created_at=created_at,
            response_body=response_body,
        )
        return command_id, created_at

    def _begin_delivery_attempt(
        self,
        *,
        owner_id: str,
        key_hash: str,
        command: str,
        canonical: str,
        resource_id: str,
        command_id: str,
        created_at: datetime,
        request_hash: str | None = None,
        response_body: dict[str, object] | None = None,
    ) -> None:
        """Durably distinguish a safe-to-send reservation from ambiguous I/O."""

        self.agent_repo.commit_checkpoint()
        self._remember(
            owner_id=owner_id,
            key_hash=key_hash,
            command=command,
            canonical=canonical,
            resource_id=resource_id,
            command_id=command_id,
            delivery_attempted=True,
            completed=False,
            request_hash=request_hash,
            created_at=created_at,
            response_body=response_body,
        )
        self.agent_repo.commit_checkpoint()

    def _reconcile_attempted_command(
        self,
        record: AgentIdempotencyRecord | None,
        *,
        owner_id: str,
        canonical: str,
        kind: AgentCommandKind,
        body: str | None = None,
    ) -> AgentRunResponse | None:
        """Settle an ambiguous durable attempt without repeating connector I/O."""

        if (
            record is None
            or record.completed
            or not record.delivery_attempted
            or record.command_id is None
        ):
            return None
        current = self.agent_repo.get_run(record.resource_id, owner_id=owner_id)
        existing = self.agent_repo.get_command(record.command_id, owner_id=owner_id)
        if existing is None:
            self.agent_repo.save_command(
                AgentRunCommandDocument(
                    id=record.command_id,
                    owner_id=owner_id,
                    run_id=current.id,
                    kind=kind,
                    body=None if current.content_expired else body,
                    delivery="unconfirmed",
                    created_at=record.created_at,
                )
            )
        if kind == "cancel":
            connection = self.agent_repo.get_connection(
                current.connection_id, owner_id=owner_id
            )
            if (
                current.reported_state not in TERMINAL_REPORTED_STATES
                and connection.status != "disconnected"
                and connection.revision
                == record.response_body.get("connection_revision")
            ):
                merge_time = max(current.updated_at, self._now())
                current = current.model_copy(
                    update={
                        "cancel_requested_at": record.created_at,
                        "updated_at": merge_time,
                        "revision": current.revision + 1,
                    }
                )
                self.agent_repo.save_run(current)
        self._remember(
            owner_id=owner_id,
            key_hash=record.key_hash,
            command=record.command,
            canonical=canonical,
            resource_id=current.id,
            command_id=record.command_id,
            delivery_attempted=True,
            created_at=record.created_at,
            request_hash=record.request_hash,
        )
        return self._run_response(current)

    def _audit(
        self,
        *,
        owner_id: str,
        action: str,
        outcome: str,
        connection_id: str | None = None,
        run_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        self.agent_repo.append_audit(
            AgentAuditEntryDocument(
                id=generate_id("agentaudit"),
                owner_id=owner_id,
                action=action,
                outcome=outcome,
                connection_id=connection_id,
                run_id=run_id,
                correlation_id=correlation_id,
                created_at=self._now(),
            )
        )

    def _bounded_audit(
        self,
        *,
        owner_id: str,
        action: str,
        outcome: str,
        bucket: str,
        connection_id: str | None = None,
        run_id: str | None = None,
    ) -> bool:
        """One coarse row per class and UTC day, however often the class recurs.

        The observer polls every sixty seconds and the push route is reachable
        by anyone who guesses a run id, so an unbounded row per event would
        turn an accountability record into a growth problem — and the ninetieth
        row of a day tells the owner nothing the first did not.
        """

        now = self._now()
        return self.agent_repo.append_bounded_audit(
            AgentAuditEntryDocument(
                id=generate_id("agentaudit"),
                owner_id=owner_id,
                action=action,
                outcome=outcome,
                connection_id=connection_id,
                run_id=run_id,
                created_at=now,
            ),
            bucket=bucket,
            day=now.astimezone(UTC).date().isoformat(),
        )

    def _validate_endpoint(self, endpoint_url: str) -> None:
        try:
            validate_destination(
                endpoint_url,
                allow_private_destinations=self.allow_private_destinations,
                resolver=self._resolver,
            )
        except DestinationRejected as exc:
            raise ValidationFailure(exc.message, detail={"reason": exc.code}) from exc

    def _a2a_target(
        self,
        connection: AgentConnectionDocument,
        *,
        interface_url: str,
        auth_header_name: str | None = None,
        guarantee_tier: str | None = None,
        authenticated: bool | None = None,
    ) -> A2ATarget:
        """Where one A2A call goes, and the credential it may carry.

        The interface is passed in rather than read off the connection because
        a *test* uses the interface the card just named while an *observation*
        must use the one pinned at dispatch: a card that moves mid-run must not
        be able to redirect a live run's traffic.

        `authenticated` is the same question for the credential: an agent whose
        card declares no security scheme asked for none, so it is sent none.
        A *test* knows that from the discovery it just performed; every later
        call reads it back off the stored card summary. Absent a card — a
        connection that has never been tested — the credential is sent, because
        withholding it would silently downgrade a connection to anonymous.
        """

        if authenticated is None:
            authenticated = connection.card is None or bool(
                connection.card.auth_schemes_offered
            )
        return A2ATarget(
            interface_url=interface_url,
            auth_scheme=connection.auth_scheme,
            auth_header_name=auth_header_name or connection.auth_header_name,
            credential=self._open_credential(connection) if authenticated else "",
            guarantee_tier=(
                "guaranteed"
                if (guarantee_tier or connection.guarantee_tier) == "guaranteed"
                else "best_effort"
            ),
        )

    def _open_credential(self, connection: AgentConnectionDocument) -> str:
        if connection.credential is None:
            raise ValidationFailure(
                "This connection has no stored credential. Reconnect the agent.",
                detail={"reason": "credential_missing"},
            )
        try:
            return self.secret_box.open(
                connection.credential,
                aad=secret_aad(
                    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                    owner_id=connection.owner_id,
                    connection_id=connection.id,
                ),
            )
        except SecretDecryptionFailed as exc:
            # Fail closed: never fall back to sending an empty or partial header.
            raise ValidationFailure(
                "This connection's stored credential can no longer be read. "
                "Rotate the credential to continue.",
                detail={"reason": "credential_unreadable"},
            ) from exc

    # --- connection projection ---------------------------------------------

    def _is_stale(self, connection: AgentConnectionDocument) -> bool:
        if connection.status != "ready" or connection.last_contact_at is None:
            return False
        return self._now() >= connection.last_contact_at + self.stale_after

    def _ready_for_handoff(self, connection: AgentConnectionDocument) -> bool:
        return connection.status == "ready" and not self._is_stale(connection)

    def _connection_response(
        self, connection: AgentConnectionDocument
    ) -> AgentConnectionResponse:
        return AgentConnectionResponse(
            id=connection.id,
            name=connection.name,
            agent_address=connection.endpoint_url,
            auth_scheme=connection.auth_scheme,
            auth_header_name=connection.auth_header_name,
            status=connection.status,
            stale=self._is_stale(connection),
            ready_for_handoff=self._ready_for_handoff(connection),
            capabilities=AgentCapabilitiesResponse(
                **connection.capabilities.model_dump()
            ),
            # BrainBuddy's own statement, never an agent claim: a tested A2A
            # connection is one BrainBuddy will offer both controls on, and the
            # run projection is what withdraws them once an agent has refused.
            controls_offered=AgentControlsResponse(
                reply=connection.status == "ready",
                cancel=connection.status == "ready",
            ),
            card=(
                AgentCardResponse.model_validate(
                    connection.card.model_dump(
                        exclude={"security_required", "security_requirements"}
                    )
                )
                if connection.card is not None
                else None
            ),
            guarantee_tier=connection.guarantee_tier,
            tier_disclosure=(
                TIER_DISCLOSURES[connection.guarantee_tier]
                if connection.guarantee_tier is not None
                else None
            ),
            tier_disclosure_url=self.tier_disclosure_url,
            cancellation_disclosure=CANCELLATION_DISCLOSURE,
            agent_changed=connection.agent_changed,
            best_effort_acknowledged_at=connection.best_effort_acknowledged_at,
            correlation_id_honoured=connection.context_id_honoured,
            disconnect_reason=connection.disconnect_reason,
            last_test_error_code=connection.last_test_error_code,
            last_test_error_detail=connection.last_test_error_detail,
            last_contact_at=connection.last_contact_at,
            last_tested_at=connection.last_tested_at,
            stale_after_seconds=int(self.stale_after.total_seconds()),
            created_at=connection.created_at,
            revision=connection.revision,
        )

    # --- connections --------------------------------------------------------

    def create_connection(
        self,
        payload: AgentConnectionCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool,
    ) -> AgentConnectionResponse:
        command = "create_connection"
        # No target: this call is what brings the connection into existence.
        canonical = self._canonical_request(command, payload, target=None)
        with self.agent_repo.command_lock(owner_id):
            key_hash, record = self._replayed(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                canonical=canonical,
            )
            if record is not None:
                return self._connection_response(
                    self.agent_repo.get_connection(
                        record.resource_id, owner_id=owner_id
                    )
                )

            if not reauthenticated:
                raise ValidationFailure(
                    "Confirm your password to connect an agent.",
                    detail={"reason": "reauthentication_required"},
                )
            self._validate_endpoint(payload.agent_address)

            now = self._now()
            connection_id = generate_id("agentconn")
            connection = AgentConnectionDocument(
                id=connection_id,
                owner_id=owner_id,
                name=payload.name.strip(),
                # Storage key unchanged from 007 on purpose (data-model.md §1).
                endpoint_url=payload.agent_address,
                auth_scheme=payload.auth_scheme,
                credential=self.secret_box.seal(
                    payload.credential,
                    aad=secret_aad(
                        AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                        owner_id=owner_id,
                        connection_id=connection_id,
                    ),
                ),
                scope_verified_at=now,
                created_at=now,
                updated_at=now,
            )
            self.agent_repo.create_connection(connection)
            self._remember(
                owner_id=owner_id,
                key_hash=key_hash,
                command=command,
                canonical=canonical,
                resource_id=connection_id,
            )
            self._audit(
                owner_id=owner_id,
                action="connection_created",
                outcome="ok",
                connection_id=connection_id,
            )

        # No secret in the 201. Under the A2A wire there is no inbound secret an
        # owner has to configure at their agent, so registration has nothing to
        # show once and everything to lose by showing it (FR-012).
        return self._connection_response(connection)

    def list_connections(self, *, owner_id: str) -> list[AgentConnectionResponse]:
        return [
            self._connection_response(connection)
            for connection in self.agent_repo.list_connections(owner_id=owner_id)
        ]

    def get_connection(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionResponse:
        return self._connection_response(
            self.agent_repo.get_connection(connection_id, owner_id=owner_id)
        )

    def update_connection(
        self,
        connection_id: str,
        payload: AgentConnectionUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool,
    ) -> AgentConnectionResponse:
        """Update only owner-visible identity and destination metadata."""

        command = "update_connection"
        canonical = self._canonical_request(command, payload, target=connection_id)
        with self.agent_repo.command_lock(owner_id):
            key_hash, record = self._replayed(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                canonical=canonical,
            )
            connection = self.agent_repo.get_connection(
                connection_id, owner_id=owner_id
            )
            if record is not None:
                return AgentConnectionResponse.model_validate(record.response_body)
            if connection.status == "disconnected":
                raise _disconnected_refusal(connection, "This agent is disconnected.")
            if connection.revision != payload.expected_revision:
                raise ConflictError(
                    "Agent connection",
                    connection_id,
                    "This agent changed elsewhere; reload and try again.",
                )

            address_changed = (
                payload.agent_address is not None
                and payload.agent_address != connection.endpoint_url
            )
            scheme_changed = (
                payload.auth_scheme is not None
                and payload.auth_scheme != connection.auth_scheme
            )
            # A scheme change is a scope change exactly as an address change is:
            # the same secret is presented differently, so the agent that
            # receives it may not be the one that received it before.
            destination_changed = address_changed or scheme_changed
            name_changed = payload.name is not None and payload.name != connection.name
            if destination_changed:
                if not reauthenticated:
                    raise ValidationFailure(
                        "Confirm your password to change this agent's destination.",
                        detail={"reason": "reauthentication_required"},
                    )
                if address_changed:
                    assert payload.agent_address is not None
                    self._validate_endpoint(payload.agent_address)

            if not name_changed and not destination_changed:
                response = self._connection_response(connection)
                self._remember(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command,
                    canonical=canonical,
                    resource_id=connection_id,
                    response_body=response.model_dump(mode="json"),
                )
                return response

            now = self._now()
            updates: dict[str, Any] = {
                "updated_at": now,
                "revision": connection.revision + 1,
            }
            if name_changed:
                updates["name"] = payload.name
            if destination_changed:
                updates.update(self._scope_reset_updates(now=now))
                if address_changed:
                    updates["endpoint_url"] = payload.agent_address
                if scheme_changed:
                    updates["auth_scheme"] = payload.auth_scheme
            updated = connection.model_copy(update=updates)
            self.agent_repo.save_connection(updated)
            self._remember(
                owner_id=owner_id,
                key_hash=key_hash,
                command=command,
                canonical=canonical,
                resource_id=connection_id,
                response_body=self._connection_response(updated).model_dump(
                    mode="json"
                ),
            )
            self._audit(
                owner_id=owner_id,
                action="connection_updated",
                outcome="destination_changed" if destination_changed else "renamed",
                connection_id=connection_id,
            )
        return self._connection_response(updated)

    # --- discovery and the authenticated probe (FR-002) ---------------------

    def _discovery_failure_updates(self, discovery: CardDiscovery) -> dict[str, Any]:
        """What a card that could not be used records, and nothing more.

        Each failure code is its own sentence to the owner (D-01-S14..S17), so
        the code is stored rather than collapsed into a single "unsupported":
        "there is no card at the well-known location" and "this card requires
        OAuth2" call for entirely different corrective actions.
        """

        code = discovery.failure_code or A2A_UNREACHABLE
        status = (
            "unsupported" if code in _UNSUPPORTED_DISCOVERY_CODES else "unreachable"
        )
        return {
            "status": status,
            "last_test_error_code": code,
            "last_test_error_detail": bounded_test_error_detail(
                discovery.failure_detail
            ),
        }

    def _probe_updates(
        self, connection: AgentConnectionDocument, discovery: CardDiscovery
    ) -> dict[str, Any]:
        """Authenticate against the interface the card just named.

        A card read proves an agent exists; it does not prove BrainBuddy may
        talk to it. ``ListTasks`` is the cheapest authenticated call that carries
        no content, and the ``GetTask`` sentinel behind it exists because an
        agent may legitimately not implement listing at all.
        """

        assert discovery.summary is not None
        assert discovery.interface_url is not None
        client = self.a2a_client
        if client is None:  # pragma: no cover - the container always wires one
            raise ValidationFailure(
                "BrainBuddy cannot test connections right now. Try again shortly.",
                detail={"reason": "a2a_unreachable"},
            )
        target = self._a2a_target(
            connection,
            interface_url=discovery.interface_url,
            auth_header_name=discovery.auth_header_name,
            guarantee_tier=discovery.guarantee_tier,
            authenticated=discovery.authenticated,
        )
        result = client.list_tasks(target, page_size=1)
        if result.error_code == A2A_METHOD_NOT_FOUND:
            result = client.get_task(target, task_id=PROBE_TASK_ID)
            if result.error_code == A2A_TASK_NOT_FOUND:
                # The credential was accepted; only the sentinel is missing,
                # which is the answer that proves the agent is reachable and
                # authenticated without it having to own a real task.
                result = A2AResult(ok=True, correlation_id=result.correlation_id)
        return self._probe_outcome_updates(result)

    @staticmethod
    def _probe_outcome_updates(result: A2AResult) -> dict[str, Any]:
        if result.ok:
            return {"status": "ready"}
        if result.error_code in _CREDENTIALS_REJECTED:
            return {
                "status": "invalid_credentials",
                "last_test_error_code": A2A_CREDENTIALS_REJECTED,
            }
        if result.error_code == A2A_RATE_LIMITED:
            # A refusal to answer is not a verdict on the connection: the probe
            # learned nothing, so the connection stays *untested* rather than
            # inheriting a failure it did not earn (AC-037, D-01-S25).
            return {
                "status": "untested",
                "last_test_error_code": A2A_RATE_LIMITED,
                "last_test_error_detail": {
                    "retry_after_seconds": result.retry_after_seconds
                },
            }
        return {"status": "unreachable", "last_test_error_code": A2A_UNREACHABLE}

    def _drift_updates(
        self, connection: AgentConnectionDocument, discovery: CardDiscovery
    ) -> dict[str, Any] | None:
        """The **Agent changed** transition, or nothing (AC-012, D-01-S20).

        The stored card is deliberately *not* replaced here: it describes the
        destination the owner actually tested, and the surface shows it beside
        the one the card now advertises. Overwriting it would erase the very
        comparison that makes the warning actionable.
        """

        if connection.card_fingerprint is None:
            return None
        if discovery.card_fingerprint == connection.card_fingerprint:
            return None
        if connection.card_drift_at is not None:
            # Announced once. The owner has seen **Agent changed** and has come
            # back to test again, which is exactly the deliberate act the
            # warning asks for — repeating the refusal would leave no way out of
            # it short of deleting the connection.
            return None
        return {
            "status": "untested",
            "last_test_error_code": AGENT_CARD_CHANGED,
            "last_test_error_detail": bounded_test_error_detail(
                {"interface_url": discovery.interface_url}
            ),
            "card_drift_at": self._now(),
            # Not an owner action, so there is no fresh proof of possession to
            # keep: the next content-bearing send has to ask for the password
            # again, and the duplicate-risk acknowledgement is asked again too.
            "scope_verified_at": None,
            "best_effort_acknowledged_at": None,
        }

    def _successful_test_updates(
        self, discovery: CardDiscovery, *, now: datetime
    ) -> dict[str, Any]:
        summary = discovery.summary
        assert summary is not None
        return {
            "status": "ready",
            "card": summary,
            "card_fingerprint": discovery.card_fingerprint,
            "card_drift_at": None,
            "guarantee_tier": discovery.guarantee_tier,
            "auth_header_name": discovery.auth_header_name,
            "capabilities": AgentCapabilities(
                streaming=summary.streaming,
                push_notifications=summary.push_notifications,
            ),
            "last_test_error_code": None,
            "last_test_error_detail": None,
            # Only an authenticated success is contact; a rejection is not.
            "last_contact_at": now,
        }

    def _test_outcome_updates(
        self, connection: AgentConnectionDocument, *, now: datetime
    ) -> dict[str, Any]:
        """One test, as the fields it changes. No I/O happens under a lock."""

        discovery = self._card_fetcher(
            connection.endpoint_url, auth_scheme=connection.auth_scheme, now=now
        )
        if not discovery.ok:
            return self._discovery_failure_updates(discovery)

        if connection.auth_scheme == "api_key" and (
            usable_auth_header_name(discovery.auth_header_name) is None
        ):
            # Discovery normally refuses this itself; repeating the check here
            # means a card can never reach the request builder with a header
            # name the transport owns, whatever path produced the discovery.
            return {
                "status": "unsupported",
                "last_test_error_code": A2A_AUTH_SCHEME_UNSUPPORTED,
                "last_test_error_detail": bounded_test_error_detail(
                    {"scheme": discovery.auth_header_name or connection.auth_scheme}
                ),
            }

        drifted = self._drift_updates(connection, discovery)
        if drifted is not None:
            return drifted

        probe = self._probe_updates(connection, discovery)
        if probe["status"] != "ready":
            return probe
        return self._successful_test_updates(discovery, now=now)

    @staticmethod
    def _scope_reset_updates(*, now: datetime) -> dict[str, Any]:
        """Everything a new destination, scheme or credential invalidates.

        Stated once because the three call sites must reset the *same* set: an
        address change that forgot to clear the card fingerprint would leave a
        connection claiming it had tested a destination it never saw. The
        duplicate-risk acknowledgement goes with them (AC-026) — it was given
        about a specific agent, and this is no longer certainly that agent.
        """

        return {
            "status": "untested",
            "capabilities": AgentCapabilities(),
            "card": None,
            "card_fingerprint": None,
            "card_drift_at": None,
            "guarantee_tier": None,
            "auth_header_name": None,
            "best_effort_acknowledged_at": None,
            "context_id_honoured": None,
            "last_test_error_code": None,
            "last_test_error_detail": None,
            "last_contact_at": None,
            "last_tested_at": None,
            # The owner just proved possession for *this* scope, and no content
            # has moved under it yet, so the first-dispatch trigger re-arms.
            "scope_verified_at": now,
            "first_dispatch_at": None,
        }

    def test_connection(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionResponse:
        """Discover the agent from its card, then prove we may talk to it."""

        connection = self.agent_repo.get_connection(connection_id, owner_id=owner_id)
        if connection.status == "disconnected":
            raise _disconnected_refusal(
                connection, "This agent is disconnected. Connect it again to test it."
            )
        # Before any request leaves: a refused network class must not be able to
        # collect even the credential-free card fetch.
        self._validate_endpoint(connection.endpoint_url)

        now = self._now()
        updates = self._test_outcome_updates(connection, now=now)

        with self.agent_repo.command_lock(owner_id):
            current = self.agent_repo.get_connection(connection_id, owner_id=owner_id)
            # Discovery and the probe intentionally happen without the owner
            # lock. Merge the test-only fields only if the exact
            # destination/credential snapshot tested is still current; any
            # intervening command wins.
            if current.revision != connection.revision:
                return self._connection_response(current)
            if current.status == "disconnected":
                return self._connection_response(current)
            updated = current.model_copy(
                update={
                    "last_test_error_code": None,
                    "last_test_error_detail": None,
                    **updates,
                    "last_tested_at": now,
                    "updated_at": now,
                    "revision": current.revision + 1,
                }
            )
            self.agent_repo.save_connection(updated)
            self._audit(
                owner_id=owner_id,
                action="card_fetched",
                outcome=updated.last_test_error_code or "ok",
                connection_id=connection_id,
            )
            if updated.agent_changed:
                self._audit(
                    owner_id=owner_id,
                    action="card_drift_detected",
                    outcome="agent_card_changed",
                    connection_id=connection_id,
                )
            self._audit(
                owner_id=owner_id,
                action="connection_tested",
                outcome=updated.status,
                connection_id=connection_id,
            )
        return self._connection_response(updated)

    def rotate_credential(
        self,
        connection_id: str,
        payload: AgentConnectionRotateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool,
    ) -> AgentConnectionResponse:
        command = "rotate_credential"
        canonical = self._canonical_request(command, payload, target=connection_id)
        with self.agent_repo.command_lock(owner_id):
            key_hash, record = self._replayed(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                canonical=canonical,
            )
            connection = self.agent_repo.get_connection(
                connection_id, owner_id=owner_id
            )
            if record is not None:
                return self._connection_response(connection)
            if not reauthenticated:
                raise ValidationFailure(
                    "Confirm your password to replace this agent's credential.",
                    detail={"reason": "reauthentication_required"},
                )
            if connection.status == "disconnected":
                raise _disconnected_refusal(connection, "This agent is disconnected.")
            if connection.revision != payload.expected_revision:
                raise ConflictError(
                    "Agent connection",
                    connection_id,
                    "This agent changed elsewhere; reload and try again.",
                )

            now = self._now()
            updated = connection.model_copy(
                update={
                    "credential": self.secret_box.seal(
                        payload.credential,
                        aad=secret_aad(
                            AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                            owner_id=owner_id,
                            connection_id=connection_id,
                        ),
                    ),
                    # A new credential is a new scope: readiness, the discovery
                    # result and the first-dispatch re-auth trigger all reset.
                    **self._scope_reset_updates(now=now),
                    "updated_at": now,
                    "revision": connection.revision + 1,
                }
            )
            self.agent_repo.save_connection(updated)
            self._remember(
                owner_id=owner_id,
                key_hash=key_hash,
                command=command,
                canonical=canonical,
                resource_id=connection_id,
            )
            self._audit(
                owner_id=owner_id,
                action="credential_rotated",
                outcome="ok",
                connection_id=connection_id,
            )
        return self._connection_response(updated)

    def disconnect_connection(
        self,
        connection_id: str,
        payload: AgentConnectionDisconnectRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool,
    ) -> AgentConnectionResponse:
        """Destroy the credential and stop the connection, keeping history."""

        command = "disconnect_connection"
        canonical = self._canonical_request(command, payload, target=connection_id)
        with self.agent_repo.command_lock(owner_id):
            key_hash, record = self._replayed(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                canonical=canonical,
            )
            connection = self.agent_repo.get_connection(
                connection_id, owner_id=owner_id
            )
            if record is not None:
                return self._connection_response(connection)
            if not reauthenticated:
                raise ValidationFailure(
                    "Confirm your password to disconnect this agent.",
                    detail={"reason": "reauthentication_required"},
                )
            if connection.revision != payload.expected_revision:
                raise ConflictError(
                    "Agent connection",
                    connection_id,
                    "This agent changed elsewhere; reload and try again.",
                )

            now = self._now()
            updated = connection.model_copy(
                update={
                    # The credential goes: a disconnected connection must not
                    # be able to reach the agent again (FR-016).
                    "credential": None,
                    "status": "disconnected",
                    "capabilities": AgentCapabilities(),
                    # The discovered card goes with the credential: it is
                    # connection configuration, and a disconnected connection
                    # that still described where it pointed would outlive the
                    # decision to stop pointing there (FR-016, AC-024).
                    "card": None,
                    "card_fingerprint": None,
                    "card_drift_at": None,
                    "guarantee_tier": None,
                    "auth_header_name": None,
                    "best_effort_acknowledged_at": None,
                    "disconnected_at": now,
                    # Deliberate, and distinguishable from the wire migration's
                    # `superseded_wire_contract`: the two read very differently
                    # to whoever finds a dead connection (D-01-S21).
                    "disconnect_reason": "owner",
                    "updated_at": now,
                    "revision": connection.revision + 1,
                }
            )
            self.agent_repo.save_connection(updated)

            for run in self.agent_repo.list_runs_for_owner(owner_id=owner_id):
                if run.connection_id != connection_id or run.dispatched_at is None:
                    continue
                if run.reported_state in TERMINAL_REPORTED_STATES:
                    continue
                self.agent_repo.save_run(
                    run.model_copy(
                        update={
                            "connection_disconnected_at": now,
                            # Nothing left to observe or register with: the
                            # credential this run's schedule depended on has
                            # just been destroyed (AC-022).
                            "next_observation_at": None,
                            "observation_trigger_pending": None,
                            "updated_at": now,
                            "revision": run.revision + 1,
                        }
                    )
                )
                if self.evict_push_limiter is not None:
                    # A run that can never be pushed for again has no use for a
                    # limiter bucket, and keeping one is pure retention.
                    self.evict_push_limiter(run.id)
            self._remember(
                owner_id=owner_id,
                key_hash=key_hash,
                command=command,
                canonical=canonical,
                resource_id=connection_id,
            )
            self._audit(
                owner_id=owner_id,
                action="connection_disconnected",
                outcome="ok",
                connection_id=connection_id,
            )
        return self._connection_response(updated)

    # --- hand-off -----------------------------------------------------------

    def _require_dispatchable(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionDocument:
        connection = self.agent_repo.get_connection(connection_id, owner_id=owner_id)
        if connection.status == "disconnected":
            raise _disconnected_refusal(
                connection,
                "This agent is disconnected. Connect it again before handing "
                "work to it.",
            )
        if connection.agent_changed:
            # Its own reason, not a generic "not ready": the corrective action
            # differs — this one asks the owner to look at *where* their content
            # would now go before agreeing to send it again (D-01-S20, AC-012).
            raise ValidationFailure(
                "This agent's card now advertises a different destination than "
                "the one you tested. Test the connection again before handing "
                "work to it.",
                detail={"reason": AGENT_CARD_CHANGED},
            )
        if connection.status != "ready":
            reason = (
                connection.last_test_error_code
                if connection.last_test_error_code in _DISPATCH_REFUSAL_REASONS
                else "connection_not_ready"
            )
            raise ValidationFailure(
                "Test this connection successfully before handing work to it.",
                detail={"reason": reason, "status": connection.status},
            )
        if self._is_stale(connection):
            raise ValidationFailure(
                "This connection has not been in contact recently. Test it "
                "again before handing work to it.",
                detail={"reason": "connection_stale"},
            )
        return connection

    def requires_dispatch_reauthentication(
        self, connection: AgentConnectionDocument
    ) -> bool:
        """Whether FR-003's first-content-in-a-new-scope trigger applies.

        Once content has already been sent under this destination/credential
        scope the trigger is spent; until then, the owner's proof of possession
        has to be recent.
        """

        if connection.first_dispatch_at is not None:
            return False
        if connection.scope_verified_at is None:
            return True
        return self._now() >= connection.scope_verified_at + SCOPE_REAUTH_WINDOW

    def push_callback_url(self, run_id: str, token: str) -> str:
        """The private per-run callback address given to the agent."""

        return f"{self.push_base_url.rstrip('/')}/{run_id}/{token}"

    @staticmethod
    def _masked_push_url(url: str) -> str:
        """The callback address as the *review* shows it: token elided.

        The manifest is re-read on every run projection, so an unmasked address
        here would put the token into every response, log line and audit row
        that ever touches the run (AC-007, push-callback.md Redaction).
        """

        head, _, _token = url.rpartition("/")
        return f"{head}/…"

    def _push_callback_for(
        self, connection: AgentConnectionDocument, *, run_id: str, token: str
    ) -> AgentPushCallback:
        if not (connection.card and connection.card.push_notifications):
            # Nothing to disclose. A masked address for a callback the agent
            # cannot use would read as one it can.
            return AgentPushCallback(registered=False)
        return AgentPushCallback(
            registered=True,
            url_preview=self._masked_push_url(self.push_callback_url(run_id, token)),
            disclosure=PUSH_CALLBACK_DISCLOSURE,
        )

    def acknowledgement_required(self, connection: AgentConnectionDocument) -> bool:
        """Whether this hand-off must carry the duplicate-risk acknowledgement.

        Asked once per connection, and again whenever its verified scope resets
        (AC-026). A guaranteed-tier agent is never asked: its card promises the
        deduplication the acknowledgement exists to warn about.
        """

        return (
            connection.guarantee_tier == "best_effort"
            and connection.best_effort_acknowledged_at is None
        )

    @staticmethod
    def _parts_preview(manifest: AgentRunManifest) -> list[str]:
        """The exact text of each part that will be sent, in order.

        The review claims to show what leaves. This is that claim made
        checkable: it is built from the same manifest the wire message is built
        from, so the two cannot drift.
        """

        parts = [manifest.title]
        if manifest.details:
            parts.append(manifest.details)
        parts.extend(f"{item.label}\n{item.body}" for item in manifest.context_items)
        return parts

    def _build_manifest(
        self,
        *,
        run_id: str,
        task: TaskSnapshot,
        connection: AgentConnectionDocument,
        payload: AgentHandoffPreviewRequest,
        push_token: str | None = None,
    ) -> AgentRunManifest:
        if len(payload.supporting_items) > MAX_CONTEXT_ITEMS:
            raise ValidationFailure(
                f"A hand-off may include at most {MAX_CONTEXT_ITEMS} supporting items.",
                detail={"reason": "too_many_supporting_items"},
            )
        context_items = [
            AgentManifestContextItem(label=item.label, body=item.body)
            for item in payload.supporting_items
        ]
        details = task.details if payload.include_details else None
        tier = connection.guarantee_tier or "best_effort"
        interface = (connection.card.interface_url if connection.card else None) or (
            connection.endpoint_url
        )
        push_callback = self._push_callback_for(
            connection, run_id=run_id, token=push_token or ""
        )
        # Inert, and written only so a rolled-back 007 image can still parse the
        # row (plan.md, Rollback boundary). Nothing in this build reads it.
        reporting = inert_reporting_contract(connection.id)
        content = {
            "run_id": run_id,
            "task_id": task.id,
            "connection_id": connection.id,
            # The *interface*, not the address the owner typed: a card that
            # moves changes where content would go, and the token has to
            # invalidate when it does (AC-012).
            "destination": interface,
            "agent_name": connection.name,
            "title": task.title,
            "details": details,
            "context_items": [item.model_dump() for item in context_items],
            "message_id": f"{run_id}:start",
            "correlation_id": run_id,
            "guarantee_tier": tier,
            "acknowledgement_required": self.acknowledgement_required(connection),
            # The callback *origin* is part of the token: a deployment that
            # moved would otherwise let a stale confirmation hand the agent an
            # address BrainBuddy no longer answers on.
            "push_callback_registered": push_callback.registered,
            "push_callback_origin": self.push_base_url,
            "protocol_version": A2A_PROTOCOL_VERSION,
        }
        token = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return AgentRunManifest(
            token=token,
            run_id=run_id,
            task_id=task.id,
            connection_id=connection.id,
            agent_name=connection.name,
            title=task.title,
            details=details,
            context_items=context_items,
            reporting=reporting,
            message_id=f"{run_id}:start",
            correlation_id=run_id,
            destination_interface=interface,
            guarantee_tier=tier,
            tier_disclosure=TIER_DISCLOSURES[tier],
            tier_disclosure_url=self.tier_disclosure_url,
            cancellation_disclosure=CANCELLATION_DISCLOSURE,
            acknowledgement_required=self.acknowledgement_required(connection),
            push_callback=push_callback,
        )

    def _manifest_response(
        self, manifest: AgentRunManifest, connection: AgentConnectionDocument
    ) -> AgentManifestResponse:
        return AgentManifestResponse(
            token=manifest.token,
            run_id=manifest.run_id,
            task_id=manifest.task_id,
            connection_id=manifest.connection_id,
            agent_name=manifest.agent_name,
            title=manifest.title,
            details=manifest.details,
            supporting_items=[
                AgentContextItemResponse(label=item.label, body=item.body)
                for item in manifest.context_items
            ],
            message_id=manifest.message_id,
            correlation_id=manifest.correlation_id,
            destination_interface=manifest.destination_interface,
            protocol_version=manifest.protocol_version,
            guarantee_tier=manifest.guarantee_tier,
            tier_disclosure=manifest.tier_disclosure,
            tier_disclosure_url=manifest.tier_disclosure_url,
            acknowledgement_required=manifest.acknowledgement_required,
            cancellation_disclosure=manifest.cancellation_disclosure,
            push_callback=AgentPushCallbackResponse(
                **manifest.push_callback.model_dump()
            ),
            external_copy_notice=EXTERNAL_COPY_NOTICE,
            reauthentication_required=self.requires_dispatch_reauthentication(
                connection
            ),
            parts_preview=self._parts_preview(manifest),
        )

    def _refuse_a_destination_that_moved(
        self, connection: AgentConnectionDocument, *, owner_id: str
    ) -> None:
        """Re-read the card at the review, and refuse a card that has moved.

        The review is the last moment before content leaves, so the destination
        it names is checked again here rather than trusted from the last test.
        A drift found now marks the connection **Agent changed** — the same
        transition a test would make — so every surface stops offering it, not
        just this one review (AC-012, D-02-S09).

        A refetch that *fails* is not evidence of drift and does not refuse: the
        tested-and-not-stale rule already carries that risk, and turning every
        transient card-fetch blip into a blocked hand-off would trade a real
        safety property for an imagined one.
        """

        if connection.card_fingerprint is None:
            return
        now = self._now()
        discovery = self._card_fetcher(
            connection.endpoint_url, auth_scheme=connection.auth_scheme, now=now
        )
        if (
            not discovery.ok
            or discovery.card_fingerprint == connection.card_fingerprint
        ):
            return
        updates = self._drift_updates(connection, discovery)
        with self.agent_repo.command_lock(owner_id):
            current = self.agent_repo.get_connection(connection.id, owner_id=owner_id)
            if updates is not None and current.revision == connection.revision:
                self.agent_repo.save_connection(
                    current.model_copy(
                        update={
                            **updates,
                            "updated_at": now,
                            "revision": current.revision + 1,
                        }
                    )
                )
                self._audit(
                    owner_id=owner_id,
                    action="card_drift_detected",
                    outcome=AGENT_CARD_CHANGED,
                    connection_id=connection.id,
                )
        raise ValidationFailure(
            "This agent's card now advertises a different destination than the "
            "one you tested. Test the connection again before handing work to it.",
            detail={"reason": AGENT_CARD_CHANGED},
        )

    def preview_handoff(
        self,
        task_id: str,
        payload: AgentHandoffPreviewRequest,
        *,
        owner_id: str,
    ) -> AgentManifestResponse:
        """Show exactly what would be sent, and reserve the run ID it names."""

        connection = self._require_dispatchable(
            payload.connection_id, owner_id=owner_id
        )
        self._refuse_a_destination_that_moved(connection, owner_id=owner_id)
        task = self.task_snapshot(task_id, owner_id=owner_id)

        now = self._now()
        run_id = generate_id("agentrun")
        manifest = self._build_manifest(
            run_id=run_id, task=task, connection=connection, payload=payload
        )
        # Durably reserve the run ID and its idempotency key before any dispatch
        # can happen (FR-006). Until confirmation this reservation is invisible
        # on every Task surface, so reviewing and walking away creates no run.
        self.agent_repo.create_run(
            AgentRunDocument(
                id=run_id,
                owner_id=owner_id,
                connection_id=connection.id,
                task_id=task.id,
                agent_name=connection.name,
                manifest=manifest,
                content_expires_at=now + self.content_retention,
                created_at=now,
                updated_at=now,
            )
        )
        return self._manifest_response(manifest, connection)

    def dispatch_run(
        self,
        task_id: str,
        payload: AgentHandoffConfirmRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool = False,
    ) -> AgentRunResponse:
        """Send exactly the reviewed manifest, exactly once."""

        command = "dispatch_run"
        # The task is the path target and appears nowhere in the body, so
        # without it a key spent handing off one task would replay as a
        # success for another.
        canonical = self._canonical_request(command, payload, target=task_id)
        operation_fingerprint = self._key_fingerprint(owner_id, idempotency_key)
        with self.agent_repo.operation_lock(owner_id, operation_fingerprint):
            with self.agent_repo.command_lock(owner_id):
                key_hash, record = self._replayed(
                    owner_id=owner_id,
                    key=idempotency_key,
                    command=command,
                    canonical=canonical,
                )
                if record is not None and record.completed:
                    return self._run_response(
                        self.agent_repo.get_run(record.resource_id, owner_id=owner_id)
                    )
                reconciled = self._reconcile_attempted_command(
                    record, owner_id=owner_id, canonical=canonical, kind="start"
                )
                if reconciled is not None:
                    return reconciled

                connection = self._require_dispatchable(
                    payload.connection_id, owner_id=owner_id
                )
                if record is None:
                    task = self.task_snapshot(task_id, owner_id=owner_id)
                    reserved = self.agent_repo.find_run_by_manifest_token(
                        payload.manifest_token, owner_id=owner_id
                    )
                    if reserved is None or reserved.dispatched_at is not None:
                        raise ValidationFailure(
                            "This hand-off review is no longer valid. Review what will "
                            "be sent and confirm again.",
                            detail={"reason": "manifest_not_reserved"},
                        )
                    manifest = self._build_manifest(
                        run_id=reserved.id,
                        task=task,
                        connection=connection,
                        payload=payload,
                    )
                    if not hmac.compare_digest(manifest.token, payload.manifest_token):
                        raise ValidationFailure(
                            "What would be sent has changed since you reviewed it. "
                            "Review it again before confirming.",
                            detail={"reason": "manifest_token_mismatch"},
                        )
                    if self.acknowledgement_required(connection) and not (
                        payload.acknowledge_duplicate_risk
                    ):
                        # Before the reservation is consumed and before any I/O:
                        # the acknowledgement is the thing being consented to, so
                        # a confirmation that lacks it is not a confirmation at
                        # all (AC-026). It is checked after the token, because a
                        # review that has gone stale is a different problem and
                        # saying "acknowledge this" about content the user can no
                        # longer see would be the wrong instruction.
                        raise ValidationFailure(
                            "Acknowledge that this agent may create a duplicate "
                            "task before sending to it for the first time.",
                            detail={
                                "reason": "duplicate_risk_acknowledgement_required"
                            },
                        )
                    if self.requires_dispatch_reauthentication(connection) and not (
                        reauthenticated
                    ):
                        raise ValidationFailure(
                            "Confirm your password before sending task content to this "
                            "agent for the first time.",
                            detail={"reason": "reauthentication_required"},
                        )
                else:
                    reserved = self.agent_repo.get_run(
                        record.resource_id, owner_id=owner_id
                    )
                    stored_manifest = reserved.manifest
                    if stored_manifest is None:
                        raise ValidationFailure(
                            "This hand-off's retained content has expired.",
                            detail={"reason": "run_content_expired"},
                        )
                    manifest = stored_manifest
                if (
                    manifest.connection_id != connection.id
                    or manifest.task_id != task_id
                ):
                    raise ConflictError("Agent run", reserved.id)

                now = record.created_at if record is not None else self._now()
                command_id, reserved_at = self._reserve_command(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command,
                    canonical=canonical,
                    resource_id=reserved.id,
                    record=record,
                    now=now,
                )
                if reserved.dispatched_at is None:
                    reserved = reserved.model_copy(
                        update={
                            "manifest": manifest,
                            "dispatched_at": now,
                            # Durable before any I/O and honestly ambiguous from
                            # this moment on. What keeps it from *reading* as an
                            # ambiguous delivery is `exchange_state`: while the
                            # exchange is queued the run projects as **Queued**,
                            # because nothing has left BrainBuddy yet (FR-006).
                            "dispatch_state": "delivery_unconfirmed",
                            "dispatch_error_code": None,
                            "content_expires_at": now + self.content_retention,
                            # The conversation *is* the run, so the correlation
                            # ID needs no second identifier to go wrong.
                            "context_id": reserved.id,
                            "message_id": f"{reserved.id}:start",
                            # Pinned: a card that moves mid-run must not be able
                            # to redirect this run's traffic, and the resend
                            # rules compare against what was pinned here.
                            "interface_url": manifest.destination_interface,
                            "card_fingerprint": connection.card_fingerprint,
                            "guarantee_tier": connection.guarantee_tier
                            or "best_effort",
                            "exchange_state": "queued",
                            "exchange_kind": "start",
                            "updated_at": now,
                            "revision": reserved.revision + 1,
                        }
                    )
                    self.agent_repo.save_run(reserved)
                    self.agent_repo.save_command(
                        AgentRunCommandDocument(
                            id=command_id,
                            owner_id=owner_id,
                            run_id=reserved.id,
                            kind="start",
                            created_at=reserved_at,
                        )
                    )
                    self._audit(
                        owner_id=owner_id,
                        action="run_dispatched",
                        outcome="queued",
                        connection_id=connection.id,
                        run_id=reserved.id,
                    )
                    if payload.acknowledge_duplicate_risk:
                        # Under the same lock as the reservation, and conditional
                        # on the stamp still being absent, so the *first*
                        # acknowledgement is the one recorded. Once it exists the
                        # flag is inert: a client that stopped sending it must
                        # not be able to withdraw a decision the owner made.
                        #
                        # It is a targeted row update rather than a field on the
                        # document above, and it runs last, because the document
                        # in hand was read before it and writing that stale copy
                        # afterwards would erase the stamp it just made.
                        self.agent_repo.acknowledge_duplicate_risk(
                            connection.id, owner_id=owner_id, at=now
                        )
                        connection = self.agent_repo.get_connection(
                            connection.id, owner_id=owner_id
                        )
                self._begin_delivery_attempt(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command,
                    canonical=canonical,
                    resource_id=reserved.id,
                    command_id=command_id,
                    created_at=reserved_at,
                    request_hash=record.request_hash if record is not None else None,
                )

            # Outside the command lock: the exchange takes it for its own writes,
            # and a send that an agent may hold open for the whole reply window
            # must never be holding a process-wide lock while it does.
            future = self._submit_exchange(owner_id=owner_id, run_id=reserved.id)
            self._await_exchange(future)
            current = self.agent_repo.get_run(reserved.id, owner_id=owner_id)
            if current.exchange_state == "open":
                # A worker still holds the send. Ask the agent once whether the
                # task already exists, so the answer can be **Sent** rather than
                # an honest but useless silence. Never while queued: nothing has
                # left, so there is nothing to find.
                current = self._probe_open_exchange(current, connection)
            if current.exchange_state != "open":
                with self.agent_repo.command_lock(owner_id):
                    self.agent_repo.save_command(
                        AgentRunCommandDocument(
                            id=command_id,
                            owner_id=owner_id,
                            run_id=current.id,
                            kind="start",
                            delivery=(
                                "confirmed"
                                if current.dispatch_state == "sent"
                                else "unconfirmed"
                            ),
                            created_at=reserved_at,
                            confirmed_at=(
                                current.last_contact_at
                                if current.dispatch_state == "sent"
                                else None
                            ),
                        )
                    )
                    self._remember(
                        owner_id=owner_id,
                        key_hash=key_hash,
                        command=command,
                        canonical=canonical,
                        resource_id=current.id,
                        command_id=command_id,
                        delivery_attempted=True,
                        created_at=reserved_at,
                    )
            return self._run_response(current)

    def _await_exchange(self, future: Future[Any] | None) -> None:
        """Give the exchange `dispatch_wait_seconds` to finish, then answer.

        The wait is a courtesy, not a contract: whatever it does or does not
        settle, the response afterwards describes only what actually happened.
        """

        if future is None or self.dispatch_wait_seconds <= 0:
            return
        try:
            future.result(timeout=self.dispatch_wait_seconds)
        except FuturesTimeoutError:
            return
        except Exception:  # pragma: no cover - the worker records its own failure
            return

    # --- the A2A exchange ---------------------------------------------------

    def _push_capable(self, connection: AgentConnectionDocument) -> bool:
        return bool(connection.card and connection.card.push_notifications)

    def _start_message(self, run: AgentRunDocument) -> dict[str, Any]:
        """The one content-bearing message, exactly as the review showed it.

        Built from the run's *frozen* manifest rather than from the Task, so
        editing or completing the Task after a dispatch can never rewrite what
        was already sent (007 FR-012).
        """

        manifest = run.manifest
        assert manifest is not None  # guarded by the caller
        return {
            "messageId": run.message_id,
            "contextId": run.context_id,
            "role": "ROLE_USER",
            "parts": [{"text": part} for part in self._parts_preview(manifest)],
            "metadata": {
                "brainbuddy.task_id": run.task_id,
                "brainbuddy.run_id": run.id,
            },
        }

    def _submit_exchange(self, *, owner_id: str, run_id: str) -> Future[Any] | None:
        """Hand one queued exchange to whoever runs exchanges here.

        The pump is the observer, which owns the per-connection bound; without
        one the service falls back to its own executor, and with neither the
        exchange simply stays **Queued** — which is a true statement about it,
        so there is nothing to invent.
        """

        if self.exchange_pump is not None:
            return self.exchange_pump(owner_id, run_id)
        if self.exchange_executor is None:
            return None
        return self.exchange_executor.submit(
            self.perform_exchange, run_id, owner_id=owner_id
        )

    def perform_exchange(self, run_id: str, *, owner_id: str) -> None:
        """Start one queued exchange, send its message, and settle it.

        The send is held open by the agent for up to the reply window, so it
        happens on an exchange worker and outside every lock: holding the
        process-wide command lock across it would stop every other owner's
        commands for as long as one agent felt like thinking.
        """

        run = self.agent_repo.get_run(run_id, owner_id=owner_id)
        if run.exchange_state != "queued" or run.manifest is None:
            return
        wire = self.a2a_client
        if wire is None:
            # No wire configured here, so nothing can leave. The exchange stays
            # **Queued**, which is exactly what has happened to it: leaving it
            # open, or closing it as unconfirmed, would both claim a send.
            return
        connection = self.agent_repo.get_connection(
            run.connection_id, owner_id=owner_id
        )
        now = self._now()
        # Minted here rather than at reservation: a queued exchange holds no
        # plaintext secret, and the manifest token commits only to the callback
        # *origin*, so the token itself is free to be created at the moment it
        # is about to leave.
        push_token = (
            derive_push_token(self.secret_box, run.id)
            if self._push_capable(connection)
            else None
        )
        prepared = run.model_copy(
            update={
                "push_token_fingerprint": (
                    push_token_fingerprint(self.secret_box, push_token)
                    if push_token is not None
                    else None
                )
            }
        )
        with self.agent_repo.command_lock(owner_id):
            opened = self.agent_repo.start_exchange(
                prepared,
                expected_version=run.run_version,
                started_at=now,
                deadline_at=now + self.reply_window,
            )
        if opened is None:
            # A replayed confirmation, a second worker or restart recovery won
            # the start. Exactly one of us may send.
            return

        result = wire.send_message(
            self._a2a_target(
                connection,
                interface_url=opened.interface_url or connection.endpoint_url,
                guarantee_tier=opened.guarantee_tier,
            ),
            message=self._start_message(opened),
            push_config=(
                {
                    "url": self.push_callback_url(opened.id, push_token),
                    "token": push_token,
                }
                if push_token is not None
                else None
            ),
            run_id=opened.id,
        )
        self._close_exchange(
            opened, connection, result, sent_push=push_token is not None
        )

    def _observation_updates(self, observation: Observation) -> dict[str, Any]:
        """One projected answer, as the run fields it may write."""

        updates: dict[str, Any] = {
            "reported_state": observation.reported_state,
            "last_contact_at": observation.observed_at,
            "last_observed_at": observation.observed_at,
        }
        if observation.agent_task_id is not None:
            updates["agent_task_id"] = observation.agent_task_id
        if observation.reported_state is None:
            return updates
        updates["progress_text"] = observation.progress_text
        updates["question_text"] = observation.question_text
        updates["result_text"] = observation.result_text
        updates["result_link"] = observation.result_link
        updates["failure_reason"] = observation.failure_reason
        updates["blocked_reason"] = observation.blocked_reason
        updates["result_availability"] = observation.result_availability
        updates["artifacts_summary"] = [
            AgentArtifactSummary(
                name=artifact.name, media_type=artifact.media_type, kind=artifact.kind
            )
            for artifact in observation.artifacts_summary
        ]
        if observation.terminal:
            updates["cancel_requested_at"] = None
        return updates

    #: The fields an observation may never write back into a run whose content
    #: tier has expired. Retention is irreversible: state, version and contact
    #: still move, but a later answer cannot recreate erased text (SC-007).
    _CONTENT_FIELDS_NEVER_REWRITTEN: tuple[str, ...] = (
        "progress_text",
        "question_text",
        "result_text",
        "result_link",
        "failure_reason",
        "blocked_reason",
        "result_availability",
    )

    def _observation_is_unchanged(
        self, current: AgentRunDocument, observation: Observation
    ) -> bool:
        """Whether this answer says exactly what the run already records.

        The sixty-second schedule means most observations are this one, and an
        unchanged answer must cost a contact timestamp rather than a timeline
        row — otherwise a healthy run accumulates a thousand identical entries
        a day and the user can no longer find the moment anything happened.
        """

        if observation.reported_state is None:
            return True
        if current.reported_state != observation.reported_state:
            return False
        if (
            observation.agent_task_id is not None
            and current.agent_task_id != observation.agent_task_id
        ):
            return False
        if content_is_due(current, now=observation.observed_at):
            # Nothing textual is written on an expired run, so text cannot be
            # what changed: the state comparison above is the whole question.
            return True
        return all(
            getattr(current, field) == value
            for field, value in (
                ("progress_text", observation.progress_text),
                ("question_text", observation.question_text),
                ("result_text", observation.result_text),
                ("result_link", observation.result_link),
                ("failure_reason", observation.failure_reason),
                ("blocked_reason", observation.blocked_reason),
                ("result_availability", observation.result_availability),
            )
        )

    def _observable(self, run: AgentRunDocument) -> bool:
        """Whether an observation may be written to this run at all.

        Four refusals, each of which is a promise: a disconnected run has no
        credential behind it, a run whose identifiers expired has nothing left
        to ask with, an undispatched one was never handed over, and a terminal
        one has already been settled by the agent's own last word.
        """

        return not (
            run.dispatched_at is None
            or run.connection_disconnected_at is not None
            or run.identifiers_expired
        )

    def _event_row(
        self,
        run: AgentRunDocument,
        observation: Observation,
        *,
        trigger: AgentRunEventTrigger,
        summary: str | None,
        kind: AgentRunEventKind = "observation",
        previous_agent_task_id: str | None = None,
        new_agent_task_id: str | None = None,
        content_due: bool = False,
    ) -> AgentRunEventDocument:
        reported = observation.reported_state or run.reported_state
        assert reported is not None  # guarded by every caller
        return AgentRunEventDocument(
            id=generate_id("agentevt"),
            owner_id=run.owner_id,
            run_id=run.id,
            connection_id=run.connection_id,
            type=reported,
            run_version=run.run_version,
            received_at=observation.observed_at,
            summary=None if content_due else summary,
            trigger=trigger,
            agent_state=observation.agent_task_state,
            kind=kind,
            previous_agent_task_id=previous_agent_task_id,
            new_agent_task_id=new_agent_task_id,
        )

    @staticmethod
    def _observation_summary(observation: Observation) -> str | None:
        return (
            observation.progress_text
            or observation.question_text
            or observation.result_text
            or observation.failure_reason
            or observation.blocked_reason
        )

    def apply_observation(
        self,
        run_id: str,
        *,
        owner_id: str,
        observation: Observation | None,
        based_on: int,
        extra: dict[str, Any] | None = None,
        superseded: dict[str, Any] | None = None,
        superseded_unless_terminal: bool = False,
        trigger: AgentRunEventTrigger = "schedule",
    ) -> AgentRunDocument | None:
        """Write one observation, or lose the race and change nothing.

        The compare-and-set on `run_version` is what keeps two answers about the
        same run from interleaving into a state neither of them saw. A terminal
        reported state is never overwritten: an agent that says "completed" and
        then goes quiet has not un-completed anything.

        `superseded` is the narrow exception: the fields still worth writing
        when a *newer* report has already landed. A dispatch uses it to record
        `sent`, because a report arriving during the exchange is itself proof
        the message got there — whatever the transport went on to say about
        itself. Nothing about the agent's state is written on that path; that
        belongs to the report that won.

        Returns ``None`` when the run is gone. A worker that started before an
        account purge finishes after it, and it must write nothing at all —
        not a run, not an event, not an audit row — rather than resurrect what
        the user asked to be erased (FR-016).

        No I/O happens inside the lock — the observation is already projected by
        the time it arrives here.
        """

        with self.agent_repo.command_lock(owner_id):
            try:
                current = self.agent_repo.get_run(run_id, owner_id=owner_id)
            except NotFoundError:
                return None
            if not self._observable(current):
                return current
            if current.run_version != based_on:
                # A newer report landed while this call was at the agent. Two
                # callers want opposite things here, and the difference is real:
                # an exchange still knows its message *arrived*, whatever state
                # the winning report carried, while a cancellation the user
                # asked for is not worth stamping onto a run that has already
                # finished — the overlay would say "cancelling" about work that
                # is over.
                if not superseded or (
                    superseded_unless_terminal
                    and current.reported_state in TERMINAL_REPORTED_STATES
                ):
                    return current
                now = self._now()
                overtaken = current.model_copy(
                    update={
                        **superseded,
                        "updated_at": max(current.updated_at, now),
                        "revision": current.revision + 1,
                    }
                )
                self.agent_repo.save_run(overtaken)
                return overtaken
            now = self._now()
            updates: dict[str, Any] = dict(extra or {})
            terminal_lock = current.reported_state in TERMINAL_REPORTED_STATES
            unchanged = observation is not None and self._observation_is_unchanged(
                current, observation
            )
            rejected = (
                observation is not None
                and terminal_lock
                and not unchanged
                and observation.reported_state is not None
            )
            content_due = content_is_due(current, now=now)
            if observation is not None and not terminal_lock:
                updates = {**self._observation_updates(observation), **updates}
                if content_due:
                    # Retention is irreversible: state and contact still move,
                    # but a late answer can never recreate expired content.
                    updates.update(dict.fromkeys(self._CONTENT_FIELDS_NEVER_REWRITTEN))
                    updates["artifacts_summary"] = []
            elif observation is not None and unchanged:
                # A terminal run that repeats itself is still contact.
                updates.setdefault("last_contact_at", observation.observed_at)
                updates.setdefault("last_observed_at", observation.observed_at)
            reported = updates.get("reported_state")
            append_row = (
                observation is not None and reported is not None and not unchanged
            )
            # `run_version` is BrainBuddy's own observation version, so only an
            # accepted, *differing* observation advances it. Burning a version
            # on an unchanged poll would make a later genuine report look like
            # a straggler and be dropped.
            if append_row:
                updates["run_version"] = current.run_version + 1
            if trigger != "schedule" or current.observation_trigger_pending:
                # The pass that ran is the one that was owed.
                updates.setdefault("observation_trigger_pending", None)
            updates.update(
                updated_at=max(current.updated_at, now),
                revision=current.revision + 1,
            )
            updated = current.model_copy(update=updates)
            if "next_observation_at" not in updates:
                # Every write is also a scheduling decision, made here because
                # this is the one place that sees the run *after* the answer
                # landed: a terminal, missing or disconnected run stops being
                # asked about, and everything else earns its next look.
                updated = updated.model_copy(
                    update={
                        "next_observation_at": self._next_observation_at(
                            updated, now=now
                        )
                    }
                )
            self.agent_repo.save_run(updated)
            if append_row and observation is not None:
                self.agent_repo.append_event(
                    self._event_row(
                        updated,
                        observation,
                        trigger=trigger,
                        summary=self._observation_summary(observation),
                        content_due=content_due,
                    )
                )
                self._bounded_audit(
                    owner_id=owner_id,
                    action="observation_accepted",
                    outcome=str(reported),
                    bucket=f"{updated.id}:{reported}",
                    connection_id=updated.connection_id,
                    run_id=updated.id,
                )
            elif rejected and observation is not None:
                self._bounded_audit(
                    owner_id=owner_id,
                    action="observation_rejected",
                    outcome="terminal_locked",
                    bucket=f"{updated.connection_id}:terminal_locked",
                    connection_id=updated.connection_id,
                    run_id=updated.id,
                )
        return updated

    def record_task_missing(self, run_id: str, *, owner_id: str) -> None:
        """The agent answered that this task does not exist (AC-020).

        Deliberately not a failure: BrainBuddy has lost sight of the work, and
        saying the work failed would be a claim about someone else's system
        that nothing here can support. Last contact is preserved for the same
        reason — the agent did answer.
        """

        with self.agent_repo.command_lock(owner_id):
            try:
                run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            except NotFoundError:
                return
            if run.agent_task_missing_at is not None or not self._observable(run):
                return
            now = self._now()
            self.agent_repo.save_run(
                run.model_copy(
                    update={
                        "agent_task_missing_at": now,
                        # Nothing left to look for, so nothing left to schedule.
                        "next_observation_at": None,
                        "updated_at": max(run.updated_at, now),
                        "revision": run.revision + 1,
                    }
                )
            )
            self._audit(
                owner_id=owner_id,
                action="agent_task_missing",
                outcome="observed",
                connection_id=run.connection_id,
                run_id=run.id,
            )

    # --- the push callback (FR-008, contracts/push-callback.md) -------------

    def verify_push(self, run_id: str, token: str) -> PushOutcome:
        """Decide what one inbound push is, in the order the contract fixes.

        Returns a classification, never a run: the route answers one opaque
        `403` for every refusal, so what it needs from here is which bounded
        audit row to write and whether to wake the observer — not anything a
        caller could read back out of a response.

        The fingerprint is deliberately still present on a closed run, so a
        valid push racing BrainBuddy's own terminal observation — the common
        Hermes case — is classified `push_after_close` rather than reported to
        the owner as a forged token (data-model.md §7, SC-003).
        """

        owner_id = self.agent_repo.owner_of_run(run_id)
        if owner_id is None:
            return PUSH_UNKNOWN
        with self.agent_repo.command_lock(owner_id):
            try:
                run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            except NotFoundError:  # pragma: no cover - purged between the two reads
                return PUSH_UNKNOWN
            if (
                run.dispatched_at is None
                or run.identifiers_expired
                or run.push_token_fingerprint is None
            ):
                # Nothing to compare against, so there is nothing this caller
                # could be right about — and no row worth keeping about them.
                return PUSH_UNKNOWN
            if not push_token_matches(
                self.secret_box, run.push_token_fingerprint, token
            ):
                self._bounded_audit(
                    owner_id=owner_id,
                    action="push_token_rejected",
                    outcome="fingerprint_mismatch",
                    bucket=run.connection_id,
                    connection_id=run.connection_id,
                    run_id=run.id,
                )
                return PushOutcome(owner_id=owner_id, verified=False, closed=False)
            if not self._push_is_still_honoured(run, owner_id=owner_id):
                self._bounded_audit(
                    owner_id=owner_id,
                    action="push_after_close",
                    outcome="run_closed",
                    bucket=run.connection_id,
                    connection_id=run.connection_id,
                    run_id=run.id,
                )
                return PushOutcome(owner_id=owner_id, verified=False, closed=True)
            now = self._now()
            self.agent_repo.save_run(
                run.model_copy(
                    update={
                        "observation_trigger_pending": "push",
                        # A verified push resets the backoff: the agent is
                        # telling BrainBuddy there is something to see.
                        "next_observation_at": min(run.next_observation_at or now, now),
                        "updated_at": max(run.updated_at, now),
                        "revision": run.revision + 1,
                    }
                )
            )
            self._audit(
                owner_id=owner_id,
                action="push_verified",
                outcome="accepted",
                connection_id=run.connection_id,
                run_id=run.id,
            )
        return PushOutcome(owner_id=owner_id, verified=True, closed=False)

    def _push_is_still_honoured(self, run: AgentRunDocument, *, owner_id: str) -> bool:
        """Whether an observation this push asked for could still mean anything."""

        if (
            run.reported_state in TERMINAL_REPORTED_STATES
            or run.agent_task_missing_at is not None
            or run.connection_disconnected_at is not None
        ):
            return False
        try:
            connection = self.agent_repo.get_connection(
                run.connection_id, owner_id=owner_id
            )
        except NotFoundError:  # pragma: no cover - connection rows outlive runs
            return False
        return connection.status != "disconnected"

    # --- the observation lane's service side (FR-008) -----------------------

    def observation_backoff(self, run: AgentRunDocument, *, now: datetime) -> timedelta:
        """How long until this run is worth asking about again.

        Derived from ``last_contact_at`` rather than stored, so there is no
        counter to drift: inside the reporting window it is the base interval,
        and past it the gap doubles per missed interval up to ten times the
        base. A silent agent is polled less, never abandoned — the run keeps
        being observed until its identifiers expire.
        """

        interval = self.observation_interval
        if run.last_contact_at is None:
            return interval
        silent_for = now - run.last_contact_at
        if silent_for < self.reporting_window:
            return interval
        overdue = (silent_for - self.reporting_window) // interval
        doublings = min(int(overdue) + 1, _MAX_BACKOFF_DOUBLINGS)
        backed_off: timedelta = interval * 2**doublings
        return min(backed_off, interval * 10)

    def _next_observation_at(
        self, run: AgentRunDocument, *, now: datetime
    ) -> datetime | None:
        """When to look again, or never.

        ``None`` is four different facts with one consequence: the run is
        terminal, the agent no longer reports it, the connection is gone, or
        the identifiers have expired. In every one of them another request
        would be made to produce an answer nobody can act on.
        """

        if (
            run.reported_state in TERMINAL_REPORTED_STATES
            or run.agent_task_missing_at is not None
            or run.connection_disconnected_at is not None
            or run.identifiers_expired
            or run.dispatched_at is None
        ):
            return None
        return now + self.observation_backoff(run, now=now)

    def record_failed_contact(self, run_id: str, *, owner_id: str) -> None:
        """An observation that could not reach the agent. A schedule, not a state.

        Deliberately writes nothing about the run's work: BrainBuddy failing to
        reach an agent says nothing about what that agent is doing, and the
        **Stopped reporting** overlay derives from `last_contact_at`, which this
        must not touch.
        """

        with self.agent_repo.command_lock(owner_id):
            try:
                run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            except NotFoundError:
                return
            if not self._observable(run):
                return
            now = self._now()
            self.agent_repo.save_run(
                run.model_copy(
                    update={
                        "next_observation_at": self._next_observation_at(run, now=now),
                        "last_observed_at": now,
                        "updated_at": max(run.updated_at, now),
                        "revision": run.revision + 1,
                    }
                )
            )

    def record_run_read(self, run_id: str, *, owner_id: str) -> None:
        """Someone is watching, so look again at the base rate (FR-008).

        The backoff exists to spare a silent agent, not to make the product
        stale for a user who has the run open. It resets the *schedule* only —
        a read is not contact and must never move `last_contact_at`.
        """

        with self.agent_repo.command_lock(owner_id):
            try:
                run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            except NotFoundError:  # pragma: no cover - the caller just read it
                return
            if not self._observable(run) or run.next_observation_at is None:
                return
            now = self._now()
            resumed = min(run.next_observation_at, now + self.observation_interval)
            if resumed == run.next_observation_at:
                return
            self.agent_repo.save_run(
                run.model_copy(
                    update={
                        "next_observation_at": resumed,
                        "updated_at": max(run.updated_at, now),
                        "revision": run.revision + 1,
                    }
                )
            )

    def read_agent_task(self, run: AgentRunDocument) -> A2AResult | None:
        """One authenticated read of the agent's task, or nothing to read.

        ``GetTask`` with no history routinely, because the state is the point
        and the history is agent-controlled bulk. A bounded history is fetched
        only when the state that came back *needs* text — a question to answer,
        a terminal summary to show — so an ordinary poll of a working task
        never carries the conversation with it.
        """

        wire = self.a2a_client
        if wire is None:
            return None
        try:
            connection = self.agent_repo.get_connection(
                run.connection_id, owner_id=run.owner_id
            )
        except NotFoundError:  # pragma: no cover - connection rows outlive runs
            return None
        target = self._a2a_target(
            connection,
            interface_url=run.interface_url or connection.endpoint_url,
            guarantee_tier=run.guarantee_tier,
        )
        if run.agent_task_id is None:
            # The start exchange never named a task, so the only question
            # available is "is there one in this conversation?".
            return wire.list_tasks(
                target,
                context_id=run.context_id,
                page_size=5,
                scheduled=True,
                run_id=run.id,
            )
        result = wire.get_task(
            target,
            task_id=run.agent_task_id,
            context_id=run.context_id,
            history_length=0,
            scheduled=True,
            run_id=run.id,
        )
        if not self._needs_history(result):
            return result
        return wire.get_task(
            target,
            task_id=run.agent_task_id,
            context_id=run.context_id,
            history_length=OBSERVATION_HISTORY_LENGTH,
            scheduled=True,
            run_id=run.id,
        )

    def _needs_history(self, result: A2AResult) -> bool:
        """Whether the answer named a state whose text the user has to see."""

        if not result.ok or result.task is None:
            return False
        if result.task.status.text:
            return False
        return result.task.status.state in TEXT_BEARING_TASK_STATES

    def apply_agent_task(
        self,
        run: AgentRunDocument,
        result: A2AResult,
        *,
        trigger: AgentRunEventTrigger = "schedule",
    ) -> None:
        """Hand one successful read to the projection, and reschedule."""

        now = self._now()
        answered = result.task
        observation = None
        if answered is not None and self._adoptable(run, answered):
            observation = project_observation(
                answered,
                now=now,
                limits=self.observation_limits,
                result_availability=result.result_availability,
            )
        elif result.tasks:
            adopted = self._newest_adoptable(run, result)
            if adopted is not None:
                observation = project_observation(
                    adopted, now=now, limits=self.observation_limits
                )
        if observation is None:
            # Something answered, but nothing in this run's conversation. That
            # is contact with the agent and no news about the work.
            self.record_failed_contact(run.id, owner_id=run.owner_id)
            return
        if answered is not None:
            self._settle_reply_by_history(run, answered)
        self.apply_observation(
            run.id,
            owner_id=run.owner_id,
            observation=observation,
            based_on=run.run_version,
            trigger=trigger,
        )

    def _adoptable(self, run: AgentRunDocument, task: Task) -> bool:
        """Whether a returned task belongs to *this* run's conversation.

        The only evidence that an agent kept BrainBuddy's correlation ID.
        Adopting a task from another conversation would attach this run to work
        BrainBuddy never asked for, and would make every later lookup lie.
        """

        return task.context_id == run.context_id

    def _exchange_outcome(
        self,
        run: AgentRunDocument,
        result: A2AResult,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any], Observation | None, bool]:
        """One A2A answer, as (run updates, observation, correlation honoured).

        The three groups are kept apart deliberately: what BrainBuddy knows
        about *its own request* (the dispatch state), what the *agent* said (the
        observation), and what the answer proved about the connection.
        """

        if not result.ok:
            code = result.error_code
            return (
                {
                    "dispatch_state": (
                        "not_sent"
                        if code in NOT_SENT_ERROR_CODES
                        else "delivery_unconfirmed"
                    ),
                    "dispatch_error_code": code,
                },
                None,
                True,
            )
        if result.task is not None:
            if not self._adoptable(run, result.task):
                # The message plainly arrived — something answered it — but the
                # task it names is not this conversation, so nothing about the
                # agent's work may be adopted from it.
                return (
                    {
                        "dispatch_state": "sent",
                        "dispatch_error_code": A2A_RESPONSE_INVALID,
                        "last_contact_at": now,
                    },
                    None,
                    False,
                )
            observation = project_observation(
                result.task,
                now=now,
                limits=self.observation_limits,
                result_availability=result.result_availability,
            )
            return (
                {"dispatch_state": "sent", "dispatch_error_code": None},
                observation,
                True,
            )
        if result.message is not None:
            # Some agents never create a task: the answer *is* the result.
            observation = project_observation(
                result.message, now=now, limits=self.observation_limits
            )
            return (
                {"dispatch_state": "sent", "dispatch_error_code": None},
                observation,
                True,
            )
        return (
            {
                "dispatch_state": "sent",
                "dispatch_error_code": A2A_RESPONSE_INVALID,
                "last_contact_at": now,
            },
            None,
            True,
        )

    def _close_exchange(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        result: A2AResult,
        *,
        sent_push: bool = False,
    ) -> None:
        """Settle one finished exchange, honestly."""

        now = self._now()
        updates, observation, honoured = self._exchange_outcome(run, result, now=now)
        updates["exchange_state"] = "closed"
        if sent_push and result.ok:
            # BrainBuddy asked inline and the send succeeded. It is not a claim
            # that the agent will actually push — a push only ever accelerates
            # an observation the schedule performs anyway.
            updates["push_registration"] = "registered"
        updated = self.apply_observation(
            run.id,
            owner_id=run.owner_id,
            observation=observation,
            based_on=run.run_version,
            extra=updates,
            # A report that landed while the exchange was open proves the
            # message arrived, so delivery is `sent` even if the transport then
            # failed on the way back. The agent's own state is left to the
            # report that won the race.
            superseded={
                "dispatch_state": "sent",
                "dispatch_error_code": None,
                "exchange_state": "closed",
            },
        )
        if not honoured and connection.context_id_honoured is not False:
            self._record_correlation_not_honoured(connection)
        if updated is None:
            # The run was purged while the exchange was at the agent. There is
            # nothing left to describe, and an audit row naming a run that no
            # longer exists is exactly the residue a purge was asked to remove.
            return
        with self.agent_repo.command_lock(run.owner_id):
            self._audit(
                owner_id=run.owner_id,
                action="exchange_closed",
                outcome=str(updates.get("dispatch_state", updated.dispatch_state)),
                connection_id=run.connection_id,
                run_id=run.id,
            )
            if observation is not None and observation.agent_task_id is not None:
                self._audit(
                    owner_id=run.owner_id,
                    action="task_adopted",
                    outcome=observation.agent_task_id,
                    connection_id=run.connection_id,
                    run_id=run.id,
                )

    def _record_correlation_not_honoured(
        self, connection: AgentConnectionDocument
    ) -> None:
        """Remember that this agent dropped BrainBuddy's correlation ID.

        Durable on the connection rather than on the run, because it decides
        something about *every* future run there: an empty lookup on such an
        agent proves nothing, so BrainBuddy never resends for it at all.
        """

        now = self._now()
        with self.agent_repo.command_lock(connection.owner_id):
            current = self.agent_repo.get_connection(
                connection.id, owner_id=connection.owner_id
            )
            if current.context_id_honoured is False:
                return
            self.agent_repo.save_connection(
                current.model_copy(
                    update={
                        "context_id_honoured": False,
                        "updated_at": now,
                        "revision": current.revision + 1,
                    }
                )
            )

    def _probe_open_exchange(
        self, run: AgentRunDocument, connection: AgentConnectionDocument
    ) -> AgentRunDocument:
        """Look once, while a worker still holds the send, for the task it made.

        Only ever run against an *open* exchange: a queued one has provably not
        left, so there is nothing at the agent to find and the probe would be a
        request made to answer a question nobody asked.
        """

        adopted = self._lookup_task(run, connection)
        if adopted is None:
            return run
        now = self._now()
        # A purge that raced the probe leaves the caller with what it read:
        # nothing was written, and nothing may be invented in its place.
        return (
            self.apply_observation(
                run.id,
                owner_id=run.owner_id,
                observation=project_observation(
                    adopted, now=now, limits=self.observation_limits
                ),
                based_on=run.run_version,
                extra={"dispatch_state": "sent", "dispatch_error_code": None},
            )
            or run
        )

    def settle_restarted_before_send(self, run_id: str, *, owner_id: str) -> None:
        """A hand-off a restart caught before its exchange started.

        **Not sent**, never **Delivery unconfirmed**: the worker never ran, so
        no byte left BrainBuddy and there is nothing at the agent to be unsure
        about. The identifiers stay exactly as they were, which is what lets the
        same hand-off be offered again rather than replaced by a second one
        (AC-032).
        """

        with self.agent_repo.command_lock(owner_id):
            run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            if run.exchange_state != "queued":
                return
            now = self._now()
            self.agent_repo.save_run(
                run.model_copy(
                    update={
                        "dispatch_state": "not_sent",
                        "dispatch_error_code": "restarted_before_send",
                        "exchange_state": "closed",
                        "updated_at": max(run.updated_at, now),
                        "revision": run.revision + 1,
                    }
                )
            )
            self._audit(
                owner_id=owner_id,
                action="exchange_closed",
                outcome="restarted_before_send",
                connection_id=run.connection_id,
                run_id=run.id,
            )

    def recover_open_exchange(self, run_id: str, *, owner_id: str) -> None:
        """An exchange a restart interrupted after it had started.

        Resolved by lookup alone. The message may already be at the agent, so
        the only safe question is "is there a task in this conversation?" — and
        the only safe answer to "no" is to leave the run **Delivery unconfirmed**
        for the user's own **Check again**. No background thread ever resends.
        """

        with self.agent_repo.command_lock(owner_id):
            run = self.agent_repo.get_run(run_id, owner_id=owner_id)
            if run.exchange_state != "open":
                return
            now = self._now()
            run = run.model_copy(
                update={
                    "exchange_state": "interrupted",
                    "dispatch_state": "delivery_unconfirmed",
                    "updated_at": max(run.updated_at, now),
                    "revision": run.revision + 1,
                }
            )
            self.agent_repo.save_run(run)
        connection = self.agent_repo.get_connection(
            run.connection_id, owner_id=owner_id
        )
        adopted = self._lookup_task(run, connection)
        if adopted is None:
            return
        self.apply_observation(
            run.id,
            owner_id=owner_id,
            observation=project_observation(
                adopted, now=self._now(), limits=self.observation_limits
            ),
            based_on=run.run_version,
            extra={
                "dispatch_state": "sent",
                "dispatch_error_code": None,
                "exchange_state": "closed",
            },
        )

    def _lookup_task(
        self, run: AgentRunDocument, connection: AgentConnectionDocument
    ) -> Task | None:
        """The correlation-ID lookup: one `ListTasks`, never a send."""

        if self.a2a_client is None:
            # Nothing to look with. An absent answer is not an empty one, so
            # the caller is told nothing rather than "no task exists".
            return None
        result = self.a2a_client.list_tasks(
            self._a2a_target(
                connection,
                interface_url=run.interface_url or connection.endpoint_url,
                guarantee_tier=run.guarantee_tier,
            ),
            context_id=run.context_id,
            page_size=5,
            run_id=run.id,
        )
        return self._newest_adoptable(run, result)

    def _newest_adoptable(
        self, run: AgentRunDocument, result: A2AResult
    ) -> Task | None:
        """The newest task in the run's own conversation, or nothing.

        A foreign `contextId` is ignored rather than adopted: a lookup that
        matched on anything looser would let one agent's unrelated work settle
        another run.
        """

        if not result.ok:
            return None
        candidates = [task for task in result.tasks if self._adoptable(run, task)]
        if result.task is not None and self._adoptable(run, result.task):
            candidates.append(result.task)
        if not candidates:
            return None
        return max(candidates, key=lambda task: task.status.timestamp or "")

    # --- check delivery -----------------------------------------------------

    def _refuse_before_the_lookup(
        self, run: AgentRunDocument, connection: AgentConnectionDocument
    ) -> None:
        """The three conditions that make looking pointless rather than unsafe.

        Each one means there is nothing at the agent this run could still be
        waiting on, so BrainBuddy does not spend a request discovering that.
        """

        if connection.status == "disconnected":
            raise ValidationFailure(
                "This agent is disconnected, so BrainBuddy can no longer reach "
                "this run.",
                detail={"reason": "connection_disconnected"},
            )
        if run.reported_state in TERMINAL_REPORTED_STATES:
            raise ValidationFailure(
                "This run has already finished.",
                detail={"reason": "run_terminal"},
            )
        if run.agent_task_missing_at is not None:
            raise ValidationFailure(
                "This agent no longer reports this run.",
                detail={"reason": "agent_task_missing"},
            )

    def _refuse_the_resend(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        *,
        resend_allowed: bool,
        reauthenticated: bool,
    ) -> None:
        """The preconditions a *send* has that a lookup does not (FR-006).

        Every one of them is about the destination or the content being other
        than what the owner reviewed, or about the owner's consent having gone
        stale. A lookup risks none of that, which is why it has already run by
        the time any of these refuse.
        """

        if not resend_allowed:
            raise ValidationFailure(
                "External agent relay is not available, so nothing was re-sent.",
                detail={"reason": "rollout_disabled"},
            )
        if connection.agent_changed or connection.card_fingerprint != (
            run.card_fingerprint
        ):
            raise ValidationFailure(
                "This agent's card now advertises a different destination than "
                "the one this run was sent to. Test the connection again.",
                detail={"reason": AGENT_CARD_CHANGED},
            )
        if connection.status != "ready" or self._is_stale(connection):
            raise ValidationFailure(
                "Test this connection successfully before sending to it again.",
                detail={"reason": "connection_not_ready"},
            )
        if run.manifest is None:
            raise ValidationFailure(
                "This hand-off's retained content has expired, so there is "
                "nothing left to send again.",
                detail={"reason": "run_content_expired"},
            )
        if self.requires_dispatch_reauthentication(connection) and not reauthenticated:
            raise ValidationFailure(
                "Confirm your password before sending task content to this "
                "agent again.",
                detail={"reason": "reauthentication_required"},
            )

    def check_delivery(
        self,
        run_id: str,
        payload: AgentCheckDeliveryRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool = False,
        resend_allowed: bool = True,
    ) -> AgentRunResponse:
        """**Check again**: look the run up, and resend only the same message.

        Ordered deliberately. The lookup is safe — it reads, it carries no task
        content, and a task it finds settles the run without any send at all —
        so it runs first and runs even while rollout is OFF. Only after it comes
        back empty do the *send* preconditions apply, and each of those refuses
        with its own reason rather than a generic failure, because each one asks
        the owner for a different next step.

        It can never mint a second run: every identifier it uses is already on
        the run, and the resend wins the same single-writer transition a first
        send does, so concurrent checks converge on one message.
        """

        run = self.agent_repo.get_run(run_id, owner_id=owner_id)
        if run.dispatched_at is None:
            raise NotFoundError("Agent run", run_id)
        if run.dispatch_state != "delivery_unconfirmed":
            # There is no ambiguity to resolve. A `sent` run's delivery is
            # already established and a `not_sent` one provably never left, so
            # the honest answer to "check again" is the run as it stands —
            # neither a lookup nor a send would tell anyone anything new.
            return self._run_response(run)
        connection = self.agent_repo.get_connection(
            run.connection_id, owner_id=owner_id
        )
        self._refuse_before_the_lookup(run, connection)

        adopted = self._lookup_task(run, connection)
        if adopted is not None:
            # `or run` for the purge race, exactly as the probe above: a run
            # that no longer exists cannot be described by what it used to be.
            run = (
                self.apply_observation(
                    run.id,
                    owner_id=owner_id,
                    observation=project_observation(
                        adopted, now=self._now(), limits=self.observation_limits
                    ),
                    based_on=run.run_version,
                    extra={
                        "dispatch_state": "sent",
                        "dispatch_error_code": None,
                        "exchange_state": "closed",
                    },
                )
                or run
            )
            self._audit(
                owner_id=owner_id,
                action="task_adopted",
                outcome=adopted.id,
                connection_id=connection.id,
                run_id=run.id,
            )
            return self._run_response(run)

        if connection.context_id_honoured is False:
            # This agent dropped BrainBuddy's correlation ID once already, so an
            # empty lookup here is not evidence that nothing exists — it is only
            # evidence that BrainBuddy cannot tell. Sending again on that basis
            # is exactly how a duplicate task gets made.
            return self._run_response(run)

        self._refuse_the_resend(
            run,
            connection,
            resend_allowed=resend_allowed,
            reauthenticated=reauthenticated,
        )
        return self._run_response(self._resend(run, connection, owner_id=owner_id))

    def _resend(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        *,
        owner_id: str,
    ) -> AgentRunDocument:
        """Put the identical message on the wire once more, or lose and stop."""

        wire = self.a2a_client
        if wire is None:  # pragma: no cover - a deployment with no wire cannot send
            return run
        now = self._now()
        with self.agent_repo.command_lock(owner_id):
            opened = self.agent_repo.start_exchange(
                run,
                expected_version=run.run_version,
                started_at=now,
                deadline_at=now + self.reply_window,
                # The states a check may reopen from: a restart-interrupted
                # exchange, and one that closed without evidence.
                from_states=("interrupted", "closed"),
            )
        if opened is None:
            # Another check won. It is sending the same message, so this one has
            # nothing to add and nothing to send.
            return self.agent_repo.get_run(run.id, owner_id=owner_id)

        result = wire.send_message(
            self._a2a_target(
                connection,
                interface_url=opened.interface_url or connection.endpoint_url,
                guarantee_tier=opened.guarantee_tier,
            ),
            message=self._start_message(opened),
            run_id=opened.id,
        )
        self._close_exchange(opened, connection, result)
        return self.agent_repo.get_run(run.id, owner_id=owner_id)

    # --- run projection -----------------------------------------------------

    def _stopped_reporting(self, run: AgentRunDocument, *, now: datetime) -> bool:
        """The clock-derived silence condition, with this deployment's window."""

        return stopped_reporting(run, now=now, reporting_window=self.reporting_window)

    def _primary_state_label(
        self, run: AgentRunDocument, *, now: datetime
    ) -> AgentPrimaryStateLabel:
        """The one label every surface renders verbatim.

        Delegated to `domain` rather than decided here: the observer reasons
        about the same precedence, and two copies of it would be one edit away
        from two answers to "what is this run doing?".
        """

        return primary_state_label(run, now=now, reporting_window=self.reporting_window)

    def _run_response(self, run: AgentRunDocument) -> AgentRunResponse:
        now = self._now()
        run = project_run_for_access(run, now=now)
        connection: AgentConnectionDocument | None
        try:
            connection = self.agent_repo.get_connection(
                run.connection_id, owner_id=run.owner_id
            )
        except NotFoundError:  # pragma: no cover - connection rows outlive runs
            connection = None
        # BrainBuddy-side, never an agent claim: cards do not advertise reply or
        # cancellation (FR-010), so both controls are offered on a live run and
        # withdrawn only once something has actually made them impossible — a
        # disconnected connection, or an agent that refused.
        commands = self.agent_repo.list_commands(run.id, owner_id=run.owner_id)
        # A reply the agent explicitly refused for *this* task withdraws the
        # control: offering it again would invite the user to answer a question
        # the agent has already said it will not read. An unconfirmed reply is
        # the opposite case and deliberately keeps it (AC-033).
        reply_refused = any(
            command.kind == "reply" and command.delivery == "rejected"
            for command in commands
        )
        controls = AgentControlsResponse(
            reply=(
                connection is not None
                and reply_control_offered(run)
                and not reply_refused
            ),
            cancel=connection is not None and cancel_control_offered(run),
        )
        reply_pending = any(
            command.kind == "reply" and command.delivery == "unconfirmed"
            for command in commands
        )
        return AgentRunResponse(
            id=run.id,
            task_id=run.task_id,
            connection_id=run.connection_id,
            agent_name=run.agent_name,
            dispatch_state=run.dispatch_state,
            dispatch_error_code=run.dispatch_error_code,
            reported_state=run.reported_state,
            run_version=run.run_version,
            stopped_reporting=self._stopped_reporting(run, now=now),
            connection_disconnected=run.connection_disconnected_at is not None,
            reply_pending=reply_pending,
            cancel_requested=run.cancel_requested_at is not None,
            needs_user=run.reported_state == "blocked" and not run.content_expired,
            primary_state_label=self._primary_state_label(run, now=now),
            progress_text=run.progress_text,
            question_text=run.question_text,
            result_text=run.result_text,
            result_link=run.result_link,
            result_link_interactive=(
                run.result_link is not None and interactive_result_link(run.result_link)
            ),
            failure_reason=run.failure_reason,
            content_expired=run.content_expired,
            content_expires_at=run.content_expires_at,
            last_contact_at=run.last_contact_at,
            reporting_window_seconds=int(self.reporting_window.total_seconds()),
            capabilities=controls,
            guarantee_tier=run.guarantee_tier,
            message_id=run.message_id,
            # The conversation identifier *is* the run's own id: one identifier,
            # so there is nothing for the two to disagree about (FR-006).
            correlation_id=run.context_id,
            agent_task_id=run.agent_task_id,
            # True for a queued exchange as well as an open one: both are
            # unfinished business the clients keep polling, and only
            # `exchange_state` says which of the two it is.
            exchange_open=run.exchange_state in ("queued", "open"),
            exchange_state=run.exchange_state,
            exchange_kind=run.exchange_kind,
            push_registration=run.push_registration,
            agent_task_missing=run.agent_task_missing_at is not None,
            cancel_outcome=run.cancel_outcome,
            blocked_reason=run.blocked_reason,
            artifacts_summary=[
                AgentArtifactSummaryResponse(
                    name=artifact.name,
                    media_type=artifact.media_type,
                    kind=artifact.kind,
                )
                for artifact in run.artifacts_summary
            ],
            result_availability=run.result_availability,
            last_observed_at=run.last_observed_at,
            observation_interval_seconds=int(self.observation_interval.total_seconds()),
            identifiers_expired=run.identifiers_expired,
            manifest=(
                self._manifest_response(run.manifest, connection)
                if run.manifest is not None and connection is not None
                else None
            ),
            events=[
                AgentRunEventResponse(
                    id=event.id,
                    type=event.type,
                    run_version=event.run_version,
                    received_at=event.received_at,
                    summary=None if run.content_expired else event.summary,
                    trigger=event.trigger,
                    kind=event.kind,
                    previous_agent_task_id=event.previous_agent_task_id,
                    new_agent_task_id=event.new_agent_task_id,
                )
                for event in self.agent_repo.list_events(run.id, owner_id=run.owner_id)
            ],
            commands=[
                AgentRunCommandResponse(
                    id=command.id,
                    kind=command.kind,
                    body=None if run.content_expired else command.body,
                    delivery=command.delivery,
                    outcome_code=command.outcome_code,
                    created_at=command.created_at,
                    confirmed_at=command.confirmed_at,
                )
                for command in commands
            ],
            created_at=run.created_at,
            revision=run.revision,
        )

    def get_run(self, run_id: str, *, owner_id: str) -> AgentRunResponse:
        run = self.agent_repo.get_run(run_id, owner_id=owner_id)
        if run.dispatched_at is None:
            raise NotFoundError("Agent run", run_id)
        # Someone is watching this run, so the backoff a silent agent earned is
        # reset to the base interval before the answer is built (FR-008).
        self.record_run_read(run_id, owner_id=owner_id)
        return self._run_response(self.agent_repo.get_run(run_id, owner_id=owner_id))

    def list_runs_for_task(
        self, task_id: str, *, owner_id: str
    ) -> list[AgentRunResponse]:
        return [
            self._run_response(run)
            for run in self.agent_repo.list_runs_for_task(task_id, owner_id=owner_id)
            if run.dispatched_at is not None
        ]

    def latest_run_summaries(
        self, *, owner_id: str, task_ids: Sequence[str]
    ) -> dict[str, AgentRunSummaryResponse]:
        latest = self.agent_repo.latest_runs_by_task(
            owner_id=owner_id, task_ids=task_ids
        )
        return {
            task_id: self._run_summary_response(run) for task_id, run in latest.items()
        }

    def _run_summary_response(self, run: AgentRunDocument) -> AgentRunSummaryResponse:
        now = self._now()
        run = project_run_for_access(run, now=now)
        return AgentRunSummaryResponse(
            id=run.id,
            task_id=run.task_id,
            agent_name=run.agent_name,
            primary_state_label=self._primary_state_label(run, now=now),
            needs_user=run.reported_state == "blocked" and not run.content_expired,
            stopped_reporting=self._stopped_reporting(run, now=now),
            last_contact_at=run.last_contact_at,
            guarantee_tier=run.guarantee_tier,
            cancel_outcome=run.cancel_outcome,
            agent_task_missing=run.agent_task_missing_at is not None,
        )

    # --- commands -----------------------------------------------------------

    def _require_commandable(
        self, run_id: str, *, owner_id: str
    ) -> tuple[AgentRunDocument, AgentConnectionDocument]:
        run = self.agent_repo.get_run(run_id, owner_id=owner_id)
        if run.dispatched_at is None:
            raise NotFoundError("Agent run", run_id)
        connection = self.agent_repo.get_connection(
            run.connection_id, owner_id=owner_id
        )
        if connection.status == "disconnected":
            raise ValidationFailure(
                "This agent is disconnected, so BrainBuddy can no longer reach "
                "this run.",
                detail={"reason": "connection_disconnected"},
            )
        if run.reported_state in TERMINAL_REPORTED_STATES:
            raise ValidationFailure(
                "This run has already finished.",
                detail={"reason": "run_terminal"},
            )
        if run.agent_task_missing_at is not None:
            # AC-020. Not a failure and not a refusal by the agent — there is
            # simply nothing left at the agent for a command to reach, and
            # sending one would be a request made to hear the same answer.
            raise ValidationFailure(
                "This agent no longer reports this run, so BrainBuddy can no "
                "longer send it anything.",
                detail={"reason": "agent_task_missing"},
            )
        return run, connection

    def _settled_command_response(
        self, record: AgentIdempotencyRecord | None, *, owner_id: str
    ) -> AgentRunResponse | None:
        """The outcome a finished command already produced, if this is its retry.

        Answered *before* the live preconditions are consulted, and without
        touching the connector. The command in the record really happened; a
        run that has since gone terminal, or a connection since pulled, changes
        what may happen next but not what already did. Re-running the guards
        here would answer a delivered reply with "this run has already
        finished", which is both false and the exact prompt a client needs to
        send the same reply a second time under a fresh key.
        """

        if record is None or not record.completed:
            return None
        return self._run_response(
            self.agent_repo.get_run(record.resource_id, owner_id=owner_id)
        )

    # --- the reply and cancel exchanges (FR-010) ----------------------------

    def _reply_message(
        self, run: AgentRunDocument, *, command_id: str, message: str
    ) -> dict[str, Any]:
        """The follow-up message, correlated to this command and this task.

        ``messageId`` *is* the command id, so a Task whose history carries it is
        proof the agent saw this exact answer — the only correlation available
        on runtimes that serve no history at all.
        """

        payload: dict[str, Any] = {
            "messageId": command_id,
            "contextId": run.context_id,
            "role": "ROLE_USER",
            "parts": [{"text": message}],
            "metadata": {
                "brainbuddy.task_id": run.task_id,
                "brainbuddy.run_id": run.id,
                "brainbuddy.command_id": command_id,
            },
        }
        if run.agent_task_id is not None:
            # Omitted rather than sent as null when no task is known yet: the
            # SDK server rejects params it does not recognise, and a null task
            # id is a claim about a task BrainBuddy has never seen.
            payload["taskId"] = run.agent_task_id
            payload["referenceTaskIds"] = [run.agent_task_id]
        return payload

    def push_token_for(self, run: AgentRunDocument) -> str | None:
        """This run's push token, or nothing when it never registered one.

        Recomputed from the key ring rather than read from a column: the run
        stores only the fingerprint (data-model.md §7), and the fingerprint is
        what says whether a token was ever issued at all.
        """

        if run.push_token_fingerprint is None:
            return None
        return derive_push_token(self.secret_box, run.id)

    def _reply_push_config(self, run: AgentRunDocument) -> dict[str, Any] | None:
        """The run's own push callback, re-offered with the reply.

        A reply may create a *successor* task, and a config registered against
        the predecessor would not follow it. Re-sending the same per-run token
        keeps the successor push-accelerated; nothing is minted, so the token
        the agent already holds stays the only one.
        """

        token = self.push_token_for(run)
        if token is None:
            return None
        return {"url": self.push_callback_url(run.id, token), "token": token}

    def _confirmed_by_history(self, task: Task, command_id: str) -> bool:
        """Whether this task's own history proves the agent saw this command.

        The only correlation available for a reply whose exchange ended
        ambiguously: the message id *is* the command id, so finding it in the
        conversation is the agent's own record of having received it — not an
        inference from timing (data-model.md §4).
        """

        return any(message.message_id == command_id for message in task.history)

    def _settle_reply_by_history(self, run: AgentRunDocument, task: Task) -> None:
        """Confirm a pending reply the agent has since acknowledged.

        A reply exchange that ended without an answer leaves the command
        `unconfirmed`, which is the truth at that moment. A later observation
        whose history carries the command id turns it into the other truth, and
        it is the only evidence that can.
        """

        pending = run.reply_pending_command_id
        if pending is None or not self._confirmed_by_history(task, pending):
            return
        command = self.agent_repo.get_command(pending, owner_id=run.owner_id)
        if command is None or command.delivery == "confirmed":
            return
        now = self._now()
        with self.agent_repo.command_lock(run.owner_id):
            self.agent_repo.save_command(
                command.model_copy(
                    update={"delivery": "confirmed", "confirmed_at": now}
                )
            )
            current = self.agent_repo.get_run(run.id, owner_id=run.owner_id)
            self.agent_repo.save_run(
                current.model_copy(
                    update={
                        "reply_pending_command_id": None,
                        "updated_at": max(current.updated_at, now),
                        "revision": current.revision + 1,
                    }
                )
            )

    def _reply_outcome(
        self,
        run: AgentRunDocument,
        result: A2AResult,
        *,
        command_id: str,
        now: datetime,
    ) -> tuple[dict[str, Any], Observation | None, dict[str, Any]]:
        """One reply answer, as (run updates, observation, command updates).

        Three groups again, and for the same reason as a start exchange: what
        BrainBuddy knows about *its own* request, what the agent said about the
        work, and what became of the command are three different facts, and a
        surface that blended them would have to guess which it was showing.
        """

        if not result.ok:
            code = result.error_code
            if result.a2a_error_code in REPLY_REJECTING_ERROR_CODES:
                # An explicit answer about this command: the agent will not act
                # on it, so the control is withdrawn rather than left inviting
                # a second attempt that cannot work.
                return ({}, None, {"delivery": "rejected", "outcome_code": code})
            if code == A2A_TASK_NOT_FOUND:
                return (
                    {"agent_task_missing_at": now, "next_observation_at": None},
                    None,
                    {"delivery": "unconfirmed", "outcome_code": code},
                )
            # Ambiguous: silence is not a refusal, so the command stays
            # unconfirmed and the control returns after a later observation.
            return (
                {},
                None,
                {
                    "delivery": "unconfirmed",
                    "outcome_code": (code if result.a2a_error_code == -32603 else None),
                },
            )
        answered = result.task
        if answered is not None:
            if not self._adoptable(run, answered):
                # Something answered, but it named another conversation. Nothing
                # about this run's work may be adopted from it.
                return (
                    {"last_contact_at": now},
                    None,
                    {
                        "delivery": "unconfirmed",
                        "outcome_code": A2A_RESPONSE_INVALID,
                    },
                )
            observation = project_observation(
                answered, now=now, limits=self.observation_limits
            )
            return (
                {},
                observation,
                {
                    "delivery": "confirmed",
                    "outcome_code": None,
                    "agent_task_id_after": answered.id,
                    "confirmed_at": now,
                },
            )
        if result.message is not None:
            return (
                {},
                project_observation(
                    result.message, now=now, limits=self.observation_limits
                ),
                {"delivery": "confirmed", "outcome_code": None, "confirmed_at": now},
            )
        return (
            {"last_contact_at": now},
            None,
            {"delivery": "unconfirmed", "outcome_code": A2A_RESPONSE_INVALID},
        )

    def _open_reply_exchange(
        self, run: AgentRunDocument, *, owner_id: str, now: datetime
    ) -> AgentRunDocument:
        """Mark the reply exchange open, so a restart can tell what happened.

        Durable before the send, exactly as a start exchange is. The window it
        opens is also what suspends scheduled observation of the predecessor
        task: a Hermes reply may block for the full reply window, and a terminal
        observation arriving inside it would lock a run the agent is about to
        continue in a new task (AC-033).
        """

        opened = run.model_copy(
            update={
                "exchange_state": "open",
                "exchange_kind": "reply",
                "exchange_started_at": now,
                "exchange_deadline_at": now + self.reply_window,
                "updated_at": max(run.updated_at, now),
                "revision": run.revision + 1,
            }
        )
        self.agent_repo.save_run(opened)
        return opened

    def _record_task_succession(
        self,
        run: AgentRunDocument,
        *,
        previous_agent_task_id: str | None,
        observation: Observation,
    ) -> None:
        """Append the one row a succession earns, and nothing else.

        Not a state change: the run keeps its correlation id and its projected
        state, and the row exists so the user can see that the identifier they
        were shown yesterday is not the one being observed today (D-03-S27).
        """

        self.agent_repo.append_event(
            self._event_row(
                run,
                observation,
                trigger="command",
                summary=TASK_SUCCESSION_SUMMARY,
                kind="task_succession",
                previous_agent_task_id=previous_agent_task_id,
                new_agent_task_id=observation.agent_task_id,
                content_due=False,
            )
        )
        self._audit(
            owner_id=run.owner_id,
            action="task_succession_recorded",
            outcome="adopted",
            connection_id=run.connection_id,
            run_id=run.id,
        )

    def _cancel_outcome_for(
        self, result: A2AResult
    ) -> tuple[AgentCancelOutcome, str | None]:
        """One `CancelTask` answer as (outcome, command outcome code).

        Only the three explicit refusals may ever produce a durable capability
        statement. Everything else — an internal error, a 5xx, a timeout, a
        dropped connection — is `unconfirmed`, which keeps the control and the
        command id, because BrainBuddy does not know whether the agent acted.
        """

        if result.ok:
            return "accepted", None
        return (
            CANCEL_OUTCOME_BY_ERROR_CODE.get(result.error_code or "", "unconfirmed"),
            result.error_code,
        )

    def _run_control(self, call: Callable[[], A2AResult]) -> A2AResult:
        """Run one short control call, never behind a hand-off exchange.

        A cancel is what *resolves* a blocked exchange on some runtimes, so
        queueing it behind the exchanges it ends would wait out the entire reply
        window while the surface could not tell pool saturation from an agent
        that simply ignores cancellation (AC-035).
        """

        pump = self.control_pump
        if pump is None:
            return call()
        future = pump(call)
        return future.result()

    def reply_to_run(
        self,
        run_id: str,
        payload: AgentReplyRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        """Answer the agent's question, once, over the same conversation.

        The send happens outside every lock: a reply is a held exchange the
        agent may sit on for the whole reply window, and holding the
        process-wide command lock across it would stop every other owner's
        commands for as long as one agent felt like thinking.
        """

        command_name = "reply_to_run"
        canonical = self._canonical_request(command_name, payload, target=run_id)
        operation_fingerprint = self._key_fingerprint(owner_id, idempotency_key)
        with self.agent_repo.operation_lock(owner_id, operation_fingerprint):
            with self.agent_repo.command_lock(owner_id):
                key_hash, record = self._replayed(
                    owner_id=owner_id,
                    key=idempotency_key,
                    command=command_name,
                    canonical=canonical,
                )
                settled = self._settled_command_response(record, owner_id=owner_id)
                if settled is not None:
                    return settled
                reconciled = self._reconcile_attempted_command(
                    record,
                    owner_id=owner_id,
                    canonical=canonical,
                    kind="reply",
                    body=payload.message,
                )
                if reconciled is not None:
                    return reconciled
                run, connection = self._require_commandable(run_id, owner_id=owner_id)
                if project_run_for_access(run, now=self._now()).content_expired:
                    raise ValidationFailure(
                        "This run's relayed content has expired, so it can no "
                        "longer accept replies.",
                        detail={"reason": "run_content_expired"},
                    )
                if run.revision != payload.expected_revision:
                    raise ConflictError(
                        "Agent run",
                        run_id,
                        "This run changed elsewhere; reload and try again.",
                    )
                now = self._now()
                command_id, reserved_at = self._reserve_command(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    record=record,
                    now=now,
                )
                self._begin_delivery_attempt(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    command_id=command_id,
                    created_at=reserved_at,
                    request_hash=record.request_hash if record is not None else None,
                )
                # Durable before the send, so a restart can tell a reply that
                # may be at the agent from one that provably never left.
                run = self._open_reply_exchange(run, owner_id=owner_id, now=now)

            result = self._send_reply(
                run, connection, command_id=command_id, message=payload.message
            )

            current = self._close_reply_exchange(
                run,
                connection,
                result,
                command_id=command_id,
                message=payload.message,
                reserved_at=reserved_at,
            )
            with self.agent_repo.command_lock(owner_id):
                self._remember(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    command_id=command_id,
                    delivery_attempted=True,
                    created_at=reserved_at,
                )
                self._audit(
                    owner_id=owner_id,
                    action="run_replied",
                    outcome=str(current.delivery if current else "unconfirmed"),
                    connection_id=connection.id,
                    run_id=run.id,
                )
            return self._run_response(
                self.agent_repo.get_run(run.id, owner_id=owner_id)
            )

    def _send_reply(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        *,
        command_id: str,
        message: str,
    ) -> A2AResult:
        wire = self.a2a_client
        if wire is None:  # pragma: no cover - a service without a wire cannot reply
            return A2AResult(ok=False, correlation_id="", error_code=A2A_UNREACHABLE)
        return wire.send_message(
            self._a2a_target(
                connection,
                interface_url=run.interface_url or connection.endpoint_url,
                guarantee_tier=run.guarantee_tier,
            ),
            message=self._reply_message(run, command_id=command_id, message=message),
            push_config=self._reply_push_config(run),
            run_id=run.id,
        )

    def _close_reply_exchange(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        result: A2AResult,
        *,
        command_id: str,
        message: str,
        reserved_at: datetime,
    ) -> AgentRunCommandDocument | None:
        """Settle one reply: the command, the run, and the succession row."""

        owner_id = run.owner_id
        now = self._now()
        run_updates, observation, command_updates = self._reply_outcome(
            run, result, command_id=command_id, now=now
        )
        run_updates["exchange_state"] = "closed"
        previous_task_id = run.agent_task_id
        succeeded = (
            observation is not None
            and observation.agent_task_id is not None
            and observation.agent_task_id != previous_task_id
        )
        if command_updates["delivery"] == "confirmed":
            # An acknowledged reply is contact, and it clears the pending
            # marker: the question the user answered is answered.
            run_updates["reply_pending_command_id"] = None
            run_updates.setdefault("last_contact_at", now)
        else:
            run_updates["reply_pending_command_id"] = command_id
        updated = self.apply_observation(
            run.id,
            owner_id=owner_id,
            observation=observation,
            based_on=run.run_version,
            extra=run_updates,
            # Whether the agent acknowledged the user's answer is a fact about
            # *this* command, so a report that overtook it does not erase it.
            superseded={
                "exchange_state": "closed",
                "reply_pending_command_id": run_updates["reply_pending_command_id"],
            },
            trigger="command",
        )
        with self.agent_repo.command_lock(owner_id):
            command = AgentRunCommandDocument(
                id=command_id,
                owner_id=owner_id,
                run_id=run.id,
                kind="reply",
                body=None if run.content_expired else message,
                created_at=reserved_at,
                **command_updates,
            )
            self.agent_repo.save_command(command)
            if succeeded and updated is not None and observation is not None:
                self._record_task_succession(
                    updated,
                    previous_agent_task_id=previous_task_id,
                    observation=observation,
                )
        return command

    def cancel_run(
        self, run_id: str, *, owner_id: str, idempotency_key: str
    ) -> AgentRunResponse:
        """Ask the agent to stop, and report only what it actually said."""

        command_name = "cancel_run"
        canonical = self._canonical_request(command_name, {}, target=run_id)
        operation_fingerprint = self._key_fingerprint(owner_id, idempotency_key)
        with self.agent_repo.operation_lock(owner_id, operation_fingerprint):
            with self.agent_repo.command_lock(owner_id):
                key_hash, record = self._replayed(
                    owner_id=owner_id,
                    key=idempotency_key,
                    command=command_name,
                    canonical=canonical,
                )
                settled = self._settled_command_response(record, owner_id=owner_id)
                if settled is not None:
                    return settled
                reconciled = self._reconcile_attempted_command(
                    record,
                    owner_id=owner_id,
                    canonical=canonical,
                    kind="cancel",
                )
                if reconciled is not None:
                    return reconciled
                run, connection = self._require_commandable(run_id, owner_id=owner_id)
                if run.cancel_outcome in CANCEL_OUTCOMES_WITHDRAWING_THE_CONTROL:
                    # The agent already answered this question. Asking again
                    # cannot change the answer, and sending a second CancelTask
                    # would only be a request made to hear it repeated.
                    return self._run_response(run)
                now = self._now()
                attempt_receipt: dict[str, object] = {
                    "id": run.id,
                    "connection_revision": connection.revision,
                }
                command_id, reserved_at = self._reserve_command(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    record=record,
                    now=now,
                    response_body=attempt_receipt,
                )
                # An ambiguous attempt keeps its command id: a retry has to be
                # the *same* request, or the agent could act on two (AC-029).
                command_id = run.cancel_command_id or command_id
                self._begin_delivery_attempt(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    command_id=command_id,
                    created_at=reserved_at,
                    request_hash=record.request_hash if record is not None else None,
                    response_body=attempt_receipt,
                )

            result = self._run_control(
                partial(self._send_cancel, run, connection, command_id=command_id)
            )
            self._close_cancel(
                run,
                connection,
                result,
                command_id=command_id,
                reserved_at=reserved_at,
                attempted_at=now,
            )
            with self.agent_repo.command_lock(owner_id):
                self._remember(
                    owner_id=owner_id,
                    key_hash=key_hash,
                    command=command_name,
                    canonical=canonical,
                    resource_id=run.id,
                    command_id=command_id,
                    delivery_attempted=True,
                    created_at=reserved_at,
                )
            return self._run_response(
                self.agent_repo.get_run(run.id, owner_id=owner_id)
            )

    def _send_cancel(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        *,
        command_id: str,
    ) -> A2AResult:
        wire = self.a2a_client
        if wire is None:  # pragma: no cover - a service without a wire cannot cancel
            return A2AResult(ok=False, correlation_id="", error_code=A2A_UNREACHABLE)
        return wire.cancel_task(
            self._a2a_target(
                connection,
                interface_url=run.interface_url or connection.endpoint_url,
                guarantee_tier=run.guarantee_tier,
            ),
            task_id=run.agent_task_id or "",
            command_id=command_id,
            run_id=run.id,
        )

    def _close_cancel(
        self,
        run: AgentRunDocument,
        connection: AgentConnectionDocument,
        result: A2AResult,
        *,
        command_id: str,
        reserved_at: datetime,
        attempted_at: datetime,
    ) -> None:
        """Settle one cancel: outcome, command row, and the audit fact.

        ``attempted_at`` is when the *user* asked, captured before the call
        left. The overlay is about their request, not about how long the agent
        took to answer it, so a slow agent must not move the timestamp.
        """

        owner_id = run.owner_id
        now = self._now()
        outcome, outcome_code = self._cancel_outcome_for(result)
        current_connection = self.agent_repo.get_connection(
            connection.id, owner_id=owner_id
        )
        # A credential rotation or a disconnect while the cancel was in flight
        # means the request no longer describes the connection it was made
        # against. The command row still records what happened; the *run* keeps
        # no cancellation overlay, because BrainBuddy would be claiming to have
        # cancelled work through a connection it no longer has.
        scope_intact = (
            current_connection.revision == connection.revision
            and current_connection.status != "disconnected"
        )
        observation = (
            project_observation(result.task, now=now, limits=self.observation_limits)
            if result.ok and result.task is not None
            else None
        )
        updates: dict[str, Any] = {
            "cancel_outcome": outcome,
            "cancel_command_id": None if outcome != "unconfirmed" else command_id,
        }
        if outcome == "accepted":
            updates["cancel_requested_at"] = attempted_at
            updates["last_contact_at"] = now
        elif outcome == "task_missing":
            updates["agent_task_missing_at"] = now
            updates["next_observation_at"] = None
        if scope_intact:
            self.apply_observation(
                run.id,
                owner_id=owner_id,
                observation=observation,
                based_on=run.run_version,
                extra=updates,
                # The outcome of the user's own request is worth recording even
                # if a report overtook it — but not onto a run that has ended.
                superseded=updates,
                superseded_unless_terminal=True,
                trigger="command",
            )
        with self.agent_repo.command_lock(owner_id):
            self.agent_repo.save_command(
                AgentRunCommandDocument(
                    id=command_id,
                    owner_id=owner_id,
                    run_id=run.id,
                    kind="cancel",
                    delivery=CANCEL_DELIVERY_BY_OUTCOME[outcome],
                    outcome_code=(None if outcome == "accepted" else outcome_code),
                    created_at=reserved_at,
                    confirmed_at=now if outcome == "accepted" else None,
                )
            )
            self._audit(
                owner_id=owner_id,
                action="run_cancel_requested",
                outcome=outcome,
                connection_id=connection.id,
                run_id=run.id,
            )

    # --- maintenance --------------------------------------------------------

    def run_retention_sweep(self) -> int:
        """Expire relayed content and identifiers, and bound the audit log.

        Two tiers, thirty days apart, because they answer different questions:
        the content tier is what the agent *said*, and the identifier tier is
        what someone could still use to reach the work. Only the second is
        worth keeping for the ninety days the audit trail runs to.
        """

        now = self._now()
        self.agent_repo.prune_undispatched_runs(before=now - RESERVATION_TTL)
        expired = self.agent_repo.expire_due_content(now=now)
        for run_id, owner_id in self.agent_repo.expire_due_identifier_runs(now=now):
            self._audit(
                owner_id=owner_id,
                action="identifiers_expired",
                outcome="swept",
                run_id=run_id,
            )
        self.agent_repo.purge_expired_audit(now=now)
        # Owner-scoped purges only fire when that owner calls; retention is a
        # promise about the rows, so the sweep drops every expired one.
        self.agent_repo.purge_all_expired_idempotency(now=now)
        return expired

    def list_audit(self, *, owner_id: str) -> list[AgentAuditEntryDocument]:
        return self.agent_repo.list_audit(owner_id=owner_id)

    def delete_all_for_owner(self, *, owner_id: str) -> None:
        self.agent_repo.delete_all_for_owner(owner_id=owner_id)


__all__ = [
    "DEFAULT_CONTENT_RETENTION",
    "DEFAULT_REPORTING_WINDOW",
    "DEFAULT_STALE_AFTER",
    "EXTERNAL_COPY_NOTICE",
    "SCOPE_REAUTH_WINDOW",
    "AgentRelayService",
    "TaskSnapshot",
    "TaskSnapshotPort",
]
