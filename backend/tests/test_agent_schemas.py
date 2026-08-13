"""HTTP schema contracts for the external-agent relay."""

from __future__ import annotations

import traceback
from collections import UserDict
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.errors import register_exception_handlers
from app.modules.agents.authority import validate_endpoint_authority
from app.modules.agents.domain import (
    AGENT_EVENT_ENVELOPE_ADAPTER,
    AgentCompletedEvent,
    _reject_endpoint_unsafe_components,
)
from app.modules.agents.egress import _is_governed_private, _is_publicly_routable
from app.schemas.agents import (
    AgentCapabilitiesResponse,
    AgentConnectionCreatedResponse,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionSigningSecretResponse,
    AgentContextItemRequest,
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

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _connection_payload() -> dict[str, object]:
    return {
        "id": "agentconn_1",
        "name": "Hermes",
        "endpoint_url": "https://agent.example.com/hooks",
        "auth_header_name": "X-Agent-Key",
        "status": "ready",
        "stale": False,
        "ready_for_handoff": True,
        "capabilities": {"progress": True, "reply": True, "cancel": False},
        "last_contact_at": NOW,
        "last_tested_at": NOW,
        "stale_after_seconds": 300,
        "created_at": NOW,
        "revision": 2,
    }


def _reporting_payload() -> dict[str, str]:
    return {
        "callback_url": "https://brainbuddy.example.com/api/agents/events",
        "connection_id": "agentconn_1",
        "connection_header": "X-BrainBuddy-Connection",
        "timestamp_header": "X-BrainBuddy-Timestamp",
        "signature_header": "X-BrainBuddy-Signature",
        "timestamp_format": "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero",
        "signature_algorithm": "hmac-sha256",
        "signing_bytes": "timestamp_bytes + b'.' + raw_body",
        "signature_format": "v1=<lowercase hex>",
        "body_envelope_version": "2026-08-09",
    }


def _manifest_payload() -> dict[str, object]:
    return {
        "token": "a" * 64,
        "run_id": "agentrun_1",
        "task_id": "task_1",
        "connection_id": "agentconn_1",
        "agent_name": "Hermes",
        "title": "Research relay security",
        "details": "Review the signed callback contract.",
        "context_items": [{"label": "Definition of done", "body": "Cite evidence."}],
        "reporting": _reporting_payload(),
        "reporting_instructions": "Sign the exact raw event body.",
        "instructions_version": "v2",
        "protocol_version": "2026-08-09",
        "destination_endpoint": "https://agent.example.com/hooks",
        "external_copy_notice": "This content leaves BrainBuddy.",
        "reauthentication_required": False,
    }


def test_connection_requests_normalize_names_and_enforce_sensitive_constraints() -> (
    None
):
    """Connection writes normalize display names but reject unsafe or stale input."""

    request = AgentConnectionCreateRequest(
        name="  Hermes  ",
        endpoint_url="https://agent.example.com/hooks",
        credential="secret-token",
        current_password="correct horse battery staple",
    )

    assert request.name == "Hermes"
    assert request.auth_header_name == "X-Agent-Key"

    for payload in (
        {**request.model_dump(), "auth_header_name": "Authorization"},
        {**request.model_dump(), "auth_header_name": "X-Agent-Key\r\nX-Evil: yes"},
        {**request.model_dump(), "name": "   "},
    ):
        with pytest.raises(ValidationError):
            AgentConnectionCreateRequest.model_validate(payload)

    with pytest.raises(ValidationError):
        AgentConnectionRotateRequest(
            credential="replacement",
            current_password="password",
            expected_revision=0,
        )
    with pytest.raises(ValidationError):
        AgentConnectionDisconnectRequest(
            current_password="password", expected_revision=0
        )
    with pytest.raises(ValidationError):
        AgentConnectionRotateSigningSecretRequest(
            current_password="password", expected_revision=0
        )


@pytest.mark.parametrize("whitespace", [" ", "\u00a0"])
@pytest.mark.parametrize("position", ["leading", "trailing"])
def test_domain_endpoint_rejects_literal_outer_whitespace(
    whitespace: str, position: str
) -> None:
    endpoint = "https://agent.example.com/hooks"
    value = whitespace + endpoint if position == "leading" else endpoint + whitespace

    with pytest.raises(ValueError, match="not a valid URL"):
        _reject_endpoint_unsafe_components(value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://agent.example.com/space here",
        "https://agent.example.com\\hooks",
        "https://agent.example.com/zero\u200bwidth",
        "https://éxample.com/hooks",
        "https://bad_host.example/hooks",
        "https://agent.example.com/bad%escape",
    ],
)
def test_domain_endpoint_rejects_non_ascii_space_and_backslash(endpoint: str) -> None:
    with pytest.raises(ValueError, match="not a valid URL"):
        _reject_endpoint_unsafe_components(endpoint)


