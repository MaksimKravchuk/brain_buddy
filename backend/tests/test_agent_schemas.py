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
    AgentCheckDeliveryRequest,
    AgentConnectionCreatedResponse,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionSigningSecretResponse,
    AgentConnectionUpdateRequest,
    AgentContextItemRequest,
    AgentControlsResponse,
    AgentEventIngestResponse,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentManifestResponse,
    AgentReplyRequest,
    AgentRunCommandResponse,
    AgentRunEventResponse,
    AgentRunResponse,
    AgentRunSummaryResponse,
)

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _card_payload() -> dict[str, object]:
    return {
        "name": "Hermes",
        "version": "1.2.3",
        "description": "A research agent.",
        "protocol_version": "1.0",
        "interface_url": "https://agent.example.com/a2a",
        "streaming": True,
        "push_notifications": False,
        "skills": [{"id": "research", "name": "Research", "description": "Digs."}],
        "auth_schemes_offered": [{"name": "bearer", "kind": "bearer"}],
        "extension_uris": [],
        "fetched_at": NOW,
    }


def _connection_payload() -> dict[str, object]:
    return {
        "id": "agentconn_1",
        "name": "Hermes",
        "agent_address": "https://agent.example.com",
        "auth_scheme": "bearer",
        "auth_header_name": None,
        "status": "ready",
        "stale": False,
        "ready_for_handoff": True,
        "capabilities": {"streaming": True, "push_notifications": False},
        "controls_offered": {"reply": True, "cancel": True},
        "card": _card_payload(),
        "guarantee_tier": "best_effort",
        "tier_disclosure": "Best-effort single start. …",
        "tier_disclosure_url": "https://example.invalid/single-start/v1.md",
        "cancellation_disclosure": "Cancellation depends on the agent …",
        "agent_changed": False,
        "best_effort_acknowledged_at": None,
        "correlation_id_honoured": None,
        "disconnect_reason": None,
        "last_test_error_code": None,
        "last_test_error_detail": None,
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
        "supporting_items": [{"label": "Definition of done", "body": "Cite evidence."}],
        "message_id": "agentrun_1:start",
        "correlation_id": "agentrun_1",
        "destination_interface": "https://agent.example.com/a2a",
        "protocol_version": "1.0",
        "guarantee_tier": "best_effort",
        "tier_disclosure": "Best-effort single start. …",
        "tier_disclosure_url": "https://example.invalid/single-start/v1.md",
        "acknowledgement_required": True,
        "cancellation_disclosure": "Cancellation depends on the agent …",
        "push_callback": {
            "registered": True,
            "url_preview": "https://brainbuddy.example/api/a2a/push/agentrun_1/…",
            "disclosure": "BrainBuddy also gives this agent a private callback address …",
        },
        "external_copy_notice": "This content leaves BrainBuddy.",
        "reauthentication_required": False,
        "parts_preview": ["Research relay security"],
    }


