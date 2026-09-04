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
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.api.agents import MAX_EVENT_BODY_BYTES, _bounded_event_body, _verify_password
from app.container import Container
from app.core import get_config
from app.core.config import FeatureFlagState
from app.core.rate_limit import sensitive_action_rate_limiter
from app.main import _run_privacy_maintenance_sweep, create_app
from app.modules.agents import service as agent_service_module
from app.modules.agents.a2a.card import (
    MAX_CARD_DESCRIPTION_CHARS,
    CardDiscovery,
)
from app.modules.agents.connector import (
    ConnectorCommandOutcome,
    ConnectorStartOutcome,
    ConnectorTarget,
    ConnectorTestOutcome,
)
from app.modules.agents.domain import PROTOCOL_VERSION, AgentCapabilities
from app.repositories.feature_flag import FlagMode
from app.schemas.auth import Invite, User
from app.services.auth_service import AuthService
from app.utils.time import utcnow

from .a2a_fakes import (
    A2AResult,
    FakeA2AClient,
    FakeCardFetcher,
    card_summary,
    ready_discovery,
)
from .conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD

SECOND_EMAIL = "second-relay@example.com"
SECOND_PASSWORD = "another-horse-battery-staple"
ENDPOINT = "https://agent.example.com"


def test_sensitive_reauthentication_rejects_a_missing_password_before_rate_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing proof fails closed without consuming the owner's attempt budget."""

    monkeypatch.setattr(
        sensitive_action_rate_limiter,
        "check",
        lambda _owner_id: pytest.fail("missing passwords must not consume attempts"),
    )

    auth_service = cast(AuthService, object())
    user = cast(User, type("UserStub", (), {"id": "owner-a"})())

    assert _verify_password(auth_service, user, None) is False


