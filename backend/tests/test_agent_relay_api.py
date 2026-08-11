"""HTTP contract for the external-agent relay.

Drives the real FastAPI app end to end: session auth, the rollout flag, owner
isolation across two real accounts, re-authentication, idempotency headers, and
the signed inbound-event endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.api.agents import MAX_EVENT_BODY_BYTES, _bounded_event_body
from app.container import Container
from app.core import get_config
from app.main import create_app
from app.modules.agents import service as agent_service_module
from app.modules.agents.connector import (
    ConnectorCommandOutcome,
    ConnectorStartOutcome,
    ConnectorTarget,
    ConnectorTestOutcome,
)
from app.modules.agents.domain import PROTOCOL_VERSION, AgentCapabilities
from app.schemas.auth import Invite
from app.utils.time import utcnow

from .conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

SECOND_EMAIL = "second-relay@example.com"
SECOND_PASSWORD = "another-horse-battery-staple"
ENDPOINT = "https://agent.example.com/hooks"


class FakeConnector:
    def __init__(self) -> None:
        self.test_outcome = ConnectorTestOutcome(
            "ready", AgentCapabilities(progress=True, reply=True, cancel=True)
        )
        self.start_outcome = ConnectorStartOutcome("sent")
        self.command_outcome = ConnectorCommandOutcome("confirmed")
        self.starts: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []

    def test(self, target: ConnectorTarget) -> ConnectorTestOutcome:
        return self.test_outcome

    def start(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorStartOutcome:
        self.starts.append(envelope)
        return self.start_outcome

    def command(
        self, target: ConnectorTarget, *, envelope: dict[str, Any]
    ) -> ConnectorCommandOutcome:
        self.commands.append(envelope)
        return self.command_outcome


def _resolver(host: str, port: int) -> list[str]:
    return {"agent.example.com": ["93.184.216.34"]}[host]


@pytest.fixture
def relay_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, TestClient, FakeConnector, Container], None, None]:
    """Two signed-in clients on one app, with the relay flag on and no network."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "relay-data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv(
        "BRAIN_BUDDY_FEATURE_FLAGS", "voice_brain_dump=on,external_agent_relay=on"
    )
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container

    connector = FakeConnector()
    container.agent_relay_service.connector = connector
    container.agent_relay_service._resolver = _resolver

    for code in ("invite_relay_a", "invite_relay_b"):
        container.invite_repo.create(Invite(code=code, created_at=utcnow()))

    first = TestClient(app)
    assert (
        first.post(
            "/api/auth/signup",
            json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
                "invite_code": "invite_relay_a",
            },
        ).status_code
        == 201
    )
    second = TestClient(app)
    assert (
        second.post(
            "/api/auth/signup",
            json={
                "email": SECOND_EMAIL,
                "password": SECOND_PASSWORD,
                "invite_code": "invite_relay_b",
            },
        ).status_code
        == 201
    )

    yield first, second, connector, container
    first.close()
    second.close()
    get_config.cache_clear()