def test_domain_endpoint_accepts_an_ascii_ip_literal() -> None:
    endpoint = "https://93.184.216.34/hooks"

    assert _reject_endpoint_unsafe_components(endpoint) == endpoint


@pytest.mark.parametrize(
    "authority",
    [
        "agent.example.com:",
        "127.1",
        "2130706433",
        "0x7f.0.0.1",
        "0x7f000001",
        "0x7f.1",
        "127.0x0.0.1",
        "999.999.999.999",
        "127.000.000.001",
        f"{'a' * 64}.example.com",
        f"{'a' * 63}.{'b' * 63}.{'c' * 63}.{'d' * 62}",
        "two..labels.example",
        "bad_host.example",
        "-leading.example",
        "trailing-.example",
        "[fe80::1%25eth0]",
    ],
)
def test_domain_endpoint_rejects_invalid_authority_grammar(authority: str) -> None:
    with pytest.raises(ValueError):
        _reject_endpoint_unsafe_components(f"https://{authority}/hooks")


@pytest.mark.parametrize(
    ("authority", "host"),
    [
        ("[2001:0db8::1]", "2001:0db8::1"),
        ("2001:db8::1", "2001:db8::1"),
        ("[93.184.216.34]", "93.184.216.34"),
    ],
)
def test_shared_authority_validator_rejects_noncanonical_literal_forms(
    authority: str, host: str
) -> None:
    with pytest.raises(ValueError):
        validate_endpoint_authority(authority, host)


@pytest.mark.parametrize("model_kind", ["document", "create_request"])
def test_endpoint_validation_error_never_echoes_endpoint_input(
    model_kind: str,
) -> None:
    from app.modules.agents.domain import AgentConnectionDocument

    canary = "rejected-endpoint-canary"
    if model_kind == "document":
        model = AgentConnectionDocument
        payload = {
            "id": "agentconn_1",
            "owner_id": "owner_1",
            "name": "Agent",
            "endpoint_url": f"https://agent.example.com/{canary} here",
            "created_at": NOW,
            "updated_at": NOW,
        }
    else:
        model = AgentConnectionCreateRequest
        payload = {
            "name": "Agent",
            "endpoint_url": f"https://agent.example.com/{canary} here",
            "credential": "credential",
            "current_password": "password",
        }

    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(payload)

    error = excinfo.value
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    surfaces = (
        str(error),
        repr(error),
        repr(error.errors()),
        error.json(),
        rendered,
        repr(error.__cause__),
        repr(error.__context__),
    )
    assert all(canary not in surface for surface in surfaces)


@pytest.mark.parametrize("mapping_type", [UserDict, MappingProxyType])
@pytest.mark.parametrize(
    "endpoint_value",
    [
        ["non-string-endpoint-canary"],
        {"nested": "non-string-endpoint-canary"},
        "https://agent.example.com/non-string-endpoint-canary here",
    ],
)
@pytest.mark.parametrize("model_kind", ["document", "create_request"])
def test_endpoint_validation_sanitizes_any_mapping_and_endpoint_value_type(
    model_kind: str,
    endpoint_value: object,
    mapping_type: type,
) -> None:
    from app.modules.agents.domain import AgentConnectionDocument

    canary = "non-string-endpoint-canary"
    if model_kind == "document":
        model = AgentConnectionDocument
        payload: dict[str, object] = {
            "id": "agentconn_1",
            "owner_id": "owner_1",
            "name": "Agent",
            "endpoint_url": endpoint_value,
            "created_at": NOW,
            "updated_at": NOW,
        }
    else:
        model = AgentConnectionCreateRequest
        payload = {
            "name": "Agent",
            "endpoint_url": endpoint_value,
            "credential": "credential",
            "current_password": "password",
        }

    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(mapping_type(payload))

    error = excinfo.value
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    surfaces = (
        str(error),
        repr(error),
        repr(error.errors()),
        error.json(),
        rendered,
        repr(error.__cause__),
        repr(error.__context__),
    )
    assert all(canary not in surface for surface in surfaces)
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize("mapping_type", [UserDict, MappingProxyType])
@pytest.mark.parametrize("model_kind", ["document", "create_request"])
def test_mapping_payloads_cannot_bypass_endpoint_syntax_validation(
    model_kind: str, mapping_type: type
) -> None:
    from app.modules.agents.domain import AgentConnectionDocument

    if model_kind == "document":
        model = AgentConnectionDocument
        payload: dict[str, object] = {
            "id": "agentconn_1",
            "owner_id": "owner_1",
            "name": "Agent",
            "endpoint_url": "https://agent.example.com/hooks",
            "created_at": NOW,
            "updated_at": NOW,
        }
    else:
        model = AgentConnectionCreateRequest
        payload = {
            "name": "Agent",
            "endpoint_url": "https://agent.example.com/hooks",
            "credential": "credential",
            "current_password": "password",
        }

    assert (
        model.model_validate(mapping_type(payload)).endpoint_url
        == payload["endpoint_url"]
    )

    payload["endpoint_url"] = "https://agent.example.com/bad path"
    with pytest.raises(ValidationError):
        model.model_validate(mapping_type(payload))