def test_connection_requests_normalize_names_and_enforce_sensitive_constraints() -> (
    None
):
    """Connection writes normalize display names but reject unsafe or stale input."""

    request = AgentConnectionCreateRequest(
        name="  Hermes  ",
        agent_address="https://agent.example.com",
        credential="secret-token",
        current_password="correct horse battery staple",
    )

    assert request.name == "Hermes"
    assert request.auth_scheme == "bearer"

    for payload in (
        {**request.model_dump(), "auth_header_name": "X-API-Key"},
        {**request.model_dump(), "auth_scheme": "oauth2"},
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
            "agent_address": f"https://agent.example.com/{canary} here",
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
            "agent_address": endpoint_value,
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
        # The storage key is deliberately still `endpoint_url` while the request
        # says `agent_address` (data-model.md §1, rollback boundary), so this
        # case parametrises the *field name* as well as the model.
        field = "endpoint_url"
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
        field = "agent_address"
        payload = {
            "name": "Agent",
            "agent_address": "https://agent.example.com/hooks",
            "credential": "credential",
            "current_password": "password",
        }

    assert getattr(model.model_validate(mapping_type(payload)), field) == payload[field]

    payload[field] = "https://agent.example.com/bad path"
    with pytest.raises(ValidationError):
        model.model_validate(mapping_type(payload))


def test_endpoint_sanitization_does_not_strip_unrelated_model_inputs() -> None:
    canary = "unrelated-name-canary"

    with pytest.raises(ValidationError) as excinfo:
        AgentConnectionCreateRequest.model_validate(
            {
                "name": [canary],
                "agent_address": "https://agent.example.com/hooks",
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
    assert dumped["capabilities"] == {"streaming": True, "push_notifications": False}
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


def test_014_FR_001_connection_writes_name_a_scheme_and_never_a_header_name() -> None:
    """The owner picks an authentication scheme; the header name comes from the card.

    AC-002. ``auth_header_name`` is discovery output, not user input: accepting it
    on a request would let an owner point their credential at a header the agent
    never asked for, and the reserved-name check would then be the only thing
    between a typo and a forged ``Authorization``.
    """

    create = AgentConnectionCreateRequest(
        name="Hermes",
        agent_address="https://agent.example.com",
        auth_scheme="api_key",
        credential="secret-token",
        current_password="correct horse battery staple",
    )
    assert create.auth_scheme == "api_key"
    assert not hasattr(create, "auth_header_name")

    update = AgentConnectionUpdateRequest(
        agent_address="https://second.example.com",
        auth_scheme="bearer",
        current_password="correct horse battery staple",
        expected_revision=2,
    )
    assert update.auth_scheme == "bearer"
    assert update.agent_address == "https://second.example.com"

    for rejected in (
        {"auth_header_name": "X-API-Key"},
        {"endpoint_url": "https://agent.example.com"},
        {"auth_scheme": "mtls"},
    ):
        with pytest.raises(ValidationError):
            AgentConnectionUpdateRequest.model_validate(
                {"expected_revision": 2, **rejected}
            )

    # Renaming alone is still a legitimate update; a body naming nothing is not.
    assert AgentConnectionUpdateRequest(name="Hermes II", expected_revision=2)
    with pytest.raises(ValidationError):
        AgentConnectionUpdateRequest.model_validate({"expected_revision": 2})


def test_014_FR_002_connection_reads_carry_discovery_tier_and_closed_error_detail() -> (
    None
):
    """Every connection read states what was discovered and why the last test failed.

    AC-003, AC-005. ``capabilities`` carries only what the card declared;
    ``controls_offered`` is BrainBuddy's own statement about the controls it
    offers on this connection's runs, so the two can never be confused for one
    another.
    """

    connection = AgentConnectionResponse.model_validate(_connection_payload())

    assert connection.agent_address == "https://agent.example.com"
    assert connection.auth_scheme == "bearer"
    assert connection.auth_header_name is None
    assert connection.capabilities.model_dump() == {
        "streaming": True,
        "push_notifications": False,
    }
    assert connection.controls_offered.model_dump() == {"reply": True, "cancel": True}
    assert connection.card is not None
    assert connection.card.interface_url == "https://agent.example.com/a2a"
    assert connection.card.skills[0].name == "Research"
    assert connection.guarantee_tier == "best_effort"
    assert connection.agent_changed is False
    assert connection.best_effort_acknowledged_at is None
    assert connection.correlation_id_honoured is None
    assert connection.disconnect_reason is None

    rate_limited = AgentConnectionResponse.model_validate(
        {
            **_connection_payload(),
            "status": "untested",
            "last_test_error_code": "a2a_rate_limited",
            "last_test_error_detail": {"retry_after_seconds": 30},
        }
    )
    assert rate_limited.last_test_error_detail == {"retry_after_seconds": 30}

    changed = AgentConnectionResponse.model_validate(
        {
            **_connection_payload(),
            "status": "untested",
            "last_test_error_code": "agent_card_changed",
            "agent_changed": True,
        }
    )
    assert changed.agent_changed is True

    superseded = AgentConnectionResponse.model_validate(
        {
            **_connection_payload(),
            "status": "disconnected",
            "disconnect_reason": "superseded_wire_contract",
        }
    )
    assert superseded.disconnect_reason == "superseded_wire_contract"

    with pytest.raises(ValidationError):
        AgentConnectionResponse.model_validate(
            {**_connection_payload(), "disconnect_reason": "because"}
        )


def test_014_FR_003_no_protocol_field_name_reaches_a_client_facing_schema() -> None:
    """ADR-0006 vocabulary: the wire's own field names never leave the backend.

    AC-006. The protocol calls them ``contextId``/``messageId``/``taskId``; the
    product says correlation ID and supporting items. Asserting this on the JSON
    schema rather than on one response keeps a future field from reintroducing
    the vocabulary through a nested model nobody re-reads.
    """

    banned = ("contextid", "context_items", "endpoint_url", "jsonrpc", "a2a_version")
    for model in (
        AgentConnectionCreateRequest,
        AgentConnectionUpdateRequest,
        AgentConnectionResponse,
    ):
        rendered = str(model.model_json_schema()).casefold()
        for word in banned:
            assert word not in rendered, f"{model.__name__} leaks {word!r}"


def test_handoff_schemas_bind_confirmation_to_an_exact_manifest() -> None:
    """Preview content is structured and confirmation accepts only a lowercase SHA-256 token."""

    preview = AgentHandoffPreviewRequest(
        connection_id="agentconn_1",
        supporting_items=[
            AgentContextItemRequest(label="Goal", body="Produce evidence")
        ],
    )
    confirmation = AgentHandoffConfirmRequest(
        **preview.model_dump(), manifest_token="a" * 64, current_password=None
    )
    manifest = AgentManifestResponse.model_validate(_manifest_payload())

    assert preview.include_details is True
    assert confirmation.manifest_token == manifest.token
    assert manifest.supporting_items[0].model_dump() == {
        "label": "Definition of done",
        "body": "Cite evidence.",
    }

    for token in ("a" * 63, "A" * 64, "g" * 64):
        with pytest.raises(ValidationError):
            AgentHandoffConfirmRequest(
                **preview.model_dump(), manifest_token=token, current_password=None
            )


def _run_payload() -> dict[str, object]:
    return {
        "id": "agentrun_1",
        "task_id": "task_1",
        "connection_id": "agentconn_1",
        "agent_name": "Hermes",
        "dispatch_state": "delivery_unconfirmed",
        "dispatch_error_code": None,
        "reported_state": None,
        "run_version": 0,
        "stopped_reporting": False,
        "connection_disconnected": False,
        "reply_pending": False,
        "cancel_requested": False,
        "needs_user": False,
        "primary_state_label": "Queued",
        "content_expired": False,
        "content_expires_at": NOW + timedelta(days=30),
        "reporting_window_seconds": 3600,
        "capabilities": {"reply": True, "cancel": True},
        "guarantee_tier": "best_effort",
        "message_id": "agentrun_1:start",
        "correlation_id": "agentrun_1",
        "agent_task_id": None,
        "exchange_open": True,
        "exchange_state": "queued",
        "exchange_kind": "start",
        "push_registration": "registered",
        "created_at": NOW,
        "revision": 1,
    }


def test_014_FR_005_the_manifest_lists_every_value_that_will_leave() -> None:
    """AC-007. The review is the consent boundary, so it is itemised in full.

    Every field here is something a user could object to before it leaves. The
    protocol's own field names are absent on purpose (ADR-0006): the product
    says supporting items and correlation ID.
    """

    manifest = AgentManifestResponse.model_validate(_manifest_payload())

    assert manifest.supporting_items[0].model_dump() == {
        "label": "Definition of done",
        "body": "Cite evidence.",
    }
    assert manifest.message_id == "agentrun_1:start"
    assert manifest.correlation_id == "agentrun_1"
    assert manifest.destination_interface == "https://agent.example.com/a2a"
    assert manifest.protocol_version == "1.0"
    assert manifest.guarantee_tier == "best_effort"
    assert manifest.tier_disclosure_url
    assert manifest.acknowledgement_required is True
    assert manifest.cancellation_disclosure
    assert manifest.push_callback is not None
    assert manifest.push_callback.registered is True
    assert manifest.push_callback.disclosure
    assert manifest.parts_preview == ["Research relay security"]

    # The bespoke reporting block is gone with the wire that needed it. Checked
    # against the property names rather than the rendered schema, so a prose
    # description mentioning "report" cannot fail it and a real field cannot
    # hide behind one.
    properties = set(AgentManifestResponse.model_json_schema()["properties"])
    for name in (
        "reporting",
        "reporting_instructions",
        "instructions_version",
        "context_items",
        "destination_endpoint",
    ):
        assert name not in properties, f"AgentManifestResponse still has {name!r}"

    # An unregistered callback carries no address and no disclosure: there is
    # nothing to disclose, and a masked address for a callback that does not
    # exist would read as one that does.
    unregistered = AgentManifestResponse.model_validate(
        {
            **_manifest_payload(),
            "push_callback": {
                "registered": False,
                "url_preview": None,
                "disclosure": None,
            },
        }
    )
    assert unregistered.push_callback is not None
    assert unregistered.push_callback.url_preview is None


def test_014_FR_005_the_acknowledgement_is_part_of_the_request_identity() -> None:
    """AC-026. A replay must not be able to drop the acknowledgement.

    It is a field of the confirmation, not a header or a separate call, so the
    canonical request the Idempotency-Key is spent on includes it: a retry that
    quietly omitted it would be a *different* request wearing the same key.
    """

    preview = AgentHandoffPreviewRequest(
        connection_id="agentconn_1",
        supporting_items=[
            AgentContextItemRequest(label="Goal", body="Produce evidence")
        ],
    )
    confirmation = AgentHandoffConfirmRequest(
        **preview.model_dump(),
        manifest_token="a" * 64,
        current_password=None,
        acknowledge_duplicate_risk=True,
    )

    assert confirmation.acknowledge_duplicate_risk is True
    assert "acknowledge_duplicate_risk" in confirmation.model_dump()
    # Defaults to false: an unstated acknowledgement is not an acknowledgement.
    assert (
        AgentHandoffConfirmRequest(
            **preview.model_dump(), manifest_token="a" * 64
        ).acknowledge_duplicate_risk
        is False
    )


def test_014_FR_006_check_delivery_asks_for_nothing_but_the_password() -> None:
    """AC-027, AC-030. Check again re-runs *this* run's own check.

    The request carries no ids and no content: everything it needs is already on
    the run. A body that could name a different run, or carry new content, would
    make "check again" capable of being a second send.
    """

    assert AgentCheckDeliveryRequest().current_password is None
    assert (
        AgentCheckDeliveryRequest(current_password="hunter2").current_password
        == "hunter2"
    )

    assert set(AgentCheckDeliveryRequest.model_json_schema()["properties"]) == {
        "current_password"
    }

    with pytest.raises(ValidationError):
        AgentCheckDeliveryRequest.model_validate({"run_id": "agentrun_2"})


def test_014_FR_006_the_run_projection_states_the_exchange_it_is_waiting_on() -> None:
    """AC-032, AC-034. Queued and Sent are different claims, and stay so.

    A queued exchange has provably not been sent. Collapsing it into `sent`
    would be the one lie this projection exists to prevent.
    """

    run = AgentRunResponse.model_validate(_run_payload())

    assert run.exchange_state == "queued"
    assert run.exchange_open is True
    assert run.exchange_kind == "start"
    assert run.primary_state_label == "Queued"
    assert run.message_id == "agentrun_1:start"
    assert run.correlation_id == "agentrun_1"
    assert run.guarantee_tier == "best_effort"
    assert run.push_registration == "registered"

    restarted = AgentRunResponse.model_validate(
        {
            **_run_payload(),
            "dispatch_state": "not_sent",
            "dispatch_error_code": "restarted_before_send",
            "exchange_state": "none",
            "exchange_open": False,
            "exchange_kind": None,
            "primary_state_label": "Not sent",
        }
    )
    assert restarted.dispatch_error_code == "restarted_before_send"
    assert restarted.exchange_state == "none"

    for invalid in ({"exchange_state": "sending"}, {"push_registration": "maybe"}):
        with pytest.raises(ValidationError):
            AgentRunResponse.model_validate({**_run_payload(), **invalid})

    properties = set(AgentRunResponse.model_json_schema()["properties"])
    for name in ("contextId", "messageId", "taskId", "context_items"):
        assert name not in properties, f"AgentRunResponse leaks {name!r}"


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
        capabilities=AgentControlsResponse(reply=True),
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
        # Present with their "nothing happened" defaults: the compact row must
        # be able to withdraw a control without a second fetch.
        "cancel_outcome": "none",
        "agent_task_missing": False,
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


# --- the observation-side run contract (spec 014, US3) ------------------------


def test_014_FR_009_the_run_contract_carries_every_observation_side_field() -> None:
    """AC-016, AC-018, AC-020, AC-028. What BrainBuddy observed, field by field.

    Each name below is a separate claim a surface renders on its own line, so
    the schema keeps them apart rather than blending them into one status
    string a client would have to re-parse.
    """

    run = AgentRunResponse.model_validate(
        {
            **_run_payload(),
            "dispatch_state": "sent",
            "reported_state": "completed",
            "exchange_state": "closed",
            "exchange_open": False,
            "primary_state_label": "Agent reported complete",
            "agent_task_id": "task-a1",
            "agent_task_missing": False,
            "cancel_outcome": "unsupported",
            "blocked_reason": None,
            "artifacts_summary": [
                {"name": "report.pdf", "media_type": "application/pdf", "kind": "file"}
            ],
            "result_link": "https://agent.example.com/r/1",
            "result_availability": "too_large",
            "last_observed_at": NOW,
            "observation_interval_seconds": 60,
            "identifiers_expired": False,
        }
    )

    assert run.agent_task_id == "task-a1"
    assert run.agent_task_missing is False
    assert run.cancel_outcome == "unsupported"
    assert run.artifacts_summary[0].media_type == "application/pdf"
    assert run.artifacts_summary[0].kind == "file"
    assert run.result_availability == "too_large"
    assert run.last_observed_at == NOW
    assert run.observation_interval_seconds == 60
    assert run.identifiers_expired is False
    # Always false, whatever the agent reported: only syntax is knowable
    # server-side, and syntax cannot answer where a browser lands later.
    assert run.result_link_interactive is False

    blocked = AgentRunResponse.model_validate(
        {
            **_run_payload(),
            "reported_state": "blocked",
            "primary_state_label": "Needs you",
            "blocked_reason": "Agent needs additional authentication",
        }
    )
    assert blocked.blocked_reason == "Agent needs additional authentication"

    for invalid in (
        {"cancel_outcome": "maybe"},
        {"result_availability": "smallish"},
        {"artifacts_summary": [{"name": "a", "media_type": None, "kind": "video"}]},
    ):
        with pytest.raises(ValidationError):
            AgentRunResponse.model_validate({**_run_payload(), **invalid})


def test_014_FR_009_defaults_never_claim_an_observation_that_did_not_happen() -> None:
    """A run nobody has observed says so, rather than defaulting to a state."""

    run = AgentRunResponse.model_validate(_run_payload())

    assert run.agent_task_missing is False
    assert run.cancel_outcome == "none"
    assert run.blocked_reason is None
    assert run.artifacts_summary == []
    assert run.result_availability is None
    assert run.last_observed_at is None
    assert run.identifiers_expired is False
    assert run.observation_interval_seconds == 60


def test_014_FR_013_the_timeline_row_says_why_it_ran_and_what_it_is() -> None:
    """AC-028. A succession row carries both task ids and is not a state change."""

    payload = {
        **_run_payload(),
        "events": [
            {
                "id": "event_1",
                "type": "running",
                "run_version": 2,
                "received_at": NOW,
                "summary": "Working",
                "trigger": "schedule",
                "kind": "observation",
            },
            {
                "id": "event_2",
                "type": "running",
                "run_version": 4,
                "received_at": NOW,
                "summary": "The agent continued this run in a new task",
                "trigger": "command",
                "kind": "task_succession",
                "previous_agent_task_id": "task-a1",
                "new_agent_task_id": "task-b2",
            },
        ],
        "commands": [
            {
                "id": "agentcmd_1",
                "kind": "cancel",
                "delivery": "rejected",
                "outcome_code": "a2a_task_not_cancelable",
                "created_at": NOW,
            }
        ],
    }
    run = AgentRunResponse.model_validate(payload)

    scheduled, succession = run.events
    assert (scheduled.trigger, scheduled.kind) == ("schedule", "observation")
    assert scheduled.previous_agent_task_id is None
    assert (succession.trigger, succession.kind) == ("command", "task_succession")
    assert succession.previous_agent_task_id == "task-a1"
    assert succession.new_agent_task_id == "task-b2"
    assert run.commands[0].delivery == "rejected"
    assert run.commands[0].outcome_code == "a2a_task_not_cancelable"

    default_event = AgentRunEventResponse(
        id="event_3", type="running", run_version=1, received_at=NOW
    )
    assert (default_event.trigger, default_event.kind) == ("schedule", "observation")

    with pytest.raises(ValidationError):
        AgentRunEventResponse.model_validate(
            {
                "id": "event_4",
                "type": "running",
                "run_version": 1,
                "received_at": NOW,
                "trigger": "telepathy",
            }
        )


def test_014_FR_014_the_label_vocabulary_is_closed_and_says_no_more() -> None:
    """FR-014. Every label a surface may render verbatim, and nothing else.

    `Agent no longer reports this run` is in the list and `Complete` is not:
    BrainBuddy never verified the work, and the vocabulary is where that
    promise is kept for every client at once.
    """

    from app.schemas.agents import AGENT_PRIMARY_STATE_LABELS

    assert AGENT_PRIMARY_STATE_LABELS == (
        "Not sent",
        "Queued",
        "Sent",
        "Delivery unconfirmed",
        "Accepted",
        "Running",
        "Needs you",
        "Cancellation requested",
        "Agent reported complete",
        "Failed",
        "Cancelled",
        "Stopped reporting",
        "Agent no longer reports this run",
        "Connection disconnected",
        "Content expired under retention policy",
    )
    assert "Complete" not in AGENT_PRIMARY_STATE_LABELS

    for label in AGENT_PRIMARY_STATE_LABELS:
        run = AgentRunResponse.model_validate(
            {**_run_payload(), "primary_state_label": label}
        )
        assert run.primary_state_label == label

    with pytest.raises(ValidationError):
        AgentRunResponse.model_validate(
            {**_run_payload(), "primary_state_label": "Complete"}
        )


def test_014_FR_013_the_compact_summary_carries_the_tier_and_the_withdrawals() -> None:
    """D-03-S21. The Task list shows the tier in full and the withdrawn control."""

    summary = AgentRunSummaryResponse(
        id="agentrun_1",
        task_id="task_1",
        agent_name="Hermes",
        primary_state_label="Running",
        needs_user=False,
        stopped_reporting=False,
        guarantee_tier="guaranteed",
        cancel_outcome="not_cancelable",
        agent_task_missing=False,
    )

    assert summary.guarantee_tier == "guaranteed"
    assert summary.cancel_outcome == "not_cancelable"
    assert summary.agent_task_missing is False

    bare = AgentRunSummaryResponse(
        id="agentrun_2",
        task_id="task_2",
        agent_name="Hermes",
        primary_state_label="Queued",
        needs_user=False,
        stopped_reporting=False,
    )
    assert bare.guarantee_tier is None
    assert bare.cancel_outcome == "none"
    assert bare.agent_task_missing is False


def test_014_FR_014_no_capability_field_claims_progress_reporting() -> None:
    """`capabilities.progress` is gone: A2A carries no progress figure at all."""

    from app.schemas.agents import AgentCapabilitiesResponse

    assert "progress" not in AgentCapabilitiesResponse.model_fields
    assert "progress" not in AgentControlsResponse.model_fields