@pytest.fixture
def client(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> TestClient:
    return relay_app[0]


@pytest.fixture
def other_client(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> TestClient:
    return relay_app[1]


@pytest.fixture
def connector(
    relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
) -> FakeConnector:
    return relay_app[2]


def create_connection(client: TestClient, *, key: str = "k-create") -> dict[str, Any]:
    response = client.post(
        "/api/agent-connections",
        headers={"Idempotency-Key": key},
        json={
            "name": "Hermes",
            "endpoint_url": ENDPOINT,
            "credential": "Bearer super-secret-token",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_task(client: TestClient, title: str = "Draft the migration plan") -> str:
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": f"task-{title}"},
        json={"title": title, "details": "Cover rollback.", "state": "next"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def hand_off(
    client: TestClient, connection_id: str, task_id: str, *, key: str = "k-dispatch"
) -> dict[str, Any]:
    preview = client.post(
        f"/api/tasks/{task_id}/agent-runs/preview",
        json={"connection_id": connection_id},
    )
    assert preview.status_code == 200, preview.text
    response = client.post(
        f"/api/tasks/{task_id}/agent-runs",
        headers={"Idempotency-Key": key},
        json={
            "connection_id": connection_id,
            "manifest_token": preview.json()["token"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestAuthAndRollout:
    def test_every_owner_route_requires_a_session(
        self, anonymous_api_client: TestClient
    ) -> None:
        """An unauthenticated caller reaches nothing."""

        for method, path in (
            ("get", "/api/agent-connections"),
            ("post", "/api/agent-connections"),
            ("get", "/api/agent-runs/agentrun_1"),
            ("post", "/api/agent-runs/agentrun_1/cancel"),
            ("get", "/api/tasks/task_1/agent-runs"),
            ("post", "/api/tasks/task_1/agent-runs/preview"),
        ):
            call = getattr(anonymous_api_client, method)
            response = call(path) if method == "get" else call(path, json={})
            assert response.status_code == 401, f"{method} {path}: {response.text}"

    def test_the_routes_are_absent_while_the_rollout_flag_is_off(
        self, api_client: TestClient
    ) -> None:
        """ADR-0008: default OFF means the feature is simply not there."""

        response = api_client.get("/api/agent-connections")

        assert response.status_code == 404

    def test_the_effective_flag_is_reported_to_the_client(
        self, client: TestClient
    ) -> None:
        """Clients gate their UI on the same server-owned flag."""

        response = client.get("/api/auth/me")

        assert response.json()["feature_flags"]["external_agent_relay"] is True

    def test_responses_carry_a_correlation_id(self, client: TestClient) -> None:
        """FR-017: every response is traceable."""

        response = client.get("/api/agent-connections")

        assert response.headers["X-Correlation-ID"]


class TestConnectionRoutes:
    def test_creating_a_connection_returns_the_secret_once_and_never_again(
        self, client: TestClient
    ) -> None:
        """AC-019: the credential is never a response field."""

        created = create_connection(client)

        assert created["status"] == "untested"
        assert created["inbound_signing_secret"]
        assert "credential" not in created

        listed = client.get("/api/agent-connections").json()
        assert "inbound_signing_secret" not in listed[0]
        assert "super-secret-token" not in json.dumps(listed)

    def test_creating_without_the_password_is_rejected(
        self, client: TestClient
    ) -> None:
        """FR-003: registration is a re-authenticated action."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "endpoint_url": ENDPOINT,
                "credential": "Bearer token",
            },
        )

        assert response.status_code == 422

    def test_creating_with_a_wrong_password_is_forbidden(
        self, client: TestClient
    ) -> None:
        """A stolen session alone cannot register a destination."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "endpoint_url": ENDPOINT,
                "credential": "Bearer token",
                "current_password": "not-the-password",
            },
        )

        assert response.status_code == 403
        assert client.get("/api/agent-connections").json() == []

    def test_creating_with_a_whitespace_only_name_is_rejected_before_action(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "blank-name"},
            json={
                "name": "   ",
                "endpoint_url": ENDPOINT,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422
        assert client.get("/api/agent-connections").json() == []
        assert connector.starts == []
        assert connector.commands == []

    @pytest.mark.parametrize(
        "auth_header_name",
        ["Authorization", "content-type", "X Bad"],
    )
    def test_creating_with_an_owned_or_malformed_auth_header_is_rejected_before_action(
        self,
        client: TestClient,
        connector: FakeConnector,
        auth_header_name: str,
    ) -> None:
        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": f"bad-header-{auth_header_name}"},
            json={
                "name": "Hermes",
                "endpoint_url": ENDPOINT,
                "auth_header_name": auth_header_name,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422
        assert client.get("/api/agent-connections").json() == []
        assert connector.starts == []
        assert connector.commands == []

    def test_creating_without_an_idempotency_key_is_rejected(
        self, client: TestClient
    ) -> None:
        """Every mutation carries a key, as elsewhere in the API."""

        response = client.post(
            "/api/agent-connections",
            json={
                "name": "Hermes",
                "endpoint_url": ENDPOINT,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://127.0.0.1/hooks",
            "https://169.254.169.254/latest",
            "http://agent.example.com/hooks",
        ],
    )
    def test_an_unsafe_destination_is_refused(
        self, client: TestClient, endpoint: str
    ) -> None:
        """AC-005 over HTTP."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k1"},
            json={
                "name": "Hermes",
                "endpoint_url": endpoint,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 400
        assert client.get("/api/agent-connections").json() == []

    def test_testing_a_connection_reports_readiness_and_capabilities(
        self, client: TestClient
    ) -> None:
        """AC-001 over HTTP."""

        created = create_connection(client)

        response = client.post(f"/api/agent-connections/{created['id']}/test")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["ready_for_handoff"] is True
        assert body["capabilities"] == {
            "progress": True,
            "reply": True,
            "cancel": True,
        }

    def test_another_owner_cannot_see_or_touch_the_connection(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """Owner isolation over HTTP."""

        created = create_connection(client)

        assert other_client.get("/api/agent-connections").json() == []
        assert (
            other_client.get(f"/api/agent-connections/{created['id']}").status_code
            == 404
        )
        assert (
            other_client.post(
                f"/api/agent-connections/{created['id']}/test"
            ).status_code
            == 404
        )

    def test_disconnecting_requires_the_password_and_the_current_revision(
        self, client: TestClient
    ) -> None:
        """AC-018 over HTTP."""

        created = create_connection(client)

        wrong_password = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-1"},
            json={"current_password": "nope", "expected_revision": created["revision"]},
        )
        assert wrong_password.status_code == 403

        stale = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-2"},
            json={"current_password": TEST_USER_PASSWORD, "expected_revision": 99},
        )
        assert stale.status_code == 409

        ok = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "k-dis-3"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "disconnected"


class TestSigningSecretRotationRoute:
    """Recovering a lost create response over HTTP.

    The create response carries the signing secret exactly once. When it is
    lost, this route is the only way back, so it has to be as guarded as
    registration itself and as retry-safe as any other relay command.
    """

    def rotate(
        self,
        client: TestClient,
        connection_id: str,
        *,
        key: str = "k-sign",
        revision: int = 1,
        password: str = TEST_USER_PASSWORD,
    ) -> Any:
        return client.post(
            f"/api/agent-connections/{connection_id}/signing-secret",
            headers={"Idempotency-Key": key},
            json={"current_password": password, "expected_revision": revision},
        )

    def test_rotation_returns_a_new_secret_the_agent_can_sign_with(
        self, client: TestClient
    ) -> None:
        """The replacement is usable immediately and the old one is not."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        response = self.rotate(client, created["id"], revision=current["revision"])

        assert response.status_code == 200, response.text
        replacement = response.json()["inbound_signing_secret"]
        assert replacement and replacement != created["inbound_signing_secret"]

        stale = TestEventIngestRoutes()._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_old",
                "run_id": run["id"],
                "type": "running",
                "run_version": 1,
            },
        )
        assert stale.status_code == 403

        fresh = TestEventIngestRoutes()._emit(
            client,
            connection_id=created["id"],
            secret=replacement,
            payload={
                "event_id": "evt_new",
                "run_id": run["id"],
                "type": "running",
                "run_version": 1,
            },
        )
        assert fresh.status_code == 202, fresh.text

    def test_replaying_the_key_returns_the_same_secret_not_a_blank_success(
        self, client: TestClient
    ) -> None:
        """A retried request recovers the value; it never answers with nothing."""

        created = create_connection(client)
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        first = self.rotate(client, created["id"], revision=current["revision"])
        replay = self.rotate(client, created["id"], revision=current["revision"])

        assert replay.status_code == 200, replay.text
        assert replay.json()["inbound_signing_secret"]
        assert (
            replay.json()["inbound_signing_secret"]
            == first.json()["inbound_signing_secret"]
        )

    def test_replaying_a_superseded_key_conflicts_instead_of_handing_back_a_dead_secret(
        self, client: TestClient
    ) -> None:
        """Once a newer rotation lands, the older receipt is not an answer."""

        created = create_connection(client)
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        first = self.rotate(
            client, created["id"], key="k-a", revision=current["revision"]
        )
        after = client.get(f"/api/agent-connections/{created['id']}").json()
        self.rotate(client, created["id"], key="k-b", revision=after["revision"])

        replay = self.rotate(
            client, created["id"], key="k-a", revision=current["revision"]
        )

        assert replay.status_code == 409, replay.text
        assert first.json()["inbound_signing_secret"] not in replay.text

    def test_rotation_requires_the_password_and_the_current_revision(
        self, client: TestClient
    ) -> None:
        """Same ceremony as registration and disconnect."""

        created = create_connection(client)
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        assert (
            self.rotate(
                client,
                created["id"],
                key="k-a",
                revision=current["revision"],
                password="nope",
            ).status_code
            == 403
        )
        assert (
            self.rotate(client, created["id"], key="k-b", revision=99).status_code
            == 409
        )

    def test_rotation_requires_an_idempotency_key(self, client: TestClient) -> None:
        """Every relay mutation carries a key."""

        created = create_connection(client)

        response = client.post(
            f"/api/agent-connections/{created['id']}/signing-secret",
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert response.status_code == 400

    def test_another_owner_cannot_rotate_the_secret(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """Owner isolation, answered as a plain 404."""

        created = create_connection(client)

        response = other_client.post(
            f"/api/agent-connections/{created['id']}/signing-secret",
            headers={"Idempotency-Key": "k-sign"},
            json={
                "current_password": SECOND_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert response.status_code == 404

    def test_no_ordinary_read_carries_the_rotated_secret(
        self, client: TestClient
    ) -> None:
        """FR-003: only this response ever holds it."""

        created = create_connection(client)
        current = client.get(f"/api/agent-connections/{created['id']}").json()
        secret = self.rotate(
            client, created["id"], revision=current["revision"]
        ).json()["inbound_signing_secret"]

        detail = client.get(f"/api/agent-connections/{created['id']}").json()
        listed = client.get("/api/agent-connections").json()

        assert "inbound_signing_secret" not in detail
        assert secret not in json.dumps(listed)

    def test_the_route_is_absent_while_the_rollout_flag_is_off(
        self, api_client: TestClient
    ) -> None:
        """ADR-0008: the flag gates this owner route like every other one."""

        response = api_client.post(
            "/api/agent-connections/agentconn_1/signing-secret",
            headers={"Idempotency-Key": "k-sign"},
            json={"current_password": TEST_USER_PASSWORD, "expected_revision": 1},
        )

        assert response.status_code == 404


class TestHandOffRoutes:
    def test_a_reviewed_hand_off_dispatches_exactly_once(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        """AC-008 / AC-009 over HTTP."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        run = hand_off(client, created["id"], task_id)

        assert run["dispatch_state"] == "sent"
        assert run["primary_state_label"] == "Sent"
        assert len(connector.starts) == 1

        listed = client.get(f"/api/tasks/{task_id}/agent-runs").json()
        assert len(listed) == 1

    def test_the_preview_discloses_exactly_what_will_be_sent(
        self, client: TestClient
    ) -> None:
        """AC-006 over HTTP."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        preview = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={
                "connection_id": created["id"],
                "context_items": [{"label": "Runbook", "body": "Step one"}],
            },
        ).json()

        assert preview["title"] == "Draft the migration plan"
        assert preview["details"] == "Cover rollback."
        assert preview["context_items"] == [{"label": "Runbook", "body": "Step one"}]
        assert preview["destination_endpoint"] == ENDPOINT
        assert preview["external_copy_notice"]

    def test_handing_off_another_owners_task_is_refused(
        self, client: TestClient, other_client: TestClient, connector: FakeConnector
    ) -> None:
        """Cross-owner hand-off fails before any content is sent."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)

        response = other_client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 404
        assert connector.starts == []

    def test_an_untested_connection_refuses_the_hand_off(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        """AC-010 over HTTP."""

        created = create_connection(client)
        task_id = create_task(client)

        response = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )

        assert response.status_code == 400
        assert connector.starts == []


class TestEventIngestRoutes:
    def _emit(
        self,
        client: TestClient,
        *,
        connection_id: str,
        secret: str,
        payload: dict[str, Any],
        timestamp: int | None = None,
    ) -> Any:
        # The strict envelope binds the protocol version and the connection
        # inside the signed body; tests state the interesting fields and get
        # those two for free.
        envelope = {
            "protocol_version": PROTOCOL_VERSION,
            "connection_id": connection_id,
            **payload,
        }
        body = json.dumps(envelope).encode("utf-8")
        stamp = (
            timestamp
            if timestamp is not None
            else int(datetime.now(tz=UTC).timestamp())
        )
        signature = hmac.new(
            secret.encode("utf-8"), f"{stamp}.".encode() + body, hashlib.sha256
        ).hexdigest()
        return client.post(
            "/api/agent-events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-BrainBuddy-Connection": connection_id,
                "X-BrainBuddy-Timestamp": str(stamp),
                "X-BrainBuddy-Signature": f"v1={signature}",
            },
        )

    def test_emitted_reporting_contract_produces_an_accepted_callback(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        reporting = connector.starts[-1]["reporting"]
        assert reporting["signature_algorithm"] == "hmac-sha256"
        assert reporting["signing_bytes"] == "timestamp_bytes + b'.' + raw_body"
        assert reporting["signature_format"] == "v1=<lowercase hex>"

        body = json.dumps(
            {
                "protocol_version": reporting["body_envelope_version"],
                "connection_id": reporting["connection_id"],
                "event_id": "evt_contract_vector",
                "run_id": run["id"],
                "type": "running",
                "run_version": 1,
                "progress": "Using emitted contract",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp_bytes = str(int(datetime.now(tz=UTC).timestamp())).encode("ascii")
        digest = hmac.new(
            created["inbound_signing_secret"].encode("utf-8"),
            timestamp_bytes + b"." + body,
            hashlib.sha256,
        ).hexdigest()

        response = client.post(
            reporting["callback_url"],
            content=body,
            headers={
                "Content-Type": "application/json",
                reporting["connection_header"]: reporting["connection_id"],
                reporting["timestamp_header"]: timestamp_bytes.decode("ascii"),
                reporting["signature_header"]: f"v1={digest}",
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": True, "run_version": 1}

    def test_reporting_v2_accepts_a_fixed_external_golden_vector(
        self,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Freeze every signed byte so producer and verifier cannot drift together."""

        client, _, connector, container = relay_app
        fixed_secret = "golden-vector-signing-secret-v2"
        fixed_timestamp = b"1786320000"
        fixed_now = datetime(2026, 8, 10, tzinfo=UTC)
        fixed_body = (
            b'{"protocol_version":"2026-08-09","connection_id":"agentconn_golden_vector",'
            b'"event_id":"evt_golden_vector","run_id":"agentrun_golden_vector",'
            b'"type":"running","run_version":1,"progress":"Fixed golden vector"}'
        )
        # Generated independently with OpenSSL over
        # b"1786320000." + fixed_body using the fixed secret above.
        expected_digest = (
            "8464ec9e75dd88ff92f85bad0d5bbe4" "68ae2aa09826d9894cd06feb9064c7700"
        )
        original_generate_id = agent_service_module.generate_id

        def fixed_relay_id(prefix: str) -> str:
            if prefix == "agentconn":
                return "agentconn_golden_vector"
            if prefix == "agentrun":
                return "agentrun_golden_vector"
            return original_generate_id(prefix)

        monkeypatch.setattr(agent_service_module, "generate_id", fixed_relay_id)
        monkeypatch.setattr(
            agent_service_module.secrets,
            "token_urlsafe",
            lambda _bytes: fixed_secret,
        )
        container.agent_relay_service._now = lambda: fixed_now

        created = create_connection(client, key="golden-create")
        assert created["id"] == "agentconn_golden_vector"
        assert created["inbound_signing_secret"] == fixed_secret
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id, key="golden-handoff")
        assert run["id"] == "agentrun_golden_vector"

        reporting = connector.starts[-1]["reporting"]
        assert reporting["instructions_version"] == "v2"
        assert reporting["body_envelope_version"] == "2026-08-09"
        assert reporting["signature_algorithm"] == "hmac-sha256"
        assert reporting["signing_bytes"] == "timestamp_bytes + b'.' + raw_body"
        assert reporting["signature_format"] == "v1=<lowercase hex>"
        assert reporting["connection_id"] == "agentconn_golden_vector"

        response = client.post(
            reporting["callback_url"],
            content=fixed_body,
            headers={
                "Content-Type": "application/json",
                reporting["connection_header"]: "agentconn_golden_vector",
                reporting["timestamp_header"]: fixed_timestamp.decode("ascii"),
                reporting["signature_header"]: f"v1={expected_digest}",
            },
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": True, "run_version": 1}

    def test_a_signed_event_updates_the_run(self, client: TestClient) -> None:
        """AC-011 over HTTP, from an unauthenticated connector."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        response = self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_1",
                "run_id": run["id"],
                "type": "running",
                "run_version": 1,
                "progress": "Cloning the repo",
            },
        )

        assert response.status_code == 202, response.text
        projected = client.get(f"/api/agent-runs/{run['id']}").json()
        assert projected["reported_state"] == "running"
        assert projected["progress_text"] == "Cloning the repo"
        assert projected["primary_state_label"] == "Running"

    def test_an_unsigned_event_is_refused_and_changes_nothing(
        self, client: TestClient
    ) -> None:
        """SC-003 over HTTP."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        response = client.post(
            "/api/agent-events",
            json={
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": created["id"],
                "event_id": "evt_1",
                "run_id": run["id"],
                "type": "completed",
                "run_version": 1,
                "result": "Done.",
            },
            headers={"X-BrainBuddy-Connection": created["id"]},
        )

        assert response.status_code in (400, 401, 403)
        assert (
            client.get(f"/api/agent-runs/{run['id']}").json()["reported_state"] is None
        )

    def test_a_wrongly_signed_event_is_refused(self, client: TestClient) -> None:
        """A forged signature never moves the projection."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        response = self._emit(
            client,
            connection_id=created["id"],
            secret="not-the-secret",
            payload={
                "event_id": "evt_1",
                "run_id": run["id"],
                "type": "completed",
                "run_version": 1,
                "result": "Done.",
            },
        )

        assert response.status_code == 403
        assert (
            client.get(f"/api/agent-runs/{run['id']}").json()["reported_state"] is None
        )

    def test_the_rejection_body_never_explains_which_check_failed(
        self, client: TestClient
    ) -> None:
        """A prober learns nothing about connections or runs from the error."""

        created = create_connection(client)

        response = self._emit(
            client,
            connection_id=created["id"],
            secret="not-the-secret",
            payload={
                "event_id": "evt_1",
                "run_id": "agentrun_whatever",
                "type": "running",
                "run_version": 1,
            },
        )

        assert "signature" not in response.text.lower()
        assert "agentrun_whatever" not in response.text

    def test_a_blocked_event_lets_the_owner_reply(self, client: TestClient) -> None:
        """AC-012 over HTTP."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_1",
                "run_id": run["id"],
                "type": "blocked",
                "run_version": 1,
                "question": "Which environment?",
            },
        )

        current = client.get(f"/api/agent-runs/{run['id']}").json()
        response = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "k-reply"},
            json={
                "message": "Use staging.",
                "expected_revision": current["revision"],
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["needs_user"] is True
        assert body["question_text"] == "Which environment?"
        assert any(command["kind"] == "reply" for command in body["commands"])

    def test_a_stale_question_revision_returns_409_before_reply_delivery(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        base = {
            "run_id": run["id"],
            "type": "blocked",
            "question": "Which environment?",
        }
        self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={**base, "event_id": "evt_1", "run_version": 1},
        )
        stale_revision = client.get(f"/api/agent-runs/{run['id']}").json()["revision"]
        self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                **base,
                "event_id": "evt_2",
                "run_version": 2,
                "question": "Which region?",
            },
        )

        response = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "k-stale-reply"},
            json={"message": "Use staging.", "expected_revision": stale_revision},
        )

        assert response.status_code == 409, response.text
        assert connector.commands == []

    # --- bounded ingestion on an unauthenticated route ----------------------

    def test_a_declared_oversize_body_is_refused_before_it_is_buffered(
        self, client: TestClient
    ) -> None:
        """A caller announcing more than the cap is refused on the header alone.

        This route takes no session, so an attacker can post to it freely.
        Reading the body first would let a single declared-huge request pull
        arbitrary bytes into memory before anyone checks the size.
        """

        consumed = 0

        def body() -> Generator[bytes, None, None]:
            nonlocal consumed
            for _ in range(40):
                consumed += 8_192
                yield b"x" * 8_192

        response = client.post(
            "/api/agent-events",
            content=body(),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(40 * 8_192),
                "X-BrainBuddy-Connection": "agentconn_probe",
                "X-BrainBuddy-Timestamp": "1",
                "X-BrainBuddy-Signature": "v1=deadbeef",
            },
        )

        assert response.status_code == 413, response.text
        assert consumed == 0, "the declared size must be refused before buffering"

    def test_an_undeclared_oversize_body_is_still_refused(
        self, client: TestClient
    ) -> None:
        """A chunked caller that declares no length is bounded all the same."""

        def body() -> Generator[bytes, None, None]:
            for _ in range(40):
                yield b"x" * 8_192

        response = client.post(
            "/api/agent-events",
            content=body(),
            headers={
                "Content-Type": "application/json",
                "X-BrainBuddy-Connection": "agentconn_probe",
                "X-BrainBuddy-Timestamp": "1",
                "X-BrainBuddy-Signature": "v1=deadbeef",
            },
        )

        assert response.status_code == 413, response.text

    def test_a_body_of_exactly_the_cap_is_not_refused_for_size(
        self, client: TestClient
    ) -> None:
        """The boundary belongs to the accepted side; the signature decides."""

        response = client.post(
            "/api/agent-events",
            content=b"x" * MAX_EVENT_BODY_BYTES,
            headers={
                "Content-Type": "application/json",
                "X-BrainBuddy-Connection": "agentconn_probe",
                "X-BrainBuddy-Timestamp": "1",
                "X-BrainBuddy-Signature": "v1=deadbeef",
            },
        )

        assert response.status_code == 403, response.text

    @pytest.mark.parametrize("declared", ["not-a-number", "-1", "12 34", ""])
    def test_a_malformed_content_length_is_handled_without_a_server_error(
        self, client: TestClient, declared: str
    ) -> None:
        """A junk length is refused like any other probe, never a 500."""

        response = client.post(
            "/api/agent-events",
            content=b'{"event_id":"e"}',
            headers={
                "Content-Type": "application/json",
                "Content-Length": declared,
                "X-BrainBuddy-Connection": "agentconn_probe",
                "X-BrainBuddy-Timestamp": "1",
                "X-BrainBuddy-Signature": "v1=deadbeef",
            },
        )

        assert response.status_code in (400, 403, 413), response.text

    def test_an_oversize_body_changes_nothing_and_keeps_its_correlation_id(
        self, client: TestClient
    ) -> None:
        """A refused oversize event is still a traceable, zero-mutation refusal."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        stamp = int(datetime.now(tz=UTC).timestamp())
        oversize = json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "connection_id": created["id"],
                "event_id": "evt_big",
                "run_id": run["id"],
                "type": "completed",
                "run_version": 1,
                "result": "x" * (MAX_EVENT_BODY_BYTES + 1_000),
            }
        ).encode("utf-8")
        signature = hmac.new(
            created["inbound_signing_secret"].encode("utf-8"),
            f"{stamp}.".encode() + oversize,
            hashlib.sha256,
        ).hexdigest()

        response = client.post(
            "/api/agent-events",
            content=oversize,
            headers={
                "Content-Type": "application/json",
                "X-BrainBuddy-Connection": created["id"],
                "X-BrainBuddy-Timestamp": str(stamp),
                "X-BrainBuddy-Signature": f"v1={signature}",
            },
        )

        assert response.status_code == 413, response.text
        assert response.headers["X-Correlation-ID"]
        assert (
            client.get(f"/api/agent-runs/{run['id']}").json()["reported_state"] is None
        )

    def test_another_owner_cannot_read_or_command_the_run(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """Owner isolation over the run routes."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)

        assert other_client.get(f"/api/agent-runs/{run['id']}").status_code == 404
        assert (
            other_client.post(
                f"/api/agent-runs/{run['id']}/cancel",
                headers={"Idempotency-Key": "k-c"},
            ).status_code
            == 404
        )


class TestBoundedEventBodyReader:
    """The reader itself, driven at the ASGI layer.

    ``TestClient`` materialises a request body before it reaches the app, so the
    "stops reading" property can only be observed by counting how many chunks
    the *server* actually pulls off the receive channel.
    """

    @staticmethod
    def _request(
        chunks: list[bytes], *, headers: list[tuple[bytes, bytes]] | None = None
    ) -> tuple[Request, list[int]]:
        pulled: list[int] = []
        remaining = list(chunks)

        async def receive() -> dict[str, Any]:
            if not remaining:
                return {"type": "http.request", "body": b"", "more_body": False}
            chunk = remaining.pop(0)
            pulled.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": bool(remaining)}

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/agent-events",
            "headers": headers or [],
        }
        return Request(scope, receive), pulled

    def test_the_reader_stops_pulling_once_the_cap_is_passed(self) -> None:
        """A caller streaming megabytes never gets megabytes buffered."""

        chunks = [b"x" * 8_192 for _ in range(200)]
        request, pulled = self._request(chunks)

        with pytest.raises(HTTPException) as raised:
            asyncio.run(_bounded_event_body(request))

        assert raised.value.status_code == 413
        assert sum(pulled) <= MAX_EVENT_BODY_BYTES + 8_192
        assert len(pulled) < len(chunks)

    def test_a_declared_oversize_length_is_refused_without_reading(self) -> None:
        """The header alone is enough; nothing is pulled off the channel."""

        request, pulled = self._request(
            [b"x" * 8_192],
            headers=[(b"content-length", str(MAX_EVENT_BODY_BYTES + 1).encode())],
        )

        with pytest.raises(HTTPException) as raised:
            asyncio.run(_bounded_event_body(request))

        assert raised.value.status_code == 413
        assert pulled == []

    @pytest.mark.parametrize("declared", [b"not-a-number", b"-1", b"", b"1_0"])
    def test_a_malformed_declared_length_falls_back_to_the_streaming_bound(
        self, declared: bytes
    ) -> None:
        """Junk in the header neither bypasses the cap nor crashes the read."""

        request, _pulled = self._request(
            [b"x" * 16], headers=[(b"content-length", declared)]
        )

        assert asyncio.run(_bounded_event_body(request)) == b"x" * 16

    def test_a_body_of_exactly_the_cap_is_returned_whole(self) -> None:
        """The boundary is inclusive: exactly the cap is still a valid body."""

        request, _pulled = self._request([b"x" * MAX_EVENT_BODY_BYTES])

        assert asyncio.run(_bounded_event_body(request)) == b"x" * MAX_EVENT_BODY_BYTES


