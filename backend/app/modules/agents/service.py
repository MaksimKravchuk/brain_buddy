"""Application service for the external-agent relay.

The organising rule of this module is that BrainBuddy only ever states what it
actually knows. There are three independent sources of truth about a run and
they are never blended: what BrainBuddy did (``dispatch_state``), what the
connector authenticated (``reported_state`` at ``run_version``), and what the
clock implies (``Stopped reporting``). A user request that has not been
acknowledged is a fourth, separate thing. Nothing here computes a percentage, an
ETA, or a completion BrainBuddy did not witness.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.exceptions import (
    BrainBuddyError,
    ConflictError,
    NotFoundError,
    ValidationFailure,
)
from app.schemas.agents import (
    AgentCapabilitiesResponse,
    AgentConnectionCreatedResponse,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionSigningSecretResponse,
    AgentContextItemResponse,
    AgentEventIngestResponse,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentManifestResponse,
    AgentReplyRequest,
    AgentReportingContractResponse,
    AgentRunCommandResponse,
    AgentRunEventResponse,
    AgentRunResponse,
    AgentRunSummaryResponse,
)
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .connector import ConnectorPort, ConnectorTarget
from .domain import (
    AGENT_EVENT_ENVELOPE_ADAPTER,
    MAX_CONTEXT_ITEMS,
    PROTOCOL_VERSION,
    REPORTING_INSTRUCTIONS_VERSION,
    TERMINAL_REPORTED_STATES,
    AgentAuditEntryDocument,
    AgentCapabilities,
    AgentCommandKind,
    AgentConnectionDocument,
    AgentEventEnvelope,
    AgentIdempotencyRecord,
    AgentManifestContextItem,
    AgentReportingContract,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
    AgentRunManifest,
)
from .egress import (
    DestinationRejected,
    Resolver,
    interactive_result_link,
    validate_destination,
)
from .repository import AgentRepository
from .secrets import (
    AAD_PURPOSE_INBOUND_SIGNING,
    AAD_PURPOSE_OUTBOUND_CREDENTIAL,
    AAD_PURPOSE_SIGNING_RECEIPT,
    SealedSecret,
    SecretBox,
    SecretDecryptionFailed,
    secret_aad,
)

DEFAULT_STALE_AFTER = timedelta(days=7)
DEFAULT_REPORTING_WINDOW = timedelta(hours=1)
DEFAULT_CONTENT_RETENTION = timedelta(days=30)
EVENT_FRESHNESS_WINDOW = timedelta(minutes=5)
SCOPE_REAUTH_WINDOW = timedelta(minutes=15)
RESERVATION_TTL = timedelta(hours=1)
MAX_EVENT_BYTES = 64_000
INBOUND_SECRET_BYTES = 32

EXTERNAL_COPY_NOTICE = (
    "Your agent receives its own copy of everything listed here. BrainBuddy "
    "cannot guarantee that its retention cleanup, disconnect, or account "
    "deletion erases that copy."
)


class EventRejected(BrainBuddyError):
    """An inbound connector report was refused; nothing was changed."""

    def __init__(self, code: str) -> None:
        super().__init__("Event rejected.")
        self.code = code


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """The only thing the relay may read from a Task: never a write path."""

    id: str
    title: str
    details: str | None


class TaskSnapshotPort(Protocol):
    def __call__(self, task_id: str, *, owner_id: str) -> TaskSnapshot: ...


def _reporting_instructions(callback_url: str, connection_id: str) -> str:
    """The versioned template shown verbatim in the hand-off review."""

    return (
        "Report progress by POSTing signed events to "
        f"{callback_url} using X-BrainBuddy-Connection: {connection_id}. Include "
        "X-BrainBuddy-Timestamp as canonical ASCII base-10 Unix seconds and "
        "X-BrainBuddy-Signature as v1=<lowercase hex HMAC-SHA256>. Sign "
        "timestamp_bytes + b'.' + raw_body with the connection signing secret. "
        "The raw JSON body uses protocol_version "
        f"{PROTOCOL_VERSION} and includes event_id, run_id, type (accepted, running, "
        "blocked, completed, failed, or cancelled), and a strictly increasing "
        "run_version. Sign each request with the connection's signing secret. "
        "BrainBuddy will not verify your result and will show it as reported by "
        "you."
    )


class AgentRelayService:
    """Owns connections, runs, and the honest projection of both."""

    def __init__(
        self,
        agent_repo: AgentRepository,
        *,
        connector: ConnectorPort,
        secret_box: SecretBox,
        task_snapshot: TaskSnapshotPort,
        callback_url: str,
        stale_after: timedelta = DEFAULT_STALE_AFTER,
        reporting_window: timedelta = DEFAULT_REPORTING_WINDOW,
        content_retention: timedelta = DEFAULT_CONTENT_RETENTION,
        allow_private_destinations: bool = False,
        resolver: Resolver | None = None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.agent_repo = agent_repo
        self.connector = connector
        self.secret_box = secret_box
        self.task_snapshot = task_snapshot
        self.callback_url = callback_url
        self.stale_after = stale_after
        self.reporting_window = reporting_window
        self.content_retention = content_retention
        self.allow_private_destinations = allow_private_destinations
        self._resolver = resolver
        self._now = now

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

    def _key_hashes(self, owner_id: str, key: str) -> list[str]:
        """Every stored form of one owner's Idempotency-Key, active key first."""

        return self.secret_box.fingerprint_candidates(
            json.dumps(
                {"v": 1, "scope": "idempotency-key", "owner": owner_id, "key": key},
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def _replayed(
        self, *, owner_id: str, key: str, command: str, canonical: str
    ) -> tuple[str, AgentIdempotencyRecord | None]:
        """Resolve a key to its stored record, refusing a reused key.

        Returns the hash the record is (or would be) stored under, so a later
        write updates that row rather than creating a second one under a newer
        key id.
        """

        candidates = self._key_hashes(owner_id, key)
        # Expired reservations must not answer for a key that is free again.
        self.agent_repo.purge_expired_idempotency(owner_id=owner_id, now=self._now())
        record = self.agent_repo.get_idempotency(
            owner_id=owner_id, key_hashes=candidates
        )
        if record is None:
            return candidates[0], None
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
                and connection.capabilities.cancel
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

    def _audit_authenticated_event_rejection(
        self,
        *,
        owner_id: str,
        connection_id: str,
        rejection_class: str,
    ) -> None:
        """Keep one coarse rejection fact per connection, class, and UTC day.

        All key material comes from authenticated server-known state. In
        particular, attacker-controlled event and run identifiers never affect
        row cardinality or appear in the durable payload.
        """

        now = self._now()
        bucket = now.astimezone(UTC).date().isoformat()
        identity = "\x1f".join(
            (owner_id, connection_id, rejection_class, bucket)
        ).encode("utf-8")
        audit_id = f"agentaudit_rejection_{hashlib.sha256(identity).hexdigest()[:24]}"
        self.agent_repo.append_audit(
            AgentAuditEntryDocument(
                id=audit_id,
                owner_id=owner_id,
                action="event_rejected",
                outcome=rejection_class,
                connection_id=connection_id,
                created_at=now,
            )
        )
        # Semantic checks run inside the owner transaction. Land this coarse row
        # before EventRejected unwinds and rolls that transaction back; no event
        # or projection mutation occurs before any rejection site.
        self.agent_repo.commit_checkpoint()

    def _validate_endpoint(self, endpoint_url: str) -> None:
        try:
            validate_destination(
                endpoint_url,
                allow_private_destinations=self.allow_private_destinations,
                resolver=self._resolver,
            )
        except DestinationRejected as exc:
            raise ValidationFailure(exc.message, detail={"reason": exc.code}) from exc

    def _target(self, connection: AgentConnectionDocument) -> ConnectorTarget:
        if connection.credential is None:
            raise ValidationFailure(
                "This connection has no stored credential. Reconnect the agent.",
                detail={"reason": "credential_missing"},
            )
        try:
            credential = self.secret_box.open(
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
        return ConnectorTarget(
            endpoint_url=connection.endpoint_url,
            auth_header_name=connection.auth_header_name,
            credential=credential,
        )

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
            endpoint_url=connection.endpoint_url,
            auth_header_name=connection.auth_header_name,
            status=connection.status,
            stale=self._is_stale(connection),
            ready_for_handoff=self._ready_for_handoff(connection),
            capabilities=AgentCapabilitiesResponse(
                **connection.capabilities.model_dump()
            ),
            last_test_error_code=connection.last_test_error_code,
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
    ) -> AgentConnectionCreatedResponse:
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
                existing = self.agent_repo.get_connection(
                    record.resource_id, owner_id=owner_id
                )
                # The one-time secret is genuinely gone; a replay cannot resurrect
                # it, and saying so beats returning a plausible-looking blank.
                return AgentConnectionCreatedResponse(
                    **self._connection_response(existing).model_dump(),
                    inbound_signing_secret="",
                )

            if not reauthenticated:
                raise ValidationFailure(
                    "Confirm your password to connect an agent.",
                    detail={"reason": "reauthentication_required"},
                )
            self._validate_endpoint(payload.endpoint_url)

            now = self._now()
            connection_id = generate_id("agentconn")
            inbound_secret = secrets.token_urlsafe(INBOUND_SECRET_BYTES)
            connection = AgentConnectionDocument(
                id=connection_id,
                owner_id=owner_id,
                name=payload.name.strip(),
                endpoint_url=payload.endpoint_url,
                auth_header_name=payload.auth_header_name,
                credential=self.secret_box.seal(
                    payload.credential,
                    aad=secret_aad(
                        AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                        owner_id=owner_id,
                        connection_id=connection_id,
                    ),
                ),
                inbound_secret=self.secret_box.seal(
                    inbound_secret,
                    aad=secret_aad(
                        AAD_PURPOSE_INBOUND_SIGNING,
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

        return AgentConnectionCreatedResponse(
            **self._connection_response(connection).model_dump(),
            inbound_signing_secret=inbound_secret,
        )

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

    def test_connection(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionResponse:
        """Ask the connector what it is, and record only what it answered."""

        connection = self.agent_repo.get_connection(connection_id, owner_id=owner_id)
        if connection.status == "disconnected":
            raise ValidationFailure(
                "This agent is disconnected. Connect it again to test it.",
                detail={"reason": "connection_disconnected"},
            )
        self._validate_endpoint(connection.endpoint_url)
        outcome = self.connector.test(self._target(connection))

        now = self._now()
        with self.agent_repo.command_lock(owner_id):
            current = self.agent_repo.get_connection(connection_id, owner_id=owner_id)
            # Connector I/O intentionally happens without the owner lock. Merge
            # the test-only fields only if the exact destination/credential
            # snapshot tested is still current; any intervening command wins.
            if current.revision != connection.revision:
                return self._connection_response(current)
            if current.status == "disconnected":
                return self._connection_response(current)
            updates: dict[str, Any] = {
                "status": outcome.status,
                "capabilities": outcome.capabilities,
                "last_test_error_code": outcome.error_code,
                "last_tested_at": now,
                "updated_at": now,
                "revision": current.revision + 1,
            }
            if outcome.status == "ready":
                # Only an authenticated success is contact; a rejection is not.
                updates["last_contact_at"] = now
            updated = current.model_copy(update=updates)
            self.agent_repo.save_connection(updated)
            self._audit(
                owner_id=owner_id,
                action="connection_tested",
                outcome=outcome.status,
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
                raise ValidationFailure(
                    "This agent is disconnected.",
                    detail={"reason": "connection_disconnected"},
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
                    "credential": self.secret_box.seal(
                        payload.credential,
                        aad=secret_aad(
                            AAD_PURPOSE_OUTBOUND_CREDENTIAL,
                            owner_id=owner_id,
                            connection_id=connection_id,
                        ),
                    ),
                    # A new credential is a new scope: readiness and the
                    # first-dispatch re-auth trigger both reset.
                    "status": "untested",
                    "capabilities": AgentCapabilities(),
                    "last_test_error_code": None,
                    "last_contact_at": None,
                    "last_tested_at": None,
                    "scope_verified_at": now,
                    "first_dispatch_at": None,
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

    def rotate_signing_secret(
        self,
        connection_id: str,
        payload: AgentConnectionRotateSigningSecretRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        reauthenticated: bool,
    ) -> AgentConnectionSigningSecretResponse:
        """Issue a replacement inbound signing secret, recoverably.

        This exists because the create response carries the secret exactly once:
        lose it and the owner holds a connection they cannot configure. The
        replacement takes effect immediately — the previous secret stops
        verifying the moment this returns — so it is guarded like registration:
        recent re-authentication, the revision the owner last saw, and a
        connection that is still connected.

        The retry story is the delicate part. If the response is lost the caller
        must be able to ask again and *get the secret*, because answering a
        replay with a blank success would leave them with a dead old secret and
        nothing to replace it with. The replacement is therefore sealed a second
        time, under its own purpose, into the idempotency record — encrypted
        under the same out-of-directory key ring, unreadable anywhere else, and
        dropped with that record after its 24-hour window. Nothing here is ever
        written or logged in plaintext.
        """

        command = "rotate_signing_secret"
        canonical = self._canonical_request(command, payload, target=connection_id)
        receipt_aad = secret_aad(
            AAD_PURPOSE_SIGNING_RECEIPT,
            owner_id=owner_id,
            connection_id=connection_id,
        )
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
                return self._replayed_signing_secret(
                    record, connection, aad=receipt_aad
                )
            if not reauthenticated:
                raise ValidationFailure(
                    "Confirm your password to replace this agent's signing secret.",
                    detail={"reason": "reauthentication_required"},
                )
            if connection.status == "disconnected":
                raise ValidationFailure(
                    "This agent is disconnected.",
                    detail={"reason": "connection_disconnected"},
                )
            if connection.revision != payload.expected_revision:
                raise ConflictError(
                    "Agent connection",
                    connection_id,
                    "This agent changed elsewhere; reload and try again.",
                )

            now = self._now()
            replacement = secrets.token_urlsafe(INBOUND_SECRET_BYTES)
            installed = self.secret_box.seal(
                replacement,
                aad=secret_aad(
                    AAD_PURPOSE_INBOUND_SIGNING,
                    owner_id=owner_id,
                    connection_id=connection_id,
                ),
            )
            updated = connection.model_copy(
                update={
                    "inbound_secret": installed,
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
                response_body={
                    "id": connection_id,
                    "sealed_signing_secret": self.secret_box.seal(
                        replacement, aad=receipt_aad
                    ).model_dump(mode="json"),
                    # What this receipt is a receipt *for*. Fingerprinting the
                    # sealed blob rather than the secret means a later replay
                    # can ask "is this still the live one?" without opening
                    # either copy.
                    "installed_secret_fingerprint": self.secret_box.fingerprint(
                        installed.ciphertext
                    ),
                },
            )
            self._audit(
                owner_id=owner_id,
                action="signing_secret_rotated",
                outcome="ok",
                connection_id=connection_id,
            )
        return self._signing_secret_response(updated, replacement)

    def _signing_secret_response(
        self, connection: AgentConnectionDocument, secret: str
    ) -> AgentConnectionSigningSecretResponse:
        return AgentConnectionSigningSecretResponse(
            **self._connection_response(connection).model_dump(),
            inbound_signing_secret=secret,
        )

    def _replayed_signing_secret(
        self,
        record: AgentIdempotencyRecord,
        connection: AgentConnectionDocument,
        *,
        aad: str,
    ) -> AgentConnectionSigningSecretResponse:
        """Answer a rotation replay only while its receipt is still current.

        A receipt outlives the rotation that wrote it, so a *later* rotation
        under a different key leaves this one describing a secret that no
        longer verifies anything. Returning it would be the worst available
        answer: a success carrying a dead secret, which the owner would then
        configure their agent with and watch every report be refused.

        Currency is decided by comparing the fingerprint of the sealed blob
        this rotation installed against the one the connection holds now.
        Both sides are ciphertext, so nothing is opened to make the comparison,
        and a receipt whose provenance cannot be established fails closed.
        """

        fingerprint = record.response_body.get("installed_secret_fingerprint")
        superseded = (
            connection.inbound_secret is None
            or not isinstance(fingerprint, str)
            or not self.secret_box.fingerprint_matches(
                fingerprint, connection.inbound_secret.ciphertext
            )
        )
        if superseded:
            raise ConflictError(
                "Agent connection",
                connection.id,
                "This agent's signing secret has been replaced since that "
                "request. Replace it again to get a secret you can use.",
            )
        return self._signing_secret_response(
            connection, self._open_receipt(record, aad=aad)
        )

    def _open_receipt(self, record: AgentIdempotencyRecord, *, aad: str) -> str:
        """Recover the replacement a lost response never delivered."""

        sealed = record.response_body.get("sealed_signing_secret")
        if not isinstance(sealed, dict):
            # The record exists but carries no receipt: nothing honest is left
            # to return, so say so rather than answering with a blank secret.
            raise ValidationFailure(
                "This signing-secret replacement can no longer be recovered. "
                "Replace the signing secret again.",
                detail={"reason": "signing_secret_unrecoverable"},
            )
        try:
            return self.secret_box.open(SealedSecret.model_validate(sealed), aad=aad)
        except (SecretDecryptionFailed, PydanticValidationError) as exc:
            raise ValidationFailure(
                "This signing-secret replacement can no longer be recovered. "
                "Replace the signing secret again.",
                detail={"reason": "signing_secret_unrecoverable"},
            ) from exc

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
                    # Both secrets go. Events signed by the old inbound secret
                    # can no longer be verified, which is the point (FR-016).
                    "credential": None,
                    "inbound_secret": None,
                    "status": "disconnected",
                    "capabilities": AgentCapabilities(),
                    "disconnected_at": now,
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
                            "updated_at": now,
                            "revision": run.revision + 1,
                        }
                    )
                )
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
            raise ValidationFailure(
                "This agent is disconnected. Connect it again before handing "
                "work to it.",
                detail={"reason": "connection_disconnected"},
            )
        if connection.status != "ready":
            raise ValidationFailure(
                "Test this connection successfully before handing work to it.",
                detail={"reason": "connection_not_ready", "status": connection.status},
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

    def _build_manifest(
        self,
        *,
        run_id: str,
        task: TaskSnapshot,
        connection: AgentConnectionDocument,
        payload: AgentHandoffPreviewRequest,
    ) -> AgentRunManifest:
        if len(payload.context_items) > MAX_CONTEXT_ITEMS:
            raise ValidationFailure(
                f"A hand-off may include at most {MAX_CONTEXT_ITEMS} context items.",
                detail={"reason": "too_many_context_items"},
            )
        context_items = [
            AgentManifestContextItem(label=item.label, body=item.body)
            for item in payload.context_items
        ]
        details = task.details if payload.include_details else None
        reporting = AgentReportingContract(
            callback_url=self.callback_url, connection_id=connection.id
        )
        instructions = _reporting_instructions(self.callback_url, connection.id)
        content = {
            "run_id": run_id,
            "task_id": task.id,
            "connection_id": connection.id,
            "destination": connection.endpoint_url,
            "agent_name": connection.name,
            "title": task.title,
            "details": details,
            "context_items": [item.model_dump() for item in context_items],
            "reporting": reporting.model_dump(mode="json"),
            "reporting_instructions": instructions,
            "instructions_version": REPORTING_INSTRUCTIONS_VERSION,
            "protocol_version": PROTOCOL_VERSION,
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
            reporting_instructions=instructions,
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
            context_items=[
                AgentContextItemResponse(label=item.label, body=item.body)
                for item in manifest.context_items
            ],
            reporting=AgentReportingContractResponse(**manifest.reporting.model_dump()),
            reporting_instructions=manifest.reporting_instructions,
            instructions_version=manifest.instructions_version,
            protocol_version=manifest.protocol_version,
            destination_endpoint=connection.endpoint_url,
            external_copy_notice=EXTERNAL_COPY_NOTICE,
            reauthentication_required=self.requires_dispatch_reauthentication(
                connection
            ),
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
        operation_fingerprint = self._key_hashes(owner_id, idempotency_key)[0]
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
                            "dispatch_state": "delivery_unconfirmed",
                            "dispatch_error_code": None,
                            "content_expires_at": now + self.content_retention,
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
                    if connection.first_dispatch_at is None:
                        connection = connection.model_copy(
                            update={
                                "first_dispatch_at": now,
                                "updated_at": now,
                                "revision": connection.revision + 1,
                            }
                        )
                        self.agent_repo.save_connection(connection)
                target = self._target(connection)
                envelope = {
                    "type": "start",
                    "protocol_version": PROTOCOL_VERSION,
                    "run_id": reserved.id,
                    "task_id": manifest.task_id,
                    "idempotency_key": reserved.id,
                    "title": manifest.title,
                    "details": manifest.details,
                    "context": [item.model_dump() for item in manifest.context_items],
                    "reporting": {
                        **manifest.reporting.model_dump(mode="json"),
                        "instructions": manifest.reporting_instructions,
                        "instructions_version": manifest.instructions_version,
                    },
                }
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

            outcome = self.connector.start(target, envelope=envelope)

            with self.agent_repo.command_lock(owner_id):
                current = self.agent_repo.get_run(reserved.id, owner_id=owner_id)
                post_io_now = self._now()
                callback_arrived_during_io = current.run_version > reserved.run_version
                effective_status = (
                    "sent" if callback_arrived_during_io else outcome.status
                )
                updates: dict[str, Any] = {
                    "dispatch_state": effective_status,
                    "dispatch_error_code": (
                        None if callback_arrived_during_io else outcome.error_code
                    ),
                    "updated_at": max(current.updated_at, post_io_now),
                    "revision": current.revision + 1,
                }
                if effective_status == "sent" and current.last_contact_at is None:
                    updates["last_contact_at"] = post_io_now
                current = current.model_copy(update=updates)
                self.agent_repo.save_run(current)
                self.agent_repo.save_command(
                    AgentRunCommandDocument(
                        id=command_id,
                        owner_id=owner_id,
                        run_id=current.id,
                        kind="start",
                        delivery=(
                            "confirmed" if effective_status == "sent" else "unconfirmed"
                        ),
                        created_at=reserved_at,
                        confirmed_at=(
                            post_io_now if effective_status == "sent" else None
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
                self._audit(
                    owner_id=owner_id,
                    action="run_dispatched",
                    outcome=effective_status,
                    connection_id=connection.id,
                    run_id=current.id,
                )
            return self._run_response(current)

    # --- run projection -----------------------------------------------------

    def _stopped_reporting(self, run: AgentRunDocument) -> bool:
        if run.reported_state in TERMINAL_REPORTED_STATES:
            return False
        if run.connection_disconnected_at is not None:
            return False
        if run.dispatch_state == "not_sent":
            return False
        if run.last_contact_at is None:
            return False
        return self._now() >= run.last_contact_at + self.reporting_window

    def _primary_state_label(self, run: AgentRunDocument) -> str:
        if run.connection_disconnected_at is not None:
            label = "Connection disconnected"
        elif run.reported_state == "completed":
            # Never "Complete": BrainBuddy did not verify the work (FR-011).
            label = "Agent reported complete"
        elif run.reported_state == "failed":
            label = "Failed"
        elif run.reported_state == "cancelled":
            label = "Cancelled"
        elif self._stopped_reporting(run):
            label = "Stopped reporting"
        elif run.reported_state == "blocked":
            label = "Needs you"
        elif run.cancel_requested_at is not None:
            label = "Cancellation requested"
        elif run.reported_state == "running":
            label = "Running"
        elif run.reported_state == "accepted":
            label = "Accepted"
        elif run.dispatch_state == "delivery_unconfirmed":
            label = "Delivery unconfirmed"
        elif run.dispatch_state == "sent":
            label = "Sent"
        else:
            label = "Not sent"
        return label

    def _run_response(self, run: AgentRunDocument) -> AgentRunResponse:
        connection: AgentConnectionDocument | None
        try:
            connection = self.agent_repo.get_connection(
                run.connection_id, owner_id=run.owner_id
            )
        except NotFoundError:  # pragma: no cover - connection rows outlive runs
            connection = None
        capabilities = (
            connection.capabilities if connection is not None else AgentCapabilities()
        )
        commands = self.agent_repo.list_commands(run.id, owner_id=run.owner_id)
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
            stopped_reporting=self._stopped_reporting(run),
            connection_disconnected=run.connection_disconnected_at is not None,
            reply_pending=reply_pending,
            cancel_requested=run.cancel_requested_at is not None,
            needs_user=run.reported_state == "blocked",
            primary_state_label=self._primary_state_label(run),
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
            capabilities=AgentCapabilitiesResponse(**capabilities.model_dump()),
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
                    summary=event.summary,
                )
                for event in self.agent_repo.list_events(run.id, owner_id=run.owner_id)
            ],
            commands=[
                AgentRunCommandResponse(
                    id=command.id,
                    kind=command.kind,
                    body=command.body,
                    delivery=command.delivery,
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
        return self._run_response(run)

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
            task_id: AgentRunSummaryResponse(
                id=run.id,
                task_id=run.task_id,
                agent_name=run.agent_name,
                primary_state_label=self._primary_state_label(run),
                needs_user=run.reported_state == "blocked",
                stopped_reporting=self._stopped_reporting(run),
                last_contact_at=run.last_contact_at,
            )
            for task_id, run in latest.items()
        }

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

    def reply_to_run(
        self,
        run_id: str,
        payload: AgentReplyRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> AgentRunResponse:
        command_name = "reply_to_run"
        canonical = self._canonical_request(command_name, payload, target=run_id)
        operation_fingerprint = self._key_hashes(owner_id, idempotency_key)[0]
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
                if run.content_expired:
                    raise ValidationFailure(
                        "This run's relayed content has expired, so it can no longer accept replies.",
                        detail={"reason": "run_content_expired"},
                    )
                if run.revision != payload.expected_revision:
                    raise ConflictError(
                        "Agent run",
                        run_id,
                        "This run changed elsewhere; reload and try again.",
                    )
                if not connection.capabilities.reply:
                    raise ValidationFailure(
                        "This agent does not support replies.",
                        detail={
                            "reason": "capability_unsupported",
                            "capability": "reply",
                        },
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
                target = self._target(connection)
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

            outcome = self.connector.command(
                target,
                envelope={
                    "type": "reply",
                    "protocol_version": PROTOCOL_VERSION,
                    "run_id": run.id,
                    "command_id": command_id,
                    "message": payload.message,
                },
            )

            with self.agent_repo.command_lock(owner_id):
                current = self.agent_repo.get_run(run.id, owner_id=owner_id)
                current_connection = self.agent_repo.get_connection(
                    connection.id, owner_id=owner_id
                )
                self.agent_repo.save_command(
                    AgentRunCommandDocument(
                        id=command_id,
                        owner_id=owner_id,
                        run_id=run.id,
                        kind="reply",
                        body=None if current.content_expired else payload.message,
                        delivery=(
                            "confirmed"
                            if outcome.status == "confirmed"
                            else "unconfirmed"
                        ),
                        created_at=reserved_at,
                        confirmed_at=now if outcome.status == "confirmed" else None,
                    )
                )
                unchanged_scope = (
                    current.revision == run.revision
                    and current_connection.revision == connection.revision
                    and current_connection.status != "disconnected"
                    and current.reported_state not in TERMINAL_REPORTED_STATES
                    and not current.content_expired
                    and current_connection.capabilities.reply
                )
                if unchanged_scope:
                    current = current.model_copy(
                        update={
                            "reply_pending_command_id": command_id,
                            "updated_at": now,
                            "revision": current.revision + 1,
                        }
                    )
                    self.agent_repo.save_run(current)
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
                    outcome=outcome.status,
                    connection_id=connection.id,
                    run_id=run.id,
                )
            return self._run_response(current)

    def cancel_run(
        self, run_id: str, *, owner_id: str, idempotency_key: str
    ) -> AgentRunResponse:
        command_name = "cancel_run"
        canonical = self._canonical_request(command_name, {}, target=run_id)
        operation_fingerprint = self._key_hashes(owner_id, idempotency_key)[0]
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
                if not connection.capabilities.cancel:
                    raise ValidationFailure(
                        "This agent does not support cancellation.",
                        detail={
                            "reason": "capability_unsupported",
                            "capability": "cancel",
                        },
                    )
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
                target = self._target(connection)
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

            outcome = self.connector.command(
                target,
                envelope={
                    "type": "cancel",
                    "protocol_version": PROTOCOL_VERSION,
                    "run_id": run.id,
                    "command_id": command_id,
                },
            )

            with self.agent_repo.command_lock(owner_id):
                current = self.agent_repo.get_run(run.id, owner_id=owner_id)
                current_connection = self.agent_repo.get_connection(
                    connection.id, owner_id=owner_id
                )
                merge_time = max(current.updated_at, self._now())
                self.agent_repo.save_command(
                    AgentRunCommandDocument(
                        id=command_id,
                        owner_id=owner_id,
                        run_id=run.id,
                        kind="cancel",
                        delivery=(
                            "confirmed"
                            if outcome.status == "confirmed"
                            else "unconfirmed"
                        ),
                        created_at=reserved_at,
                        confirmed_at=(
                            merge_time if outcome.status == "confirmed" else None
                        ),
                    )
                )
                unchanged_scope = (
                    current_connection.revision == connection.revision
                    and current_connection.status != "disconnected"
                    and current.reported_state not in TERMINAL_REPORTED_STATES
                    and current_connection.capabilities.cancel
                )
                if unchanged_scope:
                    current = current.model_copy(
                        update={
                            "cancel_requested_at": now,
                            "updated_at": merge_time,
                            "revision": current.revision + 1,
                        }
                    )
                    self.agent_repo.save_run(current)
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
                    action="run_cancel_requested",
                    outcome=outcome.status,
                    connection_id=connection.id,
                    run_id=run.id,
                )
            return self._run_response(current)

    # --- inbound events -----------------------------------------------------

    def _authenticate_event_request(
        self,
        *,
        raw_body: bytes,
        connection_id: str,
        timestamp: str,
        signature: str,
    ) -> AgentConnectionDocument:
        """Authenticate the exact wire bytes without recording probe evidence."""

        connection = self.agent_repo.find_connection_anywhere(connection_id)
        if connection is None:
            raise EventRejected("unknown_connection")
        if len(raw_body) > MAX_EVENT_BYTES:
            raise EventRejected("event_too_large")
        if connection.status == "disconnected" or connection.inbound_secret is None:
            raise EventRejected("connection_disconnected")
        try:
            secret = self.secret_box.open(
                connection.inbound_secret,
                aad=secret_aad(
                    AAD_PURPOSE_INBOUND_SIGNING,
                    owner_id=connection.owner_id,
                    connection_id=connection.id,
                ),
            )
        except SecretDecryptionFailed as exc:
            raise EventRejected("signing_secret_unreadable") from exc
        if not (
            timestamp.isascii()
            and timestamp.isdecimal()
            and (timestamp == "0" or not timestamp.startswith("0"))
        ):
            raise EventRejected("timestamp_invalid")
        try:
            sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (TypeError, ValueError, OverflowError) as exc:
            raise EventRejected("timestamp_invalid") from exc
        if abs(self._now() - sent_at) > EVENT_FRESHNESS_WINDOW:
            raise EventRejected("timestamp_stale")

        expected = hmac.new(
            secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        valid_signature_format = (
            len(signature) == 67
            and signature.startswith("v1=")
            and all(character in "0123456789abcdef" for character in signature[3:])
        )
        if not valid_signature_format or not hmac.compare_digest(
            expected, signature[3:]
        ):
            raise EventRejected("signature_invalid")
        return connection

    def _authenticated_event_rejection(
        self, connection: AgentConnectionDocument, code: str
    ) -> EventRejected:
        """Retain only bounded coarse evidence after the complete body authenticates."""

        self._audit_authenticated_event_rejection(
            owner_id=connection.owner_id,
            connection_id=connection.id,
            rejection_class=code,
        )
        return EventRejected(code)

    def _validate_authenticated_event(
        self,
        *,
        raw_body: bytes,
        connection: AgentConnectionDocument,
    ) -> AgentEventEnvelope:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self._authenticated_event_rejection(
                connection, "body_invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise self._authenticated_event_rejection(connection, "body_invalid")

        # Strict validation turns an authentic body into a valid protocol event.
        try:
            event = AGENT_EVENT_ENVELOPE_ADAPTER.validate_python(payload)
        except PydanticValidationError as exc:
            raise self._authenticated_event_rejection(
                connection, "envelope_invalid"
            ) from exc
        if event.protocol_version != PROTOCOL_VERSION:
            raise self._authenticated_event_rejection(
                connection, "protocol_version_unsupported"
            )
        if event.connection_id != connection.id:
            raise self._authenticated_event_rejection(connection, "connection_mismatch")
        return event

    def _event_run(
        self, connection: AgentConnectionDocument, event: AgentEventEnvelope
    ) -> AgentRunDocument:
        try:
            run = self.agent_repo.get_run(event.run_id, owner_id=connection.owner_id)
        except NotFoundError as exc:
            raise self._authenticated_event_rejection(
                connection, "unknown_run"
            ) from exc
        if run.dispatched_at is None or run.connection_id != connection.id:
            raise self._authenticated_event_rejection(
                connection, "run_not_for_connection"
            )
        if run.connection_disconnected_at is not None:
            raise self._authenticated_event_rejection(
                connection, "connection_disconnected"
            )
        if event.run_version <= run.run_version:
            raise self._authenticated_event_rejection(
                connection, "run_version_not_newer"
            )
        if run.reported_state in TERMINAL_REPORTED_STATES:
            raise self._authenticated_event_rejection(connection, "run_terminal")
        return run

    @staticmethod
    def _event_updates(
        run: AgentRunDocument, event: AgentEventEnvelope, *, now: datetime
    ) -> dict[str, Any]:
        progress = getattr(event, "progress", None)
        updates: dict[str, Any] = {
            "reported_state": event.type,
            "run_version": event.run_version,
            "last_contact_at": now,
            "updated_at": now,
            "revision": run.revision + 1,
        }
        if run.content_expired:
            # Retention is irreversible: higher versions advance state/contact,
            # but a late event can never recreate expired content.
            updates.update(
                progress_text=None,
                question_text=None,
                result_text=None,
                result_link=None,
                failure_reason=None,
            )
        else:
            if progress is not None:
                updates["progress_text"] = progress
            updates["question_text"] = (
                getattr(event, "question", None) if event.type == "blocked" else None
            )
            if event.type == "completed":
                updates["result_text"] = getattr(event, "result", None)
                updates["result_link"] = getattr(event, "result_link", None)
            if event.type == "failed":
                updates["failure_reason"] = getattr(event, "reason", None)
        if event.type in TERMINAL_REPORTED_STATES:
            updates["cancel_requested_at"] = None
        return updates

    @staticmethod
    def _event_summary(run: AgentRunDocument, event: AgentEventEnvelope) -> str | None:
        if run.content_expired:
            return None
        return (
            getattr(event, "progress", None)
            or getattr(event, "question", None)
            or getattr(event, "result", None)
            or getattr(event, "reason", None)
        )

    def _apply_authenticated_event(
        self, connection: AgentConnectionDocument, event: AgentEventEnvelope
    ) -> None:
        owner_id = connection.owner_id
        with self.agent_repo.command_lock(owner_id):
            run = self._event_run(connection, event)
            # Consume only after every projection check, so rejection cannot burn
            # an identifier. The repository claim remains the atomic replay gate.
            if not self.agent_repo.consume_event_id(
                owner_id=owner_id,
                connection_id=connection.id,
                event_id=event.event_id,
                now=self._now(),
            ):
                raise self._authenticated_event_rejection(connection, "event_replayed")

            now = self._now()
            self.agent_repo.save_run(
                run.model_copy(update=self._event_updates(run, event, now=now))
            )
            self.agent_repo.append_event(
                AgentRunEventDocument(
                    id=event.event_id,
                    owner_id=owner_id,
                    run_id=run.id,
                    connection_id=connection.id,
                    type=event.type,
                    run_version=event.run_version,
                    received_at=now,
                    summary=self._event_summary(run, event),
                )
            )
            self._audit(
                owner_id=owner_id,
                action="event_accepted",
                outcome=event.type,
                connection_id=connection.id,
                run_id=run.id,
            )

    def ingest_event(
        self,
        *,
        raw_body: bytes,
        connection_id: str,
        timestamp: str,
        signature: str,
    ) -> AgentEventIngestResponse:
        """Authenticate, validate, then apply one connector report."""

        connection = self._authenticate_event_request(
            raw_body=raw_body,
            connection_id=connection_id,
            timestamp=timestamp,
            signature=signature,
        )
        event = self._validate_authenticated_event(
            raw_body=raw_body,
            connection=connection,
        )
        self._apply_authenticated_event(connection, event)
        return AgentEventIngestResponse(accepted=True, run_version=event.run_version)

    # --- maintenance --------------------------------------------------------

    def run_retention_sweep(self) -> int:
        """Expire relayed content, prune reservations, and bound the audit log."""

        now = self._now()
        self.agent_repo.prune_undispatched_runs(before=now - RESERVATION_TTL)
        expired = self.agent_repo.expire_due_content(now=now)
        self.agent_repo.purge_expired_audit(now=now)
        self.agent_repo.purge_expired_event_ids(now=now)
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
    "EventRejected",
    "TaskSnapshot",
    "TaskSnapshotPort",
]