def test_endpoint_sanitization_does_not_strip_unrelated_model_inputs() -> None:
    canary = "unrelated-name-canary"

    with pytest.raises(ValidationError) as excinfo:
        AgentConnectionCreateRequest.model_validate(
            {
                "name": [canary],
                "endpoint_url": "https://agent.example.com/hooks",
                "credential": "credential",
                "current_password": "password",
            }
        )

    assert canary in repr(excinfo.value.errors())


def test_public_validation_response_serializes_sanitized_endpoint_errors() -> None:
    canary = "public-endpoint-canary"
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/connections")
    def create_connection(payload: AgentConnectionCreateRequest) -> None:
        return None

    response = TestClient(app).post(
        "/connections",
        json={
            "name": "Agent",
            "endpoint_url": {"nested": canary},
            "credential": "credential",
            "current_password": "password",
        },
    )

    assert response.status_code == 422
    assert response.json()["message"] == "Request validation failed."
    assert canary not in response.text


@pytest.mark.parametrize("secret_field", ["credential", "current_password"])
def test_public_validation_response_never_reflects_secret_inputs(
    secret_field: str,
) -> None:
    canary = f"secret-validation-canary-{secret_field}"
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/connections")
    def create_connection(payload: AgentConnectionCreateRequest) -> None:
        return None

    request = {
        "name": "Agent",
        "endpoint_url": "https://agent.example.com/hooks",
        "credential": "credential",
        "current_password": "password",
    }
    request[secret_field] = canary * 500
    response = TestClient(app).post("/connections", json=request)

    assert response.status_code == 422
    assert canary not in response.text
    assert all("input" not in error for error in response.json()["detail"])


def test_connection_responses_cannot_serialize_saved_credentials() -> None:
    """Ordinary responses reject credential fields while issue responses expose one secret."""

    connection = AgentConnectionResponse.model_validate(_connection_payload())
    dumped = connection.model_dump(mode="json")

    assert dumped["status"] == "ready"
    assert dumped["capabilities"] == {"progress": True, "reply": True, "cancel": False}
    assert "credential" not in dumped
    assert "inbound_signing_secret" not in dumped

    with pytest.raises(ValidationError):
        AgentConnectionResponse.model_validate(
            {**_connection_payload(), "credential": "must-not-leak"}
        )

    for response_type in (
        AgentConnectionCreatedResponse,
        AgentConnectionSigningSecretResponse,
    ):
        issued = response_type.model_validate(
            {**_connection_payload(), "inbound_signing_secret": "shown-once"}
        )
        assert issued.inbound_signing_secret == "shown-once"
        assert "credential" not in issued.model_dump()