class TestRunSummaryRoute:
    def test_the_compact_surface_gets_one_summary_per_task(
        self, client: TestClient
    ) -> None:
        """FR-010: the task list asks once for every task's latest run."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        other_task_id = create_task(client, "Untouched task")
        run = hand_off(client, created["id"], task_id)

        response = client.get(
            "/api/agent-run-summaries",
            params={"task_id": [task_id, other_task_id]},
        )

        assert response.status_code == 200, response.text
        summaries = response.json()
        assert list(summaries) == [task_id]
        assert summaries[task_id]["id"] == run["id"]
        assert summaries[task_id]["primary_state_label"] == "Sent"
        assert summaries[task_id]["needs_user"] is False

    def test_summaries_never_cross_owners(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        """A task ID guessed from another account yields nothing."""

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        hand_off(client, created["id"], task_id)

        response = other_client.get(
            "/api/agent-run-summaries", params={"task_id": [task_id]}
        )

        assert response.status_code == 200
        assert response.json() == {}

    def test_asking_for_no_tasks_is_an_empty_answer(self, client: TestClient) -> None:
        """An empty list page must not become an unbounded scan."""

        assert client.get("/api/agent-run-summaries").json() == {}


class TestAccountPurge:
    def test_account_purge_removes_every_relay_record(
        self, client: TestClient, relay_app: tuple[Any, ...]
    ) -> None:
        """AC-021: the existing purge contract covers relay data."""

        container: Container = relay_app[3]
        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        hand_off(client, created["id"], task_id)

        owner_id = client.get("/api/auth/me").json()["id"]
        container.account_service.purge_account(owner_id)

        assert container.agent_repo.list_connections(owner_id=owner_id) == []
        assert container.agent_repo.list_runs_for_owner(owner_id=owner_id) == []
        assert container.agent_repo.list_audit(owner_id=owner_id) == []


class TestOpenApiContract:
    def test_no_schema_can_carry_a_stored_credential_outward(
        self, client: TestClient
    ) -> None:
        """FR-003 is enforced structurally, not by discipline."""

        schema = client.get("/api/openapi.json").json()
        responses = json.dumps(schema["components"]["schemas"])

        assert "AgentConnectionResponse" in responses
        connection_schema = schema["components"]["schemas"]["AgentConnectionResponse"]
        assert "credential" not in connection_schema["properties"]
        assert "inbound_secret" not in connection_schema["properties"]