def test_sensitive_reauthentication_reports_rate_limit_before_password_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted owner cannot spend verification work or learn password validity."""

    monkeypatch.setattr(sensitive_action_rate_limiter, "check", lambda _owner_id: False)
    auth_service = cast(
        AuthService,
        type(
            "AuthService",
            (),
            {"verify_password": lambda *_args: pytest.fail("rate limit must win")},
        )(),
    )
    user = cast(User, type("UserStub", (), {"id": "owner-a"})())

    with pytest.raises(HTTPException) as excinfo:
        _verify_password(
            auth_service,
            user,
            "candidate-password",
        )

    assert excinfo.value.status_code == 429
    assert excinfo.value.detail == "Too many attempts. Try again later."


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
    return {
        "agent.example.com": ["93.184.216.34"],
        "second.example.com": ["93.184.216.35"],
    }[host]


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
    # Discovery and the A2A wire are scripted in-process: the HTTP contract is
    # what these tests are about, and a real socket would make them a network
    # test that happens to exercise routing.
    container.agent_relay_service._card_fetcher = FakeCardFetcher()
    container.agent_relay_service.a2a_client = FakeA2AClient()

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


def register_connection(client: TestClient, *, key: str = "k-create") -> dict[str, Any]:
    """The registration response exactly as the route returns it (no secret)."""

    response = client.post(
        "/api/agent-connections",
        headers={"Idempotency-Key": key},
        json={
            "name": "Hermes",
            "agent_address": ENDPOINT,
            "credential": "Bearer super-secret-token",
            "current_password": TEST_USER_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_connection(client: TestClient, *, key: str = "k-create") -> dict[str, Any]:
    """A registered connection *plus* a usable bespoke signing secret.

    Registration issues no secret under the A2A wire (014 FR-012), so the 007
    inbound-event suites — which still need one until T110–T114 delete that
    surface — take it from the rotation route, the only place it is ever shown.
    The returned body is the connection as it stands after that rotation, so a
    caller's `revision` is the real one.
    """

    created = register_connection(client, key=key)
    rotated = client.post(
        f"/api/agent-connections/{created['id']}/signing-secret",
        headers={"Idempotency-Key": f"{key}-signing"},
        json={
            "current_password": TEST_USER_PASSWORD,
            "expected_revision": created["revision"],
        },
    )
    assert rotated.status_code == 200, rotated.text
    return dict(rotated.json())


def create_task(client: TestClient, title: str = "Draft the migration plan") -> str:
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": f"task-{title}"},
        json={"title": title, "details": "Cover rollback.", "state": "next"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def hand_off(
    client: TestClient,
    connection_id: str,
    task_id: str,
    *,
    key: str = "k-dispatch",
    acknowledge: bool = True,
) -> dict[str, Any]:
    """One review and the confirmation it authorises.

    The default acknowledges the duplicate risk because every fixture connection
    here is best-effort and a real client would have shown the box; the suites
    that assert the *gate* pass `acknowledge=False` explicitly (AC-026).
    """

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
            "acknowledge_duplicate_risk": acknowledge,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def set_relay_flag(client: TestClient, state: FeatureFlagState) -> None:
    """Flip the runtime-owned `external_agent_relay` flag through the same
    SQLite-backed service request-time gating consults (ADR-0019) — `config`
    no longer holds any runtime authority for a managed flag to override."""

    app: Any = client.app
    container: Container = app.state.container
    container.feature_flag_service.set_mode(
        "external_agent_relay", FlagMode(state.value), operator_id="test-harness"
    )


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

    def test_rollout_off_preserves_reads_but_blocks_new_connections(
        self, api_client: TestClient
    ) -> None:
        """FR-019: rollback keeps owner visibility while blocking fresh work."""

        assert api_client.get("/api/agent-connections").status_code == 200
        response = api_client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "off-create"},
            json={},
        )
        assert response.status_code == 404

    def test_rollout_off_allows_owner_to_disconnect_and_destroy_secrets(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        created = create_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        response = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "disconnect-while-off"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "disconnected"
        replay = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "disconnect-while-off"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["revision"] == response.json()["revision"]
        stored = relay_app[3].agent_repo.get_connection(
            created["id"], owner_id=client.get("/api/account").json()["id"]
        )
        assert stored.credential is None
        assert stored.inbound_secret is None

    def test_rollout_off_disconnect_preserves_owner_password_revision_and_key_checks(
        self, client: TestClient, other_client: TestClient
    ) -> None:
        created = create_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        wrong_owner = other_client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-other"},
            json={
                "current_password": SECOND_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        bad_password = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-password"},
            json={
                "current_password": "not-the-password",
                "expected_revision": created["revision"],
            },
        )
        bad_revision = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect-revision"},
            json={"current_password": TEST_USER_PASSWORD, "expected_revision": 99},
        )
        missing_key = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )

        assert wrong_owner.status_code == 404
        assert bad_password.status_code == 403
        assert bad_revision.status_code == 409
        assert missing_key.status_code == 400
        assert (
            client.get(f"/api/agent-connections/{created['id']}").json()["status"]
            == "untested"
        )

    def test_rollout_off_keeps_every_dispatch_enabling_mutation_closed(
        self, client: TestClient
    ) -> None:
        created = create_connection(client)
        task_id = create_task(client, "Blocked while rollout is off")
        set_relay_flag(client, FeatureFlagState.OFF)

        requests = (
            client.post(
                "/api/agent-connections",
                headers={"Idempotency-Key": "off-create-again"},
                json={
                    "name": "Other",
                    "agent_address": ENDPOINT,
                    "credential": "Bearer other",
                    "current_password": TEST_USER_PASSWORD,
                },
            ),
            client.post(f"/api/agent-connections/{created['id']}/test"),
            client.post(
                f"/api/agent-connections/{created['id']}/credential",
                headers={"Idempotency-Key": "off-credential"},
                json={
                    "credential": "Bearer replacement",
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": created["revision"],
                },
            ),
            client.post(
                f"/api/agent-connections/{created['id']}/signing-secret",
                headers={"Idempotency-Key": "off-signing-secret"},
                json={
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": created["revision"],
                },
            ),
            client.post(
                f"/api/tasks/{task_id}/agent-runs/preview",
                json={"connection_id": created["id"]},
            ),
            client.post(
                f"/api/tasks/{task_id}/agent-runs",
                headers={"Idempotency-Key": "off-fresh-dispatch"},
                json={
                    "connection_id": created["id"],
                    "manifest_token": "a" * 64,
                },
            ),
        )

        assert [response.status_code for response in requests] == [404] * len(requests)

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
    def test_updates_name_or_destination_without_returning_secrets(
        self, client: TestClient
    ) -> None:
        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        current = client.get(f"/api/agent-connections/{created['id']}").json()

        renamed = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "update-name"},
            json={"name": "Renamed", "expected_revision": current["revision"]},
        )
        moved = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "update-destination"},
            json={
                "agent_address": "https://second.example.com",
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": renamed.json()["revision"],
            },
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["status"] == "ready"
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == "untested"
        assert "credential" not in moved.json()
        assert "inbound_signing_secret" not in moved.json()

    def test_rollout_off_blocks_connection_update(self, client: TestClient) -> None:
        created = create_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        response = client.put(
            f"/api/agent-connections/{created['id']}",
            headers={"Idempotency-Key": "off-update"},
            json={"name": "Cannot enable", "expected_revision": created["revision"]},
        )

        assert response.status_code == 404

    def test_014_FR_012_creating_a_connection_returns_no_secret_at_all(
        self, client: TestClient
    ) -> None:
        """AC-019, 014-FR-012: neither the credential nor any inbound secret.

        007's 201 carried a signing secret the owner had to copy into their
        agent. The A2A wire has none, so the safest registration response is one
        whose schema cannot hold a secret in the first place.
        """

        created = register_connection(client)

        assert created["status"] == "untested"
        assert created["auth_scheme"] == "bearer"
        assert created["agent_address"] == ENDPOINT
        assert "inbound_signing_secret" not in created
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
                "agent_address": ENDPOINT,
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
                "agent_address": ENDPOINT,
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
                "agent_address": ENDPOINT,
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
                "agent_address": ENDPOINT,
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
                "agent_address": ENDPOINT,
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
                "agent_address": endpoint,
                "credential": "Bearer token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 400
        assert client.get("/api/agent-connections").json() == []

    def test_014_FR_002_testing_reports_the_discovery_result_and_the_tier(
        self, client: TestClient
    ) -> None:
        """AC-001, AC-005 over HTTP. Two separate claims, kept separate.

        `capabilities` is what the *card* declared; `controls_offered` is what
        BrainBuddy offers on this connection's runs. A single blended object
        would let a product decision be read as an agent's promise.
        """

        created = create_connection(client)

        response = client.post(f"/api/agent-connections/{created['id']}/test")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["ready_for_handoff"] is True
        assert body["capabilities"] == {"streaming": True, "push_notifications": False}
        assert body["controls_offered"] == {"reply": True, "cancel": True}
        assert body["guarantee_tier"] == "best_effort"
        assert body["tier_disclosure"].startswith("Best-effort single start.")
        assert body["tier_disclosure_url"]
        assert body["cancellation_disclosure"].startswith(
            "Cancellation depends on the agent"
        )
        assert body["agent_changed"] is False
        assert body["correlation_id_honoured"] is None
        assert body["disconnect_reason"] is None
        assert body["last_test_error_detail"] is None
        assert body["auth_header_name"] is None
        assert body["card"]["interface_url"] == "https://agent.example.com/a2a"

    def test_014_FR_001_the_create_route_rejects_a_caller_supplied_header_name(
        self, client: TestClient
    ) -> None:
        """AC-002. The header a credential travels in comes from the card only."""

        response = client.post(
            "/api/agent-connections",
            headers={"Idempotency-Key": "k-header-name"},
            json={
                "name": "Hermes",
                "agent_address": ENDPOINT,
                "auth_scheme": "api_key",
                "auth_header_name": "X-API-Key",
                "credential": "Bearer super-secret-token",
                "current_password": TEST_USER_PASSWORD,
            },
        )

        assert response.status_code == 422, response.text
        assert "auth_header_name" in response.text
        assert client.get("/api/agent-connections").json() == []

    def test_card_text_is_returned_verbatim_and_bounded(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-031. Card text is returned exactly as the agent wrote it.

        Not escaped, not stripped, not linkified: escaping here would hide what
        the agent actually claims, and the clients are the layer that renders it
        inertly. The bound is the only processing it receives.
        """

        container = relay_app[3]
        hostile = "<script>alert(1)</script> **not markdown** [x](javascript:alert(2))"
        fetcher = FakeCardFetcher()
        fetcher.discovery = ready_discovery(
            summary=card_summary(
                name=hostile,
                description=hostile * 8,
                interface_url="javascript:alert(3)",
            )
        )
        container.agent_relay_service._card_fetcher = fetcher
        created = create_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()

        card = body["card"]
        assert card["name"] == hostile
        assert card["description"] == hostile * 8
        assert len(card["description"]) <= MAX_CARD_DESCRIPTION_CHARS
        assert card["interface_url"] == "javascript:alert(3)"

    def test_014_FR_002_a_rate_limited_test_stays_untested_with_its_retry_hint(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-037, D-01-S25 over HTTP: never `ready`, and never a hand-off."""

        container = relay_app[3]
        a2a_client = FakeA2AClient()
        a2a_client.script(
            "ListTasks",
            A2AResult(
                ok=False,
                correlation_id="c",
                error_code="a2a_rate_limited",
                http_status=429,
                retry_after_seconds=30,
            ),
        )
        container.agent_relay_service.a2a_client = a2a_client
        created = create_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()

        assert body["status"] == "untested"
        assert body["ready_for_handoff"] is False
        assert body["last_test_error_code"] == "a2a_rate_limited"
        assert body["last_test_error_detail"] == {"retry_after_seconds": 30}

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "a2a_rate_limited"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_002_a_changed_agent_refuses_the_hand_off_by_name(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-012, D-01-S20 over HTTP."""

        container = relay_app[3]
        fetcher = FakeCardFetcher()
        container.agent_relay_service._card_fetcher = fetcher
        created = create_connection(client)
        assert (
            client.post(f"/api/agent-connections/{created['id']}/test").json()["status"]
            == "ready"
        )

        fetcher.discovery = ready_discovery(
            summary=card_summary(interface_url="https://second.example.com/a2a")
        )
        drifted = client.post(f"/api/agent-connections/{created['id']}/test").json()

        assert drifted["status"] == "untested"
        assert drifted["agent_changed"] is True
        assert drifted["last_test_error_code"] == "agent_card_changed"
        assert drifted["last_test_error_detail"] == {
            "interface_url": "https://second.example.com/a2a"
        }

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "agent_card_changed"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_001_an_unsupported_card_scheme_is_named_on_the_refusal(
        self,
        client: TestClient,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """AC-004. The owner is told which scheme their card demands."""

        container = relay_app[3]
        fetcher = FakeCardFetcher()
        fetcher.discovery = CardDiscovery(
            failure_code="a2a_auth_scheme_unsupported",
            failure_detail={"scheme": "oauth2"},
        )
        container.agent_relay_service._card_fetcher = fetcher
        created = create_connection(client)

        body = client.post(f"/api/agent-connections/{created['id']}/test").json()
        assert body["status"] == "unsupported"
        assert body["last_test_error_detail"] == {"scheme": "oauth2"}

        task_id = create_task(client)
        refused = client.post(
            f"/api/tasks/{task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["reason"] == "a2a_auth_scheme_unsupported"
        assert refused.headers["X-Correlation-ID"]

    def test_014_FR_016_rollout_off_blocks_every_connection_write_but_disconnect(
        self, client: TestClient
    ) -> None:
        """D-01-S22, 014-FR-016. Disconnect stays: it only ever destroys."""

        created = create_connection(client)
        set_relay_flag(client, FeatureFlagState.OFF)

        blocked = {
            "create": client.post(
                "/api/agent-connections",
                headers={"Idempotency-Key": "off-create-2"},
                json={
                    "name": "Second",
                    "agent_address": ENDPOINT,
                    "credential": "Bearer other",
                    "current_password": TEST_USER_PASSWORD,
                },
            ),
            "update": client.put(
                f"/api/agent-connections/{created['id']}",
                headers={"Idempotency-Key": "off-update-2"},
                json={"name": "Renamed", "expected_revision": created["revision"]},
            ),
            "test": client.post(f"/api/agent-connections/{created['id']}/test"),
            "credential": client.post(
                f"/api/agent-connections/{created['id']}/credential",
                headers={"Idempotency-Key": "off-credential"},
                json={
                    "credential": "Bearer replacement",
                    "current_password": TEST_USER_PASSWORD,
                    "expected_revision": created["revision"],
                },
            ),
        }
        for name, response in blocked.items():
            assert response.status_code == 404, f"{name}: {response.text}"

        assert client.get("/api/agent-connections").status_code == 200
        disconnected = client.post(
            f"/api/agent-connections/{created['id']}/disconnect",
            headers={"Idempotency-Key": "off-disconnect"},
            json={
                "current_password": TEST_USER_PASSWORD,
                "expected_revision": created["revision"],
            },
        )
        assert disconnected.status_code == 200, disconnected.text
        assert disconnected.json()["status"] == "disconnected"
        assert disconnected.json()["disconnect_reason"] == "owner"

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
        revision: int | None = None,
        password: str = TEST_USER_PASSWORD,
    ) -> Any:
        if revision is None:
            revision = client.get(f"/api/agent-connections/{connection_id}").json()[
                "revision"
            ]
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
                "supporting_items": [{"label": "Runbook", "body": "Step one"}],
            },
        ).json()

        assert preview["title"] == "Draft the migration plan"
        assert preview["details"] == "Cover rollback."
        assert preview["supporting_items"] == [{"label": "Runbook", "body": "Step one"}]
        assert preview["destination_interface"] == "https://agent.example.com/a2a"
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

    def test_rollout_off_preserves_existing_run_control_and_reporting(
        self,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """FR-019 blocks new work without abandoning an already-dispatched run."""

        client, _, _, _ = relay_app
        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        fresh_task_id = create_task(client, "Fresh rollout dispatch")
        fresh_preview = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        ).json()

        set_relay_flag(client, FeatureFlagState.OFF)

        callback = self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_after_off",
                "run_id": run["id"],
                "type": "blocked",
                "run_version": 1,
                "question": "Which environment?",
            },
        )
        assert callback.status_code == 202

        current = client.get(f"/api/agent-runs/{run['id']}")
        assert current.status_code == 200
        reply = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "reply-after-off"},
            json={
                "message": "Use staging.",
                "expected_revision": current.json()["revision"],
            },
        )
        assert reply.status_code == 200
        cancel = client.post(
            f"/api/agent-runs/{run['id']}/cancel",
            headers={"Idempotency-Key": "cancel-after-off"},
        )
        assert cancel.status_code == 200
        assert client.get("/api/agent-connections").status_code == 200

        fresh_preview_response = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs/preview",
            json={"connection_id": created["id"]},
        )
        fresh_dispatch_response = client.post(
            f"/api/tasks/{fresh_task_id}/agent-runs",
            headers={"Idempotency-Key": "fresh-after-off"},
            json={
                "connection_id": created["id"],
                "manifest_token": fresh_preview["token"],
            },
        )
        assert fresh_preview_response.status_code == 404
        assert fresh_dispatch_response.status_code == 404

    def test_rollout_off_keeps_retention_maintenance_active_without_resurrection(
        self,
        relay_app: tuple[TestClient, TestClient, FakeConnector, Container],
    ) -> None:
        """FR-019: OFF cannot suspend expiry of already-relayed content."""

        client, _, _, container = relay_app
        created = create_connection(client, key="retention-off-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, "Retention while rollout is off")
        run = hand_off(client, created["id"], task_id, key="retention-off-dispatch")
        callback = self._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_retention_off",
                "run_id": run["id"],
                "type": "blocked",
                "run_version": 1,
                "question": "Sensitive retained question?",
            },
        )
        assert callback.status_code == 202
        current = client.get(f"/api/agent-runs/{run['id']}").json()
        reply = client.post(
            f"/api/agent-runs/{run['id']}/reply",
            headers={"Idempotency-Key": "retention-off-reply"},
            json={
                "message": "Sensitive retained reply",
                "expected_revision": current["revision"],
            },
        )
        assert reply.status_code == 200, reply.text

        stored = container.agent_repo.get_run(
            run["id"], owner_id=client.get("/api/auth/me").json()["id"]
        )
        due = datetime.now(tz=UTC)
        container.agent_repo.save_run(
            stored.model_copy(update={"content_expires_at": due})
        )
        container.agent_relay_service._now = lambda: due + timedelta(seconds=1)
        set_relay_flag(client, FeatureFlagState.OFF)

        assert _run_privacy_maintenance_sweep(container)[1] == 1
        expired = container.agent_relay_service.get_run(
            run["id"], owner_id=stored.owner_id
        )
        assert expired.content_expired is True
        assert expired.manifest is None
        assert expired.question_text is None
        assert expired.events and all(event.summary is None for event in expired.events)
        assert expired.commands and all(
            command.body is None for command in expired.commands
        )

        assert _run_privacy_maintenance_sweep(container)[1] == 0
        unchanged = container.agent_relay_service.get_run(
            run["id"], owner_id=stored.owner_id
        )
        assert unchanged == expired

    def test_the_bespoke_ingest_route_still_accepts_a_correctly_signed_event(
        self, client: TestClient, connector: FakeConnector
    ) -> None:
        """The 007 route works; 014 simply stopped advertising it.

        The manifest's `reporting` block is now an inert rollback placeholder
        with an empty callback URL — no agent is told about this route any more,
        because an A2A agent reports by answering. The route itself lives until
        T110-T114 remove it with the rest of the bespoke wire, and a run
        dispatched before that must still be able to report, so its signing
        contract is exercised here against the route directly.
        """

        created = create_connection(client)
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client)
        run = hand_off(client, created["id"], task_id)
        reporting = connector.starts[-1]["reporting"]
        assert reporting["callback_url"] == "", "the manifest advertises nothing"
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
            "/api/agent-events",
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
        # The manifest advertises no address any more (014 FR-012); the route
        # stays until T110-T114, and this vector still pins its signing rule.
        assert reporting["callback_url"] == ""

        response = client.post(
            "/api/agent-events",
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

    def test_rollout_off_keeps_account_purge_complete_for_all_relay_material(
        self, client: TestClient, relay_app: tuple[Any, ...]
    ) -> None:
        """FR-019: OFF cannot strand any owner relay or credential material."""

        container: Container = relay_app[3]
        created = create_connection(client, key="purge-off-create")
        client.post(f"/api/agent-connections/{created['id']}/test")
        task_id = create_task(client, "Purge relay data while rollout is off")
        run = hand_off(client, created["id"], task_id, key="purge-off-dispatch")
        callback = TestEventIngestRoutes()._emit(
            client,
            connection_id=created["id"],
            secret=created["inbound_signing_secret"],
            payload={
                "event_id": "evt_purge_off",
                "run_id": run["id"],
                "type": "running",
                "run_version": 1,
                "progress": "Sensitive purge content",
            },
        )
        assert callback.status_code == 202
        owner_id = client.get("/api/auth/me").json()["id"]
        relay_tables = (
            "agent_connections",
            "agent_runs",
            "agent_run_events",
            "agent_run_commands",
            "agent_audit",
            "agent_event_ids",
            "agent_idempotency",
        )
        with sqlite3.connect(container.agent_repo.db_path) as connection:
            assert all(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
                ).fetchone()[0]
                for table in relay_tables
            )
            stored_connection = connection.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()[0]
        assert created["inbound_signing_secret"] not in stored_connection
        assert '"credential":' in stored_connection
        assert '"inbound_secret":' in stored_connection

        set_relay_flag(client, FeatureFlagState.OFF)
        container.account_service.purge_account(owner_id)

        with sqlite3.connect(container.agent_repo.db_path) as connection:
            assert all(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id = ?", (owner_id,)
                ).fetchone()[0]
                == 0
                for table in relay_tables
            )


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