def test_handoff_schemas_bind_confirmation_to_an_exact_manifest() -> None:
    """Preview content is structured and confirmation accepts only a lowercase SHA-256 token."""

    preview = AgentHandoffPreviewRequest(
        connection_id="agentconn_1",
        context_items=[AgentContextItemRequest(label="Goal", body="Produce evidence")],
    )
    confirmation = AgentHandoffConfirmRequest(
        **preview.model_dump(), manifest_token="a" * 64, current_password=None
    )
    manifest = AgentManifestResponse.model_validate(_manifest_payload())

    assert preview.include_details is True
    assert confirmation.manifest_token == manifest.token
    assert manifest.context_items[0].model_dump() == {
        "label": "Definition of done",
        "body": "Cite evidence.",
    }
    assert manifest.reporting == AgentReportingContractResponse.model_validate(
        _reporting_payload()
    )

    for token in ("a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ValidationError):
            AgentHandoffConfirmRequest(
                **preview.model_dump(), manifest_token=token, current_password=None
            )


def test_run_projection_keeps_reported_derived_and_requested_state_separate() -> None:
    """A serialized run preserves connector facts, derived conditions, and pending commands."""

    event = AgentRunEventResponse(
        id="event_1",
        type="blocked",
        run_version=3,
        received_at=NOW,
        summary="Need scope",
    )
    command = AgentRunCommandResponse(
        id="command_1",
        kind="reply",
        body="Use the exact PR head.",
        delivery="unconfirmed",
        created_at=NOW,
    )
    run = AgentRunResponse(
        id="agentrun_1",
        task_id="task_1",
        connection_id="agentconn_1",
        agent_name="Hermes",
        dispatch_state="sent",
        reported_state="blocked",
        run_version=3,
        stopped_reporting=True,
        connection_disconnected=False,
        reply_pending=True,
        cancel_requested=False,
        needs_user=True,
        primary_state_label="Stopped reporting",
        question_text="Need scope",
        content_expired=False,
        content_expires_at=NOW + timedelta(days=30),
        reporting_window_seconds=300,
        capabilities=AgentCapabilitiesResponse(progress=True, reply=True),
        manifest=AgentManifestResponse.model_validate(_manifest_payload()),
        events=[event],
        commands=[command],
        created_at=NOW,
        revision=4,
    )

    dumped = run.model_dump(mode="json")
    assert dumped["reported_state"] == "blocked"
    assert dumped["stopped_reporting"] is True
    assert dumped["reply_pending"] is True
    assert dumped["commands"][0]["delivery"] == "unconfirmed"
    assert dumped["result_link_interactive"] is False

    summary = AgentRunSummaryResponse(
        id=run.id,
        task_id=run.task_id,
        agent_name=run.agent_name,
        primary_state_label=run.primary_state_label,
        needs_user=run.needs_user,
        stopped_reporting=run.stopped_reporting,
    )
    assert summary.model_dump(exclude_none=True) == {
        "id": "agentrun_1",
        "task_id": "task_1",
        "agent_name": "Hermes",
        "primary_state_label": "Stopped reporting",
        "needs_user": True,
        "stopped_reporting": True,
    }
    assert AgentEventIngestResponse(accepted=True, run_version=3).model_dump() == {
        "accepted": True,
        "run_version": 3,
    }


def test_reply_schema_rejects_empty_messages_and_stale_revisions() -> None:
    """Reply commands require both content and a positive optimistic-lock revision."""

    assert (
        AgentReplyRequest(message="Continue", expected_revision=2).message == "Continue"
    )

    for payload in (
        {"message": "", "expected_revision": 2},
        {"message": "Continue", "expected_revision": 0},
        {"message": "Continue", "expected_revision": 2, "unexpected": True},
    ):
        with pytest.raises(ValidationError):
            AgentReplyRequest.model_validate(payload)


def test_signed_event_envelopes_reject_blank_identity_and_resultless_completion() -> (
    None
):
    """Authenticated event bodies still require nonblank identity and completion evidence."""

    base = {
        "protocol_version": "2026-08-09",
        "connection_id": "agentconn_1",
        "event_id": "event_1",
        "run_id": "agentrun_1",
        "run_version": 1,
    }

    with pytest.raises(ValidationError, match="must not be blank"):
        AGENT_EVENT_ENVELOPE_ADAPTER.validate_python(
            {**base, "protocol_version": "   ", "type": "accepted"}
        )
    with pytest.raises(
        ValidationError, match="completed requires result or result_link"
    ):
        AGENT_EVENT_ENVELOPE_ADAPTER.validate_python({**base, "type": "completed"})

    completed = AGENT_EVENT_ENVELOPE_ADAPTER.validate_python(
        {**base, "type": "completed", "result": "Coverage restored"}
    )
    assert isinstance(completed, AgentCompletedEvent)
    assert completed.result == "Coverage restored"


def test_invalid_resolver_answers_fail_both_network_class_predicates() -> None:
    """Malformed DNS answers are neither public nor policy-governed private addresses."""

    assert _is_publicly_routable("not-an-ip") is False
    assert _is_governed_private("not-an-ip") is False
