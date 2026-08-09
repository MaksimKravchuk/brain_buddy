"""The generic HTTP connector: the only thing that talks to a user's agent.

These tests drive the real ``pinned_request`` egress path through an httpx mock
transport, so the pinned address, the ``Host`` header, redirect refusal, and
response bounding are all exercised rather than stubbed.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.modules.agents.connector import (
    ConnectorTarget,
    GenericHttpConnector,
)
from app.modules.agents.domain import PROTOCOL_VERSION

TARGET = ConnectorTarget(
    endpoint_url="https://agent.example.com/hooks",
    auth_header_name="Authorization",
    credential="Bearer super-secret-token",
)


def _resolver(host: str, port: int) -> list[str]:
    return {"agent.example.com": ["93.184.216.34"]}[host]


def build_connector(
    handler: Any, *, allow_private_destinations: bool = False
) -> tuple[GenericHttpConnector, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client_factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(recording_handler), **kwargs)

    connector = GenericHttpConnector(
        timeout_seconds=5.0,
        max_response_bytes=64_000,
        allow_private_destinations=allow_private_destinations,
        resolver=_resolver,
        client_factory=client_factory,
    )
    return connector, seen


def json_handler(payload: dict[str, Any], status_code: int = 200) -> Any:
    return lambda request: httpx.Response(status_code, json=payload)


class TestConnectionTest:
    def test_a_conforming_connector_is_ready_and_discloses_capabilities(self) -> None:
        """A healthy connector reports exactly what it can do."""

        connector, seen = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": False},
                    "idempotent_start": True,
                    "idempotent_reply": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.progress is True
        assert outcome.capabilities.reply is True
        assert outcome.capabilities.cancel is False
        body = json.loads(seen[0].content)
        assert body["type"] == "capabilities"
        assert body["protocol_version"] == PROTOCOL_VERSION

    def test_the_credential_travels_in_the_configured_header(self) -> None:
        """The connector sends the saved credential where the user configured it."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        connector.test(
            ConnectorTarget(
                endpoint_url="https://agent.example.com/hooks",
                auth_header_name="X-Hermes-Key",
                credential="hermes-key-value",
            )
        )

        assert seen[0].headers["X-Hermes-Key"] == "hermes-key-value"

    def test_the_request_goes_to_the_pinned_address_with_the_original_host(
        self,
    ) -> None:
        """A rebinding answer cannot move the connection after validation."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        connector.test(TARGET)

        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["Host"] == "agent.example.com"
        assert seen[0].extensions["sni_hostname"] == "agent.example.com"

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_an_authentication_rejection_is_reported_as_invalid_credentials(
        self, status_code: int
    ) -> None:
        """Bad credentials are distinguishable from an unreachable endpoint."""

        connector, _ = build_connector(json_handler({}, status_code))

        outcome = connector.test(TARGET)

        assert outcome.status == "invalid_credentials"

    @pytest.mark.parametrize("status_code", [404, 500, 503])
    def test_other_http_failures_are_reported_as_unreachable(
        self, status_code: int
    ) -> None:
        """Any other failure is honestly 'we could not reach a working agent'."""

        connector, _ = build_connector(json_handler({}, status_code))

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == f"connector_http_{status_code}"

    def test_a_transport_failure_is_reported_as_unreachable(self) -> None:
        """A dead endpoint never looks like a working one."""

        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        connector, _ = build_connector(explode)

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == "connector_unreachable"

    def test_a_timeout_is_reported_as_unreachable(self) -> None:
        """An endpoint that never answers is not 'ready'."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        assert connector.test(TARGET).status == "unreachable"

    def test_a_connector_without_start_idempotency_is_not_ready(self) -> None:
        """FR-006: no dedup guarantee means the connector cannot take a hand-off."""

        connector, _ = build_connector(
            json_handler({"capabilities": {"progress": True}, "idempotent_start": False})
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "unsupported"
        assert outcome.error_code == "connector_start_not_idempotent"

    @pytest.mark.parametrize(
        ("capability", "guarantee"),
        [("reply", "idempotent_reply"), ("cancel", "idempotent_cancel")],
    )
    def test_a_command_capability_without_its_dedup_promise_is_suppressed(
        self, capability: str, guarantee: str
    ) -> None:
        """FR-006/FR-007: a control BrainBuddy cannot replay safely is not offered.

        Reply and cancel are retried on an ambiguous send, reusing one command
        ID. A connector that advertises the control but never promises to
        deduplicate that ID could act twice on one user request, so the control
        is withheld rather than exposed with a caveat.
        """

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                    guarantee: False,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert getattr(outcome.capabilities, capability) is False
        assert outcome.capabilities.progress is True

    def test_a_missing_dedup_promise_is_not_a_promise(self) -> None:
        """Silence is not a guarantee: both controls stay off by default."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_a_dedup_promise_without_the_capability_grants_nothing(self) -> None:
        """The guarantee qualifies a capability; it cannot conjure one."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": False, "reply": False, "cancel": False},
                    "idempotent_start": True,
                    "idempotent_reply": True,
                    "idempotent_cancel": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_both_controls_survive_when_both_are_guaranteed(self) -> None:
        """A fully conforming connector keeps everything it advertised."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                    "idempotent_reply": True,
                    "idempotent_cancel": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.reply is True
        assert outcome.capabilities.cancel is True

    @pytest.mark.parametrize("truthy", ["yes", 1, {}, None])
    def test_only_an_explicit_boolean_true_counts_as_a_promise(
        self, truthy: Any
    ) -> None:
        """A truthy-looking value is not the documented guarantee."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"reply": True, "cancel": True},
                    "idempotent_start": True,
                    "idempotent_reply": truthy,
                    "idempotent_cancel": truthy,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_an_unparseable_body_is_not_ready(self) -> None:
        """A 200 that is not the agreed envelope proves nothing."""

        connector, _ = build_connector(lambda request: httpx.Response(200, text="hi"))

        outcome = connector.test(TARGET)

        assert outcome.status == "unsupported"
        assert outcome.error_code == "connector_response_invalid"

    def test_a_redirect_is_refused_rather_than_followed(self) -> None:
        """Redirects can move a credential off the validated destination."""

        connector, _ = build_connector(
            lambda request: httpx.Response(
                302, headers={"Location": "https://evil.example.com/steal"}
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_redirect_not_allowed"

    def test_an_unsafe_destination_never_reaches_the_network(self) -> None:
        """Destination class is checked before the credential is serialized."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        outcome = connector.test(
            ConnectorTarget(
                endpoint_url="https://169.254.169.254/latest",
                auth_header_name="Authorization",
                credential="Bearer super-secret-token",
            )
        )

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_network_not_allowed"
        assert seen == []


class TestStart:
    def _envelope(self) -> dict[str, Any]:
        return {
            "type": "start",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "agentrun_1",
            "task_id": "task_1",
            "idempotency_key": "idem-1",
            "title": "Draft the migration plan",
            "details": None,
            "context": [],
            "reporting": {
                "callback_url": "https://brainbuddy.example/api/agent-events",
                "instructions": "Report progress to the callback URL.",
                "instructions_version": "v1",
            },
        }

    def test_an_accepted_start_is_reported_as_sent(self) -> None:
        """A 2xx means the agent took the work."""

        connector, seen = build_connector(json_handler({"accepted": True}, 202))

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "sent"
        assert json.loads(seen[0].content)["run_id"] == "agentrun_1"
        assert seen[0].headers["Idempotency-Key"] == "idem-1"

    def test_a_timeout_is_delivery_unconfirmed_not_failed(self) -> None:
        """FR-006: ambiguous loss must never be called failure."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "delivery_unconfirmed"

    def test_a_server_error_is_delivery_unconfirmed(self) -> None:
        """A 5xx may or may not have started work; we must not guess."""

        connector, _ = build_connector(json_handler({}, 500))

        assert (
            connector.start(TARGET, envelope=self._envelope()).status
            == "delivery_unconfirmed"
        )

    def test_a_connection_error_proves_nothing_was_sent(self) -> None:
        """A refused connection is definitive evidence of non-delivery."""

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        connector, _ = build_connector(refuse)

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "not_sent"

    def test_a_client_rejection_proves_nothing_was_started(self) -> None:
        """A 4xx is a definitive refusal, so the run was never accepted."""

        connector, _ = build_connector(json_handler({"error": "bad"}, 400))

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "not_sent"
        assert outcome.error_code == "connector_http_400"


class TestCommand:
    def _envelope(self) -> dict[str, Any]:
        return {
            "type": "reply",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "agentrun_1",
            "command_id": "agentcmd_1",
            "message": "Use the staging database.",
        }

    def test_an_acknowledgement_correlated_to_the_command_confirms_delivery(
        self,
    ) -> None:
        """FR-007: only an explicit command-ID echo confirms delivery."""

        connector, _ = build_connector(json_handler({"command_id": "agentcmd_1"}))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "confirmed"

    def test_a_success_without_the_command_id_stays_unconfirmed(self) -> None:
        """A bare 200 is not evidence the agent received this command."""

        connector, _ = build_connector(json_handler({"ok": True}))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "unconfirmed"

    def test_an_acknowledgement_for_a_different_command_does_not_confirm(self) -> None:
        """Correlation is checked, not assumed."""

        connector, _ = build_connector(json_handler({"command_id": "agentcmd_other"}))

        assert connector.command(TARGET, envelope=self._envelope()).status == (
            "unconfirmed"
        )

    def test_a_non_success_response_leaves_the_command_unconfirmed(self) -> None:
        """A connector rejection is not an acknowledgement of command delivery."""

        connector, _ = build_connector(json_handler({"error": "rejected"}, 409))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "unconfirmed"
        assert outcome.error_code == "connector_http_409"

    def test_a_timeout_leaves_the_command_visibly_unconfirmed(self) -> None:
        """A command that times out is never claimed as delivered."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        assert connector.command(TARGET, envelope=self._envelope()).status == (
            "unconfirmed"
        )


class TestResponseBounding:
    def test_an_oversized_response_body_is_truncated_not_buffered(self) -> None:
        """A hostile connector cannot exhaust memory through its reply."""

        def flood(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 500_000)

        seen: list[httpx.Request] = []

        def client_factory(**kwargs: Any) -> httpx.Client:
            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(request)
                return flood(request)

            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        connector = GenericHttpConnector(
            timeout_seconds=5.0,
            max_response_bytes=1_024,
            allow_private_destinations=False,
            resolver=_resolver,
            client_factory=client_factory,
        )

        outcome = connector.test(TARGET)

        # Truncated JSON cannot parse, so the connector refuses to call it ready.
        assert outcome.status == "unsupported"
        assert outcome.error_code == "connector_response_invalid"