class TestPushCallbackInfrastructure:
    """The two things that must exist before the push route can be safe.

    The A2A push token travels in the URL path — not because that is pleasant,
    but because Hermes stores only the URL of a push config and signs with a
    secret BrainBuddy cannot know, so a header-only token would leave its
    pushes unverifiable (research.md Decision D). That choice is only
    acceptable with two properties actually in place:

    1. **The token never reaches BrainBuddy's own logs.** An agent's logs are
       outside our control and the token's power is bounded by design — it can
       trigger one authenticated observation BrainBuddy would perform anyway —
       but repeating it in our own logs would be a disclosure we chose.
    2. **Limiter memory is bounded.** The route is reachable by anyone who
       guesses a URL shape, so a per-run limiter that never evicts is a remote
       memory-growth primitive.

    014-FR-008, 014-FR-016, 014-SC-009.
    """

    # --- the bounded limiter ------------------------------------------------

    def test_014_FR_008_the_bounded_limiter_never_grows_past_its_key_cap(self) -> None:
        """AC-035: unknown ids must not be able to mint keys without bound.

        `InMemoryRateLimiter` is a `defaultdict` whose `_prune` only trims
        timestamps *inside* a key, so it never forgets a key at all. On a login
        route keyed by source IP that is a considered trade; on a route keyed by
        a caller-supplied run id it is unbounded growth driven by a stranger.
        """

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(
            max_attempts=30, window_seconds=60.0, max_keys=8
        )

        for index in range(500):
            limiter.check(f"run-{index}")

        assert limiter.key_count <= 8

    def test_014_FR_008_a_runs_bucket_is_evicted_when_the_run_closes(self) -> None:
        """A terminal or disconnected run can never be pushed for again, so
        keeping its bucket is pure retention of something with no use."""

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(
            max_attempts=2, window_seconds=60.0, max_keys=64
        )

        assert limiter.check("run-a") is True
        assert limiter.check("run-a") is True
        assert limiter.check("run-a") is False, "the window is exhausted"

        assert limiter.evict("run-a") is True
        assert limiter.key_count == 0
        # Eviction is not a bypass: a fresh key starts a fresh window, and the
        # route only evicts when the run can no longer be pushed for at all.
        assert limiter.check("run-a") is True
        assert limiter.evict("never-seen") is False

    def test_014_FR_008_eviction_under_pressure_drops_the_oldest_key(self) -> None:
        """When the cap is reached the limiter must still admit new runs.

        Refusing every new key at the cap would let one flood of stale ids
        deny push acceleration to every legitimate run — the limiter would
        become the outage it exists to prevent.
        """

        from app.core.rate_limit import BoundedKeyRateLimiter

        limiter = BoundedKeyRateLimiter(max_attempts=1, window_seconds=60.0, max_keys=2)

        limiter.check("first")
        limiter.check("second")
        limiter.check("third")

        assert limiter.key_count == 2
        # "first" was displaced, so it is admitted again as a new key rather
        # than silently refused forever.
        assert limiter.check("first") is True

    def test_014_FR_008_the_shared_login_limiter_is_left_alone(self) -> None:
        """The bounded variant is additive. `InMemoryRateLimiter` guards login
        and the sensitive account actions, and changing its eviction semantics
        under them would be a security change made by accident."""

        from app.core.rate_limit import InMemoryRateLimiter

        assert not hasattr(InMemoryRateLimiter, "evict")
        assert not hasattr(InMemoryRateLimiter, "key_count")

    def test_014_FR_008_a_fixed_size_counter_bounds_the_route_before_any_read(
        self,
    ) -> None:
        """Step 2 of the check order: a process-wide counter with no per-key
        state at all, consulted before the database is touched. Rejections of
        unknown ids are counted only here — never per unknown id, which would
        reintroduce the growth the cap above removes."""

        from app.core.rate_limit import FixedWindowCounter

        counter = FixedWindowCounter(max_events=3, window_seconds=60.0)

        assert [counter.check() for _ in range(4)] == [True, True, True, False]
        assert counter.rejected == 1

    # --- path redaction -----------------------------------------------------

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (
                "/api/a2a/push/run-123/tok-abcdef",
                "/api/a2a/push/run-123/[redacted]",
            ),
            (
                "/api/a2a/push/run-123/tok-abcdef/extra",
                "/api/a2a/push/run-123/[redacted]",
            ),
            # No token segment yet: nothing to hide, and inventing one would
            # make a 404 look like a redacted hit.
            ("/api/a2a/push/run-123", "/api/a2a/push/run-123"),
            ("/api/a2a/push/", "/api/a2a/push/"),
            ("/api/a2a/push", "/api/a2a/push"),
            # Unrelated paths are untouched: over-redaction destroys the
            # operational value of the log without adding safety.
            ("/api/agent-runs/run-1", "/api/agent-runs/run-1"),
            ("/api/tasks", "/api/tasks"),
            ("/", "/"),
        ],
    )
    def test_014_SC_009_the_path_sanitiser_hides_the_token_and_nothing_else(
        self, path: str, expected: str
    ) -> None:
        """AC-035: the run id stays visible because it is what makes a log line
        useful for support; the token is the only secret in the path."""

        from app.api.middleware import sanitize_log_path

        assert sanitize_log_path(path, api_prefix="/api") == expected

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "not-a-path",
            "//////",
            "/api/a2a/push//",
            "/api/a2a/push/%00/%00",
            "?" * 50,
        ],
    )
    def test_014_SC_009_the_path_sanitiser_never_raises(self, path: str) -> None:
        """It runs inside a logging call on the request's exception path. A
        sanitiser that could raise would turn a redaction into a 500 — and
        would do it exactly when something has already gone wrong."""

        from app.api.middleware import sanitize_log_path

        assert isinstance(sanitize_log_path(path, api_prefix="/api"), str)

    def test_014_SC_009_a_custom_api_prefix_is_still_redacted(self) -> None:
        """The prefix is configurable, and a redaction keyed to a hard-coded
        `/api` would silently stop working on a deployment that changed it."""

        from app.api.middleware import sanitize_log_path

        assert (
            sanitize_log_path("/custom/a2a/push/run-1/tok", api_prefix="/custom")
            == "/custom/a2a/push/run-1/[redacted]"
        )

    def test_014_SC_009_both_middleware_log_lines_go_through_the_sanitiser(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`api_request` *and* `api_request_failed`.

        Driven through the real middleware rather than asserted against its
        source, so the property proved is what actually reaches a log handler.
        The exception line is the one most likely to be forgotten and the one
        most likely to be read, because it fires when a push went wrong —
        exactly when someone pastes the line into a ticket.
        """

        import logging

        from fastapi import FastAPI

        from app.api.middleware import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware, api_prefix="/api")

        @app.post("/api/a2a/push/{run_id}/{token}")
        async def _ok(run_id: str, token: str) -> dict[str, str]:
            return {"run_id": run_id}

        @app.post("/api/a2a/push/boom/{token}/fail")
        async def _boom(token: str) -> dict[str, str]:
            raise RuntimeError("the push handler exploded")

        secret = "tok-never-log-this"
        with caplog.at_level(logging.INFO, logger="app.api.middleware"):
            client = TestClient(app, raise_server_exceptions=False)
            client.post(f"/api/a2a/push/run-1/{secret}")
            client.post(f"/api/a2a/push/boom/{secret}/fail")

        # Scoped to BrainBuddy's own loggers, which is exactly what SC-009
        # claims: the two in-process edges. `TestClient` drives httpx, whose
        # client-side logger prints the URL it is calling — a property of the
        # test harness standing in for the network, not of anything the server
        # writes. Asserting over it would be asserting about the test.
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("app.")
        ]
        assert any("api_request " in message for message in messages)
        assert any("api_request_failed" in message for message in messages)
        assert not any(
            secret in message for message in messages
        ), "one unsanitised log call is a full disclosure of the push token"
        assert any("/api/a2a/push/run-1/[redacted]" in message for message in messages)
        # The run id survives: it is what makes the line useful, and it is not
        # the secret.
        assert any("/api/a2a/push/boom/[redacted]" in message for message in messages)

    def test_014_SC_009_the_uvicorn_access_filter_redacts_the_push_path(self) -> None:
        """uvicorn writes its own access line, below the middleware.

        BrainBuddy's log configuration routes `uvicorn.access` to the same
        console handler, so a token redacted by the middleware would still be
        printed verbatim one line later without this filter.
        """

        import logging

        from app.core.logging import PushCallbackAccessFilter

        log_filter = PushCallbackAccessFilter(api_prefix="/api")

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "POST", "/api/a2a/push/run-1/tok-secret", "1.1", 204),
            exc_info=None,
        )

        assert log_filter.filter(record) is True
        assert "tok-secret" not in record.getMessage()
        assert "/api/a2a/push/run-1/[redacted]" in record.getMessage()

    def test_014_SC_009_the_access_filter_leaves_other_paths_alone(self) -> None:
        import logging

        from app.core.logging import PushCallbackAccessFilter

        log_filter = PushCallbackAccessFilter(api_prefix="/api")
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "GET", "/api/tasks", "1.1", 200),
            exc_info=None,
        )

        assert log_filter.filter(record) is True
        assert "/api/tasks" in record.getMessage()

    @pytest.mark.parametrize(
        "args",
        [
            None,
            (),
            ("only-one",),
            ("a", "b", 12345, "d", 200),
            "a bare string",
        ],
    )
    def test_014_SC_009_the_access_filter_never_raises_on_an_odd_record(
        self, args: Any
    ) -> None:
        """A logging filter that raises takes down the log, and uvicorn's record
        shape is not something BrainBuddy controls across versions."""

        import logging

        from app.core.logging import PushCallbackAccessFilter

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="%s",
            args=args,
            exc_info=None,
        )

        assert PushCallbackAccessFilter(api_prefix="/api").filter(record) is True

    def test_014_SC_009_the_access_filter_is_installed_on_the_uvicorn_logger(
        self,
    ) -> None:
        """A filter nobody attaches redacts nothing.

        The logging dict is where `uvicorn.access` is wired to the console
        handler, so it is also where the filter has to appear.
        """

        from app.core.logging import build_logging_dict

        config = build_logging_dict("INFO")

        assert "push_callback" in config["filters"]
        assert "push_callback" in config["loggers"]["uvicorn.access"].get("filters", [])
