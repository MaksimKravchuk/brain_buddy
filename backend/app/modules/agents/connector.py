"""The narrowest useful generic HTTP connector for a user-operated agent.

BrainBuddy is provider-agnostic at this boundary: it POSTs a small JSON envelope
to one endpoint the owner configured, with their credential in the header they
named. Hermes is a reference configuration of this connector, not a special
case — nothing in this module knows about any particular vendor.

Every outcome here is deliberately one of a few honest categories. A connector
that answers unexpectedly is never upgraded to "working"; the failure modes the
user can act on (bad credentials, unreachable, protocol mismatch) stay distinct,
and ambiguity is reported as ambiguity.

The capabilities response is normative. Alongside ``capabilities.progress``,
``capabilities.reply`` and ``capabilities.cancel``, a connector declares one
boolean dedup guarantee per command kind it can be asked to replay:

``idempotent_start``
    Required. Without it the connection is ``unsupported`` and cannot take a
    hand-off at all, because a retried dispatch could start the work twice.
``idempotent_reply`` / ``idempotent_cancel``
    Required *for the matching capability*. An advertised control whose
    guarantee is absent or not literally ``true`` is suppressed: the connection
    stays ready, and the control is simply not offered.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from .domain import PROTOCOL_VERSION, AgentCapabilities
from .egress import (
    DestinationRejected,
    Resolver,
    pinned_request,
    validate_destination,
)
from .headers import validate_auth_header_name

TestStatus = Literal["ready", "invalid_credentials", "unreachable", "unsupported"]
StartStatus = Literal["sent", "not_sent", "delivery_unconfirmed"]
CommandStatus = Literal["confirmed", "unconfirmed"]

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class ConnectorTarget:
    """Everything needed for one outbound call, with the secret already opened."""

    endpoint_url: str
    auth_header_name: str
    credential: str


@dataclass(frozen=True, slots=True)
class ConnectorTestOutcome:
    status: TestStatus
    capabilities: AgentCapabilities
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorStartOutcome:
    status: StartStatus
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorCommandOutcome:
    status: CommandStatus
    error_code: str | None = None


class ConnectorPort(Protocol):
    """The seam the relay service depends on, so tests need no network."""

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome: ...

    def start(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorStartOutcome: ...

    def command(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorCommandOutcome: ...


class GenericHttpConnector:
    """Speak the BrainBuddy relay envelope over plain authenticated HTTPS."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        allow_private_destinations: bool = False,
        resolver: Resolver | None = None,
        client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._allow_private_destinations = allow_private_destinations
        self._resolver = resolver
        self._client_factory = client_factory

    # --- shared plumbing ----------------------------------------------------

    def _send(
        self,
        target: ConnectorTarget,
        envelope: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        """Validate, pin, and POST. Raises for every unsafe or failed attempt."""

        validate_auth_header_name(target.auth_header_name)
        destination = validate_destination(
            target.endpoint_url,
            allow_private_destinations=self._allow_private_destinations,
            resolver=self._resolver,
        )
        headers = {
            target.auth_header_name: target.credential,
            "Accept": "application/json",
            "User-Agent": f"BrainBuddy-Relay/{PROTOCOL_VERSION}",
            **(extra_headers or {}),
        }
        response = pinned_request(
            method="POST",
            destination=destination,
            headers=headers,
            json_body=envelope,
            timeout_seconds=self._timeout_seconds,
            max_response_bytes=self._max_response_bytes,
            client_factory=self._client_factory,
        )
        return response.status_code, response.body

    @staticmethod
    def _decode(body: bytes) -> dict[str, Any] | None:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    # --- operations ---------------------------------------------------------

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome:
        """Ask the connector what it is and what it supports."""

        envelope = {"type": "capabilities", "protocol_version": PROTOCOL_VERSION}
        try:
            status_code, body = self._send(target, envelope)
        except DestinationRejected as exc:
            return ConnectorTestOutcome(
                "unreachable", AgentCapabilities(), error_code=exc.code
            )
        except httpx.HTTPError:
            return ConnectorTestOutcome(
                "unreachable", AgentCapabilities(), error_code="connector_unreachable"
            )

        if status_code in (401, 403):
            return ConnectorTestOutcome(
                "invalid_credentials",
                AgentCapabilities(),
                error_code="connector_credentials_rejected",
            )
        if not 200 <= status_code < 300:
            return ConnectorTestOutcome(
                "unreachable",
                AgentCapabilities(),
                error_code=f"connector_http_{status_code}",
            )

        parsed = self._decode(body)
        if parsed is None:
            return ConnectorTestOutcome(
                "unsupported",
                AgentCapabilities(),
                error_code="connector_response_invalid",
            )

        raw_capabilities = parsed.get("capabilities")
        declared = raw_capabilities if isinstance(raw_capabilities, dict) else {}
        capabilities = AgentCapabilities(
            progress=declared.get("progress") is True,
            # A control BrainBuddy may have to retry is only usable if the
            # connector promises to deduplicate it. An advertised capability
            # without its guarantee is suppressed rather than exposed, so the
            # user is offered nothing BrainBuddy cannot deliver safely (FR-007).
            reply=declared.get("reply") is True
            and parsed.get("idempotent_reply") is True,
            cancel=declared.get("cancel") is True
            and parsed.get("idempotent_cancel") is True,
        )
        if parsed.get("idempotent_start") is not True:
            # Without connector-side dedup a replayed dispatch could start the
            # same work twice, so the connection is honestly not usable (FR-006).
            return ConnectorTestOutcome(
                "unsupported",
                capabilities,
                error_code="connector_start_not_idempotent",
            )
        return ConnectorTestOutcome("ready", capabilities)

    def start(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorStartOutcome:
        """Hand one reviewed payload to the agent, exactly once."""

        idempotency_key = str(envelope.get("idempotency_key", ""))
        try:
            status_code, _body = self._send(
                target,
                envelope,
                extra_headers={
                    "Idempotency-Key": idempotency_key,
                    "X-BrainBuddy-Run-Id": str(envelope.get("run_id", "")),
                },
            )
        except DestinationRejected as exc:
            return ConnectorStartOutcome("not_sent", error_code=exc.code)
        except httpx.ConnectError:
            # Nothing ever reached the peer, so this is definitive non-delivery.
            return ConnectorStartOutcome("not_sent", error_code="connector_unreachable")
        except httpx.HTTPError:
            # A timeout or mid-flight transport failure is genuinely ambiguous:
            # the agent may already be working. Never call this a failure.
            return ConnectorStartOutcome(
                "delivery_unconfirmed", error_code="connector_timeout"
            )

        if 200 <= status_code < 300:
            return ConnectorStartOutcome("sent")
        if 400 <= status_code < 500:
            return ConnectorStartOutcome(
                "not_sent", error_code=f"connector_http_{status_code}"
            )
        return ConnectorStartOutcome(
            "delivery_unconfirmed", error_code=f"connector_http_{status_code}"
        )

    def command(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorCommandOutcome:
        """Route a reply or cancel, and confirm only on an explicit echo."""

        command_id = str(envelope.get("command_id", ""))
        try:
            status_code, body = self._send(
                target,
                envelope,
                extra_headers={
                    "Idempotency-Key": command_id,
                    "X-BrainBuddy-Run-Id": str(envelope.get("run_id", "")),
                },
            )
        except DestinationRejected as exc:
            return ConnectorCommandOutcome("unconfirmed", error_code=exc.code)
        except httpx.HTTPError:
            return ConnectorCommandOutcome(
                "unconfirmed", error_code="connector_unreachable"
            )

        if not 200 <= status_code < 300:
            return ConnectorCommandOutcome(
                "unconfirmed", error_code=f"connector_http_{status_code}"
            )
        parsed = self._decode(body)
        if parsed is None or parsed.get("command_id") != command_id:
            # FR-007: an unrelated 200 is not evidence this command arrived.
            return ConnectorCommandOutcome(
                "unconfirmed", error_code="connector_ack_not_correlated"
            )
        return ConnectorCommandOutcome("confirmed")


__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "ConnectorCommandOutcome",
    "ConnectorPort",
    "ConnectorStartOutcome",
    "ConnectorTarget",
    "ConnectorTestOutcome",
    "GenericHttpConnector",
]
